#!/usr/bin/env python3
"""7-дневный чекпойнт: об одном и том же он обязан сказать ОДИН раз.

Замер (день инцидента, подробности в журнале W32): владелец получил ТРИ одинаковых сообщения
за шесть минут, каждое — про одну и ту же дыру в треке, известную ещё с июня.
Причина: отправка шла прямо в транспорт и не помнила, что уже говорила.

Это не косметика. На шум перестают смотреть, и следующая НАСТОЯЩАЯ поломка проезжает
незамеченной — тот же механизм, из-за которого сегодня трое суток никто не видел мёртвых
кнопок. Поэтому здесь пиннится:

* повтор ТОГО ЖЕ набора провалов — молчит (дедуп, а не подавление: ни одна проверка не
  ослаблена, изменился только повтор);
* ДРУГОЙ набор провалов — звучит (иначе дедуп превратился бы в глухоту);
* возврат к норме объявляется отдельно (`resolve`) — без выхода следующий провал был бы
  беззвучным «всё ещё плохо», ровно дефект ADR-070 п.4;
* отправка идёт через ЕДИНСТВЕННЫЙ авторитет, а не мимо него.

Сети здесь нет: `push_policy` подменяется.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]


def _load_script():
    """Загрузить `scripts/checkpoint_7day.py` как модуль (он не пакет)."""
    path = _REPO / "scripts" / "checkpoint_7day.py"
    spec = importlib.util.spec_from_file_location("checkpoint_7day_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def cp():
    return _load_script()


@pytest.fixture()
def spy(monkeypatch):
    """Подменяем ОБА пути push_policy и записываем, что было вызвано."""
    calls = {"critical": [], "resolve": []}

    def fake_critical(event_key, severity, title, body="", **kw):
        calls["critical"].append({"key": event_key, "severity": severity,
                                  "title": title, **kw})
        return True

    def fake_resolve(event_key, title, body="", **kw):
        calls["resolve"].append({"key": event_key, "title": title})
        return True

    monkeypatch.setattr("spa_core.telegram.push_policy.push_critical", fake_critical)
    monkeypatch.setattr("spa_core.telegram.push_policy.resolve", fake_resolve)
    return calls


def test_failure_goes_through_the_push_authority_with_a_fingerprint(cp, spy):
    """Провал уходит через `push_policy` и несёт отпечаток НАБОРА провалов."""
    # Текст провала для дедупа непрозрачен: сравниваются СТРОКИ, а не даты внутри них.
    failures = ["gap_check: Gap in paper_evidence: <период> (9 days)"]
    assert cp._notify_via_push_policy(False, failures, "текст") is True

    assert not spy["resolve"], "провал не должен объявляться выздоровлением"
    (call,) = spy["critical"]
    assert call["key"] == "checkpoint_failed"
    assert call["dedup_key"], "без отпечатка дедуп съел бы ДРУГУЮ аварию"
    assert "gap_check" in call["dedup_key"]


def test_the_same_failure_set_produces_the_same_fingerprint(cp, spy):
    """Положительный контроль аварии: три запуска с ОДНИМ набором провалов дают один
    отпечаток, и `push_policy` промолчит на втором и третьем — вместо трёх сообщений
    владельцу за шесть минут."""
    # Текст провала для дедупа непрозрачен: сравниваются СТРОКИ, а не даты внутри них.
    failures = ["gap_check: Gap in paper_evidence: <период> (9 days)"]
    for _ in range(3):
        cp._notify_via_push_policy(False, failures, "текст")
    keys = {c["dedup_key"] for c in spy["critical"]}
    assert len(keys) == 1, "один и тот же провал обязан давать ОДИН отпечаток"


def test_a_different_failure_set_is_a_different_incident(cp, spy):
    """Дедуп не имеет права стать глухотой: новый провал обязан звучать."""
    cp._notify_via_push_policy(False, ["gap_check: дыра"], "текст")
    cp._notify_via_push_policy(False, ["gap_check: дыра", "equity_check: расхождение"], "текст")
    keys = [c["dedup_key"] for c in spy["critical"]]
    assert keys[0] != keys[1]


def test_fingerprint_is_order_independent(cp, spy):
    """Порядок провалов в списке не должен превращать ту же аварию в «новую»."""
    cp._notify_via_push_policy(False, ["b: два", "a: один"], "текст")
    cp._notify_via_push_policy(False, ["a: один", "b: два"], "текст")
    keys = [c["dedup_key"] for c in spy["critical"]]
    assert keys[0] == keys[1]


def test_passing_checkpoint_announces_recovery(cp, spy):
    """У тревоги обязан быть ВЫХОД: без него следующий провал уйдёт в тишину."""
    assert cp._notify_via_push_policy(True, [], "текст") is True
    assert not spy["critical"]
    (call,) = spy["resolve"]
    assert call["key"] == "checkpoint_failed"


def test_a_broken_push_authority_never_crashes_the_checkpoint(cp, monkeypatch):
    """Сбой уведомления не имеет права уронить сам чекпойнт — и не притворяется успехом."""
    def boom(*a, **kw):
        raise RuntimeError("канал лёг")

    monkeypatch.setattr("spa_core.telegram.push_policy.push_critical", boom)
    assert cp._notify_via_push_policy(False, ["x: y"], "текст") is False
