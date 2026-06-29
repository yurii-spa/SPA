"""
spa_core/strategy_lab/aggressive_lab/ — the HONEST RISK + TOURNAMENT-RANKING layer for the
Aggressive Strategy Paper Lab (Lane 2).

WHY THIS PACKAGE EXISTS (the core principle)
════════════════════════════════════════════
The Aggressive Lab paper-tests the 10–15% strategies the desk normally REFUSES (sUSDe delta-
neutral, LRT carry, leverage loops, points/incentive farms), so the owner can CHOOSE later —
WITH EYES OPEN ON THE RISK. The headline yield on these is RISK-COMPENSATION, not free alpha:
the tail comes (Ethena Oct-2025 $14B→$5.6B unwind; LRT depegs Aug-2024 / Apr-2026; leverage-loop
liquidation cascades). A tournament that ranked ONLY by return would mislead the owner into the
exact trap the desk exists to avoid.

So this layer surfaces RETURN **and** the RISK that comes with it, ALWAYS side by side:
  • honest realized risk metrics (THIN-aware — INSUFFICIENT_DATA below N points, NEVER a
    fabricated degenerate Sharpe — the existing tournament's trustworthy:false flaw must NOT recur),
  • THE TAIL OVERLAY — each strategy replayed through the canonical stress windows so "11% sUSDe DN"
    shows its "and here is the −X% when funding flipped / it depegged",
  • a multi-metric tournament SCORECARD (NOT a yield-sorted leaderboard) the owner sorts/picks.

GUARDRAILS (non-negotiable)
═══════════════════════════
  • ISOLATED / ADVISORY — never touches the go-live track or live allocation. Every output is
    explicitly stamped OUTSIDE_RISKPOLICY / ADVISORY / owner-selectable.
  • This package CONSUMES Lane 1's realized series; it does NOT touch Lane 1 (lab core/harness)
    or Lane 3 (API/agent) files.
  • stdlib-only, deterministic, fail-CLOSED, atomic. LLM FORBIDDEN in risk/ranking.

THE DATA CONTRACT (consume Lane 1)
══════════════════════════════════
Lane 1 writes, per aggressive strategy:

    data/aggressive_lab/<strategy_id>/realized_series.jsonl

a proof-chained, append-only JSONL — ONE JSON object per line. The shape (mirroring the lab's
existing forward *_series.json point shape + the strategy's risk SHAPE) is:

    {
      "date": "YYYY-MM-DD",        # UTC calendar day (one point per day, append-only)
      "equity_usd": <float>,       # realized marked equity that day (the proof-chained track)
      "ret": <float>,              # OPTIONAL day-over-day fractional return (derived if absent)
      "phase": "forward"|"backtest", # which track this point belongs to (see below)
      "prev_hash": "<hex>"|null,   # proof-chain link (Lane 1 owns it; we do not re-verify crypto,
      "hash": "<hex>",             #   we trust Lane 1's chain — our integrity gate is continuity)
      ...                          # other Lane-1 fields are ignored here
    }

Two tracks per strategy share this file, distinguished by ``phase``:
  • "forward"  — the live accruing paper track (THIN today; matures toward day-30),
  • "backtest" — the real 2024–2026 backtest series (deep; carries the stress windows in-sample).
A reader that only sees one phase still works (the missing track is reported INSUFFICIENT_DATA).

Each strategy also carries a RISK SHAPE (its dominant tail mechanism). Lane 1 stamps it on a
sidecar ``meta.json`` (``data/aggressive_lab/<id>/meta.json``) OR inline on each point as
``risk_shape``. The shapes this layer understands (used to pick which stress window bites hardest):

    funding_flip | depeg | liquidation | il | incentive_decay

and the Investment Director RISK CLASS (A/B/C/D), see ``RiskClass`` below.

If Lane 1's files do not exist yet, this layer runs against the DOCUMENTED FIXTURE in
``fixtures.py`` (which matches this schema exactly) — so the ranking is buildable + testable now.

stdlib-only, deterministic, fail-CLOSED, atomic. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import enum
from pathlib import Path
from typing import Dict, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[3]  # …/SPA_Claude
DATA_DIR = _REPO_ROOT / "data"
AGGRESSIVE_LAB_DIR = DATA_DIR / "aggressive_lab"
SCORECARD_FILE = DATA_DIR / "aggressive_lab" / "scorecard.json"

# The realized series filename Lane 1 writes per strategy (JSONL, append-only, proof-chained).
REALIZED_SERIES_NAME = "realized_series.jsonl"
META_NAME = "meta.json"


class RiskClass(str, enum.Enum):
    """The Investment Director risk-source taxonomy. The owner reads this FIRST: it answers
    'where does the return actually come from?' — which is the honest question a yield number hides.

      A — ALPHA          : genuine mispricing / structural edge (the rare honest one).
      B — BETA           : directional market exposure (e.g. pure ETH beta dressed up as 'yield').
      C — RISK_COMPENSATION : the yield is PAID for bearing a tail (sUSDe funding, LRT depeg, peg).
                              MOST aggressive strategies live here — the yield IS the risk premium.
      D — INCENTIVE      : token emissions / points / airdrop farming (decays; not a durable edge).
    """

    A_ALPHA = "A"
    B_BETA = "B"
    C_RISK_COMPENSATION = "C"
    D_INCENTIVE = "D"


# Human labels for the classes (surfaced on the scorecard).
RISK_CLASS_LABEL: Dict[str, str] = {
    "A": "alpha (structural edge)",
    "B": "beta (directional market exposure)",
    "C": "risk-compensation (yield paid for a tail)",
    "D": "incentive (emissions / points — decays)",
}


# ── canonical 2024–2026 stress windows (the tail that comes with the yield) ──────────────────────
# These MIRROR the magnitudes used by the rest of the lab (forward_analytics.STRESS_SCENARIOS +
# rates_desk.levered_stress.STRESS_EVENTS) so the aggressive-lab tail overlay is NO looser than the
# gate. Each window names the real event, the date range to clip the backtest series to, and the
# per-shape SHOCK magnitude (the fraction of position notional marked DOWN when that tail bites).
#
# `shape_shock` maps the strategy's dominant risk SHAPE → the one-day mark-down fraction in THIS
# window. A window bites a strategy in proportion to its shape: a depeg window hammers a `depeg`/`il`
# book, a funding-flip window hammers a `funding_flip` book, the leverage cascade hammers
# `liquidation`. A shape absent from a window's `shape_shock` takes that window's `base_shock` (a
# small systemic spillover — no strategy is fully immune to a market-wide unwind).
STRESS_WINDOWS: Tuple[Dict[str, object], ...] = (
    {
        "key": "eth_crash_2024_08",
        "label": "2024-08 ETH crash / carry-unwind",
        "date_from": "2024-08-01",
        "date_to": "2024-08-31",
        "base_shock": 0.015,
        "shape_shock": {
            "funding_flip": 0.030,   # sUSDe funding flipped hostile
            "depeg": 0.040,          # LST/LRT wobble on the de-risk
            "liquidation": 0.060,    # levered loops forced out
            "il": 0.030,
            "incentive_decay": 0.010,
        },
    },
    {
        "key": "usde_unwind_2025_10",
        "label": "2025-10 USDe leverage unwind (THE test)",
        "date_from": "2025-10-01",
        "date_to": "2025-10-31",
        "base_shock": 0.030,
        "shape_shock": {
            "funding_flip": 0.080,   # USDe $14B→$5.6B: the canonical funding/peg unwind
            "depeg": 0.070,
            "liquidation": 0.120,    # the over-levered PT-loop cascade
            "il": 0.050,
            "incentive_decay": 0.020,
        },
    },
    {
        "key": "rseth_depeg_2026_04",
        "label": "2026-04 KelpDAO rsETH depeg",
        "date_from": "2026-04-01",
        "date_to": "2026-04-30",
        "base_shock": 0.020,
        "shape_shock": {
            "funding_flip": 0.030,
            "depeg": 0.090,          # a restaking depeg — catastrophic for an LRT book
            "liquidation": 0.110,    # depeg + leverage = cascade
            "il": 0.060,
            "incentive_decay": 0.015,
        },
    },
)

# The recognized risk SHAPES (the dominant tail mechanism a strategy carries).
RISK_SHAPES: Tuple[str, ...] = (
    "funding_flip", "depeg", "liquidation", "il", "incentive_decay",
)


# ──────────────────────────────────────────────────────────────────────────────────────────────────
# Lane 1 (PRODUCER) constants — the harness/roster/feeds that WRITE the realized series Lane 2 reads.
# These live alongside the Lane 2 (risk/ranking consumer) constants above; together they make this
# package the single source of both the data contract and the domain markers. Every artifact the
# producer writes carries DOMAIN / OUTSIDE_RISKPOLICY / IS_ADVISORY so no downstream consumer (Lane 2
# risk/tournament, Lane 3 API/agent) can mistake an aggressive-lab number for the conservative track.
# ──────────────────────────────────────────────────────────────────────────────────────────────────
DOMAIN = "aggressive_lab"
OUTSIDE_RISKPOLICY = True
IS_ADVISORY = True
LABEL = "OUTSIDE_RISKPOLICY / AGGRESSIVE / ADVISORY / owner-selectable"

# Comparable virtual notional per strategy book (SEPARATE from the $100k go-live track).
DEFAULT_NOTIONAL_USD = 100_000.0
