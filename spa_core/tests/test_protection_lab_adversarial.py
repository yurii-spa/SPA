# FROZEN-DATE-OK: historical-incident — единственная дата здесь — вымышленный
# якорь синтетики 2030-01-01 (наследуется из synthetic.py); окон свежести нет.
"""Protection Lab фаза 7 v2: adversarial-сетка + кластеризация семейств отказов.

Ключевые свойства: детерминизм (одна сетка — один результат), полнота учёта
(каждая комбинация ровно в одной семье), и ГЛАВНОЕ — перебор обязан
ПЕРЕОТКРЫВАТЬ известные дыры защиты (кредит без сигнала, неисполнимый выход,
депег-ловушку). Если «улучшение» сетки перестанет их находить — она перестала
быть adversarial и тест закраснеет.
"""
from __future__ import annotations

import unittest

from spa_core.stress.protection_lab.adversarial import (
    families_to_dict,
    format_sweep_report,
    generate_grid,
    run_sweep,
    signature,
)

_GRID = generate_grid()
_FAMILIES = run_sweep(grid=_GRID)


class GridProperties(unittest.TestCase):
    def test_grid_is_large_and_deterministic(self):
        self.assertGreaterEqual(len(_GRID), 1000)
        again = generate_grid()
        self.assertEqual([g[0] for g in _GRID], [g[0] for g in again])

    def test_ids_unique(self):
        ids = [g[0] for g in _GRID]
        self.assertEqual(len(ids), len(set(ids)))

    def test_pairs_only_across_families(self):
        for sid, fams, _spec in _GRID:
            self.assertEqual(len(fams), len(set(fams)), sid)
            self.assertLessEqual(len(fams), 2, sid)


class SweepAccounting(unittest.TestCase):
    def test_every_combo_in_exactly_one_family(self):
        total = sum(len(f.members) for f in _FAMILIES.values())
        self.assertEqual(total, len(_GRID))

    def test_families_far_fewer_than_combos(self):
        # смысл кластеризации: семейств на порядок меньше, чем комбинаций
        self.assertLess(len(_FAMILIES) * 10, len(_GRID))

    def test_exemplar_is_worst_in_family(self):
        for fam in _FAMILIES.values():
            worst = max(m.report.protected.max_drawdown_pct for m in fam.members)
            self.assertEqual(fam.exemplar.report.protected.max_drawdown_pct, worst)

    def test_signature_matches_membership(self):
        for sig, fam in _FAMILIES.items():
            for m in fam.members:
                self.assertEqual(signature(m), sig)

    def test_sweep_deterministic(self):
        again = run_sweep(grid=_GRID)
        self.assertEqual(set(again.keys()), set(_FAMILIES.keys()))
        for sig in _FAMILIES:
            self.assertEqual(len(again[sig].members), len(_FAMILIES[sig].members), sig)


class RediscoversKnownHoles(unittest.TestCase):
    """Перебор обязан находить дыры, которые уже доказаны исторической библиотекой."""

    def _verdicts(self):
        return {sig[0] for sig in _FAMILIES}

    def test_finds_uncovered_credit_channel(self):
        # кредитная потеря без ценового сигнала (класс Orthogonal)
        self.assertIn("uncovered", self._verdicts())

    def test_finds_unexecutable_exits(self):
        # решение о выходе есть, вывод заморожен (класс Maple-локапов/Euler)
        self.assertIn("unexecutable", self._verdicts())

    def test_finds_costly_protection(self):
        # депег-ловушка: выход на дне хуже пассива (класс USDC/SVB)
        self.assertIn("costly", self._verdicts())

    def test_worst_family_is_severe(self):
        worst = max(f.worst_dd for f in _FAMILIES.values())
        self.assertGreater(worst, 20.0,
                           "adversarial-сетка перестала находить тяжёлые комбинации")


class Reporting(unittest.TestCase):
    def test_text_report_renders(self):
        text = format_sweep_report(_FAMILIES)
        self.assertIn("семейств отказов", text)
        self.assertIn("Худшая слабость", text)

    def test_json_dict_shape(self):
        d = families_to_dict(_FAMILIES)
        self.assertEqual(d["total_combos"], len(_GRID))
        self.assertTrue(all("exemplar" in f and "signature" in f
                            for f in d["families"]))
        dds = [f["worst_dd_pct"] for f in d["families"]]
        self.assertEqual(dds, sorted(dds, reverse=True))


if __name__ == "__main__":
    unittest.main()
