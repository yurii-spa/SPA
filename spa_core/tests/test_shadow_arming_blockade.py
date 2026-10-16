"""Достижим ли взвод ADR-060 ожиданием — или он недостижим по построению.

Каждый тест здесь — положительный контроль реального замера 2026-09-05 (цикл #487),
а не украшение. Замер: `data/shadow_trigger_evaluation.json` месяцами говорил одно
слово `NOT_READY`, критерий №3 мандата владельца (ADR-067, `net_bps > 0`) стоял
`UNCHECKED` с примечанием «no ACT verdict has been scored **yet**», и слово «yet»
читалось как «дней ещё мало». На деле окно было ПОЛНО (30/30 дней), ACT не случился
НИ РАЗУ, а гейт `week_turnover_ok` отказал на 17 из 17 существенных дней — то есть
ожидание не могло изменить ничего никогда.

Разница между «копим дни» и «нужен ответ владельца» — единственное, ради чего
написан блок `arming_blockade`; тесты держат именно её.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import importlib.util
import json
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from spa_core.paper_trading import shadow_trigger_eval as STE

_REPO = Path(__file__).resolve().parents[2]


def _day(n: int) -> str:
    """Дата-строка «n дней назад».

    Литеральная дата здесь была бы бомбой того же класса, что описан в
    `.claude/rules/deployment.md`: ни один вердикт блока от календаря не зависит
    (считается ЧИСЛО различных дат), поэтому и закреплять нечего.
    """
    return (date.today() - timedelta(days=n)).isoformat()


def _record(n: int, *, reasons=None, gates=None, has_legs: bool = True) -> dict:
    rec: dict = {"cycle_date": _day(n), "verdict": "HOLD"}
    if reasons is not None:
        rec["reasons"] = list(reasons)
    if gates is not None:
        rec["gates"] = dict(gates)
    elif reasons is None:
        pass
    if not has_legs and reasons is None and gates is None:
        rec["reasons"] = ["no_material_legs"]
    return rec


def _real_shape(days: int = 17, *, week_over: int | None = None) -> list[dict]:
    """История формы 2026-09-05: `week_turnover_over_budget` на КАЖДОМ дне.

    ``week_over`` — на скольких днях гейт недельного оборота отказывает
    (по умолчанию на всех). Остальные причины чередуются, как в живой ленте:
    ни один гейт, кроме недельного, не покрывает все дни.
    """
    week_over = days if week_over is None else week_over
    others = ["cooldown_active:0.9d<3d", "gain_below_band:0.4pp<0.750pp",
              "payback_too_long:52.7d", "move_turnover_over_budget:40.0%>15%"]
    out = []
    for i in range(days):
        reasons = [others[i % len(others)], others[(i + 1) % len(others)]]
        if i < week_over:
            reasons.append("week_turnover_over_budget")
        out.append(_record(days - i, reasons=reasons))
    return out


def _long_window_shape(days: int = 115) -> list[dict]:
    """Форма ЖИВОГО замера 2026-10-15: ни один гейт не отказывает на всех днях.

    Второй положительный контроль этого файла, и он про регрессию, которую
    первый пропустил ПО ПОСТРОЕНИЮ. На замере 05.09 (17 дней) `week_turnover_ok`
    держал 17/17 и назывался необходимым; к 15.10 окно выросло до 115
    существенных дней, лучший гейт встал на 93 %, и прибор перестал называть
    кого-либо — при том, что ACT по-прежнему не случился НИ РАЗУ и не был
    возможен ни на одном дне. Полоса «100 % у одного гейта» убывает монотонно:
    новый день может только разорвать её. Поэтому тест на 17 днях зеленел, а
    живой прибор молчал — и это молчание не видел никто.

    Доли взяты с живой переписи: payback 93 %, gain_above_band 79 %,
    move_turnover 66 %. Покрытие при этом ПОЛНО — у каждого дня есть отказ.
    """
    out = []
    for i in range(days):
        reasons = []
        if i % 100 < 93:
            reasons.append("payback_too_long:52.7d")
        if i % 100 >= 90:                      # дни без payback добирает gain
            reasons.append("gain_below_band:0.4pp<0.750pp")
        if i % 3 == 0:
            reasons.append("move_turnover_over_budget:40.0%>15%")
        out.append(_record(days - i, reasons=reasons))
    return out


class ArmingBlockadeVerdict(unittest.TestCase):

    def test_one_gate_refusing_every_material_day_is_unreachable(self) -> None:
        """Живая форма 05.09: ожидание не поможет НИКОГДА — так и сказано."""
        b = STE.arming_blockade(_real_shape(17), observed_days=30, min_days=30,
                                acts_scored=0)
        self.assertEqual(b["verdict"], STE.BLOCKADE_UNREACHABLE)
        self.assertEqual(b["necessary_blockers"], ["week_turnover_ok"])
        self.assertEqual(b["material_days"], 17)
        row = next(r for r in b["gate_census"] if r["gate"] == "week_turnover_ok")
        self.assertEqual(row["refused_days"], 17)
        self.assertEqual(row["refused_pct"], 100.0)
        self.assertTrue(row["necessary_blocker"])

    def test_one_gate_clearing_twice_does_not_make_arming_reachable(self) -> None:
        """НАМЕРЕННАЯ ПРАВКА ОЖИДАНИЯ (инвариант #16), цикл #877.

        Тест назывался `…_is_not_unreachable` и требовал `NO_SINGLE_BLOCKER`
        на окне, где недельный гейт прошёл дважды из семнадцати. Ожидание было
        НЕВЕРНО на собственной фикстуре: `_real_shape` даёт каждому дню ещё две
        причины отказа, то есть и на тех двух днях ACT не был возможен. Окно, где
        НИ НА ОДНОМ дне ACT невозможен, недостижимо ожиданием — сколько бы дней
        ни добавили. Старое ожидание закрепляло ровно тот дефект, из-за которого
        живой прибор к 15.10 замолчал на 115 днях полной тишины.

        Опасение автора («UNREACHABLE мог бы печататься на любой красной
        истории») верно и сохранено — но его держит ДРУГОЙ разделитель: наличие
        дня, на котором отказа нет вовсе. Он проверяется тестом ниже
        (`…_act_able_day…`), и это разделитель по делу, а не по случайности
        того, удержал ли какой-то гейт ровно 100 %.
        """
        b = STE.arming_blockade(_real_shape(17, week_over=15), observed_days=30,
                                min_days=30, acts_scored=0)
        self.assertEqual(b["verdict"], STE.BLOCKADE_UNREACHABLE)
        self.assertEqual(b["necessary_blockers"], [])        # 15/17 — не 100 %
        self.assertTrue(b["blockade_cover"])                 # но покрытие названо
        self.assertEqual(b["act_able_days"], [])

    def test_the_long_window_that_silenced_the_old_measure_is_unreachable(self) -> None:
        """Положительный контроль РЕГРЕССИИ 15.10: 115 дней, ни один гейт не 100 %.

        Это замер, на котором прибор печатал `NO_SINGLE_BLOCKER` («блокирует
        переменный набор») при 115 из 115 дней без возможного ACT.
        """
        b = STE.arming_blockade(_long_window_shape(115), observed_days=71,
                                min_days=30, acts_scored=0)
        self.assertEqual(b["material_days"], 115)
        self.assertEqual(b["necessary_blockers"], [])
        self.assertEqual(b["verdict"], STE.BLOCKADE_UNREACHABLE)
        self.assertEqual(b["act_able_days"], [])

    def test_an_act_able_day_is_the_real_discriminator_not_a_hundred_percent_gate(self) -> None:
        """Разделитель, которого добивался снятый тест: день БЕЗ отказов.

        На таком дне `evaluate` сказал бы ACT (ACT = «все гейты true»), значит
        ожидание ещё могло бы сработать — и вердикт обязан перестать быть
        `UNREACHABLE`. Это и есть защита от «UNREACHABLE на любой красной
        истории», но по делу: по дню, а не по круглому проценту у гейта.
        """
        recs = _real_shape(17)
        recs.append(_record(99, gates={"has_legs": True, "cooldown_ok": True,
                                       "gain_above_band": True,
                                       "payback_within_horizon": True,
                                       "week_turnover_ok": True,
                                       "move_turnover_ok": True,
                                       "day_turnover_ok": True,
                                       "move_amount_ok": True,
                                       "min_hold_ok": True,
                                       "target_fully_evidenced": True}))
        b = STE.arming_blockade(recs, observed_days=30, min_days=30, acts_scored=0)
        self.assertNotEqual(b["verdict"], STE.BLOCKADE_UNREACHABLE)
        self.assertEqual(b["verdict"], STE.BLOCKADE_UNMEASURED)
        self.assertEqual(len(b["act_able_days"]), 1)

    def test_the_named_cover_actually_covers_every_material_day(self) -> None:
        """Назвать набор и не покрыть им дни — та же подмена, но тише.

        Проверяется ПО ДНЯМ, а не доверием к функции: для каждого
        существенного дня в покрытии обязан найтись отказавший гейт.
        """
        recs = _long_window_shape(115)
        b = STE.arming_blockade(recs, observed_days=71, min_days=30, acts_scored=0)
        cover = b["blockade_cover"]
        self.assertTrue(b["cover_is_minimal"])
        material = [st for st, src in (STE.gate_state(r) for r in recs)
                    if st is not None and st.get("has_legs", True)]
        self.assertEqual(len(material), 115)
        for st in material:
            self.assertTrue(any(not st.get(g, True) for g in cover))
        # минимальность: ни один ОДИН гейт этих дней не покрывает
        for g in cover:
            self.assertFalse(all(not st.get(g, True) for st in material))

    def test_retired_verdict_is_never_produced(self) -> None:
        """Храповик против возврата тихого ответа (цикл #877).

        `NO_SINGLE_BLOCKER` снят с употребления: он звучал как «ничего
        конкретного», когда измеренная правда была «ACT не был возможен ни на
        одном из 115 дней». Имя оставлено следом для ADR-228; производиться оно
        не должно ни на одной форме истории.
        """
        shapes = [_real_shape(17), _real_shape(17, week_over=15),
                  _long_window_shape(115), _long_window_shape(40)]
        for shape in shapes:
            with self.subTest(days=len(shape)):
                b = STE.arming_blockade(shape, observed_days=71, min_days=30,
                                        acts_scored=0)
                self.assertNotEqual(b["verdict"], STE.BLOCKADE_NO_SINGLE)

    def test_window_not_full_is_accumulating_not_unreachable(self) -> None:
        """До 30-го дня ожидание ОСМЫСЛЕННО, и путать эти два ответа нельзя."""
        b = STE.arming_blockade(_real_shape(17), observed_days=12, min_days=30,
                                acts_scored=0)
        self.assertEqual(b["verdict"], STE.BLOCKADE_ACCUMULATING)

    def test_a_scored_act_makes_the_question_moot(self) -> None:
        b = STE.arming_blockade(_real_shape(17), observed_days=30, min_days=30,
                                acts_scored=1)
        self.assertEqual(b["verdict"], STE.BLOCKADE_NOT_BLOCKED)

    def test_day_without_gates_or_reasons_is_unmeasured_never_clean(self) -> None:
        """Молчание строки — не согласие всех гейтов.

        Строка без обоих полей раньше молча считалась бы днём без отказов и
        занижала бы покрытие ровно того гейта, ради которого блок написан.
        """
        recs = _real_shape(16) + [{"cycle_date": _day(99), "verdict": "HOLD"}]
        b = STE.arming_blockade(recs, observed_days=30, min_days=30, acts_scored=0)
        self.assertEqual(b["verdict"], STE.BLOCKADE_UNMEASURED)
        self.assertEqual(b["gate_state_source"]["unmeasured"], 1)
        self.assertIn(_day(99), b["unmeasured_days"])

    def test_a_full_window_with_nothing_to_decide_is_unmeasured_not_green(self) -> None:
        """«Гейты не отказывали» и «отказывать было нечему» — разные ответы."""
        recs = [_record(i, reasons=["no_material_legs"]) for i in range(1, 6)]
        b = STE.arming_blockade(recs, observed_days=30, min_days=30, acts_scored=0)
        self.assertEqual(b["verdict"], STE.BLOCKADE_UNMEASURED)
        self.assertEqual(b["material_days"], 0)

    def test_reversal_raises_the_bar_and_is_not_counted_as_a_refusal(self) -> None:
        """`reversal_of_recent_move` не отказ, а множитель планки.

        Засчитать его в перепись значило бы назвать необходимым блокиратором
        строку, которая ничего не запрещает: на живых 17 днях она встречается
        девять раз и легко подменила бы собой настоящую находку.
        """
        recs = [_record(i, reasons=["reversal_of_recent_move:['aave_v3']"])
                for i in range(1, 4)]
        b = STE.arming_blockade(recs, observed_days=30, min_days=30, acts_scored=0)
        self.assertEqual(b["material_days"], 3)
        self.assertEqual(b["necessary_blockers"], [])
        # НАМЕРЕННАЯ ПРАВКА ОЖИДАНИЯ (инв. #16), цикл #877: было
        # `NO_SINGLE_BLOCKER`. Предмет теста — что `reversal_of_recent_move` НЕ
        # идёт в перепись отказов — сохранён дословно (перепись пуста). Но у
        # этих трёх дней не оказывается НИ ОДНОГО отказа, то есть перепись их
        # тишину не объясняет, и честный ответ про них — «не измерено», а не
        # «блокирует переменный набор». Третий исход вместо тихой уверенности.
        self.assertEqual(b["verdict"], STE.BLOCKADE_UNMEASURED)
        self.assertEqual(len(b["act_able_days"]), 3)


class GateStateSource(unittest.TestCase):

    def test_gates_field_wins_over_the_derivation_when_both_are_present(self) -> None:
        rec = {"cycle_date": _day(1),
               "reasons": ["week_turnover_over_budget"],
               "gates": {"has_legs": True, "week_turnover_ok": False,
                         "cooldown_ok": True}}
        state, source = STE.gate_state(rec)
        self.assertEqual(source, "gates")
        self.assertFalse(state["week_turnover_ok"])

    def test_v1_line_without_gates_is_derived_from_reasons(self) -> None:
        state, source = STE.gate_state(
            {"cycle_date": _day(1), "reasons": ["cooldown_active:0.9d<3d"]})
        self.assertEqual(source, "reasons")
        self.assertFalse(state["cooldown_ok"])
        self.assertTrue(state["week_turnover_ok"])

    def test_a_line_with_neither_is_unmeasured(self) -> None:
        state, source = STE.gate_state({"cycle_date": _day(1)})
        self.assertIsNone(state)
        self.assertEqual(source, "unmeasured")

    def test_the_deriver_reports_its_own_agreement_rate(self) -> None:
        """У подтверждающего инструмента обязана быть СВОЯ цена ошибки."""
        rec = {"cycle_date": _day(1),
               "reasons": ["week_turnover_over_budget"],
               "gates": {"has_legs": True, "week_turnover_ok": False,
                         "cooldown_ok": True, "gain_above_band": True,
                         "payback_within_horizon": True, "min_hold_ok": True,
                         "move_turnover_ok": True, "target_fully_evidenced": True}}
        b = STE.arming_blockade([rec], observed_days=30, min_days=30, acts_scored=0)
        agree = b["reason_deriver_agreement"]
        self.assertEqual(agree["days_with_both_sources"], 1)
        self.assertEqual(agree["agreed"], 1)

    def test_every_gate_the_real_trigger_produces_has_a_reason_prefix(self) -> None:
        """Храповик отображения: новый гейт без строки причины = красный тест.

        Иначе он молча считался бы ПРОЙДЕННЫМ на всех строках схемы v1 — то есть
        занижал бы ровно ту величину, ради которой блок написан.
        """
        from spa_core.allocator import rebalance_economics as RE

        decision = RE.evaluate(
            current_positions={"aave_v3": 40_000.0, "maple": 20_000.0},
            target_positions={"maple": 60_000.0},
            apy_pct={"aave_v3": 2.7, "maple": 5.0},
            evidenced={"aave_v3", "maple"},
            chains={"aave_v3": "ethereum", "maple": "ethereum"},
            capital_usd=100_000.0,
        )
        self.assertTrue(decision.gates, "у решения нет словаря gates — мерить нечем")
        unmapped = sorted(set(decision.gates) - set(STE.GATE_BY_REASON_PREFIX.values()))
        self.assertEqual(
            unmapped, [],
            f"гейт(ы) {unmapped} печатает настоящий триггер, но в "
            "GATE_BY_REASON_PREFIX для них нет строки причины: на истории "
            "схемы v1 они молча зачлись бы как пройденные")


class WiredIntoTheMandatoryOfficeStep(unittest.TestCase):
    """Сторож, которого никто не читает, — украшение. Проверяем ПОВЕДЕНИЕ читателя."""

    @staticmethod
    def _office():
        path = _REPO / "scripts" / "consume_office_reports.py"
        spec = importlib.util.spec_from_file_location("cor_blockade", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _doc(self, blockade) -> dict:
        # Отметка времени берётся относительной: возраст артефакта здесь не
        # предмет, а литеральная дата завела бы файл в класс, описанный в
        # `.claude/rules/deployment.md`, без единой причины.
        stamp = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        return {"generated_at": stamp,
                "status": "NOT_READY", "ready_to_arm": False,
                "observation_days": 30, "counts": {"act": 0},
                "criteria": [], "arming_blockade": blockade}

    def test_office_step_says_the_blockade_out_loud(self) -> None:
        b = STE.arming_blockade(_real_shape(17), observed_days=30, min_days=30,
                                acts_scored=0)
        out = "\n".join(self._office()._summarize_json(
            "data/shadow_trigger_evaluation.json", self._doc(b)))
        self.assertIn(STE.BLOCKADE_UNREACHABLE, out)
        self.assertIn("week_turnover_ok", out)
        self.assertIn("НЕОБХОДИМЫЙ", out)

    def test_office_step_names_the_cover_when_no_gate_holds_a_hundred_percent(self) -> None:
        """Дыра покрытия, найденная мутациями цикла #877.

        На окне 15.10 необходимого блокиратора НЕТ (лучший гейт 93 %), и до
        правки читатель получал ровно слово `NO_SINGLE_BLOCKER` без единого
        имени. Проверять «вердикт в выводе» недостаточно: снять проводку
        покрытия и оставить вердикт — мутация, которую прежний набор пережил.
        Поэтому требуется, чтобы в выводе были ИМЕНА гейтов покрытия.
        """
        b = STE.arming_blockade(_long_window_shape(115), observed_days=71,
                                min_days=30, acts_scored=0)
        self.assertEqual(b["necessary_blockers"], [])      # предпосылка теста
        out = "\n".join(self._office()._summarize_json(
            "data/shadow_trigger_evaluation.json", self._doc(b)))
        self.assertIn(STE.BLOCKADE_UNREACHABLE, out)
        self.assertIn("покрытие тишины", out)
        for gate in b["blockade_cover"]:
            self.assertIn(gate, out, f"гейт покрытия {gate} не дошёл до читателя")

    def test_office_step_names_the_days_the_census_cannot_explain(self) -> None:
        """Второй читатель третьего исхода: дни без отказов обязаны быть НАЗВАНЫ."""
        recs = _real_shape(5)
        recs.append(_record(99, reasons=["reversal_of_recent_move:['aave_v3']"]))
        b = STE.arming_blockade(recs, observed_days=71, min_days=30, acts_scored=0)
        self.assertEqual(len(b["act_able_days"]), 1)       # предпосылка теста
        out = "\n".join(self._office()._summarize_json(
            "data/shadow_trigger_evaluation.json", self._doc(b)))
        self.assertIn("НЕ ОБЪЯСНЕНО", out)

    def test_office_step_names_a_report_without_the_block(self) -> None:
        """Отчёт старого образца молчал бы так же, как здоровый, — третий исход."""
        doc = self._doc(None)
        doc.pop("arming_blockade")
        out = "\n".join(self._office()._summarize_json(
            "data/shadow_trigger_evaluation.json", doc))
        self.assertIn("НЕ ИЗМЕРЕНА", out)


class EndToEnd(unittest.TestCase):

    def _history(self, tmp: Path, records: list[dict]) -> None:
        with open(tmp / STE.HISTORY_FILENAME, "w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")

    def test_evaluate_window_publishes_the_block_without_gating_anything(self) -> None:
        """Блок НАЗЫВАЕТ. Критерии взвода — мандат владельца, и он их не трогает."""
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            self._history(tmp, _real_shape(17))
            doc = STE.evaluate_window(tmp, write=False)
            self.assertIn("arming_blockade", doc)
            self.assertEqual(doc["arming_blockade"]["verdict"],
                             STE.BLOCKADE_ACCUMULATING)   # 17 дней < 30
            self.assertFalse(doc["ready_to_arm"])
            self.assertEqual([c["criterion"] for c in doc["criteria"]],
                             ["observation_days", "hit_rate", "net_bps_if_followed"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
