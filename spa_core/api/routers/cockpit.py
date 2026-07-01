"""Desk-Cockpit router — the NORMALIZED read-API the Cockpit screens consume
(Sprint-0, Lane A: SPA-001 + SPA-002).

This is a READ-ONLY RESHAPE facade, NOT a new emitter or a new risk engine. Every
endpoint here MERGES / re-projects data the SPA engines already produce into the
ONE contract shape the Cockpit PRD §3 defines. NO-FORK: it reuses kill_switch.py,
rate_policy verdicts, the rates-desk decision_log, DFB alerts, market_regime.json,
the strategy-lab backtest, and exit-nav — it never re-derives risk math.

Doctrine (matches the whole file family: live.py / rates_desk.py):
  • READ-ONLY, GET-only, deterministic, LLM FORBIDDEN, no execution/ import.
  • fail-CLOSED + never-500: a missing/corrupt source degrades to an honest
    ``available: false`` / ``UNKNOWN`` / empty list — NEVER a fabricated value,
    NEVER a 5xx (the Cockpit must not break on absent data).
  • Every response carries ``ts`` (epoch seconds) + ``stale`` (bool). A THIN /
    absent metric is ``UNKNOWN`` (fail-closed), never a made-up number.
  • advisory: moves no capital, touches no go-live track.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import logging
import time as _time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from spa_core.api._shared import (
    NO_CACHE_HEADERS,
    data_dir,
    parse_log_line,
    read_state,
    scrub_nonfinite,
    sleeve_yield_basis,
)

log = logging.getLogger("spa.api")

router = APIRouter(tags=["cockpit"])

# A merged decision/refusal feed is STALE if its newest row is older than this.
# The rates-desk paper tick runs hourly; > ~2h means the producer is lagging →
# the feed must be flagged stale, never shown as if fresh.
_FEED_STALE_SEC: float = 2.0 * 3600.0
# The regime file is written every daily cycle; > ~26h means the writer lags.
_REGIME_STALE_SEC: float = 26.0 * 3600.0
# The strategy-lab / kill-gauge snapshots are refreshed each cycle (~daily).
_SNAPSHOT_STALE_SEC: float = 26.0 * 3600.0


# ── Refusal-reason enum (the Cockpit contract) ────────────────────────────────
# The contract fixes FIVE machine reasons. We map SPA's REAL refusal reasons onto
# them HONESTLY — an unmapped/unknown source reason is surfaced verbatim under
# ``reason_raw`` and the enum is set to the closest honest bucket or left as the
# generic ``liquidity``/None fallback, NEVER invented.
REFUSAL_REASONS = (
    "spread_below_fee_drag",  # edge below the fee/haircut drag → not worth it
    "funding_flip_risk",      # funding regime could flip the carry negative
    "counterparty_flag",      # protocol/peg/oracle/red-flag on the counterparty
    "oi_concentration",       # open-interest / position concentration risk
    "liquidity",              # thin exit liquidity / size floor / depth
)

# Real rates-desk / refusal-engine reason tokens → contract enum. These are the
# ACTUAL reason strings emitted by rate_policy.py (decision_log ``reason`` /
# detail.note) and the refusal engine's tail-score groups. Anything not here is
# left unmapped (enum=None) with the raw reason preserved — honest, not invented.
_REASON_MAP: dict[str, str] = {
    # spread / edge below drag
    "size_floor": "liquidity",            # size below min-tradeable → thin-liquidity bucket
    "below_floor": "spread_below_fee_drag",
    "net_edge_below_floor": "spread_below_fee_drag",
    "negative_edge": "spread_below_fee_drag",
    "fee_drag": "spread_below_fee_drag",
    "haircut": "spread_below_fee_drag",
    "structural_haircut": "spread_below_fee_drag",
    # funding
    "funding_flip": "funding_flip_risk",
    "funding_flip_risk": "funding_flip_risk",
    "funding_regime": "funding_flip_risk",
    # counterparty (peg / oracle / protocol / red-flags / depeg)
    "peg": "counterparty_flag",
    "peg_haircut": "counterparty_flag",
    "depeg": "counterparty_flag",
    "oracle": "counterparty_flag",
    "oracle_haircut": "counterparty_flag",
    "protocol": "counterparty_flag",
    "protocol_haircut": "counterparty_flag",
    "red_flag": "counterparty_flag",
    "counterparty": "counterparty_flag",
    # concentration
    "oi_concentration": "oi_concentration",
    "concentration": "oi_concentration",
    # liquidity / depth
    "liquidity": "liquidity",
    "liquidity_haircut": "liquidity",
    "exit_liquidity": "liquidity",
    "depth": "liquidity",
    "thin": "liquidity",
    "insufficient_contemporaneous_depth": "liquidity",
}


def _map_reason(raw: Any) -> str | None:
    """Map a real refusal-reason token to the contract enum, HONESTLY.

    Returns the enum string when the raw reason is recognised, else ``None``
    (never invents a reason). Matching is case-insensitive on the normalised
    token and also on substring for compound reasons (e.g. ``"size_floor"``).
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    tok = raw.strip().lower().replace("-", "_").replace(" ", "_")
    if tok in _REASON_MAP:
        return _REASON_MAP[tok]
    # substring pass — compound reasons like "peg_haircut_0.03" or "size_floor(...)"
    for key, enum in _REASON_MAP.items():
        if key in tok:
            return enum
    return None


def _epoch_from_iso(ts: Any) -> float | None:
    """Best-effort epoch seconds from an ISO-8601 string; None if unparseable."""
    if not isinstance(ts, str) or not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def _stale_from_newest(newest_epoch: float | None, window_sec: float) -> bool:
    """fail-CLOSED staleness: unknown/absent newest timestamp → stale=True."""
    if newest_epoch is None:
        return True
    return (_time.time() - newest_epoch) > window_sec


# ─── Decision-log ingestion (shared by /api/decisions + /api/refusals) ─────────

def _read_rates_desk_rows() -> list[dict]:
    """All rates-desk decision_log.jsonl rows (fail-CLOSED to []). Read-only."""
    path = data_dir() / "rates_desk" / "decision_log.jsonl"
    rows: list[dict] = []
    if not path.exists():
        return rows
    try:
        for ln in path.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            parsed = parse_log_line(ln, corrupt_marker=None)
            # fail-CLOSED: drop non-JSON / non-finite / non-dict lines.
            if isinstance(parsed, dict):
                rows.append(parsed)
    except OSError as e:  # noqa: BLE001
        log.warning(f"cockpit: rates-desk decision log read failed: {e}")
    return rows


def _normalize_decision(row: dict) -> dict:
    """Rates-desk ENTRY row → contract Decision.

    Decision {ts, type:"decision", engine, action, ref, summary}
    """
    dec = row.get("decomposition") or {}
    detail = row.get("detail") or {}
    underlying = row.get("underlying") or dec.get("underlying")
    action = detail.get("action") or ("enter" if row.get("approved") else "hold")
    shape = row.get("shape")
    net_edge = row.get("net_edge")
    summary_bits = []
    if underlying:
        summary_bits.append(str(underlying))
    if shape:
        summary_bits.append(str(shape))
    if net_edge is not None:
        try:
            summary_bits.append(f"net_edge {float(net_edge) * 100:.2f}%")
        except (TypeError, ValueError):
            pass
    return {
        "ts": row.get("ts"),
        "type": "decision",
        "engine": "rates_desk",
        "action": str(action),
        "ref": row.get("entry_hash") or row.get("proof_hash"),
        "summary": " · ".join(summary_bits) or "rates-desk entry",
    }


def _normalize_refusal(row: dict) -> dict:
    """Rates-desk REFUSAL row → contract Refusal.

    Refusal {ts, type:"refusal", opportunity, reason(enum), expected_edge_pct,
             fee_drag_pct, verdict, capital_protected_est_usd}
    """
    dec = row.get("decomposition") or {}
    detail = row.get("detail") or {}
    underlying = row.get("underlying") or dec.get("underlying")
    raw_reason = row.get("reason") or detail.get("note")
    enum_reason = _map_reason(raw_reason)

    # expected edge (net_edge is a fraction in the log) → percent, honest None.
    edge_pct: float | None = None
    if row.get("net_edge") is not None:
        try:
            edge_pct = round(float(row["net_edge"]) * 100.0, 4)
        except (TypeError, ValueError):
            edge_pct = None

    # fee/haircut drag: total_haircut is a fraction → percent.
    fee_drag_pct: float | None = None
    if dec.get("total_haircut") is not None:
        try:
            fee_drag_pct = round(float(dec["total_haircut"]) * 100.0, 4)
        except (TypeError, ValueError):
            fee_drag_pct = None

    # capital protected: the size that WOULD have been deployed but was refused.
    # We use the exit_cap / approved_size the refusal declined (honest; the desk
    # is paper so this is an estimate, labelled _est_usd). UNKNOWN → None.
    protected: float | None = None
    for k in ("exit_cap", "approved_size_usd", "min_tradeable_size_usd"):
        v = detail.get(k)
        if v is not None:
            try:
                protected = round(float(v), 2)
                break
            except (TypeError, ValueError):
                continue

    return {
        "ts": row.get("ts"),
        "type": "refusal",
        "opportunity": (str(underlying) if underlying else None),
        "reason": enum_reason,             # enum or None (never invented)
        "reason_raw": raw_reason,          # honest original token
        "expected_edge_pct": edge_pct,     # None = UNKNOWN
        "fee_drag_pct": fee_drag_pct,      # None = UNKNOWN
        "verdict": "REFUSE",
        "capital_protected_est_usd": protected,  # None = UNKNOWN
        "engine": "rates_desk",
        "ref": row.get("entry_hash") or row.get("proof_hash"),
    }


def _read_dfb_alert_rows() -> list[dict]:
    """DFB alerts (data/dfb/alerts.json) as contract-shaped ALERT decisions.

    Read-only, fail-CLOSED to []. DFB alerts are risk-first advisory signals; we
    fold them into the unified DECISION feed as engine=dfb rows (type=decision,
    action=alert) — they are not refusals, they are surfaced signals.
    """
    raw = read_state("dfb/alerts.json", None)
    if not isinstance(raw, dict):
        return []
    alerts = raw.get("alerts")
    if not isinstance(alerts, list):
        return []
    out: list[dict] = []
    for a in alerts:
        if not isinstance(a, dict):
            continue
        out.append({
            "ts": a.get("ts") or a.get("as_of") or raw.get("as_of"),
            "type": "decision",
            "engine": "dfb",
            "action": "alert",
            "ref": a.get("alert_hash") or a.get("pool_id"),
            "summary": (
                f"{a.get('severity', 'alert')}: {a.get('pool_id') or a.get('symbol') or ''} "
                f"{a.get('message') or a.get('kind') or ''}"
            ).strip(),
        })
    return out


def _since_filter(rows: list[dict], since: str | None) -> list[dict]:
    """Keep rows with ts >= since (ISO or epoch); tolerant/fail-open on parse."""
    if not since:
        return rows
    since_ep = _epoch_from_iso(since)
    if since_ep is None:
        try:
            since_ep = float(since)
        except (TypeError, ValueError):
            return rows  # unparseable filter → do not silently drop everything
    kept = []
    for r in rows:
        ep = _epoch_from_iso(r.get("ts"))
        if ep is None or ep >= since_ep:
            kept.append(r)
    return kept


def _newest_epoch(rows: list[dict]) -> float | None:
    newest: float | None = None
    for r in rows:
        ep = _epoch_from_iso(r.get("ts"))
        if ep is not None and (newest is None or ep > newest):
            newest = ep
    return newest


# ─── SPA-001a — unified /api/decisions + /api/refusals ─────────────────────────

@router.get("/api/decisions")
def get_decisions(
    since: str | None = Query(default=None, description="ISO or epoch; keep rows at/after"),
    limit: int = Query(default=200, ge=1, le=1000),
):
    """Unified DECISION feed — rates-desk ENTRY rows + DFB alerts, one contract shape.

    Decision {ts, type:"decision", engine, action, ref, summary}. Read-only merge
    of existing sources (NO new emitter). Fail-CLOSED: a missing source is simply
    absent (its rows omitted), never a 500. Carries ``ts`` + ``stale`` (age of the
    newest row vs the producer cadence). Most-recent last.
    """
    rd_rows = _read_rates_desk_rows()
    decisions = [
        _normalize_decision(r) for r in rd_rows if r.get("kind") == "ENTRY"
    ]
    decisions.extend(_read_dfb_alert_rows())

    decisions = _since_filter(decisions, since)
    decisions.sort(key=lambda r: _epoch_from_iso(r.get("ts")) or 0.0)
    newest = _newest_epoch(decisions)
    decisions = decisions[-limit:]

    return JSONResponse(
        scrub_nonfinite({
            "ts": _time.time(),
            "stale": _stale_from_newest(newest, _FEED_STALE_SEC),
            "newest_ts": (
                datetime.fromtimestamp(newest, tz=timezone.utc).isoformat()
                if newest is not None else None
            ),
            "engines": sorted({d["engine"] for d in decisions}),
            "n_decisions": len(decisions),
            "decisions": decisions,
            "advisory": True,
        }),
        headers=NO_CACHE_HEADERS,
    )


@router.get("/api/refusals")
def get_refusals(
    since: str | None = Query(default=None, description="ISO or epoch; keep rows at/after"),
    reason: str | None = Query(default=None, description="filter by contract enum reason"),
    limit: int = Query(default=200, ge=1, le=1000),
):
    """Unified REFUSAL feed — the signature public refusal log, one contract shape.

    Refusal {ts, type:"refusal", opportunity, reason(enum), expected_edge_pct,
    fee_drag_pct, verdict, capital_protected_est_usd}. Reuses the rates-desk
    decision_log REFUSAL rows + rate_policy verdicts (NO-FORK). The real refusal
    reason is mapped to the contract enum HONESTLY (unmapped → reason:null +
    reason_raw preserved, never invented). Fail-CLOSED, never-500, ``ts``+``stale``.
    """
    rd_rows = _read_rates_desk_rows()
    refusals = [
        _normalize_refusal(r) for r in rd_rows if r.get("kind") == "REFUSAL"
    ]

    refusals = _since_filter(refusals, since)
    if reason:
        want = reason.strip().lower()
        refusals = [r for r in refusals if r.get("reason") == want]

    refusals.sort(key=lambda r: _epoch_from_iso(r.get("ts")) or 0.0)
    newest = _newest_epoch(refusals)
    refusals = refusals[-limit:]

    # honest reason histogram (enum + the null bucket for unmapped)
    reason_counts: dict[str, int] = {}
    for r in refusals:
        key = r.get("reason") or "unmapped"
        reason_counts[key] = reason_counts.get(key, 0) + 1

    return JSONResponse(
        scrub_nonfinite({
            "ts": _time.time(),
            "stale": _stale_from_newest(newest, _FEED_STALE_SEC),
            "newest_ts": (
                datetime.fromtimestamp(newest, tz=timezone.utc).isoformat()
                if newest is not None else None
            ),
            "reason_enum": list(REFUSAL_REASONS),
            "reason_counts": reason_counts,
            "n_refusals": len(refusals),
            "refusals": refusals,
            "advisory": True,
        }),
        headers=NO_CACHE_HEADERS,
    )


# ─── SPA-001b — /api/regime (live market_regime passthrough) ───────────────────

@router.get("/api/regime")
def get_regime():
    """Live market regime — passthrough of data/market_regime.json in contract shape.

    Regime {regime, streak, vol, cycle_risk, ...}. The live regime file is written
    every cycle but had no endpoint (Lane-A GAP). Read-only, verbatim-ish reshape;
    fail-CLOSED to ``available:false`` + ``UNKNOWN`` regime when missing/corrupt.
    Carries ``ts`` + ``stale`` (age vs the daily cycle cadence).
    """
    raw = read_state("market_regime.json", {})
    if not raw or not isinstance(raw, dict):
        return JSONResponse(
            {
                "ts": _time.time(), "stale": True, "available": False,
                "regime": "UNKNOWN", "streak": None, "vol": None,
                "cycle_risk": "UNKNOWN", "recommendation": None,
                "detected_at": None,
                "reason": "market_regime.json missing or corrupt (fail-closed)",
            },
            headers=NO_CACHE_HEADERS,
        )
    detected = raw.get("detected_at")
    newest = _epoch_from_iso(detected)
    # vol proxy: the cross-adapter APY std-dev the regime detector already computes.
    vol = raw.get("apy_std_dev")
    # cycle_risk: a coarse honest bucket derived from the regime label (NO new math).
    regime_label = raw.get("regime") or "UNKNOWN"
    cycle_risk = {
        "STABLE": "low",
        "HIGH_YIELD": "elevated",
        "COMPRESSED_YIELD": "low",
        "VOLATILE": "elevated",
    }.get(str(regime_label).upper(), "unknown")
    return JSONResponse(
        scrub_nonfinite({
            "ts": _time.time(),
            "stale": _stale_from_newest(newest, _REGIME_STALE_SEC),
            "available": True,
            "regime": regime_label,
            "streak": raw.get("streak"),          # None if the detector doesn't track it
            "vol": vol,
            "t1_avg_apy": raw.get("t1_avg_apy"),
            "cycle_risk": cycle_risk,
            "recommendation": raw.get("recommendation"),
            "detected_at": detected,
        }),
        headers=NO_CACHE_HEADERS,
    )


# ─── SPA-001b — /api/strategies + /api/strategies/{id} ─────────────────────────

def _reshape_strategy(sid: str, blk: dict, kills: dict) -> dict:
    """strategy_lab_backtest sleeve block → contract StrategySnapshot.

    StrategySnapshot {strategy_id, engine, name, status, allocation, pnl, apy,
    risk{delta,max_dd,sharpe,sortino}, attribution, kill_conditions[],
    liq_nav_by_tier[]}. UNKNOWN/None where THIN/absent (paper desk — honest).
    """
    m = blk.get("metrics", {}) or {}
    extra = m.get("extra", {}) or {}
    kill = blk.get("kill") or kills.get(sid)
    killed = bool(kill) or bool(extra.get("killed"))
    kill_reason = (kill or {}).get("reason") if isinstance(kill, dict) else None

    status = "killed" if killed else ("advisory" if blk.get("is_advisory") else "paper")

    # kill_conditions: the sleeve's realised kill (if any), honestly labelled.
    kill_conditions: list[dict] = []
    if killed and isinstance(kill, dict):
        kill_conditions.append({
            "name": kill.get("type") or "kill",
            "reason": kill_reason,
            "triggered_at": kill.get("date"),
            "status": "kill",
        })

    return {
        "strategy_id": blk.get("id", sid),
        "engine": "strategy_lab",
        "name": blk.get("name", sid),
        "mandate": blk.get("mandate", ""),
        "status": status,
        # paper desk: no live per-strategy allocation is tracked here → UNKNOWN.
        "allocation": None,
        # pnl: equity_last - equity_first when the series is present, else UNKNOWN.
        "pnl": (
            round(float(blk["equity_last"]) - float(blk["equity_first"]), 2)
            if blk.get("equity_last") is not None
            and blk.get("equity_first") is not None
            else None
        ),
        "apy": m.get("net_apy_pct"),
        "risk": {
            "delta": m.get("beta_to_eth"),          # β to ETH ≈ directional delta
            "max_dd": m.get("max_drawdown_pct"),
            "sharpe": m.get("sharpe"),
            "sortino": m.get("sortino"),
            "volatility_pct": m.get("volatility_pct"),
        },
        "attribution": {
            "beats_rwa_floor": m.get("beats_rwa_floor"),
            "funding_drag_pct": m.get("funding_drag_pct"),
            "yield_basis": sleeve_yield_basis(blk.get("id", sid)),
        },
        "kill_conditions": kill_conditions,
        # liq_nav_by_tier: not tracked per lab-sleeve (that's the rates-desk exit-nav
        # ticket ladder, a distinct surface) → honest empty, never fabricated.
        "liq_nav_by_tier": [],
        "is_benchmark": bool(blk.get("is_benchmark")),
        "is_advisory": bool(blk.get("is_advisory")),
    }


def _all_strategies() -> tuple[list[dict], str | None]:
    """Reshape every strategy_lab_backtest sleeve → StrategySnapshot list + generated_at."""
    raw = read_state("strategy_lab_backtest.json", {})
    if not raw or not isinstance(raw, dict):
        return [], None
    kills = raw.get("kills", {}) or {}
    out: list[dict] = []
    for sid, blk in (raw.get("strategies", {}) or {}).items():
        if isinstance(blk, dict):
            out.append(_reshape_strategy(sid, blk, kills))
    manifest = raw.get("manifest", {}) or {}
    return out, manifest.get("generated_at")


@router.get("/api/strategies")
def get_strategies():
    """StrategySnapshot[] — reshape the strategy-lab backtest into the contract shape.

    Read-only reshape of data/strategy_lab_backtest.json (NO-FORK). UNKNOWN/None
    where THIN/absent (paper desk). Fail-CLOSED to an empty list. ``ts``+``stale``.
    """
    strategies, generated_at = _all_strategies()
    newest = _epoch_from_iso(generated_at)
    return JSONResponse(
        scrub_nonfinite({
            "ts": _time.time(),
            "stale": _stale_from_newest(newest, _SNAPSHOT_STALE_SEC),
            "generated_at": generated_at,
            "n_strategies": len(strategies),
            "strategies": strategies,
            "advisory": True,
        }),
        headers=NO_CACHE_HEADERS,
    )


@router.get("/api/strategies/{strategy_id}")
def get_strategy(strategy_id: str):
    """One StrategySnapshot by id — filter of /api/strategies (thin detail route).

    Fail-CLOSED: an unknown id returns ``available:false`` (200, honest), never a
    fabricated strategy and never a 500. ``ts``+``stale``.
    """
    strategies, generated_at = _all_strategies()
    newest = _epoch_from_iso(generated_at)
    match = next(
        (s for s in strategies if s.get("strategy_id") == strategy_id), None
    )
    if match is None:
        return JSONResponse(
            {
                "ts": _time.time(),
                "stale": _stale_from_newest(newest, _SNAPSHOT_STALE_SEC),
                "available": False,
                "strategy_id": strategy_id,
                "reason": "strategy not found (fail-closed, no fabricated snapshot)",
            },
            headers=NO_CACHE_HEADERS,
        )
    return JSONResponse(
        scrub_nonfinite({
            "ts": _time.time(),
            "stale": _stale_from_newest(newest, _SNAPSHOT_STALE_SEC),
            "available": True,
            "generated_at": generated_at,
            "strategy": match,
            "advisory": True,
        }),
        headers=NO_CACHE_HEADERS,
    )


# ─── SPA-002 — Kill-Gauge per-condition headroom ───────────────────────────────

def _read_equity_daily() -> list[dict]:
    """The evidenced equity series (data/equity_curve_daily.json::daily), fail-CLOSED []."""
    doc = read_state("equity_curve_daily.json", {})
    if isinstance(doc, dict):
        daily = doc.get("daily")
        if isinstance(daily, list):
            return daily
    return []


def _drawdown_condition() -> dict:
    """Two-tier drawdown headroom — the ONE condition computable NOW.

    Value = live evidenced drawdown %, thresholds = the REAL SOFT 5% / HARD 10%
    from kill_switch.py (NO-FORK — we call ``evidenced_drawdown_pct``). headroom =
    threshold − value against the NEXT tier boundary. THIN/absent evidenced data →
    status UNKNOWN, headroom null (fail-CLOSED — never a fabricated headroom).
    """
    try:
        from spa_core.governance.kill_switch import (
            DRAWDOWN_THRESHOLD_PCT,
            SOFT_DERISK_THRESHOLD_PCT,
            evidenced_drawdown_pct,
        )
    except Exception as e:  # noqa: BLE001 — fail-CLOSED if the engine is unavailable
        log.warning(f"cockpit kill-gauge: kill_switch import failed: {e}")
        return {
            "name": "drawdown",
            "value": None, "threshold": None, "unit": "pct",
            "headroom_pct": None, "status": "UNKNOWN", "last_triggered": None,
            "reason": "kill_switch engine unavailable (fail-closed)",
        }

    dd = evidenced_drawdown_pct(_read_equity_daily())
    if dd is None:
        return {
            "name": "drawdown",
            "value": None,
            "threshold": DRAWDOWN_THRESHOLD_PCT,
            "soft_threshold": SOFT_DERISK_THRESHOLD_PCT,
            "unit": "pct",
            "headroom_pct": None,
            "status": "UNKNOWN",
            "last_triggered": None,
            "reason": "insufficient/absent evidenced drawdown data (fail-closed)",
        }

    # status by the REAL two-tier ladder (reuse the constants, do not re-derive).
    if dd >= DRAWDOWN_THRESHOLD_PCT:
        status = "kill"
        headroom = 0.0
    elif dd >= SOFT_DERISK_THRESHOLD_PCT:
        status = "warn"
        headroom = round(DRAWDOWN_THRESHOLD_PCT - dd, 4)  # room to HARD kill
    else:
        status = "ok"
        headroom = round(SOFT_DERISK_THRESHOLD_PCT - dd, 4)  # room to SOFT de-risk

    return {
        "name": "drawdown",
        "value": round(dd, 4),
        "threshold": DRAWDOWN_THRESHOLD_PCT,
        "soft_threshold": SOFT_DERISK_THRESHOLD_PCT,
        "unit": "pct",
        "headroom_pct": headroom,
        "status": status,
        "last_triggered": None,  # not tracked in the evidenced series → honest null
        "reason": f"evidenced drawdown {dd:.2f}% (SOFT {SOFT_DERISK_THRESHOLD_PCT}% / "
                  f"HARD {DRAWDOWN_THRESHOLD_PCT}%)",
    }


def _sharpe_condition() -> dict:
    """Sharpe kill headroom — THIN below the min evidenced-bar gate → UNKNOWN.

    NO-FORK: reuses kill_switch's evidenced sharpe path via a KillSwitchChecker
    read. The value is available only with ≥ MIN_DAYS_FOR_SHARPE evidenced bars;
    below that (the THIN paper desk today) it is honestly UNKNOWN, never faked.
    """
    try:
        from spa_core.governance.kill_switch import (
            MIN_DAYS_FOR_SHARPE,
            SHARPE_THRESHOLD,
        )
        from spa_core.paper_trading.track_evidence import (
            PAPER_REAL_START,
            evidenced_daily_returns,
            real_sharpe_ratio,
        )
    except Exception as e:  # noqa: BLE001
        log.warning(f"cockpit kill-gauge: sharpe import failed: {e}")
        return {
            "name": "sharpe", "value": None, "threshold": None, "unit": "ratio",
            "headroom_pct": None, "status": "UNKNOWN", "last_triggered": None,
            "reason": "sharpe engine unavailable (fail-closed)",
        }

    daily = _read_equity_daily()
    ev_returns = evidenced_daily_returns(daily, paper_start=PAPER_REAL_START)
    num_days = len(ev_returns) + 1
    sharpe = real_sharpe_ratio(daily, paper_start=PAPER_REAL_START, risk_free_rate=0.0)

    if sharpe is None or num_days < MIN_DAYS_FOR_SHARPE:
        return {
            "name": "sharpe",
            "value": (round(float(sharpe), 4) if sharpe is not None else None),
            "threshold": SHARPE_THRESHOLD,
            "unit": "ratio",
            "headroom_pct": None,
            "status": "UNKNOWN",
            "last_triggered": None,
            "reason": (
                f"THIN: {num_days} evidenced day(s) < {MIN_DAYS_FOR_SHARPE} required "
                f"→ sharpe headroom UNKNOWN (fail-closed, no fabricated headroom)"
            ),
        }

    sv = float(sharpe)
    # Kill fires when sharpe < threshold (threshold is negative). Headroom = how far
    # ABOVE the kill line, expressed as a ratio gap (unit=ratio, not pct).
    headroom = round(sv - SHARPE_THRESHOLD, 4)
    status = "kill" if sv < SHARPE_THRESHOLD else ("warn" if headroom < 0.5 else "ok")
    return {
        "name": "sharpe",
        "value": round(sv, 4),
        "threshold": SHARPE_THRESHOLD,
        "unit": "ratio",
        "headroom_pct": headroom,
        "status": status,
        "last_triggered": None,
        "reason": f"evidenced sharpe {sv:.4f} vs kill {SHARPE_THRESHOLD}",
    }


def _red_flags_condition() -> dict:
    """Red-flags kill headroom — CRITICAL-on-held count vs the threshold.

    NO-FORK: reuses KillSwitchChecker.check_red_flags_trigger's own reason string;
    the count is parsed from the deterministic reason (the checker is the single
    authority). Fail-CLOSED to UNKNOWN if the checker/data is unavailable.
    """
    try:
        from spa_core.governance.kill_switch import (
            RED_FLAGS_THRESHOLD,
            KillSwitchChecker,
        )
    except Exception as e:  # noqa: BLE001
        log.warning(f"cockpit kill-gauge: red_flags import failed: {e}")
        return {
            "name": "red_flags", "value": None, "threshold": None, "unit": "count",
            "headroom_pct": None, "status": "UNKNOWN", "last_triggered": None,
            "reason": "red_flags engine unavailable (fail-closed)",
        }
    try:
        checker = KillSwitchChecker(data_dir=str(data_dir()))
        triggered, reason = checker.check_red_flags_trigger()
    except Exception as e:  # noqa: BLE001
        return {
            "name": "red_flags", "value": None, "threshold": RED_FLAGS_THRESHOLD,
            "unit": "count", "headroom_pct": None, "status": "UNKNOWN",
            "last_triggered": None,
            "reason": f"red_flags check failed (fail-closed): {e}",
        }
    # Parse the "red_flags count N …" from the deterministic reason (the checker's
    # own output is the source of truth; we do not recompute the count ourselves).
    count: int | None = None
    import re as _re
    mt = _re.search(r"count\s+(\d+)", reason)
    if mt:
        try:
            count = int(mt.group(1))
        except ValueError:
            count = None
    if count is None:
        return {
            "name": "red_flags", "value": None, "threshold": RED_FLAGS_THRESHOLD,
            "unit": "count", "headroom_pct": None, "status": "UNKNOWN",
            "last_triggered": None,
            "reason": f"red_flags count unparseable (fail-closed): {reason}",
        }
    headroom = RED_FLAGS_THRESHOLD - count  # kill fires when count > threshold
    status = "kill" if triggered else ("warn" if headroom <= 1 else "ok")
    return {
        "name": "red_flags",
        "value": count,
        "threshold": RED_FLAGS_THRESHOLD,
        "unit": "count",
        "headroom_pct": headroom,
        "status": status,
        "last_triggered": None,
        "reason": reason,
    }


def _manual_condition() -> dict:
    """Manual kill switch — boolean present/absent condition (no headroom)."""
    try:
        from spa_core.governance.kill_switch import KillSwitchChecker
        checker = KillSwitchChecker(data_dir=str(data_dir()))
        triggered, reason = checker.check_manual_trigger()
    except Exception as e:  # noqa: BLE001
        return {
            "name": "manual", "value": None, "threshold": None, "unit": "bool",
            "headroom_pct": None, "status": "UNKNOWN", "last_triggered": None,
            "reason": f"manual check failed (fail-closed): {e}",
        }
    return {
        "name": "manual",
        "value": bool(triggered),
        "threshold": True,
        "unit": "bool",
        "headroom_pct": None,  # boolean — no numeric headroom
        "status": "kill" if triggered else "ok",
        "last_triggered": None,
        "reason": reason,
    }


@router.get("/api/kill-gauge")
def get_kill_gauge():
    """Kill-Gauge — per-kill-condition headroom over kill_switch.py (SPA-002).

    Feeds the signature KillGauge primitive. Each condition:
        {name, value, threshold, unit, headroom_pct, status: ok|warn|kill|UNKNOWN,
         last_triggered}
    The DRAWDOWN headroom is REAL — computed from the live evidenced drawdown vs
    the REAL SOFT 5% / HARD 10% thresholds (NO-FORK: reuses
    ``kill_switch.evidenced_drawdown_pct`` + the module constants). A THIN/absent
    condition (e.g. Sharpe below the min-bar gate) is ``UNKNOWN`` with a null
    headroom — NEVER a fabricated number. Read-only, fail-CLOSED, never-500,
    ``ts``+``stale``.
    """
    conditions = [
        _drawdown_condition(),
        _sharpe_condition(),
        _red_flags_condition(),
        _manual_condition(),
    ]

    # Overall gauge status = worst condition (kill > warn > ok; UNKNOWN never
    # upgrades severity but is surfaced honestly).
    order = {"kill": 3, "warn": 2, "ok": 1, "UNKNOWN": 0}
    worst = max(conditions, key=lambda c: order.get(c.get("status"), 0))
    overall = worst.get("status")
    if overall == "UNKNOWN" and any(
        c.get("status") in ("ok", "warn", "kill") for c in conditions
    ):
        # at least one real condition computed → overall reflects the real ones.
        real = [c for c in conditions if c.get("status") in ("ok", "warn", "kill")]
        overall = max(real, key=lambda c: order.get(c.get("status"), 0)).get("status")

    # Freshness: keyed off the equity series that drives the primary (drawdown)
    # condition; fail-CLOSED to stale when absent.
    doc = read_state("equity_curve_daily.json", {})
    gen = doc.get("generated_at") if isinstance(doc, dict) else None
    newest = _epoch_from_iso(gen)

    return JSONResponse(
        scrub_nonfinite({
            "ts": _time.time(),
            "stale": _stale_from_newest(newest, _SNAPSHOT_STALE_SEC),
            "overall_status": overall,
            "n_conditions": len(conditions),
            "conditions": conditions,
            "thresholds_source": "spa_core.governance.kill_switch (two-tier, ADR-034/048)",
            "advisory": True,
        }),
        headers=NO_CACHE_HEADERS,
    )
