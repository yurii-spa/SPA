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

**23.10 (решение ARB): имя в реестре — только кандидат, вычет заслуживается поимённо.**
`registry_named_scripts` (прежнее правило) стал предфильтром; вычитает
`registry_recorded_scripts` = кандидаты, подтверждённые `research_tool_verdict` по всем
признакам сразу (назначение-замер, нет записи в `data/`, нет импорта денежного пути,
полный путь в реестре закрытого списка, результат в той же записи). Неподтверждённый
кандидат остаётся под надзором. Порог «вычет < половины» живёт на когорте 13.08
(`unwired_cohort_f6b87f139.json`), где он различает реестр и «любой docs/».

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

#: Реестр карантина агентов — продукт `scripts/agent_quarantine.py` (решение владельца
#: 28.08: агента не удаляют, а откладывают; вернуть — одной командой). Инструмент
#: запускают руками по решению о партии карантина, вызывающего по расписанию у него нет
#: ПО УСТРОЙСТВУ — ровно как у R&D-замера. И доказательство того же рода: каждая запись
#: реестра несёт готовую команду возврата `python3 scripts/agent_quarantine.py restore …`,
#: то есть попасть в реестр можно только запуском инструмента (ADR-342, замер 11.09:
#: реестр называет ровно один скрипт — сам инструмент).
_QUARANTINE_REGISTRY = pathlib.Path("attic") / "agents" / "QUARANTINE.json"

#: Закрытый список реестров-продуктов. Расширение — решение (ADR), а не правка строки:
#: состав закреплён тестом `test_the_product_registries_are_a_closed_list`.
_PRODUCT_REGISTRIES = (_RND_REGISTRY, _QUARANTINE_REGISTRY)

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


#: Пакеты денежного пути: скрипт, импортирующий их, — производственный компонент,
#: а не ручной замер, сколько бы записей о нём ни было в реестре.
_MONEY_PATH = ("spa_core.execution", "spa_core.risk", "spa_core.governance",
               "spa_core.paper_trading")

#: Слова, которыми запись реестра R&D называет РЕЗУЛЬТАТ замера. Запись без любого из
#: них — анонс или упоминание, а не продукт измерения.
_RESULT_WORDS = re.compile(
    r"ПРОТЕСТИРОВАН|[Вв]ердикт|ВЕРДИКТ|[Вв]ывод|ВЫВОД|СТАТУС РЕЕСТРА|[Рр]езультат|"
    r"РЕЗУЛЬТАТ|ОПРОВЕРГ|ПОДТВЕРЖД|НЕГАТИВ")

#: Граница записи реестра R&D: заголовок, пункт-идея «- **#N…», разделитель `---`.
_RND_RECORD_BOUNDARY = re.compile(r"^(?:#{1,6} |- \*\*#\d|---\s*$)")

#: Назначение «ручной исследовательский инструмент», объявленное в докстринге модуля.
_RESEARCH_PURPOSE = re.compile(
    r"advisory|backtest|\[bt\]|\bidea\s*#\d+|outside_riskpolicy|замер|измерит|"
    r"\bR&D\b|research", re.I)

#: Вызовы, которые ПИШУТ: (имя последнего сегмента, индекс аргумента-цели или None —
#: цель это сам объект метода, `path.write_text(...)`).
_WRITE_SINKS = {
    "write_text": None, "write_bytes": None, "touch": None,
    "atomic_save": 0, "atomic_write": 0, "atomic_write_json": 0, "atomic_write_text": 0,
    "copy": 1, "copy2": 1, "copyfile": 1, "copytree": 1, "move": 1,
    "replace": 1, "rename": 1,
}


def _call_name(func: ast.AST) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _is_data_literal(value: object) -> bool:
    """Строка, ведущая в `data/`: сегмент `"data"` или префикс `"data/"`."""
    return isinstance(value, str) and (value == "data" or value.startswith("data/"))


def _write_mode(call: ast.Call, pos: int) -> bool:
    """Режим `open(...)` с записью: w / a / x / +."""
    mode = None
    if len(call.args) > pos and isinstance(call.args[pos], ast.Constant):
        mode = call.args[pos].value
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            mode = kw.value.value
    return isinstance(mode, str) and any(c in mode for c in "wax+")


def data_write_targets(source: str) -> Optional[List[str]]:
    """Куда скрипт ПИШЕТ внутри `data/` — список выражений-целей (пусто = никуда).

    `None` — не измерено (модуль не разобрался): третий исход, а не «чисто» (инв. #17).

    Цель судится по ПРОИСХОЖДЕНИЮ значения, а не по наличию слова `data` в файле:
    десятки замеров ЧИТАЮТ `data/aggressive_lab` и пишут результат в `/tmp` или в
    путь из `--json` без умолчания — это не производственный компонент. Производитель
    состояния — тот, чья цель записи (имя, атрибут `args.<dest>` по умолчанию argparse,
    вызов, f-строка) выводится из литерала `"data"` / `"data/..."`.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    assigns: Dict[str, List[ast.AST]] = {}
    defaults: Dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name):
                        assigns.setdefault(n.id, []).append(node.value)
        elif isinstance(node, ast.Call) and _call_name(node.func) == "add_argument":
            dest = None
            for a in node.args:
                if isinstance(a, ast.Constant) and isinstance(a.value, str) \
                        and a.value.startswith("--"):
                    dest = a.value.lstrip("-").replace("-", "_")
                    break
            default = None
            for kw in node.keywords:
                if kw.arg == "dest" and isinstance(kw.value, ast.Constant):
                    dest = kw.value.value
                elif kw.arg == "default":
                    default = kw.value
            if dest and default is not None:
                defaults[dest] = default

    def tainted(expr: ast.AST, seen: Set[str]) -> bool:
        for n in ast.walk(expr):
            if isinstance(n, ast.Constant) and _is_data_literal(n.value):
                return True
            if isinstance(n, ast.Name) and n.id not in seen:
                seen.add(n.id)
                if any(tainted(v, seen) for v in assigns.get(n.id, ())):
                    return True
            if isinstance(n, ast.Attribute) and ("." + n.attr) not in seen \
                    and n.attr in defaults:
                seen.add("." + n.attr)
                if tainted(defaults[n.attr], seen):
                    return True
        return False

    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node.func)
        target = None
        if name == "open":
            if isinstance(node.func, ast.Attribute):      # Path(...).open("w")
                if _write_mode(node, 0):
                    target = node.func.value
            elif node.args and _write_mode(node, 1):        # вызов open с путём и режимом записи
                target = node.args[0]
        elif name in _WRITE_SINKS:
            idx = _WRITE_SINKS[name]
            if idx is None:
                if isinstance(node.func, ast.Attribute):
                    target = node.func.value
            elif len(node.args) > idx:
                target = node.args[idx]
        if target is not None and tainted(target, set()):
            out.append(ast.unparse(target))
    return out


def money_path_imports(source: str) -> Optional[List[str]]:
    """Импорты денежного пути (`_MONEY_PATH`); `None` — модуль не разобрался."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    found = []

    def hit(mod: str) -> bool:
        return any(mod == m or mod.startswith(m + ".") for m in _MONEY_PATH)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if hit(a.name)]
        elif isinstance(node, ast.ImportFrom) and node.module:
            if hit(node.module):
                found.append(node.module)
            elif node.module == "spa_core":
                found += ["spa_core." + a.name for a in node.names
                          if hit("spa_core." + a.name)]
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and hit(node.value):
            found.append(node.value)                     # importlib.import_module("…")
    return sorted(set(found))


def _rnd_records(text: str, stem: str) -> List[Dict[str, object]]:
    """Записи реестра R&D, называющие скрипт ПОЛНЫМ путём `scripts/<stem>.py`.

    Запись — участок между границами (`_RND_RECORD_BOUNDARY`). Голое имя `<stem>.py`
    или `<stem>` записью о скрипте не является: «упомянуто» не значит «измерено им».
    """
    path = wiring_patterns(stem)["path"]
    lines = text.splitlines()
    bounds = [i for i, ln in enumerate(lines) if _RND_RECORD_BOUNDARY.match(ln)]
    out, seen = [], set()
    for i, ln in enumerate(lines):
        if not path.search(ln):
            continue
        start = max([b for b in bounds if b <= i], default=0)
        end = min([b for b in bounds if b > i], default=len(lines))
        if start in seen:
            continue
        seen.add(start)
        block = "\n".join(lines[start:end])
        out.append({"line": start + 1, "title": lines[start][:120],
                    "result": bool(_RESULT_WORDS.search(block))})
    return out


def _quarantine_records(text: str, stem: str) -> List[Dict[str, object]]:
    """Записи карантина, чья команда возврата зовёт `scripts/<stem>.py`.

    Результат записи — замер потребления на момент решения (`measurement.measured`).
    Нечитаемый JSON — ни одной записи (никого не прощаем), а не «всё прощено».
    """
    import json
    try:
        doc = json.loads(text)
    except ValueError:
        return []
    entries = doc.get("quarantined") if isinstance(doc, dict) else None
    if not isinstance(entries, dict):
        return []
    path = wiring_patterns(stem)["path"]
    out = []
    for label, e in sorted(entries.items()):
        if not isinstance(e, dict) or not path.search(str(e.get("restore", ""))):
            continue
        m = e.get("measurement")
        out.append({"line": label, "title": label,
                    "result": isinstance(m, dict) and m.get("measured") is True})
    return out


def _registry_texts(base: pathlib.Path) -> List[Tuple[pathlib.Path, str]]:
    """ЕДИНСТВЕННАЯ дверь к доказательствам вычета: файлы закрытого списка, и только они.

    И предфильтр (`registry_named_scripts`), и подтверждение (`research_tool_verdict`)
    читают реестры отсюда — подмена правила на «любой docs/» в одном месте видна обоим
    и краснит отрицательные контроли поимённо. Нечитаемый реестр просто не участвует:
    он никого не прощает (вычет сужается, надзор растёт), а не прощает всех.
    """
    out = []
    for rel in _PRODUCT_REGISTRIES:
        try:
            out.append((rel, (base / rel).read_text(encoding="utf-8", errors="ignore")))
        except OSError:
            continue
    return out


def research_tool_verdict(stem: str, root: Optional[pathlib.Path] = None) -> Dict[str, object]:
    """Подтверждён ли `scripts/<stem>.py` как ДОПУСТИМЫЙ ручной исследовательский инструмент.

    Решение ARB 23.10: вычет из-под храповика заслуживается КАЖДЫМ скриптом отдельно,
    и все признаки обязательны одновременно:

    1. **назначение** — докстринг модуля объявляет замер/бэктест/advisory (`_RESEARCH_PURPOSE`);
    2. **не производственный компонент** — ни одна цель записи не выводится из `data/`
       (`data_write_targets`) и нет импорта денежного пути (`money_path_imports`);
    3. **полный путь** `scripts/<stem>.py` в одном из реестров ЗАКРЫТОГО списка
       `_PRODUCT_REGISTRIES`;
    4. **результат** в той же записи (строка вердикта/статуса; для карантина — замер);
    5. **происхождение** на уровне записи: запись ссылается на скрипт И несёт результат
       (п. 3+4 в ОДНОЙ записи). Совпадение коммитов скрипта и записи меряется по истории,
       которой в мелком клоне нет, — поэтому здесь его нет, оно в отчёте замера.

    Отсутствие вызывающего — не дело этой функции: его мерит `scripts_without_caller`,
    и вычет применяется только к его результату.
    """
    base = pathlib.Path(root or _ROOT)
    reasons: List[str] = []
    try:
        src = (base / "scripts" / f"{stem}.py").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {"confirmed": False, "reasons": ["скрипт не прочитан — НЕ ИЗМЕРЕНО"],
                "records": []}
    try:
        doc = ast.get_docstring(ast.parse(src)) or ""
    except (SyntaxError, ValueError):
        doc = None
    if doc is None:
        reasons.append("модуль не разобран — НЕ ИЗМЕРЕНО")
    elif not _RESEARCH_PURPOSE.search(doc):
        reasons.append("докстринг не объявляет исследовательское назначение")
    writes = data_write_targets(src)
    if writes is None:
        reasons.append("цели записи не измерены")
    elif writes:
        reasons.append("пишет в data/: " + ", ".join(sorted(set(writes))))
    money = money_path_imports(src)
    if money is None:
        reasons.append("импорты не измерены")
    elif money:
        reasons.append("импортирует денежный путь: " + ", ".join(money))
    records = []
    for rel, text in _registry_texts(base):
        found = (_quarantine_records(text, stem) if rel == _QUARANTINE_REGISTRY
                 else _rnd_records(text, stem))
        records += [dict(r, registry=str(rel)) for r in found]
    if not records:
        reasons.append("полного пути scripts/%s.py нет ни в одном реестре закрытого списка"
                       % stem)
    elif not any(r["result"] for r in records):
        reasons.append("запись реестра без результата")
    return {"confirmed": not reasons, "reasons": reasons, "records": records}


def registry_named_scripts(root: Optional[pathlib.Path] = None) -> Set[str]:
    """Кандидаты: скрипты, чьё ИМЯ (`<stem>.py` / `scripts.<stem>`) есть в реестре.

    Это прежнее правило вычета (13.08) — теперь только ПРЕДФИЛЬТР. Названность не
    освобождает: освобождает `research_tool_verdict`.
    """
    base = pathlib.Path(root or _ROOT)
    texts = [text for _rel, text in _registry_texts(base)]
    out = set()
    for m in entrypoint_scripts(base):
        pats = wiring_patterns(m.stem)
        if any(m.stem in t and (pats["file"].search(t) or pats["module"].search(t))
               for t in texts):
            out.add(m.stem)
    return out


def registry_recorded_scripts(root: Optional[pathlib.Path] = None) -> Set[str]:
    """Скрипты, ПОДТВЕРЖДЁННЫЕ как ручной исследовательский инструмент (вычет храповика).

    До 23.10 сюда попадал любой скрипт, чьё имя встречалось в реестре-продукте, и вычет
    рос с каждым законным замером, а заодно мог проглотить рабочий скрипт, упомянутый в
    реестре мимоходом. Теперь — только те кандидаты (`registry_named_scripts`), у кого
    `research_tool_verdict` подтверждён по всем признакам. Неподтверждённый остаётся под
    надзором храповика.
    """
    base = pathlib.Path(root or _ROOT)
    return {s for s in registry_named_scripts(base)
            if research_tool_verdict(s, base)["confirmed"]}


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
    candidates = [p for d in _HAY_DIRS if (base / d).exists() for p in (base / d).rglob("*")]
    # Корень — НЕ рекурсивно: там живут инструменты доставки (`push_to_github.py`,
    # `push_to_github_batch.py`, `auto_push.py`), которые зовут каждая сессия и
    # `com.spa.autopush`. До 11.09 корень не читался вовсе, и сторож записи ответа
    # владельца (`check_owner_choice_authorship`, ADR-191), который пушер запускает
    # на КАЖДОЙ доставке с карточками, числился «доставленным и мёртвым».
    candidates += sorted(base.glob("*"))
    for p in candidates:
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
