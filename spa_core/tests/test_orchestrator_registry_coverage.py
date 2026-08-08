"""Оркестратор не смеет быть уже канонического реестра там, где это стоит денег.

Инцидент 2026-08-08 (мандат владельца «кэш обязан работать»): money-path видел
ТОЛЬКО 8 адаптеров — ВСЕ на Ethereum, — хотя канонический
`spa_core.adapters.ADAPTER_REGISTRY` знал 36, и `morpho_blue_base` отдавал
live APY 4.95% при live TVL $597M. Следствие было денежным: книга упиралась в
лимит одной цепочки 90% (ADR-062), ~$20k кэша размещать было НЕКУДА.

Класс дефекта — «источник ≠ предмет наблюдения» (тот же, что у
governance_watcher: следил за чужими DAO вместо держимых).

Проверки в обе стороны:
  * каждый ключ снимка обязан существовать в каноническом реестре (иначе
    оркестратор опрашивает то, чего система не знает);
  * покрытие вне Ethereum не может вернуться к нулю (храповик: хотя бы один
    не-Ethereum адаптер обязан опрашиваться — иначе chain-лимит снова станет
    потолком размещения молча).
"""
from __future__ import annotations

import unittest

from spa_core.adapters import ADAPTER_REGISTRY as CANONICAL
from spa_core.orchestrator.adapter_orchestrator import ADAPTER_REGISTRY as ORCH
from spa_core.risk.chain_limits import get_default_chain_map


class OrchestratorCoverage(unittest.TestCase):
    def setUp(self):
        self.orch_keys = [k for k, _t, _c in ORCH]
        self.canon = {k: (t, c) for k, t, c in CANONICAL}

    def test_every_polled_adapter_is_canonical(self):
        unknown = [k for k in self.orch_keys if k not in self.canon]
        self.assertEqual(unknown, [],
                         f"оркестратор опрашивает то, чего нет в каноническом реестре: {unknown}")

    def test_no_duplicate_keys(self):
        self.assertEqual(len(self.orch_keys), len(set(self.orch_keys)))

    def test_non_ethereum_coverage_never_returns_to_zero(self):
        """Храповик chain-покрытия: money-path обязан видеть хотя бы одного
        кандидата вне Ethereum. Ноль = молчаливое возвращение инцидента 08.08."""
        chain_map = get_default_chain_map()
        non_eth = [k for k in self.orch_keys
                   if str(chain_map.get(k, "ethereum")).lower() != "ethereum"]
        self.assertGreaterEqual(
            len(non_eth), 1,
            "ни одного не-Ethereum адаптера в опросе — chain-лимит 90% снова "
            "станет потолком размещения, и кэш будет стоять молча")

    def test_classes_are_instantiable_types(self):
        for k, _tier, cls in ORCH:
            self.assertTrue(isinstance(cls, type), f"{k}: класс адаптера не тип")

    def test_tiers_match_canonical_registry(self):
        """Тир в оркестраторе — fallback; расхождение с каноном = два источника
        правды о риске одного протокола."""
        for k, tier, _cls in ORCH:
            canon_tier = self.canon.get(k, (None, None))[0]
            if canon_tier is not None:
                self.assertEqual(tier, canon_tier,
                                 f"{k}: тир {tier} против канонического {canon_tier}")


if __name__ == "__main__":
    unittest.main()
