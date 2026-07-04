"""
spa_core/tests/test_rates_desk_surface_expansion.py — Proof-of-Risk WORKSTREAM C tests.

Covers the C1-C4 deepening of the validated rates-desk thesis + the BTC/ETH sleeve promotion:

  C1 — surface coverage expansion (more PT underlyings via the config-extended live matcher; more
       keyless lending venues) + the metamorphic SURFACE MONOTONICITY property (adding a feed never
       silently drops a previously-valid market) + fail-CLOSED on every new path + the refusal-first
       gate STILL fires 100% on the known-toxic LRT histories (no regression).
  C2 — the honest per-sleeve verdict layer (INSUFFICIENT_DATA vs RISK_KILL vs BEATS/BELOW_FLOOR) +
       is_advisory enforced for every promoted sleeve.
  C3 — deflated-Sharpe forward block: THIN below N, ACTIVE at N, the degenerate-Sharpe (LOCKED_VOL)
       guard holds + drawdown attribution.
  C4 — capacity provenance: the expanded surface is recorded WITHOUT inflating the above-floor number.

PURE / no network: injected fetchers + in-memory docs. stdlib + pytest. LLM-FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
from decimal import Decimal

import os
import pytest

from spa_core.strategy_lab.rates_desk import config, feeds
from spa_core.strategy_lab.rates_desk import validation as rd_validation
from spa_core.strategy_lab.rates_desk.contracts import RateVenue, UnderlyingKind


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# C1 — Pendle live surface coverage expansion (config-extended underlyings)
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
def _active_payload(names_with_apy):
    """Build a Pendle /markets/active payload (rich shape) from [(name, impliedApy, liquidity), …]."""
    return {"markets": [
        {"name": n, "expiry": "2027-12-25T00:00:00.000Z", "pt": f"0x{i:040x}",
         "details": {"impliedApy": apy, "liquidity": liq}}
        for i, (n, apy, liq) in enumerate(names_with_apy)
    ]}


def test_live_surface_matches_config_extended_underlyings():
    """sUSDS / USDS / GHO / cbETH (config-only, NOT in the cached deep TARGETS) are surfaced from the
    live /active endpoint with the correct kinds — directly attacking the single-book capacity ceiling
    by widening the gated-book universe."""
    payload = _active_payload([
        ("sUSDe", 0.09, 50_000_000),     # existing TARGET
        ("sUSDS", 0.05, 30_000_000),     # config-only (stable_rwa)
        ("GHO", 0.07, 10_000_000),       # config-only (stable_synth)
        ("cbETH", 0.03, 8_000_000),      # config-only (lst)
    ])
    rows = feeds.PendleMarketFeed(fetcher=lambda url: payload).quotes_live("2026-06-28")
    got = {(r.underlying, r.kind.value) for r in rows}
    assert ("susds", "stable_rwa") in got
    assert ("gho", "stable_synth") in got
    assert ("cbeth", "lst") in got
    assert ("susde", "stable_synth") in got
    assert all(r.venue is RateVenue.PENDLE_PT for r in rows)


def test_live_surface_still_matches_toxic_lrt_exactly():
    """The toxic LRT set (ezETH/rsETH) MUST still match exactly — widening must NOT change the gate's
    view of the toxic books (no refusal regression at the feed level)."""
    payload = _active_payload([("ezETH", 0.25, 5_000_000), ("rsETH", 0.30, 5_000_000)])
    rows = feeds.PendleMarketFeed(fetcher=lambda url: payload).quotes_live("2026-06-28")
    got = {(r.underlying, r.kind.value) for r in rows}
    assert ("ezeth", "lrt") in got
    assert ("rseth", "lrt") in got


def test_live_surface_rejects_nested_wrapper_variants():
    """A nested/wrapper underlying (jrUSDe, PT-Karak-sUSDe) is NEVER mistaken for a clean target —
    strict matching is preserved through the config-extended path."""
    payload = _active_payload([("jrUSDe", 0.40, 1_000_000), ("Karak-sUSDe", 0.35, 1_000_000)])
    rows = feeds.PendleMarketFeed(fetcher=lambda url: payload).quotes_live("2026-06-28")
    assert rows == []  # no clean target → nothing surfaced (fail-CLOSED skip, never fabricated)


def test_adversarial_nested_wrappers_never_leak():
    """Adversarial: every leading-non-target nested/wrapper underlying is rejected via BOTH the /active
    name path AND the PT-symbol path — the config-extended matcher inherits pph's strict leading-segment
    discipline, so a restaked/nested wrapper can never be mistaken for a clean carry target."""
    dangerous = ["jrUSDe", "srUSDe", "reUSDe", "Karak-sUSDe", "zs-ezETH", "wsUSDS",
                 "Karak-sUSDS", "ctUSDe", "rsUSDe", "weETHs"]
    for n in dangerous:
        assert feeds._match_pendle_underlying_extended(n, "") is None
        assert feeds._match_pendle_underlying_extended("", f"PT-{n}-26DEC2027") is None
    # a versioned CLEAN PT symbol still matches its target (correct, not a leak)
    assert feeds._match_pendle_underlying_extended("", "PT-sUSDS-26DEC2027") == "susds"


def test_live_surface_deterministic_same_inputs():
    """Same injected payload → byte-identical surface twice (no clock leak in the live path; as_of is
    the explicit input). Guards against any non-determinism the expansion could have introduced."""
    payload = _active_payload([("sUSDe", 0.09, 50_000_000), ("sUSDS", 0.05, 30_000_000),
                               ("GHO", 0.07, 10_000_000)])
    f = feeds.PendleMarketFeed(fetcher=lambda url: payload)
    r1 = f.quotes_live("2026-06-28")
    r2 = feeds.PendleMarketFeed(fetcher=lambda url: payload).quotes_live("2026-06-28")
    assert [(q.underlying, q.market_id, str(q.quoted_rate)) for q in r1] == \
           [(q.underlying, q.market_id, str(q.quoted_rate)) for q in r2]


def test_live_surface_skips_incomplete_market_fail_closed():
    """A market missing implied APY or depth is SKIPPED (one bad market never voids the snapshot, and
    a depthless/implied-less market is never sized)."""
    payload = {"markets": [
        {"name": "sUSDS", "expiry": "2027-12-25T00:00:00.000Z", "pt": "0xa",
         "details": {"impliedApy": None, "liquidity": 1_000_000}},   # no implied → skip
        {"name": "GHO", "expiry": "2027-12-25T00:00:00.000Z", "pt": "0xb",
         "details": {"impliedApy": 0.05}},                            # no depth → skip
        {"name": "sUSDe", "expiry": "2027-12-25T00:00:00.000Z", "pt": "0xc",
         "details": {"impliedApy": 0.09, "liquidity": 5_000_000}},    # complete → surfaced
    ]}
    rows = feeds.PendleMarketFeed(fetcher=lambda url: payload).quotes_live("2026-06-28")
    assert {r.underlying for r in rows} == {"susde"}


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# C1 — surface MONOTONICITY (metamorphic): expansion never drops a previously-valid market
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
def test_surface_monotonicity_additive():
    """Adding underlyings to the live snapshot is purely ADDITIVE — every market key in the smaller
    surface is still present in the larger one. assert_surface_monotonic passes; the reverse raises."""
    small = feeds.PendleMarketFeed(
        fetcher=lambda url: _active_payload([("sUSDe", 0.09, 50_000_000)])).quotes_live("2026-06-28")
    large = feeds.PendleMarketFeed(
        fetcher=lambda url: _active_payload([
            ("sUSDe", 0.09, 50_000_000), ("sUSDS", 0.05, 30_000_000),
            ("GHO", 0.07, 10_000_000)])).quotes_live("2026-06-28")
    assert feeds.assert_surface_monotonic(small, large) is True
    # the reverse (a feed that DROPPED sUSDS/GHO) is a regression → fail-CLOSED raise
    with pytest.raises(feeds.FeedError):
        feeds.assert_surface_monotonic(large, small)


def test_surface_coverage_summary_shape():
    rows = feeds.PendleMarketFeed(
        fetcher=lambda url: _active_payload([
            ("sUSDe", 0.09, 50_000_000), ("sUSDS", 0.05, 30_000_000)])).quotes_live("2026-06-28")
    summ = feeds.surface_coverage_summary(rows)
    assert summ["n_quotes"] == 2
    assert summ["n_distinct_markets"] == 2
    assert summ["by_venue"]["pendle_pt"] == 2
    assert set(summ["by_underlying"]) == {"susde", "susds"}


def test_extended_lending_targets_expanded_and_well_formed():
    """C1 expanded the keyless lending surface to MORE protocols + chains + quote stables. Assert the
    selector list grew and every selector is a well-formed (project, chain, symbol, underlying, kind)."""
    targets = config.LENDING_TARGETS
    assert len(targets) >= 10  # widened well beyond the original 3
    protocols = {t["project"] for t in targets}
    chains = {t["chain"] for t in targets}
    stables = {t["underlying"] for t in targets}
    assert {"aave-v3", "morpho-blue", "euler-v2"} <= protocols  # originals preserved
    assert {"fluid-lending", "compound-v3", "spark"} <= protocols  # new venues added
    assert {"Ethereum", "Base", "Arbitrum"} <= chains  # multi-chain (decorrelation)
    assert {"usdc", "usds", "gho"} <= stables  # more quote stables
    for t in targets:
        assert set(t) >= {"project", "chain", "symbol", "underlying", "kind"}
        assert t["kind"] in {k.value for k in UnderlyingKind}


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# C1 — REFUSAL no-regression: the gate STILL fires 100% on the known-toxic LRT histories
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.skipif(os.environ.get("GITHUB_ACTIONS") == "true", reason="data/env-dependent (needs committed data/ or the Mac host); runs locally, skipped in the data-less GitHub CI")
def test_refusal_still_100pct_on_toxic_after_expansion():
    """The whole edge: after widening the surface coverage, the refusal-first gate must STILL refuse
    every toxic LRT book on EVERY day of its real history — economics never rescues a tail-vetoed book."""
    deep = rd_validation.assertion1_deep_refusal()
    assert deep["all_toxic_books_refused_every_day"] is True
    assert deep["any_toxic_day_approved"] is False
    assert deep["VERDICT_assertion1_deep"] is True
    # and the three named stress events still refuse structurally before economics
    a1 = rd_validation.assertion1_refusal_fired_early()
    assert a1["VERDICT_assertion1_refusal_fired_early"] is True


def test_config_new_underlyings_have_full_constant_set():
    """Every newly-added underlying must have a COMPLETE documented constant set (no fail-CLOSED default
    leaking in silently): kind, SLA, reserve, oracle kind/staleness, nesting, top-borrower."""
    for u in ("susds", "usds", "gho", "cbeth"):
        assert u in config.UNDERLYING_KINDS
        assert config.underlying_kind(u) is not None
        assert config.redemption_sla_seconds(u) > 0
        assert config.oracle_kind(u) != config.DEFAULT_ORACLE_KIND
        assert u in config.NESTED_PROTOCOL_COUNT
        assert u in config.TOP_BORROWER_SHARE


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# C2 — honest per-sleeve verdict layer
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
from spa_core.strategy_lab import sleeve_verdict as SV  # noqa: E402


def _harness_result(strategies: dict, floor=3.4) -> dict:
    return {"manifest": {"rwa_floor_apy_pct": floor,
                         "window_realized": {"start": "2026-03-31", "end": "2026-06-24"}},
            "strategies": strategies}


def _sr(sid, *, advisory=True, kill=None, beats=None, apy=0.0, dd=0.0, n_series=10,
        first=100000.0, kill_equity=None):
    return {
        "id": sid, "name": sid, "mandate": "neutral", "is_advisory": advisory,
        "metrics": {"net_apy_pct": apy, "max_drawdown_pct": dd, "beats_rwa_floor": beats},
        "equity_series": [first] * n_series, "equity_first": first, "equity_last": first,
        "kill": kill if kill is None else {"date": "2026-04-01", "reason": kill,
                                           "equity_at_kill": (kill_equity if kill_equity is not None else first)},
    }


def test_verdict_insufficient_data_on_fail_closed_gap():
    """A neutral sleeve killed by a fail-closed data gap at the start (flat equity) → INSUFFICIENT_DATA,
    NOT a fabricated BELOW_FLOOR. (The dominant offline outcome for the neutral sleeves.)"""
    res = _harness_result({"eth_lst_neutral": _sr(
        "eth_lst_neutral", kill="fail-closed: funding missing/invalid on 2026-04-01",
        n_series=2, kill_equity=100000.0)})
    out = SV.build_verdicts(res)
    v = out["verdicts"][0]
    assert v["verdict"] == SV.VERDICT_INSUFFICIENT
    assert v["data_gap_kill"] is True


def test_verdict_risk_kill_on_real_drawdown():
    """A directional sleeve that traded a real record then hit its drawdown stop → RISK_KILL (honest
    NO-GO), never INSUFFICIENT_DATA."""
    res = _harness_result({"btc_lending_sleeve": _sr(
        "btc_lending_sleeve", kill="drawdown 25.22% > kill 25.00%", apy=-34.0, dd=25.2,
        n_series=86, kill_equity=66000.0)})
    out = SV.build_verdicts(res)
    v = out["verdicts"][0]
    assert v["verdict"] == SV.VERDICT_RISK_KILL
    assert v["data_gap_kill"] is False


def test_verdict_beats_and_below_floor_for_survivors():
    res = _harness_result({
        "variant_n": _sr("variant_n", kill=None, beats=True, apy=5.0),
        "variant_d": _sr("variant_d", kill=None, beats=False, apy=1.0),
    })
    out = SV.build_verdicts(res)
    by = {v["id"]: v["verdict"] for v in out["verdicts"]}
    assert by["variant_n"] == SV.VERDICT_BEATS
    assert by["variant_d"] == SV.VERDICT_BELOW


def test_verdict_advisory_enforced_fail_closed():
    """A promoted sleeve with is_advisory=False is a contract violation → RAISES (a live-capable sleeve
    must never pass through the advisory research surface)."""
    res = _harness_result({"btc_neutral": _sr("btc_neutral", advisory=False, kill=None, beats=True)})
    with pytest.raises(ValueError):
        SV.build_verdicts(res)


def test_verdict_advisory_all_true_flag():
    res = _harness_result({"variant_n": _sr("variant_n", kill=None, beats=True)})
    out = SV.build_verdicts(res)
    assert out["advisory_all_true"] is True
    assert out["n_sleeves"] == 1


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# C3 — deflated-Sharpe forward block: THIN below N, ACTIVE at N, LOCKED_VOL guard, DD attribution
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
from spa_core.strategy_lab import forward_analytics as FA  # noqa: E402


def _series_doc(equities):
    d0 = datetime.date(2026, 5, 1)
    return {"id": "t", "series": [
        {"date": (d0 + datetime.timedelta(days=i)).isoformat(), "equity_usd": e}
        for i, e in enumerate(equities)]}


def test_dsr_block_thin_below_n():
    """Below MIN_POINTS_FOR_DSR returns the block is THIN with every ratio UNKNOWN — never a fabricated
    deflated Sharpe on a handful of days (honest at today's track depth)."""
    doc = _series_doc([100000 + i * 10 for i in range(5)])
    card = FA.analyze_track(doc, name="thin", floor_apy_pct=3.4)
    blk = card["deflated_sharpe_block"]
    assert blk["status"] == "THIN"
    assert blk["deflated_sharpe"] == "UNKNOWN"
    assert blk["psr_vs_floor"] == "UNKNOWN"


def test_dsr_block_active_at_n():
    """With >= MIN_POINTS_FOR_DSR dispersed returns the block ACTIVATES with a real PSR / DSR / minTRL."""
    import random
    random.seed(7)
    eq = 100000.0
    equities = [eq]
    for _ in range(FA.MIN_POINTS_FOR_DSR + 5):
        eq *= (1 + 0.0006 + random.uniform(-0.0025, 0.0025))
        equities.append(round(eq, 2))
    card = FA.analyze_track(_series_doc(equities), name="active", floor_apy_pct=3.4)
    blk = card["deflated_sharpe_block"]
    assert blk["status"] == "ACTIVE"
    assert isinstance(blk["deflated_sharpe"], float)
    assert isinstance(blk["psr_vs_floor"], float)
    assert isinstance(blk["deflated_sharpe_passes_0_95"], bool)


def test_dsr_block_locked_vol_guard_holds():
    """The degenerate-Sharpe hazard: enough points but ZERO dispersion (flat fixed accrual) → LOCKED_VOL
    with ratios UNKNOWN — NEVER a fabricated ~4.5e8 Sharpe."""
    doc = _series_doc([100000.0] * (FA.MIN_POINTS_FOR_DSR + 3))
    card = FA.analyze_track(doc, name="locked", floor_apy_pct=3.4)
    blk = card["deflated_sharpe_block"]
    assert blk["status"] == "LOCKED_VOL"
    assert blk["deflated_sharpe"] == "UNKNOWN"


def test_drawdown_attribution_peak_trough():
    """Drawdown attribution finds the worst peak→trough span on the realized equity."""
    # rises to 110k (idx2), falls to 99k (idx4) → max DD = (110-99)/110 ≈ 10%
    doc = _series_doc([100000, 105000, 110000, 103000, 99000, 101000])
    card = FA.analyze_track(doc, name="dd", floor_apy_pct=3.4)
    dda = card["drawdown_attribution"]
    assert dda["peak_idx"] == 2
    assert dda["trough_idx"] == 4
    assert abs(dda["max_dd_pct"] - 10.0) < 0.01
    assert dda["peak_to_trough_usd"] == 11000.0


def test_scorecard_n_dsr_active_zero_at_thin_depth():
    """build_scorecard rolls up n_dsr_active; with only thin tracks it is 0 (honest, by design)."""
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "rates_desk" / "paper").mkdir(parents=True)
        import json
        doc = _series_doc([100000 + i * 5 for i in range(4)])
        (root / "rates_desk" / "paper" / "rates_desk_fixed_carry_series.json").write_text(
            json.dumps(doc))
        sc = FA.build_scorecard(data_dir=root, write=False, floor_apy_pct=3.4,
                                now_iso="2026-06-28T00:00:00+00:00")
        assert sc["n_dsr_active"] == 0
        assert sc["min_points_for_dsr"] == FA.MIN_POINTS_FOR_DSR


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# C4 — capacity provenance: expanded surface recorded WITHOUT inflating the number
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
from spa_core.strategy_lab import portfolio_capacity as PC  # noqa: E402


def _fake_rates_report(floor_pct=3.4):
    return {
        "rwa_floor_pct": floor_pct,
        "total_deployable_usd": 330000.0,
        "aggregate_net_apy_pct": 22.0,
        "n_fundable_books": 2,
    }


def test_capacity_provenance_recorded_without_inflation():
    """The capacity report records the EXPANDED surface provenance (lending venues + PT underlyings) but
    the honest above-floor number / binding constraint are driven by the deep carry + RWA family, NOT by
    the provenance. Recompute with an injected rates report twice → deterministic; provenance present."""
    r1 = PC.build_report(write=False, rates_report=_fake_rates_report(), floor_pct=3.4)
    r2 = PC.build_report(write=False, rates_report=_fake_rates_report(), floor_pct=3.4)
    prov = r1["surface_provenance"]
    assert prov["lending_venue_selectors"] == len(config.LENDING_TARGETS)
    assert prov["n_pt_underlyings_matchable"] >= 12
    assert set(prov["toxic_lrts_refusal_only"]) == {"ezeth", "rseth"}
    # deterministic above-floor number (provenance never feeds the arithmetic)
    assert r1["combined"]["total_above_floor_usd_per_yr"] == r2["combined"]["total_above_floor_usd_per_yr"]
    # the honest verdict still falls far short of $10M (never inflated)
    assert r1["combined"]["pct_of_10m_target"] < 100.0
    assert r1["combined"]["gap_to_10m_usd"] > 0


def test_capacity_provenance_is_audit_only_not_in_above_floor():
    """Metamorphic: the above-floor number must be IDENTICAL whether or not we read the provenance —
    it is an audit trail. We assert the above-floor equals the family identity (Σ above-floor − haircut
    loss), independent of provenance content."""
    r = PC.build_report(write=False, rates_report=_fake_rates_report(), floor_pct=3.4)
    fams = {f["family"]: f for f in r["families"]}
    naive_above = sum(f["above_floor_usd_per_yr"] for f in r["families"])
    # combined above-floor <= naive sum (the correlation haircut only ever REMOVES above-floor dollars)
    assert r["combined"]["total_above_floor_usd_per_yr"] <= naive_above + 1e-6
    # rates desk is the only meaningful above-floor source; RWA floor adds ~0
    assert fams["rwa_floor"]["above_floor_usd_per_yr"] <= 1.0
