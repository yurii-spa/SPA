"""Тесты инвентаризации флота по репозиторию (`scripts/fleet_inventory.py`).

Положительный контроль (обязателен по .claude/rules/deployment.md): каждая проверка
воспроизводит НАСТОЯЩУЮ аварию из истории флота на фикстурном дереве —

  • сирота-plist без записи в конституции — класс «26 orphan-plist» / fleet parity DRIFT;
  • манифест объявляет агента, plist'а нет — установка падает;
  • один label двумя файлами (scripts/ И launchd/) — ставится тот, чью строку
    набрали в установщике, а правит человек другой;
  • `program` без файла обёртки — агент мёртв (exit 126/127) и молчит;
  • запись реестра об агенте, которого нет ни в конституции, ни в RETIRED.

И симметрично: СОГЛАСОВАННОЕ дерево проходит МОЛЧА (status OK) — сторож, который
краснеет всегда, обучают отключать.

Отдельно закреплён fail-CLOSED: нечитаемый или устаревший источник даёт `null`
(«не проверено») и вердикт UNCHECKED, а НЕ пустой список («проверено, чисто»).
Именно эту подмену — отсутствие наблюдения выдать за успех — ловит этот файл.

Время — ВХОД: возраст реестра считается от переданного `now`, отметки строятся
через `_freshness.ts()`. Литеральных дат нет.
"""
from __future__ import annotations

import importlib
import json

import pytest

from spa_core.tests._freshness import now_utc, ts

fi = importlib.import_module("scripts.fleet_inventory")


# ───────────────────────────── фикстурное дерево ─────────────────────────────

def _tree(tmp_path, *, manifest_agents, scripts_plists=(), launchd_plists=(),
          wrappers=(), registry_labels=(), registry_age_hours=1.0):
    (tmp_path / "architecture").mkdir()
    (tmp_path / "architecture" / "manifest.json").write_text(json.dumps(
        {"schema_version": 1, "agents": manifest_agents}))
    (tmp_path / "scripts").mkdir()
    (tmp_path / "launchd").mkdir()
    (tmp_path / "data").mkdir()
    for name in scripts_plists:
        (tmp_path / "scripts" / f"{name}.plist").write_text("<plist/>")
    for name in launchd_plists:
        (tmp_path / "launchd" / f"{name}.plist").write_text("<plist/>")
    for name in wrappers:
        (tmp_path / "scripts" / name).write_text("#!/bin/bash\n")
    (tmp_path / "data" / "agent_registry.json").write_text(json.dumps(
        {"model": "agent_registry", "generated_at": ts(hours_ago=registry_age_hours),
         "agents": [{"label": lbl} for lbl in registry_labels]}))
    return tmp_path


def _consistent(tmp_path):
    """Дерево без единого расхождения — эталон, от которого мутируют тесты."""
    return _tree(
        tmp_path,
        manifest_agents=[
            {"label": "com.spa.alpha", "intent": "active", "program": "agent_alpha.sh"},
            {"label": "com.spa.beta", "intent": "active", "program": "agent_beta.sh"},
        ],
        scripts_plists=["com.spa.alpha"],
        launchd_plists=["com.spa.beta"],
        wrappers=["agent_alpha.sh", "agent_beta.sh"],
        registry_labels=["com.spa.alpha", "com.spa.beta"],
    )


def _run(root, **kw):
    return fi.build_inventory(root, now=now_utc(), **kw)


# ───────────────────────────── согласованный флот молчит ─────────────────────────────

def test_consistent_fleet_is_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(fi, "retired_labels", lambda: set())
    rep = _run(_consistent(tmp_path))
    assert rep["status"] == "OK", rep["findings"]
    assert rep["unchecked_classes"] == []
    assert all(rep["findings"][k] == [] for k in fi.HARD_CLASSES)
    assert rep["counts"] == {"manifest": 2, "plist_labels": 2, "plist_files": 2,
                             "wrappers": 2, "registry": 2, "retired": 0}


# ───────────────────────────── положительный контроль: каждый класс ─────────────────────────────

def test_orphan_plist_not_in_manifest(tmp_path, monkeypatch):
    """Сирота-plist: файл в дереве есть, в конституции агента нет (класс «26 сирот»)."""
    monkeypatch.setattr(fi, "retired_labels", lambda: set())
    root = _consistent(tmp_path)
    (root / "scripts" / "com.spa.stray.plist").write_text("<plist/>")   # мутация
    rep = _run(root)
    assert rep["status"] == "DRIFT"
    assert rep["findings"]["orphan_plist_not_in_manifest"] == ["com.spa.stray"]


def test_manifest_without_plist(tmp_path, monkeypatch):
    monkeypatch.setattr(fi, "retired_labels", lambda: set())
    root = _consistent(tmp_path)
    (root / "launchd" / "com.spa.beta.plist").unlink()                  # мутация
    rep = _run(root)
    assert rep["status"] == "DRIFT"
    assert rep["findings"]["manifest_without_plist"] == ["com.spa.beta"]


def test_duplicate_plist_label(tmp_path, monkeypatch):
    monkeypatch.setattr(fi, "retired_labels", lambda: set())
    root = _consistent(tmp_path)
    (root / "launchd" / "com.spa.alpha.plist").write_text("<plist/>")   # мутация: тот же label дважды
    rep = _run(root)
    assert rep["status"] == "DRIFT"
    dup = rep["findings"]["duplicate_plist_label"]
    assert len(dup) == 1 and dup[0].startswith("com.spa.alpha (")
    assert "scripts/com.spa.alpha.plist" in dup[0] and "launchd/com.spa.alpha.plist" in dup[0]
    assert rep["counts"]["plist_files"] == 3 and rep["counts"]["plist_labels"] == 2


def test_manifest_program_missing(tmp_path, monkeypatch):
    """Обёртки, которую объявляет манифест, нет → launchd упадёт с 126/127 и промолчит."""
    monkeypatch.setattr(fi, "retired_labels", lambda: set())
    root = _consistent(tmp_path)
    (root / "scripts" / "agent_beta.sh").unlink()                       # мутация
    rep = _run(root)
    assert rep["status"] == "DRIFT"
    assert rep["findings"]["manifest_program_missing"] == ["agent_beta.sh"]


def test_wrapper_without_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(fi, "retired_labels", lambda: set())
    root = _consistent(tmp_path)
    (root / "scripts" / "agent_ghost.sh").write_text("#!/bin/bash\n")   # мутация
    rep = _run(root)
    assert rep["status"] == "DRIFT"
    assert rep["findings"]["wrapper_without_agent"] == ["agent_ghost.sh"]


def test_registry_unknown_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(fi, "retired_labels", lambda: set())
    root = _consistent(tmp_path)
    p = root / "data" / "agent_registry.json"
    data = json.loads(p.read_text())
    data["agents"].append({"label": "com.spa.mystery"})                 # мутация
    p.write_text(json.dumps(data))
    rep = _run(root)
    assert rep["status"] == "DRIFT"
    assert rep["findings"]["registry_unknown_agent"] == ["com.spa.mystery"]


# ───────────────────────────── мягкие классы называются, но не красят ─────────────────────────────

def test_retired_agent_in_registry_is_named_not_drift(tmp_path, monkeypatch):
    monkeypatch.setattr(fi, "retired_labels", lambda: {"com.spa.gone"})
    root = _consistent(tmp_path)
    p = root / "data" / "agent_registry.json"
    data = json.loads(p.read_text())
    data["agents"].append({"label": "com.spa.gone"})
    p.write_text(json.dumps(data))
    rep = _run(root)
    assert rep["status"] == "OK"
    assert rep["findings"]["registry_record_of_retired"] == ["com.spa.gone"]
    assert rep["findings"]["registry_unknown_agent"] == []


def test_wrapper_of_retired_agent_is_not_orphan(tmp_path, monkeypatch):
    monkeypatch.setattr(fi, "retired_labels", lambda: {"com.spa.gone"})
    root = _consistent(tmp_path)
    (root / "scripts" / "agent_gone.sh").write_text("#!/bin/bash\n")
    rep = _run(root)
    assert rep["status"] == "OK"
    assert rep["findings"]["wrapper_of_retired"] == ["agent_gone.sh"]
    assert rep["findings"]["wrapper_without_agent"] == []


def test_declared_non_agent_wrapper_is_a_tool(tmp_path, monkeypatch):
    monkeypatch.setattr(fi, "retired_labels", lambda: set())
    root = _consistent(tmp_path)
    (root / "scripts" / "agent_template.sh").write_text("#!/bin/bash\n")
    rep = _run(root)
    assert rep["status"] == "OK"
    assert rep["findings"]["wrapper_is_tool"] == [
        f"agent_template.sh — {fi.NON_AGENT_WRAPPERS['agent_template.sh']}"]
    assert rep["findings"]["wrapper_without_agent"] == []


# ───────────────────────────── fail-CLOSED: молчание ≠ успех ─────────────────────────────

def test_stale_registry_is_unchecked_not_clean(tmp_path, monkeypatch):
    """Реестр генерится НА MAC. Устаревший снимок обязан дать null, а не пустой список."""
    monkeypatch.setattr(fi, "retired_labels", lambda: set())
    root = _tree(tmp_path,
                 manifest_agents=[{"label": "com.spa.alpha", "intent": "active",
                                   "program": "agent_alpha.sh"}],
                 scripts_plists=["com.spa.alpha"], wrappers=["agent_alpha.sh"],
                 registry_labels=["com.spa.alpha"], registry_age_hours=500.0)
    rep = _run(root, registry_max_age_hours=48.0)
    assert rep["sources"]["registry"]["status"] == "stale"
    assert rep["findings"]["registry_unknown_agent"] is None      # НЕ []
    assert rep["status"] == "UNCHECKED"
    assert "registry_unknown_agent" in rep["unchecked_classes"]
    # тот же снимок в пределах окна — уже проверяемый
    fresh = _run(root, registry_max_age_hours=1000.0)
    assert fresh["sources"]["registry"]["status"] == "read"
    assert fresh["findings"]["registry_unknown_agent"] == []
    assert fresh["status"] == "OK"


def test_missing_registry_file_is_unchecked_not_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(fi, "retired_labels", lambda: set())
    root = _consistent(tmp_path)
    (root / "data" / "agent_registry.json").unlink()
    rep = _run(root)
    assert rep["sources"]["registry"]["status"] == "unreadable"
    assert rep["status"] == "UNCHECKED"
    assert rep["findings"]["registry_unknown_agent"] is None
    assert rep["counts"]["registry"] is None


def test_broken_manifest_is_unchecked_not_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(fi, "retired_labels", lambda: set())
    root = _consistent(tmp_path)
    (root / "architecture" / "manifest.json").write_text("{ не json")
    rep = _run(root)
    assert rep["sources"]["manifest"]["status"] == "unreadable"
    assert rep["status"] == "UNCHECKED"
    assert rep["findings"]["orphan_plist_not_in_manifest"] is None
    assert rep["findings"]["manifest_without_plist"] is None
    assert rep["counts"]["manifest"] is None


def test_broken_retired_import_does_not_silently_pass(tmp_path, monkeypatch):
    """Без RETIRED_LABELS «сирота» и «списанный» неразличимы → не судить, а признать."""
    def boom():
        raise ImportError("agent_health_monitor сломан")
    monkeypatch.setattr(fi, "retired_labels", boom)
    rep = _run(_consistent(tmp_path))
    assert rep["sources"]["retired_labels"]["status"] == "unreadable"
    assert rep["status"] == "UNCHECKED"
    assert rep["findings"]["wrapper_without_agent"] is None
    assert rep["findings"]["registry_unknown_agent"] is None


# ───────────────────────────── честность про Mac + живой прогон ─────────────────────────────

def test_live_fleet_questions_are_named_with_commands(tmp_path, monkeypatch):
    """Источник правды о флоте — launchctl, и он недоступен из облака ПО ПОСТРОЕНИЮ.

    Отчёт обязан НАЗЫВАТЬ эти вопросы вместе с командой, а не делать вид, что
    их не существует.
    """
    monkeypatch.setattr(fi, "retired_labels", lambda: set())
    rep = _run(_consistent(tmp_path))
    cmds = " ".join(q["command"] for q in rep["not_measurable_here"])
    assert "launchctl list" in cmds
    assert "LaunchAgents" in cmds
    assert all(q["question"] and q["command"] for q in rep["not_measurable_here"])
    assert "launchctl" in rep["scope"]


def test_live_repo_inventory_runs_and_reports_all_four_counts():
    """Прогон против настоящего дерева: вердикт может быть любым, но четыре числа
    обязаны быть измерены, а не None (иначе сторож ослеп и не сказал об этом)."""
    rep = fi.build_inventory(now=now_utc(), registry_max_age_hours=48.0)
    for key in ("manifest", "plist_labels", "wrappers", "registry"):
        assert isinstance(rep["counts"][key], int), (key, rep["sources"])
    assert rep["status"] in ("OK", "UNCHECKED", "DRIFT")
    assert set(rep["findings"]) == set(fi.HARD_CLASSES) | set(fi.SOFT_CLASSES)


EXIT = {"OK": 0, "UNCHECKED": 1, "DRIFT": 2}


def test_exit_codes_distinguish_drift_from_unchecked(tmp_path, monkeypatch):
    """Три исхода — три разных кода: «сошлось», «не смогли проверить», «расхождение».

    Слить UNCHECKED с OK — ровно та подмена, из-за которой отсутствие наблюдения
    шесть раз выдавалось за успех.
    """
    monkeypatch.setattr(fi, "retired_labels", lambda: set())
    root = _consistent(tmp_path)
    assert EXIT[_run(root)["status"]] == 0
    (root / "data" / "agent_registry.json").unlink()          # ослепли на один источник
    assert EXIT[_run(root)["status"]] == 1
    (root / "scripts" / "com.spa.stray.plist").write_text("<plist/>")  # плюс жёсткий класс
    assert EXIT[_run(root)["status"]] == 2                    # расхождение важнее слепоты
