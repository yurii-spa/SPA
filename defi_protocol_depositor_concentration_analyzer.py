"""
MP-1155: DeFiProtocolDepositorConcentrationAnalyzer
==================================================
Advisory/read-only analytics module.

Given a vault's depositor distribution, compute how CONCENTRATED its deposit
base is among a few large holders ("whales"). A vault where one or two whales
hold the majority is fragile: if they exit, TVL collapses, APY craters, and the
remaining depositors face a slippage cascade on the way out. A diversified base
is safer. In other words: "if the biggest depositor leaves, how badly does that
hit my position, and is the base broad enough to absorb shocks?"

This isolates the *depositor-concentration / whale-dominance* question — top-1
and top-5 shares, effective depositor count, the TVL drop a whale exit would
cause, and the resulting hit to my own share.

Distinct from:
  * borrower_concentration analyzers → they model BORROWER (debt-side) clustering.
  * exit_liquidity analyzers         → they model market depth / slippage curves.
  * deposit_cap_headroom             → it models capacity to ENTER under a cap.
This module answers only the depositor-concentration / run-risk question.

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
    "data", "depositor_concentration_log.json"
)
LOG_CAP = 100

COUNT_SENTINEL_MAX = 1e6      # HHI ~ 0 → effective depositor count "very high"
HHI_MAX = 10000.0            # Herfindahl index upper bound (single holder)

# Concentration thresholds (top-1 share, %)
WHALE_DOMINATED_PCT = 50.0   # top-1 >=50% → whale-dominated
HIGHLY_CONCENTRATED_PCT = 30.0  # top-1 >=30% → highly concentrated
MODERATELY_CONCENTRATED_PCT = 15.0  # top-1 >=15% → moderately concentrated

# Top-5 concentration threshold (%)
HIGH_TOP5_PCT = 80.0         # top-5 >=80% → top-5 heavily concentrated

# Depositor-count threshold
FEW_DEPOSITORS = 5           # count <=5 (and >0) → thin base

# Whale-exit TVL-drop threshold (%)
SEVERE_EXIT_DROP_PCT = 40.0  # top-1 exit drops TVL >=40% → severe run risk

# HHI normalization band (for scoring): low HHI → diversified.
LOW_HHI = 1500.0             # HHI <1500 → competitive / diversified
HIGH_HHI = 2500.0            # HHI >2500 → concentrated


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

class DeFiProtocolDepositorConcentrationAnalyzer:
    """
    Analyzes how concentrated a vault's depositor base is and the run-risk a
    whale exit poses to the remaining depositors.

    HIGHER score = SAFER (more diversified deposit base).

    Per-position input dict fields:
        vault / token              : str
        total_tvl_usd              : float  (vault TVL)
        top1_share_pct             : float  (largest depositor's share, %)
        top5_share_pct             : float  (top-5 combined share, %, default 0)
        depositor_count            : float  (number of depositors, default 0)
        my_position_usd            : float  (my own deposit, default 0)
        hhi                        : float  (optional Herfindahl 0–10000;
                                             estimated from top shares if absent)
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
        top1 = _clamp(_f(p.get("top1_share_pct")), 0.0, 100.0)
        top5_raw = _clamp(_f(p.get("top5_share_pct")), 0.0, 100.0)
        depositor_count = max(0.0, _f(p.get("depositor_count")))
        my_position = max(0.0, _f(p.get("my_position_usd")))
        hhi_in = _f(p.get("hhi"), -1.0)

        # Insufficient data: no TVL, or no top-1 share and no other signal.
        if total_tvl <= 0 or (top1 <= 0 and top5_raw <= 0 and depositor_count <= 0):
            return self._insufficient(token)

        # top5 should be at least top1 (top-5 includes the top-1 holder).
        top5 = max(top5_raw, top1)

        # Estimate HHI if not supplied: top-1 contributes top1^2; the rest of the
        # top-5 spread evenly contributes a smaller term; remainder assumed thin.
        if hhi_in >= 0:
            concentration_hhi = _clamp(hhi_in, 0.0, HHI_MAX)
        else:
            rest5 = max(0.0, top5 - top1)
            # spread rest5 over (up to) 4 holders → each ~ rest5/4
            per_rest = rest5 / 4.0 if rest5 > 0 else 0.0
            est = top1 * top1 + 4.0 * (per_rest * per_rest)
            concentration_hhi = _clamp(est, 0.0, HHI_MAX)

        # Effective depositor count: prefer reported count; else 1/HHI_normalized.
        hhi_norm = concentration_hhi / HHI_MAX  # 0..1
        if depositor_count > 0:
            effective_count = depositor_count
        else:
            effective_count = _safe_div(1.0, hhi_norm, COUNT_SENTINEL_MAX)
            if effective_count >= COUNT_SENTINEL_MAX:
                effective_count = COUNT_SENTINEL_MAX

        # Whale exit: if top-1 leaves, TVL drops by top-1's share.
        whale_exit_drop = top1

        # My share of the vault, and my share after a whale exits.
        my_share = _clamp(
            _safe_div(my_position, total_tvl, 0.0) * 100.0, 0.0, 100.0,
        )
        remaining_frac = max(0.0, 1.0 - top1 / 100.0)
        if remaining_frac <= 0:
            post_exit_my_share = 0.0
        else:
            # my position stays; the denominator shrinks by the whale's exit.
            new_tvl = total_tvl * remaining_frac
            post_exit_my_share = _clamp(
                _safe_div(my_position, new_tvl, 0.0) * 100.0, 0.0, 100.0,
            )

        score = self._concentration_score(top1, top5, effective_count, concentration_hhi)
        classification = self._classify(top1)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags = self._flags(
            top1, top5, depositor_count, whale_exit_drop, classification,
        )

        return {
            "token": token,
            "total_tvl_usd": round(total_tvl, 2),
            "top1_share_pct": round(top1, 4),
            "top5_share_pct": round(top5, 4),
            "depositor_count": round(depositor_count, 2),
            "effective_depositor_count": (
                None if effective_count >= COUNT_SENTINEL_MAX else round(effective_count, 2)
            ),
            "whale_exit_tvl_drop_pct": round(whale_exit_drop, 4),
            "my_share_of_tvl_pct": round(my_share, 4),
            "post_whale_exit_my_share_pct": round(post_exit_my_share, 4),
            "concentration_hhi": round(concentration_hhi, 2),
            "concentration_score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _concentration_score(
        self,
        top1: float,
        top5: float,
        effective_count: float,
        concentration_hhi: float,
    ) -> float:
        """
        0–100, HIGHER = SAFER (more diversified). Weighted:
          low top-1 share (≈35) + low top-5 share (≈25)
          + many depositors (≈25) + low-HHI bonus (≈15).
        """
        # Low top-1 component — 0% → full, WHALE_DOMINATED_PCT+ → 0.
        top1_comp = 35.0 * _clamp(1.0 - top1 / WHALE_DOMINATED_PCT, 0.0, 1.0)

        # Low top-5 component — 0% → full, 100% → 0.
        top5_comp = 25.0 * _clamp(1.0 - top5 / 100.0, 0.0, 1.0)

        # Many-depositors component — saturating around 50 depositors.
        if effective_count >= COUNT_SENTINEL_MAX:
            count_comp = 25.0
        else:
            count_comp = 25.0 * _clamp(effective_count / 50.0, 0.0, 1.0)

        # Low-HHI bonus — HHI below LOW_HHI → full bonus, above HIGH_HHI → 0.
        if concentration_hhi <= LOW_HHI:
            bonus = 15.0
        elif concentration_hhi >= HIGH_HHI:
            bonus = 0.0
        else:
            span = HIGH_HHI - LOW_HHI
            bonus = 15.0 * _clamp(1.0 - (concentration_hhi - LOW_HHI) / span, 0.0, 1.0)

        return _clamp(top1_comp + top5_comp + count_comp + bonus, 0.0, 100.0)

    def _classify(self, top1: float) -> str:
        if top1 >= WHALE_DOMINATED_PCT:
            return "WHALE_DOMINATED"
        if top1 >= HIGHLY_CONCENTRATED_PCT:
            return "HIGHLY_CONCENTRATED"
        if top1 >= MODERATELY_CONCENTRATED_PCT:
            return "MODERATELY_CONCENTRATED"
        return "WELL_DISTRIBUTED"

    def _recommend(self, classification: str) -> str:
        if classification == "WELL_DISTRIBUTED":
            return "DEPLOY"
        if classification in ("MODERATELY_CONCENTRATED", "HIGHLY_CONCENTRATED"):
            return "DEPLOY_CAUTIOUSLY"
        return "AVOID"

    def _flags(
        self,
        top1: float,
        top5: float,
        depositor_count: float,
        whale_exit_drop: float,
        classification: str,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "WELL_DISTRIBUTED":
            flags.append("WELL_DISTRIBUTED")
            flags.append("DIVERSIFIED_BASE")

        if top1 >= WHALE_DOMINATED_PCT:
            flags.append("WHALE_DOMINATED")

        if top5 >= HIGH_TOP5_PCT:
            flags.append("HIGH_TOP5_CONCENTRATION")

        if 0 < depositor_count <= FEW_DEPOSITORS:
            flags.append("FEW_DEPOSITORS")
            flags.append("THIN_DEPOSITOR_BASE")

        if whale_exit_drop >= SEVERE_EXIT_DROP_PCT:
            flags.append("SEVERE_EXIT_RISK")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "total_tvl_usd": 0.0,
            "top1_share_pct": 0.0,
            "top5_share_pct": 0.0,
            "depositor_count": 0.0,
            "effective_depositor_count": None,
            "whale_exit_tvl_drop_pct": 0.0,
            "my_share_of_tvl_pct": 0.0,
            "post_whale_exit_my_share_pct": 0.0,
            "concentration_hhi": 0.0,
            "concentration_score": 0.0,
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
                "most_concentrated_vault": None,
                "least_concentrated_vault": None,
                "avg_concentration_score": 0.0,
                "whale_dominated_count": 0,
                "position_count": len(results),
            }
        # Higher score = safer/more diversified → lowest score is MOST concentrated.
        by_score = sorted(scored, key=lambda r: r["concentration_score"])
        avg = _mean([r["concentration_score"] for r in scored])
        whale_dominated = sum(1 for r in results if r["classification"] == "WHALE_DOMINATED")
        return {
            "most_concentrated_vault": by_score[0]["token"],
            "least_concentrated_vault": by_score[-1]["token"],
            "avg_concentration_score": round(avg, 2),
            "whale_dominated_count": whale_dominated,
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
                    "concentration_score": r["concentration_score"],
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
            "vault": "USDC-Vault-Diverse",
            "total_tvl_usd": 100_000_000.0,
            "top1_share_pct": 6.0,
            "top5_share_pct": 22.0,
            "depositor_count": 4200,
            "my_position_usd": 500_000.0,
        },
        {
            "vault": "ETH-Vault-Concentrated",
            "total_tvl_usd": 30_000_000.0,
            "top1_share_pct": 35.0,
            "top5_share_pct": 72.0,
            "depositor_count": 60,
            "my_position_usd": 200_000.0,
        },
        {
            "vault": "DAI-Vault-WhaleDom",
            "total_tvl_usd": 12_000_000.0,
            "top1_share_pct": 65.0,
            "top5_share_pct": 90.0,
            "depositor_count": 4,
            "my_position_usd": 100_000.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1155 Depositor Concentration Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolDepositorConcentrationAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
