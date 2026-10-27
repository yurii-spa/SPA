#!/usr/bin/env python3
"""Распределитель номеров ADR: номер нельзя занять дважды (карточка «Номера ADR сталкиваются»).

**Что было измерено.** За один день 2026-08-08 номера ADR столкнулись ДВАЖДЫ: две параллельные
сессии выписали `ADR-073`, потом две выписали `ADR-076`. Оба раза приоритет отдавали по факту
приземления на origin, а проигравший переименовывал свой файл и оставлял на старом имени
указатель — ссылка уже уехала в коммит, и мёртвая ссылка хуже указателя. На 2026-08-08 в дереве
остались следы обоих исходов: `ADR-073` разошёлся честно сразу (живая строка + строка-указатель
`Superseded`), `ADR-067` — не разошёлся и держал два действующих решения до 2026-08-15, когда
гейт go-live был перенумерован в `ADR-087` тем же правилом приоритета (цикл #251). Живых дублей
в реестре больше нет; храповик `test_live_duplicate_numbers_only_shrink` стоит с ПУСТОЙ базой,
то есть теперь любой дубль для него — новый.

**Причина — не невнимательность.** Номер выбирается взглядом на каталог `docs/decisions/` в
НАЧАЛЕ работы, а приземляется через час-два. Между этими двумя моментами живёт вся работа цикла,
и параллельная сессия за это время успевает занять тот же номер. Пока номер выдаёт взгляд, а не
распределитель, столкновения гарантированы — вопрос только частоты.

**Почему существующий сторож этого не видит.** `check_memory_in_git --links` отвечает на СВОЙ
вопрос: «каждая ссылка реестра разрешается, каждый файл решения упомянут в реестре». Два разных
решения под одним номером проходят его НАСКВОЗЬ зелёными — оба файла есть, обе строки на месте.
Это ровно тот класс, которым проект уже платил: сторож честно отвечает на свой вопрос, а читают
его как ответ на нужный. Поэтому здесь ДОБАВЛЕНО недостающее измерение, а не переписано старое:
ссылочная целостность по-прежнему меряется вызовом `check_index_links` (переиспользование, не
копия — второй реализации одного измерения в этом репозитории быть не должно).

**Два вопроса — два ответа:**

| Вопрос | Команда | Когда |
|---|---|---|
| Какой номер брать? | `next` | В МОМЕНТ пуша, не в начале работы |
| Этот набор файлов можно доставлять? | `check --files …` | Интерлок пушера, до сети |

`next` меряет занятость по СОЮЗУ origin/main, ВСЕХ остальных удалённых веток и рабочего дерева.
Смотреть только в дерево — это и есть исходный дефект: параллельная сессия живёт на origin, а не
у тебя на диске. Ветки добавлены 2026-08-20 по замеру: восемь решений (`ADR-088`…`ADR-095`)
лежали на `origin/claude/work-status-check-xfnbew`, `main` о них не знал, и номера 088/089 были
на `main` выписаны ВТОРОЙ раз под другие решения. Союз из двух источников отвечал на свой вопрос
честно — просто вопрос был у́же аварии.

**Почему `max+1`, а не «первый свободный».** В нумерации есть дыры (31–47, 49, 51, 52, 71), и
они не свободны: `ADR-071` уже назван в `docs/STATE.md` как «аудит-как-код» — решение, о котором
договорились раньше, чем написали файл. Выдать такой номер новому решению значит столкнуть его
с уже уехавшей ссылкой, то есть воспроизвести ровно ту аварию, которую этот модуль устраняет.
Карточка оставляла выбор реализации агенту; дыры дороже, чем плотность нумерации.

Коды возврата: **0** — свободно / находок нет · **1** — есть находки · **2** — что-то не
измерено (fail-CLOSED: «не измерено» никогда не сворачивается в «в порядке»).

stdlib-only, детерминирован, без сети (git читает локальные ref'ы).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from check_undelivered_work import _git  # noqa: E402  (переиспользование, не копия)

DEFAULT_BASE = "origin/main"
DECISIONS_DIR = "docs/decisions"
INDEX_REL = f"{DECISIONS_DIR}/INDEX.md"
REMOTES_NS = "refs/remotes/"

# Имя файла решения: ADR-<ключ>-<слаг>.md. Ключ бывает числовым (`067`) и именованным
# (`YL`, `OWN`, `TEST`) — это РАЗНЫЕ пространства имён, и распределяется только числовое.
_FILE_RE = re.compile(r"^ADR-(?P<key>\d+|[A-Z]+)-(?P<slug>.+)\.md$")
_NUMERIC_KEY_RE = re.compile(r"^\d+$")

# Строка реестра: `| ADR-067 | заголовок | статус | ссылка |`. Пометка «(дубль)» в первой
# колонке — часть принятого способа расходиться, а не мусор: см. ADR-073.
_ROW_RE = re.compile(r"^\|\s*(?P<num>ADR-[0-9A-Za-z.-]+?)\s*(?P<dup>\(дубль\))?\s*\|")

# Объявленная форма строки реестра — ЗАГОЛОВОК таблицы в самом файле:
# `| ADR | Заголовок | Статус | Файл |`. Четыре колонки, статус — третья.
# Это не выбор автора модуля: число берётся из шапки, которую читает человек (ADR-830).
DECLARED_COLUMNS = 4
STATUS_COLUMN = 3  # 1-based, по шапке таблицы

# Статус, снимающий претензию на номер. Строка-указатель не занимает номер: она объясняет,
# КУДА уехало решение, и без неё ссылка из старого коммита упирается в пустоту.
_RELEASED_STATUS_RE = re.compile(r"^\s*(superseded|withdrawn|rejected|отозван|заменен|заменён)",
                                 re.IGNORECASE)


def file_key(name: str):
    """Ключ нумерации по имени файла решения, либо None если это не файл решения."""
    m = _FILE_RE.match(name)
    return m.group("key") if m else None


def cell_separators(line: str):
    r"""Позиции РАЗДЕЛИТЕЛЕЙ ячеек: чёрточек, НЕ экранированных обратной косой.

    **Почему не `line.split("|")` (поправка ADR-831 к ADR-830).** ADR-830 вылечил «статус
    берётся по номеру колонки от конца», но сама колонка по-прежнему отделялась ЛЮБОЙ
    чёрточкой — то есть мера отвечала «сколько в строке чёрточек», ровно как и прежде,
    только на шаг позже. У markdown ответ другой: `\|` — литеральная чёрточка ВНУТРИ
    ячейки, ячейку она не делит, и читатель реестра видит на экране именно это.

    Замер 2026-10-27 на живом реестре (683 строки): разбор меняется у ОДНОЙ строки — 481
    (`ADR-508`, grep-шаблон `"Exception\|RuntimeError"` внутри обратных кавычек), и
    меняется В СТОРОНУ «строка в форме». Ни одна строка формы не теряет. То есть прежняя
    мера держала одно ЛОЖНОЕ срабатывание из 187, и оно же было единственной причиной,
    по которой экранирование чёрточки не могло починить строку: мера не видела экранов.

    Обратная косая экранирует СЛЕДУЮЩИЙ символ, каким бы он ни был (`\\|` — это
    экранированная косая, а потом разделитель), поэтому строка проходится, а не режется
    регуляркой с оглядкой назад.
    """
    out = []
    i, n = 0, len(line)
    while i < n:
        if line[i] == "\\":
            i += 2
            continue
        if line[i] == "|":
            out.append(i)
        i += 1
    return out


def _cells(line: str, strip: bool):
    """Ячейки строки markdown-таблицы, либо None если строка не обрамлена чёрточками.

    Обрамление — часть формы: строка, не начинающаяся и не кончающаяся `|`, не является
    строкой таблицы, и судить её колонки значило бы выдумывать их число.
    """
    seps = cell_separators(line)
    if len(seps) < 2 or line[:seps[0]].strip() or line[seps[-1] + 1:].strip():
        return None
    cells = [line[a + 1:b] for a, b in zip(seps, seps[1:])]
    return [c.strip() for c in cells] if strip else cells


def row_columns(line: str):
    """Колонки строки markdown-таблицы (очищенные), либо None."""
    return _cells(line, strip=True)


def _row_fields(line: str):
    """(ключ, статус | None, дубль?) для строки реестра, либо None если это не строка.

    **Строка узнаётся по ЯКОРЮ, статус — по ФОРМЕ (ADR-830).** Прежняя мера — «колонок
    хотя бы пять, статус предпоследний» — отвечала на вопрос «сколько в строке чёрточек»,
    а не «в объявленной ли она форме», и платила этим в обе стороны:

    * верно написанная строка из двух колонок получала `None`, то есть ИСЧЕЗАЛА из реестра,
      и `check` отказывал «нет ни одной строки ADR-NNN» — отказ верный по направлению и
      ложный по причине (цикл #955 заплатил им: его строка прошла только благодаря чёрточке
      внутри `^(FAILED|ERROR)` своего же заголовка);
    * строка вне формы отдавала СТАТУСОМ не ту колонку — у 118 строк замера 27.10 это
      заголовок на 900 символов, то есть «не измерено», выданное за измеренное (инв. #17).

    Теперь: якорь `| ADR-NNN |` делает строку строкой реестра ВСЕГДА (претензия на номер
    не зависит от формы — иначе сломанная форма освобождала бы номер, а это fail-OPEN),
    а статус читается ТОЛЬКО из объявленной формы. Нет формы ⇒ `None` = НЕ ИЗМЕРЕНО.
    """
    m = _ROW_RE.match(line)
    if not m:
        return None
    cols = row_columns(line)
    status = None
    if cols is not None and len(cols) == DECLARED_COLUMNS:
        status = cols[STATUS_COLUMN - 1]
    key = m.group("num")[len("ADR-"):]
    return key, status, bool(m.group("dup"))


def parse_index(text: str):
    """{ключ: [(статус, дубль?), …]} по тексту реестра. Ничего не читает с диска."""
    rows: dict[str, list] = {}
    for line in text.splitlines():
        fields = _row_fields(line)
        if fields is None:
            continue
        key, status, dup = fields
        rows.setdefault(key, []).append((status, dup))
    return rows


UNMEASURED_STATUS = "НЕ ИЗМЕРЕНО (строка вне объявленной формы)"


def status_label(status) -> str:
    """Статус для ПЕЧАТИ: неизмеренное не притворяется строкой статуса (инв. #17)."""
    return UNMEASURED_STATUS if status is None else status


def is_live_claim(status, dup: bool) -> bool:
    """Строка ПРЕТЕНДУЕТ на номер? Указатель и снятое решение — не претендуют.

    `status is None` — статус НЕ ИЗМЕРЕН (строка вне объявленной формы). Тогда претензия
    считается ЖИВОЙ: fail-CLOSED. Неизмеренный статус, прочитанный как «снято», освободил
    бы занятый номер и выдал его второму решению — ровно авария 08.08, ради которой этот
    модуль написан. Прежний код приходил к тому же ответу СЛУЧАЙНО (заголовок не совпадает
    с регуляркой снятия), и это держалось на том, что ни один заголовок не начинается со
    слова «Superseded». Теперь это решение, а не совпадение.
    """
    if dup:
        return False
    if status is None:
        return True
    return not _RELEASED_STATUS_RE.match(status)


# ── форма строки реестра: перепись и предложение починки (ADR-830) ───────────

#: Разделитель внутри колонки статуса. Взят у самого реестра, а не из головы.
META_JOIN = " · "
#: Предел длины ячейки, которую писатель готов счесть мета-колонкой (дата или
#: ярлык статуса). Нужен против обратной ошибки: обрывок прозы, случайно
#: совпавший с ярлыком, не должен уехать в статус. Самый длинный ЖИВОЙ ярлык
#: реестра — 66 символов (`Owner directive (приоритет и дизайн; …)`), поэтому
#: предел объявлен числом и с запасом.
META_CELL_MAXLEN = 120

_HEADER_RE = re.compile(r"^\|\s*ADR\s*\|")
_STATUS_HEADER = "Статус"
_DECLARED_STATUS_RE = re.compile(
    r"^\s*[-*]?\s*\*\*Статус:?\*\*:?\s*(?P<v>.+?)\s*$", re.IGNORECASE | re.MULTILINE)
#: ВСТРОЕННОЕ объявление статуса — поле однострочной шапки решения:
#: `**Дата:** 2026-09-12 · **Статус:** принято · **Область:** …`. Читается ТОЛЬКО
#: если объявления отдельной строкой нет: иначе ответы 552 решений сменились бы
#: молча, а менять их этот цикл не брался.
#:
#: ЗАЧЕМ. «Статус не объявлен» у 45 строк остатка оказался свойством ЧИТАТЕЛЯ, а не
#: решений: замер 27.10 по всем 686 файлам — отдельной строкой статус объявляют 552,
#: встроенным полем шапки ещё **98**, и не объявляют вовсе **36**. То есть прежний
#: читатель спрашивал «объявлен ли статус В МОЕЙ ФОРМЕ», а не «объявлен ли он»; это
#: тот же класс, который ADR-830 вылечил у строки реестра, — только у файла решения.
#:
#: Значение ограничено разделителями полей шапки (` · `, `|`, `*`, конец строки) —
#: иначе в колонку статуса уехало бы соседнее поле. Двоеточие ОБЯЗАТЕЛЬНО: без него
#: совпадало бы слово «статус» в прозе («статус скрипта = статус последней команды»).
#:
#: ЧИТАТЕЛЬ ДВУЯЗЫЧЕН, и это не удобство. Репозиторий двуязычен по построению (ADR-437:
#: канал имён был одноязычным, а репозиторий — нет), и «статус не объявлен» у
#: ADR-816/817/818 оказался ТРЕТЬИМ случаем одного класса за один цикл: читатель
#: спрашивал «объявлен ли статус В МОЕЙ ФОРМЕ СТРОКИ» (ADR-830 — у строки реестра),
#: «…В МОЕЙ ФОРМЕ ОБЪЯВЛЕНИЯ» (отдельной строкой, а не полем шапки) и «…НА МОЁМ ЯЗЫКЕ»
#: (здесь). Замер 27.10 по всем 686 решениям: отдельной строкой по-русски — 552, полем
#: шапки — ещё 98, только по-английски — 34, не объявляет НИ НА ОДНОМ языке РОВНО ОДНО
#: (`ADR-167`).
#:
#: ОТДЕЛЬНОГО англоязычного читателя строки здесь НЕТ намеренно: он был написан и
#: ОКАЗАЛСЯ МЁРТВЫМ — мутационный замер #957 показал, что его снятие не меняет ни одного
#: ответа, потому что это же объявление читает регулярка выше. Мутант выжил не от дыры в
#: тестах, а оттого, что мерил ЭКВИВАЛЕНТНУЮ правку; вторая дверь к одному измерению
#: снята, а не укрыта тестом.
_INLINE_STATUS_RE = re.compile(
    r"(?<![А-Яа-яЁёA-Za-z])\*{0,2}(?:Статус|Status)\*{0,2}:\s*\*{0,2}(?P<v>[^·|*\n]+)",
    re.IGNORECASE)


def declared_form(text: str):
    """(число колонок, 1-based номер колонки статуса) по ШАПКЕ таблицы, либо None.

    Форму объявляет сам документ, а не этот модуль: шапку `| ADR | Заголовок | Статус |
    Файл |` читает человек, и если она однажды изменится, судить строки по старой памяти
    было бы ровно тем дефектом, против которого правило. Шапки нет ⇒ None = НЕ ИЗМЕРЕНО.
    """
    for line in text.splitlines():
        if not _HEADER_RE.match(line):
            continue
        cols = row_columns(line)
        if not cols or _STATUS_HEADER not in cols:
            return None
        return len(cols), cols.index(_STATUS_HEADER) + 1
    return None


def declared_status(path: Path, max_len=META_CELL_MAXLEN):
    """Статус, объявленный САМИМ файлом решения, либо None.

    Источник правды о статусе решения — решение. Строка реестра — проекция; выдумывать
    её статус запрещено (общий стандарт эвиденса, `docs/37`), поэтому «в файле статуса
    нет» остаётся третьим исходом, а не подставляется «Accepted».

    Форм объявления ДВЕ, и спрашиваются обе (замер 27.10, ADR-831): отдельной строкой
    по-русски (552 решения из 686) и полем однострочной шапки на любом из двух языков
    (ещё 133). `max_len=None` отдаёт объявленное значение БЕЗ ограничения — это нужно,
    чтобы отличить «не объявлено» от «объявлено прозой, не помещающейся в ячейку
    статуса»: два разных исхода, и чинятся они по-разному.
    """
    try:
        head = path.read_text(encoding="utf-8")[:4000]
    except OSError:
        return None
    m = _DECLARED_STATUS_RE.search(head)
    if m:
        # Русское объявление отдельной строкой читается КАК И ПРЕЖДЕ, значением до конца
        # строки: так отвечают 552 решения из 686, и менять их ответы этот цикл не брался.
        return m.group("v")
    m = _INLINE_STATUS_RE.search(head)
    if not m:
        return None
    # Значение ОГРАНИЧЕНО самим классом символов захвата (`·`, `|`, `*`, перевод строки
    # в него не входят): иначе в ячейку статуса уехало бы соседнее поле шапки или абзац
    # про решение владельца на 250 символов, а это ровно инв. #17 — не-статус в колонке
    # статуса, только с другой стороны. Повторной обрезки по ` · ` здесь НЕТ: замер
    # мутациями #957 показал, что она ничего не меняет (разделитель уже исключён
    # классом), то есть была вторым выражением одного и того же ограничения.
    value = m.group("v").strip().rstrip(",;·").strip()
    # Незакрытая скобка — след обрезки по разделителю поля («принято владельцем
    # (вариант 1 из карточки *own-…*)»): в ячейке статуса она шум, а не наблюдение.
    while value.count("(") > value.count(")"):
        value = value[:value.rfind("(")].strip()
    if not value:
        return None
    if max_len is not None and len(value) > max_len:
        return None
    return value


def form_scan(text: str):
    """(форма | None, всего строк, в форме, [строки ВНЕ формы]) по тексту реестра.

    ОДНА дверь к вопросу «в форме ли строка» — её зовут и перепись, и интерлок пушера.
    Второй реализации того же измерения в этом репозитории быть не должно.
    """
    form = declared_form(text)
    if form is None:
        return None, 0, 0, []
    ncols, _status_col = form
    total = in_form = 0
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        m = _ROW_RE.match(line)
        if not m:
            continue
        total += 1
        cols = row_columns(line)
        if cols is not None and len(cols) == ncols:
            in_form += 1
            continue
        out.append({"key": m.group("num")[len("ADR-"):], "line": n,
                    "columns": len(cols) if cols is not None else None,
                    "kind": "без обрамления" if cols is None else f"колонок {len(cols)}"})
    return form, total, in_form, out


def index_form(root, index_rel=INDEX_REL):
    """Перепись ФОРМЫ строк реестра: что в форме, что вне, и что про вне ИЗМЕРИМО.

    Прибор только ЧИТАЕТ. Третий исход различим: реестр не прочитан / шапка не найдена ⇒
    `measured=False` с причиной, а не «вне формы нет ни одной».
    """
    root = Path(root)
    index = root / index_rel
    out = {"declared_columns": None, "status_column": None, "rows_total": 0,
           "in_form": 0, "out_of_form": [], "measured": False, "unmeasured_reason": None}
    try:
        text = index.read_text(encoding="utf-8")
    except OSError as exc:
        out["unmeasured_reason"] = f"{index_rel} не читается ({exc}) — форма НЕ измерена"
        return out
    form, total, in_form, rows = form_scan(text)
    if form is None:
        out["unmeasured_reason"] = (
            f"{index_rel}: шапка таблицы с колонкой «{_STATUS_HEADER}» не найдена — "
            f"объявленная форма НЕ измерена, судить строки не по чему")
        return out
    out["declared_columns"], out["status_column"] = form
    out["rows_total"], out["in_form"], out["measured"] = total, in_form, True

    decisions = root / DECISIONS_DIR
    for row in rows:
        key = row["key"]
        named = sorted(p.name for p in decisions.glob(f"ADR-{key}-*.md")) \
            if decisions.is_dir() else []
        repair = {"file": None, "file_reason": None, "status": None, "status_reason": None}
        if len(named) == 1:
            repair["file"] = named[0]
            status = declared_status(decisions / named[0])
            raw = declared_status(decisions / named[0], max_len=None)
            if status:
                repair["status"] = status
            elif raw:
                repair["status_reason"] = (
                    f"{named[0]}: объявленный статус длиной {len(raw)} символов — проза, "
                    f"а не ярлык (предел ячейки {META_CELL_MAXLEN}); в колонку статуса он "
                    f"не годится, статус НЕ ИЗМЕРЕН")
            else:
                repair["status_reason"] = (
                    f"{named[0]} не объявляет статус ни отдельной строкой "
                    f"(`- **Статус:**` / `- **Status:**`), ни полем шапки — статус "
                    f"НЕ ИЗМЕРЕН, выдумывать его запрещено")
        else:
            repair["file_reason"] = (
                f"файлов ADR-{key}-*.md в {DECISIONS_DIR}: {len(named)} — ссылка НЕ измерена"
                if named else
                f"файла ADR-{key}-*.md в {DECISIONS_DIR} нет — ссылка НЕ измерена")
            repair["status_reason"] = "файл решения не назван однозначно — статус НЕ ИЗМЕРЕН"
        out["out_of_form"].append(dict(row, repair=repair))
    return out


# ── ПРИВЕДЕНИЕ строки к объявленной форме (ADR-831) ──────────────────────────
#
# ЗАЧЕМ ОТДЕЛЬНЫЙ ПИСАТЕЛЬ. ADR-830 построил ПЕРЕПИСЬ (`index_form`) и назвал
# 187 строк вне формы, но переписывать их руками нечем: строка реестра — до
# 8400 символов, и у 140 из них правка касается того, что в этих символах
# ЗАТЕРЯЛОСЬ. Ручная правка такого объёма непроверяема по построению, поэтому
# починка — детерминированный писатель с контролем в обе стороны, а МЕРА
# остаётся одна (`form_scan`): второй двери к вопросу «в форме ли строка» в
# этом репозитории нет.
#
# ЧТО ПИСАТЕЛЮ РАЗРЕШЕНО — РОВНО ТРИ ДЕЙСТВИЯ, и ни одно не переставляет текст:
#
#   1. ЭКРАНИРОВАТЬ чёрточку, съеденную разбором таблицы. `^(FAILED|ERROR)` в
#      заголовке — это ОДНА ячейка в замысле автора и ДВЕ в разборе markdown;
#      `\|` возвращает замысел. Текст не меняется ни на символ, добавляется
#      обратная косая на стыке.
#   2. СВЕРНУТЬ лишнюю колонку даты/статуса в колонку статуса через ` · `.
#      Это не выдумка формата: так устроены 131 строка реестра, УЖЕ стоящие в
#      форме (`2026-10-08 · принято`) — конвенцию объявляет сам документ, и
#      перепись ярлыков берётся у него же (`declared_status_labels`).
#   3. ДОПИСАТЬ колонку, которой нет: ссылку (единственный файл решения на
#      диске) и статус (объявленный САМИМ файлом решения).
#
# ЧТО ЗАПРЕЩЕНО. Выдумывать статус (`docs/37`: нет объявления ⇒ третий исход, а
# не «Accepted» по умолчанию), переставлять текст между колонками, удалять
# наблюдение (дата сохраняется ВСЕГДА, ADR-537) и трогать строку, чьё
# приведение не измеримо целиком. Любой из этих случаев — ОТКАЗ по строке с
# названной причиной; строка остаётся в базе храповика, а не «починенной».
#
# ПОЧЕМУ ДАТА ОСТАЁТСЯ В КОЛОНКЕ СТАТУСА, А НЕ УЕЗЖАЕТ В ХВОСТ ЗАГОЛОВКА.
# Заказ G831 предписывал второе. Замер опроверг посылку заказа: у 118 строк
# вида `| ADR | проза | ДАТА |` дата стои́т РОВНО в третьей колонке, то есть
# уже на месте статуса, а 131 строка В ФОРМЕ несёт там `ДАТА · принято`.
# Перенос даты в заголовок развёл бы две половины реестра по разным
# конвенциям и потребовал бы экранированной чёрточки там, где её не было.

#: Ссылка на файл решения в последней колонке. Якорь — расширение `.md`: это
#: ссылка на ФАЙЛ, а не на раздел.
_LINK_CELL_RE = re.compile(r"^\[[^\]]+\]\([^()\s]+\.md\)$")
#: Дата-наблюдение в ячейке. Ровно ISO-день: «2026-09» или «сентябрь» датой
#: здесь не считаются — угадывать формат значило бы выдумывать наблюдение.
_DATE_CELL_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
#: Дата с пометкой цикла — `2026-10-15 (#870, доставлено #871)`. Форма взята у
#: самого реестра: такие же пометки стоя́т в колонке статуса строк В ФОРМЕ
#: (`Accepted (#884)`, `принято 2026-10-16 (#881)`). Население замерено, а не
#: предположено: из 103 коротких ячеек строк вне формы этой формы ровно ВОСЕМЬ,
#: и без неё писатель принимал их за обрывок заголовка — ошибка в ту сторону
#: экранировала бы чёрточку там, где её не ел разбор (замер 27.10, ADR-831).
_DATE_NOTE_CELL_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\s*\([^()]*\)$")


def declared_status_labels(text: str, decisions_dir=None):
    """Ярлыки статуса, объявленные САМИМИ документами, либо None если форма не измерена.

    Та же логика, что у `declared_form`: словарь статусов — свойство документов, а не
    память модуля. Список в коде пришлось бы догонять руками, и расхождение было бы
    невидимым; здесь он меряется каждый прогон. Шапки нет ⇒ None = НЕ ИЗМЕРЕНО.

    **Источников ДВА, и это не удобство.** Реестр — проекция, решения — источник правды о
    статусе, и спрашивать надо оба:

    * строки реестра В ФОРМЕ — так документ объявляет свою конвенцию печати
      (`2026-10-08 · принято`);
    * `- **Статус:**` файлов решений — так объявляет статус тот, кто вправе.

    Одного реестра НЕ ХВАТАЕТ, и это измерено контролем: в реестре, где ВСЕ строки вне
    формы, строк в форме нет вовсе ⇒ словарь пуст ⇒ писатель принимал за обрывок
    заголовка даже ячейку `принято`. На живом реестре дефект не проявлялся (496 строк в
    форме кормили словарь), то есть держался на СОВПАДЕНИИ — ровно класс, который проект
    чинит заменой совпадения на решение.
    """
    form = declared_form(text)
    if form is None:
        return None
    ncols, status_col = form
    labels: set[str] = set()

    def add(value: str):
        for part in value.split(META_JOIN):
            part = part.strip()
            if part and not _DATE_CELL_RE.match(part) \
                    and not _DATE_NOTE_CELL_RE.match(part):
                labels.add(part)

    for line in text.splitlines():
        if not _ROW_RE.match(line):
            continue
        cols = row_columns(line)
        if cols is None or len(cols) != ncols:
            continue
        add(cols[status_col - 1])
    if decisions_dir is not None and Path(decisions_dir).is_dir():
        for path in sorted(Path(decisions_dir).glob("ADR-*.md")):
            status = declared_status(path)
            if status and len(status) <= META_CELL_MAXLEN:
                add(status)
    return labels


def _is_meta_cell(value: str, labels) -> bool:
    """Ячейка — дата-наблюдение и/или ярлык статуса (а не обрывок заголовка)?

    Мера направлена в безопасную сторону: не узнали ⇒ ячейка считается ЧАСТЬЮ
    ЗАГОЛОВКА, то есть её чёрточка экранируется и текст остаётся на месте. Ошибка в
    другую сторону (обрывок прозы уехал в колонку статуса) была бы потерей смысла.
    """
    value = value.strip()
    if not value or len(value) > META_CELL_MAXLEN:
        return False
    for part in value.split(META_JOIN):
        part = part.strip()
        if not part:
            return False
        if not (_DATE_CELL_RE.match(part) or _DATE_NOTE_CELL_RE.match(part)
                or part in labels):
            return False
    return True


def _has_status_label(value: str, labels) -> bool:
    """В свёрнутой колонке есть хоть один ЯРЛЫК, а не только даты?

    Дата статусом не является: строка `| ADR | проза | 2026-09-09 |` отвечает «когда»,
    а не «принято ли». Поэтому к одной дате статус ДОПИСЫВАЕТСЯ из файла решения, и если
    файл молчит — строка не трогается.
    """
    return any(part.strip() in labels for part in value.split(META_JOIN))


def _raw_cells(line: str):
    """Сырые (неочищенные) ячейки обрамлённой строки, либо None.

    Сырые — чтобы заголовок в 8400 символов уехал в починенную строку ПОБАЙТОВО:
    `strip()` на нём сменил бы отбивку у 140 строк без всякой нужды. Разделители — те же,
    что у меры (`cell_separators`): второго определения ячейки быть не должно.
    """
    return _cells(line, strip=False)


def _split_tail(cells, labels):
    """(ячейки заголовка, мета-ячейки, ячейка-ссылка|None) — разбор СПРАВА.

    Разбор идёт от конца, потому что именно конец строки и объявлен формой: ссылка
    последняя, статус перед ней. Всё, что осталось слева, — заголовок, сколько бы
    чёрточек в нём ни съел разбор.
    """
    stripped = [c.strip() for c in cells]
    j = len(cells) - 1
    link = None
    if j >= 1 and _LINK_CELL_RE.match(stripped[j]):
        link = cells[j]
        j -= 1
    meta = []
    while j >= 1 and _is_meta_cell(stripped[j], labels):
        meta.insert(0, cells[j])
        j -= 1
    return cells[1:j + 1], meta, link


def _escape_title_pipes(line: str, title_count: int) -> str:
    """Экранировать чёрточки ВНУТРИ заголовка, не тронув остальную строку.

    Экранируются ровно разделители между кусками заголовка — с `title_count - 1`-й по
    счёту чёрточки после первой. Правка адресная: позиции считаются по сырой строке,
    поэтому ни один другой байт не двигается.
    """
    hits = cell_separators(line)
    # hits[0] — обрамление, hits[1] — граница «номер | заголовок»; дальше внутри заголовка.
    inner = hits[2:2 + title_count - 1]
    out = []
    prev = 0
    for pos in inner:
        out.append(line[prev:pos])
        out.append("\\|")
        prev = pos + 1
    out.append(line[prev:])
    return "".join(out)


def verify_repair(old_line: str, new_line: str, ncols: int):
    """Причина, по которой починке НЕЛЬЗЯ верить, либо пустая строка.

    Контроль, а не украшение: он проверяет ровно то, что писателю разрешено, и всё
    остальное объявляет отказом. Три утверждения:

    * строка стала строкой объявленной формы, и её статус теперь ИЗМЕРЕН;
    * номер (претензия на ключ) не изменился;
    * **каждое прежнее поле выжило ДОСЛОВНО** — текст старой ячейки обязан быть
      подстрокой новой строки. Проверять подстрокой строку ЦЕЛИКОМ невозможно по
      построению: добавление колонки меняет её конец. Поэтому мера поля, а не строки,
      — и этого довольно: потерять наблюдение, не потеряв ни одного поля, нельзя.
    """
    new_cols = row_columns(new_line)
    if new_cols is None or len(new_cols) != ncols:
        return (f"починенная строка не в форме: колонок "
                f"{'нет обрамления' if new_cols is None else len(new_cols)} при {ncols}")
    old_fields = _row_fields(old_line)
    new_fields = _row_fields(new_line)
    if new_fields is None:
        return "починенная строка перестала быть строкой реестра — номер потерян"
    if old_fields is not None and new_fields[0] != old_fields[0]:
        return f"номер изменился: {old_fields[0]} → {new_fields[0]}"
    if new_fields[1] is None:
        return "статус починенной строки всё равно НЕ ИЗМЕРЕН"
    for cell in (_raw_cells(old_line) or []):
        cell = cell.strip()
        if cell and cell not in new_line:
            return f"прежнее поле не выжило дословно: «{cell[:60]}…»"
    return ""


def repair_line(line: str, labels, declared, ncols=DECLARED_COLUMNS):
    """(новая строка | None, действие, причина отказа) для ОДНОЙ строки реестра.

    `declared` — объявленный статус решения и имя его файла: `(status|None, file|None)`.
    Берётся ВНЕ этой функции (она ничего не читает с диска), чтобы контроль мог
    подставить оба исхода.
    """
    cells = _raw_cells(line)
    if cells is None:
        return None, "", ("строка не обрамлена чёрточками — число колонок пришлось бы "
                          "выдумать; приведение потребовало бы ПЕРЕСТАВИТЬ текст")
    if len(cells) == ncols:
        return None, "", "строка уже в объявленной форме"

    actions = []
    for _ in range(len(cells)):           # предел витков = число ячеек, зацикливания нет
        cells = _raw_cells(line)
        title, meta, link = _split_tail(cells, labels)
        if len(title) <= 1:
            break
        line = _escape_title_pipes(line, len(title))
        actions.append("экранирована чёрточка в заголовке")
    cells = _raw_cells(line)
    title, meta, link = _split_tail(cells, labels)
    if len(title) != 1:
        return None, "", (f"заголовок остался из {len(title)} кусков — приведение "
                          f"не измерено")

    status_raw = META_JOIN.join(c.strip() for c in meta)
    declared_status_value, file_name = declared
    if len(meta) > 1:
        actions.append("лишняя колонка свёрнута в статус")
    if not status_raw or not _has_status_label(status_raw, labels):
        if not declared_status_value:
            return None, "", ("статус не объявлен ни строкой, ни файлом решения — "
                              "подставлять его ЗАПРЕЩЕНО (docs/37)")
        status_raw = (f"{status_raw}{META_JOIN}{declared_status_value}"
                      if status_raw else declared_status_value)
        actions.append("статус взят у файла решения")

    if link is None:
        if not file_name:
            return None, "", "файл решения не назван однозначно — ссылка НЕ измерена"
        key = _row_fields(line)[0]
        link = f" [ADR-{key}]({file_name}) "
        actions.append("дописана ссылка на файл решения")

    new_line = f"|{cells[0]}|{title[0]}| {status_raw} |{link}|"
    bad = verify_repair(line, new_line, ncols)
    if bad:
        return None, "", f"контроль починки отказал: {bad}"
    return new_line, " · ".join(actions), ""


def repair_index(root, index_rel=INDEX_REL):
    """Починка реестра ЦЕЛИКОМ: новый текст и отчёт по каждой строке вне формы.

    Прибор НИЧЕГО не пишет — писать решает CLI. Третий исход различим: реестр не
    прочитан или шапки нет ⇒ `measured=False` с причиной.
    """
    root = Path(root)
    out = {"measured": False, "unmeasured_reason": None, "repaired": [],
           "refused": [], "new_text": None}
    try:
        text = (root / index_rel).read_text(encoding="utf-8")
    except OSError as exc:
        out["unmeasured_reason"] = f"{index_rel} не читается ({exc}) — починка НЕ измерена"
        return out
    decisions = root / DECISIONS_DIR
    labels = declared_status_labels(text, decisions)
    form = declared_form(text)
    if form is None or labels is None:
        out["unmeasured_reason"] = (
            f"{index_rel}: шапка таблицы с колонкой «{_STATUS_HEADER}» не найдена — "
            f"ни форма, ни словарь статусов НЕ измерены, починить нечем")
        return out
    ncols, _status_col = form
    out["measured"] = True

    lines = text.splitlines(keepends=True)
    for n, raw in enumerate(lines, 1):
        line = raw.rstrip("\n")
        if not _ROW_RE.match(line):
            continue
        cols = row_columns(line)
        if cols is not None and len(cols) == ncols:
            continue
        key = _row_fields(line)[0]
        named = sorted(p.name for p in decisions.glob(f"ADR-{key}-*.md")) \
            if decisions.is_dir() else []
        file_name = named[0] if len(named) == 1 else None
        status = declared_status(decisions / file_name) if file_name else None
        new_line, action, reason = repair_line(line, labels, (status, file_name), ncols)
        if new_line is None:
            out["refused"].append({"key": key, "line": n, "reason": reason})
            continue
        lines[n - 1] = new_line + ("\n" if raw.endswith("\n") else "")
        out["repaired"].append({"key": key, "line": n, "action": action,
                                "old": line, "new": new_line})
    out["new_text"] = "".join(lines)
    return out

def _origin_files(root, base_ref, git=_git):
    """Имена файлов решений на base ref, либо None если ref не измерим (fail-CLOSED)."""
    rc, out, _ = git(root, "ls-tree", "--name-only", f"{base_ref}:{DECISIONS_DIR}")
    if rc != 0:
        return None
    return [line.strip() for line in out.splitlines() if line.strip()]


def _origin_index(root, base_ref, git=_git):
    """Текст реестра на base ref, либо None если не измерим."""
    rc, out, _ = git(root, "show", f"{base_ref}:{INDEX_REL}")
    if rc != 0:
        return None
    return out


def other_refs(root, base_ref=DEFAULT_BASE, git=_git):
    """(остальные удалённые ref'ы, не_измерено) — всё под ``refs/remotes/`` кроме base.

    ``refs/remotes/origin/HEAD`` отбрасывается: это симссылка на base, и её содержимое
    удвоило бы каждую находку. Читаются ЛОКАЛЬНЫЕ ref'ы, сети здесь нет.
    """
    rc, out, err = git(root, "for-each-ref", "--format=%(refname)", REMOTES_NS)
    if rc != 0:
        return [], [f"список удалённых ref'ов не читается ({err.strip() or rc}) — номера, "
                    f"занятые на ветках, НЕ измерены"]
    refs = []
    for line in out.splitlines():
        full = line.strip()
        if not full.startswith(REMOTES_NS) or full.endswith("/HEAD"):
            continue
        short = full[len(REMOTES_NS):]
        if short != base_ref:
            refs.append(short)
    return sorted(refs), []


def _ref_files(root, ref, git=_git):
    """Имена файлов решений на произвольном ref, либо None если ref не измерим.

    Форма ``ls-tree -r <ref> -- <путь>`` выбрана намеренно вместо ``<ref>:<путь>``: у ветки,
    где каталога решений нет вовсе, вторая форма падает — и «решений тут нет» стало бы
    неотличимо от «ветка не читается». Первое — факт, второе — отказ измерить.
    """
    rc, out, _ = git(root, "ls-tree", "--name-only", "-r", ref, "--", f"{DECISIONS_DIR}/")
    if rc != 0:
        return None
    return [line.strip().rsplit("/", 1)[-1] for line in out.splitlines() if line.strip()]


def keys_on_other_refs(root, base_ref=DEFAULT_BASE, git=_git):
    """({ключ: {имя файла: [ref, …]}}, не_измерено) по всем веткам кроме base.

    **Зачем.** Замер 2026-08-20: восемь решений (`ADR-088`…`ADR-095`) живут на
    `origin/claude/work-status-check-xfnbew`, и `main` о них не знает ни строкой. Номера 088 и
    089 при этом выписаны на `main` ЗАНОВО и под другие решения — то есть номер уже занят
    дважды, просто в разных ветках. Союз «origin/main + дерево» на этот вопрос не отвечает по
    построению: он не смотрит ни на одну ветку, кроме своей.
    """
    refs, unchecked = other_refs(root, base_ref, git=git)
    found: dict[str, dict[str, list]] = {}
    for ref in refs:
        names = _ref_files(root, ref, git=git)
        if names is None:
            unchecked.append(f"каталог решений на {ref} не читается — номера этой ветки "
                             f"НЕ измерены")
            continue
        for name in names:
            key = file_key(name)
            if key:
                found.setdefault(key, {}).setdefault(name, []).append(ref)
    return found, unchecked


def taken_keys(root, base_ref=DEFAULT_BASE, git=_git):
    """(занятые ключи, не_измерено). Союз origin, ОСТАЛЬНЫХ веток и рабочего дерева.

    Смотреть только в дерево — исходный дефект: параллельная сессия занимает номер НА ORIGIN,
    и её файла у тебя на диске нет по построению. Поэтому недоступность origin — не повод
    ответить «ну, по дереву свободно»: это отказ измерить (код 2). Ровно то же верно и для
    веток: номер, занятый на `origin/claude/…`, свободным не является.
    """
    root = Path(root)
    taken: dict[str, set] = {}
    unchecked = []

    def claim(key, where):
        taken.setdefault(key, set()).add(where)

    origin_names = _origin_files(root, base_ref, git=git)
    if origin_names is None:
        unchecked.append(
            f"каталог решений на {base_ref} не читается — занятость номеров НЕ измерена; "
            f"выдать номер по одному лишь рабочему дереву значит воспроизвести аварию 08.08")
    else:
        for name in origin_names:
            key = file_key(name)
            if key:
                claim(key, f"{base_ref}:{DECISIONS_DIR}/{name}")

    elsewhere, elsewhere_unchecked = keys_on_other_refs(root, base_ref, git=git)
    unchecked.extend(elsewhere_unchecked)
    for key, by_name in elsewhere.items():
        for name, refs in by_name.items():
            for ref in refs:
                claim(key, f"{ref}:{DECISIONS_DIR}/{name}")

    origin_index = _origin_index(root, base_ref, git=git)
    if origin_index is None:
        unchecked.append(f"{INDEX_REL} на {base_ref} не читается — строки реестра НЕ измерены")
    else:
        for key, rows in parse_index(origin_index).items():
            if any(is_live_claim(s, d) for s, d in rows):
                claim(key, f"{base_ref}:{INDEX_REL}")

    decisions = root / DECISIONS_DIR
    if decisions.is_dir():
        for p in sorted(decisions.glob("*.md")):
            key = file_key(p.name)
            if key:
                claim(key, f"дерево:{DECISIONS_DIR}/{p.name}")
    index = root / INDEX_REL
    if index.is_file():
        try:
            for key, rows in parse_index(index.read_text(encoding="utf-8")).items():
                if any(is_live_claim(s, d) for s, d in rows):
                    claim(key, f"дерево:{INDEX_REL}")
        except OSError as exc:
            unchecked.append(f"{INDEX_REL} не читается ({exc}) — строки дерева НЕ измерены")

    return taken, unchecked


def next_number(root, base_ref=DEFAULT_BASE, git=_git):
    """(следующий свободный номер | None, занятые, не_измерено)."""
    taken, unchecked = taken_keys(root, base_ref, git=git)
    if unchecked:
        return None, taken, unchecked
    numeric = [int(k) for k in taken if _NUMERIC_KEY_RE.match(k)]
    if not numeric:
        # Пустой каталог решений — это не «начинай с 001», а сломанное измерение:
        # у живого репозитория решения есть. Молчаливого «всё в порядке» здесь не будет.
        return None, taken, [
            f"на {base_ref} и в дереве не найдено НИ ОДНОГО числового решения — "
            f"измерение сломано, номер не выдаю"]
    return max(numeric) + 1, taken, []


# ── интерлок пушера: набор файлов ────────────────────────────────────────────

def _registry_listed_names(index_text: str) -> set:
    """Имена файлов, на которые ссылается реестр — тем же разбором, что у теста реестра.

    Одна мерка на двоих (`check_memory_in_git.check_index_links`): иначе сторож до пуша и
    тест после пуша спорили бы о том, «упомянуто ли решение».
    """
    from check_memory_in_git import _BACKTICK_RE, _LINK_RE
    targets = set(_LINK_RE.findall(index_text)) | set(_BACKTICK_RE.findall(index_text))
    return {Path(t).name for t in targets}


def check_push(root, files, base_ref=DEFAULT_BASE, git=_git):
    """(находки, не_измерено) для НАБОРА доставляемых файлов.

    Судит только то, что уезжает этим пушем, и то, чего этот пуш касается. Иначе
    предсуществующий дубль `ADR-067` запирал бы любую доставку, к нему не относящуюся, —
    сторож, краснеющий не на твоей работе, отключается первым.
    """
    root = Path(root)
    findings, unchecked = [], []

    rel_files = []
    for f in files:
        p = Path(f)
        try:
            rel = p.resolve().relative_to(root.resolve()).as_posix()
        except (ValueError, OSError):
            rel = p.as_posix()
        rel_files.append(rel)

    pushed_decisions = [r for r in rel_files
                        if r.startswith(f"{DECISIONS_DIR}/") and file_key(Path(r).name)]
    if not pushed_decisions:
        return [], []  # решения не уезжают — этому сторожу нечего сказать

    origin_names = _origin_files(root, base_ref, git=git)
    if origin_names is None:
        return [], [f"каталог решений на {base_ref} не читается — столкновение номеров "
                    f"НЕ измерено (fail-CLOSED)"]

    # Реестр, который БУДЕТ на origin после этого пуша: если INDEX.md уезжает — берём
    # версию из дерева, иначе действует та, что уже лежит на origin.
    if INDEX_REL in rel_files:
        index_path = root / INDEX_REL
        if not index_path.is_file():
            return [], [f"{INDEX_REL} объявлен к доставке, но в дереве его нет — не измерено"]
        try:
            index_text = index_path.read_text(encoding="utf-8")
        except OSError as exc:
            return [], [f"{INDEX_REL} не читается ({exc}) — не измерено"]
    else:
        index_text = _origin_index(root, base_ref, git=git)
        if index_text is None:
            return [], [f"{INDEX_REL} на {base_ref} не читается — не измерено"]
    index_rows = parse_index(index_text)

    # Форма строк реестра, которые уезжают этим пушем (ADR-830). Судим ТОЛЬКО тронутые
    # строки: предсуществующие 187 строк вне формы не имеют права запирать чужую
    # доставку — сторож, краснеющий не на твоей работе, отключают первым. Их убыль
    # стережёт храповик `test_adr_index_form.py`, а не этот отказ.
    index_form_scan, _total, _in_form, out_of_form_rows = form_scan(index_text)
    if index_form_scan is None:
        return [], [f"{INDEX_REL}: шапка таблицы с колонкой «{_STATUS_HEADER}» не найдена — "
                    f"форма строк НЕ измерена (fail-CLOSED)"]
    out_of_form_by_key: dict[str, list] = {}
    for row in out_of_form_rows:
        out_of_form_by_key.setdefault(row["key"], []).append(row)

    origin_by_key: dict[str, list] = {}
    for name in origin_names:
        key = file_key(name)
        if key:
            origin_by_key.setdefault(key, []).append(name)

    elsewhere, elsewhere_unchecked = keys_on_other_refs(root, base_ref, git=git)
    unchecked.extend(elsewhere_unchecked)

    for rel in sorted(pushed_decisions):
        name = Path(rel).name
        key = file_key(name)

        # 0. Именованное семейство (`OWN`, `YL`, `TEST`) — другое пространство имён, и номер
        #    в нём НЕ распределяется (шапка модуля, `_FILE_RE`). Его имя — весь слаг: шесть
        #    `ADR-OWN-…` живут на main рядом штатно. До 27.10 проверки ниже судили семейство
        #    как один номер `OWN` и отказывали ЛЮБОМУ новому решению владельца по построению:
        #    «номер занят» (#1) и «нет строки ADR-OWN» (#2 — строки реестра несут ключ
        #    `OWN-2026-07`, а не `OWN`). Для семейства претензия ровно та, что у теста
        #    реестра (`test_live_registry_of_decisions_is_intact`): на файл ссылается строка.
        if not _NUMERIC_KEY_RE.match(key):
            if name not in _registry_listed_names(index_text):
                findings.append(
                    f"{rel}: в {INDEX_REL} нет строки со ссылкой на {name} — решение уехало бы "
                    f"вне реестра и покрасило бы main (test_live_registry_of_decisions_is_intact)")
            continue

        # 1. Столкновение: НОВЫЙ файл берёт номер, уже занятый ДРУГИМ файлом на origin.
        others = [n for n in origin_by_key.get(key, []) if n != name]
        collides_on_base = bool(others) and name not in origin_by_key.get(key, [])
        if collides_on_base:
            findings.append(
                f"{rel}: номер ADR-{key} уже занят на {base_ref} файлом "
                f"{', '.join(sorted(others))} — это столкновение, а не обновление. "
                f"Возьми номер через `scripts/adr_number.py next` и переименуй ДО пуша")

        # 1b. То же столкновение, но занявший сидит на ДРУГОЙ ВЕТКЕ. На `main` номер выглядит
        #     свободным (у нас там дыры 090–095), поэтому находка #1 молчит — а решение под
        #     этим номером уже существует и уедет в конфликт при первом же слиянии.
        #     Замер 2026-08-20: так на одну ветку легли ADR-088…095, из них 088 и 089 были
        #     ВТОРОЙ раз выписаны на main под другие решения. Своё имя не считается: пуш
        #     обновления файла, который на ветке лежит под тем же именем, — не столкновение.
        if not collides_on_base:
            by_name = {n: refs for n, refs in elsewhere.get(key, {}).items() if n != name}
            if by_name:
                where = "; ".join(f"{n} ({', '.join(sorted(refs))})"
                                  for n, refs in sorted(by_name.items()))
                findings.append(
                    f"{rel}: номер ADR-{key} уже занят ВНЕ {base_ref} — {where}. "
                    f"На {base_ref} он выглядит свободным, но решение под ним существует: "
                    f"возьми номер через `scripts/adr_number.py next` и переименуй ДО пуша")

        # 2. Решение вне реестра — ловится ДО приземления, а не тестом после (карточка).
        rows = index_rows.get(key, [])
        if not rows:
            findings.append(
                f"{rel}: в {INDEX_REL} нет ни одной строки ADR-{key} — решение уехало бы "
                f"вне реестра и покрасило бы main (test_live_registry_of_decisions_is_intact)")
        elif not any(is_live_claim(s, d) for s, d in rows):
            findings.append(
                f"{rel}: все строки ADR-{key} в реестре сняты (Superseded/указатель), "
                f"а файл доставляется как действующее решение — реестр и файл спорят")

        # 2b. Строка ЕСТЬ, но не в объявленной форме ⇒ её статус НЕ ИЗМЕРЕН (ADR-830).
        #     Прежде такая строка либо проходила насквозь, отдавая статусом заголовок,
        #     либо исчезала из реестра и получала отказ #2 с ЛОЖНОЙ причиной «нет ни одной
        #     строки». Теперь причина названа верно, и починка — одна строка.
        broken = out_of_form_by_key.get(key, [])
        if broken:
            where = ", ".join(f"строка {b['line']} ({b['kind']})" for b in broken)
            ncols, status_col = index_form_scan
            findings.append(
                f"{rel}: строка ADR-{key} в {INDEX_REL} НЕ в объявленной форме "
                f"(шапка: {ncols} колонки, статус — {status_col}-я) — {where}. "
                f"Статус такой строки НЕ ИЗМЕРЕН, и реестр молча считает номер занятым. "
                f"Перепиши строку формой `| ADR-{key} | Заголовок | Статус | Файл |` "
                f"(`python3 scripts/adr_number.py form` печатает измеренные значения)")

    # 3. Две ЖИВЫЕ строки на один номер среди тронутых этим пушем — но находка только
    #    если ИМЕННО ЭТОТ пуш их создаёт или добавляет. Предсуществующий дубль (ADR-067)
    #    не должен запирать правку файла под тем же номером: сторож, краснеющий на чужой
    #    беспорядок, отключают первым, и тогда он не поймает и настоящее столкновение.
    #    Порог — состояние origin: стало хуже ⇒ отказ, не хуже (в т.ч. ЛУЧШЕ) ⇒ пропуск.
    before_rows = parse_index(_origin_index(root, base_ref, git=git) or "")
    for key in sorted({file_key(Path(r).name) for r in pushed_decisions}):
        if not _NUMERIC_KEY_RE.match(key):
            continue  # именованное семейство номер не делит — см. п. 0
        live = [s for s, d in index_rows.get(key, []) if is_live_claim(s, d)]
        was = len([s for s, d in before_rows.get(key, []) if is_live_claim(s, d)])
        if len(live) > 1 and len(live) > was:
            findings.append(
                f"ADR-{key}: в {INDEX_REL} становится {len(live)} действующих строки на один "
                f"номер ({', '.join(status_label(s) for s in live)}), было {was} — номер делят "
                f"двое. Разойтись: "
                f"проигравший перенумеровывается, на старом номере остаётся "
                f"строка-указатель Superseded")

    return findings, unchecked


def live_duplicates(root, index_rel=INDEX_REL):
    """{ключ: [статусы]} — номера с ДВУМЯ действующими претензиями в реестре дерева.

    Отдельно от `check_push`: тот судит доставку, этот — состояние живого репозитория
    (ратчет в тестах). Оба меряют одним `parse_index`/`is_live_claim`.
    """
    index = Path(root) / index_rel
    if not index.is_file():
        return {}
    out = {}
    for key, rows in parse_index(index.read_text(encoding="utf-8")).items():
        live = [s for s, d in rows if is_live_claim(s, d)]
        if len(live) > 1:
            out[key] = live
    return out


# ── CLI ──────────────────────────────────────────────────────────────────────

def _cmd_next(args) -> int:
    number, taken, unchecked = next_number(Path(args.root), args.base)
    if args.json:
        print(json.dumps({"next": number, "taken": sorted(taken),
                          "unchecked": unchecked}, ensure_ascii=False, indent=2))
    elif unchecked:
        print("❓ НЕ ИЗМЕРЕНО — номер не выдан (fail-CLOSED):")
        for u in unchecked:
            print(f"  - {u}")
    else:
        print(f"ADR-{number:03d}")
        print(f"  занято номеров: {len(taken)} "
              f"(союз {args.base}, остальных удалённых веток и рабочего дерева)")
    return 2 if unchecked else 0


def _cmd_check(args) -> int:
    findings, unchecked = check_push(Path(args.root), args.files, args.base)
    if args.json:
        print(json.dumps({"findings": findings, "unchecked": unchecked},
                         ensure_ascii=False, indent=2))
        return 2 if unchecked else (1 if findings else 0)
    if unchecked:
        print("❓ НЕ ИЗМЕРЕНО — доставку решений не подтверждаю (fail-CLOSED):")
        for u in unchecked:
            print(f"  - {u}")
        return 2
    if findings:
        print(f"⚠️  НОМЕРА ADR ({len(findings)}):")
        for f in findings:
            print(f"  - {f}")
        return 1
    print("✅ номера решений в наборе свободны, каждое есть в реестре.")
    return 0


def _cmd_form(args) -> int:
    rep = index_form(Path(args.root))
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 2 if not rep["measured"] else (1 if rep["out_of_form"] else 0)
    if not rep["measured"]:
        print("❓ НЕ ИЗМЕРЕНО — форму строк реестра не подтверждаю (fail-CLOSED):")
        print(f"  - {rep['unmeasured_reason']}")
        return 2
    print(f"форма строк {INDEX_REL} (шапка: {rep['declared_columns']} колонки, "
          f"статус — {rep['status_column']}-я):")
    print(f"  строк реестра: {rep['rows_total']} · в форме: {rep['in_form']} · "
          f"ВНЕ формы: {len(rep['out_of_form'])}")
    if not rep["out_of_form"]:
        print("✅ все строки в объявленной форме — статус измерен у каждой.")
        return 0
    whole = [r for r in rep["out_of_form"]
             if r["repair"]["file"] and r["repair"]["status"]]
    print(f"  починка ИЗМЕРИМА целиком: {len(whole)} · "
          f"статус не объявлен и выдумывать его нельзя: "
          f"{len(rep['out_of_form']) - len(whole)}")
    by_kind: dict[str, int] = {}
    for r in rep["out_of_form"]:
        by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
    for kind, n in sorted(by_kind.items(), key=lambda kv: -kv[1]):
        print(f"    · {kind}: {n}")
    for r in rep["out_of_form"][:args.limit]:
        rp = r["repair"]
        print(f"  - строка {r['line']} ADR-{r['key']} ({r['kind']}): "
              f"файл={rp['file'] or rp['file_reason']} · "
              f"статус={rp['status'] or rp['status_reason']}")
    if len(rep["out_of_form"]) > args.limit:
        print(f"  … и ещё {len(rep['out_of_form']) - args.limit} (полный список — `--json`)")
    return 1


def _cmd_repair(args) -> int:
    """Привести строки реестра к объявленной форме. По умолчанию НИЧЕГО не пишет.

    Коды возврата те же, что у соседей: 0 — приводить нечего · 1 — есть находки
    (строки, которые приведены или которые привести нельзя) · 2 — НЕ ИЗМЕРЕНО.
    """
    rep = repair_index(Path(args.root))
    if args.json:
        print(json.dumps({k: v for k, v in rep.items() if k != "new_text"},
                         ensure_ascii=False, indent=2))
        return 2 if not rep["measured"] else (
            1 if (rep["repaired"] or rep["refused"]) else 0)
    if not rep["measured"]:
        print("❓ НЕ ИЗМЕРЕНО — починку реестра не подтверждаю (fail-CLOSED):")
        print(f"  - {rep['unmeasured_reason']}")
        return 2
    print(f"починка {INDEX_REL}: приведено {len(rep['repaired'])} · "
          f"ОТКАЗАНО {len(rep['refused'])}")
    by_action: dict[str, int] = {}
    for r in rep["repaired"]:
        by_action[r["action"]] = by_action.get(r["action"], 0) + 1
    for action, n in sorted(by_action.items(), key=lambda kv: -kv[1]):
        print(f"    · {action}: {n}")
    by_reason: dict[str, int] = {}
    for r in rep["refused"]:
        by_reason[r["reason"]] = by_reason.get(r["reason"], 0) + 1
    for reason, n in sorted(by_reason.items(), key=lambda kv: -kv[1]):
        print(f"    ✗ {reason}: {n}")
    for r in rep["refused"][:args.limit]:
        print(f"  - строка {r['line']} ADR-{r['key']}: {r['reason']}")
    if not args.write:
        print("  (ничего не записано — повтори с `--write`)")
        return 1 if (rep["repaired"] or rep["refused"]) else 0
    index = Path(args.root) / INDEX_REL
    index.write_text(rep["new_text"], encoding="utf-8")
    print(f"  записано: {index}")
    return 1 if (rep["repaired"] or rep["refused"]) else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(ROOT), help="корень репозитория")
    ap.add_argument("--base", default=DEFAULT_BASE, help="базовый ref (по умолчанию origin/main)")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("next", help="следующий свободный номер (мерить В МОМЕНТ пуша)")

    c = sub.add_parser("check", help="можно ли доставлять этот набор файлов")
    c.add_argument("--files", nargs="+", required=True, help="файлы набора доставки")

    f = sub.add_parser("form", help="перепись формы строк реестра (только читает)")
    f.add_argument("--limit", type=int, default=20, help="сколько строк печатать поимённо")

    r = sub.add_parser("repair", help="привести строки реестра к объявленной форме")
    r.add_argument("--write", action="store_true",
                   help="записать результат (без флага — только показать)")
    r.add_argument("--limit", type=int, default=20, help="сколько строк печатать поимённо")

    args = ap.parse_args(argv)
    if args.cmd == "next":
        return _cmd_next(args)
    if args.cmd == "check":
        return _cmd_check(args)
    return _cmd_repair(args) if args.cmd == "repair" else _cmd_form(args)


if __name__ == "__main__":
    raise SystemExit(main())
