"""ONE bounded probe of the local Ollama provider — prepared, not run (STUDIO-OS-MODELS-01, ARB 2026-10-25).

# LLM_FORBIDDEN

    # future probe (needs the owner's approval; nothing here has been run against a real model):
    python -m spa_core.studio_os.model_roles.probe launch --ollama /usr/local/bin/ollama \
        --model qwen3.5:4b --port 11535 --context <probe_context.md> --out <dir>

Pieces, each with its own refusal:

* **grade** — the answer must be ONE JSON object with exactly four fields, checked by value AND type:
  ``verified_sha`` (str, starts with ``393faa72d``), ``ci_failures`` (``{"count": 2, "cause": "…§49/producer…"}``),
  ``production_routing_enabled`` (``false``), ``ci_result_79fa6e21d`` (``"UNKNOWN"``). A stray "UNKNOWN" or
  "off" in another field earns nothing. Outcomes: PASS · FAIL (named fields) · INCONCLUSIVE (budget spent —
  not evidence of unfitness) · the transport outcome (TIMEOUT, OWNERSHIP_UNRESOLVED, ERROR, REFUSED, …).
* **temp_config** — a TEMPORARY copy of the role configuration with a limited role ``provider_probe``
  (1 attempt, 180 s, 8 000 chars, no tools) and ``ollama_local`` qualified for THAT role only. The canonical
  file is untouched: assignments stay null, ``ollama_local.qualified_roles`` stays empty — not an architect.
* **ResourceGuard** — limits checked BEFORE start and every ``poll_s`` during the run; a violation OR a failed
  measurement stops the probe (fail-closed). RSS is measured for the OWN server's process tree (by pid from
  our own Popen), never by ``pgrep``.
* **child** — starts its OWN ``ollama serve`` on a private loopback port (``OLLAMA_HOST=127.0.0.1:<port>``,
  existing model store, ``OLLAMA_NOPRUNE=1``, one loaded model, ``keep_alive=0``), waits for readiness, runs the
  request through the contract, and ALWAYS stops its own server (SIGTERM → grace → SIGKILL by its own pid). The
  shared server on 11434 and other users' models are never addressed.
* **launch** — runs the child under the existing ``scripts/claude_run_with_timeout.py`` (total deadline; on
  timeout it finishes only processes whose ownership by this run is proven, 124/125), then sweeps any survivor
  carrying OUR ``SPA_RUN_ID`` (positive proof, the helper's own instrument) and reports whether ownership closed.

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
FIELDS = ("verified_sha", "ci_failures", "production_routing_enabled", "ci_result_79fa6e21d")
INSTRUCTION = (
    "Using ONLY the context, answer with ONE JSON object and nothing else, exactly these four keys:\n"
    '{"verified_sha": "<the verified code SHA>", '
    '"ci_failures": {"count": <integer number of failed tests>, "cause": "<why they fail>"}, '
    '"production_routing_enabled": <true or false>, '
    '"ci_result_79fa6e21d": "<the CI result for 79fa6e21d, or UNKNOWN if the context does not establish it>"}')


# ── grade ──────────────────────────────────────────────────────────────────────────────────────────────

def _extract_json(text: str) -> Optional[dict]:
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    cand = m.group(1) if m else text.strip()
    try:
        doc = json.loads(cand)
    except ValueError:
        return None
    return doc if isinstance(doc, dict) else None


def grade_answer(text: str) -> Dict[str, Any]:
    """Field-by-field check of the structured answer. Fails closed on any shape problem."""
    doc = _extract_json(text or "")
    if doc is None:
        return {"outcome": "FAIL", "why": "answer is not exactly one JSON object", "fields": {}}
    fields: Dict[str, str] = {}
    missing = [f for f in FIELDS if f not in doc]
    extra = sorted(set(doc) - set(FIELDS))
    sha = doc.get("verified_sha")
    fields["verified_sha"] = ("ok" if isinstance(sha, str) and re.fullmatch(r"393faa72d[0-9a-f]{0,31}", sha.strip())
                              else "wrong")
    cf = doc.get("ci_failures")
    count = cf.get("count") if isinstance(cf, dict) else None
    cause = cf.get("cause") if isinstance(cf, dict) else None
    fields["ci_failures.count"] = ("ok" if isinstance(count, int) and not isinstance(count, bool) and count == 2
                                   else "wrong")
    fields["ci_failures.cause"] = ("ok" if isinstance(cause, str) and re.search(r"§49|producer", cause, re.I)
                                   else "wrong")
    routing = doc.get("production_routing_enabled")
    fields["production_routing_enabled"] = "ok" if routing is False else "wrong"
    head = doc.get("ci_result_79fa6e21d")
    fields["ci_result_79fa6e21d"] = "ok" if isinstance(head, str) and head.strip().upper() == "UNKNOWN" else "wrong"
    ok = not missing and not extra and all(v == "ok" for v in fields.values()) and len(text) <= 1200
    return {"outcome": "PASS" if ok else "FAIL", "fields": fields, "missing": missing, "extra_keys": extra,
            "chars": len(text)}


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
        m["server_rss_mb"] = tree_rss_mb(server_pid)
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


def run_child(*, ollama: str, model: str, port: int, context: str, out: Path,
              measure: Callable[..., Dict[str, float]] = mac_measure, limits: Optional[Limits] = None,
              ready_timeout_s: float = 30.0, poll_s: float = 2.0, deadline_s: float = TOTAL_DEADLINE_S,
              models_dir: Optional[str] = None) -> Dict[str, Any]:
    guard = ResourceGuard(measure, limits or Limits())
    record: Dict[str, Any] = {"probe": "models01-local-probe-1", "provider": PROVIDER, "model": model,
                              "port": port, "role": PROBE_ROLE}
    try:
        guard.check()                                   # preflight: refuse to start on a breach
    except ProbeAbort as exc:
        record.update(status="refused_preflight", reason=str(exc), samples=guard.samples)
        _save(out, record)
        return record
    env = dict(os.environ, OLLAMA_HOST=f"127.0.0.1:{port}", OLLAMA_NOPRUNE="1", OLLAMA_KEEP_ALIVE="0s",
               OLLAMA_MAX_LOADED_MODELS="1", OLLAMA_NUM_PARALLEL="1")
    if models_dir:
        env["OLLAMA_MODELS"] = models_dir
    server = subprocess.Popen([ollama, "serve"], env=env, stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    record["server_pid"] = server.pid
    stop = threading.Event()
    abort: List[str] = []

    def on_term(signum, frame):  # noqa: ARG001 — interruption: stop our server, then exit
        abort.append(f"interrupted by signal {signum}")
        stop.set()
        _stop_own(server)
        record.update(status="interrupted", reason=abort[0], server_stopped=server.poll() is not None)
        _save(out, record)
        os._exit(3)
    signal.signal(signal.SIGTERM, on_term)

    def watch():
        while not stop.wait(poll_s):
            try:
                guard.check(server.pid)
            except ProbeAbort as exc:
                abort.append(str(exc))
                _stop_own(server)                   # cut the request by stopping OUR server
                return
    try:
        endpoint = f"http://127.0.0.1:{port}"
        t0 = time.monotonic()
        while True:
            guard.check(server.pid)
            try:
                ad._urllib_post_json(endpoint + "/api/show", {"model": model}, 3.0)
                break
            except Exception:  # noqa: BLE001 — not ready yet
                if server.poll() is not None or time.monotonic() - t0 > ready_timeout_s:
                    raise ProbeAbort("own server did not become ready (or model not present locally)")
                time.sleep(0.5)
        proof = ownership_proof(server.pid)
        record["ownership_proof"] = proof
        if not proof["provable"]:
            raise ProbeAbort("ownership of our own server's processes is not provable by the helper's "
                             "instruments — the deadline could not be enforced; probe blocked")
        threading.Thread(target=watch, daemon=True).start()
        cfg = temp_config(load_config())
        res = execute(Request(PROBE_ROLE, "models01-local-probe-1", INSTRUCTION, context, "probe_context.md",
                              deadline_s=deadline_s),
                      config=cfg, provider_id=PROVIDER,
                      adapters={"ollama_http": ad.ollama_http(endpoint=endpoint, model=model)})
        record["result"] = res.to_dict()
        record["status"] = "resource_limit" if abort else res.status
        if abort:
            record["reason"] = abort[0]
    except ProbeAbort as exc:
        reason = str(exc)
        record.update(status=("resource_limit" if any(k in reason for k in ("free memory", "pressure", "swap", "RSS"))
                              else "aborted"), reason=reason)
    finally:
        stop.set()
        record["server_stopped"] = _stop_own(server)
        record["samples"] = guard.samples
        record["grade"] = grade(record["result"]) if "result" in record and not abort else None
        _save(out, record)
    return record


def _save(out: Path, record: Dict[str, Any]) -> None:
    from spa_core.utils.atomic import atomic_save
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    atomic_save(record, str(out))


# ── launch: total deadline + ownership via the existing helper ────────────────────────────────────────

def sweep_run_id(run_id: str, helper=None) -> Dict[str, Any]:
    """Processes still carrying OUR run id (positive proof, the helper's instrument): SIGTERM → SIGKILL,
    then a NEW snapshot. ``closed`` is True only when that snapshot shows none; None — not measured."""
    helper = helper or ad.load_timeout_helper()

    def mine() -> List[int]:
        return sorted(helper._inst_run_id(helper.Snapshot.take(), -1, run_id) - {os.getpid()})
    try:
        found = mine()
        swept = list(found)
        for sig in (signal.SIGTERM, signal.SIGKILL):
            for pid in found:
                try:
                    os.kill(pid, sig)
                except ProcessLookupError:
                    pass
            if found:
                time.sleep(1.0)
                found = mine()
            if not found:
                break
    except Exception as exc:  # noqa: BLE001 — not measured is not closed
        return {"closed": None, "reason": f"ownership not measured: {type(exc).__name__}"}
    return {"closed": not found, "swept": swept, "left": found}


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


def launch(*, ollama: str, model: str, port: int, context_path: Path, out_dir: Path,
           total_deadline_s: float = TOTAL_DEADLINE_S, grace_s: float = 10.0, helper=None,
           child_extra: Optional[List[str]] = None) -> Dict[str, Any]:
    if not 1024 < int(port) < 65536 or int(port) == 11434:
        raise ValueError("port must be a private non-default loopback port (not 11434, the shared server)")
    out_dir.mkdir(parents=True, exist_ok=True)
    record_path = out_dir / "probe_record.json"
    helper = helper or ad.load_timeout_helper()
    run_id = f"models01-probe-{os.getpid()}-{int(time.time())}"
    cmd = [sys.executable, "-m", "spa_core.studio_os.model_roles.probe", "child", "--ollama", ollama,
           "--model", model, "--port", str(port), "--context", str(context_path), "--out", str(record_path),
           "--deadline-s", str(total_deadline_s)] + list(child_extra or [])
    rc = int(helper.run(cmd, timeout_s=total_deadline_s, grace_s=grace_s, log_path=str(out_dir / "helper.log"),
                        label="models01-probe", run_id=run_id))
    sweep = sweep_run_id(run_id, helper)
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        record = {"status": "no_record"}
    if rc == 124:
        record["status"], record["ownership"] = "timeout", "closed (helper 124)"
    elif rc == 125:
        record["status"], record["ownership"] = "ownership_unresolved", "NOT closed (helper 125)"
    elif sweep.get("closed") is True:
        record["ownership"] = "closed" + (f" (swept {sweep['swept']})" if sweep.get("swept") else "")
    else:
        record["status"] = "ownership_unresolved"
        record["ownership"] = f"NOT closed: {sweep.get('left') or sweep.get('reason')}"
    record.update(helper_rc=rc, run_id=run_id)
    _save(record_path, record)
    return record


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="spa_core.studio_os.model_roles.probe")
    ap.add_argument("mode", choices=("launch", "child"))
    ap.add_argument("--ollama", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--context", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--deadline-s", type=float, default=TOTAL_DEADLINE_S)
    ap.add_argument("--fake-measure", default=None, help="TESTS ONLY: JSON list of measurements to replay")
    ap.add_argument("--models-dir", default=None)
    a = ap.parse_args(argv)
    if a.mode == "launch":
        rec = launch(ollama=a.ollama, model=a.model, port=a.port, context_path=a.context, out_dir=a.out,
                     total_deadline_s=a.deadline_s)
        print(json.dumps({k: rec.get(k) for k in ("status", "ownership", "helper_rc", "grade")}, ensure_ascii=False))
        return 0 if (rec.get("grade") or {}).get("outcome") == "PASS" else 1
    measure = mac_measure
    if a.fake_measure:
        seq = json.loads(a.fake_measure)

        def measure(server_pid=None, _s=seq):
            m = _s.pop(0) if len(_s) > 1 else _s[0]
            if m == "error":
                raise MeasurementError("fake measurement failure")
            return dict(m)
    rec = run_child(ollama=a.ollama, model=a.model, port=a.port, context=a.context.read_text(encoding="utf-8"),
                    out=a.out, measure=measure, deadline_s=a.deadline_s, models_dir=a.models_dir, poll_s=0.5)
    return 0 if rec.get("status") == "ok" else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
