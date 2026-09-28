"""Критерий §49 `Architecture` приказа «Portfolio CIO»: существует ли владелец решения
на уровне ВСЕГО портфеля.

Критерий владельца звучит дословно так:

    **Architecture.** Portfolio-level decision owner существует.

Главное слово — **portfolio-level**. Цель §1 того же приказа сформулирована владельцем
как «максимизировать … доходность ВСЕГО ПОРТФЕЛЯ», поэтому вопрос не «есть ли
аллокатор» (есть) и не «решает ли кто-нибудь состав книги» (решают, ADR-251 насчитал
ПЯТЬ таких), а **покрывает ли чьё-то решение весь капитал системы**.

Разница между этим замером и ADR-251 существенна и названа вслух: ADR-251 спрашивал,
связывают ли три ограничения владельца У КАЖДОГО производителя цели, и мерил КНИГУ.
Здесь мерится ПОРТФЕЛЬ — объединение книг, — и единица измерения ДОЛЛАР, а не модуль.
Зелёный ответ соседа на свой вопрос ответом на этот не является.

## Две оси, и ни одна не заменяет другую

===== =============================== ==========================================
ось   вопрос                          чем меряется
===== =============================== ==========================================
A     какую долю ОБЩЕГО капитала      население книг — разбором дерева
      покрывает решение самого        (:mod:`~spa_core.monitoring.cio_target_producers`),
      широкого производителя?         капитал каждой книги — из живого ``data/``
B     существует ли модуль, который   разбор дерева: модуль, называющий ДВЕ и более
      видит ДВЕ и более книги и       книги, + приговор о происхождении
      РЕШАЕТ, а не описывает?         (``DECIDES`` / ``DESCRIBES`` / ``UNKNOWN``)
===== =============================== ==========================================

Ось A отвечает «сколько», ось B — «кто». Производитель, покрывающий 100 % капитала,
и межкнижный решатель — это одно и то же явление, увиденное с двух сторон; требовать
только одну сторону значило бы закрыть критерий на модуле, который читает три книги и
ничего не решает (`reporting/books_summary.py` — ровно такой), либо на книге, которая
сегодня случайно единственная непустая.

## Третий исход обязателен (инв. #17)

Население книг не разобрано, книга не прочитана, у книги нет числа капитала — это
**НЕ ИЗМЕРЕНО** с названной причиной, а не ноль и не «чисто». Ноль долларов у книги —
законное ЗНАЧЕНИЕ (книга пуста), и склеивать его с «файла нет» запрещено: именно на
этой склейке держался класс аварий 18.08 (ADR-129).

## Положительный контроль оси B

Проход, сломавшийся молча, не нашёл бы НИ ОДНОГО многокнижного модуля и объявил бы
«межкнижного решателя нет» — то есть изготовил бы верный на вид ответ из собственной
поломки. Поэтому многокнижные модули обязаны найтись: не нашлось ни одного ⇒ ось B
**НЕ ИЗМЕРЕНА**, громко, и её вердикт не применяется вовсе.

## Что этот замер НЕ утверждает

* **Что соответствие «производитель → книга» измерено.** Оно ОБЪЯВЛЕНО
  (``cio_target_producers.DECLARED_BOOKS``), и замер держит объявление с двух сторон:
  устаревшее объявление делает перепись производителей неполной (и тогда вердикт не
  выносится вовсе), а необъявленный производитель, который РЕШАЕТ, расширяет население
  книг — либо, если его артефакт назвать не удалось, тоже отменяет вердикт. Это защита
  объявления, а не его замена, и разница названа здесь вслух.
* **Что верны сами числа капитала.** Берётся объявленное книгой поле собственного
  капитала; прибор его не пересчитывает и не проверяет — предмет здесь ПОКРЫТИЕ, а не
  бухгалтерия книги.
* **Что portfolio-level владелец нужен.** Критерий — владельца, и замер отвечает на
  него фактом, а не советует архитектуру.

Прибор только ЧИТАЕТ: ни один порог, ни живой трек, ни RiskPolicy, ни стоп-кран не
трогаются. LLM запрещён. Только stdlib.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import ast
import json
import os
import pathlib
from datetime import datetime, timezone
from typing import Any

from spa_core.monitoring import cio_target_producers as producers
from spa_core.utils.observation import observed

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REPORT_REL = "data/cio_decision_owner.json"

OWNER_EXISTS = "OWNER_EXISTS"
PER_BOOK_ONLY = "PER_BOOK_ONLY"
UNMEASURED = "UNMEASURED"

#: Доля капитала, начиная с которой решение считается покрывающим ВЕСЬ портфель.
#: Единица, а не «почти единица»: критерий владельца про портфель целиком, и
#: 99 % — это книга, оставшаяся без владельца решения, а не округление.
_FULL_COVERAGE = 1.0

#: Допуск на арифметику с плавающей точкой при сравнении долей. Предметом не
#: является: доли складываются из долларов, и разойтись они могут только на
#: представление числа.
_EPS = 1e-9


# ───────────────────────────── ось A: капитал книги ───────────────────────────

def _book_capital(doc: Any) -> tuple[float | None, str]:
    """Капитал книги и ИМЯ поля, из которого он взят. ``None`` = наблюдения нет.

    Форм у книг две, и обе живые:

    * канонический трек — ``positions`` словарём ``{протокол: usd}`` рядом с
      ``current_equity_usd`` / ``capital_usd`` / ``cash_usd``;
    * рукава B/C — ``positions`` списком записей с ``notional_usd`` рядом с
      ``equity``.

    Число берётся из ОБЪЯВЛЕННОГО книгой поля собственного капитала, а не
    пересчитывается из позиций: пересчёт был бы вторым производителем того же
    числа, а их у нас и так больше, чем нужно. Поля нет ⇒ сумма позиций и кэша
    — но тогда имя источника говорит об этом прямо, чтобы читатель не принял
    выведенное число за объявленное.
    """
    for key in ("current_equity_usd", "equity", "capital_usd"):
        value = observed(doc, key, kind=(int, float))
        if value is not None:
            return float(value), key

    positions = observed(doc, "positions", kind=(dict, list))
    if positions is None:
        return None, "ни одного поля капитала и нет positions"

    total = 0.0
    if isinstance(positions, dict):
        for usd in positions.values():
            if not isinstance(usd, (int, float)) or isinstance(usd, bool):
                return None, "positions несёт нечисловую величину — не замер"
            total += float(usd)
    else:
        for row in positions:
            usd = observed(row, "notional_usd", kind=(int, float))
            if usd is None:
                return None, "позиция без notional_usd — капитал не наблюдён"
            total += float(usd)
    cash = observed(doc, "cash_usd", kind=(int, float))
    if cash is not None:
        total += float(cash)
    return total, "сумма positions" + (" + cash_usd" if cash is not None else "")


def _read_books(data_dir: pathlib.Path, artifacts: list[str]) -> tuple[dict, list[str]]:
    """Капитал каждой книги населения. Второй возврат — причины «не измерено»."""
    books: dict[str, dict] = {}
    unmeasured: list[str] = []
    for rel in artifacts:
        path = data_dir / pathlib.Path(rel).name
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            unmeasured.append(f"{rel}: не прочитана ({type(exc).__name__}: {exc})")
            continue
        usd, field = _book_capital(doc)
        if usd is None:
            unmeasured.append(f"{rel}: капитал не наблюдён ({field})")
            continue
        books[rel] = {"artifact": rel, "capital_usd": round(usd, 2),
                      "capital_field": field}
    return books, unmeasured


# ────────────────────── ось B: модуль, видящий ДВЕ и более книги ───────────────

def _multi_book_modules(root: str, artifacts: set[str]) -> tuple[list[dict], str]:
    """Модули рантайма, называющие ДВЕ и более книги, с приговором о роли.

    Признак «видит книгу» — имя файла книги строковым литералом в модуле. Признак
    грубый намеренно: ошибаться он обязан в сторону КАНДИДАТА (лишний кандидат
    попадёт под приговор о роли и отсеется там), а не в сторону тишины — тишина
    здесь и есть искомый ответ, поэтому дешеветь она не должна.

    Роль решает **сайт записи книги**, а не имя вызова, и причина прямая: решение,
    которого никто не записал, система не исполняет. Поэтому модуль, у которого
    сайта записи книги нет ВОВСЕ, владельцем решения быть не может — и это
    измерение, а не мнение о его назначении.

    ``DECIDES``   пишет книгу, и нагрузка происходит из решающего вызова;
    ``DESCRIBES`` пишет книгу, но нагрузка происходит из загрузки уже принятого;
    ``NO_WRITE``  сайта записи книги нет — решения не записывает никогда;
    ``UNKNOWN``   пишет книгу неустановленного происхождения, либо зовёт решающий
                  вызов, не записывая книгу сам. Третий исход: не находка и не
                  зачёт, а требование посмотреть — и если такой модуль видит ВСЕ
                  книги, вердикт оси B не выносится вовсе (fail-CLOSED).
    """
    names = {pathlib.Path(a).name for a in artifacts}
    by_name = {pathlib.Path(a).name: a for a in artifacts}
    found: list[dict] = []
    parse_failures: list[str] = []
    for rel, path in producers._iter_runtime_modules(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError) as exc:
            parse_failures.append(f"{rel}: {type(exc).__name__}: {exc}")
            continue
        literals = producers._string_constants(tree)
        seen_names = {pathlib.Path(s).name for s in literals
                      if pathlib.Path(s).name in names}
        if len(seen_names) < 2:
            continue
        writes = producers._book_shaped_writes(rel, tree, literals)
        called = {(n.func.attr if isinstance(n.func, ast.Attribute)
                   else getattr(n.func, "id", ""))
                  for n in ast.walk(tree) if isinstance(n, ast.Call)}
        decider_calls = sorted(called & set(producers._DECIDERS))
        if writes:
            provs = {w["provenance"] for w in writes}
            if "DECIDES" in provs:
                role, why = "DECIDES", sorted(
                    {o for w in writes if w["provenance"] == "DECIDES"
                     for o in (w.get("origin") or [])})
            elif "UNKNOWN" in provs:
                role, why = "UNKNOWN", ["происхождение нагрузки сайта записи не установлено"]
            else:
                role, why = "DESCRIBES", ["нагрузка происходит из уже принятого"]
        elif decider_calls:
            role, why = "UNKNOWN", [
                "зовёт решающий вызов (" + ", ".join(decider_calls)
                + "), но книгу не записывает — записывает ли её за него другой, не измерено"]
        else:
            role, why = "NO_WRITE", ["сайта записи книги нет — решение не записывает"]
        found.append({"module": rel, "role": role, "why": why,
                      "books": sorted(by_name[n] for n in seen_names)})
    reason = ""
    if parse_failures:
        reason = (f"{len(parse_failures)} модул(ь/я/ей) не разобрались "
                  f"({parse_failures[0]}) — проход частичный")
    return found, reason


# ───────────────────────────────── перепись ───────────────────────────────────

def run_census(data_dir: pathlib.Path | str,
               *,
               repo_root: pathlib.Path | str | None = None,
               now: datetime | None = None) -> dict:
    """Ответ на критерий §49 `Architecture`. Часы и каталоги — ВХОДЫ, не окружение.

    Возврат несёт ``measured`` (булево), ``reason`` (при ``False`` — причина
    словами) и, если измерено, ``verdict`` ∈ {``OWNER_EXISTS``, ``PER_BOOK_ONLY``}.
    """
    root = str(repo_root or REPO_ROOT)
    data_dir = pathlib.Path(data_dir)
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()

    enumeration = producers._enumerate_producers(root)
    if not enumeration["complete"]:
        return {"measured": False, "status": UNMEASURED, "generated_at": stamp,
                "reason": "перепись производителей цели неполна: "
                          + (enumeration["reason"] or "причина не названа")}

    # Население книг ВЫВЕДЕНО, а не взято списком из головы: объявленные книги
    # плюс артефакты необъявленных производителей, которые РЕШАЮТ. Необъявленный
    # решающий производитель, чей артефакт назвать не удалось, — третий исход:
    # он расширяет население неизвестно на сколько, и молчать об этом нельзя.
    scope: dict[str, set[str]] = {}
    for row in enumeration["declared"]:
        scope.setdefault(row["module"], set()).add(row["artifact"])
    unnamed = [w for w in enumeration["undeclared"] if not w.get("resolved")]
    if unnamed:
        return {"measured": False, "status": UNMEASURED, "generated_at": stamp,
                "reason": "необъявленный производитель РЕШАЕТ состав книги, а его "
                          "артефакт не назван: "
                          + ", ".join(f"{w['module']}:{w['line']}" for w in unnamed[:4])
                          + " — население книг неизвестно"}
    for w in enumeration["undeclared"]:
        for cand in w.get("artifact_candidates") or []:
            scope.setdefault(w["module"], set()).add(cand)

    artifacts = sorted({a for s in scope.values() for a in s})
    if not artifacts:
        return {"measured": False, "status": UNMEASURED, "generated_at": stamp,
                "reason": "население книг пусто — разбор дерева не назвал ни одной "
                          "книги, и это поломка прохода, а не ответ о системе"}

    books, book_unmeasured = _read_books(data_dir, artifacts)
    if book_unmeasured:
        return {"measured": False, "status": UNMEASURED, "generated_at": stamp,
                "reason": "капитал книги не наблюдён: " + "; ".join(book_unmeasured),
                "books_named": artifacts}

    total = sum(b["capital_usd"] for b in books.values())
    if total <= 0.0:
        return {"measured": False, "status": UNMEASURED, "generated_at": stamp,
                "reason": f"общий капитал портфеля {total} — доли неопределимы; "
                          "это не «покрытие 0 %», а отсутствие знаменателя",
                "books_named": artifacts}

    coverage = []
    for module in sorted(scope):
        covered = sorted(a for a in scope[module] if a in books)
        usd = sum(books[a]["capital_usd"] for a in covered)
        coverage.append({"producer": module, "books": covered,
                         "covered_usd": round(usd, 2),
                         "share": round(usd / total, 6)})
    # Шире всех — тот, чьё решение накрывает БОЛЬШЕ КНИГ; доллары разрешают
    # ничью. Порядок именно такой, и он не косметический: см. блок про пустую
    # книгу у `owner_by_scope` ниже.
    coverage.sort(key=lambda r: (-len(r["books"]), -r["share"]))
    widest = coverage[0]

    multi, multi_reason = _multi_book_modules(root, set(artifacts))
    if not multi:
        return {"measured": False, "status": UNMEASURED, "generated_at": stamp,
                "reason": "положительный контроль оси B не пройден: проход не нашёл "
                          "НИ ОДНОГО модуля, называющего две книги — при трёх живых "
                          "книгах это поломка прохода, а её вердикт «межкнижного "
                          "решателя нет» неотличим от настоящего ответа",
                "books_named": artifacts}

    cross_book_deciders = [m for m in multi if m["role"] == "DECIDES"
                           and set(m["books"]) >= set(books)]
    cross_book_unknown = [m for m in multi if m["role"] == "UNKNOWN"
                          and set(m["books"]) >= set(books)]
    if cross_book_unknown and not cross_book_deciders:
        return {"measured": False, "status": UNMEASURED, "generated_at": stamp,
                "reason": "ось B не выносит вердикт: модуль видит ВСЕ книги, а его "
                          "роль не установлена — "
                          + "; ".join(f"{m['module']} ({'; '.join(m['why'])})"
                                      for m in cross_book_unknown[:3])
                          + ". «Межкнижного решателя нет» здесь неотличимо от «не "
                            "разобрались, кто он», и выдавать одно за другое запрещено",
                "books_named": artifacts}
    # 🪤 Ловушка, на которой первая редакция этого прибора поймала сама себя.
    # Вердикт считался по ДОЛЯМ капитала — и на замороженной копии `data/`, где
    # две книги из трёх держат $0, доля канонического производителя вышла
    # 100.00 % при неизменившемся ответе системы: те две книги он не решает и
    # не решал. Ноль долларов у книги — законное ЗНАЧЕНИЕ («книга пуста»), а не
    # исчезновение книги из портфеля, и склеивать их запрещено (инв. #17).
    #
    # Поэтому вердикт выносит ПОКРЫТИЕ НАСЕЛЕНИЯ КНИГ (множество), а доллары
    # говорят, сколько капитала лежит вне этого решения. Так мера отвечает на
    # вопрос владельца дословно: владелец решения существует, если его решение
    # покрывает портфель, — а не если сегодня повезло с остатками.
    owner_by_scope = set(widest["books"]) >= set(books)
    verdict = OWNER_EXISTS if (owner_by_scope or cross_book_deciders) else PER_BOOK_ONLY

    return {
        "measured": True,
        "status": verdict,
        "verdict": verdict,
        "generated_at": stamp,
        "criterion": "§49 Architecture — Portfolio-level decision owner существует",
        "books": [books[a] for a in artifacts],
        "total_capital_usd": round(total, 2),
        "coverage": coverage,
        "widest_producer": widest["producer"],
        "widest_share": widest["share"],
        "widest_books": widest["books"],
        "books_out_of_scope": sorted(set(books) - set(widest["books"])),
        "widest_covered_usd": widest["covered_usd"],
        "uncovered_usd": round(total - widest["covered_usd"], 2),
        "multi_book_modules": multi,
        "cross_book_deciders": [m["module"] for m in cross_book_deciders],
        "axis_b_partial_reason": multi_reason,
        "numbers_unit": {"covered_usd": "USD", "share": "доля общего капитала (0..1)"},
    }


def _lines(report: dict) -> list[str]:
    if not report.get("measured"):
        return [f"владелец решения на уровне портфеля (§49 Architecture): "
                f"НЕ ИЗМЕРЕНО — {report.get('reason')}"]
    out = [
        f"владелец решения на уровне портфеля (§49 Architecture): {report['verdict']} · "
        f"книг {len(report['books'])} · капитал ${report['total_capital_usd']:,.2f}",
        f"[ОСЬ A] шире всех решает `{report['widest_producer']}`: книг "
        f"{len(report['widest_books'])} из {len(report['books'])}, "
        f"${report['widest_covered_usd']:,.2f} = {report['widest_share'] * 100:.2f}% "
        f"общего капитала; вне его решения ${report['uncovered_usd']:,.2f}"
        + (" · книги вне решения: " + ", ".join(report["books_out_of_scope"])
           if report["books_out_of_scope"] else ""),
    ]
    for row in report["coverage"]:
        out.append(f"[ПО ПРОИЗВОДИТЕЛЯМ] {row['producer']}: "
                   f"${row['covered_usd']:,.2f} = {row['share'] * 100:.2f}% "
                   f"· книги {', '.join(row['books']) or '—'}")
    for book in report["books"]:
        out.append(f"[КНИГА] {book['artifact']}: ${book['capital_usd']:,.2f} "
                   f"(поле `{book['capital_field']}`)")
    if report["cross_book_deciders"]:
        out.append("[ОСЬ B] межкнижный РЕШАТЕЛЬ найден: "
                   + ", ".join(report["cross_book_deciders"]))
    else:
        roles: dict[str, int] = {}
        for m in report["multi_book_modules"]:
            roles[m["role"]] = roles.get(m["role"], 0) + 1
        out.append(f"[ОСЬ B] межкнижного РЕШАТЕЛЯ нет: {len(report['multi_book_modules'])} "
                   f"модул(ь/я/ей) видят две и более книги, ни один не РЕШАЕТ "
                   f"(" + " · ".join(f"{k} {v}" for k, v in sorted(roles.items())) + ") — "
                   + ", ".join(f"{m['module']} ({m['role']})"
                               for m in report["multi_book_modules"][:6]))
    if report.get("axis_b_partial_reason"):
        out.append(f"[ЧАСТИЧНО] {report['axis_b_partial_reason']}")
    if report["verdict"] == PER_BOOK_ONLY:
        out.append("[НАХОДКА] критерий §49 `Architecture` НЕ ВЫПОЛНЕН: у каждой книги "
                   "свой решатель, портфель целиком не решает никто. Это ответ "
                   "замером, а не мнением, и он позеленеет сам, когда владелец "
                   "решения на уровне портфеля появится")
    out.append("ADVISORY: пороги RiskPolicy v1.0, стоп-кран, живой трек и книги НЕ "
               "трогаются — прибор только ЧИТАЕТ")
    return out


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", default=os.path.join(REPO_ROOT, "data"))
    ap.add_argument("--repo-root", default=REPO_ROOT)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)

    report = run_census(args.data_dir, repo_root=args.repo_root)
    for line in _lines(report):
        print(line)
    if not args.no_write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(report, os.path.join(args.repo_root, REPORT_REL))
    if not report.get("measured"):
        return 2
    return 1 if report["verdict"] == PER_BOOK_ONLY else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
