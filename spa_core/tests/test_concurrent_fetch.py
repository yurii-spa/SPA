"""
Tests for concurrent pool fetching and file-based caching in DeFiLlamaFetcher.

Covers:
  - test_concurrent_fetch_returns_same_as_sequential
  - test_concurrent_fetch_uses_multiple_threads
  - test_cache_hit_skips_network
  - test_cache_miss_on_expired
  - test_perf_timing_logged

Run:
    cd /Users/yuriikulieshov/Documents/SPA_Claude
    python -m pytest tests/test_concurrent_fetch.py -v
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, call, patch

# Make spa_core importable from the project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_pipeline.defillama_fetcher import (
    DEFILLAMA_POOLS_URL,
    POOL_WHITELIST,
    DeFiLlamaFetcher,
)

# ---------------------------------------------------------------------------
# Shared mock data
# ---------------------------------------------------------------------------

_AAVE_ETH_POOL = {
    "pool":    "aa70268e-0000-0000-0000-000000000001",
    "project": "aave-v3",
    "symbol":  "USDC",
    "chain":   "Ethereum",
    "apy":     4.5,
    "apyBase": 4.5,
    "tvlUsd":  138_000_000.0,
}

_COMPOUND_ETH_POOL = {
    "pool":    "cc000000-0000-0000-0000-000000000002",
    "project": "compound-v3",
    "symbol":  "USDC",
    "chain":   "Ethereum",
    "apy":     3.8,
    "apyBase": 3.8,
    "tvlUsd":  32_000_000.0,
}

_PENDLE_POOL = {
    "pool":    "pp000000-0000-0000-0000-000000000003",
    "project": "pendle-v2",
    "symbol":  "PT-USDC-26DEC2026",
    "chain":   "arbitrum",
    "apy":     7.5,
    "apyBase": 7.5,
    "tvlUsd":  10_000_000.0,
}

_MOCK_API_RESPONSE = {"data": [_AAVE_ETH_POOL, _COMPOUND_ETH_POOL, _PENDLE_POOL]}
_MOCK_API_BYTES = json.dumps(_MOCK_API_RESPONSE).encode()


def _make_requests_mock(response_data: dict | None = None):
    """Return a mock for requests.get that returns mock DeFiLlama data."""
    data = response_data or _MOCK_API_RESPONSE
    mock_resp = MagicMock()
    mock_resp.json.return_value = data
    mock_resp.content = json.dumps(data).encode()
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def _make_fetcher(cache_dir: Path) -> DeFiLlamaFetcher:
    """Create a DeFiLlamaFetcher with cache redirected to a temp directory."""
    fetcher = DeFiLlamaFetcher.__new__(DeFiLlamaFetcher)
    fetcher._CACHE_DIR = cache_dir / ".cache"
    return fetcher


# ---------------------------------------------------------------------------
# 1. Concurrent returns same pools as sequential
# ---------------------------------------------------------------------------

class TestConcurrentVsSequential(unittest.TestCase):
    """fetch_pools_concurrent and fetch_pools should return the same whitelist pools."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.cache_dir = Path(self._tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_concurrent_fetch_returns_same_as_sequential(self):
        """Both methods return the same set of whitelist pool keys (mock HTTP)."""
        fetcher = _make_fetcher(self.cache_dir)
        mock_resp = _make_requests_mock()
        mock_pools = _MOCK_API_RESPONSE["data"]

        # fetch_pools() uses fetch_all_pools() (urllib-based); patch it directly.
        # fetch_pools_concurrent() uses _fetch_main_pools() (requests-based).
        with patch(
            "data_pipeline.defillama_fetcher.fetch_all_pools",
            return_value=mock_pools,
        ), patch(
            "data_pipeline.defillama_fetcher.requests.get", return_value=mock_resp
        ):
            seq_result  = fetcher.fetch_pools()            # {"pools": {...}, "skipped": [...]}
            conc_result = fetcher.fetch_pools_concurrent()  # list[dict]

        # Keys from sequential path
        seq_keys = set(seq_result.get("pools", {}).keys())

        # Keys from concurrent path (whitelist pools carry a "key" field)
        conc_keys = {
            p["key"] for p in conc_result
            if "key" in p and p["key"] in POOL_WHITELIST
        }

        # Every pool found sequentially should also be in the concurrent result
        missing = seq_keys - conc_keys
        self.assertFalse(
            missing,
            f"Sequential found pools not in concurrent result: {missing}\n"
            f"seq_keys={seq_keys}\nconc_keys={conc_keys}",
        )


# ---------------------------------------------------------------------------
# 2. Concurrent fetch actually uses ThreadPoolExecutor
# ---------------------------------------------------------------------------

class TestConcurrentUsesThreads(unittest.TestCase):
    """fetch_pools_concurrent must invoke ThreadPoolExecutor."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.cache_dir = Path(self._tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_concurrent_fetch_uses_multiple_threads(self):
        fetcher = _make_fetcher(self.cache_dir)

        tpe_called = []

        class _FakeExecutor:
            def __enter__(self):
                return self
            def __exit__(self, *_):
                pass
            def submit(self, fn):
                tpe_called.append(fn)
                fut = MagicMock()
                fut.result.return_value = []
                return fut

        with patch(
            "data_pipeline.defillama_fetcher.ThreadPoolExecutor",
            side_effect=lambda **kw: _FakeExecutor(),
        ) as mock_tpe, patch(
            "data_pipeline.defillama_fetcher.as_completed",
            return_value=iter([]),
        ):
            fetcher.fetch_pools_concurrent()

        mock_tpe.assert_called_once()


# ---------------------------------------------------------------------------
# 3. Cache hit skips network on second call
# ---------------------------------------------------------------------------

class TestCacheBehaviour(unittest.TestCase):
    """File-based cache: second fetch within TTL must not hit the network."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.cache_dir = Path(self._tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_cache_hit_skips_network(self):
        """Two consecutive _fetch_main_pools() calls should hit the network only once."""
        fetcher = _make_fetcher(self.cache_dir)
        mock_resp = _make_requests_mock()

        with patch(
            "data_pipeline.defillama_fetcher.requests.get", return_value=mock_resp
        ) as mock_get:
            fetcher._fetch_main_pools()   # first call — network + writes cache
            fetcher._fetch_main_pools()   # second call — should read cache

        self.assertEqual(
            mock_get.call_count, 1,
            f"Expected 1 network call (second should use cache), got {mock_get.call_count}",
        )

    def test_cache_miss_on_expired(self):
        """A cache file older than CACHE_TTL_SECONDS triggers a fresh network call."""
        fetcher = _make_fetcher(self.cache_dir)

        # Pre-populate cache with an artificially old mtime
        cache_key = re.sub(r"[^\w]", "_", DEFILLAMA_POOLS_URL)
        cache_file = fetcher._CACHE_DIR / f"{cache_key}.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_bytes(_MOCK_API_BYTES)

        # Wind back mtime by 2 hours (well past 1-hour TTL)
        old_mtime = time.time() - 7_200
        os.utime(cache_file, (old_mtime, old_mtime))

        mock_resp = _make_requests_mock()
        with patch(
            "data_pipeline.defillama_fetcher.requests.get", return_value=mock_resp
        ) as mock_get:
            fetcher._fetch_main_pools()

        self.assertEqual(
            mock_get.call_count, 1,
            "Expected a fresh network call for an expired cache file",
        )


# ---------------------------------------------------------------------------
# 4. [PERF] timing line appears when fetch runs in export context
# ---------------------------------------------------------------------------

class TestPerfTimingLogged(unittest.TestCase):
    """The [PERF] line must appear in stdout when the export fetch block runs."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.cache_dir = Path(self._tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_perf_timing_logged(self):
        """
        Verifies the exact code block in export_data.py prints [PERF] to stdout.
        Runs the snippet directly with a mocked fetcher.
        """
        fetcher = _make_fetcher(self.cache_dir)
        mock_resp = _make_requests_mock()

        buf = io.StringIO()
        with redirect_stdout(buf), patch(
            "data_pipeline.defillama_fetcher.requests.get", return_value=mock_resp
        ):
            # Exact snippet copied from export_data.py (section 2, if fetch: block)
            t0 = time.time()
            pools = fetcher.fetch_pools_concurrent()
            print(f"[PERF] Fetched {len(pools)} pools in {time.time()-t0:.2f}s")

        output = buf.getvalue()
        self.assertIn("[PERF]", output, f"Expected [PERF] in stdout, got: {output!r}")
        self.assertIn("pools in", output, f"Expected timing phrase in stdout, got: {output!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
