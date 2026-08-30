"""Размещение простаивающего кэша — не перекладка (решение владельца 30.08).

Анти-черн ADR-168 вводился против ПЕРЕТАСОВКИ: 22 перекладки за неделю, оборот 5.3 капитала.
29–30.08 он задержал ход, который ничего не продавал, а только ставил в работу простаивающие
деньги: треть капитала стояла трое суток, доходность дня 4.21 % → 2.86 %, перераздача выросла
до $46.6 тыс. и ждала. Правило наказывало ровно за то, ради чего вводилось.

Замер, который решил вопрос: недельный оборот на 30.08 = **$530 526** при бюджете $25 000 —
превышен в 21 раз, и превышен ПРОШЛЫМ черном. То есть старая перетасовка блокировала лечение
простоя, вызванного ею же.

Почему размещение можно освободить от ОБОИХ пределов, а перетасовку нельзя: размещение
ограничено самим кэшем. Свободно ровно `капитал − книга − обязательный буфер`, больше добавить
нечего, и новый кэш появится только после ПРОДАЖИ — а продажа попадает в журнал и считается
оборотом на общих основаниях. Здесь это ограничение ПРОВЕРЯЕТСЯ, а не утверждается.
"""
from __future__ import annotations

import datetime as dt
import unittest

from spa_core.governance.churn_damper import (
    ALLOW, BLOCK, REASON_MIN_HOLD, REASON_PLACE_IDLE, decide, is_pure_addition)

# Книга и цель ровно как в проде 30.08 (из записи ADR-072 и current_positions).
BOOK = {"maple": 18947.37, "compound_v3": 37894.74, "fluid_usdc": 9473.68}
PLACEMENT = dict(BOOK, aave_v3=22105.26, morpho_blue_base=6578.95)
CAPITAL = 100_000.0


def _trades(hours_ago: float, turnover: float) -> list:
    """Ключ `delta_abs` — тот, что читает `_recent`, и это НЕ мелочь.

    Первая редакция писала `turnover_usd`, разбор его не видел, и оборот выходил нулевым:
    тест «оба предела нарушены» на самом деле проверял ход при пустом окне. Проверка,
    измеряющая не то, что заявляет, хуже отсутствующей — она даёт ложную уверенность.
    """
    ts = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours_ago)).isoformat()
    return [{"ts": ts, "delta_abs": turnover}]


class TheRealCaseOf30Aug(unittest.TestCase):
    """Положительный контроль: те же числа, что держали треть капитала трое суток."""

    def test_the_stuck_placement_is_allowed(self):
        v = decide(BOOK, PLACEMENT, _trades(22.8, 530_526.0), CAPITAL)
        self.assertEqual(v.decision, ALLOW)
        self.assertEqual(v.reason, REASON_PLACE_IDLE)

    def test_it_is_allowed_even_though_both_limits_were_breached(self):
        """И выдержка (22.8 ч < 72), и бюджет ($530k > $25k) нарушены — а ход проходит."""
        v = decide(BOOK, PLACEMENT, _trades(1.0, 999_999.0), CAPITAL)
        self.assertEqual(v.decision, ALLOW)

    def test_the_same_move_was_blocked_before(self):
        """Обратный контроль: с сокращением хотя бы одной позиции ход снова держится."""
        reshuffle = dict(PLACEMENT, maple=10_000.0)
        v = decide(BOOK, reshuffle, _trades(22.8, 530_526.0), CAPITAL)
        self.assertEqual(v.decision, BLOCK)
        self.assertEqual(v.reason, REASON_MIN_HOLD)


class PlacementIsBoundedByTheCashItself(unittest.TestCase):
    """Ограничение — проверяемое свойство, а не довод в комментарии."""

    def test_a_move_larger_than_the_free_cash_is_not_a_placement(self):
        too_big = dict(BOOK, aave_v3=60_000.0)
        v = decide(BOOK, too_big, _trades(22.8, 1000.0), CAPITAL)
        self.assertEqual(v.decision, BLOCK)
        self.assertNotEqual(v.reason, REASON_PLACE_IDLE)

    def test_the_mandatory_buffer_is_not_deployable(self):
        """Буфер 5 % трогать нельзя: свободно только то, что выше него."""
        book = {"a": 94_000.0}                       # свободно 100k − 94k − 5k = 1k
        v = decide(book, dict(book, b=1_500.0), _trades(1.0, 0.0), CAPITAL)
        self.assertEqual(v.decision, BLOCK, "размещение залезло в обязательный буфер")

    def test_exactly_the_free_cash_is_allowed(self):
        book = {"a": 94_000.0}
        v = decide(book, dict(book, b=1_000.0), _trades(1.0, 0.0), CAPITAL)
        self.assertEqual(v.decision, ALLOW)
        self.assertEqual(v.reason, REASON_PLACE_IDLE)


class PureAdditionIsTheMirrorOfPureReduction(unittest.TestCase):
    def test_only_growth_counts_as_addition(self):
        self.assertTrue(is_pure_addition({"a": 100.0}, {"a": 150.0, "b": 30.0}))

    def test_any_shrink_disqualifies(self):
        self.assertFalse(is_pure_addition({"a": 100.0, "b": 50.0}, {"a": 150.0, "b": 40.0}))

    def test_dropping_a_position_disqualifies(self):
        self.assertFalse(is_pure_addition({"a": 100.0, "b": 50.0}, {"a": 150.0}))


class TheOldGuardsStillWork(unittest.TestCase):
    """Сужение не должно обессмыслить демпфер: перетасовку он держит как держал."""

    def test_reshuffle_within_min_hold_is_blocked(self):
        cur = {"a": 50_000.0, "b": 40_000.0}
        v = decide(cur, {"a": 40_000.0, "b": 50_000.0}, _trades(2.0, 0.0), CAPITAL)
        self.assertEqual(v.decision, BLOCK)
        self.assertEqual(v.reason, REASON_MIN_HOLD)

    def test_pure_reduction_is_still_never_damped(self):
        cur = {"a": 50_000.0, "b": 40_000.0}
        v = decide(cur, {"a": 30_000.0, "b": 40_000.0}, _trades(1.0, 999_999.0), CAPITAL)
        self.assertEqual(v.decision, ALLOW)


if __name__ == "__main__":
    unittest.main()


class AFullExitIsNotAPlacement(unittest.TestCase):
    """Условие «книга не пуста» подсказал ЧУЖОЙ тест, покрасневший на первой редакции.

    `test_the_exemption_does_not_reopen_the_flip_flop` сторожит маятник: продал вчера —
    откупаю сегодня. Первая редакция этой правки его открыла, потому что пустая книга
    тоже «только добавляет». Тест не тронут — сужено правило.

    Разница по существу: пустая книга — ПОЛНЫЙ ВЫХОД, и возврат в риск это новое решение.
    Наш случай другой: книга непуста, сокращения уже исполнены, покупки отклонил гейт —
    ход недоделан наполовину, и его доведение нового оборота не создаёт.
    """

    def test_re_entry_after_a_full_exit_is_still_blocked(self):
        v = decide({}, {"aave_v3": 40_000.0}, _trades(24.0, 40_000.0), CAPITAL)
        self.assertNotEqual(v.reason, REASON_PLACE_IDLE)
        self.assertEqual(v.decision, BLOCK)

    def test_a_half_executed_move_is_completed(self):
        """Обратная сторона: книга непуста ⇒ это доведение, а не новый вход."""
        v = decide(BOOK, PLACEMENT, _trades(24.0, 530_526.0), CAPITAL)
        self.assertEqual(v.decision, ALLOW)
        self.assertEqual(v.reason, REASON_PLACE_IDLE)
