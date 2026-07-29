# LLM_FORBIDDEN
"""Hermetic tests for scripts/edge_funding_gated_carry.py (registry idea #22).

These lock the properties idea #22's honest verdict depends on:
  • the gate is CAUSAL — the day's own funding can never switch that day's position on;
  • the gate is fail-CLOSED before enough history exists (flat, not long);
  • `always` really is always-on and pays exactly the funding accrued;
  • switching costs are charged on transitions only, and both directions cost;
  • an OFF day earns the off-leg rate (0% cash by default), never funding;
  • metrics annualise on calendar days and Sharpe/Calmar respond in the right direction;
  • thin5 uses the live funding_regime agent's 5%/yr threshold.

Everything runs on hand-checkable synthetic funding series — no repo data, no network.
"""
from __future__ import annotations

import datetime
import importlib.util
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "edge_funding_gated_carry", ROOT / "scripts" / "edge_funding_gated_carry.py"
)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)  # type: ignore[union-attr]


def _dates(n: int, start="2024-01-01"):
    d0 = datetime.date.fromisoformat(start)
    return [(d0 + datetime.timedelta(days=i)).isoformat() for i in range(n)]


# ── causality / fail-closed ──────────────────────────────────────────────────────────────────────
def test_gate_ignores_the_days_own_funding():
    dates = _dates(40)
    funding = {d: -0.001 for d in dates}
    funding[dates[-1]] = +5.0                       # enormous same-day spike
    assert mod.gate_on("sign7", dates, funding, len(dates) - 1) is False


def test_gate_failclosed_without_history():
    dates = _dates(10)
    funding = {d: 0.001 for d in dates}
    assert mod.gate_on("sign7", dates, funding, 0) is False      # no past → flat
    assert mod.gate_on("sign30", dates, funding, 0) is False


def test_gate_turns_on_after_a_persistent_positive_regime():
    dates = _dates(40)
    funding = {d: 0.001 for d in dates}
    assert mod.gate_on("sign7", dates, funding, 20) is True


def test_gate_turns_off_after_a_persistent_negative_regime():
    dates = _dates(40)
    funding = {d: (0.001 if i < 10 else -0.001) for i, d in enumerate(dates)}
    assert mod.gate_on("sign7", dates, funding, 30) is False


def test_sign30_is_slower_than_sign7():
    dates = _dates(60)
    # 40 positive days then a 10-day negative patch: the 7d median flips, the 30d one does not
    funding = {d: (0.001 if i < 40 else -0.001) for i, d in enumerate(dates)}
    i = 50
    assert mod.gate_on("sign7", dates, funding, i) is False
    assert mod.gate_on("sign30", dates, funding, i) is True


def test_always_is_always_on():
    dates = _dates(20)
    funding = {d: -0.01 for d in dates}
    assert all(mod.gate_on("always", dates, funding, i) for i in range(len(dates)))


def test_thin5_uses_the_live_agent_threshold():
    dates = _dates(40)
    thin = 0.9 * mod.THIN_CARRY_ANN / (mod.FUNDING_PERIODS_PER_DAY * 365.0)
    rich = 1.5 * mod.THIN_CARRY_ANN / (mod.FUNDING_PERIODS_PER_DAY * 365.0)
    assert mod.gate_on("thin5", dates, {d: thin for d in dates}, 30) is False
    assert mod.gate_on("thin5", dates, {d: rich for d in dates}, 30) is True
    assert mod.THIN_CARRY_ANN == 0.05


# ── P&L mechanics ────────────────────────────────────────────────────────────────────────────────
def test_always_pays_exactly_the_accrued_funding_at_zero_cost():
    dates = _dates(5)
    funding = {d: 0.0001 for d in dates}
    rets, st = mod.simulate(dates, funding, "always", 0.0)
    assert all(math.isclose(r, 3 * 0.0001, rel_tol=1e-12) for r in rets)
    assert st["duty_pct"] == 100.0


def test_off_days_earn_the_off_leg_not_funding():
    dates = _dates(40)
    funding = {d: -0.001 for d in dates}
    rets, st = mod.simulate(dates, funding, "sign7", 0.0, off_apy_pct=3.31)
    assert st["duty_pct"] < 100.0
    off_day = rets[-1]
    assert math.isclose(off_day, 0.0331 / 365.0, rel_tol=1e-9)   # RWA floor, not −funding


def test_negative_funding_is_a_real_loss_for_the_ungated_sleeve():
    dates = _dates(5)
    rets, _ = mod.simulate(dates, {d: -0.0002 for d in dates}, "always", 0.0)
    assert all(r < 0 for r in rets)


def test_switch_cost_charged_once_per_transition_in_both_directions():
    dates = _dates(60)
    funding = {d: (0.001 if i < 30 else -0.001) for i, d in enumerate(dates)}
    free, st_free = mod.simulate(dates, funding, "sign7", 0.0)
    paid, st_paid = mod.simulate(dates, funding, "sign7", 20.0)
    assert st_free["switches"] == st_paid["switches"] >= 2       # on and back off
    charged = sum(f - p for f, p in zip(free, paid))
    assert math.isclose(charged, st_paid["switches"] * (20.0 / 2.0) / 10000.0, rel_tol=1e-9)


def test_higher_cost_never_raises_the_gated_apy():
    dates = _dates(120)
    funding = {d: (0.001 if (i // 10) % 2 == 0 else -0.001) for i, d in enumerate(dates)}
    apys = []
    for bps in (0.0, 10.0, 50.0):
        rets, _ = mod.simulate(dates, funding, "sign7", bps)
        apys.append(mod.metrics(dates, rets)["apy_pct"])
    assert apys[0] >= apys[1] >= apys[2]


def test_always_has_at_most_one_switch():
    dates = _dates(30)
    _, st = mod.simulate(dates, {d: 0.0001 for d in dates}, "always", 10.0)
    assert st["switches"] == 1                                   # the initial entry only


# ── metrics ──────────────────────────────────────────────────────────────────────────────────────
def test_metrics_annualise_on_calendar_days():
    dates = ["2024-01-01", "2025-01-01"]
    m = mod.metrics(dates, [0.0, 0.10])
    assert m["days"] == 366
    assert math.isclose(m["apy_pct"], (1.10 ** (365.0 / 366.0) - 1.0) * 100.0, rel_tol=1e-9)


def test_metrics_maxdd_zero_for_a_monotone_series():
    dates = _dates(10)
    m = mod.metrics(dates, [0.001] * 10)
    assert m["maxDD_pct"] == 0.0
    assert m["calmar"] == float("inf")           # honestly infinite, not silently clipped


def test_metrics_reports_drawdown_and_vol_on_a_mixed_series():
    dates = _dates(4)
    m = mod.metrics(dates, [0.10, -0.20, 0.05])
    assert m["maxDD_pct"] > 19.0
    assert m["vol_pct"] > 0.0


def test_gate_names_are_the_documented_set():
    assert mod.GATES == ("always", "sign7", "sign30", "thin5")
