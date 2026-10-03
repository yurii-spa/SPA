"""spa_core/studio_os/build_loop.py — Build Loop v1: the lifecycle of a task, DERIVED (ADR-551).

IDEA → TASK → ASSIGNED → RUN → ARTIFACT → REVIEW → DECISION → RELEASE → OUTCOME → MEMORY

There is no second task store. The task is the tracker card (``nimbalyst-local/tracker``, the
canonical store since ADR-066); its state machine is ``owner_queue.queue.CARD_TRANSITIONS`` (enforced
by ``set_status``: an allowed transition, evidence on every closing). Everything else in the loop is
READ from where it already lives:

* IDEA      — the card's ``source`` / ``origin`` / ``carried_to`` / intake text;
* TASK      — the card exists with an acceptance criterion (``acceptance_probe`` / ``finding_key``),
              or, for an owner decision, the question itself;
* ASSIGNED  — ``claimed_by`` or a status past intake;
* RUN       — the status trail shows ``in-progress`` (or later);
* ARTIFACT  — commits on origin/main whose message names the card slug;
* REVIEW    — evidence of review in those commits (``Owner-Approved:``, a reverse control, a test
              tally) or the closing evidence; else UNKNOWN;
* DECISION  — the card's ``adr`` field, ADRs named in the card or its commits, or the owner's answer;
* RELEASE   — the last such commit is an ancestor of the commit code-sync delivered to production;
* OUTCOME   — the card was CLOSED with recorded evidence (trail ``closed_by``/``evidence``);
* MEMORY    — the card (or its ADR) is in the memory index the next session asks.

Each stage is ``DONE`` / ``MISSING`` / ``UNKNOWN`` with the evidence that decided it. Reads only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Optional

from spa_core.studio_os import provenance as prov

STAGES = ("IDEA", "TASK", "ASSIGNED", "RUN", "ARTIFACT", "REVIEW", "DECISION", "RELEASE", "OUTCOME", "MEMORY")
CLOSED = {"done", "owner-done", "ingested"}
_REVIEW = re.compile(r"Owner-Approved:|reverse control|обратн\w+ контрол|\b\d+ passed\b|mutation|мутаци", re.I)


def tracker_dir() -> Path:
    """The canonical card store is origin's (ADR-066/152: the production tree's tracker drifts —
    measured 2026-10-03, 742 vs 1176 cards). Read the mirror; SPA_TRACKER_DIR overrides."""
    env = os.environ.get("SPA_TRACKER_DIR")
    if env:
        return Path(env)
    return prov.git_root() / "nimbalyst-local" / "tracker"


def _frontmatter(text: str) -> tuple[dict, list[str], str]:
    fm, trail, body = {}, [], text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end > 0:
            head, body = text[3:end], text[end + 4:]
            in_trail = False
            for line in head.splitlines():
                if line.startswith("status_trail:"):
                    in_trail = True
                    continue
                if in_trail and line.startswith("  - "):
                    trail.append(line[4:].strip().strip('"'))
                    continue
                in_trail = False
                if ":" in line and not line.startswith(" "):
                    k, _, v = line.partition(":")
                    fm[k.strip()] = v.strip().strip('"')
                elif line.strip().startswith("type:"):
                    fm["type"] = line.split(":", 1)[1].strip()
    return fm, trail, body


def find_card(query: str, tdir: Optional[Path] = None) -> Optional[Path]:
    tdir = tdir or tracker_dir()
    q = Path(query).name
    if not q.endswith(".md"):
        q += ".md"
    p = tdir / q
    return p if p.exists() else None


def _memory_has(token: str) -> Optional[bool]:
    """Is ``token`` (card slug or ADR id) in the memory index? None = index not readable."""
    try:
        from spa_core.utils.live_paths import live_data_dir
        db = Path(live_data_dir()) / "memory" / "index.db"
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            n = con.execute("SELECT COUNT(*) FROM chunks WHERE path LIKE ? OR body LIKE ?",
                            (f"%{token}%", f"%{token}%")).fetchone()[0]
        finally:
            con.close()
        return n > 0
    except Exception:  # noqa: BLE001 — absent index is a named outcome
        return None


def lineage(query: str, *, tdir: Optional[Path] = None, root: Optional[Path] = None,
            data_dir: Optional[Path] = None, memory: bool = True) -> dict:
    card = find_card(query, tdir)
    if card is None:
        return {"query": query, "state": "NOT_FOUND",
                "reason": f"no card {Path(query).name} in {tdir or tracker_dir()}"}
    text = card.read_text(encoding="utf-8")
    fm, trail, body = _frontmatter(text)
    slug = card.stem
    status = fm.get("status", "")
    root = root or prov.git_root()
    # The slug must be named as a whole token: «inbox-x» must not match «inbox-x-2» (review 2026-10-03).
    _tok = re.compile(r"(?<![\w-])" + re.escape(slug) + r"(?![\w-])")
    _shas = set()
    _full = prov._git(["log", "origin/main", f"--grep={slug}", "--fixed-strings", "--format=%H%x1f%B%x1e"], root) or ""
    for rec in _full.split("\x1e"):
        if "\x1f" in rec and _tok.search(rec.split("\x1f", 1)[1]):
            _shas.add(rec.split("\x1f", 1)[0].strip()[:9])
    commits = [c for c in prov._log(root, ["origin/main", f"--grep={slug}", "--fixed-strings"]) if c["sha"] in _shas]
    adrs = sorted(set(re.findall(r"\bADR-\d{3}\b", " ".join([fm.get("adr", ""), body] + [c["subject"] for c in commits]))))
    st: dict[str, dict] = {}

    def put(stage, state, ev):
        st[stage] = {"state": state, "evidence": ev}

    idea = fm.get("origin") or fm.get("source") or fm.get("carried_to")
    put("IDEA", "DONE" if idea else "UNKNOWN", idea or "card carries no source/origin")
    crit = fm.get("acceptance_probe") or fm.get("finding_key")
    if fm.get("type") == "owner-decision":
        put("TASK", "DONE", "owner decision card (the question is the task)")
    else:
        put("TASK", "DONE" if crit else "MISSING",
            f"criterion: {crit}" if crit else "no acceptance_probe / finding_key (acceptance rule)")
    statuses = [re.findall(r"(\S+) -> (\S+)", t) for t in trail]
    seen = {s for pair in statuses for p in pair for s in p}
    put("ASSIGNED", "DONE" if (fm.get("claimed_by") or seen - {"new", "backlog"} or status not in ("new", "backlog"))
        else "MISSING", fm.get("claimed_by") or f"status {status}")
    put("RUN", "DONE" if ({"in-progress"} & seen or status in CLOSED | {"in-progress", "blocked"}) else "MISSING",
        f"trail: {', '.join(trail[-3:]) or '—'}")
    put("ARTIFACT", "DONE" if commits else "MISSING",
        [f"{c['sha']} {c['date'][:10]} {c['subject'][:80]}" for c in commits[:6]] or
        "no commit on origin/main names this card")
    full = " ".join(rec.split("\x1f", 1)[1] for rec in _full.split("\x1e")
                    if "\x1f" in rec and rec.split("\x1f", 1)[0].strip()[:9] in _shas)
    reviewed = bool(_REVIEW.search(full)) or "evidence:" in " ".join(trail)
    put("REVIEW", "DONE" if reviewed else "UNKNOWN",
        "review evidence in commits/closure" if reviewed else "no review evidence recorded")
    owner_ans = fm.get("owner_choice") or fm.get("owner_answer_via")
    put("DECISION", "DONE" if (adrs or owner_ans) else "UNKNOWN",
        {"adrs": adrs, "owner_answer": owner_ans} if (adrs or owner_ans) else "no ADR and no owner answer linked")
    if commits:
        rel = prov.release_of(commits[0]["sha"], root=root, data_dir=data_dir)
        put("RELEASE", "DONE" if rel["state"] == "RELEASED" else
            "UNKNOWN" if rel["state"] in ("UNKNOWN", "ON_MAIN_PRODUCTION_UNKNOWN") else "MISSING", rel)
    else:
        put("RELEASE", "MISSING", "nothing to release")
    closing = [t for t in trail if "closed_by:" in t or "evidence:" in t]
    if status in CLOSED:
        put("OUTCOME", "DONE" if closing else "UNKNOWN",
            closing[-1] if closing else f"closed ({status}) before evidenced closing existed")
    else:
        put("OUTCOME", "MISSING", f"open: {status}")
    if memory:
        hit = _memory_has(slug)
        hit_adr = any(_memory_has(a) for a in adrs[:3]) if not hit and adrs else False
        put("MEMORY", "DONE" if (hit or hit_adr) else "UNKNOWN" if hit is None else "MISSING",
            "card in memory index" if hit else f"via {adrs[:3]}" if hit_adr else
            "memory index not readable" if hit is None else "not in memory index (rebuild: memory build)")
    return {"query": query, "card": str(card), "type": fm.get("type"), "status": status,
            "title": fm.get("title", "")[:160], "stages": st}


def render(x: dict) -> str:
    if x.get("state") == "NOT_FOUND":
        return f"NOT FOUND: {x['reason']}"
    out = [f"# {Path(x['card']).name}  [{x['type']} · {x['status']}]", f"  {x['title']}"]
    for s in STAGES:
        if s in x["stages"]:
            v = x["stages"][s]
            ev = v["evidence"]
            ev = "; ".join(ev) if isinstance(ev, list) else json.dumps(ev, ensure_ascii=False) if isinstance(ev, dict) else ev
            out.append(f"  {s:<9} {v['state']:<8} {str(ev)[:200]}")
    return "\n".join(out)


def board(tdir: Optional[Path] = None, *, recent: int = 10) -> dict:
    """Minimal owner read model of the loop: active, blocked, owner gates, recent closures."""
    tdir = tdir or tracker_dir()
    rows = []
    for p in sorted(tdir.glob("*.md")):
        if p.name.startswith("_"):
            continue
        try:
            fm, trail, _ = _frontmatter(p.read_text(encoding="utf-8"))
        except OSError:
            continue
        last = trail[-1][:25] if trail else None
        rows.append({"card": p.stem, "type": fm.get("type"), "status": fm.get("status"),
                     "title": fm.get("title", "")[:120], "last_transition": last})
    by = lambda s: [r for r in rows if r["status"] == s]
    closed = sorted([r for r in rows if r["status"] in CLOSED and r["last_transition"]],
                    key=lambda r: r["last_transition"], reverse=True)[:recent]
    return {"tracker": str(tdir), "total": len(rows),
            "active": by("in-progress"), "blocked": by("blocked"), "owner_gates": by("needs-owner"),
            "recently_closed": closed,
            "counts": {s: len(by(s)) for s in sorted({r["status"] for r in rows if r["status"]})}}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Build Loop v1 lineage (ADR-551)")
    ap.add_argument("cmd", choices=("lineage", "board"))
    ap.add_argument("query", nargs="?", default="")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "board":
        b = board()
        if a.json:
            print(json.dumps(b, ensure_ascii=False, indent=1))
        else:
            print(f"tracker {b['tracker']}: {b['total']} cards · {b['counts']}")
            for k in ("active", "blocked", "owner_gates"):
                print(f"{k}: {len(b[k])}")
                for r in b[k][:15]:
                    print(f"  - {r['card']} — {r['title'][:90]}")
        return 0
    x = lineage(a.query)
    print(json.dumps(x, ensure_ascii=False, indent=1, default=str) if a.json else render(x))
    return 0 if x.get("state") != "NOT_FOUND" else 2


if __name__ == "__main__":
    raise SystemExit(main())
