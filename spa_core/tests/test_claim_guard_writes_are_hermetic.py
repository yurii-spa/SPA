"""Гейт: пишущие пути шага 0b нельзя вызвать так, чтобы они молча писали в чужой журнал.

**Дефект, который это закрывает** (карточка `agent-claim-guard-tests-write-a-real-announce-journal`,
побочная находка цикла #105, починено циклом #106). `claim_card`/`release_card` принимали
`log=DEFAULT_LOG`, а четыре вызова в `spa_core/tests/test_card_claim_guard.py` задавали журнал
не явно. Замер в свежем worktree: файла `data/session_changes.jsonl` не было ВООБЩЕ, один
прогон набора создавал его и клал 2 записи, каждый следующий добавлял ещё 2 — монотонно:

```
{"session": "pid1",   "card": "agent-x", "card_state": "done", ...}
{"session": "pid999", "card": "agent-x", "card_state": "done", ...}
```

Это ровно класс `tests-write-live-alert-state`: набор мутирует живое состояние продакшена —
здесь журнал координации, который читают шаги 0a и 0b протокола. Ущерб был латентным (живой
журнал хост-репо просканирован циклом #105 на тестовые ярлыки — 0 записей) только потому, что
§3.4 обязывает работать в worktree; одного прогона из `~/Documents/SPA_Claude` хватило бы.

**Почему гейта мало без обязательного аргумента и наоборот.** Обязательный `log` делает
«забыть его» `TypeError`'ом в точке вызова — это первый рубеж. Но он держится ровно до тех
пор, пока кто-нибудь не вернёт умолчание «чтобы не чинить вызовы»; тогда все вызовы снова
станут легальными и молча начнут писать не туда. Поэтому здесь пиннится ОБА факта: подпись
без умолчания и отсутствие вызовов без `log=`. Разбор статический (AST) — гейт не исполняет
ни одного вызова и потому сам ничего никуда не пишет.

**Почему не «поменять умолчание на `shared_log()`»** (замер цикла #106, не вкус): `DEFAULT_LOG`
из worktree = `/private/tmp/spa_wt_*/data/session_changes.jsonl` — журнал, которого не видит
никто, тогда как `announce_claim` существует ровно ради немедленной видимости захвата без
пуша; `shared_log()` = `/Users/.../SPA_Claude/data/session_changes.jsonl` — ЖИВОЙ журнал
хост-репо (394 записи на момент замера), то есть такое умолчание сделало бы тестовое
загрязнение строго хуже. Верного умолчания у пишущего пути нет — поэтому его нет вовсе.

Только stdlib, без сети и git.
"""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "scripts" / "check_card_claim.py"

# Пишущие пути: каждый из них через `announce_claim` дописывает строку в журнал объявлений.
WRITING_FUNCS = ("claim_card", "release_card")

# Где ищем вызовы. Тесты — главный источник дефекта (их гоняют из произвольного дерева),
# `scripts/` — потому что там живёт единственный прод-вызывающий (CLI).
SCANNED_DIRS = ("spa_core/tests", "tests", "scripts")


def _iter_py(rel):
    d = ROOT / rel
    if not d.exists():
        return
    for p in sorted(d.rglob("*.py")):
        yield p


def _parse(path):
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return None


def _called_name(node):
    """Имя вызываемого для `f(...)`, `mod.f(...)`, `a.b.f(...)`."""
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def find_calls_without_log():
    """Все вызовы пишущих путей, где `log=` не задан явно. Возвращает [(файл, строка, имя)]."""
    out = []
    for rel in SCANNED_DIRS:
        for path in _iter_py(rel):
            if path.resolve() == Path(__file__).resolve():
                continue                      # свои же примеры в докстринге не считаем
            tree = _parse(path)
            if tree is None:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = _called_name(node)
                if name not in WRITING_FUNCS:
                    continue
                kwargs = {kw.arg for kw in node.keywords}
                if "log" in kwargs:
                    continue
                if None in kwargs:
                    continue                  # `**kwargs` — журнал может прийти оттуда
                out.append((str(path.relative_to(ROOT)), node.lineno, name))
    return out


def signature_defaults():
    """`{имя функции: есть ли у её параметра `log` умолчание}` — из АСТ самого модуля."""
    tree = _parse(GUARD)
    assert tree is not None, f"{GUARD} не разобрался — гейт ничего не проверил"
    found = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in WRITING_FUNCS:
            continue
        args = node.args
        for arg, default in zip(args.kwonlyargs, args.kw_defaults):
            if arg.arg == "log":
                found[node.name] = default is not None
    return found


class TestTheGateItselfMeasuresSomething:
    """Fail-CLOSED: гейт, который ничего не нашёл, — не зелёный, а сломанный."""

    def test_the_guard_module_exists_and_parses(self):
        assert GUARD.exists(), f"нет {GUARD} — проверять нечего"
        assert _parse(GUARD) is not None

    def test_both_writing_functions_are_actually_found(self):
        found = signature_defaults()
        missing = [f for f in WRITING_FUNCS if f not in found]
        assert not missing, (
            f"в {GUARD.name} не найден keyword-only параметр `log` у {missing} — "
            f"гейт молча не проверил бы ничего (fail-CLOSED)")

    def test_the_scanner_finds_the_legitimate_cli_calls(self):
        """Положительный контроль разбора: вызовы CLI существуют и разбираются.

        Если этот тест перестанет находить вызовы, значит сканер ослеп — и «нарушений нет»
        стало бы утверждением о том, чего он не измерял."""
        tree = _parse(GUARD)
        names = [_called_name(n) for n in ast.walk(tree) if isinstance(n, ast.Call)]
        for f in WRITING_FUNCS:
            assert names.count(f) >= 1, f"вызов {f} в CLI не найден — сканер ослеп"


class TestWritingPathsHaveNoDefaultLog:
    @pytest.mark.parametrize("func", WRITING_FUNCS)
    def test_log_is_a_required_argument(self, func):
        """Умолчания у пишущего пути быть не должно: верного значения не существует."""
        has_default = signature_defaults()[func]
        assert has_default is False, (
            f"у `{func}` вернулось умолчание для `log`. Верного умолчания нет: дерево этого "
            f"файла = журнал, невидимый другим сессиям; главное дерево = ЖИВОЙ журнал "
            f"координации, в который тогда начнут писать тесты. Оставьте аргумент "
            f"обязательным (карточка agent-claim-guard-tests-write-a-real-announce-journal)")


class TestNobodyCallsThemWithoutAnExplicitLog:
    def test_no_call_omits_log(self):
        offenders = find_calls_without_log()
        assert offenders == [], (
            "вызов пишущего пути шага 0b без явного `log=` — журнал будет выбран за вас:\n"
            + "\n".join(f"  {f}:{ln} → {name}(...)" for f, ln, name in offenders)
            + "\nЗадайте журнал явно (в тестах — фикстура `log` из `tmp_path`).")


class TestTheScannerCatchesWhatItClaims:
    """Мутационные контроли на сам разборщик — на исходниках в памяти, файлы не трогаются."""

    @staticmethod
    def _offenders_in(src):
        tree = ast.parse(src)
        out = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _called_name(node) in WRITING_FUNCS:
                kwargs = {kw.arg for kw in node.keywords}
                if "log" not in kwargs and None not in kwargs:
                    out.append(_called_name(node))
        return out

    def test_a_bare_call_is_caught(self):
        assert self._offenders_in(
            'guard.release_card("agent-x", session="pid1", tracker_dir=t)') == ["release_card"]

    def test_a_call_with_log_is_not_caught(self):
        assert self._offenders_in(
            'guard.release_card("agent-x", session="pid1", tracker_dir=t, log=log)') == []

    def test_a_plain_name_call_is_caught_too(self):
        """Не только `mod.f(...)`: CLI зовёт `claim_card(...)` напрямую."""
        assert self._offenders_in('claim_card("agent-x", session="s")') == ["claim_card"]

    def test_kwargs_splat_is_not_reported(self):
        """`**kw` может нести `log` — отчёт о нём был бы утверждением без измерения."""
        assert self._offenders_in('guard.claim_card("agent-x", **kw)') == []

    def test_an_unrelated_function_is_ignored(self):
        assert self._offenders_in('guard.gather("agent-x", tracker_dir=t)') == []

    def test_a_default_on_log_is_detected(self):
        """Контроль к `TestWritingPathsHaveNoDefaultLog`: возврат умолчания виден в АСТ."""
        tree = ast.parse("def release_card(card, *, log=DEFAULT_LOG, force=False): pass")
        fn = tree.body[0]
        pairs = dict(zip([a.arg for a in fn.args.kwonlyargs], fn.args.kw_defaults))
        assert pairs["log"] is not None

    def test_no_default_on_log_is_detected(self):
        tree = ast.parse("def release_card(card, *, log, force=False): pass")
        fn = tree.body[0]
        pairs = dict(zip([a.arg for a in fn.args.kwonlyargs], fn.args.kw_defaults))
        assert pairs["log"] is None
