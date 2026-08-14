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

import io
import pathlib
import re
import tokenize
from typing import List, Optional, Set

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


def code_without_comments(path: pathlib.Path, text: str) -> str:
    """Текст файла без комментариев — то, в чём вообще может жить ВЫЗОВ.

    Замер 14.08 (цикл #227): сырой текстовый поиск не отличал вызов от
    упоминания, и `daily_paper_report` числился «подключённым» ровно потому,
    что его имя стояло в комментарии, объяснявшем, что он НЕ подключён.

    **Докстринги здесь НЕ вырезаются — и это названный пробел, а не недосмотр.**
    Упоминание в докстринге по последствиям равно комментарию, и слепота к нему
    держит «подключёнными» ещё 8 скриптов (замер того же цикла, поимённо — в
    карточке `inbox-hrapovik-schitaet-upominanie-v-dokstring`). Их разбор —
    отдельная работа: каждый требует решения «подключить или списать», а
    дописывать в базу храповика, чтобы погасить падение, запрещено.
    """
    suffix = path.suffix
    if suffix == ".py":
        return _python_without_comments(text)
    if suffix in (".sh", ".yml", ".yaml"):
        return _cut_at_hash(text)
    if suffix == ".plist":
        return _XML_COMMENT.sub(" ", text)
    return text


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


def scripts_without_caller(root: Optional[pathlib.Path] = None) -> List[str]:
    """Сырое измерение: имена скриптов, на которые нет НИ ОДНОЙ ссылки вне тестов.

    Ссылкой считается упоминание имени файла или импорта `scripts.<stem>` в
    plist, обёртке, модуле или workflow. Тесты не считаются: тест вызывает
    деталь, а вопрос здесь — включена ли она в проводку (урок цикла #144).
    **Комментарий тоже не считается** (цикл #227): в нём вызова быть не может,
    а слепота к этому снимала скрипт с учёта молча и навсегда —
    `code_without_comments`.
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
        needle_file, needle_mod = m.name, f"scripts.{m.stem}"
        if not any(p != m and (needle_file in t or needle_mod in t) for p, t in hay):
            orphans.append(m.stem)
    return sorted(orphans)


def unwired_scripts(root: Optional[pathlib.Path] = None) -> List[str]:
    """«Доставлен и мёртв»: вызывающего нет И записи в реестре R&D тоже нет.

    Ровно этот список сторожит храповик `test_unwired_scripts_ratchet`.
    """
    base = pathlib.Path(root or _ROOT)
    return sorted(set(scripts_without_caller(base)) - registry_recorded_scripts(base))
