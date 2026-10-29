"""spa_core/monitoring/resource_guard.py — «есть ли куда писать и чем дышать» (ADR-551).

Why this exists. On 2026-10-02 22:58Z and 2026-10-03 07:55Z the Data volume reached 0 bytes free.
Fourteen fleet agents logged ENOSPC locally and NOT ONE told anybody: the hourly paper sleeves lost
an observation slot, code-sync could not fetch, and the cause (957 abandoned g17_/g18_ test stands,
87 GB, ADR-546) had been growing for three days. Memory pressure killed a Claude session the same
night. No agent measured disk, memory or swap (audit 2026-10-03).

What it does (every run, deterministic, no LLM):
1. MEASURES free disk on the Data volume, kernel memory-pressure level, swap use, and the processes
   by RSS — each classified CRITICAL / IMPORTANT / DISPOSABLE by ``architecture/resource_policy.json``
   (classes derived from dependencies, not guessed). A probe that fails is NOT_MEASURED, never OK
   (invariant #17).
2. PROTECTS critical services without killing anything:
   - under memory pressure ≥ warn, DISPOSABLE processes (test shards, headless LLM runs, browser
     checks) are re-niced to the policy's nice level;
   - a disk reserve file (``disk.reserve_gb``) is kept while disk is healthy and RELEASED at CRITICAL,
     so canonical writers keep room while the cause is found.
3. ALERTS the owner once per incident through the existing push policy (``resource_critical``,
   edge-triggered, resolved on recovery) and writes ``data/resource_health.json`` for Director.
4. CLEANUP is a separate, explicit action (``--cleanup [--apply]``): only allow-listed prefixes under
   allow-listed roots, older than their TTL, never following symlinks, never under ``never_touch``;
   linked worktrees only through the existing reaper. Default is a dry run that REPORTS.

Exit codes: 0 OK · 1 WARN · 2 CRITICAL or NOT MEASURED.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

#: Contract (ADR-154/158): what this agent PRODUCES. The daily cleanup and the orphan report live in
#: their own module (spa_core.monitoring.resource_cleanup) with their own contract.
PRODUCES = ("data/resource_health.json",)

REPO = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO / "architecture" / "resource_policy.json"
EVENT_KEY = "resource_critical"
GB = 1024 ** 3

OK, WARN, CRITICAL, UNMEASURED = "OK", "WARN", "CRITICAL", "NOT_MEASURED"
#: Verdicts of the EXHAUSTION sensor (ADR-862). Three outcomes are kept apart (inv. #17):
#: FALLING — measured and falling · STEADY — measured and NOT falling (an answer, not a missing one) ·
#: WARMING_UP — no prior sample inside the window yet (normal after a restart, NOT a blind sensor) ·
#: UNMEASURED — the sensor itself could not answer (history unreadable, clock ran backwards).
FALLING, STEADY, WARMING_UP = "FALLING", "STEADY", "WARMING_UP"
# CRITICAL outranks NOT_MEASURED (a measured emergency is named as such); NOT_MEASURED outranks WARN
# and OK — a missing measurement is never «fine» (inv. #17, second review 2026-10-03).
_RANK = {OK: 0, WARN: 1, UNMEASURED: 2, CRITICAL: 3}


def load_policy(path: Path = POLICY_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _run(cmd: list[str], timeout: float = 15.0) -> Optional[str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def user_temp_root(*, run: Callable = None) -> Optional[str]:
    """The per-user temp root (/var/folders/…/T) — where tempfile.mkdtemp put the 87 GB. launchd
    agents often have no $TMPDIR, and os.confstr("CS_DARWIN_USER_TEMP_DIR") is not available on every
    Python build (absent on this miniconda: review 2026-10-03), so ask the OS through getconf.
    None = NOT MEASURED (the caller names it; it is never «nothing to clean»)."""
    out = (run or _run)(["getconf", "DARWIN_USER_TEMP_DIR"])
    if out and out.strip():
        return out.strip().rstrip("/")
    try:
        v = os.confstr("CS_DARWIN_USER_TEMP_DIR")
        if v:
            return v.rstrip("/")
    except (ValueError, OSError, AttributeError):
        pass
    t = os.environ.get("TMPDIR")
    return t.rstrip("/") if t else None


def expand_root(root: str) -> Optional[str]:
    if root == "$USER_TEMP":
        return user_temp_root()
    return os.path.expanduser(root)


# ── measurement ─────────────────────────────────────────────────────────────

def measure_disk(policy: dict, *, disk_usage: Callable = shutil.disk_usage) -> dict:
    d = policy["disk"]
    try:
        u = disk_usage(d["volume"])
    except OSError as exc:
        return {"state": UNMEASURED, "reason": f"{d['volume']}: {exc}"}
    free = u.free / GB
    state = CRITICAL if free < d["critical_free_gb"] else WARN if free < d["warn_free_gb"] else OK
    return {"state": state, "volume": d["volume"], "free_gb": round(free, 1),
            # free_bytes is published UNROUNDED on purpose: free_gb is rounded to 0.1 GB (= 107 MB), and a
            # rate divided from rounded levels would quantise to ~1.3 GB/h on the 5-minute path (ADR-862).
            "free_bytes": u.free,
            "total_gb": round(u.total / GB, 1), "warn_free_gb": d["warn_free_gb"],
            "critical_free_gb": d["critical_free_gb"]}


def parse_swap(text: Optional[str]) -> Optional[dict]:
    # "total = 3072,00M  used = 2099,44M  free = 972,56M  (encrypted)" — the decimal comma is locale
    if not text:
        return None
    vals = {}
    for key in ("total", "used"):
        m = re.search(key + r"\s*=\s*([\d.,]+)M", text)
        if not m:
            return None
        vals[key] = float(m.group(1).replace(",", "."))
    pct = round(100.0 * vals["used"] / vals["total"], 1) if vals["total"] > 0 else 0.0
    return {"total_mb": vals["total"], "used_mb": vals["used"], "used_pct": pct}


def measure_memory(policy: dict, *, run: Callable = _run) -> dict:
    m = policy["memory"]
    lvl_txt = run(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"])
    swap = parse_swap(run(["sysctl", "-n", "vm.swapusage"]))
    try:
        level = int(str(lvl_txt).strip())
    except (TypeError, ValueError):
        level = None
    if level is None and swap is None:
        return {"state": UNMEASURED, "reason": "neither pressure level nor swap could be read"}
    states = []
    if level is not None:
        states.append(CRITICAL if level >= m["pressure_critical_level"] else
                      WARN if level >= m["pressure_warn_level"] else OK)
    else:
        states.append(UNMEASURED)
    if swap is not None and swap["total_mb"] > 0:
        states.append(CRITICAL if swap["used_pct"] >= m["swap_critical_pct"] else
                      WARN if swap["used_pct"] >= m["swap_warn_pct"] else OK)
    state = max(states, key=lambda s: _RANK[s])
    # Which signal decided the state — the owner must be able to tell «RAM is short» (kernel pressure)
    # from «the swap FILE is nearly full» (macOS grows swap in 1-GB files, so used/total of a small swap
    # is high long before RAM is short). ADR-763 package 2: 2026-10-15 20:23Z was CRITICAL by swap alone
    # at pressure 2 and 87 GB free disk.
    triggers = []
    if level is not None and level >= m["pressure_warn_level"]:
        triggers.append({"signal": "pressure", "state": states[0]})
    if swap is not None and swap["total_mb"] > 0 and swap["used_pct"] >= m["swap_warn_pct"]:
        triggers.append({"signal": "swap", "state": states[-1]})
    try:
        ram_gb = round(int(str(run(["sysctl", "-n", "hw.memsize"])).strip()) / GB, 1)
    except (TypeError, ValueError):
        ram_gb = None
    return {"state": state, "pressure_level": level, "swap": swap, "ram_total_gb": ram_gb,
            "triggers": triggers}


def launchd_pids(*, run: Callable = _run) -> dict[int, str]:
    out = run(["launchctl", "list"]) or ""
    pids = {}
    for line in out.splitlines()[1:]:
        parts = line.split("\t") if "\t" in line else line.split()
        if len(parts) >= 3 and parts[0].strip().isdigit():
            pids[int(parts[0])] = parts[2].strip()
    return pids


def classify(cmd: str, label: Optional[str], policy: dict) -> str:
    """CRITICAL job (and everything it runs) > DISPOSABLE work pattern > IMPORTANT job > UNCLASSIFIED.

    A disposable child of an IMPORTANT scheduler stays disposable: the orchestrator job itself must
    keep running, the pytest shard it spawned may be slowed. A CRITICAL job's children are critical
    (the hy_cycle wrapper's python IS the paper book writer)."""
    pc = policy["process_classes"]
    if label and label in pc["CRITICAL"]["labels"]:
        return "CRITICAL"
    for pat in pc["DISPOSABLE"]["command_patterns"]:
        if re.search(pat, cmd):
            return "DISPOSABLE"
    if label and label in pc["IMPORTANT"]["labels"]:
        return "IMPORTANT"
    return "UNCLASSIFIED"


def _ppid_map(rows) -> dict[int, int]:
    return {r["pid"]: r["ppid"] for r in rows}


_SECRET_FLAG = re.compile(r"(?i)(--?[\w-]*(?:token|secret|passw(?:or)?d|api[-_]?key|auth|credential)[\w-]*)(=|\s+)(\S+)")
_SECRET_BLOB = re.compile(r"(?<![\w/.-])[A-Za-z0-9+_=-]{40,}(?![\w/.-])")
_SECRET_ENV = re.compile(r"(?i)\b([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_KEY)[A-Z0-9_]*)=(\S+)")


def redact_cmd(cmd: str) -> str:
    """Command lines go to a file and to the owner's Telegram (Director): secrets never do (inv. #7).
    Measured 2026-10-03 by the fresh-session test: the tunnel's `--token <jwt>` landed in
    data/resource_health.json. Values of secret-looking flags/env vars and any long opaque blob
    are replaced; the process stays recognisable."""
    cmd = _SECRET_FLAG.sub(lambda m: f"{m.group(1)}{m.group(2)}<redacted>", cmd)
    cmd = _SECRET_ENV.sub(lambda m: f"{m.group(1)}=<redacted>", cmd)
    return _SECRET_BLOB.sub("<redacted>", cmd)


def measure_processes(policy: dict, *, run: Callable = _run, top: int = 15) -> dict:
    out = run(["ps", "-axo", "pid=,ppid=,rss=,nice=,etime=,command="])
    if out is None:
        return {"state": UNMEASURED, "reason": "ps failed"}
    rows = []
    for line in out.splitlines():
        parts = line.split(None, 5)
        if len(parts) < 6 or not parts[0].isdigit():
            continue
        rows.append({"pid": int(parts[0]), "ppid": int(parts[1]), "rss_mb": round(int(parts[2]) / 1024, 1),
                     "nice": int(parts[3]) if parts[3].lstrip("-").isdigit() else None,
                     "etime": parts[4], "cmd": redact_cmd(parts[5])[:240], "_raw": parts[5]})
    labels = launchd_pids(run=run)
    parents = _ppid_map(rows)

    def label_of(pid: int) -> Optional[str]:
        # a launchd job's work runs in CHILDREN of the wrapper (bash → python); walk up to the job
        seen = 0
        while pid and seen < 8:
            if pid in labels:
                return labels[pid]
            pid = parents.get(pid, 0)
            seen += 1
        return None

    for r in rows:
        r["label"] = label_of(r["pid"])
        r["class"] = classify(r.pop("_raw"), r["label"], policy)   # classify on the real line, store the redacted one
    rows.sort(key=lambda r: -r["rss_mb"])
    by_class: dict[str, float] = {}
    for r in rows:
        by_class[r["class"]] = round(by_class.get(r["class"], 0.0) + r["rss_mb"], 1)
    return {"state": OK, "count": len(rows), "rss_mb_by_class": by_class,
            "top": rows[:top], "disposable": [r for r in rows if r["class"] == "DISPOSABLE"],
            "critical": [r for r in rows if r["class"] == "CRITICAL"]}


# ── protection ──────────────────────────────────────────────────────────────

def _same_process(pid: int, cmd: str) -> bool:
    out = _run(["ps", "-o", "command=", "-p", str(pid)])
    return bool(out) and redact_cmd(out.strip())[:120] == cmd.strip()[:120]


def protect(report: dict, policy: dict, *, setpriority: Callable = os.setpriority,
            getpriority: Callable = os.getpriority, verify: Optional[Callable] = None) -> list[dict]:
    """Under memory pressure ≥ warn, lower the CPU priority of DISPOSABLE processes. Never kills."""
    mem = report.get("memory") or {}
    if mem.get("state") not in (WARN, CRITICAL):
        return []
    target = int(policy["heavy_jobs"]["nice"])
    acted = []
    for r in (report.get("processes") or {}).get("disposable", []):
        if verify is not None and not verify(r["pid"], r["cmd"]):
            continue                          # the pid was reused since the snapshot — leave it alone
        try:
            cur = getpriority(os.PRIO_PROCESS, r["pid"])
            if cur < target:
                setpriority(os.PRIO_PROCESS, r["pid"], target)
                acted.append({"pid": r["pid"], "cmd": r["cmd"][:120], "nice": f"{cur}->{target}"})
        except (OSError, PermissionError) as exc:
            acted.append({"pid": r["pid"], "cmd": r["cmd"][:120], "error": str(exc)})
    return acted


def manage_reserve(disk: dict, policy: dict) -> dict:
    """Keep a reserve file while disk is OK/WARN; release it at CRITICAL so canonical writers keep
    room. Recreated only when the disk is back above the WARN line (no flapping)."""
    d = policy["disk"]
    path = Path(os.path.expanduser(d["reserve_path"]))
    size = int(d["reserve_gb"] * GB)
    state = disk.get("state")
    try:
        if state == CRITICAL:
            if path.exists():
                # The delta is a REPORT, the release is the ACT: an unreadable volume must not keep the
                # reserve pinned at CRITICAL. Unmeasured ⇒ None with the reason, never 0 (inv. #17).
                # (CI control run 39003158532: "/System/Volumes/Data" absent on Linux ⇒ OSError ⇒ the
                # whole release reported "error" and the file stayed.)
                try:
                    before = shutil.disk_usage(d["volume"]).free
                except OSError as exc:
                    before, why = None, f"{d['volume']}: {exc}"
                path.unlink()
                freed = None
                if before is not None:
                    try:
                        freed = round((shutil.disk_usage(d["volume"]).free - before) / GB, 2)
                    except OSError as exc:
                        why = f"{d['volume']}: {exc}"
                # An APFS local snapshot can pin the file's blocks: the measured delta is reported, not
                # the nominal size (review 2026-10-03).
                out = {"action": "released", "path": str(path), "nominal_gb": d["reserve_gb"],
                       "measured_freed_gb": freed}
                if freed is None:
                    out["freed_unmeasured"] = why
                return out
            return {"action": "already_released", "path": str(path)}
        if state == OK and (not path.exists() or path.stat().st_size < size):
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "wb") as f:
                chunk = b"\0" * (64 * 1024 * 1024)
                written = 0
                while written < size:
                    f.write(chunk[: min(len(chunk), size - written)])
                    written += min(len(chunk), size - written)
            return {"action": "created", "path": str(path), "gb": d["reserve_gb"]}
        return {"action": "kept" if path.exists() else "absent", "path": str(path)}
    except OSError as exc:
        return {"action": "error", "path": str(path), "error": str(exc)}


# ── exhaustion: the RATE, not the level (ADR-862) ───────────────────────────
#
# Measured 2026-10-29: "9.7 GB free" and "9.7 GB free, falling 17.9 GB/h" demand DIFFERENT actions —
# the first is a WARN someday, the second is 33 minutes. The guard ran every 5 minutes for a month and
# published only the level, so two sessions in a row (#978, #979) had to time the rate by hand with a
# sleep loop, and the owner's card said "about 28 minutes" because nobody had the number. Every
# threshold in architecture/resource_policy.json was sized against a declared premise — "40 GB leaves a
# day of the worst measured growth (~30 GB/day)" — which the same day measured 428.9 GB/day: FALSE x14.3.
# A level cannot notice that; a rate can.


def load_samples(path: Path) -> tuple[list, Optional[str]]:
    """Past free-space observations. Returns (samples, reason-it-could-not-be-read).

    An absent file is NOT an error: it is the first run ever (⇒ WARMING_UP, not UNMEASURED). An
    unreadable or malformed one IS, and it is named — never silently treated as "no history" (inv. #17).
    """
    if not path.exists():
        return [], None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [], f"{path.name}: {type(exc).__name__}: {exc}"
    rows = doc.get("samples") if isinstance(doc, dict) else doc
    if not isinstance(rows, list):
        return [], f"{path.name}: samples is {type(rows).__name__}, expected list"
    return rows, None


def measure_exhaustion(disk: dict, policy: dict, *, samples: list, now: float,
                       samples_error: Optional[str] = None) -> dict:
    """How fast free space is going, and how long until none is left.

    ``now`` and ``samples`` are INPUTS, never the wall clock and never a file read from here
    (.claude/rules/deployment.md: time is an input, so the test fixes both ends and cannot rot).
    The span used is the LONGEST one available inside the declared window, because a rate divided over
    one 5-minute step is dominated by whatever a single cleanup or a single test shard did in it.
    """
    cfg = (policy.get("disk") or {}).get("exhaustion") or {}
    if samples_error:
        return {"state": UNMEASURED, "reason": f"история замеров не прочитана: {samples_error}"}
    free = disk.get("free_bytes")
    if free is None:
        return {"state": UNMEASURED,
                "reason": f"свободное место не измерено: {disk.get('reason') or disk.get('state')}"}
    span_max = float(cfg.get("max_span_s", 7200))
    span_min = float(cfg.get("min_span_s", 240))
    usable = [r for r in samples
              if isinstance(r, dict) and isinstance(r.get("ts"), (int, float))
              and isinstance(r.get("free_bytes"), (int, float)) and not isinstance(r.get("ts"), bool)]
    ahead = [r for r in usable if r["ts"] > now]
    fresh = [r for r in usable if 0 < now - r["ts"] <= span_max]
    if ahead and not fresh:
        # A sample stamped in the future means the clock moved, so no span here is arithmetic we may
        # trust. Guessing "steady" would hide a fall; guessing a rate would invent one.
        return {"state": UNMEASURED, "reason": "отметка замера в будущем — часы шли назад",
                "samples": len(usable)}
    if not fresh:
        return {"state": WARMING_UP, "reason": f"нет прежнего замера в окне {span_max / 60:.0f} мин",
                "samples": len(usable), "window_s": span_max}
    base = min(fresh, key=lambda r: r["ts"])
    span = now - base["ts"]
    if span < span_min:
        return {"state": WARMING_UP,
                "reason": f"пролёт {span:.0f} с короче объявленного минимума {span_min:.0f} с",
                "span_s": round(span, 1), "samples": len(fresh)}
    spent = base["free_bytes"] - free                     # > 0 ⇒ free space is FALLING
    per_h = spent / span * 3600.0
    out = {"span_s": round(span, 1), "samples": len(fresh), "gb_per_hour": round(per_h / GB, 2),
           "free_gb": round(free / GB, 2)}
    if per_h <= 0:
        # Measured AND equal to zero is an ANSWER (inv. #17): not falling must be distinguishable both
        # from "falling slowly" and from "nobody looked". There is no time-to-full, and that is a fact.
        out.update({"state": STEADY, "minutes_to_full": None})
        return out
    out.update({"state": FALLING, "minutes_to_full": round(free / per_h * 60.0, 1)})
    return out


def exhaustion_state(exh: dict, policy: dict) -> str:
    """The rate's own verdict — the half of the sensor that has a READER.

    A published number nobody reads is the defect this repo keeps finding, so the rate votes in
    ``overall``. It votes in ONE direction only (see build_report): it may escalate, never calm.
    """
    cfg = (policy.get("disk") or {}).get("exhaustion") or {}
    if exh.get("state") == UNMEASURED:
        # Deliberately NOT UNMEASURED for the report as a whole: the LEVEL is still measured, and
        # claiming the guard is blind would be false. ADR-400's lesson — two different questions must
        # not be equated. It is printed instead (summary_line, owner_body), so it is not silent either.
        return OK
    mins = exh.get("minutes_to_full")
    if mins is None:
        return OK
    if mins <= float(cfg.get("critical_minutes_to_full", 60)):
        return CRITICAL
    if mins <= float(cfg.get("warn_minutes_to_full", 240)):
        return WARN
    return OK


def record_sample(path: Path, disk: dict, policy: dict, *, samples: list, now: float) -> None:
    """Append this observation and keep the declared tail. Never raises: losing the history costs the
    NEXT rate (⇒ WARMING_UP, named), while a crash here would cost the whole 5-minute guard run."""
    if disk.get("free_bytes") is None:
        return
    cfg = (policy.get("disk") or {}).get("exhaustion") or {}
    keep = int(cfg.get("max_samples", 24))
    rows = [r for r in samples if isinstance(r, dict) and isinstance(r.get("ts"), (int, float))]
    rows.append({"ts": round(now, 1), "free_bytes": int(disk["free_bytes"])})
    rows = sorted(rows, key=lambda r: r["ts"])[-keep:]
    try:
        from spa_core.utils.atomic import atomic_save
        atomic_save({"schema": "resource-free-samples/1", "samples": rows}, str(path))
    except Exception:  # noqa: BLE001 — see docstring: the guard's run outlives its own history file
        pass


# ── cleanup ─────────────────────────────────────────────────────────────────

def _dir_size(p: Path, cap_entries: int = 200_000) -> int:
    total, n = 0, 0
    for root, _dirs, files in os.walk(p, followlinks=False):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
            n += 1
            if n > cap_entries:
                return total
    return total


def _protected(path: str, policy: dict) -> bool:
    rp = os.path.realpath(path)
    return any(rp == os.path.realpath(t) or rp.startswith(os.path.realpath(t) + os.sep)
               for t in policy["cleanup"]["never_touch"])


def _newest_mtime(p: str, cap_entries: int = 200_000) -> Optional[float]:
    """Age of a stand = its NEWEST entry, not its top-level mtime: a directory's own mtime moves only
    when a direct child is added or removed, so a live sandbox written deep inside would look old
    (review 2026-10-03). Bounded walk; past the cap the age is NOT MEASURED (None) and the stand is kept."""
    newest, n = os.lstat(p).st_mtime, 0
    for root, dirs, files in os.walk(p, followlinks=False):
        for name in dirs + files:
            try:
                newest = max(newest, os.lstat(os.path.join(root, name)).st_mtime)
            except OSError:
                pass
            n += 1
            if n >= cap_entries:
                return None            # not fully seen ⇒ age NOT MEASURED — never treated as old (review)
    return newest


def cleanup_candidates(policy: dict, *, now: Optional[float] = None, sizes: bool = True,
                       unmeasured: Optional[list] = None, deep: bool = True) -> list[dict]:
    """Allow-listed, expired disposable directories. A root that cannot be resolved or read is
    appended to ``unmeasured`` with its reason — never silently skipped."""
    now = now or time.time()
    out = []
    for rule in policy["cleanup"]["disposable_dirs"]:
        root = expand_root(rule["root"])
        if not root or not os.path.isdir(root):
            if unmeasured is not None:
                unmeasured.append({"root": rule["root"], "reason": f"root not resolved/readable: {root!r}"})
            continue
        try:
            names = os.listdir(root)
        except OSError as exc:
            if unmeasured is not None:
                unmeasured.append({"root": rule["root"], "reason": str(exc)})
            continue
        for name in names:
            if not any(name.startswith(pfx) for pfx in rule["prefixes"]):
                continue
            p = os.path.join(root, name)
            try:
                st = os.lstat(p)
            except OSError:
                continue
            if os.path.islink(p) or _protected(p, policy):
                continue                      # never follow or remove a link; never_touch wins
            if (now - st.st_mtime) / 3600.0 < rule["ttl_hours"]:
                continue                      # cheap pre-filter: a fresh top level is fresh
            if os.path.isdir(p) and deep:
                try:
                    newest = _newest_mtime(p)
                except OSError:
                    continue
                if newest is None:
                    if unmeasured is not None:
                        unmeasured.append({"path": p, "reason": "too large to read its age in one pass — kept"})
                    continue
            else:
                newest = st.st_mtime   # 5-minute path: top level only, never a deep walk (review)
            age_h = (now - newest) / 3600.0
            if age_h < rule["ttl_hours"]:
                continue
            out.append({"path": p, "rule_root": rule["root"], "age_h": round(age_h, 1),
                        "bytes": (_dir_size(Path(p)) if os.path.isdir(p) else st.st_size) if sizes else None})
    return out


def apply_cleanup(cands: list[dict], policy: dict, *, log_path: Path) -> list[dict]:
    done = []
    for c in cands[: int(policy["cleanup"]["max_deletions_per_run"])]:
        p = c["path"]
        if _protected(p, policy) or os.path.islink(p):
            continue
        try:
            if os.path.isdir(p):
                shutil.rmtree(p)
            else:
                os.unlink(p)
            done.append({**c, "removed": True})
        except OSError as exc:
            done.append({**c, "removed": False, "error": str(exc)})
    if done:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            ts = datetime.now(timezone.utc).isoformat()
            for d in done:
                f.write(json.dumps({"ts": ts, **d}, ensure_ascii=False) + "\n")
    return done


def reap_worktrees(apply: bool) -> dict:
    cmd = [sys.executable, str(REPO / "scripts" / "reap_stale_worktrees.py"), "--json"]
    if apply:
        cmd.append("--apply")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800, cwd=str(REPO))
    except (OSError, subprocess.SubprocessError) as exc:
        return {"state": UNMEASURED, "reason": str(exc)}
    try:
        data = json.loads(r.stdout)
    except ValueError:
        return {"state": UNMEASURED, "reason": f"reaper rc {r.returncode}, no JSON",
                "stderr": r.stderr[-400:]}
    counts: dict = {}
    for t in data.get("trees") or []:
        counts[t.get("verdict", "?")] = counts.get(t.get("verdict", "?"), 0) + 1
    return {"state": OK if r.returncode in (0, 1) else UNMEASURED, "rc": r.returncode,
            "counts": counts, "base_read": data.get("base_read"),
            "unmeasured_reasons": data.get("unmeasured_reasons")}


# ── report ──────────────────────────────────────────────────────────────────

def build_report(policy: dict, *, disk_usage: Callable = shutil.disk_usage, run: Callable = _run,
                 now: Optional[datetime] = None, data_dir: Optional[Path] = None,
                 samples: Optional[list] = None, samples_error: Optional[str] = None,
                 record: bool = True) -> dict:
    now = now or datetime.now(timezone.utc)
    disk = measure_disk(policy, disk_usage=disk_usage)
    mem = measure_memory(policy, run=run)
    procs = measure_processes(policy, run=run)

    # ── the rate (ADR-862). History comes from an argument when given, so a test fixes BOTH ends.
    spath = Path(data_dir) / "resource_free_samples.json" if data_dir else None
    if samples is None and spath is not None:
        samples, samples_error = load_samples(spath)
    exh = measure_exhaustion(disk, policy, samples=samples or [], now=now.timestamp(),
                             samples_error=samples_error)
    exh_state = exhaustion_state(exh, policy)
    # The rate votes in ONE direction. _RANK-max over the level AND the rate means a measured fall can
    # raise the verdict (18 GB/h at 18 GB free is CRITICAL an hour before the 15 GB line is crossed),
    # while a calm rate can never talk the level down from CRITICAL — fail-CLOSED (inv. #2).
    overall = max((disk["state"], mem["state"], procs["state"], exh_state), key=lambda s: _RANK[s])
    rep = {"schema": "resource-health/1", "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
           "overall": overall, "disk": disk, "memory": mem, "processes": procs,
           "exhaustion": {**exh, "state_vote": exh_state},
           "policy": str(POLICY_PATH.relative_to(REPO)), "policy_version": policy.get("version")}
    if record and spath is not None:
        record_sample(spath, disk, policy, samples=samples or [], now=now.timestamp())
    if disk["state"] in (WARN, CRITICAL):
        # No size walk on the 5-minute path (review 2026-10-03: hundreds of 87-GB stands would make the
        # guard overrun its own interval exactly when it matters). Counts and oldest names only; the
        # daily cleanup measures bytes.
        um: list = []
        cands = cleanup_candidates(policy, sizes=False, unmeasured=um, deep=False)
        rep["disposable_backlog"] = {"count": len(cands), "count_basis": "top-level age only (5-min path)",
                                     "unmeasured_roots": um,
                                     "oldest": sorted(cands, key=lambda c: -c["age_h"])[:10]}
    return rep


def summary_line(rep: dict) -> str:
    d, m = rep["disk"], rep["memory"]
    disk = f"disk {d.get('free_gb')} GB free" if d.get("free_gb") is not None else f"disk {d['state']}"
    sw = (m.get("swap") or {}).get("used_pct")
    mem = f"memory pressure {m.get('pressure_level')}, swap {sw}%" if m["state"] != UNMEASURED else "memory NOT MEASURED"
    return f"{rep['overall']}: {disk}{exhaustion_line(rep)}; {mem}"


def exhaustion_line(rep: dict) -> str:
    """The rate, in the one line the agent log and the office step actually read (ADR-862)."""
    e = rep.get("exhaustion") or {}
    st = e.get("state")
    if st == FALLING:
        return f", falling {e.get('gb_per_hour')} GB/h — full in {e.get('minutes_to_full')} min"
    if st == STEADY:
        return ", not falling"
    if st == WARMING_UP:
        return f", rate not yet measured ({e.get('reason')})"
    if st == UNMEASURED:
        return f", rate NOT MEASURED ({e.get('reason')})"
    return ""


_PRESSURE_RU = {1: "норма", 2: "предупреждение", 4: "критично"}


def _minutes_ru(mins: Optional[float]) -> str:
    if mins is None:
        return "неизвестно"
    if mins < 90:
        return f"{round(mins)} мин"
    return f"{str(round(mins / 60, 1)).replace('.', ',')} ч"


def _gb(mb: Optional[float]) -> str:
    return "?" if mb is None else f"{mb / 1024:.1f}".replace(".", ",")


def owner_body(rep: dict, top: int = 3) -> str:
    """Plain-Russian alert body for the owner (ADR-763 package 2): RAM, swap and disk are three different
    things and are named apart; absolute values, the measurement time and the main memory consumers.
    The swap percentage is the share of the SWAP FILE in use, never «% of RAM»."""
    from spa_core.utils.presentation import fmt_owner_time
    d, m = rep.get("disk") or {}, rep.get("memory") or {}
    lines = []
    at = rep.get("generated_at")
    lines.append(f"Замер: {fmt_owner_time(at, unknown='время не записано')}" + (f" ({at})" if at else ""))
    if m.get("state") == UNMEASURED:
        lines.append("Оперативная память (RAM): НЕ ИЗМЕРЕНО")
    else:
        lvl = m.get("pressure_level")
        ram = m.get("ram_total_gb")
        lvl_txt = "не измерено" if lvl is None else f"{lvl} ({_PRESSURE_RU.get(lvl, 'между уровнями')}; 1 — норма, 2 — предупреждение, 4 — критично)"
        lines.append(f"Оперативная память (RAM): давление {lvl_txt}" + (f"; всего RAM {str(ram).replace('.', ',')} ГБ" if ram else ""))
        sw = m.get("swap")
        if sw and sw.get("total_mb"):
            lines.append(f"Своп (файл подкачки на диске, НЕ оперативная память): занято {_gb(sw.get('used_mb'))} ГБ "
                         f"из {_gb(sw.get('total_mb'))} ГБ ({str(sw.get('used_pct')).replace('.', ',')} % файла подкачки)")
        elif sw is not None:
            lines.append("Своп (файл подкачки): не используется")
        else:
            lines.append("Своп (файл подкачки): не измерено")
    if d.get("free_gb") is not None:
        tot = d.get("total_gb")
        lines.append(f"Диск: свободно {str(d['free_gb']).replace('.', ',')} ГБ" + (f" из {str(tot).replace('.', ',')} ГБ" if tot else ""))
    else:
        lines.append(f"Диск: {d.get('state', 'не измерено')}")
    # The rate, in words: "свободно 9,7 ГБ" let the owner's card say «около 28 минут» when the measured
    # answer was 33 (ADR-862). A number without its speed is not actionable.
    e = rep.get("exhaustion") or {}
    if e.get("state") == FALLING:
        mins = e.get("minutes_to_full")
        lines.append(f"Скорость: место уходит {str(e.get('gb_per_hour')).replace('.', ',')} ГБ/ч — "
                     f"при этой скорости диск кончится через {_minutes_ru(mins)} "
                     f"(замер по пролёту {round((e.get('span_s') or 0) / 60)} мин)")
    elif e.get("state") == STEADY:
        lines.append("Скорость: место НЕ уходит (измерено, не «не измерено»)")
    elif e.get("state") == UNMEASURED:
        lines.append(f"Скорость: НЕ ИЗМЕРЕНО — {e.get('reason')}")
    why = []
    if d.get("state") in (WARN, CRITICAL):
        why.append(f"диск ({d['state']})")
    names = {"pressure": "давление на оперативную память", "swap": "заполнен файл подкачки (своп)"}
    for tr in m.get("triggers") or []:
        why.append(f"{names.get(tr.get('signal'), tr.get('signal'))} ({tr.get('state')})")
    if why:
        lines.append("Сработало: " + ", ".join(why))
    procs = (rep.get("processes") or {}).get("top") or []
    if procs:
        def name(r: dict) -> str:
            cmd = r.get("cmd") or ""
            mod = re.search(r"-m\s+([\w.]+)", cmd)
            base = mod.group(1).rsplit(".", 1)[-1] if mod else (cmd.split() or ["?"])[0].rsplit("/", 1)[-1]
            return base + (f" ({r['label']})" if r.get("label") else "")
        lines.append("Больше всего памяти: " + " · ".join(f"{name(r)} {_gb(r.get('rss_mb'))} ГБ" for r in procs[:top]))
    return "\n".join(lines)


def notify(rep: dict, *, data_dir: Path, send: bool = True) -> Optional[bool]:
    from spa_core.telegram import push_policy
    if rep["overall"] == CRITICAL:
        fp = f"disk:{rep['disk']['state']}|mem:{rep['memory']['state']}"
        body = owner_body(rep)
        bl = rep.get("disposable_backlog") or {}
        if bl.get("count"):
            body += f"\nexpired disposable stands: {bl['count']} (daily cleanup removes them; resource_guard --cleanup --apply now)"
        return push_policy.push_critical(EVENT_KEY, "CRITICAL", "Ресурсы Мака на исходе", body,
                                         data_dir=data_dir, dedup_key=fp, send=send)
    if rep["overall"] == UNMEASURED:
        # A blind guard is an incident of its own (inv. #17): pushed under its own fingerprint so it is
        # neither silenced by nor confused with a measured shortage.
        blind = [k for k in ("disk", "memory", "processes") if (rep.get(k) or {}).get("state") == UNMEASURED]
        return push_policy.push_critical(EVENT_KEY, "WARNING", "Ресурсы Мака: замер не удался",
                                         owner_body(rep) + "\nне измерено: " + ", ".join(blind),
                                         data_dir=data_dir, dedup_key="unmeasured:" + ",".join(blind), send=send)
    if rep["overall"] == OK:
        return push_policy.resolve(EVENT_KEY, "Ресурсы Мака в норме", owner_body(rep),
                                   data_dir=data_dir, send=send)
    return None


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="resource guard (ADR-551)")
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--no-notify", action="store_true")
    ap.add_argument("--no-protect", action="store_true")
    ap.add_argument("--cleanup", action="store_true", help="list allow-listed disposable dirs past TTL")
    ap.add_argument("--apply", action="store_true", help="with --cleanup: remove them (+ reap worktrees)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--policy", default=None,
                    help="alternative policy file — for drills (e.g. thresholds above the real free space) only")
    a = ap.parse_args(argv)
    from spa_core.utils.live_paths import live_data_dir
    data_dir = Path(a.data_dir) if a.data_dir else live_data_dir()
    policy = load_policy(Path(a.policy)) if a.policy else load_policy()

    if a.cleanup:
        cands = cleanup_candidates(policy)
        res = {"mode": "apply" if a.apply else "dry-run", "candidates": len(cands),
               "gb": round(sum(c["bytes"] or 0 for c in cands) / GB, 2)}
        if a.apply:
            res["removed"] = [d for d in apply_cleanup(cands, policy,
                                                       log_path=data_dir / "resource_cleanup_log.jsonl")
                              if d.get("removed")]
            res["worktrees"] = reap_worktrees(apply=True)
        else:
            res["sample"] = cands[:20]
        res["removed_count"] = len(res.get("removed", []))
        if not a.json:
            res.pop("removed", None)
        print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
        return 0

    rep = build_report(policy, data_dir=Path(data_dir))
    if not a.no_protect:
        rep["protection"] = {"reniced": protect(rep, policy, verify=_same_process),
                             "reserve": manage_reserve(rep["disk"], policy)}
    from spa_core.utils.atomic import atomic_save
    atomic_save(rep, str(data_dir / "resource_health.json"))
    if not a.no_notify:
        notify(rep, data_dir=data_dir)
    print(json.dumps(rep, ensure_ascii=False, indent=1, default=str) if a.json else summary_line(rep))
    return {OK: 0, WARN: 1}.get(rep["overall"], 2)


if __name__ == "__main__":
    sys.exit(main())
