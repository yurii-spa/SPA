"""ADR-160: срезанное АЛЛОКАТОРОМ перераздаётся, но не обратно в срезанные пулы.

Решение владельца 28.08, вариант 3 — СТРОЖЕ рекомендации автора карточки (вариант 2
возвращал капитал в те же maple/morpho, чей потолок его и срезал). Основание — ADR-055:
концентрация следует за доходностью и риском, а не за инерцией.

Что было сломано (замер 08.08): предохранитель ADR-072 считал `freed` разницей сумм ГЕЙТА,
а основные урезания происходят РАНЬШЕ гейта, внутри аллокатора (потолки протокола,
суммарные T2/T3, потолки сети). Гейт получал уже урезанную книгу, и предохранитель честно
получал НОЛЬ: 25 % капитала в кэше при обязательном буфере 5 %, и ни одна строка не
объясняла почему.

Каждый тест ниже — проверка ЭФФЕКТА, а не наличия кода.
"""
from __future__ import annotations

import unittest

from spa_core.paper_trading.risk_gate import redistribute_freed_budget
# Форма адаптера берётся у КАНОНИЧЕСКОГО помощника существующих тестов, а не пишется
# заново: своя копия фикстуры — это второй дом для одного факта. Первая редакция этих
# тестов завела свою и указала `apy` вместо `apy_pct`, отчего кандидат молча
# отбраковывался, и тест краснел не на своём предмете.
from spa_core.tests.test_redistribute_freed_budget import adapter


def _adapters():
    return [adapter("aave_v3", "T1", 4.0), adapter("compound_v3", "T1", 3.3)]


class TestAllocatorTrimsAreNowVisible(unittest.TestCase):
    """Ядро починки: раньше эти деньги были НЕВИДИМЫ для перезаполнителя."""

    def test_allocator_trim_alone_produces_freed_budget(self):
        """Гейт не срезал НИЧЕГО (asked == deployed), но аллокатор срезал 20 %.
        До ADR-160 freed был бы 0 — деньги молча оставались кэшем."""
        gate = {"aave_v3": 30000.0}
        r = redistribute_freed_budget(
            gate, dict(gate), 100000.0, _adapters(), {"tvl_unverified": []},
            allocator_trims_by_protocol={"maple": 0.20})
        self.assertGreater(r["freed_usd"], 0, "срезанное аллокатором обязано стать freed")
        self.assertAlmostEqual(r["freed_from_allocator_usd"], 20000.0, places=2)

    def test_without_the_new_argument_behaviour_is_unchanged(self):
        """Обратный контроль: без тримов аллокатора — прежний ответ, ноль."""
        gate = {"aave_v3": 30000.0}
        r = redistribute_freed_budget(
            gate, dict(gate), 100000.0, _adapters(), {"tvl_unverified": []})
        self.assertEqual(r["freed_usd"], 0.0)
        self.assertEqual(r["added"], {})


class TestTrimmedPoolsGetNothingBack(unittest.TestCase):
    """Вариант 3 владельца: вернуть деньги туда, откуда их срезал потолок, — инерция."""

    def test_the_trimmed_protocol_is_not_refilled(self):
        gate = {"aave_v3": 10000.0}
        r = redistribute_freed_budget(
            gate, dict(gate), 100000.0,
            _adapters() + [adapter("maple", "T2", 9.9)],
            {"tvl_unverified": []},
            allocator_trims_by_protocol={"maple": 0.20})
        self.assertNotIn("maple", r["added"],
                         "самый доходный кандидат, но его потолок только что срезал вес")
        self.assertIn("maple", r["blocked_by_allocator"])

    def test_an_untrimmed_candidate_still_receives(self):
        """Обратный контроль: блокировка адресная, а не «никому ничего»."""
        gate = {"aave_v3": 10000.0}
        r = redistribute_freed_budget(
            gate, dict(gate), 100000.0, _adapters(), {"tvl_unverified": []},
            allocator_trims_by_protocol={"maple": 0.20})
        self.assertTrue(r["added"], "нетронутые кандидаты обязаны получить капитал")
        self.assertNotIn("maple", r["added"])


class TestGateRemainsTheLastWord(unittest.TestCase):
    """Инвариант #1: перераздача НЕ смеет отменять слово гейта."""

    def test_pool_the_gate_just_cut_is_still_blocked(self):
        r = redistribute_freed_budget(
            {"aave_v3": 10000.0}, {"aave_v3": 30000.0}, 100000.0, _adapters(),
            {"tvl_unverified": []}, allocator_trims_by_protocol={"maple": 0.05})
        self.assertNotIn("aave_v3", r["added"], "гейт только что срезал aave_v3")

    def test_cash_buffer_is_never_touched(self):
        r = redistribute_freed_budget(
            {"aave_v3": 10000.0}, {"aave_v3": 10000.0}, 100000.0, _adapters(),
            {"tvl_unverified": []}, allocator_trims_by_protocol={"maple": 0.90})
        placed = sum(r["target_usd"].values())
        self.assertLessEqual(placed, 95000.0 + 1e-6,
                             "буфер 5 % неприкосновенен даже при огромном срезе")


class TestIdleCashIsNamed(unittest.TestCase):
    """ADR-055: молчаливый простой запрещён.

    Замер 29.08 на живых данных: дельта перераздачи НОЛЬ, книга 90 % при кэше 10 %,
    и держит её потолок цепочки (все живые кандидаты на Ethereum, ADR-076), а не
    защитные тримы. Значит цикл ОБЯЗАН называть причину, иначе простой снова молчит.
    """

    def test_nothing_to_place_still_reports_the_freed_amount_and_who_is_blocked(self):
        r = redistribute_freed_budget(
            {"maple": 10000.0}, {"maple": 10000.0}, 100000.0,
            [adapter("maple", "T2", 9.9)],
            {"tvl_unverified": []}, allocator_trims_by_protocol={"maple": 0.20})
        self.assertEqual(r["added"], {}, "единственный кандидат — сам срезанный")
        self.assertGreater(r["freed_usd"], 0, "сумма обязана быть НАЗВАНА, а не потеряна")
        self.assertEqual(r["blocked_by_allocator"], ["maple"])


if __name__ == "__main__":
    unittest.main()
