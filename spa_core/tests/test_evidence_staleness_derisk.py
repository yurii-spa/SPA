# FROZEN-DATE-OK: injected-clock — единственный якорь времени это NOW, он передаётся
# в decide(now=)/stage_for(now=), а все отметки ВЫЧИСЛЯЮТСЯ из него (NOW - timedelta).
# Обе стороны закреплены одним значением, календарь на вердикт не влияет.
"""Де-риск по слепоте: ADR-167, приёмка предписана самим решением.

# LLM_FORBIDDEN

Решение владельца требовало двух вещей, и обе здесь:

1. **положительный контроль** — тест, воспроизводящий сценарий «наблюдение старше
   168 ч при живой позиции» и краснеющий на коде БЕЗ де-риск-канала;
2. **отдельная проверка**, что массовая слепота эвакуацию НЕ запускает.

Второе не паранойя: 2026-08-04 одна сетевая икота обнулила `live_apy` у 34
адаптеров сразу. Канал, не отличающий смерть протокола от собственной поломки,
в такой день продал бы всю книгу.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from spa_core.governance import evidence_staleness as es
from spa_core.governance.evidence_staleness import (
    ACTION_DERISK,
    ACTION_MASS_BLINDNESS,
    ACTION_NONE,
    FRESH,
    HARD_STALE,
    SOFT_STALE,
    UNKNOWN_AGE,
    decide,
    stage_for,
)

NOW = datetime(2030, 3, 1, 12, 0, tzinfo=timezone.utc)


def _ago(hours: float) -> str:
    return (NOW - timedelta(hours=hours)).isoformat()


# ── лестница ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("hours,expect", [
    (0, FRESH), (35.9, FRESH), (36.0, FRESH),
    (36.1, SOFT_STALE), (100, SOFT_STALE), (168.0, SOFT_STALE),
    (168.1, HARD_STALE), (1000, HARD_STALE),
])
def test_the_ladder_boundaries_are_where_the_adr_says(hours, expect):
    assert stage_for(_ago(hours), NOW)[0] == expect


def test_soft_window_mirrors_the_allocator_it_is_not_a_fourth_copy():
    """36 ч живёт в аллокаторе; здесь обязана быть ТА ЖЕ цифра, а не своя."""
    from spa_core.allocator import allocator as alloc
    assert es.SOFT_STALE_H == alloc._EVIDENCE_MAX_AGE_H


def test_hard_window_is_the_owner_decision():
    assert es.HARD_STALE_H == 168.0


# ── положительный контроль, предписанный ADR-167 ─────────────────────────
def test_a_held_position_blind_for_more_than_a_week_is_derisked():
    """Сценарий решения владельца дословно: деньги стоят там, где мы слепы."""
    d = decide({"blind_pool": 20_000.0, "seen_pool": 30_000.0},
               {"blind_pool": _ago(200), "seen_pool": _ago(1)}, now=NOW)
    assert d.action == ACTION_DERISK
    assert [x.protocol for x in d.to_derisk] == ["blind_pool"]
    assert d.to_derisk[0].held_usd == 20_000.0
    assert "168" in d.to_derisk[0].reason and "ADR-167" in d.to_derisk[0].reason


def test_the_same_book_before_the_channel_existed_would_say_nothing():
    """Смысл контроля: до ADR-167 та же книга не давала НИ ОДНОГО сигнала.

    Проверяется поведением, а не отсутствием кода: с бесконечным жёстким окном
    (как было до решения) канал молчит на той же самой книге.
    """
    book = ({"blind_pool": 20_000.0, "seen_pool": 30_000.0},
            {"blind_pool": _ago(200), "seen_pool": _ago(1)})
    assert decide(*book, now=NOW).action == ACTION_DERISK
    assert decide(*book, now=NOW, hard_h=float("inf")).action == ACTION_NONE


def test_soft_stale_alone_never_touches_held_money():
    """Между 36 и 168 ч держимое НЕ трогаем — это разные ступени."""
    d = decide({"p": 10_000.0, "q": 10_000.0},
               {"p": _ago(100), "q": _ago(1)}, now=NOW)
    assert d.action == ACTION_NONE and d.to_derisk == []
    assert [x.stage for x in d.all_protocols] == [SOFT_STALE, FRESH]


# ── массовая слепота: тревога, а не эвакуация ────────────────────────────
def test_mass_blindness_does_not_evacuate_the_book():
    """Авария 2026-08-04 в лицах: икота обнулила наблюдение у ВСЕХ сразу."""
    d = decide({"a": 10_000.0, "b": 20_000.0, "c": 30_000.0},
               {"a": _ago(200), "b": _ago(300), "c": _ago(400)}, now=NOW)
    assert d.action == ACTION_MASS_BLINDNESS
    assert d.to_derisk == [], "книга не эвакуируется по НАШЕЙ поломке"
    assert "поломки" in d.reason


def test_one_fresh_protocol_is_enough_to_keep_the_channel_working():
    """Граница: пока хоть один виден, слепота не «массовая», и де-риск идёт."""
    d = decide({"a": 10_000.0, "b": 20_000.0, "c": 30_000.0},
               {"a": _ago(200), "b": _ago(300), "c": _ago(1)}, now=NOW)
    assert d.action == ACTION_DERISK
    assert sorted(x.protocol for x in d.to_derisk) == ["a", "b"]


def test_a_single_blind_position_is_not_mass_blindness():
    """Одна позиция в книге и она слепа — это не поломка фида, это де-риск."""
    d = decide({"only": 50_000.0}, {"only": _ago(500)}, now=NOW)
    assert d.action == ACTION_DERISK and len(d.to_derisk) == 1


# ── fail-CLOSED и края ───────────────────────────────────────────────────
def test_unknown_age_never_becomes_fresh_and_never_derisks():
    """Молчание о времени — не свежесть, но и не основание сокращать."""
    for bad in (None, "", "вчера", 12345):
        stage, _, why = stage_for(bad, NOW)
        assert stage == UNKNOWN_AGE, bad
        assert why
    d = decide({"p": 1_000.0}, {"p": "вчера"}, now=NOW)
    assert d.action == ACTION_NONE and d.to_derisk == []


def test_timestamp_from_the_future_is_unknown_not_fresh():
    stage, _, why = stage_for((NOW + timedelta(hours=5)).isoformat(), NOW)
    assert stage == UNKNOWN_AGE and "будущего" in why


def test_no_holdings_means_nothing_to_reduce():
    d = decide({}, {}, now=NOW)
    assert d.action == ACTION_NONE and "нечего" in d.reason


def test_zero_and_negative_holdings_are_not_positions():
    d = decide({"a": 0.0, "b": -5.0, "c": True}, {"a": _ago(500)}, now=NOW)
    assert d.action == ACTION_NONE and d.all_protocols == []


def test_decision_serialises_with_every_number_behind_it():
    d = decide({"a": 1_000.0}, {"a": _ago(500)}, now=NOW).to_dict()
    assert d["action"] == ACTION_DERISK and d["generated_at"] == NOW.isoformat()
    row = d["to_derisk"][0]
    assert {"protocol", "stage", "age_hours", "held_usd", "reason"} <= set(row)
    assert row["age_hours"] == pytest.approx(500.0)


def test_module_moves_no_money_itself():
    """ADR-167: сокращение — штатным ребалансом, не forced-sell отсюда."""
    import ast
    from pathlib import Path
    tree = ast.parse(Path(es.__file__).read_text(encoding="utf-8"))
    modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not [m for m in modules if m.startswith("spa_core.execution")]
    assert "# LLM_FORBIDDEN" in Path(es.__file__).read_text(encoding="utf-8")
