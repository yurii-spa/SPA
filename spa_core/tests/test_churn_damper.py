# FROZEN-DATE-OK: injected-clock — единственный якорь времени это NOW, он передаётся
# в decide(now=), а отметки сделок ВЫЧИСЛЯЮТСЯ из него. Обе стороны закреплены.
"""Ограничитель перекладок: держит частоту, но НИКОГДА не держит де-риск.

# LLM_FORBIDDEN

ADR-168 (решение владельца 29.08). Замер, из которого решение выросло:
22 перекладки за 7 дней, оборот 5.3 капитала, издержки $1 288/нед при
недельном заработке книги $87.

Половина набора сторожит не ограничение, а ИСКЛЮЧЕНИЕ из него: ход, который
только сокращает позиции, обязан проходить всегда. «Бюджет оборота исчерпан»
не может стать причиной не уйти из риска — иначе ограничитель издержек
превратится в запрет на безопасность.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from spa_core.governance import churn_damper as cd
from spa_core.governance.churn_damper import (
    ALLOW,
    BLOCK,
    REASON_DERISK,
    REASON_MIN_HOLD,
    REASON_UNMEASURABLE,
    REASON_WEEK_BUDGET,
    decide,
    is_pure_reduction,
    one_sided_turnover,
)

NOW = datetime(2030, 5, 1, 12, 0, tzinfo=timezone.utc)
CAP = 100_000.0


def _trade(hours_ago: float, delta_abs: float) -> dict:
    return {"ts": (NOW - timedelta(hours=hours_ago)).isoformat(), "delta_abs": delta_abs}


# ── исключение, ради которого половина файла ─────────────────────────────
def test_a_pure_reduction_is_never_delayed():
    """Де-риск проходит, даже когда нарушены ОБА ограничения сразу."""
    trades = [_trade(1, 90_000.0)] * 3          # и срок, и бюджет исчерпаны
    v = decide({"a": 60_000.0, "b": 40_000.0}, {"a": 20_000.0, "b": 0.0},
               trades, CAP, now=NOW)
    assert v.decision == ALLOW and v.reason == REASON_DERISK
    assert v.is_pure_reduction is True


def test_going_all_to_cash_is_a_pure_reduction():
    v = decide({"a": 50_000.0}, {}, [_trade(0.5, 99_000.0)], CAP, now=NOW)
    assert v.decision == ALLOW and v.reason == REASON_DERISK


@pytest.mark.parametrize("cur,tgt,expect", [
    ({"a": 100.0}, {"a": 50.0}, True),                      # сокращение
    ({"a": 100.0}, {"a": 100.0}, True),                     # без изменений
    ({"a": 100.0}, {"a": 150.0}, False),                    # рост
    ({"a": 100.0}, {"a": 50.0, "b": 50.0}, False),          # перекладка
    ({"a": 100.0}, {}, True),                               # выход в кэш
    ({}, {"a": 100.0}, False),                              # новая позиция
])
def test_pure_reduction_is_recognised(cur, tgt, expect):
    assert is_pure_reduction(cur, tgt) is expect


# ── сами ограничения ─────────────────────────────────────────────────────
def test_min_hold_blocks_a_fresh_reshuffle():
    v = decide({"a": 50_000.0, "b": 50_000.0}, {"a": 10_000.0, "b": 90_000.0},
               [_trade(2, 40_000.0)], CAP, now=NOW)
    assert v.decision == BLOCK and v.reason == REASON_MIN_HOLD
    assert "2.0 ч" in v.detail and "72 ч" in v.detail


def test_after_the_hold_expires_the_move_passes():
    v = decide({"a": 50_000.0, "b": 50_000.0}, {"a": 45_000.0, "b": 55_000.0},
               [_trade(80, 5_000.0)], CAP, now=NOW)
    assert v.decision == ALLOW, v.detail


def test_weekly_budget_blocks_even_after_the_hold():
    """Срок выдержан, но недельный бюджет уже исчерпан."""
    trades = [_trade(80, 24_000.0)]              # 24 % капитала за неделю
    v = decide({"a": 50_000.0, "b": 50_000.0}, {"a": 40_000.0, "b": 60_000.0},
               trades, CAP, now=NOW)
    assert v.decision == BLOCK and v.reason == REASON_WEEK_BUDGET
    assert "бюджет" in v.detail


def test_turnover_older_than_a_week_does_not_count():
    v = decide({"a": 50_000.0, "b": 50_000.0}, {"a": 45_000.0, "b": 55_000.0},
               [_trade(24 * 9, 90_000.0), _trade(80, 1_000.0)], CAP, now=NOW)
    assert v.decision == ALLOW, v.detail


def test_first_ever_move_has_no_history_and_passes():
    v = decide({}, {"a": 10_000.0}, [], CAP, now=NOW)
    assert v.decision == ALLOW and v.hours_since_last is None


# ── оборот считается односторонним ───────────────────────────────────────
def test_turnover_is_one_sided_not_gross_halved():
    """Развёртывание кэша не имеет продающей ноги: брутто/2 занизило бы вдвое."""
    assert one_sided_turnover({}, {"a": 30_000.0}) == pytest.approx(30_000.0)
    assert one_sided_turnover({"a": 50_000.0, "b": 0.0},
                              {"a": 20_000.0, "b": 30_000.0}) == pytest.approx(30_000.0)


# ── пороги не заводятся здесь заново ─────────────────────────────────────
def test_thresholds_come_from_the_adr_column_not_a_local_copy():
    from spa_core.allocator.rebalance_economics import TriggerParams
    p = TriggerParams.for_mode("paper")
    v = decide({"a": 50_000.0, "b": 50_000.0}, {"a": 40_000.0, "b": 60_000.0},
               [_trade(1, 1.0)], CAP, now=NOW)
    assert v.min_hold_hours == pytest.approx(p.min_hold_days * 24)
    assert v.week_budget_usd == pytest.approx(p.max_turnover_per_week * CAP)


def test_pilot_mode_is_stricter_than_paper():
    from spa_core.allocator.rebalance_economics import TriggerParams
    paper = decide({"a": 1.0}, {"a": 1.0, "b": 1.0}, [], CAP, now=NOW,
                   params=TriggerParams.for_mode("paper"))
    pilot = decide({"a": 1.0}, {"a": 1.0, "b": 1.0}, [], CAP, now=NOW,
                   params=TriggerParams.for_mode("pilot"))
    assert pilot.min_hold_hours > paper.min_hold_hours
    assert pilot.week_budget_usd < paper.week_budget_usd


# ── fail-safe ────────────────────────────────────────────────────────────
def test_an_unusable_input_allows_rather_than_freezes_the_book():
    """Ограничитель — не гейт безопасности: не смог решить ⇒ пропускает."""
    v = decide({"a": 1.0}, {"b": 1.0}, [], CAP, now=NOW, params=object())
    assert v.decision == ALLOW and v.reason == REASON_UNMEASURABLE


def test_malformed_trade_rows_do_not_break_the_verdict():
    v = decide({"a": 50_000.0}, {"a": 40_000.0, "b": 10_000.0},
               ["мусор", None, {"ts": "вчера"}, {"delta_abs": 5}], CAP, now=NOW)
    assert v.decision in (ALLOW, BLOCK) and v.detail


# ── положительный контроль: реальная неделя ──────────────────────────────
def test_the_real_week_would_have_been_cut_to_a_couple_of_moves():
    """22 перекладки 23–29.08 прогоняются через ограничитель по очереди.

    Форма недели воспроизведена по журналу сделок: суммы и промежутки те же
    по порядку величины. Ожидание — единицы ходов вместо двух десятков.
    """
    gaps_and_sizes = [
        (0, 55_000), (1.9, 40_000), (6.2, 40_000), (27.8, 5_000), (33.3, 2_105),
        (0.4, 3_947), (4.0, 40_000), (1.2, 40_000), (8.6, 25_000), (4.1, 3_947),
        (1.0, 7_105), (0.7, 7_105), (7.3, 27_895), (1.0, 42_105), (6.7, 40_000),
        (10.1, 2_105), (6.1, 3_947), (2.8, 40_000), (3.4, 22_105), (1.6, 37_895),
        (5.5, 30_921), (2.7, 14_342),
    ]
    trades: list = []
    clock = NOW - timedelta(days=7)
    passed = 0
    for gap_h, size in gaps_and_sizes:
        clock += timedelta(hours=gap_h)
        cur = {"a": 60_000.0, "b": 40_000.0}
        tgt = {"a": 60_000.0 - size / 2, "b": 40_000.0 + size / 2}   # перекладка, не сокращение
        v = decide(cur, tgt, list(trades), CAP, now=clock)
        if v.allowed:
            passed += 1
            trades.append({"ts": clock.isoformat(), "delta_abs": float(size)})
    assert passed <= 4, f"ограничитель пропустил {passed} из 22 — слишком мягко"
    assert passed >= 1, "ограничитель не пропустил НИ ОДНОГО хода — слишком жёстко"


# --- Первичное размещение (найдено прогоном цикла 29.08) ---------------------
#
# Первая редакция ограничителя душила ВВОД капитала в работу: $74 000 из кэша в
# пустую книгу не проходили недельный бюджет $25 000. Перекладкой это не было —
# перекладывать было нечего. Дефект нашёлся не рассуждением, а тем, что семь
# тестов цикла покраснели; правился модуль, а не тесты.


def test_first_deployment_from_cash_is_not_churn():
    v = decide({}, {"aave_v3": 74000.0}, [], 100000.0, now=NOW)
    assert v.allowed
    assert v.reason == cd.REASON_INITIAL


def test_the_exemption_does_not_reopen_the_flip_flop():
    """Продал вчера — откупаю сегодня: книга пуста, но оборот записан."""
    sold_yesterday = [_trade(hours_ago=24.0, delta_abs=40000.0)]
    v = decide({}, {"aave_v3": 40000.0}, sold_yesterday, 100000.0, now=NOW)
    assert not v.allowed, (
        "возврат в риск на следующий день после выхода — это вторая нога "
        "маятника, а не первичное размещение")


def test_a_non_empty_book_is_never_initial_deployment():
    v = decide({"aave_v3": 60000.0}, {"aave_v3": 20000.0, "maple": 74000.0},
               [], 100000.0, now=NOW)
    assert v.reason != cd.REASON_INITIAL
