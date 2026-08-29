"""Новые надзорные агенты подключены к дневному циклу — и остаются подключёнными.

# LLM_FORBIDDEN

Урок проекта: скрипт с точкой входа, которого никто не вызывает, — мёртвый груз.
На 2026-08-29 в базе неподключённых числилось 12 таких; `deployment_acceptance`
о них молчит по построению (он проверяет запуск флота, а не наличие вызова).

Оба агента подключены как НЕ-гейт: их коды возврата логируются и намеренно
не влияют на цикл. Надзор не имеет права останавливать трек — иначе первая же
находка встала бы между книгой и её ежедневным продвижением.

Тест читает скрипт как ТЕКСТ и не запускает его: дневной цикл против живого
`data/` не запускается никогда.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_CYCLE = Path(__file__).resolve().parents[2] / "scripts" / "run_daily_paper_cycle.sh"

WIRED_AGENTS = ("spa_core.agents.allocation_auditor", "spa_core.agents.apy_evidencer")


def _text() -> str:
    assert _CYCLE.exists(), f"нет {_CYCLE}"
    return _CYCLE.read_text(encoding="utf-8")


@pytest.mark.parametrize("module", WIRED_AGENTS)
def test_agent_is_called_by_the_daily_cycle(module: str):
    t = _text()
    assert re.search(rf'-m\s+{re.escape(module)}\b', t), (
        f"{module} больше не вызывается дневным циклом — агент, которого никто "
        "не зовёт, не работает, а выглядит доставленным")


@pytest.mark.parametrize("module", WIRED_AGENTS)
def test_the_agent_can_never_fail_the_cycle(module: str):
    """Надзор сообщает, а не останавливает трек."""
    t = _text()
    i = t.index(f"-m {module}")
    tail = t[i:i + 400]
    assert re.search(r"_EXIT=\$\?", tail), (
        f"{module}: код возврата не захвачен — ненулевой выход может утечь в цикл")
    assert "exit $" not in tail.split("\n")[1], "агент не должен решать судьбу цикла"


def test_the_cycle_still_ends_on_the_engine_exit_code():
    """Обратный контроль: судьбу цикла по-прежнему решает движок, а не надзор."""
    t = _text()
    assert t.rstrip().endswith("exit $CYCLE_EXIT"), (
        "цикл перестал возвращать код движка — надзор мог подменить вердикт")


def test_no_set_e_that_would_turn_a_finding_into_an_abort():
    t = _text()
    assert not re.search(r"^\s*set\s+-[a-z]*e", t, re.M), (
        "появился `set -e`: находка надзора (код 1/2) уронила бы весь цикл")


def test_supervisors_run_after_the_engine_not_before():
    """Судить книгу до того, как цикл её обновил, значит судить вчерашнюю."""
    t = _text()
    engine = t.index("cycle_runner exit=")
    for module in WIRED_AGENTS:
        assert t.index(f"-m {module}") > engine, f"{module} стоит ДО движка"
