"""Тесты intraday-сенсора просадки (ADR-068).

Positive control — сценарий, ради которого сенсор существует: депег −30%
держимого протокола ЧЕРЕЗ ЧАС после цикла. Суточный расчёт слеп до утра;
сенсор обязан насчитать dd ≥ 10% ЧЕРЕЗ ОБЩУЮ формулу governance и вызвать
активацию. Активация в тестах ИНЪЕКТИРУЕТСЯ — живые kill-файлы и Telegram
из тестов не трогаются никогда (класс tests-write-live-alert-state).

Обе стороны каждой проверки: малый дрейф ⇒ NONE без действий; протухший peg ⇒
UNCHECKED без вызова лестницы; непокрытая позиция ⇒ номинал (не фабрикация)
+ HARD по измеренной части легитимен; границы 5/10% — у единого
классификатора, здесь только проверяется, что сенсор ему подчиняется.
Часы и все входы инъектируются (время — вход).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import unittest

from spa_core.governance.kill_switch import TIER_HARD_KILL, TIER_NONE, TIER_SOFT_DERISK
from spa_core.monitoring import intraday_equity as ie

NOW = dt.datetime(2030, 6, 10, 7, 0, tzinfo=dt.timezone.utc)  # FROZEN-DATE-OK: injected-clock — часы инъектируются


def positions(book=None, cash=15000.0, ts=None):
    return {"generated_at": (ts or NOW - dt.timedelta(hours=1)).isoformat(),
            "positions": book if book is not None else
            {"morpho_steakhouse": 40000.0, "pendle": 20000.0,
             "maple": 20000.0, "aave_v3": 5000.0},
            "cash_usd": cash, "capital_usd": 100000.0}


def peg(devs: dict, ts=None):
    return {"generated_at": (ts or NOW - dt.timedelta(minutes=5)).isoformat(),
            "statuses": [{"adapter_id": a, "deviation_pct": d} for a, d in devs.items()]}


def curve(closes=(100000.0, 100500.0, 100762.0)):
    base = dt.date(2030, 6, 7)
    return {"daily": [{"date": (base + dt.timedelta(days=i)).isoformat(),
                       "close_equity": c} for i, c in enumerate(closes)]}


class Estimate(unittest.TestCase):
    def test_quiet_day_is_none_no_action(self):
        calls = []
        r = ie.compute_estimate(positions(), peg({p: 0.0 for p in
                                                  ("morpho_steakhouse", "pendle",
                                                   "maple", "aave_v3")}),
                                curve(), NOW)
        self.assertEqual(r["status"], "OK")
        self.assertEqual(r["tier"], TIER_NONE)
        self.assertEqual(r["marks"], [])
        self.assertEqual(r["equity_estimate_usd"], 100000.0)

    def test_positive_control_intraday_depeg_fires_hard(self):
        """Ядро ADR-068: депег −30% morpho (40k) через час после цикла —
        est = 100000 − 12000 = 88000; peak 100762 ⇒ dd ≈ 12.67% ≥ 10% ⇒ HARD.
        Суточный расчёт этого не увидел бы до следующего утра."""
        devs = {"morpho_steakhouse": -30.0, "pendle": 0.0, "maple": 0.0, "aave_v3": 0.0}
        r = ie.compute_estimate(positions(), peg(devs), curve(), NOW)
        self.assertEqual(r["tier"], TIER_HARD_KILL)
        self.assertEqual(r["equity_estimate_usd"], 88000.0)
        self.assertGreaterEqual(r["drawdown_pct"], 10.0)
        self.assertEqual(len(r["marks"]), 1)
        self.assertEqual(r["marks"][0]["markdown_usd"], -12000.0)

    def test_soft_band_classified_by_shared_ladder(self):
        """Депег −16% morpho ⇒ est 93600, dd ≈ 7.1% ⇒ SOFT (границы — у
        classify_drawdown_pct, сенсор лишь подчиняется)."""
        devs = {"morpho_steakhouse": -16.0, "pendle": 0.0, "maple": 0.0, "aave_v3": 0.0}
        r = ie.compute_estimate(positions(), peg(devs), curve(), NOW)
        self.assertEqual(r["tier"], TIER_SOFT_DERISK)

    def test_positive_deviation_is_never_marked_up(self):
        """Премия к пегу не смеет прятать просадку другой позиции."""
        devs = {"morpho_steakhouse": -16.0, "pendle": +5.0, "maple": 0.0, "aave_v3": 0.0}
        r = ie.compute_estimate(positions(), peg(devs), curve(), NOW)
        self.assertEqual(r["equity_estimate_usd"], 93600.0)  # pendle по номиналу

    def test_uncovered_position_not_fabricated_but_measured_part_can_fire(self):
        """maple без peg-строки ⇒ номинал + coverage=partial; измеренного
        депега morpho −30% достаточно для HARD и без maple."""
        devs = {"morpho_steakhouse": -30.0, "pendle": 0.0, "aave_v3": 0.0}
        r = ie.compute_estimate(positions(), peg(devs), curve(), NOW)
        self.assertEqual(r["coverage"], "partial")
        self.assertEqual(r["uncovered_positions"], ["maple"])
        self.assertEqual(r["tier"], TIER_HARD_KILL)

    def test_stale_peg_is_unchecked_no_ladder_call(self):
        """Протухший peg ⇒ НЕ ИЗМЕРЕНО: никакой лестницы на старых данных."""
        stale = NOW - dt.timedelta(minutes=45)
        r = ie.compute_estimate(positions(),
                                peg({"morpho_steakhouse": -30.0}, ts=stale),
                                curve(), NOW)
        self.assertEqual(r["status"], "UNCHECKED")
        self.assertIsNone(r["tier"])

    def test_stale_positions_is_unchecked(self):
        old = NOW - dt.timedelta(hours=40)
        r = ie.compute_estimate(positions(ts=old), peg({"morpho_steakhouse": 0.0}),
                                curve(), NOW)
        self.assertEqual(r["status"], "UNCHECKED")

    def test_missing_inputs_are_unchecked_not_zero_equity(self):
        r = ie.compute_estimate(None, None, None, NOW)
        self.assertEqual(r["status"], "UNCHECKED")
        self.assertEqual(len(r["unchecked"]), 3)


class RunAndActivation(unittest.TestCase):
    def _root(self, td, devs):
        os.makedirs(os.path.join(td, "data"))
        for rel, doc in [("data/current_positions.json", positions()),
                         ("data/peg_report.json", peg(devs)),
                         ("data/equity_curve_daily.json", curve())]:
            with open(os.path.join(td, rel), "w", encoding="utf-8") as f:
                json.dump(doc, f)
        return td

    def test_hard_calls_injected_activation_and_writes_report(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td, {"morpho_steakhouse": -30.0, "pendle": 0.0,
                                   "maple": 0.0, "aave_v3": 0.0})
            calls = []
            r = ie.run(root=root, now=NOW,
                       activate=lambda rt, reason: calls.append(reason) or True)
            self.assertEqual(r["tier"], TIER_HARD_KILL)
            self.assertTrue(r["kill_activated"])
            self.assertEqual(len(calls), 1)
            self.assertIn("intraday drawdown", calls[0])
            on_disk = json.load(open(os.path.join(root, "data", "intraday_equity.json")))
            self.assertEqual(on_disk["tier"], TIER_HARD_KILL)

    def test_quiet_run_never_touches_activation(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td, {p: 0.0 for p in ("morpho_steakhouse", "pendle",
                                                    "maple", "aave_v3")})
            calls = []
            r = ie.run(root=root, now=NOW,
                       activate=lambda rt, reason: calls.append(reason) or True)
            self.assertEqual(r["tier"], TIER_NONE)
            self.assertEqual(calls, [])
            self.assertNotIn("kill_activated", r)

    def test_unchecked_run_never_activates(self):
        """Даже депег −30% в ПРОТУХШЕМ отчёте не смеет убить портфель."""
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td, {})
            with open(os.path.join(td, "data", "peg_report.json"), "w") as f:
                json.dump(peg({"morpho_steakhouse": -30.0},
                              ts=NOW - dt.timedelta(hours=2)), f)
            calls = []
            r = ie.run(root=root, now=NOW,
                       activate=lambda rt, reason: calls.append(reason) or True)
            self.assertEqual(r["status"], "UNCHECKED")
            self.assertEqual(calls, [])


class LiveSanity(unittest.TestCase):
    def test_live_run_is_measured_and_quiet_or_honest(self):
        """На проде: сенсор обязан отработать по живым файлам (write=False —
        живой отчёт не подменяем из теста) и быть либо измеренным, либо честно
        UNCHECKED; фабрикация équity исключена схемой."""
        if not os.path.exists(os.path.join(ie.REPO_ROOT, "data", "peg_report.json")):
            self.skipTest("не прод-хост")
        calls = []
        r = ie.run(root=ie.REPO_ROOT, now=dt.datetime.now(dt.timezone.utc),
                   activate=lambda rt, reason: calls.append(reason) or True,
                   write=False)
        self.assertIn(r["status"], ("OK", "UNCHECKED"))
        if r["status"] == "OK":
            self.assertIsNotNone(r["drawdown_pct"])
            self.assertIn(r["tier"], (TIER_NONE, TIER_SOFT_DERISK, TIER_HARD_KILL))


if __name__ == "__main__":
    unittest.main()
