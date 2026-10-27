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


def row_columns(line: str):
    """Колонки строки markdown-таблицы, либо None если строка не обрамлена чёрточками.

    Обрамление — часть формы: строка, не начинающаяся и не кончающаяся `|`, не является
    строкой таблицы, и судить её колонки значило бы выдумывать их число.
    """
    parts = line.split("|")
    if len(parts) < 3 or parts[0].strip() or parts[-1].strip():
        return None
    return [p.strip() for p in parts[1:-1]]


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

_HEADER_RE = re.compile(r"^\|\s*ADR\s*\|")
_STATUS_HEADER = "Статус"
_DECLARED_STATUS_RE = re.compile(
    r"^\s*[-*]?\s*\*\*Статус:?\*\*:?\s*(?P<v>.+?)\s*$", re.IGNORECASE | re.MULTILINE)


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


def declared_status(path: Path):
    """Статус, объявленный САМИМ файлом решения (`- **Статус:** …`), либо None.

    Источник правды о статусе решения — решение. Строка реестра — проекция; выдумывать
    её статус запрещено (общий стандарт эвиденса, `docs/37`), поэтому «в файле статуса
    нет» остаётся третьим исходом, а не подставляется «Accepted».
    """
    try:
        head = path.read_text(encoding="utf-8")[:4000]
    except OSError:
        return None
    m = _DECLARED_STATUS_RE.search(head)
    return m.group("v") if m else None


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
            if status:
                repair["status"] = status
            else:
                repair["status_reason"] = (
                    f"{named[0]} не объявляет `- **Статус:**` — статус НЕ ИЗМЕРЕН, "
                    f"выдумывать его запрещено")
        else:
            repair["file_reason"] = (
                f"файлов ADR-{key}-*.md в {DECISIONS_DIR}: {len(named)} — ссылка НЕ измерена"
                if named else
                f"файла ADR-{key}-*.md в {DECISIONS_DIR} нет — ссылка НЕ измерена")
            repair["status_reason"] = "файл решения не назван однозначно — статус НЕ ИЗМЕРЕН"
        out["out_of_form"].append(dict(row, repair=repair))
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

    args = ap.parse_args(argv)
    if args.cmd == "next":
        return _cmd_next(args)
    return _cmd_check(args) if args.cmd == "check" else _cmd_form(args)


if __name__ == "__main__":
    raise SystemExit(main())
