"""Tests for EmergencyBreakers (ADR-030).

Coverage target: ≥ 50 tests across all five EB checks, precedence logic,
edge cases, custom threshold overrides, and atomic save.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from spa_core.risk.emergency_breakers import (
    CHECK_FAIL,
    CHECK_PASS,
    CHECK_SKIP,
    STATUS_CLEAR,
    STATUS_HALT,
    STATUS_PAUSE,
    EmergencyBreakers,
    _bar_equity,
    _max_status,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

def _eq_bar(equity: float, timestamp: str | None = None) -> dict:
    bar: dict = {"close_equity": equity}
    if timestamp:
        bar["timestamp"] = timestamp
    return bar


def _normal_history(n: int = 5, start: float = 100_000.0) -> list[dict]:
    """Generate a clean, monotonically-increasing equity history."""
    bars = []
    for i in range(n):
        ts = f"2026-06-{10 + i:02d}T08:00:00+00:00"
        bars.append(_eq_bar(start + i * 100, timestamp=ts))
    return bars


NORMAL_APY = {"aave_v3": 3.5, "compound_v3": 4.8, "morpho": 6.5}
STATIC_APY = {"aave_v3": 3.5, "compound_v3": 4.8, "morpho": 6.5}


# ═════════════════════════════════════════════════════════════════════════════
# Section 1: check_all — overall status / precedence
# ═════════════════════════════════════════════════════════════════════════════

class TestCheckAll:
    def test_all_clear_normal_inputs(self):
        eb = EmergencyBreakers()
        result = eb.check_all(
            apy_map=NORMAL_APY,
            equity_history=_normal_history(),
            gas_gwei=5.0,
            static_apy=STATIC_APY,
        )
        assert result["status"] == STATUS_CLEAR
        assert result["triggered"] == []
        assert set(result["checks"].keys()) == {"eb01", "eb02", "eb03", "eb04", "eb05"}

    def test_checked_at_is_iso(self):
        eb = EmergencyBreakers()
        result = eb.check_all(apy_map={}, equity_history=[])
        ts = result["checked_at"]
        assert "T" in ts and "Z" in ts or "+" in ts  # ISO-8601

    def test_halt_takes_precedence_over_pause(self):
        """Both EB-01 (HALT) and EB-03 (PAUSE) triggered → overall must be HALT."""
        eb = EmergencyBreakers()
        result = eb.check_all(
            apy_map={"aave_v3": 999.0},   # EB-01 triggers HALT
            equity_history=_normal_history(),
            gas_gwei=200.0,               # EB-03 triggers PAUSE
        )
        assert result["status"] == STATUS_HALT
        assert "EB-01" in result["triggered"]
        assert "EB-03" in result["triggered"]

    def test_pause_only_when_no_halt(self):
        eb = EmergencyBreakers()
        result = eb.check_all(
            apy_map=NORMAL_APY,
            equity_history=_normal_history(),
            gas_gwei=200.0,               # Only EB-03 → PAUSE
        )
        assert result["status"] == STATUS_PAUSE
        assert result["triggered"] == ["EB-03"]

    def test_multiple_halts_still_halt(self):
        """EB-01 + EB-04 both HALT → status is HALT, both in triggered."""
        eb = EmergencyBreakers()
        history = [
            _eq_bar(100_000, "2026-06-10T08:00:00+00:00"),
            _eq_bar(50_000,  "2026-06-11T08:00:00+00:00"),  # 50% drop → EB-04
        ]
        result = eb.check_all(
            apy_map={"aave_v3": 999.0},  # EB-01
            equity_history=history,
        )
        assert result["status"] == STATUS_HALT
        assert "EB-01" in result["triggered"]
        assert "EB-04" in result["triggered"]

    def test_empty_inputs_all_skipped(self):
        eb = EmergencyBreakers()
        result = eb.check_all(apy_map={}, equity_history=[])
        assert result["status"] == STATUS_CLEAR
        assert result["triggered"] == []

    def test_checks_dict_has_five_keys(self):
        eb = EmergencyBreakers()
        result = eb.check_all(apy_map=NORMAL_APY, equity_history=_normal_history())
        assert len(result["checks"]) == 5


# ═════════════════════════════════════════════════════════════════════════════
# Section 2: EB-01 — Protocol Exploit Alert
# ═════════════════════════════════════════════════════════════════════════════

class TestEB01ExploitProbe:
    def test_normal_apy_ok(self):
        eb = EmergencyBreakers()
        r = eb.check_eb01_exploit_probe(NORMAL_APY)
        assert r["status"] == CHECK_PASS
        assert r["verdict"] == STATUS_CLEAR

    def test_exploit_apy_halts(self):
        eb = EmergencyBreakers()
        r = eb.check_eb01_exploit_probe({"aave_v3": 999.9})
        assert r["status"] == CHECK_FAIL
        assert r["verdict"] == STATUS_HALT
        assert any(o["adapter"] == "aave_v3" for o in r["offenders"])

    def test_boundary_exactly_threshold_passes(self):
        """APY == threshold: not strictly greater → should PASS."""
        eb = EmergencyBreakers()
        r = eb.check_eb01_exploit_probe({"protocol": 100.0})
        assert r["verdict"] == STATUS_CLEAR  # 100.0 is not > 100.0

    def test_boundary_just_above_threshold_halts(self):
        eb = EmergencyBreakers()
        r = eb.check_eb01_exploit_probe({"protocol": 100.01})
        assert r["verdict"] == STATUS_HALT

    def test_multiple_offenders_all_listed(self):
        eb = EmergencyBreakers()
        r = eb.check_eb01_exploit_probe({"a": 200.0, "b": 150.0, "c": 5.0})
        assert r["verdict"] == STATUS_HALT
        adapters = [o["adapter"] for o in r["offenders"]]
        assert "a" in adapters
        assert "b" in adapters
        assert "c" not in adapters

    def test_empty_apy_map_skipped(self):
        eb = EmergencyBreakers()
        r = eb.check_eb01_exploit_probe({})
        assert r["status"] == CHECK_SKIP
        assert r["verdict"] == STATUS_CLEAR

    def test_nan_apy_is_exploit_signal(self):
        eb = EmergencyBreakers()
        r = eb.check_eb01_exploit_probe({"protocol": float("nan")})
        assert r["verdict"] == STATUS_HALT

    def test_infinite_apy_is_exploit_signal(self):
        eb = EmergencyBreakers()
        r = eb.check_eb01_exploit_probe({"protocol": float("inf")})
        assert r["verdict"] == STATUS_HALT

    def test_custom_threshold(self):
        eb = EmergencyBreakers(apy_exploit_threshold_pct=50.0)
        r = eb.check_eb01_exploit_probe({"protocol": 60.0})
        assert r["verdict"] == STATUS_HALT

    def test_normal_apy_below_custom_threshold(self):
        eb = EmergencyBreakers(apy_exploit_threshold_pct=200.0)
        r = eb.check_eb01_exploit_probe({"protocol": 150.0})
        assert r["verdict"] == STATUS_CLEAR


# ═════════════════════════════════════════════════════════════════════════════
# Section 3: EB-02 — Oracle Divergence Cascade
# ═════════════════════════════════════════════════════════════════════════════

class TestEB02OracleCascade:
    def test_no_divergence_ok(self):
        eb = EmergencyBreakers()
        r = eb.check_eb02_oracle_cascade(NORMAL_APY, STATIC_APY)
        assert r["status"] == CHECK_PASS
        assert r["verdict"] == STATUS_CLEAR

    def test_small_divergence_does_not_trigger(self):
        """2 adapter diverge by 400 bps — below 500 bps threshold."""
        live = {"a": 8.5, "b": 9.0, "c": 6.5}
        static = {"a": 4.5, "b": 5.0, "c": 6.5}  # a and b diverge 400 bps
        eb = EmergencyBreakers()
        r = eb.check_eb02_oracle_cascade(live, static)
        assert r["verdict"] == STATUS_CLEAR

    def test_cascade_not_enough_adapters(self):
        """Only 2 adapters diverge > 500 bps — need ≥ 3 → should not trigger."""
        live   = {"a": 10.0, "b": 12.0, "c": 5.0}
        static = {"a": 3.5,  "b": 4.0,  "c": 5.0}  # a diverges 650 bps, b 800 bps
        eb = EmergencyBreakers()
        r = eb.check_eb02_oracle_cascade(live, static)
        assert r["verdict"] == STATUS_CLEAR

    def test_cascade_3_adapters_halts(self):
        """Exactly 3 adapters diverge > 500 bps → HALT."""
        live   = {"a": 10.0, "b": 12.0, "c": 14.0}
        static = {"a": 3.5,  "b": 4.0,  "c": 4.0}
        eb = EmergencyBreakers()
        r = eb.check_eb02_oracle_cascade(live, static)
        assert r["verdict"] == STATUS_HALT
        assert len(r["diverged"]) == 3

    def test_cascade_more_than_3_halts(self):
        """4 adapters diverge → still HALT."""
        live   = {"a": 10.0, "b": 12.0, "c": 14.0, "d": 16.0}
        static = {"a": 3.5,  "b": 4.0,  "c": 4.0,  "d": 4.0}
        eb = EmergencyBreakers()
        r = eb.check_eb02_oracle_cascade(live, static)
        assert r["verdict"] == STATUS_HALT

    def test_empty_apy_map_skipped(self):
        eb = EmergencyBreakers()
        r = eb.check_eb02_oracle_cascade({}, {"a": 3.5})
        assert r["status"] == CHECK_SKIP

    def test_empty_static_apy_skipped(self):
        eb = EmergencyBreakers()
        r = eb.check_eb02_oracle_cascade({"a": 3.5}, {})
        assert r["status"] == CHECK_SKIP

    def test_no_common_keys_skipped(self):
        eb = EmergencyBreakers()
        r = eb.check_eb02_oracle_cascade({"a": 5.0}, {"b": 5.0})
        assert r["status"] == CHECK_SKIP

    def test_custom_cascade_threshold(self):
        """Custom: 2 adapters required, 200 bps threshold."""
        eb = EmergencyBreakers(
            oracle_divergence_cascade_bps=200,
            oracle_cascade_min_adapters=2,
        )
        live   = {"a": 7.5, "b": 8.0}
        static = {"a": 4.0, "b": 4.5}  # both diverge 350 bps > 200
        r = eb.check_eb02_oracle_cascade(live, static)
        assert r["verdict"] == STATUS_HALT

    def test_divergence_exactly_at_threshold_does_not_trigger(self):
        """Divergence == 500 bps (not strictly greater) → does not count."""
        live   = {"a": 8.5, "b": 9.0, "c": 9.5}
        static = {"a": 3.5, "b": 4.0, "c": 4.5}  # exactly 500 bps each
        eb = EmergencyBreakers()
        r = eb.check_eb02_oracle_cascade(live, static)
        # 500 bps not > 500 bps → none diverged → CLEAR
        assert r["verdict"] == STATUS_CLEAR


# ═════════════════════════════════════════════════════════════════════════════
# Section 4: EB-03 — Gas Crisis
# ═════════════════════════════════════════════════════════════════════════════

class TestEB03GasCrisis:
    def test_normal_gas_ok(self):
        eb = EmergencyBreakers()
        r = eb.check_eb03_gas_crisis(10.0)
        assert r["status"] == CHECK_PASS
        assert r["verdict"] == STATUS_CLEAR

    def test_crisis_gas_pauses(self):
        eb = EmergencyBreakers()
        r = eb.check_eb03_gas_crisis(75.0)
        assert r["status"] == CHECK_FAIL
        assert r["verdict"] == STATUS_PAUSE

    def test_boundary_exactly_threshold_passes(self):
        """Gas == 50 Gwei (not strictly greater) → CLEAR."""
        eb = EmergencyBreakers()
        r = eb.check_eb03_gas_crisis(50.0)
        assert r["verdict"] == STATUS_CLEAR

    def test_boundary_just_above_threshold_pauses(self):
        eb = EmergencyBreakers()
        r = eb.check_eb03_gas_crisis(50.01)
        assert r["verdict"] == STATUS_PAUSE

    def test_zero_gas_skipped(self):
        """Gas of 0 means no data provided → skip."""
        eb = EmergencyBreakers()
        r = eb.check_eb03_gas_crisis(0.0)
        assert r["status"] == CHECK_SKIP

    def test_negative_gas_skipped(self):
        eb = EmergencyBreakers()
        r = eb.check_eb03_gas_crisis(-5.0)
        assert r["status"] == CHECK_SKIP

    def test_nan_gas_skipped(self):
        eb = EmergencyBreakers()
        r = eb.check_eb03_gas_crisis(float("nan"))
        assert r["status"] == CHECK_SKIP

    def test_custom_gas_threshold(self):
        eb = EmergencyBreakers(gas_crisis_gwei=20.0)
        r = eb.check_eb03_gas_crisis(25.0)
        assert r["verdict"] == STATUS_PAUSE

    def test_result_contains_value(self):
        eb = EmergencyBreakers()
        r = eb.check_eb03_gas_crisis(15.0)
        assert r["value"] == 15.0


# ═════════════════════════════════════════════════════════════════════════════
# Section 5: EB-04 — Equity Flash Crash
# ═════════════════════════════════════════════════════════════════════════════

class TestEB04FlashCrash:
    def test_normal_change_ok(self):
        history = [_eq_bar(100_000), _eq_bar(100_100)]
        eb = EmergencyBreakers()
        r = eb.check_eb04_flash_crash(history)
        assert r["status"] == CHECK_PASS
        assert r["verdict"] == STATUS_CLEAR

    def test_flash_crash_halts(self):
        history = [_eq_bar(100_000), _eq_bar(80_000)]  # 20% drop
        eb = EmergencyBreakers()
        r = eb.check_eb04_flash_crash(history)
        assert r["status"] == CHECK_FAIL
        assert r["verdict"] == STATUS_HALT
        assert r["drop_pct"] == pytest.approx(20.0, rel=1e-3)

    def test_boundary_exactly_threshold_passes(self):
        """Drop == 15 % (not strictly greater) → PASS."""
        history = [_eq_bar(100_000), _eq_bar(85_000)]
        eb = EmergencyBreakers()
        r = eb.check_eb04_flash_crash(history)
        assert r["verdict"] == STATUS_CLEAR

    def test_just_above_threshold_halts(self):
        history = [_eq_bar(100_000), _eq_bar(84_999)]
        eb = EmergencyBreakers()
        r = eb.check_eb04_flash_crash(history)
        assert r["verdict"] == STATUS_HALT

    def test_single_entry_ok(self):
        """Need ≥ 2 bars — single bar returns SKIP."""
        eb = EmergencyBreakers()
        r = eb.check_eb04_flash_crash([_eq_bar(100_000)])
        assert r["status"] == CHECK_SKIP
        assert r["verdict"] == STATUS_CLEAR

    def test_empty_history_skipped(self):
        eb = EmergencyBreakers()
        r = eb.check_eb04_flash_crash([])
        assert r["status"] == CHECK_SKIP

    def test_equity_gain_does_not_trigger(self):
        """Equity rising → drop_pct < 0 → no crash."""
        history = [_eq_bar(100_000), _eq_bar(130_000)]
        eb = EmergencyBreakers()
        r = eb.check_eb04_flash_crash(history)
        assert r["verdict"] == STATUS_CLEAR

    def test_missing_equity_in_bar_skipped(self):
        history = [{"timestamp": "2026-06-10"}, {"timestamp": "2026-06-11"}]
        eb = EmergencyBreakers()
        r = eb.check_eb04_flash_crash(history)
        assert r["status"] == CHECK_SKIP

    def test_custom_flash_crash_threshold(self):
        eb = EmergencyBreakers(equity_flash_crash_pct=5.0)
        history = [_eq_bar(100_000), _eq_bar(93_000)]  # 7% drop > 5%
        r = eb.check_eb04_flash_crash(history)
        assert r["verdict"] == STATUS_HALT

    def test_result_contains_prev_curr_equity(self):
        history = [_eq_bar(100_000), _eq_bar(90_000)]
        eb = EmergencyBreakers()
        r = eb.check_eb04_flash_crash(history)
        assert r["prev_eq"] == pytest.approx(100_000.0)
        assert r["curr_eq"] == pytest.approx(90_000.0)

    def test_long_history_uses_last_two_bars(self):
        """Only the last two bars matter."""
        history = _normal_history(10)
        # Inject a crash at the very end
        history.append(_eq_bar(1.0))  # catastrophic drop from ~100_900 to 1
        eb = EmergencyBreakers()
        r = eb.check_eb04_flash_crash(history)
        assert r["verdict"] == STATUS_HALT


# ═════════════════════════════════════════════════════════════════════════════
# Section 6: EB-05 — Data Corruption
# ═════════════════════════════════════════════════════════════════════════════

class TestEB05DataCorruption:
    def test_clean_history_passes(self):
        eb = EmergencyBreakers()
        r = eb.check_eb05_data_corruption(_normal_history())
        assert r["status"] == CHECK_PASS
        assert r["verdict"] == STATUS_CLEAR

    def test_negative_equity_halts(self):
        history = _normal_history(3)
        history.append(_eq_bar(-500.0, "2026-06-13T08:00:00+00:00"))
        eb = EmergencyBreakers()
        r = eb.check_eb05_data_corruption(history)
        assert r["verdict"] == STATUS_HALT
        assert r["corruption_count"] >= 1

    def test_nan_equity_halts(self):
        history = [_eq_bar(100_000), _eq_bar(float("nan"))]
        eb = EmergencyBreakers()
        r = eb.check_eb05_data_corruption(history)
        assert r["verdict"] == STATUS_HALT

    def test_infinite_equity_halts(self):
        history = [_eq_bar(100_000), _eq_bar(float("inf"))]
        eb = EmergencyBreakers()
        r = eb.check_eb05_data_corruption(history)
        assert r["verdict"] == STATUS_HALT

    def test_nonmonotonic_timestamps_halts(self):
        history = [
            _eq_bar(100_000, "2026-06-12T08:00:00+00:00"),
            _eq_bar(100_100, "2026-06-11T08:00:00+00:00"),  # earlier timestamp
        ]
        eb = EmergencyBreakers()
        r = eb.check_eb05_data_corruption(history)
        assert r["verdict"] == STATUS_HALT

    def test_empty_history_skipped(self):
        eb = EmergencyBreakers()
        r = eb.check_eb05_data_corruption([])
        assert r["status"] == CHECK_SKIP

    def test_no_timestamps_no_monotonic_error(self):
        """History without timestamps should pass EB-05 (no ts → no ts check)."""
        history = [_eq_bar(100_000), _eq_bar(100_100)]
        eb = EmergencyBreakers()
        r = eb.check_eb05_data_corruption(history)
        assert r["verdict"] == STATUS_CLEAR

    def test_multiple_corruptions_all_counted(self):
        history = [
            _eq_bar(100_000, "2026-06-10T08:00:00+00:00"),
            _eq_bar(-500.0,  "2026-06-11T08:00:00+00:00"),  # negative
            _eq_bar(float("nan"), "2026-06-10T08:00:00+00:00"),  # NaN + non-monotonic
        ]
        eb = EmergencyBreakers()
        r = eb.check_eb05_data_corruption(history)
        assert r["verdict"] == STATUS_HALT
        assert r["corruption_count"] >= 2

    def test_legacy_equity_key_accepted(self):
        """Bars using ``equity`` key (not ``close_equity``) should be checked."""
        history = [
            {"equity": 100_000, "timestamp": "2026-06-10T08:00:00+00:00"},
            {"equity": -1.0,    "timestamp": "2026-06-11T08:00:00+00:00"},
        ]
        eb = EmergencyBreakers()
        r = eb.check_eb05_data_corruption(history)
        assert r["verdict"] == STATUS_HALT

    def test_single_valid_bar_passes(self):
        eb = EmergencyBreakers()
        r = eb.check_eb05_data_corruption([_eq_bar(100_000)])
        assert r["verdict"] == STATUS_CLEAR


# ═════════════════════════════════════════════════════════════════════════════
# Section 7: Precedence helper (_max_status)
# ═════════════════════════════════════════════════════════════════════════════

class TestMaxStatus:
    def test_halt_beats_clear(self):
        assert _max_status(STATUS_HALT, STATUS_CLEAR) == STATUS_HALT

    def test_halt_beats_pause(self):
        assert _max_status(STATUS_HALT, STATUS_PAUSE) == STATUS_HALT

    def test_pause_beats_clear(self):
        assert _max_status(STATUS_CLEAR, STATUS_PAUSE) == STATUS_PAUSE

    def test_same_status_returns_same(self):
        assert _max_status(STATUS_HALT, STATUS_HALT) == STATUS_HALT
        assert _max_status(STATUS_CLEAR, STATUS_CLEAR) == STATUS_CLEAR

    def test_order_independent_halt_pause(self):
        assert _max_status(STATUS_PAUSE, STATUS_HALT) == STATUS_HALT


# ═════════════════════════════════════════════════════════════════════════════
# Section 8: _bar_equity helper
# ═════════════════════════════════════════════════════════════════════════════

class TestBarEquity:
    def test_close_equity_key(self):
        assert _bar_equity({"close_equity": 100_000.0}) == pytest.approx(100_000.0)

    def test_equity_key_fallback(self):
        assert _bar_equity({"equity": 99_000.0}) == pytest.approx(99_000.0)

    def test_close_equity_preferred_over_equity(self):
        assert _bar_equity({"close_equity": 1.0, "equity": 2.0}) == pytest.approx(1.0)

    def test_missing_keys_returns_none(self):
        assert _bar_equity({"timestamp": "2026-06-10"}) is None

    def test_non_numeric_returns_none(self):
        assert _bar_equity({"close_equity": "bad"}) is None

    def test_none_value_returns_none(self):
        assert _bar_equity({"close_equity": None}) is None


# ═════════════════════════════════════════════════════════════════════════════
# Section 9: save_result — atomic write
# ═════════════════════════════════════════════════════════════════════════════

class TestSaveResult:
    def test_save_result_creates_file(self, tmp_path):
        eb = EmergencyBreakers()
        result = eb.check_all(apy_map=NORMAL_APY, equity_history=_normal_history())
        eb.save_result(result, data_dir=tmp_path)
        target = tmp_path / "emergency_status.json"
        assert target.exists()

    def test_save_result_valid_json(self, tmp_path):
        eb = EmergencyBreakers()
        result = eb.check_all(apy_map=NORMAL_APY, equity_history=_normal_history())
        eb.save_result(result, data_dir=tmp_path)
        data = json.loads((tmp_path / "emergency_status.json").read_text())
        assert data["status"] == STATUS_CLEAR

    def test_save_result_atomic_no_tmp_files(self, tmp_path):
        eb = EmergencyBreakers()
        result = eb.check_all(apy_map=NORMAL_APY, equity_history=_normal_history())
        eb.save_result(result, data_dir=tmp_path)
        # No .tmp files should remain
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == []

    def test_save_result_overwrites_existing(self, tmp_path):
        eb = EmergencyBreakers()
        result1 = {"status": STATUS_CLEAR, "checked_at": "first", "triggered": [],
                   "checks": {}}
        eb.save_result(result1, data_dir=tmp_path)
        result2 = {"status": STATUS_HALT, "checked_at": "second", "triggered": ["EB-01"],
                   "checks": {}}
        eb.save_result(result2, data_dir=tmp_path)
        data = json.loads((tmp_path / "emergency_status.json").read_text())
        assert data["status"] == STATUS_HALT

    def test_save_result_creates_dir_if_missing(self, tmp_path):
        subdir = tmp_path / "new_subdir"
        eb = EmergencyBreakers()
        result = {"status": STATUS_CLEAR, "checked_at": "t", "triggered": [], "checks": {}}
        eb.save_result(result, data_dir=subdir)
        assert (subdir / "emergency_status.json").exists()

    def test_save_result_does_not_raise_on_io_error(self, tmp_path):
        """save_result should swallow I/O errors gracefully (never raises)."""
        eb = EmergencyBreakers()
        result = {"status": STATUS_CLEAR, "checked_at": "t", "triggered": [], "checks": {}}
        # Pass a file path as data_dir — mkdir will fail on existing file
        bad_dir = tmp_path / "file.txt"
        bad_dir.write_text("I am a file, not a directory")
        # Should log WARNING but not raise
        eb.save_result(result, data_dir=bad_dir)  # no exception


# ═════════════════════════════════════════════════════════════════════════════
# Section 10: Constructor overrides
# ═════════════════════════════════════════════════════════════════════════════

class TestConstructorOverrides:
    def test_default_thresholds_are_class_values(self):
        eb = EmergencyBreakers()
        assert eb.apy_exploit_threshold_pct == EmergencyBreakers.APY_EXPLOIT_THRESHOLD_PCT
        assert eb.oracle_divergence_cascade_bps == EmergencyBreakers.ORACLE_DIVERGENCE_CASCADE_BPS
        assert eb.oracle_cascade_min_adapters == EmergencyBreakers.ORACLE_CASCADE_MIN_ADAPTERS
        assert eb.gas_crisis_gwei == EmergencyBreakers.GAS_CRISIS_GWEI
        assert eb.equity_flash_crash_pct == EmergencyBreakers.EQUITY_FLASH_CRASH_PCT

    def test_all_thresholds_overridable(self):
        eb = EmergencyBreakers(
            apy_exploit_threshold_pct=50.0,
            oracle_divergence_cascade_bps=200.0,
            oracle_cascade_min_adapters=2,
            gas_crisis_gwei=10.0,
            equity_flash_crash_pct=5.0,
        )
        assert eb.apy_exploit_threshold_pct == 50.0
        assert eb.oracle_divergence_cascade_bps == 200.0
        assert eb.oracle_cascade_min_adapters == 2
        assert eb.gas_crisis_gwei == 10.0
        assert eb.equity_flash_crash_pct == 5.0

    def test_partial_override(self):
        eb = EmergencyBreakers(gas_crisis_gwei=15.0)
        assert eb.gas_crisis_gwei == 15.0
        assert eb.apy_exploit_threshold_pct == 100.0  # default unchanged


# ═════════════════════════════════════════════════════════════════════════════
# Section 11: Integration scenarios
# ═════════════════════════════════════════════════════════════════════════════

class TestIntegrationScenarios:
    def test_exploit_scenario_full_pipeline(self):
        """Simulate an exploit: one adapter suddenly reports 500% APY."""
        eb = EmergencyBreakers()
        apy_map = {"aave_v3": 500.0, "compound_v3": 4.8}
        result = eb.check_all(
            apy_map=apy_map,
            equity_history=_normal_history(),
            gas_gwei=5.0,
            static_apy=STATIC_APY,
        )
        assert result["status"] == STATUS_HALT
        assert "EB-01" in result["triggered"]

    def test_gas_spike_only_pauses(self):
        eb = EmergencyBreakers()
        result = eb.check_all(
            apy_map=NORMAL_APY,
            equity_history=_normal_history(),
            gas_gwei=100.0,
        )
        assert result["status"] == STATUS_PAUSE
        assert result["triggered"] == ["EB-03"]

    def test_data_corruption_scenario(self):
        """Simulate equity file with NaN values."""
        history = _normal_history(5)
        history[3] = _eq_bar(float("nan"), "2026-06-13T08:00:00+00:00")
        eb = EmergencyBreakers()
        result = eb.check_all(
            apy_map=NORMAL_APY,
            equity_history=history,
        )
        assert result["status"] == STATUS_HALT
        assert "EB-05" in result["triggered"]

    def test_all_checks_have_id_field(self):
        eb = EmergencyBreakers()
        result = eb.check_all(apy_map=NORMAL_APY, equity_history=_normal_history())
        for code, chk in result["checks"].items():
            assert "id" in chk, f"Missing 'id' in {code}"
            assert chk["id"].startswith("EB-"), f"Bad id in {code}: {chk['id']}"

    def test_all_checks_have_verdict_field(self):
        eb = EmergencyBreakers()
        result = eb.check_all(apy_map=NORMAL_APY, equity_history=_normal_history())
        for code, chk in result["checks"].items():
            assert "verdict" in chk, f"Missing 'verdict' in {code}"
            assert chk["verdict"] in (STATUS_CLEAR, STATUS_HALT, STATUS_PAUSE)
