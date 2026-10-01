"""Agent passports — «why does this agent exist?» answered from evidence, not from chat.

One passport per agent, ASSEMBLED (never a second registry) from:
    architecture/manifest.json      label, role, layer, schedule, program, produces/consumes and the
                                    curated `passport` {goal, quality_metric, escalation, rights, limits,
                                    why, created_by, forbidden, supersedes, superseded_by, last_verified}
    the agent's own code            ADR / owner-directive references in the wrapper and module docstring
    architecture/memory_truth.json  facts about the agent (e.g. the mission_tick pause) and agents that
                                    live outside the SPA manifest (Studio Bridge services)
    launchd (when measured)         loaded / running / intentionally disabled
Every field carries its origin: EXPLICIT (curated, cites a source) · DERIVED (read from code/config) ·
MEASURED (live) · UNKNOWN. A missing «why» is reported as UNKNOWN — never invented.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from . import sources as src

_ADR = re.compile(r"\bADR-B?\d[\w.]*\b")
FIELDS = ("agent_id", "name", "domain", "purpose", "why", "created_by", "owner_role", "inputs", "outputs",
          "permissions", "forbidden", "dependencies", "runtime", "schedule", "state_reads", "state_writes",
          "status", "supersedes", "superseded_by", "related", "last_verified")


def _json(p: Path):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _f(value, origin: str, source: Optional[str] = None) -> Dict:
    if value in (None, "", [], {}):
        return {"value": None, "origin": "UNKNOWN", "source": source}
    return {"value": value, "origin": origin, "source": source}


def _code_refs(spa_root: Path, program: Optional[str]) -> Dict:
    """ADR refs + module named in the agent's wrapper, and the module docstring's refs."""
    if not program:
        return {}
    wrapper = spa_root / "scripts" / program
    try:
        w = wrapper.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    m = re.search(r'MODULE="([\w.]+)"', w)
    module = m.group(1) if m else None
    text = w
    if module:
        cand = [spa_root / (module.replace(".", "/") + ".py"), spa_root / module.replace(".", "/") / "__init__.py",
                spa_root / module.replace(".", "/") / "__main__.py"]
        for c in cand:
            try:
                head = c.read_text(encoding="utf-8", errors="replace")[:6000]
            except OSError:
                continue
            doc = re.search(r'^\s*(?:"""|\'\'\')(.*?)(?:"""|\'\'\')', head, re.S)
            text += "\n" + (doc.group(1) if doc else head[:1500])
    return {"module": module, "adr_refs": sorted(set(_ADR.findall(text)))[:12],
            "source": f"scripts/{program}" + (f" + {module}" if module else "")}


def _mentioned_in(spa: Path, label: str, limit: int = 3) -> List[str]:
    hits = []
    for p in sorted((spa / "docs" / "decisions").glob("ADR-*.md"),
                    key=lambda x: int(re.search(r"ADR-(\d+)", x.name).group(1)) if re.search(r"ADR-(\d+)", x.name) else 9999):
        try:
            if re.search(re.escape(label) + r"(?![\w.-])", p.read_text(encoding="utf-8", errors="replace")):
                hits.append(p.name.split("-")[0] + "-" + p.name.split("-")[1])
        except OSError:
            continue
        if len(hits) >= limit:
            break
    return hits


def _launchd() -> Dict[str, Dict]:
    out: Dict[str, Dict] = {}
    try:
        lst = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=10).stdout
        dis = subprocess.run(["launchctl", "print-disabled", f"gui/{__import__('os').getuid()}"],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return out
    for line in lst.splitlines()[1:]:
        p = line.split("\t")
        if len(p) == 3:
            out[p[2]] = {"loaded": True, "running": p[0].strip().isdigit(), "last_exit": p[1]}
    for lbl in re.findall(r'"([^"]+)"\s*=>\s*(?:disabled|true)', dis):
        out.setdefault(lbl, {"loaded": False})["disabled"] = True
    return out


def passport(label: str, *, measure_host: bool = False) -> Dict:
    spa = src.roots()["spa"]
    man = _json(spa / "architecture" / "manifest.json") or {}
    truth = _json(spa / "architecture" / "memory_truth.json") or {}
    a = next((x for x in man.get("agents", []) if x.get("label") == label), None)
    ext = next((x for x in truth.get("agents", []) if x.get("label") == label), None)
    facts = [f for f in truth.get("facts", []) if f.get("subject") == label]
    if a is None and ext is None:
        return {"agent_id": label, "found": False, "status": "UNKNOWN",
                "note": "no such agent in architecture/manifest.json or memory_truth.json agents"}
    pp = dict((a or {}).get("passport") or {})
    pp.update((ext or {}).get("passport") or {})
    base = a or ext
    code = _code_refs(spa, base.get("program")) if a else {}
    src_man = "architecture/manifest.json" if a else "architecture/memory_truth.json#agents"
    live = _launchd().get(label) if measure_host else None
    if live:
        status = _f("intentionally disabled (paused)" if live.get("disabled") and not live.get("loaded")
                    else ("running" if live.get("running") else "loaded, idle" if live.get("loaded") else "not loaded"),
                    "MEASURED", "launchctl")
    else:
        status = _f(base.get("intent"), "DERIVED", src_man)
    created = pp.get("created_by") or []
    mentioned = [] if (created or code.get("adr_refs")) else _mentioned_in(spa, label)
    p = {
        "agent_id": _f(label, "EXPLICIT", src_man),
        "name": _f(pp.get("name") or base.get("program"), "DERIVED", src_man),
        "domain": _f(pp.get("domain") or base.get("layer"), "DERIVED", src_man),
        "purpose": _f(pp.get("goal"), "EXPLICIT", src_man),
        "why": _f(pp.get("why"), "EXPLICIT", src_man),
        "created_by": _f(created, "EXPLICIT", src_man) if created else
                      _f(code.get("adr_refs"), "DERIVED", code.get("source")) if code.get("adr_refs") else
                      _f(mentioned, "HEURISTIC", "earliest canonical ADRs naming the label — «mentioned in», not «created by»"),
        "owner_role": _f(pp.get("owner_role") or base.get("role"), "DERIVED", src_man),
        "inputs": _f([c.get("artifact", c) if isinstance(c, dict) else c for c in base.get("consumes") or []]
                     or pp.get("inputs"), "DERIVED", src_man),
        "outputs": _f([c.get("artifact", c) if isinstance(c, dict) else c for c in base.get("produces") or []]
                      or pp.get("outputs"), "DERIVED", src_man),
        "permissions": _f(pp.get("rights"), "EXPLICIT", src_man),
        "forbidden": _f(pp.get("forbidden") or pp.get("limits"), "EXPLICIT", src_man),
        "dependencies": _f(pp.get("dependencies"), "EXPLICIT", src_man),
        "runtime": _f(base.get("program") + (f" → python -m {code['module']}" if code.get("module") else "")
                      if base.get("program") else None, "DERIVED", code.get("source") or src_man),
        "schedule": _f(base.get("schedule"), "DERIVED", src_man),
        "state_reads": _f([c.get("artifact", c) if isinstance(c, dict) else c for c in base.get("consumes") or []],
                          "DERIVED", src_man),
        "state_writes": _f([c.get("artifact", c) if isinstance(c, dict) else c for c in base.get("produces") or []],
                           "DERIVED", src_man),
        "status": status,
        "supersedes": _f(pp.get("supersedes"), "EXPLICIT", src_man),
        "superseded_by": _f(pp.get("superseded_by"), "EXPLICIT", src_man),
        "related": _f(sorted(set((code.get("adr_refs") or []) + created)), "DERIVED", code.get("source")),
        "last_verified": _f(pp.get("last_verified"), "EXPLICIT", src_man),
        "facts": [{"fact": f["fact"], "evidence": f.get("evidence"), "unknown": f.get("unknown")} for f in facts],
        "found": True,
    }
    return p


def answer_why(label: str, *, measure_host: bool = False) -> str:
    """One readable paragraph: why the agent exists and on which decision, or an explicit UNKNOWN."""
    p = passport(label, measure_host=measure_host)
    if not p.get("found"):
        return f"{label}: UNKNOWN — no such agent in the canonical registry."
    why = p["why"]["value"] or p["purpose"]["value"]
    by = p["created_by"]["value"]
    lines = [f"{label}: {why or 'UNKNOWN — no recorded reason'}",
             f"decision: {', '.join(by) if by else 'UNKNOWN — no decision reference found'}"
             f" ({p['created_by']['origin']}, {p['created_by']['source']})",
             f"status: {p['status']['value']} ({p['status']['origin']})"]
    for f in p["facts"]:
        lines.append(f"fact: {f['fact']}" + (f" — UNKNOWN: {f['unknown']}" if f.get("unknown") else ""))
    return "\n".join(lines)


def coverage(*, measure_host: bool = False) -> Dict:
    """How many agents can answer «why» with a decision reference — the passport quality metric."""
    spa = src.roots()["spa"]
    man = _json(spa / "architecture" / "manifest.json") or {}
    rows = []
    for a in man.get("agents", []):
        if a.get("intent") == "retired":
            continue
        p = passport(a["label"])
        rows.append({"label": a["label"], "why": p["why"]["origin"] != "UNKNOWN",
                     "purpose": p["purpose"]["origin"] != "UNKNOWN",
                     "decision": p["created_by"]["origin"], })
    n = len(rows)
    by = {o: sum(1 for r in rows if r["decision"] == o) for o in ("EXPLICIT", "DERIVED", "HEURISTIC", "UNKNOWN")}
    return {"agents": n, "with_explicit_why": sum(r["why"] for r in rows),
            "with_purpose": sum(r["purpose"] for r in rows), "decision_by_origin": by,
            "decision_unknown": [r["label"] for r in rows if r["decision"] == "UNKNOWN"]}
