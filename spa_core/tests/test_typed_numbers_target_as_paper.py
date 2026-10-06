"""RM-TRUTH-01 failure-injection census scenario
'TARGET displayed as PAPER'. Exercises the same ADR-580 C2 guard as
test_backtest_number_refused_as_realized_paper / test_target_number_refused_as_observed
in spa_core/tests/test_typed_numbers_contract.py, but for the specific combination
(source_kind=TARGET, metric_type=REALIZED_PAPER) that neither existing test exercises.
"""
import pytest
from spa_core.reporting.typed_numbers import TypeViolation, typed_pct


def test_target_number_refused_as_realized_paper():
    with pytest.raises(TypeViolation):
        typed_pct(12.0, metric_type="REALIZED_PAPER", source="tier_bands.json balanced.band_en",
                  source_kind="TARGET")


def test_target_as_target_is_not_refused_positive_control():
    env = typed_pct(12.0, metric_type="TARGET", source="tier_bands.json balanced.band_en")
    assert env["metric_type"] == "TARGET"
