"""Списание девяти константных модулей Tier-C — решение владельца 2026-08-25 (1А).

Карточка «Списать 180 фоновых модулей Tier-C или честно записать, что мы про них
не знаем», ADR-133. Замер, ради которого всё затевалось (воспроизводится
``scripts/audit_protocol_blindness.py --tier C``):

    БЫЛО:  avg_score = 20.56 для aave_v3 И 20.56 для maple, modules_ok = 9
    СТАЛО: avg_score = None,               modules_ok = 0, written_off = 9

Одинаковое число для РАЗНЫХ протоколов — и есть доказательство: девять модулей не
читают, о каком протоколе их спросили, а публикуемое ``avg_score`` складывалось
целиком из них. «Константа, притворяющаяся замером, хуже пустоты».

Второй вопрос той же карточки (2А) — 162 модуля записаны как «не знаем» и
заморожены. Это НЕ списание: списание было бы утверждением о бесполезности,
которого у нас нет. Тест ниже держит эту границу.

Tier-C — советующий слой: капитал не двигает, RiskPolicy и стоп-кран не касается.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from spa_core.analytics import _module_registry as registry
from spa_core.analytics._tier_c_writeoff import (
    UNKNOWN_FROZEN,
    WRITTEN_OFF,
)
import spa_core.analytics.signal_aggregator as sa


class TierCWriteOffRegistry(unittest.TestCase):
    """Реестр обязан описывать РЕАЛЬНЫЕ модули, а не имена из головы."""

    def test_nine_written_off(self):
        self.assertEqual(len(WRITTEN_OFF), 9)

    def test_every_written_off_name_exists_in_the_tier_c_registry(self):
        """Фантомное имя в реестре списания = списали то, чего нет."""
        known = {m["module"] for m in registry.get_tier_modules("C")}
        missing = sorted(set(WRITTEN_OFF) - known)
        self.assertEqual(missing, [], f"списаны несуществующие модули: {missing}")

    def test_every_written_off_carries_a_measured_reason(self):
        for name, reason in WRITTEN_OFF.items():
            self.assertTrue(reason and "константа" in reason,
                            f"{name}: причина не названа замером — {reason!r}")

    def test_frozen_is_not_written_off(self):
        """2А ≠ 1А: «не знаем» и «списано» — разные множества, не пересекаются."""
        overlap = sorted(set(UNKNOWN_FROZEN) & set(WRITTEN_OFF))
        self.assertEqual(overlap, [], f"заморожённые попали в списанные: {overlap}")
        self.assertEqual(len(UNKNOWN_FROZEN), 162)


class TierCWriteOffBehaviour(unittest.TestCase):
    """Поведение фильтра: списанные не доходят до исполнителя, но ВИДНЫ.

    Настоящие Tier-C модули здесь НЕ запускаются намеренно: они пишут свои
    журналы в живой ``data/`` (о чём предупреждает и докстринг аудита), а
    прогон, переписывающий git-tracked состояние прода, подсовывает свежесть,
    которой в системе нет. Поэтому реестр модулей и исполнитель подменены, и
    тест проверяет РОВНО свой предмет — фильтр списания.

    Замер на настоящих 180 модулях (avg_score 20.56 → None) снят отдельно и
    воспроизводится командой из докстринга ADR-133, а не этим набором.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._saved_writeoff = sa.TIER_C_WRITTEN_OFF
        self._saved_get = sa.registry.get_tier_modules
        self.asked: list = []

    def tearDown(self):
        sa.TIER_C_WRITTEN_OFF = self._saved_writeoff
        sa.registry.get_tier_modules = self._saved_get

    def _fake_registry(self, names):
        def _get(tier):
            return [{"module": n, "class": None, "tier": "C",
                     "category": "background", "weight": 0.0} for n in names]
        sa.registry.get_tier_modules = _get

    def _agg(self):
        agg = sa.SignalAggregator(data_dir=self.tmp)

        def _runner(module_info, protocol, context):
            self.asked.append(module_info["module"])
            agg._record(module_info["module"], "ok", "stub")
            return 42.0, True

        agg._run_module = _runner
        agg._run_module_silent = lambda m, p, c: (42.0, True)
        return agg

    def test_written_off_never_reach_the_runner(self):
        self._fake_registry(["kept_one", "dropped_one"])
        sa.TIER_C_WRITTEN_OFF = {"dropped_one": "константа 0.0 на всех протоколах аудита"}

        res = self._agg().run_tier_c(["aave_v3"], {})

        self.assertIn("kept_one", self.asked)
        self.assertNotIn("dropped_one", self.asked,
                         "списанный модуль всё-таки исполнился")
        self.assertEqual(res["protocols"]["aave_v3"]["modules_ok"], 1)

    def test_written_off_stay_visible_in_status(self):
        """Инв. #17: «не исполняем» обязано отличаться от «модуля нет»."""
        self._fake_registry(["kept_one", "dropped_one"])
        sa.TIER_C_WRITTEN_OFF = {"dropped_one": "константа 0.0 на всех протоколах аудита"}

        res = self._agg().run_tier_c(["aave_v3"], {})

        counts = res["_meta"]["module_status"]["counts"]
        self.assertEqual(counts.get("written_off"), 1, counts)
        not_ok = res["_meta"]["module_status"]["not_ok"]
        self.assertIn("dropped_one", not_ok.get("written_off", []))

    def test_all_written_off_means_empty_score_not_a_made_up_number(self):
        """Ради чего всё: остались одни списанные ⇒ публикуется ПУСТО."""
        self._fake_registry(["dropped_one", "dropped_two"])
        sa.TIER_C_WRITTEN_OFF = {
            "dropped_one": "константа 0.0 на всех протоколах аудита",
            "dropped_two": "константа 45.0 на всех протоколах аудита",
        }

        res = self._agg().run_tier_c(["aave_v3"], {})

        self.assertIsNone(res["protocols"]["aave_v3"]["avg_score"])
        self.assertEqual(res["protocols"]["aave_v3"]["modules_ok"], 0)
        self.assertEqual(self.asked, [], "исполнился хоть один списанный")

    def test_empty_writeoff_keeps_previous_behaviour(self):
        """Обратный контроль: пустой реестр ⇒ поведение ровно прежнее."""
        self._fake_registry(["kept_one", "dropped_one"])
        sa.TIER_C_WRITTEN_OFF = {}

        res = self._agg().run_tier_c(["aave_v3"], {})

        self.assertEqual(res["protocols"]["aave_v3"]["modules_ok"], 2)
        self.assertIsNotNone(res["protocols"]["aave_v3"]["avg_score"])


if __name__ == "__main__":
    unittest.main()
