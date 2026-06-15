"""
MP-1175: DeFiProtocolVaultBribeDependencyAnalyzer
=================================================
Advisory/read-only analytics module.

What fraction of the vault's headline APR is funded by EXTERNAL vote-incentive /
bribe markets (Convex / Votium / Hidden Hand style)? Bribe APR is discretionary,
third-party-funded to direct emissions, and can evaporate epoch-to-epoch. High
bribe dependency plus a declining bribe trend = an unstable, overstated headline
APR; the base (organic fee / trading) APR is the durable part. The module splits
the headline into base and bribe slices and scores how much of the yield is
durable.

Angle: "headline 14% APR but 9pp is externally-funded bribe APR (64% share) and
bribes are down 40% epoch-on-epoch → discount the headline heavily; the durable
APR is closer to 5%."

HIGHER score = less bribe-dependent / more durable headline APR.

Distinct from:
  * defi_protocol_vault_reward_token_price_exposure_analyzer (MP-1170) — PRICE
    risk of the reward TOKEN paid in-kind.
  * real_yield_ratio — fee-vs-emission split generally.
  * emission_runway — the protocol's OWN emission schedule.
  THIS module isolates the externally-funded bribe APR slice, its share, its
  epoch-on-epoch trend, and its volatility.

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
    "data", "vault_bribe_dependency_log.json"
)
LOG_CAP = 100

# Bribe-share classification thresholds (bribe_share_pct of headline).
NO_DEP_PCT = 2.0        # share at/below this → no bribe dependency
LOW_DEP_PCT = 25.0      # share at/below this → low bribe dependency
MODERATE_DEP_PCT = 50.0  # share at/below this → moderate; above → high

# bribe_heavy flag: share at/above this is heavily bribe-funded.
BRIBE_HEAVY_PCT = 50.0

# Trend / volatility scoring references.
CHANGE_FLOOR_PCT = 50.0   # a 50% drop zeroes the trend component
VOL_CEILING_PCT = 100.0   # vol at/above this zeroes the volatility component

# Trend flag thresholds (bribe_apr_change_pct).
SEVERE_DECLINE_PCT = -25.0   # change at/below this forces a heavy discount
DECLINE_PCT = -1.0           # change below this → declining
RISE_PCT = 1.0               # change above this → rising

# Volatility flag threshold.
HIGH_VOL_PCT = 80.0


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

class DeFiProtocolVaultBribeDependencyAnalyzer:
    """
    Measures how much of a vault's headline APR is funded by external bribe /
    vote-incentive markets versus durable organic (fee / trading) yield. The
    headline APR is split into a durable base slice and a discretionary bribe
    slice; the bribe share, its epoch-on-epoch trend, and its volatility combine
    into a durability score. High bribe share with a sharp decline is an
    overstated, unstable headline APR.

    HIGHER score = less bribe-dependent / more durable headline APR.

    Per-position input dict fields:
        vault / token        : str
        headline_apr_pct     : float (max(0,..)); <=0 → INSUFFICIENT.
        bribe_apr_pct        : float (default 0; max(0,..); clamped <= headline)
                               — portion funded by external bribe markets.
        bribe_apr_change_pct : float (signed, default 0) — % change in bribe APR
                               vs the previous epoch (e.g. -40 = bribes down 40%).
        bribe_volatility_pct : float (default 0; max(0,..)) — epoch-on-epoch
                               volatility of the bribe APR.
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
        # for a bribe-share computation.
        if headline <= 0:
            return self._insufficient(token)

        bribe_apr = max(0.0, _f(p.get("bribe_apr_pct")))
        bribe_change = _f(p.get("bribe_apr_change_pct"))
        bribe_vol = max(0.0, _f(p.get("bribe_volatility_pct")))

        # Bribe APR cannot exceed the headline.
        bribe_apr = min(bribe_apr, headline)
        base_apr = max(0.0, headline - bribe_apr)

        # Share of the headline that is bribe-funded.
        bribe_share = _safe_div(bribe_apr * 100.0, headline, 0.0)
        if bribe_share is None or not math.isfinite(bribe_share):
            bribe_share = 0.0

        apr_if_bribes_halve = base_apr + bribe_apr * 0.5
        apr_if_bribes_vanish = base_apr
        durable_apr = base_apr

        share_frac = _clamp(bribe_share / 100.0, 0.0, 1.0)

        bribe_heavy = bool(bribe_share >= BRIBE_HEAVY_PCT)
        bribes_declining = bool(bribe_change < DECLINE_PCT)
        bribes_rising = bool(bribe_change > RISE_PCT)
        high_bribe_volatility = bool(bribe_vol >= HIGH_VOL_PCT)

        score = self._score(bribe_share, bribe_change, bribe_vol)
        classification = self._classify(bribe_share)
        grade = _grade_from_score(score)
        recommendation = self._recommend(
            classification, bribe_change, share_frac)
        flags = self._flags(
            classification,
            bribe_heavy,
            bribes_declining,
            bribes_rising,
            high_bribe_volatility,
        )

        return {
            "token": token,
            "headline_apr_pct": round(headline, 4),
            "base_apr_pct": round(base_apr, 4),
            "bribe_apr_pct": round(bribe_apr, 4),
            "bribe_share_pct": round(bribe_share, 4),
            "bribe_apr_change_pct": round(bribe_change, 4),
            "bribe_volatility_pct": round(bribe_vol, 4),
            "apr_if_bribes_halve_pct": round(apr_if_bribes_halve, 4),
            "apr_if_bribes_vanish_pct": round(apr_if_bribes_vanish, 4),
            "durable_apr_pct": round(durable_apr, 4),
            "bribe_heavy": bribe_heavy,
            "bribes_declining": bribes_declining,
            "bribes_rising": bribes_rising,
            "high_bribe_volatility": high_bribe_volatility,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        bribe_share: float,
        bribe_change: float,
        bribe_vol: float,
    ) -> float:
        """
        0–100, HIGHER = more durable. Components:
          durable (50) — (1 - share_frac) × 50; more organic yield = safer.
          trend (30) — full 30 minus a decline penalty that scales by BOTH the
            decline depth and the bribe dependence (a falling bribe only hurts
            if you depend on it).
          volatility (20) — full 20 minus a vol penalty that also scales by the
            bribe dependence.
        A bribe share of 0 → 100; penalties scale with dependence.
        """
        share_frac = _clamp(bribe_share / 100.0, 0.0, 1.0)
        durable_comp = 50.0 * (1.0 - share_frac)
        decline = abs(min(0.0, bribe_change))
        trend_comp = 30.0 - 30.0 * _clamp(
            decline / CHANGE_FLOOR_PCT, 0.0, 1.0) * share_frac
        vol_comp = 20.0 - 20.0 * _clamp(
            bribe_vol / VOL_CEILING_PCT, 0.0, 1.0) * share_frac
        total = durable_comp + trend_comp + vol_comp
        return _clamp(total, 0.0, 100.0)

    def _classify(self, bribe_share: float) -> str:
        if bribe_share <= NO_DEP_PCT:
            return "NO_BRIBE_DEPENDENCY"
        if bribe_share <= LOW_DEP_PCT:
            return "LOW_BRIBE_DEPENDENCY"
        if bribe_share <= MODERATE_DEP_PCT:
            return "MODERATE_BRIBE_DEPENDENCY"
        return "HIGH_BRIBE_DEPENDENCY"

    def _recommend(
        self,
        classification: str,
        bribe_change: float,
        share_frac: float,
    ) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "VERIFY_DATA"
        severe_decline = bribe_change <= SEVERE_DECLINE_PCT
        if classification == "HIGH_BRIBE_DEPENDENCY" and severe_decline:
            return "AVOID_OR_VERIFY"
        if classification == "HIGH_BRIBE_DEPENDENCY":
            return "DISCOUNT_HEAVILY"
        if severe_decline and share_frac > NO_DEP_PCT / 100.0:
            return "DISCOUNT_HEAVILY"
        if classification == "MODERATE_BRIBE_DEPENDENCY":
            return "DISCOUNT_FOR_BRIBE_RISK"
        # NO_BRIBE_DEPENDENCY or LOW_BRIBE_DEPENDENCY
        return "TRUST_HEADLINE"

    def _flags(
        self,
        classification: str,
        bribe_heavy: bool,
        bribes_declining: bool,
        bribes_rising: bool,
        high_bribe_volatility: bool,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "NO_BRIBE_DEPENDENCY":
            flags.append("NO_BRIBE_DEPENDENCY")
        if classification == "LOW_BRIBE_DEPENDENCY":
            flags.append("LOW_BRIBE_DEPENDENCY")
        if classification == "MODERATE_BRIBE_DEPENDENCY":
            flags.append("MODERATE_BRIBE_DEPENDENCY")
        if classification == "HIGH_BRIBE_DEPENDENCY":
            flags.append("HIGH_BRIBE_DEPENDENCY")
        if bribe_heavy:
            flags.append("BRIBE_HEAVY")
        if bribes_declining:
            flags.append("BRIBES_DECLINING")
        if bribes_rising:
            flags.append("BRIBES_RISING")
        if high_bribe_volatility:
            flags.append("HIGH_BRIBE_VOLATILITY")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "headline_apr_pct": 0.0,
            "base_apr_pct": 0.0,
            "bribe_apr_pct": 0.0,
            "bribe_share_pct": None,
            "bribe_apr_change_pct": 0.0,
            "bribe_volatility_pct": 0.0,
            "apr_if_bribes_halve_pct": None,
            "apr_if_bribes_vanish_pct": None,
            "durable_apr_pct": None,
            "bribe_heavy": False,
            "bribes_declining": False,
            "bribes_rising": False,
            "high_bribe_volatility": False,
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
                "most_durable_vault": None,
                "most_bribe_dependent_vault": None,
                "avg_score": 0.0,
                "high_dependency_count": 0,
                "position_count": len(results),
            }
        # Higher score = more durable → highest score is most durable.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        high_dependency = sum(
            1 for r in results
            if r["classification"] == "HIGH_BRIBE_DEPENDENCY")
        return {
            "most_durable_vault": by_score[-1]["token"],
            "most_bribe_dependent_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "high_dependency_count": high_dependency,
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
            "vault": "USDC-Vault-Organic",
            "headline_apr_pct": 8.0,
            "bribe_apr_pct": 0.0,
            "bribe_apr_change_pct": 0.0,
            "bribe_volatility_pct": 0.0,
        },
        {
            "vault": "ETH-Vault-LowDep",
            "headline_apr_pct": 12.0,
            "bribe_apr_pct": 2.0,
            "bribe_apr_change_pct": 3.0,
            "bribe_volatility_pct": 20.0,
        },
        {
            "vault": "ARB-Vault-ModerateDep",
            "headline_apr_pct": 16.0,
            "bribe_apr_pct": 6.0,
            "bribe_apr_change_pct": -8.0,
            "bribe_volatility_pct": 50.0,
        },
        {
            "vault": "CRV-Vault-HighDep-Declining",
            "headline_apr_pct": 14.0,
            "bribe_apr_pct": 9.0,
            "bribe_apr_change_pct": -40.0,
            "bribe_volatility_pct": 90.0,
        },
        {
            "vault": "CVX-Vault-HighDep-Stable",
            "headline_apr_pct": 18.0,
            "bribe_apr_pct": 12.0,
            "bribe_apr_change_pct": 2.0,
            "bribe_volatility_pct": 30.0,
        },
        {
            "vault": "Mystery-Vault-NoData",
            "headline_apr_pct": 0.0,
            "bribe_apr_pct": 0.0,
            "bribe_apr_change_pct": 0.0,
            "bribe_volatility_pct": 0.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1175 Vault Bribe Dependency Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultBribeDependencyAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
