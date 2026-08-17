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
    # ADR-070 п.13: у self_heal БОЛЬШЕ НЕТ прав гасить `core_agent_down`, поэтому
    # own-28-овых сим (`_pending_core_incident` / `_resolve_core_agent_down`)
    # здесь больше нет. Вместо них — ЛОВУШКА на настоящий канал гашения: любой
    # вызов `push_policy.resolve` из self_heal записывается в `h.resolves`, и
    # каждый тест этого файла молча проверяет, что список пуст (см.
    # `test_self_heal_never_resolves_in_any_scenario`). Ловушка герметична —
    # живой push_state.json не трогается ни в одном сценарии.
    from spa_core.telegram import push_policy as _pp
    monkeypatch.setattr(
        _pp, "resolve",
        lambda key, title, body="", **kw: (h.resolves.append((key, body)), True)[1],
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
    # FIXTURE STRENGTHENED (wake-storm fail-OPEN card, 2026-08-17): the fleet observations are
    # now pinned to MEASURED values. This test is about the cycle SLA, but it used to inherit
    # the fixture defaults `_expected_labels() == []` (no plists visible) — which `healthy` now
    # correctly refuses to call healthy, because nothing was measured. The subject of the test
    # is unchanged; only the parts it never meant to leave unmeasured are now supplied.
    monkeypatch.setattr(self_heal, "_expected_labels", lambda: ["com.spa.rules_watchdog"])
    monkeypatch.setattr(self_heal, "_loaded_labels", lambda: {"com.spa.rules_watchdog": 4321})
    monkeypatch.setattr(self_heal, "_must_be_resident", lambda l: True)
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
# ADR-070 п.13 (решение владельца 2026-08-07) — self_heal БОЛЬШЕ НЕ ГАСИТ
# `core_agent_down`.
# ---------------------------------------------------------------------------
# ЧТО ИЗМЕНИЛОСЬ И ПОЧЕМУ (инвариант 16 CLAUDE.md — обоснование в теле правки).
# Раньше здесь стоял блок own-28: «финальное ✅ восстановлено даёт ТОЛЬКО
# self_heal, по одной своей чистой проверке». Владелец это решение ЗАМЕНИЛ:
# гаситель — `agent_health`, и ему нужны ДВА ЧИСТЫХ СНИМКА ПОДРЯД
# («консервативнее рекомендации — выбор владельца», ADR-070 п.13).
#
# Замер, объясняющий выбор: self_heal ходит раз в 300 с
# (`scripts/com.spa.self_heal.plist`), agent_health — раз в 3600 с. Гашение по
# одной чистой проверке закрывало инцидент через пять минут ТЕМ ЖЕ агентом,
# который его и чинил, — раньше, чем это видел хоть один часовой снимок пульса,
# и раньше, чем `push_policy` успевал ПОВТОРИТЬ недоставленную входную тревогу
# (ветка `resolved` в `_push_critical_impl` смотрит только на `state == "bad"` и
# НЕ смотрит на `entry_pushed`).
#
# Поэтому семь тестов own-28 «в таком-то сценарии self_heal НЕ гасит» здесь
# не удалены, а СХЛОПНУТЫ в одно более сильное утверждение: self_heal не гасит
# НИ В ОДНОМ сценарии, включая тот единственный, в котором он раньше гасил.
# Первый тест — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: на нефикшеном коде он красный (там
# resolve происходит). Права на ВХОД остались и проверяются ниже — иначе мы
# заменили бы «гасит слишком рано» на «не тревожит вовсе».
# ===========================================================================
def _alive_fleet(monkeypatch):
    """One residency-required agent, loaded and alive; cycle fresh."""
    monkeypatch.setattr(self_heal, "_expected_labels",
                        lambda: ["com.spa.rules_watchdog"])
    monkeypatch.setattr(self_heal, "_loaded_labels",
                        lambda: {"com.spa.rules_watchdog": 4321})
    monkeypatch.setattr(self_heal, "_must_be_resident", lambda l: True)


def test_clean_run_no_longer_resolves_core_agent_down(heal, monkeypatch):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: ровно тот сценарий, в котором own-28 гасил.

    Все резиденты живы, цикл свежий, прогон ничего не чинил — до ADR-070 п.13
    здесь уходило «✅ восстановлено» и в отчёт писалось
    `core_agent_down_resolved`. Теперь — ни того, ни другого: право гасить
    принадлежит agent_health.
    """
    _guard_no_real_io(monkeypatch)
    _alive_fleet(monkeypatch)

    report = self_heal.run_self_heal(dry_run=False)

    assert heal.resolves == []
    assert "core_agent_down_resolved" not in report


@pytest.mark.parametrize("scenario", [
    "alive_fleet",          # (а) всё хорошо — единственный случай, где гасили
    "agent_down",           # (б) резидент лежит
    "bootstrap_failed",     # (б') реанимация провалилась
    "empty_launchctl",      # (в) launchctl промолчал
    "no_plists",            # (в') плисты не видны
    "unreadable_cycle_age",  # (в'') возраст цикла нечитаем
    "stale_cycle",          # (в''') цикл протух
])
def test_self_heal_never_resolves_in_any_scenario(heal, monkeypatch, scenario):
    """Ни один сценарий self_heal не зовёт `push_policy.resolve`.

    Сильнее семи прежних отдельных «не гасит»: утверждение теперь не «в этом
    состоянии не гасим», а «канала гашения у этого модуля нет вовсе».
    """
    _guard_no_real_io(monkeypatch)
    if scenario == "alive_fleet":
        _alive_fleet(monkeypatch)
    elif scenario == "agent_down":
        monkeypatch.setattr(self_heal, "_expected_labels",
                            lambda: ["com.spa.rules_watchdog"])
        monkeypatch.setattr(self_heal, "_loaded_labels", lambda: {})
        monkeypatch.setattr(self_heal, "_must_be_resident", lambda l: True)
    elif scenario == "bootstrap_failed":
        monkeypatch.setattr(self_heal, "_expected_labels",
                            lambda: ["com.spa.rules_watchdog"])
        monkeypatch.setattr(self_heal, "_loaded_labels", lambda: {})
        monkeypatch.setattr(self_heal, "_must_be_resident", lambda l: True)
        monkeypatch.setattr(self_heal, "_bootstrap", lambda label: False)
    elif scenario == "empty_launchctl":
        monkeypatch.setattr(self_heal, "_expected_labels",
                            lambda: ["com.spa.daily_cycle"])
        monkeypatch.setattr(self_heal, "_loaded_labels", lambda: {})
        monkeypatch.setattr(self_heal, "_must_be_resident", lambda l: False)
    elif scenario == "no_plists":
        monkeypatch.setattr(self_heal, "_expected_labels", lambda: [])
        monkeypatch.setattr(self_heal, "_loaded_labels",
                            lambda: {"com.spa.apiserver": 111})
    elif scenario == "unreadable_cycle_age":
        _alive_fleet(monkeypatch)
        monkeypatch.setattr(self_heal, "_last_cycle_age_hours", lambda: None)
    elif scenario == "stale_cycle":
        _alive_fleet(monkeypatch)
        monkeypatch.setattr(self_heal, "_last_cycle_age_hours", lambda: 27.05)

    report = self_heal.run_self_heal(dry_run=False)

    assert heal.resolves == []
    assert "core_agent_down_resolved" not in report


def test_self_heal_module_has_no_resolve_seam():
    """Храповик: сами симы гашения из модуля убраны, а не оставлены спящими.

    Оставленный «на всякий случай» `_resolve_core_agent_down` — это одна строка
    вызова до возврата аварии; отсутствие имени делает возврат заметным в диффе.
    """
    assert not hasattr(self_heal, "_resolve_core_agent_down")
    assert not hasattr(self_heal, "_pending_core_incident")


def test_entry_rights_survive_the_authority_move(heal, monkeypatch):
    """Обратный контроль: отобрано ПРАВО ГАСИТЬ, а не право ТРЕВОЖИТЬ.

    Иначе «починка» превратила бы раннее гашение в вечное молчание.
    """
    _guard_no_real_io(monkeypatch)
    monkeypatch.setattr(self_heal, "_expected_labels",
                        lambda: ["com.spa.rtmr_sense"])
    monkeypatch.setattr(self_heal, "_loaded_labels", lambda: {})
    monkeypatch.setattr(self_heal, "_must_be_resident", lambda l: True)

    self_heal.run_self_heal(dry_run=False)

    assert heal.telegrams and "com.spa.rtmr_sense" in heal.telegrams[0]
    assert heal.resolves == []


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
# WAKE-STORM FAIL-OPEN (card `agent-wake-storm-fail-open-monitors`, замер 2026-08-04)
# ---------------------------------------------------------------------------
# On the 04.08 wake storm 39 agents died and the monitors reported «всё хорошо». The class is
# always the same: a monitor publishes a verdict about a measurement it never made. The sibling
# `watchdog.py` was hardened against exactly this (`_loaded_labels() -> None` for "unmeasured");
# self_heal — which ACTS on the same reading and guards the money path — was left out of it.
#
# Every test below is a POSITIVE CONTROL: it REDS on the unfixed module, where `_loaded_labels()`
# swallowed launchctl failures into `{}` and `healthy` was computed without ever asking whether
# anything had been measured at all.
#
# No `chmod` anywhere: this suite also runs as root, where permission bits are ignored, so an
# impossible write is built structurally (a destination directory that does not exist).
# ===========================================================================
# The production `_save`, captured at import time — the `heal` fixture replaces the module
# attribute with a no-op, and the publication tests need the real one back.
_SAVE = self_heal._save


class _FakeProc:
    def __init__(self, stdout: str = "", returncode: int = 0):
        self.stdout = stdout
        self.returncode = returncode


def _raise(*_a, **_k):
    raise OSError("launchctl could not be run")


def test_loaded_labels_returns_none_when_launchctl_raises(monkeypatch):
    monkeypatch.setattr(self_heal, "_run", _raise)
    assert self_heal._loaded_labels() is None      # NOT {} — "unknown" is not "nothing loaded"


def test_loaded_labels_returns_none_on_a_nonzero_exit(monkeypatch):
    monkeypatch.setattr(self_heal, "_run", lambda a: _FakeProc("", 1))
    assert self_heal._loaded_labels() is None


def test_loaded_labels_returns_none_on_unparseable_output(monkeypatch):
    monkeypatch.setattr(self_heal, "_run", lambda a: _FakeProc("Could not connect to launchd\n", 0))
    assert self_heal._loaded_labels() is None


def test_measured_launchd_without_our_agents_is_empty_not_unmeasured(monkeypatch):
    # The other direction: a launchd that ANSWERED but holds nothing of ours is a real
    # measurement ({}), so a real total outage stays actionable.
    monkeypatch.setattr(
        self_heal, "_run",
        lambda a: _FakeProc("PID\tStatus\tLabel\n123\t0\tcom.apple.something\n", 0),
    )
    assert self_heal._loaded_labels() == {}


def test_loaded_labels_parses_a_normal_listing(monkeypatch):
    monkeypatch.setattr(
        self_heal, "_run",
        lambda a: _FakeProc("42\t0\tcom.spa.apiserver\n-\t0\tcom.spa.daily_cycle\n", 0),
    )
    assert self_heal._loaded_labels() == {"com.spa.apiserver": 42, "com.spa.daily_cycle": 0}


def test_unmeasured_launchd_is_not_reported_healthy(heal, monkeypatch):
    # THE fail-OPEN, minimal form: launchd unreadable AND ~/Library unreadable — the run measured
    # NOTHING and still published healthy:true (agent_health.json said 69/69 the same morning).
    _guard_no_real_io(monkeypatch)
    monkeypatch.setattr(self_heal, "_loaded_labels", lambda: None)

    report = self_heal.run_self_heal(dry_run=False)

    assert report["healthy"] is False
    assert report["launchctl_measured"] is False
    assert report["loaded"] is None                        # never a fabricated count
    assert any("launchctl" in u for u in report["unchecked"])


def test_unmeasured_launchd_takes_no_launchd_action(heal, monkeypatch):
    # A resident agent "missing" from an unmeasured launchd is not missing — it is unknown, and
    # every remedy is a launchctl call against that same unmeasured launchd.
    _guard_no_real_io(monkeypatch)
    monkeypatch.setattr(self_heal, "_expected_labels", lambda: ["com.spa.rules_watchdog"])
    monkeypatch.setattr(self_heal, "_loaded_labels", lambda: None)
    monkeypatch.setattr(self_heal, "_must_be_resident", lambda l: True)

    report = self_heal.run_self_heal(dry_run=False)

    assert heal.bootstrapped == []                          # nothing acted on
    assert report["actions"] == [] and report["failures"] == []
    assert report["missing_resident"] == []                 # nor a "these are dead" claim
    assert report["healthy"] is False                       # …and silence is not health


def test_measured_empty_launchd_still_revives(heal, monkeypatch):
    # Control: the honesty fix must not disarm the agent. A MEASURED-empty launchd is a real
    # outage and the resident agent is still revived.
    _guard_no_real_io(monkeypatch)
    monkeypatch.setattr(self_heal, "_expected_labels", lambda: ["com.spa.rules_watchdog"])
    monkeypatch.setattr(self_heal, "_loaded_labels", lambda: {})
    monkeypatch.setattr(self_heal, "_must_be_resident", lambda l: True)

    report = self_heal.run_self_heal(dry_run=False)

    assert heal.bootstrapped == ["com.spa.rules_watchdog"]
    assert report["launchctl_measured"] is True
    assert report["missing_resident"] == ["com.spa.rules_watchdog"]


def test_invisible_plists_cannot_be_healthy(heal, monkeypatch):
    # `_expected_labels() == []` means BOTH "nothing installed" and "~/Library unreadable", so it
    # is not evidence that there is nothing to guard. The module's own resolve path already
    # refused to trust it; `healthy` did not.
    _guard_no_real_io(monkeypatch)
    monkeypatch.setattr(self_heal, "_expected_labels", lambda: [])
    monkeypatch.setattr(self_heal, "_loaded_labels", lambda: {"com.spa.apiserver": 111})

    report = self_heal.run_self_heal(dry_run=False)

    assert report["healthy"] is False
    assert any("плист" in u for u in report["unchecked"])


def test_unreadable_cycle_age_cannot_be_healthy(heal, monkeypatch):
    # `cycle_stale: false` next to `cycle_age_h: null` means "not measured", not "within SLA" —
    # and the daily cycle is the money path this agent exists to guard.
    _guard_no_real_io(monkeypatch)
    monkeypatch.setattr(self_heal, "_expected_labels", lambda: ["com.spa.rules_watchdog"])
    monkeypatch.setattr(self_heal, "_loaded_labels", lambda: {"com.spa.rules_watchdog": 1})
    monkeypatch.setattr(self_heal, "_must_be_resident", lambda l: True)
    monkeypatch.setattr(self_heal, "_last_cycle_age_hours", lambda: None)

    report = self_heal.run_self_heal(dry_run=False)

    assert report["cycle_age_h"] is None
    assert report["cycle_stale"] is False        # unchanged: the THRESHOLD was not breached…
    assert report["healthy"] is False            # …because it was never evaluated
    assert any("цикл" in u for u in report["unchecked"])


def test_a_fully_measured_clean_run_is_still_healthy(heal, monkeypatch):
    # The indispensable other direction: every input measured and fine ⇒ healthy stays True.
    # A permanently-red monitor is the same lie inverted, and would teach everyone to ignore it.
    _guard_no_real_io(monkeypatch)
    monkeypatch.setattr(self_heal, "_expected_labels", lambda: ["com.spa.rules_watchdog"])
    monkeypatch.setattr(self_heal, "_loaded_labels", lambda: {"com.spa.rules_watchdog": 4321})
    monkeypatch.setattr(self_heal, "_must_be_resident", lambda l: True)
    monkeypatch.setattr(self_heal, "_last_cycle_age_hours", lambda: 2.0)

    report = self_heal.run_self_heal(dry_run=False)

    assert report["unchecked"] == []
    assert report["healthy"] is True


# ── a verdict that was never written must not look like a passed check ───────
def test_unpublishable_verdict_is_reported_and_exits_nonzero(heal, monkeypatch, tmp_path):
    """`_save` swallowed every write failure and the process exited 0 regardless, so a broken
    disk left the PREVIOUS (possibly green) status file standing as the current verdict."""
    _guard_no_real_io(monkeypatch)
    monkeypatch.setattr(self_heal, "_DATA", tmp_path)                     # tmp only, never live data/
    monkeypatch.setattr(self_heal, "_STATUS", tmp_path / "nonexistent_dir" / "self_heal_status.json")
    monkeypatch.setattr(self_heal, "_save", _SAVE)                        # real save, impossible target

    report = self_heal.run_self_heal(dry_run=False)

    assert report["published"] is False
    assert self_heal._exit_code(report) == 2      # launchd/agent_health can SEE the failure


def test_a_published_verdict_exits_zero(heal, monkeypatch, tmp_path):
    _guard_no_real_io(monkeypatch)
    monkeypatch.setattr(self_heal, "_DATA", tmp_path)
    monkeypatch.setattr(self_heal, "_STATUS", tmp_path / "self_heal_status.json")
    monkeypatch.setattr(self_heal, "_save", _SAVE)

    report = self_heal.run_self_heal(dry_run=False)

    assert report["published"] is True
    assert (tmp_path / "self_heal_status.json").exists()
    assert self_heal._exit_code(report) == 0
