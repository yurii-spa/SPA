"""
spa_core/strategy_lab/aggressive_lab/risk_metrics.py — honest realized risk metrics per track.

For ONE track (a strategy's forward OR backtest series) this computes the metric set the owner
needs to see RETURN with the RISK that earns it:

    realized APY · annualized vol · max-drawdown · Sharpe · Sortino · Calmar (return / max-DD)

THIN-AWARE / TRUSTWORTHY GATE (the WS1.4 fail-closed logic, reused — the existing tournament's
trustworthy:false flaw must NOT recur here):
  • the series passes track_integrity FIRST (gap / duplicate / out-of-order / FUTURE / malformed →
    trustworthy=False, status INSUFFICIENT_DATA, NO numbers — never a metric on a broken series),
  • fewer than MIN_POINTS usable points → Sharpe/Sortino/Calmar = "INSUFFICIENT_DATA" (a 6-day
    Sharpe is a degenerate artifact, not a risk-adjusted score). Return/vol/max-DD are still
    reported where they ARE defined (≥ 2 points) — those are honest at any depth.
  • a locked-volatility series (zero/float-noise dispersion → metrics.sharpe()/sortino() return
    None) → status LOCKED_VOL, ratios "INSUFFICIENT_DATA" (NEVER a fabricated ~4.5e8 Sharpe).

Reuses spa_core.strategy_lab.metrics (net_apy_from_equity / max_drawdown_pct / volatility_pct /
sharpe / sortino — the SAME honest, degenerate-Sharpe-guarded helpers the rest of the lab uses) and
spa_core.strategy_lab.track_integrity (the SAME continuity gate). Nothing is reinvented.

stdlib-only, deterministic, fail-CLOSED. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from typing import Any, List, Optional, Sequence

from spa_core.strategy_lab import metrics
from spa_core.strategy_lab import track_integrity as ti

# Minimum usable equity points before a risk-adjusted ratio (Sharpe/Sortino/Calmar) is TRUSTED.
# Mirrors forward_analytics.MIN_POINTS_FOR_RATIO (7 equity points → ≥ 6 daily returns). Below it the
# ratio is a degenerate artifact → INSUFFICIENT_DATA, by design. The red-team's 6-day thin track
# lands here: it gets honest return/vol/maxDD but NO fabricated Sharpe.
MIN_POINTS = 7

# Backlog #5 — annualizing a SHORT window is a fabricated-APY hazard: `total_growth ** (365/n_days)`
# on an 8-day forward track turns a small real gain into a 155–217% "APY" artifact that must NEVER
# reach a customer-facing surface (/packages, scorecard cards). Below this many daily steps the
# annualized figure is NOT a trustworthy APY — we still report the honest PERIOD return, but flag
# `apy_trustworthy=False` and expose the sentinel so a card shows INSUFFICIENT_HISTORY_FOR_APY.
MIN_DAYS_FOR_APY = 30

# The sentinel for "we refuse to emit a number we cannot honestly compute". A STRING, never a
# float — so a consumer can never mistake it for a real (possibly degenerate) ratio.
INSUFFICIENT = "INSUFFICIENT_DATA"
INSUFFICIENT_APY = "INSUFFICIENT_HISTORY_FOR_APY"


def _extract_equity(points: Sequence[dict]) -> Optional[List[float]]:
    """Pull equity_usd from each in-order point; None (fail-CLOSED) on a malformed/non-finite one.
    (loader already drops malformed lines, but a fixture/injected series goes through here too.)"""
    eq: List[float] = []
    for p in points:
        v = p.get("equity_usd")
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return None
        vf = float(v)
        if vf != vf or vf in (float("inf"), float("-inf")):
            return None
        eq.append(vf)
    return eq


def _daily_returns(equity: Sequence[float]) -> List[float]:
    out: List[float] = []
    for i in range(1, len(equity)):
        prev = equity[i - 1]
        out.append((equity[i] / prev - 1.0) if prev > 0 else 0.0)
    return out


def calmar(net_apy_pct: float, max_dd_pct: float) -> Any:
    """Calmar-style ratio: annualized return / max-drawdown. The honest read of 'how much return
    am I getting per unit of the worst loss I actually took'.

      • max-DD == 0 (a flat / monotone-up track) → INSUFFICIENT_DATA, NEVER +inf. A divide-by-zero
        Calmar reads as an infinitely-good strategy when the truth is 'no drawdown observed yet'
        (usually just a thin/flat track). Refusing it is the honest move.
      • otherwise return / max-DD, signed (a negative return → a negative Calmar — honest).
    """
    if max_dd_pct is None or max_dd_pct <= 0.0:
        return INSUFFICIENT
    return round(net_apy_pct / max_dd_pct, 4)


def compute_track_metrics(
    series_doc: Any,
    *,
    name: str = "track",
    min_points: int = MIN_POINTS,
) -> dict:
    """Honest realized risk metrics for ONE track. Fail-CLOSED throughout.

    Returns a dict:
      {name, n_points, first_date, last_date, trustworthy, status, integrity_ok, integrity_reason,
       realized_apy_pct, vol_pct, max_dd_pct, sharpe, sortino, calmar, locked_vol}

    status ∈ {OK, THIN, LOCKED_VOL, INSUFFICIENT_DATA}:
      • INSUFFICIENT_DATA — integrity failed OR empty → trustworthy=False, all metrics None/sentinel.
      • THIN              — clean but < min_points → return/vol/maxDD honest, ratios INSUFFICIENT_DATA,
                            trustworthy=False (a thin Sharpe is not trustworthy).
      • LOCKED_VOL        — enough points but zero/float-noise dispersion → ratios INSUFFICIENT_DATA,
                            trustworthy=False (the degenerate-Sharpe hazard, refused).
      • OK                — enough real, dispersed points → a TRUSTED Sharpe/Sortino/Calmar.
    """
    base = {
        "name": name,
        "n_points": 0,
        "first_date": None,
        "last_date": None,
        "trustworthy": False,
        "status": INSUFFICIENT,
        "integrity_ok": False,
        "integrity_reason": "malformed",
        "realized_apy_pct": None,
        # Backlog #5: the honest cumulative return over the window (no annualization) — always safe to
        # show. `apy_trustworthy` is False when the window is too short to annualize honestly; then
        # `realized_apy_display` carries the INSUFFICIENT_HISTORY_FOR_APY sentinel for cards.
        "period_return_pct": None,
        "apy_trustworthy": False,
        "realized_apy_display": INSUFFICIENT_APY,
        "vol_pct": None,
        "max_dd_pct": None,
        "sharpe": INSUFFICIENT,
        "sortino": INSUFFICIENT,
        "calmar": INSUFFICIENT,
        "locked_vol": False,
    }

    # ── 1. integrity gate (fail-CLOSED) ──
    integ = ti.check_track_integrity(series_doc)
    base["integrity_ok"] = bool(integ["ok"])
    base["integrity_reason"] = integ["reason"]
    base["n_points"] = integ["n_points"]
    base["first_date"] = integ["first_date"]
    base["last_date"] = integ["last_date"]
    if not integ["ok"]:
        return base  # broken track → never a number

    points = ti._coerce_series(series_doc) or []
    if not points:
        return base  # empty track → INSUFFICIENT_DATA

    equity = _extract_equity(points)
    if equity is None:
        base["integrity_ok"] = False
        base["integrity_reason"] = "malformed:non_finite_equity"
        return base

    rets = _daily_returns(equity)

    # ── 2. return / vol / max-DD — honest at any depth ≥ 2 ──
    realized_apy = metrics.net_apy_from_equity(equity)
    max_dd = metrics.max_drawdown_pct(equity)
    vol = metrics.volatility_pct(rets)
    base["realized_apy_pct"] = realized_apy
    base["max_dd_pct"] = max_dd
    base["vol_pct"] = vol
    # Backlog #5 annualization guard: n_days = daily steps in the window. Below MIN_DAYS_FOR_APY the
    # annualized `realized_apy_pct` is an over-annualization artifact (a few days of gain compounded to
    # a year) — keep it in the JSON for continuity but flag it untrustworthy and surface the honest
    # PERIOD return + the sentinel so no card presents the artifact as a realized APY.
    n_days = len(equity) - 1
    total_growth = equity[-1] / equity[0] if equity[0] else 1.0
    base["period_return_pct"] = round((total_growth - 1.0) * 100.0, 4)
    base["apy_trustworthy"] = bool(n_days >= MIN_DAYS_FOR_APY)
    base["realized_apy_display"] = (
        round(realized_apy, 4) if base["apy_trustworthy"] else INSUFFICIENT_APY)

    # ── 3. ratios — THIN-aware + locked-vol-aware (the trustworthy gate) ──
    enough = len(equity) >= min_points
    sh = metrics.sharpe(rets)
    so = metrics.sortino(rets)
    locked_vol = bool(enough and (sh is None or so is None))
    base["locked_vol"] = locked_vol

    if not enough:
        base["status"] = "THIN"
        base["trustworthy"] = False
        # sharpe/sortino/calmar stay INSUFFICIENT_DATA
        return base
    if locked_vol:
        base["status"] = "LOCKED_VOL"
        base["trustworthy"] = False
        return base

    base["sharpe"] = sh if sh is not None else INSUFFICIENT
    base["sortino"] = so if so is not None else INSUFFICIENT
    base["calmar"] = calmar(realized_apy, max_dd)
    # trustworthy only when the headline ratio is a real number.
    base["trustworthy"] = bool(base["sharpe"] != INSUFFICIENT)
    base["status"] = "OK" if base["trustworthy"] else "LOCKED_VOL"
    return base
