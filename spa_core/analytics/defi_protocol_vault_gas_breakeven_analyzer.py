"""
MP-1164: DeFiProtocolVaultGasBreakevenAnalyzer
==============================================
Advisory/read-only analytics module.

Vaults carry FIXED gas overhead — a one-off round-trip cost to deposit and
withdraw, plus a recurring per-compound cost when the strategy auto-compounds.
That overhead is independent of position size, so for small positions it eats a
large share of the APR advantage; for large positions it is negligible. This
module answers, for a given position size and APR, whether the gas is worth it:
it computes the gas drag on the yield, the net-after-gas APR, the break-even
position size at which net yield turns positive, and the break-even holding days
needed for gross yield to cover the fixed entry/exit gas.

HIGHER score = less gas drag / faster break-even.

Distinct from:
  * vault_round_trip_cost  → percentage-based deposit/withdrawal fees + slippage.
  * vault_withdrawal_fee_decay → time-decaying loyalty exit fee.
This module isolates the *fixed dollar gas cost* of operating the vault and the
position size / holding period at which it pays for itself.

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
    "data", "vault_gas_breakeven_log.json"
)
LOG_CAP = 100

DAYS_PER_YEAR = 365.0

# Gas-drag classification thresholds (gas as a % of position over the horizon).
NEGLIGIBLE_GAS_PCT = 2.0    # drag at/below this is negligible
LOW_GAS_PCT = 5.0           # drag at/below this is low
MODERATE_GAS_PCT = 15.0     # drag at/below this is moderate; above → high

# Scoring reference: gas drag normalised against this ceiling for the low-drag
# component (drag at/above this contributes nothing).
GAS_DRAG_SCORE_CEILING_PCT = 20.0

# Flag thresholds.
SMALL_POSITION_USD = 1000.0        # positions at/below are "small"
HIGH_COMPOUND_GAS_SHARE_PCT = 50.0  # compound gas as share of total gas


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

class DeFiProtocolVaultGasBreakevenAnalyzer:
    """
    Models the FIXED gas overhead of operating a vault position and whether it
    pays for itself. Fixed round-trip gas (deposit + withdrawal) plus annual
    auto-compound gas are independent of position size, so for a given position
    size, APR and holding period the module computes gas drag, net-after-gas
    APR, the break-even position size and break-even holding days.

    HIGHER score = less gas drag / faster break-even.

    Per-position input dict fields:
        vault / token        : str
        position_usd         : float (default 0; max(0,..))
        deposit_gas_usd      : float (default 0; max(0,..))
        withdrawal_gas_usd   : float (default 0; max(0,..))
        compound_gas_usd     : float (default 0; max(0,..))
        compounds_per_year   : float (default 0; max(0,..))
        apr_pct              : float (default 0; max(0,..); gross vault APR)
        holding_days         : float (default 365; max(0,..))
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
        position_usd = max(0.0, _f(p.get("position_usd")))
        deposit_gas_usd = max(0.0, _f(p.get("deposit_gas_usd")))
        withdrawal_gas_usd = max(0.0, _f(p.get("withdrawal_gas_usd")))
        compound_gas_usd = max(0.0, _f(p.get("compound_gas_usd")))
        compounds_per_year = max(0.0, _f(p.get("compounds_per_year")))
        apr_pct = max(0.0, _f(p.get("apr_pct")))
        holding_days = max(0.0, _f(p.get("holding_days"), 365.0))

        # Insufficient data: no position and no APR → nothing to analyze.
        if position_usd <= 0 and apr_pct <= 0:
            return self._insufficient(token)

        total_fixed_gas_usd = deposit_gas_usd + withdrawal_gas_usd
        annual_compound_gas_usd = compound_gas_usd * compounds_per_year
        holding_years = holding_days / DAYS_PER_YEAR

        gross_yield_usd = position_usd * apr_pct / 100.0 * holding_years
        total_gas_usd = (
            total_fixed_gas_usd + annual_compound_gas_usd * holding_years)
        net_yield_usd = gross_yield_usd - total_gas_usd

        # Gas drag as a % of position over the whole horizon.
        gas_drag_pct = _safe_div(total_gas_usd, position_usd, 0.0) * 100.0

        # Annualised drag → net APR after gas. Guard horizon<=0.
        annualised_drag_pct = _safe_div(gas_drag_pct, holding_years, 0.0)
        net_apr_pct = apr_pct - annualised_drag_pct

        # Break-even position size: total_gas / (apr/100 * years). Fixed +
        # compound gas do not depend on size, so this is exact. None if the
        # position never earns (apr<=0 or horizon<=0).
        be_den = apr_pct / 100.0 * holding_years
        breakeven_position_usd = _safe_div(total_gas_usd, be_den, None)
        if breakeven_position_usd is not None and not math.isfinite(
                breakeven_position_usd):
            breakeven_position_usd = None

        # Break-even days: when gross yield covers the fixed round-trip gas.
        # position*apr/100*(d/365) = total_fixed_gas → d = fixed / (daily yield).
        daily_yield_usd = position_usd * apr_pct / 100.0 / DAYS_PER_YEAR
        breakeven_days = _safe_div(total_fixed_gas_usd, daily_yield_usd, None)
        if breakeven_days is not None and not math.isfinite(breakeven_days):
            breakeven_days = None

        covers_horizon = bool(net_yield_usd >= 0)
        never_breaks_even = (breakeven_position_usd is None) or (
            not covers_horizon and apr_pct <= 0)

        compound_gas_share_pct = _safe_div(
            annual_compound_gas_usd * holding_years, total_gas_usd, 0.0) * 100.0

        score = self._score(gas_drag_pct, covers_horizon, total_fixed_gas_usd)
        classification = self._classify(gas_drag_pct, covers_horizon, apr_pct)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification, covers_horizon)
        flags = self._flags(
            position_usd, gas_drag_pct, covers_horizon, net_yield_usd,
            total_fixed_gas_usd, compound_gas_share_pct, classification)

        return {
            "token": token,
            "position_usd": round(position_usd, 4),
            "deposit_gas_usd": round(deposit_gas_usd, 4),
            "withdrawal_gas_usd": round(withdrawal_gas_usd, 4),
            "compound_gas_usd": round(compound_gas_usd, 4),
            "compounds_per_year": round(compounds_per_year, 4),
            "apr_pct": round(apr_pct, 4),
            "holding_days": round(holding_days, 4),
            "holding_years": round(holding_years, 4),
            "total_fixed_gas_usd": round(total_fixed_gas_usd, 4),
            "annual_compound_gas_usd": round(annual_compound_gas_usd, 4),
            "gross_yield_usd": round(gross_yield_usd, 4),
            "total_gas_usd": round(total_gas_usd, 4),
            "net_yield_usd": round(net_yield_usd, 4),
            "gas_drag_pct": round(gas_drag_pct, 4),
            "net_apr_pct": round(net_apr_pct, 4),
            "breakeven_position_usd": (
                None if breakeven_position_usd is None
                else round(breakeven_position_usd, 4)),
            "breakeven_days": (
                None if breakeven_days is None else round(breakeven_days, 4)),
            "compound_gas_share_pct": round(compound_gas_share_pct, 4),
            "covers_horizon": covers_horizon,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        gas_drag_pct: float,
        covers_horizon: bool,
        total_fixed_gas_usd: float,
    ) -> float:
        """
        0–100, HIGHER = less gas drag / faster break-even. Components:
          low gas drag (50) — drag normalised against the scoring ceiling.
          positive net (30) — full credit when the horizon is covered.
          cheap fixed gas (20) — lower one-off round-trip gas.
        """
        low_drag_comp = 50.0 * _clamp(
            1.0 - gas_drag_pct / GAS_DRAG_SCORE_CEILING_PCT, 0.0, 1.0)
        positive_net_comp = 30.0 if covers_horizon else 0.0
        # Cheap fixed gas: full credit at $0, fading out toward a $100 round-trip.
        cheap_fixed_comp = 20.0 * _clamp(
            1.0 - total_fixed_gas_usd / 100.0, 0.0, 1.0)
        total = low_drag_comp + positive_net_comp + cheap_fixed_comp
        return _clamp(total, 0.0, 100.0)

    def _classify(
        self,
        gas_drag_pct: float,
        covers_horizon: bool,
        apr_pct: float,
    ) -> str:
        if apr_pct <= 0 or not covers_horizon:
            return "NEVER_BREAKS_EVEN"
        if gas_drag_pct <= NEGLIGIBLE_GAS_PCT:
            return "NEGLIGIBLE_GAS"
        if gas_drag_pct <= LOW_GAS_PCT:
            return "LOW_GAS"
        if gas_drag_pct <= MODERATE_GAS_PCT:
            return "MODERATE_GAS"
        return "HIGH_GAS"

    def _recommend(self, classification: str, covers_horizon: bool) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID"
        if classification in ("NEGLIGIBLE_GAS", "LOW_GAS"):
            return "DEPLOY"
        if classification == "MODERATE_GAS":
            return "DEPLOY_IF_LONG_HOLD"
        if classification == "HIGH_GAS":
            return "RECONSIDER_SIZE"
        # NEVER_BREAKS_EVEN
        return "AVOID"

    def _flags(
        self,
        position_usd: float,
        gas_drag_pct: float,
        covers_horizon: bool,
        net_yield_usd: float,
        total_fixed_gas_usd: float,
        compound_gas_share_pct: float,
        classification: str,
    ) -> List[str]:
        flags: List[str] = []

        if position_usd <= SMALL_POSITION_USD and gas_drag_pct > LOW_GAS_PCT:
            flags.append("SMALL_POSITION_GAS_HEAVY")
        if covers_horizon:
            flags.append("COVERS_HORIZON")
        if classification == "NEVER_BREAKS_EVEN":
            flags.append("NEVER_BREAKS_EVEN")
        if compound_gas_share_pct >= HIGH_COMPOUND_GAS_SHARE_PCT:
            flags.append("HIGH_COMPOUND_GAS")
        if total_fixed_gas_usd <= 0:
            flags.append("FREE_ENTRY_EXIT")
        if net_yield_usd < 0:
            flags.append("NEGATIVE_NET")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "position_usd": 0.0,
            "deposit_gas_usd": 0.0,
            "withdrawal_gas_usd": 0.0,
            "compound_gas_usd": 0.0,
            "compounds_per_year": 0.0,
            "apr_pct": 0.0,
            "holding_days": 0.0,
            "holding_years": 0.0,
            "total_fixed_gas_usd": 0.0,
            "annual_compound_gas_usd": 0.0,
            "gross_yield_usd": 0.0,
            "total_gas_usd": 0.0,
            "net_yield_usd": 0.0,
            "gas_drag_pct": 0.0,
            "net_apr_pct": 0.0,
            "breakeven_position_usd": None,
            "breakeven_days": None,
            "compound_gas_share_pct": 0.0,
            "covers_horizon": False,
            "score": 0.0,
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
                "cheapest_vault": None,
                "most_expensive_vault": None,
                "avg_score": 0.0,
                "high_gas_count": 0,
                "position_count": len(results),
            }
        # Higher score = less gas drag → highest score is cheapest.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        high_gas = sum(
            1 for r in results
            if r["classification"] in ("HIGH_GAS", "NEVER_BREAKS_EVEN"))
        return {
            "cheapest_vault": by_score[-1]["token"],
            "most_expensive_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "high_gas_count": high_gas,
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
                    "score": r["score"],
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
            "vault": "USDC-Vault-LargePosition",
            "position_usd": 100000.0,
            "deposit_gas_usd": 8.0,
            "withdrawal_gas_usd": 8.0,
            "compound_gas_usd": 2.0,
            "compounds_per_year": 52.0,
            "apr_pct": 6.0,
            "holding_days": 365.0,
        },
        {
            "vault": "GMX-Vault-TinyPosition",
            "position_usd": 200.0,
            "deposit_gas_usd": 30.0,
            "withdrawal_gas_usd": 30.0,
            "compound_gas_usd": 5.0,
            "compounds_per_year": 52.0,
            "apr_pct": 8.0,
            "holding_days": 30.0,
        },
        {
            "vault": "DAI-Vault-NoData",
            "position_usd": 0.0,
            "deposit_gas_usd": 0.0,
            "withdrawal_gas_usd": 0.0,
            "compound_gas_usd": 0.0,
            "compounds_per_year": 0.0,
            "apr_pct": 0.0,
            "holding_days": 365.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1164 Vault Gas Breakeven Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultGasBreakevenAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
