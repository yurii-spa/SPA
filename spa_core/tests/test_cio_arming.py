"""Взвод CIO (ADR-324, решение владельца 11.09): вердикт советника решает перекладку.

Каждый тест — либо один из исходов решения, либо граница, которую взвод не смеет
сдвинуть: де-риск не ждёт, неизвестный вердикт ⇒ держать, невзведённая книга живёт
по прежнему правилу, параметры CIO не тронуты.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

from spa_core.paper_trading import cio_arming as ca

ROOT = Path(__file__).resolve().parents[2]
CUR = {"compound_v3": 40000.0, "fluid_usdc": 20000.0, "maple": 5000.0}
UP = {"compound_v3": 25000.0, "fluid_usdc": 0.0, "maple": 20000.0, "euler_v2": 20000.0}
CUT = {"compound_v3": 30000.0, "fluid_usdc": 0.0, "maple": 5000.0}


def _doc(decision, reasons=()):
    return {"decision_shadow": {"decision": decision, "reasons": list(reasons)}}


class Outcomes(unittest.TestCase):
    def test_act_moves_the_armed_book(self):
        ok, dec, _ = ca.trade_allowed("conservative", _doc("ACT"), CUR, UP)
        self.assertTrue(ok)
        self.assertEqual(dec, ca.ACT)

    def test_hold_keeps_the_armed_book_and_names_why(self):
        ok, dec, why = ca.trade_allowed(
            "conservative", _doc("HOLD", ["payback_too_long:43.6d"]), CUR, UP)
        self.assertFalse(ok)
        self.assertEqual(dec, ca.HOLD)
        self.assertIn("payback_too_long", why)

    def test_derisk_never_waits_for_the_verdict(self):
        """Стоп-кран и реакция на просадку не могут стоять в очереди за экономикой."""
        for doc in (_doc("HOLD", ["cooldown_active"]), None, {"error": "Boom"}):
            ok, dec, _ = ca.trade_allowed("conservative", doc, CUR, CUT)
            self.assertTrue(ok, doc)
            self.assertEqual(dec, ca.DERISK)

    def test_unknown_verdict_holds_fail_closed(self):
        for doc in (None, {"error": "KeyError", "mode": "SHADOW"}, {},
                    {"decision_shadow": {"decision": "MAYBE"}}, "мусор"):
            ok, dec, why = ca.trade_allowed("conservative", doc, CUR, UP)
            self.assertFalse(ok, doc)
            self.assertEqual(dec, ca.HOLD)
            self.assertIn("fail-CLOSED", why)

    def test_an_unarmed_book_is_left_to_the_old_rule(self):
        ok, dec, _ = ca.trade_allowed("not_a_book", _doc("HOLD"), CUR, UP)
        self.assertTrue(ok)
        self.assertEqual(dec, ca.UNARMED)


class PlacementIsNotAReshuffle(unittest.TestCase):
    """Замер 11.09: первая редакция взвода запрещала вложить в работу пустую книгу.

    CIO судит одно — окупается ли ПЕРЕТАСОВКА. Размещение денег и де-риск не
    перетасовка; для размещения простаивающего кэша это прямое решение владельца 30.08.
    """

    def test_initial_deployment_passes_under_hold(self):
        from spa_core.governance.churn_damper import REASON_INITIAL
        ok, _, why = ca.trade_allowed("conservative", _doc("HOLD", ["gain_below_band"]),
                                      {}, UP, damper_reason=REASON_INITIAL)
        self.assertTrue(ok, why)

    def test_placing_idle_cash_passes_under_hold(self):
        from spa_core.governance.churn_damper import REASON_PLACE_IDLE
        ok, _, why = ca.trade_allowed("conservative", _doc("HOLD"), CUR, UP,
                                      damper_reason=REASON_PLACE_IDLE)
        self.assertTrue(ok, why)

    def test_a_reshuffle_within_the_dampers_limits_still_needs_the_cio(self):
        """«Демпфер пропустил» ≠ «CIO разрешил»: иначе взвод ничего бы не менял."""
        from spa_core.governance.churn_damper import REASON_WITHIN_LIMITS
        ok, dec, _ = ca.trade_allowed("conservative", _doc("HOLD"), CUR, UP,
                                      damper_reason=REASON_WITHIN_LIMITS)
        self.assertFalse(ok)
        self.assertEqual(dec, ca.HOLD)

    def test_a_damper_that_could_not_decide_does_not_open_the_gate(self):
        """Демпфер при неизмеримом ходе пропускает (fail-open); CIO — нет (fail-CLOSED)."""
        from spa_core.governance.churn_damper import REASON_UNMEASURABLE
        ok, dec, _ = ca.trade_allowed("conservative", None, CUR, UP,
                                      damper_reason=REASON_UNMEASURABLE)
        self.assertFalse(ok)
        self.assertEqual(dec, ca.HOLD)


class TheArmingIsDeclaredHonestly(unittest.TestCase):
    def test_every_armed_book_names_who_when_and_why(self):
        self.assertTrue(ca.ARMED_BOOKS, "взвод объявлен пустым — проверки ниже ничего не значат")
        for book, meta in ca.ARMED_BOOKS.items():
            for key in ("armed_by", "armed_at", "source", "adr"):
                self.assertTrue(meta.get(key), f"{book}: нет поля {key}")

    def test_the_derisk_rule_is_the_dampers_function_not_a_copy(self):
        """Второе определение «де-риска» однажды разошлось бы с первым молча."""
        from spa_core.governance import churn_damper
        self.assertIs(ca.is_pure_reduction, churn_damper.is_pure_reduction)


class Wiring(unittest.TestCase):
    """Проводка — формой вызова в AST, а не подстрокой: проза о проводке её не заменяет."""

    def setUp(self):
        self.src = (ROOT / "spa_core" / "paper_trading" / "cycle_runner.py").read_text(
            encoding="utf-8")
        self.tree = ast.parse(self.src)

    def test_the_cycle_keeps_the_cio_document(self):
        hits = [n for n in ast.walk(self.tree)
                if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "_cio_doc" for t in n.targets)
                and isinstance(n.value, ast.Call)
                and getattr(n.value.func, "id", None) == "write_shadow_rationale"]
        self.assertTrue(hits, "вердикт CIO снова выбрасывается — взвод ничем не управляет")

    def test_the_trade_decision_reads_the_armed_verdict(self):
        calls = [n for n in ast.walk(self.tree)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr == "trade_allowed"]
        self.assertTrue(calls, "cycle_runner не спрашивает cio_arming.trade_allowed")
        traded = [n for n in ast.walk(self.tree)
                  if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == "traded" for t in n.targets)]
        self.assertTrue(traded)
        names = {x.id for n in traded for x in ast.walk(n.value) if isinstance(x, ast.Name)}
        self.assertIn("_cio_gate_ok", names,
                      "решение о перекладке не зависит от вердикта CIO")
        # эшелон: вердикт демпфера обязан остаться в том же решении рядом с CIO
        seg = "".join(ast.get_source_segment(self.src, n.value) or "" for n in traded)
        self.assertIn("_churn.allowed", seg, "взвод CIO вывел демпфер из решения")

    def test_the_cio_parameters_were_not_touched(self):
        """Прямое указание владельца: «мне не нужно настраивать параметры»."""
        from spa_core.allocator.rebalance_economics import TriggerParams
        p = TriggerParams()
        self.assertEqual((p.min_gain_pp, p.max_payback_days, p.min_hold_days,
                          p.act_cooldown_days, p.max_turnover_per_move,
                          p.max_turnover_per_week),
                         (0.5, 30.0, 3, 3, 0.15, 0.25))


class SleeveBooks(unittest.TestCase):
    """ADR-328: Balanced и Aggressive — ход, ПРЕДЛОЖЕННЫЙ rebalance_book, принимается
    только с разрешения CIO; до взвода книга двигалась каждый цикл без суждения."""

    BEFORE = [{"protocol": "aave_v3", "notional_usd": 60000.0, "mark_price": 1.0},
              {"protocol": "maple", "notional_usd": 30000.0}]
    SHUFFLE = [{"protocol": "aave_v3", "notional_usd": 30000.0},
               {"protocol": "morpho_blue", "notional_usd": 60000.0}]
    CUT = [{"protocol": "aave_v3", "notional_usd": 40000.0},
           {"protocol": "maple", "notional_usd": 30000.0}]

    def _gate(self, book_id, before, proposed, verdict=None, err=None):
        import types
        from unittest import mock
        ret = ({"error": err} if err else
               {"decision_shadow": {"decision": verdict or "HOLD", "reasons": ["x"]}})
        fake_ar = types.SimpleNamespace(write_shadow_rationale=lambda **kw: ret)
        with mock.patch.dict("sys.modules",
                             {"spa_core.paper_trading.allocation_rationale": fake_ar}):
            return ca.gate_sleeve_book(book_id, before, proposed, ["o"], ["c"], [],
                                       100000.0, "/nonexistent", today="2026-09-11",
                                       run_ts="2026-09-11T06:00:00Z")

    def test_both_sleeve_books_are_armed(self):
        self.assertTrue(ca.is_armed("balanced"))
        self.assertTrue(ca.is_armed("aggressive"))

    def test_hold_keeps_the_book_exactly_and_opens_nothing(self):
        book, opened, closed, note = self._gate("balanced", self.BEFORE, self.SHUFFLE, "HOLD")
        self.assertEqual(book, self.BEFORE, "книга сдвинулась при вердикте «держать»")
        self.assertIsNot(book, self.BEFORE, "вернули ТУ ЖЕ ссылку — начисление мутирует ноги")
        self.assertEqual((opened, closed), ([], []))
        self.assertIn("HOLD", note)

    def test_act_takes_the_proposed_book(self):
        book, opened, closed, _ = self._gate("aggressive", self.BEFORE, self.SHUFFLE, "ACT")
        self.assertEqual(book, self.SHUFFLE)
        self.assertEqual((opened, closed), (["o"], ["c"]))

    def test_derisk_passes_under_hold(self):
        book, *_ = self._gate("balanced", self.BEFORE, self.CUT, "HOLD")
        self.assertEqual(book, self.CUT, "сокращение позиции задержано вердиктом CIO")

    def test_initial_placement_of_an_empty_book_passes_under_hold(self):
        book, *_ = self._gate("balanced", [], self.SHUFFLE, "HOLD")
        self.assertEqual(book, self.SHUFFLE, "пустую книгу не дали вложить в работу")

    def test_a_failed_verdict_holds(self):
        book, opened, closed, note = self._gate("aggressive", self.BEFORE, self.SHUFFLE,
                                                err="KeyError")
        self.assertEqual(book, self.BEFORE)
        self.assertIn("fail-CLOSED", note)

    def test_an_exception_while_asking_the_cio_holds(self):
        """Выжившая мутация №3 (11.09): документ-ошибка и НАСТОЯЩЕЕ исключение — разные
        ветки. Без этого теста «упало ⇒ принять предложение» проходило зелёным."""
        import types
        from unittest import mock

        def boom(**kw):
            raise RuntimeError("советник недоступен")
        fake_ar = types.SimpleNamespace(write_shadow_rationale=boom)
        with mock.patch.dict("sys.modules",
                             {"spa_core.paper_trading.allocation_rationale": fake_ar}):
            book, opened, closed, note = ca.gate_sleeve_book(
                "balanced", self.BEFORE, self.SHUFFLE, ["o"], ["c"], [], 100000.0,
                "/nonexistent", today="2026-09-11", run_ts="2026-09-11T06:00:00Z")
        self.assertEqual(book, self.BEFORE, "исключение при вердикте приняло предложение")
        self.assertEqual((opened, closed), ([], []))
        self.assertIn("fail-CLOSED", note)

    def test_both_sleeve_cycles_route_the_proposal_through_the_gate(self):
        """Проводка ФОРМОЙ вызова: результат гейта обязан перезаписать `book`."""
        for fn, bid in (("hy_cycle.py", "balanced"), ("lp_cycle.py", "aggressive")):
            tree = ast.parse((ROOT / "spa_core" / "paper_trading" / fn).read_text(encoding="utf-8"))
            ok = False
            for n in ast.walk(tree):
                if (isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
                        and isinstance(n.value.func, ast.Attribute)
                        and n.value.func.attr == "gate_sleeve_book"):
                    first = n.value.args[0] if n.value.args else None
                    tgt = n.targets[0]
                    names = [e.id for e in getattr(tgt, "elts", []) if isinstance(e, ast.Name)]
                    if (isinstance(first, ast.Constant) and first.value == bid
                            and names[:1] == ["book"]):
                        ok = True
            self.assertTrue(ok, f"{fn}: предложение rebalance_book не проходит гейт CIO ({bid})")


if __name__ == "__main__":
    unittest.main()
