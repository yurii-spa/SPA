"""
test_tier_a_protocol_context.py — гард-тесты Tier-A protocol-context wiring
(audit 2026-08-02: все 12 BLOCKING модулей были глухи к ctx["protocol"]).

Проверяем через ТОТ ЖЕ _ModuleAdapter, что и прод/аудит:
  * каждый из 12 модулей реестра даёт ok + score 0-100 для протоколов базы;
  * скоры протокол-специфичны (различаются между протоколами) — регрессия
    к no-arg/demo-константам ловится;
  * детерминизм: повторный прогон даёт тот же score;
  * неизвестный протокол → dormant (сигнал НЕ измерен, а не "OK");
  * калибровка: структурные факты не дают BLOCK (>70) ни одному
    аллоцируемому протоколу (исключение — advisory BTC-адаптеры,
    IS_ADVISORY=True, никогда не аллоцируются);
  * _protocol_facts покрывает DEFAULT_PROTOCOLS и имена живой книги.

Тесты НЕ пишут в data/: контекст-пути модулей не ведут ring-buffer логов,
адаптер вызывается напрямую (без run_tier_a → без записи signals-файлов).
"""
import unittest

from spa_core.analytics import _protocol_facts as pf
from spa_core.analytics._module_registry import TIER_A_MODULES
from spa_core.analytics.signal_aggregator import _ModuleAdapter

# Протоколы с заведомо разными структурными профилями — на них скоры
# обязаны различаться у протокол-чувствительных модулей.
DIVERSE_PROTOCOLS = [
    "aave_v3", "maple", "pendle", "ethena_susde",
    "extra_finance_base", "aave_arbitrum", "cbbtc_lending",
]

# Advisory-адаптеры (IS_ADVISORY=True, никогда не в target_usd) — им
# разрешён структурный BLOCK (честный custodial/централизационный риск).
ADVISORY_ONLY = {"cbbtc_lending", "tbtc_lending"}

BLOCK_THRESHOLD = 70.0


class TestTierAProtocolContext(unittest.TestCase):
    def _run(self, module_info, protocol):
        return _ModuleAdapter(module_info).run(protocol, {"source": "test"})

    def test_all_modules_ok_for_known_protocols(self):
        """Каждый Tier-A модуль даёт ok+score для каждого протокола базы."""
        for m in TIER_A_MODULES:
            for proto in DIVERSE_PROTOCOLS:
                score, status, detail = self._run(m, proto)
                self.assertEqual(
                    status, "ok",
                    f"{m['module']}({proto}) → {status}: {detail}")
                self.assertIsNotNone(score)
                self.assertTrue(0.0 <= score <= 100.0,
                                f"{m['module']}({proto}) score={score}")

    def test_scores_are_protocol_specific(self):
        """Регрессия к протокол-слепым константам: у каждого модуля скоры
        различаются хотя бы между какими-то протоколами разнородного набора."""
        for m in TIER_A_MODULES:
            scores = set()
            for proto in DIVERSE_PROTOCOLS:
                score, status, _ = self._run(m, proto)
                if status == "ok":
                    scores.add(round(score, 4))
            self.assertGreater(
                len(scores), 1,
                f"{m['module']}: константный score {scores} для "
                f"всех протоколов {DIVERSE_PROTOCOLS} — protocol-blind")

    def test_deterministic_repeat(self):
        """Повторный прогон → байт-в-байт тот же score (нет недетерминизма)."""
        for m in TIER_A_MODULES:
            s1, st1, _ = self._run(m, "aave_v3")
            s2, st2, _ = self._run(m, "aave_v3")
            self.assertEqual(st1, st2, m["module"])
            self.assertEqual(s1, s2, m["module"])

    def test_unknown_protocol_is_dormant_not_ok(self):
        """Неизвестный протокол → dormant (не измерен), НЕ фабрикация score."""
        for m in TIER_A_MODULES:
            score, status, _ = self._run(
                m, "__nonexistent_control_protocol__")
            self.assertIsNone(score, m["module"])
            self.assertEqual(status, "dormant", m["module"])

    def test_structural_facts_never_block_allocatable_protocols(self):
        """Калибровочный инвариант: постоянное структурное свойство протокола,
        разрешённого RiskPolicy, не должно вечно зануливать его аллокацию —
        BLOCK (>70) зарезервирован за живыми событийными сигналами."""
        for proto in pf.known_protocols():
            if proto in ADVISORY_ONLY:
                continue
            for m in TIER_A_MODULES:
                score, status, _ = self._run(m, proto)
                if status == "ok":
                    self.assertLessEqual(
                        score, BLOCK_THRESHOLD,
                        f"{m['module']}({proto})={score} > {BLOCK_THRESHOLD}: "
                        "структурный факт блокировал бы whitelisted-протокол")

    def test_facts_cover_default_protocols_and_live_book(self):
        """База покрывает DEFAULT_PROTOCOLS агрегатора и имена живой книги."""
        from spa_core.analytics.signal_aggregator import DEFAULT_PROTOCOLS
        live_book_names = ["morpho_steakhouse", "spark_susds", "susde",
                           "pendle", "extra_finance_base"]
        for name in list(DEFAULT_PROTOCOLS) + live_book_names:
            self.assertIsNotNone(
                pf.facts_for(name),
                f"нет структурных фактов для '{name}' — Tier-A слеп к нему")

    def test_facts_unknown_returns_none(self):
        self.assertIsNone(pf.facts_for("__nope__"))
        self.assertIsNone(pf.facts_for(""))
        self.assertIsNone(pf.facts_for(None))

    def test_is_protocol_context(self):
        self.assertTrue(pf.is_protocol_context({"protocol": "aave_v3"}))
        self.assertFalse(pf.is_protocol_context({"protocol": 5}))
        self.assertFalse(pf.is_protocol_context([{"protocol": "aave_v3"}]))
        self.assertFalse(pf.is_protocol_context("aave_v3"))


class TestTierBMassWiring(unittest.TestCase):
    """Гарды массовой Tier-B проводки (generic_profile_for + extract)."""

    def test_generic_profile_deterministic_and_protocol_specific(self):
        p1 = pf.generic_profile_for("aave_v3")
        p2 = pf.generic_profile_for("aave_v3")
        self.assertEqual(p1, p2)
        pm = pf.generic_profile_for("maple")
        self.assertNotEqual(p1["apy_pct"], pm["apy_pct"])
        self.assertIsNone(pf.generic_profile_for("__nope__"))

    def test_extract_protocol_score_nested_and_no_bare_numeric(self):
        prof = pf.generic_profile_for("aave_v3")
        # score во вложенном контейнере находится
        res = pf.extract_protocol_score(
            {"aggregates": {"risk_score": 42.0}}, prof)
        self.assertEqual(res["risk_score"], 42.0)
        # голое число произвольного ключа score'ом НЕ является
        # (класс ложной коэрции, убранный audit 2026-08-02)
        self.assertIsNone(pf.extract_protocol_score(
            {"aggregates": {"tvl_usd": 25e9, "timestamp": 1.7e9}}, prof))
        self.assertIsNone(pf.extract_protocol_score(None, prof))

    def test_mass_wired_modules_still_legacy_callable(self):
        """Рекурсивная контекст-ветка не ломает легаси-форму вызова."""
        from spa_core.analytics.defi_lending_market_utilization_analyzer \
            import DeFiLendingMarketUtilizationAnalyzer
        r = DeFiLendingMarketUtilizationAnalyzer().analyze(
            [pf.generic_profile_for("aave_v3")])
        self.assertIsInstance(r, dict)


if __name__ == "__main__":
    unittest.main()
