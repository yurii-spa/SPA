"""Swarm block 3 — L1 funding-regime classifier (GREEN / YELLOW / RED carry weather).

Charter: docs/SWARM_ARCHITECTURE.md. The carry books (sUSDe basis, levered PT) earn the perp
funding that longs pay shorts. That income is REGIME-SHAPED: rich and stable in risk-on (GREEN),
compressing/unstable around turns (YELLOW), inverted in risk-off (RED — the "yield" is gone and
the tail is live). The registry's guardian (idea #1) de-risks on the book's OWN realized vol — a
signal that lags the market's. This classifier is the EXOGENOUS, earlier signal: it reads the
5-venue median funding feed (Binance/Bybit/OKX/KuCoin/Hyperliquid — the same quorum discipline as
RTMR) and publishes the current carry regime for the guardians and the future leverage brain
(block 4) to consume.

Deterministic rules on the trailing funding series (thresholds are constants, documented below):
  RED     7d-median funding ≤ 0 (carry inverted), or ≥ RED_NEG_DAYS of the last 7 days negative.
  YELLOW  fast compression (7d median < YELLOW_COMPRESSION × 30d median), funding-vol spike
          (14d vol > YELLOW_VOL_MULT × trailing 60d baseline), or thin carry
          (annualized 7d median < THIN_CARRY_ANN_PCT).
  GREEN   otherwise: positive, stable, worth-holding carry.
  UNKNOWN feed unreachable or < MIN_HISTORY_DAYS of history — fail-CLOSED: consumers must treat
          UNKNOWN as not-GREEN (never assume the weather is fine because the barometer broke).

HONEST LIMITS: funding regime is a SLOW-risk signal (hours→days); it cannot see an exploit or an
instant depeg (gap risk stays in the tail). Thresholds are judgment calibrated on the 2024–26
funding history, not fitted magic — the forward paper track is what validates them. v1 has no
hysteresis (7d/30d medians smooth most flapping); if the forward log shows flapping, add it.

ADVISORY / paper-only: publishes a signal, moves no capital. Writes ONLY data/swarm/.
Deterministic given the feed series, stdlib-only. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from spa_core.strategy_lab.aggressive_lab.guardian import stdev
from spa_core.strategy_lab.swarm.common import append_daily_proof
from spa_core.utils.atomic import atomic_save

__all__ = ["classify", "run_funding_regime", "THRESHOLDS"]

REPO_ROOT = Path(__file__).resolve().parents[3]
SWARM_DIR = REPO_ROOT / "data" / "swarm"
STATUS_NAME = "funding_regime.json"
PROOF_NAME = "funding_regime_proof.jsonl"

SYMBOLS = ("ETH", "BTC")  # ETH is the primary (drives the sUSDe/basis carry books)

THRESHOLDS = {
    "MIN_HISTORY_DAYS": 45,     # need a real baseline before claiming any regime
    "RED_NEG_DAYS": 4,          # ≥4 of the last 7 days negative → carry is inverted in practice
    "YELLOW_COMPRESSION": 0.5,  # 7d median fell below half the 30d median → fast compression
    "YELLOW_VOL_MULT": 2.0,     # 14d funding-vol > 2× trailing 60d baseline → unstable regime
    "THIN_CARRY_ANN_PCT": 5.0,  # annualized 7d carry below this → not worth the tail
}
_PERIODS_PER_YEAR = 3 * 365  # 8h funding periods


def _median(xs: List[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if not n:
        return 0.0
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def classify(series: Dict[str, float]) -> dict:
    """Pure, deterministic regime classification of ONE symbol's daily funding series
    ({date: median 8h funding}). Returns {regime, metrics, reasons}."""
    t = THRESHOLDS
    dates = sorted(series)
    if len(dates) < t["MIN_HISTORY_DAYS"]:
        return {"regime": "UNKNOWN",
                "reasons": [f"history {len(dates)}d < required {t['MIN_HISTORY_DAYS']}d"],
                "metrics": {"history_days": len(dates)}}

    vals = [series[d] for d in dates]
    last7, last14, last30 = vals[-7:], vals[-14:], vals[-30:]
    med7, med30 = _median(last7), _median(last30)
    neg_days_7 = sum(1 for v in last7 if v < 0)
    vol14 = stdev(last14)
    base_window = vals[-74:-14] if len(vals) >= 74 else vals[:-14]
    vol_base = stdev(base_window) or 1e-12
    ann7_pct = med7 * _PERIODS_PER_YEAR * 100.0

    metrics = {
        "history_days": len(dates),
        "last_date": dates[-1],
        "funding_8h_med7": round(med7, 8),
        "funding_8h_med30": round(med30, 8),
        "carry_ann_pct_7d": round(ann7_pct, 3),
        "neg_days_of_last_7": neg_days_7,
        "vol14": round(vol14, 8),
        "vol_baseline_60d": round(vol_base, 8),
        "vol_ratio": round(vol14 / vol_base, 3),
    }

    reasons: List[str] = []
    if med7 <= 0:
        reasons.append(f"7d median funding {med7:+.6f} ≤ 0 — carry inverted")
    if neg_days_7 >= t["RED_NEG_DAYS"]:
        reasons.append(f"{neg_days_7}/7 recent days negative (≥{t['RED_NEG_DAYS']})")
    if reasons:
        return {"regime": "RED", "reasons": reasons, "metrics": metrics}

    if med30 > 0 and med7 < t["YELLOW_COMPRESSION"] * med30:
        reasons.append(f"fast compression: 7d median {med7:.6f} < "
                       f"{t['YELLOW_COMPRESSION']} × 30d median {med30:.6f}")
    if vol14 > t["YELLOW_VOL_MULT"] * vol_base:
        reasons.append(f"funding-vol spike: 14d vol {vol14:.6f} > "
                       f"{t['YELLOW_VOL_MULT']}× baseline {vol_base:.6f}")
    if ann7_pct < t["THIN_CARRY_ANN_PCT"]:
        reasons.append(f"thin carry: {ann7_pct:.2f}% ann < {t['THIN_CARRY_ANN_PCT']}%")
    if reasons:
        return {"regime": "YELLOW", "reasons": reasons, "metrics": metrics}

    return {"regime": "GREEN",
            "reasons": [f"positive, stable carry ≈ {ann7_pct:.1f}% ann"],
            "metrics": metrics}


def _default_provider(symbol: str) -> Dict[str, float]:
    from spa_core.strategy_lab.data.funding_feed import FundingFeed
    return FundingFeed(symbol=symbol).history()


def run_funding_regime(
    provider: Optional[Callable[[str], Dict[str, float]]] = None,
    out_dir: Path = SWARM_DIR,
) -> dict:
    """One classification pass over all SYMBOLS. A provider failure yields UNKNOWN for that
    symbol (fail-closed), never a fabricated regime. Writes status JSON + daily proof line."""
    provider = provider or _default_provider
    per_symbol: Dict[str, dict] = {}
    for sym in SYMBOLS:
        try:
            series = provider(sym)
        except Exception as exc:  # noqa: BLE001 — any feed failure → honest UNKNOWN
            per_symbol[sym] = {"regime": "UNKNOWN",
                               "reasons": [f"feed failed: {type(exc).__name__}: {exc}"],
                               "metrics": {}}
            continue
        per_symbol[sym] = classify(series or {})

    doc = {
        "domain": "swarm.funding_regime",
        "label": "SWARM L1 funding-regime classifier / ADVISORY / signal-only",
        "is_advisory": True,
        "as_of_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "thresholds": THRESHOLDS,
        "primary_symbol": "ETH",
        "regime": per_symbol.get("ETH", {}).get("regime", "UNKNOWN"),
        "symbols": per_symbol,
        "consumer_contract": (
            "UNKNOWN must be treated as not-GREEN (fail-closed). This is a SLOW-risk signal "
            "(hours-days lead); gap risk (exploit/instant depeg) is NOT visible here."
        ),
    }
    atomic_save(doc, str(out_dir / STATUS_NAME))
    payload = {"regime": doc["regime"],
               "per_symbol": {s: v["regime"] for s, v in per_symbol.items()},
               "carry_ann_pct_7d": per_symbol.get("ETH", {}).get("metrics", {})
                                             .get("carry_ann_pct_7d")}
    doc["proof_appended"] = append_daily_proof(payload, out_dir / PROOF_NAME,
                                               day=doc["as_of_utc"][:10])
    return doc


def main() -> int:
    doc = run_funding_regime()
    parts = [f"{s}={v['regime']}" for s, v in doc["symbols"].items()]
    print(f"swarm.funding_regime: {' '.join(parts)} (primary={doc['regime']}) "
          f"proof_appended={doc['proof_appended']}")
    for s, v in doc["symbols"].items():
        m = v.get("metrics", {})
        if m.get("carry_ann_pct_7d") is not None:
            print(f"  {s}: carry≈{m['carry_ann_pct_7d']}% ann, vol_ratio={m.get('vol_ratio')}, "
                  f"reasons: {'; '.join(v['reasons'])}")
        else:
            print(f"  {s}: {'; '.join(v['reasons'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
