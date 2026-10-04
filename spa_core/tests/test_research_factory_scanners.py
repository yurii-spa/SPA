"""Tests for the Package-B Research Factory scanners (ADR-560 RM-EXPAND-01).

Covers: fixture-shaped runs of each of the five scanners, a run against a read-only copy of
PRODUCTION data (schema/contract conformance), the three named invariants (never a ticker as an
instrument id; the aggregate T-bill floor never assigned to an instrument; funding inversion
never clamped), the on-chain allow-list, and a handful of hand-written mutation checks (a
positive/negative pair per guard) called out individually below.

# FROZEN-DATE-OK: injected-clock — every judgement gets now=NOW and every fixture timestamp is
# derived from that same literal anchor (never the wall clock); see NOW/ISO_NOW below.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

if __package__ in (None, ""):                      # pragma: no cover — direct-run convenience
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.research_factory import contract, counterparty_registry, onchain
from spa_core.research_factory.scanners import SCANNERS, basis, cash_treasury, discovery, rwa, trading_research

# ── the one fixed clock every test in this file uses ────────────────────────────────────────────
NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)
ISO_NOW = NOW.isoformat()


def iso(hours_ago: float) -> str:
    """A literal ISO timestamp offset from the fixed NOW anchor above — never the wall clock."""
    return (NOW - timedelta(hours=hours_ago)).isoformat()


PROD_DATA = Path("/private/tmp/claude-501/-Users-yuriikulieshov-Documents-SPA-Claude"
                "/77953ab2-8e9a-4d56-8ecb-16448ad02813/scratchpad/expand/proddata")


# ══════════════════════════════════════════════════════════════════════════════════════════════
# Appendix-I / contract-shape conformance — shared across every scanner result
# ══════════════════════════════════════════════════════════════════════════════════════════════

def assert_scan_result_shape(res: dict) -> None:
    for key in ("scanner", "domain", "as_of", "status", "reason", "denominators", "candidates",
               "unresolved", "observations", "counterparty", "existing_book_roots"):
        assert key in res, f"scan() result missing key {key!r}"
    assert res["status"] in ("OK", "PARTIAL", "UNAVAILABLE")
    assert res["domain"] in contract.DOMAINS
    for den_key in ("scanned", "discovered", "truncated"):
        assert den_key in res["denominators"]
    assert isinstance(res["denominators"]["discovered"], int)
    for c in res["candidates"]:
        assert_candidate_shape(c)
    for u in res["unresolved"]:
        assert set(u.keys()) >= {"name", "reason"}
        assert isinstance(u["reason"], str) and u["reason"]
    cids = {c["candidate_id"] for c in res["candidates"]}
    for cid, obs in res["observations"].items():
        assert cid in cids, f"observation for unknown candidate_id {cid}"
        assert_cell_shape(obs["observed_return"])
        if obs.get("realised_index") is not None:
            assert_cell_shape(obs["realised_index"])
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", obs["period"])
    for cid, cp in res["counterparty"].items():
        assert cid in cids, f"counterparty for unknown candidate_id {cid}"
        assert set(cp.keys()) == {"roles", "dimensions"}
        for role in contract.COUNTERPARTY_ROLES:
            assert role in cp["roles"], f"counterparty roles missing {role!r}"
            assert cp["roles"][role]["state"] in contract.CP_STATES
        for dim in contract.COUNTERPARTY_DIMENSIONS:
            assert dim in cp["dimensions"], f"counterparty dimensions missing {dim!r}"
            assert cp["dimensions"][dim]["state"] in contract.CP_STATES
    for root in res["existing_book_roots"]:
        assert isinstance(root, str) and root


def assert_cell_shape(c: dict) -> None:
    """Every field contract.cell() would have produced is present, and the state/value/reason
    relationship contract.cell() enforces at construction time holds — re-checked here because a
    scanner could in principle hand-build a dict that skips the constructor."""
    assert isinstance(c, dict)
    assert c.get("state") in contract.VALUE_STATES, c
    if c["state"] in contract.VALUED_STATES:
        assert c["value"] is not None and not isinstance(c["value"], bool)
        if isinstance(c["value"], (int, float)):
            assert c["value"] == c["value"] and abs(c["value"]) != float("inf")  # finite, not NaN
        if c["state"] in (contract.MEASURED, contract.DOCUMENTED):
            assert c["source_ref"] and c["source_class"] and c["source_root"]
        if c["state"] == contract.MEASURED:
            assert c["source_class"] not in contract.NOT_MEASURABLE_CLASSES
            assert contract.parse_ts(c["as_of"]) is not None
        if c["state"] == contract.ESTIMATED_WITH_METHOD:
            assert c["method"]
    else:
        assert c["value"] is None
        assert c["reason"], f"non-valued cell with no reason: {c}"


def assert_candidate_shape(c: dict) -> None:
    for field in contract.CANDIDATE_FIELDS:
        assert field in c, f"candidate missing field {field!r}"
    for f in contract.CELL_FIELDS + contract.RISK_FIELDS:
        assert_cell_shape(c[f])
    assert c["mechanism_id"] in contract.MECHANISMS
    assert c["asset_class"] == contract.MECHANISMS[c["mechanism_id"]]["asset_class"]
    assert contract.canonical_network(c["network"]) == c["network"] or c["network"] in contract.CHAIN_ALIASES.values()
    assert contract.instrument_id_ok(c["instrument_id"]), f"bad instrument_id {c['instrument_id']!r}"
    # review #2 (CRITICAL): identity is the held instrument, never a ticker.
    assert c["instrument_id"] != c["instrument"]
    assert not re.fullmatch(r"[A-Za-z0-9_\-]{1,15}", c["instrument_id"]), (
        f"instrument_id {c['instrument_id']!r} looks like a bare ticker, not a canonical id")
    # A owns admission_state/paper_status/evidence_maturity — a scanner never sets them.
    assert c["admission_state"] is None
    assert c["paper_status"] is None
    assert c["evidence_maturity"] is None
    # exposure_key / candidate_id are exactly what contract.py would derive from these fields.
    # c["network"] is ALREADY canonical (full_candidate stores the canonicalised form), and
    # contract.canonical_network() is not idempotent on an already-canonical id (it only knows
    # ALIAS spellings) — so the expected key is built directly from the canonical form rather than
    # re-running it through exposure_key()/canonical_network() a second time.
    expected_key = f"v{c['exposure_key_version']}|{c['mechanism_id']}|{c['instrument_id'].lower()}|{c['network']}"
    assert c["exposure_key"] == expected_key
    assert c["candidate_id"] == contract.candidate_id(c["exposure_key"])


# ══════════════════════════════════════════════════════════════════════════════════════════════
# cash_treasury — fixtures
# ══════════════════════════════════════════════════════════════════════════════════════════════

def _write(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def _cash_treasury_fixture(tmp_path: Path) -> Path:
    _write(tmp_path / "adapter_status.json", {
        "adapters": {
            "spark_susds": {"live_apy": 2.5, "live_apy_as_of": iso(1), "live_apy_fresh": True,
                            "apy_base": 2.5, "apy_reward": 0.0, "tvl_usd": 4.0e9, "tvl_source": "live"},
            "sdai": {"live_apy": 1.2, "live_apy_as_of": iso(1), "live_apy_fresh": True,
                    "apy_base": 1.2, "apy_reward": 0.0, "tvl_usd": 2.0e8, "tvl_source": "live"},
        },
    })
    _write(tmp_path / "sky_status.json", {"gsm_hours": 48.0, "source": "onchain", "last_checked": iso(1)})
    # USTB (Invesco) / USCC (Bitwise) are NOT in the 11-asset rwa_safety_board.json — this
    # scanner owns them (review M1). USYC/BUIDL (board-covered) are deliberately absent from this
    # fixture; see test_cash_treasury_skips_safety_board_funds for the explicit skip assertion.
    _write(tmp_path / "market_data" / "rwa_floor.json", {
        "generated_at": iso(2),
        "floor_apy_pct": 99.0,          # deliberately far from every per-pool rate below
        "tvl_weighted_apy_pct": 99.0, "median_apy_pct": 99.0,
        "pools": [
            {"label": "invesco-ustb:USTB", "apy_pct": 3.1, "tvl_usd": 1.0e9,
             "pool": "1910847a-f8b5-40ce-a1ab-1dafdded5fbb"},
            {"label": "bitwise-uscc:USCC", "apy_pct": 3.7, "tvl_usd": 9.0e8,
             "pool": "aff74ce8-4fe3-462b-af11-542cc16d24b2"},
        ],
    })
    _write(tmp_path / "current_positions.json", {"feed_coverage": {"live_adapters": ["spark_susds", "sdai"]},
                                                 "positions": {}})
    return tmp_path


def test_cash_treasury_fixture_basic():
    tmp = _cash_treasury_fixture(Path("/tmp/spa_rf_ct_fixture_1"))
    res = cash_treasury.scan(tmp, NOW)
    assert_scan_result_shape(res)
    assert res["status"] == "OK"
    symbols = {c["instrument"] for c in res["candidates"]}
    assert symbols == {"sUSDS", "sDAI", "USTB", "USCC"}
    assert set(res["existing_book_roots"]) == {cash_treasury.ROOT_SKY_SAVINGS}
    susds = [c for c in res["candidates"] if c["instrument"] == "sUSDS"][0]
    assert susds["base_return"]["value"] == 2.5
    assert susds["underlying_root"] == cash_treasury.ROOT_SKY_SAVINGS
    assert susds["economic_driver_key"] == "SKY_SSR"


def test_cash_treasury_never_assigns_the_aggregate_floor_to_an_instrument():
    """The named invariant: ``floor_apy_pct``/``tvl_weighted_apy_pct``/``median_apy_pct`` (the
    TVL-weighted AGGREGATE) must never appear as a candidate's ``base_return`` value — only a
    per-pool ``apy_pct`` row may. The fixture pins the aggregate to 99.0, far from any per-pool
    rate, so any leak is unmissable."""
    tmp = _cash_treasury_fixture(Path("/tmp/spa_rf_ct_fixture_2"))
    res = cash_treasury.scan(tmp, NOW)
    for c in res["candidates"]:
        if c["mechanism_id"] == "TOKENISED_TREASURY":
            assert c["base_return"]["value"] != 99.0
            assert c["base_return"]["value"] in (3.1, 3.7)


def test_cash_treasury_adapter_status_missing_is_partial_not_unavailable(tmp_path):
    _write(tmp_path / "market_data" / "rwa_floor.json", {"generated_at": iso(1), "pools": []})
    res = cash_treasury.scan(tmp_path, NOW)
    assert res["status"] in ("PARTIAL", "OK")
    assert len(res["unresolved"]) == 2            # neither spark_susds nor sdai resolvable


def test_cash_treasury_both_inputs_missing_is_unavailable(tmp_path):
    res = cash_treasury.scan(tmp_path, NOW)
    assert res["status"] == "UNAVAILABLE"
    assert res["candidates"] == []


def test_cash_treasury_malformed_json_is_named_not_a_crash(tmp_path):
    (tmp_path / "adapter_status.json").write_text("{not json", encoding="utf-8")
    res = cash_treasury.scan(tmp_path, NOW)  # must not raise
    assert res["status"] == "UNAVAILABLE"
    assert "unreadable" in res["reason"]


# ── post-implementation review: M1 (one T-bill track per fund) ─────────────────────────────────
def test_cash_treasury_skips_safety_board_funds(tmp_path):
    """review M1: rwa.py owns every rwa_safety_board.json fund exclusively. A rwa_floor.json pool
    whose symbol IS on the board (BUIDL here) must never be emitted by cash_treasury, even though
    it is a perfectly good per-pool rate row."""
    _write(tmp_path / "adapter_status.json", {"adapters": {}})
    _write(tmp_path / "market_data" / "rwa_floor.json", {
        "generated_at": iso(1),
        "pools": [
            {"label": "blackrock-buidl:BUIDL", "apy_pct": 3.7, "tvl_usd": 9.0e8,
             "pool": "590d770e-ed5d-4c8d-ad96-5178c2072295"},
            {"label": "invesco-ustb:USTB", "apy_pct": 3.1, "tvl_usd": 1.0e9,
             "pool": "1910847a-f8b5-40ce-a1ab-1dafdded5fbb"},
        ],
    })
    res = cash_treasury.scan(tmp_path, NOW)
    symbols = {c["instrument"] for c in res["candidates"]}
    assert "BUIDL" not in symbols
    assert "USTB" in symbols


def test_cash_treasury_and_rwa_never_emit_the_same_fund(tmp_path):
    """review M1 test: 'no fund is emitted by two scanners' — run BOTH scanners on the same
    data_dir (BUIDL present in both rwa_safety_board.json and rwa_floor.json, as it is in prod)
    and assert the symbol sets do not intersect."""
    _write(tmp_path / "adapter_status.json", {"adapters": {}})
    _write(tmp_path / "market_data" / "rwa_floor.json", {
        "generated_at": iso(1),
        "pools": [
            {"label": "blackrock-buidl:BUIDL", "apy_pct": 3.7, "tvl_usd": 9.0e8,
             "pool": "590d770e-ed5d-4c8d-ad96-5178c2072295"},
            {"label": "invesco-ustb:USTB", "apy_pct": 3.1, "tvl_usd": 1.0e9,
             "pool": "1910847a-f8b5-40ce-a1ab-1dafdded5fbb"},
        ],
    })
    _write(tmp_path / "rwa_safety_board.json", {
        "generated_at": iso(1),
        "assets": [{"symbol": "BUIDL", "issuer": "BlackRock / Securitize", "redemption_documented": True,
                   "redemption_delay_days": 1.0, "redemption_fee_bps": 0.0, "exit_capacity_72h_usd": 0.0,
                   "transfer_restricted": True, "nav_source": "off_chain_estimate"}],
    })
    ct_res = cash_treasury.scan(tmp_path, NOW)
    rwa_res = rwa.scan(tmp_path, NOW)
    ct_syms = {c["instrument"].upper() for c in ct_res["candidates"]}
    rwa_syms = {c["instrument"].upper() for c in rwa_res["candidates"]}
    assert not (ct_syms & rwa_syms), f"fund(s) emitted by both scanners: {ct_syms & rwa_syms}"
    assert "BUIDL" in rwa_syms and "USTB" in ct_syms


def test_fund_roots_ousg_and_usdy_are_distinct():
    """review M1 test: OUSG and USDY share one DeFiLlama project slug ('ondo-yield-assets') but
    are two DIFFERENT Ondo funds — the shared root table must never merge them."""
    assert cash_treasury.FUND_ROOTS["OUSG"] != cash_treasury.FUND_ROOTS["USDY"]
    assert "ondo-yield-assets" not in cash_treasury.FUND_ROOTS["OUSG"]
    assert "ondo-yield-assets" not in cash_treasury.FUND_ROOTS["USDY"]


# ── post-implementation review: N6 (wrapper-root lookup must not miss mixed-case keys) ─────────
def test_fund_root_wrappers_share_their_funds_root_case_insensitively():
    """review N6: FUND_ROOTS stores canonical mixed-case keys (wUSDM, cUSDO, sBUIDL — matching how
    collateral_registry.py/rwa_safety_board.json actually spell them). A lookup that upper-cases
    the symbol first (the old bug: ``FUND_ROOTS.get(symbol.upper(), ...)``) misses them entirely
    and falls through to the per-symbol default, un-deduping the wrapper from its fund. Every
    wrapper must resolve to EXACTLY its fund's root, looked up through ``fund_root()`` the way the
    scanners do — via the exact key, via ``.upper()``, and via ``.lower()`` (any case a source
    file might hand us)."""
    pairs = [("wUSDM", "USDM"), ("sBUIDL", "BUIDL"), ("cUSDO", None)]
    for wrapper, fund in pairs:
        default = f"fund:{wrapper.lower()}"  # the WRONG answer the N6 bug used to produce
        root = cash_treasury.fund_root(wrapper, default)
        assert root != default, f"{wrapper} fell through to the per-symbol default — case lookup regressed"
        if fund is not None:
            assert root == cash_treasury.fund_root(fund, f"fund:{fund.lower()}")
        for mutated in (wrapper.upper(), wrapper.lower()):
            assert cash_treasury.fund_root(mutated, f"fund:{mutated.lower()}") == root, (
                f"fund_root({mutated!r}) did not match the canonical-case lookup")


def test_fund_root_matches_the_live_book_root_map():
    """review N6: the wrapper's root (keyed by symbol, cash_treasury.FUND_ROOTS) and the live
    book's root (keyed by protocol slug, cash_treasury.PROTOCOL_ROOT_MAP) must agree for the SAME
    real-world fund — wUSDM's symbol-keyed root must equal the "wusdm" adapter's protocol-keyed
    root, so a held wUSDM position is actually caught as a duplicate."""
    assert cash_treasury.fund_root("wUSDM", "?") == cash_treasury.PROTOCOL_ROOT_MAP["wusdm"]


def test_rwa_scan_produces_the_same_wrapper_roots_as_the_shared_table(tmp_path):
    """End-to-end regression: rwa.py's own output for cUSDO/wUSDM must carry the shared table's
    root, not a per-symbol fallback — red under the old ``symbol.upper()`` lookup."""
    _write(tmp_path / "rwa_safety_board.json", {
        "generated_at": iso(1),
        "assets": [
            {"symbol": "cUSDO", "issuer": "OpenEden", "redemption_documented": True,
             "redemption_delay_days": 1.0, "redemption_fee_bps": 0.0, "exit_capacity_72h_usd": 0.0,
             "transfer_restricted": False, "nav_source": "onchain_4626"},
            {"symbol": "wUSDM", "issuer": "Mountain Protocol", "redemption_documented": True,
             "redemption_delay_days": 1.0, "redemption_fee_bps": 0.0, "exit_capacity_72h_usd": 0.0,
             "transfer_restricted": False, "nav_source": "onchain_4626"},
            {"symbol": "USDM", "issuer": "Mountain Protocol", "redemption_documented": True,
             "redemption_delay_days": 1.0, "redemption_fee_bps": 0.0, "exit_capacity_72h_usd": 0.0,
             "transfer_restricted": False, "nav_source": "off_chain_estimate"},
        ],
    })
    res = rwa.scan(tmp_path, NOW)
    by_symbol = {c["instrument"]: c for c in res["candidates"]}
    assert by_symbol["cUSDO"]["underlying_root"] == cash_treasury.FUND_ROOTS["cUSDO"]
    assert by_symbol["cUSDO"]["underlying_root"] != "fund:cusdo"
    assert by_symbol["wUSDM"]["underlying_root"] == by_symbol["USDM"]["underlying_root"]
    assert by_symbol["wUSDM"]["underlying_root"] != "fund:wusdm"


# ── post-implementation review: H1 (never default as_of to the scan clock) ─────────────────────
def test_cash_treasury_rwa_floor_without_generated_at_is_not_measured_no_exception(tmp_path):
    """review H1: market_data/rwa_floor.json with no top-level 'generated_at' must produce
    NOT_MEASURED cells (never a scan-time stand-in, never an exception)."""
    _write(tmp_path / "adapter_status.json", {"adapters": {}})
    _write(tmp_path / "market_data" / "rwa_floor.json", {
        "pools": [{"label": "invesco-ustb:USTB", "apy_pct": 3.1, "tvl_usd": 1.0e9,
                  "pool": "1910847a-f8b5-40ce-a1ab-1dafdded5fbb"}],
    })
    res = cash_treasury.scan(tmp_path, NOW)  # must not raise
    assert len(res["candidates"]) == 1
    cand = res["candidates"][0]
    assert cand["base_return"]["state"] == contract.NOT_MEASURED
    assert cand["capacity"]["state"] == contract.NOT_MEASURED
    assert "generated_at" in cand["base_return"]["reason"]


def test_cash_treasury_savings_as_of_is_never_the_scan_clock(tmp_path):
    """review H1: the sUSDS/sDAI base_return cell's as_of must be adapter_status.json's own
    live_apy_as_of, never the scan-time NOW, even when they happen to be close."""
    tmp = _cash_treasury_fixture(tmp_path)
    res = cash_treasury.scan(tmp, NOW)
    susds = [c for c in res["candidates"] if c["instrument"] == "sUSDS"][0]
    assert susds["base_return"]["as_of"] == iso(1)
    assert susds["base_return"]["as_of"] != ISO_NOW


# ── post-implementation review: M3 (time_to_exit must not invent a DeFiLlama-sourced claim) ────
def test_cash_treasury_time_to_exit_from_adapter_constant_not_invented(tmp_path):
    """review M3: the 'instant exit' fact comes from the adapter module's own EXIT_LATENCY_HOURS
    class constant (a genuine repo-curated fact), never stamped as if DeFiLlama said it."""
    tmp = _cash_treasury_fixture(tmp_path)
    res = cash_treasury.scan(tmp, NOW)
    susds = [c for c in res["candidates"] if c["instrument"] == "sUSDS"][0]
    tte = susds["time_to_exit"]
    assert tte["state"] == contract.DOCUMENTED
    assert tte["value"] == 0.0
    assert tte["unit"] == "hours"
    assert tte["source_class"] == contract.SECONDARY_SOURCE
    assert tte["source_class"] != contract.REPUTABLE_AGGREGATOR
    assert "spark_susds_adapter.py" in tte["source_ref"]


# ══════════════════════════════════════════════════════════════════════════════════════════════
# rwa — fixtures
# ══════════════════════════════════════════════════════════════════════════════════════════════

def _rwa_fixture(tmp_path: Path) -> Path:
    _write(tmp_path / "rwa_safety_board.json", {
        "generated_at": iso(1),
        "assets": [
            {"symbol": "BUIDL", "issuer": "BlackRock / Securitize", "redemption_documented": True,
             "redemption_delay_days": 1.0, "redemption_fee_bps": 0.0, "exit_capacity_72h_usd": 0.0,
             "transfer_restricted": True, "nav_source": "off_chain_estimate"},
            {"symbol": "cUSDO", "issuer": "OpenEden", "redemption_documented": True,
             "redemption_delay_days": 1.0, "redemption_fee_bps": 0.0, "exit_capacity_72h_usd": 0.0,
             "transfer_restricted": False, "nav_source": "onchain_4626"},
            {"symbol": "sBUIDL", "issuer": "Securitize", "redemption_documented": True,
             "redemption_delay_days": 1.0, "redemption_fee_bps": 0.0, "exit_capacity_72h_usd": 0.0,
             "transfer_restricted": True, "nav_source": "off_chain_estimate"},
        ],
    })
    return tmp_path


def test_rwa_fixture_resolves_contracts_and_skips_no_contract_assets(tmp_path):
    _rwa_fixture(tmp_path)
    res = rwa.scan(tmp_path, NOW)
    assert_scan_result_shape(res)
    symbols = {c["instrument"] for c in res["candidates"]}
    assert symbols == {"BUIDL", "cUSDO"}
    assert [u["name"] for u in res["unresolved"]] == ["sBUIDL"]
    assert "no public mainnet token contract" in res["unresolved"][0]["reason"]


def test_rwa_sbuidl_and_buidl_share_the_same_underlying_root(tmp_path):
    """review #3: a wrapper resolves to its root fund — sBUIDL would share BUIDL's root if it had
    a contract to resolve from; here we assert the shared FUND_ROOTS table (owned by
    cash_treasury.py, imported here — review M1: one table, not two) encodes that, independent of
    whether sBUIDL happens to be resolvable today."""
    assert rwa.FUND_ROOTS is cash_treasury.FUND_ROOTS
    assert rwa.FUND_ROOTS["sBUIDL"] == rwa.FUND_ROOTS["BUIDL"]
    assert rwa.FUND_ROOTS["wUSDM"] == rwa.FUND_ROOTS["USDM"]


# ── post-implementation review: H6c (NAV read never upgrades reserve_transparency) ──────────────
def test_rwa_onchain_nav_never_upgrades_reserve_transparency(tmp_path):
    """review H6c: an on-chain share-price read is not a reserve-composition fact. Even with a
    successful on-chain quorum read for cUSDO (a genuine ERC-4626 wrapper), reserve_transparency
    must stay at its UNKNOWN/DOCUMENTED floor — the NAV read is recorded ONLY as its own
    ``observations[cid]['realised_index']`` fact, entirely separate from counterparty."""
    _rwa_fixture(tmp_path)
    client, _ = _fake_rpc_client(nav_raw=1_060_000_000_000_000_000)
    res = rwa.scan(tmp_path, NOW, rpc_client=client)
    cusdo = [c for c in res["candidates"] if c["instrument"] == "cUSDO"][0]
    cp = res["counterparty"][cusdo["candidate_id"]]
    assert cp["dimensions"]["reserve_transparency"]["state"] != contract.CP_OBSERVED
    # the successful on-chain read IS recorded, but only as the separate observation fact:
    obs = res["observations"][cusdo["candidate_id"]]
    assert obs["realised_index"] is not None
    assert obs["realised_index"]["state"] == contract.MEASURED
    buidl = [c for c in res["candidates"] if c["instrument"] == "BUIDL"][0]
    cp2 = res["counterparty"][buidl["candidate_id"]]
    assert cp2["dimensions"]["reserve_transparency"]["state"] != contract.CP_OBSERVED


def test_rwa_missing_board_is_unavailable(tmp_path):
    res = rwa.scan(tmp_path, NOW)
    assert res["status"] == "UNAVAILABLE"


# ── post-implementation review: M4 (as_of=None must never raise inside contract.cell()) ────────
def test_rwa_floor_rate_without_generated_at_is_not_measured_no_exception(tmp_path):
    """review M4: rwa.py used to build a MEASURED cell with as_of=None when rwa_floor.json had a
    matching per-pool rate but no top-level 'generated_at' — contract.cell() raises on that,
    which used to kill all 11 RWA candidates. Must now be NOT_MEASURED, no exception, and every
    OTHER asset must still be processed."""
    _rwa_fixture(tmp_path)
    _write(tmp_path / "market_data" / "rwa_floor.json", {
        # no 'generated_at' at all
        "pools": [{"label": "blackrock-buidl:BUIDL", "apy_pct": 3.7, "tvl_usd": 9.0e8,
                  "pool": "590d770e-ed5d-4c8d-ad96-5178c2072295"}],
    })
    res = rwa.scan(tmp_path, NOW)  # must not raise
    assert len(res["candidates"]) == 2  # BUIDL + cUSDO (sBUIDL stays unresolved, no contract)
    buidl = [c for c in res["candidates"] if c["instrument"] == "BUIDL"][0]
    assert buidl["base_return"]["state"] == contract.NOT_MEASURED
    assert "generated_at" in buidl["base_return"]["reason"]


def test_rwa_board_without_generated_at_is_not_measured_no_exception(tmp_path):
    """review H1/M4, the board's OWN 'generated_at': fees/time_to_exit/liquidity cite board_as_of
    — absent that timestamp they must be NOT_MEASURED, never scan-time, never an exception."""
    _write(tmp_path / "rwa_safety_board.json", {
        # no 'generated_at'
        "assets": [{"symbol": "BUIDL", "issuer": "BlackRock / Securitize", "redemption_documented": True,
                   "redemption_delay_days": 1.0, "redemption_fee_bps": 0.0, "exit_capacity_72h_usd": 0.0,
                   "transfer_restricted": True, "nav_source": "off_chain_estimate"}],
    })
    res = rwa.scan(tmp_path, NOW)  # must not raise
    buidl = res["candidates"][0]
    assert buidl["fees"]["state"] == contract.NOT_MEASURED
    assert buidl["time_to_exit"]["state"] == contract.NOT_MEASURED
    assert buidl["liquidity"]["state"] == contract.NOT_MEASURED


# ── post-implementation review: H6a/H6b (counterparty honesty) ─────────────────────────────────
def test_rwa_counterparty_roles_default_unknown_not_blanket_na(tmp_path):
    """review H6a: TOKENISED_TREASURY's required_roles are issuer/custodian/redemption_agent/
    legal_entity — custodian and legal_entity (undocumented here) must be UNKNOWN, NOT
    NOT_APPLICABLE; a role the mechanism genuinely does not call for (e.g. 'exchange') IS
    NOT_APPLICABLE."""
    _rwa_fixture(tmp_path)
    res = rwa.scan(tmp_path, NOW)
    buidl = [c for c in res["candidates"] if c["instrument"] == "BUIDL"][0]
    cp = res["counterparty"][buidl["candidate_id"]]
    assert cp["roles"]["custodian"]["state"] == contract.CP_UNKNOWN
    assert cp["roles"]["legal_entity"]["state"] == contract.CP_UNKNOWN
    assert cp["roles"]["exchange"]["state"] == contract.CP_NOT_APPLICABLE


def test_rwa_counterparty_never_cites_audited_document(tmp_path):
    """review H6b: this repo holds no audit letter for any of these funds — AUDITED_DOCUMENT must
    never appear as a source_class. Redemption fee/delay (the issuer's own published terms) are
    ISSUER_CLAIM; the board's own liquidity analysis is SECONDARY_SOURCE."""
    _rwa_fixture(tmp_path)
    res = rwa.scan(tmp_path, NOW)
    buidl = [c for c in res["candidates"] if c["instrument"] == "BUIDL"][0]
    cp = res["counterparty"][buidl["candidate_id"]]
    classes = {r["source_class"] for r in cp["roles"].values() if r["source_class"]} | \
             {d["source_class"] for d in cp["dimensions"].values() if d["source_class"]}
    assert contract.AUDITED_DOCUMENT not in classes
    assert cp["roles"]["redemption_agent"]["source_class"] == contract.ISSUER_CLAIM
    assert cp["dimensions"]["redemption_restrictions"]["source_class"] == contract.ISSUER_CLAIM
    assert cp["dimensions"]["legal_dependence"]["source_class"] == contract.SECONDARY_SOURCE
    # the candidate's own cells agree: fees/time_to_exit are ISSUER_CLAIM (issuer-published terms).
    assert buidl["fees"]["source_class"] == contract.ISSUER_CLAIM
    assert buidl["time_to_exit"]["source_class"] == contract.ISSUER_CLAIM
    assert buidl["liquidity"]["source_class"] == contract.SECONDARY_SOURCE


# ══════════════════════════════════════════════════════════════════════════════════════════════
# basis — fixtures, incl. funding inversion never clamped
# ══════════════════════════════════════════════════════════════════════════════════════════════

def _basis_fixture(tmp_path: Path, eth_rate_8h: float, btc_rate_8h: float) -> Path:
    _write(tmp_path / "market_data" / "funding.json", {"generated_at": iso(0.5),
                                                        "series": {"2026-10-03": 0.0001, "2026-10-04": eth_rate_8h}})
    _write(tmp_path / "market_data" / "btc_funding.json", {"generated_at": iso(0.5),
                                                           "series": {"2026-10-04": btc_rate_8h}})
    _write(tmp_path / "adapter_status.json", {"adapters": {
        "susde": {"live_apy": 5.0, "live_apy_as_of": iso(0.5), "live_apy_fresh": True, "apy_base": 5.0,
                  "apy_reward": 0.0, "tvl_usd": 1.0e9, "tvl_source": "live"},
    }})
    return tmp_path


def test_basis_funding_inversion_is_not_clamped(tmp_path):
    """A negative funding rate must survive annualisation as a negative number — never clamped to
    zero and never sign-flipped (`abs()`). This is the invariant the test name promises."""
    _basis_fixture(tmp_path, eth_rate_8h=-0.0005, btc_rate_8h=-0.0002)
    res = basis.scan(tmp_path, NOW)
    eth = [c for c in res["candidates"] if c["mechanism_id"] == "FUNDING_CAPTURE" and "ETH" in c["instrument"]][0]
    btc = [c for c in res["candidates"] if c["mechanism_id"] == "FUNDING_CAPTURE" and "BTC" in c["instrument"]][0]
    expected_eth = -0.0005 * basis.SETTLEMENTS_PER_DAY * basis.DAYS_PER_YEAR * 100.0
    expected_btc = -0.0002 * basis.SETTLEMENTS_PER_DAY * basis.DAYS_PER_YEAR * 100.0
    assert eth["funding"]["value"] == pytest.approx(expected_eth)
    assert btc["funding"]["value"] == pytest.approx(expected_btc)
    assert eth["funding"]["value"] < 0
    assert btc["funding"]["value"] < 0


def test_basis_funding_positive_also_not_clamped(tmp_path):
    _basis_fixture(tmp_path, eth_rate_8h=0.0009, btc_rate_8h=0.0003)
    res = basis.scan(tmp_path, NOW)
    eth = [c for c in res["candidates"] if "ETH" in c["instrument"]][0]
    assert eth["funding"]["value"] == pytest.approx(0.0009 * 3 * 365 * 100.0)


def test_basis_susde_funding_is_embedded_never_double_counted(tmp_path):
    _basis_fixture(tmp_path, eth_rate_8h=0.0001, btc_rate_8h=0.0001)
    res = basis.scan(tmp_path, NOW)
    susde = [c for c in res["candidates"] if c["mechanism_id"] == "DELTA_NEUTRAL_CARRY"][0]
    assert susde["funding"]["embedded_in_return"] is True
    assert susde["base_return"]["value"] == 5.0


def test_basis_susde_funding_is_not_measured_not_fabricated_zero(tmp_path):
    """review M3 (invariant #17): no code in this repo splits funding out of sUSDe's blended
    rate — that is an ABSENT observation, not an observed zero. The funding cell must be
    NOT_MEASURED (never a fabricated MEASURED 0.0), while still carrying
    embedded_in_return=True so net_expected_return() does not treat it as a missing cost."""
    _basis_fixture(tmp_path, eth_rate_8h=0.0001, btc_rate_8h=0.0001)
    res = basis.scan(tmp_path, NOW)
    susde = [c for c in res["candidates"] if c["mechanism_id"] == "DELTA_NEUTRAL_CARRY"][0]
    assert susde["funding"]["state"] == contract.NOT_MEASURED
    assert susde["funding"]["value"] is None
    assert susde["funding"]["embedded_in_return"] is True
    # and because fees/gas/etc are also unmeasured, net_expected_return must NOT fail on
    # "funding" specifically — it should name whichever OTHER cost actually blocked it.
    assert "funding" not in (susde["net_expected_return"].get("reason") or "")


def test_basis_susde_dn_frozen_series_is_estimated_not_measured(tmp_path):
    _basis_fixture(tmp_path, 0.0001, 0.0001)
    series_path = tmp_path / "aggressive_lab" / "susde_dn" / "realized_series.jsonl"
    series_path.parent.mkdir(parents=True, exist_ok=True)
    series_path.write_text(
        json.dumps({"as_of": "2026-10-03", "net_apy_pct": 3.1}) + "\n"
        + json.dumps({"as_of": "2026-10-04", "net_apy_pct": 3.14}) + "\n",
        encoding="utf-8")
    res = basis.scan(tmp_path, NOW)
    susde = [c for c in res["candidates"] if c["mechanism_id"] == "DELTA_NEUTRAL_CARRY"][0]
    rr = susde["realised_return"]
    assert rr["state"] == contract.ESTIMATED_WITH_METHOD
    assert rr["source_class"] == contract.MODELLED
    assert "FROZEN REPLAY" in rr["method"]
    assert rr["value"] == 3.14  # the LATEST row — never the first, never averaged


def test_basis_variant_n_is_never_emitted_as_a_candidate(tmp_path):
    """post-implementation review, LOW item: variant_n is an engine-owned strategy_lab paper
    strategy, not a capital-opportunity candidate — even when its series file is present and
    well-formed, basis.py must never turn it into a candidate."""
    _basis_fixture(tmp_path, 0.0001, 0.0001)
    _write(tmp_path / "strategy_lab_paper" / "variant_n_series.json", {
        "series": [{"date": "2026-10-04", "ts": iso(1), "equity_usd": 100700.0, "net_apy_pct": 1.8}],
    })
    res = basis.scan(tmp_path, NOW)
    assert not any("variant_n" in str(c.get("instrument", "")) for c in res["candidates"])
    assert len(res["candidates"]) == 3  # ETH + BTC funding capture + sUSDe only


# ── post-implementation review: H1 (funding as_of = the true upstream settlement day) ──────────
def test_basis_funding_as_of_is_the_series_date_not_generated_at(tmp_path):
    """review H1: funding.json's own 'generated_at' is OUR fetch time, which can advance daily
    while the underlying settlement series stays frozen. as_of must be the LATEST SERIES DATE,
    never the file's generated_at, even when the two disagree by a lot."""
    _write(tmp_path / "market_data" / "funding.json", {
        "generated_at": iso(0.1),            # recent fetch...
        "series": {"2026-01-01": 0.0001},    # ...of a settlement series frozen months ago
    })
    _write(tmp_path / "market_data" / "btc_funding.json", {"generated_at": iso(0.1), "series": {}})
    _write(tmp_path / "adapter_status.json", {"adapters": {}})
    res = basis.scan(tmp_path, NOW)
    eth = [c for c in res["candidates"] if "ETH" in c["instrument"]][0]
    assert eth["funding"]["as_of"].startswith("2026-01-01")
    assert eth["funding"]["as_of"] != iso(0.1)
    # review N5: a frozen day is capped at ITS OWN end-of-day, not midnight and not generated_at.
    assert eth["funding"]["as_of"] == "2026-01-01T23:59:59+00:00"


# ── post-implementation review: N5 (fresh same-day fetch is NOT undercounted to midnight) ──────
def test_basis_funding_as_of_same_day_fetch_uses_generated_at_not_midnight(tmp_path):
    """review N5: the feed writes ~09:10 UTC the SAME day the series' latest date reports. Capping
    as_of at a plain 'T00:00:00' anchor would make the observation "fresh" (12h funding window)
    only from 00:00-12:00 UTC even though the fetch itself is same-day and current — as_of must
    credit the fetch time (generated_at) here, not undercount to midnight."""
    today = NOW.date().isoformat()  # NOW = 2026-10-04T12:00:00Z
    gen_at = "2026-10-04T09:10:00+00:00"   # same day as the latest series date, before NOW
    _write(tmp_path / "market_data" / "funding.json", {
        "generated_at": gen_at, "series": {today: 0.0001},
    })
    _write(tmp_path / "market_data" / "btc_funding.json", {"generated_at": gen_at, "series": {}})
    _write(tmp_path / "adapter_status.json", {"adapters": {}})
    res = basis.scan(tmp_path, NOW)
    eth = [c for c in res["candidates"] if "ETH" in c["instrument"]][0]
    assert eth["funding"]["as_of"] == gen_at
    assert eth["funding"]["as_of"] != f"{today}T00:00:00+00:00"


def test_basis_funding_as_of_never_later_than_generated_at(tmp_path):
    """review N5, explicit boundary: as_of must never be LATER than generated_at — a frozen
    series day whose generated_at has moved on to a LATER day must cap at the frozen day's own
    end, never borrow the later fetch time."""
    _write(tmp_path / "market_data" / "funding.json", {
        "generated_at": iso(0.1),             # today, recent
        "series": {"2026-10-03": 0.0002},     # yesterday — frozen one day behind the fetch
    })
    _write(tmp_path / "market_data" / "btc_funding.json", {"generated_at": iso(0.1), "series": {}})
    _write(tmp_path / "adapter_status.json", {"adapters": {}})
    res = basis.scan(tmp_path, NOW)
    eth = [c for c in res["candidates"] if "ETH" in c["instrument"]][0]
    assert eth["funding"]["as_of"] == "2026-10-03T23:59:59+00:00"
    assert eth["funding"]["as_of"] != iso(0.1)


def test_basis_funding_as_of_never_in_the_future(tmp_path):
    """review N5, explicit boundary: a bogus future generated_at (clock skew) must never make
    as_of land in the future — contract.cell() would raise on that for a MEASURED cell, and this
    must never crash the scanner (H0's discipline, applied here)."""
    today = NOW.date().isoformat()
    future = (NOW + timedelta(hours=5)).isoformat()
    _write(tmp_path / "market_data" / "funding.json", {
        "generated_at": future, "series": {today: 0.0001},
    })
    _write(tmp_path / "market_data" / "btc_funding.json", {"generated_at": future, "series": {}})
    _write(tmp_path / "adapter_status.json", {"adapters": {}})
    res = basis.scan(tmp_path, NOW)  # must not raise
    eth = [c for c in res["candidates"] if "ETH" in c["instrument"]][0]
    assert eth["funding"]["state"] == contract.MEASURED
    assert contract.parse_ts(eth["funding"]["as_of"]) <= NOW
    assert eth["funding"]["as_of"] != future


# ── post-implementation review: H6d (never name our venues as Ethena's) ────────────────────────
def test_basis_susde_counterparty_exchange_role_is_unknown_not_our_venues(tmp_path):
    _basis_fixture(tmp_path, 0.0001, 0.0001)
    res = basis.scan(tmp_path, NOW)
    susde = [c for c in res["candidates"] if c["mechanism_id"] == "DELTA_NEUTRAL_CARRY"][0]
    cp = res["counterparty"][susde["candidate_id"]]
    assert cp["roles"]["exchange"]["state"] == contract.CP_UNKNOWN
    assert cp["roles"]["exchange"]["name"] is None


# ══════════════════════════════════════════════════════════════════════════════════════════════
# discovery — fixtures, incl. the sky-lending collision and six-Midas-stay-six
# ══════════════════════════════════════════════════════════════════════════════════════════════

def _discovery_fixture(tmp_path: Path, rows: list, max_candidates: int = 25) -> Path:
    _write(tmp_path / "candidate_registry.json", {
        "generated_at": iso(1), "scanned_pools": 16989,
        "gates": {"max_candidates": max_candidates}, "candidates": rows,
    })
    return tmp_path


def test_discovery_sky_lending_collides_with_the_live_books_root(tmp_path):
    rows = [
        {"pool_id": "d8c4eff5-c8a9-46fc-a888-057c4c668e72", "protocol": "sky-lending", "chain": "Ethereum",
         "symbol": "SUSDS", "apy_pct": 3.6, "tvl_usd": 4.6e9, "age_days": None},
        {"pool_id": "c8a24fee-ec00-4f38-86c0-9f6daebc4225", "protocol": "sky-lending", "chain": "Ethereum",
         "symbol": "SDAI", "apy_pct": 1.25, "tvl_usd": 2.0e8, "age_days": None},
    ]
    _discovery_fixture(tmp_path, rows)
    _write(tmp_path / "current_positions.json", {"feed_coverage": {"live_adapters": ["spark_susds", "sdai"]},
                                                 "positions": {}})
    res = discovery.scan(tmp_path, NOW)
    assert_scan_result_shape(res)
    roots = {c["underlying_root"] for c in res["candidates"]}
    assert roots == {cash_treasury.ROOT_SKY_SAVINGS}
    assert cash_treasury.ROOT_SKY_SAVINGS in res["existing_book_roots"]
    susds = [c for c in res["candidates"] if c["instrument"] == "SUSDS"][0]
    assert susds["mechanism_id"] == "STABLECOIN_SAVINGS"
    assert susds["economic_driver_key"] == "SKY_SSR"


def test_discovery_without_the_override_a_pool_keeps_its_own_root(tmp_path):
    """Negative control for the collision above: an UNRELATED pool (not in _KNOWN_OVERRIDES) must
    NOT be swept into fund:sky-savings — the override is specific, not a catch-all."""
    rows = [
        {"pool_id": "11111111-1111-1111-1111-111111111111", "protocol": "some-other-lending",
         "chain": "Ethereum", "symbol": "USDC", "apy_pct": 4.0, "tvl_usd": 1.0e7, "age_days": None},
    ]
    _discovery_fixture(tmp_path, rows)
    res = discovery.scan(tmp_path, NOW)
    cand = res["candidates"][0]
    assert cand["underlying_root"] == "llama:11111111-1111-1111-1111-111111111111"
    assert cand["underlying_root"] != cash_treasury.ROOT_SKY_SAVINGS


def test_discovery_six_midas_pools_stay_six_candidates(tmp_path):
    rows = [
        {"pool_id": f"aaaaaaaa-0000-0000-0000-00000000000{i}", "protocol": "midas-rwa", "chain": "Ethereum",
         "symbol": "USDC", "apy_pct": 5.0 + i, "tvl_usd": 1.0e7, "age_days": None}
        for i in range(6)
    ]
    _discovery_fixture(tmp_path, rows)
    res = discovery.scan(tmp_path, NOW)
    assert len(res["candidates"]) == 6
    assert len({c["candidate_id"] for c in res["candidates"]}) == 6
    assert all(c["instrument"] == "USDC" for c in res["candidates"])
    assert all(c["mechanism_id"] == "RWA_CREDIT" for c in res["candidates"])
    roots = {c["underlying_root"] for c in res["candidates"]}
    assert len(roots) == 6, "six distinct Midas pools must never be merged onto one root by symbol"


def test_discovery_unclear_project_goes_to_unresolved_not_a_guess(tmp_path):
    rows = [
        {"pool_id": "22222222-2222-2222-2222-222222222222", "protocol": "mystery-protocol", "chain": "Ethereum",
         "symbol": "USDC", "apy_pct": 9.0, "tvl_usd": 1.0e7, "age_days": None},
    ]
    _discovery_fixture(tmp_path, rows)
    res = discovery.scan(tmp_path, NOW)
    assert res["candidates"] == []
    assert len(res["unresolved"]) == 1
    assert "mechanism keyword" in res["unresolved"][0]["reason"]


def test_discovery_multi_leg_symbol_is_stable_lp(tmp_path):
    rows = [
        {"pool_id": "33333333-3333-3333-3333-333333333333", "protocol": "uniswap-v4", "chain": "Ethereum",
         "symbol": "USDC-USDT", "apy_pct": 0.5, "tvl_usd": 1.0e7, "age_days": None},
    ]
    _discovery_fixture(tmp_path, rows)
    res = discovery.scan(tmp_path, NOW)
    assert res["candidates"][0]["mechanism_id"] == "STABLE_LP"


def test_discovery_age_gate_defect_is_named_on_every_candidate(tmp_path):
    rows = [
        {"pool_id": "44444444-4444-4444-4444-444444444444", "protocol": "justlend-v1", "chain": "Tron",
         "symbol": "USDT", "apy_pct": 2.0, "tvl_usd": 1.0e7, "age_days": None},
    ]
    _discovery_fixture(tmp_path, rows)
    res = discovery.scan(tmp_path, NOW)
    cand = res["candidates"][0]
    assert cand["duration"]["state"] == contract.NOT_MEASURED
    assert "age gate is never measured" in cand["duration"]["reason"]


def test_discovery_finance_keyword_goes_to_unresolved_not_vault_aggregator(tmp_path):
    """post-implementation review, LOW item: 'finance' is too loose a keyword (many unrelated
    protocols have it in their name) — a project like 'harmonix-finance' must go to unresolved,
    never be guessed as VAULT_AGGREGATOR."""
    rows = [
        {"pool_id": "66666666-6666-6666-6666-666666666666", "protocol": "harmonix-finance",
         "chain": "Ethereum", "symbol": "USDC", "apy_pct": 5.9, "tvl_usd": 1.0e7, "age_days": None},
    ]
    _discovery_fixture(tmp_path, rows)
    res = discovery.scan(tmp_path, NOW)
    assert res["candidates"] == []
    assert len(res["unresolved"]) == 1
    assert "mechanism keyword" in res["unresolved"][0]["reason"]


# ── post-implementation review: H1 (never default to the scan clock) ───────────────────────────
def test_discovery_without_generated_at_is_not_measured_no_exception(tmp_path):
    rows = [
        {"pool_id": "77777777-7777-7777-7777-777777777777", "protocol": "justlend-v1", "chain": "Tron",
         "symbol": "USDT", "apy_pct": 2.0, "tvl_usd": 1.0e7, "age_days": None},
    ]
    _write(tmp_path / "candidate_registry.json", {
        # no 'generated_at'
        "scanned_pools": 100, "gates": {"max_candidates": 25}, "candidates": rows,
    })
    res = discovery.scan(tmp_path, NOW)  # must not raise
    assert len(res["candidates"]) == 1
    cand = res["candidates"][0]
    assert cand["base_return"]["state"] == contract.NOT_MEASURED
    assert cand["capacity"]["state"] == contract.NOT_MEASURED
    assert "generated_at" in cand["base_return"]["reason"]
    assert cand["base_return"]["as_of"] is None


def test_discovery_truncation_is_named(tmp_path):
    rows = [
        {"pool_id": f"55555555-5555-5555-5555-55555555555{i}", "protocol": "justlend-v1", "chain": "Tron",
         "symbol": "USDT", "apy_pct": 2.0, "tvl_usd": 1.0e7, "age_days": None}
        for i in range(3)
    ]
    _discovery_fixture(tmp_path, rows, max_candidates=3)
    res = discovery.scan(tmp_path, NOW)
    assert res["denominators"]["truncated"] == 3


# ══════════════════════════════════════════════════════════════════════════════════════════════
# trading_research — fixtures
# ══════════════════════════════════════════════════════════════════════════════════════════════

def _tr_fixture(tmp_path: Path, shortlist: list) -> Path:
    _write(tmp_path / "trading_research" / "status.json", {
        "generated_at_ms": int(NOW.timestamp() * 1000), "candidates": 138,
        "stages": {"REJECTED": 138 - len(shortlist), "FORWARD_PAPER": len(shortlist)},
        "shortlist": shortlist,
    })
    return tmp_path


def test_trading_research_verdict_from_forward_net_sign(tmp_path):
    _tr_fixture(tmp_path, [
        {"id": "supertrend@v1:BTC:1D:spot_long:cb4ee7a5a5", "forward_net": -0.003, "forward_bars": 4},
        {"id": "donchian@v1:BTC:4h:spot_long:8f4bfc1d5a", "forward_net": 0.0, "forward_bars": 21},
    ])
    res = trading_research.scan(tmp_path, NOW)
    assert_scan_result_shape(res)
    assert len(res["candidates"]) == 2
    neg = [c for c in res["candidates"] if c["realised_return"]["value"] == -0.003][0]
    assert "FORWARD_PAPER_NEGATIVE" in neg["realised_return"]["method"]
    flat = [c for c in res["candidates"] if c["realised_return"]["value"] == 0.0][0]
    assert "FORWARD_PAPER_FLAT" in flat["realised_return"]["method"]
    assert neg["domain"] == "TRADING_RESEARCH"
    assert neg["admission_state"] is None


def test_trading_research_instrument_id_sanitised_from_raw_engine_id(tmp_path):
    """The raw shortlist id contains '@' and ':', which INSTRUMENT_ID_RE's engine-id segment does
    not allow — the scanner must still produce a valid instrument_id (never raise, never truncate
    to a bare ticker)."""
    raw_id = "supertrend@v1:BTC:1D:spot_long:cb4ee7a5a5"
    _tr_fixture(tmp_path, [{"id": raw_id, "forward_net": 0.01, "forward_bars": 10}])
    res = trading_research.scan(tmp_path, NOW)
    cand = res["candidates"][0]
    assert contract.instrument_id_ok(cand["instrument_id"])
    assert "@" not in cand["instrument_id"] and ":" not in cand["instrument_id"].split(":", 2)[2]


def test_trading_research_missing_status_is_unavailable(tmp_path):
    res = trading_research.scan(tmp_path, NOW)
    assert res["status"] == "UNAVAILABLE"


# ── post-implementation review: H1 (never default to the scan clock) ───────────────────────────
def test_trading_research_without_generated_at_ms_is_not_measured_no_exception(tmp_path):
    _write(tmp_path / "trading_research" / "status.json", {
        # no 'generated_at_ms'
        "candidates": 138, "stages": {"REJECTED": 137, "FORWARD_PAPER": 1},
        "shortlist": [{"id": "donchian@v1:BTC:4h:spot_long:8f4bfc1d5a", "forward_net": 0.01, "forward_bars": 5}],
    })
    res = trading_research.scan(tmp_path, NOW)  # must not raise
    assert len(res["candidates"]) == 1
    cand = res["candidates"][0]
    assert cand["realised_return"]["state"] == contract.NOT_MEASURED
    assert "generated_at_ms" in cand["realised_return"]["reason"]


# ══════════════════════════════════════════════════════════════════════════════════════════════
# onchain.py — the only network surface; allow-list + behaviour
# ══════════════════════════════════════════════════════════════════════════════════════════════

ALLOWED_METHODS = {"eth_call", "eth_blockNumber", "eth_getBlockByNumber"}


def _fake_rpc_client(*, decimals=18, nav_raw=None, block_number=1000, block_hash="0xblockhash",
                     block_ts=1_700_000_000, n_endpoints=3, decimals_endpoint_fail=()):
    """A fake RpcClient (real class, fake transport) with ``n_endpoints`` independent operators
    all agreeing — the happy path every behaviour test starts from."""
    from spa_core.capital_shadow.rpc import RpcClient
    seen_methods = set()
    nav_raw = nav_raw if nav_raw is not None else 1_060_000_000_000_000_000  # ≈1.06 per 1e18 share

    def post(url, payload):
        seen_methods.add(payload["method"])
        method, params = payload["method"], payload["params"]
        if method == "eth_blockNumber":
            return {"jsonrpc": "2.0", "id": 1, "result": hex(block_number + 2)}
        if method == "eth_getBlockByNumber":
            return {"jsonrpc": "2.0", "id": 1,
                    "result": {"hash": block_hash, "timestamp": hex(block_ts), "number": params[0]}}
        if method == "eth_call":
            data = params[0]["data"]
            if data == onchain.SEL_DECIMALS:
                if url in decimals_endpoint_fail:
                    return {"jsonrpc": "2.0", "id": 1, "error": {"message": "execution reverted"}}
                return {"jsonrpc": "2.0", "id": 1, "result": hex(decimals)}
            return {"jsonrpc": "2.0", "id": 1, "result": hex(nav_raw)}
        raise AssertionError(f"disallowed method reached transport: {method}")

    endpoints = [(f"http://op{i}.example", f"Op{i}") for i in range(n_endpoints)]
    client = RpcClient(chain_id=1, endpoints=endpoints, post=post)
    return client, seen_methods


def test_onchain_realised_index_without_client_is_not_measured_rpc_not_enabled():
    cell = onchain.realised_index("sUSDS", onchain.SUSDS_ADDRESS, rpc_client=None, now=NOW)
    assert cell["state"] == contract.NOT_MEASURED
    assert cell["reason"] == "rpc not enabled"


def test_onchain_realised_index_without_contract_address():
    client, _ = _fake_rpc_client()
    cell = onchain.realised_index("mystery", None, rpc_client=client, now=NOW)
    assert cell["state"] == contract.NOT_MEASURED
    assert "no on-chain contract address" in cell["reason"]


def test_onchain_realised_index_happy_path_uses_only_allowed_methods():
    client, seen = _fake_rpc_client(decimals=18, nav_raw=1_060_000_000_000_000_000)
    cell = onchain.realised_index("sUSDS", onchain.SUSDS_ADDRESS, rpc_client=client, now=NOW)
    assert cell["state"] == contract.MEASURED
    assert cell["value"] == pytest.approx(1.06)
    assert cell["source_class"] == contract.PRIMARY_CHAIN
    assert cell["source_root"] == "chain:1"
    assert contract.parse_ts(cell["as_of"]) is not None
    assert seen <= ALLOWED_METHODS
    assert seen == ALLOWED_METHODS            # every allowed method is actually exercised


def test_onchain_disallowed_method_never_reaches_the_transport():
    """Positive control for the allow-list claim above: a client asked to perform a forbidden
    method raises BEFORE any transport call, so ``seen`` never contains it."""
    from spa_core.capital_shadow.rpc import ForbiddenMethod
    client, seen = _fake_rpc_client()
    with pytest.raises(ForbiddenMethod):
        client.request("http://op0.example", "eth_sendRawTransaction", ["0xdead"])
    assert "eth_sendRawTransaction" not in seen


def test_onchain_sanity_band_mutation_pair():
    """Guard: a clean read outside [0.5, 2.0] is an ABI/decode mismatch, not a signal.
    Positive: 1.06 (in-band) → MEASURED. Negative (the mutant): 48.0 (out-of-band, as a wrong-ABI
    read would produce) → NOT_MEASURED, never surfaced as a NAV."""
    in_band, _ = _fake_rpc_client(nav_raw=1_060_000_000_000_000_000)
    cell_ok = onchain.realised_index("sDAI", onchain.SDAI_ADDRESS, rpc_client=in_band, now=NOW)
    assert cell_ok["state"] == contract.MEASURED

    out_of_band, _ = _fake_rpc_client(nav_raw=48_000_000_000_000_000_000)
    cell_bad = onchain.realised_index("sDAI", onchain.SDAI_ADDRESS, rpc_client=out_of_band, now=NOW)
    assert cell_bad["state"] == contract.NOT_MEASURED
    assert "sane band" in cell_bad["reason"]


def test_onchain_quorum_shortfall_mutation_pair():
    """Guard: 2-of-N independent agreement is required on decimals(). Positive: 3 agreeing
    endpoints → MEASURED. Negative (the mutant): decimals() fails on enough endpoints that fewer
    than 2 agree → NOT_MEASURED, never a single-witness guess."""
    good, _ = _fake_rpc_client(n_endpoints=3, decimals_endpoint_fail=())
    cell_ok = onchain.realised_index("sUSDS", onchain.SUSDS_ADDRESS, rpc_client=good, now=NOW)
    assert cell_ok["state"] == contract.MEASURED

    starved, _ = _fake_rpc_client(n_endpoints=3,
                                  decimals_endpoint_fail=("http://op0.example", "http://op1.example"))
    cell_bad = onchain.realised_index("sUSDS", onchain.SUSDS_ADDRESS, rpc_client=starved, now=NOW)
    assert cell_bad["state"] == contract.NOT_MEASURED
    assert "decimals" in cell_bad["reason"]


def test_onchain_block_pin_failure_propagates_as_not_measured():
    from spa_core.capital_shadow.rpc import RpcClient

    def dead_post(url, payload):
        raise ConnectionError("endpoint down")

    client = RpcClient(chain_id=1, endpoints=[("http://op0.example", "Op0"), ("http://op1.example", "Op1")],
                       post=dead_post)
    cell = onchain.realised_index("sUSDS", onchain.SUSDS_ADDRESS, rpc_client=client, now=NOW)
    assert cell["state"] == contract.NOT_MEASURED
    assert "block pin failed" in cell["reason"]


# ── post-implementation review: H0 (a real RpcClient; ANY read failure → NOT_MEASURED, never a
# scanner exception) ─────────────────────────────────────────────────────────────────────────
def test_onchain_realised_index_with_a_client_that_always_raises(monkeypatch):
    """H0, literal wording: 'test with a fake client that raises'. The transport raises on EVERY
    call (not just block-pin) — realised_index must still return a clean NOT_MEASURED cell, never
    propagate the exception."""
    client, _ = _fake_rpc_client()

    def always_raises(*args, **kwargs):
        raise RuntimeError("transport exploded")

    monkeypatch.setattr(client, "_post_fn", always_raises)
    cell = onchain.realised_index("sUSDS", onchain.SUSDS_ADDRESS, rpc_client=client, now=NOW)
    assert cell["state"] == contract.NOT_MEASURED
    assert cell["value"] is None


def test_onchain_realised_index_survives_pin_block_itself_raising(monkeypatch):
    """H0's top-level guard specifically: even if ``RpcClient.pin_block`` itself raised (not just
    its transport) — a scenario the normal per-operator catch does not cover — realised_index must
    still come back NOT_MEASURED, never an uncaught exception reaching the scanner."""
    client, _ = _fake_rpc_client()

    def boom():
        raise RuntimeError("pin_block itself exploded")

    monkeypatch.setattr(client, "pin_block", boom)
    cell = onchain.realised_index("sUSDS", onchain.SUSDS_ADDRESS, rpc_client=client, now=NOW)  # must not raise
    assert cell["state"] == contract.NOT_MEASURED
    assert "RuntimeError" in cell["reason"]


# ══════════════════════════════════════════════════════════════════════════════════════════════
# counterparty_registry.py — direct unit tests (H6)
# ══════════════════════════════════════════════════════════════════════════════════════════════

def test_counterparty_empty_floor_unknown_vs_not_applicable_by_required_roles():
    """review H6a: a role is NOT_APPLICABLE only when the mechanism's own required_roles says so
    — every other role defaults to UNKNOWN, never a blanket NOT_APPLICABLE floor."""
    out = counterparty_registry._empty("TOKENISED_TREASURY")
    required = contract.MECHANISMS["TOKENISED_TREASURY"]["required_roles"]
    for role in contract.COUNTERPARTY_ROLES:
        expected = contract.CP_UNKNOWN if role in required else contract.CP_NOT_APPLICABLE
        assert out["roles"][role]["state"] == expected, role
    for dim in contract.COUNTERPARTY_DIMENSIONS:
        assert out["dimensions"][dim]["state"] == contract.CP_UNKNOWN


def test_counterparty_source_code_never_cites_audited_document():
    """review H6b, static guard: this repo holds no audit letter for any instrument the factory
    covers — contract.AUDITED_DOCUMENT must never be referenced as an actual value anywhere in
    counterparty_registry.py (the word may appear in prose/comments explaining why it is banned)."""
    src = Path(counterparty_registry.__file__).read_text(encoding="utf-8")
    assert "contract.AUDITED_DOCUMENT" not in src


def test_counterparty_stablecoin_savings_gsm_issuer_claim_vs_observed(tmp_path):
    out_no_gsm = counterparty_registry.stablecoin_savings("sUSDS")
    assert out_no_gsm["dimensions"]["redemption_restrictions"]["source_class"] == contract.ISSUER_CLAIM
    out_gsm = counterparty_registry.stablecoin_savings("sUSDS", gsm_hours=48.0, gsm_as_of=ISO_NOW)
    assert out_gsm["dimensions"]["redemption_restrictions"]["state"] == contract.CP_OBSERVED
    assert out_gsm["dimensions"]["redemption_restrictions"]["source_class"] == contract.PRIMARY_CHAIN


# ══════════════════════════════════════════════════════════════════════════════════════════════
# static / source-level guards
# ══════════════════════════════════════════════════════════════════════════════════════════════

_SCANNER_SOURCE_FILES = [
    Path(cash_treasury.__file__), Path(rwa.__file__), Path(basis.__file__),
    Path(discovery.__file__), Path(trading_research.__file__),
]


def test_no_scanner_source_reads_the_aggregate_treasury_floor_fields():
    """Static guard, independent of any fixture: the literal field names that hold the AGGREGATE
    TVL-weighted floor must never appear in a scanner's source at all — the only legitimate way to
    get a per-instrument rate is the ``pools[*].apy_pct`` row, which this asserts by omission."""
    forbidden = ("floor_apy_pct", "tvl_weighted_apy_pct")
    for path in _SCANNER_SOURCE_FILES:
        src = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in src, f"{path.name} references the aggregate field {token!r}"


def test_no_scanner_imports_execution_or_studio_os_or_capital_shadow_writer():
    banned_substrings = ("spa_core.execution", "spa_core.studio_os", "spa_core.investment_cio")
    for path in _SCANNER_SOURCE_FILES + [Path(onchain.__file__), Path(counterparty_registry.__file__)]:
        src = path.read_text(encoding="utf-8")
        for token in banned_substrings:
            assert token not in src, f"{path.name} references forbidden module {token!r}"
    onchain_src = Path(onchain.__file__).read_text(encoding="utf-8")
    assert "spa_core.capital_shadow.rpc" in onchain_src
    assert "spa_core.capital_shadow.keccak" in onchain_src
    assert "spa_core.capital_shadow.contract" not in onchain_src


def test_llm_forbidden_marker_present_on_every_package_b_module():
    for path in _SCANNER_SOURCE_FILES + [Path(onchain.__file__), Path(counterparty_registry.__file__)]:
        src = path.read_text(encoding="utf-8")
        assert re.search(r"^# LLM_FORBIDDEN\s*$", src, re.MULTILINE), f"{path} missing a '# LLM_FORBIDDEN' marker line"


# ══════════════════════════════════════════════════════════════════════════════════════════════
# production-data run — read-only use of a copy of the prod data/ tree
# ══════════════════════════════════════════════════════════════════════════════════════════════

pytestmark_prod = pytest.mark.skipif(not PROD_DATA.is_dir(), reason="prod data copy not available in this environment")


@pytest.mark.skipif(not PROD_DATA.is_dir(), reason="prod data copy not available in this environment")
@pytest.mark.parametrize("mod", SCANNERS, ids=lambda m: m.__name__.rsplit(".", 1)[-1])
def test_every_scanner_against_production_data_conforms_to_appendix_i(mod):
    res = mod.scan(PROD_DATA, NOW)
    assert_scan_result_shape(res)
    assert res["status"] != "UNAVAILABLE", res.get("reason")
    assert len(res["candidates"]) > 0


@pytest.mark.skipif(not PROD_DATA.is_dir(), reason="prod data copy not available in this environment")
def test_production_data_no_candidate_id_collides_across_scanners():
    seen: dict = {}
    for mod in SCANNERS:
        res = mod.scan(PROD_DATA, NOW)
        for c in res["candidates"]:
            prev = seen.get(c["candidate_id"])
            assert prev is None or prev == (mod.__name__, c["exposure_key"]), (
                f"candidate_id collision between scanners for different exposures: "
                f"{prev} vs {(mod.__name__, c['exposure_key'])}")
            seen[c["candidate_id"]] = (mod.__name__, c["exposure_key"])


@pytest.mark.skipif(not PROD_DATA.is_dir(), reason="prod data copy not available in this environment")
def test_production_data_sky_lending_discovery_collides_with_live_book():
    res = discovery.scan(PROD_DATA, NOW)
    sky_candidates = [c for c in res["candidates"] if c["venue_or_protocol"] == "sky-lending"
                      and c["instrument"] in ("SUSDS", "SDAI")]
    assert sky_candidates, "expected the sky-lending SUSDS/SDAI rows on the prod snapshot"
    for c in sky_candidates:
        assert c["underlying_root"] == cash_treasury.ROOT_SKY_SAVINGS
    assert cash_treasury.ROOT_SKY_SAVINGS in res["existing_book_roots"]


@pytest.mark.skipif(not PROD_DATA.is_dir(), reason="prod data copy not available in this environment")
def test_production_data_rwa_four_no_contract_assets_are_unresolved():
    res = rwa.scan(PROD_DATA, NOW)
    names = {u["name"] for u in res["unresolved"]}
    assert names == {"BENJI", "STAC", "VBILL", "sBUIDL"}


@pytest.mark.skipif(not PROD_DATA.is_dir(), reason="prod data copy not available in this environment")
def test_production_data_basis_funding_is_a_real_signed_annualised_rate():
    res = basis.scan(PROD_DATA, NOW)
    eth = [c for c in res["candidates"] if c["mechanism_id"] == "FUNDING_CAPTURE" and "ETH" in c["instrument"]][0]
    assert eth["funding"]["state"] == contract.MEASURED
    assert isinstance(eth["funding"]["value"], float)


@pytest.mark.skipif(not PROD_DATA.is_dir(), reason="prod data copy not available in this environment")
def test_production_data_counterparty_unknown_census():
    """Not an assertion on a specific number (that would be a stale-literal trap) — just proves
    the census is computable and finds at least one UNKNOWN role somewhere, which is the honest
    expectation for freshly discovered pools."""
    any_unknown = False
    for mod in SCANNERS:
        res = mod.scan(PROD_DATA, NOW)
        for cp in res["counterparty"].values():
            if any(r["state"] == contract.CP_UNKNOWN for r in cp["roles"].values()):
                any_unknown = True
    assert any_unknown


@pytest.mark.skipif(not PROD_DATA.is_dir(), reason="prod data copy not available in this environment")
def test_production_data_no_cell_as_of_equals_the_scan_clock():
    """review H1, production-level regression guard: no scanner may stamp a cell's as_of with the
    scan time itself — that would be exactly the forbidden scan-time fallback surviving."""
    for mod in SCANNERS:
        res = mod.scan(PROD_DATA, NOW)
        for c in res["candidates"]:
            for f in contract.CELL_FIELDS + contract.RISK_FIELDS:
                cell = c[f]
                if cell.get("as_of"):
                    assert cell["as_of"] != ISO_NOW, f"{mod.__name__}:{f} as_of == scan clock"


@pytest.mark.skipif(not PROD_DATA.is_dir(), reason="prod data copy not available in this environment")
def test_production_data_cash_treasury_and_rwa_do_not_overlap():
    """review M1, production-level regression guard."""
    ct_syms = {c["instrument"].upper() for c in cash_treasury.scan(PROD_DATA, NOW)["candidates"]
              if c["mechanism_id"] == "TOKENISED_TREASURY"}
    rwa_syms = {c["instrument"].upper() for c in rwa.scan(PROD_DATA, NOW)["candidates"]}
    assert not (ct_syms & rwa_syms), f"overlap: {ct_syms & rwa_syms}"
    assert ct_syms and rwa_syms  # both non-empty on the prod snapshot — a real check, not vacuous


@pytest.mark.skipif(not PROD_DATA.is_dir(), reason="prod data copy not available in this environment")
def test_production_data_no_audited_document_anywhere():
    """review H6b, production-level regression guard."""
    for mod in SCANNERS:
        res = mod.scan(PROD_DATA, NOW)
        for c in res["candidates"]:
            for f in contract.CELL_FIELDS:
                assert c[f]["source_class"] != contract.AUDITED_DOCUMENT
        for cp in res["counterparty"].values():
            for r in cp["roles"].values():
                assert r["source_class"] != contract.AUDITED_DOCUMENT
            for d in cp["dimensions"].values():
                assert d["source_class"] != contract.AUDITED_DOCUMENT
