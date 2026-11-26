#!/usr/bin/env python3
"""Кто из `landing/src/**` ОБРАЩАЕТСЯ к полю дневного снимка — замер, а не догадка.

Зачем это есть (ADR-1117, заказ G1091 п. 3). Сторож `test_site_snapshot_view_shape.py`
отвечает на вопрос О ФОРМЕ: несёт ли переходник `landing/src/lib/snapshot_view.js` каждый
путь снимка. 26.11 он красен на **61** пути, и у каждого честных исходов ровно два:

* поле читает хоть одна страница ⇒ его надо ДОБАВИТЬ в переходник (иначе страница напечатает
  слово «undefined» молча — ровно авария ADR-373, `positions_count`);
* не читает ни одна ⇒ объявить в `NOT_IN_VIEW` **с ИЗМЕРЕННОЙ причиной**.

Выбор между ними есть ЗАМЕР СПРОСА, и до этого прибора его не делал никто: сторож формы про
спрос не знает ничего, а дописывать шестьдесят одну строку «не нужно» запрещено (инв. #16).

**Токен читателем не делает.** `grep book_exposure landing/src` даёт семь файлов, и ни один
из них не читает поле снимка: `book_exposure` живёт на ВИТРИНЕ (`site_numbers.json`, блок
`exposure`) и в своей библиотеке `lib/book_exposure.js`. Поэтому мера идёт не по слову, а по
ДОРОГЕ значения: ввоз переходника (или самого снимка) → имя привязки → цепочка обращений.

**Три исхода различимы** (инв. #17): `read` (назван файл и дорога) · `not_read` (измеренный
ноль) · `unmeasured` с НАЗВАННОЙ причиной. Нечитаемый файл, обращение по вычисляемому ключу
(`snap[k]`) и утечка привязки туда, куда прибор не идёт, дают именно третий исход, а не
«не читает»: «не измерено» никогда не выдаётся за «чисто».

**Утечка значения стóит ровно столько, сколько у значения ПОДВЕТОК.** `const days =
snap.real_track_days;` и дальше `{days}` в разметке — это не потерянная дорога: у листа
подветок в снимке НЕТ, спрашивать о них нечего, и объявлять такую пару «не измерено» значило
бы раздуть третий исход до бессмысленности. Утечка объекта (`goLiveLabel(snap)` внутри
помощника передаёт параметр ДАЛЬШЕ) — наоборот, настоящая потеря дороги, и она называется.

Охват дорог (ГРАНИЦА, объявленная вслух — не свойство дерева):

1. прямая цепочка на привязке ввоза: `snap.paper_tracks.balanced.apy_pct`;
2. **хоп через псевдоним**: `const t = snap.paper_tracks;` → `t.balanced.apy_pct`;
3. **хоп через разбор**: `const { bars, packages } = snap;` → `bars.length`;
4. **хоп через помощника**: `f(snap, true)` → определение `f` в `landing/src/**` → имя
   параметра на этом месте → цепочки на нём внутри тела.

Хопов прибор идёт `MAX_HOPS` и дальше НЕ идёт, говоря это вслух. Урок
`.claude/rules/deployment.md` § «ПРОИЗВОДНАЯ ПЕРЕПИСЬ» дословен: форма, теряющая известного
члена, класс не сужает, а подменяет, — поэтому у прибора есть положительный контроль на
НАСТОЯЩЕЙ аварии (`paper_tracks.*.positions_count`, ADR-373) и обратный на выдуманном имени.

Коды возврата:
    0 — каждый путь снимка РЕШЁН, и ни один читаемый путь переходник не теряет
    1 — НАХОДКА: путь читают, а переходник его не несёт (страница напечатает «undefined»)
    2 — НЕ ИЗМЕРЕНО (каталог сайта не прочитан, снимок не разобран, `node` не нашёлся …)
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

#: Расширения, которые прибор разбирает. Файл иного рода в поверхность не входит, и это
#: ГРАНИЦА ОХВАТА, а не замер его пустоты.
SUFFIXES = (".astro", ".js", ".jsx", ".mjs", ".ts", ".tsx")

#: Сколько хопов прибор проходит от корневой привязки. Число ОБЪЯВЛЕНО: за его пределом
#: дорога числится `unmeasured`, а не «не читает».
MAX_HOPS = 4

VIEW_REL = "landing/src/lib/snapshot_view.js"
SNAPSHOT_REL = "landing/src/data/track_snapshot.json"
SURFACE_REL = "landing/src"

#: Роды корневой привязки: переходник (его форму и судит сторож) и САМ снимок.
KIND_VIEW = "view"
KIND_RAW = "raw"

#: Вердикты пути (инв. #17 — три исхода различимы).
READ_VIEW = "read_through_view"
READ_RAW = "read_from_raw_snapshot"
NOT_READ = "not_read"

_IDENT = r"[A-Za-z_$][A-Za-z0-9_$]*"
_RE_DEFAULT_IMPORT = re.compile(
    rf"^[ \t]*import[ \t]+({_IDENT})[ \t]+from[ \t]*['\"]([^'\"]+)['\"]", re.M)
_RE_NAMED_IMPORT = re.compile(
    r"^[ \t]*import[ \t]*\{([^}]*)\}[ \t]*from[ \t]*['\"]([^'\"]+)['\"]", re.M)
_RE_FN_DECL = re.compile(
    rf"(?:export[ \t]+)?(?:async[ \t]+)?function[ \t]+({_IDENT})[ \t]*\(([^)]*)\)")
_RE_FN_ARROW = re.compile(
    rf"(?:export[ \t]+)?(?:const|let|var)[ \t]+({_IDENT})[ \t]*=[ \t]*"
    r"(?:async[ \t]*)?\(([^)]*)\)[ \t]*=>")


#: `a && b` отдаёт `b`, когда `a` истинно: имя слева — операнд ПРОВЕРКИ, а не значение.
_RE_AND_NEXT = re.compile(r"[ \t]*&&")

#: Что стои́т сразу после имени, когда значение ПРОВЕРЯЮТ, а не передают дальше.
_RE_GUARD_NEXT = re.compile(r"[ \t]*(?:&&|\|\||\?\?|===|!==|==|!=|\?[^.]|instanceof\b|in\b)")

#: Слова, за которыми стои́т `(`, но зовом они не являются.
_NOT_A_CALLEE = frozenset({
    "return", "if", "else", "while", "for", "switch", "case", "catch", "typeof", "await",
    "new", "delete", "void", "yield", "do", "in", "of", "function",
})

#: Левая сторона объявления псевдонима и то, что идиоматически стои́т между `=` и обращением.
_RE_ALIAS_LHS = re.compile(rf"(?:const|let|var)[ \t]+({_IDENT})[ \t]*=[ \t]*$")
#: Защитная цепочка того же корня перед обращением: `(snap && snap.a && ` .
_RE_GUARD_PREFIX = re.compile(
    rf"(?:[(!\s]*)(?:{_IDENT}(?:\s*\??\.\s*{_IDENT})*\s*(?:&&|\|\||\?\?)\s*)*[(!\s]*$")


def _alias_lhs(text: str, start: int):
    """Объявляется ли этим обращением ПСЕВДОНИМ, и под каким именем.

    Форма `const t = snap.paper_tracks;` узнаётся напрямую; идиома с null-guard —
    `const t = (snap && snap.paper_tracks) || {};` — через отсечение защитной цепочки ТОГО
    ЖЕ корня. Без второй половины прибор терял бы псевдоним ровно у двух страниц, которые
    читают книги и пакеты, и молчал бы о вычисляемом ключе на них — то есть выдавал бы
    «не измерено» за «измеренный ноль» (инв. #17).
    """
    before = text[max(0, start - 240):start]
    m = _RE_ALIAS_LHS.search(before)
    if m and m.end() == len(before):
        return m
    guard = _RE_GUARD_PREFIX.search(before)
    if not guard or guard.end() != len(before) or guard.start() == len(before):
        return None
    head = before[:guard.start()]
    m = _RE_ALIAS_LHS.search(head)
    return m if m and m.end() == len(head) else None


class NotMeasured(RuntimeError):
    """Замер не состоялся; причина названа."""


# ───────────────────────────── форма снимка и переходника ──────────────────────────────

def document_paths(doc) -> set[str]:
    """Пути документа в той же форме, какую судит сторож (`/a/b`)."""
    out: set[str] = set()

    def walk(obj, prefix: str) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                out.add(f"{prefix}/{key}")
                if isinstance(value, dict):
                    walk(value, f"{prefix}/{key}")

    walk(doc, "")
    return out


_DUMP = """
import { readFileSync } from 'node:fs';
import path from 'node:path';
const root = process.argv[2];
const src = readFileSync(path.join(root, 'landing/src/lib/snapshot_view.js'), 'utf8');
const NUMBERS = JSON.parse(readFileSync(path.join(root, 'landing/src/data/site_numbers.json'), 'utf8'));
const RAW = JSON.parse(readFileSync(path.join(root, 'landing/src/data/track_snapshot.json'), 'utf8'));
const body = src.split('\\n').filter((l) => !/^\\s*import\\s/.test(l)).join('\\n')
  .replace(/export\\s+default\\s+/, 'return ');
console.log(JSON.stringify(new Function('NUMBERS', 'RAW', body)(NUMBERS, RAW)));
"""


def view_paths(root: Path) -> set[str]:
    """Форма переходника, снятая ЗАПУСКОМ его же байтов (та же дверь, что у сторожа)."""
    node = shutil.which("node")
    if node is None:
        raise NotMeasured("`node` не найден — форму переходника нечем снять")
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "dump.mjs"
        script.write_text(_DUMP, encoding="utf-8")
        try:
            out = subprocess.run([node, str(script), str(root)], capture_output=True,
                                 text=True, timeout=120)
        except Exception as exc:  # noqa: BLE001
            raise NotMeasured(f"node не запустился ({exc})") from exc
    if out.returncode != 0:
        raise NotMeasured(f"переходник не загрузился: {out.stderr.strip()[:200]}")
    try:
        return document_paths(json.loads(out.stdout))
    except ValueError as exc:
        raise NotMeasured(f"вывод переходника не разобран ({exc})") from exc


# ────────────────────────────────── разбор обращений ───────────────────────────────────

def strip_comments(text: str) -> str:
    """Убрать `//…` и `/*…*/`, СОХРАНИВ длину текста.

    Длина сохраняется намеренно: смещения обращений остаются сопоставимы с исходником.
    Комментарий читателем не делает — `// ← track_snapshot.book_exposure` в
    `due-diligence.astro` именно такой случай, и без этой чистки он дал бы ложное чтение.
    """
    out = list(text)
    i, n = 0, len(text)
    in_line = in_block = False
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_line:
            if ch == "\n":
                in_line = False
            else:
                out[i] = " "
        elif in_block:
            if ch == "*" and nxt == "/":
                out[i] = out[i + 1] = " "
                i += 2
                in_block = False
                continue
            if ch != "\n":
                out[i] = " "
        elif ch == "/" and nxt == "/":
            in_line = True
            out[i] = out[i + 1] = " "
            i += 2
            continue
        elif ch == "/" and nxt == "*":
            in_block = True
            out[i] = out[i + 1] = " "
            i += 2
            continue
        i += 1
    return "".join(out)


def _skip_ws(text: str, i: int) -> int:
    while i < len(text) and text[i] in " \t\r\n":
        i += 1
    return i


def _rskip_ws(text: str, i: int) -> int:
    while i >= 0 and text[i] in " \t\r\n":
        i -= 1
    return i


def read_chain(text: str, i: int) -> tuple[list, str]:
    """Цепочка членов сразу ПОСЛЕ имени привязки.

    Сегмент — либо имя (литерал), либо ``None`` = **ключ вычисляется**
    (``paperTracks[t.key].status``). Вычисляемый ключ цепочку НЕ ОБРЫВАЕТ: поле за ним
    по-прежнему названо литералом, и честный ответ — «спрос у ВСЕХ соседей этого уровня»
    (fail-CLOSED), а не «не измерено». Первая редакция прибора обрывала чтение здесь и
    потому молчала о трёх настоящих дорогах (`packages.astro`, `PackageStatusRows.astro`).

    Род: `member` — цепочка прочитана; `dynamic_unparsed` — скобку не удалось даже
    разметить, и тогда отвечать о подветке действительно нечем.
    """
    members: list = []
    while True:
        j = _skip_ws(text, i)
        if j < len(text) - 1 and text[j] == "?" and text[j + 1] == ".":
            j += 2
        elif j < len(text) and text[j] == ".":
            j += 1
        elif j < len(text) and text[j] == "[":
            k = _skip_ws(text, j + 1)
            if k < len(text) and text[k] in "'\"":
                quote = text[k]
                end = text.find(quote, k + 1)
                if end == -1:
                    return members, "dynamic_unparsed"
                name = text[k + 1:end]
                k = _skip_ws(text, end + 1)
                if k >= len(text) or text[k] != "]":
                    return members, "dynamic_unparsed"
                members.append(name)
                i = k + 1
                continue
            close = _match_bracket(text, j)
            if close is None:
                return members, "dynamic_unparsed"
            members.append(None)
            i = close + 1
            continue
        else:
            return members, "member"
        k = _skip_ws(text, j)
        m = re.match(_IDENT, text[k:])
        if not m:
            return members, "member"
        members.append(m.group(0))
        i = k + m.end()


def _match_bracket(text: str, open_at: int):
    """Парная `]` для `[` в `open_at`; не нашлась — None."""
    depth = 0
    i = open_at
    while i < len(text):
        if text[i] in "([{":
            depth += 1
        elif text[i] in ")]}":
            depth -= 1
            if depth == 0:
                return i if text[i] == "]" else None
        i += 1
    return None


def occurrences(text: str, name: str):
    """Все обращения к имени: (начало, конец, члены, род)."""
    for m in re.finditer(rf"(?<![A-Za-z0-9_$.]){re.escape(name)}(?![A-Za-z0-9_$])", text):
        members, kind = read_chain(text, m.end())
        yield m.start(), m.end(), members, kind


def _module_path(root: Path, from_file: Path, spec: str):
    """Относительный ввоз → файл дерева; иначе None (чужой пакет или вне дерева)."""
    if not spec.startswith("."):
        return None
    target = (from_file.parent / spec).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None
    return target


def param_names(params: str) -> list:
    """Имена параметров по позициям; разобранный (`{a}`) и остаточный (`...r`) — None."""
    pieces: list[str] = []
    depth = 0
    cur = ""
    for ch in params:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            pieces.append(cur)
            cur = ""
            continue
        cur += ch
    if cur.strip():
        pieces.append(cur)
    names: list = []
    for raw in pieces:
        head = raw.split("=")[0].strip()
        m = re.fullmatch(_IDENT, head)
        names.append(m.group(0) if m else None)
    return names


def find_function(text: str, name: str):
    """Определение функции → (параметры, начало тела, конец тела); нет — None."""
    for regex in (_RE_FN_DECL, _RE_FN_ARROW):
        for m in regex.finditer(text):
            if m.group(1) != name:
                continue
            params = param_names(m.group(2))
            body_start = text.find("{", m.end())
            if body_start == -1 or text[m.end():body_start].strip() not in ("", "=>"):
                end = text.find(";", m.end())
                return params, m.end(), (end if end != -1 else len(text))
            depth, i = 0, body_start
            while i < len(text):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        return params, body_start, i
                i += 1
            return params, body_start, len(text)
    return None


def enclosing_call(text: str, pos: int):
    """Привязка стои́т аргументом зова ⇒ (имя функции, номер аргумента); иначе None."""
    depth = 0
    i = pos - 1
    while i >= 0:
        ch = text[i]
        if ch in ")]}":
            depth += 1
        elif ch == "(":
            if depth == 0:
                break
            depth -= 1
        elif ch in "[{":
            if depth == 0:
                return None
            depth -= 1
        i -= 1
    if i < 0:
        return None
    open_paren = i
    j = _rskip_ws(text, open_paren - 1)
    m = re.search(rf"({_IDENT})$", text[:j + 1])
    if not m:
        return None
    if m.group(1) in _NOT_A_CALLEE:
        # `return (pt && pt.x)` — ключевое слово зовом не является. Не отсечь его значило бы
        # печатать «помощник `return` не разрешён», то есть объявлять НЕ ИЗМЕРЕННОЙ дорогу,
        # которой нет (замер 26.11: ровно одна такая строка в `packages.astro`).
        return None
    before_name = text[:m.start()].rstrip()
    if before_name.endswith("."):
        # `JSON.stringify(rec)` — зов на члене чужого объекта: дорогу прибор не идёт, и это
        # ЕСТЬ третий исход (значение уходит в разметку целиком), а не «не читает».
        owner = re.search(rf"({_IDENT}(?:\s*\.\s*{_IDENT})*)\s*\.$", before_name)
        prefix = owner.group(1).replace(" ", "") if owner else "?"
        return (f"{prefix}.{m.group(1)}", -1)
    seg = text[open_paren + 1:pos]
    depth = 0
    index = 0
    for ch in seg:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            index += 1
    return m.group(1), index


def expand_chain(base: list, members: list, all_paths: set) -> tuple[list, bool]:
    """Пути цепочки под базой, с РАСКРЫТИЕМ вычисляемых ключей во всех соседей.

    Чтение `/a/b/c` есть обращение и к `/a`, и к `/a/b`. Сегмент `None` (ключ вычисляется)
    раскрывается во ВСЕ непосредственные дети текущего пути, какие есть в снимке: ключ
    неизвестен, поле названо, и записать спрос каждому соседу — fail-CLOSED. Детей нет
    (лист либо список) ⇒ раскрытие останавливается: индекс в массив есть чтение самого
    массива, и выдумывать ему подветку нельзя.

    Второй член возврата — было ли раскрытие (для отдельной оси отчёта).
    """
    frontier = ["/" + "/".join(base) if base else ""]
    out: list = []
    expanded = False
    for seg in members:
        nxt: list = []
        for cur in frontier:
            if seg is not None:
                nxt.append(f"{cur}/{seg}")
                continue
            expanded = True
            kids = sorted(p for p in all_paths
                          if p.startswith(cur + "/") and "/" not in p[len(cur) + 1:])
            nxt.extend(kids)
        if not nxt:
            break
        out.extend(nxt)
        frontier = nxt
    return [p for p in out if p], expanded


# ───────────────────────────────────── сам замер ───────────────────────────────────────

class _Measurement:
    """Одно прохождение поверхности: спрос, третий исход и граница охвата."""

    def __init__(self, root: Path, snapshot_children: set, all_paths: set):
        self.root = root
        self.children = snapshot_children          # пути, у которых в снимке ЕСТЬ подветка
        self.all_paths = all_paths                 # все пути снимка — для раскрытия ключа
        self.expanded_keys = 0                     # сколько цепочек раскрыто по соседям
        self.view: dict = {}
        self.raw: dict = {}
        self.unmeasured: list = []
        self.hops_spent = 0
        self.texts: dict = {}

    # ── вспомогательное ───────────────────────────────────────────────────────────────
    def bucket(self, kind: str) -> dict:
        return self.view if kind == KIND_VIEW else self.raw

    def text_of(self, path: Path):
        if path not in self.texts:
            try:
                self.texts[path] = strip_comments(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError) as exc:
                self.texts[path] = None
                self.unmeasured.append(
                    f"{self._rel(path)}: не прочитан ({exc})")
        return self.texts[path]

    def _rel(self, path: Path) -> str:
        try:
            return path.relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return str(path)

    # ── обход привязки ────────────────────────────────────────────────────────────────
    def walk_binding(self, *, text: str, name: str, base: list, kind: str,
                     where: str, road: str, hop: int, file: Path,
                     import_spans: tuple = (), file_text: str | None = None) -> None:
        """Собрать обращения к привязке `name`, чья база — путь `base`.

        `text` — ОБЛАСТЬ, в которой ищутся обращения (тело помощника может быть срезом);
        `file_text` — ПОЛНЫЙ текст файла, и зовы разрешаются по нему. Разделение не
        косметическое: срез тела не несёт ни строк ввоза, ни соседних определений, и
        резолвинг по срезу объявлял неразрешённым помощника, лежащего рядом в том же файле.
        """
        bucket = self.bucket(kind)
        whole = file_text if file_text is not None else text
        base_path_here = "/" + "/".join(base) if base else ""
        has_subtree = (not base_path_here) or base_path_here in self.children
        for start, end, members, chain_kind in occurrences(text, name):
            if any(a <= start < b for a, b in import_spans):
                continue                                   # сама строка ввоза
            if chain_kind == "dynamic_unparsed":
                if not has_subtree:
                    continue    # лист (или список): подветок в снимке нет, терять нечего
                self.unmeasured.append(
                    f"{where}: скобку обращения на `{name}` не удалось разметить — о "
                    f"подветке отвечать нечем ({road})")
                continue
            if members:
                paths, expanded = expand_chain(base, members, self.all_paths)
                if expanded:
                    self.expanded_keys += 1
                for p in paths:
                    bucket.setdefault(p, set()).add(
                        f"{where} ({road}{' · ключ вычисляется' if expanded else ''})")
                if hop < MAX_HOPS and all(s is not None for s in members):
                    self._maybe_alias(text, start, base + list(members), kind, where,
                                      road, hop, file, import_spans, whole)
                elif hop < MAX_HOPS and paths:
                    # Псевдоним подветки, добытой вычисляемым ключом: база неизвестна
                    # ПОИМЁННО, поэтому хоп идёт по КАЖДОМУ раскрытому соседу — иначе
                    # `const pt = paperTracks[t.key]` потерял бы все чтения на `pt`.
                    tail = [p for p in paths if p.count("/") == len(members) + len(base)]
                    for p in tail:
                        self._maybe_alias(text, start, p.strip("/").split("/"), kind,
                                          where, road, hop, file, import_spans, whole)
                continue
            # Привязка упомянута БЕЗ члена: разбор, зов помощника или утечка значения.
            # Место, где имя ОБЪЯВЛЯЕТСЯ (`const s = snap || {}` — левая сторона), чтением
            # не является и утечкой тоже: не отсеять его значило бы записать в третий исход
            # каждый защитный псевдоним, то есть ответить «не измерено» о дороге, которую
            # прибор как раз прошёл.
            if re.search(r"(?:const|let|var)[ \t]+$", text[max(0, start - 12):start]):
                continue
            if self._maybe_destructure(text, start, base, kind, where, road, hop,
                                       file, import_spans, whole):
                continue
            # `&&` и `||` различаются СЕМАНТИКОЙ, и на этом различии стои́т верность меры.
            # `snap && snap.packages` — имя слева есть ОПЕРАНД ПРОВЕРКИ: значением
            # выражения становится то, что СПРАВА, и псевдоним принадлежит ему. `snap || {}`
            # — наоборот: значением остаётся САМО имя, и псевдоним его. Не развести это
            # значило бы приписать `const snapPkg = (snap && snap.packages) || {}` псевдоним
            # КОРНЯ, а дальше раскрыть вычисляемый ключ по ВСЕМ полям верхнего уровня —
            # ровно шесть ложных «читают», которые поймал свой же перемеряющий сторож.
            nxt = text[end:end + 12]
            if _RE_AND_NEXT.match(nxt):
                continue
            if hop < MAX_HOPS:
                m = _alias_lhs(text, start)
                if m:
                    self.hops_spent += 1
                    self.walk_binding(
                        text=text, name=m.group(1), base=base, kind=kind, where=where,
                        road=f"{road} → псевдоним `{m.group(1)}`", hop=hop + 1,
                        file=file, import_spans=import_spans, file_text=whole)
                    continue
            # Остальные проверки значения утечкой тоже не являются: сравнение, `!`, `typeof`.
            if (_RE_GUARD_NEXT.match(nxt)
                    or text[max(0, start - 8):start].rstrip().endswith(("!", "typeof"))):
                continue
            if not has_subtree:
                continue      # лист: подветок нет, спрашивать о них нечего
            if hop >= MAX_HOPS:
                self.unmeasured.append(
                    f"{where}: `{name}` уехал за предел {MAX_HOPS} хоп(ов) — дальше прибор "
                    f"не идёт ({road})")
                continue
            call = enclosing_call(text, start)
            if call is None:
                self.unmeasured.append(
                    f"{where}: `{name}` упомянут без обращения и вне зова — дорога не "
                    f"прослежена ({road})")
                continue
            self._hop_into_helper(call, base, kind, where, road, hop, file, whole)

    def _maybe_alias(self, text: str, start: int, base: list, kind: str, where: str,
                     road: str, hop: int, file: Path, import_spans: tuple,
                     whole: str) -> None:
        """`const t = snap.paper_tracks;` — псевдоним подветки."""
        m = _alias_lhs(text, start)
        if not m:
            return
        self.hops_spent += 1
        self.walk_binding(text=text, name=m.group(1), base=base, kind=kind, where=where,
                          road=f"{road} → псевдоним `{m.group(1)}`", hop=hop + 1,
                          file=file, import_spans=import_spans, file_text=whole)

    def _maybe_destructure(self, text: str, start: int, base: list, kind: str,
                           where: str, road: str, hop: int, file: Path,
                           import_spans: tuple, whole: str) -> bool:
        """`const { bars, packages } = snap;` — разбор привязки."""
        before = text[max(0, start - 260):start]
        m = re.search(r"(?:const|let|var)[ \t]*\{([^}]*)\}[ \t]*=[ \t]*$", before)
        if not m:
            return False
        bucket = self.bucket(kind)
        for piece in m.group(1).split(","):
            piece = piece.strip()
            if not piece:
                continue
            if ":" in piece:
                src, local = (s.strip() for s in piece.split(":", 1))
            else:
                src = local = piece
            if not re.fullmatch(_IDENT, src) or not re.fullmatch(_IDENT, local):
                self.unmeasured.append(
                    f"{where}: разбор `{piece}` не в объявленной форме — дорога не "
                    f"прослежена ({road})")
                continue
            bucket.setdefault("/" + "/".join(base + [src]), set()).add(
                f"{where} ({road} → разбор)")
            if hop < MAX_HOPS:
                self.hops_spent += 1
                self.walk_binding(text=text, name=local, base=base + [src], kind=kind,
                                  where=where, road=f"{road} → разбор `{local}`",
                                  hop=hop + 1, file=file, import_spans=import_spans,
                                  file_text=whole)
        return True

    def _hop_into_helper(self, call, base: list, kind: str, where: str, road: str,
                         hop: int, file: Path, text: str) -> None:  # noqa: PLR0913
        """`f(snap, true)` — хоп в тело помощника к параметру на этом месте."""
        fn_name, arg_index = call
        if arg_index < 0:
            self.unmeasured.append(
                f"{where}: значение уходит в `{fn_name}(…)` целиком — дорога за чужой "
                f"дверью не прослеживается ({road})")
            return
        target, src_name = self._resolve_callee(file, text, fn_name, where, road)
        if target is None:
            return
        body_text = self.text_of(target)
        if body_text is None:
            return
        if not isinstance(src_name, str):
            return
        found = find_function(body_text, src_name)
        if found is None:
            self.unmeasured.append(
                f"{where}: определение помощника `{src_name}` не найдено в "
                f"{self._rel(target)} — дорога не прослежена ({road})")
            return
        params, body_start, body_end = found
        if arg_index >= len(params) or params[arg_index] is None:
            self.unmeasured.append(
                f"{where}: аргумент №{arg_index} помощника `{src_name}` не назван простым "
                f"именем — дорога не прослежена ({road})")
            return
        pname = params[arg_index]
        self.hops_spent += 1
        self.walk_binding(
            text=body_text[body_start:body_end], name=pname, base=base, kind=kind,
            where=where, road=f"{road} → помощник {self._rel(target)}::{src_name}"
                              f"(`{pname}`)", hop=hop + 1, file=target,
            file_text=body_text)

    def _resolve_callee(self, file: Path, text: str, name: str, where: str, road: str):
        """Файл и исходное имя помощника; не разрешилось — третий исход с причиной."""
        for m in _RE_NAMED_IMPORT.finditer(text):
            target = _module_path(self.root, file, m.group(2))
            if target is None or not target.is_file():
                continue
            for piece in m.group(1).split(","):
                piece = piece.strip()
                if not piece:
                    continue
                if " as " in piece:
                    src, local = (s.strip() for s in piece.split(" as ", 1))
                else:
                    src = local = piece
                if local == name:
                    return target, src
        if find_function(text, name) is not None:
            return file, name
        self.unmeasured.append(
            f"{where}: помощник `{name}` не разрешён (ни ввоз из дерева, ни своё "
            f"определение) — дорога не прослежена ({road})")
        return None, None


def _file_roots(root: Path, path: Path, text: str) -> list:
    """Корневые привязки файла: (имя, род, промежуток строки ввоза)."""
    roots = []
    for m in _RE_DEFAULT_IMPORT.finditer(text):
        target = _module_path(root, path, m.group(2))
        if target is None:
            continue
        rel = target.relative_to(root.resolve()).as_posix()
        if rel == VIEW_REL:
            roots.append((m.group(1), KIND_VIEW, (m.start(), m.end())))
        elif rel == SNAPSHOT_REL:
            roots.append((m.group(1), KIND_RAW, (m.start(), m.end())))
    return roots


def measure(root, *, want_view_shape: bool = True) -> dict:
    """Замер спроса: путь снимка → кто к нему обращается и какой дорогой."""
    # Корень РАЗРЕШАЕТСЯ сразу: на macOS `/tmp` есть ссылка на `/private/tmp`, и без этого
    # относительные пути файлов не вычитались из корня — переходник попадал в поверхность
    # как чужой читатель, а дерево БЕЗ корневой привязки отвечало «одна привязка» вместо
    # отказа. Нашёл это свой же контроль, а не вычитка.
    root = Path(root).resolve()
    snap_file = root / SNAPSHOT_REL
    surface_dir = root / SURFACE_REL
    if not snap_file.is_file():
        raise NotMeasured(f"снимка нет: {snap_file}")
    if not surface_dir.is_dir():
        raise NotMeasured(f"каталога сайта нет: {surface_dir}")
    try:
        snap = json.loads(snap_file.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise NotMeasured(f"снимок не разобран ({exc})") from exc

    files = sorted(p for p in surface_dir.rglob("*")
                   if p.is_file() and p.suffix in SUFFIXES
                   and "/data/" not in p.as_posix())
    if not files:
        raise NotMeasured(f"ни одного файла объявленного рода в {surface_dir}")

    snap_all = document_paths(snap)
    children = {p for p in snap_all if any(q.startswith(p + "/") for q in snap_all)}
    run = _Measurement(root, children, snap_all)
    roots_seen = 0

    for path in files:
        text = run.text_of(path)
        if text is None:
            continue
        rel = run._rel(path)
        if rel == VIEW_REL:
            continue                      # сам переходник потребителем своей формы не является
        for name, kind, span in _file_roots(root, path, text):
            roots_seen += 1
            run.walk_binding(text=text, name=name, base=[], kind=kind, where=rel,
                             road=f"ввоз {kind}", hop=0, file=path,
                             import_spans=(span,))

    if roots_seen == 0:
        raise NotMeasured(
            "ни один файл поверхности не ввозит ни переходник, ни снимок — дороги, "
            "о которой прибор судит, в этом дереве нет")

    view_shape = view_paths(root) if want_view_shape else None

    verdict = {}
    for p in sorted(snap_all):
        if p in run.view:
            verdict[p] = READ_VIEW
        elif p in run.raw:
            verdict[p] = READ_RAW
        else:
            verdict[p] = NOT_READ

    findings = []
    if view_shape is not None:
        findings = [p for p in sorted(snap_all)
                    if verdict[p] == READ_VIEW and p not in view_shape]

    return {
        "root": str(root),
        "files_in_surface": len(files),
        "roots": roots_seen,
        "hops_spent": run.hops_spent,
        "chains_with_computed_key": run.expanded_keys,
        "max_hops": MAX_HOPS,
        "snapshot_paths": len(snap_all),
        "verdict": verdict,
        "read_through_view": {p: sorted(v) for p, v in sorted(run.view.items())
                              if p in snap_all},
        "read_from_raw_snapshot": {p: sorted(v) for p, v in sorted(run.raw.items())
                                   if p in snap_all},
        "not_read": sorted(p for p in snap_all if verdict[p] == NOT_READ),
        "unmeasured": sorted(set(run.unmeasured)),
        "view_shape_measured": view_shape is not None,
        "findings": findings,
    }


def not_read_paths(root, *, want_view_shape: bool = False) -> set:
    """Пути, которых НЕ читает никто — измеренный ноль. Для сторожа объявлений."""
    return set(measure(root, want_view_shape=want_view_shape)["not_read"])


# ──────────────────────────────────────── CLI ──────────────────────────────────────────

def format_report(result: dict) -> str:
    counts: dict = {}
    for value in result["verdict"].values():
        counts[value] = counts.get(value, 0) + 1
    lines = [
        f"Спрос на поля снимка (дерево {result['root']}):",
        f"  поверхность {result['files_in_surface']} файл(ов), корневых привязок "
        f"{result['roots']}, хопов пройдено {result['hops_spent']} при пределе "
        f"{result['max_hops']}; путей снимка {result['snapshot_paths']}",
        f"  читают через переходник: {counts.get(READ_VIEW, 0)}"
        f" · напрямую из снимка: {counts.get(READ_RAW, 0)}"
        f" · НЕ ЧИТАЕТ НИКТО (измеренный ноль): {counts.get(NOT_READ, 0)}",
    ]
    if not result["view_shape_measured"]:
        lines.append("  форма переходника НЕ СНЯТА (--no-view-shape) — о потере полей "
                     "этот прогон не судит")
    for p in result["findings"]:
        lines.append(f"  🚨 НАХОДКА {p}: поле ЧИТАЮТ, а переходник его не несёт — страница "
                     f"напечатает «undefined» молча; читатели: "
                     f"{', '.join(result['read_through_view'].get(p, []))}")
    if result["unmeasured"]:
        lines.append(f"  [НЕ ИЗМЕРЕНО] дорог без вердикта: {len(result['unmeasured'])} — "
                     f"это НЕ ноль и НЕ находка")
        for item in result["unmeasured"]:
            lines.append(f"      · {item}")
    if not result["findings"]:
        lines.append("  ✅ ни один ЧИТАЕМЫЙ путь переходник не теряет")
    lines.append("  прибор только ЧИТАЕТ: ни переходника, ни снимка, ни страниц не правит")
    return "\n".join(lines)


def main(argv=None) -> int:
    doc = __doc__ or ""
    ap = argparse.ArgumentParser(description=doc.splitlines()[0] if doc else None)
    ap.add_argument("--repo-root", default=None,
                    help="дерево замера; умолчание — дерево прибора, и оно ПЕЧАТАЕТСЯ")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    ap.add_argument("--no-view-shape", action="store_true",
                    help="не снимать форму переходника (без `node`); о потере полей не судить")
    ap.add_argument("--path", default=None, help="спросить про ОДИН путь снимка")
    args = ap.parse_args(argv)

    if args.repo_root:
        root = Path(args.repo_root).expanduser()
        if not root.is_dir():
            print(f"НЕ ИЗМЕРЕНО: названное дерево не прочитано — {root}", file=sys.stderr)
            return 2
        chosen = f"НАЗВАНО входом: {root}"
    else:
        root = Path(__file__).resolve().parents[1]
        chosen = f"УМОЛЧАНИЕ (дерево прибора): {root}"

    try:
        result = measure(root, want_view_shape=not args.no_view_shape)
    except NotMeasured as exc:
        print(f"НЕ ИЗМЕРЕНО: {exc}  [{chosen}]", file=sys.stderr)
        return 2

    result["tree_choice"] = chosen
    if args.path:
        verdict = result["verdict"].get(args.path)
        if verdict is None:
            print(f"НЕ ИЗМЕРЕНО: пути {args.path} в снимке нет  [{chosen}]", file=sys.stderr)
            return 2
        readers = (result["read_through_view"].get(args.path)
                   or result["read_from_raw_snapshot"].get(args.path) or [])
        print(f"{args.path}: {verdict}" + (f" — {', '.join(readers)}" if readers else ""))
        return 1 if args.path in result["findings"] else 0

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=sorted))
    else:
        print(f"{chosen}\n{format_report(result)}")
    return 1 if result["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
