# FROZEN-DATE-OK: historical-incident — сценарии библиотеки описывают
# исторические кризисы (Terra 2022-05, USDC/SVB 2023-03-11, 10.10.2025 и т.д.);
# даты — предмет данных, окон свежести нет.
"""Protection Lab: библиотека исторических сценариев — валидность, голдены, честность.

Голдены — это НЕ украшение: replay детерминирован, и любое изменение сценарного
файла или движка обязано осознанно перемерить эти числа (и объяснить сдвиг в
журнале), а не молча их «улучшить». Отдельно закреплены НЕ-льстивые результаты:
в депеге USDC защита обязана быть ХУЖЕ пассива (кэш — тот же USDC, выход платит
haircut), в FTX/Orthogonal — потеря обязана пройти мимо защиты (кредитный канал
без ценового сигнала). Если такой тест позеленел «в плюс» — движок начал
рисовать красивый бектест, что прямо запрещено заданием владельца (ADR-120).
"""
from __future__ import annotations

import unittest

from spa_core.stress.protection_lab import load_all_scenarios, run_replay

_SCENARIOS = load_all_scenarios()
_REPORTS = {sid: run_replay(sc) for sid, sc in _SCENARIOS.items() if sc.has_replay}


class LibraryIntegrity(unittest.TestCase):
    def test_library_size_and_validity(self):
        # load_all_scenarios fail-CLOSED: сам факт загрузки = все файлы валидны.
        # 12 канонических + 4 продвинутых аудитом полноты (H13-H16).
        self.assertGreaterEqual(len(_SCENARIOS), 16)

    def test_canonical_twelve_present(self):
        for sid in [
            "H01_mtgox_2014", "H02_2018_crypto_winter",
            "H03_covid_black_thursday_2020", "H04_may_2021_cascade",
            "H05_terra_ust_luna_2022", "H06_celsius_3ac_stETH_june_2022",
            "H07_ftx_november_2022", "H08_usdc_svb_depeg_2023",
            "H09_curve_vyper_july_2023", "H10_aug_2024_yen_carry",
            "H11_bybit_hack_feb_2025", "H12_oct_10_2025_cascade",
            # продвинутые аудитом полноты — дыры каналов ИМЕННО нашей книги:
            "H13_maple_orthogonal_dec_2022", "H14_stream_xusd_nov_2025",
            "H15_euler_mar_2023", "H16_aave_capo_mar_2026",
        ]:
            self.assertIn(sid, _SCENARIOS)

    def test_every_historical_scenario_has_provenance(self):
        for sid, sc in _SCENARIOS.items():
            if sc.synthetic:
                continue
            self.assertGreaterEqual(len(sc.sources), 3, sid)
            self.assertTrue(sc.confidence_notes, sid)
            self.assertTrue(sc.summary, sid)

    def test_replay_specs_name_their_assumptions(self):
        # Молчаливых прокси нет: каждая replay-спека несёт явные допущения маппинга.
        for sid, sc in _SCENARIOS.items():
            if sc.has_replay and not sc.synthetic:
                self.assertTrue(sc.replay.assumptions,
                                f"{sid}: replay без назв. допущений маппинга")


class GoldenNumbers(unittest.TestCase):
    """Три тяжёлых кейса владельца (Black Thursday, Terra, 10/10) + два флагмана."""

    def _golden(self, sid, bench_final, prot_final, det_day):
        r = _REPORTS[sid]
        self.assertAlmostEqual(r.benchmark.final_equity, bench_final, places=2,
                               msg=f"{sid}: benchmark сдвинулся")
        self.assertAlmostEqual(r.protected.final_equity, prot_final, places=2,
                               msg=f"{sid}: protected сдвинулся")
        self.assertEqual(r.detection_day, det_day, f"{sid}: день обнаружения")

    def test_h03_black_thursday(self):
        self._golden("H03_covid_black_thursday_2020", 100026.51, 98407.40, 10)

    def test_h05_terra(self):
        # Книга не касалась UST по вайтлисту — прямых потерь нет, защита молчит.
        self._golden("H05_terra_ust_luna_2022", 100201.58, 100201.58, None)

    def test_h07_ftx_orthogonal(self):
        self._golden("H07_ftx_november_2022", 95851.91, 95851.91, None)

    def test_h08_usdc_svb(self):
        self._golden("H08_usdc_svb_depeg_2023", 99962.34, 96615.58, 2)

    def test_h12_oct_10_2025(self):
        self._golden("H12_oct_10_2025_cascade", 99996.44, 99337.28, 2)

    def test_h13_maple_orthogonal(self):
        # Флагман кредитного канала: −80% пула M11 одним блоком, выход заперт локапами.
        self._golden("H13_maple_orthogonal_dec_2022", 88390.03, 87706.22, 28)


class HonestOutcomes(unittest.TestCase):
    """Нельстивые результаты закреплены НАПРАВЛЕНИЕМ, не только числом."""

    def test_usdc_depeg_protection_is_worse_than_passive(self):
        r = _REPORTS["H08_usdc_svb_depeg_2023"]
        self.assertLess(
            r.protected.final_equity, r.benchmark.final_equity,
            "H08: защита стала «лучше» пассива в депеге USDC — движок начал "
            "рисовать красивый бектест (кэш — тот же USDC, выход платит haircut; "
            "менять этот вердикт можно только осознанно, с записью в журнал)")
        self.assertTrue(any("кэш системы — USDC" in f for f in r.findings))

    def test_ftx_credit_loss_passes_the_defence_silently(self):
        r = _REPORTS["H07_ftx_november_2022"]
        self.assertIsNone(r.detection_day,
                          "H07: у кредитного дефолта Orthogonal не было ценового "
                          "сигнала — «обнаружение» здесь означает look-ahead")
        self.assertGreater(r.benchmark_loss_usd, 4000)
        self.assertTrue(any("не покрыт политикой" in f for f in r.findings))

    def test_frozen_position_is_execution_failure_not_protection(self):
        # H13: 17 попыток выйти из замороженного maple; H15: 28 из halt'нутого
        # Euler-требования — «решение верное, исполнить нельзя» обязано быть видно.
        for sid in ("H13_maple_orthogonal_dec_2022", "H15_euler_mar_2023"):
            r = _REPORTS[sid]
            self.assertTrue(r.protected.execution_failures, sid)
            self.assertTrue(any("отказ исполнения" in f for f in r.findings), sid)

    def test_quiet_controls_stay_quiet(self):
        for sid in ("H04_may_2021_cascade", "H05_terra_ust_luna_2022",
                    "H09_curve_vyper_july_2023", "H10_aug_2024_yen_carry",
                    "H11_bybit_hack_feb_2025", "H14_stream_xusd_nov_2025",
                    "H16_aave_capo_mar_2026"):
            r = _REPORTS[sid]
            self.assertEqual(r.capital_saved_usd, 0.0,
                             f"{sid}: контрольный сценарий перестал быть тихим")
            self.assertEqual(r.protected.final_equity, r.benchmark.final_equity, sid)

    def test_no_lookahead_detection_never_day_zero(self):
        for sid, r in _REPORTS.items():
            if r.detection_day is not None:
                self.assertGreaterEqual(r.detection_day, 1, sid)

    def test_determinism_across_reruns(self):
        for sid in ("H08_usdc_svb_depeg_2023", "H12_oct_10_2025_cascade"):
            again = run_replay(_SCENARIOS[sid])
            self.assertEqual(again.protected.bars, _REPORTS[sid].protected.bars, sid)


if __name__ == "__main__":
    unittest.main()
