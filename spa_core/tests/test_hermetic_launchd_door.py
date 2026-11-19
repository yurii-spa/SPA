"""Приёмка ЕДИНСТВЕННОЙ двери герметичного launchd (ADR-1065).

Каждый тест ниже — КОНТРОЛЬ, и контроли идут в обе стороны:

* **положительный** воспроизводит настоящую аварию 2026-11-19 (прод-код ВПРАВДУ
  зовёт мутирующий `launchctl`, и зов МОЛЧИТ) — без него правка была бы
  украшением: проверка, никогда не видевшая поломки, ничего не держит;
* **обратный** требует, чтобы закрытая дверь ничего не ОТМЕНЯЛА: вердикт правила
  3b остаётся контрактом прод-кода, перехваченное действие ЗАПИСАНО, а после
  выхода из двери атрибуты модулей — ИСХОДНЫЕ.

Третий исход (инв. #17) различим: дверь, до которой сцена не ходит, закрыта
ГРОМКО и называет причину, а не возвращает безобидный успех.

# LLM_FORBIDDEN
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime as dt
import pathlib
import subprocess

import pytest

from spa_core.monitoring import catchup_cycle, threat_reactor
from spa_core.tests import _hermetic_launchd

_TESTS = pathlib.Path(__file__).resolve().parent

#: Файлы, чьи сцены ОБЯЗАНЫ брать дверь из единственного места. Перечень ЗАМКНУТ
#: намеренно: это контроль ПРОВОДКИ трёх названных сайтов, а не растущая база, в
#: которую можно дописать файл, чтобы погасить падение.
_WIRED = (
    "test_self_heal.py",
    "test_chaos_resilience.py",
    "test_alert_recovery_stuck_events.py",
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Положительный контроль: дверь ЕСТЬ, и прод-код в неё ходит МОЛЧА
# ─────────────────────────────────────────────────────────────────────────────
def test_the_prod_code_really_does_call_a_mutating_launchctl(monkeypatch):
    """Воспроизведение аварии: `threat_reactor.py:277` поднимает НАСТОЯЩИЙ зов.

    Если этот тест когда-нибудь станет зелёным «сам», значит прод-код перестал
    звать `launchctl` — и тогда вся дверь ниже не нужна. Пока он красен без
    двери, дверь обязана быть.
    """
    seen: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run",
                        lambda argv, **kw: seen.append([str(x) for x in argv]))

    threat_reactor._kickstart_cycle()

    assert len(seen) == 1, seen
    argv = seen[0]
    assert "launchctl" in argv[0]
    assert argv[1] in _hermetic_launchd.MUTATING_VERBS, argv
    assert argv[-1].endswith(_hermetic_launchd.threat_reactor_label()), argv


def test_the_real_call_is_SILENT_so_a_differential_measure_would_miss_it():
    """Почему класс нельзя мерить сменой вердикта.

    Зов обёрнут `except Exception: pass`, поэтому ни упавшая подмена, ни
    отсутствующий `launchctl` не делают тест красным. Пойманный зов обязан
    записываться, а не судиться по исходу теста.
    """
    source = (pathlib.Path(threat_reactor.__file__)).read_text(encoding="utf-8")
    body = source[source.index("def _kickstart_cycle("):]
    body = body[:body.index("\ndef ")]
    assert "except Exception" in body, body
    assert "raise" not in body, body


# ─────────────────────────────────────────────────────────────────────────────
# 2. Прямая сторона: дверь закрыта, действие ЗАПИСАНО, а не исполнено
# ─────────────────────────────────────────────────────────────────────────────
def test_the_closed_door_records_the_action_instead_of_executing_it(monkeypatch):
    seen: list[list[str]] = []
    monkeypatch.setattr(subprocess, "run",
                        lambda argv, **kw: seen.append([str(x) for x in argv]))

    with _hermetic_launchd.closed() as door:
        threat_reactor._kickstart_cycle()

    assert seen == [], f"настоящий subprocess всё-таки позван: {seen}"
    assert door.calls == [
        f"threat_reactor._kickstart_cycle:{_hermetic_launchd.threat_reactor_label()}"
    ], door.calls


def test_the_monkeypatch_installer_closes_the_same_doors(monkeypatch):
    """Два установщика — ОДИН перечень. Разойдись они, у pytest-файлов и
    unittest-файлов были бы РАЗНЫЕ двери, то есть снова две."""
    door = _hermetic_launchd.close_with_monkeypatch(monkeypatch)
    plan = _hermetic_launchd._plan(door, catchup_verdict=catchup_cycle.CYCLE_PRESENT)

    for module, name, _replacement in plan:
        current = getattr(module, name)
        assert current.__module__ == _hermetic_launchd.__name__, (name, current)


def test_a_door_the_scene_never_walks_through_is_closed_LOUDLY():
    """Третий исход: не «безобидный успех», а отказ с НАЗВАННОЙ причиной."""
    with _hermetic_launchd.closed():
        with pytest.raises(AssertionError, match="НАСТОЯЩИЙ мутирующий launchd"):
            catchup_cycle._kickstart(catchup_cycle.DAILY_CYCLE_LABEL)
        with pytest.raises(AssertionError, match="НАСТОЯЩИЙ мутирующий launchd"):
            catchup_cycle._alert("что угодно")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Обратная сторона: дверь ничего не ОТМЕНЯЕТ и не ПЕРЕЖИВАЕТ сцену
# ─────────────────────────────────────────────────────────────────────────────
def test_the_door_does_not_outlive_the_scene():
    """Подмена, пережившая тест, глушит дверь у СОСЕДЕЙ в том же процессе.

    Ровно так устроено `tests/test_kill_switch_eval_path.py` (прямое присваивание
    атрибута модуля без возврата), и после такого «дверь закрыта» неотличимо от
    «её закрыл сосед» — перепись класса становится слепой.
    """
    before = {name: getattr(module, name)
              for module, name, _ in _hermetic_launchd._plan(
                  _hermetic_launchd.LaunchdDoor(),
                  catchup_verdict=catchup_cycle.CYCLE_PRESENT)}

    with _hermetic_launchd.closed():
        inside = {name: getattr(module, name)
                  for module, name, _ in _hermetic_launchd._plan(
                      _hermetic_launchd.LaunchdDoor(),
                      catchup_verdict=catchup_cycle.CYCLE_PRESENT)}

    after = {name: getattr(module, name)
             for module, name, _ in _hermetic_launchd._plan(
                 _hermetic_launchd.LaunchdDoor(),
                 catchup_verdict=catchup_cycle.CYCLE_PRESENT)}

    assert inside != before, "дверь не закрылась вовсе"
    assert after == before, "подмена пережила сцену"


def test_the_declared_verdict_is_still_the_prod_contract():
    """Инъекция закрывает дверь, а не отменяет правило 3b (инв. #16).

    Объявит сцена `not_measured` — вердикт обязан дойти до вызывающего как
    `not_measured`, иначе дверь стала бы глушителем.
    """
    with _hermetic_launchd.closed(catchup_verdict=catchup_cycle.NOT_MEASURED) as door:
        verdict = catchup_cycle.run(write=True)

    assert verdict["verdict"] == catchup_cycle.NOT_MEASURED
    assert verdict["dry_run"] is False
    assert door.calls == [f"catchup_cycle.run:{catchup_cycle.NOT_MEASURED}"], door.calls


# ─────────────────────────────────────────────────────────────────────────────
# 4. ПОЧЕМУ сцена не вправе одалживать этот вердикт у хоста
# ─────────────────────────────────────────────────────────────────────────────
def test_the_live_verdict_is_a_property_of_the_HOUR_OF_DAY():
    """Замер, из-за которого правка и понадобилась.

    При ОДНОЙ И ТОЙ ЖЕ отметке снимка живой вердикт меняется от того, в каком
    часу пошёл прогон: до `CATCHUP_HOUR_UTC` — `not_due`, после — `launched`.
    Сцена, читающая его у хоста, краснеет от КАЛЕНДАРЯ при неизменных байтах.
    """
    day = "2026-07-04"  # FROZEN-DATE-OK: отметка снимка в git-каноне дерева прогона
    before = catchup_cycle.decide(
        now=dt.datetime(2026, 11, 19, catchup_cycle.CATCHUP_HOUR_UTC - 1, 20,
                        tzinfo=dt.timezone.utc),
        last_cycle_day=day, unmeasured_reason=None, last_attempt_day=None)
    after = catchup_cycle.decide(
        now=dt.datetime(2026, 11, 19, catchup_cycle.CATCHUP_HOUR_UTC, 20,
                        tzinfo=dt.timezone.utc),
        last_cycle_day=day, unmeasured_reason=None, last_attempt_day=None)

    assert before["verdict"] == catchup_cycle.NOT_DUE
    assert before["launch"] is False
    assert after["verdict"] == catchup_cycle.LAUNCHED
    assert after["launch"] is True


def test_observation_is_not_forbidden_only_mutation_is():
    """Запрещать `launchctl list` значило бы запретить НАБЛЮДЕНИЕ."""
    assert "list" not in _hermetic_launchd.MUTATING_VERBS
    assert "print" not in _hermetic_launchd.MUTATING_VERBS
    assert "kickstart" in _hermetic_launchd.MUTATING_VERBS
    assert "bootout" in _hermetic_launchd.MUTATING_VERBS


# ─────────────────────────────────────────────────────────────────────────────
# 5. Проводка: три сайта берут дверь из ЕДИНСТВЕННОГО места
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", _WIRED)
def test_each_wired_site_takes_the_door_from_the_single_place(name):
    """Копия фикстуры в файле — это ВТОРАЯ дверь, и расходятся они молча.

    Контроль именно на ввоз и зов: «похожий код рядом» дверью не является.
    """
    source = (_TESTS / name).read_text(encoding="utf-8")
    assert "from spa_core.tests import _hermetic_launchd" in source, name
    assert ("_hermetic_launchd.closed(" in source
            or "_hermetic_launchd.close_with_monkeypatch(" in source), name
