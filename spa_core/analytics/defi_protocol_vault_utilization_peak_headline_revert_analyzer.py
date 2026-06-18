"""
MP-1191: DeFiProtocolVaultUtilizationPeakHeadlineRevertAnalyzer
==============================================================
Advisory/read-only analytics module.

Для lending-style волтов supply-APR ≈ borrow_apr × utilization ×
(1 − reserve_factor). Заголовочный supply-APR котируется при ТЕКУЩЕЙ
утилизации. Если текущая утилизация заметно ВЫШЕ типичной/равновесной полосы
волта, заголовок временно ЗАВЫШЕН и будет mean-revert вниз к
equilibrium-utilization APR по мере нормализации спроса на заём.
Buy-and-hold поставщик реализует ближе к РАВНОВЕСНОМУ APR, а не к пиковому
снапшоту.

Угол: "заголовочные 12% котируются при util=95%, но равновесие волта ~70% →
equilibrium-APR ≈ 12% × 70/95 ≈ 8.8% → дисконтируй заголовок к равновесной
базе для honest buy-and-hold."

HIGHER score = заголовок заякорен у равновесия (нет пикового завышения).

Отличие от:
  * defi_protocol_lending_utilization_cliff_detector (protocol_health) —
    обнаруживает близость к утилизационному КЛИФУ/кинку для риска вывода/
    ликвидаций; ЭТОТ модуль изолирует ЗАВЫШЕНИЕ headline supply-APR из-за
    временно пиковой утилизации, которая mean-revert.
  * defi_protocol_lending_utilization_elasticity_analyzer (market_conditions) —
    меряет ЧУВСТВИТЕЛЬНОСТЬ ставки к изменению утилизации; ЭТОТ дисконтирует
    заголовок к equilibrium-utilization базе для buy-and-hold.
  * defi_protocol_vault_apr_lookback_window_selection_bias_analyzer — про ВЫБОР
    временного ОКНА; ЭТОТ — про УРОВЕНЬ утилизации, формирующий снапшот.

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
    "data", "vault_utilization_peak_headline_revert_log.json"
)
LOG_CAP = 100

# Small epsilon for strict "above equilibrium" comparisons (pp of utilization).
EPS = 1e-9

# Utilization at/above which the vault is considered near full (flag).
NEAR_FULL_UTILIZATION_PCT = 90.0

# Classification thresholds on revert_haircut_pct (% the headline must shed to
# reach the equilibrium-utilization APR).
# at/below this → ANCHORED.
ANCHORED_HAIRCUT_PCT = 2.0
# at/below this → MILD_PEAK.
MILD_HAIRCUT_PCT = 10.0
# at/below this → MODERATE_PEAK; above → SEVERE_PEAK.
MODERATE_HAIRCUT_PCT = 25.0

# A revert haircut at/above this is flagged LARGE_REVERT_HAIRCUT.
LARGE_HAIRCUT_PCT = MODERATE_HAIRCUT_PCT

# Score penalty per point of revert_haircut_pct (HIGHER score = anchored).
# K=3 maps haircut 2 → 94 (A), 10 → 70 (B), 25 → 25 (F).
HAIRCUT_PENALTY_K = 3.0


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


def _is_number(val) -> bool:
    """True only for real, finite int/float (excludes bool / non-numeric)."""
    if isinstance(val, bool):
        return False
    if not isinstance(val, (int, float)):
        return False
    return math.isfinite(val)


def _valid_utilization(val) -> Optional[float]:
    """
    Return a utilization in (0, 100] as float, else None. Accepts numeric-ish
    strings via _f but rejects non-finite, <=0 and >100.
    """
    if not _is_number(val):
        # allow string-coercible numerics (e.g. "70") through _f
        coerced = _f(val, default=float("nan"))
        if not math.isfinite(coerced):
            return None
        val = coerced
    fv = float(val)
    if not math.isfinite(fv):
        return None
    if fv <= 0.0 or fv > 100.0:
        return None
    return fv


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

class DeFiProtocolVaultUtilizationPeakHeadlineRevertAnalyzer:
    """
    Измеряет, завышен ли заголовочный supply-APR волта из-за временно ПИКОВОЙ
    утилизации, которая mean-revert вниз к равновесной полосе. Для lending-style
    волтов supply-APR пропорционален утилизации; при util выше равновесия
    заголовок временно завышен. equilibrium_apr ≈ headline × (eq_util/cur_util)
    (только когда cur_util > eq_util). score 0-100 ВЫШЕ = заголовок заякорен у
    равновесия (нет пикового завышения). Только совет — фонды не двигает.

    Поля входного словаря позиции:
        vault / token                : str
        headline_apr_pct             : float; <=0 / non-finite → INSUFFICIENT_DATA.
        current_utilization_pct      : float 0..100; вне (0,100] / non-finite →
                                       INSUFFICIENT_DATA.
        equilibrium_utilization_pct  : float 0..100; вне (0,100] / non-finite →
                                       INSUFFICIENT_DATA.
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

        # Insufficient data: a non-positive / non-finite headline gives nothing
        # to discount.
        if headline <= 0 or not math.isfinite(headline):
            return self._insufficient(token, "INSUFFICIENT_DATA")

        cur_util = _valid_utilization(p.get("current_utilization_pct"))
        eq_util = _valid_utilization(p.get("equilibrium_utilization_pct"))
        if cur_util is None or eq_util is None:
            return self._insufficient(token, "INSUFFICIENT_DATA")

        # Linear approximation below the kink: supply-APR ∝ utilization.
        # Headline is quoted at the current utilization; the equilibrium-APR
        # discounts it by the utilization ratio ONLY when current sits above
        # equilibrium (a transient peak). At/below equilibrium nothing is
        # inflated by utilization → headline is anchored.
        if cur_util > eq_util:
            equilibrium_apr = headline * (eq_util / cur_util)
        else:
            equilibrium_apr = headline
        equilibrium_apr = _clamp(equilibrium_apr, 0.0, headline)

        utilization_excess_pct = max(0.0, cur_util - eq_util)

        # How much the headline must shed to reach the equilibrium-APR (0..100).
        revert_haircut = _safe_div(headline - equilibrium_apr, headline, 0.0)
        if revert_haircut is None or not math.isfinite(revert_haircut):
            revert_haircut = 0.0
        revert_haircut_pct = _clamp(revert_haircut * 100.0, 0.0, 100.0)

        # Premium the headline carries over the equilibrium-APR (%).
        premium = _safe_div(headline - equilibrium_apr, equilibrium_apr, 0.0)
        if premium is None or not math.isfinite(premium):
            premium = 0.0
        headline_premium_pct = max(0.0, premium * 100.0)
        if not math.isfinite(headline_premium_pct):
            headline_premium_pct = 0.0

        above_equilibrium = bool(cur_util > eq_util + EPS)
        near_full_utilization = bool(cur_util >= NEAR_FULL_UTILIZATION_PCT)

        score = self._score(revert_haircut_pct)
        classification = self._classify(revert_haircut_pct)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags = self._flags(
            classification, above_equilibrium, near_full_utilization,
            revert_haircut_pct)

        return {
            "token": token,
            "headline_apr_pct": round(headline, 4),
            "current_utilization_pct": round(cur_util, 4),
            "equilibrium_utilization_pct": round(eq_util, 4),
            "equilibrium_apr_pct": round(equilibrium_apr, 4),
            "utilization_excess_pct": round(utilization_excess_pct, 4),
            "revert_haircut_pct": round(revert_haircut_pct, 4),
            "headline_premium_pct": round(headline_premium_pct, 4),
            "above_equilibrium": above_equilibrium,
            "near_full_utilization": near_full_utilization,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(self, revert_haircut_pct: float) -> float:
        """
        0-100, HIGHER = anchored (headline tracks the equilibrium-APR, no
        transient-peak inflation).
          score = clamp(100 - revert_haircut_pct × HAIRCUT_PENALTY_K, 0, 100).
        With K=3 the grade bands line up with the classification thresholds:
        an ANCHORED headline (haircut ≤ 2) scores ≥ 94 (grade A); a MILD peak
        (haircut 10) scores 70 (grade B); a SEVERE peak (haircut ≥ 25) scores
        ≤ 25 (grade F).
        """
        haircut = _clamp(revert_haircut_pct, 0.0, 100.0)
        return _clamp(100.0 - haircut * HAIRCUT_PENALTY_K, 0.0, 100.0)

    def _classify(self, revert_haircut_pct: float) -> str:
        pct = max(0.0, revert_haircut_pct)
        if pct <= ANCHORED_HAIRCUT_PCT:
            return "ANCHORED"
        if pct <= MILD_HAIRCUT_PCT:
            return "MILD_PEAK"
        if pct <= MODERATE_HAIRCUT_PCT:
            return "MODERATE_PEAK"
        return "SEVERE_PEAK"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "VERIFY_DATA"
        if classification == "ANCHORED":
            return "TRUST_HEADLINE"
        if classification == "MILD_PEAK":
            return "MINOR_DISCOUNT"
        if classification == "MODERATE_PEAK":
            return "USE_EQUILIBRIUM_BASE"
        # SEVERE_PEAK
        return "AVOID_OR_VERIFY"

    def _flags(
        self,
        classification: str,
        above_equilibrium: bool,
        near_full_utilization: bool,
        revert_haircut_pct: float,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "ANCHORED":
            flags.append("ANCHORED")
        if classification == "MILD_PEAK":
            flags.append("MILD_PEAK")
        if classification == "MODERATE_PEAK":
            flags.append("MODERATE_PEAK")
        if classification == "SEVERE_PEAK":
            flags.append("SEVERE_PEAK")
        if above_equilibrium:
            flags.append("ABOVE_EQUILIBRIUM_UTIL")
        if near_full_utilization:
            flags.append("NEAR_FULL_UTILIZATION")
        if revert_haircut_pct >= LARGE_HAIRCUT_PCT:
            flags.append("LARGE_REVERT_HAIRCUT")

        return flags

    def _insufficient(self, token: str, classification: str) -> dict:
        return {
            "token": token,
            "headline_apr_pct": 0.0,
            "current_utilization_pct": None,
            "equilibrium_utilization_pct": None,
            "equilibrium_apr_pct": None,
            "utilization_excess_pct": None,
            "revert_haircut_pct": None,
            "headline_premium_pct": None,
            "above_equilibrium": False,
            "near_full_utilization": False,
            "score": 0.0,
            "classification": classification,
            "recommendation": "VERIFY_DATA",
            "grade": "F",
            "flags": [classification],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results
                  if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "least_revert_vault": None,
                "most_revert_vault": None,
                "avg_score": 0.0,
                "severe_peak_count": 0,
                "position_count": len(results),
            }
        # Higher score = less revert (anchored) → highest score is least-revert.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        severe = sum(
            1 for r in results
            if r["classification"] == "SEVERE_PEAK")
        return {
            "least_revert_vault": by_score[-1]["token"],
            "most_revert_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "severe_peak_count": severe,
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
            # Current util at equilibrium → headline anchored, no peak.
            "vault": "USDC-Vault-Anchored",
            "headline_apr_pct": 8.0,
            "current_utilization_pct": 70.0,
            "equilibrium_utilization_pct": 70.0,
        },
        {
            # Slightly above equilibrium → mild peak (~6.6% haircut → MILD).
            "vault": "DAI-Vault-Mild",
            "headline_apr_pct": 9.0,
            "current_utilization_pct": 75.0,
            "equilibrium_utilization_pct": 70.0,
        },
        {
            # Well above equilibrium → moderate peak (~17.6% haircut).
            "vault": "ETH-Vault-Moderate",
            "headline_apr_pct": 11.0,
            "current_utilization_pct": 85.0,
            "equilibrium_utilization_pct": 70.0,
        },
        {
            # Near-full util vs low equilibrium → severe peak (~37% haircut).
            "vault": "ARB-Vault-Severe",
            "headline_apr_pct": 14.0,
            "current_utilization_pct": 95.0,
            "equilibrium_utilization_pct": 60.0,
        },
        {
            # Current util BELOW equilibrium → headline not inflated → anchored.
            "vault": "OP-Vault-BelowEq",
            "headline_apr_pct": 7.0,
            "current_utilization_pct": 55.0,
            "equilibrium_utilization_pct": 70.0,
        },
        {
            # No headline → INSUFFICIENT_DATA.
            "vault": "Mystery-Vault-NoData",
            "headline_apr_pct": 0.0,
            "current_utilization_pct": 80.0,
            "equilibrium_utilization_pct": 70.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1191 Vault Utilization Peak Headline Revert Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultUtilizationPeakHeadlineRevertAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
