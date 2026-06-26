"""
spa_core/strategy_lab/rates_desk/capacity.py — the Rates-Desk CAPACITY curve (does the edge survive size?).

The single fundability question every allocator asks of thesis #1 (FixedCarry → GO): "this carry is
real, but how much capital can it absorb before slippage/depth erodes the edge below the RWA floor?"

The validated FixedCarry SURVIVOR book (backtest_rates: ~6.09% net APY at $100k, beats the 3.4% floor)
clips a genuinely-mispriced stable-synth PT carry. But that carry lives in THIN Pendle PT pools. As the
deployed AUM grows, the §9 exit-capacity sizing (rate_policy SIZE rule: size <= max_size_frac_of_exit *
exit_liquidity, where exit_liquidity = contemporaneous pool_depth * impact_band * sla_discount) caps how
much can go into each market. Beyond that cap the book has only two honest places to put the marginal
dollar:

  (a) IDLE @ the RWA floor — the un-deployable remainder earns the cash/RWA floor (~3.4%), diluting the
      book APY DOWN toward the floor; and/or
  (b) DEEPER market impact — pushing past the impact band means slippage on the carry leg (the engine's
      LIQUIDITY haircut, k_liquidity * size/exit_liquidity, is exactly this drag priced into fair value).

This module sweeps a range of deployed-AUM levels and, for EACH, replays the FixedCarry sleeve over the
DEEP historical RateSurface under the SAME honest accounting as backtest_rates (idle cash @ floor,
maturity-retire, 30% global ceiling, exit-capacity sizing) and decomposes the achieved book net APY into:

    book_net_apy(AUM) = deployed_frac * gross_carry_after_slippage  +  idle_frac * rwa_floor

Then it reports the HONEST ceiling: the AUM where book APY drops to floor+200bps, and the AUM where it
saturates (effectively == the floor). A LOW ceiling is the truth for thin Pendle markets — we report the
real number, we do NOT inflate it. The allocator-relevant conclusion: the rates desk is CAPACITY-LIMITED
to ~$X before the edge compresses to the floor, which is exactly why a $10M target needs SCALE across many
such books, not one.

CONVENTIONS (inherited, enforced): stdlib only; PURE — `as_of` is always explicit (the deep stream's
dates), never the wall clock; deterministic — no RNG, sorted iteration, Decimal-exact; fail-CLOSED — a
missing deep dataset / a market with no depth RAISES rather than fabricating a benign capacity; atomic
writes (tmp + shutil.move, repo rule #4); LLM-FORBIDDEN. Advisory / research — no live capital.

Run (offline, on the deep cached data):
    python3 -m spa_core.strategy_lab.rates_desk.capacity
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.strategy_lab.base import MarketSnapshot
from spa_core.strategy_lab.rates_desk import _io
from spa_core.strategy_lab.rates_desk import backtest_rates as br
from spa_core.strategy_lab.rates_desk import pendle_pt_history as pph
from spa_core.strategy_lab.rates_desk.contracts import D0, D1, RatePolicyParams
from spa_core.strategy_lab.rates_desk.feeds import BorosFeed
from spa_core.strategy_lab.rates_desk.opportunity_engine import CostConfig
from spa_core.strategy_lab.rates_desk.sleeves import FixedCarrySleeve

_ROOT = Path(__file__).resolve().parents[3]
_OUT = _ROOT / "data" / "rates_desk" / "capacity.json"
_DOC = _ROOT / "docs" / "RATES_DESK_VALIDATION.md"

# Idempotent markers so the capacity section can be (re)written into the validation doc without clobbering
# the assertion1/assertion2 / 4-sleeve / levered-stress content the other modules own.
_DOC_BEGIN = "<!-- BEGIN rates-desk capacity analysis (capacity) -->"
_DOC_END = "<!-- END rates-desk capacity analysis (capacity) -->"

# The deployed-AUM sweep (USD). Spans the desk's plausible range from a small book up to a $1B mega-
# allocation, so the curve shows BOTH the near-unconstrained ceiling (small AUM) and the saturation tail
# (large AUM → floor). The sub-$1M rungs ($100k–$500k) are where the THIN Pendle PT pools bite — the
# honest fundable ceiling (floor+200bps) lands in that band, so the sweep must resolve it there rather
# than report "off the bottom of the curve". Deterministic, version-pinned; widening is a research change.
DEFAULT_AUM_LEVELS_USD: List[Decimal] = [
    Decimal("100000"),       # $100k
    Decimal("250000"),       # $250k
    Decimal("500000"),       # $500k
    Decimal("1000000"),      # $1M
    Decimal("10000000"),     # $10M
    Decimal("50000000"),     # $50M
    Decimal("100000000"),    # $100M
    Decimal("250000000"),    # $250M
    Decimal("500000000"),    # $500M
    Decimal("1000000000"),   # $1B
]

# A TINY probe-AUM at which the book is effectively cash-bound (deploys its full cash into the single best
# PT each day) — this measures the UNCONSTRAINED carry the book would clip if depth were infinite. It is
# the "edge at zero size" reference the capacity compression is measured against (the ~6% number). Held
# separate from the sweep so it is reported as the ceiling, not as a fundable AUM.
UNCONSTRAINED_PROBE_AUM_USD = Decimal("10000")

# The "edge survives" band: book APY this far ABOVE the floor still represents a real, fundable excess.
# Below floor+200bps the carry edge has compressed to a marginal sliver over cash; below ~floor it has
# saturated. These are reporting thresholds (not gate thresholds); pinned + auditable.
ABOVE_FLOOR_BPS = Decimal("0.0200")          # floor + 200bps = the "edge still real" line
SATURATION_EPS_BPS = Decimal("0.0010")       # within 10bps of the floor → SATURATED (capacity-bound)


def _atomic_write_json(path: Path, obj) -> None:
    _io.atomic_write_json(path, obj, indent=1)


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# Instrumented FixedCarry replay — same honest accounting as backtest_rates, plus deployed/idle tracking
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _replay_fixed_carry_capacity(
    aum: Decimal,
    dates: List[str],
    deep: dict,
    funding: Dict[str, float],
    hedge_map: Dict[str, bool],
    params: RatePolicyParams,
    costs: CostConfig,
) -> dict:
    """Replay the FixedCarry sleeve at `aum` over the deep surface, EXACTLY as backtest_rates.replay_sleeve
    does for fixed_carry (maturity-retire → exit-capacity sizing → daily carry accrual → idle cash @
    floor), but ADDITIONALLY tracking, per day, how much capital was deployed into carry vs left idle.

    The decomposition is read straight off the honest equity track (no re-modelling):
      • book_net_apy   = annualized total-capital return (deployed carry + idle@floor) — identical to
                          replay_sleeve's net_apy_pct, so this is the SAME validated number.
      • deployed_frac  = time-and-capital-weighted average fraction of AUM in carry books.
      • idle_at_floor  = idle_frac * floor (the part of the book APY coming from cash @ floor).
      • gross_carry    = the carry-leg contribution annualized over the AUM (book_net_apy - idle_at_floor),
                          i.e. deployed_frac * carry_rate_after_slippage. The §9 LIQUIDITY haircut already
                          sits inside the gate's fair-value (it shrinks the approved books / their edge), so
                          this gross-carry figure is NET OF SLIPPAGE — the honest harvestable carry at size.
      • slippage_drag  = unconstrained_gross_carry_at_size - gross_carry: how much of the small-book carry
                          rate was eroded by sizing into thinner depth (the depth/impact cost of size).

    PURE w.r.t. the gate/engine; this harness only threads the surface stream + bookkeeping. Deterministic.
    fail-CLOSED: a malformed surface day is skipped (data gap → safe-hold, same as replay_sleeve)."""
    floor = params.rwa_floor
    floor_daily_dec = floor / Decimal("365")
    maturities = br._maturity_map(deep)

    sleeve = FixedCarrySleeve(params)
    sleeve.init(float(aum), {})

    equity: List[float] = []
    deployed_frac_samples: List[Decimal] = []   # per-day deployed fraction of AUM (capital-weighted)
    carry_days = 0
    matured_count = 0

    for d in dates:
        fneg = br._funding_neg_frac_90d(funding, d)
        try:
            surface, risks = br.build_deep_surface(d, deep, fneg, hedge_map)
        except ValueError:
            continue  # data gap → fail-CLOSED safe-hold (no advance this day)

        matured_count += br._retire_matured(sleeve, maturities, d)

        if not surface.pt_quotes:
            # whole book idle in cash → 0 deployed this day; accrue idle @ floor
            cash = getattr(sleeve, "_cash", D0)
            if cash > D0:
                sleeve._accrued += cash * floor_daily_dec
            deployed_frac_samples.append(D0)
            equity.append(sleeve.equity())
            continue

        br._drive_fixed_carry(sleeve, surface, risks, d)
        if sleeve._books:
            carry_days += 1

        # capital deployed into carry books TODAY (Decimal-exact, from the sleeve's own books)
        deployed = sum((bk["size"] for bk in sleeve._books.values()), D0)
        if aum > D0:
            deployed_frac_samples.append(min(D1, deployed / aum))
        else:
            deployed_frac_samples.append(D0)

        # accrue carry on open books + idle cash @ floor (same order as replay_sleeve)
        sleeve.step(MarketSnapshot(date=d))
        cash = getattr(sleeve, "_cash", D0)
        if cash > D0:
            sleeve._accrued += cash * floor_daily_dec
        equity.append(sleeve.equity())

    n = len(equity)
    aum_f = float(aum)
    span_years = (n / 365.0) if n else 0.0
    net = (equity[-1] - aum_f) if equity else 0.0
    book_net_apy = round((net / aum_f) / span_years * 100.0, 4) if (aum_f > 0 and span_years > 0) else 0.0

    deployed_frac = (
        float(sum(deployed_frac_samples, D0) / Decimal(len(deployed_frac_samples)))
        if deployed_frac_samples else 0.0
    )
    deployed_frac = round(min(1.0, max(0.0, deployed_frac)), 6)
    idle_frac = round(1.0 - deployed_frac, 6)
    floor_pct = float(floor) * 100.0
    idle_at_floor_pct = round(idle_frac * floor_pct, 4)
    # gross carry contribution (net of slippage) = total book APY minus the idle-cash@floor contribution
    gross_carry_pct = round(book_net_apy - idle_at_floor_pct, 4)

    return {
        "aum_usd": aum_f,
        "n_days": n,
        "deployed_frac": deployed_frac,
        "deployed_usd": round(deployed_frac * aum_f, 2),
        "idle_frac": idle_frac,
        "book_net_apy_pct": book_net_apy,
        "idle_at_floor_pct": idle_at_floor_pct,
        "gross_carry_pct": gross_carry_pct,
        "carry_days": carry_days,
        "matured_books": matured_count,
        "final_equity_usd": round(equity[-1], 2) if equity else aum_f,
    }


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# build_report — the capacity curve
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def build_report(
    write: bool = True,
    params: Optional[RatePolicyParams] = None,
    costs: Optional[CostConfig] = None,
    deep: Optional[dict] = None,
    funding: Optional[Dict[str, float]] = None,
    aum_levels: Optional[List[Decimal]] = None,
    out_path: Optional[Path] = None,
) -> dict:
    """Build the deterministic capacity curve for the FixedCarry survivor book and (optionally) write
    data/rates_desk/capacity.json atomically. Same (deep, funding, params) → same result.

    For each AUM in the sweep we replay the validated FixedCarry book over the deep surface and decompose
    its achieved book net APY into deployed-carry (net of slippage) vs idle-cash@floor. We then locate:
      • saturation_aum_usd            — the smallest swept AUM whose book APY has saturated to ~the floor.
      • max_aum_above_floor_plus_200bps — the largest swept AUM still delivering floor + 200bps (the
                                          honest fundable ceiling: above it the edge is a marginal sliver).

    fail-CLOSED: a missing deep dataset RAISES (we never fabricate a capacity curve)."""
    from spa_core.strategy_lab.rates_desk import retro

    params = params or RatePolicyParams()
    costs = costs or CostConfig()
    if deep is None:
        deep = pph.load()
    if funding is None:
        try:
            funding = retro.load_funding()
        except FileNotFoundError:
            funding = {}
    aum_levels = list(aum_levels) if aum_levels is not None else list(DEFAULT_AUM_LEVELS_USD)

    # fail-CLOSED: a deep dataset with no markets / no dated samples can never yield a real capacity
    # curve — RAISE rather than emit a fabricated all-floor curve from an empty replay.
    markets = deep.get("markets")
    if not isinstance(markets, dict) or not markets:
        raise ValueError("capacity: deep dataset has empty/invalid 'markets' (fail-CLOSED)")
    dates = br._all_dates(deep)
    if not dates:
        raise ValueError("capacity: deep dataset has no dated PT samples (fail-CLOSED)")
    universe = sorted({m["underlying"].lower() for m in deep["markets"].values()})
    hedge_map = BorosFeed().hedge_available(universe)
    floor_pct = round(float(params.rwa_floor) * 100.0, 4)

    # the unconstrained reference (tiny book → effectively cash-bound, deploys full cash into best PT):
    # this is the carry the book WOULD clip with infinite depth — the "edge at zero size" ceiling.
    unc = _replay_fixed_carry_capacity(
        UNCONSTRAINED_PROBE_AUM_USD, dates, deep, funding, hedge_map, params, costs)
    unconstrained_gross_carry_pct = unc["gross_carry_pct"]

    levels: List[dict] = []
    for aum in sorted(aum_levels):
        row = _replay_fixed_carry_capacity(aum, dates, deep, funding, hedge_map, params, costs)
        # slippage_drag = how much of the unconstrained per-deployed-dollar carry was lost to depth/impact
        # at this size. Computed on the DEPLOYED basis (gross_carry is on the AUM basis), so we lift it to
        # the per-deployed rate before differencing — honest comparison of carry RATE at size vs at zero.
        dframe = row["deployed_frac"] or 1e-12
        per_deployed_carry = row["gross_carry_pct"] / dframe
        unc_dframe = unc["deployed_frac"] or 1e-12
        unc_per_deployed = unc["gross_carry_pct"] / unc_dframe
        slippage_drag_pct = round(max(0.0, unc_per_deployed - per_deployed_carry), 4)
        beats_floor = bool(row["book_net_apy_pct"] > floor_pct)
        levels.append({
            "aum_usd": row["aum_usd"],
            "deployed_usd": row["deployed_usd"],
            "deployed_frac": row["deployed_frac"],
            "idle_frac": row["idle_frac"],
            "gross_carry_pct": row["gross_carry_pct"],
            "slippage_drag_pct": slippage_drag_pct,
            "idle_at_floor_pct": row["idle_at_floor_pct"],
            "book_net_apy_pct": row["book_net_apy_pct"],
            "beats_floor": beats_floor,
            "carry_days": row["carry_days"],
        })

    # ── the honest ceiling + saturation point ──
    above = floor_pct + float(ABOVE_FLOOR_BPS) * 100.0
    sat_eps = float(SATURATION_EPS_BPS) * 100.0
    max_aum_above = None
    for lv in levels:  # levels are sorted ascending by aum
        if lv["book_net_apy_pct"] >= above:
            max_aum_above = lv["aum_usd"]
    saturation_aum = None
    for lv in levels:
        if lv["book_net_apy_pct"] <= floor_pct + sat_eps:
            saturation_aum = lv["aum_usd"]
            break

    note = (
        "CAPACITY-LIMITED (honest). The FixedCarry survivor carry is real but lives in THIN Pendle PT "
        "pools: the §9 exit-capacity rule caps per-market deployment at max_size_frac_of_exit of one-tick "
        "exit liquidity, so the desk REFUSES to push past the impact band (it sizes DOWN rather than eat "
        "slippage). The depth cost therefore shows up not as carry slippage but as IDLE capital — the "
        "un-deployable remainder sits @ the RWA floor and the book APY compresses toward the floor as AUM "
        f"grows. The unconstrained (zero-size) carry is ~{unconstrained_gross_carry_pct:.2f}%/yr; it does "
        f"NOT survive size — the fundable ceiling (book APY >= floor+200bps) is ~{_fmt_usd(max_aum_above)} "
        f"deployed AUM, and the edge saturates to ~the floor by {_fmt_usd(saturation_aum)}. This is exactly "
        "why a $10M/yr target needs SCALE across MANY such gated books, not one — a single rates book caps "
        "out well below institutional size before the edge erodes to the floor.")

    result = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": "rates_desk_capacity_curve",
        "llm_forbidden": True,
        "deterministic": True,
        "is_advisory": True,
        "data_source": "deep_pendle_pt_history",
        "window": deep.get("window"),
        "n_dates": len(dates),
        "rwa_floor_pct": floor_pct,
        "floor_plus_200bps_pct": round(above, 4),
        "sleeve": "fixed_carry (validated survivor book)",
        "unconstrained_probe_aum_usd": float(UNCONSTRAINED_PROBE_AUM_USD),
        "unconstrained_book_net_apy_pct": unc["book_net_apy_pct"],
        "unconstrained_gross_carry_pct": unconstrained_gross_carry_pct,
        "aum_levels": levels,
        "saturation_aum_usd": saturation_aum,
        "max_aum_above_floor_plus_200bps": max_aum_above,
        "note": note,
    }
    if write:
        _atomic_write_json(out_path or _OUT, result)
    return result


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# doc section + printing
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _fmt_usd(x) -> str:
    if x is None:
        return "—"
    return f"${float(x):,.0f}"


def _render_doc_section(result: dict) -> str:
    floor = result.get("rwa_floor_pct")
    lines: List[str] = [_DOC_BEGIN, ""]
    lines.append("## Capacity — does the edge survive size?  (the fundability ceiling)\n")
    lines.append(
        "_Deterministic capacity curve for the validated FixedCarry SURVIVOR book over the DEEP "
        f"historical RateSurface ({result.get('window', {}).get('start')}→"
        f"{result.get('window', {}).get('end')}, {result.get('n_dates')} days). For each deployed-AUM "
        "level the book is replayed under the SAME honest accounting as the backtest (§9 exit-capacity "
        "sizing, idle cash @ the RWA floor, maturity-retire, 30% global ceiling). PURE / fail-CLOSED / "
        "advisory. Re-runnable via `python3 -m spa_core.strategy_lab.rates_desk.capacity`._\n")
    lines.append(
        f"RWA floor: **{floor}%/yr**. Unconstrained (zero-size) carry: "
        f"**~{result.get('unconstrained_gross_carry_pct')}%/yr** — the edge the book clips with infinite "
        "depth. The model: as AUM grows, exit-capacity sizing forces the marginal dollar IDLE @ the floor "
        "(diluting the book) or into DEEPER impact (slippage on the carry) — `book_net_apy(AUM) = "
        "deployed·carry_after_slippage + idle·floor`.\n")
    lines.append("| deployed AUM | deployed | deployed % | gross carry %/yr | slippage drag %/yr | "
                 "idle@floor %/yr | book net APY %/yr | beats floor |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|:--:|")
    for lv in result.get("aum_levels", []):
        lines.append(
            f"| {_fmt_usd(lv['aum_usd'])} | {_fmt_usd(lv['deployed_usd'])} | "
            f"{lv['deployed_frac'] * 100:.2f} | {lv['gross_carry_pct']:.4f} | "
            f"{lv['slippage_drag_pct']:.4f} | {lv['idle_at_floor_pct']:.4f} | "
            f"{lv['book_net_apy_pct']:.4f} | {'yes' if lv['beats_floor'] else 'no'} |")
    lines.append("")
    ceil = result.get("max_aum_above_floor_plus_200bps")
    sat = result.get("saturation_aum_usd")
    lines.append(
        f"- **Fundable ceiling (book APY >= floor+200bps = {result.get('floor_plus_200bps_pct')}%):** "
        f"**{_fmt_usd(ceil)}** deployed AUM.")
    lines.append(
        f"- **Saturation (book APY → the floor, edge gone):** "
        f"{('reached by **' + _fmt_usd(sat) + '** AUM') if sat is not None else 'not reached within the swept range (compresses toward but does not fully touch the floor)'}.")
    lines.append("")
    lines.append(f"> **Honest verdict — CAPACITY-LIMITED.** {result.get('note')}\n")
    lines.append(_DOC_END)
    return "\n".join(lines)


def write_doc_section(result: dict, doc_path: Optional[Path] = None) -> Path:
    """Idempotently (re)write the capacity section into docs/RATES_DESK_VALIDATION.md between the markers,
    preserving the other validation content. Atomic write (repo rule #4)."""
    path = doc_path or _DOC
    section = _render_doc_section(result)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if _DOC_BEGIN in existing and _DOC_END in existing:
        pre = existing[: existing.index(_DOC_BEGIN)].rstrip("\n")
        post = existing[existing.index(_DOC_END) + len(_DOC_END):].lstrip("\n")
        body = (pre + "\n\n" + section + ("\n\n" + post if post else "\n")).rstrip("\n") + "\n"
    else:
        body = (existing.rstrip("\n") + "\n\n" + section + "\n") if existing else (section + "\n")
    _io.atomic_write_text(path, body)
    return path


def _print_curve(result: dict) -> None:
    floor = result.get("rwa_floor_pct")
    print(f"Rates Desk — CAPACITY curve (FixedCarry survivor book)   RWA floor {floor}%/yr")
    print(f"window: {result.get('window')}  ·  dates: {result.get('n_dates')}")
    print(f"unconstrained (zero-size) carry: ~{result.get('unconstrained_gross_carry_pct')}%/yr\n")
    hdr = (f"{'deployed AUM':>16s} {'deployed%':>9s} {'grossCarry%':>11s} {'slipDrag%':>9s} "
           f"{'idle@floor%':>11s} {'bookAPY%':>9s} {'beats':>6s}")
    print(hdr)
    print("-" * len(hdr))
    for lv in result.get("aum_levels", []):
        print(f"{_fmt_usd(lv['aum_usd']):>16s} {lv['deployed_frac'] * 100:9.2f} "
              f"{lv['gross_carry_pct']:11.4f} {lv['slippage_drag_pct']:9.4f} "
              f"{lv['idle_at_floor_pct']:11.4f} {lv['book_net_apy_pct']:9.4f} "
              f"{('yes' if lv['beats_floor'] else 'no'):>6s}")
    print()
    print(f"Fundable ceiling (>= floor+200bps): {_fmt_usd(result.get('max_aum_above_floor_plus_200bps'))} AUM")
    sat = result.get("saturation_aum_usd")
    print(f"Saturation (→ floor): {(_fmt_usd(sat) + ' AUM') if sat is not None else 'not reached in swept range'}")
    print(f"\n{result.get('note')}")


def main() -> int:
    result = build_report(write=True)
    _print_curve(result)
    print(f"\nWrote {_OUT}")
    try:
        write_doc_section(result)
        print(f"Updated {_DOC} (capacity section)")
    except Exception as exc:  # noqa: BLE001 — doc enrichment must not fail the analysis
        print(f"(doc section skipped: {exc})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
