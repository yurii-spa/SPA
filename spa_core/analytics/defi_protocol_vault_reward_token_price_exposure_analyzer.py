"""
MP-1170: DeFiProtocolVaultRewardTokenPriceExposureAnalyzer
==========================================================
Advisory/read-only analytics module.

A vault pays part of its headline APR in a VOLATILE reward/incentive token
(e.g. CRV, a points token). The holder's REALIZED yield depends on the reward
token's PRICE between when it accrues and when it is sold. If the reward token
has fallen, the realized reward APR is haircut below the headline; high
reward-token price volatility/drawdown = realization risk. The base (stable,
in-kind) APR is safe; only the reward-denominated portion is exposed.

Angle: "headline 20% APR but 12pp is paid in a reward token down 35% since
accrual → realized APR far below headline; high reward-token exposure."

HIGHER score = LESS reward-token price exposure / reward value better held
(more of the APR is safe base yield and/or the reward token has held/gained
value).

Distinct from:
  * defi_reward_token_sell_pressure_analyzer — market-wide sell pressure /
    price impact of OTHERS dumping the reward token.
  * protocol_defi_reward_token_lockup_discount_analyzer — PV haircut of LOCKED
    rewards (time-value, not price-move).
  * reward_token_liquidity_scorer — whether you can EXIT the reward token.
  THIS module isolates the holder's realized-value haircut from the reward
  token's PRICE MOVE, plus the share of APR that is reward-denominated vs the
  safe base.

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
    "data", "vault_reward_token_price_exposure_log.json"
)
LOG_CAP = 100

# Reward share classification thresholds (reward_share_pct of headline).
NO_EXPOSURE_SHARE_PCT = 2.0      # share at/below this → no reward exposure
LOW_EXPOSURE_SHARE_PCT = 25.0    # share at/below this → low reward exposure
MODERATE_EXPOSURE_SHARE_PCT = 50.0  # share at/below this → moderate; above → high

# reward_heavy: reward share at/above this is heavily reward-denominated.
REWARD_HEAVY_SHARE_PCT = 50.0

# price-move flag thresholds (reward_token_price_change_pct).
DEPRECIATED_CHANGE_PCT = -1.0    # change below this → depreciated
APPRECIATED_CHANGE_PCT = 1.0     # change above this → appreciated
# A "heavy" depreciation that forces a fast hedge/sell recommendation.
HEAVY_DEPRECIATION_CHANGE_PCT = -25.0

# volatility flag threshold and scoring ceiling (annualized vol %).
HIGH_VOLATILITY_PCT = 80.0
VOLATILITY_SCORE_CEILING_PCT = 120.0


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

class DeFiProtocolVaultRewardTokenPriceExposureAnalyzer:
    """
    Measures a vault holder's exposure to the PRICE MOVE of a volatile reward
    token. The headline APR is split into a safe base portion (paid in-kind /
    stable) and a reward-denominated portion. The realized value of the reward
    portion is scaled by the reward token's price change since accrual; a fall
    haircuts the realized reward APR below the headline. The module reports the
    realization haircut plus the share of APR that is reward-exposed.

    HIGHER score = LESS reward-token price exposure / reward value better held.

    Per-position input dict fields:
        vault / token                 : str
        headline_apr_pct              : float (default 0)
        reward_apr_pct                : float (default 0; max(0,..); clamped to
                                        <= headline) — portion paid in reward
                                        token.
        reward_token_price_change_pct : float (default 0; e.g. -35 = down 35%
                                        since accrual; may be positive)
        reward_token_volatility_pct   : float (default 0; max(0,..); annualized
                                        vol, used for the risk flag)
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
        headline = _f(p.get("headline_apr_pct"))
        reward_apr = max(0.0, _f(p.get("reward_apr_pct")))
        price_change = _f(p.get("reward_token_price_change_pct"))
        volatility = max(0.0, _f(p.get("reward_token_volatility_pct")))

        # Insufficient data fast-path: a non-positive headline gives no basis
        # for a reward-share or realization computation.
        if headline <= 0:
            return self._insufficient(token)

        # Reward APR cannot exceed the headline.
        reward_apr = min(reward_apr, headline)
        base_apr = max(0.0, headline - reward_apr)

        # Share of the headline that is reward-denominated.
        reward_share = _safe_div(reward_apr * 100.0, headline, None)
        if reward_share is not None and not math.isfinite(reward_share):
            reward_share = None
        if reward_share is None:
            reward_share = 0.0

        # Realized reward APR: scale by the price move, but a deep fall toward
        # -100% wipes the reward (never goes negative).
        price_factor = max(0.0, 1.0 + price_change / 100.0)
        realized_reward_apr = reward_apr * price_factor
        if not math.isfinite(realized_reward_apr):
            realized_reward_apr = 0.0

        realized_apr = base_apr + realized_reward_apr
        realization_haircut = headline - realized_apr  # negative if appreciated

        realization_ratio = _safe_div(realized_apr, headline, None)
        if realization_ratio is not None and not math.isfinite(
                realization_ratio):
            realization_ratio = None

        # Value lost (or gained) from the reward portion's price move.
        effective_loss_from_reward = reward_apr - realized_reward_apr

        reward_heavy = bool(reward_share >= REWARD_HEAVY_SHARE_PCT)
        reward_token_depreciated = bool(
            price_change < DEPRECIATED_CHANGE_PCT)
        reward_token_appreciated = bool(
            price_change > APPRECIATED_CHANGE_PCT)
        high_reward_volatility = bool(volatility >= HIGH_VOLATILITY_PCT)
        heavily_depreciated = bool(
            price_change <= HEAVY_DEPRECIATION_CHANGE_PCT)

        score = self._score(
            reward_share, reward_apr, realized_reward_apr, volatility)
        classification = self._classify(reward_share)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification, heavily_depreciated)
        flags = self._flags(
            classification,
            reward_heavy,
            reward_token_depreciated,
            reward_token_appreciated,
            high_reward_volatility,
        )

        return {
            "token": token,
            "headline_apr_pct": round(headline, 4),
            "base_apr_pct": round(base_apr, 4),
            "reward_apr_pct": round(reward_apr, 4),
            "reward_share_pct": round(reward_share, 4),
            "reward_token_price_change_pct": round(price_change, 4),
            "reward_token_volatility_pct": round(volatility, 4),
            "realized_reward_apr_pct": round(realized_reward_apr, 4),
            "realized_apr_pct": round(realized_apr, 4),
            "realization_haircut_pct": round(realization_haircut, 4),
            "realization_ratio": (
                None if realization_ratio is None
                else round(realization_ratio, 4)),
            "effective_loss_from_reward_pct": round(
                effective_loss_from_reward, 4),
            "reward_heavy": reward_heavy,
            "reward_token_depreciated": reward_token_depreciated,
            "high_reward_volatility": high_reward_volatility,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        reward_share: float,
        reward_apr: float,
        realized_reward_apr: float,
        volatility: float,
    ) -> float:
        """
        0–100, HIGHER = LESS reward-token price exposure. Components:
          safe-base-share (45) — (1 - reward_share/100) × 45; more safe base
            yield = safer.
          reward-held-value (35) — realized_reward / reward_apr clamped 0..1,
            × 35; if no reward APR, the full 35 (no value at risk).
          low-volatility (20) — (1 - vol/ceiling) × 20; calmer reward token =
            safer.
        """
        safe_base_comp = 45.0 * _clamp(
            1.0 - reward_share / 100.0, 0.0, 1.0)
        if reward_apr > 0:
            held_value_comp = 35.0 * _clamp(
                _safe_div(realized_reward_apr, reward_apr, 0.0), 0.0, 1.0)
        else:
            held_value_comp = 35.0
        low_vol_comp = 20.0 * _clamp(
            1.0 - volatility / VOLATILITY_SCORE_CEILING_PCT, 0.0, 1.0)
        total = safe_base_comp + held_value_comp + low_vol_comp
        return _clamp(total, 0.0, 100.0)

    def _classify(self, reward_share: float) -> str:
        if reward_share <= NO_EXPOSURE_SHARE_PCT:
            return "NO_REWARD_EXPOSURE"
        if reward_share <= LOW_EXPOSURE_SHARE_PCT:
            return "LOW_REWARD_EXPOSURE"
        if reward_share <= MODERATE_EXPOSURE_SHARE_PCT:
            return "MODERATE_REWARD_EXPOSURE"
        return "HIGH_REWARD_EXPOSURE"

    def _recommend(
        self,
        classification: str,
        heavily_depreciated: bool,
    ) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_OR_VERIFY"
        if classification == "HIGH_REWARD_EXPOSURE" or heavily_depreciated:
            return "HEDGE_OR_SELL_REWARDS_FAST"
        if classification == "MODERATE_REWARD_EXPOSURE":
            return "DISCOUNT_FOR_REWARD_RISK"
        # NO_REWARD_EXPOSURE or LOW_REWARD_EXPOSURE and not heavily depreciated
        return "TRUST_HEADLINE"

    def _flags(
        self,
        classification: str,
        reward_heavy: bool,
        reward_token_depreciated: bool,
        reward_token_appreciated: bool,
        high_reward_volatility: bool,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "NO_REWARD_EXPOSURE":
            flags.append("NO_REWARD_EXPOSURE")
        if classification == "LOW_REWARD_EXPOSURE":
            flags.append("LOW_REWARD_EXPOSURE")
        if classification == "MODERATE_REWARD_EXPOSURE":
            flags.append("MODERATE_REWARD_EXPOSURE")
        if classification == "HIGH_REWARD_EXPOSURE":
            flags.append("HIGH_REWARD_EXPOSURE")
        if reward_heavy:
            flags.append("REWARD_HEAVY")
        if reward_token_depreciated:
            flags.append("REWARD_TOKEN_DEPRECIATED")
        if reward_token_appreciated:
            flags.append("REWARD_TOKEN_APPRECIATED")
        if high_reward_volatility:
            flags.append("HIGH_REWARD_VOLATILITY")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "headline_apr_pct": 0.0,
            "base_apr_pct": 0.0,
            "reward_apr_pct": 0.0,
            "reward_share_pct": None,
            "reward_token_price_change_pct": 0.0,
            "reward_token_volatility_pct": 0.0,
            "realized_reward_apr_pct": None,
            "realized_apr_pct": None,
            "realization_haircut_pct": None,
            "realization_ratio": None,
            "effective_loss_from_reward_pct": None,
            "reward_heavy": False,
            "reward_token_depreciated": False,
            "high_reward_volatility": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID_OR_VERIFY",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "safest_vault": None,
                "most_exposed_vault": None,
                "avg_score": 0.0,
                "high_exposure_count": 0,
                "position_count": len(results),
            }
        # Higher score = less exposure → highest score is safest.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        high_exposure = sum(
            1 for r in results
            if r["classification"] == "HIGH_REWARD_EXPOSURE")
        return {
            "safest_vault": by_score[-1]["token"],
            "most_exposed_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "high_exposure_count": high_exposure,
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
            "vault": "USDC-Vault-NoReward",
            "headline_apr_pct": 8.0,
            "reward_apr_pct": 0.0,
            "reward_token_price_change_pct": 0.0,
            "reward_token_volatility_pct": 0.0,
        },
        {
            "vault": "CRV-Vault-LowExposure",
            "headline_apr_pct": 12.0,
            "reward_apr_pct": 2.0,
            "reward_token_price_change_pct": 5.0,
            "reward_token_volatility_pct": 60.0,
        },
        {
            "vault": "GMX-Vault-ModerateExposure",
            "headline_apr_pct": 16.0,
            "reward_apr_pct": 6.0,
            "reward_token_price_change_pct": -10.0,
            "reward_token_volatility_pct": 70.0,
        },
        {
            "vault": "Points-Vault-HighExposure",
            "headline_apr_pct": 20.0,
            "reward_apr_pct": 14.0,
            "reward_token_price_change_pct": -35.0,
            "reward_token_volatility_pct": 110.0,
        },
        {
            "vault": "DAI-Vault-NoData",
            "headline_apr_pct": 0.0,
            "reward_apr_pct": 0.0,
            "reward_token_price_change_pct": 0.0,
            "reward_token_volatility_pct": 0.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1170 Vault Reward Token Price Exposure Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultRewardTokenPriceExposureAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
