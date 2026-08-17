"""
spa_core/alerts/severity.py
===========================
Single source of truth for the red-flag SEVERITY vocabulary (N8).

The red-flag *writer* (``spa_core.alerts.red_flag_monitor``) and every
*consumer* that has to decide "is this red flag a CRITICAL?" must agree on the
exact set of strings that count as critical. Previously each module hard-coded
its own literal:

  * the writer emitted ``"WARN"`` / ``"CRITICAL"``
  * ``system_health_monitor`` matched only the single literal ``"CRITICAL"``
  * ``agent_health_monitor`` matched the SET ``("CRITICAL", "CRIT")``

That drift is a false-negative hazard: the day a writer renames a level (e.g.
``"WARN"`` → ``"WARNING"``, or ``"CRITICAL"`` → ``"CRIT"``/``"FATAL"``) a
single-literal consumer SILENTLY stops detecting real criticals. Centralising
the vocabulary here — and having consumers match against a SET via
``is_critical()`` — means a writer change can only widen detection, never
disable it.

stdlib-only, deterministic, no I/O, LLM-FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import math
from typing import Any

# ─── Canonical severity literals (what the writer emits today) ────────────────
SEV_WARN = "WARN"
SEV_CRITICAL = "CRITICAL"

# Ordered low → high; the writer's canonical output vocabulary.
SEVERITIES: tuple[str, ...] = (SEV_WARN, SEV_CRITICAL)

# ─── Critical-severity SET (what consumers match against) ─────────────────────
# A red flag is "critical" if its (upper-cased) severity is in this set. We
# include synonyms/aliases so that a future writer that switches to any of these
# spellings is still caught. Members are upper-case; callers MUST upper-case the
# raw value before membership testing (use ``is_critical()`` which does this).
CRITICAL_SEVERITIES: frozenset[str] = frozenset({
    "CRITICAL",
    "CRIT",
    "FATAL",
    "SEVERE",
    "EMERGENCY",
})

# ─── Warning-severity SET (advisory / non-paging) ─────────────────────────────
WARNING_SEVERITIES: frozenset[str] = frozenset({
    "WARN",
    "WARNING",
})


def is_critical(severity: Any) -> bool:
    """
    Return True if ``severity`` denotes a critical red flag.

    Matches against the CRITICAL_SEVERITIES SET (case-insensitive), NOT a single
    literal — so a writer changing the exact spelling cannot silently disable
    critical detection. Non-string / None inputs are treated as not-critical
    (fail-OPEN here is wrong for safety, but an unparseable severity is not a
    positive critical signal; callers that need fail-closed should validate the
    schema separately).
    """
    if not isinstance(severity, str):
        return False
    return severity.strip().upper() in CRITICAL_SEVERITIES


def is_warning(severity: Any) -> bool:
    """Return True if ``severity`` denotes a (non-critical) warning."""
    if not isinstance(severity, str):
        return False
    return severity.strip().upper() in WARNING_SEVERITIES


# ─── portfolio_health.json field unification (N8) ─────────────────────────────
# The portfolio-health writer (spa_core.paper_trading.portfolio_monitor) emits
# the key ``health_score`` into data/portfolio_health.json. Two different
# consumers previously read different keys / orders ("score" vs "health_score"),
# so a mismatch read None and silently skipped the health gate. This is the ONE
# helper both consumers call so they always read the ACTUAL key written, in a
# single agreed precedence order.
_PORTFOLIO_HEALTH_SCORE_KEYS: tuple[str, ...] = (
    "health_score",            # canonical key written by portfolio_monitor
    "score",                   # legacy / portfolio_health.py module shape
    "portfolio_health_score",  # alternate alias seen in some emitters
    "overall_score",           # run_health_check() aggregate shape
)


def read_portfolio_health_score(doc: Any) -> float | None:
    """
    Read the portfolio-health score from a loaded portfolio_health.json dict.

    Tries the canonical key first (``health_score``, what the writer emits) and
    falls back through known aliases. Returns a float, or None when no numeric
    score field is present. Booleans are rejected (they are ints in Python but
    never a valid score).
    """
    if not isinstance(doc, dict):
        return None
    for key in _PORTFOLIO_HEALTH_SCORE_KEYS:
        v = doc.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return None


# ─── portfolio_health VERDICT unification ────────────────────────────────────
# Reading the same key was only half the job. Both monitors then classified the
# number INDEPENDENTLY, against the same floor, and disagreed about what the
# result MEANS:
#
#   * system_health_monitor  (d6.health, domain d6_risk_gates): score < 70 -> CRITICAL
#     — and, being the worst check in the domain, it turned the whole SYSTEM
#       verdict CRITICAL;
#   * agent_health_monitor:  the identical score < 70 -> WARNING.
#
# Measured 2026-08-07 on live data: health_score = 69.43 produced "System Health
# 🔴 CRITICAL" next to "Agents ⚠️ WARNING" in SYSTEM_BRIEFING from ONE number,
# with RiskPolicy policy_compliant=true and no gate having refused anything.
# By 08:00 the same score had drifted back to 72.62 on its own (journal W32) —
# i.e. the loudest level in the system was being spent on a flapping composite
# quality score, which is how CRITICAL stops being read literally.
#
# WHY THE AGREED LEVEL IS **WARNING** AND NOT CRITICAL (this is not "painting it
# green" — the floor of 70.0 is UNCHANGED and the score is still reported):
#   1. The number is a COMPOSITE QUALITY SCORE (APY component + risk component +
#      diversification), not a gate refusal. A real d6_risk_gates CRITICAL —
#      concentration-cap breach, T2-cap breach (ADR-019), RiskPolicy refusal,
#      kill-switch — is unaffected by this helper and still CRITICAL.
#   2. Escalating the OTHER way is structurally impossible: agent_health_monitor
#      documents the invariant `critical_count == 0 ⟺ overall_status != CRITICAL`
#      (build_report), and critical_count counts agent-level criticals plus
#      red-flag criticals. A CRITICAL driven by portfolio_health would report
#      overall CRITICAL with critical_count == 0 and break that invariant.
#   Therefore WARNING is the only verdict BOTH monitors can carry consistently.
#
# One number -> one verdict: both monitors call classify_portfolio_health().
PORTFOLIO_HEALTH_FLOOR: float = 70.0

# Status literals used by the classifier. Deliberately plain strings: both
# monitors already use this exact vocabulary ("OK" / "WARNING"), and importing a
# monitor's enum here would invert the dependency direction.
_PH_OK = "OK"
_PH_WARNING = "WARNING"


def classify_portfolio_health(
    score: Any,
    floor: float = PORTFOLIO_HEALTH_FLOOR,
) -> tuple[str, str]:
    """
    Classify a portfolio-health score into the ONE agreed (status, reason).

    Returns
    -------
    (status, reason)
        status is ``"OK"`` or ``"WARNING"`` — never CRITICAL (see the module
        comment above: a composite quality score is not a gate refusal).

    Fail-CLOSED on unusable input: a missing / non-numeric / NaN / infinite
    score yields WARNING, never OK — absence of a reading is never evidence of
    health. It is also not a breach, so it is not escalated beyond WARNING.
    """
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return _PH_WARNING, "portfolio health score absent or not numeric (absence != breach)"
    val = float(score)
    if not math.isfinite(val):
        return _PH_WARNING, "portfolio health score not finite (absence != breach)"
    if val < float(floor):
        return _PH_WARNING, f"portfolio health {val:g} < {float(floor):g} (composite quality score)"
    return _PH_OK, f"portfolio health {val:g} >= {float(floor):g}"
