"""Сверка обязана читать НАЗВАННУЮ причину из атрибуции кэша того же цикла (ADR-076.3).

Каждый тест — положительный контроль: воспроизводит живой замер 18.08 и краснеет на
модуле без починки.

Авария: брифинг печатал `house_view_gap warn=2` — `moonwell_base` 5.73 % и
`fluid_fusdc` 5.54 % «доступны книге, не держатся, отказ НЕ назван». Причина каждого
была измерена и записана ТЕМ ЖЕ циклом в `allocation_rationale.json → cash`
(`ineligible_rooms`: `tvl_below_floor` / `apy_not_live`), но сверка читала из rationale
ровно два поля — `below_median_cap` и `decision_shadow.warnings` — и про атрибуцию не
знала. Вторая копия определения «назван ли отказ»: производитель называет причину в
одном месте, потребитель ищет в другом, владелец читает «непонятно почему» про
измеренное.

Обратная сторона закреплена здесь же: настоящий безымянный простой (цикл сам пишет
`unexplained_deployable`) обязан ОСТАТЬСЯ WARN. Иначе это не починка отчёта, а глушение
сигнала (инвариант 16 по духу).

Время — ВХОД: `compute_gaps(..., now=)`, отметки относительны. Календарь фикстуры не
трогает.
"""
from __future__ import annotations

import datetime as dt

from spa_core.monitoring import house_view_gap as H

# FROZEN-DATE-OK: injected-clock — часы здесь ВХОД, а не окружение (шаблон 1
# `.claude/rules/deployment.md`): `NOW` фиксирован, ВСЕ отметки фикстур строятся
# относительно него (`iso(hours_ago=…)`), а свежесть артефактов сверка судит по
# явному `age_s` из `AGES`, а не по календарю. Сдвиг даты не может уронить ни один
# тест этого файла — обе стороны закреплены.
NOW = dt.datetime(2026, 8, 18, 12, 0, tzinfo=dt.timezone.utc)
REGISTRY = {"moonwell_base", "fluid_fusdc"}
AGES = {k: {"age_s": 3600} for k in
        ("chief_investment", "current_positions", "allocation_rationale")}


def iso(hours_ago: float = 0.0) -> str:
    return (NOW - dt.timedelta(hours=hours_ago)).isoformat()


def chief(protocols=(("moonwell_base", 5.73), ("fluid_fusdc", 5.54))):
    return {"generated_at": iso(3), "house_view": {
        "overall_posture": "YELLOW",
        "top_opportunities": [
            {"value": {"protocol": p, "apy_pct": apy}, "evidence_level": "L3",
             "source": "io_chief_investment"} for p, apy in protocols]}}


def positions():
    return {"generated_at": iso(2), "capital_usd": 100000.0,
            "positions": {"aave_v3": 40000.0, "morpho_steakhouse": 20000.0}}


def rationale(cash):
    """Форма ровно та, что пишет `allocation_rationale.write_shadow_rationale`."""
    doc = {"generated_at": iso(2), "decision_shadow": {"warnings": []},
           "below_median_cap": []}
    if cash is not None:
        doc["cash"] = cash
    return doc


def keys(report):
    return {g["key"]: g["severity"] for g in report["gaps"]}


def run(cash):
    return H.compute_gaps(chief(), positions(), rationale(cash), REGISTRY, {},
                          NOW, ages=AGES)


# ── сторона 1: причина измерена и записана — объяснение обязано появиться ────

def test_ineligible_rooms_name_the_refusal():
    """Живой замер 18.08: обе возможности отклонены по названным причинам."""
    report = run({
        "status": "UNEXPLAINED_CASH", "unexplained_pct": 20.0,
        "components": [{"kind": "insufficient_eligible_live", "usd": 20000.0,
                        "protocols": ["moonwell_base($20,000: tvl_below_floor:1.41M<5.00M)",
                                      "fluid_fusdc($20,000: apy_not_live)"]}],
        "ineligible_rooms": [
            {"protocol": "moonwell_base", "why": ["tvl_below_floor:1.41M<5.00M"]},
            {"protocol": "fluid_fusdc", "why": ["apy_not_live"]}],
    })
    assert report["counts"]["warn"] == 0, report["gaps"]
    assert keys(report) == {"gap:opportunity_explained:moonwell_base": "INFO",
                            "gap:opportunity_explained:fluid_fusdc": "INFO"}
    # Причина НАЗВАНА дословно, а не заменена словом «объяснено».
    named = {g["protocol"]: g["refusal_reason"] for g in report["gaps"]}
    assert named["moonwell_base"] == "tvl_below_floor:1.41M<5.00M"
    assert named["fluid_fusdc"] == "apy_not_live"
    assert "tvl_below_floor" in [g for g in report["gaps"]
                                 if g["protocol"] == "moonwell_base"][0]["message"]


def test_per_protocol_cap_component_names_the_limit():
    """Комнату держит потолок тира — это записанное решение, а не молчание."""
    report = run({
        "status": "UNEXPLAINED_CASH", "unexplained_pct": 0.0,
        "components": [{"kind": "per_protocol_cap", "usd": 20000.0,
                        "protocols": ["moonwell_base@cap(counterfactual)",
                                      "fluid_fusdc@cap(counterfactual)"]}],
    })
    assert report["counts"]["warn"] == 0, report["gaps"]
    assert {g["refusal_reason"] for g in report["gaps"]} == {"per_protocol_cap"}


def test_policy_refusal_names_the_gate():
    report = run({
        "status": "UNEXPLAINED_CASH", "unexplained_pct": 20.0, "components": [],
        "policy_refusals": [
            {"protocol": "moonwell_base", "reason": "tvl_unverified_policy_gate",
             "usd_removed_from_target": 10000.0},
            {"protocol": "fluid_fusdc", "reason": "tvl_unverified_policy_gate",
             "usd_removed_from_target": 5000.0}],
    })
    assert report["counts"]["warn"] == 0, report["gaps"]
    assert {g["refusal_reason"] for g in report["gaps"]} == {"tvl_unverified_policy_gate"}


# ── сторона 2 (положительный контроль): молчание обязано остаться WARN ───────

def test_unexplained_deployable_stays_unnamed():
    """Цикл САМ пишет «фондируемо и стоит без записанной причины» — сигнал не гасить."""
    report = run({
        "status": "UNEXPLAINED_CASH", "unexplained_pct": 20.0,
        "components": [{"kind": "unexplained_deployable", "usd": 20000.0,
                        "protocols": ["moonwell_base(+$20,000 @ 5.73%)",
                                      "fluid_fusdc(+$20,000 @ 5.54%)"]}],
    })
    assert report["counts"]["warn"] == 2, report["gaps"]
    assert set(keys(report)) == {"gap:opportunity_unnamed:moonwell_base",
                                 "gap:opportunity_unnamed:fluid_fusdc"}


def test_unexplained_deployable_outranks_a_mere_mention():
    """«Упомянут» ≠ «отказ назван»: имя в warnings не отменяет молчания атрибуции."""
    doc = rationale({
        "status": "UNEXPLAINED_CASH", "unexplained_pct": 20.0,
        "components": [{"kind": "unexplained_deployable", "usd": 20000.0,
                        "protocols": ["moonwell_base(+$20,000 @ 5.73%)"]}],
        "ineligible_rooms": [{"protocol": "moonwell_base", "why": ["stale_note"]}],
    })
    doc["decision_shadow"] = {"warnings": ["moonwell_base upgrade pending"]}
    report = H.compute_gaps(chief((("moonwell_base", 5.73),)), positions(), doc,
                            REGISTRY, {}, NOW, ages=AGES)
    assert keys(report) == {"gap:opportunity_unnamed:moonwell_base": "WARN"}


def test_missing_cash_block_changes_nothing():
    """Атрибуции нет ⇒ причина НЕ ИЗМЕРЕНА ⇒ прежний вердикт, а не выдуманное объяснение."""
    report = run(None)
    assert report["counts"]["warn"] == 2, report["gaps"]
    assert set(keys(report)) == {"gap:opportunity_unnamed:moonwell_base",
                                 "gap:opportunity_unnamed:fluid_fusdc"}


def test_broken_cash_block_changes_nothing():
    """Мусор вместо атрибуции — тоже «не измерено» (fail-CLOSED), не объяснение."""
    assert H.named_refusals_from_cash({"cash": "oops"}) == {}
    assert H.named_refusals_from_cash({"cash": {"components": [None, 5]}}) == {}
    assert H.named_refusals_from_cash(None) == {}
    assert run("not-a-dict-cash")["counts"]["warn"] == 2


def test_rationale_absent_is_still_unchecked_not_a_finding():
    """Гарантия 3 ADR-070 не ослаблена: файла нет ⇒ отказ судить, а не находка."""
    report = H.compute_gaps(chief(), positions(), None, REGISTRY, {}, NOW, ages=AGES)
    assert report["counts"]["warn"] == 0
    assert [u["input"] for u in report["unchecked"]].count("allocation_rationale") >= 1
