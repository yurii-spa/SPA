"""Tests for spa_core.monitoring.system_health_monitor.

Network and subprocess are monkeypatched — no real egress / no real kill-switch.
Covers: each domain, the severity matrix, the skip-graph, fingerprint dedup,
APY/tier normalization, JSON output compliance, and the always-exit-0 guarantee.
"""
from __future__ import annotations

import json
import subprocess
from datetime import date, timedelta, datetime, timezone
from pathlib import Path

import pytest

from spa_core.monitoring import system_health_monitor as shm
from spa_core.monitoring.system_health_monitor import (
    SystemHealthMonitor, CheckResult,
    CRITICAL, WARNING, INFO, OK, SKIPPED,
    _normalize_apy, _normalize_tier, _worst, _is_finite_number,
)


# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------
def _dates(n: int):
    today = date.today()
    return [(today - timedelta(days=n - 1 - i)).isoformat() for i in range(n)]


def _good_equity(n: int = 12):
    daily = []
    eq = 100_000.0
    for i, d in enumerate(_dates(n)):
        eq += 12.0
        daily.append({"date": d, "close_equity": round(eq, 2),
                      "daily_return_pct": 0.012})
    return {
        "is_demo": False,
        "summary": {"num_days": n, "end_equity": daily[-1]["close_equity"]},
        "daily": daily,
    }


def _good_adapter():
    return {
        "adapters": {
            "aave_v3": {"apy": 3.11, "live_apy": 3.11, "fallback_apy": 3.5, "tier": 1},
            "compound_v3": {"apy": 3.27, "live_apy": 3.27, "fallback_apy": 5.2, "tier": 1},
            "morpho_steakhouse": {"apy": 4.6, "tier": "T1"},
            "aave_arbitrum": {"apy": 4.6, "tier": 1},
            "spark_susds": {"apy": 3.45, "tier": 1},
            "aave_v3_optimism": {"apy": 4.0, "tier": 1},
            "aave_v3_polygon": {"apy": 4.0, "tier": 1},
            "yearn_v3": {"apy": 4.9, "tier": 2},
            "euler_v2": {"apy": 5.0, "tier": 2},
        }
    }


def _good_tournament():
    return {
        "is_demo": False,
        "winner": {"strategy_id": "S20", "name": "X", "paper_apy": 18.5},
        "ranked_strategies": [
            {"strategy_id": "S1", "paper_apy": 3.5},
            {"strategy_id": "S2", "paper_apy": 5.0},
            {"strategy_id": "S20", "paper_apy": 18.5},
        ],
    }


def _good_status():
    ts = datetime.now(timezone.utc).isoformat()
    return {"is_demo": False, "current_equity": 100_120.0, "last_cycle_ts": ts,
            "days_running": 12}


def _good_golive():
    return {"ready": False, "passed": 27, "total": 29, "checks": {}, "criteria": []}


def _good_positions():
    return {
        "is_demo": False,
        "positions": {
            "aave_v3": 20_000.0, "compound_v3": 20_000.0, "yearn_v3": 15_000.0,
            "euler_v2": 15_000.0, "morpho_steakhouse": 15_000.0, "spark_susds": 15_000.0,
        },
    }


def _good_red_flags():
    return {"red_flags": [{"protocol": "x", "severity": "WARN", "message": "minor"}],
            "summary": {}}


def _write(d: Path, name: str, obj):
    (d / name).write_text(json.dumps(obj), encoding="utf-8")


@pytest.fixture
def good_dir(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    _write(data, "equity_curve_daily.json", _good_equity())
    _write(data, "adapter_status.json", _good_adapter())
    _write(data, "paper_trading_status.json", _good_status())
    _write(data, "golive_status.json", _good_golive())
    _write(data, "current_positions.json", _good_positions())
    _write(data, "red_flags.json", _good_red_flags())
    _write(data, "strategy_tournament.json", _good_tournament())
    # Healthy SQLite track mirror so d1.track_db.mirror passes (a real cycle
    # writes this; without it the mirror check correctly flags a 0-byte db).
    _write(data, "trades.json", [{"trade_id": "T001", "ts": "2026-06-10T00:00:00+00:00",
                                   "diff_usd": 1.0, "is_demo": False}])
    from spa_core.persistence.track_store import TrackStore
    TrackStore(db_path=data / "track.db").sync_from_json(data)
    return tmp_path


def make_mon(root: Path) -> SystemHealthMonitor:
    mon = SystemHealthMonitor(data_dir=str(root / "data"), project_root=str(root))
    return mon


def by_id(results, cid):
    for r in results:
        if r.id == cid:
            return r
    return None


def prelude(mon):
    mon._prev_cache = None
    mon._prelude()


# ---------------------------------------------------------------------------
# Helpers / normalization (unit)
# ---------------------------------------------------------------------------
def test_worst_ignores_skipped():
    assert _worst([OK, SKIPPED, WARNING]) == WARNING
    assert _worst([SKIPPED]) == OK
    assert _worst([OK, INFO, CRITICAL, WARNING]) == CRITICAL


def test_is_finite_number():
    assert _is_finite_number(3.2)
    assert not _is_finite_number(float("nan"))
    assert not _is_finite_number(float("inf"))
    assert not _is_finite_number(True)
    assert not _is_finite_number("3")


def test_normalize_tier_int_and_string_equivalent():
    assert _normalize_tier(1)[0] == "T1"
    assert _normalize_tier("1")[0] == "T1"
    assert _normalize_tier("T1")[0] == "T1"
    assert _normalize_tier(2)[0] == "T2"
    assert _normalize_tier("T2")[0] == "T2"


def test_normalize_tier_unknown_defaults_t2_flagged():
    tier, unknown = _normalize_tier("T3")
    assert tier == "T2" and unknown is True


def test_normalize_apy_percent_passthrough():
    assert _normalize_apy(3.11) == pytest.approx(3.11)
    assert _normalize_apy(18.4) == pytest.approx(18.4)


def test_normalize_apy_decimal_with_sibling_scaled():
    # 0.03 decimal + sibling 3.5 (~x100) -> 3.0 percent
    assert _normalize_apy(0.03, [3.5, 5.0]) == pytest.approx(3.0)


def test_normalize_apy_decimal_without_sibling_scaled():
    assert _normalize_apy(0.04, []) == pytest.approx(4.0)


def test_normalize_apy_zero_and_none():
    assert _normalize_apy(0.0) == 0.0          # not treated as decimal
    assert _normalize_apy(None) is None
    assert _normalize_apy(float("nan")) is None


# ---------------------------------------------------------------------------
# DOMAIN 1 — Data Pipeline
# ---------------------------------------------------------------------------
def test_d1_all_good(good_dir):
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d1_data_pipeline()
    assert by_id(res, "d1.equity.exists").status == OK
    assert by_id(res, "d1.equity.range").status == OK
    assert by_id(res, "d1.status.demo").status == OK
    assert by_id(res, "d1.adapter.present").status == OK
    # Healthy SQLite mirror present → mirror check passes.
    assert by_id(res, "d1.track_db.mirror").status == OK


def test_d1_track_db_zero_bytes_is_critical(good_dir):
    """A 0-byte track.db (the historical silent bug) now surfaces as CRITICAL
    in monitoring instead of hiding behind the cycle's status:ok."""
    (good_dir / "data" / "track.db").write_bytes(b"")
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d1_data_pipeline()
    chk = by_id(res, "d1.track_db.mirror")
    assert chk.status == CRITICAL
    assert "0 bytes" in chk.title


def test_d1_track_db_persist_flag_false_is_critical(good_dir):
    """The cycle-written track_persist_status.json flag is honoured: a
    track_persist_ok:false flag → CRITICAL with the recorded reason."""
    import json as _json
    (good_dir / "data" / "track_persist_status.json").write_text(
        _json.dumps({"track_persist_ok": False, "reason": "sqlite open/query failed",
                     "db_size_bytes": 0}),
        encoding="utf-8",
    )
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d1_data_pipeline()
    chk = by_id(res, "d1.track_db.mirror")
    assert chk.status == CRITICAL
    assert "sqlite open/query failed" in chk.title


def test_d1_equity_missing_is_critical_and_skips_dependents(good_dir):
    (good_dir / "data" / "equity_curve_daily.json").unlink()
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d1_data_pipeline()
    assert by_id(res, "d1.equity.exists").status == CRITICAL
    for cid in ("d1.equity.count", "d1.equity.range", "d1.equity.nan", "d1.equity.dates"):
        assert by_id(res, cid).status == SKIPPED
        assert by_id(res, cid).skipped_reason


def test_d1_equity_range_breach_critical(good_dir):
    eq = _good_equity()
    eq["daily"][-1]["close_equity"] = 50_000.0      # capital corruption
    _write(good_dir / "data", "equity_curve_daily.json", eq)
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d1_data_pipeline()
    assert by_id(res, "d1.equity.range").status == CRITICAL


def test_d1_equity_high_breach_critical(good_dir):
    eq = _good_equity()
    eq["daily"][3]["close_equity"] = 200_000.0
    _write(good_dir / "data", "equity_curve_daily.json", eq)
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d1_data_pipeline()
    assert by_id(res, "d1.equity.range").status == CRITICAL


def test_d1_equity_nan_critical(good_dir):
    eq = _good_equity()
    eq["daily"][2]["close_equity"] = float("inf")
    # json can't store inf cleanly; write manually
    p = good_dir / "data" / "equity_curve_daily.json"
    p.write_text(json.dumps(eq).replace("Infinity", "1e999"), encoding="utf-8")
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d1_data_pipeline()
    assert by_id(res, "d1.equity.nan").status == CRITICAL


def test_d1_equity_count_low_warns(good_dir):
    eq = _good_equity(n=2)
    eq["summary"]["num_days"] = 2
    _write(good_dir / "data", "equity_curve_daily.json", eq)
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d1_data_pipeline()
    assert by_id(res, "d1.equity.count").status == WARNING


def test_d1_equity_date_gap_warns(good_dir):
    eq = _good_equity()
    eq["daily"][5]["date"] = (date.today() - timedelta(days=30)).isoformat()
    _write(good_dir / "data", "equity_curve_daily.json", eq)
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d1_data_pipeline()
    assert by_id(res, "d1.equity.dates").status == WARNING


def test_d1_adapter_missing_t1_critical(good_dir):
    ad = _good_adapter()
    del ad["adapters"]["aave_v3"]
    _write(good_dir / "data", "adapter_status.json", ad)
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d1_data_pipeline()
    assert by_id(res, "d1.adapter.present").status == CRITICAL


def test_d1_adapter_file_missing_warns_and_skips(good_dir):
    (good_dir / "data" / "adapter_status.json").unlink()
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d1_data_pipeline()
    assert by_id(res, "d1.adapter.present").status == WARNING
    assert by_id(res, "d1.adapter.apy_range").status == SKIPPED
    assert by_id(res, "d1.adapter.apy_none").status == SKIPPED


def test_d1_adapter_apy_out_of_range_warns(good_dir):
    ad = _good_adapter()
    ad["adapters"]["euler_v2"]["apy"] = 99.0
    _write(good_dir / "data", "adapter_status.json", ad)
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d1_data_pipeline()
    assert by_id(res, "d1.adapter.apy_range").status == WARNING


def test_d1_adapter_apy_none_single_warning(good_dir):
    ad = _good_adapter()
    ad["adapters"]["euler_v2"]["apy"] = None
    _write(good_dir / "data", "adapter_status.json", ad)
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d1_data_pipeline()
    assert by_id(res, "d1.adapter.apy_none").status == WARNING


def test_d1_adapter_apy_none_triple_critical(good_dir):
    ad = _good_adapter()
    for k in ("euler_v2", "yearn_v3", "spark_susds"):
        ad["adapters"][k]["apy"] = None
    _write(good_dir / "data", "adapter_status.json", ad)
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d1_data_pipeline()
    assert by_id(res, "d1.adapter.apy_none").status == CRITICAL


def test_d1_tournament_demo_critical(good_dir):
    t = _good_tournament()
    t["is_demo"] = True
    _write(good_dir / "data", "strategy_tournament.json", t)
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d1_data_pipeline()
    assert by_id(res, "d1.tournament.demo").status == CRITICAL


def test_d1_tournament_empty_warns(good_dir):
    t = {"is_demo": False, "winner": None, "ranked_strategies": []}
    _write(good_dir / "data", "strategy_tournament.json", t)
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d1_data_pipeline()
    assert by_id(res, "d1.tournament.populated").status == WARNING


def test_d1_tournament_fallback_file(good_dir):
    (good_dir / "data" / "strategy_tournament.json").unlink()
    _write(good_dir / "data", "tournament_results.json",
           {"is_demo": False, "winner": {"strategy_id": "S1"},
            "strategies": [{"strategy_id": "S1", "apy": 3.0},
                           {"strategy_id": "S2", "apy": 4.0}]})
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d1_data_pipeline()
    assert by_id(res, "d1.tournament.demo").status == OK


def test_d1_status_demo_critical(good_dir):
    s = _good_status()
    s["is_demo"] = True
    _write(good_dir / "data", "paper_trading_status.json", s)
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d1_data_pipeline()
    assert by_id(res, "d1.status.demo").status == CRITICAL


def test_d1_status_equity_breach_critical(good_dir):
    s = _good_status()
    s["current_equity"] = 5.0
    _write(good_dir / "data", "paper_trading_status.json", s)
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d1_data_pipeline()
    assert by_id(res, "d1.status.equity").status == CRITICAL


def test_d1_status_stale_warns(good_dir):
    s = _good_status()
    s["last_cycle_ts"] = (datetime.now(timezone.utc) - timedelta(hours=40)).isoformat()
    _write(good_dir / "data", "paper_trading_status.json", s)
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d1_data_pipeline()
    assert by_id(res, "d1.status.fresh").status == WARNING


def test_d1_status_missing_is_critical(good_dir):
    (good_dir / "data" / "paper_trading_status.json").unlink()
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d1_data_pipeline()
    assert by_id(res, "d1.status.demo").status == CRITICAL


def test_d1_golive_all_pass_info(good_dir):
    g = _good_golive()
    g["passed"] = 29
    g["total"] = 29
    _write(good_dir / "data", "golive_status.json", g)
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d1_data_pipeline()
    assert by_id(res, "d1.golive.count").status == INFO


# ---------------------------------------------------------------------------
# DOMAIN 3 — Strategy Quality
# ---------------------------------------------------------------------------
def test_d3_cycle_ran_today_ok(good_dir):
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d3_strategy_quality()
    assert by_id(res, "d3.cycle.ran_today").status == OK


def test_d3_cycle_stale_2d_critical(good_dir):
    eq = _good_equity()
    for i, b in enumerate(eq["daily"]):
        b["date"] = (date.today() - timedelta(days=len(eq["daily"]) + 2 - i)).isoformat()
    _write(good_dir / "data", "equity_curve_daily.json", eq)
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d3_strategy_quality()
    assert by_id(res, "d3.cycle.ran_today").status == CRITICAL


def test_d3_cycle_stale_1d_warning(good_dir):
    eq = _good_equity()
    for i, b in enumerate(eq["daily"]):
        b["date"] = (date.today() - timedelta(days=len(eq["daily"]) - i)).isoformat()
    _write(good_dir / "data", "equity_curve_daily.json", eq)
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d3_strategy_quality()
    assert by_id(res, "d3.cycle.ran_today").status == WARNING


def test_d3_skips_when_equity_missing(good_dir):
    (good_dir / "data" / "equity_curve_daily.json").unlink()
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d3_strategy_quality()
    assert by_id(res, "d3.cycle.ran_today").status == SKIPPED
    assert by_id(res, "d3.equity.trend7").status == SKIPPED


def test_d3_tournament_not_differentiated_warns(good_dir):
    t = _good_tournament()
    for s in t["ranked_strategies"]:
        s["paper_apy"] = 4.0
    _write(good_dir / "data", "strategy_tournament.json", t)
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d3_strategy_quality()
    assert by_id(res, "d3.tournament.differentiated").status == WARNING


def test_d3_alloc_cap_over_warns(good_dir):
    pos = _good_positions()
    pos["positions"] = {"aave_v3": 90_000.0, "compound_v3": 10_000.0}
    _write(good_dir / "data", "current_positions.json", pos)
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d3_strategy_quality()
    assert by_id(res, "d3.alloc.cap").status == WARNING


def test_d3_alloc_cap_ok(good_dir):
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d3_strategy_quality()
    assert by_id(res, "d3.alloc.cap").status == OK


def test_d3_trend7_declining_warns(good_dir):
    eq = _good_equity(n=10)
    base = 100_000.0
    for i, b in enumerate(eq["daily"]):
        b["close_equity"] = round(base - i * 200, 2)        # declining
    _write(good_dir / "data", "equity_curve_daily.json", eq)
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d3_strategy_quality()
    assert by_id(res, "d3.equity.trend7").status == WARNING


# ---------------------------------------------------------------------------
# DOMAIN 2 — Connectivity (network mocked)
# ---------------------------------------------------------------------------
def _fake_pools_payload():
    return json.dumps({"data": [
        {"project": "aave-v3", "symbol": "USDC", "apy": 3.2},
        {"project": "compound-v3", "symbol": "USDC", "apy": 3.3},
    ]}).encode()


def test_d2_reach_ok_and_deviation_ok(good_dir, monkeypatch):
    def fake_http(url, timeout=10, want_headers=False):
        return 200, _fake_pools_payload(), {}
    monkeypatch.setattr(shm, "_http_get", fake_http)
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d2_connectivity()
    assert by_id(res, "d2.defillama.reach").status == OK
    assert by_id(res, "d2.defillama.deviation").status == OK


def test_d2_unreachable_warns_and_skips_deviation(good_dir, monkeypatch):
    def fake_http(url, timeout=10, want_headers=False):
        raise OSError("boom")
    monkeypatch.setattr(shm, "_http_get", fake_http)
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d2_connectivity()
    assert by_id(res, "d2.defillama.reach").status == WARNING
    assert by_id(res, "d2.defillama.deviation").status == SKIPPED


def test_d2_deviation_warns_when_far(good_dir, monkeypatch):
    def fake_http(url, timeout=10, want_headers=False):
        payload = json.dumps({"data": [
            {"project": "aave-v3", "symbol": "USDC", "apy": 12.0},   # vs stored 3.11
            {"project": "compound-v3", "symbol": "USDC", "apy": 3.3},
        ]}).encode()
        return 200, payload, {}
    monkeypatch.setattr(shm, "_http_get", fake_http)
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d2_connectivity()
    assert by_id(res, "d2.defillama.deviation").status == WARNING


def test_d2_gzip_decompressed(good_dir, monkeypatch):
    import gzip as _gz
    packed = _gz.compress(_fake_pools_payload())

    def fake_urlopen(req, timeout=10):
        class R:
            status = 200
            headers = {}
            def read(self_inner):
                return packed
            def __enter__(self_inner):
                return self_inner
            def __exit__(self_inner, *a):
                return False
        return R()
    monkeypatch.setattr(shm.urllib.request, "urlopen", fake_urlopen)
    # use the real _http_get to exercise gzip sniffing
    status, body, _ = shm._http_get(shm.DEFILLAMA_POOLS)
    assert status == 200
    assert b"aave-v3" in body


# ---------------------------------------------------------------------------
# DOMAIN 4 — External services (network mocked)
# ---------------------------------------------------------------------------
def test_d4_all_ok(good_dir, monkeypatch):
    def fake_http(url, timeout=10, want_headers=False, extra_headers=None):
        if want_headers:
            return 200, b"{}", {"x-ratelimit-remaining": "4000", "x-ratelimit-limit": "5000"}
        return 200, b"ok", {}
    monkeypatch.setattr(shm, "_http_get", fake_http)
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d4_external()
    assert {r.id for r in res} == {"d4.earndefi", "d4.github_raw", "d4.github_rate", "d4.local_api"}
    assert all(r.status == OK for r in res)


def test_d4_independent_failures_isolated(good_dir, monkeypatch):
    def fake_http(url, timeout=10, want_headers=False, extra_headers=None):
        if "earn-defi" in url:
            raise OSError("down")
        if want_headers:
            return 200, b"{}", {"x-ratelimit-remaining": "4000", "x-ratelimit-limit": "5000"}
        return 200, b"ok", {}
    monkeypatch.setattr(shm, "_http_get", fake_http)
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d4_external()
    assert by_id(res, "d4.earndefi").status == WARNING
    assert by_id(res, "d4.github_raw").status == OK   # not masked by the down one


def test_d4_github_rate_low_warns(good_dir, monkeypatch):
    # Authenticated (5000 ceiling) but remaining genuinely exhausted -> WARNING.
    import spa_core.utils.keychain as _kc
    monkeypatch.setattr(_kc, "get_github_pat", lambda: "ghp_fake")

    def fake_http(url, timeout=10, want_headers=False, extra_headers=None):
        if want_headers:
            return 200, b"{}", {"x-ratelimit-remaining": "10", "x-ratelimit-limit": "5000"}
        return 200, b"ok", {}
    monkeypatch.setattr(shm, "_http_get", fake_http)
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d4_external()
    assert by_id(res, "d4.github_rate").status == WARNING


def test_d4_github_rate_unauthenticated_advisory(good_dir, monkeypatch):
    # No PAT (CI/sandbox): anonymous 60-ceiling is below the 100 floor by design,
    # so a "low" reading there is advisory (INFO), not a system WARNING.
    import spa_core.utils.keychain as _kc
    monkeypatch.setattr(_kc, "get_github_pat", lambda: None)

    def fake_http(url, timeout=10, want_headers=False, extra_headers=None):
        if want_headers:
            return 200, b"{}", {"x-ratelimit-remaining": "57", "x-ratelimit-limit": "60"}
        return 200, b"ok", {}
    monkeypatch.setattr(shm, "_http_get", fake_http)
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d4_external()
    assert by_id(res, "d4.github_rate").status == INFO


# ---------------------------------------------------------------------------
# DOMAIN 5 — Code Integrity (subprocess mocked)
# ---------------------------------------------------------------------------
def test_d5_imports_ok(good_dir, monkeypatch):
    mon = make_mon(good_dir)
    monkeypatch.setattr(mon, "_run_import", lambda code: (True, ""))
    prelude(mon)
    res = mon.check_d5_code_integrity()
    assert by_id(res, "d5.import.adapters").status == OK
    assert by_id(res, "d5.import.cycle_runner").status == OK


def test_d5_adapter_import_fail_critical(good_dir, monkeypatch):
    mon = make_mon(good_dir)
    def fake(code):
        return (False, "SyntaxError") if "importlib" in code else (True, "")
    monkeypatch.setattr(mon, "_run_import", fake)
    prelude(mon)
    res = mon.check_d5_code_integrity()
    assert by_id(res, "d5.import.adapters").status == CRITICAL
    assert by_id(res, "d5.import.cycle_runner").status == OK


def test_d5_cycle_runner_import_fail_critical(good_dir, monkeypatch):
    mon = make_mon(good_dir)
    def fake(code):
        return (False, "ImportError") if "cycle_runner" in code else (True, "")
    monkeypatch.setattr(mon, "_run_import", fake)
    prelude(mon)
    res = mon.check_d5_code_integrity()
    assert by_id(res, "d5.import.cycle_runner").status == CRITICAL


def test_d5_secrets_clean(good_dir, monkeypatch):
    mon = make_mon(good_dir)
    monkeypatch.setattr(mon, "_run_import", lambda code: (True, ""))
    prelude(mon)
    mon._git_untracked = ["data/foo.json", "README.md"]
    res = mon.check_d5_code_integrity()
    assert by_id(res, "d5.security.secrets").status == OK


def test_d5_secrets_detected_critical(good_dir, monkeypatch):
    mon = make_mon(good_dir)
    monkeypatch.setattr(mon, "_run_import", lambda code: (True, ""))
    prelude(mon)
    mon._git_untracked = ["scripts/cf_install_token.command", "data/ok.json"]
    res = mon.check_d5_code_integrity()
    r = by_id(res, "d5.security.secrets")
    assert r.status == CRITICAL
    assert any("cf_install_token.command" in p for p in r.evidence["paths"])


def test_d5_secrets_lock_excluded(good_dir, monkeypatch):
    mon = make_mon(good_dir)
    monkeypatch.setattr(mon, "_run_import", lambda code: (True, ""))
    prelude(mon)
    mon._git_untracked = ["package-lock.json", "poetry-secret.lock"]
    res = mon.check_d5_code_integrity()
    assert by_id(res, "d5.security.secrets").status == OK


# ---------------------------------------------------------------------------
# DOMAIN 6 — Risk Gates
# ---------------------------------------------------------------------------
def _patch_killswitch(mon, monkeypatch, triggered=False):
    cr = CheckResult("d6.killswitch", "d6_risk_gates",
                     CRITICAL if triggered else OK, "ks")
    monkeypatch.setattr(mon, "_check_killswitch", lambda D: cr)


def test_d6_t2_cap_ok(good_dir, monkeypatch):
    mon = make_mon(good_dir)
    prelude(mon)
    _patch_killswitch(mon, monkeypatch)
    res = mon.check_d6_risk_gates()
    assert by_id(res, "d6.t2.cap").status == OK


def test_d6_t2_cap_breach_critical(good_dir, monkeypatch):
    # Make T2 dominate: yearn_v3 + euler_v2 are T2
    pos = _good_positions()
    pos["positions"] = {"yearn_v3": 60_000.0, "euler_v2": 20_000.0, "aave_v3": 20_000.0}
    _write(good_dir / "data", "current_positions.json", pos)
    mon = make_mon(good_dir)
    prelude(mon)
    _patch_killswitch(mon, monkeypatch)
    res = mon.check_d6_risk_gates()
    assert by_id(res, "d6.t2.cap").status == CRITICAL


def test_d6_t2_cap_skipped_when_adapter_missing(good_dir, monkeypatch):
    (good_dir / "data" / "adapter_status.json").unlink()
    mon = make_mon(good_dir)
    prelude(mon)
    _patch_killswitch(mon, monkeypatch)
    res = mon.check_d6_risk_gates()
    assert by_id(res, "d6.t2.cap").status == SKIPPED


def test_d6_health_missing_is_warning_not_critical(good_dir, monkeypatch):
    mon = make_mon(good_dir)
    prelude(mon)
    _patch_killswitch(mon, monkeypatch)
    res = mon.check_d6_risk_gates()
    assert by_id(res, "d6.health").status == WARNING


def test_d6_health_low_critical(good_dir, monkeypatch):
    _write(good_dir / "data", "portfolio_health.json", {"score": 42})
    mon = make_mon(good_dir)
    prelude(mon)
    _patch_killswitch(mon, monkeypatch)
    res = mon.check_d6_risk_gates()
    assert by_id(res, "d6.health").status == CRITICAL


def test_d6_health_good_ok(good_dir, monkeypatch):
    _write(good_dir / "data", "portfolio_health.json", {"score": 88})
    mon = make_mon(good_dir)
    prelude(mon)
    _patch_killswitch(mon, monkeypatch)
    res = mon.check_d6_risk_gates()
    assert by_id(res, "d6.health").status == OK


def test_d6_red_flags_critical(good_dir, monkeypatch):
    # Held-protocol contract (2026-06-23): a CRITICAL flag on a HELD protocol
    # (aave_v3 is in _good_positions) drives d6 CRITICAL.
    _write(good_dir / "data", "red_flags.json",
           {"red_flags": [{"protocol": "aave_v3", "severity": "CRITICAL", "message": "boom"}]})
    mon = make_mon(good_dir)
    prelude(mon)
    _patch_killswitch(mon, monkeypatch)
    res = mon.check_d6_risk_gates()
    assert by_id(res, "d6.red_flags").status == CRITICAL


def test_d6_red_flags_external_advisory(good_dir, monkeypatch):
    # A CRITICAL flag on a NON-held (external) protocol is market intel → advisory
    # INFO, not a risk-gate WARNING. It must NOT escalate the d6 domain: external
    # red flags are not a defect of SPA's risk gates (held flags are the real signal).
    _write(good_dir / "data", "red_flags.json",
           {"red_flags": [{"protocol": "some_external_proto", "severity": "CRITICAL",
                           "message": "boom"}]})
    mon = make_mon(good_dir)
    prelude(mon)
    _patch_killswitch(mon, monkeypatch)
    res = mon.check_d6_risk_gates()
    # The red-flags sub-check itself is advisory INFO (rank 1 < WARNING rank 2), so
    # it cannot escalate the d6 domain — only the held-protocol path (above) can.
    assert by_id(res, "d6.red_flags").status == INFO


def test_d6_red_flags_unreadable_warns(good_dir, monkeypatch):
    (good_dir / "data" / "red_flags.json").unlink()
    mon = make_mon(good_dir)
    prelude(mon)
    _patch_killswitch(mon, monkeypatch)
    res = mon.check_d6_risk_gates()
    assert by_id(res, "d6.red_flags").status == WARNING


def test_d6_killswitch_dry_probe_ok(good_dir, monkeypatch):
    mon = make_mon(good_dir)
    prelude(mon)

    class FakeProc:
        returncode = 0
        stdout = "KS False 'all triggers clear'\n"
        stderr = ""
    monkeypatch.setattr(shm.subprocess, "run", lambda *a, **k: FakeProc())
    r = mon._check_killswitch("d6_risk_gates")
    assert r.status == OK


def test_d6_killswitch_triggered_critical(good_dir, monkeypatch):
    mon = make_mon(good_dir)
    prelude(mon)

    class FakeProc:
        returncode = 0
        stdout = "KS True 'drawdown'\n"
        stderr = ""
    monkeypatch.setattr(shm.subprocess, "run", lambda *a, **k: FakeProc())
    r = mon._check_killswitch("d6_risk_gates")
    assert r.status == CRITICAL


def test_d6_killswitch_error_critical(good_dir, monkeypatch):
    mon = make_mon(good_dir)
    prelude(mon)

    class FakeProc:
        returncode = 1
        stdout = ""
        stderr = "Traceback"
    monkeypatch.setattr(shm.subprocess, "run", lambda *a, **k: FakeProc())
    r = mon._check_killswitch("d6_risk_gates")
    assert r.status == CRITICAL


def test_d6_sub_gate_exception_is_isolated(good_dir, monkeypatch):
    # Per-gate isolation (architect N11): a transient error in ONE sub-gate
    # (e.g. a data/*.json rewritten under us by a live agent) must report a
    # per-check WARNING for THAT gate only — it MUST NOT abort the whole d6
    # domain and blank the other gates' verdicts.
    mon = make_mon(good_dir)
    prelude(mon)
    _patch_killswitch(mon, monkeypatch)

    def boom(D):
        raise RuntimeError("transient state rewrite under us")
    monkeypatch.setattr(mon, "_check_t2_cap", boom)

    res = mon.check_d6_risk_gates()
    # The failing gate degrades to a per-check WARNING (not an aborted domain)...
    t2 = by_id(res, "d6.t2.cap")
    assert t2.status == WARNING
    assert t2.error and "RuntimeError" in t2.error
    # ...and the OTHER gates still ran and reported their own verdicts.
    assert by_id(res, "d6.health") is not None
    assert by_id(res, "d6.red_flags") is not None
    assert by_id(res, "d6.killswitch").status == OK
    assert len(res) == 4


# ---------------------------------------------------------------------------
# DOMAIN 7 — Hygiene
# ---------------------------------------------------------------------------
def test_d7_kanban_stale_warns(good_dir):
    old = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
    (good_dir / "KANBAN.json").write_text(json.dumps({
        "columns": {"in_progress": [{"id": "MP-1", "moved_to_in_progress": old}]}
    }), encoding="utf-8")
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d7_hygiene()
    assert by_id(res, "d7.kanban.stale").status == WARNING


def test_d7_kanban_fresh_ok(good_dir):
    recent = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    (good_dir / "KANBAN.json").write_text(json.dumps({
        "columns": {"in_progress": [{"id": "MP-2", "moved_to_in_progress": recent}]}
    }), encoding="utf-8")
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d7_hygiene()
    assert by_id(res, "d7.kanban.stale").status == OK


def test_d7_clutter_info(good_dir):
    mon = make_mon(good_dir)
    prelude(mon)
    res = mon.check_d7_hygiene()
    assert by_id(res, "d7.scripts.clutter").status in (OK, INFO)


# ---------------------------------------------------------------------------
# Fingerprint / dedup
# ---------------------------------------------------------------------------
def test_fingerprint_stable_for_same_checks(good_dir):
    mon = make_mon(good_dir)
    checks = [CheckResult("a", "d", CRITICAL), CheckResult("b", "d", WARNING),
              CheckResult("c", "d", OK)]
    fp1 = mon._fingerprint(checks)
    fp2 = mon._fingerprint(list(reversed(checks)))
    assert fp1 == fp2 and len(fp1) == 8


def test_fingerprint_changes_on_new_critical(good_dir):
    mon = make_mon(good_dir)
    base = [CheckResult("a", "d", WARNING)]
    plus = base + [CheckResult("b", "d", CRITICAL)]
    assert mon._fingerprint(base) != mon._fingerprint(plus)


def test_new_critical_dedup_same_set(good_dir):
    mon = make_mon(good_dir)
    report = {"checks": [{"id": "x", "status": CRITICAL}]}
    prev = {"checks": [{"id": "x", "status": CRITICAL}]}
    assert mon._new_critical(report, prev) is False


def test_new_critical_fires_on_new_id(good_dir):
    mon = make_mon(good_dir)
    report = {"checks": [{"id": "x", "status": CRITICAL}, {"id": "y", "status": CRITICAL}]}
    prev = {"checks": [{"id": "x", "status": CRITICAL}]}
    assert mon._new_critical(report, prev) is True


def test_new_critical_fires_on_clear_then_return(good_dir):
    mon = make_mon(good_dir)
    report = {"checks": [{"id": "x", "status": CRITICAL}]}
    prev = {"checks": [{"id": "x", "status": OK}]}
    assert mon._new_critical(report, prev) is True


def test_new_critical_false_when_no_critical(good_dir):
    mon = make_mon(good_dir)
    report = {"checks": [{"id": "x", "status": WARNING}]}
    assert mon._new_critical(report, None) is False


# ---------------------------------------------------------------------------
# collect() / run() integration (network + subprocess fully mocked)
# ---------------------------------------------------------------------------
def _patch_all_io(mon_module, monkeypatch):
    def fake_http(url, timeout=10, want_headers=False):
        if want_headers:
            return 200, b"{}", {"x-ratelimit-remaining": "5000"}
        return 200, _fake_pools_payload(), {}
    monkeypatch.setattr(mon_module, "_http_get", fake_http)

    real_run = subprocess.run

    def fake_run(args, **kw):
        class P:
            returncode = 0
            stdout = ""
            stderr = ""
        p = P()
        joined = " ".join(args) if isinstance(args, list) else str(args)
        if "kill_switch" in joined or (isinstance(args, list) and "-c" in args and "KillSwitch" in joined):
            p.stdout = "KS False 'all triggers clear'\n"
        elif "git" in joined:
            p.stdout = ""
        else:
            p.stdout = "OK\n"
        # handle the -c code passed as element
        if isinstance(args, list) and len(args) >= 3 and args[1] == "-c":
            code = args[2]
            if "KillSwitchChecker" in code:
                p.stdout = "KS False 'all triggers clear'\n"
            else:
                p.stdout = "OK\n"
        return p
    monkeypatch.setattr(mon_module.subprocess, "run", fake_run)


def test_collect_returns_full_schema(good_dir, monkeypatch):
    _patch_all_io(shm, monkeypatch)
    mon = make_mon(good_dir)
    report = mon.collect()
    for key in ("schema_version", "generated_at", "run_id", "overall_status",
                "fingerprint", "counts", "domains", "checks", "trend", "history"):
        assert key in report
    assert set(report["domains"]) == {
        "d1_data_pipeline", "d2_connectivity", "d3_strategy_quality",
        "d4_external", "d5_code_integrity", "d6_risk_gates", "d7_hygiene"}
    # checks sorted by id
    ids = [c["id"] for c in report["checks"]]
    assert ids == sorted(ids)


def test_collect_good_dir_is_ok_or_info(good_dir, monkeypatch):
    _patch_all_io(shm, monkeypatch)
    # no CRITICAL red flags, health good
    _write(good_dir / "data", "portfolio_health.json", {"score": 90})
    mon = make_mon(good_dir)
    report = mon.collect()
    assert report["overall_status"] in (OK, INFO, WARNING)
    assert report["counts"][CRITICAL] == 0


def test_collect_skipgraph_no_critical_spam(good_dir, monkeypatch):
    _patch_all_io(shm, monkeypatch)
    (good_dir / "data" / "equity_curve_daily.json").unlink()
    mon = make_mon(good_dir)
    report = mon.collect()
    statuses = {c["id"]: c["status"] for c in report["checks"]}
    # equity.exists is the only equity-CRITICAL; dependents are SKIPPED
    assert statuses["d1.equity.exists"] == CRITICAL
    assert statuses["d3.cycle.ran_today"] == SKIPPED
    assert report["counts"][SKIPPED] >= 5


# Phase-1 Telegram rebuild: system_health no longer has _send_telegram. It now
# (a) pushes CRITICAL via _push_system_critical (push_policy edge-trigger),
# (b) emits _resolve_system_critical when healthy, and (c) routes the twice-daily
# summary to the digest queue via _digest_summary (never a push). The tests below
# patch those three seams.
def test_run_check_does_not_send_telegram(good_dir, monkeypatch):
    _patch_all_io(shm, monkeypatch)
    pushes, summaries = [], []
    monkeypatch.setattr(shm, "_push_system_critical", lambda m: pushes.append(m) or True)
    monkeypatch.setattr(shm, "_resolve_system_critical", lambda: None)
    monkeypatch.setattr(shm, "_digest_summary", lambda m: summaries.append(m))
    mon = make_mon(good_dir)
    mon.run(send=False)
    assert pushes == [] and summaries == []
    assert (good_dir / "data" / "system_health.json").exists()


def test_run_send_emits_summary_to_digest(good_dir, monkeypatch):
    _patch_all_io(shm, monkeypatch)
    _write(good_dir / "data", "portfolio_health.json", {"score": 90})
    summaries = []
    monkeypatch.setattr(shm, "_push_system_critical", lambda m: True)
    monkeypatch.setattr(shm, "_resolve_system_critical", lambda: None)
    monkeypatch.setattr(shm, "_digest_summary", lambda m: summaries.append(m))
    mon = make_mon(good_dir)
    mon.run(send=True)
    assert len(summaries) == 1                   # summary goes to the digest


def test_run_send_pushes_on_critical(good_dir, monkeypatch):
    _patch_all_io(shm, monkeypatch)
    _write(good_dir / "data", "red_flags.json",
           {"red_flags": [{"severity": "CRITICAL", "message": "boom"}]})
    pushes, summaries = [], []
    monkeypatch.setattr(shm, "_push_system_critical", lambda m: pushes.append(m) or True)
    monkeypatch.setattr(shm, "_resolve_system_critical", lambda: None)
    monkeypatch.setattr(shm, "_digest_summary", lambda m: summaries.append(m))
    mon = make_mon(good_dir)
    mon.run(send=True)
    # one Tier-1 push (CRITICAL page) + one digest summary
    assert len(pushes) == 1
    assert len(summaries) == 1


def test_run_edge_trigger_handles_repeat_critical(good_dir, monkeypatch):
    # The edge-trigger (one push per critical episode) is owned + unit-tested by
    # push_policy; here we just confirm the monitor routes CRITICAL to it every
    # run (push_policy itself suppresses the re-fire).
    _patch_all_io(shm, monkeypatch)
    _write(good_dir / "data", "red_flags.json",
           {"red_flags": [{"severity": "CRITICAL", "message": "boom"}]})
    pushes = []
    monkeypatch.setattr(shm, "_push_system_critical", lambda m: pushes.append(m) or True)
    monkeypatch.setattr(shm, "_resolve_system_critical", lambda: None)
    monkeypatch.setattr(shm, "_digest_summary", lambda m: None)
    make_mon(good_dir).run(send=True)
    make_mon(good_dir).run(send=True)
    assert len(pushes) == 2  # routed both runs; push_policy dedups the actual send


def test_history_ring_buffer_caps_at_30(good_dir, monkeypatch):
    _patch_all_io(shm, monkeypatch)
    mon = make_mon(good_dir)
    big_hist = [{"run_id": f"r{i}", "overall_status": OK,
                 "counts": {CRITICAL: 0, WARNING: 0, INFO: 0},
                 "fingerprint": "x", "equity_7d_pct": 0.0} for i in range(40)]
    monkeypatch.setattr(mon, "_load_previous", lambda: {"history": big_hist})
    report = mon.collect()
    assert len(report["history"]) == shm._HISTORY_MAX
    assert report["history"][-1]["run_id"] == report["run_id"]


# ---------------------------------------------------------------------------
# Always-exit-0 / fail-safe
# ---------------------------------------------------------------------------
def test_main_exits_zero_on_check(good_dir, monkeypatch):
    _patch_all_io(shm, monkeypatch)
    monkeypatch.setattr(shm.SystemHealthMonitor, "data_dir", None, raising=False)
    rc = shm.main(["--check", "--data-dir", str(good_dir / "data")])
    assert rc == 0


def test_main_exits_zero_even_when_collect_raises(good_dir, monkeypatch):
    def boom(self, send=True):
        raise RuntimeError("kaboom")
    monkeypatch.setattr(shm.SystemHealthMonitor, "run", boom)
    rc = shm.main(["--check", "--data-dir", str(good_dir / "data")])
    assert rc == 0


def test_run_never_raises_on_bad_data_dir():
    mon = SystemHealthMonitor(data_dir="/nonexistent/path/xyz", project_root="/tmp")
    report = mon.run(send=False)               # must not raise
    assert isinstance(report, dict)
    assert "overall_status" in report


def test_collect_handles_unparseable_json(good_dir, monkeypatch):
    _patch_all_io(shm, monkeypatch)
    (good_dir / "data" / "adapter_status.json").write_text("{ broken json", encoding="utf-8")
    mon = make_mon(good_dir)
    report = mon.collect()                      # must not raise
    statuses = {c["id"]: c["status"] for c in report["checks"]}
    assert statuses["d1.adapter.present"] == WARNING
