"""
MP-1178: DeFiProtocolVaultRewardSellPressureRunwayAnalyzer
==========================================================
Advisory/read-only analytics module.

A protocol/vault continuously emits and sells a reward token. The structural
"overhang" of recurring emission-driven sell pressure relative to the reward
token's organic buy-side liquidity (daily trading volume) determines how
sustainably the token holds its price. If the daily emission-sell USD is a
large fraction of the token's daily volume, there is constant downward pressure
on the price → the in-kind reward APR is worth less over time → the headline
overstates the durable yield.

Angle: "a vault pays an 8pp reward APR in a token whose daily emission-sell is
$400k against a $2M daily volume (20%) → a constant overhang, discount the
reward layer."

HIGHER score = more sustainable / overhang more easily absorbed.

Distinct from:
  * defi_protocol_vault_reward_autosell_slippage_analyzer (MP-1177) — the
    per-harvest EXECUTION slippage of the vault's OWN single sale.
  * defi_protocol_vault_reward_token_price_exposure_analyzer (MP-1170) — the
    MARKET price risk of HOLDING the reward token.
  * defi_protocol_vault_bribe_dependency_analyzer (MP-1175) — external bribe
    FUNDING of the headline APR slice.
  * gauge_emission_decay_forecaster (MP-1074) — the emission decay SCHEDULE.
  THIS module isolates the structural SELL-PRESSURE OVERHANG: protocol-level
  emission-sell USD vs the reward token's buy-side liquidity / volume — whether
  the market can absorb the current emissions.

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
    "data", "vault_reward_sell_pressure_runway_log.json"
)
LOG_CAP = 100

# sell_pressure_ratio (daily emission-sell USD / daily volume USD) thresholds.
NEGLIGIBLE_OVERHANG_RATIO = 0.02   # ratio at/below this → negligible
LOW_OVERHANG_RATIO = 0.05          # ratio at/below this → low
MODERATE_OVERHANG_RATIO = 0.15     # ratio at/below this → moderate; above → high

# absorbable flag: a ratio at/below this small threshold is comfortably absorbed.
ABSORBABLE_RATIO = 0.02

# thin_buyside flag threshold (sell_pressure_ratio).
THIN_BUYSIDE_RATIO = 0.10

# Scoring reference: a ratio at/above this fraction of daily volume zeroes the
# overhang component (≈25% of daily volume is treated as a maximal overhang).
OVERHANG_CEILING = 0.25

# High-reward-share flag threshold (reward_share_pct).
HIGH_REWARD_SHARE_PCT = 50.0


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


def _safe_div(num: float, den: float, sentinel):
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

class DeFiProtocolVaultRewardSellPressureRunwayAnalyzer:
    """
    Measures the structural SELL-PRESSURE OVERHANG of a vault/protocol that
    continuously emits and sells a reward token. The recurring daily emission-
    sell USD relative to the reward token's daily trading volume drives a
    sell-pressure ratio: the larger the share of daily volume consumed by the
    emission overhang, the more persistent the downward price pressure, which
    discounts the reward slice of the APR. The base (non-reward) APR is
    unaffected. A heavy overhang into a thin buy-side is a durable drag the
    headline does not show.

    HIGHER score = more sustainable / overhang more easily absorbed.

    Per-position input dict fields:
        vault / token             : str
        headline_apr_pct          : float (max(0,..)); <=0 → INSUFFICIENT.
        reward_apr_pct            : float (default 0; max(0,..); clamped <=
                                    headline) — the APR slice paid in the
                                    emission-sold reward token. <=0 →
                                    NO_EMISSIONS.
        daily_emission_sell_usd   : float (default 0; max(0,..)) — daily USD
                                    volume of emission-driven reward-token
                                    sells by the protocol.
        reward_token_daily_volume_usd : float (default 0; max(0,..)) — daily
                                    trading volume of the reward token. <=0 with
                                    reward>0 → INSUFFICIENT (overhang
                                    uncomputable).
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
        headline = max(0.0, _f(p.get("headline_apr_pct")))

        # Insufficient data fast-path: a non-positive headline gives no basis
        # for a reward-share / overhang computation.
        if headline <= 0:
            return self._insufficient(token)

        reward_apr = max(0.0, _f(p.get("reward_apr_pct")))
        emission_sell = max(0.0, _f(p.get("daily_emission_sell_usd")))
        daily_volume = max(0.0, _f(p.get("reward_token_daily_volume_usd")))

        # Reward APR cannot exceed the headline.
        reward_apr = min(reward_apr, headline)
        base_apr = max(0.0, headline - reward_apr)

        # Share of the headline that is paid in the emission-sold reward token.
        reward_share = _safe_div(reward_apr * 100.0, headline, 0.0)
        if reward_share is None or not math.isfinite(reward_share):
            reward_share = 0.0

        # No emissions: the headline is fully trustworthy on the overhang axis.
        if reward_apr <= 0:
            return self._no_emissions(token, headline, base_apr, reward_share)

        # With a reward slice but no buy-side volume, the overhang is
        # uncomputable.
        if daily_volume <= 0:
            return self._insufficient(token)

        sell_pressure_ratio = _safe_div(emission_sell, daily_volume, None)
        if sell_pressure_ratio is None or not math.isfinite(sell_pressure_ratio):
            sell_pressure_ratio = 0.0

        # Fraction of daily volume consumed by the emission overhang.
        est_sell_pressure = _clamp(sell_pressure_ratio * 100.0, 0.0, 100.0)

        absorbable = bool(sell_pressure_ratio <= ABSORBABLE_RATIO)
        thin_buyside = bool(sell_pressure_ratio >= THIN_BUYSIDE_RATIO)
        high_reward_share = bool(reward_share >= HIGH_REWARD_SHARE_PCT)

        score = self._score(sell_pressure_ratio, reward_share)
        classification = self._classify(sell_pressure_ratio)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags = self._flags(
            classification,
            thin_buyside,
            high_reward_share,
        )

        return {
            "token": token,
            "headline_apr_pct": round(headline, 4),
            "base_apr_pct": round(base_apr, 4),
            "reward_apr_pct": round(reward_apr, 4),
            "reward_share_pct": round(reward_share, 4),
            "daily_emission_sell_usd": round(emission_sell, 4),
            "reward_token_daily_volume_usd": round(daily_volume, 4),
            "sell_pressure_ratio": round(sell_pressure_ratio, 4),
            "est_sell_pressure_pct": round(est_sell_pressure, 4),
            "absorbable": absorbable,
            "thin_buyside": thin_buyside,
            "high_reward_share": high_reward_share,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        sell_pressure_ratio: float,
        reward_share: float,
    ) -> float:
        """
        0–100, HIGHER = more sustainable / overhang more easily absorbed.
        Components:
          pressure (60) — (1 - clamp(ratio / OVERHANG_CEILING)) × 60; the
            direct overhang impact on the reward token's price.
          share-weighted (40) — (1 - clamp(ratio / OVERHANG_CEILING) ×
            reward_share_frac) × 40; an overhang penalty scaled by how much of
            the headline rides on the emission-sold reward token.
        A ratio of 0 → 100; penalties scale with the overhang.
        """
        pressure_norm = _clamp(
            sell_pressure_ratio / OVERHANG_CEILING, 0.0, 1.0)
        reward_share_frac = _clamp(reward_share / 100.0, 0.0, 1.0)
        pressure_comp = 60.0 * (1.0 - pressure_norm)
        share_comp = 40.0 * (1.0 - pressure_norm * reward_share_frac)
        total = pressure_comp + share_comp
        return _clamp(total, 0.0, 100.0)

    def _classify(self, sell_pressure_ratio: float) -> str:
        if sell_pressure_ratio <= NEGLIGIBLE_OVERHANG_RATIO:
            return "NEGLIGIBLE_OVERHANG"
        if sell_pressure_ratio <= LOW_OVERHANG_RATIO:
            return "LOW_OVERHANG"
        if sell_pressure_ratio <= MODERATE_OVERHANG_RATIO:
            return "MODERATE_OVERHANG"
        return "HIGH_OVERHANG"

    def _recommend(
        self,
        classification: str,
    ) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "VERIFY_DATA"
        if classification in ("NO_EMISSIONS", "NEGLIGIBLE_OVERHANG"):
            return "TRUST_HEADLINE"
        if classification == "LOW_OVERHANG":
            return "MINOR_REWARD_DISCOUNT"
        if classification == "MODERATE_OVERHANG":
            return "DISCOUNT_REWARD_LAYER"
        # HIGH_OVERHANG
        return "AVOID_OR_VERIFY"

    def _flags(
        self,
        classification: str,
        thin_buyside: bool,
        high_reward_share: bool,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "NO_EMISSIONS":
            flags.append("NO_EMISSIONS")
        if classification == "NEGLIGIBLE_OVERHANG":
            flags.append("NEGLIGIBLE_OVERHANG")
        if classification == "LOW_OVERHANG":
            flags.append("LOW_OVERHANG")
        if classification == "MODERATE_OVERHANG":
            flags.append("MODERATE_OVERHANG")
        if classification == "HIGH_OVERHANG":
            flags.append("HIGH_OVERHANG")
        if thin_buyside:
            flags.append("THIN_BUYSIDE")
        if high_reward_share:
            flags.append("HIGH_REWARD_SHARE")

        return flags

    def _no_emissions(
        self,
        token: str,
        headline: float,
        base_apr: float,
        reward_share: float,
    ) -> dict:
        return {
            "token": token,
            "headline_apr_pct": round(headline, 4),
            "base_apr_pct": round(base_apr, 4),
            "reward_apr_pct": 0.0,
            "reward_share_pct": round(reward_share, 4),
            "daily_emission_sell_usd": 0.0,
            "reward_token_daily_volume_usd": 0.0,
            "sell_pressure_ratio": 0.0,
            "est_sell_pressure_pct": 0.0,
            "absorbable": True,
            "thin_buyside": False,
            "high_reward_share": False,
            "score": 100.0,
            "classification": "NO_EMISSIONS",
            "recommendation": "TRUST_HEADLINE",
            "grade": "A",
            "flags": ["NO_EMISSIONS"],
        }

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "headline_apr_pct": 0.0,
            "base_apr_pct": 0.0,
            "reward_apr_pct": 0.0,
            "reward_share_pct": None,
            "daily_emission_sell_usd": 0.0,
            "reward_token_daily_volume_usd": 0.0,
            "sell_pressure_ratio": None,
            "est_sell_pressure_pct": None,
            "absorbable": False,
            "thin_buyside": False,
            "high_reward_share": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "VERIFY_DATA",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "most_sustainable_vault": None,
                "most_overhang_vault": None,
                "avg_score": 0.0,
                "high_overhang_count": 0,
                "position_count": len(results),
            }
        # Higher score = more sustainable → highest score is most sustainable.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        high_overhang = sum(
            1 for r in results
            if r["classification"] == "HIGH_OVERHANG")
        return {
            "most_sustainable_vault": by_score[-1]["token"],
            "most_overhang_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "high_overhang_count": high_overhang,
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
            "vault": "USDC-Vault-NoEmissions",
            "headline_apr_pct": 8.0,
            "reward_apr_pct": 0.0,
            "daily_emission_sell_usd": 0.0,
            "reward_token_daily_volume_usd": 0.0,
        },
        {
            "vault": "ETH-Vault-Negligible",
            "headline_apr_pct": 12.0,
            "reward_apr_pct": 4.0,
            "daily_emission_sell_usd": 20000.0,
            "reward_token_daily_volume_usd": 5000000.0,
        },
        {
            "vault": "ARB-Vault-LowOverhang",
            "headline_apr_pct": 16.0,
            "reward_apr_pct": 6.0,
            "daily_emission_sell_usd": 80000.0,
            "reward_token_daily_volume_usd": 2000000.0,
        },
        {
            "vault": "CRV-Vault-ModerateOverhang",
            "headline_apr_pct": 18.0,
            "reward_apr_pct": 10.0,
            "daily_emission_sell_usd": 200000.0,
            "reward_token_daily_volume_usd": 2000000.0,
        },
        {
            "vault": "CVX-Vault-HighOverhang-ThinBuyside",
            "headline_apr_pct": 20.0,
            "reward_apr_pct": 14.0,
            "daily_emission_sell_usd": 400000.0,
            "reward_token_daily_volume_usd": 2000000.0,
        },
        {
            "vault": "Mystery-Vault-NoData",
            "headline_apr_pct": 0.0,
            "reward_apr_pct": 0.0,
            "daily_emission_sell_usd": 0.0,
            "reward_token_daily_volume_usd": 0.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1178 Vault Reward Sell Pressure Runway Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultRewardSellPressureRunwayAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
