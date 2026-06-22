#!/usr/bin/env python3
"""DeFi Protocol Lending Market Health Scorer (SPA / MP-1076) — read-only / advisory.

Computes a composite health score (0–100) for a DeFi lending protocol market
given on-chain supply/borrow/reserve/oracle metrics. Produces a human-readable
health_label for dashboard surfacing.

Design constraints
------------------
* Pure stdlib only — no numpy / scipy / requests / pandas / web3.
* Advisory / read-only: never modifies risk/, execution/, monitoring/, allocator/.
* Atomic writes: tmp + os.replace (POSIX-atomic).
* Ring-buffer log capped at 100 entries in data/lending_market_health_log.json.
* Never raises on the happy path; degenerate inputs degrade gracefully.
* NOT imported from risk/, execution/, monitoring/ (LLM_FORBIDDEN_AGENTS).

Scoring dimensions (weights sum to 1.0)
-----------------------------------------
  utilization_score   (0–100)  — penalises very high or very low utilisation
  bad_debt_score      (0–100)  — penalises bad-debt ratio
  reserve_score       (0–100)  — rewards strong reserve coverage
  concentration_score (0–100)  — penalises top-borrower concentration
  oracle_score        (0–100)  — chainlink > twap > internal
  market_pause_score  (0–100)  — penalises paused markets ratio
  incentive_score     (0–100)  — liquidation incentive in healthy range

  market_health_score = weighted sum (rounded, clamped 0–100)

Labels
------
  PRISTINE   score >= 85
  HEALTHY    score >= 70
  WATCH      score >= 50
  STRESSED   score >= 30
  CRITICAL   score <  30

CLI
---
  python3 -m spa_core.analytics.defi_protocol_lending_market_health_scorer --check
  python3 -m spa_core.analytics.defi_protocol_lending_market_health_scorer --run
  python3 -m spa_core.analytics.defi_protocol_lending_market_health_scorer --run --data-dir PATH
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants & paths
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"

LOG_FILENAME = "lending_market_health_log.json"
RING_BUFFER_CAP = 100

SCHEMA_VERSION = 1
SOURCE_NAME = "defi_protocol_lending_market_health_scorer"
MP_TAG = "MP-1076"

# Score thresholds → labels (descending)
LABEL_PRISTINE = 85.0
LABEL_HEALTHY = 70.0
LABEL_WATCH = 50.0
LABEL_STRESSED = 30.0

# Dimension weights (must sum to 1.0)
WEIGHTS: Dict[str, float] = {
    "utilization":   0.20,
    "bad_debt":      0.25,
    "reserve":       0.20,
    "concentration": 0.10,
    "oracle":        0.10,
    "market_pause":  0.05,
    "incentive":     0.10,
}

# Oracle quality map
ORACLE_SCORES: Dict[str, float] = {
    "chainlink": 100.0,
    "twap":       60.0,
    "internal":   30.0,
}

log = logging.getLogger("spa.analytics.defi_protocol_lending_market_health_scorer")


# ---------------------------------------------------------------------------
# Sub-scorers (pure functions, no IO)
# ---------------------------------------------------------------------------

def _score_utilization(utilization_rate_pct: float) -> float:
    """Penalise extremes of utilisation.

    Ideal range is 50–80 %.  Below 20 % (no demand) or above 90 %
    (near-illiquid) scores poorly.  Score is 0–100.
    """
    u = float(utilization_rate_pct)
    if u < 0.0:
        u = 0.0
    if u > 100.0:
        u = 100.0

    if u <= 20.0:
        # 0 → 50, linearly interpolated
        return round(u / 20.0 * 50.0, 4)
    if u <= 80.0:
        # ideal band: 100 at 65 %, tapering to 80 at both ends
        mid = 65.0
        half_width = 15.0
        dist = abs(u - mid)
        frac = min(dist / half_width, 1.0)
        return round(100.0 - frac * 20.0, 4)
    if u <= 90.0:
        # 80→90 % → score drops from 80 to 40
        frac = (u - 80.0) / 10.0
        return round(80.0 - frac * 40.0, 4)
    # 90–100 % → score drops from 40 to 0
    frac = (u - 90.0) / 10.0
    return round(max(0.0, 40.0 - frac * 40.0), 4)


def _score_bad_debt(bad_debt_ratio_pct: float) -> float:
    """Score falls steeply as bad-debt ratio rises.

    0 % → 100; ≥ 5 % → 0.
    """
    r = float(bad_debt_ratio_pct)
    if r <= 0.0:
        return 100.0
    if r >= 5.0:
        return 0.0
    return round(max(0.0, 100.0 - r / 5.0 * 100.0), 4)


def _score_reserve_coverage(reserve_coverage_ratio: float) -> float:
    """Reward high reserve-coverage.

    coverage_ratio = reserve_balance_usd / bad_debt_usd.
    When bad_debt is 0, ratio is treated as 'infinite' → 100.

    0 → 0; 1 → 60; 2 → 80; ≥ 5 → 100.
    """
    r = float(reserve_coverage_ratio)
    if r < 0.0:
        r = 0.0
    if r == 0.0:
        return 0.0
    if r >= 5.0:
        return 100.0
    if r <= 1.0:
        return round(r * 60.0, 4)
    if r <= 2.0:
        return round(60.0 + (r - 1.0) * 20.0, 4)
    # 2–5 → 80–100
    return round(80.0 + (r - 2.0) / 3.0 * 20.0, 4)


def _score_concentration(top_borrower_concentration_pct: float) -> float:
    """Penalise high single-borrower concentration.

    ≤ 10 % → 100; ≥ 50 % → 0.
    """
    c = float(top_borrower_concentration_pct)
    if c <= 10.0:
        return 100.0
    if c >= 50.0:
        return 0.0
    return round(max(0.0, 100.0 - (c - 10.0) / 40.0 * 100.0), 4)


def _score_oracle(oracle_type: str) -> float:
    """Return oracle quality score."""
    key = str(oracle_type).strip().lower()
    return ORACLE_SCORES.get(key, 20.0)   # unknown oracle scores poorly


def _score_market_pause(paused_markets: int, total_markets: int) -> float:
    """Penalise proportion of paused markets.

    0 paused → 100; all paused → 0.
    """
    p = max(0, int(paused_markets))
    t = max(0, int(total_markets))
    if t == 0:
        return 100.0
    ratio = p / t
    return round(max(0.0, 100.0 - ratio * 100.0), 4)


def _score_incentive(liquidation_incentive_pct: float) -> float:
    """Reward sensible liquidation incentives.

    Ideal: 5–15 %.  Too low → no incentive; too high → borrowers punished
    excessively (chilling demand) & cascades possible.

    0–5 %  → score scales from 0 to 80.
    5–15 % → score is 100.
    15–20 %→ score drops from 100 to 60.
    > 20 % → score drops from 60 to 0.
    """
    inc = float(liquidation_incentive_pct)
    if inc < 0.0:
        inc = 0.0
    if inc <= 5.0:
        return round(inc / 5.0 * 80.0, 4)
    if inc <= 15.0:
        return 100.0
    if inc <= 20.0:
        frac = (inc - 15.0) / 5.0
        return round(100.0 - frac * 40.0, 4)
    # > 20 %
    frac = min((inc - 20.0) / 30.0, 1.0)
    return round(max(0.0, 60.0 - frac * 60.0), 4)


def _health_label(score: float) -> str:
    if score >= LABEL_PRISTINE:
        return "PRISTINE"
    if score >= LABEL_HEALTHY:
        return "HEALTHY"
    if score >= LABEL_WATCH:
        return "WATCH"
    if score >= LABEL_STRESSED:
        return "STRESSED"
    return "CRITICAL"


# ---------------------------------------------------------------------------
# Derived metrics
# ---------------------------------------------------------------------------

def _compute_utilization_rate(
    total_supplied_usd: float, total_borrowed_usd: float
) -> float:
    """Return utilization_rate_pct = borrowed / supplied * 100 (clamped 0–100)."""
    s = float(total_supplied_usd)
    b = float(total_borrowed_usd)
    if s <= 0.0:
        return 0.0
    return round(min(100.0, max(0.0, b / s * 100.0)), 6)


def _compute_bad_debt_ratio(bad_debt_usd: float, total_supplied_usd: float) -> float:
    """Return bad_debt_ratio_pct = bad_debt / supplied * 100 (clamped ≥ 0)."""
    bd = float(bad_debt_usd)
    s = float(total_supplied_usd)
    if s <= 0.0:
        return 0.0
    return round(max(0.0, bd / s * 100.0), 6)


def _compute_reserve_coverage(
    reserve_balance_usd: float, bad_debt_usd: float, reserve_factor_pct: float
) -> float:
    """Return reserve_coverage_ratio = reserve_balance / bad_debt.

    When bad_debt == 0: coverage = min(reserve_balance / (supplied*0.01), 10.0)
    capped at 10 to avoid infinity in output.
    Uses reserve_factor_pct as a tiebreaker when bad_debt is near-zero.
    """
    rb = float(reserve_balance_usd)
    bd = float(bad_debt_usd)
    if bd <= 0.0:
        # Good sign — no bad debt. Score based on reserve balance alone.
        if rb <= 0.0:
            return 0.0
        # Scale coverage by reserve_factor_pct; cap at 10
        rf = float(reserve_factor_pct)
        if rf <= 0.0:
            return min(10.0, rb / 1_000.0)
        return min(10.0, rb / max(1.0, rb) * (rf / 10.0) * 10.0)
    return round(max(0.0, rb / bd), 6)


# ---------------------------------------------------------------------------
# Core analysis function
# ---------------------------------------------------------------------------

def analyze(data: Dict[str, Any]) -> Dict[str, Any]:
    """Analyse a single lending market snapshot.

    Parameters
    ----------
    data : dict
        Required keys:
          protocol_name              str
          total_supplied_usd         float  ≥ 0
          total_borrowed_usd         float  ≥ 0
          bad_debt_usd               float  ≥ 0
          reserve_factor_pct         float  0–100
          reserve_balance_usd        float  ≥ 0
          top_borrower_concentration_pct  float  0–100
          liquidation_incentive_pct  float  ≥ 0
          oracle_type                str   "chainlink"/"twap"/"internal"/...
          paused_markets             int   ≥ 0
          total_markets              int   ≥ 0

    Returns
    -------
    dict
        utilization_rate_pct, bad_debt_ratio_pct, reserve_coverage_ratio,
        market_health_score, health_label, dimension_scores, mp_tag, source
    """
    protocol_name = str(data.get("protocol_name", "unknown"))
    total_supplied = float(data.get("total_supplied_usd", 0.0))
    total_borrowed = float(data.get("total_borrowed_usd", 0.0))
    bad_debt = float(data.get("bad_debt_usd", 0.0))
    reserve_factor = float(data.get("reserve_factor_pct", 0.0))
    reserve_balance = float(data.get("reserve_balance_usd", 0.0))
    top_concentration = float(data.get("top_borrower_concentration_pct", 0.0))
    liq_incentive = float(data.get("liquidation_incentive_pct", 0.0))
    oracle_type = str(data.get("oracle_type", "unknown"))
    paused_markets = int(data.get("paused_markets", 0))
    total_markets = int(data.get("total_markets", 1))

    # Derived metrics
    utilization_rate_pct = _compute_utilization_rate(total_supplied, total_borrowed)
    bad_debt_ratio_pct = _compute_bad_debt_ratio(bad_debt, total_supplied)
    reserve_coverage_ratio = _compute_reserve_coverage(
        reserve_balance, bad_debt, reserve_factor
    )

    # Dimension scores
    dim = {
        "utilization":   _score_utilization(utilization_rate_pct),
        "bad_debt":      _score_bad_debt(bad_debt_ratio_pct),
        "reserve":       _score_reserve_coverage(reserve_coverage_ratio),
        "concentration": _score_concentration(top_concentration),
        "oracle":        _score_oracle(oracle_type),
        "market_pause":  _score_market_pause(paused_markets, total_markets),
        "incentive":     _score_incentive(liq_incentive),
    }

    # Weighted composite
    raw = sum(WEIGHTS[k] * v for k, v in dim.items())
    market_health_score = round(min(100.0, max(0.0, raw)), 2)
    label = _health_label(market_health_score)

    return {
        "protocol_name": protocol_name,
        "utilization_rate_pct": utilization_rate_pct,
        "bad_debt_ratio_pct": bad_debt_ratio_pct,
        "reserve_coverage_ratio": reserve_coverage_ratio,
        "market_health_score": market_health_score,
        "health_label": label,
        "dimension_scores": dim,
        "mp_tag": MP_TAG,
        "source": SOURCE_NAME,
        "schema_version": SCHEMA_VERSION,
    }


# ---------------------------------------------------------------------------
# Ring-buffer log helpers
# ---------------------------------------------------------------------------

def _load_json_list(path: Path) -> list:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_save(payload, str(path))
def _append_log(result: Dict[str, Any], data_dir: Path) -> None:
    log_path = data_dir / LOG_FILENAME
    entries = _load_json_list(log_path)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        **result,
    }
    entries.append(entry)
    if len(entries) > RING_BUFFER_CAP:
        entries = entries[-RING_BUFFER_CAP:]
    _atomic_write(log_path, entries)


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------

class DeFiProtocolLendingMarketHealthScorer:
    """Score the health of a DeFi lending protocol market.

    Usage
    -----
    scorer = DeFiProtocolLendingMarketHealthScorer()
    result = scorer.score(data_dict)
    # result keys: utilization_rate_pct, bad_debt_ratio_pct,
    #              reserve_coverage_ratio, market_health_score, health_label
    """

    def score(
        self,
        data: Dict[str, Any],
        *,
        write_log: bool = False,
        data_dir: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """Analyse ``data`` and return a health-score result dict.

        Parameters
        ----------
        data        : input snapshot dict (see module docstring for keys)
        write_log   : if True, atomically append result to ring-buffer log
        data_dir    : override default data directory (default: <repo>/data/)
        """
        result = analyze(data)

        if write_log:
            _dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
            try:
                _append_log(result, _dir)
            except Exception as exc:
                log.warning("log write failed: %s", exc)

        return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _demo_data() -> Dict[str, Any]:
    return {
        "protocol_name":                  "Aave V3 Demo",
        "total_supplied_usd":             1_000_000_000.0,
        "total_borrowed_usd":               650_000_000.0,
        "bad_debt_usd":                       1_000_000.0,
        "reserve_factor_pct":                        10.0,
        "reserve_balance_usd":                5_000_000.0,
        "top_borrower_concentration_pct":           12.0,
        "liquidation_incentive_pct":                 8.0,
        "oracle_type":                       "chainlink",
        "paused_markets":                              0,
        "total_markets":                              20,
    }


def _main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description=f"DeFi Protocol Lending Market Health Scorer ({MP_TAG})"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="Compute and print (no write)")
    group.add_argument("--run",   action="store_true", help="Compute, print, write log")
    parser.add_argument("--data-dir", type=str, default=None)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    data_dir = Path(args.data_dir) if args.data_dir else _DEFAULT_DATA_DIR
    demo = _demo_data()
    scorer = DeFiProtocolLendingMarketHealthScorer()
    result = scorer.score(demo, write_log=args.run, data_dir=data_dir)

    print(json.dumps(result, indent=2))
    if args.run:
        print(f"\n[{MP_TAG}] Logged to {data_dir / LOG_FILENAME}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
