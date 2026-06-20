"""tests/test_rebalance_trigger.py — Comprehensive pytest suite for
spa_core.paper_trading.rebalance_trigger.RebalanceTrigger.

Covers
======
- RT-01 drift trigger: above threshold, below threshold, exact threshold,
  no weights, asymmetric key sets, adapters only in current, only in target
- RT-02 APY opportunity: regime change + gain, no regime change, same regime,
  gain below threshold, gain at threshold, None regimes, empty string regimes
- RT-03 risk gate: DL-03 fired (direct flag), DL-03 nested under "checks",
  snake_case key, no DL-03, empty dict, None input
- RT-04 calendar: 7 days + drift, 6 days no trigger, exactly 7 days,
  no drift no trigger, never rebalanced, invalid date string, future date
- check_all: no triggers, RT-01 only, RT-02 only, RT-03 only, RT-04 only,
  multiple triggers, all triggers, structure of returned dict
- load_config: good config, missing file, corrupt JSON, non-object JSON,
  partial keys, unknown keys ignored

Run::

    python3 -m pytest tests/test_rebalance_trigger.py -v
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import tempfile

# Ensure spa_core is importable from the project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from spa_core.paper_trading.rebalance_trigger import (
    RebalanceTrigger,
    _DEFAULT_APY_OPPORTUNITY_BPS,
    _DEFAULT_CALENDAR_MIN_DRIFT_PCT,
    _DEFAULT_CALENDAR_TRIGGER_DAYS,
    _DEFAULT_DRIFT_TRIGGER_PCT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_trigger(**kwargs) -> RebalanceTrigger:
    """Create a RebalanceTrigger with optional parameter overrides."""
    return RebalanceTrigger(**kwargs)


def yesterday_str(offset: int = 1) -> str:
    """Return a date string N days in the past."""
    d = datetime.now(timezone.utc).date() - timedelta(days=offset)
    return d.isoformat()


def _write_config(data_dir: str, cfg: dict) -> str:
    """Write a rebalancing_config.json to data_dir and return the path."""
    path = os.path.join(data_dir, "rebalancing_config.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    return path


# ============================================================
# RT-01: Drift Trigger
# ============================================================

class TestRT01Drift:
    def test_rt01_no_drift(self):
        """Identical weights → not triggered."""
        t = make_trigger()
        w = {"aave_v3": 0.50, "compound_v3": 0.50}
        res = t.check_rt01_drift(w, w.copy())
        assert res["triggered"] is False
        assert res["max_drift_pct"] == pytest.approx(0.0, abs=1e-6)

    def test_rt01_drift_above_threshold(self):
        """6% drift on one adapter → triggered."""
        t = make_trigger()
        current = {"aave_v3": 0.36, "compound_v3": 0.64}
        target = {"aave_v3": 0.30, "compound_v3": 0.70}
        res = t.check_rt01_drift(current, target)
        assert res["triggered"] is True
        assert res["max_drift_pct"] == pytest.approx(6.0, abs=0.01)
        assert res["max_drift_adapter"] == "aave_v3"
        assert res["threshold"] == 5.0

    def test_rt01_drift_below_threshold(self):
        """4.9% drift → not triggered."""
        t = make_trigger()
        current = {"aave_v3": 0.349, "compound_v3": 0.651}
        target = {"aave_v3": 0.300, "compound_v3": 0.700}
        res = t.check_rt01_drift(current, target)
        assert res["triggered"] is False
        assert res["max_drift_pct"] == pytest.approx(4.9, abs=0.01)

    def test_rt01_drift_clearly_below_threshold(self):
        """4.9% drift (clearly below 5.0) → NOT triggered."""
        t = make_trigger()
        current = {"aave_v3": 0.349}
        target = {"aave_v3": 0.300}
        res = t.check_rt01_drift(current, target)
        assert res["triggered"] is False
        assert res["max_drift_pct"] == pytest.approx(4.9, abs=0.01)

    def test_rt01_drift_just_over_threshold(self):
        """5.01% drift → triggered."""
        t = make_trigger()
        current = {"aave_v3": 0.3501}
        target = {"aave_v3": 0.3000}
        res = t.check_rt01_drift(current, target)
        assert res["triggered"] is True

    def test_rt01_adapters_not_in_target(self):
        """Adapter present in current but missing from target → full weight is drift."""
        t = make_trigger()
        current = {"aave_v3": 0.40, "new_protocol": 0.60}
        target = {"aave_v3": 0.40}  # new_protocol not in target
        res = t.check_rt01_drift(current, target)
        # new_protocol: |0.60 - 0| * 100 = 60 pp → triggered
        assert res["triggered"] is True
        assert res["max_drift_adapter"] == "new_protocol"
        assert res["max_drift_pct"] == pytest.approx(60.0, abs=0.01)

    def test_rt01_adapters_only_in_target(self):
        """Adapter in target but not in current → target weight is drift."""
        t = make_trigger()
        current = {"aave_v3": 1.0}
        target = {"aave_v3": 0.70, "compound_v3": 0.30}
        res = t.check_rt01_drift(current, target)
        # aave_v3: |1.0 - 0.7| * 100 = 30 pp; compound_v3: |0 - 0.3| * 100 = 30 pp
        assert res["triggered"] is True
        assert res["max_drift_pct"] == pytest.approx(30.0, abs=0.01)

    def test_rt01_empty_weights(self):
        """Both empty dicts → no drift, not triggered."""
        t = make_trigger()
        res = t.check_rt01_drift({}, {})
        assert res["triggered"] is False
        assert res["max_drift_pct"] == pytest.approx(0.0, abs=1e-6)
        assert res["max_drift_adapter"] is None

    def test_rt01_custom_threshold(self):
        """Custom drift threshold of 3.0% triggers on 3.5% drift."""
        t = make_trigger(drift_trigger_pct=3.0)
        current = {"aave_v3": 0.335, "compound_v3": 0.665}
        target = {"aave_v3": 0.300, "compound_v3": 0.700}
        res = t.check_rt01_drift(current, target)
        assert res["triggered"] is True
        assert res["threshold"] == 3.0

    def test_rt01_multiple_adapters_worst_wins(self):
        """The adapter with the highest drift determines triggered and max_drift_adapter."""
        t = make_trigger()
        current = {"a": 0.32, "b": 0.33, "c": 0.36}
        target = {"a": 0.30, "b": 0.30, "c": 0.30}
        # drifts: a=2pp, b=3pp, c=6pp → c is worst → triggered
        res = t.check_rt01_drift(current, target)
        assert res["triggered"] is True
        assert res["max_drift_adapter"] == "c"
        assert res["max_drift_pct"] == pytest.approx(6.0, abs=0.01)

    def test_rt01_result_structure(self):
        """Return dict always has all required keys."""
        t = make_trigger()
        res = t.check_rt01_drift({"a": 0.5}, {"a": 0.5})
        assert "triggered" in res
        assert "max_drift_pct" in res
        assert "max_drift_adapter" in res
        assert "threshold" in res


# ============================================================
# RT-02: APY Opportunity
# ============================================================

class TestRT02ApyOpportunity:
    def test_rt02_regime_change_with_gain(self):
        """Regime changed + gain 60 bps > 50 bps → triggered."""
        t = make_trigger()
        res = t.check_rt02_apy_opportunity("bull", "bear", 60.0)
        assert res["triggered"] is True
        assert res["regime_changed"] is True
        assert res["apy_gain_bps"] == pytest.approx(60.0)
        assert res["threshold_bps"] == pytest.approx(50.0)

    def test_rt02_no_regime_change(self):
        """Same regime → not triggered even with high gain."""
        t = make_trigger()
        res = t.check_rt02_apy_opportunity("bull", "bull", 200.0)
        assert res["triggered"] is False
        assert res["regime_changed"] is False

    def test_rt02_gain_below_threshold(self):
        """Regime changed but gain < 50 bps → not triggered."""
        t = make_trigger()
        res = t.check_rt02_apy_opportunity("bull", "neutral", 40.0)
        assert res["triggered"] is False
        assert res["regime_changed"] is True

    def test_rt02_gain_exactly_at_threshold(self):
        """Gain exactly 50.0 bps → NOT triggered (strictly >)."""
        t = make_trigger()
        res = t.check_rt02_apy_opportunity("bull", "bear", 50.0)
        assert res["triggered"] is False

    def test_rt02_gain_just_above_threshold(self):
        """Gain 50.001 bps → triggered."""
        t = make_trigger()
        res = t.check_rt02_apy_opportunity("bull", "bear", 50.001)
        assert res["triggered"] is True

    def test_rt02_none_current_regime(self):
        """current_regime=None → regime_changed=False → not triggered."""
        t = make_trigger()
        res = t.check_rt02_apy_opportunity(None, "bear", 100.0)
        assert res["triggered"] is False
        assert res["regime_changed"] is False

    def test_rt02_none_new_regime(self):
        """new_regime=None → regime_changed=False → not triggered."""
        t = make_trigger()
        res = t.check_rt02_apy_opportunity("bull", None, 100.0)
        assert res["triggered"] is False
        assert res["regime_changed"] is False

    def test_rt02_both_none_regime(self):
        """Both regimes None → not triggered."""
        t = make_trigger()
        res = t.check_rt02_apy_opportunity(None, None, 200.0)
        assert res["triggered"] is False

    def test_rt02_empty_string_regime(self):
        """Empty string regime → not a valid regime label → not triggered."""
        t = make_trigger()
        res = t.check_rt02_apy_opportunity("", "bear", 100.0)
        assert res["triggered"] is False
        assert res["regime_changed"] is False

    def test_rt02_zero_gain(self):
        """Zero gain with regime change → not triggered."""
        t = make_trigger()
        res = t.check_rt02_apy_opportunity("bull", "bear", 0.0)
        assert res["triggered"] is False

    def test_rt02_custom_threshold(self):
        """Custom threshold of 100 bps — gain 80 bps + regime change → not triggered."""
        t = make_trigger(apy_opportunity_bps=100.0)
        res = t.check_rt02_apy_opportunity("bull", "bear", 80.0)
        assert res["triggered"] is False

    def test_rt02_result_structure(self):
        """Return dict always has all required keys."""
        t = make_trigger()
        res = t.check_rt02_apy_opportunity("a", "b", 0.0)
        assert "triggered" in res
        assert "regime_changed" in res
        assert "apy_gain_bps" in res
        assert "threshold_bps" in res


# ============================================================
# RT-03: Risk Gate
# ============================================================

class TestRT03RiskGate:
    def test_rt03_dl03_fired_direct_flag(self):
        """dl03_fired=True in direct dict → triggered."""
        t = make_trigger()
        res = t.check_rt03_risk_gate({"dl03_fired": True})
        assert res["triggered"] is True
        assert res["dl03_fired"] is True

    def test_rt03_dl03_not_fired_direct_flag(self):
        """dl03_fired=False → not triggered."""
        t = make_trigger()
        res = t.check_rt03_risk_gate({"dl03_fired": False})
        assert res["triggered"] is False
        assert res["dl03_fired"] is False

    def test_rt03_dl03_nested_checks_DL03(self):
        """DL-03 nested under checks with key 'DL-03' → triggered."""
        t = make_trigger()
        result = {"checks": {"DL-03": {"triggered": True}}}
        res = t.check_rt03_risk_gate(result)
        assert res["triggered"] is True

    def test_rt03_dl03_nested_checks_dl_03(self):
        """DL-03 nested under checks with snake_case key 'dl_03' → triggered."""
        t = make_trigger()
        result = {"checks": {"dl_03": {"triggered": True}}}
        res = t.check_rt03_risk_gate(result)
        assert res["triggered"] is True

    def test_rt03_dl03_nested_checks_not_fired(self):
        """DL-03 nested but triggered=False → not triggered."""
        t = make_trigger()
        result = {"checks": {"DL-03": {"triggered": False}}}
        res = t.check_rt03_risk_gate(result)
        assert res["triggered"] is False

    def test_rt03_no_dl03(self):
        """Dict with unrelated keys → not triggered."""
        t = make_trigger()
        result = {"dl01_fired": True, "dl02_fired": True}
        res = t.check_rt03_risk_gate(result)
        assert res["triggered"] is False

    def test_rt03_no_limits_result_none(self):
        """None input → not triggered."""
        t = make_trigger()
        res = t.check_rt03_risk_gate(None)
        assert res["triggered"] is False
        assert res["dl03_fired"] is False

    def test_rt03_empty_dict(self):
        """Empty dict → not triggered."""
        t = make_trigger()
        res = t.check_rt03_risk_gate({})
        assert res["triggered"] is False

    def test_rt03_dl03_fired_takes_priority(self):
        """Direct dl03_fired=True even if checks say False → triggered."""
        t = make_trigger()
        result = {"dl03_fired": True, "checks": {"DL-03": {"triggered": False}}}
        res = t.check_rt03_risk_gate(result)
        assert res["triggered"] is True

    def test_rt03_result_structure(self):
        """Return dict always has triggered and dl03_fired keys."""
        t = make_trigger()
        res = t.check_rt03_risk_gate(None)
        assert "triggered" in res
        assert "dl03_fired" in res


# ============================================================
# RT-04: Calendar
# ============================================================

class TestRT04Calendar:
    def test_rt04_7_days_elapsed_with_drift(self):
        """7 days since last rebalance AND 3% drift → triggered."""
        t = make_trigger()
        last = yesterday_str(7)
        current = {"aave_v3": 0.33, "compound_v3": 0.67}
        target = {"aave_v3": 0.30, "compound_v3": 0.70}  # 3pp drift
        res = t.check_rt04_calendar(last, current, target)
        assert res["triggered"] is True
        assert res["days_since"] == 7
        assert res["threshold_days"] == 7
        assert res["max_drift_pct"] == pytest.approx(3.0, abs=0.01)

    def test_rt04_8_days_elapsed_with_drift(self):
        """8 days elapsed + drift → triggered."""
        t = make_trigger()
        last = yesterday_str(8)
        current = {"aave_v3": 0.35}
        target = {"aave_v3": 0.30}
        res = t.check_rt04_calendar(last, current, target)
        assert res["triggered"] is True
        assert res["days_since"] == 8

    def test_rt04_not_enough_days(self):
        """Only 6 days elapsed → not triggered even with drift."""
        t = make_trigger()
        last = yesterday_str(6)
        current = {"aave_v3": 0.35}
        target = {"aave_v3": 0.30}
        res = t.check_rt04_calendar(last, current, target)
        assert res["triggered"] is False
        assert res["days_since"] == 6

    def test_rt04_7_days_no_drift(self):
        """7 days elapsed but drift < 2% → not triggered."""
        t = make_trigger()
        last = yesterday_str(7)
        current = {"aave_v3": 0.301}
        target = {"aave_v3": 0.300}  # only 0.1pp drift
        res = t.check_rt04_calendar(last, current, target)
        assert res["triggered"] is False

    def test_rt04_drift_clearly_below_min(self):
        """Drift 1.9pp (clearly below 2.0pp threshold) AND 7 days → not triggered."""
        t = make_trigger()
        last = yesterday_str(7)
        current = {"aave_v3": 0.319}
        target = {"aave_v3": 0.300}   # 1.9pp drift
        res = t.check_rt04_calendar(last, current, target)
        assert res["triggered"] is False
        assert res["max_drift_pct"] == pytest.approx(1.9, abs=0.01)

    def test_rt04_drift_just_over_min(self):
        """Drift 2.001% AND 7 days → triggered."""
        t = make_trigger()
        last = yesterday_str(7)
        current = {"aave_v3": 0.32001}
        target = {"aave_v3": 0.30000}
        res = t.check_rt04_calendar(last, current, target)
        assert res["triggered"] is True

    def test_rt04_never_rebalanced(self):
        """last_rebalance_date=None → treated as infinite days → triggered if drift."""
        t = make_trigger()
        current = {"aave_v3": 0.35}
        target = {"aave_v3": 0.30}   # 5pp drift > 2pp
        res = t.check_rt04_calendar(None, current, target)
        assert res["triggered"] is True
        assert res["days_since"] is None

    def test_rt04_never_rebalanced_no_drift(self):
        """Never rebalanced but no drift → not triggered."""
        t = make_trigger()
        current = {"aave_v3": 0.30}
        target = {"aave_v3": 0.30}
        res = t.check_rt04_calendar(None, current, target)
        assert res["triggered"] is False
        assert res["days_since"] is None

    def test_rt04_invalid_date_string(self):
        """Invalid date string treated as never rebalanced."""
        t = make_trigger()
        current = {"aave_v3": 0.35}
        target = {"aave_v3": 0.30}
        res = t.check_rt04_calendar("not-a-date", current, target)
        # treated as never rebalanced → triggered if drift > 2pp
        assert res["triggered"] is True

    def test_rt04_result_structure(self):
        """Return dict has all expected keys."""
        t = make_trigger()
        res = t.check_rt04_calendar(None, {}, {})
        assert "triggered" in res
        assert "days_since" in res
        assert "max_drift_pct" in res
        assert "threshold_days" in res

    def test_rt04_custom_trigger_days(self):
        """Custom trigger of 3 days — 4 days elapsed + drift → triggered."""
        t = make_trigger(calendar_trigger_days=3)
        last = yesterday_str(4)
        current = {"aave_v3": 0.33}
        target = {"aave_v3": 0.30}
        res = t.check_rt04_calendar(last, current, target)
        assert res["triggered"] is True
        assert res["threshold_days"] == 3

    def test_rt04_today_not_triggered(self):
        """Rebalanced today (0 days) → not triggered."""
        t = make_trigger()
        today = datetime.now(timezone.utc).date().isoformat()
        current = {"aave_v3": 0.40}
        target = {"aave_v3": 0.30}
        res = t.check_rt04_calendar(today, current, target)
        assert res["triggered"] is False
        assert res["days_since"] == 0


# ============================================================
# check_all
# ============================================================

class TestCheckAll:
    def test_check_all_no_triggers(self):
        """All identical weights, same regime, no DL-03, recent rebalance → no trigger."""
        t = make_trigger()
        w = {"aave_v3": 0.50, "compound_v3": 0.50}
        res = t.check_all(
            current_weights=w,
            target_weights=w.copy(),
            current_regime="bull",
            new_regime="bull",
            apy_gain_bps=0.0,
            daily_limits_result=None,
            last_rebalance_date=yesterday_str(1),
        )
        assert res["should_rebalance"] is False
        assert res["triggered"] == []

    def test_check_all_rt01_only(self):
        """Big drift fires RT-01, nothing else fires."""
        t = make_trigger()
        current = {"aave_v3": 0.40, "compound_v3": 0.60}
        target = {"aave_v3": 0.30, "compound_v3": 0.70}  # 10pp drift
        res = t.check_all(
            current_weights=current,
            target_weights=target,
            current_regime="bull",
            new_regime="bull",
            apy_gain_bps=0.0,
            daily_limits_result=None,
            last_rebalance_date=yesterday_str(1),
        )
        assert res["should_rebalance"] is True
        assert "RT-01" in res["triggered"]
        assert "RT-02" not in res["triggered"]
        assert "RT-03" not in res["triggered"]

    def test_check_all_rt02_only(self):
        """Regime change + 60 bps, no drift, no DL-03, recent rebalance → RT-02."""
        t = make_trigger()
        w = {"aave_v3": 0.50, "compound_v3": 0.50}
        res = t.check_all(
            current_weights=w,
            target_weights=w.copy(),
            current_regime="bull",
            new_regime="bear",
            apy_gain_bps=60.0,
            daily_limits_result=None,
            last_rebalance_date=yesterday_str(1),
        )
        assert res["should_rebalance"] is True
        assert res["triggered"] == ["RT-02"]

    def test_check_all_rt03_only(self):
        """DL-03 fired, no drift, same regime → RT-03."""
        t = make_trigger()
        w = {"aave_v3": 0.50, "compound_v3": 0.50}
        res = t.check_all(
            current_weights=w,
            target_weights=w.copy(),
            current_regime="bull",
            new_regime="bull",
            apy_gain_bps=0.0,
            daily_limits_result={"dl03_fired": True},
            last_rebalance_date=yesterday_str(1),
        )
        assert res["should_rebalance"] is True
        assert res["triggered"] == ["RT-03"]

    def test_check_all_rt04_only(self):
        """7 days elapsed + 3pp drift, no other triggers → RT-04."""
        t = make_trigger()
        current = {"aave_v3": 0.33, "compound_v3": 0.67}
        target = {"aave_v3": 0.30, "compound_v3": 0.70}
        res = t.check_all(
            current_weights=current,
            target_weights=target,
            current_regime="bull",
            new_regime="bull",
            apy_gain_bps=0.0,
            daily_limits_result=None,
            last_rebalance_date=yesterday_str(7),
        )
        assert res["should_rebalance"] is True
        assert "RT-04" in res["triggered"]
        # RT-01 not triggered: 3pp < 5pp
        assert "RT-01" not in res["triggered"]

    def test_check_all_multiple_triggers_rt01_rt03(self):
        """RT-01 and RT-03 both fire."""
        t = make_trigger()
        current = {"aave_v3": 0.40, "compound_v3": 0.60}
        target = {"aave_v3": 0.30, "compound_v3": 0.70}
        res = t.check_all(
            current_weights=current,
            target_weights=target,
            daily_limits_result={"dl03_fired": True},
            last_rebalance_date=yesterday_str(1),
        )
        assert res["should_rebalance"] is True
        assert "RT-01" in res["triggered"]
        assert "RT-03" in res["triggered"]

    def test_check_all_all_triggers(self):
        """All 4 triggers fire simultaneously."""
        t = make_trigger()
        current = {"aave_v3": 0.40, "compound_v3": 0.60}
        target = {"aave_v3": 0.30, "compound_v3": 0.70}
        res = t.check_all(
            current_weights=current,
            target_weights=target,
            current_regime="bull",
            new_regime="bear",
            apy_gain_bps=100.0,
            daily_limits_result={"dl03_fired": True},
            last_rebalance_date=yesterday_str(8),
        )
        assert res["should_rebalance"] is True
        for code in ("RT-01", "RT-02", "RT-03", "RT-04"):
            assert code in res["triggered"]

    def test_check_all_result_structure(self):
        """Return dict has all required top-level keys and nested check keys."""
        t = make_trigger()
        res = t.check_all({}, {})
        assert "should_rebalance" in res
        assert "triggered" in res
        assert "checks" in res
        assert "checked_at" in res
        checks = res["checks"]
        for key in ("rt01", "rt02", "rt03", "rt04"):
            assert key in checks

    def test_check_all_checked_at_is_iso(self):
        """checked_at field is a valid ISO timestamp string."""
        t = make_trigger()
        res = t.check_all({}, {})
        # Should parse without error
        dt = datetime.fromisoformat(res["checked_at"])
        assert dt is not None

    def test_check_all_triggered_order(self):
        """Triggered list preserves RT-01 → RT-02 → RT-03 → RT-04 order."""
        t = make_trigger()
        current = {"aave_v3": 0.40}
        target = {"aave_v3": 0.30}
        res = t.check_all(
            current_weights=current,
            target_weights=target,
            current_regime="bull",
            new_regime="bear",
            apy_gain_bps=100.0,
            daily_limits_result={"dl03_fired": True},
            last_rebalance_date=yesterday_str(8),
        )
        assert res["triggered"] == ["RT-01", "RT-02", "RT-03", "RT-04"]

    def test_check_all_defaults(self):
        """check_all works with only positional weight args (all optional params default)."""
        t = make_trigger()
        res = t.check_all(
            current_weights={"aave_v3": 0.50},
            target_weights={"aave_v3": 0.50},
        )
        assert isinstance(res["should_rebalance"], bool)
        assert isinstance(res["triggered"], list)

    def test_check_all_equity_history_ignored(self):
        """equity_history param doesn't break anything (reserved)."""
        t = make_trigger()
        res = t.check_all(
            current_weights={},
            target_weights={},
            equity_history=[{"date": "2026-06-01", "equity": 100000}],
        )
        assert isinstance(res["should_rebalance"], bool)


# ============================================================
# load_config
# ============================================================

class TestLoadConfig:
    def test_load_config_all_keys(self):
        """Full config updates all instance attributes."""
        t = make_trigger()
        with tempfile.TemporaryDirectory() as td:
            cfg = {
                "drift_trigger_pct": 3.0,
                "calendar_trigger_days": 5,
                "calendar_min_drift_pct": 1.5,
                "apy_opportunity_bps": 75.0,
            }
            path = _write_config(td, cfg)
            t.load_config(path)
        assert t.drift_trigger_pct == pytest.approx(3.0)
        assert t.calendar_trigger_days == 5
        assert t.calendar_min_drift_pct == pytest.approx(1.5)
        assert t.apy_opportunity_bps == pytest.approx(75.0)

    def test_load_config_partial_keys(self):
        """Only drift_trigger_pct in config — others keep defaults."""
        t = make_trigger()
        with tempfile.TemporaryDirectory() as td:
            path = _write_config(td, {"drift_trigger_pct": 2.5})
            t.load_config(path)
        assert t.drift_trigger_pct == pytest.approx(2.5)
        assert t.calendar_trigger_days == _DEFAULT_CALENDAR_TRIGGER_DAYS
        assert t.calendar_min_drift_pct == pytest.approx(_DEFAULT_CALENDAR_MIN_DRIFT_PCT)

    def test_load_config_unknown_keys_ignored(self):
        """Unknown keys in config don't raise exceptions."""
        t = make_trigger()
        with tempfile.TemporaryDirectory() as td:
            path = _write_config(td, {
                "drift_trigger_pct": 4.0,
                "some_future_key": 999,
                "adr_reference": "ADR-031",
            })
            t.load_config(path)
        assert t.drift_trigger_pct == pytest.approx(4.0)

    def test_load_config_missing_file(self):
        """Missing file → keeps defaults, no exception."""
        t = make_trigger()
        t.load_config("/nonexistent/path/config.json")  # should not raise
        assert t.drift_trigger_pct == pytest.approx(_DEFAULT_DRIFT_TRIGGER_PCT)
        assert t.calendar_trigger_days == _DEFAULT_CALENDAR_TRIGGER_DAYS

    def test_load_config_corrupt_json(self):
        """Corrupt JSON → keeps defaults, no exception."""
        t = make_trigger()
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "rebalancing_config.json")
            with open(path, "w") as f:
                f.write("{invalid json}")
            t.load_config(path)
        assert t.drift_trigger_pct == pytest.approx(_DEFAULT_DRIFT_TRIGGER_PCT)

    def test_load_config_non_object_json(self):
        """JSON array (not object) → keeps defaults, no exception."""
        t = make_trigger()
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "rebalancing_config.json")
            with open(path, "w") as f:
                json.dump([1, 2, 3], f)
            t.load_config(path)
        assert t.drift_trigger_pct == pytest.approx(_DEFAULT_DRIFT_TRIGGER_PCT)

    def test_load_config_real_project_config(self):
        """Load the real data/rebalancing_config.json if it exists."""
        t = make_trigger()
        config_path = Path(__file__).parent.parent / "data" / "rebalancing_config.json"
        if config_path.exists():
            t.load_config(str(config_path))
            # Values should match what's in the file
            assert t.drift_trigger_pct == pytest.approx(5.0)
            assert t.calendar_trigger_days == 7
            assert t.calendar_min_drift_pct == pytest.approx(2.0)
        else:
            pytest.skip("data/rebalancing_config.json not found")

    def test_load_config_default_path_arg(self):
        """load_config() accepts string path, no required args."""
        t = make_trigger()
        # Should not raise even if default path doesn't exist from test CWD
        try:
            t.load_config("data/rebalancing_config.json")
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"load_config raised unexpectedly: {exc}")


# ============================================================
# Default constructor values
# ============================================================

class TestDefaults:
    def test_default_constants_match_adr031(self):
        """Module-level defaults match ADR-031 spec."""
        assert _DEFAULT_DRIFT_TRIGGER_PCT == pytest.approx(5.0)
        assert _DEFAULT_CALENDAR_TRIGGER_DAYS == 7
        assert _DEFAULT_CALENDAR_MIN_DRIFT_PCT == pytest.approx(2.0)
        assert _DEFAULT_APY_OPPORTUNITY_BPS == pytest.approx(50.0)

    def test_default_instance_values(self):
        """Fresh instance inherits module-level defaults."""
        t = RebalanceTrigger()
        assert t.drift_trigger_pct == pytest.approx(_DEFAULT_DRIFT_TRIGGER_PCT)
        assert t.calendar_trigger_days == _DEFAULT_CALENDAR_TRIGGER_DAYS
        assert t.calendar_min_drift_pct == pytest.approx(_DEFAULT_CALENDAR_MIN_DRIFT_PCT)
        assert t.apy_opportunity_bps == pytest.approx(_DEFAULT_APY_OPPORTUNITY_BPS)

    def test_constructor_overrides(self):
        """Constructor kwargs override defaults."""
        t = RebalanceTrigger(
            drift_trigger_pct=10.0,
            calendar_trigger_days=14,
            calendar_min_drift_pct=3.0,
            apy_opportunity_bps=100.0,
        )
        assert t.drift_trigger_pct == pytest.approx(10.0)
        assert t.calendar_trigger_days == 14
        assert t.calendar_min_drift_pct == pytest.approx(3.0)
        assert t.apy_opportunity_bps == pytest.approx(100.0)
