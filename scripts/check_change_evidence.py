#!/usr/bin/env python3
"""A significant removal must carry a change record — checked, not promised (ADR-537, owner 2026-10-02).

Owner requirement: «существующая функция не должна исчезать только потому, что новая сессия не
понимает, зачем её когда-то сделали». Measured the same day: in the three-portfolio epic a session
removed the home-page calculator's scenario column (owner-commissioned redesign task M3, 2026-07-12)
with the reason «it typed 0.20 and compared a target with a result» — two real defects — and with it
the user capability, whose origin it had not looked up. The memory assembler could not have told it:
the spec was not indexed. Nothing in the delivery path asked.

## What counts as a significant removal (proportionate: cosmetic edits never trigger)

| unit | where | detected when |
|---|---|---|
| ``py:<path>:<name>`` | top-level ``def``/``class`` in money-path / status / memory modules (``SCOPED_PY``) | the name is gone from the new file |
| ``route:<METHOD> <path>`` | ``@router.<method>("…")`` / ``@app.<method>`` in ``spa_core/api/`` | the route is gone from the pushed set |
| ``id:<value>`` / ``track:<value>`` | ``id="…"`` / ``data-track="…"`` in ``landing/src/`` | gone from EVERY new file of the pushed set (a move is not a removal) |
| ``export:<path>:<name>`` | ``export function|const`` in ``landing/src/lib`` | the export is gone from the new file |
| ``fn:<path>:<name>`` | a named ``function`` in a page/component script (``.astro``) | the function is gone from the new file |
| ``file:<path>`` | a deleted file in any of the scopes above | the new content is absent |

## What the record must hold

The commit message names it: ``Change-Record: <repo path>#<record id>``. The record is a fenced block

    ```change-record
    id: CR-…
    task: … · role: …
    component: …
    purpose: …                 # why it existed
    purpose_source: <repo path | commit sha | UNKNOWN>
    defect: …                  # what was wrong (or «none — superseded by …»)
    decision: …                # the chosen option
    alternative: …             # the option considered and not taken
    preserved: …               # behaviour that stays, and where
    changed: …                 # what changes on purpose
    removes: <unit>, <unit>    # EVERY detected unit, by its exact key
    consumers: …               # sources/readers affected
    owner_approval: not required (<subject>) | required: <card id>
    reversible: yes (<how>) | no (<why acceptable>)
    rollback: …
    ```

Deterministic part (this script): the reference resolves, every key is present and non-empty, every
detected unit is listed, ``purpose_source`` resolves to a file or a commit (or is UNKNOWN — then
``reversible`` must start with ``yes``: UNKNOWN is not OBSOLETE). Whether the reasoning is
SUFFICIENT is the independent reviewer's question, not this script's: a filled ``purpose`` field
proves nothing about the purpose.

## Three outcomes (invariant #17)

| rc | meaning |
|---|---|
| 0 | no significant removal, or every one is covered by a valid record |
| 1 | a removal without a valid record — refused, every unit named |
| 2 | NOT MEASURED — git unavailable / base unreadable; never reported as clean |

LLM_FORBIDDEN, stdlib only, read-only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

SCOPED_PY = ("spa_core/paper_trading/", "spa_core/defi_engine/", "spa_core/risk/", "spa_core/governance/",
             "spa_core/api/", "spa_core/studio_os/memory/", "scripts/generate_track_snapshot.py",
             "scripts/build_site_numbers.py", "scripts/build_site_constitution.py", "scripts/check_owner_gate.py",
             "scripts/safe_site_push.py", "push_to_github.py", "push_to_github_batch.py")
SITE = "landing/src/"
REQUIRED = ("id", "task", "component", "purpose", "purpose_source", "defect", "decision", "alternative",
            "preserved", "changed", "removes", "consumers", "owner_approval", "reversible", "rollback")

_RE_ID = re.compile(r'(?<![\w-])id="([A-Za-z][\w:-]*)"')
_RE_TRACK = re.compile(r'data-track="([^"{}]+)"')
_RE_EXPORT = re.compile(r"^\s*export\s+(?:async\s+)?(?:function|const|let)\s+([A-Za-z_$][\w$]*)", re.M)
_RE_FN = re.compile(r"\bfunction\s+([A-Za-z_$][\w$]{2,})\s*\(")
_RE_ROUTE = re.compile(r"@(?:router|app)\.(get|post|put|delete|patch|websocket)\(\s*['\"]([^'\"]+)['\"]")
_RE_REF = re.compile(r"^\s*Change-Record:\s*(\S+?)#(\S+)\s*$", re.M | re.I)
_RE_BLOCK = re.compile(r"```change-record\s*\n(.*?)\n```", re.S)


def _scoped_py(path: str) -> bool:
    return path.endswith(".py") and "/tests/" not in path and any(
        path == s or path.startswith(s) for s in SCOPED_PY)


def _site(path: str) -> bool:
    return path.startswith(SITE) and not path.startswith(SITE + "data/") and path.endswith(
        (".astro", ".js", ".ts", ".jsx", ".tsx"))


def _py_names(text: Optional[str]) -> Optional[set]:
    if text is None:
        return set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    return {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}


def removals(pairs: Iterable[Tuple[str, Optional[str], Optional[str]]]) -> Tuple[List[str], List[str]]:
    """Significant units present in an old file and absent from the new set. Returns (units, problems)."""
    pairs = list(pairs)
    units: List[str] = []
    problems: List[str] = []
    new_site_ids, new_site_tracks, new_routes = set(), set(), set()
    for path, _old, new in pairs:
        if new is None:
            continue
        if _site(path):
            new_site_ids |= set(_RE_ID.findall(new))
            new_site_tracks |= set(_RE_TRACK.findall(new))
        if path.startswith("spa_core/api/"):
            new_routes |= {f"{m.upper()} {p}" for m, p in _RE_ROUTE.findall(new)}
    for path, old, new in pairs:
        if old is None:
            continue
        if new is None and (_scoped_py(path) or _site(path)):
            units.append(f"file:{path}")
        if _scoped_py(path):
            before, after = _py_names(old), _py_names(new)
            if before is None or after is None:
                problems.append(f"{path}: not parseable — removals NOT MEASURED")
            else:
                units += [f"py:{path}:{n}" for n in sorted(before - after)]
            if path.startswith("spa_core/api/"):
                units += [f"route:{r}" for r in sorted({f"{m.upper()} {p}" for m, p in _RE_ROUTE.findall(old)}
                                                     - new_routes)]
        if _site(path):
            units += [f"id:{v}" for v in sorted(set(_RE_ID.findall(old)) - new_site_ids)]
            units += [f"track:{v}" for v in sorted(set(_RE_TRACK.findall(old)) - new_site_tracks)]
            if path.endswith(".astro") and new is not None:
                units += [f"fn:{path}:{n}" for n in sorted(set(_RE_FN.findall(old)) - set(_RE_FN.findall(new)))]
            if path.startswith(SITE + "lib/") and new is not None:
                units += [f"export:{path}:{n}" for n in sorted(set(_RE_EXPORT.findall(old))
                                                              - set(_RE_EXPORT.findall(new)))]
    return sorted(set(units)), problems


def parse_records(text: str) -> Dict[str, Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {}
    for block in _RE_BLOCK.findall(text or ""):
        rec: Dict[str, str] = {}
        key = None
        for line in block.splitlines():
            m = re.match(r"^([a-z_]+):\s*(.*)$", line)
            if m:
                key = m.group(1)
                rec[key] = m.group(2).strip()
            elif key and line.startswith((" ", "\t")):
                rec[key] = (rec[key] + " " + line.strip()).strip()
        if rec.get("id"):
            out[rec["id"]] = rec
    return out


def _resolves(source: str, repo: Path, read) -> bool:
    for token in re.split(r"[\s,;]+", source):
        token = token.strip("`()")
        if not token:
            continue
        if re.fullmatch(r"[0-9a-f]{7,40}", token):
            rc = subprocess.run(["git", "cat-file", "-e", f"{token}^{{commit}}"], cwd=str(repo),
                                capture_output=True).returncode
            if rc == 0:
                return True
        elif "/" in token or token.endswith(".md"):
            if read(token.split("#")[0]) is not None:
                return True
    return False


def validate(units: List[str], message: str, read, repo: Path) -> List[str]:
    """Problems with the evidence for ``units`` (empty = covered). ``read(path)`` returns text or None."""
    if not units:
        return []
    refs = _RE_REF.findall(message or "")
    if not refs:
        return ["no `Change-Record: <path>#<id>` line in the commit message for: " + ", ".join(units)]
    problems: List[str] = []
    covered: set = set()
    for path, rid in refs:
        text = read(path)
        if text is None:
            problems.append(f"Change-Record {path}#{rid}: file not found in the pushed set, the tree or the base")
            continue
        rec = parse_records(text).get(rid)
        if rec is None:
            problems.append(f"Change-Record {path}#{rid}: no ```change-record block with id {rid}")
            continue
        missing = [k for k in REQUIRED if not rec.get(k)]
        if missing:
            problems.append(f"Change-Record {rid}: empty or missing fields {missing}")
        src = rec.get("purpose_source", "")
        if src.upper().startswith("UNKNOWN"):
            if not rec.get("reversible", "").lower().startswith("yes"):
                problems.append(f"Change-Record {rid}: purpose UNKNOWN requires `reversible: yes …` "
                                "(UNKNOWN is not OBSOLETE)")
        elif src and not _resolves(src, repo, read):
            problems.append(f"Change-Record {rid}: purpose_source {src!r} resolves to no file and no commit")
        covered |= {u.strip() for u in re.split(r",\s*", rec.get("removes", "")) if u.strip()}
    uncovered = [u for u in units if u not in covered]
    if uncovered:
        problems.append("removed but not listed in any record's `removes`: " + ", ".join(uncovered))
    return problems


def _git(args: List[str], cwd: Path) -> Optional[str]:
    p = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    return p.stdout if p.returncode == 0 else None


def _top(path: Path) -> Optional[Path]:
    out = _git(["rev-parse", "--show-toplevel"], path if path.is_dir() else path.parent)
    return Path(out.strip()) if out else None


def run(files: List[str], message: str, base: str = "origin/main", staged: bool = False) -> Tuple[int, str]:
    if staged:
        repo = _top(Path.cwd())
        if repo is None:
            return 2, "NOT MEASURED: not a git tree"
        names = _git(["diff", "--cached", "--name-only", "--diff-filter=ACMRD"], repo)
        if names is None:
            return 2, "NOT MEASURED: staged diff unreadable"
        rels = [n for n in names.splitlines() if n]
        pairs = [(r, _git(["show", f"HEAD:{r}"], repo), _git(["show", f":{r}"], repo)) for r in rels]
    else:
        if not files:
            return 0, "nothing to check"
        repo = _top(Path(files[0]).resolve())
        if repo is None:
            return 2, "NOT MEASURED: the files are not in a git tree"
        if _git(["rev-parse", "--verify", f"{base}^{{commit}}"], repo) is None:
            return 2, f"NOT MEASURED: base {base} unknown in {repo}"
        pairs = []
        for f in files:
            p = Path(f).resolve()
            try:
                rel = str(p.relative_to(repo))
            except ValueError:
                return 2, f"NOT MEASURED: {f} is outside {repo}"
            old = _git(["show", f"{base}:{rel}"], repo)
            new = p.read_text(encoding="utf-8", errors="replace") if p.exists() else None
            pairs.append((rel, old, new))
    units, problems = removals(pairs)
    if problems:
        return 2, "NOT MEASURED: " + "; ".join(problems)
    pushed = {r: n for r, _o, n in pairs}

    def read(rel: str) -> Optional[str]:
        if rel in pushed:
            return pushed[rel]
        fp = repo / rel
        if fp.is_file():
            return fp.read_text(encoding="utf-8", errors="replace")
        return _git(["show", f"{base}:{rel}"], repo)

    bad = validate(units, message, read, repo)
    if bad:
        return 1, "REFUSED — significant removal without a valid change record:\n  - " + "\n  - ".join(bad)
    return 0, (f"OK: {len(units)} significant removal(s), each covered by a change record" if units
               else "OK: no significant removal")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0] if __doc__ else None)
    ap.add_argument("--files", nargs="*", default=[])
    ap.add_argument("--message", default="")
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--staged", action="store_true", help="check the git index against HEAD (pre-commit)")
    a = ap.parse_args(argv)
    msg = a.message
    if a.staged and not msg:
        mf = _top(Path.cwd())
        p = (mf / ".git" / "COMMIT_EDITMSG") if mf else None
        msg = p.read_text(encoding="utf-8") if p and p.is_file() else ""
    rc, text = run(a.files, msg, a.base, a.staged)
    print(text, file=sys.stderr if rc else sys.stdout)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
