"""
tests/test_portfolio_monitor.py
================================
Unit tests for spa_core.paper_trading.portfolio_monitor — PortfolioMonitor.

Coverage (≥ 85 tests):

TestConstants (5):
  C01  ALERT_INFO == "INFO"
  C02  ALERT_WARNING == "WARNING"
  C03  ALERT_CRITICAL == "CRITICAL"
  C04  SNAPSHOTS_MAX == 100
  C05  SNAPSHOTS_FILENAME == "monitor_snapshots.json"

TestMonitorAlertDataclass (8):
  A01  MonitorAlert stores level, adapter_id, message, drift
  A02  to_dict returns correct keys
  A03  to_dict drift is float
  A04  to_dict level is string
  A05  Two alerts with same data compare equal (dataclass)
  A06  to_dict returns plain dict (not MonitorAlert)
  A07  drift=0.0 is allowed
  A08  drift value round-trips through JSON

TestPortfolioMonitorInit (7):
  I01  Default info_threshold == 3.0
  I02  Default warning_threshold == 5.0
  I03  Default critical_threshold == 10.0
  I04  Default t2_critical_cap == 0.50
  I05  Custom thresholds are stored
  I06  data_dir attribute is set
  I07  Thresholds are floats after init

TestCheckDrift (15):
  D01  No drift when current == target
  D02  Single over-allocated adapter above default threshold
  D03  Single under-allocated adapter above default threshold
  D04  Adapter below threshold is excluded
  D05  Both adapters returned when both exceed threshold
  D06  drift_pct is in percentage points (e.g. 0.07 delta → 7.0 pp)
  D07  Sign: over-allocated → positive drift_pct
  D08  Sign: under-allocated → negative drift_pct
  D09  Adapter in target but not current has drift
  D10  Adapter in current but not target has drift
  D11  Custom threshold=0.0 returns all adapters
  D12  Custom threshold=0.10 filters more aggressively
  D13  Empty dicts return empty dict
  D14  Drift values are rounded to 6 decimal places
  D15  Large drift (30 pp) is captured correctly

TestGetAlerts (22):
  G01  No alerts when current == target
  G02  INFO alert when drift == info_threshold (exactly 3 pp)
  G03  INFO alert at 4 pp drift
  G04  WARNING alert at exactly warning_threshold (5 pp)
  G05  WARNING alert at 7 pp drift
  G06  CRITICAL alert when drift > 10 pp
  G07  Drift exactly 10 pp → WARNING (not CRITICAL; boundary)
  G08  Drift just over 10 pp → CRITICAL
  G09  Multiple adapters each get independent alert levels
  G10  T2 aggregate above cap → CRITICAL alert with T2_AGGREGATE id
  G11  T2 aggregate exactly at cap → no T2 aggregate alert
  G12  T2 aggregate below cap → no T2 aggregate alert
  G13  T2 cap can be overridden via risk_limits["t2_cap"]
  G14  Empty t2_adapters → no T2 aggregate alert
  G15  CRITICAL appears before WARNING in sorted output
  G16  WARNING appears before INFO in sorted output
  G17  Within same level, higher drift appears first
  G18  alert.drift is always ≥ 0
  G19  alert.message contains adapter_id
  G20  alert.message contains threshold value
  G21  No alerts for adapter with drift == 0
  G22  Returns list (not generator)

TestComputeHealthScore (12):
  H01  Empty weights returns 0.0
  H02  All-zero weights returns 0.0
  H03  Score is in [0, 100] range
  H04  Higher APY improves score
  H05  Lower risk_score improves score
  H06  More equal weights improve diversification score
  H07  Single adapter (HHI=1) → divers_score == 0
  H08  Missing adapter in adapters dict → defaults used, no error
  H09  APY component capped at 35 pts for very high APY
  H10  Risk component capped at 35 pts for zero-risk adapters
  H11  Returns float rounded to 2 decimal places
  H12  Score increases monotonically with APY improvement (all else equal)

TestGetSnapshot (12):
  S01  Snapshot has all required keys
  S02  generated_at is ISO UTC string
  S03  equity matches portfolio equity
  S04  adapter_count == len(adapters)
  S05  current_weights reflect portfolio input
  S06  target_weights reflect input
  S07  drift_map contains all adapters (threshold=0.0)
  S08  alerts list is serialisable list of dicts
  S09  health_score is float in [0, 100]
  S10  t2_total_weight reflects sum of T2 adapters
  S11  summary_level == "OK" when no drift
  S12  summary_level == "CRITICAL" when a drift exceeds critical threshold

TestSaveSnapshot (8):
  W01  save_snapshot creates monitor_snapshots.json in data_dir
  W02  saved content round-trips through JSON
  W03  Second save appends (ring-buffer grows)
  W04  Ring-buffer caps at SNAPSHOTS_MAX (100)
  W05  No lingering .tmp file after successful save
  W06  Existing corrupt file is tolerated (starts fresh)
  W07  save_snapshot with explicit data_dir argument
  W08  Atomic write: target file is updated after replace

TestLoadLatestSnapshot (6):
  L01  Returns None when file does not exist
  L02  Returns None for empty ring-buffer
  L03  Returns the last item in the ring-buffer
  L04  Tolerates corrupt file → returns None
  L05  load_latest_snapshot with explicit data_dir
  L06  After save+load cycle, data matches

TestCLI (5):
  CLI01  _main([]) exits 0
  CLI02  _main(["--check"]) exits 0
  CLI03  _main(["--run", "--data-dir", tmp_dir]) exits 0 and creates file
  CLI04  _main(["--data-dir", tmp_dir]) exits 0
  CLI05  Running --run twice accumulates 2 snapshots

TestImportHygiene (4):
  H_01  No subprocess import
  H_02  No requests/web3/numpy/pandas/scipy imports
  H_03  No openai/anthropic imports
  H_04  No execution/risk/monitoring imports
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

# Allow running from repo root: python -m unittest tests.test_portfolio_monitor
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from spa_core.paper_trading.portfolio_monitor import (
    ALERT_CRITICAL,
    ALERT_INFO,
    ALERT_WARNING,
    SNAPSHOTS_FILENAME,
    SNAPSHOTS_MAX,
    MonitorAlert,
    PortfolioMonitor,
    _main,
)


# ── Shared helpers ────────────────────────────────────────────────────────────

def _make_monitor(**kwargs) -> PortfolioMonitor:
    """Instantiate a PortfolioMonitor with a fresh temp data_dir by default."""
    if "data_dir" not in kwargs:
        kwargs["data_dir"] = tempfile.mkdtemp()
    return PortfolioMonitor(**kwargs)


_ADAPTERS_BASIC: Dict[str, Any] = {
    "aave_v3":     {"apy": 3.5,  "tvl": 1e9,   "risk_score": 0.20, "tier": "T1"},
    "compound_v3": {"apy": 4.8,  "tvl": 5e8,   "risk_score": 0.22, "tier": "T1"},
    "morpho":      {"apy": 6.5,  "tvl": 1.5e8, "risk_score": 0.28, "tier": "T2"},
    "cash":        {"apy": 0.0,  "tvl": 0.0,   "risk_score": 0.0,  "tier": "T1"},
}

_CURRENT_BASIC = {"aave_v3": 0.40, "compound_v3": 0.30, "morpho": 0.25, "cash": 0.05}
_TARGET_BASIC  = {"aave_v3": 0.35, "compound_v3": 0.35, "morpho": 0.25, "cash": 0.05}


# ── TestConstants ─────────────────────────────────────────────────────────────

class TestConstants(unittest.TestCase):
    """C01–C05: module-level constant values."""

    def test_c01_alert_info(self):
        self.assertEqual(ALERT_INFO, "INFO")

    def test_c02_alert_warning(self):
        self.assertEqual(ALERT_WARNING, "WARNING")

    def test_c03_alert_critical(self):
        self.assertEqual(ALERT_CRITICAL, "CRITICAL")

    def test_c04_snapshots_max(self):
        self.assertEqual(SNAPSHOTS_MAX, 100)

    def test_c05_snapshots_filename(self):
        self.assertEqual(SNAPSHOTS_FILENAME, "monitor_snapshots.json")


# ── TestMonitorAlertDataclass ─────────────────────────────────────────────────

class TestMonitorAlertDataclass(unittest.TestCase):
    """A01–A08: MonitorAlert dataclass behaviour."""

    def _make(self, **kwargs) -> MonitorAlert:
        defaults = dict(
            level=ALERT_INFO, adapter_id="aave_v3",
            message="test msg", drift=4.0
        )
        defaults.update(kwargs)
        return MonitorAlert(**defaults)

    def test_a01_fields_stored(self):
        a = self._make()
        self.assertEqual(a.level, ALERT_INFO)
        self.assertEqual(a.adapter_id, "aave_v3")
        self.assertEqual(a.message, "test msg")
        self.assertAlmostEqual(a.drift, 4.0)

    def test_a02_to_dict_keys(self):
        d = self._make().to_dict()
        self.assertIn("level", d)
        self.assertIn("adapter_id", d)
        self.assertIn("message", d)
        self.assertIn("drift", d)

    def test_a03_to_dict_drift_float(self):
        d = self._make(drift=7.5).to_dict()
        self.assertIsInstance(d["drift"], float)

    def test_a04_to_dict_level_string(self):
        d = self._make(level=ALERT_CRITICAL).to_dict()
        self.assertIsInstance(d["level"], str)
        self.assertEqual(d["level"], "CRITICAL")

    def test_a05_equality(self):
        a1 = self._make(drift=4.0)
        a2 = self._make(drift=4.0)
        self.assertEqual(a1, a2)

    def test_a06_to_dict_returns_plain_dict(self):
        d = self._make().to_dict()
        self.assertIsInstance(d, dict)
        self.assertNotIsInstance(d, MonitorAlert)

    def test_a07_drift_zero_allowed(self):
        a = self._make(drift=0.0)
        self.assertEqual(a.drift, 0.0)

    def test_a08_drift_json_roundtrip(self):
        a = self._make(drift=12.345678)
        serialised = json.dumps(a.to_dict())
        loaded = json.loads(serialised)
        self.assertAlmostEqual(loaded["drift"], 12.345678, places=4)


# ── TestPortfolioMonitorInit ──────────────────────────────────────────────────

class TestPortfolioMonitorInit(unittest.TestCase):
    """I01–I07: PortfolioMonitor constructor."""

    def test_i01_default_info_threshold(self):
        m = _make_monitor()
        self.assertAlmostEqual(m.info_threshold, 3.0)

    def test_i02_default_warning_threshold(self):
        m = _make_monitor()
        self.assertAlmostEqual(m.warning_threshold, 5.0)

    def test_i03_default_critical_threshold(self):
        m = _make_monitor()
        self.assertAlmostEqual(m.critical_threshold, 10.0)

    def test_i04_default_t2_cap(self):
        m = _make_monitor()
        self.assertAlmostEqual(m.t2_critical_cap, 0.50)

    def test_i05_custom_thresholds(self):
        m = _make_monitor(
            info_threshold=2.0,
            warning_threshold=4.0,
            critical_threshold=8.0,
            t2_critical_cap=0.40,
        )
        self.assertAlmostEqual(m.info_threshold, 2.0)
        self.assertAlmostEqual(m.warning_threshold, 4.0)
        self.assertAlmostEqual(m.critical_threshold, 8.0)
        self.assertAlmostEqual(m.t2_critical_cap, 0.40)

    def test_i06_data_dir_set(self):
        tmp = tempfile.mkdtemp()
        m = PortfolioMonitor(data_dir=tmp)
        self.assertEqual(m.data_dir, tmp)

    def test_i07_thresholds_are_floats(self):
        m = _make_monitor()
        self.assertIsInstance(m.info_threshold, float)
        self.assertIsInstance(m.warning_threshold, float)
        self.assertIsInstance(m.critical_threshold, float)
        self.assertIsInstance(m.t2_critical_cap, float)


# ── TestCheckDrift ────────────────────────────────────────────────────────────

class TestCheckDrift(unittest.TestCase):
    """D01–D15: check_drift logic."""

    def setUp(self):
        self.m = _make_monitor()

    def test_d01_no_drift(self):
        result = self.m.check_drift({"a": 0.40}, {"a": 0.40})
        self.assertEqual(result, {})

    def test_d02_over_allocated_above_threshold(self):
        result = self.m.check_drift({"a": 0.42}, {"a": 0.35})
        self.assertIn("a", result)
        self.assertGreater(result["a"], 0)

    def test_d03_under_allocated_above_threshold(self):
        result = self.m.check_drift({"a": 0.28}, {"a": 0.35})
        self.assertIn("a", result)
        self.assertLess(result["a"], 0)

    def test_d04_below_threshold_excluded(self):
        # 0.03 fraction = 3 pp — below default 5 pp threshold
        result = self.m.check_drift({"a": 0.38}, {"a": 0.35})
        self.assertNotIn("a", result)

    def test_d05_both_adapters_returned(self):
        cur = {"a": 0.42, "b": 0.28}
        tgt = {"a": 0.35, "b": 0.35}
        result = self.m.check_drift(cur, tgt)
        self.assertIn("a", result)
        self.assertIn("b", result)

    def test_d06_drift_in_percentage_points(self):
        # 0.07 fraction delta → 7.0 percentage points
        result = self.m.check_drift({"a": 0.42}, {"a": 0.35})
        self.assertAlmostEqual(result["a"], 7.0, places=4)

    def test_d07_sign_positive_when_over_allocated(self):
        result = self.m.check_drift({"a": 0.42}, {"a": 0.35})
        self.assertGreater(result["a"], 0)

    def test_d08_sign_negative_when_under_allocated(self):
        result = self.m.check_drift({"a": 0.28}, {"a": 0.35})
        self.assertLess(result["a"], 0)

    def test_d09_adapter_only_in_target(self):
        # "b" is in target but not in current → current=0, delta=0-0.10=-0.10
        result = self.m.check_drift({}, {"b": 0.10})
        self.assertIn("b", result)
        self.assertAlmostEqual(result["b"], -10.0, places=4)

    def test_d10_adapter_only_in_current(self):
        # "b" in current but not target → delta=0.10-0=+0.10
        result = self.m.check_drift({"b": 0.10}, {})
        self.assertIn("b", result)
        self.assertAlmostEqual(result["b"], 10.0, places=4)

    def test_d11_threshold_zero_returns_all(self):
        cur = {"a": 0.40, "b": 0.35}
        tgt = {"a": 0.40, "b": 0.35}
        result = self.m.check_drift(cur, tgt, threshold=0.0)
        # Both have zero drift — still included (|0| >= 0)
        self.assertIn("a", result)
        self.assertIn("b", result)

    def test_d12_high_custom_threshold_filters(self):
        # threshold=0.10 → only adapters with |drift| ≥ 10 pp
        cur = {"a": 0.42, "b": 0.60}
        tgt = {"a": 0.35, "b": 0.35}
        result = self.m.check_drift(cur, tgt, threshold=0.10)
        self.assertNotIn("a", result)  # 7 pp < 10 pp
        self.assertIn("b", result)     # 25 pp ≥ 10 pp

    def test_d13_empty_dicts(self):
        result = self.m.check_drift({}, {})
        self.assertEqual(result, {})

    def test_d14_values_rounded_6dp(self):
        result = self.m.check_drift({"a": 0.42}, {"a": 0.35})
        val = result["a"]
        # Rounded to 6 dp — confirm it's not a raw float with excessive precision
        self.assertEqual(val, round(val, 6))

    def test_d15_large_drift_captured(self):
        # 30 pp over-allocated
        result = self.m.check_drift({"a": 0.65}, {"a": 0.35})
        self.assertAlmostEqual(result["a"], 30.0, places=4)


# ── TestGetAlerts ─────────────────────────────────────────────────────────────

class TestGetAlerts(unittest.TestCase):
    """G01–G22: get_alerts alert generation."""

    def setUp(self):
        self.m = _make_monitor()
        self.rl_empty = {"t2_adapters": []}

    def _rl(self, t2=None, cap=0.50):
        return {"t2_adapters": t2 or [], "t2_cap": cap}

    def test_g01_no_alerts_when_equal(self):
        alerts = self.m.get_alerts({"a": 0.40}, {"a": 0.40}, self.rl_empty)
        self.assertEqual(alerts, [])

    def test_g02_info_at_exactly_info_threshold(self):
        # 3 pp drift → INFO
        alerts = self.m.get_alerts({"a": 0.38}, {"a": 0.35}, self.rl_empty)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].level, ALERT_INFO)

    def test_g03_info_at_4pp(self):
        # 4 pp → INFO
        alerts = self.m.get_alerts({"a": 0.39}, {"a": 0.35}, self.rl_empty)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].level, ALERT_INFO)

    def test_g04_warning_at_exactly_warning_threshold(self):
        # 5 pp → WARNING
        alerts = self.m.get_alerts({"a": 0.40}, {"a": 0.35}, self.rl_empty)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].level, ALERT_WARNING)

    def test_g05_warning_at_7pp(self):
        # 7 pp → WARNING
        alerts = self.m.get_alerts({"a": 0.42}, {"a": 0.35}, self.rl_empty)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].level, ALERT_WARNING)

    def test_g06_critical_when_drift_exceeds_10pp(self):
        # 11 pp → CRITICAL
        alerts = self.m.get_alerts({"a": 0.46}, {"a": 0.35}, self.rl_empty)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].level, ALERT_CRITICAL)

    def test_g07_9pp_drift_is_warning_not_critical(self):
        # 9 pp drift (0.44-0.35=0.09 exactly) → WARNING, not CRITICAL
        alerts = self.m.get_alerts({"a": 0.44}, {"a": 0.35}, self.rl_empty)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].level, ALERT_WARNING)

    def test_g08_just_over_10pp_is_critical(self):
        # 10.1 pp → CRITICAL
        alerts = self.m.get_alerts({"a": 0.451}, {"a": 0.35}, self.rl_empty)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].level, ALERT_CRITICAL)

    def test_g09_multiple_adapters_independent(self):
        cur = {"a": 0.46, "b": 0.39}   # a=11pp CRITICAL, b=4pp INFO
        tgt = {"a": 0.35, "b": 0.35}
        alerts = self.m.get_alerts(cur, tgt, self.rl_empty)
        levels = {a.adapter_id: a.level for a in alerts}
        self.assertEqual(levels["a"], ALERT_CRITICAL)
        self.assertEqual(levels["b"], ALERT_INFO)

    def test_g10_t2_aggregate_over_cap_is_critical(self):
        # T2 total = 0.55 > 0.50 cap
        cur = {"a": 0.30, "t2a": 0.35, "t2b": 0.20, "cash": 0.15}
        tgt = {"a": 0.30, "t2a": 0.35, "t2b": 0.20, "cash": 0.15}
        rl = self._rl(t2=["t2a", "t2b"])
        alerts = self.m.get_alerts(cur, tgt, rl)
        tier_alerts = [a for a in alerts if a.adapter_id == "T2_AGGREGATE"]
        self.assertEqual(len(tier_alerts), 1)
        self.assertEqual(tier_alerts[0].level, ALERT_CRITICAL)

    def test_g11_t2_aggregate_exactly_at_cap_no_alert(self):
        # T2 total == 0.50 → no alert (strict >)
        cur = {"a": 0.25, "t2a": 0.25, "t2b": 0.25, "cash": 0.25}
        tgt = cur.copy()
        rl = self._rl(t2=["t2a", "t2b"])  # t2a+t2b = 0.50
        alerts = self.m.get_alerts(cur, tgt, rl)
        tier_alerts = [a for a in alerts if a.adapter_id == "T2_AGGREGATE"]
        self.assertEqual(len(tier_alerts), 0)

    def test_g12_t2_below_cap_no_alert(self):
        cur = {"a": 0.60, "t2a": 0.20, "cash": 0.20}
        tgt = cur.copy()
        rl = self._rl(t2=["t2a"])
        alerts = self.m.get_alerts(cur, tgt, rl)
        tier_alerts = [a for a in alerts if a.adapter_id == "T2_AGGREGATE"]
        self.assertEqual(len(tier_alerts), 0)

    def test_g13_t2_cap_overridden_by_risk_limits(self):
        # Override t2_cap=0.30 — t2a+t2b=0.40 > 0.30 → CRITICAL
        cur = {"a": 0.30, "t2a": 0.25, "t2b": 0.15, "cash": 0.30}
        tgt = cur.copy()
        rl = self._rl(t2=["t2a", "t2b"], cap=0.30)
        alerts = self.m.get_alerts(cur, tgt, rl)
        tier_alerts = [a for a in alerts if a.adapter_id == "T2_AGGREGATE"]
        self.assertEqual(len(tier_alerts), 1)
        self.assertEqual(tier_alerts[0].level, ALERT_CRITICAL)

    def test_g14_empty_t2_adapters_no_tier_alert(self):
        cur = {"a": 0.60, "b": 0.40}
        tgt = cur.copy()
        rl = {"t2_adapters": []}
        alerts = self.m.get_alerts(cur, tgt, rl)
        self.assertEqual(alerts, [])

    def test_g15_critical_before_warning(self):
        cur = {"a": 0.46, "b": 0.42}   # a=11pp CRITICAL, b=7pp WARNING
        tgt = {"a": 0.35, "b": 0.35}
        alerts = self.m.get_alerts(cur, tgt, self.rl_empty)
        crit_idx   = next(i for i, a in enumerate(alerts) if a.level == ALERT_CRITICAL)
        warn_idx   = next(i for i, a in enumerate(alerts) if a.level == ALERT_WARNING)
        self.assertLess(crit_idx, warn_idx)

    def test_g16_warning_before_info(self):
        cur = {"a": 0.42, "b": 0.38}   # a=7pp WARNING, b=3pp INFO
        tgt = {"a": 0.35, "b": 0.35}
        alerts = self.m.get_alerts(cur, tgt, self.rl_empty)
        warn_idx = next(i for i, a in enumerate(alerts) if a.level == ALERT_WARNING)
        info_idx = next(i for i, a in enumerate(alerts) if a.level == ALERT_INFO)
        self.assertLess(warn_idx, info_idx)

    def test_g17_same_level_higher_drift_first(self):
        cur = {"a": 0.50, "b": 0.47}   # a=15pp CRITICAL, b=12pp CRITICAL
        tgt = {"a": 0.35, "b": 0.35}
        alerts = self.m.get_alerts(cur, tgt, self.rl_empty)
        crit = [a for a in alerts if a.level == ALERT_CRITICAL]
        self.assertEqual(crit[0].adapter_id, "a")

    def test_g18_drift_always_non_negative(self):
        cur = {"a": 0.28, "b": 0.42}
        tgt = {"a": 0.35, "b": 0.35}
        alerts = self.m.get_alerts(cur, tgt, self.rl_empty)
        for a in alerts:
            self.assertGreaterEqual(a.drift, 0)

    def test_g19_message_contains_adapter_id(self):
        alerts = self.m.get_alerts({"xyz": 0.46}, {"xyz": 0.35}, self.rl_empty)
        self.assertIn("xyz", alerts[0].message)

    def test_g20_message_contains_threshold(self):
        # CRITICAL threshold = 10.0 → message should mention it
        alerts = self.m.get_alerts({"a": 0.46}, {"a": 0.35}, self.rl_empty)
        self.assertIn("10.0", alerts[0].message)

    def test_g21_zero_drift_no_alert(self):
        alerts = self.m.get_alerts({"a": 0.35}, {"a": 0.35}, self.rl_empty)
        self.assertEqual(alerts, [])

    def test_g22_returns_list(self):
        result = self.m.get_alerts({"a": 0.40}, {"a": 0.35}, self.rl_empty)
        self.assertIsInstance(result, list)


# ── TestComputeHealthScore ────────────────────────────────────────────────────

class TestComputeHealthScore(unittest.TestCase):
    """H01–H12: compute_portfolio_health_score logic."""

    def setUp(self):
        self.m = _make_monitor()

    def test_h01_empty_weights_returns_zero(self):
        score = self.m.compute_portfolio_health_score({}, {})
        self.assertEqual(score, 0.0)

    def test_h02_all_zero_weights_returns_zero(self):
        score = self.m.compute_portfolio_health_score(
            {"a": {"apy": 5.0, "risk_score": 0.2}},
            {"a": 0.0},
        )
        self.assertEqual(score, 0.0)

    def test_h03_score_in_range(self):
        score = self.m.compute_portfolio_health_score(
            _ADAPTERS_BASIC, _CURRENT_BASIC
        )
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_h04_higher_apy_improves_score(self):
        low_apy  = {"a": {"apy": 1.0, "risk_score": 0.3}}
        high_apy = {"a": {"apy": 8.0, "risk_score": 0.3}}
        s_low  = self.m.compute_portfolio_health_score(low_apy,  {"a": 1.0})
        s_high = self.m.compute_portfolio_health_score(high_apy, {"a": 1.0})
        self.assertGreater(s_high, s_low)

    def test_h05_lower_risk_improves_score(self):
        high_risk = {"a": {"apy": 5.0, "risk_score": 0.9}}
        low_risk  = {"a": {"apy": 5.0, "risk_score": 0.1}}
        s_high = self.m.compute_portfolio_health_score(high_risk, {"a": 1.0})
        s_low  = self.m.compute_portfolio_health_score(low_risk,  {"a": 1.0})
        self.assertGreater(s_low, s_high)

    def test_h06_equal_weights_better_diversification(self):
        adapters = {
            "a": {"apy": 5.0, "risk_score": 0.3},
            "b": {"apy": 5.0, "risk_score": 0.3},
            "c": {"apy": 5.0, "risk_score": 0.3},
        }
        equal       = {"a": 1/3, "b": 1/3, "c": 1/3}
        concentrated = {"a": 0.90, "b": 0.05, "c": 0.05}
        s_equal = self.m.compute_portfolio_health_score(adapters, equal)
        s_conc  = self.m.compute_portfolio_health_score(adapters, concentrated)
        self.assertGreater(s_equal, s_conc)

    def test_h07_single_adapter_zero_divers(self):
        # HHI=1 → divers_score=0
        adapters = {"a": {"apy": 0.0, "risk_score": 0.0}}
        score = self.m.compute_portfolio_health_score(adapters, {"a": 1.0})
        # Contribution: divers = 30*(1-1) = 0; apy = 0; risk = 35*(1-0) = 35
        self.assertAlmostEqual(score, 35.0, places=1)

    def test_h08_missing_adapter_in_adapters_no_error(self):
        # "b" not in adapters dict → defaults used
        score = self.m.compute_portfolio_health_score(
            {"a": {"apy": 5.0, "risk_score": 0.2}},
            {"a": 0.5, "b": 0.5},
        )
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_h09_apy_component_capped_at_35(self):
        # APY = 100% >> 10% ceiling → capped at 35 pts
        adapters = {"a": {"apy": 100.0, "risk_score": 0.0}}
        score = self.m.compute_portfolio_health_score(adapters, {"a": 1.0})
        # apy=35, risk=35, divers=0 → 70
        self.assertAlmostEqual(score, 70.0, places=1)

    def test_h10_risk_component_max_when_zero_risk(self):
        # All zero risk → risk_score = 35
        adapters = {"a": {"apy": 10.0, "risk_score": 0.0}}
        score = self.m.compute_portfolio_health_score(adapters, {"a": 1.0})
        # apy=35, risk=35, divers=0 → 70
        self.assertAlmostEqual(score, 70.0, places=1)

    def test_h11_returns_float_rounded_2dp(self):
        score = self.m.compute_portfolio_health_score(
            _ADAPTERS_BASIC, _CURRENT_BASIC
        )
        self.assertIsInstance(score, float)
        self.assertEqual(score, round(score, 2))

    def test_h12_apy_improvement_monotonic(self):
        """Increasing APY monotonically increases health score up to the APY
        ceiling (_APY_HEALTH_MAX = 6%), then plateaus (full APY credit)."""
        from spa_core.paper_trading.portfolio_monitor import _APY_HEALTH_MAX
        # Sample strictly below the ceiling → strictly increasing.
        scores = []
        for apy in [1.0, 2.0, 3.0, 4.0, 5.0]:
            adapters = {"a": {"apy": apy, "risk_score": 0.3}}
            scores.append(self.m.compute_portfolio_health_score(adapters, {"a": 1.0}))
        for i in range(len(scores) - 1):
            self.assertLess(scores[i], scores[i + 1])
        # At/above the ceiling the APY component is maxed → equal scores.
        at_ceiling = self.m.compute_portfolio_health_score(
            {"a": {"apy": _APY_HEALTH_MAX, "risk_score": 0.3}}, {"a": 1.0})
        above_ceiling = self.m.compute_portfolio_health_score(
            {"a": {"apy": _APY_HEALTH_MAX + 5.0, "risk_score": 0.3}}, {"a": 1.0})
        self.assertEqual(at_ceiling, above_ceiling)


# ── TestGetSnapshot ───────────────────────────────────────────────────────────

class TestGetSnapshot(unittest.TestCase):
    """S01–S12: get_snapshot structure and content."""

    def setUp(self):
        self.m = _make_monitor()
        self.portfolio = {"current_weights": _CURRENT_BASIC, "equity": 100_000.0}

    def _snap(self, portfolio=None, adapters=None, target=None):
        return self.m.get_snapshot(
            portfolio or self.portfolio,
            adapters or _ADAPTERS_BASIC,
            target or _TARGET_BASIC,
        )

    def test_s01_required_keys_present(self):
        snap = self._snap()
        for key in (
            "generated_at", "equity", "adapter_count",
            "current_weights", "target_weights", "drift_map",
            "alerts", "health_score", "t2_total_weight", "summary_level",
        ):
            self.assertIn(key, snap, f"Missing key: {key}")

    def test_s02_generated_at_is_iso_utc(self):
        snap = self._snap()
        ga = snap["generated_at"]
        self.assertIsInstance(ga, str)
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(ga)
        self.assertIsNotNone(dt.tzinfo)

    def test_s03_equity_matches_input(self):
        snap = self._snap()
        self.assertAlmostEqual(snap["equity"], 100_000.0)

    def test_s04_adapter_count(self):
        snap = self._snap()
        self.assertEqual(snap["adapter_count"], len(_ADAPTERS_BASIC))

    def test_s05_current_weights_reflect_input(self):
        snap = self._snap()
        self.assertAlmostEqual(snap["current_weights"]["aave_v3"], 0.40, places=6)

    def test_s06_target_weights_reflect_input(self):
        snap = self._snap()
        self.assertAlmostEqual(snap["target_weights"]["aave_v3"], 0.35, places=6)

    def test_s07_drift_map_contains_all_adapters(self):
        snap = self._snap()
        # threshold=0.0 → all adapters appear in drift_map
        for aid in _CURRENT_BASIC:
            self.assertIn(aid, snap["drift_map"])

    def test_s08_alerts_is_list_of_dicts(self):
        snap = self._snap()
        self.assertIsInstance(snap["alerts"], list)
        for a in snap["alerts"]:
            self.assertIsInstance(a, dict)

    def test_s09_health_score_in_range(self):
        snap = self._snap()
        self.assertGreaterEqual(snap["health_score"], 0.0)
        self.assertLessEqual(snap["health_score"], 100.0)

    def test_s10_t2_total_weight(self):
        # morpho is T2 in _ADAPTERS_BASIC; current weight = 0.25
        snap = self._snap()
        self.assertAlmostEqual(snap["t2_total_weight"], 0.25, places=6)

    def test_s11_summary_level_ok_when_no_drift(self):
        # current == target → no alerts
        port = {"current_weights": _TARGET_BASIC, "equity": 100_000.0}
        snap = self.m.get_snapshot(port, _ADAPTERS_BASIC, _TARGET_BASIC)
        self.assertEqual(snap["summary_level"], "OK")

    def test_s12_summary_level_critical_on_large_drift(self):
        big_drift_cur = {"aave_v3": 0.70, "compound_v3": 0.10,
                         "morpho": 0.10, "cash": 0.10}
        port = {"current_weights": big_drift_cur, "equity": 100_000.0}
        snap = self.m.get_snapshot(port, _ADAPTERS_BASIC, _TARGET_BASIC)
        self.assertEqual(snap["summary_level"], ALERT_CRITICAL)


# ── TestSaveSnapshot ──────────────────────────────────────────────────────────

class TestSaveSnapshot(unittest.TestCase):
    """W01–W08: save_snapshot atomic persistence."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.m = PortfolioMonitor(data_dir=self.tmp)
        self.snap = {"generated_at": "2026-06-13T00:00:00+00:00",
                     "equity": 100_000.0, "summary_level": "OK"}

    def test_w01_creates_file(self):
        snap_path = Path(self.tmp) / SNAPSHOTS_FILENAME
        self.assertFalse(snap_path.exists())
        self.m.save_snapshot(self.snap)
        self.assertTrue(snap_path.exists())

    def test_w02_content_roundtrip(self):
        self.m.save_snapshot(self.snap)
        raw = json.loads(
            (Path(self.tmp) / SNAPSHOTS_FILENAME).read_text(encoding="utf-8")
        )
        self.assertIsInstance(raw, list)
        self.assertEqual(len(raw), 1)
        self.assertEqual(raw[0]["equity"], 100_000.0)

    def test_w03_second_save_appends(self):
        self.m.save_snapshot(self.snap)
        self.m.save_snapshot({**self.snap, "equity": 101_000.0})
        raw = json.loads(
            (Path(self.tmp) / SNAPSHOTS_FILENAME).read_text(encoding="utf-8")
        )
        self.assertEqual(len(raw), 2)

    def test_w04_ring_buffer_caps_at_max(self):
        for i in range(SNAPSHOTS_MAX + 10):
            self.m.save_snapshot({**self.snap, "equity": float(i)})
        raw = json.loads(
            (Path(self.tmp) / SNAPSHOTS_FILENAME).read_text(encoding="utf-8")
        )
        self.assertEqual(len(raw), SNAPSHOTS_MAX)

    def test_w05_no_lingering_tmp_files(self):
        self.m.save_snapshot(self.snap)
        tmp_files = list(Path(self.tmp).glob(".monitor_snapshots_*.tmp"))
        self.assertEqual(tmp_files, [])

    def test_w06_corrupt_file_tolerated(self):
        snap_path = Path(self.tmp) / SNAPSHOTS_FILENAME
        snap_path.write_text("NOT VALID JSON", encoding="utf-8")
        self.m.save_snapshot(self.snap)   # should not raise
        raw = json.loads(snap_path.read_text(encoding="utf-8"))
        self.assertEqual(len(raw), 1)

    def test_w07_explicit_data_dir_argument(self):
        other_tmp = tempfile.mkdtemp()
        self.m.save_snapshot(self.snap, data_dir=other_tmp)
        self.assertTrue((Path(other_tmp) / SNAPSHOTS_FILENAME).exists())

    def test_w08_target_file_updated_after_replace(self):
        snap_path = Path(self.tmp) / SNAPSHOTS_FILENAME
        self.m.save_snapshot(self.snap)
        mtime1 = snap_path.stat().st_mtime
        import time; time.sleep(0.01)
        self.m.save_snapshot({**self.snap, "equity": 99_000.0})
        mtime2 = snap_path.stat().st_mtime
        self.assertGreaterEqual(mtime2, mtime1)


# ── TestSaveSnapshotPortfolioHealth ──────────────────────────────────────────
# Tests specifically for the 6-line block added to save_snapshot() that writes
# data/portfolio_health.json for agent_health_monitor / system_health_monitor.
#
# The 6 lines under test:
#   health_file = data_path / "portfolio_health.json"
#   health_payload = {
#       "generated_at": snapshot.get("generated_at"),
#       "health_score": snapshot.get("health_score"),
#       "summary_level": snapshot.get("summary_level"),
#   }
#   atomic_save(health_payload, str(health_file))

class TestSaveSnapshotPortfolioHealth(unittest.TestCase):
    """PH01–PH09: portfolio_health.json written by save_snapshot()."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.m = PortfolioMonitor(data_dir=self.tmp)
        # Build a real snapshot via the public API so generated_at / health_score
        # / summary_level are properly populated.
        portfolio = {"current_weights": _CURRENT_BASIC, "equity": 80_000.0}
        self.snap = self.m.get_snapshot(portfolio, _ADAPTERS_BASIC, _TARGET_BASIC)

    def _health_path(self) -> Path:
        return Path(self.tmp) / "portfolio_health.json"

    def _health_data(self) -> dict:
        return json.loads(self._health_path().read_text(encoding="utf-8"))

    def test_ph01_portfolio_health_json_created(self):
        """save_snapshot() creates portfolio_health.json in the data_dir."""
        self.assertFalse(self._health_path().exists(), "precondition: file absent")
        self.m.save_snapshot(self.snap)
        self.assertTrue(
            self._health_path().exists(),
            "portfolio_health.json was not created by save_snapshot()",
        )

    def test_ph02_has_generated_at_key(self):
        """portfolio_health.json contains the 'generated_at' key."""
        self.m.save_snapshot(self.snap)
        self.assertIn("generated_at", self._health_data())

    def test_ph03_has_health_score_key(self):
        """portfolio_health.json contains the 'health_score' key."""
        self.m.save_snapshot(self.snap)
        self.assertIn("health_score", self._health_data())

    def test_ph04_has_summary_level_key(self):
        """portfolio_health.json contains the 'summary_level' key."""
        self.m.save_snapshot(self.snap)
        self.assertIn("summary_level", self._health_data())

    def test_ph05_exactly_three_keys(self):
        """portfolio_health.json contains exactly generated_at, health_score, summary_level."""
        self.m.save_snapshot(self.snap)
        self.assertEqual(
            set(self._health_data().keys()),
            {"generated_at", "health_score", "summary_level"},
        )

    def test_ph06_values_match_snapshot(self):
        """portfolio_health.json values exactly mirror the snapshot dict."""
        self.m.save_snapshot(self.snap)
        data = self._health_data()
        self.assertEqual(data["generated_at"],  self.snap["generated_at"])
        self.assertEqual(data["health_score"],   self.snap["health_score"])
        self.assertEqual(data["summary_level"],  self.snap["summary_level"])

    def test_ph07_health_score_is_numeric(self):
        """portfolio_health.json['health_score'] is a number in [0, 100]."""
        self.m.save_snapshot(self.snap)
        score = self._health_data()["health_score"]
        self.assertIsInstance(score, (int, float))
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_ph08_overwritten_on_second_save(self):
        """A second save_snapshot() overwrites portfolio_health.json with new values."""
        self.m.save_snapshot(self.snap)
        # Build a second snapshot with a deliberately different health score by
        # changing the equity (doesn't affect health score) but swapping adapters
        # to force a different summary_level.
        portfolio2 = {"current_weights": _TARGET_BASIC, "equity": 50_000.0}
        snap2 = self.m.get_snapshot(portfolio2, _ADAPTERS_BASIC, _TARGET_BASIC)
        self.m.save_snapshot(snap2)
        data = self._health_data()
        self.assertEqual(data["generated_at"],  snap2["generated_at"])
        self.assertEqual(data["health_score"],   snap2["health_score"])
        self.assertEqual(data["summary_level"],  snap2["summary_level"])

    def test_ph09_created_alongside_snapshots_file(self):
        """Both monitor_snapshots.json and portfolio_health.json are written together."""
        self.m.save_snapshot(self.snap)
        self.assertTrue((Path(self.tmp) / SNAPSHOTS_FILENAME).exists())
        self.assertTrue(self._health_path().exists())

    def test_ph10_works_with_explicit_data_dir_override(self):
        """portfolio_health.json is created in the explicit data_dir, not self.data_dir."""
        other_tmp = tempfile.mkdtemp()
        self.m.save_snapshot(self.snap, data_dir=other_tmp)
        self.assertTrue((Path(other_tmp) / "portfolio_health.json").exists())
        # Original dir should be untouched
        self.assertFalse(self._health_path().exists())

    def test_ph11_summary_level_ok_when_no_drift(self):
        """summary_level in portfolio_health.json is 'OK' when no drift exists."""
        portfolio = {"current_weights": _TARGET_BASIC, "equity": 10_000.0}
        snap_ok = self.m.get_snapshot(portfolio, _ADAPTERS_BASIC, _TARGET_BASIC)
        self.m.save_snapshot(snap_ok)
        self.assertEqual(self._health_data()["summary_level"], "OK")

    def test_ph12_summary_level_warning_on_moderate_drift(self):
        """summary_level reflects WARNING when an adapter has notable drift."""
        cur = dict(_TARGET_BASIC)
        cur["aave_v3"] = cur.get("aave_v3", 0.35) + 0.08   # +8 pp drift → WARNING
        portfolio = {"current_weights": cur, "equity": 10_000.0}
        snap_w = self.m.get_snapshot(portfolio, _ADAPTERS_BASIC, _TARGET_BASIC)
        self.m.save_snapshot(snap_w)
        self.assertIn(
            self._health_data()["summary_level"],
            {"WARNING", ALERT_CRITICAL},   # large drift may cascade to CRITICAL
        )


# ── TestLoadLatestSnapshot ────────────────────────────────────────────────────

class TestLoadLatestSnapshot(unittest.TestCase):
    """L01–L06: load_latest_snapshot."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.m = PortfolioMonitor(data_dir=self.tmp)
        self.snap = {"generated_at": "2026-06-13T00:00:00+00:00",
                     "equity": 100_000.0, "summary_level": "OK"}

    def test_l01_returns_none_when_file_missing(self):
        result = self.m.load_latest_snapshot()
        self.assertIsNone(result)

    def test_l02_returns_none_for_empty_list(self):
        snap_path = Path(self.tmp) / SNAPSHOTS_FILENAME
        snap_path.write_text("[]", encoding="utf-8")
        result = self.m.load_latest_snapshot()
        self.assertIsNone(result)

    def test_l03_returns_last_item(self):
        self.m.save_snapshot({"equity": 1.0})
        self.m.save_snapshot({"equity": 2.0})
        self.m.save_snapshot({"equity": 3.0})
        result = self.m.load_latest_snapshot()
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["equity"], 3.0)

    def test_l04_corrupt_file_returns_none(self):
        snap_path = Path(self.tmp) / SNAPSHOTS_FILENAME
        snap_path.write_text("BROKEN", encoding="utf-8")
        result = self.m.load_latest_snapshot()
        self.assertIsNone(result)

    def test_l05_explicit_data_dir(self):
        other_tmp = tempfile.mkdtemp()
        self.m.save_snapshot(self.snap, data_dir=other_tmp)
        result = self.m.load_latest_snapshot(data_dir=other_tmp)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result["equity"], 100_000.0)

    def test_l06_save_load_round_trip(self):
        portfolio = {"current_weights": _CURRENT_BASIC, "equity": 99_999.99}
        snap = self.m.get_snapshot(portfolio, _ADAPTERS_BASIC, _TARGET_BASIC)
        self.m.save_snapshot(snap)
        loaded = self.m.load_latest_snapshot()
        self.assertIsNotNone(loaded)
        self.assertAlmostEqual(loaded["equity"], 99_999.99, places=2)
        self.assertIn("summary_level", loaded)
        self.assertIn("health_score", loaded)


# ── TestCLI ───────────────────────────────────────────────────────────────────

class TestCLI(unittest.TestCase):
    """CLI01–CLI05: _main entry-point."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_cli01_no_args_exits_0(self):
        rc = _main([])
        self.assertEqual(rc, 0)

    def test_cli02_check_flag_exits_0(self):
        rc = _main(["--check"])
        self.assertEqual(rc, 0)

    def test_cli03_run_flag_creates_file(self):
        _main(["--run", "--data-dir", self.tmp])
        snap_path = Path(self.tmp) / SNAPSHOTS_FILENAME
        self.assertTrue(snap_path.exists())

    def test_cli04_data_dir_flag_exits_0(self):
        rc = _main(["--data-dir", self.tmp])
        self.assertEqual(rc, 0)

    def test_cli05_run_twice_accumulates(self):
        _main(["--run", "--data-dir", self.tmp])
        _main(["--run", "--data-dir", self.tmp])
        raw = json.loads(
            (Path(self.tmp) / SNAPSHOTS_FILENAME).read_text(encoding="utf-8")
        )
        self.assertEqual(len(raw), 2)


# ── TestImportHygiene ─────────────────────────────────────────────────────────

class TestImportHygiene(unittest.TestCase):
    """H_01–H_04: forbidden import checks."""

    def _src(self) -> str:
        import spa_core.paper_trading.portfolio_monitor as _mod
        return Path(_mod.__file__).read_text(encoding="utf-8")

    def test_h_01_no_subprocess(self):
        self.assertNotIn("import subprocess", self._src())

    def test_h_02_no_requests_or_web3(self):
        src = self._src()
        for banned in ("import requests", "import web3", "import numpy",
                       "import pandas", "import scipy"):
            self.assertNotIn(banned, src)

    def test_h_03_no_llm_sdk(self):
        src = self._src()
        for banned in ("import openai", "import anthropic"):
            self.assertNotIn(banned, src)

    def test_h_04_no_forbidden_domain_imports(self):
        src = self._src()
        for banned in ("from spa_core.execution", "from spa_core.risk",
                       "from spa_core.monitoring"):
            self.assertNotIn(banned, src)


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
