"""Кто РЕАЛЬНО читает `getUpdates` и кто владеет смещением — замер по AST.

Зачем
------------------------------------------------------------------------------
Авария #185 (13.08): гейт перед деплоем поднял ВТОРОЙ `telegram_bot` на том же
токене рядом с живым. Два поллера на одном токене — 409-конфликты `getUpdates`,
команды владельца достаются то одному, то другому, часть теряется. Живой бот с
тех пор умеет ЗАМЕЧАТЬ конфликт (`_conflict_streak`, `spa_core/telegram/bot.py`),
но заметить — не то же, что не допустить.

Второй поллер попадает в дерево не запуском, а НАЛИЧИЕМ: модуль с собственным
циклом `getUpdates`, собственным файлом смещения и собственным `__main__`
запускается одной строкой `python3 -m …`. Именно так жил
`spa_core/alerts/bot_commands.py` — заменённый `spa_core/telegram/bot.py` ещё
14.06 (обёртка снятого агента звала УЖЕ новый модуль), но оставшийся в дереве
целиком.

Почему AST, а не грепанье (урок #227)
------------------------------------------------------------------------------
Слово `getUpdates` встречается в комментариях (`scripts/checkpoint_7day.py`) и в
докстрингах (шапка самого поллера). Текстовый поиск не отличает УПОМИНАНИЕ от
ВЫЗОВА, и цикл #227 уже поймал этот класс на себе: комментарий, объяснявший, что
скрипт не подключён, делал его «подключённым». Поэтому:

* комментарии не видит сам AST;
* докстринги (строка-выражение) вычитаются явно;
* остаётся строковый литерал в позиции, где он может быть только ПАРАМЕТРОМ
  вызова Bot API.

Только stdlib. Модули НЕ импортируются: импорт `bot.py` поднял бы клиента
Telegram — разбор обязан быть инертным (то же правило, что и в
`_telegram_doors.py`).
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, Set

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Где ищем. Тесты исключены намеренно: они ходят в Telegram только через
#: заглушки (живую попытку ловит `telegram_guard`).
SEARCH_ROOTS = ("spa_core", "scripts")

#: Метод Bot API, читающий очередь обновлений. Ровно он конфликтует с самим
#: собой: два читателя на одном токене → 409 Conflict.
POLL_METHOD = "getUpdates"

#: Признак файла, в котором бот хранит своё смещение (`update_id` + 1).
#: Два разных хранилища смещения = два независимых читателя очереди.
#:
#: Второе слово здесь не украшение и не догадка: первая редакция знала только
#: «offset» и МОЛЧА пропустила настоящее третье хранилище —
#: `data/telegram_last_update_id.json` у `telegram_watcher` (тот списан 17.08 по
#: own-55, но слово остаётся: разбор обязан видеть ОБЕ формы имени, иначе
#: следующий такой файл пройдёт незамеченным). Разбор, который видит два из
#: трёх, читается как «всё чисто» — тот же класс, что и сторож, честно
#: отвечающий не на тот вопрос.
_OFFSET_MARKERS = ("offset", "update_id")


def _iter_sources(root: Path):
    for rel_root in SEARCH_ROOTS:
        base = root / rel_root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            parts = set(path.parts)
            if "tests" in parts or "__pycache__" in parts:
                continue
            yield path


def _docstring_nodes(tree: ast.AST) -> Set[int]:
    """id() узлов-констант, которые являются докстрингами или голыми строками.

    Именно они — «упоминание», а не вызов: шапка модуля `bot_commands` называет
    `getUpdates` в первой же строке.
    """
    out: Set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            out.add(id(node.value))
    return out


def _catalogue_nodes(tree: ast.AST) -> Set[int]:
    """id() строк, лежащих ВНУТРИ словаря-справочника: ключ или его описание.

    Четвёртая форма «упоминания» после докстринга, голой строки и комментария —
    и найдена она не рассуждением, а падением прогона 18.08. Модуль
    `spa_core/monitoring/data_git_policy.py` (заведён 07600ccac тем же днём) —
    КАТАЛОГ файлов `data/**` с классом риска отката: ключ
    ``"data/tg_bot_v2_offset.json"``, значение — кортеж («H-REPLAY», проза, в
    которой сказано слово ``getUpdates``). Каталог не читает очередь и не хранит
    смещение: он ОПИСЫВАЕТ, что делает с ними бот. Разбор же видел ровно те же
    литералы, что у настоящего поллера, и объявлял второго претендента на токен.

    Цена ложной тревоги здесь выше обычного: этот сторож существует, чтобы
    поймать ВТОРОЙ `getUpdates` на одном токене (авария #185, нажатия владельца
    теряются). Сторож, который краснеет на каталоге, приучает гасить себя — и
    настоящий второй поллер проедет следующим.

    Сужение per-occurrence, а не per-module: тот же литерал в вызове или
    присваивании в ТОМ ЖЕ файле по-прежнему считается действием. Модуль,
    который и описывает, и читает, остаётся пойманным.
    """
    out: Set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for part in list(node.keys) + list(node.values):
            if part is None:
                continue
            for inner in ast.walk(part):
                if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                    out.add(id(inner))
    return out


def _code_string_constants(tree: ast.AST):
    skip = _docstring_nodes(tree) | _catalogue_nodes(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and id(node) not in skip:
            yield node.value


def poller_modules(root: Path | None = None) -> Dict[str, int]:
    """Модули, которые ЧИТАЮТ очередь обновлений: rel-путь → число литералов.

    Пустой словарь значил бы «поллера в проекте нет вовсе» — состояние, которого
    не бывает, поэтому у разбора есть положительный контроль в тестах.
    """
    root = Path(root) if root else REPO_ROOT
    found: Dict[str, int] = {}
    for path in _iter_sources(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        hits = sum(1 for s in _code_string_constants(tree) if POLL_METHOD in s)
        if hits:
            found[path.relative_to(root).as_posix()] = hits
    return found


def offset_stores(root: Path | None = None) -> Dict[str, Set[str]]:
    """Модули, которые ХРАНЯТ смещение очереди: rel-путь → имена файлов.

    Своё смещение = своя память о прочитанном. Второй такой файл означает, что
    кто-то намерен читать очередь независимо от канонического бота.
    """
    root = Path(root) if root else REPO_ROOT
    found: Dict[str, Set[str]] = {}
    for path in _iter_sources(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        names = {
            s for s in _code_string_constants(tree)
            if s.endswith(".json") and any(m in s.lower() for m in _OFFSET_MARKERS)
        }
        if names:
            found[path.relative_to(root).as_posix()] = names
    return found


# ─── Кто ВЛАДЕЕТ модулем: импорт или запуск ──────────────────────────────────
#
# Дверь в чат владельца без владельца — это дверь, которую никто не открывает,
# но открыть может любой одной строкой. Ровно таким был `bot_commands`: свой
# `__main__`, свой поллер, и ни одного вызывающего.
#
# Формы владения ровно три, и каждая — ДЕЙСТВИЕ, а не упоминание:
#   * `import` — модуль импортируют из боевого кода (разбор по AST);
#   * `launch` — точечное имя модуля стоит отдельным токеном в обёртке/plist/
#     workflow (`agent_template.sh telegram_bot spa_core.telegram.bot`);
#   * `exec`   — путь файла стоит в одной строке с интерпретатором
#     (`python scripts/site_freshness_monitor.py`).
#
# Чего формой владения НЕ считается (замер 16.08): путь файла в СПИСКЕ ДОСТАВКИ
# (`scripts/push_all_session.sh` перечисляет пути для пушера). Это ровно
# четвёртая слепота из #227 — упоминание имени принимается за вызов; здесь она
# закрыта тем, что путь засчитывается только рядом с интерпретатором, в одной
# строке.

import re as _re

from spa_core.tests import _unwired as _unwired_mod

_OWNER_HAY_DIRS = ("spa_core", "scripts", "launchd", ".github")
_OWNER_HAY_SUFFIXES = (".py", ".sh", ".plist", ".yml", ".yaml")


def _hay(root: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for rel_root in _OWNER_HAY_DIRS:
        base = root / rel_root
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.suffix not in _OWNER_HAY_SUFFIXES:
                continue
            parts = set(path.parts)
            if "tests" in parts or "__pycache__" in parts:
                continue
            try:
                out[path.relative_to(root).as_posix()] = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
    return out


def _imported_names(hay: Dict[str, str]) -> Set[str]:
    names: Set[str] = set()
    for rel, raw in hay.items():
        if not rel.endswith(".py"):
            continue
        try:
            tree = ast.parse(raw)
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    names.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                names.add(node.module)
                for alias in node.names:
                    names.add(node.module + "." + alias.name)
    return names


def module_owners(rel: str, root: Path | None = None) -> list:
    """Доказательства того, что модуль `rel` кто-то ИМПОРТИРУЕТ или ЗАПУСКАЕТ."""
    root = Path(root) if root else REPO_ROOT
    hay = _hay(root)
    return _owners_from(rel, hay, _imported_names(hay))


def _owners_from(rel: str, hay: Dict[str, str], imported: Set[str]) -> list:
    dotted = rel[:-3].replace("/", ".")
    evidence = []
    if dotted in imported:
        evidence.append("import:" + dotted)
    token = _re.compile(r"(?<![\w.\-/])" + _re.escape(dotted) + r"(?![\w.])")
    launched = _re.compile(r"python[0-9.]*\s+(?:-\S+\s+)*" + _re.escape(rel))
    for other, raw in hay.items():
        if other == rel:
            continue
        if dotted not in raw and rel not in raw:
            continue
        code = _unwired_mod.code_without_comments(Path(other), raw)
        if not other.endswith(".py") and token.search(code):
            evidence.append("launch:" + other)
        if launched.search(code):
            evidence.append("exec:" + other)
    return evidence


def ownerless(rels, root: Path | None = None) -> Dict[str, list]:
    """Из переданных модулей — те, кого никто не импортирует и не запускает."""
    root = Path(root) if root else REPO_ROOT
    hay = _hay(root)
    imported = _imported_names(hay)
    found = {rel: _owners_from(rel, hay, imported) for rel in rels}
    return {rel: ev for rel, ev in found.items() if not ev}
