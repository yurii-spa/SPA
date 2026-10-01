"""spa_core/paper_trading/onchain_read.py — read-only JSON-RPC ``eth_call`` with a witness quorum.

For PAPER simulation inputs only (ADR-533): a loop model must value collateral at the price the
market itself liquidates at, and that price lives on-chain. Rules:

* **read-only:** only ``eth_call`` / ``eth_blockNumber``; nothing here can sign or send;
* **quorum:** a value counts only when ≥ ``min_agree`` independent public endpoints return the
  SAME result word (or within ``rel_tol`` for numbers read at slightly different heads);
  fewer ⇒ ``None`` with a reason — never a guessed or single-witness number (invariant #2/#17);
* **injectable transport:** tests pass a fake ``post(url, payload) -> dict``; no test touches
  the network.

Endpoints are the keyless public RPCs already used by ``data_pipeline/sky_monitor.py``.
Stdlib only, LLM_FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import urllib.request
from typing import Callable, Optional

RPC_ENDPOINTS = (
    "https://ethereum-rpc.publicnode.com",
    "https://eth.drpc.org",
    "https://1rpc.io/eth",
    "https://rpc.ankr.com/eth",
    "https://eth.llamarpc.com",
)
_TIMEOUT = 8
_UA = {"Content-Type": "application/json", "User-Agent": "spa-paper/1.0"}


def _default_post(url: str, payload: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=_UA)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:  # noqa: S310 — public https RPC
        return json.loads(r.read())


Post = Callable[[str, dict], dict]


def _close(a: str, b: str, rel_tol: float) -> bool:
    """Same-length static returns whose every word agrees within ``rel_tol`` (heads may differ)."""
    if len(a) != len(b):
        return False
    wa, wb = words(a), words(b)
    return all(x == y or (max(x, y) > 0 and abs(x - y) / max(x, y) <= rel_tol) for x, y in zip(wa, wb))


def eth_call_quorum(to: str, data: str, *, post: Optional[Post] = None,
                    endpoints=RPC_ENDPOINTS, min_agree: int = 2, rel_tol: float = 0.0) -> dict:
    """``{"result": hex|None, "witnesses": [...], "reason": str|None}``.

    The result is accepted only when ``min_agree`` endpoints return byte-identical data (or, with
    ``rel_tol`` > 0, data whose every word agrees within that relative tolerance — two witnesses
    may read heads a block apart; the FIRST witness's value is kept). Calls
    stop as soon as the quorum is reached (cheap on public RPCs).
    """
    post = post or _default_post
    seen: dict[str, list[str]] = {}
    errors: list[str] = []
    for url in endpoints:
        try:
            resp = post(url, {"jsonrpc": "2.0", "id": 1, "method": "eth_call",
                              "params": [{"to": to, "data": data}, "latest"]})
            res = resp.get("result") if isinstance(resp, dict) else None
            if not isinstance(res, str) or not res.startswith("0x") or len(res) < 3:
                errors.append(f"{url.split('/')[2]}: no result")
                continue
            key = res.lower()
            if rel_tol > 0:
                key = next((k for k in seen if _close(k, key, rel_tol)), key)
            seen.setdefault(key, []).append(url.split("/")[2])
            if len(seen[key]) >= min_agree:
                return {"result": key, "witnesses": seen[key], "reason": None}
        except Exception as exc:  # noqa: BLE001 — an unreachable witness is just not a witness
            errors.append(f"{url.split('/')[2]}: {type(exc).__name__}")
    split = {k[:18]: v for k, v in seen.items()}
    return {"result": None, "witnesses": [],
            "reason": f"no {min_agree}-witness agreement (answers {split}, errors {errors})"}


def words(hexdata: str) -> list[int]:
    """ABI-decode a static return into 32-byte unsigned words."""
    body = hexdata[2:]
    return [int(body[i:i + 64], 16) for i in range(0, len(body), 64) if len(body[i:i + 64]) == 64]


def address_word(w: int) -> str:
    return "0x" + format(w, "064x")[24:]


def uint_arg(v: int) -> str:
    return format(int(v), "064x")
