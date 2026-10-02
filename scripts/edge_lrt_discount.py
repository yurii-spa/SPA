"""
edge_lrt_discount.py — Idea #121 LDR: LRT/LST Discount Reversion — «покупать ezETH/weETH/rETH,
когда рынок отдаёт их дешевле справедливого курса к ETH, и ждать возврата».

Hypothesis. A liquid-restaking token trades against ETH at market ratio R_t; its fair value
drifts slowly (accrued staking/restaking yield). A print far BELOW the trailing fair value
(dev_t = R_t / median(R_{t-30..t-1}) − 1 < −k) is a temporary discount (forced sellers, a
withdrawal queue, a points rotation); buying it and holding to reversion harvests the gap
on top of the token's own yield. This is the textbook LST-discount trade, and nothing in the
registry (#1…#120) tests it: #116 LYP ranks staking APRs, #117/#118 are Pendle PT, the
depeg entries are hedges against a depeg, not a harvest of one.

What this file actually establishes — the precondition, measured, before any P&L:
the only price history in the repository (data/rates_desk/prices_deep.json, the rates-desk
retro feed) is measured on its NEGATIVE CONTROL first. stETH and eETH are rebasing 1:1
claims on ETH whose market ratio barely moves; any "discount reversion" the rule finds on
them is measurement, not market. If the control shows an edge as large as the LRTs do, the
series cannot tell a discount from noise and the verdict is the third outcome — НЕ ИЗМЕРЕНО
— never a number (invariant #17).

Two diagnostics, both stated with their reason:
  • lag-1 autocorrelation of daily Δlog R. White measurement noise on a LEVEL gives exactly
    −0.5 after differencing; a real slowly-mean-reverting discount gives a value near 0.
  • the naive rule's gross return on the control vs on the LRTs (same k, same horizon).

ADVISORY / OUTSIDE_RISKPOLICY / IS_ADVISORY=True. stdlib-only, no network, LLM FORBIDDEN.
Never imports spa_core.execution. Reads data/rates_desk read-only (SPA_RATES_DIR).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

ROOT = Path(__file__).resolve().parent.parent
RATES_DIR = Path(os.environ.get("SPA_RATES_DIR") or (ROOT / "data" / "rates_desk"))

CONTROLS: Tuple[str, ...] = ("steth", "eeth")          # rebasing 1:1 claims — the negative control
LRTS: Tuple[str, ...] = ("ezeth", "weeth", "reth")      # accruing tokens — the hypothesis
FAIR_WINDOW = 30
K_BP = 50.0               # entry: dev below −50 bp
ROUNDTRIP_BP = 10.0       # LST/ETH DEX swap in+out, deliberately cheap (favours the hypothesis)
#: |lag-1 AC| this close to −0.5 means the level is dominated by white measurement noise.
NOISE_AC = -0.35
#: control fake edge at least this fraction of the LRT edge ⇒ the series cannot separate them.
CONTROL_RATIO = 0.5


class Refusal(RuntimeError):
    pass


def load_prices(rates_dir: Optional[Path] = None) -> Dict[str, Dict[str, float]]:
    # resolved at CALL time: a default bound at import would ignore a patched RATES_DIR and a
    # test of the absent-file refusal would pass only on trees that happen to lack data/
    p = (rates_dir if rates_dir is not None else RATES_DIR) / "prices_deep.json"
    if not p.is_file():
        raise Refusal(f"{p} absent — НЕ ИЗМЕРЕНО (set SPA_RATES_DIR)")
    series = json.loads(p.read_text()).get("series")
    if not isinstance(series, dict) or "eth" not in series:
        raise Refusal(f"{p}: no 'series.eth' — НЕ ИЗМЕРЕНО")
    return {k: {d: float(v) for d, v in s.items() if v} for k, s in series.items()}


def ratio(prices: Dict[str, Dict[str, float]], asset: str) -> List[Tuple[str, float]]:
    eth = prices["eth"]
    a = prices.get(asset) or {}
    return [(d, a[d] / eth[d]) for d in sorted(set(a) & set(eth)) if eth[d] > 0 and a[d] > 0]


def lag1_ac(xs: Sequence[float]) -> Optional[float]:
    if len(xs) < 3:
        return None
    m = statistics.fmean(xs)
    den = sum((x - m) ** 2 for x in xs)
    if den == 0:
        return None
    return sum((xs[i] - m) * (xs[i - 1] - m) for i in range(1, len(xs))) / den


def diagnostics(r: Sequence[Tuple[str, float]]) -> Dict[str, Optional[float]]:
    ch = [math.log(r[i][1] / r[i - 1][1]) for i in range(1, len(r))]
    vals = [v for _, v in r]
    return {
        "n": float(len(r)),
        "sd_bp": statistics.pstdev(ch) * 1e4 if len(ch) > 1 else None,
        "lag1_ac": lag1_ac(ch),
        "min_ratio": min(vals) if vals else None,
        "min_date": r[vals.index(min(vals))][0] if vals else None,  # type: ignore[dict-item]
    }


def naive_rule(r: Sequence[Tuple[str, float]], k_bp: float = K_BP,
               roundtrip_bp: float = ROUNDTRIP_BP) -> Dict[str, float]:
    """Enter at print t when dev_t < −k (fair = median of the 30 PRIOR prints), exit at the next
    print. Causal in the decision; NOT causal in the fill — it buys at the very print it reads,
    which is exactly what makes noise look like edge. That is the point of running it on the
    control. Returns gross/net bp per trade and trades per year of the sample."""
    trades: List[float] = []
    for i in range(FAIR_WINDOW, len(r) - 1):
        fair = statistics.median(v for _, v in r[i - FAIR_WINDOW:i])
        dev = r[i][1] / fair - 1.0
        if dev * 1e4 < -k_bp:
            trades.append((r[i + 1][1] / r[i][1] - 1.0) * 1e4)
    n = len(trades)
    years = max(len(r) / 365.0, 1e-9)
    gross = statistics.fmean(trades) if trades else 0.0
    return {"trades": float(n), "gross_bp": gross, "net_bp": gross - roundtrip_bp,
            "per_year": n / years, "net_bp_yr": (gross - roundtrip_bp) * n / years}


def verdict(diag: Dict[str, Dict[str, Optional[float]]], edge: Dict[str, Dict[str, float]]) -> Tuple[str, str]:
    """('MEASURED' | 'НЕ ИЗМЕРЕНО', reason). Fail-CLOSED: any missing diagnostic is a refusal."""
    for a in CONTROLS + LRTS:
        if a not in diag or diag[a]["lag1_ac"] is None:
            return "НЕ ИЗМЕРЕНО", f"{a}: no diagnostic (series absent or too short)"
    noisy = [a for a in CONTROLS if (diag[a]["lag1_ac"] or 0.0) <= NOISE_AC]
    if noisy:
        return "НЕ ИЗМЕРЕНО", (f"negative control {', '.join(noisy)} has lag-1 AC ≤ {NOISE_AC} "
                               f"(white noise on the level gives −0.5) — the series' own noise "
                               f"is the signal the rule trades")
    ctrl = max(edge[a]["gross_bp"] for a in CONTROLS)
    lrt = max(edge[a]["gross_bp"] for a in LRTS)
    if lrt <= 0 or ctrl >= CONTROL_RATIO * lrt:
        return "НЕ ИЗМЕРЕНО", (f"control fake edge {ctrl:.0f} bp/trade vs LRT {lrt:.0f} — "
                               f"the series cannot tell a discount from noise")
    return "MEASURED", "control is quiet and LRT edge exceeds it"


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Idea #121 — LRT discount reversion (precondition first)")
    ap.parse_args(argv)
    try:
        prices = load_prices()
    except Refusal as e:
        print(f"НЕ ИЗМЕРЕНО: {e}")
        return 2
    diag: Dict[str, Dict[str, Optional[float]]] = {}
    edge: Dict[str, Dict[str, float]] = {}
    print(f"{'asset':7s} {'role':8s} {'n':>4s} {'sd Δlog bp':>10s} {'lag1 AC':>8s} {'min R':>7s} {'on':>10s} | "
          f"{'trades':>6s} {'gross bp':>8s} {'net bp':>7s} {'net bp/yr':>9s}")
    for a in CONTROLS + LRTS:
        r = ratio(prices, a)
        if len(r) < FAIR_WINDOW + 2:
            continue
        diag[a] = diagnostics(r)
        edge[a] = naive_rule(r)
        d, e = diag[a], edge[a]
        print(f"{a:7s} {'CONTROL' if a in CONTROLS else 'LRT':8s} {d['n']:4.0f} {d['sd_bp']:10.1f} "
              f"{d['lag1_ac']:8.3f} {d['min_ratio']:7.4f} {d['min_date']!s:>10s} | {e['trades']:6.0f} "
              f"{e['gross_bp']:8.1f} {e['net_bp']:7.1f} {e['net_bp_yr']:9.0f}")
    v, why = verdict(diag, edge)
    print(f"\nverdict: {v} — {why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
