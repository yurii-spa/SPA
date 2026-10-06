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

# ADR-591 §A2: named-entity extraction for the question. "Named entity" here is deliberately
# heuristic — identifiers, capitalised proper nouns (Latin or Cyrillic), bare filenames — exactly
# the set the acceptance criterion names. A few extra false positives (a capitalised common word)
# only ever DEMOTE a verdict toward PARTIAL, never promote one toward SUFFICIENT, so the heuristic
# errs the safe way (invariant #2, fail-CLOSED).
_IDENTIFIER = re.compile(r"\bADR-B?\d[\w.]*\b|\bcom\.[\w.-]+\b|\bb19\.\d+\.\d+\b|\b[a-z]+_[a-z][a-z_]{2,}\b", re.I)
_FILENAME = re.compile(r"\b[\w][\w\-./]{1,80}\.(?:md|json|py|yaml|yml|sh|txt)\b", re.I)
_PROPER_EN = re.compile(r"\b[A-Z][A-Za-z]{2,}\b")
_PROPER_RU = re.compile(r"\b[А-ЯЁ][а-яё]{2,}\b")
_ENTITY_STOP = {
    "как", "что", "где", "кто", "когда", "почему", "зачем", "какой", "какая", "какие", "какого",
    "какую", "каком", "сколько", "откуда", "расскажи", "скажи",
    "what", "where", "who", "when", "why", "how", "which", "does", "do", "is", "are", "the",
    "this", "that", "we", "us", "our",
    # ADR-591 §Wave2: a BARE category word that names the whole class of records, not one specific
    # record. "ADR" alone appears in the title/heading of ~91% of every canonical chunk in the corpus
    # (measured 2026-10-06, docs/decisions + docs/adr) — every ADR's own title starts "ADR-NNN …" —
    # so letting it satisfy the entity gate was equivalent to no gate at all for any question that
    # merely says the word "ADR" without a number. A numbered reference ("ADR-256") is unaffected:
    # that is caught by `_IDENTIFIER` below, which this stop-list never touches.
    "adr", "адр",
}


def _word_present(entity: str, text: str) -> bool:
    """Whole-word containment, case-insensitive. Plain substring `in` was the bug behind one of the
    Wave-1 false-SUFFICIENTs (ADR-591 §Wave2): entity "PAT" matched inside "money-path"/"Path" (the
    risk-engine's own vocabulary), so a corpus term that merely CONTAINS the entity's letters
    satisfied the gate. `\\w` alone is not enough here — it does not cover Cyrillic — so the boundary
    is spelled out explicitly."""
    chars = "0-9A-Za-zА-Яа-яЁё_"
    pat = re.compile(r"(?<![" + chars + r"])" + re.escape(entity.lower()) + r"(?![" + chars + r"])")
    return bool(pat.search(text.lower()))


def _entities(task: str) -> Dict[str, List[str]]:
    """Identifiers/filenames (`specific`) and capitalised proper nouns (`generic`) mentioned in the
    question — the things A2 requires to actually show up in the retrieved evidence, not just a word
    that happens to co-occur. Split in two (ADR-591 §Wave2): an identifier or filename ("ADR-554",
    "roles.json") is inherently rare, so finding it ANYWHERE in the top-3 chunks' text is real
    evidence. A bare capitalised word ("Director", "PAT", "Telegram") is not — it is exactly as
    likely to be a common corpus term as a question subject (measured 2026-10-06: "PAT" appears in
    21 chunks, "Telegram" in 258, purely incidentally in most of them), so it only counts when it is
    the TITLE/HEADING of a top-3 chunk — i.e. that chunk is actually ABOUT it, not merely mentioning
    it in passing."""
    specific, generic = set(), set()
    for pat in (_IDENTIFIER, _FILENAME):
        specific |= {m.group(0) for m in pat.finditer(task)}
    for pat in (_PROPER_EN, _PROPER_RU):
        for m in pat.finditer(task):
            w = m.group(0)
            if w.lower() not in _ENTITY_STOP:
                generic.add(w)
    return {"specific": sorted(specific), "generic": sorted(generic)}


_FACT_RETIRED = re.compile(r"\[(SUPERSEDED|REJECTED)\]")


def _facts(rows: List[Dict]) -> List[Dict]:
    """`memory_truth.json` facts, excluding any whose OWN status (carried in `[STATUS]` inside the
    chunk heading, not the chunk-table status column — one JSON file resolves to one document-level
    status, but each fact inside it declares its own) marks it SUPERSEDED/REJECTED. ADR-591 §Wave2:
    a retired fact is history, not current evidence — it should not be handed to a caller as a
    `semantic_facts` entry, the one section of the package `TRUTH_POLICY` tells a reader to trust
    outright."""
    return [r for r in rows if r["kind"] == "truth" and not _FACT_RETIRED.search(r["heading"])]


def _clip(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def assemble(task: str, *, budget_chars: int = 12000, k: int = 10, index_path=None,
             measure_host: bool = False, auto_rebuild: bool = True) -> Dict:
    """ADR-591 §A1: before searching, `ensure_fresh()` compares the on-disk index against the
    CURRENT sources (stat-only, cheap). `auto_rebuild=True` (default): a stale index is rebuilt in
    place first, so a query always answers from sources that match what is actually on disk —
    measured 2026-10-05, this is what closes the 0.668-vs-0.744 (live-vs-fresh) gap. A caller that
    sets `auto_rebuild=False` gets the cheap check only; `evidence_sufficiency.verdict` is then
    capped at "STALE" (never SUFFICIENT) whenever the sources moved."""
    fresh = ix.ensure_fresh(index_path, rebuild=auto_rebuild)
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
        # ADR-591 §A1: the index age/staleness the verdict below is gated on.
        "index_freshness": {"stale": fresh["stale"], "rebuilt": fresh.get("rebuilt"), "age_s": fresh.get("age_s")},
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
    verdict = ("SUFFICIENT" if ratio >= 0.75 and len(missing) <= 1 and authoritative else
               "PARTIAL" if ratio >= 0.4 else "INSUFFICIENT")

    # ADR-591 §A2: a high word-coverage ratio is not enough when a NAMED ENTITY of the question —
    # an identifier, a proper noun, a filename — never shows up in the TOP-3 authoritative chunks
    # (what a reader actually sees first, not the whole retrieved set). Measured 2026-10-05: this
    # was the single biggest source of false-SUFFICIENT on questions.json (20% live). Only ever
    # demotes toward PARTIAL — never promotes, never turns PARTIAL into INSUFFICIENT — so a question
    # with no extractable entity (ordinary words only) is scored exactly as before.
    top3 = authoritative[:3]
    hay3 = " ".join((r.get("path", "") + " " + r["title"] + " " + r["heading"] + " " + r["text"])
                    for r in top3)
    titlehead3 = " ".join((r["title"] + " " + r["heading"]) for r in top3)
    ents = _entities(task)
    # ADR-591 §Wave2: an identifier/filename is rare enough that body-wide presence is real evidence
    # (word-boundary, not substring — "PAT" no longer matches inside "money-path"/"Path"); a bare
    # proper noun is common enough that it must be the chunk's OWN subject (title/heading), not an
    # incidental body mention, to count — see `_entities`'s docstring for the measured justification.
    entities_missing = ([e for e in ents["specific"] if not _word_present(e, hay3)]
                         + [e for e in ents["generic"] if not _word_present(e, titlehead3)])
    entities = sorted(set(ents["specific"]) | set(ents["generic"]))
    if entities_missing and verdict == "SUFFICIENT":
        verdict = "PARTIAL"

    # ADR-591 §A1: a stale index is never allowed to present itself as SUFFICIENT. `auto_rebuild`
    # already heals this in the common case (see docstring); this branch only fires when the
    # caller explicitly disabled the rebuild and the sources moved anyway.
    if fresh["stale"]:
        verdict = "STALE"

    alias_notes = ix.alias_notes_in(task)
    pkg["evidence_sufficiency"] = {"concepts": [c["term"] for c in strong], "covered": covered,
                                   "uncovered": missing, "ratio": round(ratio, 2),
                                   "entities": entities, "entities_missing": entities_missing,
                                   "alias_notes": alias_notes, "verdict": verdict}
    _fit(pkg, budget_chars)
    return pkg


def _fit(pkg: Dict, budget: int) -> None:
    """Trim the lowest-ranked sources until the package fits the budget (facts and policy stay)."""
    while len(json.dumps(pkg, ensure_ascii=False)) > budget and pkg["sources"]:
        pkg["sources"].pop()
    pkg["size_chars"] = len(json.dumps(pkg, ensure_ascii=False))


def render_markdown(pkg: Dict) -> str:
    es = pkg["evidence_sufficiency"]
    fr = pkg.get("index_freshness") or {}
    L = [f"# Context package — {pkg['task']}", "", f"**Truth policy.** {pkg['truth_policy']}", "",
         f"**Permissions** ({pkg['permissions']['ref']}): {pkg['permissions']['text']}", ""]
    if fr.get("stale"):
        age = fr.get("age_s")
        L.append(f"**Index STALE** (age {age}s, not rebuilt) — evidence below may predate a source change.")
        L.append("")
    L += [f"**Evidence sufficiency:** {es['verdict']} "
          f"(covered {es['covered']} of {es['concepts']}; NOT covered: {es['uncovered'] or 'none'}"
          f"{'; MISSING entities: ' + str(es['entities_missing']) if es.get('entities_missing') else ''})", ""]
    for note in es.get("alias_notes") or []:
        L.append(f"*(«{note['superseded_name']}» is an ex-name, valid until {note['valid_to']}; "
                 f"canonical now: {note['canonical']})*")
    if es.get("alias_notes"):
        L.append("")
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
