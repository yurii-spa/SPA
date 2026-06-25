"""
spa_core/strategy_lab/data/market_data.py — the UNIFIER.

Assembles funding + ETH/LRT prices + LRT/ETH ratios + restaking APY + defi APY into one
`MarketSnapshot` per date. SAME shape for backtest (historical_range) and live paper-trading
(latest). One cached source so both share identical inputs.

Public surface:
  MarketData.snapshot(date)            -> MarketSnapshot for a specific ISO date
  MarketData.latest()                  -> MarketSnapshot for the most recent available date
  MarketData.historical_range(s, e)    -> [MarketSnapshot] ascending by date over [s, e]
                                          (sets the deep window so a cache miss fetches [s,e])
  MarketData.refresh(start, end)       -> re-fetch the full PAGINATED deep range + rewrite cache
  MarketData.refresh()                 -> shallow most-recent page (or instance `window` if set)

Gap / forward-fill policy (per the contract):
  - For a date with no fresh datapoint for a field, forward-fill from the most recent prior
    date — but ONLY within FF_LIMIT_DAYS (default 2). Filled fields are flagged in
    snapshot.ff_filled.
  - Beyond the limit (or with no prior value at all) the field is left None and its name is
    added to snapshot.gaps.
  - Fail-CLOSED end to end: a feed raising InvalidDataError on refresh propagates; we never
    fabricate a series. On a cache-only read with no network, we serve whatever was cached.

Caching: data/market_data/{funding,prices,ratios,restaking,defi}.json written atomically
(tmp + shutil.move — cross-device safe in sandbox, per repo rule #4).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from spa_core.strategy_lab.base import InvalidDataError, MarketSnapshot
from spa_core.strategy_lab.data.btc_lending_feed import BtcLendingFeed
from spa_core.strategy_lab.data.funding_feed import FundingFeed
from spa_core.strategy_lab.data.price_feed import (
    BTC_REF_SYMBOL,
    BTC_WRAPPER_SYMBOLS,
    RATIO_SYMBOLS,
    PriceFeed,
)
from spa_core.strategy_lab.data.restaking_feed import RestakingFeed

_ROOT = Path(__file__).resolve().parents[3]  # …/SPA_Claude
_CACHE_DIR = _ROOT / "data" / "market_data"

FF_LIMIT_DAYS = 2


def _try_btc(fn):
    """Run a BTC-feed fetch; on ANY failure return {} (fail-OPEN at the data layer). A BTC feed
    gap (e.g. wrapper history that doesn't reach the window start, or a transient API error) must
    NOT crash an ETH-centric refresh — the BTC STRATEGIES still fail-CLOSED per-tick on the
    resulting snapshot gaps. ETH feeds are NOT wrapped (they remain fail-closed, as before)."""
    try:
        return fn() or {}
    except Exception:  # noqa: BLE001 — degrade to empty so the ETH path is unaffected
        return {}


# ── atomic JSON cache helpers ───────────────────────────────────────────────────────────────
def _atomic_write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.stem + "_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=2, sort_keys=True)
        shutil.move(tmp, str(path))  # atomic, cross-device safe (repo rule #4)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _read_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:  # noqa: BLE001 - a corrupt cache is treated as absent (will refetch)
        return None


def _ff_lookup(series: Dict[str, float], date: str, limit: int) -> tuple[Optional[float], bool]:
    """Return (value, was_ff). Exact hit → (v, False). Else nearest prior within `limit` days
    → (v, True). Else (None, False)."""
    if date in series:
        return series[date], False
    if not series:
        return None, False
    target = datetime.date.fromisoformat(date)
    prior = [d for d in series if d < date]
    if not prior:
        return None, False
    nearest = max(prior)
    age = (target - datetime.date.fromisoformat(nearest)).days
    if age <= limit:
        return series[nearest], True
    return None, False


def _ff_lookup_map(
    series_map: Dict[str, Dict[str, float]], date: str, limit: int
) -> tuple[Dict[str, float], set, set]:
    """Forward-fill a {key: {date: value}} structure for one date.
    Returns (values, ff_keys, gap_keys)."""
    values: Dict[str, float] = {}
    ff_keys: set = set()
    gap_keys: set = set()
    for key, series in series_map.items():
        v, was_ff = _ff_lookup(series, date, limit)
        if v is None:
            gap_keys.add(key)
        else:
            values[key] = v
            if was_ff:
                ff_keys.add(key)
    return values, ff_keys, gap_keys


class MarketData:
    """Unified market-data source for the Strategy Lab.

    Feeds are injectable (tests pass fakes). `ff_limit_days` bounds forward-fill. `defi_apy`
    is an optional caller-supplied {protocol: {date: apy_decimal}} series (e.g. from the
    existing DeFiLlama historical-APY cache) — the lab's stable benchmark sleeve uses it;
    if absent the defi_apy field is simply empty (and not treated as a gap)."""

    def __init__(
        self,
        funding_feed: Optional[FundingFeed] = None,
        price_feed: Optional[PriceFeed] = None,
        restaking_feed: Optional[RestakingFeed] = None,
        defi_apy_series: Optional[Dict[str, Dict[str, float]]] = None,
        cache_dir: Optional[Path] = None,
        ff_limit_days: int = FF_LIMIT_DAYS,
        price_span: int = 90,
        window: Optional[tuple] = None,
        btc_funding_feed: Optional[FundingFeed] = None,
        btc_lending_feed: Optional[BtcLendingFeed] = None,
    ):
        self._funding = funding_feed or FundingFeed()
        self._price = price_feed or PriceFeed()
        self._restaking = restaking_feed or RestakingFeed()
        # BTC perp funding = the SAME 5-venue median feed, built for the BTC perp. BTC lending =
        # the wrapped-BTC supply-yield floor (tBTC/cbBTC). Both injectable for hermetic tests.
        self._btc_funding = btc_funding_feed or FundingFeed(symbol="BTC")
        self._btc_lending = btc_lending_feed or BtcLendingFeed()
        self._defi_series = defi_apy_series or {}
        self._cache_dir = Path(cache_dir) if cache_dir else _CACHE_DIR
        self._ff_limit = ff_limit_days
        self._price_span = price_span
        # Deep-history window (start_date, end_date) ISO. When set, refresh() pulls the full
        # PAGINATED range from every feed instead of the most-recent single page.
        self._window = window

        # in-memory series (loaded from cache lazily / populated by refresh)
        self._funding_series: Dict[str, float] = {}
        self._price_series: Dict[str, Dict[str, float]] = {}   # {sym: {date: price}}
        self._ratio_series: Dict[str, Dict[str, float]] = {}   # {lrt_sym: {date: ratio}}
        self._restaking_latest: Dict[str, float] = {}          # {sym: apy} (point-in-time fallback)
        self._restaking_series: Dict[str, Dict[str, float]] = {}  # {sym: {date: apy}} (deep history)
        # BTC series (parallel to the ETH ones)
        self._btc_funding_series: Dict[str, float] = {}        # {date: median 8h BTC funding}
        self._btc_ratio_series: Dict[str, Dict[str, float]] = {}  # {wrapper_sym: {date: ratio}}
        self._btc_lending_latest: Dict[str, float] = {}        # {sym: apy} (point-in-time fallback)
        self._btc_lending_series: Dict[str, Dict[str, float]] = {}  # {sym: {date: apy}} (deep history)
        self._loaded = False

    # ── paths ────────────────────────────────────────────────────────────────────────────
    def _p(self, name: str) -> Path:
        return self._cache_dir / f"{name}.json"

    # ── load / refresh ─────────────────────────────────────────────────────────────────────
    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        cached = self._load_cache()
        if not cached:
            self.refresh()
        self._loaded = True

    def _load_cache(self) -> bool:
        funding = _read_json(self._p("funding"))
        prices = _read_json(self._p("prices"))
        ratios = _read_json(self._p("ratios"))
        restaking = _read_json(self._p("restaking"))
        defi = _read_json(self._p("defi"))
        btc_funding = _read_json(self._p("btc_funding"))
        btc_ratios = _read_json(self._p("btc_ratios"))
        btc_lending = _read_json(self._p("btc_lending"))
        if funding is None or prices is None:
            return False
        self._funding_series = {k: float(v) for k, v in funding.get("series", {}).items()}
        self._price_series = {
            sym: {d: float(p) for d, p in s.items()}
            for sym, s in (prices.get("series", {}) or {}).items()
        }
        self._ratio_series = {
            sym: {d: float(p) for d, p in s.items()}
            for sym, s in ((ratios or {}).get("series", {}) or {}).items()
        }
        self._restaking_latest = {
            k: float(v) for k, v in ((restaking or {}).get("apys", {}) or {}).items()
        }
        self._restaking_series = {
            sym: {d: float(a) for d, a in s.items()}
            for sym, s in ((restaking or {}).get("series", {}) or {}).items()
        }
        if defi and defi.get("series"):
            self._defi_series = {
                proto: {d: float(a) for d, a in s.items()}
                for proto, s in defi["series"].items()
            }
        # BTC series (optional — absent on an ETH-only cache; left empty → snapshot gaps)
        self._btc_funding_series = {
            k: float(v) for k, v in ((btc_funding or {}).get("series", {}) or {}).items()
        }
        self._btc_ratio_series = {
            sym: {d: float(p) for d, p in s.items()}
            for sym, s in ((btc_ratios or {}).get("series", {}) or {}).items()
        }
        self._btc_lending_latest = {
            k: float(v) for k, v in ((btc_lending or {}).get("apys", {}) or {}).items()
        }
        self._btc_lending_series = {
            sym: {d: float(a) for d, a in s.items()}
            for sym, s in ((btc_lending or {}).get("series", {}) or {}).items()
        }
        return True

    def refresh(self, start: Optional[str] = None, end: Optional[str] = None) -> None:
        """Re-fetch ALL series from the live feeds and rewrite the cache atomically.

        With start/end (or the instance `window`): pull the full PAGINATED deep range from every
        feed — funding median per day, ETH/LRT prices + ratios at daily granularity, and the
        per-date restaking APY series. Without a window: the original most-recent single page.
        Fail-CLOSED: a feed raising InvalidDataError propagates (we do not write a partial
        fabricated cache)."""
        win = (start, end) if (start is not None and end is not None) else self._window
        restaking_series: Dict[str, Dict[str, float]] = {}
        restaking_latest: Dict[str, float] = {}
        # BTC series — fail-OPEN at refresh (a BTC feed gap must NOT crash an ETH-centric run;
        # the BTC strategies fail-CLOSED per-tick on the resulting snapshot gaps). The wrapped-BTC
        # tokens' on-chain price history may start AFTER the ETH window opens (tBTC/cbBTC are
        # younger), so a partial BTC series is normal and expected.
        btc_funding: Dict[str, float] = {}
        btc_ratio_hist: Dict[str, Dict[str, float]] = {}
        btc_lending_series: Dict[str, Dict[str, float]] = {}
        btc_lending_latest: Dict[str, float] = {}
        if win:
            s, e = win
            funding = self._funding.history(start_date=s, end_date=e)
            price_hist = self._price.history(start_date=s, end_date=e)
            ratio_hist = self._price.history_ratios(start_date=s, end_date=e)
            restaking_series = self._restaking.history(s, e)
            # derive a point-in-time 'latest' from the deep series (most recent apy per symbol)
            restaking_latest = {
                sym: ser[max(ser)] for sym, ser in restaking_series.items() if ser
            }
            btc_funding = _try_btc(lambda: self._btc_funding.history(start_date=s, end_date=e))
            btc_ratio_hist = _try_btc(
                lambda: self._price.history_btc_ratios(start_date=s, end_date=e)
            )
            btc_lending_series = _try_btc(lambda: self._btc_lending.history(s, e))
            btc_lending_latest = {
                sym: ser[max(ser)] for sym, ser in (btc_lending_series or {}).items() if ser
            }
        else:
            funding = self._funding.history()
            price_hist = self._price.history(span=self._price_span)
            ratio_hist = self._price.history_ratios(span=self._price_span)
            restaking_latest = self._restaking.apys()
            btc_funding = _try_btc(lambda: self._btc_funding.history())
            btc_ratio_hist = _try_btc(lambda: self._price.history_btc_ratios(span=self._price_span))
            btc_lending_latest = _try_btc(lambda: self._btc_lending.apys())

        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        _atomic_write_json(self._p("funding"), {"generated_at": ts, "series": funding})
        _atomic_write_json(self._p("prices"), {"generated_at": ts, "series": price_hist})
        _atomic_write_json(self._p("ratios"), {"generated_at": ts, "series": ratio_hist})
        _atomic_write_json(
            self._p("restaking"),
            {"generated_at": ts, "apys": restaking_latest, "series": restaking_series},
        )
        _atomic_write_json(self._p("btc_funding"), {"generated_at": ts, "series": btc_funding})
        _atomic_write_json(self._p("btc_ratios"), {"generated_at": ts, "series": btc_ratio_hist})
        _atomic_write_json(
            self._p("btc_lending"),
            {"generated_at": ts, "apys": btc_lending_latest, "series": btc_lending_series},
        )
        if self._defi_series:
            _atomic_write_json(
                self._p("defi"), {"generated_at": ts, "series": self._defi_series}
            )

        self._funding_series = funding
        self._price_series = price_hist
        self._ratio_series = ratio_hist
        self._restaking_latest = restaking_latest
        self._restaking_series = restaking_series
        self._btc_funding_series = btc_funding
        self._btc_ratio_series = btc_ratio_hist
        self._btc_lending_latest = btc_lending_latest
        self._btc_lending_series = btc_lending_series
        self._loaded = True

    # ── assembly ───────────────────────────────────────────────────────────────────────────
    def snapshot(self, date: str) -> MarketSnapshot:
        """Assemble the MarketSnapshot for `date` (ISO). Forward-fills within the limit, flags
        gaps and ff_filled. Never fabricates beyond a ff'd prior real value."""
        self._ensure_loaded()
        # validate date shape early (fail-closed on a malformed date)
        try:
            datetime.date.fromisoformat(date)
        except ValueError as exc:
            raise InvalidDataError(f"snapshot: invalid date {date!r}") from exc

        snap = MarketSnapshot(date=date)

        # funding (scalar)
        funding, ff = _ff_lookup(self._funding_series, date, self._ff_limit)
        if funding is None:
            snap.gaps.add("funding_rate_8h")
        else:
            snap.funding_rate_8h = funding
            if ff:
                snap.ff_filled.add("funding_rate_8h")

        # eth price (scalar)
        eth_series = self._price_series.get("eth", {})
        eth_price, eth_ff = _ff_lookup(eth_series, date, self._ff_limit)
        if eth_price is None:
            snap.gaps.add("eth_price_usd")
        else:
            snap.eth_price_usd = eth_price
            if eth_ff:
                snap.ff_filled.add("eth_price_usd")

        # staked-ETH-token prices (map) — LRTs AND LSTs (eth handled above)
        lrt_price_map = {s: self._price_series[s] for s in RATIO_SYMBOLS if s in self._price_series}
        vals, ff_keys, gap_keys = _ff_lookup_map(lrt_price_map, date, self._ff_limit)
        snap.lrt_price_usd = vals
        for k in ff_keys:
            snap.ff_filled.add(f"lrt_price_usd.{k}")
        for k in gap_keys:
            snap.gaps.add(f"lrt_price_usd.{k}")

        # lrt/eth ratios (map)
        vals, ff_keys, gap_keys = _ff_lookup_map(self._ratio_series, date, self._ff_limit)
        snap.lrt_eth_ratio = vals
        for k in ff_keys:
            snap.ff_filled.add(f"lrt_eth_ratio.{k}")
        for k in gap_keys:
            snap.gaps.add(f"lrt_eth_ratio.{k}")

        # restaking apy (map) — prefer the per-date deep series (yields /chart) with forward-fill;
        # fall back to the point-in-time latest applied to every date when no deep series exists.
        if self._restaking_series:
            vals, ff_keys, gap_keys = _ff_lookup_map(self._restaking_series, date, self._ff_limit)
            snap.restaking_apy = vals
            for k in ff_keys:
                snap.ff_filled.add(f"restaking_apy.{k}")
            for k in gap_keys:
                snap.gaps.add(f"restaking_apy.{k}")
            if not vals:
                snap.gaps.add("restaking_apy")
        else:
            snap.restaking_apy = dict(self._restaking_latest)
            if not self._restaking_latest:
                snap.gaps.add("restaking_apy")

        # ── BTC sleeve fields (parallel to the ETH ones) ──────────────────────────────────
        # btc price (scalar) — the WBTC reference price from the same price series.
        btc_series = self._price_series.get(BTC_REF_SYMBOL, {})
        btc_price, btc_ff = _ff_lookup(btc_series, date, self._ff_limit)
        if btc_price is None:
            snap.gaps.add("btc_price_usd")
        else:
            snap.btc_price_usd = btc_price
            if btc_ff:
                snap.ff_filled.add("btc_price_usd")

        # btc funding (scalar)
        btc_funding, btc_f_ff = _ff_lookup(self._btc_funding_series, date, self._ff_limit)
        if btc_funding is None:
            snap.gaps.add("btc_funding_rate_8h")
        else:
            snap.btc_funding_rate_8h = btc_funding
            if btc_f_ff:
                snap.ff_filled.add("btc_funding_rate_8h")

        # wrapped-BTC prices (map) — tBTC / cbBTC from the same price series.
        wrapper_price_map = {
            s: self._price_series[s] for s in BTC_WRAPPER_SYMBOLS if s in self._price_series
        }
        vals, ff_keys, gap_keys = _ff_lookup_map(wrapper_price_map, date, self._ff_limit)
        snap.btc_wrapper_price_usd = vals
        for k in ff_keys:
            snap.ff_filled.add(f"btc_wrapper_price_usd.{k}")
        for k in gap_keys:
            snap.gaps.add(f"btc_wrapper_price_usd.{k}")

        # wrapper/btc ratios (map) — the wrapper-depeg signal.
        vals, ff_keys, gap_keys = _ff_lookup_map(self._btc_ratio_series, date, self._ff_limit)
        snap.btc_wrapper_ratio = vals
        for k in ff_keys:
            snap.ff_filled.add(f"btc_wrapper_ratio.{k}")
        for k in gap_keys:
            snap.gaps.add(f"btc_wrapper_ratio.{k}")

        # btc lending apy (map) — prefer the per-date deep series with forward-fill; fall back to
        # the point-in-time latest applied to every date when no deep series exists.
        if self._btc_lending_series:
            vals, ff_keys, gap_keys = _ff_lookup_map(
                self._btc_lending_series, date, self._ff_limit
            )
            snap.btc_lending_apy = vals
            for k in ff_keys:
                snap.ff_filled.add(f"btc_lending_apy.{k}")
            for k in gap_keys:
                snap.gaps.add(f"btc_lending_apy.{k}")
            if not vals:
                snap.gaps.add("btc_lending_apy")
        elif self._btc_lending_latest:
            snap.btc_lending_apy = dict(self._btc_lending_latest)
        else:
            snap.gaps.add("btc_lending_apy")

        # defi apy (map) — optional caller-supplied per-date series
        if self._defi_series:
            vals, ff_keys, gap_keys = _ff_lookup_map(self._defi_series, date, self._ff_limit)
            snap.defi_apy = vals
            for k in ff_keys:
                snap.ff_filled.add(f"defi_apy.{k}")
            for k in gap_keys:
                snap.gaps.add(f"defi_apy.{k}")

        return snap

    def latest(self) -> MarketSnapshot:
        """Snapshot for the most recent date across the loaded series (live paper-trading)."""
        self._ensure_loaded()
        candidates = set(self._funding_series) | set(self._price_series.get("eth", {}))
        for s in self._price_series.values():
            candidates |= set(s)
        if not candidates:
            raise InvalidDataError("latest: no cached/fetched data available")
        return self.snapshot(max(candidates))

    def historical_range(self, start: str, end: str) -> List[MarketSnapshot]:
        """Ascending list of snapshots for each calendar day in [start, end] inclusive.

        Sets the deep-history window to [start, end] so a cache MISS triggers a paginated deep
        fetch over exactly this range (not the shallow most-recent page)."""
        if self._window is None:
            self._window = (start, end)
        self._ensure_loaded()
        try:
            d0 = datetime.date.fromisoformat(start)
            d1 = datetime.date.fromisoformat(end)
        except ValueError as exc:
            raise InvalidDataError(f"historical_range: bad date(s) {start!r}..{end!r}") from exc
        if d1 < d0:
            raise InvalidDataError(f"historical_range: end {end} before start {start}")
        out: List[MarketSnapshot] = []
        cur = d0
        while cur <= d1:
            out.append(self.snapshot(cur.isoformat()))
            cur += datetime.timedelta(days=1)
        return out


if __name__ == "__main__":  # manual real-network smoke test (run on the Mac)
    import socket

    socket.setdefaulttimeout(20)
    md = MarketData()
    md.refresh()
    snap = md.latest()
    print("LATEST", snap.date)
    print("  eth_price_usd =", snap.eth_price_usd)
    print("  funding_rate_8h =", snap.funding_rate_8h)
    print("  lrt_price_usd =", snap.lrt_price_usd)
    print("  lrt_eth_ratio =", snap.lrt_eth_ratio)
    print("  restaking_apy =", snap.restaking_apy)
    print("  gaps =", snap.gaps, " ff_filled =", snap.ff_filled)
