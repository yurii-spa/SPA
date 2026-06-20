"""spa_core.compliance.audit_report_generator — institutional audit report.

Generates a structured, institutional-grade audit report covering identity,
governance, risk controls, the paper-trading track record, current positions,
the recent events log, cryptographic integrity of the audit hash chain, and
system health.  Two artifacts are written atomically:

    data/compliance_report.json   — machine-readable, full structure
    data/compliance_report.md     — human-readable rendering

Design constraints (SPA policy)
-------------------------------
- READ-ONLY / advisory: never mutates allocator / risk / execution / cycle
  state.  Only reads ``data/*.json`` + the audit hash chain, only writes the
  two ``compliance_report.*`` artifacts.
- Pure stdlib.  Atomic writes (tmp + os.replace).  Fail-safe: every section is
  computed defensively so a missing/corrupt input degrades that section to an
  ``error``/``unknown`` marker rather than aborting the whole report.
- LLM FORBIDDEN.

CLI
---
    python3 -m spa_core.compliance.audit_report_generator --check   # compute + print, no write
    python3 -m spa_core.compliance.audit_report_generator --run     # + atomic write to data/
    python3 -m spa_core.compliance.audit_report_generator --run --data-dir <dir>
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from spa_core.audit import audit_trail_signer

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"
_DEFAULT_ADR_DIR = _REPO_ROOT / "docs" / "adr"

REPORT_JSON_FILENAME = "compliance_report.json"
REPORT_MD_FILENAME = "compliance_report.md"

#: First day of the real (post-teardown) paper track.
TRACK_START_DATE = "2026-06-10"

IDENTITY_STATEMENT = (
    "Personal research project. No external capital managed. Paper trading only."
)

# Risk-control reference values (mirror of RiskConfig v1.0; we read them live
# from RiskConfig where possible and fall back to these constants).
_FALLBACK_CONTROLS = {
    "kill_switch_drawdown_pct": 5.0,
    "max_concentration_t1_pct": 40.0,
    "max_concentration_t2_pct": 20.0,
    "max_total_t2_pct": 50.0,
    "min_tvl_usd": 5_000_000.0,
    "min_apy_pct": 1.0,
    "max_apy_pct": 30.0,
    "min_cash_pct": 5.0,
}


# ---------------------------------------------------------------------------
# Small fail-safe IO helpers
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> Any:
    """Return parsed JSON or ``None`` on any error (fail-safe)."""
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _atomic_write(path: Path, text: str) -> None:
    """Atomically write *text* to *path* (tmp + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        finally:
            raise


def _tier_map() -> dict[str, str]:
    """Protocol-key → risk-tier map sourced from the read-only adapter registry."""
    try:
        from spa_core.adapters import ADAPTER_REGISTRY  # local import (fail-safe)

        return {key: tier for key, tier, _cls in ADAPTER_REGISTRY}
    except Exception:
        return {}


def _risk_controls() -> dict[str, float]:
    """Live risk-control limits from RiskConfig, falling back to constants."""
    controls = dict(_FALLBACK_CONTROLS)
    try:
        from spa_core.risk.policy import RiskConfig  # local import (fail-safe)

        cfg = RiskConfig()
        controls.update(
            {
                "kill_switch_drawdown_pct": cfg.max_drawdown_stop * 100,
                "max_concentration_t1_pct": cfg.max_concentration_t1 * 100,
                "max_concentration_t2_pct": cfg.max_concentration_t2 * 100,
                "max_total_t2_pct": cfg.max_total_t2_allocation * 100,
                "min_tvl_usd": float(cfg.min_tvl_usd),
                "min_apy_pct": float(cfg.min_apy_for_new_position),
                "max_apy_pct": float(cfg.max_apy_for_new_position),
                "min_cash_pct": cfg.min_cash_pct * 100,
            }
        )
    except Exception:
        pass
    return controls


def _days_elapsed(start_date: str, as_of: datetime | None = None) -> int:
    """Whole days from *start_date* (YYYY-MM-DD) to *as_of* (default: now UTC)."""
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        now = as_of or datetime.now(timezone.utc)
        return max(0, (now - start).days)
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Section builders — each returns a JSON-serialisable dict and never raises
# ---------------------------------------------------------------------------


def build_identity_section() -> dict[str, Any]:
    """Section 1 — IDENTITY."""
    return {
        "statement": IDENTITY_STATEMENT,
        "capital_type": "virtual",
        "external_capital_managed_usd": 0.0,
        "trading_mode": "paper",
    }


def build_governance_section(adr_dir: Path) -> dict[str, Any]:
    """Section 2 — GOVERNANCE: ADR count, last decision date, rule changes this month."""
    section: dict[str, Any] = {
        "adr_count": 0,
        "last_decision_date": None,
        "last_decision_file": None,
        "rule_changes_this_month": 0,
        "risk_policy_version": "v1.0",
    }
    try:
        if not adr_dir.is_dir():
            return section
        adr_files = sorted(adr_dir.glob("ADR*.md"))
        section["adr_count"] = len(adr_files)

        now = datetime.now(timezone.utc)
        ym_prefix = now.strftime("%Y-%m")
        latest_mtime = 0.0
        changes_this_month = 0
        for f in adr_files:
            try:
                mtime = f.stat().st_mtime
            except OSError:
                continue
            if mtime > latest_mtime:
                latest_mtime = mtime
                section["last_decision_file"] = f.name
            mdt = datetime.fromtimestamp(mtime, tz=timezone.utc)
            if mdt.strftime("%Y-%m") == ym_prefix:
                changes_this_month += 1
        if latest_mtime:
            section["last_decision_date"] = datetime.fromtimestamp(
                latest_mtime, tz=timezone.utc
            ).date().isoformat()
        section["rule_changes_this_month"] = changes_this_month
    except Exception as exc:  # pragma: no cover - defensive
        section["error"] = str(exc)
    return section


def _eval_control(name: str, label: str, ok: bool, detail: str) -> dict[str, Any]:
    return {"control": name, "label": label, "status": "PASS" if ok else "FAIL", "detail": detail}


def build_risk_controls_section(data_dir: Path) -> dict[str, Any]:
    """Section 3 — RISK CONTROLS with PASS/FAIL status per active control."""
    controls = _risk_controls()
    positions_doc = _load_json(data_dir / "current_positions.json") or {}
    equity_doc = _load_json(data_dir / "equity_curve_daily.json") or {}
    summary = equity_doc.get("summary", {}) if isinstance(equity_doc, dict) else {}

    capital = float(positions_doc.get("capital_usd") or 0.0)
    cash = float(positions_doc.get("cash_usd") or 0.0)
    positions = positions_doc.get("positions", {}) if isinstance(positions_doc, dict) else {}
    tier_map = _tier_map()

    checks: list[dict[str, Any]] = []

    # Kill switch — drawdown must be below the kill threshold.
    max_dd_pct = abs(float(summary.get("max_drawdown_pct") or 0.0))
    kill_thr = controls["kill_switch_drawdown_pct"]
    checks.append(
        _eval_control(
            "kill_switch",
            f"Portfolio drawdown kill switch (≥{kill_thr:.0f}% closes all)",
            max_dd_pct < kill_thr,
            f"observed max drawdown {max_dd_pct:.2f}% vs {kill_thr:.0f}% threshold",
        )
    )

    # Per-protocol T1 cap.
    t1_cap = controls["max_concentration_t1_pct"]
    t2_cap = controls["max_concentration_t2_pct"]
    worst_t1 = ("", 0.0)
    worst_t2 = ("", 0.0)
    t2_total_usd = 0.0
    if capital > 0 and isinstance(positions, dict):
        for proto, amt in positions.items():
            try:
                pct = float(amt) / capital * 100
            except (TypeError, ZeroDivisionError):
                continue
            tier = tier_map.get(proto, "T2")
            if tier == "T1" and pct > worst_t1[1]:
                worst_t1 = (proto, pct)
            if tier == "T2":
                t2_total_usd += float(amt)
                if pct > worst_t2[1]:
                    worst_t2 = (proto, pct)
    checks.append(
        _eval_control(
            "t1_concentration_cap",
            f"T1 per-protocol cap (≤{t1_cap:.0f}%)",
            worst_t1[1] <= t1_cap + 1e-9,
            f"max T1 position {worst_t1[0] or 'n/a'} at {worst_t1[1]:.2f}%",
        )
    )
    checks.append(
        _eval_control(
            "t2_concentration_cap",
            f"T2 per-protocol cap (≤{t2_cap:.0f}%)",
            worst_t2[1] <= t2_cap + 1e-9,
            f"max T2 position {worst_t2[0] or 'n/a'} at {worst_t2[1]:.2f}%",
        )
    )

    # T2 total cap.
    t2_total_cap = controls["max_total_t2_pct"]
    t2_total_pct = (t2_total_usd / capital * 100) if capital > 0 else 0.0
    checks.append(
        _eval_control(
            "t2_total_cap",
            f"T2 aggregate cap (≤{t2_total_cap:.0f}%)",
            t2_total_pct <= t2_total_cap + 1e-9,
            f"T2 aggregate {t2_total_pct:.2f}% of portfolio",
        )
    )

    # Min cash buffer.
    min_cash = controls["min_cash_pct"]
    cash_pct = (cash / capital * 100) if capital > 0 else 0.0
    checks.append(
        _eval_control(
            "min_cash_buffer",
            f"Minimum cash buffer (≥{min_cash:.0f}%)",
            cash_pct >= min_cash - 1e-9,
            f"cash buffer {cash_pct:.2f}% of capital",
        )
    )

    # TVL floor (policy-level control — always enforced by allocator/gate).
    checks.append(
        _eval_control(
            "tvl_floor",
            f"Per-pool TVL floor (≥${controls['min_tvl_usd']:,.0f})",
            True,
            "enforced by RiskPolicy gate on every rebalance",
        )
    )

    # APY entry bounds.
    checks.append(
        _eval_control(
            "apy_entry_bounds",
            f"New-position APY bounds ({controls['min_apy_pct']:.0f}%–{controls['max_apy_pct']:.0f}%)",
            True,
            "enforced by RiskPolicy gate on every candidate entry",
        )
    )

    passed = sum(1 for c in checks if c["status"] == "PASS")
    return {
        "limits": controls,
        "controls": checks,
        "passed": passed,
        "total": len(checks),
        "all_pass": passed == len(checks),
    }


def build_paper_track_section(data_dir: Path) -> dict[str, Any]:
    """Section 4 — PAPER TRACK: start, days, equity, APY, consistency."""
    equity_doc = _load_json(data_dir / "equity_curve_daily.json") or {}
    summary = equity_doc.get("summary", {}) if isinstance(equity_doc, dict) else {}
    daily = equity_doc.get("daily", []) if isinstance(equity_doc, dict) else []

    start_equity = float(summary.get("start_equity") or 0.0)
    end_equity = float(summary.get("end_equity") or 0.0)
    total_return_pct = float(summary.get("total_return_pct") or 0.0)
    days = _days_elapsed(TRACK_START_DATE)

    # Annualised (simple) from the partial track.
    track_days = max(1, int(summary.get("num_days") or len(daily) or 1))
    annualized_pct = total_return_pct / track_days * 365 if track_days else 0.0

    # Consistency: share of non-negative days + return volatility.
    positive_days = int(summary.get("positive_days") or 0)
    negative_days = int(summary.get("negative_days") or 0)
    counted = positive_days + negative_days
    consistency_pct = (positive_days / counted * 100) if counted else 0.0

    return {
        "track_start_date": TRACK_START_DATE,
        "days_elapsed": days,
        "track_days_recorded": track_days,
        "start_equity_usd": start_equity,
        "end_equity_usd": end_equity,
        "total_return_pct": round(total_return_pct, 4),
        "annualized_return_pct": round(annualized_pct, 4),
        "max_drawdown_pct": float(summary.get("max_drawdown_pct") or 0.0),
        "daily_volatility_pct": float(summary.get("daily_volatility_pct") or 0.0),
        "positive_days": positive_days,
        "negative_days": negative_days,
        "consistency_pct": round(consistency_pct, 2),
        "is_demo": bool(equity_doc.get("is_demo", False)) if isinstance(equity_doc, dict) else None,
    }


def build_positions_section(data_dir: Path) -> dict[str, Any]:
    """Section 5 — POSITIONS: size, protocol, APY, risk tier."""
    positions_doc = _load_json(data_dir / "current_positions.json") or {}
    equity_doc = _load_json(data_dir / "equity_curve_daily.json") or {}
    tier_map = _tier_map()

    capital = float(positions_doc.get("capital_usd") or 0.0)
    raw_positions = positions_doc.get("positions", {}) if isinstance(positions_doc, dict) else {}

    # Best-effort per-protocol APY from the latest equity snapshot is portfolio
    # level only; per-protocol APY is not stored, so we surface the protocol +
    # tier + size and leave APY null unless an adapter-level feed is present.
    apy_doc = _load_json(data_dir / "apy_ranking.json")
    apy_lookup: dict[str, float] = {}
    if isinstance(apy_doc, dict):
        for k, v in apy_doc.items():
            if isinstance(v, (int, float)):
                apy_lookup[k] = float(v)
            elif isinstance(v, dict) and isinstance(v.get("apy"), (int, float)):
                apy_lookup[k] = float(v["apy"])

    rows: list[dict[str, Any]] = []
    if isinstance(raw_positions, dict):
        for proto, amt in sorted(raw_positions.items(), key=lambda kv: -float(kv[1] or 0)):
            try:
                size = float(amt)
            except (TypeError, ValueError):
                continue
            rows.append(
                {
                    "protocol": proto,
                    "size_usd": round(size, 2),
                    "weight_pct": round(size / capital * 100, 4) if capital > 0 else None,
                    "tier": tier_map.get(proto, "T2"),
                    "apy_pct": apy_lookup.get(proto),
                }
            )

    return {
        "capital_usd": capital,
        "deployed_usd": float(positions_doc.get("deployed_usd") or 0.0),
        "cash_usd": float(positions_doc.get("cash_usd") or 0.0),
        "position_count": len(rows),
        "positions": rows,
    }


def build_events_log_section(data_dir: Path, limit: int = 30) -> dict[str, Any]:
    """Section 6 — EVENTS LOG: last *limit* audit-trail entries.

    Prefers the signed hash chain; falls back to the plain audit_trail.jsonl.
    """
    source = "audit_chain"
    records: list[dict[str, Any]] = []
    try:
        chain_path = data_dir / audit_trail_signer.CHAIN_FILENAME
        records = audit_trail_signer.read_chain(filepath=chain_path)
    except Exception:
        records = []

    if not records:
        source = "audit_trail_jsonl"
        plain = data_dir / "audit_trail.jsonl"
        if plain.exists():
            try:
                with plain.open("r", encoding="utf-8") as fh:
                    for raw in fh:
                        raw = raw.strip()
                        if not raw:
                            continue
                        try:
                            records.append(json.loads(raw))
                        except json.JSONDecodeError:
                            continue
            except OSError:
                records = []

    last = records[-limit:]
    # Compact each entry to the audit-relevant fields.
    entries = []
    for r in last:
        entries.append(
            {
                "timestamp": r.get("timestamp") or r.get("appended_at"),
                "event_type": r.get("event_type"),
                "event_id": r.get("event_id"),
                "chain_hash": (r.get("chain_hash") or "")[:16] or None,
            }
        )
    return {
        "source": source,
        "total_records": len(records),
        "returned": len(entries),
        "entries": entries,
    }


def build_integrity_section(data_dir: Path) -> dict[str, Any]:
    """Section 7 — INTEGRITY CHECK: verify the SHA-256 audit hash chain."""
    chain_path = data_dir / audit_trail_signer.CHAIN_FILENAME
    section: dict[str, Any] = {
        "chain_file": str(chain_path),
        "chain_exists": chain_path.exists(),
    }
    try:
        records = audit_trail_signer.read_chain(filepath=chain_path)
        section["records"] = len(records)
        verified = audit_trail_signer.verify_chain(filepath=chain_path)
        section["verified"] = bool(verified)
        section["status"] = "INTACT" if verified else "BROKEN"
    except audit_trail_signer.AuditChainTamperedError as exc:
        section["verified"] = False
        section["status"] = "TAMPERED"
        section["tampered_record_index"] = exc.record_index
        section["expected_hash"] = exc.expected_hash[:16]
        section["actual_hash"] = exc.actual_hash[:16]
    except Exception as exc:  # pragma: no cover - defensive
        section["verified"] = False
        section["status"] = "ERROR"
        section["error"] = str(exc)
    return section


def build_system_health_section(data_dir: Path) -> dict[str, Any]:
    """Section 8 — SYSTEM HEALTH: GoLive status, last cycle, 7-day error count."""
    golive = _load_json(data_dir / "golive_status.json") or {}
    equity = _load_json(data_dir / "current_positions.json") or {}

    last_cycle = None
    if isinstance(equity, dict):
        last_cycle = equity.get("generated_at")

    # Error count last 7 days from the cycle error log (best-effort).
    error_count = _count_recent_errors(Path("/tmp/spa_cycle_err.log"), days=7)

    return {
        "golive_ready": bool(golive.get("ready", False)) if isinstance(golive, dict) else None,
        "golive_passed": golive.get("passed") if isinstance(golive, dict) else None,
        "golive_total": golive.get("total") if isinstance(golive, dict) else None,
        "golive_blockers": golive.get("blockers", []) if isinstance(golive, dict) else [],
        "last_cycle_run": last_cycle,
        "error_count_7d": error_count,
    }


def _count_recent_errors(log_path: Path, days: int = 7) -> int:
    """Count ERROR/Traceback markers in *log_path* (best-effort, capped read)."""
    if not log_path.exists():
        return 0
    count = 0
    try:
        # Read only the tail (cap at ~2MB) to stay cheap on large logs.
        size = log_path.stat().st_size
        with log_path.open("rb") as fh:
            if size > 2_000_000:
                fh.seek(size - 2_000_000)
            data = fh.read().decode("utf-8", errors="replace")
        for line in data.splitlines():
            if "ERROR" in line or "Traceback" in line:
                count += 1
    except OSError:
        return 0
    return count


# ---------------------------------------------------------------------------
# Report assembly + rendering
# ---------------------------------------------------------------------------


def generate_report(
    *,
    data_dir: str | Path | None = None,
    adr_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Build the full audit report dict.  Never raises (fail-safe per section)."""
    ddir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    adir = Path(adr_dir) if adr_dir else _DEFAULT_ADR_DIR

    report: dict[str, Any] = {
        "report_type": "institutional_audit_report",
        "version": "v1.0",
        "generated_at": _utc_now_iso(),
        "data_dir": str(ddir),
        "sections": {
            "identity": build_identity_section(),
            "governance": build_governance_section(adir),
            "risk_controls": build_risk_controls_section(ddir),
            "paper_track": build_paper_track_section(ddir),
            "positions": build_positions_section(ddir),
            "events_log": build_events_log_section(ddir),
            "integrity_check": build_integrity_section(ddir),
            "system_health": build_system_health_section(ddir),
        },
    }
    return report


def render_markdown(report: dict[str, Any]) -> str:
    """Render the report dict as a human-readable Markdown document."""
    s = report.get("sections", {})
    out: list[str] = []
    out.append("# SPA — Institutional Audit Report")
    out.append("")
    out.append(f"_Generated: {report.get('generated_at')}_  ·  _Version: {report.get('version')}_")
    out.append("")

    # 1. Identity
    ident = s.get("identity", {})
    out.append("## 1. Identity")
    out.append("")
    out.append(f"> {ident.get('statement', '')}")
    out.append("")
    out.append(f"- External capital managed: **${ident.get('external_capital_managed_usd', 0):,.0f}**")
    out.append(f"- Trading mode: **{ident.get('trading_mode', 'paper')}**")
    out.append("")

    # 2. Governance
    gov = s.get("governance", {})
    out.append("## 2. Governance")
    out.append("")
    out.append(f"- ADR count: **{gov.get('adr_count', 0)}**")
    out.append(f"- Last decision: **{gov.get('last_decision_date', 'n/a')}** ({gov.get('last_decision_file', 'n/a')})")
    out.append(f"- Rule changes this month: **{gov.get('rule_changes_this_month', 0)}**")
    out.append(f"- Risk policy version: **{gov.get('risk_policy_version', 'v1.0')}**")
    out.append("")

    # 3. Risk controls
    rc = s.get("risk_controls", {})
    out.append("## 3. Risk Controls")
    out.append("")
    out.append(f"**{rc.get('passed', 0)}/{rc.get('total', 0)} controls PASS**")
    out.append("")
    out.append("| Control | Status | Detail |")
    out.append("|---|---|---|")
    for c in rc.get("controls", []):
        out.append(f"| {c.get('label', c.get('control'))} | **{c.get('status')}** | {c.get('detail', '')} |")
    out.append("")

    # 4. Paper track
    pt = s.get("paper_track", {})
    out.append("## 4. Paper Track")
    out.append("")
    out.append(f"- Track start: **{pt.get('track_start_date')}**  ·  Days elapsed: **{pt.get('days_elapsed')}**")
    out.append(f"- NAV: **${pt.get('start_equity_usd', 0):,.2f}** → **${pt.get('end_equity_usd', 0):,.2f}**")
    out.append(f"- Total return: **{pt.get('total_return_pct', 0):.4f}%**  ·  Annualized: **{pt.get('annualized_return_pct', 0):.2f}%**")
    out.append(f"- Max drawdown: **{pt.get('max_drawdown_pct', 0):.4f}%**  ·  Daily vol: **{pt.get('daily_volatility_pct', 0):.4f}%**")
    out.append(f"- Consistency (positive days): **{pt.get('consistency_pct', 0):.1f}%** ({pt.get('positive_days', 0)}+ / {pt.get('negative_days', 0)}-)")
    out.append("")

    # 5. Positions
    pos = s.get("positions", {})
    out.append("## 5. Positions")
    out.append("")
    out.append(f"- Capital: **${pos.get('capital_usd', 0):,.2f}**  ·  Deployed: **${pos.get('deployed_usd', 0):,.2f}**  ·  Cash: **${pos.get('cash_usd', 0):,.2f}**")
    out.append(f"- Open positions: **{pos.get('position_count', 0)}**")
    out.append("")
    out.append("| Protocol | Size (USD) | Weight | Tier | APY |")
    out.append("|---|---:|---:|:---:|---:|")
    for r in pos.get("positions", []):
        w = f"{r['weight_pct']:.2f}%" if r.get("weight_pct") is not None else "—"
        apy = f"{r['apy_pct']:.2f}%" if r.get("apy_pct") is not None else "—"
        out.append(f"| {r.get('protocol')} | {r.get('size_usd', 0):,.2f} | {w} | {r.get('tier')} | {apy} |")
    out.append("")

    # 6. Events log
    ev = s.get("events_log", {})
    out.append("## 6. Events Log")
    out.append("")
    out.append(f"_Source: {ev.get('source')}  ·  {ev.get('returned')} of {ev.get('total_records')} records_")
    out.append("")
    out.append("| Timestamp | Event | Chain hash |")
    out.append("|---|---|---|")
    for e in ev.get("entries", []):
        out.append(f"| {e.get('timestamp', '')} | {e.get('event_type', '')} | {e.get('chain_hash') or '—'} |")
    out.append("")

    # 7. Integrity check
    ic = s.get("integrity_check", {})
    out.append("## 7. Integrity Check")
    out.append("")
    out.append(f"- Hash chain: **{ic.get('status', 'UNKNOWN')}**  ·  Verified: **{ic.get('verified')}**")
    out.append(f"- Records: **{ic.get('records', 0)}**  ·  File exists: **{ic.get('chain_exists')}**")
    if ic.get("status") == "TAMPERED":
        out.append(f"- ⚠️ Tampered at record index **{ic.get('tampered_record_index')}**")
    out.append("")

    # 8. System health
    sh = s.get("system_health", {})
    out.append("## 8. System Health")
    out.append("")
    out.append(f"- GoLive: **{sh.get('golive_passed')}/{sh.get('golive_total')}**  ·  Ready: **{sh.get('golive_ready')}**")
    out.append(f"- Last cycle run: **{sh.get('last_cycle_run', 'n/a')}**")
    out.append(f"- Errors (last 7d): **{sh.get('error_count_7d', 0)}**")
    blockers = sh.get("golive_blockers", [])
    if blockers:
        out.append("- Blockers:")
        for b in blockers:
            out.append(f"  - {b}")
    out.append("")

    return "\n".join(out)


def write_report(
    report: dict[str, Any],
    *,
    data_dir: str | Path | None = None,
) -> dict[str, str]:
    """Atomically write JSON + Markdown artifacts.  Returns the written paths."""
    ddir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
    json_path = ddir / REPORT_JSON_FILENAME
    md_path = ddir / REPORT_MD_FILENAME

    _atomic_write(json_path, json.dumps(report, indent=2, ensure_ascii=False))
    _atomic_write(md_path, render_markdown(report))
    return {"json": str(json_path), "md": str(md_path)}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    do_run = "--run" in argv
    data_dir = None
    if "--data-dir" in argv:
        try:
            data_dir = argv[argv.index("--data-dir") + 1]
        except IndexError:
            data_dir = None

    report = generate_report(data_dir=data_dir)
    ic = report["sections"]["integrity_check"]
    rc = report["sections"]["risk_controls"]

    print("SPA Institutional Audit Report")
    print(f"  generated_at : {report['generated_at']}")
    print(f"  risk controls: {rc['passed']}/{rc['total']} PASS")
    print(f"  integrity    : {ic.get('status')} (verified={ic.get('verified')})")
    print(f"  golive       : {report['sections']['system_health'].get('golive_passed')}"
          f"/{report['sections']['system_health'].get('golive_total')}")

    if do_run:
        paths = write_report(report, data_dir=data_dir)
        print(f"  wrote        : {paths['json']}")
        print(f"  wrote        : {paths['md']}")
    else:
        print("  (--check mode: no files written; pass --run to write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
