"""
spa_core/riskwire — RISKWIRE: the unified NO-FORK measurement-engine FACADE (WS1.2).

> *The desk proved its edge is honest measurement, not yield. DFB proved measurement can be a public
> product. RISKWIRE unifies the three disconnected L3 measurement SEEDS into ONE coherent measurement
> object per subject, so every product deliverable (reports, oracle, API) presents from a single
> engine — not three seeds that could silently drift.*

THE THREE SEEDS RISKWIRE UNIFIES (it CALLS them; it re-implements NONE of their risk math)
------------------------------------------------------------------------------------------
  1. DFB overlay      (spa_core.dfb.risk_overlay.overlay)       — per-POOL A/B/C/D + exit-liquidity-
                                                                   by-size + refusal + engine_proof_hash.
  2. RWA Safety Board (spa_core.strategy_lab.rwa_backstop)      — per-RWA-COLLATERAL liquidation-NAV /
                                                                   LIQUID/THIN/REDEMPTION_ONLY/UNSAFE.
  3. Underwriting     (spa_core.strategy_lab.underwriting.report) — per-BOOK hash-anchored risk report
                                                                   (the head_hash is the book's anchor).

THE NON-NEGOTIABLE «NO-FORK» RULE (AST + byte-identity asserted by test_riskwire_no_fork.py)
--------------------------------------------------------------------------------------------
RISKWIRE defines **ZERO risk math**. Every verdict field on a `RiskWireMeasurement` is COPIED from
the seed that produced it (which itself imports the SPA engine). So for any subject:

    RiskWire's verdict == the underlying seed's verdict == the desk's verdict   (byte-identical)

The facade is a thin PRESENTATION + PROVENANCE + PROOF-CHAIN layer over the seeds. It cannot soften a
toxic subject: a class-D / REFUSE pool stays class-D / REFUSE because the facade reads the seed's
`risk_class` / `refusal` verbatim (the size-independent structural veto lives in the engine, surfaced
by DFB, and RISKWIRE only re-presents it).

CONSTRAINTS (inherited verbatim from CLAUDE.md / RISKWIRE_CHARTER §3)
--------------------------------------------------------------------
stdlib-only · deterministic (`as_of` = the DATA date, never the wall clock) · fail-CLOSED (a subject
whose seed cannot grade it → `risk_class=UNKNOWN` + `flagged`, NEVER a fabricated unified grade) ·
atomic writes (confined to `data/riskwire/`) · NO LLM in the risk path · NEVER imports
`spa_core.execution` · READ-ONLY + advisory (moves no capital, never touches the go-live track).

THE SHARED CONTRACT (this module defines it; WS1.3/1.4 CONSUME it)
-----------------------------------------------------------------
`SubjectKind` (POOL | RWA_COLLATERAL | BOOK) + `Subject` (stable id + kind + provenance) +
`RiskWireMeasurement` (the unified per-subject object). The exact on-disk schema is documented on
`RiskWireMeasurement.to_dict` and in docs form on the class docstring.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── the subject taxonomy — WHAT RiskWire measures ─────────────────────────────────────────────────
class SubjectKind(str, enum.Enum):
    """The kind of measurable subject, which routes `measure()` to the seed that grades it.

      POOL            — a followed DeFi pool/market → DFB overlay (A/B/C/D + exit-by-size + refusal).
      RWA_COLLATERAL  — a tokenized-RWA collateral candidate → RWA Safety Board (liquidation-NAV +
                        LIQUID/THIN/REDEMPTION_ONLY/UNSAFE + marketing-vs-liq gap).
      BOOK            — a book/sleeve/portfolio underwriting subject → the hash-anchored underwriting
                        report (the report head_hash is the book's measurement anchor).
    """
    POOL = "pool"
    RWA_COLLATERAL = "rwa_collateral"
    BOOK = "book"


# ── the unified risk-class taxonomy (a SUPERSET presentation — NOT new risk math) ──────────────────
class RiskWireClass(str, enum.Enum):
    """The unified A/B/C/D/UNKNOWN letter presented on every measurement. For POOL subjects it IS the
    DFB `RiskClass` verbatim (the engine's own verdict). For RWA_COLLATERAL / BOOK subjects, where the
    seed produces a native verdict vocabulary (LIQUID/THIN/… or SURVIVES_AT/…), RISKWIRE maps that
    seed verdict onto the SAME A/B/C/D letter with a DETERMINISTIC, documented PRESENTATION map (no
    arithmetic, no re-scoring — a pure lookup on the seed's own verbatim verdict string). The native
    seed verdict is ALWAYS preserved verbatim in `native_verdict` so nothing is laundered."""
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    UNKNOWN = "UNKNOWN"


RISKWIRE_CLASS_LABELS: Dict[RiskWireClass, str] = {
    RiskWireClass.A: "alpha — seed would enter / cash-like executable exit (structurally clean)",
    RiskWireClass.B: "beta-floor — seed would enter, ~baseline (own-the-floor) / thin-but-present exit",
    RiskWireClass.C: "risk-comp — seed refuses on economics/size/liquidity, or redemption-gated only",
    RiskWireClass.D: "incentive/unsafe — structural toxicity veto, or no executable exit (refuse@any size)",
    RiskWireClass.UNKNOWN: "unknown — data too thin/stale to grade (fail-closed, never a fabricated grade)",
}


# ── the subject identity model ────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Subject:
    """One measurable subject — pure IDENTITY + provenance, NO judgment. `subject_id` is a STABLE,
    deterministic slug so history/detail files and cross-surface joins are reproducible."""
    subject_id: str                 # stable slug: "<kind>::<native id>" (sanitized)
    kind: SubjectKind
    display_name: str               # human label (e.g. the pool_id, the RWA symbol, the book name)
    provenance: str                 # which seed/registry produced this identity
    native_ref: Dict[str, Any] = field(default_factory=dict)  # the raw identity handed to the seed

    def to_dict(self) -> dict:
        return {
            "subject_id": self.subject_id,
            "kind": self.kind.value,
            "display_name": self.display_name,
            "provenance": self.provenance,
            "native_ref": dict(self.native_ref),
        }


# ── an exit-by-size ticket (flattened, seed-agnostic presentation) ─────────────────────────────────
@dataclass(frozen=True)
class ExitLiquidityBySize:
    """One ticket on the exit-liquidity-by-size schedule. For POOL subjects these are DFB's engine
    depth rows; for RWA_COLLATERAL these are the Safety Board's liquidation-NAV sized legs. RISKWIRE
    computes NONE of these numbers — they are copied from the seed. A fail-CLOSED hole → `absorbable_usd`
    / `exit_frac` is None + `flagged=True`."""
    ticket_usd: int
    absorbable_usd: Optional[float]
    exit_frac: Optional[float]
    flagged: bool

    def to_dict(self) -> dict:
        return {
            "ticket_usd": self.ticket_usd,
            "absorbable_usd": self.absorbable_usd,
            "exit_frac": self.exit_frac,
            "flagged": self.flagged,
        }


# ── the refusal verdict (verbatim from the seed) ───────────────────────────────────────────────────
@dataclass(frozen=True)
class RiskWireRefusal:
    """The would-I-underwrite verdict, copied verbatim from the seed.
      verdict   "SAFE" | "REFUSE" | "UNKNOWN"
      reason    the seed's own reason string
      tail_veto True iff the refusal is the size-INDEPENDENT structural toxicity veto (cannot be sized
                around — the worst, class-D refusal). Copied from the seed; never re-derived here."""
    verdict: str
    reason: str
    tail_veto: bool

    def to_dict(self) -> dict:
        return {"verdict": self.verdict, "reason": self.reason, "tail_veto": self.tail_veto}


# ── the unified per-subject measurement object — THE product of the facade ─────────────────────────
@dataclass(frozen=True)
class RiskWireMeasurement:
    """The unified measurement object per subject — one coherent risk-truth view composed from the
    seed's OWN verdict. This is THE contract WS1.3 (day-30 pipeline) and WS1.4 (proof/verifier) consume.

    EXACT data/riskwire/measurements.json (list element) AND data/riskwire/subject/<subject_id>.json
    schema:

    {
      "subject_id": str,                 # stable slug "<kind>::<native id>"
      "kind": "pool"|"rwa_collateral"|"book",
      "display_name": str,
      "risk_class": "A"|"B"|"C"|"D"|"UNKNOWN",   # the unified A/B/C/D letter (seed verdict, presented)
      "risk_class_label": str,
      "native_verdict": str,             # the seed's OWN verbatim verdict (A/B/C/D | LIQUID/THIN/… |
                                         #   SURVIVES_AT/DOES_NOT_SURVIVE_PAST/INSUFFICIENT_DATA)
      "refusal": {"verdict","reason","tail_veto"},   # verbatim from the seed (POOL/COLLATERAL); BOOK: n/a
      "exit_liquidity_by_size": [ {"ticket_usd","absorbable_usd","exit_frac","flagged"}, … ],
      "liquidation_nav": {…}|null,       # RWA_COLLATERAL only: {frac_1m, usd_1m, gap_pct_1m, …} verbatim
      "structural_haircut": float|null,  # POOL only: the engine's OWN size-independent tail haircut
      "total_haircut": float|null,       # POOL only
      "seed": str,                       # which seed produced this ("dfb"|"rwa_backstop"|"underwriting")
      "seed_proof_hash": str,            # the seed's OWN anchor (DFB engine_proof_hash | book head_hash |
                                         #   safety-board row proof — byte-identical to the seed)
      "as_of": str|null,                 # the DATA date, NEVER the wall clock
      "flagged": bool,                   # any fail-CLOSED hole in this measurement
      "flag_reason": str|null,
      "provenance": str,                 # subject provenance
      "prev_hash": str,                  # per-row proof-chain link (genesis "0"*64)
      "row_hash": str                    # sha256 over the canonical row (PROOF_CHAIN pattern)
    }
    """
    subject_id: str
    kind: SubjectKind
    display_name: str
    risk_class: RiskWireClass
    risk_class_label: str
    native_verdict: str
    refusal: Optional[RiskWireRefusal]
    exit_liquidity_by_size: List[ExitLiquidityBySize]
    liquidation_nav: Optional[Dict[str, Any]]
    structural_haircut: Optional[float]
    total_haircut: Optional[float]
    seed: str
    seed_proof_hash: str
    as_of: Optional[str]
    flagged: bool
    flag_reason: Optional[str]
    provenance: str
    prev_hash: str
    row_hash: str = ""

    def to_dict(self) -> dict:
        """The canonical JSON dict (the shared contract above). Deterministic key set / order."""
        return {
            "subject_id": self.subject_id,
            "kind": self.kind.value,
            "display_name": self.display_name,
            "risk_class": self.risk_class.value,
            "risk_class_label": self.risk_class_label,
            "native_verdict": self.native_verdict,
            "refusal": (self.refusal.to_dict() if self.refusal is not None else None),
            "exit_liquidity_by_size": [r.to_dict() for r in self.exit_liquidity_by_size],
            "liquidation_nav": (dict(self.liquidation_nav)
                                if self.liquidation_nav is not None else None),
            "structural_haircut": self.structural_haircut,
            "total_haircut": self.total_haircut,
            "seed": self.seed,
            "seed_proof_hash": self.seed_proof_hash,
            "as_of": self.as_of,
            "flagged": self.flagged,
            "flag_reason": self.flag_reason,
            "provenance": self.provenance,
            "prev_hash": self.prev_hash,
            "row_hash": self.row_hash,
        }


__all__ = [
    "SubjectKind",
    "RiskWireClass",
    "RISKWIRE_CLASS_LABELS",
    "Subject",
    "ExitLiquidityBySize",
    "RiskWireRefusal",
    "RiskWireMeasurement",
]
