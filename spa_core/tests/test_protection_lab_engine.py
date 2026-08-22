# FROZEN-DATE-OK: historical-incident — даты здесь либо исторические кризисы
# (предмет теста), либо заведомо вымышленный якорь синтетики 2030-01-01;
# окон свежести от wall clock в Protection Lab нет по построению.
"""Protection Lab: движок replay — лестница, депег-гейт, no-look-ahead, отказы исполнения.

Ключевое свойство, которое закрепляется: у Protection Lab НЕТ СВОИХ порогов —
уровни защиты приходят из spa_core.governance.kill_switch (ADR-034/048), депег —
из того же detect_depeg, что использует RiskPolicy. Дрейф порогов (ошибка
stress_engine v1 с _KILL_SWITCH_DD=0.05) здесь невозможен по построению,
и тесты проверяют это ПОВЕДЕНИЕМ, а не констанстой в исходнике.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from spa_core.governance.kill_switch import (
    TIER_HARD_KILL,
    TIER_NONE,
    TIER_SOFT_DERISK,
)
from spa_core.stress.protection_lab import (
    BookPosition,
    build_synthetic_scenario,
    run_replay,
)
from spa_core.stress.protection_lab.synthetic import (
    ADVERSARIAL_SPECS,
    DepegSpec,
    SyntheticSpec,
)

_BOOK = [
    BookPosition("aave_v3", 0.40, tier="T1", exposure_symbol="USDC"),
    BookPosition("pendle", 0.20, tier="T2", exposure_symbol="PT_USDC"),
    BookPosition("maple", 0.15, tier="T2", exposure_symbol="USDC"),
    BookPosition("morpho_steakhouse", 0.15, tier="T2", exposure_symbol="USDC"),
]


def _loss_spec(loss_pct: float, day: int = 2, protocol: str = "aave_v3",
               duration: int = 15) -> SyntheticSpec:
    return SyntheticSpec(
        name=f"SYN_test_loss_{int(loss_pct * 100)}",
        description="тестовый шок",
        duration_days=duration,
        capital_losses=[{"protocol": protocol, "day": day, "loss_pct": loss_pct}],
    )


class LadderComesFromGovernance(unittest.TestCase):
    """Уровни SOFT/HARD берутся из настоящей лестницы, не из локальной копии."""

    def test_six_pct_drawdown_soft_derisk_not_kill(self):
        # aave 40% × 15% потери = 6% NAV — внутри [5,10): SOFT, БЕЗ ликвидации.
        rep = run_replay(build_synthetic_scenario(_loss_spec(0.15)), book=_BOOK)
        kinds = {a["kind"] for a in rep.protected.actions}
        self.assertIn("soft_derisk", kinds)
        self.assertNotIn("hard_kill", kinds)
        self.assertIn(TIER_SOFT_DERISK, rep.protected.tier_by_day)
        self.assertNotIn(TIER_HARD_KILL, rep.protected.tier_by_day)
        # SOFT не ликвидирует: позиции остаются в книге.
        self.assertIn("aave_v3", rep.protected.positions_end_usd)

    def test_twelve_pct_drawdown_hard_kill_all_cash(self):
        # aave 40% × 30% = 12% NAV — ≥10%: HARD_KILL → всё в кэш.
        rep = run_replay(build_synthetic_scenario(_loss_spec(0.30)), book=_BOOK)
        kinds = {a["kind"] for a in rep.protected.actions}
        self.assertIn("hard_kill", kinds)
        self.assertIn(TIER_HARD_KILL, rep.protected.tier_by_day)
        self.assertEqual(rep.protected.positions_end_usd, {},
                         "после HARD_KILL позиций остаться не должно")
        self.assertGreater(rep.protected.cash_end_usd, 0)

    def test_four_pct_drawdown_no_tier(self):
        # aave 40% × 10% = 4% NAV — ниже SOFT: лестница молчит.
        rep = run_replay(build_synthetic_scenario(_loss_spec(0.10)), book=_BOOK)
        self.assertEqual(set(rep.protected.tier_by_day), {TIER_NONE})

    def test_no_local_threshold_constants_in_engine(self):
        # Дрейф stress_engine v1 начался с локальной константы порога.
        # В replay.py числовых порогов лестницы быть не должно — только импорт.
        src = (Path(__file__).resolve().parent.parent
               / "stress" / "protection_lab" / "replay.py").read_text(encoding="utf-8")
        for pattern in (r"=\s*0\.05\b", r"=\s*0\.10\b", r"=\s*5\.0\b", r"=\s*10\.0\b"):
            self.assertIsNone(
                re.search(pattern, src),
                f"в replay.py похоже завёлся локальный порог ({pattern}) — "
                f"пороги живут ТОЛЬКО в governance/kill_switch.py")


class NoLookAhead(unittest.TestCase):
    """Решение дня T видит только рынок конца дня T-1."""

    def test_reaction_comes_day_after_signal_never_same_day(self):
        # Депег виден с дня 2 (trough), значит первое действие — день 3.
        spec = SyntheticSpec(
            name="SYN_test_lookahead",
            description="депег без предвестника",
            duration_days=10,
            depegs=[DepegSpec("USDC", 0.80, start_day=2, trough_day=2,
                              recovery_day=None)],
        )
        rep = run_replay(build_synthetic_scenario(spec), book=_BOOK)
        # NAV-удар такого депега ≥10%, поэтому первым может успеть HARD_KILL —
        # засчитываем любой защитный путь, важна только хронология.
        exit_actions = [a for a in rep.protected.actions
                        if a["kind"] in ("depeg_exit", "hard_kill")]
        self.assertTrue(exit_actions)
        self.assertGreaterEqual(
            min(a["day"] for a in exit_actions), 3,
            "защита отреагировала в день шока — look-ahead bias")

    def test_day_zero_never_acts(self):
        rep = run_replay(build_synthetic_scenario(_loss_spec(0.30, day=0)), book=_BOOK)
        self.assertTrue(all(a["day"] >= 1 for a in rep.protected.actions))


class DepegGateSemantics(unittest.TestCase):
    """WARN (≥2%) — наблюдение; CRITICAL (≥4%) — выход. Семантика detect_depeg."""

    def test_warn_level_depeg_does_not_exit(self):
        spec = SyntheticSpec(
            name="SYN_test_warn", description="лёгкий депег",
            duration_days=8,
            depegs=[DepegSpec("USDC", 0.97, start_day=1, trough_day=2,
                              recovery_day=5)],
        )
        rep = run_replay(build_synthetic_scenario(spec), book=_BOOK)
        self.assertFalse([a for a in rep.protected.actions
                          if a["kind"] == "depeg_exit"])

    def test_critical_depeg_exits_exposed_positions(self):
        spec = SyntheticSpec(
            name="SYN_test_critical", description="жёсткий депег PT",
            duration_days=8,
            depegs=[DepegSpec("PT_USDC", 0.85, start_day=1, trough_day=2,
                              recovery_day=None)],
        )
        rep = run_replay(build_synthetic_scenario(spec), book=_BOOK)
        exits = [a for a in rep.protected.actions if a["kind"] == "depeg_exit"]
        self.assertTrue(exits)
        self.assertIn("pendle", exits[0]["detail"])
        self.assertNotIn("pendle", rep.protected.positions_end_usd)

    def test_usdc_critical_records_unprotected_cash_channel(self):
        spec = SyntheticSpec(
            name="SYN_test_cash_channel", description="депег самого кэша",
            duration_days=8,
            depegs=[DepegSpec("USDC", 0.85, start_day=1, trough_day=2,
                              recovery_day=6)],
        )
        rep = run_replay(build_synthetic_scenario(spec), book=_BOOK)
        self.assertTrue(any("кэш системы — USDC" in f for f in rep.findings),
                        "депег USDC обязан фиксироваться как незащищённый канал")


class ExecutionAware(unittest.TestCase):
    """Верное решение ≠ исполненное решение."""

    def test_frozen_protocol_records_failure_then_executes_after_thaw(self):
        spec = SyntheticSpec(
            name="SYN_test_freeze", description="решение есть, вывода нет",
            duration_days=12,
            capital_losses=[{"protocol": "aave_v3", "day": 1, "loss_pct": 0.30}],
            freezes=[{"protocol": "aave_v3", "from_day": 0, "to_day": 6}],
        )
        rep = run_replay(build_synthetic_scenario(spec), book=_BOOK)
        fails = [f for f in rep.protected.execution_failures
                 if f["protocol"] == "aave_v3"]
        self.assertTrue(fails, "заморозка обязана дать execution failure")
        executed = [a for a in rep.protected.actions
                    if a["kind"] == "exit_executed" and "aave_v3" in a["detail"]]
        self.assertTrue(executed, "после разморозки выход обязан исполниться")
        self.assertGreaterEqual(min(a["day"] for a in executed), 7)
        self.assertTrue(any("отказ исполнения" in f for f in rep.findings))

    def test_haircut_and_gas_are_paid_on_exit(self):
        spec = SyntheticSpec(
            name="SYN_test_haircut", description="выход стоит денег",
            duration_days=10,
            capital_losses=[{"protocol": "aave_v3", "day": 1, "loss_pct": 0.30}],
            liquidity={"from_day": 0, "to_day": 9, "exit_haircut_pct": 0.02,
                       "gas_cost_usd": 100.0},
        )
        rep = run_replay(build_synthetic_scenario(spec), book=_BOOK)
        self.assertGreater(rep.protected.haircut_usd, 0)
        self.assertGreater(rep.protected.gas_usd, 0)
        self.assertEqual(rep.benchmark.haircut_usd, 0.0,
                         "пассивный держатель не выходит и haircut не платит")


class HonestAccounting(unittest.TestCase):
    """Метрики защиты не приукрашивают."""

    def test_no_signal_no_difference(self):
        # Потеря 1.8% NAV: ниже SOFT, депега нет — защита не должна выдумывать
        # действий, прогоны идентичны.
        spec = SyntheticSpec(
            name="SYN_test_quiet", description="тихий убыток",
            duration_days=10,
            capital_losses=[{"protocol": "morpho_steakhouse", "day": 2,
                             "loss_pct": 0.12}],
        )
        rep = run_replay(build_synthetic_scenario(spec), book=_BOOK)
        self.assertEqual(rep.capital_saved_usd, 0.0)
        self.assertEqual(rep.protected.final_equity, rep.benchmark.final_equity)

    def test_capital_saved_can_be_negative(self):
        # PT-дислокация: выход по дисконту фиксирует убыток, пассив дожидается
        # пара. Отрицательный capital_saved обязан быть виден, а не обрезан.
        spec = next(s for s in ADVERSARIAL_SPECS if s.name == "SYN_S05_pt_dislocation")
        rep = run_replay(build_synthetic_scenario(spec), book=_BOOK)
        self.assertLess(rep.capital_saved_usd, 0)

    def test_determinism(self):
        spec = next(s for s in ADVERSARIAL_SPECS if s.name == "SYN_S06_oct10_x2")
        r1 = run_replay(build_synthetic_scenario(spec), book=_BOOK)
        r2 = run_replay(build_synthetic_scenario(spec), book=_BOOK)
        self.assertEqual(r1.protected.bars, r2.protected.bars)
        self.assertEqual(r1.benchmark.bars, r2.benchmark.bars)
        self.assertEqual(r1.capital_saved_usd, r2.capital_saved_usd)

    def test_benchmark_never_acts(self):
        for spec in ADVERSARIAL_SPECS:
            rep = run_replay(build_synthetic_scenario(spec), book=_BOOK)
            self.assertEqual(rep.benchmark.actions, [],
                             f"{spec.name}: benchmark действовать не может")
            self.assertEqual(rep.benchmark.execution_failures, [])


if __name__ == "__main__":
    unittest.main()
