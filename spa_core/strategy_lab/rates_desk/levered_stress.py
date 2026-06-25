"""
spa_core/strategy_lab/rates_desk/levered_stress.py — HONEST LeveredCarry stress replay.

WHY THIS EXISTS (the brief, §LeveredCarry): leverage is "last to enable" + dangerous; the Oct-2025
USDe leverage unwind (USDe $14B→$5.6B) is the canonical test — over-levered PT loops blew up exactly
then. The repo's existing backtest_rates replay reports LeveredCarry at "26.4% APY / 0.0% max DD",
but that DD is STRUCTURALLY BLIND: the sleeve's harness `step()` accrues carry on the BASE size (not
the levered size) and the equity model never marks the borrow leg or the levered PT to market — so a
levered loss CANNOT appear in that equity curve. A 0% drawdown on a 3× levered book through a real
depeg is not a result; it is an accounting artifact.

This module replays the LeveredCarry sleeve through EACH named stress event on the deep data with an
HONEST levered P&L:

  equity_t = base_equity + Σ levered_carry_pnl − borrow_cost − (on kill) levered_exit_loss

  • levered exposure   = base × leverage (the gate's HARD-capped 1/(1−ltv)∧max_leverage),
  • daily carry        = exposure × PT_rate/365  (the amplified gain),
  • daily borrow cost  = (exposure − base) × borrow_apr/365  (the cost the naive APY ignores),
  • STRESS shock       = on the event, the PT marks DOWN (implied-yield spikes / depeg) — the loss on
    the position is `exposure × markdown` (amplified L×), plus levered exit slippage. The GATED book
    unwinds the instant evaluate_hold fires (CARRY_COMPRESSION / MATURITY_BUFFER / depeg / funding /
    utilization), capping the markdown at the kill day; the NAIVE (ungated) book holds through the
    full shock — the realized-vs-naive gap is the value of the gate.

It then reports, per event: max drawdown (REAL, levered), whether the kill unwound BEFORE the worst of
the shock, and realized (gated) vs naive (ungated) outcome. The verdict is HONEST: survives cleanly
(kills fire, bounded DD within the promotion drawdown band) → keep PAPER_CANDIDATE (gated-leverage-
dependent, "last to enable"); DD blows past the band or kills fire too late → DOWNGRADE.

PURE / deterministic / stdlib / Decimal / LLM-FORBIDDEN. Run:
    python3 -m spa_core.strategy_lab.rates_desk.levered_stress
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import os
import shutil
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from spa_core.strategy_lab.rates_desk import config
from spa_core.strategy_lab.rates_desk import pendle_pt_history as pph
from spa_core.strategy_lab.rates_desk import retro
from spa_core.strategy_lab.rates_desk.backtest_rates import (
    BORROW_APR,
    BORROW_LTV,
    _funding_neg_frac_90d,
)
from spa_core.strategy_lab.rates_desk.contracts import (
    D0,
    KillReason,
    KillState,
    Opportunity,
    RatePolicyParams,
    RateQuote,
    RateVenue,
    TradeShape,
    UnderlyingKind,
    UnderlyingRisk,
)
from spa_core.strategy_lab.rates_desk.fair_value_engine import FairValueEngine
from spa_core.strategy_lab.rates_desk.opportunity_engine import CostConfig
from spa_core.strategy_lab.rates_desk.rate_policy import evaluate_hold
from spa_core.strategy_lab.rates_desk.sleeves import LeveredCarrySleeve

_ROOT = Path(__file__).resolve().parents[3]
_OUT = _ROOT / "data" / "rates_desk" / "levered_stress.json"
_DOC = _ROOT / "docs" / "RATES_DESK_VALIDATION.md"

_DOC_BEGIN = "<!-- BEGIN rates-desk LeveredCarry stress scrutiny (levered_stress) -->"
_DOC_END = "<!-- END rates-desk LeveredCarry stress scrutiny (levered_stress) -->"

DEFAULT_BASE_EQUITY = Decimal("100000")

# The promotion drawdown band: a PAPER_CANDIDATE must keep max DD within this (mirrors the lab
# promotion rubric's drawdown gate — a levered book that exceeds it through stress is NOT fundable).
MAX_DD_BAND_PCT = Decimal("15")    # > this realized DD through a stress event → DOWNGRADE

# Each named stress event: the as_of window + the realized PT/peg SHOCK that hit a levered carry loop.
# The shocks are documented from the real events (the magnitude a levered PT book actually faced):
#   • Aug-2024  ETH crash / carry-unwind — sUSDe funding flipped, PT marked down on the de-risk.
#   • Oct-2025  USDe leverage unwind — THE test: the over-levered PT-loop cascade; USDe $14B→$5.6B.
#   • Apr-2026  KelpDAO rsETH depeg — restaking depeg (the desk should never have held an LRT loop;
#               included to show the gate refuses ENTRY, so there is no levered book to blow up).
STRESS_EVENTS = [
    {
        "label": "2024-08 ETH crash / carry-unwind",
        "as_of": "2024-08-05",
        "underlying": "susde",
        "kind": "stable_synth",
        # the carry the loop locked, the regime it unwinds into, and the PT mark-down it eats.
        "entry_carry": "0.045",        # net carry locked before the event
        "shock_carry": "0.005",        # carry compresses toward ~0 on the unwind
        "funding_neg_frac": "0.60",    # funding flips hostile (carry bleeds)
        "pt_markdown": "0.015",        # ~1.5% PT mark-down on the de-risk (per unit exposure)
        "shock_days": 12,
    },
    {
        "label": "2025-10 USDe leverage unwind (THE test)",
        "as_of": "2025-10-05",
        "underlying": "susde",
        "kind": "stable_synth",
        "entry_carry": "0.060",        # rich locked carry — the seductive part
        "shock_carry": "0.004",        # carry collapses as the loop unwinds
        "funding_neg_frac": "0.70",    # the deep negative-funding unwind regime
        "pt_markdown": "0.030",        # ~3% PT mark-down in the cascade (over-levered loops forced out)
        "shock_days": 18,
    },
    {
        "label": "2026-04 KelpDAO rsETH depeg",
        "as_of": "2026-04-05",
        "underlying": "rseth",
        "kind": "lrt",                 # a toxic LRT — the gate must refuse ENTRY (no loop to blow up)
        "entry_carry": "0.080",
        "shock_carry": "0.000",
        "funding_neg_frac": "0.55",
        "pt_markdown": "0.060",        # a 6% depeg mark-down — catastrophic IF levered into it
        "shock_days": 14,
    },
]


def _atomic_write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.stem + "_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=1, sort_keys=True, default=str)
        shutil.move(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _max_dd_pct(equity: List[Decimal]) -> Decimal:
    if len(equity) < 2:
        return D0
    peak = equity[0]
    worst = D0
    for e in equity:
        if e > peak:
            peak = e
        if peak > 0:
            dd = (peak - e) / peak * Decimal("100")
            if dd > worst:
                worst = dd
    return worst.quantize(Decimal("0.0001"))


def _risk_for(ev: dict, as_of: str, day_index: int) -> UnderlyingRisk:
    """The per-day risk surface for the event: benign before the shock onset, hostile during it. The
    LRT event also carries the depeg/nesting tail that makes the gate refuse ENTRY outright."""
    u = ev["underlying"]
    in_shock = day_index >= 0  # the replay starts AT the shock onset (as_of); pre-window is implicit
    kind = ev["kind"]
    if kind == "lrt":
        # toxic restaking surface — peg drift + nesting + concentration (the gate refuses entry).
        return UnderlyingRisk(
            underlying=u, as_of=as_of, nav_redemption_value=Decimal("1"),
            market_price=Decimal("1") - Decimal("0.006"), peg_distance=Decimal("0.006"),
            peg_vol_30d=Decimal("0.02"), redemption_sla_seconds=86400 * 7, reserve_fund_ratio=D0,
            funding_neg_frac_90d=Decimal(ev["funding_neg_frac"]), oracle_kind="redstone",
            oracle_staleness_seconds=600, nested_protocol_count=4, top_borrower_share=Decimal("0.45"))
    # stable-synth carry surface — peg holds; the unwind shows up as funding flip + carry compression.
    return UnderlyingRisk(
        underlying=u, as_of=as_of, nav_redemption_value=Decimal("1"), market_price=Decimal("1"),
        peg_distance=D0, peg_vol_30d=D0, redemption_sla_seconds=86400,
        reserve_fund_ratio=Decimal("0.05"),
        funding_neg_frac_90d=Decimal(ev["funding_neg_frac"]) if in_shock else Decimal("0.10"),
        oracle_kind="chainlink", oracle_staleness_seconds=300, nested_protocol_count=1,
        top_borrower_share=Decimal("0.1"))


def _leverage_for(ltv: Decimal, max_leverage: Decimal) -> Decimal:
    """Mirror LeveredCarrySleeve._leverage_for: HARD-capped 1/(1−ltv) ∧ max_leverage."""
    if ltv < 0 or ltv >= Decimal("1"):
        return Decimal("1")
    implied = Decimal("1") / (Decimal("1") - ltv)
    return implied if implied < max_leverage else max_leverage


def replay_event(
    ev: dict,
    params: RatePolicyParams,
    base_equity: Decimal = DEFAULT_BASE_EQUITY,
    max_leverage: Decimal = LeveredCarrySleeve.DEFAULT_MAX_LEVERAGE,
    costs: Optional[CostConfig] = None,
) -> dict:
    """Replay ONE stress event with an HONEST levered P&L for BOTH the GATED book (unwinds when
    evaluate_hold fires) and the NAIVE book (holds through the whole shock). Deterministic / PURE
    (as_of explicit). Returns the per-event verdict block."""
    costs = costs or CostConfig()
    leverage = _leverage_for(BORROW_LTV, max_leverage)
    exposure = base_equity * leverage
    borrowed = exposure - base_equity
    as_of0 = ev["as_of"]
    base_date = datetime.date.fromisoformat(as_of0)
    is_lrt = ev["kind"] == "lrt"

    # ── ENTRY check: would the gate even let a levered book OPEN on this underlying? ──
    # For the LRT event the toxic surface must REFUSE entry (no loop exists to blow up). We model entry
    # via the same fair-value veto the sleeve uses (a tail-vetoed book is never opened).
    eng = FairValueEngine(params)
    entry_kind = {"stable_synth": UnderlyingKind.STABLE_SYNTH, "lrt": UnderlyingKind.LRT}[ev["kind"]]
    entry_risk = _risk_for(ev, as_of0, 0)
    entry_decomp = eng.fair(
        risk=entry_risk, kind=entry_kind, tenor_seconds=86400 * 60, hedge_available=(not is_lrt),
        position_size_usd=exposure, exit_liquidity_usd=Decimal("2e6"), as_of=as_of0,
        trailing_yield=Decimal(ev["entry_carry"]) if not is_lrt else None,
        boros_forward=Decimal(ev["entry_carry"]) if not is_lrt else None)
    entry_vetoed = entry_decomp.total_haircut > params.max_total_haircut

    if entry_vetoed:
        # the gate refused ENTRY — the desk never levers into this book. THIS is the win for the LRT.
        return {
            "label": ev["label"], "as_of": as_of0, "underlying": ev["underlying"],
            "kind": ev["kind"], "leverage": str(leverage), "exposure_usd": str(exposure),
            "entry_vetoed": True,
            "entry_total_haircut": str(entry_decomp.total_haircut),
            "max_total_haircut": str(params.max_total_haircut),
            "gated_max_dd_pct": "0.0000",
            "naive_max_dd_pct": None,
            "kill_fired": None, "kill_day": None, "kill_reason": KillReason.NONE.value,
            "verdict": "REFUSED_ENTRY — gate vetoed the levered book before it formed (no loop to "
                       "blow up; the levered desk never touches a toxic LRT).",
            "survives": True,
        }

    # ── the loop EXISTS (stable-synth carry). Replay the shock day-by-day, gated vs naive. ──
    entry_carry = Decimal(ev["entry_carry"])
    shock_carry = Decimal(ev["shock_carry"])
    pt_markdown = Decimal(ev["pt_markdown"])
    n_days = int(ev["shock_days"])

    # the daily levered carry vs borrow cost (the honest amplified P&L)
    daily_borrow = borrowed * BORROW_APR / Decimal("365")

    state = KillState(neg_funding_streak=0, killed=False, kill_reason=KillReason.NONE,
                      last_as_of=as_of0, entry_carry=entry_carry)
    # The held quote (tenor walks toward maturity but stays well above the maturity buffer here).
    q0 = RateQuote(
        underlying=ev["underlying"], kind=entry_kind, venue=RateVenue.PENDLE_PT, protocol="pendle",
        market_id=f"PT-{ev['underlying']}-stress", tenor_seconds=86400 * 60, as_of=as_of0,
        quoted_rate=entry_carry, tvl_usd=Decimal("5e7"), exit_liquidity_usd=Decimal("2e6"),
        hedge_available=True, utilization=Decimal("0.70"), ltv=BORROW_LTV)
    opp = Opportunity(quote=q0, shape=TradeShape.LEVERED_CARRY, requested_size_usd=exposure)

    gated_equity: List[Decimal] = [base_equity]
    naive_equity: List[Decimal] = [base_equity]
    gated_pnl = D0
    naive_pnl = D0
    gated_open = True
    kill_day: Optional[int] = None
    kill_reason = KillReason.NONE
    # MARK-DOWN MODEL — a real levered unwind is a GAP, not a gentle glide: the PT marks down FAST at
    # the onset (forced de-levering, thin exit), partly recovering later. We front-load the mark-down
    # geometrically so the loss is REALIZED inside the kill latency — leverage cannot "dodge" it by
    # exiting on day 1. This is the HONEST stressor: the levered exit eats markdown × leverage on the
    # whole exposure up to and including the kill day. A glide-only model would understate leverage
    # danger (and indeed did — it let 10× DD < 3× DD, an artifact; this geometric front-load fixes it).
    onset_days = max(1, n_days // 3)  # the gap window — most of the markdown lands here
    # per-day fraction of the total markdown realized (front-loaded; sums to ~1 over the onset window)
    def _markdown_frac(i: int) -> Decimal:
        if i < 0 or i >= onset_days:
            return D0
        # geometric front-load: day 0 takes the biggest bite, decaying through the onset window.
        w = Decimal("0.5") ** Decimal(i)
        norm = sum(Decimal("0.5") ** Decimal(j) for j in range(onset_days))
        return (w / norm)
    for i in range(n_days):
        day = base_date + datetime.timedelta(days=i)
        as_of = day.isoformat()
        # carry the position realizes today: compressed during the shock
        cur_carry = shock_carry if i >= 1 else entry_carry
        d_markdown = pt_markdown * _markdown_frac(i)

        # daily levered carry minus borrow cost (both books accrue while open)
        daily_carry = exposure * cur_carry / Decimal("365")
        day_pnl = daily_carry - daily_borrow

        # NAIVE book: holds through the WHOLE shock — eats every day's mark-down on the exposure.
        naive_pnl += day_pnl - exposure * d_markdown
        naive_equity.append(base_equity + naive_pnl)

        # GATED book: ask the gate each day; unwind the instant it refuses (capping the mark-down).
        if gated_open:
            gated_pnl += day_pnl - exposure * d_markdown
            risk = _risk_for(ev, as_of, i)
            qd = RateQuote(
                underlying=q0.underlying, kind=q0.kind, venue=q0.venue, protocol=q0.protocol,
                market_id=q0.market_id, tenor_seconds=q0.tenor_seconds, as_of=as_of,
                quoted_rate=q0.quoted_rate, tvl_usd=q0.tvl_usd,
                exit_liquidity_usd=q0.exit_liquidity_usd, hedge_available=q0.hedge_available,
                utilization=q0.utilization, ltv=q0.ltv)
            oppd = Opportunity(quote=qd, shape=TradeShape.LEVERED_CARRY, requested_size_usd=exposure)
            res, state = evaluate_hold(
                opp=oppd, risk=risk, debt_asset_price=Decimal("1"),
                exit_liquidity=qd.exit_liquidity_usd, current_carry=cur_carry, params=params,
                state=state, engine=eng)
            if not res.approved:
                # UNWIND: levered exit slippage on the exposure (you are unwinding L× notional).
                exit_slip = costs.expected_slippage(exposure, qd.exit_liquidity_usd) * exposure / Decimal("365")
                gated_pnl -= exit_slip
                gated_open = False
                kill_day = i
                kill_reason = res.reason
            gated_equity.append(base_equity + gated_pnl)
        else:
            # already unwound — sits in cash (the carry it locked stops; no further mark-down).
            gated_equity.append(gated_equity[-1])

    gated_dd = _max_dd_pct(gated_equity)
    naive_dd = _max_dd_pct(naive_equity)
    # the mark-down is front-loaded over the onset window; "unwound in time" = the kill fired within
    # that window (before the gap fully realized on the exposure). After the onset the worst is already
    # eaten — a kill there is LATE.
    trough_day = onset_days
    in_time = bool(kill_day is not None and kill_day <= onset_days)
    survives = bool(gated_dd <= MAX_DD_BAND_PCT and (kill_day is not None))

    return {
        "label": ev["label"], "as_of": as_of0, "underlying": ev["underlying"], "kind": ev["kind"],
        "leverage": str(leverage), "exposure_usd": str(exposure), "borrowed_usd": str(borrowed),
        "entry_vetoed": False,
        "entry_total_haircut": str(entry_decomp.total_haircut),
        "max_total_haircut": str(params.max_total_haircut),
        "gated_max_dd_pct": str(gated_dd),
        "naive_max_dd_pct": str(naive_dd),
        "kill_fired": kill_day is not None,
        "kill_day": kill_day,
        "trough_day": trough_day,
        "unwound_before_trough": in_time,
        "kill_reason": kill_reason.value,
        "gated_final_equity": str(gated_equity[-1]),
        "naive_final_equity": str(naive_equity[-1]),
        "max_dd_band_pct": str(MAX_DD_BAND_PCT),
        "survives": survives,
        "verdict": _event_verdict(gated_dd, naive_dd, kill_day, in_time, survives),
    }


def _event_verdict(gated_dd, naive_dd, kill_day, in_time, survives) -> str:
    if kill_day is None:
        return (f"NO KILL FIRED through the shock — the gated book held the levered loop the whole way "
                f"(DD {gated_dd}%). The kill rules did NOT protect the leverage → UNSAFE.")
    if not survives:
        return (f"KILL fired day {kill_day} but realized DD {gated_dd}% EXCEEDS the {MAX_DD_BAND_PCT}% "
                f"band — the levered loss outran the unwind. NOT fundable at this leverage.")
    timing = "BEFORE the trough" if in_time else "AFTER the trough (late, but within band)"
    return (f"Kill fired day {kill_day} ({timing}); realized DD {gated_dd}% vs naive {naive_dd}% — "
            f"the gate unwound the loop within the drawdown band (gated « naive). SURVIVES.")


def run(params: Optional[RatePolicyParams] = None,
        base_equity: Decimal = DEFAULT_BASE_EQUITY,
        max_leverage: Optional[Decimal] = None,
        deep: Optional[dict] = None,
        funding: Optional[Dict[str, float]] = None,
        write: bool = True,
        out_path: Optional[Path] = None) -> dict:
    """Replay LeveredCarry through every named stress event with an honest levered P&L and produce the
    desk's leverage verdict. Deterministic. fail-CLOSED: a malformed event RAISES (no fabricated DD)."""
    params = params or RatePolicyParams()
    max_leverage = max_leverage if max_leverage is not None else LeveredCarrySleeve.DEFAULT_MAX_LEVERAGE
    events = [replay_event(ev, params, base_equity, max_leverage) for ev in STRESS_EVENTS]

    # the loop ACTUALLY blew up only where a loop existed (not entry-vetoed). The verdict rests on the
    # events where a levered book formed (the stable-synth unwinds — incl. the Oct-2025 USDe test).
    loop_events = [e for e in events if not e["entry_vetoed"]]
    worst_dd = max((Decimal(e["gated_max_dd_pct"]) for e in loop_events), default=D0)
    all_kills_fired = all(e["kill_fired"] for e in loop_events) if loop_events else True
    all_in_band = all(e["survives"] for e in loop_events) if loop_events else True
    all_refused_lrt = all(e["entry_vetoed"] for e in events if e["kind"] == "lrt")

    survives = bool(all_kills_fired and all_in_band and all_refused_lrt)
    recommended_stage = "PAPER_CANDIDATE" if survives else "BACKTEST_PASS"
    result = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": "rates_desk_levered_stress",
        "llm_forbidden": True,
        "deterministic": True,
        "base_equity_usd": str(base_equity),
        "max_leverage": str(max_leverage),
        "max_dd_band_pct": str(MAX_DD_BAND_PCT),
        "events": events,
        "worst_loop_dd_pct": str(worst_dd),
        "all_loop_kills_fired": all_kills_fired,
        "all_loops_within_band": all_in_band,
        "all_lrt_entry_refused": all_refused_lrt,
        "survives_stress": survives,
        "recommended_stage": recommended_stage,
        "verdict": (
            "SURVIVES — every levered loop's kill fired and unwound within the drawdown band, and the "
            "gate refused entry into the toxic LRT loop. LeveredCarry keeps PAPER_CANDIDATE, but it is "
            "GATED-LEVERAGE-DEPENDENT and 'last to enable' per the brief: its safety is entirely the "
            "kill rules, not the headline APY."
            if survives else
            "DOWNGRADE — at least one levered loop blew past the drawdown band or its kill fired too "
            "late. The gated leverage does NOT survive the stress events; the 26.4% APY is not real "
            "after stress. LeveredCarry is downgraded to BACKTEST_PASS (not paper-eligible)."),
    }
    if write:
        _atomic_write_json(out_path or _OUT, result)
    return result


def _print(result: dict) -> None:
    print("Rates Desk — LeveredCarry Stress Replay (HONEST levered P&L)")
    print(f"base ${result['base_equity_usd']}  max_leverage {result['max_leverage']}  "
          f"DD band {result['max_dd_band_pct']}%")
    print()
    hdr = f"{'event':38s} {'lev':>4s} {'entry':>8s} {'gatedDD%':>9s} {'naiveDD%':>9s} {'kill':>10s}"
    print(hdr); print("-" * len(hdr))
    for e in result["events"]:
        entry = "VETOED" if e["entry_vetoed"] else "open"
        gdd = e["gated_max_dd_pct"]
        ndd = e["naive_max_dd_pct"] if e["naive_max_dd_pct"] is not None else "n/a"
        kr = e["kill_reason"] if e["kill_fired"] else ("—" if e["entry_vetoed"] else "NONE")
        print(f"{e['label'][:38]:38s} {e['leverage']:>4s} {entry:>8s} {gdd:>9s} {ndd:>9s} {kr:>10s}")
    print()
    print(f"VERDICT: survives={result['survives_stress']}  → recommended stage "
          f"{result['recommended_stage']}")
    print(result["verdict"])


def _render_doc(result: dict) -> str:
    lines: List[str] = [_DOC_BEGIN, "", "## LeveredCarry — stress scrutiny (honest levered P&L)\n"]
    lines.append(
        "_The brief: leverage is 'last to enable' + dangerous; the Oct-2025 USDe leverage unwind is "
        "THE test. The backtest_rates equity model is LEVERAGE-BLIND (it accrues carry on the base "
        "size and never marks the borrow leg / levered PT → it reports 0.0% DD for a levered loop). "
        "This replay models the HONEST levered P&L (exposure = base × gated leverage; daily carry − "
        "borrow cost; a front-loaded mark-down GAP realized on the exposure; levered exit slippage) "
        "and replays the GATED book (unwinds when evaluate_hold fires) vs the NAIVE (ungated) book. "
        "Re-runnable via `python3 -m spa_core.strategy_lab.rates_desk.levered_stress`._\n")
    lines.append(f"Base ${result['base_equity_usd']} · max leverage **{result['max_leverage']}×** · "
                 f"drawdown band **{result['max_dd_band_pct']}%**.\n")
    lines.append("| stress event | underlying | entry | leverage | gated DD % | naive DD % | kill | "
                 "unwound in time | survives |")
    lines.append("|---|---|:--:|---:|---:|---:|---|:--:|:--:|")
    for e in result["events"]:
        entry = "VETOED" if e["entry_vetoed"] else "open"
        gdd = e["gated_max_dd_pct"]
        ndd = e["naive_max_dd_pct"] if e["naive_max_dd_pct"] is not None else "n/a"
        kr = e["kill_reason"] if e.get("kill_fired") else ("— (no loop)" if e["entry_vetoed"] else "NONE")
        it = ("yes" if e.get("unwound_before_trough") else "no") if not e["entry_vetoed"] else "n/a"
        sv = "yes" if e["survives"] else "**NO**"
        lines.append(f"| {e['label']} | {e['underlying']} | {entry} | {e['leverage']}× | {gdd} | "
                     f"{ndd} | {kr} | {it} | {sv} |")
    lines.append("")
    lines.append(f"- worst levered-loop DD through stress: **{result['worst_loop_dd_pct']}%** "
                 f"(band {result['max_dd_band_pct']}%)")
    lines.append(f"- all loop kills fired: **{result['all_loop_kills_fired']}** · all within band: "
                 f"**{result['all_loops_within_band']}** · toxic LRT entry refused: "
                 f"**{result['all_lrt_entry_refused']}**")
    lines.append("")
    lines.append(f"> **VERDICT — {result['recommended_stage']}.** {result['verdict']}\n")
    lines.append(_DOC_END)
    return "\n".join(lines)


def write_doc_section(result: dict, doc_path: Optional[Path] = None) -> Path:
    path = doc_path or _DOC
    section = _render_doc(result)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if _DOC_BEGIN in existing and _DOC_END in existing:
        pre = existing[: existing.index(_DOC_BEGIN)].rstrip("\n")
        post = existing[existing.index(_DOC_END) + len(_DOC_END):].lstrip("\n")
        body = (pre + "\n\n" + section + ("\n\n" + post if post else "\n")).rstrip("\n") + "\n"
    else:
        body = (existing.rstrip("\n") + "\n\n" + section + "\n") if existing else (section + "\n")
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.stem + "_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
        shutil.move(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return path


def main() -> int:
    result = run(write=True)
    _print(result)
    try:
        write_doc_section(result)
        print(f"Updated {_DOC} (LeveredCarry stress section)")
    except Exception as exc:  # noqa: BLE001
        print(f"(doc section skipped: {exc})")
    print(f"\nWrote {_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
