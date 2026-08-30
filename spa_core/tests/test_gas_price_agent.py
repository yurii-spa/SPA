"""Агент цены газа (ADR-183): отказ источников — это «не измерено», не число.

Положительные контроли воспроизводят аварию 30.08: arbitrum/optimism_gas_monitor
при неотвечающих Blocknative/Infura молча печатали свой FALLBACK_GWEI, и
константа была неотличима от чтения. Новый агент обязан в этой же ситуации
сказать `unchecked` БЕЗ числа — и тесты держат именно эту границу.

Всё герметично: сеть заменяется инъектированным fetcher'ом, часы — параметром
`now`, файлы — tmp-каталогом (живой data/ не трогается).
"""
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import gas_price_agent as g

T0 = datetime(2026, 8, 30, 21, 0, tzinfo=timezone.utc)  # FROZEN-DATE-OK: дата аварии-образца


def fetcher_returning(mapping):
    """fetcher по словарю url→gwei; отсутствие url = источник молчит."""
    return lambda url: mapping.get(url)


class UncheckedNotAConstant(unittest.TestCase):
    """Ядро контракта: нет источников — нет числа."""

    def test_all_sources_dead_yields_unchecked_without_a_number(self):
        # Авария 30.08 как есть: ни один источник не ответил.
        r = g.measure_chain("arbitrum", fetcher_returning({}))
        self.assertEqual(r["source"], g.UNCHECKED)
        self.assertNotIn("gwei", r)

    def test_module_has_no_fallback_constant_at_all(self):
        # Класс аварии — само существование FALLBACK_GWEI. Его нет.
        self.assertFalse(hasattr(g, "FALLBACK_GWEI"))

    def test_ethereum_needs_two_agreeing_sources(self):
        one = {"https://eth.drpc.org": 0.07}
        r = g.measure_chain("ethereum", fetcher_returning(one))
        self.assertEqual(r["source"], g.UNCHECKED)
        two = dict(one, **{"https://1rpc.io/eth": 0.073})
        r2 = g.measure_chain("ethereum", fetcher_returning(two))
        self.assertEqual(r2["source"], g.LIVE)
        self.assertAlmostEqual(r2["gwei"], 0.0715, places=4)  # медиана двух

    def test_disagreeing_sources_are_a_feed_divergence_not_an_average(self):
        # Инвариант 2: расхождение фидов ⇒ отказ, а не среднее из спора.
        r = g.measure_chain("ethereum", fetcher_returning({
            "https://eth.drpc.org": 0.07, "https://1rpc.io/eth": 5.0}))
        self.assertEqual(r["source"], g.UNCHECKED)
        self.assertNotIn("gwei", r)

    def test_eth_spot_divergence_blocks_usd_per_leg(self):
        spot = lambda url: 2000.0 if "coinbase" in url else 2500.0
        e = g.measure_eth_usd(spot)
        self.assertEqual(e["source"], g.UNCHECKED)


class RegimeJudgement(unittest.TestCase):
    def _history(self, values):
        return list(values)

    def test_insufficient_history_is_named_not_guessed(self):
        v = g.regime_for([0.07] * (g.MIN_HISTORY_FOR_REGIME - 1),
                         {"source": g.LIVE, "gwei": 0.07})
        self.assertEqual(v["regime"], g.REGIME_NO_HISTORY)

    def test_cheap_and_expensive_by_own_percentiles(self):
        hist = [float(i) for i in range(1, 101)]  # 1..100 Gwei
        cheap = g.regime_for(hist, {"source": g.LIVE, "gwei": 10.0})
        dear = g.regime_for(hist, {"source": g.LIVE, "gwei": 95.0})
        mid = g.regime_for(hist, {"source": g.LIVE, "gwei": 50.0})
        self.assertEqual(cheap["regime"], g.REGIME_CHEAP)
        self.assertEqual(dear["regime"], g.REGIME_EXPENSIVE)
        self.assertEqual(mid["regime"], g.REGIME_NORMAL)

    def test_unmeasured_reading_gets_no_regime(self):
        v = g.regime_for([0.07] * 100, {"source": g.UNCHECKED})
        self.assertEqual(v["regime"], g.REGIME_UNMEASURED)

    def test_regime_history_uses_only_live_rows(self):
        # unchecked-строки истории не участвуют в перцентиле: run() пишет их
        # без gwei, а снимок берёт только source==live.
        with TemporaryDirectory() as td:
            gas = fetcher_returning({u: 0.07 for us in g.CHAIN_SOURCES.values() for u in us})
            spot = lambda url: 2491.0
            now = T0
            for i in range(g.MIN_HISTORY_FOR_REGIME + 1):
                st = g.run(td, gas, spot, now=now + timedelta(minutes=30 * i))
            eth = st["chains"]["ethereum"]
            self.assertEqual(eth["regime"], g.REGIME_NORMAL)


class RunAndPersistence(unittest.TestCase):
    def _fetchers(self, gwei=0.07, usd=2491.0):
        gas = fetcher_returning({u: gwei for us in g.CHAIN_SOURCES.values() for u in us})
        return gas, (lambda url: usd)

    def test_happy_path_writes_live_reading_and_usd_per_leg(self):
        gas, spot = self._fetchers()
        with TemporaryDirectory() as td:
            st = g.run(td, gas, spot, now=T0)
            eth = st["chains"]["ethereum"]
            self.assertEqual(eth["source"], g.LIVE)
            # 0.07 Gwei × 250k газа × $2491 = $0.0436
            self.assertAlmostEqual(eth["usd_per_leg"], 0.0436, places=3)
            on_disk = json.loads((Path(td) / g.OUTPUT_PATH).read_text())
            self.assertEqual(on_disk["chains"]["ethereum"]["source"], g.LIVE)
            self.assertTrue(on_disk["advisory"])

    def test_unchecked_tick_is_recorded_as_unchecked_on_disk(self):
        # История хранит ФАКТ «не измерено» — не ноль и не константу.
        with TemporaryDirectory() as td:
            g.run(td, fetcher_returning({}), lambda url: None, now=T0)
            on_disk = json.loads((Path(td) / g.OUTPUT_PATH).read_text())
            row = on_disk["history"]["ethereum"][0]
            self.assertEqual(row["source"], g.UNCHECKED)
            self.assertNotIn("gwei", row)

    def test_ring_buffer_trims_history(self):
        gas, spot = self._fetchers()
        with TemporaryDirectory() as td:
            out = Path(td) / g.OUTPUT_PATH
            out.parent.mkdir(parents=True)
            fat = {"history": {"ethereum": [
                {"ts": "x", "source": g.LIVE, "gwei": 0.07}] * (g.HISTORY_MAX_READINGS + 50)}}
            out.write_text(json.dumps(fat))
            g.run(td, gas, spot, now=T0)
            n = len(json.loads(out.read_text())["history"]["ethereum"])
            self.assertEqual(n, g.HISTORY_MAX_READINGS)

    def test_corrupt_history_file_does_not_crash_the_agent(self):
        gas, spot = self._fetchers()
        with TemporaryDirectory() as td:
            out = Path(td) / g.OUTPUT_PATH
            out.parent.mkdir(parents=True)
            out.write_text("{broken json")
            st = g.run(td, gas, spot, now=T0)
            self.assertEqual(st["chains"]["ethereum"]["source"], g.LIVE)


class AdvisoryBoundary(unittest.TestCase):
    """Агент — advisory: не гейтит, капитал не двигает, execution не знает."""

    def test_snapshot_says_advisory_true(self):
        gas = fetcher_returning({u: 0.07 for us in g.CHAIN_SOURCES.values() for u in us})
        st = g.run(".", gas, lambda url: 2491.0, now=T0, write=False)
        self.assertIs(st["advisory"], True)

    def test_module_never_imports_execution(self):
        src = Path(g.__file__).read_text()
        self.assertNotIn("spa_core.execution", src)
        self.assertNotIn("from spa_core import execution", src)

    def test_produces_contract_declared(self):
        self.assertEqual(g.PRODUCES, ("data/gas_price_history.json",))

    def test_expensive_advice_explicitly_spares_derisk(self):
        # Совет «отложить» обязан оговаривать, что де-риск не задерживается
        # (ADR-168) — иначе текст можно прочитать как гейт.
        self.assertIn("де-риск", g._ADVICE[g.REGIME_EXPENSIVE])


if __name__ == "__main__":
    unittest.main()
