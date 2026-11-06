"""
scripts/edge_frozen_mark_provenance.py — #154 FMP: Frozen-Mark Provenance.

ИСПОЛНЕНИЕ ЗАКАЗА #152 (повторён #153 п. 1): «почему forward-шаг `aggressive_lab` выдаёт
5 книгам из 10 нулевой `mtm_today_pct` и не переоценивает `eth_directional` по цене ETH;
приёмка — напечатанный ИСТОЧНИК МАРКИ для каждой из 10 книг и НАЗВАННАЯ ПРИЧИНА нуля у
каждой из пяти» + второй вопрос заказа про существование `exit_nav` для панели.

ЧТО ЭТО МЕРИТ — и почему это НЕ повтор #152.
  #152 считал единицу «день с маркой» как `mtm_today_pct != 0`. У строки есть ВТОРОЕ поле —
  `mtm_source` (провенанс марки, пишется `harness._point`), и его не читал никто. Эти два
  поля дают РАЗНЫЕ ответы, и разница между ними и есть предмет записи:

    mtm_source = null   ⇒ марки в этот день НЕ БЫЛО      (честное «не измерено»)
    mtm_source = <имя>  ⇒ марка ОБЪЯВЛЕНА;               (претензия на наблюдение)
      и тогда значение 0.0 — это «измерено и равно нулю», а не «не измерено».

  Пять книг, которые #152 назвал «без ни одной марки», распадаются по этой оси на ТРИ
  разных рода, и два из них — дефекты, а не тишина.

  Обратная сторона, которой единица #152 не видит ПО ПОСТРОЕНИЮ: книга, чья марка читает
  замороженный фид как УРОВЕНЬ (а не как разность день-к-дню), продолжает печатать
  НЕнулевые числа — и выглядит живее всех. Поэтому прибор меряет не только «есть ли
  марка», но и «является ли объявленный ряд НАБЛЮДЕНИЕМ дневного пути».

ТРИ ИСХОДА РАЗЛИЧИМЫ ВСЮДУ (инв. #17): измерено · измерено и равно нулю · НЕ ИЗМЕРЕНО
(каталог нечитаем · forward-строк нет · поля `mtm_today_pct` в строке НЕТ вовсе — это
не ноль). Прибор ОТКАЗЫВАЕТ кодом 2, если не смог прочитать ни одной книги.

Все числа — [L0] замер артефакта, не реализованный P&L. Хвост печатается рядом с доходом.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── объявления прибора (мерка живёт здесь, не в голове читателя) ──────────────────────────
#
# Доля РАЗЛИЧНЫХ значений объявленной марки, ниже которой ряд наблюдением дневного пути
# НЕ является. Выбрана НЕ подгонкой: марка, снятая с дневного рыночного пути, меняется
# практически каждый день, поэтому порог стои́т посередине (0.5) — он отделяет «путь» от
# «уровень, применённый повторно», а не ранжирует книги. Любое значение в (0.1, 0.9) даёт
# на этом замере тот же вердикт у всех десяти книг, и это напечатано (§1, колонка «доля»).
OBSERVED_MIN_DISTINCT_FRACTION = 0.5

# Сколько строк нужно, чтобы вообще СУДИТЬ о постоянстве ряда. Меньше — третий исход.
MIN_ROWS_FOR_CONSTANCY_VERDICT = 10

# Сколько книг должны сменить значение марки В ОДИН ДЕНЬ, чтобы день стал кандидатом в
# «шаг обновления набора данных», а не в рыночное событие. Три — это минимум, при котором
# совпадение перестаёт быть парой.
SHARED_STEP_MIN_BOOKS = 3

PANEL_BOOKS = [
    "eth_directional", "leverage_loop", "levered_restaking", "lp_eth_stable",
    "lrt_neutral", "pendle_pt_levered", "pendle_yt_susde", "points_farm",
    "susde_dn", "susde_spot",
]

# ── роды вердикта: НЕ взаимозаменяемы ────────────────────────────────────────────────────
NO_FORWARD_ROWS = "НЕ ИЗМЕРЕНО: forward-строк нет"
UNREADABLE = "НЕ ИЗМЕРЕНО: ряд нечитаем"
FIELD_ABSENT = "НЕ ИЗМЕРЕНО: поля mtm_today_pct в строках НЕТ"
TOO_SHORT = "НЕ ИЗМЕРЕНО: строк меньше объявленного минимума"
NO_MARK = "МАРКИ НЕТ (источник null во всех строках)"
DECLARED_ALL_ZERO = "МАРКА ОБЪЯВЛЕНА и РАВНА НУЛЮ во всех объявленных днях"
DECLARED_CONSTANT = "МАРКА ОБЪЯВЛЕНА, но ряд НЕ является наблюдением дневного пути"
OBSERVED = "НАБЛЮДЕНИЕ дневного пути"

VERDICTS = (NO_FORWARD_ROWS, UNREADABLE, FIELD_ABSENT, TOO_SHORT,
            NO_MARK, DECLARED_ALL_ZERO, DECLARED_CONSTANT, OBSERVED)


# Дерево, из которого прибор ввозит `spa_core`: СВОЁ, а не прод-дерево. `--repo-root`
# задаёт, ГДЕ искать данные и соседей `exit_nav`; код берётся оттуда, где лежит прибор,
# иначе замер отвечал бы о чужом дереве (та же дверь, что § «ДЕРЕВО, ИЗ КОТОРОГО
# ЧИТАЮТСЯ БАЙТЫ» в .claude/rules/deployment.md).
_MODULE_ROOT = Path(__file__).resolve().parents[1]


def _import_root() -> None:
    if str(_MODULE_ROOT) not in sys.path:
        sys.path.insert(0, str(_MODULE_ROOT))


class Unmeasured(Exception):
    """Прибор не смог ответить. Никогда не подменяется нулём и не выдаётся за «чисто»."""


# ── чтение ряда ──────────────────────────────────────────────────────────────────────────

def read_forward_rows(data_dir: Path, book: str) -> Tuple[Optional[List[dict]], str]:
    """Вернуть (строки forward-блока, причина-если-None). Нечитаемость — НЕ пустой список."""
    p = Path(data_dir) / book / "realized_series.jsonl"
    if not p.is_file():
        return None, f"{UNREADABLE}: нет файла {p}"
    rows: List[dict] = []
    try:
        with open(p, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                doc = json.loads(line)
                if isinstance(doc, dict) and doc.get("phase") == "forward":
                    rows.append(doc)
    except (OSError, ValueError) as exc:
        return None, f"{UNREADABLE}: {type(exc).__name__}: {exc}"
    if not rows:
        return [], NO_FORWARD_ROWS
    return rows, ""


# ── ЕДИНСТВЕННАЯ дверь к вопросу «является ли объявленный ряд наблюдением» ────────────────

def classify_series(rows: Optional[List[dict]], *, unreadable_reason: str = "") -> dict:
    """Класс марки ОДНОЙ книги по её forward-блоку.

    Отвечает на три РАЗНЫХ вопроса раздельно и никогда не сводит их в один:
      (1) объявлен ли источник марки в этот день (`mtm_source`);
      (2) чему равно значение марки в объявленный день;
      (3) является ли ОБЪЯВЛЕННЫЙ ряд наблюдением дневного пути.
    """
    if rows is None:
        return {"verdict": unreadable_reason or UNREADABLE, "n_rows": None,
                "n_declared": None, "n_no_mark": None, "n_declared_zero": None,
                "n_declared_nonzero": None, "distinct_declared": None,
                "distinct_fraction": None, "change_points": [],
                "single_day_excursions": [], "n_single_day_excursions": None,
                "measurable": False}
    if not rows:
        return {"verdict": NO_FORWARD_ROWS, "n_rows": 0, "n_declared": 0, "n_no_mark": 0,
                "n_declared_zero": 0, "n_declared_nonzero": 0, "distinct_declared": 0,
                "distinct_fraction": None, "change_points": [],
                "single_day_excursions": [], "n_single_day_excursions": 0,
                "measurable": False}

    # (0) поле может ОТСУТСТВОВАТЬ — это не ноль (инв. #17)
    with_key = [r for r in rows if "mtm_today_pct" in r]
    if not with_key:
        return {"verdict": FIELD_ABSENT, "n_rows": len(rows), "n_declared": None,
                "n_no_mark": None, "n_declared_zero": None, "n_declared_nonzero": None,
                "distinct_declared": None, "distinct_fraction": None,
                "change_points": [], "single_day_excursions": [],
                "n_single_day_excursions": None, "measurable": False}

    declared = [r for r in rows if r.get("mtm_source") is not None]
    no_mark = [r for r in rows if r.get("mtm_source") is None]
    dz = [r for r in declared
          if isinstance(r.get("mtm_today_pct"), (int, float)) and r["mtm_today_pct"] == 0.0]
    dnz = [r for r in declared
           if isinstance(r.get("mtm_today_pct"), (int, float)) and r["mtm_today_pct"] != 0.0]
    distinct = sorted({r.get("mtm_today_pct") for r in declared
                       if isinstance(r.get("mtm_today_pct"), (int, float))})

    # точки смены значения марки — отпечаток «шага», а не пути
    change_points: List[dict] = []
    prev = None
    for r in rows:
        v = r.get("mtm_today_pct")
        if prev is not None and v != prev:
            change_points.append({"date": r.get("date"), "from": prev, "to": v})
        prev = v

    # ОДНОДНЕВНАЯ ЭКСКУРСИЯ: значение ушло и ВЕРНУЛОСЬ к прежнему следующей же сменой,
    # причём смена пришла на следующий календарный день ряда. Рыночный путь так не ходит;
    # так ходит ОДНОРАЗОВО обновлённый вход, прочитанный как разность день-к-дню.
    excursions: List[dict] = []
    for i in range(len(change_points) - 1):
        a, b = change_points[i], change_points[i + 1]
        if a.get("to") == b.get("from") and b.get("to") == a.get("from"):
            excursions.append({"out": a.get("date"), "back": b.get("date"),
                               "value": a.get("to"), "baseline": a.get("from")})

    frac = (len(distinct) / len(declared)) if declared else None

    if not declared:
        verdict = NO_MARK
    elif len(rows) < MIN_ROWS_FOR_CONSTANCY_VERDICT:
        verdict = TOO_SHORT
    elif not dnz:
        verdict = DECLARED_ALL_ZERO
    elif frac is not None and frac < OBSERVED_MIN_DISTINCT_FRACTION:
        verdict = DECLARED_CONSTANT
    else:
        verdict = OBSERVED

    return {
        "verdict": verdict,
        "n_rows": len(rows),
        "n_declared": len(declared),
        "n_no_mark": len(no_mark),
        "n_declared_zero": len(dz),
        "n_declared_nonzero": len(dnz),
        "distinct_declared": len(distinct),
        "distinct_values": distinct[:8],
        "distinct_fraction": frac,
        "change_points": change_points,
        "single_day_excursions": excursions,
        "n_single_day_excursions": len(excursions),
        "sources": sorted({str(r.get("mtm_source")) for r in rows}),
        "first_date": rows[0].get("date"),
        "last_date": rows[-1].get("date"),
        "measurable": verdict == OBSERVED,
    }


# ── §1 перепись источника марки по всем книгам ───────────────────────────────────────────

def mark_source_census(data_dir: Path, books: Optional[List[str]] = None) -> dict:
    books = list(books or PANEL_BOOKS)
    per: Dict[str, dict] = {}
    for b in books:
        rows, reason = read_forward_rows(data_dir, b)
        per[b] = classify_series(rows, unreadable_reason=reason)
    read_ok = [b for b, c in per.items() if c["n_rows"] not in (None,)]
    if not read_ok:
        raise Unmeasured(
            f"ни одна книга не прочитана в {data_dir} — ответ о панели НЕ ВЫДАЁТСЯ")
    observed = [b for b, c in per.items() if c["verdict"] == OBSERVED]
    return {
        "data_dir": str(data_dir),
        "books": per,
        "n_books": len(books),
        "n_read": len(read_ok),
        "n_observed": len(observed),
        "observed_books": observed,
        "evidence_level": "L0 — замер артефакта forward-блока, НЕ реализованный P&L",
    }


# ── §2 причина нуля: названа МЕХАНИЗМОМ кода, а не догадкой ──────────────────────────────

def code_causes(paper_state: Optional[dict] = None) -> dict:
    """Для каждой книги ростера: есть ли у неё крюк марки, какие ЯКОРЯ он держит и
    сохраняются ли эти якоря между перезапусками службы.

    Якорь, которого НЕТ в сохраняемом наборе `harness._book_state`, означает, что крюк
    КАЖДЫЙ перезапуск уходит в ветку «первая точка ряда» и возвращает 0.0, не объявив
    источника — то есть марка невозможна ПО ПОСТРОЕНИЮ, сколько дней ни добавляй.
    """
    _import_root()
    try:
        from spa_core.strategy_lab.aggressive_lab import harness as H
        from spa_core.strategy_lab.aggressive_lab import roster as R
    except Exception as exc:  # noqa: BLE001
        raise Unmeasured(f"ростер/харнесс не ввезены: {type(exc).__name__}: {exc}") from exc

    try:
        strats = R.build_roster(None, notional_usd=100_000.0)
    except Exception as exc:  # noqa: BLE001
        raise Unmeasured(f"ростер не собран: {type(exc).__name__}: {exc}") from exc

    import inspect
    base_hook = R._AggressiveBase._mark_to_market_pct
    out: Dict[str, dict] = {}
    for sid, s in sorted(strats.items()):
        try:
            s.init(100_000.0, {})
        except Exception:  # noqa: BLE001 — init не обязателен для вопроса о якорях
            pass
        has_hook = type(s)._mark_to_market_pct is not base_hook
        anchors = sorted(a for a in vars(s)
                         if a.startswith("_prev_") or a.startswith("_entry_"))
        persisted = set(H._book_state(s).keys())
        missing = [a for a in anchors if a.lstrip("_") not in persisted]
        # Якорь, которого нет в сохраняемом наборе, гасит НЕ ТОЛЬКО марку: если его имя
        # читает ещё и `_kill`, то не сохранённый якорь делает ГЕЙТ слепым (каждый
        # перезапуск сравнивает сегодняшнее значение с сегодняшним ⇒ отклонение 0).
        kill_src = ""
        for meth in ("_kill", "kill_check"):
            fn = getattr(type(s), meth, None)
            if fn is None:
                continue
            try:
                kill_src += inspect.getsource(fn)
            except (OSError, TypeError):
                kill_src += ""
        mark_src = ""
        try:
            mark_src = inspect.getsource(type(s)._mark_to_market_pct) if has_hook else ""
        except (OSError, TypeError):
            mark_src = ""
        blind_kill = [a for a in missing if a in kill_src]
        blind_mark = [a for a in missing if a in mark_src]
        killed = None
        if isinstance(paper_state, dict):
            b = (paper_state.get("books") or {}).get(sid)
        kill_reason = None
        if isinstance(paper_state, dict):
            b = (paper_state.get("books") or {}).get(sid)
            if isinstance(b, dict):
                killed = bool(b.get("killed"))
                kill_reason = b.get("kill_reason") or None
        out[sid] = {
            "has_mark_hook": has_hook,
            "anchors": anchors,
            "anchors_not_persisted": missing,
            "anchors_not_persisted_read_by_kill": blind_kill,
            "anchors_not_persisted_read_by_mark": blind_mark,
            "killed_in_state": killed,
            "kill_reason_in_state": kill_reason,
        }
    return {"books": out,
            "persisted_anchor_keys": sorted(
                k for k in H._book_state(next(iter(strats.values()))).keys()
                if k.startswith("prev_") or k.startswith("entry_"))}


# ── §3 общий шаг: день, в который значение сменили СРАЗУ несколько книг ──────────────────

def shared_step_days(census: dict) -> List[dict]:
    """Дни, в которые значение марки сменилось у >= SHARED_STEP_MIN_BOOKS книг.

    Рыночное событие продолжается следующими днями; ШАГ обновлённого набора данных —
    нет: ряд возвращается к прежнему значению на следующий же день. Прибор печатает ОБА
    признака и не решает за читателя, печатает ФАКТ возврата."""
    by_day: Dict[str, List[str]] = {}
    for b, c in (census.get("books") or {}).items():
        for cp in (c.get("change_points") or []):
            by_day.setdefault(str(cp.get("date")), []).append(b)
    out = []
    for day, bs in sorted(by_day.items()):
        if len(bs) >= SHARED_STEP_MIN_BOOKS:
            reverted = []
            for b in bs:
                cps = (census["books"][b].get("change_points") or [])
                idx = [i for i, cp in enumerate(cps) if str(cp.get("date")) == day]
                if idx and idx[0] + 1 < len(cps):
                    nxt = cps[idx[0] + 1]
                    if nxt.get("to") == cps[idx[0]].get("from"):
                        reverted.append(b)
            out.append({"date": day, "books": sorted(bs), "n_books": len(bs),
                        "reverted_next_change": sorted(reverted)})
    return out


# ── §4 второй вопрос заказа: существует ли exit_nav для панели ───────────────────────────

def exit_nav_presence(repo_root: Path, panel_dir: Path) -> dict:
    panel = Path(panel_dir) / "exit_nav.json"
    neighbours = []
    data = Path(repo_root) / "data"
    if data.is_dir():
        for p in sorted(data.glob("*/exit_nav.json")):
            neighbours.append(str(p.relative_to(repo_root)))
    return {"panel_exit_nav": str(panel), "panel_exit_nav_exists": panel.is_file(),
            "neighbours_that_exist": neighbours,
            "data_dir_readable": data.is_dir()}


# ── §5 возраст входа марки: НЕ стенные часы, а объявленный момент ────────────────────────

def mark_input_staleness(now: datetime.date, pt_history: Path) -> dict:
    """НОВЕЙШАЯ дата набора данных, который форвардный тик читает как «живое» значение.

    `run._real_history_feeds()` отдаёт живому тику ТЕ ЖЕ исторические ряды, что и бэктесту,
    а `feeds.build_live_snapshot` берёт из каждого ряда `max(series)` — то есть ПОСЛЕДНЮЮ
    дату набора. Пока набор не обновлён, «живое» значение тика есть КОНСТАНТА, и разность
    день-к-дню от константы тождественно равна нулю.

    Вопрос здесь УЖЕ: «какая дата в наборе самая новая» — на него отвечает канонический
    загрузчик `pendle_pt_history.load(path)`, и подбор рынка по TVL (дело
    `load_real_susde_history`) для него не нужен. Отсутствие набора — ТРЕТИЙ ИСХОД, а не
    ноль и не сегодняшняя дата."""
    _import_root()
    path = Path(pt_history)
    try:
        from spa_core.strategy_lab.rates_desk import pendle_pt_history as pph
    except Exception as exc:  # noqa: BLE001
        return {"measured": False,
                "reason": f"НЕ ИЗМЕРЕНО: загрузчик набора не ввезён — {type(exc).__name__}: {exc}"}
    try:
        deep = pph.load(path)
    except Exception as exc:  # noqa: BLE001
        return {"measured": False, "path": str(path),
                "reason": f"НЕ ИЗМЕРЕНО: набор не прочитан ({path}) — {type(exc).__name__}: {exc}"}
    dates: set = set()
    for mkt in (deep.get("markets") or {}).values():
        for pt in (mkt.get("series") or []):
            d = pt.get("date") if isinstance(pt, dict) else None
            if isinstance(d, str):
                dates.add(d)
    if not dates:
        return {"measured": False, "path": str(path),
                "reason": f"НЕ ИЗМЕРЕНО: в наборе {path} нет ни одной датированной точки "
                          f"(ключ `series` у рынков пуст или отсутствует)"}
    last = max(dates)
    try:
        last_d = datetime.date.fromisoformat(last)
    except ValueError as exc:
        return {"measured": False, "path": str(path),
                "reason": f"НЕ ИЗМЕРЕНО: дата {last!r} не разобрана: {exc}"}
    return {"measured": True, "path": str(path), "n_dates": len(dates),
            "first": min(dates), "last": last,
            "stale_days_vs_now": (now - last_d).days, "now": now.isoformat()}


# ── отчёт ────────────────────────────────────────────────────────────────────────────────

def parse_now(raw: Optional[str]) -> datetime.date:
    """Момент — ВХОД, а не окружение (ADR-897). Неразбираемое значение — ОТКАЗ, не часы."""
    if raw is None:
        return datetime.datetime.now(datetime.timezone.utc).date()
    try:
        return datetime.date.fromisoformat(raw.strip())
    except (ValueError, AttributeError) as exc:
        raise Unmeasured(f"--now {raw!r} не разобран как ISO-8601 date: {exc}") from exc


def print_report(rep: dict) -> None:
    c = rep["census"]
    print("=" * 94)
    print("  #154 FMP — Frozen-Mark Provenance   [L0 — замер артефакта, НЕ реализованный P&L]")
    print("  ИСПОЛНЕНИЕ ЗАКАЗА #152 / #153 п. 1 — ИСТОЧНИК МАРКИ по каждой из 10 книг")
    print("=" * 94)
    print(f"  данные: {c['data_dir']}   прочитано книг: {c['n_read']}/{c['n_books']}")
    print()
    print("── §1 ПЕРЕПИСЬ ИСТОЧНИКА МАРКИ (приёмка заказа) ───────────────────────────────────────")
    print(f"  {'книга':<19}{'стр':>4}{'объявл':>7}{'null':>6}{'объявл=0':>9}"
          f"{'≠0':>5}{'разл':>6}{'доля':>7}  вердикт")
    print(f"  {'-'*19}{'-'*4:>4}{'-'*7:>7}{'-'*6:>6}{'-'*9:>9}{'-'*5:>5}{'-'*6:>6}{'-'*7:>7}  {'-'*40}")
    for b in PANEL_BOOKS:
        s = c["books"].get(b)
        if s is None:
            continue
        def _n(v):
            return "  —" if v is None else f"{v}"
        frac = s.get("distinct_fraction")
        frac_s = "    —" if frac is None else f"{frac:5.3f}"
        print(f"  {b:<19}{_n(s['n_rows']):>4}{_n(s['n_declared']):>7}{_n(s['n_no_mark']):>6}"
              f"{_n(s['n_declared_zero']):>9}{_n(s['n_declared_nonzero']):>5}"
              f"{_n(s['distinct_declared']):>6}{frac_s:>7}  {s['verdict']}")
    print()
    print()
    print("  ОДНОДНЕВНЫЕ ЭКСКУРСИИ (ушло и вернулось следующей же сменой) — отпечаток ШАГА, не пути:")
    for b in PANEL_BOOKS:
        s2 = c["books"].get(b) or {}
        exc = s2.get("single_day_excursions") or []
        if exc:
            print(f"    {b:<19} {len(exc)}: " + ", ".join(
                f"{e['out']}→{e['back']} ({e['baseline']}→{e['value']}→{e['baseline']})"
                for e in exc[:4]))
    print()
    print(f"  НАБЛЮДЕНИЙ дневного пути среди 10 книг: {c['n_observed']}"
          f"  {c['observed_books'] or '(ни одной)'}")

    print()
    print("── §2 ПРИЧИНА, названная МЕХАНИЗМОМ кода ──────────────────────────────────────────────")
    cz = rep.get("causes")
    if not cz or not cz.get("measured", True):
        print(f"  {cz.get('reason') if cz else 'НЕ ИЗМЕРЕНО: раздел не запрошен'}")
    else:
        print(f"  сохраняемые якоря харнесса: {cz['persisted_anchor_keys']}")
        print(f"  {'книга':<19}{'крюк':>5}  {'якорь НЕ сохраняется':<22}"
              f"{'гасит марку':<14}{'ГАСИТ ГЕЙТ':<14}killed")
        print(f"  {'-'*19}{'-'*5:>5}  {'-'*22:<22}{'-'*14:<14}{'-'*14:<14}{'-'*6}")
        for b in PANEL_BOOKS:
            d = (cz.get("books") or {}).get(b)
            if d is None:
                continue
            print(f"  {b:<19}{('ДА' if d['has_mark_hook'] else 'нет'):>5}  "
                  f"{','.join(d['anchors_not_persisted']) or '—':<22}"
                  f"{(','.join(d['anchors_not_persisted_read_by_mark']) or '—'):<14}"
                  f"{(','.join(d['anchors_not_persisted_read_by_kill']) or '—'):<14}"
                  f"{d['killed_in_state']}")
        print()
        for b in PANEL_BOOKS:
            d = (cz.get("books") or {}).get(b) or {}
            if d.get("kill_reason_in_state"):
                print(f"    {b}: killed — {d['kill_reason_in_state']}")

    print()
    print("── §3 ОБЩИЙ ШАГ: день, в который марку сменили СРАЗУ несколько книг ───────────────────")
    steps = rep.get("shared_steps") or []
    if not steps:
        print("  таких дней нет")
    for s in steps:
        print(f"  {s['date']}  книг: {s['n_books']} {s['books']}")
        print(f"             вернулись к прежнему значению следующей же сменой: "
              f"{s['reverted_next_change'] or '—'}")

    print()
    print("── §4 exit_nav для панели (второй вопрос заказа) ──────────────────────────────────────")
    e = rep.get("exit_nav") or {}
    print(f"  {e.get('panel_exit_nav')}  существует: {e.get('panel_exit_nav_exists')}")
    print(f"  соседи, которые существуют: {e.get('neighbours_that_exist')}")

    print()
    print("── §5 ВОЗРАСТ ВХОДА МАРКИ ─────────────────────────────────────────────────────────────")
    st = rep.get("staleness") or {}
    if st.get("measured"):
        print(f"  набор PT: {st['n_dates']} датированных дней, {st['first']} … {st['last']}")
        print(f"  файл: {st['path']}")
        print(f"  «живое» значение тика = значение за {st['last']}; "
              f"возраст на {st['now']}: {st['stale_days_vs_now']} дней")
    else:
        print(f"  {st.get('reason', 'НЕ ИЗМЕРЕНО: раздел не запрошен')}")

    print()
    print("  ЧЕСТНЫЕ ОГОВОРКИ:")
    print("  (а) Все числа — [L0] замер артефакта forward-блока, НЕ реализованный P&L.")
    print("  (б) Прибор судит, является ли ОБЪЯВЛЕННЫЙ ряд наблюдением дневного пути, и НЕ")
    print("      судит ПРАВДИВОСТЬ отдельного дня: верно размеченный день он назовёт верным.")
    print("  (в) «Общий шаг» — КАНДИДАТ по двум признакам (совпадение дня у >= 3 книг и возврат")
    print("      к прежнему значению). Прибор печатает признаки, а не причину события.")
    print("  (г) Порог 0.5 ОБЪЯВЛЕН вверху модуля; доля напечатана у каждой книги, чтобы")
    print("      вердикт можно было перемерить любым другим порогом, не трогая прибор.")
    print("  (д) IS_ADVISORY=True · OUTSIDE_RISKPOLICY=True · живой трек не открывался.")
    print("=" * 94)


def build_report(data_dir: Path, repo_root: Path, *, now: datetime.date,
                 want_causes: bool = True, want_staleness: bool = True,
                 pt_history: Optional[Path] = None) -> dict:
    census = mark_source_census(data_dir)
    rep = {"census": census, "shared_steps": shared_step_days(census),
           "exit_nav": exit_nav_presence(repo_root, data_dir), "now": now.isoformat()}
    if want_causes:
        state_p = Path(data_dir) / "paper_state.json"
        state = None
        if state_p.is_file():
            try:
                state = json.loads(state_p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                state = None
        try:
            cz = code_causes(state)
            cz["measured"] = True
            rep["causes"] = cz
        except Unmeasured as exc:
            rep["causes"] = {"measured": False, "reason": f"НЕ ИЗМЕРЕНО: {exc}"}
    if want_staleness:
        rep["staleness"] = mark_input_staleness(
            now, pt_history or (Path(repo_root) / "data" / "rates_desk" / "pendle_pt_history.json"))
    return rep


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="#154 FMP — перепись источника марки forward-блока")
    ap.add_argument("--data-dir", default=None,
                    help="каталог панели (умолчание — data/aggressive_lab репозитория)")
    ap.add_argument("--repo-root", default=None, help="корень репозитория")
    ap.add_argument("--now", default=None,
                    help="момент замера, ISO-8601 (ВХОД, а не стенные часы)")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    ap.add_argument("--no-causes", action="store_true", help="не ввозить ростер (§2)")
    ap.add_argument("--no-staleness", action="store_true", help="не читать набор данных (§5)")
    ap.add_argument("--pt-history", default=None,
                    help="путь к набору Pendle PT (умолчание — <repo-root>/data/rates_desk/pendle_pt_history.json)")
    a = ap.parse_args(argv)

    repo_root = Path(a.repo_root) if a.repo_root else Path(__file__).resolve().parents[1]
    data_dir = Path(a.data_dir) if a.data_dir else repo_root / "data" / "aggressive_lab"
    try:
        now = parse_now(a.now)
        rep = build_report(data_dir, repo_root, now=now,
                           want_causes=not a.no_causes,
                           want_staleness=not a.no_staleness,
                           pt_history=Path(a.pt_history) if a.pt_history else None)
    except Unmeasured as exc:
        print(f"НЕ ИЗМЕРЕНО: {exc}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    else:
        print_report(rep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
