"""Симметрия двух гейтов риск-политики — решение владельца 2026-08-25 (вариант А).

Карточка «Проверка книги слабее проверки перед сделкой — 60 % в рисковом уровне
проходит как здоровый портфель», ADR-134.

Замер, ради которого всё затевалось (книга $100k: T1 35 % + три T2 по 20 %):

    БЫЛО:  перед сделкой -> approved=False (Total T2 allocation 60.0% > 50.0%)
           на книге      -> approved=True, violations=[], warnings=[]
    СТАЛО: оба гейта     -> approved=False, тот же порог, то же число

**Пороги не меняются ни на цифру** — оба гейта читают их из одного
``RiskConfig``. Меняется ТОЛЬКО охват. Проверка «а не подкрутили ли заодно
числа» — в ``ThresholdsUnchanged`` ниже.

**Ответ на нарушение — не распродажа.** Второе, что закрывает этот файл:
``approved`` («книга в пределах политики?») и ``required_response`` («что с этим
делать?») стали разными вопросами. До ADR-134 вопрос был один, и
``engine.rebalance`` закрывал ВСЁ по любому ``approved=False`` — включая
SOFT-тир просадки, в тексте нарушения которого дословно написано «NOT
all-cash». Расширение охвата без этой правки превратило бы просевший APY
удерживаемой позиции в принудительный выход в кэш.

**Условие владельца:** «выход из позиций не блокируется никогда» — ``ExitNever
Blocked`` ниже.
"""
from __future__ import annotations

import inspect
import math
import unittest

from spa_core.governance.kill_switch import TIER_HARD_KILL, TIER_SOFT_DERISK
from spa_core.risk.policy import (
    RESPONSE_ALL_CASH,
    RESPONSE_HALT_NEW,
    RESPONSE_NONE,
    PortfolioState,
    Position,
    RiskPolicy,
)

CAPITAL = 100_000.0


def pos(key, tier, usd, apy=8.0, chain="ethereum", pnl=0.0):
    return Position(protocol_key=key, tier=tier, asset="USDC", amount_usd=usd,
                    apy_at_open=apy, current_apy=apy, chain=chain,
                    unrealized_pnl_usd=pnl)


def book(*positions):
    return PortfolioState(total_capital_usd=CAPITAL, positions=list(positions))


def tvl_all(positions, usd=500_000_000.0):
    """Живой TVL для каждой позиции — чтобы пол TVL был ИЗМЕРЕН, а не пропущен."""
    return {p.protocol_key: usd for p in positions}


class GateSymmetry(unittest.TestCase):
    """Порог, который отказывает ПЕРЕД СДЕЛКОЙ, обязан отказывать И НА КНИГЕ.

    Каждый тест прогоняет ОБА гейта на одних и тех же числах: сначала предельную
    сделку через ``check_new_position``, затем получившуюся книгу через
    ``check_portfolio_health``. Утверждение — что вердикты совпали. Так тест
    нельзя удовлетворить, подкрутив один гейт: он сверяет их друг с другом, а не
    с записанной в него константой.
    """

    def setUp(self):
        self.p = RiskPolicy()

    def _both_reject(self, pre_state, trade, full_book, tvl_map=None, needle=""):
        entry = self.p.check_new_position(pre_state, **trade)
        health = self.p.check_portfolio_health(full_book, tvl_map=tvl_map)
        self.assertFalse(entry.approved, f"вход должен отказывать: {entry.violations}")
        self.assertFalse(health.approved,
                         f"книга должна отказывать тоже: warnings={health.warnings}")
        if needle:
            self.assertTrue(any(needle in v for v in health.violations),
                            f"на книге нет нарушения про {needle!r}: {health.violations}")
        return entry, health

    def test_t2_total_cap(self):
        """Тот самый случай из карточки: 60 % в рисковом уровне.

        Единственный порог, который книга способна нарушить БЕЗ ЕДИНОЙ СДЕЛКИ:
        тир динамический (ADR-055), куратор двигает протокол T1→T2 и доля
        рисковых растёт сама. Входной гейт такую книгу не увидит никогда — он
        смотрит только на прибавку.
        """
        pre = book(pos("aave_v3", "T1", 35_000), pos("pendle", "T2", 20_000),
                   pos("euler", "T2", 20_000))
        full = book(pos("aave_v3", "T1", 35_000), pos("pendle", "T2", 20_000),
                    pos("euler", "T2", 20_000), pos("morpho", "T2", 20_000))
        _, health = self._both_reject(
            pre,
            dict(protocol_key="morpho", tier="T2", amount_usd=20_000,
                 current_apy=8.0, tvl_usd=500_000_000),
            full, tvl_map=tvl_all(full.positions), needle="Total T2 allocation 60.0%",
        )
        self.assertEqual(health.required_response, RESPONSE_HALT_NEW)

    def test_l2_total_cap(self):
        pre = book(pos("aave_v3", "T1", 30_000), pos("aero", "T2", 20_000, chain="base"),
                   pos("gmx", "T2", 20_000, chain="arbitrum"))
        full = book(pos("aave_v3", "T1", 30_000), pos("aero", "T2", 20_000, chain="base"),
                    pos("gmx", "T2", 20_000, chain="arbitrum"),
                    pos("extra", "T2", 20_000, chain="base"))
        self._both_reject(
            pre,
            dict(protocol_key="extra", tier="T2", amount_usd=20_000,
                 current_apy=8.0, tvl_usd=500_000_000, chain="base"),
            full, tvl_map=tvl_all(full.positions), needle="Total L2 allocation 60.0%",
        )

    def test_single_chain_cap(self):
        pre = book(pos("aave_v3", "T1", 40_000), pos("compound", "T1", 35_000))
        full = book(pos("aave_v3", "T1", 40_000), pos("compound", "T1", 35_000),
                    pos("pendle", "T2", 20_000))
        self._both_reject(
            pre,
            dict(protocol_key="pendle", tier="T2", amount_usd=20_000,
                 current_apy=8.0, tvl_usd=500_000_000),
            full, tvl_map=tvl_all(full.positions),
            needle="Chain concentration on ethereum 95.0%",
        )

    def test_cash_buffer(self):
        """Раньше на книге это было ПРЕДУПРЕЖДЕНИЕ — отчёт говорил «здоров»."""
        pre = book(pos("aave_v3", "T1", 39_000), pos("compound", "T1", 40_000))
        full = book(pos("aave_v3", "T1", 39_000), pos("compound", "T1", 40_000),
                    pos("pendle", "T2", 20_000))
        _, health = self._both_reject(
            pre,
            dict(protocol_key="pendle", tier="T2", amount_usd=20_000,
                 current_apy=8.0, tvl_usd=500_000_000),
            full, tvl_map=tvl_all(full.positions),
            needle="Cash buffer 1.0% below minimum 5.0%",
        )
        self.assertFalse(any("Cash buffer" in w for w in health.warnings),
                         "кэш-буфер обязан быть нарушением, а не предупреждением")

    def test_apy_corridor_high(self):
        pre = book(pos("aave_v3", "T1", 30_000))
        full = book(pos("aave_v3", "T1", 30_000), pos("pendle", "T2", 20_000, apy=55.0))
        self._both_reject(
            pre,
            dict(protocol_key="pendle", tier="T2", amount_usd=20_000,
                 current_apy=55.0, tvl_usd=500_000_000),
            full, tvl_map=tvl_all(full.positions), needle="Held APY pendle 55.0%",
        )

    def test_apy_corridor_low(self):
        pre = book(pos("aave_v3", "T1", 30_000))
        full = book(pos("aave_v3", "T1", 30_000), pos("pendle", "T2", 20_000, apy=0.4))
        self._both_reject(
            pre,
            dict(protocol_key="pendle", tier="T2", amount_usd=20_000,
                 current_apy=0.4, tvl_usd=500_000_000),
            full, tvl_map=tvl_all(full.positions), needle="Held APY pendle 0.4%",
        )

    def test_tvl_floor(self):
        pre = book(pos("aave_v3", "T1", 30_000))
        full = book(pos("aave_v3", "T1", 30_000), pos("tiny", "T2", 20_000))
        tvl = {"aave_v3": 500_000_000.0, "tiny": 1_000_000.0}
        self._both_reject(
            pre,
            dict(protocol_key="tiny", tier="T2", amount_usd=20_000,
                 current_apy=8.0, tvl_usd=1_000_000),
            full, tvl_map=tvl, needle="Held TVL tiny $1,000,000",
        )


class NoFalsePositives(unittest.TestCase):
    """Обратный контроль. Без него файл нельзя отличить от «книга всегда красная»."""

    def setUp(self):
        self.p = RiskPolicy()

    def test_healthy_book_stays_approved(self):
        bk = book(pos("aave_v3", "T1", 35_000), pos("compound", "T1", 25_000),
                  pos("pendle", "T2", 20_000), pos("euler", "T2", 10_000))
        r = self.p.check_portfolio_health(bk, tvl_map=tvl_all(bk.positions))
        self.assertTrue(r.approved, r.violations)
        self.assertEqual(r.violations, [])
        self.assertEqual(r.required_response, RESPONSE_NONE)

    def test_empty_book_is_not_a_violation(self):
        """Пустая книга — не нарушение политики (кэш 100 % ≥ буфера).

        Пустоту ловит отдельный чек go-live, а не этот гейт: иначе рано или
        поздно кто-нибудь «починит» её принудительной покупкой.
        """
        r = self.p.check_portfolio_health(book())
        self.assertTrue(r.approved, r.violations)

    def test_exactly_at_the_cap_is_green(self):
        """Порог — включительно снизу: ровно 50 % T2 проходит, 50.1 % нет.

        Часть книги на Base намеренно: иначе 90 % на одной сети срабатывает
        раньше и тест мерил бы не тот порог.
        """
        at = book(pos("aave_v3", "T1", 40_000), pos("pendle", "T2", 20_000),
                  pos("euler", "T2", 20_000), pos("aero", "T2", 10_000, chain="base"))
        over = book(pos("aave_v3", "T1", 40_000), pos("pendle", "T2", 20_000),
                    pos("euler", "T2", 20_000), pos("aero", "T2", 10_100, chain="base"))
        self.assertTrue(self.p.check_portfolio_health(
            at, tvl_map=tvl_all(at.positions)).approved)
        r_over = self.p.check_portfolio_health(over, tvl_map=tvl_all(over.positions))
        self.assertFalse(r_over.approved)
        self.assertTrue(any("Total T2 allocation" in v for v in r_over.violations),
                        r_over.violations)


class ThresholdsUnchanged(unittest.TestCase):
    """Вариант А обещал «пороги не меняются ни на цифру». Здесь это утверждение.

    Числа сверяются с ``RiskConfig`` — то есть с тем же источником, из которого
    их берёт входной гейт. Тест краснеет и если кто-то поменяет конфиг мимо ADR,
    и если книга начнёт судить по собственной константе.
    """

    def test_book_reads_the_same_config_object(self):
        cfg = RiskPolicy().config
        self.assertEqual(cfg.max_total_t2_allocation, 0.50)
        self.assertEqual(cfg.max_l2_total_allocation, 0.50)
        self.assertEqual(cfg.max_single_chain_allocation, 0.90)
        self.assertEqual(cfg.min_cash_pct, 0.05)
        self.assertEqual(cfg.min_apy_for_new_position, 1.0)
        self.assertEqual(cfg.max_apy_for_new_position, 30.0)
        self.assertEqual(cfg.min_tvl_usd, 5_000_000)
        self.assertEqual(cfg.version, "v1.0")

    def test_custom_config_moves_both_gates_together(self):
        """Порог живёт в одном месте: сдвинули конфиг — сдвинулись ОБА гейта."""
        from spa_core.risk.policy import RiskConfig
        loose = RiskPolicy(RiskConfig(max_total_t2_allocation=0.70))
        # Часть на Base — чтобы мерился именно потолок T2, а не 90 % на сети.
        bk = book(pos("aave_v3", "T1", 35_000), pos("pendle", "T2", 20_000),
                  pos("euler", "T2", 20_000), pos("aero", "T2", 20_000, chain="base"))
        self.assertTrue(loose.check_portfolio_health(
            bk, tvl_map=tvl_all(bk.positions)).approved)
        strict = RiskPolicy(RiskConfig(max_total_t2_allocation=0.50))
        self.assertFalse(strict.check_portfolio_health(
            bk, tvl_map=tvl_all(bk.positions)).approved)


class AbsentObservationIsNotAPass(unittest.TestCase):
    """Инвариант #17: «не измерено» обязано отличаться от «пройдено».

    Производитель числа здесь этим и грешит: ``engine._load_portfolio_state``
    пишет ``current_apy = snap["apy_total"] if snap else (net_apy_annualized or
    0.0)`` — молчание фида приходит сюда НУЛ�ём. Судить по такому нулю «APY ниже
    1 % ⇒ нарушение» значило бы объявить нарушением молчание фида.
    """

    def setUp(self):
        self.p = RiskPolicy()

    def test_unmeasured_apy_is_a_warning_not_a_violation(self):
        bk = book(pos("aave_v3", "T1", 30_000, apy=0.0))
        r = self.p.check_portfolio_health(bk, tvl_map=tvl_all(bk.positions))
        self.assertTrue(r.approved, r.violations)
        self.assertTrue(any("APY_UNCHECKED" in w for w in r.warnings), r.warnings)
        self.assertFalse(any("Held APY" in v for v in r.violations), r.violations)

    def test_non_finite_apy_is_also_unchecked_not_a_violation(self):
        bk = book(pos("aave_v3", "T1", 30_000, apy=float("nan")))
        r = self.p.check_portfolio_health(bk, tvl_map=tvl_all(bk.positions))
        self.assertTrue(any("APY_UNCHECKED" in w for w in r.warnings), r.warnings)

    def test_measured_apy_out_of_corridor_IS_a_violation(self):
        """Положительный контроль к двум предыдущим: измеренное — судим."""
        bk = book(pos("aave_v3", "T1", 30_000, apy=0.4))
        r = self.p.check_portfolio_health(bk, tvl_map=tvl_all(bk.positions))
        self.assertFalse(r.approved)
        self.assertTrue(any("Held APY" in v for v in r.violations), r.violations)

    def test_missing_tvl_map_is_named_not_silently_passed(self):
        bk = book(pos("aave_v3", "T1", 30_000))
        r = self.p.check_portfolio_health(bk)  # tvl_map не передан вовсе
        self.assertTrue(any("TVL_FLOOR_UNCHECKED" in w for w in r.warnings), r.warnings)
        self.assertFalse(any("Held TVL" in v for v in r.violations), r.violations)

    def test_partial_tvl_map_names_only_the_unmeasured(self):
        bk = book(pos("aave_v3", "T1", 30_000), pos("pendle", "T2", 20_000))
        r = self.p.check_portfolio_health(bk, tvl_map={"aave_v3": 500_000_000.0})
        unchecked = [w for w in r.warnings if "TVL_FLOOR_UNCHECKED" in w]
        self.assertEqual(len(unchecked), 1, r.warnings)
        self.assertIn("pendle", unchecked[0])
        self.assertNotIn("aave_v3", unchecked[0])


class ResponseIsNotTheSameQuestionAsApproval(unittest.TestCase):
    """``approved`` — «в пределах политики?». ``required_response`` — «что делать?».

    До ADR-134 это был один вопрос, и ответ на него был один: закрыть всё.
    """

    def setUp(self):
        self.p = RiskPolicy()

    def test_hard_kill_still_demands_all_cash(self):
        """Положительный контроль: настоящий кил не ослаблен."""
        bk = book(pos("aave_v3", "T1", 90_000, pnl=-12_000))
        r = self.p.check_portfolio_health(bk, tvl_map=tvl_all(bk.positions))
        self.assertEqual(r.drawdown_tier, TIER_HARD_KILL)
        self.assertEqual(r.required_response, RESPONSE_ALL_CASH)
        self.assertTrue(r.all_cash_reasons)

    def test_soft_derisk_is_halt_new_not_all_cash(self):
        """Текст нарушения дословно говорит «NOT all-cash» — теперь и ответ тоже.

        Это ADR-050, который до сих пор исполнялся только на словах: вердикт
        сообщал SOFT, а потребитель закрывал книгу целиком.
        """
        bk = book(pos("aave_v3", "T1", 30_000, pnl=-6_000))
        r = self.p.check_portfolio_health(bk, tvl_map=tvl_all(bk.positions))
        self.assertEqual(r.drawdown_tier, TIER_SOFT_DERISK)
        self.assertFalse(r.approved)
        self.assertEqual(r.required_response, RESPONSE_HALT_NEW)
        self.assertEqual(r.all_cash_reasons, [])

    def test_coverage_violation_never_demands_all_cash(self):
        """Ради чего вся развязка: новый охват не умеет вызывать распродажу."""
        books = [
            book(pos("aave_v3", "T1", 35_000), pos("pendle", "T2", 20_000),
                 pos("euler", "T2", 20_000), pos("morpho", "T2", 20_000)),   # T2 60 %
            book(pos("aave_v3", "T1", 30_000), pos("pendle", "T2", 20_000, apy=0.4)),
            book(pos("aave_v3", "T1", 39_000), pos("compound", "T1", 40_000),
                 pos("pendle", "T2", 20_000)),                               # кэш 1 %
        ]
        for bk in books:
            with self.subTest(book=[p.protocol_key for p in bk.positions]):
                r = self.p.check_portfolio_health(bk, tvl_map=tvl_all(bk.positions))
                self.assertFalse(r.approved)
                self.assertEqual(r.required_response, RESPONSE_HALT_NEW)
                self.assertEqual(r.all_cash_reasons, [])

    def test_non_finite_drawdown_still_fails_closed_to_all_cash(self):
        bk = book(pos("aave_v3", "T1", 30_000, pnl=float("-inf")))
        self.assertFalse(math.isfinite(bk.total_drawdown_pct))
        r = self.p.check_portfolio_health(bk)
        self.assertEqual(r.required_response, RESPONSE_ALL_CASH)

    def test_nan_pnl_no_longer_reads_as_zero_drawdown(self):
        """Дыра, найденная замером при написании этого файла — теперь закрыта.

        ``total_drawdown_pct`` = ``max(0.0, -pnl/capital)``, а ``max(0.0, nan)``
        в Python равен **0.0**: испорченный pnl доходил до гейта как «просадки
        нет», и fail-closed guard, обещавший в своём же комментарии поймать
        «pnl corrupted to NaN», не срабатывал НИКОГДА. Инвариант #17 наизнанку.
        """
        bk = book(pos("aave_v3", "T1", 30_000, pnl=float("nan")))
        self.assertEqual(bk.total_drawdown_pct, 0.0,
                         "свойство перестало сглаживать NaN — тест ниже надо пересмотреть")
        r = self.p.check_portfolio_health(bk)
        self.assertFalse(r.approved)
        self.assertEqual(r.required_response, RESPONSE_ALL_CASH)
        self.assertTrue(any("non-finite pnl/capital" in v for v in r.violations),
                        r.violations)


class ExitNeverBlocked(unittest.TestCase):
    """Условие владельца к варианту А: «выход из позиций не блокируется никогда».

    Сегодня выход структурно нигде не гейтится — ``close_position`` риск-политику
    не спрашивает. Тесты ниже существуют, чтобы это перестало быть устной
    договорённостью: они покраснеют в тот день, когда кто-нибудь загейтит.
    """

    def test_no_verdict_blocks_exit(self):
        p = RiskPolicy()
        for bk in (
            book(pos("aave_v3", "T1", 90_000, pnl=-12_000)),                 # HARD
            book(pos("aave_v3", "T1", 30_000, pnl=-6_000)),                  # SOFT
            book(pos("aave_v3", "T1", 35_000), pos("pendle", "T2", 20_000),
                 pos("euler", "T2", 20_000), pos("morpho", "T2", 20_000)),   # охват
        ):
            r = p.check_portfolio_health(bk, tvl_map=tvl_all(bk.positions))
            self.assertFalse(r.approved)
            self.assertFalse(r.blocks_exit)

    def test_close_position_does_not_consult_the_risk_gates(self):
        """Структурное утверждение: выход не спрашивает разрешения у политики."""
        from spa_core.paper_trading.engine import PaperTrader
        src = inspect.getsource(PaperTrader.close_position)
        for gate in ("check_new_position", "check_portfolio_health"):
            self.assertNotIn(gate, src,
                             f"close_position стал спрашивать {gate} — выход загейчен")


class EngineRespondsToTheResponseNotTheVerdict(unittest.TestCase):
    """``engine.rebalance`` закрывает книгу только по требованию ALL_CASH."""

    def _trader(self):
        import tempfile
        from pathlib import Path
        from spa_core.database.init_db import init_database
        from spa_core.paper_trading.engine import PaperTrader
        db = Path(tempfile.mktemp(suffix=".db"))
        init_database(db_path=db)
        return PaperTrader(db_path=db)

    class _Verdict:
        def __init__(self, response, approved, reasons=()):
            from spa_core.risk.policy import RiskCheckResult
            self.r = RiskCheckResult(
                approved=approved, violations=[] if approved else ["stub violation"],
                warnings=[], check_name="portfolio_health",
                required_response=response, all_cash_reasons=list(reasons),
            )

    def _run_with(self, response, approved, reasons=()):
        trader = self._trader()
        trader.open_position("aave-v3-usdc-ethereum", 20_000.0, 5.0, 500_000_000.0)
        verdict = self._Verdict(response, approved, reasons).r
        trader.policy.check_portfolio_health = lambda *a, **k: verdict
        return trader.rebalance()

    def test_all_cash_closes_the_book(self):
        actions = self._run_with(RESPONSE_ALL_CASH, False, ["HARD kill: stub"])
        self.assertTrue(any(a.get("reason") == "kill_switch" for a in actions), actions)

    def test_halt_new_closes_nothing_and_says_so(self):
        actions = self._run_with(RESPONSE_HALT_NEW, False)
        self.assertFalse(any(a.get("reason") == "kill_switch" for a in actions), actions)
        halt = [a for a in actions if a.get("action") == "HALT_NEW"]
        self.assertEqual(len(halt), 1, actions)
        self.assertTrue(halt[0]["exit_allowed"])
        self.assertFalse(any(a.get("action") == "NO_OP" for a in actions),
                         "нарушение не смеет отчитаться «portfolio_healthy»")

    def test_healthy_book_is_still_a_noop(self):
        actions = self._run_with(RESPONSE_NONE, True)
        self.assertTrue(any(a.get("action") == "NO_OP" for a in actions), actions)


if __name__ == "__main__":
    unittest.main()
