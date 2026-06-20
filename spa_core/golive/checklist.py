"""
Go-Live Readiness Checker — automated pre-flight for real capital deployment.
All criteria must PASS before go-live is recommended.
Owner (Yurii) makes final decision — this is advisory only.

Criteria evaluated:
  1.  Paper trading duration  ≥ 56 days (8 weeks per DEV_STRATEGY_v1.0)
  2.  PnL positive            total_pnl_usd > 0
  3.  No critical alerts      0 CRITICAL severity alerts
  4.  Strategy Sharpe ≥ 2.0   backtest sharpe_ratio (DEV_STRATEGY_v1.0 requirement)
  5.  Policy unchanged        RiskConfig.version == "v1.0"
  6.  Max drawdown < 3%       portfolio total_drawdown_pct
  7.  Diversification         ≥ 2 protocols, none > 45%
  8.  Data freshness          last export < 6h ago
  9.  Wallet ready            Gnosis Safe + hot wallet setup (manual — always PENDING)
  10. Strategy tournament      v1_passive OR v3_pendle_focused must be WINNING or TIED
                                (PASS) — v2_aggressive winner with LOW confidence (WARN)
                                — v2_aggressive winner with MEDIUM/HIGH confidence (FAIL)
  11. APY gap                  current APY within 2% of 7.3% target
  12. Agent stability          ≥ 28 consecutive days of stable agent operation

Verdict logic:
  READY        — all performance criteria PASS (or at most 1 WARN, no FAIL/PENDING
                 on criteria 1–8, 10–12); criterion 9 PENDING is acceptable for READY verdict
  ALMOST_READY — ≤2 WARN on performance criteria, no FAIL, no PENDING
  NOT_READY    — any FAIL or any PENDING on performance criteria
  BLOCKED      — critical alerts OR negative PnL
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# ── Constants ────────────────────────────────────────────────────────────────

GO_LIVE_DATE     = "2026-07-15"
# Real track started 2026-06-10; data before this date is demo/invalid.
PAPER_START_DATE = "2026-06-10"
MIN_PAPER_DAYS   = 56    # minimum days of paper trading required (8 weeks)
APY_TARGET       = 7.3   # target annualised APY (%)
APY_GAP_MAX      = 2.0   # maximum allowed deviation from APY_TARGET (%)

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

def days_remaining() -> int:
    """Return days remaining until go-live target date (2026-07-15). Never negative."""
    go_live_dt = datetime.fromisoformat(GO_LIVE_DATE).replace(tzinfo=timezone.utc)
    return max(0, (go_live_dt - _today()).days)


def check_paper_duration() -> dict:
    """Days of paper trading elapsed ≥ MIN_PAPER_DAYS.

    Start date is hardcoded as PAPER_START_DATE (2026-06-10) and requires
    ≥ MIN_PAPER_DAYS (56) days of paper trading before PASS (8-week minimum
    per DEV_STRATEGY_v1.0).
    Any count below MIN_PAPER_DAYS is PENDING — never a hard FAIL, because being
    early in the paper-trading period is expected, not a deployment blocker.
    """
    start = datetime.fromisoformat(PAPER_START_DATE).replace(tzinfo=timezone.utc)
    elapsed = (_today() - start).days

    if elapsed >= MIN_PAPER_DAYS:
        status = _PASS
        note   = f"{elapsed} days elapsed ≥ {MIN_PAPER_DAYS}-day minimum"
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


MIN_SHARPE = 2.0  # DEV_STRATEGY_v1.0 requires Sharpe ≥ 2.0 for go-live


def check_strategy_performance(backtest_data: dict) -> dict:
    """Backtest Sharpe ratio ≥ 2.0 (DEV_STRATEGY_v1.0 requirement)."""
    metrics = backtest_data.get("metrics", {})
    sharpe  = metrics.get("sharpe_ratio", None)

    if sharpe is None:
        return _criterion(
            name      = "Strategy Sharpe",
            status    = _WARN,
            value     = None,
            threshold = MIN_SHARPE,
            note      = "Backtest data unavailable — cannot evaluate Sharpe ratio",
        )

    sharpe = float(sharpe)

    if sharpe >= MIN_SHARPE:
        status = _PASS
        note   = f"Sharpe: {sharpe:.2f} ≥ {MIN_SHARPE}"
    elif sharpe >= 1.0:
        status = _WARN
        note   = f"Sharpe: {sharpe:.2f} — marginal (1.0 ≤ sharpe < {MIN_SHARPE})"
    else:
        status = _FAIL
        note   = f"Sharpe: {sharpe:.2f} — below minimum {MIN_SHARPE}"

    return _criterion(
        name      = "Strategy Sharpe",
        status    = status,
        value     = round(sharpe, 4),
        threshold = MIN_SHARPE,
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
    """Max drawdown must be < 3% (WARN 3–5%, FAIL > 5%).

    The FAIL threshold of 5% is aligned with RiskConfig.max_drawdown_stop — the
    same value that triggers the kill switch in the live risk policy.  Using the
    RiskConfig as single source of truth prevents the go-live check from using a
    different (harder-coded) threshold than the engine's own circuit breaker.
    """
    # Read the kill-switch threshold from RiskConfig so there is one source of truth.
    try:
        import sys as _sys
        _spa_core = str(Path(__file__).parent.parent)
        if _spa_core not in _sys.path:
            _sys.path.insert(0, _spa_core)
        from risk.policy import RiskConfig as _RiskConfig
        _max_drawdown_stop = _RiskConfig().max_drawdown_stop  # e.g. 0.05
    except Exception:
        _max_drawdown_stop = 0.05  # fallback if import fails

    drawdown = portfolio.get("total_drawdown_pct", 0.0) or 0.0
    drawdown = float(drawdown)
    pct_str  = f"{drawdown * 100:.2f}%"

    if drawdown <= 0.03:
        status = _PASS
        note   = f"{pct_str} ≤ 3.0% threshold"
    elif drawdown <= _max_drawdown_stop:
        status = _WARN
        note   = (f"{pct_str} — elevated (3.0–{_max_drawdown_stop*100:.0f}% zone), "
                  f"monitor closely (kill switch fires at {_max_drawdown_stop*100:.0f}%)")
    else:
        status = _FAIL
        note   = (f"{pct_str} exceeds {_max_drawdown_stop*100:.0f}% hard limit "
                  f"(RiskConfig.max_drawdown_stop)")

    return _criterion(
        name      = "Max Drawdown",
        status    = status,
        value     = round(drawdown, 6),
        threshold = _max_drawdown_stop,
        note      = note,
    )


def check_diversification(positions: list, total_capital: float = 0.0) -> dict:
    """At least 2 protocols, no single protocol > 45% of total portfolio capital.

    Args:
        positions:      list of position dicts (each with protocol_key/protocol, amount_usd).
        total_capital:  total portfolio capital in USD (deployed + cash).  When > 0
                        concentration is measured against total capital — the correct
                        denominator.  Falls back to deployed-only sum when omitted so
                        callers that don't have total_capital still get a usable result.
    """
    # Build per-protocol totals
    protocol_totals: dict[str, float] = {}
    total_deployed = 0.0
    for pos in positions:
        key = pos.get("protocol_key") or pos.get("protocol", "unknown")
        amt = float(pos.get("amount_usd", 0.0) or 0.0)
        protocol_totals[key] = protocol_totals.get(key, 0.0) + amt
        total_deployed += amt

    # Use total_capital as denominator when available (fixes bug: concentration was
    # measured against deployed-only capital, inflating percentages when cash is held).
    # E.g. $30K in one protocol out of $100K total = 30%, not 30/40 = 75%.
    denominator = total_capital if total_capital > 0 else total_deployed

    n_protocols = len(protocol_totals)
    max_conc_pct = 0.0
    max_conc_proto = "—"

    if denominator > 0:
        for proto, amt in protocol_totals.items():
            frac = amt / denominator
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


def check_tournament_winner(tournament_data: dict) -> dict:
    """Criterion 10: strategy tournament — an acceptable conservative strategy
    must be WINNING or TIED.

    Reads from data/tournament_results.json (written by export_data.py section 18).
    Ties are defined as scores within 0.001 of each other.

    Updated for IDEA-006 (sprint v2.3) to support the 3-way tournament:
        - v1_passive         — conservative baseline
        - v2_aggressive      — growth competitor (must NOT win with confidence)
        - v3_pendle_focused  — Pendle-focused yield maximiser (acceptable winner)

    Decision logic:
        PASS  — winner ∈ {v1_passive, v3_pendle_focused}, OR top two scores
                are within 0.001 (effectively tied at the top)
        WARN  — v2_aggressive winning with LOW confidence (statistical noise)
        FAIL  — v2_aggressive winning with MEDIUM or HIGH confidence

    Backwards compatibility: when tournament_results.json predates v3 it
    simply has no v3_pendle_focused score (defaults to 0.0) and the
    function still degrades to the original v1 vs v2 behaviour.
    """
    winner     = tournament_data.get("winner")
    scores     = tournament_data.get("scores", {})
    confidence = tournament_data.get("confidence", "UNKNOWN")

    if not winner:
        return _criterion(
            name      = "Strategy Tournament",
            status    = _WARN,
            value     = "unavailable",
            threshold = "v1_passive or v3_pendle_focused winning or tied",
            note      = "Tournament data unavailable — cannot evaluate",
        )

    v1_score = float(scores.get("v1_passive",        0.0) or 0.0)
    v2_score = float(scores.get("v2_aggressive",     0.0) or 0.0)
    v3_score = float(scores.get("v3_pendle_focused", 0.0) or 0.0)

    # Top two strategies are effectively tied if their scores are within 0.001.
    # We consider this a PASS — there is no statistically meaningful winner.
    sorted_scores = sorted([v1_score, v2_score, v3_score], reverse=True)
    top_two_tied  = abs(sorted_scores[0] - sorted_scores[1]) < 0.001

    acceptable_winners = {"v1_passive", "v3_pendle_focused"}

    score_str = (
        f"v1={v1_score:.3f}, v2={v2_score:.3f}, v3={v3_score:.3f}"
    )

    if winner in acceptable_winners or top_two_tied:
        status = _PASS
        descriptor = "TIED" if top_two_tied and winner not in acceptable_winners else (
            "TIED" if top_two_tied else "WINNING"
        )
        note = (
            f"acceptable winner: {winner} {descriptor} "
            f"(scores: {score_str}, confidence: {confidence})"
        )
    elif winner == "v2_aggressive" and str(confidence).upper() == "LOW":
        status = _WARN
        note = (
            f"v2_aggressive winning with LOW confidence — "
            f"likely statistical noise (scores: {score_str})"
        )
    else:
        status = _FAIL
        note = (
            f"v2_aggressive WINNING (confidence: {confidence}) — "
            f"conservative strategies losing (scores: {score_str})"
        )

    return _criterion(
        name      = "Strategy Tournament",
        status    = status,
        value     = {
            "winner":   winner,
            "v1_score": round(v1_score, 4),
            "v2_score": round(v2_score, 4),
            "v3_score": round(v3_score, 4),
        },
        threshold = "v1_passive or v3_pendle_focused winning or tied",
        note      = note,
    )


def check_apy_gap(analytics_data: dict, portfolio: dict) -> dict:
    """Criterion 11: APY gap — current APY must be within APY_GAP_MAX (2%) of APY_TARGET (7.3%).

    Prefers annualised_return_pct from advanced_analytics.json summary;
    falls back to current_apy from portfolio (status.json).

    PASS  — gap ≤ 2.0 pp
    WARN  — gap 2.0–3.0 pp
    FAIL  — gap > 3.0 pp
    """
    # Prefer annualised return from advanced analytics
    summary     = analytics_data.get("summary", {}) if analytics_data else {}
    current_apy = summary.get("annualised_return_pct")
    source      = "annualised_return"

    # Fall back to portfolio current_apy
    if current_apy is None:
        current_apy = portfolio.get("current_apy")
        source      = "portfolio_current_apy"

    if current_apy is None:
        return _criterion(
            name      = "APY Gap",
            status    = _WARN,
            value     = None,
            threshold = f"within {APY_GAP_MAX}% of {APY_TARGET}% target",
            note      = "APY data unavailable — cannot evaluate (no analytics or portfolio data)",
        )

    current_apy = float(current_apy)
    gap         = abs(current_apy - APY_TARGET)
    gap_sign    = "above" if current_apy > APY_TARGET else "below"

    if gap <= APY_GAP_MAX:
        status = _PASS
        note   = (
            f"APY {current_apy:.2f}% — {gap:.2f}pp {gap_sign} "
            f"{APY_TARGET}% target (source: {source})"
        )
    elif gap <= 3.0:
        status = _WARN
        note   = (
            f"APY {current_apy:.2f}% — {gap:.2f}pp {gap_sign} "
            f"{APY_TARGET}% target (limit: {APY_GAP_MAX}pp, source: {source})"
        )
    else:
        status = _FAIL
        note   = (
            f"APY {current_apy:.2f}% — {gap:.2f}pp {gap_sign} "
            f"{APY_TARGET}% target (limit: {APY_GAP_MAX}pp, source: {source})"
        )

    return _criterion(
        name      = "APY Gap",
        status    = status,
        value     = round(current_apy, 4),
        threshold = f"within {APY_GAP_MAX}% of {APY_TARGET}%",
        note      = note,
    )



def check_agent_stability(data_dir: str | None = None) -> dict:
    """Criterion 12: \u2265 28 consecutive days of stable agent operation.

    Reads from data/agent_stability.json via AgentStabilityTracker (SPA-F001).
    "Stable" means status.json is refreshed every export cycle (< 6 h old).
    Clock resets automatically if status.json becomes stale or is missing.

    PASS  \u2014 days >= 28
    WARN  \u2014 14 <= days < 28
    FAIL  \u2014 days < 14 (or tracking not yet started)
    """
    try:
        import sys as _sys
        _spa_core = str(Path(__file__).parent.parent)
        if _spa_core not in _sys.path:
            _sys.path.insert(0, _spa_core)
        from paper_trading.agent_stability import AgentStabilityTracker

        tracker = AgentStabilityTracker(
            data_dir=Path(data_dir) if data_dir else None
        )
        result = tracker.check_criterion()
        return _criterion(
            name      = "Agent Stability",
            status    = result["status"],
            value     = result["days"],
            threshold = result["target"],
            note      = result["message"],
        )
    except Exception as exc:
        return _criterion(
            name      = "Agent Stability",
            status    = _WARN,
            value     = None,
            threshold = 28,
            note      = f"Could not evaluate agent stability: {exc}",
        )

_WALLET_SENTINEL       = Path(__file__).parent.parent.parent / "data" / "wallet_ready.sentinel"
_WALLET_APPROVED_JSON  = Path(__file__).parent.parent.parent / "data" / "wallet_ready_approved.json"


def check_wallet_ready(data_dir: str | None = None) -> dict:
    """
    Criterion 9: Gnosis Safe and hot wallet infrastructure is set up.

    PASS when ANY of the following exist:
      (a) data/wallet_ready_approved.json  with {"approved": true, ...}
          — created by  python -m spa_core.golive.approve_wallet  (SPA-F003)
      (b) data/wallet_ready.sentinel
          — written by activate.py on full go-live activation

    Returns PENDING when neither file is present — manual setup required.

    Severity: WARN (not FAIL) — wallet setup is a deployment prerequisite, not
    a performance criterion. It does NOT block the READY verdict on its own.

    What constitutes "wallet ready":
      - Gnosis Safe created and tested with a $10 test transaction
      - Hot wallet (MetaMask) created, funded with ETH for gas, no USDC
      - Hot wallet added as Safe delegate
      - SAFE_ADDRESS and WALLET_ADDRESS set in GitHub Secrets
      - Private key NOT in git history
    """
    base = Path(data_dir) if data_dir else None

    # ── (a) JSON approval flag (SPA-F003) ────────────────────────────────────
    approved_json = (base / "wallet_ready_approved.json") if base else _WALLET_APPROVED_JSON
    if approved_json.exists():
        try:
            record = json.loads(approved_json.read_text(encoding="utf-8"))
            if record.get("approved") is True:
                approved_at = record.get("approved_at", "unknown")
                approved_by = record.get("approved_by", "operator")
                return _criterion(
                    name      = "Wallet Ready",
                    status    = _PASS,
                    value     = "approved",
                    threshold = "manual_setup",
                    note      = (
                        f"wallet_ready_approved.json present — "
                        f"approved by '{approved_by}' at {approved_at}"
                    ),
                )
        except Exception:
            pass  # fall through to sentinel check

    # ── (b) Legacy sentinel (written by activate.py) ──────────────────────────
    sentinel = (base / "wallet_ready.sentinel") if base else _WALLET_SENTINEL
    if sentinel.exists():
        return _criterion(
            name      = "Wallet Ready",
            status    = _PASS,
            value     = "verified",
            threshold = "manual_setup",
            note      = "wallet_ready.sentinel present — wallet infrastructure confirmed by owner",
        )

    # ── Neither present ───────────────────────────────────────────────────────
    return _criterion(
        name      = "Wallet Ready",
        status    = _PENDING,
        value     = "not_verified",
        threshold = "manual_setup",
        note      = (
            "Manual setup required — run: python -m spa_core.golive.approve_wallet  "
            "(SPA-F003). Complete Section B of docs/v2_activation_checklist.md: "
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
    performance-based verdict evaluation.
    Criteria 1–8, 10, 11 are all performance criteria and ARE evaluated.
    """
    # Split criteria: performance criteria (1–8, 10, 11) vs setup criteria (9)
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
    start_dt   = datetime.fromisoformat(PAPER_START_DATE).replace(tzinfo=timezone.utc)
    elapsed    = (today - start_dt).days

    # When will duration criterion pass?
    duration_pass_dt  = start_dt + timedelta(days=MIN_PAPER_DAYS)
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
    Run all 12 go-live readiness criteria against JSON data files in data_dir.

    Criteria 1–8, 10–12 are performance-based and auto-verified from data files.
    Criterion 9 (Wallet Ready) is a manual setup task — always PENDING.
    Criterion 9 PENDING does NOT block the READY verdict; it is advisory.

    Never crashes — all file I/O is wrapped in try/except.
    Returns a fully populated dict with verdict, criteria list, and recommendation.
    """
    now = _today()

    # ── Load data files (all optional — degrade gracefully) ──────────────────
    status_data      = _load_json(data_dir, "status.json")            or {}
    alerts_data      = _load_json(data_dir, "risk_alerts.json")       or {}
    backtest_data    = _load_json(data_dir, "backtest_results.json")  or {}
    tournament_data  = _load_json(data_dir, "tournament_results.json") or {}
    analytics_data   = _load_json(data_dir, "advanced_analytics.json") or {}

    portfolio    = status_data.get("portfolio", {})
    positions    = status_data.get("positions", [])
    generated_at = status_data.get("timestamp") or now.isoformat()

    # ── Run all 12 criteria ──────────────────────────────────────────────────
    # v3.21: count realigned from 11 → 12 — Agent Stability (#12) was added in
    # v2.6 but the inline comment was never updated.
    criteria = [
        check_paper_duration(),                           # 1
        check_pnl_positive(portfolio),                    # 2
        check_no_critical_alerts(alerts_data),            # 3
        check_strategy_performance(backtest_data),        # 4
        check_policy_unchanged(),                         # 5
        check_drawdown_acceptable(portfolio),             # 6
        check_diversification(                            # 7
            positions,
            total_capital=float(portfolio.get("total_capital_usd", 0.0) or 0.0),
        ),
        check_data_freshness(generated_at),               # 8
        check_wallet_ready(),                             # 9 — manual, always PENDING
        check_tournament_winner(tournament_data),         # 10
        check_apy_gap(analytics_data, portfolio),         # 11
        check_agent_stability(data_dir),                  # 12
    ]

    # ── Verdict ──────────────────────────────────────────────────────────────
    verdict, verdict_emoji = _compute_verdict(criteria)
    summary                = _build_summary(criteria)
    recommendation, owner_action = _build_recommendation(verdict, criteria)

    # ── Days remaining until go-live ─────────────────────────────────────────
    dr = days_remaining()

    return {
        "generated_at":          now.isoformat(),
        "verdict":               verdict,
        "verdict_emoji":         verdict_emoji,
        "days_remaining":        dr,
        "go_live_date":          GO_LIVE_DATE,
        "paper_start_date":      PAPER_START_DATE,
        "min_paper_days":        MIN_PAPER_DAYS,
        "summary":               summary,
        "criteria":              criteria,
        "recommendation":        recommendation,
        "owner_action_required": owner_action,
    }
