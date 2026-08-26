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

Опт-аут-флага в коде здесь намеренно НЕТ: флаг научил бы сторожа отключать.
"""
from __future__ import annotations

import ast
import io
import pathlib
import re
import tokenize
from typing import Dict, Iterable, List, Optional, Pattern, Set, Tuple

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_HAY_DIRS = ("launchd", "scripts", "spa_core", ".github")
_HAY_SUFFIXES = (".sh", ".plist", ".py", ".yml", ".yaml")

#: Реестр R&D-идей: единственный документ, запись в котором считается проводкой.
_RND_REGISTRY = pathlib.Path("docs") / "DYNAMIC_LEVERAGE_GUARDIAN.md"

#: XML-комментарий plist'а: `<!-- ... -->` (в plist'ах он многострочный).
_XML_COMMENT = re.compile(r"<!--.*?-->", re.S)

#: Пробел любого вида: им отличается цельный путь-токен от текста для человека.
_WHITESPACE = re.compile(r"\s")

#: Вызовы, внутри аргументов которых строка — КОМАНДА, а не текст для человека.
#: Имя сравнивается последним сегментом (`subprocess.run` → `run`).
_LAUNCHER_FUNCS = frozenset({
    "run", "Popen", "call", "check_call", "check_output",
    "getoutput", "getstatusoutput", "system", "popen",
    "execv", "execve", "execvp", "execvpe", "spawnv", "spawnve", "spawnl",
    "run_path", "run_module", "spec_from_file_location",
    "create_subprocess_shell", "create_subprocess_exec",
})


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


#: Инструменты ДОСТАВКИ: путь в их аргументах — ГРУЗ ПУША, а не запуск.
#: Список закрытый и намеренно короткий: расширять его значит гасить доказательство.
_DELIVERY_TOOLS = ("push_to_github", "safe_site_push")

#: Флаг, после которого у команды доставки идёт СПИСОК ГРУЗА.
_PAYLOAD_FLAG = re.compile(r"(?<![\w-])--files(?![\w-])")


def _sh_without_delivery_payload(text: str) -> str:
    """Оболочка без СПИСКА ГРУЗА доставки: имя файла там — не вызов.

    `python3 push_to_github.py --files … "$REPO_ROOT/scripts/X.py" --message "…"`
    ОТПРАВЛЯЕТ `X.py` на origin, а не запускает его. До цикла #379 сканер читал
    такое упоминание как проводку, и скрипт числился подключённым ровно потому,
    что однажды уехал в пуше (карточка
    `inbox-hrapovik-nepodklyuchennyh-skriptov-schit-3`, замер #375). Это тот же
    класс, что докстринг (#255) и текст сообщения (#278): доказательство слабее
    вызова, снимающее скрипт с учёта молча и навсегда.

    Затирается **только хвост после `--files`** и только внутри логической
    строки, где назван инструмент доставки. Границы выбраны так, чтобы ошибиться
    в сторону СОХРАНЕНИЯ доказательства (объявить живой скрипт сиротой в этом
    проекте хуже пропуска, #183/#255):

    * сам `push_to_github.py` НЕ затирается — он-то как раз запускается;
    * груз кончается на первом же токене-флаге (`--message`, `--branch`), дальше
      текст остаётся нетронутым;
    * настоящий запуск из `.sh` (`bash scripts/X.py`, `python3 scripts/X.py --once`)
      под правило не попадает вовсе: у него нет `--files` перед именем.

    Логическая строка склеивается по обратным слэшам — пушер зовут именно так,
    по одному пути на строку, и правило, судящее физические строки, увидело бы
    груз как самостоятельную команду.
    """
    lines = text.splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    groups: List[List[int]] = []
    cur: List[int] = []
    for i, line in enumerate(lines):
        cur.append(i)
        if not line.rstrip("\n").endswith("\\"):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    out = list(text)
    for g in groups:
        a, b = starts[g[0]], starts[g[-1] + 1]
        chunk = text[a:b]
        if not any(tool in chunk for tool in _DELIVERY_TOOLS):
            continue
        for m in _PAYLOAD_FLAG.finditer(chunk):
            i = m.end()
            while i < len(chunk):
                while i < len(chunk) and chunk[i].isspace():
                    i += 1
                if i >= len(chunk):
                    break
                if chunk[i] == "\\":       # перенос строки внутри одной команды
                    i += 1
                    continue
                if chunk[i] == "-":        # следующий ФЛАГ — груз кончился
                    break
                while i < len(chunk) and not chunk[i].isspace():
                    if chunk[i] != "\n":
                        out[a + i] = " "
                    i += 1
    return "".join(out)


def _python_without_comments(text: str) -> str:
    """Питон без `#`-комментариев; строковые литералы СОХРАНЕНЫ.

    Литерал оставлен намеренно: `subprocess.run(["python3", "scripts/x.py"])` —
    настоящий вызов, и он живёт именно в строке. Токенайзер, а не регулярка,
    потому что `#` внутри тройной строки регулярка отрежет вместе с вызовом.
    Не разобралось (битый файл, чужой синтаксис) — запасной путь `_cut_at_hash`:
    он строже сырого текста, и молчаливого возврата к слепоте здесь нет.

    Вырезается КООРДИНАТАМИ, а не пересборкой из токенов: пересборка склеивает
    токены разделителем и рвёт `from scripts.<stem> import …` на куски, после
    чего настоящий импорт перестаёт находиться и живой скрипт объявляется
    сиротой. Поймано положительным контролем `test_module_import_form_is_a_call`.
    """
    try:
        comments = [t.start for t in tokenize.generate_tokens(io.StringIO(text).readline)
                    if t.type == tokenize.COMMENT]
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return _cut_at_hash(text)
    if not comments:
        return text
    cut_at = {}
    for lineno, col in comments:
        cut_at[lineno] = min(cut_at.get(lineno, col), col)
    lines = text.splitlines(keepends=True)
    for lineno, col in cut_at.items():
        if 1 <= lineno <= len(lines):
            line = lines[lineno - 1]
            tail = "\n" if line.endswith("\n") else ""
            lines[lineno - 1] = line[:col] + tail
    return "".join(lines)


def _byte_col_to_char(line: str, col: int) -> int:
    """Колонка `ast` — в БАЙТАХ utf-8, а строка индексируется символами.

    Поймано собственным положительным контролем
    (`test_line_numbers_survive_the_stripper`): в этом проекте докстринги
    кириллические, байт на символ приходится два, и затирание по байтовой
    колонке уезжало на строку вперёд — съедая настоящий `from scripts.x import`
    следом за докстрингом. То есть ровно та авария (живой скрипт объявлен
    сиротой), ради предотвращения которой правки делались в этом порядке.
    """
    if col <= 0:
        return 0
    raw = line.encode("utf-8")
    if col >= len(raw):
        return len(line)
    return len(raw[:col].decode("utf-8", errors="ignore"))


def _blank_spans(text: str, spans: Iterable[Tuple[int, int, int, int]]) -> str:
    """Затереть пробелами куски текста по координатам `ast`, сохранив номера строк.

    Пробелами, а не вырезанием: координаты остальных кусков остаются верными,
    и ни одна строка не склеивается с соседней (склейка уже однажды порвала
    `from scripts.<stem> import …` — см. `_python_without_comments`).
    """
    lines = text.splitlines(keepends=True)
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line))
    out = list(text)
    for (l1, c1, l2, c2) in spans:
        if not (1 <= l1 <= len(lines) and 1 <= l2 <= len(lines)):
            continue
        a = starts[l1 - 1] + _byte_col_to_char(lines[l1 - 1], c1)
        b = starts[l2 - 1] + _byte_col_to_char(lines[l2 - 1], c2)
        for i in range(a, min(b, len(out))):
            if out[i] != "\n":
                out[i] = " "
    return "".join(out)


def _parent_map(tree: ast.AST) -> Dict[int, ast.AST]:
    """`id(узел) -> родитель`. Контекст литерала иначе не восстановить: у `ast`
    ссылки идут только вниз."""
    out: Dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            out[id(child)] = node
    return out


def _inside_launcher_call(node: ast.AST, parents: Dict[int, ast.AST]) -> bool:
    """Литерал лежит в АРГУМЕНТАХ вызова, который запускает программу.

    Только здесь строка с пробелами имеет право быть командой:
    `subprocess.run(f"python3 scripts/x.py --once", shell=True)`. Тот же текст в
    `print(...)` — сообщение человеку.

    Имя вызова берётся ПОСЛЕДНИМ сегментом (`subprocess.run` → `run`), потому что
    модуль зовут и `import subprocess`, и `from subprocess import run`. Набор
    заведомо ШИРЕ нужного (`run`/`call` носят и невинные вызовы) — и это
    осознанное направление ошибки: лишний запускатель СОХРАНЯЕТ доказательство
    проводки, то есть скрипт остаётся «подключённым». Ошибиться в другую сторону
    значит объявить живой скрипт сиротой, а этот исход в проекте признан хуже
    пропуска (#183, #255).
    """
    cur = node
    while True:
        parent = parents.get(id(cur))
        if parent is None:
            return False
        if isinstance(parent, ast.Call) and cur is not parent.func:
            func = parent.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in _LAUNCHER_FUNCS:
                return True
        cur = parent


def _joined_str_text(node: ast.JoinedStr) -> str:
    """Постоянные куски f-строки, склеенные: то, что в ней написано БУКВАЛЬНО.

    f-строка судится ЦЕЛИКОМ (и затирается целиком), а не по кускам: у вложенных
    узлов координаты зависят от версии интерпретатора, а у самого `JoinedStr` —
    нет. Одно сообщение — одно решение.
    """
    return "".join(v.value for v in node.values
                   if isinstance(v, ast.Constant) and isinstance(v.value, str))


def _docstring_spans(tree: ast.AST) -> List[Tuple[int, int, int, int]]:
    """Докстринги модуля/класса/функции — проза о коде, вызова в ней быть не может.

    Проверяется отдельно от общего правила о прозе: докстринг вида `\"\"\"x.py\"\"\"`
    пробелов не содержит и под «текст для человека» по форме не попадает,
    а вызовом от этого не становится.
    """
    spans = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            v = first.value
            spans.append((v.lineno, v.col_offset, v.end_lineno, v.end_col_offset))
    return spans


def _prose_spans(tree: ast.AST) -> List[Tuple[int, int, int, int]]:
    """Строковые литералы, которые являются ТЕКСТОМ ДЛЯ ЧЕЛОВЕКА, а не запуском.

    Признак — форма самого литерала, а не догадка о смысле:

    * **цельный токен** (`"scripts/x.py"`, `"x.py"`, `str(ROOT / "x.py")`) — путь и
      ничего кроме пути. Так выглядит подавляющая часть настоящих ссылок, и такой
      литерал СОХРАНЯЕТСЯ независимо от того, где он лежит;
    * **строка с пробелами** (`"Протестируй: python3 scripts/x.py --dry-run"`) —
      сообщение, ЕСЛИ она не лежит в аргументах запускателя. Команда с флагами
      внутри `subprocess.run(...)` — тоже строка с пробелами, и её сохраняет
      `_inside_launcher_call`.

    Почему не «литерал вообще не доказательство»: `subprocess.run(["python3",
    "scripts/x.py"])` — настоящий вызов, и живёт он именно в литерале (#255 снял
    докстринг только потому, что докстринг отличим структурно). Почему не
    «литерал в `print` не доказательство»: сообщение собирают и `out.append(f"…")`,
    и `lines.append(...)`, и `return "…"` — перечислить писателей нельзя, а
    перечислить запускателей можно.
    """
    parents = _parent_map(tree)
    in_fstring = {id(c) for node in ast.walk(tree) if isinstance(node, ast.JoinedStr)
                  for c in ast.walk(node) if c is not node}
    spans = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            literal = _joined_str_text(node)
        elif (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in in_fstring):
            literal = node.value
        else:
            continue
        if not _WHITESPACE.search(literal.strip()):
            continue
        if _inside_launcher_call(node, parents):
            continue
        spans.append((node.lineno, node.col_offset, node.end_lineno, node.end_col_offset))
    return spans


def _python_without_prose(text: str) -> str:
    """Питон без докстрингов и без строк-сообщений; литералы-запуски СОХРАНЕНЫ.

    Три формы прозы сняты в трёх циклах и все — в одну сторону, убирая
    доказательство слабее вызова: комментарий (#227), докстринг (#255), текст
    сообщения (#278). Четвёртая была опаснее прочих: чтобы навсегда снять
    НАСТОЯЩИЙ мёртвый скрипт с учёта, хватало один раз назвать его имя в тексте
    любой подсказки — молча и без злого умысла (карточка
    `inbox-hrapovik-nepodklyuchennyh-skriptov-schit-2`, найдено падением #257 на
    строке-подсказке шага 0a про `scripts/reap_stale_worktrees.py`).

    Файл не разобрался (битый синтаксис) — возвращаем как есть: это СЛАБЕЕ,
    и потому названо вслух, а не спрятано. Комментарии с такого файла всё
    равно снимаются запасным путём `_cut_at_hash`.
    """
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return text
    spans = _docstring_spans(tree) + _prose_spans(tree)
    return _blank_spans(text, spans) if spans else text


def code_without_comments(path: pathlib.Path, text: str) -> str:
    """Текст файла без комментариев, докстрингов и сообщений — где может жить ВЫЗОВ.

    Замер 14.08 (цикл #227): сырой текстовый поиск не отличал вызов от
    упоминания, и `daily_paper_report` числился «подключённым» ровно потому,
    что его имя стояло в комментарии, объяснявшем, что он НЕ подключён.

    Докстринги закрыты циклом #255, текст сообщений — #278, но ТОЛЬКО ПОСЛЕ того,
    как сканер научился видеть все формы проводки (`wiring_patterns`). Порядок
    здесь не украшение: `check_tracker_drift` держится докстрингами, а зовут его
    голым `import check_tracker_drift` — снять докстринги первыми значило объявить
    живой, ежедневно исполняемый скрипт сиротой, то есть покрасить храповика
    на честной работе (исход, который в этом проекте признан хуже пропуска).
    """
    suffix = path.suffix
    if suffix == ".py":
        return _python_without_prose(_python_without_comments(text))
    if suffix in (".sh", ".yml", ".yaml"):
        return _sh_without_delivery_payload(_cut_at_hash(text))
    if suffix == ".plist":
        return _XML_COMMENT.sub(" ", text)
    return text


def wiring_patterns(stem: str) -> Dict[str, Pattern]:
    """Формы, в которых скрипт `scripts/<stem>.py` бывает ПОДКЛЮЧЁН.

    До цикла #255 форм было две — подстрока `<stem>.py` и подстрока
    `scripts.<stem>`, — и обе без границ слова. Отсюда два разных вранья:

    * **подстрочная коллизия** — `perf_budget` числился подключённым, потому
      что рядом лежит `dfb_perf_budget.py`; `scripts.run_backtest` находится
      внутри `scripts.run_backtest_real`;
    * **невидимая форма** — `import <stem>` по `sys.path` не виден вовсе, хотя
      `scripts/orchestrator_queue.py` именно так зовёт `check_tracker_drift`.

    Границы обязаны стоять с ОБЕИХ сторон: слева `(?<![\\w.\\-])`, чтобы имя не
    ловилось хвостом другого имени, справа `(?![\\w])`, чтобы `scripts.x` не
    ловилось началом `scripts.x_real`.
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


def _is_wiring(hay_path: pathlib.Path, text: str, script: pathlib.Path,
               pats: Dict[str, Pattern]) -> bool:
    """Есть ли в этом файле доказательство того, что скрипт ЗОВУТ.

    **Однофамилец судится строже.** Файл с тем же именем в другом каталоге
    (`spa_core/riskwire/day30_review.py`, `spa_core/audit/ots_anchor.py`)
    упоминает сам себя — своё же имя в шапке, — и этого хватало, чтобы
    одноимённый скрипт числился вызванным. Ни один из двух модулей скрипта не
    зовёт. Поэтому у однофамильца засчитываются только формы, которые НЕЛЬЗЯ
    написать про себя: путь `scripts/<stem>.py` и модуль `scripts.<stem>`.

    Дешёвая отсечка первой строкой — не украшение: без неё пять регулярок гоняются
    по каждой паре (101 скрипт × ~1500 файлов) и один замер стоил минуты, то есть
    сторож становился слишком дорогим, чтобы его гоняли. Отсечка ТОЧНА по
    построению: имя скрипта входит в КАЖДУЮ из пяти форм, значит файл без
    подстроки имени не может содержать ни одной из них.
    """
    if script.stem not in text:
        return False
    if hay_path.stem == script.stem:
        return bool(pats["path"].search(text) or pats["module"].search(text))
    if pats["file"].search(text) or pats["module"].search(text):
        return True
    return hay_path.suffix == ".py" and bool(
        pats["import"].search(text) or pats["from"].search(text))


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
    """
    base = pathlib.Path(root or _ROOT)
    reg = base / _RND_REGISTRY
    try:
        text = reg.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return set()
    out = set()
    for m in entrypoint_scripts(base):
        pats = wiring_patterns(m.stem)
        if pats["file"].search(text) or pats["module"].search(text):
            out.add(m.stem)
    return out


def scripts_without_caller(root: Optional[pathlib.Path] = None) -> List[str]:
    """Сырое измерение: имена скриптов, на которые нет НИ ОДНОЙ ссылки вне тестов.

    Ссылкой считается любая из форм `wiring_patterns` — файл, `scripts.<stem>`,
    голый `import <stem>` — в plist, обёртке, модуле или workflow. Тесты не
    считаются: тест вызывает деталь, а вопрос здесь — включена ли она в проводку
    (урок цикла #144). **Комментарий тоже не считается** (цикл #227), **и
    докстринг** (цикл #255): в них вызова быть не может, а слепота к этому
    снимала скрипт с учёта молча и навсегда — `code_without_comments`.
    """
    base = pathlib.Path(root or _ROOT)
    hay = []
    for d in _HAY_DIRS:
        d_base = base / d
        if not d_base.exists():
            continue
        for p in d_base.rglob("*"):
            if p.is_file() and p.suffix in _HAY_SUFFIXES and "/tests/" not in str(p):
                try:
                    raw = p.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                hay.append((p, code_without_comments(p, raw)))
    orphans = []
    for m in entrypoint_scripts(base):
        pats = wiring_patterns(m.stem)
        if not any(p != m and _is_wiring(p, t, m, pats) for p, t in hay):
            orphans.append(m.stem)
    return sorted(orphans)


def unwired_scripts(root: Optional[pathlib.Path] = None) -> List[str]:
    """«Доставлен и мёртв»: вызывающего нет И записи в реестре R&D тоже нет.

    Ровно этот список сторожит храповик `test_unwired_scripts_ratchet`.
    """
    base = pathlib.Path(root or _ROOT)
    return sorted(set(scripts_without_caller(base)) - registry_recorded_scripts(base))
