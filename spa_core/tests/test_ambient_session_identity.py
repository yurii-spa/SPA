"""Вердикт теста не решает окружение прогона — положительные контроли к сторожу.

Авария (26.08, цикл #388, карточка `inbox-commit-9cb8a7823-krasit-28-testov-zahvata`)
--------------------------------------------------------------------------------------
На ОДНОМ И ТОМ ЖЕ sha `2a9489d84` полный набор трёх файлов захвата карточек отвечал
по-разному в зависимости от того, КТО его запустил::

    python3 -m pytest spa_core/tests/test_card_claim_guard.py \\
        spa_core/tests/test_card_claim_takeover.py \\
        spa_core/tests/test_session_state_shared_root.py -q

    Мак под оркестратором (SPA_SESSION_PID экспортирован) → 197 passed
    CI                     (переменной нет)               →  28 failed, 169 passed

Разница — ровно `env -u SPA_SESSION_PID -u SPA_SESSION_ID`. Автор коммита `9cb8a7823`,
который ввёл fail-CLOSED отказ `UnmeasurableClaim`, свой прогон видел зелёным и падение
воспроизвести не мог; красный `main` при этом красил КАЖДЫЙ открытый PR, не трогавший
ни строчки этого кода.

Почему контроли меряют эффект в ДОЧЕРНЕМ процессе
--------------------------------------------------
В CI `SPA_SESSION_PID` нет вовсе, поэтому проверка «переменной не видно» зелена там сама
по себе и не проверяет НИЧЕГО (урок `guard-untested-when-default-state-makes-it-redundant`:
сторож надо проверять из состояния, в котором умолчание его не подменяет). Поэтому
ключевые контроли ниже запускают дочерний `pytest` с ЭКСПОРТИРОВАННОЙ переменной — то
самое состояние, в котором жил дефект, — и требуют от него того же ответа.

Только stdlib. LLM рядом не стоял.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

from spa_core.tests._child_pytest import run_child_pytest

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

#: Узлы, каждый из которых входил в те самые 28 падений 26.08. Меряем по одному из
#: КАЖДОГО файла: дефект был общий, но зависимость наследовалась в трёх местах отдельно.
REPAIRED_NODES = (
    "test_card_claim_guard.py::TestClaimAndRelease::test_claim_writes_fields_and_preserves_the_rest",
    "test_card_claim_takeover.py::test_takeover_lifts_the_orphaned_claim_and_records_the_reason",
    "test_session_state_shared_root.py::TestClaimAlwaysAnnounces::test_claim_writes_an_announce_entry",
)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def guard_mod():
    return _load("_test_ambient_check_card_claim", "scripts/check_card_claim.py")


@pytest.fixture(scope="module")
def ambient():
    return _load("_test_ambient_session_guard", "spa_core/tests/ambient_session_guard.py")


def _env_with_declared_session():
    """Окружение прогона в том виде, в каком его делает `scripts/agent_orchestrator.sh`."""
    env = dict(os.environ)
    env["SPA_SESSION_PID"] = str(os.getpid())
    env["SPA_SESSION_ID"] = "cycle-ambient-probe"
    return env


def _env_without_session():
    env = dict(os.environ)
    env.pop("SPA_SESSION_PID", None)
    env.pop("SPA_SESSION_ID", None)
    return env


# ── зонд: сам факт, что личность сессии до теста не доходит ───────────────────

def test_ambient_vars_are_absent_inside_a_test():
    """Зонд. В CI он зелен сам по себе — поэтому НЕ является контролем в одиночку.

    Его несущая проверка — соседний тест, который запускает ИМЕННО ЭТОТ узел в дочернем
    процессе с экспортированной переменной. Разделены намеренно: зонд обязан быть обычным
    тестом набора, иначе дочерний прогон нечего было бы адресовать.
    """
    assert os.environ.get("SPA_SESSION_PID") is None
    assert os.environ.get("SPA_SESSION_ID") is None


def test_the_probe_is_not_vacuous_when_the_variable_is_exported():
    """Положительный контроль сторожа: снять autouse-фикстуру — и этот тест краснеет.

    Дочерний прогон получает окружение с `SPA_SESSION_PID`/`SPA_SESSION_ID` — ровно то,
    в котором на Маке 26.08 было «197 passed», а в CI «28 failed».
    """
    node = f"{HERE / 'test_ambient_session_identity.py'}::test_ambient_vars_are_absent_inside_a_test"
    res = run_child_pytest(node, "-q", "-p", "no:randomly",
                           cwd=ROOT, env=_env_with_declared_session())
    assert res.returncode == 0, (
        "личность сессии дошла до теста — сторож снят или обойдён\n"
        f"{res.stdout[-3000:]}\n{res.stderr[-2000:]}")


# ── тот самый набор: один и тот же ответ при любом запускающем ────────────────

@pytest.mark.parametrize("node", REPAIRED_NODES)
def test_repaired_nodes_answer_the_same_with_and_without_the_variable(node):
    """Приёмка аварии дословно: вердикт обязан совпасть в ОБОИХ окружениях.

    Это контроль не только на сторожа, но и на явные якоря в трёх файлах: верните любой
    из них к умолчанию `_ENV_ANCHOR` И снимите фикцию — прогон без переменной покраснеет,
    и тест назовёт, какой именно узел разошёлся.
    """
    target = str(HERE / node.split("::")[0]) + "::" + "::".join(node.split("::")[1:])
    with_var = run_child_pytest(target, "-q", "-p", "no:randomly",
                                cwd=ROOT, env=_env_with_declared_session())
    without = run_child_pytest(target, "-q", "-p", "no:randomly",
                               cwd=ROOT, env=_env_without_session())
    assert with_var.returncode == without.returncode, (
        f"{node}: вердикт решает ОКРУЖЕНИЕ — с переменной rc={with_var.returncode}, "
        f"без неё rc={without.returncode}\n"
        f"--- с переменной ---\n{with_var.stdout[-2000:]}\n"
        f"--- без переменной ---\n{without.stdout[-2000:]}")
    assert with_var.returncode == 0, f"{node} красный в обоих окружениях\n{with_var.stdout[-3000:]}"


# ── обратный контроль: отказ 9cb8a7823 НЕ ослаблен ───────────────────────────

def test_claim_still_refuses_without_a_declared_process(guard_mod, tmp_path):
    """Починка не гасит то, что коммит `9cb8a7823` специально закрывал (инв. #16).

    Без якоря захват по-прежнему НЕ состоится — меняется только то, что теперь тесты
    подают якорь явно, а не наследуют его от того, кто запустил прогон.
    """
    tracker = tmp_path / "tracker"
    tracker.mkdir()
    (tracker / "agent-x.md").write_text(
        "---\ntitle: Демо\nstatus: backlog\n---\n\nтело\n", encoding="utf-8")
    log = tmp_path / "session_changes.jsonl"
    log.write_text("", encoding="utf-8")

    with pytest.raises(guard_mod.UnmeasurableClaim):
        guard_mod.claim_card("agent-x", session="cycle-bare", tracker_dir=tracker,
                             log=log, ps=lambda pid: (1, ""), self_anchor=None)


def test_the_same_claim_goes_through_with_an_explicit_anchor(guard_mod, tmp_path):
    """Обратное плечо: с явным якорем тот же вход проходит — иначе тест выше был бы
    зелёным и на коде, который вообще не умеет брать карточки."""
    tracker = tmp_path / "tracker"
    tracker.mkdir()
    (tracker / "agent-x.md").write_text(
        "---\ntitle: Демо\nstatus: backlog\n---\n\nтело\n", encoding="utf-8")
    log = tmp_path / "session_changes.jsonl"
    log.write_text("", encoding="utf-8")

    res = guard_mod.claim_card("agent-x", session="cycle-bare", tracker_dir=tracker,
                               log=log, ps=lambda pid: (1, ""),
                               self_anchor=(41721, "Sat Aug  1 13:37:28 2026"))
    assert res["claimed_by"] == "cycle-bare"


# ── сам сторож: снятие и возврат окружения ───────────────────────────────────

class TestScrubAndRestore:
    def test_restore_returns_a_value_that_was_there(self, ambient):
        env = {"SPA_SESSION_PID": "4242", "SPA_SESSION_ID": "cycle-x", "ДРУГОЕ": "не трогать"}
        saved = ambient.scrub(env)
        assert "SPA_SESSION_PID" not in env and "SPA_SESSION_ID" not in env
        assert env["ДРУГОЕ"] == "не трогать", "сторож трогает ТОЛЬКО свои две переменные"
        ambient.restore(saved, env)
        assert env["SPA_SESSION_PID"] == "4242" and env["SPA_SESSION_ID"] == "cycle-x"

    def test_restore_does_not_invent_a_variable_that_was_absent(self, ambient):
        """«Было пусто» — тоже состояние. Возврат обязан вернуть именно его."""
        env = {"SPA_SESSION_PID": "4242"}
        saved = ambient.scrub(env)
        env["SPA_SESSION_ID"] = "появилась внутри теста"
        ambient.restore(saved, env)
        assert env["SPA_SESSION_PID"] == "4242"
        assert "SPA_SESSION_ID" not in env

    def test_the_guard_is_registered_in_both_conftest_roots(self):
        """CI гоняет `spa_core/tests/` и `tests/` разными шагами — сторож нужен обоим.

        Проверяется ИСТОЧНИК (файлы conftest), а не поведение текущего прогона: прогон
        из одного корня о втором ничего сказать не может.
        """
        for rel in ("spa_core/tests/conftest.py", "tests/conftest.py"):
            src = (ROOT / rel).read_text(encoding="utf-8")
            assert "ambient_session_guard" in src, f"{rel} не подключает сторож"
            assert "_no_ambient_session_identity = " in src, \
                f"{rel} подключает модуль, но не регистрирует autouse-фикцию"
