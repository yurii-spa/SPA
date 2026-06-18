"""
MP-1177: DeFiProtocolVaultRewardAutosellSlippageAnalyzer
========================================================
Advisory/read-only analytics module.

An auto-compounding vault periodically SELLS its reward token to reinvest into
the underlying. If the size of that recurring sale is large relative to the
reward token's market depth, the compounding operation ITSELF incurs slippage,
which eats into realized yield below the headline. The bigger the sell relative
to depth, the worse the per-harvest price impact.

Angle: "a vault harvests and dumps $200k of CRV weekly into a $1.5M-deep pool →
~6.7% slippage per harvest drags the realized APY below the headline."

HIGHER score = cleaner compounding / less self-inflicted slippage.

Distinct from:
  * defi_protocol_vault_reward_token_price_exposure_analyzer (MP-1170) — the
    MARKET price risk of HOLDING the reward token.
  * defi_protocol_vault_bribe_dependency_analyzer (MP-1175) — external bribe
    FUNDING of the headline APR.
  * gas_cost_breakeven — gas DOLLARS spent on harvest, not price slippage.
  THIS module isolates the EXECUTION slippage of the vault's OWN recurring
  reward sale: sell size vs reward-token market depth.

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
    "data", "vault_reward_autosell_slippage_log.json"
)
LOG_CAP = 100

# est_slippage_pct classification thresholds.
NEGLIGIBLE_SLIPPAGE_PCT = 0.5   # slippage at/below this → negligible
LOW_SLIPPAGE_PCT = 2.0          # slippage at/below this → low
MODERATE_SLIPPAGE_PCT = 5.0     # slippage at/below this → moderate; above → high

# high_slippage flag: slippage at/above this is materially impactful.
HIGH_SLIPPAGE_PCT = 5.0

# Slippage model: selling 100% of market depth ≈ 50% slippage.
SLIPPAGE_IMPACT_FACTOR = 0.5

# Scoring references.
SLIPPAGE_CEILING = 20.0   # slippage at/above this zeroes the slippage component
DEPTH_CEILING = 0.5       # sell/depth at/above this zeroes the depth component

# thin_market flag threshold (sell_to_depth_ratio).
THIN_RATIO = 0.10

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

class DeFiProtocolVaultRewardAutosellSlippageAnalyzer:
    """
    Measures the EXECUTION slippage a vault inflicts on itself when it auto-sells
    its reward token to compound. The recurring sell size relative to the reward
    token's market depth drives a price-impact estimate, which discounts the
    reward slice of the APR. The base (non-reward) APR is unaffected. A large
    sell into a thin market is a self-inflicted drag the headline does not show.

    HIGHER score = cleaner compounding / less self-inflicted slippage.

    Per-position input dict fields:
        vault / token           : str
        headline_apr_pct        : float (max(0,..)); <=0 → INSUFFICIENT.
        reward_apr_pct          : float (default 0; max(0,..); clamped <=
                                  headline) — the APR slice paid in the
                                  auto-sold reward token. <=0 → NO_AUTOSELL.
        harvest_sell_usd        : float (default 0; max(0,..)) — USD size of each
                                  recurring reward sale.
        reward_market_depth_usd : float (default 0; max(0,..)) — market depth
                                  available for the sale. <=0 with reward>0 →
                                  INSUFFICIENT (slippage uncomputable).
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
        # for a reward-share / slippage computation.
        if headline <= 0:
            return self._insufficient(token)

        reward_apr = max(0.0, _f(p.get("reward_apr_pct")))
        sell_usd = max(0.0, _f(p.get("harvest_sell_usd")))
        depth_usd = max(0.0, _f(p.get("reward_market_depth_usd")))

        # Reward APR cannot exceed the headline.
        reward_apr = min(reward_apr, headline)
        base_apr = max(0.0, headline - reward_apr)

        # Share of the headline that is paid in the auto-sold reward token.
        reward_share = _safe_div(reward_apr * 100.0, headline, 0.0)
        if reward_share is None or not math.isfinite(reward_share):
            reward_share = 0.0

        # No auto-sell: the headline is fully trustworthy on the slippage axis.
        if reward_apr <= 0:
            return self._no_autosell(token, headline, base_apr, reward_share)

        # With a reward slice but no depth, slippage is uncomputable.
        if depth_usd <= 0:
            return self._insufficient(token)

        sell_to_depth = _safe_div(sell_usd, depth_usd, None)
        if sell_to_depth is None or not math.isfinite(sell_to_depth):
            sell_to_depth = 0.0

        est_slippage = _clamp(
            sell_to_depth * SLIPPAGE_IMPACT_FACTOR * 100.0, 0.0, 100.0)
        realized_reward_apr = reward_apr * (1.0 - est_slippage / 100.0)
        realized_reward_apr = _clamp(realized_reward_apr, 0.0, reward_apr)
        reward_apr_lost = max(0.0, reward_apr - realized_reward_apr)
        realized_headline_apr = base_apr + realized_reward_apr

        high_slippage = bool(est_slippage >= HIGH_SLIPPAGE_PCT)
        thin_market = bool(sell_to_depth >= THIN_RATIO)
        high_reward_share = bool(reward_share >= HIGH_REWARD_SHARE_PCT)

        score = self._score(est_slippage, sell_to_depth)
        classification = self._classify(est_slippage)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags = self._flags(
            classification,
            thin_market,
            high_reward_share,
            high_slippage,
        )

        return {
            "token": token,
            "headline_apr_pct": round(headline, 4),
            "base_apr_pct": round(base_apr, 4),
            "reward_apr_pct": round(reward_apr, 4),
            "reward_share_pct": round(reward_share, 4),
            "harvest_sell_usd": round(sell_usd, 4),
            "reward_market_depth_usd": round(depth_usd, 4),
            "sell_to_depth_ratio": round(sell_to_depth, 4),
            "est_slippage_pct": round(est_slippage, 4),
            "realized_reward_apr_pct": round(realized_reward_apr, 4),
            "reward_apr_lost_pct": round(reward_apr_lost, 4),
            "realized_headline_apr_pct": round(realized_headline_apr, 4),
            "high_slippage": high_slippage,
            "thin_market": thin_market,
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
        est_slippage: float,
        sell_to_depth: float,
    ) -> float:
        """
        0–100, HIGHER = cleaner compounding. Components:
          slippage (60) — (1 - clamp(slippage / SLIPPAGE_CEILING)) × 60; the
            direct realized-yield impact.
          depth (40) — (1 - clamp(sell_to_depth / DEPTH_CEILING)) × 40; a
            thin-market penalty independent of the modelled slippage.
        A slippage of 0 → 100; penalties scale with impact.
        """
        slippage_comp = 60.0 * (
            1.0 - _clamp(est_slippage / SLIPPAGE_CEILING, 0.0, 1.0))
        depth_comp = 40.0 * (
            1.0 - _clamp(sell_to_depth / DEPTH_CEILING, 0.0, 1.0))
        total = slippage_comp + depth_comp
        return _clamp(total, 0.0, 100.0)

    def _classify(self, est_slippage: float) -> str:
        if est_slippage <= NEGLIGIBLE_SLIPPAGE_PCT:
            return "NEGLIGIBLE_SLIPPAGE"
        if est_slippage <= LOW_SLIPPAGE_PCT:
            return "LOW_SLIPPAGE"
        if est_slippage <= MODERATE_SLIPPAGE_PCT:
            return "MODERATE_SLIPPAGE"
        return "HIGH_SLIPPAGE"

    def _recommend(
        self,
        classification: str,
    ) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "VERIFY_DATA"
        if classification in ("NO_AUTOSELL", "NEGLIGIBLE_SLIPPAGE"):
            return "TRUST_HEADLINE"
        if classification == "LOW_SLIPPAGE":
            return "MINOR_COMPOUNDING_DRAG"
        if classification == "MODERATE_SLIPPAGE":
            return "DISCOUNT_FOR_SLIPPAGE"
        # HIGH_SLIPPAGE
        return "AVOID_OR_VERIFY"

    def _flags(
        self,
        classification: str,
        thin_market: bool,
        high_reward_share: bool,
        high_slippage: bool,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "NO_AUTOSELL":
            flags.append("NO_AUTOSELL")
        if classification == "NEGLIGIBLE_SLIPPAGE":
            flags.append("NEGLIGIBLE_SLIPPAGE")
        if classification == "LOW_SLIPPAGE":
            flags.append("LOW_SLIPPAGE")
        if classification == "MODERATE_SLIPPAGE":
            flags.append("MODERATE_SLIPPAGE")
        if classification == "HIGH_SLIPPAGE":
            flags.append("HIGH_SLIPPAGE")
        if thin_market:
            flags.append("THIN_MARKET")
        if high_reward_share:
            flags.append("HIGH_REWARD_SHARE")

        return flags

    def _no_autosell(
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
            "harvest_sell_usd": 0.0,
            "reward_market_depth_usd": 0.0,
            "sell_to_depth_ratio": 0.0,
            "est_slippage_pct": 0.0,
            "realized_reward_apr_pct": 0.0,
            "reward_apr_lost_pct": 0.0,
            "realized_headline_apr_pct": round(headline, 4),
            "high_slippage": False,
            "thin_market": False,
            "high_reward_share": False,
            "score": 100.0,
            "classification": "NO_AUTOSELL",
            "recommendation": "TRUST_HEADLINE",
            "grade": "A",
            "flags": ["NO_AUTOSELL"],
        }

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "headline_apr_pct": 0.0,
            "base_apr_pct": 0.0,
            "reward_apr_pct": 0.0,
            "reward_share_pct": None,
            "harvest_sell_usd": 0.0,
            "reward_market_depth_usd": 0.0,
            "sell_to_depth_ratio": None,
            "est_slippage_pct": None,
            "realized_reward_apr_pct": None,
            "reward_apr_lost_pct": None,
            "realized_headline_apr_pct": None,
            "high_slippage": False,
            "thin_market": False,
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
                "cleanest_vault": None,
                "most_slippage_vault": None,
                "avg_score": 0.0,
                "high_slippage_count": 0,
                "position_count": len(results),
            }
        # Higher score = cleaner → highest score is cleanest.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        high_slip = sum(
            1 for r in results
            if r["classification"] == "HIGH_SLIPPAGE")
        return {
            "cleanest_vault": by_score[-1]["token"],
            "most_slippage_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "high_slippage_count": high_slip,
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
            "vault": "USDC-Vault-NoAutosell",
            "headline_apr_pct": 8.0,
            "reward_apr_pct": 0.0,
            "harvest_sell_usd": 0.0,
            "reward_market_depth_usd": 0.0,
        },
        {
            "vault": "ETH-Vault-Negligible",
            "headline_apr_pct": 12.0,
            "reward_apr_pct": 4.0,
            "harvest_sell_usd": 10000.0,
            "reward_market_depth_usd": 5000000.0,
        },
        {
            "vault": "ARB-Vault-LowSlippage",
            "headline_apr_pct": 16.0,
            "reward_apr_pct": 6.0,
            "harvest_sell_usd": 60000.0,
            "reward_market_depth_usd": 2000000.0,
        },
        {
            "vault": "CRV-Vault-ModerateSlippage",
            "headline_apr_pct": 18.0,
            "reward_apr_pct": 10.0,
            "harvest_sell_usd": 120000.0,
            "reward_market_depth_usd": 2000000.0,
        },
        {
            "vault": "CVX-Vault-HighSlippage-ThinMkt",
            "headline_apr_pct": 20.0,
            "reward_apr_pct": 14.0,
            "harvest_sell_usd": 200000.0,
            "reward_market_depth_usd": 1500000.0,
        },
        {
            "vault": "Mystery-Vault-NoData",
            "headline_apr_pct": 0.0,
            "reward_apr_pct": 0.0,
            "harvest_sell_usd": 0.0,
            "reward_market_depth_usd": 0.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1177 Vault Reward Autosell Slippage Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultRewardAutosellSlippageAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
