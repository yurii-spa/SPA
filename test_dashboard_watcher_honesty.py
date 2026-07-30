"""Honesty tests for spa_core/monitoring/dashboard_watcher.py.

The dashboard watcher is a LIVE launchd agent (``com.spa.dashboard_watcher``,
``StartInterval=300``) that had **zero tests anywhere in the repo** before this
file. It polls the live API and, when nothing is wrong, publishes a liveness
pulse ("✅ Dashboard check OK").

Two properties are pinned here:

1. **It must never claim a check it did not run** (invariant #2, fail-CLOSED /
   refusal-first). If ``ping`` succeeds but ``/api/live/agents``,
   ``/api/live/portfolio`` or ``/api/live/system`` returns nothing usable, every
   ``check_*`` returns an empty finding list — which the pre-fix code read as
   "all clear" and turned into a green pulse. Unmeasured inputs must be reported
   as UNCHECKED, and the pulse must say INCOMPLETE instead of OK.
2. **The pulse cadence must hold.** ``send_telegram`` was retired to a
   digest route that always returns ``False``, so ``mark_pulse()`` was never
   reached, ``should_send_pulse()`` was permanently ``True`` and a pulse was
   enqueued on *every* 5-minute run instead of once per 6 h.

UNCHECKED is deliberately NOT escalated into an alert: no threshold
(``EQUITY_FLOOR`` / ``EQUITY_CEIL`` / ``APY_FLOOR`` / ``CRITICAL_AGENTS``) and no
alert kind is changed by these tests. Everything here is hermetic — dedup /
cooldown / pulse / golive state files are redirected into ``tmp_path``, no
network call and no Telegram transport is reachable.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from spa_core.monitoring import dashboard_watcher as dw


# ---------------------------------------------------------------------------
# Hermetic fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolate_state(monkeypatch, tmp_path):
    """Redirect every /tmp state file into tmp_path (no shared host state)."""
    monkeypatch.setattr(dw, "TMP_PREFIX_SEEN", str(tmp_path / "seen_"))
    monkeypatch.setattr(dw, "TMP_PREFIX_COOLDOWN", str(tmp_path / "cool_"))
    monkeypatch.setattr(dw, "PULSE_FILE", str(tmp_path / "pulse_last"))
    monkeypatch.setattr(dw, "GOLIVE_FILE", str(tmp_path / "golive_last"))
    return tmp_path


@pytest.fixture
def outbox(monkeypatch) -> List[str]:
    """Capture everything the watcher tries to publish.

    Patches BOTH the legacy ``send_telegram`` and the digest route so the test
    is hermetic against the pre-fix and post-fix module alike, and so the real
    ``push_policy`` digest queue is never touched.
    """
    sent: List[str] = []

    def _capture(text: str, *args: Any, **kwargs: Any) -> bool:
        sent.append(text)
        return True

    monkeypatch.setattr(dw, "send_telegram", _capture)
    monkeypatch.setattr(dw, "route_to_digest", _capture, raising=False)
    return sent


@pytest.fixture
def digest_outbox(monkeypatch) -> List[Dict[str, Any]]:
    """Capture at the REAL boundary: push_policy._enqueue_digest.

    ``send_telegram`` / ``route_to_digest`` run for real here (only the queue
    write is intercepted), so the retired-push return contract is exercised
    instead of stubbed. This is what pins the pulse cadence: a capture that
    returns ``True`` would hide the bug, because the live ``send_telegram``
    always returns ``False``.
    """
    from spa_core.telegram import push_policy

    items: List[Dict[str, Any]] = []

    def _capture(tg_dir: Any, item: Dict[str, Any], **kwargs: Any) -> None:
        items.append(item)

    monkeypatch.setattr(push_policy, "_enqueue_digest", _capture)
    return items


def _fetch_map(monkeypatch, mapping: Dict[str, Any]) -> None:
    """Stub fetch_json with a path → payload mapping (no network)."""
    def _fake(path: str, timeout: int = dw.HTTP_TIMEOUT) -> Any:
        return mapping.get(path)
    monkeypatch.setattr(dw, "fetch_json", _fake)


PING_OK = {"ok": True, "ts": 1.0, "version": "live-api-v1"}


def _agents_ok(n: int = 3) -> Dict[str, Any]:
    """A healthy /api/live/agents payload in the shape the live API emits."""
    return {
        "overall_status": "OK",
        "healthy_count": n,
        "warning_count": 0,
        "critical_count": 0,
        "total_agents": n,
        "agents": [
            {"label": f"com.spa.a{i}", "status": "OK", "log_age_min": 0.0, "issue": ""}
            for i in range(n)
        ],
    }


def _portfolio_ok() -> Dict[str, Any]:
    """Live shape: the bundle has no portfolio_state — only paper_trading_status."""
    return {
        "paper_trading_status": {
            "is_demo": False,
            "current_equity": 100_628.61,
            "apy_today_pct": 0.0,
        }
    }


def _system_ok() -> Dict[str, Any]:
    return {
        "system_health": {
            "overall_status": "OK",
            "domains": {"d1_data_pipeline": {"status": "OK", "ms": 5}},
        },
        "golive_status": {"ready": False, "passed": 28, "total": 29},
    }


def _all_ok(monkeypatch) -> None:
    _fetch_map(monkeypatch, {
        dw.PING_PATH: PING_OK,
        dw.AGENTS_PATH: _agents_ok(),
        dw.PORTFOLIO_PATH: _portfolio_ok(),
        dw.SYSTEM_PATH: _system_ok(),
    })


# ===========================================================================
# 1. Positive controls — the honest paths must stay honest
# ===========================================================================

class TestPositiveControls:
    """These pass BEFORE and AFTER the fix: behaviour is not inverted."""

    def test_all_measured_and_healthy_yields_green_pulse(self, monkeypatch, outbox):
        """Steady state on the live host: a go-live baseline is on record."""
        _all_ok(monkeypatch)
        dw._write_golive_last(28)
        dw.run_once()
        assert len(outbox) == 1
        assert "Dashboard check OK" in outbox[0]
        assert "INCOMPLETE" not in outbox[0]

    def test_first_run_without_baseline_says_incomplete(self, monkeypatch, outbox):
        """After a reboot (/tmp cleared) a regression genuinely cannot be seen.

        Self-healing: the baseline is written on the same run, so the very next
        run measures it. One honest INCOMPLETE beats a green light over a check
        that could not run.
        """
        _all_ok(monkeypatch)
        dw.run_once()
        assert "INCOMPLETE" in outbox[0] and "golive" in outbox[0]
        assert dw._read_golive_last() == 28, "baseline must be recorded"

    def test_real_finding_still_alerts(self, monkeypatch, outbox):
        sysd = _system_ok()
        sysd["system_health"]["overall_status"] = "CRITICAL"
        _fetch_map(monkeypatch, {
            dw.PING_PATH: PING_OK,
            dw.AGENTS_PATH: _agents_ok(),
            dw.PORTFOLIO_PATH: _portfolio_ok(),
            dw.SYSTEM_PATH: sysd,
        })
        dw.run_once()
        assert any("System health CRITICAL" in t for t in outbox)
        assert not any("Dashboard check OK" in t for t in outbox)

    def test_unreachable_api_still_alerts(self, monkeypatch, outbox):
        _fetch_map(monkeypatch, {})  # ping returns None
        dw.run_once()
        assert len(outbox) == 1
        assert "API" in outbox[0] or "недоступен" in outbox[0]

    def test_thresholds_unchanged(self):
        """Pinned so a later 'cleanup' cannot quietly move the alert bar."""
        assert dw.EQUITY_FLOOR == 99_000.0
        assert dw.EQUITY_CEIL == 110_000.0
        assert dw.APY_FLOOR == -5.0
        assert dw.PULSE_INTERVAL_SEC == 21_600
        assert dw.DEDUP_TTL_SEC == 7_200

    def test_equity_low_finding_preserved(self):
        out = dw.check_portfolio({"equity": 98_000.0, "is_demo": False,
                                  "apy_today": 0.0})
        assert [f["subtype"] for f in out] == ["equity_low"]

    def test_is_demo_regression_finding_preserved(self):
        out = dw.check_portfolio({"equity": 100_000.0, "is_demo": True,
                                  "apy_today": 0.0})
        assert any(f["subtype"] == "is_demo" for f in out)


# ===========================================================================
# 2. The fail-OPEN pulse — "OK" about checks that never ran
# ===========================================================================

class TestPulseNeverLies:
    def test_no_endpoint_answered_must_not_claim_ok(self, monkeypatch, outbox):
        """ping OK, all three bundles unusable → pulse must NOT say OK."""
        _fetch_map(monkeypatch, {dw.PING_PATH: PING_OK})
        dw.run_once()
        assert len(outbox) == 1, "expected exactly one pulse"
        text = outbox[0]
        assert "Dashboard check OK" not in text, (
            "watcher claimed everything is OK while agents/portfolio/system "
            "were never measured"
        )
        assert "INCOMPLETE" in text

    def test_incomplete_pulse_names_every_unmeasured_check(self, monkeypatch, outbox):
        _fetch_map(monkeypatch, {dw.PING_PATH: PING_OK})
        dw.run_once()
        text = outbox[0]
        for name in ("agents", "portfolio", "system", "golive"):
            assert name in text, f"unmeasured check {name!r} not named in the pulse"

    def test_garbage_response_type_is_not_ok(self, monkeypatch, outbox):
        """A list instead of an object is 'not measured', not 'healthy'."""
        _fetch_map(monkeypatch, {
            dw.PING_PATH: PING_OK,
            dw.AGENTS_PATH: ["not", "an", "object"],
            dw.PORTFOLIO_PATH: _portfolio_ok(),
            dw.SYSTEM_PATH: _system_ok(),
        })
        dw.run_once()
        assert len(outbox) == 1
        assert "Dashboard check OK" not in outbox[0]
        assert "agents" in outbox[0]

    def test_empty_agents_list_is_not_healthy_fleet(self, monkeypatch, outbox):
        """Zero agents evaluated must not read as 'no agent is down'."""
        payload = _agents_ok()
        payload["agents"] = []
        payload["healthy_count"] = 0
        payload["total_agents"] = 0
        _fetch_map(monkeypatch, {
            dw.PING_PATH: PING_OK,
            dw.AGENTS_PATH: payload,
            dw.PORTFOLIO_PATH: _portfolio_ok(),
            dw.SYSTEM_PATH: _system_ok(),
        })
        dw.run_once()
        assert "Dashboard check OK" not in outbox[0]

    def test_portfolio_bundle_without_state_is_unchecked(self, monkeypatch, outbox):
        _fetch_map(monkeypatch, {
            dw.PING_PATH: PING_OK,
            dw.AGENTS_PATH: _agents_ok(),
            dw.PORTFOLIO_PATH: {"equity_curve_daily": {"generated_at": "x"}},
            dw.SYSTEM_PATH: _system_ok(),
        })
        dw.run_once()
        assert "Dashboard check OK" not in outbox[0]
        assert "portfolio" in outbox[0]

    def test_system_bundle_without_health_is_unchecked(self, monkeypatch, outbox):
        _fetch_map(monkeypatch, {
            dw.PING_PATH: PING_OK,
            dw.AGENTS_PATH: _agents_ok(),
            dw.PORTFOLIO_PATH: _portfolio_ok(),
            dw.SYSTEM_PATH: {"_fetched_at": 1.0},
        })
        dw.run_once()
        assert "Dashboard check OK" not in outbox[0]
        assert "system" in outbox[0]

    def test_alert_footer_names_unmeasured_checks(self, monkeypatch, outbox):
        """When an alert goes out anyway, it must carry what was NOT measured.

        Same volume as before (no new item) — only the text gains the truth.
        """
        sysd = {"system_health": {"overall_status": "CRITICAL",
                                  "domains": {"d6": {"status": "CRITICAL"}}}}
        _fetch_map(monkeypatch, {
            dw.PING_PATH: PING_OK,
            dw.AGENTS_PATH: None,          # agents never measured
            dw.PORTFOLIO_PATH: _portfolio_ok(),
            dw.SYSTEM_PATH: sysd,
        })
        dw.run_once()
        assert outbox, "a CRITICAL system finding must still be published"
        assert any("agents" in t and ("Not measured" in t or "не измерено" in t)
                   for t in outbox), "alert did not disclose the unmeasured check"


# ===========================================================================
# 3. Pulse cadence — the retired-push refactor broke mark_pulse()
# ===========================================================================

class TestPulseCadence:
    """Exercised through the REAL routing path (``digest_outbox``).

    ``send_telegram`` was retired to the digest queue and documented to "always
    return False"; both call sites still read that as "not delivered", so
    ``mark_pulse()`` was unreachable and ``should_send_pulse()`` stayed ``True``
    forever. The published cadence (once per 6 h, module docstring) must hold.
    """

    def test_pulse_is_marked_and_not_repeated(self, monkeypatch, digest_outbox):
        _all_ok(monkeypatch)
        dw.run_once()
        dw.run_once()
        dw.run_once()
        pulses = [i for i in digest_outbox if "Dashboard check" in (i.get("body") or "")]
        assert len(pulses) == 1, (
            f"pulse published {len(pulses)}× in three consecutive runs — "
            "mark_pulse() is not reached, so the 6 h cadence is dead and the "
            "digest queue (cap 500) floods at 288 items/day"
        )

    def test_pulse_marker_file_is_written(self, monkeypatch, digest_outbox):
        _all_ok(monkeypatch)
        dw.run_once()
        assert Path(dw.PULSE_FILE).exists(), (
            "pulse marker was never written — the enqueued pulse reported "
            "'not sent', so the cadence state was never advanced"
        )

    def test_pulse_returns_after_interval(self, monkeypatch, digest_outbox):
        _all_ok(monkeypatch)
        dw.run_once()
        assert len(digest_outbox) == 1
        # age the marker beyond the 6 h interval
        Path(dw.PULSE_FILE).write_text("0")
        dw.run_once()
        assert len(digest_outbox) == 2, "pulse must resume once the interval elapsed"

    def test_incomplete_pulse_is_also_rate_limited(self, monkeypatch, digest_outbox):
        """The honest INCOMPLETE pulse must not flood either."""
        _fetch_map(monkeypatch, {dw.PING_PATH: PING_OK})
        dw.run_once()
        dw.run_once()
        assert len(digest_outbox) == 1

    def test_findings_are_still_routed_to_the_digest(self, monkeypatch, digest_outbox):
        """Alerts keep reaching the digest queue verbatim (no volume change)."""
        sysd = _system_ok()
        sysd["system_health"]["overall_status"] = "CRITICAL"
        _fetch_map(monkeypatch, {
            dw.PING_PATH: PING_OK,
            dw.AGENTS_PATH: _agents_ok(),
            dw.PORTFOLIO_PATH: _portfolio_ok(),
            dw.SYSTEM_PATH: sysd,
        })
        dw.run_once()
        assert digest_outbox, "a CRITICAL finding never reached the digest queue"
        assert all(i.get("event_key") == "dashboard_watch" for i in digest_outbox)

    def test_push_transport_is_never_used(self, monkeypatch, digest_outbox):
        """The retired push must stay retired — no Telegram transport call."""
        from spa_core.telegram import push_policy

        def _boom(*a: Any, **k: Any) -> bool:
            raise AssertionError("dashboard_watcher must never push to Telegram")

        monkeypatch.setattr(push_policy, "_send", _boom)
        _all_ok(monkeypatch)
        dw.run_once()


# ===========================================================================
# 4. UNCHECKED accounting — per-check, with reasons
# ===========================================================================

class TestUncheckedAgents:
    def test_none_payload(self):
        out = dw.unchecked_agents(None)
        assert len(out) == 1 and out[0]["check"] == "agents"
        assert out[0]["reason"]

    def test_wrong_type_quotes_it_verbatim(self):
        out = dw.unchecked_agents(["x"])
        assert "list" in out[0]["reason"]

    def test_missing_agents_list(self):
        out = dw.unchecked_agents({"overall_status": "OK", "healthy_count": 3})
        assert any("agents" in u["reason"] or "list" in u["reason"] for u in out)

    def test_empty_agents_list(self):
        out = dw.unchecked_agents({"overall_status": "OK", "agents": []})
        assert out, "an empty fleet list must be reported as unmeasured"

    def test_unrecognized_overall_is_quoted(self):
        out = dw.unchecked_agents({"overall_status": "WAT", "agents":
                                   [{"label": "a", "status": "OK"}]})
        assert any("WAT" in u["reason"] for u in out)

    def test_healthy_payload_is_fully_measured(self):
        assert dw.unchecked_agents(_agents_ok()) == []

    def test_warning_overall_is_recognized(self):
        """Live API emits WARNING — it must not be read as 'unmeasured'."""
        payload = _agents_ok()
        payload["overall_status"] = "WARNING"
        assert dw.unchecked_agents(payload) == []


class TestUncheckedPortfolio:
    def test_empty_state(self):
        out = dw.unchecked_portfolio({})
        assert out and out[0]["check"] == "portfolio"

    def test_missing_equity(self):
        out = dw.unchecked_portfolio({"is_demo": False, "apy_today": 0.0})
        assert any("equity" in u["reason"] for u in out)

    def test_non_numeric_equity_is_quoted(self):
        out = dw.unchecked_portfolio({"equity": "100628.61", "is_demo": False,
                                      "apy_today": 0.0})
        assert any("equity" in u["reason"] for u in out)

    def test_bool_equity_is_not_a_number(self):
        out = dw.unchecked_portfolio({"equity": True, "is_demo": False,
                                      "apy_today": 0.0})
        assert any("equity" in u["reason"] for u in out)

    def test_missing_is_demo(self):
        out = dw.unchecked_portfolio({"equity": 100_000.0, "apy_today": 0.0})
        assert any("is_demo" in u["reason"] for u in out)

    def test_missing_apy(self):
        out = dw.unchecked_portfolio({"equity": 100_000.0, "is_demo": False})
        assert any("apy" in u["reason"].lower() for u in out)

    def test_live_shape_is_fully_measured(self):
        """The real bundle (paper_trading_status fallback) measures everything."""
        pstate = dw.extract_portfolio(_portfolio_ok())
        assert dw.unchecked_portfolio(pstate) == []


class TestUncheckedSystem:
    def test_empty(self):
        assert dw.unchecked_system({})

    def test_missing_overall(self):
        out = dw.unchecked_system({"domains": {"d1": {"status": "OK"}}})
        assert any("overall" in u["reason"].lower() for u in out)

    def test_unrecognized_overall_quoted(self):
        out = dw.unchecked_system({"overall_status": "sideways",
                                   "domains": {"d1": {"status": "OK"}}})
        assert any("sideways" in u["reason"] for u in out)

    def test_missing_domains(self):
        out = dw.unchecked_system({"overall_status": "OK"})
        assert any("domain" in u["reason"].lower() for u in out)

    def test_empty_domains(self):
        out = dw.unchecked_system({"overall_status": "OK", "domains": {}})
        assert any("domain" in u["reason"].lower() for u in out)

    def test_unrecognized_domain_status(self):
        out = dw.unchecked_system({"overall_status": "OK",
                                   "domains": {"d1": {"ms": 5}}})
        assert any("d1" in u["reason"] for u in out)

    def test_live_shape_is_fully_measured(self):
        assert dw.unchecked_system(_system_ok()["system_health"]) == []


class TestUncheckedGolive:
    def test_missing_block(self):
        out = dw.unchecked_golive({}, 28)
        assert out and out[0]["check"] == "golive"

    def test_non_integer_count(self):
        out = dw.unchecked_golive({"passed": "28", "total": 29}, 28)
        assert out

    def test_no_baseline_is_unmeasured_not_ok(self):
        """First run / cleared /tmp: regression cannot be detected at all."""
        out = dw.unchecked_golive({"passed": 28, "total": 29}, None)
        assert out, "missing baseline must be disclosed, not silently passed"
        assert any("baseline" in u["reason"].lower()
                   or "previous" in u["reason"].lower() for u in out)

    def test_with_baseline_is_measured(self):
        assert dw.unchecked_golive({"passed": 28, "total": 29}, 28) == []

    def test_regression_still_detected(self):
        out = dw.check_golive({"passed": 27, "total": 29}, 28)
        assert out and out[0]["subtype"] == "regression"


class TestCollectUnchecked:
    def test_everything_measured(self):
        assert dw.collect_unchecked(
            _agents_ok(),
            dw.extract_portfolio(_portfolio_ok()),
            _system_ok()["system_health"],
            _system_ok()["golive_status"],
            28,
        ) == []

    def test_nothing_measured_lists_all_four(self):
        out = dw.collect_unchecked(None, {}, {}, {}, None)
        checks = {u["check"] for u in out}
        assert checks == {"agents", "portfolio", "system", "golive"}

    def test_every_entry_carries_a_reason(self):
        for u in dw.collect_unchecked(None, {}, {}, {}, None):
            assert u.get("reason"), f"unchecked entry without a reason: {u}"

    def test_never_raises_on_hostile_input(self):
        for bad in (None, 0, "", [], {"agents": 5}, {"domains": 7}):
            dw.collect_unchecked(bad, bad, bad, bad, bad)  # must not raise


# ===========================================================================
# 5. Crash-safety — a TypeError silently voided the whole run
# ===========================================================================

class TestNoSilentCrash:
    def test_agents_summary_survives_garbage_counters(self):
        """Pre-fix: int({}) → TypeError → main() swallows it → the watcher does
        NOTHING for that tick and launchd still sees exit 0."""
        healthy, total = dw.agents_summary(
            {"agents": [{"label": "a", "status": "OK"}],
             "healthy_count": {}, "total_agents": None}
        )
        assert healthy is None or isinstance(healthy, int)
        assert total is None or isinstance(total, int)

    def test_run_once_publishes_despite_garbage_counters(self, monkeypatch, outbox):
        payload = _agents_ok()
        payload["healthy_count"] = {}
        payload["total_agents"] = "many"
        _fetch_map(monkeypatch, {
            dw.PING_PATH: PING_OK,
            dw.AGENTS_PATH: payload,
            dw.PORTFOLIO_PATH: _portfolio_ok(),
            dw.SYSTEM_PATH: _system_ok(),
        })
        dw.run_once()   # pre-fix: raises TypeError out of run_once
        assert outbox, "the run produced nothing at all"

    def test_footer_never_raises_on_partial_context(self):
        for ctx in ({}, {"portfolio": None}, {"healthy": None, "total": 3},
                    {"portfolio": {"equity": "x"}}):
            dw._footer(ctx)


# ===========================================================================
# 6. Scope guard — UNCHECKED must not become a new alert
# ===========================================================================

class TestNoEscalation:
    def test_unchecked_does_not_create_alert_findings(self, monkeypatch):
        """Unmeasured inputs must not manufacture alert findings (no new noise)."""
        assert dw.check_agent_health(None) == []
        assert dw.check_portfolio({}) == []
        assert dw.check_system_health({}) == []
        assert dw.check_golive({}, None) == []

    def test_unchecked_run_publishes_at_most_the_pulse(self, monkeypatch, outbox):
        _fetch_map(monkeypatch, {dw.PING_PATH: PING_OK})
        dw.run_once()
        assert len(outbox) == 1, "unmeasured inputs must not add alert volume"

    def test_no_llm_or_network_import(self):
        """Invariant #3/#4: monitoring stays stdlib-only, no LLM client."""
        src = Path(dw.__file__).read_text()
        for banned in ("anthropic", "openai", "import requests", "from requests",
                       "import pandas", "import numpy", "web3"):
            assert banned not in src, f"banned dependency in monitoring: {banned}"
