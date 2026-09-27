#!/usr/bin/env python3
"""Приёмка прибора §49 `Persistence` (цикл #702, ADR-481).

Каждый тест — либо воспроизведение НАСТОЯЩЕГО исхода журнала денег, либо
контроль порванного звена в обратную сторону, и порванное звено названо в имени
теста. Проба, проходящая подстрокой или на полуконтуре, тут не годится
(`.claude/rules/acceptance.md` п. 3).

**Часы ИНЪЕКТИРОВАНЫ, и обе стороны закреплены.** Прибор судит о ВОЗРАСТЕ ходов,
поэтому стенные часы сделали бы сцену смертной от календаря
(`.claude/rules/deployment.md`, приём №1). Единственный литерал времени здесь —
``ANCHOR``; из него выведены ВСЕ дни ряда (:func:`day`), все отметки ходов
(:func:`ts`) и он же передаётся прибору аргументом ``now=``. Сдвиг календаря не
меняет ни одного вердикта этой батареи.
"""
# FROZEN-DATE-OK: injected-clock — единственный литерал ANCHOR передаётся
# run_census(..., now=ANCHOR), и от него же выведены все дни ряда (day()) и
# отметки ходов (ts()); настенных часов сцена не касается ни в одном тесте.
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.monitoring import gain_persistence_census as gpc

ANCHOR = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)  # якорь сцены, не календарь


class Dials:
    """Колонка порогов владельца, поданная ВХОДОМ.

    Нужна, чтобы проверить: границы пород берутся отсюда, а не из тела прибора.
    """

    __dataclass_fields__ = {          # прибор перечисляет ручки по этому полю
        "min_hold_days": None, "max_payback_days": None,
        "min_leg_frac": None, "mode": None, "version": None,
    }

    def __init__(self, min_hold_days=3, max_payback_days=30.0,
                 min_leg_frac=0.005, mode="paper", version="vTEST"):
        self.min_hold_days = min_hold_days
        self.max_payback_days = max_payback_days
        self.min_leg_frac = min_leg_frac
        self.mode = mode
        self.version = version


def day(offset: int, now: datetime = ANCHOR) -> str:
    """День ряда как строка, выведенная из якоря (не литерал)."""
    return (now + timedelta(days=offset)).date().isoformat()


def ts(offset: int, now: datetime = ANCHOR) -> str:
    return (now + timedelta(days=offset)).isoformat()


def write_scene(tmp_path: Path, *, moves, series, decisions=None) -> Path:
    """Одноразовый каталог данных. Живое `data/` тесты не видят по построению.

    Ряд записывается в ТОЙ ЖЕ форме, что у настоящего артефакта — перечнем пар
    ``[день, ставка]``. Форма — часть сцены: словарь вместо перечня прибор
    честно прочитал бы как «точек нет», и вся батарея измеряла бы третий исход
    вместо породы (поймано при первом прогоне).
    """
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "trades.json").write_text(json.dumps(moves), encoding="utf-8")
    as_points = {key: [[d, r] for d, r in sorted(byday.items())]
                 for key, byday in series.items()}
    (data / gpc.SERIES_NAME).write_text(
        json.dumps({"series": as_points}), encoding="utf-8")
    rows = decisions if decisions is not None else [{"gates": {
        "cooldown_ok": True, "gain_above_band": True,
        "payback_within_horizon": True}}]
    (data / gpc.DECISIONS_NAME).write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return data


def move(trade_id: str, offset: int, frm: dict, to: dict) -> dict:
    return {"trade_id": trade_id, "ts": ts(offset),
            "from_allocation": frm, "to_allocation": to}


def rates_from(first_offset: int, values) -> dict:
    """Точки ряда как {день: ставка}, начиная с указанного смещения от якоря."""
    return {day(first_offset + i): float(v) for i, v in enumerate(values)}


# ── 1. пороги: числа владельца, третий исход без них ────────────────────────

class TestPolicy:
    def test_dials_come_from_the_owner_column_not_from_the_module(self):
        pol = gpc.load_policy(Dials(min_hold_days=7, max_payback_days=99.0))
        assert pol["measured"] and pol["min_hold_days"] == 7
        assert pol["max_payback_days"] == 99.0
        assert pol["version"] == "vTEST"

    def test_full_dial_list_is_reported_so_the_claim_is_checkable(self):
        pol = gpc.load_policy(Dials())
        assert "min_hold_days" in pol["dials"] and "max_payback_days" in pol["dials"]
        assert not [d for d in pol["dials"] if "persist" in d], (
            "если ручка про устойчивость появится, утверждение прибора обязано "
            "перестать быть верным — этот контроль и есть её приёмка")

    def test_missing_dial_is_a_third_outcome_not_a_substituted_default(self):
        class Broken:
            pass
        pol = gpc.load_policy(Broken())
        assert pol["measured"] is False
        assert "НЕ ИЗМЕРЕНО" in pol["reason"]

    def test_unavailable_column_refuses_instead_of_hardcoding(self, monkeypatch):
        import builtins
        real = builtins.__import__

        def boom(name, *a, **kw):
            if name.endswith("rebalance_economics"):
                raise ImportError("колонки нет")
            return real(name, *a, **kw)

        monkeypatch.setattr(builtins, "__import__", boom)
        pol = gpc.load_policy(None)
        assert pol["measured"] is False and "Не hardcode" in pol["reason"]


# ── 2. ряд ставок: отсутствие материала — не «преимущество жило» ─────────────

class TestSeries:
    def test_missing_series_file_is_a_third_outcome(self, tmp_path):
        out = gpc.read_series(tmp_path)
        assert out["measured"] is False
        assert "мерить НЕЧЕМ" in out["reason"]

    def test_unreadable_series_names_the_parse_error(self, tmp_path):
        (tmp_path / gpc.SERIES_NAME).write_text("{не json", encoding="utf-8")
        out = gpc.read_series(tmp_path)
        assert out["measured"] is False and "нечитаем" in out["reason"]

    def test_series_without_the_section_is_not_an_empty_measurement(self, tmp_path):
        (tmp_path / gpc.SERIES_NAME).write_text(
            json.dumps({"generated_at": "x"}), encoding="utf-8")
        out = gpc.read_series(tmp_path)
        assert out["measured"] is False and "series" in out["reason"]

    def test_non_numeric_point_is_absence_of_observation_not_a_zero(self, tmp_path):
        (tmp_path / gpc.SERIES_NAME).write_text(json.dumps({"series": {
            "a": [[day(0), None], [day(1), True], [day(2), 4.0]]}}),
            encoding="utf-8")
        out = gpc.read_series(tmp_path)
        assert out["measured"] and out["series"]["a"] == {day(2): 4.0}, (
            "None и True наблюдениями не являются; превратить их в 0.0 значило бы "
            "выдать молчание фида за ставку нуль"
        )


# ── 3. словарь гейтов: поведенческая популяция ──────────────────────────────

class TestDecisionGates:
    def test_vocabulary_is_collected_over_all_recorded_decisions(self, tmp_path):
        path = tmp_path / gpc.DECISIONS_NAME
        path.write_text("\n".join(json.dumps(r) for r in [
            {"gates": {"a": True}}, {"gates": {"b": False}}]), encoding="utf-8")
        out = gpc.read_decision_gates(tmp_path)
        assert out["measured"] and out["gates"] == ["a", "b"]
        assert out["decisions"] == 2

    def test_missing_journal_is_a_third_outcome_not_an_empty_vocabulary(self, tmp_path):
        out = gpc.read_decision_gates(tmp_path)
        assert out["measured"] is False and "НЕ ИЗМЕРЕН" in out["reason"]

    def test_journal_of_unreadable_lines_only_is_a_third_outcome(self, tmp_path):
        (tmp_path / gpc.DECISIONS_NAME).write_text("{битая\n{тоже\n", encoding="utf-8")
        out = gpc.read_decision_gates(tmp_path)
        assert out["measured"] is False and "нечитаем" in out["reason"]


# ── 4. ноги хода и псевдонимы ───────────────────────────────────────────────

class TestLegs:
    def test_rename_without_alias_looks_like_a_move_that_never_happened(self):
        m = {"from": {"old": 20000.0}, "to": {"new": 20000.0}}
        bare = gpc.move_legs(m, {}, 500.0)
        assert bare["inflow"] == {"new": 20000.0}, "без псевдонима это «ход»"
        aliased = gpc.move_legs(m, {"old": "new"}, 500.0)
        assert aliased["inflow"] == {} and aliased["outflow"] == {}, (
            "с измеренным псевдонимом переименование перестаёт быть ходом")

    def test_leg_below_materiality_is_not_a_leg(self):
        m = {"from": {"a": 1000.0}, "to": {"a": 1400.0, "b": 100.0}}
        legs = gpc.move_legs(m, {}, 500.0)
        assert legs["inflow"] == {} and legs["outflow"] == {}

    def test_partial_observation_yields_none_not_a_partial_average(self):
        series = {"a": {day(1): 10.0}}
        assert gpc._weighted_rate({"a": 100.0, "b": 100.0}, series, day(1)) is None
        assert gpc._weighted_rate({"a": 100.0}, series, day(1)) == 10.0


# ── 5. срок жизни преимущества: воспроизведение исходов ─────────────────────

def lifetime(moves, series, *, aliases=None, min_usd=500.0):
    days = sorted({d for byday in series.values() for d in byday})
    return gpc.advantage_lifetime(
        {"trade_id": moves["trade_id"],
         "ts": datetime.fromisoformat(moves["ts"]),
         "from": moves["from_allocation"], "to": moves["to_allocation"]},
        series, days, aliases or {}, min_usd)


class TestLifetime:
    def _series(self, dest_rates, src_rates):
        return {"dest": rates_from(0, dest_rates), "src": rates_from(0, src_rates)}

    def test_advantage_that_holds_three_days_then_dies_lives_three_days(self):
        # исход T008: преимущество +0.58 пп, три дня, затем знак меняется
        series = self._series([5.0, 5.0, 5.0, 5.0, 3.0], [4.0, 4.0, 4.0, 4.0, 4.0])
        out = lifetime(move("T", 0, {"src": 60000.0}, {"dest": 60000.0}), series)
        assert out["advantage_days"] == 3
        assert out["advantage_at_move_pp"] == pytest.approx(1.0)
        assert "преимущество стало" in out["stopped_because"]

    def test_advantage_negative_on_the_first_forward_day_lives_zero_days(self):
        # исход T009/T014/T025: назавтра преимущества уже нет
        series = self._series([3.0, 2.0], [4.0, 4.0])
        out = lifetime(move("T", 0, {"src": 40000.0}, {"dest": 40000.0}), series)
        assert out["advantage_days"] == 0
        assert out["advantage_at_move_pp"] == pytest.approx(-1.0)

    def test_key_without_a_series_is_unmeasured_and_names_the_key(self):
        # исход T033: $20 000 в pendle, ряда у ключа нет вовсе
        series = {"src": {day(0): 4.0, day(1): 4.0}}
        out = lifetime(move("T", 0, {"src": 20000.0}, {"pendle": 20000.0}), series)
        assert out["species"] == gpc.SPECIES_UNMEASURED
        assert "pendle" in out["reason"] and "даже в принципе" in out["reason"]

    def test_move_before_the_series_begins_is_unmeasured_and_names_the_first_day(self):
        series = self._series([5.0, 5.0], [4.0, 4.0])
        out = lifetime(move("T", -30, {"src": 1000.0}, {"dest": 1000.0}), series)
        assert out["species"] == gpc.SPECIES_UNMEASURED
        assert day(0) in out["reason"]

    def test_no_forward_day_is_unmeasured_not_zero_lifetime(self):
        series = self._series([5.0], [4.0])
        out = lifetime(move("T", 0, {"src": 1000.0}, {"dest": 1000.0}), series)
        assert out["species"] == gpc.SPECIES_UNMEASURED
        assert "форвардных дней" in out["reason"]

    def test_gap_in_the_series_stops_the_count_and_is_never_interpolated(self):
        series = {"dest": {day(0): 5.0, day(1): 5.0, day(3): 5.0},
                  "src": {day(0): 4.0, day(1): 4.0, day(2): 4.0, day(3): 4.0}}
        out = lifetime(move("T", 0, {"src": 1000.0}, {"dest": 1000.0}), series)
        assert out["advantage_days"] == 1, (
            "день без наблюдения у одной ноги обрывает счёт; продлить его "
            "последним известным числом значило бы выдумать наблюдение")
        assert "не у всех ног" in out["stopped_because"]

    def test_equal_rates_mean_the_reason_is_gone_not_that_it_survives(self):
        """Преимущество РОВНО ноль — причина хода исчезла, а не «держится».

        Контроль на границу знака: `>= 0` вместо `> 0` объявил бы день с равными
        ставками днём жизни преимущества, то есть выдал бы отсутствие выгоды за
        выгоду. Выжившая мутация первого прогона — это она.
        """
        series = self._series([4.0, 4.0], [4.0, 4.0])
        out = lifetime(move("T", 0, {"src": 40000.0}, {"dest": 40000.0}), series)
        assert out["advantage_days"] == 0
        assert "+0.0000 пп" in out["stopped_because"]

    def test_a_move_that_transfers_nothing_is_not_a_persistence_finding(self):
        series = self._series([5.0, 5.0], [4.0, 4.0])
        out = lifetime(move("T", 0, {"dest": 1000.0}, {"dest": 1000.0}), series)
        assert out["species"] == gpc.SPECIES_UNMEASURED
        assert "не переносит деньги" in out["reason"]


# ── 6. породы: границы — числа владельца ────────────────────────────────────

class TestClassify:
    def _item(self, lived, exhausted=False):
        return {"advantage_days": lived, "species": None,
                "exhausted_series": exhausted}

    def test_shorter_than_minimum_hold_is_its_own_species(self):
        out = gpc.classify(self._item(2), 3, 30.0)
        assert out["species"] == gpc.SPECIES_BEFORE_HOLD

    def test_shorter_than_payback_horizon_is_a_different_species(self):
        out = gpc.classify(self._item(10), 3, 30.0)
        assert out["species"] == gpc.SPECIES_WITHIN_PAYBACK

    def test_outliving_the_horizon_is_no_finding(self):
        out = gpc.classify(self._item(30), 3, 30.0)
        assert out["species"] == gpc.SPECIES_OUTLIVED

    def test_lifetime_exactly_equal_to_the_minimum_hold_is_not_shorter_than_it(self):
        """Граница РОВНО на ручке владельца: `<` против `<=`.

        Срок, равный минимальному удержанию, требование владельца выполнил —
        назвать его «короче удержания» значило бы сместить породу на один день
        и посчитать исполненное правило нарушенным. Выжившая мутация первого
        прогона — это она.
        """
        out = gpc.classify(self._item(3), 3, 30.0)
        assert out["species"] == gpc.SPECIES_WITHIN_PAYBACK

    def test_lifetime_exactly_equal_to_the_payback_horizon_outlived_it(self):
        out = gpc.classify(self._item(30), 3, 30.0)
        assert out["species"] == gpc.SPECIES_OUTLIVED

    def test_species_boundary_follows_the_injected_dial_not_a_literal_three(self):
        assert gpc.classify(self._item(5), 7, 30.0)["species"] == gpc.SPECIES_BEFORE_HOLD
        assert gpc.classify(self._item(5), 3, 30.0)["species"] == gpc.SPECIES_WITHIN_PAYBACK

    def test_series_exhausted_before_the_horizon_is_unmeasured_not_outlived(self):
        out = gpc.classify(self._item(9, exhausted=True), 3, 30.0)
        assert out["species"] == gpc.SPECIES_UNMEASURED, (
            "преимущество не умерло — кончился ряд; назвать это находкой значило бы "
            "выдать «не измерено» за вред, а «пережил» — за измеренный успех")
        assert "НЕ ИЗМЕРЕНО" in out["reason"]

    def test_unmeasured_item_is_passed_through_untouched(self):
        item = {"species": gpc.SPECIES_UNMEASURED, "reason": "ряда нет"}
        assert gpc.classify(item, 3, 30.0) is item


# ── 7. перепись целиком: вердикт судит настоящее ────────────────────────────

def scene_with_dead_advantage(tmp_path, *, move_offset):
    """Ход, преимущество которого умирает назавтра, на заданном возрасте."""
    series = {"dest": {day(i): 3.0 for i in range(-40, 1)},
              "src": {day(i): 4.0 for i in range(-40, 1)}}
    series["dest"][day(move_offset)] = 5.0
    moves = [move("T1", move_offset, {"src": 40000.0}, {"dest": 40000.0})]
    return write_scene(tmp_path, moves=moves, series=series)


class TestCensus:
    def test_fresh_dead_advantage_inside_the_owner_horizon_is_critical(self, tmp_path):
        data = scene_with_dead_advantage(tmp_path, move_offset=-5)
        rep = gpc.run_census(data, now=ANCHOR, params=Dials())
        assert rep["status"] == gpc.STATUS_CRITICAL
        assert rep["counts"]["recent_dead_within_horizon"] == 1

    def test_old_dead_advantage_is_warning_so_quiet_is_not_never(self, tmp_path):
        data = scene_with_dead_advantage(tmp_path, move_offset=-35)
        rep = gpc.run_census(data, now=ANCHOR, params=Dials())
        assert rep["status"] == gpc.STATUS_WARNING
        assert rep["counts"]["died_before_min_hold"] == 1
        assert rep["counts"]["recent_dead_within_horizon"] == 0
        assert "НЕ значит" in " ".join(gpc.format_report(rep))

    def test_verdict_window_is_the_owner_dial_not_a_literal_thirty(self, tmp_path):
        data = scene_with_dead_advantage(tmp_path, move_offset=-35)
        rep = gpc.run_census(data, now=ANCHOR, params=Dials(max_payback_days=90.0))
        assert rep["status"] == gpc.STATUS_CRITICAL

    def test_advantage_that_outlives_the_horizon_is_ok(self, tmp_path):
        series = {"dest": {day(i): 9.0 for i in range(-40, 1)},
                  "src": {day(i): 4.0 for i in range(-40, 1)}}
        data = write_scene(
            tmp_path, moves=[move("T1", -40, {"src": 40000.0}, {"dest": 40000.0})],
            series=series)
        rep = gpc.run_census(data, now=ANCHOR, params=Dials())
        assert rep["status"] == gpc.STATUS_OK
        assert rep["counts"]["outlived_horizon"] == 1

    def test_nothing_measurable_is_unmeasured_not_ok(self, tmp_path):
        series = {"src": {day(i): 4.0 for i in range(-10, 1)}}
        data = write_scene(
            tmp_path, moves=[move("T1", -5, {"src": 40000.0}, {"pendle": 40000.0})],
            series=series)
        rep = gpc.run_census(data, now=ANCHOR, params=Dials())
        assert rep["measured"] is False
        assert rep["status"] == gpc.STATUS_UNMEASURED
        assert "НЕ ИЗМЕРЕН ни разу" in rep["reason"]

    def test_missing_journal_refuses_before_touching_the_series(self, tmp_path):
        data = tmp_path / "data"
        data.mkdir()
        rep = gpc.run_census(data, now=ANCHOR, params=Dials())
        assert rep["measured"] is False and "журнал ходов" in rep["reason"]

    def test_unmeasured_moves_are_counted_and_priced_separately(self, tmp_path):
        series = {"dest": {day(i): 3.0 for i in range(-10, 1)},
                  "src": {day(i): 4.0 for i in range(-10, 1)}}
        series["dest"][day(-5)] = 5.0
        moves = [move("T1", -5, {"src": 40000.0}, {"dest": 40000.0}),
                 move("T2", -4, {"dest": 20000.0}, {"pendle": 20000.0})]
        data = write_scene(tmp_path, moves=moves, series=series)
        rep = gpc.run_census(data, now=ANCHOR, params=Dials())
        assert rep["counts"]["unmeasured_no_material"] == 1
        assert rep["usd_unmeasured_recent"] == 20000.0
        assert rep["counts"]["measurable"] == 1

    def test_a_top_up_is_not_counted_as_money_we_could_not_measure(self, tmp_path):
        """Ход, ничего не переносящий, НЕ идёт в слепые доллары.

        Пополнение (только вход, выхода нет) преимущества не имеет по
        построению — у него нет источника, с которым сравнивать. Смешать его со
        «не хватило материала» значило бы завысить сумму, про которую прибор
        говорит «проверить нельзя», то есть выдумать слепоту.
        """
        series = {"dest": {day(i): 3.0 for i in range(-10, 1)},
                  "src": {day(i): 4.0 for i in range(-10, 1)}}
        series["dest"][day(-5)] = 5.0
        moves = [move("T1", -5, {"src": 40000.0}, {"dest": 40000.0}),
                 move("T2", -4, {"dest": 40000.0}, {"dest": 40000.0, "src": 9000.0})]
        data = write_scene(tmp_path, moves=moves, series=series)
        rep = gpc.run_census(data, now=ANCHOR, params=Dials())
        assert rep["counts"]["not_a_transfer"] == 1
        assert rep["counts"]["unmeasured_no_material"] == 0
        assert rep["usd_unmeasured_recent"] == 0.0

    def test_advantage_absent_already_at_the_move_is_its_own_count(self, tmp_path):
        series = {"dest": {day(i): 3.0 for i in range(-10, 1)},
                  "src": {day(i): 4.0 for i in range(-10, 1)}}
        data = write_scene(
            tmp_path, moves=[move("T1", -5, {"src": 40000.0}, {"dest": 40000.0})],
            series=series)
        rep = gpc.run_census(data, now=ANCHOR, params=Dials())
        assert rep["counts"]["advantage_negative_at_move"] == 1
        assert "ПРЕИМУЩЕСТВА НЕ БЫЛО УЖЕ В ДЕНЬ ХОДА" in " ".join(
            gpc.format_report(rep))

    def test_a_same_day_round_trip_is_one_decision_not_two(self, tmp_path):
        """Туда-обратно за один день — ОДНО решение, и знаменатель это знает.

        Без замера читатель прочтёт N записей как N решений. Породу это не
        меняет (преимущество всё равно умерло), меняется только число, которым
        находку честно называть.
        """
        # Сцена устроена так, чтобы УМЕРЛИ ОБЕ половины — иначе проверяемая
        # ветка недостижима, и тест «проходил» бы мимо предмета (поймано при
        # первом прогоне: у пары одна сторона всегда выгодна, если ставки не
        # пересекаются). Ставки пересекаются на третий день.
        series = {"dest": dict({day(i): 3.0 for i in range(-10, 1)},
                              **{day(-3): 6.0, day(-2): 6.0}),
                  "src": {day(i): 4.0 for i in range(-10, 1)}}
        moves = [move("T1", -5, {"src": 40000.0}, {"dest": 40000.0}),
                 move("T2", -5, {"dest": 40000.0}, {"src": 40000.0})]
        data = write_scene(tmp_path, moves=moves, series=series)
        rep = gpc.run_census(data, now=ANCHOR, params=Dials())
        assert rep["counts"]["measurable"] == 2, "обе половины обязаны быть измеримы"
        assert rep["counts"]["dead_in_same_day_round_trips"] == 2
        assert rep["counts"]["independent_dead_decisions"] == 1
        assert "СЧИТАТЬ РЕШЕНИЯ, А НЕ ЗАПИСИ" in " ".join(gpc.format_report(rep))

    def test_moves_on_different_days_are_not_called_a_round_trip(self, tmp_path):
        """Контроль в обратную сторону: возврат ЧЕРЕЗ ДНИ — два решения.

        Схлопнуть его в одно значило бы занизить знаменатель, то есть спрятать
        половину находок под видом аккуратности.
        """
        series = {"dest": dict({day(i): 3.0 for i in range(-10, 1)},
                              **{day(-3): 6.0, day(-2): 6.0}),
                  "src": {day(i): 4.0 for i in range(-10, 1)}}
        moves = [move("T1", -6, {"src": 40000.0}, {"dest": 40000.0}),
                 move("T2", -5, {"dest": 40000.0}, {"src": 40000.0})]
        data = write_scene(tmp_path, moves=moves, series=series)
        rep = gpc.run_census(data, now=ANCHOR, params=Dials())
        assert rep["counts"]["measurable"] == 2
        assert rep["counts"]["dead_in_same_day_round_trips"] == 0
        assert rep["counts"]["independent_dead_decisions"] == 2

    def test_blind_spot_is_reported_even_when_the_book_is_quiet(self, tmp_path):
        series = {"dest": {day(i): 9.0 for i in range(-40, 1)},
                  "src": {day(i): 4.0 for i in range(-40, 1)}}
        data = write_scene(
            tmp_path, moves=[move("T1", -40, {"src": 40000.0}, {"dest": 40000.0})],
            series=series)
        rep = gpc.run_census(data, now=ANCHOR, params=Dials())
        assert rep["status"] == gpc.STATUS_OK
        assert rep["blind_spot_demonstrated"] is True, (
            "слепота — утверждение о ПОСТРОЕНИИ, и от тишины книги она не гаснет")
        assert "СЛЕПОТА ПО ПОСТРОЕНИЮ" in " ".join(gpc.format_report(rep))

    def test_gate_vocabulary_failure_is_named_and_not_silently_empty(self, tmp_path):
        data = scene_with_dead_advantage(tmp_path, move_offset=-5)
        (data / gpc.DECISIONS_NAME).unlink()
        rep = gpc.run_census(data, now=ANCHOR, params=Dials())
        assert rep["blind_spot"]["recorded_decision_gates"] is None
        assert rep["blind_spot"]["gate_vocabulary_unmeasured"]
        assert "СЛОВАРЬ ГЕЙТОВ НЕ ИЗМЕРЕН" in " ".join(gpc.format_report(rep))


# ── 8. пересечение населений с соседом ──────────────────────────────────────

class TestOverlap:
    def test_missing_neighbour_artifact_is_a_third_outcome(self, tmp_path):
        out = gpc.oscillation_overlap([], tmp_path)
        assert out["measured"] is False
        assert "НЕ «они не пересекаются»" in out["reason"]

    def test_shared_moves_are_measured_from_the_artifact_not_assumed(self, tmp_path):
        (tmp_path / gpc.OSCILLATION_ARTIFACT).write_text(json.dumps(
            {"returns": [{"from_trade": "T9", "to_trade": "T10"}]}), encoding="utf-8")
        items = [{"trade_id": "T9", "species": gpc.SPECIES_BEFORE_HOLD},
                 {"trade_id": "T7", "species": gpc.SPECIES_WITHIN_PAYBACK}]
        out = gpc.oscillation_overlap(items, tmp_path)
        assert out["measured"] and out["shared"] == ["T9"]

    def test_unreadable_neighbour_artifact_is_named_not_counted_as_zero(self, tmp_path):
        (tmp_path / gpc.OSCILLATION_ARTIFACT).write_text("{битый", encoding="utf-8")
        out = gpc.oscillation_overlap([], tmp_path)
        assert out["measured"] is False and "нечитаем" in out["reason"]


# ── 9. состав записи хода: схема мерится, а не помнится ─────────────────────

class TestCostFields:
    def test_executed_move_carrying_no_cost_is_measured_as_such(self, tmp_path):
        (tmp_path / "trades.json").write_text(
            json.dumps([{"trade_id": "T1", "diff_usd": 1.0}]), encoding="utf-8")
        out = gpc._cost_fields_present(tmp_path)
        assert out["measured"] and out["carries_cost"] is False

    def test_a_cost_field_appearing_later_is_noticed_the_same_day(self, tmp_path):
        (tmp_path / "trades.json").write_text(
            json.dumps([{"trade_id": "T1", "cost_usd": 12.0}]), encoding="utf-8")
        out = gpc._cost_fields_present(tmp_path)
        assert out["carries_cost"] is True and out["found"] == ["cost_usd"]

    def test_unreadable_journal_is_a_third_outcome(self, tmp_path):
        out = gpc._cost_fields_present(tmp_path)
        assert out["measured"] is False and "НЕ ИЗМЕРЕН" in out["reason"]


# ── 10. артефакт: контроль читает ДИСК, а не вывод ──────────────────────────

class TestArtifact:
    def test_artifact_is_actually_written_and_reads_back(self, tmp_path):
        data = scene_with_dead_advantage(tmp_path, move_offset=-5)
        rep = gpc.run_census(data, now=ANCHOR, params=Dials())
        gpc.save_artifact(rep, data)
        on_disk = json.loads((data / gpc.ARTIFACT_NAME).read_text(encoding="utf-8"))
        assert on_disk["status"] == rep["status"], (
            "контроль обязан читать ДИСК: отказ записи неотличим от успеха у "
            "всякого, кто смотрит на вывод ступени (настоящая поломка #701)")

    def test_stage_leaves_an_artifact_even_on_the_third_outcome(self, tmp_path):
        (tmp_path / "data").mkdir()
        out = gpc.run(root=str(tmp_path), now=ANCHOR)
        assert out["measured"] is False
        doc = json.loads(
            (tmp_path / "data" / gpc.ARTIFACT_NAME).read_text(encoding="utf-8"))
        assert doc["status"] == gpc.STATUS_UNMEASURED, (
            "без артефакта шаг 0-офис не отличит «не измерено» от «ступень не "
            "запускалась»")


# ── 11. отчёт и коды возврата ───────────────────────────────────────────────

class TestReportAndExit:
    def test_third_outcome_is_printed_as_such(self):
        lines = gpc.format_report(
            {"measured": False, "status": gpc.STATUS_UNMEASURED, "reason": "ряда нет"})
        assert "НЕ ИЗМЕРЕНО" in lines[0] and "ряда нет" in lines[0]

    def test_exit_code_three_on_unmeasured(self, tmp_path, capsys):
        (tmp_path / "data").mkdir()
        assert gpc.main(["--data-dir", str(tmp_path / "data")]) == gpc.EXIT_UNMEASURED
        assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().out

    def test_exit_code_one_on_a_fresh_finding_and_zero_on_history(self, tmp_path,
                                                                 monkeypatch):
        """Свежая находка — ненулевой код; история печатается, но кодом не нудит."""
        fresh = scene_with_dead_advantage(tmp_path / "a", move_offset=-5)
        old = scene_with_dead_advantage(tmp_path / "b", move_offset=-35)
        real = gpc.run_census          # взять ДО подмены, иначе рекурсия
        monkeypatch.setattr(gpc, "run_census",
                            lambda data_dir, now=None, params=None:
                            real(Path(data_dir), now=ANCHOR, params=Dials()))
        assert gpc.main(["--data-dir", str(fresh)]) == 1
        assert gpc.main(["--data-dir", str(old)]) == 0


