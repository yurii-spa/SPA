"""Курс лаборатории считается по отметке времени — решение владельца 25.08 (вариант 1).

Карточка «Курс, по которому лаборатория решает "сработала авария", шумит сильнее
самой аварии — и убил четыре книги зря», ADR-139.

**Дефект.** Курс получался делением двух ДНЕВНЫХ цен: последний внутридневной
принт токена на последний внутридневной принт эфира. У разных токенов эти принты
приходятся на разные моменты суток, поэтому в день, когда эфир ходит на 5–10 %,
частное подхватывало не отвязку, а рассинхрон отметок.

Замер по 565 дням (карточка, записи #75–#76 `docs/DYNAMIC_LEVERAGE_GUARDIAN.md`):

* stETH/ETH «ходил» на 3.5 % в день, худшие отметки −17 % и **+33 % за сутки**;
* **59 дней из 565** двигались больше 5 % — ровно порог, по которому лаборатория
  объявляет отвязку и убивает книгу; десять дней — больше 12.5 % (порог
  ликвидации плечевой книги);
* 46–57 % каждого крупного движения отыгрывалось назад на следующий день,
  у самой цены эфира — того же источника, тех же дней — 2 %;
* средний УРОВЕНЬ был правильный (0.9994 при должном 1.0000) — врал разброс,
  поэтому полтора года никто не замечал.

Здесь проверяется механика починки, а не панель: панель перемеряется отдельно и
требует сети, которой из контейнера нет (ADR-139 §5).

Курс читают ТОЛЬКО исследовательские модули. Реальные деньги, RiskPolicy,
аллокатор и стоп-кран его не читают.
"""
from __future__ import annotations

import datetime as _dt
import unittest

from spa_core.strategy_lab.data.price_feed import (
    MAX_PAIR_GAP_S,
    RATIO_MEDIAN_WINDOW,
    _causal_median,
    _ratios_from_points,
)

DAY = "2024-08-05"


def _ts(day: str, hour: int = 0, minute: int = 0) -> float:
    return _dt.datetime.fromisoformat(
        f"{day}T{hour:02d}:{minute:02d}:00+00:00").timestamp()


def _points(day_to_pair):
    """{sym: {date: (price, ts)}} из компактной записи."""
    out = {}
    for sym, days in day_to_pair.items():
        out[sym] = {d: (price, ts) for d, (price, ts) in days.items()}
    return out


class TimestampPairing(unittest.TestCase):
    """Частное двух РАЗНЫХ моментов рынка — не курс."""

    def test_prints_close_in_time_are_paired(self):
        hist = _points({
            "eth":   {DAY: (3000.0, _ts(DAY, 23, 50))},
            "steth": {DAY: (2999.0, _ts(DAY, 23, 55))},
        })
        r = _ratios_from_points(hist, "eth", ("steth",), median_window=0)
        self.assertAlmostEqual(r["steth"][DAY], 2999.0 / 3000.0, places=6)

    def test_prints_hours_apart_are_refused_not_ratioed(self):
        """Ровно тот день, что убивал книги: эфир прошёл 10 % между принтами.

        Курс тут «упал» бы на 9 % — при неподвижной привязке. Раньше это
        объявлялось отвязкой; теперь день просто НЕ ИЗМЕРЕН.
        """
        hist = _points({
            "eth":   {DAY: (3300.0, _ts(DAY, 23, 55))},   # поздний принт, после роста
            "steth": {DAY: (2999.0, _ts(DAY, 2, 0))},     # ранний принт, до роста
        })
        r = _ratios_from_points(hist, "eth", ("steth",), median_window=0)
        self.assertNotIn(DAY, r["steth"],
                         "рассинхрон отметок снова подан как курс")

    def test_absent_day_is_absent_not_zero(self):
        """Инв. #17: «не измерено» ≠ «курс ноль» и ≠ «курс прежний».

        Потребитель ниже по течению fail-CLOSE'ится на отсутствующем курсе —
        подставить сюда что-нибудь значило бы снять этот отказ.
        """
        hist = _points({
            "eth":   {DAY: (3300.0, _ts(DAY, 23, 55))},
            "steth": {DAY: (2999.0, _ts(DAY, 2, 0))},
        })
        r = _ratios_from_points(hist, "eth", ("steth",), median_window=0)
        self.assertEqual(r["steth"], {})

    def test_gap_boundary_is_inclusive(self):
        base = _ts(DAY, 12, 0)
        for delta, expected in ((MAX_PAIR_GAP_S, True), (MAX_PAIR_GAP_S + 1, False)):
            with self.subTest(delta=delta):
                hist = _points({
                    "eth":   {DAY: (3000.0, base)},
                    "steth": {DAY: (2999.0, base + delta)},
                })
                r = _ratios_from_points(hist, "eth", ("steth",), median_window=0)
                self.assertEqual(DAY in r["steth"], expected)

    def test_missing_reference_day_is_skipped(self):
        hist = _points({
            "eth":   {},
            "steth": {DAY: (2999.0, _ts(DAY))},
        })
        r = _ratios_from_points(hist, "eth", ("steth",), median_window=0)
        self.assertEqual(r["steth"], {})


class CausalMedianIsInterimAndCausal(unittest.TestCase):
    """Временная мера решения владельца: причинная медиана за 5 дней."""

    def test_default_window_is_five(self):
        self.assertEqual(RATIO_MEDIAN_WINDOW, 5)

    def test_lone_spike_is_rejected(self):
        """Худшая измеренная отметка: +33 % за сутки на неподвижной привязке."""
        days = {f"2024-08-{d:02d}": 1.0 for d in range(1, 11)}
        days["2024-08-05"] = 1.33
        out = _causal_median(days, 5)
        self.assertAlmostEqual(out["2024-08-05"], 1.0, places=6)

    def test_median_never_looks_forward(self):
        """Причинная: значение дня не зависит ни от одного будущего дня.

        Иначе прогон подглядывал бы вперёд — и получал доходность, которой на
        живых деньгах не бывает.
        """
        days = {f"2024-08-{d:02d}": 1.0 for d in range(1, 6)}
        with_future = dict(days)
        with_future["2024-08-06"] = 5.0
        self.assertEqual(_causal_median(days, 5)["2024-08-05"],
                         _causal_median(with_future, 5)["2024-08-05"])

    def test_first_days_use_what_exists(self):
        days = {"2024-08-01": 1.0, "2024-08-02": 2.0}
        out = _causal_median(days, 5)
        self.assertEqual(out["2024-08-01"], 1.0)
        self.assertEqual(out["2024-08-02"], 1.5)

    def test_window_three_lets_a_two_day_artefact_through_and_five_does_not(self):
        """Почему именно 5, а не 3 — механикой, а не ссылкой на замер.

        Два подряд испорченных дня внутри окна 3 составляют БОЛЬШИНСТВО и
        становятся медианой; внутри окна 5 они остаются меньшинством.
        """
        days = {"2024-08-01": 1.0, "2024-08-02": 1.0, "2024-08-03": 1.0,
                "2024-08-04": 1.30, "2024-08-05": 1.30}
        self.assertAlmostEqual(_causal_median(days, 3)["2024-08-05"], 1.30, places=6)
        self.assertAlmostEqual(_causal_median(days, 5)["2024-08-05"], 1.00, places=6)

    def test_zero_window_disables_smoothing(self):
        days = {"2024-08-01": 1.0, "2024-08-02": 1.33}
        self.assertEqual(_causal_median(days, 0), days)

    def test_a_real_sustained_depeg_still_gets_through(self):
        """ОБРАТНЫЙ КОНТРОЛЬ — самый важный тест файла.

        Сглаживание, которое глушит и настоящую отвязку, не чинит лабораторию,
        а ослепляет её. Устойчивая просадка обязана дойти до порога.
        """
        days = {f"2024-08-{d:02d}": 1.0 for d in range(1, 6)}
        days.update({f"2024-08-{d:02d}": 0.90 for d in range(6, 14)})
        out = _causal_median(days, 5)
        self.assertLess(out["2024-08-13"], 0.95,
                        "настоящая отвязка не дошла до порога — сглаживание ослепило гейт")


class BothRatioFamiliesAreFixed(unittest.TestCase):
    """Тот же источник, тот же дефект — BTC-обёртки лечатся тем же кодом."""

    def test_btc_wrapper_ratio_refuses_desynced_prints(self):
        hist = _points({
            "btc":   {DAY: (66000.0, _ts(DAY, 23, 55))},
            "tbtc":  {DAY: (60000.0, _ts(DAY, 2, 0))},
        })
        r = _ratios_from_points(hist, "btc", ("tbtc",), median_window=0)
        self.assertEqual(r["tbtc"], {})

    def test_smoothing_applies_to_every_symbol_asked_for(self):
        base = _ts(DAY, 12, 0)
        hist = {"eth": {}, "steth": {}, "eeth": {}}
        for i in range(1, 8):
            d = f"2024-08-{i:02d}"
            t = base + i * 86400
            hist["eth"][d] = (3000.0, t)
            hist["steth"][d] = (3000.0 * (1.33 if i == 4 else 1.0), t)
            hist["eeth"][d] = (3000.0 * (1.33 if i == 4 else 1.0), t)
        r = _ratios_from_points(hist, "eth", ("steth", "eeth"))
        for sym in ("steth", "eeth"):
            with self.subTest(symbol=sym):
                self.assertAlmostEqual(r[sym]["2024-08-04"], 1.0, places=6)


class FeedSurfaceKeepsItsShape(unittest.TestCase):
    """Правка источника не должна ломать форму ответа фида."""

    def test_history_projects_prices_from_points(self):
        from spa_core.strategy_lab.data.price_feed import _parse_chart, _parse_chart_points
        payload = {"coins": {"ethereum:0xabc": {"symbol": "X", "prices": [
            {"timestamp": _ts(DAY, 10), "price": 3000.0},
            {"timestamp": _ts(DAY, 23), "price": 3010.0},
        ]}}}
        pts = _parse_chart_points(payload, "0xabc", "eth")
        prices = _parse_chart(payload, "0xabc", "eth")
        self.assertEqual(prices[DAY], 3010.0, "последний принт дня должен выигрывать")
        self.assertEqual(pts[DAY][0], 3010.0)
        self.assertAlmostEqual(pts[DAY][1], _ts(DAY, 23), places=3)


if __name__ == "__main__":
    unittest.main()
