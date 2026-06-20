"""
MP-815 SmartMoneyFlowDetector
Advisory/read-only module — detects large wallet (smart money) deposit/withdrawal
patterns in DeFi protocols as a leading indicator of upcoming TVL and APY changes.

Data log: data/smart_money_flow_log.json  (ring-buffer 100, atomic write)
Pure stdlib only. LLM FORBIDDEN.
"""

import json
import os
import time
from typing import Optional
from spa_core.utils.atomic import atomic_save

# ── defaults ─────────────────────────────────────────────────────────────────
_DEFAULT_WHALE_THRESHOLD_USD: float = 500_000.0
_DEFAULT_LOOKBACK_HOURS: float = 24.0
_DEFAULT_SIGNAL_WINDOW_HOURS: float = 168.0  # 7 days
_LOG_RING_SIZE: int = 100
_LOG_PATH_DEFAULT: str = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "smart_money_flow_log.json",
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _load_log(path: str) -> list:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_log(path: str, entries: list) -> None:
    """Atomic write with ring-buffer cap."""
    entries = entries[-_LOG_RING_SIZE:]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    atomic_save(entries, str(path))
def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _compute_flow_signal(net_flow_usd: float, gross_inflow: float, gross_outflow: float) -> str:
    total = gross_inflow + gross_outflow
    if total <= 0:
        return "NEUTRAL"
    net_pct = net_flow_usd / total * 100.0
    if net_pct > 50:
        return "STRONG_INFLOW"
    if net_pct > 10:
        return "INFLOW"
    if net_pct >= -10:
        return "NEUTRAL"
    if net_pct >= -50:
        return "OUTFLOW"
    return "STRONG_OUTFLOW"


def _compute_whale_signal(whale_net_flow_usd: float) -> str:
    if whale_net_flow_usd > 0:
        return "ACCUMULATING"
    if whale_net_flow_usd < 0:
        return "DISTRIBUTING"
    return "NEUTRAL"


def _build_interpretation(
    flow_signal: str,
    whale_signal: str,
    net_flow_usd: float,
    whale_net_flow_usd: float,
) -> str:
    net_abs = abs(net_flow_usd)
    net_str = f"${net_abs / 1e6:.2f}M" if net_abs >= 1e6 else f"${net_abs / 1e3:.0f}K"

    direction = "inflow" if net_flow_usd >= 0 else "outflow"

    if flow_signal in ("STRONG_INFLOW", "INFLOW") and whale_signal == "ACCUMULATING":
        return f"Net {net_str} {direction} with whale accumulation — bullish signal"
    if flow_signal in ("STRONG_OUTFLOW", "OUTFLOW") and whale_signal == "DISTRIBUTING":
        return f"Net {net_str} {direction} with whale distribution — monitor closely"
    if flow_signal in ("STRONG_INFLOW", "INFLOW"):
        return f"Net {net_str} {direction} — inflow trend detected"
    if flow_signal in ("STRONG_OUTFLOW", "OUTFLOW"):
        return f"Net {net_str} {direction} — outflow trend, caution advised"
    if whale_signal == "ACCUMULATING":
        return "Neutral flow but whale accumulation present — watch for momentum shift"
    if whale_signal == "DISTRIBUTING":
        return "Neutral flow but whale distribution detected — potential early exit signal"
    return "Flow neutral — no significant smart money signal detected"


# ── public API ────────────────────────────────────────────────────────────────

def analyze(
    protocol: str,
    flow_events: list,
    config: Optional[dict] = None,
    *,
    log_path: Optional[str] = None,
    persist: bool = True,
) -> dict:
    """
    Analyze smart money (whale/institution) flow events for a protocol.

    Parameters
    ----------
    protocol : str
        Protocol identifier (e.g. "aave_v3").
    flow_events : list[dict]
        Each entry: {timestamp, wallet_type, action, amount_usd}.
    config : dict, optional
        whale_threshold_usd, lookback_hours, signal_window_hours.
    log_path : str, optional
        Override default log file path.
    persist : bool
        Write result to log (default True).

    Returns
    -------
    dict  — see module docstring for full schema.
    """
    cfg = config or {}
    whale_threshold = float(cfg.get("whale_threshold_usd", _DEFAULT_WHALE_THRESHOLD_USD))
    lookback_hours = float(cfg.get("lookback_hours", _DEFAULT_LOOKBACK_HOURS))
    signal_window_hours = float(cfg.get("signal_window_hours", _DEFAULT_SIGNAL_WINDOW_HOURS))

    now_ts = time.time()
    cutoff_recent = now_ts - lookback_hours * 3600.0
    cutoff_window = now_ts - signal_window_hours * 3600.0

    # ── filter events ─────────────────────────────────────────────────────────
    recent_events = [
        e for e in flow_events
        if isinstance(e, dict) and float(e.get("timestamp", 0)) >= cutoff_recent
    ]
    window_events = [
        e for e in flow_events
        if isinstance(e, dict) and float(e.get("timestamp", 0)) >= cutoff_window
    ]

    # ── recent_24h metrics ────────────────────────────────────────────────────
    gross_inflow = 0.0
    gross_outflow = 0.0
    whale_inflow = 0.0
    whale_outflow = 0.0
    deposit_count = 0
    withdrawal_count = 0
    largest_single = 0.0

    for ev in recent_events:
        amount = float(ev.get("amount_usd", 0.0))
        action = ev.get("action", "")
        wtype = ev.get("wallet_type", "")
        is_whale = wtype in ("whale", "institution") or amount >= whale_threshold

        if amount > largest_single:
            largest_single = amount

        if action == "deposit":
            gross_inflow += amount
            deposit_count += 1
            if is_whale:
                whale_inflow += amount
        elif action == "withdrawal":
            gross_outflow += amount
            withdrawal_count += 1
            if is_whale:
                whale_outflow += amount

    net_flow_usd = gross_inflow - gross_outflow
    whale_net_flow_usd = whale_inflow - whale_outflow

    # ── 7-day context volume ──────────────────────────────────────────────────
    window_total_volume = sum(
        float(e.get("amount_usd", 0.0)) for e in window_events
    )

    # ── signals ───────────────────────────────────────────────────────────────
    flow_signal = _compute_flow_signal(net_flow_usd, gross_inflow, gross_outflow)
    whale_signal = _compute_whale_signal(whale_net_flow_usd)

    # ── smart_money_score ─────────────────────────────────────────────────────
    raw_score = whale_net_flow_usd / (window_total_volume + 1.0) * 100.0
    smart_money_score = int(_clamp(raw_score, -100.0, 100.0))

    # ── risk_events ───────────────────────────────────────────────────────────
    risk_events: list = []

    for ev in recent_events:
        amount = float(ev.get("amount_usd", 0.0))
        action = ev.get("action", "")
        wtype = ev.get("wallet_type", "")
        is_whale = wtype in ("whale", "institution") or amount >= whale_threshold
        if action == "withdrawal" and is_whale and amount >= whale_threshold:
            risk_events.append(f"Large whale withdrawal: ${amount / 1e6:.1f}M")

    if window_total_volume > 0 and whale_outflow > 0.10 * window_total_volume:
        risk_events.append("Elevated whale exits vs 7-day volume")

    # ── interpretation ────────────────────────────────────────────────────────
    interpretation = _build_interpretation(
        flow_signal, whale_signal, net_flow_usd, whale_net_flow_usd
    )

    result = {
        "protocol": protocol,
        "analysis_window_hours": lookback_hours,
        "recent_24h": {
            "gross_inflow_usd": gross_inflow,
            "gross_outflow_usd": gross_outflow,
            "net_flow_usd": net_flow_usd,
            "whale_inflow_usd": whale_inflow,
            "whale_outflow_usd": whale_outflow,
            "whale_net_flow_usd": whale_net_flow_usd,
            "deposit_count": deposit_count,
            "withdrawal_count": withdrawal_count,
            "largest_single_event_usd": largest_single,
        },
        "flow_signal": flow_signal,
        "whale_signal": whale_signal,
        "smart_money_score": smart_money_score,
        "risk_events": risk_events,
        "interpretation": interpretation,
        "timestamp": now_ts,
    }

    if persist:
        _path = log_path or _LOG_PATH_DEFAULT
        entries = _load_log(_path)
        entries.append(result)
        _save_log(_path, entries)

    return result


def init_log(path: Optional[str] = None) -> None:
    """Ensure log file exists and is a valid empty list."""
    _path = path or _LOG_PATH_DEFAULT
    os.makedirs(os.path.dirname(_path), exist_ok=True)
    if not os.path.exists(_path):
        _save_log(_path, [])


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="MP-815 SmartMoneyFlowDetector")
    parser.add_argument("--protocol", default="demo_protocol")
    parser.add_argument("--check", action="store_true", help="Compute without persisting")
    parser.add_argument("--run", action="store_true", help="Compute and persist to log")
    args = parser.parse_args()

    # Demo events: simulate whale deposit + retail withdrawal
    _now = time.time()
    _demo_events = [
        {"timestamp": _now - 3600, "wallet_type": "whale", "action": "deposit", "amount_usd": 1_500_000},
        {"timestamp": _now - 7200, "wallet_type": "institution", "action": "deposit", "amount_usd": 2_000_000},
        {"timestamp": _now - 1800, "wallet_type": "retail", "action": "withdrawal", "amount_usd": 50_000},
        {"timestamp": _now - 86400 * 2, "wallet_type": "whale", "action": "deposit", "amount_usd": 800_000},
    ]

    _persist = args.run and not args.check
    _result = analyze(args.protocol, _demo_events, persist=_persist)
    print(json.dumps(_result, indent=2))
