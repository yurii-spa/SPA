"""
MP-1190: DeFiProtocolVaultAPRLookbackWindowSelectionBiasAnalyzer
================================================================
Advisory/read-only analytics module.

Заголовочный APR может быть подобран («cherry-picked») из самого ВЫГОДНОГО
трейлингового окна. Имея показания APR по нескольким стандартным окнам
обозрения (например 7d/30d/90d), если заголовок совпадает с самым высоким/
коротким окном, а нейтральная более длинная база заметно ниже, заголовок
отражает оптимизм ВЫБОРА ОКНА, а не устойчивую доходность.

Угол: "заголовочные 19% равны 7d-окну, но 30d=12%, а 90d=9% → заголовок
выбирает самое горячее окно → дисконтируй к более длинной базе."

HIGHER score = заголовок согласуется с нейтральной/более длинной базой (нет
смещения выбора окна).

Отличие от:
  * defi_protocol_vault_apr_annualization_basis_risk_analyzer — там риск
    ЭКСТРАПОЛЯЦИИ из ДЛИНЫ одного короткого окна (короткий период годуется);
    ЭТОТ модуль о том, КАКОЕ из нескольких окон было ВЫБРАНО для заголовка.
  * defi_protocol_vault_trailing_window_boost_backdating_analyzer — там
    ИСТЁКШИЙ буст всё ещё сидит внутри трейлингового среднего; ЭТОТ модуль
    изолирует именно ВЫБОР окна среди нескольких, а не остаточный буст.

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
    "data", "vault_apr_lookback_window_selection_bias_log.json"
)
LOG_CAP = 100

# Minimum number of valid windows needed to judge selection bias.
MIN_WINDOWS = 2

# Tolerance (pp) for deciding the headline "matches" the hottest window.
HOTTEST_MATCH_TOLERANCE_PCT = 0.5

# Classification thresholds on headline_vs_baseline (% above the long baseline).
# pct at/below this → NEUTRAL_BASIS.
NEUTRAL_BIAS_PCT = 5.0
# at/below this → MILD_SELECTION.
MILD_BIAS_PCT = 20.0
# at/below this → MODERATE_SELECTION; above → STRONG_SELECTION.
MODERATE_BIAS_PCT = 50.0

# Reference headline_vs_baseline (%) at which the agreement-component → 0.
BIAS_CEILING_PCT = 100.0

# Weights of the two score components (sum 100).
AGREEMENT_WEIGHT = 60.0
HOTTEST_WEIGHT = 40.0

# A baseline is "materially lower" when the headline exceeds it by this (%).
MATERIAL_BASELINE_GAP_PCT = NEUTRAL_BIAS_PCT

# Flag: window APRs span a wide range (max-min, pp).
WIDE_WINDOW_SPREAD_PCT = 5.0


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


def _is_window_key(key) -> bool:
    """True for a positive integer-ish window-day key (excludes bool)."""
    if isinstance(key, bool):
        return False
    if isinstance(key, int):
        return key > 0
    if isinstance(key, float):
        return math.isfinite(key) and key > 0
    if isinstance(key, str):
        try:
            return int(key) > 0
        except (TypeError, ValueError):
            return False
    return False


def _clean_windows(raw) -> Dict[int, float]:
    """
    Sanitize a window->apr mapping: keep positive integer keys mapping to
    finite, non-negative numeric APRs. Drop None/bool/non-numeric/negative
    values and non-positive / non-integer keys.
    """
    cleaned: Dict[int, float] = {}
    if not isinstance(raw, dict):
        return cleaned
    for k, v in raw.items():
        if not _is_window_key(k):
            continue
        if not _is_number(v):
            continue
        if v < 0:
            continue
        try:
            ik = int(k)
        except (TypeError, ValueError):
            continue
        cleaned[ik] = float(v)
    return cleaned


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

class DeFiProtocolVaultAPRLookbackWindowSelectionBiasAnalyzer:
    """
    Измеряет, отражает ли заголовочный APR хранилища ВЫБОР самого выгодного
    трейлингового окна, а не устойчивую доходность. Имея APR по нескольким
    окнам, нейтральная база — APR самого ДЛИННОГО доступного окна. Если
    заголовок сидит у самого горячего экстремума, а длинная база заметно ниже,
    заголовок смещён выбором окна. score 0-100 ВЫШЕ = заголовок согласуется с
    нейтральной/длинной базой (нет смещения). Только совет — фонды не двигает.

    Поля входного словаря позиции:
        vault / token       : str
        headline_apr_pct    : float; <=0 / non-finite → INSUFFICIENT_DATA.
        window_aprs         : dict window-days(int>0) -> apr_pct(float).
                              None/bool/нечисловые/отрицательные значения и
                              неположительные ключи отфильтровываются; нужно
                              >=2 валидных окна, иначе INSUFFICIENT_WINDOWS
                              (score=0, исключается из агрегата как
                              INSUFFICIENT_DATA).
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
        # to judge against.
        if headline <= 0 or not math.isfinite(headline):
            return self._insufficient(token, "INSUFFICIENT_DATA")

        windows = _clean_windows(p.get("window_aprs"))
        if len(windows) < MIN_WINDOWS:
            return self._insufficient(token, "INSUFFICIENT_WINDOWS")

        keys = sorted(windows.keys())
        longest_key = keys[-1]
        shortest_key = keys[0]
        baseline = windows[longest_key]          # neutral long baseline
        shortest_window_apr = windows[shortest_key]
        apr_values = list(windows.values())
        max_apr = max(apr_values)
        min_apr = min(apr_values)
        window_spread = max(0.0, max_apr - min_apr)

        # How far the headline sits above the neutral baseline (%).
        excess = max(0.0, headline - baseline)
        headline_vs_baseline = _safe_div(excess, baseline, 0.0)
        if headline_vs_baseline is None or not math.isfinite(
                headline_vs_baseline):
            headline_vs_baseline = 0.0
        headline_vs_baseline_pct = max(0.0, headline_vs_baseline * 100.0)

        # Does the headline coincide with the hottest window?
        headline_matches_hottest = bool(
            abs(headline - max_apr) <= HOTTEST_MATCH_TOLERANCE_PCT)

        # Where does the headline sit between baseline and the hottest extreme?
        denom = max_apr - baseline
        if denom > 0:
            selection_bias_ratio = _clamp(
                _safe_div(excess, denom, 0.0), 0.0, 1.0)
            if selection_bias_ratio is None or not math.isfinite(
                    selection_bias_ratio):
                selection_bias_ratio = 0.0
        else:
            selection_bias_ratio = 0.0

        baseline_materially_lower = bool(
            headline_vs_baseline_pct >= MATERIAL_BASELINE_GAP_PCT)
        wide_window_spread = bool(window_spread >= WIDE_WINDOW_SPREAD_PCT)

        score = self._score(
            headline_vs_baseline_pct, headline_matches_hottest,
            baseline_materially_lower)
        classification = self._classify(headline_vs_baseline_pct)
        grade = _grade_from_score(score)
        recommendation = self._recommend(
            classification, headline_matches_hottest)
        flags = self._flags(
            classification, headline_matches_hottest, wide_window_spread)

        return {
            "token": token,
            "headline_apr_pct": round(headline, 4),
            "window_count": len(windows),
            "baseline_window_days": longest_key,
            "shortest_window_days": shortest_key,
            "baseline_apr_pct": round(baseline, 4),
            "shortest_window_apr_pct": round(shortest_window_apr, 4),
            "max_window_apr_pct": round(max_apr, 4),
            "min_window_apr_pct": round(min_apr, 4),
            "window_spread_pct": round(window_spread, 4),
            "headline_vs_baseline_pct": round(headline_vs_baseline_pct, 4),
            "selection_bias_ratio": round(selection_bias_ratio, 4),
            "headline_matches_hottest": headline_matches_hottest,
            "baseline_materially_lower": baseline_materially_lower,
            "wide_window_spread": wide_window_spread,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        headline_vs_baseline_pct: float,
        headline_matches_hottest: bool,
        baseline_materially_lower: bool,
    ) -> float:
        """
        0-100, HIGHER = unbiased (headline consistent with the long baseline).
          agreement (60) — AGREEMENT_WEIGHT × (1 - clamp(headline_vs_baseline /
            BIAS_CEILING, 0, 1)). A headline at/below the baseline earns the
            full 60; one sitting at/above the ceiling above baseline earns 0.
          hottest-penalty (40) — HOTTEST_WEIGHT awarded in full UNLESS the
            headline matches the hottest window AND the baseline is materially
            lower (a cherry-picked top window), in which case it earns 0.
        """
        agree_frac = _clamp(
            headline_vs_baseline_pct / BIAS_CEILING_PCT, 0.0, 1.0)
        agreement = AGREEMENT_WEIGHT * (1.0 - agree_frac)
        if headline_matches_hottest and baseline_materially_lower:
            hottest = 0.0
        else:
            hottest = HOTTEST_WEIGHT
        return _clamp(agreement + hottest, 0.0, 100.0)

    def _classify(self, headline_vs_baseline_pct: float) -> str:
        pct = max(0.0, headline_vs_baseline_pct)
        if pct <= NEUTRAL_BIAS_PCT:
            return "NEUTRAL_BASIS"
        if pct <= MILD_BIAS_PCT:
            return "MILD_SELECTION"
        if pct <= MODERATE_BIAS_PCT:
            return "MODERATE_SELECTION"
        return "STRONG_SELECTION"

    def _recommend(
        self,
        classification: str,
        headline_matches_hottest: bool,
    ) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "VERIFY_DATA"
        if classification == "INSUFFICIENT_WINDOWS":
            return "VERIFY_DATA"
        # Override: a headline pinned to the hottest window at MODERATE+ bias is
        # a cherry-pick → avoid or verify.
        if headline_matches_hottest and classification in (
                "MODERATE_SELECTION", "STRONG_SELECTION"):
            return "AVOID_OR_VERIFY"
        if classification == "NEUTRAL_BASIS":
            return "TRUST_HEADLINE"
        if classification == "MILD_SELECTION":
            return "MINOR_DISCOUNT"
        if classification == "MODERATE_SELECTION":
            return "USE_LONGER_BASELINE"
        # STRONG_SELECTION
        return "AVOID_OR_VERIFY"

    def _flags(
        self,
        classification: str,
        headline_matches_hottest: bool,
        wide_window_spread: bool,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "NEUTRAL_BASIS":
            flags.append("NEUTRAL_BASIS")
        if classification == "MILD_SELECTION":
            flags.append("MILD_SELECTION")
        if classification == "MODERATE_SELECTION":
            flags.append("MODERATE_SELECTION")
        if classification == "STRONG_SELECTION":
            flags.append("STRONG_SELECTION")
        if headline_matches_hottest:
            flags.append("HEADLINE_AT_HOTTEST")
        if wide_window_spread:
            flags.append("WIDE_WINDOW_SPREAD")

        return flags

    def _insufficient(self, token: str, classification: str) -> dict:
        return {
            "token": token,
            "headline_apr_pct": 0.0,
            "window_count": 0,
            "baseline_window_days": None,
            "shortest_window_days": None,
            "baseline_apr_pct": None,
            "shortest_window_apr_pct": None,
            "max_window_apr_pct": None,
            "min_window_apr_pct": None,
            "window_spread_pct": None,
            "headline_vs_baseline_pct": None,
            "selection_bias_ratio": None,
            "headline_matches_hottest": False,
            "baseline_materially_lower": False,
            "wide_window_spread": False,
            "score": 0.0,
            "classification": classification,
            "recommendation": "VERIFY_DATA",
            "grade": "F",
            "flags": [classification],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results
                  if r["classification"] not in (
                      "INSUFFICIENT_DATA", "INSUFFICIENT_WINDOWS")]
        if not scored:
            return {
                "least_biased_vault": None,
                "most_biased_vault": None,
                "avg_score": 0.0,
                "strong_selection_count": 0,
                "position_count": len(results),
            }
        # Higher score = less biased → highest score is the least biased.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        strong = sum(
            1 for r in results
            if r["classification"] == "STRONG_SELECTION")
        return {
            "least_biased_vault": by_score[-1]["token"],
            "most_biased_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "strong_selection_count": strong,
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
            # Headline ~ long baseline; windows flat → no selection bias.
            "vault": "USDC-Vault-Neutral",
            "headline_apr_pct": 9.0,
            "window_aprs": {7: 9.2, 30: 9.0, 90: 9.0},
        },
        {
            # Headline slightly above the 90d baseline → mild selection.
            "vault": "DAI-Vault-Mild",
            "headline_apr_pct": 11.0,
            "window_aprs": {7: 11.0, 30: 10.0, 90: 10.0},
        },
        {
            # Headline = hot 7d, 90d baseline ~30% lower → moderate selection.
            "vault": "ETH-Vault-Moderate",
            "headline_apr_pct": 13.0,
            "window_aprs": {7: 13.0, 30: 11.0, 90: 10.0},
        },
        {
            # Headline = blazing 7d, 90d baseline less than half → strong.
            "vault": "ARB-Vault-Strong",
            "headline_apr_pct": 19.0,
            "window_aprs": {7: 19.0, 30: 12.0, 90: 9.0},
        },
        {
            # Only one valid window → INSUFFICIENT_WINDOWS.
            "vault": "OP-Vault-OneWindow",
            "headline_apr_pct": 14.0,
            "window_aprs": {30: 14.0},
        },
        {
            # No headline → INSUFFICIENT_DATA.
            "vault": "Mystery-Vault-NoData",
            "headline_apr_pct": 0.0,
            "window_aprs": {7: 5.0, 30: 4.0},
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1190 Vault APR Lookback Window Selection Bias Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultAPRLookbackWindowSelectionBiasAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
