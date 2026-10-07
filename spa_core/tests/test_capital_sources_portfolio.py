"""CAPITAL-SOURCES-01 Wave C (ADR-641): portfolio of return sources (PAPER) + Oracle multi-source consumption.

Failure injection (epic §15) for the Oracle side: stale source, gross offered as net, immature source given a
weight, live flag, real-capital claim, source history mismatch, correlation collapse; plus reproducibility
(same inputs ⇒ same bytes; as-of truncation is causal) and the §12 frontier verdict reading only evidence.
"""
# FROZEN-DATE-OK: injected-clock — ANCHOR is the scene anchor; every series date and every `as_of` handed to the
# functions under test is derived from it (`_d(i)`), the functions never read the wall clock.
from __future__ import annotations

import json
import math
from datetime import date, timedelta

import pytest

from spa_core.investment_cio import contract
from spa_core.investment_cio import sources_portfolio as sp

ANCHOR = date(2026, 1, 1)


def _d(i: int) -> str:
    return (ANCHOR + timedelta(days=i)).isoformat()


def _as_of(i: int) -> str:
    return _d(i) + "T12:00:00Z"


def _m(v, unit="fraction", n=None, note=None):
    return contract.measured(v, unit=unit, source="test", as_of=None, n=n, note=note)


def _nm(reason="not measured"):
    return contract.absent(contract.NOT_MEASURED, reason=reason)


def _source(sid, stype, *, days, ann=None, net=None, gross=None, dd=-0.001, status="ALLOCATABLE_PAPER",
            blockers=None, fresh_state="FRESH", capital_mode="PAPER", name=None, start=0):
    cell = lambda x: _m(x) if x is not None else _nm()   # noqa: E731
    return {
        "evidence_start": _m(_d(start), unit="date"),
        "source_id": sid, "source_type": stype, "name": name or sid, "status": status,
        "capital_mode": capital_mode, "oracle_sleeve": sid,
        "evidence_days": _m(days, unit="days") if days is not None else _nm(),
        "net_return": cell(net), "gross_return": cell(gross), "annualized_return": cell(ann),
        "drawdown": cell(dd), "confidence": _m("LOW", unit=None),
        "freshness": _m({"state": fresh_state, "age_hours": 1.0}, unit=None),
        "blockers": list(blockers or []),
    }


def _registry(*sources, real_capital=0, executes=False):
    srcs = [_source("cash", "TREASURY_CASH", days=None)] + list(sources)
    return {"schema": contract.SCHEMA_CAPITAL_SOURCES, "capital_mode": "PAPER", "real_capital_usd": real_capital,
            "executes": executes, "sources": srcs}


def _accrual(n, rate=0.0002, start=0):
    return {_d(start + i): rate * (1 + (i % 7) / 10) for i in range(n)}


CONS = lambda days=106: _source("defi_conservative", "DEFI_YIELD", days=days, ann=0.049)   # noqa: E731


# ── assessment ─────────────────────────────────────────────────────────────────────────────────────────────
def test_mature_net_source_qualifies_with_a_cap_not_a_recommendation():
    a = sp.assess(_registry(CONS()))
    v = a["by_source"]["defi_conservative"]
    assert v["qualifies"] and v["max_paper_weight"] == 0.50
    assert "cap, not a recommendation" in v["statement"]


def test_developing_source_gets_the_developing_cap_and_trading_its_mechanism_cap():
    a = sp.assess(_registry(CONS(45), _source("trading_alpha", "TRADING_ALPHA", days=200, net=0.05, gross=0.06,
                                              status="RESEARCH_ONLY")))
    assert a["by_source"]["defi_conservative"]["max_paper_weight"] == 0.20
    ta = a["by_source"]["trading_alpha"]
    assert ta["qualifies"] and ta["max_paper_weight"] == 0.10
    assert "research-only" in ta["statement"]          # the contract still keeps it out of the main weights


def test_immature_source_does_not_qualify():
    a = sp.assess(_registry(_source("trading_alpha", "TRADING_ALPHA", days=6.7, net=0.0004, gross=0.002)))
    v = a["by_source"]["trading_alpha"]
    assert not v["qualifies"] and v["max_paper_weight"] == 0.0
    assert any("immature" in b for b in v["blockers"])


def test_stale_source_is_excluded():
    a = sp.assess(_registry(_source("defi_conservative", "DEFI_YIELD", days=120, ann=0.05, fresh_state="STALE")))
    v = a["by_source"]["defi_conservative"]
    assert not v["qualifies"] and any("STALE" in b for b in v["blockers"])


def test_gross_offered_as_net_is_refused_both_ways():
    labelled = _source("trading_alpha", "TRADING_ALPHA", days=200, gross=0.06)
    labelled["net_return"] = _m(0.06, unit="fraction, GROSS of costs")
    v = sp.assess(_registry(labelled))["by_source"]["trading_alpha"]
    assert not v["qualifies"] and any("gross" in b for b in v["blockers"])
    above = _source("trading_alpha", "TRADING_ALPHA", days=200, net=0.07, gross=0.06)
    v2 = sp.assess(_registry(above))["by_source"]["trading_alpha"]
    assert not v2["qualifies"] and any("exceeds gross" in b for b in v2["blockers"])


def test_only_gross_measured_never_qualifies():
    only_gross = _source("trading_alpha", "TRADING_ALPHA", days=200, gross=0.06)
    v = sp.assess(_registry(only_gross))["by_source"]["trading_alpha"]
    assert not v["qualifies"] and any("net return not measured" in b for b in v["blockers"])


def test_unknown_costs_block_eligibility():
    s = _source("trading_alpha", "TRADING_ALPHA", days=200, net=0.05, gross=0.06,
                blockers=["cost component spread is UNKNOWN"])
    assert not sp.assess(_registry(s))["by_source"]["trading_alpha"]["qualifies"]


@pytest.mark.parametrize("kw", [{"real_capital": 5000}, {"real_capital": True}, {"executes": True}])
def test_real_capital_or_execution_claim_refuses_everything(kw):
    with pytest.raises(sp.PaperBoundaryRefused):
        sp.assess(_registry(CONS(), **kw))


def test_live_flag_on_any_source_refuses_everything():
    live = CONS()
    live["capital_mode"] = "LIVE"
    with pytest.raises(sp.PaperBoundaryRefused):
        sp.assess(_registry(live))
    flagged = CONS()
    flagged["live_enabled"] = True
    with pytest.raises(sp.PaperBoundaryRefused):
        sp.assess(_registry(flagged))


# ── paper portfolio ────────────────────────────────────────────────────────────────────────────────────────
def test_immature_source_with_nonzero_weight_is_refused_not_clipped():
    reg = _registry(CONS(), _source("trading_alpha", "TRADING_ALPHA", days=6.7, net=0.0004, gross=0.002))
    series = {"defi_conservative": _accrual(106), "trading_alpha": _accrual(6)}
    with pytest.raises(sp.AllocationRefused):
        sp.paper_portfolio(reg, series, {"defi_conservative": 0.5, "trading_alpha": 0.01, "cash": 0.49},
                           as_of=_as_of(120))


def test_weight_above_the_evidence_cap_is_refused():
    with pytest.raises(sp.AllocationRefused):
        sp.paper_portfolio(_registry(CONS()), {"defi_conservative": _accrual(106)},
                           {"defi_conservative": 0.6, "cash": 0.4}, as_of=_as_of(120))


def test_portfolio_is_reproducible_and_causal():
    reg = _registry(CONS())
    series = {"defi_conservative": _accrual(106)}
    w = {"defi_conservative": 0.5, "cash": 0.5}
    a = json.dumps(sp.paper_portfolio(reg, series, w, as_of=_as_of(120)), sort_keys=True)
    b = json.dumps(sp.paper_portfolio(reg, series, w, as_of=_as_of(120)), sort_keys=True)
    assert a == b
    early = sp.paper_portfolio(reg, series, w, as_of=_as_of(39))          # as of day 39: 40 dates known
    assert early["window"]["to"] == _d(39) and early["window"]["observations"] == 40
    later_only = dict(series["defi_conservative"])
    later_only[_d(39)] = 0.5                                              # a shock on day 39 …
    early2 = sp.paper_portfolio(reg, {"defi_conservative": later_only}, w, as_of=_as_of(38))
    assert early2["window"]["to"] == _d(38)                               # … invisible to as_of day 38
    assert early2["metrics"]["net_return"] == sp.paper_portfolio(reg, series, w, as_of=_as_of(38))["metrics"][
        "net_return"]


def test_weights_on_past_dates_are_the_ones_knowable_then_not_todays():
    """Review P1-1: today's 50 % cap (≥90 days) must not be applied from day 1. The weight DECIDED on day i is
    the cap ladder by evidenced days then (day index i ⇒ i+1 evidenced days: 0 below 30, 20 % to 89, 50 %
    from 90) and it earns day i+1's return (one-observation shift)."""
    reg = _registry(CONS())
    series = {"defi_conservative": {_d(i): 0.001 for i in range(106)}}
    p = sp.paper_portfolio(reg, series, {"defi_conservative": 0.5, "cash": 0.5}, as_of=_as_of(120))
    path = {r["from"]: r["weights"]["defi_conservative"] for r in p["weight_path"]}
    # decided on day 29 (30 evidenced days) ⇒ earns from day 30; decided on day 89 (90 days) ⇒ earns from day 90
    assert path == {_d(0): 0.0, _d(1): 0.0, _d(30): 0.2, _d(90): 0.5}   # day 0: nothing decided yet; day 1: ladder 0
    want = (1 + 0.2 * 0.001) ** 60 * (1 + 0.5 * 0.001) ** 16 - 1.0
    assert p["metrics"]["net_return"]["value"] == pytest.approx(want, rel=1e-6)
    lookahead = (1 + 0.5 * 0.001) ** 106 - 1.0
    assert p["metrics"]["net_return"]["value"] < lookahead            # positive control: the old figure is larger
    assert "CAUSAL" in p["reconstruction"]


def test_a_decision_never_earns_its_own_day():
    """The weight decided on day D (at/after D's close) earns D+1, never D — a shock ON the unlock day is not
    captured at the new weight."""
    reg = _registry(CONS())
    base = {_d(i): 0.0 for i in range(106)}
    shock = dict(base)
    shock[_d(29)] = 0.10                                               # the day the 20 % cap is DECIDED
    p = sp.paper_portfolio(reg, {"defi_conservative": shock}, {"defi_conservative": 0.5, "cash": 0.5},
                           as_of=_as_of(120))
    assert p["metrics"]["net_return"]["value"] == pytest.approx(0.0, abs=1e-12)
    shock_next = dict(base)
    shock_next[_d(30)] = 0.10                                          # positive control: the next day IS earned
    p2 = sp.paper_portfolio(reg, {"defi_conservative": shock_next}, {"defi_conservative": 0.5, "cash": 0.5},
                            as_of=_as_of(120))
    assert p2["metrics"]["net_return"]["value"] == pytest.approx(0.2 * 0.10, rel=1e-9)


def test_cap_ladder_counts_evidenced_days_not_calendar_days():
    """Two missing dates must delay the 30-day unlock by two days, exactly like assess() counts evidence."""
    reg = _registry(CONS())
    days = [i for i in range(106) if i not in (5, 6)]
    series = {"defi_conservative": {_d(i): 0.001 for i in days}}
    p = sp.paper_portfolio(reg, series, {"defi_conservative": 0.5, "cash": 0.5}, as_of=_as_of(120))
    first_20 = min(r["from"] for r in p["weight_path"] if r["weights"]["defi_conservative"] == 0.2)
    assert first_20 == _d(32)                                          # 30 evidenced days reached on day 31


def test_oracle_ledger_weights_take_precedence_over_the_ladder():
    reg = _registry(CONS())
    series = {"defi_conservative": {_d(i): 0.001 for i in range(106)}}
    hist = sp.weight_history_from_ledger([{"recommendation": {"date": _d(100), "recommended_weights":
                                                              {"defi_conservative": 0.3, "cash": 0.7}}}])
    p = sp.paper_portfolio(reg, series, {"defi_conservative": 0.5, "cash": 0.5}, as_of=_as_of(120),
                           weight_history=hist)
    rows = [r for r in p["weight_path"] if r["from"] == _d(101)]        # decided on 100 ⇒ earns 101
    assert rows and rows[0]["weights"]["defi_conservative"] == 0.3 and rows[0]["basis"] == ["oracle_ledger"]


def test_annualisation_uses_calendar_span_and_reports_gaps():
    reg = _registry(CONS())
    days = [i for i in range(106) if i not in (20, 40)]                 # two missing dates
    series = {"defi_conservative": {_d(i): 0.001 for i in days}}
    p = sp.paper_portfolio(reg, series, {"defi_conservative": 0.5, "cash": 0.5}, as_of=_as_of(120))
    assert p["window"]["calendar_days"] == 106 and p["window"]["observations"] == 104
    assert p["window"]["missing_dates"] == 2
    nav = p["metrics"]["nav"]["value"]
    assert p["metrics"]["annualized_return"]["value"] == pytest.approx(nav ** (365 / 106) - 1, rel=1e-6)


def test_short_window_gives_no_rates():
    p = sp.paper_portfolio(_registry(CONS()), {"defi_conservative": _accrual(10)},
                           {"defi_conservative": 0.5, "cash": 0.5}, as_of=_as_of(9))
    for k in ("annualized_return", "volatility", "sharpe", "sortino"):
        assert p["metrics"][k]["state"] == contract.NOT_ENOUGH_HISTORY
    assert p["metrics"]["net_return"]["state"] == contract.MEASURED


def test_source_history_mismatch_is_refused():
    """A weighted source whose daily series is missing (history does not match the registry) is refused."""
    with pytest.raises(sp.AllocationRefused):
        sp.paper_portfolio(_registry(CONS()), {"defi_conservative": None}, {"defi_conservative": 0.5, "cash": 0.5},
                           as_of=_as_of(120))
    with pytest.raises(sp.AllocationRefused):       # series exists but nothing on/before as_of
        sp.paper_portfolio(_registry(CONS()), {"defi_conservative": _accrual(10, start=200)},
                           {"defi_conservative": 0.5, "cash": 0.5}, as_of=_as_of(100))


def test_correlation_collapse_gives_zero_diversification_credit():
    a_src = _source("defi_conservative", "DEFI_YIELD", days=120, ann=0.05)
    b_src = _source("defi_balanced", "DEFI_YIELD", days=120, ann=0.05)
    base = {_d(i): 0.01 * math.sin(i) + 0.0005 for i in range(120)}
    series = {"defi_conservative": base, "defi_balanced": dict(base)}           # identical ⇒ ρ = 1
    p = sp.paper_portfolio(_registry(a_src, b_src), series,
                           {"defi_conservative": 0.3, "defi_balanced": 0.3, "cash": 0.4}, as_of=_as_of(130))
    assert p["diversification"]["value"]["credit"] == pytest.approx(0.0, abs=1e-9)
    m = sp.correlation_matrix(series)
    assert m["defi_balanced"]["defi_conservative"]["value"] == pytest.approx(1.0)
    # positive control: anti-correlated sources DO earn credit
    anti = {_d(i): -0.01 * math.sin(i) + 0.0005 for i in range(120)}
    p2 = sp.paper_portfolio(_registry(a_src, b_src), {"defi_conservative": base, "defi_balanced": anti},
                            {"defi_conservative": 0.3, "defi_balanced": 0.3, "cash": 0.4}, as_of=_as_of(130))
    assert p2["diversification"]["value"]["credit"] > 0.5


def test_short_overlap_correlation_is_not_measured_not_zero():
    m = sp.correlation_matrix({"a": _accrual(10), "b": _accrual(10), "c": None})
    assert m["a"]["b"]["state"] == contract.NOT_ENOUGH_HISTORY and m["a"]["b"]["value"] is None
    assert m["a"]["c"]["state"] == contract.NOT_MEASURED


# ── §12 frontier ───────────────────────────────────────────────────────────────────────────────────────────
def test_frontier_answers_no_from_evidence_and_never_reads_hypotheticals():
    reg = _registry(CONS())
    series = {"defi_conservative": _accrual(106)}
    huge = {_d(i): 0.01 for i in range(106)}                                   # a fantastic BACKTEST
    f = sp.frontier(reg, series, as_of=_as_of(120),
                    trading_backtest={"daily_returns": huge,
                                      "long_run": {"mean_oos_cagr": 0.5, "mean_oos_max_drawdown": -0.4}})
    assert f["answer"] == "NO"
    assert all(p["evidence_type"].startswith("REALIZED_PAPER") for p in f["realized_points"])
    assert any(p["annualized_net"] and p["annualized_net"] > 0.10 for p in f["hypothetical_points"])
    assert "not evidence" in f["verdict"] and "drawdown" in f["verdict"]
    assert f["status"].startswith("RESEARCH_TARGET")


def test_frontier_unknown_without_any_evidenced_source():
    reg = _registry(_source("trading_alpha", "TRADING_ALPHA", days=6, net=0.001, gross=0.002))
    f = sp.frontier(reg, {"trading_alpha": _accrual(6)}, as_of=_as_of(10))
    assert f["answer"] == "UNKNOWN" and f["realized_points"] == []


def test_frontier_yes_only_when_evidence_reaches_it_within_caps():
    s1 = _source("defi_conservative", "DEFI_YIELD", days=200, ann=0.20)
    s2 = _source("defi_balanced", "DEFI_YIELD", days=200, ann=0.20)
    series = {k: {_d(i): 0.0006 for i in range(200)} for k in ("defi_conservative", "defi_balanced")}
    f = sp.frontier(_registry(s1, s2), series, as_of=_as_of(210))
    assert f["answer"] == "YES"


# ── Oracle view ────────────────────────────────────────────────────────────────────────────────────────────
def test_view_uses_the_oracle_policy_weights_and_refuses_an_unadmitted_one():
    reg = _registry(CONS(), _source("trading_alpha", "TRADING_ALPHA", days=6.7, net=0.0004, gross=0.002))
    inputs = {"registry": reg, "series": {"defi_conservative": _accrual(106), "trading_alpha": _accrual(6)}}
    v = sp.view(inputs, {}, "INSUFFICIENT_EVIDENCE",
                {"EVIDENCE_ONLY": {"weights": {"defi_conservative": 0.5, "cash": 0.5}}}, as_of=_as_of(110))
    assert v["paper_portfolio"]["weights"] == {"cash": 0.5, "defi_conservative": 0.5}
    assert v["executes"] is False and v["real_capital_usd"] == 0
    bad = sp.view(inputs, {"defi_conservative": 0.45, "trading_alpha": 0.05, "cash": 0.5}, "RECOMMEND", {},
                  as_of=_as_of(110))
    assert bad["paper_portfolio"]["state"] == "REFUSED"


def test_view_refuses_whole_on_real_capital():
    v = sp.view({"registry": _registry(CONS(), real_capital=1), "series": {}}, {}, "NO_RECOMMENDATION", {},
                as_of=_as_of(110))
    assert v["state"] == "REFUSED" and "paper boundary" in v["reason"]


def test_recommend_carries_the_view_and_its_weights_never_change():
    """The view is additive: the ADR-554 policy's recommended weights are identical with or without it."""
    from datetime import datetime, timezone
    from spa_core.investment_cio import policy
    now = datetime(ANCHOR.year, ANCHOR.month, ANCHOR.day, tzinfo=timezone.utc) + timedelta(days=110)
    doc = {"sleeves": {}, "seed_split_weights": {}, "inputs": []}
    base = policy.recommend(doc, None, now)
    with_view = policy.recommend(dict(doc, capital_sources={"registry": _registry(CONS()),
                                                            "series": {"defi_conservative": _accrual(106)}}),
                                 None, now)
    assert base["recommended_weights"] == with_view["recommended_weights"]
    assert "capital_sources_view" in with_view and "capital_sources_view" not in base
    assert with_view["executes"] is False
    refused = policy.recommend(dict(doc, capital_sources={"state": "REFUSED", "reason": "x"}), None, now)
    assert refused["capital_sources_view"]["state"] == "REFUSED"


def test_module_never_imports_execution():
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(sp))
    names = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module] + \
            [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    assert not any("execution" in x for x in names)


def test_diversification_is_undefined_on_accrual_like_series():
    a_src = _source("defi_conservative", "DEFI_YIELD", days=120, ann=0.05)
    b_src = _source("defi_balanced", "DEFI_YIELD", days=120, ann=0.05)
    series = {"defi_conservative": _accrual(120), "defi_balanced": _accrual(120, rate=0.0003)}
    p = sp.paper_portfolio(_registry(a_src, b_src), series,
                           {"defi_conservative": 0.3, "defi_balanced": 0.3, "cash": 0.4}, as_of=_as_of(130))
    assert p["diversification"]["state"] == contract.UNDEFINED


def test_net_check_reads_labels_not_notes_and_checks_the_annualised_fallback():
    gross_with_note = _source("trading_alpha", "TRADING_ALPHA", days=200, gross=0.06)
    gross_with_note["net_return"] = _m(0.06, unit="fraction, gross", note="net of costs (says the note)")
    v = sp.assess(_registry(gross_with_note))["by_source"]["trading_alpha"]
    assert not v["qualifies"] and any("labelled gross" in b for b in v["blockers"])
    fallback = _source("defi_conservative", "DEFI_YIELD", days=120, ann=0.08)
    fallback["annualized_gross_return"] = _m(0.06)
    v2 = sp.assess(_registry(fallback))["by_source"]["defi_conservative"]
    assert not v2["qualifies"] and any("exceeds annualised gross" in b for b in v2["blockers"])
    honest = _source("defi_conservative", "DEFI_YIELD", days=120, ann=0.05)
    honest["annualized_return"] = _m(0.05, unit="fraction per year", note="net of modelled gas and slippage")
    assert sp.assess(_registry(honest))["by_source"]["defi_conservative"]["qualifies"]


def test_hypothetical_points_carry_cap_flags_and_only_in_cap_hits_are_counted():
    reg = _registry(CONS())
    series = {"defi_conservative": _accrual(106)}
    huge = {_d(i): 0.01 for i in range(106)}
    f = sp.frontier(reg, series, as_of=_as_of(120),
                    trading_backtest={"daily_returns": huge,
                                      "long_run": {"mean_oos_cagr": 0.5, "mean_oos_max_drawdown": -0.4}})
    flags = {p["weights"]["trading_alpha"]: p["within_policy_caps"] for p in f["hypothetical_points"]}
    assert flags[0.10] is True and flags[0.2] is False and flags[0.5] is False
    assert all(p["weights"]["defi_conservative"] <= 0.5 + 1e-9 for p in f["hypothetical_points"])
    hits_in_text = int(f["verdict"].split(" hypothetical")[0].split()[-1]) if " hypothetical" in f["verdict"] else 0
    in_cap_hits = sum(1 for p in f["hypothetical_points"] if p["within_policy_caps"] and p["annualized_net"]
                      and p["annualized_net"] >= 0.10)
    assert hits_in_text == in_cap_hits


def test_frontier_stores_only_efficient_points_and_refuses_an_exploding_grid():
    srcs = [_source(f"s{i}", "DEFI_YIELD", days=200, ann=0.05) for i in range(5)]
    series = {f"s{i}": _accrual(200, rate=0.0001 * (i + 1)) for i in range(5)}
    f = sp.frontier(_registry(*srcs), series, as_of=_as_of(210))
    assert f["answer"] == "UNKNOWN" and "grid is not run" in f["verdict"]
    two = sp.frontier(_registry(*srcs[:2]), {k: series[k] for k in ("s0", "s1")}, as_of=_as_of(210))
    assert len(two["realized_points"]) <= two["realized_points_total"]
    assert len(json.dumps(two)) < 60_000


def test_view_size_is_bounded_for_the_ledger():
    reg = _registry(CONS(), _source("trading_alpha", "TRADING_ALPHA", days=6.7, net=0.0004, gross=0.002))
    v = sp.view({"registry": reg, "series": {"defi_conservative": _accrual(106), "trading_alpha": _accrual(6)}},
                {}, "INSUFFICIENT_EVIDENCE", {"EVIDENCE_ONLY": {"weights": {"defi_conservative": 0.5, "cash": 0.5}}},
                as_of=_d(110))
    assert v["schema"] == sp.SCHEMA_VIEW and len(json.dumps(v)) < 120_000


def test_same_evidence_different_clock_same_recommendation_id():
    """Review P1-2: the view's as_of is the recommendation DATE; the hour of the run must not change the id."""
    from datetime import datetime, timezone
    from spa_core.investment_cio import policy
    day = datetime(ANCHOR.year, ANCHOR.month, ANCHOR.day, tzinfo=timezone.utc) + timedelta(days=110)
    doc = {"sleeves": {}, "seed_split_weights": {}, "inputs": [],
           "capital_sources": {"registry": _registry(CONS()), "series": {"defi_conservative": _accrual(106)}}}
    r1 = policy.recommend(doc, None, day.replace(hour=6))
    r2 = policy.recommend(doc, None, day.replace(hour=18, minute=37))
    assert r1["recommendation_id"] == r2["recommendation_id"]
    assert r1["capital_sources_view"]["as_of"] == day.strftime("%Y-%m-%d")


def test_weight_history_reads_the_oracle_ledger_basis_compactly_and_within_the_window():
    entries = [{"recommendation": {"date": _d(i), "recommended_weights": {"a": 0.4, "cash": 0.6}}} for i in range(3)]
    entries.append({"recommendation": {"date": _d(3), "recommended_weights": {},
                                       "alternatives_considered": {"EVIDENCE_ONLY": {"weights": {"a": 0.2,
                                                                                                 "cash": 0.8}}}}})
    h = sp.weight_history_from_ledger(entries)
    assert h["coverage"] == [_d(0), _d(3)]
    assert h["changes"] == [{"date": _d(0), "weights": {"a": 0.4, "cash": 0.6}},
                            {"date": _d(3), "weights": {"a": 0.2, "cash": 0.8}}]   # 4 days, 2 rows (changes only)
    assert sp.weight_history_from_ledger(entries, since=_d(2))["coverage"] == [_d(2), _d(3)]
    look = sp._history_lookup(h)
    assert look(_d(2)) == {"a": 0.4, "cash": 0.6} and look(_d(9)) is None   # outside coverage ⇒ ladder
    many = [{"recommendation": {"date": _d(i), "recommended_weights": {"a": 0.5, "cash": 0.5}}} for i in range(400)]
    assert len(json.dumps(sp.weight_history_from_ledger(many))) < 500        # bounded: one row, not 400
