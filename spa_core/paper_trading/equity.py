#!/usr/bin/env python3
"""Equity-curve maintenance for the paper-trading cycle (N12 decomposition).

PURE-MOVE EXTRACTION from ``cycle_runner.py``: the daily-bar accrual + equity
curve roll-up logic, including the N3 APY accrual guardrail and the T10 evidenced
``real_*`` segregation. Bodies are byte-identical to their originals — no
behaviour change. ``cycle_runner`` re-exports every name below for back-compat.

stdlib only. Atomic writes via the shared ``_atomic_write_json``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from spa_core.paper_trading._cycle_io import (
    CAPITAL_USD,
    EQUITY_FILENAME,
    MAX_EQUITY_POINTS,
    PAPER_REAL_START_DATE,
    _atomic_write_json,
)

log = logging.getLogger("spa.cycle_runner")


# ── N3: APY accrual guardrail ──────────────────────────────────────────────────
# A single normalizer guards every accrual against a cross-file unit mismatch.
# Some code paths treat APY as a PERCENT (adapter_status.apy → 5.2 == 5.2%),
# others as a DECIMAL (adapter_registry.live_apy → 0.052). If a decimal value
# ever reaches accrual as if it were a percent — or, worse, a percent is fed
# where a decimal*100 was expected — the track can be off by 100×. We fail
# CLOSED: any APY% outside [0, 100] is rejected (excluded from accrual) and
# logged, so a single bad value can never silently 100× the go-live track.
APY_ACCRUAL_MIN_PCT: float = 0.0
APY_ACCRUAL_MAX_PCT: float = 100.0


def _normalize_accrual_apy(pool: str, apy: object) -> "float | None":
    """Return a sane APY% for accrual, or ``None`` to exclude the pool.

    Fail-closed: a non-numeric, NaN/inf, or out-of-[0,100]% value (e.g. 520 from
    a decimal/percent mix-up, or a raw decimal 0.052 that's harmlessly low but
    not unit-safe) is rejected with a WARNING rather than accrued as-is. A bad
    APY must never reach ``equity_curve_daily.json``.
    """
    if isinstance(apy, bool) or not isinstance(apy, (int, float)):
        log.warning("accrual guardrail: %s APY non-numeric (%r) — excluded", pool, apy)
        return None
    val = float(apy)
    if val != val or val in (float("inf"), float("-inf")):  # NaN / inf
        log.warning("accrual guardrail: %s APY not finite (%r) — excluded", pool, apy)
        return None
    if val < APY_ACCRUAL_MIN_PCT or val > APY_ACCRUAL_MAX_PCT:
        log.warning(
            "accrual guardrail: %s APY %.4f%% outside [%.0f, %.0f]%% "
            "(possible decimal/percent unit mismatch — 100x risk) — REJECTED",
            pool, val, APY_ACCRUAL_MIN_PCT, APY_ACCRUAL_MAX_PCT,
        )
        return None
    return val


def _accrue_daily_yield(
    positions: dict[str, float], apy_map: dict[str, float]
) -> float:
    """Sum one day of yield across positions: Σ pos_usd × apy% / 100 / 365.

    N3: every APY is run through ``_normalize_accrual_apy`` (fail-closed) before
    it can contribute to the daily yield, so an out-of-range value never lands
    in the equity curve.
    """
    total = 0.0
    for pool, usd in positions.items():
        if not isinstance(usd, (int, float)) or isinstance(usd, bool):
            continue
        apy = _normalize_accrual_apy(pool, apy_map.get(pool))
        if apy is None:
            continue
        total += float(usd) * apy / 100.0 / 365.0
    return total


def _rebuild_summary(daily: list[dict]) -> dict:
    """Recompute the roll-up summary over the daily bars (schema-compatible)."""
    if not daily:
        return {
            "num_days": 0,
            "num_snapshots": 0,
            "start_equity": 0.0,
            "end_equity": 0.0,
            "total_return_pct": 0.0,
            "best_day": None,
            "worst_day": None,
            "max_drawdown_pct": 0.0,
            "positive_days": 0,
            "negative_days": 0,
            "daily_volatility_pct": 0.0,
            "first_date": None,
            "last_date": None,
        }

    start_equity = float(daily[0].get("open_equity", daily[0].get("close_equity", 0.0)))
    end_equity = float(daily[-1].get("close_equity", 0.0))
    # Day 1 has a synthetic 0.0 return — exclude from best/worst/vol stats.
    real_rets = [
        (d.get("date"), float(d.get("daily_return_pct", 0.0))) for d in daily[1:]
    ]
    best = max(real_rets, key=lambda x: x[1], default=None)
    worst = min(real_rets, key=lambda x: x[1], default=None)

    peak = float("-inf")
    max_dd = 0.0
    for d in daily:
        close = float(d.get("close_equity", 0.0))
        peak = max(peak, close)
        if peak > 0:
            dd = (close / peak - 1.0) * 100.0
            max_dd = min(max_dd, dd)

    positive = sum(1 for _, r in real_rets if r > 0)
    negative = sum(1 for _, r in real_rets if r < 0)

    # Population stdev of the real daily returns (stdlib, no numpy).
    vol = 0.0
    vals = [r for _, r in real_rets]
    if len(vals) >= 1:
        mean = sum(vals) / len(vals)
        vol = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5

    # S0.1: a bar counts toward the REAL track record only when it is
    # (a) dated ON OR AFTER PAPER_REAL_START_DATE (the post-teardown anchor) AND
    # (b) not explicitly flagged is_warmup. The DATE anchor is authoritative and
    # comes first: a legacy curve whose pre-teardown bars lack an is_warmup flag
    # (the 2026-06-25 corruption: real_days jumped to 32, first_real drifted to
    # 2026-05-21) can NEVER inflate real_days — first_real_date is clamped to
    # PAPER_REAL_START_DATE and warmup bars are excluded by date regardless of flag.
    def _bar_date(d: dict):
        try:
            return datetime.strptime(str(d.get("date"))[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None

    real_daily = [
        d
        for d in daily
        if not d.get("is_warmup", False)
        and (_bar_date(d) is not None and _bar_date(d) >= PAPER_REAL_START_DATE)
    ]
    if real_daily:
        first_real_date = real_daily[0].get("date")
    else:
        # No real bars yet — report the anchor, never an earlier (warmup) date.
        first_real_date = PAPER_REAL_START_DATE.isoformat()

    # ── T10 segregation: honest roll-up over the EVIDENCED series ONLY ──────────
    # The fields above (start/end_equity, total_return_pct, max_drawdown_pct, …)
    # are computed over ALL bars (warmup + backfill + reconstructed + cycle) for
    # schema back-compat. They MUST NOT be read as real metrics: warmup→backfill
    # discontinuities fabricate drawdown the real track never had. These ``real_*``
    # fields are the clean headline computed strictly over evidenced (real
    # daily_cycle) bars via track_evidence — the single segregation point. They
    # are additive and never change ``real_days`` / the evidenced count.
    from spa_core.paper_trading.track_evidence import (
        evidenced_bars as _evidenced_bars,
        real_max_drawdown_pct as _real_max_drawdown_pct,
        real_total_return_pct as _real_total_return_pct,
    )

    ev = _evidenced_bars(daily, paper_start=PAPER_REAL_START_DATE)
    if ev:
        real_start_equity = round(
            float(ev[0].get("open_equity", ev[0].get("close_equity", 0.0))), 2
        )
        real_end_equity = round(float(ev[-1].get("close_equity", 0.0)), 2)
    else:
        real_start_equity = 0.0
        real_end_equity = 0.0
    real_total_return = _real_total_return_pct(daily, paper_start=PAPER_REAL_START_DATE)
    real_max_dd = _real_max_drawdown_pct(daily, paper_start=PAPER_REAL_START_DATE)

    return {
        "num_days": len(daily),
        # Honest track length = bars dated >= PAPER_REAL_START and not is_warmup.
        # Pre-2026-06-10 warmup/demo bars excluded. Display real_days, not num_days.
        "real_days": len(real_daily),
        "num_snapshots": len(daily),
        "start_equity": round(start_equity, 2),
        "end_equity": round(end_equity, 2),
        "total_return_pct": round((end_equity / start_equity - 1.0) * 100.0, 4)
        if start_equity
        else 0.0,
        "best_day": {"date": best[0], "daily_return_pct": round(best[1], 4)}
        if best
        else None,
        "worst_day": {"date": worst[0], "daily_return_pct": round(worst[1], 4)}
        if worst
        else None,
        "max_drawdown_pct": round(max_dd, 4),
        # Honest REAL headline — evidenced bars only (T10). Read THESE for real
        # equity / return / drawdown; the unprefixed fields above include warmup.
        "real_start_equity": real_start_equity,
        "real_end_equity": real_end_equity,
        "real_total_return_pct": real_total_return,
        "real_max_drawdown_pct": real_max_dd,
        "positive_days": positive,
        "negative_days": negative,
        "daily_volatility_pct": round(vol, 4),
        "first_date": first_real_date,
        "first_real_date": first_real_date,
        "last_date": daily[-1].get("date"),
    }


def _upsert_equity_point(
    equity_doc: dict,
    *,
    date: str,
    apy_today_pct: float,
    positions: dict[str, float],
    apy_map: dict[str, float],
    run_ts: str,
    accrual_source: str = "live",
) -> tuple[dict, float, float, float]:
    """Append or refresh today's daily bar, idempotently per UTC day.

    Returns ``(equity_doc, close_equity, daily_yield_usd, daily_return_pct)``.

    The day's yield is always computed off the *previous* day's close, so a
    second run on the same date recomputes (rather than compounds) the bar.
    """
    daily: list[dict] = list(equity_doc.get("daily") or [])

    # Drop a same-date trailing bar so we recompute it from the prior close.
    if daily and daily[-1].get("date") == date:
        daily = daily[:-1]

    prev_close = float(daily[-1]["close_equity"]) if daily else CAPITAL_USD
    daily_yield = _accrue_daily_yield(positions, apy_map)
    close_equity = round(prev_close + daily_yield, 6)

    daily_return_pct = (
        round((close_equity / prev_close - 1.0) * 100.0, 6) if prev_close else 0.0
    )
    # Day 1 convention: first ever bar has a 0.0 daily return.
    if not daily:
        daily_return_pct = 0.0

    first_open = float(daily[0]["open_equity"]) if daily else prev_close
    cumulative_return_pct = (
        round((close_equity / first_open - 1.0) * 100.0, 6) if first_open else 0.0
    )

    peak = close_equity
    for d in daily:
        peak = max(peak, float(d.get("close_equity", 0.0)))
    drawdown_pct = round((close_equity / peak - 1.0) * 100.0, 6) if peak else 0.0

    bar = {
        "date": date,
        "open_equity": round(prev_close, 2),
        "close_equity": round(close_equity, 2),
        "high_equity": round(max(prev_close, close_equity), 2),
        "low_equity": round(min(prev_close, close_equity), 2),
        "snapshots": 1,
        "daily_return_pct": daily_return_pct,
        "cumulative_return_pct": cumulative_return_pct,
        "drawdown_pct": drawdown_pct,
        # SPA-V409: flat fields requested for the real cycle track record.
        "equity": round(close_equity, 2),
        "apy_today": round(apy_today_pct, 4),
        "daily_yield_usd": round(daily_yield, 4),
        "positions": {p: round(v, 2) for p, v in positions.items()},
        # HONEST TRACK RESET (2026-06-26): a bar written by THIS running cycle is,
        # by construction, evidence that a real daily_cycle ran today. Label it as
        # such so the go-live track (track_evidence / golive_checker / gap_monitor)
        # counts it honestly without relying on a post-hoc log scan. Flat-rate
        # backfill / reconstructed bars are NEVER written here, so they never get
        # source="cycle".
        "source": "cycle",
        "evidenced": True,
        # N3(b): "live" when the day's yield was accrued from a live feed, or
        # "fallback" when it was derived from a fallback file (adapter_status.json
        # / adapter_registry.json). Makes the track auditable for fabricated /
        # fallback accrual — a bar of mostly-fallback yield is NOT unimpeachable.
        "accrual_source": "fallback" if accrual_source == "fallback" else "live",
    }
    daily.append(bar)
    daily = daily[-MAX_EQUITY_POINTS:]  # ring-buffer

    equity_doc = {
        "generated_at": run_ts,
        "source": "cycle_runner",
        "execution_mode": "read_only_simulation",
        "is_demo": False,
        "summary": _rebuild_summary(daily),
        "daily": daily,
    }
    return equity_doc, close_equity, daily_yield, daily_return_pct


def _write_equity(
    ddir: Path,
    equity_doc: dict,
    prev_equity_usd: float,
    date: str,
    daily_yield_usd: float,
    positions: dict[str, float],
    apy_today_pct: float,
) -> dict:
    """Persist a zero-accrual equity snapshot on HALT / blocked-cycle days.

    Called when the DailyLimitsChecker or another safety gate fires HALT so
    the track record still has an entry for every calendar day without gaps.
    Yield is forced to 0 USD (empty positions → _accrue_daily_yield = 0).

    Args:
        ddir:            data directory (Path).
        equity_doc:      current in-memory equity document.
        prev_equity_usd: previous equity value (informational, not used for
                         accrual — prev_close comes from equity_doc.daily).
        date:            ISO date string for the halted day (``YYYY-MM-DD``).
        daily_yield_usd: intended yield (0.0 on HALT days).
        positions:       current positions (empty dict on full HALT).
        apy_today_pct:   weighted APY (0.0 on HALT days).

    Returns the updated equity_doc.
    """
    run_ts = datetime.now(timezone.utc).isoformat()
    updated_doc, _close, _yield, _ret = _upsert_equity_point(
        equity_doc,
        date=date,
        apy_today_pct=apy_today_pct,
        positions={},   # empty → _accrue_daily_yield returns 0.0
        apy_map={},
        run_ts=run_ts,
    )
    _atomic_write_json(ddir / EQUITY_FILENAME, updated_doc)
    return updated_doc
