"""
MP-1189: DeFiProtocolVaultAPYCompoundingBasisOverstatementAnalyzer
=================================================================
Advisory/read-only analytics module.

Заголовочный APY обычно выводится из простого/номинального APR при НЕКОТОРОЙ
ПРЕДПОЛАГАЕМОЙ частоте капитализации. Если витрина рекламирует APY при более
богатой каденции капитализации (например ежедневной, 365x), чем хранилище на
самом деле авто-капитализирует (например еженедельно, 52x), то достижимый
эффективный APY НИЖЕ заголовочного → заголовок ЗАВЫШАЕТ доходность.

Угол: "заголовочные 22% APY предполагают ежедневную (365x) капитализацию, но
хранилище фактически капитализирует еженедельно (52x) → достижимый эффективный
APY ниже → дисконтируй заголовок до достижимой базы."

HIGHER score = заголовок близок к достижимому (честная база капитализации).

Отличие от:
  * defi_protocol_auto_compounding_frequency_analyzer /
    defi_protocol_yield_compounding_optimizer — те ОПТИМИЗИРУЮТ каденцию
    капитализации против газа (как часто стоит реинвестировать); ЭТОТ модуль
    изолирует, ДОСТИГАЕТСЯ ли фактически БАЗА КАПИТАЛИЗАЦИИ заголовочного APY
    (доверие к котировке), а не подбирает оптимальную частоту.

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
    "data", "vault_apy_compounding_basis_overstatement_log.json"
)
LOG_CAP = 100

# Default compounding cadences when none / non-positive supplied.
DEFAULT_ADVERTISED_COMPOUNDS = 365.0
DEFAULT_ACTUAL_COMPOUNDS = 52.0

# Cap on compounds per year used to keep the (1+r/n)**n computation finite.
MAX_COMPOUNDS = 365.0 * 24.0  # hourly ceiling

# Classification thresholds on the relative headline gap (gap / achievable).
# rel_gap at/below this → HONEST_BASIS.
HONEST_GAP_RATIO = 0.02
# at/below this → MINOR_OVERSTATEMENT.
MINOR_GAP_RATIO = 0.06
# at/below this → MODERATE_OVERSTATEMENT; above → SEVERE_OVERSTATEMENT.
MODERATE_GAP_RATIO = 0.15

# Reference relative headline gap at which the gap-component of the score → 0.
GAP_CEILING_RATIO = 0.40

# Weights of the two score components (sum 100).
SHORTFALL_WEIGHT = 60.0
GAP_WEIGHT = 40.0

# Flag: actual compounding is sparser than advertised.
SHORTFALL_RATIO_FLOOR = 1.0
# Flag: the quoted headline sits materially above what's achievable (abs pp).
LARGE_HEADLINE_GAP_PCT = 2.0


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


def _eff_apy(apr_pct: float, compounds: float) -> float:
    """
    Effective APY (%) for a simple/nominal APR (%) under `compounds` per year:
        ((1 + apr/n)**n - 1) * 100,  apr as a fraction, n>=1.
    Guards n>=1 and clamps to a finite value.
    """
    n = max(1.0, compounds)
    apr_frac = apr_pct / 100.0
    base = 1.0 + apr_frac / n
    if base <= 0.0 or not math.isfinite(base):
        return apr_pct
    try:
        eff = (base ** n - 1.0) * 100.0
    except (OverflowError, ValueError):
        return apr_pct
    if not math.isfinite(eff):
        return apr_pct
    return eff


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

class DeFiProtocolVaultAPYCompoundingBasisOverstatementAnalyzer:
    """
    Измеряет, насколько честна БАЗА КАПИТАЛИЗАЦИИ заголовочного APY хранилища.
    Заголовочный APY строится из простого base_apr при ПРЕДПОЛАГАЕМОЙ частоте
    (advertised_compounds_per_year); достижимая эффективная доходность считается
    при ФАКТИЧЕСКОЙ частоте авто-капитализации (actual_compounds_per_year). Если
    фактическая каденция реже, достижимый эффективный APY ниже рекламируемого, а
    заголовок завышает доходность. score 0-100 ВЫШЕ = заголовок близок к
    достижимому (честная база). Только совет — фонды не двигает.

    Поля входного словаря позиции:
        vault / token                  : str
        headline_apy_pct               : float; <=0 / non-finite →
                                         INSUFFICIENT_DATA.
        base_apr_pct                   : float (простой/номинальный APR, из
                                         которого строится APY); <=0 / non-finite
                                         → INSUFFICIENT_DATA.
        advertised_compounds_per_year  : float/int (default 365; <=0 → default).
        actual_compounds_per_year      : float/int (default 52; <=0 → default).
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
        headline = _f(p.get("headline_apy_pct"))
        base_apr = _f(p.get("base_apr_pct"))

        # Insufficient data: need a positive, finite headline APY and a positive,
        # finite base APR to judge the compounding basis.
        if headline <= 0 or not math.isfinite(headline):
            return self._insufficient(token)
        if base_apr <= 0 or not math.isfinite(base_apr):
            return self._insufficient(token)

        advertised = _f(p.get("advertised_compounds_per_year"),
                        DEFAULT_ADVERTISED_COMPOUNDS)
        if advertised <= 0 or not math.isfinite(advertised):
            advertised = DEFAULT_ADVERTISED_COMPOUNDS
        advertised = _clamp(advertised, 1.0, MAX_COMPOUNDS)

        actual = _f(p.get("actual_compounds_per_year"),
                    DEFAULT_ACTUAL_COMPOUNDS)
        if actual <= 0 or not math.isfinite(actual):
            actual = DEFAULT_ACTUAL_COMPOUNDS
        actual = _clamp(actual, 1.0, MAX_COMPOUNDS)

        advertised_eff = _eff_apy(base_apr, advertised)
        achievable_eff = _eff_apy(base_apr, actual)
        if not math.isfinite(advertised_eff):
            advertised_eff = base_apr
        if not math.isfinite(achievable_eff):
            achievable_eff = base_apr

        # How much richer-compounding inflates the advertised effective APY over
        # what the actual cadence can deliver.
        overstatement = max(0.0, advertised_eff - achievable_eff)
        # How far the *quoted* headline sits above what's achievable.
        headline_gap = max(0.0, headline - achievable_eff)

        # 1.0 = honest cadence (compounds as advertised); <1 = sparser.
        shortfall_ratio = _safe_div(actual, advertised, 0.0)
        if shortfall_ratio is None or not math.isfinite(shortfall_ratio):
            shortfall_ratio = 0.0
        shortfall_ratio = _clamp(shortfall_ratio, 0.0, 1.0)

        # Relative headline gap vs the achievable basis.
        rel_gap = _safe_div(headline_gap, achievable_eff, 0.0)
        if rel_gap is None or not math.isfinite(rel_gap):
            rel_gap = 0.0
        rel_gap = max(0.0, rel_gap)

        compounding_shortfall = bool(shortfall_ratio < SHORTFALL_RATIO_FLOOR)
        large_headline_gap = bool(headline_gap >= LARGE_HEADLINE_GAP_PCT)

        score = self._score(shortfall_ratio, rel_gap)
        classification = self._classify(rel_gap)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags = self._flags(
            classification, compounding_shortfall, large_headline_gap)

        return {
            "token": token,
            "headline_apy_pct": round(headline, 4),
            "base_apr_pct": round(base_apr, 4),
            "advertised_compounds_per_year": round(advertised, 4),
            "actual_compounds_per_year": round(actual, 4),
            "advertised_effective_apy_pct": round(advertised_eff, 4),
            "achievable_effective_apy_pct": round(achievable_eff, 4),
            "overstatement_pct": round(overstatement, 4),
            "headline_gap_pct": round(headline_gap, 4),
            "relative_headline_gap": round(rel_gap, 4),
            "compounding_shortfall_ratio": round(shortfall_ratio, 4),
            "compounding_shortfall": compounding_shortfall,
            "large_headline_gap": large_headline_gap,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(self, shortfall_ratio: float, rel_gap: float) -> float:
        """
        0-100, HIGHER = honest compounding basis (headline close to achievable).
          shortfall (60) — SHORTFALL_WEIGHT × compounding_shortfall_ratio. A
            vault that compounds exactly as advertised (ratio 1.0) earns the full
            60; one that compounds far sparser earns proportionally less.
          gap (40) — GAP_WEIGHT × (1 - clamp(rel_gap / GAP_CEILING_RATIO, 0, 1)).
            A headline sitting at/below the achievable basis earns the full 40; a
            relative gap at/above the ceiling earns 0.
        """
        ratio = _clamp(shortfall_ratio, 0.0, 1.0)
        gap = max(0.0, rel_gap)
        gap_frac = _clamp(gap / GAP_CEILING_RATIO, 0.0, 1.0)
        total = SHORTFALL_WEIGHT * ratio + GAP_WEIGHT * (1.0 - gap_frac)
        return _clamp(total, 0.0, 100.0)

    def _classify(self, rel_gap: float) -> str:
        gap = max(0.0, rel_gap)
        if gap <= HONEST_GAP_RATIO:
            return "HONEST_BASIS"
        if gap <= MINOR_GAP_RATIO:
            return "MINOR_OVERSTATEMENT"
        if gap <= MODERATE_GAP_RATIO:
            return "MODERATE_OVERSTATEMENT"
        return "SEVERE_OVERSTATEMENT"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "VERIFY_DATA"
        if classification == "HONEST_BASIS":
            return "TRUST_HEADLINE"
        if classification == "MINOR_OVERSTATEMENT":
            return "MINOR_DISCOUNT"
        if classification == "MODERATE_OVERSTATEMENT":
            return "DISCOUNT_TO_ACHIEVABLE"
        # SEVERE_OVERSTATEMENT
        return "USE_ACHIEVABLE_BASIS"

    def _flags(
        self,
        classification: str,
        compounding_shortfall: bool,
        large_headline_gap: bool,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "HONEST_BASIS":
            flags.append("HONEST_BASIS")
        if classification == "MINOR_OVERSTATEMENT":
            flags.append("MINOR_OVERSTATEMENT")
        if classification == "MODERATE_OVERSTATEMENT":
            flags.append("MODERATE_OVERSTATEMENT")
        if classification == "SEVERE_OVERSTATEMENT":
            flags.append("SEVERE_OVERSTATEMENT")
        if compounding_shortfall:
            flags.append("COMPOUNDING_SHORTFALL")
        if large_headline_gap:
            flags.append("LARGE_HEADLINE_GAP")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "headline_apy_pct": 0.0,
            "base_apr_pct": 0.0,
            "advertised_compounds_per_year": round(
                DEFAULT_ADVERTISED_COMPOUNDS, 4),
            "actual_compounds_per_year": round(DEFAULT_ACTUAL_COMPOUNDS, 4),
            "advertised_effective_apy_pct": None,
            "achievable_effective_apy_pct": None,
            "overstatement_pct": None,
            "headline_gap_pct": None,
            "relative_headline_gap": None,
            "compounding_shortfall_ratio": None,
            "compounding_shortfall": False,
            "large_headline_gap": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "VERIFY_DATA",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results
                  if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "most_honest_vault": None,
                "most_overstated_vault": None,
                "avg_score": 0.0,
                "severe_overstatement_count": 0,
                "position_count": len(results),
            }
        # Higher score = more honest → highest score is the most honest.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        severe = sum(
            1 for r in results
            if r["classification"] == "SEVERE_OVERSTATEMENT")
        return {
            "most_honest_vault": by_score[-1]["token"],
            "most_overstated_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "severe_overstatement_count": severe,
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
            # Honest: advertised cadence equals actual cadence → headline is the
            # truly achievable effective APY → near-zero gap.
            "vault": "USDC-Vault-Honest",
            "headline_apy_pct": 5.1267,
            "base_apr_pct": 5.0,
            "advertised_compounds_per_year": 365.0,
            "actual_compounds_per_year": 365.0,
        },
        {
            # Headline quotes the daily-compounded number but the vault only
            # compounds annually → a minor relative gap above achievable.
            "vault": "DAI-Vault-MinorOver",
            "headline_apy_pct": 5.1267,
            "base_apr_pct": 5.0,
            "advertised_compounds_per_year": 365.0,
            "actual_compounds_per_year": 1.0,
        },
        {
            "vault": "ETH-Vault-ModerateOver",
            "headline_apy_pct": 16.1798,
            "base_apr_pct": 15.0,
            "advertised_compounds_per_year": 365.0,
            "actual_compounds_per_year": 1.0,
        },
        {
            "vault": "ARB-Vault-SevereOver",
            "headline_apy_pct": 34.9692,
            "base_apr_pct": 30.0,
            "advertised_compounds_per_year": 365.0,
            "actual_compounds_per_year": 1.0,
        },
        {
            "vault": "OP-Vault-SevereOver2",
            "headline_apy_pct": 64.8157,
            "base_apr_pct": 50.0,
            "advertised_compounds_per_year": 365.0,
            "actual_compounds_per_year": 4.0,
        },
        {
            "vault": "Mystery-Vault-NoData",
            "headline_apy_pct": 0.0,
            "base_apr_pct": 0.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1189 Vault APY Compounding Basis Overstatement Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultAPYCompoundingBasisOverstatementAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
