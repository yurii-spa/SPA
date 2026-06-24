"""
spa_core/backtesting/tier1/evaluator.py — Tier-1 verdict over the tournament.

PARALLEL MODEL — reads the EXISTING mass_tournament_results.json (does not change the
tournament, RiskPolicy, or any canonical module) and produces an INSTITUTIONAL verdict:

  1. Deflated Sharpe Ratio per strategy — corrects the leaderboard for the fact that we
     ranked ~64 strategies and would pick the best (selection bias / data-snooping).
  2. Probabilistic Sharpe + minimum-track-record-length — is the Sharpe trustworthy yet?
  3. Net-of-cost APY — gas + slippage + bridge drag subtracted from gross.
  4. Risk-tiered PACKAGES — assigns each validated strategy to conservative / balanced /
     aggressive (the product tiers shown on the landing), so the future "pick your risk
     package" model is backed by real validation, not raw backtest rank.

Output: data/tier1_verdict.json (atomic). Deterministic, stdlib only, LLM-forbidden.
Honest by design: with a short track record DSR will (correctly) fail for most/all
strategies — the verdict says so rather than pretending the ranking is trustworthy.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Optional

from spa_core.backtesting.tier1 import deflated_sharpe as ds
from spa_core.backtesting.tier1.cost_model import net_of_cost_apy

_ROOT = Path(__file__).resolve().parents[3]
_DATA = _ROOT / "data"
_RESULTS = _DATA / "mass_tournament_results.json"
_OUT = _DATA / "tier1_verdict.json"

# Risk-tiered product packages (mirror the landing's tiers). A strategy is offered in a
# package when its NET APY and worst-case drawdown fall in the band. DSR gates trust.
PACKAGES = [
    {"key": "conservative", "label": "Conservative", "net_apy_min": 2.0, "net_apy_max": 6.0,  "max_dd_limit": 3.0},
    {"key": "balanced",     "label": "Balanced",     "net_apy_min": 6.0, "net_apy_max": 12.0, "max_dd_limit": 10.0},
    {"key": "aggressive",   "label": "Aggressive",   "net_apy_min": 12.0, "net_apy_max": 999.0, "max_dd_limit": 25.0},
]
DSR_PASS = 0.95
PSR_PASS = 0.90
DEFAULT_CAPITAL = 100_000.0


def _parse_n_obs(result: dict) -> int:
    """Number of return observations (days) from simulation_period; default 90.
    Handles 'YYYY-MM-DD to YYYY-MM-DD' (day delta), an int, or {days:N}."""
    sp = result.get("simulation_period")
    if isinstance(sp, (int, float)):
        return max(int(sp), 2)
    if isinstance(sp, str):
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", sp)
        if len(dates) >= 2:
            try:
                d0 = datetime.date.fromisoformat(dates[0])
                d1 = datetime.date.fromisoformat(dates[1])
                return max((d1 - d0).days, 2)
            except ValueError:
                pass
        m = re.search(r"(\d+)\s*day", sp)
        if m:
            return max(int(m.group(1)), 2)
    if isinstance(sp, dict):
        for k in ("days", "n", "length"):
            if isinstance(sp.get(k), (int, float)):
                return max(int(sp[k]), 2)
    return 90


# A real DeFi-yield Sharpe is ~0.5–4; vol below this floor means near-constant (mock)
# returns where Sharpe/DSR are mathematically degenerate and NOT trustworthy.
SANE_SHARPE_MAX = 6.0
MIN_VOL_PCT = 0.5


def _assess_data_quality(board: list) -> dict:
    """Detect degenerate backtest data (mock / near-constant) that makes Sharpe meaningless."""
    if not board:
        return {"status": "EMPTY", "trustworthy": False, "reason": "no leaderboard"}
    sharpes = sorted(abs(float(e.get("sharpe") or 0.0)) for e in board)
    vols = sorted(float(e.get("volatility_pct") or 0.0) for e in board)
    med_sharpe = sharpes[len(sharpes) // 2]
    med_vol = vols[len(vols) // 2]
    degenerate = med_sharpe > SANE_SHARPE_MAX or med_vol < MIN_VOL_PCT
    return {
        "status": "DEGENERATE" if degenerate else "OK",
        "trustworthy": not degenerate,
        "median_sharpe": round(med_sharpe, 2),
        "median_vol_pct": round(med_vol, 3),
        "reason": (
            f"median Sharpe {med_sharpe:.1f} (>{SANE_SHARPE_MAX}) / vol {med_vol:.3f}% "
            f"(<{MIN_VOL_PCT}%) → near-constant (MOCK) data; metrics NOT trustworthy. "
            "P0 fix: backtest on real point-in-time historical APY series."
        ) if degenerate else "volatility/Sharpe in a plausible range",
    }


def _assign_package(net_apy: float, max_dd_pct: float) -> Optional[str]:
    dd = abs(max_dd_pct or 0.0)
    for p in PACKAGES:
        if p["net_apy_min"] <= net_apy < p["net_apy_max"] and dd <= p["max_dd_limit"]:
            return p["key"]
    return None


def _grade(dsr: float, psr: float, net_apy: float) -> str:
    if dsr >= DSR_PASS and net_apy > 0:
        return "A"          # edge survives multiple-testing
    if psr >= PSR_PASS and net_apy > 0:
        return "B"          # individually significant, not yet multiple-testing-proof
    if net_apy > 0:
        return "C"          # positive net but statistically unproven
    return "D"              # negative net-of-cost or no edge


def evaluate(write: bool = True) -> dict:
    result = json.loads(_RESULTS.read_text())
    board = result.get("leaderboard", []) or []
    capital = float(result.get("initial_capital_usd") or DEFAULT_CAPITAL)
    n_obs = _parse_n_obs(result)
    n_trials = int(result.get("strategies_tested") or len(board) or 1)
    dq = _assess_data_quality(board)
    trustworthy = dq["trustworthy"]

    # Per-period Sharpe variance across all trials (consistent units for DSR).
    sharpes_pp = [ds.deannualize_sharpe(float(e.get("sharpe") or 0.0)) for e in board]
    sr_var_pp = ds.sharpe_variance_across_trials(sharpes_pp)

    evaluated = []
    pkg_counts = {p["key"]: 0 for p in PACKAGES}
    for e in board:
        sr_annual = float(e.get("sharpe") or 0.0)
        sr_pp = ds.deannualize_sharpe(sr_annual)
        gross_apy = float(e.get("annual_return_pct") or 0.0)
        alloc = e.get("allocation") or {}
        n_pos = len([k for k, v in alloc.items() if k != "cash" and v]) if isinstance(alloc, dict) else 1

        dsr = ds.deflated_sharpe_ratio(sr_pp, n_obs, sr_var_pp, n_trials)
        psr = ds.probabilistic_sharpe_ratio(sr_pp, n_obs)
        mtrl = ds.min_track_record_length(sr_pp)
        cost = net_of_cost_apy(gross_apy, capital, n_positions=max(n_pos, 1),
                               rebalances_per_year=12, annual_turnover=1.0)
        net_apy = cost["net_apy_pct"]
        pkg = _assign_package(net_apy, e.get("max_dd_pct"))
        if pkg:
            pkg_counts[pkg] += 1
        # Degenerate (mock) data → metrics not trustworthy: force UNPROVEN, no DSR pass.
        dsr_passes = bool(dsr["passes"]) and trustworthy
        grade = _grade(dsr["dsr"], psr, net_apy) if trustworthy else "UNPROVEN"
        evaluated.append({
            "id": e.get("id"),
            "rank_gross": e.get("rank"),
            "sharpe_annual": round(sr_annual, 3),
            "gross_apy_pct": round(gross_apy, 3),
            "net_apy_pct": net_apy,
            "cost_drag_pct": cost["total_cost_pct"],
            "max_dd_pct": e.get("max_dd_pct"),
            "psr": round(psr, 4),
            "dsr": round(dsr["dsr"], 4),
            "dsr_passes": dsr_passes,
            "min_track_record_days": round(mtrl, 1) if mtrl != float("inf") else None,
            "tier1_grade": grade,
            "package": pkg,
        })

    # Re-rank by net APY among DSR-passers first, else by net APY.
    evaluated.sort(key=lambda x: (x["dsr_passes"], x["net_apy_pct"]), reverse=True)
    passers = [x for x in evaluated if x["dsr_passes"]]

    verdict = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": "tier1_parallel",
        "llm_forbidden": True,
        "n_trials": n_trials,
        "n_obs_days": n_obs,
        "sr_benchmark_annual_under_null": round(
            ds.annualize_sharpe(ds.expected_max_sharpe(sr_var_pp, n_trials)), 3),
        "dsr_pass_threshold": DSR_PASS,
        "data_quality": dq,
        "strategies_evaluated": len(evaluated),
        "dsr_passers": len(passers),
        "honest_note": (
            "DATA QUALITY FAIL — " + dq["reason"]
        ) if not trustworthy else (
            "0 DSR-passers is EXPECTED on a short track record — the expected-max Sharpe "
            "under the null from many trials is high, so no strategy is yet proven."
        ) if not passers else f"{len(passers)} strategy(ies) survive multiple-testing.",
        "packages": {p["key"]: {"label": p["label"], "net_apy_band": [p["net_apy_min"], p["net_apy_max"]],
                                "max_dd_limit": p["max_dd_limit"], "candidates": pkg_counts[p["key"]]}
                     for p in PACKAGES},
        "leaderboard_tier1": evaluated,
    }
    if write:
        _DATA.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=_DATA, prefix=".tier1_")
        with os.fdopen(fd, "w") as f:
            json.dump(verdict, f, indent=2)
        os.replace(tmp, _OUT)
    return verdict


if __name__ == "__main__":
    v = evaluate()
    print(json.dumps({
        "n_trials": v["n_trials"], "n_obs_days": v["n_obs_days"],
        "sr_benchmark_annual_under_null": v["sr_benchmark_annual_under_null"],
        "dsr_passers": v["dsr_passers"], "packages": {k: x["candidates"] for k, x in v["packages"].items()},
        "top3_by_net": [(x["id"], x["net_apy_pct"], x["dsr"], x["tier1_grade"]) for x in v["leaderboard_tier1"][:3]],
        "honest_note": v["honest_note"],
    }, indent=2, ensure_ascii=False))
