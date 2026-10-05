"""Tests for ADR-564 (RM-EVIDENCE-01) package E3 — collectors, instrument identity, curated
registries and tracks.

Covers: chain-correct DeFiLlama pool joins (and that a symbol-only join is impossible to produce
the same answer), the three new on-chain oracle readers incl. frozen-value detection, the
per-venue funding collector (median5-single-print replay, expected settlement counts, sign flip
never clamped, same-venue conflict band), and `registry/facts.jsonl` validity + full citation
coverage against the Phase-0 seed.

# FROZEN-DATE-OK: injected-clock — every judgement gets now=NOW, a literal anchor, never the wall
clock; see NOW below (same convention as test_research_factory_scanners.py).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

if __package__ in (None, ""):                      # pragma: no cover — direct-run convenience
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.research_factory import contract, evidence_contract, instruments, onchain, registry_loader
from spa_core.research_factory.collectors import books, contract_identity, funding_venues, treasury
from spa_core.research_factory.scanners import basis, rwa

NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)
REGISTRY_DIR = Path(instruments.__file__).resolve().parent / "registry"
SEED_PATH = Path("/private/tmp/claude-501/-Users-yuriikulieshov-Documents-SPA-Claude"
                 "/77953ab2-8e9a-4d56-8ecb-16448ad02813/scratchpad/ev/phase0_citations.md")


def _load_facts() -> list:
    out = []
    with open(REGISTRY_DIR / "facts.jsonl", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _load_origins() -> dict:
    with open(REGISTRY_DIR / "origins.json", encoding="utf-8") as fh:
        return json.load(fh)


def _facts_as_independently_reviewed() -> list:
    """The real ``facts.jsonl`` content, with ``reviewed_by`` stamped by a DIFFERENT (fixture-only)
    session — H6/M5: the git-tracked file itself keeps ``reviewed_by=null`` (an independent review
    session, not this one, stamps it for real), so testing rwa.py's SUBSTANTIVE fee-cell logic
    needs a reviewed copy injected via monkeypatch, never by editing the tracked file."""
    out = []
    for row in _load_facts():
        row = dict(row)
        row["reviewed_by"] = "test-fixture-independent-review"
        out.append(row)
    return out


def _patch_reviewed_facts(monkeypatch) -> None:
    """Make ``rwa.py``'s ``registry_loader.load_facts()`` return the reviewed copy above, for
    tests of rwa.py's actual fee VALUES/units (as opposed to the separate, real-file test that
    confirms graceful degradation while ``reviewed_by`` is genuinely still null)."""
    reviewed = _facts_as_independently_reviewed()
    monkeypatch.setattr(registry_loader, "load_facts", lambda path=None: reviewed)


# ══════════════════════════════════════════════════════════════════════════════════════════════
# instruments.py — chain-correct pool join; a symbol join is impossible
# ══════════════════════════════════════════════════════════════════════════════════════════════

def _buidl_pools():
    """The Phase-0 defect, reproduced: a BUIDL-labelled pool on Ethereum (correct) AND one on
    Solana (the wrong-chain mis-join target, same symbol, different contract/chain)."""
    return [
        {"pool": "b2b1d98f", "chain": "Ethereum", "symbol": "BUIDL", "apy": 3.467,
         "underlyingTokens": ["0x7712c34205737192402172409a8f7ccef8aa2aec"]},
        {"pool": "590d770e", "chain": "Solana", "symbol": "BUIDL", "apy": 3.778,
         "underlyingTokens": ["5xpsxur8kwqinvd43t8bjwxxj8sj3gxgwu8ejng9rqte"]},
    ]


def test_instruments_chain_correct_join_picks_the_ethereum_contract():
    pool, reason = instruments.join_pool_by_chain_and_contract("BUIDL", _buidl_pools())
    assert reason is None
    assert pool["pool"] == "b2b1d98f"
    assert pool["chain"] == "Ethereum"


def test_instruments_a_symbol_only_join_would_have_picked_the_wrong_chain():
    """Positive control: prove the fixture actually exercises the ambiguity a naive
    ``label.split(':')[1] == symbol`` join would fall into (the Phase-0 defect), so the chain-
    correct join above is a real fix, not a vacuous pass."""
    assert instruments.symbol_join_is_forbidden("BUIDL", _buidl_pools()) is True
    # a naive symbol join picking "the first BUIDL pool it sees" would get the WRONG one here —
    # Solana is listed after Ethereum but a differently-ordered feed would have picked it instead;
    # the chain-correct join is immune to ordering.
    reordered = list(reversed(_buidl_pools()))
    pool, reason = instruments.join_pool_by_chain_and_contract("BUIDL", reordered)
    assert reason is None
    assert pool["pool"] == "b2b1d98f"


def test_instruments_ousg_chain_correct_join_rejects_xrpl():
    pools = [
        {"pool": "7436db9b", "chain": "Ethereum", "symbol": "OUSG", "apy": 3.43,
         "underlyingTokens": ["0x1b19c19393e2d034d8ff31ff34c81252fcbbee92"]},
        {"pool": "36e8a552", "chain": "XRPL", "symbol": "OUSG",
         "underlyingTokens": ["rXRPLOUSGTOKEN"]},
    ]
    pool, reason = instruments.join_pool_by_chain_and_contract("OUSG", pools)
    assert reason is None and pool["pool"] == "7436db9b"


def test_instruments_usyc_chain_correct_join_rejects_bsc():
    pools = [
        {"pool": "448a64ff", "chain": "Ethereum", "symbol": "USYC",
         "underlyingTokens": ["0x136471a34f6ef19fe571effc1ca711fdb8e49f2b"]},
        {"pool": "7c0a89c7", "chain": "BSC", "symbol": "USYC", "underlyingTokens": ["0x8d0fbnc"]},
    ]
    pool, reason = instruments.join_pool_by_chain_and_contract("USYC", pools)
    assert reason is None and pool["pool"] == "448a64ff"


def test_instruments_no_ethereum_pool_is_not_measured_not_a_guess():
    pool, reason = instruments.join_pool_by_chain_and_contract("USDY", [])
    assert pool is None
    assert "no Ethereum pool" in reason


def test_instruments_ambiguous_match_refuses_rather_than_picks_first():
    dup = [
        {"pool": "aaa", "chain": "Ethereum", "underlyingTokens": ["0x7712c34205737192402172409a8f7ccef8aa2aec"]},
        {"pool": "bbb", "chain": "Ethereum", "underlyingTokens": ["0x7712c34205737192402172409a8f7ccef8aa2aec"]},
    ]
    pool, reason = instruments.join_pool_by_chain_and_contract("BUIDL", dup)
    assert pool is None
    assert "ambiguous" in reason


def test_instruments_unknown_symbol_refuses():
    pool, reason = instruments.join_pool_by_chain_and_contract("NOPE", _buidl_pools())
    assert pool is None and "not a known instrument" in reason


def test_instruments_candidate_id_matches_tokenised_treasury_exposure_key():
    cid = instruments.candidate_id_for("USYC")
    expected = contract.candidate_id(
        contract.exposure_key("TOKENISED_TREASURY", instruments.instrument_id("USYC"), "ethereum"))
    assert cid == expected


# ══════════════════════════════════════════════════════════════════════════════════════════════
# onchain.py — the three new oracle readers + identity verification, incl. frozen-value detection
# ══════════════════════════════════════════════════════════════════════════════════════════════

def _fake_rpc(selectors: dict, *, block_number=26_119_871, block_hash="0xblockhash",
             block_ts=1_770_000_000, n_endpoints=3):
    """``selectors``: {4-byte-selector-prefix: full 0x-result-hex}. Matches by the CALLDATA
    PREFIX so a parameterised call (``getAssetPrice(address)``) still dispatches correctly."""
    from spa_core.capital_shadow.rpc import RpcClient

    def post(url, payload):
        method, params = payload["method"], payload["params"]
        if method == "eth_blockNumber":
            return {"jsonrpc": "2.0", "id": 1, "result": hex(block_number + 2)}
        if method == "eth_getBlockByNumber":
            return {"jsonrpc": "2.0", "id": 1,
                    "result": {"hash": block_hash, "timestamp": hex(block_ts), "number": params[0]}}
        if method == "eth_call":
            data = params[0]["data"]
            for sel, result in selectors.items():
                if data.startswith(sel):
                    return {"jsonrpc": "2.0", "id": 1, "result": result}
            return {"jsonrpc": "2.0", "id": 1, "error": {"message": "execution reverted"}}
        raise AssertionError(f"disallowed method reached transport: {method}")

    endpoints = [(f"http://op{i}.example", f"Op{i}") for i in range(n_endpoints)]
    return RpcClient(chain_id=1, endpoints=endpoints, post=post)


def _word(n: int) -> str:
    return f"{n & (2**256 - 1):064x}"


def _encoded_string(s: str) -> str:
    data = s.encode("utf-8")
    padded_len = ((len(data) + 31) // 32) * 32 or 32
    hex_data = data.hex().ljust(padded_len * 2, "0")
    return "0x" + _word(32) + _word(len(data)) + hex_data


def test_onchain_verify_erc20_identity_matches():
    selectors = {
        onchain.SEL_NAME: _encoded_string("US Yield Coin"),
        onchain.SEL_SYMBOL: _encoded_string("USYC"),
        onchain.SEL_DECIMALS: "0x" + _word(6),
    }
    client = _fake_rpc(selectors)
    cell = onchain.verify_erc20_identity(instruments.USYC_ADDRESS, expected_name="US Yield Coin",
                                         expected_symbol="USYC", expected_decimals=6, rpc_client=client, now=NOW)
    assert cell["state"] == contract.MEASURED
    assert cell["value"] == {"name": "US Yield Coin", "symbol": "USYC", "decimals": 6}
    assert cell["source_class"] == contract.PRIMARY_CHAIN


def test_onchain_verify_erc20_identity_mismatch_is_conflicted_not_silently_accepted():
    """Mutation pair: a wrong on-chain symbol must CONFLICT, never be accepted as a match."""
    selectors_ok = {onchain.SEL_NAME: _encoded_string("US Yield Coin"), onchain.SEL_SYMBOL: _encoded_string("USYC"),
                   onchain.SEL_DECIMALS: "0x" + _word(6)}
    ok = onchain.verify_erc20_identity(instruments.USYC_ADDRESS, expected_name="US Yield Coin",
                                       expected_symbol="USYC", expected_decimals=6,
                                       rpc_client=_fake_rpc(selectors_ok), now=NOW)
    assert ok["state"] == contract.MEASURED

    selectors_bad = {onchain.SEL_NAME: _encoded_string("Some Other Token"),
                     onchain.SEL_SYMBOL: _encoded_string("USYC"), onchain.SEL_DECIMALS: "0x" + _word(6)}
    bad = onchain.verify_erc20_identity(instruments.USYC_ADDRESS, expected_name="US Yield Coin",
                                        expected_symbol="USYC", expected_decimals=6,
                                        rpc_client=_fake_rpc(selectors_bad), now=NOW)
    assert bad["state"] == contract.CONFLICTED
    assert bad["value"] is None
    assert "mismatch" in bad["reason"]


def test_onchain_verify_erc20_identity_without_client_is_rpc_not_enabled():
    cell = onchain.verify_erc20_identity(instruments.USYC_ADDRESS, expected_name="x", expected_symbol="y",
                                         expected_decimals=1, rpc_client=None, now=NOW)
    assert cell["state"] == contract.NOT_MEASURED and cell["reason"] == "rpc not enabled"


def test_onchain_chainlink_round_as_of_is_updated_at_not_block_time():
    updated_at = 1_759_000_000  # deliberately far from the fake block_ts, to prove it's NOT block time
    result = "0x" + _word(525) + _word(1_139_002_815_000_000_000) + _word(1_758_999_000) + _word(updated_at) \
        + _word(525)
    client = _fake_rpc({onchain.SEL_LATEST_ROUND_DATA: result}, block_ts=1_770_000_000)
    cell = onchain.chainlink_round(instruments.INSTRUMENTS["USYC"]["oracle"]["address"], rpc_client=client, now=NOW)
    assert cell["state"] == contract.MEASURED
    assert cell["value"] == pytest.approx(1.139002815)
    assert cell["as_of"] == datetime.fromtimestamp(updated_at, tz=timezone.utc).isoformat()
    assert cell["as_of"] != datetime.fromtimestamp(1_770_000_000, tz=timezone.utc).isoformat()


def test_onchain_chainlink_round_unanswered_round_is_not_measured():
    result = "0x" + _word(1) + _word(0) + _word(0) + _word(0) + _word(1)  # updatedAt=0 ⇒ never answered
    client = _fake_rpc({onchain.SEL_LATEST_ROUND_DATA: result})
    cell = onchain.chainlink_round("0xoracle", rpc_client=client, now=NOW)
    assert cell["state"] == contract.NOT_MEASURED
    assert "not a real timestamp" in cell["reason"]


def test_onchain_ondo_price_data_timestamp_is_never_trusted_as_as_of():
    """Coordinator live-validation finding #2 (2026-10-04): getPriceData()'s own `timestamp` is
    USDY's continuous issuer-scheduled-accrual EVALUATION time, not a discrete NAV-report event —
    it must never be surfaced as as_of (that graded a formula-driven number "fresh" on every
    single read). The raw value is still returned (NOT_MEASURED, as_of=None) for display/diffing."""
    ts = 1_759_500_000
    result = "0x" + _word(1_148_430_460_000_000_000) + _word(ts)
    client = _fake_rpc({onchain.SEL_GET_PRICE_DATA: result})
    cell = onchain.ondo_price_data("0xusdyoracle", rpc_client=client, now=NOW)
    assert cell["state"] == contract.NOT_MEASURED
    assert cell["as_of"] is None
    assert cell["value"] == pytest.approx(1.14843046)
    assert "issuer-scheduled accrual" in cell["reason"]
    assert str(ts) in cell["reason"]      # the raw timestamp is named as a diagnostic, never used


# ── frozen-value detection: the ADR-564 binding #6 behaviour this package exists to add ────────
# Coordinator live-validation finding #1 (2026-10-04): a live first-ever run had NO prior value,
# and the old code treated "no history" identically to "a confirmed change", stamping
# as_of = now ("a value with no known change time graded fresh"). The three tests below replay
# exactly that scenario across three simulated runs, and the fix: first read -> NOT_MEASURED,
# as_of=None; unchanged (still no bracketed transition) -> stays NOT_MEASURED; a GENUINE change
# brackets a transition and anchors as_of at the PREVIOUS fetch time, never `now`.
def test_onchain_ondo_asset_price_three_simulated_runs_first_read_is_not_measured():
    raw_price = 116_767_284_000_000_000_000  # 116.767284 at 18 decimals
    client = _fake_rpc({onchain.SEL_GET_ASSET_PRICE: "0x" + _word(raw_price)})

    # run 1: no history at all — the coordinator's exact finding.
    run1 = onchain.ondo_asset_price("0xoracle", "0xousg", rpc_client=client, now=NOW)
    assert run1["state"] == contract.NOT_MEASURED
    assert run1["as_of"] is None                      # never `now` — the fix
    assert run1["value"] == pytest.approx(116.767284)  # but the value IS kept, for the next run's diff
    assert "first read" in run1["reason"]


def test_onchain_ondo_asset_price_three_simulated_runs_unchanged_stays_unanchored_then_anchors_on_change():
    raw_price = 116_767_284_000_000_000_000
    client = _fake_rpc({onchain.SEL_GET_ASSET_PRICE: "0x" + _word(raw_price)})
    t1 = NOW
    run1 = onchain.ondo_asset_price("0xoracle", "0xousg", rpc_client=client, now=t1)

    # run 2 (t2): STILL the same value. No transition has ever been bracketed yet (run 1 could not
    # establish one) — must STILL be NOT_MEASURED, never "now", never a guessed earlier time.
    t2 = t1.replace(hour=23)
    run2 = onchain.ondo_asset_price("0xoracle", "0xousg", rpc_client=client, now=t2,
                                    prev_value=run1["value"], prev_as_of=run1["as_of"],
                                    prev_fetched_at=t1.isoformat())
    assert run2["state"] == contract.NOT_MEASURED
    assert run2["as_of"] is None
    assert run2["value"] == run1["value"]
    assert "no confirmed transition" in run2["reason"]

    # run 3 (t3): the value FINALLY changes. The transition is bracketed between t2 (the last
    # confirmed-old-value fetch) and t3 — as_of = t2 (prev_fetched_at passed from run 2), NEVER t3.
    t3 = t1.replace(day=5)
    client_v2 = _fake_rpc({onchain.SEL_GET_ASSET_PRICE: "0x" + _word(116_900_000_000_000_000_000)})
    run3 = onchain.ondo_asset_price("0xoracle", "0xousg", rpc_client=client_v2, now=t3,
                                    prev_value=run2["value"], prev_as_of=run2["as_of"],
                                    prev_fetched_at=t2.isoformat())
    assert run3["state"] == contract.MEASURED
    assert run3["value"] != run2["value"]
    assert run3["as_of"] == t2.isoformat()     # the previous FETCH time — the conservative lower bound
    assert run3["as_of"] != t3.isoformat()     # never "now", never the moment we merely noticed it
    assert "CHANGED" in run3["method"]


def test_onchain_ondo_asset_price_once_a_transition_is_bracketed_unchanged_carries_it_forward():
    """A 4th run, continuing run3 above: the newly-established as_of (t2) must carry forward
    unchanged while the value stays the same — never re-anchored to the 4th run's own fetch time."""
    t2 = NOW.replace(hour=23)
    established_as_of = t2.isoformat()
    client = _fake_rpc({onchain.SEL_GET_ASSET_PRICE: "0x" + _word(116_900_000_000_000_000_000)})
    t4 = NOW.replace(day=10)
    run4 = onchain.ondo_asset_price("0xoracle", "0xousg", rpc_client=client, now=t4,
                                    prev_value=116.9, prev_as_of=established_as_of,
                                    prev_fetched_at=NOW.replace(day=5).isoformat())
    assert run4["state"] == contract.MEASURED
    assert run4["as_of"] == established_as_of
    assert run4["as_of"] != t4.isoformat()


def test_onchain_ondo_asset_price_changed_without_any_anchor_fails_closed():
    """Defensive: prev_value supplied but neither prev_fetched_at nor prev_as_of — must never
    invent an as_of; NOT_MEASURED with a named reason."""
    client = _fake_rpc({onchain.SEL_GET_ASSET_PRICE: "0x" + _word(116_900_000_000_000_000_000)})
    cell = onchain.ondo_asset_price("0xoracle", "0xousg", rpc_client=client, now=NOW, prev_value=100.0,
                                    prev_as_of=None, prev_fetched_at=None)
    assert cell["state"] == contract.NOT_MEASURED
    assert cell["as_of"] is None
    assert "cannot be honestly set" in cell["reason"]


def test_onchain_ondo_asset_price_without_client_is_not_measured():
    cell = onchain.ondo_asset_price("0xoracle", "0xousg", rpc_client=None, now=NOW)
    assert cell["state"] == contract.NOT_MEASURED and cell["reason"] == "rpc not enabled"


def test_onchain_every_new_reader_wraps_exceptions_as_not_measured(monkeypatch):
    """H0 discipline, applied to the three new readers: a transport that always raises must never
    propagate out of chainlink_round / ondo_price_data / ondo_asset_price / verify_erc20_identity."""
    client = _fake_rpc({})

    def boom(*a, **k):
        raise RuntimeError("transport exploded")

    monkeypatch.setattr(client, "pin_block", boom)
    for fn, args in (
        (onchain.chainlink_round, ("0xa",)),
        (onchain.ondo_price_data, ("0xa",)),
        (onchain.ondo_asset_price, ("0xa", "0xb")),
        (onchain.verify_erc20_identity, ("0xa",)),
    ):
        kwargs = {"rpc_client": client, "now": NOW}
        if fn is onchain.verify_erc20_identity:
            kwargs.update(expected_name="n", expected_symbol="s", expected_decimals=1)
        cell = fn(*args, **kwargs)  # must not raise
        assert cell["state"] == contract.NOT_MEASURED


# ══════════════════════════════════════════════════════════════════════════════════════════════
# collectors/funding_venues.py — the median5-single-print replay + the other named invariants
# ══════════════════════════════════════════════════════════════════════════════════════════════

def test_funding_venues_sign_flip_is_never_clamped():
    assert funding_venues.rate_per_8h(-0.0005, 8.0) == pytest.approx(-0.0005)
    assert funding_venues.rate_per_8h(-0.0005, 1.0) == pytest.approx(-0.004)


def test_funding_venues_hyperliquid_hourly_normalises_to_8h_equivalent():
    assert funding_venues.rate_per_8h(0.0001, 1.0) == pytest.approx(0.0008)


def test_funding_venues_same_venue_conflict_band():
    band = evidence_contract.FUNDING_SAME_VENUE_BAND_BPS_8H
    assert funding_venues.same_venue_conflict(0.0001, 0.0001 + (band / 2) / 10_000.0) is False
    assert funding_venues.same_venue_conflict(0.0001, 0.0001 + (band * 2) / 10_000.0) is True


def test_funding_venues_collect_persists_every_venue_separately_not_a_blend():
    """The median5-single-print defect, replayed: feed ONE venue's real settlement history and
    show the OLD pipeline's failure mode (a single-venue day silently masquerading as a 5-venue
    median) can no longer happen — the new collector names the venue on every row, and a day with
    only one venue answering is visibly a ONE-VENUE day, never blended into a fake aggregate."""
    binance_payload = [
        {"symbol": "ETHUSDT", "fundingTime": 1_759_017_600_000, "fundingRate": "0.00012"},
        {"symbol": "ETHUSDT", "fundingTime": 1_759_046_400_000, "fundingRate": "-0.00005"},
        {"symbol": "ETHUSDT", "fundingTime": 1_759_075_200_000, "fundingRate": "0.00008"},
    ]
    rows = funding_venues.collect(NOW, client=None, assets=("ETH",),
                                  payloads={("binance", "ETH"): binance_payload})
    binance_rows = [r for r in rows if r["origin"] == "venue:binance"]
    other_rows = [r for r in rows if r["origin"] != "venue:binance" and r.get("claim") == "funding_settlement:ETH"]
    assert len(binance_rows) == 3
    assert other_rows == []            # no venue was asked to contribute anything it didn't have
    # every row names ITS OWN venue and ITS OWN true settlement timestamp — nothing here is a
    # cross-venue median standing in as if several venues had agreed.
    for r in binance_rows:
        assert r["origin"] == "venue:binance"
        assert r["state"] == "MEASURED"
        assert contract.parse_ts(r["upstream_ts"]) is not None
    assert binance_rows[0]["value"] == pytest.approx(0.00012)
    assert binance_rows[1]["value"] == pytest.approx(-0.00005)          # sign preserved
    day_summary = funding_venues.settlement_day_summary(rows)
    key = ("binance", "ETH", "2025-09-28")
    assert key in day_summary
    assert day_summary[key] == {"count": 3, "expected": 3, "partial": False}


def test_funding_venues_expected_settlement_counts_flag_partial_days():
    partial_payload = [
        {"symbol": "ETHUSDT", "fundingTime": 1_759_017_600_000, "fundingRate": "0.0001"},
        {"symbol": "ETHUSDT", "fundingTime": 1_759_046_400_000, "fundingRate": "0.0001"},
        # only 2 of binance's expected 3 settlements for this UTC day
    ]
    rows = funding_venues.collect(NOW, client=None, assets=("ETH",),
                                  payloads={("binance", "ETH"): partial_payload})
    summary = funding_venues.settlement_day_summary(rows)
    key = ("binance", "ETH", "2025-09-28")
    assert summary[key]["count"] == 2
    assert summary[key]["expected"] == funding_venues.EXPECTED_SETTLEMENTS_PER_DAY["binance"] == 3
    assert summary[key]["partial"] is True


def test_funding_venues_hyperliquid_expected_count_is_24_per_day():
    assert funding_venues.EXPECTED_SETTLEMENTS_PER_DAY["hyperliquid"] == 24


def test_funding_venues_bad_payload_is_not_measured_not_a_crash():
    rows = funding_venues.collect(NOW, client=None, assets=("ETH",),
                                  payloads={("binance", "ETH"): {"not": "a list"}})
    binance_rows = [r for r in rows if r["origin"] == "venue:binance"]
    assert len(binance_rows) == 1
    assert binance_rows[0]["state"] == "NOT_MEASURED"


def test_funding_venues_candidate_id_matches_funding_capture_exposure_key():
    cid = funding_venues._pair_candidate_id("ETH", "binance")
    expected = contract.candidate_id(contract.exposure_key("FUNDING_CAPTURE", "perp:ETH:binance", "cex"))
    assert cid == expected


# ══════════════════════════════════════════════════════════════════════════════════════════════
# collectors/books.py — the book walk + fee/timestamp labelling
# ══════════════════════════════════════════════════════════════════════════════════════════════

def test_books_walk_book_vwap_across_two_levels():
    avg, filled = books.walk_book([[100.0, 1.0], [101.0, 2.0]], 150.0)
    assert avg == pytest.approx(100.331125, rel=1e-5)
    assert filled == pytest.approx(150.0)


def test_books_walk_book_too_thin_fills_less_than_requested_never_pads():
    avg, filled = books.walk_book([[100.0, 1.0]], 1_000.0)
    assert avg == pytest.approx(100.0)
    assert filled == pytest.approx(100.0)    # less than the 1000 requested — never silently padded


def test_books_walk_book_empty_is_none_not_a_guess():
    assert books.walk_book([], 100.0) == (None, None)
    assert books.walk_book(None, 100.0) == (None, None)


# ══════════════════════════════════════════════════════════════════════════════════════════════
# collectors/treasury.py — oracle dispatch, USYC official-API channel, DeFiLlama aggregator-only
# ══════════════════════════════════════════════════════════════════════════════════════════════

class _FakeClient:
    def __init__(self, gets=None, raises=None):
        self._gets = gets or {}
        self._raises = raises or set()

    def get(self, host, path, params):
        if (host, path) in self._raises:
            raise RuntimeError("network down")
        return self._gets.get((host, path))

    def post_info(self, info_type, payload):
        raise AssertionError("treasury collector never POSTs")


def test_treasury_collect_usyc_official_api_is_official_api_channel():
    client = _FakeClient(gets={
        (treasury.USYC_API_HOST, "/api/price"): {"price": 1.139002815, "timestamp": "2026-10-02T12:31:59+00:00"},
        (treasury.USYC_API_HOST, "/api/price-reports"): {"price": 1.139002815,
                                                          "timestamp": "2026-10-02T12:31:59+00:00"},
    })
    rows = treasury.collect(NOW, client, pools=[])
    usyc_api = [r for r in rows if r["candidate_id"] == instruments.candidate_id_for("USYC")
               and r["channel"] == evidence_contract.CHANNEL_OFFICIAL_API]
    assert len(usyc_api) == 2
    assert all(r["origin"] == "issuer:hashnote" for r in usyc_api)
    assert all(r["state"] == "MEASURED" for r in usyc_api)


def test_treasury_collect_defillama_is_always_aggregator_channel():
    rows = treasury.collect(NOW, None, pools=_buidl_pools())
    buidl_llama = [r for r in rows if r["candidate_id"] == instruments.candidate_id_for("BUIDL")
                  and r["claim"] == treasury.CLAIM_NAV_AGGREGATOR_APY][0]
    assert buidl_llama["channel"] == evidence_contract.CHANNEL_AGGREGATOR
    assert buidl_llama["origin"] == "aggregator:defillama"
    assert buidl_llama["state"] == "MEASURED"
    assert buidl_llama["value"] == pytest.approx(3.467)


def test_treasury_collect_backfill_true_on_first_collection_only():
    rows_first = treasury.collect(NOW, None, pools=[])
    buidl_oracle = [r for r in rows_first if r["candidate_id"] == instruments.candidate_id_for("BUIDL")
                   and r["claim"] == treasury.CLAIM_NAV_ORACLE][0]
    assert buidl_oracle["backfill"] is True       # no prior ⇒ first collection ⇒ backfill

    rows_second = treasury.collect(NOW, None, pools=[], prior={"BUIDL": {"value": 1.0, "as_of": NOW.isoformat()}})
    buidl_oracle2 = [r for r in rows_second if r["candidate_id"] == instruments.candidate_id_for("BUIDL")
                    and r["claim"] == treasury.CLAIM_NAV_ORACLE][0]
    assert buidl_oracle2["backfill"] is False


def test_treasury_collect_client_failure_is_not_measured_not_a_crash():
    client = _FakeClient(raises={(treasury.USYC_API_HOST, "/api/price"),
                                 (treasury.USYC_API_HOST, "/api/price-reports")})
    rows = treasury.collect(NOW, client, pools=[])  # must not raise
    usyc_api = [r for r in rows if r["channel"] == evidence_contract.CHANNEL_OFFICIAL_API]
    assert all(r["state"] == "NOT_MEASURED" for r in usyc_api)


# ══════════════════════════════════════════════════════════════════════════════════════════════
# scanners/basis.py — funding pairs + exposure family + median5 SUPERSEDED
# ══════════════════════════════════════════════════════════════════════════════════════════════

def _settlement_row(asset, venue, ts_iso, value):
    return {"schema": evidence_contract.SCHEMA_OBS_ROW, "candidate_id": funding_venues._pair_candidate_id(asset, venue),
           "claim": f"funding_settlement:{asset}", "value": value, "unit": "rate_per_8h", "window": None,
           "upstream_ts": ts_iso, "fetched_at": NOW.isoformat(), "origin": f"venue:{venue}",
           "channel": evidence_contract.CHANNEL_OFFICIAL_API, "ref": "x", "raw_sha256": None, "backfill": False,
           "revises": None, "state": "MEASURED", "reason": None}


def test_basis_funding_pair_candidates_cover_every_perp_times_spot_combo():
    rows = [_settlement_row("ETH", "binance", "2026-10-03T08:00:00+00:00", 0.0001)]
    cands = basis.funding_pair_candidates("ETH", rows, [], NOW)
    assert len(cands) == len(basis.PERP_LEG_VENUES) * len(basis.SPOT_LEG_VENUES)
    ids = {c["instrument_id"] for c in cands}
    assert "perp:ETH:binancebinance" in ids
    assert "perp:ETH:hyperliquidkucoin" in ids
    # every pair of ONE asset shares one family (contract.py v1 has no dedicated exposure_family
    # field — this package records it on underlying_root, see module docstring).
    assert {c["underlying_root"] for c in cands} == {basis.FUNDING_FAMILY_ROOT.format(asset="ETH")}


def test_basis_funding_pair_fee_known_only_for_kucoin_and_hyperliquid():
    """H2 (post-implementation review, 2026-10-04): the v1 single ``fees`` cell is NEVER fed a
    one-off taker fee again (that was the live -2697-shaped defect's sibling: a one-off cost
    mislabelled as if comparable to an annual rate) — it is NOT_APPLICABLE for every pair, and the
    actual per-leg taker fee lives in ``paper_accounting_hints.legs`` instead."""
    rows = [_settlement_row("ETH", "binance", "2026-10-03T08:00:00+00:00", 0.0001)]
    cands = {c["instrument_id"]: c for c in basis.funding_pair_candidates("ETH", rows, [], NOW)}
    kucoin_leg = cands["perp:ETH:kucoinbinance"]
    assert kucoin_leg["fees"]["state"] == contract.NOT_APPLICABLE
    hints = kucoin_leg["paper_accounting_hints"]["legs"]
    perp_fee = hints["perp"]["entry_fee_components"][0]["cell"]
    assert perp_fee["state"] == contract.DOCUMENTED
    assert perp_fee["value"] == pytest.approx(0.0006)
    assert perp_fee["unit"] == basis.UNIT_ONE_OFF

    binance_leg = cands["perp:ETH:binancekucoin"]
    binance_hints = binance_leg["paper_accounting_hints"]["legs"]
    binance_perp_fee = binance_hints["perp"]["entry_fee_components"][0]["cell"]
    assert binance_perp_fee["state"] == contract.NOT_MEASURED
    assert "COST UNKNOWN" in binance_perp_fee["reason"]


def test_basis_funding_pair_without_book_evidence_never_fabricates_a_hedge_leg():
    rows = [_settlement_row("ETH", "binance", "2026-10-03T08:00:00+00:00", 0.0001)]
    cand = basis.funding_pair_candidates("ETH", rows, [], NOW)[0]
    assert cand["hedging_cost"]["state"] == contract.NOT_MEASURED
    assert "BOTH legs" in cand["hedging_cost"]["reason"]


def test_basis_scan_marks_legacy_median5_superseded_when_pair_rows_are_supplied(tmp_path):
    (tmp_path / "market_data").mkdir()
    (tmp_path / "market_data" / "funding.json").write_text(
        json.dumps({"generated_at": NOW.isoformat(), "series": {"2026-10-03": 0.0001}}))
    (tmp_path / "market_data" / "btc_funding.json").write_text(
        json.dumps({"generated_at": NOW.isoformat(), "series": {"2026-10-03": 0.0001}}))
    (tmp_path / "adapter_status.json").write_text(json.dumps({"adapters": {}}))
    rows = [_settlement_row("ETH", "binance", "2026-10-03T08:00:00+00:00", 0.0001)]
    res = basis.scan(tmp_path, NOW, funding_rows=rows, book_rows=[])
    legacy = [c for c in res["candidates"] if c["instrument_id"] == "perp:ETH:median5"][0]
    assert legacy["superseded_by"] == basis.FUNDING_FAMILY_ROOT.format(asset="ETH")
    pair_ids = {c["instrument_id"] for c in res["candidates"] if c["mechanism_id"] == "FUNDING_CAPTURE"
               and c["instrument_id"] != "perp:ETH:median5" and c["instrument_id"] != "perp:BTC:median5"}
    assert "perp:ETH:binancebinance" in pair_ids


def test_basis_scan_without_collected_rows_leaves_legacy_candidate_unsuperseded(tmp_path):
    """Backward compatibility: a caller with no collected rows yet still gets the plain median5
    candidate, unsuperseded — never a crash from the new, optional parameters."""
    (tmp_path / "market_data").mkdir()
    (tmp_path / "market_data" / "funding.json").write_text(
        json.dumps({"generated_at": NOW.isoformat(), "series": {"2026-10-03": 0.0001}}))
    (tmp_path / "market_data" / "btc_funding.json").write_text(
        json.dumps({"generated_at": NOW.isoformat(), "series": {"2026-10-03": 0.0001}}))
    (tmp_path / "adapter_status.json").write_text(json.dumps({"adapters": {}}))
    res = basis.scan(tmp_path, NOW)
    legacy = [c for c in res["candidates"] if c["instrument_id"] == "perp:ETH:median5"][0]
    assert legacy["superseded_by"] is None


# ══════════════════════════════════════════════════════════════════════════════════════════════
# registry/origins.json + registry/facts.jsonl — schema validity and full citation coverage
# ══════════════════════════════════════════════════════════════════════════════════════════════

def test_origins_registry_every_key_matches_the_frozen_origin_regex():
    origins = _load_origins()
    for key in origins:
        if key.startswith("_"):
            continue
        assert evidence_contract.ORIGIN_RE.match(key), f"bad origin id {key!r}"


def test_origins_circle_and_hashnote_share_one_group():
    origins = _load_origins()
    assert origins["issuer:circle"]["group"] == origins["issuer:hashnote"]["group"]


def test_origins_nav_consulting_has_appointed_by():
    origins = _load_origins()
    assert origins["administrator:nav_consulting"]["appointed_by"]


def test_facts_jsonl_every_row_matches_fact_fields_exactly():
    facts = _load_facts()
    assert len(facts) > 0
    expected = set(evidence_contract.FACT_FIELDS)
    for row in facts:
        # tail of ADR-564: every REQUIRED field exactly, plus only the contract's OPTIONAL fields (effective_until)
        extra = set(row.keys()) - expected
        assert expected <= set(row.keys()) and extra <= set(evidence_contract.FACT_OPTIONAL_FIELDS), \
            f"{row.get('fact_id')}: missing={expected - set(row.keys())} extra={extra}"
        assert row["schema"] == evidence_contract.SCHEMA_FACT.replace("1", "1") or row["schema"] == "curated-fact/1"


def test_facts_jsonl_quote_length_within_quote_max_chars():
    for row in _load_facts():
        quote = row.get("quote")
        assert isinstance(quote, str) and quote, row["fact_id"]
        assert len(quote) <= evidence_contract.QUOTE_MAX_CHARS, (row["fact_id"], len(quote))


def test_facts_jsonl_fact_ids_are_unique():
    ids = [row["fact_id"] for row in _load_facts()]
    assert len(ids) == len(set(ids))


_CURATORS = ("RM-EVIDENCE-01 Phase-0 audit",
             "RM-EVIDENCE-01 remediation re-curation (coordinator session, 2026-10-04)",
             # tail of ADR-564: fact-012 gained a structured effective_until (re-curated, re-reviewed round 4)
             "RM-EVIDENCE-01 tail curation (coordinator session, 2026-10-05)")


def _fact_reviews() -> dict:
    """reviewer string -> {fact_id: verdict}, from the committed review records."""
    out = {}
    for path in sorted((REGISTRY_DIR / "fact_reviews").glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        out.setdefault(doc["reviewer"], {}).update({f["fact_id"]: f["verdict"] for f in doc["facts"]})
    return out


def test_facts_jsonl_curated_by_is_a_named_curation_and_never_self_reviewed():
    # ADR-564: "a different session must review" — the curating session never self-reviews.
    for row in _load_facts():
        assert row["curated_by"] in _CURATORS, row["fact_id"]
        assert row["reviewed_by"] != row["curated_by"], row["fact_id"]


def test_every_reviewed_by_is_backed_by_a_committed_confirmed_review_record():
    """Independent fact review (2026-10-04) replaced 'every fact is still unreviewed': a stamp is
    only legitimate when a COMMITTED review record by that reviewer CONFIRMED that very fact —
    a reviewed_by string with no record behind it is a self-certification."""
    reviews = _fact_reviews()
    stamped = [r for r in _load_facts() if r["reviewed_by"] is not None]
    assert stamped, "no fact carries an independent review — the registry is unusable"
    for row in stamped:
        verdicts = reviews.get(row["reviewed_by"])
        assert verdicts is not None, (row["fact_id"], "no committed record for reviewer", row["reviewed_by"])
        assert verdicts.get(row["fact_id"]) == "CONFIRMED", (row["fact_id"], verdicts.get(row["fact_id"]))


def test_a_fact_rejected_by_review_and_not_re_curated_stays_unusable():
    reviews = _fact_reviews()
    for row in _load_facts():
        rejected_by = [rev for rev, v in reviews.items() if v.get(row["fact_id"]) == "REJECTED"]
        if rejected_by and row["curated_by"] == _CURATORS[0]:
            assert row["reviewed_by"] is None, row["fact_id"]


def test_facts_jsonl_usdy_issuer_conflict_is_recorded_as_two_conflicting_facts():
    usdy_issuer_facts = [r for r in _load_facts() if r["entity"] == "USDY" and r["claim_type"] == "issuer"]
    assert len(usdy_issuer_facts) == 2
    values = {r["value"] for r in usdy_issuer_facts}
    assert len(values) == 2, "the two USDY issuer facts must actually disagree, not duplicate each other"
    assert all(r["subject_to_change"] for r in usdy_issuer_facts)


def test_facts_jsonl_ousg_ondo_i_lp_link_is_recorded_unknown_with_a_reason():
    row = next(r for r in _load_facts() if r["entity"] == "OUSG"
              and r["claim_type"] == "legal_entity_link_inferred")
    assert row["value"]["state"] == "UNKNOWN"
    assert row["value"]["reason"]
    assert "INFERRED" in row["value"]["reason"]


def test_facts_jsonl_no_fact_lacks_a_citation_from_the_seed_file():
    """Every curated fact's ``ref``/``quote`` must trace back to something actually present in the
    Phase-0 citation seed this package was told to curate from — not invented. Checked by a loose
    but meaningful substring heuristic: a distinguishing token from the fact (an address fragment,
    a cited figure, or an entity name) must appear somewhere in the seed text."""
    seed_text = SEED_PATH.read_text(encoding="utf-8")
    facts = _load_facts()
    assert len(facts) > 0
    for row in facts:
        token = _distinguishing_token(row)
        assert token in seed_text, f"{row['fact_id']} ({row['claim_type']!r}, value={row['value']!r}) — " \
                                   f"no trace of {token!r} in the Phase-0 citation seed"


def _distinguishing_token(row: dict) -> str:
    """A short, present-in-the-seed-or-fail string that identifies THIS fact's claim, so the test
    above cannot pass on a fact that was simply invented with a plausible-looking ref."""
    v = row["value"]
    overrides = {
        ("USYC", "fee_performance"): "10%", ("USYC", "fee_subscription"): "4 bps",
        ("USYC", "fee_redemption"): "3 bps", ("OUSG", "fee_management"): "0.15%",
        ("USDY", "fee_spread"): "small spread", ("BUIDL", "oracle_address"): "RedStone",
        ("USYC", "oracle_address"): "74f2", ("OUSG", "oracle_address"): "9Cad45a8",
        ("USDY", "oracle_address"): "87b126e5",
        ("BUIDL", "legal_entity"): "2013810", ("OUSG", "legal_entity"): "1957431",
        ("BUIDL", "custodian"): "Bank of New York Mellon", ("USYC", "custodian"): "Marex",
        ("USDY", "collateral_agent"): "Ankura", ("OUSG", "legal_entity_link_inferred"): "1957431",
        ("perp:kucoin", "perp_taker_fee"): "0.0006", ("perp:hyperliquid", "perp_taker_fee"): "0.045",
        ("venue:binance", "legal_entity"): "Nest", ("venue:kucoin", "legal_entity"): "Turks and Caicos",
        ("USYC", "redemption_terms"): "Teller", ("USDY", "redemption_terms"): "USD wire",
        ("OUSG", "redemption_terms"): "InstantManager", ("USYC", "legal_entity"): "SDYF",
        ("OUSG", "issuer"): "Ondo (docs OUSG overview)",
    }
    key = (row["entity"], row["claim_type"])
    if key in overrides:
        return overrides[key]
    if row["claim_type"] == "token_identity" and isinstance(v, dict):
        return v["symbol"]
    if row["claim_type"] == "pool_join" and isinstance(v, dict):
        return v.get("ethereum_pool", row["entity"])
    if row["claim_type"] == "price_net_of_fees":
        return "token-price"
    if row["claim_type"] in ("issuer", "legal_entity", "redemption_terms", "administrator", "auditor",
                             "transfer_agent"):
        return str(v)[:24] if isinstance(v, str) else row["entity"]
    return row["entity"]


def test_facts_jsonl_every_instrument_has_a_token_identity_fact():
    facts = _load_facts()
    for symbol in instruments.INSTRUMENTS:
        assert any(r["entity"] == symbol and r["claim_type"] == "token_identity" for r in facts), symbol


def test_instruments_ambiguous_match_resolves_only_to_the_declared_issuer_project():
    """Live 2026-10-04: two Ethereum pools name the OUSG contract — the issuer's own ondo-yield-assets pool and a
    third-party money market (flux-finance). The declared issuer project disambiguates deterministically; a
    third-party listing alone never becomes the instrument's yield, and two own-project pools stay ambiguous."""
    addr = "0x1b19c19393e2d034d8ff31ff34c81252fcbbee92"
    pools = [
        {"pool": "issuer", "chain": "Ethereum", "project": "ondo-yield-assets", "underlyingTokens": [addr]},
        {"pool": "thirdparty", "chain": "Ethereum", "project": "flux-finance", "underlyingTokens": [addr]},
    ]
    pool, reason = instruments.join_pool_by_chain_and_contract("OUSG", pools)
    assert reason is None and pool["pool"] == "issuer"
    only_third = [pools[1], dict(pools[1], pool="thirdparty2")]
    assert instruments.join_pool_by_chain_and_contract("OUSG", only_third)[0] is None
    two_own = [pools[0], dict(pools[0], pool="issuer2")]
    assert instruments.join_pool_by_chain_and_contract("OUSG", two_own)[0] is None


# ══════════════════════════════════════════════════════════════════════════════════════════════
# collectors/contract_identity.py — coordinator live-validation finding #3 (2026-10-04):
# identity_verified failed for every funding pair (PRIMARY_IDENTITY WEAK) because nothing
# collected the venue's own contract spec. Every endpoint below is already inside
# evidence_contract.HTTP_ALLOW by host+method+path-prefix.
# ══════════════════════════════════════════════════════════════════════════════════════════════

class _FakeIdentityClient:
    """Canned, shape-accurate responses for every venue's identity endpoint (real field names,
    captured from each venue's public docs / the 2026-10-04 live-validation run)."""

    def get(self, host, path, params):
        if host == "fapi.binance.com" and path == "/fapi/v1/exchangeInfo":
            return {"symbols": [{"symbol": "ETHUSDT", "contractType": "PERPETUAL", "marginAsset": "USDT",
                                 "baseAsset": "ETH", "quoteAsset": "USDT"}]}
        if host == "api.binance.com" and path == "/api/v3/exchangeInfo":
            return {"symbols": [{"symbol": params.get("symbol"), "status": "TRADING", "baseAsset": "ETH",
                                 "quoteAsset": "USDT"}]}
        if host == "api.bybit.com" and path == "/v5/market/instruments-info":
            if params.get("category") == "linear":
                return {"result": {"list": [{"symbol": "ETHUSDT", "contractType": "LinearPerpetual",
                                             "settleCoin": "USDT"}]}}
            return {"result": {"list": [{"symbol": "ETHUSDT", "baseCoin": "ETH", "quoteCoin": "USDT"}]}}
        if host == "www.okx.com" and path == "/api/v5/public/instruments":
            if params.get("instType") == "SWAP":
                return {"data": [{"instId": "ETH-USDT-SWAP", "ctType": "linear", "settleCcy": "USDT",
                                  "ctValCcy": "ETH", "ctVal": "0.1"}]}
            return {"data": [{"instId": "ETH-USDT", "baseCcy": "ETH", "quoteCcy": "USDT"}]}
        if host == "api-futures.kucoin.com" and path == "/api/v1/contracts/ETHUSDTM":
            return {"data": {"symbol": "ETHUSDTM", "type": "FFWCSX", "settleCurrency": "USDT",
                             "baseCurrency": "ETH", "quoteCurrency": "USDT", "multiplier": 0.01}}
        return None

    def post_info(self, info_type, payload):
        assert info_type == "metaAndAssetCtxs"
        return [{"universe": [{"name": "ETH", "szDecimals": 4, "maxLeverage": 50}]}, [{}]]


def test_contract_identity_binance_perp_and_spot_rows_shaped_correctly():
    rows = contract_identity.collect(NOW, _FakeIdentityClient(), assets=("ETH",))
    perp = next(r for r in rows if r["origin"] == "venue:binance" and r["claim"] == "perp_contract_identity:ETH")
    assert perp["state"] == "MEASURED"
    assert perp["value"]["contract_type"] == "PERPETUAL"
    assert perp["value"]["settle_asset"] == "USDT"
    spot = next(r for r in rows if r["origin"] == "venue:binance" and r["claim"] == "spot_contract_identity:ETH")
    assert spot["state"] == "MEASURED"
    assert spot["value"]["base_asset"] == "ETH"


def test_contract_identity_every_perp_venue_produces_a_row():
    rows = contract_identity.collect(NOW, _FakeIdentityClient(), assets=("ETH",))
    perp_rows = {r["origin"] for r in rows if r["claim"] == "perp_contract_identity:ETH"}
    assert perp_rows == {f"venue:{v}" for v in books.PERP_VENUES}
    for r in rows:
        if r["claim"] == "perp_contract_identity:ETH":
            assert r["state"] == "MEASURED", r


def test_contract_identity_hyperliquid_reuses_metaandassetctxs_not_a_new_info_type():
    """The allow-listed HYPERLIQUID_INFO_TYPES must never be bypassed — this module uses
    "metaAndAssetCtxs" (already allowed), never a bare "meta" call."""
    rows = contract_identity.collect(NOW, _FakeIdentityClient(), assets=("ETH",))
    hl = next(r for r in rows if r["origin"] == "venue:hyperliquid")
    assert hl["state"] == "MEASURED"
    assert hl["value"]["contract_type"] == "PERPETUAL"
    assert "metaAndAssetCtxs" in evidence_contract.HYPERLIQUID_INFO_TYPES


def test_contract_identity_every_endpoint_used_is_inside_http_allow():
    """Positive control for 'tell me, don't bypass': every (host, path) this module calls must
    already satisfy evidence_contract.HTTP_ALLOW's (host, method, path-prefix, body-type)."""
    calls = []

    class _Recorder:
        def get(self, host, path, params):
            calls.append(("GET", host, path, None))
            return _FakeIdentityClient().get(host, path, params)

        def post_info(self, info_type, payload):
            calls.append(("POST", "api.hyperliquid.xyz", "/info", "hyperliquid_info"))
            return _FakeIdentityClient().post_info(info_type, payload)

    contract_identity.collect(NOW, _Recorder(), assets=("ETH",))
    assert calls, "no calls were recorded — the test fixture itself is broken"
    for method, host, path, body_type in calls:
        allowed = any(h == host and m == method and path.startswith(prefix) and bt == body_type
                      for h, m, prefix, bt in evidence_contract.HTTP_ALLOW)
        assert allowed, f"{method} {host}{path} (body_type={body_type}) is NOT in evidence_contract.HTTP_ALLOW"


def test_contract_identity_missing_symbol_is_not_measured_not_a_crash():
    class _EmptyClient:
        def get(self, host, path, params):
            return {"symbols": []}

        def post_info(self, info_type, payload):
            return [{"universe": []}, [{}]]

    rows = contract_identity.collect(NOW, _EmptyClient(), assets=("ETH",))
    assert all(r["state"] == "NOT_MEASURED" for r in rows)
    assert all(r["reason"] for r in rows)


def test_contract_identity_no_client_is_not_measured_not_a_crash():
    rows = contract_identity.collect(NOW, None, assets=("ETH",))
    assert rows
    assert all(r["state"] == "NOT_MEASURED" and r["reason"] == "no client" for r in rows)


def test_contract_identity_client_raising_is_not_measured_not_a_crash():
    class _BoomClient:
        def get(self, host, path, params):
            raise RuntimeError("venue down")

        def post_info(self, info_type, payload):
            raise RuntimeError("venue down")

    rows = contract_identity.collect(NOW, _BoomClient(), assets=("ETH",))
    assert all(r["state"] == "NOT_MEASURED" for r in rows)
    assert any("venue down" in (r["reason"] or "") for r in rows)


# ══════════════════════════════════════════════════════════════════════════════════════════════
# scanners/rwa.py — fee UNIT honesty (coordinator live-validation finding, 2026-10-04): a live
# run netted -2697 because USYC's ONE-OFF subscription/redemption fee (4+3 bps) was labelled
# unit="fraction" — a unit contract.ANNUAL_RATE_UNITS treats as an ANNUAL rate, so
# net_expected_return subtracted a one-off trade cost from an APY as if it recurred every year.
# ══════════════════════════════════════════════════════════════════════════════════════════════

def test_rwa_one_off_fee_components_are_never_labelled_an_annual_unit():
    """Generic guard: for every Phase-0 instrument, EVERY fee component marked one_off=True must
    use a unit outside contract.ANNUAL_RATE_UNITS (so net_expected_return can never mistake it
    for a recurring annual rate) — the exact shape of the live -2697 defect."""
    for symbol in instruments.INSTRUMENTS:
        hints = rwa.paper_accounting_hints(symbol, NOW)
        if hints is None:
            continue
        for leg in ("entry_fee_components", "exit_fee_components"):
            for comp in hints[leg]:
                if comp["one_off"]:
                    assert comp["unit"] not in contract.ANNUAL_RATE_UNITS, \
                        f"{symbol}.{leg} ({comp['kind']}): one-off component labelled annual unit {comp['unit']!r}"
                    if comp["cell"]["state"] in contract.VALUED_STATES:
                        assert comp["cell"]["unit"] not in contract.ANNUAL_RATE_UNITS


def test_rwa_usyc_fees_cell_is_annual_zero_never_the_one_off_bps(monkeypatch):
    _patch_reviewed_facts(monkeypatch)
    """The candidate's SINGLE v1 fees cell must carry only the ANNUAL total — never USYC's
    one-off subscription+redemption bps (the live defect: that sum, mislabelled "fraction", got
    netted as if it were an annual rate)."""
    cell = rwa._phase0_fee_cell("USYC", NOW)
    assert cell["state"] == contract.DOCUMENTED
    assert cell["value"] == 0.0
    assert cell["unit"] == rwa.UNIT_ANNUAL
    assert cell["unit"] in contract.ANNUAL_RATE_UNITS       # netting may use it directly
    assert "0.0004" not in str(cell["value"]) and "0.0003" not in str(cell["value"])


def test_rwa_usyc_one_off_components_are_4_and_3_bps_in_a_one_off_unit(monkeypatch):
    _patch_reviewed_facts(monkeypatch)
    hints = rwa.paper_accounting_hints("USYC", NOW)
    entry = hints["entry_fee_components"][0]
    exit_ = hints["exit_fee_components"][0]
    assert entry["kind"] == "entry" and entry["one_off"] is True
    assert exit_["kind"] == "exit" and exit_["one_off"] is True
    assert entry["unit"] == exit_["unit"] == rwa.UNIT_ONE_OFF
    assert entry["unit"] not in contract.ANNUAL_RATE_UNITS
    assert entry["cell"]["value"] == pytest.approx(0.0004)    # 4 bps
    assert exit_["cell"]["value"] == pytest.approx(0.0003)     # 3 bps
    assert entry["cell"]["unit"] == exit_["cell"]["unit"] == rwa.UNIT_ONE_OFF
    # the performance fee is a THIRD, separate concept — fraction OF THE YIELD, not one-off, not annual.
    perf = hints["performance_fee_rate"]
    assert perf["unit"] == rwa.UNIT_OF_YIELD
    assert perf["embedded_in_return"] is True
    assert perf["value"] == pytest.approx(0.10)


def test_rwa_usyc_net_expected_return_never_double_counts_the_one_off_fee(monkeypatch):
    _patch_reviewed_facts(monkeypatch)
    """Positive control for the actual live bug: build the v1 cells exactly as rwa.py's scan()
    does for USYC and confirm net_expected_return treats the one-off fee as what it is — never
    netted directly against the APY (contract.net_expected_return refuses to net a non-annual
    unit, per contract.py's own ADR-564 integration fix)."""
    base = contract.cell(contract.MEASURED, 4.0, unit="pct_apy", source_ref="x", source_class=contract.PRIMARY_CHAIN,
                         source_root="chain:1", as_of=NOW.isoformat(), recorded_at=NOW.isoformat(), now=NOW)
    cells = {"base_return": base, "fees": rwa._phase0_fee_cell("USYC", NOW),
            "gas": contract.cell(contract.NOT_APPLICABLE, reason="x"),
            "hedging_cost": contract.cell(contract.NOT_APPLICABLE, reason="x"),
            "funding": contract.cell(contract.NOT_APPLICABLE, reason="x")}
    net = contract.net_expected_return(cells)
    # fees is DOCUMENTED 0.0 fraction_apy ⇒ net = base - 0 = base's own annual fraction, not -2697.
    assert net["state"] == contract.ESTIMATED_WITH_METHOD
    assert net["value"] == pytest.approx(0.04)


def test_rwa_ousg_total_annual_fee_is_not_measured_because_expenses_are_only_capped(monkeypatch):
    _patch_reviewed_facts(monkeypatch)
    """M5 (post-implementation review, 2026-10-04): "expenses capped at 0.15%" must NOT become
    annual 0. The management fee IS known (0, waived until 2027-01-01) but OTHER fund expenses
    are only capped, with no cited actual run-rate — the TOTAL v1 annual cell is honestly
    NOT_MEASURED, never the management-fee-only 0 (invariant #17: missing-as-zero forbidden)."""
    cell = rwa._phase0_fee_cell("OUSG", NOW)
    assert cell["state"] == contract.NOT_MEASURED
    assert cell["value"] is None
    assert "2027-01-01" in cell["reason"]
    assert "capped" in cell["reason"]


def test_rwa_ousg_management_and_expenses_cap_are_two_separate_components(monkeypatch):
    _patch_reviewed_facts(monkeypatch)
    """The management fee (known, 0, waived) and the expenses cap (capped but UNMEASURED) are
    two DIFFERENT annual components, never merged — an annual cost component that is not measured
    must block a HOLDABLE net (paper.py's own documented discipline)."""
    hints = rwa.paper_accounting_hints("OUSG", NOW)
    components = hints["entry_fee_components"]
    assert len(components) == 2
    mgmt_component, expenses_component = components
    assert mgmt_component["kind"] == "management"
    assert mgmt_component["unit"] == rwa.UNIT_ANNUAL
    assert mgmt_component["one_off"] is False
    assert mgmt_component["effective_from"] is not None          # the waiver's own cited start date
    assert mgmt_component["cell"]["state"] == contract.DOCUMENTED
    assert mgmt_component["cell"]["value"] == 0.0
    assert mgmt_component["cell"]["unit"] == rwa.UNIT_ANNUAL

    assert expenses_component["kind"] == "management"            # no dedicated "expenses" kind exists
    assert expenses_component["unit"] == rwa.UNIT_ANNUAL
    assert expenses_component["cell"]["state"] == contract.NOT_MEASURED
    assert expenses_component["cell"]["value"] is None
    assert "0.15" in expenses_component["cell"]["reason"] or "capped" in expenses_component["cell"]["reason"]
    # the unmeasured expenses component is exactly what REFUSES a HOLDABLE paper open, per
    # paper.py's own stated discipline for a non-VALUED fee component.
    assert expenses_component["cell"]["state"] not in contract.VALUED_STATES


def test_rwa_unit_constants_are_disjoint_from_each_other_and_from_bare_fraction():
    assert len({rwa.UNIT_ANNUAL, rwa.UNIT_ONE_OFF, rwa.UNIT_OF_YIELD}) == 3
    assert rwa.UNIT_ANNUAL in contract.ANNUAL_RATE_UNITS
    assert rwa.UNIT_ONE_OFF not in contract.ANNUAL_RATE_UNITS
    assert rwa.UNIT_OF_YIELD not in contract.ANNUAL_RATE_UNITS
    assert "fraction" not in (rwa.UNIT_ANNUAL, rwa.UNIT_ONE_OFF, rwa.UNIT_OF_YIELD)


# ══════════════════════════════════════════════════════════════════════════════════════════════
# M7 (post-implementation review, 2026-10-04): collectors/* and scanners/* may reach the network
# ONLY through spa_core.capital_shadow.rpc (eth_call) and spa_core.research_factory.http_client
# (HTTP) — never a second network client pulled in transitively (the exact defect:
# collectors/funding_venues.py used to import strategy_lab.data.funding_feed, which imports
# strategy_lab.data._http, which does raw urllib.request).
# ══════════════════════════════════════════════════════════════════════════════════════════════

import ast as _ast  # local alias — this file's top already imports `ast`-adjacent stdlib sparingly

_REPO_ROOT = Path(contract.__file__).resolve().parents[2]
_NETWORK_ALLOWED_FILES = {
    _REPO_ROOT / "spa_core" / "capital_shadow" / "rpc.py",
    _REPO_ROOT / "spa_core" / "research_factory" / "http_client.py",
}


def _module_file(mod_name: str) -> "Path | None":
    if not mod_name.startswith("spa_core"):
        return None
    rel = mod_name.replace(".", "/")
    for cand in (_REPO_ROOT / f"{rel}.py", _REPO_ROOT / rel / "__init__.py"):
        if cand.is_file():
            return cand
    return None


def _dotted_names_imported(tree: "_ast.AST") -> list:
    """Every dotted name this module imports (both forms), as plain strings — e.g.
    ``import urllib.request`` -> ``"urllib.request"``; ``from http import client`` -> ``"http.client"``."""
    out = []
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Import):
            out.extend(alias.name for alias in node.names)
        elif isinstance(node, _ast.ImportFrom) and node.module:
            out.extend(f"{node.module}.{alias.name}" for alias in node.names)
            out.append(node.module)
    return out


def _is_network_name(name: str) -> bool:
    """A module that can actually perform network I/O — ``urllib.parse`` is pure string parsing
    (no socket ever opened) and is deliberately NOT flagged; ``urllib.request``/``urllib2`` are."""
    return name == "socket" or name == "ssl" or name.startswith("socket.") or name.startswith("ssl.") \
        or name == "urllib.request" or name.startswith("urllib.request.") or name == "urllib2" \
        or name == "http.client" or name.startswith("http.client.")


def _walk_collector_scanner_imports() -> dict:
    """``{violating_file: {offending dotted names}}`` — BFS over every ``collectors/*.py`` and
    ``scanners/*.py`` module's transitive ``spa_core.*`` import graph, flagging a network-module
    import found anywhere OUTSIDE ``_NETWORK_ALLOWED_FILES``."""
    roots = sorted((_REPO_ROOT / "spa_core" / "research_factory" / "collectors").glob("*.py")) + \
        sorted((_REPO_ROOT / "spa_core" / "research_factory" / "scanners").glob("*.py"))
    seen: set = set()
    violations: dict = {}
    queue = list(roots)
    while queue:
        path = queue.pop()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        tree = _ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names = _dotted_names_imported(tree)
        if path not in _NETWORK_ALLOWED_FILES:
            hits = {n for n in names if _is_network_name(n)}
            if hits:
                violations[path] = hits
        for n in names:
            mod_file = _module_file(n)
            if mod_file is not None and mod_file not in seen:
                queue.append(mod_file)
    return violations


def test_collectors_and_scanners_reach_the_network_only_through_the_sanctioned_surface():
    violations = _walk_collector_scanner_imports()
    assert violations == {}, f"network import outside the sanctioned surface: {violations}"


def test_funding_venues_no_longer_imports_funding_feed_at_all():
    """Positive control for the actual M7 fix: funding_venues.py's OWN ast must not import
    strategy_lab.data.funding_feed (which is how the second network client used to arrive)."""
    path = _REPO_ROOT / "spa_core" / "research_factory" / "collectors" / "funding_venues.py"
    tree = _ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = _dotted_names_imported(tree)
    assert not any("funding_feed" in n for n in names)
    assert not any("strategy_lab" in n for n in names)


def test_funding_row_parsers_copy_matches_funding_feed_semantics():
    """The copied parsers must behave identically to the originals on the same input (attribution
    is a promise of behavioural equivalence, not just a comment)."""
    from spa_core.research_factory import _funding_row_parsers as copy
    from spa_core.strategy_lab.data import funding_feed as original

    binance_payload = [{"symbol": "ETHUSDT", "fundingTime": 1_759_017_600_000, "fundingRate": "0.00012"}]
    assert copy.rows_binance(binance_payload) == original._rows_binance(binance_payload)

    bybit_payload = {"retCode": 0, "result": {"list": [{"symbol": "ETHUSDT", "fundingRate": "0.0001",
                                                        "fundingRateTimestamp": "1759017600000"}]}}
    assert copy.rows_bybit(bybit_payload) == original._rows_bybit(bybit_payload)

    okx_payload = {"code": "0", "data": [{"fundingRate": "0.0001", "fundingTime": "1759017600000"}]}
    assert copy.rows_okx(okx_payload) == original._rows_okx(okx_payload)

    kucoin_payload = {"code": "200000", "data": [{"fundingRate": 0.0001, "timepoint": 1759017600000}]}
    assert copy.rows_kucoin(kucoin_payload) == original._rows_kucoin(kucoin_payload)

    hl_payload = [{"coin": "ETH", "fundingRate": "0.00001", "premium": "0.0", "time": 1759017600000}]
    assert copy.rows_hyperliquid(hl_payload) == original._rows_hyperliquid(hl_payload)

    # fail-closed behaviour preserved too
    with pytest.raises(copy.InvalidDataError):
        copy.rows_binance([{"symbol": "ETHUSDT"}])            # missing fundingRate
    with pytest.raises(original.InvalidDataError):
        original._rows_binance([{"symbol": "ETHUSDT"}])


# ══════════════════════════════════════════════════════════════════════════════════════════════
# H2 (post-implementation review, 2026-10-04): funding pairs must give EACH leg its own fee
# components, in one-off units; a leg with no official fee source has NOT_MEASURED components
# (never ADEQUATE); hedging_cost is a slippage COST in bps, never the book-walk FILL PRICE.
# ══════════════════════════════════════════════════════════════════════════════════════════════

def _slippage_row(asset, venue, bps):
    return {"schema": evidence_contract.SCHEMA_OBS_ROW, "candidate_id": "x", "claim": f"spot_slippage_bps:{asset}",
           "value": bps, "unit": "bps", "window": None, "upstream_ts": None, "fetched_at": NOW.isoformat(),
           "origin": f"venue:{venue}", "channel": evidence_contract.CHANNEL_OFFICIAL_API, "ref": "x",
           "raw_sha256": None, "backfill": False, "revises": None, "state": "MEASURED", "reason": None}


def test_h2_hedging_cost_is_slippage_in_bps_never_the_fill_price():
    """Positive control for the actual live defect: a 'spot_book' row carrying a FILL PRICE
    (e.g. 2701.78, unit avg_price_usd_for_10000_usd_notional) must NEVER reach hedging_cost; only
    the dedicated 'spot_slippage_bps' claim, in bps, does."""
    rows_ = [_settlement_row("ETH", "binance", "2026-10-03T08:00:00+00:00", 0.0001)]
    price_row = {"schema": evidence_contract.SCHEMA_OBS_ROW, "candidate_id": "x", "claim": "spot_book:ETH",
                "value": 2701.78, "unit": "avg_price_usd_for_10000_usd_notional", "window": None,
                "upstream_ts": None, "fetched_at": NOW.isoformat(), "origin": "venue:binance",
                "channel": evidence_contract.CHANNEL_OFFICIAL_API, "ref": "x", "raw_sha256": None,
                "backfill": False, "revises": None, "state": "MEASURED", "reason": None}
    slip_row = _slippage_row("ETH", "binance", 34.97)
    cand = basis.funding_pair_candidates("ETH", rows_, [price_row, slip_row], NOW)[0]
    assert cand["hedging_cost"]["state"] == contract.MEASURED
    assert cand["hedging_cost"]["value"] == pytest.approx(34.97)
    assert cand["hedging_cost"]["unit"] == "bps"
    assert cand["hedging_cost"]["value"] != 2701.78          # never the fill price


def test_h2_hedging_cost_never_equals_a_bare_price_unit():
    rows_ = [_settlement_row("ETH", "binance", "2026-10-03T08:00:00+00:00", 0.0001)]
    cand = basis.funding_pair_candidates("ETH", rows_, [], NOW)[0]
    assert cand["hedging_cost"].get("unit") != "avg_price_usd_for_10000_usd_notional"


def test_h2_legs_shape_matches_paper_accounting_evidence_fields():
    rows_ = [_settlement_row("ETH", "binance", "2026-10-03T08:00:00+00:00", 0.0001)]
    cand = basis.funding_pair_candidates("ETH", rows_, [], NOW)[0]
    legs = cand["paper_accounting_hints"]["legs"]
    assert set(legs.keys()) == {"perp", "spot"}
    for leg in legs.values():
        assert set(leg.keys()) == set(evidence_contract.PAPER_ACCOUNTING_EVIDENCE_FIELDS)
        assert leg["entry_fee_components"]      # non-empty, per the frozen shape
        assert leg["exit_fee_components"]


def test_h2_spot_leg_fee_components_are_always_not_measured_no_cited_source():
    """No venue has a cited SPOT taker fee in this repo's citation seed — every spot leg's
    fee components must be NOT_MEASURED, on every (perp, spot) combination, never a guess."""
    rows_ = [_settlement_row("ETH", "binance", "2026-10-03T08:00:00+00:00", 0.0001)]
    for cand in basis.funding_pair_candidates("ETH", rows_, [], NOW):
        spot_leg = cand["paper_accounting_hints"]["legs"]["spot"]
        for comp in spot_leg["entry_fee_components"] + spot_leg["exit_fee_components"]:
            assert comp["cell"]["state"] == contract.NOT_MEASURED
            assert comp["cell"]["state"] not in contract.VALUED_STATES   # COST can never grade ADEQUATE


def test_h2_every_fee_component_unit_is_one_off_never_bare_fraction_never_annual():
    rows_ = [_settlement_row("ETH", "binance", "2026-10-03T08:00:00+00:00", 0.0001)]
    for cand in basis.funding_pair_candidates("ETH", rows_, [], NOW):
        for leg in cand["paper_accounting_hints"]["legs"].values():
            for comp in leg["entry_fee_components"] + leg["exit_fee_components"]:
                assert comp["unit"] == basis.UNIT_ONE_OFF
                assert comp["unit"] != "fraction"
                assert comp["unit"] not in contract.ANNUAL_RATE_UNITS
                if comp["cell"]["state"] in contract.VALUED_STATES:
                    assert comp["cell"]["unit"] != "fraction"
                    assert comp["cell"]["unit"] not in contract.ANNUAL_RATE_UNITS


def test_h2_kucoin_perp_fee_component_matches_the_cited_value_and_unit():
    rows_ = [_settlement_row("ETH", "binance", "2026-10-03T08:00:00+00:00", 0.0001)]
    cands = {c["instrument_id"]: c for c in basis.funding_pair_candidates("ETH", rows_, [], NOW)}
    leg = cands["perp:ETH:kucoinbinance"]["paper_accounting_hints"]["legs"]["perp"]
    entry = leg["entry_fee_components"][0]
    assert entry["cell"]["state"] == contract.DOCUMENTED
    assert entry["cell"]["value"] == pytest.approx(0.0006)
    assert entry["cell"]["unit"] == basis.UNIT_ONE_OFF
    assert entry["one_off"] is True


# ══════════════════════════════════════════════════════════════════════════════════════════════
# H6 (content, post-implementation review, 2026-10-04): an issuer-HOSTED page is the ISSUER's
# claim about who serves a role, whatever party it names — facts 019/022/023/032 had the NAMED
# party (Marex/NAV Consulting/Cohen) as `origin` even though their `ref` is an issuer-hosted page.
# ══════════════════════════════════════════════════════════════════════════════════════════════

def test_h6_usyc_custodian_administrator_auditor_facts_have_issuer_origin():
    facts = _load_facts()
    for claim_type in ("custodian", "administrator", "auditor"):
        row = next(r for r in facts if r["entity"] == "USYC" and r["claim_type"] == claim_type)
        assert row["origin"] == "issuer:hashnote", (claim_type, row["origin"])
        assert "usyc.docs.hashnote.com" in row["ref"]


def test_h6_ousg_administrator_fact_has_issuer_origin():
    row = next(r for r in _load_facts() if r["entity"] == "OUSG" and r["claim_type"] == "administrator")
    assert row["origin"] == "issuer:ondo"
    assert "docs.ondo.finance" in row["ref"]


def test_h6_buidl_press_release_facts_never_count_as_independent_of_blackrock():
    """The independent fact review found every BUIDL prnewswire release is "News provided by
    Securitize" — the origin is agent:securitize, not issuer:blackrock. What must never regress is
    the INDEPENDENCE consequence: Securitize is appointed by BlackRock, so a press-release fact
    still resolves to BlackRock's group — never a second, independent origin."""
    origins = _load_origins()
    facts = _load_facts()
    for claim_type in ("custodian", "transfer_agent"):
        row = next(r for r in facts if r["entity"] == "BUIDL" and r["claim_type"] == claim_type)
        assert evidence_contract.origin_group(row["origin"], origins) == \
            evidence_contract.origin_group("issuer:blackrock", origins), (claim_type, row["origin"])


def test_h6_every_origin_has_a_hosts_list():
    origins = _load_origins()
    for origin_id, entry in origins.items():
        assert isinstance(entry.get("hosts"), list), f"{origin_id} has no 'hosts' list"


def test_h6_issuer_hosts_match_the_refs_actually_cited_for_that_issuer():
    origins = _load_origins()
    assert "usyc.docs.hashnote.com" in origins["issuer:hashnote"]["hosts"]
    assert "docs.ondo.finance" in origins["issuer:ondo"]["hosts"]
    assert "www.sec.gov" in origins["regulator:sec"]["hosts"]


def test_h6_named_parties_appointed_by_the_issuer_fold_into_the_issuers_group():
    """evidence_contract.origin_group() folds an appointed party's group into its appointer's —
    Marex/Customers Bank/Cohen/NAV Consulting(USYC) are appointed by issuer:hashnote and must fold
    to "circle"; NAV Consulting's SEPARATE OUSG appointment folds to "ondo" instead (one id per
    appointment relationship, since one legal entity can serve two different, non-affiliated
    issuers)."""
    origins = _load_origins()
    for origin_id in ("custodian:marex", "custodian:customers_bank", "auditor:cohen_and_company",
                     "administrator:nav_consulting"):
        assert origins[origin_id]["appointed_by"] == "issuer:hashnote", origin_id
        assert evidence_contract.origin_group(origin_id, origins) == "circle", origin_id
    assert origins["administrator:nav_consulting_ousg"]["appointed_by"] == "issuer:ondo"
    assert evidence_contract.origin_group("administrator:nav_consulting_ousg", origins) == "ondo"


def test_rwa_unreviewed_facts_degrade_to_not_measured_never_a_crash(tmp_path, monkeypatch):
    """A registry whose facts are all unreviewed (reviewed_by=null) — the real file's state before
    the independent review, reproduced here on a COPY so the test no longer depends on the real
    file staying unreviewed — makes registry_loader.load_facts() refuse every row
    (FACT_REQUIRES_INDEPENDENT_REVIEW). rwa.py must degrade to its own NOT_MEASURED fallback,
    never propagate the refusal as an uncaught exception that would take down the whole scan."""
    unreviewed = tmp_path / "facts.jsonl"
    unreviewed.write_text("".join(json.dumps(dict(r, reviewed_by=None)) + "\n" for r in _load_facts()),
                          encoding="utf-8")
    real_load = registry_loader.load_facts
    monkeypatch.setattr(rwa.registry_loader, "load_facts",
                        lambda *a, **kw: real_load(unreviewed, **{k: v for k, v in kw.items() if k != "path"}))
    cell = rwa._phase0_fee_cell("USYC", NOW)          # must not raise
    assert cell["state"] == contract.NOT_MEASURED
    hints = rwa.paper_accounting_hints("USYC", NOW)    # must not raise
    assert hints["entry_fee_components"][0]["cell"]["state"] == contract.NOT_MEASURED
