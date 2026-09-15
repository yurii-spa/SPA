"""Проба приёмки «бесплатный ход» — контроль в ОБЕ стороны (ADR-393, цикл #611).

Правило `.claude/rules/acceptance.md`, п. 3: новая проба регистрируется в
``card_acceptance.PROBES`` только вместе с тестом, где она ЗЕЛЕНА на целом контуре
и КРАСНА на каждом порванном звене — с названным звеном; и где она не проходит
подстрокой.

Звеньев у этой пробы два, и они смотрят в разные стороны:

1. **ноль — цена** (ветка ``cost_rec is not None``). Рвётся возвратом старой ветки
   ``cost_rec is not None and cost_rec > 0.0`` — ровно тот тест, который заказал
   владелец в карточке;
2. **отсутствие — не ноль** (допущение ``ASSUMED_COST_BPS_OF_TURNOVER``). Рвётся
   «починкой», которая читает отсутствующую цену как ноль.

Второе звено существует потому, что без него правка выглядела бы выполненной и
одновременно разрешала бы бесплатные ходы там, где цену просто не записали, — то
есть инвариант #17 наизнанку. Проба, у которой порвать можно только одно звено,
про второе молчит по построению.

Живой ``data/`` не открывается ни на чтение, ни на запись: контур синтетический,
а даты в нём строятся от эпохи и являются ключами ПОРЯДКА — судья
(``evaluate_window``) детерминирован по файлам и часов не читает вовсе.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import unittest

from spa_core.monitoring import card_acceptance as ca
from spa_core.paper_trading import shadow_trigger_eval as ste

PROBE = "free_move_priced_as_free"


class ProbeIsRegistered(unittest.TestCase):

    def test_probe_name_is_in_the_registry_and_accepted_by_the_writer(self):
        """Имя объявляемо: иначе карточка получила бы `unmeasured` навсегда."""
        self.assertIn(PROBE, ca.PROBES)
        self.assertIsNone(ca.validate_spec(PROBE))


class WholeContourIsGreen(unittest.TestCase):

    def test_probe_is_satisfied_on_the_intact_judge(self):
        verdict, detail = ca.run_probe(PROBE)
        self.assertEqual(verdict, ca.SATISFIED, detail)
        # Вердикт обязан нести ЧИСЛА, а не слово: отчёт без них нечем перемерить.
        self.assertIn("$", detail)

    def test_the_two_scores_differ_by_the_price_of_a_cent_not_by_luck(self):
        """Внутренняя сверка: ноль дороже цента ровно на стоимость центов.

        Если бы проба зеленела по какой-то посторонней причине, это равенство не
        держалось бы. Оно и есть довод, что зелёный получен той самой ветвью.
        """
        import tempfile
        import shutil
        from pathlib import Path

        from spa_core.monitoring import criterion_sign_price as csp
        from spa_core.monitoring import swap_existence_price as sep

        root = tempfile.mkdtemp(prefix="spa_free_move_test_")
        try:
            ca._free_move_journal(root, cost_usd=100.0)
            got = sep.zero_is_absent(Path(root), horizon_days=ste.DEFAULT_HORIZON_DAYS,
                                     gates=csp._gate_names())
            self.assertFalse(got["collides"])
            gap = got["best_net_usd_zero"] - got["best_net_usd_one_cent"]
            days = got["rows"][2].get("scorable_days")
            self.assertIsNotNone(days)
            self.assertAlmostEqual(gap, 0.01 * days, places=2)
        finally:
            shutil.rmtree(root, ignore_errors=True)


class EachBrokenLinkIsRed(unittest.TestCase):
    """Каждое звено рвётся ОТДЕЛЬНО, и проба обязана назвать именно его."""

    def _run_with_judge_patched(self, fn):
        original = ste._evaluate_verdict
        ste._evaluate_verdict = fn(original)
        try:
            return ca.run_probe(PROBE)
        finally:
            ste._evaluate_verdict = original

    def test_returning_the_old_branch_makes_the_probe_red(self):
        """ЗВЕНО 1 — ровно тот возврат, против которого владелец заказал тест.

        Ветка воспроизводится не переписыванием исходника, а подменой цены на входе
        судьи: записанный ноль подаётся так, как его читала СТАРАЯ ветка — то есть
        как отсутствие записи. Исход обязан совпасть с историческим.
        """
        def old_branch(original):
            def patched(rec, forward, horizon_days, *a, **kw):
                if rec.get("cost_usd") == 0.0:
                    rec = {k: v for k, v in rec.items() if k != "cost_usd"}
                return original(rec, forward, horizon_days, *a, **kw)
            return patched

        verdict, detail = self._run_with_judge_patched(old_branch)
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("СЛИТЫ", detail)

    def test_reading_an_absent_price_as_zero_makes_the_probe_red(self):
        """ЗВЕНО 2 — «починка» наизнанку: отсутствие цены прочитано как ноль."""
        def absent_as_zero(original):
            def patched(rec, forward, horizon_days, *a, **kw):
                if "cost_usd" not in rec:
                    rec = dict(rec, cost_usd=0.0)
                return original(rec, forward, horizon_days, *a, **kw)
            return patched

        verdict, detail = self._run_with_judge_patched(absent_as_zero)
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("БЕЗ записанной цены", detail)

    def test_an_instrument_that_refuses_gives_unmeasured_never_satisfied(self):
        """Третий исход назван: нечем мерить ≠ критерий не выполнен и ≠ выполнен."""
        from spa_core.monitoring import swap_existence_price as sep
        original = sep.zero_is_absent

        def boom(*a, **kw):
            raise OSError("проба: прибор недоступен")

        sep.zero_is_absent = boom
        try:
            verdict, detail = ca.run_probe(PROBE)
        finally:
            sep.zero_is_absent = original
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("OSError", detail)


class TheProbeDoesNotPassBySubstring(unittest.TestCase):
    """ADR-333: вердикт берётся у ИСХОДА, а не у текста, найденного в отчёте."""

    def test_verdict_does_not_depend_on_any_text_in_the_journal(self):
        import tempfile
        import shutil
        from pathlib import Path

        from spa_core.monitoring import criterion_sign_price as csp
        from spa_core.monitoring import swap_existence_price as sep

        root = tempfile.mkdtemp(prefix="spa_free_move_text_")
        try:
            ca._free_move_journal(root, cost_usd=100.0)
            path = Path(root) / "allocation_rationale_history.jsonl"
            poisoned = path.read_text(encoding="utf-8").replace(
                '"decision_id": "free-move-probe-0"',
                '"decision_id": "zero_price_is_read_as_absent_price СЛИТЫ"')
            path.write_text(poisoned, encoding="utf-8")
            got = sep.zero_is_absent(Path(root), horizon_days=ste.DEFAULT_HORIZON_DAYS,
                                     gates=csp._gate_names())
            self.assertFalse(got["collides"])
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
