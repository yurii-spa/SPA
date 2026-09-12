#!/usr/bin/env python3
"""Перепись зовов git в SHELL-скриптах по ИСТОЧНИКУ каталога запуска (ЗАКАЗ #576).

ADR-354 пересчитал зовы git в python-части и честно назвал вне замера **183
shell-скрипта**: AST их не разбирает. Это НЕ «у них чисто» — это «не смотрели».
Здесь смотрим.

Вопрос заказа: у скольких зовов каталог запуска делает путь неверным?

**Ловушка здесь ДРУГАЯ, чем в python**, и названа заказом заранее: в shell каталог
задаётся не параметром, а СОСТОЯНИЕМ — `cd` в теле, `cd` в вызывающей обёртке,
`WorkingDirectory` в launchd-plist, наследование от позвавшего. Поэтому:

* «в скрипте есть `cd`» — ПРИЗНАК, и он ошибается в обе стороны: `cd` может стоять
  ПОСЛЕ зова или в неисполняемой ветке; а его ОТСУТСТВИЕ не означает ambient —
  обёртку мог позвать launchd с `WorkingDirectory`;
* единица учёта — **ЗОВ, а не файл**: каталог у shell-скрипта меняется ВНУТРИ файла;
* первый результат — **НАСЕЛЕНИЕ ПО ИСТОЧНИКУ** каталога (сам · plist · обёртка ·
  не задан ничем), и предмет — только последняя группа.

Чувствительность (слеп ли зов) устанавливается НАБЛЮДЕНИЕМ и заимствована у
ADR-354 целиком: форма гоняется в одноразовой копии из корня и из подкаталога,
ответы сравниваются. Своего мнения про git у прибора нет.

Коды возврата (ADR-347): 0 — предмет пуст · 3 — есть доказанно слепые зовы ·
2 — НЕ ИЗМЕРЕНО с названной причиной. 1 оставлен CPython, чтобы падение прибора
никогда не выглядело его находкой.
"""
from __future__ import annotations

import os
import re
import sys
import json
import plistlib
import argparse
import tempfile
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from git_path_coordinate_census import (       # noqa: E402
    DYNAMIC, PATH_PLACEHOLDER, build_probe_repo, observe_sensitivity,
    classify, _subcommand,
)

# ─────────────────────────────── лексика shell ───────────────────────────────

# Операторы, после которых начинается НОВАЯ команда.
CMD_START_OPS = {";", "&", "|", "&&", "||", ";;", "\n", "(", "{", "|&"}
# Слова, после которых начинается новая команда.
# После этих слов начинается КОМАНДА. `if`/`while`/`until` тут обязательны:
# без них `if git diff --quiet && …` теряет первый из трёх зовов строки —
# ровно та ошибка «в меньшую сторону», которой грешит и греп.
CMD_START_WORDS = {"then", "do", "else", "elif", "!", "time", "{", "}",
                   "if", "while", "until"}
ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\+?=")

OPEN_BLOCK = {"if", "for", "while", "until", "case", "select"}
# Слова, которые СТРУКТУРИРУЮТ, но командами не являются.
STRUCTURAL = {"then", "do", "else", "elif", "!", "time", "in"}
CLOSE_BLOCK = {"fi", "done", "esac"}

REDIR_OPS = {">", ">>", "<", "<<", "<<<", ">&", "<&", "2>", "2>>", "&>"}


class Lexer:
    """Токенизатор ровно той глубины, какая нужна вопросу.

    Он обязан различать ЗОВ и УПОМИНАНИЕ: `echo "git commit --no-verify"` — не зов,
    а `[ -z "$(git ls-files)" ]` — зов, спрятанный внутри строки. Оба случая живут
    в наборе, и греп ошибается на них в РАЗНЫЕ стороны.
    """

    def __init__(self, text: str, line0: int = 1):
        self.text = text
        self.i = 0
        self.n = len(text)
        self.line = line0
        self.toks: list[tuple[str, str, int]] = []   # (текст, вид, строка)
        self.pending: list[tuple[str, int]] = []     # вложенные подстановки

    # — чтение слова со всеми видами кавычек и подстановок —

    def _dollar(self):
        """`$(...)`, `${...}`, `$NAME`. Подстановка команд УХОДИТ В pending:
        внутри неё живут настоящие зовы git."""
        t, n = self.text, self.n
        i = self.i
        if t.startswith("$(", i):
            depth, j = 1, i + 2
            while j < n and depth:
                if t[j] == "(":
                    depth += 1
                elif t[j] == ")":
                    depth -= 1
                elif t[j] == "\\":
                    j += 1
                j += 1
            inner = t[i + 2:j - 1]
            self.pending.append((inner, self.line))
            self.line += t[i:j].count("\n")
            self.i = j
            return DYNAMIC
        if t.startswith("${", i):
            depth, j = 1, i + 2
            while j < n and depth:
                if t[j] == "{":
                    depth += 1
                elif t[j] == "}":
                    depth -= 1
                elif t[j] == "\\":
                    j += 1
                j += 1
            inner = t[i + 2:j - 1]
            # `${1:-$(git rev-parse …)}` — зов внутри раскрытия параметра.
            # Подстановка отдаётся pending ЦЕЛИКОМ вместе с обрамлением: её
            # разберёт тот же лексер, и вложенный зов не потеряется.
            if "$(" in inner or "`" in inner:
                self.pending.append((inner, self.line))
            self.line += t[i:j].count("\n")
            self.i = j
            return DYNAMIC
        j = i + 1
        while j < n and (t[j].isalnum() or t[j] == "_"):
            j += 1
        self.i = max(j, i + 1)
        return DYNAMIC

    def _dquote(self):
        """Двойные кавычки: текст литерален, но подстановки внутри ЖИВЫ."""
        t, n = self.text, self.n
        self.i += 1
        out = []
        while self.i < n and t[self.i] != '"':
            ch = t[self.i]
            if ch == "\\" and self.i + 1 < n:
                out.append(t[self.i + 1])
                self.i += 2
                continue
            if ch == "$":
                out.append(self._dollar())
                continue
            if ch == "`":
                out.append(self._backtick())
                continue
            if ch == "\n":
                self.line += 1
            out.append(ch)
            self.i += 1
        self.i += 1
        return "".join(out)

    def _backtick(self):
        t, n = self.text, self.n
        j = self.text.find("`", self.i + 1)
        if j < 0:
            j = n
        self.pending.append((t[self.i + 1:j], self.line))
        self.line += t[self.i:j].count("\n")
        self.i = j + 1
        return DYNAMIC

    def _word(self):
        t, n = self.text, self.n
        out = []
        while self.i < n:
            ch = t[self.i]
            if ch in " \t\n" or ch in ";&|()<>":
                break
            if ch == "\\":
                if self.i + 1 < n and t[self.i + 1] == "\n":
                    self.i += 2
                    self.line += 1
                    continue
                if self.i + 1 < n:
                    out.append(t[self.i + 1])
                    self.i += 2
                    continue
                self.i += 1
                continue
            if ch == "'":
                j = t.find("'", self.i + 1)
                if j < 0:
                    j = n
                seg = t[self.i + 1:j]
                self.line += seg.count("\n")
                out.append(seg)
                self.i = j + 1
                continue
            if ch == '"':
                out.append(self._dquote())
                continue
            if ch == "$":
                out.append(self._dollar())
                continue
            if ch == "`":
                out.append(self._backtick())
                continue
            out.append(ch)
            self.i += 1
        return "".join(out)

    def _eat_heredocs(self, pending):
        """Проглотить тела heredoc'ов, начинающихся после этой строки.

        Без этого тело `<<'PYEOF' … PYEOF` (у нас там ПИТОН) разбирается как shell:
        его фигурные скобки ломают счёт функций, а любое слово `git` в нём становится
        зовом, которого нет. Ошибка в ОБЕ стороны из одного упущения."""
        t, n = self.text, self.n
        while pending:
            delim, strip_tabs = pending.pop(0)
            while self.i < n:
                eol = t.find("\n", self.i)
                if eol < 0:
                    eol = n
                line_txt = t[self.i:eol]
                self.i = eol + 1 if eol < n else n
                self.line += 1
                probe = line_txt.strip() if strip_tabs else line_txt.rstrip("\r")
                if probe.strip() == delim:
                    break

    def run(self):
        t, n = self.text, self.n
        at_word_start = True
        heredocs = []
        while self.i < n:
            ch = t[self.i]
            if ch == "\n":
                self.toks.append(("\n", "op", self.line))
                self.line += 1
                self.i += 1
                at_word_start = True
                if heredocs:
                    self._eat_heredocs(heredocs)
                continue
            if ch in " \t":
                self.i += 1
                at_word_start = True
                continue
            if ch == "\\" and self.i + 1 < n and t[self.i + 1] == "\n":
                self.i += 2
                self.line += 1
                continue
            if ch == "#" and at_word_start:
                while self.i < n and t[self.i] != "\n":
                    self.i += 1
                continue
            if t.startswith("<<<", self.i):          # here-string, не heredoc
                self.toks.append(("<<<", "op", self.line))
                self.i += 3
                at_word_start = True
                continue
            if t.startswith("<<", self.i):
                self.i += 2
                strip_tabs = False
                if self.i < n and t[self.i] == "-":
                    strip_tabs = True
                    self.i += 1
                while self.i < n and t[self.i] in " \t":
                    self.i += 1
                line_at = self.line
                delim = self._word()
                heredocs.append((delim.strip(), strip_tabs))
                # Ограничитель выдаётся ТОКЕНОМ, хотя тело уже проглочено: сборка
                # argv пропускает после оператора перенаправления ровно два токена,
                # и без ограничителя пропуск съедал перевод строки — команда
                # продолжалась через весь heredoc и хватала чужие слова.
                self.toks.append(("<<", "op", line_at))
                self.toks.append((delim.strip(), "word", line_at))
                at_word_start = True
                continue
            two = t[self.i:self.i + 2]
            if two in ("&&", "||", ";;", "|&", ">>", "2>", "&>"):
                self.toks.append((two, "op", self.line))
                self.i += 2
                at_word_start = True
                continue
            if ch in ";&|()<>":
                self.toks.append((ch, "op", self.line))
                self.i += 1
                at_word_start = True
                continue
            line_at = self.line
            w = self._word()
            if w != "":
                self.toks.append((w, "word", line_at))
            at_word_start = False
        return self.toks, self.pending


# ──────────────────── зовы и смена каталога внутри файла ────────────────────

def parse_commands(text: str, line0: int = 1, scope_prefix: str = "0"):
    """Разобрать источник в список команд с ГЛУБИНОЙ и признаком условности.

    Возвращает (команды, вложенные-подстановки). Команда:
      {argv, line, depth, in_func, conditional}

    `conditional` — команда является ПРАВЫМ операндом `&&`/`||`, то есть может
    не исполниться. Для `cd` это решающее: `[ -d x ] && cd x` каталог не меняет
    гарантированно, а `cd x || exit 1` — меняет (там условен выход, не `cd`)."""
    lex = Lexer(text, line0)
    toks, pending = lex.run()

    cmds = []
    func_ranges = []           # (имя, строка-начала, строка-конца)
    depth = 0
    cond_region = 0            # глубина, на которой идёт УСЛОВИЕ if/while/until
    cond_is_elif = False
    # Подоболочка `( … )` — СОБСТВЕННЫЙ каталог: `cd` внутри неё не переживает
    # закрывающую скобку. Без этого `SCRIPT_DIR="$( cd "$(dirname …)" && pwd )"`
    # (идиома из `auto_push.sh`) господствовал бы над всем, что ниже по файлу.
    scope_stack = [scope_prefix] if scope_prefix else ["0"]
    scope_seq = 0
    func_stack = []            # (имя, уровень скобок, строка) — функции вкладываются
    pending_func = None        # имя функции, чьё `{` ещё не встречено
    brace = 0
    i = 0
    prev_sig = None            # предыдущий значимый токен
    conditional_next = False

    def is_cmd_pos(prev):
        if prev is None:
            return True
        txt, kind = prev
        if kind == "op":
            return txt in CMD_START_OPS
        return txt in CMD_START_WORDS or bool(ASSIGN_RE.match(txt))

    while i < len(toks):
        txt, kind, line = toks[i]
        if kind == "op":
            if txt == "(" and not pending_func:
                scope_seq += 1
                scope_stack.append(scope_stack[-1] + "/" + str(scope_seq))
            elif txt == ")" and len(scope_stack) > 1:
                scope_stack.pop()
            if txt in ("&&", "||"):
                conditional_next = True
            elif txt in (";", "\n", "&", "|", ";;", "|&", "(", ")"):
                conditional_next = False
            prev_sig = (txt, kind)
            i += 1
            continue

        cmd_pos = is_cmd_pos(prev_sig)

        if cmd_pos and txt in OPEN_BLOCK:
            depth += 1
            # УСЛОВИЕ `if`/`while`/`until` исполняется всегда — это не ветка.
            # `if ! cd "$REPO_DIR"; then …` меняет каталог гарантированно, и
            # ровно так написан `git_autopush.sh`: пока условие считалось телом,
            # ВСЕ 19 его зовов числились «`cd` не доказан». Вердикт был свойством
            # прибора, а не кода.
            if txt in ("if", "while", "until"):
                cond_region, cond_is_elif = depth, False
        elif cmd_pos and txt == "elif":
            # А вот условие `elif` исполняется, только если прошлая ветка не
            # сошлась — оно УСЛОВНО, и уравнивать его с `if` значит изготовить
            # доказательство из ничего.
            cond_region, cond_is_elif = depth, True
        elif cmd_pos and txt in ("then", "do"):
            cond_region, cond_is_elif = 0, False
        elif cmd_pos and txt in CLOSE_BLOCK:
            depth = max(0, depth - 1)
            cond_region, cond_is_elif = 0, False

        # `{` и `}` приходят СЛОВАМИ, а не операторами: в наборе символов
        # оператора их нет. Пока они разбирались как команды, счётчик скобок не
        # двигался вовсе и ни одна функция не опознавалась.
        if txt == "{":
            brace += 1
            if pending_func is not None:
                func_stack.append((pending_func, brace, line))
                pending_func = None
            prev_sig = ("{", "word")
            i += 1
            continue
        if txt == "}":
            if func_stack and func_stack[-1][1] == brace:
                done = func_stack.pop()
                func_ranges.append((done[0], done[2], line))
            brace = max(0, brace - 1)
            prev_sig = ("}", "word")
            i += 1
            continue

        # СЛУЖЕБНЫЕ слова и префиксы — не команды. `!` съедал
        # `git checkout … -- <пути>` целиком (строка 214 `code_sync_from_origin.sh`,
        # мутирующий зов с путём — самый предмет заказа), а `then` тем же способом
        # съедал `cd` из ветки `if`, и ветка переставала существовать для прибора:
        # зов уезжал в «ambient» вместо «`cd` не доказан». Один дефект — ошибка в
        # обе стороны сразу.
        if cmd_pos and (txt in STRUCTURAL or ASSIGN_RE.match(txt)):
            prev_sig = (txt, "word")
            i += 1
            continue

        # определение функции: `name() {` или `function name {`. Имя нужно не для
        # красоты: `cd` наверху тела функции доказанно исполняется до зова В ТОЙ ЖЕ
        # функции, и без имени этот случай попадал в «не доказано» — а он и есть
        # главный в наборе (`main() { cd "$REPO" … }`).
        is_func_def = False
        if cmd_pos and i + 1 < len(toks) and toks[i + 1][0] == "(":
            if i + 2 < len(toks) and toks[i + 2][0] == ")":
                pending_func = txt
                is_func_def = True
        if cmd_pos and txt == "function" and i + 1 < len(toks):
            pending_func = toks[i + 1][0]

        # ОПРЕДЕЛЕНИЕ функции — не её зов. Пока `name() {` считалось зовом, вторая
        # дорога доказательства мерила лишнюю точку: определение стои́т там, где
        # его написали, а не там, где функцию зовут, и `cd` между ними решает
        # вопрос в другую сторону.
        if cmd_pos and not is_func_def and txt not in OPEN_BLOCK and txt not in CLOSE_BLOCK:
            argv = [txt]
            j = i + 1
            while j < len(toks):
                t2, k2, _ = toks[j]
                if k2 == "op":
                    if t2 in REDIR_OPS:
                        j += 2          # оператор и его цель — не аргументы
                        continue
                    break
                argv.append(t2)
                j += 1
            in_cond = cond_region == depth and depth > 0
            cmds.append({
                "argv": argv, "line": line,
                # В условии команда живёт на ОБЪЕМЛЮЩЕЙ глубине: она исполняется
                # до всякого ветвления.
                "depth": depth - 1 if in_cond else depth,
                "in_condition": in_cond,
                "scope": scope_stack[-1],
                "in_func": bool(func_stack),
                "func": func_stack[-1][0] if func_stack else None,
                "conditional": conditional_next or (in_cond and cond_is_elif),
            })
            prev_sig = (toks[j - 1][0], "word")
            i = j
            conditional_next = False
            continue

        prev_sig = (txt, kind)
        i += 1

    for name, start, _ in func_stack:          # функция без закрывающей скобки
        func_ranges.append((name, start, 10 ** 9))
    return cmds, pending, func_ranges


_INVOCATIONS: dict[str, list] = {}


def collect_calls(sh_path: Path, repo_root: Path):
    """Все зовы git и все смены каталога в одном скрипте.

    Возвращает (зовы, смены-каталога, причина-НЕ-ИЗМЕРЕНО|None)."""
    try:
        text = sh_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [], [], f"{sh_path} не прочитан: {exc}"

    rel = str(sh_path.relative_to(repo_root))
    git_calls, cds = [], []
    invocations = []
    queue = [(text, 1, False, "0")]
    func_ranges: list = []
    guard = 0
    while queue:
        guard += 1
        if guard > 5000:
            return git_calls, cds, f"{rel}: разбор не сошёлся (вложенность подстановок)"
        src, line0, nested, prefix = queue.pop()
        try:
            cmds, pending, ranges = parse_commands(src, line0, prefix)
        except (RecursionError, ValueError) as exc:
            return git_calls, cds, f"{rel} не разобран: {exc}"
        func_ranges.extend(ranges)

        def scope_at(ln):
            """Подоболочка, действовавшая в РОДИТЕЛЕ на строке подстановки.

            Она и есть предок для всего, что внутри подстановки: `$( … )` наследует
            каталог того места, где написана."""
            best = prefix
            for cm in cmds:
                if cm["line"] <= ln:
                    best = cm["scope"]
            return best

        for n, (sub_src, sub_line) in enumerate(pending):
            # Подстановка САМА есть подоболочка, поэтому её область — ПОТОМОК
            # родительской, а не она же. Иначе `cd` внутри `$( … )` оказывается в
            # одной области с тем, что стои́т ниже по файлу, и снова господствует
            # над ним — та же ошибка, только через другую дверь.
            queue.append((sub_src, sub_line, True,
                          f"{scope_at(sub_line)}/sub{guard}_{n}"))
        for c in cmds:
            head = c["argv"][0]
            if head in ("cd", "pushd"):
                cds.append({**c, "file": rel})
            elif head == "git" or head.endswith("/git"):
                git_calls.append({**c, "file": rel, "nested": nested,
                                  "path_exprs": []})
            else:
                invocations.append({**c, "file": rel})
    # Зов внутри `$(…)` разбирается ОТДЕЛЬНЫМ источником и своей функции не знает.
    # Без восстановления области `cd` наверху `main` переставал доказуемо
    # господствовать над зовом, стоящим внутри подстановки в той же `main`, —
    # и зов уезжал в «не доказано» по свойству ПРИБОРА, а не кода.
    def enclosing(line):
        best = None
        for name, start, end in func_ranges:
            if start <= line <= end and (best is None or start > best[1]):
                best = (name, start)
        return best[0] if best else None

    # Восстановление области нужно и ЗОВАМ ДРУГИХ СКРИПТОВ/ФУНКЦИЙ: без него
    # `RETIRED=$(retired_instructions)` разбирается отдельным источником, его
    # область теряется, и вторая дорога доказательства не находит своего сайта.
    for c in git_calls + cds + invocations:
        if c["func"] is None:
            c["func"] = enclosing(c["line"])
    git_calls.sort(key=lambda c: (c["line"], c["argv"]))
    cds.sort(key=lambda c: c["line"])
    _INVOCATIONS[rel] = invocations
    return git_calls, cds, None


# ──────────────── источник каталога: сам · plist · обёртка · ничто ────────────────

def _plist_index(roots):
    """script-path → список plist'ов, что его запускают, и их WorkingDirectory.

    Читаются и ДОСТАВЛЕННЫЕ (`launchd/`, `scripts/`) и УСТАНОВЛЕННЫЕ
    (`~/Library/LaunchAgents`) паспорта: работает второй, а доставляется первый,
    и расхождение между ними — само по себе улика (правило доставки)."""
    index, unread = {}, []
    for root in roots:
        if not root.exists():
            continue
        for p in sorted(root.rglob("*.plist")):
            try:
                with p.open("rb") as fh:
                    doc = plistlib.load(fh)
            except (OSError, ValueError, plistlib.InvalidFileException) as exc:
                unread.append(f"{p}: {exc}")
                continue
            if not isinstance(doc, dict):
                unread.append(f"{p}: не словарь")
                continue
            wd = doc.get("WorkingDirectory")
            args = doc.get("ProgramArguments") or []
            if isinstance(doc.get("Program"), str):
                args = [doc["Program"]] + list(args)
            for a in args:
                if not isinstance(a, str) or not a.endswith(".sh"):
                    continue
                index.setdefault(Path(a).name, []).append(
                    {"plist": str(p), "wd": wd, "installed": "LaunchAgents" in str(p)})
    return index, unread


def _caller_index(repo_root: Path, sh_files):
    """basename скрипта → кто его РЕАЛЬНО ЗОВЁТ, с признаком «зовущий сам сменил
    каталог ДО зова».

    Ключевое слово — зовёт, а не упоминает. Первая редакция искала имя скрипта в
    ТЕКСТЕ файла и потому считала обёрткой каждый тест, который про него пишет:
    `code_sync_from_origin.sh` упоминают девять тест-файлов и ни один его не
    запускает. Классификация по имени ошибается в обе стороны — ровно тот дефект,
    который ADR-354 нашёл у себя, и он воспроизвёлся здесь до первой проверки.

    Тесты называются отдельно и обёрткой НЕ считаются: тест задаёт каталог сам и
    про прод не свидетельствует."""
    names = {p.name for p in sh_files}
    callers = {n: [] for n in names}
    for p in sorted(repo_root.rglob("*.sh")):
        if SKIP_PARTS & set(p.parts) or p.name not in names:
            continue
        _, cds, err = collect_calls(p, repo_root)
        if err:
            continue
        rel = str(p.relative_to(repo_root))
        is_test = "test" in p.name or "tests" in p.parts
        for inv in _INVOCATIONS.get(rel, []):
            for tok in inv["argv"]:
                base = Path(tok).name
                if base not in names or base == p.name:
                    continue
                proven, _why = dominating_cd(cds, inv, _INVOCATIONS.get(rel, []))
                callers[base].append({"caller": rel, "line": inv["line"],
                                      "sets_cwd": proven is not None,
                                      "is_test": is_test})
    return callers, 0


def _sane_cd(c, call):
    """`cd`, который исполнится, если до него дошли, И чей эффект доживает до зова.

    Три условия: не внутри `if`/`for`/`case` · не правый операнд `&&`/`||` · его
    подоболочка ОБЪЕМЛЕТ подоболочку зова.

    Отношение подоболочек несимметрично, и обе стороны важны. Дочерняя оболочка
    НАСЛЕДУЕТ каталог родителя — поэтому `cd` наверху `main()` действует и внутри
    `RETIRED=$(retired_instructions)`. Но изменить каталог родителю она не может —
    поэтому `SCRIPT_DIR="$( cd "$(dirname …)" && pwd )"` (идиома из `auto_push.sh`)
    не меняет каталог ничему, что стои́т ниже по файлу. Равенство подоболочек ловит
    вторую половину и теряет первую; предок-или-сам ловит обе."""
    return (c["depth"] == 0 and not c["conditional"]
            and str(call.get("scope", "")).startswith(str(c.get("scope", "\x00"))))


def dominating_cd(cds, call, invocations=(), _seen=None):
    """`cd`, про который ДОКАЗАНО, что он исполнился до зова.

    Две дороги доказательства, и вторая обязательна — без неё прибор отвечает
    верно по чужой причине:

    1. `cd` В ТОЙ ЖЕ функции (или оба на верхнем уровне), строкой выше, исполнимый.
       Весь набор написан как `main() { cd "$REPO"; … }`, поэтому правило «внутри
       функции — не доказано» отправляло бы в «не доказано» самый доказанный случай.

    2. Зов лежит в функции G, а `cd` — в позвавшей её функции. Тогда каталог задан,
       если КАЖДЫЙ зов G в файле сам господствуем (рекурсивно). Ровно так устроен
       `code_sync_from_origin.sh`: `cd "$REPO"` наверху `main`, а пути читают
       `retired_instructions` и `drift_split`, которые `main` зовёт ниже. Без этой
       дороги все три зова объявлялись «обёрткой» — вердикт верный, причина чужая,
       и держался он на постороннем файле.

    «Ни одна дорога не сошлась» — это НЕ «каталога нет», а «не доказано»."""
    _seen = _seen or set()
    before = [c for c in cds if c["line"] < call["line"]]
    same = [c for c in before if _sane_cd(c, call) and c["func"] == call["func"]]
    if same:
        return same[-1], f"`cd` строкой {same[-1]['line']} в той же области"

    fn = call["func"]
    if fn and fn not in _seen:
        sites = [i for i in invocations if i["argv"] and i["argv"][0] == fn]
        if sites:
            chain = []
            for site in sites:
                got, why = dominating_cd(cds, site, invocations, _seen | {fn})
                if not got:
                    break
                chain.append((site, got, why))
            else:
                site, got, why = chain[0]
                return got, (f"`cd` строкой {got['line']}: {fn}() зовётся строкой "
                             f"{site['line']}, и каждый её зов ({len(sites)}) господствуем")
    return None, None


def cwd_source(call, cds, plists, callers, invocations=()):
    """Один из пяти исходов. Порядок проверки — от самого сильного знания."""
    if "-C" in call["argv"]:
        return "pinned_at_call", "зов несёт `-C`: каталог задан самим зовом"
    proven, why = dominating_cd(cds, call, invocations)
    if proven:
        return "self", why
    unproven = [c for c in cds if c["line"] < call["line"]]
    entries = plists.get(Path(call["file"]).name, [])
    with_wd = [e for e in entries if e["wd"]]
    if with_wd:
        where = "установленный" if any(e["installed"] for e in with_wd) else "доставленный"
        return "plist", f"launchd задаёт WorkingDirectory={with_wd[0]['wd']} ({where} паспорт)"
    entries_c = [c for c in callers.get(Path(call["file"]).name, []) if not c["is_test"]]
    setters = [c for c in entries_c if c["sets_cwd"]]
    if setters:
        return "wrapper", (f"позвавший {setters[0]['caller']}:{setters[0]['line']} "
                           f"сам сменил каталог до зова")
    if entries_c:
        return "wrapper_no_cwd", (f"скрипт зовёт {entries_c[0]['caller']}, но каталог "
                                  f"НЕ задаёт — вопрос уезжает к нему")
    if unproven:
        return "unproven_cd", (f"`cd` в файле есть ({len(unproven)} до зова), но ни один не "
                               f"доказан: ветка, функция или правый операнд `&&`/`||`")
    if entries:
        return "plist_no_wd", "launchd запускает скрипт, но WorkingDirectory не задан"
    return "ambient", "каталог не задан ничем: наследуется от позвавшего"


# ─────────────────────────────── перепись ───────────────────────────────

SKIP_PARTS = {".git", "node_modules", ".claude", "attic"}

# Источники, при которых каталог зова НЕ ОПРЕДЕЛЁН. Все они — предмет наблюдения.
UNDETERMINED = {"ambient", "unproven_cd", "plist_no_wd", "wrapper_no_cwd"}


def shell_files(repo_root: Path):
    out = []
    for p in sorted(repo_root.rglob("*.sh")):
        if SKIP_PARTS & set(p.parts):
            continue
        out.append(p)
    return out


def census(repo_root: Path, observe: bool = True):
    files = shell_files(repo_root)
    plists, plist_unread = _plist_index([
        repo_root / "launchd", repo_root / "scripts",
        Path.home() / "Library" / "LaunchAgents"])
    callers, _ = _caller_index(repo_root, files)

    calls, unread = [], list(plist_unread)
    for p in files:
        got, cds, err = collect_calls(p, repo_root)
        if err:
            unread.append(err)
            continue
        for c in got:
            c["roles"] = classify(c)
            c["cwd_source"], c["cwd_why"] = cwd_source(
                c, cds, plists, callers, _INVOCATIONS.get(str(p.relative_to(repo_root)), []))
            calls.append(c)

    # Предмет класса — зов, НЕСУЩИЙ путь от каталога запуска, чей каталог НЕ
    # ОПРЕДЕЛЁН. Зов без такого пути в класс не входит вовсе: «каталог не задан»
    # само по себе не дефект.
    #
    # Не определён — это НЕ только «не задан ничем». `cd`, который есть, но не
    # доказан (ветка, подоболочка, `elif`), — та же неопределённость, и
    # выбрасывать его из наблюдения значило бы сложить «не доказано» в «в
    # порядке»: ровно тот дефект, против которого написан инвариант #17.
    subject = [c for c in calls
               if c["cwd_source"] in UNDETERMINED and c["roles"]["pathspec"]
               and not c["roles"]["absolute_only"]]

    observed = []
    if observe and subject:
        with tempfile.TemporaryDirectory(prefix="shcensus-") as td:
            tmp = Path(td)
            pristine = tmp / "pristine"
            pristine.mkdir()
            env = build_probe_repo(pristine)
            scratch = tmp / "scratch"
            scratch.mkdir()
            for c in subject:
                verdict, why = observe_sensitivity(c["argv"], c["roles"],
                                                   pristine, env, scratch)
                observed.append({**c, "sensitivity": verdict, "why": why})
    elif subject:
        observed = [{**c, "sensitivity": "unmeasured",
                     "why": "наблюдение выключено ключом --no-observe"}
                    for c in subject]

    blind = [c for c in observed if c["sensitivity"] == "sensitive"]
    unmeasured = [c for c in observed if c["sensitivity"] == "unmeasured"]

    return {"files": len(files), "calls": calls, "subject": subject,
            "observed": observed, "blind": blind, "unmeasured": unmeasured,
            "unread": unread}


def grep_control(repo_root: Path):
    """Контрольный ПРИЗНАК — ровно тот, которым соблазняет заказ.

    Печатается рядом с замером не для красоты: разность двух чисел и есть
    доказательство, что греп ошибается в ОБЕ стороны, а не рассуждение о том,
    что мог бы."""
    pat = re.compile(r"(^|[^A-Za-z0-9_./-])git\s")
    lines = 0
    for p in shell_files(repo_root):
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for ln in text.split("\n"):
            if ln.lstrip().startswith("#"):
                continue
            if pat.search(ln):
                lines += 1
    return lines


ORDER = ["ambient", "unproven_cd", "wrapper_no_cwd", "plist_no_wd", "wrapper",
         "plist", "self", "pinned_at_call"]
TITLE = {"ambient": "не задан НИЧЕМ (предмет)", "unproven_cd": "`cd` есть, но НЕ ДОКАЗАН",
         "plist_no_wd": "launchd без WorkingDirectory", "wrapper": "обёртка",
         "wrapper_no_cwd": "обёртка, каталог НЕ задающая",
         "plist": "plist (WorkingDirectory)", "self": "сам (`cd` в теле)",
         "pinned_at_call": "сам зов (`-C`)"}


def render(r) -> str:
    out = []
    add = out.append
    add("── перепись зовов git в shell-скриптах по ИСТОЧНИКУ каталога (ЗАКАЗ #576) ──")
    add(f"скриптов прочитано: {r['files']} · зовов git найдено: {len(r['calls'])}")
    add("")
    add("НАСЕЛЕНИЕ ПО ИСТОЧНИКУ КАТАЛОГА (единица — ЗОВ, не файл):")
    counts = {}
    for c in r["calls"]:
        counts[c["cwd_source"]] = counts.get(c["cwd_source"], 0) + 1
    for key in ORDER:
        if counts.get(key):
            add(f"   {counts[key]:>4}  {TITLE[key]}")
    add("")
    add(f"ПРЕДМЕТ: зовов с НЕОПРЕДЕЛЁННЫМ каталогом, несущих путь, — {len(r['subject'])}")
    if r["observed"]:
        add(f"   доказанно СЛЕПЫХ (ответ меняется от каталога): {len(r['blind'])}")
        add(f"   устойчивых: {len(r['observed']) - len(r['blind']) - len(r['unmeasured'])}"
            f" · НЕ ИЗМЕРЕНО: {len(r['unmeasured'])}")
        for c in r["blind"]:
            add(f"   🔴 {c['file']}:{c['line']}  git {' '.join(c['argv'][1:])[:70]}")
            add(f"      каталог: {c['cwd_why']}")
        for c in r["unmeasured"]:
            add(f"   ⚪ {c['file']}:{c['line']}  НЕ ИЗМЕРЕНО: {c['why']}")
    if r["unread"]:
        add("")
        add(f"НЕ ПРОЧИТАНО (третий исход, не «чисто»): {len(r['unread'])}")
        for u in r["unread"][:10]:
            add(f"   ⚪ {u}")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=None)
    ap.add_argument("--no-observe", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--grep-control", action="store_true",
                    help="напечатать рядом ПРИЗНАК (строк с `git`), которым соблазняет заказ")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    if not (root / ".git").exists():
        print(f"НЕ ИЗМЕРЕНО: {root} не похож на рабочую копию репозитория", file=sys.stderr)
        return 2

    r = census(root, observe=not args.no_observe)
    if args.json:
        print(json.dumps({
            "files": r["files"], "calls": len(r["calls"]),
            "by_source": {k: sum(1 for c in r["calls"] if c["cwd_source"] == k)
                          for k in ORDER},
            "subject": len(r["subject"]), "blind": len(r["blind"]),
            "unmeasured": len(r["unmeasured"]), "unread": r["unread"],
        }, ensure_ascii=False, indent=2))
    else:
        print(render(r))
        if args.grep_control:
            print("")
            print(f"ПРИЗНАК для сравнения: строк с `git ` по грепу — {grep_control(root)}"
                  f" · зовов по разбору — {len(r['calls'])}")

    if r["unread"]:
        return 2
    if r["blind"]:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
