"""Portable role context pack — STUDIO-OS-MODELS-01, increment 1 (ADR-OWN-2026-10-23).

# LLM_FORBIDDEN

A fresh architect/reviewer session — of ANY vendor or model — recovers one task without chat
history from a single versioned file. This is context PREPARATION, not a model router: it calls
no model, selects no provider and grants no permission.

    python -m spa_core.studio_os.memory role-pack --handover docs/evidence/<task>/HANDOVER_….md \
        --roadmap-item 17 [--role architect] [--root R] [--out DIR] [--at ISO] [--verified-sha SHA]
    # exit 0 complete · 1 complete with UNKNOWN sections · 2 not built

No new memory store. Everything is projected from what already exists:

* role and authority — ``docs/continuity/ARCHITECT_CONTEXT.md`` §3 (the row of the role; the role id
  is stable, the current participant is a separate field — a model never becomes the role);
* owner intent — the owner-directive lines of the ``docs/ROADMAP.md`` header and the roadmap item;
* the task — the curated task handover (an existing file; its sections are carried verbatim);
* decisions — every ADR id the handover or the roadmap item cites, resolved to its file;
* revision — MEASURED from git, not taken from prose: branch, HEAD, dirtiness, the server value of the
  branch (``ls-remote``, read-only; no network ⇒ UNKNOWN), and whether the code after the verified SHA
  is docs-only (``git diff --name-only <verified>..HEAD``);
* the company read model — the committed ``docs/continuity/state.json`` header, as reference.

Credentials never enter the pack: every text goes through the memory sanitizer (lines that look like a
credential are dropped and counted). Absent/unparsed inputs are UNKNOWN with a reason, never empty.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from spa_core.studio_os.memory.continuity import HEX40, UNKNOWN, _git, _roadmap_items
from spa_core.studio_os.memory.sources import sanitize

PACK_VERSION = "role-pack/1"
CODE_REPO = Path(__file__).resolve().parents[3]
CONTEXT_FILE = "docs/continuity/ARCHITECT_CONTEXT.md"
ROADMAP_FILE = "docs/ROADMAP.md"
STATE_FILE = "docs/continuity/state.json"

#: Stable role ids → the row of ARCHITECT_CONTEXT §3 that defines them. The participant (vendor/model)
#: is recorded separately and is NOT part of the role (ADR-OWN-2026-10-23 «roles, not vendor names»).
ROLES = {
    "architect": {"row": "Architecture Review Board", "participant": "ChatGPT"},
    "worker": {"row": "Claude Code", "participant": "Claude Code"},
}

#: What a fresh session must recover, and which handover headings carry it (keyword match, first wins).
TOPICS = (
    ("goal", ("цель", "goal")),
    ("revision", ("ветка", "sha", "revision", "ревизи")),
    ("decisions", ("решени", "decision")),
    ("verification", ("ci", "census", "проверк")),
    ("open_problems_and_next_step", ("блокер", "следующ", "next", "open")),
    ("constraints", ("разрешено", "запрещено", "constraint", "ограничен")),
)

_ADR = re.compile(r"\bADR-(?:OWN-\d{4}-\d{2}-\d{2}-[a-z0-9-]+|\d{3,4})\b")


class PackError(Exception):
    """The pack cannot be built at all (no handover, not a git tree)."""


def _sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _clean_text(text: str) -> Tuple[str, int]:
    return sanitize(text)


def _sections(md: str) -> List[Tuple[str, str]]:
    """``## heading`` → body, in order. Text before the first heading is the preamble."""
    out: List[Tuple[str, str]] = []
    cur, buf = "preamble", []
    for line in md.splitlines():
        if line.startswith("## "):
            out.append((cur, "\n".join(buf).strip()))
            cur, buf = line[3:].strip(), []
        else:
            buf.append(line)
    out.append((cur, "\n".join(buf).strip()))
    return [(h, b) for h, b in out if b]


def _role_row(context: str, role: str) -> Optional[str]:
    key = ROLES[role]["row"]
    for line in context.splitlines():
        if line.startswith("|") and key in line:
            return line.strip()
    return None


def _owner_directives(roadmap: str) -> List[str]:
    """Header lines of the roadmap that state an owner directive (multi-line quote joined)."""
    head = roadmap.split("\n## ", 1)[0]
    joined = re.sub(r"\n>\s*", " ", head)
    return [m.group(0).strip() for m in
            re.finditer(r"(?:Latest|Continuing|Last confirmed)[^.]*?owner[^>]*?(?=(?:Latest|Continuing|Status words|$))",
                        joined, re.S)]


def _resolve_adr(root: Path, adr: str) -> Dict[str, Any]:
    for reg in ("docs/decisions", "docs/adr"):
        d = root / reg
        if not d.is_dir():
            continue
        hits = sorted(p for p in d.glob(f"{adr}*.md"))
        if hits:
            first = hits[0].read_text(encoding="utf-8", errors="replace").splitlines()
            title = next((ln.lstrip("# ").strip() for ln in first if ln.startswith("#")), UNKNOWN)
            return {"id": adr, "path": str(hits[0].relative_to(root)), "title": title,
                    "files": len(hits)}
    return {"id": adr, "path": UNKNOWN, "title": UNKNOWN, "files": 0,
            "reason": "no file in docs/decisions or docs/adr"}


def _verified_sha(handover: str) -> Optional[str]:
    for line in handover.splitlines():
        low = line.lower()
        if "проверенный код" in low or "verified code" in low:
            m = re.search(r"[0-9a-f]{40}", line)
            if m:
                return m.group(0)
    return None


def revision_facts(root: Path, verified: Optional[str]) -> Dict[str, Any]:
    """Measured, not quoted: what the tree holds and how it relates to the verified code."""
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    head = _git(root, "rev-parse", "HEAD")
    status = _git(root, "status", "--porcelain", "--untracked-files=all")
    server = None
    if branch and branch != "HEAD":
        out = _git(root, "ls-remote", "origin", f"refs/heads/{branch}")
        server = out.split()[0] if out and HEX40.match(out.split()[0]) else None
    facts: Dict[str, Any] = {
        "branch": branch or UNKNOWN,
        "head": head if head and HEX40.match(head) else UNKNOWN,
        "dirty": (None if status is None else [ln for ln in status.splitlines() if ln.strip()]),
        "server_branch_head": server or UNKNOWN,
        "head_equals_server": (None if not (server and head) else head == server),
        "verified_code_sha": verified or UNKNOWN,
    }
    if verified and head and HEX40.match(head):
        known = _git(root, "cat-file", "-e", f"{verified}^{{commit}}") is not None
        ancestor = _git(root, "merge-base", "--is-ancestor", verified, head) is not None
        changed = _git(root, "diff", "--name-only", f"{verified}..{head}") if known else None
        files = [f for f in (changed or "").splitlines() if f]
        code = [f for f in files if not f.startswith("docs/")]
        facts.update({
            "verified_is_ancestor_of_head": ancestor if known else None,
            "changed_since_verified": files if changed is not None else UNKNOWN,
            "code_changed_since_verified": code if changed is not None else UNKNOWN,
            "head_code_is_verified": (None if changed is None else not code),
        })
    else:
        facts.update({"verified_is_ancestor_of_head": None, "changed_since_verified": UNKNOWN,
                      "code_changed_since_verified": UNKNOWN, "head_code_is_verified": None})
    return facts


def build(root: Path, handover_rel: str, roadmap_item: Optional[int], role: str = "architect",
          at: Optional[str] = None, verified: Optional[str] = None) -> Dict[str, Any]:
    if role not in ROLES:
        raise PackError(f"unknown role {role!r}; declared roles: {sorted(ROLES)}")
    if _git(root, "rev-parse", "--show-toplevel") is None:
        raise PackError(f"{root} is not a git tree: the revision cannot be measured")
    hpath = root / handover_rel
    try:
        hbytes = hpath.read_bytes()
    except OSError as exc:
        raise PackError(f"task handover not readable: {handover_rel}: {exc}") from exc

    inputs: Dict[str, str] = {handover_rel: _sha256(hbytes)}
    dropped = 0
    unknown: List[str] = []

    def read(rel: str) -> Optional[str]:
        try:
            b = (root / rel).read_bytes()
        except OSError:
            unknown.append(f"{rel}: not readable")
            return None
        inputs[rel] = _sha256(b)
        return b.decode("utf-8", errors="replace")

    handover, n = _clean_text(hbytes.decode("utf-8", errors="replace"))
    dropped += n
    context = read(CONTEXT_FILE) or ""
    roadmap = read(ROADMAP_FILE) or ""

    sections = _sections(handover)
    topics: Dict[str, Any] = {}
    for key, words in TOPICS:
        hit = next(((h, b) for h, b in sections if any(w in h.lower() for w in words)
                    and h not in [t.get("heading") for t in topics.values() if isinstance(t, dict)]),
                   None)
        if hit:
            topics[key] = {"heading": hit[0], "text": hit[1]}
        else:
            topics[key] = UNKNOWN
            unknown.append(f"topic {key}: no handover section matched {list(words)}")

    row = _role_row(context, role)
    if row is None:
        unknown.append(f"role {role}: row {ROLES[role]['row']!r} not found in {CONTEXT_FILE} §3")
    row, n = _clean_text(row or "")
    dropped += n

    item = None
    if roadmap_item is not None:
        item = next((t for i, t in _roadmap_items(roadmap) if i == roadmap_item), None)
        if item is None:
            unknown.append(f"roadmap item {roadmap_item}: not found in {ROADMAP_FILE}")
    directives = _owner_directives(roadmap) if roadmap else []
    if not directives:
        unknown.append("owner directives: none parsed from the roadmap header")

    cited = sorted(set(_ADR.findall(handover)) | set(_ADR.findall(item or ""))
                   | set(a for d in directives for a in _ADR.findall(d)))
    adrs = [_resolve_adr(root, a) for a in cited]
    unknown += [f"{a['id']}: {a['reason']}" for a in adrs if a.get("reason")]

    verified = verified or _verified_sha(handover)
    if not verified:
        unknown.append("verified code SHA: not stated in the handover and not given")
    rev = revision_facts(root, verified)
    for k in ("head", "server_branch_head"):
        if rev[k] == UNKNOWN:
            unknown.append(f"revision {k}: not measured")

    company = None
    st = read(STATE_FILE)
    if st:
        try:
            meta = json.loads(st).get("header") or {}
            company = {k: meta.get(k, UNKNOWN) for k in
                       ("generated_at", "repo_commit", "origin_commit", "verdict_at_generation",
                        "copy_role", "latest_accepted_epic")}
            unknown += [f"{STATE_FILE} header: no {k!r}" for k, v in company.items() if v == UNKNOWN]
        except ValueError:
            unknown.append(f"{STATE_FILE}: not JSON")

    return {
        "pack_version": PACK_VERSION,
        "generated_at": at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "authority": "DERIVED — files and git are canonical; this pack is a projection",
        "role": {"role_id": role, "authority_row": row or UNKNOWN,
                 "current_participant": ROLES[role]["participant"],
                 "note": "the role is stable; the participant (vendor/model) is replaceable and "
                         "gains no permission by being selected"},
        "owner_intent": {"directives": directives, "roadmap_item": roadmap_item,
                         "roadmap_text": item or UNKNOWN},
        "task": topics,
        "revision": rev,
        "decisions": adrs,
        "company_read_model": company or UNKNOWN,
        "inputs_sha256": inputs,
        "credentials_dropped_lines": dropped,
        "unknown": unknown,
        "not_this": "context preparation only — no model call, no provider routing, no permission",
    }


def render(pack: Dict[str, Any]) -> str:
    r = pack["revision"]
    out = [f"# Role context pack — {pack['role']['role_id']} ({pack['pack_version']})", "",
           f"> {pack['authority']}. Generated {pack['generated_at']}. {pack['not_this']}.", "",
           "## Role", "", f"- role_id: `{pack['role']['role_id']}` · current participant: "
           f"{pack['role']['current_participant']} ({pack['role']['note']})",
           f"- authority: {pack['role']['authority_row']}", "",
           "## Owner intent", ""]
    out += [f"- {d}" for d in pack["owner_intent"]["directives"]] or ["- UNKNOWN"]
    out += ["", f"Roadmap item {pack['owner_intent']['roadmap_item']}: "
            f"{pack['owner_intent']['roadmap_text'][:1500]}", "",
            "## Revision (measured from git)", ""]
    for k in ("branch", "head", "server_branch_head", "head_equals_server", "verified_code_sha",
              "verified_is_ancestor_of_head", "head_code_is_verified", "code_changed_since_verified",
              "changed_since_verified", "dirty"):
        out.append(f"- {k}: {r.get(k)}")
    out += ["", "## Decisions cited", ""]
    out += [f"- {a['id']}: {a['title']} — `{a['path']}`" for a in pack["decisions"]] or ["- none"]
    for key, _w in TOPICS:
        t = pack["task"][key]
        out += ["", f"## Task · {key}", ""]
        out.append(t["text"] if isinstance(t, dict) else "UNKNOWN")
    out += ["", "## UNKNOWN", ""] + ([f"- {u}" for u in pack["unknown"]] or ["- none"])
    out += ["", f"Credential-like lines dropped: {pack['credentials_dropped_lines']}",
            "", "## Inputs (sha256)", ""] + [f"- `{k}` {v}" for k, v in pack["inputs_sha256"].items()]
    return "\n".join(out) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="role-pack", description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--root", type=Path, default=CODE_REPO)
    ap.add_argument("--handover", required=True, help="repo-relative path of the task handover")
    ap.add_argument("--roadmap-item", type=int, default=None)
    ap.add_argument("--role", default="architect", choices=sorted(ROLES))
    ap.add_argument("--verified-sha", default=None)
    ap.add_argument("--at", default=None)
    ap.add_argument("--out", type=Path, default=None, help="directory for pack.json + pack.md")
    a = ap.parse_args(argv)
    try:
        pack = build(a.root, a.handover, a.roadmap_item, a.role, a.at, a.verified_sha)
    except PackError as exc:
        print(f"ROLE PACK NOT BUILT: {exc}")
        return 2
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
        from spa_core.utils.atomic import atomic_save, atomic_save_text
        atomic_save(pack, str(a.out / "pack.json"))
        atomic_save_text(render(pack), str(a.out / "pack.md"))
        print(f"ROLE PACK {pack['pack_version']} → {a.out}/pack.md · UNKNOWN {len(pack['unknown'])}")
    else:
        sys.stdout.write(render(pack))
    return 1 if pack["unknown"] else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
