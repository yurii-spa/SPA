"""Экономика цеха ПОДКЛЮЧЕНА и цена приходит из настройки владельца (ADR-276, ADR-285).

До 2026-09-09 модуль `fleet_economics` не был вызван ниоткуда: артефакта в проде не было,
и дневной отчёт честно писал «стоимость не оценена». Владелец назвал число (230 $/мес, тариф
Max; замер git-истории: 102 уникальных цикла за 30 дней ⇒ 2.25 $ за цикл) и по границе решений
ADR-285 подключение стало делом агента.

Проверяется ПРОВОДКА, а не намерение: что ежечасный агент действительно пишет артефакт, что
цена берётся из синхронизируемой в прод настройки, и что отставшее дерево по-прежнему даёт
«не измерено», а не ложный ноль.
"""
from __future__ import annotations

import json
from pathlib import Path

from spa_core.monitoring import agent_health_monitor as ahm
from spa_core.monitoring import fleet_economics as fe

_ROOT = Path(__file__).resolve().parents[2]


# ── цена: настройка владельца, синхронизируемая в прод ────────────────────────────────
def test_the_owner_price_lives_in_a_file_that_reaches_prod():
    """`architecture/` возится в прод (решение владельца 09.08); `data/` — нет."""
    p = _ROOT / "architecture" / "owner_settings.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert doc["cost_per_cycle_usd"] == 2.25
    assert "230" in doc["cost_per_cycle_provenance"] and "102" in doc["cost_per_cycle_provenance"]


def test_price_comes_from_the_settings_file_when_the_env_is_absent(tmp_path, monkeypatch):
    monkeypatch.delenv("SPA_COST_PER_CYCLE_USD", raising=False)
    s = tmp_path / "owner_settings.json"
    s.write_text(json.dumps({"cost_per_cycle_usd": 3.5}), encoding="utf-8")
    assert fe._cost_per_cycle_raw(s) == "3.5"


def test_the_env_overrides_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv("SPA_COST_PER_CYCLE_USD", "9.99")
    s = tmp_path / "owner_settings.json"
    s.write_text(json.dumps({"cost_per_cycle_usd": 3.5}), encoding="utf-8")
    assert fe._cost_per_cycle_raw(s) == "9.99"


def test_a_missing_or_broken_settings_file_leaves_the_cost_unestimated(tmp_path, monkeypatch):
    """Третий исход сохранён: нет числа ⇒ «не оценена», а не ноль."""
    monkeypatch.delenv("SPA_COST_PER_CYCLE_USD", raising=False)
    assert fe._cost_per_cycle_raw(tmp_path / "nope.json") == ""
    bad = tmp_path / "bad.json"; bad.write_text("{not json", encoding="utf-8")
    assert fe._cost_per_cycle_raw(bad) == ""
    nonnum = tmp_path / "nn.json"; nonnum.write_text(json.dumps({"cost_per_cycle_usd": "дорого"}), encoding="utf-8")
    assert fe._cost_per_cycle_raw(nonnum) == ""


# ── проводка: ежечасный агент пишет артефакт ──────────────────────────────────────────
def test_the_hourly_agent_declares_the_artifact():
    assert "data/fleet_economics.json" in ahm.PRODUCES


def test_the_hourly_agent_actually_writes_it(tmp_path):
    ahm._write_fleet_economics(tmp_path)
    doc = json.loads((tmp_path / "fleet_economics.json").read_text(encoding="utf-8"))
    for key in ("measured", "cycles", "commits", "cost_per_cycle_usd", "cost_estimate_usd",
                "repo_root", "head_age_hours", "window_hours"):
        assert key in doc, key


def test_the_side_car_never_breaks_the_monitor(tmp_path, monkeypatch):
    """Пульс флота важнее строки о стоимости: падение экономики не имеет права его ронять."""
    import spa_core.monitoring.fleet_economics as _fe
    def boom(*_a, **_k):
        raise RuntimeError("диск полон")
    monkeypatch.setattr(_fe, "write_artifact", boom)
    ahm._write_fleet_economics(tmp_path)          # не должно бросить
    assert not (tmp_path / "fleet_economics.json").exists()


def test_the_measuring_tree_is_not_the_prod_tree():
    """ADR-276: мерить по прод-дереву нельзя — суточное окно там пусто ПО ПОСТРОЕНИЮ."""
    assert ahm._ECONOMICS_TREE != _ROOT
    assert ahm._ECONOMICS_TREE.name == "SPA_mirror"


def test_a_stale_tree_still_reports_not_measured(tmp_path):
    """Контроль обратного направления: если мерить отставшим деревом — «не измерено», не ноль."""
    r = fe.summary(tmp_path, subjects_fn=lambda *_a, **_k: [], head_age_fn=lambda *_a, **_k: 255.4)
    assert r["measured"] is False and r["cycles"] is None
    assert "ПО ПОСТРОЕНИЮ" in r["unmeasured_reason"]
