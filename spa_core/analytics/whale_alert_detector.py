"""
MP-695: WhaleAlertDetector
Detect unusual large transactions that could signal major market moves
or protocol-level risks.

Advisory / read-only analytics. Pure stdlib. Atomic writes (os.replace).
"""

from dataclasses import dataclass, field
from typing import List, Optional
import json
import os
import time
from pathlib import Path

DATA_FILE = Path("data/whale_alert_log.json")
MAX_ENTRIES = 200

# Alert thresholds (USD)
THRESHOLDS = {
    "MEGA_WHALE": 10_000_000,   # $10M+
    "WHALE":       1_000_000,   # $1M+
    "LARGE":         100_000,   # $100k+
    "MEDIUM":         10_000,   # $10k+
}


@dataclass
class Transaction:
    tx_id: str
    protocol: str
    tx_type: str          # "DEPOSIT", "WITHDRAW", "SWAP", "LIQUIDATE", "BORROW"
    amount_usd: float
    timestamp: float
    wallet_age_days: int  # 0 = new wallet (more suspicious)
    is_contract: bool     # True if originating from a smart contract


@dataclass
class WhaleAlert:
    tx_id: str
    protocol: str
    tx_type: str
    amount_usd: float
    alert_tier: str       # MEGA_WHALE / WHALE / LARGE / MEDIUM / BELOW_THRESHOLD
    suspicion_score: float  # 0.0–1.0
    flags: List[str]      # list of suspicious indicators
    risk_level: str       # CRITICAL / HIGH / MEDIUM / LOW / INFO
    action: str           # MONITOR / INVESTIGATE / ALERT


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _alert_tier(amount_usd: float) -> str:
    """Classify transaction by USD size."""
    if amount_usd >= THRESHOLDS["MEGA_WHALE"]:
        return "MEGA_WHALE"
    if amount_usd >= THRESHOLDS["WHALE"]:
        return "WHALE"
    if amount_usd >= THRESHOLDS["LARGE"]:
        return "LARGE"
    if amount_usd >= THRESHOLDS["MEDIUM"]:
        return "MEDIUM"
    return "BELOW_THRESHOLD"


def _suspicion_score(tx: Transaction) -> float:
    """Compute suspicion score [0.0, 1.0]."""
    score = 0.1  # base
    if tx.wallet_age_days < 7:
        score += 0.3
    if tx.tx_type == "LIQUIDATE":
        score += 0.2
    if tx.is_contract:
        score += 0.2
    if tx.amount_usd >= THRESHOLDS["MEGA_WHALE"]:
        score += 0.2
    return min(1.0, max(0.0, score))


def _flags(tx: Transaction) -> List[str]:
    """Build list of suspicious-indicator strings."""
    result: List[str] = []
    if tx.wallet_age_days < 7:
        result.append("🆕 New wallet (< 7 days old)")
    if tx.tx_type == "LIQUIDATE":
        result.append("⚡ Liquidation — forced seller")
    if tx.is_contract:
        result.append("🤖 Contract-originated tx — possible MEV/bot")
    if tx.amount_usd >= THRESHOLDS["MEGA_WHALE"]:
        result.append("🐋 MEGA WHALE — market-moving size")
    if tx.amount_usd >= THRESHOLDS["WHALE"] and tx.tx_type == "WITHDRAW":
        result.append("🚨 Large withdrawal — potential exodus signal")
    return result


def _risk_level(tier: str, suspicion: float) -> str:
    """Map tier + suspicion to risk level."""
    if tier == "MEGA_WHALE" and suspicion > 0.5:
        return "CRITICAL"
    if tier in ("MEGA_WHALE", "WHALE") or suspicion > 0.6:
        return "HIGH"
    if tier == "LARGE" or suspicion > 0.3:
        return "MEDIUM"
    if tier == "MEDIUM":
        return "LOW"
    return "INFO"


def _action(risk: str) -> str:
    """Map risk level to recommended action."""
    if risk in ("CRITICAL", "HIGH"):
        return "ALERT"
    if risk == "MEDIUM":
        return "INVESTIGATE"
    return "MONITOR"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect(tx: Transaction) -> Optional[WhaleAlert]:
    """
    Analyse a single transaction and return a WhaleAlert, or None
    if the transaction is BELOW_THRESHOLD with low suspicion.
    """
    tier = _alert_tier(tx.amount_usd)
    suspicion = _suspicion_score(tx)

    # Skip low-signal noise
    if tier == "BELOW_THRESHOLD" and suspicion < 0.3:
        return None

    alert_flags = _flags(tx)
    risk = _risk_level(tier, suspicion)
    act = _action(risk)

    return WhaleAlert(
        tx_id=tx.tx_id,
        protocol=tx.protocol,
        tx_type=tx.tx_type,
        amount_usd=tx.amount_usd,
        alert_tier=tier,
        suspicion_score=suspicion,
        flags=alert_flags,
        risk_level=risk,
        action=act,
    )


def detect_batch(txs: List[Transaction]) -> List[WhaleAlert]:
    """Detect alerts for a list of transactions; filter out None results."""
    results = []
    for tx in txs:
        alert = detect(tx)
        if alert is not None:
            results.append(alert)
    return results


def filter_critical(alerts: List[WhaleAlert]) -> List[WhaleAlert]:
    """Return only CRITICAL-risk alerts."""
    return [a for a in alerts if a.risk_level == "CRITICAL"]


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _alert_to_dict(alert: WhaleAlert) -> dict:
    return {
        "tx_id": alert.tx_id,
        "protocol": alert.protocol,
        "tx_type": alert.tx_type,
        "amount_usd": alert.amount_usd,
        "alert_tier": alert.alert_tier,
        "suspicion_score": alert.suspicion_score,
        "flags": alert.flags,
        "risk_level": alert.risk_level,
        "action": alert.action,
        "_saved_at": time.time(),
    }


def save_results(
    alerts: List[WhaleAlert],
    data_file: Path = DATA_FILE,
    max_entries: int = MAX_ENTRIES,
) -> None:
    """Append alerts to ring-buffer JSON; atomic write via os.replace."""
    data_file = Path(data_file)
    existing = load_history(data_file)

    new_records = [_alert_to_dict(a) for a in alerts]
    combined = existing + new_records

    if len(combined) > max_entries:
        combined = combined[-max_entries:]

    tmp = data_file.with_suffix(".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp, "w") as fh:
        json.dump(combined, fh, indent=2)
    os.replace(tmp, data_file)


def load_history(data_file: Path = DATA_FILE) -> list:
    """Load saved alerts; returns [] if file missing or invalid."""
    data_file = Path(data_file)
    if not data_file.exists():
        return []
    try:
        with open(data_file) as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return []
