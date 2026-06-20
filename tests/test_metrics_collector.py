"""
tests/test_metrics_collector.py
25 unit tests for spa_core/utils/metrics.py (MP-1532 v11.48)
"""
import os
import json
import tempfile
import time

import pytest

from spa_core.utils.metrics import MetricsCollector, get_metrics, reset_global


@pytest.fixture(autouse=True)
def fresh_global():
    """Reset global singleton before each test."""
    reset_global()
    yield
    reset_global()


@pytest.fixture()
def mc():
    """Fresh MetricsCollector using a temp directory."""
    with tempfile.TemporaryDirectory() as tmp:
        yield MetricsCollector(base_dir=tmp)


# ── counters ─────────────────────────────────────────────────────────────────

def test_counter_increment_basic(mc):
    mc.increment("daily_cycle")
    assert mc.get_counter("daily_cycle") == 1


def test_counter_initial_zero(mc):
    assert mc.get_counter("missing_counter") == 0


def test_counter_multi_increment(mc):
    mc.increment("apy_fetch")
    mc.increment("apy_fetch")
    mc.increment("apy_fetch")
    assert mc.get_counter("apy_fetch") == 3


def test_counter_n_param(mc):
    mc.increment("batch", n=5)
    assert mc.get_counter("batch") == 5


def test_counter_accumulates(mc):
    mc.increment("events", n=10)
    mc.increment("events", n=3)
    assert mc.get_counter("events") == 13


def test_counter_with_tags(mc):
    mc.increment("fetch", protocol="aave")
    mc.increment("fetch", protocol="compound")
    mc.increment("fetch", protocol="aave")
    assert mc.get_counter("fetch", protocol="aave") == 2
    assert mc.get_counter("fetch", protocol="compound") == 1


# ── gauges ────────────────────────────────────────────────────────────────────

def test_gauge_set(mc):
    mc.set_gauge("portfolio_value", 100000.0)
    assert mc.get_gauge("portfolio_value") == 100000.0


def test_gauge_overwrite(mc):
    mc.set_gauge("apy", 4.5)
    mc.set_gauge("apy", 6.2)
    assert mc.get_gauge("apy") == 6.2


def test_gauge_none_if_missing(mc):
    assert mc.get_gauge("nonexistent") is None


def test_gauge_with_tags(mc):
    mc.set_gauge("tvl", 5_000_000.0, protocol="morpho")
    mc.set_gauge("tvl", 3_000_000.0, protocol="aave")
    assert mc.get_gauge("tvl", protocol="morpho") == 5_000_000.0
    assert mc.get_gauge("tvl", protocol="aave") == 3_000_000.0


# ── timers ────────────────────────────────────────────────────────────────────

def test_timer_record(mc):
    mc.record_time("cycle_ms", 250.0)
    stats = mc.get_timer_stats("cycle_ms")
    assert stats is not None
    assert stats["count"] == 1


def test_timer_multiple_records(mc):
    for ms in [100.0, 200.0, 300.0]:
        mc.record_time("fetch_ms", ms)
    stats = mc.get_timer_stats("fetch_ms")
    assert stats["count"] == 3


def test_timer_avg(mc):
    mc.record_time("op", 100.0)
    mc.record_time("op", 200.0)
    mc.record_time("op", 300.0)
    stats = mc.get_timer_stats("op")
    assert abs(stats["avg_ms"] - 200.0) < 0.01


def test_timer_p95(mc):
    samples = list(range(100))  # 0..99
    for s in samples:
        mc.record_time("p95_test", float(s))
    stats = mc.get_timer_stats("p95_test")
    # p95 index = int(100 * 0.95) = 95, value = 95.0
    assert stats["p95_ms"] == 95.0


def test_timer_ring_buffer_cap(mc):
    for i in range(1200):
        mc.record_time("bounded", float(i))
    key = MetricsCollector._make_key("bounded", {})
    assert len(mc._timers[key]) == 1000


def test_timer_context_manager(mc):
    with mc.timer("ctx_timer"):
        time.sleep(0.005)
    stats = mc.get_timer_stats("ctx_timer")
    assert stats is not None
    assert stats["count"] == 1
    assert stats["avg_ms"] >= 1.0  # at least 1ms


def test_timer_context_manager_measures_time(mc):
    with mc.timer("sleep_timer"):
        time.sleep(0.02)
    stats = mc.get_timer_stats("sleep_timer")
    # Should be at least 15ms
    assert stats["avg_ms"] >= 10.0


def test_timer_with_tags(mc):
    mc.record_time("fetch_ms", 50.0, protocol="aave")
    mc.record_time("fetch_ms", 80.0, protocol="compound")
    aave_stats = mc.get_timer_stats("fetch_ms", protocol="aave")
    compound_stats = mc.get_timer_stats("fetch_ms", protocol="compound")
    assert aave_stats["avg_ms"] == 50.0
    assert compound_stats["avg_ms"] == 80.0


def test_timer_none_if_missing(mc):
    assert mc.get_timer_stats("never_recorded") is None


# ── key construction ──────────────────────────────────────────────────────────

def test_key_without_tags():
    key = MetricsCollector._make_key("my_metric", {})
    assert key == "my_metric"


def test_key_with_tags_sorted():
    key = MetricsCollector._make_key("m", {"z": "last", "a": "first"})
    assert key == "m{a=first,z=last}"


# ── flush ─────────────────────────────────────────────────────────────────────

def test_flush_returns_dict(mc):
    mc.increment("cycles")
    result = mc.flush()
    assert isinstance(result, dict)


def test_flush_structure(mc):
    mc.increment("c1")
    mc.set_gauge("g1", 1.0)
    mc.record_time("t1", 100.0)
    result = mc.flush()
    assert "counters" in result
    assert "gauges" in result
    assert "timers" in result
    assert "timestamp" in result


def test_flush_to_file(mc):
    mc.increment("daily_cycle", n=3)
    mc.set_gauge("portfolio", 100000.0)
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "data"), exist_ok=True)
        path = os.path.join(tmp, "data", "metrics.json")
        mc.flush(path=path)
        with open(path) as f:
            data = json.load(f)
    assert data["counters"]["daily_cycle"] == 3
    assert data["gauges"]["portfolio"] == 100000.0


def test_flush_timestamp(mc):
    result = mc.flush()
    assert "T" in result["timestamp"]  # ISO 8601


# ── global singleton ──────────────────────────────────────────────────────────

def test_get_metrics_returns_collector():
    m = get_metrics()
    assert isinstance(m, MetricsCollector)


def test_get_metrics_singleton():
    m1 = get_metrics()
    m2 = get_metrics()
    assert m1 is m2


def test_reset(mc):
    mc.increment("x", n=5)
    mc.set_gauge("y", 10.0)
    mc.record_time("z", 100.0)
    mc.reset()
    assert mc.get_counter("x") == 0
    assert mc.get_gauge("y") is None
    assert mc.get_timer_stats("z") is None
