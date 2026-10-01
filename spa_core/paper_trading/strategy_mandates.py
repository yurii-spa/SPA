"""spa_core/paper_trading/strategy_mandates.py — the three package MANDATES and their experiments.

Owner requirement 2026-10-01 (ADR-533): Conservative, Balanced and Aggressive are three separate
PAPER portfolios that differ by investment MECHANIC, not by protocol tier. A mandate is the
contract of one package: which mechanics it may use, where its yield comes from, when it enters,
holds and exits, what it costs, where it stops, who is responsible, and which decision / tests /
experiment it answers to.

**Strategy version ≠ accounting version.** ``sleeve-econ-v2`` (ADR-531) fixed how a sleeve is
charged; it did not create any mechanic. A mandate carries both, separately.

**Experiments.** A change of mechanic opens a NEW experiment in the SAME canonical book: earlier
rows stay exactly as written, their experiment id stays theirs, and no figure of an earlier
experiment is attributed to the new one. ``ensure_experiment`` opens an experiment once, records
its explicit initial virtual state, and is idempotent (re-running a day opens nothing new).

Every mechanic here is PAPER. Borrowing, leverage and liquidation exist only inside the simulated
loop experiment of the Aggressive package; nothing in this tree signs or sends a transaction.
LLM_FORBIDDEN, stdlib only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from typing import Optional

ROLES = {
    "opportunity_scan": "rank eligible markets from live feeds (sleeve_book.book_candidates / pendle_market / morpho_market)",
    "net_economics": "compute carry net of modelled costs before any move (pt_carry / loop_book economics)",
    "position_simulation": "build and value the simulated position (pt_carry legs / loop_book collateral+debt)",
    "risk_and_stress": "entry gates, stop conditions, stress scenarios (loop_book.stress, pt_carry gates)",
    "debt_supervision": "health factor, deleverage, unwind, liquidation simulation (loop_book.supervise)",
    "liquidity_exit": "exit latency / depth (defi_engine.exit_model, market liquidity in the feeds)",
    "portfolio_supervision": "book-level kill and CIO arming (hy_cycle / lp_cycle / cycle_runner gates)",
    "independent_review": "a separate reviewer agent per delivery (ADR-532/533 review sections)",
}

MANDATES: dict[str, dict] = {
    "conservative": {
        "strategy_id": "conservative-lending",
        "strategy_version": "conservative-lending-v1",
        "accounting_version": "main-book-adr298",
        "experiment_id": "conservative-lending-v1@2026-06-22",
        "experiment_started": "2026-06-22",
        "engine": "cycle_runner (com.spa.daily_cycle, daily 08:00 local)",
        "book": "data/current_positions.json + data/equity_curve_daily.json",
        "mechanic": "unlevered stablecoin supply in T1/T2 lending markets",
        "yield_source": "borrowers' interest on over-collateralised lending markets",
        "instruments": ["T1/T2 lending markets on the RiskPolicy v1.0 whitelist"],
        "entry": "allocator target that passes RiskPolicy v1.0, TVL floor on LIVE TVL, CIO arming",
        "hold": "CIO HOLD when the gain does not beat the band or payback is too long (ADR-060)",
        "exit": "RiskPolicy violation, Tier-A BLOCK, stale feed (unevidenced), kill switch",
        "costs": "modelled gas + slippage of the book's own moves (ADR-298, cost_model)",
        "limits": "RiskPolicy v1.0: T1 ≤40 %, T2 ≤20 %/protocol, T2 total ≤50 %, cash ≥5 %",
        "stop": "SOFT_DERISK at −5 % from peak, HARD_KILL at −10 % (ADR-034/048)",
        "leverage": "none (no borrowing of its own)",
        "target_mechanics": ["supply", "savings_rate"],
        "roles": ["opportunity_scan", "net_economics", "risk_and_stress", "liquidity_exit",
                  "portfolio_supervision"],
        "refs": {"decision": ["ADR-019", "ADR-034", "ADR-048", "ADR-060", "ADR-298", "ADR-533"],
                 "tests": ["spa_core/tests/test_cycle_runner.py", "spa_core/tests/test_paper_mechanics.py"]},
    },
    "balanced": {
        "strategy_id": "balanced-fixed-carry",
        "strategy_version": "balanced-fixed-carry-v1",
        "accounting_version": "sleeve-econ-v2",
        "engine": "hy_cycle (com.spa.hy_cycle, hourly; one accounting row a day)",
        "book": "data/hy_paper_trading.json",
        "mechanic": ("unlevered fixed rate: Pendle PT bought at a discount and held to maturity, "
                     "next to floating stablecoin supply"),
        "yield_source": ("the fixed rate locked at purchase (PT pulls to par at expiry) plus "
                         "borrowers' interest on the floating part"),
        "instruments": ["Pendle PT on an underlying with an evidenced USD peg (today: sUSDS)",
                        "the floating lending candidates of the sleeve (live APY + live TVL)"],
        "entry": ("PT listed, observed price agrees with the implied-APY price, 21–270 days to expiry, "
                  "market liquidity ≥ $2M and the order ≤ 2 % of it, implied APY ≥ max(3 %, floating "
                  "benchmark − 1.0 pp); fixed part ≤ 40 % of equity, ≤ 25 % per market"),
        "hold": "a PT leg is held to maturity; no eligible market ⇒ the book stays floating (HOLD)",
        "exit": ("maturity ⇒ redeemed at par (1 accounting-asset unit); stop condition (mark unmeasured "
                 "3 days) ⇒ no adds, the held legs are kept to maturity — v1 never sells before expiry"),
        "costs": "PT trade: Pendle fee + 5 bp slippage on notional + $12 gas; lending: sleeve cost model",
        "limits": "fixed-rate share ≤ 40 %; per market ≤ 25 %; underlying peg must be evidenced",
        "stop": "book kill at −8 % from peak (hy_cycle); PT stop: market mark unmeasured 3 days ⇒ no adds",
        "leverage": "none",
        "target_mechanics": ["pt_fixed", "supply", "savings_rate"],
        "roles": ["opportunity_scan", "net_economics", "position_simulation", "risk_and_stress",
                  "liquidity_exit", "portfolio_supervision"],
        "refs": {"decision": ["ADR-531", "ADR-532", "ADR-533"],
                 "tests": ["spa_core/tests/test_paper_mechanics.py", "spa_core/tests/test_paper_cycles.py"]},
    },
    "aggressive": {
        "strategy_id": "aggressive-susde-loop",
        "strategy_version": "aggressive-susde-loop-v1",
        "accounting_version": "sleeve-econ-v2",
        "engine": "lp_cycle (com.spa.lp_cycle, hourly; supervision every run, accounting row daily)",
        "book": "data/lp_paper_trading.json",
        "mechanic": ("SIMULATED recursive lending: sUSDe collateral, PYUSD debt on Morpho Blue "
                     "(market 0x90ef…, LLTV 0.915), next to concentrated stablecoin supply"),
        "yield_source": ("sUSDe staking yield on L× the loop equity minus PYUSD borrow interest on "
                         "(L−1)×; sUSDe yield = Ethena funding + staking, variable"),
        "instruments": ["one Morpho Blue market (fixed identity, verified on-chain each run)",
                        "the concentrated lending candidates of the sleeve (top-2, ≤60 %)"],
        "entry": ("all inputs measured (on-chain quorum + two borrow-rate sources); spread yield − "
                  "borrow ≥ 0.5 pp; levered net after round-trip cost amortised over 90 days ≥ "
                  "unlevered yield + 1.0 pp; utilisation ≤ 95 %; free liquidity ≥ 20× the borrow"),
        "hold": "target LTV 0.70 (HF ≈ 1.31); no entry condition met ⇒ the loop part stays in lending",
        "exit": ("HF < 1.15 ⇒ deleverage to target; HF < 1.08, implied USDe < 0.97 or negative carry "
                 "3 days running ⇒ full unwind; HF ≤ 1.0 ⇒ liquidation simulated with the market LIF"),
        "costs": "swap 5 bp of the traded notional (×3 under stress) + $12 gas per transaction",
        "limits": "loop equity ≤ 50 % of the book; LTV ≤ 0.75 at entry; one market",
        "stop": "book kill at −25 % from peak (lp_cycle); loop unwinds on its own triggers first",
        "leverage": "SIMULATED only — paper experiment, no key, no transaction",
        "target_mechanics": ["loop", "supply"],
        "roles": list(ROLES),
        "refs": {"decision": ["ADR-531", "ADR-532", "ADR-533"],
                 "tests": ["spa_core/tests/test_paper_mechanics.py", "spa_core/tests/test_paper_cycles.py"]},
    },
}


def mandate(package: str) -> dict:
    return MANDATES[package]


def experiment_id(package: str, start_date: str) -> str:
    return f"{MANDATES[package]['strategy_version']}@{start_date}"


def ensure_experiment(state: dict, package: str, *, start_date: str, run_ts: str,
                      initial_equity: float, initial_note: str) -> dict:
    """Open the CURRENT mandate's experiment in ``state`` once; return it. Idempotent.

    Earlier experiments (and the rows they wrote) are never touched. The initial virtual state is
    recorded explicitly — the new version does not inherit the old version's statistics.
    """
    m = MANDATES[package]
    exps = state.setdefault("experiments", [])
    for e in exps:
        if e.get("strategy_version") == m["strategy_version"]:
            return e
    if not exps:
        # The book's history before the first explicit experiment is recorded as such, not erased.
        exps.append({"experiment_id": f"{package}-legacy-lending",
                     "strategy_version": f"{package}-legacy-lending",
                     "accounting_version": "mixed (sleeve-econ-v1 rows, then sleeve-econ-v2)",
                     "status": "closed",
                     "closed_at": run_ts,
                     "note": "rows written before ADR-533; kept as written, not attributed to any new version"})
    else:
        for e in exps:
            if e.get("status") == "active":
                e["status"] = "closed"
                e["closed_at"] = run_ts
    exp = {"experiment_id": experiment_id(package, start_date),
           "strategy_version": m["strategy_version"], "accounting_version": m["accounting_version"],
           "status": "active", "started_at": run_ts, "start_date": start_date,
           "initial_state": {"equity_usd": round(float(initial_equity), 2), "note": initial_note}}
    exps.append(exp)
    return exp


def active_experiment(state: dict) -> Optional[dict]:
    for e in reversed(state.get("experiments") or []):
        if e.get("status") == "active":
            return e
    return None
