"""
Go-Live Readiness Checker — automated pre-flight for real capital deployment.
All criteria must PASS before go-live is recommended.
Owner (Yurii) makes final decision — this is advisory only.

Criteria evaluated:
  1. Paper trading duration  ≥ 50 days
  2. PnL positive            total_pnl_usd > 0
  3. No critical alerts      0 CRITICAL severity alerts
  4. Strategy Sharpe ≥ 1.0   backtest sharpe_ratio
  5. Policy unchanged        RiskConfig.version == "v1.0"
  6. Max drawdown < 3%       portfolio total_drawdown_pct
  7. Diversification         ≥ 2 protocols, none > 45%
  8. Data freshness          last export < 6h ago
  9. Wallet ready            Gnosis Safe + hot wallet setup (manual — always PENDING)

Verdict logic:
  READY        — all performance criteria PASS (or at most 1 WARN, no FAIL/PENDING
                 on criteria 1–8); criterion 9 PENDING is acceptable for READY verdict
  ALMOST_READY — ≤2 WARN on criteria 1–8, no FAIL, no PENDING on criteria 1–8
  NOT_READY    — any FAIL or any PENDING on criteria 1–8
  BLOCKED      — critical alerts OR negative PnL
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# ── Constants ────────────────────────────────────────────────────────────────

GO_LIVE_DATE    = "2026-07-15"
PAPER_START_DATE = "2026-05-20"
MIN_PAPER_DAYS  = 50   # minimum days of paper trading required

_STATUS   = "status"
_PASS     = "PASS"
_FAIL     = "FAIL"
_WARN     = "WARN"
_PENDING  = "PENDING"

# ── Helpers ──────────────────────────────────────────────────────────────────

def _criterion(name: str, status: str, value: Any, threshold: Any, note: str) -> dict:
    return {
        "name":      name,
        "status":    status,
        "value":     value,
        "threshold": threshold,
        "note":      note,
    }


def _load_json(data_dir: str, filename: str) -> dict | None:
    """Load a JSON file from data_dir; return None on any failure."""
    try:
        path = Path(data_dir) / filename
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _today() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(ts: str) -> datetime:
    """Parse ISO-8601 timestamp, always returning a timezone-aware datetime."""
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ── Individual criteria ───────────────────────────────────────────────────────

def check_paper_duration() -> dict:
    """Days of paper trading elapsed ≥ MIN_PAPER_DAYS."""
    start = datetime.fromisoformat(PAPER_START_DATE).replace(tzinfo=timezone.utc)
    elapsed = (_today() - start).days

    if elapsed >= MIN_PAPER_DAYS:
        status = _PASS
        note   = f"{elapsed} days elapsed ≥ {MIN_PAPER_DAYS}-day minimum"
    elif elapsed < 14:
        status = _FAIL
        note   = f"Only {elapsed} days elapsed — too early to evaluate (< 14 days)"
    else:
        status = _PENDING
        note   = f"{elapsed}/{MIN_PAPER_DAYS} days elapsed — keep paper trading"

    return _criterion(
        name      = "Paper Duration",
        status    = status,
        value     = elapsed,
        threshold = MIN_PAPER_DAYS,
        note      = note,
    )


def check_pnl_positive(portfolio: dict) -> dict:
    """Total PnL must be positive."""
    pnl = portfolio.get("total_pnl_usd", 0.0) or 0.0
    total = portfolio.get("total_capital_usd", 100_000) or 100_000
    pnl_pct = round(pnl / total * 100, 4) if total else 0.0

    if pnl > 0:
        status = _PASS
        note   = f"+${pnl:,.2f} (+{pnl_pct:.2f}%)"
    elif pnl == 0:
        status = _WARN
        note   = "PnL is exactly $0.00 — neutral"
    else:
        status = _FAIL
        note   = f"Negative PnL: ${pnl:,.2f} ({pnl_pct:.2f}%)"

    return _criterion(
        name      = "PnL Positive",
        status    = status,
        value     = round(pnl, 2),
        threshold = 0,
        note      = note,
    )


def check_no_critical_alerts(risk_data: dict) -> dict:
    """No CRITICAL-severity risk alerts currently active."""
    alerts = risk_data.get("alerts", [])
    critical = [a for a in alerts if str(a.get("severity", "")).upper() == "CRITICAL"]
    count = len(critical)

    if count == 0:
        status = _PASS
        note   = f"0 critical alerts{' ('+str(len(alerts))+' warnings)' if alerts else ''}"
    else:
        status = _FAIL
        note   = f"{count} critical alert(s) active: " + "; ".join(
            a.get("message", str(a)) for a in critical[:3]
        )

    return _criterion(
        name      = "No Critical Alerts",
        status    = status,
        value     = count,
        threshold = 0,
        note      = note,
    )


def check_strategy_performance(backtest_data: dict) -> dict:
    """Backtest Sharpe ratio ≥ 1.0."""
    metrics = backtest_data.get("metrics", {})
    sharpe  = metrics.get("sharpe_ratio", None)

    if sharpe is None:
        return _criterion(
            name      = "Strategy Sharpe",
            status    = _WARN,
            value     = None,
            threshold = 1.0,
            note      = "Backtest data unavailable — cannot evaluate Sharpe ratio",
        )

    sharpe = float(sharpe)

    if sharpe >= 1.0:
        status = _PASS
        note   = f"Sharpe: {sharpe:.2f} ≥ 1.0"
    elif sharpe >= 0.5:
        status = _WARN
        note   = f"Sharpe: {sharpe:.2f} — marginal (0.5 ≤ sharpe < 1.0)"
    else:
        status = _FAIL
        note   = f"Sharpe: {sharpe:.2f} — below minimum 0.5"

    return _criterion(
        name      = "Strategy Sharpe",
        status    = status,
        value     = round(sharpe, 4),
        threshold = 1.0,
        note      = note,
    )


def check_policy_unchanged() -> dict:
    """Active RiskConfig must still be v1.0 (no unapproved changes)."""
    try:
        import sys
        # Ensure spa_core is on the path
        spa_core = str(Path(__file__).parent.parent)
        if spa_core not in sys.path:
            sys.path.insert(0, spa_core)
        from risk.policy import RiskConfig
        version = RiskConfig().version
    except Exception as e:
        return _criterion(
            name      = "Policy v1.0",
            status    = _WARN,
            value     = "unknown",
            threshold = "v1.0",
            note      = f"Could not load RiskConfig: {e}",
        )

    if version == "v1.0":
        status = _PASS
        note   = "RiskConfig v1.0 active — no unapproved changes"
    else:
        status = _WARN
        note   = f"Active policy is {version} (expected v1.0) — requires owner review"

    return _criterion(
        name      = "Policy v1.0",
        status    = status,
        value     = version,
        threshold = "v1.0",
        note      = note,
    )


def check_drawdown_acceptable(portfolio: dict) -> dict:
    """Max drawdown must be < 3% (WARN 3-4%, FAIL > 4%)."""
    drawdown = portfolio.get("total_drawdown_pct", 0.0) or 0.0
    drawdown = float(drawdown)
    pct_str  = f"{drawdown * 100:.2f}%"

    if drawdown <= 0.03:
        status = _PASS
        note   = f"{pct_str} ≤ 3.0% threshold"
    elif drawdown <= 0.04:
        status = _WARN
        note   = f"{pct_str} — elevated (3.0–4.0% zone), monitor closely"
    else:
        status = _FAIL
        note   = f"{pct_str} exceeds 4.0% hard limit"

    return _criterion(
        name      = "Max Drawdown",
        status    = status,
        value     = round(drawdown, 6),
        threshold = 0.03,
        note      = note,
    )


def check_diversification(positions: list) -> dict:
    """At least 2 protocols, no single protocol > 45% of portfolio."""
    # Build per-protocol totals
    protocol_totals: dict[str, float] = {}
    total_deployed = 0.0
    for pos in positions:
        key = pos.get("protocol_key") or pos.get("protocol", "unknown")
        amt = float(pos.get("amount_usd", 0.0) or 0.0)
        protocol_totals[key] = protocol_totals.get(key, 0.0) + amt
        total_deployed += amt

    n_protocols = len(protocol_totals)
    max_conc_pct = 0.0
    max_conc_proto = "—"

    if total_deployed > 0:
        for proto, amt in protocol_totals.items():
            frac = amt / total_deployed
            if frac > max_conc_pct:
                max_conc_pct = frac
                max_conc_proto = proto

    if max_conc_pct > 0.45:
        status = _FAIL
        note   = (f"Protocol '{max_conc_proto}' at {max_conc_pct*100:.0f}% "
                  f"exceeds 45% single-protocol cap")
    elif n_protocols < 2:
        status = _WARN
        note   = f"Only {n_protocols} protocol(s) — aim for ≥ 2"
    else:
        status = _PASS
        note   = (f"{n_protocols} protocols, "
                  f"max concentration {max_conc_pct*100:.0f}% ({max_conc_proto})")

    return _criterion(
        name      = "Diversification",
        status    = status,
        value     = {"protocols": n_protocols, "max_concentration": round(max_conc_pct, 4)},
        threshold = {"min_protocols": 2, "max_single_pct": 0.45},
        note      = note,
    )


def check_wallet_ready() -> dict:
    """
    Criterion 9: Gnosis Safe and hot wallet infrastructure is set up.

    This criterion is ALWAYS PENDING — it is a manual setup task that cannot
    be auto-verified by reading data files. Yurii must complete all items in
    docs/v2_activation_checklist.md (Section B) and manually confirm readiness.

    Severity: WARN (not FAIL) — wallet setup is a deployment prerequisite, not
    a performance criterion. It does NOT block the READY verdict on its own.

    What constitutes "wallet ready":
      - Gnosis Safe created and tested with a $10 test transaction
      - Hot wallet (MetaMask) created, funded with ETH for gas, no USDC
      - Hot wallet added as Safe delegate
      - SAFE_ADDRESS and WALLET_ADDRESS set in GitHub Secrets
      - Private key NOT in git history

    Returns:
        Criterion dict with status=PENDING and note pointing to the checklist.
    """
    return _criterion(
        name      = "Wallet Ready",
        status    = _PENDING,
        value     = "not_verified",
        threshold = "manual_setup",
        note      = (
            "Manual setup required — cannot auto-verify. "
            "Complete Section B of docs/v2_activation_checklist.md: "
            "Gnosis Safe creation, hot wallet setup, Safe delegate configuration, "
            "and GitHub Secrets (SAFE_ADDRESS, WALLET_ADDRESS)."
        ),
    )


def check_data_freshness(generated_at: str) -> dict:
    """Last data export must be < 6h ago (WARN 6-12h, FAIL > 12h)."""
    try:
        export_dt = _parse_iso(generated_at)
        age       = _today() - export_dt
        hours     = age.total_seconds() / 3600
    except Exception as e:
        return _criterion(
            name      = "Data Freshness",
            status    = _WARN,
            value     = generated_at,
            threshold = "< 6h",
            note      = f"Cannot parse timestamp: {e}",
        )

    if hours < 6:
        status = _PASS
        note   = f"Updated {hours:.1f}h ago"
    elif hours < 12:
        status = _WARN
        note   = f"Data is {hours:.1f}h old — approaching staleness (threshold: 6h)"
    else:
        status = _FAIL
        note   = f"Data is {hours:.1f}h old — stale (threshold: 12h)"

    return _criterion(
        name      = "Data Freshness",
        status    = status,
        value     = f"{hours:.1f}h ago",
        threshold = "< 6h",
        note      = note,
    )


# ── Verdict ──────────────────────────────────────────────────────────────────

def _compute_verdict(criteria: list[dict]) -> tuple[str, str]:
    """Return (verdict, verdict_emoji) from list of criterion dicts.

    Criterion 9 (Wallet Ready) is a WARN-class criterion — its PENDING status
    does NOT trigger NOT_READY on its own. It is excluded from the
    performance-based verdict evaluation (criteria 1–8).
    """
    # Split criteria: performance criteria (1–8) vs setup criteria (9+)
    SETUP_CRITERIA = {"Wallet Ready"}
    perf_criteria  = [c for c in criteria if c["name"] not in SETUP_CRITERIA]

    statuses = [c["status"] for c in perf_criteria]

    fail_count    = statuses.count(_FAIL)
    pending_count = statuses.count(_PENDING)
    warn_count    = statuses.count(_WARN)

    # BLOCKED — critical special case (negative PnL or critical alerts)
    pnl_crit   = next((c for c in perf_criteria if c["name"] == "PnL Positive"),    None)
    alert_crit = next((c for c in perf_criteria if c["name"] == "No Critical Alerts"), None)
    if (pnl_crit    and pnl_crit["status"]   == _FAIL) or \
       (alert_crit  and alert_crit["status"] == _FAIL):
        return "BLOCKED", "🚫"

    if fail_count > 0 or pending_count > 0:
        return "NOT_READY", "🔴"

    if warn_count == 0:
        return "READY", "✅"
    if warn_count == 1:
        return "READY", "✅"
    if warn_count <= 2:
        return "ALMOST_READY", "🟡"

    return "NOT_READY", "🔴"


def _build_summary(criteria: list[dict]) -> str:
    fails    = [c["name"] for c in criteria if c["status"] == _FAIL]
    pendings = [c["name"] for c in criteria if c["status"] == _PENDING]
    warns    = [c["name"] for c in criteria if c["status"] == _WARN]
    passes   = sum(1 for c in criteria if c["status"] == _PASS)
    total    = len(criteria)

    parts = [f"{passes}/{total} criteria passing"]
    if pendings:
        parts.append(f"{len(pendings)} pending ({', '.join(pendings)})")
    if fails:
        parts.append(f"{len(fails)} failing ({', '.join(fails)})")
    if warns:
        parts.append(f"{len(warns)} warning ({', '.join(warns)})")
    return "; ".join(parts)


def _build_recommendation(verdict: str, criteria: list[dict]) -> tuple[str, bool]:
    """Return (recommendation_text, owner_action_required)."""
    today      = _today()
    go_live_dt = datetime.fromisoformat(GO_LIVE_DATE).replace(tzinfo=timezone.utc)
    start_dt   = datetime.fromisoformat(PAPER_START_DATE).replace(tzinfo=timezone.utc)
    elapsed    = (today - start_dt).days

    # When will duration criterion pass?
    duration_pass_dt = start_dt + timedelta(days=MIN_PAPER_DAYS)
    duration_pass_str = duration_pass_dt.strftime("%Y-%m-%d")

    if verdict == "READY":
        return (
            f"All criteria met. Owner review recommended before deploying real capital. "
            f"Go-live target: {GO_LIVE_DATE}.",
            True,
        )
    elif verdict == "ALMOST_READY":
        warn_names = [c["name"] for c in criteria if c["status"] == _WARN]
        return (
            f"Minor items to resolve: {', '.join(warn_names)}. "
            f"Review again in 48h or after addressing warnings.",
            False,
        )
    elif verdict == "BLOCKED":
        fail_names = [c["name"] for c in criteria if c["status"] == _FAIL]
        return (
            f"Deployment blocked: {', '.join(fail_names)}. "
            f"Resolve failing criteria before proceeding.",
            True,
        )
    else:  # NOT_READY
        if elapsed < MIN_PAPER_DAYS:
            days_left = MIN_PAPER_DAYS - elapsed
            return (
                f"Continue paper trading. "
                f"Next milestone: duration criterion passes on {duration_pass_str} "
                f"({days_left} days away). Review again after {duration_pass_str}.",
                False,
            )
        else:
            fail_names = [c["name"] for c in criteria if c["status"] in (_FAIL, _PENDING)]
            return (
                f"Address failing criteria: {', '.join(fail_names)}. "
                f"Review again in 48h.",
                False,
            )


# ── Main entry point ──────────────────────────────────────────────────────────

def run_full_check(data_dir: str) -> dict:
    """
    Run all 9 go-live readiness criteria against JSON data files in data_dir.

    Criteria 1–8 are performance-based and auto-verified from data files.
    Criterion 9 (Wallet Ready) is a manual setup task — always PENDING.
    Criterion 9 PENDING does NOT block the READY verdict; it is advisory.

    Never crashes — all file I/O is wrapped in try/except.
    Returns a fully populated dict with verdict, criteria list, and recommendation.
    """
    now = _today()

    # ── Load data files (all optional — degrade gracefully) ──────────────────
    status_data   = _load_json(data_dir, "status.json")   or {}
    alerts_data   = _load_json(data_dir, "risk_alerts.json") or {}
    backtest_data = _load_json(data_dir, "backtest_results.json") or {}

    portfolio  = status_data.get("portfolio", {})
    positions  = status_data.get("positions", [])
    generated_at = status_data.get("timestamp") or now.isoformat()

    # ── Run all 9 criteria ───────────────────────────────────────────────────
    criteria = [
        check_paper_duration(),
        check_pnl_positive(portfolio),
        check_no_critical_alerts(alerts_data),
        check_strategy_performance(backtest_data),
        check_policy_unchanged(),
        check_drawdown_acceptable(portfolio),
        check_diversification(positions),
        check_data_freshness(generated_at),
        check_wallet_ready(),             # Criterion 9 — manual, always PENDING
    ]

    # ── Verdict ──────────────────────────────────────────────────────────────
    verdict, verdict_emoji = _compute_verdict(criteria)
    summary                = _build_summary(criteria)
    recommendation, owner_action = _build_recommendation(verdict, criteria)

    # ── Days remaining until go-live ─────────────────────────────────────────
    go_live_dt     = datetime.fromisoformat(GO_LIVE_DATE).replace(tzinfo=timezone.utc)
    days_remaining = max(0, (go_live_dt - now).days)

    return {
        "generated_at":          now.isoformat(),
        "verdict":               verdict,
        "verdict_emoji":         verdict_emoji,
        "days_remaining":        days_remaining,
        "go_live_date":          GO_LIVE_DATE,
        "paper_start_date":      PAPER_START_DATE,
        "min_paper_days":        MIN_PAPER_DAYS,
        "summary":               summary,
        "criteria":              criteria,
        "recommendation":        recommendation,
        "owner_action_required": owner_action,
    }
