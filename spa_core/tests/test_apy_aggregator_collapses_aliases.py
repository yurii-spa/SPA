"""Один протокол — одна строка ранжирования, даже если у него два написания.

# LLM_FORBIDDEN

Секции 2–4 в `APYAggregator.load` кладут строку под СВОИМ написанием ключа
(`morpho-blue-steakhouse`, `aave-v3-arbitrum`, `pendle-pt`), а те же протоколы
уже пришли из `adapters` под каноническими именами. Дедуп сравнивал сырые строки
и пару не схлопывал: 33 строки при 30 протоколах.

**Почему это не косметика (замер 2026-08-29).** `by_apy` читают ТРИ потребителя —
`risk_budget`, `capital_efficiency`, `_apy_series` — и НИ ОДИН не фильтрует по
провенансу. Дубль `pendle-pt` с литералом **8.0 %** входил в их расчёты вторым
экземпляром протокола, настоящее наблюдение по которому — **4.70 %**.

Предыдущая сессия видела пересечение и осознанно сняла только ложную метку
«наблюдение», отложив схлопывание до замера по потребителям. Замер сделан —
схлопывание доставлено.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spa_core.adapters.apy_aggregator import APYAggregator, _canonical_key
from spa_core.tests._freshness import ts   # отметки — ВОЗРАСТ, а не календарь



@pytest.mark.parametrize("slug,canon", [
    ("pendle-pt", "pendle_pt_susde"),
    ("morpho-blue-steakhouse", "morpho_steakhouse"),
    ("aave-v3-arbitrum", "aave_arbitrum"),
    ("  Pendle-PT  ", "pendle_pt_susde"),
])
def test_slug_resolves_to_the_canonical_registry_key(slug, canon):
    assert _canonical_key(slug) == canon


@pytest.mark.parametrize("name", ["aave_v3", "compound_v3", "неизвестный_протокол", ""])
def test_a_name_that_is_not_an_alias_passes_through(name):
    """Резолвер не выдумывает соответствий — только те, что в таблице."""
    assert _canonical_key(name) == name


def test_the_pair_collapses_and_the_observed_row_survives(tmp_path):
    """Положительный контроль: ровно форма аварии — слаг рядом с каноном."""
    (tmp_path / "adapter_status.json").write_text(json.dumps({
        "generated_at": ts(hours_ago=1),
        "adapters": {
            "pendle_pt_susde": {"apy": 4.70, "live_apy": 4.70, "tier": 2, "active": True},
            "aave_v3": {"apy": 5.0, "live_apy": 5.0, "tier": 1, "active": True},
        },
        # legacy-блок того же протокола под ДРУГИМ написанием и с ЛИТЕРАЛОМ
        "pendle_pt": {"protocol_key": "pendle-pt", "apy": 8.0, "tier": "T2"},
    }), encoding="utf-8")

    names = [s.protocol for s in APYAggregator.load(tmp_path).rank_by_apy()]
    assert "pendle-pt" not in names, "слаг обязан схлопнуться в канонический ключ"
    assert names.count("pendle_pt_susde") == 1, "протокол не может стоять дважды"
    assert len(names) == len(set(names)), "в ранжировании остались дубли"

    apys = {s.protocol: s.apy_pct for s in APYAggregator.load(tmp_path).rank_by_apy()}
    assert apys["pendle_pt_susde"] == pytest.approx(4.70), (
        "выжило литеральное 8.0 % вместо наблюдённого 4.70 — сортировка по "
        "доходности снова поставит выдумку выше правды")


def test_legacy_block_still_lands_when_there_is_no_canonical_row(tmp_path):
    """Обратный контроль: схлопывание не должно ГЛОТАТЬ протокол целиком."""
    (tmp_path / "adapter_status.json").write_text(json.dumps({
        "generated_at": ts(hours_ago=1),
        "adapters": {"aave_v3": {"apy": 5.0, "live_apy": 5.0, "tier": 1, "active": True}},
        "pendle_pt": {"protocol_key": "pendle-pt", "apy": 8.0, "tier": "T2"},
    }), encoding="utf-8")
    names = [s.protocol for s in APYAggregator.load(tmp_path).rank_by_apy()]
    assert "pendle_pt_susde" in names, "единственная строка протокола потеряна"
    assert "pendle-pt" not in names, "и она обязана быть под каноническим ключом"


def test_unrelated_protocols_are_untouched(tmp_path):
    (tmp_path / "adapter_status.json").write_text(json.dumps({
        "generated_at": ts(hours_ago=1),
        "adapters": {
            "aave_v3": {"apy": 5.0, "live_apy": 5.0, "tier": 1, "active": True},
            "compound_v3": {"apy": 4.0, "live_apy": 4.0, "tier": 1, "active": True},
        },
    }), encoding="utf-8")
    names = sorted(s.protocol for s in APYAggregator.load(tmp_path).rank_by_apy())
    assert names == ["aave_v3", "compound_v3"]


def test_resolver_survives_an_unavailable_alias_table(monkeypatch):
    """Fail-safe: карта недоступна ⇒ имя как есть, а не падение агрегатора."""
    import builtins
    real = builtins.__import__

    def boom(name, *a, **kw):
        if name == "spa_core.adapters.tier_map":
            raise ImportError("нет карты")
        return real(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", boom)
    assert _canonical_key("pendle-pt") == "pendle-pt"
