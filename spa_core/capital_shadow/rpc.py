"""spa_core/capital_shadow/rpc.py — allow-listed, no-signing JSON-RPC client with a witness quorum.

ADR-556 WP-S02/S03 + the binding architecture-review revision (point 3, point 13): the AI side of
``capital_shadow`` may only READ the chain. This client:

* refuses every method outside :data:`contract.RPC_ALLOWED_METHODS` — exact, case-sensitive match —
  and any non-list ``params`` (which also catches a batch array smuggled in as ``params``) BEFORE any
  network I/O, and records the refusal as a security event (review #13: "a forbidden-method attempt is
  a SECURITY incident, not only an exception");
* pins a block by asking ``eth_blockNumber`` of every declared operator and requiring independent
  agreement (review #3), then asks ``eth_getBlockByNumber`` and requires independent agreement on the
  block hash;
* answers a read (``quorum``) only when >= ``contract.RPC_MIN_INDEPENDENT_OPERATORS`` distinct operators
  return the identical result (or the identical revert) at the SAME pinned block; disagreement is itself
  a security-relevant signal (recorded, never silently resolved by "pick one").

Only this module may import ``urllib`` / ``http`` / ``socket`` / ``ssl`` (review #13). No key, no
signing, no ``eth_sendRawTransaction``/``eth_sendTransaction``/``eth_sign``/``personal_sign`` path exists
here — the allow-list makes that impossible by construction, not by discipline.

# LLM_FORBIDDEN — every refusal and every quorum verdict is deterministic.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.request
from typing import Any, Callable, Optional

from spa_core.capital_shadow import contract

Post = Callable[[str, dict], dict]

#: where the block tag is inserted into params_without_block (review #3's quorum shapes)
_BLOCK_PARAM_INDEX = {"eth_call": 1, "eth_estimateGas": 1, "eth_getCode": 1}
_UA = {"Content-Type": "application/json", "User-Agent": "spa-capital-shadow/1.0"}


class ForbiddenMethod(Exception):
    """Raised BEFORE any network I/O for a method outside the allow-list, a non-list ``params``, or a batch."""


def _is_revert(error_obj: Any) -> bool:
    if not isinstance(error_obj, dict):
        return False
    if error_obj.get("code") == 3:
        return True
    return "execution reverted" in str(error_obj.get("message", "")).lower()


def _revert_key(error_obj: dict) -> str:
    data = error_obj.get("data")
    if isinstance(data, str):
        return data
    return str(error_obj.get("message", "revert"))


def _params_with_block(method: str, params_without_block: list, block_number) -> list:
    params = list(params_without_block)
    if block_number is None:
        return params
    block_hex = block_number if isinstance(block_number, str) else hex(int(block_number))
    idx = _BLOCK_PARAM_INDEX.get(method)
    if idx is None:
        return params + [block_hex]
    params.insert(min(idx, len(params)), block_hex)
    return params


def _short_digest(value: Any) -> str:
    """A short, non-reversible stand-in for a value in a security event — review #5: record WHO
    dissented and a digest of WHAT they said, never the raw value (keeps the event log short and
    avoids echoing a large revert/call payload back out)."""
    return hashlib.sha256(str(value).encode()).hexdigest()[:10]


def _winner_and_dissent(buckets: list):
    """``buckets``: ``[(key, [operator, ...]), ...]``, one entry per distinct answer seen.

    Returns ``(winning_key, winning_distinct_operators, dissenting_detail)`` where
    ``dissenting_detail`` is ``[(operator, key), ...]`` for every operator whose answer is a
    DIFFERENT key than the winner — i.e. every answer the quorum did not pick, named individually
    rather than averaged away. ``(None, None, [])`` when no bucket reaches
    ``RPC_MIN_INDEPENDENT_OPERATORS`` distinct operators at all (plain unavailability/disagreement,
    handled by the caller).

    review #5 (ADR-556 post-implementation audit): the two callers below used to ``return`` the first
    bucket that reached the threshold without ever looking at the REST of the buckets — a 2-of-3
    agreement with a dissenting third operator was reported as a clean, silent MEASURED. Finding a
    winner is no longer a reason to stop looking at the other buckets.
    """
    winner_key, winner_ops = None, None
    for key, operators in buckets:
        if winner_key is None and len(set(operators)) >= contract.RPC_MIN_INDEPENDENT_OPERATORS:
            winner_key, winner_ops = key, sorted(set(operators))
    if winner_key is None:
        return None, None, []
    dissenting_detail = [(op, key) for key, operators in buckets if key != winner_key
                         for op in sorted(set(operators))]
    return winner_key, winner_ops, dissenting_detail


class RpcClient:
    """Read-only JSON-RPC client over the ``chain_id``'s declared, independent operators.

    ``post`` is injectable (``callable(url, payload) -> dict``) so tests never touch the network. Every
    refusal and every disagreement is appended to :attr:`security_events`.
    """

    def __init__(self, chain_id: int, endpoints: Optional[list] = None, post: Optional[Post] = None,
                 timeout_s: int = 10):
        self.chain_id = chain_id
        self.endpoints = list(endpoints) if endpoints is not None else list(contract.RPC_OPERATORS.get(chain_id, ()))
        self.timeout_s = timeout_s
        self._post_fn = post or self._default_post
        self.security_events: list = []

    # -- transport (the only network I/O in this package) ------------------------------------------
    def _default_post(self, url: str, payload: dict) -> dict:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=_UA)
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:  # noqa: S310 — public https RPC, GET-equivalent read
            return json.loads(resp.read())

    def _record_security_event(self, kind: str, detail: dict) -> None:
        self.security_events.append({"kind": kind, "detail": detail, "ts": time.time()})

    # -- the single choke point: nothing reaches the network through any other path ----------------
    def request(self, url: str, method: str, params: list) -> dict:
        """Build and send one allow-listed JSON-RPC call; refuse everything else before any I/O."""
        reason = None
        if not isinstance(method, str) or method not in contract.RPC_ALLOWED_METHODS:
            reason = f"method not allow-listed: {method!r}"
        elif not isinstance(params, list) or isinstance(params, (str, bytes, bytearray)):
            reason = f"params must be a list (refuses batch/object forms), got {type(params).__name__}"
        if reason is not None:
            self._record_security_event("forbidden_method", {"method": method, "url": url, "reason": reason})
            raise ForbiddenMethod(reason)
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        return self._post_fn(url, payload)

    def _poll_operators(self, method: str, params: list) -> list:
        out = []
        for url, operator in self.endpoints:
            try:
                resp = self.request(url, method, params)
            except ForbiddenMethod:
                raise
            except Exception as exc:  # noqa: BLE001 — an unreachable/broken operator is just not a witness
                out.append((operator, None, f"{type(exc).__name__}: {exc}"))
                continue
            out.append((operator, resp, None))
        return out

    # -- WP-S02: pin a block before any read ----------------------------------------------------------
    def pin_block(self) -> dict:
        """Lowest height reached by >= RPC_MIN_INDEPENDENT_OPERATORS operators, minus a 2-block safety
        margin, then independent agreement on that block's hash. ``{"state": NOT_MEASURED, ...}`` on any
        shortfall — never a single-witness number (invariant #2/#17)."""
        polled = self._poll_operators("eth_blockNumber", [])
        heights = []
        for operator, resp, err in polled:
            if err or not isinstance(resp, dict) or "result" not in resp:
                continue
            try:
                heights.append((operator, int(resp["result"], 16)))
            except (TypeError, ValueError):
                continue
        if len(heights) < contract.RPC_MIN_INDEPENDENT_OPERATORS:
            return {"state": contract.NOT_MEASURED,
                    "reason": f"only {len(heights)} operator(s) answered eth_blockNumber "
                              f"(need >= {contract.RPC_MIN_INDEPENDENT_OPERATORS})"}
        heights_sorted = sorted((h for _, h in heights), reverse=True)
        common = heights_sorted[contract.RPC_MIN_INDEPENDENT_OPERATORS - 1]
        pinned_number = common - 2
        if pinned_number < 0:
            return {"state": contract.NOT_MEASURED, "reason": "pinned block below genesis after safety margin"}

        polled_blocks = self._poll_operators("eth_getBlockByNumber", [hex(pinned_number), False])
        seen: dict = {}
        for operator, resp, err in polled_blocks:
            if err or not isinstance(resp, dict):
                continue
            result = resp.get("result")
            block_hash = result.get("hash") if isinstance(result, dict) else None
            if isinstance(block_hash, str):
                seen.setdefault(block_hash, []).append(operator)
        winning_hash, winning_ops, dissent_detail = _winner_and_dissent(list(seen.items()))
        if winning_hash is not None:
            result = {"state": contract.MEASURED, "number": pinned_number, "hash": winning_hash,
                      "operators": winning_ops}
            if dissent_detail:
                # review #5: a winner was found, but do NOT stop looking — a dissenting operator on
                # the block hash is security-relevant (a disagreeing witness) even though the quorum
                # itself is satisfied, so it is both recorded AND surfaced in the response.
                self._record_security_event(
                    "quorum_disagreement",
                    {"method": "eth_getBlockByNumber", "number": pinned_number, "winning_operators": winning_ops,
                     "dissenting": [{"operator": op, "hash_digest": _short_digest(key)} for op, key in dissent_detail]},
                )
                result["dissent"] = sorted({op for op, _ in dissent_detail})
            return result
        self._record_security_event(
            "quorum_disagreement",
            {"method": "eth_getBlockByNumber", "number": pinned_number, "answers": {k: v for k, v in seen.items()}},
        ) if len(seen) > 1 else None
        return {"state": contract.NOT_MEASURED,
                "reason": f"no {contract.RPC_MIN_INDEPENDENT_OPERATORS}-operator agreement on the block hash "
                          f"at {pinned_number} (answers={ {k: v for k, v in seen.items()} })"}

    # -- WP-S02/S03: a quorum read at an explicit pinned block ----------------------------------------
    def quorum(self, method: str, params_without_block: list, block_number) -> dict:
        """A value counts only when >= RPC_MIN_INDEPENDENT_OPERATORS operators return the IDENTICAL
        result (or the identical revert) at ``block_number``. Disagreement among >= 2 answers is itself a
        security-relevant signal (recorded), distinct from mere unavailability (< 2 answers)."""
        if not isinstance(method, str) or method not in contract.RPC_ALLOWED_METHODS:
            self._record_security_event("forbidden_method", {"method": method, "stage": "quorum"})
            raise ForbiddenMethod(f"refused method={method!r}")

        full_params = _params_with_block(method, params_without_block, block_number)
        polled = self._poll_operators(method, full_params)

        results: dict = {}
        reverts: dict = {}
        errors: list = []
        answered = 0
        for operator, resp, err in polled:
            if err:
                errors.append(f"{operator}: {err}")
                continue
            if not isinstance(resp, dict):
                errors.append(f"{operator}: malformed response")
                continue
            if "error" in resp:
                error_obj = resp["error"]
                if _is_revert(error_obj):
                    reverts.setdefault(_revert_key(error_obj), []).append(operator)
                    answered += 1
                else:
                    # an endpoint-specific limitation (e.g. estimateGas rejecting a 3rd/overrides param)
                    # is unavailability FOR THAT OPERATOR, not a global failure and not a revert.
                    errors.append(f"{operator}: rpc_error {error_obj}")
                continue
            result = resp.get("result")
            if result is None:
                errors.append(f"{operator}: no result")
                continue
            key = result if isinstance(result, str) else repr(result)
            results.setdefault(key, []).append(operator)
            answered += 1

        # review #5: results and reverts are tagged so a result string and a revert string that
        # happen to collide textually are never merged into one bucket; the winner is the FIRST
        # bucket (results before reverts, matching the previous preference order) to reach the
        # threshold — but finding it does not stop the search: every OTHER bucket's operators are
        # dissenters, named and recorded even though the quorum itself was satisfied.
        buckets = [(("result", key), operators) for key, operators in results.items()] + \
                 [(("revert", key), operators) for key, operators in reverts.items()]
        winner_tag, winner_ops, dissent_detail = _winner_and_dissent(buckets)
        if winner_tag is not None:
            kind, key = winner_tag
            response = {"state": contract.MEASURED, "operators": winner_ops}
            if kind == "revert":
                response["revert"] = True
                response["revert_data"] = key
            else:
                response["result"] = key
            if dissent_detail:
                self._record_security_event(
                    "quorum_disagreement",
                    {"method": method, "block_number": block_number, "winning_operators": winner_ops,
                     "dissenting": [{"operator": op, "kind": tag[0], "value_digest": _short_digest(tag[1])}
                                    for op, tag in dissent_detail]},
                )
                response["dissent"] = sorted({op for op, _ in dissent_detail})
            return response

        if answered >= contract.RPC_MIN_INDEPENDENT_OPERATORS:
            self._record_security_event(
                "quorum_disagreement",
                {"method": method, "block_number": block_number, "results": list(results.keys()),
                 "reverts": list(reverts.keys())},
            )
            return {"state": contract.NOT_MEASURED, "disagreement": True,
                    "reason": "operators answered but disagreed",
                    "results_seen": list(results.values()) + list(reverts.values())}
        return {"state": contract.NOT_MEASURED,
                "reason": f"fewer than {contract.RPC_MIN_INDEPENDENT_OPERATORS} operators answered ({errors})"}
