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


def _python_without_docstrings(text: str) -> str:
    """Питон без ДОКСТРИНГОВ модуля/класса/функции; прочие литералы СОХРАНЕНЫ.

    Докстринг — проза о коде, и по последствиям он равен комментарию: цикл
    #227 сделал сканер комментарио-слепым, но упоминание `scripts/<имя>.py`
    в `\"\"\"…\"\"\"` продолжало числиться вызовом и держало «подключёнными»
    пять скриптов (замер 14.08, карточка `inbox-hrapovik-schitaet-upominanie-v-dokstring`).

    Вырезается ТОЛЬКО первый строковый литерал тела `Module`/`ClassDef`/
    `FunctionDef`/`AsyncFunctionDef` — то есть ровно докстринг. Любой другой
    литерал остаётся: в нём живёт настоящий вызов
    (`subprocess.run(["python3", "scripts/x.py"])`).

    Файл не разобрался (битый синтаксис) — возвращаем как есть: это СЛАБЕЕ,
    и потому названо вслух, а не спрятано. Комментарии с такого файла всё
    равно снимаются запасным путём `_cut_at_hash`.
    """
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return text
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
    return _blank_spans(text, spans) if spans else text


def code_without_comments(path: pathlib.Path, text: str) -> str:
    """Текст файла без комментариев И докстрингов — то, где может жить ВЫЗОВ.

    Замер 14.08 (цикл #227): сырой текстовый поиск не отличал вызов от
    упоминания, и `daily_paper_report` числился «подключённым» ровно потому,
    что его имя стояло в комментарии, объяснявшем, что он НЕ подключён.

    Докстринги закрыты циклом #255 — но ТОЛЬКО ПОСЛЕ того, как сканер научился
    видеть все формы проводки (`wiring_patterns`). Порядок здесь не украшение:
    `check_tracker_drift` держится докстрингами, а зовут его голым
    `import check_tracker_drift` — снять докстринги первыми значило объявить
    живой, ежедневно исполняемый скрипт сиротой, то есть покрасить храповика
    на честной работе (исход, который в этом проекте признан хуже пропуска).
    """
    suffix = path.suffix
    if suffix == ".py":
        return _python_without_docstrings(_python_without_comments(text))
    if suffix in (".sh", ".yml", ".yaml"):
        return _cut_at_hash(text)
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
