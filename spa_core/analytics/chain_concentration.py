"""Chain Concentration Analyzer (MP-387) — read-only / advisory.

Reads ``data/adapter_status.json``, computes per-chain allocation weights,
checks compliance against the 70 % single-chain cap (ADR), and emits
rebalance suggestions when ethereum concentration is excessive.

Design constraints
------------------
* Stdlib only (json / os / datetime / tempfile / pathlib) — no numpy/requests.
* Atomic writes: ``tmp + os.replace``.
* Pure advisory — never touches allocator / risk / execution.
* Exit-0 always; IO errors degrade gracefully to empty results.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHAIN_CONCENTRATION_LIMIT: float = 0.70  # ADR: max 70 % single chain

CHAINS: List[str] = ["ethereum", "arbitrum", "optimism", "polygon", "base"]


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

class ChainConcentrationAnalyzer:
    """Compute chain-level concentration and emit rebalance suggestions.

    Parameters
    ----------
    adapter_status_path:
        Path to ``data/adapter_status.json``.  Can be relative (resolved at
        call time) or absolute.
    """

    def __init__(self, adapter_status_path: str = "data/adapter_status.json") -> None:
        self._path: str = adapter_status_path

    # ------------------------------------------------------------------
    # Core computation
    # ------------------------------------------------------------------

    def load_allocations(self) -> Dict[str, float]:
        """Read active-adapter chain allocations from adapter_status.json.

        For each adapter in the ``adapters`` list whose ``allocation_cap``
        is positive, the cap is split evenly across the adapter's supported
        chains.  Adapters with ``allocation_cap == 0`` (e.g. sky-susds in
        paper-period) are excluded.

        Returns
        -------
        dict
            ``{chain_name: total_weight}`` — un-normalised raw weights.
            Returns ``{}`` if the file is missing or unparseable.
        """
        try:
            with open(self._path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

        if not isinstance(data, dict):
            return {}

        allocations: Dict[str, float] = {}
        for adapter in data.get("adapters", []):
            if not isinstance(adapter, dict):
                continue
            cap = adapter.get("allocation_cap", 0.0)
            if not isinstance(cap, (int, float)) or cap <= 0:
                continue
            chains: List[str] = adapter.get("chains", [])
            if not chains:
                continue
            per_chain = float(cap) / len(chains)
            for chain in chains:
                chain_key = str(chain).lower()
                allocations[chain_key] = allocations.get(chain_key, 0.0) + per_chain

        return allocations

    def compute_concentrations(self, allocations: Optional[Dict[str, float]] = None) -> Dict[str, float]:
        """Normalise raw chain allocations to fractions summing to 1.0.

        Parameters
        ----------
        allocations:
            Raw ``{chain: weight}`` dict.  If *None*, calls
            :meth:`load_allocations` automatically.

        Returns
        -------
        dict
            ``{chain: fraction}`` where all fractions sum to 1.0, or ``{}``
            if there are no positive weights.
        """
        if allocations is None:
            allocations = self.load_allocations()

        positive = {
            chain: float(w)
            for chain, w in (allocations or {}).items()
            if isinstance(w, (int, float)) and float(w) > 0
        }
        total = sum(positive.values())
        if total <= 0:
            return {}
        return {chain: w / total for chain, w in positive.items()}

    def is_compliant(self, concentrations: Optional[Dict[str, float]] = None) -> bool:
        """Return True if no single chain exceeds :data:`CHAIN_CONCENTRATION_LIMIT`.

        Parameters
        ----------
        concentrations:
            Pre-computed ``{chain: fraction}`` dict.  If *None*, computed
            from :meth:`load_allocations`.

        Returns
        -------
        bool
            ``True`` when ``max(fractions) <= CHAIN_CONCENTRATION_LIMIT`` or
            the concentrations dict is empty (nothing deployed).
        """
        if concentrations is None:
            concentrations = self.compute_concentrations(self.load_allocations())
        if not concentrations:
            return True
        return max(concentrations.values()) <= CHAIN_CONCENTRATION_LIMIT

    def get_over_concentrated_chains(
        self, concentrations: Optional[Dict[str, float]] = None
    ) -> List[Tuple[str, float]]:
        """Return chains whose concentration strictly exceeds the limit.

        Parameters
        ----------
        concentrations:
            Pre-computed ``{chain: fraction}`` dict.  If *None*, computed
            automatically.

        Returns
        -------
        list of (chain, fraction)
            Sorted by fraction descending; empty when portfolio is compliant.
        """
        if concentrations is None:
            concentrations = self.compute_concentrations(self.load_allocations())
        over = [
            (chain, frac)
            for chain, frac in (concentrations or {}).items()
            if frac > CHAIN_CONCENTRATION_LIMIT
        ]
        return sorted(over, key=lambda x: -x[1])

    def get_rebalance_suggestions(
        self, concentrations: Optional[Dict[str, float]] = None
    ) -> List[Dict[str, Any]]:
        """Emit advisory rebalance suggestions for over-concentrated chains.

        * If **ethereum** is over-concentrated → suggest increasing **arbitrum**
          allocation by the excess (minimum 0.05).
        * For any other over-concentrated chain → suggest reducing that chain.

        Parameters
        ----------
        concentrations:
            Pre-computed ``{chain: fraction}`` dict.  If *None*, computed
            automatically.

        Returns
        -------
        list of dicts
            Each dict: ``{action, chain, reason, target_delta}``.
            Empty list when portfolio is compliant.
        """
        if concentrations is None:
            concentrations = self.compute_concentrations(self.load_allocations())

        suggestions: List[Dict[str, Any]] = []
        limit_pct = int(CHAIN_CONCENTRATION_LIMIT * 100)

        for chain, frac in (concentrations or {}).items():
            if frac <= CHAIN_CONCENTRATION_LIMIT:
                continue
            excess = frac - CHAIN_CONCENTRATION_LIMIT
            if chain == "ethereum":
                suggestions.append(
                    {
                        "action": "increase",
                        "chain": "arbitrum",
                        "reason": f"ethereum > {limit_pct}%",
                        "target_delta": round(max(excess, 0.05), 4),
                    }
                )
            else:
                suggestions.append(
                    {
                        "action": "reduce",
                        "chain": chain,
                        "reason": f"{chain} > {limit_pct}%",
                        "target_delta": round(excess, 4),
                    }
                )

        return suggestions

    # ------------------------------------------------------------------
    # Snapshot / persistence
    # ------------------------------------------------------------------

    def summary(self) -> Dict[str, Any]:
        """Return a full compliance snapshot as a JSON-serialisable dict.

        Keys: ``concentrations``, ``compliant``, ``suggestions``,
        ``timestamp`` (Unix epoch int).
        """
        allocations = self.load_allocations()
        concentrations = self.compute_concentrations(allocations)
        compliant = self.is_compliant(concentrations)
        suggestions = self.get_rebalance_suggestions(concentrations)
        rounded = {chain: round(frac, 4) for chain, frac in concentrations.items()}
        return {
            "concentrations": rounded,
            "compliant": compliant,
            "suggestions": suggestions,
            "timestamp": int(datetime.now(timezone.utc).timestamp()),
        }

    def save_report(self, path: str = "data/chain_concentration.json") -> None:
        """Atomically write :meth:`summary` to *path* (tmp + os.replace).

        Parameters
        ----------
        path:
            Destination JSON file.  Parent directory must exist.
        """
        data = self.summary()
        atomic_save(data, str(path))
# ---------------------------------------------------------------------------
# CLI (offline, exit 0 always)
# ---------------------------------------------------------------------------

def _main() -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Chain Concentration Analyzer (MP-387)"
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Compute and atomically write data/chain_concentration.json",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=True,
        help="Compute and print (default; no write)",
    )
    parser.add_argument("--data-dir", default="data", help="Override data directory")
    args = parser.parse_args()

    adapter_path = str(Path(args.data_dir) / "adapter_status.json")
    analyzer = ChainConcentrationAnalyzer(adapter_status_path=adapter_path)
    snap = analyzer.summary()

    print(json.dumps(snap, indent=2))

    if args.run:
        out_path = str(Path(args.data_dir) / "chain_concentration.json")
        try:
            analyzer.save_report(out_path)
            print(f"[chain_concentration] Written → {out_path}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print(f"[chain_concentration] ERROR writing report: {exc}", file=sys.stderr)


if __name__ == "__main__":
    _main()
