# LLM_FORBIDDEN
"""
SPA Mass Strategy Tournament v1.0
spa_core/backtesting/mass_tournament.py

Discovers every strategy file in spa_core/strategies/s*.py, extracts its
allocation vector, runs a full 4-year backtest (2022-2025) via
ProfessionalBacktest.run_strategy(), and builds a Sharpe-sorted leaderboard.

LLM_FORBIDDEN: no LLM calls. All logic is deterministic.

Constraints
-----------
* stdlib only — zero external dependencies
* Atomic writes: write to <path>.tmp then shutil.move
* Advisory / read-only — never imports execution/, feed_health/, or risk agents
* approved=False from RiskPolicy cannot be overridden anywhere here
"""
# LLM_FORBIDDEN

from __future__ import annotations

import importlib
import json
import logging
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from spa_core.backtesting.professional_backtest import ProfessionalBacktest

_log = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_STRATEGIES_DIR = _PROJECT_ROOT / "spa_core" / "strategies"
_DATA_DIR = _PROJECT_ROOT / "data"

VERSION = "v1.0"

# ─────────────────────────────────────────────────────────────────────────────
# Protocol universe
# ─────────────────────────────────────────────────────────────────────────────

# Protocols that ProfessionalBacktest has APY history for
KNOWN_PROTOCOLS = frozenset({
    "aave_v3",
    "compound_v3",
    "morpho_steakhouse",
    "spark_susds",
    "maple",
    "euler_v2",
    "yearn_v3",
})

# Map strategy-specific protocol keys → backtest engine keys.
# None means "drop this protocol" (contributes 0 % yield, not included in weights).
PROTOCOL_ALIAS: Dict[str, Optional[str]] = {
    # Variants of known protocols
    "morpho_blue":          "morpho_steakhouse",
    "morpho_blue_base":     "morpho_steakhouse",
    "morpho_base":          "morpho_steakhouse",
    "morpho":               "morpho_steakhouse",
    "sky_susds":            "spark_susds",
    "sky_dai":              "spark_susds",
    "sky":                  "spark_susds",
    "aave_v3_arbitrum":     "aave_v3",
    "aave_v3_base":         "aave_v3",
    "aave_v3_optimism":     "aave_v3",
    "aave_v3_polygon":      "aave_v3",
    "aave_arbitrum":        "aave_v3",
    "aave_base":            "aave_v3",
    "aave_mainnet":         "aave_v3",
    "aave_usdc":            "aave_v3",
    "aave":                 "aave_v3",
    "compound_usdc":        "compound_v3",
    "compound":             "compound_v3",
    "fluid":                "euler_v2",
    "fluid_adapter":        "euler_v2",
    "fluid_fusdc":          "euler_v2",
    "moonwell_base":        "euler_v2",   # closest T2 lending proxy
    "radiant_arbitrum":     "euler_v2",   # T2 lending proxy
    "yearn":                "yearn_v3",
    "maple_usdc":           "maple",
    # Explicitly dropped (no reliable historical series / T3-SPEC)
    "cash":                 None,
    "pendle_pt":            None,
    "pendle_yt":            None,
    "ethena_susde":         None,
    "susde_spot":           None,
    "perp_short_hedge":     None,
    "aerodrome":            None,
    "aerodrome_base":       None,
    "velodrome":            None,
    "velodrome_optimism":   None,
    "gmx_glp":              None,
    "glp":                  None,
    "sushi_stable":         None,
    "crv":                  None,
    "cvx":                  None,
    "convex":               None,
    "curve":                None,
    "radiant":              None,
}

# Mock APY snapshot used when a strategy's get_allocation() needs live rates.
# Values in decimal (0.035 = 3.5 %).
MOCK_APY: Dict[str, float] = {
    "aave_v3":           0.035,
    "compound_v3":       0.052,
    "morpho_steakhouse": 0.058,
    "morpho_blue":       0.058,
    "spark_susds":       0.055,
    "sky_susds":         0.055,
    "maple":             0.068,
    "euler_v2":          0.062,
    "yearn_v3":          0.048,
    "pendle_pt":         0.072,
    "aave_v3_arbitrum":  0.046,
    "fluid":             0.062,
    "fluid_adapter":     0.062,
}

INITIAL_CAPITAL = 100_000.0

# Files to skip (not actual strategy implementations)
_SKIP_FILES = frozenset({
    "strategy_registry.py",
    "strategy_selector.py",
    "strategy_config.py",
})

# Module name prefix for strategy imports
_MODULE_PREFIX = "spa_core.strategies"


# ─────────────────────────────────────────────────────────────────────────────
# Atomic write helper
# ─────────────────────────────────────────────────────────────────────────────

def _atomic_write_json(path: Path, data: Any) -> None:
    """Write *data* as JSON to *path* atomically (tmp + shutil.move)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, default=str)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(payload)
    shutil.move(tmp, str(path))


# ─────────────────────────────────────────────────────────────────────────────
# MassTournament
# ─────────────────────────────────────────────────────────────────────────────

class MassTournament:
    """
    Discovers all strategy files, extracts allocation vectors, runs each
    through ProfessionalBacktest, and builds a Sharpe-sorted leaderboard.

    Usage
    -----
    mt = MassTournament()
    result = mt.run()      # returns dict; also saves data/mass_tournament_results.json
    """

    def __init__(
        self,
        strategies_dir: Optional[Path] = None,
        data_dir: Optional[Path] = None,
        add_noise: bool = True,
    ) -> None:
        self._strategies_dir = Path(strategies_dir) if strategies_dir else _STRATEGIES_DIR
        self._data_dir = Path(data_dir) if data_dir else _DATA_DIR
        self._add_noise = add_noise
        self._backtest = ProfessionalBacktest(
            data_dir=self._data_dir,
            add_noise=add_noise,
        )

    # ── Strategy file discovery ───────────────────────────────────────────────

    def discover_strategy_files(self) -> List[Path]:
        """Return all s*.py strategy files, excluding registry/config helpers."""
        return sorted([
            p for p in self._strategies_dir.glob("s*.py")
            if p.name not in _SKIP_FILES
        ])

    # ── Source-code analysis ──────────────────────────────────────────────────

    @staticmethod
    def detect_leverage(content: str) -> bool:
        """Return True if source code shows leverage / looping constructs."""
        patterns = [
            r'\bborrow_amount\s*[:=]',      # dataclass field or assignment
            r'\bLOOP_FACTOR\b',             # loop factor constant
            r'\bMAX_LOOPS\b',               # loop count constant
            r'\bloop_factor\b',             # runtime variable
            r'deposit.*borrow.*re.?deposit', # textual description
            r'recursive.*borrow',
        ]
        for pat in patterns:
            if re.search(pat, content, re.IGNORECASE):
                return True
        return False

    @staticmethod
    def detect_amm_lp(content: str) -> bool:
        """Return True if strategy is an AMM LP (not pure lending)."""
        patterns = [
            r'\b_is_lp_pool\b',
            r'\bimpermanent_loss\b',
            r'\badd_liquidity\b',
            r'\blp_stable\b',
        ]
        for pat in patterns:
            if re.search(pat, content, re.IGNORECASE):
                return True
        return False

    @staticmethod
    def find_primary_class(content: str) -> Optional[str]:
        """Return the best strategy class name found in *content*.

        Priority:
        1. Class that has ``def get_allocation`` in its body
        2. Class whose name ends with 'Strategy' or matches S\d+ pattern
        3. First public class that is not a config/mixin/helper
        """
        # Find all public class names
        all_classes = re.findall(r"^class (\w+)", content, re.MULTILINE)
        skip_names = {"AdapterAPYMixin", "AdapterMixin"}
        config_suffixes = ("Config", "Mixin", "Helper", "Error", "Exception")
        public = [c for c in all_classes
                  if not c.startswith("_") and c not in skip_names]
        if not public:
            return None

        # Prefer the class that defines get_allocation
        # Parse class bodies (rough: find class X:...class Y: boundaries)
        class_body_re = re.compile(
            r"^class (\w+)[^\n]*:\n((?:(?!^class ).*\n)*)",
            re.MULTILINE,
        )
        for m in class_body_re.finditer(content):
            cls_name, body = m.group(1), m.group(2)
            if cls_name in public and "def get_allocation" in body:
                return cls_name
        # Also check get_target_weights
        for m in class_body_re.finditer(content):
            cls_name, body = m.group(1), m.group(2)
            if cls_name in public and "def get_target_weights" in body:
                return cls_name

        # Fall back: skip config/mixin classes, prefer strategy-named ones
        strategy_classes = [
            c for c in public
            if not any(c.endswith(s) for s in config_suffixes)
        ]
        if strategy_classes:
            return strategy_classes[0]

        return public[0] if public else None

    # ── Allocation normalization ──────────────────────────────────────────────

    @staticmethod
    def normalize_allocation(raw: Dict[str, Any]) -> Dict[str, float]:
        """
        Convert a raw strategy allocation dict to ``{known_protocol: weight}``.

        Handles two output formats:
        * **Dollars**: values ≫ 1.0 (e.g. 40000.0) — divides by INITIAL_CAPITAL
        * **Weights**: values ≤ 1.0 each — used directly

        Protocol aliases are applied; protocols with alias=None are dropped.
        Unknown protocols (no alias) are also dropped.
        Merged weights are then renormalised to sum ≤ 1.0.
        """
        if not raw or not isinstance(raw, dict):
            return {}

        # Detect dollar vs weight format
        pos_vals = [v for v in raw.values() if isinstance(v, (int, float)) and v > 0]
        if not pos_vals:
            return {}
        total_raw = sum(pos_vals)
        is_dollars = total_raw > 1.5  # dollar totals are always >> 1.5

        merged: Dict[str, float] = {}
        for proto, val in raw.items():
            if not isinstance(val, (int, float)) or val <= 0:
                continue
            w = (val / INITIAL_CAPITAL) if is_dollars else float(val)

            # Resolve alias
            if proto in PROTOCOL_ALIAS:
                mapped = PROTOCOL_ALIAS[proto]
            elif proto in KNOWN_PROTOCOLS:
                mapped = proto
            else:
                # Unknown protocol — skip
                continue

            if mapped is None:
                continue  # explicitly dropped

            merged[mapped] = merged.get(mapped, 0.0) + w

        if not merged:
            return {}

        # Cap total at 1.0 (renormalise if overcrowded due to aliasing)
        total_w = sum(merged.values())
        if total_w > 1.0:
            merged = {k: v / total_w for k, v in merged.items()}

        return {k: round(v, 8) for k, v in merged.items() if v > 0}

    # ── Allocation extraction ─────────────────────────────────────────────────

    def extract_allocation(
        self,
        module_path: str,
        class_name: str,
        content: str,
    ) -> Tuple[Optional[Dict[str, float]], str]:
        """
        Try to extract and normalise an allocation from a strategy class.

        Returns
        -------
        (normalised_weights, method_label) on success.
        (None, skip_reason) on failure.

        Attempts in order:
          1. get_allocation()  — no args
          2. get_allocation(capital_usd=CAPITAL)
          3. get_allocation(capital_usd=CAPITAL, apy_map=MOCK_APY)
          4. get_allocation(portfolio_value=CAPITAL, apy_data=MOCK_APY)
          5. get_target_weights()
          6. Module-level ALLOCATION constant
        """
        # Import module
        try:
            mod = importlib.import_module(module_path)
        except Exception as exc:
            return None, f"import_error: {exc}"

        module_alloc = getattr(mod, "ALLOCATION", None)

        # Get class
        cls = getattr(mod, class_name, None)
        if cls is None:
            if isinstance(module_alloc, dict):
                norm = self.normalize_allocation(module_alloc)
                return (norm, "ALLOCATION_constant") if norm else (None, "empty_after_normalize")
            return None, f"class_not_found:{class_name}"

        # Instantiate
        try:
            instance = cls()
        except Exception as exc:
            if isinstance(module_alloc, dict):
                norm = self.normalize_allocation(module_alloc)
                return (norm, "ALLOCATION_constant_fallback") if norm else (None, "empty_after_normalize")
            return None, f"instantiation_error:{exc}"

        # Try get_target_weights (s12 pattern)
        if hasattr(instance, "get_target_weights") and not hasattr(instance, "get_allocation"):
            try:
                raw = instance.get_target_weights()
                norm = self.normalize_allocation(raw)
                return (norm, "get_target_weights") if norm else (None, "empty_after_normalize")
            except Exception:
                pass

        # Accept get_allocation() OR allocate() (s7x-style) as the allocation method —
        # recovers strategies that expose allocate() instead of get_allocation().
        _alloc_fn = getattr(instance, "get_allocation", None) or getattr(instance, "allocate", None)
        if _alloc_fn is None:
            if isinstance(module_alloc, dict):
                norm = self.normalize_allocation(module_alloc)
                return (norm, "ALLOCATION_constant") if norm else (None, "empty_after_normalize")
            return None, "no_get_allocation_method"

        # Try various call signatures
        attempts: List[Tuple[Dict, str]] = [
            ({}, "get_allocation()"),
            ({"capital_usd": INITIAL_CAPITAL}, "get_allocation(capital_usd)"),
            ({"capital_usd": INITIAL_CAPITAL, "apy_map": MOCK_APY},
             "get_allocation(capital_usd,apy_map)"),
            ({"apy_map": MOCK_APY}, "get_allocation(apy_map)"),
            ({"portfolio_value": INITIAL_CAPITAL, "apy_data": MOCK_APY},
             "get_allocation(portfolio_value,apy_data)"),
            ({"capital_usd": INITIAL_CAPITAL, "current_apys": MOCK_APY},
             "get_allocation(capital_usd,current_apys)"),
            # s11-style: mode string argument
            ({"mode": "bull"}, "get_allocation(mode=bull)"),
            # s44-style: regime string argument
            ({"regime": "normal"}, "get_allocation(regime=normal)"),
            ({"regime": "normal", "spiking_protocol": "aave_v3"},
             "get_allocation(regime,spiking_protocol)"),
            # allocate()-style signatures (s7x / research strategies)
            ({"apy_data": MOCK_APY}, "allocate(apy_data)"),
            ({"capital": INITIAL_CAPITAL, "live_apy": MOCK_APY}, "allocate(capital,live_apy)"),
            ({"capital": INITIAL_CAPITAL}, "allocate(capital)"),
        ]

        for kwargs, label in attempts:
            try:
                raw = _alloc_fn(**kwargs)
                if isinstance(raw, dict) and raw:
                    norm = self.normalize_allocation(raw)
                    if norm:
                        return norm, label
            except TypeError:
                continue  # wrong signature — try next
            except Exception as exc:
                _log.debug("get_allocation attempt '%s' raised %s", label, exc)
                continue

        # Last resort: module ALLOCATION constant
        if isinstance(module_alloc, dict):
            norm = self.normalize_allocation(module_alloc)
            return (norm, "ALLOCATION_constant_last_resort") if norm else (None, "empty_after_normalize")

        return None, "all_call_attempts_failed"

    # ── Single-strategy backtest ──────────────────────────────────────────────

    def _run_one(
        self,
        strategy_id: str,
        allocation: Dict[str, float],
    ) -> Dict[str, Any]:
        """Run ProfessionalBacktest for one allocation. Returns metrics dict."""
        try:
            metrics = self._backtest.run_strategy(allocation, strategy_name=strategy_id)
            return metrics
        except Exception as exc:
            _log.warning("Backtest failed for %s: %s", strategy_id, exc)
            raise

    # ── Main run ─────────────────────────────────────────────────────────────

    def run(self, data_dir: Optional[str] = None) -> Dict[str, Any]:
        """
        Discover all strategies, run each through the backtest, build leaderboard.

        Parameters
        ----------
        data_dir:
            Override output directory (for testing).

        Returns
        -------
        Full result dict.  Also atomically saves
        ``data/mass_tournament_results.json``.
        """
        out_dir = Path(data_dir) if data_dir else self._data_dir
        out_path = out_dir / "mass_tournament_results.json"

        strategy_files = self.discover_strategy_files()
        _log.info("MassTournament: discovered %d strategy files", len(strategy_files))

        leaderboard: List[Dict[str, Any]] = []
        skip_reasons: Dict[str, str] = {}
        strategies_skipped = 0
        strategies_tested = 0

        for fpath in strategy_files:
            sid = fpath.stem  # e.g. "s46_safe_harbor"
            try:
                with open(fpath, encoding="utf-8") as fh:
                    content = fh.read()
            except Exception as exc:
                skip_reasons[sid] = f"read_error:{exc}"
                strategies_skipped += 1
                continue

            # ── Skip checks ───────────────────────────────────────────────────
            if self.detect_leverage(content):
                skip_reasons[sid] = "leverage_detected"
                strategies_skipped += 1
                _log.debug("Skipping %s: leverage detected", sid)
                continue

            if self.detect_amm_lp(content):
                skip_reasons[sid] = "amm_lp_strategy"
                strategies_skipped += 1
                _log.debug("Skipping %s: AMM LP strategy", sid)
                continue

            primary_class = self.find_primary_class(content)
            if primary_class is None:
                skip_reasons[sid] = "no_class_found"
                strategies_skipped += 1
                continue

            module_path = f"{_MODULE_PREFIX}.{sid}"

            # ── Extract allocation ────────────────────────────────────────────
            allocation, method_used = self.extract_allocation(
                module_path, primary_class, content
            )

            if allocation is None:
                skip_reasons[sid] = method_used  # method_used carries reason
                strategies_skipped += 1
                _log.debug("Skipping %s: %s", sid, method_used)
                continue

            if not allocation:
                skip_reasons[sid] = "empty_allocation"
                strategies_skipped += 1
                continue

            # ── Run backtest ──────────────────────────────────────────────────
            try:
                metrics = self._run_one(sid, allocation)
            except Exception as exc:
                skip_reasons[sid] = f"backtest_error:{exc}"
                strategies_skipped += 1
                continue

            strategies_tested += 1
            leaderboard.append({
                "id":                sid,
                "class":             primary_class,
                "method_used":       method_used,
                "sharpe":            metrics["sharpe_ratio"],
                "sortino":           metrics["sortino_ratio"],
                "calmar":            metrics["calmar_ratio"],
                "annual_return_pct": metrics["annualized_return_pct"],
                "total_return_pct":  metrics["total_return_pct"],
                "max_dd_pct":        metrics["max_drawdown_pct"],
                "volatility_pct":    metrics["annualized_volatility_pct"],
                "win_rate_pct":      metrics["win_rate_pct"],
                "final_equity_usd":  metrics["final_equity_usd"],
                "allocation":        allocation,
            })
            _log.info(
                "Tested %s: Sharpe=%.3f  APY=%.2f%%  MaxDD=%.3f%%",
                sid,
                metrics["sharpe_ratio"],
                metrics["annualized_return_pct"],
                metrics["max_drawdown_pct"],
            )

        # ── Sort by Sharpe ────────────────────────────────────────────────────
        leaderboard.sort(key=lambda x: x["sharpe"], reverse=True)
        for i, entry in enumerate(leaderboard, 1):
            entry["rank"] = i

        top_5 = leaderboard[:5]
        bottom_5 = leaderboard[-5:] if len(leaderboard) >= 5 else leaderboard[:]

        result: Dict[str, Any] = {
            "generated_at":       datetime.now(timezone.utc).isoformat(),
            "version":            VERSION,
            "llm_forbidden":      True,
            "simulation_period":  "2022-01-01 to 2025-12-31",
            "initial_capital_usd": INITIAL_CAPITAL,
            "strategies_tested":  strategies_tested,
            "strategies_skipped": strategies_skipped,
            "total_files_scanned": len(strategy_files),
            "skip_reasons":       skip_reasons,
            "leaderboard":        leaderboard,
            "top_5":              top_5,
            "bottom_5":           bottom_5,
        }

        _atomic_write_json(out_path, result)
        _log.info(
            "MassTournament complete: %d tested, %d skipped → %s",
            strategies_tested, strategies_skipped, out_path,
        )
        return result


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    """Run mass tournament from command line."""
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="SPA Mass Strategy Tournament — runs all strategies through backtest"
    )
    parser.add_argument(
        "--data-dir", default=None,
        help="Override output data directory (default: project data/)"
    )
    parser.add_argument(
        "--no-noise", action="store_true",
        help="Disable APY noise (deterministic but unrealistically smooth Sharpe)"
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Debug logging"
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    mt = MassTournament(add_noise=not args.no_noise)
    result = mt.run(data_dir=args.data_dir)

    print(f"\n{'='*60}")
    print(f"Mass Tournament Results")
    print(f"{'='*60}")
    print(f"Strategies tested : {result['strategies_tested']}")
    print(f"Strategies skipped: {result['strategies_skipped']}")
    print(f"\nTop 5 by Sharpe ratio:")
    for e in result["top_5"]:
        print(
            f"  #{e['rank']:2d}  {e['id']:<38s}  "
            f"Sharpe={e['sharpe']:7.3f}  APY={e['annual_return_pct']:5.2f}%  "
            f"MaxDD={e['max_dd_pct']:.4f}%"
        )
    print(f"\nBottom 5 by Sharpe ratio:")
    for e in result["bottom_5"]:
        print(
            f"  #{e['rank']:2d}  {e['id']:<38s}  "
            f"Sharpe={e['sharpe']:7.3f}  APY={e['annual_return_pct']:5.2f}%  "
            f"MaxDD={e['max_dd_pct']:.4f}%"
        )
    print(f"\nSkipped strategies ({result['strategies_skipped']}):")
    for sid, reason in sorted(result["skip_reasons"].items()):
        print(f"  {sid:<38s}  {reason}")
    print(f"\nSaved → data/mass_tournament_results.json")


if __name__ == "__main__":
    main()
