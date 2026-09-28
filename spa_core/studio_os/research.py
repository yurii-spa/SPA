"""Research → Evidence → Decision relationship model (ADR-495 Phase 4). Derived, read-only, no graph DB.
Edges are VERIFIED references (a decision/ADR that names a research file), never guessed. Unlinked research
is marked ORPHAN honestly. Each edge carries provenance (which file names which)."""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RESEARCH_DIR = REPO / "research"
DECISIONS_DIR = REPO / "docs" / "decisions"
EVIDENCE_DOC = "docs/37_apy_realism_and_evidence_standard.md"
MATURITY = "docs/MATURITY_REGISTER.md"


def _read(p):
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def _title(text, fallback):
    m = re.search(r"^#\s*(.+)$", text, re.M)
    return m.group(1).strip() if m else fallback


# Reference-material patterns: standalone background that legitimately drives no single decision.
_STANDALONE_RE = re.compile(
    r"competitor|devops|best.?practic|regulator|architecture|guide|cloudflare|gnosis|safe|"
    r"конкурент|практик|регулятор|архитектур|руководств|обзор", re.I)


def classify_orphan(stem: str, text: str, cites_evidence: bool) -> tuple[str, str, str]:
    """Classify an unlinked research item — returns (class, confidence, reason). This is filename/pattern
    matching, so it is HEURISTIC, NOT fact (ADR-497): classes are LIKELY_* and never asserted as verified.
    Only an explicit in-text marker (e.g. 'obsolete') is DERIVED. Never a guessed LINK."""
    low = stem.lower()
    if re.search(r"obsolete|deprecated|устарел|архив", low + " " + text[:400], re.I):
        return "OBSOLETE", "DERIVED", "текст/имя ЯВНО содержит маркер устаревания (verified in-text)"
    if _STANDALONE_RE.search(low):
        return ("LIKELY_STANDALONE", "HEURISTIC",
                "имя совпало с паттерном справочного материала (конкуренты/devops/регулятор/архитектура/гайд) "
                "— вероятно фоновой материал, НО это эвристика по имени файла, не факт")
    if cites_evidence:
        return ("LIKELY_MISSING_LINK", "HEURISTIC",
                "цитирует стандарт эвиденса (L0–L6) ⇒ вероятно относится к решению, но ни один ADR не называет "
                "его; сигнал, не доказательство")
    return ("UNKNOWN", "UNKNOWN", "ни ссылки из решения, ни признаков справочной/устаревшей природы")


def build_research_model() -> dict:
    items = []
    if not RESEARCH_DIR.exists():
        return {"present": False, "items": [], "note": "research/ absent"}

    # index decision text once so edges are verified references, not guesses
    decisions = []
    if DECISIONS_DIR.exists():
        for d in sorted(DECISIONS_DIR.glob("ADR-*.md")):
            decisions.append((d.name, _read(d).lower()))

    ev_present = (REPO / EVIDENCE_DOC).exists()
    for f in sorted(RESEARCH_DIR.glob("*.md")):
        if f.name.lower() == "readme.md":
            continue
        text = _read(f)
        stem = f.stem.lower()
        # a decision references this research if it mentions the file stem or a distinctive title token
        title = _title(text, f.stem)
        key_tokens = [t for t in re.split(r"[^a-z0-9]+", stem) if len(t) > 4][:4]
        supports = []
        for name, dtext in decisions:
            if f.name.lower() in dtext or (key_tokens and all(t in dtext for t in key_tokens) and key_tokens):
                supports.append(name)
        # evidence link: does the research cite the evidence standard (L0-L6)?
        cites_evidence = bool(re.search(r"\bL[0-6]\b|evidence|доказат", text, re.I))
        m = re.search(r"(20\d\d[-/]\d\d[-/]\d\d)", text)
        date = m.group(1) if m else None
        linked = bool(supports)
        if linked:
            orphan_class = orphan_conf = orphan_reason = None
        else:
            orphan_class, orphan_conf, orphan_reason = classify_orphan(f.stem, text, cites_evidence)
        items.append({
            "id": f.stem, "title": title[:90], "ref": f"research/{f.name}",
            "date": date,
            "evidence": {"cites_standard": cites_evidence, "standard": EVIDENCE_DOC if ev_present else None},
            "supports_decisions": supports,            # verified references (decision names this research)
            "produced_task": None,                     # MISSING: no canonical research→task link source wired
            "implemented": None,                       # MISSING
            "status": "LINKED" if linked else "ORPHAN",
            "orphan_class": orphan_class,              # why it is unlinked (never a guessed link)
            "orphan_confidence": orphan_conf,          # HEURISTIC / DERIVED / UNKNOWN (ADR-497)
            "orphan_reason": orphan_reason,
            "provenance": "research/ + scan of docs/decisions/ for a naming reference",
        })
    linked = sum(1 for i in items if i["status"] == "LINKED")
    from collections import Counter
    orphan_breakdown = dict(Counter(i["orphan_class"] for i in items if i["status"] == "ORPHAN"))
    return {
        "schema": "studio-os/research-model/1", "present": True,
        "total": len(items), "linked": linked, "orphan": len(items) - linked,
        "orphan_breakdown": orphan_breakdown,
        "evidence_standard": EVIDENCE_DOC, "maturity_register": MATURITY,
        "items": items,
        "note": "Edges are VERIFIED references only (a decision names the research file/tokens). Unlinked = "
                "ORPHAN, shown honestly. research→task/implementation links are MISSING (no canonical source).",
    }


if __name__ == "__main__":
    import json
    print(json.dumps(build_research_model(), ensure_ascii=False, indent=1))
