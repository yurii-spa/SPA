"""Колонка «Заголовок» реестра решений есть ЗАГОЛОВОК, а не пересказ (ADR-840).

**Что измерено 2026-10-28 (цикл #961, заказ G839 п. 2).** ADR-838 поставил предел на колонку
(200 символов, якорь измерен) и честно сказал вслух: рост остановлен, СОСТОЯНИЕ оставлено —
673 строки долга и 1 574 806 символов цены чтения у файла, который `CLAUDE.md` §«Протокол
сессии» делает обязательным чтением КАЖДОЙ сессии. Этот цикл состояние убрал.

| | до | после |
|---|---|---|
| цена чтения `docs/decisions/INDEX.md` | 1 574 973 символа | **136 610** (11,5×) |
| максимум колонки «Заголовок» | 8 370 | **188** |
| медиана колонки | 1 902 | **88** |
| строк длиннее предела | 675 из 691 | **0** |

**Откуда взялся новый заголовок.** Из строки `H1` файла решения, на который ссылается
ЧЕТВЁРТАЯ колонка той же строки, — тот же принцип, что у статуса (`declared_status`,
ADR-831): источник правды о решении есть решение. Выдумывать, обрезать по многоточию или
брать первую строку абзаца ЗАПРЕЩЕНО (`docs/37`): нет файла, нет `H1`, `H1` сам длиннее
предела ⇒ третий исход с названной причиной (инв. #17). Отказов на живом реестре — **0**.

**Почему сокращение потребовало АРХИВА.** Проза строки реестра в файле решения не лежит:
замер 28.10 — из 675 толстых строк первые 80 символов колонки найдены в тексте своего же
решения лишь у **96 (14,2 %)**. То есть это ПЕРЕНОС, а не удаление дубля, и без дословного
снимка (`docs/journal/INDEX-archive-*.md`) проза 579 строк была бы потеряна МОЛЧА — ровно
то, против чего `.claude/rules/site-copy.md` §«Память ДО правки».

**Вторая находка цикла: у реестра было ДВА разбора строки, и второй занижал длину.** Храповик
цены чтения (ADR-838) мерил колонку своим `line.strip("|").split("|")`, а markdown считает
`\\|` литеральной чёрточкой ВНУТРИ ячейки — ею же ADR-831 починил 185 строк. Разборы расходятся
на **21** строке живого реестра, и на **18** наивный отвечает КОРОЧЕ ячейки: у `ADR-831` —
163 символа против **2 089**, у `ADR-611` — 200 против **509**. Обе строки проходили предел,
не будучи в нём, и в базу долга поэтому не попали. Ещё на трёх строках наивный разбор выдумывал
ключ (`ADR-067 (дубль)`), то есть база сторожила ключи, которых канонический реестр не знает.
Дверь теперь ОДНА — `scripts/adr_number.py::register_title_rows`.

Каждый тест ниже — положительный контроль измеренного поведения, а не украшение
(`.claude/rules/deployment.md`, «проверка сторожа сторожей»): на целом контуре он зелен, на
каждом порванном звене — красен, и ни один не проходит подстрокой.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, mod)
    spec.loader.exec_module(mod)
    return mod


adr = _load("adr_number_titles_under_test", "scripts/adr_number.py")

HEAD = (
    "# ADR INDEX\n\n"
    "| ADR | Заголовок | Статус | Файл |\n"
    "|---|---|---|---|\n"
)
FAT = "пересказ решения на много символов, " * 20          # заведомо длиннее предела


def _scene(tmp_path: Path, rows: str, decisions: dict[str, str]) -> Path:
    """Одноразовое дерево со своим реестром и своими файлами решений."""
    (tmp_path / "docs" / "decisions").mkdir(parents=True)
    (tmp_path / "docs" / "decisions" / "INDEX.md").write_text(HEAD + rows, encoding="utf-8")
    for name, text in decisions.items():
        (tmp_path / "docs" / "decisions" / name).write_text(text, encoding="utf-8")
    return tmp_path


# ── заголовок БЕРЁТСЯ у решения, а не выдумывается ───────────────────────────

def test_the_new_title_is_the_h1_of_the_decision_file(tmp_path):
    """Заголовок строки — проекция решения; источник правды о заголовке есть сам файл."""
    p = tmp_path / "ADR-900-x.md"
    p.write_text("<!-- шапка -->\n\n# ADR-900 · Короткий честный заголовок\n\nтекст\n",
                 encoding="utf-8")
    title, reason = adr.title_from_decision(p)
    assert (title, reason) == ("ADR-900 · Короткий честный заголовок", None)


def test_a_decision_without_an_h1_is_the_third_outcome_not_a_guess(tmp_path):
    """`H1` в файле нет ⇒ НЕ ИЗМЕРЕНО с причиной, а не «первая строка абзаца» (инв. #17)."""
    p = tmp_path / "ADR-901-x.md"
    p.write_text("## подзаголовок\n\nпроза, которая могла бы стать заголовком\n",
                 encoding="utf-8")
    title, reason = adr.title_from_decision(p)
    assert title is None
    assert reason and "нет строки `H1`" in reason


def test_an_unreadable_decision_is_named_and_not_silently_skipped(tmp_path):
    """Файла нет ⇒ причина НАЗВАНА. Пустая строка совпала бы с «заголовок пуст»."""
    title, reason = adr.title_from_decision(tmp_path / "ADR-902-missing.md")
    assert title is None
    assert reason and "не читается" in reason


def test_an_empty_h1_is_refused_too(tmp_path):
    """`# ` без текста — не заголовок. Иначе ячейка опустела бы «успешно»."""
    p = tmp_path / "ADR-903-x.md"
    p.write_text("# \n\nтекст\n", encoding="utf-8")
    title, reason = adr.title_from_decision(p)
    assert title is None and reason and "пуст" in reason


# ── правка АДРЕСНАЯ: меняется ровно одна ячейка ──────────────────────────────

def test_shorten_replaces_only_the_title_cell():
    """Статус и ссылка на файл переносятся ПОБАЙТОВО — иначе сокращение переписало бы статус."""
    line = f"| ADR-904 | {FAT} | 2026-10-28 · принято | [ADR-904](ADR-904-x.md) |"
    new, reason = adr.shorten_line(line, "Короткий заголовок")
    assert new and not reason
    cols = adr.row_columns(new)
    assert cols == ["ADR-904", "Короткий заголовок", "2026-10-28 · принято",
                    "[ADR-904](ADR-904-x.md)"]
    assert "| 2026-10-28 · принято |" in new and "[ADR-904](ADR-904-x.md)" in new


def test_shorten_refuses_an_h1_that_is_itself_longer_than_the_limit():
    """Прибор не вправе обрезать ЗАГОЛОВОК РЕШЕНИЯ: это правка решения, а не реестра."""
    line = f"| ADR-905 | {FAT} | Accepted | [ADR-905](ADR-905-x.md) |"
    new, reason = adr.shorten_line(line, "я" * 201)
    assert new is None
    assert reason and "сокращать ЗАГОЛОВОК РЕШЕНИЯ" in reason


def test_shorten_refuses_a_row_outside_the_declared_form():
    """Строка вне формы — предмет ADR-830/831. Чужой сторож её не «починит» заодно."""
    new, reason = adr.shorten_line("| ADR-906 | заголовок | 2026-10-28 |", "Заголовок")
    assert new is None
    assert reason and "не в объявленной форме" in reason


def test_a_pipe_inside_the_h1_is_escaped_and_the_row_stays_in_form():
    """Чёрточка в `H1` обязана быть экранирована — иначе заголовок РАЗДЕЛИЛ бы строку.

    Это та же авария, что ADR-831 чинил у 185 строк, только с другой стороны: не читатель
    не видел экранов, а писатель их не поставил.
    """
    line = f"| ADR-907 | {FAT} | Accepted | [ADR-907](ADR-907-x.md) |"
    new, reason = adr.shorten_line(line, "Шаблон `a|b` в заголовке")
    assert new and not reason, reason
    cols = adr.row_columns(new)
    assert len(cols) == 4, f"строка вышла из формы: {cols}"
    assert cols[1] == "Шаблон `a\\|b` в заголовке"


# ── контроль сокращения отвечает в ОБЕ стороны ───────────────────────────────

ORIG = "| ADR-908 | длинный пересказ | Accepted | [ADR-908](ADR-908-x.md) |"


def test_verify_shorten_is_quiet_on_an_honest_shortening():
    """Обратная сторона отказов ниже: честная правка проходит молча.

    Без этой половины отказы были бы неотличимы от сторожа, который краснеет всегда.
    """
    assert adr.verify_shorten(
        ORIG, "| ADR-908 | Заголовок | Accepted | [ADR-908](ADR-908-x.md) |") == ""


@pytest.mark.parametrize("new_line, expect", [
    ("| ADR-908 | Заголовок | Superseded | [ADR-908](ADR-908-x.md) |", "статус изменился"),
    ("| ADR-908 | Заголовок | Accepted | [ADR-908](ADR-999-y.md) |", "ячейка файла изменилась"),
    ("| ADR-909 | Заголовок | Accepted | [ADR-908](ADR-908-x.md) |", "номер изменился"),
    ("| ADR-908 |  | Accepted | [ADR-908](ADR-908-x.md) |", "новый заголовок пуст"),
    ("| ADR-908 | " + "я" * 201 + " | Accepted | [ADR-908](ADR-908-x.md) |",
     "символов при пределе"),
    ("| ADR-908 | Заголовок | Accepted |", "не в форме"),
])
def test_verify_shorten_refuses_every_forbidden_change(new_line, expect):
    """Каждое звено порвано отдельно — и каждое названо своей причиной, а не общим «нет»."""
    bad = adr.verify_shorten(ORIG, new_line)
    assert bad and expect in bad, f"ожидалась причина «{expect}», получено «{bad}»"


# ── реестр ЦЕЛИКОМ: три исхода различимы ─────────────────────────────────────

def test_shorten_index_shortens_the_fat_row_and_leaves_the_short_one(tmp_path):
    """«Уже в пределе» — это «измерено и равно», а не находка: строка не трогается."""
    root = _scene(
        tmp_path,
        f"| ADR-910 | {FAT} | Accepted | [ADR-910](ADR-910-x.md) |\n"
        "| ADR-911 | Короткий | Accepted | [ADR-911](ADR-911-x.md) |\n",
        {"ADR-910-x.md": "# ADR-910 · Взятый из решения заголовок\n",
         "ADR-911-x.md": "# ADR-911 · Другой заголовок\n"})
    rep = adr.shorten_index(root)
    assert rep["measured"] and not rep["refused"], rep
    assert [r["key"] for r in rep["shortened"]] == ["910"]
    assert [r["key"] for r in rep["already"]] == ["911"]
    assert rep["chars_after"] < rep["chars_before"]
    text = (root / "docs/decisions/INDEX.md").read_text(encoding="utf-8")
    assert FAT.strip() in text, "прибор НЕ ПИШЕТ сам — запись решает CLI"


def test_shorten_index_names_the_row_whose_file_cell_has_no_link(tmp_path):
    """Ссылки на решение нет ⇒ отказ с причиной; проза остаётся, а не угадывается.

    Такая строка в живом реестре есть ровно одна — `ADR-034`, историческая, со текстом
    `*(историческое, см. ADR-048)*` вместо ссылки. Её заголовок и так в пределе, поэтому на
    живом реестре отказов ноль; здесь сцена делает её ТОЛСТОЙ, чтобы путь отказа был пройден.
    """
    root = _scene(tmp_path,
                  f"| ADR-912 | {FAT} | Superseded | *(историческое, см. ADR-048)* |\n", {})
    rep = adr.shorten_index(root)
    assert rep["measured"] and not rep["shortened"]
    assert [r["key"] for r in rep["refused"]] == ["912"]
    assert "нет ссылки на файл решения" in rep["refused"][0]["reason"]


def test_shorten_index_refuses_when_the_decision_declares_no_h1(tmp_path):
    """Третий исход доходит до отчёта реестра, а не теряется внутри читателя файла."""
    root = _scene(tmp_path,
                  f"| ADR-913 | {FAT} | Accepted | [ADR-913](ADR-913-x.md) |\n",
                  {"ADR-913-x.md": "## без H1\n\nтекст\n"})
    rep = adr.shorten_index(root)
    assert rep["measured"] and not rep["shortened"]
    assert "нет строки `H1`" in rep["refused"][0]["reason"]


def test_an_unreadable_register_is_unmeasured_with_a_named_reason(tmp_path):
    """Реестра нет ⇒ `measured=False` и причина, а не «сокращать нечего» (инв. #17)."""
    rep = adr.shorten_index(tmp_path)
    assert rep["measured"] is False
    assert rep["unmeasured_reason"] and "НЕ измерена" in rep["unmeasured_reason"]
    assert rep["shortened"] == [] and rep["refused"] == []


def test_a_register_without_a_header_is_unmeasured_not_quietly_empty(tmp_path):
    """Шапки нет ⇒ неизвестно, какая колонка является заголовком. Fail-CLOSED."""
    (tmp_path / "docs" / "decisions").mkdir(parents=True)
    (tmp_path / "docs/decisions/INDEX.md").write_text(
        "# ADR INDEX\n\n| ADR-914 | заголовок | Accepted | [x](x.md) |\n", encoding="utf-8")
    rep = adr.shorten_index(tmp_path)
    assert rep["measured"] is False
    assert rep["unmeasured_reason"] and "шапка таблицы" in rep["unmeasured_reason"]


# ── ОДНА дверь: наивный разбор занижал длину, и это воспроизводится ──────────

def test_the_naive_split_under_reports_an_escaped_pipe_title():
    """АВАРИЯ ДОСЛОВНО: второй разбор отвечал КОРОЧЕ, чем стои́т ячейка.

    `ADR-831` на живом реестре: 163 символа по наивному разбору против 2 089 по
    каноническому, то есть строка «проходила» предел 200, не будучи в нём.
    """
    tail = "хвост пересказа, " * 20
    line = f"| ADR-915 | начало \\| {tail} | Accepted | [ADR-915](ADR-915-x.md) |"
    naive = [c.strip() for c in line.strip().strip("|").split("|")][1]
    canonical = adr.row_columns(line)[1]
    assert len(naive) < len(canonical), (
        "наивный разбор перестал занижать длину — сцена больше не воспроизводит аварию")
    assert len(naive) <= 200 < len(canonical), (
        f"сцена не воспроизводит ЦЕНУ: наивный {len(naive)}, канонический "
        f"{len(canonical)} — нужна ячейка, которую наивный разбор пускает через предел")
    assert len(adr.register_title_rows(HEAD + line + "\n")) == 1
    assert adr.register_title_rows(HEAD + line + "\n")[0][1] == canonical


def test_register_title_rows_skips_a_row_whose_form_is_not_declared():
    """Вне формы заголовок НЕ ИЗМЕРЕН, и дверь его не возвращает.

    Иначе колонкой «Заголовок» стала бы вторая ячейка чего угодно — ровно тот дефект, за
    который ADR-830 вынул статус из `parts[-3]`: у 118 строк замера 27.10 «статусом»
    оказывался заголовок на 900 символов.
    """
    rows = adr.register_title_rows(
        HEAD
        + "| ADR-917 | заголовок | 2026-10-28 |\n"
        + "| ADR-918 | заголовок | Accepted | [ADR-918](ADR-918-x.md) |\n")
    assert [r[0] for r in rows] == ["918"], (
        "строка вне объявленной формы попала в замер колонки — её вторая ячейка заголовком "
        "не является, и считать её таковой значит выдумать измерение")


def test_register_title_rows_does_not_invent_a_key_for_a_duplicate_pointer():
    """Ключ — номер, а не номер с пометкой: база сторожила `ADR-067 (дубль)`, которого нет."""
    rows = adr.register_title_rows(
        HEAD + "| ADR-916 (дубль) | Указатель | Superseded | [ADR-916](ADR-916-x.md) |\n")
    assert [r[0] for r in rows] == ["916"]


# ── живой реестр: состояние, а не обещание ───────────────────────────────────

def test_the_live_register_has_no_row_left_to_shorten():
    """На живом реестре прибору сокращать нечего, и отказов у него ноль.

    Это и есть исполнение заказа G839 п. 2: ADR-838 остановил рост, ADR-840 убрал состояние.
    """
    rep = adr.shorten_index(ROOT)
    assert rep["measured"], rep["unmeasured_reason"]
    assert rep["shortened"] == [], (
        f"в реестре снова есть строки, чей заголовок длиннее "
        f"{adr.TITLE_MAX_CHARS} символов: {[r['key'] for r in rep['shortened']][:10]}. "
        f"Позови `python3 scripts/adr_number.py titles --write`, а не правь базу храповика."
    )
    assert rep["refused"] == [], (
        f"прибор отказал на живом реестре: {rep['refused'][:3]} — отказ есть НАХОДКА "
        f"(у решения нет H1 либо в строке нет ссылки на файл), и разбирать её надо, а не "
        f"считать нормой."
    )


def test_the_shortening_is_a_transfer_and_the_archive_proves_it():
    """Проза не удалена, а ПЕРЕНЕСЕНА: дословный снимок реестра лежит в дереве.

    Без снимка сокращение было бы потерей 579 строк прозы, которой в файлах решений нет
    (замер 28.10: совпало 96 из 675). Файл ищется ГЛОБОМ, а не литеральной датой: дата —
    свойство снимка, а не предмет проверки (`.claude/rules/deployment.md`, § «Время в тестах»).
    """
    archives = sorted((ROOT / "docs" / "journal").glob("INDEX-archive-*.md"))
    assert archives, (
        "дословного снимка реестра нет ни одного. Сокращать колонку «Заголовок», не сохранив "
        "прозу, запрещено: в файлах решений её нет (замер 14,2 %)."
    )
    newest = archives[-1]
    text = newest.read_text(encoding="utf-8")
    assert "| ADR | Заголовок | Статус | Файл |" in text, (
        f"{newest.name} не содержит шапки реестра — это не снимок реестра.")
    rows = adr.register_title_rows(text)
    fat = [key for key, title, _ in rows if len(title) > adr.TITLE_MAX_CHARS]
    assert len(fat) > 500, (
        f"в снимке {newest.name} толстых строк всего {len(fat)} — снимок снят ПОСЛЕ "
        f"сокращения и прозы в нём нет, то есть переносить было некуда.")


def test_the_register_row_of_this_very_change_obeys_the_limit():
    """Положительный контроль на живучесть правила: своя строка ему подчиняется."""
    rows = adr.register_title_rows(
        (ROOT / "docs" / "decisions" / "INDEX.md").read_text(encoding="utf-8"))
    lengths = {f"ADR-{key}": len(title) for key, title, _ in rows}
    assert "ADR-840" in lengths, (
        "строки ADR-840 в реестре нет — решение, приводящее колонку к заголовку, обязано "
        "само в реестре стоять.")
    assert lengths["ADR-840"] <= adr.TITLE_MAX_CHARS, (
        f"заголовок собственной строки ADR-840 стои́т {lengths['ADR-840']} символов при "
        f"пределе {adr.TITLE_MAX_CHARS} — правило невыполнимо для своего же автора.")


def test_the_enforced_limit_is_anchored_by_a_literal():
    """Предел прибора объявлен ЛИТЕРАЛОМ рядом с проверкой — иначе его можно поднять молча.

    Тот же замок, что у ADR-837/838: сцена, определённая ОТНОСИТЕЛЬНО проверяемой константы,
    сверяет её сама с собой и переживает любую подмену.
    """
    assert adr.TITLE_MAX_CHARS == 200, (
        "предел колонки «Заголовок» разошёлся с объявленным (200). Двигать его можно ТОЛЬКО "
        "вниз, и тогда литерал здесь двигается тем же коммитом (инв. #16).")
