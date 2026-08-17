"""Сторож против МОЛЧАЛИВОГО мока в стратегиях турнира.

Что именно ловится и почему это отдельный модуль
------------------------------------------------
Класс S23: стратегия заявляет живой источник, импортирует адаптер внутри
``try: ... except Exception: pass``, адаптер мёртв → ошибка проглочена → стратегия
НАВСЕГДА на mock-числе, и оно уезжает в турнир как реальная оценка. Зелёный прогон
при этом бессмыслен: «стратегия заработала» на выдуманном числе выглядит ровно как
настоящий результат.

Вынесено в отдельный модуль, чтобы храповик и его база считались ОДНИМ кодом:
база, построенная другой функцией, разойдётся с проверкой на первой же правке
(тот же довод, что у `_unwired.py`).

**Три РАЗНЫХ вопроса, и ни один не заменяет другого.**

============================  ===================================  =======================
Вопрос                        Кто отвечает                          Чего НЕ проверяет
============================  ===================================  =======================
Заявленный адаптер вообще
ГРУЗИТСЯ?                     :func:`broken_live_claims`           молчит ли обработчик
Ошибка импорта проглочена
МОЛЧА?                        :func:`silently_swallowed_imports`   грузится ли адаптер
Подстановка НАЗВАНА в
рейтинге?                     тесты турнира (`mock_tainted`)        обе предыдущие
============================  ===================================  =======================

**Почему запрет мока здесь НЕ вводится.** Моки в paper-симуляции законны — без них
часть стратегий нельзя прогнать офлайн (тесты не ходят в живую сеть). Сторож,
запрещающий моки как таковые, будет отключён первым же человеком, которому он
помешал по делу, и тогда мы потеряем и то, что он ловил. Поэтому здесь ровно две
обязанности: заявленное должно ГРУЗИТЬСЯ, а провал — быть СЛЫШНЫМ.

Опт-аут-флага в коде намеренно нет: флаг научил бы сторожа отключать.

Правила: stdlib only · детерминированно · сеть не трогается (импорт модуля-адаптера
не выполняет сетевых вызовов: адаптеры ходят в сеть только из методов).
"""
from __future__ import annotations

import ast
import importlib
import pathlib
from typing import Any, Dict, Iterable, List, NamedTuple, Optional, Tuple

_ROOT = pathlib.Path(__file__).resolve().parents[2]
STRATEGIES_DIR = _ROOT / "spa_core" / "strategies"

#: Префикс пакета адаптеров: заявка на живой источник — это импорт оттуда.
_ADAPTER_PKG = "spa_core.adapters"

#: Файлы каталога стратегий, которые стратегиями не являются.
_SKIP_FILES = frozenset({
    "__init__.py",
    "strategy_registry.py",
    "strategy_selector.py",
    "strategy_config.py",
    "strategy_config_schema.py",
    "mock_provenance.py",
})


class LiveClaim(NamedTuple):
    """Заявка стратегии на живой источник: «я импортирую вот этот адаптер»."""

    strategy_file: str
    lineno: int
    module: str
    names: Tuple[str, ...]
    inside_try: bool


class SilentSwallow(NamedTuple):
    """Обработчик, который проглатывает провал импорта БЕЗ звука."""

    strategy_file: str
    handler_lineno: int
    imported_modules: Tuple[str, ...]
    exception_type: str


def _strategy_files(root: Optional[pathlib.Path] = None) -> List[pathlib.Path]:
    base = pathlib.Path(root) if root is not None else STRATEGIES_DIR
    if not base.is_dir():
        return []
    return sorted(p for p in base.glob("*.py") if p.name not in _SKIP_FILES)


def _parse(path: pathlib.Path) -> Optional[ast.Module]:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), str(path))
    except (OSError, SyntaxError):
        return None


def _imports_in(node: ast.AST) -> List[Tuple[int, str, Tuple[str, ...]]]:
    """Все импорты внутри поддерева: ``[(lineno, module, names)]``."""
    out: List[Tuple[int, str, Tuple[str, ...]]] = []
    for n in ast.walk(node):
        if isinstance(n, ast.ImportFrom):
            out.append((n.lineno, n.module or "", tuple(a.name for a in n.names)))
        elif isinstance(n, ast.Import):
            for a in n.names:
                out.append((n.lineno, a.name, ()))
    return out


def _is_adapter_module(module: str) -> bool:
    return module == _ADAPTER_PKG or module.startswith(_ADAPTER_PKG + ".")


# ─────────────────────────────────────────────────────────────────────────────
# Вопрос 1: заявленный адаптер ГРУЗИТСЯ?
# ─────────────────────────────────────────────────────────────────────────────

def live_claims(root: Optional[pathlib.Path] = None) -> List[LiveClaim]:
    """Все заявки стратегий на живой источник (импорты из ``spa_core.adapters``).

    ``inside_try=True`` означает, что заявка стоит внутри ``try`` — именно такая
    заявка может провалиться незаметно, и именно её обязан проверить импорт.
    """
    claims: List[LiveClaim] = []
    for path in _strategy_files(root):
        tree = _parse(path)
        if tree is None:
            continue
        try_lines: set = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                for lineno, module, _names in _imports_in(node):
                    try_lines.add(lineno)
        for lineno, module, names in _imports_in(tree):
            if not _is_adapter_module(module):
                continue
            claims.append(LiveClaim(
                strategy_file=path.name,
                lineno=lineno,
                module=module,
                names=names,
                inside_try=lineno in try_lines,
            ))
    return claims


def broken_live_claims(root: Optional[pathlib.Path] = None) -> List[Dict[str, Any]]:
    """Заявки, которые НЕ ГРУЗЯТСЯ: модуль не импортируется или в нём нет имени.

    Проверка **импортом**, а не ``compile``: ровно этот дефект (S23) был в том, что
    модуль компилировался, а импорт бросал исключение. ``compile`` его не увидел бы.

    Каждая находка — красный тест, а не тихий mock.
    """
    broken: List[Dict[str, Any]] = []
    cache: Dict[str, Any] = {}
    for claim in live_claims(root):
        if claim.module in cache:
            mod = cache[claim.module]
        else:
            try:
                mod = importlib.import_module(claim.module)
            except Exception as exc:  # noqa: BLE001 — это и есть находка
                mod = exc
            cache[claim.module] = mod
        if isinstance(mod, BaseException):
            broken.append({
                "strategy_file": claim.strategy_file,
                "lineno": claim.lineno,
                "module": claim.module,
                "name": None,
                "detail": f"{type(mod).__name__}: {mod}",
            })
            continue
        for name in claim.names:
            if name == "*":
                continue
            if not hasattr(mod, name):
                broken.append({
                    "strategy_file": claim.strategy_file,
                    "lineno": claim.lineno,
                    "module": claim.module,
                    "name": name,
                    "detail": f"module imports, but has no attribute {name!r}",
                })
    return broken


# ─────────────────────────────────────────────────────────────────────────────
# Вопрос 2: провал импорта проглочен МОЛЧА?
# ─────────────────────────────────────────────────────────────────────────────

def _handler_is_silent(handler: ast.ExceptHandler) -> bool:
    """Обработчик молчит, если в его теле НЕТ ни звука, ни повторного броска.

    Звуком считается вызов чего угодно (``_log.warning``, ``print``, ``warnings.warn``,
    свой ``_note_mock(...)``) — сторож не диктует, КАК шуметь, он требует, чтобы шум
    вообще был. Присваивание ``x = None`` звуком не является: это и есть тихая
    подстановка. ``raise`` / ``return`` считаются реакцией, а не тишиной.
    """
    for stmt in ast.walk(handler):
        if isinstance(stmt, (ast.Raise, ast.Return)):
            return False
        if isinstance(stmt, ast.Call):
            return False
    return True


def silently_swallowed_imports(
    root: Optional[pathlib.Path] = None,
) -> List[SilentSwallow]:
    """``try``-блоки с импортом, чей обработчик молчит.

    Считаются только ``try``, в теле которых ЕСТЬ импорт: проглоченный вызов метода
    — другой класс дефекта и здесь не судится.
    """
    found: List[SilentSwallow] = []
    for path in _strategy_files(root):
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            body_imports = [
                mod for _ln, mod, _nm in _imports_in(ast.Module(body=node.body, type_ignores=[]))
            ]
            if not body_imports:
                continue
            for handler in node.handlers:
                if not _handler_is_silent(handler):
                    continue
                found.append(SilentSwallow(
                    strategy_file=path.name,
                    handler_lineno=handler.lineno,
                    imported_modules=tuple(sorted(set(body_imports))),
                    exception_type=(
                        ast.unparse(handler.type) if handler.type is not None else "bare"
                    ),
                ))
    return found


def silent_swallow_counts(
    root: Optional[pathlib.Path] = None,
) -> Dict[str, int]:
    """``{файл_стратегии: сколько молчаливых обработчиков}`` — форма для храповика."""
    counts: Dict[str, int] = {}
    for item in silently_swallowed_imports(root):
        counts[item.strategy_file] = counts.get(item.strategy_file, 0) + 1
    return dict(sorted(counts.items()))


def format_findings(items: Iterable[Any]) -> str:
    """Человекочитаемый список находок для сообщения упавшего теста."""
    lines: List[str] = []
    for item in items:
        if isinstance(item, dict):
            lines.append(
                f"  {item.get('strategy_file')}:{item.get('lineno')} "
                f"{item.get('module')}"
                + (f".{item['name']}" if item.get("name") else "")
                + f" — {item.get('detail')}"
            )
        elif isinstance(item, SilentSwallow):
            lines.append(
                f"  {item.strategy_file}:{item.handler_lineno} "
                f"except {item.exception_type}: <молча> "
                f"вокруг импорта {', '.join(item.imported_modules)}"
            )
        else:
            lines.append(f"  {item!r}")
    return "\n".join(lines)
