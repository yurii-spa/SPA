#!/usr/bin/env python3
"""
analytics_pipeline.py — Unified analytics runner for SPA (MP-663).

Reads real position/APY data from data/*.json and runs all analytics modules
(MP-637 through MP-662).  Writes results to data/analytics_report.json.

Usage:
    python3 -m spa_core.analytics.analytics_pipeline          # run all
    python3 -m spa_core.analytics.analytics_pipeline --module risk
    python3 -m spa_core.analytics.analytics_pipeline --data-dir /custom/path

Called automatically by cycle_runner.py after each simulation day.
Pure stdlib.  Read-only / advisory only — no capital touched.
Atomic writes (tmp + os.replace).  Ring-buffer: MAX_REPORT_HISTORY entries.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Project root resolution
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = PROJECT_ROOT / "data"

REPORT_FILE = _DEFAULT_DATA_DIR / "analytics_report.json"
MAX_REPORT_HISTORY = 30

log = logging.getLogger("spa.analytics_pipeline")

# ---------------------------------------------------------------------------
# Tier / protocol catalogue (static reference data)
# ---------------------------------------------------------------------------

# Adapter → (tier, lock_days)
_ADAPTER_TIER: Dict[str, tuple] = {
    "aave_v3":           ("T1", 0),
    "aave_v3_arbitrum":  ("T1", 0),
    "compound_v3":       ("T1", 0),
    "morpho_steakhouse": ("T1", 0),
    "morpho_blue":       ("T2", 0),
    "yearn_v3":          ("T2", 0),
    "euler_v2":          ("T2", 0),
    "maple":             ("T2", 0),
    "pendle_pt":         ("T3", 7),
    "pendle_yt":         ("T3", 7),
    "delta_neutral":     ("T2", 0),
    "emode_looping":     ("T2", 0),
}

# Static protocol risk inputs (conservative defaults)
_PROTOCOL_INPUTS: Dict[str, dict] = {
    "aave_v3": {
        "tvl_usd": 15_000_000_000,
        "audit_count": 5,
        "age_days": 900,
        "incident_count": 0,
        "is_upgradeable": True,
    },
    "aave_v3_arbitrum": {
        "tvl_usd": 3_000_000_000,
        "audit_count": 5,
        "age_days": 700,
        "incident_count": 0,
        "is_upgradeable": True,
    },
    "compound_v3": {
        "tvl_usd": 3_000_000_000,
        "audit_count": 4,
        "age_days": 800,
        "incident_count": 0,
        "is_upgradeable": True,
    },
    "morpho_steakhouse": {
        "tvl_usd": 1_000_000_000,
        "audit_count": 3,
        "age_days": 400,
        "incident_count": 0,
        "is_upgradeable": True,
    },
    "morpho_blue": {
        "tvl_usd": 500_000_000,
        "audit_count": 3,
        "age_days": 400,
        "incident_count": 0,
        "is_upgradeable": False,
    },
    "yearn_v3": {
        "tvl_usd": 500_000_000,
        "audit_count": 3,
        "age_days": 1200,
        "incident_count": 1,
        "is_upgradeable": True,
    },
    "euler_v2": {
        "tvl_usd": 400_000_000,
        "audit_count": 3,
        "age_days": 350,
        "incident_count": 1,
        "is_upgradeable": True,
    },
    "maple": {
        "tvl_usd": 200_000_000,
        "audit_count": 2,
        "age_days": 900,
        "incident_count": 0,
        "is_upgradeable": True,
    },
    "pendle_pt": {
        "tvl_usd": 300_000_000,
        "audit_count": 2,
        "age_days": 500,
        "incident_count": 0,
        "is_upgradeable": True,
    },
}


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def _safe_read_json(path: Path, default: Any) -> Any:
    """Read JSON from *path*; return *default* on any error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        log.warning("Cannot read %s: %s", path, exc)
        return default


def _load_positions(data_dir: Path) -> Dict[str, float]:
    """Return {adapter_id: capital_usd} from current_positions.json.

    Handles two shapes:
    * {"positions": {"aave_v3": 23750, ...}, ...}  (cycle_runner output)
    * [{"adapter_id": "aave_v3", "capital_usd": 23750, ...}, ...]   (list)
    * {"aave_v3": 23750, ...}  (flat dict)
    """
    raw = _safe_read_json(data_dir / "current_positions.json", None)
    if raw is None:
        return {}
    if isinstance(raw, dict):
        if "positions" in raw and isinstance(raw["positions"], dict):
            return {k: float(v) for k, v in raw["positions"].items() if v}
        # flat dict: filter out metadata keys (non-numeric values)
        out: Dict[str, float] = {}
        for k, v in raw.items():
            if isinstance(v, (int, float)):
                out[k] = float(v)
        return out
    if isinstance(raw, list):
        out = {}
        for item in raw:
            if isinstance(item, dict) and "adapter_id" in item:
                out[item["adapter_id"]] = float(item.get("capital_usd", 0))
        return out
    return {}


def _load_apy_history(data_dir: Path) -> List[float]:
    """Return a list of daily APY values (fractional) from equity_curve_daily.json.

    equity_curve_daily.json schema:
        {"daily": [{"date": "...", "apy_today": 3.95, "equity_usd": 100036}, ...]}
    apy_today is in percent → divide by 100.
    """
    raw = _safe_read_json(data_dir / "equity_curve_daily.json", None)
    if raw is None:
        return []
    daily = []
    if isinstance(raw, dict):
        daily = raw.get("daily", [])
    elif isinstance(raw, list):
        daily = raw
    out: List[float] = []
    for entry in daily:
        if isinstance(entry, dict):
            val = entry.get("apy_today", entry.get("apy", None))
            if val is not None:
                # apy_today is stored in percent (e.g. 3.95 = 3.95%)
                out.append(float(val) / 100.0)
    return out


def _load_status(data_dir: Path) -> Dict[str, Any]:
    """Return paper_trading_status.json as a dict."""
    return _safe_read_json(data_dir / "paper_trading_status.json", {})


def _load_adapter_status(data_dir: Path) -> Dict[str, Any]:
    """Return adapter_status.json as a dict."""
    return _safe_read_json(data_dir / "adapter_status.json", {})


# ---------------------------------------------------------------------------
# Input builders (raw data → module-specific dataclasses)
# ---------------------------------------------------------------------------

def _build_adapter_liquidities(positions: Dict[str, float]):
    """Build List[AdapterLiquidity] from position map, if module is importable."""
    try:
        from spa_core.analytics.liquidity_stress_simulator import AdapterLiquidity
    except Exception:
        return []
    items = []
    for adapter_id, capital in positions.items():
        tier, lock_days = _ADAPTER_TIER.get(adapter_id, ("T2", 0))
        items.append(AdapterLiquidity(
            adapter_id=adapter_id,
            capital_deployed=capital,
            tier=tier,
            lock_days=lock_days,
            tvl_usd=0.0,                # unknown at this layer
            withdrawal_limit_pct=0.10,
        ))
    return items


def _build_protocol_inputs(positions: Dict[str, float]):
    """Build List[ProtocolInput] for protocols that have positions."""
    try:
        from spa_core.analytics.protocol_risk_scorer import ProtocolInput
    except Exception:
        return []
    items = []
    seen = set()
    for adapter_id in positions:
        if adapter_id in seen:
            continue
        seen.add(adapter_id)
        info = _PROTOCOL_INPUTS.get(adapter_id, {
            "tvl_usd": 100_000_000,
            "audit_count": 1,
            "age_days": 180,
            "incident_count": 0,
            "is_upgradeable": True,
        })
        items.append(ProtocolInput(
            protocol_id=adapter_id,
            tvl_usd=info["tvl_usd"],
            audit_count=info["audit_count"],
            age_days=info["age_days"],
            incident_count=info["incident_count"],
            is_upgradeable=info["is_upgradeable"],
        ))
    return items


def _build_allocation_slots(positions: Dict[str, float], total_capital: float):
    """Build List[AllocationSlot] for RebalanceTriggerEngine."""
    try:
        from spa_core.analytics.rebalance_trigger_engine import AllocationSlot
    except Exception:
        return []
    if not positions or total_capital <= 0:
        return []

    # Compute equal-weight target
    n = len(positions)
    equal_target = 1.0 / n if n > 0 else 0.0
    slots = []
    for adapter_id, capital in positions.items():
        current_pct = capital / total_capital
        slots.append(AllocationSlot(
            adapter_id=adapter_id,
            target_pct=equal_target,
            current_pct=round(current_pct, 6),
            current_apy=0.04,   # unknown at this layer; use neutral default
            prev_apy=0.04,
            days_since_last=8,  # assume last rebalance was 8 days ago → past cooldown
        ))
    return slots


# ---------------------------------------------------------------------------
# Dataclass helpers for serialisation
# ---------------------------------------------------------------------------

def _to_dict(obj: Any) -> Any:
    """Recursively convert dataclasses / lists to plain dicts for JSON."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_to_dict(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    # dataclass or object with __dict__
    try:
        import dataclasses
        if dataclasses.is_dataclass(obj):
            return {f.name: _to_dict(getattr(obj, f.name))
                    for f in dataclasses.fields(obj)}
    except Exception:
        pass
    try:
        return vars(obj)
    except Exception:
        return str(obj)


# ---------------------------------------------------------------------------
# AnalyticsPipeline
# ---------------------------------------------------------------------------

class AnalyticsPipeline:
    """Run all SPA analytics modules and produce a unified report."""

    def __init__(self, data_dir: Optional[Path] = None,
                 report_file: Optional[Path] = None):
        self.data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
        self.report_file = Path(report_file) if report_file else (
            self.data_dir / "analytics_report.json"
        )
        self._modules_run = 0
        self._modules_failed = 0

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> Dict[str, Any]:
        """Run all analytics modules; write and return the report dict."""
        t0 = time.time()
        self._modules_run = 0
        self._modules_failed = 0

        # Load real data
        positions = self._load_positions()
        apy_history = self._load_apy_history()
        status = self._load_status()
        adapter_status = self._load_adapter_status()

        total_capital = status.get("current_equity",
                        sum(positions.values()) if positions else 0.0)
        portfolio_apy = status.get("apy_today_pct", 0.0) / 100.0

        # ----------------------------------------------------------------
        # Run each analytics module — each call is doubly isolated:
        #   1. _run_module() catches exceptions inside the inner function.
        #   2. _safe_run() catches any exception from the runner method
        #      itself (e.g. if a test replaces the method with a raiser).
        # ----------------------------------------------------------------
        results: Dict[str, Any] = {}

        # --- Risk modules -----------------------------------------------
        results["volatility_regime"] = self._safe_run(
            "volatility_regime", self._run_volatility_regime, apy_history)
        results["liquidity_stress"] = self._safe_run(
            "liquidity_stress", self._run_liquidity_stress, positions)
        results["collateral_health"] = self._safe_run(
            "collateral_health", self._run_collateral_health)
        results["protocol_risk_scores"] = self._safe_run(
            "protocol_risk_scores", self._run_protocol_risk, positions)

        # --- Yield modules ----------------------------------------------
        results["apy_momentum"] = self._safe_run(
            "apy_momentum", self._run_apy_momentum, apy_history)
        results["yield_benchmarks"] = self._safe_run(
            "yield_benchmarks", self._run_yield_benchmarks, portfolio_apy)
        results["drawdown_episodes"] = self._safe_run(
            "drawdown_episodes", self._run_drawdown_recovery, apy_history)
        results["apy_forecast"] = self._safe_run(
            "apy_forecast", self._run_apy_forecast, apy_history)

        # --- Trade optimisation -----------------------------------------
        results["rebalance_trigger"] = self._safe_run(
            "rebalance_trigger", self._run_rebalance_trigger,
            positions, total_capital)
        results["slippage_estimates"] = self._safe_run(
            "slippage_estimates", self._run_slippage, positions, total_capital)
        results["gas_cost_estimate"] = self._safe_run(
            "gas_cost_estimate", self._run_gas_cost, total_capital, portfolio_apy)
        results["chain_fee_comparison"] = self._safe_run(
            "chain_fee_comparison", self._run_chain_fees)

        # ----------------------------------------------------------------
        # Assemble & persist report
        # ----------------------------------------------------------------
        elapsed = round(time.time() - t0, 6)
        report = self._build_report(
            positions=positions,
            total_capital=total_capital,
            portfolio_apy=portfolio_apy,
            results=results,
            elapsed_sec=elapsed,
        )
        self._append_to_history(report)
        return report

    # ------------------------------------------------------------------
    # Public data-loading methods (also used by tests)
    # ------------------------------------------------------------------

    def _load_positions(self) -> Dict[str, float]:
        return _load_positions(self.data_dir)

    def _load_apy_history(self) -> List[float]:
        return _load_apy_history(self.data_dir)

    def _load_status(self) -> Dict[str, Any]:
        return _load_status(self.data_dir)

    def _load_adapter_status(self) -> Dict[str, Any]:
        return _load_adapter_status(self.data_dir)

    # ------------------------------------------------------------------
    # Report builder
    # ------------------------------------------------------------------

    def _build_report(
        self,
        positions: Dict[str, float],
        total_capital: float,
        portfolio_apy: float,
        results: Dict[str, Any],
        elapsed_sec: float,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        return {
            "timestamp": time.time(),
            "run_at": now,
            "elapsed_sec": elapsed_sec,
            "portfolio_summary": {
                "total_capital_usd": round(total_capital, 2),
                "current_apy": round(portfolio_apy, 6),
                "current_apy_pct": round(portfolio_apy * 100, 4),
                "positions_count": len(positions),
                "positions": {k: round(v, 2) for k, v in positions.items()},
            },
            "modules_run": self._modules_run,
            "modules_failed": self._modules_failed,
            "results": results,
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _append_to_history(self, report: Dict[str, Any]) -> None:
        """Atomically append *report* to ring-buffer JSON file."""
        self.report_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing: List[dict] = json.loads(
                self.report_file.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []

        existing.append(report)
        # Ring-buffer: keep only the latest MAX_REPORT_HISTORY entries
        if len(existing) > MAX_REPORT_HISTORY:
            existing = existing[-MAX_REPORT_HISTORY:]

        tmp = self.report_file.with_suffix(".tmp")
        try:
            tmp.write_text(
                json.dumps(existing, indent=2, default=str),
                encoding="utf-8",
            )
            os.replace(tmp, self.report_file)
        except Exception as exc:
            log.error("Failed to write analytics report: %s", exc)
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Module runners — each wrapped in try/except for isolation
    # ------------------------------------------------------------------

    def _run_module(self, name: str, fn, *args, **kwargs) -> Any:
        """Call *fn(*args, **kwargs)*, track success/failure, return result."""
        try:
            result = fn(*args, **kwargs)
            self._modules_run += 1
            return result
        except Exception as exc:
            self._modules_failed += 1
            log.warning("Module %s failed: %s\n%s",
                        name, exc, traceback.format_exc())
            return {"error": str(exc), "module": name}

    def _safe_run(self, name: str, runner, *args, **kwargs) -> Any:
        """Outer guard: call *runner*, catching any exception it leaks.

        This is distinct from _run_module — it catches failures in the
        runner method itself (e.g. import errors or test-time replacements)
        so that run() can never be crashed by a single bad module.
        Failures here also increment _modules_failed.
        """
        try:
            return runner(*args, **kwargs)
        except Exception as exc:
            self._modules_failed += 1
            log.warning("Module runner %s crashed: %s", name, exc)
            return {"error": str(exc), "module": name}

    # ---- Risk ----------------------------------------------------------

    def _run_volatility_regime(self, apy_history: List[float]) -> Any:
        def _inner():
            from spa_core.analytics.volatility_regime_detector import (
                VolatilityRegimeDetector,
            )
            detector = VolatilityRegimeDetector()
            snap = detector.detect(
                strategy_id="portfolio",
                apy_series=apy_history if apy_history else [0.04],
            )
            return _to_dict(snap)
        return self._run_module("volatility_regime", _inner)

    def _run_liquidity_stress(self, positions: Dict[str, float]) -> Any:
        def _inner():
            from spa_core.analytics.liquidity_stress_simulator import (
                LiquidityStressSimulator,
            )
            adapters = _build_adapter_liquidities(positions)
            if not adapters:
                # Synthesize a single placeholder so the module can run
                from spa_core.analytics.liquidity_stress_simulator import (
                    AdapterLiquidity,
                )
                adapters = [AdapterLiquidity(
                    adapter_id="placeholder",
                    capital_deployed=0.0,
                    tier="T1",
                    lock_days=0,
                    tvl_usd=0.0,
                    withdrawal_limit_pct=0.10,
                )]
            sim = LiquidityStressSimulator()
            result = sim.simulate(adapters, scenario="MODERATE")
            return _to_dict(result)
        return self._run_module("liquidity_stress", _inner)

    def _run_collateral_health(self) -> Any:
        """Return empty result — no leveraged positions in paper trading."""
        def _inner():
            from spa_core.analytics.collateral_health_monitor import analyze
            result = analyze([])
            return {
                "positions_assessed": len(result.get("positions", [])),
                "results": _to_dict(result),
            }
        return self._run_module("collateral_health", _inner)

    def _run_protocol_risk(self, positions: Dict[str, float]) -> Any:
        def _inner():
            from spa_core.analytics.protocol_risk_scorer import ProtocolRiskScorer
            protocols = _build_protocol_inputs(positions)
            scorer = ProtocolRiskScorer()
            scores = scorer.score_batch(protocols)
            return _to_dict(scores)
        return self._run_module("protocol_risk_scores", _inner)

    # ---- Yield ---------------------------------------------------------

    def _run_apy_momentum(self, apy_history: List[float]) -> Any:
        def _inner():
            from spa_core.analytics.apy_momentum_tracker import analyze
            history = apy_history if apy_history else [0.04]
            protocols = [{"name": "portfolio", "apy_history": history}]
            result = analyze(protocols)
            return _to_dict(result)
        return self._run_module("apy_momentum", _inner)

    def _run_yield_benchmarks(self, portfolio_apy: float) -> Any:
        def _inner():
            from spa_core.analytics.yield_benchmark_comparator import analyze
            apy = portfolio_apy if portfolio_apy > 0 else 0.04
            strategies = [{"name": "portfolio", "apy": apy, "risk_score": 20,
                           "liquidity": "HIGH"}]
            benchmarks = {"risk_free_rate": 0.045, "eth_staking_apy": 0.038,
                          "btc_holding_apy": 0.0}
            result = analyze(strategies, benchmarks)
            return _to_dict(result)
        return self._run_module("yield_benchmarks", _inner)

    def _run_drawdown_recovery(self, apy_history: List[float]) -> Any:
        def _inner():
            from spa_core.analytics.drawdown_recovery_tracker import (
                DrawdownRecoveryTracker,
            )
            tracker = DrawdownRecoveryTracker()
            episodes = tracker.detect_episodes(
                strategy_id="portfolio",
                apy_series=apy_history if apy_history else [0.04, 0.04],
            )
            return _to_dict(episodes)
        return self._run_module("drawdown_episodes", _inner)

    def _run_apy_forecast(self, apy_history: List[float]) -> Any:
        def _inner():
            from spa_core.analytics.apy_forecast_v2 import APYForecastV2
            forecaster = APYForecastV2()
            points = forecaster.forecast_adapter(
                adapter_id="portfolio",
                history=apy_history if apy_history else [0.04],
            )
            return _to_dict(points)
        return self._run_module("apy_forecast", _inner)

    # ---- Trade optimisation --------------------------------------------

    def _run_rebalance_trigger(
        self,
        positions: Dict[str, float],
        total_capital: float,
    ) -> Any:
        def _inner():
            from spa_core.analytics.rebalance_trigger_engine import (
                RebalanceTriggerEngine,
            )
            slots = _build_allocation_slots(positions, total_capital)
            engine = RebalanceTriggerEngine()
            trigger = engine.evaluate(slots)
            return _to_dict(trigger)
        return self._run_module("rebalance_trigger", _inner)

    def _run_slippage(
        self,
        positions: Dict[str, float],
        total_capital: float,
    ) -> Any:
        def _inner():
            from spa_core.analytics.slippage_model_advisor import SlippageModelAdvisor
            advisor = SlippageModelAdvisor()
            # Estimate slippage for a hypothetical 10 % rebalance
            rebalance_size = total_capital * 0.10 if total_capital > 0 else 10_000.0
            estimates = []
            for adapter_id, capital in positions.items():
                info = _PROTOCOL_INPUTS.get(adapter_id, {})
                tvl_usd = float(info.get("tvl_usd", 0))
                trade_size = min(rebalance_size, capital)
                est = advisor.estimate(
                    adapter_id=adapter_id,
                    protocol=adapter_id,
                    trade_size_usd=trade_size,
                    tvl_usd=tvl_usd if tvl_usd > 0 else 1_000_000,
                )
                estimates.append(_to_dict(est))
            return estimates
        return self._run_module("slippage_estimates", _inner)

    def _run_gas_cost(self, total_capital: float, portfolio_apy: float) -> Any:
        def _inner():
            from spa_core.analytics.gas_cost_optimizer import GasCostOptimizer
            optimizer = GasCostOptimizer()
            estimate = optimizer.estimate(
                operation="AAVE_DEPOSIT",
                gas_price_gwei=30.0,
                eth_price_usd=3_000.0,
                capital_usd=total_capital if total_capital > 0 else 100_000.0,
                expected_apy=portfolio_apy if portfolio_apy > 0 else 0.04,
            )
            return _to_dict(estimate)
        return self._run_module("gas_cost_estimate", _inner)

    def _run_chain_fees(self) -> Any:
        def _inner():
            from spa_core.analytics.chain_fee_tracker import ChainFeeTracker
            tracker = ChainFeeTracker()
            # Snapshot ETH, Arbitrum, Base
            eth_snap = tracker.snapshot_chain(
                chain="ethereum",
                gas_price_gwei=30.0,
                l1_overhead_gwei=0.0,
                eth_price_usd=3_000.0,
            )
            arb_snap = tracker.snapshot_chain(
                chain="arbitrum",
                gas_price_gwei=0.1,
                l1_overhead_gwei=0.05,
                eth_price_usd=3_000.0,
            )
            base_snap = tracker.snapshot_chain(
                chain="base",
                gas_price_gwei=0.05,
                l1_overhead_gwei=0.04,
                eth_price_usd=3_000.0,
            )
            comparison = tracker.compare_chains([eth_snap, arb_snap, base_snap])
            return _to_dict(comparison)
        return self._run_module("chain_fee_comparison", _inner)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args(argv):
    import argparse
    parser = argparse.ArgumentParser(
        prog="analytics_pipeline",
        description="Unified SPA analytics runner (MP-663).",
    )
    parser.add_argument(
        "--module",
        default=None,
        choices=["risk", "yield", "trade", "all"],
        help="Run only a subset of modules (default: all)",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Override data directory path",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Enable verbose logging",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    data_dir = Path(args.data_dir) if args.data_dir else None
    pipeline = AnalyticsPipeline(data_dir=data_dir)

    log.info("Running analytics pipeline…")
    report = pipeline.run()

    total = report["modules_run"] + report["modules_failed"]
    log.info(
        "Done: %d/%d modules OK (%d failed) in %.2fs",
        report["modules_run"],
        total,
        report["modules_failed"],
        report["elapsed_sec"],
    )

    summary = report["portfolio_summary"]
    print(f"  capital     : ${summary['total_capital_usd']:,.2f}")
    print(f"  APY         : {summary['current_apy_pct']:.4f}%")
    print(f"  positions   : {summary['positions_count']}")
    print(f"  modules OK  : {report['modules_run']}/{total}")
    print(f"  modules FAIL: {report['modules_failed']}")
    print(f"  report      : {pipeline.report_file}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
