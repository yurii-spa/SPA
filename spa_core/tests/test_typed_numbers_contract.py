"""spa_core/tests/test_typed_numbers_contract.py — ADR-580 C2 failure-injection tests
(RM-TRUTH-01 W5, task 3).

Three refusals this contract exists to make cheap:
  (a) a TARGET/BACKTEST value cannot be stamped REALIZED_PAPER by a producer;
  (b) (see test_paper_apy_staleness.py) a stale snapshot reports stale, not a
      silently-served old number;
  (c) an ordering/ladder comparison helper refuses to mix metric_type/reportability,
      and the "higher-risk TARGET lower than lower-risk TARGET" check is evaluated
      ONLY against TARGET values.

Each has a positive control (the correct shape passes) so the refusal is proven to
catch the real defect, not merely to always raise (ADR-333: a probe that never
passes is not a probe).
"""
from __future__ import annotations

import pytest

from spa_core.reporting.typed_numbers import (
    TypeViolation,
    compare_typed,
    target_ladder_conflicts,
    typed_pct,
)

# FROZEN-DATE-OK: injected-clock — the single literal date in this file
# ("2026-10-05" passed as `as_of=` to typed_pct) is handed directly to the call as
# an argument (not read back from any container), and `typed_pct` only stores it
# as an opaque passthrough field (grepped: no `datetime.now()`/staleness logic
# anywhere in spa_core/reporting/typed_numbers.py) — the test never asserts
# anything about its age, so no calendar move can flip this test's verdict.


# ─── (a) a BACKTEST/TARGET value cannot be emitted as REALIZED_PAPER ───────────


def test_realized_paper_construction_succeeds_positive_control():
    env = typed_pct(4.9, metric_type="REALIZED_PAPER", window_days=104,
                     annualisation="compound", as_of="2026-10-05",
                     source="data/equity_curve_daily.json", reportable=True)
    assert env["value"] == 4.9
    assert env["metric_type"] == "REALIZED_PAPER"
    assert env["reportable"] is True


def test_backtest_number_refused_as_realized_paper():
    """RM-TRUTH-01 A3 §2.1 row 19 / D5: a live producer stamped a BACKTEST number
    (tier1_packages.blended_net_apy_pct) ``kind: замер`` on the public shelf. This
    is the Python-producer equivalent of that mistake, refused at construction."""
    with pytest.raises(TypeViolation):
        typed_pct(3.7, metric_type="REALIZED_PAPER", source="tier1_packages.blended_net_apy_pct",
                  source_kind="BACKTEST")


def test_target_number_refused_as_observed():
    """Same refusal for OBSERVED, and for the TARGET source — the ladder's own
    6/12/20% numbers (ADR-548 6a) must never be relabeled as something that
    already happened."""
    with pytest.raises(TypeViolation):
        typed_pct(12.0, metric_type="OBSERVED", source="tier_bands.json balanced.band_en",
                  source_kind="TARGET")


def test_target_as_target_is_not_refused_negative_control():
    """A TARGET value stamped TARGET (its own honest kind) is NOT refused — the
    refusal is about the MISLABEL, not about TARGET numbers existing at all."""
    env = typed_pct(12.0, metric_type="TARGET", source="tier_bands.json balanced.band_en")
    assert env["value"] == 12.0
    assert env["metric_type"] == "TARGET"


def test_unknown_metric_type_refused():
    with pytest.raises(TypeViolation):
        typed_pct(1.0, metric_type="ANNUALIZED")  # not one of the five C2 kinds


# ─── (c) compare_typed: same metric_type AND same reportability, or refuse ─────


def test_compare_typed_refuses_cross_type_comparison():
    realized = typed_pct(4.9, metric_type="REALIZED_PAPER", reportable=True)
    target = typed_pct(12.0, metric_type="TARGET", reportable=True)
    result = compare_typed(realized, target)
    assert result["comparable"] is False
    assert result["reason"] == "metric_type_mismatch"


def test_compare_typed_refuses_cross_reportability_comparison():
    reportable = typed_pct(4.9, metric_type="REALIZED_PAPER", reportable=True)
    not_reportable = typed_pct(1.2, metric_type="REALIZED_PAPER", reportable=False)
    result = compare_typed(reportable, not_reportable)
    assert result["comparable"] is False
    assert result["reason"] == "reportability_mismatch"


def test_compare_typed_same_type_same_reportability_compares_positive_control():
    a = typed_pct(4.9, metric_type="REALIZED_PAPER", reportable=True)
    b = typed_pct(1.2, metric_type="REALIZED_PAPER", reportable=True)
    result = compare_typed(a, b)
    assert result["comparable"] is True
    assert result["higher"] == "a"


def test_compare_typed_refuses_when_value_missing():
    a = typed_pct(None, metric_type="REALIZED_PAPER", reportable=False)
    b = typed_pct(4.9, metric_type="REALIZED_PAPER", reportable=False)
    result = compare_typed(a, b)
    assert result["comparable"] is False
    assert result["reason"] == "value_missing"


# ─── (c) target_ladder_conflicts: TARGET-only monotonicity, flags a conflict ───


def _target(v):
    return typed_pct(v, metric_type="TARGET", source="tier_bands.json")


def test_target_ladder_6_12_20_has_no_conflict_positive_control():
    """The REAL ladder (ADR-OWN-2026-07 / ADR-548 6a: up to 6/12/20%) is monotone —
    this is the shape the site actually publishes today."""
    ladder = {"conservative": _target(6.0), "balanced": _target(12.0), "aggressive": _target(20.0)}
    result = target_ladder_conflicts(ladder)
    assert result["ok"] is True
    assert result["conflicts"] == []


def test_target_ladder_conflict_is_flagged_when_higher_risk_target_is_lower():
    """Negative control: a HIGHER-risk tier's TARGET at or below a lower-risk
    tier's TARGET is flagged — this is the shape a monotonicity bug would take,
    on the ladder where the owner's decision DOES require monotonicity."""
    ladder = {"conservative": _target(6.0), "balanced": _target(4.0), "aggressive": _target(20.0)}
    result = target_ladder_conflicts(ladder)
    assert result["ok"] is False
    assert {"lower_risk": "conservative", "higher_risk": "balanced",
            "lower_risk_target_pct": 6.0, "higher_risk_target_pct": 4.0} in result["conflicts"]


def test_realized_paper_inversion_is_not_a_ladder_conflict():
    """RM-TRUTH-01's actual finding (A3 §2: Balanced/Aggressive REALIZED_PAPER
    below Conservative's) must NOT be evaluated by this function at all — no ADR
    requires realized numbers to be monotone in risk (only the TARGET ladder is).
    Feeding REALIZED_PAPER values in is refused structurally, not silently
    'compared and found fine'."""
    realized = {
        "conservative": typed_pct(4.9, metric_type="REALIZED_PAPER"),
        "balanced": typed_pct(-4.36, metric_type="REALIZED_PAPER"),
        "aggressive": typed_pct(1.36, metric_type="REALIZED_PAPER"),
    }
    result = target_ladder_conflicts(realized)
    assert result["ok"] is None
    assert "non-TARGET values given" in result["reason"]
    assert result["conflicts"] == []


def test_target_ladder_ignores_missing_tiers():
    ladder = {"conservative": _target(6.0), "aggressive": _target(20.0)}
    result = target_ladder_conflicts(ladder)
    assert result["ok"] is True
