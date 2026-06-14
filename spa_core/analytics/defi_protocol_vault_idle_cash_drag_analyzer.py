"""
MP-1157: DeFiProtocolVaultIdleCashDragAnalyzer
==============================================
Advisory/read-only analytics module.

A yield vault often keeps part of its TVL as an idle / uninvested liquidity
buffer (for instant withdrawals) rather than deployed into the yield strategy.
Idle capital earns nothing, so the vault's *realized* (net) APY is lower than
its strategy (gross) APY. This module answers: "what fraction of this vault is
sitting idle, how much APY drag does that create, and is the buffer reasonable
or wastefully large?"

This isolates the *uninvested / idle capital and resulting yield drag* question
— idle vs deployed split, the gross-to-effective APR drag, how much idle exceeds
the intended buffer, and how much APR could be recovered.

Distinct from:
  * deposit_cap_headroom        → it models capacity to ENTER under a cap.
  * yield_reserve_buffer        → it models a profit-smoothing reserve.
  * performance-fee analyzers   → they model fee drag on returns.
This module answers only the idle-capital / yield-drag question.

Pure stdlib, read-only/advisory, atomic ring-buffer log, sentinels (no inf/NaN).
"""

import json
import math
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "vault_idle_cash_drag_log.json"
)
LOG_CAP = 100

DEFAULT_TARGET_BUFFER_PCT = 5.0   # buffer the vault intends to hold (%)

# Idle-fraction bands (%)
HEAVY_BUFFER_PCT = 20.0           # idle >= 20% (and < 50%) → heavy buffer
MOSTLY_IDLE_PCT = 50.0            # idle >= 50% → mostly idle

# Capital-efficiency flag threshold (deployed %)
EFFICIENT_DEPLOYED_PCT = 90.0     # deployed >= 90% → capital efficient


# ── helpers ───────────────────────────────────────────────────────────────────

def _f(val, default: float = 0.0) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _safe_div(num: float, den: float, sentinel: float) -> float:
    if den <= 0:
        return sentinel
    return num / den


def _build_default_cfg(overrides: Optional[dict] = None) -> dict:
    cfg = {"log_path": LOG_PATH, "log_cap": LOG_CAP}
    if overrides:
        cfg.update(overrides)
    return cfg


def _grade_from_score(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    if score >= 40:
        return "D"
    return "F"


# ── main class ────────────────────────────────────────────────────────────────

class DeFiProtocolVaultIdleCashDragAnalyzer:
    """
    Analyzes how much of a vault's TVL sits idle (uninvested) and the resulting
    APY drag, and whether the buffer is reasonable or wastefully large.

    HIGHER score = BETTER (more capital productively deployed, low excess idle).

    Per-position input dict fields:
        vault / token        : str
        total_tvl_usd        : float  (vault TVL)
        idle_cash_usd        : float  (uninvested buffer, default 0)
        deployed_usd         : float  (deployed capital; used if idle absent)
        strategy_apr_pct     : float  (gross APR on the DEPLOYED portion)
        target_buffer_pct    : float  (intended buffer, default 5.0)
    """

    # ── public API ────────────────────────────────────────────────────────────

    def analyze(
        self,
        position: dict,
        cfg: Optional[dict] = None,
        write_log: bool = False,
    ) -> dict:
        cfg = _build_default_cfg(cfg)
        result = self._analyze_one(position)
        if write_log:
            self._write_log([result], self._aggregate([result]), cfg)
        return result

    def analyze_portfolio(
        self,
        positions: List[dict],
        cfg: Optional[dict] = None,
        write_log: bool = False,
    ) -> dict:
        cfg = _build_default_cfg(cfg)
        results = [self._analyze_one(p) for p in positions]
        agg = self._aggregate(results)
        if write_log:
            self._write_log(results, agg, cfg)
        return {"positions": results, "aggregate": agg}

    # ── per-position ───────────────────────────────────────────────────────────

    def _analyze_one(self, p: dict) -> dict:
        token = p.get("vault", p.get("token", "UNKNOWN"))
        total_tvl = _f(p.get("total_tvl_usd"))
        strategy_apr = max(0.0, _f(p.get("strategy_apr_pct")))
        target_buffer = _clamp(
            _f(p.get("target_buffer_pct"), DEFAULT_TARGET_BUFFER_PCT),
            0.0, 100.0,
        )

        # Insufficient data: cannot reason about idle fraction without TVL.
        if total_tvl <= 0:
            return self._insufficient(token)

        # Resolve idle capital: prefer explicit idle, else derive from deployed.
        idle = self._resolve_idle(p, total_tvl)

        idle_pct = _clamp(_safe_div(idle, total_tvl, 0.0) * 100.0, 0.0, 100.0)
        deployed_pct = _clamp(100.0 - idle_pct, 0.0, 100.0)

        # Idle earns 0 → effective APR scales with deployed fraction.
        effective_apr = strategy_apr * deployed_pct / 100.0
        apr_drag = max(0.0, strategy_apr - effective_apr)

        # Idle beyond the intended buffer is "excess / wasteful".
        excess_idle_pct = max(0.0, idle_pct - target_buffer)
        recoverable_apr = strategy_apr * excess_idle_pct / 100.0

        score = self._efficiency_score(deployed_pct, excess_idle_pct)
        classification = self._classify(idle_pct, target_buffer)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags = self._flags(
            idle_pct, deployed_pct, excess_idle_pct, strategy_apr, classification,
        )

        return {
            "token": token,
            "total_tvl_usd": round(total_tvl, 2),
            "idle_cash_usd": round(idle, 2),
            "idle_pct": round(idle_pct, 4),
            "deployed_pct": round(deployed_pct, 4),
            "strategy_apr_pct": round(strategy_apr, 4),
            "effective_apr_pct": round(effective_apr, 4),
            "apr_drag_pct": round(apr_drag, 4),
            "target_buffer_pct": round(target_buffer, 4),
            "excess_idle_pct": round(excess_idle_pct, 4),
            "recoverable_apr_pct": round(recoverable_apr, 4),
            "efficiency_score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── metrics ────────────────────────────────────────────────────────────────

    def _resolve_idle(self, p: dict, total_tvl: float) -> float:
        """
        Resolve idle capital. Prefer explicit idle_cash_usd when supplied; else
        derive idle from deployed_usd; else default to 0. Clamped to [0, tvl].
        """
        if "idle_cash_usd" in p and p.get("idle_cash_usd") is not None:
            idle = _f(p.get("idle_cash_usd"))
        elif "deployed_usd" in p and p.get("deployed_usd") is not None:
            deployed = _f(p.get("deployed_usd"))
            idle = total_tvl - deployed
        else:
            idle = 0.0
        return _clamp(idle, 0.0, total_tvl)

    # ── scoring ────────────────────────────────────────────────────────────────

    def _efficiency_score(
        self,
        deployed_pct: float,
        excess_idle_pct: float,
    ) -> float:
        """
        0–100, HIGHER = BETTER. Weighted:
          deployed component (≈70, saturating toward 100% deployed)
          + low-excess-idle component (≈30, full when no excess idle).
        """
        deployed_comp = 70.0 * _clamp(deployed_pct / 100.0, 0.0, 1.0)
        excess_comp = 30.0 * _clamp(1.0 - excess_idle_pct / 100.0, 0.0, 1.0)
        return _clamp(deployed_comp + excess_comp, 0.0, 100.0)

    def _classify(self, idle_pct: float, target_buffer: float) -> str:
        if idle_pct >= MOSTLY_IDLE_PCT:
            return "MOSTLY_IDLE"
        if idle_pct >= HEAVY_BUFFER_PCT:
            return "HEAVY_BUFFER"
        if idle_pct <= target_buffer:
            return "FULLY_DEPLOYED"
        return "LEAN_BUFFER"

    def _recommend(self, classification: str) -> str:
        if classification in ("FULLY_DEPLOYED", "LEAN_BUFFER"):
            return "DEPLOY"
        if classification == "HEAVY_BUFFER":
            return "DEPLOY_CAUTIOUSLY"
        return "AVOID"

    def _flags(
        self,
        idle_pct: float,
        deployed_pct: float,
        excess_idle_pct: float,
        strategy_apr: float,
        classification: str,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "FULLY_DEPLOYED":
            flags.append("FULLY_DEPLOYED")

        if deployed_pct >= EFFICIENT_DEPLOYED_PCT:
            flags.append("CAPITAL_EFFICIENT")

        if excess_idle_pct > 0:
            flags.append("EXCESS_IDLE_CASH")

        if idle_pct >= HEAVY_BUFFER_PCT:
            flags.append("HEAVY_BUFFER")

        if idle_pct >= MOSTLY_IDLE_PCT:
            flags.append("MOSTLY_IDLE")

        if strategy_apr <= 0:
            flags.append("ZERO_STRATEGY_YIELD")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "total_tvl_usd": 0.0,
            "idle_cash_usd": 0.0,
            "idle_pct": 0.0,
            "deployed_pct": 0.0,
            "strategy_apr_pct": 0.0,
            "effective_apr_pct": 0.0,
            "apr_drag_pct": 0.0,
            "target_buffer_pct": 0.0,
            "excess_idle_pct": 0.0,
            "recoverable_apr_pct": 0.0,
            "efficiency_score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "most_idle_vault": None,
                "least_idle_vault": None,
                "avg_efficiency_score": 0.0,
                "mostly_idle_count": 0,
                "position_count": len(results),
            }
        # Higher score = better → lowest score is MOST idle.
        by_score = sorted(scored, key=lambda r: r["efficiency_score"])
        avg = _mean([r["efficiency_score"] for r in scored])
        mostly_idle = sum(1 for r in results if r["classification"] == "MOSTLY_IDLE")
        return {
            "most_idle_vault": by_score[0]["token"],
            "least_idle_vault": by_score[-1]["token"],
            "avg_efficiency_score": round(avg, 2),
            "mostly_idle_count": mostly_idle,
            "position_count": len(results),
        }

    # ── ring-buffer log ───────────────────────────────────────────────────────

    def _write_log(self, results: List[dict], agg: dict, cfg: dict) -> None:
        log_path = cfg["log_path"]
        cap = cfg["log_cap"]
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "position_count": len(results),
            "aggregate": agg,
            "snapshots": [
                {
                    "token": r["token"],
                    "classification": r["classification"],
                    "efficiency_score": r["efficiency_score"],
                    "recommendation": r["recommendation"],
                    "flags": r["flags"],
                }
                for r in results
            ],
        }

        log: List[dict] = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r") as fh:
                    log = json.load(fh)
                if not isinstance(log, list):
                    log = []
            except (json.JSONDecodeError, OSError):
                log = []

        log.append(entry)
        if len(log) > cap:
            log = log[-cap:]

        tmp = log_path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(log, fh, indent=2)
        os.replace(tmp, log_path)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _demo_positions() -> List[dict]:
    return [
        {
            "vault": "USDC-Vault-Efficient",
            "total_tvl_usd": 100_000_000.0,
            "idle_cash_usd": 3_000_000.0,
            "strategy_apr_pct": 8.0,
            "target_buffer_pct": 5.0,
        },
        {
            "vault": "ETH-Vault-HeavyBuffer",
            "total_tvl_usd": 50_000_000.0,
            "deployed_usd": 37_500_000.0,
            "strategy_apr_pct": 6.0,
            "target_buffer_pct": 5.0,
        },
        {
            "vault": "DAI-Vault-MostlyIdle",
            "total_tvl_usd": 20_000_000.0,
            "idle_cash_usd": 14_000_000.0,
            "strategy_apr_pct": 10.0,
            "target_buffer_pct": 5.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1157 Vault Idle Cash Drag Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultIdleCashDragAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
