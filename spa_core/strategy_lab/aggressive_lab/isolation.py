"""
spa_core/strategy_lab/aggressive_lab/isolation.py — the AIRTIGHT ISOLATION guardrail.

This is the non-negotiable safety core of the Aggressive Lab. The lab runs strategies OUTSIDE the
conservative RiskPolicy refusal gate ON PURPOSE (to measure what the refused strategies WOULD do),
so it MUST be provably unable to touch anything that matters:

  • the go-live $100k evidenced track — equity_curve_daily.json, golive_status.json,
    paper_evidence_history.json, trades.json,
  • the live conservative allocation — current_positions.json (cycle_runner's output),
  • any real capital — there is none here; pure virtual books under data/aggressive_lab/.

THREE LAYERS OF DEFENSE
  1. A PROTECTED-PATH guard (`assert_safe_write_path`): every write this lab makes goes through the
     package's atomic writer, which calls this guard FIRST. A path that resolves to (or escapes into)
     anything other than data/aggressive_lab/ raises IsolationViolation — the lab literally cannot
     write a go-live/live-allocation file, even by a coding mistake or a path-traversal id.
  2. A byte-level WITNESS (`snapshot_protected` / `verify_unchanged`): the red-team + every paper/
     backtest run captures the md5 of every protected file before doing work and asserts it is
     byte-identical after. A drift raises IsolationViolation. This catches an isolation breach the
     instant it happens, not in production.
  3. DOMAIN STAMPING (`stamp`): every artifact carries domain="aggressive_lab", outside_riskpolicy
     =True, is_advisory=True so no downstream consumer (Lane 2 risk/tournament, Lane 3 API/agent)
     can mistake an aggressive-lab number for the conservative live track.

stdlib-only, deterministic, fail-CLOSED. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, Optional

from spa_core.strategy_lab.aggressive_lab import (
    DOMAIN,
    IS_ADVISORY,
    LABEL,
    OUTSIDE_RISKPOLICY,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]  # …/SPA_Claude
DATA_DIR = _REPO_ROOT / "data"
AGGRESSIVE_LAB_DIR = DATA_DIR / "aggressive_lab"

# The go-live track + live-allocation files this lab must NEVER touch. Relative to data/.
PROTECTED_FILES = (
    "equity_curve_daily.json",     # the $100k evidenced equity track
    "golive_status.json",          # the 29-criteria go-live gate
    "paper_evidence_history.json", # the proof-chained evidence
    "trades.json",                 # the live virtual trades
    "current_positions.json",      # the live conservative allocation (cycle_runner output)
)


class IsolationViolation(RuntimeError):
    """Raised the instant the lab would (or did) touch a protected go-live / live-allocation file.
    fail-CLOSED: a violation aborts the operation rather than silently proceeding."""


def protected_paths() -> Dict[str, Path]:
    """{filename: absolute Path} for every protected go-live / live-allocation file."""
    return {name: DATA_DIR / name for name in PROTECTED_FILES}


# ── layer 1: the protected-path write guard ──────────────────────────────────────────────────────
def assert_safe_write_path(path: Path, *, lab_root: Optional[Path] = None) -> Path:
    """Return ``path`` resolved IF it is a safe aggressive-lab write target; else raise
    IsolationViolation. A safe target is strictly inside the lab root (default data/aggressive_lab/;
    tests pass their temp state_dir) AND is never one of the protected go-live/live-allocation files.

    TWO independent refusals, BOTH always active regardless of root:
      • escape refusal — the resolved path must be the lab root or strictly inside it. This defeats
        a path-traversal id (e.g. "../current_positions.json"): the resolved path lands outside the
        root, so it is refused. This is the wall that keeps writes inside the sandbox.
      • protected-name refusal — even a path that LOOKS inside is refused if its basename is one of
        the protected files. Belt-and-braces: a protected filename can never be written, period.

    NOTE: we resolve (symlinks/..) without requiring existence, so a brand-new artifact under the
    root is allowed while an escaping path is still caught."""
    p = Path(path)
    resolved = (p if p.is_absolute() else (Path.cwd() / p)).resolve()
    root = (Path(lab_root) if lab_root is not None else AGGRESSIVE_LAB_DIR).resolve()
    # escape refusal: must be the root itself or strictly inside it
    if resolved != root and root not in resolved.parents:
        raise IsolationViolation(
            f"aggressive_lab refused to write outside its sandbox: {resolved} "
            f"(allowed root: {root})"
        )
    # protected-name refusal: never a go-live / live-allocation filename, even inside the root
    if resolved.name in PROTECTED_FILES:
        raise IsolationViolation(
            f"aggressive_lab refused to write a PROTECTED go-live/live-allocation file: "
            f"{resolved.name}"
        )
    return resolved


# ── layer 2: the byte-level witness (md5 before/after) ─────────────────────────────────────────────
def _md5_of(path: Path) -> Optional[str]:
    """md5 hexdigest of a file, or None if it does not exist (a non-existent protected file is a
    valid state — what matters is that its existence/content does not CHANGE across a lab run)."""
    if not path.is_file():
        return None
    h = hashlib.md5()
    h.update(path.read_bytes())
    return h.hexdigest()


def snapshot_protected() -> Dict[str, Optional[str]]:
    """{filename: md5-or-None} for every protected file — the WITNESS taken before lab work."""
    return {name: _md5_of(p) for name, p in protected_paths().items()}


def verify_unchanged(before: Dict[str, Optional[str]]) -> None:
    """Assert every protected file is byte-identical to its pre-work snapshot. Raise
    IsolationViolation listing any file whose md5 (or existence) drifted. fail-CLOSED."""
    after = snapshot_protected()
    drifted = []
    for name in PROTECTED_FILES:
        if before.get(name) != after.get(name):
            drifted.append(f"{name} (before={before.get(name)} after={after.get(name)})")
    if drifted:
        raise IsolationViolation(
            "ISOLATION BREACH — aggressive_lab altered protected go-live/live-allocation file(s): "
            + "; ".join(drifted)
        )


# ── layer 3: domain stamping ───────────────────────────────────────────────────────────────────────
def stamp(obj: dict) -> dict:
    """Add the OUTSIDE_RISKPOLICY / AGGRESSIVE / ADVISORY domain markers to an artifact dict
    (in place + returned) so no downstream consumer can mistake it for the conservative live track."""
    obj["domain"] = DOMAIN
    obj["outside_riskpolicy"] = OUTSIDE_RISKPOLICY
    obj["is_advisory"] = IS_ADVISORY
    obj["label"] = LABEL
    return obj
