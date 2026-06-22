"""
MP-1192: DeFiProtocolVaultBoostTierHeadlineRealizationAnalyzer
==============================================================
Advisory/read-only analytics module.

Во многих gauge/ve-модельных волтах (Curve/Convex-стиль) ЗАГОЛОВОЧНЫЙ APR — это
МАКСИМАЛЬНАЯ забустенная ставка, достижимая только при максимальном veToken-локе
(max_boost_multiplier, напр. 2.5×). Депозитор БЕЗ лока (unboosted) реализует
базовую ставку = headline / max_boost_multiplier. Депозитор с частичным бустом
реализует headline × (depositor_boost / max_boost).

Угол: "заголовок 20% — это max-boost 2.5×, но unboosted базовая = 8% →
дисконтируй заголовок к фактическому boost-тиру депозитора." ВЫШЕ score =
заголовок соответствует реально достижимому депозитором бусту (нет завышения
boost-тиром).

HIGHER score = headline реализуем при boost-тире депозитора (нет завышения).

Отличие от:
  * yield_booster_detector (MP-820) — ДЕТЕКТИРУЕТ boost-программы и их
    устойчивость/ценность; НЕ изолирует gap «max-boost заголовок vs реализуемый
    депозитором буст». ЭТОТ модуль изолирует именно этот gap.
  * defi_protocol_vault_trailing_window_boost_backdating_analyzer — про
    ИСТЁКШИЙ буст внутри трейлингового окна (backdating-артефакт в трейлинг-
    средней); ЭТОТ — про max-boost заголовок vs boost-тир депозитора СЕЙЧАС.
  * protocol_defi_ve_token_lock_optimizer / vetoken_governance_power —
    ОПТИМИЗИРУЮТ решение о локе; ЭТОТ дисконтирует заголовок к реализуемому
    депозитором бусту (не советует, как лочить).

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
    "data", "vault_boost_tier_headline_realization_log.json"
)
LOG_CAP = 100

# Small epsilon for strict "unboosted" comparisons (boost multiplier units).
EPS = 1e-9

# A max_boost_multiplier at/above this means the headline REQUIRES a meaningful
# lock to realize (flag MAX_BOOST_REQUIRED).
MAX_BOOST_REQUIRED_MULTIPLIER = 2.0

# Classification thresholds on boost_haircut_pct (% the headline must shed to
# reach the depositor-realized APR).
# at/below this → FULLY_REALIZED.
FULLY_REALIZED_HAIRCUT_PCT = 2.0
# at/below this → MILD_BOOST_GAP.
MILD_HAIRCUT_PCT = 15.0
# at/below this → MODERATE_BOOST_GAP; above → SEVERE_BOOST_GAP.
MODERATE_HAIRCUT_PCT = 40.0

# A boost haircut at/above this is flagged LARGE_BOOST_HAIRCUT.
LARGE_HAIRCUT_PCT = MODERATE_HAIRCUT_PCT

# Score penalty per point of boost_haircut_pct (HIGHER score = realized).
# K=1.6 maps haircut 2 → 96.8 (A), 15 → 76 (B), 40 → 36 (F).
HAIRCUT_PENALTY_K = 1.6


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


def _valid_max_boost(val) -> Optional[float]:
    """
    Return a max_boost_multiplier (>= 1.0) as float, else None. Accepts
    numeric-ish strings via _f but rejects non-finite and < 1.0.
    """
    if not _is_number(val):
        coerced = _f(val, default=float("nan"))
        if not math.isfinite(coerced):
            return None
        val = coerced
    fv = float(val)
    if not math.isfinite(fv):
        return None
    if fv < 1.0:
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

class DeFiProtocolVaultBoostTierHeadlineRealizationAnalyzer:
    """
    Измеряет, насколько заголовочный (котируемый при МАКС-бусте) APR волта
    завышен относительно того, что реально РЕАЛИЗУЕТ данный депозитор при его
    boost-тире. В gauge/ve-модельных волтах headline квотируется при
    max_boost_multiplier (напр. 2.5×); unboosted база = headline / max_boost;
    депозитор с фактическим depositor_boost реализует
    headline × (depositor_boost / max_boost). score 0-100 ВЫШЕ = заголовок
    реализуем при boost-тире депозитора (нет boost-завышения). Только совет —
    фонды не двигает.

    Поля входного словаря позиции:
        vault / token             : str
        headline_apr_pct          : float; <=0 / non-finite → INSUFFICIENT_DATA.
        max_boost_multiplier      : float >= 1.0; < 1.0 / non-finite /
                                    отсутствует → INSUFFICIENT_DATA.
        depositor_boost_multiplier: float; по умолчанию (отсутствует/невалиден)
                                    = 1.0 (unboosted); клампится в
                                    [1.0, max_boost_multiplier].
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

        max_boost = _valid_max_boost(p.get("max_boost_multiplier"))
        if max_boost is None:
            return self._insufficient(token, "INSUFFICIENT_DATA")

        # Depositor boost defaults to 1.0 (unboosted) and is clamped into
        # [1.0, max_boost]. Invalid / missing → unboosted.
        raw_dep = p.get("depositor_boost_multiplier")
        if _is_number(raw_dep):
            dep_boost = float(raw_dep)
        else:
            coerced = _f(raw_dep, default=float("nan"))
            dep_boost = coerced if math.isfinite(coerced) else 1.0
        if not math.isfinite(dep_boost):
            dep_boost = 1.0
        dep_boost = _clamp(dep_boost, 1.0, max_boost)

        # Unboosted base = headline at boost 1.0 = headline / max_boost.
        base_apr = _safe_div(headline, max_boost, headline)
        if base_apr is None or not math.isfinite(base_apr):
            base_apr = headline
        base_apr = _clamp(base_apr, 0.0, headline)

        # Realization ratio = depositor_boost / max_boost ∈ (0, 1].
        realization_ratio = _safe_div(dep_boost, max_boost, 1.0)
        if realization_ratio is None or not math.isfinite(realization_ratio):
            realization_ratio = 1.0
        realization_ratio = _clamp(realization_ratio, 0.0, 1.0)

        # Realized APR = headline × realization_ratio = base_apr × dep_boost.
        realized_apr = headline * realization_ratio
        realized_apr = _clamp(realized_apr, 0.0, headline)

        boost_gap_multiplier = max(0.0, max_boost - dep_boost)

        # How much the headline must shed to reach the depositor-realized APR
        # (0..100) = (1 - realization_ratio) × 100.
        boost_haircut_pct = _clamp((1.0 - realization_ratio) * 100.0, 0.0, 100.0)

        # Premium the headline carries over the depositor-realized APR (%).
        premium = _safe_div(headline - realized_apr, realized_apr, 0.0)
        if premium is None or not math.isfinite(premium):
            premium = 0.0
        boost_premium_pct = max(0.0, premium * 100.0)
        if not math.isfinite(boost_premium_pct):
            boost_premium_pct = 0.0

        unboosted = bool(dep_boost <= 1.0 + EPS and max_boost > 1.0 + EPS)
        max_boost_required = bool(max_boost >= MAX_BOOST_REQUIRED_MULTIPLIER)

        score = self._score(boost_haircut_pct)
        classification = self._classify(boost_haircut_pct)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags = self._flags(
            classification, unboosted, max_boost_required, boost_haircut_pct)

        return {
            "token": token,
            "headline_apr_pct": round(headline, 4),
            "max_boost_multiplier": round(max_boost, 4),
            "depositor_boost_multiplier": round(dep_boost, 4),
            "base_apr_pct": round(base_apr, 4),
            "realized_apr_pct": round(realized_apr, 4),
            "realization_ratio": round(realization_ratio, 4),
            "boost_gap_multiplier": round(boost_gap_multiplier, 4),
            "boost_haircut_pct": round(boost_haircut_pct, 4),
            "boost_premium_pct": round(boost_premium_pct, 4),
            "unboosted": unboosted,
            "max_boost_required": max_boost_required,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(self, boost_haircut_pct: float) -> float:
        """
        0-100, HIGHER = realized (headline tracks the depositor-realized APR, no
        boost-tier inflation).
          score = clamp(100 - boost_haircut_pct × HAIRCUT_PENALTY_K, 0, 100).
        With K=1.6 the grade bands line up with the classification thresholds:
        a FULLY_REALIZED headline (haircut ≤ 2) scores ≥ 96.8 (grade A); a MILD
        gap (haircut 15) scores 76 (grade B); the MODERATE/SEVERE boundary
        (haircut 40) scores 36 (grade F). (haircut 2→96.8 A, 15→76 B, 40→36 F.)
        """
        haircut = _clamp(boost_haircut_pct, 0.0, 100.0)
        return _clamp(100.0 - haircut * HAIRCUT_PENALTY_K, 0.0, 100.0)

    def _classify(self, boost_haircut_pct: float) -> str:
        pct = max(0.0, boost_haircut_pct)
        if pct <= FULLY_REALIZED_HAIRCUT_PCT:
            return "FULLY_REALIZED"
        if pct <= MILD_HAIRCUT_PCT:
            return "MILD_BOOST_GAP"
        if pct <= MODERATE_HAIRCUT_PCT:
            return "MODERATE_BOOST_GAP"
        return "SEVERE_BOOST_GAP"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "VERIFY_DATA"
        if classification == "FULLY_REALIZED":
            return "TRUST_HEADLINE"
        if classification == "MILD_BOOST_GAP":
            return "MINOR_DISCOUNT"
        if classification == "MODERATE_BOOST_GAP":
            return "USE_BASE_OR_BOOST_TIER"
        # SEVERE_BOOST_GAP
        return "AVOID_OR_LOCK_FOR_BOOST"

    def _flags(
        self,
        classification: str,
        unboosted: bool,
        max_boost_required: bool,
        boost_haircut_pct: float,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "FULLY_REALIZED":
            flags.append("FULLY_REALIZED")
        if classification == "MILD_BOOST_GAP":
            flags.append("MILD_BOOST_GAP")
        if classification == "MODERATE_BOOST_GAP":
            flags.append("MODERATE_BOOST_GAP")
        if classification == "SEVERE_BOOST_GAP":
            flags.append("SEVERE_BOOST_GAP")
        if unboosted:
            flags.append("UNBOOSTED")
        if max_boost_required:
            flags.append("MAX_BOOST_REQUIRED")
        if boost_haircut_pct >= LARGE_HAIRCUT_PCT:
            flags.append("LARGE_BOOST_HAIRCUT")

        return flags

    def _insufficient(self, token: str, classification: str) -> dict:
        return {
            "token": token,
            "headline_apr_pct": 0.0,
            "max_boost_multiplier": None,
            "depositor_boost_multiplier": None,
            "base_apr_pct": None,
            "realized_apr_pct": None,
            "realization_ratio": None,
            "boost_gap_multiplier": None,
            "boost_haircut_pct": None,
            "boost_premium_pct": None,
            "unboosted": False,
            "max_boost_required": False,
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
                "least_boost_gap_vault": None,
                "most_boost_gap_vault": None,
                "avg_score": 0.0,
                "severe_count": 0,
                "position_count": len(results),
            }
        # Higher score = less gap (realized) → highest score is least-gap.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        severe = sum(
            1 for r in results
            if r["classification"] == "SEVERE_BOOST_GAP")
        return {
            "least_boost_gap_vault": by_score[-1]["token"],
            "most_boost_gap_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "severe_count": severe,
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
            # Depositor at max boost → headline fully realized.
            "vault": "CRV-Vault-FullyRealized",
            "headline_apr_pct": 20.0,
            "max_boost_multiplier": 2.5,
            "depositor_boost_multiplier": 2.5,
        },
        {
            # Near-max boost → mild gap (~12% haircut → MILD).
            "vault": "CVX-Vault-Mild",
            "headline_apr_pct": 18.0,
            "max_boost_multiplier": 2.5,
            "depositor_boost_multiplier": 2.2,
        },
        {
            # Partial boost well below max → moderate gap (~36% haircut).
            "vault": "BAL-Vault-Moderate",
            "headline_apr_pct": 16.0,
            "max_boost_multiplier": 2.5,
            "depositor_boost_multiplier": 1.6,
        },
        {
            # Unboosted at max=2.5 → severe gap (60% haircut).
            "vault": "FXS-Vault-Severe",
            "headline_apr_pct": 20.0,
            "max_boost_multiplier": 2.5,
            "depositor_boost_multiplier": 1.0,
        },
        {
            # Partial boost (default unboosted via missing field) at max=1.5.
            "vault": "AURA-Vault-PartialDefault",
            "headline_apr_pct": 12.0,
            "max_boost_multiplier": 1.5,
        },
        {
            # No headline → INSUFFICIENT_DATA.
            "vault": "Mystery-Vault-NoData",
            "headline_apr_pct": 0.0,
            "max_boost_multiplier": 2.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1192 Vault Boost Tier Headline Realization Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultBoostTierHeadlineRealizationAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
