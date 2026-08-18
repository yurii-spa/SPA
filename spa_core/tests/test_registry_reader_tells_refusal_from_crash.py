"""Реестр флота обязан отличать ОТКАЗ дневного цикла от его АВАРИИ.

Карточка ``inbox-otkaz-zamka-tsikla-neotlichim-ot-avarii``, пункт 1 дословно:
«Измерить ВСЕХ читателей ``last_exit``, прежде чем менять код возврата». Коды
развели (#219, ``spa_core/paper_trading/cycle_exit.py``), читателя
``agent_health`` научили покупать тишину доказательством живого держателя
(``cycle_lock_watch.judge_lock_refusal``, 17.08) — а ВТОРОЙ читатель тех же
цифр, ``scripts/build_agent_registry.py``, остался слепым к словарю целиком.

Замер до правки (18.08, этим же способом загрузки модуля)::

    last_exit=1 → ['последний выход 1 (проверить)']   ← АВАРИЯ цикла
    last_exit=2 → ['последний выход 2 (проверить)']   ← защита сработала
    last_exit=3 → ['последний выход 3 (проверить)']   ← штатный отказ политики

Три противоположных исхода — одна и та же строка, и все три одинаково поднимают
``problem_count``, который ``/admin/agents`` рисует красным KPI. Правильная
работа системы была неотличима от поломки, а настоящая авария тонула в шуме.

**Тесты — в ОБЕ стороны.** Здесь не только «штатное молчит», но и:
  * авария (1) по-прежнему краснит — при ЛЮБОМ состоянии замка;
  * отказ замка молчит ТОЛЬКО при предъявленном живом держателе; труп в дверях
    и «не измерено» остаются проблемой (fail-CLOSED);
  * штатный исход не исчезает бесследно — он назван вслух в ``notes``;
  * словарь применяется ТОЛЬКО к метке дневного цикла: у чужого агента та же
    тройка означает что угодно, и молчать о ней нельзя;
  * ``problem_count`` считает проблемы и НЕ считает заметки.

Никакой живой сети и никаких литеральных дат: вердикт замка подаётся ВХОДОМ
(``build(lock_verdict=...)``), ``launchctl`` и ``~/Library/LaunchAgents``
подменяются, как в ``test_build_agent_registry.py``.
"""
from __future__ import annotations

import importlib.util
import plistlib
from pathlib import Path

import pytest

from spa_core.monitoring.cycle_lock_watch import (
    CRITICAL,
    OK,
    STATE_HELD_ALIVE,
    STATE_HELD_DEAD,
    CycleLockVerdict,
)
from spa_core.paper_trading.cycle_exit import (
    CYCLE_AGENT_LABEL,
    EXIT_ERROR,
    EXIT_LOCK_REFUSED,
    EXIT_POLICY_REFUSED,
)

_REPO = Path(__file__).resolve().parents[2]
_BUILDER = _REPO / "scripts" / "build_agent_registry.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("build_agent_registry", _BUILDER)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def mod():
    return _load_module()


@pytest.fixture()
def holder_alive():
    """Замок держит ЖИВОЙ цикл — отказ остальных вызовов есть работа защиты."""
    return CycleLockVerdict(
        state=STATE_HELD_ALIVE, severity=OK, pid=4242,
        detail="цикл идёт: держатель pid=4242 жив",
    )


@pytest.fixture()
def holder_dead():
    """Замок держит ТРУП — тот же отказ означает, что цикл встал (08.08)."""
    return CycleLockVerdict(
        state=STATE_HELD_DEAD, severity=CRITICAL, pid=98535,
        detail="замок держит МЁРТВЫЙ процесс pid=98535",
    )


# --------------------------------------------------------------- judge_last_exit

def test_crash_stays_loud_whatever_the_lock_says(mod, holder_alive, holder_dead):
    """Авария цикла — проблема ВСЕГДА. Живой держатель её не выкупает.

    Это зеркальный fail-OPEN, на котором споткнулись 17.08: тишина, купленная
    доказательством, доставалась исходу, к которому доказательство не относится.
    """
    for verdict in (holder_alive, holder_dead, None):
        problem, note = mod.judge_last_exit(
            CYCLE_AGENT_LABEL, EXIT_ERROR, lock_verdict=verdict)
        assert problem, f"авария замолчала при вердикте {verdict}"
        assert note is None
        assert "АВАРИЯ" in problem


def test_lock_refusal_is_silent_only_with_a_live_holder(mod, holder_alive):
    problem, note = mod.judge_last_exit(
        CYCLE_AGENT_LABEL, EXIT_LOCK_REFUSED, lock_verdict=holder_alive)
    assert problem is None, "законный отказ замка всё ещё краснит пульт"
    assert note and "4242" in note, "исход не назван вслух — это тишина, а не информация"


def test_lock_refusal_over_a_corpse_stays_a_problem(mod, holder_dead):
    """Труп в дверях: тот же код 2, противоположный смысл — цикл ВСТАЛ."""
    problem, note = mod.judge_last_exit(
        CYCLE_AGENT_LABEL, EXIT_LOCK_REFUSED, lock_verdict=holder_dead)
    assert problem, "отказ над трупом погашен вместе с законным — сигнал потерян"
    assert note is None
    assert "НЕ ДОКАЗАНА" in problem


def test_lock_refusal_with_unmeasured_lock_stays_a_problem(mod):
    """«Не измерено» никогда не хранится как «в порядке» (fail-CLOSED)."""
    problem, note = mod.judge_last_exit(
        CYCLE_AGENT_LABEL, EXIT_LOCK_REFUSED, lock_verdict=None)
    assert problem and note is None
    assert "НЕ ДОКАЗАНА" in problem


def test_policy_refusal_is_information_not_a_problem(mod):
    """13.08 этот исход держал агента в WARNING круглые сутки на исправной работе."""
    problem, note = mod.judge_last_exit(
        CYCLE_AGENT_LABEL, EXIT_POLICY_REFUSED, lock_verdict=None)
    assert problem is None
    assert note and str(EXIT_POLICY_REFUSED) in note


def test_the_three_outcomes_are_no_longer_the_same_string(mod, holder_alive):
    """Прямой положительный контроль на дефект из карточки.

    До правки все три кода давали ОДНУ строку «последний выход N (проверить)»;
    различала их только цифра, а не смысл.
    """
    said = {
        code: mod.judge_last_exit(CYCLE_AGENT_LABEL, code, lock_verdict=holder_alive)
        for code in (EXIT_ERROR, EXIT_LOCK_REFUSED, EXIT_POLICY_REFUSED)
    }
    # Авария — единственная из трёх, кто краснит.
    assert said[EXIT_ERROR][0] is not None
    assert said[EXIT_LOCK_REFUSED][0] is None
    assert said[EXIT_POLICY_REFUSED][0] is None
    # И ни одна пара исходов не описывается одинаковыми словами.
    texts = [(p or "") + (n or "") for p, n in said.values()]
    # Цифру убираем: сравниваем СМЫСЛ, а не номер кода.
    stripped = [t.replace(str(c), "#") for t, c in zip(texts, said)]
    assert len(set(stripped)) == 3, f"исходы неразличимы по смыслу: {stripped}"


def test_dictionary_is_not_applied_to_other_agents(mod, holder_alive):
    """У чужого агента тройка означает что угодно — молчать о ней нельзя."""
    for label in ("com.spa.telegram_bot", "com.spa.apiserver"):
        for code in (EXIT_LOCK_REFUSED, EXIT_POLICY_REFUSED):
            problem, note = mod.judge_last_exit(label, code, lock_verdict=holder_alive)
            assert problem, f"{label} exit={code} замолчал по чужому словарю"
            assert note is None


def test_clean_exits_stay_clean(mod, holder_alive):
    """0 и SIGTERM(-15) не порождают ни проблемы, ни шумной заметки."""
    for code in (None, 0, -15):
        assert mod.judge_last_exit(CYCLE_AGENT_LABEL, code,
                                   lock_verdict=holder_alive) == (None, None)


# --------------------------------------------------------------- build() целиком

def _wire(mod, monkeypatch, tmp_path, loaded):
    # Плист на месте для каждого агента — иначе сборщик добавит СВОЮ проблему
    # («не переживёт reboot»), и тест мерил бы не то, ради чего написан.
    for label in loaded:
        (tmp_path / f"{label}.plist").write_bytes(
            plistlib.dumps({"StartCalendarInterval": {"Hour": 8, "Minute": 0}}))
    monkeypatch.setattr(mod, "_launchctl", lambda: loaded)
    monkeypatch.setattr(mod, "_retired", lambda: set())
    monkeypatch.setattr(mod, "_LAUNCH_DIR", tmp_path)


def _cycle(reg):
    return {a["label"]: a for a in reg["agents"]}[CYCLE_AGENT_LABEL]


def test_build_does_not_count_a_legitimate_refusal_as_a_problem(
        mod, monkeypatch, tmp_path, holder_alive):
    """Сквозь весь сборщик: KPI «Проблемы» не растёт от работы защиты.

    08.08 цикл звали 20 раз, 18 — отказ замка, ни одной аварии, и пульт светился.
    """
    _wire(mod, monkeypatch, tmp_path,
          loaded={CYCLE_AGENT_LABEL: {"pid": 0, "last_exit": EXIT_LOCK_REFUSED}})
    reg = mod.build(lock_verdict=holder_alive)
    a = _cycle(reg)
    assert a["problems"] == []
    assert a["notes"], "исход исчез с пульта совсем — тишина вместо информации"
    assert reg["problem_count"] == 0


def test_build_still_counts_a_real_crash(mod, monkeypatch, tmp_path, holder_alive):
    _wire(mod, monkeypatch, tmp_path,
          loaded={CYCLE_AGENT_LABEL: {"pid": 0, "last_exit": EXIT_ERROR}})
    reg = mod.build(lock_verdict=holder_alive)
    a = _cycle(reg)
    assert a["problems"], "авария цикла перестала попадать в проблемы"
    assert a["notes"] == []
    assert reg["problem_count"] == 1


def test_build_counts_a_refusal_held_by_a_corpse(
        mod, monkeypatch, tmp_path, holder_dead):
    _wire(mod, monkeypatch, tmp_path,
          loaded={CYCLE_AGENT_LABEL: {"pid": 0, "last_exit": EXIT_LOCK_REFUSED}})
    reg = mod.build(lock_verdict=holder_dead)
    assert reg["problem_count"] == 1
    assert _cycle(reg)["notes"] == []


def test_every_agent_record_carries_notes(mod, monkeypatch, tmp_path, holder_alive):
    """Поле обязано существовать всегда — читателю нельзя гадать, есть ли оно."""
    _wire(mod, monkeypatch, tmp_path, loaded={
        CYCLE_AGENT_LABEL: {"pid": 1, "last_exit": 0},
        "com.spa.telegram_bot": {"pid": 2, "last_exit": -15},
    })
    reg = mod.build(lock_verdict=holder_alive)
    for a in reg["agents"]:
        assert isinstance(a["notes"], list), a["label"]


def test_build_reads_the_lock_when_no_verdict_is_injected(mod, monkeypatch, tmp_path):
    """Умолчание не подменяется тишиной: сборщик идёт мерить замок сам.

    Положительный контроль на пропущенную проводку: если ``build`` перестанет
    звать ``_cycle_lock_verdict``, отказ замка начнёт судиться по «не измерено»
    молча — а мы этого не заметим.
    """
    called = []
    monkeypatch.setattr(mod, "_cycle_lock_verdict",
                        lambda: called.append(1) or None)
    _wire(mod, monkeypatch, tmp_path,
          loaded={CYCLE_AGENT_LABEL: {"pid": 0, "last_exit": EXIT_LOCK_REFUSED}})
    reg = mod.build()
    assert called, "build() больше не читает замок — вердикт всегда «не измерено»"
    assert reg["problem_count"] == 1  # «не измерено» ⇒ прежняя громкость
