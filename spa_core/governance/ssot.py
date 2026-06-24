#!/usr/bin/env python3
# LLM_FORBIDDEN
"""SPA Single Source of Truth (SSOT) MANIFEST + presentation validator.

ARCHITECTURE_TIER1.md Law 3 (Plane 1.5/1.6):
    Each data TYPE has exactly ONE canonical source. The presentation layer
    (site / Telegram bot / dashboards) must MIRROR the SSOT — never invent or
    cache a divergent value. The stale GoLive-dates / APY bug on the site was a
    Law-3 violation: presentation showed numbers that were not in canon.

This module is a PARALLEL governance layer:
    * Pure stdlib, deterministic, no LLM calls (# LLM_FORBIDDEN).
    * Reads existing canonical files; writes only data/ssot_manifest.json (atomic).
    * Touches no existing module (no edits) — additive guard only.

Public API
----------
    registry()                      -> {data_type: {canonical, kind}}
    canonical_source(data_type)     -> path/str of the canonical source
    read_canonical(data_type)       -> dict loaded from the canonical file
    key_facts()                     -> canonical headline facts (mirror verbatim)
    validate_presentation(claims)   -> {ok, divergences:[...]} structural guard
    build_report(write=True)        -> data/ssot_manifest.json (registry+key_facts)

The contract enforced by validate_presentation():
    "The site cannot show a number that isn't in canon."
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Reuse the centralized atomic writer (stdlib-backed tmp+os.replace).
from spa_core.utils.atomic import atomic_save

# ─── Version pin ────────────────────────────────────────────────────────────────
# Bump when the registry mapping changes (Law-3 structural change → new ADR).
SSOT_VERSION = "v1.0"

# Repo root = two levels up from this file (spa_core/governance/ssot.py).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DATA_DIR = _REPO_ROOT / "data"

# GitHub repo identity — canonical home of code / configs / risk-limits.
GITHUB_REPO = "yurii-spa/SPA"

# Divergence tolerances for numeric presentation claims.
# Counts (track_days, golive passed/total) must match exactly → tol 0.
# Money/percent fields get a small absolute slack to absorb rounding.
_TOL_ABS_USD = 1.0          # NAV / equity dollars
_TOL_ABS_PCT = 0.05         # APY / return percent points
_TOL_COUNT = 0              # day-counts, criterion counts → exact


# ─── Registry: data TYPE → canonical source (Law 3) ─────────────────────────────
# kind:
#   "github" → source of truth lives in the git repo (code/config/limits)
#   "file"   → a single canonical data/ JSON file
#   "files"  → an ordered list of files that jointly form the canon for a type
_REGISTRY: dict[str, dict[str, Any]] = {
    # ── repo-canonical (versioned in GitHub) ──
    "code": {"canonical": GITHUB_REPO, "kind": "github"},
    "strategy-configs": {"canonical": GITHUB_REPO, "kind": "github"},
    "risk-limits": {"canonical": GITHUB_REPO, "kind": "github"},
    # ── data-canonical (single JSON files) ──
    "portfolio-state": {
        "canonical": ["current_positions.json", "paper_trading_status.json"],
        "kind": "files",
    },
    "positions": {"canonical": "current_positions.json", "kind": "file"},
    "equity": {"canonical": "equity_curve_daily.json", "kind": "file"},
    "track": {"canonical": "paper_trading_status.json", "kind": "file"},
    "golive-criteria": {"canonical": "golive_status.json", "kind": "file"},
    "backtest-results": {
        "canonical": ["tier1_verdict.json", "mass_tournament_results.json"],
        "kind": "files",
    },
    "packages": {"canonical": "tier1_packages.json", "kind": "file"},
    "agent-health": {"canonical": "agent_health.json", "kind": "file"},
    "nav": {"canonical": "tier1_nav_proof.json", "kind": "file"},
}


# ─── IO helpers ─────────────────────────────────────────────────────────────────


def _read_json(path: Path, default: Any = None) -> Any:
    """Read JSON defensively; never raises (returns *default* on any error)."""
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return default


def _data_dir(data_dir: str | os.PathLike | None = None) -> Path:
    return Path(data_dir) if data_dir is not None else _DATA_DIR


# ─── Public: registry accessors ─────────────────────────────────────────────────


def registry() -> dict[str, dict[str, Any]]:
    """Return a deep copy of the SSOT registry {data_type: {canonical, kind}}."""
    out: dict[str, dict[str, Any]] = {}
    for dtype, spec in _REGISTRY.items():
        canon = spec["canonical"]
        canon_copy = list(canon) if isinstance(canon, list) else canon
        out[dtype] = {"canonical": canon_copy, "kind": spec["kind"]}
    return out


def canonical_source(data_type: str) -> Any:
    """Return the canonical source for *data_type*.

    - github kinds → the repo identity string (e.g. "yurii-spa/SPA").
    - file kinds   → the canonical filename (e.g. "golive_status.json").
    - files kinds  → list of canonical filenames.

    Raises KeyError for an unregistered data_type (fail loud — never guess).
    """
    if data_type not in _REGISTRY:
        raise KeyError(
            f"unregistered data_type {data_type!r}; "
            f"known: {sorted(_REGISTRY)}"
        )
    canon = _REGISTRY[data_type]["canonical"]
    return list(canon) if isinstance(canon, list) else canon


def read_canonical(
    data_type: str, data_dir: str | os.PathLike | None = None
) -> dict[str, Any]:
    """Load the canonical file(s) for *data_type*.

    For "file" kind → returns the file's dict (or {} if absent/invalid).
    For "files" kind → returns {filename: dict, ...} for each component.
    For "github" kind → returns {"canonical": repo, "kind": "github"} (no file).

    Never raises on missing files (graceful empty).
    """
    if data_type not in _REGISTRY:
        raise KeyError(f"unregistered data_type {data_type!r}")
    spec = _REGISTRY[data_type]
    kind = spec["kind"]
    ddir = _data_dir(data_dir)

    if kind == "github":
        return {"canonical": spec["canonical"], "kind": "github"}
    if kind == "file":
        doc = _read_json(ddir / spec["canonical"], {})
        return doc if isinstance(doc, dict) else {}
    if kind == "files":
        out: dict[str, Any] = {}
        for fname in spec["canonical"]:
            doc = _read_json(ddir / fname, {})
            out[fname] = doc if isinstance(doc, dict) else {}
        return out
    return {}


# ─── Public: key_facts (the numbers the site SHOULD show, verbatim) ─────────────


def key_facts(data_dir: str | os.PathLike | None = None) -> dict[str, Any]:
    """Return canonical headline facts read straight from SSOT.

    The presentation layer consumes this VERBATIM so it mirrors canon
    rather than inventing values. Missing files degrade gracefully to None.
    """
    ddir = _data_dir(data_dir)

    track = _read_json(ddir / "paper_trading_status.json", {}) or {}
    golive = _read_json(ddir / "golive_status.json", {}) or {}
    nav = _read_json(ddir / "tier1_nav_proof.json", {}) or {}

    if not isinstance(track, dict):
        track = {}
    if not isinstance(golive, dict):
        golive = {}
    if not isinstance(nav, dict):
        nav = {}

    return {
        "ssot_version": SSOT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "track_days": track.get("days_running"),
        "paper_start_date": track.get("paper_start_date"),
        "current_equity": track.get("current_equity"),
        "total_return_pct": track.get("total_return_pct"),
        "apy_today_pct": track.get("apy_today_pct"),
        "daily_yield_usd": track.get("daily_yield_usd"),
        "regime": track.get("market_regime"),
        "golive_passed": golive.get("passed"),
        "golive_total": golive.get("total"),
        "golive_ready": golive.get("ready"),
        "nav": nav.get("computed_nav_usd"),
        "nav_reconciliation_ok": nav.get("reconciliation_ok"),
    }


# ─── Public: presentation validator (the structural Law-3 guard) ────────────────

# Map presentation-claim field → (canonical key in key_facts, tolerance).
# Only fields listed here are checked; unknown claim keys are reported as
# "unverifiable" (no canonical mapping) rather than silently ignored.
_CLAIM_MAP: dict[str, tuple[str, float]] = {
    "track_days": ("track_days", _TOL_COUNT),
    "days_running": ("track_days", _TOL_COUNT),
    "current_equity": ("current_equity", _TOL_ABS_USD),
    "equity": ("current_equity", _TOL_ABS_USD),
    "apy_pct": ("apy_today_pct", _TOL_ABS_PCT),
    "apy_today_pct": ("apy_today_pct", _TOL_ABS_PCT),
    "total_return_pct": ("total_return_pct", _TOL_ABS_PCT),
    "golive_passed": ("golive_passed", _TOL_COUNT),
    "golive_total": ("golive_total", _TOL_COUNT),
    "nav": ("nav", _TOL_ABS_USD),
    "regime": ("regime", 0.0),  # string field → exact match
}


def _diverges(claimed: Any, canonical: Any, tol: float) -> bool:
    """True if *claimed* diverges from *canonical* beyond *tol*.

    Numeric → abs diff > tol. Non-numeric (str/bool) → strict inequality.
    A None canonical (file absent) means we cannot confirm → treat as divergence
    only if the claim is non-None (presentation asserting an unbacked value).
    """
    if canonical is None:
        return claimed is not None
    # Try numeric comparison first.
    try:
        return abs(float(claimed) - float(canonical)) > tol
    except (TypeError, ValueError):
        return claimed != canonical


def validate_presentation(
    claims: dict[str, Any], data_dir: str | os.PathLike | None = None
) -> dict[str, Any]:
    """Compare presentation *claims* against canonical key_facts.

    Returns {"ok": bool, "divergences": [{field, claimed, canonical}], ...}.
    A claim that diverges beyond tolerance → recorded in divergences and ok=False.
    Claim keys with no canonical mapping → recorded as unverifiable (ok unaffected
    but surfaced so the caller knows the field is outside canon).

    This is the structural guard enforcing Law 3: the site can't show a number
    that isn't in canon.
    """
    facts = key_facts(data_dir=data_dir)
    divergences: list[dict[str, Any]] = []
    unverifiable: list[str] = []

    for field, claimed in (claims or {}).items():
        if field not in _CLAIM_MAP:
            unverifiable.append(field)
            continue
        canon_key, tol = _CLAIM_MAP[field]
        canonical = facts.get(canon_key)
        if _diverges(claimed, canonical, tol):
            divergences.append(
                {"field": field, "claimed": claimed, "canonical": canonical}
            )

    return {
        "ok": len(divergences) == 0,
        "divergences": divergences,
        "unverifiable": unverifiable,
        "checked": [f for f in (claims or {}) if f in _CLAIM_MAP],
        "ssot_version": SSOT_VERSION,
    }


# ─── Public: manifest report ────────────────────────────────────────────────────


def build_report(
    write: bool = True, data_dir: str | os.PathLike | None = None
) -> dict[str, Any]:
    """Build the SSOT manifest (registry + key_facts) → data/ssot_manifest.json.

    Atomic write via atomic_save (tmp+os.replace). Returns the manifest dict.
    """
    manifest = {
        "model": "ssot_manifest",
        "ssot_version": SSOT_VERSION,
        "llm_forbidden": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "github_repo": GITHUB_REPO,
        "registry": registry(),
        "key_facts": key_facts(data_dir=data_dir),
    }
    if write:
        ddir = _data_dir(data_dir)
        atomic_save(manifest, str(ddir / "ssot_manifest.json"))
    return manifest


# ─── __main__ ───────────────────────────────────────────────────────────────────


def _main() -> None:
    # Persist the manifest (registry + key_facts) → data/ssot_manifest.json (atomic).
    manifest = build_report(write=True)
    facts = manifest["key_facts"]
    print("=== SPA SSOT key_facts (canonical — site MUST mirror) ===")
    for k, v in facts.items():
        print(f"  {k:24} = {v}")
    print()
    print("=== SSOT registry (data_type → canonical source · Law 3) ===")
    for dtype, spec in registry().items():
        print(f"  {dtype:20} [{spec['kind']:6}] -> {spec['canonical']}")
    print()
    print("wrote: data/ssot_manifest.json")


if __name__ == "__main__":
    _main()
