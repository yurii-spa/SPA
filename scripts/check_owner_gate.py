#!/usr/bin/env python3
# LLM_FORBIDDEN
"""OWNER-GATE guard — blocks autonomous auto-ship of OWNER-GATED site changes.

The site is push==live (Cloudflare Pages builds landing/ on every push to main).
The autonomous orchestrator may auto-ship SAFE site changes (layout/CSS, component
refactors, non-legal copy, SEO, bugfixes, DYNAMIC number reads), but a protected
set of change-classes must NEVER auto-ship — they route to an owner-decision card:

  A  solicitation language        (.claude/rules/site-copy.md, CLAUDE.md #8)
  B  displayed APY/yield NUMBERS  (owner-gated)
  C  tier NAMING + "SPA" brand expansion (owner-gated)
  D  legal / disclaimer copy      (owner-gated)
  E  APY-honesty tokens REMOVED   (evidence L0-L6, tail-always-visible)

Detection substrates
--------------------
  * Structured JSON (landing/src/lib/tier_bands.json, landing/src/data/track_snapshot.json):
    parse OLD vs NEW and field-diff — robust, no regex guessing.
  * Free copy (.astro/.jsx/.ts/.html): bilingual EN+RU regex on ADDED / REMOVED
    diff-hunk lines only.

Custodian exemption (not forgeable)
-----------------------------------
  track_snapshot.json is legitimately auto-updated by deploy_site_snapshot.py. We do
  NOT trust the commit message. Instead: regenerate the snapshot from the committed
  data/ canon (scripts/generate_track_snapshot.py) and compare (ignoring the volatile
  generated_at). Byte-equivalent → deterministic custodian output → EXEMPT. A hand
  edited number will not match regeneration → GATED. (Only available where data/ is
  present, i.e. the pre-push self-check on the owner's machine — not in CI.)

Owner-approval bypass
---------------------
  A change touching a gated class ships only if the push carries a commit trailer
  `Owner-Approved: own-NN` AND that card exists with status: owner-done (owner-only —
  spa_core.owner_queue enforces it) AND its `approves:` scope covers the violations.

Design: pure stdlib, deterministic, no LLM (# LLM_FORBIDDEN). Reads read-only; writes
only data/owner_gate_check.json (gitignored) when --report.

Exit: 0 clean · 2 owner-gated violation(s) · 1 tool/IO error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ── which paths are in scope (the deploy surface) ───────────────────────────
_SITE_PREFIX = "landing/"
_TIER_BANDS = "landing/src/lib/tier_bands.json"
_TRACK_SNAPSHOT = "landing/src/data/track_snapshot.json"

# Legal pages — ANY diff touching these is Class D (path-based).
_LEGAL_PATHS = frozenset(
    {
        "landing/src/components/Disclaimer.astro",
        "landing/src/pages/disclaimer.astro",
        "landing/src/pages/risk-disclosure.astro",
    }
)

# tier_bands.json per-tier field taxonomy.
_TB_NUMBER_FIELDS = (  # Class B — displayed yield/drawdown numbers
    "band_en", "band_ru", "nav_band_en", "nav_band_ru",
    "dd_short_en", "dd_short_ru", "tail_en", "tail_ru",
)
_TB_IDENTITY_FIELDS = ("key", "en", "ru", "alt_en", "alt_ru")  # Class C — naming
_TB_EVIDENCE_FIELDS = ("evidence_en", "evidence_ru")  # Class E — honesty tokens

# track_snapshot.json numeric fields (Class B).
_TS_NUMBER_FIELDS = (
    "nav_usd", "end_equity", "paper_apy_pct", "max_drawdown_pct",
    "gates_passed", "gates_total", "real_track_days",
)

# ── regexes (compiled once) ─────────────────────────────────────────────────
# Class A — solicitation (active-offer phrasing). EN + RU.
_RE_SOLICIT = re.compile(
    r"minimum\s+(?:investment|deposit|to\s+invest)"
    r"|withdrawals?\s+within\s+\d+\s+days?"
    r"|no\s+lock[-\s]?up"
    r"|fee\s+after\s+kyc"
    r"|guaranteed\s+returns?"
    r"|минимальн\w+\s+(?:сумма|вклад|инвест)"
    r"|вывод\w*\s+(?:в\s+течени[ие]|за)\s+\d+\s+дн"
    r"|без\s+блокировк"
    r"|комисси\w+\s+после\s+kyc"
    r"|гарантированн\w+\s+(?:доход|прибыл)",
    re.IGNORECASE,
)
# Class B — a percent literal next to a yield keyword (a BAKED number, not a read).
_RE_YIELD_NUMBER = re.compile(
    r"(?:up\s+to|net|apy|yield|годовых|доходност)\D{0,12}\d{1,3}(?:\.\d+)?\s*%"
    r"|\d{1,3}(?:\.\d+)?\s*%\s*(?:net\s+)?apy",
    re.IGNORECASE,
)
# A dynamic read (snap.paper_apy_pct, {apy}, toFixed) — NOT a baked literal. Suppresses B.
_RE_DYNAMIC = re.compile(
    r"snap\.|initialFacts|\{[^}]*(?:apy|pct|nav|equity|yield|days|gates)[^}]*\}"
    r"|\.toFixed\(|fmtPct|fmtUsd|f\.[a-z_]+|props\.",
    re.IGNORECASE,
)
# The dynamic-read exemption is applied per MATCH SPAN, not per whole line: only a
# dynamic token WITHIN this many chars of a baked percent suppresses it. A wider (line-
# level) suppressor let a hardcoded "30% net APY" ship whenever any unrelated dynamic
# token ({snap.x}, props.) sat elsewhere on the same line — a fail-OPEN. Kept small so an
# adjacent `{apy}%` / `.toFixed()%` read is still exempt but a distant literal still gates.
_DYNAMIC_WINDOW = 6
# Class C — a "SPA" brand expansion that differs from canon.
_CANON_SPA_EXPANSION = "smart passive aggregator"
_RE_SPA_EXPANSION = re.compile(
    r"\bSPA\b[^\n]{0,24}?\b([A-Z][a-z]+)\s+([A-Z][a-z]+)\s+([A-Z][a-z]+)\b"
    r"|\b([A-Z][a-z]+)\s+([A-Z][a-z]+)\s+([A-Z][a-z]+)\b[^\n]{0,8}?\(SPA\)",
)
# Class D legal copy is protected PATH-BASED (the legal files in _LEGAL_PATHS). We do
# NOT scan free text for legal phrases: "not investment advice" / "paper / research"
# appear in ordinary marketing prose, so a content detector over-gates every copy
# refactor into an owner card — noise that makes auto-ship useless. The disclaimer text
# itself lives in Disclaimer.astro / the legal pages, which the path rule already gates.
#
# Class E — honesty tokens. Narrow to the SPECIFIC evidence labels (level + refused-for-
# live). Tier drawdown/tail budgets live in tier_bands.json and are field-diffed (Class E
# there), so we do NOT gate on the generic word "drawdown/просадка" in free prose.
_RE_EVIDENCE_TOKEN = re.compile(
    r"\bL[0-6]\b\s*·"
    r"|refused\s+for\s+live|для\s+live\s+отказан",
    re.IGNORECASE,
)


# ── diff acquisition ────────────────────────────────────────────────────────
def _git(args: list[str], cwd: Path) -> str:
    out = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True
    )
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout


def _changed_paths_and_hunks(
    diff_text: str,
) -> tuple[list[str], dict[str, list[tuple[str, int, str]]]]:
    """Parse `git diff --unified=0` → (changed paths, {path: [(sign,line,text)]}).

    sign is '+' or '-'. line is the NEW-file line for '+', OLD-file line for '-'.
    """
    paths: list[str] = []
    hunks: dict[str, list[tuple[str, int, str]]] = {}
    cur: str | None = None
    old_ln = new_ln = 0
    for raw in diff_text.splitlines():
        if raw.startswith("+++ b/"):
            cur = raw[6:].strip()
            if cur == "/dev/null":
                cur = None
            elif cur not in hunks:
                paths.append(cur)
                hunks[cur] = []
        elif raw.startswith("--- ") or raw.startswith("diff --git"):
            continue
        elif raw.startswith("@@"):
            m = re.search(r"-(\d+)(?:,\d+)?\s+\+(\d+)(?:,\d+)?", raw)
            if m:
                old_ln = int(m.group(1))
                new_ln = int(m.group(2))
        elif cur is not None and raw.startswith("+") and not raw.startswith("+++"):
            hunks[cur].append(("+", new_ln, raw[1:]))
            new_ln += 1
        elif cur is not None and raw.startswith("-") and not raw.startswith("---"):
            hunks[cur].append(("-", old_ln, raw[1:]))
            old_ln += 1
        else:
            old_ln += 1
            new_ln += 1
    return paths, hunks


def _blob(ref: str, path: str, cwd: Path) -> str | None:
    """Content of `path` at git `ref` (or None if absent)."""
    out = subprocess.run(
        ["git", "show", f"{ref}:{path}"], cwd=str(cwd), capture_output=True, text=True
    )
    return out.stdout if out.returncode == 0 else None


def _acquire(
    mode: str, base: str | None, head: str | None, files: list[str] | None, repo: Path
):
    """Return (diff_text, old_ref) for the chosen mode. old_ref names the baseline
    used for JSON field-diff of structured files."""
    if mode == "git-range":
        b = base or "HEAD~1"
        h = head or "HEAD"
        return _git(["diff", "--unified=0", b, h], repo), b
    if mode == "worktree":
        return _git(["diff", "--unified=0", "origin/main", "--", "landing/"], repo), "origin/main"
    if mode == "files":
        # Compare each given local file against origin/main; synthesize a diff.
        parts: list[str] = []
        for f in files or []:
            rel = _rel(f, repo)
            old = _blob("origin/main", rel, repo)
            try:
                new = (repo / rel).read_text(encoding="utf-8", errors="replace")
            except OSError:
                new = ""
            if old == new:
                continue
            parts.append(_unified(rel, old or "", new))
        return "\n".join(parts), "origin/main"
    raise ValueError(f"unknown diff-mode {mode}")


def _rel(f: str | os.PathLike, repo: Path) -> str:
    p = Path(f)
    try:
        return str(p.resolve().relative_to(repo))
    except ValueError:
        return str(f)


def _unified(rel: str, old: str, new: str) -> str:
    import difflib

    diff = difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile=f"a/{rel}", tofile=f"b/{rel}", n=0,
    )
    return "".join(diff)


# ── JSON field-diff for the two structured sources ──────────────────────────
def _json_at(ref: str, path: str, repo: Path) -> dict[str, Any] | None:
    txt = _blob(ref, path, repo)
    if txt is None:
        return None
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        return None


def _tier_bands_violations(old: Any, new: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(new, dict):
        return out
    old = old if isinstance(old, dict) else {}
    for tier in ("conservative", "balanced", "aggressive"):
        o = old.get(tier, {}) if isinstance(old.get(tier), dict) else {}
        n = new.get(tier, {}) if isinstance(new.get(tier), dict) else {}
        if not n:
            continue
        for fld in _TB_NUMBER_FIELDS:
            if o.get(fld) != n.get(fld):
                out.append(_v(_TIER_BANDS, 0, "B", "tier_bands.number",
                              f"{tier}.{fld}: {o.get(fld)!r} → {n.get(fld)!r}"))
        for fld in _TB_IDENTITY_FIELDS:
            if o.get(fld) != n.get(fld):
                out.append(_v(_TIER_BANDS, 0, "C", "tier_bands.naming",
                              f"{tier}.{fld}: {o.get(fld)!r} → {n.get(fld)!r}"))
        for fld in _TB_EVIDENCE_FIELDS:
            # gate if an evidence token disappears / changes
            if o.get(fld) and o.get(fld) != n.get(fld):
                out.append(_v(_TIER_BANDS, 0, "E", "tier_bands.evidence",
                              f"{tier}.{fld}: {o.get(fld)!r} → {n.get(fld)!r}"))
    return out


def _track_snapshot_violations(
    old: Any, new: Any, exempt: bool
) -> list[dict[str, Any]]:
    if exempt:
        return []
    out: list[dict[str, Any]] = []
    if not isinstance(new, dict):
        return out
    old = old if isinstance(old, dict) else {}

    def _walk(o, n, prefix=""):
        if isinstance(n, dict):
            for k, nv in n.items():
                ov = o.get(k) if isinstance(o, dict) else None
                key = f"{prefix}{k}"
                base = k
                if base in _TS_NUMBER_FIELDS or base.endswith(("_pct", "_usd")):
                    if ov != nv and not isinstance(nv, (dict, list)):
                        out.append(_v(_TRACK_SNAPSHOT, 0, "B", "snapshot.number",
                                      f"{key}: {ov!r} → {nv!r}"))
                if isinstance(nv, (dict, list)):
                    _walk(ov if isinstance(ov, (dict, list)) else {}, nv, key + ".")

    _walk(old, new)
    return out


def _snapshot_is_custodian_equivalent(repo: Path) -> bool:
    """True if the working-tree track_snapshot.json byte-equals a fresh regeneration
    from the committed data/ canon (ignoring volatile fields). Requires data/*.json."""
    try:
        import importlib.util

        gen = repo / "scripts" / "generate_track_snapshot.py"
        spec = importlib.util.spec_from_file_location("_gen_ts", gen)
        if spec is None or spec.loader is None:
            return False
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        regenerated = mod.build_snapshot()
        current = json.loads((repo / _TRACK_SNAPSHOT).read_text(encoding="utf-8"))
    except Exception:
        return False
    volatile = {"generated_at", "as_of_generated", "_generated"}
    a = {k: v for k, v in regenerated.items() if k not in volatile}
    b = {k: v for k, v in current.items() if k not in volatile}
    return a == b


# ── free-text scan ──────────────────────────────────────────────────────────
def _v(file: str, line: int, klass: str, rule: str, matched: str,
       change: str = "") -> dict[str, Any]:
    return {"file": file, "line": line, "klass": klass, "rule": rule,
            "change": change, "matched_text": matched[:200]}


def _scan_free_text(
    path: str, hunk_lines: list[tuple[str, int, str]]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    is_legal_path = path in _LEGAL_PATHS
    for sign, line, text in hunk_lines:
        # Class D — path-based: any change to a legal file gates.
        if is_legal_path:
            out.append(_v(path, line, "D", "legal.path",
                          text.strip(), "added" if sign == "+" else "removed"))
            continue
        if sign == "+":
            if _RE_SOLICIT.search(text):
                out.append(_v(path, line, "A", "solicitation", text.strip(), "added"))
            for m in _RE_YIELD_NUMBER.finditer(text):
                window = text[max(0, m.start() - _DYNAMIC_WINDOW): m.end() + _DYNAMIC_WINDOW]
                if not _RE_DYNAMIC.search(window):
                    out.append(_v(path, line, "B", "yield.number.literal", text.strip(), "added"))
                    break
            m = _RE_SPA_EXPANSION.search(text)
            if m and " ".join(g for g in m.groups() if g).lower() != _CANON_SPA_EXPANSION:
                out.append(_v(path, line, "C", "spa.expansion", text.strip(), "added"))
        elif sign == "-":
            # Class E — removing a specific honesty/evidence token.
            if _RE_EVIDENCE_TOKEN.search(text):
                out.append(_v(path, line, "E", "honesty.token.removed", text.strip(), "removed"))
    return out


# ── owner-approval bypass ───────────────────────────────────────────────────
def _approved_scope(commit_message: str | None, repo: Path) -> dict[str, Any] | None:
    """If the commit message carries a valid `Owner-Approved: own-NN` trailer whose
    card is owner-done, return {card, approves:[...]}; else None. Never self-approvable
    by the orchestrator (owner-done is owner-only, enforced in spa_core.owner_queue)."""
    if not commit_message:
        return None
    m = re.search(r"Owner-Approved:\s*((?:own|Q-OWN)-\S+)", commit_message, re.IGNORECASE)
    if not m:
        return None
    card_id = m.group(1).strip()
    try:
        from spa_core.owner_queue.queue import load_card, list_cards  # type: ignore
    except Exception:
        return None
    card = None
    try:
        for c in list_cards(card_type="owner-decision"):
            cid = str(getattr(c, "id", "") or getattr(c, "name", ""))
            if card_id.lower() in cid.lower() or cid.lower() in card_id.lower():
                card = c
                break
    except Exception:
        card = None
    if card is None:
        return None
    status = str(getattr(card, "status", "") or "").lower()
    if status != "owner-done":
        return None
    fm = getattr(card, "frontmatter", {}) or {}
    return {"card": card_id, "approves": fm.get("approves", [])}


# ── main check ──────────────────────────────────────────────────────────────
def check_owner_gate(
    diff_mode: str = "worktree",
    base: str | None = None,
    head: str | None = None,
    files: Iterable[str] | None = None,
    commit_message: str | None = None,
    repo_root: str | os.PathLike | None = None,
) -> dict[str, Any]:
    repo = Path(repo_root) if repo_root is not None else _REPO_ROOT
    flist = [str(f) for f in files] if files else None

    diff_text, old_ref = _acquire(diff_mode, base, head, flist, repo)
    paths, hunks = _changed_paths_and_hunks(diff_text)
    site_paths = [p for p in paths if p.startswith(_SITE_PREFIX)]

    violations: list[dict[str, Any]] = []

    # Structured JSON field-diff.
    if _TIER_BANDS in site_paths:
        old = _json_at(old_ref, _TIER_BANDS, repo)
        new = _json_at("WORKTREE", _TIER_BANDS, repo) if diff_mode != "git-range" \
            else _json_at(head or "HEAD", _TIER_BANDS, repo)
        if new is None:
            try:
                new = json.loads((repo / _TIER_BANDS).read_text(encoding="utf-8"))
            except Exception:
                new = None
        violations.extend(_tier_bands_violations(old, new))

    if _TRACK_SNAPSHOT in site_paths:
        exempt = _snapshot_is_custodian_equivalent(repo) if diff_mode != "git-range" else False
        old = _json_at(old_ref, _TRACK_SNAPSHOT, repo)
        try:
            new = json.loads((repo / _TRACK_SNAPSHOT).read_text(encoding="utf-8"))
        except Exception:
            new = _json_at(head or "HEAD", _TRACK_SNAPSHOT, repo)
        violations.extend(_track_snapshot_violations(old, new, exempt))

    # Free-text scan (skip the two structured files — handled above).
    for p in site_paths:
        if p in (_TIER_BANDS, _TRACK_SNAPSHOT):
            continue
        violations.extend(_scan_free_text(p, hunks.get(p, [])))

    # Owner-approval bypass — drop violations covered by an owner-done card scope.
    approval = _approved_scope(commit_message, repo)
    bypassed: list[dict[str, Any]] = []
    if approval and approval.get("approves"):
        scope = approval["approves"]
        scope_files = {s for s in scope if "/" in str(s)}
        scope_klass = {str(s).upper() for s in scope if len(str(s)) == 1}
        kept = []
        for v in violations:
            if v["file"] in scope_files or v["klass"] in scope_klass:
                v = {**v, "bypassed_by": approval["card"]}
                bypassed.append(v)
            else:
                kept.append(v)
        violations = kept

    violations.sort(key=lambda d: (d["file"], d["line"], d["klass"]))
    return {
        "model": "owner_gate_check",
        "llm_forbidden": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "diff_mode": diff_mode,
        "ok": len(violations) == 0,
        "gated_count": len(violations),
        "site_paths": sorted(site_paths),
        "violations": violations,
        "approved_bypasses": bypassed,
        "approval": approval,
    }


def _write_report(report: dict[str, Any], repo: Path) -> Path:
    dst = repo / "data" / "owner_gate_check.json"
    try:
        from spa_core.utils.atomic import atomic_save

        atomic_save(report, str(dst))
        return dst
    except Exception:
        import tempfile
        import shutil

        dst.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(dst.parent), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)
        shutil.move(tmp, str(dst))
        return dst


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Owner-gate guard (auto-ship safety).")
    ap.add_argument("--diff-mode", choices=("git-range", "files", "worktree"),
                    default="worktree")
    ap.add_argument("--base")
    ap.add_argument("--head")
    ap.add_argument("--files", nargs="*")
    ap.add_argument("--commit-message", default=None)
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args(argv)

    try:
        report = check_owner_gate(
            diff_mode=args.diff_mode, base=args.base, head=args.head,
            files=args.files, commit_message=args.commit_message,
        )
    except Exception as exc:  # tool/IO error
        print(f"owner-gate: ERROR {exc}", file=sys.stderr)
        return 1

    print("=== Owner-gate guard (auto-ship safety) ===")
    print(f"  diff-mode: {report['diff_mode']} · site paths: {len(report['site_paths'])}")
    for v in report["violations"]:
        print(f"    [{v['klass']}] {v['file']}:{v['line']} {v['rule']} "
              f"({v['change']}) — {v['matched_text']}")
    if report["approved_bypasses"]:
        print(f"  owner-approved bypasses: {len(report['approved_bypasses'])} "
              f"(card {report['approval']['card']})")

    if args.report:
        dst = _write_report(report, _REPO_ROOT)
        print(f"  report → {dst}")

    if report["ok"]:
        print("  RESULT: CLEAN — no owner-gated changes; safe to auto-ship.")
        return 0
    print(f"  RESULT: GATED — {report['gated_count']} owner-gated change(s) → route to owner card.")
    return 2


if __name__ == "__main__":
    raise SystemExit(_main())
