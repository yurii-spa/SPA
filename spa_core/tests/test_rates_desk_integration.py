"""
spa_core/tests/test_rates_desk_integration.py — the rates-desk WIRING (§7 integration) tests.

Covers the five integration pieces built on top of the engine + gate + 4 sleeves + feeds:
  1. backtest_rates  — replay is DETERMINISTIC + produces per-sleeve metrics (net_apy/maxDD/deflated
                        Sharpe/beats_floor/kills/refusals); BasisHedge is honestly BLOCKED-NO-HEDGE.
  2. promotion_rates — maps the backtest into the lab promotion rubric → a stage per sleeve; FixedCarry
                        reaches PAPER_CANDIDATE, BasisHedge is BLOCKED-NO-HEDGE.
  3. proof_chain     — appends BOTH entries AND refusals to the hash_chain, verifies, deterministic.
  4. paper_rates     — registers FixedCarry into a live-style paper service; restart-survival + per-day
                        idempotency (no double-accrue).
  5. surface_io      — round-trips a cached surface + scans it (the shape the API serves).

Hermetic + fast: a tiny SYNTHETIC deep dataset (one stable-synth carry market + one toxic LRT market)
drives the backtest, so the tests do not depend on the multi-MB live cache. stdlib only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from decimal import Decimal as D

import pytest

from spa_core.audit import hash_chain
from spa_core.strategy_lab.rates_desk import (
    backtest_rates,
    promotion_rates,
    proof_chain,
    surface_io,
)
from spa_core.strategy_lab.rates_desk.contracts import (
    D0,
    KillState,
    Opportunity,
    RatePolicyParams,
    RateQuote,
    RateVenue,
    TradeShape,
    UnderlyingKind,
    UnderlyingRisk,
)
from spa_core.strategy_lab.rates_desk.feeds import BorosFeed
from spa_core.strategy_lab.rates_desk.sleeves import FixedCarrySleeve

try:
    from spa_core.strategy_lab.rates_desk import pendle_pt_history as _pph
    _pph.load()
    _DEEP_AVAILABLE = True
except Exception:  # noqa: BLE001 — deep cache may be absent in a fresh clone / hermetic CI
    _DEEP_AVAILABLE = False


# ── a tiny synthetic deep dataset (carry market + toxic LRT market) ───────────────────────────────
def _series(start_day: int, n: int, implied: float, underlying: float):
    import datetime
    base = datetime.date(2024, 6, 1)
    return [
        {"date": (base + datetime.timedelta(days=start_day + i)).isoformat(),
         "implied_yield": implied, "underlying_yield": underlying, "pt_price": None}
        for i in range(n)
    ]


@pytest.fixture
def deep_dataset():
    """Synthetic deep dataset: one harvestable sUSDe carry market (implied >> fair) maturing well past
    the window, and one toxic ezETH LRT market (the gate must refuse it). 220 days of history."""
    return {
        "generated_at": "2024-06-01T00:00:00+00:00",
        "method": "synthetic_test",
        "underlyings": ["sUSDe", "ezETH"],
        "window": {"start": "2024-06-01", "end": "2025-01-07"},
        "markets": {
            "PT-sUSDE-TEST": {
                "underlying": "sUSDe", "kind": "stable_synth", "symbol": "PT-sUSDE-TEST",
                "market_address": "0xcarry", "pt_address": "0xpt", "maturity": "2026-01-01",
                "method": "synthetic", "series": _series(0, 220, 0.12, 0.09),
            },
            "PT-ezETH-TEST": {
                "underlying": "ezETH", "kind": "lrt", "symbol": "PT-ezETH-TEST",
                "market_address": "0xtoxic", "pt_address": "0xptx", "maturity": "2026-01-01",
                "method": "synthetic", "series": _series(0, 220, 0.35, 0.03),
            },
        },
    }


@pytest.fixture
def funding():
    """Benign funding (no negative streak) so the funding-flip kill is not the dominant signal."""
    import datetime
    base = datetime.date(2024, 6, 1)
    return {(base + datetime.timedelta(days=i)).isoformat(): 0.0001 for i in range(260)}


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 1) backtest replay
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_backtest_replay_deterministic(deep_dataset, funding):
    r1 = backtest_rates.run(deep=deep_dataset, funding=funding, write=False)
    r2 = backtest_rates.run(deep=deep_dataset, funding=funding, write=False)
    r1["sleeves"]  # touch
    a = json.dumps(r1["sleeves"], sort_keys=True)
    b = json.dumps(r2["sleeves"], sort_keys=True)
    assert a == b, "backtest replay is not deterministic"


def test_backtest_replay_per_sleeve_metrics(deep_dataset, funding):
    r = backtest_rates.run(deep=deep_dataset, funding=funding, write=False)
    sleeves = r["sleeves"]
    assert set(sleeves) == {"fixed_carry", "levered_carry", "basis_hedge", "rate_matrix"}
    for kind, blk in sleeves.items():
        for field in ("net_apy_pct", "max_drawdown_pct", "deflated_sharpe",
                      "beats_floor", "kills", "refusals_count", "approvals_count", "carry_days"):
            assert field in blk, f"{kind} missing {field}"
    # the gate REFUSED the toxic LRT book (the refusal edge), and OPENED the harvestable carry leg
    assert sleeves["fixed_carry"]["refusals_count"] > 0
    assert sleeves["fixed_carry"]["approvals_count"] > 0
    assert sleeves["fixed_carry"]["carry_days"] > 0


@pytest.mark.skipif(not _DEEP_AVAILABLE, reason="deep pendle_pt_history cache not present")
def test_backtest_real_deep_carry_beats_floor():
    """On the REAL cached deep dataset the harvestable carry sleeve must beat the ~3.4% floor (the
    validated GO result) — the thin synthetic fixture is exit-cap-bound so it under-states this."""
    r = backtest_rates.run(write=False)
    assert r["sleeves"]["fixed_carry"]["beats_floor"] is True
    assert r["sleeves"]["fixed_carry"]["deflated_sharpe_passes_0_95"] is True


# ── HONEST CAPITAL BASIS: net_apy is on the TOTAL sleeve capital, NOT the deployed slice ────────────
def test_net_apy_is_on_total_capital_not_deployed_slice(deep_dataset, funding):
    """PIN: net_apy must be the return on the TOTAL $100k sleeve book (deployed carry + idle cash at the
    floor), NOT the annualized return on the small deployed slice. A FixedCarry book that can only safely
    deploy a FRACTION into thin PT pools (exit-capacity sizing) MUST show a MODEST book APY — bounded
    BELOW the locked carry rate, because the idle remainder only earns the ~3.4% floor.

    This is the guard against the 79.69% artifact: a 12%-implied PT held at exit-cap size with the rest
    of the book idle can NEVER make the WHOLE book return 12% — let alone the un-maturing 99%-APY bag the
    bug produced. The capacity-constrained book APY is strictly LESS than the unconstrained carry rate."""
    r = backtest_rates.run(deep=deep_dataset, funding=funding, write=False)
    fc = r["sleeves"]["fixed_carry"]
    floor_pct = r["rwa_floor_pct"]                       # 3.4
    carry_rate_pct = 0.12 * 100.0                        # the synthetic sUSDe PT implied (12%)

    # the harness records that net_apy is on total capital with idle cash at the floor.
    assert fc["capital_basis"] == "total_sleeve_capital"
    assert fc["idle_cash_earns_floor"] is True
    assert fc["capital_usd"] == 100000.0

    napy = fc["net_apy_pct"]
    # (1) STRICTLY below the unconstrained carry rate — the capacity constraint costs real edge.
    assert napy < carry_rate_pct, (
        f"book APY {napy}% must be < unconstrained carry {carry_rate_pct}% (capacity-bound)")
    # (2) At/above the floor (the idle remainder alone earns the floor; deployed carry only adds).
    assert napy >= floor_pct - 0.01
    # (3) Bounded by the capital-basis identity book_apy ≈ frac·carry + (1-frac)·floor for SOME deploy
    #     fraction in [0,1]; equivalently it lies in [floor, carry]. (Strict slice-only annualization
    #     would put it AT or ABOVE the carry rate — which (1) forbids.)
    assert floor_pct - 0.01 <= napy <= carry_rate_pct


def test_idle_cash_floor_credited_when_no_opportunity():
    """PIN: on a stretch with NO harvestable PT (whole book idle), the book still accrues the RWA floor
    on its cash — so over a fully-idle window the book APY converges to the floor, never 0% and never the
    deployed-slice rate. (Confirms idle/refused/between-maturity capital earns AT MOST the floor.)"""
    import datetime
    base = datetime.date(2024, 6, 1)
    # a dataset whose only market MATURED before the window even starts → never harvestable → book idle.
    deep = {
        "generated_at": "2024-06-01T00:00:00+00:00", "method": "synthetic_test",
        "underlyings": ["sUSDe"], "window": {"start": "2024-06-01", "end": "2024-09-08"},
        "markets": {
            "PT-sUSDE-MATURED": {
                "underlying": "sUSDe", "kind": "stable_synth", "symbol": "PT-sUSDE-MATURED",
                "market_address": "0x", "pt_address": "0x", "maturity": "2099-01-01",
                # implied yield is ABOVE the 30% global ceiling on every day → never approvable → idle.
                "series": [
                    {"date": (base + datetime.timedelta(days=i)).isoformat(),
                     "implied_yield": 0.95, "underlying_yield": 0.10, "pt_price": None}
                    for i in range(100)],
            },
        },
    }
    funding = {(base + datetime.timedelta(days=i)).isoformat(): 0.0001 for i in range(120)}
    r = backtest_rates.run(deep=deep, funding=funding, write=False)
    fc = r["sleeves"]["fixed_carry"]
    floor_pct = r["rwa_floor_pct"]
    # the 95%-implied PT is over the global APY ceiling → composed-refused → NO book opens (carry_days 0)
    # → book stays idle → earns only the floor. (approvals_count counts gate-approvals; the global ceiling
    # blocks the book from opening, so carry_days/net_apy are the honest 'did it actually hold?' signal.)
    assert fc["carry_days"] == 0, "an over-ceiling PT must not open a carry book"
    assert abs(fc["net_apy_pct"] - floor_pct) < 0.2, (
        f"fully-idle book APY {fc['net_apy_pct']}% must converge to the floor {floor_pct}%, "
        f"not the 95% slice rate")


def test_over_ceiling_pt_is_refused_not_held(deep_dataset, funding):
    """PIN: a PT with implied yield ABOVE the global RiskPolicy 30% APY ceiling is REFUSED (composed
    under the global policy), never opened — so it cannot inflate the book. The toxic LRT market in the
    fixture is at 35% implied; the harvestable sUSDe at 12% is the only one that may open."""
    # raise the toxic market's implied above the ceiling is already the case (0.35 LRT); also confirm a
    # raised stable-synth above the ceiling does not open.
    d2 = json.loads(json.dumps(deep_dataset))
    for pt in d2["markets"]["PT-sUSDE-TEST"]["series"]:
        pt["implied_yield"] = 0.40                       # push the carry PT over the 30% ceiling
    r = backtest_rates.run(deep=d2, funding=funding, write=False)
    fc = r["sleeves"]["fixed_carry"]
    # nothing opens a book (both markets over the 30% global ceiling → composed-refused), and the book
    # earns only the idle floor. carry_days==0 is the honest 'no book held' signal (approvals_count counts
    # gate-approvals; the global ceiling is what blocks the actual book-open).
    assert fc["carry_days"] == 0, "no carry book may open when every PT is over the global APY ceiling"
    assert abs(fc["net_apy_pct"] - r["rwa_floor_pct"]) < 0.2


def test_backtest_basis_hedge_blocked_no_hedge(deep_dataset, funding):
    r = backtest_rates.run(deep=deep_dataset, funding=funding, write=False)
    bh = r["sleeves"]["basis_hedge"]
    assert bh.get("blocked_no_hedge") is True
    assert bh["beats_floor"] is False
    assert bh["refusals_count"] == 0 and bh["approvals_count"] == 0
    # honest: the Boros hedge is unavailable for every underlying
    assert r["hedge_available_any"] is False


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 1b) BACKTEST-ONLY funding-proxy BasisHedge (architect T4) — research only, NEVER live
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_hedge_proxy_default_off_leaves_live_path_unchanged(deep_dataset, funding):
    """DEFAULT (HEDGE_IS_BACKTEST_PROXY=False): the basis_hedge block is BLOCKED-NO-HEDGE, carries NO
    backtest_proxy sub-block, and the live hedge map is all-False — byte-identical to the prior result."""
    assert backtest_rates.HEDGE_IS_BACKTEST_PROXY is False  # the module flag ships OFF
    r = backtest_rates.run(deep=deep_dataset, funding=funding, write=False)
    bh = r["sleeves"]["basis_hedge"]
    assert bh.get("blocked_no_hedge") is True
    assert "backtest_proxy" not in bh
    assert r.get("hedge_is_backtest_proxy") is False
    assert r["hedge_available_any"] is False


def test_hedge_proxy_on_produces_backtest_apy_but_stays_blocked(deep_dataset, funding):
    """HEDGE_IS_BACKTEST_PROXY=True (via arg): the BasisHedge sleeve produces a backtest APY using the
    funding proxy (a SEPARATE backtest_proxy block), under the SAME honest accounting (total-capital
    basis, idle@floor). The PRIMARY block STILL carries blocked_no_hedge=True and the live hedge map is
    STILL all-False — the proxy is research/reporting only and never flips live eligibility."""
    r = backtest_rates.run(deep=deep_dataset, funding=funding, write=False, hedge_backtest_proxy=True)
    bh = r["sleeves"]["basis_hedge"]
    # PRIMARY (live) verdict unchanged
    assert bh.get("blocked_no_hedge") is True
    assert r["hedge_available_any"] is False
    assert r.get("hedge_is_backtest_proxy") is True
    # the research-only proxy block exists with the honest accounting + a clear live-BLOCKED label
    proxy = bh.get("backtest_proxy")
    assert isinstance(proxy, dict)
    assert proxy["live_eligible"] is False
    assert "BACKTEST-ONLY" in proxy["label"] and "live-BLOCKED" in proxy["label"]
    assert proxy["capital_basis"] == "total_sleeve_capital"
    assert proxy["idle_cash_earns_floor"] is True
    assert "net_apy_pct" in proxy and isinstance(proxy["net_apy_pct"], float)
    # the proxy actually formed BASIS_HEDGE candidates (the synthetic Boros leg made the shape exist)
    assert proxy["approvals_count"] > 0 or proxy["refusals_count"] > 0


def test_hedge_proxy_determinism(deep_dataset, funding):
    """Same (deep, funding) + proxy ON → identical basis_hedge backtest_proxy block (PURE/deterministic)."""
    a = backtest_rates.run(deep=deep_dataset, funding=funding, write=False, hedge_backtest_proxy=True)
    b = backtest_rates.run(deep=deep_dataset, funding=funding, write=False, hedge_backtest_proxy=True)
    pa = a["sleeves"]["basis_hedge"]["backtest_proxy"]
    pb = b["sleeves"]["basis_hedge"]["backtest_proxy"]
    assert json.dumps(pa, sort_keys=True) == json.dumps(pb, sort_keys=True)


def test_hedge_proxy_does_not_touch_live_feed_or_gate(deep_dataset, funding):
    """SAFETY INVARIANT: even with the proxy ON, the LIVE Boros feed and the live gate are untouched —
    BorosFeed.HEDGE_ENABLED stays False, hedge_available() stays all-False, and the live (proxy-free)
    surface still yields ZERO executable BASIS_HEDGE candidates → the live gate cannot open one."""
    from spa_core.strategy_lab.rates_desk.opportunity_engine import OpportunityEngine
    from spa_core.strategy_lab.rates_desk.contracts import TradeShape

    # run with proxy ON; it must not mutate the live feed class state
    backtest_rates.run(deep=deep_dataset, funding=funding, write=False, hedge_backtest_proxy=True)
    assert BorosFeed.HEDGE_ENABLED is False
    assert all(v is False for v in BorosFeed().hedge_available(["susde", "ezeth", "wsteth"]).values())

    # the LIVE-style surface (no proxy) carries NO boros quotes and hedge_available all-False, so the
    # OpportunityEngine emits zero BASIS_HEDGE candidates → nothing for the live gate to ever approve.
    fneg = D("0")
    hedge_map = BorosFeed().hedge_available(
        sorted({m["underlying"].lower() for m in deep_dataset["markets"].values()}))
    surface, risks = backtest_rates.build_deep_surface("2024-09-01", deep_dataset, fneg, hedge_map)
    assert surface.boros_quotes == {}
    assert all(q.hedge_available is False for q in surface.pt_quotes.values())
    eng = OpportunityEngine()
    cands = [so for so in eng.scan_detailed(surface, risks, "2024-09-01")
             if so.opportunity.shape == TradeShape.BASIS_HEDGE]
    assert cands == [], "live (proxy-free) surface must never form a BASIS_HEDGE candidate"


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 2) promotion mapping
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_promotion_mapping_assigns_stages(deep_dataset, funding):
    bt = backtest_rates.run(deep=deep_dataset, funding=funding, write=False)
    report = promotion_rates.build_report(write=False, backtest=bt)
    stages = {s["id"]: s["stage"] for s in report["sleeves"]}
    assert report["n_sleeves"] == 4
    # every sleeve is assigned a valid stage + carries a reason string
    valid = {"REJECT", "BACKTEST_PASS", "PAPER_CANDIDATE", promotion_rates.STAGE_BLOCKED_NO_HEDGE}
    for s in report["sleeves"]:
        assert s["stage"] in valid, s["stage"]
        assert isinstance(s.get("reason"), str) and s["reason"]
    # BasisHedge is honestly blocked (cannot be promoted on no hedge venue)
    assert stages["rates_desk_basis_hedge"] == promotion_rates.STAGE_BLOCKED_NO_HEDGE


@pytest.mark.skipif(not _DEEP_AVAILABLE, reason="deep pendle_pt_history cache not present")
def test_promotion_real_deep_fixed_carry_reaches_paper_candidate():
    """On the REAL deep dataset the validated FixedCarry sleeve reaches PAPER_CANDIDATE (the GO
    result), BasisHedge stays BLOCKED-NO-HEDGE."""
    bt = backtest_rates.run(write=False)
    report = promotion_rates.build_report(write=False, backtest=bt)
    stages = {s["id"]: s["stage"] for s in report["sleeves"]}
    assert stages["rates_desk_fixed_carry"] == "PAPER_CANDIDATE"
    assert stages["rates_desk_basis_hedge"] == promotion_rates.STAGE_BLOCKED_NO_HEDGE


def test_promotion_mapping_deterministic(deep_dataset, funding):
    bt = backtest_rates.run(deep=deep_dataset, funding=funding, write=False)
    r1 = promotion_rates.build_report(write=False, backtest=bt)
    r2 = promotion_rates.build_report(write=False, backtest=bt)
    assert json.dumps(r1["sleeves"], sort_keys=True) == json.dumps(r2["sleeves"], sort_keys=True)


def test_promotion_missing_backtest_fail_closed():
    report = promotion_rates.build_report(write=False, backtest={})
    assert report["n_sleeves"] == 0
    assert report["sleeves"] == []


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 3) proof chain
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _toxic_and_carry_verdicts():
    """A scan over one carry + one toxic quote → one ENTRY + one REFUSAL (deterministic)."""
    carry_q = RateQuote(
        underlying="susde", kind=UnderlyingKind.STABLE_SYNTH, venue=RateVenue.PENDLE_PT,
        protocol="pendle", market_id="PT-susde", tenor_seconds=86400 * 90, as_of="2026-01-01",
        quoted_rate=D("0.12"), tvl_usd=D("5e7"), exit_liquidity_usd=D("2e6"), hedge_available=True)
    toxic_q = RateQuote(
        underlying="ezeth", kind=UnderlyingKind.LRT, venue=RateVenue.PENDLE_PT,
        protocol="pendle", market_id="PT-ezeth", tenor_seconds=86400 * 90, as_of="2026-01-01",
        quoted_rate=D("0.35"), tvl_usd=D("5e7"), exit_liquidity_usd=D("2e6"), hedge_available=False)
    carry_risk = UnderlyingRisk(
        underlying="susde", as_of="2026-01-01", nav_redemption_value=D("1"), market_price=D("1"),
        peg_distance=D0, peg_vol_30d=D0, redemption_sla_seconds=86400, reserve_fund_ratio=D("0.05"),
        funding_neg_frac_90d=D("0.1"), oracle_kind="chainlink", oracle_staleness_seconds=300,
        nested_protocol_count=1, top_borrower_share=D("0.1"))
    toxic_risk = UnderlyingRisk(
        underlying="ezeth", as_of="2026-01-01", nav_redemption_value=D("1"), market_price=D("0.994"),
        peg_distance=D("0.006"), peg_vol_30d=D("0.02"), redemption_sla_seconds=86400 * 7,
        reserve_fund_ratio=D0, funding_neg_frac_90d=D("0.30"), oracle_kind="redstone",
        oracle_staleness_seconds=600, nested_protocol_count=4, top_borrower_share=D("0.45"))
    sleeve = FixedCarrySleeve()
    sleeve.init(100000, {})
    return sleeve.scan_and_enter([carry_q, toxic_q],
                                 {"susde": carry_risk, "ezeth": toxic_risk}, "2026-01-01")


def test_proof_chain_appends_entries_and_refusals(tmp_path, monkeypatch):
    monkeypatch.setattr(hash_chain, "_CHAIN", tmp_path / "audit_chain.jsonl")
    log_path = tmp_path / "decision_log.jsonl"
    verdicts = _toxic_and_carry_verdicts()
    assert any(v.approved for v in verdicts) and any(not v.approved for v in verdicts)

    entries = proof_chain.record_decisions(verdicts, ts="2026-01-01T00:00:00+00:00", log_path=log_path)
    assert len(entries) == len(verdicts)
    # the chain verifies (tamper-evident, prev-linked)
    assert proof_chain.verify()["valid"] is True
    # the readable mirror carries BOTH kinds
    rows = proof_chain.recent_decisions(100, log_path=log_path)
    kinds = {r["kind"] for r in rows}
    assert "ENTRY" in kinds and "REFUSAL" in kinds
    # each decision carries a proof hash + the decomposition
    for r in rows:
        assert r["proof_hash"] and "decomposition" in r


def test_proof_chain_payload_deterministic():
    verdicts = _toxic_and_carry_verdicts()
    p1 = [proof_chain.decision_payload(v)["proof_hash"] for v in verdicts]
    p2 = [proof_chain.decision_payload(v)["proof_hash"] for v in verdicts]
    assert p1 == p2


def test_proof_chain_tamper_detected(tmp_path, monkeypatch):
    chain = tmp_path / "audit_chain.jsonl"
    monkeypatch.setattr(hash_chain, "_CHAIN", chain)
    verdicts = _toxic_and_carry_verdicts()
    proof_chain.record_decisions(verdicts, ts="2026-01-01T00:00:00+00:00",
                                 log_path=tmp_path / "decision_log.jsonl")
    # mutate a historical entry → the chain must break
    lines = chain.read_text().splitlines()
    obj = json.loads(lines[0])
    obj["payload"]["approved"] = not obj["payload"]["approved"]
    lines[0] = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    chain.write_text("\n".join(lines) + "\n")
    assert proof_chain.verify()["valid"] is False


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 4) paper service registration (restart-survival + idempotency)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _paper_provider(deep_dataset):
    """A surface provider over the synthetic deep dataset at a fixed day (deterministic)."""
    day = "2024-09-01"
    hedge = BorosFeed().hedge_available(["susde", "ezeth"])
    surface, risks = backtest_rates.build_deep_surface(day, deep_dataset, D0, hedge,
                                                       include_lending=False)
    quotes = list(surface.pt_quotes.values())

    def provider(as_of=None):
        return quotes, risks
    return provider, day


def test_paper_registration_restart_survival(tmp_path, deep_dataset, monkeypatch):
    from spa_core.strategy_lab.rates_desk import paper_rates
    monkeypatch.setattr(hash_chain, "_CHAIN", tmp_path / "audit_chain.jsonl")
    provider, day = _paper_provider(deep_dataset)

    svc = paper_rates.RatesDeskPaperService(surface_provider=provider, state_dir=tmp_path,
                                            record_proof=True)
    st1 = svc.tick(as_of=day)
    assert st1["gap"] is False
    eq1 = st1["sleeve"]["equity_usd"]
    open1 = st1["sleeve"]["open_books"]
    assert open1 >= 1, "the carry sleeve should have opened a book"

    # RESTART: a fresh service must restore the book, not zero it
    svc2 = paper_rates.RatesDeskPaperService(surface_provider=provider, state_dir=tmp_path,
                                             record_proof=False)
    assert len(svc2._sleeve._books) == open1
    assert svc2._last_tick == day

    # IDEMPOTENT: re-ticking the same day does NOT double-accrue
    st2 = svc2.tick(as_of=day)
    assert abs(st2["sleeve"]["equity_usd"] - eq1) < 1e-6, "same-day re-tick double-accrued"


def test_paper_fail_closed_on_empty_surface(tmp_path):
    from spa_core.strategy_lab.rates_desk import paper_rates

    def empty_provider(as_of=None):
        return [], {}
    svc = paper_rates.RatesDeskPaperService(surface_provider=empty_provider, state_dir=tmp_path,
                                            record_proof=False, alert_on_gap=False)
    st = svc.tick(as_of="2026-01-01")
    assert st["gap"] is True  # no usable quote → fail-closed gap, no advance


def test_paper_scan_diagnostic_present_and_transparent(tmp_path, deep_dataset):
    """The 'why N entries' diagnostic must be present in BOTH the status and the series point, and must
    distinguish a genuine entry from an honest-no-edge / thin-surface sit-in-cash (the transparency the
    brief demands — 0 entries must never be an opaque flat line)."""
    from spa_core.strategy_lab.rates_desk import paper_rates
    provider, day = _paper_provider(deep_dataset)
    svc = paper_rates.RatesDeskPaperService(surface_provider=provider, state_dir=tmp_path,
                                            record_proof=False, alert_on_gap=False)
    st = svc.tick(as_of=day)
    diag = st["scan_diag"]
    assert diag is not None
    # the diagnostic carries the honest fields
    for fld in ("markets_scanned", "approvals", "refusals", "refused_by_reason",
                "best_net_edge_bps", "surface_thin", "summary"):
        assert fld in diag, f"scan_diag missing {fld}"
    assert diag["markets_scanned"] >= 1
    assert isinstance(diag["summary"], str) and diag["summary"]
    # the series point persists the same diagnostic (so the forward track is auditable, not opaque)
    import json
    ser = json.loads((tmp_path / "rates_desk_fixed_carry_series.json").read_text())
    assert ser["series"][-1]["scan_diag"]["markets_scanned"] == diag["markets_scanned"]
    # a bare status() refresh recovers the last diagnostic from the persisted series
    st2 = svc.status()
    assert st2["scan_diag"] is not None
    assert st2["scan_diag"]["markets_scanned"] == diag["markets_scanned"]


def test_paper_scan_diagnostic_flags_thin_surface(tmp_path, deep_dataset):
    """A surface with too FEW PT markets (< THIN_SURFACE_MARKETS) flags surface_thin=True — so a
    data/wiring gap (the live feed under-surfacing) is never silently misread as desk discipline."""
    from spa_core.strategy_lab.rates_desk import paper_rates
    # the synthetic deep dataset has only sUSDe + ezETH on this day → 2 PT quotes (< the thin floor).
    provider, day = _paper_provider(deep_dataset)
    svc = paper_rates.RatesDeskPaperService(surface_provider=provider, state_dir=tmp_path,
                                            record_proof=False, alert_on_gap=False)
    st = svc.tick(as_of=day)
    diag = st["scan_diag"]
    assert diag["markets_scanned"] < paper_rates.THIN_SURFACE_MARKETS
    assert diag["surface_thin"] is True


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# 5) surface_io round-trip + scan (the API shape)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_surface_io_roundtrip_and_scan():
    raw = {
        "generated_at": "2026-06-25T00:00:00+00:00", "as_of": "2026-06-25", "mode": "live",
        "hedge_available": {"susde": False},
        "quotes": [{
            "underlying": "susde", "kind": "stable_synth", "venue": "pendle_pt", "protocol": "pendle",
            "market_id": "PT-susde", "tenor_seconds": 86400 * 90, "as_of": "2026-06-25",
            "quoted_rate": "0.12", "tvl_usd": "50000000", "exit_liquidity_usd": "2000000",
            "hedge_available": False, "utilization": "0", "ltv": "0", "cap_headroom_usd": "0",
        }],
        "underlying_risk": {"susde": {
            "underlying": "susde", "as_of": "2026-06-25", "nav_redemption_value": "1",
            "market_price": "1", "peg_distance": "0", "peg_vol_30d": "0",
            "redemption_sla_seconds": 86400, "reserve_fund_ratio": "0.05",
            "funding_neg_frac_90d": "0.1", "oracle_kind": "chainlink",
            "oracle_staleness_seconds": 300, "nested_protocol_count": 1, "top_borrower_share": "0.1",
        }},
    }
    surface, risks = surface_io.surface_from_cached(raw)
    assert "susde" in surface.pt_quotes and "susde" in risks
    out = surface_io.scan_cached_surface(raw)
    assert out["as_of"] == "2026-06-25"
    assert out["n_opportunities"] >= 1
    shapes = {o["shape"] for o in out["opportunities"]}
    assert "fixed_carry" in shapes
