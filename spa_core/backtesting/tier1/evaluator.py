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
import re
from pathlib import Path
from typing import Optional

from spa_core.backtesting.tier1 import deflated_sharpe as ds
from spa_core.backtesting.tier1 import oos as oos_mod
from spa_core.backtesting.tier1.cost_model import net_of_cost_apy
from spa_core.backtesting.tier1.tail_risk import strategy_tail_risk
from spa_core.utils.atomic import atomic_save

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


def _data_source() -> dict:
    """Read the historical-APY cache to tell REAL DeFiLlama data from absent/mock."""
    try:
        c = json.loads((_DATA / "bee" / "defillama_apy_history.json").read_text())
        pr = c.get("pool_results", {})
        days = [v.get("n_days", 0) for v in pr.values() if isinstance(v, dict)]
        return {"source": c.get("source"), "matched": c.get("matched", len(pr)),
                "max_days": max(days) if days else 0}
    except Exception:
        return {"source": None, "matched": 0, "max_days": 0}


# Capacity: a single position must not exceed this share of its pool's TVL (institutional
# liquidity constraint — matters when scaling to external AUM, the $100M goal).
CAPACITY_MAX_POOL_PCT = 0.02  # 2% of pool TVL


def _load_tvl() -> Dict[str, float]:
    """{protocol: tvl_usd} from the real DeFiLlama cache (for capacity)."""
    try:
        c = json.loads((_DATA / "bee" / "defillama_apy_history.json").read_text())
        return {k: float(v.get("tvl_usd") or 0.0)
                for k, v in (c.get("pool_results") or {}).items() if isinstance(v, dict)}
    except Exception:
        return {}


def _capacity(allocation: dict, tvl_map: Dict[str, float], capital: float) -> dict:
    """Max AUM the allocation can hold before any position exceeds CAPACITY_MAX_POOL_PCT of
    its pool, and whether the CURRENT capital fits. Protocols without TVL data are skipped."""
    weights = {k: float(v) for k, v in (allocation or {}).items()
               if k != "cash" and v and tvl_map.get(k, 0) > 0}
    if not weights:
        return {"capacity_aum_usd": None, "capacity_ok": True, "binding_protocol": None}
    # per protocol: max_aum_i = tvl_i * CAP_PCT / weight_i ; capacity = min over protocols
    per = {p: tvl_map[p] * CAPACITY_MAX_POOL_PCT / w for p, w in weights.items()}
    binding = min(per, key=per.get)
    cap_aum = per[binding]
    return {"capacity_aum_usd": round(cap_aum, 0),
            "capacity_ok": cap_aum >= capital,
            "binding_protocol": binding}


def _regime(dq: dict, src: dict) -> str:
    """NORMAL = vol meaningful, Sharpe usable.
    LOW_VOL_YIELD = REAL data but near-deterministic yield → Sharpe degenerate BY NATURE,
                    rank by net-of-cost APY + tail risk (the Tier-1-correct metric).
    DEGENERATE_MOCK = degenerate AND no real data → not trustworthy, fix the data."""
    real = src.get("source") == "defillama_real" and src.get("matched", 0) > 0
    if dq["status"] != "DEGENERATE":
        return "NORMAL"
    return "LOW_VOL_YIELD" if real else "DEGENERATE_MOCK"


def _assign_package(net_apy: float, max_dd_pct: float) -> Optional[str]:
    dd = abs(max_dd_pct or 0.0)
    for p in PACKAGES:
        if p["net_apy_min"] <= net_apy < p["net_apy_max"] and dd <= p["max_dd_limit"]:
            return p["key"]
    return None


def _grade_yield(net_apy: float, in_package: bool, oos_holds: Optional[bool]) -> str:
    """Yield-regime grade — Sharpe inapplicable; net-of-cost APY + package fit + OOS hold."""
    if oos_holds is False:
        return "C"          # net positive but yield decayed out-of-sample → not top-grade
    if net_apy >= 3.0 and in_package and oos_holds:
        return "A"          # solid net yield, fits a package, AND holds out-of-sample
    if net_apy > 0 and in_package:
        return "B"          # positive net yield, fits a package (OOS unknown/insufficient)
    if net_apy > 0:
        return "C"          # positive net but outside package risk bands
    return "D"              # negative net-of-cost


def _grade(dsr: float, psr: float, net_apy: float) -> str:
    if dsr >= DSR_PASS and net_apy > 0:
        return "A"          # edge survives multiple-testing
    if psr >= PSR_PASS and net_apy > 0:
        return "B"          # individually significant, not yet multiple-testing-proof
    if net_apy > 0:
        return "C"          # positive net but statistically unproven
    return "D"              # negative net-of-cost or no edge


def assess_tournament_trust(result: dict) -> dict:
    """Trustworthiness stamp for a mass-tournament result — the SINGLE honesty gate.

    Reuses the Tier-1 degeneracy detector (_assess_data_quality) + the real-vs-mock data
    provenance (_data_source) + the regime classifier (_regime) so the PRODUCER, the API,
    and the public site all agree on one verdict. A Sharpe-ranked leaderboard is trustworthy
    ONLY when the underlying returns are not near-constant (degenerate). Stablecoin yield is
    near-deterministic, so a Sharpe ranking is NOT trustworthy regardless of whether the data
    is real (LOW_VOL_YIELD) or mock (DEGENERATE_MOCK) — both → trustworthy=False.

    Returns a dict (always; fail-CLOSED → trustworthy=False on any error):
      {trustworthy, data_source, data_source_regime, data_quality, reason}
    """
    try:
        board = (result or {}).get("leaderboard", []) or []
        dq = _assess_data_quality(board)
        src = _data_source()
        regime = _regime(dq, src)
        # Trustworthy iff the data is NOT degenerate (NORMAL regime). Sharpe on near-constant
        # returns (LOW_VOL_YIELD or DEGENERATE_MOCK) is mathematically degenerate → untrusted.
        trustworthy = bool(dq.get("trustworthy")) and regime == "NORMAL"
        if regime == "DEGENERATE_MOCK":
            reason = ("MOCK / no real APY data — Sharpe ranking is degenerate and NOT a live "
                      "result. " + dq.get("reason", ""))
        elif regime == "LOW_VOL_YIELD":
            reason = ("Real DeFiLlama data but stablecoin yield is near-deterministic → Sharpe "
                      "degenerate by asset class; a Sharpe leaderboard is not a trustworthy live "
                      "ranking. Rank by net-of-cost APY (Tier-1 verdict) instead.")
        else:
            reason = dq.get("reason", "volatility/Sharpe in a plausible range")
        return {
            "trustworthy": trustworthy,
            "data_source": src.get("source") or "none",
            "data_source_regime": regime,
            "data_quality": dq,
            "reason": reason,
        }
    except Exception as exc:  # fail-CLOSED — never present an unverified ranking as live
        return {
            "trustworthy": False,
            "data_source": "unknown",
            "data_source_regime": "DEGENERATE_MOCK",
            "data_quality": {"status": "ERROR", "trustworthy": False, "reason": str(exc)},
            "reason": f"trust assessment failed ({exc}) — fail-closed, ranking not trustworthy",
        }


def evaluate(write: bool = True) -> dict:
    result = json.loads(_RESULTS.read_text())
    board = result.get("leaderboard", []) or []
    capital = float(result.get("initial_capital_usd") or DEFAULT_CAPITAL)
    n_obs = _parse_n_obs(result)
    n_trials = int(result.get("strategies_tested") or len(board) or 1)
    dq = _assess_data_quality(board)
    src = _data_source()
    regime = _regime(dq, src)

    # Per-period Sharpe variance across all trials (consistent units for DSR).
    sharpes_pp = [ds.deannualize_sharpe(float(e.get("sharpe") or 0.0)) for e in board]
    sr_var_pp = ds.sharpe_variance_across_trials(sharpes_pp)
    series_map = oos_mod.load_protocol_series()  # real per-protocol APY for OOS
    tvl_map = _load_tvl()                         # real per-protocol TVL for capacity

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
        oos_res = oos_mod.oos_check(alloc if isinstance(alloc, dict) else {}, series_map)
        oos_holds = oos_res.get("oos_holds")  # True / False / None(insufficient)
        cap = _capacity(alloc if isinstance(alloc, dict) else {}, tvl_map, capital)
        tr = strategy_tail_risk(alloc if isinstance(alloc, dict) else {})
        risk_adj_apy = round(net_apy - tr["tail_risk_pct"], 4)
        dsr_passes = bool(dsr["passes"])
        # Grade by REGIME: Sharpe-DSR for NORMAL; net-yield + OOS for real low-vol yield;
        # UNPROVEN when degenerate AND data isn't real (mock).
        if regime == "NORMAL":
            grade = _grade(dsr["dsr"], psr, net_apy)
            validated = dsr_passes and net_apy > 0
        elif regime == "LOW_VOL_YIELD":
            grade = _grade_yield(net_apy, pkg is not None, oos_holds)
            # validated = real data + fits a package + yield held out-of-sample + capacity OK
            validated = (net_apy > 0 and pkg is not None and oos_holds is not False
                         and cap["capacity_ok"])
        else:  # DEGENERATE_MOCK
            grade = "UNPROVEN"
            validated = False
        if pkg and validated:
            pkg_counts[pkg] += 1
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
            "dsr_passes": dsr_passes,          # informational under LOW_VOL_YIELD
            "oos_in_sample_apy_pct": oos_res.get("in_sample_apy_pct"),
            "oos_out_sample_apy_pct": oos_res.get("out_of_sample_apy_pct"),
            "oos_holds": oos_holds,
            "oos_status": oos_res.get("status"),
            "capacity_aum_usd": cap["capacity_aum_usd"],
            "capacity_ok": cap["capacity_ok"],
            "tail_risk_pct": tr["tail_risk_pct"],
            "risk_adjusted_apy_pct": risk_adj_apy,
            "validated": validated,            # regime-appropriate pass (drives packages)
            "min_track_record_days": round(mtrl, 1) if mtrl != float("inf") else None,
            "tier1_grade": grade,
            "package": pkg,
        })

    # Rank validated first, then by RISK-ADJUSTED net APY (net-of-cost minus tail risk) —
    # the yield you keep after expected principal loss, the correct Tier-1 yield ranking.
    evaluated.sort(key=lambda x: (x["validated"], x["risk_adjusted_apy_pct"]), reverse=True)
    passers = [x for x in evaluated if x["validated"]]

    verdict = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": "tier1_parallel",
        "llm_forbidden": True,
        "n_trials": n_trials,
        "n_obs_days": n_obs,
        "sr_benchmark_annual_under_null": round(
            ds.annualize_sharpe(ds.expected_max_sharpe(sr_var_pp, n_trials)), 3),
        "dsr_pass_threshold": DSR_PASS,
        "regime": regime,
        "ranking_metric": "net_of_cost_apy" if regime == "LOW_VOL_YIELD" else "deflated_sharpe",
        "data_quality": dq,
        "data_source": src,
        "strategies_evaluated": len(evaluated),
        "validated_count": len(passers),
        "honest_note": {
            "DEGENERATE_MOCK": "DATA QUALITY FAIL — " + dq["reason"],
            "LOW_VOL_YIELD": (
                f"REAL DeFiLlama data ({src.get('matched')} protocols, up to {src.get('max_days')}d). "
                "Stablecoin yield is near-deterministic → Sharpe degenerate BY ASSET CLASS "
                "(not a data bug). Ranking by NET-OF-COST APY + package risk bands (the "
                f"Tier-1-correct metric). {len(passers)} strategy(ies) validated into packages. "
                "Tail/principal risk (depeg/exploit) is governed separately by RiskPolicy."
            ),
            "NORMAL": (
                f"{len(passers)} strategy(ies) survive multiple-testing (DSR)."
                if passers else
                "0 DSR-passers — expected-max Sharpe under the null is high; nothing proven yet."
            ),
        }[regime],
        "packages": {p["key"]: {"label": p["label"], "net_apy_band": [p["net_apy_min"], p["net_apy_max"]],
                                "max_dd_limit": p["max_dd_limit"], "candidates": pkg_counts[p["key"]]}
                     for p in PACKAGES},
        "leaderboard_tier1": evaluated,
    }
    if write:
        atomic_save(verdict, str(_OUT))
    return verdict


if __name__ == "__main__":
    v = evaluate()
    print(json.dumps({
        "regime": v["regime"], "ranking_metric": v["ranking_metric"],
        "data_source": v["data_source"], "n_obs_days": v["n_obs_days"],
        "validated_count": v["validated_count"],
        "packages": {k: x["candidates"] for k, x in v["packages"].items()},
        "top3": [(x["id"], "net=%.2f%%" % x["net_apy_pct"], "dd=%s" % x["max_dd_pct"], x["tier1_grade"])
                 for x in v["leaderboard_tier1"][:3]],
        "honest_note": v["honest_note"],
    }, indent=2, ensure_ascii=False))
