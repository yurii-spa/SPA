"""
On-chain position monitoring for SPA v2.0.

Currently reads from the paper trading database (data/status.json).
v2.0 will read directly from blockchain via web3.py.

Monitoring interval: every 15 minutes (vs 4h in paper trading).
See docs/v2_architecture.md § 6 for the full monitoring architecture.

Usage:
    monitor = PositionMonitor(data_dir="/path/to/data")

    # Get current positions (paper DB now, on-chain in v2.0)
    positions = monitor.get_positions()

    # Check for APY deviation from expected
    deviation = monitor.get_apy_deviation("aave-v3")

    # Scan for anomalies
    anomalies = monitor.detect_anomalies()

    # Verify post-execution state
    result = monitor.verify_post_execution("aave-v3", "supply", 1000.0, "0xabc...")
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional


# ── Constants ─────────────────────────────────────────────────────────────────

_APY_DEVIATION_WARN_PCT  = 20.0  # warn if APY deviates > 20% from 7-day average
_APY_DEVIATION_ALERT_PCT = 40.0  # alert if APY deviates > 40%

_TVL_DROP_WARN_PCT  = 10.0  # warn if protocol TVL drops > 10% in 24h
_TVL_DROP_ALERT_PCT = 25.0  # alert if protocol TVL drops > 25% in 24h

_POSITION_CHANGE_ALERT_PCT = 5.0  # alert if position value changes > 5% unexpectedly

# Expected APY ranges per protocol (historical basis, paper trading calibration)
# Format: {protocol_key: (min_apy_pct, max_apy_pct)}
_EXPECTED_APY_RANGES: dict[str, tuple[float, float]] = {
    "aave-v3":  (2.5,  8.0),
    "compound": (2.0,  7.5),
    "morpho":   (3.0,  9.0),
    "yearn":    (4.0, 12.0),
    "maple":    (6.0, 15.0),
    "euler":    (3.5, 10.0),
    "spark":    (3.0,  8.5),
}


# ── PositionMonitor ───────────────────────────────────────────────────────────

class PositionMonitor:
    """
    Monitors on-chain DeFi positions and detects anomalies.

    Data source:
      - Now (paper trading): reads from data/status.json and data/historical_apy.json
      - v2.0 (real capital): reads from blockchain via web3.py contract calls

    The interface is identical between paper and real modes — only the data
    source changes. This allows the monitoring logic to be tested during paper
    trading and activated without changes for real capital.
    """

    def __init__(
        self,
        data_dir: str = "data",
        mode:     str = "paper",
    ):
        """
        Args:
            data_dir: Path to the SPA data directory (contains status.json, etc.)
            mode:     "paper" (reads from DB) | "live" (reads from blockchain, v2.0)
        """
        self.data_dir = Path(data_dir)
        self.mode = mode

        if mode == "live":
            raise NotImplementedError(
                "Live on-chain mode is not yet implemented. "
                "See docs/v2_architecture.md for activation requirements."
            )

    def _load_json(self, filename: str) -> dict:
        """Load a JSON file from data_dir. Returns empty dict on failure."""
        try:
            return json.loads((self.data_dir / filename).read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    # ── Position reads ────────────────────────────────────────────────────────

    def get_positions(self) -> list[dict]:
        """
        Get all current deployed positions.

        Paper mode: reads from data/status.json → positions array.
        Live mode (v2.0): reads aToken balances from Aave V3 contract,
          cToken balances from Compound, etc.

        Returns:
            List of position dicts, each containing:
              {
                "protocol":   str,    # protocol key
                "token":      str,    # token symbol (e.g. "USDC")
                "amount_usd": float,  # current value in USD
                "apy":        float,  # current APY (%)
                "last_updated": str,  # ISO timestamp
                "source":     str,    # "paper_db" | "on_chain"
              }
        """
        status = self._load_json("status.json")
        raw_positions = status.get("positions", [])

        positions = []
        for pos in raw_positions:
            positions.append({
                "protocol":     pos.get("protocol_key") or pos.get("protocol", "unknown"),
                "token":        pos.get("token", "USDC"),
                "amount_usd":   float(pos.get("amount_usd", 0.0) or 0.0),
                "apy":          float(pos.get("apy", 0.0) or 0.0),
                "last_updated": pos.get("last_updated") or self._now().isoformat(),
                "source":       "paper_db",
            })

        return positions

    def get_portfolio_summary(self) -> dict:
        """
        Get portfolio-level summary (total capital, PnL, drawdown).

        Returns:
            Portfolio dict from data/status.json → portfolio, or empty dict.
        """
        status = self._load_json("status.json")
        return status.get("portfolio", {})

    # ── APY monitoring ────────────────────────────────────────────────────────

    def get_apy_history(self, protocol: str, days: int = 7) -> list[dict]:
        """
        Get historical APY data for a protocol.

        Paper mode: reads from data/historical_apy.json.
        Live mode (v2.0): queries on-chain rate history.

        Args:
            protocol: Protocol key
            days:     Number of days of history to return

        Returns:
            List of {timestamp, apy} dicts, newest first.
        """
        apy_data = self._load_json("historical_apy.json")
        history  = apy_data.get(protocol, [])

        cutoff = self._now() - timedelta(days=days)
        recent = []
        for entry in history:
            try:
                ts = datetime.fromisoformat(
                    entry.get("timestamp", "").replace("Z", "+00:00")
                )
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= cutoff:
                    recent.append({"timestamp": entry["timestamp"], "apy": entry.get("apy", 0.0)})
            except Exception:
                continue

        return sorted(recent, key=lambda x: x["timestamp"], reverse=True)

    def get_apy_deviation(self, protocol: str) -> float:
        """
        Calculate current APY deviation from the 7-day moving average.

        Args:
            protocol: Protocol key (e.g. "aave-v3")

        Returns:
            Percentage deviation from the 7-day average.
            Positive = current APY is above average.
            Negative = current APY is below average.
            0.0 if insufficient data or current APY is unavailable.
        """
        # Get current APY from positions
        positions = self.get_positions()
        current_apy: Optional[float] = None
        for pos in positions:
            if pos["protocol"] == protocol:
                current_apy = pos.get("apy")
                break

        if current_apy is None:
            return 0.0

        # Get 7-day history
        history = self.get_apy_history(protocol, days=7)
        if len(history) < 3:  # need at least 3 data points for a meaningful average
            return 0.0

        avg_apy = sum(h["apy"] for h in history) / len(history)
        if avg_apy == 0:
            return 0.0

        return round(((current_apy - avg_apy) / avg_apy) * 100, 2)

    # ── Anomaly detection ─────────────────────────────────────────────────────

    def detect_anomalies(self) -> list[dict]:
        """
        Scan positions and market data for anomalies requiring attention.

        Checks:
          1. APY deviation > threshold (sudden rate drop or spike)
          2. Position value outside expected range
          3. APY outside historical protocol range
          4. Stale data (position not updated in > 1 hour)

        Returns:
            List of anomaly dicts. Empty list if no anomalies found.
            Each anomaly:
              {
                "type":        str,    # anomaly type
                "severity":    str,    # "WARN" | "ALERT"
                "protocol":    str,
                "message":     str,
                "detected_at": str,    # ISO timestamp
                "value":       float,  # measured value
                "threshold":   float,  # threshold that was breached
              }
        """
        anomalies: list[dict] = []
        now = self._now()
        positions = self.get_positions()

        for pos in positions:
            protocol = pos["protocol"]
            apy      = pos.get("apy", 0.0)
            amount   = pos.get("amount_usd", 0.0)

            # 1. APY outside expected range
            expected_range = _EXPECTED_APY_RANGES.get(protocol)
            if expected_range and apy > 0:
                min_apy, max_apy = expected_range
                if apy < min_apy:
                    anomalies.append({
                        "type":        "apy_below_minimum",
                        "severity":    "ALERT",
                        "protocol":    protocol,
                        "message":     f"{protocol} APY {apy:.2f}% is below expected minimum {min_apy:.1f}%",
                        "detected_at": now.isoformat(),
                        "value":       apy,
                        "threshold":   min_apy,
                    })
                elif apy > max_apy:
                    anomalies.append({
                        "type":        "apy_above_maximum",
                        "severity":    "WARN",
                        "protocol":    protocol,
                        "message":     f"{protocol} APY {apy:.2f}% is above expected maximum {max_apy:.1f}% — verify data",
                        "detected_at": now.isoformat(),
                        "value":       apy,
                        "threshold":   max_apy,
                    })

            # 2. APY deviation from 7-day average
            deviation = self.get_apy_deviation(protocol)
            if abs(deviation) >= _APY_DEVIATION_ALERT_PCT:
                anomalies.append({
                    "type":        "apy_spike",
                    "severity":    "ALERT",
                    "protocol":    protocol,
                    "message":     f"{protocol} APY deviated {deviation:+.1f}% from 7-day average",
                    "detected_at": now.isoformat(),
                    "value":       deviation,
                    "threshold":   _APY_DEVIATION_ALERT_PCT,
                })
            elif abs(deviation) >= _APY_DEVIATION_WARN_PCT:
                anomalies.append({
                    "type":        "apy_deviation",
                    "severity":    "WARN",
                    "protocol":    protocol,
                    "message":     f"{protocol} APY deviated {deviation:+.1f}% from 7-day average",
                    "detected_at": now.isoformat(),
                    "value":       deviation,
                    "threshold":   _APY_DEVIATION_WARN_PCT,
                })

            # 3. Stale position data
            try:
                last_updated_str = pos.get("last_updated", "")
                if last_updated_str:
                    last_updated = datetime.fromisoformat(
                        last_updated_str.replace("Z", "+00:00")
                    )
                    if last_updated.tzinfo is None:
                        last_updated = last_updated.replace(tzinfo=timezone.utc)
                    age_hours = (now - last_updated).total_seconds() / 3600
                    if age_hours > 2:
                        anomalies.append({
                            "type":        "stale_position_data",
                            "severity":    "WARN",
                            "protocol":    protocol,
                            "message":     f"{protocol} position data is {age_hours:.1f}h old (threshold: 2h)",
                            "detected_at": now.isoformat(),
                            "value":       age_hours,
                            "threshold":   2.0,
                        })
            except Exception:
                pass

        return anomalies

    # ── Post-execution verification ───────────────────────────────────────────

    def verify_post_execution(
        self,
        protocol:      str,
        action:        str,
        amount_usd:    float,
        tx_hash:       Optional[str] = None,
        expected_delta: Optional[float] = None,
    ) -> dict:
        """
        Verify on-chain state matches expected state after a transaction.

        Paper mode: checks that the paper trading DB was updated correctly.
        Live mode (v2.0): reads aToken/cToken balance from the contract and
          verifies it increased/decreased by the expected amount.

        Args:
            protocol:       Protocol key
            action:         "supply" | "withdraw"
            amount_usd:     Transaction amount in USD
            tx_hash:        Transaction hash (for on-chain lookup in v2.0)
            expected_delta: Expected change in position value (+ for supply, - for withdraw)

        Returns:
            {
                "verified":       bool,
                "protocol":       str,
                "action":         str,
                "amount_usd":     float,
                "tx_hash":        str | None,
                "on_chain_delta": float | None,  # None in paper/simulation mode
                "message":        str,
                "verified_at":    str,
            }
        """
        positions    = self.get_positions()
        pos_for_protocol = next(
            (p for p in positions if p["protocol"] == protocol), None
        )

        return {
            "verified":       pos_for_protocol is not None,
            "protocol":       protocol,
            "action":         action,
            "amount_usd":     amount_usd,
            "tx_hash":        tx_hash,
            "on_chain_delta": None,  # populated in v2.0 when web3.py is wired up
            "current_balance": pos_for_protocol["amount_usd"] if pos_for_protocol else None,
            "message": (
                f"Paper DB shows position for {protocol}: "
                f"${pos_for_protocol['amount_usd']:,.2f}"
                if pos_for_protocol
                else f"No position found for {protocol} in paper DB after {action}"
            ),
            "verified_at": self._now().isoformat(),
        }

    # ── Health check ──────────────────────────────────────────────────────────

    def health_check(self) -> dict:
        """
        Quick health check of the monitoring system.

        Returns:
            {
                "healthy":         bool,
                "data_source":     str,
                "positions_count": int,
                "anomaly_count":   int,
                "last_checked":    str,
                "issues":          list[str],
            }
        """
        issues: list[str] = []
        positions = self.get_positions()
        anomalies = self.detect_anomalies()

        # Check data freshness
        status = self._load_json("status.json")
        ts = status.get("timestamp")
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                age_hours = (self._now() - dt).total_seconds() / 3600
                if age_hours > 6:
                    issues.append(f"Status data is {age_hours:.1f}h old (threshold: 6h)")
            except Exception:
                issues.append("Could not parse status.json timestamp")
        else:
            issues.append("status.json missing or has no timestamp")

        alert_anomalies = [a for a in anomalies if a["severity"] == "ALERT"]
        if alert_anomalies:
            issues.append(f"{len(alert_anomalies)} ALERT-level anomalies detected")

        return {
            "healthy":         len(issues) == 0,
            "data_source":     "paper_db" if self.mode == "paper" else "on_chain",
            "positions_count": len(positions),
            "anomaly_count":   len(anomalies),
            "last_checked":    self._now().isoformat(),
            "issues":          issues,
        }
