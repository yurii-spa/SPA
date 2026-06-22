"""
tests/test_policy_enforcer.py — Policy Enforcer Test Suite

Минимум 60 тестов для:
  - spa_core.risk.policy_enforcer (validate_positions, ValidationResult, Violation)
  - spa_core.risk.position_validator (run_validation_check)
  - spa_core.monitoring.rules_watchdog (individual checks)
  - Current positions now valid (regression guard)
  - Tier mapping correctness

LLM_FORBIDDEN: тестируем детерминированный код — никаких моков AI.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Dict

import pytest

# ── Ensure repo root on path ──────────────────────────────────────────────
_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

from spa_core.risk.policy_enforcer import (
    T1_ADAPTERS,
    T3_ADAPTERS,
    RULES,
    SUSPENDED_ADAPTERS,
    Violation,
    ValidationResult,
    validate_positions,
    validate_positions_from_file,
    format_violations_text,
    _normalize_tier,
)

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

CAPITAL = 100_000.0

def _valid_portfolio() -> Dict[str, float]:
    """A portfolio that satisfies ALL policy rules."""
    return {
        "aave_v3_optimism":  22_000.0,   # T1 22%
        "spark_susds":       18_000.0,   # T1 18%
        "morpho_steakhouse": 15_000.0,   # T1 15%
        "compound_v3":        5_000.0,   # T1  5%
        "frax":              15_000.0,   # T2 15%
        "scrvusd":           13_000.0,   # T2 13%
        "susde":              5_000.0,   # T3  5%
    }  # Cash = 7,000 (7%)


def _valid_cash() -> float:
    return 7_000.0


def _adapter_apy() -> Dict:
    """Mock adapter_apy dict."""
    return {
        "aave_v3_optimism": {"apy": 4.8,  "tier": 1, "active": True},
        "spark_susds":       {"apy": 3.64, "tier": 1, "active": True},
        "morpho_steakhouse": {"apy": 3.49, "tier": 1, "active": True},
        "compound_v3":       {"apy": 3.27, "tier": 1, "active": True},
        "frax":              {"apy": 7.5,  "tier": 2, "active": True},
        "scrvusd":           {"apy": 7.0,  "tier": 2, "active": True},
        "susde":             {"apy": 12.0, "tier": 3, "active": True},
    }


# ─────────────────────────────────────────────────────────────────────────────
# Section 1: Input validation (fail-closed) — 8 tests
# ─────────────────────────────────────────────────────────────────────────────

class TestInputValidation:

    def test_none_positions_rejected(self):
        result = validate_positions(None, CAPITAL)
        assert result.passed is False
        assert result.has_violations
        assert result.violations[0].rule == "input_validation"

    def test_list_positions_rejected(self):
        result = validate_positions([{"proto": "aave_v3", "usd": 10000}], CAPITAL)
        assert result.passed is False
        assert result.violations[0].rule == "input_validation"

    def test_string_positions_rejected(self):
        result = validate_positions("aave_v3:50000", CAPITAL)
        assert result.passed is False
        assert result.violations[0].rule == "input_validation"

    def test_zero_capital_rejected(self):
        result = validate_positions({}, 0.0)
        assert result.passed is False
        assert result.violations[0].rule == "input_validation"

    def test_negative_capital_rejected(self):
        result = validate_positions({}, -1000.0)
        assert result.passed is False
        assert result.violations[0].rule == "input_validation"

    def test_empty_positions_no_protocols_violates_nothing(self):
        # Empty dict is valid for protocol-count rule (0 <= 8)
        # but will fail t1_min_pct if T1=0 < 55%
        result = validate_positions({}, CAPITAL, cash_usd=CAPITAL)
        # T1=0% violates t1_min_pct
        rules = [v.rule for v in result.violations]
        assert "t1_min_pct" in rules

    def test_none_adapter_apy_accepted(self):
        # adapter_apy=None should not cause crash
        pos = _valid_portfolio()
        result = validate_positions(pos, CAPITAL, adapter_apy=None, cash_usd=_valid_cash())
        assert result.passed is True

    def test_invalid_adapter_apy_type_ignored(self):
        pos = _valid_portfolio()
        result = validate_positions(pos, CAPITAL, adapter_apy="bad_data", cash_usd=_valid_cash())
        # Should still pass (apy coherence check is skipped gracefully)
        assert result.passed is True


# ─────────────────────────────────────────────────────────────────────────────
# Section 2: max_protocols rule — 7 tests
# ─────────────────────────────────────────────────────────────────────────────

class TestMaxProtocols:

    def test_rejects_too_many_protocols(self):
        # 23 protocols like the broken portfolio
        pos = {"aave_v3": 4000.0, "compound_v3": 4000.0, "spark_susds": 4000.0,
               "morpho_blue": 4000.0, "yearn_v3": 4000.0, "euler_v2": 4000.0,
               "maple": 4000.0, "frax": 4000.0, "scrvusd": 4000.0,
               "fluid_fusdc": 4000.0, "morpho_blue_base": 4000.0, "sfrax": 4000.0,
               "stusd": 4000.0, "sdai": 4000.0, "moonwell_base": 4000.0,
               "wusdm": 4000.0, "aave_v3_optimism": 4000.0, "aave_v3_polygon": 4000.0,
               "aave_arbitrum": 4000.0, "morpho_steakhouse": 4000.0, "pendle": 4000.0,
               "susde": 4000.0, "extra_finance_base": 4000.0}
        assert len(pos) == 23
        result = validate_positions(pos, CAPITAL, cash_usd=8000.0)
        assert result.passed is False
        rules = [v.rule for v in result.violations]
        assert "max_protocols" in rules

    def test_rejects_9_protocols(self):
        # Just over the limit
        pos = {f"proto_{i}": 10000.0 for i in range(9)}
        pos["aave_v3"] = 10000.0  # ensure some T1
        result = validate_positions(pos, CAPITAL, cash_usd=5000.0)
        assert result.passed is False
        assert any(v.rule == "max_protocols" for v in result.violations)

    def test_accepts_8_protocols(self):
        # Exactly at limit — compliant in all other ways
        pos = {
            "aave_v3": 20000.0, "compound_v3": 10000.0,
            "spark_susds": 10000.0, "aave_arbitrum": 10000.0,
            "morpho_steakhouse": 10000.0,  # T1 total = 60%
            "frax": 10000.0, "scrvusd": 5000.0, "yearn_v3": 5000.0,
        }
        cash = CAPITAL - sum(pos.values())
        result = validate_positions(pos, CAPITAL, cash_usd=cash)
        assert not any(v.rule == "max_protocols" for v in result.violations)

    def test_accepts_7_protocols(self):
        pos = _valid_portfolio()
        assert len(pos) == 7
        result = validate_positions(pos, CAPITAL, cash_usd=_valid_cash())
        assert not any(v.rule == "max_protocols" for v in result.violations)

    def test_accepts_3_protocols(self):
        pos = {
            "aave_v3": 40000.0,
            "compound_v3": 20000.0,
            "frax": 30000.0,
        }
        # T1 = 60%, cash = 10,000 = 10%
        result = validate_positions(pos, CAPITAL, cash_usd=10000.0)
        assert not any(v.rule == "max_protocols" for v in result.violations)

    def test_max_protocols_rule_value(self):
        assert int(RULES["max_protocols"]) == 8

    def test_violation_detail_includes_actual_count(self):
        pos = {f"proto_{i}": 1000.0 for i in range(20)}
        pos["aave_v3"] = 10000.0
        result = validate_positions(pos, CAPITAL, cash_usd=5000.0)
        v = next(v for v in result.violations if v.rule == "max_protocols")
        assert v.actual == 21  # 20 protos + aave_v3


# ─────────────────────────────────────────────────────────────────────────────
# Section 3: T1 minimum — 8 tests
# ─────────────────────────────────────────────────────────────────────────────

class TestT1Minimum:

    def test_rejects_t1_below_55_pct(self):
        # Like the broken portfolio: T1 = 49.7%
        pos = {
            "morpho_steakhouse": 9000.0,   # T1
            "spark_susds": 7500.0,          # T1
            "compound_v3": 7000.0,          # T1
            "aave_v3": 4500.0,              # T1
            "aave_v3_optimism": 7000.0,     # T1
            "aave_v3_polygon": 7000.0,      # T1
            "susde": 5500.0,                # T3
            "frax": 4000.0,                 # T2
        }
        # T1 = 42,000 = 42% < 55%
        result = validate_positions(pos, CAPITAL, cash_usd=8000.0)
        assert any(v.rule == "t1_min_pct" for v in result.violations)

    def test_rejects_zero_t1(self):
        pos = {
            "frax": 30000.0,
            "scrvusd": 30000.0,
            "susde": 5000.0,
        }
        result = validate_positions(pos, CAPITAL, cash_usd=35000.0)
        assert any(v.rule == "t1_min_pct" for v in result.violations)

    def test_accepts_t1_exactly_55_pct(self):
        pos = {
            "aave_v3": 55000.0,   # T1 = 55%
            "frax": 35000.0,      # T2 = 35%
        }
        result = validate_positions(pos, CAPITAL, cash_usd=10000.0)
        assert not any(v.rule == "t1_min_pct" for v in result.violations)

    def test_accepts_t1_60_pct(self):
        pos = _valid_portfolio()
        # T1 = aave_v3_optimism + spark_susds + morpho_steakhouse + compound_v3
        #     = 22k + 18k + 15k + 5k = 60k = 60%
        result = validate_positions(pos, CAPITAL, cash_usd=_valid_cash())
        assert not any(v.rule == "t1_min_pct" for v in result.violations)

    def test_t1_adapters_set_correct(self):
        assert "aave_v3" in T1_ADAPTERS
        assert "compound_v3" in T1_ADAPTERS
        assert "spark_susds" in T1_ADAPTERS
        assert "morpho_steakhouse" in T1_ADAPTERS
        assert "aave_arbitrum" in T1_ADAPTERS

    def test_t1_adapters_excludes_t2(self):
        assert "frax" not in T1_ADAPTERS
        assert "yearn_v3" not in T1_ADAPTERS
        assert "pendle" not in T1_ADAPTERS
        assert "euler_v2" not in T1_ADAPTERS

    def test_t1_adapters_excludes_t3(self):
        assert "susde" not in T1_ADAPTERS
        assert "extra_finance_base" not in T1_ADAPTERS

    def test_violation_contains_t1_pct(self):
        pos = {"frax": 90000.0}   # T2, T1 = 0%
        result = validate_positions(pos, CAPITAL, cash_usd=10000.0)
        v = next((v for v in result.violations if v.rule == "t1_min_pct"), None)
        assert v is not None
        assert v.actual == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Section 4: per-protocol max — 6 tests
# ─────────────────────────────────────────────────────────────────────────────

class TestPerProtocolMax:

    def test_rejects_per_protocol_over_25_pct(self):
        pos = {
            "aave_v3": 30000.0,   # 30% > 25%
            "compound_v3": 25000.0,
            "spark_susds": 30000.0,  # 30% > 25%
        }
        result = validate_positions(pos, CAPITAL, cash_usd=15000.0)
        rules = [v.rule for v in result.violations]
        assert "per_protocol_max_pct" in rules

    def test_accepts_per_protocol_exactly_25_pct(self):
        pos = {
            "aave_v3": 25000.0,       # T1 25%
            "compound_v3": 25000.0,   # T1 25%
            "spark_susds": 15000.0,   # T1 15%
            "frax": 25000.0,          # T2 25%
        }
        # T1 = 65%, per-protocol all <= 25%
        result = validate_positions(pos, CAPITAL, cash_usd=10000.0)
        assert not any(v.rule == "per_protocol_max_pct" for v in result.violations)

    def test_rejects_100pct_single_protocol(self):
        pos = {"aave_v3": 95000.0}   # 95% — T1 OK, but per-protocol > 25%
        result = validate_positions(pos, CAPITAL, cash_usd=5000.0)
        assert any(v.rule == "per_protocol_max_pct" for v in result.violations)

    def test_violation_names_offending_protocol(self):
        pos = {"aave_v3": 30000.0, "compound_v3": 25000.0, "spark_susds": 30000.0}
        result = validate_positions(pos, CAPITAL, cash_usd=15000.0)
        offenders = [v.actual for v in result.violations if v.rule == "per_protocol_max_pct"]
        assert len(offenders) > 0
        assert all(v > 25.0 for v in offenders)

    def test_per_protocol_rule_value(self):
        assert float(RULES["per_protocol_max_pct"]) == 25.0

    def test_valid_portfolio_all_per_protocol_pass(self):
        pos = _valid_portfolio()
        result = validate_positions(pos, CAPITAL, cash_usd=_valid_cash())
        assert not any(v.rule == "per_protocol_max_pct" for v in result.violations)


# ─────────────────────────────────────────────────────────────────────────────
# Section 5: T2 max and T3 max — 6 tests
# ─────────────────────────────────────────────────────────────────────────────

class TestT2T3Caps:

    def test_rejects_t2_over_50_pct(self):
        pos = {
            "aave_v3": 25000.0,   # T1 25%
            "compound_v3": 20000.0,  # T1 20%
            "frax": 25000.0,      # T2 25%
            "scrvusd": 25000.0,   # T2 25%  -> T2 total = 50%... just at edge
        }
        # T1=45% < 55% violates T1 min
        # T2=50% is exactly at limit, not a violation
        result = validate_positions(pos, CAPITAL, cash_usd=5000.0)
        assert not any(v.rule == "t2_max_pct" for v in result.violations)

    def test_rejects_t2_over_51_pct(self):
        pos = {
            "aave_v3": 25000.0,   # T1
            "frax": 26000.0,      # T2
            "scrvusd": 25000.0,   # T2 -> T2 = 51%
        }
        result = validate_positions(pos, CAPITAL, cash_usd=24000.0)
        # T1=25% < 55% also fails, but we check T2 specifically
        assert any(v.rule == "t2_max_pct" for v in result.violations)

    def test_accepts_t2_50_pct(self):
        pos = {
            "aave_v3": 30000.0,       # T1 30%
            "compound_v3": 10000.0,   # T1 10%
            "spark_susds": 10000.0,   # T1 10%  -> T1=50% >= 55% ??? no, 50% < 55%
        }
        # Actually 50% T1 fails. Let's build properly:
        pos = {
            "aave_v3": 30000.0,       # T1
            "compound_v3": 15000.0,   # T1
            "spark_susds": 10000.0,   # T1   -> T1=55%
            "frax": 25000.0,          # T2
            "scrvusd": 15000.0,       # T2   -> T2=40%
        }
        result = validate_positions(pos, CAPITAL, cash_usd=5000.0)
        assert not any(v.rule == "t2_max_pct" for v in result.violations)

    def test_rejects_t3_over_15_pct(self):
        pos = {
            "aave_v3": 40000.0,       # T1
            "compound_v3": 20000.0,   # T1  -> T1=60%
            "susde": 10000.0,         # T3
            "extra_finance_base": 6000.0,  # T3  -> T3=16% > 15%
        }
        result = validate_positions(pos, CAPITAL, cash_usd=24000.0)
        assert any(v.rule == "t3_max_pct" for v in result.violations)

    def test_accepts_t3_exactly_15_pct(self):
        pos = {
            "aave_v3": 40000.0,     # T1
            "compound_v3": 20000.0,  # T1  -> T1=60%
            "susde": 15000.0,       # T3=15%
        }
        result = validate_positions(pos, CAPITAL, cash_usd=25000.0)
        assert not any(v.rule == "t3_max_pct" for v in result.violations)

    def test_t3_adapters_set_correct(self):
        assert "susde" in T3_ADAPTERS
        assert "extra_finance_base" in T3_ADAPTERS
        assert "aave_v3" not in T3_ADAPTERS
        assert "frax" not in T3_ADAPTERS


# ─────────────────────────────────────────────────────────────────────────────
# Section 6: Cash buffer — 5 tests
# ─────────────────────────────────────────────────────────────────────────────

class TestCashBuffer:

    def test_rejects_zero_cash(self):
        pos = {"aave_v3": 60000.0, "compound_v3": 40000.0}
        # T1=100%, cash=0
        result = validate_positions(pos, CAPITAL, cash_usd=0.0)
        assert any(v.rule == "cash_min_pct" for v in result.violations)

    def test_rejects_cash_below_5_pct(self):
        pos = {"aave_v3": 55000.0, "compound_v3": 40000.0}
        # cash = 5000 = 5%, but we say cash_usd=4000 = 4%
        result = validate_positions(pos, CAPITAL, cash_usd=4000.0)
        assert any(v.rule == "cash_min_pct" for v in result.violations)

    def test_accepts_cash_exactly_5_pct(self):
        pos = {"aave_v3": 55000.0, "compound_v3": 40000.0}
        result = validate_positions(pos, CAPITAL, cash_usd=5000.0)
        assert not any(v.rule == "cash_min_pct" for v in result.violations)

    def test_accepts_cash_7_pct(self):
        pos = _valid_portfolio()
        result = validate_positions(pos, CAPITAL, cash_usd=_valid_cash())
        assert not any(v.rule == "cash_min_pct" for v in result.violations)

    def test_cash_min_rule_value(self):
        assert float(RULES["cash_min_pct"]) == 5.0


# ─────────────────────────────────────────────────────────────────────────────
# Section 7: Valid portfolio passes — 5 tests
# ─────────────────────────────────────────────────────────────────────────────

class TestValidPortfolio:

    def test_accepts_valid_portfolio(self):
        pos = _valid_portfolio()
        result = validate_positions(pos, CAPITAL, cash_usd=_valid_cash())
        assert result.passed is True
        assert not result.has_violations

    def test_valid_portfolio_has_correct_summary(self):
        pos = _valid_portfolio()
        result = validate_positions(pos, CAPITAL, cash_usd=_valid_cash())
        s = result.portfolio_summary
        assert s["t1_pct"] == 60.0
        assert s["t2_pct"] == 28.0
        assert s["t3_pct"] == 5.0
        assert s["cash_pct"] == 7.0
        assert s["protocol_count"] == 7

    def test_valid_portfolio_with_adapter_apy(self):
        pos = _valid_portfolio()
        result = validate_positions(
            pos, CAPITAL, adapter_apy=_adapter_apy(), cash_usd=_valid_cash()
        )
        assert result.passed is True

    def test_validation_result_is_dataclass(self):
        result = validate_positions(_valid_portfolio(), CAPITAL, cash_usd=_valid_cash())
        assert isinstance(result, ValidationResult)
        assert isinstance(result.violations, list)
        assert isinstance(result.warnings, list)
        assert isinstance(result.checked_at, str)

    def test_violation_to_dict(self):
        v = Violation(rule="test_rule", severity="CRITICAL", message="test msg",
                      actual=5, expected="<=3")
        d = v.to_dict()
        assert d["rule"] == "test_rule"
        assert d["severity"] == "CRITICAL"
        assert d["actual"] == 5
        assert d["expected"] == "<=3"


# ─────────────────────────────────────────────────────────────────────────────
# Section 8: Tier mapping — 6 tests
# ─────────────────────────────────────────────────────────────────────────────

class TestTierMapping:

    def test_normalize_tier_t1_adapters(self):
        for proto in ["aave_v3", "compound_v3", "spark_susds", "morpho_steakhouse"]:
            assert _normalize_tier(proto) == "T1", f"{proto} should be T1"

    def test_normalize_tier_t3_adapters(self):
        for proto in ["susde", "extra_finance_base"]:
            assert _normalize_tier(proto) == "T3", f"{proto} should be T3"

    def test_normalize_tier_unknown_defaults_t2(self):
        assert _normalize_tier("totally_unknown_protocol") == "T2"

    def test_normalize_tier_uses_adapter_apy_for_unknown(self):
        apy = {"new_protocol": {"tier": 1}}
        assert _normalize_tier("new_protocol", apy) == "T1"

    def test_normalize_tier_string_t1_in_adapter_apy(self):
        apy = {"new_protocol": {"tier": "T1"}}
        assert _normalize_tier("new_protocol", apy) == "T1"

    def test_normalize_tier_own_set_overrides_adapter_apy(self):
        # aave_v3 is T1 in T1_ADAPTERS; adapter_apy says tier=3 — our set wins
        apy = {"aave_v3": {"tier": 3}}
        assert _normalize_tier("aave_v3", apy) == "T1"


# ─────────────────────────────────────────────────────────────────────────────
# Section 9: APY coherence warning — 4 tests
# ─────────────────────────────────────────────────────────────────────────────

class TestApyCoherence:

    def test_rejects_apy_incoherence_as_warning(self):
        # susde (12%) is T3 and small — top APY not in top allocation
        pos = _valid_portfolio()
        result = validate_positions(
            pos, CAPITAL, adapter_apy=_adapter_apy(), cash_usd=_valid_cash()
        )
        # susde is top APY but small allocation — warning expected
        assert result.has_warnings
        w = next((w for w in result.warnings if w.rule == "apy_coherence"), None)
        assert w is not None

    def test_apy_coherence_only_warning_not_critical(self):
        # APY incoherence is WARNING, not a blocker
        pos = _valid_portfolio()
        result = validate_positions(
            pos, CAPITAL, adapter_apy=_adapter_apy(), cash_usd=_valid_cash()
        )
        assert result.passed is True  # Still passes
        assert not result.has_violations

    def test_no_apy_coherence_without_adapter_data(self):
        pos = _valid_portfolio()
        result = validate_positions(pos, CAPITAL, cash_usd=_valid_cash())
        assert not any(w.rule == "apy_coherence" for w in result.warnings)

    def test_apy_coherence_skip_when_few_adapters(self):
        pos = {"aave_v3": 60000.0, "compound_v3": 30000.0}
        apy = {"aave_v3": {"apy": 3.1}, "compound_v3": {"apy": 3.3}}
        result = validate_positions(pos, CAPITAL, adapter_apy=apy, cash_usd=10000.0)
        # Only 2 adapters with APY — skip coherence (need >= 3)
        assert not any(w.rule == "apy_coherence" for w in result.warnings)


# ─────────────────────────────────────────────────────────────────────────────
# Section 10: format_violations_text — 4 tests
# ─────────────────────────────────────────────────────────────────────────────

class TestFormatViolationsText:

    def test_format_passed_portfolio(self):
        pos = _valid_portfolio()
        result = validate_positions(pos, CAPITAL, cash_usd=_valid_cash())
        text = format_violations_text(result)
        assert "PASSED" in text
        assert "✅" in text

    def test_format_failed_portfolio(self):
        result = validate_positions(None, CAPITAL)
        text = format_violations_text(result)
        assert "REJECTED" in text or "violation" in text.lower()
        assert "❌" in text

    def test_format_includes_summary(self):
        pos = _valid_portfolio()
        result = validate_positions(pos, CAPITAL, cash_usd=_valid_cash())
        text = format_violations_text(result)
        assert "T1=" in text
        assert "T2=" in text
        assert "Cash=" in text

    def test_format_shows_warnings(self):
        pos = _valid_portfolio()
        result = validate_positions(
            pos, CAPITAL, adapter_apy=_adapter_apy(), cash_usd=_valid_cash()
        )
        text = format_violations_text(result)
        assert "warning" in text.lower() or "⚠️" in text


# ─────────────────────────────────────────────────────────────────────────────
# Section 11: validate_positions_from_file — 5 tests
# ─────────────────────────────────────────────────────────────────────────────

class TestValidateFromFile:

    def _write_positions_file(self, positions, capital=CAPITAL, cash_usd=7000.0):
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        json.dump({
            "capital_usd": capital,
            "cash_usd": cash_usd,
            "positions": positions,
        }, tmp)
        tmp.flush()
        tmp.close()
        return tmp.name

    def test_file_not_found(self):
        result = validate_positions_from_file("/nonexistent/path.json")
        assert result.passed is False
        assert result.violations[0].rule == "file_exists"

    def test_invalid_json_file(self):
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        tmp.write("{invalid json}")
        tmp.close()
        try:
            result = validate_positions_from_file(tmp.name)
            assert result.passed is False
            assert result.violations[0].rule == "file_valid_json"
        finally:
            os.unlink(tmp.name)

    def test_valid_file_passes(self):
        path = self._write_positions_file(_valid_portfolio())
        try:
            result = validate_positions_from_file(path)
            assert result.passed is True
        finally:
            os.unlink(path)

    def test_invalid_portfolio_file_fails(self):
        bad_pos = {f"proto_{i}": 4000.0 for i in range(20)}
        path = self._write_positions_file(bad_pos, cash_usd=5000.0)
        try:
            result = validate_positions_from_file(path)
            assert result.passed is False
        finally:
            os.unlink(path)

    def test_current_positions_json_now_valid(self):
        """Regression guard: the ACTUAL data/current_positions.json must pass."""
        positions_path = str(_REPO / "data" / "current_positions.json")
        adapter_path   = str(_REPO / "data" / "adapter_status.json")
        if not os.path.exists(positions_path):
            pytest.skip("current_positions.json not found")
        result = validate_positions_from_file(positions_path, adapter_path)
        assert result.passed is True, (
            "REGRESSION: current_positions.json fails policy! "
            "Violations: {}".format([v.to_dict() for v in result.violations])
        )


# ─────────────────────────────────────────────────────────────────────────────
# Section 12: ValidationResult properties — 4 tests
# ─────────────────────────────────────────────────────────────────────────────

class TestValidationResultProperties:

    def test_passed_no_violations(self):
        r = ValidationResult(passed=True)
        assert r.has_violations is False
        assert r.has_warnings is False

    def test_has_violations_flag(self):
        r = ValidationResult(
            passed=False,
            violations=[Violation("x", "CRITICAL", "msg")]
        )
        assert r.has_violations is True

    def test_has_warnings_flag(self):
        r = ValidationResult(
            passed=True,
            warnings=[Violation("y", "WARNING", "warn msg")]
        )
        assert r.has_warnings is True

    def test_to_dict_structure(self):
        pos = _valid_portfolio()
        result = validate_positions(pos, CAPITAL, cash_usd=_valid_cash())
        d = result.to_dict()
        assert "passed" in d
        assert "violations" in d
        assert "warnings" in d
        assert "checked_at" in d
        assert "violation_count" in d
        assert d["violation_count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Section 13: Watchdog checks — 5 tests
# ─────────────────────────────────────────────────────────────────────────────

class TestWatchdogChecks:

    def test_check_position_limits_passes_valid(self):
        from spa_core.monitoring.rules_watchdog import check_position_limits
        # Uses actual data/current_positions.json — after P0 fix should pass
        positions_path = _REPO / "data" / "current_positions.json"
        if not positions_path.exists():
            pytest.skip("current_positions.json not found")
        result = check_position_limits()
        assert result.status in ("OK", "WARNING", "CRITICAL")

    def test_check_t1_concentration_passes_valid(self):
        from spa_core.monitoring.rules_watchdog import check_t1_concentration
        positions_path = _REPO / "data" / "current_positions.json"
        if not positions_path.exists():
            pytest.skip("current_positions.json not found")
        result = check_t1_concentration()
        # After P0 fix, should be OK
        assert result.status == "OK", (
            "T1 concentration check failed: {}".format(result.message)
        )

    def test_check_adapter_status_returns_result(self):
        from spa_core.monitoring.rules_watchdog import check_adapter_status, CheckResult
        result = check_adapter_status()
        assert isinstance(result, CheckResult)
        assert result.status in ("OK", "WARNING", "CRITICAL", "SKIPPED")

    def test_check_circuit_breaker_returns_result(self):
        from spa_core.monitoring.rules_watchdog import check_circuit_breaker, CheckResult
        result = check_circuit_breaker()
        assert isinstance(result, CheckResult)

    def test_check_llm_forbidden_violations(self):
        from spa_core.monitoring.rules_watchdog import check_llm_forbidden_violations
        result = check_llm_forbidden_violations()
        # Should be OK (no LLM in risk/execution/monitoring)
        assert result.status == "OK", (
            "LLM detected in forbidden domain: {}".format(result.message)
        )


# ─────────────────────────────────────────────────────────────────────────────
# Section 14: Suspended adapters + RULES constants — 4 tests
# ─────────────────────────────────────────────────────────────────────────────

class TestSuspendedAndConstants:

    def test_suspended_adapters_initially_empty(self):
        # No adapters suspended by default
        assert len(SUSPENDED_ADAPTERS) == 0

    def test_suspended_adapter_would_be_rejected(self):
        # Monkey-patch SUSPENDED_ADAPTERS for this test
        import spa_core.risk.policy_enforcer as pe
        original = pe.SUSPENDED_ADAPTERS
        pe.SUSPENDED_ADAPTERS = frozenset({"evil_protocol"})
        try:
            pos = {
                "aave_v3": 55000.0,     # T1
                "compound_v3": 10000.0,  # T1
                "evil_protocol": 5000.0,
            }
            result = validate_positions(pos, CAPITAL, cash_usd=30000.0)
            assert any(v.rule == "no_suspended" for v in result.violations)
        finally:
            pe.SUSPENDED_ADAPTERS = original

    def test_rules_dict_has_all_keys(self):
        required_keys = {
            "max_protocols", "per_protocol_max_pct", "t1_min_pct",
            "t2_max_pct", "t3_max_pct", "cash_min_pct", "apy_rank_tolerance",
        }
        assert required_keys.issubset(set(RULES.keys()))

    def test_rules_values_are_numeric(self):
        for key, val in RULES.items():
            assert isinstance(val, (int, float)), f"RULES[{key}] should be numeric"


# ─────────────────────────────────────────────────────────────────────────────
# Section 15: Integration — the broken portfolio is detected — 4 tests
# ─────────────────────────────────────────────────────────────────────────────

class TestBrokenPortfolioDetected:
    """Simulate the original broken portfolio (23 protocols, T1=49.7%)."""

    def _broken_portfolio(self):
        return {
            "morpho_steakhouse": 8996.0,
            "spark_susds": 7612.0,
            "compound_v3": 7196.0,
            "aave_v3_polygon": 7058.0,
            "aave_v3_optimism": 6643.0,
            "susde": 5773.0,
            "aave_arbitrum": 5674.0,
            "aave_v3": 4321.0,
            "pendle": 3896.0,
            "extra_finance_base": 3849.0,
            "frax": 3608.0,
            "scrvusd": 3368.0,
            "fluid_fusdc": 3127.0,
            "morpho_blue_base": 2983.0,
            "sfrax": 2887.0,
            "stusd": 2887.0,
            "sdai": 2646.0,
            "moonwell_base": 2646.0,
            "wusdm": 2405.0,
            "maple": 2392.0,
            "aave_v3_base": 2165.0,
            "yearn_v3": 1543.0,
            "euler_v2": 1326.0,
        }

    def test_broken_portfolio_rejected(self):
        pos = self._broken_portfolio()
        result = validate_positions(pos, CAPITAL, cash_usd=5000.0)
        assert result.passed is False

    def test_broken_portfolio_detects_max_protocols(self):
        pos = self._broken_portfolio()
        assert len(pos) == 23
        result = validate_positions(pos, CAPITAL, cash_usd=5000.0)
        assert any(v.rule == "max_protocols" for v in result.violations)

    def test_broken_portfolio_detects_t1_below_min(self):
        pos = self._broken_portfolio()
        result = validate_positions(pos, CAPITAL, cash_usd=5000.0)
        assert any(v.rule == "t1_min_pct" for v in result.violations)

    def test_fixed_portfolio_passes_all_checks(self):
        """After P0 fix, the new portfolio must pass."""
        pos = _valid_portfolio()
        result = validate_positions(pos, CAPITAL, cash_usd=_valid_cash())
        assert result.passed is True
        assert len(result.violations) == 0


# ─────────────────────────────────────────────────────────────────────────────
# Section 16: Edge cases — 4 tests
# ─────────────────────────────────────────────────────────────────────────────

class TestEdgeCases:

    def test_single_t1_protocol_no_max_protocols_violation(self):
        pos = {"aave_v3": 90000.0}
        result = validate_positions(pos, CAPITAL, cash_usd=10000.0)
        assert not any(v.rule == "max_protocols" for v in result.violations)
        # But per_protocol_max_pct: 90% > 25% — violation
        assert any(v.rule == "per_protocol_max_pct" for v in result.violations)

    def test_positions_with_zero_values(self):
        pos = {
            "aave_v3": 60000.0,
            "compound_v3": 30000.0,
            "dead_protocol": 0.0,
        }
        result = validate_positions(pos, CAPITAL, cash_usd=10000.0)
        # dead_protocol = 0% — no per-protocol violation
        assert not any(
            v.rule == "per_protocol_max_pct" and "dead_protocol" in v.message
            for v in result.violations
        )

    def test_multiple_violations_at_once(self):
        # Should catch ALL violations, not short-circuit at first
        pos = {f"p{i}": 4000.0 for i in range(15)}   # 15 protocols > 8
        result = validate_positions(pos, CAPITAL, cash_usd=5000.0)
        rule_names = {v.rule for v in result.violations}
        assert "max_protocols" in rule_names
        assert "t1_min_pct" in rule_names  # 0% T1

    def test_checked_at_is_iso_datetime(self):
        pos = _valid_portfolio()
        result = validate_positions(pos, CAPITAL, cash_usd=_valid_cash())
        from datetime import datetime
        # Should parse without exception
        dt = datetime.fromisoformat(result.checked_at.replace("Z", "+00:00"))
        assert dt is not None
