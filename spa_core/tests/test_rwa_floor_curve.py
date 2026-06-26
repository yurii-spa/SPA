"""
spa_core/tests/test_rwa_floor_curve.py — the RWA risk-free-FLOOR forward record.

DISCONNECT (a) coverage. Verifies the floor-curve append contract (mirrors rwa_backstop/nav_curve
+ the rates-desk paper track):
  - one point per UTC day appended to data/rwa_floor_curve.json (atomic, no leftover tmp),
  - idempotent per UTC day — re-running the same day REFRESHES, never dups,
  - ring-buffer cap (SERIES_CAP),
  - restart-survival — the series reloads from disk intact and continues,
  - FAIL-CLOSED — a bad/empty/unavailable feed SKIPS the day's append (no fabricated point),
  - summarize_floor produces the documented forward-point shape,
  - record_forward_point() pulls the LIVE feed (injected) and appends.

Pure synthetic, no network (the RWAFeed fetcher is injected). LLM-forbidden.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import os

from spa_core.strategy_lab.data import rwa_floor_curve as fc
from spa_core.strategy_lab.data.rwa_feed import RWAFeed


# ── fixtures ──────────────────────────────────────────────────────────────────────────────────
def _floor(date=None, apy=3.375, median=3.4, n_pools=7, total_tvl=5_970_000_000.0):
    d = {
        "floor_apy_pct": apy,
        "method": "tvl_weighted",
        "tvl_weighted_apy_pct": apy,
        "median_apy_pct": median,
        "n_pools": n_pools,
        "total_tvl_usd": total_tvl,
        "generated_at": "2026-06-26T00:00:00+00:00",
    }
    return d


def _pools_payload():
    """Two qualifying tokenized-T-bill pools above the $5M floor (TVL-weighted ≈ 3.375%)."""
    return {
        "status": "success",
        "data": [
            {"project": "blackrock-buidl", "symbol": "BUIDL", "apy": 3.5,
             "tvlUsd": 831_000_000.0, "pool": "buidl-pool"},
            {"project": "circle-usyc", "symbol": "USYC", "apy": 3.3,
             "tvlUsd": 3_000_000_000.0, "pool": "usyc-pool"},
        ],
    }


class _FakeFetcher:
    def __init__(self, payload):
        self._payload = payload
        self.calls = 0

    def __call__(self, url):
        self.calls += 1
        return self._payload


# ── 1. summarize_floor shape ──────────────────────────────────────────────────────────────────
def test_summarize_floor_shape():
    pt = fc.summarize_floor(_floor(date="2026-06-26"), date="2026-06-26")
    assert pt is not None
    for k in ("date", "ts", "floor_apy_pct", "median_apy_pct", "n_pools", "total_tvl_usd"):
        assert k in pt
    assert pt["date"] == "2026-06-26"
    assert pt["floor_apy_pct"] == 3.375
    assert pt["n_pools"] == 7


def test_summarize_floor_fail_closed_on_bad_input():
    assert fc.summarize_floor(None) is None
    assert fc.summarize_floor({}) is None
    assert fc.summarize_floor({"floor_apy_pct": "oops"}) is None


# ── 2. append one point per day + shape ──────────────────────────────────────────────────────────
def test_append_one_point(tmp_path):
    path = tmp_path / "rwa_floor_curve.json"
    doc = fc.record_forward_point(_floor(), curve_path=path, date="2026-06-26")
    assert doc["n_points"] == 1
    assert doc["series"][0]["date"] == "2026-06-26"
    assert doc["advisory"] is True and doc["research_only"] is True
    assert doc["latest"]["floor_apy_pct"] == 3.375
    assert path.exists()


# ── 3. idempotent per UTC day — re-run same day → no dup ──────────────────────────────────────────
def test_idempotent_same_day_no_dup(tmp_path):
    path = tmp_path / "rwa_floor_curve.json"
    fc.record_forward_point(_floor(apy=3.30), curve_path=path, date="2026-06-26")
    doc = fc.record_forward_point(_floor(apy=3.45), curve_path=path, date="2026-06-26")
    assert doc["n_points"] == 1, "re-running the same day must REFRESH, not dup"
    assert doc["series"][-1]["floor_apy_pct"] == 3.45  # refreshed to the latest measurement


def test_distinct_days_accumulate(tmp_path):
    path = tmp_path / "rwa_floor_curve.json"
    fc.record_forward_point(_floor(), curve_path=path, date="2026-06-24")
    fc.record_forward_point(_floor(), curve_path=path, date="2026-06-25")
    doc = fc.record_forward_point(_floor(), curve_path=path, date="2026-06-26")
    assert doc["n_points"] == 3
    assert [p["date"] for p in doc["series"]] == ["2026-06-24", "2026-06-25", "2026-06-26"]


# ── 4. ring-buffer cap ────────────────────────────────────────────────────────────────────────────
def test_ring_buffer_cap(tmp_path):
    path = tmp_path / "rwa_floor_curve.json"
    for i in range(fc.SERIES_CAP + 50):
        day = f"d{i}"  # distinct synthetic date strings → accumulate (idempotency keys on date)
        fc.append_point({"date": day, "ts": "t", "floor_apy_pct": 3.4,
                         "median_apy_pct": 3.4, "n_pools": 7, "total_tvl_usd": 1.0},
                        curve_path=path)
    doc = fc._load_curve(path)
    assert len(doc["series"]) == fc.SERIES_CAP


# ── 5. fail-CLOSED — feed unavailable / bad → no append, prior series intact ──────────────────────
def test_fail_closed_feed_down_no_append(tmp_path):
    """A live feed that raises (network down) → SKIP, no file fabricated."""
    path = tmp_path / "rwa_floor_curve.json"

    def _boom(url):
        raise RuntimeError("network down")

    feed = RWAFeed(fetcher=_boom, cache_path=tmp_path / "cache.json")
    assert fc.record_forward_point(curve_path=path, feed=feed) is None
    assert not path.exists()


def test_fail_closed_preserves_existing_series(tmp_path):
    """A bad measurement after a good day must NOT touch the existing series."""
    path = tmp_path / "rwa_floor_curve.json"
    fc.record_forward_point(_floor(), curve_path=path, date="2026-06-25")
    # bad floor dict → skip
    assert fc.record_forward_point({}, curve_path=path, date="2026-06-26") is None
    doc = fc._load_curve(path)
    assert doc["n_points"] == 1
    assert doc["series"][-1]["date"] == "2026-06-25"


# ── 6. restart-survival — reload intact and continue ──────────────────────────────────────────────
def test_restart_survival(tmp_path):
    path = tmp_path / "rwa_floor_curve.json"
    fc.record_forward_point(_floor(), curve_path=path, date="2026-06-24")
    fc.record_forward_point(_floor(), curve_path=path, date="2026-06-25")
    reloaded = fc._load_curve(path)  # simulate a fresh process
    assert [p["date"] for p in reloaded["series"]] == ["2026-06-24", "2026-06-25"]
    doc = fc.record_forward_point(_floor(), curve_path=path, date="2026-06-26")
    assert [p["date"] for p in doc["series"]] == ["2026-06-24", "2026-06-25", "2026-06-26"]


def test_corrupt_file_starts_fresh(tmp_path):
    path = tmp_path / "rwa_floor_curve.json"
    path.write_text("{ not json", encoding="utf-8")
    doc = fc.record_forward_point(_floor(), curve_path=path, date="2026-06-26")
    assert doc["n_points"] == 1


# ── 7. atomic write — no leftover tmp ─────────────────────────────────────────────────────────────
def test_atomic_no_leftover_tmp(tmp_path):
    path = tmp_path / "rwa_floor_curve.json"
    fc.record_forward_point(_floor(), curve_path=path, date="2026-06-26")
    with open(path) as f:
        on_disk = json.load(f)
    assert on_disk["n_points"] == 1
    leftovers = [p for p in os.listdir(tmp_path) if p.startswith(".") and p.endswith(".tmp")]
    assert not leftovers


# ── 8. wiring — record_forward_point pulls the LIVE feed (injected, no network) ───────────────────
def test_record_pulls_live_feed_and_appends(tmp_path):
    """record_forward_point() with no explicit floor must fetch the live feed and append a point
    carrying the live blended rate (TVL-weighted ≈ 3.375%)."""
    path = tmp_path / "rwa_floor_curve.json"
    feed = RWAFeed(fetcher=_FakeFetcher(_pools_payload()), cache_path=tmp_path / "cache.json")
    doc = fc.record_forward_point(curve_path=path, feed=feed, date="2026-06-26")
    assert doc is not None
    assert doc["n_points"] == 1
    # TVL-weighted: (3.5*831M + 3.3*3000M) / 3831M ≈ 3.343%
    assert 3.0 <= doc["latest"]["floor_apy_pct"] <= 3.6
    assert doc["latest"]["n_pools"] == 2
