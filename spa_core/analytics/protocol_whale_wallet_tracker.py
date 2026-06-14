"""
MP-915: ProtocolWhaleWalletTracker
Tracks whale wallet activity in DeFi protocols.
Pure stdlib only. Advisory/read-only. Atomic writes.
"""

import json
import os
import time
from pathlib import Path

DATA_FILE = Path("data/whale_tracker_log.json")
MAX_ENTRIES = 100


class ProtocolWhaleWalletTracker:
    """
    Tracks whale wallet activity across DeFi protocols.
    Each wallet dict must have:
        address, protocol, position_usd, entry_price_usd, current_price_usd,
        unrealized_pnl_usd, days_held, transaction_count_30d,
        last_action (deposit/withdraw/borrow/claim),
        last_action_days_ago, wallet_label (whale/shark/dolphin)
    """

    def __init__(self, data_file: Path = DATA_FILE):
        self.data_file = Path(data_file)

    # ------------------------------------------------------------------
    # Internal calculations
    # ------------------------------------------------------------------

    def _compute_pnl_pct(self, wallet: dict) -> float:
        entry_price = wallet.get("entry_price_usd", 0.0)
        current_price = wallet.get("current_price_usd", 0.0)
        if entry_price <= 0:
            return 0.0
        return round((current_price - entry_price) / entry_price * 100.0, 4)

    def _compute_holding_strength_score(self, wallet: dict) -> float:
        """
        0-100: combination of position size, holding duration, recent activity.
        Higher score = stronger holder.
        """
        position_usd = wallet.get("position_usd", 0.0)
        days_held = wallet.get("days_held", 0)
        tx_count_30d = wallet.get("transaction_count_30d", 0)
        last_action_days_ago = wallet.get("last_action_days_ago", 0)

        # Size: $0 → 0, $10M+ → 100
        size_score = min(100.0, position_usd / 10_000_000.0 * 100.0)

        # Duration: 0 days → 0, 365+ days → 100
        duration_score = min(100.0, days_held / 365.0 * 100.0)

        # Activity: mix of tx count and recency
        tx_score = min(50.0, tx_count_30d / 30.0 * 50.0)
        recency_score = max(0.0, 50.0 - last_action_days_ago * 1.5)
        activity_score = min(100.0, tx_score + recency_score)

        score = (
            size_score * 0.40
            + duration_score * 0.35
            + activity_score * 0.25
        )
        return round(max(0.0, min(100.0, score)), 2)

    def _compute_exit_risk_score(self, wallet: dict) -> float:
        """
        0-100: high inactivity + large unrealized profit = higher exit risk.
        """
        pnl_pct = self._compute_pnl_pct(wallet)
        last_action_days_ago = wallet.get("last_action_days_ago", 0)
        tx_count_30d = wallet.get("transaction_count_30d", 0)
        last_action = wallet.get("last_action", "")

        # Profit-taking risk: 0% pnl → 0, 100% pnl → 60
        pnl_risk = min(60.0, max(0.0, pnl_pct / 100.0 * 60.0))

        # Inactivity risk: 0 days → 0, 26+ days → 40
        inactivity_risk = min(40.0, last_action_days_ago * 1.5)

        # Low tx: 0 tx → 10, 20+ tx → 0
        tx_risk = max(0.0, 10.0 - tx_count_30d * 0.5)

        # Withdraw/claim action signal
        action_risk = 20.0 if last_action in ("withdraw", "claim") else 0.0

        score = pnl_risk + inactivity_risk + tx_risk + action_risk
        return round(max(0.0, min(100.0, score)), 2)

    def _get_activity_label(self, wallet: dict) -> str:
        last_action = wallet.get("last_action", "")
        last_action_days_ago = wallet.get("last_action_days_ago", 0)
        tx_count_30d = wallet.get("transaction_count_30d", 0)

        if last_action_days_ago > 30:
            return "INACTIVE"
        if last_action == "withdraw":
            if tx_count_30d > 5:
                return "REDUCING"
            return "EXITING"
        if last_action in ("deposit", "borrow"):
            if tx_count_30d > 10:
                return "ACCUMULATING"
            return "HOLDING"
        # claim and anything else
        return "HOLDING"

    def _compute_flags(self, wallet: dict, pnl_pct: float) -> list:
        flags = []
        position_usd = wallet.get("position_usd", 0.0)
        last_action_days_ago = wallet.get("last_action_days_ago", 0)
        days_held = wallet.get("days_held", 0)
        tx_count_30d = wallet.get("transaction_count_30d", 0)

        if pnl_pct > 50.0:
            flags.append("LARGE_UNREALIZED_PROFIT")
        if last_action_days_ago > 30 and position_usd > 1_000_000:
            flags.append("INACTIVE_WHALE")
        if days_held < 7:
            flags.append("RECENT_ENTRY")
        if tx_count_30d > 50:
            flags.append("HIGH_CHURN")
        return flags

    def _analyze_wallet(self, wallet: dict) -> dict:
        pnl_pct = self._compute_pnl_pct(wallet)
        holding_strength_score = self._compute_holding_strength_score(wallet)
        exit_risk_score = self._compute_exit_risk_score(wallet)
        activity_label = self._get_activity_label(wallet)
        flags = self._compute_flags(wallet, pnl_pct)

        return {
            "address": wallet.get("address", ""),
            "protocol": wallet.get("protocol", ""),
            "position_usd": wallet.get("position_usd", 0.0),
            "entry_price_usd": wallet.get("entry_price_usd", 0.0),
            "current_price_usd": wallet.get("current_price_usd", 0.0),
            "unrealized_pnl_usd": wallet.get("unrealized_pnl_usd", 0.0),
            "days_held": wallet.get("days_held", 0),
            "transaction_count_30d": wallet.get("transaction_count_30d", 0),
            "last_action": wallet.get("last_action", ""),
            "last_action_days_ago": wallet.get("last_action_days_ago", 0),
            "wallet_label": wallet.get("wallet_label", ""),
            "pnl_pct": pnl_pct,
            "holding_strength_score": holding_strength_score,
            "exit_risk_score": exit_risk_score,
            "activity_label": activity_label,
            "flags": flags,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def track(self, wallets: list, config: dict) -> dict:
        """
        Track whale wallet activity and return analysis.

        Returns dict with:
            timestamp, wallet_count, wallets (list of analyzed),
            aggregates: { largest_position, highest_exit_risk,
                          total_whale_tvl_usd, average_pnl_pct,
                          accumulating_count }
        """
        if not wallets:
            return {
                "timestamp": time.time(),
                "wallet_count": 0,
                "wallets": [],
                "aggregates": {
                    "largest_position": None,
                    "highest_exit_risk": None,
                    "total_whale_tvl_usd": 0.0,
                    "average_pnl_pct": 0.0,
                    "accumulating_count": 0,
                },
            }

        analyzed = [self._analyze_wallet(w) for w in wallets]

        largest = max(analyzed, key=lambda x: x["position_usd"])
        highest_exit = max(analyzed, key=lambda x: x["exit_risk_score"])
        total_tvl = sum(w["position_usd"] for w in analyzed)
        avg_pnl = sum(w["pnl_pct"] for w in analyzed) / len(analyzed)
        accumulating_count = sum(
            1 for w in analyzed if w["activity_label"] == "ACCUMULATING"
        )

        result = {
            "timestamp": time.time(),
            "wallet_count": len(analyzed),
            "wallets": analyzed,
            "aggregates": {
                "largest_position": largest["address"],
                "highest_exit_risk": highest_exit["address"],
                "total_whale_tvl_usd": round(total_tvl, 2),
                "average_pnl_pct": round(avg_pnl, 4),
                "accumulating_count": accumulating_count,
            },
        }

        self._append_log(result)
        return result

    # ------------------------------------------------------------------
    # Ring-buffer log (atomic write)
    # ------------------------------------------------------------------

    def _append_log(self, result: dict) -> None:
        log_entry = {
            "timestamp": result["timestamp"],
            "wallet_count": result["wallet_count"],
            "aggregates": result["aggregates"],
        }
        try:
            if self.data_file.exists():
                with open(self.data_file) as f:
                    log = json.load(f)
            else:
                log = []
        except (json.JSONDecodeError, OSError):
            log = []

        log.append(log_entry)
        if len(log) > MAX_ENTRIES:
            log = log[-MAX_ENTRIES:]

        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(self.data_file) + ".tmp"
        with open(tmp, "w") as f:
            json.dump(log, f, indent=2)
        os.replace(tmp, str(self.data_file))
