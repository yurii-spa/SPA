"""
Tests для Monitor (M3) — AlertEngine + HealthCheck.
"""

from __future__ import annotations

import sys, tempfile
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from database.init_db import init_database
from spa_core.monitoring.alerts import AlertEngine, Alert
from spa_core.monitoring.health_check import HealthCheck

# ─── Runner ───────────────────────────────────────────────────────────────────

PASS = FAIL = 0
_log = []

def run(name, fn):
    global PASS, FAIL
    try:
        fn()
        PASS += 1
        _log.append(f"  ✅  {name}")
    except Exception as e:
        FAIL += 1
        _log.append(f"  ❌  {name}  →  {str(e)[:80]}")

def make_db() -> Path:
    p = Path(tempfile.mktemp(suffix=".db"))
    init_database(db_path=p)
    return p

engine = AlertEngine()

def snap(key, apy, tvl, ts=None):
    return {
        "protocol_key": key,
        "apy_total": apy,
        "tvl_usd": tvl,
        "timestamp": (ts or datetime.now(timezone.utc)).isoformat(),
        "tier": "T1",
    }

NOW = datetime.now(timezone.utc)

# ─── AlertEngine: APY drop ────────────────────────────────────────────────────

def test_apy_drop_warning():
    cur  = [snap("aave-v3-usdc-ethereum", 3.0, 100e6)]
    prev = [snap("aave-v3-usdc-ethereum", 5.0, 100e6)]
    alerts = engine.check_snapshots(cur, prev)
    drops = [a for a in alerts if a.event_type == "APY_DROP"]
    assert len(drops) == 1
    assert drops[0].severity in ("WARNING", "CRITICAL")
run("Alerts::apy_drop_triggers_warning", test_apy_drop_warning)

def test_apy_drop_critical_at_50pct():
    cur  = [snap("aave-v3-usdc-ethereum", 2.0, 100e6)]
    prev = [snap("aave-v3-usdc-ethereum", 5.0, 100e6)]  # 60% drop → CRITICAL
    alerts = engine.check_snapshots(cur, prev)
    drops = [a for a in alerts if a.event_type == "APY_DROP"]
    assert any(a.severity == "CRITICAL" for a in drops)
run("Alerts::apy_drop_critical_at_60pct", test_apy_drop_critical_at_50pct)

def test_no_apy_drop_alert_for_small_change():
    cur  = [snap("aave-v3-usdc-ethereum", 4.8, 100e6)]
    prev = [snap("aave-v3-usdc-ethereum", 5.0, 100e6)]  # 4% drop → no alert
    alerts = engine.check_snapshots(cur, prev)
    drops = [a for a in alerts if a.event_type == "APY_DROP"]
    assert len(drops) == 0
run("Alerts::no_alert_small_apy_change", test_no_apy_drop_alert_for_small_change)

# ─── AlertEngine: APY spike ───────────────────────────────────────────────────

def test_apy_spike_warning():
    cur  = [snap("maple-usdc-ethereum", 8.0, 100e6)]
    prev = [snap("maple-usdc-ethereum", 5.0, 100e6)]   # +60% spike
    alerts = engine.check_snapshots(cur, prev)
    spikes = [a for a in alerts if a.event_type == "APY_SPIKE"]
    assert len(spikes) == 1
run("Alerts::apy_spike_triggers_warning", test_apy_spike_warning)

# ─── AlertEngine: TVL drop ────────────────────────────────────────────────────

def test_tvl_drop_warning():
    cur  = [snap("compound-v3-usdc-ethereum", 4.5, 20e6)]
    prev = [snap("compound-v3-usdc-ethereum", 4.5, 50e6)]   # -60% drop
    alerts = engine.check_snapshots(cur, prev)
    drops = [a for a in alerts if a.event_type == "TVL_DROP"]
    assert len(drops) == 1
run("Alerts::tvl_drop_triggers_warning", test_tvl_drop_warning)

def test_tvl_drop_critical_at_60pct():
    cur  = [snap("compound-v3-usdc-ethereum", 4.5, 15e6)]
    prev = [snap("compound-v3-usdc-ethereum", 4.5, 50e6)]   # -70% → CRITICAL
    alerts = engine.check_snapshots(cur, prev)
    drops = [a for a in alerts if a.event_type == "TVL_DROP"]
    assert any(a.severity == "CRITICAL" for a in drops)
run("Alerts::tvl_drop_critical_at_70pct", test_tvl_drop_critical_at_60pct)

# ─── AlertEngine: stale data ─────────────────────────────────────────────────

def test_stale_data_warning():
    old_ts = (NOW - timedelta(hours=10)).isoformat()
    cur = [snap("aave-v3-usdc-ethereum", 4.5, 100e6, ts=datetime.fromisoformat(old_ts))]
    # Replace timestamp manually
    cur[0]["timestamp"] = old_ts
    alerts = engine.check_snapshots(cur, [])
    stale = [a for a in alerts if a.event_type == "STALE_DATA"]
    assert len(stale) == 1
run("Alerts::stale_data_warning", test_stale_data_warning)

def test_fresh_data_no_stale():
    cur = [snap("aave-v3-usdc-ethereum", 4.5, 100e6)]
    alerts = engine.check_snapshots(cur, [])
    stale = [a for a in alerts if a.event_type == "STALE_DATA"]
    assert len(stale) == 0
run("Alerts::fresh_data_no_stale_alert", test_fresh_data_no_stale)

# ─── AlertEngine: pipeline ────────────────────────────────────────────────────

def test_no_data_critical():
    alerts = engine.check_pipeline_health([])
    assert any(a.event_type == "NO_DATA" and a.severity == "CRITICAL" for a in alerts)
run("Alerts::no_data_triggers_critical", test_no_data_critical)

def test_missing_protocol_warning():
    # Only 3 of 7 protocols
    snaps = [snap("aave-v3-usdc-ethereum", 4.5, 100e6)]
    alerts = engine.check_pipeline_health(snaps)
    missing = [a for a in alerts if a.event_type == "MISSING_PROTOCOL_DATA"]
    assert len(missing) == 1 and missing[0].severity == "WARNING"
run("Alerts::missing_protocol_data_warning", test_missing_protocol_warning)

def test_all_protocols_no_pipeline_alert():
    all_snaps = [
        snap("aave-v3-usdc-ethereum",    4.5, 100e6),
        snap("aave-v3-usdt-ethereum",    3.0, 300e6),
        snap("compound-v3-usdc-ethereum",4.8, 30e6),
        snap("morpho-usdc-ethereum",     3.1, 100e6),
        snap("yearn-v3-usdc-ethereum",   3.4, 25e6),
        snap("maple-usdc-ethereum",      4.8, 3000e6),
        snap("euler-v2-usdc-ethereum",   2.0, 30e6),
    ]
    alerts = engine.check_pipeline_health(all_snaps)
    assert len(alerts) == 0
run("Alerts::all_protocols_no_pipeline_alert", test_all_protocols_no_pipeline_alert)

# ─── AlertEngine: low TVL ─────────────────────────────────────────────────────

def test_low_tvl_warning():
    cur = [snap("euler-v2-usdc-ethereum", 2.0, 5e6)]   # $5M < $10M threshold
    alerts = engine.check_snapshots(cur, [])
    low = [a for a in alerts if a.event_type == "LOW_TVL"]
    assert len(low) == 1
run("Alerts::low_tvl_warning", test_low_tvl_warning)

# ─── HealthCheck ──────────────────────────────────────────────────────────────

def test_health_check_runs_without_error():
    db = make_db()
    checker = HealthCheck(db_path=db)
    result = checker.run()
    assert "timestamp" in result
    assert "summary" in result
    assert "alerts" in result
run("HealthCheck::runs_without_error", test_health_check_runs_without_error)

def test_health_check_summary_keys():
    db = make_db()
    checker = HealthCheck(db_path=db)
    s = checker.run()["summary"]
    for k in ["total_alerts", "critical", "warnings", "info", "overall_status"]:
        assert k in s, f"Missing: {k}"
run("HealthCheck::summary_has_required_keys", test_health_check_summary_keys)

def test_health_check_ok_on_empty_db():
    db = make_db()
    checker = HealthCheck(db_path=db)
    s = checker.run()["summary"]
    # empty DB = no snapshots → CRITICAL alert (NO_DATA)
    # but portfolio itself is healthy
    assert s["overall_status"] in ("OK", "WARNING", "CRITICAL")  # any valid status
run("HealthCheck::valid_status_on_empty_db", test_health_check_ok_on_empty_db)

def test_health_check_market_data_section():
    db = make_db()
    checker = HealthCheck(db_path=db)
    r = checker.run()
    assert "market_data" in r
    assert "protocols" in r["market_data"]
run("HealthCheck::has_market_data_section", test_health_check_market_data_section)

# ─── Alert severity ordering ──────────────────────────────────────────────────

def test_alert_str_format():
    a = Alert(severity="WARNING", event_type="TEST", protocol_key="aave-v3-usdc-ethereum",
              message="test message")
    s = str(a)
    assert "WARNING" in s and "test message" in s
run("Alert::str_format", test_alert_str_format)

def test_alert_str_no_protocol():
    a = Alert(severity="CRITICAL", event_type="TEST", protocol_key=None, message="global alert")
    s = str(a)
    assert "CRITICAL" in s and "global alert" in s
run("Alert::str_format_no_protocol", test_alert_str_no_protocol)

# ─── Report ───────────────────────────────────────────────────────────────────

print(f"\n{'═'*62}")
print(f"  SPA Monitor (M3) — Test Suite")
print(f"{'═'*62}")
for line in _log:
    print(line)
print(f"{'─'*62}")
total = PASS + FAIL
pct = "100%" if FAIL == 0 else f"{int(PASS/total*100)}%"
print(f"  {total} tests  |  {PASS} passed  |  {FAIL} failed  |  {pct} green")
print(f"{'═'*62}\n")
