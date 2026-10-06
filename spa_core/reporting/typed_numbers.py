"""spa_core/reporting/typed_numbers.py — C2 typed public numbers (ADR-580, C2).

RM-TRUTH-01's ADR-580 extends the existing ``kind`` field of the site-numbers shelf
(``.claude/rules/site-numbers.md``: замер/решение) with three more kinds for the
Python producers that feed the public/owner surfaces straight from live state
(``books_summary``, ``/api/health-public``, ``/api/ssot/facts``) rather than through
the weekly shelf: ``REALIZED_PAPER``, ``OBSERVED``, ``BACKTEST``, ``TARGET``,
``MODELLED``. The site shelf's own ``kind`` vocabulary is untouched — this module
is the ONE place Python producers name these kinds, so a second informal spelling
of the same idea (the exact defect C1 forbids) does not grow in each producer file.

Two refusals this module exists to make CHEAP to add, because RM-TRUTH-01's audit
(``docs/rm_truth/A3_product.md`` §2.1 row 19, D5) found a live case of each:

  1. A BACKTEST number (``tier1_packages.blended_net_apy_pct``) reaching the public
     shelf tagged ``kind: замер`` — i.e. a BACKTEST value stamped as a measurement.
     ``typed_pct(..., metric_type="REALIZED_PAPER", source_kind="BACKTEST")`` refuses.
  2. The "higher-risk package shows a lower realized %" inversion being read as a
     policy breach, when no ADR requires REALIZED numbers to be monotone in risk —
     only the TARGET ladder (6/12/20%, ADR-OWN-2026-07 / ADR-548 item 6a) carries
     that claim. ``target_ladder_conflicts`` evaluates monotonicity ONLY over
     TARGET-typed values, never over REALIZED_PAPER ones.

LLM forbidden. Pure stdlib, no I/O.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from typing import Any, Optional

#: The five kinds this contract recognises for a typed PERCENT number. Comparing or
#: ranking across kinds is refused everywhere in this module — that is the point.
METRIC_TYPES = frozenset({"REALIZED_PAPER", "OBSERVED", "BACKTEST", "TARGET", "MODELLED"})

#: Risk order, increasing — ADR-125 ("agression = concentration + wide drawdown
#: budget, NOT directional risk") still orders the three public profiles this way;
#: ADR-OWN-2026-07 / ADR-548 item 6a is the decision that gives them a TARGET ladder
#: at all (6/12/20%).
RISK_ORDER: tuple[str, ...] = ("conservative", "balanced", "aggressive")


class TypeViolation(ValueError):
    """Raised when a producer tries to emit a number this contract forbids."""


def typed_pct(
    value: Optional[float],
    *,
    metric_type: str,
    window_days: Optional[int] = None,
    annualisation: Optional[str] = None,
    as_of: Optional[str] = None,
    source: Optional[str] = None,
    reportable: bool = True,
    reportable_after: Optional[int] = None,
    source_kind: Optional[str] = None,
) -> dict[str, Any]:
    """Build one typed-number envelope: ``{value, metric_type, window_days,
    annualisation, as_of, source, reportable, reportable_after}``.

    Refuses (raises :class:`TypeViolation`) a ``REALIZED_PAPER``/``OBSERVED`` claim
    whose own *source_kind* names it as ``BACKTEST``/``TARGET``/``MODELLED`` — the C2
    rule that a backtest or a target can never carry the "already happened" label.
    *source_kind* is optional and only present when the caller itself is relaying a
    value whose provenance it knows is one of the non-measured kinds; a caller with
    no reason to doubt its own value passes nothing and nothing is checked.

    This function does not gate MATURITY — a caller below ``reportable_after`` must
    already pass ``value=None`` (invariant #17: absence is a distinct value, decided
    by the caller who knows the maturity rule); ``reportable`` here only records that
    decision so a reader does not have to re-derive "is this printable" from a raw
    None.
    """
    if metric_type not in METRIC_TYPES:
        raise TypeViolation(f"unknown metric_type {metric_type!r}; one of {sorted(METRIC_TYPES)}")
    if source_kind is not None and source_kind not in METRIC_TYPES:
        raise TypeViolation(f"unknown source_kind {source_kind!r}; one of {sorted(METRIC_TYPES)}")
    if metric_type in ("REALIZED_PAPER", "OBSERVED") and source_kind in ("BACKTEST", "TARGET", "MODELLED"):
        raise TypeViolation(
            f"refused: a {source_kind} number cannot be stamped {metric_type} (ADR-580 C2) — "
            f"source={source!r}"
        )
    return {
        "value": value,
        "metric_type": metric_type,
        "window_days": window_days,
        "annualisation": annualisation,
        "as_of": as_of,
        "source": source,
        "reportable": bool(reportable) and value is not None,
        "reportable_after": reportable_after,
    }


def compare_typed(a: dict, b: dict) -> dict:
    """Compare two :func:`typed_pct` envelopes.

    Refuses (``comparable: False``) unless both carry the SAME ``metric_type`` AND
    the SAME ``reportable`` — "comparison is only within one type AND one
    reportability" (ADR-580 C2). Never compares a missing value either side."""
    if not (isinstance(a, dict) and isinstance(b, dict)):
        return {"comparable": False, "reason": "not_a_typed_number"}
    if a.get("metric_type") != b.get("metric_type"):
        return {"comparable": False, "reason": "metric_type_mismatch"}
    if bool(a.get("reportable")) != bool(b.get("reportable")):
        return {"comparable": False, "reason": "reportability_mismatch"}
    av, bv = a.get("value"), b.get("value")
    if not isinstance(av, (int, float)) or not isinstance(bv, (int, float)):
        return {"comparable": False, "reason": "value_missing"}
    higher = "a" if av > bv else ("b" if bv > av else "equal")
    return {"comparable": True, "reason": None, "higher": higher}


def target_ladder_conflicts(targets: dict[str, dict]) -> dict:
    """Monotonicity check over TARGET-typed values keyed by tier name, in
    :data:`RISK_ORDER`.

    Evaluated ONLY against ``metric_type == "TARGET"`` entries — the inversion
    RM-TRUTH-01 found live (A3 §2: Balanced/Aggressive REALIZED_PAPER below
    Conservative) is NOT a ladder conflict by this function, because no ADR
    requires realized numbers to be monotone in risk; only the TARGET ladder does
    (ADR-OWN-2026-07, ADR-548 item 6a). Mixing a non-TARGET value into the input is
    refused structurally: ``ok: None`` names which keys are not TARGET, rather than
    silently comparing them.

    Returns ``{"ok": bool | None, "conflicts": [...]}`` — ``ok`` is ``None`` (not a
    verdict) when the input itself is not all-TARGET; a conflict entry names the
    lower-risk/higher-risk pair and both values.
    """
    non_target = sorted(
        k for k, v in targets.items()
        if isinstance(v, dict) and v.get("metric_type") != "TARGET"
    )
    if non_target:
        return {"ok": None, "reason": f"non-TARGET values given: {non_target}", "conflicts": []}
    ordered = [(k, targets[k].get("value")) for k in RISK_ORDER if k in targets]
    conflicts = []
    for (lo_key, lo_val), (hi_key, hi_val) in zip(ordered, ordered[1:]):
        if not isinstance(lo_val, (int, float)) or not isinstance(hi_val, (int, float)):
            continue
        if hi_val <= lo_val:
            conflicts.append({
                "lower_risk": lo_key, "higher_risk": hi_key,
                "lower_risk_target_pct": lo_val, "higher_risk_target_pct": hi_val,
            })
    return {"ok": not conflicts, "conflicts": conflicts}
