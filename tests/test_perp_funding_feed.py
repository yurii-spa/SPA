"""
Tests for spa_core/feeds/perp_funding_feed.py — Hyperliquid perp funding rate feed.

Tests mock urllib responses (patch urllib.request.urlopen) to avoid live API calls.
"""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from spa_core.feeds.perp_funding_feed import (
    HISTORY_MAX,
    HOURS_PER_YEAR,
    MAX_RETRIES,
    STALE_AFTER_S,
    PerpFundingFeed,
    PerpFundingRate,
    fetch_and_save,
    get_funding_annual,
    load_latest,
)


def _make_hyperliquid_response(assets=None):
    """Build a fake Hyperliquid metaAndAssetCtxs response."""
    if assets is None:
        assets = [
            {"name": "BTC", "funding": "0.000015", "openInterest": "5000",
             "markPx": "65000.0", "premium": "0.0001"},
            {"name": "ETH", "funding": "0.000012", "openInterest": "150000",
             "markPx": "3200.5", "premium": "0.00008"},
            {"name": "SOL", "funding": "0.000020", "openInterest": "2000000",
             "markPx": "140.0", "premium": "0.0002"},
            {"name": "ARB", "funding": "0.000005", "openInterest": "10000000",
             "markPx": "1.05", "premium": "0.00001"},
            {"name": "DOGE", "funding": "0.000001", "openInterest": "50000000",
             "markPx": "0.15", "premium": "0.00003"},
        ]
    meta = {"universe": [{"name": a["name"]} for a in assets]}
    ctxs = [
        {
            "funding": a["funding"],
            "openInterest": a["openInterest"],
            "markPx": a["markPx"],
            "premium": a.get("premium", "0"),
        }
        for a in assets
    ]
    return json.dumps([meta, ctxs]).encode("utf-8")


def _mock_urlopen_success(response_bytes):
    """Create a mock urlopen that returns the given bytes."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = response_bytes
    mock_resp.headers = MagicMock()
    mock_resp.headers.get.return_value = ""
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


class TestPerpFundingRate(unittest.TestCase):
    """Test PerpFundingRate dataclass."""

    def test_to_dict(self):
        r = PerpFundingRate(
            asset="ETH",
            funding_rate_1h=0.000012,
            funding_rate_8h=0.000096,
            funding_rate_annual=0.10512,
            open_interest_usd=850_000_000.0,
            mark_price=3200.5,
            premium=0.00008,
            timestamp="2026-06-21T15:00:00+00:00",
        )
        d = r.to_dict()
        self.assertEqual(d["funding_rate_1h"], 0.000012)
        self.assertEqual(d["funding_rate_annual"], 0.10512)
        self.assertNotIn("asset", d)

    def test_annualize_basic(self):
        result = PerpFundingFeed._annualize(0.000012)
        self.assertAlmostEqual(result, 0.000012 * 8760, places=6)

    def test_annualize_zero(self):
        self.assertEqual(PerpFundingFeed._annualize(0.0), 0.0)

    def test_annualize_negative(self):
        result = PerpFundingFeed._annualize(-0.000012)
        self.assertAlmostEqual(result, -0.000012 * 8760, places=6)

    def test_annualize_exact_value(self):
        result = PerpFundingFeed._annualize(0.000012)
        expected = 0.10512
        self.assertAlmostEqual(result, expected, places=5)


class TestPerpFundingFeedFetch(unittest.TestCase):
    """Test PerpFundingFeed fetch and normalization."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmp_dir)
        self.feed = PerpFundingFeed(data_dir=self.data_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    @patch("urllib.request.urlopen")
    def test_successful_fetch(self, mock_urlopen):
        response = _make_hyperliquid_response()
        mock_urlopen.return_value = _mock_urlopen_success(response)
        rates = self.feed.fetch()
        self.assertIsNotNone(rates)
        self.assertGreater(len(rates), 0)
        eth = next((r for r in rates if r.asset == "ETH"), None)
        self.assertIsNotNone(eth)
        self.assertEqual(eth.funding_rate_1h, 0.000012)

    @patch("urllib.request.urlopen")
    def test_eth_funding_parsed_correctly(self, mock_urlopen):
        response = _make_hyperliquid_response()
        mock_urlopen.return_value = _mock_urlopen_success(response)
        rates = self.feed.fetch()
        eth = next(r for r in rates if r.asset == "ETH")
        self.assertAlmostEqual(eth.funding_rate_1h, 0.000012, places=8)
        self.assertAlmostEqual(eth.funding_rate_8h, 0.000012 * 8, places=8)
        self.assertAlmostEqual(eth.funding_rate_annual, 0.000012 * HOURS_PER_YEAR, places=5)

    @patch("urllib.request.urlopen")
    def test_btc_funding_parsed(self, mock_urlopen):
        response = _make_hyperliquid_response()
        mock_urlopen.return_value = _mock_urlopen_success(response)
        rates = self.feed.fetch()
        btc = next(r for r in rates if r.asset == "BTC")
        self.assertAlmostEqual(btc.funding_rate_1h, 0.000015, places=8)

    @patch("urllib.request.urlopen")
    def test_sol_funding_parsed(self, mock_urlopen):
        response = _make_hyperliquid_response()
        mock_urlopen.return_value = _mock_urlopen_success(response)
        rates = self.feed.fetch()
        sol = next(r for r in rates if r.asset == "SOL")
        self.assertAlmostEqual(sol.funding_rate_1h, 0.000020, places=8)

    @patch("urllib.request.urlopen")
    def test_arb_funding_parsed(self, mock_urlopen):
        response = _make_hyperliquid_response()
        mock_urlopen.return_value = _mock_urlopen_success(response)
        rates = self.feed.fetch()
        arb = next((r for r in rates if r.asset == "ARB"), None)
        self.assertIsNotNone(arb)
        self.assertAlmostEqual(arb.funding_rate_1h, 0.000005, places=8)

    @patch("urllib.request.urlopen")
    def test_open_interest_usd(self, mock_urlopen):
        response = _make_hyperliquid_response()
        mock_urlopen.return_value = _mock_urlopen_success(response)
        rates = self.feed.fetch()
        eth = next(r for r in rates if r.asset == "ETH")
        expected_oi = 150000 * 3200.5
        self.assertAlmostEqual(eth.open_interest_usd, expected_oi, places=0)

    @patch("urllib.request.urlopen")
    def test_mark_price(self, mock_urlopen):
        response = _make_hyperliquid_response()
        mock_urlopen.return_value = _mock_urlopen_success(response)
        rates = self.feed.fetch()
        eth = next(r for r in rates if r.asset == "ETH")
        self.assertAlmostEqual(eth.mark_price, 3200.5, places=1)

    @patch("urllib.request.urlopen")
    def test_untracked_asset_excluded(self, mock_urlopen):
        response = _make_hyperliquid_response()
        mock_urlopen.return_value = _mock_urlopen_success(response)
        rates = self.feed.fetch()
        doge = next((r for r in rates if r.asset == "DOGE"), None)
        self.assertIsNone(doge)

    @patch("urllib.request.urlopen")
    def test_fetch_disabled(self, mock_urlopen):
        feed = PerpFundingFeed(data_dir=self.data_dir, enabled=False)
        rates = feed.fetch()
        self.assertIsNone(rates)
        mock_urlopen.assert_not_called()


class TestPerpFundingFeedFailure(unittest.TestCase):
    """Test failure scenarios."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmp_dir)
        self.feed = PerpFundingFeed(data_dir=self.data_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    @patch("urllib.request.urlopen")
    @patch("time.sleep")
    def test_failed_fetch_returns_none(self, mock_sleep, mock_urlopen):
        mock_urlopen.side_effect = Exception("Connection refused")
        rates = self.feed.fetch()
        self.assertIsNone(rates)

    @patch("urllib.request.urlopen")
    @patch("time.sleep")
    def test_failed_fetch_writes_stale(self, mock_sleep, mock_urlopen):
        mock_urlopen.side_effect = Exception("Connection refused")
        result = self.feed.run()
        self.assertTrue(result["stale"])
        self.assertIn("error", result)

    @patch("urllib.request.urlopen")
    @patch("time.sleep")
    def test_retry_count(self, mock_sleep, mock_urlopen):
        mock_urlopen.side_effect = Exception("timeout")
        self.feed._post_info({"type": "metaAndAssetCtxs"})
        self.assertEqual(mock_urlopen.call_count, MAX_RETRIES)

    @patch("urllib.request.urlopen")
    @patch("time.sleep")
    def test_exponential_backoff_delays(self, mock_sleep, mock_urlopen):
        mock_urlopen.side_effect = Exception("timeout")
        self.feed._post_info({"type": "metaAndAssetCtxs"})
        calls = mock_sleep.call_args_list
        self.assertEqual(len(calls), MAX_RETRIES - 1)
        self.assertAlmostEqual(calls[0][0][0], 1.0, places=1)
        self.assertAlmostEqual(calls[1][0][0], 2.0, places=1)

    @patch("urllib.request.urlopen")
    def test_malformed_json_returns_none(self, mock_urlopen):
        mock_resp = _mock_urlopen_success(b"not json at all")
        mock_urlopen.return_value = mock_resp
        rates = self.feed.fetch()
        self.assertIsNone(rates)

    @patch("urllib.request.urlopen")
    def test_wrong_structure_returns_none(self, mock_urlopen):
        mock_resp = _mock_urlopen_success(json.dumps({"wrong": True}).encode())
        mock_urlopen.return_value = mock_resp
        rates = self.feed.fetch()
        self.assertIsNone(rates)

    @patch("urllib.request.urlopen")
    def test_empty_array_returns_none(self, mock_urlopen):
        mock_resp = _mock_urlopen_success(json.dumps([]).encode())
        mock_urlopen.return_value = mock_resp
        rates = self.feed.fetch()
        self.assertIsNone(rates)


class TestPerpFundingFeedAtomicWrite(unittest.TestCase):
    """Test atomic write and file operations."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmp_dir)
        self.feed = PerpFundingFeed(data_dir=self.data_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    @patch("urllib.request.urlopen")
    def test_run_creates_file(self, mock_urlopen):
        response = _make_hyperliquid_response()
        mock_urlopen.return_value = _mock_urlopen_success(response)
        self.feed.run()
        self.assertTrue(self.feed.data_file.exists())

    @patch("urllib.request.urlopen")
    def test_run_file_is_valid_json(self, mock_urlopen):
        response = _make_hyperliquid_response()
        mock_urlopen.return_value = _mock_urlopen_success(response)
        self.feed.run()
        with open(self.feed.data_file) as f:
            data = json.load(f)
        self.assertIn("assets", data)
        self.assertIn("ETH", data["assets"])

    @patch("urllib.request.urlopen")
    def test_run_file_has_correct_schema(self, mock_urlopen):
        response = _make_hyperliquid_response()
        mock_urlopen.return_value = _mock_urlopen_success(response)
        result = self.feed.run()
        self.assertIn("timestamp", result)
        self.assertIn("fetched_at", result)
        self.assertIn("stale", result)
        self.assertIn("assets", result)
        self.assertFalse(result["stale"])

    @patch("urllib.request.urlopen")
    def test_no_tmp_file_left(self, mock_urlopen):
        response = _make_hyperliquid_response()
        mock_urlopen.return_value = _mock_urlopen_success(response)
        self.feed.run()
        tmp_files = list(self.data_dir.glob("*.tmp"))
        self.assertEqual(len(tmp_files), 0)

    @patch("urllib.request.urlopen")
    def test_history_file_created(self, mock_urlopen):
        response = _make_hyperliquid_response()
        mock_urlopen.return_value = _mock_urlopen_success(response)
        self.feed.run()
        self.assertTrue(self.feed.history_file.exists())


class TestPerpFundingFeedRingBuffer(unittest.TestCase):
    """Test ring buffer capping."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmp_dir)
        self.feed = PerpFundingFeed(data_dir=self.data_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_ring_buffer_capped(self):
        big_history = [{"i": i} for i in range(HISTORY_MAX + 50)]
        with open(self.feed.history_file, "w") as f:
            json.dump(big_history, f)
        payload = {
            "timestamp": "2026-06-21T10:00:00+00:00",
            "fetched_at": time.time(),
            "stale": False,
            "assets": {"ETH": {"funding_rate_annual": 0.1}},
        }
        self.feed._append_history(payload)
        with open(self.feed.history_file) as f:
            history = json.load(f)
        self.assertLessEqual(len(history), HISTORY_MAX)

    @patch("urllib.request.urlopen")
    def test_multiple_runs_accumulate_history(self, mock_urlopen):
        response = _make_hyperliquid_response()
        for _ in range(5):
            mock_urlopen.return_value = _mock_urlopen_success(response)
            self.feed.run()
        with open(self.feed.history_file) as f:
            history = json.load(f)
        self.assertEqual(len(history), 5)


class TestPerpFundingFeedLoad(unittest.TestCase):
    """Test load and stale detection."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmp_dir)
        self.feed = PerpFundingFeed(data_dir=self.data_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_load_missing_file(self):
        data = self.feed.load()
        self.assertEqual(data, {})

    def test_load_stale_by_age(self):
        old_data = {
            "timestamp": "2026-06-21T01:00:00",
            "fetched_at": time.time() - STALE_AFTER_S - 100,
            "stale": False,
            "assets": {"ETH": {"funding_rate_annual": 0.1}},
        }
        with open(self.feed.data_file, "w") as f:
            json.dump(old_data, f)
        data = self.feed.load()
        self.assertTrue(data.get("stale"))

    def test_load_fresh(self):
        fresh_data = {
            "timestamp": "2026-06-21T15:00:00",
            "fetched_at": time.time(),
            "stale": False,
            "assets": {"ETH": {"funding_rate_annual": 0.1}},
        }
        with open(self.feed.data_file, "w") as f:
            json.dump(fresh_data, f)
        data = self.feed.load()
        self.assertFalse(data.get("stale"))


class TestModuleLevelAPI(unittest.TestCase):
    """Test module-level convenience functions."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmp_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_get_funding_annual_returns_float(self):
        fresh_data = {
            "timestamp": "2026-06-21T15:00:00",
            "fetched_at": time.time(),
            "stale": False,
            "assets": {
                "ETH": {"funding_rate_annual": 0.10512},
            },
        }
        data_file = self.data_dir / "perp_funding_rates.json"
        with open(data_file, "w") as f:
            json.dump(fresh_data, f)
        result = get_funding_annual("ETH", data_dir=self.data_dir)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 0.10512, places=5)

    def test_get_funding_annual_missing_asset(self):
        fresh_data = {
            "timestamp": "2026-06-21T15:00:00",
            "fetched_at": time.time(),
            "stale": False,
            "assets": {"ETH": {"funding_rate_annual": 0.1}},
        }
        data_file = self.data_dir / "perp_funding_rates.json"
        with open(data_file, "w") as f:
            json.dump(fresh_data, f)
        result = get_funding_annual("DOGE", data_dir=self.data_dir)
        self.assertIsNone(result)

    def test_get_funding_annual_stale_returns_none(self):
        stale_data = {
            "timestamp": "2026-06-21T01:00:00",
            "fetched_at": time.time() - STALE_AFTER_S - 100,
            "stale": False,
            "assets": {"ETH": {"funding_rate_annual": 0.1}},
        }
        data_file = self.data_dir / "perp_funding_rates.json"
        with open(data_file, "w") as f:
            json.dump(stale_data, f)
        result = get_funding_annual("ETH", data_dir=self.data_dir)
        self.assertIsNone(result)

    def test_get_funding_annual_no_file_returns_none(self):
        result = get_funding_annual("ETH", data_dir=self.data_dir)
        self.assertIsNone(result)

    def test_load_latest_missing(self):
        data = load_latest(data_dir=self.data_dir)
        self.assertEqual(data, {})

    def test_load_latest_existing(self):
        test_data = {"stale": False, "assets": {"ETH": {}}}
        data_file = self.data_dir / "perp_funding_rates.json"
        with open(data_file, "w") as f:
            json.dump(test_data, f)
        data = load_latest(data_dir=self.data_dir)
        self.assertIn("assets", data)

    @patch("urllib.request.urlopen")
    def test_fetch_and_save(self, mock_urlopen):
        response = _make_hyperliquid_response()
        mock_urlopen.return_value = _mock_urlopen_success(response)
        result = fetch_and_save(data_dir=self.data_dir)
        self.assertIsNotNone(result)
        self.assertFalse(result["stale"])
        self.assertIn("ETH", result["assets"])

    @patch("urllib.request.urlopen")
    @patch("time.sleep")
    def test_fetch_and_save_failure(self, mock_sleep, mock_urlopen):
        mock_urlopen.side_effect = Exception("network error")
        result = fetch_and_save(data_dir=self.data_dir)
        self.assertIsNotNone(result)
        self.assertTrue(result["stale"])


class TestPerpFundingFeedGetRate(unittest.TestCase):
    """Test get_rate method."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmp_dir)
        self.feed = PerpFundingFeed(data_dir=self.data_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_get_rate_from_cache(self):
        fresh_data = {
            "timestamp": "2026-06-21T15:00:00",
            "fetched_at": time.time(),
            "stale": False,
            "assets": {"ETH": {"funding_rate_annual": 0.10512}},
        }
        with open(self.feed.data_file, "w") as f:
            json.dump(fresh_data, f)
        rate = self.feed.get_rate("ETH")
        self.assertAlmostEqual(rate, 0.10512, places=5)

    def test_get_rate_missing_asset_cache(self):
        fresh_data = {
            "timestamp": "2026-06-21T15:00:00",
            "fetched_at": time.time(),
            "stale": False,
            "assets": {"ETH": {"funding_rate_annual": 0.1}},
        }
        with open(self.feed.data_file, "w") as f:
            json.dump(fresh_data, f)
        rate = self.feed.get_rate("XRP")
        self.assertIsNone(rate)


class TestNormalization(unittest.TestCase):
    """Test edge cases in normalization."""

    def setUp(self):
        self.feed = PerpFundingFeed(data_dir=Path(tempfile.mkdtemp()))

    def test_missing_asset_in_universe(self):
        universe = [{"name": "DOGE"}]
        ctxs = [{"funding": "0.0001", "openInterest": "100", "markPx": "0.15"}]
        rates = self.feed._normalize(universe, ctxs)
        self.assertEqual(len(rates), 0)

    def test_malformed_ctx(self):
        universe = [{"name": "ETH"}]
        ctxs = ["not_a_dict"]
        rates = self.feed._normalize(universe, ctxs)
        self.assertEqual(len(rates), 0)

    def test_negative_funding(self):
        universe = [{"name": "ETH"}]
        ctxs = [{"funding": "-0.00005", "openInterest": "100", "markPx": "3000"}]
        rates = self.feed._normalize(universe, ctxs)
        self.assertEqual(len(rates), 1)
        self.assertLess(rates[0].funding_rate_annual, 0)

    def test_zero_funding(self):
        universe = [{"name": "ETH"}]
        ctxs = [{"funding": "0", "openInterest": "100", "markPx": "3000"}]
        rates = self.feed._normalize(universe, ctxs)
        self.assertEqual(len(rates), 1)
        self.assertEqual(rates[0].funding_rate_annual, 0.0)


if __name__ == "__main__":
    unittest.main()
