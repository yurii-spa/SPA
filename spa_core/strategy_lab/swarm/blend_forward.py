"""Swarm block 2 — the FORWARD 3-desk blend paper portfolio (validated idea #3 made live).

Charter: docs/SWARM_ARCHITECTURE.md · numbers: docs/DYNAMIC_LEVERAGE_GUARDIAN.md idea #3 — the
cross-desk blend (sUSDe-carry / rates-fixed-carry / RWA-floor, measured cross-correlations ≈ 0)
kept the return of a lone sUSDe book while cutting its max drawdown 8.5% → 2.1% (−75%, Calmar ×4)
on the 699-day backtest, ~4× in EACH named crisis. This module runs that blend FORWARD, daily, on
the three LIVE paper legs the fleet already produces:

  • sUSDe leg  — aggressive_lab `susde_dn` forward paper series (funding-carry, depeg/funding tail)
  • rates leg  — rates_desk fixed-carry live paper series (com.spa.rates_desk_paper)
  • RWA leg    — strategy_lab `rwa_sleeve` live paper series (REALIZED T-bill floor, not benchmark)

Method (deterministic, causal): legs are aligned BY DATE (never by row index — the known axis trap);
the blend is daily-rebalanced to the FIXED default weights 25/50/25 (idea #3's validated default —
idea #4's vol-targeting did NOT hold OOS and is deliberately NOT used). An inverse-vol (risk-parity)
variant is reported as a research column only once enough common history exists (idea #2's one
positive: inverse-vol > equal-weight), never as the default.

Fail-CLOSED: any leg missing/unreadable → blend state DEGRADED with the reason; < 2 common dates →
WARMUP with no invented numbers; a stale leg simply stops the common window from advancing (honest
stall, flagged). Full recompute each tick — idempotent, restart-proof, no persisted state.

ADVISORY / paper-only / OUTSIDE_RISKPOLICY: moves no capital, never touches the go-live track,
writes ONLY data/swarm/. Deterministic, stdlib-only. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from spa_core.strategy_lab.swarm.common import append_daily_proof, apy_pct, max_drawdown_pct
from spa_core.strategy_lab.aggressive_lab.guardian import stdev
from spa_core.utils.atomic import atomic_save

__all__ = ["run_forward_blend", "DEFAULT_WEIGHTS", "load_legs"]

REPO_ROOT = Path(__file__).resolve().parents[3]
SWARM_DIR = REPO_ROOT / "data" / "swarm"
STATUS_NAME = "blend_forward.json"
PROOF_NAME = "blend_forward_proof.jsonl"
NOTIONAL_USD = 100_000.0

# Idea #3's validated default (25% sUSDe / 50% rates-carry / 25% RWA-floor).
DEFAULT_WEIGHTS: Dict[str, float] = {"susde": 0.25, "rates": 0.50, "rwa": 0.25}
RISK_PARITY_LOOKBACK = 20  # causal trailing window for the research-only inverse-vol variant
STALE_AFTER_DAYS = 3  # a leg whose last date is older than this (vs the freshest leg) is flagged

LEG_SOURCES = {
    "susde": {
        "path": REPO_ROOT / "data" / "aggressive_lab" / "susde_dn" / "realized_series.jsonl",
        "desc": "aggressive_lab susde_dn forward paper (funding carry, depeg/funding tail)",
    },
    "rates": {
        "path": REPO_ROOT / "data" / "rates_desk" / "paper" / "rates_desk_fixed_carry_series.json",
        "desc": "rates_desk fixed-carry live paper (PT carry, rate/maturity tail)",
    },
    "rwa": {
        "path": REPO_ROOT / "data" / "strategy_lab_paper" / "rwa_sleeve_series.json",
        "desc": "strategy_lab rwa_sleeve live paper (REALIZED tokenized T-bill floor)",
    },
}


# ── leg loaders (each → {date: equity_usd}, fail-closed to {}) ─────────────────────────────────
def _load_susde(path: Path) -> Dict[str, float]:
    """aggressive_lab hash-chained jsonl; FORWARD phase only (backtest bars are history, not track)."""
    out: Dict[str, float] = {}
    try:
        with path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    doc = json.loads(line)
                except ValueError:
                    continue
                if (isinstance(doc, dict) and doc.get("phase") == "forward"
                        and isinstance(doc.get("equity_usd"), (int, float)) and doc.get("date")):
                    out[str(doc["date"])] = float(doc["equity_usd"])
    except OSError:
        return {}
    return out


def _load_series_json(path: Path) -> Dict[str, float]:
    """{'series': [{date, equity_usd}, …]} document (rates_desk / strategy_lab paper format)."""
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    out: Dict[str, float] = {}
    for row in (doc.get("series") or []) if isinstance(doc, dict) else []:
        if isinstance(row, dict) and isinstance(row.get("equity_usd"), (int, float)) and row.get("date"):
            out[str(row["date"])] = float(row["equity_usd"])
    return out


def load_legs(sources: Optional[dict] = None) -> Dict[str, Dict[str, float]]:
    srcs = sources or LEG_SOURCES
    return {
        "susde": _load_susde(Path(srcs["susde"]["path"])),
        "rates": _load_series_json(Path(srcs["rates"]["path"])),
        "rwa": _load_series_json(Path(srcs["rwa"]["path"])),
    }


# ── blend math (daily-rebalanced, causal) ──────────────────────────────────────────────────────
def _blend_path(dates: List[str], legs: Dict[str, Dict[str, float]],
                weights: Dict[str, float]) -> List[float]:
    """Daily-rebalanced blend equity over the common dates: r_blend = Σ w_i · r_i each day."""
    eq = [NOTIONAL_USD]
    for i in range(1, len(dates)):
        r = 0.0
        for leg, w in weights.items():
            prev, cur = legs[leg][dates[i - 1]], legs[leg][dates[i]]
            if prev > 0:
                r += w * (cur / prev - 1.0)
        eq.append(eq[-1] * (1.0 + r))
    return eq


def _risk_parity_weights(dates: List[str], legs: Dict[str, Dict[str, float]]) -> Optional[Dict[str, float]]:
    """Inverse-vol weights from the TRAILING window only (causal). None until enough history."""
    if len(dates) < RISK_PARITY_LOOKBACK + 1:
        return None
    window = dates[-(RISK_PARITY_LOOKBACK + 1):]
    inv: Dict[str, float] = {}
    for leg in legs:
        rets = [legs[leg][window[i]] / legs[leg][window[i - 1]] - 1.0
                for i in range(1, len(window)) if legs[leg][window[i - 1]] > 0]
        vol = stdev(rets)
        inv[leg] = 1.0 / max(vol, 1e-9)
    total = sum(inv.values())
    return {leg: round(v / total, 4) for leg, v in inv.items()}


def _leg_view(leg: Dict[str, float], dates: List[str]) -> dict:
    eq = [leg[d] for d in dates]
    return {
        "days": len(dates),
        "window": {"start": dates[0], "end": dates[-1]},
        "equity_usd": round(eq[-1], 2),
        "apy_pct": apy_pct(eq, len(dates)),
        "max_dd_pct": max_drawdown_pct(eq),
    }


def run_forward_blend(sources: Optional[dict] = None, out_dir: Path = SWARM_DIR) -> dict:
    """One blend pass. Writes the status JSON + daily proof line; returns the status doc."""
    srcs = sources or LEG_SOURCES
    legs = load_legs(srcs)
    now = datetime.now(timezone.utc)

    missing = sorted(name for name, series in legs.items() if not series)
    common = sorted(set.intersection(*(set(s) for s in legs.values()))) if not missing else []

    doc: dict = {
        "domain": "swarm.blend_forward",
        "label": "SWARM L3 cross-desk blend (idea #3 forward) / ADVISORY / paper / OUTSIDE_RISKPOLICY",
        "is_advisory": True,
        "outside_riskpolicy": True,
        "as_of_utc": now.isoformat(timespec="seconds"),
        "weights_default": DEFAULT_WEIGHTS,
        "legs_desc": {k: v["desc"] for k, v in srcs.items()},
        "honest_limits": (
            "paper blend of three live paper legs, not realized capital; validated on backtest "
            "(DD −75%, Calmar ×4) — the FORWARD window below is what counts and it starts small; "
            "in a SYSTEMIC crisis the two crypto legs correlate toward 1 (true decorrelator is the "
            "off-chain RWA leg); a stale leg stalls the common window (flagged, never papered over)."
        ),
    }

    if missing:
        doc.update({"state": "DEGRADED", "reason": f"missing/unreadable legs: {missing}",
                    "common_days": 0})
    elif len(common) < 2:
        doc.update({"state": "WARMUP", "common_days": len(common),
                    "reason": "fewer than 2 common dates across the three legs — blend arms as the "
                              "youngest leg (susde forward) accrues days"})
    else:
        blend_eq = _blend_path(common, legs, DEFAULT_WEIGHTS)
        rp_weights = _risk_parity_weights(common, legs)
        # Staleness: any leg whose own last date lags the freshest leg by > STALE_AFTER_DAYS.
        last_dates = {leg: max(series) for leg, series in legs.items()}
        freshest = max(last_dates.values())
        stale = sorted(leg for leg, d in last_dates.items()
                       if (datetime.fromisoformat(freshest) - datetime.fromisoformat(d)).days
                       > STALE_AFTER_DAYS)
        doc.update({
            "state": "STALE_LEG" if stale else "TRACKING",
            "stale_legs": stale,
            "common_days": len(common),
            "window": {"start": common[0], "end": common[-1]},
            "blend": {
                "equity_usd": round(blend_eq[-1], 2),
                "apy_pct": apy_pct(blend_eq, len(common)),
                "max_dd_pct": max_drawdown_pct(blend_eq),
            },
            "legs": {leg: _leg_view(series, common) for leg, series in legs.items()},
            "risk_parity_research": (
                {"weights": rp_weights,
                 "note": "inverse-vol trailing weights — RESEARCH ONLY (idea #4 did not hold OOS); "
                         "default stays the fixed 25/50/25"}
                if rp_weights else
                {"weights": None,
                 "note": f"needs ≥{RISK_PARITY_LOOKBACK + 1} common days (have {len(common)})"}
            ),
        })

    atomic_save(doc, str(out_dir / STATUS_NAME))
    payload = {"state": doc["state"], "common_days": doc.get("common_days", 0),
               "blend_equity_usd": (doc.get("blend") or {}).get("equity_usd"),
               "blend_max_dd_pct": (doc.get("blend") or {}).get("max_dd_pct")}
    doc["proof_appended"] = append_daily_proof(payload, out_dir / PROOF_NAME,
                                               day=doc["as_of_utc"][:10])
    return doc


def main() -> int:
    doc = run_forward_blend()
    line = f"swarm.blend_forward: state={doc['state']} common_days={doc.get('common_days', 0)}"
    if doc.get("blend"):
        b = doc["blend"]
        line += f" equity=${b['equity_usd']:,.2f} apy={b['apy_pct']}% maxDD={b['max_dd_pct']}%"
    print(line + f" proof_appended={doc['proof_appended']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
