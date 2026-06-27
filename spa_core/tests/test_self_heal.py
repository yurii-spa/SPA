"""
test_self_heal.py — unit tests for the SPA self-healing watchdog
(spa_core/monitoring/self_heal.py), the agent that GUARDS THE MONEY PATH:
it revives dead agents, kickstarts down/unreachable servers, and re-runs a
missed daily cycle.

Sprint R3 + R5. Every test is FULLY MOCKED — no real launchd, no real network,
no writes to live data/. We monkeypatch the module's I/O seams
(_loaded_labels / _expected_labels / _must_be_resident / _last_cycle_age_hours /
_served_cycle_age_hours / _revival_history) and the MUTATING actions
(_bootstrap / _kickstart / _recover_cycle), recording the DECISIONS the
watchdog would take. The persistence + telegram seams (_save /
_save_revival_history / _send_telegram) are stubbed to no-ops so a test never
touches the live filesystem or sends a message.

Covered (R3):
  (a) idle calendar agent (RunAtLoad:False, not due) → NOT bootstrapped
  (b) resident agent (KeepAlive / StartInterval) missing → bootstrapped
  (c) circuit-breaker: >5 revivals/hr → stops reviving (no infinite loop)
  (d) cycle-gap >28h → cycle-recovery path invoked (mocked, no real cycle)
  (e) dry_run=True → mutates NOTHING (no launchctl, no writes)
  (f) RETIRED agent (bot_commands etc.) → NEVER revived
  (g) probe-down server → kickstarted

Covered (R5 — apiserver data-staleness probe):
  (h) fresh cycle on disk BUT stale served API → exactly ONE apiserver kickstart
  (i) fresh served API → zero kickstarts
  (j) stale-data kickstart is circuit-broken (never a kickstart loop)
"""
# LLM_FORBIDDEN
from __future__ import annotations

import time

import pytest

from spa_core.monitoring import self_heal


# ---------------------------------------------------------------------------
# Harness — wire the watchdog's I/O seams to in-memory fakes and record the
# mutating decisions. No real subprocess / network / disk.
# ---------------------------------------------------------------------------
class _Harness:
    def __init__(self):
        self.bootstrapped: list[str] = []
        self.kickstarted: list[str] = []
        self.recovered = 0
        self.saved = 0
        self.revival_history_written = 0
        self.telegrams: list[str] = []


@pytest.fixture
def heal(monkeypatch):
    """Patch every I/O seam in self_heal so run_self_heal() is hermetic.

    Tests further override the read seams (_loaded_labels / _expected_labels /
    _must_be_resident / age probes / revival history) for their scenario.
    Defaults: nothing loaded, nothing expected, fresh cycle, no served-API
    staleness, empty revival history.
    """
    h = _Harness()

    # --- mutating actions: record, never execute ---------------------------
    def _bootstrap(label: str) -> bool:
        h.bootstrapped.append(label)
        return True

    def _kickstart(label: str) -> bool:
        h.kickstarted.append(label)
        return True

    def _recover_cycle() -> bool:
        h.recovered += 1
        return True

    monkeypatch.setattr(self_heal, "_bootstrap", _bootstrap)
    monkeypatch.setattr(self_heal, "_kickstart", _kickstart)
    monkeypatch.setattr(self_heal, "_recover_cycle", _recover_cycle)

    # --- persistence + telegram: stub so no live FS / network --------------
    monkeypatch.setattr(self_heal, "_save", lambda report: h.__setattr__("saved", h.saved + 1))
    monkeypatch.setattr(
        self_heal, "_save_revival_history",
        lambda hist: h.__setattr__("revival_history_written", h.revival_history_written + 1),
    )
    monkeypatch.setattr(self_heal, "_send_telegram", lambda msg: h.telegrams.append(msg))

    # --- read seams: safe hermetic defaults (overridden per-test) ----------
    monkeypatch.setattr(self_heal, "_loaded_labels", lambda: {})
    monkeypatch.setattr(self_heal, "_expected_labels", lambda: [])
    monkeypatch.setattr(self_heal, "_must_be_resident", lambda label: False)
    monkeypatch.setattr(self_heal, "_last_cycle_age_hours", lambda: 1.0)  # fresh
    monkeypatch.setattr(self_heal, "_served_cycle_age_hours", lambda url=None: None)
    monkeypatch.setattr(self_heal, "_revival_history", lambda: {})
    # liveness probes UP by default (no kickstart from 2b)
    monkeypatch.setattr(self_heal, "_http_up", lambda url: True)

    return h


def _guard_no_real_io(monkeypatch):
    """Belt-and-braces: blow up if any test path reaches a real subprocess /
    network call (it shouldn't — the seams above are all patched)."""
    def _boom(*a, **k):
        raise AssertionError("real subprocess invoked in a mocked test")
    monkeypatch.setattr(self_heal, "_run", _boom)


# ===========================================================================
# R3 (a) — idle calendar agent (RunAtLoad:False, not due) → NOT bootstrapped
# ===========================================================================
def test_idle_calendar_agent_not_bootstrapped(heal, monkeypatch):
    _guard_no_real_io(monkeypatch)
    # Installed + expected, but NOT loaded and NOT residency-required (calendar).
    monkeypatch.setattr(self_heal, "_expected_labels", lambda: ["com.spa.daily_cycle"])
    monkeypatch.setattr(self_heal, "_loaded_labels", lambda: {})
    monkeypatch.setattr(self_heal, "_must_be_resident", lambda label: False)

    report = self_heal.run_self_heal(dry_run=False)

    assert heal.bootstrapped == []                      # the chronic false-revive guard
    assert report["idle_calendar_skipped"] == 1
    assert report["missing_resident"] == []
    assert report["healthy"] is True                    # idle calendar ≠ unhealthy


# ===========================================================================
# R3 (b) — resident agent (KeepAlive / StartInterval) missing → bootstrapped
# ===========================================================================
def test_missing_resident_agent_bootstrapped(heal, monkeypatch):
    _guard_no_real_io(monkeypatch)
    monkeypatch.setattr(self_heal, "_expected_labels", lambda: ["com.spa.rules_watchdog"])
    monkeypatch.setattr(self_heal, "_loaded_labels", lambda: {})          # missing
    monkeypatch.setattr(self_heal, "_must_be_resident", lambda label: True)  # resident-required

    report = self_heal.run_self_heal(dry_run=False)

    assert heal.bootstrapped == ["com.spa.rules_watchdog"]
    assert any("revived (bootstrap) com.spa.rules_watchdog" in a for a in report["actions"])
    # missing_resident reflects the pre-heal snapshot (loaded is captured once),
    # so the just-revived label is correctly still reported as having been down.
    assert report["missing_resident"] == ["com.spa.rules_watchdog"]


# ===========================================================================
# R3 (c) — circuit-breaker: >5 revivals/hr → stops reviving (no infinite loop)
# ===========================================================================
def test_circuit_breaker_stops_reviving_crash_looper(heal, monkeypatch):
    _guard_no_real_io(monkeypatch)
    label = "com.spa.flapper"
    monkeypatch.setattr(self_heal, "_expected_labels", lambda: [label])
    monkeypatch.setattr(self_heal, "_loaded_labels", lambda: {})
    monkeypatch.setattr(self_heal, "_must_be_resident", lambda l: True)
    # already revived MAX times within the last hour
    now = time.time()
    monkeypatch.setattr(
        self_heal, "_revival_history",
        lambda: {label: [now - i for i in range(self_heal.MAX_REVIVALS_PER_HOUR)]},
    )

    report = self_heal.run_self_heal(dry_run=False)

    assert heal.bootstrapped == []                      # breaker tripped → NOT revived
    assert any("circuit-breaker" in b and label in b for b in report["circuit_breakers"])
    assert report["healthy"] is False                   # an open breaker is unhealthy


# ===========================================================================
# R3 (d) — cycle-gap >28h → cycle-recovery path invoked (mocked, no real cycle)
# ===========================================================================
def test_cycle_gap_triggers_recovery(heal, monkeypatch):
    _guard_no_real_io(monkeypatch)
    monkeypatch.setattr(self_heal, "_last_cycle_age_hours", lambda: 40.0)  # > 28h

    report = self_heal.run_self_heal(dry_run=False)

    assert heal.recovered == 1
    assert any("cycle recovery ok" in a for a in report["actions"])


def test_fresh_cycle_no_recovery(heal, monkeypatch):
    _guard_no_real_io(monkeypatch)
    monkeypatch.setattr(self_heal, "_last_cycle_age_hours", lambda: 3.0)   # fresh

    report = self_heal.run_self_heal(dry_run=False)

    assert heal.recovered == 0
    assert not any("cycle recovery" in a for a in report["actions"])


# ===========================================================================
# R3 (e) — dry_run=True → mutates NOTHING (no launchctl, no writes)
# ===========================================================================
def test_dry_run_mutates_nothing(heal, monkeypatch):
    _guard_no_real_io(monkeypatch)
    # Pile up would-act conditions that can coexist: missing resident, down
    # server, unreachable probe, and a stale served-API (disk FRESH so the
    # stale-API edge fires). The mutually-exclusive cycle-gap case (needs a STALE
    # disk) is covered by test_dry_run_cycle_gap below.
    monkeypatch.setattr(self_heal, "_expected_labels", lambda: ["com.spa.rules_watchdog"])
    monkeypatch.setattr(self_heal, "_loaded_labels", lambda: {"com.spa.familyfund": 0})
    monkeypatch.setattr(self_heal, "_must_be_resident", lambda l: True)
    monkeypatch.setattr(self_heal, "_http_up", lambda url: False)          # unreachable probe(s)
    monkeypatch.setattr(self_heal, "_last_cycle_age_hours", lambda: 2.0)    # fresh disk
    monkeypatch.setattr(self_heal, "_served_cycle_age_hours",
                        lambda url=None: self_heal.API_STALE_HOURS + 5.0)   # stale served API

    report = self_heal.run_self_heal(dry_run=True)

    # NOTHING mutated:
    assert heal.bootstrapped == []
    assert heal.kickstarted == []
    assert heal.recovered == 0
    assert heal.saved == 0
    assert heal.revival_history_written == 0
    assert heal.telegrams == []
    # …but the would-do decisions ARE surfaced:
    assert any("would bootstrap" in a for a in report["actions"])
    assert any("would kickstart" in a for a in report["actions"])
    assert any("would kickstart apiserver" in a for a in report["actions"])


def test_dry_run_cycle_gap_no_recovery(heal, monkeypatch):
    _guard_no_real_io(monkeypatch)
    monkeypatch.setattr(self_heal, "_last_cycle_age_hours", lambda: 40.0)  # stale disk

    report = self_heal.run_self_heal(dry_run=True)

    assert heal.recovered == 0
    assert heal.saved == 0
    assert any("would recover cycle" in a for a in report["actions"])


# ===========================================================================
# R3 (f) — RETIRED agent (bot_commands etc.) → NEVER revived
# ===========================================================================
def test_retired_agent_never_revived(heal, monkeypatch):
    _guard_no_real_io(monkeypatch)
    # _expected_labels() filters RETIRED_LABELS out at the source. Even if a
    # retired label somehow slipped through, it must not be bootstrapped — assert
    # both: it's excluded from expected, and never acted on.
    assert "com.spa.bot_commands" in self_heal.RETIRED_LABELS

    # Simulate the real _expected_labels filtering: retired never appears.
    monkeypatch.setattr(self_heal, "_expected_labels", lambda: [])  # bot_commands filtered out
    monkeypatch.setattr(self_heal, "_loaded_labels", lambda: {})    # not loaded
    monkeypatch.setattr(self_heal, "_must_be_resident", lambda l: True)

    report = self_heal.run_self_heal(dry_run=False)

    assert "com.spa.bot_commands" not in heal.bootstrapped
    assert heal.bootstrapped == []


def test_expected_labels_excludes_retired(monkeypatch, tmp_path):
    """The source-of-truth guard: _expected_labels() never yields a RETIRED label
    even when its .plist is physically present in the LaunchAgents dir."""
    la = tmp_path / "LaunchAgents"
    la.mkdir()
    # one retired + one live plist on disk
    (la / "com.spa.bot_commands.plist").write_text("<plist></plist>")
    (la / "com.spa.rules_watchdog.plist").write_text("<plist></plist>")
    monkeypatch.setattr(self_heal, "_LA", la)

    labels = self_heal._expected_labels()

    assert "com.spa.bot_commands" not in labels
    assert "com.spa.rules_watchdog" in labels


# ===========================================================================
# R3 (g) — probe-down server → kickstarted
# ===========================================================================
def test_probe_down_server_kickstarted(heal, monkeypatch):
    _guard_no_real_io(monkeypatch)
    # apiserver probe URL is unreachable → kickstart com.spa.apiserver.
    def _http_up(url):
        return url != "http://127.0.0.1:8765/health"
    monkeypatch.setattr(self_heal, "_http_up", _http_up)

    report = self_heal.run_self_heal(dry_run=False)

    assert "com.spa.apiserver" in heal.kickstarted
    assert any("restarted unreachable com.spa.apiserver" in a for a in report["actions"])


def test_down_server_pid0_kickstarted(heal, monkeypatch):
    _guard_no_real_io(monkeypatch)
    # loaded but PID 0 → kickstart (step 2).
    monkeypatch.setattr(self_heal, "_loaded_labels", lambda: {"com.spa.apiserver": 0})
    report = self_heal.run_self_heal(dry_run=False)
    assert "com.spa.apiserver" in heal.kickstarted
    assert any("restarted down server com.spa.apiserver" in a for a in report["actions"])


# ===========================================================================
# R5 (h) — fresh cycle on disk BUT stale served API → exactly ONE kickstart
# ===========================================================================
def test_stale_api_with_fresh_cycle_kickstarts_once(heal, monkeypatch):
    _guard_no_real_io(monkeypatch)
    # Disk cycle FRESH (cycle DID run) but apiserver SERVES a frozen, stale status.
    monkeypatch.setattr(self_heal, "_last_cycle_age_hours", lambda: 2.0)   # fresh on disk
    monkeypatch.setattr(self_heal, "_served_cycle_age_hours",
                        lambda url=None: self_heal.API_STALE_HOURS + 5.0)   # served stale

    report = self_heal.run_self_heal(dry_run=False)

    # EXACTLY ONE apiserver kickstart from the stale-data path.
    assert heal.kickstarted.count("com.spa.apiserver") == 1
    assert any("serving STALE data" in a for a in report["actions"])


# ===========================================================================
# R5 (i) — fresh served API → zero kickstarts
# ===========================================================================
def test_fresh_api_no_kickstart(heal, monkeypatch):
    _guard_no_real_io(monkeypatch)
    monkeypatch.setattr(self_heal, "_last_cycle_age_hours", lambda: 2.0)   # fresh disk
    monkeypatch.setattr(self_heal, "_served_cycle_age_hours", lambda url=None: 1.5)  # fresh API

    report = self_heal.run_self_heal(dry_run=False)

    assert heal.kickstarted == []
    assert not any("STALE data" in a for a in report["actions"])


def test_unreachable_served_status_no_stale_kickstart(heal, monkeypatch):
    """If the served-status probe can't read a timestamp (None), the stale-data
    path takes NO action — a probe error must never trigger a kickstart. (Port
    down is handled by the separate liveness probe, not here.)"""
    _guard_no_real_io(monkeypatch)
    monkeypatch.setattr(self_heal, "_last_cycle_age_hours", lambda: 2.0)
    monkeypatch.setattr(self_heal, "_served_cycle_age_hours", lambda url=None: None)

    report = self_heal.run_self_heal(dry_run=False)

    assert heal.kickstarted == []
    assert not any("STALE data" in a for a in report["actions"])


def test_stale_cycle_does_not_trigger_stale_api_path(heal, monkeypatch):
    """When the cycle on disk is itself stale (>28h), the stale-API path is
    edge-OFF (it only fires when the cycle DID run recently) — the cycle-gap
    recovery in step 3 owns that case instead, so no double-action."""
    _guard_no_real_io(monkeypatch)
    monkeypatch.setattr(self_heal, "_last_cycle_age_hours", lambda: 40.0)  # stale disk
    monkeypatch.setattr(self_heal, "_served_cycle_age_hours", lambda url=None: 50.0)

    report = self_heal.run_self_heal(dry_run=False)

    # No stale-data kickstart (cycle wasn't fresh); recovery handled it.
    assert heal.kickstarted.count("com.spa.apiserver") == 0
    assert heal.recovered == 1


# ===========================================================================
# R5 (j) — stale-data kickstart is circuit-broken (never a kickstart loop)
# ===========================================================================
def test_stale_api_kickstart_circuit_broken(heal, monkeypatch):
    _guard_no_real_io(monkeypatch)
    monkeypatch.setattr(self_heal, "_last_cycle_age_hours", lambda: 2.0)
    monkeypatch.setattr(self_heal, "_served_cycle_age_hours",
                        lambda url=None: self_heal.API_STALE_HOURS + 5.0)
    # already kickstarted MAX times this hour under the synthetic stale-data key
    now = time.time()
    monkeypatch.setattr(
        self_heal, "_revival_history",
        lambda: {self_heal._API_STALE_LABEL:
                 [now - i for i in range(self_heal.MAX_REVIVALS_PER_HOUR)]},
    )

    report = self_heal.run_self_heal(dry_run=False)

    assert heal.kickstarted == []                       # breaker tripped → no loop
    assert any("stale-data kickstart suppressed" in b for b in report["circuit_breakers"])


def test_stale_api_records_revival_for_breaker(heal, monkeypatch):
    """A successful stale-data kickstart is RECORDED so the breaker can count it
    on the next run — proving the loop-guard accrues (edge → eventually broken)."""
    _guard_no_real_io(monkeypatch)
    monkeypatch.setattr(self_heal, "_last_cycle_age_hours", lambda: 2.0)
    monkeypatch.setattr(self_heal, "_served_cycle_age_hours",
                        lambda url=None: self_heal.API_STALE_HOURS + 5.0)

    captured = {}

    def _record(hist, label, epoch):
        captured.setdefault(label, 0)
        captured[label] += 1
    monkeypatch.setattr(self_heal, "_record_revival", _record)

    self_heal.run_self_heal(dry_run=False)

    assert captured.get(self_heal._API_STALE_LABEL) == 1


# ===========================================================================
# Cross-cutting: a fully-healthy fleet does NOTHING and is healthy.
# ===========================================================================
def test_healthy_fleet_noop(heal, monkeypatch):
    _guard_no_real_io(monkeypatch)
    monkeypatch.setattr(self_heal, "_expected_labels", lambda: ["com.spa.rules_watchdog"])
    monkeypatch.setattr(self_heal, "_loaded_labels", lambda: {"com.spa.rules_watchdog": 4321})
    monkeypatch.setattr(self_heal, "_must_be_resident", lambda l: True)

    report = self_heal.run_self_heal(dry_run=False)

    assert heal.bootstrapped == []
    assert heal.kickstarted == []
    assert heal.recovered == 0
    assert report["actions"] == []
    assert report["failures"] == []
    assert report["circuit_breakers"] == []
    assert report["healthy"] is True
