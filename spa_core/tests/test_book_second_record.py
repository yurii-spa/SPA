#!/usr/bin/env python3
"""Вторая запись о деньгах: сходится ли книга с журналом ходов.

Шаг 3 из трёх до go-live (ADR-286 §1), вторая половина. Первая — независимое
наблюдение — упирается в ключи владельца и здесь НЕ решается (ADR-257/349).

Сцены синтетические: живой `data/` тест не читает НИКОГДА — вердикт, зависящий от
состояния боевого дерева, отвечает не на тот вопрос (`test_verdict_decided_by_live_data_dir`).

**Главное, что здесь проверяется, — РАЗЛИЧЕНИЕ, а не обнаружение.** Прибор обязан
отличать дыру в записи о деньгах от переименования ключа пула, и обе стороны этого
различения имеют цену ошибки:

* назвать переименование дырой — ложная тревога о деньгах;
* простить дыру как переименование («суммы же сошлись») — слепота ровно на том классе,
  ради которого прибор написан.

Замер 12.09 на живой книге дал по одному экземпляру КАЖДОГО рода, и оба рода настоящие:
T008 (журнал пуст с 20.06 по 23.08, $94 999.88 → $80 000.00) и T034 (слияние ключа
`fluid_usdc` → `fluid_fusdc`, ADR-331/335, суммы равны).
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("_bsr", ROOT / "scripts" / "book_second_record.py")
bsr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bsr)


def _trade(tid, frm, to):
    return {"trade_id": tid, "ts": f"2026-06-{int(tid[1:]):02d}T00:00:00+00:00",
            "type": "rebalance", "from_allocation": frm, "to_allocation": to}


class _Scene(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="spa_bsr_"))

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def write(self, trades, positions=None):
        (self.d / "trades.json").write_text(json.dumps(trades), encoding="utf-8")
        if positions is None:
            positions = {"positions": dict(trades[-1]["to_allocation"])}
        (self.d / "current_positions.json").write_text(json.dumps(positions), encoding="utf-8")
        return bsr.measure(str(self.d))


class AContinuousChainReconciles(_Scene):
    def test_a_clean_book_reconciles(self):
        r = self.write([_trade("T1", {}, {"aave_v3": 100.0}),
                        _trade("T2", {"aave_v3": 100.0}, {"maple": 60.0, "aave_v3": 40.0})])
        self.assertTrue(r["reconciles"])
        self.assertEqual(r["chain_breaks"], [])
        self.assertIsNone(r["terminal_divergence"])


class TheTwoKindsAreTold(_Scene):
    """Оба направления ошибки различения — каждое своим контролем."""

    def test_money_that_moved_without_a_record_is_a_gap(self):
        """Положительный контроль формы T008: суммы разошлись."""
        r = self.write([_trade("T1", {}, {"aave_v3": 100.0}),
                        _trade("T2", {"aave_v3": 85.0}, {"maple": 85.0})])
        self.assertEqual([b["kind"] for b in r["chain_breaks"]], ["money_gap"])
        self.assertEqual(r["chain_breaks"][0]["gap_usd"], -15.0)
        self.assertFalse(r["reconciles"])

    def test_a_renamed_key_is_named_and_is_NOT_a_money_gap(self):
        """Форма T034: слияние ключа пула. Суммы равны — деньгами это не является."""
        r = self.write([_trade("T1", {}, {"fluid_usdc": 100.0}),
                        _trade("T2", {"fluid_fusdc": 100.0}, {"maple": 100.0})])
        self.assertEqual([b["kind"] for b in r["chain_breaks"]], ["renamed_key"])
        self.assertEqual(r["money_gaps"], [])
        self.assertEqual(r["chain_breaks"][0]["keys_only_before"], ["fluid_usdc"])
        self.assertEqual(r["chain_breaks"][0]["keys_only_after"], ["fluid_fusdc"])

    def test_a_rename_is_NOT_silently_forgiven(self):
        """Обратная сторона: «суммы сошлись» НЕ означает «сходится».

        Прощать переименование молча значило бы ослепить прибор на дефекте ИМЕНИ —
        том самом, на котором уже один раз ослеп денежный гейт (ADR-331/335).
        """
        r = self.write([_trade("T1", {}, {"fluid_usdc": 100.0}),
                        _trade("T2", {"fluid_fusdc": 100.0}, {"maple": 100.0})])
        self.assertFalse(r["reconciles"], "переименование обязано быть НАЗВАНО, а не прощено")

    def test_a_gap_hidden_behind_a_rename_is_still_a_gap(self):
        """Смешанный случай: имя сменилось И денег стало меньше. Род — дыра."""
        r = self.write([_trade("T1", {}, {"fluid_usdc": 100.0}),
                        _trade("T2", {"fluid_fusdc": 85.0}, {"maple": 85.0})])
        self.assertEqual([b["kind"] for b in r["chain_breaks"]], ["money_gap"])


class TheEndMustMeetTheBook(_Scene):
    def test_a_book_that_disagrees_with_the_last_trade_is_named(self):
        r = self.write([_trade("T1", {}, {"aave_v3": 100.0})],
                       positions={"positions": {"aave_v3": 91.0}})
        self.assertIsNotNone(r["terminal_divergence"])
        self.assertEqual(r["terminal_divergence"]["per_key"], {"aave_v3": [100.0, 91.0]})
        self.assertFalse(r["reconciles"])

    def test_a_cent_of_rounding_is_not_a_divergence(self):
        """Допуск существует, и его граница названа: книга ведётся в центах."""
        r = self.write([_trade("T1", {}, {"aave_v3": 100.0})],
                       positions={"positions": {"aave_v3": 100.004}})
        self.assertIsNone(r["terminal_divergence"])

    def test_the_tolerance_cannot_swallow_a_real_divergence(self):
        """Контроль на сам допуск: иначе он молча стал бы глушилкой."""
        r = self.write([_trade("T1", {}, {"aave_v3": 100.0})],
                       positions={"positions": {"aave_v3": 100.02}})
        self.assertIsNotNone(r["terminal_divergence"])


class NotMeasuredIsItsOwnOutcome(unittest.TestCase):
    """Инв. #17: «не смогли» никогда не выдаётся за «сходится»."""

    def test_a_missing_data_dir_is_not_a_finding(self):
        with self.assertRaises(bsr.NotMeasured) as ctx:
            bsr.measure("/nonexistent/spa/data")
        self.assertIn("ШТАТНО", str(ctx.exception))

    def test_a_missing_journal_refuses(self):
        d = Path(tempfile.mkdtemp(prefix="spa_bsr_empty_"))
        try:
            with self.assertRaises(bsr.NotMeasured) as ctx:
                bsr.measure(str(d))
            self.assertIn("trades.json", str(ctx.exception))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_an_unparsable_journal_refuses(self):
        d = Path(tempfile.mkdtemp(prefix="spa_bsr_broken_"))
        try:
            (d / "trades.json").write_text("{не json", encoding="utf-8")
            with self.assertRaises(bsr.NotMeasured) as ctx:
                bsr.measure(str(d))
            self.assertIn("не разобран", str(ctx.exception))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_an_empty_journal_refuses_rather_than_reconciling(self):
        d = Path(tempfile.mkdtemp(prefix="spa_bsr_zero_"))
        try:
            (d / "trades.json").write_text("[]", encoding="utf-8")
            (d / "current_positions.json").write_text('{"positions": {}}', encoding="utf-8")
            with self.assertRaises(bsr.NotMeasured) as ctx:
                bsr.measure(str(d))
            self.assertIn("пуст", str(ctx.exception))
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_a_book_without_positions_refuses(self):
        d = Path(tempfile.mkdtemp(prefix="spa_bsr_nopos_"))
        try:
            (d / "trades.json").write_text(json.dumps([_trade("T1", {}, {"a": 1.0})]), encoding="utf-8")
            (d / "current_positions.json").write_text('{"capital_usd": 100000}', encoding="utf-8")
            with self.assertRaises(bsr.NotMeasured) as ctx:
                bsr.measure(str(d))
            self.assertIn("positions", str(ctx.exception))
        finally:
            shutil.rmtree(d, ignore_errors=True)


class TheExitCodeSeparatesThreeOutcomes(unittest.TestCase):
    """Код возврата — носитель третьего исхода, и 1 не смешана с 2."""

    def test_not_measured_returns_two_not_one(self):
        self.assertEqual(bsr.main(["--data-dir", "/nonexistent/spa/data"]), 2)

    def test_a_clean_book_returns_zero(self):
        d = Path(tempfile.mkdtemp(prefix="spa_bsr_ok_"))
        try:
            (d / "trades.json").write_text(json.dumps([_trade("T1", {}, {"a": 1.0})]), encoding="utf-8")
            (d / "current_positions.json").write_text('{"positions": {"a": 1.0}}', encoding="utf-8")
            self.assertEqual(bsr.main(["--data-dir", str(d)]), 0)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_a_divergence_returns_one(self):
        d = Path(tempfile.mkdtemp(prefix="spa_bsr_bad_"))
        try:
            (d / "trades.json").write_text(json.dumps(
                [_trade("T1", {}, {"a": 100.0}), _trade("T2", {"a": 85.0}, {"b": 85.0})]),
                encoding="utf-8")
            (d / "current_positions.json").write_text('{"positions": {"b": 85.0}}', encoding="utf-8")
            self.assertEqual(bsr.main(["--data-dir", str(d)]), 1)
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
