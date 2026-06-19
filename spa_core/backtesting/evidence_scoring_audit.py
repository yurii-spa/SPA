"""
spa_core/backtesting/evidence_scoring_audit.py

Audits the evidence scoring pipeline.
Answers: "When will we have enough evidence to go live?"

Evidence model (from paper_evidence_tracker_v2.py):
  - CLEAN source day   = 1.0 pt  (clean_included, low drift)
  - RESEARCH source day = 0.3 pt (any non-CLEAN source present)
  - PLACEHOLDER        = 0.1 pt  (not used in current mix; treated as research)
  - Extreme market day = ×1.5 multiplier (stress-test bonus)
  - HIGH drift day     = ×0.5 penalty    (allocation deviated > 2%)
  - Required for live  = 30.0 pts

Days to live with different source quality mixes:
  - All CLEAN (100%):          daily = 1.0 → 30 days minimum
  - Current mix (17% CLEAN):   daily ≈ 0.419 → ~72 days
  - Target mix  (50% CLEAN):   daily = 0.65 → ~47 days

Priority (highest wins for a single day): extreme > high_drift > non_clean > default.
For expected-value purposes, multipliers are applied to the base score independently.

MP-1352 (v9.68)
stdlib only. Advisory/read-only. LLM FORBIDDEN.
"""

from __future__ import annotations

import math
from typing import List

# ── Evidence constants ────────────────────────────────────────────────────────

SCORE_CLEAN       = 1.0   # CLEAN source day
SCORE_RESEARCH    = 0.3   # any non-CLEAN source (PENDING / MANUAL_PROXY / etc.)
SCORE_PLACEHOLDER = 0.1   # placeholder data (treated as research in our model)

MULTIPLIER_EXTREME    = 1.5   # extreme market day bonus
MULTIPLIER_HIGH_DRIFT = 0.5   # high drift penalty (drift > 2%)

REQUIRED_POINTS = 30.0   # points needed to unlock live trading

# Total number of sources being tracked (used for source_impact weight)
TOTAL_SOURCES = 12

# Roadmap milestones: (clean_pct, label)
_ROADMAP_MILESTONES: list[tuple[float, str]] = [
    (0.17,  "Current (17% CLEAN)"),
    (0.25,  "25% CLEAN — first upgrade"),
    (0.33,  "33% CLEAN — one-third"),
    (0.50,  "50% CLEAN — target mix"),
    (0.75,  "75% CLEAN — near complete"),
    (1.00,  "100% CLEAN — all sources clean"),
]


# ══════════════════════════════════════════════════════════════════════════════
# EvidenceScoringAudit
# ══════════════════════════════════════════════════════════════════════════════

class EvidenceScoringAudit:
    """
    Audits the evidence scoring pipeline for the CPA paper trading period.

    Args:
        clean_pct: Fraction of capital in CLEAN sources (0.0–1.0).
                   Default 0.17 reflects current portfolio (2/12 sources clean).
    """

    def __init__(self, clean_pct: float = 0.17) -> None:
        if not 0.0 <= clean_pct <= 1.0:
            raise ValueError(f"clean_pct must be in [0, 1], got {clean_pct}")
        self._clean_pct = float(clean_pct)

    # ── Core scoring math ─────────────────────────────────────────────────────

    def _base_score(self, clean_pct: float) -> float:
        """
        Expected evidence points for one normal (non-extreme, low-drift) day.

        Formula:
            base = clean_pct × SCORE_CLEAN + (1 − clean_pct) × SCORE_RESEARCH
                 = SCORE_RESEARCH + (SCORE_CLEAN − SCORE_RESEARCH) × clean_pct
                 = 0.3 + 0.7 × clean_pct
        """
        research_pct = 1.0 - clean_pct
        return clean_pct * SCORE_CLEAN + research_pct * SCORE_RESEARCH

    def daily_score(
        self,
        is_extreme: bool = False,
        is_high_drift: bool = False,
    ) -> float:
        """
        Expected evidence points for one day given current source mix.

        Multipliers are applied on top of the base score.
        Priority: extreme > high_drift (extreme takes precedence if both True).

        Args:
            is_extreme:   True if market regime is extreme (×1.5 bonus).
            is_high_drift: True if allocation drift > 2% (×0.5 penalty).

        Returns:
            Float evidence points for that day (always > 0).
        """
        base = self._base_score(self._clean_pct)
        if is_extreme:
            return base * MULTIPLIER_EXTREME
        if is_high_drift:
            return base * MULTIPLIER_HIGH_DRIFT
        return base

    # ── Days to live ──────────────────────────────────────────────────────────

    def days_to_live(self) -> int:
        """
        Expected days to accumulate 30 points with the current source mix.

        Returns:
            Integer days (ceiling of REQUIRED_POINTS / daily_base_score).
        """
        return self.days_to_live_at(self._clean_pct)

    def days_to_live_at(self, clean_pct: float) -> int:
        """
        Expected days to accumulate 30 points with the given clean_pct.

        Args:
            clean_pct: Fraction of capital in CLEAN sources (0.0–1.0).

        Returns:
            Integer days (ceiling). Always >= 30 (30 when clean_pct == 1.0).
        """
        base = self._base_score(max(0.0, min(1.0, clean_pct)))
        if base <= 0:
            return 10_000  # safety cap
        return math.ceil(REQUIRED_POINTS / base)

    # ── Roadmap ───────────────────────────────────────────────────────────────

    def roadmap(self) -> List[dict]:
        """
        List of milestone dicts showing days-to-live at different CLEAN fractions.

        Each element::

            {
                "clean_pct":  float,   # fraction 0–1
                "clean_pct_pct": int,  # percentage label
                "daily_score": float,  # pts per day (normal regime)
                "days":       int,     # days to accumulate 30 pts
                "milestone":  str,     # human description
            }
        """
        result = []
        for clean_pct, label in _ROADMAP_MILESTONES:
            days = self.days_to_live_at(clean_pct)
            result.append({
                "clean_pct":     round(clean_pct, 4),
                "clean_pct_pct": round(clean_pct * 100),
                "daily_score":   round(self._base_score(clean_pct), 4),
                "days":          days,
                "milestone":     label,
            })
        return result

    # ── Source impact ─────────────────────────────────────────────────────────

    def source_impact(self, source_id: str) -> dict:
        """
        Impact of making one source CLEAN (assumes capital weight = 1/TOTAL_SOURCES).

        Args:
            source_id: Identifier string for the source (used as label only).

        Returns::

            {
                "source_id":      str,
                "weight":         float,   # 1 / TOTAL_SOURCES
                "before_days":    int,     # days to live before upgrade
                "after_days":     int,     # days to live after upgrade
                "days_saved":     int,     # before - after (>= 0)
                "daily_gain":     float,   # pts/day improvement
            }
        """
        weight = 1.0 / TOTAL_SOURCES
        # New clean_pct after making this one source clean
        new_clean_pct = min(1.0, self._clean_pct + weight)

        before = self.days_to_live_at(self._clean_pct)
        after  = self.days_to_live_at(new_clean_pct)

        before_score = self._base_score(self._clean_pct)
        after_score  = self._base_score(new_clean_pct)

        return {
            "source_id":   source_id,
            "weight":      round(weight, 6),
            "before_days": before,
            "after_days":  after,
            "days_saved":  max(0, before - after),
            "daily_gain":  round(after_score - before_score, 6),
        }

    # ── Markdown report ───────────────────────────────────────────────────────

    def to_markdown(self) -> str:
        """
        Markdown report with roadmap table.

        Contains '30.0 pts' threshold and a table of milestones.
        """
        lines = [
            "# Evidence Scoring Audit — When Can We Go Live?",
            "",
            f"**Required evidence:** {REQUIRED_POINTS:.1f} pts (30.0 pts)",
            f"**Current CLEAN fraction:** {self._clean_pct * 100:.0f}%",
            f"**Current daily score:** {self._base_score(self._clean_pct):.4f} pts/day",
            f"**Days to live (current mix):** {self.days_to_live()} days",
            "",
            "## Roadmap — Days to Live at Different Source Quality Mixes",
            "",
            "| CLEAN % | Daily Score | Days to 30 pt | Milestone |",
            "|---------|-------------|---------------|-----------|",
        ]

        for row in self.roadmap():
            lines.append(
                f"| {row['clean_pct_pct']:>6}% "
                f"| {row['daily_score']:>11.4f} "
                f"| {row['days']:>13} "
                f"| {row['milestone']} |"
            )

        lines += [
            "",
            "## Evidence Model",
            "",
            f"- CLEAN source day    = **{SCORE_CLEAN:.1f} pt**",
            f"- Research source day = **{SCORE_RESEARCH:.1f} pt**",
            f"- Extreme market day  = **×{MULTIPLIER_EXTREME}** multiplier (bonus)",
            f"- High drift day      = **×{MULTIPLIER_HIGH_DRIFT}** multiplier (penalty)",
            f"- **Required for live = {REQUIRED_POINTS:.1f} pts (30 pt threshold)**",
            "",
            "> LLM FORBIDDEN in this module (advisory, read-only).",
        ]

        return "\n".join(lines)
