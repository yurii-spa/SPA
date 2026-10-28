"""Могло ли РАЗРЕШЕНИЕ ВЛАДЕЛЬЦА на пробный ход сработать хоть раз после выдачи.

Каждый тест — положительный контроль живого замера 28.10 (цикл #966), а не
украшение. Замер: владелец ответил 11.09 (ADR-334, `owner_choice: 1`) «советник
получает право ровно на ОДИН ход, чтобы появилось что оценивать», и сорок семь
дней спустя ACT по-прежнему ноль. Перепись по живой истории: из 124 существенных
записей ПОСЛЕ выдачи разрешение не могло сработать ни на одной (45 дат), а ДО
выдачи таких записей было 6 из 24 — то есть предпосылка ответа владельца была
верна в день ответа и перестала быть верной после него. Чаще всех стои́т
`payback_within_horizon` (115 записей, 92.7 %), которого разрешение не снимает
НАМЕРЕННО: экономика хода обязана пройти сама.

Держат тесты две вещи, и обе — про подмену, а не про арифметику:

1. **Правило разрешения живёт ОДНОЙ дверью.** `grant_blockers` судит и живой ход
   (`apply_trial_grant`), и историю (`trial_grant_reach`). Вторая копия спорила
   бы с первой молча, поэтому здесь есть контроль проводки в обе стороны:
   подменённая дверь обязана менять ОБА ответа.
2. **«Не мешало» и «не измерено» различимы (инв. #17).** Состояние гейтов,
   выведенное из строк причин, лосси по построению, и по нему «разрешение
   сработало бы» не утверждается — а НАЗВАННЫЙ отказ по нему принимается:
   положительное свидетельство остаётся свидетельством.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import importlib.util
import json
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from spa_core.paper_trading import cio_trial as CT
from spa_core.paper_trading import shadow_trigger_eval as STE

_REPO = Path(__file__).resolve().parents[2]
_MIN_GAIN = 0.50          # базовый порог бумажной колонки — читается у контракта ниже
_GRANT_AGE_DAYS = 20      # «выдача» сцены: относительная, чтобы тест не зависел от календаря


def _day(n: int) -> str:
    """Дата-строка «n дней назад» — литеральная дата здесь была бы бомбой класса
    `.claude/rules/deployment.md` (ни один вердикт переписи от календаря не
    зависит: считаются записи и различные даты)."""
    return (date.today() - timedelta(days=n)).isoformat()


def _grant() -> dict:
    return {"adr": "ADR-TEST", "granted_at": _day(_GRANT_AGE_DAYS) + "T12:00:00Z",
            "book": "conservative", "moves": 1}


def _rec(n: int, *, gates=None, reasons=None, gain=1.0, has_legs=True) -> dict:
    rec: dict = {"cycle_date": _day(n), "verdict": "HOLD"}
    if gain is not None:
        rec["gain_pp"] = gain
    if gates is not None:
        state = {g: True for g in STE._ALL_GATES}
        state["has_legs"] = has_legs
        state.update(gates)
        rec["gates"] = state
    if reasons is not None:
        rec["reasons"] = reasons
    return rec


def _reach(records, **kw):
    kw.setdefault("grant", _grant())
    kw.setdefault("min_gain_pp", _MIN_GAIN)
    return STE.trial_grant_reach(records, **kw)


class TheDoorOfTheGrantRule(unittest.TestCase):
    """`grant_blockers` — одно правило на живой ход и на историю."""

    def test_only_frequency_limiters_are_no_obstacle(self):
        blockers, why = CT.grant_blockers(
            ["week_turnover_ok", "move_turnover_ok", "cooldown_ok", "day_turnover_ok",
             "min_hold_ok", "gain_above_band"],
            gain_pp=1.0, min_gain_pp=_MIN_GAIN)
        self.assertIsNone(why)
        self.assertEqual(blockers, [], "ограничители частоты разрешение снимает")

    def test_economics_is_named_and_not_waived(self):
        blockers, _ = CT.grant_blockers(["payback_within_horizon"],
                                        gain_pp=1.0, min_gain_pp=_MIN_GAIN)
        self.assertEqual(blockers, [(CT.BLOCK_ECONOMIC, ["payback_within_horizon"])])

    def test_the_base_bar_is_named_even_when_the_band_is_waived(self):
        blockers, _ = CT.grant_blockers(["gain_above_band"],
                                        gain_pp=0.1, min_gain_pp=_MIN_GAIN)
        self.assertEqual(blockers, [(CT.BLOCK_BASE_GAIN, [])])

    def test_a_gate_the_grant_does_not_know_is_named_not_assumed_away(self):
        blockers, _ = CT.grant_blockers(["move_amount_ok"],
                                        gain_pp=1.0, min_gain_pp=_MIN_GAIN)
        self.assertEqual(blockers, [(CT.BLOCK_UNKNOWN, ["move_amount_ok"])])

    def test_nothing_to_move_is_not_an_obstacle_to_the_grant(self):
        blockers, _ = CT.grant_blockers(["has_legs"], gain_pp=1.0, min_gain_pp=_MIN_GAIN)
        self.assertEqual(blockers, [], "«двигать нечего» — отсутствие предмета, не препятствие")

    def test_a_missing_input_is_the_third_outcome_not_a_verdict(self):
        for kwargs in ({"gain_pp": None, "min_gain_pp": _MIN_GAIN},
                       {"gain_pp": 1.0, "min_gain_pp": None}):
            with self.subTest(**kwargs):
                blockers, why = CT.grant_blockers(["week_turnover_ok"], **kwargs)
                self.assertIsNone(blockers, "НЕ ИЗМЕРЕНО выдано за «не мешало»")
                self.assertTrue(why, "у третьего исхода обязана быть названная причина")

    def test_all_obstacles_are_named_at_once_not_only_the_first(self):
        blockers, _ = CT.grant_blockers(
            ["payback_within_horizon", "move_amount_ok"], gain_pp=0.1,
            min_gain_pp=_MIN_GAIN)
        self.assertEqual([k for k, _g in blockers],
                         [CT.BLOCK_ECONOMIC, CT.BLOCK_BASE_GAIN, CT.BLOCK_UNKNOWN])


class TheLiveDecisionGoesThroughThatDoor(unittest.TestCase):
    """Проводка, а не наличие функции: подменённая дверь меняет живой вердикт."""

    class _Dec:
        def __init__(self):
            self.decision = "HOLD"
            self.gain_pp = 1.0
            self.payback_days = 3
            self.gates = {g: True for g in STE._ALL_GATES}
            self.gates["has_legs"] = True
            self.gates["week_turnover_ok"] = False
            self.reasons = []

    class _Params:
        min_gain_pp = _MIN_GAIN

    def _apply(self, tmp):
        return CT.apply_trial_grant(self._Dec(), self._Params(),
                                    book_id="conservative", data_dir=tmp)

    def test_the_grant_fires_when_the_door_sees_no_obstacle(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            dec, why = self._apply(tmp)
        self.assertEqual(dec.decision, "ACT", why)

    def test_a_door_that_names_an_obstacle_holds_the_live_move(self):
        import tempfile
        original = CT.grant_blockers
        CT.grant_blockers = lambda failing, **kw: ([("economics_failed", ["подменено"])], None)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                dec, why = self._apply(tmp)
        finally:
            CT.grant_blockers = original
        self.assertEqual(dec.decision, "HOLD",
                         "живой ход судит НЕ дверь — значит у правила две копии")
        self.assertIn("подменено", why)

    def test_a_door_that_cannot_measure_holds_the_live_move(self):
        import tempfile
        original = CT.grant_blockers
        CT.grant_blockers = lambda failing, **kw: (None, "нечем мерить")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                dec, why = self._apply(tmp)
        finally:
            CT.grant_blockers = original
        self.assertEqual(dec.decision, "HOLD", "НЕ ИЗМЕРЕНО не имеет права открывать ход")
        self.assertIn("не измерены", why)


class TheCensusOfReach(unittest.TestCase):
    """Перепись истории — тем же правилом и с различимыми исходами."""

    def test_economics_after_the_grant_makes_it_unreachable_and_names_the_blocker(self):
        recs = [_rec(n, gates={"payback_within_horizon": False, "week_turnover_ok": False})
                for n in range(1, 6)]
        out = _reach(recs)
        self.assertEqual(out["verdict"], STE.REACH_BLOCKED)
        self.assertEqual(out["after_grant"]["open_by_gates_records"], 0)
        self.assertEqual(out["after_grant"]["blocked_records"], 5)
        self.assertEqual(out["blocker_census"][0]["gate"], "payback_within_horizon")
        self.assertEqual(out["blocker_census"][0]["records"], 5)

    def test_a_record_the_gates_did_not_block_is_OPEN_and_claims_no_more_than_that(self):
        recs = [_rec(1, gates={"week_turnover_ok": False})]
        out = _reach(recs)
        self.assertEqual(out["verdict"], STE.REACH_OPEN)
        self.assertEqual(out["after_grant"]["open_by_gates_records"], 1)
        self.assertIn("демпфер", out["reason"],
                      "вердикт обязан вслух назвать входы, которых история не несёт")

    def test_a_lossy_source_cannot_say_the_grant_would_have_fired(self):
        recs = [_rec(1, reasons=["week_turnover_over_budget:30%>25%"], gates=None)]
        out = _reach(recs)
        self.assertEqual(out["after_grant"]["open_by_gates_records"], 0,
                         "по выводу из строк причин «не мешало» не утверждается")
        self.assertEqual(out["after_grant"]["unmeasured_records"], 1)
        self.assertEqual(out["verdict"], STE.REACH_UNMEASURED)

    def test_a_named_refusal_from_the_same_lossy_source_is_still_evidence(self):
        recs = [_rec(1, reasons=["payback_too_long:197.1d"], gates=None)]
        out = _reach(recs)
        self.assertEqual(out["after_grant"]["blocked_records"], 1,
                         "названный отказ — положительное свидетельство, его не теряем")
        self.assertEqual(out["verdict"], STE.REACH_BLOCKED)

    def test_a_record_without_a_measured_gain_is_unmeasured_not_open(self):
        recs = [_rec(1, gates={"week_turnover_ok": False}, gain=None)]
        out = _reach(recs)
        self.assertEqual(out["after_grant"]["unmeasured_records"], 1)
        self.assertEqual(out["verdict"], STE.REACH_UNMEASURED)
        self.assertTrue(out["unmeasured_sample"][0]["why"])

    def test_an_act_in_the_window_makes_the_question_moot(self):
        recs = [_rec(1, gates={"payback_within_horizon": False})]
        self.assertEqual(_reach(recs, acts=1)["verdict"], STE.REACH_MOOT)

    def test_no_material_record_after_the_grant_is_unmeasured_not_blocked(self):
        recs = [_rec(_GRANT_AGE_DAYS + 5, gates={"payback_within_horizon": False})]
        out = _reach(recs)
        self.assertEqual(out["after_grant"]["records"], 0)
        self.assertEqual(out["verdict"], STE.REACH_UNMEASURED)

    def test_the_day_of_the_grant_counts_as_before_it(self):
        recs = [_rec(_GRANT_AGE_DAYS, gates={"week_turnover_ok": False})]
        out = _reach(recs)
        self.assertEqual(out["before_grant"]["records"], 1)
        self.assertEqual(out["after_grant"]["records"], 0)

    def test_trivial_holds_are_not_counted_at_all(self):
        recs = [_rec(1, gates={"has_legs": False}, has_legs=False)]
        out = _reach(recs)
        self.assertEqual(out["after_grant"]["records"], 0)

    def test_records_and_dates_are_two_numbers_not_one(self):
        recs = [_rec(1, gates={"payback_within_horizon": False}) for _ in range(3)]
        out = _reach(recs)
        self.assertEqual(out["after_grant"]["records"], 3)
        self.assertEqual(out["after_grant"]["dates"], 1,
                         "три прогона одного дня — одна дата и три записи")

    def test_the_census_goes_through_the_same_door(self):
        recs = [_rec(1, gates={"payback_within_horizon": False})]
        original = CT.grant_blockers
        CT.grant_blockers = lambda failing, **kw: ([], None)
        try:
            out = _reach(recs)
        finally:
            CT.grant_blockers = original
        self.assertEqual(out["verdict"], STE.REACH_OPEN,
                         "перепись судит НЕ дверью — значит у правила две копии")

    def test_the_before_after_contrast_is_in_the_verdict_itself(self):
        recs = ([_rec(_GRANT_AGE_DAYS + 2, gates={"week_turnover_ok": False})]
                + [_rec(1, gates={"payback_within_horizon": False})])
        out = _reach(recs)
        self.assertEqual(out["verdict"], STE.REACH_BLOCKED)
        self.assertEqual(out["before_grant"]["open_by_gates_records"], 1)
        self.assertIn("перестала быть верной", out["reason"])

    def test_the_unit_of_count_is_declared_in_the_report(self):
        out = _reach([_rec(1, gates={"payback_within_horizon": False})])
        self.assertIn("запись вердикта", out["unit"])


class TheReaderOfTheCensus(unittest.TestCase):
    """Прибор без читателя — сирота (урок ADR-843). Читатель проверяется НАСТОЯЩИЙ."""

    def test_a_missing_block_is_the_third_outcome_not_silence(self):
        lines = STE.format_trial_reach(None)
        self.assertEqual(len(lines), 1)
        self.assertIn("НЕ ИЗМЕРЕНА", lines[0])

    def test_an_ABSENT_unmeasured_sample_is_not_read_as_clean(self):
        """Инв. #17 у ОБРАЗЦА: «поля нет» ≠ «не измеренных нет».

        Положительный контроль на дефект, найденный храповиком класса 28.10:
        читатель брал `reach.get("unmeasured_sample") or []`, и отчёт СТАРОГО
        образца (поля нет вовсе) печатался ровно как чистый замер — молча, в том
        самом блоке, который против этого и написан.
        """
        out = _reach([_rec(1, gates={"payback_within_horizon": False})])
        out.pop("unmeasured_sample", None)
        text = "\n".join(STE.format_trial_reach(out))
        self.assertIn("не назван вовсе", text,
                      "отсутствие образца выдано за «не измеренных нет»")

    def test_an_EMPTY_unmeasured_sample_stays_a_measurement(self):
        """Контроль в обратную сторону: пустой образец — ЗАМЕР, а не отсутствие.

        Без него «назови отсутствие» было бы неотличимо от «назови всегда».
        """
        out = _reach([_rec(1, gates={"payback_within_horizon": False})])
        out["unmeasured_sample"] = []
        text = "\n".join(STE.format_trial_reach(out))
        self.assertNotIn("не назван вовсе", text,
                         "измеренный пустой образец объявлен отсутствующим")

    def test_the_blocked_verdict_is_drawn_with_its_numbers(self):
        out = _reach([_rec(1, gates={"payback_within_horizon": False})])
        text = "\n".join(STE.format_trial_reach(out))
        self.assertIn("🔴", text)
        self.assertIn(STE.REACH_BLOCKED, text)
        self.assertIn("payback_within_horizon", text)
        self.assertIn("ADVISORY", text)

    def test_the_office_step_prints_the_block(self):
        spec = importlib.util.spec_from_file_location(
            "cor_reach", _REPO / "scripts" / "consume_office_reports.py")
        cor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cor)
        # Отметка времени добавлена циклом #968: без неё эта площадка перевела
        # потолок двери объявлений 16 → 17 (`test_office_declaration_doors`),
        # то есть красный, не замеченный в цикле её рождения. Дата ОТНОСИТЕЛЬНАЯ:
        # свежесть сцены ни на один вердикт переписи не влияет.
        doc = {"status": "NOT_READY", "ready_to_arm": False, "observation_days": 84,
               "generated_at": datetime.now(timezone.utc).isoformat(),
               "counts": {"act": 0}, "criteria": [],
               "arming_blockade": {"verdict": STE.BLOCKADE_UNREACHABLE, "reason": "—"},
               "trial_grant_reach": _reach([_rec(1, gates={"payback_within_horizon": False})])}
        lines = cor._summarize_json(
            str(_REPO / "data" / "shadow_trigger_evaluation.json"), doc,
            root=str(_REPO), artifact_root=str(_REPO))
        text = "\n".join(lines)
        self.assertIn("Достижимость пробного хода", text,
                      "шаг 0-офис блок НЕ читает — прибор остался бы сиротой")
        self.assertIn(STE.REACH_BLOCKED, text)

    def test_the_office_declares_both_the_producer_and_the_fields_it_reads(self):
        spec = importlib.util.spec_from_file_location(
            "cor_decl", _REPO / "scripts" / "consume_office_reports.py")
        cor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cor)
        name = "shadow_trigger_evaluation.json"
        self.assertIn(name, cor._PRODUCER)
        self.assertIn("trial_grant_reach", cor._READ_SCHEMA.get(name, ()))


class TheLiveArtifactCarriesIt(unittest.TestCase):
    """Блок обязан появляться в самом отчёте, а не только в функции."""

    def test_evaluate_window_carries_the_block(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            (data_dir / "allocation_rationale_history.jsonl").write_text(
                json.dumps(_rec(1, gates={"payback_within_horizon": False})) + "\n",
                encoding="utf-8")
            doc = STE.evaluate_window(data_dir, write=False)
        self.assertIn("trial_grant_reach", doc)
        self.assertEqual(doc["trial_grant_reach"]["grant"]["adr"],
                         CT.TRIAL_GRANT["adr"], "перепись судит РЕАЛЬНОЕ разрешение")

    def test_the_blockade_prints_dates_next_to_records(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            lines = [json.dumps(_rec(1, gates={"payback_within_horizon": False}))
                     for _ in range(2)]
            (data_dir / "allocation_rationale_history.jsonl").write_text(
                "\n".join(lines) + "\n", encoding="utf-8")
            doc = STE.evaluate_window(data_dir, write=False)
        b = doc["arming_blockade"]
        self.assertEqual(b["material_days"], 2, "`*_days` этого блока считает ЗАПИСИ")
        self.assertEqual(b["material_dates"], 1, "дат одна — и это другое число")


if __name__ == "__main__":   # pragma: no cover
    unittest.main()
