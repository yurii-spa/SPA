"""Батарея §23 «Starting policy for Shadow Mode» (ADR-966).

Каждая проба здесь — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: зелена на целом контуре и красна
на ОДНОМ названном порванном звене. Ни одно утверждение не судит о структуре
ПОДСТРОКОЙ текста (ADR-333): проверяется форма отчёта и ПЕРЕХОД вердикта.

Две ошибки замера, которые эта батарея держит, чтобы они не вернулись:

* **узкий край APY в сцене шестой величины.** Ход на 2 пп при узком крае не
  дотягивает до ``min_gain_pp`` (0.50 пп от ВСЕГО капитала), дверь отказывает
  ПО ВЫИГРЫШУ, и «величина не спрашивается» прочиталось бы на пустом месте.
  Держит :func:`test_alloc_scene_is_economically_worth_it_at_both_edges`.
* **соседний потолок, связывающий первым.** Сцена дневного оборота на ходе
  22 пп отклонялась ``max_turnover_per_move`` и ``max_trade_usd``, а не дневной
  ручкой; возмущение дневного потолка вердикт не двигало, и прибор сказал бы
  «ручка инертна», споря с §22 (BINDING). Держит
  :func:`test_turnover_scene_is_bound_by_the_daily_dial_and_not_a_neighbour`.
"""
# Литеральной даты в этом файле НЕТ ни одной, поэтому и претензии
# `FROZEN-DATE-OK` здесь нет: якорь сцены (`SCENE_NOW`) объявлен в §22 и
# ВВОЗИТСЯ, часы обеих дверей получают момент входом `now`, а записка о
# инъекции без своего якоря была бы претензией без предмета.
from __future__ import annotations

import dataclasses

import pytest

from spa_core.analytics import anti_churn_census as s22
from spa_core.analytics import shadow_start_policy_census as s23
from spa_core.analytics.shadow_start_policy_census import (
    ABSENT, BINDING, DECLARATION_KINDS, DELEGATED_TO_22, DELEGATION_REFUSED,
    OWNER_START_VALUES_DECLARED, OWNER_START_WORDING, ORDER_G954_NAMED,
    REACH_KINDS, SHADOW_START_VALUES, UNMEASURED, VALUE_KINDS,
)


# ───────────────────────── ввоз словарей и шкалы ────────────────────────────

def test_vocabularies_are_imported_not_copied():
    """Словари ВВЕЗЕНЫ. Своя копия перечня — вторая шкала об одном предмете."""
    assert s23._VOCAB_ERRORS == [], s23._VOCAB_ERRORS
    # ТОЖДЕСТВО объекта, а не равенство текста: равный по значению список мог бы
    # быть набран руками и разойтись молча при первом же изменении §22.
    assert s23.SURFACES_22 is s22.SURFACES_22
    assert s23.SCENE_NOW is s22.SCENE_NOW
    assert s23._books is s22._books
    assert s23._econ_move is s22._econ_move
    assert s23._damper_move is s22._damper_move


def test_broken_import_is_unmeasured_not_a_clean_pass(monkeypatch):
    """Порванный ввоз ⇒ код 2 с названной причиной, а не зелёный отчёт."""
    monkeypatch.setattr(s23, "_VOCAB_ERRORS", ["§22 словари: ImportError: сцена"])
    report = s23.census()
    assert s23.verdict_code(report) == 2
    assert report["vocab_errors"]
    assert report["control"]["passed"] is False


# ───────────────── ШЕСТЬ величин, а не четыре (ловушка заказа) ───────────────

def test_six_values_declared_and_the_order_undercount_is_reported():
    """§23 называет ШЕСТЬ величин; заказ G954 назвал четыре, и это ИЗМЕРЕНО."""
    assert OWNER_START_VALUES_DECLARED == 6
    assert len(SHADOW_START_VALUES) == OWNER_START_VALUES_DECLARED
    assert len(set(SHADOW_START_VALUES)) == OWNER_START_VALUES_DECLARED
    assert ORDER_G954_NAMED == 4
    report = s23.census()
    assert report["values_declared"] == 6
    assert report["order_undercount"] == 2
    assert len(report["values"]) == 6


def test_every_value_carries_the_owners_wording_verbatim():
    """У каждой величины объявлено СЛОВО владельца — пересказ теряет пункты."""
    assert set(OWNER_START_WORDING) == set(SHADOW_START_VALUES)
    for name in SHADOW_START_VALUES:
        assert OWNER_START_WORDING[name].strip()
    # Две величины, потерянные заказом, обязаны быть НАЗВАНЫ.
    assert "cooldown" in SHADOW_START_VALUES
    assert "maximum daily turnover" in SHADOW_START_VALUES


# ──────────────────────────── делегирование §22 ─────────────────────────────

def test_five_values_are_delegated_and_the_sixth_is_refused_with_a_reason():
    delegated = set(DELEGATED_TO_22)
    assert len(delegated) == 5
    assert delegated | set(DELEGATION_REFUSED) == set(SHADOW_START_VALUES)
    assert set(DELEGATION_REFUSED) == {"target allocation difference"}
    assert DELEGATION_REFUSED["target allocation difference"].strip()
    # Все цели делегирования — СЛОВА ВЛАДЕЛЬЦА из §22, а не наши слаги.
    assert set(DELEGATED_TO_22.values()) <= set(s22.OWNER_PARAMS)


def test_delegation_key_is_the_owners_word_not_our_slug(monkeypatch):
    """Переименуй §22 свою строку — делегирование даёт НЕ ИЗМЕРЕНО, не молчание.

    Порванное звено НАЗВАНО: ключ ``param`` в отчёте §22.
    """
    real = s22.census

    def renamed(*a, **kw):
        doc = real(*a, **kw)
        for row in doc["params"]:
            row["param"] = "НАШ_СЛАГ::" + str(row["param"])
        return doc

    monkeypatch.setattr(s23, "census_22", renamed)
    report = s23.census()
    for row in report["values"]:
        if row["value"] in DELEGATED_TO_22:
            assert row["existence"] == UNMEASURED, row
            assert row["existence_detail"].strip()
            assert row["declaration"] == UNMEASURED
    assert s23.verdict_code(report) == 2


def test_failed_control_of_s22_gives_unmeasured_not_absent(monkeypatch):
    """§22 не смог измерить ⇒ UNMEASURED, а НЕ ABSENT.

    Порванное звено НАЗВАНО: положительный контроль §22.
    """
    real = s22.census

    def broken(*a, **kw):
        doc = real(*a, **kw)
        doc["control"] = {"passed": False, "reason": "сцена не построена",
                          "healthy_baseline": {}}
        return doc

    monkeypatch.setattr(s23, "census_22", broken)
    report = s23.census()
    delegated_rows = [r for r in report["values"] if r["value"] in DELEGATED_TO_22]
    assert delegated_rows
    for row in delegated_rows:
        assert row["existence"] == UNMEASURED
        assert row["existence"] != ABSENT
    assert s23.verdict_code(report) == 2


# ───────────────────── род объявления: контроль по каждому ───────────────────

def test_declaration_kinds_vocabulary_is_closed_and_each_is_reachable():
    """Каждый род шкалы ДОСТИЖИМ — иначе его ноль есть свойство классификатора."""
    assert UNMEASURED in DECLARATION_KINDS
    seen = set()
    # величины нет
    seen.add(s23._declaration_kind(False, None, {}, {})[0])
    # есть, но несущий контракт не найден
    seen.add(s23._declaration_kind(True, None, {}, {})[0])
    # есть, контракт несёт признак СТАРТОВОГО значения
    seen.add(s23._declaration_kind(
        True, "Fake", {"Fake": ["shadow_start_min_hold"]}, {})[0])
    # есть, контракт объявлен ПРОДАКШН-политикой
    seen.add(s23._declaration_kind(
        True, "Fake", {}, {"Fake": ["version", "version_date"]})[0])
    # есть, род не объявлен никак
    seen.add(s23._declaration_kind(True, "Fake", {}, {})[0])
    assert seen == set(DECLARATION_KINDS), sorted(seen)


def test_a_shadow_marker_beats_a_production_marker():
    """Признак СТАРТОВОГО значения старше признака продакшн-решения.

    Порванное звено НАЗВАНО: порядок вопросов в ``_declaration_kind``.
    """
    kind, why = s23._declaration_kind(
        True, "Fake", {"Fake": ["shadow_start_cooldown"]},
        {"Fake": ["version"]})
    assert kind == "shadow_start_declared"
    assert why.strip()


def test_marker_census_is_measured_from_declared_fields_not_a_hand_list():
    """Признак МЕРИТСЯ по полям контракта: добавь поле — ответ обязан измениться."""
    before = s23._marker_fields({"C": {"min_hold_days"}}, s23.SHADOW_MARKER_TOKENS)
    after = s23._marker_fields({"C": {"min_hold_days", "shadow_min_hold_days"}},
                               s23.SHADOW_MARKER_TOKENS)
    assert before == {}
    assert after == {"C": ["shadow_min_hold_days"]}


def test_the_live_policy_declares_no_shadow_start_marker_at_all():
    """Замер, ради которого §23 и мерится: рода «стартовое» в политике НЕТ.

    Утверждение структурное: имена полей берутся у ``dataclasses.fields``, а не
    из текста модуля. Появись в политике поле со стартовым признаком — тест
    покраснеет, и это ВЕРНО: отчёт обязан измениться вместе с деревом.
    """
    from spa_core.allocator.rebalance_economics import TriggerParams
    names = {f.name for f in dataclasses.fields(TriggerParams)}
    shadowish = {n for n in names
                 if any(t in n.lower() for t in s23.SHADOW_MARKER_TOKENS)}
    productionish = {n for n in names
                     if any(t in n.lower() for t in s23.PRODUCTION_MARKER_TOKENS)}
    assert shadowish == set(), shadowish
    assert productionish, "продакшн-признак обязан быть — иначе шкала не применима"


# ─────────────────────── ось значения: контроль в обе стороны ────────────────

def test_value_kinds_vocabulary_is_closed():
    assert UNMEASURED in VALUE_KINDS
    assert set(VALUE_KINDS) >= {"matches", "differs", "no_live_value",
                                "not_commensurable"}


def test_cooldown_value_differs_today_and_would_match_at_the_owners_number(monkeypatch):
    """Сравнение ДВИЖЕТСЯ от живого числа — иначе это не сравнение.

    Порванное звено НАЗВАНО: живая колонка порогов ``_live_params``.
    """
    today = s23._value_comparison("cooldown", True)
    assert today["kind"] == "differs"

    from spa_core.allocator.rebalance_economics import TriggerParams
    monkeypatch.setattr(
        s23, "_live_params",
        lambda: dataclasses.replace(
            TriggerParams.for_mode("paper"),
            min_hold_days=s23.S23_COOLDOWN_HOURS / 24.0))
    assert s23._value_comparison("cooldown", True)["kind"] == "matches"


def test_absent_value_is_no_live_value_not_differs():
    out = s23._value_comparison("target allocation difference", False)
    assert out["kind"] == "no_live_value"
    assert out["why"].strip()


def test_unreadable_policy_is_unmeasured_not_a_number(monkeypatch):
    """Политику не прочитали ⇒ третий исход, а не «не совпало».

    Порванное звено НАЗВАНО: ``_live_params`` падает.
    """
    def boom():
        raise RuntimeError("колонка порогов не прочитана")

    monkeypatch.setattr(s23, "_live_params", boom)
    assert s23._value_comparison("cooldown", True)["kind"] == UNMEASURED


# ───────────── шестая величина: своя проба и её положительный контроль ───────

def test_alloc_scene_is_economically_worth_it_at_both_edges():
    """Края сцены ДОЛЖНЫ быть экономически выгодны — иначе ответ случаен.

    Это ПЕРВАЯ моя ошибка замера, закреплённая тестом: при узком крае APY ход
    на 2 пп не дотягивает до ``min_gain_pp``, и «величина не спрашивается»
    читалось бы там, где дверь отказывает ПО ВЫИГРЫШУ.
    Порванное звено НАЗВАНО: ``_ALLOC_SCENE_EDGE_PCT``.
    """
    cap = s23._scene_capital()
    books = s23._books(cap)
    edge = s23._alloc_edge()
    for pp in (s23._ALLOC_BELOW_PP, s23._ALLOC_WITHIN_PP):
        d = s23._econ_move(books["A"], s23._alloc_target(pp, cap), "pendle",
                           apy_pct=edge)
        assert d.decision == "ACT", (pp, d.decision, list(d.reasons))
        assert float(d.gain_pp) >= 0.50, (pp, d.gain_pp)


def test_allocation_difference_quantity_is_not_asked_by_any_door():
    """Разница РАСКЛАДКИ не спрашивается: 2 пп проходят ровно как 10 пп."""
    report = s23.census()
    row = next(r for r in report["values"]
               if r["value"] == "target allocation difference")
    assert row["existence"] == ABSENT
    assert row["declaration"] == "nothing_to_declare"
    quantity = [r for r in row["records"] if r["axis"] == "quantity"]
    assert quantity, row
    assert not any(r["changed"] for r in quantity), quantity
    # Отказ от делегирования ПЕЧАТАЕТСЯ: это утверждение, не умолчание.
    assert row["delegation_refused"].strip()


def test_the_dust_dial_refuses_a_large_aggregate_for_the_wrong_reason():
    """Агрегат внутри полосы §23 отклоняется ПО ПЫЛИ У НОГ, а не по агрегату.

    Это и есть доказательство, что существующая ручка мерит НОГУ, а не разницу
    раскладки. Порванное звено НАЗВАНО: ``min_leg_frac``.
    """
    cap = s23._scene_capital()
    books = s23._books(cap)
    target = {"aave_v3": 0.30 * cap}
    apy = dict(s23._alloc_edge())
    for i in range(20):
        target["p{:02d}".format(i)] = 0.005 * cap - 1.0
        apy["p{:02d}".format(i)] = s23._ALLOC_SCENE_EDGE_PCT
    d = s23._econ_move(books["A"], target, "pendle", apy_pct=apy)
    assert d.decision != "ACT"
    # Причина названа ПО ИМЕНИ (структурный ключ вердикта), не подстрокой прозы.
    assert any(str(r).startswith("proposal_has_unexecuted_legs")
               for r in d.reasons), list(d.reasons)


# ─────────────── достижимость: стартовое значение переворачивает ─────────────

def test_reach_kinds_vocabulary_is_closed():
    assert UNMEASURED in REACH_KINDS
    assert "reachable_verdict_flipped" in REACH_KINDS
    assert "reachable_no_flip" in REACH_KINDS


def test_s23_cooldown_flips_the_live_door_and_the_baseline_really_blocks():
    """Сцена ПОСТРОЕНА: без BLOCK в основании «переворот» был бы случайным.

    Порванное звено НАЗВАНО: ``min_hold`` у ``churn_damper``.
    """
    out = s23._reach_cooldown_on_live_door()
    assert out["kind"] == "reachable_verdict_flipped", out
    cap = s23._scene_capital()
    books = s23._books(cap)
    trades = [s23._trade(0.5, 1_000.0, s23.SCENE_NOW)]
    base = s23._damper_move(books["A"], books["B"], trades)
    # Основание обязано отказывать ИМЕННО сроком удержания, а не чем попало.
    assert base.decision == "BLOCK"
    assert base.reason == "min_hold"


def test_turnover_scene_is_bound_by_the_daily_dial_and_not_a_neighbour():
    """Сцена ИЗОЛИРУЕТ дневную ручку — иначе «инертна» спорило бы с §22.

    Это ВТОРАЯ моя ошибка замера, закреплённая тестом: ход на 22 пп отклонялся
    потолком ОДНОГО ХОДА и абсолютной суммой, то есть соседями.
    Порванное звено НАЗВАНО: ``max_turnover_per_day``.
    """
    out = s23._reach_turnover_on_price_door()
    assert out["kind"] == "reachable_verdict_flipped", out
    cap = s23._scene_capital()
    books = s23._books(cap)
    base = s23._econ_move(books["A"], books["B"], "pendle",
                          turnover_today_usd=8_000.0)
    assert base.decision != "ACT"
    reasons = [str(r) for r in base.reasons]
    assert any(r.startswith("day_turnover_over_budget") for r in reasons), reasons
    # Ни один СОСЕДНИЙ потолок связывать не имеет права — иначе изоляции нет.
    for neighbour in ("move_turnover_over_budget", "move_amount_over_cap",
                      "week_turnover_over_budget"):
        assert not any(r.startswith(neighbour) for r in reasons), (neighbour, reasons)


def test_a_broken_reach_scene_is_unmeasured_not_safe(monkeypatch):
    """Упавшая сцена ⇒ НЕ ИЗМЕРЕНО, а не «переворота нет».

    Порванное звено НАЗВАНО: ``_damper_move``.
    """
    def boom(*a, **kw):
        raise RuntimeError("дверь живого пути не спрошена")

    monkeypatch.setattr(s23, "_damper_move", boom)
    out = s23._reach_cooldown_on_live_door()
    assert out["kind"] == UNMEASURED
    assert out["why"].strip()


# ──────────────────────────── вердикт отчёта ────────────────────────────────

def test_verdict_code_zero_only_when_every_value_is_declared_shadow():
    clean = {
        "vocab_errors": [], "control": {"passed": True},
        "tally": {k: 0 for k in DECLARATION_KINDS},
        "reachability": {"a": {"kind": "unreachable_by_construction"}},
    }
    clean["tally"]["shadow_start_declared"] = 6
    assert s23.verdict_code(clean) == 0


@pytest.mark.parametrize("mutate,expected", [
    ({"tally": {"production_declared": 1}}, 1),
    ({"tally": {"undistinguished": 1}}, 1),
    ({"tally": {"nothing_to_declare": 1}}, 1),
    ({"tally": {UNMEASURED: 1}}, 2),
    ({"reachability": {"a": {"kind": "reachable_verdict_flipped"}}}, 1),
    ({"reachability": {"a": {"kind": UNMEASURED}}}, 2),
    ({"control": {"passed": False}}, 2),
    ({"vocab_errors": ["x"]}, 2),
])
def test_verdict_code_positive_controls(mutate, expected):
    report = {
        "vocab_errors": [], "control": {"passed": True},
        "tally": dict({k: 0 for k in DECLARATION_KINDS},
                      shadow_start_declared=6),
        "reachability": {"a": {"kind": "unreachable_by_construction"}},
    }
    for key, val in mutate.items():
        if key == "tally":
            report["tally"] = dict({k: 0 for k in DECLARATION_KINDS},
                                   shadow_start_declared=5, **val)
        else:
            report[key] = val
    assert s23.verdict_code(report) == expected


# ───────────────────────── живой замер и его форма ──────────────────────────

def test_live_report_is_a_finding_with_three_absent_and_three_production():
    """Сегодняшний замер: 0 стартовых · 3 production · 3 объявлять нечем."""
    report = s23.census()
    assert report["control"]["passed"] is True, report["control"]
    t = report["tally"]
    assert t["shadow_start_declared"] == 0
    assert t["production_declared"] == 3
    assert t["nothing_to_declare"] == 3
    assert t[UNMEASURED] == 0
    assert t["undistinguished"] == 0
    assert s23.verdict_code(report) == 1
    # Оба сцены достижимости обязаны быть ПОСТРОЕНЫ, а не пропущены.
    assert set(report["reachability"]) == {"cooldown_on_live_door",
                                           "turnover_on_price_door"}
    for scene in report["reachability"].values():
        assert scene["kind"] == "reachable_verdict_flipped", scene


def test_report_names_what_it_does_not_claim():
    """«Не измерено» обязано быть НАЗВАНО, а не читаться как ноль."""
    report = s23.census()
    assert len(report["not_claimed"]) >= 2
    for line in report["not_claimed"]:
        assert line.strip()


def test_render_does_not_raise_on_any_outcome():
    for mutate in ({}, {"vocab_errors": ["x"]},
                   {"control": {"passed": False, "reason": "r",
                                "healthy_baseline": {}}}):
        report = s23.census()
        report.update(mutate)
        assert s23.render(report)


def test_the_instrument_writes_nothing_and_reads_no_live_data(tmp_path):
    """ADVISORY по построению: ни одного файла в дереве прибор не создаёт."""
    before = sorted(p.name for p in tmp_path.iterdir())
    s23.census(root=tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == before
