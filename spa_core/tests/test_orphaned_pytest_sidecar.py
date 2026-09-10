"""Брошенные прогоны pytest НАЗЫВАЮТСЯ ежечасно, а не при следующей сессии.

Замер (карточка `owner-decision-broshennye-progony-testov…`): прогон, заказанный умершей
сессией, жжёт ядро часами, и все восемь случаев подряд находились ГЛАЗАМИ. Проверка на них
написана и работает, но расписания у неё не было.

Здесь она получает расписание — ежечасное, вместе с пульсом флота, — и НИЧЕГО НЕ УБИВАЕТ:
монитор, который действует, перестаёт быть монитором. Снятие прогона остаётся решением сессии.

Оффлайн, stdlib, пути инжектируются. LLM_FORBIDDEN.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spa_core.monitoring import agent_health_monitor as ahm


def test_the_sidecar_writes_the_artifact(tmp_path):
    ahm._write_orphaned_pytest(tmp_path)
    f = tmp_path / "orphaned_pytest.json"
    assert f.is_file(), "артефакт не записан — находка снова живёт только в чужой голове"
    doc = json.loads(f.read_text(encoding="utf-8"))
    assert "orphans" in doc and "unmeasured" in doc
    assert doc["status"] in ("clear", "collision", "unmeasured")


def test_the_third_outcome_reaches_the_artifact(tmp_path):
    """«Кому нужен прогон, НЕ ИЗМЕРЕНО» — не сирота и не порядок, и оно ДОХОДИТ до файла.

    Смешать их значит либо звать на помощь зря, либо промолчать о настоящей находке.

    Отчёт ИНЪЕКТИРУЕТСЯ: без этого тест судил бы о том, сколько прогонов сейчас на
    хосте, и один и тот же sha давал бы разный ответ на разных машинах. Первая редакция
    проверяла лишь «список существует» — и мутация «третий исход схлопнут» её не роняла.
    """
    ahm._write_orphaned_pytest(tmp_path, report={
        "status": "clear",
        "orphans": [{"pid": 111, "cwd": "/tmp/dead", "orphan_why": "сессия мертва"}],
        "orphan_unmeasured": [{"pid": 222, "cwd": "/tmp/unknown",
                               "orphan_why": "заказчик НЕ НАЗВАН"}],
    })
    doc = json.loads((tmp_path / "orphaned_pytest.json").read_text(encoding="utf-8"))
    assert [o["pid"] for o in doc["orphans"]] == [111]
    assert [o["pid"] for o in doc["unmeasured"]] == [222], (
        "третий исход не доехал до артефакта — «не измерено» стало неотличимо от «чисто»")
    assert doc["unmeasured"][0]["why"] == "заказчик НЕ НАЗВАН"


def test_the_monitor_never_kills(tmp_path):
    """Монитор НАЗЫВАЕТ и не действует — проверяется РАЗБОРОМ, а не обещанием.

    В исходнике side-car'а не должно быть ни одного вызова, снимающего процесс.
    """
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(ahm._write_orphaned_pytest))
    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            called.add(getattr(f, "attr", None) or getattr(f, "id", None))
    for forbidden in ("kill", "terminate", "killpg", "send_signal"):
        assert forbidden not in called, f"монитор вызывает {forbidden} — он перестал быть монитором"


def test_a_broken_checker_never_breaks_the_heartbeat(tmp_path, monkeypatch):
    """Отказ проверки не имеет права уронить пульс флота — но и молчать не должен."""
    bad = tmp_path / "no_such_dir_at_all"
    monkeypatch.setattr(ahm, "_PROJECT_ROOT", bad)
    ahm._write_orphaned_pytest(tmp_path)          # не поднимает исключение
    assert not (tmp_path / "orphaned_pytest.json").is_file(), (
        "проверка не отработала, а артефакт всё равно записан — это выдуманный ответ")


def test_the_sidecar_is_called_by_the_hourly_agent():
    """Проводка: модуль, который никто не зовёт, — это ADR-259 в чистом виде."""
    import ast
    import inspect
    src = inspect.getsource(ahm.main)
    tree = ast.parse(src.lstrip())
    names = {getattr(n.func, "id", None) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert "_write_orphaned_pytest" in names, "ежечасный агент не зовёт side-car"
