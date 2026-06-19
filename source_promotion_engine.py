"""
spa_core/backtesting/source_promotion_engine.py

Manages the formal process for promoting a data source through quality states.

State machine:
  SOURCE_NEEDED → PENDING → REVIEW → CLEAN_INCLUDED
  Any state → RESEARCH_ONLY (downgrade, no data found after investigation)
  MANUAL_PROXY → REVIEW → CLEAN_INCLUDED (if proxy replaced by real data)

Each promotion requires a PromotionEvidence object:
  {
    source_id: str,
    from_state: str,
    to_state: str,
    promoted_by: str,      # "yurii" | "system"
    evidence_url: str,     # DeFiLlama URL, on-chain explorer, etc.
    data_period_start: str, # earliest historical data found
    data_period_end: str,
    notes: str,
    promoted_at: str,      # ISO datetime
  }

Promotion log stored in: data/backtest/source_promotion_log.json

Stdlib only. No external dependencies. LLM FORBIDDEN.
Atomic writes: mkstemp + os.replace.

Date: 2026-06-19 (MP-1319)
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.backtesting.source_pipeline import SourcePipeline, SourceState

# ─── Valid state transition table ────────────────────────────────────────────

# Forward path: SOURCE_NEEDED → PENDING → REVIEW → CLEAN_INCLUDED
# Proxy path:   MANUAL_PROXY  → REVIEW  → CLEAN_INCLUDED
# Downgrade:    any state     → RESEARCH_ONLY
VALID_TRANSITIONS: set[tuple[str, str]] = {
    # Forward path
    (SourceState.SOURCE_NEEDED,  SourceState.PENDING),
    (SourceState.PENDING,        SourceState.REVIEW),
    (SourceState.REVIEW,         SourceState.CLEAN_INCLUDED),
    # Proxy path
    (SourceState.MANUAL_PROXY,   SourceState.REVIEW),
    # Downgrade from any state → RESEARCH_ONLY
    (SourceState.SOURCE_NEEDED,  SourceState.RESEARCH_ONLY),
    (SourceState.PENDING,        SourceState.RESEARCH_ONLY),
    (SourceState.REVIEW,         SourceState.RESEARCH_ONLY),
    (SourceState.CLEAN_INCLUDED, SourceState.RESEARCH_ONLY),
    (SourceState.MANUAL_PROXY,   SourceState.RESEARCH_ONLY),
    # Re-investigation paths from RESEARCH_ONLY
    (SourceState.RESEARCH_ONLY,  SourceState.PENDING),
    (SourceState.RESEARCH_ONLY,  SourceState.SOURCE_NEEDED),
}

# ─── RS-001 / RS-002 source groupings for roadmap ────────────────────────────

RS001_SOURCES = {
    "gmx_btc",
    "gmx_eth",
    "btc_stable_pool",
    "gold_proxy",
    "gmx_btc_exposure",  # alias sometimes used
}

RS002_SOURCES = {
    "btc_usd_conc_liq",
    "rwa_conc_liq",
    "trader_losses_vault",
}

SCHEMA_VERSION = "1.0"
_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "backtest"
_LOG_FILENAME = "source_promotion_log.json"


# ══════════════════════════════════════════════════════════════════════════════
# PromotionEvidence
# ══════════════════════════════════════════════════════════════════════════════

class PromotionEvidence:
    """
    Immutable evidence record for a single source state promotion.

    Attributes
    ----------
    source_id         : str  — source being promoted
    from_state        : str  — SourceState before promotion
    to_state          : str  — SourceState after promotion
    promoted_by       : str  — "yurii" | "system"
    evidence_url      : str  — DeFiLlama URL, on-chain explorer, etc.
    data_period_start : str  — earliest historical data found (YYYY-MM-DD or "")
    data_period_end   : str  — latest data available (YYYY-MM-DD or "")
    notes             : str  — free-form context
    promoted_at       : str  — ISO datetime (auto-set if not provided)
    """

    def __init__(
        self,
        source_id: str,
        from_state: str,
        to_state: str,
        promoted_by: str,
        evidence_url: str,
        data_period_start: str,
        data_period_end: str,
        notes: str = "",
        promoted_at: str = "",
    ) -> None:
        self.source_id = source_id
        self.from_state = from_state
        self.to_state = to_state
        self.promoted_by = promoted_by
        self.evidence_url = evidence_url
        self.data_period_start = data_period_start
        self.data_period_end = data_period_end
        self.notes = notes
        self.promoted_at = promoted_at or datetime.now(timezone.utc).isoformat()

    # ──────────────────────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict."""
        return {
            "source_id": self.source_id,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "promoted_by": self.promoted_by,
            "evidence_url": self.evidence_url,
            "data_period_start": self.data_period_start,
            "data_period_end": self.data_period_end,
            "notes": self.notes,
            "promoted_at": self.promoted_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PromotionEvidence":
        """Deserialize from a dict."""
        return cls(
            source_id=d["source_id"],
            from_state=d["from_state"],
            to_state=d["to_state"],
            promoted_by=d.get("promoted_by", ""),
            evidence_url=d.get("evidence_url", ""),
            data_period_start=d.get("data_period_start", ""),
            data_period_end=d.get("data_period_end", ""),
            notes=d.get("notes", ""),
            promoted_at=d.get("promoted_at", ""),
        )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"PromotionEvidence({self.source_id!r}: "
            f"{self.from_state} → {self.to_state} by {self.promoted_by!r})"
        )


# ══════════════════════════════════════════════════════════════════════════════
# SourcePromotionEngine
# ══════════════════════════════════════════════════════════════════════════════

class SourcePromotionEngine:
    """
    Formalises the source data promotion workflow.

    Validates evidence, applies state transitions to the SourcePipeline,
    and appends to an immutable promotion log.

    Parameters
    ----------
    pipeline : SourcePipeline, optional
        The pipeline to mutate. Defaults to SourcePipeline().
    data_dir : str or Path, optional
        Directory for the promotion log. Defaults to data/backtest/.
    """

    LOG_PATH = "data/backtest/source_promotion_log.json"

    def __init__(
        self,
        pipeline: Optional[SourcePipeline] = None,
        data_dir: Optional[str | Path] = None,
    ) -> None:
        self._pipeline = pipeline if pipeline is not None else SourcePipeline()
        if data_dir is None:
            self._data_dir = _DEFAULT_DATA_DIR
        else:
            self._data_dir = Path(data_dir)
        self._log_path = self._data_dir / _LOG_FILENAME

    # ──────────────────────────────────────────────────────────────────────────
    # Core promotion API
    # ──────────────────────────────────────────────────────────────────────────

    def promote(self, evidence: PromotionEvidence) -> dict:
        """
        Validate and apply a state promotion for a source.

        Checks:
          1. Transition is valid in the state machine.
          2. The evidence.from_state matches the source's current state
             in the pipeline.

        On success:
          - Updates the pipeline via promote_source().
          - Appends to the promotion log atomically.

        Returns
        -------
        dict
            {
              "success": bool,
              "from_state": str,
              "to_state": str,
              "blocked_by": str | None,   # reason string if blocked, else None
            }
        """
        # 1. Check transition validity
        if not self.validate_promotion(evidence.from_state, evidence.to_state):
            return {
                "success": False,
                "from_state": evidence.from_state,
                "to_state": evidence.to_state,
                "blocked_by": (
                    f"Invalid transition: {evidence.from_state} → {evidence.to_state} "
                    f"not allowed by state machine"
                ),
            }

        # 2. Verify from_state matches actual pipeline state
        actual_state = self._pipeline.state(evidence.source_id)
        if actual_state != evidence.from_state:
            return {
                "success": False,
                "from_state": evidence.from_state,
                "to_state": evidence.to_state,
                "blocked_by": (
                    f"from_state mismatch: evidence says '{evidence.from_state}' "
                    f"but pipeline has '{actual_state}' for '{evidence.source_id}'"
                ),
            }

        # 3. Apply to pipeline
        self._pipeline.promote_source(
            source_id=evidence.source_id,
            new_state=evidence.to_state,
            reason=(
                f"SourcePromotionEngine: promoted by {evidence.promoted_by!r} "
                f"— {evidence.notes or 'no notes'}"
            ),
        )

        # 4. Append to promotion log atomically
        self._append_log(evidence)

        return {
            "success": True,
            "from_state": evidence.from_state,
            "to_state": evidence.to_state,
            "blocked_by": None,
        }

    def validate_promotion(self, from_state: str, to_state: str) -> bool:
        """
        Check whether a (from_state, to_state) pair is valid in the state machine.

        Parameters
        ----------
        from_state : str
            Current SourceState.
        to_state : str
            Target SourceState.

        Returns
        -------
        bool
            True if the transition is in VALID_TRANSITIONS.
        """
        return (from_state, to_state) in VALID_TRANSITIONS

    # ──────────────────────────────────────────────────────────────────────────
    # Query API
    # ──────────────────────────────────────────────────────────────────────────

    def promotion_history(self, source_id: Optional[str] = None) -> List[dict]:
        """
        Return the full promotion log, optionally filtered by source_id.

        Parameters
        ----------
        source_id : str, optional
            If provided, return only entries for this source.

        Returns
        -------
        list[dict]
            List of promotion log entry dicts.
        """
        entries = self._load_log()
        if source_id is not None:
            entries = [e for e in entries if e.get("source_id") == source_id]
        return entries

    def sources_needing_promotion(self) -> List[str]:
        """
        Return a sorted list of source IDs that are in SOURCE_NEEDED or PENDING state.

        These are the actionable sources that require investigation and evidence.

        Returns
        -------
        list[str]
        """
        all_sources = self._pipeline.all_sources()
        return sorted(
            sid
            for sid, state in all_sources.items()
            if state in (SourceState.SOURCE_NEEDED, SourceState.PENDING)
        )

    def promotion_roadmap(self) -> dict:
        """
        Return an actionable roadmap for promoting sources.

        Groups sources by strategy (RS-001, RS-002) and computes priority
        next actions.

        Returns
        -------
        dict
            {
              "rs001_needs": [source_ids needing promotion for RS-001],
              "rs002_needs": [source_ids needing promotion for RS-002],
              "other_needs": [other sources needing promotion],
              "total_pending": int,
              "next_action": str,   # human-readable first priority
            }
        """
        needing = self.sources_needing_promotion()
        needing_set = set(needing)

        rs001_needs = sorted(needing_set & RS001_SOURCES)
        rs002_needs = sorted(needing_set & RS002_SOURCES)
        other_needs = sorted(needing_set - RS001_SOURCES - RS002_SOURCES)

        # Determine first priority next action
        if rs001_needs:
            next_action = f"Find DeFiLlama pool ID for: {rs001_needs[0]}"
        elif rs002_needs:
            next_action = f"Find DeFiLlama pool ID for: {rs002_needs[0]}"
        elif other_needs:
            next_action = f"Find data source for: {other_needs[0]}"
        else:
            next_action = "All sources either promoted or at REVIEW+ — run manual review"

        return {
            "rs001_needs": rs001_needs,
            "rs002_needs": rs002_needs,
            "other_needs": other_needs,
            "total_pending": len(needing),
            "next_action": next_action,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Log persistence (atomic)
    # ──────────────────────────────────────────────────────────────────────────

    def _load_log(self) -> List[dict]:
        """Load promotion log from disk. Returns [] if not found or invalid."""
        if not self._log_path.exists():
            return []
        try:
            with open(self._log_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return data.get("entries", [])
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
        return []

    def _append_log(self, evidence: PromotionEvidence) -> None:
        """
        Append one evidence entry to the promotion log atomically.
        Uses mkstemp + os.replace.
        """
        self._data_dir.mkdir(parents=True, exist_ok=True)
        entries = self._load_log()
        entries.append(evidence.to_dict())

        payload = json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "entries": entries,
            },
            indent=2,
            ensure_ascii=False,
        )
        fd, tmp_path = tempfile.mkstemp(
            dir=self._data_dir,
            prefix=".source_promotion_log_tmp_",
            suffix=".json",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp_path, self._log_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


# ─── CLI ──────────────────────────────────────────────────────────────────────

def _cli() -> None:  # pragma: no cover
    engine = SourcePromotionEngine()
    roadmap = engine.promotion_roadmap()
    print(json.dumps(roadmap, indent=2))


if __name__ == "__main__":  # pragma: no cover
    _cli()
