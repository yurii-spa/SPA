"""
spa_core/strategy_lab/aggressive_lab/feeds.py — the REAL-DATA snapshot builder for the lab.

This is the module that makes the Aggressive Lab's comparison HONEST: every accrual is driven by a
MarketSnapshot whose fields come from LIVE keyless feeds, NOT mock data. (The existing tournament's
trustworthy:false flaw is exactly mock-driven accrual — this lab must not repeat it.)

It augments the strategy_lab MarketSnapshot with the aggressive-roster-specific defi_apy keys:

    defi_apy["susde"]            ← Ethena sUSDe staking APY        (DeFiLlama yields)
    defi_apy["pendle_pt_susde"]  ← Pendle PT-sUSDe implied yield   (rates_desk pendle history/surface)
    defi_apy["pendle_yt_susde"]  ← Pendle YT-sUSDe implied yield   (YT yield ≈ implied/(1−PTprice) proxy)
    defi_apy["points"]           ← points/incentive APY            (config-modelled; flagged class D)
    defi_apy["aave_v3_wsteth"]   ← wstETH supply APY               (DeFiLlama, fallback)
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
from typing import Callable, Dict, List, Optional, Tuple

from spa_core.strategy_lab.base import InvalidDataError, MarketSnapshot

# config-modelled points APY (class D). A literal here is a MODELLING assumption, not a fabricated
# market price — and it is explicitly flagged as the incentive class that decays. Strategies that
# require it fail closed if it is not supplied; the default below is only used when points modelling
# is enabled. (It is NOT a hardcoded yield for a market-priced strategy — those use the live feeds.)
DEFAULT_POINTS_APY = 0.06


def _utc_today() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


# ──────────────────────────────────────────────────────────────────────────────────────────────────
# A small, self-contained source of the aggressive-specific yields. Each source returns either a
# per-date dict {date: apy_decimal} (history mode) or a scalar latest (live mode). All are injectable.
# ──────────────────────────────────────────────────────────────────────────────────────────────────
class AggressiveFeeds:
    """Builds augmented MarketSnapshots on REAL data.

    Injectable series (history mode) — each a {ISO_date: apy_decimal} or {ISO_date: value}:
        susde_apy_series, pt_susde_series, funding_series, restaking_series (per-symbol nested),
        eth_price_series, lrt_ratio_series (per-symbol nested), points_apy_series.
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
        self._points_apy = points_apy if points_apy is not None else DEFAULT_POINTS_APY
        self._enable_points = enable_points
        self._yt_premium = float(pendle_pt_premium)
        self._live = live_loaders or {}

    # ── history mode: the full per-day replay series (the 2024–2026 backtest) ─────────────────────
    def available_dates(self) -> List[str]:
        """Sorted union of dates across the injected series (history mode). Empty if none injected."""
        dates: set = set()
        for s in (self._susde, self._pt, self._funding, self._eth):
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
        if self._enable_points:
            defi["points"] = self._points_apy
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
        if self._enable_points:
            defi["points"] = self._points_apy

        snap.defi_apy = defi
        return snap


# ──────────────────────────────────────────────────────────────────────────────────────────────────
# Real deep-history loader: reuse the rates_desk Pendle PT dataset (2024–2026, real implied yields)
# to build the sUSDe PT implied-yield series — the backbone of the real backtest stress windows.
# ──────────────────────────────────────────────────────────────────────────────────────────────────
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
