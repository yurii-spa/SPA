"""Разметка кураторов как ДАННЫЕ — решение владельца 2026-08-25 (вариант Б).

Карточка «Потолок концентрации не видит общего куратора — половина книги может
лечь под одну команду», ADR-135.

Владелец выбрал НЕ вводить потолок поверх пустой разметки: «вводить потолок, где
известны 2 протокола из 36, — значит получить зелёную галочку, которая ничего не
гарантирует». Поэтому предмет этого файла — не потолок, а **честность разметки**:

* у каждого протокола реестра есть строка (неизвестный — тоже строка);
* у известного есть источник, у проверенного — дата;
* «выведено из поведения адаптера» отличимо от «проверено» (инв. #17);
* размер незнания едет числом рядом с числом концентрации;
* метрика попала в отчёт и НИЧЕГО не гейтит.
"""
from __future__ import annotations

import unittest

from spa_core.paper_trading import curator_registry as cr
from spa_core.paper_trading.concentration_analytics import (
    _CURATOR_OF,
    _curator_block,
    curator_concentration,
)


class MarkupIsData(unittest.TestCase):
    """Строка есть у каждого протокола, и её поля не выдуманы."""

    def test_every_registry_protocol_has_a_row(self):
        from spa_core.adapters import ADAPTER_REGISTRY
        names = {str(r[0]) for r in ADAPTER_REGISTRY}
        reg = cr.registry()
        missing = sorted(names - set(reg))
        self.assertEqual(missing, [], f"протоколы без строки разметки: {missing}")

    def test_unknown_is_a_row_not_a_hole(self):
        """«Не знаем» — заполненная строка с причиной, а не отсутствие записи."""
        e = cr.entry_for("no_such_protocol_at_all")
        self.assertEqual(e.confidence, cr.UNKNOWN)
        self.assertIsNone(e.curator)
        self.assertTrue(e.note, "у незнания обязана быть названа причина")

    def test_known_rows_carry_a_source(self):
        for name, e in cr.registry().items():
            if e.curator:
                with self.subTest(protocol=name):
                    self.assertTrue(e.source, f"{name}: имя есть, источника нет")

    def test_pinned_carries_a_verification_date_and_derived_does_not_claim_one(self):
        """Дата проверки — только у проверенного. Выведенное её не изображает."""
        for name, e in cr.registry().items():
            with self.subTest(protocol=name):
                if e.confidence == cr.PINNED:
                    self.assertTrue(e.verified_at, f"{name}: pinned без даты проверки")
                elif e.confidence == cr.DERIVED:
                    self.assertIsNone(
                        e.verified_at,
                        f"{name}: выведенная метка не смеет предъявлять дату проверки")

    def test_morpho_blue_base_is_derived_not_pinned(self):
        """Ключевая честность карточки.

        Адаптер берёт USDC-хранилище Morpho на Base с МАКСИМАЛЬНЫМ TVL, а не
        закреплённое. Замер 2026-08-18: крупнейшее — Steakhouse ($587 млн),
        следом Gauntlet ($428 млн), другая команда. Пометить это «проверено»
        значило бы соврать: метка сменится молча.
        """
        e = cr.entry_for("morpho_blue_base")
        self.assertEqual(e.confidence, cr.DERIVED)
        self.assertIn("максимальным TVL".lower(), (e.source or "").lower())

    def test_confidence_vocabulary_is_closed(self):
        allowed = {cr.PINNED, cr.DERIVED, cr.UNKNOWN}
        for name, e in cr.registry().items():
            with self.subTest(protocol=name):
                self.assertIn(e.confidence, allowed)

    def test_registry_survives_an_unreadable_adapter_registry(self):
        """Разметка не обязана падать вместе с реестром — известное сохраняется."""
        import spa_core.paper_trading.curator_registry as mod
        saved = mod._adapter_protocols
        try:
            mod._adapter_protocols = lambda: []
            reg = mod.registry()
            self.assertIn("morpho_steakhouse", reg)
        finally:
            mod._adapter_protocols = saved


class CoverageNamesTheSizeOfIgnorance(unittest.TestCase):
    """Число концентрации без размера незнания — это гарантия, которой нет."""

    def test_coverage_counts_all_three_outcomes(self):
        cov = cr.coverage()
        self.assertEqual(
            cov["total"],
            len(cov["pinned"]) + len(cov["derived"]) + cov["unknown_count"],
            cov,
        )
        self.assertGreater(cov["total"], 0)

    def test_gate_is_explicitly_not_ready_and_says_why(self):
        """Вариант Б дословно: сначала данные, потом гейт."""
        cov = cr.coverage()
        self.assertFalse(cov["gate_ready"])
        self.assertIn("сначала данные", cov["gate_ready_reason"])

    def test_unknown_is_the_majority_and_that_is_reported_not_hidden(self):
        cov = cr.coverage()
        self.assertGreater(cov["unknown_count"], len(cov["pinned"]) + len(cov["derived"]),
                           "если разметка выросла — обнови ADR-135 и вернись к потолку")
        self.assertLess(cov["known_pct"], 100.0)


class MetricIsWiredIntoTheReport(unittest.TestCase):
    """Метрика была написана и не вызывалась ниоткуда, кроме своего теста."""

    def test_report_block_carries_both_the_number_and_the_ignorance(self):
        blk = _curator_block({"morpho_steakhouse": 40_000.0, "pendle": 20_000.0},
                             100_000.0)
        self.assertTrue(blk["available"])
        self.assertEqual(blk["max_curator"], "steakhouse")
        self.assertAlmostEqual(blk["max_pct"], 40.0)
        self.assertIn("pendle", blk["unmapped"])
        self.assertIn("coverage", blk, "число поехало без размера незнания")

    def test_report_block_gates_nothing(self):
        blk = _curator_block({"morpho_steakhouse": 90_000.0}, 100_000.0)
        self.assertTrue(blk["advisory_only"])
        self.assertTrue(blk["gates_nothing"])
        self.assertNotIn("approved", blk)
        self.assertNotIn("violations", blk)

    def test_unreadable_markup_is_named_not_zeroed(self):
        """Инв. #17: сломанная разметка ≠ «концентрации нет»."""
        import spa_core.paper_trading.concentration_analytics as ca
        saved = ca.curator_concentration
        try:
            def _boom(*a, **k):
                raise RuntimeError("разметка недоступна")
            ca.curator_concentration = _boom
            blk = ca._curator_block({"morpho_steakhouse": 40_000.0}, 100_000.0)
        finally:
            ca.curator_concentration = saved
        self.assertFalse(blk["available"])
        self.assertIn("reason", blk)
        self.assertNotIn("max_pct", blk, "недоступность подана нулём")

    def test_build_concentration_carries_the_block(self):
        from spa_core.paper_trading.concentration_analytics import build_concentration
        doc = build_concentration()
        self.assertIn("curator", doc)
        self.assertIn("coverage", doc["curator"])

    def test_curator_metric_is_reachable_when_module_runs_as_main(self):
        """Причина, по которой метрика «не вызывалась ниоткуда».

        ``curator_concentration`` и ``_CURATOR_OF`` были объявлены НИЖЕ
        ``if __name__ == "__main__": sys.exit(main())`` — при запуске модуля
        отчёт строился до того, как эти имена вообще появлялись. Тест держит
        порядок объявлений: определения обязаны стоять ВЫШЕ точки входа.
        """
        import inspect
        import spa_core.paper_trading.concentration_analytics as ca
        src = inspect.getsource(ca)
        self.assertLess(src.index("def curator_concentration("),
                        src.index('if __name__ == "__main__"'),
                        "метрика снова объявлена ниже точки входа — она снова мертва")


class DerivedViewStaysCompatible(unittest.TestCase):
    """``_CURATOR_OF`` остаётся под тем же именем, но истина — в разметке."""

    def test_legacy_name_matches_the_registry(self):
        self.assertEqual(_CURATOR_OF, cr.curator_of())

    def test_derived_labels_are_counted_not_dropped(self):
        """Выбросить выведенную метку значило бы ЗАНИЗИТЬ концентрацию."""
        self.assertIn("morpho_blue_base", cr.curator_of())
        self.assertNotIn("morpho_blue_base", cr.curator_of(confidences=(cr.PINNED,)))

    def test_metric_still_answers_the_original_measurement(self):
        """Замер карточки: три имени под одной командой = 50 % книги."""
        res = curator_concentration(
            {"morpho_steakhouse": 20_000.0, "morpho_blue_base": 10_000.0,
             "morpho_blue": 20_000.0},
            100_000.0,
        )
        self.assertEqual(res["max_curator"], "steakhouse")
        self.assertAlmostEqual(res["max_pct"], 30.0)
        self.assertIn("morpho_blue", res["unmapped"],
                      "куратор morpho_blue не проверен — он обязан быть в unmapped")


if __name__ == "__main__":
    unittest.main()
