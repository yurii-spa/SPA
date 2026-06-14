"""
MP-1081: ProtocolDeFiPositionHealthMonitor
Monitors health and risk of individual DeFi positions.
Read-only/advisory — no modifications to allocator/risk/execution.
Atomic writes to data/position_health_monitor_log.json (ring-buffer 100).
"""

import json
import math
import os
import tempfile
from datetime import datetime, timezone
from typing import Any

# ── constants ─────────────────────────────────────────────────────────────────
LOG_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data",
    "position_health_monitor_log.json"
)
LOG_CAP = 100

VALID_POSITION_TYPES = {"lending", "lp", "staking", "vault"}

# Risk score thresholds (0–100, higher = more risky)
RISK_LABEL_THRESHOLDS = {
    "CRITICAL_ACTION_NEEDED": 75.0,
    "AT_RISK": 50.0,
    "NEUTRAL": 30.0,
    "HEALTHY": 10.0,
    # THRIVING → score < 10
}

# Health factor danger zone (for lending positions)
HF_LIQUIDATION_DANGER = 1.1   # below this → critical
HF_AT_RISK = 1.3              # below this → at risk

# IL thresholds
IL_HIGH_PCT = 10.0   # >10% IL → high risk
IL_MODERATE = 5.0    # 5–10% IL → moderate risk

# Lock period risk escalation (days remaining locked)
LOCK_HIGH_DAYS = 30
LOCK_MODERATE_DAYS = 7

# Annualise factor
DAYS_IN_YEAR = 365.0


# ── helpers ───────────────────────────────────────────────────────────────────

def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _compute_net_pnl_usd(
    unrealized_pnl_usd: float,
    exit_cost_usd: float,
) -> float:
    """Net PnL = unrealized PnL − exit cost."""
    return round(unrealized_pnl_usd - exit_cost_usd, 4)


def _compute_net_pnl_pct(
    net_pnl_usd: float,
    entry_value_usd: float,
) -> float:
    """Net PnL as percentage of entry value."""
    if entry_value_usd <= 0:
        return 0.0
    return round(100.0 * net_pnl_usd / entry_value_usd, 4)


def _compute_annualized_return(
    net_pnl_pct: float,
    days_held: float,
) -> float:
    """
    Annualise the net PnL percentage.
    annualized = net_pnl_pct / days_held * 365, clamped to [-1000, 1000].
    """
    if days_held <= 0:
        return 0.0
    ann = net_pnl_pct / days_held * DAYS_IN_YEAR
    return round(max(-1000.0, min(1000.0, ann)), 4)


def _health_factor_risk(
    position_type: str,
    health_factor: float | None,
    liquidation_threshold_pct: float,
) -> float:
    """
    Returns a risk contribution 0–40 based on lending health factor.
    Only applied when position_type == 'lending'.
    """
    if position_type != "lending" or health_factor is None:
        return 0.0
    if health_factor < HF_LIQUIDATION_DANGER:
        return 40.0
    if health_factor < HF_AT_RISK:
        return 25.0
    # Scale linearly between 1.3 and 3.0: lower HF → higher risk
    if health_factor < 3.0:
        fraction = (3.0 - health_factor) / (3.0 - HF_AT_RISK)
        return round(_clamp(fraction * 15.0, 0.0, 15.0), 4)
    return 0.0


def _il_risk(position_type: str, il_pct: float | None) -> float:
    """
    Returns a risk contribution 0–30 based on impermanent loss.
    Only applied when position_type == 'lp'.
    """
    if position_type != "lp" or il_pct is None:
        return 0.0
    il = abs(il_pct)
    if il > IL_HIGH_PCT:
        return 30.0
    if il > IL_MODERATE:
        return 15.0
    # Linear below IL_MODERATE
    return round(_clamp(il / IL_MODERATE * 10.0, 0.0, 10.0), 4)


def _lock_risk(lock_remaining_days: float) -> float:
    """
    Returns a risk contribution 0–20 based on remaining lock period.
    Long lock = exit illiquidity.
    """
    if lock_remaining_days <= 0:
        return 0.0
    if lock_remaining_days > LOCK_HIGH_DAYS:
        return 20.0
    if lock_remaining_days > LOCK_MODERATE_DAYS:
        return 10.0
    return round(_clamp(lock_remaining_days / LOCK_MODERATE_DAYS * 5.0, 0.0, 5.0), 4)


def _pnl_risk(net_pnl_pct: float) -> float:
    """
    Returns a risk contribution 0–20 based on negative net PnL.
    Losses compound risk; gains reduce it (min 0).
    """
    if net_pnl_pct >= 0:
        return 0.0
    # -5% → 5 pts; -20% → 20 pts (capped at 20)
    return round(_clamp(abs(net_pnl_pct), 0.0, 20.0), 4)


def _exit_cost_risk(exit_cost_usd: float, current_value_usd: float) -> float:
    """
    Returns a risk contribution 0–10 when exit cost is a significant
    fraction of position value (exit friction).
    """
    if current_value_usd <= 0:
        return 0.0
    fraction_pct = 100.0 * exit_cost_usd / current_value_usd
    # >5% exit cost → max contribution 10
    return round(_clamp(fraction_pct * 2.0, 0.0, 10.0), 4)


def _compute_position_risk_score(
    position_type: str,
    health_factor: float | None,
    liquidation_threshold_pct: float,
    il_pct: float | None,
    lock_remaining_days: float,
    net_pnl_pct: float,
    exit_cost_usd: float,
    current_value_usd: float,
) -> float:
    """
    Composite risk score 0–100.
    Components:
      - health factor risk (0–40, lending only)
      - IL risk            (0–30, lp only)
      - lock risk          (0–20)
      - pnl risk           (0–20)
      - exit cost risk     (0–10)
    Capped at 100.
    """
    hf_r = _health_factor_risk(position_type, health_factor, liquidation_threshold_pct)
    il_r = _il_risk(position_type, il_pct)
    lk_r = _lock_risk(lock_remaining_days)
    pnl_r = _pnl_risk(net_pnl_pct)
    ec_r = _exit_cost_risk(exit_cost_usd, current_value_usd)
    return round(_clamp(hf_r + il_r + lk_r + pnl_r + ec_r), 4)


def _compute_position_label(risk_score: float) -> str:
    """
    THRIVING     → risk < 10
    HEALTHY      → risk 10–29
    NEUTRAL      → risk 30–49
    AT_RISK      → risk 50–74
    CRITICAL_ACTION_NEEDED → risk ≥ 75
    """
    if risk_score >= RISK_LABEL_THRESHOLDS["CRITICAL_ACTION_NEEDED"]:
        return "CRITICAL_ACTION_NEEDED"
    if risk_score >= RISK_LABEL_THRESHOLDS["AT_RISK"]:
        return "AT_RISK"
    if risk_score >= RISK_LABEL_THRESHOLDS["NEUTRAL"]:
        return "NEUTRAL"
    if risk_score >= RISK_LABEL_THRESHOLDS["HEALTHY"]:
        return "HEALTHY"
    return "THRIVING"


def _monitor_single(data: dict) -> dict:
    """Core monitoring logic for one position snapshot."""
    protocol_name = str(data.get("protocol_name", "UNKNOWN"))
    position_type = str(data.get("position_type", "vault")).lower()
    if position_type not in VALID_POSITION_TYPES:
        position_type = "vault"

    entry_value = float(data.get("entry_value_usd", 0.0))
    current_value = float(data.get("current_value_usd", 0.0))
    unrealized_pnl = float(data.get("unrealized_pnl_usd", 0.0))
    days_held = float(data.get("days_held", 1.0))
    apy_earned = float(data.get("apy_earned_pct", 0.0))
    health_factor = data.get("health_factor")
    if health_factor is not None:
        health_factor = float(health_factor)
    liquidation_threshold = float(data.get("liquidation_threshold_pct", 80.0))
    il_pct = data.get("il_pct")
    if il_pct is not None:
        il_pct = float(il_pct)
    lock_remaining = float(data.get("lock_remaining_days", 0.0))
    exit_cost = float(data.get("exit_cost_usd", 0.0))

    net_pnl = _compute_net_pnl_usd(unrealized_pnl, exit_cost)
    net_pnl_pct = _compute_net_pnl_pct(net_pnl, entry_value)
    ann_return = _compute_annualized_return(net_pnl_pct, days_held)
    risk_score = _compute_position_risk_score(
        position_type, health_factor, liquidation_threshold,
        il_pct, lock_remaining, net_pnl_pct, exit_cost, current_value,
    )
    label = _compute_position_label(risk_score)

    return {
        "protocol_name": protocol_name,
        "position_type": position_type,
        "entry_value_usd": round(entry_value, 2),
        "current_value_usd": round(current_value, 2),
        "net_pnl_usd": net_pnl,
        "net_pnl_pct": net_pnl_pct,
        "annualized_return_pct": ann_return,
        "apy_earned_pct": round(apy_earned, 4),
        "position_risk_score": risk_score,
        "position_label": label,
        "days_held": days_held,
        "lock_remaining_days": lock_remaining,
    }


def _atomic_write(path: str, data: Any) -> None:
    """Write JSON atomically via tmp-file + os.replace."""
    dir_path = os.path.dirname(path)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dir_path or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _append_log(result: dict, log_path: str) -> None:
    """Append a log entry (ring-buffer, cap LOG_CAP)."""
    existing: list = []
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
        if not isinstance(existing, list):
            existing = []
    except (FileNotFoundError, json.JSONDecodeError):
        existing = []

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "protocol_name": result.get("protocol_name", ""),
        "position_type": result.get("position_type", ""),
        "net_pnl_usd": result.get("net_pnl_usd", 0.0),
        "position_risk_score": result.get("position_risk_score", 0.0),
        "position_label": result.get("position_label", ""),
    }
    existing.append(entry)
    if len(existing) > LOG_CAP:
        existing = existing[-LOG_CAP:]
    _atomic_write(log_path, existing)


# ── main class ────────────────────────────────────────────────────────────────

class ProtocolDeFiPositionHealthMonitor:
    """
    Monitors the health and risk of individual DeFi protocol positions.

    Input dict keys:
        protocol_name           str
        position_type           str   one of: lending / lp / staking / vault
        entry_value_usd         float
        current_value_usd       float
        unrealized_pnl_usd      float
        days_held               float
        apy_earned_pct          float
        health_factor           float | None  (lending only)
        liquidation_threshold_pct float
        il_pct                  float | None  (lp only)
        lock_remaining_days     float
        exit_cost_usd           float

    Output dict keys:
        net_pnl_usd             float
        net_pnl_pct             float
        annualized_return_pct   float
        position_risk_score     float  0–100
        position_label          str    one of:
                                THRIVING / HEALTHY / NEUTRAL /
                                AT_RISK / CRITICAL_ACTION_NEEDED
    """

    def monitor(self, data: dict, config: dict | None = None) -> dict:
        cfg = config or {}
        log_path = cfg.get("log_path", LOG_FILE)
        write_log = cfg.get("write_log", True)

        if not isinstance(data, dict):
            raise TypeError("data must be a dict")

        result = _monitor_single(data)

        if write_log:
            try:
                _append_log(result, log_path)
            except Exception:
                pass  # advisory — never raise on log failure

        return result
