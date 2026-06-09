"""
APY Gap Report — SPA Phase 1-3 APY gap analysis.

Computes the delta between the portfolio's current weighted APY and the 7.3% target,
and estimates how much of the gap is closeable by activating Pendle PT (T2) and
Sky/sUSDS (once whitelisted).

Target APY: 7.3%
Current baseline (paper trading start 2026-05-20): ~4.2%
Gap to close: ~3.1%

Estimated contributions:
  - Pendle PT (T2, fixed-rate): +2.0–3.5% depending on available pools (6–9% APY)
  - Sky/sUSDS (PENDING whitelist): ~0.5–1.0% contribution once unlocked

Usage:
    from data_pipeline.apy_gap_report import apy_gap_report

    report = apy_gap_report(portfolio_status)
    print(report)

portfolio_status is the dict returned by PaperTrader.get_status().
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

TARGET_APY = 7.3          # % — SPA Phase 1-3 target weighted APY
PAPER_START_APY = 4.2     # % — baseline at paper trading start (2026-05-20)

# ── History persistence (SPA-V373) ────────────────────────────────────────────
# Compact append-only log of the APY-gap headline over time, so the dashboard can
# render a sparkline of current_weighted_apy progress toward the 7.3% target.
# Mirrors the readiness/checklist/combined-gate history pattern (SPA-V363/V365/V368).
DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
APY_GAP_HISTORY_FILENAME = "apy_gap_report_history.json"
MAX_HISTORY = 180          # trim cap — same as readiness_score history logs

# Pendle PT assumptions (conservative estimates based on current pool landscape)
PENDLE_TYPICAL_APY = 7.5  # % — typical Pendle PT APY on stables (range 6–9%)
PENDLE_MAX_T2_PCT = 0.35  # max T2 allocation fraction (policy max_total_t2_allocation)
PENDLE_TYPICAL_T2_PCT = 0.15  # realistic T2 deployment fraction (conservative)

# Sky / sUSDS assumptions (PENDING whitelist approval)
SKY_SUSDS_TYPICAL_APY = 6.0   # % — approximate Sky/sUSDS APY
SKY_TYPICAL_PCT = 0.10         # expected allocation fraction once approved


def _weighted_apy(positions: list[dict], total_capital: float) -> float:
    """
    Compute the portfolio's weighted average APY across all open positions.

    Positions with no current_apy are excluded (cash / undeployed capital is 0%).
    The weighting denominator is total_capital so idle cash drags the average down.

    Args:
        positions:     list of position dicts (from PaperTrader.get_status())
        total_capital: total portfolio capital in USD

    Returns:
        Weighted APY in % (0.0 if no positions or zero capital)
    """
    if not positions or total_capital <= 0:
        return 0.0

    weighted_sum = sum(
        p.get("amount_usd", 0.0) * p.get("current_apy", 0.0)
        for p in positions
        if p.get("amount_usd", 0.0) > 0
    )
    return weighted_sum / total_capital


def _pendle_apy_contribution(
    portfolio_status: dict,
    pendle_apy: float = PENDLE_TYPICAL_APY,
    t2_target_pct: float = PENDLE_TYPICAL_T2_PCT,
) -> float:
    """
    Estimate the APY contribution Pendle PT would add to the portfolio
    if allocated at `t2_target_pct` of total capital.

    Logic: additional_contribution = pendle_apy × t2_target_pct
    minus the opportunity cost of re-allocating from current T1 yield.

    Returns estimated delta APY in percentage points.
    """
    portfolio = portfolio_status.get("portfolio", {})
    total_capital = portfolio.get("total_capital_usd", 100_000.0) or 100_000.0

    positions = portfolio_status.get("positions", [])
    current_t2_usd = sum(
        p.get("amount_usd", 0.0) for p in positions if p.get("tier") == "T2"
    )
    current_t2_pct = current_t2_usd / total_capital if total_capital > 0 else 0.0

    # Additional T2 headroom available (up to policy max)
    incremental_t2_pct = max(0.0, t2_target_pct - current_t2_pct)

    if incremental_t2_pct <= 0:
        return 0.0

    # Estimate current T1 APY baseline (from positions)
    t1_positions = [p for p in positions if p.get("tier") == "T1"]
    t1_baseline = (
        sum(p.get("current_apy", 0.0) for p in t1_positions) / len(t1_positions)
        if t1_positions else 4.0
    )

    # APY uplift from deploying incremental capital into Pendle vs holding as cash (0%)
    # or rebalancing from T1. We model it as pure additive contribution from cash/idle.
    contribution = pendle_apy * incremental_t2_pct
    return round(contribution, 4)


def _sky_apy_contribution(
    portfolio_status: dict,
    sky_apy: float = SKY_SUSDS_TYPICAL_APY,
    sky_target_pct: float = SKY_TYPICAL_PCT,
) -> float:
    """
    Estimate the APY contribution Sky/sUSDS would add if whitelisted and allocated.

    Returns estimated delta APY in percentage points (0 until whitelist approved).
    """
    # Sky is PENDING whitelist — return the estimated uplift for planning purposes
    contribution = sky_apy * sky_target_pct
    return round(contribution, 4)


def apy_gap_report(portfolio_status: dict) -> dict:
    """
    Generate an APY gap analysis for the SPA portfolio.

    Args:
        portfolio_status: dict returned by PaperTrader.get_status() or equivalent,
                          with keys "portfolio" and "positions".

    Returns:
        {
            "current_weighted_apy": float,   # weighted APY across all open positions
            "target_apy": 7.3,               # SPA Phase 1-3 target
            "gap": float,                    # target - current (positive = below target)
            "gap_closeable_by_pendle": float, # estimated APY uplift from Pendle PT
            "gap_closeable_by_sky": float,   # estimated APY uplift from Sky/sUSDS
            "remaining_gap": float,           # gap after Pendle + Sky contributions
            "on_track": bool,                # True if current APY >= target
            "pendle_status": str,            # "eligible" | "partial" | "none"
            "sky_status": str,               # "pending_whitelist"
            "summary": str,                  # human-readable summary
        }
    """
    portfolio = portfolio_status.get("portfolio", {})
    positions = portfolio_status.get("positions", [])
    total_capital = portfolio.get("total_capital_usd", 100_000.0) or 100_000.0

    # Current weighted APY
    current_apy = _weighted_apy(positions, total_capital)

    # Gap to target
    gap = round(TARGET_APY - current_apy, 4)
    on_track = current_apy >= TARGET_APY

    # Pendle contribution estimate
    gap_closeable_by_pendle = _pendle_apy_contribution(portfolio_status)

    # Sky/sUSDS contribution estimate
    gap_closeable_by_sky = _sky_apy_contribution(portfolio_status)

    # Remaining gap after all available levers
    remaining_gap = round(max(0.0, gap - gap_closeable_by_pendle - gap_closeable_by_sky), 4)

    # Pendle status — check if any Pendle PT positions exist already
    pendle_positions = [p for p in positions if p.get("special") == "fixed_rate"
                        or "pendle" in str(p.get("protocol_key", "")).lower()]
    if pendle_positions:
        total_pendle_usd = sum(p.get("amount_usd", 0.0) for p in pendle_positions)
        pendle_pct = total_pendle_usd / total_capital if total_capital > 0 else 0.0
        pendle_status = "partial" if pendle_pct < PENDLE_TYPICAL_T2_PCT else "eligible"
    else:
        pendle_status = "none"

    # Summary
    if on_track:
        summary = (
            f"On track: current APY {current_apy:.2f}% ≥ target {TARGET_APY}%. "
            f"Gap closed."
        )
    else:
        levers = []
        if gap_closeable_by_pendle > 0:
            levers.append(f"Pendle PT +{gap_closeable_by_pendle:.2f}%")
        if gap_closeable_by_sky > 0:
            levers.append(f"Sky/sUSDS +{gap_closeable_by_sky:.2f}% (pending whitelist)")
        lever_str = ", ".join(levers) if levers else "no additional levers identified"
        summary = (
            f"Gap {gap:.2f}% (current {current_apy:.2f}% vs target {TARGET_APY}%). "
            f"Available levers: {lever_str}. "
            f"Remaining gap after levers: {remaining_gap:.2f}%."
        )

    report = {
        "current_weighted_apy": round(current_apy, 4),
        "target_apy":           TARGET_APY,
        "gap":                  gap,
        "gap_closeable_by_pendle": gap_closeable_by_pendle,
        "gap_closeable_by_sky":    gap_closeable_by_sky,
        "remaining_gap":           remaining_gap,
        "on_track":                on_track,
        "pendle_status":           pendle_status,
        "sky_status":              "pending_whitelist",
        "summary":                 summary,
    }

    log.info(
        f"apy_gap_report: current={current_apy:.2f}%, target={TARGET_APY}%, "
        f"gap={gap:.2f}%, pendle_contribution={gap_closeable_by_pendle:.2f}%, "
        f"sky_contribution={gap_closeable_by_sky:.2f}%, on_track={on_track}"
    )
    return report


def append_apy_gap_history(
    doc: Dict[str, Any], data_dir: Optional[str] = None
) -> None:
    """SPA-V373 -- append a compact record of the APY-gap headline to its history log.

    Mirror of ``readiness_score.append_combined_history``: reads the existing
    history (``<data_dir>/apy_gap_report_history.json`` or
    ``DEFAULT_DATA_DIR / APY_GAP_HISTORY_FILENAME`` when ``data_dir`` is None),
    appends a small ``{generated_at, current_weighted_apy, gap, on_track}`` record,
    dedups on ``generated_at`` (a same-timestamp re-run replaces the last record
    rather than duplicating it), trims to the last ``MAX_HISTORY`` records and
    writes it back. A missing or corrupt history file is treated as an empty list;
    any failure is swallowed (logged at debug) so it can never break the main
    ``apy_gap_report.json`` write. Pure read-only analytics persistence -- no
    money-moving code, no new feed-health monitor (SPA-BL-011 freeze respected).
    """
    try:
        target = (
            Path(data_dir) / APY_GAP_HISTORY_FILENAME
            if data_dir is not None
            else DEFAULT_DATA_DIR / APY_GAP_HISTORY_FILENAME
        )
        history: List[Dict[str, Any]] = []
        if target.exists():
            try:
                loaded = json.loads(target.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    history = loaded
            except Exception:  # noqa: BLE001 -- corrupt file -> start fresh
                history = []
        record = {
            "generated_at": doc.get("generated_at"),
            "current_weighted_apy": doc.get("current_weighted_apy"),
            "gap": doc.get("gap"),
            "on_track": doc.get("on_track"),
        }
        if history and history[-1].get("generated_at") == record["generated_at"]:
            history[-1] = record
        else:
            history.append(record)
        history = history[-MAX_HISTORY:]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(history, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 -- never propagate
        log.debug("append_apy_gap_history failed: %s", exc)
        return
