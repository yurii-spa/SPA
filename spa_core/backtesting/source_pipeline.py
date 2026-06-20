"""
spa_core/backtesting/source_pipeline.py — CPA Source Pipeline

Manages source data classification for strict backtesting.
Implements the CPA methodology: strict evidence ≠ research ≠ pending.

Source states:
  CLEAN_INCLUDED  — accepted for strict backtest
  PENDING         — under review, cannot affect strict results
  RESEARCH_ONLY   — modeled/estimated, no clean historical data
  MANUAL_PROXY    — proxy available but not clean direct data
  REVIEW          — needs owner/analyst verification
  SOURCE_NEEDED   — no data source connected yet

Storage: data/backtest/source_pipeline.json (atomic writes, mkstemp + os.replace)

Strict eligibility rule:
  Only CLEAN_INCLUDED sources can affect strict backtest results.
  All other states are excluded from strict evidence.

Stdlib only. No external dependencies. LLM FORBIDDEN.
Atomic writes: mkstemp + os.replace.

Date: 2026-06-19 (MP-1304)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.utils.atomic import atomic_save

# ─── Source state constants ───────────────────────────────────────────────────


class SourceState:
    """Enumeration of possible source data states."""

    CLEAN_INCLUDED = "clean_included"   # accepted for strict backtest
    PENDING        = "pending"          # under review, not yet accepted
    RESEARCH_ONLY  = "research_only"    # modeled/estimated, no clean history
    MANUAL_PROXY   = "manual_proxy"     # proxy exists, not clean direct data
    REVIEW         = "review"           # needs owner/analyst verification
    SOURCE_NEEDED  = "source_needed"    # no data source connected yet

    _ALL_STATES = {
        CLEAN_INCLUDED,
        PENDING,
        RESEARCH_ONLY,
        MANUAL_PROXY,
        REVIEW,
        SOURCE_NEEDED,
    }

    @classmethod
    def is_valid(cls, state: str) -> bool:
        return state in cls._ALL_STATES

    @classmethod
    def can_affect_backtest(cls, state: str) -> bool:
        """Return True only for CLEAN_INCLUDED."""
        return state == cls.CLEAN_INCLUDED


# ─── Default source table ─────────────────────────────────────────────────────

_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "backtest"
_FILENAME = "source_pipeline.json"
SCHEMA_VERSION = "1.0"

# Default source table based on CPA backtest findings.
# Keys are source IDs; values are SourceState strings.
DEFAULT_SOURCES: Dict[str, str] = {
    # Clean historical data — strict backtest eligible
    "aave_v2_usdc":          SourceState.CLEAN_INCLUDED,
    "compound_v2_usdc":      SourceState.CLEAN_INCLUDED,
    "aave_v3_usdc":          SourceState.CLEAN_INCLUDED,
    "compound_v3_usdc":      SourceState.CLEAN_INCLUDED,
    "aave_v3_base":          SourceState.CLEAN_INCLUDED,
    "morpho_blue":           SourceState.CLEAN_INCLUDED,
    "sky_susds":             SourceState.CLEAN_INCLUDED,
    "sfrax":                 SourceState.CLEAN_INCLUDED,
    # Proxy available but not clean direct data
    "pendle_pt_susde":       SourceState.MANUAL_PROXY,   # no clean point-in-time
    "ethena_usde":           SourceState.MANUAL_PROXY,
    # Under review — excluded from strict
    "morpho_steakhouse":     SourceState.PENDING,
    "yearn_v3_yvusdc":       SourceState.PENDING,
    "euler_v2_usdc":         SourceState.PENDING,
    # Needs owner/analyst verification
    "maple_syrupusdc":       SourceState.REVIEW,
    # No data source connected yet
    "btc_yield":             SourceState.SOURCE_NEEDED,
    "eth_staking":           SourceState.SOURCE_NEEDED,
    # RS-001 sources
    "gmx_btc":               SourceState.SOURCE_NEEDED,
    "gmx_eth":               SourceState.SOURCE_NEEDED,
    "btc_stable_pool":       SourceState.SOURCE_NEEDED,
    "gold_proxy":            SourceState.SOURCE_NEEDED,
    # RS-002 Cashflow sources
    "btc_usd_conc_liq":      SourceState.SOURCE_NEEDED,
    "rwa_conc_liq":          SourceState.SOURCE_NEEDED,
    "trader_losses_vault":   SourceState.SOURCE_NEEDED,
    # Research / model only
    "delta_neutral":         SourceState.RESEARCH_ONLY,
}


# ══════════════════════════════════════════════════════════════════════════════
# SourcePipeline
# ══════════════════════════════════════════════════════════════════════════════

class SourcePipeline:
    """
    Single source of truth for what's in strict evidence vs research.

    Initialized from DEFAULT_SOURCES. Can be updated via promote_source()
    or loaded from data/backtest/pre_paper_backtest_gate.json.

    State is persisted to data/backtest/source_pipeline.json atomically.

    Parameters
    ----------
    data_dir : str or Path, optional
        Directory for persistence. Defaults to <repo-root>/data/backtest/.
    sources : dict, optional
        Initial source → state mapping. Defaults to DEFAULT_SOURCES.
    """

    def __init__(
        self,
        data_dir: Optional[str | Path] = None,
        sources: Optional[Dict[str, str]] = None,
    ) -> None:
        if data_dir is None:
            self._data_dir = _DEFAULT_DATA_DIR
        else:
            self._data_dir = Path(data_dir)
        self._path = self._data_dir / _FILENAME

        # Initialise from persisted state if available, else from defaults
        persisted = self._load_from_disk()
        if persisted is not None:
            self._sources: Dict[str, str] = persisted["sources"]
            self._audit_log: list = persisted.get("audit_log", [])
        else:
            self._sources = dict(sources if sources is not None else DEFAULT_SOURCES)
            self._audit_log: list = []

    # ──────────────────────────────────────────────────────────────────────────
    # Query API
    # ──────────────────────────────────────────────────────────────────────────

    def state(self, source_id: str) -> str:
        """
        Return the state for source_id.
        Unknown sources default to SOURCE_NEEDED.
        """
        return self._sources.get(source_id, SourceState.SOURCE_NEEDED)

    def is_strict_eligible(self, source_id: str) -> bool:
        """Return True if source_id is CLEAN_INCLUDED."""
        return self.state(source_id) == SourceState.CLEAN_INCLUDED

    def can_affect_backtest(self, source_id: str) -> bool:
        """Return True if source_id can affect strict backtest (= CLEAN_INCLUDED)."""
        return SourceState.can_affect_backtest(self.state(source_id))

    def strict_sources(self) -> List[str]:
        """Return sorted list of CLEAN_INCLUDED source IDs."""
        return sorted(k for k, v in self._sources.items() if v == SourceState.CLEAN_INCLUDED)

    def research_sources(self) -> List[str]:
        """Return sorted list of RESEARCH_ONLY source IDs."""
        return sorted(k for k, v in self._sources.items() if v == SourceState.RESEARCH_ONLY)

    def pending_sources(self) -> List[str]:
        """Return sorted list of PENDING source IDs."""
        return sorted(k for k, v in self._sources.items() if v == SourceState.PENDING)

    def source_summary(self) -> Dict[str, int]:
        """
        Return counts of sources by state.

        Returns
        -------
        dict
            {state_str: count, ...} for all states present in the table.
        """
        counts: Dict[str, int] = {}
        for v in self._sources.values():
            counts[v] = counts.get(v, 0) + 1
        return counts

    def all_sources(self) -> Dict[str, str]:
        """Return a copy of the full source → state mapping."""
        return dict(self._sources)

    # ──────────────────────────────────────────────────────────────────────────
    # Mutation API
    # ──────────────────────────────────────────────────────────────────────────

    def promote_source(self, source_id: str, new_state: str, reason: str) -> None:
        """
        Change the state of a source and persist atomically.

        Parameters
        ----------
        source_id : str
            The source to promote/demote.
        new_state : str
            Target state (must be a valid SourceState).
        reason : str
            Audit reason string.

        Raises
        ------
        ValueError
            If new_state is not a valid SourceState.
        """
        if not SourceState.is_valid(new_state):
            raise ValueError(
                f"Invalid state '{new_state}'. "
                f"Must be one of: {sorted(SourceState._ALL_STATES)}"
            )
        old_state = self._sources.get(source_id, SourceState.SOURCE_NEEDED)
        self._sources[source_id] = new_state
        self._audit_log.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_id": source_id,
            "from_state": old_state,
            "to_state": new_state,
            "reason": reason,
        })
        self._save()

    # ──────────────────────────────────────────────────────────────────────────
    # Gate integration
    # ──────────────────────────────────────────────────────────────────────────

    def load_from_gate(self, gate_path: str) -> None:
        """
        Update source states from a pre_paper_backtest_gate.json file.

        Reads the "research_exclusions" array from the gate file and maps
        each entry's current_status to a SourceState. Known mappings:

          "clean_included"      → CLEAN_INCLUDED
          "pending"             → PENDING
          "research_only"       → RESEARCH_ONLY
          "model_only"          → RESEARCH_ONLY  (alias)
          "manual_proxy_only"   → MANUAL_PROXY
          "review"              → REVIEW
          "source_needed"       → SOURCE_NEEDED

        Only updates sources found in the gate file; others are unchanged.

        Parameters
        ----------
        gate_path : str
            Absolute path to pre_paper_backtest_gate.json.

        Raises
        ------
        FileNotFoundError
            If gate_path does not exist.
        json.JSONDecodeError
            If the file is not valid JSON.
        """
        gate_path_obj = Path(gate_path)
        if not gate_path_obj.exists():
            raise FileNotFoundError(f"Gate file not found: {gate_path}")

        with open(gate_path_obj, "r", encoding="utf-8") as fh:
            gate = json.load(fh)

        # Map gate current_status strings → SourceState
        _gate_status_map: Dict[str, str] = {
            "clean_included":    SourceState.CLEAN_INCLUDED,
            "pending":           SourceState.PENDING,
            "research_only":     SourceState.RESEARCH_ONLY,
            "model_only":        SourceState.RESEARCH_ONLY,   # alias
            "manual_proxy_only": SourceState.MANUAL_PROXY,
            "manual_proxy":      SourceState.MANUAL_PROXY,
            "review":            SourceState.REVIEW,
            "source_needed":     SourceState.SOURCE_NEEDED,
        }

        exclusions = gate.get("research_exclusions", [])
        for exc in exclusions:
            pid = exc.get("protocol_id", "")
            status = exc.get("current_status", "")
            mapped = _gate_status_map.get(status)
            if pid and mapped:
                reason = f"loaded from gate: {exc.get('reason', '')}"
                self.promote_source(pid, mapped, reason)

    # ──────────────────────────────────────────────────────────────────────────
    # Persistence
    # ──────────────────────────────────────────────────────────────────────────

    def _load_from_disk(self) -> Optional[dict]:
        """Load persisted state from disk. Returns None if not found or invalid."""
        if not self._path.exists():
            return None
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict) and "sources" in data:
                return data
        except (json.JSONDecodeError, OSError):
            pass
        return None

    def _save(self) -> None:
        """Atomically persist current state (atomic_save)."""
        atomic_save(
            {
                "schema_version": SCHEMA_VERSION,
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "sources": self._sources,
                "audit_log": self._audit_log,
            },
            str(self._path),
        )

    def save(self) -> None:
        """Public wrapper: persist current state to disk."""
        self._save()


# ─── CLI ──────────────────────────────────────────────────────────────────────

def _cli() -> None:  # pragma: no cover
    import sys
    pipeline = SourcePipeline()
    summary = pipeline.source_summary()
    print(json.dumps({
        "strict_sources": pipeline.strict_sources(),
        "pending_sources": pipeline.pending_sources(),
        "research_sources": pipeline.research_sources(),
        "summary": summary,
    }, indent=2))


if __name__ == "__main__":  # pragma: no cover
    _cli()
