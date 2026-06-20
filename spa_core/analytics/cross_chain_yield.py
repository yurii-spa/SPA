"""
spa_core/analytics/cross_chain_yield.py

Cross-chain yield comparison analytics.
Compares APY opportunities across Ethereum and Base.

MP-1487 (v11.03): Cross-chain yield comparator
Sprint: v11.03
Stdlib only — no external dependencies.
Read-only / advisory — never writes to execution or risk domain.
LLM FORBIDDEN in this module.

CLI:
    python3 -m spa_core.analytics.cross_chain_yield --check   # compute + print (default)
    python3 -m spa_core.analytics.cross_chain_yield --run     # + atomic write to data/

Output: data/cross_chain_yield.json
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from spa_core.base import BaseAnalytics
from spa_core.utils.errors import SPAError

# Module-level import so tests can patch spa_core.adapters.registry.ADAPTER_REGISTRY
try:
    from spa_core.adapters.registry import ADAPTER_REGISTRY as _ADAPTER_REGISTRY
except ImportError:
    _ADAPTER_REGISTRY = {}

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OUTPUT_PATH = "data/cross_chain_yield.json"

SUPPORTED_CHAINS = ["ethereum", "base"]

# Canonical chain names as stored in ADAPTER_REGISTRY["chain"] field.
# Registry uses title-case: "Ethereum", "Base", etc.
_CHAIN_CANONICAL: Dict[str, str] = {
    "ethereum": "Ethereum",
    "base":     "Base",
}

# Base-chain adapters are not yet in the main ADAPTER_REGISTRY.
# This supplementary map defines them so they can still be compared.
# Format: {adapter_id: {module, class, tier, chain, fallback_apy}}
_BASE_CHAIN_SUPPLEMENTARY: Dict[str, Dict[str, Any]] = {
    "aave_v3_base": {
        "module":      "spa_core.adapters.aave_v3_base_adapter",
        "class":       "AaveV3BaseAdapter",
        "tier":        "T2",
        "chain":       "Base",
        "fallback_apy": 5.2,
    },
    "morpho_blue_base": {
        "module":      "spa_core.adapters.morpho_blue_base_adapter",
        "class":       "MorphoBlueBaseAdapter",
        "tier":        "T2",
        "chain":       "Base",
        "fallback_apy": 6.2,
    },
    "moonwell_base": {
        "module":      "spa_core.adapters.moonwell_base_adapter",
        "class":       "MoonwellBaseAdapter",
        "tier":        "T2",
        "chain":       "Base",
        "fallback_apy": 5.5,
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_apy(adapter: Any, fallback: float) -> float:
    """Call adapter.get_apy() safely; return fallback on any error.

    `get_apy()` may raise, return None, or return an invalid type.
    This wrapper guarantees a non-negative float always.

    Args:
        adapter:  Any object with an optional ``get_apy()`` method.
        fallback: Value returned when live fetch is unavailable.

    Returns:
        APY as a percentage-point float (e.g. 4.8 means 4.8 %).
    """
    try:
        result = adapter.get_apy()
        if result is None:
            return float(fallback)
        val = float(result)
        # get_apy() returns decimal (0.048) in some adapters, percent in others.
        # Heuristic: values < 1.0 are likely decimals → convert to %.
        if val < 1.0 and val >= 0.0:
            val = val * 100.0
        return max(0.0, val)
    except Exception as exc:  # noqa: BLE001
        logger.debug("safe_apy fallback for %s: %s", type(adapter).__name__, exc)
        return float(fallback)


def _instantiate(meta: Dict[str, Any]) -> Any:
    """Import and instantiate the adapter class described by *meta*.

    Args:
        meta: Dict with keys ``module`` and ``class``.

    Returns:
        Adapter instance.

    Raises:
        ImportError: If the module cannot be imported.
        AttributeError: If the class is not found in the module.
    """
    mod = importlib.import_module(meta["module"])
    cls = getattr(mod, meta["class"])
    return cls()


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class CrossChainYieldComparator(BaseAnalytics):
    """Compares yield opportunities across Ethereum and Base chains.

    Usage::

        comparator = CrossChainYieldComparator(base_dir="/path/to/spa")
        data = comparator.compare_all()
        comparator.save(data)          # atomic write to data/cross_chain_yield.json

    All network calls in adapters are already wrapped in try/except; this
    class adds one more safety layer so a single broken adapter never aborts
    the full comparison run.
    """

    OUTPUT_PATH = OUTPUT_PATH
    SUPPORTED_CHAINS = SUPPORTED_CHAINS

    def __init__(self, base_dir: str = "."):
        super().__init__(base_dir)
        self._data: Dict[str, Any] = {
            "chains": {},
            "best_opportunities": [],
            "last_updated": None,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def collect_chain_data(self, chain: str) -> Dict[str, Any]:
        """Collect all adapter APYs for *chain*.

        Iterates the main ADAPTER_REGISTRY filtered by canonical chain name,
        then supplements with ``_BASE_CHAIN_SUPPLEMENTARY`` for Base.

        Args:
            chain: Lowercase chain name, e.g. ``"ethereum"`` or ``"base"``.

        Returns:
            Dict mapping adapter_id → ``{apy, tier, chain}``.
            On per-adapter failure, adds ``"error"`` key instead of raising.

        Raises:
            SPAError: If *chain* is not in ``SUPPORTED_CHAINS``.
        """
        chain_lower = chain.lower()
        if chain_lower not in SUPPORTED_CHAINS:
            raise SPAError(
                f"Unsupported chain '{chain}'. Supported: {SUPPORTED_CHAINS}"
            )

        canonical = _CHAIN_CANONICAL.get(chain_lower, chain.capitalize())
        results: Dict[str, Any] = {}

        # --- Main registry (covers Ethereum + future chains added there) ---
        # Uses module-level _ADAPTER_REGISTRY (patchable via spa_core.adapters.registry.ADAPTER_REGISTRY).
        from spa_core.adapters import registry as _reg_module
        registry_snapshot = getattr(_reg_module, "ADAPTER_REGISTRY", _ADAPTER_REGISTRY)

        for adapter_id, meta in registry_snapshot.items():
            reg_chain = meta.get("chain", "")
            if reg_chain.lower() != chain_lower:
                continue
            if meta.get("research_only", False):
                continue
            results[adapter_id] = self._fetch_adapter(adapter_id, meta)

        # --- Supplementary Base-chain adapters ---
        if chain_lower == "base":
            for adapter_id, meta in _BASE_CHAIN_SUPPLEMENTARY.items():
                if adapter_id not in results:  # avoid duplicates if ever added to registry
                    results[adapter_id] = self._fetch_adapter(adapter_id, meta)

        return results

    def compare_all(self) -> Dict[str, Any]:
        """Run comparison across all supported chains.

        Returns:
            Dict with keys:
                ``chains`` — per-chain adapter APY data,
                ``best_opportunities`` — top adapter per chain sorted by APY desc,
                ``last_updated`` — UTC ISO timestamp.
        """
        comparison: Dict[str, Any] = {}
        for chain in SUPPORTED_CHAINS:
            try:
                comparison[chain] = self.collect_chain_data(chain)
            except SPAError as exc:
                logger.warning("collect_chain_data failed for '%s': %s", chain, exc)
                comparison[chain] = {}

        # Find best per chain
        best: List[Dict[str, Any]] = []
        for chain, adapters in comparison.items():
            if not adapters:
                continue
            # Filter to entries that have numeric apy
            valid = {k: v for k, v in adapters.items() if isinstance(v.get("apy"), (int, float))}
            if not valid:
                continue
            top_id, top_meta = max(valid.items(), key=lambda kv: kv[1]["apy"])
            best.append({
                "chain":   chain,
                "adapter": top_id,
                "apy":     top_meta["apy"],
                "tier":    top_meta.get("tier", "?"),
            })

        self._data = {
            "chains":            comparison,
            "best_opportunities": sorted(best, key=lambda x: x["apy"], reverse=True),
            "last_updated":      datetime.now(timezone.utc).isoformat(),
        }
        return self._data

    def to_dict(self) -> Dict[str, Any]:
        """Return the last computed data snapshot."""
        return self._data

    def best_chain(self) -> Optional[str]:
        """Return the chain name with the highest best APY, or None if no data."""
        opps = self._data.get("best_opportunities", [])
        if not opps:
            return None
        return opps[0]["chain"]

    def apy_spread(self) -> float:
        """Return APY spread (best - second-best) across chains. 0.0 if < 2 chains."""
        opps = self._data.get("best_opportunities", [])
        if len(opps) < 2:
            return 0.0
        return round(opps[0]["apy"] - opps[1]["apy"], 4)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _fetch_adapter(self, adapter_id: str, meta: Dict[str, Any]) -> Dict[str, Any]:
        """Instantiate adapter and return its APY + metadata.

        Never raises — all exceptions are caught and returned as ``error`` key.
        """
        fallback = float(meta.get("fallback_apy", 0.0))
        tier = meta.get("tier", "?")
        chain = meta.get("chain", "?")
        try:
            adapter = _instantiate(meta)
            apy = _safe_apy(adapter, fallback)
        except Exception as exc:  # noqa: BLE001
            return {
                "apy":   fallback,
                "tier":  tier,
                "chain": chain,
                "error": str(exc),
            }
        return {
            "apy":   apy,
            "tier":  tier,
            "chain": chain,
        }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _run(write: bool = False, base_dir: str = ".") -> int:
    """Main CLI logic. Returns exit code."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    comp = CrossChainYieldComparator(base_dir=base_dir)
    data = comp.compare_all()

    # Pretty print
    print("\n=== Cross-Chain Yield Comparison ===")
    for chain, adapters in data["chains"].items():
        print(f"\n  Chain: {chain.upper()}")
        for adapter_id, info in adapters.items():
            apy_str = f"{info['apy']:.2f}%" if isinstance(info.get("apy"), (int, float)) else "N/A"
            err_str = f"  [err: {info['error']}]" if "error" in info else ""
            print(f"    {adapter_id:30s}  APY={apy_str:8s}  Tier={info.get('tier','?')}{err_str}")

    print("\n  Best opportunities (by chain):")
    for opp in data["best_opportunities"]:
        print(f"    {opp['chain'].upper():10s}  {opp['adapter']:30s}  APY={opp['apy']:.2f}%")

    print(f"\n  APY spread (best - 2nd): {comp.apy_spread():.2f}%")
    print(f"  Best chain: {comp.best_chain()}")
    print(f"\n  Last updated: {data['last_updated']}")

    if write:
        path = comp.save(data)
        print(f"\n  Saved → {path}")
    else:
        print("\n  (dry run — use --run to write)")

    return 0


if __name__ == "__main__":
    _mode = "--run" in sys.argv
    sys.exit(_run(write=_mode))
