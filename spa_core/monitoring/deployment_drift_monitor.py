"""Deployment-drift guard: is the RUNNING code the code we delivered?

Closes the second hop of the delivery chain. The first hop — session → origin —
already has guards (`check_undelivered_work.py`, `check_card_claim.py`, the
orchestrator's step 0a). The second hop — origin → the checkout the agents
actually execute from — had none, and on 2026-08-03 that cost a day of work:
three accepted ADRs (evidence gate, chain caps, honest adapters) sat on
``origin/main`` while the daily cycle kept running a checkout **409 commits
behind on another branch**, still ranking 40 % of the book on a 6.5 % literal and
still holding two positions that the invariants forbid.

The health monitor has a domain called "Code Integrity", which is why the gap
looked covered. It only probes that modules *import* — it answers "does the code
run?", never "is this the code we shipped?". A green check on the wrong question.

Read-only by construction: it NEVER pulls, checks out, or otherwise touches the
working tree. Updating production is an owner decision, not a monitor's.

LLM forbidden. Pure stdlib. Atomic writes.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from spa_core.utils.atomic import atomic_save

log = logging.getLogger("spa.monitoring.deployment_drift")

_REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_FILENAME = "deployment_drift.json"

OK = "OK"
WARNING = "WARNING"
CRITICAL = "CRITICAL"
UNCHECKED = "UNCHECKED"

DEFAULT_REMOTE_REF = "origin/main"

# Paths whose divergence means the RISK LOGIC in production is not the reviewed
# one. Drift here is never cosmetic: it is the difference between the policy an
# ADR accepted and the policy that actually moves the paper book.
MONEY_PATH_PREFIXES = (
    "spa_core/risk/",
    "spa_core/allocator/",
    "spa_core/governance/",
    "spa_core/adapters/",
    "spa_core/paper_trading/cycle_runner.py",
    "spa_core/paper_trading/risk_gate.py",
    "spa_core/paper_trading/cycle_gates.py",
    "spa_core/tuner/",
)


def _is_money_path(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in MONEY_PATH_PREFIXES)



def _content_mismatches(root: Path, ref: str, run) -> tuple[Optional[List[str]], Optional[str]]:
    """Files whose CONTENT on disk differs from ``ref``. Returns ``(paths, error)``.

    Compares blob hashes, not git's index, because the index answers the wrong
    question here. ``git diff <ref>`` is blind to UNTRACKED files: a file-level
    deployment (rsync from a clean checkout) writes files that the stale checkout
    never tracked, and git then reports them as "deleted" — a CRITICAL about code
    that is byte-identical to what was delivered. A guard that cries wolf about a
    correct deployment is worse than no guard: it teaches everyone to ignore it.

    Two subprocess calls regardless of file count: one ``ls-tree`` for the
    delivered hashes, one batched ``hash-object`` for what is on disk.
    """
    ok, listing = run(["ls-tree", "-r", ref], root)
    if not ok:
        return None, "git ls-tree {} failed: {}".format(ref, listing)

    expected: Dict[str, str] = {}
    for line in listing.splitlines():
        # "<mode> <type> <sha>\t<path>"
        head, _, path = line.partition("\t")
        parts = head.split()
        if len(parts) == 3 and parts[1] == "blob" and path:
            expected[path] = parts[2]
    if not expected:
        return None, "ls-tree {} returned no blobs".format(ref)

    paths = sorted(expected)
    on_disk = [p for p in paths if (root / p).is_file()]
    missing = [p for p in paths if p not in set(on_disk)]

    actual: Dict[str, str] = {}
    if on_disk:
        ok, hashes = run(["hash-object", "--stdin-paths"], root, "\n".join(on_disk) + "\n")
        if not ok:
            return None, "git hash-object failed: {}".format(hashes)
        lines = hashes.splitlines()
        if len(lines) != len(on_disk):
            return None, "hash-object returned {} lines for {} paths".format(
                len(lines), len(on_disk))
        actual = dict(zip(on_disk, lines))

    changed = [p for p in on_disk if actual.get(p) != expected[p]]
    return sorted(changed + missing), None


@dataclass
class DriftReport:
    status: str = UNCHECKED
    checked_at: str = ""
    repo_root: str = ""
    branch: Optional[str] = None
    head: Optional[str] = None
    remote_ref: str = DEFAULT_REMOTE_REF
    remote_head: Optional[str] = None
    commits_behind: Optional[int] = None
    commits_ahead: Optional[int] = None
    money_path_files: List[str] = field(default_factory=list)
    other_files: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    unchecked_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def _git(args: List[str], cwd: Path, stdin: Optional[str] = None,
         timeout: float = 60.0) -> tuple[bool, str]:
    """Run a read-only git command. Returns ``(ok, output_or_error)``."""
    try:
        proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                              text=True, timeout=timeout, input=stdin)
    except Exception as exc:  # noqa: BLE001 — git missing / hung / not a repo
        return False, "{}: {}".format(type(exc).__name__, exc)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "").strip()[:300]
    return True, proc.stdout.strip()


def check_deployment_drift(
    repo_root: Optional[Path] = None,
    remote_ref: str = DEFAULT_REMOTE_REF,
    *,
    fetch: bool = True,
    expected_branch: str = "main",
    git_runner: Optional[Callable[[List[str], Path], tuple]] = None,
) -> DriftReport:
    """Compare the checkout that RUNS the code against the delivered ref.

    ``git_runner`` is injectable so tests describe a repository state instead of
    building one — the suite stays offline, deterministic and fast.

    Fail-CLOSED: anything that cannot be determined returns ``UNCHECKED`` with the
    reason. It never returns ``OK`` about a comparison it did not make — that is
    precisely the failure this module exists to prevent.
    """
    root = Path(repo_root) if repo_root else _REPO_ROOT
    run = git_runner or (lambda args, cwd, stdin=None: _git(args, cwd, stdin))
    rep = DriftReport(
        checked_at=datetime.now(timezone.utc).isoformat(),
        repo_root=str(root),
        remote_ref=remote_ref,
    )

    ok, head = run(["rev-parse", "HEAD"], root)
    if not ok:
        rep.unchecked_reason = "git rev-parse HEAD failed: {}".format(head)
        return rep
    rep.head = head[:12]

    ok, branch = run(["rev-parse", "--abbrev-ref", "HEAD"], root)
    rep.branch = branch if ok else None

    if fetch:
        # Fetch updates remote-tracking refs only; it never touches the working
        # tree or the index, so it is safe to run against production.
        ok_fetch, fetch_msg = run(["fetch", "origin", expected_branch, "--quiet"], root)
        if not ok_fetch:
            rep.unchecked_reason = (
                "could not refresh {}: {} — comparison would be against a stale ref"
                .format(remote_ref, fetch_msg)
            )
            return rep

    ok, remote_head = run(["rev-parse", remote_ref], root)
    if not ok:
        rep.unchecked_reason = "git rev-parse {} failed: {}".format(remote_ref, remote_head)
        return rep
    rep.remote_head = remote_head[:12]

    ok, counts = run(["rev-list", "--left-right", "--count",
                      "HEAD...{}".format(remote_ref)], root)
    if ok:
        parts = counts.split()
        if len(parts) == 2:
            try:
                rep.commits_ahead, rep.commits_behind = int(parts[0]), int(parts[1])
            except ValueError:
                pass

    # Content comparison against the delivered ref (see _content_mismatches).
    changed, err = _content_mismatches(root, remote_ref, run)
    if err:
        rep.unchecked_reason = err
        return rep
    rep.money_path_files = sorted(p for p in changed if _is_money_path(p))
    rep.other_files = sorted(p for p in changed if not _is_money_path(p))

    # ── verdict ────────────────────────────────────────────────────────────
    if rep.branch and rep.branch != expected_branch and rep.branch != "HEAD":
        rep.reasons.append(
            "checkout is on branch '{}', not '{}' — delivered work lands on '{}' and "
            "will never appear here".format(rep.branch, expected_branch, expected_branch)
        )

    if rep.money_path_files:
        rep.status = CRITICAL
        rep.reasons.append(
            "{} money-path file(s) differ from {} — the risk logic running in "
            "production is NOT the reviewed one: {}".format(
                len(rep.money_path_files), remote_ref,
                rep.money_path_files[:10] + (["…"] if len(rep.money_path_files) > 10 else []))
        )
    elif rep.other_files:
        rep.status = WARNING
        rep.reasons.append(
            "{} non-money-path file(s) differ from {} — delivered work is not "
            "running here, but no risk logic is affected".format(
                len(rep.other_files), remote_ref)
        )
    elif rep.branch and rep.branch != expected_branch and rep.branch != "HEAD":
        # Content matches today, but the branch guarantees future drift.
        rep.status = WARNING
    else:
        rep.status = OK
        rep.reasons.append("checkout matches {} on every tracked file".format(remote_ref))

    return rep


def run_deployment_drift_monitor(
    data_dir: Optional[Path] = None,
    repo_root: Optional[Path] = None,
    *,
    write: bool = True,
    **kwargs,
) -> dict:
    """Check, persist to ``data/deployment_drift.json``, return the report dict."""
    rep = check_deployment_drift(repo_root=repo_root, **kwargs)
    doc = rep.to_dict()
    doc["monitor"] = "deployment_drift"
    doc["note"] = (
        "Read-only. This monitor never pulls or checks out — updating production "
        "is an owner decision."
    )
    if write:
        ddir = Path(data_dir) if data_dir else (_REPO_ROOT / "data")
        try:
            atomic_save(doc, str(ddir / STATE_FILENAME))
        except Exception as exc:  # noqa: BLE001 — reporting must not break a caller
            log.warning("deployment_drift: could not persist state (%s)", exc)

    if rep.status == CRITICAL:
        log.error("DEPLOYMENT DRIFT (CRITICAL): %s", "; ".join(rep.reasons))
    elif rep.status == WARNING:
        log.warning("DEPLOYMENT DRIFT: %s", "; ".join(rep.reasons))
    elif rep.status == UNCHECKED:
        log.warning("DEPLOYMENT DRIFT UNCHECKED: %s", rep.unchecked_reason)
    else:
        log.info("deployment_drift: %s", "; ".join(rep.reasons))
    return doc


def format_report_text(doc: dict) -> str:
    """Human-readable summary for CLI / Telegram."""
    status = doc.get("status", UNCHECKED)
    icon = {OK: "✅", WARNING: "⚠️", CRITICAL: "🚨", UNCHECKED: "❓"}.get(status, "❓")
    lines = ["{} deployment_drift: {}".format(icon, status),
             "  checkout : {}".format(doc.get("repo_root")),
             "  branch   : {} @ {}".format(doc.get("branch"), doc.get("head")),
             "  delivered: {} @ {}".format(doc.get("remote_ref"), doc.get("remote_head"))]
    if doc.get("commits_behind") is not None:
        lines.append("  behind   : {} commit(s), ahead {}".format(
            doc.get("commits_behind"), doc.get("commits_ahead")))
    if doc.get("unchecked_reason"):
        lines.append("  UNCHECKED: {}".format(doc["unchecked_reason"]))
    for reason in doc.get("reasons", []):
        lines.append("  • {}".format(reason))
    return "\n".join(lines)


def main() -> int:
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description="Deployment drift guard (origin → production)")
    ap.add_argument("--repo-root", default=None, help="checkout to inspect (default: this one)")
    ap.add_argument("--remote-ref", default=DEFAULT_REMOTE_REF)
    ap.add_argument("--expected-branch", default="main")
    ap.add_argument("--no-fetch", action="store_true", help="do not refresh remote refs")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()

    doc = run_deployment_drift_monitor(
        repo_root=Path(args.repo_root) if args.repo_root else None,
        remote_ref=args.remote_ref,
        expected_branch=args.expected_branch,
        fetch=not args.no_fetch,
        write=not args.no_write,
    )
    print(format_report_text(doc))
    # Exit code carries the verdict for launchd/CI: 0 ok, 1 drift, 2 unchecked.
    return {OK: 0, WARNING: 1, CRITICAL: 1, UNCHECKED: 2}.get(doc.get("status"), 2)


if __name__ == "__main__":
    raise SystemExit(main())
