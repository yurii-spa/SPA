#!/usr/bin/env python3
"""Перепись §-ов ТЗ владельца «Portfolio CIO»: у какого § назван АДРЕС решения, у какого — нет.

Предмет — заказ G1055 п. 0, который стал исполнимым только после ADR-1066:
488 циклов карточку приказа **нельзя было прочитать** (3 273 543 символа), поэтому
«что из ТЗ закрыто» никто не называл ни разу. Карточка сжата 77,2×, ТЗ §1–§52 теперь
читается целиком — и первый же вопрос к нему («какие § закрыты, какие нет») до сих
пор отвечался ПРОЗОЙ сессий, которых уже нет.

Прибор не перечитывает прозу и ничего не чинит. Он спрашивает заново.

## Что он отвечает, и чего НЕ отвечает

**Отвечает:** у какого § ТЗ есть АДРЕС — строка реестра решений, назвавшая этот §
своим предметом. Это проверяемое свойство реестра, а не мнение о работе.

**НЕ отвечает:** исполнен ли §. «Адрес назван» и «§ закрыт» — ДВА разных
утверждения, и склеить их значило бы произвести ровно тот дефект, против которого
написано `.claude/rules/site-numbers.md`: перепечатанное число не отстаёт и не
расходится — оно молча перестаёт быть правдой. Прибор печатает это ограничение
вслух в каждом своём отчёте, а не в комментарии к коду.

## Двери

1. **Население — из самой карточки приказа**, не из списка в этом файле. «Пятьдесят
   два» здесь нигде не зашито: получи ТЗ владельца пятьдесят третий пункт, прибор
   ответит про пятьдесят три сам.

   Дверь — **ЦЕПЬ**, а не греп: принимается строка `^N. <текст>` ровно тогда, когда
   `N` есть следующий ожидаемый номер. Наивный греп по той же карточке даёт **80**
   кандидатов против 52 членов цепи (+54 %): внутри §51 владелец перечислил
   собственные пункты 1…14, и у них та же форма. Разница ПЕЧАТАЕТСЯ — иначе
   следующий читатель повторит наивную дверь и получит население, которого нет.

2. **Реестр решений СОСТАВНОЙ** — `INDEX.md` (живая часть) + `INDEX-ARCHIVE.md`
   (номера ≤ ADR-900, перенесены ADR-1046). Спросить одну часть значило бы объявить
   «адреса нет» у § , чей адрес уехал в архив. Непрочитанная часть — **третий
   исход** (`unmeasured`, fail-CLOSED), а не «адреса нет».

3. **Ось ХРОНИКИ объявлена НЕ ИЗМЕРЕННОЙ, и причина НАЗВАНА замером.** Архив хроники
   (`docs/journal/CARD-archive-portfolio-cio-chronicle-2026-11-19.md`, 374 записи
   цикла) упоминает `§N` тысячи раз — но символ `§` НЕ НАЗЫВАЕТ ДОКУМЕНТ: в той же
   прозе живут `ADR-980 § 6`, `§6 диагностики`, `CLAUDE.md §2.4`. Замер величины
   ошибки печатается прибором (`chronicle_ambiguity`) вместе с ХУДШИМ случаем:
   у `§6` из 238 строгих упоминаний 230 принадлежат РАЗДЕЛАМ ADR, а не §6 ТЗ.
   Поэтому хроника здесь — адрес для человека, а не ось замера.

## Исходы (инв. #17 — три, и они различимы)

* у § назван адрес (`addressed`, перечислены ADR-номера);
* адреса нет (`no_address`) — это НАЙДЕННОЕ, а не ошибка прибора;
* **НЕ ИЗМЕРЕНО** (`unmeasured`) с названной причиной: карточка не прочитана ·
  цепь §-ов не найдена · часть реестра не прочитана.

## Коды возврата

* **0** — население прочитано И у каждого § есть адрес.
* **1** — население прочитано, и у части §-ов адреса НЕТ (перечислены поимённо).
* **2** — переписи НЕТ ВОВСЕ (`unmeasured`): про §-ы не сказано НИЧЕГО, и выдать
  это за «чисто» нельзя.

ADVISORY: только читает. Ни строки risk-логики, стоп-крана, аллокатора, живого
трека или `landing/**`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

CARD_REL = "nimbalyst-local/tracker/inbox-task-portfolio-cio-dynamic-capital-alloc.md"
REGISTER_PARTS = ("docs/decisions/INDEX.md", "docs/decisions/INDEX-ARCHIVE.md")
CHRONICLE_REL = "docs/journal/CARD-archive-portfolio-cio-chronicle-2026-11-19.md"

#: Граница хвоста ТЗ: любой markdown-заголовок (`## Приоритет…`, `### Заказ…`).
MARKDOWN_HEADER_RE = re.compile(r"^#{1,6}\s")

#: Заголовок §-а ТЗ владельца: номер, точка, пробел, непустой текст.
SECTION_LINE_RE = re.compile(r"^(\d{1,2})\.\s+(\S.*)$")

#: `§N` или `§ N`, и НЕ `§N.M` (`CLAUDE.md §2.4` — чужой документ).
SECTION_REF_RE = re.compile(r"§\s?(\d{1,2})(?![\d.])")

#: `§A…§B` / `§A–B` — притязание на ДИАПАЗОН §-ов.
SECTION_RANGE_RE = re.compile(r"§\s?(\d{1,2})\s?[…\-–—]+\s?§?\s?(\d{1,2})(?![\d.])")

ADR_RE = re.compile(r"ADR-(\d{3,4})")

#: Артефакт, НАЗВАННЫЙ владельцем внутри §: `PORTFOLIO_CIO_AS_IS.md`.
#: Форма узкая намеренно: ЗАГЛАВНЫЕ с подчёркиваниями — так владелец называет
#: документ-поручение. Строчное имя (`docs/37`) — ссылка на чужой документ, а не
#: поручение, и зачесть её поручением значило бы выдумать требование.
NAMED_ARTIFACT_RE = re.compile(r"\b([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\.md)\b")

#: `ADR-980 § 6` — § принадлежит РАЗДЕЛУ решения, не ТЗ владельца.
ADR_OWNED_PREFIX_RE = re.compile(r"ADR-\d{3,4}\s*$")

ADDRESSED = "addressed"
NO_ADDRESS = "no_address"
UNMEASURED = "unmeasured"


class NotMeasured(Exception):
    """Переписи нет вовсе: причина названа, нулём это не считается."""


def _read(root: str, rel: str) -> str:
    path = os.path.join(root, rel)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        raise NotMeasured(f"{rel} не прочитан: {exc}") from exc


def section_population(card_text: str) -> tuple:
    """Население §-ов ТЗ — ЦЕПЬ, и рядом замер наивной двери.

    Возвращает ``(sections, naive_count)``, где ``sections`` — список записей
    ``{"section", "title", "line", "body"}`` в порядке цепи. Цепь принимает строку
    только когда её номер есть СЛЕДУЮЩИЙ ожидаемый: так вложенные перечисления
    владельца (§51 содержит собственные 1…14) не становятся §-ами ТЗ.
    """
    naive = 0
    sections = []
    expected = 1
    lines = card_text.splitlines()
    for index, line in enumerate(lines):
        match = SECTION_LINE_RE.match(line)
        if not match:
            continue
        naive += 1
        number = int(match.group(1))
        if number == expected:
            sections.append({
                "section": number,
                "title": match.group(2).strip(),
                "line": index + 1,
            })
            expected += 1
    if not sections:
        raise NotMeasured(
            "цепь §-ов ТЗ не найдена в карточке приказа — населения нет, "
            f"наивных кандидатов {naive}"
        )
    for position, entry in enumerate(sections):
        start = entry["line"]
        if position + 1 < len(sections):
            end = sections[position + 1]["line"] - 1
        else:
            # У ПОСЛЕДНЕГО § соседа нет, и «до конца файла» было бы неверно: ниже ТЗ
            # в карточке живут заказы и пост-записи циклов, а они владельцем не
            # писаны. Хвост кончается на ПЕРВОМ markdown-заголовке после §: иначе
            # поручение, названное в заказе, зачлось бы последнему § ТЗ (замер
            # 19.11: `PORTFOLIO_CIO_AS_IS.md` из заказа G1056 попал §52).
            end = len(lines)
            for offset in range(start, len(lines)):
                if MARKDOWN_HEADER_RE.match(lines[offset]):
                    end = offset
                    break
        entry["body"] = "\n".join(lines[start:end])
    return sections, naive


def register_addresses(root: str) -> tuple:
    """Адреса §-ов из СОСТАВНОГО реестра решений.

    Возвращает ``(exact, ranged, parts_read)``: номер § → множество ADR-номеров,
    назвавших его точно, и отдельно — назвавших ДИАПАЗОН, в который он входит.
    Диапазон держится отдельной осью намеренно: «ADR про §12…§23» слабее строки
    «ADR про §17», и слить их значило бы зачесть адрес, которого нет.

    Непрочитанная часть реестра — :class:`NotMeasured` (fail-CLOSED): «адреса
    нет» и «мы не смотрели туда, где он лежит» — разные ответы.
    """
    exact: dict = {}
    ranged: dict = {}
    parts_read = []
    for rel in REGISTER_PARTS:
        text = _read(root, rel)  # NotMeasured пробрасывается наверх
        parts_read.append(rel)
        for line in text.splitlines():
            adrs = set(ADR_RE.findall(line))
            if not adrs:
                continue
            consumed = []
            for match in SECTION_RANGE_RE.finditer(line):
                low, high = int(match.group(1)), int(match.group(2))
                consumed.append(match.span())
                if low <= high:
                    for number in range(low, high + 1):
                        ranged.setdefault(number, set()).update(adrs)
            for match in SECTION_REF_RE.finditer(line):
                if any(start <= match.start() < end for start, end in consumed):
                    continue
                exact.setdefault(int(match.group(1)), set()).update(adrs)
    return exact, ranged, parts_read


def chronicle_ambiguity(root: str) -> dict:
    """ПОЧЕМУ ось хроники не является осью: замер неоднозначности символа `§`.

    Отсутствие хроники — не отказ прибора: это слепота ОДНОЙ оси, и она
    объявлена. Возвращается ``reason`` плюс, когда файл прочитан, числа
    «упоминаний всего» / «принадлежат РАЗДЕЛАМ ADR» — величина ошибки, которую
    сделал бы наивный греп.
    """
    try:
        text = _read(root, CHRONICLE_REL)
    except NotMeasured as exc:
        return {"measured": False, "reason": str(exc)}
    total = 0
    adr_owned = 0
    per_section: dict = {}
    for match in SECTION_REF_RE.finditer(text):
        total += 1
        number = int(match.group(1))
        seen, owned = per_section.get(number, (0, 0))
        if ADR_OWNED_PREFIX_RE.search(text[max(0, match.start() - 16):match.start()]):
            adr_owned += 1
            owned += 1
        per_section[number] = (seen + 1, owned)
    worst = max(per_section.items(), key=lambda item: item[1][1], default=None)
    return {
        "measured": False,
        "reason": (
            "символ «§» не называет документ: в той же прозе живут разделы ADR "
            "и чужих документов — ось хроники осью замера не является"
        ),
        "refs_total": total,
        "refs_owned_by_adr_sections": adr_owned,
        "worst_section": None if worst is None else {
            "section": worst[0], "refs": worst[1][0], "owned_by_adr": worst[1][1],
        },
    }


def tree_basenames(root: str) -> set:
    """Имена всех файлов дерева — чтобы спросить «такой документ существует?».

    Дерево обходится целиком, кроме `.git`: поручение владельца могло быть
    исполнено в любом каталоге, и искать его только в `docs/` значило бы
    получить «нет» от своей двери, а не от дерева.
    """
    names = set()
    for _, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__")]
        names.update(files)
    return names


def _import_deliverable_door():
    """Ввоз прибора §6 ОТДЕЛЬНОЙ дверью — чтобы сцена могла его отнять.

    Без этой двери исход «инструмента нет» не поставить ни одной пробой, и
    мутация «не ввезён ⇒ объявить ИСПОЛНЕННЫМ» выживала (замер цикла #1211,
    M16): fail-OPEN тише красного теста, поэтому опаснее.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    import cio_as_is_deliverable as door
    return door


def deliverable_axis(root: str) -> dict:
    """Ось ИСПОЛНЕНИЯ §6 — вопрос, на который эта перепись отвечать НЕ МОЖЕТ.

    Перепись мерит РЕЕСТР решений и честно печатает свою слепоту («адрес назван» НЕ
    ЕСТЬ «§ исполнен»). У §6 следующий вопрос задаёт отдельный прибор
    `scripts/cio_as_is_deliverable.py` (ADR-1069): существует ли названный владельцем
    документ, несёт ли он ВСЕ ШЕСТЬ названных разделов и есть ли у каждого якорь
    замера, чей путь существует.

    Прибор не ввезён ⇒ **НЕ ИЗМЕРЕНО** с названной причиной, а не «исполнен» и не
    «не исполнен»: отсутствие инструмента есть самостоятельный третий исход
    (`.claude/rules/deployment.md`, дословный урок `pyflakes`).
    """
    try:
        door = _import_deliverable_door()
    except Exception as exc:  # noqa: BLE001
        return {"measured": False, "section": 6,
                "reason": f"прибор исполнения §6 не ввезён: {exc}"}
    try:
        report = door.audit(root)
    except door.NotMeasured as exc:
        return {"measured": False, "section": 6, "reason": str(exc)}
    return {"measured": True, "section": 6, "status": report["status"],
            "doc": report.get("doc"), "why": report["why"]}


def census(root: str) -> dict:
    """Перепись целиком. :class:`NotMeasured` — единственный путь к коду 2."""
    card_text = _read(root, CARD_REL)
    sections, naive = section_population(card_text)
    exact, ranged, parts_read = register_addresses(root)
    basenames = tree_basenames(root)

    rows = []
    for entry in sections:
        number = entry["section"]
        adrs_exact = sorted(exact.get(number, ()), key=int)
        adrs_ranged = sorted(ranged.get(number, ()), key=int)
        named = sorted(set(NAMED_ARTIFACT_RE.findall(entry["body"])))
        rows.append({
            "section": number,
            "title": entry["title"],
            "verdict": ADDRESSED if (adrs_exact or adrs_ranged) else NO_ADDRESS,
            "adr_exact": adrs_exact,
            "adr_range_only": [] if adrs_exact else adrs_ranged,
            "named_artifacts": named,
            "named_artifacts_missing": [name for name in named if name not in basenames],
        })

    unaddressed = [row["section"] for row in rows if row["verdict"] == NO_ADDRESS]
    return {
        "measured": True,
        "population": len(rows),
        "naive_candidates": naive,
        "register_parts_read": parts_read,
        "addressed": len(rows) - len(unaddressed),
        "no_address": len(unaddressed),
        "no_address_sections": unaddressed,
        "range_only": [row["section"] for row in rows if row["adr_range_only"]],
        "named_artifacts_missing": {
            str(row["section"]): row["named_artifacts_missing"]
            for row in rows if row["named_artifacts_missing"]
        },
        "chronicle_axis": chronicle_ambiguity(root),
        "deliverable_axis": deliverable_axis(root),
        "sections": rows,
        "blindness": (
            "«адрес назван» НЕ ЕСТЬ «§ исполнен»: прибор мерит реестр решений, "
            "а не работу. Исполнение § судит его собственная проба приёмки."
        ),
    }


def render(report: dict) -> str:
    lines = [
        "ПЕРЕПИСЬ §-ов ТЗ владельца «Portfolio CIO» — у какого § назван АДРЕС решения",
        f"  население (ЦЕПЬ): {report['population']} §  ·  "
        f"наивный греп дал бы {report['naive_candidates']} "
        f"(+{report['naive_candidates'] - report['population']})",
        f"  реестр прочитан частями: {', '.join(report['register_parts_read'])}",
        f"  адрес назван: {report['addressed']}  ·  адреса НЕТ: {report['no_address']}",
    ]
    if report["range_only"]:
        lines.append(
            "  только ДИАПАЗОНОМ (слабее строки про сам §): "
            + ", ".join(f"§{n}" for n in report["range_only"])
        )
    chronicle = report["chronicle_axis"]
    lines.append(f"  ось ХРОНИКИ: НЕ ИЗМЕРЕНО — {chronicle['reason']}")
    if "refs_total" in chronicle:
        lines.append(
            f"     величина ошибки наивной двери: упоминаний «§N» {chronicle['refs_total']}, "
            f"из них принадлежат РАЗДЕЛАМ ADR {chronicle['refs_owned_by_adr_sections']}"
        )
        worst = chronicle.get("worst_section")
        if worst:
            lines.append(
                f"     худший случай — «§{worst['section']}»: {worst['refs']} упоминаний, "
                f"из них {worst['owned_by_adr']} суть РАЗДЕЛ решения, а не § ТЗ"
            )
    if report["named_artifacts_missing"]:
        lines.append("  § НАЗВАЛ ДОКУМЕНТ, которого в дереве НЕТ:")
        for number, names in sorted(report["named_artifacts_missing"].items(), key=lambda i: int(i[0])):
            lines.append(f"     §{number} → {', '.join(names)}")
    else:
        lines.append("  названные §-ами документы: все существуют в дереве")
    if report["no_address_sections"]:
        lines.append("  §-ы БЕЗ АДРЕСА (поимённо):")
        by_number = {row["section"]: row for row in report["sections"]}
        for number in report["no_address_sections"]:
            lines.append(f"     §{number} — {by_number[number]['title']}")
    axis = report.get("deliverable_axis") or {}
    if not axis:
        pass
    elif not axis.get("measured"):
        lines.append(f"  ось ИСПОЛНЕНИЯ §6: НЕ ИЗМЕРЕНО — {axis.get('reason')}")
    elif axis.get("status") == "satisfied":
        lines.append(f"  ось ИСПОЛНЕНИЯ §6: ✅ исполнен — {axis.get('doc')}")
    else:
        lines.append(f"  ось ИСПОЛНЕНИЯ §6: ❌ НЕ исполнен — "
                     + "; ".join(axis.get("why") or ["причина не названа"]))
    lines.append(f"  ⚠️ {report['blindness']}")
    lines.append(
        "  ✅ у каждого § есть адрес" if not report["no_address_sections"]
        else f"  🔎 НАХОДКА: §-ов без адреса — {report['no_address']}"
    )
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="перепись §-ов ТЗ приказа «Portfolio CIO»: у какого § назван "
                    "АДРЕС решения, у какого — нет"
    )
    parser.add_argument(
        "--repo-root",
        default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        help="дерево, о котором отвечает перепись (умолчание — дерево этого файла; "
             "выбор ПЕЧАТАЕТСЯ)",
    )
    parser.add_argument("--json", action="store_true", help="машинный отчёт в stdout")
    args = parser.parse_args(argv)

    root = os.path.abspath(args.repo_root)
    try:
        report = census(root)
    except NotMeasured as exc:
        payload = {"measured": False, "reason": str(exc), "repo_root": root}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"❌ НЕ ИЗМЕРЕНО ({root}): {exc}", file=sys.stderr)
        return 2

    report["repo_root"] = root
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=sorted))
    else:
        print(f"дерево: {root}")
        print(render(report))
    return 1 if report["no_address_sections"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
