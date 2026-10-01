"""Context assembler — a task-specific WORKING CONTEXT package for any model (Claude Code, Codex, a local
LLM). Model-independent: a JSON document + a plain-markdown rendering; nothing provider-specific.

    assemble(task) → {
      task, generated_at, budget_chars,
      truth_policy        what each status means; «no evidence ⇒ answer UNKNOWN»
      permissions         the owner-gated subjects (current canonical source, never history)
      semantic_facts      matched facts from the truth registry (each with evidence refs)
      sources             retrieved chunks: ref, layer, status (SUPERSEDED flagged), excerpt
      agents              passports of agents named in the task
      lineage             compact lineage of decisions named in the task
      evidence_sufficiency  coverage of the task's concepts by CANONICAL/SEMANTIC evidence
    }
It never dumps history: every section is ranked and capped, the whole package is held to the budget.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Dict, List

from . import index as ix
from . import lineage as ln
from . import passports as pp

TRUTH_POLICY = (
    "Statuses: ACCEPTED/ACTIVE = decided and in force · PROPOSED = suggested, not decided · "
    "SUPERSEDED/REJECTED = no longer true (cite what replaced it) · OBSERVED = a record of what happened, "
    "not a decision · UNKNOWN = not enough evidence. Answer ONLY from this package; cite refs. If the package "
    "does not contain the answer, say UNKNOWN (НЕИЗВЕСТНО) and what is missing — never guess. A past "
    "permission is not a new permission; permissions come only from the 'permissions' section.")

_LABEL = re.compile(r"\bcom\.(?:spa|studiobridge|earn-defi)\.[\w.-]+|\b(mission_tick|trading_research|telegram_bot|self_heal|agent_health|reboot_verify|orchestrator|daily_cycle|decision_loop)\b")
_ADR = re.compile(r"\bADR-B?\d[\w.]*\b", re.I)


def _facts(rows: List[Dict]) -> List[Dict]:
    return [r for r in rows if r["kind"] == "truth"]


def _clip(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def assemble(task: str, *, budget_chars: int = 12000, k: int = 10, index_path=None,
             measure_host: bool = False) -> Dict:
    rows = ix.search(task, k=k + 6, path=index_path)
    facts = _facts(rows)[:5]
    docs = [r for r in rows if r["kind"] != "truth"][:k]
    perm = ix.search("owner approval three subjects ADR-285 одобрение владельца", k=3, path=index_path)
    perm_fact = next((r for r in perm if r["kind"] == "truth" and "owner-approval" in r["heading"]), None)
    labels = sorted({m.group(0) if m.group(0).startswith("com.") else f"com.spa.{m.group(1)}"
                     for m in _LABEL.finditer(task)})
    adrs = sorted({a.upper() for a in _ADR.findall(task)})
    pkg: Dict = {
        "schema": "studio-os/context-package/1",
        "task": task,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "budget_chars": budget_chars,
        "truth_policy": TRUTH_POLICY,
        "permissions": {"text": _clip(perm_fact["text"], 700) if perm_fact else
                        "Owner-gated: real money, public yield numbers / tier naming / legal wording, irreversible actions (CLAUDE.md, ADR-285).",
                        "ref": "spa:CLAUDE.md · spa:docs/decisions/ADR-285-owner-decision-boundary-by-subject.md"},
        "semantic_facts": [{"subject": f["heading"].split(" [")[0].replace("FACT ", ""), "text": _clip(f["text"], 900),
                            "evidence": f.get("evidence", [])} for f in facts],
        "sources": [{"ref": f"{r['repo']}:{r['path']}", "heading": r["heading"][:120], "layer": r["layer"],
                     "status": r["status"], "superseded_by": r.get("superseded_by"),
                     "excerpt": _clip(r["text"], 700)} for r in docs],
        "agents": [],
        "lineage": [],
    }
    for lbl in labels[:3]:
        p = pp.passport(lbl, measure_host=measure_host)
        if p.get("found"):
            pkg["agents"].append({"label": lbl, "why": p["why"]["value"] or p["purpose"]["value"],
                                  "created_by": p["created_by"]["value"], "created_by_origin": p["created_by"]["origin"],
                                  "status": p["status"]["value"], "facts": p["facts"]})
        else:
            pkg["agents"].append({"label": lbl, "status": "UNKNOWN", "note": p.get("note")})
    for a in adrs[:2]:
        pkg["lineage"].append(ln.render(ln.lineage(a)))
    cs = ix.concepts(task)
    strong = [c for c in cs if c["weight"] >= 1]
    authoritative = [r for r in rows if r["layer"] in ("CANONICAL", "SEMANTIC") and r["status"] not in ("SUPERSEDED", "REJECTED")]
    hay = " ".join((r["heading"] + " " + r["text"]).lower() for r in authoritative)
    hay_st = " " + ix.stems(hay)
    covered = [c["term"] for c in strong if any(a in hay for a in c["alts"]) or any(f" {s}" in hay_st for s in c["stems"])]
    ratio = len(covered) / len(strong) if strong else 0.0
    missing = [c["term"] for c in strong if c["term"] not in covered]
    # SUFFICIENT needs the SUBJECT covered, not just most words: two uncovered concepts are a different
    # question (held-out Q1: «агент торгового ресёрча» scored 0.8 while its two subject words were absent)
    pkg["evidence_sufficiency"] = {"concepts": [c["term"] for c in strong], "covered": covered,
                                   "uncovered": missing, "ratio": round(ratio, 2),
                                   "verdict": "SUFFICIENT" if ratio >= 0.75 and len(missing) <= 1 and authoritative else
                                              "PARTIAL" if ratio >= 0.4 else "INSUFFICIENT"}
    _fit(pkg, budget_chars)
    return pkg


def _fit(pkg: Dict, budget: int) -> None:
    """Trim the lowest-ranked sources until the package fits the budget (facts and policy stay)."""
    while len(json.dumps(pkg, ensure_ascii=False)) > budget and pkg["sources"]:
        pkg["sources"].pop()
    pkg["size_chars"] = len(json.dumps(pkg, ensure_ascii=False))


def render_markdown(pkg: Dict) -> str:
    L = [f"# Context package — {pkg['task']}", "", f"**Truth policy.** {pkg['truth_policy']}", "",
         f"**Permissions** ({pkg['permissions']['ref']}): {pkg['permissions']['text']}", "",
         f"**Evidence sufficiency:** {pkg['evidence_sufficiency']['verdict']} "
         f"(covered {pkg['evidence_sufficiency']['covered']} of {pkg['evidence_sufficiency']['concepts']}; "
         f"NOT covered: {pkg['evidence_sufficiency']['uncovered'] or 'none'})", ""]
    if pkg["semantic_facts"]:
        L.append("## Semantic facts (distilled, with evidence)")
        for f in pkg["semantic_facts"]:
            L.append(f"- **{f['subject']}** — {f['text']}")
        L.append("")
    if pkg["agents"]:
        L.append("## Agent passports")
        for a in pkg["agents"]:
            L.append(f"- `{a['label']}` — why: {a.get('why') or 'UNKNOWN'} · decision: {a.get('created_by') or 'UNKNOWN'}"
                     f" · status: {a.get('status')}")
            for f in a.get("facts") or []:
                L.append(f"  - {f['fact']}" + (f" (UNKNOWN: {f['unknown']})" if f.get("unknown") else ""))
        L.append("")
    if pkg["lineage"]:
        L.append("## Lineage")
        L += [x for x in pkg["lineage"]]
        L.append("")
    L.append("## Sources (ranked)")
    for s in pkg["sources"]:
        st = s["status"] + (f" → {s['superseded_by']}" if s.get("superseded_by") else "")
        L.append(f"- [{s['layer']} · {st}] `{s['ref']}` — {s['heading']}: {s['excerpt']}")
    return "\n".join(L)
