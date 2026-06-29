"""
spa_core/strategy_lab/rates_desk/capacity_sizing.py — ROUND-2 WS-3.2: CAPACITY-AWARE GRADED sizing.

THE QUESTION THIS ANSWERS (WS-1's honest finding)
══════════════════════════════════════════════════
WS-1.3 (edge_at_scale) showed the desk's selection uplift is a $100k artifact — it goes NEGATIVE past
$1M because the capacity caps clamp the high-yield concentration the edge depends on. The lesson is NOT
"refuse everything"; it is "size to the REALIZED liquidity, never above it". A binary refuse/all-in gate
is the wrong tool: it either dumps the whole cash book into a thin pool (maxing the liquidity haircut →
a FALSE tail-veto) or refuses a genuinely-fundable carry book because the §9 one-tick cap collapses it
below the tradeable floor. The fix is GRADED participation: position size = f(depth, edge), HARD-capped
at the realized one-tick capacity, so the desk stays invested at a size where the edge actually survives.

WHAT THIS COMPUTES (pure, deterministic, fail-CLOSED)
══════════════════════════════════════════════════════
`graded_size(realized_depth_usd, net_edge, cash_available_usd, params, recal=None)` →
  GradedSize(size_usd, capacity_cap_usd, edge_participation_frac, binding, reason)

The size is the MINIMUM of three honest bounds — it can never exceed ANY of them:
  (1) CAPACITY CAP   = max_size_frac_of_exit × realized_depth_usd   (the §9 one-tick exit cap — the
                       desk never moves more than this fraction of one-tick exit liquidity; this is the
                       HARD ceiling that keeps us from betting $100k into a $5M pool).
  (2) EDGE-GRADED    = capacity_cap × participation(net_edge)       (GRADED, not binary: a thin edge
                       takes a small fraction of the capacity cap; a fat edge ramps toward the full cap.
                       participation is a clamped linear ramp in net_edge between a min-edge floor and a
                       full-participation edge — bounded [0, 1], monotone non-decreasing in edge).
  (3) CASH AVAILABLE = cash_available_usd                            (never size beyond the book's cash).

The result is the smallest of the three; `binding` names which bound won so the sizing is auditable.
A NON-POSITIVE / malformed depth, edge, or cash → size 0 (fail-CLOSED: never size into the unknown).

WHY THIS DOES NOT WEAKEN THE REFUSAL THESIS
═════════════════════════════════════════════
Sizing is the LAST gate step (step 7), reached ONLY after every structural/economic veto has passed.
A toxic book is TAIL_VETO'd at step 1 on its SIZE-INDEPENDENT structural haircut — it never reaches
sizing at all, so no amount of graded sizing can re-admit it (the red-team's size-down exploit stays
closed). Graded sizing only decides HOW MUCH of an already-approved, structurally-clean carry book to
take — it makes the desk fund real carry at a survivable size, it never lets capital into a refused book.

stdlib only, Decimal-exact, deterministic, PURE (no clock / IO / RNG), LLM-FORBIDDEN, fail-CLOSED.
Advisory: this only SHAPES an approved book's size; it never approves, never moves live capital.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from spa_core.strategy_lab.rates_desk.contracts import D0, D1, RatePolicyParams
from spa_core.strategy_lab.rates_desk.fair_value_engine import _safe_decimal

# ── graded-participation ramp parameters (pinned; an edge below MIN takes ~0 of the cap, an edge at/
#    above FULL takes the full cap; linear in between). These are SIZING knobs, NOT risk vetoes — they
#    can only make an already-approved book SMALLER, never re-admit a refused one. Documented + pinned. ─
# Below this net_edge the book is barely-above-hurdle carry → take only the floor fraction of capacity.
GRADED_MIN_EDGE = Decimal("0.005")        # 50 bps net edge → ramp begins
# At/above this net_edge the carry is fat enough to justify the FULL capacity cap.
GRADED_FULL_EDGE = Decimal("0.03")        # 300 bps net edge → full one-tick capacity
# The floor participation fraction at MIN_EDGE (never 0 for an approved book — a real but thin edge
# still deserves a small, capacity-bounded ticket rather than an all-or-nothing refuse).
GRADED_FLOOR_FRAC = Decimal("0.25")       # at MIN_EDGE take 25% of the capacity cap


@dataclass(frozen=True)
class GradedSize:
    """The graded-sizing verdict. FROZEN / Decimal-exact / hashable for the proof chain. `size_usd` is
    the capacity-aware graded ticket (0 when any input is malformed/non-positive — fail-CLOSED)."""
    size_usd: Decimal
    capacity_cap_usd: Decimal               # max_size_frac_of_exit × realized_depth (the §9 hard ceiling)
    edge_participation_frac: Decimal        # the graded ramp value in [0, 1]
    binding: str                            # "capacity" | "edge" | "cash" | "malformed"
    reason: str

    def proof(self) -> dict:
        return {
            "size_usd": str(self.size_usd),
            "capacity_cap_usd": str(self.capacity_cap_usd),
            "edge_participation_frac": str(self.edge_participation_frac),
            "binding": self.binding,
            "reason": self.reason,
        }


def participation_frac(net_edge: Decimal) -> Decimal:
    """The GRADED participation ramp: how much of the capacity cap an approved book takes, as a clamped
    linear function of net_edge. Bounded [0, 1], MONOTONE non-decreasing in net_edge (more edge → never
    less participation). PURE / Decimal-exact / fail-CLOSED (malformed edge → 0).

      net_edge <= 0                  → 0      (no edge → no participation; should not happen post-gate)
      0 < net_edge <= MIN_EDGE       → FLOOR_FRAC (a thin-but-real approved edge takes the floor slice)
      MIN_EDGE < net_edge < FULL_EDGE→ linear from FLOOR_FRAC up to 1.0
      net_edge >= FULL_EDGE          → 1.0    (full capacity cap)
    """
    e = _safe_decimal(net_edge)
    if e is None or e <= D0:
        return D0
    if e <= GRADED_MIN_EDGE:
        return GRADED_FLOOR_FRAC
    if e >= GRADED_FULL_EDGE:
        return D1
    # linear ramp FLOOR_FRAC → 1.0 across [MIN_EDGE, FULL_EDGE]
    span = GRADED_FULL_EDGE - GRADED_MIN_EDGE
    if span <= D0:  # defensive: degenerate config → full participation (never negative)
        return D1
    frac = GRADED_FLOOR_FRAC + (D1 - GRADED_FLOOR_FRAC) * ((e - GRADED_MIN_EDGE) / span)
    if frac < D0:
        return D0
    if frac > D1:
        return D1
    return frac


def graded_size(
    realized_depth_usd: Decimal,
    net_edge: Decimal,
    cash_available_usd: Decimal,
    params: RatePolicyParams,
) -> GradedSize:
    """Capacity-aware graded ticket = min(capacity_cap, edge_graded, cash_available). PURE /
    deterministic / fail-CLOSED.

    `realized_depth_usd` is the position market's REAL one-tick exit liquidity (the §9 proxy from the
    live RateSurface — NOT a guessed/peak depth). The result NEVER exceeds the §9 capacity cap
    (max_size_frac_of_exit × depth), so the desk can never bet more than a safe fraction of realized
    liquidity (the WS-1 'edge dissolves past capacity' lesson). A malformed / non-positive depth, edge,
    or cash yields size 0 — we never size into liquidity we cannot measure."""
    depth = _safe_decimal(realized_depth_usd)
    edge = _safe_decimal(net_edge)
    cash = _safe_decimal(cash_available_usd)
    if depth is None or depth <= D0 or edge is None or cash is None or cash <= D0:
        return GradedSize(
            size_usd=D0, capacity_cap_usd=D0, edge_participation_frac=D0,
            binding="malformed",
            reason=("fail-CLOSED: realized depth / net_edge / cash malformed or non-positive — "
                    "never size into unmeasured liquidity"))

    frac_of_exit = _safe_decimal(params.max_size_frac_of_exit)
    if frac_of_exit is None or frac_of_exit < D0:
        frac_of_exit = D0
    capacity_cap = frac_of_exit * depth          # (1) the §9 one-tick exit ceiling — HARD bound
    part = participation_frac(edge)              # (2) the graded edge ramp in [0, 1]
    edge_graded = capacity_cap * part

    # the ticket is the SMALLEST of the three honest bounds — it can exceed NONE of them.
    candidates = [
        (capacity_cap, "capacity"),
        (edge_graded, "edge"),
        (cash, "cash"),
    ]
    size, binding = min(candidates, key=lambda c: c[0])
    if size < D0:
        size = D0
    return GradedSize(
        size_usd=size,
        capacity_cap_usd=capacity_cap,
        edge_participation_frac=part,
        binding=binding,
        reason=(f"graded ticket = min(capacity ${capacity_cap}, edge-graded ${edge_graded} "
                f"@ part={part}, cash ${cash}) → ${size} (binding: {binding})"),
    )
