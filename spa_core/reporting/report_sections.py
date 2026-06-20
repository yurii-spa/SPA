"""
spa_core/reporting/report_sections.py

Reusable, stdlib-only report section builders for investor and internal reports.

Each builder returns a plain dict (JSON-serialisable) so it can be embedded
into PDF reports, Telegram messages, or the investor portal without further
coupling to any specific output format.

MP-1478 (v10.94) — stdlib only, no external deps, offline-safe.

Usage::

    from spa_core.reporting.report_sections import (
        golive_section,
        evidence_section,
        tournament_section,
        security_audit_section,
    )

    sections = [
        golive_section(score=62, categories={"gate_status": 8, "evidence_points": 12}),
        evidence_section(days=10, target=30, score=12.5),
        tournament_section(),
        security_audit_section(),
    ]
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Repository root (for reading data/*.json)
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read_json(rel_path: str, default: Any = None) -> Any:
    """Load a JSON file relative to repo root; return *default* on any error."""
    full = os.path.join(_REPO_ROOT, rel_path)
    try:
        with open(full, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        logger.debug("Could not load %s: %s", full, exc)
        return default


# ---------------------------------------------------------------------------
# Static strategy catalogue (S0–S12)
# Used when tournament_results.json is absent.
# ---------------------------------------------------------------------------

_STRATEGY_CATALOGUE: List[Dict[str, Any]] = [
    {"id": "S0", "name": "Cash",                  "apy_est": 0.0,  "tier": "T1",  "status": "active"},
    {"id": "S1", "name": "T1+T2 Balanced",         "apy_est": 6.5,  "tier": "T1",  "status": "active"},
    {"id": "S2", "name": "T1 Only",                "apy_est": 5.0,  "tier": "T1",  "status": "active"},
    {"id": "S3", "name": "T2 Max Yield",            "apy_est": 8.5,  "tier": "T2",  "status": "active"},
    {"id": "S4", "name": "Morpho Heavy",            "apy_est": 7.2,  "tier": "T1",  "status": "active"},
    {"id": "S5", "name": "Compound Focus",          "apy_est": 4.8,  "tier": "T1",  "status": "active"},
    {"id": "S6", "name": "Euler Mix",               "apy_est": 7.8,  "tier": "T2",  "status": "active"},
    {"id": "S7", "name": "Yearn V3 Max",            "apy_est": 9.0,  "tier": "T2",  "status": "active"},
    {"id": "S8", "name": "Delta-Neutral sUSDe",     "apy_est": 27.5, "tier": "T3",  "status": "advisory"},
    {"id": "S9", "name": "E-Mode Looping",          "apy_est": 5.84, "tier": "T1",  "status": "active"},
    {"id": "S10","name": "Pendle YT",               "apy_est": 14.0, "tier": "T3-SPEC", "status": "advisory"},
    {"id": "S11","name": "Hybrid Yield Max",        "apy_est": 11.2, "tier": "T2",  "status": "research"},
    {"id": "S12","name": "Base Layer Yield",        "apy_est": 8.9,  "tier": "T2",  "status": "research"},
]


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def golive_section(
    score: Optional[int] = None,
    categories: Optional[Dict[str, Any]] = None,
    data_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a Go-Live Readiness section dict.

    Parameters
    ----------
    score:
        Overall score 0–100.  If ``None``, read from ``data/golive_status.json``.
    categories:
        Per-category breakdown dict.  If ``None``, derived from golive_status.json.
    data_dir:
        Override directory for data/*.json lookup (useful in tests).

    Returns
    -------
    dict with keys: ``title``, ``score``, ``status``, ``passed``, ``total``,
    ``breakdown``, ``blockers``, ``generated_at``.
    """
    golive: Dict[str, Any] = {}
    if data_dir:
        golive = _read_json_from(data_dir, "golive_status.json") or {}
    else:
        golive = _read_json("data/golive_status.json") or {}

    passed = golive.get("passed", 0)
    total = golive.get("total", 26)

    if score is None:
        # Derive percentage from passed/total
        score = int(round(passed / max(total, 1) * 100))

    status: str
    if score >= 80:
        status = "ON_TRACK"
    elif score >= 50:
        status = "NEEDS_ATTENTION"
    else:
        status = "BLOCKED"

    if categories is None:
        raw_checks = golive.get("checks", {})
        if isinstance(raw_checks, dict):
            categories = {k: int(bool(v)) for k, v in raw_checks.items()}
        else:
            categories = {}

    blockers: List[str] = []
    raw_blockers = golive.get("blockers", [])
    if isinstance(raw_blockers, list):
        blockers = [str(b) for b in raw_blockers]

    return {
        "title": "Go-Live Readiness",
        "score": f"{score}/100",
        "score_int": score,
        "status": status,
        "passed": passed,
        "total": total,
        "breakdown": categories,
        "blockers": blockers,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def evidence_section(
    days: Optional[int] = None,
    target: int = 30,
    score: Optional[float] = None,
    eta: Optional[str] = None,
    data_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a Paper Trading Evidence section dict.

    Parameters
    ----------
    days:
        Completed paper-trading days.  If ``None``, read from data files.
    target:
        Target number of days (default 30).
    score:
        Evidence score (0–30 pts).  If ``None``, derived from days/target.
    eta:
        Estimated completion date string.  If ``None``, computed automatically.
    data_dir:
        Override directory for data/*.json lookup.

    Returns
    -------
    dict with keys: ``title``, ``progress``, ``days_done``, ``days_target``,
    ``score``, ``pct_complete``, ``eta``, ``generated_at``.
    """
    # Try to load equity_curve_daily to count real trading days
    eq_curve: List[Dict[str, Any]] = []
    if data_dir:
        eq_curve = _read_json_from(data_dir, "equity_curve_daily.json") or []
    else:
        eq_curve = _read_json("data/equity_curve_daily.json") or []

    if days is None:
        if isinstance(eq_curve, list):
            days = len(eq_curve)
        else:
            days = 0

    pct = round(days / max(target, 1) * 100, 1)

    if score is None:
        score = round(days / max(target, 1) * target, 1)

    if eta is None:
        remaining = max(target - days, 0)
        try:
            today = date.today()
            from datetime import timedelta
            eta_date = today + timedelta(days=remaining)
            eta = eta_date.isoformat()
        except Exception:
            eta = "TBD"

    return {
        "title": "Paper Trading Evidence",
        "progress": f"{days}/{target} days",
        "days_done": days,
        "days_target": target,
        "score": f"{score}/{target} pts",
        "score_float": float(score),
        "pct_complete": pct,
        "eta": eta,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def tournament_section(
    data_dir: Optional[str] = None,
    include_research: bool = True,
) -> Dict[str, Any]:
    """Build a Strategy Tournament results section dict.

    Reads ``data/tournament_results.json`` if available; falls back to the
    static catalogue (``_STRATEGY_CATALOGUE``) so the section always renders.

    Parameters
    ----------
    data_dir:
        Override directory for data/*.json lookup.
    include_research:
        If ``False``, exclude strategies with status == 'research'.

    Returns
    -------
    dict with keys: ``title``, ``total_strategies``, ``active_count``,
    ``advisory_count``, ``top_apy``, ``strategies`` (list of dicts),
    ``generated_at``.
    """
    raw: Optional[Dict[str, Any]] = None
    if data_dir:
        raw = _read_json_from(data_dir, "tournament_results.json")
    else:
        raw = _read_json("data/tournament_results.json")

    strategies: List[Dict[str, Any]]

    if raw and isinstance(raw, dict):
        # Extract per-strategy results from live tournament data
        results = raw.get("results", raw.get("strategies", {}))
        strategies = []
        for sid, info in (results.items() if isinstance(results, dict) else []):
            apy = info.get("apy", info.get("apy_pct", info.get("mean_apy", 0.0)))
            strategies.append({
                "id": sid,
                "name": info.get("name", sid),
                "apy_est": round(float(apy), 2),
                "sharpe": round(float(info.get("sharpe", 0.0)), 3),
                "status": info.get("status", "active"),
                "tier": info.get("tier", "T1"),
            })
    else:
        # Use static catalogue
        strategies = list(_STRATEGY_CATALOGUE)

    if not include_research:
        strategies = [s for s in strategies if s.get("status") != "research"]

    # Sort by APY descending
    strategies_sorted = sorted(strategies, key=lambda s: s.get("apy_est", 0), reverse=True)

    active = [s for s in strategies if s.get("status") == "active"]
    advisory = [s for s in strategies if s.get("status") == "advisory"]
    all_apys = [s.get("apy_est", 0) for s in strategies if s.get("apy_est", 0) > 0]

    return {
        "title": "Strategy Tournament (S0–S12)",
        "total_strategies": len(strategies),
        "active_count": len(active),
        "advisory_count": len(advisory),
        "top_apy": round(max(all_apys), 2) if all_apys else 0.0,
        "avg_active_apy": (
            round(sum(s.get("apy_est", 0) for s in active) / len(active), 2)
            if active else 0.0
        ),
        "strategies": strategies_sorted,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def security_audit_section(
    data_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a Security Audit status section dict.

    Checks:
    - ``data/security_audit_status.json`` (if present)
    - Forbidden import scan of spa_core/risk and spa_core/execution
    - LLM_FORBIDDEN_AGENTS compliance marker
    - Secrets policy marker (no PAT in files)

    Always succeeds (returns a dict); never raises.

    Returns
    -------
    dict with keys: ``title``, ``overall_status``, ``checks`` (list),
    ``last_audit``, ``open_findings``, ``generated_at``.
    """
    # Try loading a pre-computed audit status file
    audit_data: Dict[str, Any] = {}
    if data_dir:
        audit_data = _read_json_from(data_dir, "security_audit_status.json") or {}
    else:
        audit_data = _read_json("data/security_audit_status.json") or {}

    # Run lightweight inline checks
    checks: List[Dict[str, Any]] = []

    # Check 1: forbidden LLM imports in risk/execution
    forbidden_ok, forbidden_detail = _check_forbidden_imports()
    checks.append({
        "name": "LLM forbidden imports (risk/execution)",
        "passed": forbidden_ok,
        "detail": forbidden_detail,
    })

    # Check 2: SECRETS_POLICY — no PAT patterns in .py/.sh files (fast check)
    secrets_ok, secrets_detail = _check_secrets_policy()
    checks.append({
        "name": "Secrets policy (no PAT in source)",
        "passed": secrets_ok,
        "detail": secrets_detail,
    })

    # Check 3: atomic writes — no direct open(...,'w') on state files
    atomic_ok, atomic_detail = _check_atomic_writes()
    checks.append({
        "name": "Atomic write contract",
        "passed": atomic_ok,
        "detail": atomic_detail,
    })

    # Merge with pre-computed data if available
    if audit_data:
        pre_checks = audit_data.get("checks", [])
        if isinstance(pre_checks, list):
            checks = pre_checks + checks

    open_findings = [c for c in checks if not c.get("passed", True)]
    overall = "PASS" if not open_findings else f"ISSUES ({len(open_findings)})"

    last_audit = (
        audit_data.get("last_audit")
        or audit_data.get("timestamp")
        or datetime.now(timezone.utc).isoformat()
    )

    return {
        "title": "Security Audit Status",
        "overall_status": overall,
        "checks": checks,
        "checks_passed": len(checks) - len(open_findings),
        "checks_total": len(checks),
        "last_audit": last_audit,
        "open_findings": [c["name"] for c in open_findings],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def build_full_report(data_dir: Optional[str] = None) -> Dict[str, Any]:
    """Convenience wrapper: assemble all four sections into one report dict."""
    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sections": {
            "golive": golive_section(data_dir=data_dir),
            "evidence": evidence_section(data_dir=data_dir),
            "tournament": tournament_section(data_dir=data_dir),
            "security_audit": security_audit_section(data_dir=data_dir),
        },
    }


# ---------------------------------------------------------------------------
# Internal audit helpers
# ---------------------------------------------------------------------------


def _check_forbidden_imports() -> tuple[bool, str]:
    """Scan spa_core/risk and spa_core/execution for banned LLM imports."""
    forbidden_libs = ["anthropic", "openai", "langchain"]
    violations: List[str] = []
    for domain in ("spa_core/risk", "spa_core/execution"):
        domain_path = os.path.join(_REPO_ROOT, domain)
        if not os.path.isdir(domain_path):
            continue
        for dirpath, _, filenames in os.walk(domain_path):
            for fname in filenames:
                if not fname.endswith(".py"):
                    continue
                fpath = os.path.join(dirpath, fname)
                try:
                    with open(fpath, encoding="utf-8", errors="ignore") as _fh:
                        src = _fh.read()
                    for lib in forbidden_libs:
                        if f"import {lib}" in src or f"from {lib}" in src:
                            violations.append(f"{fpath}: {lib}")
                except OSError:
                    pass
    if violations:
        return False, f"Forbidden imports found: {violations[:3]}"
    return True, "No forbidden LLM imports in risk/execution"


def _check_secrets_policy() -> tuple[bool, str]:
    """Quick scan for GitHub PAT patterns (ghp_) in Python/shell files."""
    import re
    pat_pattern = re.compile(r"ghp_[A-Za-z0-9]{10,}")
    scan_dirs = [os.path.join(_REPO_ROOT, "spa_core"), os.path.join(_REPO_ROOT, "scripts")]
    violations: List[str] = []
    for scan_dir in scan_dirs:
        if not os.path.isdir(scan_dir):
            continue
        for dirpath, _, filenames in os.walk(scan_dir):
            for fname in filenames:
                if not (fname.endswith(".py") or fname.endswith(".sh")):
                    continue
                fpath = os.path.join(dirpath, fname)
                try:
                    with open(fpath, encoding="utf-8", errors="ignore") as _fh:
                        src = _fh.read()
                    if pat_pattern.search(src):
                        violations.append(fpath)
                except OSError:
                    pass
    if violations:
        return False, f"PAT-like string found in {len(violations)} file(s)"
    return True, "No PAT patterns found in source"


def _check_atomic_writes() -> tuple[bool, str]:
    """Heuristic check: data-write code should use atomic_save, not direct open+w."""
    import re
    # Pattern: open(something, 'w') writing to data/ paths — not via tmp
    bad_pattern = re.compile(r"""open\s*\(\s*[^)]*['"]w['"]\s*\)""")
    violations: List[str] = []
    for dirpath, _, filenames in os.walk(os.path.join(_REPO_ROOT, "spa_core")):
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            fpath = os.path.join(dirpath, fname)
            try:
                with open(fpath, encoding="utf-8", errors="ignore") as _fh:
                    src = _fh.read()
                for line in src.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("#"):
                        continue
                    if bad_pattern.search(line) and "data/" in line:
                        violations.append(f"{fpath}: {stripped[:80]}")
            except OSError:
                pass
    if violations:
        return False, f"Non-atomic writes to data/ found ({len(violations)} hits)"
    return True, "Atomic write contract appears sound"


def _read_json_from(directory: str, filename: str) -> Optional[Any]:
    """Load a JSON file from an explicit directory."""
    path = os.path.join(directory, filename)
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None
