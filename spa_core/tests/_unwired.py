"""Кто из скриптов с точкой входа никем не вызывается.

Вынесено отдельно, чтобы храповик и его база считались ОДНИМ кодом: база,
построенная другой функцией, разойдётся с проверкой при первой же правке.

**Два разных вопроса, и путать их нельзя.**

- `scripts_without_caller()` — «его кто-нибудь ЗОВЁТ?» (plist, обёртка, модуль,
  workflow). Сырое измерение, ничего не прощает.
- `unwired_scripts()` — «он доставлен и МЁРТВ?» То, ради чего заведён храповик.
  Отсюда вычтен класс, у которого вызывающего нет ПО УСТРОЙСТВУ: исследовательский
  замер, который запускают руками, а его продукт — запись в реестре R&D-идей
  `docs/DYNAMIC_LEVERAGE_GUARDIAN.md`.

**Почему засчитывается ТОЛЬКО реестр, а не любой файл в `docs/`** (замер 13.08,
цикл #214): скриптов без вызывающего 88; имя хотя бы одного из них встречается
где-нибудь в `docs/` у **62** — считать весь `docs/` проводкой значит снять с учёта
две трети подопечных. У **пяти** единственное упоминание — в `docs/journal/`, то есть
в ЛЕТОПИСИ: журнал называет всё доставленное поимённо и потому не доказывает ничего.
Реестр R&D — другое: попасть в него можно только измерением, и запись в нём и есть
продукт такого скрипта. Это доказательство того же рода, какого проект требует от APY.

**Порядок работ обязан быть именно такой: сперва НАУЧИТЬ видеть вызов, потом
ОТНИМАТЬ доказательства слабее вызова.** Цикл #227 снял слепоту к комментариям и
измерил обратную сторону: «подключёнными» держались ещё 8 скриптов — докстрингом,
самоупоминанием однофамильца и подстрочной коллизией. Чинить это в лоб было бы
ОПАСНЕЕ, чем оставить: `check_tracker_drift` подключён живым
``import check_tracker_drift`` (`scripts/orchestrator_queue.py:198`), а сканер искал
только `<имя>.py` и `scripts.<имя>` — голого импорта он не видел вовсе. Снять
докстринги, не научившись видеть импорт, значило объявить сиротой ежедневно
исполняемый скрипт, то есть покрасить храповик на ЧЕСТНОЙ работе. Поэтому цикл #228
сперва расширил набор распознаваемых форм вызова (`file_references`, разбор импортов
через `ast`), и только затем отнял три слабых доказательства.

**Четвёртая форма прозы — строка-СООБЩЕНИЕ (17.08, цикл #258).** Комментарий (#227),
докстринг и самоупоминание однофамильца (#255) сняты; оставалась строка, которую
программа ПЕЧАТАЕТ человеку: подсказка ``out.append(f"… `scripts/reap_stale_worktrees.py
--worktree …`")`` мгновенно объявляла уборщик подключённым. Чинить это «не считать
литералы вызовом» нельзя — самая частая настоящая форма запуска сама литерал
(`subprocess.run([PY, str(ROOT / "scripts/x.py")])`), поэтому судится СОДЕРЖИМОЕ
литерала, а внутри вызова-исполнителя не судится вовсе (`_message_literal_spans`).
Цена измерена на живом дереве: проводкой по одному упоминанию в тексте держались
**8** скриптов (`audit_protocol_blindness`, `build_dd_snapshot`,
`defenses_exercised_report`, `find_defillama_sources`, `findings_to_cards`,
`optimizer_ab`, `verify_dfb_pool`, `verify_riskwire`); ни одного из них не запускает
никто. Сырое измерение: 96 сирот до, 104 после; ни один подключённый скрипт сиротой
не стал (разность в обратную сторону пуста).

Опт-аут-флага в коде здесь намеренно НЕТ: флаг научил бы сторожа отключать.

**Сведение двух реализаций (17.08).** Сторож три недели жил в ДВУХ независимых
версиях: эта (разбор импортов `ast`, четыре формы ссылки, протокольные команды,
класс «продукт — запись в реестре») и версия автономных циклов Мака
(`wiring_patterns` — пять форм с границами слова с обеих сторон, голый импорт по
`sys.path`, строгий суд однофамильца, дешёвая отсечка первой строкой). Свести их
надо было, ничего не потеряв.

Замер на живом дереве 17.08 показал главное: **сырые вердикты совпадают точно** —
обе версии называют одни и те же 95 скриптов без вызывающего, множества
идентичны (разность в обе стороны пуста). Расхождение в `unwired_scripts` (52
против 55) — это ровно три имени, вычитаемые ЗДЕСЬ двумя классами, которых у той
версии нет (`adr_number`, `reap_stale_worktrees` — команда протокола;
`audit_tier_c_wiring_feasibility` — генератор). То есть по силе обнаружения эта
версия — надмножество, и основой берётся она; замер приведён в отчёте цикла.

Поэтому из версии Мака переносится не движок, а то, чего здесь не было **как
названного и проверяемого понятия**: `wiring_patterns` — одно место, где пять форм
подключения записаны с границами слова с ОБЕИХ сторон, и `is_wiring` — строгий
суд однофамильца с дешёвой отсечкой первой строкой. Обе живут не украшением:
`registry_recorded_scripts` судит реестр R&D именно ими (до сведения он искал имя
ГОЛОЙ подстрокой — та самая подстрочная коллизия, от которой обход дерева уже был
защищён, а вычитаемый класс ещё нет), а `scripts_without_caller_by_patterns` —
второе, независимое мнение о том же дереве; их совпадение закреплено тестом.

**Почему движком остался одиночный проход** (замер 17.08, живое дерево). Пять
регулярок × 101 скрипт × ~1500 файлов — это O(скрипты × файлы); отсечка первой
строкой делает такой перебор терпимым, но не дешёвым: 16.1 с за прогон, и КАЖДЫЙ
прогон заново (повтор — 15.9 с, кэша нет). Одиночный проход извлекает имена из
файла один раз (O(файлы)) и держит разобранное дерево в `_HAY_CACHE`: первый
прогон 19.9–21.1 с, каждый следующий — 0.30 с, полный `unwired_scripts` — 1.8 с.
Отсечка при этом сохранена там, где перебор действительно есть (`is_wiring`,
`registry_recorded_scripts`), и её цена измерена отдельно, а не заявлена.
"""
from __future__ import annotations

import ast
import io
import pathlib
import re
import tokenize
from typing import Dict, List, Optional, Pattern, Set, Tuple

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_HAY_DIRS = ("launchd", "scripts", "spa_core", ".github")
_HAY_SUFFIXES = (".sh", ".plist", ".py", ".yml", ".yaml")

#: Реестр R&D-идей: единственный документ, запись в котором считается проводкой.
_RND_REGISTRY = pathlib.Path("docs") / "DYNAMIC_LEVERAGE_GUARDIAN.md"

#: Протокол цикла: единственный документ, КОМАНДА в котором считается вызовом.
_PROTOCOL_DOC = pathlib.Path("docs") / "ORCHESTRATOR_PROTOCOL.md"

#: XML-комментарий plist'а: `<!-- ... -->` (в plist'ах он многострочный).
_XML_COMMENT = re.compile(r"<!--.*?-->", re.S)

#: Символы, из которых состоит имя модуля. Граница по ним — единственная защита от
#: подстрочной коллизии: `perf_budget` — подстрока `dfb_perf_budget`.
_NAME = r"[A-Za-z0-9_]"


# ────────────────────────────────────────────────────────────────────────────────
# Вырезание прозы: комментарий и докстринг — не вызов
# ────────────────────────────────────────────────────────────────────────────────

def _cut_at_hash(text: str) -> str:
    """Отрезать `#`-комментарии, не трогая `#` внутри кавычек.

    Для `.sh`/`.yml` и как запасной путь для `.py`, который не разобрался
    токенайзером. `#` считается началом комментария только вне кавычек и
    только в начале строки либо после пробела: `"a#b"` и `url#fragment` —
    не комментарии.
    """
    out = []
    for line in text.splitlines():
        quote = None
        cut = None
        for i, ch in enumerate(line):
            if quote is not None:
                if ch == quote:
                    quote = None
                continue
            if ch in "'\"":
                quote = ch
                continue
            if ch == "#" and (i == 0 or line[i - 1].isspace()):
                cut = i
                break
        out.append(line if cut is None else line[:cut])
    return "\n".join(out)


def _char_col(line: str, byte_col: int) -> int:
    """Байтовое смещение `ast` → символьное.

    `ast` отдаёт `col_offset` в БАЙТАХ UTF-8, `tokenize` — в символах. В этом
    репозитории докстринги русские, и путаница смещений вырезала бы кусок строки
    по живому — молча и в середине слова.
    """
    raw = line.encode("utf-8")
    if byte_col >= len(raw):
        return len(line)
    return len(raw[:byte_col].decode("utf-8", errors="ignore"))


def _parse(text: str) -> Optional[ast.AST]:
    """Разобрать питон или `None`. Один разбор на файл — см. `_analyze`.

    Разбор `ast` — самая дорогая операция обхода, и до сведения он делался ДВАЖДЫ
    на один и тот же файл (докстринги и импорты — независимо друг от друга). Замер
    17.08 на живом дереве, два прогона каждой версии: два разбора — 23.4 / 24.9 с
    холодного обхода, один — 21.1 / 19.9 с. Дешевизна здесь того же рода, что
    дешёвая отсечка в `is_wiring`: сторож, который стоит минуты, перестают запускать.
    """
    try:
        return ast.parse(text)
    except (SyntaxError, ValueError):
        return None


def _docstring_spans(text: str, tree: Optional[ast.AST] = None) -> List[Tuple[int, int, int]]:
    """Координаты ДОКСТРИНГОВ: `(строка, начало, конец)` в символах, 1-based.

    Докстринг модуля / класса / функции — проза, и по последствиям он равен
    комментарию: `daily_paper_report` держался комментарием, объяснявшим, что
    скрипт НЕ подключён, а `run_stress_tests` — фразой в докстринге чужого
    модуля. Прочие строковые литералы НЕ трогаются: в них живёт настоящий вызов
    (`subprocess.run(["python3", "scripts/x.py"])`).
    """
    if tree is None:
        tree = _parse(text)
    if tree is None:
        return []
    lines = text.splitlines()
    spans: List[Tuple[int, int, int]] = []
    holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, holders):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if not (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            continue
        lit = first.value
        start, end = lit.lineno, getattr(lit, "end_lineno", None) or lit.lineno
        for ln in range(start, end + 1):
            if not (1 <= ln <= len(lines)):
                continue
            line = lines[ln - 1]
            a = _char_col(line, lit.col_offset) if ln == start else 0
            b = (_char_col(line, lit.end_col_offset) if ln == end
                 else len(line))
            spans.append((ln, a, b))
    return spans


def _comment_spans(text: str) -> Optional[List[Tuple[int, int, int]]]:
    """Координаты `#`-комментариев, или `None` — файл не разобрался токенайзером."""
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return None
    lines = text.splitlines()
    out = []
    for t in toks:
        if t.type != tokenize.COMMENT:
            continue
        ln, col = t.start
        width = len(lines[ln - 1]) if 1 <= ln <= len(lines) else col
        out.append((ln, col, width))
    return out


def _blank(text: str, spans: List[Tuple[int, int, int]]) -> str:
    """Заменить участки пробелами, СОХРАНЯЯ разбивку на строки и длину файла.

    Пробелы, а не удаление: вырезать «сжатием» значит склеить соседние куски и
    родить вызовы, которых в файле нет. Ровно на склейке (пересборка из токенов)
    цикл #227 потерял `from scripts.<имя> import …` и объявил живой скрипт сиротой.
    """
    if not spans:
        return text
    lines = text.splitlines(keepends=True)
    per_line: Dict[int, List[Tuple[int, int]]] = {}
    for ln, a, b in spans:
        per_line.setdefault(ln, []).append((a, b))
    for ln, regions in per_line.items():
        if not (1 <= ln <= len(lines)):
            continue
        line = lines[ln - 1]
        tail = ""
        for nl in ("\r\n", "\n", "\r"):
            if line.endswith(nl):
                line, tail = line[: -len(nl)], nl
                break
        chars = list(line)
        for a, b in regions:
            for i in range(max(a, 0), min(b, len(chars))):
                chars[i] = " "
        lines[ln - 1] = "".join(chars) + tail
    return "".join(lines)


#: Литерал-ПУТЬ: целиком путь к файлу (`scripts/x.py`, `./x.py`, `x.py`) и ничего больше.
_PATH_ONLY_LITERAL = re.compile(rf"^[./]*(?:[\w.\-]+/)*{_NAME}+\.py$")

#: Литерал-МОДУЛЬ: целиком `scripts.<имя>` и ничего больше.
_MODULE_ONLY_LITERAL = re.compile(rf"^scripts\.{_NAME}+$")

#: Вызовы, аргумент которых ИСПОЛНЯЕТСЯ, а не показывается человеку.
#: Внутри них литерал засчитывается КАК ЕСТЬ — там живёт командная строка
#: (`subprocess.run("python3 scripts/x.py --flag", shell=True)`), и требовать от неё
#: формы «голый путь» значило бы объявить сиротой реально запускаемый скрипт.
_EXEC_CALLS = frozenset({
    "run", "Popen", "call", "check_call", "check_output", "getoutput",
    "getstatusoutput", "system", "popen", "run_path", "spec_from_file_location",
    "execv", "execve", "execvp", "execvpe", "execl", "execle", "execlp",
    "spawnv", "spawnl", "spawnvp", "spawnlp",
    "create_subprocess_exec", "create_subprocess_shell",
})


def _call_func_name(node: ast.AST) -> str:
    """Последний компонент имени вызываемого: `subprocess.run` → `run`."""
    func = getattr(node, "func", None)
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def _message_literal_spans(text: str, tree: Optional[ast.AST]) -> List[Tuple[int, int, int]]:
    """Координаты строковых литералов-СООБЩЕНИЙ: текст для человека, а не запуск.

    Четвёртая форма прозы, после комментария (#227), докстринга и самоупоминания
    (#255). Найдена циклом #257 своим же падением: подсказка
    ``out.append(f"убирать за собой обязан `scripts/reap_stale_worktrees.py …`")``
    мгновенно объявила уборщик ПОДКЛЮЧЁННЫМ, хотя вызывать его по-прежнему некому.
    Одной строки в тексте сообщения хватало, чтобы навсегда снять настоящую сироту
    с учёта храповика — молча и без злого умысла.

    **Почему нельзя просто «не считать литералы вызовом».** Самая частая настоящая
    форма запуска — тоже литерал: ``subprocess.run([PY, str(ROOT / "scripts/x.py")])``.
    Поэтому судится не «литерал или нет», а ЧТО в литерале написано:

    * литерал, который ЦЕЛИКОМ есть путь (`scripts/x.py`, `x.py`) или модуль
      (`scripts.x`), — это аргумент запуска/импорта, он ОСТАЁТСЯ;
    * литерал с текстом вокруг пути (``"Run scripts/optimizer_ab.py to regenerate"``,
      ``help="отчёт audit_protocol_blindness.py --tier C"``) — сообщение, вырезается;
    * f-строка вырезается целиком: путь, склеенный с подстановкой, — это текст,
      а не argv (у argv каждый элемент отдельным литералом).

    Исключение — тело вызова из `_EXEC_CALLS`: там литерал исполняется, каким бы
    он ни был (`shell=True` принимает командную строку одной строкой). Исключение
    работает только в плюс — оно СОХРАНЯЕТ проводку, а не отнимает.
    """
    if tree is None:
        return []
    lines = text.splitlines()
    spans: List[Tuple[int, int, int]] = []

    def _span(node: ast.AST) -> None:
        start = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", None) or start
        if start is None:
            return
        for ln in range(start, end + 1):
            if not (1 <= ln <= len(lines)):
                continue
            line = lines[ln - 1]
            a = _char_col(line, node.col_offset) if ln == start else 0
            b = _char_col(line, node.end_col_offset) if ln == end else len(line)
            spans.append((ln, a, b))

    def _walk(node: ast.AST, executed: bool) -> None:
        here = executed or (isinstance(node, ast.Call)
                            and _call_func_name(node) in _EXEC_CALLS)
        if isinstance(node, ast.JoinedStr):
            if not here:
                _span(node)
            return                      # внутрь f-строки не спускаемся
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and not here):
            value = node.value.strip()
            if not (_PATH_ONLY_LITERAL.match(value) or _MODULE_ONLY_LITERAL.match(value)):
                _span(node)
            return
        for child in ast.iter_child_nodes(node):
            _walk(child, here)

    _walk(tree, False)
    return spans


def _python_without_prose(text: str, tree: Optional[ast.AST] = None) -> str:
    """Питон без комментариев, докстрингов И литералов-сообщений.

    Литерал-ПУТЬ сохранён: в нём живёт настоящий вызов
    (`subprocess.run(["python3", "scripts/x.py"])`). Разбор — `_message_literal_spans`.

    Не разобралось (битый файл, чужой синтаксис) — запасной путь `_cut_at_hash`:
    он строже сырого текста, и молчаливого возврата к слепоте здесь нет.
    """
    comments = _comment_spans(text)
    if comments is None:
        return _cut_at_hash(text)
    if tree is None:
        tree = _parse(text)
    return _blank(text, comments + _docstring_spans(text, tree)
                  + _message_literal_spans(text, tree))


def code_without_comments(path: pathlib.Path, text: str,
                          tree: Optional[ast.AST] = None) -> str:
    """Текст файла без ПРОЗЫ — то, в чём вообще может жить ВЫЗОВ.

    Замер 14.08 (цикл #227): сырой текстовый поиск не отличал вызов от
    упоминания, и `daily_paper_report` числился «подключённым» ровно потому,
    что его имя стояло в комментарии, объяснявшем, что он НЕ подключён.

    Цикл #228 добавил сюда докстринги — и только ПОСЛЕ того, как сканер научился
    видеть импорт (`file_references`). Обратный порядок дал бы ложную сироту:
    `check_tracker_drift` держался бы докстрингом, а его настоящий вызов
    (`import check_tracker_drift`) сканеру был не виден.
    """
    suffix = path.suffix
    if suffix == ".py":
        return _python_without_prose(text, tree)
    if suffix in (".sh", ".yml", ".yaml"):
        return _cut_at_hash(text)
    if suffix == ".plist":
        return _XML_COMMENT.sub(" ", text)
    return text


# ────────────────────────────────────────────────────────────────────────────────
# Формы вызова
# ────────────────────────────────────────────────────────────────────────────────

def imported_modules(text: str, tree: Optional[ast.AST] = None) -> Set[str]:
    """Модули, которые файл ИМПОРТИРУЕТ, — полными путями.

    Разбор через `ast`, а не поиск подстроки, потому что различить надо две
    внешне похожие строки с противоположным смыслом:

    - ``import check_tracker_drift`` — настоящая проводка `scripts/check_tracker_drift.py`
      (`scripts/` попадает на `sys.path` при запуске из каталога);
    - ``from spa_core.riskwire import day30_review`` — импорт ОДНОФАМИЛЬЦА,
      к `scripts/day30_review.py` отношения не имеющий.

    Текстовый поиск «\\bimport day30_review» назвал бы вторую строку проводкой и
    снял бы с учёта мёртвый скрипт. Здесь второй случай даёт
    ``spa_core.riskwire.day30_review`` и со скриптом не совпадает.

    Относительные импорты (``from . import x``) пропущены: они внутрипакетные и
    до `scripts/` не дотягиваются.
    """
    if tree is None:
        tree = _parse(text)
    if tree is None:
        return set()
    mods: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            base = node.module or ""
            if not base:
                continue
            mods.add(base)
            for alias in node.names:
                mods.add(f"{base}.{alias.name}")
    return mods


#: Имя файла-скрипта: `<имя>.py` с любым путём или без него.
#:
#: Имя захватывается ЦЕЛИКОМ и жадно — отсюда невосприимчивость к подстрочной
#: коллизии: в `dfb_perf_budget.py` совпадение начинается с `d`, поэтому `perf_budget`
#: отсюда не извлекается вовсе. Раньше извлекалось — и мёртвый `scripts/perf_budget.py`
#: числился живым за счёт совсем другого файла.
_REF_FILE = re.compile(rf"({_NAME}+)\.py(?!{_NAME})")

#: `scripts/<имя>.py` — ПОЛНОЕ, ни с чем не смешиваемое указание на скрипт.
_REF_QUALIFIED_PATH = re.compile(rf"(?<!{_NAME})scripts/({_NAME}+)\.py(?!{_NAME})")

#: `scripts.<имя>` — тот же скрипт в форме модуля (plist, обёртка, workflow).
_REF_QUALIFIED_MOD = re.compile(rf"(?<![A-Za-z0-9_.])scripts\.({_NAME}+)(?!{_NAME})")

#: `python3 -m <имя>` / `-m scripts.<имя>` — запуск модулем.
_REF_DASH_M = re.compile(rf"-m\s+(scripts\.)?({_NAME}+)(?![A-Za-z0-9_.])")


def file_references(text: str, modules: Set[str]) -> Tuple[Set[str], Set[str]]:
    """Имена скриптов, на которые ссылается ОДИН файл: `(любые, только полные)`.

    Возвращаются два множества, потому что у ссылки есть СИЛА:

    - «любые» — годятся для чужого файла: `<имя>.py` в обёртке, `import <имя>`,
      `-m <имя>`;
    - «только полные» — `scripts/<имя>.py` и `scripts.<имя>`. Ровно их требуют
      от ОДНОФАМИЛЬЦА: файл `spa_core/riskwire/day30_review.py`, упомянув
      собственное имя, «подключал» `scripts/day30_review.py`, которого не зовёт
      никто (замер 14.08 — так держались 2 скрипта).

    Один проход по файлу вместо прогона 177 наборов шаблонов: сканер иначе
    считает дерево минутами и его перестают запускать.
    """
    qualified = set(_REF_QUALIFIED_PATH.findall(text)) | set(_REF_QUALIFIED_MOD.findall(text))
    plain = set(_REF_FILE.findall(text))
    for prefix, name in _REF_DASH_M.findall(text):
        (qualified if prefix else plain).add(name)
    for mod in modules:
        if mod.startswith("scripts."):
            tail = mod[len("scripts."):]
            if "." not in tail:
                qualified.add(tail)
        elif "." not in mod:
            plain.add(mod)
    return plain | qualified, qualified


# ────────────────────────────────────────────────────────────────────────────────
# Формы подключения ОДНОГО скрипта — перенесено из версии Мака (циклы #255/#265)
# ────────────────────────────────────────────────────────────────────────────────

def wiring_patterns(stem: str) -> Dict[str, Pattern]:
    """Формы, в которых скрипт `scripts/<stem>.py` бывает ПОДКЛЮЧЁН.

    Одно место, где все пять форм записаны с границами слова с ОБЕИХ сторон.
    До цикла #255 форм было две — подстрока `<stem>.py` и подстрока
    `scripts.<stem>`, — и обе без границ. Отсюда два разных вранья:

    * **подстрочная коллизия** — `perf_budget` числился подключённым, потому
      что рядом лежит `dfb_perf_budget.py`; `scripts.run_backtest` находится
      внутри `scripts.run_backtest_real`;
    * **невидимая форма** — `import <stem>` по `sys.path` не виден вовсе, хотя
      `scripts/orchestrator_queue.py` именно так зовёт `check_tracker_drift`.

    Границы обязаны стоять с ОБЕИХ сторон: слева `(?<![\\w.\\-])`, чтобы имя не
    ловилось хвостом другого имени, справа `(?![\\w])`, чтобы `scripts.x` не
    ловилось началом `scripts.x_real`.

    Обход дерева пользуется не этими шаблонами, а извлечением имён одним проходом
    (`file_references`) — там та же строгость достигается жадным захватом имени
    целиком. Шаблоны нужны там, где судится ОДИН документ против ОДНОГО скрипта:
    реестр R&D (`registry_recorded_scripts`) и второе мнение о дереве
    (`scripts_without_caller_by_patterns`).
    """
    s = re.escape(stem)
    return {
        # запуск/ссылка по файлу: plist, обёртка, subprocess, runpy.run_path
        "file": re.compile(r"(?<![\w.\-])" + s + r"\.py(?![\w])"),
        # то же, но обязательно из каталога scripts/ — для однофамильцев
        "path": re.compile(r"(?<![\w.\-])scripts/" + s + r"\.py(?![\w])"),
        # `python3 -m scripts.<stem>` и `from scripts.<stem> import …`
        "module": re.compile(r"(?<![\w.])scripts\." + s + r"(?![\w])"),
        # голый импорт по sys.path: `import <stem>` / `import <stem> as x`
        "import": re.compile(r"^[ \t]*import[ \t]+" + s + r"(?![\w.])", re.M),
        # голый импорт по sys.path: `from <stem> import …`
        "from": re.compile(r"^[ \t]*from[ \t]+" + s + r"(?![\w.])[ \t]+import[ \t]", re.M),
    }


def is_wiring(hay_path: pathlib.Path, text: str, script: pathlib.Path,
              pats: Dict[str, Pattern]) -> bool:
    """Есть ли в ЭТОМ файле доказательство того, что скрипт ЗОВУТ.

    **Однофамилец судится строже.** Файл с тем же именем в другом каталоге
    (`spa_core/riskwire/day30_review.py`, `spa_core/audit/ots_anchor.py`)
    упоминает сам себя — своё же имя в шапке, — и этого хватало, чтобы
    одноимённый скрипт числился вызванным. Ни один из двух модулей скрипта не
    зовёт. Поэтому у однофамильца засчитываются только формы, которые НЕЛЬЗЯ
    написать про себя: путь `scripts/<stem>.py` и модуль `scripts.<stem>`.

    Голый импорт по `sys.path` спрашивается только у `.py`: в обёртке и plist'е
    строка `import x` — проза, а не проводка.

    **Дешёвая отсечка первой строкой — не украшение.** Без неё пять регулярок
    гоняются по каждой паре (101 скрипт × ~1500 файлов) и один замер стоил минуты,
    то есть сторож становился слишком дорогим, чтобы его гоняли. Отсечка ТОЧНА по
    построению: имя скрипта входит в КАЖДУЮ из пяти форм, значит файл без
    подстроки имени не может содержать ни одной из них — отсечка не может ни
    добавить сироту, ни отнять. Цена измерена на живом дереве 17.08:
    с отсечкой 18.2 с, без неё 231.0 с — в 12.7 раза дороже при том же вердикте
    (`scripts_without_caller_by_patterns(cheap_cutoff=False)`).
    """
    if script.stem not in text:
        return False
    if hay_path.stem == script.stem:
        return bool(pats["path"].search(text) or pats["module"].search(text))
    if pats["file"].search(text) or pats["module"].search(text):
        return True
    return hay_path.suffix == ".py" and bool(
        pats["import"].search(text) or pats["from"].search(text))


# ────────────────────────────────────────────────────────────────────────────────
# Обход дерева
# ────────────────────────────────────────────────────────────────────────────────

def entrypoint_scripts(root: Optional[pathlib.Path] = None) -> List[pathlib.Path]:
    """Скрипты в `scripts/`, которые можно запустить как программу."""
    base = pathlib.Path(root or _ROOT)
    out = []
    for p in sorted((base / "scripts").glob("*.py")):
        try:
            if "__main__" in p.read_text(encoding="utf-8", errors="ignore"):
                out.append(p)
        except OSError:
            continue
    return out


def registry_recorded_scripts(root: Optional[pathlib.Path] = None) -> Set[str]:
    """Скрипты, чей ПРОДУКТ — запись в реестре R&D-идей.

    У исследовательского замера вызывающего нет и быть не должно: его запускают
    руками, а результат уезжает в `docs/DYNAMIC_LEVERAGE_GUARDIAN.md`. Реестр —
    единственный документ с таким правом (см. модульный docstring: любой другой
    файл `docs/`, включая журнал, проводкой НЕ считается).

    **Судится шаблонами `wiring_patterns`, а не голой подстрокой** (сведение 17.08).
    Раньше здесь стояло `m.name in text` — ровно та подстрочная коллизия, от которой
    обход дерева уже был защищён жадным захватом имени: запись про
    `dfb_perf_budget.py` в реестре вывела бы из-под храповика ЧУЖОЙ `perf_budget`,
    то есть вычитаемый класс был слабее самого измерения. Строгость обоих плеч
    обязана быть одинаковой, иначе дыра переезжает из измерения в поблажку.
    """
    base = pathlib.Path(root or _ROOT)
    reg = base / _RND_REGISTRY
    try:
        text = reg.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return set()
    out: Set[str] = set()
    for m in entrypoint_scripts(base):
        if m.stem not in text:          # дешёвая отсечка, см. `is_wiring`
            continue
        pats = wiring_patterns(m.stem)
        if pats["file"].search(text) or pats["module"].search(text):
            out.add(m.stem)
    return out


#: Кэш разобранного дерева: ключ — отпечаток (путь, mtime, размер) всех файлов.
_HAY_CACHE: Dict[tuple, List[Tuple[pathlib.Path, Set[str], Set[str], Set[str]]]] = {}


def _haystack(base: pathlib.Path) -> List[Tuple[pathlib.Path, Set[str], Set[str], Set[str]]]:
    """`(файл, названные им скрипты, названные ПОЛНЫМ именем, импортируемые модули)`.

    Четвёртое поле — полные dotted-имена импортов файла. Оно нужно правилу
    «продукт скрипта импортирует живой код» (`generated_artifact_scripts`) и
    берётся из уже сделанного разбора, а не вторым проходом по дереву.
    """
    files = []
    for d in _HAY_DIRS:
        d_base = base / d
        if not d_base.exists():
            continue
        for p in sorted(d_base.rglob("*")):
            if p.is_file() and p.suffix in _HAY_SUFFIXES and "/tests/" not in str(p):
                files.append(p)
    try:
        key = tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in files)
    except OSError:
        key = None
    if key is not None and key in _HAY_CACHE:
        return _HAY_CACHE[key]
    hay = []
    for p in files:
        try:
            raw = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        tree = _parse(raw) if p.suffix == ".py" else None
        mods = imported_modules(raw, tree) if p.suffix == ".py" else set()
        plain, qualified = file_references(code_without_comments(p, raw, tree), mods)
        hay.append((p, plain, qualified, mods))
    if key is not None:
        _HAY_CACHE.clear()
        _HAY_CACHE[key] = hay
    return hay


def scripts_without_caller(root: Optional[pathlib.Path] = None) -> List[str]:
    """Сырое измерение: имена скриптов, которых НИКТО не вызывает (тесты не в счёт).

    Вызовом считается любая из форм: путь к файлу (`scripts/<имя>.py`, `<имя>.py`
    в обёртке или plist), `python3 -m scripts.<имя>`, импорт `scripts.<имя>` или
    голый `import <имя>` по `sys.path`. Тесты не считаются: тест вызывает деталь,
    а вопрос здесь — включена ли она в проводку (урок цикла #144).

    **Проводкой НЕ считаются** (каждое — измеренная слепота, не гипотеза):
    комментарий и докстринг (в них вызова быть не может — `code_without_comments`),
    самоупоминание ОДНОФАМИЛЬЦА из другого каталога (от него требуется полное имя —
    `file_references`) и случайное вхождение имени внутрь ДРУГОГО имени
    (`_REF_FILE` захватывает имя целиком).
    """
    base = pathlib.Path(root or _ROOT)
    hay = _haystack(base)
    orphans = []
    for m in entrypoint_scripts(base):
        stem = m.stem
        wired = any(
            stem in (qualified if p.stem == stem else plain)
            for p, plain, qualified, _mods in hay if p != m
        )
        if not wired:
            orphans.append(stem)
    return sorted(orphans)


def scripts_without_caller_by_patterns(root: Optional[pathlib.Path] = None,
                                       cheap_cutoff: bool = True) -> List[str]:
    """То же измерение ВТОРЫМ движком: `wiring_patterns` × `is_wiring` по каждой паре.

    Это не запасной путь и не украшение, а **второе мнение**. Две реализации
    сторожа разошлись на три недели именно потому, что каждая знала свои формы;
    здесь обе живут рядом, и их согласие проверяется тестом на живом дереве
    (`test_unwired_wiring_forms.py::TestTwoEnginesAgree`). Разойдутся — тест
    покраснеет и назовёт имена, вместо того чтобы одна из версий тихо победила.

    Движком по умолчанию он НЕ является: перебор O(скрипты × файлы) стоит 16–18 с
    за прогон и КАЖДЫЙ прогон заново, тогда как одиночный проход
    `scripts_without_caller` стоит ~20 с холодным и 0.30 с на повторе (кэш дерева).

    `cheap_cutoff=False` снимает отсечку первой строкой — только для того, чтобы
    цену отсечки можно было ИЗМЕРИТЬ, а не заявить. Вердикт при этом обязан
    остаться тем же (отсечка точна по построению), и это тоже закреплено тестом.
    """
    base = pathlib.Path(root or _ROOT)
    hay: List[Tuple[pathlib.Path, str]] = []
    for d in _HAY_DIRS:
        d_base = base / d
        if not d_base.exists():
            continue
        for p in sorted(d_base.rglob("*")):
            if not (p.is_file() and p.suffix in _HAY_SUFFIXES and "/tests/" not in str(p)):
                continue
            try:
                raw = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            hay.append((p, code_without_comments(p, raw)))
    orphans = []
    for m in entrypoint_scripts(base):
        pats = wiring_patterns(m.stem)
        wired = False
        for p, t in hay:
            if p == m:
                continue
            if cheap_cutoff:
                if is_wiring(p, t, m, pats):
                    wired = True
                    break
            elif _is_wiring_no_cutoff(p, t, m, pats):
                wired = True
                break
        if not wired:
            orphans.append(m.stem)
    return sorted(orphans)


def _is_wiring_no_cutoff(hay_path: pathlib.Path, text: str, script: pathlib.Path,
                         pats: Dict[str, Pattern]) -> bool:
    """`is_wiring` без дешёвой отсечки — существует РАДИ ЗАМЕРА её цены.

    Вердикт обязан совпадать с `is_wiring` дословно: отсечка отбрасывает только
    файлы, где имени скрипта нет ни одной буквой, а имя входит во все пять форм.
    """
    if hay_path.stem == script.stem:
        return bool(pats["path"].search(text) or pats["module"].search(text))
    if pats["file"].search(text) or pats["module"].search(text):
        return True
    return hay_path.suffix == ".py" and bool(
        pats["import"].search(text) or pats["from"].search(text))


#: `python3 scripts/<имя>.py` / `python3 -m scripts.<имя>` — КОМАНДА, а не упоминание.
_PROTOCOL_CMD = re.compile(rf"python3\s+(?:-m\s+)?scripts[/.]({_NAME}+)(?:\.py)?(?!{_NAME})")


def protocol_executor(root: Optional[pathlib.Path] = None) -> Optional[pathlib.Path]:
    """Файл-ИСПОЛНИТЕЛЬ протокола цикла, или `None` — исполнителя нет.

    Правило `protocol_commanded_scripts` держится не на документе, а на ЦЕПОЧКЕ:
    `launchd/com.spa.orchestrator.plist` → `scripts/agent_orchestrator.sh` → строка
    «Исполни ПОЛНОСТЬЮ docs/ORCHESTRATOR_PROTOCOL.md за один цикл». Исполнитель
    называет протокол В КОДЕ (не в комментарии) — то есть команда из протокола
    исполняется агентом так же, как строка из обёртки.

    Исполнителя не нашли ⇒ **None**, и класс не вычитается ВОВСЕ (fail-CLOSED):
    протокол без исполнителя — обычный документ, а весь `docs/` проводкой не
    считается (замер #214: снял бы с учёта 62 из 88).
    """
    base = pathlib.Path(root or _ROOT)
    needle = _PROTOCOL_DOC.as_posix()
    for d in ("scripts", "launchd"):
        d_base = base / d
        if not d_base.exists():
            continue
        for p in sorted(d_base.rglob("*")):
            if not (p.is_file() and p.suffix in (".sh", ".plist", ".py")):
                continue
            if "/tests/" in str(p):
                continue
            try:
                raw = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if needle in code_without_comments(p, raw):
                return p
    return None


def protocol_commanded_scripts(root: Optional[pathlib.Path] = None) -> Set[str]:
    """Скрипты, которые ОБЯЗАТЕЛЬНЫЙ протокол цикла велит запускать КОМАНДОЙ.

    Вызывающий здесь — не программа, а агент-оркестратор, исполняющий
    `docs/ORCHESTRATOR_PROTOCOL.md` каждый цикл (см. `protocol_executor`).
    Поэтому класс ВЫЧИТАЕТСЯ (как реестр R&D), а не считается вызовом: сырое
    измерение `scripts_without_caller` продолжает честно говорить «ни одна
    программа его не зовёт».

    **Засчитывается только КОМАНДНАЯ форма** `python3 scripts/<имя>.py`, не
    упоминание имени. Разница измерена 15.08 на живом дереве: командная форма
    снимает с учёта **2** скрипта из 61 (`adr_number`, `reap_stale_worktrees`),
    свободное упоминание — 3 (добавился бы `smoke`, названный в протоколе прозой
    и никем не запускаемый). Ровно за такую подмену прозы вызовом цикл #228 и
    снял три слепоты, поэтому здесь она закрыта заранее.
    """
    base = pathlib.Path(root or _ROOT)
    if protocol_executor(base) is None:
        return set()
    try:
        text = (base / _PROTOCOL_DOC).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return set()
    commanded = set(_PROTOCOL_CMD.findall(text))
    return {p.stem for p in entrypoint_scripts(base) if p.stem in commanded}


#: Литерал вида `<имя>.py` — кандидат в ПРОДУКТ скрипта-генератора.
_ARTIFACT_LITERAL = re.compile(rf"^{_NAME}+\.py$")


def _code_string_literals(text: str) -> Set[str]:
    """Строковые литералы файла БЕЗ докстрингов (докстринг — проза, капкан #227)."""
    tree = _parse(text)
    if tree is None:
        return set()
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            d = ast.get_docstring(node, clean=False)
            if d:
                docs.add(d)
    return {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)} - docs


def generated_artifact_scripts(root: Optional[pathlib.Path] = None) -> Set[str]:
    """Скрипты-ГЕНЕРАТОРЫ, чей продукт лежит в дереве и импортируется живым кодом.

    Такой скрипт не «доставлен и мёртв»: мёртв только его вход, а продукт
    исполняется каждый день внутри чужого модуля. Пример на 15.08 —
    `audit_tier_c_wiring_feasibility` → `spa_core/analytics/_protocol_key_coverage.py`
    → `signal_aggregator.run_tier_b` (разметка решает, какие Tier-B модули
    исключить из composite).

    **Требуются ОБЕ стороны, и ни одна из них не является одиночной прозой:**

    1. скрипт называет путь продукта **в коде** (не в докстринге) — здесь это
       аргумент записи `emit_markup(report, ROOT / … / "_protocol_key_coverage.py")`;
    2. продукт называет скрипт у себя (шапка «СГЕНЕРИРОВАНО …»);
    3. продукт — отслеживаемый модуль вне `scripts/` и вне тестов, который
       **импортирует** живой (не тестовый) код.

    Цена правила измерена 15.08 на живом дереве: одностороннее «скрипт назвал путь
    модуля» снимает с учёта **6** подопечных храповика из 61, и пять из них не
    генераторы вовсе — они просто упоминают чужой модуль (`verify_infrastructure`
    → `cycle_runner.py`). Встречное требование срезает эти пять и оставляет **1**
    (`audit_tier_c_wiring_feasibility`). Правилу отвечают ещё два скрипта
    (`audit_protocol_blindness`, `site_freshness_monitor`), но они подключены
    обычным вызовом и под храповиком не числятся — на список подопечных правило
    влияет ровно на одно имя. Узость измерена, а не заявлена.
    """
    base = pathlib.Path(root or _ROOT)
    hay = _haystack(base)
    imported_dotted: Set[str] = set()
    for _p, _plain, _qual, mods in hay:
        imported_dotted |= mods

    # продукт-кандидат: модуль вне scripts/ и вне тестов
    artifacts: Dict[str, List[pathlib.Path]] = {}
    for p, _plain, _qual, _mods in hay:
        rel = p.relative_to(base)
        if rel.suffix != ".py" or rel.parts[0] == "scripts":
            continue
        artifacts.setdefault(rel.name, []).append(p)

    out: Set[str] = set()
    for m in entrypoint_scripts(base):
        try:
            lits = _code_string_literals(m.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
        names = {pathlib.PurePath(s).name for s in lits
                 if _ARTIFACT_LITERAL.match(pathlib.PurePath(s).name or "")}
        for name in names:
            for art in artifacts.get(name, []):
                dotted = ".".join(art.relative_to(base).with_suffix("").parts)
                if dotted not in imported_dotted:
                    continue
                try:
                    art_text = art.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                if m.stem in art_text:
                    out.add(m.stem)
    return out


def unwired_scripts(root: Optional[pathlib.Path] = None) -> List[str]:
    """«Доставлен и мёртв»: вызывающего нет И ни одно вычитаемое плечо не сработало.

    Вычитаются три класса, у каждого вызывающего нет ПО УСТРОЙСТВУ, и у каждого
    цена правила измерена на живом дереве (иначе это не класс, а поблажка):

    - `registry_recorded_scripts` — исследовательский замер, продукт которого —
      запись в реестре R&D (#214);
    - `protocol_commanded_scripts` — команда обязательного протокола цикла,
      которую исполняет агент-оркестратор (#248, цена 2 из 61);
    - `generated_artifact_scripts` — генератор, чей продукт импортирует живой код
      (#248, цена 1 из 61).

    Ровно этот список сторожит храповик `test_unwired_scripts_ratchet`.
    """
    base = pathlib.Path(root or _ROOT)
    return sorted(set(scripts_without_caller(base))
                  - registry_recorded_scripts(base)
                  - protocol_commanded_scripts(base)
                  - generated_artifact_scripts(base))
