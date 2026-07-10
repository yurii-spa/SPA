"""
spa_core/strategy_lab/rates_desk/backtest_rates.py — the rates-desk SLEEVE BACKTEST REPLAY.

Replay all FOUR rates-desk sleeves (FixedCarry / LeveredCarry / BasisHedge / RateMatrix) over the
DEEP historical RateSurface (2024→2026) assembled per as_of from the deep Pendle PT implied-yield
history + the documented lending/risk feed constants. For each sleeve this is a PURE function of the
(surface stream, KillState) → orders → equity/track. Same data → same result (deterministic).

Output: data/rates_desk/rates_backtest.json — per sleeve:
    {net_apy, max_drawdown, deflated_sharpe, beats_floor, kills, refusals_count, ...}

WHY a separate replay (not strategy_lab/backtest.py): the lab harness ticks MarketSnapshots (ETH /
funding price bars); the rates desk ticks a RateSurface (PT/lending/boros quotes + per-underlying
risk). This module is the rates-desk analogue of run_backtest() — one command runs every sleeve over
the same historical surface stream and produces a risk-adjusted, deflated-Sharpe comparison vs the
RWA floor, mirroring validation.assertion2 but for the FULL sleeve set (not just FixedCarry).

CONVENTIONS (inherited, enforced): stdlib only; PURE — `as_of` is always explicit, never the wall
clock; deterministic — no RNG, sorted iteration; fail-CLOSED — a malformed surface day RAISES rather
than fabricating a benign bar; atomic writes (tmp + shutil.move, repo rule #4); LLM-FORBIDDEN.

The 4 sleeves do NOT all express on the same legs:
  • FixedCarry  — buys PT (the harvestable stable-synth carry leg) and holds to maturity.
  • LeveredCarry— borrows a stable, buys PT (needs a LENDING borrow leg too).
  • BasisHedge  — PT vs a Boros forward-funding short — UNAVAILABLE: BorosFeed.HEDGE_ENABLED is False
                  (no keyless forward-funding venue), so the BASIS_HEDGE shape never exists. The
                  replay reports it HONESTLY as zero opportunities / blocked-no-hedge, NEVER fabricated.
  • RateMatrix  — argmax-net-rate venue per underlying (PT vs supply vs Boros), rotating on hysteresis.

Run (offline, on the deep cached data):
    python3 -m spa_core.strategy_lab.rates_desk.backtest_rates
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from spa_core.strategy_lab.base import MarketSnapshot
from spa_core.backtesting.tier1.deflated_sharpe import (
    annualize_sharpe,
    deflated_sharpe_ratio,
    min_track_record_length,
    moments,
    probabilistic_sharpe_ratio,
    sharpe_per_period,
)
from spa_core.strategy_lab.rates_desk import _io
from spa_core.strategy_lab.rates_desk import config
from spa_core.strategy_lab.rates_desk import pendle_pt_history as pph
from spa_core.strategy_lab.rates_desk.contracts import (
    D0,
    KillReason,
    RatePolicyParams,
    RateQuote,
    RateVenue,
    UnderlyingKind,
    UnderlyingRisk,
)
from spa_core.strategy_lab.rates_desk.feeds import BorosFeed, exit_liquidity_usd
from spa_core.strategy_lab.rates_desk.opportunity_engine import CostConfig, RateSurface
from spa_core.strategy_lab.rates_desk.sleeves import (
    BasisHedgeSleeve,
    FixedCarrySleeve,
    LeveredCarrySleeve,
    RateMatrixSleeve,
)

_ROOT = Path(__file__).resolve().parents[3]
_OUT = _ROOT / "data" / "rates_desk" / "rates_backtest.json"
_DOC = _ROOT / "docs" / "RATES_DESK_VALIDATION.md"

# Idempotent markers so the 4-sleeve section can be (re)written into the validation doc without
# clobbering the assertion1/assertion2 content that validation.py owns.
_DOC_BEGIN = "<!-- BEGIN rates-desk 4-sleeve validation (backtest_rates) -->"
_DOC_END = "<!-- END rates-desk 4-sleeve validation (backtest_rates) -->"

_KIND_BY_VALUE = {k.value: k for k in UnderlyingKind}

# Capital each sleeve is replayed at (equal-footing, like strategy_lab/backtest.py).
DEFAULT_CAPITAL = Decimal("100000")

# A synthetic LENDING borrow leg for the levered/rate-matrix shapes. The deep PT history carries no
# money-market quotes, so for the backtest we model the borrow leg with a documented, conservative,
# CONSTANT borrow APR per the levered-carry thesis (USDC borrow ~the t-bill rate; an honest, auditable
# input — the live feed supplies the real rate intraday). It is well BELOW typical PT implied so the
# levered spread is real, and its ltv/util are set to documented constants. This is a documented PROXY,
# flagged in the output; it never fabricates an edge the gate cannot independently clear on fair value.
BORROW_APR = Decimal("0.045")          # USDC borrow APR proxy (~t-bill); below PT implied → real carry
BORROW_LTV = Decimal("0.86")           # PT-collateral max LTV proxy (Morpho PT markets ~86%)
BORROW_UTILIZATION = Decimal("0.70")   # documented utilization proxy (well below the 0.97 kill)
BORROW_DEPTH_USD = Decimal("20000000") # money-market depth proxy (deep USDC markets)

# ── BACKTEST-ONLY hedge-rate proxy flag (architect T4) ─────────────────────────────────────────────
# HEDGE_IS_BACKTEST_PROXY gates a RESEARCH-ONLY simulation of the BasisHedge sleeve (shape C) over the
# deep window, using the historical 5-venue median funding (funding_feed) as the hedge-leg rate proxy.
# It answers ONE question honestly: "would the isolated basis have been a real edge?" — WITHOUT enabling
# live execution.
#
# CRITICAL SAFETY INVARIANT (architect): this flag NEVER touches the live path. It is read ONLY inside
# this backtest module. `feeds.BorosFeed.HEDGE_ENABLED` stays False; `BorosFeed().hedge_available(...)`
# stays all-False; the live gate still refuses any BasisHedge live entry (no Boros venue → shape never
# forms). When the proxy is ON, the basis_hedge result block STILL carries blocked_no_hedge=True (so
# promotion_rates keeps it STAGE_BLOCKED_NO_HEDGE) and the proxy APY is reported in a SEPARATE
# `backtest_proxy` sub-block, clearly labelled BACKTEST-ONLY · live-BLOCKED. Default False → live path
# and every existing result are byte-identical (the proxy adds nothing unless explicitly turned on).
HEDGE_IS_BACKTEST_PROXY = False

# Funding is a per-8h rate (the median of the 5-venue feed). The hedge leg PAYS funding continuously, so
# the annualized hedge cost = funding_8h * 3 settlements/day * 365 days/yr. This is the documented PROXY
# the BACKTEST uses for the Boros pay-variable leg (no executable Boros venue exists live).
FUNDING_8H_PERIODS_PER_YEAR = Decimal("3") * Decimal("365")  # 1095

# Global RiskPolicy APY ceiling (spa_core/risk/policy.py: max_apy_for_new_position = 30%). The rates
# desk composes UNDER the global RiskPolicy (compose_under_global_policy): a rate-gate approval is
# necessary but NOT sufficient — the global policy still has to approve, and it REFUSES any position
# with APY > 30% as "risk too high". The deep PT history carries synth-PT implied yields up to ~196%
# (2024 funding boom); a 99%-APY PT locked for months is risk premium, NOT a safe held-to-maturity
# carry, and the global policy would never let it open. Surfacing those into the book was a core driver
# of the inflated net APY. We honour the global ceiling here by dropping over-ceiling PT quotes before
# the sleeve ever sees them (exactly what global_approved=False would do, made explicit per-quote).
GLOBAL_MAX_APY = Decimal("0.30")


# ── atomic JSON write (repo rule #4) ──────────────────────────────────────────────────────────────
def _atomic_write_json(path: Path, obj) -> None:
    _io.atomic_write_json(path, obj, indent=1)


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# Historical RateSurface assembly from the deep dataset (ONE function, per as_of)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _risk_for(underlying: str, kind: UnderlyingKind, as_of: str,
              funding_neg_frac_90d: Decimal) -> UnderlyingRisk:
    """The per-underlying risk surface for a historical day, from the documented config constants +
    the trailing funding-neg fraction. STABLE_SYNTH/STABLE_RWA model par peg (the synth tail is carried
    by the funding/structural haircuts); LST/LRT model a documented grinding-drift peg so the toxic LRT
    books carry the depeg/nesting tail the gate refuses. PURE — as_of explicit, fail-CLOSED constants."""
    u = underlying.lower()
    if kind in (UnderlyingKind.STABLE_SYNTH, UnderlyingKind.STABLE_RWA):
        return UnderlyingRisk(
            underlying=u, as_of=as_of,
            nav_redemption_value=Decimal("1"), market_price=Decimal("1"),
            peg_distance=D0, peg_vol_30d=D0,
            redemption_sla_seconds=config.redemption_sla_seconds(u),
            reserve_fund_ratio=Decimal(str(config.reserve_fund_ratio(u))),
            funding_neg_frac_90d=funding_neg_frac_90d,
            oracle_kind=config.oracle_kind(u), oracle_staleness_seconds=config.oracle_staleness_seconds(u),
            nested_protocol_count=config.nested_protocol_count(u),
            top_borrower_share=Decimal(str(config.top_borrower_share(u))),
        )
    # LST / LRT — documented grinding-drift peg surface (the restaking-tail the gate refuses on LRT).
    # The LRT peg is modelled at the LOWER edge of the real toxic-LRT drawdown band (config cites
    # "LRT ratio drawdowns reach 5-6%"); 0.025 (2.5%) is a deliberately conservative floor that still
    # drives the peg haircut to its cap so a toxic restaking book is refused on STRUCTURAL grounds
    # (peg/nesting tail) at ANY position size — NOT as a side-effect of an over-sized liquidity haircut.
    # (A milder 0.6% modelled peg previously leaked through once the desk sized to exit-capacity instead
    # of throwing the full cash book at the gate — that was a sizing artifact masquerading as the veto;
    # the structural refusal must not depend on over-sizing. Real ezETH/rsETH always carry >= this.)
    peg = Decimal("0.025") if kind == UnderlyingKind.LRT else Decimal("0.001")
    return UnderlyingRisk(
        underlying=u, as_of=as_of,
        nav_redemption_value=Decimal("1"), market_price=Decimal("1") - peg,
        peg_distance=peg, peg_vol_30d=Decimal("0.02") if kind == UnderlyingKind.LRT else Decimal("0.005"),
        redemption_sla_seconds=config.redemption_sla_seconds(u),
        reserve_fund_ratio=Decimal(str(config.reserve_fund_ratio(u))),
        funding_neg_frac_90d=funding_neg_frac_90d,
        oracle_kind=config.oracle_kind(u), oracle_staleness_seconds=config.oracle_staleness_seconds(u),
        nested_protocol_count=config.nested_protocol_count(u),
        top_borrower_share=Decimal(str(config.top_borrower_share(u))),
    )


def _maturity_ts(maturity: str) -> int:
    d = datetime.date.fromisoformat(maturity[:10])
    return int(datetime.datetime(d.year, d.month, d.day, tzinfo=datetime.timezone.utc).timestamp())


def _as_of_ts(as_of: str) -> int:
    d = datetime.date.fromisoformat(as_of[:10])
    return int(datetime.datetime(d.year, d.month, d.day, tzinfo=datetime.timezone.utc).timestamp())


def _funding_8h_as_of(funding: Dict[str, float], date: str) -> Optional[Decimal]:
    """The latest median 8h funding observation on-or-before `date` (Decimal, via str — no float→Decimal
    binary noise). None if the funding series has no day <= `date` (fail-CLOSED: no proxy rate that day).
    PURE: explicit date, sorted iteration."""
    dates = sorted(d for d in funding if d <= date)
    if not dates:
        return None
    return Decimal(str(funding[dates[-1]]))


def _proxy_hedge_apy(funding: Dict[str, float], date: str) -> Optional[Decimal]:
    """BACKTEST-ONLY hedge-leg rate proxy: annualize the 8h median funding to a per-year APY-equivalent
    (funding_8h * 3 * 365). This is the cost the basis trade PAYS on the hedge leg. None when no funding
    observation exists on-or-before `date`. NEVER used on the live path."""
    f8 = _funding_8h_as_of(funding, date)
    if f8 is None:
        return None
    return f8 * FUNDING_8H_PERIODS_PER_YEAR


def build_deep_surface(
    as_of: str,
    deep: dict,
    funding_neg_frac_90d: Decimal,
    hedge_map: Dict[str, bool],
    *,
    include_lending: bool = True,
    proxy_hedge_apy: Optional[Decimal] = None,
) -> Tuple[RateSurface, Dict[str, UnderlyingRisk]]:
    """Assemble the historical RateSurface + risk map for one `as_of` from the deep PT dataset.

    For each underlying we keep the LONGEST-tenor PT market that has an implied-yield sample on `as_of`
    AND has not yet matured (the desk holds the freshest, furthest-out fixed rate). The PT quote uses
    the documented historical pool-depth proxy for the §9 exit model. A synthetic LENDING borrow leg is
    attached per underlying (the documented borrow proxy) so the LEVERED/RATE_MATRIX shapes can form.

    BOROS legs: by default EMPTY (no keyless hedge venue → BASIS_HEDGE never forms — reported honestly).
    When `proxy_hedge_apy` is given (BACKTEST-ONLY, HEDGE_IS_BACKTEST_PROXY path), a SYNTHETIC Boros
    pay-variable leg is attached per underlying at that annualized funding-proxy rate and the PT quotes
    are stamped hedge_available=True, so the BASIS_HEDGE shape forms and the isolated basis (PT fixed −
    funding proxy − costs) can be simulated. This NEVER touches the live feed (BorosFeed.HEDGE_ENABLED
    stays False); it is research/reporting only.

    PURE / fail-CLOSED: a malformed market RAISES; a market without an as_of sample is simply absent."""
    proxy_on = proxy_hedge_apy is not None
    as_of_ts = _as_of_ts(as_of)
    pt_quotes: Dict[str, RateQuote] = {}
    lending_quotes: Dict[str, RateQuote] = {}
    boros_quotes: Dict[str, RateQuote] = {}
    supply_quotes: Dict[str, RateQuote] = {}

    # pick, per underlying, the longest-tenor live PT with a sample today
    best_by_u: Dict[str, Tuple[int, RateQuote]] = {}
    markets = deep.get("markets")
    if not isinstance(markets, dict) or not markets:
        raise ValueError("deep dataset: empty/invalid 'markets'")
    for key, m in sorted(markets.items()):
        kind = _KIND_BY_VALUE.get(m.get("kind"))
        if kind is None:
            raise ValueError(f"deep market {key}: bad kind {m.get('kind')!r}")
        by_date = {pt["date"]: pt for pt in m["series"] if "date" in pt}
        pt = by_date.get(as_of)
        if pt is None:
            continue
        implied = pt.get("implied_yield")
        if implied is None:
            continue
        maturity = m.get("maturity")
        if not maturity:
            raise ValueError(f"deep market {key}: missing maturity")
        tenor = _maturity_ts(maturity) - as_of_ts
        if tenor <= 0:
            continue  # matured — cannot hold
        u = str(m.get("underlying", "")).lower()
        if not u:
            raise ValueError(f"deep market {key}: missing underlying")
        # §9 pool depth — CONTEMPORANEOUS per-day TVL (Oct-2025 fix), fail-CLOSED to the documented
        # constant only when a day carries no recorded TVL (old deep file). The exit model shrinks
        # with real pool depth so the sleeve sizes down / exits when liquidity thins.
        depth = config.contemporaneous_pool_depth_usd(pt.get("tvl_usd"))
        sla = config.redemption_sla_seconds(u)
        q = RateQuote(
            underlying=u, kind=kind, venue=RateVenue.PENDLE_PT, protocol="pendle",
            market_id=str(key), tenor_seconds=int(tenor), as_of=as_of,
            quoted_rate=Decimal(str(implied)), tvl_usd=depth,
            exit_liquidity_usd=exit_liquidity_usd(depth, sla),
            # hedge_available reflects the live map by default; the BACKTEST-ONLY proxy path stamps it
            # True so the BASIS_HEDGE shape forms against the synthetic funding-proxy Boros leg below.
            hedge_available=bool(proxy_on or hedge_map.get(u, False)),
        )
        prev = best_by_u.get(u)
        if prev is None or tenor > prev[0]:
            best_by_u[u] = (int(tenor), q)

    for u, (_, q) in best_by_u.items():
        pt_quotes[u] = q
        if include_lending:
            sla = config.redemption_sla_seconds(u)
            lending_quotes[u] = RateQuote(
                underlying=u, kind=q.kind, venue=RateVenue.LENDING, protocol="lending_proxy",
                market_id=f"borrow:{u}", tenor_seconds=0, as_of=as_of,
                quoted_rate=BORROW_APR, tvl_usd=BORROW_DEPTH_USD,
                exit_liquidity_usd=exit_liquidity_usd(BORROW_DEPTH_USD, sla),
                hedge_available=False, utilization=BORROW_UTILIZATION, ltv=BORROW_LTV,
            )
        if proxy_on:
            # BACKTEST-ONLY synthetic Boros pay-variable leg at the annualized funding-proxy rate. Same
            # exit depth as the PT leg (the hedge sits on the same underlying's liquidity surface), so
            # the §9 exit model binds on the thinner of the two legs (here equal). NEVER live.
            boros_quotes[u] = RateQuote(
                underlying=u, kind=q.kind, venue=RateVenue.BOROS, protocol="funding_proxy",
                market_id=f"boros_proxy:{u}", tenor_seconds=q.tenor_seconds, as_of=as_of,
                quoted_rate=proxy_hedge_apy, tvl_usd=q.tvl_usd,
                exit_liquidity_usd=q.exit_liquidity_usd, hedge_available=True,
            )

    surface = RateSurface(
        as_of=as_of, pt_quotes=pt_quotes, lending_quotes=lending_quotes,
        boros_quotes=boros_quotes, supply_quotes=supply_quotes,
    )
    risks = {u: _risk_for(u, q.kind, as_of, funding_neg_frac_90d)
             for u, q in pt_quotes.items()}
    return surface, risks


def _all_dates(deep: dict) -> List[str]:
    dates: set = set()
    for m in deep["markets"].values():
        for pt in m["series"]:
            if "date" in pt:
                dates.add(pt["date"])
    return sorted(dates)


def _maturity_map(deep: dict) -> Dict[str, str]:
    """market_id -> maturity ISO-date, for the WHOLE deep universe. Used by the replay to RETIRE a PT
    book the day it matures (the notional redeems back to cash) so a held PT does NOT keep accruing its
    locked carry forever past maturity. Without this the replay over-states net APY massively: a 99%-APY
    synth PT bought in 2024 would accrue ~99%/yr indefinitely across the entire 2.5-year window, which
    is an APY-computation artifact, not a real (held-to-maturity) carry."""
    out: Dict[str, str] = {}
    for key, m in deep.get("markets", {}).items():
        mat = m.get("maturity")
        if mat:
            out[str(key)] = str(mat)[:10]
    return out


def _retire_matured(sleeve, maturities: Dict[str, str], as_of: str) -> int:
    """Retire (redeem→cash) every open FixedCarry book whose PT has reached/passed maturity on `as_of`.
    Returns the number retired. The notional returns to cash (sleeve._unwind), where it then earns at
    most the cash/RWA floor — exactly as a real maturing PT would (you get your principal back; you do
    NOT keep clipping the fixed coupon on an instrument that no longer exists)."""
    if not hasattr(sleeve, "_books"):
        return 0
    retired = 0
    for mid in list(sleeve._books.keys()):
        mat = maturities.get(mid)
        if mat and mat <= as_of[:10]:
            if hasattr(sleeve, "_unwind"):
                # FixedCarrySleeve: redeem→cash + audit log via its own unwind path.
                sleeve._unwind(mid, KillReason.MATURITY_BUFFER, f"matured {mat}")
            else:
                # Phase-1 pure sleeves (Levered/Basis/RateMatrix) have no _unwind: redeem the book's
                # notional back to cash directly (carry was already accrued in step()), mirroring the
                # cash bookkeeping step_apply does on an 'unwind' order.
                bk = sleeve._books.pop(mid, None)
                if bk is not None:
                    sleeve._cash += bk["size"]
                    if hasattr(sleeve, "_closed"):
                        sleeve._closed.append({
                            "market_id": mid, "reason": KillReason.MATURITY_BUFFER.value,
                            "note": f"matured {mat}", "size": str(bk["size"]),
                            "entry_rate": str(bk["entry_rate"]),
                        })
            retired += 1
    return retired


def _funding_neg_frac_90d(funding: Dict[str, float], date: str) -> Decimal:
    dates = sorted(d for d in funding if d <= date)
    tail = dates[-90:]
    if not tail:
        return D0
    neg = sum(1 for d in tail if funding[d] < 0)
    return Decimal(str(round(neg / len(tail), 6)))


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# Per-sleeve replay
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def _max_drawdown_pct(equity: List[float]) -> float:
    if len(equity) < 2:
        return 0.0
    peak = equity[0]
    worst = 0.0
    for e in equity:
        if e > peak:
            peak = e
        if peak > 0:
            dd = (peak - e) / peak * 100.0
            if dd > worst:
                worst = dd
    return round(worst, 6)


def _deflated_block(returns: List[float], floor_daily: float, n_trials: int) -> dict:
    n = len(returns)
    if n < 2:
        return {"n_obs": n, "status": "insufficient observations"}
    mom = moments(returns)
    sr_pp = sharpe_per_period(returns, rf_per_period=floor_daily)
    sr_annual = annualize_sharpe(sr_pp)
    nt = max(2, n_trials)
    dsr = deflated_sharpe_ratio(sr_pp, n, sr_variance_across_trials=(sr_pp ** 2) / nt,
                                n_trials=nt, skew=mom["skew"], kurt=mom["kurt"])
    psr = probabilistic_sharpe_ratio(sr_pp, n, skew=mom["skew"], kurt=mom["kurt"],
                                     sr_benchmark_per_period=floor_daily)
    mintrl = min_track_record_length(sr_pp, skew=mom["skew"], kurt=mom["kurt"],
                                     sr_benchmark_per_period=floor_daily)
    mintrl_obs = None if mintrl == float("inf") else round(mintrl, 1)
    return {
        "n_obs": n,
        "sharpe_annual_vs_floor": round(sr_annual, 4),
        "psr_vs_floor": round(psr, 4),
        "deflated_sharpe": round(dsr["dsr"], 4),
        "deflated_sharpe_passes_0_95": bool(dsr["passes"]),
        "min_track_record_length_obs": mintrl_obs,
        "mintrl_satisfied": bool(mintrl_obs is not None and n >= mintrl_obs),
    }


def replay_sleeve(
    sleeve_kind: str,
    dates: List[str],
    deep: dict,
    funding: Dict[str, float],
    hedge_map: Dict[str, bool],
    params: RatePolicyParams,
    costs: CostConfig,
    capital: Decimal = DEFAULT_CAPITAL,
    use_funding_proxy: bool = False,
    return_series: bool = False,
) -> dict:
    """Replay ONE sleeve over the full historical date stream. Returns the per-sleeve result block.

    Pipeline per day (date order): build the surface for the day → drive the sleeve (FixedCarry uses
    scan_and_enter+tick_hold on the flat PT quotes; the Phase-1 sleeves use step_apply on the
    RateSurface) → accrue carry (sleeve.step) → record equity + count refusals/kills. PURE w.r.t. the
    sleeve; this harness only threads the surface stream + bookkeeping. Deterministic.

    `use_funding_proxy` (BACKTEST-ONLY, basis_hedge only): when True each day's surface is built with a
    synthetic Boros pay-variable leg at the annualized funding-proxy rate (so BASIS_HEDGE forms). NEVER
    set on the live path — the live BasisHedge stays BLOCKED-NO-HEDGE."""
    floor = params.rwa_floor
    floor_daily = float(floor) / 365.0
    floor_daily_dec = floor / Decimal("365")
    maturities = _maturity_map(deep)

    sleeve = _build_sleeve(sleeve_kind, params, costs)
    sleeve.init(float(capital), {})

    equity: List[float] = []
    series_dates: List[str] = []  # date axis parallel to `equity` (only days that produced a bar)
    refusals_count = 0
    approvals_count = 0
    kills = 0
    carry_days = 0
    no_opp_days = 0
    matured_count = 0

    def _accrue_idle_cash_floor() -> None:
        """HONEST capital basis: the un-deployed (idle / refused / between-maturity) cash earns AT MOST
        the cash/RWA floor — exactly the basis the 3.4% RWA floor is on. Without this the book's net APY
        would be the annualized return on only the small DEPLOYED slice (ignoring idle-cash drag), which
        OVER-states the book return. Crediting idle cash at the floor makes net_apy a return on the TOTAL
        sleeve capital ($100k book), directly comparable to the floor. A sleeve that can only safely
        deploy a fraction into thin PT pools therefore shows a MODEST book APY (deployed·carry +
        idle·floor), reflecting the real capacity constraint — not a slice-only number."""
        cash = getattr(sleeve, "_cash", None)
        if cash is not None and cash > D0:
            sleeve._accrued += cash * floor_daily_dec

    # FixedCarry uses a synthetic step()-accrual at the sleeve level; the Phase-1 sleeves accrue via
    # their own step(). We drive both uniformly and read equity() after each day.
    for d in dates:
        fneg = _funding_neg_frac_90d(funding, d)
        proxy = _proxy_hedge_apy(funding, d) if use_funding_proxy else None
        try:
            surface, risks = build_deep_surface(d, deep, fneg, hedge_map, proxy_hedge_apy=proxy)
        except ValueError:
            # a malformed surface day is a data gap → fail-CLOSED safe-hold (no advance this day).
            continue

        # RETIRE matured PT books FIRST (notional redeems → cash). A held PT must NOT keep accruing its
        # locked carry past maturity — doing so was the primary net-APY artifact (a 99%-APY synth PT
        # bought in 2024 was accruing ~99%/yr across the whole 2.5-year window). After this, the
        # redeemed notional sits in cash and earns only the floor below.
        matured_count += _retire_matured(sleeve, maturities, d)

        if not surface.pt_quotes:
            no_opp_days += 1
            # still accrue the idle cash floor on a no-opportunity day (whole book is in cash).
            _accrue_idle_cash_floor()
            equity.append(sleeve.equity())
            series_dates.append(d)
            continue

        if isinstance(sleeve, FixedCarrySleeve):
            ref, app, kl, held = _drive_fixed_carry(sleeve, surface, risks, d)
        else:
            ref, app, kl, held = _drive_pure_sleeve(sleeve, surface, risks, d)
        refusals_count += ref
        approvals_count += app
        kills += kl
        if held:
            carry_days += 1

        # one accrual tick (the sleeve's daily carry on its open books) + the idle-cash floor on the
        # un-deployed remainder, so net_apy is on the TOTAL sleeve capital (same basis as the floor).
        sleeve.step(MarketSnapshot(date=d))
        _accrue_idle_cash_floor()
        equity.append(sleeve.equity())
        series_dates.append(d)

    n = len(equity)
    cap_f = float(capital)
    net = equity[-1] - cap_f if equity else 0.0
    # annualize over the span actually replayed (n daily bars)
    span_years = (n / 365.0) if n else 0.0
    net_apy_pct = round((net / cap_f) / span_years * 100.0, 4) if (cap_f > 0 and span_years > 0) else 0.0

    # daily returns from equity for the deflated-Sharpe block
    rets = [(equity[i] - equity[i - 1]) / equity[i - 1] for i in range(1, n) if equity[i - 1]]
    n_underlyings = max(2, len({q.underlying for d in dates[:1]
                                for q in build_deep_surface(d, deep, D0, hedge_map)[0].pt_quotes.values()}
                              )) if dates else 2
    deflated = _deflated_block(rets, floor_daily, n_trials=n_underlyings)

    max_dd = _max_drawdown_pct(equity)
    mean_apy = round(((equity[-1] - cap_f) / cap_f) / span_years * 100.0, 4) if span_years > 0 else 0.0
    beats_floor = bool(net_apy_pct > float(floor) * 100.0)

    series = ([{"date": series_dates[i], "equity_usd": round(equity[i], 4)} for i in range(n)]
              if return_series else None)

    return {
        "sleeve_id": sleeve.id,
        "sleeve_name": sleeve.name,
        "shape": sleeve_kind,
        "is_advisory": True,
        "capital_usd": cap_f,
        "n_days": n,
        "net_apy_pct": net_apy_pct,
        "mean_apy_pct": mean_apy,
        "max_drawdown_pct": max_dd,
        "deflated_sharpe": deflated.get("deflated_sharpe"),
        "deflated_sharpe_passes_0_95": deflated.get("deflated_sharpe_passes_0_95", False),
        "deflated_block": deflated,
        "beats_floor": beats_floor,
        "rwa_floor_pct": round(float(floor) * 100.0, 4),
        "kills": kills,
        "refusals_count": refusals_count,
        "approvals_count": approvals_count,
        "carry_days": carry_days,
        "no_opportunity_days": no_opp_days,
        "matured_books": matured_count,
        "idle_cash_earns_floor": True,
        "capital_basis": "total_sleeve_capital",
        "final_equity_usd": round(equity[-1], 4) if equity else cap_f,
        **({"series": series} if return_series else {}),
    }


def _build_sleeve(kind: str, params: RatePolicyParams, costs: CostConfig):
    if kind == "fixed_carry":
        return FixedCarrySleeve(params)
    if kind == "levered_carry":
        return LeveredCarrySleeve(params, costs)
    if kind == "basis_hedge":
        return BasisHedgeSleeve(params, costs)
    if kind == "rate_matrix":
        return RateMatrixSleeve(params, costs)
    raise ValueError(f"unknown sleeve kind {kind!r}")


def _drive_fixed_carry(sleeve: FixedCarrySleeve, surface: RateSurface,
                       risks: Dict[str, UnderlyingRisk], as_of: str) -> Tuple[int, int, int, bool]:
    """Drive FixedCarry on the day's flat PT quotes (only the harvestable stable-synth carry leg is a
    fixed-carry candidate; the gate refuses toxic LRT books). Returns (refusals, approvals, kills,
    held_any)."""
    pt_quotes = list(surface.pt_quotes.values())
    # continuous hold-kill first (the gate refreshes tenor toward maturity from the held book)
    hold_verdicts = sleeve.tick_hold(risks, current_carries={}, as_of=as_of)
    kills = sum(1 for v in hold_verdicts if not v.approved)
    # GLOBAL APY CEILING (compose_under_global_policy): the rates desk composes UNDER the global
    # RiskPolicy, which REFUSES any position with APY > 30% as "risk too high". A PT whose implied yield
    # exceeds the ceiling is risk premium, not safe carry — the global policy would never approve it. We
    # still run it through the rate gate (so it is counted as a candidate/refusal, preserving the visible
    # refusal edge), but pass global_approved=False so the book can never OPEN. Splitting the scan by the
    # ceiling makes the composition per-quote without changing the gate. This (with maturity retirement +
    # idle-cash@floor) is what corrects the inflated net APY — the 2024 boom's 89–99% synth PTs no longer
    # leak into the book.
    under = [q for q in pt_quotes if q.quoted_rate <= GLOBAL_MAX_APY]
    over = [q for q in pt_quotes if q.quoted_rate > GLOBAL_MAX_APY]
    entry_verdicts = sleeve.scan_and_enter(under, risks, as_of, global_approved=True)
    if over:
        entry_verdicts = entry_verdicts + sleeve.scan_and_enter(over, risks, as_of, global_approved=False)
    refusals = sum(1 for v in entry_verdicts if not v.approved)
    approvals = sum(1 for v in entry_verdicts if v.approved)
    return refusals, approvals, kills, bool(sleeve._books)


def _drive_pure_sleeve(sleeve, surface: RateSurface, risks: Dict[str, UnderlyingRisk],
                       as_of: str) -> Tuple[int, int, int, bool]:
    """Drive a Phase-1 pure sleeve (Levered / Basis / RateMatrix) one day. Returns (refusals,
    approvals, kills, held_any). Refusals here = candidate shapes the gate did NOT open (scanned −
    opened); kills = unwind orders."""
    # GLOBAL APY CEILING (compose_under_global_policy): drive the sleeve on a surface whose over-ceiling
    # (>30% APY) PT quotes are removed — the global RiskPolicy would refuse those positions, so they can
    # never OPEN a book. Candidate counting below uses the FULL surface, so an over-ceiling opportunity
    # still counts toward refusals (scanned − opened). Keeps the visible refusal edge while preventing the
    # 2024 boom's 89–99% synth PTs from opening a book.
    open_surface = _ceiling_filtered_surface(surface)
    orders = sleeve.step_apply(open_surface, risks, as_of)
    opened = sum(1 for o in orders if o["action"] == "open")
    rotated = sum(1 for o in orders if o["action"] == "rotate")
    unwound = sum(1 for o in orders if o["action"] == "unwind")
    approvals = opened + rotated
    # count candidate shapes this sleeve cares about that the engine scanned this day (FULL surface)
    shape = {"rates_desk_levered_carry": "levered_carry",
             "rates_desk_basis_hedge": "basis_hedge",
             "rates_desk_rate_matrix": "rate_matrix"}.get(sleeve.id, "")
    scanned = _count_candidates(sleeve, surface, risks, as_of, shape)
    refusals = max(0, scanned - opened)
    return refusals, approvals, unwound, bool(sleeve._books)


def _ceiling_filtered_surface(surface: RateSurface) -> RateSurface:
    """A copy of the surface with over-ceiling (>GLOBAL_MAX_APY) PT quotes removed, so a sleeve never
    OPENS a book the global RiskPolicy (30% APY ceiling) would refuse. Lending/boros/supply legs are
    carried through unchanged (the borrow proxy is well below the ceiling)."""
    kept = {u: q for u, q in surface.pt_quotes.items() if q.quoted_rate <= GLOBAL_MAX_APY}
    if len(kept) == len(surface.pt_quotes):
        return surface
    return RateSurface(
        as_of=surface.as_of, pt_quotes=kept, lending_quotes=surface.lending_quotes,
        boros_quotes=surface.boros_quotes, supply_quotes=surface.supply_quotes,
    )


def _count_candidates(sleeve, surface, risks, as_of, shape: str) -> int:
    """How many opportunities of the sleeve's shape the OpportunityEngine emitted this day (the
    'considered' count, for the refusals tally)."""
    from spa_core.strategy_lab.rates_desk.contracts import TradeShape
    want = {"levered_carry": TradeShape.LEVERED_CARRY,
            "basis_hedge": TradeShape.BASIS_HEDGE,
            "rate_matrix": TradeShape.RATE_MATRIX}.get(shape)
    if want is None:
        return 0
    try:
        scanned = sleeve.opp_engine.scan_detailed(surface, risks, as_of)
    except Exception:  # noqa: BLE001 — fail-CLOSED: a scan error counts as no candidates
        return 0
    return sum(1 for so in scanned if so.opportunity.shape == want)


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# run — replay all four sleeves over the deep surface
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def run(
    params: Optional[RatePolicyParams] = None,
    costs: Optional[CostConfig] = None,
    deep: Optional[dict] = None,
    funding: Optional[Dict[str, float]] = None,
    write: bool = True,
    out_path: Optional[Path] = None,
    capital: Decimal = DEFAULT_CAPITAL,
    hedge_backtest_proxy: Optional[bool] = None,
) -> dict:
    """Replay all four rates-desk sleeves over the deep historical surface and (optionally) write
    data/rates_desk/rates_backtest.json atomically. Deterministic: same (deep, funding) → same result.

    `hedge_backtest_proxy` (BACKTEST-ONLY): when True (default = the module-level HEDGE_IS_BACKTEST_PROXY
    flag), the BasisHedge sleeve is ADDITIONALLY simulated with the historical 5-venue median funding as
    the hedge-leg rate proxy, and the research-only result is attached to the basis_hedge block under
    `backtest_proxy`. The PRIMARY basis_hedge block (and its blocked_no_hedge=True / live promotion
    stage) is UNCHANGED — the proxy is research/reporting only and NEVER enables live execution. The live
    hedge map (BorosFeed.hedge_available) stays all-False regardless of this flag.

    fail-CLOSED: a missing deep dataset RAISES (we never produce a fabricated backtest)."""
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

    dates = _all_dates(deep)
    # honest hedge map straight from the Boros feed (all False until a keyless venue exists)
    universe = sorted({m["underlying"].lower() for m in deep["markets"].values()})
    hedge_map = BorosFeed().hedge_available(universe)

    sleeves: Dict[str, dict] = {}
    for kind in ("fixed_carry", "levered_carry", "basis_hedge", "rate_matrix"):
        sleeves[kind] = replay_sleeve(kind, dates, deep, funding, hedge_map, params, costs, capital)

    # BasisHedge honesty: if hedge is unavailable everywhere (LIVE truth), the PRIMARY block is BLOCKED.
    hedge_available_any = any(hedge_map.values())
    if not hedge_available_any:
        bh = sleeves["basis_hedge"]
        bh["blocked_no_hedge"] = True
        bh["blocked_reason"] = (
            "BASIS_HEDGE unavailable — BorosFeed.HEDGE_ENABLED is False (no keyless forward-funding "
            "venue), so the shape never forms. Reported honestly as zero opportunities, never fabricated.")

    # ── BACKTEST-ONLY funding-proxy simulation of BasisHedge (research/reporting only) ──
    # Replays the BasisHedge sleeve with a synthetic Boros leg priced at the annualized 5-venue median
    # funding (the hedge-rate proxy), under the SAME honest accounting as the others (net_apy on total
    # capital, idle@floor, maturity-retire, 30% ceiling). The result is attached as a SEPARATE
    # `backtest_proxy` sub-block; it does NOT change blocked_no_hedge or the live promotion stage. The
    # live path (BorosFeed.HEDGE_ENABLED / hedge_map / the live gate) is untouched.
    proxy_on = HEDGE_IS_BACKTEST_PROXY if hedge_backtest_proxy is None else bool(hedge_backtest_proxy)
    if proxy_on and funding:
        proxy_block = replay_sleeve(
            "basis_hedge", dates, deep, funding, hedge_map, params, costs, capital,
            use_funding_proxy=True)
        floor_pct = round(float(params.rwa_floor) * 100.0, 4)
        proxy_block.update({
            "label": "BACKTEST-ONLY (funding proxy) · live-BLOCKED until Boros permissionless",
            "hedge_rate_source": "5-venue median perp funding (funding_feed), annualized funding_8h*3*365",
            "live_eligible": False,
            "beats_floor_backtest_proxy": bool(proxy_block.get("net_apy_pct", 0.0) > floor_pct),
        })
        sleeves["basis_hedge"]["backtest_proxy"] = proxy_block

    result = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "model": "rates_desk_backtest_replay",
        "llm_forbidden": True,
        "deterministic": True,
        "data_source": "deep_pendle_pt_history",
        "window": deep.get("window"),
        "n_dates": len(dates),
        "capital_usd": float(capital),
        "rwa_floor_pct": round(float(params.rwa_floor) * 100.0, 4),
        "hedge_available": hedge_map,
        "hedge_available_any": hedge_available_any,
        "hedge_is_backtest_proxy": bool(proxy_on),
        "borrow_proxy": {
            "borrow_apr": str(BORROW_APR), "ltv": str(BORROW_LTV),
            "utilization": str(BORROW_UTILIZATION),
            "note": ("documented borrow-leg PROXY for the levered/rate-matrix shapes — the deep PT "
                     "history carries no money-market quotes; the live feed supplies the real rate"),
        },
        "sleeves": sleeves,
    }
    if write:
        _atomic_write_json(out_path or _OUT, result)
    return result


def _render_doc_section(result: dict, promotion: Optional[dict]) -> str:
    """Render the 4-sleeve validation markdown section (between the idempotent markers). Includes the
    full per-sleeve table (net APY, beats-floor, deflated Sharpe, stage) + the honest BasisHedge note."""
    floor = result.get("rwa_floor_pct")
    stage_by_id = {}
    stress_dd_by_id = {}
    if isinstance(promotion, dict):
        stage_by_id = {s.get("id"): s.get("stage") for s in promotion.get("sleeves", [])}
        stress_dd_by_id = {s.get("id"): s.get("stress_dd_pct") for s in promotion.get("sleeves", [])
                           if s.get("stress_dd_pct") is not None}
    lines: List[str] = [_DOC_BEGIN, ""]
    lines.append("## Full 4-sleeve validation (backtest_rates replay)\n")
    lines.append(
        "_Replay of all four rates-desk sleeves over the DEEP historical RateSurface "
        f"({result.get('window', {}).get('start')}→{result.get('window', {}).get('end')}, "
        f"{result.get('n_dates')} days, ${result.get('capital_usd'):,.0f} each). Deterministic "
        "(same data → same result), PURE pricing/policy, fail-CLOSED. Re-runnable via "
        "`python3 -m spa_core.strategy_lab.rates_desk.backtest_rates`._\n")
    lines.append(f"RWA floor: **{floor}%/yr**. Boros hedge venue: "
                 f"**{'ON' if result.get('hedge_available_any') else 'OFF — all False (honest)'}**.\n")
    lines.append("| sleeve | shape | net APY %/yr | beats floor | max DD % | deflated Sharpe "
                 "(passes 0.95) | kills | refusals | stage |")
    lines.append("|---|---|---:|:--:|---:|---:|---:|---:|---|")
    names = {"fixed_carry": "Fixed Carry (PT→maturity)",
             "levered_carry": "Levered Carry (borrow stable, buy PT)",
             "basis_hedge": "Basis Hedge (PT vs Boros funding)",
             "rate_matrix": "Rate Matrix (argmax venue)"}
    for kind in ("fixed_carry", "levered_carry", "basis_hedge", "rate_matrix"):
        s = result["sleeves"][kind]
        sid = s.get("sleeve_id", kind)
        ds = s.get("deflated_sharpe")
        ds_s = (f"{ds} ({'yes' if s.get('deflated_sharpe_passes_0_95') else 'no'})"
                if ds is not None else "—")
        beats = "yes" if s.get("beats_floor") else "no"
        stage = stage_by_id.get(sid, "—")
        # LeveredCarry: the backtest DD is leverage-BLIND (0.0%); show the HONEST stress DD instead.
        dd_val = s.get("max_drawdown_pct", 0.0)
        dd_s = f"{dd_val:.3f}"
        if sid in stress_dd_by_id:
            dd_s = f"{float(stress_dd_by_id[sid]):.3f} (stress)"
        if s.get("blocked_no_hedge"):
            ds_s = "n/a"
            beats = "n/a (blocked)"
        lines.append(
            f"| {names[kind]} | `{kind}` | {s.get('net_apy_pct', 0.0):.4f} | {beats} | "
            f"{dd_s} | {ds_s} | {s.get('kills', 0)} | "
            f"{s.get('refusals_count', 0)} | **{stage}** |")
    lines.append("")
    if stress_dd_by_id:
        lines.append(
            "> **LeveredCarry max DD is the HONEST levered-stress figure**, not the backtest's "
            "leverage-blind 0.0% (the replay equity model accrues carry on the base size and never "
            "marks the borrow leg / levered PT — see the LeveredCarry stress section). It keeps "
            "PAPER_CANDIDATE only because the kill rules unwind every levered loop within the "
            "drawdown band; it is GATED-LEVERAGE-DEPENDENT and 'last to enable' per the brief.\n")
    bh = result["sleeves"]["basis_hedge"]
    if bh.get("blocked_no_hedge"):
        lines.append(f"> **BasisHedge — BLOCKED-NO-HEDGE.** {bh.get('blocked_reason', '')}\n")
    # ── THIRD honest stage: the BACKTEST-ONLY funding-proxy BasisHedge result (research, live-BLOCKED) ──
    proxy = bh.get("backtest_proxy")
    if isinstance(proxy, dict):
        p_napy = proxy.get("net_apy_pct", 0.0)
        p_beats = "yes" if proxy.get("beats_floor_backtest_proxy") else "no"
        p_ds = proxy.get("deflated_sharpe")
        p_ds_s = (f"{p_ds} ({'yes' if proxy.get('deflated_sharpe_passes_0_95') else 'no'})"
                  if p_ds is not None else "—")
        lines.append("### BasisHedge — BACKTEST-ONLY (funding proxy) · live-BLOCKED until Boros permissionless\n")
        lines.append(
            "_Isolated-basis simulation: PT receive-fixed minus the 5-venue median perp funding paid on "
            "the hedge leg (the documented hedge-rate proxy, annualized funding_8h·3·365), minus costs, "
            "over the deep window. SAME honest accounting as the carry sleeves (net APY on TOTAL capital, "
            "idle cash @ floor, maturity-retire, 30% global ceiling) so the number is comparable — NOT an "
            "inflated slice. This is RESEARCH ONLY: the live BasisHedge stays BLOCKED-NO-HEDGE (no keyless "
            "Boros venue), and this proxy result never enables live execution._\n")
        lines.append("| basis (funding proxy) | net APY %/yr | beats floor | max DD % | deflated Sharpe "
                     "(passes 0.95) | kills | refusals | live |")
        lines.append("|---|---:|:--:|---:|---:|---:|---:|:--:|")
        lines.append(
            f"| isolated basis | {p_napy:.4f} | {p_beats} | {proxy.get('max_drawdown_pct', 0.0):.3f} | "
            f"{p_ds_s} | {proxy.get('kills', 0)} | {proxy.get('refusals_count', 0)} | **BLOCKED** |")
        verdict = ("**beats** the" if proxy.get("beats_floor_backtest_proxy") else "does **NOT** beat the")
        lines.append(
            f"\n> **Honest verdict:** on the funding proxy the isolated basis {verdict} {floor}%/yr RWA "
            f"floor (net {p_napy:.4f}%/yr, total-capital basis). Either way it stays live-BLOCKED until a "
            "permissionless Boros forward-funding venue exists; the proxy answers the research question "
            "without flipping any live eligibility.\n")
    lines.append(
        "> The desk's whole edge is visible in the **refusals** column: the gate refused the toxic "
        "restaking (LRT) books on most days — the carry sleeves only ever held the harvestable "
        "stable-synth PTs. Net APY is the locked-at-entry carry held to maturity (degenerate-Sharpe "
        "near-zero downside by construction — the verdict rests on beating the floor across stress, "
        "see Assertion 2 above).\n")
    lines.append(_DOC_END)
    return "\n".join(lines)


def write_validation_section(result: dict, promotion: Optional[dict] = None,
                            doc_path: Optional[Path] = None) -> Path:
    """Idempotently (re)write the 4-sleeve section into docs/RATES_DESK_VALIDATION.md between the
    markers, preserving the assertion1/assertion2 content validation.py owns. Atomic write."""
    path = doc_path or _DOC
    section = _render_doc_section(result, promotion)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if _DOC_BEGIN in existing and _DOC_END in existing:
        pre = existing[: existing.index(_DOC_BEGIN)].rstrip("\n")
        post = existing[existing.index(_DOC_END) + len(_DOC_END):].lstrip("\n")
        body = (pre + "\n\n" + section + ("\n\n" + post if post else "\n")).rstrip("\n") + "\n"
    else:
        body = (existing.rstrip("\n") + "\n\n" + section + "\n") if existing else (section + "\n")
    _io.atomic_write_text(path, body)
    return path


def _print_table(result: dict) -> None:
    floor = result.get("rwa_floor_pct")
    print(f"Rates Desk — Sleeve Backtest Replay   (RWA floor {floor}%)")
    print(f"window: {result.get('window')}  ·  dates: {result.get('n_dates')}  ·  "
          f"capital: ${result.get('capital_usd'):,.0f}")
    print()
    hdr = (f"{'sleeve':16s} {'net APY%':>9s} {'maxDD%':>8s} {'deflSharpe':>11s} "
           f"{'beats':>6s} {'kills':>6s} {'refusals':>9s}")
    print(hdr)
    print("-" * len(hdr))
    for kind in ("fixed_carry", "levered_carry", "basis_hedge", "rate_matrix"):
        s = result["sleeves"][kind]
        ds = s.get("deflated_sharpe")
        ds_s = f"{ds:.3f}" if isinstance(ds, (int, float)) else "—"
        beats = "yes" if s.get("beats_floor") else "no"
        extra = "  [BLOCKED-NO-HEDGE]" if s.get("blocked_no_hedge") else ""
        print(f"{kind:16s} {s.get('net_apy_pct', 0.0):9.4f} {s.get('max_drawdown_pct', 0.0):8.3f} "
              f"{ds_s:>11s} {beats:>6s} {s.get('kills', 0):6d} {s.get('refusals_count', 0):9d}{extra}")
    # THIRD honest stage: BACKTEST-ONLY funding-proxy basis (research, live-BLOCKED)
    proxy = result["sleeves"]["basis_hedge"].get("backtest_proxy")
    if isinstance(proxy, dict):
        ds = proxy.get("deflated_sharpe")
        ds_s = f"{ds:.3f}" if isinstance(ds, (int, float)) else "—"
        beats = "yes" if proxy.get("beats_floor_backtest_proxy") else "no"
        print(f"{'basis(proxy)':16s} {proxy.get('net_apy_pct', 0.0):9.4f} "
              f"{proxy.get('max_drawdown_pct', 0.0):8.3f} {ds_s:>11s} {beats:>6s} "
              f"{proxy.get('kills', 0):6d} {proxy.get('refusals_count', 0):9d}  "
              f"[BACKTEST-ONLY · live-BLOCKED]")


def main() -> int:
    # Reporting run turns the BACKTEST-ONLY funding proxy ON (research only — live stays BLOCKED).
    result = run(write=True, hedge_backtest_proxy=True)
    _print_table(result)
    print(f"\nWrote {_OUT}")
    # also map into the promotion engine + (re)write the 4-sleeve section of the validation doc
    promotion = None
    try:
        from spa_core.strategy_lab.rates_desk import promotion_rates
        promotion = promotion_rates.build_report(write=True, backtest=result)
        print(f"Wrote {promotion_rates.DEFAULT_OUT}")
    except Exception as exc:  # noqa: BLE001 — doc/promotion enrichment must not fail the backtest
        print(f"(promotion mapping skipped: {exc})")
    try:
        write_validation_section(result, promotion)
        print(f"Updated {_DOC} (4-sleeve section)")
    except Exception as exc:  # noqa: BLE001
        print(f"(doc section skipped: {exc})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
