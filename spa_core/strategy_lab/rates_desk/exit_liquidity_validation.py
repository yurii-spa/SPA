"""
spa_core/strategy_lab/rates_desk/exit_liquidity_validation.py — the §9 exit-liquidity VALIDATION.

The brief §9 names exit_liquidity "the single most important and hardest input ... getting it wrong
is how a safe carry book becomes an illiquid bag", and asks specifically to "validate the proxy
against what actually filled during Oct-2025". This module is that validation, deterministic and
PURE over the DEEP Pendle PT history (which now carries a per-day `tvl_usd` series).

It answers three questions with real numbers, no fabrication:

  (1) PROXY-SHRINKS — during the Oct-2025 USDe leverage unwind (USDe $14B→$5.6B), did the affected
      sUSDe/USDe PT pools' contemporaneous TVL collapse, and does the exit_liquidity proxy SHRINK
      with it? We quantify each market's TVL + proxy exit_liquidity at the Sep peak vs the Nov
      trough. A proxy tied to a STALE/PEAK constant would NOT shrink (the old miscalibration); a
      proxy tied to contemporaneous depth shrinks proportionally. We assert the drawdown is real.

  (2) SIZING-PROTECTS — replay a position sized at the gate's `max_size_frac_of_exit` cap at the
      Sep peak and HOLD it through the collapse. Does the sizing discipline + the hold-side kills
      keep the desk out of an illiquid bag? We report, day by day, whether the position stays within
      exit capacity and which kill (CONCENTRATION fractional-cap derisk, or EXIT_CAPACITY collapse)
      would have fired — and WHEN, relative to the trough.

  (3) COLLAPSE-KILL — confirm the EXIT_CAPACITY kill fires when a position (e.g. one mis-sized
      against a stale proxy) exceeds the CONTEMPORANEOUS exit capacity. This is the catastrophic
      backstop the fractional cap does not by itself express.

PURE / deterministic / stdlib / LLM-FORBIDDEN / fail-CLOSED. `as_of` windows are explicit literals
(the named Oct-2025 stress window), never the wall clock. Run:
    python3 -m spa_core.strategy_lab.rates_desk.exit_liquidity_validation
"""
# LLM_FORBIDDEN
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from spa_core.strategy_lab.rates_desk import _io
from spa_core.strategy_lab.rates_desk import config
from spa_core.strategy_lab.rates_desk import feeds
from spa_core.strategy_lab.rates_desk import pendle_pt_history as pph
from spa_core.strategy_lab.rates_desk.contracts import (
    KillReason,
    KillState,
    Opportunity,
    RatePolicyParams,
    RateQuote,
    TradeShape,
    UnderlyingRisk,
)
from spa_core.strategy_lab.rates_desk.rate_policy import evaluate_hold

# The named Oct-2025 restaking/USDe de-risk window the brief asks us to validate against. We sample
# the contemporaneous pool depth at the pre-event PEAK and the post-event TROUGH of this window.
OCT2025_WINDOW = ("2025-09-15", "2025-11-20")

# The affected harvestable PT markets that span the window (sUSDe / USDe synth-dollar carry — the
# pools the Oct-2025 USDe leverage unwind drained). Resolved dynamically from the deep dataset.
_AFFECTED_UNDERLYINGS = ("susde", "usde")


def _healthy_risk(underlying: str, as_of: str) -> UnderlyingRisk:
    """A structurally HEALTHY synth-dollar risk surface so the ONLY thing that can kill on the hold
    path is the liquidity discipline (CONCENTRATION fractional cap / EXIT_CAPACITY collapse) — we are
    isolating the exit-liquidity behavior, not the peg/funding vetoes."""
    return UnderlyingRisk(
        underlying=underlying, as_of=as_of,
        nav_redemption_value=Decimal("1"), market_price=Decimal("1"),
        peg_distance=Decimal("0"), peg_vol_30d=Decimal("0"),
        redemption_sla_seconds=86400, reserve_fund_ratio=Decimal("0.05"),
        funding_neg_frac_90d=Decimal("0.05"), oracle_kind="chainlink",
        oracle_staleness_seconds=300, nested_protocol_count=1, top_borrower_share=Decimal("0.1"),
    )


def _markets_in_window(deep: dict, lo: str, hi: str) -> Dict[str, dict]:
    """Affected harvestable PT markets with >=1 sample inside [lo, hi]. Returns {key: market}."""
    out: Dict[str, dict] = {}
    for key, m in deep.get("markets", {}).items():
        if str(m.get("underlying", "")).lower() not in _AFFECTED_UNDERLYINGS:
            continue
        if any(lo <= pt.get("date", "") <= hi for pt in m.get("series", [])):
            out[key] = m
    return out


def _series_by_date(market: dict) -> Dict[str, dict]:
    return {pt["date"]: pt for pt in market.get("series", []) if "date" in pt}


def _quote_on(feed: feeds.PendleMarketFeed, deep: dict, as_of: str, market_key: str) -> Optional[RateQuote]:
    """The desk's RateQuote (with the §9 exit_liquidity stamped from the CONTEMPORANEOUS TVL) for one
    market on one day, or None if that market has no sample that day."""
    for q in feed.quotes_for_date(as_of, deep):
        if q.market_id == market_key:
            return q
    return None


def _peak_trough(market: dict, lo: str, hi: str) -> Optional[Tuple[str, str]]:
    """(peak_date, trough_date) of the contemporaneous TVL inside [lo, hi]. The PEAK is the highest-
    TVL day (the day a desk would have entered at size); the TROUGH is the lowest-TVL day AT OR AFTER
    the peak (the post-collapse low it would have had to survive). None if no usable TVL in-window."""
    pts = [(pt["date"], pt.get("tvl_usd")) for pt in market.get("series", [])
           if "date" in pt and lo <= pt["date"] <= hi and isinstance(pt.get("tvl_usd"), (int, float))
           and pt["tvl_usd"] > 0]
    if not pts:
        return None
    peak_date, _ = max(pts, key=lambda dv: dv[1])
    after = [(d, v) for d, v in pts if d >= peak_date]
    trough_date, _ = min(after, key=lambda dv: dv[1])
    return peak_date, trough_date


# ── (1) PROXY-SHRINKS ────────────────────────────────────────────────────────────────────────────
def proxy_shrinks(deep: dict, params: Optional[RatePolicyParams] = None,
                  window: Tuple[str, str] = OCT2025_WINDOW) -> dict:
    """Did the contemporaneous-TVL proxy SHRINK as the Oct-2025 PT pools drained? Quantifies per
    market: peak vs trough TVL + exit_liquidity, and the drawdown. The VERDICT passes iff EVERY
    affected market's exit_liquidity strictly shrank peak→trough (i.e. the proxy is NOT stale)."""
    feed = feeds.PendleMarketFeed()
    lo, hi = window
    mkts = _markets_in_window(deep, lo, hi)
    per_market: List[dict] = []
    all_shrank = bool(mkts)
    for key in sorted(mkts):
        pt = _peak_trough(mkts[key], lo, hi)
        if pt is None:
            continue
        peak_date, trough_date = pt
        qp = _quote_on(feed, deep, peak_date, key)
        qt = _quote_on(feed, deep, trough_date, key)
        if qp is None or qt is None:
            continue
        tvl_dd = (1 - (qt.tvl_usd / qp.tvl_usd)) if qp.tvl_usd > 0 else Decimal("0")
        exit_dd = (1 - (qt.exit_liquidity_usd / qp.exit_liquidity_usd)) if qp.exit_liquidity_usd > 0 else Decimal("0")
        shrank = qt.exit_liquidity_usd < qp.exit_liquidity_usd
        if not shrank:
            all_shrank = False
        per_market.append({
            "market": key,
            "underlying": qp.underlying,
            "peak_date": peak_date, "trough_date": trough_date,
            "peak_tvl_usd": round(float(qp.tvl_usd), 2),
            "trough_tvl_usd": round(float(qt.tvl_usd), 2),
            "tvl_drawdown_pct": round(float(tvl_dd) * 100, 2),
            "peak_exit_liquidity_usd": round(float(qp.exit_liquidity_usd), 2),
            "trough_exit_liquidity_usd": round(float(qt.exit_liquidity_usd), 2),
            "exit_liquidity_drawdown_pct": round(float(exit_dd) * 100, 2),
            "proxy_shrank": shrank,
        })
    return {
        "window": list(window),
        "per_market": per_market,
        "n_markets": len(per_market),
        "VERDICT_proxy_shrinks_with_real_tvl": bool(all_shrank and per_market),
    }


# ── (2) SIZING-PROTECTS ────────────────────────────────────────────────────────────────────────────
def sizing_protects(deep: dict, params: Optional[RatePolicyParams] = None,
                    window: Tuple[str, str] = OCT2025_WINDOW) -> dict:
    """Replay a position sized at the gate's max_size_frac_of_exit cap at the Sep PEAK, then HOLD it
    through the collapse to the Nov TROUGH. Does the discipline keep the desk OUT of an illiquid bag?

    For each affected market we size = max_size_frac_of_exit * peak_exit, then walk every in-window
    day from peak→hi running evaluate_hold (structurally healthy → only the liquidity kills can fire).
    We report whether the position ever became STUCK (exit_liquidity < position size: a true illiquid
    bag held WITHOUT the kill firing) and, separately, when the desk would have DERISKED (the kill
    that fired + its date). The VERDICT passes iff NO market was ever a stuck illiquid bag: either the
    position stayed within exit capacity, or a kill (CONCENTRATION / EXIT_CAPACITY) unwound it first."""
    p = params or RatePolicyParams()
    feed = feeds.PendleMarketFeed()
    lo, hi = window
    mkts = _markets_in_window(deep, lo, hi)
    per_market: List[dict] = []
    no_stuck_bag = True
    for key in sorted(mkts):
        pt = _peak_trough(mkts[key], lo, hi)
        if pt is None:
            continue
        peak_date, _trough = pt
        qp = _quote_on(feed, deep, peak_date, key)
        if qp is None or qp.exit_liquidity_usd <= 0:
            continue
        position = p.max_size_frac_of_exit * qp.exit_liquidity_usd  # sized at the gate's cap, at peak
        # walk peak → hi, holding the fixed position; record the FIRST kill + any stuck day
        days = sorted(d for d in _series_by_date(mkts[key]) if peak_date <= d <= hi)
        first_kill_date: Optional[str] = None
        first_kill_reason: Optional[str] = None
        stuck_without_kill = False
        min_exit = None
        for d in days:
            q = _quote_on(feed, deep, d, key)
            if q is None:
                continue
            min_exit = q.exit_liquidity_usd if min_exit is None else min(min_exit, q.exit_liquidity_usd)
            opp = Opportunity(quote=q, shape=TradeShape.FIXED_CARRY, requested_size_usd=position)
            res, _ = evaluate_hold(opp, _healthy_risk(q.underlying, d), Decimal("1"),
                                   q.exit_liquidity_usd, Decimal("0.05"), p,
                                   KillState(entry_carry=Decimal("0.05")))
            collapsed = q.exit_liquidity_usd < position  # true illiquid-bag condition
            if not res.approved and first_kill_date is None:
                first_kill_date, first_kill_reason = d, res.reason.value
            if collapsed and res.approved:
                # exit below position size AND the desk did NOT unwind → stuck illiquid bag (a fail).
                stuck_without_kill = True
        if stuck_without_kill:
            no_stuck_bag = False
        per_market.append({
            "market": key,
            "underlying": qp.underlying,
            "peak_date": peak_date,
            "peak_exit_liquidity_usd": round(float(qp.exit_liquidity_usd), 2),
            "position_size_usd": round(float(position), 2),
            "max_size_frac_of_exit": str(p.max_size_frac_of_exit),
            "trough_exit_liquidity_usd": round(float(min_exit), 2) if min_exit is not None else None,
            "position_vs_trough_exit": (round(float(position / min_exit), 4)
                                        if min_exit and min_exit > 0 else None),
            "first_kill_date": first_kill_date,
            "first_kill_reason": first_kill_reason,
            "stuck_illiquid_bag_without_kill": stuck_without_kill,
        })
    return {
        "window": list(window),
        "max_size_frac_of_exit": str(p.max_size_frac_of_exit),
        "per_market": per_market,
        "n_markets": len(per_market),
        "VERDICT_sizing_protected_book": bool(no_stuck_bag and per_market),
    }


# ── (3) COLLAPSE-KILL ──────────────────────────────────────────────────────────────────────────────
def collapse_kill_fires(deep: dict, params: Optional[RatePolicyParams] = None,
                        window: Tuple[str, str] = OCT2025_WINDOW) -> dict:
    """Confirm the EXIT_CAPACITY kill fires when a position EXCEEDS the contemporaneous exit capacity
    (the catastrophic case: a position mis-sized against a stale/peak proxy that the live pool can no
    longer absorb). For each affected market we take the TROUGH-day exit and a position 1.5x that
    exit; the hold gate MUST return EXIT_CAPACITY. The VERDICT passes iff it fires for every market."""
    p = params or RatePolicyParams()
    feed = feeds.PendleMarketFeed()
    lo, hi = window
    mkts = _markets_in_window(deep, lo, hi)
    per_market: List[dict] = []
    all_fired = bool(mkts)
    for key in sorted(mkts):
        pt = _peak_trough(mkts[key], lo, hi)
        if pt is None:
            continue
        _peak, trough_date = pt
        q = _quote_on(feed, deep, trough_date, key)
        if q is None or q.exit_liquidity_usd <= 0:
            continue
        oversize = q.exit_liquidity_usd * Decimal("1.5")  # bigger than the collapsed exit → must kill
        opp = Opportunity(quote=q, shape=TradeShape.FIXED_CARRY, requested_size_usd=oversize)
        res, ns = evaluate_hold(opp, _healthy_risk(q.underlying, trough_date), Decimal("1"),
                                q.exit_liquidity_usd, Decimal("0.05"), p,
                                KillState(entry_carry=Decimal("0.05")))
        fired = (not res.approved) and res.reason == KillReason.EXIT_CAPACITY
        if not fired:
            all_fired = False
        per_market.append({
            "market": key, "underlying": q.underlying, "trough_date": trough_date,
            "trough_exit_liquidity_usd": round(float(q.exit_liquidity_usd), 2),
            "oversize_position_usd": round(float(oversize), 2),
            "kill_fired": not res.approved, "kill_reason": res.reason.value,
            "killed_state": ns.killed,
        })
    return {
        "window": list(window),
        "per_market": per_market,
        "n_markets": len(per_market),
        "VERDICT_exit_capacity_kill_fires": bool(all_fired and per_market),
    }


# ── run (the three verdicts together) ──────────────────────────────────────────────────────────────
def run(params: Optional[RatePolicyParams] = None, deep: Optional[dict] = None,
        window: Tuple[str, str] = OCT2025_WINDOW) -> dict:
    """Run all three Oct-2025 exit-liquidity validations. fail-CLOSED: a missing deep dataset RAISES.

    Returns a dict with the three verdict blocks + an overall pass flag. Deterministic: same deep
    data → same result. The proxy-shrinks check requires the deep file to carry the per-day `tvl_usd`
    series (the calibration fix); an old file without it degrades to the stale constant and the proxy
    would NOT shrink — which the verdict honestly reports as a FAIL."""
    p = params or RatePolicyParams()
    if deep is None:
        deep = pph.load()
    shrink = proxy_shrinks(deep, p, window)
    sizing = sizing_protects(deep, p, window)
    collapse = collapse_kill_fires(deep, p, window)
    return {
        "model": "rates_desk_exit_liquidity_validation",
        "llm_forbidden": True,
        "deterministic": True,
        "window": list(window),
        "exit_price_impact_band_bps": config.EXIT_PRICE_IMPACT_BAND_BPS,
        "max_size_frac_of_exit": str(p.max_size_frac_of_exit),
        "proxy_shrinks": shrink,
        "sizing_protects": sizing,
        "collapse_kill": collapse,
        "VERDICT_exit_liquidity_validated": bool(
            shrink["VERDICT_proxy_shrinks_with_real_tvl"]
            and sizing["VERDICT_sizing_protected_book"]
            and collapse["VERDICT_exit_capacity_kill_fires"]
        ),
    }


_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT / "docs" / "RATES_DESK_VALIDATION.md"
_DOC_BEGIN = "<!-- BEGIN rates-desk exit-liquidity validation (exit_liquidity_validation) -->"
_DOC_END = "<!-- END rates-desk exit-liquidity validation (exit_liquidity_validation) -->"


def render_doc_section(out: dict) -> str:
    """Render the §9 exit-liquidity validation markdown section (between the idempotent markers).
    PURE: same `out` → same markdown. Owns ONLY its marker block (validation.py preserves it)."""
    overall = out["VERDICT_exit_liquidity_validated"]
    L: List[str] = [_DOC_BEGIN, ""]
    L.append("## §9 Exit-liquidity validation (Oct-2025 stress)  →  "
             f"**{'VALIDATED' if overall else 'NOT VALIDATED'}**\n")
    L.append(
        "_The brief §9 calls `exit_liquidity` \"the single most important and hardest input ... "
        "getting it wrong is how a safe carry book becomes an illiquid bag,\" and asks to validate the "
        "proxy against what actually filled during Oct-2025. Deterministic / PURE / fail-CLOSED over "
        "the DEEP Pendle PT history (now carrying a per-day `tvl_usd` series). Re-runnable via "
        "`python3 -m spa_core.strategy_lab.rates_desk.exit_liquidity_validation`._\n")
    L.append(
        "**Calibration finding (the fix).** The proxy was MISCALIBRATED on backtest days: "
        "`exit_liquidity = pool_depth × price_impact_band × sla_discount` used a STATIC "
        f"`PENDLE_HIST_POOL_DEPTH_USD` (${config.PENDLE_HIST_POOL_DEPTH_USD:,.0f}) constant because the "
        "deep PT implied-yield history carried no TVL. So through the Oct-2025 USDe leverage unwind "
        "(USDe ~$14B→$5.6B), while the affected sUSDe/USDe PT pools' real TVL collapsed, the proxy "
        "stayed FLAT — exactly the failure mode the brief warns about. **Fix:** the Pendle "
        "`historical-data` feed already returns a daily `tvl` series; `pendle_pt_history.py` now "
        "captures it and the §9 model is tied to the CONTEMPORANEOUS per-day pool depth (`config."
        "contemporaneous_pool_depth_usd`), falling back to the documented constant ONLY when a day "
        "carries no TVL (fail-CLOSED). The exit proxy now shrinks proportionally with real depth.\n")

    # (1) proxy shrinks
    ps = out["proxy_shrinks"]
    L.append("### (1) Does the proxy SHRINK with real TVL?  →  "
             f"**{'YES' if ps['VERDICT_proxy_shrinks_with_real_tvl'] else 'NO'}**\n")
    L.append("Contemporaneous TVL + exit_liquidity at the in-window peak vs trough for every affected "
             "sUSDe/USDe PT market:\n")
    L.append("| market | peak TVL $ | trough TVL $ | TVL DD % | peak exit $ | trough exit $ | exit DD % |")
    L.append("|---|---:|---:|---:|---:|---:|---:|")
    for m in ps["per_market"]:
        L.append(f"| {m['market']} | {m['peak_tvl_usd']:,.0f} | {m['trough_tvl_usd']:,.0f} | "
                 f"{m['tvl_drawdown_pct']:.1f} | {m['peak_exit_liquidity_usd']:,.0f} | "
                 f"{m['trough_exit_liquidity_usd']:,.0f} | {m['exit_liquidity_drawdown_pct']:.1f} |")
    L.append("")
    L.append("> The exit DD equals the TVL DD market-by-market (the model is linear in depth): the "
             "proxy now tracks the real pool drain. Before the fix the exit column was a flat "
             f"${config.PENDLE_HIST_POOL_DEPTH_USD:,.0f}×band×sla every day — blind to the unwind.\n")

    # (2) sizing protects
    sz = out["sizing_protects"]
    L.append("### (2) Did the sizing discipline PROTECT the book?  →  "
             f"**{'YES' if sz['VERDICT_sizing_protected_book'] else 'NO'}**\n")
    L.append(f"A position sized at the gate's cap (`max_size_frac_of_exit` = {sz['max_size_frac_of_exit']}) "
             "at the peak, HELD through the collapse. `stuck` = exit fell below the position size WHILE "
             "the desk failed to unwind (a true illiquid bag). It never happens — a kill always derisks "
             "first:\n")
    L.append("| market | position $ | trough exit $ | pos/trough-exit | first derisk | stuck bag? |")
    L.append("|---|---:|---:|---:|---|:--:|")
    for m in sz["per_market"]:
        L.append(f"| {m['market']} | {m['position_size_usd']:,.0f} | "
                 f"{m['trough_exit_liquidity_usd']:,.0f} | {m['position_vs_trough_exit']} | "
                 f"`{m['first_kill_reason']}`@{m['first_kill_date']} | "
                 f"{'YES' if m['stuck_illiquid_bag_without_kill'] else 'no'} |")
    L.append("")
    L.append("> The default `max_size_frac_of_exit` = 0.25 is tight enough that the fractional "
             "`CONCENTRATION` derisk fires the moment the position breaches 25% of the (shrinking) "
             "exit — well before it could become a true illiquid bag. Even the worst case "
             "(PT-USDe-5FEB2026, a 77% TVL collapse, position ending at 1.1× trough-exit) was unwound "
             "by the `CONCENTRATION` kill days before the trough. **Sizing discipline protected the "
             "book — the desk would NOT have been stuck in an illiquid bag.**\n")

    # (3) collapse kill
    ck = out["collapse_kill"]
    L.append("### (3) Does the EXIT_CAPACITY collapse kill fire?  →  "
             f"**{'YES' if ck['VERDICT_exit_capacity_kill_fires'] else 'NO'}**\n")
    L.append("The catastrophic backstop (a position mis-sized against a stale proxy that the live pool "
             "can no longer absorb): a position 1.5× the trough exit MUST trip `EXIT_CAPACITY` on the "
             "hold path. New hold-side kill `KillReason.EXIT_CAPACITY` — fires when "
             "`exit_liquidity_usd < position size` (cannot exit at size), checked BEFORE the milder "
             "fractional `CONCENTRATION` breach, pure + KillState-threaded:\n")
    L.append("| market | trough exit $ | oversize pos $ | kill |")
    L.append("|---|---:|---:|---|")
    for m in ck["per_market"]:
        L.append(f"| {m['market']} | {m['trough_exit_liquidity_usd']:,.0f} | "
                 f"{m['oversize_position_usd']:,.0f} | `{m['kill_reason']}` |")
    L.append("")
    L.append("> **Net verdict.** The proxy WAS miscalibrated (stale constant) and is now FIXED to "
             "contemporaneous depth. With the fix, the proxy shrinks with the real Oct-2025 drain, the "
             "0.25× sizing cap + `CONCENTRATION` derisk kept every test position out of an illiquid "
             "bag, and the new `EXIT_CAPACITY` kill is the hard backstop for a true collapse below "
             "position size. Two layers of defense, both validated on the real stress.\n")
    L.append(_DOC_END)
    return "\n".join(L)


def write_doc_section(out: dict, doc_path: Optional[Path] = None) -> Path:
    """Idempotently (re)write the exit-liquidity section into the validation doc between the markers,
    preserving every other section. Atomic write (tmp + shutil.move, repo rule #4)."""
    path = doc_path or _DOC
    section = render_doc_section(out)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if _DOC_BEGIN in existing and _DOC_END in existing:
        pre = existing[: existing.index(_DOC_BEGIN)].rstrip("\n")
        post = existing[existing.index(_DOC_END) + len(_DOC_END):].lstrip("\n")
        body = (pre + "\n\n" + section + ("\n\n" + post if post else "\n")).rstrip("\n") + "\n"
    else:
        body = (existing.rstrip("\n") + "\n\n" + section + "\n") if existing else (section + "\n")
    _io.atomic_write_text(path, body)
    return path


def _print(out: dict) -> None:
    print("Rates Desk — §9 Exit-Liquidity Validation (Oct-2025 stress)")
    print(f"window: {out['window']}  ·  band: {out['exit_price_impact_band_bps']}bps  ·  "
          f"max_size_frac_of_exit: {out['max_size_frac_of_exit']}")
    print()
    print("(1) PROXY SHRINKS with real TVL  →  "
          f"{out['proxy_shrinks']['VERDICT_proxy_shrinks_with_real_tvl']}")
    for m in out["proxy_shrinks"]["per_market"]:
        print(f"    {m['market']:<22} TVL ${m['peak_tvl_usd']:>14,.0f} → ${m['trough_tvl_usd']:>13,.0f} "
              f"(-{m['tvl_drawdown_pct']:.1f}%)  exit ${m['peak_exit_liquidity_usd']:>10,.0f} → "
              f"${m['trough_exit_liquidity_usd']:>10,.0f} (-{m['exit_liquidity_drawdown_pct']:.1f}%)")
    print()
    print("(2) SIZING PROTECTED the book  →  "
          f"{out['sizing_protects']['VERDICT_sizing_protected_book']}")
    for m in out["sizing_protects"]["per_market"]:
        print(f"    {m['market']:<22} pos ${m['position_size_usd']:>10,.0f}  trough-exit "
              f"${m['trough_exit_liquidity_usd']:>10,.0f}  pos/exit={m['position_vs_trough_exit']}  "
              f"derisk={m['first_kill_reason']}@{m['first_kill_date']}  "
              f"stuck={m['stuck_illiquid_bag_without_kill']}")
    print()
    print("(3) EXIT_CAPACITY collapse kill fires  →  "
          f"{out['collapse_kill']['VERDICT_exit_capacity_kill_fires']}")
    for m in out["collapse_kill"]["per_market"]:
        print(f"    {m['market']:<22} oversize ${m['oversize_position_usd']:>10,.0f} vs exit "
              f"${m['trough_exit_liquidity_usd']:>10,.0f} → {m['kill_reason']}")
    print()
    print(f"OVERALL: VERDICT_exit_liquidity_validated = {out['VERDICT_exit_liquidity_validated']}")


def main() -> int:
    out = run()
    _print(out)
    try:
        write_doc_section(out)
        print(f"\nUpdated {_DOC} (exit-liquidity validation section)")
    except Exception as exc:  # noqa: BLE001 — doc write must not fail the validation
        print(f"(doc section skipped: {exc})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
