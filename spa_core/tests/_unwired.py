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

Опт-аут-флага в коде здесь намеренно НЕТ: флаг научил бы сторожа отключать.
"""
from __future__ import annotations

import ast
import io
import pathlib
import re
import tokenize
from typing import Dict, List, Optional, Set, Tuple

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_HAY_DIRS = ("launchd", "scripts", "spa_core", ".github")
_HAY_SUFFIXES = (".sh", ".plist", ".py", ".yml", ".yaml")

#: Реестр R&D-идей: единственный документ, запись в котором считается проводкой.
_RND_REGISTRY = pathlib.Path("docs") / "DYNAMIC_LEVERAGE_GUARDIAN.md"

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


def _docstring_spans(text: str) -> List[Tuple[int, int, int]]:
    """Координаты ДОКСТРИНГОВ: `(строка, начало, конец)` в символах, 1-based.

    Докстринг модуля / класса / функции — проза, и по последствиям он равен
    комментарию: `daily_paper_report` держался комментарием, объяснявшим, что
    скрипт НЕ подключён, а `run_stress_tests` — фразой в докстринге чужого
    модуля. Прочие строковые литералы НЕ трогаются: в них живёт настоящий вызов
    (`subprocess.run(["python3", "scripts/x.py"])`).
    """
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
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


def _python_without_prose(text: str) -> str:
    """Питон без комментариев И без докстрингов; прочие литералы СОХРАНЕНЫ.

    Не разобралось (битый файл, чужой синтаксис) — запасной путь `_cut_at_hash`:
    он строже сырого текста, и молчаливого возврата к слепоте здесь нет.
    """
    comments = _comment_spans(text)
    if comments is None:
        return _cut_at_hash(text)
    return _blank(text, comments + _docstring_spans(text))


def code_without_comments(path: pathlib.Path, text: str) -> str:
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
        return _python_without_prose(text)
    if suffix in (".sh", ".yml", ".yaml"):
        return _cut_at_hash(text)
    if suffix == ".plist":
        return _XML_COMMENT.sub(" ", text)
    return text


# ────────────────────────────────────────────────────────────────────────────────
# Формы вызова
# ────────────────────────────────────────────────────────────────────────────────

def imported_modules(text: str) -> Set[str]:
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
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
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
    """
    base = pathlib.Path(root or _ROOT)
    reg = base / _RND_REGISTRY
    try:
        text = reg.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return set()
    return {
        m.stem for m in entrypoint_scripts(base)
        if m.name in text or f"scripts.{m.stem}" in text
    }


#: Кэш разобранного дерева: ключ — отпечаток (путь, mtime, размер) всех файлов.
_HAY_CACHE: Dict[tuple, List[Tuple[pathlib.Path, Set[str], Set[str]]]] = {}


def _haystack(base: pathlib.Path) -> List[Tuple[pathlib.Path, Set[str], Set[str]]]:
    """`(файл, названные им скрипты, названные ПОЛНЫМ именем)` — по всем вызывающим."""
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
        mods = imported_modules(raw) if p.suffix == ".py" else set()
        plain, qualified = file_references(code_without_comments(p, raw), mods)
        hay.append((p, plain, qualified))
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
            for p, plain, qualified in hay if p != m
        )
        if not wired:
            orphans.append(stem)
    return sorted(orphans)


def unwired_scripts(root: Optional[pathlib.Path] = None) -> List[str]:
    """«Доставлен и мёртв»: вызывающего нет И записи в реестре R&D тоже нет.

    Ровно этот список сторожит храповик `test_unwired_scripts_ratchet`.
    """
    base = pathlib.Path(root or _ROOT)
    return sorted(set(scripts_without_caller(base)) - registry_recorded_scripts(base))
