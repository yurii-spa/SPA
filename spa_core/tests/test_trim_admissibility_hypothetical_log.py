"""Гипотетическая книга перебора урезания не пишет строку журнала на каждую пробу.

Авария 29–30.10.2026: ``com.spa.decision_loop`` (мост находок) за ночь набрал
>100 ГБ в /tmp/spa_decision_loop.log, ~7 МБ/с. Источник — ``book_verdict``:
переписи урезания зовут ``RiskPolicy.check_portfolio_health`` 60 947 раз на один
``shadow_trigger_eval.evaluate_window``, и каждая пробная книга печатала
WARNING/ERROR (TVL_FLOOR_UNCHECKED, «Held APY … below minimum»).

Контроль в обе стороны:
* пробная книга — вердикт и нарушения ТЕ ЖЕ, строк журнала политики нет;
* живая книга той же формы через ``RiskPolicy()`` — строки журнала ЕСТЬ
  (правка не глушит предупреждения риск-политики вообще).
"""
from __future__ import annotations

import logging
import unittest

from spa_core.paper_trading import trim_admissibility as ta
from spa_core.risk.policy import PortfolioState, Position, RiskPolicy

_POLICY_LOGGER = "spa_core.risk.policy"

# Книга с удерживаемой ставкой ниже коридора 1 % ⇒ отказ с названным нарушением.
_BOOK = {"aave_v3": 40_000.0, "euler_v2": 40_000.0}
_APY = {"aave_v3": 4.0, "euler_v2": 0.7}
_TIERS = {"aave_v3": "T1", "euler_v2": "T1"}
_CHAINS = {"aave_v3": "ethereum", "euler_v2": "ethereum"}


def _live_state() -> PortfolioState:
    return PortfolioState(total_capital_usd=100_000.0, positions=[
        Position(protocol_key=k, tier=_TIERS[k], asset="USDC", amount_usd=v,
                 apy_at_open=_APY[k], current_apy=_APY[k], unrealized_pnl_usd=0.0,
                 days_held=0.0, chain=_CHAINS[k])
        for k, v in sorted(_BOOK.items())])


class HypotheticalBookLog(unittest.TestCase):
    def _policy_records(self, fn):
        logger = logging.getLogger(_POLICY_LOGGER)
        records = []

        class _H(logging.Handler):
            def emit(self, record):
                records.append(record)

        h = _H(level=logging.DEBUG)
        old_level = logger.level
        logger.addHandler(h)
        logger.setLevel(logging.DEBUG)
        try:
            out = fn()
        finally:
            logger.removeHandler(h)
            logger.setLevel(old_level)
        return out, [r for r in records if r.levelno >= logging.WARNING]

    def test_hypothetical_book_keeps_verdict_and_writes_no_policy_line(self):
        before = dict(ta.HYPOTHETICAL_CHECKS)
        (verdict, unknown), lines = self._policy_records(lambda: ta.book_verdict(
            _BOOK, _APY, 100_000.0, tiers=_TIERS, chains=_CHAINS))
        self.assertEqual(unknown, [])
        live = RiskPolicy().check_portfolio_health(_live_state())
        # вердикт и нарушения — те же, что у живой двери на той же книге
        self.assertEqual(verdict["approved"], bool(live.approved))
        self.assertEqual(verdict["violations"], [str(v) for v in live.violations])
        self.assertFalse(verdict["approved"])
        self.assertTrue(any("euler_v2" in v for v in verdict["violations"]))
        self.assertEqual(lines, [], "пробная книга не пишет WARNING/ERROR политики")
        self.assertEqual(ta.HYPOTHETICAL_CHECKS["checked"], before["checked"] + 1)
        self.assertEqual(ta.HYPOTHETICAL_CHECKS["rejected"], before["rejected"] + 1)

    def test_live_policy_call_still_logs(self):
        """Положительный контроль: правка не глушит журнал политики целиком."""
        _res, lines = self._policy_records(
            lambda: RiskPolicy().check_portfolio_health(_live_state()))
        self.assertTrue(lines, "живая проверка обязана печатать отказ")
        self.assertTrue(any("euler_v2" in r.getMessage() for r in lines))

    def test_hypothetical_sink_does_not_leak_to_later_live_instances(self):
        ta.book_verdict(_BOOK, _APY, 100_000.0, tiers=_TIERS, chains=_CHAINS)
        self.assertNotIn("_log_result", vars(RiskPolicy()))


if __name__ == "__main__":
    unittest.main()
