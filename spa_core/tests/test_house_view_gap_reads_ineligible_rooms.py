"""Сверка офис↔книга обязана читать ЧЕТВЁРТЫЙ регистр — и НАЗЫВАТЬ, что именно биндит.

# FROZEN-DATE-OK: injected-clock — часы здесь ВХОД: `compute_gaps(..., now=NOW)` с
# фиксированным `NOW` и фиксированными возрастами входов; календарь на вердикт не влияет.

**Авария, которую повторяет каждый положительный контроль (замер 28.08, цикл #418).**
Обязательный шаг 0-офис третий день подряд печатал красную строку:

    🔴 РЕЦИДИВ: 4 находки ВЕРНУЛИСЬ после закрытия
       причина ОДНА: весь рецидив из класса `gap:opportunity_unnamed`
       - gap:opportunity_unnamed:spark_susds ×2 …

и находка звучала так: «возможность spark_susds 3.9431% (evidence L4) доступна книге,
не держится и отказ НЕ назван — безымянный простой». А в том же
`data/allocation_rationale.json`, в разделе `cash.ineligible_rooms`, про этот же
протокол стояло `why: ["tvl_not_live"]`, `room_usd: 40000.0`, `pct_of_capital: 40.0`.
Причина была названа — просто НЕ ТАМ, куда смотрел сторож.

Это ТОТ ЖЕ класс, что и месяцем раньше (`test_house_view_gap_reads_policy_refusals`,
#394, третий регистр). Дважды подряд одна и та же ошибка означает, что чинить надо не
случай, а то, чем он держался: список опрошенных регистров нигде не был НАЗВАН, и
«отказ НЕ назван» звучало как вывод, хотя было предположением. Поэтому вторая половина
этого файла проверяет, что WARN перечисляет все четыре регистра поимённо.

Контроли — в обе стороны: настоящий безымянный простой обязан остаться WARN, а запись
без причины не имеет права гасить сигнал.
"""

from __future__ import annotations

import datetime as dt
import inspect

import pytest

from spa_core.monitoring import house_view_gap as H

NOW = dt.datetime(2026, 8, 28, 23, 0, tzinfo=dt.timezone.utc)
AGES = {"chief_investment": {"input": "chief_investment", "age_s": 360},
        "current_positions": {"input": "current_positions", "age_s": 3240}}
PROTO = "spark_susds"

#: Дословная запись прод-цикла 28.08 22:08Z (`data/allocation_rationale.json`).
REAL_ROOM = {"protocol": PROTO, "room_usd": 40000.0, "pct_of_capital": 40.0,
             "why": ["tvl_not_live"]}

#: Соседи по тому же живому регистру — четыре разных семейства причин в одной записи.
REAL_ROOM_BLOCKED = {"protocol": "stusd", "room_usd": 20000.0, "pct_of_capital": 20.0,
                     "why": ["blocked:unevidenced", "apy_source_missing",
                             "tvl_not_live", "tvl_unmeasured"]}
REAL_ROOM_FLOOR = {"protocol": "moonwell_base", "room_usd": 20000.0,
                   "pct_of_capital": 20.0,
                   "why": ["tvl_below_floor:$2,086,116<$5,000,000"]}
REAL_ROOM_APY = {"protocol": "scrvusd", "room_usd": 20000.0, "pct_of_capital": 20.0,
                 "why": ["apy_below_min:0.52%<1.00%"]}


def chief(protocol: str = PROTO, apy: float = 3.9431) -> dict:
    return {"house_view": {"overall_posture": "GREEN",
                           "top_opportunities": [
                               {"evidence_level": "L4", "source": "defillama",
                                "value": {"protocol": protocol, "apy_pct": apy}}]}}


def book_without(protocol: str) -> dict:
    return {"capital_usd": 100000.0, "cash_usd": 10000.0,
            "positions": {"compound_v3": {"usd": 90000.0}}}


def rationale(rooms=None, policy_refusals=None, below_median=None, cash=True) -> dict:
    doc: dict = {"below_median_cap": below_median or [],
                 "decision_shadow": {"warnings": []}}
    if cash:
        doc["cash"] = {"policy_refusals": policy_refusals or []}
        if rooms is not None:
            doc["cash"]["ineligible_rooms"] = rooms
    return doc


def run(rat, protocol: str = PROTO, registry=(PROTO, "compound_v3", "stusd",
                                              "moonwell_base", "scrvusd")) -> dict:
    return H.compute_gaps(chief(protocol), book_without(protocol), rat,
                          set(registry), {}, NOW, AGES)


def keys(report: dict) -> set:
    return {g["key"] for g in report["gaps"]}


def gap_for(report: dict, protocol: str) -> dict:
    found = [g for g in report["gaps"] if g["key"].endswith(f":{protocol}")]
    assert len(found) == 1, [g["key"] for g in report["gaps"]]
    return found[0]


# ── положительные контроли: авария 28.08 дословно ───────────────────────────

def test_reason_named_in_ineligible_rooms_is_not_an_unnamed_idle():
    """Дословный регистр прод-цикла 28.08: WARN «безымянный простой» исчезает."""
    report = run(rationale(rooms=[REAL_ROOM]))
    assert f"gap:opportunity_unnamed:{PROTO}" not in keys(report)
    assert f"gap:opportunity_explained:{PROTO}" in keys(report)
    assert gap_for(report, PROTO)["severity"] == "INFO"
    assert report["counts"]["warn"] == 0, report["gaps"]


def test_the_message_says_WHAT_binds_not_just_that_something_does():
    """Пункт 1 карточки: назван ФИД, а не «отказ где-то назван»."""
    g = gap_for(run(rationale(rooms=[REAL_ROOM])), PROTO)
    assert "фид молчит" in g["message"], g["message"]
    assert "tvl_not_live" in g["message"], g["message"]      # машинный код грепается
    assert g["refusal"] and "tvl_not_live" in g["refusal"]


def test_the_message_carries_how_much_capital_is_bound():
    """«Фид молчит» без денег читается как мелочь — за ним стояли 40 % капитала."""
    g = gap_for(run(rationale(rooms=[REAL_ROOM])), PROTO)
    assert "40 000" in g["message"], g["message"]
    assert "40.0% капитала" in g["message"], g["message"]


def test_bridge_no_longer_sees_a_warn_for_this_protocol():
    """Мост ADR-066 заводит карточки только на WARN/CRITICAL — их тут больше нет."""
    report = run(rationale(rooms=[REAL_ROOM]))
    assert [g for g in report["gaps"] if g["severity"] in ("WARN", "CRITICAL")
            and g["key"].endswith(f":{PROTO}")] == []


@pytest.mark.parametrize("row, expect", [
    (REAL_ROOM_BLOCKED, "закрыт режимом (unevidenced)"),
    (REAL_ROOM_FLOOR, "размер пула ниже порога политики ($2,086,116<$5,000,000)"),
    (REAL_ROOM_APY, "доходность ниже нижней границы политики (0.52%<1.00%)"),
])
def test_every_live_reason_family_is_named_in_russian(row, expect):
    """Четыре семейства кодов живого регистра — режим, порог TVL, нижняя граница APY."""
    proto = row["protocol"]
    g = gap_for(run(rationale(rooms=[row]), protocol=proto), proto)
    assert expect in g["message"], g["message"]


def test_measured_numbers_of_the_allocator_pass_through_verbatim():
    """Чужой замер не пересказываем своими словами — иначе однажды разойдёмся молча."""
    assert "$2,086,116<$5,000,000" in H.humanize_why(REAL_ROOM_FLOOR["why"])


def test_an_unknown_code_is_printed_verbatim_not_swallowed():
    """Сверка обязана быть ШИРЕ подопечного: новый код аллокатора читатель увидит."""
    assert H.humanize_why(["kod_kotorogo_my_ne_znaem"]) == "kod_kotorogo_my_ne_znaem"


def test_room_without_an_amount_still_explains():
    """Сумма — украшение, причина — суть."""
    g = gap_for(run(rationale(rooms=[{"protocol": PROTO, "why": ["tvl_not_live"]}])), PROTO)
    assert g["key"] == f"gap:opportunity_explained:{PROTO}"
    assert "фид молчит" in g["message"]
    assert "заперта комната" not in g["message"]


# ── обратные контроли: настоящая находка обязана выжить ─────────────────────

def test_silent_registers_are_still_an_unnamed_idle():
    """Ни один из четырёх регистров не назвал причину ⇒ WARN, как и до починки."""
    report = run(rationale(rooms=[]))
    assert f"gap:opportunity_unnamed:{PROTO}" in keys(report)
    assert report["counts"]["warn"] >= 1


def test_a_room_about_another_protocol_does_not_explain_ours():
    """Названная причина про соседа не закрывает вопрос про нас."""
    report = run(rationale(rooms=[REAL_ROOM_BLOCKED]))
    assert f"gap:opportunity_unnamed:{PROTO}" in keys(report)


@pytest.mark.parametrize("row", [
    {"protocol": PROTO},                            # причины нет вовсе
    {"protocol": PROTO, "why": []},                 # список пуст
    {"protocol": PROTO, "why": ["", "   "]},        # причины из пробелов
    {"protocol": PROTO, "why": {"a": 1}},           # не список
    {"why": ["tvl_not_live"]},                      # протокол не назван
    "не словарь",                                   # мусор вместо записи
    None,
])
def test_a_room_without_a_reason_explains_nothing(row):
    """Запись без ПРИЧИНЫ — не объяснение: иначе пустой регистр гасил бы сигнал."""
    report = run(rationale(rooms=[row]))
    assert f"gap:opportunity_unnamed:{PROTO}" in keys(report)


def test_ineligible_rooms_not_a_list_is_ignored_not_trusted():
    """Раздел не той формы — не причина: молчаливое гашение сигнала запрещено."""
    for junk in ("строка", {"protocol": PROTO}, 7):
        report = run(rationale(rooms=junk))
        assert f"gap:opportunity_unnamed:{PROTO}" in keys(report), junk


def test_missing_section_falls_back_to_the_old_three_registers():
    """Старая форма rationale (раздела нет) обязана вести себя ровно как раньше."""
    report = run(rationale(rooms=None))
    assert f"gap:opportunity_unnamed:{PROTO}" in keys(report)
    report_no_cash = run(rationale(cash=False))
    assert f"gap:opportunity_unnamed:{PROTO}" in keys(report_no_cash)


def test_policy_refusals_win_over_ineligible_rooms():
    """Гейт ближе к деньгам, чем «почему протокол непригоден» — его слово первое."""
    g = gap_for(run(rationale(
        rooms=[REAL_ROOM],
        policy_refusals=[{"protocol": PROTO, "reason": "tvl_unverified_policy_gate",
                          "usd_removed_from_target": 37894.74}])), PROTO)
    assert "tvl_unverified_policy_gate" in g["refusal"]
    assert "tvl_not_live" not in g["refusal"]


def test_empty_below_median_entry_is_replaced_by_the_named_reason():
    """`below_median_cap` объяснением не был — пустая строка не имеет права его держать."""
    g = gap_for(run(rationale(rooms=[REAL_ROOM],
                              below_median=[{"protocol": PROTO}])), PROTO)
    assert g["refusal"] and "tvl_not_live" in g["refusal"], g


# ── «отказ НЕ назван» обязан назвать, У КОГО спрашивали ─────────────────────

def test_the_unnamed_warning_lists_every_register_it_asked():
    """Иначе это не вывод, а предположение — и дважды подряд оно было ЛОЖНЫМ."""
    g = gap_for(run(rationale(rooms=[])), PROTO)
    assert "безымянный простой" in g["message"]          # находка НЕ погашена
    for register in ("below_median_cap", "cash.policy_refusals",
                     "cash.ineligible_rooms", "decision_shadow.warnings"):
        assert register in g["message"], (register, g["message"])


def test_the_named_register_list_matches_the_registers_actually_read():
    """Обещание в тексте и код обязаны совпадать: переименовали регистр — тест краснеет."""
    src = inspect.getsource(H.compute_gaps)
    named = [r.strip() for r in H.REGISTERS_RU.split(" · ")]
    assert len(named) == 4, named          # текст обещает ЧЕТЫРЕ — столько и проверяем
    for register in named:
        # Путь читается по сегментам (`cash` → `policy_refusals`), поэтому и сверяем
        # посегментно: `rationale.get("decision_shadow")` и `shadow.get("warnings")` —
        # два разных литерала, склеенных только в тексте находки.
        for segment in register.split("."):
            assert f'"{segment}"' in src, (register, segment, "нет в compute_gaps")
