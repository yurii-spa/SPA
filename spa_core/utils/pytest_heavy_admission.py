"""pytest plugin — a full-suite run takes a heavy-job lease (ADR-551, spa_core/utils/heavy_job.py).

Engages only when ALL hold: macOS (the production Mac shares CPU/RAM/disk with the paper
schedulers), not a CI runner (`CI=true` / `GITHUB_ACTIONS=true`; `SPA_ENV=ci` alone is NOT CI —
the prescribed local command sets it), not an xdist worker, at least
`heavy_jobs.full_suite_min_tests` tests collected, no lease inherited from a parent process
(`SPA_HEAVY_LEASE`), and `SPA_HEAVY_ADMISSION` not set to `off`. A refusal stops the run before the
first test with the reason (exit code 75, EX_TEMPFAIL) — it never fails a test.
"""
from __future__ import annotations

import os
import sys

import pytest

_LEASE = None


#: Exit code of a refused run. Not pytest's 4 (USAGE_ERROR): a wrapper must be able to tell «the
#: machine is busy, try later» from «the command line is wrong». 75 = EX_TEMPFAIL.
REFUSED_EXIT = 75


def _ci() -> bool:
    """A CI runner announces itself (GitHub Actions sets CI=true and GITHUB_ACTIONS=true). SPA_ENV=ci is
    NOT a CI signal: the prescribed full-suite command sets it on the Mac too — and that is exactly the
    run that has to take a lease (review 2026-10-03)."""
    return os.environ.get("CI", "").lower() == "true" or os.environ.get("GITHUB_ACTIONS", "").lower() == "true"


def _engaged(n_items: int, min_tests: int) -> bool:
    return (sys.platform == "darwin"
            and not _ci()
            and not os.environ.get("PYTEST_XDIST_WORKER")      # a worker is not the job; the controller is
            and os.environ.get("SPA_HEAVY_ADMISSION", "on") != "off"
            and not os.environ.get("SPA_HEAVY_LEASE")
            and n_items >= min_tests)


def pytest_collection_finish(session):
    global _LEASE
    try:
        from spa_core.utils import heavy_job
        policy = heavy_job._policy()
    except Exception:  # noqa: BLE001 — no policy file (e.g. an old tree): admission NOT MEASURED, run proceeds
        return
    if not _engaged(len(session.items), int(policy["full_suite_min_tests"])):
        return
    try:
        _LEASE = heavy_job.admit("full_suite", str(session.config.rootpath), policy=policy,
                                 note=f"{len(session.items)} tests")
    except heavy_job.AdmissionRefused as exc:
        pytest.exit(f"heavy-job admission refused (ADR-551): {exc}. "
                    f"Override deliberately with SPA_HEAVY_ADMISSION=off.", returncode=REFUSED_EXIT)
    os.environ["SPA_HEAVY_LEASE"] = str(_LEASE.file)


def pytest_unconfigure(config):
    global _LEASE
    if _LEASE is not None:
        _LEASE.release()
        _LEASE = None
