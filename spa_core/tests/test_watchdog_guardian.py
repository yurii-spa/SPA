"""Hermetic tests for spa_core/monitoring/watchdog.py — the guardian-of-guardians.

Why this file exists (cycle #84): `watchdog.py` was the only module in `spa_core/monitoring/`
with a LIVE launchd agent (`com.spa.watchdog`, every 10 min) and ZERO test files, and it
carried two instances of the recurring class #29/#31/#35–#38/#40 — publishing a claim about a
measurement that never happened:

  1. `_loaded_labels()` swallowed every failure of `launchctl list` and returned `{}`, so
     "could not measure launchd" was read as "the guardian is NOT loaded" — and acted upon.
  2. `_send_telegram()` discarded the `sent?` bool documented by `push_policy.push_critical`,
     and the flood window was marked spent regardless. Since `core_agent_down` is
     edge-triggered and was measured stuck in `bad` since 2026-07-17, every escalation
     returned False and was dropped without even reaching the digest — while the watchdog
     booked it as "the owner was warned" and went quiet for an hour.

Hermetic by construction: `_DATA` / `_STATUS` / `_FLOOD_LOG` / `GUARDIANS` are redirected into
a tmp dir and `_run` / `_bootstrap` / `_kickstart` / `_send_telegram` are stubbed, so no test
here shells out to launchctl, touches the live `data/` tree, or can emit a real Telegram push
(see the `tests-write-live-alert-state` incident class).
"""
from __future__ import annotations

import datetime
import json

import pytest

from spa_core.monitoring import watchdog as wd


# ── harness ──────────────────────────────────────────────────────────────────
def _iso(minutes_ago: float) -> str:
    t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minutes_ago)
    return t.isoformat()


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    """Redirect every path the module writes to, and forbid real side effects."""
    data = tmp_path / "data"
    data.mkdir()
    guardians = {
        "com.spa.self_heal": data / "self_heal_status.json",
        "com.spa.threat_reactor": data / "threat_reactor_status.json",
    }
    monkeypatch.setattr(wd, "_DATA", data)
    monkeypatch.setattr(wd, "_STATUS", data / "watchdog_status.json")
    monkeypatch.setattr(wd, "_FLOOD_LOG", data / "watchdog_alerts.json")
    monkeypatch.setattr(wd, "GUARDIANS", guardians)

    def _forbidden(*_a, **_kw):  # pragma: no cover - only fires on a regression
        raise AssertionError("a real subprocess/launchctl call escaped the sandbox")

    monkeypatch.setattr(wd, "_run", _forbidden)
    return {"data": data, "guardians": guardians, "monkeypatch": monkeypatch}


def _fresh_heartbeats(sandbox, minutes_ago: float = 1.0) -> None:
    for path in sandbox["guardians"].values():
        path.write_text(json.dumps({"ts": _iso(minutes_ago)}))


def _all_loaded(sandbox):
    return {label: 123 for label in sandbox["guardians"]}


def _stub_launchd(sandbox, loaded, *, bootstrap=True, kickstart=True):
    """Pin what the module believes about launchd, and record actions taken against it."""
    calls = {"bootstrap": [], "kickstart": []}
    mp = sandbox["monkeypatch"]
    mp.setattr(wd, "_loaded_labels", lambda: loaded)

    def _bs(label):
        calls["bootstrap"].append(label)
        return bootstrap

    def _ks(label):
        calls["kickstart"].append(label)
        return kickstart

    mp.setattr(wd, "_bootstrap", _bs)
    mp.setattr(wd, "_kickstart", _ks)
    return calls


def _stub_launchd_actions_only(sandbox):
    """Record bootstrap/kickstart WITHOUT pinning what the module believes about launchd —
    so the real `_loaded_labels` runs and the subprocess stub decides the outcome."""
    calls = {"bootstrap": [], "kickstart": []}
    mp = sandbox["monkeypatch"]
    mp.setattr(wd, "_bootstrap", lambda label: calls["bootstrap"].append(label) or True)
    mp.setattr(wd, "_kickstart", lambda label: calls["kickstart"].append(label) or True)
    return calls


def _stub_send(sandbox, outcome):
    """Replace the escalation with a recorder returning a fixed tri-state outcome."""
    sent = []
    mp = sandbox["monkeypatch"]

    # NOTE 2026-08-05: production _send_telegram grew an optional dedup_key
    # (per-incident push_policy fingerprint — the alerts_undelivered fix); the
    # stub mirrors the new signature. Recording/assertions are unchanged.
    def _send(msg, dedup_key=None):
        sent.append(msg)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    mp.setattr(wd, "_send_telegram", _send)
    return sent


class _Proc:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


_LAUNCHCTL_OK = (
    "PID\tStatus\tLabel\n"
    "123\t0\tcom.spa.self_heal\n"
    "-\t0\tcom.spa.threat_reactor\n"
    "456\t0\tcom.apple.something\n"
)


# ── 1. `launchctl list` that could not be measured is not an empty launchd ────
def test_loaded_labels_returns_none_when_the_call_raises(monkeypatch):
    monkeypatch.setattr(wd, "_run", lambda *_a, **_kw: (_ for _ in ()).throw(OSError("boom")))
    assert wd._loaded_labels() is None


def test_loaded_labels_returns_none_on_a_nonzero_exit(monkeypatch):
    monkeypatch.setattr(wd, "_run", lambda *_a, **_kw: _Proc(stdout="", returncode=1))
    assert wd._loaded_labels() is None


def test_loaded_labels_returns_none_on_empty_output(monkeypatch):
    """No parsable row at all is not evidence that nothing is loaded."""
    monkeypatch.setattr(wd, "_run", lambda *_a, **_kw: _Proc(stdout="", returncode=0))
    assert wd._loaded_labels() is None


def test_loaded_labels_parses_a_normal_listing(monkeypatch):
    """Positive control: a real-shaped listing is MEASURED, pids included."""
    monkeypatch.setattr(wd, "_run", lambda *_a, **_kw: _Proc(stdout=_LAUNCHCTL_OK))
    got = wd._loaded_labels()
    assert got == {"com.spa.self_heal": 123, "com.spa.threat_reactor": 0}


def test_measured_launchd_without_our_agents_is_empty_not_unmeasured(monkeypatch):
    """Positive control: {} and None must stay distinguishable — {} is a real measurement."""
    monkeypatch.setattr(
        wd, "_run", lambda *_a, **_kw: _Proc(stdout="PID\tStatus\tLabel\n1\t0\tcom.apple.x\n")
    )
    assert wd._loaded_labels() == {}


# ── 1b. the defect, reproduced END-TO-END through the real `_loaded_labels` ──
# These call `run_watchdog` with only the SUBPROCESS stubbed, so they are executable against
# the unfixed module too (no new keyword, no new key) — i.e. they fail on origin because of
# BEHAVIOUR, not because of a signature. On origin they fail exactly as the defect predicts:
# a launchctl that could not be run is read as "the guardian is NOT loaded", the module then
# bootstraps a guardian that may well be alive, and escalates a fabricated claim.
def test_unrunnable_launchctl_does_not_produce_a_not_loaded_claim(sandbox):
    _fresh_heartbeats(sandbox)
    sandbox["monkeypatch"].setattr(
        wd, "_run", lambda *_a, **_kw: (_ for _ in ()).throw(OSError("launchctl missing"))
    )
    calls = _stub_launchd_actions_only(sandbox)
    sent = _stub_send(sandbox, True)

    rep = wd.run_watchdog()

    assert calls["bootstrap"] == [], "bootstrapped a guardian whose state was never measured"
    assert rep["actions"] == [] and rep["failures"] == []
    claims = " ".join(sent)
    assert "NOT loaded" not in claims, "claimed 'NOT loaded' about an unmeasured launchd"


def test_unrunnable_launchctl_is_not_reported_healthy(sandbox):
    """NOTE — this one does NOT discriminate: it passes against the unfixed module too, but
    for the opposite reason (there, `healthy` is False because the module invented two
    bootstrap actions out of an unmeasured world). Kept as a forward pin on the intended
    reason, recorded here so the red-count is not read as evidence it does not have."""
    _fresh_heartbeats(sandbox)
    sandbox["monkeypatch"].setattr(
        wd, "_run", lambda *_a, **_kw: (_ for _ in ()).throw(OSError("launchctl missing"))
    )
    _stub_launchd_actions_only(sandbox)
    _stub_send(sandbox, True)

    rep = wd.run_watchdog()
    assert rep["healthy"] is False, "called the plane healthy without measuring launchd"


def test_a_runnable_launchctl_behaves_exactly_as_before(sandbox):
    """Positive control for the pair above: when launchctl DOES answer, nothing changed."""
    _fresh_heartbeats(sandbox)
    sandbox["monkeypatch"].setattr(wd, "_run", lambda *_a, **_kw: _Proc(stdout=_LAUNCHCTL_OK))
    calls = _stub_launchd_actions_only(sandbox)
    _stub_send(sandbox, True)

    rep = wd.run_watchdog()

    assert rep["healthy"] is True
    assert calls["bootstrap"] == [] and calls["kickstart"] == []


def test_a_runnable_launchctl_missing_a_guardian_still_bootstraps(sandbox):
    """Positive control: the remedy path still fires on a MEASURED absence."""
    _fresh_heartbeats(sandbox)
    listing = "PID\tStatus\tLabel\n123\t0\tcom.spa.self_heal\n"
    sandbox["monkeypatch"].setattr(wd, "_run", lambda *_a, **_kw: _Proc(stdout=listing))
    calls = _stub_launchd_actions_only(sandbox)
    _stub_send(sandbox, True)

    rep = wd.run_watchdog()

    assert calls["bootstrap"] == ["com.spa.threat_reactor"]
    assert rep["healthy"] is False


# ── 2. an unmeasured launchd is reported, not acted on, and is never "healthy" ─
def test_unmeasured_launchd_reports_unchecked_and_takes_no_action(sandbox):
    _fresh_heartbeats(sandbox)
    calls = _stub_launchd(sandbox, None)
    _stub_send(sandbox, True)

    rep = wd.run_watchdog()

    assert sorted(rep["unchecked"]) == ["com.spa.self_heal", "com.spa.threat_reactor"]
    assert calls["bootstrap"] == [] and calls["kickstart"] == []
    assert rep["actions"] == [] and rep["failures"] == []
    for state in rep["guardians"].values():
        assert state["loaded"] is None
        assert "launchctl" in state["unchecked"]


def test_unmeasured_launchd_is_not_healthy(sandbox):
    """The heart of the class: no actions and no failures is NOT proof of health."""
    _fresh_heartbeats(sandbox)
    _stub_launchd(sandbox, None)
    _stub_send(sandbox, True)

    assert wd.run_watchdog()["healthy"] is False


def test_unmeasured_launchd_does_not_escalate(sandbox):
    """We did not establish that anything is wrong either — do not cry wolf."""
    _fresh_heartbeats(sandbox)
    _stub_launchd(sandbox, None)
    sent = _stub_send(sandbox, True)

    rep = wd.run_watchdog()
    assert sent == []
    assert rep["alerts_attempted"] == []


def test_measured_missing_guardian_still_bootstraps(sandbox):
    """Positive control: a MEASURED absence must behave exactly as before."""
    _fresh_heartbeats(sandbox)
    calls = _stub_launchd(sandbox, {"com.spa.threat_reactor": 1})
    _stub_send(sandbox, True)

    rep = wd.run_watchdog()

    assert calls["bootstrap"] == ["com.spa.self_heal"]
    assert rep["guardians"]["com.spa.self_heal"]["action"] == "bootstrap"
    assert rep["guardians"]["com.spa.self_heal"]["loaded"] is False
    assert rep["healthy"] is False


def test_measured_stale_heartbeat_still_kickstarts(sandbox):
    """Positive control: the stale branch is untouched by this change."""
    _fresh_heartbeats(sandbox, minutes_ago=wd.STALE_MINUTES + 5)
    calls = _stub_launchd(sandbox, _all_loaded(sandbox))
    _stub_send(sandbox, True)

    rep = wd.run_watchdog()

    assert sorted(calls["kickstart"]) == ["com.spa.self_heal", "com.spa.threat_reactor"]
    assert rep["healthy"] is False


def test_everything_measured_and_fine_is_healthy(sandbox):
    """Positive control: the green verdict itself did not get stricter by accident."""
    _fresh_heartbeats(sandbox)
    calls = _stub_launchd(sandbox, _all_loaded(sandbox))
    _stub_send(sandbox, True)

    rep = wd.run_watchdog()

    assert rep["healthy"] is True
    assert rep["unchecked"] == []
    assert calls["bootstrap"] == [] and calls["kickstart"] == []


# ── 3. delivery of the escalation is measured, not assumed ───────────────────
def test_a_refused_push_is_not_booked_as_a_warning_given(sandbox):
    """The live defect: push_critical returns False and the watchdog claimed it warned."""
    _fresh_heartbeats(sandbox)
    _stub_launchd(sandbox, {})
    _stub_send(sandbox, False)

    rep = wd.run_watchdog()

    assert sorted(rep["alerts_attempted"]) == ["com.spa.self_heal", "com.spa.threat_reactor"]
    assert rep["alerts_delivered"] == []
    assert sorted(rep["alerts_undelivered"]) == [
        "com.spa.self_heal",
        "com.spa.threat_reactor",
    ]
    for state in rep["guardians"].values():
        assert state["alert"] == "refused_by_push_policy"


def test_a_delivered_push_is_reported_as_delivered(sandbox):
    """Positive control: a genuine delivery must still read as one."""
    _fresh_heartbeats(sandbox)
    _stub_launchd(sandbox, {})
    _stub_send(sandbox, True)

    rep = wd.run_watchdog()

    assert sorted(rep["alerts_delivered"]) == ["com.spa.self_heal", "com.spa.threat_reactor"]
    assert rep["alerts_undelivered"] == []
    assert rep["alerts_delivery_unmeasured"] == []
    for state in rep["guardians"].values():
        assert state["alert"] == "delivered"


def test_an_unmeasurable_push_is_reported_as_not_measured(sandbox):
    _fresh_heartbeats(sandbox)
    _stub_launchd(sandbox, {})
    _stub_send(sandbox, None)

    rep = wd.run_watchdog()

    assert sorted(rep["alerts_delivery_unmeasured"]) == [
        "com.spa.self_heal",
        "com.spa.threat_reactor",
    ]
    assert rep["alerts_delivered"] == [] and rep["alerts_undelivered"] == []
    for state in rep["guardians"].values():
        assert state["alert"] == "not_measured"


def test_an_unattempted_push_does_not_spend_the_flood_window(sandbox):
    """Nothing reached the push authority ⇒ recording "warned" would be a fabrication."""
    _fresh_heartbeats(sandbox)
    _stub_launchd(sandbox, {})
    _stub_send(sandbox, None)

    wd.run_watchdog()

    flood = json.loads((sandbox["data"] / "watchdog_alerts.json").read_text())
    assert flood == {}


def test_a_delivered_push_spends_the_flood_window(sandbox):
    """Positive control: the flood guard still works for messages that did go out."""
    _fresh_heartbeats(sandbox)
    _stub_launchd(sandbox, {})
    _stub_send(sandbox, True)

    wd.run_watchdog()

    flood = json.loads((sandbox["data"] / "watchdog_alerts.json").read_text())
    assert sorted(flood) == ["com.spa.self_heal", "com.spa.threat_reactor"]


def test_a_measured_refusal_still_spends_the_flood_window(sandbox):
    """Deliberate: some refusal paths queue into the digest, so retrying every 10 min would
    trade a silent lie for a noisy one. Pinned so a future change is a decision, not a slip."""
    _fresh_heartbeats(sandbox)
    _stub_launchd(sandbox, {})
    _stub_send(sandbox, False)

    wd.run_watchdog()

    flood = json.loads((sandbox["data"] / "watchdog_alerts.json").read_text())
    assert sorted(flood) == ["com.spa.self_heal", "com.spa.threat_reactor"]


def test_flood_suppressed_alerts_are_labelled_and_not_sent(sandbox):
    """Positive control: within the window nothing is attempted, and the report says why."""
    _fresh_heartbeats(sandbox)
    _stub_launchd(sandbox, {})
    _stub_send(sandbox, True)
    wd.run_watchdog()

    sent = _stub_send(sandbox, True)
    rep = wd.run_watchdog()

    assert sent == []
    assert rep["alerts_attempted"] == []
    for state in rep["guardians"].values():
        assert state["alert"] == "flood_suppressed"


# ── 4. `_send_telegram` itself: three states, never raises ───────────────────
def test_send_telegram_returns_the_push_authority_verdict(monkeypatch):
    from spa_core.telegram import push_policy

    monkeypatch.setattr(push_policy, "push_critical", lambda *a, **kw: True)
    assert wd._send_telegram("x") is True
    monkeypatch.setattr(push_policy, "push_critical", lambda *a, **kw: False)
    assert wd._send_telegram("x") is False


def test_send_telegram_reports_not_measured_when_the_authority_raises(monkeypatch):
    from spa_core.telegram import push_policy

    def _boom(*_a, **_kw):
        raise RuntimeError("transport down")

    monkeypatch.setattr(push_policy, "push_critical", _boom)
    assert wd._send_telegram("x") is None


def test_send_telegram_reports_not_measured_on_a_non_bool_answer(monkeypatch):
    """An answer we cannot interpret is never optimistically read as "delivered"."""
    from spa_core.telegram import push_policy

    monkeypatch.setattr(push_policy, "push_critical", lambda *a, **kw: "sent")
    assert wd._send_telegram("x") is None
    monkeypatch.setattr(push_policy, "push_critical", lambda *a, **kw: None)
    assert wd._send_telegram("x") is None


# ── 5. the live mechanism, against the real push policy (no transport) ───────
def test_edge_triggered_core_agent_down_really_refuses_while_bad(tmp_path):
    """Not a mock: reproduces the measured live state (`core_agent_down` stuck `bad` since
    2026-07-17) against the real push_policy, in a tmp data dir and with send=False."""
    from spa_core.telegram import push_policy

    tg = tmp_path / "telegram"
    tg.mkdir()
    (tg / "push_state.json").write_text(
        json.dumps(
            {
                "events": {
                    "core_agent_down": {
                        "state": "bad",
                        "last_ts": "2026-07-17T13:51:31.080091+00:00",
                        "entry_pushed": True,
                    }
                },
                "ceiling": {},
            }
        )
    )

    refused = push_policy.push_critical(
        "core_agent_down", "CRITICAL", "SPA Watchdog", "guardian down",
        data_dir=tmp_path, send=False,
    )
    assert refused is False, "a persistent bad state must stay silent (edge-trigger)"


def test_a_first_entry_for_core_agent_down_would_push(tmp_path):
    """Positive control for the test above: the key itself is not blacklisted — only the
    persistent bad state silences it, which is exactly why the watchdog must notice."""
    from spa_core.telegram import push_policy

    (tmp_path / "telegram").mkdir()
    sent = push_policy.push_critical(
        "core_agent_down", "CRITICAL", "SPA Watchdog", "guardian down",
        data_dir=tmp_path, send=False,
    )
    assert sent is True


# ── 6. the report contract stays honest and the dry run stays inert ──────────
def test_dry_run_writes_nothing_and_sends_nothing(sandbox):
    _fresh_heartbeats(sandbox, minutes_ago=wd.STALE_MINUTES + 5)
    calls = _stub_launchd(sandbox, {})
    sent = _stub_send(sandbox, True)

    rep = wd.run_watchdog(dry_run=True)

    assert not (sandbox["data"] / "watchdog_status.json").exists()
    assert not (sandbox["data"] / "watchdog_alerts.json").exists()
    assert sent == [] and calls["bootstrap"] == [] and calls["kickstart"] == []
    assert rep["alerts_attempted"] == []


def test_status_file_records_the_delivery_verdict(sandbox):
    """The status file is this agent's only durable trace — it must carry the outcome."""
    _fresh_heartbeats(sandbox)
    _stub_launchd(sandbox, {})
    _stub_send(sandbox, False)

    wd.run_watchdog()

    saved = json.loads((sandbox["data"] / "watchdog_status.json").read_text())
    assert sorted(saved["alerts_undelivered"]) == [
        "com.spa.self_heal",
        "com.spa.threat_reactor",
    ]
    assert saved["alerts_delivered"] == []
