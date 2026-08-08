"""Deployment acceptance — can the fleet still START after a change?

Every test here is a positive control for a failure that actually happened on
2026-08-04 and that every existing guard missed for five hours:

* modes stripped from 67 of 69 entrypoints → launchd exit 126, fleet dead;
* a partial file copy → a module importing a dependency the tree lacked;
* the daily cycle silently not running, noticed only when a human asked.

Offline and hermetic: plists, scripts and artifacts are built in ``tmp_path``,
imports are injected. Nothing touches the real fleet.
"""
from __future__ import annotations

import os
import plistlib
import time
from pathlib import Path

import pytest

from spa_core.monitoring.deployment_acceptance import (
    CRITICAL,
    OK,
    STATE_FILENAME,
    WARNING,
    check_entrypoints,
    check_imports,
    check_scheduled_artifacts,
    run_acceptance,
)


def _fleet(tmp_path: Path, modes) -> tuple:
    """Build a fake launchd fleet; ``modes`` is one octal mode per agent."""
    agents, scripts = tmp_path / "agents", tmp_path / "scripts"
    agents.mkdir(exist_ok=True)
    scripts.mkdir(exist_ok=True)
    for i, mode in enumerate(modes):
        s = scripts / f"agent_{i}.sh"
        s.write_text("#!/bin/bash\ntrue\n", encoding="utf-8")
        os.chmod(s, mode)
        (agents / f"com.spa.a{i}.plist").write_bytes(
            plistlib.dumps({"Label": f"com.spa.a{i}",
                            "ProgramArguments": ["/bin/bash", str(s)]}))
    return agents, scripts


def _artifacts(tmp_path: Path, ages_hours: dict) -> Path:
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    now = time.time()
    for name, age in ages_hours.items():
        f = data / name
        f.write_text("{}", encoding="utf-8")
        os.utime(f, (now - age * 3600, now - age * 3600))
    return data


FRESH = {"current_positions.json": 1.0, "adapter_status.json": 1.0, "agent_health.json": 1.0}


# ── the 2026-08-04 failure ──────────────────────────────────────────────────


def test_stripped_exec_bit_is_caught_immediately(tmp_path: Path) -> None:
    """THE failure: rsync applied origin's modes and launchd died with 126.

    deployment_drift stayed green (content matched), agent_health could only
    notice hours later. This check sees it before anything is scheduled.
    """
    agents, _ = _fleet(tmp_path, [0o755, 0o644, 0o644])
    broken = check_entrypoints(agents)
    assert [b["label"] for b in broken] == ["com.spa.a1", "com.spa.a2"]
    assert all("126" in b["problem"] for b in broken)


def test_verdict_is_critical_when_any_entrypoint_is_dead(tmp_path: Path) -> None:
    agents, _ = _fleet(tmp_path, [0o755, 0o644])
    doc = run_acceptance(agent_dir=agents, data_dir=_artifacts(tmp_path, FRESH),
                         modules=(), write=False)
    assert doc["status"] == CRITICAL
    assert "DEAD" in doc["reasons"][0]


def test_missing_entrypoint_is_as_bad_as_a_non_executable_one(tmp_path: Path) -> None:
    agents, scripts = _fleet(tmp_path, [0o755])
    (scripts / "agent_0.sh").unlink()
    assert check_entrypoints(agents)[0]["problem"] == "entrypoint missing"


def test_healthy_fleet_passes(tmp_path: Path) -> None:
    agents, _ = _fleet(tmp_path, [0o755, 0o755, 0o755])
    doc = run_acceptance(agent_dir=agents, data_dir=_artifacts(tmp_path, FRESH),
                         modules=(), write=False)
    assert doc["status"] == OK


# ── the partial-copy failure ────────────────────────────────────────────────


def test_broken_import_is_critical(tmp_path: Path) -> None:
    """Copying one file between tree versions left it importing a module the
    tree did not have — the whole adapters package then failed to import."""
    agents, _ = _fleet(tmp_path, [0o755])
    failing = {"spa_core.adapters": (False, "ModuleNotFoundError: spa_core.utils.retry_backoff")}
    doc = run_acceptance(
        agent_dir=agents, data_dir=_artifacts(tmp_path, FRESH),
        modules=("spa_core.adapters",),
        import_runner=lambda m: failing.get(m, (True, "")), write=False)
    assert doc["status"] == CRITICAL
    assert doc["imports_failed"][0]["module"] == "spa_core.adapters"


def test_imports_are_checked_in_a_separate_process() -> None:
    """In-process would answer about memory, not about the tree on disk."""
    seen = []
    check_imports(("a.b",), runner=lambda m: (seen.append(m), (True, ""))[1])
    assert seen == ["a.b"]


# ── the silently-skipped job ────────────────────────────────────────────────


def test_overdue_artifact_means_the_job_did_not_run(tmp_path: Path) -> None:
    """The cycle skipped 06:00 and only a human noticed, three hours later."""
    data = _artifacts(tmp_path, {"current_positions.json": 31.0,
                                 "adapter_status.json": 1.0, "agent_health.json": 1.0})
    overdue = check_scheduled_artifacts(data)
    assert [o["artifact"] for o in overdue] == ["current_positions.json"]
    assert "did not run" in overdue[0]["problem"]


def test_never_produced_artifact_is_overdue_not_exempt(tmp_path: Path) -> None:
    data = _artifacts(tmp_path, {"adapter_status.json": 1.0, "agent_health.json": 1.0})
    assert any(o["problem"] == "never produced" for o in check_scheduled_artifacts(data))


def test_overdue_artifact_alone_is_a_warning_not_critical(tmp_path: Path) -> None:
    """A late job is serious; a fleet that cannot start is worse. Keep them apart."""
    agents, _ = _fleet(tmp_path, [0o755])
    data = _artifacts(tmp_path, {"current_positions.json": 99.0,
                                 "adapter_status.json": 1.0, "agent_health.json": 1.0})
    assert run_acceptance(agent_dir=agents, data_dir=data, modules=(),
                          write=False)["status"] == WARNING


# ── fail-CLOSED ─────────────────────────────────────────────────────────────


def test_finding_no_entrypoints_is_critical_not_clean(tmp_path: Path) -> None:
    """An empty result means the check looked in the wrong place and verified
    nothing — reporting OK there is how a guard becomes decorative."""
    empty = tmp_path / "nowhere"
    empty.mkdir()
    doc = run_acceptance(agent_dir=empty, data_dir=_artifacts(tmp_path, FRESH),
                         modules=(), write=False)
    assert doc["status"] == CRITICAL
    assert "nothing was actually verified" in doc["reasons"][-1]


def test_unreadable_plist_is_reported_not_skipped(tmp_path: Path) -> None:
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "com.spa.broken.plist").write_bytes(b"not a plist")
    assert "plist unreadable" in check_entrypoints(agents)[0]["problem"]


def test_state_file_names_what_it_does_not_verify(tmp_path: Path) -> None:
    """Three guards, three questions. The artifact says so, so nobody assumes
    a green acceptance means the code is also the delivered version."""
    agents, _ = _fleet(tmp_path, [0o755])
    doc = run_acceptance(agent_dir=agents, data_dir=_artifacts(tmp_path, FRESH),
                         modules=(), write=True)
    import json
    on_disk = json.loads((tmp_path / "data" / STATE_FILENAME).read_text(encoding="utf-8"))
    assert on_disk == doc
    assert "deployment_drift" in doc["note"] and "agent_health" in doc["note"]


def test_slo_matches_the_producer_rhythm_for_daily_artifacts():
    """SLO суточного артефакта не может быть короче суток.

    Измерено 2026-08-07: adapter_status.json имел SLO 12ч, а пересобирается
    дневным циклом раз в 24ч — тревога срабатывала КАЖДЫЙ день во второй
    половине суток, гарантированно и без повода. Приёмка сообщала «работа не
    запускалась», хотя цикл отработал штатно.

    Сторож, который кричит по расписанию, перестаёт читаться — и на его фоне
    теряется настоящая просрочка. Это тот же класс, что ложное «всё хорошо»,
    только вывернутый наизнанку.
    """
    from spa_core.monitoring.deployment_acceptance import SCHEDULED_ARTIFACTS

    for artifact in ("current_positions.json", "adapter_status.json"):
        slo = SCHEDULED_ARTIFACTS[artifact]
        assert slo >= 24.0, (
            f"{artifact} производит дневной цикл (24ч), а SLO={slo}ч — "
            f"тревога будет срабатывать каждый день без повода"
        )


def test_artifacts_of_the_same_producer_share_their_slo():
    """Два артефакта одного производителя не могут иметь разный SLO без причины.

    Расхождение означает, что один из них назначен наугад — и именно так
    adapter_status.json получил 12ч рядом с 30ч у соседа по циклу.
    """
    from spa_core.monitoring.deployment_acceptance import SCHEDULED_ARTIFACTS

    daily_cycle = ("current_positions.json", "adapter_status.json")
    slos = {SCHEDULED_ARTIFACTS[a] for a in daily_cycle}
    assert len(slos) == 1, f"артефакты дневного цикла разошлись по SLO: {slos}"


# ── schedule reading: how often does this job actually fire? ────────────────
#
# Added 2026-08-08 for `deployment_drift`, which needs to know whether the daily
# code sync can deliver a drifted entrypoint before the agent next runs. Getting
# this wrong in the "rarely" direction hides the drift, so every ambiguous case
# below must resolve to None (fail-CLOSED) rather than to a large number.


def test_start_interval_is_the_schedule():
    from spa_core.monitoring.deployment_acceptance import _schedule_interval_sec

    assert _schedule_interval_sec({"StartInterval": 3600}) == 3600.0


def test_keepalive_job_is_the_most_urgent_schedule_there_is():
    """Restarted the moment it exits: drift takes effect immediately."""
    from spa_core.monitoring.deployment_acceptance import _schedule_interval_sec

    assert _schedule_interval_sec({"KeepAlive": True}) == 0.0


@pytest.mark.parametrize("spec,expected", [
    ({"Hour": 8, "Minute": 0}, 86400.0),              # daily at 08:00
    ({"Minute": 30}, 3600.0),                         # every hour at :30
    ({}, 60.0),                                       # every minute
    ({"Weekday": 1, "Hour": 3}, 7 * 86400.0),         # weekly
    ({"Day": 1, "Hour": 3}, 30 * 86400.0),            # monthly
])
def test_calendar_interval_uses_the_coarsest_pinned_field(spec, expected):
    from spa_core.monitoring.deployment_acceptance import _schedule_interval_sec

    assert _schedule_interval_sec({"StartCalendarInterval": spec}) == expected


def test_several_calendar_entries_fire_that_many_times_per_period():
    """Two daily entries = twice a day. Reporting 86400 here would round toward
    "rare" and let a drifted entrypoint pass as self-healing."""
    from spa_core.monitoring.deployment_acceptance import _schedule_interval_sec

    twice_daily = [{"Hour": 8, "Minute": 0}, {"Hour": 20, "Minute": 0}]
    assert _schedule_interval_sec({"StartCalendarInterval": twice_daily}) == 43200.0


@pytest.mark.parametrize("doc", [
    {},                                               # RunAtLoad only / unscheduled
    {"StartInterval": 0},                             # not a schedule
    {"StartInterval": "hourly"},                      # wrong type
    {"StartCalendarInterval": []},                    # empty
    {"StartCalendarInterval": ["not-a-dict"]},        # malformed
])
def test_unreadable_schedule_is_none_never_a_guess(doc):
    """None is the honest answer, and callers treat it as urgent. A guess here
    would be indistinguishable from a measurement downstream."""
    from spa_core.monitoring.deployment_acceptance import _schedule_interval_sec

    assert _schedule_interval_sec(doc) is None


def test_entrypoint_listing_carries_the_schedule(tmp_path: Path):
    """The drift guard reads this field; it must survive the plist round-trip."""
    from spa_core.monitoring.deployment_acceptance import _entrypoints_from_plists

    agents, scripts = tmp_path / "agents", tmp_path / "scripts"
    agents.mkdir()
    scripts.mkdir()
    script = scripts / "agent_orchestrator.sh"
    script.write_text("#!/bin/bash\n", encoding="utf-8")
    plistlib.dump(
        {"Label": "com.spa.orchestrator",
         "ProgramArguments": ["/bin/bash", str(script)],
         "StartInterval": 3600},
        open(agents / "com.spa.orchestrator.plist", "wb"))

    entries = _entrypoints_from_plists(agents)
    assert entries == [{"label": "com.spa.orchestrator", "script": str(script),
                        "interval_sec": 3600.0, "problem": None}]


def test_unreadable_plist_still_reports_the_schedule_field(tmp_path: Path):
    """A broken plist must not simply lack the key the caller reads — that
    turns "unreadable" into a KeyError somewhere far from here."""
    from spa_core.monitoring.deployment_acceptance import _entrypoints_from_plists

    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "com.spa.broken.plist").write_text("not a plist", encoding="utf-8")

    entries = _entrypoints_from_plists(agents)
    assert len(entries) == 1
    assert entries[0]["interval_sec"] is None
    assert "unreadable" in entries[0]["problem"]
