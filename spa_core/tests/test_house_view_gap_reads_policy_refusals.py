"""Сверка офис↔книга обязана читать ТРЕТИЙ регистр названных отказов.

# FROZEN-DATE-OK: injected-clock — часы здесь ВХОД: `compute_gaps(..., now=NOW)` с
# фиксированным `NOW` и фиксированными возрастами входов; календарь на вердикт не влияет.

**Авария, которую повторяет каждый положительный контроль (замер 27.08, цикл #394).**
`house_view_gap` спрашивал «назван ли отказ?» у ДВУХ регистров аллокатора —
`below_median_cap` и `decision_shadow.warnings`. Третий, `cash.policy_refusals`, пишет
тот же цикл в тот же файл и содержит протокол, ПРИЧИНУ и снятую с цели сумму. В итоге
`spark_susds` шёл как **безымянный простой** (WARN), мост ADR-066 завёл по нему карточку
и понёс её владельцу, а в `data/allocation_rationale.json` про этот же протокол стояло
`tvl_unverified_policy_gate`, $37 894.74 снято с цели. Отказ был назван — просто не там,
куда смотрел сторож.

Это не «сторож придирался»: он честно отвечал на СВОЙ вопрос, а читали его как ответ на
нужный. Ложная находка стоит внимания владельца, а рядом с ней однажды проедет настоящая.

Контроли — в обе стороны: настоящий безымянный простой обязан остаться WARN.
"""

from __future__ import annotations

import datetime as dt

import pytest

from spa_core.monitoring import house_view_gap as H

NOW = dt.datetime(2026, 8, 27, 10, 0, tzinfo=dt.timezone.utc)
AGES = {"chief_investment": 0.1, "current_positions": 0.1}
PROTO = "spark_susds"


def chief(protocol: str, apy: float = 3.8367) -> dict:
    return {"house_view": {"overall_posture": "GREEN",
                           "top_opportunities": [
                               {"evidence_level": "L4", "source": "defillama",
                                "value": {"protocol": protocol, "apy_pct": apy}}]}}


def book_without(protocol: str) -> dict:
    return {"capital_usd": 100000.0, "cash_usd": 10000.0,
            "positions": {"aave_v3": {"usd": 90000.0}}}


def rationale(policy_refusals=None, below_median=None) -> dict:
    return {"below_median_cap": below_median or [],
            "decision_shadow": {"warnings": []},
            "cash": {"policy_refusals": policy_refusals or []}}


def run(rat, registry=(PROTO, "aave_v3")) -> dict:
    return H.compute_gaps(chief(PROTO), book_without(PROTO), rat, set(registry), {},
                          NOW, AGES)


def keys(report: dict) -> set:
    return {g["key"] for g in report["gaps"]}


def gap_for(report: dict, protocol: str) -> dict:
    found = [g for g in report["gaps"] if g["key"].endswith(f":{protocol}")]
    assert len(found) == 1, [g["key"] for g in report["gaps"]]
    return found[0]


# ── положительные контроли: авария 27.08 ────────────────────────────────────

REAL_REFUSAL = [{"protocol": "fluid_fusdc", "reason": "tvl_unverified_policy_gate",
                 "usd_removed_from_target": 18947.37, "pct_of_capital": 18.9474},
                {"protocol": "spark_susds", "reason": "tvl_unverified_policy_gate",
                 "usd_removed_from_target": 37894.74, "pct_of_capital": 37.8947}]


def test_refusal_named_in_policy_refusals_is_not_an_unnamed_idle():
    """Дословный регистр прод-цикла 27.08: WARN «безымянный простой» исчезает."""
    report = run(rationale(policy_refusals=REAL_REFUSAL))
    assert f"gap:opportunity_unnamed:{PROTO}" not in keys(report)
    assert f"gap:opportunity_explained:{PROTO}" in keys(report)
    assert gap_for(report, PROTO)["severity"] == "INFO"


def test_the_message_carries_the_reason_itself():
    """Читатель находки узнаёт ПРИЧИНУ, не открывая rationale."""
    g = gap_for(run(rationale(policy_refusals=REAL_REFUSAL)), PROTO)
    assert "tvl_unverified_policy_gate" in g["message"]
    assert "37 895" in g["message"], g["message"]
    assert g["refusal"] and "tvl_unverified_policy_gate" in g["refusal"]


def test_bridge_no_longer_sees_a_warn_for_this_protocol():
    """Мост ADR-066 заводит карточки только на WARN/CRITICAL — их тут больше нет."""
    report = run(rationale(policy_refusals=REAL_REFUSAL))
    assert [g for g in report["gaps"] if g["severity"] in ("WARN", "CRITICAL")
            and g["key"].endswith(f":{PROTO}")] == []


def test_refusal_without_the_removed_amount_still_explains():
    """Сумма — украшение, причина — суть."""
    g = gap_for(run(rationale(policy_refusals=[{"protocol": PROTO, "reason": "gate"}])), PROTO)
    assert g["key"] == f"gap:opportunity_explained:{PROTO}"
    assert g["refusal"] == "gate"


# ── обратные контроли: настоящая находка обязана выжить ─────────────────────

def test_silent_rationale_is_still_an_unnamed_idle():
    """Ни один регистр не назвал отказ ⇒ WARN, как и до починки."""
    report = run(rationale())
    assert f"gap:opportunity_unnamed:{PROTO}" in keys(report)
    assert report["counts"]["warn"] >= 1


def test_refusal_about_another_protocol_does_not_explain_ours():
    """Названный отказ про соседа не закрывает вопрос про нас."""
    report = run(rationale(policy_refusals=[{"protocol": "fluid_fusdc", "reason": "gate"}]))
    assert f"gap:opportunity_unnamed:{PROTO}" in keys(report)


@pytest.mark.parametrize("row", [
    {"protocol": PROTO},                       # причины нет вовсе
    {"protocol": PROTO, "reason": ""},         # причина пустая
    {"protocol": PROTO, "reason": "   "},      # причина из пробелов
    {"reason": "gate"},                        # протокол не назван
    "не словарь",                              # мусор вместо записи
    None,
])
def test_a_refusal_without_a_reason_explains_nothing(row):
    """Запись без ПРИЧИНЫ — не объяснение: иначе пустой регистр гасил бы сигнал."""
    report = run(rationale(policy_refusals=[row]))
    assert f"gap:opportunity_unnamed:{PROTO}" in keys(report)


def test_missing_cash_section_falls_back_to_the_old_two_registers():
    """Старая форма rationale (без `cash`) обязана вести себя ровно как раньше."""
    report = run({"below_median_cap": [], "decision_shadow": {"warnings": []}})
    assert f"gap:opportunity_unnamed:{PROTO}" in keys(report)
    report2 = run({"below_median_cap": [{"protocol": PROTO}],
                   "decision_shadow": {"warnings": []}})
    assert f"gap:opportunity_explained:{PROTO}" in keys(report2)
    assert gap_for(report2, PROTO)["refusal"] is None


def test_below_median_cap_message_is_unchanged_without_a_named_reason():
    """У ветки `below_median_cap` причины нет — текст обязан остаться прежним."""
    g = gap_for(run(rationale(below_median=[{"protocol": PROTO}])), PROTO)
    assert g["message"].endswith("отказ НАЗВАН в rationale")
