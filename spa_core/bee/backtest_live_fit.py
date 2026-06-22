"""
BEE Ядро B — Backtest ↔ Live Correlation
=========================================
EPIC-9 / ADR-043

LLM_FORBIDDEN: этот модуль не вызывает и не использует никаких LLM-вызовов
Расширение backtest_paper_correlation до явной метрики согласованности.
Сверяет live-paper дневные значения с распределением, предсказанным бэктестом.

Честная дата начала трека: 2026-06-10 (is_demo: false).

Дизайн:
  - PIT: только данные от HONEST_START
  - Детерминированная классификация режима
  - Verdict: in_distribution | drifting | broken | insufficient_data
  - KS-test: сравнивает live APY с теоретическим нормальным распределением
  - Алерт при drifting/broken
  - Атомарная запись в data/bee/backtest_live_fit.json

stdlib only. scipy опционально (для KS p-value).
"""
# LLM_FORBIDDEN
import json
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DATA_BEE = _PROJECT_ROOT / "data" / "bee"
_DATA = _PROJECT_ROOT / "data"

# Честная стартовая дата трека
HONEST_START = "2026-06-10"

# --- Optional scipy for KS p-value ---
try:
    from scipy import stats as _scipy_stats  # type: ignore
    _HAS_SCIPY = True
except ImportError:
    _scipy_stats = None
    _HAS_SCIPY = False


# ---------------------------------------------------------------------------
#  KS-test helpers (stdlib fallback)
# ---------------------------------------------------------------------------

def _normal_cdf(x: float, mu: float, sigma: float) -> float:
    """Normal CDF using math.erf (stdlib). LLM_FORBIDDEN."""
    if sigma <= 0:
        return 0.0 if x < mu else 1.0
    z = (x - mu) / (sigma * math.sqrt(2))
    return 0.5 * (1.0 + math.erf(z))


def _ks_stat_vs_normal(data: List[float], mu: float, sigma: float) -> float:
    """
    Compute KS statistic D = max|F_empirical - F_normal| (stdlib only).
    LLM_FORBIDDEN.
    """
    if not data or sigma <= 0:
        return 0.0
    n = len(data)
    sorted_data = sorted(data)
    ks = 0.0
    for i, x in enumerate(sorted_data):
        f_theor = _normal_cdf(x, mu, sigma)
        d_plus = abs((i + 1) / n - f_theor)
        d_minus = abs(i / n - f_theor)
        ks = max(ks, d_plus, d_minus)
    return ks


def _ks_pvalue_approx(ks_stat: float, n: int) -> float:
    """
    Approximate p-value for the one-sample KS test using Kolmogorov distribution.
    Accurate for n >= 10.  Returns value in [0, 1].
    LLM_FORBIDDEN.
    """
    if ks_stat <= 0 or n <= 0:
        return 1.0
    # Correction factor for finite n (Stephens 1970)
    x = ks_stat * (math.sqrt(n) + 0.12 + 0.11 / math.sqrt(n))
    # Kolmogorov series: P(K > x) = 2 * sum_{k=1}^{inf} (-1)^{k-1} * exp(-2*k^2*x^2)
    pval = 0.0
    for k in range(1, 50):
        sign = (-1) ** (k - 1)
        term = sign * math.exp(-2.0 * k * k * x * x)
        pval += term
        if abs(term) < 1e-10:
            break
    pval = max(0.0, min(1.0, 2.0 * pval))
    return pval


def _run_ks_test(
    live_apys: List[float],
    mu: float,
    sigma: float,
) -> Dict:
    """
    Run KS test of live_apys against normal(mu, sigma).
    Returns dict with ks_statistic, ks_pvalue, ks_verdict.
    LLM_FORBIDDEN.
    """
    if len(live_apys) < 2:
        return {
            "ks_statistic": None,
            "ks_pvalue": None,
            "ks_verdict": "insufficient_data",
        }

    if _HAS_SCIPY and _scipy_stats is not None:
        # Preferred: scipy's kstest (exact p-value via Kolmogorov distribution)
        try:
            ks_stat, ks_pval = _scipy_stats.kstest(live_apys, "norm", args=(mu, sigma))
            ks_stat = float(ks_stat)
            ks_pval = float(ks_pval)
        except Exception:
            ks_stat = _ks_stat_vs_normal(live_apys, mu, sigma)
            ks_pval = _ks_pvalue_approx(ks_stat, len(live_apys))
    else:
        # Stdlib fallback
        ks_stat = _ks_stat_vs_normal(live_apys, mu, sigma)
        ks_pval = _ks_pvalue_approx(ks_stat, len(live_apys))

    ks_verdict = "consistent" if ks_pval > 0.05 else "diverging"
    return {
        "ks_statistic": round(ks_stat, 6),
        "ks_pvalue": round(ks_pval, 6),
        "ks_verdict": ks_verdict,
    }


# ---------------------------------------------------------------------------
#  Data loading
# ---------------------------------------------------------------------------

def load_live_paper_history(
    equity_curve_path: Optional[Path] = None,
    paper_status_path: Optional[Path] = None,
) -> List[Dict]:
    """
    Загружает live-paper дневной ряд от честной даты (2026-06-10).

    Использует equity_curve_daily.json (поле 'daily') как основной источник.
    Fallback: paper_trading_status.json (equity_curve, history, daily_history).
    Фильтрует записи до HONEST_START.

    Returns:
        список дневных записей (dict с полем 'apy_today' или 'current_apy')
    """
    honest_start_dt = datetime.strptime(HONEST_START, "%Y-%m-%d")

    # Основной источник: equity_curve_daily.json
    if equity_curve_path is None:
        equity_curve_path = _DATA / "equity_curve_daily.json"

    if equity_curve_path.exists():
        try:
            raw = json.loads(equity_curve_path.read_text())
            # Поддерживаем форматы: dict с 'daily' или прямой список
            if isinstance(raw, dict):
                daily = raw.get("daily", [])
            elif isinstance(raw, list):
                daily = raw
            else:
                daily = []

            filtered = []
            for entry in daily:
                date_str = entry.get("date", "")
                if date_str:
                    try:
                        entry_dt = datetime.strptime(str(date_str)[:10], "%Y-%m-%d")
                        if entry_dt >= honest_start_dt and not entry.get("is_warmup", False):
                            # Нормализуем APY поле
                            normalized = dict(entry)
                            if "apy_today" in entry and "current_apy" not in entry:
                                normalized["current_apy"] = entry["apy_today"] / 100.0
                            elif "apy_today_pct" in entry:
                                normalized["current_apy"] = entry["apy_today_pct"] / 100.0
                            filtered.append(normalized)
                    except ValueError:
                        pass
            if filtered:
                return filtered
        except Exception:
            pass

    # Fallback: paper_trading_status.json
    if paper_status_path is None:
        paper_status_path = _DATA / "paper_trading_status.json"

    if not paper_status_path.exists():
        return []

    try:
        status = json.loads(paper_status_path.read_text())
        history = (
            status.get("equity_curve", [])
            or status.get("history", [])
            or status.get("daily_history", [])
            or []
        )

        filtered = []
        for entry in history:
            if isinstance(entry, dict):
                date_str = entry.get("date", entry.get("ts", entry.get("timestamp", "")))
                if date_str:
                    try:
                        entry_dt = datetime.strptime(str(date_str)[:10], "%Y-%m-%d")
                        if entry_dt >= honest_start_dt:
                            filtered.append(entry)
                    except ValueError:
                        pass

        return filtered
    except Exception:
        return []


# ---------------------------------------------------------------------------
#  Regime helpers
# ---------------------------------------------------------------------------

def _in_regime(apy: float, regime_label: str) -> bool:
    """Check whether an APY value belongs to the given regime."""
    if regime_label == "normal":
        return 0.04 <= apy < 0.07
    elif regime_label == "high_demand":
        return apy >= 0.07
    elif regime_label == "low_rate":
        return 0.02 <= apy < 0.04
    elif regime_label == "stress":
        return apy < 0.02
    return True  # unknown — include all


def compute_backtest_distribution(
    regime_label: str,
    real_data: Optional[Dict] = None,
    use_real_data: bool = True,
) -> Dict:
    """
    Вычисляет ожидаемое распределение APY для текущего режима из бэктеста.

    Если use_real_data=True (по умолчанию), пробует использовать реальные данные
    из DeFiLlama (через defillama_feed). data_source = "real-data" при успехе,
    "modeled" при fallback.

    Args:
        regime_label: "normal" | "high_demand" | "low_rate" | "stress"
        real_data: предзагруженные данные из fetch_apy_history() (опционально)
        use_real_data: если False — всегда возвращает "modeled"

    Returns:
        distribution dict с band [lo, hi] для 80% и 95% CI, data_source tag
    """
    # LLM_FORBIDDEN
    if use_real_data:
        # Try to get real data
        feed_data = real_data
        if feed_data is None:
            try:
                from spa_core.bee.defillama_feed import fetch_apy_history
                feed_data = fetch_apy_history()
            except Exception:
                feed_data = None

        if feed_data:
            # Aggregate APY series across all pools, filter to regime
            regime_apys: List[float] = []
            for pool_data in feed_data.values():
                if isinstance(pool_data, dict):
                    for entry in pool_data.get("apy_series", []):
                        apy = entry.get("apy")
                        if apy is not None:
                            apy_f = float(apy)
                            if _in_regime(apy_f, regime_label):
                                regime_apys.append(apy_f)

            if len(regime_apys) >= 5:
                n = len(regime_apys)
                mean = sum(regime_apys) / n
                variance = sum((x - mean) ** 2 for x in regime_apys) / n
                std = max(math.sqrt(variance), 1e-6)
                band_lo_80 = round(max(0.0, mean - 1.282 * std), 4)
                band_hi_80 = round(mean + 1.282 * std, 4)
                band_lo_95 = round(max(0.0, mean - 1.96 * std), 4)
                band_hi_95 = round(mean + 1.96 * std, 4)
                # daily bps
                daily_mean_bps = round(mean * 10000.0 / 365.0, 2)
                daily_std_bps = round(std * 10000.0 / 365.0, 2)
                return {
                    "expected_apy_band_80": [band_lo_80, band_hi_80],
                    "expected_apy_band_95": [band_lo_95, band_hi_95],
                    "expected_daily_return_bps_mean": daily_mean_bps,
                    "expected_daily_return_bps_std": daily_std_bps,
                    "data_source": "real-data",
                    "regime_label": regime_label,
                    "n_samples": n,
                    "notes": (
                        f"DeFiLlama historical data, regime={regime_label}, n={n}"
                    ),
                }

    # ---------------------------------------------------------------------------
    #  Modeled fallback
    # ---------------------------------------------------------------------------
    # Core режимы стейбл-лендинга — из исторических данных Aave/Compound/Morpho
    regime_distributions: Dict[str, Dict] = {
        "normal": {
            "expected_apy_band_80": [0.035, 0.065],
            "expected_apy_band_95": [0.025, 0.085],
            "expected_daily_return_bps_mean": 1.25,
            "expected_daily_return_bps_std": 0.45,
            "data_source": "modeled",
            "notes": "Core stablecoin lending, normal market conditions (3.5–6.5% APY)",
        },
        "high_demand": {
            "expected_apy_band_80": [0.055, 0.095],
            "expected_apy_band_95": [0.040, 0.120],
            "expected_daily_return_bps_mean": 2.05,
            "expected_daily_return_bps_std": 0.80,
            "data_source": "modeled",
            "notes": "High utilization regime (>7% APY)",
        },
        "low_rate": {
            "expected_apy_band_80": [0.020, 0.045],
            "expected_apy_band_95": [0.010, 0.060],
            "expected_daily_return_bps_mean": 0.85,
            "expected_daily_return_bps_std": 0.35,
            "data_source": "modeled",
            "notes": "Low rate environment (<4% APY)",
        },
        "stress": {
            "expected_apy_band_80": [0.000, 0.030],
            "expected_apy_band_95": [-0.050, 0.050],
            "expected_daily_return_bps_mean": 0.50,
            "expected_daily_return_bps_std": 2.00,
            "data_source": "modeled",
            "notes": "Stress / crisis regime (<2% APY or negative)",
        },
    }

    dist = dict(regime_distributions.get(regime_label, regime_distributions["normal"]))
    dist["regime_label"] = regime_label
    return dist


def classify_regime(current_apy: float) -> str:
    """
    Детерминированная классификация текущего режима по APY.

    Args:
        current_apy: APY как доля (0.054 = 5.4%)

    Returns:
        "normal" | "high_demand" | "low_rate" | "stress"
    """
    if current_apy >= 0.07:
        return "high_demand"
    elif current_apy >= 0.04:
        return "normal"
    elif current_apy >= 0.02:
        return "low_rate"
    else:
        return "stress"


def check_live_vs_backtest(
    live_history: List[Dict],
    distribution: Dict,
    ci_level: float = 0.80,
) -> Dict:
    """
    Сверяет live-paper значения с распределением бэктеста.

    BEE-002: добавлен KS-test (ks_statistic, ks_pvalue, ks_verdict).
    scipy используется если установлен; иначе stdlib fallback.

    Args:
        live_history: дневные записи от HONEST_START
        distribution: распределение из compute_backtest_distribution()
        ci_level: уровень CI (0.80 или 0.95)

    Returns:
        fit result с verdict: in_distribution | drifting | broken | insufficient_data
        + KS fields: ks_statistic, ks_pvalue, ks_verdict
    """
    # LLM_FORBIDDEN
    _ks_empty = {"ks_statistic": None, "ks_pvalue": None, "ks_verdict": "insufficient_data"}

    if not live_history:
        return {
            "verdict": "insufficient_data",
            "pct_live_days_in_band": None,
            "drift_bps": None,
            "live_days_analyzed": 0,
            "note": "Нет live-paper данных для сравнения (трек < 1 дня)",
            **_ks_empty,
        }

    band_key = "expected_apy_band_80" if ci_level >= 0.79 else "expected_apy_band_95"
    band = distribution.get(band_key, distribution.get("expected_apy_band_80", [0.03, 0.07]))
    band_lo, band_hi = float(band[0]), float(band[1])

    days_in_band = 0
    live_apys: List[float] = []

    for entry in live_history:
        # Извлекаем APY: поддерживаем разные форматы
        apy = (
            entry.get("current_apy")
            or entry.get("apy_today")
            or entry.get("apy")
            or entry.get("annualized_return")
            or entry.get("total_apy")
        )

        if apy is not None:
            try:
                apy_float = float(apy)
                if apy_float > 1.0:  # если в процентах → конвертируем в долях
                    apy_float /= 100.0
                live_apys.append(apy_float)
                if band_lo <= apy_float <= band_hi:
                    days_in_band += 1
            except (ValueError, TypeError):
                pass

    if not live_apys:
        return {
            "verdict": "insufficient_data",
            "pct_live_days_in_band": None,
            "drift_bps": None,
            "live_days_analyzed": len(live_history),
            "note": "Нет извлекаемых APY значений в истории",
            **_ks_empty,
        }

    live_apy_mean = sum(live_apys) / len(live_apys)
    pct_in_band = days_in_band / len(live_apys)

    # Дрейф: разница между live средним и центром бэктест-распределения
    backtest_center = (band_lo + band_hi) / 2.0
    drift_bps = int((live_apy_mean - backtest_center) * 10000)

    # Вердикт
    if pct_in_band >= 0.70:
        verdict = "in_distribution"
    elif pct_in_band >= 0.40:
        verdict = "drifting"
    else:
        verdict = "broken"

    needs_alert = verdict in ("drifting", "broken")

    # --- KS-test (BEE-002) ---
    # Derive normal distribution params from the 80% band
    half_width = (band_hi - band_lo) / 2.0
    backtest_std = half_width / 1.282 if half_width > 0 else 0.01
    ks_result = _run_ks_test(live_apys, backtest_center, backtest_std)

    return {
        "regime_label": distribution.get("regime_label", "unknown"),
        "expected_apy_band": band,
        "ci_level": ci_level,
        "live_apy_observed": round(live_apy_mean, 6),
        "live_apy_min": round(min(live_apys), 6),
        "live_apy_max": round(max(live_apys), 6),
        "pct_live_days_in_band": round(pct_in_band, 4),
        "days_in_band": days_in_band,
        "total_live_days": len(live_apys),
        "drift_bps": drift_bps,
        "verdict": verdict,
        "needs_alert": needs_alert,
        "alert_message": (
            f"BEE АЛЕРТ: live-paper {verdict}. "
            f"APY={live_apy_mean * 100:.2f}%, "
            f"band=[{band_lo * 100:.1f}%, {band_hi * 100:.1f}%], "
            f"только {pct_in_band * 100:.0f}% дней в полосе."
        ) if needs_alert else None,
        "interpretation": {
            "in_distribution": "Модель предсказывает реальность — сильнейший credential.",
            "drifting": "Live систематически расходится с бэктестом — проверить данные или модель.",
            "broken": "Серьёзное расхождение — модель не описывает текущую реальность.",
        }.get(verdict, ""),
        # BEE-002: KS-test fields
        "ks_statistic": ks_result["ks_statistic"],
        "ks_pvalue": ks_result["ks_pvalue"],
        "ks_verdict": ks_result["ks_verdict"],
    }


def run_backtest_live_fit(output_path: Optional[Path] = None) -> Dict:
    """
    Основная функция Ядра B → backtest_live_fit.json.

    LLM_FORBIDDEN.
    Атомарная запись: tmp + os.replace.

    Returns:
        fit result dict
    """
    _DATA_BEE.mkdir(parents=True, exist_ok=True)

    if output_path is None:
        output_path = _DATA_BEE / "backtest_live_fit.json"

    # Загружаем live-paper историю
    live_history = load_live_paper_history()

    # Определяем текущий APY и режим
    current_apy = 0.054  # дефолт 5.4%

    status_path = _DATA / "paper_trading_status.json"
    if status_path.exists():
        try:
            status = json.loads(status_path.read_text())
            raw_apy = status.get("apy_today_pct", status.get("current_apy", None))
            if raw_apy is not None:
                raw_apy = float(raw_apy)
                if raw_apy > 1.0:
                    raw_apy /= 100.0
                current_apy = raw_apy
        except Exception:
            pass

    regime_label = classify_regime(current_apy)

    # Optionally load real DeFiLlama data for distribution
    real_data = None
    try:
        from spa_core.bee.defillama_feed import fetch_apy_history
        real_data = fetch_apy_history()
    except Exception:
        pass

    distribution = compute_backtest_distribution(regime_label, real_data=real_data)

    fit_80 = check_live_vs_backtest(live_history, distribution, ci_level=0.80)
    fit_95 = check_live_vs_backtest(live_history, distribution, ci_level=0.95)

    result = {
        "version": "1.1",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "honest_start_date": HONEST_START,
        "live_days_since_honest_start": len(live_history),
        "current_apy": current_apy,
        "current_regime": regime_label,
        "regime_label": regime_label,
        "distribution": distribution,
        "expected_apy_band": distribution.get("expected_apy_band_80", [0.03, 0.07]),
        "fit_80pct_ci": fit_80,
        "fit_95pct_ci": fit_95,
        "live_apy_observed": fit_80.get("live_apy_observed"),
        "pct_live_days_in_band": fit_80.get("pct_live_days_in_band"),
        "drift_bps": fit_80.get("drift_bps"),
        "verdict": fit_80.get("verdict", "insufficient_data"),
        "needs_alert": fit_80.get("needs_alert", False),
        # BEE-002: KS test summary at top level
        "ks_statistic": fit_80.get("ks_statistic"),
        "ks_pvalue": fit_80.get("ks_pvalue"),
        "ks_verdict": fit_80.get("ks_verdict"),
        "data_note": (
            f"Текущие данные: live-paper ряд от {HONEST_START} "
            f"({len(live_history)} дней). "
            f"Распределение бэктеста — {distribution.get('data_source', 'modeled')}. "
            "Для credential-grade нужны реальные исторические ряды Aave/Compound APY."
        ),
    }

    # Атомарная запись
    payload = json.dumps(result, indent=2)
    tmp_path = str(output_path) + ".tmp"
    with open(tmp_path, "w") as f:
        f.write(payload)
    os.replace(tmp_path, str(output_path))

    return result
