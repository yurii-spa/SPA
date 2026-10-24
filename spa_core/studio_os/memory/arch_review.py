"""One command: a SAFE architecture review of one task by the chosen provider (STUDIO-OS-MODELS-01, inc. 4).

Lives in ``memory`` (next to ``role_pack``), not in ``model_roles``: the dependency runs memory → model_roles
only — the transport layer never imports its callers (held by ``test_memory_answer_via_contract``).

# LLM_FORBIDDEN

    python -m spa_core.studio_os.memory arch-review --handover <repo-rel handover> --task-id ID \
        --task "<one task>" --verified-sha <40-hex> --provider <id> --out DIR \
        [--roadmap-item 17] [--extra-context FILE ...] [--fixture F.json]

What it does — and nothing else:

1. builds the context with the existing :mod:`spa_core.studio_os.memory.role_pack` (role ``architect``,
   the given verified revision), plus small EXPLICIT extra fragments (implementation snippets, links),
   each sanitized by the same credential sanitizer and fingerprinted;
2. calls role ``architect`` through the existing contract (:func:`contract.execute`) with the provider
   named explicitly (repository assignments stay null — no routing);
3. writes ``DIR/context.md`` (exactly what the model saw), ``DIR/review.json`` (task id, revisions, context
   hash, provider, status, time, reported usage, completeness, parsed sections) and
   ``DIR/recommendation.md`` (facts → unknowns → decision with reason → acceptance criteria → one
   copyable task block for the implementer).

It never edits the roadmap, cards, ADRs or permissions and never records an owner approval: the output
directory is the only thing it writes. A successful model call is NOT evidence that the context was
complete, and NOT an architecture acceptance — both are stated in every output.
Exit: 0 ok and structure complete · 1 provider outcome ≠ ok, or the answer lacks a required section ·
2 refused / not built.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from spa_core.studio_os.memory import role_pack
from spa_core.studio_os.model_roles import adapters as ad
from spa_core.studio_os.model_roles.contract import ConfigError, Request, execute, load_config

REVIEW_VERSION = "arch-review/1"
ROLE = "architect"
EXTRA_LIMIT_CHARS = 20000
#: Section headings the answer must carry, in this order (the parser is keyed on them).
SECTIONS = ("FACTS", "UNKNOWNS", "DECISION", "ACCEPTANCE CRITERIA", "CLAUDE TASK")
DISCLAIMER = ("PROPOSAL ONLY — not an owner approval, not an ARB acceptance, changes nothing by itself. "
              "A successful model call does not prove the context was complete.")

INSTRUCTION = """Architecture review of ONE task. Use ONLY the context below (project pack + fragments).
TASK: {task}

Reply in EXACTLY these five sections, with these headings, in this order:
## FACTS — what the context establishes, each with its source path.
## UNKNOWNS — what the context does NOT establish (say UNKNOWN; do not guess).
## DECISION — the recommended solution and WHY (alternatives you rejected, one line each).
## ACCEPTANCE CRITERIA — machine-checkable conditions (tests/commands), before the work starts.
## CLAUDE TASK — ONE fenced code block (```text … ```) the owner can copy to the implementer: scope,
files, constraints (no production, no main, no tracker), checks, and what NOT to do.
This is a proposal: do not claim approval or acceptance."""


class ReviewError(Exception):
    """The review cannot be built — refused before any model call."""


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _git(root: Path, *args: str) -> Optional[str]:
    try:
        p = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def extra_fragments(paths: Sequence[Path]) -> tuple:
    """(markdown block, rows, unknown) — each fragment sanitized and fingerprinted; limit enforced."""
    rows: List[Dict[str, Any]] = []
    unknown: List[str] = []
    parts: List[str] = []
    total = 0
    for p in paths:
        try:
            raw = Path(p).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            unknown.append(f"extra fragment {p}: not readable ({exc})")
            continue
        clean, dropped = role_pack._clean_text(raw)
        if dropped:
            unknown.append(f"extra fragment {Path(p).name}: {dropped} credential-like line(s) dropped")
        total += len(clean)
        if total > EXTRA_LIMIT_CHARS:
            raise ReviewError(f"extra fragments exceed {EXTRA_LIMIT_CHARS} chars — give smaller fragments")
        rows.append({"name": Path(p).name, "sha256": _sha(clean), "chars": len(clean),
                     "credential_lines_dropped": dropped})
        parts.append(f"### Fragment: {Path(p).name}\n\n{clean.rstrip()}\n")
    return ("\n".join(parts), rows, unknown)


def parse_sections(text: str) -> Dict[str, Optional[str]]:
    """Body of each required ``## SECTION`` heading; ``None`` — the section is missing."""
    out: Dict[str, Optional[str]] = {s: None for s in SECTIONS}
    marks = []
    for s in SECTIONS:
        m = re.search(r"(?mi)^#{1,4}\s*" + re.escape(s) + r"\b.*$", text)
        if m:
            marks.append((m.start(), m.end(), s))
    marks.sort()
    for i, (_a, b, s) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        body = text[b:end].strip()
        out[s] = body or None
    return out


def claude_task_block(section: Optional[str]) -> Optional[str]:
    if not section:
        return None
    m = re.search(r"```[a-zA-Z]*\n(.*?)```", section, re.S)
    return m.group(1).strip() if m else None


def run_review(root: Path, *, handover: str, task_id: str, task: str, verified_sha: str,
               provider: Optional[str], out: Path, roadmap_item: Optional[int] = None,
               extra: Sequence[Path] = (), adapters: Optional[Dict] = None,
               config: Optional[Dict] = None, at: Optional[str] = None) -> Dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{40}", verified_sha or ""):
        raise ReviewError("--verified-sha must be a full 40-hex commit id (the EXACT verified revision)")
    if _git(root, "cat-file", "-e", f"{verified_sha}^{{commit}}") is None:
        raise ReviewError(f"verified revision {verified_sha[:12]} is not a commit in {root}")
    try:
        pack = role_pack.build(root, handover, roadmap_item, ROLE, at, verified_sha)
    except role_pack.PackError as exc:
        raise ReviewError(f"context pack not built: {exc}") from exc
    frag_md, frag_rows, frag_unknown = extra_fragments(extra)
    context = role_pack.render(pack) + ("\n## Task fragments (explicit, sanitized)\n\n" + frag_md if frag_md else "")
    unknown = list(pack["unknown"]) + frag_unknown
    req = Request(ROLE, task_id, INSTRUCTION.format(task=task), context, "role-pack + fragments")
    res = execute(req, config=config or load_config(), provider_id=provider,
                  adapters=adapters if adapters is not None else {"claude_cli": ad.claude_cli()})
    sections = parse_sections(res.text) if res.status == "ok" else {s: None for s in SECTIONS}
    block = claude_task_block(sections["CLAUDE TASK"])
    missing = [s for s, v in sections.items() if v is None] + ([] if block or res.status != "ok"
                                                               else ["CLAUDE TASK code block"])
    rev = pack["revision"]
    record = {
        "review_version": REVIEW_VERSION, "task_id": task_id, "task": task,
        "generated_at": at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "revisions": {"verified_code_sha": verified_sha, "head": rev.get("head"),
                      "server_branch_head": rev.get("server_branch_head"),
                      "head_code_is_verified": rev.get("head_code_is_verified"),
                      "code_changed_since_verified": rev.get("code_changed_since_verified"),
                      "branch": rev.get("branch")},
        "context_sha256": res.context_sha256, "context_chars": len(context),
        "context_complete": not unknown, "context_unknown": unknown, "fragments": frag_rows,
        "provider": res.provider_id, "real_provider": res.real_provider, "model": res.model,
        "status": res.status, "reason": res.reason, "attempts": res.attempts, "elapsed_s": res.elapsed_s,
        "usage": res.usage, "sections": sections, "claude_task": block,
        "structure_complete": res.status == "ok" and not missing, "missing_sections": missing,
        "disclaimer": DISCLAIMER, "writes": "only this output directory",
    }
    out.mkdir(parents=True, exist_ok=True)
    from spa_core.utils.atomic import atomic_save, atomic_save_text
    atomic_save_text(context, str(out / "context.md"))
    atomic_save(record, str(out / "review.json"))
    atomic_save_text(render_recommendation(record), str(out / "recommendation.md"))
    return record


def render_recommendation(r: Dict[str, Any]) -> str:
    rv = r["revisions"]
    head = [f"# Architecture review — {r['task_id']}", "",
            f"> {r['disclaimer']}", "",
            f"- task: {r['task']}",
            f"- verified code: `{rv['verified_code_sha']}` · HEAD `{rv['head']}` · HEAD code is verified: "
            f"{rv['head_code_is_verified']}",
            f"- provider: `{r['provider']}` (real provider: {r['real_provider']}) · model (as reported): {r['model']}",
            f"- status: **{r['status']}** · attempts {r['attempts']} · {r['elapsed_s']} s · usage: "
            f"{json.dumps(r['usage'], ensure_ascii=False)}",
            f"- context sha256 `{r['context_sha256']}` · {r['context_chars']} chars · complete: "
            f"**{r['context_complete']}**"]
    if r["context_unknown"]:
        head += ["", "## Context gaps (UNKNOWN)", ""] + [f"- {u}" for u in r["context_unknown"]]
    if r["status"] != "ok":
        return "\n".join(head + ["", f"## No recommendation — {r['status']}", "", str(r["reason"])]) + "\n"
    body = []
    for s in SECTIONS:
        body += ["", f"## {s.title()}", "", r["sections"][s] or "MISSING — the answer did not contain this section"]
    if r["missing_sections"]:
        body += ["", "## Structure incomplete", "", ", ".join(r["missing_sections"])]
    return "\n".join(head + body) + "\n"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="spa_core.studio_os.memory arch-review")
    ap.add_argument("--root", type=Path, default=role_pack.CODE_REPO)
    ap.add_argument("--handover", required=True)
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--task", required=True)
    ap.add_argument("--verified-sha", required=True)
    ap.add_argument("--provider", default=None, help="explicit provider id (no default routing)")
    ap.add_argument("--roadmap-item", type=int, default=None)
    ap.add_argument("--extra-context", type=Path, action="append", default=[])
    ap.add_argument("--fixture", type=Path, default=None, help="answers for the TEST adapter")
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    adapters = {"claude_cli": ad.claude_cli()}
    if a.fixture:
        adapters["fixture"] = ad.fixture_from_file(a.fixture)
    try:
        cfg = load_config(a.config)
        rec = run_review(a.root, handover=a.handover, task_id=a.task_id, task=a.task,
                         verified_sha=a.verified_sha, provider=a.provider, out=a.out,
                         roadmap_item=a.roadmap_item, extra=a.extra_context, adapters=adapters, config=cfg)
    except (ReviewError, ConfigError) as exc:
        print(f"REVIEW NOT BUILT: {exc}")
        return 2
    print(f"{rec['status']} · structure complete {rec['structure_complete']} · context complete "
          f"{rec['context_complete']} → {a.out}/recommendation.md")
    if rec["status"] == "refused":
        return 2
    return 0 if rec["structure_complete"] else 1
