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


# ── ADR-564 / RM-EVIDENCE-01 (package E3): identity + the three RWA NAV oracle readers ──────────
#
# The Phase-0 audit's four tokenised-Treasury instruments (BUIDL, USYC, OUSG, USDY) do not share
# ERC-4626 — only USYC has a genuine Chainlink-interface oracle; OUSG's and USDY's Ondo oracles are
# bespoke (``getPriceData``/``getAssetPrice``); BUIDL has none on Ethereum at all. Every reader
# below follows the same discipline as :func:`realised_index`: ``rpc_client=None`` -> NOT_MEASURED
# "rpc not enabled"; any other failure -> a named NOT_MEASURED, never an exception, never a 0.

SEL_NAME = selector("name()")
SEL_SYMBOL = selector("symbol()")
SEL_LATEST_ROUND_DATA = selector("latestRoundData()")
SEL_GET_PRICE_DATA = selector("getPriceData()")
#: Ondo's OndoOracle.getAssetPrice(address asset) -> uint256 (cited: "no timestamp getter").
SEL_GET_ASSET_PRICE = selector("getAssetPrice(address)")


def _decode_word(result_hex: Any, index: int) -> Optional[str]:
    """The ``index``-th 32-byte word (64 hex chars) of an ``eth_call`` result, or ``None`` if the
    payload is too short / malformed."""
    if not isinstance(result_hex, str) or not result_hex.startswith("0x"):
        return None
    h = result_hex[2:]
    start = index * 64
    if len(h) < start + 64:
        return None
    return h[start:start + 64]


def _decode_uint_word(result_hex: Any, index: int) -> Optional[int]:
    word = _decode_word(result_hex, index)
    if word is None:
        return None
    try:
        return int(word, 16)
    except ValueError:
        return None


def _decode_int256_word(result_hex: Any, index: int) -> Optional[int]:
    """Two's-complement decode of the ``index``-th word — Chainlink's ``answer`` is ``int256``
    (may be negative for some feeds, though never for a price-in-USD feed in practice)."""
    raw = _decode_uint_word(result_hex, index)
    if raw is None:
        return None
    if raw >= 1 << 255:
        raw -= 1 << 256
    return raw


def _decode_abi_string(result_hex: Any) -> Optional[str]:
    """A ``string`` return value: head word = byte offset into the tail (normally ``0x20``),
    then a length word, then the UTF-8 bytes (right-padded to a 32-byte boundary). Falls back to
    a ``bytes32``-style fixed string (older ERC-20s encode ``name()``/``symbol()`` this way) when
    the dynamic decode does not look sane. Returns ``None`` on anything unreadable — never a
    guess."""
    if not isinstance(result_hex, str) or not result_hex.startswith("0x"):
        return None
    h = result_hex[2:]
    offset = _decode_uint_word(result_hex, 0)
    if offset is not None and offset % 32 == 0:
        length_idx = offset // 32
        length = _decode_uint_word(result_hex, length_idx)
        if length is not None and 0 <= length <= 1024:
            data_start = (length_idx + 1) * 64
            data_hex = h[data_start:data_start + length * 2]
            if len(data_hex) == length * 2:
                try:
                    return bytes.fromhex(data_hex).decode("utf-8", errors="strict").rstrip("\x00")
                except (ValueError, UnicodeDecodeError):
                    pass
    # bytes32 fallback: a single 32-byte word, NUL-padded.
    word = _decode_word(result_hex, 0)
    if word is None:
        return None
    try:
        raw = bytes.fromhex(word)
    except ValueError:
        return None
    text = raw.rstrip(b"\x00")
    try:
        return text.decode("utf-8", errors="strict") or None
    except UnicodeDecodeError:
        return None


def _unanchored_cell(value: Any, *, unit: str, reason: str, source_ref: str, source_class: str,
                     source_root: str, recorded_at: str) -> dict:
    """A reading we DO trust (the eth_call succeeded and decoded cleanly) but whose upstream
    UPDATE TIME we honestly do not know — coordinator finding 2026-10-04 #1/#2: a value must never
    be graded fresh just because it was CONVENIENT to read it at ``now``. Deliberately bypasses
    ``contract.cell()`` (which forbids a value on a non-VALUED state) because the caller — a
    diffing collector — needs the raw value preserved for the NEXT run's comparison even though
    THIS run cannot honestly claim a freshness/advance verdict for it. Same key set as
    ``contract.cell()`` produces, so every existing consumer that reads ``cell['state']``/
    ``cell['as_of']`` behaves identically; only code that calls ``contract.value_of()``/
    ``measured_value_of()`` (which both gate on ``state in VALUED_STATES`` first) correctly never
    sees this value — a collector reads ``row['value']`` directly instead, by design."""
    return {"state": contract.NOT_MEASURED, "value": value, "unit": unit, "source_ref": source_ref,
           "source_class": source_class, "source_root": source_root, "as_of": None,
           "recorded_at": recorded_at, "method": None, "reason": reason, "n": None, "window": None,
           "precision": None, "embedded_in_return": None}


def verify_erc20_identity(address: str, *, expected_name: str, expected_symbol: str, expected_decimals: int,
                          rpc_client: Optional[RpcClient], now: datetime) -> dict:
    """``name()`` / ``symbol()`` / ``decimals()`` read at one quorum-pinned block, compared to the
    citation's expected identity (ADR-564 decision #4: "instrument identity is verified on-chain
    ... a symbol join is forbidden"). A clean match -> MEASURED; any on-chain mismatch ->
    CONFLICTED (never silently accepted — this is exactly the signal that would catch a wrong
    contract address, not just a wrong pool join); any read failure -> NOT_MEASURED."""
    try:
        return _verify_erc20_identity_impl(address, expected_name=expected_name, expected_symbol=expected_symbol,
                                           expected_decimals=expected_decimals, rpc_client=rpc_client, now=now)
    except Exception as exc:  # noqa: BLE001 — H0 discipline: never let this module crash a scan
        return contract.cell(contract.NOT_MEASURED,
                             reason=f"verify_erc20_identity({address!r}) raised {type(exc).__name__}: {exc}")


def _verify_erc20_identity_impl(address: str, *, expected_name: str, expected_symbol: str,
                                expected_decimals: int, rpc_client: Optional[RpcClient], now: datetime) -> dict:
    if rpc_client is None:
        return contract.cell(contract.NOT_MEASURED, reason="rpc not enabled")
    pinned = rpc_client.pin_block()
    if pinned.get("state") != "MEASURED":
        return contract.cell(contract.NOT_MEASURED, reason=f"block pin failed: {pinned.get('reason', 'unknown')}")
    block_number = pinned["number"]

    name_resp = rpc_client.quorum("eth_call", [{"to": address.lower(), "data": SEL_NAME}], block_number)
    symbol_resp = rpc_client.quorum("eth_call", [{"to": address.lower(), "data": SEL_SYMBOL}], block_number)
    decimals_raw = _eth_call_quorum(rpc_client, address, SEL_DECIMALS, block_number)
    if (name_resp.get("state") != "MEASURED" or symbol_resp.get("state") != "MEASURED"
            or decimals_raw is None):
        return contract.cell(contract.NOT_MEASURED,
                             reason=f"name()/symbol()/decimals() not readable with quorum at block {block_number}")
    name = _decode_abi_string(name_resp.get("result"))
    symbol = _decode_abi_string(symbol_resp.get("result"))
    if name is None or symbol is None:
        return contract.cell(contract.NOT_MEASURED,
                             reason="name()/symbol() returned but could not be ABI-decoded as string or bytes32")

    ts = _block_timestamp(rpc_client, block_number)
    as_of = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts is not None else None

    mismatches = []
    if name != expected_name:
        mismatches.append(f"name {name!r} != expected {expected_name!r}")
    if symbol != expected_symbol:
        mismatches.append(f"symbol {symbol!r} != expected {expected_symbol!r}")
    if decimals_raw != expected_decimals:
        mismatches.append(f"decimals {decimals_raw!r} != expected {expected_decimals!r}")
    if mismatches:
        return contract.cell(contract.CONFLICTED,
                             reason=f"on-chain identity mismatch at {address}: " + "; ".join(mismatches))
    if as_of is None:
        return contract.cell(contract.NOT_MEASURED,
                             reason=f"identity matched at block {block_number} but its timestamp was not "
                                    "independently agreed (< 2 operators)")
    return contract.cell(
        contract.MEASURED, {"name": name, "symbol": symbol, "decimals": decimals_raw}, unit="identity",
        source_ref=f"chain:{CHAIN_ID}:{address.lower()}:name,symbol,decimals:block:{block_number}",
        source_class=contract.PRIMARY_CHAIN, source_root=f"chain:{CHAIN_ID}", as_of=as_of,
        recorded_at=now.isoformat(), now=now,
        method="eth_call name()/symbol()/decimals() at a 2-of-N quorum-pinned block, compared to the cited "
               "identity (ADR-564 decision #4)",
    )


def chainlink_round(address: str, *, rpc_client: Optional[RpcClient], now: datetime,
                    answer_decimals: int = 18) -> dict:
    """``latestRoundData()`` on a Chainlink-interface oracle (USYC's price feed). ``as_of`` is the
    feed's OWN ``updatedAt`` (ADR-564 binding #6: "``latestRoundData`` by ``updatedAt``") — never
    the block time, never the wall clock. Every failure is a named NOT_MEASURED."""
    try:
        return _chainlink_round_impl(address, rpc_client=rpc_client, now=now, answer_decimals=answer_decimals)
    except Exception as exc:  # noqa: BLE001
        return contract.cell(contract.NOT_MEASURED,
                             reason=f"chainlink_round({address!r}) raised {type(exc).__name__}: {exc}")


def _chainlink_round_impl(address: str, *, rpc_client: Optional[RpcClient], now: datetime,
                          answer_decimals: int) -> dict:
    if rpc_client is None:
        return contract.cell(contract.NOT_MEASURED, reason="rpc not enabled")
    if not address:
        return contract.cell(contract.NOT_MEASURED, reason="no oracle address known")
    pinned = rpc_client.pin_block()
    if pinned.get("state") != "MEASURED":
        return contract.cell(contract.NOT_MEASURED, reason=f"block pin failed: {pinned.get('reason', 'unknown')}")
    block_number = pinned["number"]
    resp = rpc_client.quorum("eth_call", [{"to": address.lower(), "data": SEL_LATEST_ROUND_DATA}], block_number)
    if resp.get("state") != "MEASURED" or resp.get("revert"):
        return contract.cell(contract.NOT_MEASURED,
                             reason=f"latestRoundData() not readable with quorum at block {block_number}")
    result = resp.get("result")
    # (uint80 roundId, int256 answer, uint256 startedAt, uint256 updatedAt, uint80 answeredInRound)
    round_id = _decode_uint_word(result, 0)
    answer = _decode_int256_word(result, 1)
    updated_at = _decode_uint_word(result, 3)
    if round_id is None or answer is None or updated_at is None:
        return contract.cell(contract.NOT_MEASURED, reason="latestRoundData() result could not be decoded")
    if updated_at <= 0:
        return contract.cell(contract.NOT_MEASURED, reason=f"latestRoundData() updatedAt={updated_at} is not a "
                                                           "real timestamp (round not yet answered)")
    as_of = datetime.fromtimestamp(updated_at, tz=timezone.utc).isoformat()
    value = answer / (10 ** answer_decimals)
    return contract.cell(
        contract.MEASURED, round(value, 10), unit="usd_per_unit",
        source_ref=f"chain:{CHAIN_ID}:{address.lower()}:latestRoundData:round:{round_id}:block:{block_number}",
        source_class=contract.PRIMARY_CHAIN, source_root=f"chain:{CHAIN_ID}", as_of=as_of,
        recorded_at=now.isoformat(), now=now,
        method="eth_call latestRoundData() at a 2-of-N quorum-pinned block; as_of = the feed's own updatedAt",
    )


def ondo_price_data(address: str, *, rpc_client: Optional[RpcClient], now: datetime,
                    price_decimals: int = 18) -> dict:
    """Ondo's ``USDYOracleWrapper.getPriceData()`` -> ``(uint256 price, uint256 timestamp)``.

    Coordinator live-validation finding (2026-10-04 #2): the second return word is NOT a NAV
    report time — USDY's price is a continuous issuer-scheduled accrual (the formula advances the
    price every second by construction), so ``timestamp`` tracks block/call time, not a discrete
    update event. Treating it as ``as_of`` graded a formula-driven number "fresh" on every single
    read, which is exactly the frozen-value failure mode in the other direction (claiming MORE
    freshness than the data actually supports, never less). Per instruction: do not invent a real
    update time where none is readable — ``getPriceData()``'s own ``timestamp`` field is kept only
    as a diagnostic (not surfaced as ``as_of``), and the reading is NOT_MEASURED for freshness,
    honestly, with the raw ``price`` preserved for display/REFERENCE_TRACK use. No other method on
    this oracle (nor its underlying ``0xA0219AA5...``, per the Phase-0 citation) is documented to
    expose a genuine rate-range-start/update event; none is invented here."""
    try:
        return _ondo_price_data_impl(address, rpc_client=rpc_client, now=now, price_decimals=price_decimals)
    except Exception as exc:  # noqa: BLE001
        return contract.cell(contract.NOT_MEASURED,
                             reason=f"ondo_price_data({address!r}) raised {type(exc).__name__}: {exc}")


def _ondo_price_data_impl(address: str, *, rpc_client: Optional[RpcClient], now: datetime,
                          price_decimals: int) -> dict:
    if rpc_client is None:
        return contract.cell(contract.NOT_MEASURED, reason="rpc not enabled")
    if not address:
        return contract.cell(contract.NOT_MEASURED, reason="no oracle address known")
    pinned = rpc_client.pin_block()
    if pinned.get("state") != "MEASURED":
        return contract.cell(contract.NOT_MEASURED, reason=f"block pin failed: {pinned.get('reason', 'unknown')}")
    block_number = pinned["number"]
    resp = rpc_client.quorum("eth_call", [{"to": address.lower(), "data": SEL_GET_PRICE_DATA}], block_number)
    if resp.get("state") != "MEASURED" or resp.get("revert"):
        return contract.cell(contract.NOT_MEASURED,
                             reason=f"getPriceData() not readable with quorum at block {block_number}")
    result = resp.get("result")
    price = _decode_uint_word(result, 0)
    timestamp = _decode_uint_word(result, 1)
    if price is None or timestamp is None:
        return contract.cell(contract.NOT_MEASURED, reason="getPriceData() result could not be decoded")
    value = round(price / (10 ** price_decimals), 10)
    ref = f"chain:{CHAIN_ID}:{address.lower()}:getPriceData:block:{block_number}"
    # coordinator finding #2: getPriceData()'s own `timestamp` is the formula's evaluation time
    # (continuous issuer-scheduled accrual), not a discrete NAV-report event — never surfaced as
    # as_of. The raw value is still returned (bypassing contract.cell()'s value-on-NOT_MEASURED
    # guard, same discipline as _unanchored_cell/ondo_asset_price) so a REFERENCE_TRACK display or
    # a future bracketing diff still has something to show/compare.
    return _unanchored_cell(
        value, unit="usd_per_unit", source_ref=ref, source_class=contract.PRIMARY_CHAIN,
        source_root=f"chain:{CHAIN_ID}", recorded_at=now.isoformat(),
        reason="issuer-scheduled accrual; price advances by formula, not by a new report — "
               f"getPriceData()'s own timestamp ({timestamp}) is evaluation time, not an update "
               "event, and is never used as as_of (no genuine rate-range-start/update method is "
               "documented or readable for this oracle)",
    )


def ondo_asset_price(address: str, asset_address: str, *, rpc_client: Optional[RpcClient], now: datetime,
                     price_decimals: int = 18, prev_value: Optional[float] = None,
                     prev_as_of: Optional[str] = None, prev_fetched_at: Optional[str] = None) -> dict:
    """Ondo's ``OndoOracle.getAssetPrice(address asset)`` -> ``uint256`` price, with NO timestamp
    getter (the Phase-0 citation is explicit: OUSG's oracle has none). ADR-564 binding #6: an
    oracle without its own timestamp is dated by the time of its LAST VALUE CHANGE, never the
    read block and never the wall clock standing in for an unchanged value.

    Coordinator live-validation finding (2026-10-04 #1): the FIRST-EVER read of a new oracle has
    nothing to diff against, and the previous version of this function treated "no history" the
    SAME as "a confirmed change" — stamping ``as_of = now``, which is exactly "a value with no
    known change time graded fresh". Three states across calls, all supplied by the caller (a
    diffing collector keeps the memory this stateless reader cannot — ``run.py``'s
    ``_treasury_prior_readings`` is the intended loader, reading back prior
    ``evidence_observation`` ledger rows):

    * ``prev_value`` — the raw value last recorded (``None`` ⇒ never observed before);
    * ``prev_fetched_at`` — the FETCH time of that previous recording (the newest moment we know
      for CERTAIN the value was still ``prev_value`` — the conservative lower bound for a change
      detected THIS run);
    * ``prev_as_of`` — the ALREADY-ESTABLISHED last-change time, if any confirmed transition has
      ever been bracketed (carried forward unchanged while the value keeps matching).

    Outcomes (never ``as_of = now`` under ANY of them — that claim is never available to this
    oracle):

    1. ``prev_value is None`` (true first read) ⇒ record the value for next time, but
       NOT_MEASURED / ``as_of=None`` — "first read, last change time unknown". This is the exact
       fix for the coordinator's finding.
    2. value UNCHANGED from ``prev_value`` ⇒ ``as_of`` stays ``prev_as_of`` (which may ITSELF
       still be ``None`` if no transition has ever been bracketed yet — staying NOT_MEASURED is
       correct until one is).
    3. value CHANGED ⇒ a transition is now bracketed between ``prev_fetched_at`` and ``now``;
       ``as_of = prev_fetched_at`` (never ``now`` — the conservative lower bound of when the
       change actually happened, not the moment we happened to notice it)."""
    try:
        return _ondo_asset_price_impl(address, asset_address, rpc_client=rpc_client, now=now,
                                      price_decimals=price_decimals, prev_value=prev_value, prev_as_of=prev_as_of,
                                      prev_fetched_at=prev_fetched_at)
    except Exception as exc:  # noqa: BLE001
        return contract.cell(contract.NOT_MEASURED,
                             reason=f"ondo_asset_price({address!r}) raised {type(exc).__name__}: {exc}")


def _ondo_asset_price_impl(address: str, asset_address: str, *, rpc_client: Optional[RpcClient],
                           now: datetime, price_decimals: int, prev_value: Optional[float],
                           prev_as_of: Optional[str], prev_fetched_at: Optional[str]) -> dict:
    if rpc_client is None:
        return contract.cell(contract.NOT_MEASURED, reason="rpc not enabled")
    if not address or not asset_address:
        return contract.cell(contract.NOT_MEASURED, reason="oracle address or asset address not known")
    pinned = rpc_client.pin_block()
    if pinned.get("state") != "MEASURED":
        return contract.cell(contract.NOT_MEASURED, reason=f"block pin failed: {pinned.get('reason', 'unknown')}")
    block_number = pinned["number"]
    # getAssetPrice(address) — the asset address is left-padded to 32 bytes, as every ABI address
    # argument is.
    calldata = SEL_GET_ASSET_PRICE + asset_address.lower().replace("0x", "").rjust(64, "0")
    price = _eth_call_quorum(rpc_client, address, calldata, block_number)
    if price is None:
        return contract.cell(contract.NOT_MEASURED,
                             reason=f"getAssetPrice() not readable with quorum at block {block_number}")
    value = round(price / (10 ** price_decimals), 10)
    ref = f"chain:{CHAIN_ID}:{address.lower()}:getAssetPrice:block:{block_number}"
    cell_kwargs = dict(source_ref=ref, source_class=contract.PRIMARY_CHAIN, source_root=f"chain:{CHAIN_ID}",
                       recorded_at=now.isoformat())

    if prev_value is None:
        # outcome 1: true first read — nothing to diff against. Honest NOT_MEASURED, value kept
        # for the caller to persist and feed back next time (coordinator finding #1).
        return _unanchored_cell(value, unit="usd_per_unit",
                                reason="first read — last change time unknown (no previous recorded "
                                      "value to diff against)", **cell_kwargs)

    if value == round(float(prev_value), 10):
        # outcome 2: unchanged. as_of carries forward whatever was already established — which may
        # itself still be None if no transition has ever been bracketed (stays NOT_MEASURED then).
        if prev_as_of is None:
            return _unanchored_cell(value, unit="usd_per_unit",
                                    reason="value unchanged since the first read, but no confirmed "
                                          "transition has been observed yet — its true start time is "
                                          "still unknown", **cell_kwargs)
        return contract.cell(contract.MEASURED, value, unit="usd_per_unit", as_of=prev_as_of, now=now,
                            method="eth_call getAssetPrice(address) at a 2-of-N quorum-pinned block; value "
                                   "UNCHANGED from the previous recording — as_of carried forward, never "
                                   "advanced (ADR-564 binding #6)", **cell_kwargs)

    # outcome 3: changed. A transition is bracketed; as_of = the previous FETCH time (the newest
    # moment we know for certain the OLD value still held) — the conservative lower bound, never
    # `now` (the moment we merely happened to notice).
    anchor = prev_fetched_at if prev_fetched_at is not None else prev_as_of
    if anchor is None:
        # defensive: a prev_value was supplied with nothing at all to bound the change by — fail
        # closed rather than invent an as_of (should not occur if the caller always supplies at
        # least one of prev_fetched_at/prev_as_of alongside a non-None prev_value).
        return _unanchored_cell(value, unit="usd_per_unit",
                                reason="value changed but no previous fetch/change time was supplied to "
                                      "bound the change — as_of cannot be honestly set", **cell_kwargs)
    return contract.cell(contract.MEASURED, value, unit="usd_per_unit", as_of=anchor, now=now,
                        method="eth_call getAssetPrice(address) at a 2-of-N quorum-pinned block; value "
                               "CHANGED since the previous recording — as_of = the previous fetch time "
                               "(conservative lower bound of the actual change time, never the time we "
                               "happened to notice it; ADR-564 binding #6)", **cell_kwargs)
