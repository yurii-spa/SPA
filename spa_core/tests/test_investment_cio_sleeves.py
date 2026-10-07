"""Tests for spa_core.investment_cio.sleeves / exposure / correlation (ADR-554 WP-S01).

Every scene is a disposable ``tmp_path`` built by hand to the real shapes of
``defi_engine/status.json``, the per-book paper-trading files, the evidenced equity curve,
the kill-switch / de-risk status and the research ledgers (inspected directly against the
live ``~/Documents/SPA_Claude/data`` tree while writing this module). ``now`` is always
passed into ``build_sleeves`` explicitly — the function has no clock of its own.
"""
# FROZEN-DATE-OK: injected-clock — now passed into build_sleeves(now=)/correlation.build(now=)
from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.investment_cio import contract, correlation, exposure, sleeves

NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=timezone.utc)

_PKG_DIR = Path(sleeves.__file__).resolve().parent

CELL_FIELDS = (
    "capital_basis", "current_equity", "observation_window", "valid_periods", "maturity",
    "expected_return", "realized_return", "volatility", "max_drawdown",
    "liquidity", "time_to_exit", "cash_share", "gross_exposure_over_nav", "leverage",
    "nearest_enforced_stop", "loss_budget", "stress_loss", "worst_case_loss",
    "mtm_coverage", "data_freshness", "evidence_state", "confidence", "capacity",
)
PLAIN_FIELDS = (
    "sleeve_id", "name", "mechanism", "mechanism_class", "mode", "allocatable", "live_admission",
    "experiment_id", "experiment_start", "versions_closed",
    "risk", "composition", "factors", "correlation_features", "gates", "warnings", "unknowns",
)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _mechanic_exposure(buckets: dict) -> dict:
    return {"by_mechanic": buckets, "findings": [], "measured": True,
            "parameter_status": "test", "share_basis": "NAV (measured cash included)"}


def _book_entry(*, nav_usd, cash_usd, cash_reason, mechanic_exposure, spot_net, realized_net_value,
                realized_net_days, nearest_stop, budget_pct, share_exitable_24h, share_exitable_reason,
                exit_latency_h, share_basis, evidence_level="L3 · paper track", stops=None,
                cost_drag_pct=None, cost_drag_window_days=None, share_illiquid=0.1) -> dict:
    return {
        "measured": True, "reason": None, "engine": "test",
        "gate": {"under_riskpolicy": True, "stops": stops if stops is not None else []},
        "nav_usd": nav_usd, "cash_usd": cash_usd, "cash_reason": cash_reason,
        "notional_minus_nav_usd": None, "n_positions": 1, "series_basis": "test", "pre_fix_rows": 0,
        "apy": {
            "book_spot_apy_net": ({"value": spot_net} if spot_net is not None
                                   else {"value": None, "unmeasured_reason": "test: no observed APY"}),
            "book_cost_drag_30d": ({"value": cost_drag_pct, "window_days": cost_drag_window_days, "cost_usd": None}
                                    if cost_drag_pct is not None else None),
            "track_realized_apy_net": {"value": realized_net_value, "days": realized_net_days,
                                       "first_date": "2026-06-22", "last_date": "2026-10-03"},
        },
        "mechanic_exposure": mechanic_exposure,
        "exit": {"measured": True, "enforced": False, "illiquid_positions": [], "illiquid_threshold_hours": 72.0,
                  "max_illiquid_share": 0.25, "max_share_of_pool_tvl": 0.001,
                  "nav_weighted_exit_latency_hours": exit_latency_h, "note": "test",
                  "policy_ok": True, "share_basis": share_basis,
                  "share_exitable_24h": share_exitable_24h, "share_exitable_24h_reason": share_exitable_reason,
                  "share_illiquid": share_illiquid},
        "loss_budget": {"bars": realized_net_days, "bound_by_enforced_stop": False, "bound_reason": None,
                         "budget_pct": budget_pct, "budget_source": "test",
                         "consumed_share_of_budget": 0.0, "current_drawdown_pct": 0.0, "enforced": False,
                         "nearest_enforced_stop_pct": nearest_stop, "note": "test", "series_basis": "test",
                         "status": "ok", "unbound_gap_pct": None, "worst_drawdown_pct": 0.0},
        "evidence_level": evidence_level,
    }


def _pkg_entry(*, package, valid_periods, stale_after_h, last_run_iso, mechanic, mode_state, mode_live,
              experiment_id, experiment_start_date, tiers_held) -> dict:
    return {
        "package": package, "mechanic": mechanic, "engine": "test",
        "experiment_id": experiment_id, "experiment_start_date": experiment_start_date,
        "mode": {"state": mode_state, "live": mode_live, "live_reason_en": "test"},
        "data": {"state": "HEALTHY", "reason": None},
        "work": {"state": "RUNNING", "reason": None, "age_h": 0.0},
        "history": {"first_period": "2026-06-22", "last_period": "2026-10-03",
                     "valid_periods": valid_periods, "reportable_after": 30,
                     "observed_drawdown_pct": 0.0, "state": "REPORTABLE" if valid_periods >= 30 else "ACCUMULATING"},
        "freshness": {"stale_after_h": stale_after_h, "last_successful_run_at": last_run_iso},
        "composition": {"state": "MEASURED", "tiers_held": tiers_held, "unresolved": {}},
    }


def _write_defi_engine_status(data_dir: Path, *, generated_at: datetime, conservative=None, balanced=None,
                              aggressive=None, findings=None) -> None:
    books = {}
    packages = {}
    for pkg_key, book in (("conservative", conservative), ("balanced", balanced), ("aggressive", aggressive)):
        if book is None:
            continue
        books[pkg_key] = book["book"]
        packages[pkg_key] = book["pkg"]
    doc = {
        "schema": "defi-engine-status/1", "generated_at": _iso(generated_at), "run_id": "test",
        "code_version": "test", "execution_mode": "paper", "books": books, "packages": packages,
        "findings": findings or [], "tier_authority": {}, "pool_snapshot": {}, "pool_apy": {},
    }
    (data_dir / "defi_engine").mkdir(parents=True, exist_ok=True)
    (data_dir / "defi_engine" / "status.json").write_text(json.dumps(doc))


def _write_hy_paper_trading(data_dir: Path, *, last_cycle_at: datetime, mtm_rows, stop_breach=False,
                            cash_reason="sleeve state carries no cash field") -> None:
    rows = []
    for i, (date, equity, mtm) in enumerate(mtm_rows):
        rows.append({"date": date, "equity": equity, "peak_equity": equity, "drawdown_pct": 0.0,
                     "apy_pct": 5.0, "mtm_coverage_pct": mtm, "economics_model": "sleeve-econ-v2"})
    doc = {
        "sleeve": "balanced", "engine": "hy_cycle", "daily_history": rows,
        "last_cycle_at": _iso(last_cycle_at),
        "experiments": [{"experiment_id": "balanced-v1@2026-10-02", "status": "closed", "closed_at": "2026-10-02T00:00:00Z"}],
        "stop_reference": {"drawdown_pct": -0.5 if stop_breach else -0.001, "threshold_pct": -0.08},
    }
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "hy_paper_trading.json").write_text(json.dumps(doc))


def _write_lp_paper_trading(data_dir: Path, *, last_cycle_at: datetime, mtm_rows, leverage=3.3333,
                            debt_value=116716.62, loop_equity=50053.62, loop_stress=None,
                            stop_breach=False) -> None:
    rows = []
    for date, equity, mtm in mtm_rows:
        rows.append({"date": date, "equity": equity, "peak_equity": equity, "il_drawdown_pct": 0.0,
                     "apy_pct": 5.0, "mtm_coverage_pct": mtm, "economics_model": "sleeve-econ-v2"})
    doc = {
        "sleeve": "aggressive", "engine": "lp_cycle", "daily_history": rows,
        "last_cycle_at": _iso(last_cycle_at),
        "experiments": [{"experiment_id": "aggressive-v1@2026-10-02", "status": "closed", "closed_at": "2026-10-02T00:00:00Z"}],
        "loop": {
            "status": "open",
            "entry": {"economics": {"leverage": leverage}},
            "last_valuation": {"debt_value": debt_value, "equity": loop_equity},
        },
        "loop_stress": loop_stress if loop_stress is not None else [
            {"scenario": "usde_depeg_10", "equity_change_pct": -33.309, "liquidatable": False},
            {"scenario": "usde_depeg_5", "equity_change_pct": -16.655, "liquidatable": False},
        ],
        "stop_reference": {"drawdown_pct": -0.5 if stop_breach else -0.001, "threshold_pct": -0.25},
    }
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "lp_paper_trading.json").write_text(json.dumps(doc))


def _varied_pct(i: int, scale: float = 0.03) -> float:
    """Deterministic but non-repetitive daily return, in percent — at least a dozen distinct
    values over any run of ~15+ days, so correlation's distinct-returns gate can pass."""
    return round(((i * 7) % 13 - 6) * scale, 5)


def _write_equity_curve(data_dir: Path, *, generated_at: datetime, n_days=102, start_equity=100000.0) -> None:
    rows = []
    equity = start_equity
    for i in range(n_days):
        date = (datetime(2026, 6, 22) + timedelta(days=i)).strftime("%Y-%m-%d")
        ret = _varied_pct(i)
        equity = equity * (1 + ret / 100.0)
        rows.append({"date": date, "equity": round(equity, 2), "daily_return_pct": ret,
                     "evidenced": True, "source": "cycle"})
    doc = {"generated_at": _iso(generated_at), "source": "test", "execution_mode": "paper", "is_demo": False,
           "summary": {"real_days": n_days, "real_max_drawdown_pct": -0.0393, "num_days": n_days},
           "daily": rows}
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "equity_curve_daily.json").write_text(json.dumps(doc))


def _write_kill_switch_and_derisk(data_dir: Path, *, generated_at: datetime, triggered=False, active=False,
                                  kill_state="CLEAR", triggered_value=None) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    tv = triggered if triggered_value is None else triggered_value
    (data_dir / "kill_switch_status.json").write_text(json.dumps(
        {"generated_at": _iso(generated_at), "triggered": tv, "state": kill_state, "reason": "test",
         "triggers": [], "allocation": {}}))
    (data_dir / "derisk_status.json").write_text(json.dumps(
        {"generated_at": _iso(generated_at), "active": active, "tier": "NONE", "reason": "test", "policy": "none"}))


def _write_trading_research(data_dir: Path, *, generated_at: datetime) -> None:
    (data_dir / "trading_research").mkdir(parents=True, exist_ok=True)
    doc = {"schema": "trading-research-status/1", "generated_at_ms": int(generated_at.timestamp() * 1000),
           "ok": True, "mode": "PAPER_RESEARCH_ONLY", "live_capital_usd": 0, "candidates": 10,
           "backtest_qualified": 3, "forward_paper": 2, "evidence_verified": True,
           "shortlist": [{"id": "donchian@v1:BTC:4h:spot_long:x", "forward_bars": 10, "forward_net": 0.01,
                           "oos_max_drawdown": -0.2, "oos_sharpe": 1.0, "score": 0.8}]}
    (data_dir / "trading_research" / "status.json").write_text(json.dumps(doc))


def _write_research_strands(data_dir: Path, *, n_days=60) -> None:
    (data_dir / "strategy_lab_paper").mkdir(parents=True, exist_ok=True)
    (data_dir / "aggressive_lab" / "susde_dn").mkdir(parents=True, exist_ok=True)
    (data_dir / "rates_desk").mkdir(parents=True, exist_ok=True)

    series = []
    equity = 100000.0
    for i in range(n_days):
        date = (datetime(2026, 6, 22) + timedelta(days=i))
        equity *= 1 + _varied_pct(i, scale=0.0004)
        series.append({"date": date.strftime("%Y-%m-%d"), "ts": date.isoformat() + "Z",
                       "equity_usd": round(equity, 2), "net_apy_pct": 0.1})
    (data_dir / "strategy_lab_paper" / "variant_n_series.json").write_text(json.dumps(
        {"id": "variant_n", "series": series, "generated_at": series[-1]["ts"]}))

    lines = []
    equity = 100000.0
    for i in range(n_days):
        date = (datetime(2026, 6, 22) + timedelta(days=i)).strftime("%Y-%m-%d")
        equity *= 1 + _varied_pct(i, scale=0.0005)
        lines.append(json.dumps({"as_of": date, "date": date, "equity_usd": round(equity, 2),
                                 "mtm_today_pct": 0.02, "net_apy_pct": 0.3}))
    (data_dir / "aggressive_lab" / "susde_dn" / "realized_series.jsonl").write_text("\n".join(lines))

    lines = []
    equity = 100000.0
    for i in range(n_days):
        date = (datetime(2026, 6, 22) + timedelta(days=i)).strftime("%Y-%m-%d")
        equity *= 1 + _varied_pct(i, scale=0.0003)
        lines.append(json.dumps({"date": date, "close_equity": round(equity, 2), "apy_today": 4.0}))
    (data_dir / "rates_desk" / "equity_track.jsonl").write_text("\n".join(lines))


def _write_regime(data_dir: Path, *, generated_at: datetime) -> None:
    (data_dir / "investment_os").mkdir(parents=True, exist_ok=True)
    (data_dir / "swarm").mkdir(parents=True, exist_ok=True)
    (data_dir / "investment_os" / "chief_investment.json").write_text(json.dumps(
        {"generated_at": _iso(generated_at), "house_view": {"overall_posture": "GREEN"}}))
    (data_dir / "swarm" / "funding_regime.json").write_text(json.dumps(
        {"as_of_utc": _iso(generated_at), "regime": "GREEN"}))
    (data_dir / "market_regime.json").write_text(json.dumps(
        {"detected_at": _iso(generated_at), "regime": "VOLATILE", "recommendation": "diversify"}))


def _full_scene(tmp_path: Path, *, now: datetime = NOW, defi_generated_at=None, hy_last_cycle=None,
                lp_last_cycle=None, cons_valid_periods=102, bal_valid_periods=2, agg_valid_periods=2,
                shared_protocol="aave_v3", skip_defi_engine=False) -> Path:
    data_dir = tmp_path / "data"
    defi_generated_at = defi_generated_at or now
    hy_last_cycle = hy_last_cycle or now
    lp_last_cycle = lp_last_cycle or now

    conservative = {
        "book": _book_entry(nav_usd=101502.46, cash_usd=5000.0, cash_reason=None,
                            mechanic_exposure=_mechanic_exposure(
                                {"supply": {"protocols": [shared_protocol], "share": 0.9, "usd": 90000.0}}),
                            spot_net=3.34, realized_net_value=4.91, realized_net_days=cons_valid_periods,
                            nearest_stop=5.0, budget_pct=3.0, share_exitable_24h=0.78,
                            share_exitable_reason=None, exit_latency_h=66.2,
                            share_basis="NAV (measured cash included)",
                            # two-tier kill-switch stops (ADR-034/048): SOFT_DERISK halts new money but
                            # does NOT liquidate — only HARD_KILL does (ADR-554 finding 1).
                            stops=[{"name": "SOFT_DERISK", "drawdown_pct": 5.0,
                                    "effect": "halt new / no increase"},
                                   {"name": "HARD_KILL", "drawdown_pct": 10.0,
                                    "effect": "full kill to all-cash"}],
                            cost_drag_pct=0.7852, cost_drag_window_days=23),
        "pkg": _pkg_entry(package="conservative", valid_periods=cons_valid_periods, stale_after_h=26.0,
                          last_run_iso=_iso(defi_generated_at), mechanic="unlevered stablecoin supply",
                          mode_state="PAPER_ONLY", mode_live="NOT_APPROVED",
                          experiment_id="conservative-lending-v1@2026-06-22", experiment_start_date="2026-06-22",
                          tiers_held={"T1": [shared_protocol]}),
    }
    balanced = {
        "book": _book_entry(nav_usd=99461.47, cash_usd=None, cash_reason="sleeve state carries no cash field",
                            mechanic_exposure=_mechanic_exposure(
                                {"supply": {"protocols": [shared_protocol], "share": 0.37, "usd": 37000.0},
                                 "other": {"protocols": ["morpho_steakhouse"], "share": 0.1, "usd": 10000.0}}),
                            spot_net=None, realized_net_value=-17.87, realized_net_days=bal_valid_periods,
                            nearest_stop=8.0, budget_pct=10.0, share_exitable_24h=None,
                            share_exitable_reason="sleeve state carries no cash field", exit_latency_h=100.5,
                            share_basis="deployed notional (book state carries no cash)",
                            stops=[{"name": "book_kill_switch", "drawdown_pct": 8.0, "effect": "book stops"}],
                            cost_drag_pct=24.9093, cost_drag_window_days=1),
        "pkg": _pkg_entry(package="balanced", valid_periods=bal_valid_periods, stale_after_h=2.5,
                          last_run_iso=_iso(defi_generated_at), mechanic="fixed-rate PT",
                          mode_state="PAPER_ONLY", mode_live="REFUSED",
                          experiment_id="balanced-fixed-carry-v1@2026-10-02", experiment_start_date="2026-10-02",
                          tiers_held={"T2": [shared_protocol, "morpho_steakhouse"]}),
    }
    aggressive = {
        "book": _book_entry(nav_usd=100133.68, cash_usd=None, cash_reason="sleeve state carries no cash field",
                            mechanic_exposure=_mechanic_exposure(
                                {"loop": {"protocols": ["morpho_susde_pyusd_loop"], "share": 0.5, "usd": 50053.62},
                                 "supply": {"protocols": [shared_protocol], "share": 0.25, "usd": 25000.0}}),
                            spot_net=None, realized_net_value=12.27, realized_net_days=agg_valid_periods,
                            nearest_stop=25.0, budget_pct=25.0, share_exitable_24h=None,
                            share_exitable_reason="sleeve state carries no cash field", exit_latency_h=96.0,
                            share_basis="deployed notional (book state carries no cash)",
                            stops=[{"name": "book_kill_switch", "drawdown_pct": 25.0, "effect": "book stops"}],
                            cost_drag_pct=0.0, cost_drag_window_days=1),
        "pkg": _pkg_entry(package="aggressive", valid_periods=agg_valid_periods, stale_after_h=2.5,
                          last_run_iso=_iso(defi_generated_at), mechanic="SIMULATED recursive lending",
                          mode_state="PAPER_ONLY", mode_live="REFUSED",
                          experiment_id="aggressive-susde-loop-v1@2026-10-02", experiment_start_date="2026-10-02",
                          tiers_held={"T2": [shared_protocol]}),
    }
    if not skip_defi_engine:
        _write_defi_engine_status(data_dir, generated_at=defi_generated_at, conservative=conservative,
                                  balanced=balanced, aggressive=aggressive,
                                  findings=[{"book": "aggressive", "kind": "mechanic_cap", "mechanic": "loop",
                                             "share": 0.5, "advisory_cap": 0.1}])
    _write_hy_paper_trading(data_dir, last_cycle_at=hy_last_cycle,
                            mtm_rows=[("2026-10-02", 99555.06, 0.0), ("2026-10-03", 99461.47, 0.0)])
    _write_lp_paper_trading(data_dir, last_cycle_at=lp_last_cycle,
                            mtm_rows=[("2026-10-02", 100260.76, 0.0), ("2026-10-03", 100133.68, 0.0)])
    _write_equity_curve(data_dir, generated_at=defi_generated_at, n_days=cons_valid_periods)
    _write_kill_switch_and_derisk(data_dir, generated_at=defi_generated_at)
    _write_trading_research(data_dir, generated_at=defi_generated_at)
    _write_research_strands(data_dir, n_days=60)
    _write_regime(data_dir, generated_at=defi_generated_at)
    return data_dir


# ── T1: every sleeve carries every contract field, cells are always dicts ──────────────────────

def test_every_sleeve_has_all_fields(tmp_path):
    data_dir = _full_scene(tmp_path)
    out = sleeves.build_sleeves(data_dir, NOW)
    assert out["schema"] == contract.SCHEMA_SLEEVES
    assert set(out["sleeves"]) == set(contract.SLEEVES)
    for sid, sleeve in out["sleeves"].items():
        missing = [f for f in contract.SLEEVE_FIELDS if f not in sleeve]
        assert not missing, f"{sid} missing {missing}"
        for f in CELL_FIELDS:
            cell = sleeve[f]
            assert isinstance(cell, dict) and "state" in cell, f"{sid}.{f} is not a cell: {cell!r}"
            assert cell["state"] in contract.CELL_STATES
            if cell["state"] == contract.DEFINITIONAL:
                # true by definition, not observed (CAPITAL-SOURCES-01 review): value kept for display, the
                # definition named, and value_of() refuses it as a measurement
                assert cell.get("note") and cell["source"] == "definitional"
                assert contract.value_of(cell) is None
            elif cell["state"] != contract.MEASURED:
                assert cell["value"] is None
                assert cell.get("reason")
        assert isinstance(sleeve["regime_fit"], dict) and sleeve["regime_fit"]
        for name, cell in sleeve["regime_fit"].items():
            assert isinstance(cell, dict) and "state" in cell, f"{sid}.regime_fit.{name}"
        for f in PLAIN_FIELDS:
            assert f in sleeve


# ── T2: missing source file -> NOT_MEASURED, never a bare 0 ────────────────────────────────────

def test_missing_defi_engine_status_gives_not_measured_not_zero(tmp_path):
    data_dir = _full_scene(tmp_path, skip_defi_engine=True)
    out = sleeves.build_sleeves(data_dir, NOW)
    for sid in contract.DEFI_SLEEVES:
        sleeve = out["sleeves"][sid]
        for f in ("current_equity", "capital_basis", "expected_return", "nearest_enforced_stop", "loss_budget"):
            cell = sleeve[f]
            assert cell["state"] == contract.NOT_MEASURED, f"{sid}.{f} => {cell}"
            assert cell["value"] is None
            assert cell["value"] != 0
    manifest = {row["name"]: row for row in out["inputs"]}
    assert manifest["defi_engine_status"]["state"] == contract.NOT_MEASURED
    assert manifest["defi_engine_status"]["digest"] is None


def test_missing_lp_book_gives_not_measured_leverage_and_stress(tmp_path):
    data_dir = _full_scene(tmp_path)
    (data_dir / "lp_paper_trading.json").unlink()
    out = sleeves.build_sleeves(data_dir, NOW)
    agg = out["sleeves"]["defi_aggressive"]
    assert agg["leverage"]["state"] == contract.NOT_MEASURED
    assert agg["stress_loss"]["state"] == contract.NOT_MEASURED
    assert agg["gross_exposure_over_nav"]["state"] == contract.NOT_MEASURED


# ── T3: stale engine -> STALE cells + gate FAIL ─────────────────────────────────────────────────

def test_stale_defi_engine_gives_stale_cells_and_gate_fail(tmp_path):
    stale_generated_at = NOW - timedelta(hours=10)  # hourly cadence threshold is 3h
    data_dir = _full_scene(tmp_path, defi_generated_at=stale_generated_at, hy_last_cycle=NOW, lp_last_cycle=NOW)
    out = sleeves.build_sleeves(data_dir, NOW)
    for sid in contract.DEFI_SLEEVES:
        sleeve = out["sleeves"][sid]
        assert sleeve["current_equity"]["state"] == contract.STALE, sid
        assert sleeve["current_equity"]["value"] is None
        gate_states = {g["gate"]: g["state"] for g in sleeve["gates"]}
        assert gate_states["data_fresh"] == "FAIL", sid
    manifest = {row["name"]: row for row in out["inputs"]}
    assert manifest["defi_engine_status"]["state"] == contract.STALE
    assert manifest["defi_engine_status"]["age_hours"] == pytest.approx(10.0, abs=0.01)


def test_fresh_defi_engine_gives_measured_cells_and_gate_pass(tmp_path):
    data_dir = _full_scene(tmp_path, defi_generated_at=NOW - timedelta(minutes=30))
    out = sleeves.build_sleeves(data_dir, NOW)
    sleeve = out["sleeves"]["defi_conservative"]
    assert sleeve["current_equity"]["state"] == contract.MEASURED
    gate_states = {g["gate"]: g["state"] for g in sleeve["gates"]}
    assert gate_states["data_fresh"] == "PASS"


# ── T4: maturity thresholds 29/30/89/90 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("valid_periods,expected", [
    (29, contract.MATURITY_IMMATURE),
    (30, contract.MATURITY_DEVELOPING),
    (89, contract.MATURITY_DEVELOPING),
    (90, contract.MATURITY_MATURE),
])
def test_maturity_thresholds(tmp_path, valid_periods, expected):
    data_dir = _full_scene(tmp_path, bal_valid_periods=valid_periods)
    out = sleeves.build_sleeves(data_dir, NOW)
    maturity = out["sleeves"]["defi_balanced"]["maturity"]
    assert maturity["state"] == contract.MEASURED
    assert maturity["value"] == expected, f"valid_periods={valid_periods} => {maturity}"


def test_maturity_not_measured_when_valid_periods_absent(tmp_path):
    data_dir = _full_scene(tmp_path)
    out = sleeves.build_sleeves(data_dir, NOW)
    maturity = out["sleeves"]["market_neutral_basis"]["maturity"]
    assert maturity["state"] == contract.NOT_MEASURED
    assert maturity["value"] is None


# ── T5: worst-case loss rules ───────────────────────────────────────────────────────────────────

def test_worst_case_loss_unlevered_lending_uses_only_the_liquidating_stop(tmp_path):
    """ADR-554 finding 1: the nearest stop is SOFT_DERISK at 5% (halts new money, never liquidates).
    The worst-case bound must skip it and use the nearest LIQUIDATING stop (HARD_KILL at 10%)."""
    data_dir = _full_scene(tmp_path)
    out = sleeves.build_sleeves(data_dir, NOW)
    cons = out["sleeves"]["defi_conservative"]
    stop_cell = cons["nearest_enforced_stop"]
    assert stop_cell["state"] == contract.MEASURED
    assert stop_cell["value"] == 10.0  # HARD_KILL, never the SOFT_DERISK 5%
    assert "SOFT_DERISK" in stop_cell["note"]
    cell = cons["worst_case_loss"]
    assert cell["state"] == contract.MEASURED
    assert cell["value"] == 10.0
    assert "liquidating stop" in cell["note"]


def test_nearest_enforced_stop_unknown_when_only_a_soft_stop_is_declared(tmp_path):
    """If the only declared stop is SOFT_DERISK, the loss bound is genuinely unknown — never
    silently falls back to the soft threshold (ADR-554 finding 1, fail-closed edge case)."""
    data_dir = tmp_path / "data"
    conservative = {
        "book": _book_entry(nav_usd=100000.0, cash_usd=5000.0, cash_reason=None,
                            mechanic_exposure=_mechanic_exposure(
                                {"supply": {"protocols": ["aave_v3"], "share": 0.9, "usd": 90000.0}}),
                            spot_net=3.0, realized_net_value=3.0, realized_net_days=60,
                            nearest_stop=5.0, budget_pct=3.0, share_exitable_24h=0.78,
                            share_exitable_reason=None, exit_latency_h=66.2,
                            share_basis="NAV (measured cash included)",
                            stops=[{"name": "SOFT_DERISK", "drawdown_pct": 5.0,
                                    "effect": "halt new / no increase"}]),
        "pkg": _pkg_entry(package="conservative", valid_periods=60, stale_after_h=26.0,
                          last_run_iso=_iso(NOW), mechanic="unlevered stablecoin supply",
                          mode_state="PAPER_ONLY", mode_live="NOT_APPROVED",
                          experiment_id="x@2026-06-22", experiment_start_date="2026-06-22",
                          tiers_held={"T1": ["aave_v3"]}),
    }
    _write_defi_engine_status(data_dir, generated_at=NOW, conservative=conservative)
    _write_kill_switch_and_derisk(data_dir, generated_at=NOW)
    out = sleeves.build_sleeves(data_dir, NOW)
    cons = out["sleeves"]["defi_conservative"]
    assert cons["nearest_enforced_stop"]["state"] == contract.NOT_MEASURED
    assert "soft" in cons["nearest_enforced_stop"]["reason"].lower()
    assert cons["worst_case_loss"]["state"] == contract.NOT_MEASURED


def test_worst_case_loss_fixed_rate_pt_without_stress_is_not_measured(tmp_path):
    data_dir = _full_scene(tmp_path)
    out = sleeves.build_sleeves(data_dir, NOW)
    cell = out["sleeves"]["defi_balanced"]["worst_case_loss"]
    assert cell["state"] == contract.NOT_MEASURED
    assert "limit, not a loss estimate" in cell["reason"]
    stop = out["sleeves"]["defi_balanced"]["nearest_enforced_stop"]
    assert stop["state"] == contract.MEASURED and stop["value"] == 8.0


def test_worst_case_loss_leveraged_loop_uses_worst_stress_scenario(tmp_path):
    data_dir = _full_scene(tmp_path)
    out = sleeves.build_sleeves(data_dir, NOW)
    agg = out["sleeves"]["defi_aggressive"]
    assert agg["stress_loss"]["state"] == contract.MEASURED
    assert agg["stress_loss"]["value"] == pytest.approx(33.309)
    assert "usde_depeg_10" in agg["stress_loss"]["note"]
    worst = agg["worst_case_loss"]
    assert worst["state"] == contract.MEASURED
    assert worst["value"] == pytest.approx(33.309)  # max(stop=25.0, stress=33.309)


# ── T6: cash_share is NOT_MEASURED for balanced/aggressive, measured for conservative ──────────

def test_cash_share_none_for_balanced_and_aggressive(tmp_path):
    data_dir = _full_scene(tmp_path)
    out = sleeves.build_sleeves(data_dir, NOW)
    cons = out["sleeves"]["defi_conservative"]["cash_share"]
    assert cons["state"] == contract.MEASURED
    assert cons["value"] == pytest.approx(5000.0 / 101502.46, abs=1e-5)
    for sid in ("defi_balanced", "defi_aggressive"):
        cell = out["sleeves"][sid]["cash_share"]
        assert cell["state"] == contract.NOT_MEASURED
        assert cell["value"] is None
        assert cell["reason"] == "sleeve state carries no cash field"


def test_cash_sleeve_look_through_cash_unknown_when_any_book_cash_unmeasured(tmp_path):
    data_dir = _full_scene(tmp_path)
    out = sleeves.build_sleeves(data_dir, NOW)
    cash = out["sleeves"]["cash"]
    assert cash["current_equity"]["state"] == contract.NOT_MEASURED
    # CAPITAL-SOURCES-01 review: idle cash's 0 % is DEFINITIONAL, not a measurement (inv. #17)
    assert cash["expected_return"] == contract.definitional(
        0.0, unit="pct_annualized", basis="no accrual exists for idle cash (ADR-554 audit)",
        as_of=cash["expected_return"]["as_of"])
    assert contract.value_of(cash["expected_return"]) is None
    for f in ("realized_return", "volatility", "max_drawdown", "confidence"):
        assert cash[f]["state"] == contract.DEFINITIONAL, f


# ── T7: correlation NOT_ENOUGH_HISTORY / UNDEFINED / measured with n ────────────────────────────

def test_correlation_not_enough_history_for_thin_defi_pairs(tmp_path):
    data_dir = _full_scene(tmp_path)
    out = sleeves.build_sleeves(data_dir, NOW)
    pairs = {tuple(sorted(p["pair"])): p for p in out["correlation"]["official_pairs"]}
    pair = pairs[tuple(sorted(("defi_balanced", "defi_aggressive")))]
    assert pair["correlation"]["state"] == contract.NOT_ENOUGH_HISTORY
    assert pair["correlation"]["n"] <= 2


def test_correlation_undefined_for_constant_cash_series(tmp_path):
    data_dir = _full_scene(tmp_path, cons_valid_periods=60)
    out = sleeves.build_sleeves(data_dir, NOW)
    pairs = {tuple(sorted(p["pair"])): p for p in out["correlation"]["official_pairs"]}
    pair = pairs[tuple(sorted(("defi_conservative", "cash")))]
    assert pair["overlap_days"] >= contract.POLICY["correlation_min_overlap_days"]
    assert pair["correlation"]["state"] == contract.UNDEFINED
    assert "distinct" in pair["correlation"]["reason"]


def test_correlation_measured_with_n_for_long_overlapping_research_series(tmp_path):
    data_dir = _full_scene(tmp_path, cons_valid_periods=60)
    out = sleeves.build_sleeves(data_dir, NOW)
    pairs = {tuple(sorted(p["pair"])): p for p in out["correlation"]["research_pairs"]}
    pair = pairs[tuple(sorted(("defi_conservative", "variant_n")))]
    assert pair["correlation"]["state"] == contract.MEASURED
    assert isinstance(pair["correlation"]["value"], float)
    assert -1.0 <= pair["correlation"]["value"] <= 1.0
    assert pair["correlation"]["n"] >= contract.POLICY["correlation_min_overlap_days"]
    assert pair["correlation"]["unit"] == "accrual_correlation"


def test_correlation_no_series_published_pair_is_not_enough_history(tmp_path):
    data_dir = _full_scene(tmp_path)
    out = sleeves.build_sleeves(data_dir, NOW)
    pairs = {tuple(sorted(p["pair"])): p for p in out["correlation"]["official_pairs"]}
    pair = pairs[tuple(sorted(("trading_research", "market_neutral_basis")))]
    assert pair["correlation"]["state"] == contract.NOT_ENOUGH_HISTORY
    assert pair["overlap_days"] == 0


# ── T8: exposure finds shared protocols ─────────────────────────────────────────────────────────

def test_exposure_finds_protocols_shared_across_sleeves(tmp_path):
    data_dir = _full_scene(tmp_path, shared_protocol="aave_v3")
    out = sleeves.build_sleeves(data_dir, NOW)
    shared = out["exposure"]["shared_protocols"]
    assert "aave_v3" in shared
    assert set(shared["aave_v3"]) == {"defi_conservative", "defi_balanced", "defi_aggressive"}


def test_exposure_without_weights_reports_not_measured_weighted_share(tmp_path):
    data_dir = _full_scene(tmp_path)
    out = sleeves.build_sleeves(data_dir, NOW)
    overlap = {row["protocol"]: row for row in out["exposure"]["protocol_overlap"]}
    for row in overlap.values():
        assert row["weighted_share"]["state"] == contract.NOT_MEASURED


def test_exposure_with_weights_sums_shares(tmp_path):
    data_dir = _full_scene(tmp_path, shared_protocol="aave_v3")
    out = sleeves.build_sleeves(data_dir, NOW)
    sleeve_dicts = out["sleeves"]
    weights = {"defi_conservative": 0.5, "defi_balanced": 0.3, "defi_aggressive": 0.2, "cash": 0.0,
               "trading_research": 0.0, "market_neutral_basis": 0.0}
    weighted = exposure.build(sleeve_dicts, weights=weights)
    row = {r["protocol"]: r for r in weighted["protocol_overlap"]}["aave_v3"]
    assert row["weighted_share"]["state"] == contract.MEASURED
    expected = 0.5 * 0.9 + 0.3 * 0.37 + 0.2 * 0.25
    assert row["weighted_share"]["value"] == pytest.approx(expected, abs=1e-6)
    assert weighted["risk_policy_caps_reference"]["T1"] == 0.40
    assert weighted["risk_policy_caps_reference"]["T2"] == 0.20


# ── review-fix tests (post-implementation review of ADR-554 WP-S01) ────────────────────────────

# finding 2: conservative stop/kill gate must be UNKNOWN on stale/unreadable/non-bool inputs, and
# must PASS-with-warning (not silently PASS) on a CLEAR*-but-not-plain-CLEAR kill state.

def test_stop_gate_unknown_when_kill_switch_stale(tmp_path):
    data_dir = _full_scene(tmp_path)
    _write_kill_switch_and_derisk(data_dir, generated_at=NOW - timedelta(hours=40))  # > 26h daily cadence
    out = sleeves.build_sleeves(data_dir, NOW)
    gate = {g["gate"]: g for g in out["sleeves"]["defi_conservative"]["gates"]}["stop_not_active"]
    assert gate["state"] == "UNKNOWN"


def test_stop_gate_unknown_when_triggered_field_is_not_boolean(tmp_path):
    data_dir = _full_scene(tmp_path)
    _write_kill_switch_and_derisk(data_dir, generated_at=NOW, triggered_value="no")
    out = sleeves.build_sleeves(data_dir, NOW)
    gate = {g["gate"]: g for g in out["sleeves"]["defi_conservative"]["gates"]}["stop_not_active"]
    assert gate["state"] == "UNKNOWN"


def test_stop_gate_passes_with_warning_on_clear_partial(tmp_path):
    data_dir = _full_scene(tmp_path)
    _write_kill_switch_and_derisk(data_dir, generated_at=NOW, kill_state="CLEAR_PARTIAL")
    out = sleeves.build_sleeves(data_dir, NOW)
    cons = out["sleeves"]["defi_conservative"]
    gate = {g["gate"]: g for g in cons["gates"]}["stop_not_active"]
    assert gate["state"] == "PASS"
    assert any("CLEAR_PARTIAL" in w for w in cons["warnings"])


# finding 3: an input with a declared cadence but no readable as_of is NOT_MEASURED, not fresh;
# research strands get a realistic (daily-series) cadence so a dead strand shows up as STALE.

def test_input_no_as_of_with_declared_cadence_is_not_measured(tmp_path):
    data_dir = _full_scene(tmp_path)
    (data_dir / "strategy_lab_paper" / "variant_n_series.json").write_text(
        json.dumps({"id": "variant_n", "series": []}))
    out = sleeves.build_sleeves(data_dir, NOW)
    manifest = {row["name"]: row for row in out["inputs"]}
    row = manifest["variant_n_series"]
    assert row["state"] == contract.NOT_MEASURED
    assert row["age_hours"] is None


def test_research_strand_becomes_stale_when_dead(tmp_path):
    """The default scene's three research strands end 2026-08-20 — 45 days before NOW. Under a
    realistic daily cadence that is a dead strand, not a 400-day-old snapshot still 'fresh'."""
    data_dir = _full_scene(tmp_path)
    out = sleeves.build_sleeves(data_dir, NOW)
    manifest = {row["name"]: row for row in out["inputs"]}
    assert manifest["variant_n_series"]["state"] == contract.STALE


# finding 1: see test_worst_case_loss_unlevered_lending_uses_only_the_liquidating_stop and
# test_nearest_enforced_stop_unknown_when_only_a_soft_stop_is_declared above (T5 section).


# finding 8 (exposure): an absent weight for a holder is 0, not NOT_MEASURED; a genuinely unmeasured
# share / multi-protocol bucket / UNKNOWN-or-T3 tier is named in unchecked_protocols, which rolls
# up into protocol_cap_state.

def test_exposure_absent_weight_for_a_holder_counts_as_zero_not_as_not_measured(tmp_path):
    data_dir = _full_scene(tmp_path, shared_protocol="aave_v3")
    out = sleeves.build_sleeves(data_dir, NOW)
    sleeve_dicts = out["sleeves"]
    weights = {"defi_conservative": 0.5, "defi_balanced": 0.3}  # aggressive's weight is absent
    weighted = exposure.build(sleeve_dicts, weights=weights)
    row = {r["protocol"]: r for r in weighted["protocol_overlap"]}["aave_v3"]
    assert row["weighted_share"]["state"] == contract.MEASURED
    expected = 0.5 * 0.9 + 0.3 * 0.37  # aggressive's absent weight contributes 0, not NOT_MEASURED
    assert row["weighted_share"]["value"] == pytest.approx(expected, abs=1e-6)


def test_exposure_protocol_cap_state_partial_when_a_protocol_tier_is_unknown(tmp_path):
    data_dir = _full_scene(tmp_path, shared_protocol="aave_v3")
    out = sleeves.build_sleeves(data_dir, NOW)
    exp = out["exposure"]
    assert exp["protocol_cap_state"] == "PARTIAL"
    unknown_entries = [u for u in exp["unchecked_protocols"] if u["protocol"] == "morpho_susde_pyusd_loop"]
    assert unknown_entries, exp["unchecked_protocols"]


def test_exposure_unchecked_protocols_from_unmeasured_share_in_multi_protocol_bucket():
    sleeves_in = {
        "defi_balanced": {
            "composition": [
                {"protocol": "aave_v3", "mechanic": "supply", "tier": "T1",
                 "share": contract.measured(0.4, unit="share", source="test", as_of=None),
                 "usd": contract.absent(contract.NOT_MEASURED, reason="x")},
                {"protocol": "morpho_steakhouse", "mechanic": "multi", "tier": "T2",
                 "share": contract.absent(contract.NOT_MEASURED,
                                           reason="bucket 'multi' aggregates 2 protocols; no per-protocol split"),
                 "usd": contract.absent(contract.NOT_MEASURED, reason="same")},
            ],
        },
    }
    out = exposure.build(sleeves_in, weights={"defi_balanced": 1.0})
    assert out["protocol_cap_state"] == "PARTIAL"
    names = {u["protocol"] for u in out["unchecked_protocols"]}
    assert "morpho_steakhouse" in names
    measured_row = {r["protocol"]: r for r in out["protocol_overlap"]}["aave_v3"]
    assert measured_row["weighted_share"]["state"] == contract.MEASURED
    assert measured_row["weighted_share"]["value"] == pytest.approx(0.4)
    unmeasured_row = {r["protocol"]: r for r in out["protocol_overlap"]}["morpho_steakhouse"]
    assert unmeasured_row["weighted_share"]["state"] == contract.NOT_MEASURED


def test_exposure_cap_state_measured_when_nothing_is_unchecked():
    sleeves_in = {
        "defi_conservative": {
            "composition": [
                {"protocol": "aave_v3", "mechanic": "supply", "tier": "T1",
                 "share": contract.measured(1.0, unit="share", source="test", as_of=None),
                 "usd": contract.measured(100.0, unit="usd", source="test", as_of=None)},
            ],
        },
    }
    out = exposure.build(sleeves_in, weights={"defi_conservative": 1.0})
    assert out["protocol_cap_state"] == "MEASURED"
    assert out["unchecked_protocols"] == []


# finding 9a: conservative/balanced leverage/gross_exposure=1.0 is MEASURED only with a positive
# source (engine mechanic_exposure shows no leveraged/loop mechanic); otherwise NOT_MEASURED.

def test_conservative_leverage_measured_one_from_unlevered_mechanic_exposure(tmp_path):
    data_dir = _full_scene(tmp_path)
    out = sleeves.build_sleeves(data_dir, NOW)
    cons = out["sleeves"]["defi_conservative"]
    assert cons["leverage"]["state"] == contract.MEASURED
    assert cons["leverage"]["value"] == 1.0
    assert "mechanic_exposure" in cons["leverage"]["note"]
    assert cons["gross_exposure_over_nav"]["state"] == contract.MEASURED


def test_balanced_leverage_not_measured_when_mechanic_exposure_shows_a_loop_bucket(tmp_path):
    """An anomalous 'balanced' book reporting a loop mechanic must not be assumed unlevered."""
    data_dir = _full_scene(tmp_path)
    doc_path = data_dir / "defi_engine" / "status.json"
    doc = json.loads(doc_path.read_text())
    doc["books"]["balanced"]["mechanic_exposure"]["by_mechanic"]["loop"] = {
        "protocols": ["some_loop"], "share": 0.05, "usd": 5000.0}
    doc_path.write_text(json.dumps(doc))
    out = sleeves.build_sleeves(data_dir, NOW)
    bal = out["sleeves"]["defi_balanced"]
    assert bal["leverage"]["state"] == contract.NOT_MEASURED
    assert bal["gross_exposure_over_nav"]["state"] == contract.NOT_MEASURED


# finding 9b: trading-research leverage/time_to_exit must not be inferred from an id tag; without
# a real per-candidate field, both stay NOT_MEASURED.

def test_trading_research_leverage_and_time_to_exit_not_measured_no_fabricated_source(tmp_path):
    data_dir = _full_scene(tmp_path)
    out = sleeves.build_sleeves(data_dir, NOW)
    tr = out["sleeves"]["trading_research"]
    assert tr["leverage"]["state"] == contract.NOT_MEASURED
    assert tr["time_to_exit"]["state"] == contract.NOT_MEASURED


# finding 9c: DeFi risk-axis evidence is built from the actual values read, never a hardcoded
# qualitative literal; not read => level UNKNOWN, evidence "not measured".

def test_risk_axis_execution_evidence_built_from_real_cost_drag_value(tmp_path):
    data_dir = _full_scene(tmp_path)
    out = sleeves.build_sleeves(data_dir, NOW)
    cons_exec = out["sleeves"]["defi_conservative"]["risk"]["EXECUTION"]
    assert cons_exec["level"] == "LOW"
    assert "0.7852" in cons_exec["evidence"]
    assert "23" in cons_exec["evidence"]


def test_risk_axis_execution_unknown_when_cost_drag_not_published(tmp_path):
    data_dir = _full_scene(tmp_path)
    doc_path = data_dir / "defi_engine" / "status.json"
    doc = json.loads(doc_path.read_text())
    doc["books"]["conservative"]["apy"]["book_cost_drag_30d"] = None
    doc_path.write_text(json.dumps(doc))
    out = sleeves.build_sleeves(data_dir, NOW)
    axis = out["sleeves"]["defi_conservative"]["risk"]["EXECUTION"]
    assert axis["level"] == "UNKNOWN"
    assert axis["evidence"] == "not measured"


def test_risk_axis_aggressive_leverage_and_liquidity_evidence_from_real_values(tmp_path):
    data_dir = _full_scene(tmp_path)
    out = sleeves.build_sleeves(data_dir, NOW)
    agg_risk = out["sleeves"]["defi_aggressive"]["risk"]
    assert agg_risk["LEVERAGE"]["level"] == "HIGH"
    assert "3.3333" in agg_risk["LEVERAGE"]["evidence"]
    assert agg_risk["LIQUIDITY"]["level"] == "MEDIUM"
    assert "0.1" in agg_risk["LIQUIDITY"]["evidence"]  # the fixture's share_illiquid default


def test_risk_axis_aggressive_leverage_unknown_when_loop_book_missing(tmp_path):
    data_dir = _full_scene(tmp_path)
    (data_dir / "lp_paper_trading.json").unlink()
    out = sleeves.build_sleeves(data_dir, NOW)
    agg_risk = out["sleeves"]["defi_aggressive"]["risk"]
    assert agg_risk["LEVERAGE"]["level"] == "UNKNOWN"
    assert agg_risk["LEVERAGE"]["evidence"] == "not measured"


# finding 12: realized_return with a non-numeric 'days' must be NOT_ENOUGH_HISTORY with n=None,
# never MEASURED with n=None.

def test_realized_return_not_enough_history_when_days_is_non_numeric(tmp_path):
    data_dir = _full_scene(tmp_path)
    doc_path = data_dir / "defi_engine" / "status.json"
    doc = json.loads(doc_path.read_text())
    doc["books"]["conservative"]["apy"]["track_realized_apy_net"]["days"] = None
    doc_path.write_text(json.dumps(doc))
    out = sleeves.build_sleeves(data_dir, NOW)
    rr = out["sleeves"]["defi_conservative"]["realized_return"]
    assert rr["state"] == contract.NOT_ENOUGH_HISTORY
    assert rr["n"] is None
    assert "bar count unknown" in rr["reason"]


# finding 17: stop comparison is strict '<' (matching the books' own stop logic), not '<='.

def test_stop_breach_uses_strict_less_than_not_less_equal(tmp_path):
    data_dir = _full_scene(tmp_path)
    doc = json.loads((data_dir / "hy_paper_trading.json").read_text())
    doc["stop_reference"] = {"drawdown_pct": -0.08, "threshold_pct": -0.08}  # exactly AT threshold
    (data_dir / "hy_paper_trading.json").write_text(json.dumps(doc))
    out = sleeves.build_sleeves(data_dir, NOW)
    gate = {g["gate"]: g for g in out["sleeves"]["defi_balanced"]["gates"]}["stop_not_active"]
    assert gate["state"] == "PASS"


# finding 18: trading-research current_equity must not default to a measured 0.0 when
# live_capital_usd is simply absent from the document.

def test_trading_research_current_equity_not_measured_when_live_capital_field_absent(tmp_path):
    data_dir = _full_scene(tmp_path)
    doc_path = data_dir / "trading_research" / "status.json"
    doc = json.loads(doc_path.read_text())
    del doc["live_capital_usd"]
    doc_path.write_text(json.dumps(doc))
    out = sleeves.build_sleeves(data_dir, NOW)
    ce = out["sleeves"]["trading_research"]["current_equity"]
    assert ce["state"] == contract.NOT_MEASURED
    assert ce["value"] is None


def test_trading_research_current_equity_measured_zero_when_explicitly_published(tmp_path):
    """An EXPLICIT 0 is still a measurement (invariant #17: absence != a measured zero, but a
    measured zero is still a measured zero)."""
    data_dir = _full_scene(tmp_path)
    out = sleeves.build_sleeves(data_dir, NOW)
    ce = out["sleeves"]["trading_research"]["current_equity"]
    assert ce["state"] == contract.MEASURED
    assert ce["value"] == 0


# ── re-review fixes (second pass over ADR-554 WP-S01) ───────────────────────────────────────────

# finding 1 residual: without a structured gate.stops list, the legacy nearest_enforced_stop_pct
# field carries no liquidating/soft distinction (it IS the soft number for the real conservative
# book) and must never be used as a stand-in for "the liquidating stop".

def test_nearest_enforced_stop_not_measured_when_gate_stops_missing_legacy_fallback_removed(tmp_path):
    data_dir = tmp_path / "data"
    conservative = {
        "book": _book_entry(nav_usd=100000.0, cash_usd=5000.0, cash_reason=None,
                            mechanic_exposure=_mechanic_exposure(
                                {"supply": {"protocols": ["aave_v3"], "share": 0.9, "usd": 90000.0}}),
                            spot_net=3.0, realized_net_value=3.0, realized_net_days=60,
                            nearest_stop=5.0, budget_pct=3.0, share_exitable_24h=0.78,
                            share_exitable_reason=None, exit_latency_h=66.2,
                            share_basis="NAV (measured cash included)",
                            stops=None),  # no structured gate.stops published at all
        "pkg": _pkg_entry(package="conservative", valid_periods=60, stale_after_h=26.0,
                          last_run_iso=_iso(NOW), mechanic="unlevered stablecoin supply",
                          mode_state="PAPER_ONLY", mode_live="NOT_APPROVED",
                          experiment_id="x@2026-06-22", experiment_start_date="2026-06-22",
                          tiers_held={"T1": ["aave_v3"]}),
    }
    _write_defi_engine_status(data_dir, generated_at=NOW, conservative=conservative)
    _write_kill_switch_and_derisk(data_dir, generated_at=NOW)
    out = sleeves.build_sleeves(data_dir, NOW)
    cons = out["sleeves"]["defi_conservative"]
    assert cons["nearest_enforced_stop"]["state"] == contract.NOT_MEASURED
    assert cons["nearest_enforced_stop"]["value"] is None
    # specifically NOT the legacy loss_budget.nearest_enforced_stop_pct (5.0, the soft number)
    assert cons["nearest_enforced_stop"]["reason"] == "no liquidating stop identifiable (no gate.stops published)"
    assert cons["worst_case_loss"]["state"] == contract.NOT_MEASURED


# finding N4: the balanced/aggressive stop gate must not read a STALE book's stop_reference as
# "not breached" — it must be UNKNOWN, same fail-closed pattern as the conservative gate (finding 2).

def test_balanced_stop_gate_unknown_when_book_file_is_stale(tmp_path):
    data_dir = _full_scene(tmp_path, hy_last_cycle=NOW - timedelta(hours=10))  # > 3h hourly cadence
    out = sleeves.build_sleeves(data_dir, NOW)
    gate = {g["gate"]: g for g in out["sleeves"]["defi_balanced"]["gates"]}["stop_not_active"]
    assert gate["state"] == "UNKNOWN"


def test_aggressive_stop_gate_unknown_when_book_file_is_stale(tmp_path):
    data_dir = _full_scene(tmp_path, lp_last_cycle=NOW - timedelta(hours=10))  # > 3h hourly cadence
    out = sleeves.build_sleeves(data_dir, NOW)
    gate = {g["gate"]: g for g in out["sleeves"]["defi_aggressive"]["gates"]}["stop_not_active"]
    assert gate["state"] == "UNKNOWN"


def test_balanced_stop_gate_unknown_when_book_file_missing(tmp_path):
    data_dir = _full_scene(tmp_path)
    (data_dir / "hy_paper_trading.json").unlink()
    out = sleeves.build_sleeves(data_dir, NOW)
    gate = {g["gate"]: g for g in out["sleeves"]["defi_balanced"]["gates"]}["stop_not_active"]
    assert gate["state"] == "UNKNOWN"


# finding N5: concentration caps are about actual protocol positions. cash is never a protocol
# holder for cap purposes; a sleeve allocated weight 0 under an explicit recommendation holds no
# capital and cannot keep protocol_cap_state stuck at PARTIAL forever. Without weights (no
# allocation to filter by) every non-cash sleeve is still listed, descriptively, as before.

def test_exposure_cash_never_contributes_to_protocol_cap_or_overlap():
    sleeves_in = {
        "cash": {
            "composition": [{"protocol": "usdc", "mechanic": "cash_buffer", "tier": "UNKNOWN",
                             "share": contract.measured(1.0, unit="share", source="test", as_of=None),
                             "usd": contract.measured(5000.0, unit="usd", source="test", as_of=None)}],
        },
        "defi_conservative": {
            "composition": [{"protocol": "aave_v3", "mechanic": "supply", "tier": "T1",
                             "share": contract.measured(1.0, unit="share", source="test", as_of=None),
                             "usd": contract.measured(100000.0, unit="usd", source="test", as_of=None)}],
        },
    }
    out = exposure.build(sleeves_in, weights={"defi_conservative": 1.0, "cash": 0.0})
    assert out["protocol_cap_state"] == "MEASURED"
    protos = {r["protocol"] for r in out["protocol_overlap"]}
    assert "usdc" not in protos
    assert not any(u["protocol"] == "usdc" for u in out["unchecked_protocols"])


def test_exposure_zero_weight_sleeve_excluded_from_cap_when_weights_given():
    sleeves_in = {
        "trading_research": {
            "composition": [{"protocol": "donchian@v1", "mechanic": "directional_trading", "tier": "UNKNOWN",
                             "share": contract.absent(contract.NOT_MEASURED, reason="no capital allocated"),
                             "usd": contract.absent(contract.NOT_MEASURED, reason="no capital allocated")}],
        },
        "defi_conservative": {
            "composition": [{"protocol": "aave_v3", "mechanic": "supply", "tier": "T1",
                             "share": contract.measured(1.0, unit="share", source="test", as_of=None),
                             "usd": contract.measured(100000.0, unit="usd", source="test", as_of=None)}],
        },
    }
    out = exposure.build(sleeves_in, weights={"defi_conservative": 1.0, "trading_research": 0.0})
    assert out["protocol_cap_state"] == "MEASURED"
    protos = {r["protocol"] for r in out["protocol_overlap"]}
    assert "donchian@v1" not in protos
    assert not any(u["protocol"] == "donchian@v1" for u in out["unchecked_protocols"])


def test_exposure_without_weights_still_lists_zero_capital_sleeves_descriptively():
    sleeves_in = {
        "trading_research": {
            "composition": [{"protocol": "donchian@v1", "mechanic": "directional_trading", "tier": "UNKNOWN",
                             "share": contract.absent(contract.NOT_MEASURED, reason="no capital allocated"),
                             "usd": contract.absent(contract.NOT_MEASURED, reason="no capital allocated")}],
        },
    }
    out = exposure.build(sleeves_in)  # no weights supplied => descriptive, nothing filtered by weight
    protos = {r["protocol"] for r in out["protocol_overlap"]}
    assert "donchian@v1" in protos
    assert out["protocol_cap_state"] == "PARTIAL"


# ── T9: no import of forbidden packages ─────────────────────────────────────────────────────────

FORBIDDEN_MODULES = (
    "spa_core.execution", "spa_core.paper_trading", "spa_core.allocator",
    "spa_core.risk", "spa_core.governance", "spa_core.investment_os",
)


@pytest.mark.parametrize("filename", ["sleeves.py", "exposure.py", "correlation.py"])
def test_no_forbidden_imports(filename):
    source = (_PKG_DIR / filename).read_text()
    tree = ast.parse(source, filename=filename)
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if any(alias.name == f or alias.name.startswith(f + ".") for f in FORBIDDEN_MODULES):
                    hits.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if any(mod == f or mod.startswith(f + ".") for f in FORBIDDEN_MODULES):
                hits.append(mod)
    assert not hits, f"{filename} imports forbidden module(s): {hits}"


def test_module_never_writes_files(tmp_path):
    """Pure read model: building twice against the same scene must not change any file on disk."""
    data_dir = _full_scene(tmp_path)
    before = {p: p.read_bytes() for p in data_dir.rglob("*") if p.is_file()}
    sleeves.build_sleeves(data_dir, NOW)
    after = {p: p.read_bytes() for p in data_dir.rglob("*") if p.is_file()}
    assert before == after
    assert set(before) == set(after)


# ── T10: live smoke test against the real data/ tree (skips if absent) ─────────────────────────

def _real_data_dir() -> Path:
    # The live Mac data tree (ADR-152: the git worktree's own data/ is a disposable scene,
    # not the live state) — the task names this path explicitly.
    return Path.home() / "Documents" / "SPA_Claude" / "data"


def _assert_no_bare_numbers(node, path="root"):
    """Walk the built document: every cell dict's value may be a number, but a bare number
    must never appear OUTSIDE a cell dict (invariant #17 — never a bare number for a cell)."""
    if isinstance(node, dict):
        if "state" in node and node["state"] in contract.CELL_STATES:
            return  # this IS a cell; its own 'value' is allowed to be a number
        for k, v in node.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                raise AssertionError(f"bare number outside a cell at {path}.{k} = {v!r}")
            _assert_no_bare_numbers(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _assert_no_bare_numbers(v, f"{path}[{i}]")


def test_live_smoke_against_real_data_dir():
    data_dir = _real_data_dir()
    if not data_dir.exists():
        pytest.skip(f"no live data dir at {data_dir}")
    out = sleeves.build_sleeves(data_dir, datetime.now(timezone.utc))
    assert out["schema"] == contract.SCHEMA_SLEEVES
    assert set(out["sleeves"]) == set(contract.SLEEVES)
    for sid, sleeve in out["sleeves"].items():
        for f in contract.SLEEVE_FIELDS:
            assert f in sleeve, f"{sid} missing {f}"
        _assert_no_bare_numbers(sleeve, path=sid)
    # exposure.py / correlation.py legitimately carry plain numeric summaries alongside cells
    # (leverage_per_sleeve, risk_policy_caps_reference, overlap_days) — only their *cell* fields
    # (weighted_share, correlation) are checked here, via the sleeves themselves above.
    for row in out["exposure"]["protocol_overlap"]:
        assert isinstance(row["weighted_share"], dict) and "state" in row["weighted_share"]
    for row in out["correlation"]["official_pairs"] + out["correlation"]["research_pairs"]:
        assert isinstance(row["correlation"], dict) and "state" in row["correlation"]

    print("\n=== investment_cio.sleeves live summary ===")
    for sid, sleeve in out["sleeves"].items():
        rr = sleeve["realized_return"]
        print(f"{sid}: maturity={sleeve['maturity'].get('value')} "
             f"valid_periods={sleeve['valid_periods'].get('value')} "
             f"realized_return={rr.get('state')}/{rr.get('value')}/n={rr.get('n')} "
             f"worst_case_loss={sleeve['worst_case_loss'].get('state')}/{sleeve['worst_case_loss'].get('value')} "
             f"cash_share={sleeve['cash_share'].get('state')}/{sleeve['cash_share'].get('value')} "
             f"gates_failing={[g['gate'] for g in sleeve['gates'] if g['state'] == 'FAIL']}")
