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
  - Алерт при drifting/broken
  - Атомарная запись в data/bee/backtest_live_fit.json

stdlib only. No external dependencies.
"""
# LLM_FORBIDDEN
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DATA_BEE = _PROJECT_ROOT / "data" / "bee"
_DATA = _PROJECT_ROOT / "data"

# Честная стартовая дата трека
HONEST_START = "2026-06-10"


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


def compute_backtest_distribution(regime_label: str) -> Dict:
    """
    Вычисляет ожидаемое распределение APY для текущего режима из бэктеста.

    В реальном BEE: прогоняет боевой allocator на исторических данных режима.
    Сейчас: детерминированные диапазоны (Core stablecoin lending, DeFiLlama 2026-06).

    data_source тег всегда "modeled" пока нет реальных исторических рядов.

    Returns:
        distribution dict с band [lo, hi] для 80% и 95% CI
    """
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

    Args:
        live_history: дневные записи от HONEST_START
        distribution: распределение из compute_backtest_distribution()
        ci_level: уровень CI (0.80 или 0.95)

    Returns:
        fit result с verdict: in_distribution | drifting | broken | insufficient_data
    """
    if not live_history:
        return {
            "verdict": "insufficient_data",
            "pct_live_days_in_band": None,
            "drift_bps": None,
            "live_days_analyzed": 0,
            "note": "Нет live-paper данных для сравнения (трек < 1 дня)",
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
    distribution = compute_backtest_distribution(regime_label)

    fit_80 = check_live_vs_backtest(live_history, distribution, ci_level=0.80)
    fit_95 = check_live_vs_backtest(live_history, distribution, ci_level=0.95)

    result = {
        "version": "1.0",
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
        "data_note": (
            f"Текущие данные: live-paper ряд от {HONEST_START} "
            f"({len(live_history)} дней). "
            "Распределение бэктеста — modeled (не real-data). "
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
