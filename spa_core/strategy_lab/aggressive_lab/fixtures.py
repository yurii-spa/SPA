"""
spa_core/strategy_lab/aggressive_lab/fixtures.py — documented FIXTURE matching the Lane 1 schema.

Lane 1 (the lab core/harness) will write the real
``data/aggressive_lab/<id>/realized_series.jsonl`` + ``meta.json``. Until those land, this module
supplies a deterministic fixture that EXACTLY matches the data contract (see __init__.py) so the
risk/ranking layer is buildable, testable, and demonstrable NOW. When Lane 1's files exist, the
loader reads them instead; this fixture is only the offline fallback / the test substrate.

The roster is chosen to exercise the honest-ranking principle (and the red-team):

  • susde_dn          — the canonical "11% sUSDe delta-neutral" (RiskClass C, shape funding_flip):
                        a deep backtest that takes a REAL hit in the Oct-2025 USDe unwind window. The
                        owner must see the −X% next to the 11%.
  • lrt_carry         — LRT carry (RiskClass C, shape depeg): fat ~13% headline, CATASTROPHIC drawdown
                        in the Apr-2026 rsETH depeg window (the red-team "fat APY, buried tail" case).
  • leverage_loop     — levered PT loop (RiskClass C, shape liquidation): ~15% headline, the worst
                        tail of all (the Oct-2025 cascade).
  • points_farm       — incentive/points farm (RiskClass D, shape incentive_decay): high headline that
                        DECAYS; modest tail but the class flags it as not-durable.
  • variant_d         — pure directional ETH restaking (RiskClass B, shape depeg): the red-team
                        "secretly pure ETH-beta" case — must be flagged B/directional, not alpha.
  • thin_new          — a 6-day forward-only track (RiskClass C): the red-team THIN case — must read
                        INSUFFICIENT_DATA, NEVER a degenerate Sharpe.

Each strategy has a deep BACKTEST track spanning 2024-07 .. 2026-05 (covering all stress windows)
and a short FORWARD track (the live accruing paper record). Series are generated deterministically
from a seeded per-day drift + the window shocks — NO randomness, NO network, NO LLM.

stdlib-only, deterministic. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import math
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.strategy_lab.aggressive_lab import REALIZED_SERIES_NAME, META_NAME, STRESS_WINDOWS


# ── per-strategy fixture spec ────────────────────────────────────────────────────────────────────
# daily_drift: the benign daily fractional return outside stress windows (the headline carry).
# window_hits: {window_key: total fractional loss realized over that window in-sample} — the REAL
#   tail the backtest takes when it passes through that event (front-loaded over the window).
_SPEC: Dict[str, dict] = {
    "susde_dn": {
        "risk_class": "C", "risk_shape": "funding_flip", "headline_apy_pct": 11.0,
        "note": "sUSDe delta-neutral: long sUSDe + short ETH perp. Yield = funding carry — paid for "
                "bearing the funding-flip / Ethena-unwind tail.",
        "daily_drift": 11.0 / 100.0 / 365.0,
        "window_hits": {"eth_crash_2024_08": 0.03, "usde_unwind_2025_10": 0.09,
                        "rseth_depeg_2026_04": 0.01},
        "fwd_days": 12,
    },
    "lrt_carry": {
        "risk_class": "C", "risk_shape": "depeg", "headline_apy_pct": 13.0,
        "note": "LRT carry (eETH/rsETH PT). Fat headline; the yield is compensation for the depeg "
                "tail that hit Aug-2024 and Apr-2026.",
        "daily_drift": 13.0 / 100.0 / 365.0,
        "window_hits": {"eth_crash_2024_08": 0.05, "usde_unwind_2025_10": 0.04,
                        "rseth_depeg_2026_04": 0.22},   # CATASTROPHIC depeg — the red-team buried tail
        "fwd_days": 12,
    },
    "leverage_loop": {
        "risk_class": "C", "risk_shape": "liquidation", "headline_apy_pct": 15.0,
        "note": "Levered PT carry loop. Highest headline; the worst liquidation-cascade tail (Oct-2025).",
        "daily_drift": 15.0 / 100.0 / 365.0,
        "window_hits": {"eth_crash_2024_08": 0.06, "usde_unwind_2025_10": 0.28,
                        "rseth_depeg_2026_04": 0.11},
        "fwd_days": 12,
    },
    "points_farm": {
        "risk_class": "D", "risk_shape": "incentive_decay", "headline_apy_pct": 14.0,
        "note": "Points / airdrop farm. High headline but DECAYS (incentive class) — not a durable edge.",
        "daily_drift": 14.0 / 100.0 / 365.0,
        "window_hits": {"eth_crash_2024_08": 0.01, "usde_unwind_2025_10": 0.02,
                        "rseth_depeg_2026_04": 0.015},
        "fwd_days": 12,
    },
    "variant_d": {
        "risk_class": "B", "risk_shape": "depeg", "headline_apy_pct": 9.0,
        "note": "Pure directional ETH restaking (NO hedge). Secretly ETH beta — flagged B/directional.",
        "daily_drift": 9.0 / 100.0 / 365.0,
        "window_hits": {"eth_crash_2024_08": 0.18, "usde_unwind_2025_10": 0.10,
                        "rseth_depeg_2026_04": 0.20},   # moves with the market — directional, not alpha
        "fwd_days": 12,
    },
    "thin_new": {
        "risk_class": "C", "risk_shape": "funding_flip", "headline_apy_pct": 12.0,
        "note": "A brand-new sleeve — only 6 forward days. Must read INSUFFICIENT_DATA, not a Sharpe.",
        "daily_drift": 12.0 / 100.0 / 365.0,
        "window_hits": {},
        "fwd_days": 6,            # the red-team THIN track — too few points for a trustworthy ratio
        "no_backtest": True,
    },
}

_BACKTEST_START = datetime.date(2024, 7, 1)
_BACKTEST_END = datetime.date(2026, 5, 31)
_FORWARD_END = datetime.date(2026, 6, 28)   # the live track's most recent day (deterministic stamp)
_INITIAL = 100_000.0


def _window_for(d: datetime.date) -> Optional[dict]:
    for w in STRESS_WINDOWS:
        lo = datetime.date.fromisoformat(str(w["date_from"]))
        hi = datetime.date.fromisoformat(str(w["date_to"]))
        if lo <= d <= hi:
            return w
    return None


def _build_backtest_series(spec: dict) -> List[dict]:
    """Deterministic daily equity from 2024-07-01..2026-05-31: benign drift + front-loaded window
    losses spread across each window's days. NO randomness — pure, reproducible."""
    drift = float(spec["daily_drift"])
    window_hits: Dict[str, float] = spec.get("window_hits", {})
    # precompute per-window per-day loss fraction (front-loaded geometrically over the window days)
    series: List[dict] = []
    eq = _INITIAL
    d = _BACKTEST_START
    # build a map: date -> daily loss fraction from the active window
    # to front-load, we compute window day-index on the fly
    window_day_counters: Dict[str, int] = {}
    window_lengths: Dict[str, int] = {}
    for w in STRESS_WINDOWS:
        lo = datetime.date.fromisoformat(str(w["date_from"]))
        hi = datetime.date.fromisoformat(str(w["date_to"]))
        window_lengths[str(w["key"])] = (hi - lo).days + 1
    while d <= _BACKTEST_END:
        w = _window_for(d)
        daily_loss = 0.0
        if w is not None:
            key = str(w["key"])
            total = float(window_hits.get(key, 0.0))
            if total > 0:
                n = window_lengths[key]
                idx = window_day_counters.get(key, 0)
                window_day_counters[key] = idx + 1
                # geometric front-load: most of the loss lands in the first ~third
                norm = sum(0.5 ** j for j in range(n))
                frac = (0.5 ** idx) / norm if norm > 0 else 0.0
                daily_loss = total * frac
        eq = eq * (1.0 + drift - daily_loss)
        series.append({"date": d.isoformat(), "equity_usd": round(eq, 2), "phase": "backtest"})
        d += datetime.timedelta(days=1)
    return series


def _build_forward_series(spec: dict) -> List[dict]:
    """A short, benign forward track (the live accruing paper record) ending _FORWARD_END."""
    drift = float(spec["daily_drift"])
    n = int(spec["fwd_days"])
    series: List[dict] = []
    eq = _INITIAL
    start = _FORWARD_END - datetime.timedelta(days=n - 1)
    d = start
    while d <= _FORWARD_END:
        eq = eq * (1.0 + drift)
        series.append({"date": d.isoformat(), "equity_usd": round(eq, 2), "phase": "forward"})
        d += datetime.timedelta(days=1)
    return series


def strategy_jsonl(strategy_id: str) -> str:
    """The realized_series.jsonl content (one JSON object per line) for a fixture strategy."""
    spec = _SPEC[strategy_id]
    lines: List[str] = []
    if not spec.get("no_backtest"):
        for p in _build_backtest_series(spec):
            lines.append(json.dumps(p, sort_keys=True))
    for p in _build_forward_series(spec):
        lines.append(json.dumps(p, sort_keys=True))
    return "\n".join(lines) + "\n"


def strategy_meta(strategy_id: str) -> dict:
    spec = _SPEC[strategy_id]
    return {
        "strategy_id": strategy_id,
        "risk_class": spec["risk_class"],
        "risk_shape": spec["risk_shape"],
        "headline_apy_pct": spec["headline_apy_pct"],
        "note": spec["note"],
        "is_advisory": True,
        "outside_riskpolicy": True,
    }


def roster() -> List[str]:
    return sorted(_SPEC.keys())


def materialize(data_dir: Path) -> Path:
    """Write the full fixture roster under ``data_dir`` (one subdir per strategy with
    realized_series.jsonl + meta.json). Returns the root. Used by tests + the offline smoke run."""
    root = Path(data_dir)
    for sid in roster():
        sdir = root / sid
        sdir.mkdir(parents=True, exist_ok=True)
        (sdir / REALIZED_SERIES_NAME).write_text(strategy_jsonl(sid), encoding="utf-8")
        (sdir / META_NAME).write_text(
            json.dumps(strategy_meta(sid), indent=2, sort_keys=True), encoding="utf-8")
    return root
