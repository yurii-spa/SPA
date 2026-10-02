"""
edge_cads.py — CADS: Crisis-Adaptive Drawdown Stop (#119)

Per-strategy drawdown stop with Calmar-guided reallocation.

Core mechanism: maintain an equal-weight basket of the fixture strategies.
When any individual strategy drops >= STOP_PCT from its own HWM (peak
equity), exit that strategy and redirect its capital to the active
strategy with the best recent rolling Calmar ratio. Re-enter at equal
weight when the strategy recovers to within RE_ENTRY_PCT of its HWM.

Why this is genuinely new vs. the existing registry:
  • #1 Guardian, #11 CPPI, #14 HWMP — portfolio-level gates (whole basket
    goes to cash / reduced total exposure). CADS is per-strategy: only the
    wounded sleeve exits; the others continue at full weight.
  • #9 DDO — reorders depth; does not EXIT and REALLOCATE.
  • #15 KODS — a scalar Kelly multiplier on the whole portfolio, not a
    strategy-selection mechanism.
  • #113 CMRS — uses Sharpe regime; degenerated on σ²=0 fixture.
  CADS uses STOP depth (discrete threshold) + rolling Calmar TARGET
  (non-degenerate: in calm periods maxDD is stable, Calmar is stable,
  so ranking persists; after a stress hit the damaged strategy's Calmar
  drops, correctly ranking it below survivors).

On the fixture this produces STOP events on day-0 of each stress window
(when the front-loaded loss is largest) and avoids the subsequent tail
losses for the stopped strategy. Re-entry happens when the strategy has
recovered within RE_ENTRY_PCT of its HWM.

ADVISORY / OUTSIDE_RISKPOLICY / IS_ADVISORY=True.
Fixture-based: deterministic, stdlib-only, no network. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from spa_core.strategy_lab.aggressive_lab.fixtures import roster, strategy_jsonl

# ── Parameters ────────────────────────────────────────────────────────────────
STOP_PCT: float = 0.05      # exit strategy when it drops >= 5% from its own HWM
RE_ENTRY_PCT: float = 0.03  # re-enter when recovered to within 3% of own HWM
CALMAR_LOOKBACK: int = 60   # days lookback for rolling Calmar (reallocation target)


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_bt_prices(strategy_id: str) -> list[tuple[str, float]]:
    """Return sorted [(date_str, normalised_price)] from backtest phase.
    Price is normalised to 1.0 on the first backtest day."""
    rows: list[tuple[str, float]] = []
    for line in strategy_jsonl(strategy_id).strip().splitlines():
        r = json.loads(line)
        if r.get("phase") == "backtest":
            rows.append((r["date"], float(r["equity_usd"])))
    rows.sort(key=lambda x: x[0])
    if not rows:
        return []
    base = rows[0][1]
    return [(d, eq / base) for d, eq in rows]


def cagr(p_start: float, p_end: float, n_days: int) -> float:
    if n_days <= 0 or p_start <= 0 or p_end <= 0:
        return 0.0
    return (p_end / p_start) ** (365.0 / n_days) - 1.0


def max_drawdown(prices: list[float]) -> float:
    if not prices:
        return 0.0
    peak = prices[0]
    max_dd = 0.0
    for p in prices:
        if p > peak:
            peak = p
        if peak > 0:
            dd = (peak - p) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd


def rolling_calmar(prices: list[float], day_idx: int, lookback: int) -> float:
    """Rolling Calmar over last `lookback` days ending at day_idx."""
    start = max(0, day_idx - lookback + 1)
    window = prices[start:day_idx + 1]
    if len(window) < 5:
        return 0.0
    ann = cagr(window[0], window[-1], len(window))
    mdd = max_drawdown(window)
    if mdd <= 0:
        return ann * 999.0 if ann > 0 else 0.0  # no drawdown → top-ranked
    return ann / mdd


# ── Main backtest ─────────────────────────────────────────────────────────────

def run_cads(
    stop_pct: float = STOP_PCT,
    re_entry_pct: float = RE_ENTRY_PCT,
    calmar_lookback: int = CALMAR_LOOKBACK,
) -> dict:
    """
    Simulate CADS on all fixture backtest strategies except thin_new.

    Returns a results dict with:
      apy_bt, max_dd_bt, calmar_bt — CADS portfolio metrics
      baseline_apy_bt, baseline_max_dd_bt, baseline_calmar_bt — equal-weight baseline
      stop_events, reentry_events — list of (date, strategy_id, dd_pct)
      portfolio_curve — list of normalised portfolio equity
    """
    strats = [s for s in roster() if s != "thin_new"]
    n = len(strats)

    # Aligned price series
    raw: dict[str, list[tuple[str, float]]] = {sid: load_bt_prices(sid) for sid in strats}
    dates = [d for d, _ in raw[strats[0]]]
    n_days = len(dates)
    for sid in strats:
        if len(raw[sid]) != n_days:
            raise RuntimeError(f"Series length mismatch for {sid}")

    prices: dict[str, list[float]] = {sid: [p for _, p in raw[sid]] for sid in strats}

    # ── Equal-weight buy-and-hold baseline ───────────────────────────────
    baseline_curve = [sum(prices[sid][i] for sid in strats) / n for i in range(n_days)]
    baseline_apy = cagr(baseline_curve[0], baseline_curve[-1], n_days) * 100
    baseline_mdd = max_drawdown(baseline_curve) * 100
    baseline_calmar = (baseline_apy / baseline_mdd) if baseline_mdd > 0 else 0.0

    # ── CADS simulation ──────────────────────────────────────────────────
    # Portfolio: strat_shares[sid] * prices[sid][i] = value in strategy sid.
    # Initial: equal value in each strategy; prices[sid][0] = 1.0 so shares = 1/n.
    strat_shares: dict[str, float] = {sid: 1.0 / n for sid in strats}
    stopped: dict[str, bool] = {sid: False for sid in strats}
    strat_hwm: dict[str, float] = {sid: 1.0 for sid in strats}

    portfolio_curve: list[float] = []
    stop_events: list[tuple[str, str, float]] = []
    reentry_events: list[tuple[str, str, float]] = []

    def _pv(i: int) -> float:
        return sum(
            strat_shares[s] * prices[s][i]
            for s in strats
            if not stopped[s]
        )

    def _actives() -> list[str]:
        return [s for s in strats if not stopped[s]]

    def _best_calmar(i: int, exclude: str | None = None) -> str | None:
        candidates = [s for s in _actives() if s != exclude]
        if not candidates:
            return None
        return max(candidates,
                   key=lambda s: rolling_calmar(prices[s], i, calmar_lookback))

    for i in range(n_days):
        # 1. Update per-strategy price HWM
        for sid in strats:
            if prices[sid][i] > strat_hwm[sid]:
                strat_hwm[sid] = prices[sid][i]

        # 2. Check stops
        for sid in strats:
            if stopped[sid]:
                continue
            hwm = strat_hwm[sid]
            p = prices[sid][i]
            dd = (hwm - p) / hwm if hwm > 0 else 0.0
            if dd >= stop_pct:
                proceeds = strat_shares[sid] * p
                strat_shares[sid] = 0.0
                stopped[sid] = True
                stop_events.append((dates[i], sid, round(dd * 100, 1)))
                target = _best_calmar(i, exclude=sid)
                if target is not None:
                    strat_shares[target] += proceeds / prices[target][i]

        # 3. Check re-entries
        for sid in strats:
            if not stopped[sid]:
                continue
            hwm = strat_hwm[sid]
            p = prices[sid][i]
            dd = (hwm - p) / hwm if hwm > 0 else 0.0
            if dd <= re_entry_pct:
                stopped[sid] = False
                reentry_events.append((dates[i], sid, round(dd * 100, 1)))
                # Rebalance all actives (including re-entering) to equal weight
                pv = _pv(i)
                active = _actives()
                if pv > 0 and active:
                    target_val = pv / len(active)
                    for s in active:
                        strat_shares[s] = target_val / prices[s][i]

        # 4. Record portfolio value
        portfolio_curve.append(_pv(i))

    cads_apy = cagr(portfolio_curve[0], portfolio_curve[-1], n_days) * 100
    cads_mdd = max_drawdown(portfolio_curve) * 100
    cads_calmar = (cads_apy / cads_mdd) if cads_mdd > 0 else 0.0

    return {
        "n_days": n_days,
        "n_strats": n,
        "strategies": strats,
        "stop_pct": stop_pct,
        "re_entry_pct": re_entry_pct,
        "calmar_lookback": calmar_lookback,
        "apy_bt": round(cads_apy, 2),
        "max_dd_bt": round(cads_mdd, 2),
        "calmar_bt": round(cads_calmar, 2),
        "baseline_apy_bt": round(baseline_apy, 2),
        "baseline_max_dd_bt": round(baseline_mdd, 2),
        "baseline_calmar_bt": round(baseline_calmar, 2),
        "n_stops": len(stop_events),
        "n_reentries": len(reentry_events),
        "stop_events": stop_events,
        "reentry_events": reentry_events,
        "portfolio_curve": portfolio_curve,
    }


def main() -> None:
    r = run_cads()
    print("=" * 60)
    print("CADS #119 — Crisis-Adaptive Drawdown Stop")
    print("=" * 60)
    print(f"Strategies ({r['n_strats']}): {', '.join(r['strategies'])}")
    print(f"Days: {r['n_days']} | Stop: {r['stop_pct']*100:.0f}% | "
          f"Re-entry: {r['re_entry_pct']*100:.0f}% | Calmar lookback: {r['calmar_lookback']}d")
    print()
    print(f"{'Metric':<22} {'CADS':>10} {'Baseline EW':>12}")
    print("-" * 46)
    print(f"{'APY bt':<22} {r['apy_bt']:>9.2f}% {r['baseline_apy_bt']:>11.2f}%")
    print(f"{'MaxDD bt':<22} {r['max_dd_bt']:>9.2f}% {r['baseline_max_dd_bt']:>11.2f}%")
    print(f"{'Calmar bt':<22} {r['calmar_bt']:>10.2f} {r['baseline_calmar_bt']:>12.2f}")
    print()
    print(f"Stop events ({r['n_stops']}):")
    for d, sid, dd in r['stop_events']:
        print(f"  {d}: {sid} DD_from_HWM={dd:.1f}%")
    print(f"Re-entry events ({r['n_reentries']}):")
    for d, sid, dd in r['reentry_events']:
        print(f"  {d}: {sid} DD_from_HWM={dd:.1f}%")


if __name__ == "__main__":
    if "--real" in sys.argv[1:]:
        # #120 CADS-REAL: this mechanism re-measured on the REAL 10-book panel, decomposed into
        # stop vs target, with costs and a train/test split (scripts/edge_cads_real.py).
        import edge_cads_real
        raise SystemExit(edge_cads_real.main([a for a in sys.argv[1:] if a != "--real"]))
    main()
