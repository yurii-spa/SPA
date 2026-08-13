"""Кто РЕАЛЬНО стучится в чат владельца напрямую — измерение, а не грепанье.

Зачем
------------------------------------------------------------------------------
13.08 владелец дважды пожаловался на одно и то же: поток одинаковых сообщений и
невозможность узнать, кто их шлёт. Оба раза чинили дверь, а класс оставался: у
проекта их несколько, и защиту они разбирали ПОПОЛАМ — кто-то брал лимит потока
без дедупа, кто-то слал вовсе мимо журнала. Цикл #215 свёл под общий
``guard_outbound`` две двери, #218 — оставшиеся три.

Дальше нужен храповик, иначе четвёртая дверь появится молча.

Почему разбор идёт по AST, а не текстом
------------------------------------------------------------------------------
Наивное правило «в файле есть `api.telegram.org` + `sendMessage` и нет
`guard_outbound`» даёт СЕМЬ имён, и все семь — ложные:

* пятеро (`telegram_manager`, `alert_dispatcher`, `telegram_daily_digest`,
  `telegram_protocols_reporter`, `auto_fixer`) ВЫВЕДЕНЫ ИЗ СТРОЯ ещё в Phase-1:
  текст уезжает в дайджест, POST'а нет вовсе — от константы URL остался мёртвый
  литерал;
* двое (`family_fund/lead_tracker`, `family_fund/telegram_blast`) уже делегируют
  каноническому клиенту, а константу держат для совместимости подписи.

Занести такое в базу значило бы «покрасить» храповик именами, за которыми нет
поведения, — ровно то, от чего цикл #214 отказался в храповике неподключённых
скриптов («измерено, не выбрано»). Поэтому дверью считается только то, что
ДЕЙСТВИТЕЛЬНО отправляет: в одной функции сходятся (а) URL Telegram, (б) вызов
``urlopen``, (в) метод, адресованный чату (``sendMessage`` / ``editMessageText``).
Метод берётся из той же функции: ``getUpdates``/``getMe``/``answerCallbackQuery``
чат не трогают и заслона не требуют.

Только stdlib, без сети и без импорта разбираемых модулей (импорт `bot.py` поднял
бы клиента Telegram — разбор обязан быть инертным).
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Где ищем. Тесты исключены намеренно: они ходят в Telegram только через
#: заглушки, а живую попытку ловит `telegram_guard` (он же и сторож той аварии).
SEARCH_ROOTS = ("spa_core", "scripts")

TELEGRAM_HOST = "api.telegram.org"

#: Методы Bot API, адресованные ЧАТУ владельца. Только они требуют заслона.
CHAT_BOUND_METHODS = ("sendMessage", "editMessageText")

#: Единственная проверка перед отправкой (см. `telegram_client.guard_outbound`).
GUARD = "guard_outbound"

#: Второй ЗАКОННЫЙ исход для сообщения, адресованного чату: не отправлять вовсе, а
#: положить в дайджест (Phase-1: «выведено из строя как пуш»). Такая дверь владельца
#: не беспокоит по построению, и требовать от неё заслона бессмысленно — но и молча
#: пропускать её нельзя, поэтому она названа здесь, а не забыта.
DIGEST_ROUTE = "enqueue_digest"


def _mentions_host(node: ast.AST) -> bool:
    """Есть ли в поддереве строковый литерал с хостом Telegram (в т.ч. внутри f-строки)."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and TELEGRAM_HOST in sub.value:
            return True
    return False


def _calls_urlopen(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            fn = sub.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name == "urlopen":
                return True
    return False


def _chat_bound_methods(node: ast.AST) -> List[str]:
    found = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            for m in CHAT_BOUND_METHODS:
                if m in sub.value and m not in found:
                    found.append(m)
    return found


def _mentions_symbol(node: ast.AST, symbol: str) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id == symbol:
            return True
        if isinstance(sub, ast.Attribute) and sub.attr == symbol:
            return True
        if isinstance(sub, ast.alias) and symbol in (sub.name, sub.asname):
            return True
    return False


def _guarded(node: ast.AST) -> bool:
    """Законный исход: спросить общий заслон ИЛИ увести сообщение в дайджест."""
    return _mentions_symbol(node, GUARD) or _mentions_symbol(node, DIGEST_ROUTE)


def _url_bindings(tree: ast.AST) -> tuple:
    """Куда в этом модуле кладут URL Telegram: ``([имена], [атрибуты])``.

    Атрибуты нужны из-за `bot.py`: базовый URL там собирается в ``__init__``
    (``self.api_base = "https://api.telegram.org/bot…"``), а POST уходит в
    ``_api_call``, где хоста в тексте нет вовсе. Без этого разбор не увидел бы
    ГЛАВНУЮ дверь проекта и храповик молча пропустил бы её целиком.
    """
    names: List[str] = []
    attrs: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None and _mentions_host(node.value):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name):
                    names.append(t.id)
                elif isinstance(t, ast.Attribute):
                    attrs.append(t.attr)
    return names, attrs


def _uses_names(node: ast.AST, names: List[str], attrs: List[str] = ()) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id in names:
            return True
        if isinstance(sub, ast.Attribute) and sub.attr in attrs:
            return True
    return False


def scan_file(path: Path) -> List[Dict[str, object]]:
    """Двери этого файла: список ``{function, methods, guarded}``."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    if TELEGRAM_HOST not in text:
        return []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    url_vars, url_attrs = _url_bindings(tree)
    doors: List[Dict[str, object]] = []
    #: Общий транспорт: URL + urlopen есть, а имя метода приходит АРГУМЕНТОМ
    #: (`bot.py::_api_call`). Сам он не дверь — дверью делает его звонящий, и
    #: судить надо звонящего: именно так устроена третья дверь, `edit_message_text`.
    transports: List[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not _calls_urlopen(node):
            continue
        if not (_mentions_host(node) or _uses_names(node, url_vars, url_attrs)):
            continue
        methods = _chat_bound_methods(node)
        if not methods:
            transports.append(node.name)
            continue
        doors.append({
            "function": node.name,
            "methods": methods,
            "guarded": _guarded(node),
        })

    if transports:
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name in transports:
                continue
            methods: List[str] = []
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Call):
                    continue
                fn = sub.func
                callee = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                if callee not in transports:
                    continue
                for arg in sub.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        for m in CHAT_BOUND_METHODS:
                            if m == arg.value and m not in methods:
                                methods.append(m)
            if methods:
                doors.append({
                    "function": node.name,
                    "methods": methods,
                    "guarded": _guarded(node),
                })
    return doors


def scan_repo(root: Path | None = None) -> Dict[str, List[Dict[str, object]]]:
    """Все двери репозитория: ``{путь-от-корня: [двери]}`` (только не-тестовый код)."""
    root = root or REPO_ROOT
    out: Dict[str, List[Dict[str, object]]] = {}
    for base in SEARCH_ROOTS:
        for path in sorted((root / base).rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if "/tests/" in rel or rel.startswith("tests/"):
                continue
            doors = scan_file(path)
            if doors:
                out[rel] = doors
    return out


def unguarded(root: Path | None = None) -> Dict[str, List[str]]:
    """``{путь: [функции]}`` — двери в чат владельца БЕЗ общего заслона."""
    out: Dict[str, List[str]] = {}
    for rel, doors in scan_repo(root).items():
        names = [str(d["function"]) for d in doors if not d["guarded"]]
        if names:
            out[rel] = names
    return out
