"""ADR-972 — ответ владельца 27.10 (ADR-836, вариант А) ИСПОЛНЕН в колонке `TriggerParams`.

Вопрос «Перепроверка перед сделкой: назови два числа» (карточка
`owner-decision-pereproverka-pered-sdelkoi-nazovi-dva-ch`, 27.09) владелец закрыл 27.10:
допуск свежести ВХОДА 60 с на бумаге / 15 с вживую, срок годности РЕШЕНИЯ 10 минут.
Замер ADR-971 (#1089): 13 дней ответ лежал без исполнителя — в колонке ручки не было,
а читатель колонки (ADR-487 `load_owner_tolerance`) брал ИМЯ ручки, не ЗНАЧЕНИЕ.

Здесь закреплены обе половины исполнения И их связь, в обе стороны:
* числа — ВЛАДЕЛЬЦА (паритет с реестром ответов через константы прибора §28);
* читатель видит ручки ЧЕРЕЗ СВОИ подсказки, а не подстрокой теста (ADR-333);
* колонка без ручки / с нечисловой ручкой — отсутствие названо, число не выдумано;
* смена порогов = новая версия контракта с датой ответа владельца (ADR-060 §3).
"""
# FROZEN-DATE-OK: дата 2026-10-27 — САМА предмет утверждения (version_date контракта = дата
# ответа владельца, ADR-836/972); ни одного сравнения с часами или окна свежести в файле нет —
# календарь этот тест не красит, покраснеть он может только от смены даты в контракте.
from __future__ import annotations

import dataclasses
import types

import pytest

from spa_core.allocator.rebalance_economics import TriggerParams
from spa_core.analytics import decision_expiry_census as DX
from spa_core.monitoring import pre_trade_recheck_census as S49

OWNER_ANSWER_DATE = "2026-10-27"


@pytest.mark.parametrize("mode, freshness_s", [("paper", 60.0), ("pilot", 15.0)])
def test_both_columns_carry_the_owner_numbers_verbatim(mode, freshness_s):
    p = TriggerParams.for_mode(mode)
    assert p.input_freshness_tolerance_s == freshness_s
    assert p.decision_ttl_s == 600.0
    # те же числа, что прибор §28 читает из реестра ответов (ADR-836/839): паритет,
    # а не два независимых литерала
    assert p.input_freshness_tolerance_s == DX.OWNER_FRESHNESS_S[mode]
    assert p.decision_ttl_s == DX.OWNER_TTL_S


def test_contract_version_is_bumped_and_dated_by_the_owner_answer():
    p = TriggerParams()
    assert p.version == "v1.2"
    assert p.version_date == OWNER_ANSWER_DATE
    assert TriggerParams.for_mode("pilot").version_date == OWNER_ANSWER_DATE


def test_the_two_dials_are_declared_fields_not_attributes_bolted_on():
    names = {f.name for f in dataclasses.fields(TriggerParams)}
    assert {"input_freshness_tolerance_s", "decision_ttl_s"} <= names


@pytest.mark.parametrize("mode", ["paper", "pilot"])
def test_the_column_reader_sees_both_dials_by_its_own_hints_and_reads_their_values(mode):
    """Не подстрокой: вопрос задаётся читателю ADR-487, и он отвечает именами И числами."""
    out = S49.load_owner_tolerance(TriggerParams.for_mode(mode))
    assert out["measured"] is True
    assert out["tolerance_dial"] == "input_freshness_tolerance_s"
    assert out["tolerance_s"] == DX.OWNER_FRESHNESS_S[mode]
    assert out["ttl_dial"] == "decision_ttl_s"
    assert out["ttl_s"] == DX.OWNER_TTL_S
    assert out["mode"] == mode and out["version"] == "v1.2"


def test_dial_names_fall_under_the_readers_hints_measured_not_assumed():
    """Если переименовать ручку мимо подсказок, читатель её потеряет — это и проверяется."""
    for name in ("input_freshness_tolerance_s", "decision_ttl_s"):
        assert any(h in name for h in S49._TOLERANCE_HINTS), name
    assert any(h in "input_freshness_tolerance_s" for h in S49._FRESHNESS_HINTS)
    assert any(h in "decision_ttl_s" for h in S49._TTL_HINTS)
    renamed = types.SimpleNamespace(freshness_window=60.0, expiry_of_decision=600.0,
                                    version="scene", mode="paper")
    out = S49.load_owner_tolerance(renamed)
    # «expir» — подсказка, «freshness_window» без «fresh»? содержит — тоже видна
    assert out["ttl_dial"] == "expiry_of_decision" and out["ttl_s"] == 600.0
    assert out["tolerance_dial"] == "freshness_window" and out["tolerance_s"] == 60.0
    lost = types.SimpleNamespace(window_a=60.0, window_b=600.0, version="scene", mode="paper")
    out = S49.load_owner_tolerance(lost)
    assert out["ttl_dial"] is None and out["tolerance_dial"] is None


def test_the_s28_instrument_sees_the_answer_as_executed_with_matching_numbers():
    b = DX.measure_owner_column()
    assert b["measured"], b.get("reason")
    assert b["loader"]["kind"] == "reads_value"
    assert b["column_matches_answer"]["kind"] == "matches", b["column_matches_answer"]


def test_pilot_column_is_judged_against_the_pilot_number_not_the_paper_one():
    b = DX.measure_owner_column(params=TriggerParams.for_mode("pilot"))
    assert b["tolerance_s"] == 15.0
    assert b["column_matches_answer"]["kind"] == "matches", b["column_matches_answer"]


def test_a_mutated_dial_is_reported_as_misexecution_not_absence():
    """Контроль в обратную сторону: число подменили — сторож называет расхождение."""
    mutated = dataclasses.replace(TriggerParams(), decision_ttl_s=60.0)
    b = DX.measure_owner_column(params=mutated)
    assert b["ttl_dial"] == "decision_ttl_s"
    assert b["column_matches_answer"]["kind"] == "differs"
    assert "600" in b["column_matches_answer"]["reason"]


def test_risk_policy_thresholds_are_not_touched_by_the_answer():
    """Ручки мандата ADR-060 §3 ≠ пороги RiskPolicy v1.0: вторые не изменились."""
    from spa_core.risk.policy import RiskConfig
    cfg = RiskConfig()
    assert getattr(cfg, "version", "v1.0") == "v1.0"
    names = {f.name for f in dataclasses.fields(RiskConfig)}
    assert not any("ttl" in n or "fresh" in n for n in names)
