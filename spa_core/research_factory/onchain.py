"""spa_core/research_factory/onchain.py — the Research Factory's ONLY network surface (ADR-560,
WP-S06, binding review #5).

A forward period's ``realised_return`` may only count as consistent with the quoted/observed rate
when it comes from an INDEPENDENT series — an ERC-4626 share-price / exchange-rate delta read
on-chain — never from the same quoted number repeated (that is exactly the ``susde_dn`` failure
mode the review calls out by name: identical frozen forward rows). This module reads that
independent series for the five tokenised-savings wrappers the factory covers (sUSDS, sDAI,
cUSDO, wUSDM, sUSDe) via ``convertToAssets(1 share)`` — the ERC-4626 intrinsic NAV per share.

It is the ONLY place in Package B that touches the network, and only through the existing
allow-listed, keyless, no-signing client ``spa_core.capital_shadow.rpc.RpcClient``:

* ``eth_call`` only (``decimals()`` then ``convertToAssets(10**decimals)``), each a 2-of-N
  independent-operator quorum at ONE pinned block (``RpcClient.pin_block()`` + ``RpcClient.quorum``);
* the block's own timestamp is cross-checked the same way (``eth_getBlockByNumber``, 2-of-N
  agreement on the ``timestamp`` field) so ``as_of`` is never the wall clock standing in for the
  chain's own time;
* function selectors come from ``spa_core.capital_shadow.keccak.selector`` — no hand-typed 4-byte
  constant pretending to be a hash.

Without an injected ``rpc_client`` every call returns ``NOT_MEASURED`` with the reason
``"rpc not enabled"`` — the factory runs daily with no client configured by default; a scanner
that wants a live chain read must be handed one explicitly (``research_factory.run`` decides that,
not this module). No fallback value is ever fabricated: a clean read or a named reason, nothing
between.

Token contracts are the EXACT addresses already live in this repo's adapters / collateral
registry (never invented here); each constant below cites its in-repo source.

LLM_FORBIDDEN, stdlib only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from spa_core.capital_shadow.keccak import selector
from spa_core.capital_shadow.rpc import RpcClient
from spa_core.research_factory import contract

# ── mainnet contract addresses — every one already lives in this repo ───────────────────────────
#: sUSDS (Sky Savings Rate vault) — spa_core/adapters/spark_susds_adapter.py VAULT_ADDRESS
#: (the adapter's module/display name says "Spark"; the vault IS the Sky sUSDS savings token).
SUSDS_ADDRESS = "0xa3931d71877C0E7a3148CB7Eb4463524FEc27fbD"
#: sDAI (MakerDAO/Spark Savings DAI) — spa_core/adapters/sdai_adapter.py VAULT_ADDRESS, and the
#: same literal is the canonical-4626-probe constant in
#: spa_core/strategy_lab/rwa_backstop/onchain_nav.py (_PROBE_4626_CONTRACT).
SDAI_ADDRESS = "0x83F20F44975D03b1b09e64809B757c47f942BEeA"
#: cUSDO (OpenEden ERC-4626 wrapper of USDO) — spa_core/strategy_lab/rwa_backstop/
#: collateral_registry.py token_contract for symbol "cUSDO".
CUSDO_ADDRESS = "0xaD55aebc9b8c03FC43cd9f62260391c13c23e7c0"
#: wUSDM (Mountain Protocol ERC-4626 wrapper of USDM) — collateral_registry.py token_contract for
#: symbol "wUSDM".
WUSDM_ADDRESS = "0x57F5E098CaD7A3D1Eed53991D4d66C45C9AF7812"
#: sUSDe (Ethena staked USDe) — spa_core/adapters/susde_adapter.py VAULT_ADDRESS.
SUSDE_ADDRESS = "0x9D39A5DE30e57443BfF2A8307A4256c8797A3497"

TOKEN_ADDRESSES = {
    "sUSDS": SUSDS_ADDRESS, "sDAI": SDAI_ADDRESS, "cUSDO": CUSDO_ADDRESS,
    "wUSDM": WUSDM_ADDRESS, "sUSDe": SUSDE_ADDRESS,
}

# ── selectors — derived, never hand-typed ────────────────────────────────────────────────────────
SEL_DECIMALS = selector("decimals()")
SEL_CONVERT_TO_ASSETS = selector("convertToAssets(uint256)")

#: a clean ERC-4626 share-NAV read outside this band is an ABI/decode mismatch, not a signal —
#: mirrors the sanity band already used by spa_core/strategy_lab/rwa_backstop/onchain_nav.py.
NAV_SANITY_LOW = 0.5
NAV_SANITY_HIGH = 2.0

#: the method name recorded on the cell — review #7 requires MEASURED only from a real read; this
#: names exactly what happened so a later audit does not have to re-derive it from the code.
METHOD = "eth_call convertToAssets(10**decimals) at a 2-of-N quorum-pinned block (capital_shadow.rpc)"

CHAIN_ID = 1


def _decode_uint(result_hex: Any) -> Optional[int]:
    """0x-hex ``eth_call`` result → non-negative int, or ``None`` on anything but a clean value
    (fail-CLOSED: missing / non-string / empty / unparseable / a revert already filtered upstream
    by ``RpcClient.quorum`` are all the same "no reading")."""
    if not isinstance(result_hex, str) or not result_hex.startswith("0x"):
        return None
    h = result_hex[2:]
    if not h:
        return None
    try:
        return int(h, 16)
    except ValueError:
        return None


def _eth_call_quorum(rpc_client: RpcClient, to_addr: str, data_hex: str, block_number: int) -> Optional[int]:
    """One ``eth_call`` at ``block_number``, 2-of-N independent-operator quorum via the allow-listed
    client, decoded to an int. ``None`` on disagreement, shortfall, revert or a malformed result —
    the caller turns that into a named ``NOT_MEASURED`` reason, never a guess."""
    resp = rpc_client.quorum("eth_call", [{"to": to_addr.lower(), "data": data_hex}], block_number)
    if resp.get("state") != "MEASURED" or resp.get("revert"):
        return None
    return _decode_uint(resp.get("result"))


def _block_timestamp(rpc_client: RpcClient, block_number: int) -> Optional[int]:
    """The pinned block's own ``timestamp`` (unix seconds), independently agreed by
    ``RPC_MIN_INDEPENDENT_OPERATORS`` (2) operators on the EXACT hex string — the same quorum
    discipline ``RpcClient.pin_block`` applies to the block hash, applied here to the field this
    module actually needs. Uses ``RpcClient.request`` (already allow-list-checked; only
    ``eth_getBlockByNumber`` is asked) directly rather than ``RpcClient.quorum`` because that
    method's generic bucketing keys a non-string ``result`` by ``repr()`` — robust for grouping,
    useless for pulling a field back out of the winning bucket."""
    seen: dict = {}
    for url, operator in rpc_client.endpoints:
        try:
            resp = rpc_client.request(url, "eth_getBlockByNumber", [hex(block_number), False])
        except Exception:  # noqa: BLE001 — an unreachable/broken operator is just not a witness
            continue
        result = resp.get("result") if isinstance(resp, dict) else None
        ts_hex = result.get("timestamp") if isinstance(result, dict) else None
        if isinstance(ts_hex, str):
            seen.setdefault(ts_hex, []).append(operator)
    for ts_hex, operators in seen.items():
        if len(set(operators)) >= 2:
            try:
                return int(ts_hex, 16)
            except ValueError:
                continue
    return None


def realised_index(symbol: str, token_contract: Optional[str], *, rpc_client: Optional[RpcClient],
                    now: datetime) -> dict:
    """The ERC-4626 intrinsic NAV/share for ``symbol`` as a ``contract.cell()`` — the independent
    on-chain series review #5 requires before a candidate's ``realised_vs_observed_consistent``
    gate may be anything but UNKNOWN. ``NOT_MEASURED`` (never 0, never the quoted/observed rate
    echoed back) on every failure mode, each with its own named reason:

    * no ``rpc_client`` injected → "rpc not enabled" (the literal reason the ADR specifies);
    * no known contract address → cannot read;
    * the block cannot be pinned with quorum, or the block timestamp cannot be independently
      agreed → no reading;
    * ``decimals()`` or ``convertToAssets`` fails or disagrees → no reading;
    * the derived NAV falls outside the sanity band → treated as a decode/ABI mismatch, not a
      signal (mirrors ``rwa_backstop/onchain_nav.py``).

    Post-implementation review H0: this is the Research Factory's ONLY network surface, called
    once per candidate per day from ``run.py`` — a crash here must never take the whole scan down.
    ``RpcClient`` itself already catches a misbehaving transport per-operator (``_poll_operators``),
    but this function wraps its ENTIRE body in a last-resort guard anyway: any exception this
    module's own arithmetic/parsing did not anticipate becomes a NOT_MEASURED cell naming the
    exception, never an uncaught exception reaching the scanner."""
    try:
        return _realised_index_impl(symbol, token_contract, rpc_client=rpc_client, now=now)
    except Exception as exc:  # noqa: BLE001 — a read failure is a named NOT_MEASURED, never a crash (H0)
        return contract.cell(contract.NOT_MEASURED,
                              reason=f"realised_index({symbol!r}) raised {type(exc).__name__}: {exc}")


def _realised_index_impl(symbol: str, token_contract: Optional[str], *, rpc_client: Optional[RpcClient],
                         now: datetime) -> dict:
    sym = str(symbol or "")
    if rpc_client is None:
        return contract.cell(contract.NOT_MEASURED, reason="rpc not enabled")
    if not token_contract:
        return contract.cell(contract.NOT_MEASURED, reason=f"no on-chain contract address known for {sym}")

    pinned = rpc_client.pin_block()
    if pinned.get("state") != "MEASURED":
        return contract.cell(contract.NOT_MEASURED,
                              reason=f"block pin failed: {pinned.get('reason', 'unknown')}")
    block_number = pinned["number"]

    decimals_raw = _eth_call_quorum(rpc_client, token_contract, SEL_DECIMALS, block_number)
    if decimals_raw is None or decimals_raw < 0 or decimals_raw > 36:
        return contract.cell(contract.NOT_MEASURED,
                              reason=f"decimals() not readable with quorum for {sym} at block {block_number}")

    one_share = 10 ** decimals_raw
    calldata = SEL_CONVERT_TO_ASSETS + f"{one_share:064x}"
    assets_raw = _eth_call_quorum(rpc_client, token_contract, calldata, block_number)
    if assets_raw is None:
        return contract.cell(contract.NOT_MEASURED,
                              reason=f"convertToAssets() not readable with quorum for {sym} at block {block_number}")

    nav = assets_raw / (10 ** decimals_raw)
    if not (NAV_SANITY_LOW <= nav <= NAV_SANITY_HIGH):
        return contract.cell(contract.NOT_MEASURED,
                              reason=f"intrinsic NAV {nav} for {sym} outside sane band "
                                     f"[{NAV_SANITY_LOW}, {NAV_SANITY_HIGH}] — treated as decode mismatch")

    ts = _block_timestamp(rpc_client, block_number)
    if ts is None:
        return contract.cell(contract.NOT_MEASURED,
                              reason=f"block {block_number} timestamp not independently agreed (< 2 operators)")
    as_of = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    return contract.cell(
        contract.MEASURED, round(nav, 10), unit="usd_per_share",
        source_ref=f"chain:{CHAIN_ID}:{token_contract.lower()}:block:{block_number}",
        source_class=contract.PRIMARY_CHAIN, source_root=f"chain:{CHAIN_ID}", as_of=as_of,
        recorded_at=now.isoformat(), now=now, method=METHOD, n=len(pinned.get("operators") or []),
    )
