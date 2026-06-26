"""
spa_core/strategy_lab/rates_desk/feeds.py — the Rates-Desk DATA LAYER (the RateSurface assembler).

THIS IS PURE DATA. Per the implementation brief §1-2, the feeds emit the EXACT contract dataclasses
(RateQuote / UnderlyingRisk from contracts.py) and NOTHING ELSE. There is **no judgment** here — no
haircuts, no fair-value, no approve/refuse. All of that lives in the engine (fair_value_engine.py /
rate_policy.py), which this module does NOT touch. A feed's only job is to turn a real (or injected)
data source into validated, Decimal-exact rows.

Five feeds + the assembler:

  1. PendleMarketFeed   → RateQuote rows, venue=PENDLE_PT (one per PT market).
                          Historical via pendle_pt_history (REUSED verbatim — the deep expired-markets
                          implied-yield pull), live via the keyless /active markets endpoint.
  2. LendingRateFeed    → RateQuote rows, venue=LENDING (LENDING_SUPPLY + LENDING_BORROW) for the
                          USDC money-markets + PT-collateral markets (Morpho / Euler / Aave) via the
                          keyless DeFiLlama yields/lendBorrow surface.
  3. BorosFeed          → RateQuote rows, venue=BOROS (forward-funding) + an HONEST per-underlying
                          hedge_available flag. We PROBE for a keyless Boros endpoint; absent one, the
                          flag is False for every underlying and that is documented (so the engine
                          correctly drops BasisHedge + applies the larger funding-flip haircut). The
                          5-venue CEX funding feed is the SIGNAL, never an executable hedge.
  4. UnderlyingRiskFeed → one UnderlyingRisk per underlying (nav/market/peg + vol + funding_neg_frac
                          + redemption SLA / reserve / oracle / nesting — REUSING price_feed,
                          restaking_feed, funding_feed). Documented constants live in config.py.
  5. exit_liquidity_usd → the §9 model: pool depth absorbing <= a fixed price-impact band at the
                          trade size, DISCOUNTED by the redemption SLA (longer cooldown → smaller
                          usable exit). A documented PROXY, to be validated against Oct-2025 fills.

  build_surface(as_of) -> (list[RateQuote], dict[underlying -> UnderlyingRisk]) ties them together for
  BOTH backtest (a historical as_of) and live/paper (latest). ONE function = one source of truth.
  Caches to data/rates_desk/rate_surface.json atomically (tmp + shutil.move, repo rule #4).

CONVENTIONS (inherited, enforced): stdlib only (urllib + gzip + json); deterministic (as_of is an
explicit input, never the wall clock — only the live-`None` path resolves "latest"); fail-CLOSED —
missing / malformed data RAISES or is flagged, NEVER fabricated into a benign value; LLM-FORBIDDEN.

Run (real network, on the Mac):
    python3 -m spa_core.strategy_lab.rates_desk.feeds
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import gzip
import json
import statistics
import urllib.request
from decimal import Decimal
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from spa_core.strategy_lab.rates_desk import _io
from spa_core.strategy_lab.rates_desk import config
from spa_core.strategy_lab.rates_desk import pendle_pt_history as pph
from spa_core.strategy_lab.rates_desk.contracts import (
    D0,
    D1,
    RateQuote,
    RateVenue,
    UnderlyingKind,
    UnderlyingRisk,
)

_ROOT = Path(__file__).resolve().parents[3]
_SURFACE_OUT = _ROOT / "data" / "rates_desk" / "rate_surface.json"

Fetcher = Callable[[str], object]


class FeedError(ValueError):
    """A feed produced no usable, valid data (fail-CLOSED). Distinct from a transport error: this
    means the source was reached but the data was missing / malformed, so we refuse to emit a row."""


# ── stdlib HTTP (urllib + gzip), identical convention to pendle_pt_history ──────────────────────────
def _http_fetch(url: str, timeout: int = 30) -> object:
    req = urllib.request.Request(
        url,
        headers={
            "Accept-Encoding": "gzip",
            "User-Agent": "spa-rates-desk/1.0 (+stdlib)",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def _D(x) -> Decimal:
    """Parse anything numeric to a Decimal via str (NEVER float(x) → Decimal: that imports the
    float's binary noise). fail-CLOSED: a None / unparseable value raises."""
    if x is None:
        raise FeedError("expected a numeric value, got None")
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def _iso_date(as_of: str) -> str:
    """Normalize an as_of (date or ISO timestamp) to a YYYY-MM-DD date string. Raises on garbage."""
    s = (as_of or "").strip()
    if not s:
        raise FeedError("as_of is empty")
    try:
        return datetime.date.fromisoformat(s[:10]).isoformat()
    except ValueError as exc:
        raise FeedError(f"as_of not an ISO date: {as_of!r}") from exc


def _maturity_ts(maturity: str) -> int:
    d = datetime.date.fromisoformat(maturity[:10])
    return int(datetime.datetime(d.year, d.month, d.day, tzinfo=datetime.timezone.utc).timestamp())


def _as_of_ts(as_of: str) -> int:
    d = datetime.date.fromisoformat(_iso_date(as_of))
    return int(datetime.datetime(d.year, d.month, d.day, tzinfo=datetime.timezone.utc).timestamp())


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# §9 — EXIT-LIQUIDITY MODEL  (the brief's hardest input)
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
def exit_liquidity_usd(
    pool_depth_usd: Decimal,
    redemption_sla_seconds: int,
    *,
    price_impact_band: Decimal = None,
    trade_size_usd: Optional[Decimal] = None,
) -> Decimal:
    """The one-tick USABLE exit capacity (USD) for a position, per brief §9.

    PROXY MODEL (documented; MUST be validated against the Oct-2025 restaking de-risk fills before
    any size is trusted — see RATES_DESK_DERISK.md):

      exit_liquidity = pool_depth * price_impact_band * sla_discount

    1. `pool_depth * price_impact_band` — the slice of a constant-product-ish pool you can take while
       the marginal price moves <= the band (default 50 bps from config.EXIT_PRICE_IMPACT_BAND_BPS).
       For a CP-AMM, the fraction of reserves that moves price by ~b is ~b/2 for small b; we use the
       slightly-more-conservative full `b` as a depth fraction (the desk's exit is a SELL into the
       pool, and PT pools are concentrated, so the linear-in-band depth proxy is intentionally tight).
    2. `sla_discount` — the redemption-SLA haircut. The longer the NAV-redemption cooldown, the LESS
       of that depth is *usable in one tick*: a 7-day cooldown means you cannot lean on the redemption
       backstop intratick, so secondary-market depth alone must absorb the exit. We discount linearly
       in cooldown days, floored, per config.SLA_DISCOUNT_* :
         sla_discount = clamp( 1 - SLA_DISCOUNT_PER_DAY * (sla_seconds/86400), SLA_DISCOUNT_FLOOR, 1)

    MONOTONICITY (tested): exit_liquidity is non-decreasing in pool_depth and NON-INCREASING in
    redemption_sla_seconds. `trade_size_usd` is accepted for API symmetry/future caller use; the
    returned capacity is a property of the pool+SLA, and the policy compares it against the requested
    size (max_size_frac_of_exit) — we do NOT silently clamp here (the engine owns that judgment).

    fail-CLOSED: a negative pool_depth or negative SLA raises (a malformed depth must NOT become a
    benign exit). Zero depth → zero exit (honest: nothing to exit into)."""
    if price_impact_band is None:
        price_impact_band = config.exit_price_impact_band()
    depth = _D(pool_depth_usd)
    if depth < D0:
        raise FeedError(f"exit_liquidity: negative pool_depth {depth}")
    if redemption_sla_seconds < 0:
        raise FeedError(f"exit_liquidity: negative redemption_sla_seconds {redemption_sla_seconds}")
    band = _D(price_impact_band)
    if band <= D0:
        raise FeedError(f"exit_liquidity: non-positive price_impact_band {band}")
    sla_days = Decimal(redemption_sla_seconds) / Decimal(86400)
    per_day = _D(config.SLA_DISCOUNT_PER_DAY)
    floor = _D(config.SLA_DISCOUNT_FLOOR)
    discount = D1 - per_day * sla_days
    if discount < floor:
        discount = floor
    if discount > D1:
        discount = D1
    return depth * band * discount


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# 1) PendleMarketFeed → RateQuote rows (venue = PENDLE_PT)
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# LIVE markets. TWO Pendle endpoints expose the current set with DIFFERENT shapes; we use BOTH so the
# live surface is as RICH as the deep/backtest one (the data-gap fix the brief calls out):
#
#   • /{chain}/markets/active  → the AUTHORITATIVE live set (~60 markets), each a flat dict with
#       {name(=underlying symbol), expiry, pt(=chain-addr string), underlyingAsset,
#        details:{impliedApy, liquidity, pendleApy, ...}}. This is what the desk needs: every CURRENT
#       sUSDe/USDe/sUSDS/wstETH PT with live implied APY + liquidity. We prefer this endpoint.
#   • /{chain}/markets?limit=&skip=  → the PAGED endpoint pendle_pt_history pages (WITHOUT the
#       `expired=true` flag). It returns mostly EXPIRED markets (impliedApy=0, expiry in the past) and
#       only the handful of live ones — too thin on its own (only ~2 live targets survive the
#       negative-tenor drop). Kept ONLY as a fail-CLOSED FALLBACK + for the injected `pt.symbol` test
#       shape; the active endpoint is authoritative when reachable.
#
# Why the old code under-surfaced: it used the paged /markets endpoint, matched on `pt.symbol`, and so
# saw only the 2 live target PTs buried among 470 mostly-expired markets — the LRT pools (ezETH/rsETH)
# have wound down and the sUSDS/wstETH pools never carry a PT-<token> symbol on this endpoint. The
# active endpoint surfaces all four current targets (sUSDe/USDe/sUSDS/wstETH) with real liquidity.
PENDLE_ACTIVE_URL = pph.PENDLE_API_BASE + "/{chain}/markets/active"
PENDLE_MARKETS_PAGED_URL = pph.PENDLE_API_BASE + "/{chain}/markets?limit={limit}&skip={skip}"


class PendleMarketFeed:
    """PT markets → RateQuote rows. Historical days REUSE the deep pendle_pt_history dataset (the
    expired-markets implied-yield pull); the live snapshot uses the keyless /active endpoint.

    Inject `fetcher` (url->json) in tests. Each row carries: underlying, kind, tenor_seconds
    (maturity - as_of, fail-CLOSED >= 0), quoted_rate (implied yield, Decimal), tvl_usd,
    exit_liquidity_usd (the §9 model on pool depth), hedge_available, cap_headroom_usd."""

    def __init__(self, fetcher: Optional[Fetcher] = None, chain: int = pph.CHAIN_ID):
        self._fetch = fetcher or _http_fetch
        self._chain = chain

    # ── historical (REUSE the deep dataset) ────────────────────────────────────────────────────
    def quotes_for_date(
        self,
        as_of: str,
        deep: dict,
        hedge_by_underlying: Optional[Dict[str, bool]] = None,
        sla_by_underlying: Optional[Dict[str, int]] = None,
    ) -> List[RateQuote]:
        """RateQuote rows for every PT market that has an implied-yield sample on `as_of` in the deep
        dataset (from pendle_pt_history.load()/build()). `deep` is the dataset dict — the caller loads
        it once and passes it (no IO here). fail-CLOSED: malformed market RAISES; a market without an
        as_of sample is simply absent (not fabricated)."""
        d = _iso_date(as_of)
        hedge_by_underlying = hedge_by_underlying or {}
        sla_by_underlying = sla_by_underlying or {}
        markets = deep.get("markets")
        if not isinstance(markets, dict) or not markets:
            raise FeedError("pendle deep dataset: empty/invalid 'markets'")
        as_of_ts = _as_of_ts(d)
        rows: List[RateQuote] = []
        for key, m in markets.items():
            if not isinstance(m, dict) or "series" not in m or "kind" not in m:
                raise FeedError(f"pendle market {key} malformed")
            by_date = {pt["date"]: pt for pt in m["series"] if "date" in pt}
            pt = by_date.get(d)
            if pt is None:
                continue
            implied = pt.get("implied_yield")
            if implied is None:
                continue
            try:
                kind = UnderlyingKind(m["kind"])
            except ValueError as exc:
                raise FeedError(f"pendle market {key}: bad kind {m['kind']!r}") from exc
            maturity = m.get("maturity")
            if not maturity:
                raise FeedError(f"pendle market {key}: missing maturity")
            tenor = _maturity_ts(maturity) - as_of_ts
            if tenor < 0:
                # the deep history never includes post-maturity samples; a negative tenor here means a
                # corrupt as_of/maturity pairing — fail-CLOSED rather than emit a matured "fixed rate".
                raise FeedError(f"pendle market {key}: negative tenor at {d} (maturity {maturity})")
            underlying = str(m.get("underlying", "")).lower()
            if not underlying:
                raise FeedError(f"pendle market {key}: missing underlying")
            # §9 pool depth — tie to the CONTEMPORANEOUS per-day TVL from the deep series so the exit
            # model SHRINKS when a pool's real depth collapses (the Oct-2025 calibration fix). Only
            # when a day carries no usable TVL (an old deep file pulled before the TVL series was
            # captured) do we fall back to the documented depth constant. Live days use /active liquidity.
            depth = config.contemporaneous_pool_depth_usd(pt.get("tvl_usd"))
            sla = int(sla_by_underlying.get(underlying, config.redemption_sla_seconds(underlying)))
            rows.append(
                RateQuote(
                    underlying=underlying,
                    kind=kind,
                    venue=RateVenue.PENDLE_PT,
                    protocol="pendle",
                    market_id=str(key),
                    tenor_seconds=int(tenor),
                    as_of=d,
                    quoted_rate=_D(implied),
                    tvl_usd=depth,
                    exit_liquidity_usd=exit_liquidity_usd(depth, sla),
                    hedge_available=bool(hedge_by_underlying.get(underlying, False)),
                    cap_headroom_usd=D0,
                )
            )
        rows.sort(key=lambda q: (q.underlying, q.market_id))
        return rows

    # ── live (/active markets) ───────────────────────────────────────────────────────────────────
    def quotes_live(
        self,
        as_of: str,
        hedge_by_underlying: Optional[Dict[str, bool]] = None,
        sla_by_underlying: Optional[Dict[str, int]] = None,
    ) -> List[RateQuote]:
        """RateQuote rows from the keyless Pendle /active endpoint for the current snapshot. Only the
        canonical straight PTs of our TARGET underlyings are kept (reusing pph._match_underlying so a
        nested wrapper variant is never mistaken for a clean PT). fail-CLOSED: malformed payload RAISES;
        a market missing implied/expiry/depth is SKIPPED (one bad market does not void the snapshot)."""
        d = _iso_date(as_of)
        hedge_by_underlying = hedge_by_underlying or {}
        sla_by_underlying = sla_by_underlying or {}
        markets = self._fetch_active_markets()
        as_of_ts = _as_of_ts(d)
        rows: List[RateQuote] = []
        for m in markets:
            parsed = _parse_live_market(m)
            if parsed is None:
                continue  # not a target / incomplete market — skip (never fabricate)
            underlying, market_id, implied, expiry, depth = parsed
            tenor = _maturity_ts(expiry) - as_of_ts
            if tenor < 0:
                continue  # an /active market past its expiry edge — skip
            kind = pph.TARGETS[underlying]
            ul = underlying.lower()
            sla = int(sla_by_underlying.get(ul, config.redemption_sla_seconds(ul)))
            rows.append(
                RateQuote(
                    underlying=ul,
                    kind=kind,
                    venue=RateVenue.PENDLE_PT,
                    protocol="pendle",
                    market_id=market_id,
                    tenor_seconds=int(tenor),
                    as_of=d,
                    quoted_rate=_D(implied),
                    tvl_usd=_D(depth),
                    exit_liquidity_usd=exit_liquidity_usd(_D(depth), sla),
                    hedge_available=bool(hedge_by_underlying.get(ul, False)),
                    cap_headroom_usd=D0,
                )
            )
        rows.sort(key=lambda q: (q.underlying, q.market_id))
        return rows

    # ── live markets fetch (/markets/active, rich shape; paged /markets fallback) ──────────────────
    def _fetch_active_markets(self, limit: int = pph.PAGE_LIMIT) -> List[dict]:
        """Fetch the live market set. PREFER the authoritative single-shot /markets/active endpoint
        ({"markets":[...]}) which carries the rich per-market details (impliedApy + liquidity per CURRENT
        market). An injected test fetcher may return that shape, the paged v2 shape ({"results":[...],
        "total":N}), or a bare list — all are handled. fail-CLOSED: a malformed payload RAISES.

        We page ONLY when the endpoint returns the paged shape (the real /markets?limit=&skip= fallback
        the tests may inject); the active endpoint returns everything at once, so the loop exits after
        the first page."""
        out: List[dict] = []
        skip = 0
        total: Optional[int] = None
        while True:
            payload = self._fetch(PENDLE_ACTIVE_URL.format(chain=self._chain, limit=limit, skip=skip))
            page = _pendle_markets_page(payload)
            if page is None:
                # the active endpoint / injected simple shape ({"markets":[...]} or a list) returns
                # everything at once — no pagination needed.
                return _pendle_active_markets(payload)
            results, total = page
            out.extend(results)
            skip += limit
            if total is None or skip >= int(total) or not results:
                break
        return [m for m in out if isinstance(m, dict)]


def _pendle_markets_page(payload: object):
    """If `payload` is the real paginated v2 shape ({"results":[...], "total":N}), return
    (results, total). Otherwise return None (the caller falls back to the single-shot parser).
    fail-CLOSED: a dict claiming pagination but with a non-list `results` RAISES."""
    if isinstance(payload, dict) and "results" in payload:
        results = payload.get("results")
        if not isinstance(results, list):
            raise FeedError("pendle /markets: 'results' is not a list")
        return [m for m in results if isinstance(m, dict)], payload.get("total")
    return None


def _pendle_active_markets(payload: object) -> List[dict]:
    """Single-shot live-markets payload (injected/simple shape): {"markets":[...]} or a bare list.
    fail-CLOSED: anything else raises."""
    if isinstance(payload, dict):
        ms = payload.get("markets")
        if isinstance(ms, list):
            return [m for m in ms if isinstance(m, dict)]
        raise FeedError("pendle live markets: missing 'markets' list")
    if isinstance(payload, list):
        return [m for m in payload if isinstance(m, dict)]
    raise FeedError(f"pendle live markets: expected object/list, got {type(payload).__name__}")


def _pendle_depth_usd(m: dict) -> Optional[Decimal]:
    """Pool depth (USD) of a live market, fail-CLOSED. Reads, in order:
      • the rich /markets/active shape: details.liquidity (a bare USD number) or details.tvl;
      • the legacy /markets shape: top-level tvl.usd / liquidity.usd (dict or bare number).
    These are AMM pools, so AMM liquidity IS the exitable TVL. Returns None if no positive depth is
    present (the market is then SKIPPED — never sized into a depthless pool)."""
    details = m.get("details")
    if isinstance(details, dict):
        for fld in ("liquidity", "tvl"):
            raw = details.get(fld)
            val = raw.get("usd") if isinstance(raw, dict) else raw
            if isinstance(val, (int, float)) and val > 0:
                return _D(val)
    for fld in ("tvl", "liquidity"):
        raw = m.get(fld)
        val = None
        if isinstance(raw, dict):
            val = raw.get("usd")
        elif isinstance(raw, (int, float)):
            val = raw
        if isinstance(val, (int, float)) and val > 0:
            return _D(val)
    return None


def _parse_live_market(m: dict):
    """Normalize ONE live market dict (either Pendle live shape) to (underlying, market_id, implied,
    expiry_date, depth) or None if it is not a clean target / is incomplete (fail-CLOSED skip).

    Handles BOTH shapes:
      • /markets/active (authoritative): {name(=underlying symbol), expiry, pt(=chain-addr string),
        details:{impliedApy, liquidity}}. Underlying matched EXACTLY by `name` (the clean underlying
        symbol) so a nested wrapper underlying never slips through.
      • /markets (legacy/injected test): {address, expiry, impliedApy, tvl/liquidity,
        pt:{address, symbol}}. Underlying matched by parsing the PT `symbol` (PT-<token>-<expiry>),
        which excludes wrapper PT symbols (PT-zs-ezETH, PT-Karak-sUSDe, ...).

    A market missing implied APY / expiry / positive depth, or not a target, returns None (skipped)."""
    if not isinstance(m, dict):
        return None
    pt = m.get("pt")
    pt_dict = pt if isinstance(pt, dict) else {}
    details = m.get("details") if isinstance(m.get("details"), dict) else {}

    # underlying: prefer the active-endpoint `name` (clean underlying symbol), then the legacy PT symbol
    underlying = pph._match_underlying_by_name(m.get("name") or "")
    if underlying is None:
        symbol = pt_dict.get("symbol") or m.get("symbol") or ""
        underlying = pph._match_underlying(symbol)
    if underlying is None:
        return None

    implied = details.get("impliedApy") if "impliedApy" in details else m.get("impliedApy")
    expiry = (m.get("expiry") or "")[:10]
    if implied is None or not expiry:
        return None  # incomplete market — skip (never fabricate)

    depth = _pendle_depth_usd(m)
    if depth is None:
        return None

    # market id: the market address (legacy dict) or the pt chain-address string (active), else symbol
    market_id = (
        m.get("address")
        or (pt if isinstance(pt, str) else pt_dict.get("address"))
        or pt_dict.get("symbol")
        or m.get("symbol")
        or f"{underlying}-{expiry}"
    )
    return underlying, str(market_id), implied, expiry, depth


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# 2) LendingRateFeed → RateQuote rows (venue = LENDING; SUPPLY + BORROW)
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
YIELDS_POOLS_URL = "https://yields.llama.fi/pools"
YIELDS_LENDBORROW_URL = "https://yields.llama.fi/lendBorrow"


class LendingRateFeed:
    """Money-market supply/borrow APRs → RateQuote rows (LENDING venue, two rows per pool: a
    LENDING_SUPPLY leg with the supply APR and a LENDING_BORROW leg with the borrow APR). Targets the
    USDC markets + the PT-collateral markets on Morpho / Euler / Aave, for the levered-carry leg.

    Source: the keyless DeFiLlama `yields/pools` (apy/apyBaseBorrow/totalSupplyUsd/...) joined with
    `yields/lendBorrow` (apyBaseBorrow / ltv / totalSupplyUsd / totalBorrowUsd → utilization). Pools
    are matched by (project, chain, symbol) like restaking_feed/btc_lending_feed.

    There is NO supply/borrow APR shaping or netting here — that is the engine's levered-carry math.
    We emit the raw rates as two honest RateQuote legs. fail-CLOSED: malformed payload RAISES; a pool
    that matches but lacks a needed field is SKIPPED; an empty result RAISES (nothing matched)."""

    def __init__(self, fetcher: Optional[Fetcher] = None):
        self._fetch = fetcher or _http_fetch

    def quotes(self, as_of: str) -> List[RateQuote]:
        d = _iso_date(as_of)
        pools = _validate_yields_pools(self._fetch(YIELDS_POOLS_URL))
        lend = _index_lendborrow(self._fetch(YIELDS_LENDBORROW_URL))
        rows: List[RateQuote] = []
        for sel in config.LENDING_TARGETS:
            best = _match_lending_pool(pools, sel)
            if best is None:
                continue
            pool_id = best.get("pool")
            lb = lend.get(pool_id, {}) if isinstance(pool_id, str) else {}
            supply_apr = best.get("apyBase")
            if supply_apr is None:
                supply_apr = best.get("apy")
            borrow_apr = best.get("apyBaseBorrow")
            if borrow_apr is None:
                borrow_apr = lb.get("apyBaseBorrow")
            tvl = best.get("tvlUsd")
            total_supply = lb.get("totalSupplyUsd")
            total_borrow = lb.get("totalBorrowUsd")
            ltv = lb.get("ltv")
            cap = lb.get("debtCeilingUsd")
            util = _utilization(total_supply, total_borrow)
            depth = _D(tvl) if isinstance(tvl, (int, float)) else D0
            sla = config.redemption_sla_seconds(str(sel["underlying"]).lower())
            base = dict(
                underlying=str(sel["underlying"]).lower(),
                kind=UnderlyingKind(sel["kind"]),
                venue=RateVenue.LENDING,
                protocol=str(sel["project"]),
                market_id=str(pool_id or f"{sel['project']}:{sel['symbol']}"),
                tenor_seconds=0,  # money-market legs are perpetual (no fixed maturity)
                as_of=d,
                tvl_usd=depth,
                exit_liquidity_usd=exit_liquidity_usd(depth, sla),
                hedge_available=False,
                utilization=util,
                ltv=_D(ltv) if isinstance(ltv, (int, float)) else D0,
                cap_headroom_usd=_cap_headroom(cap, total_borrow),
            )
            if supply_apr is not None:
                rows.append(RateQuote(quoted_rate=_apr_to_decimal(supply_apr),
                                      market_id=base["market_id"] + ":supply", **{k: v for k, v in base.items() if k != "market_id"}))
            if borrow_apr is not None:
                rows.append(RateQuote(quoted_rate=_apr_to_decimal(borrow_apr),
                                      market_id=base["market_id"] + ":borrow", **{k: v for k, v in base.items() if k != "market_id"}))
        if not rows:
            raise FeedError("lending: no target pool matched with a usable rate")
        rows.sort(key=lambda q: (q.underlying, q.market_id))
        return rows


def _validate_yields_pools(payload: object) -> List[dict]:
    if not isinstance(payload, dict):
        raise FeedError(f"yields pools: expected object, got {type(payload).__name__}")
    if payload.get("status") != "success":
        raise FeedError(f"yields pools: status={payload.get('status')!r}")
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise FeedError("yields pools: 'data' missing or empty")
    return data


def _index_lendborrow(payload: object) -> Dict[str, dict]:
    """yields/lendBorrow → {pool_id: row}. fail-CLOSED on a non-list payload; rows missing a pool id
    are skipped."""
    if isinstance(payload, dict):
        payload = payload.get("data", payload)
    if not isinstance(payload, list):
        raise FeedError(f"yields lendBorrow: expected list, got {type(payload).__name__}")
    out: Dict[str, dict] = {}
    for row in payload:
        if isinstance(row, dict) and isinstance(row.get("pool"), str):
            out[row["pool"]] = row
    return out


def _match_lending_pool(pools: List[dict], sel: dict) -> Optional[dict]:
    """Highest-TVL pool matching project+chain+symbol (symbol compared upper-case), or None."""
    proj, chain, sym = sel["project"], sel["chain"], str(sel["symbol"]).upper()
    best, best_tvl = None, float("-inf")
    for p in pools:
        if not isinstance(p, dict):
            continue
        if p.get("project") != proj or p.get("chain") != chain:
            continue
        if (p.get("symbol") or "").upper() != sym:
            continue
        tvl = p.get("tvlUsd")
        tvl = float(tvl) if isinstance(tvl, (int, float)) else 0.0
        if tvl > best_tvl:
            best_tvl, best = tvl, p
    return best


def _apr_to_decimal(apr) -> Decimal:
    """DeFiLlama APRs are in PERCENT (e.g. 4.5 == 4.5%) → Decimal fraction."""
    return _D(apr) / Decimal(100)


def _utilization(total_supply, total_borrow) -> Decimal:
    if not isinstance(total_supply, (int, float)) or total_supply <= 0:
        return D0
    if not isinstance(total_borrow, (int, float)) or total_borrow < 0:
        return D0
    u = _D(total_borrow) / _D(total_supply)
    return u if u <= D1 else D1


def _cap_headroom(cap, total_borrow) -> Decimal:
    if not isinstance(cap, (int, float)) or cap <= 0:
        return D0
    used = _D(total_borrow) if isinstance(total_borrow, (int, float)) and total_borrow > 0 else D0
    head = _D(cap) - used
    return head if head > D0 else D0


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# 3) BorosFeed → RateQuote rows (venue = BOROS) + honest hedge_available
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
class BorosFeed:
    """The forward-funding / Boros hedge surface. HONESTY IS THE POINT (brief §3): a BasisHedge can
    only exist if there is a real, keyless, executable forward-funding venue. As of this build NO such
    clean keyless Boros endpoint is available to the desk (Boros markets require authenticated /
    SDK-gated access), so `hedge_available()` returns False for EVERY underlying and `quotes()` emits
    NO executable BOROS rows. This is deliberate, not a stub: the engine reads this flag to (a) make
    BasisHedge unavailable and (b) apply the LARGER funding-flip haircut on FixedCarry. A fabricated
    "hedge available" here would silently understate risk — exactly the failure mode the desk forbids.

    The 5-venue CEX/DEX funding feed (data/funding_feed.py) is the funding SIGNAL — it drives
    funding_neg_frac_90d in UnderlyingRiskFeed — but it is NOT an executable hedge for the desk, so it
    is intentionally kept OUT of the BOROS venue (it would be a CEX_FUNDING_SIG signal venue, which the
    contract enum does not expose as executable).

    If/when a keyless Boros endpoint is wired, set HEDGE_ENABLED + populate quotes(); the flag becomes
    honestly True per-underlying and the engine re-enables BasisHedge with no other change."""

    HEDGE_ENABLED = False  # flip ONLY when a real keyless forward-funding venue is wired + tested

    def __init__(self, fetcher: Optional[Fetcher] = None):
        self._fetch = fetcher or _http_fetch

    def hedge_available(self, underlyings: List[str]) -> Dict[str, bool]:
        """Per-underlying hedge flag. Honest: all False until HEDGE_ENABLED + a probed venue."""
        return {str(u).lower(): bool(self.HEDGE_ENABLED) for u in underlyings}

    def quotes(self, as_of: str) -> List[RateQuote]:
        """Executable forward-funding (BOROS) rows. Empty while no keyless venue exists (fail-CLOSED:
        we emit nothing rather than a fabricated forward rate)."""
        _iso_date(as_of)  # validate as_of even on the empty path (deterministic, no clock)
        return []


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# 4) UnderlyingRiskFeed → UnderlyingRisk per underlying
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
class UnderlyingRiskFeed:
    """The per-underlying risk surface. Combines the live structural facts with documented constants:

      nav_redemption_value / market_price / peg_distance — from the protocol NAV ref vs the secondary
        market price. For staked-ETH underlyings (LST/LRT) the NAV ref is the X/ETH ratio's trailing
        peak (a value-accruing wrapper drifts ABOVE 1.0, so depeg is measured as DRAWDOWN-from-peak,
        not absolute distance from 1.0 — same false-depeg remedy as config.py / eth_lst_neutral). For
        synth/RWA stables the NAV ref is 1.0 (USD).
      peg_vol_30d — 30d downside-drift vol of the (smoothed) ratio / price (REUSES price_feed history).
      funding_neg_frac_90d — fraction of last 90d with NEGATIVE 8h funding (REUSES the 5-venue
        FundingFeed median — the SIGNAL).
      redemption_sla_seconds / reserve_fund_ratio / oracle_kind / oracle_staleness_seconds /
        nested_protocol_count — documented per-underlying constants in config.py (reserve_fund_ratio
        notes "pull live later"; oracle staleness is best-effort).

    fail-CLOSED: a requested underlying with no resolvable price/peg signal RAISES (we mark it, never
    fabricate a benign peg=0). Injected feeds in tests; real feeds default. as_of is explicit."""

    def __init__(
        self,
        price_feed=None,
        restaking_feed=None,
        funding_feed=None,
        fetcher: Optional[Fetcher] = None,
    ):
        # lazy-import the data feeds so a missing optional dep doesn't break import of the contracts
        self._price = price_feed
        self._restaking = restaking_feed
        self._funding = funding_feed
        self._fetcher = fetcher

    def _ensure_feeds(self):
        if self._price is None:
            from spa_core.strategy_lab.data.price_feed import PriceFeed
            self._price = PriceFeed(fetcher=self._fetcher) if self._fetcher else PriceFeed()
        if self._funding is None:
            from spa_core.strategy_lab.data.funding_feed import FundingFeed
            self._funding = FundingFeed(fetcher=self._fetcher) if self._fetcher else FundingFeed()

    def risks(self, as_of: str, underlyings: List[str]) -> Dict[str, UnderlyingRisk]:
        """{underlying(lower) -> UnderlyingRisk} for the requested underlyings at `as_of`."""
        d = _iso_date(as_of)
        self._ensure_feeds()
        # one funding pull → funding_neg_frac_90d (shared systemic signal across underlyings)
        fneg = self._funding_neg_frac_90d(d)
        # one price-history pull (90d window ending as_of) for the staked-ETH peg/vol signals
        ratio_hist = self._ratio_history(d)
        out: Dict[str, UnderlyingRisk] = {}
        for raw_u in underlyings:
            u = str(raw_u).lower()
            kind = config.underlying_kind(u)
            nav, mkt, peg, vol = self._peg_signals(u, kind, ratio_hist)
            out[u] = UnderlyingRisk(
                underlying=u,
                as_of=d,
                nav_redemption_value=nav,
                market_price=mkt,
                peg_distance=peg,
                peg_vol_30d=vol,
                redemption_sla_seconds=config.redemption_sla_seconds(u),
                reserve_fund_ratio=_D(config.reserve_fund_ratio(u)),
                funding_neg_frac_90d=_D(round(fneg, 6)),
                oracle_kind=config.oracle_kind(u),
                oracle_staleness_seconds=config.oracle_staleness_seconds(u),
                nested_protocol_count=config.nested_protocol_count(u),
                top_borrower_share=_D(config.top_borrower_share(u)),
            )
        return out

    # ── funding signal ───────────────────────────────────────────────────────────────────────────
    def _funding_neg_frac_90d(self, as_of: str) -> float:
        """Fraction of the 90 calendar days ending `as_of` with NEGATIVE median 8h funding.
        fail-CLOSED: an empty funding series raises (no fabricated 0.0)."""
        start = (datetime.date.fromisoformat(as_of) - datetime.timedelta(days=120)).isoformat()
        series = self._funding.history(start_date=start, end_date=as_of)
        if not series:
            raise FeedError("underlying-risk: empty funding series (cannot compute funding_neg_frac)")
        dates = sorted(dd for dd in series if dd <= as_of)
        tail = dates[-90:]
        if not tail:
            raise FeedError("underlying-risk: no funding days <= as_of")
        neg = sum(1 for dd in tail if series[dd] < 0)
        return neg / len(tail)

    # ── staked-ETH peg signals (REUSE price_feed ratio history) ───────────────────────────────────
    def _ratio_history(self, as_of: str) -> Dict[str, Dict[str, float]]:
        """{token -> {date -> X/ETH ratio}} for the 90d window ending as_of. Empty dict if the price
        feed cannot serve the window (the per-underlying signal then fail-CLOSEs for ETH kinds)."""
        start = (datetime.date.fromisoformat(as_of) - datetime.timedelta(days=120)).isoformat()
        try:
            return self._price.history_ratios(start_date=start, end_date=as_of)
        except Exception:  # noqa: BLE001 — propagated as a fail-CLOSED at the per-underlying level
            return {}

    def _peg_signals(
        self, underlying: str, kind: UnderlyingKind, ratio_hist: Dict[str, Dict[str, float]]
    ) -> Tuple[Decimal, Decimal, Decimal, Decimal]:
        """(nav_redemption_value, market_price, peg_distance, peg_vol_30d).

        STABLE_RWA / STABLE_SYNTH: NAV = 1.0 USD; market = 1.0 (the desk's stable-depeg veto reads the
        DEBT/quote stable separately — here the synth/RWA carry token's own peg is modelled at par with
        the structural haircuts carrying the tail). peg_distance/vol = 0 at par. (Documented: a live
        secondary-market stable price can be wired later via price_feed; until then par is the honest,
        non-fabricated reference and the funding/peg haircuts carry the synth tail.)

        LST / LRT: NAV = trailing-PEAK of the smoothed X/ETH ratio (value-accruing → depeg is DD from
        peak); market = latest smoothed ratio; peg_distance = max(0, (peak-latest)/peak); peg_vol_30d =
        downside-drift vol of the smoothed ratio. fail-CLOSED: no ratio series for an ETH underlying
        RAISES (we never fabricate peg=0 for a restaking token whose data is missing)."""
        if kind in (UnderlyingKind.STABLE_RWA, UnderlyingKind.STABLE_SYNTH):
            return D1, D1, D0, D0
        # LST / LRT — map the underlying symbol to the price_feed ratio key
        token = config.ratio_token_for(underlying)
        series = ratio_hist.get(token, {})
        if not series:
            raise FeedError(
                f"underlying-risk: no X/ETH ratio history for {underlying} ({token}) — fail-CLOSED")
        dates = sorted(series)
        vals = [series[dd] for dd in dates]
        smoothed = _trailing_median(vals, config.RATIO_MEDIAN_WINDOW)
        latest = smoothed[-1]
        peak = max(smoothed[-config.RATIO_PEAK_WINDOW:]) if smoothed else latest
        if peak <= 0:
            raise FeedError(f"underlying-risk: non-positive ratio peak for {underlying}")
        peg_distance = max(0.0, (peak - latest) / peak)
        vol = _downside_drift_vol(smoothed[-config.DRIFT_VOL_WINDOW:])
        return (_D(round(peak, 8)), _D(round(latest, 8)),
                _D(round(peg_distance, 8)), _D(round(vol, 8)))


def _trailing_median(vals: List[float], window: int) -> List[float]:
    """Trailing-median smoothing (the same de-noise as config.RATIO_MEDIAN_WINDOW)."""
    out: List[float] = []
    for i in range(len(vals)):
        w = vals[max(0, i - window + 1): i + 1]
        out.append(float(statistics.median(w)))
    return out


def _downside_drift_vol(vals: List[float]) -> float:
    """Std of the NEGATIVE day-over-day log-ish returns of the ratio (downside-drift proxy). 0 if
    fewer than 2 points or no down moves (honest: a flat/up series has no measured downside drift)."""
    if len(vals) < 2:
        return 0.0
    downs: List[float] = []
    for a, b in zip(vals[:-1], vals[1:]):
        if a > 0:
            r = (b - a) / a
            if r < 0:
                downs.append(r)
    if len(downs) < 2:
        return 0.0
    return float(statistics.pstdev(downs))


# ═══════════════════════════════════════════════════════════════════════════════════════════════════
# build_surface — the RateSurface assembler (ONE function: backtest + live)
# ═══════════════════════════════════════════════════════════════════════════════════════════════════
def build_surface(
    as_of: Optional[str] = None,
    *,
    pendle_feed: Optional[PendleMarketFeed] = None,
    lending_feed: Optional[LendingRateFeed] = None,
    boros_feed: Optional[BorosFeed] = None,
    risk_feed: Optional[UnderlyingRiskFeed] = None,
    deep: Optional[dict] = None,
    include_lending: bool = True,
    cache: bool = False,
    out_path: Optional[Path] = None,
) -> Tuple[List[RateQuote], Dict[str, UnderlyingRisk]]:
    """Assemble the RateSurface = (list[RateQuote], {underlying -> UnderlyingRisk}) at `as_of`.

    SAME function for backtest and live (one source of truth):
      • as_of given + `deep` dataset given/loaded → BACKTEST: PT quotes come from the deep history for
        that historical day.
      • as_of None → LIVE: as_of = the latest UTC date; PT quotes come from the /active endpoint.

    Pipeline (each step pure-given-feeds):
      1. BorosFeed.hedge_available(...) → the honest per-underlying hedge flag (drives both the PT row
         flag AND the engine's BasisHedge availability).
      2. PendleMarketFeed → PT RateQuote rows (the hedge flag stamped in).
      3. (optional) LendingRateFeed → LENDING supply/borrow rows for the levered/lending legs.
      4. UnderlyingRiskFeed → one UnderlyingRisk per underlying present in the quotes.

    fail-CLOSED throughout: a feed raising propagates (we never emit a half-fabricated surface). The
    quotes are sorted deterministically. If `cache`, the surface is written atomically to
    data/rates_desk/rate_surface.json."""
    live = as_of is None
    d = _iso_date(as_of) if as_of is not None else datetime.datetime.now(datetime.timezone.utc).date().isoformat()

    pendle_feed = pendle_feed or PendleMarketFeed()
    lending_feed = lending_feed or LendingRateFeed()
    boros_feed = boros_feed or BorosFeed()
    risk_feed = risk_feed or UnderlyingRiskFeed()

    # the universe of underlyings the desk follows (drives the honest hedge map + risk surface)
    universe = sorted(set(config.UNDERLYING_KINDS) | set(u.lower() for u in pph.TARGETS))
    hedge_map = boros_feed.hedge_available(universe)
    sla_map = {u: config.redemption_sla_seconds(u) for u in universe}

    quotes: List[RateQuote] = []
    if live:
        quotes.extend(pendle_feed.quotes_live(d, hedge_by_underlying=hedge_map, sla_by_underlying=sla_map))
    else:
        if deep is None:
            deep = pph.load()
        quotes.extend(pendle_feed.quotes_for_date(d, deep, hedge_by_underlying=hedge_map, sla_by_underlying=sla_map))

    if include_lending:
        quotes.extend(lending_feed.quotes(d))

    # BOROS executable rows (empty until a keyless forward-funding venue exists)
    quotes.extend(boros_feed.quotes(d))

    quotes.sort(key=lambda q: (q.venue.value, q.underlying, q.market_id))

    # the risk surface covers every underlying that actually appears in the quotes
    quote_underlyings = sorted({q.underlying for q in quotes})
    risks: Dict[str, UnderlyingRisk] = risk_feed.risks(d, quote_underlyings) if quote_underlyings else {}

    if cache:
        _cache_surface(out_path or _SURFACE_OUT, d, live, quotes, risks, hedge_map)
    return quotes, risks


# ── caching (atomic; PURE serialization of the contract dataclasses) ───────────────────────────────
def _quote_to_dict(q: RateQuote) -> dict:
    return {
        "underlying": q.underlying,
        "kind": q.kind.value,
        "venue": q.venue.value,
        "protocol": q.protocol,
        "market_id": q.market_id,
        "tenor_seconds": q.tenor_seconds,
        "as_of": q.as_of,
        "quoted_rate": str(q.quoted_rate),
        "tvl_usd": str(q.tvl_usd),
        "exit_liquidity_usd": str(q.exit_liquidity_usd),
        "hedge_available": q.hedge_available,
        "utilization": str(q.utilization),
        "ltv": str(q.ltv),
        "cap_headroom_usd": str(q.cap_headroom_usd),
    }


def _risk_to_dict(r: UnderlyingRisk) -> dict:
    return {
        "underlying": r.underlying,
        "as_of": r.as_of,
        "nav_redemption_value": str(r.nav_redemption_value),
        "market_price": str(r.market_price),
        "peg_distance": str(r.peg_distance),
        "peg_vol_30d": str(r.peg_vol_30d),
        "redemption_sla_seconds": r.redemption_sla_seconds,
        "reserve_fund_ratio": str(r.reserve_fund_ratio),
        "funding_neg_frac_90d": str(r.funding_neg_frac_90d),
        "oracle_kind": r.oracle_kind,
        "oracle_staleness_seconds": r.oracle_staleness_seconds,
        "nested_protocol_count": r.nested_protocol_count,
        "top_borrower_share": str(r.top_borrower_share),
    }


def _cache_surface(path: Path, as_of: str, live: bool, quotes, risks, hedge_map) -> None:
    obj = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "as_of": as_of,
        "mode": "live" if live else "backtest",
        "hedge_available": hedge_map,
        "quotes": [_quote_to_dict(q) for q in quotes],
        "underlying_risk": {u: _risk_to_dict(r) for u, r in sorted(risks.items())},
    }
    _io.atomic_write_json(path, obj, indent=1)


if __name__ == "__main__":  # manual real-network smoke test (run on the Mac)
    import socket

    socket.setdefaulttimeout(30)
    qs, rs = build_surface(as_of=None, include_lending=True, cache=True)
    print(f"LIVE surface: {len(qs)} RateQuote rows, {len(rs)} underlyings")
    hedge_cov = sum(1 for q in qs if q.hedge_available)
    print(f"hedge_available rows: {hedge_cov}/{len(qs)} (Boros keyless venue: "
          f"{'ON' if BorosFeed.HEDGE_ENABLED else 'OFF — all False, honest'})")
    by_venue: Dict[str, int] = {}
    for q in qs:
        by_venue[q.venue.value] = by_venue.get(q.venue.value, 0) + 1
    print(f"by venue: {by_venue}")
    if qs:
        s = qs[0]
        print(f"sample: {s.underlying} {s.venue.value} rate={s.quoted_rate} "
              f"tenor_d={s.tenor_seconds // 86400} exit=${s.exit_liquidity_usd}")
    for u, r in sorted(rs.items()):
        print(f"  {u:>8}: peg={r.peg_distance} vol30={r.peg_vol_30d} "
              f"fneg90={r.funding_neg_frac_90d} sla_d={r.redemption_sla_seconds // 86400} "
              f"nested={r.nested_protocol_count}")
