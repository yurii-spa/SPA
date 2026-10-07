"""Fresh-session proof (ADR-610, ARB-CONTINUITY-01 §6): 36 owner questions answered from the bootstrap
read set ONLY — `docs/continuity/*` (curated + the COMMITTED generated copy) and `docs/ROADMAP.md` — with no
chat transcript and no other repository file. Each answer carries its source path, whether that source is
CURRENT / SUPERSEDED / DERIVED, and a sufficiency class. UNKNOWN is a valid answer.

The GRADER is a different code path: it checks every answer against the canon the answer did not read
(architecture/roles.json, the ADR files, the code itself, state.json consistency). A wrong confident answer
fails. This is a deterministic file-reader test, NOT the independent LLM run (`FRESH_SESSION_PROMPT.md`).

    python -m spa_core.tests.test_arb_fresh_session      # prints the answer record (JSON)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CDIR = REPO / "docs" / "continuity"
UNKNOWN = "UNKNOWN"


class Reader:
    """Everything a fresh session may read. Opening any other path is a test failure."""

    ALLOWED = ("docs/continuity/", "docs/ROADMAP.md")

    def __init__(self, repo: Path = REPO):
        self.repo = repo
        self.opened: list[str] = []

    def text(self, rel: str) -> str:
        assert rel.startswith(self.ALLOWED), f"fresh session read outside the bootstrap set: {rel}"
        self.opened.append(rel)
        return (self.repo / rel).read_text(encoding="utf-8")

    def state(self) -> dict:
        return json.loads(self.text("docs/continuity/state.json"))

    def section(self, key: str) -> dict:
        return self.state()["sections"][key]

    def topic(self, name: str) -> dict:
        return next(r for r in self.state()["decisions"] if r["topic"] == name)

    def context_paragraph(self, heading: str) -> str:
        t = self.text("docs/continuity/ARCHITECT_CONTEXT.md")
        m = re.search(r"(?ms)^## [^\n]*" + re.escape(heading) + r"[^\n]*\n(.*?)(?=^## |\Z)", t)
        return m.group(1) if m else ""

    def intent(self, iid: str) -> dict:
        t = self.text("docs/continuity/OWNER_INTENT_LEDGER.md")
        m = re.search(r"(?ms)^## " + iid + r" · [^\n]+\n(.*?)(?=^## |\Z)", t)
        return dict(re.findall(r"(?m)^- \*\*(\w+):\*\* (.+)$", m.group(1))) if m else {}


def _ans(answer, source, status="CURRENT", sufficiency="SUFFICIENT", limit=500):
    if answer in (None, "", UNKNOWN):
        return dict(answer=UNKNOWN, source=source, source_status=status, sufficiency="UNKNOWN")
    return dict(answer=re.sub(r"\s+", " ", str(answer)).strip()[:limit], source=source, source_status=status,
                sufficiency=sufficiency)


def _sec(r: Reader, key: str, prefix: str = ""):
    s = r.section(key)
    ok = s["status"] != UNKNOWN
    suff = "UNKNOWN" if not ok else ("PARTIAL" if s["status"] == "PARTIAL" else "SUFFICIENT")
    return _ans(prefix + s["display"] + (f" (as of {s['as_of']})" if s["as_of"] else "") if ok else UNKNOWN,
                f"docs/continuity/CURRENT_STATE.md «{key}» ← {s['source']}", "DERIVED", suff)


def _row(r: Reader, topic: str):
    row = r.topic(topic)
    refs = ", ".join(x["adr"] for x in row["refs"])
    # a REJECTED row is a CURRENT decision to reject — say so, never plain «CURRENT» (review P2)
    status = {"SUPERSEDED": "SUPERSEDED", "CURRENT": "CURRENT", "REJECTED": "CURRENT_REJECTION",
              "EXPERIMENTAL": "CURRENT_EXPERIMENT"}.get(row["cls"], UNKNOWN)
    return _ans(f"[{row['cls']}] {row['title']} — {row['note']} ({refs})" if row["cls"] != UNKNOWN else UNKNOWN,
                f"docs/continuity/ARCHITECT_DECISION_INDEX.md «{topic}» → {refs}", status)


def answer_all(r: Reader) -> dict:
    ctx = "docs/continuity/ARCHITECT_CONTEXT.md"
    led = "docs/continuity/OWNER_INTENT_LEDGER.md"
    roles = r.context_paragraph("Roles and authority")
    worlds = r.context_paragraph("Three worlds")
    st = r.state()
    h = st["header"]

    def role_row(name):
        m = re.search(r"(?m)^\| \*\*" + re.escape(name) + r"\*\*[^\n]*$", roles)
        return m.group(0) if m else UNKNOWN

    A = {}
    A[1] = _ans(r.context_paragraph("Project identity"), f"{ctx} §1")
    A[2] = _ans("; ".join(re.findall(r"(?m)^\| \*\*([A-Z ]+)\*\*", worlds)), f"{ctx} §2 (ADR-592 §6)")
    A[3] = _ans(role_row("Owner"), f"{ctx} §3 (ADR-285)")
    A[4] = _ans(role_row("ChatGPT — Architecture Review Board (ARB)"), f"{ctx} §3 (ADR-610)")
    A[5] = _ans(role_row("Claude Code"), f"{ctx} §3")
    A[6] = _ans(role_row("Oracle"), f"{ctx} §3 (ADR-554)")
    A[7] = _ans(role_row("Sherlock"), f"{ctx} §3 (ADR-564)")
    A[8] = _ans("No — " + role_row("Oracle"), f"{ctx} §3 (ADR-554)")
    A[9] = _ans("No — " + role_row("Sherlock"), f"{ctx} §3 (ADR-564)")
    A[10] = _sec(r, "real_capital")
    A[11] = _sec(r, "live_execution")
    A[12] = _row(r, "trading-lab-canonical")
    A[13] = _ans(r.intent("INT-03").get("why_it_matters"), f"{led} INT-03")
    A[14] = _row(r, "older-btc-engines")
    A[15] = _sec(r, "defi_paper")
    mature = [p for p in st["profiles"] if p["reportable"] is True]
    A[16] = _ans("; ".join(f"{p['profile']} ({p['internal_book']}, {p['metric_type']}, {p['value']})" for p in mature)
                 if mature else UNKNOWN, "docs/continuity/CURRENT_STATE.md «Public profile mapping»", "DERIVED")
    acc = [p for p in st["profiles"] if p["reportable"] is False]
    A[17] = _ans("; ".join(f"{p['profile']}: accumulating {p['accumulating_days']} d, reportable after 30" for p in acc)
                 if acc else UNKNOWN, "docs/continuity/CURRENT_STATE.md «Public profile mapping»", "DERIVED")
    A[18] = _ans(r.intent("INT-02").get("current_implementation"), f"{led} INT-02 (ADR-580, ADR-592)")
    A[19] = _row(r, "director-os-read-model")
    A[20] = _row(r, "memory-hybrid")
    mp = r.topic("mempalace-dependency")
    A[21] = _ans("No — MemPalace as a runtime dependency is " + mp["cls"] if mp["cls"] == "REJECTED" else UNKNOWN,
                 "docs/continuity/ARCHITECT_DECISION_INDEX.md «mempalace-dependency»", "CURRENT_REJECTION")
    A[22] = _ans(r.intent("INT-11").get("current_status"), f"{led} INT-11 (ADR-591)")
    A[23] = _ans(r.intent("INT-12").get("owner_intent"), f"{led} INT-12; docs/ROADMAP.md item 10")
    A[24] = _ans(r.intent("INT-12").get("current_implementation"), f"{led} INT-12")
    A[25] = _sec(r, "active_problems")
    A[26] = _sec(r, "owner_gates")
    A[27] = _row(r, "openclaw")
    A[28] = _row(r, "backup-offsite")
    A[29] = _ans(h["production_release"] if h["production_release"] != UNKNOWN else UNKNOWN,
                 "docs/continuity/CURRENT_STATE.md header production_release ← data/code_sync_status.json", "DERIVED")
    A[30] = _sec(r, "next_safe_action")
    sup = [x for x in st["decisions"] if x["cls"] == "SUPERSEDED"]
    A[31] = _ans(f"{sup[0]['title']} — {sup[0]['note']}" if sup else UNKNOWN,
                 "docs/continuity/ARCHITECT_DECISION_INDEX.md «SUPERSEDED»", "SUPERSEDED")
    A[32] = _ans(r.intent("INT-05").get("why_it_matters"), f"{led} INT-05")
    A[33] = _ans("; ".join(f"{p['profile']} ↔ {p['internal_book']} ↔ {p['decision']} {p['effective']} ↔ "
                           f"{p['track_source']} ↔ {p['metric_type']}" for p in st["profiles"]),
                 "docs/continuity/CURRENT_STATE.md «Public profile mapping»", "DERIVED", limit=2000)
    A[34] = _sec(r, "product_publication")
    boot = r.text("docs/continuity/BOOTSTRAP.md")
    A[35] = _ans("Rebuild from canon: " + ("`continuity build`" if "continuity build" in boot else UNKNOWN)
                 + "; " + r.topic("backup-offsite")["note"], "docs/continuity/BOOTSTRAP.md + DECISION_INDEX «backup-offsite»")
    A[36] = _ans(r.intent("INT-08").get("current_status") + " — " + r.intent("INT-08").get("known_gaps", ""),
                 f"{led} INT-08 (ADR-521)")
    return A


# ── grading (independent of the answer path) ─────────────────────────────────────────────────

def _roles() -> dict:
    return {x["role_id"]: x for x in json.loads((REPO / "architecture/roles.json").read_text())["roles"]}


def _adr_text(n: str) -> str:
    return next((REPO / "docs/decisions").glob(f"{n}-*.md")).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def answers():
    r = Reader()
    a = answer_all(r)
    assert all(p.startswith(Reader.ALLOWED) for p in r.opened)
    return a, json.loads((CDIR / "state.json").read_text(encoding="utf-8"))


def test_every_answer_has_source_status_and_sufficiency(answers):
    a, _ = answers
    assert sorted(a) == list(range(1, 37))
    for q, x in a.items():
        assert x["source"] and x["source_status"] in ("CURRENT", "CURRENT_REJECTION", "CURRENT_EXPERIMENT",
                                                      "SUPERSEDED", "DERIVED", UNKNOWN), q
        assert x["sufficiency"] in ("SUFFICIENT", "PARTIAL", "UNKNOWN"), q
        assert (x["answer"] == UNKNOWN) == (x["sufficiency"] == "UNKNOWN"), q


def test_static_architecture_answers_match_the_canon(answers):
    a, _ = answers
    roles = _roles()
    assert "SPA" in a[1]["answer"] and "paper" in a[1]["answer"]
    for w in ("CAPITAL", "STUDIO OS", "EARN DEFI PRODUCT"):
        assert w in a[2]["answer"]
        assert w in _adr_text("ADR-592")
    assert roles["chief_investment_officer"]["display_name"] in a[6]["answer"]
    assert roles["head_of_research"]["display_name"] in a[7]["answer"]
    assert "move money" in roles["chief_investment_officer"]["may_not"] and a[8]["answer"].startswith("No")
    assert "move money" in roles["head_of_research"]["may_not"] and a[9]["answer"].startswith("No")
    assert "implementation" in a[5]["answer"].lower()
    assert "architecture" in a[4]["answer"].lower()


def test_decision_answers_are_current_or_flagged_superseded(answers):
    a, st = answers
    assert "ADR-590" in a[12]["source"] and a[12]["answer"].startswith("[CURRENT]")
    assert a[14]["source_status"] == "SUPERSEDED"
    assert a[27]["source_status"] == "SUPERSEDED" and "REMOVED" in json.dumps(st["decisions"])
    assert a[19]["answer"].startswith("[CURRENT]") and "not an authority" in a[19]["answer"]
    assert a[31]["source_status"] == "SUPERSEDED"
    assert "Accepted" in _adr_text("ADR-599") or "Accepted" in _adr_text("ADR-599").title()


def test_mempalace_answer_matches_the_code(answers):
    a, _ = answers
    assert a[21]["answer"].startswith("No") and a[21]["source_status"] == "CURRENT_REJECTION"
    imports = [p for p in (REPO / "spa_core").rglob("*.py")
               if re.search(r"(?m)^\s*(import|from)\s+mempalace", p.read_text(encoding="utf-8", errors="ignore"))]
    assert imports == []
    assert "REJECTED" in a[22]["answer"]


def test_runtime_answers_equal_the_generated_state_and_never_guess(answers):
    a, st = answers
    s = st["sections"]
    for q, key in ((10, "real_capital"), (11, "live_execution"), (15, "defi_paper"), (25, "active_problems"),
                   (30, "next_safe_action"), (34, "product_publication")):
        if s[key]["status"] == UNKNOWN:
            assert a[q]["answer"] == UNKNOWN, q
        else:
            assert s[key]["display"] in a[q]["answer"], q
    if s["real_capital"]["status"] == UNKNOWN:
        assert "$0" not in a[10]["answer"]
    assert a[29]["answer"] in (st["header"]["production_release"], UNKNOWN)
    if a[29]["answer"] != UNKNOWN:
        assert re.fullmatch(r"[0-9a-f]{40}", a[29]["answer"])


def test_mature_vs_accumulating_track_never_mix(answers):
    a, st = answers
    for p in st["profiles"]:
        if p["reportable"] is False:
            assert p["profile"] not in a[16]["answer"]
    for t in ("TARGET_RETURN", "REALIZED_PAPER_RETURN"):
        assert t in a[33]["answer"]


def test_intent_answers_quote_the_ledger_not_invent(answers):
    a, _ = answers
    led = (CDIR / "OWNER_INTENT_LEDGER.md").read_text(encoding="utf-8")
    for q in (13, 18, 22, 23, 24, 32, 36):
        assert a[q]["answer"] == UNKNOWN or a[q]["answer"][:60] in re.sub(r"\s+", " ", led), q


if __name__ == "__main__":
    rec = answer_all(Reader())
    json.dump({str(k): v for k, v in rec.items()}, sys.stdout, ensure_ascii=False, indent=1)
