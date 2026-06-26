"""
spa_core/strategy_lab/rates_desk/pendle_pt_history.py — DEEP Pendle PT implied-yield history.

THE DATA-GAP FIX. The keyless Pendle `/markets/active` endpoint returns only LIVE markets, so a
straight pull gives ~69 days of PT implied-yield history with no in-sample stress event — far too
short for a credible deflated-Sharpe carry verdict. This module solves that by reaching the EXPIRED
markets and pulling their FULL daily implied-yield history, spanning 2024-02 → today (2.3yr) and
covering all three named stress events (Aug-2024 carry-unwind, Oct-2025 restaking de-risk,
Apr-2026 KelpDAO rsETH depeg).

TWO methods are implemented; we use the FIRST (Pendle exposes implied APY directly, so deriving from
price is unnecessary):

  (A) DIRECT — preferred, used in build():
      • markets list (expired + live):
          GET api-v2.pendle.finance/core/v1/{chain}/markets?expired=true&limit=100&skip=K
        → 470 markets, each with {address, expiry, pt:{address}, underlyingAsset:{symbol}, ...},
          INCLUDING expired ones back to 2024-02.
      • per-market FULL daily implied/underlying APY history:
          GET api-v2.pendle.finance/core/v1/{chain}/markets/{addr}/historical-data?time_frame=day
        → {timestamp:[...], impliedApy:[...], underlyingApy:[...], ...} (daily; the underscore
          `time_frame=day` returns the WHOLE life of the market — the `timeframe=daily` spelling is
          silently capped to the last ~1440 hourly points).

  (B) DERIVED — implied_yield_from_price(): a PT redeems 1:1 for its underlying at maturity, so from
      the PT price (in face units) and days-to-maturity:
          implied_yield = (face / pt_price) ** (365 / days) - 1          (discrete, annualized)
      DENOMINATION CONVENTION: pt_price must be quoted in the SAME unit as the redemption face. For a
      PT-sUSDe priced in USD that redeems 1 sUSDe, divide by the sUSDe USD price first so both sides
      are in sUSDe units (price_in_face = pt_price_usd / underlying_usd). face defaults to 1.0 (one
      unit of underlying). This is kept for cross-checks / when the API lacks impliedApy; build() does
      not rely on it because the direct feed is authoritative.

Output: data/rates_desk/pendle_pt_history.json (atomic via shutil.move), schema:
  {"generated_at": iso, "method": "...", "underlyings": [...], "window": {...},
   "markets": {market_key: {underlying, pt_address, market_address, maturity, kind, symbol, method,
                            series: [{date, implied_yield, underlying_yield, pt_price|null}]}}}

PURE-ish: the fetch is the only IO (injectable `fetcher` for tests). Parsing/derivation are pure +
deterministic. fail-CLOSED: a malformed market/series RAISES (never a fabricated yield). stdlib only
(urllib + gzip + json). LLM-FORBIDDEN.

Run (real network, on the Mac):
    python3 -m spa_core.strategy_lab.rates_desk.pendle_pt_history
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import gzip
import json
import os
import shutil
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional

from spa_core.strategy_lab.rates_desk.contracts import UnderlyingKind

_ROOT = Path(__file__).resolve().parents[3]
_OUT = _ROOT / "data" / "rates_desk" / "pendle_pt_history.json"

PENDLE_API_BASE = "https://api-v2.pendle.finance/core/v1"
CHAIN_ID = 1
MARKETS_URL = PENDLE_API_BASE + "/{chain}/markets?expired=true&limit={limit}&skip={skip}"
HIST_URL = PENDLE_API_BASE + "/{chain}/markets/{addr}/historical-data?time_frame=day"
PAGE_LIMIT = 100
PAGE_DELAY_S = 0.15
TIMEOUT_S = 30

# Target underlyings. The "stable/synth" harvestable books + the TOXIC restaking books (needed to
# confirm refusal would have kept us out). Each key matches against the PT symbol (case-insensitive).
# `kind` drives the baseline model in the FairValueEngine.
HARVESTABLE = {
    "sUSDe": UnderlyingKind.STABLE_SYNTH,   # Ethena staked-USDe (the flagship synth-carry PT)
    "USDe":  UnderlyingKind.STABLE_SYNTH,   # Ethena USDe
    "eETH":  UnderlyingKind.LST,            # ether.fi eETH (matched via PT-weETH-*, LST baseline)
}
TOXIC = {
    "ezETH": UnderlyingKind.LRT,            # Renzo restaking (Aug-2024 carry-unwind)
    "rsETH": UnderlyingKind.LRT,            # KelpDAO restaking (Apr-2026 depeg)
}
TARGETS: Dict[str, UnderlyingKind] = {**HARVESTABLE, **TOXIC}

Fetcher = Callable[[str], object]


# ── HTTP (stdlib urllib + gzip) ──────────────────────────────────────────────────────────────────
def _http_fetch(url: str, timeout: int = TIMEOUT_S) -> object:
    req = urllib.request.Request(
        url, headers={"Accept-Encoding": "gzip", "User-Agent": "spa-rates-desk/1.0 (+stdlib)",
                      "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


# ── DERIVED method (B): implied yield from PT price (documented + tested cross-check) ─────────────
def implied_yield_from_price(
    pt_price: float,
    days_to_maturity: float,
    face: float = 1.0,
    underlying_price: Optional[float] = None,
    continuous: bool = False,
) -> float:
    """Annualized implied yield of a PT from its PRICE, robust + our-stack-native.

    A PT redeems 1:1 for `face` units of its underlying at maturity. The annualized implied yield is

        discrete:   (face / price_in_face) ** (365 / days) - 1
        continuous: -ln(price_in_face / face) * 365 / days

    DENOMINATION: `price_in_face` MUST be in the same unit as `face` (units of the underlying). If the
    PT price is quoted in USD and `underlying_price` (USD per 1 underlying) is given, we convert
    pt_price_usd -> underlying units first: price_in_face = pt_price / underlying_price. (For a PT
    that redeems 1 sUSDe, price the PT and the face both in sUSDe.)

    fail-CLOSED: a non-positive price / face / days, or a price >= face (PTs trade at a DISCOUNT to
    face before maturity — a price at/above face implies a non-positive yield, which for a fixed-rate
    instrument is malformed input), RAISES ValueError. Never returns a fabricated yield."""
    if days_to_maturity <= 0:
        raise ValueError(f"implied_yield_from_price: non-positive days_to_maturity {days_to_maturity}")
    if face <= 0:
        raise ValueError(f"implied_yield_from_price: non-positive face {face}")
    price_in_face = pt_price
    if underlying_price is not None:
        if underlying_price <= 0:
            raise ValueError(f"implied_yield_from_price: non-positive underlying_price {underlying_price}")
        price_in_face = pt_price / underlying_price
    if price_in_face <= 0:
        raise ValueError(f"implied_yield_from_price: non-positive price_in_face {price_in_face}")
    if price_in_face >= face:
        raise ValueError(
            f"implied_yield_from_price: price_in_face {price_in_face} >= face {face} "
            "(a PT trades at a discount pre-maturity; >=face → non-positive yield, malformed)")
    years = days_to_maturity / 365.0
    if continuous:
        import math
        return -math.log(price_in_face / face) * (1.0 / years)
    return (face / price_in_face) ** (1.0 / years) - 1.0


# ── DIRECT method (A): the Pendle expired-markets feed ───────────────────────────────────────────
def _iso(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).date().isoformat()


def _match_underlying(symbol: str) -> Optional[str]:
    """Return the canonical target underlying for a PT symbol, or None.

    Pendle PT symbols look like `PT-sUSDE-26DEC2024`, `PT-weETH-26SEP2024`, `PT-zs-ezETH-…`. We keep
    ONLY the straight PT of a target underlying (`PT-<token>-<expiry>`). Strict LEADING-segment
    matching is what excludes every nested/restaked wrapper variant: PT-zs-ezETH (body `zs-ezeth`),
    PT-Karak-sUSDe (`karak-susde`), PT-ctUSDe (`ctusde`), PT-rsUSDe (`rsusde`), PT-weETHs (`weeths`)
    etc. none START with `<token>-`, so they are all rejected. Conversely `usde` does NOT match the
    `reusde`/`susde` bodies, and `susde` matches only `pt-susde-…`. eETH trades as `PT-weETH-…`."""
    s = symbol.lower()
    if not s.startswith("pt-"):
        return None
    body = s[3:]  # strip "pt-"
    # longest token first so "susde" wins over "usde" when both could prefix-match
    for name in sorted(TARGETS, key=lambda n: -len(n)):
        token = "weeth" if name.lower() == "eeth" else name.lower()
        if body.startswith(token + "-"):
            return name
    return None


def fetch_markets(fetcher: Fetcher, chain: int = CHAIN_ID) -> List[dict]:
    """Page the expired+live markets endpoint. Returns the raw market dicts. fail-CLOSED: a malformed
    page (missing 'results'/'total') RAISES."""
    out: List[dict] = []
    total = None
    skip = 0
    while True:
        payload = fetcher(MARKETS_URL.format(chain=chain, limit=PAGE_LIMIT, skip=skip))
        if not isinstance(payload, dict):
            raise ValueError(f"pendle markets: expected object, got {type(payload).__name__}")
        results = payload.get("results")
        total = payload.get("total") if total is None else total
        if not isinstance(results, list):
            raise ValueError("pendle markets: missing/invalid 'results'")
        out.extend(results)
        skip += PAGE_LIMIT
        if total is None or skip >= int(total) or not results:
            break
        if PAGE_DELAY_S:
            time.sleep(PAGE_DELAY_S)
    return out


def select_target_markets(raw_markets: List[dict]) -> List[dict]:
    """Filter the raw markets to the canonical straight PTs of our TARGET underlyings. Returns a list
    of normalized {underlying, kind, symbol, market_address, pt_address, maturity}. Deterministic
    (sorted by underlying then maturity)."""
    picked: List[dict] = []
    for m in raw_markets:
        pt = m.get("pt") or {}
        symbol = pt.get("symbol") or m.get("symbol") or ""
        underlying = _match_underlying(symbol)
        if underlying is None:
            continue
        market_addr = m.get("address")
        pt_addr = pt.get("address")
        expiry = (m.get("expiry") or "")[:10]
        if not market_addr or not pt_addr or not expiry:
            continue  # fail-CLOSED: incomplete market metadata → skip (never fabricate)
        picked.append({
            "underlying": underlying,
            "kind": TARGETS[underlying].value,
            "symbol": symbol,
            "market_address": market_addr,
            "pt_address": pt_addr,
            "maturity": expiry,
        })
    picked.sort(key=lambda d: (d["underlying"], d["maturity"]))
    return picked


def _maturity_ts(maturity: str) -> int:
    d = datetime.date.fromisoformat(maturity)
    return int(datetime.datetime(d.year, d.month, d.day, tzinfo=datetime.timezone.utc).timestamp())


def fetch_market_history(fetcher: Fetcher, market: dict, chain: int = CHAIN_ID) -> List[dict]:
    """Fetch one market's FULL daily implied/underlying APY series. Returns a sorted list of
    {date, implied_yield, underlying_yield, tvl_usd}. fail-CLOSED: malformed payload RAISES;
    individual non-numeric points are skipped (a single bad sample is not a fabricated yield, the
    series as a whole is still real). Near-maturity samples (< NEAR_MATURITY_DAYS to expiry) are
    dropped: a PT's implied APY explodes into illiquid noise in its final days (price→face), which is
    not harvestable carry.

    The `tvl` series is captured per day so the §9 exit-liquidity proxy can be tied to the
    CONTEMPORANEOUS pool depth (NOT a stale/peak constant). This is the calibration fix the Oct-2025
    stress validation demands: when a PT pool's TVL collapses during a de-risk unwind, the desk's
    exit capacity must shrink with it (so it sizes down / cannot exit at size) — that only works if
    we record the real per-day depth here. tvl_usd is the raw Pendle TVL (USD) for the day; a
    non-numeric / absent TVL → None (the consumer fail-CLOSEs to the documented depth constant and
    flags it). Early pre-liquidity placeholder days (Pendle reports tvl≈0.1 at market inception) are
    kept VERBATIM and honestly tiny — the desk would never trade a $0.10-depth pool (the gate's
    exit-capacity check refuses it), so capturing the real value is the correct fail-CLOSED behavior."""
    NEAR_MATURITY_DAYS = 3
    payload = fetcher(HIST_URL.format(chain=chain, addr=market["market_address"]))
    if not isinstance(payload, dict):
        raise ValueError(f"pendle history {market['symbol']}: expected object")
    ts = payload.get("timestamp")
    ia = payload.get("impliedApy")
    ua = payload.get("underlyingApy")
    tv = payload.get("tvl")
    if not isinstance(ts, list) or not isinstance(ia, list) or not ts:
        raise ValueError(f"pendle history {market['symbol']}: missing timestamp/impliedApy")
    ua = ua if isinstance(ua, list) else [None] * len(ts)
    tv = tv if isinstance(tv, list) else [None] * len(ts)
    mat_ts = _maturity_ts(market["maturity"])
    cutoff = mat_ts - NEAR_MATURITY_DAYS * 86400
    by_date: Dict[str, dict] = {}
    for i, t in enumerate(ts):
        if not isinstance(t, (int, float)):
            continue
        if t > cutoff:
            continue  # drop near-maturity illiquid noise
        try:
            implied = float(ia[i])
        except (TypeError, ValueError, IndexError):
            continue
        try:
            und = float(ua[i]) if i < len(ua) and ua[i] is not None else None
        except (TypeError, ValueError):
            und = None
        try:
            tvl = float(tv[i]) if i < len(tv) and tv[i] is not None else None
        except (TypeError, ValueError):
            tvl = None
        d = _iso(t)
        by_date[d] = {"date": d, "implied_yield": round(implied, 6),
                      "underlying_yield": (round(und, 6) if und is not None else None),
                      "tvl_usd": (round(tvl, 2) if tvl is not None else None),
                      "pt_price": None}  # direct method: implied is authoritative, price not needed
    return [by_date[d] for d in sorted(by_date)]


# ── build the deep dataset ────────────────────────────────────────────────────────────────────────
def build(fetcher: Optional[Fetcher] = None, chain: int = CHAIN_ID,
          out_path: Optional[Path] = None) -> dict:
    """Build the deep PT implied-yield dataset and write it atomically. Returns the dataset dict.

    Method = DIRECT (Pendle's per-market historical-data feed exposes implied APY directly across
    expired markets). The DERIVED-from-price path is available (implied_yield_from_price) for
    cross-checks but is NOT needed here. fail-CLOSED throughout."""
    out_path = out_path if out_path is not None else _OUT
    fetch = fetcher or _http_fetch
    raw = fetch_markets(fetch, chain)
    targets = select_target_markets(raw)

    markets: Dict[str, dict] = {}
    all_dates: List[str] = []
    for m in targets:
        if PAGE_DELAY_S:
            time.sleep(PAGE_DELAY_S)
        try:
            series = fetch_market_history(fetch, m, chain)
        except ValueError:
            # a single market with no usable history is skipped (not fabricated); the dataset as a
            # whole is still real. We do NOT raise here so one dead market can't void the deep pull.
            continue
        if not series:
            continue
        key = m["symbol"]
        markets[key] = {
            "underlying": m["underlying"],
            "kind": m["kind"],
            "symbol": m["symbol"],
            "market_address": m["market_address"],
            "pt_address": m["pt_address"],
            "maturity": m["maturity"],
            "method": "direct_api_implied",
            "series": series,
        }
        all_dates.extend(p["date"] for p in series)

    window = {"start": min(all_dates), "end": max(all_dates)} if all_dates else {"start": None, "end": None}
    dataset = {
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "method": "direct_api_implied (Pendle expired-markets historical-data, time_frame=day)",
        "underlyings": sorted({m["underlying"] for m in markets.values()}),
        "window": window,
        "markets": markets,
    }
    _atomic_write_json(out_path, dataset)
    return dataset


def _atomic_write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.stem + "_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=1, sort_keys=True)
        shutil.move(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ── loader (used by the validation) ────────────────────────────────────────────────────────────────
def load(out_path: Optional[Path] = None) -> dict:
    """Load + validate the deep dataset. fail-CLOSED: missing file or malformed schema RAISES."""
    out_path = out_path if out_path is not None else _OUT
    if not out_path.exists():
        raise FileNotFoundError(
            f"deep Pendle PT history not found at {out_path} — run "
            "`python3 -m spa_core.strategy_lab.rates_desk.pendle_pt_history` first")
    data = json.loads(out_path.read_text())
    if not isinstance(data, dict) or "markets" not in data:
        raise ValueError(f"deep Pendle PT history malformed: {out_path}")
    markets = data["markets"]
    if not isinstance(markets, dict) or not markets:
        raise ValueError("deep Pendle PT history: empty/invalid 'markets'")
    for key, m in markets.items():
        if not isinstance(m, dict) or "series" not in m or "kind" not in m:
            raise ValueError(f"deep Pendle PT history: market {key} malformed")
        ser = m["series"]
        if not isinstance(ser, list):
            raise ValueError(f"deep Pendle PT history: market {key} series not a list")
        for p in ser:
            if "date" not in p or "implied_yield" not in p:
                raise ValueError(f"deep Pendle PT history: market {key} bad point {p}")
    return data


if __name__ == "__main__":
    import socket
    socket.setdefaulttimeout(TIMEOUT_S)
    ds = build()
    ms = ds["markets"]
    print(f"method: {ds['method']}")
    print(f"window: {ds['window']}")
    print(f"underlyings: {ds['underlyings']}")
    print(f"markets: {len(ms)}")
    for key, m in sorted(ms.items()):
        ser = m["series"]
        print(f"  {key:>26}  {m['underlying']:>6}/{m['kind']:<12} "
              f"n={len(ser):>4}  {ser[0]['date']}..{ser[-1]['date']}")
    print(f"\nWrote {_OUT}")
