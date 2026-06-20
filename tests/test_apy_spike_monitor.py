"""
tests/test_apy_spike_monitor.py — MP-1581

25 tests for spa_core/alerts/apy_spike_monitor.py (APY yield-spike monitor).

Pure stdlib + pytest. No network: Telegram is monkeypatched, APY source is
injected. History writes go to a tmp_path so the real data/ is untouched.
"""
from __future__ import annotations

import json
import os

import pytest

from spa_core.alerts.apy_spike_monitor import (
    APYSpikeMonitor,
    SpikeAlert,
    SPIKE_THRESHOLDS,
    HISTORY_PATH,
    HISTORY_CAP,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mon(tmp_path):
    """Monitor rooted at a tmp repo with a data/ dir."""
    (tmp_path / "data").mkdir()
    return APYSpikeMonitor(base_dir=str(tmp_path))


def _write_adapter_status(tmp_path, apys):
    """Write a minimal execution-style adapter_status.json (apy in percent)."""
    adapters = {p: {"apy": v, "tier": 1} for p, v in apys.items()}
    path = tmp_path / "data" / "adapter_status.json"
    path.write_text(json.dumps({"schema_version": 2, "adapters": adapters}))


# ---------------------------------------------------------------------------
# Thresholds / config (1-3)
# ---------------------------------------------------------------------------

def test_thresholds_cover_five_protocols():
    assert set(SPIKE_THRESHOLDS) == {
        "aave_v3", "compound_v3", "yearn_v3", "morpho_blue", "fluid_usdc"
    }


def test_threshold_values():
    assert SPIKE_THRESHOLDS["aave_v3"] == 7.0
    assert SPIKE_THRESHOLDS["compound_v3"] == 8.0
    assert SPIKE_THRESHOLDS["yearn_v3"] == 10.0
    assert SPIKE_THRESHOLDS["morpho_blue"] == 9.0
    assert SPIKE_THRESHOLDS["fluid_usdc"] == 9.0


def test_class_exposes_thresholds(mon):
    assert mon.SPIKE_THRESHOLDS is SPIKE_THRESHOLDS


# ---------------------------------------------------------------------------
# check_spikes — detection logic (4-13)
# ---------------------------------------------------------------------------

def test_no_spike_when_all_below_threshold(mon):
    apys = {"aave_v3": 3.64, "compound_v3": 4.0, "yearn_v3": 5.0,
            "morpho_blue": 6.0, "fluid_usdc": 5.5}
    assert mon.check_spikes(apys=apys) == []


def test_single_spike_aave(mon):
    spikes = mon.check_spikes(apys={"aave_v3": 12.60})
    assert len(spikes) == 1
    assert spikes[0].protocol == "aave_v3"
    assert spikes[0].current_apy == 12.60


def test_spike_excess_pct(mon):
    spikes = mon.check_spikes(apys={"aave_v3": 12.60})
    # 12.60 - 7.0 threshold = 5.60 percentage points
    assert spikes[0].excess_pct == pytest.approx(5.60)


def test_spike_threshold_recorded(mon):
    spikes = mon.check_spikes(apys={"yearn_v3": 16.05})
    assert spikes[0].threshold == 10.0


def test_recommendation_text(mon):
    spikes = mon.check_spikes(apys={"morpho_blue": 9.57})
    assert spikes[0].recommendation == "Consider increasing morpho_blue allocation"


def test_exactly_at_threshold_is_not_a_spike(mon):
    # strictly greater-than: equal does not trigger
    assert mon.check_spikes(apys={"aave_v3": 7.0}) == []


def test_just_above_threshold_triggers(mon):
    spikes = mon.check_spikes(apys={"aave_v3": 7.01})
    assert len(spikes) == 1


def test_multiple_spikes(mon):
    apys = {"aave_v3": 12.60, "compound_v3": 11.70,
            "yearn_v3": 16.05, "morpho_blue": 9.57}
    spikes = mon.check_spikes(apys=apys)
    assert {s.protocol for s in spikes} == {
        "aave_v3", "compound_v3", "yearn_v3", "morpho_blue"
    }


def test_unknown_protocol_ignored(mon):
    spikes = mon.check_spikes(apys={"some_random_proto": 99.0})
    assert spikes == []


def test_missing_protocol_skipped(mon):
    # only aave present; others absent → only aave evaluated
    spikes = mon.check_spikes(apys={"aave_v3": 8.0})
    assert len(spikes) == 1 and spikes[0].protocol == "aave_v3"


# ---------------------------------------------------------------------------
# SpikeAlert dataclass (14-16)
# ---------------------------------------------------------------------------

def test_spikealert_fields():
    a = SpikeAlert("aave_v3", 12.6, 7.0, 5.6, "2026-06-21T00:00:00", "rec")
    assert a.protocol == "aave_v3"
    assert a.current_apy == 12.6
    assert a.timestamp == "2026-06-21T00:00:00"


def test_spikealert_to_dict_roundtrip(mon):
    spike = mon.check_spikes(apys={"aave_v3": 12.6})[0]
    d = spike.to_dict()
    assert d["protocol"] == "aave_v3"
    assert set(d) == {
        "protocol", "current_apy", "threshold",
        "excess_pct", "timestamp", "recommendation",
    }


def test_timestamp_is_iso(mon):
    spike = mon.check_spikes(apys={"aave_v3": 12.6})[0]
    # parseable as ISO-8601
    import datetime
    datetime.datetime.fromisoformat(spike.timestamp)


# ---------------------------------------------------------------------------
# APY source resolution (17-20)
# ---------------------------------------------------------------------------

def test_loads_from_adapter_status(tmp_path):
    (tmp_path / "data").mkdir()
    _write_adapter_status(tmp_path, {"aave_v3": 12.60, "compound_v3": 3.0})
    mon = APYSpikeMonitor(base_dir=str(tmp_path))
    spikes = mon.check_spikes()
    assert len(spikes) == 1 and spikes[0].protocol == "aave_v3"


def test_injected_dict_source(tmp_path):
    mon = APYSpikeMonitor(base_dir=str(tmp_path), apy_source={"aave_v3": 8.0})
    assert len(mon.check_spikes()) == 1


def test_injected_callable_source(tmp_path):
    mon = APYSpikeMonitor(base_dir=str(tmp_path),
                          apy_source=lambda: {"yearn_v3": 16.05})
    spikes = mon.check_spikes()
    assert spikes[0].protocol == "yearn_v3"


def test_missing_adapter_status_is_safe(mon):
    # no adapter_status.json written → empty source → no spikes, no crash
    assert mon.check_spikes() == []


# ---------------------------------------------------------------------------
# Telegram (21-22)
# ---------------------------------------------------------------------------

def test_send_telegram_alert_calls_client(mon, monkeypatch):
    sent = {}

    def fake_send(text, parse_mode="Markdown"):
        sent["text"] = text
        sent["parse_mode"] = parse_mode
        return True

    monkeypatch.setattr(
        "spa_core.alerts.telegram_client.send_message", fake_send
    )
    spike = mon.check_spikes(apys={"aave_v3": 12.60})[0]
    assert mon.send_telegram_alert(spike) is True
    assert "YIELD SPIKE" in sent["text"]
    assert "aave_v3" in sent["text"]
    assert sent["parse_mode"] == "HTML"


def test_send_telegram_alert_failsafe(mon, monkeypatch):
    def boom(text, parse_mode="Markdown"):
        raise RuntimeError("network down")

    monkeypatch.setattr(
        "spa_core.alerts.telegram_client.send_message", boom
    )
    spike = mon.check_spikes(apys={"aave_v3": 12.60})[0]
    # never raises, returns False
    assert mon.send_telegram_alert(spike) is False


def test_format_alert_contents(mon):
    spike = mon.check_spikes(apys={"aave_v3": 12.60})[0]
    msg = mon.format_alert(spike)
    assert msg.startswith("🚀 YIELD SPIKE: aave_v3 at 12.60% APY!")
    assert "Consider increasing aave_v3 allocation" in msg


# ---------------------------------------------------------------------------
# History logging (24-25) + run()
# ---------------------------------------------------------------------------

def test_log_spike_to_history_writes_atomically(mon, tmp_path):
    spike = mon.check_spikes(apys={"aave_v3": 12.60})[0]
    mon.log_spike_to_history(spike)
    path = tmp_path / HISTORY_PATH
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["spikes"][-1]["protocol"] == "aave_v3"
    # no leftover tmp files
    assert not any(f.endswith(".tmp") for f in os.listdir(tmp_path / "data"))


def test_history_ring_buffer_cap(mon):
    spike = mon.check_spikes(apys={"aave_v3": 12.60})[0]
    last = 0
    for _ in range(HISTORY_CAP + 10):
        last = mon.log_spike_to_history(spike)
    assert last == HISTORY_CAP


def test_run_sends_and_logs(mon, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "spa_core.alerts.telegram_client.send_message",
        lambda text, parse_mode="Markdown": calls.append(text) or True,
    )
    spikes = mon.run(apys={"aave_v3": 12.60, "compound_v3": 11.70})
    assert len(spikes) == 2
    assert len(calls) == 2  # one telegram per spike
    data = json.loads((tmp_path / HISTORY_PATH).read_text())
    assert len(data["spikes"]) == 2
