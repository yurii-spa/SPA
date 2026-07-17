"""Regression tests for spa_core/analytics/golive_readiness_report.py.

`GoLiveReadinessReport` is the PUBLISHED go-live readiness surface: it feeds
`/api/v1/golive` (public API), the Telegram morning digest and `/status`, the
inline `api/client` fallback, and `scripts/pre_deploy_check.py`. It answers the
project's single loudest question — "can we go live yet?" — so a silent
arithmetic or fail-open drift here over-reports readiness to the owner and to
the public API. That is the exact honesty failure the module's own comments
forbid ("this published readiness surface must not [overstate]"), which is why
the scoring contract is pinned here bar by bar.

Fully hermetic: every report is constructed with `base_dir=tmp_path`, so all
`data/` reads and the `save()` writes stay inside the temp tree. No production
file is touched — in particular NOT the live go-live track
(`data/equity_curve_daily.json`). Tests only; the module is never modified
(invariant #16).

Deliberately NOT covered: the `overall_status()` "BLOCKED — no backtest gate
pass" branch. It looks up a category named `gate_status`, which the v10.41
six-category refactor no longer produces (the live name is `gates`), so the
branch is unreachable dead code. Pinning either behaviour here would bless a
fail-open defect or pre-empt an owner decision on published go-live semantics,
so it is raised as a `needs-owner` card instead.
"""
from __future__ import annotations

import json

import pytest

from spa_core.analytics.golive_readiness_report import (
    EVIDENCE_TARGET,
    SCHEMA_VERSION,
    CategoryScore,
    GoLiveReadinessReport,
)
from spa_core.paper_trading.track_evidence import PAPER_REAL_START


# ── fixtures / helpers ─────────────────────────────────────────────────────────


def _w(base, rel, data):
    """Write `data` as JSON to `base/rel`, creating parents. Returns the path."""
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _bar(day, **labels):
    """An equity-curve bar dated `day` days after the post-teardown anchor.

    With no honesty labels the bar counts as evidenced (`is_evidenced_bar`
    treats an unlabelled bar as real); `**labels` injects the negative labels
    (`reconstructed`, `evidenced=False`, `source=backfill`, …) that must NOT.
    """
    from datetime import timedelta

    bar = {"date": (PAPER_REAL_START + timedelta(days=day)).isoformat()}
    bar.update(labels)
    return bar


def _iso(day):
    from datetime import timedelta

    return (PAPER_REAL_START + timedelta(days=day)).isoformat()


@pytest.fixture()
def report(tmp_path):
    """A report rooted at an EMPTY tmp repo — every data file is absent."""
    return GoLiveReadinessReport(base_dir=str(tmp_path))


# ══ CategoryScore ══════════════════════════════════════════════════════════════


def test_pct_is_score_over_max():
    assert CategoryScore("gates", 15.0, 20.0, [], []).pct == 75.0


def test_pct_zero_max_returns_zero_not_zerodivision():
    """A zero-max category must read as 0%, never raise — `to_dict`/markdown
    call `pct` unconditionally, so a raise here would kill the whole report."""
    assert CategoryScore("empty", 0.0, 0.0, [], []).pct == 0.0


def test_pct_negative_max_returns_zero():
    assert CategoryScore("bad", 5.0, -10.0, [], []).pct == 0.0


def test_to_dict_shape_and_rounding():
    d = CategoryScore("gates", 6.666, 20.0, ["a"], ["b"], notes="n").to_dict()
    assert d == {
        "name": "gates",
        "score": 6.67,      # round(_, 2)
        "max_score": 20.0,
        "pct": 33.3,        # round(_, 1)
        "items_done": ["a"],
        "items_pending": ["b"],
        "notes": "n",
    }


def test_constructor_copies_item_lists():
    """The score must not alias caller lists — a later mutation of the source
    list would otherwise rewrite an already-computed category."""
    done = ["x"]
    cat = CategoryScore("c", 1.0, 2.0, done, [])
    done.append("y")
    assert cat.items_done == ["x"]


def test_constructor_coerces_numeric_types():
    cat = CategoryScore("c", 1, 2, [], [], notes=None)
    assert isinstance(cat.score, float) and isinstance(cat.max_score, float)
    assert cat.notes == "None"


# ══ _read_json — defensive reads ═══════════════════════════════════════════════


def test_read_json_missing_file_returns_empty_dict(report, tmp_path):
    assert report._read_json(tmp_path / "nope.json") == {}


def test_read_json_malformed_returns_empty_dict(report, tmp_path):
    """Every assessor reads through `_read_json`; a truncated JSON file (a
    half-written state file) must degrade to "absent", not explode."""
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert report._read_json(bad) == {}


def test_read_json_valid_returns_payload(report, tmp_path):
    good = _w(tmp_path, "good.json", {"a": 1})
    assert report._read_json(good) == {"a": 1}


# ══ _evidenced_real_days — the honesty core ════════════════════════════════════


def test_evidenced_real_days_intersects_paper_dates_with_curve(report, tmp_path):
    """The honest count is paper-evidence dates ∩ evidenced curve bars."""
    _w(tmp_path, "data/equity_curve_daily.json",
       {"daily": [_bar(0), _bar(1), _bar(2)]})
    # day 2 is on the curve but has no paper evidence; day 9 has paper evidence
    # but no curve bar — neither may count.
    got = report._evidenced_real_days({_iso(0), _iso(1), _iso(9)})
    assert got == 2


def test_evidenced_real_days_empty_paper_dates_uses_curve_count(report, tmp_path):
    _w(tmp_path, "data/equity_curve_daily.json", {"daily": [_bar(0), _bar(1)]})
    assert report._evidenced_real_days(set()) == 2


def test_evidenced_real_days_excludes_unevidenced_bars(report, tmp_path):
    """Backfill / reconstructed / seed / warmup bars are NOT track evidence.

    This is the over-reporting the module was hardened against: the raw day
    count (4) must collapse to the one honest day.
    """
    _w(tmp_path, "data/equity_curve_daily.json", {"daily": [
        _bar(0),
        _bar(1, reconstructed=True),
        _bar(2, evidenced=False),
        _bar(3, is_seed=True),
    ]})
    assert report._evidenced_real_days(set()) == 1


def test_evidenced_real_days_excludes_pre_anchor_bars(report, tmp_path):
    """Bars before PAPER_REAL_START are pre-teardown history, not track days."""
    _w(tmp_path, "data/equity_curve_daily.json", {"daily": [
        _bar(-5), _bar(-1), _bar(0),
    ]})
    assert report._evidenced_real_days(set()) == 1


def test_evidenced_real_days_present_but_empty_curve_falls_back(report, tmp_path):
    """A present-but-EMPTY curve is not a usable evidence source — the count
    falls back to the paper-evidence dates rather than collapsing to 0."""
    _w(tmp_path, "data/equity_curve_daily.json", {"daily": []})
    assert report._evidenced_real_days({_iso(0), _iso(1)}) == 2


def test_evidenced_real_days_no_curve_file_falls_back(report):
    assert report._evidenced_real_days({_iso(0), _iso(1), _iso(2)}) == 3


# ══ assess_gates (max 20) ══════════════════════════════════════════════════════


def _evidence_calc(tmp_path):
    """Create the evidence_auto_calculator.py the assessors probe for."""
    p = tmp_path / "spa_core" / "analytics" / "evidence_auto_calculator.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# calculator\n", encoding="utf-8")
    return p


def test_gates_empty_repo_scores_zero(report):
    cat = report.assess_gates()
    assert (cat.name, cat.score, cat.max_score) == ("gates", 0.0, 20.0)
    assert cat.items_done == []


def test_gates_backtest_pass_awards_6(report, tmp_path):
    _w(tmp_path, "data/backtest/pre_paper_backtest_gate.json", {"status": "PASS"})
    assert report.assess_gates().score == 6.0


def test_gates_backtest_non_pass_awards_nothing(report, tmp_path):
    _w(tmp_path, "data/backtest/pre_paper_backtest_gate.json", {"status": "FAIL"})
    cat = report.assess_gates()
    assert cat.score == 0.0
    assert any("Backtest Gate: FAIL" in i for i in cat.items_pending)


@pytest.mark.parametrize("status", ["READY", "PASS"])
def test_gates_pre_paper_ready_or_pass_awards_2(report, tmp_path, status):
    _w(tmp_path, "data/backtest/paper_ready_gate.json", {"status": status})
    assert report.assess_gates().score == 2.0


def test_gates_paper_started_via_paper_evidence_awards_3(report, tmp_path):
    _w(tmp_path, "data/paper_evidence.json", {"days": [{"date": _iso(0)}]})
    assert report.assess_gates().score == 3.0


def test_gates_paper_started_via_equity_curve_awards_3(report, tmp_path):
    """`effective_days` is max(paper_days, eq_days) — either source alone is
    enough to evidence that paper trading has started."""
    _w(tmp_path, "data/equity_curve_daily.json", {"daily": [_bar(0)]})
    assert report.assess_gates().score == 3.0


def test_gates_paper_started_via_summary_num_days(report, tmp_path):
    _w(tmp_path, "data/equity_curve_daily.json", {"summary": {"num_days": 4}})
    assert report.assess_gates().score == 3.0


def test_gates_evidence_infra_complete_awards_3(report, tmp_path):
    _evidence_calc(tmp_path)
    _w(tmp_path, "data/paper_evidence_history.json", {"schema_version": "1.0"})
    assert report.assess_gates().score == 3.0


def test_gates_evidence_calc_only_awards_half(report, tmp_path):
    """Calculator present but history never initialised → partial credit."""
    _evidence_calc(tmp_path)
    cat = report.assess_gates()
    assert cat.score == 1.5
    assert any("paper_evidence_history.json not initialized" in i
               for i in cat.items_pending)


def test_gates_kill_switch_untriggered_awards_2(report, tmp_path):
    """Read-only probe of a kill-switch STATE fixture (no kill logic touched)."""
    _w(tmp_path, "data/kill_switch_status.json", {"triggered": False})
    assert report.assess_gates().score == 2.0


def test_gates_kill_switch_triggered_awards_nothing(report, tmp_path):
    _w(tmp_path, "data/kill_switch_status.json", {"triggered": True})
    assert report.assess_gates().score == 0.0


@pytest.mark.parametrize("state", ["LOCKED", "ARMED", "TESTED"])
def test_gates_kill_switch_state_via_gate_status_awards_2(report, tmp_path, state):
    _w(tmp_path, "data/gate_status.json", {"kill_switch_status": state})
    assert report.assess_gates().score == 2.0  # no schema_version → no +2


def test_gates_pre_launch_validation_at_80pct_awards_2(report, tmp_path):
    """80% is inclusive — the documented threshold is ">= 80%"."""
    _w(tmp_path, "data/pre_launch_validation.json",
       {"pass_count": 8, "total_count": 10})
    assert report.assess_gates().score == 2.0


def test_gates_pre_launch_validation_below_80pct_awards_nothing(report, tmp_path):
    _w(tmp_path, "data/pre_launch_validation.json",
       {"pass_count": 7, "total_count": 10})
    cat = report.assess_gates()
    assert cat.score == 0.0
    assert any("need ≥80%" in i for i in cat.items_pending)


def test_gates_validation_missing_falls_back_to_golive_checks(report, tmp_path):
    """No pre_launch_validation.json → fall back to golive_status checks."""
    _w(tmp_path, "data/golive_status.json",
       {"checks": {"a": True, "b": True, "c": True, "d": True, "e": False}})
    assert report.assess_gates().score == 2.0  # 4/5 = 80%


def test_gates_golive_fallback_below_80pct_awards_nothing(report, tmp_path):
    _w(tmp_path, "data/golive_status.json",
       {"checks": {"a": True, "b": False, "c": False}})
    assert report.assess_gates().score == 0.0


def test_gates_gate_status_schema_awards_2(report, tmp_path):
    _w(tmp_path, "data/gate_status.json", {"schema_version": "1.0"})
    assert report.assess_gates().score == 2.0


def test_gates_all_signals_green_totals_max_20(report, tmp_path):
    _evidence_calc(tmp_path)
    _w(tmp_path, "data/backtest/pre_paper_backtest_gate.json", {"status": "PASS"})
    _w(tmp_path, "data/backtest/paper_ready_gate.json", {"status": "READY"})
    _w(tmp_path, "data/paper_evidence.json", {"days": [{"date": _iso(0)}]})
    _w(tmp_path, "data/paper_evidence_history.json", {"schema_version": "1.0"})
    _w(tmp_path, "data/kill_switch_status.json", {"triggered": False})
    _w(tmp_path, "data/pre_launch_validation.json",
       {"pass_count": 10, "total_count": 10})
    _w(tmp_path, "data/gate_status.json", {"schema_version": "1.0"})
    cat = report.assess_gates()
    assert cat.score == 20.0 == cat.max_score
    assert cat.items_pending == []


# ══ assess_evidence (max 25) ═══════════════════════════════════════════════════


def test_evidence_empty_repo_scores_zero(report):
    cat = report.assess_evidence()
    assert (cat.name, cat.score, cat.max_score) == ("evidence", 0.0, 25.0)


def test_evidence_infrastructure_awards_5_plus_5(report, tmp_path):
    _evidence_calc(tmp_path)
    _w(tmp_path, "data/paper_evidence_history.json", {"schema_version": "1.0"})
    assert report.assess_evidence().score == 10.0  # no cycles yet


@pytest.mark.parametrize("days,expect", [
    (0, 0.0),    # no tier
    (1, 1.0),    # ≥1
    (3, 3.0),    # ≥1 +≥3
    (5, 5.0),    # ≥1 +≥3 +≥5
    (10, 10.0),  # +≥10
    (15, 15.0),  # +≥15 → cap
    (40, 15.0),  # cap holds
])
def test_evidence_cycle_tiers_are_cumulative_and_capped(report, tmp_path, days, expect):
    """N real days → N cycle pts up to the documented 15-pt cap."""
    _w(tmp_path, "data/equity_curve_daily.json",
       {"daily": [_bar(i) for i in range(days)]})
    assert report.assess_evidence().score == expect


def test_evidence_counts_honest_days_not_raw_paper_evidence(report, tmp_path):
    """The published surface must use the gate's own evidenced-day rule.

    Raw `paper_evidence.days` has 5 entries, but only 2 are evidenced on the
    curve — the score must reflect 2, never 5.
    """
    _w(tmp_path, "data/paper_evidence.json",
       {"days": [{"date": _iso(i)} for i in range(5)]})
    _w(tmp_path, "data/equity_curve_daily.json", {"daily": [
        _bar(0), _bar(1), _bar(2, reconstructed=True), _bar(3, evidenced=False),
    ]})
    cat = report.assess_evidence()
    assert cat.score == 1.0            # 2 real days → only the ≥1 tier
    assert "2 real days" in cat.notes


# ══ assess_infrastructure_v2 (max 20) ══════════════════════════════════════════


def test_infrastructure_v2_empty_scores_zero_of_20(report):
    cat = report.assess_infrastructure_v2()
    assert (cat.name, cat.score, cat.max_score) == ("infrastructure", 0.0, 20.0)


def test_infrastructure_v2_awards_2_per_check(report, tmp_path):
    _w(tmp_path, "data/golive_status.json", {"checks": {
        "autopush_installed": True, "http_server": True, "gap_monitor_ok": False,
    }})
    cat = report.assess_infrastructure_v2()
    assert cat.score == 4.0
    assert any("gap_monitor: no gaps: missing/failed" in i for i in cat.items_pending)


def test_infrastructure_v2_all_ten_checks_total_20(report, tmp_path):
    keys = ["autopush_installed", "http_server", "cycle_runner_exists",
            "multi_strategy_runner", "safe_tx_builder", "promotion_engine",
            "gap_monitor_ok", "adr022_exists", "data_fresh_48h",
            "telegram_alert_today"]
    _w(tmp_path, "data/golive_status.json", {"checks": {k: True for k in keys}})
    cat = report.assess_infrastructure_v2()
    assert cat.score == 20.0 == cat.max_score
    assert cat.items_pending == []


# ══ assess_financial (max 15) ══════════════════════════════════════════════════


def test_financial_empty_scores_zero_of_15(report):
    cat = report.assess_financial()
    assert (cat.name, cat.score, cat.max_score) == ("financial", 0.0, 15.0)


def test_financial_capital_config_awards_3(report, tmp_path):
    _w(tmp_path, "data/capital_config.json",
       {"capital": {"starting_capital_usd": 100_000}})
    assert report.assess_financial().score == 3.0


def test_financial_capital_config_below_100k_awards_nothing(report, tmp_path):
    _w(tmp_path, "data/capital_config.json",
       {"capital": {"starting_capital_usd": 99_999}})
    assert report.assess_financial().score == 0.0


def test_financial_capital_and_is_demo_false_award_2_plus_2(report, tmp_path):
    _w(tmp_path, "data/paper_trading_status.json",
       {"virtual_capital": 100_000, "is_demo": False})
    assert report.assess_financial().score == 4.0


def test_financial_is_demo_true_withholds_its_2(report, tmp_path):
    """Demo capital is not go-live capital — the +2 must be withheld."""
    _w(tmp_path, "data/paper_trading_status.json",
       {"virtual_capital": 100_000, "is_demo": True})
    cat = report.assess_financial()
    assert cat.score == 2.0
    assert any("is_demo=True" in i for i in cat.items_pending)


def test_financial_capital_falls_back_to_positions_file(report, tmp_path):
    """paper_trading_status absent → capital comes from current_positions."""
    _w(tmp_path, "data/current_positions.json",
       {"capital_usd": 100_000, "is_demo": False})
    assert report.assess_financial().score == 4.0


def test_financial_equity_curve_7_days_awards_2(report, tmp_path):
    _w(tmp_path, "data/equity_curve_daily.json",
       {"daily": [_bar(i) for i in range(7)]})
    assert report.assess_financial().score == 2.0


def test_financial_equity_curve_6_days_awards_nothing(report, tmp_path):
    cat = GoLiveReadinessReport(base_dir=str(tmp_path))
    _w(tmp_path, "data/equity_curve_daily.json",
       {"daily": [_bar(i) for i in range(6)]})
    got = cat.assess_financial()
    assert got.score == 0.0
    assert any("6/7 equity curve days" in i for i in got.items_pending)


def test_financial_risk_policy_and_fee_structure_award_2_each(report, tmp_path):
    for rel, size in [("spa_core/risk/policy.py", 200),
                      ("spa_core/analytics/fee_structure.py", 300)]:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("#" * size, encoding="utf-8")
    assert report.assess_financial().score == 4.0


def test_financial_undersized_policy_file_awards_nothing(report, tmp_path):
    """A stub file must not earn the point — size floor is the check."""
    p = tmp_path / "spa_core" / "risk" / "policy.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("#", encoding="utf-8")
    assert report.assess_financial().score == 0.0


# ══ assess_data_sources (max 10) ═══════════════════════════════════════════════


def test_data_sources_empty_scores_zero_of_10(report):
    cat = report.assess_data_sources()
    assert (cat.name, cat.score, cat.max_score) == ("data_sources", 0.0, 10.0)


def test_data_sources_five_clean_awards_count_and_pct(report, tmp_path):
    """5 CLEAN of 5 → +2 (≥5 CLEAN) and +2 (≥50% CLEAN)."""
    _w(tmp_path, "data/backtest/source_pipeline.json",
       {"sources": {f"s{i}": "clean_included" for i in range(5)}})
    cat = report.assess_data_sources()
    assert cat.score == 4.0
    assert "5/5 CLEAN" in cat.notes


def test_data_sources_four_clean_awards_pct_only(report, tmp_path):
    """4 CLEAN of 5 = 80% → the ≥50% point only; the ≥5-CLEAN point is withheld."""
    sources = {f"s{i}": "clean_included" for i in range(4)}
    sources["s4"] = "quarantined"
    _w(tmp_path, "data/backtest/source_pipeline.json", {"sources": sources})
    assert report.assess_data_sources().score == 2.0


def test_data_sources_defillama_and_promotion_engine_award_2_each(report, tmp_path):
    for rel in ["spa_core/adapters/defillama_feed.py",
                "spa_core/analytics/strategy_promoter.py"]:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# stub\n", encoding="utf-8")
    assert report.assess_data_sources().score == 4.0


# ══ assess_documentation_v2 (max 10) ═══════════════════════════════════════════


def test_documentation_v2_normalizes_100_scale_to_10(report, tmp_path):
    """v2 is the old 100-pt assessor rescaled — 4 of 8 docs (40 pts) → 4.0/10."""
    docs = tmp_path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    for name in ["RISK_MANAGEMENT_POLICY.md", "DEPLOYMENT_RUNBOOK.md",
                 "DATA_SOURCES_REGISTRY.md", "API_REFERENCE.md"]:
        (docs / name).write_text("x" * 600, encoding="utf-8")
    cat = report.assess_documentation_v2()
    assert (cat.name, cat.max_score) == ("documentation", 10.0)
    assert cat.score == 4.0  # 40/100 * 10


def test_documentation_undersized_doc_does_not_count(report, tmp_path):
    """A <500-byte placeholder is not a document — no credit."""
    docs = tmp_path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "RISK_MANAGEMENT_POLICY.md").write_text("stub", encoding="utf-8")
    assert report.assess_documentation_v2().score == 0.0


def test_documentation_adr_directory_awards_20_of_100(report, tmp_path):
    """8 required docs × 10 pts + 20 pts for a ≥3-file ADR directory = 100."""
    adr = tmp_path / "docs" / "adr"
    adr.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        (adr / f"ADR-{i}.md").write_text("x" * 600, encoding="utf-8")
    cat = report.assess_documentation()
    assert cat.score == 20.0 and cat.max_score == 100.0


def test_documentation_two_adrs_miss_the_minimum(report, tmp_path):
    adr = tmp_path / "docs" / "adr"
    adr.mkdir(parents=True, exist_ok=True)
    for i in range(2):
        (adr / f"ADR-{i}.md").write_text("x" * 600, encoding="utf-8")
    cat = report.assess_documentation()
    assert cat.score == 0.0
    assert any("need ≥3 ADR files (found 2)" in i for i in cat.items_pending)


# ══ aggregation: _get_categories / total_score ═════════════════════════════════


def test_get_categories_returns_the_six_live_categories(report):
    """The v10.41 six-category system, summing to a 100-pt max."""
    cats = report._get_categories()
    assert [c.name for c in cats] == [
        "gates", "evidence", "infrastructure", "financial",
        "data_sources", "documentation",
    ]
    assert sum(c.max_score for c in cats) == 100.0


def test_get_categories_is_cached(report, monkeypatch):
    """Assessors hit the filesystem — the report must run each one once."""
    calls = []
    real = report.assess_gates
    monkeypatch.setattr(report, "assess_gates",
                        lambda: (calls.append(1), real())[1])
    report._get_categories()
    report._get_categories()
    report.total_score()
    assert len(calls) == 1


def test_total_score_is_points_over_max_as_pct(report):
    report._categories_cache = [
        CategoryScore("gates", 10.0, 20.0, [], []),
        CategoryScore("evidence", 15.0, 30.0, [], []),
    ]
    assert report.total_score() == 50.0


def test_total_score_zero_max_returns_zero(report):
    """Guard: an all-zero-max category set must read 0.0, not raise."""
    report._categories_cache = [CategoryScore("x", 0.0, 0.0, [], [])]
    assert report.total_score() == 0.0


def test_total_score_on_empty_categories_returns_zero(report):
    report._categories_cache = []
    assert report.total_score() == 0.0


# ══ overall_status ═════════════════════════════════════════════════════════════


def test_overall_status_strict_blocked_returns_blocked(report, tmp_path):
    """A hard structural blocker outranks any score."""
    _w(tmp_path, "data/backtest/paper_ready_gate.json",
       {"expanded_universe_verification_status": "STRICT_BLOCKED"})
    report._categories_cache = [CategoryScore("gates", 100.0, 100.0, [], [])]
    assert report.overall_status() == "BLOCKED"


def test_overall_status_ready_at_80(report):
    """80.0 is inclusive — the documented rule is ">= 80"."""
    report._categories_cache = [CategoryScore("gates", 80.0, 100.0, [], [])]
    assert report.overall_status() == "READY"


def test_overall_status_below_80_is_not_ready(report):
    report._categories_cache = [CategoryScore("gates", 79.9, 100.0, [], [])]
    assert report.overall_status() == "NOT_READY"


def test_overall_status_empty_repo_is_not_ready(report):
    """The honest default for a repo with no evidence at all."""
    assert report.overall_status() == "NOT_READY"


# ══ blocking_items ═════════════════════════════════════════════════════════════


def test_blocking_items_collects_pending_across_categories(report):
    report._categories_cache = [
        CategoryScore("gates", 0.0, 20.0, [], ["fix gates"]),
        CategoryScore("evidence", 0.0, 25.0, [], ["fix evidence"]),
    ]
    assert report.blocking_items() == ["fix gates", "fix evidence"]


def test_blocking_items_appends_golive_blockers(report, tmp_path):
    _w(tmp_path, "data/golive_status.json", {"blockers": ["25/30 track days"]})
    report._categories_cache = [CategoryScore("gates", 0.0, 20.0, [], ["a"])]
    assert report.blocking_items() == ["a", "25/30 track days"]


def test_blocking_items_deduplicates_golive_blockers(report, tmp_path):
    """A golive blocker already surfaced by a category must not double-print."""
    _w(tmp_path, "data/golive_status.json", {"blockers": ["dup", "new"]})
    report._categories_cache = [CategoryScore("gates", 0.0, 20.0, [], ["dup"])]
    assert report.blocking_items() == ["dup", "new"]


# ══ estimated_days_to_ready ════════════════════════════════════════════════════


def _hardening_ok(tmp_path):
    """Neutralise the infra-days penalty so track math can be read alone.

    A MISSING paper_ready_gate.json reads `hardening_status` as None, which is
    NOT in the ("PASS", "READY", "") pass-list → a 7-day penalty applies (see
    `test_eta_missing_gate_file_is_fail_closed`). Tests that isolate the track
    arithmetic must clear it explicitly.
    """
    _w(tmp_path, "data/backtest/paper_ready_gate.json", {"hardening_status": "PASS"})


def test_eta_reads_more_needed_from_blockers(report, tmp_path):
    _hardening_ok(tmp_path)
    _w(tmp_path, "data/golive_status.json",
       {"blockers": ["min_track_days_30: 25/30 — 5 more needed"]})
    _w(tmp_path, "data/backtest/owner_paper_acceptance.json", {"accepted": True})
    assert report.estimated_days_to_ready() == 5


def test_eta_missing_gate_file_is_fail_closed(report, tmp_path):
    """An ABSENT paper_ready_gate.json costs the full 7 hardening days.

    `.get("hardening_status")` yields None for a missing file, and None is not
    in the ("PASS", "READY", "") pass-list — so "no gate file" is estimated as
    pessimistically as "hardening failed". That is the honest direction for a
    readiness ETA, and this pins it: widening the pass-list to swallow None (or
    defaulting the `.get` to "") would silently make the published ETA
    optimistic on a repo that never ran the gate.
    """
    _w(tmp_path, "data/golive_status.json", {"consecutive_ready_days": 30})
    _w(tmp_path, "data/backtest/owner_paper_acceptance.json", {"accepted": True})
    assert report.estimated_days_to_ready() == 7


def test_eta_takes_the_largest_more_needed(report, tmp_path):
    _w(tmp_path, "data/golive_status.json",
       {"blockers": ["3 more needed", "9 more needed"]})
    _w(tmp_path, "data/backtest/owner_paper_acceptance.json", {"accepted": True})
    assert report.estimated_days_to_ready() == 9


def test_eta_adds_one_day_for_unsigned_owner_acceptance(report, tmp_path):
    _hardening_ok(tmp_path)
    _w(tmp_path, "data/golive_status.json", {"blockers": ["5 more needed"]})
    assert report.estimated_days_to_ready() == 6  # 5 + 1 owner day


def test_eta_falls_back_to_consecutive_ready_days(report, tmp_path):
    """No parsable blocker → infer the remainder of the 30-day track."""
    _hardening_ok(tmp_path)
    _w(tmp_path, "data/golive_status.json", {"consecutive_ready_days": 28})
    _w(tmp_path, "data/backtest/owner_paper_acceptance.json", {"accepted": True})
    assert report.estimated_days_to_ready() == 2


def test_eta_empty_repo_assumes_full_track_plus_owner(report):
    assert report.estimated_days_to_ready() == 31  # 30 track + 1 owner


def test_eta_hardening_not_ready_costs_7_days(report, tmp_path):
    _w(tmp_path, "data/golive_status.json", {"consecutive_ready_days": 30})
    _w(tmp_path, "data/backtest/paper_ready_gate.json",
       {"hardening_status": "FAIL"})
    _w(tmp_path, "data/backtest/owner_paper_acceptance.json", {"accepted": True})
    assert report.estimated_days_to_ready() == 7


def test_eta_strict_blocked_costs_14_days(report, tmp_path):
    _w(tmp_path, "data/golive_status.json", {"consecutive_ready_days": 30})
    _w(tmp_path, "data/backtest/paper_ready_gate.json",
       {"expanded_universe_verification_status": "STRICT_BLOCKED"})
    _w(tmp_path, "data/backtest/owner_paper_acceptance.json", {"accepted": True})
    assert report.estimated_days_to_ready() == 14


def test_eta_never_returns_zero(report, tmp_path):
    """Floor of 1 — "ready today" still reports a day, never 0."""
    _hardening_ok(tmp_path)
    _w(tmp_path, "data/golive_status.json", {"consecutive_ready_days": 30})
    _w(tmp_path, "data/backtest/owner_paper_acceptance.json", {"accepted": True})
    assert report.estimated_days_to_ready() == 1


# ══ output: to_dict / generate_report / to_markdown / save ══════════════════════


def test_to_dict_shape(report):
    d = report.to_dict()
    assert d["schema_version"] == SCHEMA_VERSION
    assert d["overall_status"] == "NOT_READY"
    assert d["total_score"] == 0.0
    assert [c["name"] for c in d["categories"]] == [
        "gates", "evidence", "infrastructure", "financial",
        "data_sources", "documentation",
    ]
    assert isinstance(d["blocking_items"], list)


def test_generate_report_is_an_alias_of_to_dict(report):
    """Consumers (/api/v1/golive, morning_digest, pre_deploy_check) call
    `generate_report()`; it must stay identical to `to_dict()`."""
    assert report.generate_report() == report.to_dict()


def test_to_markdown_renders_status_score_and_sections(report):
    report._categories_cache = [
        CategoryScore("gates", 18.0, 20.0, ["done thing"], ["pending thing"],
                      notes="18/20 pts"),
    ]
    md = report.to_markdown()
    assert "# Go-Live Readiness Report" in md
    assert "**Overall Status:** `READY`" in md   # 18/20 = 90 ≥ 80
    assert "**Total Score:** 90.0 / 100" in md
    assert "| gates | 18 | 20 | 90% | ✅ |" in md
    assert "- done thing" in md and "- pending thing" in md


@pytest.mark.parametrize("score,emoji", [
    (16.0, "✅"),   # 80% — inclusive
    (8.0, "⚠️"),    # 40% — inclusive
    (7.8, "❌"),    # 39%
])
def test_to_markdown_category_emoji_thresholds(report, score, emoji):
    report._categories_cache = [CategoryScore("gates", score, 20.0, [], [])]
    assert f"| {emoji} |" in report.to_markdown()


def test_to_markdown_no_blockers_says_ready(report):
    report._categories_cache = [CategoryScore("gates", 20.0, 20.0, [], [])]
    assert "_No blocking items — READY for go-live._" in report.to_markdown()


def test_save_writes_json_and_markdown_under_base_dir(report, tmp_path):
    """`save()` must stay inside its own base_dir (here: tmp)."""
    from datetime import date

    path = report.save()
    today = date.today().isoformat()
    json_path = tmp_path / "data" / "reports" / f"golive_readiness_{today}.json"
    md_path = tmp_path / "data" / "reports" / f"golive_readiness_{today}.md"

    assert path == str(json_path)
    assert json_path.exists() and md_path.exists()

    saved = json.loads(json_path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == SCHEMA_VERSION
    assert saved["date"] == today
    assert saved["overall_status"] == "NOT_READY"
    assert [c["name"] for c in saved["categories"]] == [
        "gates", "evidence", "infrastructure", "financial",
        "data_sources", "documentation",
    ]
    assert md_path.read_text(encoding="utf-8").startswith("# Go-Live Readiness Report")


def test_save_leaves_no_tmp_files_behind(report, tmp_path):
    """Atomic write: tmp + os.replace — no `.tmp` residue in reports/."""
    report.save()
    reports = tmp_path / "data" / "reports"
    assert [p.name for p in reports.iterdir() if p.suffix == ".tmp"] == []


def test_evidence_target_is_thirty_points():
    """The paper-gate evidence target the report scores against."""
    assert EVIDENCE_TARGET == 30.0
