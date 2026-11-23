"""spa_core/tests/_hermetic_launchd.py — ОДНА дверь: мутирующий launchd для сцены.

**Почему дверь одна, а не фикстура в каждом файле.** ADR-1064 (19.11) закрыл ЧЕТВЁРТУЮ
дверь правила 3b (`self_heal` → `catchup_cycle.run` без инъекции) фикстурой внутри
`spa_core/tests/test_self_heal.py` — и в тот же день соседний файл с теми же сценами
покраснел на `main`: `test_chaos_resilience.py::test_self_heal_healthy_when_all_present`
зовёт `run_self_heal(dry_run=True)` СВОИМ набором заглушек, в котором правила 3b нет.
Копия фикстуры в каждом новом файле — это «половина починки, оставляющая второй сайт»:
дверей становится столько, сколько файлов, и расходятся они молча.

**Что именно здесь закрыто (замер 2026-11-19, прибор журнала W47 — плагин на единственной
двери `subprocess.run`/`Popen.__init__`, запись argv без исполнения):**

| предмет | как проявлялся |
|---|---|
| `catchup_cycle.run` из правила 3b | вердикт теста = свойство ЧАСА СУТОК: `decide` при той же отметке снимка (git-канон `2026-07-04`) отвечает `not_due` в 09:20 UTC и `launched` в 10:20 UTC (`CATCHUP_HOUR_UTC = 10`) ⇒ `actions != []` ⇒ красный тест при НЕИЗМЕННЫХ байтах |
| `threat_reactor._kickstart_cycle` (`threat_reactor.py:277`) | `test_alert_recovery_stuck_events.py::TestKillSwitchRecovery::test_no_recovery_while_a_threat_is_standing` зовёт `run_reactor()` с умолчанием `dry_run=False`, угроза есть, стоп-кран снят ⇒ ПРЯМОЙ `subprocess` поднимал НАСТОЯЩИЙ `launchctl kickstart -k gui/<uid>/com.spa.daily_cycle`, и тест при этом **ПРОХОДИЛ**: зов обёрнут `except Exception: pass` |

Второй случай опаснее первого ровно тем, что он МОЛЧИТ. Поэтому дифференциальный метод
(«прогнать дважды, предмет класса — тот, у кого МЕНЯЕТСЯ вердикт», `.claude/rules/
deployment.md`) его бы НЕ НАШЁЛ: вердикт не меняется ни в одну сторону. Нашёл прибор,
который ЗАПИСЫВАЕТ пойманный argv, а не судит по вердикту.

**Ни одно перехваченное действие не исполняется, и все они ЗАПИСАНЫ** — сцена мерит ИСХОД
(сколько запусков и каких), а не структуру кода. Дверь, о которой сцена заявляет «сюда я
не ходила», закрывается ГРОМКО (`loud=`): снимут объявленный вердикт — тест упадёт, вместо
того чтобы двинуть прод-флот.

Шов в ПРОД-коде здесь не заводится намеренно: зарегистрированная проба приёмки
`catchup_cycle_fires_once_after_the_hour` (ось `live_caller`) требует, чтобы зов
`catchup_cycle.run(...)` стоял ЛЕКСИЧЕСКИ внутри `run_self_heal`, и шов ради удобства
теста сломал бы критерий. Закрывает сцена — и закрывает ОДНИМ местом.

Только stdlib. # LLM_FORBIDDEN
"""
# LLM_FORBIDDEN
from __future__ import annotations

import contextlib
from typing import Any, Callable, Iterator

from spa_core.monitoring import catchup_cycle, threat_reactor

#: Глаголы `launchctl`, которые МЕНЯЮТ состояние флота. Опрос (`list`, `print`) сюда не
#: входит: читающий зов сцене не вредит, и запрещать его значило бы запретить наблюдение.
MUTATING_VERBS = frozenset({
    "kickstart", "bootstrap", "bootout", "load", "unload", "stop", "enable", "disable",
})


class LaunchdDoor:
    """Записи перехваченных мутирующих действий. Ни одно НЕ ИСПОЛНЕНО.

    `calls` — список строк вида ``"<модуль>.<дверь>:<аргумент>"``; сцена вправе
    утверждать о НЁМ, а не о структуре кода.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    def record(self, where: str, arg: str = "") -> bool:
        self.calls.append(f"{where}:{arg}" if arg else where)
        return True

    def __repr__(self) -> str:  # для читаемого ассерта
        return f"LaunchdDoor(calls={self.calls!r})"


def _declared_catchup(verdict: str, door: LaunchdDoor) -> Callable[..., dict[str, Any]]:
    """Вердикт правила 3b ОБЪЯВЛЯЕТ сцена, а не хост.

    Живой вердикт зависит от того, съел ли сегодняшнюю попытку кто-то другой
    (правило «не чаще одного догоняющего запуска в сутки»), поэтому ПЕРВЫЙ дошедший
    до него тест получал один ответ, а остальные — другой.
    """

    def _run(write: bool = False, **_kw: Any) -> dict[str, Any]:
        door.record("catchup_cycle.run", verdict)
        return {
            "verdict": verdict,
            "reason": f"сцена объявила вердикт правила 3b: {verdict}",
            "dry_run": not write,
        }

    return _run


def _loud(where: str) -> Callable[..., Any]:
    def _boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError(
            f"НАСТОЯЩИЙ мутирующий launchd из теста: {where} — сцена заявила, "
            f"что сюда не ходит; либо закройте дверь, либо снимите заявление"
        )

    return _boom


def _plan(door: LaunchdDoor, *, catchup_verdict: str) -> list[tuple[Any, str, Any]]:
    """ЕДИНСТВЕННЫЙ перечень дверей. Новый мутирующий зов добавляется ЗДЕСЬ.

    Возвращает тройки ``(модуль, имя атрибута, замена)``.
    """
    return [
        # Правило 3b: вердикт объявлен сценой, журнал попытки не пишется.
        (catchup_cycle, "run", _declared_catchup(catchup_verdict, door)),
        # Действия внутри соседа объявленный вердикт не достаёт вовсе ⇒ ГРОМКО.
        (catchup_cycle, "_kickstart", _loud("catchup_cycle._kickstart")),
        (catchup_cycle, "_alert", _loud("catchup_cycle._alert")),
        # `threat_reactor.py:277` — зов ЗАКОНОМЕРНО достигается сценой выздоровления
        # (угроза есть, стоп-кран снят ⇒ реактор ДЕЙСТВУЕТ), поэтому здесь ЗАПИСЬ, а
        # не отказ: иначе громкая дверь превратила бы верную сцену в ошибку.
        (threat_reactor, "_kickstart_cycle",
         lambda *_a, **_k: door.record("threat_reactor._kickstart_cycle",
                                       threat_reactor_label())),
    ]


def threat_reactor_label() -> str:
    """Какую службу будит реактор. Имя берётся из прод-кода, не перепечатывается."""
    return "com.spa.daily_cycle"


def close_with_monkeypatch(monkeypatch: Any, *,
                           catchup_verdict: str = catchup_cycle.CYCLE_PRESENT,
                           ) -> LaunchdDoor:
    """pytest-дверь. `monkeypatch` возвращает всё сам при выходе из теста."""
    door = LaunchdDoor()
    for module, name, replacement in _plan(door, catchup_verdict=catchup_verdict):
        monkeypatch.setattr(module, name, replacement, raising=False)
    return door


@contextlib.contextmanager
def closed(*, catchup_verdict: str = catchup_cycle.CYCLE_PRESENT) -> Iterator[LaunchdDoor]:
    """unittest-дверь: тот же перечень, восстановление в `finally`.

    Присваивать атрибут модуля напрямую (как делает `tests/test_kill_switch_eval_path.py`)
    нельзя: подмена ПЕРЕЖИВАЕТ тест и глушит дверь у соседей в том же процессе — после
    такого перепись класса слепа, а «дверь закрыта» неотличимо от «её закрыл сосед».
    """
    door = LaunchdDoor()
    plan = _plan(door, catchup_verdict=catchup_verdict)
    saved: list[tuple[Any, str, Any, bool]] = []
    try:
        for module, name, replacement in plan:
            had = hasattr(module, name)
            saved.append((module, name, getattr(module, name, None), had))
            setattr(module, name, replacement)
        yield door
    finally:
        for module, name, original, had in reversed(saved):
            if had:
                setattr(module, name, original)
            else:  # атрибута не было — не выдумывать его существование
                with contextlib.suppress(AttributeError):
                    delattr(module, name)


# ─────────────────────────────────────────────────────────────────────────────
# ПЕРЕПИСЬ ВТОРОГО САЙТА: кто ставит дверь ПРЯМЫМ присваиванием, без возврата
#
# ADR-1065 НАЗВАЛ этот сайт дважды (докстринги `closed()` и теста двери) и не
# закрыл его — а 23.11 перетасовка шардов цикла #1218 свела полюттера и
# положительный контроль двери в ОДИН процесс, и `main` покраснел:
# `tests/test_kill_switch_eval_path.py` держит `threat_reactor._kickstart_cycle
# = lambda: None` ПОСЛЕ своего `tearDown` (он возвращает `_DATA`, `_STATUS` и
# `_send_telegram` — и забывает четвёртый атрибут), поэтому сосед, проверяющий
# «прод-код ВПРАВДУ зовёт мутирующий launchctl», видел ПУСТОЙ список зовов.
#
# Мера отвечает на вопрос «есть ли в наборе ВТОРАЯ дверь», а не «красен ли
# кто-то сегодня»: вердикт прямого присваивания зависит от того, попал ли сосед
# на тот же шард, то есть дифференциальным методом класс НЕ ловится (тот же
# урок, что и у молчащего зова выше).
# ─────────────────────────────────────────────────────────────────────────────

#: Имена атрибутов двери берутся ИЗ САМОГО перечня, а не перепечатываются:
#: разойдись они — перепись искала бы не ту дверь, которую закрывает `closed()`.
def door_attrs() -> frozenset[str]:
    plan = _plan(LaunchdDoor(), catchup_verdict=catchup_cycle.CYCLE_PRESENT)
    return frozenset(name for _module, name, _replacement in plan)


def door_module_names() -> frozenset[str]:
    """Короткие имена модулей перечня (`threat_reactor`, `catchup_cycle`)."""
    plan = _plan(LaunchdDoor(), catchup_verdict=catchup_cycle.CYCLE_PRESENT)
    return frozenset(module.__name__.rsplit(".", 1)[-1]
                     for module, _name, _replacement in plan)


#: Каталоги, которые гоняет предписанный прогон (`CLAUDE.md`, «Команды»). Сайт
#: второй двери может жить в любом из них, и ограничиться `spa_core/tests/`
#: значило бы не увидеть РОВНО того файла, из-за которого перепись написана:
#: он лежит в `tests/`.
MEASURED_TEST_DIRS = (
    "tests", "spa_core/tests", "scripts/tests", "studio_shell",
    "spa_core/analytics/gross_of", "research/cards",
)


def _denoting_names(tree: Any, module_names: frozenset[str]) -> set[str]:
    """Имена и атрибуты ЭТОГО файла, обозначающие модуль перечня.

    Сайт пишет не `threat_reactor._kickstart_cycle = …`, а
    `self._tr._kickstart_cycle = …`, потому что `setUp` сделал `self._tr = tr`.
    Искать по короткому имени модуля значило бы не увидеть его вовсе; поэтому
    псевдонимы прослеживаются — и по `import … as`, и по присваиванию.
    """
    import ast

    denoting = set(module_names)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.rsplit(".", 1)[-1] in module_names:
                    denoting.add((alias.asname or alias.name).rsplit(".", 1)[-1])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in module_names:
                    denoting.add(alias.asname or alias.name)
    # Второй проход: псевдоним-атрибут (`self._tr = tr`) виден только после
    # того, как собраны имена — поэтому до неподвижной точки, а не одним шагом.
    for _ in range(4):
        grew = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            value = node.value
            source = None
            if isinstance(value, ast.Name):
                source = value.id
            elif isinstance(value, ast.Attribute):
                source = value.attr
            if source not in denoting:
                continue
            for target in node.targets:
                if isinstance(target, ast.Attribute) and target.attr not in denoting:
                    denoting.add(target.attr)
                    grew = True
                elif isinstance(target, ast.Name) and target.id not in denoting:
                    denoting.add(target.id)
                    grew = True
        if not grew:
            break
    return denoting


def direct_door_assignments(repo_root: Any,
                            dirs: tuple[str, ...] = MEASURED_TEST_DIRS,
                            ) -> tuple[list[str], list[str], int]:
    """Прямые присваивания атрибутов двери в тестах под `repo_root`.

    Возвращает ``(находки, НЕ РАЗОБРАНО, сколько файлов просмотрено)``.
    Находка — строка ``"<путь>:<строка> <база>.<атрибут>"``.

    Третий исход (инв. #17) ОТДЕЛЬНЫЙ: файл, который не прочитан или не
    разобран, попадает во второй список с НАЗВАННОЙ причиной, а не молча
    считается чистым. Ноль находок при непустом втором списке — не «чисто».
    """
    import ast
    import pathlib

    root = pathlib.Path(repo_root)
    attrs = door_attrs()
    module_names = door_module_names()
    hits: list[str] = []
    unparsed: list[str] = []
    seen = 0
    here = pathlib.Path(__file__).resolve()
    for rel in dirs:
        base = root / rel
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("test_*.py")):
            if path.resolve() == here:            # сама дверь — не второй сайт
                continue
            seen += 1
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, SyntaxError, ValueError) as exc:
                unparsed.append(f"{path.relative_to(root)}: "
                                f"{type(exc).__name__}: {exc}")
                continue
            denoting = _denoting_names(tree, module_names)
            for node in ast.walk(tree):
                # `AugAssign` сюда НЕ входит: `x.run += 1` дверь не ставит, а
                # широта без сцены есть мутация, которую нечем убить.
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                targets = (node.targets if isinstance(node, ast.Assign)
                           else [node.target])
                for target in targets:
                    if not isinstance(target, ast.Attribute):
                        continue
                    if target.attr not in attrs:
                        continue
                    value = target.value
                    owner = (value.id if isinstance(value, ast.Name)
                             else value.attr if isinstance(value, ast.Attribute)
                             else None)
                    if owner in denoting:
                        hits.append(f"{path.relative_to(root)}:{node.lineno} "
                                    f"{owner}.{target.attr}")
    return hits, unparsed, seen


def door_importers(repo_root: Any,
                   dirs: tuple[str, ...] = MEASURED_TEST_DIRS,
                   ) -> tuple[list[str], list[str], int]:
    """Тест-файлы, которые ВВОЗЯТ дверь. Форма та же: ``(кто, НЕ РАЗОБРАНО, сколько)``.

    Нужна, чтобы замкнутый перечень проводки (`_WIRED`) не мог МОЛЧА укоротиться:
    перечень обязан совпадать с ввозящими, а не быть короче на забытый файл.
    """
    import ast
    import pathlib

    root = pathlib.Path(repo_root)
    importers: list[str] = []
    unparsed: list[str] = []
    seen = 0
    for rel in dirs:
        base = root / rel
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("test_*.py")):
            seen += 1
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, SyntaxError, ValueError) as exc:
                unparsed.append(f"{path.relative_to(root)}: "
                                f"{type(exc).__name__}: {exc}")
                continue
            for node in ast.walk(tree):
                names = ()
                if isinstance(node, ast.ImportFrom):
                    names = tuple(a.name for a in node.names)
                elif isinstance(node, ast.Import):
                    names = tuple(a.name.rsplit(".", 1)[-1] for a in node.names)
                if "_hermetic_launchd" in names:
                    importers.append(str(path.relative_to(root)))
                    break
    return importers, unparsed, seen
