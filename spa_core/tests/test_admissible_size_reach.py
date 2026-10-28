"""Предложение НИКОГДА не урезается до ДОПУСТИМОГО размера (ADR-848).

Каждый тест — положительный контроль живого замера 28.10 (цикл #968), а не
украшение. Замер по живой истории (163 записи / 84 даты, книга conservative):
на **7 записях (6 дат)** ход, урезанный до допустимых $15 000, прошёл бы ВСЕ
гейты, которых разрешение владельца (ADR-334) не снимает; **3 из них — после
выдачи разрешения** (2026-10-02 и 2026-10-15 ×2). Самая острая запись —
2026-10-02: предложение $40 000 при выигрыше 3.236 пп и окупаемости 9.94 дн.,
отказано ТОЛЬКО потолками размера; урезанное до $15 000 оно даёт выигрыш
1.214 пп при окупаемости ≤ 26.5 дн.

Сосед `trial_grant_reach` на той же истории печатает «разрешение сработало бы на
0 записях» — и ОБА верны: сосед судит ЗАПИСАННОЕ предложение, этот прибор —
допустимое подмножество того же предложения. Потолок размера читается как ФИЛЬТР
предложений, а не как РАЗМЕР хода, и урезать предложение не умеет никто.

Держат тесты три вещи, и все три — про подмену, а не про арифметику:

1. **Направление оценки.** Снятие стены даёт ПОТОЛОК достижимости (прошло ⇒ не
   доказано ничего), урезание — НИЖНЮЮ границу (прошло ⇒ ход был возможен).
   Перепутать их значило бы выдать отмену защиты за доказательство.
2. **Ошибка идёт ПРОТИВ находки.** Стоимость урезанного хода берётся полной, то
   есть окупаемость ЗАВЫШЕНА. Тест на это есть: удешеви стоимость — находок
   станет больше, и значит объявленная оценка консервативна.
3. **Три исхода различимы (инв. #17).** Урезание, обращающее ногу в пыль, — это
   НЕ ИЗМЕРЕНО, а не «не прошло»: предложение стало ДРУГИМ. Бюджеты дня и
   недели при меньшем обороте — «не решено», а не «открыто».
"""
# LLM_FORBIDDEN
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from spa_core.allocator.rebalance_economics import TriggerParams
from spa_core.paper_trading import admissible_size as ADM
from spa_core.paper_trading import cio_trial as CT
from spa_core.paper_trading import shadow_trigger_eval as STE

_REPO = Path(__file__).resolve().parents[2]
_PAPER = TriggerParams.for_mode("paper")

#: Сцена замера 2026-10-02 — числа ЖИВОЙ записи, а не выдуманные.
_INCIDENT = {
    "capital_usd": 100_000.0,
    "turnover_usd": 40_000.0,
    "gain_pp": 3.23635,
    "cost_usd": 88.15,
    "payback_days": 9.94,
    "legs": [{"protocol": "aave_v3", "delta_usd": 35_000.0},
             {"protocol": "fluid_fusdc", "delta_usd": -20_000.0},
             {"protocol": "maple", "delta_usd": -20_000.0},
             {"protocol": "morpho_blue_base", "delta_usd": 5_000.0}],
    "schema": "shadow-hist-v2",
}

_ALL_PASS = {"has_legs": True, "gain_above_band": True, "payback_within_horizon": True,
             "cooldown_ok": True, "min_hold_ok": True, "move_turnover_ok": True,
             "move_amount_ok": True, "week_turnover_ok": True, "day_turnover_ok": True,
             "target_fully_evidenced": True}


def _day(n: int) -> str:
    """Дата-строка «n дней назад»: литеральная дата была бы бомбой класса
    `.claude/rules/deployment.md`, а ни один вердикт переписи от календаря не
    зависит (считаются записи и различные даты)."""
    return (date.today() - timedelta(days=n)).isoformat()


def _now_iso() -> str:
    """Отметка времени сцены — ОТНОСИТЕЛЬНАЯ: литеральная дата здесь была бы
    бомбой класса `.claude/rules/deployment.md`, а свежесть сцены ни на один
    вердикт этого прибора не влияет."""
    return (datetime.now(timezone.utc)).isoformat()


def _rec(n: int = 1, **over) -> dict:
    """Запись сцены 2026-10-02 с подменой любого поля."""
    gates = dict(_ALL_PASS)
    gates.update({"move_turnover_ok": False, "move_amount_ok": False,
                  "week_turnover_ok": False, "day_turnover_ok": False})
    gates.update(over.pop("gates", {}))
    rec = dict(_INCIDENT)
    rec.update({"cycle_date": _day(n), "gates": gates})
    rec.update(over)
    return rec


def _reach(records, **kw) -> dict:
    return ADM.admissible_size_reach(records, params=_PAPER, **kw)


class TheIncidentOf_2026_10_02(unittest.TestCase):
    """Запись, на которой экономика прошла, а отказали ТОЛЬКО потолки размера."""

    def test_the_cut_move_fires_and_the_numbers_are_named(self):
        out = _reach([_rec(1)])
        self.assertEqual(out["verdict"], ADM.ADM_FIRES)
        row = out["fires"][0]
        self.assertEqual(row["klass"], ADM.CLASS_FIRES)
        self.assertAlmostEqual(row["turnover_usd_cut"], 15_000.0, places=2)
        self.assertAlmostEqual(row["gain_pp_cut"], 3.23635 * 0.375, places=6)
        self.assertAlmostEqual(row["payback_days_bound"], 9.94 / 0.375, places=2)

    def test_the_gain_is_exact_not_approximate(self):
        """Смешанная ставка линейна по позициям ⇒ выигрыш урезанного хода ТОЧЕН.

        Сверяется до 6 знаков — ровно до той сетки, на которой прибор печатает
        (``round(..., 6)``). Требовать больше значило бы проверять округление, а
        не линейность; требовать меньше — не заметить, если линейность подменят
        приближением.
        """
        cut, why = ADM.cut_to_admissible(_rec(1), _PAPER)
        self.assertEqual(why, "")
        self.assertAlmostEqual(cut["gain_pp_cut"], _INCIDENT["gain_pp"] * cut["k"],
                               places=6)

    def test_payback_is_an_upper_bound_so_the_error_runs_against_the_finding(self):
        """Стоимость взята ПОЛНОЙ: истинная окупаемость не хуже напечатанной.

        Контроль направления: удешеви стоимость (меньше газа/проскальзывания) —
        находка только УСИЛИТСЯ. Если бы прибор ошибался в другую сторону, он
        рождал бы находки из арифметики, а не из замера.
        """
        cheap = dict(_rec(1))
        cheap["payback_days"] = _INCIDENT["payback_days"] / 2.0
        bound_cheap = ADM.cut_to_admissible(cheap, _PAPER)[0]["payback_days_bound"]
        bound_full = ADM.cut_to_admissible(_rec(1), _PAPER)[0]["payback_days_bound"]
        self.assertLess(bound_cheap, bound_full)

    def test_the_neighbour_that_judges_the_RECORDED_proposal_says_the_opposite(self):
        """Оба верны, и в этом вся находка: судят РАЗНЫЕ ходы."""
        rec = _rec(1)
        neighbour = STE.trial_grant_reach([rec], min_gain_pp=_PAPER.min_gain_pp, acts=0)
        self.assertEqual(neighbour["verdict"], STE.REACH_BLOCKED,
                         "сосед обязан отказать записанному предложению ($40 000 "
                         "выше потолка $15 000) — иначе сцена не воспроизводит замер")
        self.assertEqual(_reach([rec])["verdict"], ADM.ADM_FIRES)


class WhatCuttingCannotFix(unittest.TestCase):
    """Красное на КАЖДОМ порванном звене, и звено НАЗВАНО."""

    def test_a_gain_too_small_to_survive_cutting_is_named_as_economics(self):
        out = _reach([_rec(1, gain_pp=0.60, payback_days=20.0)])
        self.assertEqual(out["verdict"], ADM.ADM_NEVER)
        self.assertEqual(out["class_census"][ADM.CLASS_ECON_FAILS], 1)

    def test_a_payback_that_cutting_pushes_past_the_horizon_is_named(self):
        out = _reach([_rec(1, payback_days=20.0)])   # 20 / 0.375 = 53.3 дн. > 30
        self.assertEqual(out["verdict"], ADM.ADM_NEVER)
        self.assertEqual(out["class_census"][ADM.CLASS_ECON_FAILS], 1)

    def test_an_unevidenced_target_is_not_something_size_can_fix(self):
        out = _reach([_rec(1, gates={"target_fully_evidenced": False})])
        self.assertEqual(out["verdict"], ADM.ADM_NEVER)
        self.assertIn(ADM.CLASS_ECON_FAILS + "", out["class_census"])

    def test_a_proposal_already_inside_the_caps_is_its_own_class_not_a_finding(self):
        out = _reach([_rec(1, turnover_usd=10_000.0, gain_pp=0.1, payback_days=120.0,
                           legs=[{"protocol": "a", "delta_usd": -10_000.0},
                                 {"protocol": "b", "delta_usd": 10_000.0}])])
        self.assertEqual(out["class_census"][ADM.CLASS_ALREADY_ADMISSIBLE], 1)
        self.assertEqual(out["verdict"], ADM.ADM_NEVER)

    def test_nothing_material_to_move_is_not_a_refusal(self):
        out = _reach([_rec(1, gates={"has_legs": False})])
        self.assertEqual(out["class_census"][ADM.CLASS_NO_PROPOSAL], 1)


class TheThirdOutcomeIsDistinguishable(unittest.TestCase):
    """Инв. #17: «не измерено» нигде не выдаётся за «не прошло» и за «прошло»."""

    def test_cutting_a_leg_into_dust_is_UNMEASURED_not_a_refusal(self):
        rec = _rec(1, legs=[{"protocol": "big", "delta_usd": 39_000.0},
                            {"protocol": "dust", "delta_usd": -1_000.0},
                            {"protocol": "other", "delta_usd": -38_000.0}])
        out = _reach([rec])
        self.assertEqual(out["class_census"][ADM.CLASS_UNMEASURED], 1)
        self.assertIn("пыль", out["unmeasured_sample"][0]["why"])

    def test_a_record_without_capital_is_UNMEASURED_with_a_named_reason(self):
        rec = _rec(1)
        rec.pop("capital_usd")
        out = _reach([rec])
        self.assertEqual(out["class_census"][ADM.CLASS_UNMEASURED], 1)
        self.assertTrue(out["unmeasured_sample"][0]["why"])

    def test_a_record_whose_gates_are_unknown_is_UNMEASURED_not_open(self):
        rec = _rec(1)
        rec.pop("gates")
        rec.pop("reasons", None)
        out = _reach([rec])
        self.assertEqual(out["class_census"][ADM.CLASS_UNMEASURED], 1)

    def test_a_refused_turnover_budget_is_UNDECIDED_not_open(self):
        """Бюджет при МЕНЬШЕМ обороте может пройти — но это не измерено."""
        out = _reach([_rec(1)])
        self.assertEqual(out["fires"][0]["arming_without_grant"],
                         ADM.ARM_UNDECIDED)
        self.assertIn("day_turnover_ok", out["fires"][0]["arming_blocking_gates"])

    def test_a_budget_that_PASSED_at_the_bigger_move_stays_passed_when_cut(self):
        """Монотонность: пройденный бюджет при меньшем обороте остаётся пройденным."""
        out = _reach([_rec(1, gates={"week_turnover_ok": True, "day_turnover_ok": True})])
        self.assertEqual(out["fires"][0]["arming_without_grant"], ADM.ARM_OPEN)

    def test_an_unmeasured_record_is_not_counted_as_judged(self):
        rec = _rec(1)
        rec.pop("gates")
        rec.pop("reasons", None)
        out = _reach([rec])
        self.assertEqual(out["measured_records"], 0)
        self.assertEqual(out["verdict"], ADM.ADM_UNMEASURED,
                         "ни одной измеренной записи ⇒ НЕ ИЗМЕРЕНО, а не «не прошло»")


class TheRuleLivesBehindOneDoor(unittest.TestCase):
    """Правило разрешения не переписано здесь — зовётся дверь `cio_trial`."""

    def test_a_substituted_door_changes_the_answer(self):
        calls = []

        def fake(failing, *, gain_pp, min_gain_pp):
            calls.append(sorted(failing))
            return [(CT.BLOCK_ECONOMIC, ["payback_within_horizon"])], None

        out = ADM.admissible_size_reach([_rec(1)], params=_PAPER,
                                        grant_blockers_fn=fake)
        self.assertTrue(calls, "дверь не позвана ⇒ правило живёт ВТОРОЙ копией здесь")
        self.assertEqual(out["verdict"], ADM.ADM_NEVER)

    def test_the_door_is_the_same_one_that_judges_the_live_move(self):
        """Та же функция, которой `apply_trial_grant` решает живой ход."""
        import inspect
        src = inspect.getsource(CT.apply_trial_grant)
        self.assertIn("grant_blockers", src)
        self.assertIs(CT.grant_blockers,
                      __import__("spa_core.paper_trading.cio_trial",
                                 fromlist=["grant_blockers"]).grant_blockers)

    def test_the_gate_state_reader_is_the_shadow_evals_own(self):
        seen = []

        def fake_state(rec):
            seen.append(rec.get("cycle_date"))
            return None, "unmeasured"

        out = ADM.admissible_size_reach([_rec(1)], params=_PAPER,
                                        gate_state_fn=fake_state)
        self.assertTrue(seen, "состояние гейтов читается НЕ дверью соседа")
        self.assertEqual(out["verdict"], ADM.ADM_UNMEASURED)

    def test_thresholds_come_from_the_live_contract_not_from_literals(self):
        out = _reach([_rec(1)])
        self.assertEqual(out["params"]["max_trade_usd"], _PAPER.max_trade_usd)
        self.assertEqual(out["params"]["min_gain_pp"], _PAPER.min_gain_pp)
        self.assertEqual(out["params"]["policy_version"], _PAPER.version)

    def test_a_stricter_contract_moves_the_admissible_size(self):
        """Потолок читается у контракта: другая колонка ⇒ другой допустимый ход."""
        pilot = TriggerParams.for_mode("pilot")
        self.assertLess(ADM.admissible_turnover_usd(100_000.0, pilot),
                        ADM.admissible_turnover_usd(100_000.0, _PAPER))


class TheReportSaysWhatItCounts(unittest.TestCase):
    """Единица счёта, оговорки и вопрос, который прибор НЕ решает."""

    def test_records_and_dates_are_two_numbers_not_one(self):
        out = _reach([_rec(1), _rec(1), _rec(2)])
        self.assertEqual(out["records"], 3)
        self.assertEqual(out["dates"], 2)

    def test_an_act_in_the_window_makes_the_question_moot(self):
        out = _reach([_rec(1)], acts=1)
        self.assertEqual(out["verdict"], ADM.ADM_MOOT)

    def test_the_proportional_cut_is_declared_an_assumption(self):
        joined = " ".join(_reach([_rec(1)])["assumptions"])
        self.assertIn("НИЖНЯЯ", joined, "оценка снизу обязана быть названа оценкой снизу")
        self.assertIn("ЗАВЫШЕНА", joined, "направление ошибки стоимости не объявлено")

    def test_the_bar_is_the_BASE_threshold_not_the_reversal_premium(self):
        """Разрешение снимает НАДБАВКУ за разворот, а базовый порог — нет.

        Запись с поднятой планкой (`required_gain_pp` 0.75) и урезанным выигрышем
        между базой и надбавкой обязана СРАБОТАТЬ: иначе прибор молча сузил бы
        ответ владельца, подставив вместо базы планку того дня.
        """
        rec = _rec(1, gain_pp=1.70, payback_days=9.0, required_gain_pp=0.75)
        cut = ADM.cut_to_admissible(rec, _PAPER)[0]
        self.assertTrue(_PAPER.min_gain_pp <= cut["gain_pp_cut"] < 0.75,
                        "сцена не воспроизводит предмет: выигрыш обязан лежать "
                        "МЕЖДУ базой и надбавкой")
        self.assertEqual(_reach([rec])["verdict"], ADM.ADM_FIRES)

    def test_fires_after_the_grant_are_counted_separately(self):
        """Дата выдачи разрешения берётся у двери, а не literal'ом здесь."""
        granted = str(CT.TRIAL_GRANT["granted_at"])[:10]
        before = dict(_rec(1)); before["cycle_date"] = "2000-01-01"
        after = dict(_rec(1)); after["cycle_date"] = granted
        out = _reach([before, after])
        self.assertEqual(len(out["fires"]), 2)
        self.assertEqual(out["fires_after_grant_records"], 1)


class TheOfficeStepReadsIt(unittest.TestCase):
    """Прибор без читателя — сирота (урок ADR-843). Читатель проверяется НАСТОЯЩИЙ."""

    @staticmethod
    def _office():
        spec = importlib.util.spec_from_file_location(
            "cor_adm", _REPO / "scripts" / "consume_office_reports.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_the_office_step_prints_the_block(self):
        cor = self._office()
        # Отметка времени у сцены артефакта — требование двери объявлений
        # (`test_office_declaration_doors`): документ без неё учит выжимку
        # обходиться без свежести, а потолок класса может только убывать.
        doc = {"status": "NOT_READY", "ready_to_arm": False, "observation_days": 84,
               "generated_at": _now_iso(),
               "counts": {"act": 0}, "criteria": [],
               "arming_blockade": {"verdict": STE.BLOCKADE_NO_SINGLE, "reason": "—"},
               "trial_grant_reach": {"verdict": STE.REACH_BLOCKED, "reason": "—"},
               "admissible_size_reach": _reach([_rec(1)])}
        text = "\n".join(cor._summarize_json(
            str(_REPO / "data" / "shadow_trigger_evaluation.json"), doc,
            root=str(_REPO), artifact_root=str(_REPO)))
        self.assertIn("урезанный до допустимого", text,
                      "шаг 0-офис блок НЕ читает — прибор остался бы сиротой")
        self.assertIn(ADM.ADM_FIRES, text)

    def test_the_office_declares_the_field_it_reads(self):
        cor = self._office()
        name = "shadow_trigger_evaluation.json"
        self.assertIn("admissible_size_reach", cor._READ_SCHEMA.get(name, ()),
                      "необъявленное чтение молча станет None в строке оркестратора")

    def test_a_missing_block_is_the_third_outcome_not_silence(self):
        text = "\n".join(ADM.format_admissible_reach(None))
        self.assertIn("НЕ ИЗМЕРЕН", text)
        self.assertIn("admissible_size_reach", text)


class TheLiveArtifactCarriesIt(unittest.TestCase):
    """Блок обязан появляться в САМОМ отчёте, а не только в функции."""

    def test_evaluate_window_carries_the_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            (data_dir / "allocation_rationale_history.jsonl").write_text(
                json.dumps(_rec(1)) + "\n", encoding="utf-8")
            doc = STE.evaluate_window(data_dir, write=False)
        self.assertIn("admissible_size_reach", doc,
                      "ключа нет в отчёте ⇒ читателю нечего читать")
        self.assertEqual(doc["admissible_size_reach"]["verdict"], ADM.ADM_FIRES)

    def test_the_summary_prints_the_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            (data_dir / "allocation_rationale_history.jsonl").write_text(
                json.dumps(_rec(1)) + "\n", encoding="utf-8")
            doc = STE.evaluate_window(data_dir, write=False)
        self.assertIn("урезанный до допустимого", STE.format_summary(doc))

    def test_it_changes_no_arming_verdict(self):
        """ADVISORY: `ready_to_arm` этим блоком не двигается ни в одну сторону."""
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            (data_dir / "allocation_rationale_history.jsonl").write_text(
                json.dumps(_rec(1)) + "\n", encoding="utf-8")
            doc = STE.evaluate_window(data_dir, write=False)
        self.assertFalse(doc["ready_to_arm"])
        self.assertEqual(doc["admissible_size_reach"]["verdict"], ADM.ADM_FIRES)


if __name__ == "__main__":   # pragma: no cover
    unittest.main()
