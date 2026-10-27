"""Перепись ПУСТОГО совета: когда советник сравнил книгу с самой собой (ADR-765).

Тень советника ADR-060 ведёт по книге append-only ленту вердиктов
(``allocation_rationale_history[_<book>].jsonl``), а слой отображения
(:mod:`spa_core.paper_trading.cio_brief`) превращает последнюю запись в прозу
для владельца. Замер 16.10 (заказ G764 п. 2 приказа «Portfolio CIO»):

===========  =========  =====  ================================  ==============
книга        записей    дней   target ТОЖДЕСТВЕННО равен current  с ногами
===========  =========  =====  ================================  ==============
conservative       138     72   0                                 134
balanced           725     45   706                               1
aggressive         725     45   707                               1
===========  =========  =====  ================================  ==============

У Balanced/Aggressive это не свойство рынка, а ПОСТРОЕНИЕ: ``hy_cycle.py`` и
``lp_cycle.py`` передают тени цель = УЖЕ РЕШЁННУЮ книгу дня (ADR-531), а на
повторном прогоне дня решения нет вовсе и целью становится держимое. Значит
``HOLD`` на этих лентах не есть вывод «держать правильно» — тени нечего было
взвешивать. У Conservative цель приходит от аллокатора и отличается от книги,
поэтому ноги есть на 68 днях из 72.

**Предмет переписи — не лента, а то, ОТЛИЧИМ ли этот случай у читателя.** Три
исхода обязаны быть различимы (инв. #17): взвешено · взвешено и выгода равна
нулю · взвешивать было нечего. Прибор только ЧИТАЕТ: он ничего не чинит, цель
не подставляет и ни одного гейта не трогает — подстановка цели для рукавов это
money-path и решение владельца.

Зачёт меряется ЗНАЧЕНИЕМ поля, а не подстрокой в прозе (ADR-333): слой
отображения обязан нести ``weighed`` и ``unchanged_days`` полями, и перепись
сверяет их со своим собственным замером по ленте.

LLM forbidden. Pure stdlib. Прибор ADVISORY.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from spa_core.monitoring.call_provenance import call_provenance
from spa_core.monitoring.call_provenance import describe as provenance_line
from spa_core.paper_trading.shadow_trigger_eval import load_history
from spa_core.utils.atomic import atomic_save
from spa_core.utils.observation import observed

#: Артефакт и его производитель — ОБЪЯВЛЕНИЕ, а не вывод из кода (ADR-154/158).
#: Сверяется с `findings_bridge.CENSUS_PRODUCT` и с конституцией
#: (`architecture/manifest.json`); перепись, добавленная мимо объявления,
#: краснеет, а не молчит.
ARTIFACT = "vacuous_advice_census.json"
PRODUCER = "spa_core/monitoring/vacuous_advice_census.py"

#: Корень дерева по умолчанию — своё, а не чужое.
_ROOT = Path(__file__).resolve().parents[2]

#: Книги, у которых есть своя лента. ``None`` — Conservative (исходное имя файла).
BOOKS: tuple[tuple[str, Optional[str]], ...] = (
    ("conservative", None),
    ("balanced", "balanced"),
    ("aggressive", "aggressive"),
)

#: Исходы одной записи ленты. ``unmeasured`` — ТРЕТИЙ исход, а не «не взвешено»:
#: запись схемы ``shadow-hist-v1`` не несёт ``gates`` вовсе, и выдать её за
#: пустой совет значило бы придумать наблюдение.
WEIGHED = "weighed"
SELF_COMPARED = "self_compared"
IMMATERIAL_DRIFT = "immaterial_drift"
RECORD_UNMEASURED = "unmeasured"

#: Названные причины «взвешивать было нечего». Причина — часть ответа: без неё
#: «ног нет» неотличимо от «цель не вычислялась».
REASON_SELF = "target_is_the_held_book"
REASON_DRIFT = "differences_below_material_leg"
REASON_POSITIONS_UNMEASURED = "positions_not_recorded"
REASON_GATES_UNMEASURED = "gates_not_recorded"

#: Находки переписи.
F_VACUITY_NOT_NAMED = "vacuity_not_named"
F_UNMEASURED_AS_FALSE = "unmeasured_passed_as_not_weighed"
F_STREAK_NOT_DECLARED = "streak_not_declared"
F_STREAK_OVERSTATED = "streak_overstated_in_days"


def classify_record(rec: dict) -> tuple[str, Optional[str]]:
    """Один исход записи + названная причина (``None`` только у ``weighed``).

    Порядок проверок намеренный: сперва спрашивается, записан ли вердикт гейтов
    вообще. Запись без ``gates`` — это «не измерено», и ответить по ней
    «советник ничего не взвесил» нельзя: мы не знаем, взвешивал ли он.
    """
    gates = rec.get("gates")
    if not isinstance(gates, dict) or not gates:
        return RECORD_UNMEASURED, REASON_GATES_UNMEASURED
    if "has_legs" not in gates:
        return RECORD_UNMEASURED, REASON_GATES_UNMEASURED
    if gates.get("has_legs"):
        return WEIGHED, None
    cur, tgt = rec.get("current_positions"), rec.get("target_positions")
    if not isinstance(cur, dict) or not isinstance(tgt, dict):
        return SELF_COMPARED if cur == tgt else IMMATERIAL_DRIFT, REASON_POSITIONS_UNMEASURED
    if cur == tgt:
        return SELF_COMPARED, REASON_SELF
    return IMMATERIAL_DRIFT, REASON_DRIFT


def _day_streak(records: List[dict]) -> tuple[Optional[int], Optional[str]]:
    """Серия неизменности, посчитанная в ДНЯХ. Третий исход назван причиной.

    Прежняя мера считала ЗАПИСИ и печатала слово «день»: лента Balanced пишется
    ≈16 раз за цикл, и владелец читал «323-й день подряд» на ленте возрастом
    45 дней — число больше её собственного возраста в 7 раз.
    """
    if not records:
        return None, "лента пуста"
    latest = records[-1]
    verdict, reasons = latest.get("verdict"), latest.get("reasons")
    run: List[dict] = [latest]
    for rec in reversed(records[:-1]):
        if rec.get("verdict") == verdict and rec.get("reasons") == reasons:
            run.append(rec)
        else:
            break
    days = {rec.get("cycle_date") for rec in run}
    if any(not isinstance(d, str) or not d for d in days):
        return None, ("у записи серии нет `cycle_date` — серия в ДНЯХ не "
                      "измерена (записей в серии {})".format(len(run)))
    return len(days), None


def measure_tape(records: List[dict]) -> dict:
    """Замер одной ленты: исходы по записям, по дням и серия в днях."""
    counts: Dict[str, int] = {WEIGHED: 0, SELF_COMPARED: 0,
                              IMMATERIAL_DRIFT: 0, RECORD_UNMEASURED: 0}
    reasons: Dict[str, int] = {}
    days_with_legs: set = set()
    all_days: set = set()
    for rec in records:
        outcome, reason = classify_record(rec)
        counts[outcome] = counts.get(outcome, 0) + 1
        if reason:
            reasons[reason] = reasons.get(reason, 0) + 1
        all_days.add(rec.get("cycle_date"))
        if outcome == WEIGHED:
            days_with_legs.add(rec.get("cycle_date"))
    streak_days, streak_why = _day_streak(records)
    latest_outcome, latest_reason = (
        classify_record(records[-1]) if records else (RECORD_UNMEASURED, "лента пуста"))
    return {
        "records": len(records),
        "days": len(all_days),
        "days_with_legs": len(days_with_legs),
        "outcomes": counts,
        "reasons": reasons,
        "streak_days": streak_days,
        "streak_unmeasured_reason": streak_why,
        "latest_outcome": latest_outcome,
        "latest_reason": latest_reason,
        "latest_cycle_date": records[-1].get("cycle_date") if records else None,
        "latest_generated_at": records[-1].get("generated_at") if records else None,
    }


def _default_brief_fn(data_dir: Path) -> dict:
    from spa_core.paper_trading.cio_brief import build_books_brief
    return build_books_brief(Path(data_dir))


def run_census(data_dir: Path,
               *,
               brief_fn: Optional[Callable[[Path], dict]] = None) -> dict:
    """Сверяет замер по ленте с тем, что выдача ОТДАЁТ читателю.

    ``brief_fn`` — ВХОД, а не окружение: положительный контроль обязан уметь
    подать выдачу ровно той формы, что была до починки (замер 16.10), иначе
    красную сторону проверки закрепить нечем.

    Возвращает ``measured=False`` с названной причиной, когда мерить нечего, —
    «не измерено» никогда не выдаётся ни за находку, ни за зачёт.
    """
    root = Path(data_dir)
    tapes: Dict[str, dict] = {}
    unreadable: Dict[str, str] = {}
    for name, book_id in BOOKS:
        try:
            records, _ = load_history(root, book_id=book_id)
        except BaseException as exc:  # noqa: BLE001 — причина обязана быть названа
            unreadable[name] = f"{type(exc).__name__}: {exc}"
            continue
        if not records:
            unreadable[name] = "лента книги пуста или не прочитана"
            continue
        tapes[name] = measure_tape(records)
    if not tapes:
        return {"measured": False,
                "reason": ("ни одна лента вердиктов не прочитана: "
                           + "; ".join(f"{b}: {r}" for b, r in sorted(unreadable.items()))),
                "unreadable": unreadable}

    try:
        payload = (brief_fn or _default_brief_fn)(root)
    except BaseException as exc:  # noqa: BLE001
        return {"measured": False,
                "reason": (f"слой отображения упал на этих данных "
                           f"({type(exc).__name__}: {exc}) — что доходит до "
                           f"владельца, НЕ измерено"),
                "tapes": tapes, "unreadable": unreadable}
    if not isinstance(payload, dict):
        return {"measured": False,
                "reason": (f"слой отображения вернул {type(payload).__name__}, "
                           f"а не словарь книг"),
                "tapes": tapes, "unreadable": unreadable}

    findings: List[dict] = []
    books: Dict[str, dict] = {}
    for name, tape in sorted(tapes.items()):
        brief: Any = payload.get(name)
        if not isinstance(brief, dict) or not brief.get("available"):
            books[name] = {"tape": tape, "brief_available": False}
            unreadable.setdefault(
                name, "выдача по книге недоступна — сверять поле не с чем")
            continue
        declared_weighed = brief.get("weighed", "__absent__")
        declared_reason = brief.get("not_weighed_reason")
        declared_days = brief.get("unchanged_days", "__absent__")
        expected_weighed = {WEIGHED: True, SELF_COMPARED: False,
                            IMMATERIAL_DRIFT: False,
                            RECORD_UNMEASURED: None}[tape["latest_outcome"]]

        if declared_weighed == "__absent__" or declared_weighed != expected_weighed:
            findings.append({
                "finding": (F_UNMEASURED_AS_FALSE
                            if (expected_weighed is None
                                and declared_weighed is not None
                                and declared_weighed != "__absent__")
                            else F_VACUITY_NOT_NAMED),
                "book": name,
                "detail": (
                    f"лента: {tape['latest_outcome']}"
                    f"{' (' + tape['latest_reason'] + ')' if tape['latest_reason'] else ''}"
                    f" ⇒ выдача обязана нести weighed={expected_weighed!r}, "
                    f"несёт {declared_weighed!r}"),
            })
        elif expected_weighed is not True and not declared_reason:
            findings.append({
                "finding": F_VACUITY_NOT_NAMED, "book": name,
                "detail": ("выдача объявила weighed={!r}, но ПРИЧИНУ не назвала — "
                           "«ног нет» неотличимо от «цель не вычислялась»"
                           .format(declared_weighed)),
            })

        if declared_days == "__absent__":
            findings.append({
                "finding": F_STREAK_NOT_DECLARED, "book": name,
                "detail": ("выдача не несёт `unchanged_days` полем — серию можно "
                           "сверить только подстрокой в прозе, а это не зачёт "
                           "(ADR-333)"),
            })
        elif tape["streak_days"] is None:
            if declared_days is not None:
                findings.append({
                    "finding": F_STREAK_OVERSTATED, "book": name,
                    "detail": ("серия в днях НЕ ИЗМЕРЕНА ({}) — выдача всё равно "
                               "объявила {!r}".format(tape["streak_unmeasured_reason"],
                                                      declared_days)),
                })
        elif not isinstance(declared_days, int) or isinstance(declared_days, bool) \
                or declared_days != tape["streak_days"]:
            findings.append({
                "finding": F_STREAK_OVERSTATED, "book": name,
                "detail": ("серия неизменности: лента даёт {} дн. (записей в ленте "
                           "{}, дней {}), выдача объявила {!r}"
                           .format(tape["streak_days"], tape["records"],
                                   tape["days"], declared_days)),
            })

        books[name] = {
            "tape": tape, "brief_available": True,
            "declared_weighed": None if declared_weighed == "__absent__" else declared_weighed,
            "declared_weighed_absent": declared_weighed == "__absent__",
            "declared_reason": declared_reason,
            "declared_unchanged_days": (None if declared_days == "__absent__"
                                        else declared_days),
        }

    measured_books = {b: d for b, d in books.items() if d.get("brief_available")}
    if not measured_books:
        return {"measured": False,
                "reason": ("ни по одной книге выдача не прочитана: "
                           + "; ".join(f"{b}: {r}" for b, r in sorted(unreadable.items()))),
                "books": books, "unreadable": unreadable}

    vacuous_records = sum(d["tape"]["outcomes"].get(SELF_COMPARED, 0)
                          + d["tape"]["outcomes"].get(IMMATERIAL_DRIFT, 0)
                          for d in measured_books.values())
    total_records = sum(d["tape"]["records"] for d in measured_books.values())
    return {
        "measured": True,
        "reason": None,
        "books": books,
        "unreadable": unreadable,
        "findings": findings,
        "books_measured": len(measured_books),
        "vacuous_records": vacuous_records,
        "records_total": total_records,
    }


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def measure(root: Path, *, now: Optional[dt.datetime] = None,
            brief_fn: Optional[Callable[[Path], dict]] = None) -> dict:
    """Документ артефакта: замер + происхождение зова + статус.

    Такта у этой переписи НЕТ намеренно: она читает три ленты и строит одну
    выдачу — цена зова измерима долями секунды, и гасить её тактом значило бы
    заплатить задержкой ответа за экономию, которой нет. Соседи с недельным
    тактом (`python_reader_clock_doors`, `artifact_stamp_clock_doors`) зовут
    сотню чужих производителей — это другой порядок цены.
    """
    report = run_census(root / "data", brief_fn=brief_fn)
    doc = {
        "generated_at": (now or _utcnow()).isoformat(),
        "generated_by": PRODUCER,
        "invoked_by": call_provenance(tree_root=root),
        "status": ("UNMEASURED" if not report.get("measured")
                   else ("FINDING" if report.get("findings") else "OK")),
        "reason": report.get("reason"),
        "books": report.get("books") or {},
        "findings": report.get("findings") or [],
        "books_measured": report.get("books_measured"),
        "records_total": report.get("records_total"),
        "vacuous_records": report.get("vacuous_records"),
        "unreadable": report.get("unreadable") or {},
        "what_it_does_not_prove": [
            "ПРАВ ли советник, когда ноги есть — перепись мерит только то, было ли "
            "что взвешивать и назван ли этот исход у читателя",
            "ПОЧЕМУ цель совпадает с книгой у рукавов — это свойство вызывающего "
            "(hy_cycle/lp_cycle передают решённую книгу дня, ADR-531), а не ленты",
            "читает ли выдачу живая поверхность владельца — здесь сверяется ТО, "
            "ЧТО ОНА ОТДАЁТ, а не то, кто её открыл",
        ],
    }
    return doc


def run(root: "str | Path" = _ROOT, *, dest: Optional[Path] = None,
        write: bool = True, now: Optional[dt.datetime] = None,
        brief_fn: Optional[Callable[[Path], dict]] = None) -> dict:
    """Ступень моста: позвать, записать артефакт, вернуть вердикт.

    `measured=False` — ТРЕТИЙ исход с названной причиной, а не тишина: ступень,
    промолчавшая о непрочитанной ленте, неотличима от ступени, которой не было.
    """
    root = Path(root)
    target = Path(dest) if dest is not None else root / "data" / ARTIFACT
    doc = measure(root, now=now, brief_fn=brief_fn)
    if write:
        atomic_save(doc, str(target))
    return {"measured": doc.get("status") != "UNMEASURED", "doc": doc,
            "artifact": str(target)}


def format_report(report: dict) -> str:
    """Одна печатная сводка — для шага 0-офис и для глаз.

    Принимает И документ артефакта (есть ключ ``status``), И прямой возврат
    :func:`run_census` (есть ключ ``measured``). Две формы одного замера жили бы
    двумя отрисовками, и одна из них непременно отстала бы от другой — читатель
    шага 0-офис получает ровно то, что печатает CLI.
    """
    # ЗВАВШИЙ печатается ДО раннего возврата намеренно: на документе
    # UNMEASURED вопрос «кто это позвал» не менее интересен, чем на
    # измеренном — именно так выглядел бы прогон, который ступень моста
    # завела, а стенд не построила. Тот же приём и та же причина, что у
    # `list_identity_census`. До ADR-825 этот отчёт умел ПОЖАЛОВАТЬСЯ на
    # отсутствие штампа (строкой шага 0-офис) и не умел его ПРОЧЕСТЬ:
    # замер ADR-822 назвал четыре таких производителя, этот — один из них.
    # `report()` у этого производителя нет вовсе: печатную сводку собирает
    # `format_report`, и она ОДНА строка (CLI печатает её `print`-ом, шаг
    # 0-офис разбирает `splitlines()`) — поэтому строка звавшего ЗДЕСЬ.
    caller = ("   [ЗВАВШИЙ] "
              f"{provenance_line(observed(report, 'invoked_by', kind=dict))}")
    if "status" in report:
        report = dict(report, measured=report.get("status") != "UNMEASURED")
    if not report.get("measured"):
        return "НЕ ИЗМЕРЕНО: " + str(report.get("reason")) + "\n" + caller
    lines = ["пустой совет (ADR-765): книг измерено {}, записей {}, из них "
             "пустых {}".format(report["books_measured"], report["records_total"],
                                report["vacuous_records"]), caller]
    for book, data in sorted((report.get("books") or {}).items()):
        tape = data.get("tape") or {}
        if not data.get("brief_available"):
            lines.append(f"   {book}: выдача недоступна — НЕ ИЗМЕРЕНО")
            continue
        out = tape.get("outcomes") or {}
        lines.append(
            "   {}: записей {} · дней {} · дней с ногами {} · сравнил сам с собой {} "
            "· дрейф ниже порога {} · не измерено {} · серия {} дн. · выдача: "
            "weighed={!r} ({}) unchanged_days={!r}".format(
                book, tape.get("records"), tape.get("days"), tape.get("days_with_legs"),
                out.get(SELF_COMPARED), out.get(IMMATERIAL_DRIFT),
                out.get(RECORD_UNMEASURED), tape.get("streak_days"),
                data.get("declared_weighed"), data.get("declared_reason"),
                data.get("declared_unchanged_days")))
    for f in report.get("findings") or []:
        lines.append("   [НАХОДКА/{}] {}: {}".format(f["finding"], f["book"], f["detail"]))
    if not report.get("findings"):
        lines.append("   ✅ у каждой книги исход совета назван полем, серия сверена в днях")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    import json
    import os

    ap = argparse.ArgumentParser(description="перепись пустого совета (ADR-765)")
    ap.add_argument("--data-dir", default=os.environ.get("SPA_DATA_DIR", "data"))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    report = run_census(Path(args.data_dir))
    print(json.dumps(report, ensure_ascii=False, indent=1, default=str)
          if args.json else format_report(report))
    if not report.get("measured"):
        return 2
    return 1 if report.get("findings") else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
