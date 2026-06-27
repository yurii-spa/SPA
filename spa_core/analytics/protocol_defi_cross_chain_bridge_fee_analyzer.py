"""
MP-1095: ProtocolDeFiCrossChainBridgeFeeAnalyzer
Calculates the true cost of bridging assets cross-chain for yield farming,
including bridge fees, destination gas, time cost (opportunity cost during
bridge time), and net APY impact.

Pure stdlib, read-only analytics, atomic ring-buffer log (cap 100).
"""

import json
import os
from spa_core.utils import clock

# --------------------------------------------------------------------------- #
# Log config
# --------------------------------------------------------------------------- #
_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "cross_chain_bridge_fee_log.json"
)
_LOG_CAP = 100

# --------------------------------------------------------------------------- #
# Bridge labels
# --------------------------------------------------------------------------- #
LABEL_EFFICIENT_BRIDGE    = "EFFICIENT_BRIDGE"
LABEL_ACCEPTABLE_COST     = "ACCEPTABLE_COST"
LABEL_HIGH_BRIDGE_COST    = "HIGH_BRIDGE_COST"
LABEL_INEFFICIENT_BRIDGE  = "INEFFICIENT_BRIDGE"
LABEL_BRIDGE_NOT_WORTH_IT = "BRIDGE_NOT_WORTH_IT"

# --------------------------------------------------------------------------- #
# Scoring thresholds
# --------------------------------------------------------------------------- #
_BREAKEVEN_EFFICIENT   = 3.0   # days
_BREAKEVEN_ACCEPTABLE  = 7.0   # days
_BREAKEVEN_HIGH        = 14.0  # days
_BREAKEVEN_INEFFICIENT = 30.0  # days

# Large sentinel for "infinite" breakeven (no APY advantage)
_BREAKEVEN_INF = 9_999.0

# Minutes per year (used for opportunity cost)
_MINUTES_PER_YEAR = 365.0 * 24.0 * 60.0

# Days per year
_DAYS_PER_YEAR = 365.0


# --------------------------------------------------------------------------- #
# Pure helpers (importable for testing)
# --------------------------------------------------------------------------- #

def compute_total_bridge_cost_usd(
    bridge_fee_pct: float,
    bridge_fee_fixed_usd: float,
    destination_gas_usd: float,
    source_gas_usd: float,
    position_size_usd: float,
) -> float:
    """
    Total bridge cost in USD = percentage fee + fixed fee + destination gas + source gas.
    bridge_fee_pct is applied to position_size_usd.
    Position size is floored at 0 for the percentage component.
    """
    pct_fee = max(bridge_fee_pct, 0.0) / 100.0 * max(position_size_usd, 0.0)
    fixed   = max(bridge_fee_fixed_usd, 0.0)
    dst_gas = max(destination_gas_usd, 0.0)
    src_gas = max(source_gas_usd, 0.0)
    total   = pct_fee + fixed + dst_gas + src_gas
    return round(total, 6)


def compute_total_bridge_cost_pct(
    total_bridge_cost_usd: float,
    position_size_usd: float,
) -> float:
    """
    Bridge cost as a percentage of position size.
    Returns 0.0 if position_size_usd <= 0.
    """
    if position_size_usd <= 0:
        return 0.0
    return round(total_bridge_cost_usd / position_size_usd * 100.0, 6)


def compute_opportunity_cost_usd(
    position_size_usd: float,
    source_apy_pct: float,
    bridge_time_minutes: int,
) -> float:
    """
    Yield foregone on the source chain during bridge transit time.
    Formula: position_size * (source_apy / 100) * (bridge_time_minutes / minutes_per_year)
    Both position_size and source_apy are floored at 0 (no negative opportunity cost).
    """
    pos  = max(position_size_usd, 0.0)
    apy  = max(source_apy_pct,   0.0) / 100.0
    mins = max(bridge_time_minutes, 0)
    cost = pos * apy * (mins / _MINUTES_PER_YEAR)
    return round(cost, 6)


def compute_net_apy_advantage_pct(
    target_apy_pct: float,
    source_apy_pct: float,
) -> float:
    """Net APY advantage = target APY minus source APY (can be negative)."""
    return round(target_apy_pct - source_apy_pct, 6)


def compute_breakeven_days(
    total_bridge_cost_usd: float,
    position_size_usd: float,
    net_apy_advantage_pct: float,
) -> float:
    """
    Days of higher yield needed to recover the total bridge cost.

    Formula: (total_bridge_cost_usd / position_size_usd) / (net_apy_advantage_pct / 100)
             * 365

    Returns _BREAKEVEN_INF (9_999.0) if:
      - net_apy_advantage_pct <= 0  (no advantage — never breaks even)
      - position_size_usd <= 0      (undefined)
      - total_bridge_cost_usd <= 0  (free bridge → 0 days)
    """
    if position_size_usd <= 0:
        return _BREAKEVEN_INF if net_apy_advantage_pct <= 0 else _BREAKEVEN_INF
    if net_apy_advantage_pct <= 0:
        return _BREAKEVEN_INF
    if total_bridge_cost_usd <= 0:
        return 0.0
    days = (total_bridge_cost_usd / position_size_usd) / (net_apy_advantage_pct / 100.0) * _DAYS_PER_YEAR
    return round(min(days, _BREAKEVEN_INF), 6)


def compute_bridge_efficiency_score(
    breakeven_days: float,
    net_apy_advantage_pct: float,
) -> int:
    """
    Bridge efficiency score (int 0-100).
    Score = max(0, 100 - breakeven_days * 2)
    If net_apy_advantage_pct <= 0 → score = 0.
    BRIDGE_NOT_WORTH_IT scenario (breakeven >= 30 or no advantage) → ≤ 40 pts.
    """
    if net_apy_advantage_pct <= 0:
        return 0
    raw = 100.0 - breakeven_days * 2.0
    return int(round(min(max(raw, 0.0), 100.0)))


def compute_bridge_label(
    breakeven_days: float,
    net_apy_advantage_pct: float,
) -> str:
    """
    Assign bridge label based on breakeven_days and net_apy_advantage_pct.

    Rules (evaluated in order):
      net_apy_advantage_pct <= 0                   → BRIDGE_NOT_WORTH_IT
      breakeven_days > 30 (or >= _BREAKEVEN_INF)   → BRIDGE_NOT_WORTH_IT
      breakeven_days <= 3                           → EFFICIENT_BRIDGE
      breakeven_days <= 7                           → ACCEPTABLE_COST
      breakeven_days <= 14                          → HIGH_BRIDGE_COST
      breakeven_days <= 30                          → INEFFICIENT_BRIDGE
      otherwise                                     → BRIDGE_NOT_WORTH_IT
    """
    if net_apy_advantage_pct <= 0:
        return LABEL_BRIDGE_NOT_WORTH_IT
    if breakeven_days > _BREAKEVEN_INEFFICIENT:
        return LABEL_BRIDGE_NOT_WORTH_IT
    if breakeven_days <= _BREAKEVEN_EFFICIENT:
        return LABEL_EFFICIENT_BRIDGE
    if breakeven_days <= _BREAKEVEN_ACCEPTABLE:
        return LABEL_ACCEPTABLE_COST
    if breakeven_days <= _BREAKEVEN_HIGH:
        return LABEL_HIGH_BRIDGE_COST
    # breakeven_days <= 30
    return LABEL_INEFFICIENT_BRIDGE


def _atomic_log_append(entry: dict, log_path: str, cap: int) -> None:
    """Append one entry to ring-buffer JSON log atomically (tmp + os.replace)."""
    log_dir = os.path.dirname(log_path)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as fh:
                records = json.load(fh)
            if not isinstance(records, list):
                records = []
        except (json.JSONDecodeError, OSError):
            records = []
    else:
        records = []

    records.append(entry)
    if len(records) > cap:
        records = records[-cap:]

    tmp = log_path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(records, fh, indent=2)
    os.replace(tmp, log_path)


# --------------------------------------------------------------------------- #
# Main class
# --------------------------------------------------------------------------- #

class ProtocolDeFiCrossChainBridgeFeeAnalyzer:
    """
    Calculates the true cost of bridging assets cross-chain for yield farming.

    Accounts for:
    - Bridge protocol percentage fee
    - Bridge fixed fee
    - Destination chain gas costs
    - Source chain gas costs
    - Opportunity cost during bridge transit (yield foregone)
    - Net APY advantage of the destination protocol

    Inputs (keyword arguments):
        protocol_name       (str)   — bridge/protocol identifier
        bridge_fee_pct      (float) — bridge protocol fee as % of amount
        bridge_fee_fixed_usd (float)— fixed fee in USD (regardless of amount)
        destination_gas_usd (float) — gas cost on destination chain (USD)
        source_gas_usd      (float) — gas cost on source chain (USD)
        bridge_time_minutes (int)   — estimated bridge completion time
        position_size_usd   (float) — position size being bridged (USD)
        target_apy_pct      (float) — APY available on destination chain (%)
        source_apy_pct      (float) — APY foregone on source chain (%)

    Outputs (returned dict keys):
        protocol_name            (str)
        bridge_fee_pct           (float)
        bridge_fee_fixed_usd     (float)
        destination_gas_usd      (float)
        source_gas_usd           (float)
        bridge_time_minutes      (int)
        position_size_usd        (float)
        target_apy_pct           (float)
        source_apy_pct           (float)
        total_bridge_cost_usd    (float) — all fees combined
        total_bridge_cost_pct    (float) — cost as % of position
        opportunity_cost_usd     (float) — yield lost during bridge time
        breakeven_days           (float) — days of higher yield to recover cost
        net_apy_advantage_pct    (float) — target minus source APY
        bridge_efficiency_score  (int)   — 0-100
        bridge_label             (str)   — EFFICIENT_BRIDGE / ACCEPTABLE_COST /
                                           HIGH_BRIDGE_COST / INEFFICIENT_BRIDGE /
                                           BRIDGE_NOT_WORTH_IT
        timestamp                (str)   — ISO-8601 UTC

    Usage::

        analyzer = ProtocolDeFiCrossChainBridgeFeeAnalyzer()
        result = analyzer.analyze(
            protocol_name="Stargate",
            bridge_fee_pct=0.06,
            bridge_fee_fixed_usd=0.0,
            destination_gas_usd=2.5,
            source_gas_usd=5.0,
            bridge_time_minutes=20,
            position_size_usd=50_000.0,
            target_apy_pct=8.5,
            source_apy_pct=3.5,
        )
    """

    def __init__(self, log_path: str | None = None, log_cap: int = _LOG_CAP):
        self._log_path = log_path or _LOG_PATH
        self._log_cap  = log_cap

    # ---------------------------------------------------------------------- #
    # Public API
    # ---------------------------------------------------------------------- #

    def analyze(
        self,
        protocol_name: str,
        bridge_fee_pct: float,
        bridge_fee_fixed_usd: float,
        destination_gas_usd: float,
        source_gas_usd: float,
        bridge_time_minutes: int,
        position_size_usd: float,
        target_apy_pct: float,
        source_apy_pct: float,
    ) -> dict:
        """
        Analyze the true cost and efficiency of a cross-chain bridge operation.

        Returns
        -------
        dict with all computed metrics; result is also appended to ring-buffer log.
        """
        # Coerce inputs
        bridge_fee_pct       = float(bridge_fee_pct)
        bridge_fee_fixed_usd = float(bridge_fee_fixed_usd)
        destination_gas_usd  = float(destination_gas_usd)
        source_gas_usd       = float(source_gas_usd)
        bridge_time_minutes  = int(bridge_time_minutes)
        position_size_usd    = float(position_size_usd)
        target_apy_pct       = float(target_apy_pct)
        source_apy_pct       = float(source_apy_pct)

        # Core computations
        total_bridge_cost_usd = compute_total_bridge_cost_usd(
            bridge_fee_pct, bridge_fee_fixed_usd,
            destination_gas_usd, source_gas_usd, position_size_usd,
        )
        total_bridge_cost_pct = compute_total_bridge_cost_pct(
            total_bridge_cost_usd, position_size_usd
        )
        opportunity_cost_usd = compute_opportunity_cost_usd(
            position_size_usd, source_apy_pct, bridge_time_minutes
        )
        net_apy_advantage_pct = compute_net_apy_advantage_pct(target_apy_pct, source_apy_pct)
        breakeven_days = compute_breakeven_days(
            total_bridge_cost_usd, position_size_usd, net_apy_advantage_pct
        )
        bridge_efficiency_score = compute_bridge_efficiency_score(breakeven_days, net_apy_advantage_pct)
        bridge_label = compute_bridge_label(breakeven_days, net_apy_advantage_pct)

        timestamp = clock.utcnow().isoformat() + "Z"

        result = {
            "protocol_name":           protocol_name,
            "bridge_fee_pct":          bridge_fee_pct,
            "bridge_fee_fixed_usd":    bridge_fee_fixed_usd,
            "destination_gas_usd":     destination_gas_usd,
            "source_gas_usd":          source_gas_usd,
            "bridge_time_minutes":     bridge_time_minutes,
            "position_size_usd":       position_size_usd,
            "target_apy_pct":          target_apy_pct,
            "source_apy_pct":          source_apy_pct,
            "total_bridge_cost_usd":   total_bridge_cost_usd,
            "total_bridge_cost_pct":   total_bridge_cost_pct,
            "opportunity_cost_usd":    opportunity_cost_usd,
            "breakeven_days":          breakeven_days,
            "net_apy_advantage_pct":   net_apy_advantage_pct,
            "bridge_efficiency_score": bridge_efficiency_score,
            "bridge_label":            bridge_label,
            "timestamp":               timestamp,
        }

        log_entry = {
            "timestamp":               timestamp,
            "protocol_name":           protocol_name,
            "position_size_usd":       position_size_usd,
            "total_bridge_cost_usd":   total_bridge_cost_usd,
            "total_bridge_cost_pct":   total_bridge_cost_pct,
            "breakeven_days":          breakeven_days,
            "net_apy_advantage_pct":   net_apy_advantage_pct,
            "bridge_efficiency_score": bridge_efficiency_score,
            "bridge_label":            bridge_label,
        }
        _atomic_log_append(log_entry, self._log_path, self._log_cap)

        return result

    def analyze_batch(self, bridges: list) -> list:
        """
        Analyze a list of bridge operation dicts.
        Each dict must contain all required keys (see class docstring).
        Returns list of result dicts in the same order.
        """
        results = []
        for b in bridges:
            result = self.analyze(
                protocol_name       = str(b.get("protocol_name", "unknown")),
                bridge_fee_pct      = float(b.get("bridge_fee_pct", 0.0)),
                bridge_fee_fixed_usd= float(b.get("bridge_fee_fixed_usd", 0.0)),
                destination_gas_usd = float(b.get("destination_gas_usd", 0.0)),
                source_gas_usd      = float(b.get("source_gas_usd", 0.0)),
                bridge_time_minutes = int(b.get("bridge_time_minutes", 0)),
                position_size_usd   = float(b.get("position_size_usd", 0.0)),
                target_apy_pct      = float(b.get("target_apy_pct", 0.0)),
                source_apy_pct      = float(b.get("source_apy_pct", 0.0)),
            )
            results.append(result)
        return results

    def rank_by_efficiency(self, bridges: list) -> list:
        """
        Analyze a list of bridge dicts and return sorted by
        bridge_efficiency_score descending, then breakeven_days ascending.
        Most efficient bridge first.
        """
        results = self.analyze_batch(bridges)
        return sorted(
            results,
            key=lambda r: (-r["bridge_efficiency_score"], r["breakeven_days"]),
        )
