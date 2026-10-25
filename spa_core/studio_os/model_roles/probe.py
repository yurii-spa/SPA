"""ONE bounded probe of the local Ollama provider — prepared, not run (STUDIO-OS-MODELS-01, ARB 2026-10-25).

# LLM_FORBIDDEN

    # future probe (needs the owner's approval; nothing here has been run against a real model):
    python -m spa_core.studio_os.model_roles.probe prepare-store --model qwen3.5:4b --models-dir <new dir> --out <dir>
    python -m spa_core.studio_os.model_roles.probe launch --ollama /usr/local/bin/ollama \
        --model qwen3.5:4b --port 11535 --context <probe_context.md> --out <dir> --models-dir <same dir>

Pieces, each with its own refusal:

* **grade** — the answer must be ONE JSON object with exactly four fields, checked by value AND type:
  ``verified_sha`` (exactly the full ``393faa72d1…cd80`` or ``393faa72d``), ``ci_failures``
  (``{"count": 2, "cause": "s49_producer_not_installed"}`` — the fixed value named in the instruction),
  ``production_routing_enabled`` (``false``), ``ci_result_79fa6e21d`` (``"UNKNOWN"``). A stray "UNKNOWN" or
  "off" in another field earns nothing; duplicate keys, extra fields and any text outside the one object
  (one fence allowed) fail. Outcomes: PASS · FAIL (named fields) · INCONCLUSIVE (budget spent —
  not evidence of unfitness) · the transport outcome (TIMEOUT, OWNERSHIP_UNRESOLVED, ERROR, REFUSED, …).
* **temp_config** — a TEMPORARY copy of the role configuration with a limited role ``provider_probe``
  (1 attempt, 180 s, 8 000 chars, no tools) and ``ollama_local`` qualified for THAT role only. The canonical
  file is untouched: assignments stay null, ``ollama_local.qualified_roles`` stays empty — not an architect.
* **ResourceGuard** — limits checked BEFORE start and every ``poll_s`` during the run; a violation OR a failed
  measurement stops the probe (fail-closed). RSS is measured for OUR processes: the own server's tree (by pid
  from our own Popen) plus any process carrying our run label (a detached runner), never by ``pgrep``.
* **child** — starts its OWN ``ollama serve`` on a private loopback port (``OLLAMA_HOST=127.0.0.1:<port>``,
  a PRIVATE model store copied by ``prepare-store`` — never ``~/.ollama/models``; ``OLLAMA_NOPRUNE=1``, one loaded model, ``keep_alive=0``), waits for readiness, runs the
  request through the contract (a busy port, or a listener that is not ours, is refused before any request;
  redirects are never followed), and ALWAYS stops its own server (SIGTERM → grace → SIGKILL by its own pid). The
  shared server on 11434 and other users' models are never addressed.
* **launch** — runs the child under the existing ``scripts/claude_run_with_timeout.py`` (total deadline; on
  timeout it finishes only processes whose ownership by this run is proven, 124/125), then sweeps any survivor
  carrying OUR unique ``SPA_RUN_ID`` with the helper's own ``census``/``_terminate`` (ownership re-checked before
  every signal). ONE ``verdict`` decides the record AND the exit code: status ok, grade PASS, server stopped,
  ownership closed — all four, or it is not a success.

A PASS proves only this scenario (short fixed context, four questions), not fitness for the architect role.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from spa_core.studio_os.model_roles import adapters as ad
from spa_core.studio_os.model_roles.contract import Request, execute, load_config

PROBE_ROLE = "provider_probe"
PROVIDER = "ollama_local"
TOTAL_DEADLINE_S = 180.0
WATCHER_THREAD = "probe-resource-watch"
FIELDS = ("verified_sha", "ci_failures", "production_routing_enabled", "ci_result_79fa6e21d")
CAUSE_VALUE = "s49_producer_not_installed"
VERIFIED_FULL = "393faa72d112007eb1031b63fc43313fb377cd80"
VERIFIED_SHORT = "393faa72d"
INSTRUCTION = (
    "Using ONLY the context, answer with ONE JSON object and nothing else (no prose before or after), "
    "exactly these four keys:\n"
    '{"verified_sha": "<the verified code SHA exactly as written in the context>", '
    '"ci_failures": {"count": <integer number of failed tests>, '
    '"cause": "s49_producer_not_installed" if the context says the failures are because the §49 producer is not '
    'installed, otherwise "other"}, '
    '"production_routing_enabled": <true or false>, '
    '"ci_result_79fa6e21d": "<the CI result for 79fa6e21d, or UNKNOWN if the context does not establish it>"}')


# ── grade ──────────────────────────────────────────────────────────────────────────────────────────────

class _DuplicateKey(ValueError):
    pass


def _no_duplicates(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise _DuplicateKey(k)
        out[k] = v
    return out


def _extract_json(text: str) -> Optional[dict]:
    """The WHOLE answer must be one JSON object — bare, or alone inside ONE fence. Anything outside, a second
    object, or a repeated key ⇒ None (the answer is rejected, not repaired)."""
    t = (text or "").strip()
    m = re.fullmatch(r"```(?:json)?[ \t]*\n(.*?)\n?```", t, re.S)
    body = m.group(1).strip() if m else t
    if not (body.startswith("{") and body.endswith("}")):
        return None
    try:
        doc = json.loads(body, object_pairs_hook=_no_duplicates)
    except ValueError:                      # includes _DuplicateKey and trailing data
        return None
    return doc if isinstance(doc, dict) else None


def grade_answer(text: str) -> Dict[str, Any]:
    """Field-by-field check of the structured answer. Exact values and types; fails closed on any shape problem."""
    doc = _extract_json(text or "")
    if doc is None:
        return {"outcome": "FAIL", "why": "answer is not exactly one JSON object (no outside text, no repeated "
                                          "keys)", "fields": {}}
    fields: Dict[str, str] = {}
    missing = [f for f in FIELDS if f not in doc]
    extra = sorted(set(doc) - set(FIELDS))
    sha = doc.get("verified_sha")
    fields["verified_sha"] = "ok" if isinstance(sha, str) and sha in (VERIFIED_FULL, VERIFIED_SHORT) else "wrong"
    cf = doc.get("ci_failures")
    cf_extra = sorted(set(cf) - {"count", "cause"}) if isinstance(cf, dict) else []
    count = cf.get("count") if isinstance(cf, dict) else None
    cause = cf.get("cause") if isinstance(cf, dict) else None
    fields["ci_failures.count"] = ("ok" if isinstance(count, int) and not isinstance(count, bool) and count == 2
                                   else "wrong")
    fields["ci_failures.cause"] = "ok" if cause == CAUSE_VALUE else "wrong"
    routing = doc.get("production_routing_enabled")
    fields["production_routing_enabled"] = "ok" if routing is False else "wrong"
    head = doc.get("ci_result_79fa6e21d")
    fields["ci_result_79fa6e21d"] = "ok" if head == "UNKNOWN" else "wrong"
    ok = (not missing and not extra and not cf_extra and all(v == "ok" for v in fields.values())
          and len(text) <= 1200)
    return {"outcome": "PASS" if ok else "FAIL", "fields": fields, "missing": missing,
            "extra_keys": extra + [f"ci_failures.{k}" for k in cf_extra], "chars": len(text)}


def grade(record: Dict[str, Any]) -> Dict[str, Any]:
    """Outcome of a contract Result (dict). Budget exhaustion is INCONCLUSIVE, never FAIL."""
    st = record.get("status")
    if st == "ok":
        return grade_answer(record.get("text") or "")
    if st == "malformed" and "budget_exhausted" in str(record.get("reason")):
        return {"outcome": "INCONCLUSIVE", "why": record.get("reason")}
    return {"outcome": str(st or "error").upper(), "why": record.get("reason")}


# ── temporary configuration ───────────────────────────────────────────────────────────────────────────

def temp_config(canonical: Dict[str, Any]) -> Dict[str, Any]:
    """A copy with role ``provider_probe``; ``ollama_local`` qualified for it ONLY. Canonical untouched."""
    cfg = copy.deepcopy(canonical)
    cfg["roles"][PROBE_ROLE] = {"description": "ONE bounded provider probe — not a role admission",
                                "permissions": ["read_context_pack", "answer_text"], "tools": [],
                                "requires": ["text"], "max_context_chars": 8000,
                                "deadline_s": TOTAL_DEADLINE_S, "max_attempts": 1}
    cfg["providers"][PROVIDER]["qualified_roles"] = [PROBE_ROLE]
    cfg["assignments"] = {k: None for k in cfg.get("assignments") or {}}
    return cfg


# ── resources ─────────────────────────────────────────────────────────────────────────────────────────

class ProbeAbort(Exception):
    """The probe must stop now (limit breached or the measurement failed)."""


class MeasurementError(RuntimeError):
    """A resource measurement could not be taken — the guard turns it into a stop."""


class StoreError(ValueError):
    """The private model store could not be prepared safely."""


@dataclass
class Limits:
    min_free_pct: float = 40.0
    max_pressure_level: int = 1
    max_swap_growth_mb: float = 1024.0
    max_server_rss_mb: float = 6144.0


def _run(cmd: List[str], timeout: float = 10.0) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise MeasurementError(f"{cmd[0]} rc={p.returncode}")
    return p.stdout


def tree_rss_mb(root_pid: int, ps_out: Optional[str] = None) -> float:
    """RSS (MB) of ``root_pid`` and its descendants — by our own pid, not by process name."""
    out = ps_out if ps_out is not None else _run(["ps", "-A", "-o", "pid=,ppid=,rss="])
    rows = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3 and all(x.isdigit() for x in parts):
            rows[int(parts[0])] = (int(parts[1]), int(parts[2]))
    if root_pid not in rows:
        raise MeasurementError(f"server pid {root_pid} not found in the process table")
    keep, frontier = {root_pid}, [root_pid]
    while frontier:
        cur = frontier.pop()
        for pid, (ppid, _rss) in rows.items():
            if ppid == cur and pid not in keep:
                keep.add(pid)
                frontier.append(pid)
    return sum(rows[p][1] for p in keep) / 1024.0


def owned_pids(server_pid: int, helper=None) -> List[int]:
    """Our processes: the server's tree AND every process carrying OUR run id — a runner that detached
    (re-parented to init, own session) is still counted. Measurement failure raises."""
    helper = helper or ad.load_timeout_helper()
    run_id = os.environ.get(helper.RUN_ID_VAR, "")
    try:
        snap = helper.Snapshot.take()
    except Exception as exc:  # noqa: BLE001
        raise MeasurementError(f"process table not read: {type(exc).__name__}") from exc
    pids = {server_pid} | helper._inst_tree(snap, server_pid, run_id)
    if run_id:
        pids |= helper._inst_run_id(snap, -1, run_id)
    pids.discard(os.getpid())
    return sorted(pids)


def rss_mb(pids: List[int], ps_out: Optional[str] = None) -> float:
    out = ps_out if ps_out is not None else _run(["ps", "-A", "-o", "pid=,rss="])
    rows = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and all(x.isdigit() for x in parts):
            rows[int(parts[0])] = int(parts[1])
    return sum(rows.get(p, 0) for p in pids) / 1024.0


def mac_measure(server_pid: Optional[int] = None) -> Dict[str, float]:
    """Real measurement on macOS. Any failure raises — the guard turns it into a stop."""
    free = re.search(r"free percentage:\s*(\d+)%", _run(["memory_pressure"]))
    level = _run(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"]).strip()
    swap = re.search(r"used = ([\d.,]+)M", _run(["sysctl", "-n", "vm.swapusage"]))
    if not (free and level.isdigit() and swap):
        raise MeasurementError("memory measurement not parsed")
    m = {"free_pct": float(free.group(1)), "pressure_level": int(level),
         "swap_used_mb": float(swap.group(1).replace(",", "."))}
    if server_pid is not None:
        m["server_rss_mb"] = rss_mb(owned_pids(server_pid))
    return m


class ResourceGuard:
    def __init__(self, measure: Callable[..., Dict[str, float]], limits: Limits):
        self.measure, self.limits = measure, limits
        self.base_swap: Optional[float] = None
        self.samples: List[Dict[str, Any]] = []

    def check(self, server_pid: Optional[int] = None) -> Dict[str, float]:
        try:
            m = self.measure(server_pid)
        except Exception as exc:  # noqa: BLE001 — a failed measurement is a STOP, never a pass
            raise ProbeAbort(f"resource measurement failed: {type(exc).__name__}: {exc}") from exc
        self.samples.append(dict(m, t=time.time()))
        if self.base_swap is None:
            self.base_swap = m["swap_used_mb"]
        lim = self.limits
        if m["free_pct"] < lim.min_free_pct:
            raise ProbeAbort(f"free memory {m['free_pct']}% < {lim.min_free_pct}%")
        if m["pressure_level"] > lim.max_pressure_level:
            raise ProbeAbort(f"memory pressure level {m['pressure_level']} > {lim.max_pressure_level}")
        if m["swap_used_mb"] - self.base_swap > lim.max_swap_growth_mb:
            raise ProbeAbort(f"swap grew {m['swap_used_mb'] - self.base_swap:.0f} MB > {lim.max_swap_growth_mb:.0f} MB")
        if m.get("server_rss_mb", 0.0) > lim.max_server_rss_mb:
            raise ProbeAbort(f"server RSS {m['server_rss_mb']:.0f} MB > {lim.max_server_rss_mb:.0f} MB")
        return m


# ── child: own server, one request, always stop own server ────────────────────────────────────────────

def _stop_own(proc: subprocess.Popen, grace_s: float = 5.0) -> bool:
    """Stop OUR server by its own pid (never by name, never `ollama stop`). True — it is gone."""
    if proc.poll() is not None:
        return True
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=grace_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=grace_s)
        except subprocess.TimeoutExpired:
            return False
    return True


SHARED_STORE = Path.home() / ".ollama" / "models"


def port_is_free(port: int) -> bool:
    import socket
    sk = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sk.bind(("127.0.0.1", int(port)))
        return True
    except OSError:
        return False
    finally:
        sk.close()


def listener_pids(port: int) -> List[int]:
    """Pids LISTENING on 127.0.0.1:<port> (lsof, else ss). Not measurable ⇒ MeasurementError (fail-closed)."""
    for cmd, rx in ((["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"], r"^(\d+)$"),
                    (["ss", "-H", "-ltnp", f"sport = :{port}"], r"pid=(\d+)")):
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            continue
        if p.returncode not in (0, 1):
            continue
        found = sorted({int(x) for x in re.findall(rx, p.stdout, re.M)})
        if found or p.returncode == 0:
            return found
    raise MeasurementError(f"listener of port {port} not measurable (no lsof/ss answer)")


def run_child(*, ollama: str, model: str, port: int, context: str, out: Path, models_dir: Optional[str],
              measure: Callable[..., Dict[str, float]] = mac_measure, limits: Optional[Limits] = None,
              ready_timeout_s: float = 30.0, poll_s: float = 2.0,
              deadline_s: float = TOTAL_DEADLINE_S) -> Dict[str, Any]:
    guard = ResourceGuard(measure, limits or Limits())
    record: Dict[str, Any] = {"probe": "models01-local-probe-1", "provider": PROVIDER, "model": model,
                              "port": port, "role": PROBE_ROLE, "models_dir": models_dir}

    def refuse(status: str, reason: str) -> Dict[str, Any]:
        record.update(status=status, reason=reason, samples=guard.samples)
        record["verdict"] = verdict(record)
        _save(out, record)
        return record
    # ── isolation BEFORE anything starts
    if not models_dir:
        return refuse("refused_preflight", "no private model store given (--models-dir) — the shared store is "
                                           "never used")
    md = Path(models_dir).resolve()
    if md == SHARED_STORE.resolve() or SHARED_STORE.resolve() in md.parents:
        return refuse("refused_preflight", "models dir is the shared Ollama store — use a private copy")
    if not port_is_free(port):
        return refuse("refused_preflight", f"port {port} is already in use — not our instance")
    try:
        guard.check()                                   # preflight: refuse to start on a breach
    except ProbeAbort as exc:
        return refuse("refused_preflight", str(exc))
    env = dict(os.environ, OLLAMA_HOST=f"127.0.0.1:{port}", OLLAMA_NOPRUNE="1", OLLAMA_KEEP_ALIVE="0s",
               OLLAMA_MAX_LOADED_MODELS="1", OLLAMA_NUM_PARALLEL="1", OLLAMA_MODELS=str(md))
    server = subprocess.Popen([ollama, "serve"], env=env, stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    record["server_pid"] = server.pid
    stop = threading.Event()
    abort: List[str] = []

    def on_term(signum, frame):  # noqa: ARG001 — interruption: stop our server, then exit
        abort.append(f"interrupted by signal {signum}")
        stop.set()
        record.update(status="interrupted", reason=abort[0], server_stopped=_stop_own(server))
        record["verdict"] = verdict(record)
        _save(out, record)
        os._exit(3)
    signal.signal(signal.SIGTERM, on_term)

    def watch():
        try:
            while not stop.wait(poll_s):
                guard.check(server.pid)
        except ProbeAbort as exc:
            abort.append(str(exc))
            _stop_own(server)                       # cut the request by stopping OUR server
        except Exception as exc:  # noqa: BLE001 — a crashed watcher is a stop, and its error is kept
            abort.append(f"resource watcher failed: {type(exc).__name__}: {exc}")
            _stop_own(server)
    watcher = threading.Thread(target=watch, name=WATCHER_THREAD, daemon=True)
    try:
        endpoint = f"http://127.0.0.1:{port}"
        t0 = time.monotonic()
        while True:
            guard.check(server.pid)
            try:
                ad._urllib_post_json(endpoint + "/api/version", {}, 3.0, method="GET")
                break
            except Exception:  # noqa: BLE001 — not ready yet
                if server.poll() is not None or time.monotonic() - t0 > ready_timeout_s:
                    raise ProbeAbort("own server did not become ready")
                time.sleep(0.5)
        mine = set(owned_pids(server.pid))
        listeners = listener_pids(port)
        record["endpoint_listeners"] = listeners
        if not listeners or not set(listeners) <= mine:
            raise ProbeAbort(f"endpoint 127.0.0.1:{port} is not served by our instance (listeners {listeners})")
        proof = ownership_proof(server.pid)
        record["ownership_proof"] = proof
        if not proof["provable"]:
            raise ProbeAbort("ownership of our own server's processes is not provable by the helper's "
                             "instruments — the deadline could not be enforced; probe blocked")
        watcher.start()
        cfg = temp_config(load_config())
        res = execute(Request(PROBE_ROLE, "models01-local-probe-1", INSTRUCTION, context, "probe_context.md",
                              deadline_s=deadline_s),
                      config=cfg, provider_id=PROVIDER,
                      adapters={"ollama_http": ad.ollama_http(endpoint=endpoint, model=model)})
        record["result"] = res.to_dict()
        record["status"] = res.status
    except ProbeAbort as exc:
        reason = str(exc)
        record.update(status=("resource_limit" if any(k in reason for k in ("free memory", "pressure", "swap", "RSS"))
                              else "aborted"), reason=reason)
    except MeasurementError as exc:
        record.update(status="aborted", reason=f"measurement failed: {exc}")
    finally:
        stop.set()
        if watcher.is_alive():
            watcher.join(timeout=max(poll_s * 3, 5.0))
        if watcher.is_alive():
            abort.append("resource watcher did not stop")
        if abort:                                       # the watcher's verdict is never lost
            record["status"] = ("resource_limit" if any(k in abort[0] for k in ("free memory", "pressure", "swap", "RSS"))
                                else "aborted")
            record["reason"] = abort[0]
        record["server_stopped"] = _stop_own(server)
        record["samples"] = guard.samples
        record["grade"] = grade(record["result"]) if "result" in record else None
        record["verdict"] = verdict(record)
        _save(out, record)
    return record


def verdict(record: Dict[str, Any]) -> Dict[str, Any]:
    """ONE criterion for the record AND the exit code. Success needs ALL of: provider status ok, grade PASS,
    no resource/abort status, our server stopped, and — once launched — ownership confirmed closed.
    The answer's quality grade stays separate (``grade``) and never makes the probe a success by itself."""
    reasons = []
    if record.get("status") != "ok":
        reasons.append(f"status {record.get('status')}")
    if (record.get("grade") or {}).get("outcome") != "PASS":
        reasons.append(f"grade {(record.get('grade') or {}).get('outcome')}")
    if record.get("server_stopped") is not True:
        reasons.append("own server stop not confirmed")
    if "ownership_closed" in record and record["ownership_closed"] is not True:
        reasons.append("ownership not confirmed closed")
    return {"success": not reasons, "reasons": reasons}


def _save(out: Path, record: Dict[str, Any]) -> None:
    from spa_core.utils.atomic import atomic_save
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    atomic_save(record, str(out))


# ── launch: total deadline + ownership via the existing helper ────────────────────────────────────────

def sweep_run_id(run_id: str, run_age_s: float, helper=None, log_path: Optional[str] = None) -> Dict[str, Any]:
    """Finish processes PROVEN ours by the helper's full census (run-id instrument, age not older than the run,
    never pid 1 / ourselves / our session / zombies), re-checked right before each signal by the helper's own
    ``_terminate``; then a NEW census. ``closed`` True only when it finds none; None — not measured."""
    helper = helper or ad.load_timeout_helper()
    inst = {"run_id": helper._inst_run_id}
    me, my_sid = os.getpid(), os.getsid(0)
    log = helper.Log(log_path)
    try:
        owned = helper.census(-1, run_id, run_age_s, self_pid=me, self_sid=my_sid, instruments=inst)
        swept = [o.pid for o in owned]
        for sig in (signal.SIGTERM, signal.SIGKILL):
            if not owned:
                break
            helper._terminate(owned, sig, log, run_id, -1, run_age_s, me, my_sid, inst)
            time.sleep(1.0)
            owned = helper.census(-1, run_id, run_age_s, self_pid=me, self_sid=my_sid, instruments=inst)
    except Exception as exc:  # noqa: BLE001 — not measured is not closed
        return {"closed": None, "reason": f"ownership not measured: {type(exc).__name__}"}
    return {"closed": not owned, "swept": swept, "left": [o.pid for o in owned]}


def ownership_proof(server_pid: int, helper=None) -> Dict[str, Any]:
    """Can the helper SEE our server and its descendants? Needed before the run, or the deadline can't be
    proven. Uses the helper's own instruments (run id in the environment · same session)."""
    helper = helper or ad.load_timeout_helper()
    run_id = os.environ.get(helper.RUN_ID_VAR, "")
    snap = helper.Snapshot.take()
    tree = {server_pid} | helper._inst_tree(snap, server_pid, run_id)
    by_run_id = helper._inst_run_id(snap, -1, run_id) if run_id else set()
    sid = os.getsid(0)
    by_session = {p for p in tree if helper._safe_sid(p) == sid}
    seen = {p: [n for n, ok in (("run_id", p in by_run_id), ("session", p in by_session)) if ok] for p in tree}
    return {"run_id_set": bool(run_id), "processes": len(tree), "seen": seen,
            "provable": bool(run_id) and all(seen[p] for p in tree)}


def launch(*, ollama: str, model: str, port: int, context_path: Path, out_dir: Path, models_dir: Path,
           total_deadline_s: float = TOTAL_DEADLINE_S, grace_s: float = 10.0, helper=None,
           child_extra: Optional[List[str]] = None) -> Dict[str, Any]:
    import uuid
    if not 1024 < int(port) < 65536 or int(port) == 11434:
        raise ValueError("port must be a private non-default loopback port (not 11434, the shared server)")
    out_dir.mkdir(parents=True, exist_ok=True)
    record_path = out_dir / "probe_record.json"
    helper = helper or ad.load_timeout_helper()
    run_id = f"models01-probe-{uuid.uuid4().hex}"           # unique per run
    cmd = [sys.executable, "-m", "spa_core.studio_os.model_roles.probe", "child", "--ollama", ollama,
           "--model", model, "--port", str(port), "--context", str(context_path), "--out", str(record_path),
           "--deadline-s", str(total_deadline_s), "--models-dir", str(models_dir)] + list(child_extra or [])
    t0 = time.monotonic()
    rc = int(helper.run(cmd, timeout_s=total_deadline_s, grace_s=grace_s, log_path=str(out_dir / "helper.log"),
                        label="models01-probe", run_id=run_id))
    sweep = sweep_run_id(run_id, time.monotonic() - t0 + 5.0, helper, str(out_dir / "helper.log"))
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        record = {"status": "no_record"}
    closed = sweep.get("closed") is True and rc != 125
    record["ownership_closed"] = closed
    record["ownership"] = {"helper_rc": rc, "sweep": sweep,
                           "summary": "closed" if closed else "NOT closed (or not measured)"}
    if rc == 124:
        record["status"] = "timeout" if closed else "ownership_unresolved"
    elif rc == 125 or not closed:
        record["status"] = "ownership_unresolved"
    record.update(helper_rc=rc, run_id=run_id)
    record["verdict"] = verdict(record)
    _save(record_path, record)
    return record


def prepare_private_store(src: Path, model: str, dest: Path, *, max_bytes: Optional[int] = None) -> Dict[str, Any]:
    """Private copy of ONE model (manifest + its blobs) — real copies, never hard links; every blob's sha256
    is verified against its digest. ``dest`` must not exist yet (nothing is overwritten)."""
    import hashlib
    import shutil
    name, _, tag = model.partition(":")
    rel = Path("manifests") / "registry.ollama.ai" / "library" / name / (tag or "latest")
    man = Path(src) / rel
    doc = json.loads(man.read_text(encoding="utf-8"))
    digests = [doc["config"]["digest"]] + [layer["digest"] for layer in doc.get("layers") or []]
    total = sum((Path(src) / "blobs" / d.replace(":", "-")).stat().st_size for d in digests)
    if max_bytes is not None and total > max_bytes:
        raise StoreError(f"model blobs {total} bytes > allowed {max_bytes}")
    dest = Path(dest)
    if dest.exists():
        raise StoreError(f"{dest} already exists — nothing is overwritten")
    (dest / rel).parent.mkdir(parents=True)
    (dest / "blobs").mkdir()
    shutil.copyfile(man, dest / rel)
    for d in digests:
        s_blob, d_blob = Path(src) / "blobs" / d.replace(":", "-"), dest / "blobs" / d.replace(":", "-")
        shutil.copyfile(s_blob, d_blob)                     # a real copy (copyfile never links)
        if os.stat(d_blob).st_ino == os.stat(s_blob).st_ino:
            raise StoreError("copy shares an inode with the source")
        h = hashlib.sha256()
        with open(d_blob, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        if "sha256:" + h.hexdigest() != d:
            raise StoreError(f"copied blob {d} does not match its digest")
    return {"model": model, "dest": str(dest), "blobs": len(digests), "bytes": total}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="spa_core.studio_os.model_roles.probe")
    ap.add_argument("mode", choices=("launch", "child", "prepare-store"))
    ap.add_argument("--ollama")
    ap.add_argument("--model", required=True)
    ap.add_argument("--port", type=int)
    ap.add_argument("--context", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--deadline-s", type=float, default=TOTAL_DEADLINE_S)
    ap.add_argument("--models-dir", type=Path, default=None, help="PRIVATE model store (never the shared one)")
    ap.add_argument("--source-store", type=Path, default=SHARED_STORE, help="prepare-store: copy FROM here")
    ap.add_argument("--fake-measure", default=None, help="TESTS ONLY: JSON list of measurements to replay")
    a = ap.parse_args(argv)
    if a.mode == "prepare-store":
        if not a.models_dir:
            print("REFUSED: --models-dir (the new private store) is required")
            return 2
        try:
            print(json.dumps(prepare_private_store(a.source_store, a.model, a.models_dir), ensure_ascii=False))
        except (StoreError, OSError, KeyError, ValueError) as exc:
            print(f"STORE NOT PREPARED: {type(exc).__name__}: {exc}")
            return 2
        return 0
    if a.mode == "launch":
        if not a.models_dir:
            print("REFUSED: --models-dir (a private store prepared by `prepare-store`) is required")
            return 2
        extra = ["--fake-measure", a.fake_measure] if a.fake_measure else []
        rec = launch(ollama=a.ollama, model=a.model, port=a.port, context_path=a.context, out_dir=a.out,
                     models_dir=a.models_dir, total_deadline_s=a.deadline_s, child_extra=extra)
        print(json.dumps({k: rec.get(k) for k in ("status", "verdict", "grade", "ownership")}, ensure_ascii=False))
        return 0 if rec["verdict"]["success"] else 1
    measure = mac_measure
    if a.fake_measure:
        seq = json.loads(a.fake_measure)
        last: List[Any] = [None]

        def fake_measure(server_pid=None, _s=seq):
            head = _s[0]
            if isinstance(head, dict) and "in_watcher" in head:     # a sample only the resource watcher sees
                m = head["in_watcher"] if threading.current_thread().name == WATCHER_THREAD else last[0]
            else:
                m = _s.pop(0) if len(_s) > 1 else head
            last[0] = m
            if m == "error":
                raise MeasurementError("fake measurement failure")
            if server_pid is not None:
                owned_pids(server_pid)          # the real ownership walk still runs (and may fail)
            return dict(m)
        measure = fake_measure
    rec = run_child(ollama=a.ollama, model=a.model, port=a.port, context=a.context.read_text(encoding="utf-8"),
                    out=a.out, measure=measure, deadline_s=a.deadline_s,
                    models_dir=str(a.models_dir) if a.models_dir else None, poll_s=0.5)
    return 0 if rec["verdict"]["success"] else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
