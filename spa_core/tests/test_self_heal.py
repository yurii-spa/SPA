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

Covered (R6 — telegram_bot beacon-staleness probe, owner mandate 2026-08-21):
  (k) live pid + stale beacon → exactly ONE bot kickstart; fresh/unmeasurable → none
  (l) pid 0 left to rule 2 (never two kickstarts for one incident)
  (m) bot not loaded → probe never even READ; circuit breaker; dry-run
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
        self.resolves: list[str] = []          # own-28: recovered-pushes emitted


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
    # NOTE 2026-08-05: production _send_telegram grew an optional dedup_key
    # (per-incident push_policy fingerprint — the alerts_undelivered fix); the
    # stub mirrors the new signature. Recording/assertions are unchanged.
    monkeypatch.setattr(self_heal, "_send_telegram",
                        lambda msg, dedup_key=None: h.telegrams.append(msg))
    # own-28 resolve seams (hermetic: never touch the live push_state.json).
    # Default: NOTHING pending → no resolve. raising=False on purpose: on
    # UNFIXED code (seams absent) the attributes are injected but never called,
    # so the positive-control test fails on ITS OWN assertion (resolve did not
    # happen) instead of erroring every unrelated test in this file.
    monkeypatch.setattr(self_heal, "_pending_core_incident",
                        lambda: None, raising=False)
    monkeypatch.setattr(
        self_heal, "_resolve_core_agent_down",
        lambda msg: (h.resolves.append(msg), True)[1], raising=False,
    )

    # --- read seams: safe hermetic defaults (overridden per-test) ----------
    monkeypatch.setattr(self_heal, "_loaded_labels", lambda: {})
    monkeypatch.setattr(self_heal, "_expected_labels", lambda: [])
    monkeypatch.setattr(self_heal, "_must_be_resident", lambda label: False)
    monkeypatch.setattr(self_heal, "_last_cycle_age_hours", lambda: 1.0)  # fresh
    monkeypatch.setattr(self_heal, "_served_cycle_age_hours", lambda url=None: None)
    monkeypatch.setattr(self_heal, "_revival_history", lambda: {})
    # liveness probes UP by default (no kickstart from 2b)
    monkeypatch.setattr(self_heal, "_http_up", lambda url: True)
    # NOTE 2026-08-21: R6 (telegram_bot stale-beacon probe) added its own read
    # seam; default None = «не измерено» → no action, so tests that load the bot
    # with a live pid never touch the real data/ beacon. raising=False for the
    # same reason as the own-28 seams above.
    monkeypatch.setattr(self_heal, "_beacon_age_seconds", lambda: None, raising=False)

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


# ===========================================================================
# S2 (2026-08-05) — fail-OPEN: a breached cycle-staleness threshold reported
# healthy:true. Measured in prod: cycle_age_h 27.05 (> CYCLE_STALE_H 26, the
# SAME threshold agent_health CRITICALs on) while self_heal_status.json said
# healthy:true. POSITIVE CONTROL: reds on unfixed code (healthy ignored age).
# ===========================================================================
def test_breached_cycle_staleness_cannot_be_healthy(heal, monkeypatch):
    _guard_no_real_io(monkeypatch)
    # 27.05h: inside the 26..28 window — past the staleness SLA, but below the
    # 28h ACT (recovery) threshold, so no action fires. Exactly the prod case.
    monkeypatch.setattr(self_heal, "_last_cycle_age_hours", lambda: 27.05)

    report = self_heal.run_self_heal(dry_run=False)

    assert heal.recovered == 0                       # ACT threshold (28h) not reached
    assert report["cycle_age_h"] == 27.05
    assert report["cycle_stale"] is True
    assert report["healthy"] is False                # breached SLA ≠ healthy


def test_fresh_cycle_within_sla_is_healthy(heal, monkeypatch):
    # Control in the other direction: a fresh cycle stays healthy.
    _guard_no_real_io(monkeypatch)
    monkeypatch.setattr(self_heal, "_last_cycle_age_hours", lambda: 25.9)

    report = self_heal.run_self_heal(dry_run=False)

    assert report["cycle_stale"] is False
    assert report["healthy"] is True


def test_cycle_stale_threshold_matches_agent_health(heal, monkeypatch):
    # The SENSE threshold must stay the single shared source (agent_health's
    # CYCLE_STALE_H), so the two monitors can never disagree about "stale".
    from spa_core.monitoring.agent_health_monitor import CYCLE_STALE_H
    _guard_no_real_io(monkeypatch)
    monkeypatch.setattr(self_heal, "_last_cycle_age_hours", lambda: 1.0)
    report = self_heal.run_self_heal(dry_run=False)
    assert report["cycle_stale_threshold_h"] == CYCLE_STALE_H == 26.0


def test_incident_fingerprint_reaches_push_policy(heal, monkeypatch):
    # The Telegram escalation must carry a per-incident dedup_key (the labels
    # acted on), so a NEW incident is never silenced by an old one that left
    # the shared core_agent_down class "bad" (alerts_undelivered fix).
    _guard_no_real_io(monkeypatch)
    seen = {}

    def _capture(msg, dedup_key=None):
        seen["msg"] = msg
        seen["dedup_key"] = dedup_key

    monkeypatch.setattr(self_heal, "_send_telegram", _capture)
    monkeypatch.setattr(self_heal, "_expected_labels", lambda: ["com.spa.rtmr_sense"])
    monkeypatch.setattr(self_heal, "_loaded_labels", lambda: {})
    monkeypatch.setattr(self_heal, "_must_be_resident", lambda l: True)

    self_heal.run_self_heal(dry_run=False)

    assert "com.spa.rtmr_sense" in seen.get("msg", "")
    assert seen.get("dedup_key") == "com.spa.rtmr_sense"


# ===========================================================================
# own-28 (вариант 1, 2026-08-05) — финальное «✅ восстановлено» по
# core_agent_down даёт ТОЛЬКО self_heal, и ТОЛЬКО когда его собственная
# проверка флота этим прогоном доказывает «все агенты снова живы».
# До фикса resolve('core_agent_down') не вызывался НИКЕМ — recovered-сообщение
# не приходило вовсе (S2, measured in prod).
# POSITIVE CONTROL: первый тест красный на нефиксенном коде (resolve нет).
# ===========================================================================
_PENDING = {"state": "bad", "fingerprint": "uptime:com.spa.daily_cycle",
            "entry_pushed": True}


def _alive_fleet(monkeypatch):
    """One residency-required agent, loaded and alive; cycle fresh."""
    monkeypatch.setattr(self_heal, "_expected_labels",
                        lambda: ["com.spa.rules_watchdog"])
    monkeypatch.setattr(self_heal, "_loaded_labels",
                        lambda: {"com.spa.rules_watchdog": 4321})
    monkeypatch.setattr(self_heal, "_must_be_resident", lambda l: True)


def test_all_alive_with_pending_incident_resolves(heal, monkeypatch):
    # (а) все живы + push_policy держит 'bad' → ровно один «восстановлено»,
    # и он НАЗЫВАЕТ, что было (fingerprint инцидента) и что проверено.
    _guard_no_real_io(monkeypatch)
    _alive_fleet(monkeypatch)
    monkeypatch.setattr(self_heal, "_pending_core_incident", lambda: dict(_PENDING))

    report = self_heal.run_self_heal(dry_run=False)

    assert len(heal.resolves) == 1
    assert "com.spa.daily_cycle" in heal.resolves[0]     # что было
    assert "снова живы" in heal.resolves[0]              # что восстановлено
    assert report["core_agent_down_resolved"] is True
    assert heal.telegrams == []                          # никакого entry-пуша


def test_agent_down_does_not_resolve(heal, monkeypatch):
    # (б) хоть один резидент лежит → resolve НЕ вызван (прогон чинил, снимок
    # доказывает лишь что агент БЫЛ мёртв; резолвит следующий чистый прогон).
    _guard_no_real_io(monkeypatch)
    monkeypatch.setattr(self_heal, "_expected_labels",
                        lambda: ["com.spa.rules_watchdog"])
    monkeypatch.setattr(self_heal, "_loaded_labels", lambda: {})     # лежит
    monkeypatch.setattr(self_heal, "_must_be_resident", lambda l: True)
    monkeypatch.setattr(self_heal, "_pending_core_incident", lambda: dict(_PENDING))

    report = self_heal.run_self_heal(dry_run=False)

    assert heal.resolves == []
    assert "core_agent_down_resolved" not in report


def test_bootstrap_failure_does_not_resolve(heal, monkeypatch):
    # (б') реанимация ПРОВАЛИЛАСЬ → тем более не гасим.
    _guard_no_real_io(monkeypatch)
    monkeypatch.setattr(self_heal, "_expected_labels",
                        lambda: ["com.spa.rules_watchdog"])
    monkeypatch.setattr(self_heal, "_loaded_labels", lambda: {})
    monkeypatch.setattr(self_heal, "_must_be_resident", lambda l: True)
    monkeypatch.setattr(self_heal, "_bootstrap", lambda label: False)
    monkeypatch.setattr(self_heal, "_pending_core_incident", lambda: dict(_PENDING))

    self_heal.run_self_heal(dry_run=False)

    assert heal.resolves == []


def test_open_circuit_breaker_does_not_resolve(heal, monkeypatch):
    # (б'') crash-looper под брейкером = флот НЕ здоров → не гасим.
    _guard_no_real_io(monkeypatch)
    label = "com.spa.flapper"
    monkeypatch.setattr(self_heal, "_expected_labels", lambda: [label])
    monkeypatch.setattr(self_heal, "_loaded_labels", lambda: {})
    monkeypatch.setattr(self_heal, "_must_be_resident", lambda l: True)
    now = time.time()
    monkeypatch.setattr(
        self_heal, "_revival_history",
        lambda: {label: [now - i for i in range(self_heal.MAX_REVIVALS_PER_HOUR)]},
    )
    monkeypatch.setattr(self_heal, "_pending_core_incident", lambda: dict(_PENDING))

    self_heal.run_self_heal(dry_run=False)

    assert heal.resolves == []


def test_empty_launchctl_snapshot_does_not_resolve(heal, monkeypatch):
    # (в) launchctl ничего не ответил (loaded пуст) — «все живы» недоказуемо,
    # даже если по плистам никто не обязан быть резидентом → fail-CLOSED.
    _guard_no_real_io(monkeypatch)
    monkeypatch.setattr(self_heal, "_expected_labels",
                        lambda: ["com.spa.daily_cycle"])
    monkeypatch.setattr(self_heal, "_loaded_labels", lambda: {})     # пусто
    monkeypatch.setattr(self_heal, "_must_be_resident", lambda l: False)  # calendar
    monkeypatch.setattr(self_heal, "_pending_core_incident", lambda: dict(_PENDING))

    report = self_heal.run_self_heal(dry_run=False)

    assert report["healthy"] is True      # idle-calendar сам по себе не болезнь…
    assert heal.resolves == []            # …но доказательства жизни НЕТ → не гасим


def test_no_expected_plists_does_not_resolve(heal, monkeypatch):
    # (в') плисты не видны (expected пуст — ~/Library недоступна?) → не гасим.
    _guard_no_real_io(monkeypatch)
    monkeypatch.setattr(self_heal, "_expected_labels", lambda: [])
    monkeypatch.setattr(self_heal, "_loaded_labels",
                        lambda: {"com.spa.apiserver": 111})
    monkeypatch.setattr(self_heal, "_pending_core_incident", lambda: dict(_PENDING))

    self_heal.run_self_heal(dry_run=False)

    assert heal.resolves == []


def test_unreadable_cycle_age_does_not_resolve(heal, monkeypatch):
    # (в'') возраст цикла нечитаем (None) → свежесть недоказуема → не гасим.
    _guard_no_real_io(monkeypatch)
    _alive_fleet(monkeypatch)
    monkeypatch.setattr(self_heal, "_last_cycle_age_hours", lambda: None)
    monkeypatch.setattr(self_heal, "_pending_core_incident", lambda: dict(_PENDING))

    self_heal.run_self_heal(dry_run=False)

    assert heal.resolves == []


def test_stale_cycle_within_act_window_does_not_resolve(heal, monkeypatch):
    # (в''') цикл 27ч — SLA (26ч) пробит, ACT (28ч) ещё нет: не здоров → не гасим.
    _guard_no_real_io(monkeypatch)
    _alive_fleet(monkeypatch)
    monkeypatch.setattr(self_heal, "_last_cycle_age_hours", lambda: 27.05)
    monkeypatch.setattr(self_heal, "_pending_core_incident", lambda: dict(_PENDING))

    self_heal.run_self_heal(dry_run=False)

    assert heal.resolves == []


def test_no_pending_incident_stays_silent(heal, monkeypatch):
    # Нечего гасить (push_policy не в 'bad') → ни resolve-пуша, ни записи.
    _guard_no_real_io(monkeypatch)
    _alive_fleet(monkeypatch)
    # fixture default: _pending_core_incident → None

    report = self_heal.run_self_heal(dry_run=False)

    assert heal.resolves == []
    assert "core_agent_down_resolved" not in report


def test_dry_run_never_resolves(heal, monkeypatch):
    _guard_no_real_io(monkeypatch)
    _alive_fleet(monkeypatch)
    monkeypatch.setattr(self_heal, "_pending_core_incident", lambda: dict(_PENDING))

    self_heal.run_self_heal(dry_run=True)

    assert heal.resolves == []


def test_resolve_seam_targets_core_agent_down(monkeypatch):
    # Сим напрямую: _resolve_core_agent_down зовёт push_policy.resolve
    # ИМЕННО по ключу core_agent_down (не какой-то другой класс).
    from spa_core.telegram import push_policy
    calls: list[tuple] = []
    monkeypatch.setattr(
        push_policy, "resolve",
        lambda key, title, body="", **k: (calls.append((key, title, body)), True)[1],
    )
    assert self_heal._resolve_core_agent_down("msg") is True
    assert calls == [("core_agent_down", "SPA Self-Heal — агенты восстановлены", "msg")]


def test_watchdog_and_uptime_monitor_never_resolve(monkeypatch):
    # (г) watchdog / uptime_monitor прав гасить НЕ получили: их entry-пути
    # не зовут push_policy.resolve и не передают resolved=True.
    from spa_core.monitoring import uptime_monitor, watchdog
    from spa_core.telegram import push_policy

    resolve_calls: list = []
    push_kwargs: list[dict] = []
    monkeypatch.setattr(
        push_policy, "resolve",
        lambda *a, **k: (resolve_calls.append((a, k)), True)[1],
    )
    monkeypatch.setattr(
        push_policy, "push_critical",
        lambda *a, **k: (push_kwargs.append(k), True)[1],
    )

    watchdog._send_telegram("guardian escalation", dedup_key="wd:fp")
    uptime_monitor._send_agent_alert("com.spa.daily_cycle", 30, None)  # CORE agent

    assert resolve_calls == []                        # никто не гасил
    assert len(push_kwargs) == 2                      # оба ушли entry-путём
    assert all(not k.get("resolved") for k in push_kwargs)


# ===========================================================================
# R6 — telegram_bot BEACON-staleness probe (мандат владельца 2026-08-21:
# бот завис дважды за день, PID жив, long-poll заклинил; единственный признак —
# протухший маячок; владелец дважды перезапускал руками)
# ===========================================================================
def _bot_loaded(monkeypatch, pid=10658):
    monkeypatch.setattr(self_heal, "_loaded_labels",
                        lambda: {"com.spa.telegram_bot": pid})


def test_r6_stale_beacon_live_pid_kickstarts_bot(heal, monkeypatch):
    """Положительный контроль всей проводки: маячок протух при живом PID → kickstart."""
    _guard_no_real_io(monkeypatch)
    _bot_loaded(monkeypatch)
    monkeypatch.setattr(self_heal, "_beacon_age_seconds", lambda: 900.0)  # > 600

    report = self_heal.run_self_heal()

    assert heal.kickstarted == ["com.spa.telegram_bot"]
    assert any("beacon" in a and "telegram_bot" in a for a in report["actions"])


def test_r6_fresh_beacon_no_action(heal, monkeypatch):
    _guard_no_real_io(monkeypatch)
    _bot_loaded(monkeypatch)
    monkeypatch.setattr(self_heal, "_beacon_age_seconds", lambda: 45.0)  # живой виток

    self_heal.run_self_heal()

    assert heal.kickstarted == []


def test_r6_unmeasurable_beacon_no_action(heal, monkeypatch):
    """Нет файла / не читается ⇒ None ⇒ БЕЗ действия. «Не смогли измерить» — не
    доказательство зависания: старый бот без маячка не должен уходить в
    kickstart-петлю (тот же fail-safe, что у R5)."""
    _guard_no_real_io(monkeypatch)
    _bot_loaded(monkeypatch)
    monkeypatch.setattr(self_heal, "_beacon_age_seconds", lambda: None)

    self_heal.run_self_heal()

    assert heal.kickstarted == []


def test_r6_pid_zero_left_to_rule2(heal, monkeypatch):
    """PID 0 — мёртвый сервер, это юрисдикция правила 2 (оно и kickstart'ит).
    R6 по протухшему маячку при PID 0 действовать не должен — иначе один инцидент
    дал бы ДВА kickstart'а за прогон."""
    _guard_no_real_io(monkeypatch)
    _bot_loaded(monkeypatch, pid=0)
    monkeypatch.setattr(self_heal, "_beacon_age_seconds", lambda: 900.0)

    self_heal.run_self_heal()

    # ровно один kickstart — от правила 2 (_SERVERS), не два
    assert heal.kickstarted == ["com.spa.telegram_bot"]


def test_r6_bot_not_loaded_probe_never_read(heal, monkeypatch):
    """Вне Мака / в CI loaded пуст — R6 обязан быть полностью инертен и даже
    НЕ ЧИТАТЬ маячок (гейт по loaded стоит ПЕРВЫМ)."""
    _guard_no_real_io(monkeypatch)

    def _boom():
        raise AssertionError("beacon probe read while bot not loaded")

    monkeypatch.setattr(self_heal, "_beacon_age_seconds", _boom)
    # loaded по умолчанию пуст (фикстура)

    self_heal.run_self_heal()

    assert heal.kickstarted == []


def test_r6_circuit_breaker_suppresses_kickstart_loop(heal, monkeypatch):
    """Заклинивший намертво бот: MAX_REVIVALS_PER_HOUR перезапусков в час уже
    сделано ⇒ предохранитель, НЕ kickstart (иначе петля перезапусков)."""
    import time as _t
    _guard_no_real_io(monkeypatch)
    _bot_loaded(monkeypatch)
    monkeypatch.setattr(self_heal, "_beacon_age_seconds", lambda: 900.0)
    now = _t.time()
    monkeypatch.setattr(
        self_heal, "_revival_history",
        lambda: {self_heal._BOT_STALE_LABEL:
                 [now - 60 * i for i in range(1, self_heal.MAX_REVIVALS_PER_HOUR + 1)]},
    )

    report = self_heal.run_self_heal()

    assert heal.kickstarted == []
    assert any("stale-beacon" in b for b in report["circuit_breakers"])


def test_r6_dry_run_reports_without_acting(heal, monkeypatch):
    _guard_no_real_io(monkeypatch)
    _bot_loaded(monkeypatch)
    monkeypatch.setattr(self_heal, "_beacon_age_seconds", lambda: 900.0)

    report = self_heal.run_self_heal(dry_run=True)

    assert heal.kickstarted == []
    assert any(a.startswith("would kickstart telegram_bot") for a in report["actions"])


def test_r6_beacon_age_reader_units(tmp_path, monkeypatch):
    """Юнит на сам зонд: читает updated_at, наивная отметка = UTC, мусор = None."""
    import datetime as dt
    import json as _json

    monkeypatch.setattr(self_heal, "_DATA", tmp_path)
    p = tmp_path / self_heal._BOT_BEACON_FILE

    # свежая отметка → маленький возраст
    now = dt.datetime.now(dt.timezone.utc)
    p.write_text(_json.dumps({"updated_at": (now - dt.timedelta(seconds=30)).isoformat()}))
    age = self_heal._beacon_age_seconds()
    assert age is not None and 0 <= age < 120

    # мусор → None (не действие)
    p.write_text("{ not json")
    assert self_heal._beacon_age_seconds() is None

    # нет отметки → None
    p.write_text(_json.dumps({"capabilities": ["alert_actions"]}))
    assert self_heal._beacon_age_seconds() is None

    # нет файла → None
    p.unlink()
    assert self_heal._beacon_age_seconds() is None
