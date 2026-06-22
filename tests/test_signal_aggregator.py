"""
test_signal_aggregator.py — ADR-031 / MP-1146 analytics integration tests.

Covers: Tier-A OK/BLOCK, Tier-B neutral-on-missing-data, Tier-B multiplier for
low risk, atomic write, fail-open on module timeout, and TTL-cache staleness.

The aggregator runs real registry modules in `run_tier_*`; to keep tests fast
and deterministic we stub the registry's tier lists with synthetic fake modules
whose adapters return controlled scores.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

import pytest

from spa_core.analytics import signal_aggregator as sa


# ─── Fakes ──────────────────────────────────────────────────────────────────

class _FakeAdapter:
    """Stand-in for _ModuleAdapter returning a fixed (score, ok)/timeout."""

    def __init__(self, module_info):
        self._score = module_info.get("_fake_score")
        self._ok = module_info.get("_fake_ok", True)
        self._sleep = module_info.get("_fake_sleep", 0.0)
        self.module_name = module_info.get("module", "fake")
        self.weight = float(module_info.get("weight", 0.5) or 0.5)

    def run(self, protocol, context):
        if self._sleep:
            time.sleep(self._sleep)
        if not self._ok or self._score is None:
            return None, False
        return float(self._score), True


def _fake_modules(tier, scores):
    """Build registry entries with synthetic scores."""
    out = []
    for i, sc in enumerate(scores):
        out.append({
            "module": f"fake_{tier}_{i}",
            "class": None,
            "tier": tier,
            "category": "test",
            "weight": 0.5,
            "protocols": ["all"],
            "_fake_score": sc,
            "_fake_ok": sc is not None,
        })
    return out


@pytest.fixture(autouse=True)
def _patch_adapter(monkeypatch):
    monkeypatch.setattr(sa, "_ModuleAdapter", _FakeAdapter)


# ─── Tier A ───────────────────────────────────────────────────────────────────

def test_tier_a_returns_ok_for_healthy_protocol(monkeypatch, tmp_path):
    monkeypatch.setattr(sa.registry, "get_tier_modules",
                        lambda t: _fake_modules("A", [10.0, 5.0, 20.0]))
    agg = sa.SignalAggregator(data_dir=tmp_path)
    res = agg.run_tier_a(["aave_v3"], {})
    assert res["protocols"]["aave_v3"]["signal"] == "OK"
    assert res["protocols"]["aave_v3"]["score"] <= sa.WARN_THRESHOLD


def test_tier_a_blocks_high_risk_protocol(monkeypatch, tmp_path):
    monkeypatch.setattr(sa.registry, "get_tier_modules",
                        lambda t: _fake_modules("A", [10.0, 88.0, 30.0]))
    agg = sa.SignalAggregator(data_dir=tmp_path)
    res = agg.run_tier_a(["pendle"], {})
    sig = res["protocols"]["pendle"]
    assert sig["signal"] == "BLOCK"
    assert sig["score"] > sa.BLOCK_THRESHOLD
    assert sig["triggered_by"]  # at least one module flagged


def test_tier_a_warns_on_mid_risk(monkeypatch, tmp_path):
    monkeypatch.setattr(sa.registry, "get_tier_modules",
                        lambda t: _fake_modules("A", [55.0]))
    agg = sa.SignalAggregator(data_dir=tmp_path)
    res = agg.run_tier_a(["maple"], {})
    assert res["protocols"]["maple"]["signal"] == "WARN"


# ─── Tier B ───────────────────────────────────────────────────────────────────

def test_tier_b_returns_neutral_on_missing_data(monkeypatch, tmp_path):
    # all modules dormant (no data) → confidence 0 → neutral multiplier 1.0
    monkeypatch.setattr(sa.registry, "get_tier_modules",
                        lambda t: _fake_modules("B", [None, None, None]))
    agg = sa.SignalAggregator(data_dir=tmp_path)
    res = agg.run_tier_b(["aave_v3"], {})
    entry = res["protocols"]["aave_v3"]
    assert entry["confidence"] == 0.0
    assert entry["risk_multiplier"] == pytest.approx(1.0, abs=1e-6)


def test_tier_b_increases_multiplier_for_low_risk(monkeypatch, tmp_path):
    # low risk scores (well below 50) on enough modules to clear MIN_CONFIDENCE
    scores = [10.0] * 10
    monkeypatch.setattr(sa.registry, "get_tier_modules",
                        lambda t: _fake_modules("B", scores))
    agg = sa.SignalAggregator(data_dir=tmp_path)
    res = agg.run_tier_b(["aave_v3"], {})
    entry = res["protocols"]["aave_v3"]
    # low risk → multiplier above neutral (1.0), up to 1.5
    assert entry["risk_multiplier"] > 1.0
    assert entry["risk_multiplier"] <= 1.5
    assert entry["composite_risk_0_100"] < 50.0


def test_tier_b_high_risk_lowers_multiplier(monkeypatch, tmp_path):
    scores = [90.0] * 10
    monkeypatch.setattr(sa.registry, "get_tier_modules",
                        lambda t: _fake_modules("B", scores))
    agg = sa.SignalAggregator(data_dir=tmp_path)
    res = agg.run_tier_b(["pendle"], {})
    entry = res["protocols"]["pendle"]
    assert entry["risk_multiplier"] < 1.0
    assert entry["risk_multiplier"] >= 0.5


# ─── Atomic write ───────────────────────────────────────────────────────────

def test_atomic_write(tmp_path):
    agg = sa.SignalAggregator(data_dir=tmp_path)
    target = tmp_path / "sub" / "out.json"
    payload = {"hello": "world", "n": 42}
    agg._write_atomic(target, payload)
    assert target.exists()
    assert json.loads(target.read_text()) == payload
    # no leftover temp files
    leftovers = list((tmp_path / "sub").glob(".out.json.*.tmp"))
    assert not leftovers


# ─── Fail-open on timeout ─────────────────────────────────────────────────────

def test_module_timeout_is_ignored(monkeypatch, tmp_path):
    # one module sleeps beyond the timeout → must be dropped (fail-open), not crash
    mods = _fake_modules("A", [12.0])
    mods[0]["_fake_sleep"] = 1.0
    monkeypatch.setattr(sa.registry, "get_tier_modules", lambda t: mods)
    agg = sa.SignalAggregator(data_dir=tmp_path, module_timeout=0.05)
    res = agg.run_tier_a(["aave_v3"], {})
    sig = res["protocols"]["aave_v3"]
    # timed-out module dropped → no active signal → OK, score 0
    assert sig["signal"] == "OK"
    assert sig["score"] == 0.0
    # health log recorded a timeout
    statuses = {e["status"] for e in agg._log}
    assert "timeout" in statuses


def test_failed_module_is_ignored(monkeypatch, tmp_path):
    mods = _fake_modules("A", [None])  # dormant / no data
    monkeypatch.setattr(sa.registry, "get_tier_modules", lambda t: mods)
    agg = sa.SignalAggregator(data_dir=tmp_path)
    res = agg.run_tier_a(["aave_v3"], {})
    assert res["protocols"]["aave_v3"]["signal"] == "OK"


# ─── TTL cache ─────────────────────────────────────────────────────────────────

def test_ttl_cache_stale_returns_neutral(monkeypatch, tmp_path):
    # Write a STALE advisory file, then ensure the scoring_engine treats it as
    # neutral (0.5). This mirrors ADR-031's 2h TTL on the consumer side.
    from spa_core.risk import scoring_engine as se
    stale_ts = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat().replace(
        "+00:00", "Z"
    )
    advisory = {
        "_meta": {"timestamp": stale_ts, "tier": "B"},
        "protocols": {"aave_v3": {"risk_multiplier": 1.5, "confidence": 0.9}},
    }
    monkeypatch.setattr(se, "ANALYTICS_ADVISORY_FILE", tmp_path / "adv.json")
    (tmp_path / "adv.json").write_text(json.dumps(advisory))
    eng = se.RiskScoringEngine(offline=True)
    # stale → neutral 0.5 (NOT 1.0 which a fresh mult=1.5 would give)
    assert eng._score_analytics("aave-v3") == pytest.approx(0.5)


def test_fresh_cache_used(tmp_path):
    agg = sa.SignalAggregator(data_dir=tmp_path)
    fresh = {
        "_meta": {"timestamp": sa._utc_now_iso(), "tier": "B"},
        "protocols": {"aave_v3": {"risk_multiplier": 1.2}},
    }
    (tmp_path / sa.ADVISORY_FILE).write_text(json.dumps(fresh))
    # run_tier_b should return the cached payload unchanged (no recompute)
    res = sa.run_tier_b(["aave_v3"], data_dir=tmp_path, use_cache=True)
    assert res["protocols"]["aave_v3"]["risk_multiplier"] == 1.2


def test_scoring_engine_consumes_advisory(monkeypatch, tmp_path):
    from spa_core.risk import scoring_engine as se
    advisory = {
        "_meta": {"timestamp": sa._utc_now_iso(), "tier": "B"},
        "protocols": {"aave_v3": {"risk_multiplier": 1.5, "confidence": 0.9}},
    }
    monkeypatch.setattr(se, "ANALYTICS_ADVISORY_FILE", tmp_path / "adv.json")
    (tmp_path / "adv.json").write_text(json.dumps(advisory))
    eng = se.RiskScoringEngine(offline=True)
    # mult 1.5 (lowest risk) → score 1.0 (safest)
    assert eng._score_analytics("aave-v3") == pytest.approx(1.0)
