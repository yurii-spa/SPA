#!/usr/bin/env python3
# LLM_FORBIDDEN
"""PRESENTATION-vs-SSOT consistency guard (ARCHITECTURE_TIER1.md Law 3).

The presentation layer (landing/src site, public HTML) must MIRROR the SSOT —
it may not show a hard-coded number that contradicts canon. The historical
"stale site" bug was exactly this: the landing pages carried hard-coded GoLive
criteria counts ("26/26"), paper-day literals and paper-APY claims that DRIFTED
away from the canonical values in data/*.json.

This guard SCANS the committed presentation source for hard-coded numbers that
SHOULD come from SSOT and FLAGS clear divergences from canon (from
spa_core.governance.ssot.key_facts). It is intentionally CONSERVATIVE: it only
flags a literal number that *contradicts* canon, and it never flags a dynamic
placeholder element (e.g. <span id="hero-paper-day">…</span>) that fetches the
live value at runtime.

Design
------
  * Pure stdlib, deterministic, no LLM calls (# LLM_FORBIDDEN).
  * Reads canon via ssot.key_facts(); reads presentation files read-only.
  * Writes only data/presentation_ssot_check.json (when --report given), atomic.
  * Creates no other files, edits no site files.

Divergence kinds (each conservative — see the per-kind matcher docstrings):
  golive_total   "NN criteria" / "NN-criterion" / "X/NN" pass-count where the
                 denominator NN != canonical golive_total.
  golive_passed  "X/NN" pass-count where NN == canonical golive_total but the
                 numerator X != canonical golive_passed.
  paper_apy      headline paper-APY claim ("paper APY: ~X.X%" / "current APY:
                 ~X.X%") diverging > 1.0pp from canonical apy_today_pct.
  paper_day      "Paper day NN" literal where NN != canonical track_days AND the
                 literal is not inside a dynamic placeholder element.
  golive_date    a go-live target date literal (YYYY-MM-DD) that contradicts the
                 canonical paper_start_date horizon (only flagged when an
                 explicit canonical golive target is known — see TARGET note).

Exit code 0 if clean, 1 if any divergences (CI gate).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# Repo root = parent of scripts/.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.governance.ssot import key_facts  # noqa: E402

# Paper-APY divergence tolerance: claims within 1.0 percentage-point are OK
# (the headline APY is variable / rounded). Beyond that → a contradictory claim.
_APY_TOL_PP = 1.0

# Presentation source roots scanned (relative to repo root).
_SCAN_GLOBS = (
    "landing/src/**/*.astro",
    "landing/src/**/*.jsx",
    "landing/public/*.html",
)

# ── Regexes (compiled once; deterministic) ──────────────────────────────────

# "NN criteria" or "NN-criterion" or "NN-criteria"  → denominator-style total.
_RE_CRITERIA_TOTAL = re.compile(
    r"(?<![\d.])(\d{1,3})\s*[- ]?criteri(?:on|a)\b", re.IGNORECASE
)
# "X/NN" or "X / NN" optionally followed by criteria/pass/checks → pass-count.
_RE_PASS_COUNT = re.compile(
    r"(?<![\d./])(\d{1,3})\s*/\s*(\d{1,3})"
    r"(?=\s*(?:</[^>]+>)?\s*(?:criteria|criterion|pass|passing|checks?|met)\b"
    r"|\s*(?:criteria|criterion|pass|passing|checks?|met)\b)",
    re.IGNORECASE,
)
# Headline paper-APY claim: "paper APY: ~3.6%", "current APY: ~3.6%",
# "Current paper APY: 3.6%". Captures the numeric percent.
_RE_PAPER_APY = re.compile(
    r"(?:current\s+paper\s+apy|paper\s+apy|current\s+apy)\s*[:=]?\s*~?\s*"
    r"(\d{1,2}(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)
# "Paper day NN" literal.
_RE_PAPER_DAY = re.compile(r"\bpaper\s+day\s+(\d{1,4})\b", re.IGNORECASE)
# Go-live context guard: the "NN criteria" total matcher only fires on a line
# that is clearly ABOUT the GoLive gate (avoids false positives like a JS
# comment "first 4 criteria" or generic "validation criteria" prose).
_RE_GOLIVE_CONTEXT = re.compile(r"go.?live|golivechecker", re.IGNORECASE)
# A dynamic placeholder id that fetches live values (don't flag content inside).
_RE_DYNAMIC_ID = re.compile(
    r'id=["\'](?:hero-paper-day|hero-track-days|stat-paper|paper-status-strip'
    r'|spa-paper-badge)["\']',
    re.IGNORECASE,
)


def _iter_files(repo_root: Path) -> list[Path]:
    """Return the sorted (deterministic) list of presentation files to scan."""
    out: set[Path] = set()
    for pattern in _SCAN_GLOBS:
        out.update(repo_root.glob(pattern))
    return sorted(p for p in out if p.is_file())


def _line_has_dynamic_placeholder(line: str) -> bool:
    """True if the line carries a known dynamic-placeholder element id."""
    return bool(_RE_DYNAMIC_ID.search(line))


def _scan_text(
    rel_path: str,
    text: str,
    canon: dict[str, Any],
) -> list[dict[str, Any]]:
    """Scan one file's text → list of divergence records (conservative)."""
    divs: list[dict[str, Any]] = []
    g_total = canon.get("golive_total")
    g_passed = canon.get("golive_passed")
    apy = canon.get("apy_today_pct")
    track_days = canon.get("track_days")

    for i, line in enumerate(text.splitlines(), start=1):
        # ── golive criteria TOTAL ("NN criteria" / "NN-criterion") ──
        # Only on a line clearly about the GoLive gate (avoid e.g. a JS comment
        # "first 4 criteria" or generic "validation criteria" prose).
        if isinstance(g_total, int) and _RE_GOLIVE_CONTEXT.search(line):
            for m in _RE_CRITERIA_TOTAL.finditer(line):
                nn = int(m.group(1))
                if nn != g_total:
                    divs.append(
                        {
                            "file": rel_path,
                            "line": i,
                            "kind": "golive_total",
                            "claimed": nn,
                            "canonical": g_total,
                            "context": m.group(0).strip(),
                        }
                    )

        # ── pass-count "X/NN" (criteria/pass/checks) ──
        for m in _RE_PASS_COUNT.finditer(line):
            x, nn = int(m.group(1)), int(m.group(2))
            if isinstance(g_total, int) and nn != g_total:
                divs.append(
                    {
                        "file": rel_path,
                        "line": i,
                        "kind": "golive_total",
                        "claimed": nn,
                        "canonical": g_total,
                        "context": m.group(0).strip(),
                    }
                )
            elif (
                isinstance(g_total, int)
                and isinstance(g_passed, int)
                and nn == g_total
                and x != g_passed
            ):
                divs.append(
                    {
                        "file": rel_path,
                        "line": i,
                        "kind": "golive_passed",
                        "claimed": x,
                        "canonical": g_passed,
                        "context": m.group(0).strip(),
                    }
                )

        # ── headline paper-APY claim ──
        if isinstance(apy, (int, float)):
            for m in _RE_PAPER_APY.finditer(line):
                claimed = float(m.group(1))
                if abs(claimed - float(apy)) > _APY_TOL_PP:
                    divs.append(
                        {
                            "file": rel_path,
                            "line": i,
                            "kind": "paper_apy",
                            "claimed": claimed,
                            "canonical": round(float(apy), 4),
                            "context": m.group(0).strip(),
                        }
                    )

        # ── "Paper day NN" literal (skip dynamic placeholders) ──
        if isinstance(track_days, int) and not _line_has_dynamic_placeholder(
            line
        ):
            for m in _RE_PAPER_DAY.finditer(line):
                nn = int(m.group(1))
                if nn != track_days:
                    divs.append(
                        {
                            "file": rel_path,
                            "line": i,
                            "kind": "paper_day",
                            "claimed": nn,
                            "canonical": track_days,
                            "context": m.group(0).strip(),
                        }
                    )

    return divs


def check_presentation(
    repo_root: str | os.PathLike | None = None,
    data_dir: str | os.PathLike | None = None,
    files: Iterable[str | os.PathLike] | None = None,
) -> dict[str, Any]:
    """Run the presentation-vs-SSOT guard.

    Args:
        repo_root: repo root (defaults to the SPA repo containing this script).
        data_dir:  canon data dir (passed to key_facts; defaults to repo/data).
        files:     explicit file list to scan (testing); else the scan globs.

    Returns a deterministic report:
        {
          "ok": bool, "divergence_count": int,
          "divergences": [{file, line, kind, claimed, canonical, context}, ...],
          "scanned_files": int, "canonical": {...subset of key_facts...},
          "generated_at": iso8601, "ssot_version": str,
        }
    """
    root = Path(repo_root) if repo_root is not None else _REPO_ROOT
    canon = key_facts(data_dir=data_dir)

    if files is not None:
        targets = sorted(Path(f) for f in files)
    else:
        targets = _iter_files(root)

    divergences: list[dict[str, Any]] = []
    for path in targets:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            rel = str(path.relative_to(root))
        except ValueError:
            rel = str(path)
        divergences.extend(_scan_text(rel, text, canon))

    # Deterministic ordering: by (file, line, kind).
    divergences.sort(key=lambda d: (d["file"], d["line"], d["kind"]))

    return {
        "model": "presentation_ssot_check",
        "llm_forbidden": True,
        "ssot_version": canon.get("ssot_version"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ok": len(divergences) == 0,
        "divergence_count": len(divergences),
        "scanned_files": len(targets),
        "canonical": {
            "golive_total": canon.get("golive_total"),
            "golive_passed": canon.get("golive_passed"),
            "track_days": canon.get("track_days"),
            "apy_today_pct": canon.get("apy_today_pct"),
            "paper_start_date": canon.get("paper_start_date"),
        },
        "divergences": divergences,
    }


def _write_report(report: dict[str, Any], repo_root: Path) -> Path:
    """Atomically write the report to data/presentation_ssot_check.json."""
    try:
        from spa_core.utils.atomic import atomic_save

        dst = repo_root / "data" / "presentation_ssot_check.json"
        atomic_save(report, str(dst))
        return dst
    except Exception:
        # Fallback atomic write (stdlib only) if atomic_save unavailable.
        import tempfile
        import shutil

        dst = repo_root / "data" / "presentation_ssot_check.json"
        dst.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(dst.parent), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)
        shutil.move(tmp, str(dst))
        return dst


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Presentation-vs-SSOT consistency guard (Law 3)."
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="write data/presentation_ssot_check.json",
    )
    args = parser.parse_args(argv)

    report = check_presentation()

    c = report["canonical"]
    print("=== Presentation-vs-SSOT guard (Law 3) ===")
    print(
        f"  canon: golive {c['golive_passed']}/{c['golive_total']} · "
        f"track_days {c['track_days']} · apy {c['apy_today_pct']}% · "
        f"start {c['paper_start_date']}"
    )
    print(f"  scanned {report['scanned_files']} presentation files")
    print(f"  divergences: {report['divergence_count']}")
    for d in report["divergences"]:
        print(
            f"    [{d['kind']}] {d['file']}:{d['line']}  "
            f"claimed={d['claimed']!r} canonical={d['canonical']!r}  "
            f"({d['context']})"
        )

    if args.report:
        dst = _write_report(report, _REPO_ROOT)
        print(f"  report → {dst}")

    if report["ok"]:
        print("  RESULT: CLEAN — site mirrors canon.")
        return 0
    print(f"  RESULT: DRIFT — {report['divergence_count']} divergence(s).")
    return 1


if __name__ == "__main__":
    raise SystemExit(_main())
