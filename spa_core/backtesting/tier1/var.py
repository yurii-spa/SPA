"""
spa_core/backtesting/tier1/var.py — Value-at-Risk / Conditional VaR (Tier-1).

PARALLEL MODEL. Pure stdlib (math + statistics.NormalDist), deterministic, no network,
LLM-forbidden. Does NOT modify RiskPolicy, the cycle, or any canonical module — it is a
read-only risk overlay on top of the existing tournament + tier1_verdict outputs.

Why TWO VaR numbers:

  (1) YIELD VaR — classic price/return VaR on the strategy's daily-yield series.
      For a stablecoin yield book the daily return is blended_apy/365: tiny, near-
      deterministic and POSITIVE. So historical/parametric VaR on this series is
      essentially zero. We still compute it (parametric Normal VaR via NormalDist AND
      historical-simulation VaR, at 95% and 99%, annualized) because it is the textbook
      number — but it is NOT the institutional risk number for this asset class.

  (2) PRINCIPAL VaR — the number that actually matters. Stablecoin principal risk is a
      DISCRETE tail: depeg / smart-contract exploit / bad debt that wipes part of the
      capital in a held protocol. We model it with a deterministic, probability-weighted
      shock distribution derived from the allocation's tier mix (reusing tail_risk's tier
      map + expected-loss calibration), and read the loss quantile at 95% / 99%. The
      tail_risk expected-loss is folded in as the distribution's mean drag. This is the
      real institutional VaR for a stable-yield book.

`combined_annual_risk_pct` reports the principal VaR (the binding risk), with the tiny
yield VaR exposed separately so the two are never conflated.

Estimates are conservative and version-pinned (change → new ADR). They are NOT live
probabilities — they are a transparent risk overlay complementing the deterministic
RiskPolicy (which still governs live exposure).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import math
import os
import tempfile
from pathlib import Path
from statistics import NormalDist
from typing import Dict, List, Optional, Sequence

from spa_core.backtesting.tier1 import oos as oos_mod
from spa_core.backtesting.tier1.tail_risk import (
    PROTOCOL_TIER,
    strategy_tail_risk,
)

VAR_VERSION = "v1.0"
DAYS_PER_YEAR = 365
_N = NormalDist()

_ROOT = Path(__file__).resolve().parents[3]
_DATA = _ROOT / "data"
_VERDICT = _DATA / "tier1_verdict.json"
_RESULTS = _DATA / "mass_tournament_results.json"
_OUT = _DATA / "tier1_var.json"


# ---------------------------------------------------------------------------
# Principal-shock scenario calibration (deterministic, version-pinned).
# Per tier: an annual probability of a principal-loss event and the loss severity
# (fraction of the position's principal lost in that event). These are conservative,
# transparent priors — NOT live probabilities. tail_risk's TIER_EXPECTED_LOSS already
# encodes the *mean* drag (prob*severity, roughly); here we expose the distribution so we
# can read a TAIL quantile rather than only the mean.
# ---------------------------------------------------------------------------
TIER_SHOCK: Dict[str, dict] = {
    # tier: {annual probability of a loss event, severity = % of principal lost}
    "T1": {"prob": 0.010, "severity_pct": 30.0},   # blue-chip: rare but a depeg/bad-debt
    "T2": {"prob": 0.030, "severity_pct": 50.0},   # newer/yield-bearing: larger surface
    "T3": {"prob": 0.080, "severity_pct": 65.0},   # exotic/LP/leverage: frequent + severe
    "cash": {"prob": 0.0, "severity_pct": 0.0},
    "_default": {"prob": 0.040, "severity_pct": 55.0},
}


def _tier_of(protocol: str) -> str:
    if protocol == "cash":
        return "cash"
    return PROTOCOL_TIER.get(protocol, "T2")


# ---------------------------------------------------------------------------
# (1) Classic VaR / CVaR on a return series
# ---------------------------------------------------------------------------
def var_cvar(daily_returns: Sequence[float], conf: float = 0.95) -> dict:
    """VaR and CVaR (Expected Shortfall) of a daily-return series at `conf`.

    Reports a LOSS as a positive percent. Combines:
      • parametric Normal VaR (mean/std via NormalDist), and
      • historical-simulation VaR (empirical loss quantile).
    The returned var_pct/cvar_pct use the historical method when there are enough
    observations, else the parametric one; both are always exposed. Returns are
    fractional (e.g. 0.00013 = 0.013%/day); output percents are annualized loss.

    By construction CVaR >= VaR (the average of the worst tail is at least as bad as the
    cutoff), and a higher confidence gives a larger (worse) VaR.
    """
    rets = [float(r) for r in daily_returns if r is not None]
    n = len(rets)
    if n == 0:
        return {"var_pct": 0.0, "cvar_pct": 0.0, "method": "empty",
                "var_parametric_pct": 0.0, "var_historical_pct": 0.0,
                "cvar_parametric_pct": 0.0, "cvar_historical_pct": 0.0,
                "n_obs": 0, "conf": conf}

    alpha = 1.0 - conf  # left-tail mass
    mean = sum(rets) / n
    if n >= 2:
        var_s = sum((r - mean) ** 2 for r in rets) / (n - 1)
    else:
        var_s = 0.0
    std = math.sqrt(var_s)

    # --- Parametric Normal VaR/CVaR (daily) ---
    z = _N.inv_cdf(conf)  # positive quantile
    var_loss_param = max(0.0, z * std - mean)  # loss = -(mean - z*std)
    # Normal CVaR (Expected Shortfall): E[loss | loss > VaR] = -mean + std*phi(z)/alpha
    phi = math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)
    cvar_loss_param = max(0.0, std * (phi / alpha) - mean)

    # --- Historical-simulation VaR/CVaR (daily) ---
    losses = sorted((-r for r in rets))  # losses ascending; tail = right end
    # index of the VaR quantile in the loss distribution
    idx = int(math.ceil(conf * n)) - 1
    idx = min(max(idx, 0), n - 1)
    var_loss_hist = max(0.0, losses[idx])
    tail = [l for l in losses[idx:] if l is not None]
    cvar_loss_hist = max(0.0, sum(tail) / len(tail)) if tail else var_loss_hist

    # Annualize a daily loss: scale by sqrt(time) for the volatility-driven loss.
    ann = math.sqrt(DAYS_PER_YEAR)
    var_param_a = var_loss_param * ann * 100.0
    cvar_param_a = cvar_loss_param * ann * 100.0
    var_hist_a = var_loss_hist * ann * 100.0
    cvar_hist_a = cvar_loss_hist * ann * 100.0

    use_hist = n >= 20
    return {
        "var_pct": round(var_hist_a if use_hist else var_param_a, 6),
        "cvar_pct": round(cvar_hist_a if use_hist else cvar_param_a, 6),
        "method": "historical" if use_hist else "parametric_normal",
        "var_parametric_pct": round(var_param_a, 6),
        "cvar_parametric_pct": round(cvar_param_a, 6),
        "var_historical_pct": round(var_hist_a, 6),
        "cvar_historical_pct": round(cvar_hist_a, 6),
        "n_obs": n,
        "conf": conf,
    }


# ---------------------------------------------------------------------------
# Build a strategy's daily-yield series from its allocation, on REAL data.
# ---------------------------------------------------------------------------
def _daily_yield_series(allocation: Dict[str, float],
                        series_map: Dict[str, Dict[str, float]]) -> List[float]:
    """Allocation-weighted blended daily yield (apy/365) along the common forward-filled
    date axis, using the real per-protocol DeFiLlama APY series (decimal apy)."""
    weights = {k: float(v) for k, v in (allocation or {}).items()
               if k != "cash" and v and k in series_map}
    if not weights:
        return []
    axis = oos_mod._common_axis(series_map, list(weights.keys()))
    if not axis:
        return []
    ffilled = {p: oos_mod._ffill_apy(series_map[p], axis) for p in weights}
    out: List[float] = []
    for i in range(len(axis)):
        num, wsum = 0.0, 0.0
        for p, w in weights.items():
            a = ffilled[p][i]
            if a is not None:
                num += w * a
                wsum += w
        if wsum > 0:
            blended_apy = num / wsum          # decimal APY
            out.append(blended_apy / DAYS_PER_YEAR)  # daily fractional yield
    return out


# ---------------------------------------------------------------------------
# (2) Principal-loss VaR overlay (the institutional number)
# ---------------------------------------------------------------------------
def principal_var(allocation: Dict[str, float], conf: float = 0.95) -> dict:
    """Probability-weighted principal-loss VaR for an allocation.

    Model: each non-cash dollar sits in a protocol of some tier. The portfolio-level
    annual loss is the sum over positions of (independent Bernoulli shock × severity ×
    weight). We build the deterministic loss distribution analytically as a small
    discrete mixture (no Monte-Carlo, fully reproducible): treat the tiers as the loss
    drivers and read the quantile of the worst-tier shock plus the expected drag from
    lighter tiers. We then floor it at the tail_risk expected-loss (the mean drag), so the
    VaR can never under-report the known expected loss.
    """
    weights = {k: float(v) for k, v in (allocation or {}).items() if v}
    wsum = sum(weights.values())
    if wsum <= 0:
        return {"principal_var_pct": 0.0, "expected_loss_pct": 0.0, "conf": conf,
                "tier_weights": {}, "method": "principal_shock"}

    # normalized weight per tier
    tier_w: Dict[str, float] = {}
    for p, w in weights.items():
        t = _tier_of(p)
        tier_w[t] = tier_w.get(t, 0.0) + w / wsum

    alpha = 1.0 - conf  # tail mass we must cover

    # Mean drag (expected loss) = sum_t w_t * prob_t * severity_t.
    expected_loss = 0.0
    for t, w in tier_w.items():
        sh = TIER_SHOCK.get(t, TIER_SHOCK["_default"])
        expected_loss += w * (sh["prob"] / 1.0) * sh["severity_pct"]

    # Tail loss: account each tier's shock as a portfolio-fraction loss = w_t*severity_t,
    # occurring with probability prob_t. Sort these candidate shock losses by severity and
    # accumulate their probabilities from worst to least until we reach the (1-conf) tail
    # mass; the VaR is the loss level at which cumulative shock probability first reaches
    # the tail mass. This reads a genuine quantile of the discrete shock distribution.
    shocks: List[tuple] = []  # (loss_fraction_pct, prob)
    for t, w in tier_w.items():
        sh = TIER_SHOCK.get(t, TIER_SHOCK["_default"])
        if sh["prob"] > 0 and w > 0:
            shocks.append((w * sh["severity_pct"], sh["prob"]))
    shocks.sort(reverse=True)  # worst loss first

    var_loss = 0.0
    cum_p = 0.0
    for loss, prob in shocks:
        cum_p += prob
        if cum_p >= alpha:
            var_loss = loss  # this shock's loss is the quantile at the tail boundary
            break
    else:
        # cumulative shock probability never reaches the tail mass: tail is dominated by
        # the no-event ("only expected drag") outcome → VaR is the expected loss.
        var_loss = expected_loss

    # The VaR is the worse (larger) of the shock quantile and the expected drag.
    principal_var_pct = max(var_loss, expected_loss)
    return {
        "principal_var_pct": round(principal_var_pct, 4),
        "expected_loss_pct": round(expected_loss, 4),
        "conf": conf,
        "tier_weights": {t: round(w, 4) for t, w in tier_w.items()},
        "method": "principal_shock",
        "version": VAR_VERSION,
    }


# ---------------------------------------------------------------------------
# Top-level per-strategy risk
# ---------------------------------------------------------------------------
def strategy_risk(allocation: Dict[str, float],
                  series_map: Optional[Dict[str, Dict[str, float]]] = None) -> dict:
    """Full Tier-1 risk profile for an allocation: tiny yield VaR (return series) +
    the real principal VaR (shock distribution). `combined_annual_risk_pct` is the
    principal VaR (the binding institutional number)."""
    if series_map is None:
        series_map = oos_mod.load_protocol_series()

    series = _daily_yield_series(allocation, series_map)
    y95 = var_cvar(series, conf=0.95)
    y99 = var_cvar(series, conf=0.99)

    p95 = principal_var(allocation, conf=0.95)
    p99 = principal_var(allocation, conf=0.99)
    tr = strategy_tail_risk(allocation)

    return {
        "version": VAR_VERSION,
        "yield_var_method": y95["method"],
        "yield_n_obs": y95["n_obs"],
        # yield VaR (tiny by asset class) — annualized loss %
        "yield_var_95": y95["var_pct"],
        "yield_cvar_95": y95["cvar_pct"],
        "yield_var_99": y99["var_pct"],
        "yield_cvar_99": y99["cvar_pct"],
        # principal VaR (the real number) — annual % of capital at risk
        "principal_var_95": p95["principal_var_pct"],
        "principal_var_99": p99["principal_var_pct"],
        "principal_expected_loss_pct": p95["expected_loss_pct"],
        "tail_risk_pct": tr["tail_risk_pct"],
        "tier_mix": tr.get("tier_mix", {}),
        # the binding institutional risk number = principal VaR @99%
        "combined_annual_risk_pct": p99["principal_var_pct"],
        "note": ("yield VaR is near-zero by asset class (stablecoin yield is "
                 "near-deterministic & positive); principal VaR is the institutional "
                 "risk number (depeg/exploit/bad-debt tail)."),
    }


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------
def _load_allocations() -> Dict[str, dict]:
    """{strategy_id: allocation} from the tournament leaderboard."""
    try:
        res = json.loads(_RESULTS.read_text())
    except Exception:
        return {}
    out: Dict[str, dict] = {}
    for e in res.get("leaderboard", []) or []:
        sid = e.get("id")
        alloc = e.get("allocation")
        if sid and isinstance(alloc, dict):
            out[sid] = alloc
    return out


def build_report(write: bool = True) -> dict:
    """Compute per-validated-strategy VaR from tier1_verdict + tournament allocations.
    Writes data/tier1_var.json atomically (tmp + os.replace)."""
    try:
        verdict = json.loads(_VERDICT.read_text())
    except Exception:
        verdict = {}
    allocs = _load_allocations()
    series_map = oos_mod.load_protocol_series()

    lb = verdict.get("leaderboard_tier1", []) or []
    validated = [x for x in lb if x.get("validated")]

    strategies = []
    for x in validated:
        sid = x.get("id")
        alloc = allocs.get(sid, {})
        risk = strategy_risk(alloc, series_map)
        strategies.append({
            "id": sid,
            "package": x.get("package"),
            "net_apy_pct": x.get("net_apy_pct"),
            "allocation": alloc,
            "risk": risk,
        })

    report = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": "tier1_var",
        "version": VAR_VERSION,
        "llm_forbidden": True,
        "regime": verdict.get("regime"),
        "data_source": verdict.get("data_source"),
        "validated_count": len(validated),
        "scenario_calibration": TIER_SHOCK,
        "note": ("Two VaR families: yield VaR (return-series, near-zero for stablecoin "
                 "yield) and principal VaR (probability-weighted depeg/exploit shock "
                 "distribution). principal VaR is the binding institutional number."),
        "strategies": strategies,
    }
    if write:
        _DATA.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=_DATA, prefix=".tier1_var_")
        with os.fdopen(fd, "w") as f:
            json.dump(report, f, indent=2)
        os.replace(tmp, _OUT)
    return report


if __name__ == "__main__":
    rep = build_report(write=True)
    print(json.dumps({
        "validated_count": rep["validated_count"],
        "data_source": rep.get("data_source"),
        "strategies": [
            {
                "id": s["id"],
                "package": s["package"],
                "yield_var_95": s["risk"]["yield_var_95"],
                "yield_cvar_95": s["risk"]["yield_cvar_95"],
                "principal_var_95": s["risk"]["principal_var_95"],
                "principal_var_99": s["risk"]["principal_var_99"],
                "combined_annual_risk_pct": s["risk"]["combined_annual_risk_pct"],
                "tier_mix": s["risk"]["tier_mix"],
            }
            for s in rep["strategies"]
        ],
    }, indent=2))
    # Illustrative T2-heavy allocation (shows a meaningful principal VaR even when the
    # validated set is T1-only).
    demo = {"morpho_steakhouse": 0.5, "euler_v2": 0.3, "maple": 0.2}
    print("\nT2-heavy demo principal VaR:", json.dumps({
        k: v for k, v in strategy_risk(demo).items()
        if k in ("yield_var_95", "principal_var_95", "principal_var_99",
                 "combined_annual_risk_pct", "tier_mix")
    }, indent=2))
