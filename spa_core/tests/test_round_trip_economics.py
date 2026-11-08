"""Контроль прибора §14 «round trip» (ADR-957).

Каждая проверка — КОНТРОЛЬ В ОБЕ СТОРОНЫ: приборный ответ обязан меняться,
когда меняется мир, который он мерит. Проверка, никогда не видевшая обратного
исхода, украшение (`.claude/rules/deployment.md`, «Проверка сторожа сторожей»).

FROZEN-DATE-OK: injected-clock — якорь `NOW` передаётся прибору входом
(`measure(..., now=NOW)` / `probe_input_directions(..., now=NOW)`), и ОБЕ
стороны сравнения производны от него же: отметки сцен считаются от `NOW`
(`NOW - timedelta(...)`), а не берутся у стенных часов. Подпроцессов,
судящих о свежести, прибор не поднимает ни одного (ADR-897).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.analytics import round_trip_economics as rt  # noqa: E402
from spa_core.analytics.report_sections import SECTION_NAMES  # noqa: E402

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def _ledger(records):
    return [dict(r) for r in records]


def _write(tmp: Path, name: str, payload) -> None:
    (tmp / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


class ObjavlenieNesetSvoiKontrakt(unittest.TestCase):
    """Объявление прибора мерит САМО СЕБЯ (урок ADR-937)."""

    def test_contract_holds_on_the_shipped_declaration(self):
        self.assertEqual(rt.validate(), [])

    def test_unmeasured_must_not_sit_on_the_scale_of_kinds(self):
        # Обратный контроль: подмешай «не измерено» в шкалу родов — объявление
        # обязано покраснеть само, не дожидаясь чужого сторожа.
        original = rt.CHARGE_KINDS
        try:
            rt.CHARGE_KINDS = original + (rt.UNMEASURED,)
            broken = rt.validate()
        finally:
            rt.CHARGE_KINDS = original
        self.assertTrue(any("unmeasured" in b for b in broken), broken)

    def test_a_missing_forward_direction_breaks_the_contract(self):
        original = rt.INPUT_DIRECTIONS
        try:
            rt.INPUT_DIRECTIONS = tuple(d for d in original if d != "forward_looking")
            broken = rt.validate()
        finally:
            rt.INPUT_DIRECTIONS = original
        self.assertTrue(any("forward_looking" in b for b in broken), broken)

    def test_the_doubt_axis_demands_both_a_subject_and_a_control(self):
        original = rt.DOUBT_INPUTS
        try:
            rt.DOUBT_INPUTS = tuple(d for d in original if d["role"] != "control")
            broken = rt.validate()
        finally:
            rt.DOUBT_INPUTS = original
        self.assertTrue(any("контроль" in b for b in broken), broken)

    def test_a_broken_declaration_yields_UNMEASURED_not_a_clean_pass(self):
        original = rt.TERMS
        try:
            rt.TERMS = original[:2]          # владелец назвал ТРИ слагаемых
            rep = rt.measure(Path(os.devnull).parent, now=NOW)
        finally:
            rt.TERMS = original
        self.assertEqual(rep["status"], "SKIPPED")
        self.assertEqual(rep["verdict"], rt.UNMEASURED.upper())
        self.assertIn("контракт", rep["reason"])


class DverCenyNeVvezena(unittest.TestCase):
    """Отсутствие двери — НЕ ИЗМЕРЕНО, а не «слагаемых нет» (инв. #17)."""

    def test_absent_cost_door_is_a_third_outcome(self):
        original = rt.load_cost_door
        try:
            rt.load_cost_door = lambda: (None, "дверь цены не ввезена (проба)")
            rep = rt.measure(Path(os.devnull).parent, now=NOW)
        finally:
            rt.load_cost_door = original
        self.assertEqual(rep["status"], "SKIPPED")
        self.assertEqual(rep["verdict"], rt.UNMEASURED.upper())
        self.assertNotIn("round_trip", rep)


class TriSlagaemyhIVilkaKruga(unittest.TestCase):
    """Оси 1–2 на ЖИВОЙ двери цены, а не на своей копии формулы."""

    def setUp(self):
        door, why = rt.load_cost_door()
        self.assertIsNotNone(door, why)
        self.door = door

    def test_two_legs_are_priced_and_the_third_has_no_input_door(self):
        rep = rt.probe_round_trip(self.door)
        kinds = {t["term"]: t["kind"] for t in rep["terms"]}
        self.assertEqual(kinds["eventual_b_exit"], "no_input_door")
        # ЖИВОЙ ответ двери пришпилен, а не «любой из двух»: сегодня газ есть
        # ОДИН литерал на ногу, и направление цена ИГНОРИРУЕТ (замер ADR-956).
        # Расщепи литерал по направлению — проверка обязана покраснеть и
        # потребовать ПЕРЕМЕРА, а не молча согласиться (мутант м2 выжил на
        # «assertIn из двух» в первой редакции).
        self.assertTrue(rep["direction_blind"],
                        "направление стало различимо — §14 сдвинулся, перемерить ADR-957")
        self.assertEqual(kinds["a_exit"], "charged_merged")
        self.assertEqual(kinds["b_entry"], "charged_merged")
        self.assertEqual(rep["legs_priced"], 2)
        self.assertEqual(rep["leg_directions"], ["decrease", "increase"])

    def test_the_missing_summand_is_proven_by_the_real_signature(self):
        rep = rt.probe_round_trip(self.door)
        third = next(t for t in rep["terms"] if t["term"] == "eventual_b_exit")
        # Доказательство — ПОДПИСЬ настоящей двери, а не слова в докстринге.
        self.assertEqual(third["door_params"],
                         [n for n in __import__("inspect")
                          .signature(self.door["move_cost"]).parameters])
        self.assertNotIn("exit", " ".join(third["door_params"]).lower())

    def test_the_fork_is_ordered_and_strictly_above_what_the_door_charges(self):
        rep = rt.probe_round_trip(self.door)
        priced = rep["priced_cost_usd"]
        lo, hi = rep["owner_three_legs_cost_usd"], rep["round_trip_cost_usd"]
        # Нижняя граница обязана стоять на ТРЁХ ногах. Без этой проверки
        # «удвоенный оборот на той же паре ног» проходил за три ноги (мутант м3).
        self.assertEqual(rep["owner_three_legs_count"], 3)
        self.assertEqual(rep["legs_priced"] + 1, rep["owner_three_legs_count"])
        self.assertGreater(lo, priced, "три ноги владельца обязаны стоить БОЛЬШЕ двух")
        self.assertGreaterEqual(hi, lo, "верхняя граница вилки ниже нижней — вилка перевёрнута")
        self.assertGreater(rep["owner_three_legs_over_priced"], 1.0)
        self.assertGreaterEqual(rep["round_trip_over_priced"],
                                rep["owner_three_legs_over_priced"])

    def test_the_fork_follows_the_door_and_is_not_a_literal(self):
        """Обратный контроль: подорожала дверь ⇒ подорожала и вилка."""
        base = rt.probe_round_trip(self.door)
        expensive = dict(self.door)
        expensive["move_cost"] = (
            lambda legs, turnover_usd, chains, _f=self.door["move_cost"]:
            _f(legs, turnover_usd, chains) * 10.0)
        louder = rt.probe_round_trip(expensive)
        self.assertAlmostEqual(louder["priced_cost_usd"],
                               base["priced_cost_usd"] * 10.0, places=4)
        self.assertAlmostEqual(louder["owner_three_legs_cost_usd"],
                               base["owner_three_legs_cost_usd"] * 10.0, places=4)
        # Отношение при пропорциональном подорожании НЕ меняется — это и
        # доказывает, что оно считается, а не напечатано.
        self.assertAlmostEqual(louder["owner_three_legs_over_priced"],
                               base["owner_three_legs_over_priced"], places=6)

    def test_a_direction_aware_door_is_reported_as_charged_named(self):
        """Обратный контроль рода: расщепи литерал по направлению — род сменится."""
        aware = dict(self.door)

        def by_direction(legs, turnover_usd, chains, _f=self.door["move_cost"]):
            extra = sum(7.0 for leg in legs if leg.get("direction") == "decrease")
            return _f(legs, turnover_usd, chains) + extra

        aware["move_cost"] = by_direction
        rep = rt.probe_round_trip(aware)
        kinds = {t["term"]: t["kind"] for t in rep["terms"]}
        self.assertEqual(kinds["a_exit"], "charged_named")
        self.assertEqual(kinds["b_entry"], "charged_named")
        self.assertFalse(rep["direction_blind"])


class NapravlenieVhodov(unittest.TestCase):
    """Ось 3: направление МЕРИТСЯ у производителя, а не объявляется."""

    def setUp(self):
        door, why = rt.load_cost_door()
        self.assertIsNotNone(door, why)
        self.door = door
        self.producers, self.why = rt.load_history_producers()
        self.assertTrue(self.producers, self.why)

    def test_every_temporal_input_of_the_live_door_looks_backward(self):
        rep = rt.probe_input_directions(self.door, self.producers, NOW, self.why)
        self.assertEqual(rep["forward_looking"], 0,
                         "вход, обращённый вперёд, появился — §14 стал исполним, "
                         "и эта проверка обязана быть перемерена, а не поправлена")
        self.assertGreater(rep["counts"]["observed_past"], 0)
        self.assertEqual(rep["door_inputs_declared"],
                         len(__import__("inspect")
                             .signature(self.door["evaluate"]).parameters))

    def test_position_age_is_judged_as_temporal_and_not_hidden(self):
        """Первая редакция звала `position_age_days` «не временным» — это ложь."""
        rep = rt.probe_input_directions(self.door, self.producers, NOW, self.why)
        row = next(r for r in rep["inputs"] if r["input"] == "position_age_days")
        self.assertEqual(row["direction"], "observed_past")

    def test_a_producer_not_derived_from_the_recorded_past_IS_SEEN(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: без него ноль «обращённых вперёд» ничего не значит.

        Прибор, не способный присвоить род `forward_looking` НИ ОДНОМУ входу,
        отвечал бы ноль на любом дереве — то есть не мерил бы ничего (ложное
        усиление, урок ADR-940). Производитель-пустышка отдаёт одно и то же
        число при любом журнале, значит записанным прошлым не объясняется.
        """
        def not_from_the_past(trades, now):
            return {"days_since_last_move": 5.0, "days_since_last_act": 5.0,
                    "last_move_legs": None, "turnover_last_week_usd": 0.0,
                    "turnover_today_usd": 0.0}

        rep = rt.probe_input_directions(
            self.door, {"_history_from_trades": not_from_the_past}, NOW, ())
        self.assertGreater(rep["forward_looking"], 0,
                           "род `forward_looking` НЕДОСТИЖИМ — ось мерит себя")
        row = next(r for r in rep["inputs"] if r["input"] == "days_since_last_move")
        self.assertEqual(row["direction"], "forward_looking")
        self.assertTrue(rep["forward_looking_is_upper_bound"])

    def test_the_second_recorded_scene_is_what_saves_todays_turnover(self):
        """Одной записанной сцены НЕ ХВАТАЛО, и это измерено на живом производителе.

        У хода двухдневной давности оборот «за сегодня» равен нулю — то есть
        совпадает со сценой пустого журнала, и при единственной записанной сцене
        вход был бы объявлен не производным от прошлого ОШИБОЧНО.
        """
        rep = rt.probe_input_directions(self.door, self.producers, NOW, self.why)
        row = next(r for r in rep["inputs"] if r["input"] == "turnover_today_usd")
        self.assertEqual(row["direction"], "observed_past")
        self.assertIn("an_hour_ago", row["evidence"])
        self.assertNotIn("two_days_ago", row["evidence"])
        self.assertIn("an_hour_ago", rep["scenes"])

    def test_absent_producers_are_UNMEASURED_not_zero(self):
        rep = rt.measure(Path(os.devnull).parent, now=NOW)
        # Боевой путь производителей есть; подменяем загрузчик.
        original = rt.load_history_producers
        try:
            rt.load_history_producers = lambda: ({}, ["производитель не ввезён (проба)"])
            rep = rt.measure(Path(os.devnull).parent, now=NOW)
        finally:
            rt.load_history_producers = original
        self.assertEqual(rep["input_directions"]["state"], rt.UNMEASURED)
        self.assertIn("проба", rep["input_directions"]["unmeasured"])
        self.assertTrue(any("НЕ ИЗМЕРЕНО" in f for f in rep["findings"]))


class TretiyIshodUVhodaRazvorota(unittest.TestCase):
    """Ось 4: «не измерено» против «разворота нет» — ДВА разных утверждения."""

    def setUp(self):
        door, why = rt.load_cost_door()
        self.assertIsNotNone(door, why)
        self.door = door

    def test_the_control_member_of_the_class_holds(self):
        """Без подтверждённого контроля вердикт об оси НЕ ВЫДАЁТСЯ."""
        rep = rt.probe_doubt(self.door)
        self.assertTrue(rep["control_holds"])
        self.assertEqual(rep["states"]["turnover_today_usd"], "fail_closed")

    def test_the_reversal_input_resolves_doubt_in_favour_of_the_trade(self):
        rep = rt.probe_doubt(self.door)
        self.assertEqual(rep["states"]["days_since_last_move"], "fail_open")
        scenes = next(r for r in rep["inputs"]
                      if r["input"] == "days_since_last_move")["scenes"]
        # Сцена обязана РАЗЛИЧАТЬ разворот, иначе ось мерила бы себя.
        self.assertNotEqual(scenes["inside_window"]["required_gain_pp"],
                            scenes["outside_window"]["required_gain_pp"])
        # И ровно в этом предмет: «не измерено» совпало с благоприятным исходом.
        self.assertEqual(scenes["unmeasured"]["required_gain_pp"],
                         scenes["outside_window"]["required_gain_pp"])

    def test_a_fail_CLOSED_door_is_reported_as_fail_closed(self):
        """Обратный контроль: дверь, поднимающая планку на `None`, НЕ fail_open."""
        strict = dict(self.door)

        def careful(**kw):
            if kw.get("last_move_legs") and kw.get("days_since_last_move") is None:
                kw["days_since_last_move"] = 0.0   # сомнение ПРОТИВ сделки
            return self.door["evaluate"](**kw)

        strict["evaluate"] = careful
        rep = rt.probe_doubt(strict)
        self.assertEqual(rep["states"]["days_since_last_move"], "fail_closed")

    def test_a_door_that_never_escalates_is_no_effect_not_a_finding(self):
        """Сцена, не различающая разворот, обязана сказать это, а не «fail_open»."""
        flat = dict(self.door)

        def no_reversal(**kw):
            kw["last_move_legs"] = None
            return self.door["evaluate"](**kw)

        flat["evaluate"] = no_reversal
        rep = rt.probe_doubt(flat)
        self.assertEqual(rep["states"]["days_since_last_move"], "no_effect")


class NabludenieSrokaUderzhaniya(unittest.TestCase):
    """Ось 5: срок удержания выводи́тся из журнала — или НЕ ИЗМЕРЕН с причиной."""

    def test_absent_ledger_is_UNMEASURED_with_a_named_reason(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            rep = rt.holding_period_observation(Path(tmp))
        self.assertEqual(rep["state"], rt.UNMEASURED)
        self.assertIn("журнал ходов", rep["unmeasured"])

    def test_a_ledger_without_parsable_stamps_is_UNMEASURED_not_zero(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp), "trades.json", [
                {"type": "rebalance", "ts": "вчера",
                 "from_allocation": {}, "to_allocation": {"A": 10.0}}])
            rep = rt.holding_period_observation(Path(tmp))
        self.assertEqual(rep["state"], rt.UNMEASURED)
        self.assertIn("отметкой", rep["unmeasured"])
        self.assertEqual(rep["rebalances"], 1)

    def test_a_closed_holding_is_derived_with_its_length(self):
        import tempfile
        opened, closed = NOW - timedelta(days=10), NOW - timedelta(days=3)
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp), "trades.json", _ledger([
                {"type": "rebalance", "ts": opened.isoformat(),
                 "from_allocation": {}, "to_allocation": {"A": 1000.0}},
                {"type": "rebalance", "ts": closed.isoformat(),
                 "from_allocation": {"A": 1000.0}, "to_allocation": {"B": 1000.0}},
            ]))
            _write(Path(tmp), "current_positions.json", {"positions": {"B": 1000.0}})
            rep = rt.holding_period_observation(Path(tmp))
        self.assertEqual(rep["state"], "derived")
        self.assertEqual(rep["holdings_closed"], 1)
        self.assertEqual(rep["holdings_real"], 1)
        self.assertEqual(rep["holdings_below_threshold"], 0)
        self.assertAlmostEqual(rep["longest_real_days"], 7.0, places=3)
        self.assertEqual(rep["holdings_open_not_in_book"], 0)

    def test_a_same_minute_pair_is_NAMED_not_silently_filtered(self):
        """19 «удержаний» по 0.001 дн. — свойство ПИСАТЕЛЯ, и его видно."""
        import tempfile
        t0 = NOW - timedelta(days=5)
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp), "trades.json", _ledger([
                {"type": "rebalance", "ts": t0.isoformat(),
                 "from_allocation": {}, "to_allocation": {"A": 1000.0}},
                {"type": "rebalance", "ts": (t0 + timedelta(seconds=30)).isoformat(),
                 "from_allocation": {"A": 1000.0}, "to_allocation": {"B": 1000.0}},
            ]))
            rep = rt.holding_period_observation(Path(tmp))
        self.assertEqual(rep["holdings_closed"], 1)
        self.assertEqual(rep["holdings_real"], 0)
        self.assertEqual(rep["holdings_below_threshold"], 1)
        self.assertIsNone(rep["longest_real_days"])

    def test_an_unreadable_book_leaves_the_orphan_axis_None_not_zero(self):
        import tempfile
        opened = NOW - timedelta(days=4)
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp), "trades.json", _ledger([
                {"type": "rebalance", "ts": opened.isoformat(),
                 "from_allocation": {}, "to_allocation": {"A": 1000.0}}]))
            rep = rt.holding_period_observation(Path(tmp))
        self.assertEqual(rep["holdings_open"], 1)
        self.assertIsNone(rep["holdings_open_not_in_book"])
        self.assertIn("НЕ ИЗМЕРЕНО", rep["book_state"])

    def test_an_open_holding_absent_from_the_book_is_counted(self):
        import tempfile
        opened = NOW - timedelta(days=9)
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp), "trades.json", _ledger([
                {"type": "rebalance", "ts": opened.isoformat(),
                 "from_allocation": {}, "to_allocation": {"A": 1000.0, "C": 500.0}}]))
            _write(Path(tmp), "current_positions.json", {"positions": {"A": 1000.0}})
            rep = rt.holding_period_observation(Path(tmp))
        self.assertEqual(rep["holdings_open_not_in_book"], 1)
        self.assertEqual(rep["holdings_open_not_in_book_names"], ["C"])

    def test_the_observation_has_no_publisher_and_that_is_the_finding(self):
        import tempfile
        opened, closed = NOW - timedelta(days=20), NOW - timedelta(days=2)
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp), "trades.json", _ledger([
                {"type": "rebalance", "ts": opened.isoformat(),
                 "from_allocation": {}, "to_allocation": {"A": 1000.0}},
                {"type": "rebalance", "ts": closed.isoformat(),
                 "from_allocation": {"A": 1000.0}, "to_allocation": {"B": 1000.0}},
            ]))
            _write(Path(tmp), "current_positions.json", {"positions": {"B": 1000.0}})
            rep = rt.measure(Path(tmp), now=NOW)
        self.assertIsNone(rep["holding_period"]["published_by"])
        self.assertTrue(any("не публикует его никто" in f for f in rep["findings"]))

    def test_the_instrument_writes_nothing_into_the_data_dir(self):
        """ADVISORY значит ЧИТАЕТ: ни одного нового файла после прогона."""
        import tempfile
        opened = NOW - timedelta(days=6)
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp), "trades.json", _ledger([
                {"type": "rebalance", "ts": opened.isoformat(),
                 "from_allocation": {}, "to_allocation": {"A": 1000.0}}]))
            before = sorted(p.name for p in Path(tmp).iterdir())
            rt.measure(Path(tmp), now=NOW)
            after = sorted(p.name for p in Path(tmp).iterdir())
        self.assertEqual(before, after)


class SekciyaImeetChitatelya(unittest.TestCase):
    """Прибор без читателя внутри цикла неотличим от незапускавшегося (ADR-526)."""

    def test_the_section_is_wired_into_the_analytics_report(self):
        self.assertIn("round_trip_economics", SECTION_NAMES)

    def test_it_is_built_BEFORE_the_census_that_judges_its_neighbours(self):
        names = list(SECTION_NAMES)
        self.assertLess(names.index("round_trip_economics"),
                        names.index("apy_name_census"))

    def test_the_section_publishes_no_apy_named_number(self):
        """Иначе перепись родов (§5) обязана была бы покраснеть на этой секции."""
        from spa_core.analytics.apy_name_census import _walk
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            rep = rt.measure(Path(tmp), now=NOW)
        numbers, non_numeric = {}, {}
        _walk(rep, "sections/round_trip_economics", numbers, non_numeric)
        self.assertEqual(sorted(numbers), [])


class SvodkaIKodyVozvrata(unittest.TestCase):
    def test_findings_are_printed_as_a_number_not_as_silence(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            rep = rt.measure(Path(tmp), now=NOW)
        self.assertIn("findings", rep)
        self.assertIn(rep["verdict"], ("OK", "FINDINGS"))
        self.assertTrue(rep["is_advisory"])
        self.assertIn(rep["status"], ("OK", "SKIPPED", "ERROR"))

    def test_a_broken_control_withholds_the_verdict(self):
        """Признак, не прошедший контроль ИЗВЕСТНЫМ членом, вердикта не даёт."""
        import tempfile
        original = rt.probe_doubt
        try:
            rt.probe_doubt = lambda door: {
                "inputs": [], "states": {"days_since_last_move": "fail_open"},
                "control_holds": False, "reversal_window_days": 14,
                "reversal_escalation": 1.5}
            with tempfile.TemporaryDirectory() as tmp:
                rep = rt.measure(Path(tmp), now=NOW)
        finally:
            rt.probe_doubt = original
        self.assertEqual(rep["status"], "SKIPPED")
        self.assertIn("контроль", rep["reason"])
        self.assertTrue(any("КОНТРОЛЬ" in f for f in rep["findings"]))
        # И при непройденном контроле вердикт об оси НЕ выдаётся.
        self.assertFalse(any("в пользу сделки" in f.lower() for f in rep["findings"]))

    def test_the_report_status_obeys_the_report_contract(self):
        """Словарь статусов — ЧУЖОЙ (отчёт аналитики), и секция ему подчиняется."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            empty = rt.measure(Path(tmp), now=NOW)
        self.assertIn(empty["status"], ("OK", "SKIPPED", "ERROR"))
        # Без журнала ось 5 не измерена ⇒ секция данных честно пропущена,
        # и причина НАЗВАНА (контракт `test_report_sections.py`).
        self.assertEqual(empty["status"], "SKIPPED")
        self.assertTrue(empty["reason"])
        # Но ИЗМЕРЕННОЕ при этом остаётся в теле целиком — пропуск статуса не
        # означает потери замера.
        self.assertIn("round_trip", empty)
        self.assertIn("doubt", empty)

    def test_a_readable_ledger_makes_the_section_OK(self):
        import tempfile
        opened, closed = NOW - timedelta(days=30), NOW - timedelta(days=1)
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp), "trades.json", _ledger([
                {"type": "rebalance", "ts": opened.isoformat(),
                 "from_allocation": {}, "to_allocation": {"A": 1000.0}},
                {"type": "rebalance", "ts": closed.isoformat(),
                 "from_allocation": {"A": 1000.0}, "to_allocation": {"B": 1000.0}},
            ]))
            _write(Path(tmp), "current_positions.json", {"positions": {"B": 1000.0}})
            rep = rt.measure(Path(tmp), now=NOW)
        self.assertEqual(rep["status"], "OK")
        self.assertEqual(rep["verdict"], "FINDINGS")

    def test_cli_exit_code_is_1_on_findings_and_2_on_unmeasured(self):
        import tempfile
        opened, closed = NOW - timedelta(days=30), NOW - timedelta(days=1)
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp), "trades.json", _ledger([
                {"type": "rebalance", "ts": opened.isoformat(),
                 "from_allocation": {}, "to_allocation": {"A": 1000.0}},
                {"type": "rebalance", "ts": closed.isoformat(),
                 "from_allocation": {"A": 1000.0}, "to_allocation": {"B": 1000.0}},
            ]))
            _write(Path(tmp), "current_positions.json", {"positions": {"B": 1000.0}})
            self.assertEqual(rt.main(["--data-dir", tmp]), 1)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(rt.main(["--data-dir", tmp]), 2)  # журнала нет
        original = rt.load_cost_door
        try:
            rt.load_cost_door = lambda: (None, "дверь не ввезена (проба)")
            with tempfile.TemporaryDirectory() as tmp:
                self.assertEqual(rt.main(["--data-dir", tmp]), 2)
        finally:
            rt.load_cost_door = original


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
