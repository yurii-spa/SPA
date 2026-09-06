"""ADR-240 — слой триггеров ребаланса отвечал «не надо» ИЗ ПУСТОТЫ.

Каждый тест здесь — положительный контроль на замер 2026-09-06 (цикл #500),
сделанный на ЖИВЫХ артефактах прод-дерева, а не на предположении. Правило
`.claude/rules/deployment.md`: проверка, не видевшая настоящей поломки, —
украшение.

Что было измерено в тот день (два артефакта ОДНОГО прогона дневного цикла):

* ``data/risk_limits_check.json`` (06:00:27Z) — ``DL-03 Adapter Concentration:
  compound_v3 at 42.1% exceeds limit 40.0%``, ``status: "FAIL"``;
* ``data/rebalance_trigger.json`` (06:01:32Z) — ``rt03.dl03_fired: false``.

Причин у расхождения оказалось ДВЕ, и каждая ломает по-своему:

1. **Вход не передавался.** Живой путь `evaluate_from_state` звал
   `smart_rebalance_check` четырьмя аргументами и НИ РАЗУ не передавал
   `daily_limits_result`, режим и дату последней перекладки. Три проверки из
   пяти отвечали `triggered: false` при любом состоянии мира.
2. **Формы не совпадали.** Даже переданный вердикт RT-03 не прочёл бы:
   `DailyLimitsChecker` пишет ``checks`` СПИСКОМ записей
   ``{"id": "DL-03", "status": "FAIL"}``, а читатель искал СЛОВАРЬ с ключом
   ``triggered``, которого у производителя нет вовсе.

Плюс два входных файла, которых не пишет ни один производитель
(``adapter_snapshot.json``, ``target_allocation.json``): их отсутствие давало
дрейф 0.0 и разрыв доходности 0.0 — числа, неотличимые от «посмотрели, всё
ровно».

Дифференциал на снимке 06.09 (тот же вход, до и после):

    should_rebalance  false      → true (RT-01, RT-03)
    rt01.max_drift    0.0        → 29.64 пп (aave_v3)
    rt03.dl03_fired   false      → true
    rt04.days_since   null       → 6
    rt05.best         null / 0.0 → compound_v3 / 0.737 пп
    verdict           (нет поля) → REBALANCE, `unmeasured` = [RT-02]

ADVISORY. Капитал по этому вердикту не двигается ни на цент: у артефакта нет
исполняющего потребителя, живой ход решают аллокатор + гейты ADR-060 + демпфер
ADR-168. Предмет здесь — ЧЕСТНОСТЬ сигнала, а не новое право на сделку.

Время в фикстурах относительное (`_freshness.ts`) — литеральных дат нет
намеренно: `check_rt04_calendar` спрашивает календарь хоста, и литерал стал бы
той самой бомбой из правила о времени.
"""
from __future__ import annotations

import ast
import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.paper_trading.rebalance_trigger import (
    RebalanceTrigger,
    evaluate_from_state,
    smart_rebalance_check,
)
from spa_core.tests._freshness import ts

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _dl_doc(status: str = "FAIL", pct: float = 42.1053) -> dict:
    """Ровно то, что пишет ``DailyLimitsChecker.save_result`` (форма 06.09)."""
    return {
        "gate": "WARN",
        "checks": [
            {"id": "DL-01", "name": "Daily Loss", "limit": 2.0,
             "status": "PASS", "value": -0.0114},
            {"id": "DL-03", "name": "Adapter Concentration", "limit": 40.0,
             "status": status, "value": pct, "top_adapter": "compound_v3",
             "message": f"compound_v3 at {pct:.1f}% exceeds limit 40.0%"},
        ],
        "halt_reasons": [],
        "warn_reasons": (
            [f"DL-03 Adapter Concentration: compound_v3 at {pct:.1f}% "
             f"exceeds limit 40.0%"] if status == "FAIL" else []),
        "skip_reasons": [],
        "checked_at": ts(hours_ago=0.5),
    }


class TestRT03ReadsWhatTheProducerActuallyWrites(unittest.TestCase):
    """Пункт 2 замера: формы не совпадали."""

    def test_list_of_records_with_status_fail_fires(self):
        """Авария 06.09 дословно: DL-03 в списке, ключа `triggered` нет.

        `warn_reasons` СНЯТ намеренно. Первая редакция этого теста оставляла
        его на месте — и мутация «ослепить чтение списка» не красила НИЧЕГО:
        находку подхватывала соседняя ветка по агрегированной строке. Контроль,
        зелёный при выключенном предмете, есть украшение (замер мутаций #500).
        """
        doc = _dl_doc()
        doc.pop("warn_reasons")
        res = RebalanceTrigger().check_rt03_risk_gate(doc)
        self.assertTrue(res["triggered"])
        self.assertTrue(res["dl03_fired"])
        self.assertTrue(res["measured"])

    def test_the_two_readings_are_independent(self):
        """Каждая форма ловит аварию САМА — иначе одна прикрывает другую."""
        only_list = {"checks": [{"id": "DL-03", "status": "FAIL"}]}
        only_line = {"warn_reasons": ["DL-03 Adapter Concentration: 42.1%"]}
        t = RebalanceTrigger()
        self.assertTrue(t.check_rt03_risk_gate(only_list)["triggered"])
        self.assertTrue(t.check_rt03_risk_gate(only_line)["triggered"])

    def test_aggregated_warn_reason_line_fires(self):
        """Того же документа хватает и одной агрегированной строкой."""
        doc = {"warn_reasons": ["DL-03 Adapter Concentration: compound_v3 at 42.1%"]}
        self.assertTrue(RebalanceTrigger().check_rt03_risk_gate(doc)["triggered"])

    def test_passing_dl03_does_not_fire(self):
        """Контроль на ложное срабатывание: тот же документ со `status: PASS`."""
        res = RebalanceTrigger().check_rt03_risk_gate(_dl_doc(status="PASS"))
        self.assertFalse(res["triggered"])
        self.assertTrue(res["measured"])

    def test_other_check_failing_does_not_fire_rt03(self):
        """DL-01 FAIL — не предмет RT-03; иначе сторож звал бы на любую поломку."""
        doc = {"checks": [{"id": "DL-01", "status": "FAIL"}], "warn_reasons": []}
        self.assertFalse(RebalanceTrigger().check_rt03_risk_gate(doc)["triggered"])

    def test_absent_input_is_a_third_outcome_not_a_no(self):
        """«DL-03 не спрашивали» ≠ «DL-03 не сработал»."""
        for empty in (None, {}, [], "нет"):
            res = RebalanceTrigger().check_rt03_risk_gate(empty)
            self.assertFalse(res["triggered"])
            self.assertFalse(res["measured"])
            self.assertIn("НЕ СПРАШИВАЛИ", res["unmeasured_reason"])

    def test_legacy_layouts_still_read(self):
        """Три прежних макета не ослаблены — на них стоят тесты с 2026 г."""
        t = RebalanceTrigger()
        self.assertTrue(t.check_rt03_risk_gate({"dl03_fired": True})["triggered"])
        self.assertTrue(t.check_rt03_risk_gate(
            {"checks": {"DL-03": {"triggered": True}}})["triggered"])
        self.assertTrue(t.check_rt03_risk_gate(
            {"checks": {"dl_03": {"triggered": True}}})["triggered"])


class TestVacuumIsNamedNotAnswered(unittest.TestCase):
    """Проверка без входа обязана СКАЗАТЬ это, а не отвечать «нет»."""

    def test_rt05_empty_universe_is_unmeasured(self):
        res = RebalanceTrigger().check_rt05_apy_spread(4.7, {})
        self.assertEqual(res["spread_pct"], 0.0)
        self.assertFalse(res["measured"])
        self.assertIn("сравнивать не с чем", res["unmeasured_reason"])

    def test_rt05_with_a_universe_is_measured(self):
        res = RebalanceTrigger().check_rt05_apy_spread(4.7, {"compound_v3": 5.43})
        self.assertTrue(res["measured"])
        self.assertIsNone(res["unmeasured_reason"])
        self.assertEqual(res["best_protocol"], "compound_v3")

    def test_rt02_without_any_regime_label_is_unmeasured(self):
        res = RebalanceTrigger().check_rt02_apy_opportunity(None, None, 191.7)
        self.assertFalse(res["measured"])
        self.assertIn("НЕ СПРАШИВАЛИ", res["unmeasured_reason"])

    def test_rt02_with_one_label_is_measured_and_says_no_change(self):
        res = RebalanceTrigger().check_rt02_apy_opportunity("VOLATILE", "VOLATILE", 191.7)
        self.assertTrue(res["measured"])
        self.assertFalse(res["triggered"])


class TestAggregateHasThreeOutcomes(unittest.TestCase):
    def test_nothing_measured_is_unchecked_not_no_trigger(self):
        out = smart_rebalance_check(
            current_positions={"aave_v3": 100000.0},
            target_positions={"aave_v3": 100000.0},
            current_apy_pct=None,
            available_apys=None,
            input_gaps={"rt01": "цели нет", "rt04": "цели нет"},
        )
        self.assertFalse(out["should_rebalance"])
        self.assertEqual(out["verdict"], "UNCHECKED")
        self.assertEqual(set(out["unmeasured"]),
                         {"RT-01", "RT-02", "RT-03", "RT-04", "RT-05"})

    def test_all_measured_and_quiet_is_no_trigger(self):
        """Пять входов на месте, ни один не сработал — вот это и есть «повода нет».

        Режим передаётся ЯВНО (`check_all`, а не `smart_rebalance_check`):
        второй ручки для него нет, и это само по себе — тот пробел, который
        живой путь называет вслух в `evaluate_from_state`.
        """
        out = RebalanceTrigger().check_all(
            current_weights={"aave_v3": 0.5, "compound_v3": 0.5},
            target_weights={"aave_v3": 0.5, "compound_v3": 0.5},
            current_regime="VOLATILE",
            new_regime="VOLATILE",
            apy_gain_bps=0.0,
            current_apy_pct=5.0,
            available_apys={"aave_v3": 5.05},
            last_rebalance_date=None,
            daily_limits_result=_dl_doc(status="PASS"),
        )
        self.assertEqual(out["unmeasured"], [])
        self.assertEqual(out["verdict"], "NO_TRIGGER")
        self.assertFalse(out["should_rebalance"])

    def test_a_gap_forbids_the_check_from_firing(self):
        """«Не измерено» не имеет права стать утверждением.

        Дрейф здесь ОГРОМЕН (100 пп) и математика сказала бы «сработал»; но
        цель читателю не досталась, значит утверждать нечего.
        """
        out = smart_rebalance_check(
            current_positions={"aave_v3": 100000.0},
            target_positions={"compound_v3": 100000.0},
            input_gaps={"rt01": "цель аллокатора не прочитана"},
        )
        self.assertNotIn("RT-01", out["triggered"])
        self.assertFalse(out["checks"]["rt01"]["measured"])
        self.assertIn("RT-01", out["unmeasured"])

    def test_a_fired_check_wins_over_gaps(self):
        out = smart_rebalance_check(
            current_positions={"aave_v3": 100000.0},
            target_positions={"aave_v3": 100000.0},
            daily_limits_result=_dl_doc(),
            input_gaps={"rt01": "цели нет"},
        )
        self.assertEqual(out["verdict"], "REBALANCE")
        self.assertIn("RT-03", out["triggered"])


class TestLivePathReadsRealArtifacts(unittest.TestCase):
    """Пункт 1 замера: вход не передавался. Проверяется ПОВЕДЕНИЕМ."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dir = Path(self.tmp)

    def _w(self, name: str, obj) -> None:
        (self.dir / name).write_text(json.dumps(obj), encoding="utf-8")

    def _live_shaped_tree(self) -> None:
        """Формы ровно как в прод-дереве 06.09 (имена и вложенность — те же)."""
        self._w("paper_trading_status.json", {
            "current_positions": {"compound_v3": 40000.0, "fluid_usdc": 20000.0,
                                  "maple": 20000.0, "morpho_blue_base": 10000.0,
                                  "aave_v3": 5000.0},
            "apy_today_pct": 4.6978,
        })
        self._w("allocation_rationale.json", {
            "generated_at": ts(hours_ago=0.8),
            "decision_shadow": {
                "decision": "HOLD",
                "legs": [
                    {"protocol": "aave_v3", "delta_usd": 28157.89, "direction": "increase"},
                    {"protocol": "fluid_usdc", "delta_usd": -20000.0, "direction": "decrease"},
                    {"protocol": "maple", "delta_usd": -20000.0, "direction": "decrease"},
                ],
            },
        })
        self._w("risk_limits_check.json", _dl_doc())
        self._w("adapter_status.json", {"adapters": {
            "compound_v3": {"live_apy": 5.4345, "live_apy_fresh": True},
            "aave_v3": {"live_apy": 2.5804, "live_apy_fresh": True},
            # Литерал НЕ должен участвовать: ставка, которую никто не наблюдал,
            # не может быть поводом переложить книгу (доктрина ADR-226).
            "moonwell_base": {"live_apy": 99.0, "live_apy_fresh": False,
                              "fallback_apy": 99.0},
        }})
        self._w("trades.json", [{"ts": ts(hours_ago=24 * 6), "delta_abs": 17368.42}])
        self._w("market_regime.json", {"regime": "VOLATILE"})

    def test_rt03_fires_from_the_real_daily_limits_artifact(self):
        """Авария целиком: тот же каталог — и RT-03 больше не молчит."""
        self._live_shaped_tree()
        out = evaluate_from_state(str(self.dir))
        self.assertTrue(out["checks"]["rt03"]["dl03_fired"])
        self.assertIn("RT-03", out["triggered"])
        self.assertEqual(out["inputs"]["daily_limits"], "risk_limits_check.json")

    def test_target_comes_from_the_rationale_legs(self):
        """`target_allocation.json` не пишет никто — цель берётся у аллокатора."""
        self._live_shaped_tree()
        out = evaluate_from_state(str(self.dir))
        rt01 = out["checks"]["rt01"]
        self.assertTrue(rt01["measured"])
        self.assertEqual(rt01["max_drift_adapter"], "aave_v3")
        self.assertGreater(rt01["max_drift_pct"], 5.0)
        self.assertIn("decision_shadow.legs", out["inputs"]["target"])

    def test_apy_universe_uses_observed_numbers_only(self):
        self._live_shaped_tree()
        out = evaluate_from_state(str(self.dir))
        rt05 = out["checks"]["rt05"]
        self.assertTrue(rt05["measured"])
        self.assertEqual(rt05["best_protocol"], "compound_v3")
        self.assertNotEqual(rt05["best_protocol"], "moonwell_base")

    def test_last_rebalance_date_comes_from_the_trades_journal(self):
        self._live_shaped_tree()
        out = evaluate_from_state(str(self.dir))
        self.assertIsNotNone(out["checks"]["rt04"]["days_since"])
        self.assertEqual(out["inputs"]["last_rebalance"], "trades.json")

    def test_regime_gap_is_named_not_invented(self):
        self._live_shaped_tree()
        out = evaluate_from_state(str(self.dir))
        rt02 = out["checks"]["rt02"]
        self.assertFalse(rt02["measured"])
        self.assertIn("ДВУХ отметок", rt02["unmeasured_reason"])
        self.assertIn("RT-02", out["unmeasured"])

    def test_empty_tree_says_unchecked_not_no_trigger(self):
        """Прежнее поведение — ровно `should_rebalance: false` и тишина."""
        out = evaluate_from_state(str(self.dir))
        self.assertFalse(out["should_rebalance"])
        self.assertEqual(out["verdict"], "UNCHECKED")
        self.assertIn("RT-01", out["unmeasured"])
        self.assertIn("RT-03", out["unmeasured"])
        self.assertIn("цель аллокатора не прочитана",
                      out["checks"]["rt01"]["unmeasured_reason"])

    def test_legacy_file_names_still_win(self):
        """Старые имена не ослаблены: на них стоят тесты, и они старше."""
        self._live_shaped_tree()
        self._w("target_allocation.json",
                {"target_positions": {"compound_v3": 95000.0}})
        out = evaluate_from_state(str(self.dir))
        self.assertEqual(out["inputs"]["target"], "target_allocation.json")


class TestWiringByCallForm(unittest.TestCase):
    """Проводку меряем ФОРМОЙ вызова: имя в комментарии — не вызов."""

    def _fn_source(self, name: str) -> ast.FunctionDef:
        path = os.path.join(REPO_ROOT, "spa_core", "paper_trading",
                            "rebalance_trigger.py")
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        self.fail(f"функция {name} не найдена")

    def test_live_reader_passes_the_inputs_it_reads(self):
        """Мутация «убрать аргумент» обязана красить ЭТОТ тест."""
        fn = self._fn_source("evaluate_from_state")
        passed: set[str] = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Call):
                fname = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if fname == "smart_rebalance_check":
                    passed = {kw.arg for kw in node.keywords if kw.arg}
        self.assertTrue(passed, "smart_rebalance_check не вызывается вовсе")
        for arg in ("daily_limits_result", "input_gaps", "last_rebalance_date",
                    "available_apys", "target_positions"):
            self.assertIn(arg, passed, f"живой путь не передаёт {arg}")

    def test_artifact_is_declared_in_both_homes(self):
        """Артефакт без манифеста и без объявления живёт БЕЗ SLO (замер #500)."""
        from spa_core.paper_trading.cycle_runner import PRODUCES

        self.assertIn("data/rebalance_trigger.json", PRODUCES)
        manifest = json.loads(Path(
            os.path.join(REPO_ROOT, "architecture", "manifest.json")
        ).read_text(encoding="utf-8"))
        entry = next((a for a in manifest["artifacts"]
                      if a.get("path") == "data/rebalance_trigger.json"), None)
        self.assertIsNotNone(entry, "артефакта нет в манифесте — SLO не назначен")
        self.assertEqual(entry["status"], "active")
        self.assertIn("orchestrator_protocol", entry["consumers"])
        self.assertIsInstance(entry.get("slo_hours"), int)


class TestOfficeStepNamesTheThirdOutcome(unittest.TestCase):
    """Ветка читателя проверяется ПОВЕДЕНИЕМ, а не наличием строки."""

    def _reader(self):
        import importlib.util

        path = os.path.join(REPO_ROOT, "scripts", "consume_office_reports.py")
        spec = importlib.util.spec_from_file_location("_office_reader_rt", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_unchecked_verdict_is_spoken_aloud(self):
        mod = self._reader()
        doc = {"should_rebalance": False, "triggered": [], "verdict": "UNCHECKED",
               "unmeasured": ["RT-01", "RT-03"], "checked_at": ts(hours_ago=0.5),
               "checks": {"rt01": {"triggered": False, "measured": False,
                                   "unmeasured_reason": "цель не прочитана"}}}
        text = "\n".join(mod._summarize_json("rebalance_trigger.json", doc))
        self.assertIn("UNCHECKED", text)
        self.assertIn("НЕ ИЗМЕРЕНО", text)
        self.assertIn("цель не прочитана", text)

    def test_pre_adr240_file_is_called_blind_not_calm(self):
        """Файл без поля `unmeasured` — ровно то, что лежало в проде 06.09."""
        mod = self._reader()
        doc = {"should_rebalance": False, "triggered": [],
               "checked_at": ts(hours_ago=0.5), "checks": {}}
        text = "\n".join(mod._summarize_json("rebalance_trigger.json", doc))
        self.assertIn("СЛЕПОТА", text)

    def test_advisory_boundary_is_stated(self):
        """Сигнал не есть право на сделку — и это сказано в самом выводе."""
        mod = self._reader()
        doc = {"should_rebalance": True, "triggered": ["RT-03"],
               "verdict": "REBALANCE", "unmeasured": [],
               "checked_at": ts(hours_ago=0.5),
               "checks": {"rt03": {"triggered": True, "measured": True}}}
        text = "\n".join(mod._summarize_json("rebalance_trigger.json", doc))
        self.assertIn("ADVISORY", text)
        self.assertIn("RT03", text.upper())


if __name__ == "__main__":
    unittest.main()
