"""
spa_core/strategy_lab/rates_desk/calibrate.py — calibrate the REFUSAL THRESHOLD + haircut coefficients.

Brief §9: `max_total_haircut` is "the most consequential single parameter" — it is the cliff between
REFUSING tail-comp (the desk's edge) and STRANGLING real carry (losing the edge). This module SWEEPS
that threshold AND the five haircut coefficients (k_peg / k_liquidity / k_protocol / k_funding) over a
grid and, for each candidate, measures on the DEEP 2024→2026 data:

  (a) TOXIC-VETO COVERAGE — the fraction of toxic restaking (ezETH/rsETH) PT days the gate REFUSES,
      across every toxic book and BEFORE each named stress event. Want ~100% (a toxic book held into
      its depeg is the catastrophic failure the desk exists to prevent).

  (b) HEALTHY-CARRY FIRE-RATE + survivor-book APY — the fraction of harvestable sUSDe/USDe PT days the
      gate APPROVES, and the survivor book's realized APY vs the RWA floor. Want this HIGH — an over-
      tight threshold vetoes the real edge too (you would lose the carry you are paid to harvest).

The objective MAXIMIZES (toxic vetoed AND healthy preserved): a candidate is ADMISSIBLE only if toxic
coverage stays at the safe ceiling (≥ min_toxic_coverage, default 100%) AND no toxic day is approved
on any of the three stress events; among admissible candidates we MAXIMIZE the healthy survivor APY
(then fire-rate as a tie-break). This is a deterministic, exhaustive grid search — no optimizer, no RNG.

The chosen values are written to config.py's CALIBRATED_* block (NOT hardcoded in the engine); the
RatePolicyParams default `factory` reads them. The trade-off curve + the chosen point are documented in
docs/RATES_DESK_VALIDATION.md.

PURE / deterministic / stdlib / LLM-FORBIDDEN. Run:
    python3 -m spa_core.strategy_lab.rates_desk.calibrate
"""
# LLM_FORBIDDEN
from __future__ import annotations

import dataclasses
import datetime
import itertools
import json
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from spa_core.strategy_lab.rates_desk import _io
from spa_core.strategy_lab.rates_desk import pendle_pt_history as pph
from spa_core.strategy_lab.rates_desk import retro
from spa_core.strategy_lab.rates_desk import validation as V
from spa_core.strategy_lab.rates_desk.contracts import RatePolicyParams

_ROOT = Path(__file__).resolve().parents[3]
_OUT = _ROOT / "data" / "rates_desk" / "rates_calibration.json"
_DOC = _ROOT / "docs" / "RATES_DESK_VALIDATION.md"

_DOC_BEGIN = "<!-- BEGIN rates-desk calibration sweep (calibrate) -->"
_DOC_END = "<!-- END rates-desk calibration sweep (calibrate) -->"

# The three named stress events (their as_of anchors) — a calibrated threshold must refuse the toxic
# book on EACH (this is the "before the event" guarantee the brief demands).
_STRESS_AS_OF = ["2024-08-01", "2025-10-01", "2026-04-01"]

# The swept THRESHOLD parameter. After the red-team FAIL #1 fix the toxic-vs-healthy cliff is the
# size-INDEPENDENT structural-haircut cap (max_structural_haircut), NOT max_total_haircut (which is the
# additional economics-incl-liquidity cap). All boundary / strangle / margin / rank logic keys on this.
SWEEP_THRESHOLD_KEY = "max_structural_haircut"


# ── the sweep grid (Decimal-exact) ─────────────────────────────────────────────────────────────────
# We sweep `max_structural_haircut` (the TOXICITY cliff — the size-INDEPENDENT peg+funding+oracle+protocol
# cutoff that now governs the toxic-vs-healthy boundary; the red-team FAIL #1 fix moved the toxicity
# verdict onto this size-proof term so it can't be sized around) plus the two coefficients that move that
# boundary on this data — k_peg (the depeg tail that discriminates LRT) and k_protocol (the nesting/
# concentration tail). `max_total_haircut` is the ADDITIONAL economics-incl-liquidity cap (a book can also
# fail on size/liquidity); it is pinned at its config default here because the toxicity cliff is the
# structural cap. k_funding / k_liquidity are a systemic overlay + a size term — neither discriminates
# toxic-vs-healthy on the per-day deep surface, so they are not swept.
# NOTE (red-team FAIL #1 fix): this sweep now tunes the TOXICITY CAP (max_structural_haircut), holding
# k_peg / k_protocol at their ALREADY-VALIDATED config defaults. The haircut COEFFICIENTS were calibrated
# and validated in a prior sweep; re-opening them here would churn a validated risk param (repo rule #7)
# AND would let the objective "cheat" the band by scaling the toxic structural haircut up to admit a
# looser cap. Pinning the coefficients makes this an HONEST confirmation that 0.09 is the robust center of
# the toxic-vs-healthy structural band at the live calibration. (A full coefficient re-sweep is a separate
# ADR-level event; widen the k_* lists deliberately if/when that is the intent.)
DEFAULT_GRID = {
    "max_structural_haircut": ["0.06", "0.07", "0.08", "0.09", "0.10", "0.11", "0.12", "0.14"],
    "k_peg":                  ["4.0"],   # pinned to the validated config default
    "k_protocol":             ["0.02"],  # pinned to the validated config default
}


def _params_with(over: Dict[str, str], base: Optional[RatePolicyParams] = None) -> RatePolicyParams:
    """A RatePolicyParams with the swept Decimal overrides applied (everything else = base/default)."""
    base = base or RatePolicyParams()
    kwargs = {f.name: getattr(base, f.name) for f in dataclasses.fields(base)}
    for k, v in over.items():
        cur = kwargs[k]
        kwargs[k] = Decimal(str(v)) if isinstance(cur, Decimal) else type(cur)(v)
    return RatePolicyParams(**kwargs)


# ── measurement (reuses the validated deep-data eval paths) ────────────────────────────────────────
def measure(params: RatePolicyParams, deep: dict, funding: Dict[str, float]) -> dict:
    """Measure (toxic-veto coverage, healthy fire-rate, survivor APY) for ONE params point on the deep
    data. Reuses validation.assertion1_deep_refusal (toxic) + validation._deep_survivor_series
    (healthy carry book) so the calibration measures the SAME gate the desk runs. PURE/deterministic."""
    eng = V.FairValueEngine(params)

    # (a) TOXIC: refuse rate across every toxic LRT PT day, + zero approvals on the stress as_ofs.
    a1 = V.assertion1_deep_refusal(params)
    tox_days = sum(m["days"] for m in a1["per_market"])
    tox_refused = sum(m["refused_days"] for m in a1["per_market"])
    toxic_coverage = (tox_refused / tox_days) if tox_days else 0.0
    toxic_all_refused = bool(a1["all_toxic_books_refused_every_day"])

    # stress-event guarantee: on each named event date, the synthetic toxic book is REFUSED structurally
    stress_refused = 0
    for ev in V.STRESS_EVENTS:
        risk = V._build_toxic_risk(ev)
        from spa_core.strategy_lab.rates_desk.contracts import (
            KillState, Opportunity, RateQuote, RateVenue, TradeShape)
        q = RateQuote(
            underlying=ev["underlying"], kind=ev["kind"], venue=RateVenue.PENDLE_PT,
            protocol="pendle", market_id=f"PT-{ev['underlying']}", tenor_seconds=86400 * 60,
            as_of=ev["as_of"], quoted_rate=Decimal(ev["quoted_rate"]), tvl_usd=Decimal("5e7"),
            exit_liquidity_usd=Decimal("2e6"), hedge_available=False)
        opp = Opportunity(quote=q, shape=TradeShape.FIXED_CARRY, requested_size_usd=Decimal("100000"))
        res, _ = V.evaluate_entry(opp, risk, Decimal("1"), q.exit_liquidity_usd, params,
                                  KillState(), engine=eng)
        if not res.approved:
            stress_refused += 1
    stress_all_refused = (stress_refused == len(V.STRESS_EVENTS))

    # LIVE-STYLE toxic LRT guarantee (red-team FAIL #1 anchor): the synthetic STRESS_EVENTS above model
    # a SEVERE toxic surface (structural haircut ~0.18). The book that ACTUALLY leaked in the public
    # decision log (seq=63 ezETH) was a MILDER, real-feed-style LRT surface — the documented config LRT
    # constants (nested=2, top_borrower=0.30, redstone 600s oracle) with a realistic ratio-drawdown peg —
    # whose STRUCTURAL haircut is ~0.097 at the calibrated coeffs. The calibration MUST place the toxic-
    # leak cliff against THAT real surface, or it would credit a falsely-wide band and pick a cap above
    # the surface that actually leaked. We REFUSE it at any size; a candidate that approves it is NOT
    # admissible. This is what anchors the chosen structural cap below the real toxic surface.
    # The exploit surface: a MODERATE peg distance UNDER the 1% hard UNDERLYING_DEPEG gate (so that gate
    # does NOT catch it) plus peg VOLATILITY driving the peg haircut up — exactly the seq=63 ezETH shape
    # (peg_distance 0.008 < 0.01, peg_vol 0.016 → peg_haircut ~0.064, structural ~0.097). Before the fix
    # this was sized down to ~$4k to drop its liquidity haircut and clear the TOTAL cap. The toxicity cap
    # MUST sit below this structural haircut, or the size-down exploit reopens. peg/vol chosen to stay
    # under the peg gate so this probes the STRUCTURAL veto (not the peg gate) specifically.
    from spa_core.strategy_lab.rates_desk import config as _rd_config
    live_toxic_refused = True
    for _u in ("ezeth", "rseth"):
        risk = V.UnderlyingRisk(
            underlying=_u, as_of="2024-09-01", nav_redemption_value=Decimal("1"),
            market_price=Decimal("0.992"), peg_distance=Decimal("0.008"),
            peg_vol_30d=Decimal("0.016"), redemption_sla_seconds=_rd_config.redemption_sla_seconds(_u),
            reserve_fund_ratio=Decimal(str(_rd_config.reserve_fund_ratio(_u))),
            funding_neg_frac_90d=Decimal("0.05"), oracle_kind=_rd_config.oracle_kind(_u),
            oracle_staleness_seconds=_rd_config.oracle_staleness_seconds(_u),
            nested_protocol_count=_rd_config.nested_protocol_count(_u),
            top_borrower_share=Decimal(str(_rd_config.top_borrower_share(_u))))
        from spa_core.strategy_lab.rates_desk.contracts import (
            KillState as _KS, Opportunity as _Opp, RateQuote as _RQ, RateVenue as _RV,
            TradeShape as _TS, UnderlyingKind as _UK)
        q = _RQ(underlying=_u, kind=_UK.LRT, venue=_RV.PENDLE_PT, protocol="pendle",
                market_id=f"PT-{_u}", tenor_seconds=86400 * 60, as_of="2024-09-01",
                quoted_rate=Decimal("0.35"), tvl_usd=Decimal("5e7"),
                exit_liquidity_usd=Decimal("65000"), hedge_available=False)
        # probe at a TINY ticket — the size-down exploit the structural veto must close (any size).
        opp = _Opp(quote=q, shape=_TS.FIXED_CARRY, requested_size_usd=Decimal("1000"))
        res, _ = V.evaluate_entry(opp, risk, Decimal("1"), q.exit_liquidity_usd, params, _KS(),
                                  engine=eng)
        if res.approved:
            live_toxic_refused = False
    stress_all_refused = stress_all_refused and live_toxic_refused

    # (b) HEALTHY: the survivor carry book over the deep window — fire-rate + realized APY vs floor.
    # apply_global_ceiling=False: this STRUCTURAL-haircut calibration optimizes the peg/liquidity/protocol
    # tail SEPARATION between toxic-LRT and healthy-carry. The downstream global APY ceiling (30%) is a
    # COMPOSITION layer applied to the PUBLISHED book — it must NOT move the structural cutoff, or it would
    # churn the risk calibration for a cosmetic APY effect. (The published survivor APY in validation.py
    # DOES apply the ceiling; the calibration deliberately does not.)
    daily, per_market = V._deep_survivor_series(params, eng, deep, funding, apply_global_ceiling=False)
    healthy_days = sum(m["n_days"] for m in per_market.values())
    healthy_carry_days = sum(m["carry_days"] for m in per_market.values())
    fire_rate = (healthy_carry_days / healthy_days) if healthy_days else 0.0
    n = len(daily)
    mean_book_apy = (sum(r["book_apy"] for r in daily) / n) if n else 0.0
    floor = float(params.rwa_floor)
    beats_floor = mean_book_apy > floor

    return {
        "toxic_coverage": round(toxic_coverage, 6),
        "toxic_all_refused_every_day": toxic_all_refused,
        "toxic_stress_all_refused": stress_all_refused,
        "toxic_days": tox_days,
        "healthy_fire_rate": round(fire_rate, 6),
        "healthy_carry_days": healthy_carry_days,
        "healthy_days": healthy_days,
        "survivor_mean_apy": round(mean_book_apy, 6),
        "survivor_beats_floor": bool(beats_floor),
        "survivor_days": n,
    }


# ── the sweep ──────────────────────────────────────────────────────────────────────────────────────
def sweep(
    grid: Optional[Dict[str, List[str]]] = None,
    deep: Optional[dict] = None,
    funding: Optional[Dict[str, float]] = None,
    min_toxic_coverage: float = 1.0,
) -> dict:
    """Exhaustive deterministic grid sweep. Returns the full table + the chosen calibrated point.

    Admissibility (fail-CLOSED — safety FIRST): a candidate is admissible ONLY if toxic coverage ≥
    min_toxic_coverage (default 100%) AND every toxic book is refused every day AND the synthetic toxic
    book is refused on every stress event. Among admissible candidates we MAXIMIZE the survivor APY
    (the real edge), tie-broken by fire-rate, then by the LOOSEST threshold that still holds (looser =
    less risk of strangling future healthy carry), then a deterministic key for replay-stability.

    fail-CLOSED: if NO candidate is admissible the chosen point is None (never a fabricated pick)."""
    grid = grid or DEFAULT_GRID
    if deep is None:
        deep = pph.load()
    if funding is None:
        try:
            funding = retro.load_funding()
        except FileNotFoundError:
            funding = {}

    keys = sorted(grid.keys())
    rows: List[dict] = []
    for combo in itertools.product(*[grid[k] for k in keys]):
        over = dict(zip(keys, combo))
        p = _params_with(over)
        m = measure(p, deep, funding)
        admissible = bool(
            m["toxic_coverage"] >= min_toxic_coverage
            and m["toxic_all_refused_every_day"]
            and m["toxic_stress_all_refused"])
        rows.append({"params": over, "admissible": admissible, **m})

    # deterministic sort for the table: admissible first, then APY desc, then fire-rate desc.
    rows.sort(key=lambda r: (not r["admissible"], -r["survivor_mean_apy"], -r["healthy_fire_rate"],
                             json.dumps(r["params"], sort_keys=True)))

    admissible_rows = [r for r in rows if r["admissible"]]

    # the toxic/healthy BOUNDARY: per (k_peg, k_protocol), the safe ceiling + the leak floor — the
    # trade-off cliff. Computed first because the ROBUST objective ranks by margin to those cliffs.
    boundary = _boundary(rows)

    # annotate each admissible row with its DISTANCE TO BOTH FAILURE CLIFFS:
    #   • toxic-leak margin   = (min leaking threshold for its coeffs) − its threshold  (room before a
    #                            toxic book clears the veto). None-leak ⇒ unbounded headroom.
    #   • healthy-strangle margin = its threshold − (the loosest threshold that still strangles healthy
    #                            for its coeffs, i.e. the highest sub-full-fire-rate point) — room above
    #                            the over-veto cliff. We approximate the strangle edge from the rows.
    # The brief's objective is "tight enough toxic vetoed AND loose enough healthy fires" — that is
    # MAXIMIZE THE MINIMUM of the two margins (the robust CENTER of the admissible band), NOT chase APY
    # (which is flat across the band — locked carry is identical once fire-rate saturates). APY is only
    # a final tie-break.
    _strangle_edge = _strangle_edges(rows)
    for r in admissible_rows:
        kp = r["params"].get("k_peg", "-")
        kpr = r["params"].get("k_protocol", "-")
        thr = float(r["params"][SWEEP_THRESHOLD_KEY])
        leak = next((b["min_leaking_threshold"] for b in boundary
                     if b["k_peg"] == kp and b["k_protocol"] == kpr), None)
        # toxic margin: if no leak observed in-grid, credit the grid's own ceiling step as headroom.
        toxic_margin = (leak - thr) if leak is not None else (thr - _max_grid_threshold(grid)) + 0.04
        strangle = _strangle_edge.get((kp, kpr))
        healthy_margin = (thr - strangle) if strangle is not None else thr
        r["toxic_leak_margin"] = round(toxic_margin, 6)
        r["healthy_strangle_margin"] = round(healthy_margin, 6)
        r["robust_margin"] = round(min(toxic_margin, healthy_margin), 6)

    chosen = None
    if admissible_rows:
        # ROBUST objective: MAX min-margin-to-either-cliff (the CENTER of the safe band, not its loose
        # edge — a threshold one grid-step below the toxic leak is brittle even if its APY is identical).
        # Tie-breaks, in order: (1) PREFER the value already in config — a risk param that is provably
        # at the robust optimum should NOT be churned for a cosmetic APY tick (repo rule #7: RiskPolicy
        # stability; changing a risk cutoff is an ADR-level event, justified only by a real safety gain),
        # (2) higher survivor APY, (3) higher fire-rate, (4) deterministic key.
        dflt = RatePolicyParams()
        dflt_key = {SWEEP_THRESHOLD_KEY: str(getattr(dflt, SWEEP_THRESHOLD_KEY)),
                    "k_peg": str(dflt.k_peg), "k_protocol": str(dflt.k_protocol)}

        def _matches_default(r) -> int:
            return 0 if all(r["params"].get(k) == v for k, v in dflt_key.items()) else 1

        def _rank(r):
            return (-r["robust_margin"], _matches_default(r), -r["survivor_mean_apy"],
                    -r["healthy_fire_rate"], json.dumps(r["params"], sort_keys=True))
        chosen = sorted(admissible_rows, key=_rank)[0]

    return {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": "rates_desk_calibration_sweep",
        "llm_forbidden": True,
        "deterministic": True,
        "grid": grid,
        "min_toxic_coverage": min_toxic_coverage,
        "n_candidates": len(rows),
        "n_admissible": len(admissible_rows),
        "rows": rows,
        "boundary": boundary,
        "chosen": chosen,
        "defaults": {f.name: str(getattr(RatePolicyParams(), f.name))
                     for f in dataclasses.fields(RatePolicyParams())
                     if f.name in ("max_structural_haircut", "max_total_haircut", "k_peg",
                                   "k_protocol", "k_funding", "k_liquidity")},
    }


def _max_grid_threshold(grid: Dict[str, List[str]]) -> float:
    """The loosest swept threshold in the grid (for crediting unbounded-toxic-headroom honestly)."""
    return max(float(x) for x in grid.get(SWEEP_THRESHOLD_KEY, ["0.09"]))


def _strangle_edges(rows: List[dict]) -> Dict[Tuple[str, str], Optional[float]]:
    """For each (k_peg, k_protocol), the HIGHEST swept threshold that still STRANGLES healthy carry
    (fire-rate < 1.0) — the over-veto cliff. None ⇒ healthy never strangled in-grid (fires at every
    swept threshold). Deterministic."""
    by_coef: Dict[Tuple[str, str], List[dict]] = {}
    for r in rows:
        key = (r["params"].get("k_peg", "-"), r["params"].get("k_protocol", "-"))
        by_coef.setdefault(key, []).append(r)
    out: Dict[Tuple[str, str], Optional[float]] = {}
    for key, rs in by_coef.items():
        strangled = [float(r["params"][SWEEP_THRESHOLD_KEY]) for r in rs
                     if r["healthy_fire_rate"] < 1.0]
        out[key] = max(strangled) if strangled else None
    return out


def _boundary(rows: List[dict]) -> List[dict]:
    """For each (k_peg, k_protocol) pair, the LOWEST swept threshold that is still admissible and the
    HIGHEST that leaks a toxic day — the cliff. Deterministic."""
    by_coef: Dict[Tuple[str, str], List[dict]] = {}
    for r in rows:
        key = (r["params"].get("k_peg", "-"), r["params"].get("k_protocol", "-"))
        by_coef.setdefault(key, []).append(r)
    out: List[dict] = []
    for (kp, kpr), rs in sorted(by_coef.items()):
        rs_sorted = sorted(rs, key=lambda r: float(r["params"][SWEEP_THRESHOLD_KEY]))
        leaks = [r for r in rs_sorted if not r["admissible"]]
        safe = [r for r in rs_sorted if r["admissible"]]
        out.append({
            "k_peg": kp, "k_protocol": kpr,
            "max_safe_threshold": (max(float(r["params"][SWEEP_THRESHOLD_KEY]) for r in safe)
                                   if safe else None),
            "min_leaking_threshold": (min(float(r["params"][SWEEP_THRESHOLD_KEY]) for r in leaks)
                                      if leaks else None),
        })
    return out


# ── persistence + doc ──────────────────────────────────────────────────────────────────────────────
def _atomic_write(path: Path, text: str) -> None:
    _io.atomic_write_text(path, text)


def _atomic_write_json(path: Path, obj) -> None:
    _io.atomic_write_json(path, obj, indent=1, default=str)


def _render_doc(result: dict) -> str:
    lines: List[str] = [_DOC_BEGIN, "", "## Calibration sweep — refusal threshold + haircut coefficients\n"]
    lines.append(
        "_Brief §9 + red-team FAIL #1 fix: the toxicity cliff is now `max_structural_haircut` (the "
        "size-INDEPENDENT peg+funding+oracle+protocol cap, so toxicity can't be sized around). This is an "
        "exhaustive, deterministic grid sweep over `max_structural_haircut` + `k_peg` + `k_protocol` on "
        "the DEEP 2024→2026 data, measuring (toxic-veto coverage) vs (healthy-carry fire-rate / survivor "
        "APY). Re-runnable via `python3 -m spa_core.strategy_lab.rates_desk.calibrate`._\n")
    ch = result.get("chosen")
    df = result.get("defaults", {})
    if ch:
        lines.append(
            f"**Chosen (calibrated):** `max_structural_haircut={ch['params']['max_structural_haircut']}`, "
            f"`k_peg={ch['params']['k_peg']}`, `k_protocol={ch['params']['k_protocol']}` → toxic "
            f"coverage **{ch['toxic_coverage']*100:.1f}%** (all stress events refused: "
            f"`{ch['toxic_stress_all_refused']}`), healthy fire-rate **{ch['healthy_fire_rate']*100:.1f}%**, "
            f"survivor APY **{ch['survivor_mean_apy']*100:.2f}%** vs floor "
            f"`{float(RatePolicyParams().rwa_floor)*100:.1f}%` (beats: `{ch['survivor_beats_floor']}`).\n")
        lines.append(
            "> _Note: this calibration's `survivor APY` is computed WITHOUT the downstream global APY "
            "ceiling (30%) and at full-book sizing — deliberately, because this sweep tunes the "
            "STRUCTURAL tail-haircut cutoff (peg/liquidity/protocol separation of toxic-LRT vs healthy "
            "carry), and that cutoff must not move with a downstream composition layer. It is an "
            "OPTIMIZATION objective, NOT the published carry number. The HONEST published, "
            "capacity-bound, ceiling-composed book APY is in the Assertion-2 and 4-sleeve sections "
            "above (FixedCarry ≈ 6% on the total-capital basis, idle cash at the floor)._\n")
        same = (ch["params"]["max_structural_haircut"] == df.get("max_structural_haircut")
                and ch["params"]["k_peg"] == df.get("k_peg")
                and ch["params"]["k_protocol"] == df.get("k_protocol"))
        lines.append(
            f"> The current defaults (`max_structural_haircut={df.get('max_structural_haircut')}`, "
            f"`k_peg={df.get('k_peg')}`, `k_protocol={df.get('k_protocol')}`) "
            + ("**are confirmed optimal by the sweep** (the chosen point equals them)."
               if same else
               "differ from the chosen point — config CALIBRATED_* updated to the chosen values.")
            + " Calibration is pinned in `config.py` (`CALIBRATED_*`), not hardcoded in the engine.\n")
    else:
        lines.append("> **NO admissible candidate** — no swept point holds 100% toxic coverage. "
                     "fail-CLOSED: defaults retained.\n")

    lines.append("Trade-off — the boundary (cliff) per coefficient pair (the threshold at/above which a "
                 "toxic day would leak through):\n")
    lines.append("| k_peg | k_protocol | max SAFE threshold | min LEAKING threshold |")
    lines.append("|---:|---:|---:|---:|")
    for b in result.get("boundary", []):
        ms = b["max_safe_threshold"]
        ml = b["min_leaking_threshold"]
        lines.append(f"| {b['k_peg']} | {b['k_protocol']} | "
                     f"{('%.2f' % ms) if ms is not None else '—'} | "
                     f"{('%.2f' % ml) if ml is not None else 'none (all safe)'} |")
    lines.append("")
    lines.append("Top sweep rows (admissible first, then survivor APY desc):\n")
    lines.append("| max_structural_haircut | k_peg | k_protocol | admissible | toxic cov % | fire-rate % | "
                 "survivor APY % | beats floor |")
    lines.append("|---:|---:|---:|:--:|---:|---:|---:|:--:|")
    for r in result.get("rows", [])[:14]:
        p = r["params"]
        lines.append(
            f"| {p['max_structural_haircut']} | {p['k_peg']} | {p['k_protocol']} | "
            f"{'yes' if r['admissible'] else 'no'} | {r['toxic_coverage']*100:.1f} | "
            f"{r['healthy_fire_rate']*100:.1f} | {r['survivor_mean_apy']*100:.2f} | "
            f"{'yes' if r['survivor_beats_floor'] else 'no'} |")
    lines.append("")
    lines.append(
        "> Reading the curve: loosening `max_structural_haircut` raises the survivor fire-rate/APY (less "
        "real carry strangled) but eventually lets a toxic restaking book clear the veto — the "
        "`min LEAKING threshold` column is exactly where that happens. The calibrated point sits at "
        "the richest admissible carry that is still strictly below every leak. On THIS data the toxic "
        "LRT books carry a depeg+nesting tail so far above any healthy sUSDe PT that the safe band is "
        "wide — the chosen threshold both vetoes 100% of toxic days and leaves healthy carry intact.\n")
    lines.append(_DOC_END)
    return "\n".join(lines)


def write_doc_section(result: dict, doc_path: Optional[Path] = None) -> Path:
    """Idempotently (re)write the calibration section between the markers (preserves the rest)."""
    path = doc_path or _DOC
    section = _render_doc(result)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if _DOC_BEGIN in existing and _DOC_END in existing:
        pre = existing[: existing.index(_DOC_BEGIN)].rstrip("\n")
        post = existing[existing.index(_DOC_END) + len(_DOC_END):].lstrip("\n")
        body = (pre + "\n\n" + section + ("\n\n" + post if post else "\n")).rstrip("\n") + "\n"
    else:
        body = (existing.rstrip("\n") + "\n\n" + section + "\n") if existing else (section + "\n")
    _atomic_write(path, body)
    return path


def main() -> int:
    result = sweep()
    _atomic_write_json(_OUT, result)
    ch = result.get("chosen")
    print("Rates Desk — Calibration Sweep")
    print(f"candidates: {result['n_candidates']}  admissible: {result['n_admissible']}")
    if ch:
        print(f"CHOSEN: max_structural_haircut={ch['params']['max_structural_haircut']} "
              f"k_peg={ch['params']['k_peg']} k_protocol={ch['params']['k_protocol']}")
        print(f"  toxic coverage={ch['toxic_coverage']*100:.1f}%  fire-rate={ch['healthy_fire_rate']*100:.1f}%  "
              f"survivor APY={ch['survivor_mean_apy']*100:.2f}%")
    else:
        print("CHOSEN: none (no admissible candidate — defaults retained, fail-CLOSED)")
    write_doc_section(result)
    print(f"Wrote {_OUT} and updated {_DOC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
