#!/usr/bin/env python3
"""DeFi Yield-Bearing Collateral Analyzer (MP-966) — read-only / advisory.

Analyzes the use of yield-bearing tokens (stETH, aUSDC, cDAI, etc.) as
collateral in lending protocols. Computes net carry, safety margin,
liquidation buffer, yield capture efficiency, and oracle lag risk for
each position, then flags structural risks and aggregates portfolio-level
insights.

Strictly read-only and advisory. Pure stdlib only (json, os, math,
datetime, argparse, tempfile, logging, pathlib). No network, no LLM,
no external packages. Atomic writes via tmp + os.replace.

CLI::

    python3 -m spa_core.analytics.defi_yield_bearing_collateral_analyzer --check
    python3 -m spa_core.analytics.defi_yield_bearing_collateral_analyzer --run
    python3 -m spa_core.analytics.defi_yield_bearing_collateral_analyzer --run --data-dir <dir>
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ── constants ────────────────────────────────────────────────────────────────
VERSION = "1.0.0"
MODULE_ID = "MP-966"
LOG_FILE = "yield_bearing_collateral_log.json"
LOG_CAP = 100

# Carry labels
LABEL_OPTIMAL = "OPTIMAL_CARRY"
LABEL_POSITIVE = "POSITIVE_CARRY"
LABEL_BREAK_EVEN = "BREAK_EVEN"
LABEL_NEGATIVE = "NEGATIVE_CARRY"
LABEL_LIQUIDATION = "LIQUIDATION_IMMINENT"

# Oracle types for lag scoring
ORACLE_CHAINLINK = "chainlink"
ORACLE_PROTOCOL_NATIVE = "protocol_native"
ORACLE_TWAP = "twap"

# Rebasing types
REBASING = "rebasing"
NON_REBASING = "non_rebasing"
WRAPPED = "wrapped"


# ── core analyzer ────────────────────────────────────────────────────────────

class DeFiYieldBearingCollateralAnalyzer:
    """Analyze yield-bearing tokens used as collateral.

    Parameters
    ----------
    config : dict, optional
        Optional overrides for thresholds. Supported keys:
        - tight_liquidation_threshold (default 5.0) — safety margin below
          which TIGHT_LIQUIDATION flag is raised (pct).
        - high_oracle_lag_threshold (default 70.0) — oracle_lag_risk_score
          above which HIGH_ORACLE_LAG flag is raised.
        - optimal_carry_min_pct (default 2.0) — net carry >= this → OPTIMAL.
        - liquidation_imminent_safety_margin (default 2.0) — safety margin
          <= this → LIQUIDATION_IMMINENT label.
        - yield_dominant_ratio (default 2.0) — apy / borrow_rate >= this →
          YIELD_DOMINANT flag.
    """

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.tight_liq_threshold: float = float(cfg.get("tight_liquidation_threshold", 5.0))
        self.high_oracle_lag: float = float(cfg.get("high_oracle_lag_threshold", 70.0))
        self.optimal_carry_min: float = float(cfg.get("optimal_carry_min_pct", 2.0))
        self.liq_imminent_margin: float = float(cfg.get("liquidation_imminent_safety_margin", 2.0))
        self.yield_dominant_ratio: float = float(cfg.get("yield_dominant_ratio", 2.0))

    # ── public API ──────────────────────────────────────────────────────────

    def analyze(self, positions: list[dict], config: dict | None = None) -> dict:
        """Analyze yield-bearing collateral positions.

        Parameters
        ----------
        positions : list[dict]
            Each position dict must include:
            - asset_name (str)
            - protocol_used_as_collateral (str)
            - underlying_apy_pct (float)
            - collateral_factor_pct (float)  — LTV at origination
            - liquidation_threshold_pct (float)
            - current_ltv_pct (float)
            - position_value_usd (float)
            - borrow_rate_pct (float)
            - rebasing_type (str): "rebasing" | "non_rebasing" | "wrapped"
            - oracle_type (str): "chainlink" | "protocol_native" | "twap"
            - price_deviation_risk_pct (float)  — max historical depeg
        config : dict, optional
            Runtime config overrides (merged with constructor config).

        Returns
        -------
        dict with keys: positions (list), aggregates (dict), meta (dict)
        """
        # merge runtime config
        if config:
            for k, v in config.items():
                if k == "tight_liquidation_threshold":
                    self.tight_liq_threshold = float(v)
                elif k == "high_oracle_lag_threshold":
                    self.high_oracle_lag = float(v)
                elif k == "optimal_carry_min_pct":
                    self.optimal_carry_min = float(v)
                elif k == "liquidation_imminent_safety_margin":
                    self.liq_imminent_margin = float(v)
                elif k == "yield_dominant_ratio":
                    self.yield_dominant_ratio = float(v)

        analyzed: list[dict] = []
        for pos in positions:
            analyzed.append(self._analyze_position(pos))

        aggregates = self._compute_aggregates(analyzed)
        return {
            "positions": analyzed,
            "aggregates": aggregates,
            "meta": {
                "module": MODULE_ID,
                "version": VERSION,
                "generated_at": _utcnow(),
                "position_count": len(analyzed),
            },
        }

    # ── per-position analysis ───────────────────────────────────────────────

    def _analyze_position(self, pos: dict) -> dict:
        asset = str(pos.get("asset_name", "unknown"))
        protocol = str(pos.get("protocol_used_as_collateral", "unknown"))
        apy = float(pos.get("underlying_apy_pct", 0.0))
        liq_threshold = float(pos.get("liquidation_threshold_pct", 80.0))
        current_ltv = float(pos.get("current_ltv_pct", 0.0))
        position_value = float(pos.get("position_value_usd", 0.0))
        borrow_rate = float(pos.get("borrow_rate_pct", 0.0))
        rebasing = str(pos.get("rebasing_type", NON_REBASING))
        oracle = str(pos.get("oracle_type", ORACLE_CHAINLINK))
        price_deviation = float(pos.get("price_deviation_risk_pct", 0.0))

        # ── computed metrics ────────────────────────────────────────────────
        net_carry = round(apy - borrow_rate, 6)
        safety_margin = round(liq_threshold - current_ltv, 6)

        # Liquidation buffer: how many days until liquidation at rate of
        # 0.1 pct/day LTV drift (conservative default)
        daily_ltv_drift = float(pos.get("daily_ltv_drift_pct", 0.1))
        if daily_ltv_drift > 0 and safety_margin > 0:
            liq_buffer_days = round(safety_margin / daily_ltv_drift, 2)
        elif safety_margin <= 0:
            liq_buffer_days = 0.0
        else:
            liq_buffer_days = 9999.0

        # Yield capture efficiency: what fraction of the underlying yield
        # survives after paying for the borrow
        if apy > 0:
            yield_capture_eff = round((net_carry / apy) * 100.0, 4)
        elif apy == 0 and borrow_rate == 0:
            yield_capture_eff = 100.0
        else:
            yield_capture_eff = 0.0

        oracle_lag_risk = self._oracle_lag_risk_score(oracle, rebasing, price_deviation)

        # ── label ───────────────────────────────────────────────────────────
        if safety_margin <= self.liq_imminent_margin:
            label = LABEL_LIQUIDATION
        elif net_carry >= self.optimal_carry_min:
            label = LABEL_OPTIMAL
        elif net_carry > 0:
            label = LABEL_POSITIVE
        elif net_carry == 0:
            label = LABEL_BREAK_EVEN
        else:
            label = LABEL_NEGATIVE

        # ── flags ───────────────────────────────────────────────────────────
        flags: list[str] = []
        if rebasing == REBASING and oracle == ORACLE_PROTOCOL_NATIVE:
            flags.append("REBASING_ORACLE_RISK")
        if 0 < safety_margin < self.tight_liq_threshold:
            flags.append("TIGHT_LIQUIDATION")
        if net_carry > 0:
            flags.append("POSITIVE_CARRY")
        if oracle_lag_risk > self.high_oracle_lag:
            flags.append("HIGH_ORACLE_LAG")
        if borrow_rate > 0 and apy >= self.yield_dominant_ratio * borrow_rate:
            flags.append("YIELD_DOMINANT")
        elif borrow_rate == 0 and apy > 0:
            flags.append("YIELD_DOMINANT")

        return {
            "asset_name": asset,
            "protocol_used_as_collateral": protocol,
            "underlying_apy_pct": apy,
            "borrow_rate_pct": borrow_rate,
            "current_ltv_pct": current_ltv,
            "liquidation_threshold_pct": liq_threshold,
            "position_value_usd": position_value,
            "rebasing_type": rebasing,
            "oracle_type": oracle,
            "price_deviation_risk_pct": price_deviation,
            "net_carry_pct": net_carry,
            "safety_margin_pct": safety_margin,
            "liquidation_buffer_days_estimate": liq_buffer_days,
            "yield_capture_efficiency_pct": yield_capture_eff,
            "oracle_lag_risk_score": oracle_lag_risk,
            "label": label,
            "flags": flags,
        }

    def _oracle_lag_risk_score(
        self,
        oracle: str,
        rebasing: str,
        price_deviation: float,
    ) -> float:
        """Compute oracle lag risk score 0-100.

        Higher = more dangerous lag exposure.
        """
        base: float
        if oracle == ORACLE_CHAINLINK:
            base = 10.0
        elif oracle == ORACLE_TWAP:
            base = 30.0
        elif oracle == ORACLE_PROTOCOL_NATIVE:
            base = 50.0
        else:
            base = 40.0

        # Rebasing tokens amplify oracle lag risk
        if rebasing == REBASING:
            base += 25.0
        elif rebasing == NON_REBASING:
            base += 0.0
        elif rebasing == WRAPPED:
            base += 10.0

        # Historical depeg adds risk
        deviation_penalty = min(price_deviation * 2.0, 30.0)
        score = base + deviation_penalty
        return round(min(score, 100.0), 4)

    # ── aggregates ──────────────────────────────────────────────────────────

    def _compute_aggregates(self, analyzed: list[dict]) -> dict:
        if not analyzed:
            return {
                "best_carry_pct": None,
                "worst_carry_pct": None,
                "total_position_value_usd": 0.0,
                "average_net_carry_pct": None,
                "liquidation_imminent_count": 0,
                "positive_carry_count": 0,
                "negative_carry_count": 0,
                "rebasing_oracle_risk_count": 0,
                "total_positions": 0,
            }

        carries = [p["net_carry_pct"] for p in analyzed]
        values = [p["position_value_usd"] for p in analyzed]
        total_value = sum(values)

        liq_imminent = sum(1 for p in analyzed if p["label"] == LABEL_LIQUIDATION)
        pos_carry = sum(1 for p in analyzed if p["net_carry_pct"] > 0)
        neg_carry = sum(1 for p in analyzed if p["net_carry_pct"] < 0)
        rebasing_oracle_risk = sum(
            1 for p in analyzed if "REBASING_ORACLE_RISK" in p["flags"]
        )

        return {
            "best_carry_pct": round(max(carries), 6),
            "worst_carry_pct": round(min(carries), 6),
            "total_position_value_usd": round(total_value, 4),
            "average_net_carry_pct": round(sum(carries) / len(carries), 6),
            "liquidation_imminent_count": liq_imminent,
            "positive_carry_count": pos_carry,
            "negative_carry_count": neg_carry,
            "rebasing_oracle_risk_count": rebasing_oracle_risk,
            "total_positions": len(analyzed),
        }


# ── ring-buffer log writer ───────────────────────────────────────────────────

def write_log(result: dict, data_dir: Path) -> None:
    """Atomically append result to ring-buffer log (cap LOG_CAP)."""
    log_path = data_dir / LOG_FILE
    if log_path.exists():
        try:
            existing = json.loads(log_path.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []
    else:
        existing = []

    existing.append(result)
    if len(existing) > LOG_CAP:
        existing = existing[-LOG_CAP:]

    _atomic_write(log_path, json.dumps(existing, indent=2, ensure_ascii=False))
    logger.info("Log written: %s (%d entries)", log_path, len(existing))


def _atomic_write(path: Path, content: str) -> None:
    dir_ = path.parent
    dir_.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dir_, prefix=".tmp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── CLI ─────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="DeFi Yield-Bearing Collateral Analyzer (MP-966)"
    )
    p.add_argument("--check", action="store_true", help="Compute and print (default)")
    p.add_argument("--run", action="store_true", help="Compute, print and write log")
    p.add_argument("--data-dir", default="data", help="Directory for log file")
    return p


def _sample_positions() -> list[dict]:
    return [
        {
            "asset_name": "stETH",
            "protocol_used_as_collateral": "Aave V3",
            "underlying_apy_pct": 4.5,
            "collateral_factor_pct": 75.0,
            "liquidation_threshold_pct": 80.0,
            "current_ltv_pct": 60.0,
            "position_value_usd": 500000.0,
            "borrow_rate_pct": 3.2,
            "rebasing_type": "rebasing",
            "oracle_type": "chainlink",
            "price_deviation_risk_pct": 1.5,
        },
        {
            "asset_name": "aUSDC",
            "protocol_used_as_collateral": "Morpho Blue",
            "underlying_apy_pct": 6.1,
            "collateral_factor_pct": 85.0,
            "liquidation_threshold_pct": 90.0,
            "current_ltv_pct": 88.0,
            "position_value_usd": 200000.0,
            "borrow_rate_pct": 5.8,
            "rebasing_type": "non_rebasing",
            "oracle_type": "protocol_native",
            "price_deviation_risk_pct": 0.2,
        },
    ]


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = _build_parser().parse_args(argv)

    analyzer = DeFiYieldBearingCollateralAnalyzer()
    positions = _sample_positions()
    result = analyzer.analyze(positions, {})

    print(json.dumps(result, indent=2, ensure_ascii=False))

    if args.run:
        data_dir = Path(args.data_dir)
        write_log(result, data_dir)

    return 0


if __name__ == "__main__":
    sys.exit(main())
