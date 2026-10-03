"""spa_core/utils/heavy_job.py — admission for heavy development jobs (ADR-551).

A heavy job (a full pytest suite, a mutation run, a headless browser matrix) takes a LEASE before it
starts. The lease is refused — loudly, with the reason — when:

* too many jobs of the same kind already hold live leases (``heavy_jobs.max_concurrent``);
* another LIVE job already holds the same working tree (two workers never mutate one tree);
* free disk is below ``heavy_jobs.min_free_disk_gb``;
* kernel memory pressure is at ``heavy_jobs.refuse_at_pressure_level``.

A granted lease lowers the job's own CPU priority (``nice``) — children inherit it — so a test
shard cannot starve the paper schedulers (``architecture/resource_policy.json``, CRITICAL class).

Leases are small JSON files in ``heavy_jobs.registry_dir`` (outside every worktree, shared by all
of them). A lease whose pid is dead is stale and does not count — a crashed job cannot block the
fleet. Nothing here kills anything.

Why: docs/audits/p0-ci-resource-admission.md — two concurrent full runs drove free memory to 0.1 GB
and six jobs were killed; the previous epic's six parallel worktree shards ran the disk out.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

REPO = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO / "architecture" / "resource_policy.json"
GB = 1024 ** 3


class AdmissionRefused(RuntimeError):
    """A heavy job may not start now; the message names why and who holds what."""


def _policy(path: Path = POLICY_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))["heavy_jobs"]


def pid_alive(pid: int) -> bool:
    if pid <= 0:                       # os.kill(0, …) signals the process GROUP and «succeeds»
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def start_time(pid: int) -> Optional[str]:
    """The process's start time as the OS reports it — the lease's identity together with the pid,
    so a reused pid is not mistaken for the original holder (review 2026-10-03)."""
    try:
        r = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() or None


def _pressure_level() -> Optional[int]:
    try:
        out = subprocess.run(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"],
                             capture_output=True, text=True, timeout=5)
        return int(out.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def registry(policy: dict) -> Path:
    return Path(os.path.expanduser(policy["registry_dir"]))


def live_leases(policy: dict, *, alive: Callable[[int], bool] = pid_alive,
                started: Callable[[int], Optional[str]] = start_time, prune: bool = True) -> list[dict]:
    """Leases whose holder is the SAME live process that took them. A lease whose pid is dead or
    reused (start time differs) is stale: it is ignored and, by default, removed — a run killed by
    SIGKILL/os._exit never reaches its own release."""
    out = []
    d = registry(policy)
    if not d.is_dir():
        return out
    for f in d.glob("*.json"):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
            pid = int(rec.get("pid", 0))
        except (OSError, ValueError, TypeError):
            pid, rec = 0, {}
        live = alive(pid)
        if live and rec.get("pid_started") and started is not None:
            now_started = started(pid)
            live = now_started is None or now_started == rec["pid_started"]
        if live:
            out.append({**rec, "_file": str(f)})
        elif prune:
            try:
                f.unlink()
            except OSError:
                pass
    return out


@dataclass
class Lease:
    kind: str
    tree: str
    pid: int
    file: Path
    reniced: Optional[str] = None
    record: dict = field(default_factory=dict)

    def release(self) -> None:
        try:
            self.file.unlink()
        except FileNotFoundError:
            pass

    def __enter__(self) -> "Lease":
        return self

    def __exit__(self, *exc) -> None:
        self.release()


def admit(kind: str, tree: str, *, pid: Optional[int] = None, policy: Optional[dict] = None,
          alive: Callable[[int], bool] = pid_alive,
          disk_usage: Callable = shutil.disk_usage,
          pressure: Callable[[], Optional[int]] = _pressure_level,
          renice: bool = True, note: str = "",
          started: Callable[[int], Optional[str]] = start_time) -> Lease:
    """Take a lease or raise ``AdmissionRefused``. ``tree`` is the working tree the job mutates."""
    policy = policy or _policy()
    pid = pid or os.getpid()
    tree = os.path.realpath(tree)
    d = registry(policy)
    d.mkdir(parents=True, exist_ok=True)
    # The whole read → check → write is ONE critical section under an exclusive lock on the registry
    # (second review 2026-10-03): ordering by file mtime let two racers both win, because the time is
    # stamped when the temp file is written, not when the lease becomes visible.
    import fcntl
    with open(d / ".lock", "a+") as lockf:
        fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
        try:
            leases = live_leases(policy, alive=alive, started=started)
            same_tree = [l for l in leases if l.get("tree") == tree and int(l.get("pid", 0)) != pid]
            if same_tree:
                h = same_tree[0]
                raise AdmissionRefused(
                    f"tree {tree} is already held by live {h.get('kind')} job pid {h.get('pid')} "
                    f"(since {h.get('started_at')}): two workers never mutate one tree — use your own worktree")
            cap = policy["max_concurrent"].get(kind, policy["max_concurrent"]["default"])
            same_kind = [l for l in leases if l.get("kind") == kind and int(l.get("pid", 0)) != pid]
            if len(same_kind) >= cap:
                raise AdmissionRefused(
                    f"{len(same_kind)} live '{kind}' jobs already run (cap {cap}): "
                    + ", ".join(f"pid {l['pid']} on {l.get('tree')}" for l in same_kind)
                    + " — wait for one to finish")
            try:
                free_gb = disk_usage(tree).free / GB
            except OSError:
                free_gb = None
            if free_gb is not None and free_gb < policy["min_free_disk_gb"]:
                raise AdmissionRefused(f"free disk {free_gb:.1f} GB < {policy['min_free_disk_gb']} GB — "
                                       f"a heavy job now could starve the paper books of disk")
            lvl = pressure()
            if lvl is not None and lvl >= policy["refuse_at_pressure_level"]:
                raise AdmissionRefused(f"kernel memory pressure level {lvl} — heavy jobs wait until it clears")
            reniced = None
            if renice and pid == os.getpid():
                try:
                    cur = os.getpriority(os.PRIO_PROCESS, 0)
                    if cur < policy["nice"]:
                        os.setpriority(os.PRIO_PROCESS, 0, policy["nice"])
                        reniced = f"{cur}->{policy['nice']}"
                except OSError:
                    reniced = None
            rec = {"kind": kind, "tree": tree, "pid": pid, "pid_started": started(pid) if started else None,
                   "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "note": note[:200],
                   "reniced": reniced}
            f = d / f"{kind}-{pid}-{uuid.uuid4().hex[:8]}.json"
            tmp = f.with_suffix(".tmp")
            tmp.write_text(json.dumps(rec), encoding="utf-8")
            os.replace(tmp, f)
        finally:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)
    return Lease(kind=kind, tree=tree, pid=pid, file=f, reniced=reniced, record=rec)


def main(argv: Optional[list[str]] = None) -> int:
    """`python -m spa_core.utils.heavy_job status` — list live leases (read-only)."""
    pol = _policy()
    leases = live_leases(pol)
    print(json.dumps({"live": [{k: v for k, v in l.items() if k != "_file"} for l in leases],
                      "caps": pol["max_concurrent"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
