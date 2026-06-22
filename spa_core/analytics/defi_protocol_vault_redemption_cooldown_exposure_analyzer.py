"""
MP-1170: DeFiProtocolVaultRedemptionCooldownExposureAnalyzer
============================================================
Advisory/read-only analytics module.

When a holder asks to withdraw, many vaults impose a redemption COOLDOWN
(`cooldown_days`). During that window the holder's capital REMAINS under market
exposure — the share price keeps moving — yet the holder CANNOT act (cannot
exit, cannot re-deploy). This module quantifies that "locked-in" exposure: the
expected adverse price move (1σ / 2σ value-at-risk) over the cooldown horizon,
and the yield foregone if the capital sits idle during cooldown.

Angle: "the vault enforces a 14-day cooldown; at 2%/day volatility the share
price can drift ~7.5% against me over that window while I'm powerless to exit,
and if it does not earn during cooldown I also forfeit the APR."

HIGHER score = LESS cooldown risk (short cooldown, cheap exposure, not trapped).

Distinct from:
  * withdrawal_queue_risk_analyzer → that one is about protocol-level CONGESTION
    of the exit QUEUE (how long until your turn comes). This module is about the
    holder's MARKET EXPOSURE during a KNOWN, contractual cooldown period.

Pure stdlib, read-only/advisory, atomic ring-buffer log, sentinels (no inf/NaN).
"""

import json
import math
import os
from datetime import datetime, timezone
from typing import List, Optional

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "vault_redemption_cooldown_exposure_log.json"
)
LOG_CAP = 100

# Scoring reference ceilings.
COOLDOWN_SCORE_CEILING_DAYS = 14.0   # cooldown normalised against this ceiling.
COST_SCORE_CEILING_PCT = 10.0        # cooldown_cost_pct normalised vs ceiling.

# Classification thresholds (cooldown_cost_pct).
LOW_EXPOSURE_COST_PCT = 1.0          # at/below this → low exposure.
MODERATE_EXPOSURE_COST_PCT = 5.0     # at/below this → moderate; above → high.

# Flag thresholds.
LONG_COOLDOWN_DAYS = 14.0            # cooldown at/above this → long.
HIGH_VAR_COST_PCT = 5.0             # cooldown_cost_pct at/above this → high var.


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

class DeFiProtocolVaultRedemptionCooldownExposureAnalyzer:
    """
    Quantifies the market exposure a holder is forced to carry during a vault's
    redemption cooldown. Once a withdrawal is requested, capital stays exposed to
    share-price moves for `cooldown_days` while the holder cannot act. This
    module estimates the 1σ / 2σ value-at-risk over the cooldown horizon and the
    yield foregone if capital does not earn during cooldown.

    HIGHER score = LESS cooldown risk (short cooldown, cheap exposure, not
    trapped).

    Per-position input dict fields:
        vault / token            : str
        position_usd             : float (default 0)
        cooldown_days            : float (default 0; max(0,..))
        daily_volatility_pct     : float (default 0; max(0,..); share-price σ/day)
        earns_during_cooldown    : bool  (default False)
        vault_apr_pct            : float (default 0)
        exit_urgency_days        : float (default 0; days until funds may be
                                          needed; 0 = none/unknown)
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
        position_usd = _f(p.get("position_usd"))
        cooldown_days = max(0.0, _f(p.get("cooldown_days")))
        daily_vol = max(0.0, _f(p.get("daily_volatility_pct")))
        earns = bool(p.get("earns_during_cooldown", False))
        apr = _f(p.get("vault_apr_pct"))
        exit_urgency_days = _f(p.get("exit_urgency_days"))

        # Fast-path: no capital to measure.
        if position_usd <= 0:
            return self._insufficient(token)

        position_usd = max(0.0, position_usd)
        has_cooldown = bool(cooldown_days > 0)

        # Expected adverse move over the cooldown horizon (σ * sqrt(t)).
        raw_move = daily_vol * math.sqrt(cooldown_days) if cooldown_days > 0 \
            else 0.0
        if not math.isfinite(raw_move):
            raw_move = 0.0
        expected_adverse_move_pct = _clamp(raw_move, 0.0, 1e9)

        # 1σ downside value-at-risk (>= 0).
        value_at_risk_usd = _clamp(
            position_usd * expected_adverse_move_pct / 100.0, 0.0, 1e18)
        two_sigma_var_usd = _clamp(2.0 * value_at_risk_usd, 0.0, 1e18)

        # Yield foregone if capital sits idle during cooldown.
        if earns:
            foregone_yield_usd = 0.0
        else:
            raw_fy = position_usd * apr / 100.0 * cooldown_days / 365.0
            if not math.isfinite(raw_fy):
                raw_fy = 0.0
            foregone_yield_usd = _clamp(raw_fy, 0.0, 1e18)

        # Total cooldown cost as a fraction of the position.
        cost_num = value_at_risk_usd + foregone_yield_usd
        if position_usd > 0:
            cooldown_cost_pct = _clamp(cost_num / position_usd * 100.0,
                                       0.0, 1e9)
        else:
            cooldown_cost_pct = 0.0
        if not math.isfinite(cooldown_cost_pct):
            cooldown_cost_pct = 0.0

        # Trapped: funds needed sooner than the cooldown will release them.
        trapped = bool(
            exit_urgency_days > 0 and cooldown_days > exit_urgency_days)

        score = self._score(cooldown_days, cooldown_cost_pct, trapped)
        classification = self._classify(cooldown_days, cooldown_cost_pct,
                                        trapped)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags = self._flags(cooldown_days, earns, trapped, cooldown_cost_pct)

        return {
            "token": token,
            "position_usd": round(position_usd, 4),
            "cooldown_days": round(cooldown_days, 4),
            "has_cooldown": has_cooldown,
            "daily_volatility_pct": round(daily_vol, 4),
            "expected_adverse_move_pct": round(expected_adverse_move_pct, 4),
            "value_at_risk_usd": round(value_at_risk_usd, 4),
            "two_sigma_var_usd": round(two_sigma_var_usd, 4),
            "foregone_yield_usd": round(foregone_yield_usd, 4),
            "cooldown_cost_pct": round(cooldown_cost_pct, 4),
            "earns_during_cooldown": earns,
            "trapped": trapped,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        cooldown_days: float,
        cooldown_cost_pct: float,
        trapped: bool,
    ) -> float:
        """
        0–100, HIGHER = LESS cooldown risk. Components:
          short cooldown (40) — cooldown normalised against the ceiling.
          low cost (40) — cooldown_cost_pct normalised against the ceiling.
          not trapped (20) — full if funds are not needed before release.
        For INSTANT_EXIT (no cooldown) the score is a perfect 100.
        """
        if cooldown_days <= 0:
            return 100.0
        short_comp = 40.0 * _clamp(
            1.0 - cooldown_days / COOLDOWN_SCORE_CEILING_DAYS, 0.0, 1.0)
        cost_comp = 40.0 * _clamp(
            1.0 - cooldown_cost_pct / COST_SCORE_CEILING_PCT, 0.0, 1.0)
        trapped_comp = 0.0 if trapped else 20.0
        total = short_comp + cost_comp + trapped_comp
        return _clamp(total, 0.0, 100.0)

    def _classify(
        self,
        cooldown_days: float,
        cooldown_cost_pct: float,
        trapped: bool,
    ) -> str:
        if cooldown_days <= 0:
            return "INSTANT_EXIT"
        if trapped:
            return "TRAPPED_RISK"
        if cooldown_cost_pct <= LOW_EXPOSURE_COST_PCT:
            return "LOW_EXPOSURE"
        if cooldown_cost_pct <= MODERATE_EXPOSURE_COST_PCT:
            return "MODERATE_EXPOSURE"
        return "HIGH_EXPOSURE"

    def _recommend(self, classification: str) -> str:
        return {
            "INSUFFICIENT_DATA": "HOLD",
            "INSTANT_EXIT": "EXIT_ANYTIME",
            "LOW_EXPOSURE": "ENTER_OK",
            "MODERATE_EXPOSURE": "ENTER_REDUCED_SIZE",
            "HIGH_EXPOSURE": "AVOID_IF_LIQUIDITY_NEEDED",
            "TRAPPED_RISK": "AVOID",
        }.get(classification, "HOLD")

    def _flags(
        self,
        cooldown_days: float,
        earns: bool,
        trapped: bool,
        cooldown_cost_pct: float,
    ) -> List[str]:
        flags: List[str] = []

        if cooldown_days > 0:
            flags.append("HAS_COOLDOWN")
        else:
            flags.append("INSTANT_EXIT")
        if earns:
            flags.append("EARNS_DURING_COOLDOWN")
        if not earns and cooldown_days > 0:
            flags.append("IDLE_DURING_COOLDOWN")
        if trapped:
            flags.append("TRAPPED")
        if cooldown_days >= LONG_COOLDOWN_DAYS:
            flags.append("LONG_COOLDOWN")
        if cooldown_cost_pct >= HIGH_VAR_COST_PCT:
            flags.append("HIGH_VAR")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "position_usd": 0.0,
            "cooldown_days": 0.0,
            "has_cooldown": False,
            "daily_volatility_pct": 0.0,
            "expected_adverse_move_pct": 0.0,
            "value_at_risk_usd": 0.0,
            "two_sigma_var_usd": 0.0,
            "foregone_yield_usd": 0.0,
            "cooldown_cost_pct": 0.0,
            "earns_during_cooldown": False,
            "trapped": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "HOLD",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results
                  if r["classification"] != "INSUFFICIENT_DATA"]
        trapped_count = sum(1 for r in results if r.get("trapped"))
        if not scored:
            return {
                "safest_vault": None,
                "riskiest_vault": None,
                "avg_score": 0.0,
                "trapped_count": trapped_count,
                "position_count": len(results),
            }
        # Higher score = safer (less cooldown risk).
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        return {
            "safest_vault": by_score[-1]["token"],
            "riskiest_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "trapped_count": trapped_count,
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
            "vault": "USDC-Vault-Instant",
            "position_usd": 100000.0,
            "cooldown_days": 0.0,
            "daily_volatility_pct": 0.1,
            "earns_during_cooldown": True,
            "vault_apr_pct": 5.0,
            "exit_urgency_days": 0.0,
        },
        {
            "vault": "ETH-Vault-LongIdle",
            "position_usd": 50000.0,
            "cooldown_days": 21.0,
            "daily_volatility_pct": 3.0,
            "earns_during_cooldown": False,
            "vault_apr_pct": 12.0,
            "exit_urgency_days": 0.0,
        },
        {
            "vault": "GMX-Vault-Trapped",
            "position_usd": 25000.0,
            "cooldown_days": 14.0,
            "daily_volatility_pct": 2.0,
            "earns_during_cooldown": False,
            "vault_apr_pct": 20.0,
            "exit_urgency_days": 5.0,
        },
        {
            "vault": "DAI-Vault-NoData",
            "position_usd": 0.0,
            "cooldown_days": 7.0,
            "daily_volatility_pct": 1.0,
            "earns_during_cooldown": False,
            "vault_apr_pct": 8.0,
            "exit_urgency_days": 0.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1170 Vault Redemption Cooldown Exposure Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultRedemptionCooldownExposureAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
