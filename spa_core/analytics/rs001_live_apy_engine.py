"""
spa_core/analytics/rs001_live_apy_engine.py — RS-001 Live APY Wiring (MP-1316)

Assembles live APY composition for RS-001 Anti-Crisis Research Strategy.

Sources:
  CLEAN (strict evidence): stablecoin_t1 (15% weight) → Aave V3 / Morpho real APY
  RESEARCH: gmx_btc_exposure, gmx_eth_exposure, gold_proxy  → research adapters
  PLACEHOLDER: btc_stable_pool, eth_aggressive_pool          → static estimates

Each slot returns:
  {
    "slot_id":        str,
    "weight":         float,
    "apy":            float,
    "source":         str,    # e.g. "aave_v3_usdc_clean", "gmx_research_fallback"
    "source_quality": "CLEAN" | "RESEARCH" | "PLACEHOLDER",
    "note":           str | None,
  }

blended_apy() shows total weighted APY; clean_fraction_apy() shows the
contribution from strict-evidence sources only.

save() writes atomically to data/research/rs001_apy_breakdown.json.

Rules:
  - stdlib only — no external dependencies
  - Atomic writes: tmp file + os.replace
  - Read-only / advisory — does NOT modify allocator / risk / execution
  - LLM FORBIDDEN
  - Exit 0 always (never raises from main)

Date: 2026-06-19 (MP-1316, Sprint v9.32)
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Repository root (two levels up: spa_core/analytics/ → spa_core/ → repo) ──
_HERE = Path(__file__).resolve().parent
_DEFAULT_REPO_ROOT = _HERE.parent.parent

# ── Slot definitions ──────────────────────────────────────────────────────────

# Matches RESEARCH_WEIGHTS in s20_anticrisis_research.py
_SLOT_DEFS = [
    {
        "slot_id":        "stablecoin_t1",
        "weight":         0.15,
        "source_quality": "CLEAN",
        "placeholder_apy": 3.5,
        "note": "Live Aave V3 / Morpho Steakhouse USDC APY (T1 tier)",
    },
    {
        "slot_id":        "gmx_btc_exposure",
        "weight":         0.20,
        "source_quality": "RESEARCH",
        "placeholder_apy": 15.0,
        "note": "GMX GLP/GM BTC APY via DeFiLlama (research, no point-in-time history)",
    },
    {
        "slot_id":        "gmx_eth_exposure",
        "weight":         0.10,
        "source_quality": "RESEARCH",
        "placeholder_apy": 15.0,
        "note": "GMX GLP/GM ETH APY via DeFiLlama (research, no point-in-time history)",
    },
    {
        "slot_id":        "btc_stable_pool",
        "weight":         0.35,
        "source_quality": "PLACEHOLDER",
        "placeholder_apy": 25.0,
        "note": "BTC-correlated stable pool — venue unspecified; SOURCE_NEEDED",
    },
    {
        "slot_id":        "eth_aggressive_pool",
        "weight":         0.05,
        "source_quality": "PLACEHOLDER",
        "placeholder_apy": 45.0,
        "note": "ETH aggressive pool — pool unspecified; SOURCE_NEEDED",
    },
    {
        "slot_id":        "gold_proxy",
        "weight":         0.15,
        "source_quality": "RESEARCH",
        "placeholder_apy": 8.0,
        "note": "Gold proxy APY via GoldProxyResearchAdapter (research, identity unconfirmed)",
    },
]

# Expected total weight (sanity check)
_EXPECTED_TOTAL_WEIGHT: float = 1.0

# Default save path (relative to repo root)
_DEFAULT_DATA_PATH = "data/research/rs001_apy_breakdown.json"

# Status thresholds
_CLEAN_DOMINATED_THRESHOLD: float = 0.50  # if clean_pct_of_capital > 50%, CLEAN_DOMINATED


# ── RS001LiveAPYEngine ────────────────────────────────────────────────────────

class RS001LiveAPYEngine:
    """Assembles live APY composition for the RS-001 Anti-Crisis Research Strategy.

    Tries to load:
      - AaveV3Adapter or MorphoSteakhouseAdapter for stablecoin_t1 (CLEAN)
      - GMXResearchAdapter for gmx_btc / gmx_eth (RESEARCH)
      - GoldProxyResearchAdapter for gold_proxy (RESEARCH)
      - Static placeholders for btc_stable_pool / eth_aggressive_pool (PLACEHOLDER)

    All adapter imports are wrapped in try/except — failure falls back to
    placeholder APY values. Never raises from public methods.

    Args:
        repo_root: Override repo root for save() path resolution.
    """

    def __init__(self, repo_root: Optional[str] = None) -> None:
        self._repo_root = Path(repo_root) if repo_root else _DEFAULT_REPO_ROOT

        # Try to load live adapters (fail silently)
        self._stablecoin_adapter = None
        self._stablecoin_source: str = "placeholder_fallback"
        self._gmx_adapter = None
        self._gold_adapter = None

        self._load_adapters()

    # ── Adapter loading ───────────────────────────────────────────────────────

    def _load_adapters(self) -> None:
        """Import and instantiate research adapters. Fail silently on any error."""
        # --- stablecoin_t1 (CLEAN): try Aave V3, then Morpho ---
        for loader in (self._try_load_aave, self._try_load_morpho):
            try:
                adapter, source = loader()
                if adapter is not None:
                    self._stablecoin_adapter = adapter
                    self._stablecoin_source = source
                    break
            except Exception:
                pass

        # --- GMX research ---
        try:
            from spa_core.adapters.gmx_research import GMXResearchAdapter  # type: ignore
            self._gmx_adapter = GMXResearchAdapter()
        except Exception as exc:
            logger.debug("RS001LiveAPYEngine: GMXResearchAdapter not loaded: %s", exc)

        # --- Gold proxy research ---
        try:
            from spa_core.adapters.gold_proxy_research import GoldProxyResearchAdapter  # type: ignore
            self._gold_adapter = GoldProxyResearchAdapter()
        except Exception as exc:
            logger.debug("RS001LiveAPYEngine: GoldProxyResearchAdapter not loaded: %s", exc)

    @staticmethod
    def _try_load_aave():
        from spa_core.adapters.aave_v3 import AaveV3Adapter  # type: ignore
        return AaveV3Adapter(), "aave_v3_usdc_clean"

    @staticmethod
    def _try_load_morpho():
        from spa_core.adapters.morpho_steakhouse_adapter import MorphoSteakhouseAdapter  # type: ignore
        return MorphoSteakhouseAdapter(), "morpho_steakhouse_clean"

    # ── APY resolution ────────────────────────────────────────────────────────

    def _resolve_stablecoin_apy(self) -> tuple[float, str]:
        """Return (apy_pct, source_label) for stablecoin_t1 slot.

        AaveV3Adapter.get_apy() returns a decimal (0.035 = 3.5%).
        MorphoSteakhouseAdapter.get_apy() also returns a decimal.
        Returns placeholder on any failure.
        """
        if self._stablecoin_adapter is None:
            return 3.5, "placeholder_stablecoin_t1"
        try:
            apy_decimal = self._stablecoin_adapter.get_apy()
            if isinstance(apy_decimal, (int, float)) and not isinstance(apy_decimal, bool):
                apy_pct = float(apy_decimal) * 100.0  # decimal → percent
                if 0 < apy_pct <= 50:  # sanity bounds for stablecoin
                    return apy_pct, self._stablecoin_source
        except Exception as exc:
            logger.debug("RS001LiveAPYEngine: stablecoin adapter error: %s", exc)
        return 3.5, f"{self._stablecoin_source}_fallback"

    def _resolve_gmx_btc_apy(self) -> tuple[float, str]:
        if self._gmx_adapter is None:
            return 15.0, "gmx_research_not_loaded"
        try:
            apy = self._gmx_adapter.btc_exposure_apy()
            if isinstance(apy, (int, float)) and not isinstance(apy, bool) and apy > 0:
                return float(apy), "gmx_research_live"
        except Exception as exc:
            logger.debug("RS001LiveAPYEngine: GMX BTC error: %s", exc)
        return 15.0, "gmx_research_fallback"

    def _resolve_gmx_eth_apy(self) -> tuple[float, str]:
        if self._gmx_adapter is None:
            return 15.0, "gmx_research_not_loaded"
        try:
            apy = self._gmx_adapter.eth_exposure_apy()
            if isinstance(apy, (int, float)) and not isinstance(apy, bool) and apy > 0:
                return float(apy), "gmx_research_live"
        except Exception as exc:
            logger.debug("RS001LiveAPYEngine: GMX ETH error: %s", exc)
        return 15.0, "gmx_research_fallback"

    def _resolve_gold_proxy_apy(self) -> tuple[float, str]:
        if self._gold_adapter is None:
            return 8.0, "gold_proxy_not_loaded"
        try:
            apy = self._gold_adapter.gold_proxy_apy()
            if isinstance(apy, (int, float)) and not isinstance(apy, bool) and apy > 0:
                return float(apy), "gold_proxy_research_live"
        except Exception as exc:
            logger.debug("RS001LiveAPYEngine: gold proxy error: %s", exc)
        return 8.0, "gold_proxy_research_fallback"

    def _resolve_slot(self, slot_def: dict) -> dict:
        """Build a fully resolved slot entry dict."""
        sid = slot_def["slot_id"]
        weight = slot_def["weight"]
        quality = slot_def["source_quality"]

        if sid == "stablecoin_t1":
            apy, source = self._resolve_stablecoin_apy()
        elif sid == "gmx_btc_exposure":
            apy, source = self._resolve_gmx_btc_apy()
        elif sid == "gmx_eth_exposure":
            apy, source = self._resolve_gmx_eth_apy()
        elif sid == "btc_stable_pool":
            apy = slot_def["placeholder_apy"]
            source = "placeholder_btc_stable_source_needed"
        elif sid == "eth_aggressive_pool":
            apy = slot_def["placeholder_apy"]
            source = "placeholder_eth_aggressive_source_needed"
        elif sid == "gold_proxy":
            apy, source = self._resolve_gold_proxy_apy()
        else:
            apy = slot_def["placeholder_apy"]
            source = f"placeholder_{sid}"

        return {
            "slot_id":        sid,
            "weight":         weight,
            "apy":            round(float(apy), 6),
            "source":         source,
            "source_quality": quality,
            "note":           slot_def.get("note"),
        }

    # ── Public API ────────────────────────────────────────────────────────────

    def slot_apys(self) -> list:
        """Return APY breakdown for all 6 RS-001 slots.

        Returns:
            List of dicts, each with: slot_id, weight, apy, source,
            source_quality ("CLEAN"|"RESEARCH"|"PLACEHOLDER"), note.
        """
        return [self._resolve_slot(s) for s in _SLOT_DEFS]

    def blended_apy(self) -> float:
        """Weighted blended APY across all slots (percent).

        Returns:
            Blended APY in percent (float ≥ 0).
        """
        slots = self.slot_apys()
        total = sum(s["weight"] * s["apy"] for s in slots)
        return round(total, 6)

    def clean_fraction_apy(self) -> float:
        """APY contribution (percent) from CLEAN sources only.

        Returns:
            Weighted APY contribution from strict-evidence slots only.
        """
        slots = self.slot_apys()
        total = sum(
            s["weight"] * s["apy"]
            for s in slots
            if s["source_quality"] == "CLEAN"
        )
        return round(total, 6)

    def research_fraction_apy(self) -> float:
        """APY contribution (percent) from RESEARCH sources only.

        Returns:
            Weighted APY contribution from research (non-clean, non-placeholder) slots.
        """
        slots = self.slot_apys()
        total = sum(
            s["weight"] * s["apy"]
            for s in slots
            if s["source_quality"] == "RESEARCH"
        )
        return round(total, 6)

    def placeholder_fraction_apy(self) -> float:
        """APY contribution (percent) from PLACEHOLDER sources only."""
        slots = self.slot_apys()
        total = sum(
            s["weight"] * s["apy"]
            for s in slots
            if s["source_quality"] == "PLACEHOLDER"
        )
        return round(total, 6)

    def apy_breakdown_report(self) -> dict:
        """Full APY breakdown report for RS-001.

        Returns:
            {
              "blended":              float,
              "clean_contribution":   float,  # APY from CLEAN slots (pct weighted)
              "research_contribution": float, # APY from RESEARCH slots
              "placeholder_contribution": float,
              "clean_pct_of_capital": float,  # % of capital with CLEAN sources
              "slots":                list,
              "status":               "RESEARCH_DOMINATED" | "CLEAN_DOMINATED",
              "schema_version":       "1.0",
              "strategy_id":          "RS-001",
              "generated_at":         str,
            }
        """
        slots = self.slot_apys()
        blended = round(sum(s["weight"] * s["apy"] for s in slots), 6)
        clean_contrib = round(
            sum(s["weight"] * s["apy"] for s in slots if s["source_quality"] == "CLEAN"),
            6,
        )
        research_contrib = round(
            sum(s["weight"] * s["apy"] for s in slots if s["source_quality"] == "RESEARCH"),
            6,
        )
        placeholder_contrib = round(
            sum(s["weight"] * s["apy"] for s in slots if s["source_quality"] == "PLACEHOLDER"),
            6,
        )
        clean_pct_of_capital = round(
            sum(s["weight"] for s in slots if s["source_quality"] == "CLEAN") * 100.0,
            4,
        )

        if clean_pct_of_capital > _CLEAN_DOMINATED_THRESHOLD * 100:
            status = "CLEAN_DOMINATED"
        else:
            status = "RESEARCH_DOMINATED"

        return {
            "blended":                    blended,
            "clean_contribution":         clean_contrib,
            "research_contribution":      research_contrib,
            "placeholder_contribution":   placeholder_contrib,
            "clean_pct_of_capital":       clean_pct_of_capital,
            "slots":                      slots,
            "status":                     status,
            "schema_version":             "1.0",
            "strategy_id":                "RS-001",
            "generated_at":               datetime.now(timezone.utc).isoformat(),
        }

    def save(self, path: Optional[str] = None) -> None:
        """Atomically write apy_breakdown_report() to disk (tmp + os.replace).

        Args:
            path: Absolute or relative path for output file.
                  Default: <repo_root>/data/research/rs001_apy_breakdown.json
        """
        if path is None:
            out_path = self._repo_root / _DEFAULT_DATA_PATH
        else:
            out_path = Path(path)

        out_path.parent.mkdir(parents=True, exist_ok=True)

        report = self.apy_breakdown_report()

        from spa_core.utils.atomic import atomic_save
        atomic_save(report, str(out_path))
        logger.info("RS001LiveAPYEngine.save: wrote %s", out_path)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cli() -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="RS-001 Live APY Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--check", action="store_true",
                        help="Compute and print breakdown without writing.")
    parser.add_argument("--run", action="store_true",
                        help="Compute + atomically write to data/research/rs001_apy_breakdown.json.")
    parser.add_argument("--data-dir", dest="data_dir", default=None,
                        help="Override output directory.")
    args = parser.parse_args()

    engine = RS001LiveAPYEngine()

    if args.run:
        out_path = (
            str(Path(args.data_dir) / "rs001_apy_breakdown.json")
            if args.data_dir
            else None
        )
        engine.save(path=out_path)
        report = engine.apy_breakdown_report()
        print(json.dumps(report, indent=2))
        print(
            f"\nBlended APY: {report['blended']:.2f}%  "
            f"Status: {report['status']}  "
            f"Clean capital: {report['clean_pct_of_capital']:.1f}%",
            file=sys.stderr,
        )
    else:
        report = engine.apy_breakdown_report()
        print(json.dumps(report, indent=2))
        print("\n[DRY RUN] No data written. Use --run to persist.", file=sys.stderr)


if __name__ == "__main__":
    import sys
    try:
        _cli()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(0)
