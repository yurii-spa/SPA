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
