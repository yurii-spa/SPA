"""
DecisionLogger — structured audit trail for every agent action.
Writes to agent_decisions table in SQLite.

Every agent that makes a meaningful decision (allocate, pass, rebalance,
alert, hold, report) should call this logger so we can audit why the system
made specific trades or passed on opportunities. Foundation for future
LLM-powered reasoning (v0.16+).

Usage:
    from agents.decision_logger import DecisionLogger

    logger = DecisionLogger(db_path, 'TraderAgent')
    logger.log_allocate('aave-v3-usdc-ethereum', 40000.0, 4.23, 'T1',
                        'APY in range, TVL sufficient', risk_approved=True)
    logger.log_pass('euler-v2-usdc-ethereum', 'APY 0.8% below minimum 1.0%')
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.init_db import get_connection, get_db_path

log = logging.getLogger(__name__)

POLICY_VERSION = "v1.0"


class DecisionLogger:
    """
    Structured audit trail logger. Writes every agent reasoning step to SQLite.

    Designed to be robust — all DB operations are wrapped in try/except so that
    a logging failure NEVER propagates into business logic.
    """

    def __init__(
        self,
        db_path: "Path | str | None" = None,
        agent_name: str = "UnknownAgent",
        strategy_id: str = "paper-v1",
    ):
        self.db_path = Path(db_path) if db_path else get_db_path()
        self.agent_name = agent_name
        self.strategy_id = strategy_id

    # ── Core log method ──────────────────────────────────────────────────────

    def log(
        self,
        decision_type: str,
        reasoning: str,
        protocol_key: str = None,
        amount_usd: float = None,
        data_snapshot: dict = None,
        risk_check_result: str = None,
        outcome: str = None,
    ) -> int:
        """
        Write one decision record to agent_decisions.

        Returns the inserted row id, or -1 on failure (never raises).
        """
        try:
            ts = datetime.now(timezone.utc).isoformat()
            snapshot_str: Optional[str] = None
            if data_snapshot is not None:
                try:
                    snapshot_str = json.dumps(data_snapshot, default=str)
                except Exception:
                    snapshot_str = str(data_snapshot)

            with get_connection(self.db_path) as conn:
                cursor = conn.execute("""
                    INSERT INTO agent_decisions
                        (timestamp, agent_name, decision_type, protocol_key,
                         amount_usd, reasoning, data_snapshot,
                         policy_version, strategy_id,
                         risk_check_result, outcome)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    ts,
                    self.agent_name,
                    decision_type,
                    protocol_key,
                    amount_usd,
                    reasoning,
                    snapshot_str,
                    POLICY_VERSION,
                    self.strategy_id,
                    risk_check_result,
                    outcome,
                ))
                conn.commit()
                row_id = cursor.lastrowid

            log.debug(
                f"[DecisionLogger] {self.agent_name} {decision_type} "
                f"proto={protocol_key} id={row_id}"
            )
            return row_id

        except Exception as exc:
            log.error(f"[DecisionLogger] Failed to write decision: {exc}", exc_info=True)
            return -1

    # ── Typed convenience methods ────────────────────────────────────────────

    def log_allocate(
        self,
        protocol_key: str,
        amount_usd: float,
        apy: float,
        tier: str,
        reasoning: str,
        risk_approved: bool,
    ) -> int:
        """Log an ALLOCATE decision (position opened or attempted)."""
        risk_result = "APPROVED" if risk_approved else "REJECTED"
        data = {
            "apy": round(apy, 4),
            "tier": tier,
            "amount_usd": round(amount_usd, 2),
        }
        return self.log(
            decision_type="ALLOCATE",
            reasoning=reasoning,
            protocol_key=protocol_key,
            amount_usd=amount_usd,
            data_snapshot=data,
            risk_check_result=risk_result,
            outcome="EXECUTED" if risk_approved else "SKIPPED",
        )

    def log_pass(
        self,
        protocol_key: str,
        reason: str,
        apy: float = None,
        data: dict = None,
    ) -> int:
        """Log a PASS decision (protocol skipped / not traded)."""
        snapshot = dict(data) if data else {}
        if apy is not None:
            snapshot["apy"] = round(apy, 4)
        return self.log(
            decision_type="PASS",
            reasoning=reason,
            protocol_key=protocol_key,
            data_snapshot=snapshot if snapshot else None,
            outcome="SKIPPED",
        )

    def log_rebalance(
        self,
        from_protocol: str,
        to_protocol: str,
        amount_usd: float,
        reasoning: str,
    ) -> int:
        """Log a REBALANCE decision (capital moved between protocols)."""
        data = {
            "from_protocol": from_protocol,
            "to_protocol": to_protocol,
            "amount_usd": round(amount_usd, 2),
        }
        return self.log(
            decision_type="REBALANCE",
            reasoning=reasoning,
            protocol_key=from_protocol,
            amount_usd=amount_usd,
            data_snapshot=data,
            outcome="EXECUTED",
        )

    def log_alert(
        self,
        alert_type: str,
        severity: str,
        details: dict,
    ) -> int:
        """Log an ALERT decision (RiskAgent or AlertEngine raised a flag)."""
        reasoning = f"Alert [{severity}] {alert_type}: {details.get('message', '')}"
        data = {"alert_type": alert_type, "severity": severity, **details}
        return self.log(
            decision_type="ALERT",
            reasoning=reasoning,
            data_snapshot=data,
        )

    def log_hold(
        self,
        protocol_key: str,
        reasoning: str,
        current_apy: float,
    ) -> int:
        """Log a HOLD decision (position kept open, no action taken)."""
        data = {"current_apy": round(current_apy, 4)}
        return self.log(
            decision_type="HOLD",
            reasoning=reasoning,
            protocol_key=protocol_key,
            data_snapshot=data,
            outcome="SKIPPED",
        )

    # ── Query helpers ────────────────────────────────────────────────────────

    def get_recent(self, limit: int = 50) -> list[dict]:
        """
        Return the most recent decisions as a list of dicts.
        data_snapshot is already parsed back to dict (or left as str on error).
        """
        try:
            with get_connection(self.db_path) as conn:
                rows = conn.execute("""
                    SELECT id, timestamp, agent_name, decision_type,
                           protocol_key, amount_usd, reasoning, data_snapshot,
                           policy_version, strategy_id, risk_check_result, outcome
                    FROM agent_decisions
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (limit,)).fetchall()

            result = []
            for row in rows:
                d = dict(row)
                if d.get("data_snapshot"):
                    try:
                        d["data_snapshot"] = json.loads(d["data_snapshot"])
                    except Exception:
                        pass  # keep as raw string
                result.append(d)
            return result

        except Exception as exc:
            log.error(f"[DecisionLogger] get_recent failed: {exc}")
            return []

    def get_by_protocol(self, protocol_key: str, limit: int = 20) -> list[dict]:
        """
        Return recent decisions for a specific protocol.
        data_snapshot is already parsed back to dict.
        """
        try:
            with get_connection(self.db_path) as conn:
                rows = conn.execute("""
                    SELECT id, timestamp, agent_name, decision_type,
                           protocol_key, amount_usd, reasoning, data_snapshot,
                           policy_version, strategy_id, risk_check_result, outcome
                    FROM agent_decisions
                    WHERE protocol_key = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """, (protocol_key, limit)).fetchall()

            result = []
            for row in rows:
                d = dict(row)
                if d.get("data_snapshot"):
                    try:
                        d["data_snapshot"] = json.loads(d["data_snapshot"])
                    except Exception:
                        pass
                result.append(d)
            return result

        except Exception as exc:
            log.error(f"[DecisionLogger] get_by_protocol failed: {exc}")
            return []
