"""Tests for spa_core/monitoring/dashboard_watcher.py.

All tests are offline: urllib, Telegram, time and the /tmp state files are
mocked or redirected into a per-test temp dir. No real network calls.
"""
from __future__ import annotations

import json

import pytest

import spa_core.monitoring.dashboard_watcher as dw


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Redirect every /tmp state path into an isolated temp dir."""
    monkeypatch.setattr(dw, "TMP_PREFIX_SEEN", str(tmp_path / "seen_"))
    monkeypatch.setattr(dw, "TMP_PREFIX_COOLDOWN", str(tmp_path / "cooldown_"))
    monkeypatch.setattr(dw, "PULSE_FILE", str(tmp_path / "pulse_last"))
    monkeypatch.setattr(dw, "GOLIVE_FILE", str(tmp_path / "golive_last"))
    yield


@pytest.fixture
def no_telegram(monkeypatch):
    """Capture Telegram sends instead of hitting the network."""
    sent = []
    monkeypatch.setattr(dw, "send_telegram",
                        lambda text, **kw: sent.append(text) or True)
    return sent


# Sample data in the REAL live-API (verbatim file) shape.
HEALTHY_AGENTS = {
    "overall_status": "OK",
    "healthy_count": 24, "warning_count": 0, "critical_count": 0,
    "total_agents": 24,
    "agents": [
        {"label": "com.spa.daily_cycle", "status": "OK", "issue": ""},
        {"label": "com.spa.peg_monitor", "status": "OK", "issue": ""},
    ],
}

# Sample data in the DOCUMENTED shape (overall / healthy / issues).
HEALTHY_AGENTS_DOC = {
    "overall": "OK",
    "agents": [
        {"label": "com.spa.daily_cycle", "healthy": True, "issues": []},
    ],
}


# ===========================================================================
# check_agent_health
# ===========================================================================

def test_agent_health_ok_real_shape():
    assert dw.check_agent_health(HEALTHY_AGENTS) == []


def test_agent_health_ok_documented_shape():
    assert dw.check_agent_health(HEALTHY_AGENTS_DOC) == []


def test_agent_health_overall_critical():
    data = {"overall_status": "CRITICAL", "critical_count": 3, "warning_count": 1,
            "total_agents": 24, "agents": []}
    findings = dw.check_agent_health(data)
    assert any(f["subtype"] == "overall_critical" for f in findings)


def test_agent_health_unhealthy_agent_real_shape():
    data = {"overall_status": "WARNING", "agents": [
        {"label": "com.spa.uptime_monitor", "status": "WARNING", "issue": "log stale"},
    ]}
    findings = dw.check_agent_health(data)
    downs = [f for f in findings if f["subtype"] == "down"]
    assert len(downs) == 1
    assert downs[0]["label"] == "com.spa.uptime_monitor"
    assert downs[0]["critical"] is False


def test_agent_health_unhealthy_documented_shape():
    data = {"overall": "WARNING", "agents": [
        {"label": "com.spa.foo", "healthy": False, "issues": ["boom"]},
    ]}
    downs = [f for f in dw.check_agent_health(data) if f["subtype"] == "down"]
    assert len(downs) == 1
    assert downs[0]["issues"] == ["boom"]


def test_agent_health_critical_agent_flagged():
    data = {"overall_status": "CRITICAL", "agents": [
        {"label": "com.spa.peg_monitor", "status": "CRITICAL",
         "issue": "log stale 42.3 min (threshold 10 min)"},
    ]}
    downs = [f for f in dw.check_agent_health(data) if f["subtype"] == "down"]
    assert downs[0]["critical"] is True


def test_agent_health_issue_field_becomes_issues_list():
    data = {"overall_status": "WARNING", "agents": [
        {"label": "com.spa.x", "status": "WARNING", "issue": "stale"},
    ]}
    downs = dw.check_agent_health(data)
    assert downs[0]["issues"] == ["stale"]


def test_agent_health_non_dict_safe():
    assert dw.check_agent_health(None) == []
    assert dw.check_agent_health("nope") == []


# ===========================================================================
# check_portfolio
# ===========================================================================

def test_portfolio_ok():
    assert dw.check_portfolio({"equity": 100134.53, "is_demo": False,
                               "apy_today": 4.81}) == []


def test_portfolio_equity_low():
    f = dw.check_portfolio({"equity": 98500.0, "is_demo": False, "apy_today": 1.0})
    assert any(x["subtype"] == "equity_low" for x in f)


def test_portfolio_equity_high():
    f = dw.check_portfolio({"equity": 120000.0, "is_demo": False})
    assert any(x["subtype"] == "equity_high" for x in f)


def test_portfolio_is_demo_true():
    f = dw.check_portfolio({"equity": 100000.0, "is_demo": True})
    assert any(x["subtype"] == "is_demo" for x in f)


def test_portfolio_apy_below_floor():
    f = dw.check_portfolio({"equity": 100000.0, "is_demo": False, "apy_today": -6.2})
    assert any(x["subtype"] == "apy_low" for x in f)


def test_portfolio_apy_mild_negative_ok():
    assert dw.check_portfolio({"equity": 100000.0, "apy_today": -2.0}) == []


def test_portfolio_empty_safe():
    assert dw.check_portfolio({}) == []
    assert dw.check_portfolio(None) == []


def test_portfolio_missing_equity_only_apy():
    f = dw.check_portfolio({"apy_today": -10.0})
    assert [x["subtype"] for x in f] == ["apy_low"]


# ===========================================================================
# check_system_health
# ===========================================================================

def test_system_ok_for_warning():
    assert dw.check_system_health({"overall_status": "WARNING",
                                   "domains": {"d1": {"status": "WARNING"}}}) == []


def test_system_overall_critical():
    f = dw.check_system_health({"overall_status": "CRITICAL", "domains": {}})
    assert any(x["subtype"] == "overall_critical" for x in f)


def test_system_domain_critical():
    f = dw.check_system_health({"overall_status": "WARNING",
                               "domains": {"d4_external": {"status": "CRITICAL"}}})
    doms = [x for x in f if x["subtype"] == "domain_critical"]
    assert doms and doms[0]["domain"] == "d4_external"


def test_system_documented_overall_key():
    f = dw.check_system_health({"overall": "CRITICAL", "domains": {}})
    assert any(x["subtype"] == "overall_critical" for x in f)


def test_system_non_dict_safe():
    assert dw.check_system_health(None) == []


# ===========================================================================
# check_api_availability
# ===========================================================================

def test_api_ok_when_ping_responds():
    assert dw.check_api_availability({"ok": True, "ts": 1.0}) == []


def test_api_alert_on_none():
    f = dw.check_api_availability(None)
    assert f and f[0]["subtype"] == "unreachable"


def test_api_alert_on_bad_payload():
    assert dw.check_api_availability({"ok": False})[0]["subtype"] == "unreachable"


# ===========================================================================
# check_golive
# ===========================================================================

def test_golive_no_regression():
    assert dw.check_golive({"passed": 26, "total": 29}, 26) == []


def test_golive_regression_detected():
    f = dw.check_golive({"passed": 24, "total": 29}, 26)
    assert f and f[0]["subtype"] == "regression"
    assert f[0]["prev"] == 26 and f[0]["now"] == 24


def test_golive_improvement_no_alert():
    assert dw.check_golive({"passed": 28, "total": 29}, 26) == []


def test_golive_no_baseline_no_alert():
    assert dw.check_golive({"passed": 20, "total": 29}, None) == []


def test_golive_passing_count_alias():
    f = dw.check_golive({"passing_count": 10}, 12)
    assert f and f[0]["now"] == 10


# ===========================================================================
# Dedup / cooldown
# ===========================================================================

def test_dedup_suppresses_second_identical(no_telegram):
    f = {"kind": "system", "subtype": "overall_critical", "key": "system:overall_critical"}
    assert dw.maybe_send(f, {}) is True
    assert dw.maybe_send(f, {}) is False  # deduped
    assert len(no_telegram) == 1


def test_cooldown_suppresses_other_alert_same_kind(no_telegram):
    f1 = {"kind": "agent", "subtype": "down", "key": "agent:down:a", "label": "a",
          "issues": [], "log_age_min": None, "critical": False}
    f2 = {"kind": "agent", "subtype": "down", "key": "agent:down:b", "label": "b",
          "issues": [], "log_age_min": None, "critical": False}
    assert dw.maybe_send(f1, {}) is True
    # different key (not deduped) but same kind → cooldown blocks it
    assert dw.maybe_send(f2, {}) is False
    assert len(no_telegram) == 1


def test_seen_expires_after_ttl(monkeypatch):
    monkeypatch.setattr(dw, "DEDUP_TTL_SEC", 0)
    dw._mark_seen("k")
    # ttl 0 → immediately expired
    assert dw._is_seen("k") is False


def test_failed_send_does_not_start_cooldown(monkeypatch):
    monkeypatch.setattr(dw, "send_telegram", lambda *a, **k: False)
    f = {"kind": "api", "subtype": "unreachable", "key": "api:unreachable"}
    assert dw.maybe_send(f, {}) is False
    assert dw._is_in_cooldown("api") is False


# ===========================================================================
# Pulse
# ===========================================================================

def test_pulse_due_when_no_file():
    assert dw.should_send_pulse(now=1000.0) is True


def test_pulse_not_due_within_window():
    dw.mark_pulse(now=1000.0)
    assert dw.should_send_pulse(now=1000.0 + 60) is False


def test_pulse_due_after_6h():
    dw.mark_pulse(now=1000.0)
    assert dw.should_send_pulse(now=1000.0 + dw.PULSE_INTERVAL_SEC + 1) is True


# ===========================================================================
# Formatting
# ===========================================================================

def test_format_agent_alert_text():
    f = {"kind": "agent", "subtype": "down", "key": "k",
         "label": "com.spa.peg_monitor", "critical": True,
         "issues": ["log stale 42.3 min (threshold 10 min)"], "log_age_min": 42.3}
    ctx = {"portfolio": {"equity": 100134.0, "apy_today": 4.81},
           "healthy": 23, "total": 24}
    text = dw.format_agent_alert(f, ctx)
    assert "Dashboard Alert" in text
    assert "com.spa.peg_monitor" in text
    assert "log stale 42.3 min" in text
    assert "$100,134" in text
    assert "APY 4.81%" in text
    assert "23/24" in text


def test_format_agent_overall_critical_text():
    f = {"kind": "agent", "subtype": "overall_critical", "key": "k",
         "critical_count": 3, "warning_count": 2}
    text = dw.format_agent_alert(f, {})
    assert "CRITICAL" in text
    assert "3 critical" in text


def test_format_portfolio_alert_equity_low():
    f = {"kind": "portfolio", "subtype": "equity_low", "key": "k", "equity": 98000.0}
    text = dw.format_portfolio_alert(f, {})
    assert "$98,000" in text
    assert "$99,000" in text


def test_format_portfolio_alert_is_demo():
    f = {"kind": "portfolio", "subtype": "is_demo", "key": "k"}
    text = dw.format_portfolio_alert(f, {})
    assert "is_demo" in text


def test_format_portfolio_alert_apy_low():
    f = {"kind": "portfolio", "subtype": "apy_low", "key": "k", "apy": -6.5}
    text = dw.format_portfolio_alert(f, {})
    assert "-6.50%" in text


def test_format_pulse_text():
    ctx = {"portfolio": {"equity": 100134.0, "apy_today": 4.81},
           "healthy": 24, "total": 24}
    text = dw.format_pulse(ctx)
    assert text.startswith("✅ Dashboard check OK")
    assert "24/24 agents" in text
    assert "$100,134" in text
    assert "APY 4.81%" in text


def test_format_api_alert_text():
    text = dw.format_api_alert({"kind": "api", "subtype": "unreachable", "key": "k"}, {})
    assert "Live API" in text


def test_format_golive_alert_text():
    f = {"kind": "golive", "subtype": "regression", "key": "k",
         "prev": 26, "now": 24, "total": 29}
    text = dw.format_golive_alert(f, {})
    assert "26" in text and "24/29" in text


# ===========================================================================
# Normalization / extraction helpers
# ===========================================================================

def test_agents_summary_uses_counters():
    assert dw.agents_summary(HEALTHY_AGENTS) == (24, 24)


def test_agents_summary_derives_when_no_counters():
    data = {"agents": [
        {"label": "a", "status": "OK"},
        {"label": "b", "status": "WARNING"},
    ]}
    healthy, total = dw.agents_summary(data)
    assert (healthy, total) == (1, 2)


def test_extract_portfolio_from_bundle():
    bundle = {"portfolio_state": {"equity": 100000.0}, "pnl_history": {}}
    assert dw.extract_portfolio(bundle) == {"equity": 100000.0}


def test_extract_portfolio_bare_dict():
    assert dw.extract_portfolio({"equity": 1.0}) == {"equity": 1.0}


def test_extract_portfolio_normalizes_live_field_names():
    # cycle_runner writes current_equity / apy_today_pct
    bundle = {"portfolio_state": {"current_equity": 98000.0,
                                  "apy_today_pct": -6.0, "is_demo": False}}
    p = dw.extract_portfolio(bundle)
    assert p["equity"] == 98000.0
    assert p["apy_today"] == -6.0
    # and the checks then fire on the normalized state
    subs = {f["subtype"] for f in dw.check_portfolio(p)}
    assert subs == {"equity_low", "apy_low"}


def test_extract_system_and_golive_from_bundle():
    bundle = {"system_health": {"overall_status": "OK"},
              "golive_status": {"passed": 26}}
    assert dw.extract_system(bundle) == {"overall_status": "OK"}
    assert dw.extract_golive(bundle) == {"passed": 26}


# ===========================================================================
# run_once integration (all mocked)
# ===========================================================================

def test_run_once_api_down_sends_api_alert(monkeypatch, no_telegram):
    monkeypatch.setattr(dw, "fetch_json", lambda path, timeout=10: None)
    dw.run_once()
    assert len(no_telegram) == 1
    assert "Live API" in no_telegram[0]


def test_run_once_all_ok_sends_pulse_then_silent(monkeypatch, no_telegram):
    def fake_fetch(path, timeout=10):
        if path == dw.PING_PATH:
            return {"ok": True}
        if path == dw.AGENTS_PATH:
            return HEALTHY_AGENTS
        if path == dw.PORTFOLIO_PATH:
            return {"portfolio_state": {"equity": 100134.0, "is_demo": False,
                                        "apy_today": 4.81}}
        if path == dw.SYSTEM_PATH:
            return {"system_health": {"overall_status": "OK", "domains": {}},
                    "golive_status": {"passed": 26, "total": 29}}
        return None
    monkeypatch.setattr(dw, "fetch_json", fake_fetch)

    dw.run_once()  # pulse due (no file) → sends
    assert len(no_telegram) == 1
    assert no_telegram[0].startswith("✅ Dashboard check OK")

    dw.run_once()  # within 6h → silent
    assert len(no_telegram) == 1


def test_run_once_emits_portfolio_and_agent_alerts(monkeypatch, no_telegram):
    def fake_fetch(path, timeout=10):
        if path == dw.PING_PATH:
            return {"ok": True}
        if path == dw.AGENTS_PATH:
            return {"overall_status": "CRITICAL", "critical_count": 1,
                    "warning_count": 0, "total_agents": 24, "agents": [
                        {"label": "com.spa.daily_cycle", "status": "CRITICAL",
                         "issue": "exited 1"}]}
        if path == dw.PORTFOLIO_PATH:
            return {"portfolio_state": {"equity": 98000.0, "is_demo": False}}
        if path == dw.SYSTEM_PATH:
            return {"system_health": {"overall_status": "WARNING", "domains": {}},
                    "golive_status": {"passed": 26, "total": 29}}
        return None
    monkeypatch.setattr(dw, "fetch_json", fake_fetch)
    dw.run_once()
    joined = "\n".join(no_telegram)
    # overall_critical (agent kind) + equity_low (portfolio kind) both sent;
    # agent-down for daily_cycle is suppressed by the agent-kind cooldown.
    assert "Agent health CRITICAL" in joined
    assert "Equity below floor" in joined


def test_run_once_golive_regression(monkeypatch, no_telegram):
    dw._write_golive_last(26)

    def fake_fetch(path, timeout=10):
        if path == dw.PING_PATH:
            return {"ok": True}
        if path == dw.AGENTS_PATH:
            return HEALTHY_AGENTS
        if path == dw.PORTFOLIO_PATH:
            return {"portfolio_state": {"equity": 100000.0, "is_demo": False}}
        if path == dw.SYSTEM_PATH:
            return {"system_health": {"overall_status": "OK", "domains": {}},
                    "golive_status": {"passed": 24, "total": 29}}
        return None
    monkeypatch.setattr(dw, "fetch_json", fake_fetch)
    dw.run_once()
    assert any("GoLive regression" in t for t in no_telegram)
    assert dw._read_golive_last() == 24  # baseline updated
