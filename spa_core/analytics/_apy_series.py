"""
_apy_series.py — детерминированный читатель исторических APY-рядов (линия A1,
план docs/PLAN_YIELD_STABILITY_2026-08-05.md, поток 3 плана
docs/analytics_relocation_plan_2026-08-04.md).

Зачем: форкастерам/компараторам сигнального слоя структурного профиля
(_protocol_facts) мало — им нужны РЯДЫ. Этот модуль отдаёт честный временной
ряд APY по протоколу из уже существующих файлов data/, ничего не выдумывая.

Источники (только чтение, приоритет на совпадающую дату сверху вниз):
  1. data/historical_apy/<file>.json — дневные ряды [{"date","apy"}, ...]
     (5 файлов, ~365 дней каждый);
  2. data/adapter_status.json        — текущая живая точка (apy / live_apy);
  3. data/apy_ranking.json           — текущая точка снапшота (apy_pct).

Инварианты:
* ВЫРАВНИВАНИЕ ПО ДАТЕ, НЕ ПО ИНДЕКСУ. Оси дат файлов historical_apy НЕ
  совпадают (память проекта historical-apy-axis-misaligned: compound
  начинается 2025-06-19, остальные 2025-06-21) — ряд собирается словарём
  {date: apy} и сортируется по дате.
* Единицы: все три источника хранят ПРОЦЕНТЫ (3.31 = 3.31% годовых).
  Правило adapter-слоя «старые адаптеры возвращают долю» относится к
  get_apy() объектов-адаптеров, а НЕ к этим файлам data/ — они пишутся
  генераторами уже в процентах. Никакой эвристики «0.03 → 3%» здесь нет
  сознательно: она неотличима от честного APY 0.03%.
* Fail-CLOSED: недобор min_days → None (не интерполяция, не подстановка).
  Дыры в ряду (например разрыв historical_apy 2026-06-20 → живая точка
  сегодня) остаются дырами: ряд — только фактические (date, apy) точки.
* Никаких записей: модуль строго read-only по отношению к data/.
* stdlib-only, LLM FORBIDDEN, детерминированный (кеш по mtime/size файлов).

Алиасы протоколов — консервативные: только имена, обозначающие ТОТ ЖЕ
рынок (morpho → morpho_blue; sky/spark/susds → spark_susds). Намеренно НЕТ
маппинга morpho_steakhouse → morpho_blue (другой vault, другая доходность —
подстановка чужого ряда была бы фабрикацией).
"""
from __future__ import annotations

import json
import math
from datetime import date as _date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # SPA_Claude/
DATA_DIR = BASE_DIR / "data"

HIST_SUBDIR = "historical_apy"
ADAPTER_STATUS_FILE = "adapter_status.json"
APY_RANKING_FILE = "apy_ranking.json"

SERIES_SOURCE = "apy_series_v1"

# Канонический протокол → файл дневного ряда (data/historical_apy/<stem>.json)
_HIST_FILES: Dict[str, str] = {
    "aave_v3": "aave_v3_usdc",
    "compound_v3": "compound_v3_usdc",
    "morpho_blue": "morpho_blue_usdc",
    "yearn_v3": "yearn_v3_usdc",
    "spark_susds": "sky_susds",
}

# Консервативные алиасы (тот же рынок под другим именем).
_ALIASES: Dict[str, str] = {
    "aave_v3_eth": "aave_v3",
    "morpho": "morpho_blue",
    "sky": "spark_susds",
    "sky_susds": "spark_susds",
    "spark": "spark_susds",
    "susds": "spark_susds",
}

# Приоритет источника на совпадающую дату (меньше = главнее).
_PRIO_HIST = 0
_PRIO_ACCUMULATED = 1   # data/apy_series_daily.json — дневной накопитель (живые точки цикла)
_PRIO_ADAPTER_STATUS = 2
_PRIO_RANKING = 3
ACCUMULATED_FILE = "apy_series_daily.json"

# Санитарный фильтр значений: конечное число в правдоподобном диапазоне
# процентов годовых. Всё вне диапазона отбрасывается (fail-closed), а не
# «чинится».
_APY_MIN = -100.0
_APY_MAX = 10_000.0

# Кеш: str(data_dir) → (signature, table)
# table: {canonical_protocol: {date_iso: (prio, apy_pct)}}
_CACHE: Dict[str, Tuple[Tuple, Dict[str, Dict[str, Tuple[int, float]]]]] = {}


def canonical_protocol(protocol: Any) -> Optional[str]:
    """Каноническое имя протокола или None (не строка / пусто)."""
    if not isinstance(protocol, str):
        return None
    key = protocol.strip().lower()
    if not key:
        return None
    return _ALIASES.get(key, key)


def _valid_apy(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    if not math.isfinite(f) or f < _APY_MIN or f > _APY_MAX:
        return None
    return f


def _valid_date(s: Any) -> Optional[str]:
    """ISO-дата (первые 10 символов ISO-строки) или None."""
    if not isinstance(s, str) or len(s) < 10:
        return None
    d = s[:10]
    try:
        _date.fromisoformat(d)
    except ValueError:
        return None
    return d


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _source_files(data_dir: Path) -> List[Path]:
    files: List[Path] = []
    hist = data_dir / HIST_SUBDIR
    if hist.is_dir():
        files.extend(sorted(hist.glob("*.json")))
    for name in (ADAPTER_STATUS_FILE, APY_RANKING_FILE):
        p = data_dir / name
        if p.is_file():
            files.append(p)
    return files


def _signature(files: List[Path]) -> Tuple:
    sig = []
    for p in files:
        try:
            st = p.stat()
            sig.append((str(p), st.st_mtime_ns, st.st_size))
        except OSError:
            sig.append((str(p), None, None))
    return tuple(sig)


def _put(table: Dict[str, Dict[str, Tuple[int, float]]],
         proto: Optional[str], day: Optional[str],
         apy: Optional[float], prio: int) -> None:
    if proto is None or day is None or apy is None:
        return
    row = table.setdefault(proto, {})
    old = row.get(day)
    if old is None or prio < old[0]:
        row[day] = (prio, apy)


def _build_table(data_dir: Path) -> Dict[str, Dict[str, Tuple[int, float]]]:
    table: Dict[str, Dict[str, Tuple[int, float]]] = {}

    # 1. Дневные ряды historical_apy/ (ось дат у файлов РАЗНАЯ — ключуем датой).
    stem_to_proto = {stem: proto for proto, stem in _HIST_FILES.items()}
    hist_dir = data_dir / HIST_SUBDIR
    if hist_dir.is_dir():
        for path in sorted(hist_dir.glob("*.json")):
            proto = canonical_protocol(stem_to_proto.get(path.stem, path.stem))
            rows = _load_json(path)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                _put(table, proto, _valid_date(row.get("date")),
                     _valid_apy(row.get("apy")), _PRIO_HIST)

    # 1.5. Дневной накопитель apy_series_daily.json (пишет apy_series_accumulator из
    # дневного цикла с 2026-08-05; закрывает смерть генератора historical_apy 2026-06-30 —
    # без него у 31 протокола была бы вечно одна точка). Живые точки, дыры не заполняются.
    acc = _load_json(data_dir / ACCUMULATED_FILE)
    if isinstance(acc, dict) and isinstance(acc.get("series"), dict):
        for name, rows in acc["series"].items():
            if not isinstance(rows, list):
                continue
            proto = canonical_protocol(name)
            for row in rows:
                if isinstance(row, list) and len(row) == 2:
                    _put(table, proto, _valid_date(row[0]), _valid_apy(row[1]),
                         _PRIO_ACCUMULATED)

    # 2. Текущая живая точка adapter_status.json (проценты).
    status = _load_json(data_dir / ADAPTER_STATUS_FILE)
    if isinstance(status, dict):
        default_day = _valid_date(status.get("generated_at"))
        adapters = status.get("adapters")
        if isinstance(adapters, dict):
            for name, info in adapters.items():
                if not isinstance(info, dict):
                    continue
                apy = _valid_apy(info.get("apy"))
                if apy is None:
                    apy = _valid_apy(info.get("live_apy"))
                day = (_valid_date(info.get("live_apy_as_of"))
                       or _valid_date(info.get("last_updated"))
                       or default_day)
                _put(table, canonical_protocol(name), day, apy,
                     _PRIO_ADAPTER_STATUS)

    # 3. Текущая точка apy_ranking.json (apy_pct, проценты).
    ranking = _load_json(data_dir / APY_RANKING_FILE)
    if isinstance(ranking, dict):
        default_day = _valid_date(ranking.get("generated_at"))
        rows = ranking.get("by_apy")
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                day = _valid_date(row.get("last_updated")) or default_day
                _put(table, canonical_protocol(row.get("protocol")), day,
                     _valid_apy(row.get("apy_pct")), _PRIO_RANKING)

    return table


def _table(data_dir: Optional[Path]) -> Dict[str, Dict[str, Tuple[int, float]]]:
    dd = Path(data_dir) if data_dir is not None else DATA_DIR
    key = str(dd)
    files = _source_files(dd)
    sig = _signature(files)
    cached = _CACHE.get(key)
    if cached is not None and cached[0] == sig:
        return cached[1]
    table = _build_table(dd)
    _CACHE[key] = (sig, table)
    return table


# ─── Public API ──────────────────────────────────────────────────────────────

def get_series(protocol: Any, min_days: Optional[int] = None,
               data_dir: Optional[Any] = None
               ) -> Optional[List[Tuple[str, float]]]:
    """Ряд [(date_iso, apy_pct), ...] по возрастанию даты, или None.

    None (fail-closed) когда: протокол неизвестен/нет ни одной точки, либо
    точек меньше *min_days*. Дыры в датах НЕ интерполируются — возвращаются
    только фактические точки.
    """
    proto = canonical_protocol(protocol)
    if proto is None:
        return None
    row = _table(Path(data_dir) if data_dir is not None else None).get(proto)
    if not row:
        return None
    series = [(day, row[day][1]) for day in sorted(row)]
    if min_days is not None and int(min_days) > 0 and len(series) < int(min_days):
        return None
    return series


def days_available(protocol: Any, data_dir: Optional[Any] = None) -> int:
    """Сколько фактических дневных точек есть у протокола (0 = ни одной)."""
    series = get_series(protocol, data_dir=data_dir)
    return len(series) if series else 0


def latest(protocol: Any, data_dir: Optional[Any] = None
           ) -> Optional[Tuple[str, float]]:
    """Последняя фактическая точка (date_iso, apy_pct) или None."""
    series = get_series(protocol, data_dir=data_dir)
    return series[-1] if series else None


def latest_all(data_dir: Optional[Any] = None) -> Dict[str, Tuple[str, float]]:
    """Последняя точка каждого известного протокола: {proto: (date, apy)}."""
    table = _table(Path(data_dir) if data_dir is not None else None)
    out: Dict[str, Tuple[str, float]] = {}
    for proto, row in table.items():
        if row:
            day = max(row)
            out[proto] = (day, row[day][1])
    return out


def list_protocols(data_dir: Optional[Any] = None) -> List[str]:
    """Отсортированный список протоколов, у которых есть хоть одна точка."""
    table = _table(Path(data_dir) if data_dir is not None else None)
    return sorted(p for p, row in table.items() if row)


def get_aligned(protocols: List[Any], min_days: Optional[int] = None,
                data_dir: Optional[Any] = None
                ) -> Optional[Dict[str, List[Tuple[str, float]]]]:
    """Ряды нескольких протоколов, выровненные ПО ОБЩИМ ДАТАМ.

    Возвращает {proto: [(date, apy), ...]} — у всех протоколов одинаковый
    набор дат (пересечение). None (fail-closed), если хоть у одного
    протокола нет данных или общих дат меньше *min_days*.
    """
    per_proto: Dict[str, Dict[str, float]] = {}
    common: Optional[set] = None
    for p in protocols:
        series = get_series(p, data_dir=data_dir)
        if not series:
            return None
        proto = canonical_protocol(p)
        d = dict(series)
        per_proto[proto] = d
        common = set(d) if common is None else (common & set(d))
    if not common:
        return None
    days = sorted(common)
    if min_days is not None and int(min_days) > 0 and len(days) < int(min_days):
        return None
    return {proto: [(day, vals[day]) for day in days]
            for proto, vals in per_proto.items()}


def stats(protocol: Any, min_days: Optional[int] = None,
          window: Optional[int] = None, data_dir: Optional[Any] = None
          ) -> Optional[Dict[str, Any]]:
    """Детерминированные статистики ряда (или None при недоборе min_days).

    window — взять только последние N точек (после проверки min_days
    на полном ряду окно НЕ ослабляет требование: min_days применяется
    к обрезанному окну тоже).
    """
    series = get_series(protocol, min_days=min_days, data_dir=data_dir)
    if series is None:
        return None
    if window is not None and int(window) > 0:
        series = series[-int(window):]
        if min_days is not None and len(series) < int(min_days):
            return None
    values = [v for _, v in series]
    n = len(values)
    mean = sum(values) / n
    if n >= 2:
        std = math.sqrt(sum((v - mean) ** 2 for v in values) / n)
    else:
        std = 0.0
    peak = values[0]
    max_dd = 0.0  # максимальная относительная просадка APY от пика, %
    for v in values:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak * 100.0
            if dd > max_dd:
                max_dd = dd
    return {
        "protocol": canonical_protocol(protocol),
        "n": n,
        "first_date": series[0][0],
        "last_date": series[-1][0],
        "current": values[-1],
        "mean": mean,
        "std": std,
        "min": min(values),
        "max": max(values),
        "max_drawdown_pct": max_dd,
        "source": SERIES_SOURCE,
    }


def clear_cache() -> None:
    """Сбросить кеш (для тестов)."""
    _CACHE.clear()
