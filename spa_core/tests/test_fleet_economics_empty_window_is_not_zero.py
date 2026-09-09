"""Пустое окно ≠ ноль работы: экономика цеха не имеет права рапортовать ложный ноль (ADR-276).

Замер 2026-09-09. Модуль `spa_core/monitoring/fleet_economics.py` два месяца не был подключён
ни к одному plist/обёртке — его артефакта в проде нет вовсе. Подключить его «как есть» значило
бы завести новый ЛОЖНЫЙ артефакт: в прод-дереве `git log --since=24.hours` возвращает ПУСТОЙ
СПИСОК (не ошибку), потому что пуши уходят на origin через API и локальный индекс отстаёт —
HEAD прода был от 29.08, то есть на 255 часов. В зеркале за те же сутки 44 коммита, 6 циклов.

Часы здесь инъектированы: возраст HEAD и темы коммитов приходят параметрами.
# FROZEN-DATE-OK: injected-clock — `summary(now=…)` плюс `head_age_fn`/`subjects_fn` параметрами;
# стенных часов в тесте нет, литеральные даты — только как метки инцидента в прозе.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from spa_core.monitoring import fleet_economics as fe

NOW = datetime(2030, 5, 1, 12, 0, tzinfo=timezone.utc)
ROOT = Path("/nonexistent/tree")


def _s(subjects, age):
    return fe.summary(ROOT, now=NOW,
                      subjects_fn=lambda *_a, **_k: subjects,
                      head_age_fn=lambda *_a, **_k: age)


def test_a_stale_tree_reports_not_measured_instead_of_zero():
    """Тот самый случай прода: окно пусто, а HEAD старше окна ⇒ измерения НЕ было."""
    r = _s([], 255.4)
    assert r["measured"] is False
    assert r["cycles"] is None and r["commits"] is None
    assert "ПО ПОСТРОЕНИЮ" in r["unmeasured_reason"]
    assert r["head_age_hours"] == 255.4


def test_a_fresh_tree_with_a_genuinely_quiet_day_reports_a_real_zero():
    """Обратный контроль: свежее дерево и пустое окно — это НАСТОЯЩИЙ ноль, и он измерен."""
    r = _s([], 2.0)
    assert r["measured"] is True and r["cycles"] == 0 and r["commits"] == 0


def test_a_fresh_tree_counts_cycles_and_commits():
    r = _s(["orchestrator цикл #531: …", "fix(site): …", "цикл #532 STATE+journal"], 0.5)
    assert r["measured"] is True and r["commits"] == 3 and r["cycles"] == 2


def test_git_unavailable_is_still_not_measured():
    r = _s(None, None)
    assert r["measured"] is False and "git недоступен" in r["unmeasured_reason"]


def test_an_unknown_head_age_is_not_measured_either():
    """Свежесть дерева неизвестна ⇒ пустое окно неотличимо от отстающего индекса."""
    r = _s([], None)
    assert r["measured"] is False and "HEAD" in r["unmeasured_reason"]


def test_a_stale_tree_that_did_commit_inside_the_window_is_still_measured():
    """Ветка отказа стоит на «пусто И старо», а не на возрасте отдельно: непустое окно
    измерено даже у дерева, чей HEAD формально старше (часовые пояса, правки истории)."""
    r = _s(["цикл #500: …"], 100.0)
    assert r["measured"] is True and r["cycles"] == 1


def test_cost_stays_unestimated_without_the_owner_env(monkeypatch):
    monkeypatch.delenv("SPA_COST_PER_CYCLE_USD", raising=False)
    r = _s(["цикл #1"], 1.0)
    assert r["cost_estimate_usd"] is None and "стоимость не оценена" in r["note"]


def test_cost_is_estimated_when_the_owner_set_the_price(monkeypatch):
    monkeypatch.setenv("SPA_COST_PER_CYCLE_USD", "2.5")
    r = _s(["цикл #1", "цикл #2"], 1.0)
    assert r["cost_per_cycle_usd"] == 2.5 and r["cost_estimate_usd"] == 5.0
