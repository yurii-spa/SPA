"""Ставка ERC-4626 хранилищ: измеряем сами, отказываемся честно.

`stusd` (Angle) и `wusdm` (Mountain) не индексируются DeFiLlama вовсе — широкий
скан 15 639 пулов дал по ним ноль совпадений. Пока протокол не наблюдается,
капитал в него разместить нельзя.

Классический способ снять ставку с ERC-4626 — сравнить `convertToAssets` на двух
блоках — отвергнут по измерению: архивные вызовы анонимно отдаёт ровно ОДИН
публичный эндпоинт из трёх. Один эндпоинт — единственная точка доверия для числа,
которое пускает капитал. Поэтому цена доли читается на `latest` (это умеют все,
значит достижим кворум), ряд копится сам, и ставка выводится из двух собственных
наблюдений.

Тесты держат обе стороны. Только «отказ при одной точке» пропустил бы версию,
которая не выводит ставку никогда; только «выводит из двух точек» пропустил бы
версию, которая верит одному узлу и любому адресу.
"""
from __future__ import annotations

import unittest
from datetime import timedelta
from unittest import mock

from spa_core.data_pipeline import erc4626_rate_monitor as M
from spa_core.tests._freshness import now_utc

_ONE = 10 ** 18


def _hex_price(value: float) -> str:
    return hex(int(value * _ONE))


def _hex_symbol(text: str) -> str:
    raw = text.encode()
    body = (b"\x00" * 31 + b"\x20") + len(raw).to_bytes(32, "big") + raw.ljust(32, b"\x00")
    return "0x" + body.hex()


def _series(prices, hours_apart=24.0):
    now = now_utc()
    n = len(prices)
    return [{"share_price": p,
             "observed_at": (now - timedelta(hours=hours_apart * (n - 1 - i))).isoformat(),
             "witnesses": 2}
            for i, p in enumerate(prices)]


class TestQuorumAndIdentity(unittest.TestCase):
    """Кворум по значению И проверка личности контракта — оба обязательны."""

    def _fake(self, mapping):
        def _call(rpc, to, data, timeout=8):
            return mapping.get((rpc, data[:10]))
        return _call

    def test_agreeing_endpoints_yield_a_price(self):
        sym, conv = M._SEL_SYMBOL, M._SEL_CONVERT_TO_ASSETS
        m = {("a", sym): _hex_symbol("stUSD"), ("a", conv): _hex_price(1.16),
             ("b", sym): _hex_symbol("stUSD"), ("b", conv): _hex_price(1.16)}
        with mock.patch.object(M, "_eth_call", self._fake(m)):
            price, witnesses = M.read_share_price("0xdead", "stUSD", endpoints=["a", "b"])
        self.assertAlmostEqual(price, 1.16, places=10)
        self.assertEqual(sorted(witnesses), ["a", "b"])

    def test_wrong_symbol_rejects_the_address(self):
        """Контракт обязан назвать себя. Иначе адрес не тот — и число не берётся.

        Это единственное, что отличает наблюдение от догадки об адресе.
        """
        sym, conv = M._SEL_SYMBOL, M._SEL_CONVERT_TO_ASSETS
        m = {("a", sym): _hex_symbol("НЕ-ТОТ"), ("a", conv): _hex_price(1.16),
             ("b", sym): _hex_symbol("НЕ-ТОТ"), ("b", conv): _hex_price(1.16)}
        with mock.patch.object(M, "_eth_call", self._fake(m)):
            price, _ = M.read_share_price("0xdead", "stUSD", endpoints=["a", "b"])
        self.assertIsNone(price)

    def test_single_endpoint_is_not_enough(self):
        sym, conv = M._SEL_SYMBOL, M._SEL_CONVERT_TO_ASSETS
        m = {("a", sym): _hex_symbol("stUSD"), ("a", conv): _hex_price(1.16)}
        with mock.patch.object(M, "_eth_call", self._fake(m)):
            price, _ = M.read_share_price("0xdead", "stUSD", endpoints=["a", "b"])
        self.assertIsNone(price)

    def test_disagreement_is_refused_not_averaged(self):
        """Два узла с разным состоянием одного контракта: кто-то неправ, кто — неизвестно."""
        sym, conv = M._SEL_SYMBOL, M._SEL_CONVERT_TO_ASSETS
        m = {("a", sym): _hex_symbol("stUSD"), ("a", conv): _hex_price(1.16),
             ("b", sym): _hex_symbol("stUSD"), ("b", conv): _hex_price(1.20),
             ("c", sym): _hex_symbol("stUSD"), ("c", conv): _hex_price(1.16)}
        with mock.patch.object(M, "_eth_call", self._fake(m)):
            price, _ = M.read_share_price("0xdead", "stUSD", endpoints=["a", "b", "c"])
        self.assertIsNone(price, "большинство 2:1 не даёт права выбрать")

    def test_absurd_price_is_not_a_price(self):
        sym, conv = M._SEL_SYMBOL, M._SEL_CONVERT_TO_ASSETS
        for bad in (0.0, 0.1, 1e6):
            with self.subTest(price=bad):
                m = {(e, sym): _hex_symbol("stUSD") for e in ("a", "b")}
                m.update({(e, conv): _hex_price(bad) for e in ("a", "b")})
                with mock.patch.object(M, "_eth_call", self._fake(m)):
                    price, _ = M.read_share_price("0xdead", "stUSD", endpoints=["a", "b"])
                self.assertIsNone(price)


class TestRateDerivation(unittest.TestCase):

    def test_two_points_give_a_rate(self):
        """0.01 % за сутки ≈ 3.7 % годовых — обычная стейбл-ставка."""
        apy = M.derive_apy_pct(_series([1.0, 1.0001], hours_apart=24.0))
        self.assertIsNotNone(apy)
        self.assertAlmostEqual(apy, 3.72, delta=0.15)

    def test_one_point_refuses(self):
        """Первый прогон — не недостаток, а правильный ответ.

        Вывести доходность из одного замера нельзя ничем.
        """
        self.assertIsNone(M.derive_apy_pct(_series([1.0])))
        self.assertIsNone(M.derive_apy_pct([]))
        self.assertIsNone(M.derive_apy_pct(None))

    def test_points_too_close_refuse(self):
        """Близкие замеры превращают шум округления в дикую годовую цифру."""
        self.assertIsNone(M.derive_apy_pct(_series([1.0, 1.0001], hours_apart=1.0)))

    def test_absurd_result_is_refused_not_reported(self):
        """300 % на стейбл-хранилище — это «посчитали не то», а не находка."""
        self.assertIsNone(M.derive_apy_pct(_series([1.0, 1.5], hours_apart=24.0)))

    def test_a_falling_share_price_is_reported_as_negative(self):
        """Убыток — тоже наблюдение. Прятать его значило бы врать в другую сторону."""
        apy = M.derive_apy_pct(_series([1.0, 0.99995], hours_apart=24.0))
        self.assertIsNotNone(apy)
        self.assertLess(apy, 0.0)

    def test_broken_points_never_raise(self):
        for bad in ([{"share_price": "x", "observed_at": "z"}],
                    [{"share_price": 1.0}, {"share_price": 1.1}],
                    [{"observed_at": "not-a-date", "share_price": 1.0}] * 2):
            with self.subTest(series=bad):
                self.assertIsNone(M.derive_apy_pct(bad))


class TestObserveAccumulates(unittest.TestCase):

    def test_history_survives_a_failed_observation(self):
        """Неудача не стирает ряд — иначе один сетевой сбой обнуляет неделю работы."""
        from tempfile import TemporaryDirectory
        from pathlib import Path
        import json

        with TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / M.STATUS_FILENAME).write_text(json.dumps({
                "vaults": {"stusd": {"history": _series([1.0, 1.0001])}}}), encoding="utf-8")
            with mock.patch.object(M, "read_share_price", lambda *a, **k: (None, [])):
                out = M.observe(data_dir=d)
            self.assertEqual(len(out["vaults"]["stusd"]["history"]), 2,
                             "прошлые точки обязаны пережить неудачный прогон")
            self.assertIsNotNone(out["vaults"]["stusd"]["apy_pct"])

    def test_missing_rate_states_its_reason(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path

        with TemporaryDirectory() as tmp:
            with mock.patch.object(M, "read_share_price", lambda *a, **k: (1.16, ["a", "b"])):
                out = M.observe(data_dir=Path(tmp))
            entry = out["vaults"]["stusd"]
            self.assertIsNone(entry["apy_pct"])
            self.assertIn("≥2", entry["apy_note"])


if __name__ == "__main__":
    unittest.main()


class TestZeroGrowthIsNotZeroRate(unittest.TestCase):
    """Нулевой рост — «не измерено», а не «доходность 0 %».

    Измерено 2026-08-07. Производитель набрал вторую точку, но обе имели
    ОДИНАКОВУЮ цену доли: за сутки стейблкоин-хранилище не выросло в пределах
    точности числа. Расчёт честно вывел 0.0, число ушло в ``live_apy`` как
    НАБЛЮДЕНИЕ, монитор увидел два адаптера вне вменяемого диапазона APY, и
    оценка здоровья портфеля просела 74.7 → 69.43 — ниже критического порога.
    Ложное критичное.

    Защиты были от близких замеров (12ч) и от абсурдных значений (−5…60 %), но
    не от нулевого роста. «Не измерено» ≠ «измерено и равно нулю» — путать их
    значит выдавать отсутствие разрешения за результат.
    """

    def test_identical_share_price_refuses_instead_of_returning_zero(self):
        """Ровно наш случай — обе точки с одинаковой ценой доли."""
        p = 1.1617319305415383
        self.assertIsNone(M.derive_apy_pct(_series([p, p], hours_apart=24.0)))

    def test_a_measurable_rise_still_produces_a_rate(self):
        """Обратная сторона: отказ не должен съесть настоящие числа."""
        apy = M.derive_apy_pct(_series([1.0, 1.0001], hours_apart=24.0))
        self.assertIsNotNone(apy)
        self.assertGreater(apy, 0.0)

    def test_a_fall_is_still_reported(self):
        """Убыток — тоже измерение. Прятать его значило бы врать в другую сторону."""
        apy = M.derive_apy_pct(_series([1.0, 0.99995], hours_apart=24.0))
        self.assertIsNotNone(apy)
        self.assertLess(apy, 0.0)

    def test_the_series_is_kept_so_the_rate_can_appear_later(self):
        """Отказ НЕ отменяет накопление: ставка появится с измеримым ростом.

        Иначе «не измеримо сегодня» превратилось бы в «не измеримо никогда».
        """
        p = 1.16173193
        self.assertIsNone(M.derive_apy_pct(_series([p, p], hours_apart=24.0)))
        self.assertIsNotNone(M.derive_apy_pct(_series([p, p, p * 1.0001], hours_apart=24.0)))
