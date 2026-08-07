"""Digest launchd wrappers must report an HONEST exit code (ADR-070 п.11).

Owner decision 2026-08-07: «не ушло — ошибка; agent_health видит».

The defect these tests replay: `scripts/agent_work_digest.sh` (and its retired twin
`agent_morning_digest.sh`) captured the python exit code into `RC`, printed it into the
log — and then ended with an unconditional `exit 0`. launchd therefore recorded
`LastExitStatus=0` for a digest that never reached Telegram, and `agent_health_monitor`
— which classifies precisely on that field — reported the agent OK. The python half was
already honest (`morning_work_digest.main()` returns 1 whenever delivery is not
CONFIRMED), so the whole answer was being thrown away by the last line of the wrapper.

Every test here is a POSITIVE CONTROL: on the pre-fix wrapper (`exit 0` / `cd || exit 0`)
it goes red. The suite deliberately covers BOTH halves of the chain — the wrapper's
propagation AND the python's delivery verdict — because a wrapper that faithfully
propagates the code of a python that lies is no better than the defect it replaced
(«mutate the wiring, not just the parts»).

Time and environment are INPUTS here (sandbox repo + stub interpreter target via the
documented SPA_DIGEST_* overrides), so there are no literal dates and nothing in this file
can rot with the calendar. Production plists set none of those variables; the sandbox log
path keeps the tests off the real /tmp/spa_*_digest.log (a test must never write live
agent state).
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPERS = {
    "work": REPO_ROOT / "scripts" / "agent_work_digest.sh",
    "morning": REPO_ROOT / "scripts" / "agent_morning_digest.sh",
}
DIGEST_PY = REPO_ROOT / "scripts" / "morning_work_digest.py"

# Which wrapper the delivered mode is asserted for. `work` is the LIVE entrypoint
# (com.spa.work_digest.plist names it) and is `100755` on origin — asserting it gives the
# check teeth: strip the bit and this file goes red. `morning` is the RETIRED twin — its plist
# still sits on origin but its label is in `RETIRED_LABELS` and `launchctl list` does not show
# it — and it is `100644` on origin, while the host copy is `755`, which is exactly why
# the session that wrote these tests measured them green and would still have painted CI red
# (git checkout reproduces the ORIGIN mode, the host tree does not). Asserting a bit that
# (a) nothing executes and (b) `push_to_github.py` cannot set — `tree_entry_mode` deliberately
# reuses the remote mode for existing paths so a push can never silently strip an x-bit, which
# also means it can never add one — would be a permanently red lamp with no defect behind it.
# The mode-on-origin gap itself is a finding, not a fact to live with: card
# `agent-task-prava-na-origin-nechem-pochinit-pusher-p`.
EXEC_REQUIRED = {"work": True, "morning": False}


def _sandbox(tmp_path: Path, exit_code: int, *, marker: Path | None = None) -> Path:
    """A fake repo whose scripts/morning_work_digest.py is a stub exiting `exit_code`.

    The stub sits at the EXACT path production uses: if a wrapper is ever rewired to call
    something else, the stub never runs and the wiring assertions below fail — the honest
    exit code of a digest that was never attempted is not the property under test.
    """
    fake = tmp_path / "repo" / "scripts"
    fake.mkdir(parents=True)
    body = "import sys\n"
    if marker is not None:
        body += f"import pathlib; pathlib.Path({str(marker)!r}).write_text('ran')\n"
    body += f"sys.exit({exit_code})\n"
    (fake / "morning_work_digest.py").write_text(body, encoding="utf-8")
    return tmp_path / "repo"


def _run(wrapper: Path, repo: Path, log: Path) -> subprocess.CompletedProcess:
    env = {
        "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME": str(repo),
        "SPA_DIGEST_REPO": str(repo),
        "SPA_DIGEST_PYTHON": sys.executable,
        "SPA_DIGEST_LOG": str(log),
    }
    return subprocess.run(
        ["/bin/bash", str(wrapper)], capture_output=True, text=True, timeout=120, env=env
    )


@pytest.mark.parametrize("name", sorted(WRAPPERS))
def test_wrapper_exists_and_is_executable(name: str) -> None:
    """Mode is part of delivery — a 100644 launchd entrypoint is a dead agent (2026-08-04).

    Asserted for the live entrypoint only; see `EXEC_REQUIRED` for why the retired twin's
    mode is a named finding rather than a green-or-red assertion here.
    """
    wrapper = WRAPPERS[name]
    assert wrapper.is_file(), f"{wrapper} missing"
    if EXEC_REQUIRED[name]:
        assert wrapper.stat().st_mode & 0o111, f"{wrapper} is not executable"


def _live_wrappers() -> set[str]:
    """Wrappers a NON-retired launchd label runs, read from the plists themselves.

    A plist file on disk is not proof of a live agent: `launchd/com.spa.morning_digest.plist`
    still exists on origin while its label sits in `RETIRED_LABELS` and `launchctl list` does
    not show it (the retirement note says the plists may be deleted at leisure). Liveness is
    therefore label-driven, from the SAME frozenset `agent_health_monitor` classifies by —
    not from a second local copy that could drift out of agreement with it.
    """
    from spa_core.monitoring.agent_health_monitor import RETIRED_LABELS

    live: set[str] = set()
    for plist in (REPO_ROOT / "launchd").glob("*.plist"):
        text = plist.read_text(encoding="utf-8")
        label_match = re.search(r"<key>Label</key>\s*<string>([^<]+)</string>", text)
        if label_match is None or label_match.group(1) in RETIRED_LABELS:
            continue
        live.update(name for name, path in WRAPPERS.items() if path.name in text)
    return live


def test_live_entrypoint_is_the_one_whose_mode_is_asserted() -> None:
    """Positive control for the map above: whatever a LIVE label runs must be in EXEC_REQUIRED.

    Without this, `EXEC_REQUIRED` would be a place to quietly park a failing wrapper. Derived
    from the plists, the assertion follows the wiring: revive `com.spa.morning_digest` (drop it
    from RETIRED_LABELS) and this test demands its delivered mode too — which is the moment the
    `100644` on origin stops being a documented finding and becomes a blocker.
    """
    live = _live_wrappers()
    assert live, "no digest wrapper is run by a live launchd label — wiring lost"
    for name in live:
        assert EXEC_REQUIRED[name], (
            f"{WRAPPERS[name].name} is run by a live launchd label but its delivered mode "
            "is not asserted"
        )


@pytest.mark.parametrize("name", sorted(WRAPPERS))
def test_failed_digest_exits_nonzero(tmp_path: Path, name: str) -> None:
    """THE defect: digest did not go out, wrapper said 0, agent_health saw a healthy agent."""
    marker = tmp_path / "ran"
    repo = _sandbox(tmp_path, 1, marker=marker)
    log = tmp_path / "digest.log"
    proc = _run(WRAPPERS[name], repo, log)
    assert marker.is_file(), "the digest script never ran — wiring broken, exit code moot"
    assert proc.returncode == 1, (
        "a digest that was NOT delivered must reach launchd as a failure; "
        f"got rc={proc.returncode} (pre-fix wrappers ended in an unconditional `exit 0`)"
    )


@pytest.mark.parametrize("name", sorted(WRAPPERS))
def test_successful_digest_exits_zero(tmp_path: Path, name: str) -> None:
    """The other direction: honesty must not degenerate into always-alarm."""
    marker = tmp_path / "ran"
    repo = _sandbox(tmp_path, 0, marker=marker)
    log = tmp_path / "digest.log"
    proc = _run(WRAPPERS[name], repo, log)
    assert marker.is_file(), "the digest script never ran"
    assert proc.returncode == 0, f"a delivered digest must exit 0; got {proc.returncode}"


@pytest.mark.parametrize("name", sorted(WRAPPERS))
def test_exit_code_is_the_pythons_own_code(tmp_path: Path, name: str) -> None:
    """Propagated VERBATIM, not merely collapsed to 'nonzero' — the code carries the class
    (1 = logic, 75 = environment, 78 = config), which is how monitoring tells them apart."""
    repo = _sandbox(tmp_path, 3)
    log = tmp_path / "digest.log"
    proc = _run(WRAPPERS[name], repo, log)
    assert proc.returncode == 3, f"expected the python's own 3, got {proc.returncode}"


@pytest.mark.parametrize("name", sorted(WRAPPERS))
def test_unreachable_repo_is_tempfail_not_success(tmp_path: Path, name: str) -> None:
    """`cd "$REPO" || exit 0` reported an UNREACHABLE repo as a delivered digest.

    Not hypothetical: on 2026-08-07 a TCC block made ~/Documents unreadable for ~25 minutes.
    75 = EX_TEMPFAIL, the same code agent_template.sh uses for 'environment not ready'.
    """
    missing = tmp_path / "no-such-repo"
    log = tmp_path / "digest.log"
    proc = _run(WRAPPERS[name], missing, log)
    assert proc.returncode == 75, (
        "an unreachable repo must be EX_TEMPFAIL, never success; "
        f"got rc={proc.returncode} (pre-fix: `cd ... || exit 0`)"
    )


@pytest.mark.parametrize("name", sorted(WRAPPERS))
def test_log_records_the_true_exit_code(tmp_path: Path, name: str) -> None:
    """The log stays the human-readable half of the same answer launchd gets."""
    repo = _sandbox(tmp_path, 1)
    log = tmp_path / "digest.log"
    _run(WRAPPERS[name], repo, log)
    assert log.is_file(), "wrapper wrote no log"
    assert "exit 1" in log.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", sorted(WRAPPERS))
def test_no_unconditional_exit_zero_remains(name: str) -> None:
    """Source-level ratchet: the exact line that caused this defect must not come back.

    Behavioural tests above already cover today's shapes; this one refuses the specific
    reintroduction (a trailing bare `exit 0`) even in a form that dodges them.
    """
    lines = [ln.strip() for ln in WRAPPERS[name].read_text(encoding="utf-8").splitlines()]
    assert "exit 0" not in lines, (
        f"{WRAPPERS[name].name} contains a bare `exit 0` — the digest failure would again "
        "reach launchd as success"
    )


# ── the other half of the chain: the python must not lie to the honest wrapper ──────────

def _load_digest_module():
    spec = importlib.util.spec_from_file_location("spa_morning_work_digest", DIGEST_PY)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "response, delivered",
    [
        ({"ok": True, "result": {}}, True),
        (True, True),
        ({"ok": False, "description": "chat not found"}, False),
        ({"result": {}}, False),          # no `ok` field — NOT measured, not success
        (None, False),                    # fail-safe sender swallowed a network error
        (False, False),
        ("weird", False),                 # unrecognised shape is refused, not rounded up
    ],
)
def test_delivery_verdict_only_confirmed_counts_as_sent(response: object, delivered: bool) -> None:
    """Only Telegram's own ok=true is evidence of delivery; everything else is a failure the
    wrapper is now able to report. Truthiness would bless {'result': ...} and the string."""
    module = _load_digest_module()
    got, reason = module.delivery_verdict(response)
    assert got is delivered, f"{response!r} → delivered={got}, expected {delivered}"
    if not delivered:
        assert reason, "a refusal must carry a verbatim reason for the log"
