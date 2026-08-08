#!/usr/bin/env python3
"""Карточка owner-gate обязана нести ВАРИАНТЫ, а не прозу.

Замер (день инцидента, журнал W32): владельцу пришло «Сайт: автономная правка задела
owner-gated область» БЕЗ единой кнопки и с советом «открой её в трекере» — из телефона
неисполнимым. Причина не в доставке: генератор писал «одобрить или отклонить» прозой, а
разбор (ADR-075) читает ПРОНУМЕРОВАННЫЙ перечень.

Эта карточка машинная и повторяется при каждой owner-gated правке сайта, поэтому её форма —
не косметика: без вариантов владелец не может ответить тем способом, ради которого всё
строилось.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from spa_core.telegram.owner_decisions import parse_options

_REPO = Path(__file__).resolve().parents[2]


@pytest.fixture()
def ssp():
    path = _REPO / "scripts" / "safe_site_push.py"
    spec = importlib.util.spec_from_file_location("safe_site_push_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _body(ssp, monkeypatch) -> str:
    """Тело карточки, как его строит настоящий генератор. Карточку НЕ создаём и не шлём."""
    captured = {}

    def fake_create_card(**kw):
        captured.update(kw)
        return _REPO / "nimbalyst-local" / "tracker" / "own-test.md"

    monkeypatch.setattr("spa_core.owner_queue.queue.create_card", fake_create_card)
    monkeypatch.setattr("spa_core.owner_queue.notify.notify_needs_owner",
                        lambda *a, **k: "")
    ssp._route_to_owner_card(
        ["landing/src/pages/packages.astro"],
        {"violations": [{"klass": "E", "file": "landing/x.astro",
                         "rule": "honesty.token.removed", "matched_text": "RESEARCH"}]},
        "packages: правка статусов",
    )
    assert captured, "генератор обязан был создать карточку"
    return captured["body"]


def test_the_card_offers_numbered_options(ssp, monkeypatch):
    """Положительный контроль аварии: без нумерованных вариантов кнопок не будет."""
    options = parse_options(_body(ssp, monkeypatch))
    assert [o.num for o in options] == ["1", "2", "3"]
    labels = [o.label.lower() for o in options]
    assert "одобрить" in labels[0]
    assert "отклонить" in labels[1]


def test_the_safe_option_is_the_recommended_one(ssp, monkeypatch):
    """Рекомендация ведёт к ОТКАЗУ, а не к публикации.

    Инвариант #8: owner-gated поверхность (числа доходности, нейминг тиров, legal,
    solicitation) не уезжает в live без осознанного решения. Рекомендовать «одобрить»
    значило бы одним тапом с телефона отправлять в публичный доступ то, ради чего гейт
    и существует.
    """
    options = parse_options(_body(ssp, monkeypatch))
    recommended = [o for o in options if o.recommended]
    assert len(recommended) == 1
    assert "отклонить" in recommended[0].label.lower()


def test_the_flagged_details_survive_next_to_the_options(ssp, monkeypatch):
    """Варианты не должны вытеснить факты: что за файл и что зафлагано — на месте."""
    body = _body(ssp, monkeypatch)
    assert "packages.astro" in body
    assert "honesty.token.removed" in body


# ── повтор попытки не должен плодить карточки и сообщения ────────────────────


def test_the_same_violations_do_not_create_a_second_card(ssp, monkeypatch, tmp_path):
    """Положительный контроль потока (замер 08.08): оркестратор повторяет попытку пуша, и
    КАЖДЫЙ упор в owner-gate заводил новую карточку и слал новое сообщение — три карточки
    за 40 минут и поток одинаковых уведомлений владельцу.

    Отпечаток набора нарушений делает повтор молчаливым. Это дедуп, а НЕ подавление:
    owner-gate по-прежнему не пускает правку в live, решение владельца по-прежнему ждут.
    """
    created, notified = [], []
    store = {}

    def fake_create(**kw):
        path = tmp_path / f"own-{len(created)}.md"
        path.write_text(kw["body"], encoding="utf-8")
        store[path] = kw["body"]
        created.append(path)
        return path

    class FakeCard:
        def __init__(self, path, body):
            self.path, self.body = path, body

    monkeypatch.setattr("spa_core.owner_queue.queue.create_card", fake_create)
    monkeypatch.setattr("spa_core.owner_queue.queue.list_cards",
                        lambda **kw: [FakeCard(p, b) for p, b in store.items()])
    monkeypatch.setattr(ssp.subprocess, "run",
                        lambda *a, **k: notified.append(a) or None)

    report = {"violations": [{"klass": "E", "file": "landing/x.astro",
                              "rule": "honesty.token.removed", "matched_text": "RESEARCH"}]}
    for _ in range(3):
        ssp._route_to_owner_card(["landing/x.astro"], report, "правка")

    assert len(created) == 1, "повтор той же блокировки не должен плодить карточки"
    assert len(notified) == 1, "и не должен слать владельцу второе уведомление"


def test_a_different_violation_set_is_a_new_decision(ssp, monkeypatch, tmp_path):
    """Дедуп не имеет права стать глухотой: ДРУГОЕ нарушение — другое решение владельца."""
    created = []
    store = {}

    def fake_create(**kw):
        path = tmp_path / f"own-{len(created)}.md"
        store[path] = kw["body"]
        created.append(path)
        return path

    class FakeCard:
        def __init__(self, path, body):
            self.path, self.body = path, body

    monkeypatch.setattr("spa_core.owner_queue.queue.create_card", fake_create)
    monkeypatch.setattr("spa_core.owner_queue.queue.list_cards",
                        lambda **kw: [FakeCard(p, b) for p, b in store.items()])
    monkeypatch.setattr(ssp.subprocess, "run", lambda *a, **k: None)

    ssp._route_to_owner_card(["a.astro"], {"violations": [
        {"klass": "E", "file": "a.astro", "rule": "honesty.token.removed"}]}, "m")
    ssp._route_to_owner_card(["b.astro"], {"violations": [
        {"klass": "E", "file": "b.astro", "rule": "apy.number.changed"}]}, "m")

    assert len(created) == 2


def test_fingerprint_ignores_order_and_matched_text(ssp):
    """Тот же набор нарушений в другом порядке — та же карточка, а не «новый инцидент».

    `matched_text` тоже не участвует: он меняется от правки к правке внутри одной и той же
    owner-gated области, а решение владельцу нужно одно.
    """
    a = ssp._violations_fingerprint([
        {"file": "a", "rule": "r1", "matched_text": "первый текст"},
        {"file": "b", "rule": "r2", "matched_text": "второй"}])
    b = ssp._violations_fingerprint([
        {"file": "b", "rule": "r2", "matched_text": "ДРУГОЙ текст"},
        {"file": "a", "rule": "r1", "matched_text": "и тут другой"}])
    assert a == b


def test_a_broken_lookup_creates_the_card_rather_than_swallowing_it(ssp, monkeypatch, tmp_path):
    """Fail-CLOSED в сторону ВЛАДЕЛЬЦА: сбой поиска дубля не имеет права подавить карточку.

    Лишняя карточка — неприятность; потерянное решение владельца — потеря контроля.
    """
    created = []
    monkeypatch.setattr("spa_core.owner_queue.queue.create_card",
                        lambda **kw: created.append(kw) or (tmp_path / "own.md"))
    monkeypatch.setattr("spa_core.owner_queue.queue.list_cards",
                        lambda **kw: (_ for _ in ()).throw(RuntimeError("трекер недоступен")))
    monkeypatch.setattr(ssp.subprocess, "run", lambda *a, **k: None)
    ssp._route_to_owner_card(["a.astro"], {"violations": [{"file": "a", "rule": "r"}]}, "m")
    assert len(created) == 1
