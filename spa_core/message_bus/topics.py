"""
SPA Message Bus — Topics & Message dataclass (M4)
"""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


class Topic:
    MARKET_DATA       = "MARKET_DATA"
    HEALTH_ALERT      = "HEALTH_ALERT"
    STRATEGY_SIGNAL   = "STRATEGY_SIGNAL"
    TRADE_DECISION    = "TRADE_DECISION"
    EXECUTION_RESULT  = "EXECUTION_RESULT"
    ARCHITECT_PROPOSAL = "architect.proposal"  # v2.4 (BL-002)
    ALL = (
        MARKET_DATA, HEALTH_ALERT, STRATEGY_SIGNAL,
        TRADE_DECISION, EXECUTION_RESULT, ARCHITECT_PROPOSAL,
    )


class Priority:
    CRITICAL = 1
    HIGH     = 3
    NORMAL   = 5
    LOW      = 8
    BATCH    = 10


@dataclass(frozen=True)
class Message:
    topic:     str
    sender:    str
    payload:   dict
    id:        str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    priority:  int = Priority.NORMAL
    status:    str = "pending"
    consumer:  str | None = None

    def __str__(self) -> str:
        return f"[{self.topic}] {self.sender} → {self.payload}"


def market_data_payload(snapshots: list[dict], fetched_at: str | None = None) -> dict:
    return {
        "snapshots": snapshots,
        "protocol_count": len(snapshots),
        "fetched_at": fetched_at or datetime.now(timezone.utc).isoformat(),
    }


def health_alert_payload(alerts: list[dict], overall_status: str, portfolio: dict | None = None) -> dict:
    return {
        "alerts": alerts,
        "overall_status": overall_status,
        "critical_count": sum(1 for a in alerts if a.get("severity") == "CRITICAL"),
        "warning_count":  sum(1 for a in alerts if a.get("severity") == "WARNING"),
        "portfolio": portfolio or {},
    }


def strategy_signal_payload(recommendations: list[dict], reasoning: str, confidence: float = 0.8) -> dict:
    return {
        "recommendations": recommendations,
        "reasoning": reasoning,
        "confidence": confidence,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def trade_decision_payload(
    protocol_key: str, action: str, amount_usd: float,
    reasoning: str, approved: bool = True, rejection_reason: str | None = None,
) -> dict:
    return {
        "protocol_key": protocol_key, "action": action, "amount_usd": amount_usd,
        "reasoning": reasoning, "approved": approved,
        "rejection_reason": rejection_reason,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def execution_result_payload(
    protocol_key: str, action: str, approved: bool,
    amount_usd: float = 0.0, pnl_usd: float = 0.0,
    rejection_reason: str | None = None, trade_id: str | None = None,
) -> dict:
    return {
        "protocol_key": protocol_key, "action": action, "approved": approved,
        "amount_usd": amount_usd, "pnl_usd": pnl_usd,
        "rejection_reason": rejection_reason, "trade_id": trade_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
