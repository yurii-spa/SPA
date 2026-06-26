#!/usr/bin/env python3
"""SPA публичный ежемесячный tear-sheet (MP-501, SPA-V427) — offline-ядро.

Read-only / advisory генератор tear-sheet поверх СУЩЕСТВУЮЩИХ данных трека
(data/*.json) и существующих модулей. «Основа воронки доверия»: net APY,
Sharpe/Sortino/PSR, drawdown, volatility, exposure, инциденты, Merkle roots
Proof-of-Track (MP-406) — всё за один календарный месяц (UTC).
Публикация наружу (GitHub Pages — UA-004) НЕ выполняется: «автопубликация»
здесь = детерминированная генерация готовых к публикации артефактов.

Источники (все опциональны; отсутствие/битость → честные None/«нет данных»
+ запись в notes, никогда не raise, ничего не выдумываем):
* ``data/equity_curve_daily.json``        — дневные бары equity; поля в
  ПРОЦЕНТАХ (``daily_return_pct``: 0.0087 == 0.0087%), как пишет cycle_runner
  и как читают capital_ladder.py / risk_metrics.py.
* ``data/paper_trading_status.json``      — days_running, paper_start_date.
* ``data/current_positions.json``         — exposure по протоколам (USD).
* ``data/adapter_orchestrator_status.json`` — тиры протоколов (T1/T2/...).
* ``data/capital_ladder_status.json``     — текущая ступень L0–L5 (MP-505).
* ``data/proof_of_track_anchors.json``    — Merkle roots месяца (MP-406),
  включаются в tear-sheet для verifiability (published true/false честно).
* ``data/golive_status.json``             — вердикт anti-demo гейта MP-006.
* ``data/trades.json``                    — число сделок за месяц (опционально).

Метрики месяца (по дневным return'ам внутри календарного месяца; глобальный
seed-бар кривой — первый бар с daily_return_pct=0.0 — исключается, как в
risk_metrics._daily_returns):
* net return за месяц (компаундинг дневных), annualized net APY (365 дней —
  конвенция risk_metrics.ANNUALIZATION_DAYS);
* Sharpe / Sortino / volatility / win-rate / max drawdown — переиспользуются
  ИМПОРТОМ чистой ``risk_metrics.compute_risk_metrics`` поверх синтетической
  месячной кривой (seed-бар + бары месяца с внутримесячным drawdown);
  нулевая дисперсия / нехватка данных → честный None (конвенция risk_metrics);
* PSR (Probabilistic Sharpe Ratio, Bailey & López de Prado 2012) — реализован
  здесь через ``math.erf`` (нормальная CDF) с поправкой на skew/kurtosis;
  ряд короче ``PSR_MIN_RETURNS`` (10 баров) / плоский ряд / V<=0 → честный
  None + note, ничего не выдумывается;
* инциденты ≥1% AUM — переиспользуется ИМПОРТОМ чистая
  ``capital_ladder.detect_incidents`` (модуль capital_ladder НЕ модифицируется).

Структура doc (build_tear_sheet): секции ``meta`` (generated_at, period,
is_demo, advisory_only, source_files, track, disclaimer), ``performance``,
``risk``, ``exposure``, ``incidents``, ``proof_of_track``, ``capital_ladder``,
``notes``.

Выходы (атомарная запись tmp + os.replace, паттерн capital_ladder /
proof_of_track):
* ``data/tear_sheet_latest.json``       — машиночитаемый последний tear-sheet
  + история прогонов (``history``) с ротацией ≤500;
* ``reports/tear_sheet_<YYYY-MM>.md``   — человекочитаемый markdown (один
  файл на месяц; отсутствующие метрики — «н/д», без выдуманных цифр).

Идемпотентность (задокументированный выбор): ``generated_at`` обновляется
ТОЛЬКО при изменении контента. Контент сравнивается отпечатком
:func:`content_fingerprint` (весь doc без волатильных ``meta.generated_at`` /
``history``); если контент не изменился — ни JSON, ни markdown НЕ
перезаписываются → повторный прогон того же месяца с теми же данными
байт-в-байт не меняет файлы, history не растёт.

CLI::

    python3 -m spa_core.reporting.tear_sheet --check            # по умолчанию
    python3 -m spa_core.reporting.tear_sheet --run
    python3 -m spa_core.reporting.tear_sheet --run --month 2026-06
    python3 -m spa_core.reporting.tear_sheet --check --data-dir d --reports-dir r

Офлайн, без сети, exit 0, без трейсбеков даже на пустых данных; мусорный
``--month`` → понятная ошибка в stderr, exit 0.

Scope / safety: LLM FORBIDDEN — детерминированная логика, pure stdlib
(json/math/statistics/datetime/pathlib/argparse/logging/tempfile/os), без
requests/web3/pandas/numpy. STRICTLY READ-ONLY (SPA-BL-011): никогда не
трогает execution path, risk policy, кошельки, money-moving код — только
читает data/*.json и пишет собственные отчётные артефакты.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import statistics
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Tuple

from spa_core.governance.capital_ladder import (
    INCIDENT_THRESHOLD_PCT,
    detect_incidents,
)
from spa_core.paper_trading.risk_metrics import (
    ANNUALIZATION_DAYS,
    compute_risk_metrics,
)
from spa_core.utils.atomic import atomic_save_text

# Re-export: TearSheetGenerator (Tier-1 fund-quality backtest HTML, MP-1356)
# lives in tear_sheet_html.py since the P3-15 dedup split. Re-exported here so
# existing callers `from spa_core.reporting.tear_sheet import TearSheetGenerator`
# keep working byte-for-byte (the HTML/JSON output is unchanged).
from spa_core.reporting.tear_sheet_html import TearSheetGenerator  # noqa: F401

log = logging.getLogger("spa.reporting.tear_sheet")

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"
_DEFAULT_REPORTS_DIR = _REPO_ROOT / "reports"

SCHEMA_VERSION = 1
SOURCE_NAME = "tear_sheet"

STATUS_FILENAME = "tear_sheet_latest.json"
MD_FILENAME_TPL = "tear_sheet_{month}.md"
HISTORY_MAX = 500  # ротация истории прогонов (паттерн capital_ladder / MP-406)

EQUITY_FILENAME = "equity_curve_daily.json"
PT_STATUS_FILENAME = "paper_trading_status.json"
POSITIONS_FILENAME = "current_positions.json"
ORCH_STATUS_FILENAME = "adapter_orchestrator_status.json"
LADDER_STATUS_FILENAME = "capital_ladder_status.json"
ANCHORS_FILENAME = "proof_of_track_anchors.json"
GOLIVE_STATUS_FILENAME = "golive_status.json"
TRADES_FILENAME = "trades.json"

SOURCE_FILES = (
    EQUITY_FILENAME,
    PT_STATUS_FILENAME,
    POSITIONS_FILENAME,
    ORCH_STATUS_FILENAME,
    LADDER_STATUS_FILENAME,
    ANCHORS_FILENAME,
    GOLIVE_STATUS_FILENAME,
    TRADES_FILENAME,
)

# Минимум дневных return'ов для PSR: короче — честный None + note
# (оценка моментов на <10 точках статистически бессмысленна).
PSR_MIN_RETURNS = 10

# Benchmark per-period Sharpe SR* для PSR: 0.0 — «есть ли edge вообще»
# (та же конвенция, что в probabilistic_sharpe.py / SPA-V404).
DEFAULT_BENCHMARK_SR = 0.0

DISCLAIMER = (
    "Paper track (read-only simulation), NOT investment advice. "
    "Все цифры — виртуальный paper-трек SPA без реальных средств; "
    "прошлая доходность не гарантирует будущую."
)

_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


# ─── Толерантный IO (паттерн capital_ladder / proof_of_track) ────────────────


def _read_json(path: Path) -> Any:
    """Читает JSON терпимо: нет файла / битый файл → None, никогда не raise."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _atomic_write_text(path: Path, text: str) -> None:
    """Атомарная запись текста через общий :func:`atomic_save_text`.

    Делегирует в ``spa_core.utils.atomic`` (tmpfile в той же папке + fsync +
    os.replace) — байт-в-байт тот же результат на диске, без дублирования
    паттерна. Markdown/JSON tear-sheet'а — однонодный том, cross-device не
    участвует, поэтому os.replace корректен.
    """
    atomic_save_text(text, str(path))


def _atomic_write_json(path: Path, obj: Any) -> None:
    """Атомарная запись JSON через :func:`_atomic_write_text`."""
    _atomic_write_text(
        path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
    )


def _num(value: Any) -> Optional[float]:
    """Число или None (bool — не число); NaN/inf — не данные."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)):
        return None
    return float(value)


def _valid_date(value: Any) -> bool:
    try:
        datetime.strptime(str(value), "%Y-%m-%d")
        return True
    except ValueError:
        return False


# ─── Месяц / фильтрация баров (чистые функции) ───────────────────────────────


def validate_month(month: Any) -> str:
    """Валидирует строку месяца ``YYYY-MM``; мусор → ValueError."""
    s = str(month)
    if not _MONTH_RE.match(s):
        raise ValueError(f"invalid month {month!r}: expected YYYY-MM")
    try:
        datetime.strptime(s, "%Y-%m")
    except ValueError as exc:
        raise ValueError(f"invalid month {month!r}: {exc}") from None
    return s


def current_month_utc(now: Optional[datetime] = None) -> str:
    """Текущий календарный месяц в UTC как ``YYYY-MM``."""
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y-%m")


def filter_month_bars(daily: Any, month: str) -> List[dict]:
    """Валидные бары равного месяца, отсортированные по дате.

    Чистая функция: мусорные элементы (не dict, битая/отсутствующая дата)
    молча пропускаются — паттерн detect_incidents.
    """
    out: List[dict] = []
    if not isinstance(daily, list):
        return out
    for bar in daily:
        if not isinstance(bar, dict):
            continue
        date = bar.get("date")
        if not _valid_date(date) or not str(date).startswith(month + "-"):
            continue
        out.append(bar)
    out.sort(key=lambda b: str(b.get("date")))
    return out


def monthly_return_series(daily: Any, month: str) -> List[Tuple[str, float]]:
    """Дневные return'ы (%) месяца как [(date, ret), ...].

    Глобальный seed-бар кривой (самый первый валидный бар — его
    ``daily_return_pct`` это 0.0-заглушка без прошлого close) исключается,
    в точности как ``risk_metrics._daily_returns`` исключает ``curve[0]``.
    Нечисловые return'ы молча пропускаются.
    """
    if not isinstance(daily, list):
        return []
    valid = [
        b for b in daily
        if isinstance(b, dict) and _valid_date(b.get("date"))
    ]
    valid.sort(key=lambda b: str(b.get("date")))
    seed_date = str(valid[0].get("date")) if valid else None
    series: List[Tuple[str, float]] = []
    for bar in valid:
        date = str(bar.get("date"))
        if not date.startswith(month + "-") or date == seed_date:
            continue
        ret = _num(bar.get("daily_return_pct"))
        if ret is None:
            continue
        series.append((date, ret))
    return series


# ─── Чистая математика месяца ────────────────────────────────────────────────


def compound_return_pct(returns: List[float]) -> Optional[float]:
    """Компаундинг дневных return'ов (%) в суммарный return месяца (%).

    Пустой ряд → None (нет данных — нет цифры). Капитал не уходит ниже −100%.
    """
    if not returns:
        return None
    growth = 1.0
    for r in returns:
        growth *= (1.0 + r / 100.0)
    if growth <= 0:
        return -100.0
    return (growth - 1.0) * 100.0


def max_drawdown_from_returns(returns: List[float]) -> float:
    """Максимальная просадка (%) компаундированного пути return'ов; <= 0."""
    growth = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in returns:
        growth *= (1.0 + r / 100.0)
        peak = max(peak, growth)
        if peak > 0:
            dd = (growth / peak - 1.0) * 100.0
            max_dd = min(max_dd, dd)
    return max_dd


def _norm_cdf(x: float) -> float:
    """Стандартная нормальная CDF Φ(x) через math.erf."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def compute_psr(
    returns: List[float],
    benchmark_sr: float = DEFAULT_BENCHMARK_SR,
    min_returns: int = PSR_MIN_RETURNS,
) -> dict:
    """Probabilistic Sharpe Ratio (Bailey & López de Prado 2012).

    PSR(SR*) = Φ[(SR − SR*)·√(n−1) / √V], V = 1 − γ3·SR + (γ4−1)/4·SR²,
    где γ3 — population skewness, γ4 — non-excess kurtosis. Честные None:
    * ряд короче ``min_returns`` (по умолчанию 10 баров) → psr=None + note;
    * плоский ряд (stdev=0) / V<=0 → psr=None + note.
    Никогда не raise; ничего не выдумывается.
    """
    sr_star = float(benchmark_sr)
    base = {
        "psr": None,
        "sharpe_daily": None,
        "skewness": None,
        "excess_kurtosis": None,
        "variance_term": None,
        "num_returns": len(returns) if isinstance(returns, list) else 0,
        "min_returns": int(min_returns),
        "benchmark_sharpe_daily": round(sr_star, 6),
        "note": None,
    }
    if not isinstance(returns, list):
        base["note"] = "invalid input — PSR not computed"
        return base
    vals = [v for v in (_num(r) for r in returns) if v is not None]
    n = len(vals)
    base["num_returns"] = n
    if n < int(min_returns):
        base["note"] = (
            f"insufficient data: {n} return(s) < min {int(min_returns)} — "
            "PSR not computed"
        )
        return base
    mean = statistics.fmean(vals)
    stdev = statistics.pstdev(vals)
    if stdev == 0:
        base["note"] = "zero variance series — PSR undefined"
        return base
    sr = mean / stdev
    m3 = sum((v - mean) ** 3 for v in vals) / n
    m4 = sum((v - mean) ** 4 for v in vals) / n
    skew = m3 / (stdev ** 3)
    exkurt = m4 / (stdev ** 4) - 3.0
    # V с поправкой на высшие моменты; γ4 = exkurt + 3 → (γ4−1)/4 = (exkurt+2)/4
    v_term = 1.0 - skew * sr + ((exkurt + 2.0) / 4.0) * sr * sr
    base.update(
        sharpe_daily=round(sr, 6),
        skewness=round(skew, 6),
        excess_kurtosis=round(exkurt, 6),
        variance_term=round(v_term, 6),
    )
    if v_term <= 0.0:
        base["note"] = "estimator variance term <= 0 — PSR undefined"
        return base  # дисперсия оценщика не определена → честный None
    z = (sr - sr_star) * math.sqrt(n - 1) / math.sqrt(v_term)
    base["psr"] = round(_norm_cdf(z), 6)
    return base


def _risk_metrics_for_month(series: List[Tuple[str, float]]) -> Optional[dict]:
    """Sharpe/Sortino/vol/win-rate/maxDD месяца через risk_metrics ИМПОРТОМ.

    Строит синтетическую месячную кривую: seed-бар (0.0, как в реальной
    кривой cycle_runner) + бары месяца с внутримесячным drawdown — так
    ``compute_risk_metrics`` (его конвенция: curve[1:] — реальные return'ы)
    переиспользуется без модификации и без дублирования формул.
    """
    if not series:
        return None
    curve: List[dict] = [
        {"date": "seed", "daily_return_pct": 0.0, "drawdown_pct": 0.0}
    ]
    growth = 1.0
    peak = 1.0
    for date, ret in series:
        growth *= (1.0 + ret / 100.0)
        peak = max(peak, growth)
        dd = (growth / peak - 1.0) * 100.0 if peak > 0 else 0.0
        curve.append(
            {"date": date, "daily_return_pct": ret, "drawdown_pct": dd}
        )
    return compute_risk_metrics(curve)


# ─── Exposure (чистая) ───────────────────────────────────────────────────────


def build_exposure(positions_doc: Any, orch_doc: Any) -> dict:
    """Снимок exposure: доли по протоколам + агрегация по тирам + cash.

    Чистая функция от содержимого current_positions.json и
    adapter_orchestrator_status.json. Битые/отсутствующие входы →
    ``{"available": False}``; протокол без тира в оркестраторе → "unknown".
    """
    unavailable = {"available": False, "as_of": None, "capital_usd": None,
                   "deployed_usd": None, "cash_pct": None,
                   "by_protocol": {}, "by_tier": {}}
    if not isinstance(positions_doc, dict):
        return unavailable
    raw = positions_doc.get("positions")
    positions: dict = {}
    if isinstance(raw, dict):
        for proto, usd in raw.items():
            val = _num(usd)
            if val is not None and val >= 0:
                positions[str(proto)] = val
    cash = _num(positions_doc.get("cash_usd"))
    if not positions and cash is None:
        return unavailable
    deployed = sum(positions.values())
    capital = _num(positions_doc.get("capital_usd"))
    total = capital if (capital is not None and capital > 0) else (
        deployed + (cash or 0.0)
    )
    if total <= 0:
        return unavailable

    tier_map: dict = {}
    if isinstance(orch_doc, dict) and isinstance(orch_doc.get("adapters"), list):
        for ad in orch_doc["adapters"]:
            if isinstance(ad, dict) and ad.get("protocol"):
                tier_map[str(ad["protocol"])] = str(ad.get("tier") or "unknown")

    by_protocol: dict = {}
    by_tier: dict = {}
    for proto in sorted(positions):
        share = positions[proto] / total * 100.0
        tier = tier_map.get(proto, "unknown")
        by_protocol[proto] = {
            "usd": round(positions[proto], 2),
            "share_pct": round(share, 4),
            "tier": tier,
        }
        by_tier[tier] = round(by_tier.get(tier, 0.0) + share, 4)
    return {
        "available": True,
        "as_of": positions_doc.get("generated_at"),
        "capital_usd": round(total, 2),
        "deployed_usd": round(deployed, 2),
        "cash_pct": None if cash is None else round(cash / total * 100.0, 4),
        "by_protocol": by_protocol,
        "by_tier": dict(sorted(by_tier.items())),
    }


# ─── Proof-of-Track / Capital Ladder (чистые) ────────────────────────────────


def collect_month_anchors(anchors_doc: Any, month: str) -> List[dict]:
    """Merkle-якоря месяца из proof_of_track_anchors.json (MP-406).

    Мусорные записи пропускаются; published/tx_hash честно как в файле.
    """
    out: List[dict] = []
    if not isinstance(anchors_doc, dict):
        return out
    anchors = anchors_doc.get("anchors")
    if not isinstance(anchors, list):
        return out
    for a in anchors:
        if not isinstance(a, dict):
            continue
        date = a.get("date")
        if not _valid_date(date) or not str(date).startswith(month + "-"):
            continue
        out.append({
            "date": str(date),
            "merkle_root": a.get("merkle_root"),
            "leaf_count": a.get("leaf_count"),
            "published": a.get("published") is True,
            "tx_hash": a.get("tx_hash"),
        })
    out.sort(key=lambda a: a["date"])
    return out


def count_month_trades(trades_doc: Any, month: str) -> Optional[int]:
    """Число сделок месяца из trades.json. Чистая функция.

    Принимает список сделок или dict с ключом ``trades``; принадлежность
    месяцу — UTC ``ts``/``timestamp`` начинается с ``YYYY-MM-``.
    Отсутствующий/битый вход → честный None (нет данных — нет цифры);
    мусорные записи молча пропускаются.
    """
    items = trades_doc if isinstance(trades_doc, list) else (
        trades_doc.get("trades") if isinstance(trades_doc, dict) else None
    )
    if not isinstance(items, list):
        return None
    count = 0
    for trade in items:
        if not isinstance(trade, dict):
            continue
        stamp = trade.get("ts") or trade.get("timestamp")
        if isinstance(stamp, str) and stamp.startswith(month + "-"):
            count += 1
    return count


def _ladder_snapshot(ladder_doc: Any) -> Optional[dict]:
    """Срез capital_ladder_status.json (MP-505); битый/нет → None."""
    if not isinstance(ladder_doc, dict):
        return None
    return {
        "current_level": ladder_doc.get("current_level"),
        "level_code": ladder_doc.get("level_code"),
        "level_name": ladder_doc.get("level_name"),
        "aum_cap_usd": ladder_doc.get("aum_cap_usd"),
        "aum_usd": ladder_doc.get("aum_usd"),
        "track_days": ladder_doc.get("track_days"),
        "incidents_total": ladder_doc.get("incidents_total"),
    }


# ─── Сборка tear-sheet ───────────────────────────────────────────────────────


def build_tear_sheet(
    period: Optional[str] = None,
    data_dir: Optional[str | os.PathLike] = None,
    now: Optional[datetime] = None,
) -> dict:
    """Полный машиночитаемый tear-sheet за месяц ``period`` (YYYY-MM).

    Никогда не raise на данных: все источники опциональны, отсутствие/
    битость честно отражается в ``notes`` и None-полях. Секции:
    meta / performance / risk / exposure / incidents / proof_of_track /
    capital_ladder / notes.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    month = validate_month(period) if period is not None else current_month_utc(now)
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    notes: List[str] = []

    equity = _read_json(ddir / EQUITY_FILENAME)
    daily = equity.get("daily") if isinstance(equity, dict) else None
    if not isinstance(daily, list):
        daily = []
        notes.append(f"{EQUITY_FILENAME}: missing/unreadable — no monthly metrics")

    month_bars = filter_month_bars(daily, month)
    series = monthly_return_series(daily, month)
    returns = [r for _, r in series]
    if not month_bars:
        notes.append(f"no equity bars for month {month}")

    rm = _risk_metrics_for_month(series)
    net_return = compound_return_pct(returns)
    psr = compute_psr(returns)
    if psr.get("note"):
        notes.append(f"PSR: {psr['note']}")

    performance = {
        "num_days_in_month": len(month_bars),
        "num_return_days": rm["num_return_days"] if rm else 0,
        "net_return_pct": None if net_return is None else round(net_return, 6),
        "annualized_apy_pct": rm["annualized_return_pct"] if rm else None,
        "win_rate_pct": rm["win_rate_pct"] if rm else None,
        "best_day": rm["best_day"] if rm else None,
        "worst_day": rm["worst_day"] if rm else None,
        "annualization_days": ANNUALIZATION_DAYS,
    }
    trades_doc = _read_json(ddir / TRADES_FILENAME)
    performance["num_trades"] = count_month_trades(trades_doc, month)
    if performance["num_trades"] is None:
        notes.append(f"{TRADES_FILENAME}: missing/unreadable — no trade count")

    risk = {
        "daily_volatility_pct": rm["daily_volatility_pct"] if rm else None,
        "annualized_vol_pct": rm["annualized_vol_pct"] if rm else None,
        "sharpe_ratio": rm["sharpe_ratio"] if rm else None,
        "sortino_ratio": rm["sortino_ratio"] if rm else None,
        "max_drawdown_pct": rm["max_drawdown_pct"] if rm else None,
        "psr": psr,
        "incident_threshold_pct": INCIDENT_THRESHOLD_PCT,
    }

    pt = _read_json(ddir / PT_STATUS_FILENAME)
    if not isinstance(pt, dict):
        pt = {}
        notes.append(f"{PT_STATUS_FILENAME}: missing/unreadable")
    golive = _read_json(ddir / GOLIVE_STATUS_FILENAME)
    if not isinstance(golive, dict):
        notes.append(f"{GOLIVE_STATUS_FILENAME}: missing/unreadable")
    track = {
        "paper_start_date": pt.get("paper_start_date"),
        "days_running": pt.get("days_running"),
        "execution_mode": pt.get("execution_mode")
        or (equity.get("execution_mode") if isinstance(equity, dict) else None),
        "golive_ready": golive.get("ready") is True
        if isinstance(golive, dict) else None,
    }

    positions_doc = _read_json(ddir / POSITIONS_FILENAME)
    orch_doc = _read_json(ddir / ORCH_STATUS_FILENAME)
    exposure = build_exposure(positions_doc, orch_doc)
    if not exposure["available"]:
        notes.append(f"{POSITIONS_FILENAME}: missing/unreadable — no exposure")

    incident_items = detect_incidents(month_bars)
    ladder = _ladder_snapshot(_read_json(ddir / LADDER_STATUS_FILENAME))
    if ladder is None:
        notes.append(f"{LADDER_STATUS_FILENAME}: missing/unreadable")
    anchors = collect_month_anchors(_read_json(ddir / ANCHORS_FILENAME), month)
    if not anchors:
        notes.append(f"{ANCHORS_FILENAME}: no anchors for month {month}")

    is_demo = None
    for doc in (equity, pt):
        if isinstance(doc, dict) and isinstance(doc.get("is_demo"), bool):
            is_demo = doc["is_demo"]
            break

    return {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE_NAME,
        "meta": {
            "generated_at": now.isoformat(),
            "period": month,
            "is_demo": is_demo,
            "advisory_only": True,
            "source_files": list(SOURCE_FILES),
            "track": track,
            "publication": {
                "mode": "files_only",
                "note": "автопубликация = детерминированная генерация файлов; "
                        "хостинг GitHub Pages — UA-004 (не сделан)",
            },
            "disclaimer": DISCLAIMER,
        },
        "performance": performance,
        "risk": risk,
        "exposure": exposure,
        "incidents": {
            "threshold_pct": INCIDENT_THRESHOLD_PCT,
            "count": len(incident_items),
            "items": incident_items,
        },
        "proof_of_track": {
            "anchors_count": len(anchors),
            "latest_root": anchors[-1]["merkle_root"] if anchors else None,
            "anchors": anchors,
            "note": "Merkle roots дневного audit-трека (MP-406); "
                    "published=false до on-chain публикации (MP-017)",
        },
        "capital_ladder": ladder,
        "notes": notes,
    }


# ─── Markdown-рендер ─────────────────────────────────────────────────────────


def _fmt(value: Any, suffix: str = "") -> str:
    """Человекочитаемое значение; None → «н/д» (нет данных — нет цифры)."""
    if value is None:
        return "н/д"
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, float):
        return f"{value:.4f}{suffix}"
    return f"{value}{suffix}"


def render_markdown(doc: dict) -> str:
    """Детерминированный человекочитаемый markdown из машиночитаемого doc."""
    meta = doc.get("meta") or {}
    perf = doc.get("performance") or {}
    risk = doc.get("risk") or {}
    psr = risk.get("psr") or {}
    track = meta.get("track") or {}
    month = meta.get("period")
    lines: List[str] = []
    lines.append(f"# SPA — Публичный tear-sheet за {month}")
    lines.append("")
    lines.append(f"> **Дисклеймер:** {meta.get('disclaimer', DISCLAIMER)}")
    lines.append("")
    lines.append(f"- Сгенерировано: {meta.get('generated_at')} (UTC)")
    lines.append(f"- is_demo: {_fmt(meta.get('is_demo'))}")
    lines.append(f"- Режим: {_fmt(track.get('execution_mode'))}")
    lines.append(f"- Старт paper-трека: {_fmt(track.get('paper_start_date'))}")
    lines.append(f"- Дней трека всего: {_fmt(track.get('days_running'))}")
    lines.append(f"- Go-live гейт (MP-006): {_fmt(track.get('golive_ready'))}")
    lines.append("")
    lines.append("## Метрики")
    lines.append("")
    lines.append("| Метрика | Значение |")
    lines.append("|---|---|")
    rows = [
        ("Дней с данными в месяце", _fmt(perf.get("num_days_in_month"))),
        ("Дневных return'ов", _fmt(perf.get("num_return_days"))),
        ("Net return за месяц", _fmt(perf.get("net_return_pct"), "%")),
        ("Annualized APY (net)", _fmt(perf.get("annualized_apy_pct"), "%")),
        ("Дневная волатильность", _fmt(risk.get("daily_volatility_pct"), "%")),
        ("Годовая волатильность", _fmt(risk.get("annualized_vol_pct"), "%")),
        ("Sharpe (annualized)", _fmt(risk.get("sharpe_ratio"))),
        ("Sortino (annualized)", _fmt(risk.get("sortino_ratio"))),
        ("PSR (Bailey & López de Prado)", _fmt(psr.get("psr"))),
        ("Max drawdown за месяц", _fmt(risk.get("max_drawdown_pct"), "%")),
        ("Win-rate", _fmt(perf.get("win_rate_pct"), "%")),
        ("Сделок за месяц", _fmt(perf.get("num_trades"))),
    ]
    lines.extend(f"| {k} | {v} |" for k, v in rows)
    lines.append("")

    lines.append("## Exposure (на конец месяца)")
    lines.append("")
    exposure = doc.get("exposure") or {}
    if exposure.get("available") and exposure.get("by_protocol"):
        lines.append("| Протокол | Tier | USD | Доля |")
        lines.append("|---|---|---|---|")
        for proto, info in exposure["by_protocol"].items():
            lines.append(
                f"| {proto} | {info.get('tier')} | "
                f"{_fmt(info.get('usd'))} | {_fmt(info.get('share_pct'), '%')} |"
            )
        lines.append("")
        tiers = ", ".join(
            f"{t}: {share:.2f}%" for t, share in (exposure.get("by_tier") or {}).items()
        )
        lines.append(f"- По тирам: {tiers if tiers else 'н/д'}")
        lines.append(f"- Cash: {_fmt(exposure.get('cash_pct'), '%')}")
    else:
        lines.append("нет данных")
    lines.append("")

    incidents = doc.get("incidents") or {}
    lines.append(
        f"## Инциденты (порог ≥ {incidents.get('threshold_pct', INCIDENT_THRESHOLD_PCT)}% AUM)"
    )
    lines.append("")
    items = incidents.get("items") or []
    if items:
        lines.append("| Дата | Потеря | Тип |")
        lines.append("|---|---|---|")
        lines.extend(
            f"| {i.get('date')} | {_fmt(i.get('loss_pct'), '%')} | {i.get('kind')} |"
            for i in items
        )
    else:
        lines.append("Инцидентов за месяц не зафиксировано.")
    lines.append("")

    lines.append("## Proof-of-Track (Merkle roots)")
    lines.append("")
    anchors = (doc.get("proof_of_track") or {}).get("anchors") or []
    if anchors:
        lines.append("| Дата | Merkle root | Листьев | Published |")
        lines.append("|---|---|---|---|")
        for a in anchors:
            root = a.get("merkle_root")
            lines.append(
                f"| {a.get('date')} | `{root if root else 'null (пустой день)'}` "
                f"| {_fmt(a.get('leaf_count'))} | {_fmt(a.get('published'))} |"
            )
    else:
        lines.append("нет данных (якоря месяца отсутствуют)")
    lines.append("")

    lines.append("## Capital Ladder")
    lines.append("")
    ladder = doc.get("capital_ladder")
    if isinstance(ladder, dict):
        lines.append(
            f"- Ступень: {_fmt(ladder.get('level_code'))} "
            f"{_fmt(ladder.get('level_name'))} "
            f"(cap ${_fmt(ladder.get('aum_cap_usd'))})"
        )
        lines.append(f"- AUM: {_fmt(ladder.get('aum_usd'))} USD")
        lines.append(f"- Инцидентов за весь трек: {_fmt(ladder.get('incidents_total'))}")
    else:
        lines.append("нет данных")
    lines.append("")
    if doc.get("notes"):
        lines.append("## Примечания (notes)")
        lines.append("")
        lines.extend(f"- {n}" for n in doc["notes"])
        lines.append("")
    lines.append("---")
    lines.append(
        "_Сгенерировано детерминированно `spa_core.reporting.tear_sheet` "
        "(MP-501); публикация файлов — GitHub Pages (UA-004, pending)._"
    )
    lines.append("")
    return "\n".join(lines)


# ─── Запись выходов ──────────────────────────────────────────────────────────


def content_fingerprint(doc: Any) -> str:
    """Канонический отпечаток КОНТЕНТА tear-sheet'а. Чистая функция.

    Волатильные поля (``meta.generated_at``, top-level ``history``)
    исключаются: задокументированный выбор идемпотентности — generated_at
    обновляется ТОЛЬКО при изменении контента, history — производная прошлых
    прогонов. Не-dict вход → отпечаток, который никогда не совпадёт с
    валидным doc.
    """
    if not isinstance(doc, dict):
        return "<invalid>"
    core = {k: v for k, v in doc.items() if k != "history"}
    meta = core.get("meta")
    if isinstance(meta, dict):
        core["meta"] = {k: v for k, v in meta.items() if k != "generated_at"}
    return json.dumps(core, sort_keys=True, ensure_ascii=False)


def _history_entry(doc: dict) -> dict:
    """Краткая запись истории прогонов для tear_sheet_latest.json."""
    meta = doc.get("meta") or {}
    perf = doc.get("performance") or {}
    risk = doc.get("risk") or {}
    return {
        "period": meta.get("period"),
        "generated_at": meta.get("generated_at"),
        "net_return_pct": perf.get("net_return_pct"),
        "sharpe_ratio": risk.get("sharpe_ratio"),
        "max_drawdown_pct": risk.get("max_drawdown_pct"),
        "incidents_count": (doc.get("incidents") or {}).get("count"),
    }


def write_outputs(
    doc: dict,
    data_dir: Optional[str | os.PathLike] = None,
    reports_dir: Optional[str | os.PathLike] = None,
) -> dict:
    """Атомарно пишет data/tear_sheet_latest.json + reports/*.md.

    Идемпотентность: если контент (см. :func:`content_fingerprint`) не
    изменился относительно сохранённого статуса — ни JSON, ни существующий
    markdown НЕ перезаписываются (повторный --run байт-в-байт ничего не
    меняет, history не растёт). При изменении контента generated_at
    обновляется, в history добавляется запись (ротация ≤ HISTORY_MAX).
    Битый существующий статус-файл толерантно трактуется как отсутствующий.
    Markdown — один файл на месяц. Возвращает пути и флаг ``changed``.
    """
    ddir = Path(data_dir) if data_dir is not None else _DEFAULT_DATA_DIR
    rdir = Path(reports_dir) if reports_dir is not None else _DEFAULT_REPORTS_DIR
    json_path = ddir / STATUS_FILENAME
    month = (doc.get("meta") or {}).get("period")
    md_path = rdir / MD_FILENAME_TPL.format(month=month)

    prev = _read_json(json_path)
    changed = content_fingerprint(prev) != content_fingerprint(doc)
    if not changed and isinstance(prev, dict):
        # Контент тот же: переиспользуем прежний doc (его generated_at),
        # JSON не трогаем; markdown дописываем только если его ещё нет.
        doc = prev
        if not md_path.exists():
            _atomic_write_text(md_path, render_markdown(doc))
        log.info("tear sheet unchanged: %s", json_path)
        return {"json": str(json_path), "markdown": str(md_path),
                "changed": False}

    history: List[dict] = []
    if isinstance(prev, dict) and isinstance(prev.get("history"), list):
        history = [h for h in prev["history"] if isinstance(h, dict)]
    history.append(_history_entry(doc))
    doc = dict(doc)
    doc["history"] = history[-HISTORY_MAX:]
    _atomic_write_json(json_path, doc)
    _atomic_write_text(md_path, render_markdown(doc))
    log.info("tear sheet written: %s, %s", json_path, md_path)
    return {"json": str(json_path), "markdown": str(md_path), "changed": True}


# ─── CLI ─────────────────────────────────────────────────────────────────────


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tear_sheet",
        description="Публичный ежемесячный tear-sheet SPA (MP-501) — "
                    "read-only/advisory, без сети.",
    )
    group = p.add_mutually_exclusive_group()
    group.add_argument(
        "--check", action="store_true",
        help="вычислить и напечатать tear-sheet БЕЗ записи (по умолчанию)",
    )
    group.add_argument(
        "--run", action="store_true",
        help="вычислить и атомарно записать JSON + markdown",
    )
    p.add_argument(
        "--month", default=None,
        help="календарный месяц YYYY-MM (UTC; по умолчанию текущий)",
    )
    p.add_argument("--data-dir", default=None, help="override data directory")
    p.add_argument(
        "--reports-dir", default=None,
        help="override reports/ directory (для markdown)",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    try:
        if args.month is not None:
            try:
                validate_month(args.month)
            except ValueError as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 0
        doc = build_tear_sheet(period=args.month, data_dir=args.data_dir)
        if args.run:
            paths = write_outputs(
                doc, data_dir=args.data_dir, reports_dir=args.reports_dir
            )
            print(
                f"TEAR SHEET {doc['meta']['period']}: "
                f"{'written' if paths['changed'] else 'unchanged (idempotent)'} "
                f"{paths['json']} and {paths['markdown']} "
                f"(days={doc['performance']['num_days_in_month']}, "
                f"net={doc['performance']['net_return_pct']}%, "
                f"incidents={doc['incidents']['count']})"
            )
        else:
            print(json.dumps(doc, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:  # advisory CLI: никогда не трейсбек
        print(f"ERROR: tear_sheet failed: {exc}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
