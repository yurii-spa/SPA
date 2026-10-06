"""
spa_core/tests/test_retired_but_loaded_visibility.py — ADR-580 C11 (RM-TRUTH-01):
"retired" means unloaded AND recorded. A RETIRED_LABELS agent that launchd STILL has
LOADED is a violation, and it must be VISIBLE, never a silent `continue`.

WHY: A4/REVIEW_1 (2026-10-05, item #12) measured `com.spa.weekly_backup` loaded on the
real host (launchctl list shows it, last exit 1 — the 10-03 backup run FAILED) while
`agent_health_monitor.AgentHealthMonitor.collect()` skipped it outright because its label
is in `RETIRED_LABELS` — so neither the fact that it is still loaded NOR its failing runs
were reported by anything. The owner-approved retirement rationale
(`RETIRED_LABELS["com.spa.weekly_backup"]` comment) says "the owner may fully unload +
delete its plist at leisure" — but nothing ever told the owner it had NOT been unloaded.

Hermetic: every launchctl answer is injected (mirrors test_launchd_disabled_is_not_down.py);
the host is never asked.
"""
from __future__ import annotations

import plistlib
from pathlib import Path

from spa_core.monitoring import agent_health_monitor as ahm

RETIRED = "com.spa.weekly_backup"
assert RETIRED in ahm.RETIRED_LABELS, "test subject must actually be retired"

LIVE = "com.spa.novel_edge_rnd"  # an ordinary, non-retired resident label for contrast


def _calendar_plist(la: Path, label: str) -> None:
    with open(la / f"{label}.plist", "wb") as f:
        plistlib.dump(
            {"Label": label, "ProgramArguments": ["/bin/true"],
             "StartCalendarInterval": {"Hour": 8, "Minute": 0}, "RunAtLoad": False},
            f,
        )


def _collect(tmp_path: Path, launchctl_output: str) -> dict:
    la = tmp_path / "LaunchAgents"
    la.mkdir()
    _calendar_plist(la, RETIRED)
    _calendar_plist(la, LIVE)
    data = tmp_path / "data"
    data.mkdir()
    mon = ahm.AgentHealthMonitor(data_dir=data, launch_agents_dir=la,
                                 launchctl_output=launchctl_output,
                                 launchctl_disabled_output="")
    report = mon.collect()
    return {a["label"]: a for a in report["agents"]}


def test_retired_but_loaded_is_a_visible_warning(tmp_path):
    """The real finding: RETIRED label present in `launchctl list` output (loaded,
    last exit 1 — the measured 10-03 failure) must show up as a WARNING finding, not
    vanish from the report."""
    launchctl_output = f"-\t1\t{RETIRED}\n12345\t0\t{LIVE}\n"
    agents = _collect(tmp_path, launchctl_output)

    assert RETIRED in agents, (
        f"{RETIRED} is loaded (per launchctl) but RETIRED_LABELS made it vanish from the "
        f"report entirely — this is exactly the A4/REVIEW_1 #12 invisibility bug"
    )
    assert agents[RETIRED]["status"] == ahm.WARNING
    assert "retired_but_loaded" in agents[RETIRED]["issue"]
    assert agents[RETIRED]["loaded"] is True


def test_retired_and_actually_unloaded_stays_invisible(tmp_path):
    """The other half of C11: PROPERLY retired (unloaded) must still be silent — this
    finding is specifically about the loaded case, not a reason to start paging on every
    retired label that was correctly torn down."""
    launchctl_output = f"12345\t0\t{LIVE}\n"  # RETIRED absent from launchctl entirely
    agents = _collect(tmp_path, launchctl_output)

    assert RETIRED not in agents, (
        "a retired label that launchd does NOT have loaded must stay invisible — "
        "it is correctly retired, not a violation"
    )
    assert LIVE in agents


def test_retired_but_loaded_does_not_count_as_a_normal_agent(tmp_path):
    """The violation must be visible, but still classified distinctly (CAT_ON_DEMAND,
    not re-derived from the retired plist's own real schedule) — its category is not the
    subject of this finding, only its visibility is."""
    launchctl_output = f"-\t0\t{RETIRED}\n12345\t0\t{LIVE}\n"
    agents = _collect(tmp_path, launchctl_output)
    assert agents[RETIRED]["category"] == ahm.CAT_ON_DEMAND


def test_retired_but_loaded_with_clean_exit_is_still_a_warning(tmp_path):
    """Visibility does not depend on the retired agent currently failing — being loaded
    AT ALL under a superseded label is itself the C11 violation."""
    launchctl_output = f"-\t0\t{RETIRED}\n12345\t0\t{LIVE}\n"
    agents = _collect(tmp_path, launchctl_output)
    assert agents[RETIRED]["status"] == ahm.WARNING
    assert agents[RETIRED]["last_exit"] == 0
