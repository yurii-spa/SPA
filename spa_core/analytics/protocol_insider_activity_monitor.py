"""
MP-870: ProtocolInsiderActivityMonitor
Monitors suspicious insider activity signals (team wallet movements, governance
token dumps, large pre-announcement trades) to flag protocols where insiders
may be cashing out.

Advisory / read-only. Pure stdlib only. Atomic writes (tmp + os.replace).
Ring-buffer JSON log capped at 100 entries.

Usage:
    from spa_core.analytics.protocol_insider_activity_monitor import analyze
    result = analyze(protocols)
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_FILE = _REPO_ROOT / "data" / "insider_activity_log.json"
MAX_ENTRIES = 100

# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _token_dump_score(governance_token_sales_30d_usd: float,
                      governance_token_mcap_usd: float) -> int:
    """Token dump score 0-30 based on sales as % of market cap."""
    if governance_token_mcap_usd > 0:
        sell_pct = governance_token_sales_30d_usd / governance_token_mcap_usd * 100.0
    else:
        sell_pct = 0.0

    if sell_pct >= 5.0:
        return 30
    elif sell_pct >= 2.0:
        return 25
    elif sell_pct >= 1.0:
        return 18
    elif sell_pct >= 0.5:
        return 10
    elif sell_pct >= 0.1:
        return 4
    else:
        return 0


def _wallet_movement_score(team_wallet_outflows_30d_usd: float,
                            governance_token_mcap_usd: float,
                            treasury_to_team_transfers_30d_usd: float) -> int:
    """Wallet movement score 0-25."""
    if governance_token_mcap_usd > 0:
        outflow_pct = (
            team_wallet_outflows_30d_usd / governance_token_mcap_usd * 100.0
        )
        treasury_pct = (
            treasury_to_team_transfers_30d_usd / governance_token_mcap_usd * 100.0
        )
    else:
        outflow_pct = 0.0
        treasury_pct = 0.0

    # Base outflow score
    if outflow_pct >= 5.0:
        score = 20
    elif outflow_pct >= 2.0:
        score = 15
    elif outflow_pct >= 1.0:
        score = 10
    elif outflow_pct >= 0.5:
        score = 5
    else:
        score = 0

    # Treasury-to-team bonus
    if treasury_pct >= 1.0:
        score += 5
    elif treasury_pct >= 0.5:
        score += 3
    elif treasury_pct >= 0.1:
        score += 1

    return min(score, 25)


def _anomaly_score(unusual_tx_count_7d: int, days_since_last_team_dump: int) -> int:
    """Anomaly score 0-25 from tx count + recency of last dump."""
    # Unusual transaction component
    if unusual_tx_count_7d >= 20:
        tx_score = 15
    elif unusual_tx_count_7d >= 10:
        tx_score = 10
    elif unusual_tx_count_7d >= 5:
        tx_score = 6
    elif unusual_tx_count_7d >= 2:
        tx_score = 3
    else:
        tx_score = 0

    # Dump recency bonus (999 = never → 0)
    if days_since_last_team_dump <= 7:
        dump_bonus = 10
    elif days_since_last_team_dump <= 30:
        dump_bonus = 7
    elif days_since_last_team_dump <= 90:
        dump_bonus = 4
    elif days_since_last_team_dump <= 180:
        dump_bonus = 2
    else:
        dump_bonus = 0

    return min(tx_score + dump_bonus, 25)


def _correlation_score(token_price_change_30d_pct: float,
                       dump_score: int,
                       wallet_score: int) -> int:
    """Correlation score 0-20: selling while price drops is a worse signal."""
    if token_price_change_30d_pct <= -30.0 and (dump_score > 0 or wallet_score > 10):
        return 20
    elif token_price_change_30d_pct <= -15.0 and dump_score > 0:
        return 15
    elif token_price_change_30d_pct <= -5.0 and dump_score > 0:
        return 8
    elif token_price_change_30d_pct > 0.0 and dump_score > 15:
        return 5  # selling into a pump
    else:
        return 0


def _risk_label(score: int) -> str:
    """Map insider risk score 0-100 to risk label."""
    if score >= 75:
        return "EXIT"
    elif score >= 55:
        return "RED_FLAG"
    elif score >= 35:
        return "SUSPICIOUS"
    elif score >= 15:
        return "WATCH"
    else:
        return "CLEAN"


def _build_red_flags(
    name: str,
    governance_token_sales_30d_usd: float,
    governance_token_mcap_usd: float,
    treasury_to_team_transfers_30d_usd: float,
    unusual_tx_count_7d: int,
    days_since_last_team_dump: int,
    token_price_change_30d_pct: float,
    dump_score: int,
    team_token_holdings_pct: float,
    team_wallet_outflows_30d_usd: float,
) -> list:
    """Build list of triggered red flags."""
    flags = []

    if (governance_token_mcap_usd > 0 and
            governance_token_sales_30d_usd > governance_token_mcap_usd * 0.01):
        flags.append("Significant governance token sales")

    if treasury_to_team_transfers_30d_usd > 100_000.0:
        flags.append("Large treasury-to-team transfers")

    if unusual_tx_count_7d >= 10:
        flags.append("High anomalous transaction count")

    if days_since_last_team_dump <= 30:
        flags.append("Recent team token dump")

    if token_price_change_30d_pct <= -20.0 and dump_score >= 10:
        flags.append("Selling during price decline")

    if team_token_holdings_pct <= 5.0 and team_wallet_outflows_30d_usd > 50_000.0:
        flags.append("Team reducing remaining position")

    return flags if flags else ["No significant red flags detected"]


def _build_recommendation(name: str, label: str) -> str:
    """Build protocol-level recommendation string."""
    if label == "EXIT":
        return f"EXIT {name}. Multiple insider red flags. Team selling heavily."
    elif label == "RED_FLAG":
        return f"HIGH RISK: Insider activity detected in {name}. Reduce exposure."
    elif label == "SUSPICIOUS":
        return f"Suspicious patterns in {name}. Monitor closely before adding exposure."
    elif label == "WATCH":
        return f"Minor signals in {name}. Watch for escalation."
    else:
        return f"{name} shows no significant insider selling signals."


# ---------------------------------------------------------------------------
# Per-protocol analysis
# ---------------------------------------------------------------------------

def _analyze_protocol(protocol: dict) -> dict:
    """Compute insider activity risk for a single protocol dict."""
    name = str(protocol.get("name", "unknown"))
    outflows = float(protocol.get("team_wallet_outflows_30d_usd", 0.0))
    team_holdings_pct = float(protocol.get("team_token_holdings_pct", 0.0))
    gov_sales = float(protocol.get("governance_token_sales_30d_usd", 0.0))
    mcap = float(protocol.get("governance_token_mcap_usd", 0.0))
    unusual_tx = int(protocol.get("unusual_tx_count_7d", 0))
    treasury_transfers = float(protocol.get("treasury_to_team_transfers_30d_usd", 0.0))
    days_dump = int(protocol.get("days_since_last_team_dump", 999))
    price_change = float(protocol.get("token_price_change_30d_pct", 0.0))

    # Scores
    dump_score = _token_dump_score(gov_sales, mcap)
    wallet_score = _wallet_movement_score(outflows, mcap, treasury_transfers)
    anom_score = _anomaly_score(unusual_tx, days_dump)
    corr_score = _correlation_score(price_change, dump_score, wallet_score)

    insider_risk_score = min(100, dump_score + wallet_score + anom_score + corr_score)
    label = _risk_label(insider_risk_score)

    outflow_intensity_pct = (outflows / mcap * 100.0) if mcap > 0 else 0.0

    red_flags = _build_red_flags(
        name, gov_sales, mcap, treasury_transfers, unusual_tx,
        days_dump, price_change, dump_score, team_holdings_pct, outflows,
    )
    recommendation = _build_recommendation(name, label)

    return {
        "name": name,
        "insider_risk_score": insider_risk_score,
        "risk_label": label,
        "outflow_intensity_pct": outflow_intensity_pct,
        "token_dump_score": dump_score,
        "wallet_movement_score": wallet_score,
        "anomaly_score": anom_score,
        "correlation_score": corr_score,
        "red_flags": red_flags,
        "recommendation": recommendation,
    }


# ---------------------------------------------------------------------------
# Log helpers
# ---------------------------------------------------------------------------

def _append_log(result: dict, log_file: Path = None) -> None:
    """Append result snapshot to ring-buffer log (atomic write, max 100 entries)."""
    if log_file is None:
        log_file = DATA_FILE

    try:
        if log_file.exists():
            with open(log_file, "r") as fh:
                existing = json.load(fh)
            if not isinstance(existing, list):
                existing = []
        else:
            existing = []
    except Exception:
        existing = []

    existing.append(result)
    if len(existing) > MAX_ENTRIES:
        existing = existing[-MAX_ENTRIES:]

    tmp_path = str(log_file) + ".tmp"
    try:
        os.makedirs(log_file.parent, exist_ok=True)
        with open(tmp_path, "w") as fh:
            json.dump(existing, fh, indent=2)
        os.replace(tmp_path, log_file)
    except Exception:
        pass  # Advisory: never raise on log failure


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(protocols: list, config: dict = None) -> dict:
    """
    Analyze protocols for insider activity red flags.

    Parameters
    ----------
    protocols : list[dict]
        Each dict contains: name, team_wallet_outflows_30d_usd,
        team_token_holdings_pct, governance_token_sales_30d_usd,
        governance_token_mcap_usd, unusual_tx_count_7d,
        treasury_to_team_transfers_30d_usd, days_since_last_team_dump,
        token_price_change_30d_pct.
    config : dict, optional
        Reserved for future use; currently unused.

    Returns
    -------
    dict with per-protocol analysis and aggregate summary.
    """
    if not protocols:
        result = {
            "protocols": [],
            "most_suspicious": None,
            "cleanest_protocol": None,
            "flagged_protocols": [],
            "average_risk_score": 0.0,
            "timestamp": time.time(),
        }
        _append_log(result)
        return result

    analyzed = [_analyze_protocol(p) for p in protocols]

    # Most suspicious / cleanest
    most_suspicious_p = max(analyzed, key=lambda p: p["insider_risk_score"])
    cleanest_p = min(analyzed, key=lambda p: p["insider_risk_score"])

    # Flagged protocols
    flagged = [
        p["name"]
        for p in analyzed
        if p["risk_label"] in ("SUSPICIOUS", "RED_FLAG", "EXIT")
    ]

    average_score = sum(p["insider_risk_score"] for p in analyzed) / len(analyzed)

    result = {
        "protocols": analyzed,
        "most_suspicious": most_suspicious_p["name"],
        "cleanest_protocol": cleanest_p["name"],
        "flagged_protocols": flagged,
        "average_risk_score": average_score,
        "timestamp": time.time(),
    }

    _append_log(result)
    return result
