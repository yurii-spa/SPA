"""
spa_core/strategy_lab/aggressive_lab/feeds.py — the REAL-DATA snapshot builder for the lab.

This is the module that makes the Aggressive Lab's comparison HONEST: every accrual is driven by a
MarketSnapshot whose fields come from LIVE keyless feeds, NOT mock data. (The existing tournament's
trustworthy:false flaw is exactly mock-driven accrual — this lab must not repeat it.)

It augments the strategy_lab MarketSnapshot with the aggressive-roster-specific defi_apy keys:

    defi_apy["susde"]            ← Ethena sUSDe staking APY        (DeFiLlama yields)
    defi_apy["pendle_pt_susde"]  ← Pendle PT-sUSDe implied yield   (rates_desk pendle history/surface)
    defi_apy["pendle_yt_susde"]  ← Pendle YT-sUSDe implied yield   (YT yield ≈ implied/(1−PTprice) proxy)
    defi_apy["points"]           ← ZERO by owner decision 2026-08-16 (see DEFAULT_POINTS_APY)
    defi_apy["aave_v3_wsteth"]   ← wstETH supply APY               (DeFiLlama, PINNED pool, fallback)
  plus the standard ETH price / LRT ratios / restaking APY / funding the base feeds already give.

TWO MODES, ONE SHAPE (so backtest and live are apples-to-apples):
  • LIVE:     build_live_snapshot(as_of=None) — the most-recent real values from the live feeds.
  • HISTORY:  historical_snapshots(start, end) — a per-UTC-day series replayed from the deep Pendle
              dataset (2024–2026) + the deep funding history. THIS carries the real stress windows.

FAIL-CLOSED everywhere: a feed that raises / returns nothing → the corresponding defi_apy key is
simply ABSENT (added to snapshot.gaps), so a strategy requiring it FAILS CLOSED (no fabricated
accrual). We NEVER substitute a hardcoded yield.

Feeds are INJECTABLE (the test seam): pass susde_apy_series / pt_series / funding_series / etc. to
drive the builder from fixtures with zero network. Default = the real live feeds.

stdlib-only, deterministic, fail-CLOSED. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from spa_core.strategy_lab.base import InvalidDataError, MarketSnapshot

# ══════════════════════════════════════════════════════════════════════════════════════════════════
# POINTS YIELD IS ZERO. Owner decision 2026-08-16 (docs/AGGRESSIVE_PANEL_FEEDS.md §3).
#
# This used to be 0.06 — a flat 6% a year accrued onto `points_farm` EVERY day the panel ran, from
# a literal typed into this file. It was defended in the old comment as "a modelling assumption, not
# a fabricated market price". That defence does not survive the measurement: there is no public feed
# for points yield and there cannot be one, because points are not quoted until the conversion ratio
# is disclosed. A number nobody can check, compounding daily into a ranked track, IS a fabricated
# number (invariant 2) — and it is worse than a gap, because a gap fails closed and is visible while
# a literal quietly wins the tournament.
#
# The rule now: POINTS ARE NOT INCOME UNTIL THEY ARE DISTRIBUTED. Undistributed points have no
# price; the honest carry of holding them is zero. When a distribution actually lands, it arrives as
# a realized token amount at a quoted price — that is a real feed, and it can be wired here then.
#
# The BOOK STAYS on the panel (owner's explicit choice): its risk shape, its tail and its place in
# the roster stay measurable. Only its invented return is gone.
DEFAULT_POINTS_APY = 0.0
# ETH/stable LP trading-fee APY (S78, #96). Config-modelled default (like points) — flagged as a
# MODEL input, not a live feed yet; the VALIDATION step is to wire this to a live DeFiLlama ETH/stable
# pool apyBase. The IL/directional TAIL is already REAL (marked off the live ETH price path).
DEFAULT_LP_FEE_APY = 0.18


def _utc_today() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# PINNED-POOL FEED (ADR-064) — keyless DeFiLlama yields resolved by pool UUID, never by name.
#
# WHY A PIN AND NOT A NAME MATCH. `defi_apy["aave_v3_wsteth"]` is the fallback accrual source for
# levered_restaking / leverage_loop when restaking_apy["steth"] has a hole. It was never produced by
# anything — it lived only in this module's docstring, so the fallback never fired and the books
# failed closed on the exact days they needed it. Wiring it by project/chain/symbol would repeat the
# failure ADR-064 was written for: several pools answer to the same hints, "best TVL wins" picks a
# different one between runs, and the record shows nothing. A pinned UUID is a stable identity; the
# recorded chain/project/symbol next to it is the receipt that proves the UUID still means what it
# meant when it was taken.
#
# fail-CLOSED, three ways: no pin → refuse; pin not present in the live payload → refuse; pin
# present but describing a DIFFERENT pool than the receipt says → refuse. Never a fuzzy fallback.
# ══════════════════════════════════════════════════════════════════════════════════════════════════
POOLS_URL = "https://yields.llama.fi/pools"
CHART_URL = "https://yields.llama.fi/chart/{pool}"

#: git-tracked pin registry. Operators fill a null pool_id from the live feed; no code change.
PINNED_POOLS_FILE = Path(__file__).with_name("pinned_pools.json")

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                      r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def load_pinned_pools(path: Optional[Path] = None) -> Dict[str, dict]:
    """The pin registry as ``{key: {pool_id, project, chain, symbol, ...}}``.

    fail-SAFE on read (a missing/corrupt file yields an empty registry, which then fails CLOSED at
    resolution time — an unreadable config must never become a licence to guess a pool)."""
    p = Path(path) if path is not None else PINNED_POOLS_FILE
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — an unreadable registry is "no pins", never "any pool will do"
        return {}
    pools = doc.get("pools") if isinstance(doc, dict) else None
    if not isinstance(pools, dict):
        return {}
    return {k: v for k, v in pools.items() if isinstance(v, dict)}


def unpinned_keys(path: Optional[Path] = None) -> List[str]:
    """Keys DECLARED in the registry whose pool_id is still null — i.e. the values that must be
    substituted once, off the live feed, on a machine with egress. Named out loud so the gap is a
    line in a report rather than a silent absence."""
    return sorted(k for k, rec in load_pinned_pools(path).items()
                  if not isinstance(rec.get("pool_id"), str))


def _validate_pools_payload(payload: object) -> List[dict]:
    if not isinstance(payload, dict):
        raise InvalidDataError(f"yields pools: expected object, got {type(payload).__name__}")
    if payload.get("status") != "success":
        raise InvalidDataError(f"yields pools: status={payload.get('status')!r}")
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise InvalidDataError("yields pools: 'data' missing or empty")
    return data


class PinnedPoolFeed:
    """One DeFiLlama pool's APY, resolved ONLY by its pinned UUID.

    ``key`` indexes the pin registry (``pinned_pools.json``). ``pins`` / ``pins_path`` override the
    registry (tests, and the operator's substitution path). ``fetcher`` is ``url -> parsed_json``
    (injected in tests; the default is the repo's stdlib gzip fetcher).

    All methods raise :class:`InvalidDataError` rather than returning a substitute value.
    """

    def __init__(
        self,
        key: str,
        *,
        pins: Optional[Dict[str, dict]] = None,
        pins_path: Optional[Path] = None,
        fetcher: Optional[Callable[[str], Any]] = None,
    ) -> None:
        self.key = key
        if pins is not None:
            self._pins = pins
        else:
            self._pins = load_pinned_pools(pins_path)
        self._fetch = fetcher
        if self._fetch is None:
            from spa_core.strategy_lab.data._http import http_fetch
            self._fetch = http_fetch

    # ── the pin itself ────────────────────────────────────────────────────────────────────────────
    def pool_id(self) -> str:
        """The pinned UUID. Refuses on a missing/null/malformed pin — an unpinned key has no value,
        and MUST NOT quietly degrade to a name match (that is the ADR-064 failure)."""
        rec = self._pins.get(self.key)
        if not isinstance(rec, dict):
            raise InvalidDataError(
                f"aggressive_lab: pool key {self.key!r} is not declared in the pin registry "
                f"({PINNED_POOLS_FILE.name}) — refusing to resolve it by project/chain/symbol")
        pid = rec.get("pool_id")
        if not isinstance(pid, str) or not _UUID_RE.match(pid):
            raise InvalidDataError(
                f"aggressive_lab: pool key {self.key!r} has no pinned DeFiLlama UUID "
                f"(pool_id={pid!r}). Read it off https://yields.llama.fi/pools on a machine with "
                f"egress and write it into {PINNED_POOLS_FILE.name}; until then this feed is a "
                f"declared GAP, not a guess (ADR-064, invariant 2)")
        return pid

    def _receipt_matches(self, pool: dict) -> Tuple[bool, str]:
        """The pin records what the UUID identified when it was taken. If the live row now says
        something else, the identity drifted — that is exactly the silent switch a pin exists to
        catch, so it is a refusal, not a warning."""
        rec = self._pins.get(self.key) or {}
        for field, live_key, fold in (("project", "project", str),
                                      ("chain", "chain", str),
                                      ("symbol", "symbol", lambda s: str(s).upper())):
            expected = rec.get(field)
            if expected is None:
                continue  # a receipt field the operator did not record cannot be checked
            actual = pool.get(live_key)
            if actual is None or fold(actual) != fold(expected):
                return False, f"{field}: pinned {expected!r} but feed says {actual!r}"
        return True, ""

    def _live_row(self) -> dict:
        pid = self.pool_id()
        for p in _validate_pools_payload(self._fetch(POOLS_URL)):
            if isinstance(p, dict) and p.get("pool") == pid:
                ok, why = self._receipt_matches(p)
                if not ok:
                    raise InvalidDataError(
                        f"aggressive_lab: pinned pool {pid} for {self.key!r} DRIFTED ({why}) — "
                        f"refusing to accrue on a pool that is no longer the pinned one")
                return p
        raise InvalidDataError(
            f"aggressive_lab: pinned pool {pid} for {self.key!r} is absent from the live feed — "
            f"fail-closed (no fuzzy substitute)")

    # ── values ────────────────────────────────────────────────────────────────────────────────────
    def apy(self) -> float:
        """Latest APY as a DECIMAL (DeFiLlama serves percent). Refuses on a missing/invalid apy."""
        row = self._live_row()
        apy = row.get("apy")
        if not isinstance(apy, (int, float)) or isinstance(apy, bool) or apy < 0:
            raise InvalidDataError(
                f"aggressive_lab: pinned pool for {self.key!r} has no usable apy ({apy!r})")
        return round(float(apy) / 100.0, 6)

    def history(self, start_date: str, end_date: str) -> Dict[str, float]:
        """``{ISO_date: apy_decimal}`` over ``[start_date, end_date]`` from ``/chart/{uuid}``.

        The UUID addresses the chart directly, so history needs no name matching at all. A day the
        pool itself has no point for is simply absent (a gap), never interpolated."""
        try:
            d0 = datetime.date.fromisoformat(start_date)
            d1 = datetime.date.fromisoformat(end_date)
        except ValueError as exc:
            raise InvalidDataError(
                f"aggressive_lab pinned history: bad date(s) {start_date!r}..{end_date!r}") from exc
        if d1 < d0:
            raise InvalidDataError(
                f"aggressive_lab pinned history: end {end_date} before start {start_date}")
        pid = self.pool_id()
        from spa_core.strategy_lab.data.restaking_feed import _parse_apy_chart
        chart = _parse_apy_chart(self._fetch(CHART_URL.format(pool=pid)), self.key)
        return {d: a for d, a in chart.items() if start_date <= d <= end_date}


# ──────────────────────────────────────────────────────────────────────────────────────────────────
# A small, self-contained source of the aggressive-specific yields. Each source returns either a
# per-date dict {date: apy_decimal} (history mode) or a scalar latest (live mode). All are injectable.
# ──────────────────────────────────────────────────────────────────────────────────────────────────
class AggressiveFeeds:
    """Builds augmented MarketSnapshots on REAL data.

    Injectable series (history mode) — each a {ISO_date: apy_decimal} or {ISO_date: value}:
        susde_apy_series, pt_susde_series, funding_series, restaking_series (per-symbol nested),
        eth_price_series, lrt_ratio_series (per-symbol nested), wsteth_apy_series, points_apy_series.
    If a series is omitted, the live feed is used (network); if the live feed raises, that field is a
    gap (fail-closed). points has no live market feed → modelled from points_apy (config) if enabled.
    """

    def __init__(
        self,
        *,
        susde_apy_series: Optional[Dict[str, float]] = None,
        pt_susde_series: Optional[Dict[str, float]] = None,
        funding_series: Optional[Dict[str, float]] = None,
        restaking_series: Optional[Dict[str, Dict[str, float]]] = None,
        eth_price_series: Optional[Dict[str, float]] = None,
        lrt_ratio_series: Optional[Dict[str, Dict[str, float]]] = None,
        wsteth_apy_series: Optional[Dict[str, float]] = None,
        points_apy: Optional[float] = None,
        enable_points: bool = True,
        pendle_pt_premium: float = 0.05,   # YT yield proxy: YT_apy ≈ PT_apy + this leverage premium
        live_loaders: Optional[Dict[str, Callable]] = None,
    ) -> None:
        self._susde = susde_apy_series
        self._pt = pt_susde_series
        self._funding = funding_series
        self._restaking = restaking_series
        self._eth = eth_price_series
        self._ratio = lrt_ratio_series
        # wstETH supply APY (the aave_v3_wsteth fallback key). Injected series in history mode;
        # live mode reads the "aave_v3_wsteth" loader (a PinnedPoolFeed.apy in production).
        self._wsteth = wsteth_apy_series
        self._points_apy = points_apy if points_apy is not None else DEFAULT_POINTS_APY
        self._enable_points = enable_points
        self._yt_premium = float(pendle_pt_premium)
        self._live = live_loaders or {}

    # ── history mode: the full per-day replay series (the 2024–2026 backtest) ─────────────────────
    def available_dates(self) -> List[str]:
        """Sorted union of dates across the injected series (history mode). Empty if none injected."""
        dates: set = set()
        for s in (self._susde, self._pt, self._funding, self._eth, self._wsteth):
            if s:
                dates.update(s.keys())
        for nested in (self._restaking, self._ratio):
            if nested:
                for inner in nested.values():
                    dates.update(inner.keys())
        return sorted(dates)

    def _snapshot_for(self, date: str) -> MarketSnapshot:
        """Assemble ONE day's augmented snapshot from the injected history series. A field whose
        series has no datapoint for `date` becomes a gap (fail-closed downstream)."""
        snap = MarketSnapshot(date=date)
        # standard fields
        if self._funding is not None:
            v = self._funding.get(date)
            if v is None:
                snap.gaps.add("funding_rate_8h")
            else:
                snap.funding_rate_8h = float(v)
        if self._eth is not None:
            v = self._eth.get(date)
            if v is None:
                snap.gaps.add("eth_price_usd")
            else:
                snap.eth_price_usd = float(v)
        if self._restaking is not None:
            snap.restaking_apy = {sym: s[date] for sym, s in self._restaking.items() if date in s}
        if self._ratio is not None:
            snap.lrt_eth_ratio = {sym: s[date] for sym, s in self._ratio.items() if date in s}
        # aggressive-specific defi_apy keys
        defi: Dict[str, float] = {}
        if self._susde is not None and date in self._susde:
            defi["susde"] = float(self._susde[date])
        if self._pt is not None and date in self._pt:
            pt = float(self._pt[date])
            defi["pendle_pt_susde"] = pt
            # YT yield proxy: a YT-sUSDe is a leveraged claim on sUSDe yield. Honest proxy: the PT
            # implied yield plus a modelled leverage premium (the YT trades richer than PT carry).
            defi["pendle_yt_susde"] = pt + self._yt_premium
        # wstETH supply APY (PINNED pool) — the fallback accrual source for the levered books. A day
        # with no datapoint is simply ABSENT (gap → the book fails closed), never back-filled.
        if self._wsteth is not None and date in self._wsteth:
            defi["aave_v3_wsteth"] = float(self._wsteth[date])
        if self._enable_points:
            defi["points"] = self._points_apy
        # LP fee APY (S78): config-modelled until wired to a live pool feed (#96). Tail is real (ETH path).
        defi["lp_eth_stable"] = float(getattr(self, "_lp_fee_apy", DEFAULT_LP_FEE_APY))
        snap.defi_apy = defi
        return snap

    def historical_snapshots(self, start: str, end: str) -> List[MarketSnapshot]:
        """Per-UTC-day augmented snapshots over [start, end] from the injected history series.
        Ascending, one per calendar day that has ANY datapoint. fail-CLOSED: if no series was
        injected, raises InvalidDataError (we will not fabricate a backtest from nothing)."""
        dates = [d for d in self.available_dates() if start <= d <= end]
        if not dates:
            raise InvalidDataError(
                f"aggressive_lab: no real history datapoints in [{start}, {end}] — refusing to "
                f"fabricate a backtest (inject real series or load the deep Pendle/funding history)"
            )
        return [self._snapshot_for(d) for d in dates]

    # ── live mode: the most-recent real values (the forward paper tick) ───────────────────────────
    def build_live_snapshot(self, as_of: Optional[str] = None) -> MarketSnapshot:
        """One LIVE augmented snapshot. Each field is pulled from its live loader (or injected
        scalar); a loader that raises → that field is a gap (fail-closed). NEVER a hardcoded yield."""
        day = as_of or _utc_today()
        snap = MarketSnapshot(date=day)
        defi: Dict[str, float] = {}

        def _try(field_setter, loader_key, gap_name):
            loader = self._live.get(loader_key)
            if loader is None:
                return
            try:
                field_setter(loader())
            except Exception:  # noqa: BLE001 — a failing live loader is an honest gap, never a fake
                snap.gaps.add(gap_name)

        # If history series are injected, take their latest as the "live" value (test convenience).
        if self._susde:
            defi["susde"] = float(self._susde[max(self._susde)])
        else:
            _try(lambda v: defi.__setitem__("susde", float(v)), "susde", "defi_apy.susde")
        if self._pt:
            pt = float(self._pt[max(self._pt)])
            defi["pendle_pt_susde"] = pt
            defi["pendle_yt_susde"] = pt + self._yt_premium
        else:
            def _set_pt(v):
                pt = float(v)
                defi["pendle_pt_susde"] = pt
                defi["pendle_yt_susde"] = pt + self._yt_premium
            _try(_set_pt, "pendle_pt", "defi_apy.pendle_pt_susde")
        if self._funding:
            snap.funding_rate_8h = float(self._funding[max(self._funding)])
        else:
            _try(lambda v: setattr(snap, "funding_rate_8h", float(v)), "funding", "funding_rate_8h")
        if self._eth:
            snap.eth_price_usd = float(self._eth[max(self._eth)])
        else:
            _try(lambda v: setattr(snap, "eth_price_usd", float(v)), "eth_price", "eth_price_usd")
        if self._restaking:
            snap.restaking_apy = {sym: s[max(s)] for sym, s in self._restaking.items() if s}
        elif "restaking" in self._live:
            try:
                snap.restaking_apy = dict(self._live["restaking"]())
            except Exception:  # noqa: BLE001
                snap.gaps.add("restaking_apy")
        if self._ratio:
            snap.lrt_eth_ratio = {sym: s[max(s)] for sym, s in self._ratio.items() if s}
        elif "lrt_ratio" in self._live:
            try:
                snap.lrt_eth_ratio = dict(self._live["lrt_ratio"]())
            except Exception:  # noqa: BLE001
                snap.gaps.add("lrt_eth_ratio")
        # wstETH supply APY (PINNED pool, ADR-064). In production the loader is a
        # PinnedPoolFeed("aave_v3_wsteth").apy — it RAISES while the pin is null, which lands here
        # as an honest gap rather than a number.
        if self._wsteth:
            defi["aave_v3_wsteth"] = float(self._wsteth[max(self._wsteth)])
        else:
            _try(lambda v: defi.__setitem__("aave_v3_wsteth", float(v)),
                 "aave_v3_wsteth", "defi_apy.aave_v3_wsteth")
        if self._enable_points:
            defi["points"] = self._points_apy
        # LP fee APY (S78): config-modelled until wired to a live pool feed (#96). Tail is real (ETH path).
        defi["lp_eth_stable"] = float(getattr(self, "_lp_fee_apy", DEFAULT_LP_FEE_APY))

        snap.defi_apy = defi
        return snap


# ──────────────────────────────────────────────────────────────────────────────────────────────────
# Real deep-history loader: reuse the rates_desk Pendle PT dataset (2024–2026, real implied yields)
# to build the sUSDe PT implied-yield series — the backbone of the real backtest stress windows.
# ──────────────────────────────────────────────────────────────────────────────────────────────────
def default_live_loaders() -> Dict[str, Callable]:
    """The production live-loader map for the keys THIS module owns.

    Kept as a separate constructor (rather than a default inside ``AggressiveFeeds.__init__``) so a
    test never touches the network by accident: a bare ``AggressiveFeeds()`` still has NO loaders.
    While ``aave_v3_wsteth`` is unpinned the loader raises, which the builder records as a gap."""
    return {"aave_v3_wsteth": PinnedPoolFeed("aave_v3_wsteth").apy}


def load_wsteth_apy_history(start: str, end: str, *, fetcher: Optional[Callable] = None
                            ) -> Dict[str, float]:
    """``{date: apy_decimal}`` for the PINNED wstETH supply pool over the window — the history-mode
    source for ``wsteth_apy_series``. Raises while the pin is null (fail-CLOSED)."""
    return PinnedPoolFeed("aave_v3_wsteth", fetcher=fetcher).history(start, end)


def load_real_susde_history() -> Tuple[Dict[str, float], Dict[str, float]]:
    """Return (pt_susde_series, susde_apy_series) as {date: apy_decimal} from the REAL deep Pendle
    dataset (spa_core.strategy_lab.rates_desk.pendle_pt_history). For each UTC day we take the
    sUSDe PT market that is live that day (the one with most TVL if several overlap) and use its
    real implied_yield as the PT yield; the underlying_yield (when present) is the sUSDe staking APY.

    fail-CLOSED: if the deep dataset is missing/empty → InvalidDataError (we never fabricate). This
    is the load-bearing 'REAL data, not mock' source for the backtest."""
    from spa_core.strategy_lab.rates_desk import pendle_pt_history as pph

    deep = pph.load()  # raises FileNotFoundError/ValueError if missing/malformed (fail-closed)
    markets = deep.get("markets") or {}
    # collect per-day candidate points across all sUSDe markets, keep the highest-TVL one per day
    pt_by_day: Dict[str, Tuple[float, float]] = {}   # date -> (tvl, implied_yield)
    susde_by_day: Dict[str, Tuple[float, float]] = {}  # date -> (tvl, underlying_yield)
    for sym, m in markets.items():
        if str(m.get("underlying", "")).lower() != "susde":
            continue
        for p in m.get("series", []):
            d = p.get("date")
            iy = p.get("implied_yield")
            tvl = float(p.get("tvl_usd") or 0.0)
            if not isinstance(d, str) or not isinstance(iy, (int, float)):
                continue
            if d not in pt_by_day or tvl > pt_by_day[d][0]:
                pt_by_day[d] = (tvl, float(iy))
            uy = p.get("underlying_yield")
            if isinstance(uy, (int, float)) and uy > 0:
                if d not in susde_by_day or tvl > susde_by_day[d][0]:
                    susde_by_day[d] = (tvl, float(uy))
    if not pt_by_day:
        raise InvalidDataError("aggressive_lab: no sUSDe PT history in the deep Pendle dataset")
    pt_series = {d: iy for d, (_, iy) in pt_by_day.items()}
    # sUSDe staking APY: prefer the real underlying_yield; where absent fall back to the PT implied
    # yield itself (PT yield IS a market estimate of sUSDe's yield to maturity — a real, not faked,
    # proxy). This keeps the susde-spot/DN books accruing on a real series across the whole window.
    susde_series = {d: (susde_by_day[d][1] if d in susde_by_day else pt_series[d]) for d in pt_series}
    return pt_series, susde_series


# ──────────────────────────────────────────────────────────────────────────────────────────────────
# Operator CLI — name the unpinned keys out loud, and (with egress) prove a pin still resolves.
# ──────────────────────────────────────────────────────────────────────────────────────────────────
def main(argv: Optional[List[str]] = None) -> int:
    import sys as _sys
    args = list(argv if argv is not None else _sys.argv[1:])
    missing = unpinned_keys()
    print(f"pin registry: {PINNED_POOLS_FILE}")
    for key, rec in sorted(load_pinned_pools().items()):
        pid = rec.get("pool_id")
        where = f"{rec.get('project')}/{rec.get('chain')}/{rec.get('symbol')}"
        print(f"  {key:20s} {where:36s} pool_id={pid or 'NULL — must be read off the live feed'}")
    if missing:
        print(f"\nUNPINNED (feeds for these keys FAIL CLOSED, no number is produced): "
              f"{', '.join(missing)}")
    if "--verify" not in args:
        # exit 1 = "there is an unsubstituted pin", not a crash. Silence would be the bug.
        return 1 if missing else 0
    rc = 0
    for key in sorted(load_pinned_pools()):
        try:
            print(f"  verify {key}: apy = {PinnedPoolFeed(key).apy() * 100:.3f}%")
        except Exception as exc:  # noqa: BLE001 — the CLI reports the refusal, it does not swallow it
            print(f"  verify {key}: REFUSED — {exc}")
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
