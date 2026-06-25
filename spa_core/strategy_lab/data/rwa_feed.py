"""
spa_core/strategy_lab/data/rwa_feed.py — LIVE tokenized-T-bill (RWA) risk-free floor.

Per docs/RESEARCH_EXPANSION_2026-06-25.md, tokenized US-Treasury funds (BlackRock BUIDL,
Ondo USDY/OUSG, Circle/Hashnote USYC, Franklin BENJI, Superstate USTB, OpenEden TBILL, …)
are a ~$15B market yielding ~3.3–3.5%. That blended yield is the REAL risk-free benchmark
every Strategy-Lab strategy must beat on a risk-adjusted basis — it replaces the hardcoded
4.5% literal in config (which is kept only as a conservative offline fallback).

Source (keyless): https://yields.llama.fi/pools → {"status":"success","data":[ {project,
chain,symbol,apy,tvlUsd,pool,...} ]}. We match the canonical NATIVE tokenized-Treasury issuer
pools by (project, symbol) — NOT LP pools that merely contain an RWA token, and NOT lending
markets re-listing the token. A per-pool TVL floor (default $5M, the repo's risk floor) drops
the tiny zero-yield mirror listings each issuer publishes across many chains.

Representative RWA floor = TVL-WEIGHTED mean APY across the qualifying pools (median also
exposed for cross-check). TVL-weighted reflects where the ~$15B actually sits (BUIDL/USYC/USDY
dominate) — a single small high-APY mirror cannot move the floor.

Verified against live /pools (2026-06-25):
  ondo-yield-assets  USDY  ~3.55%  ($1.1B)   ondo-yield-assets  OUSG  ~3.80%  ($255M)
  blackrock-buidl    BUIDL ~3.54%  ($831M)   circle-usyc        USYC  ~3.17%  ($3.0B)
  invesco-ustb       USTB  ~3.77%  ($605M)   openeden-tbill     TBILL ~3.29%  ($33M)
  bitwise-uscc       USCC  ~2.90%  ($91M)
  → TVL-weighted blend ≈ 3.3–3.5% (the live floor).

FAIL-CLOSED: malformed payload, empty data, or NONE of the selectors matched a pool with a
valid apy AND tvl above the floor → InvalidDataError. We NEVER fabricate a floor; callers
(config.rwa_floor_apy_pct) decide whether to fall back to the committed literal.

Caching: data/market_data/rwa_floor.json written atomically (tmp + shutil.move, cross-device
safe per repo rule #4). `current_rwa_floor_pct()` returns the cached fresh value (or refetches);
`history(start, end)` returns the per-date TVL-weighted floor series via yields /chart.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from spa_core.strategy_lab.base import InvalidDataError
from spa_core.strategy_lab.data._http import http_fetch

POOLS_URL = "https://yields.llama.fi/pools"
CHART_URL = "https://yields.llama.fi/chart/{pool}"

_ROOT = Path(__file__).resolve().parents[3]  # …/SPA_Claude
_CACHE_PATH = _ROOT / "data" / "market_data" / "rwa_floor.json"

# Default per-pool TVL floor = the repo's risk-policy floor ($5M). Mirror/dust listings drop.
DEFAULT_TVL_FLOOR_USD = 5_000_000.0
# A live tokenized-T-bill yield must be inside this sane band; outside → that pool is ignored
# (a 0% mirror listing or a corrupted >100% datapoint cannot pollute the floor).
MIN_SANE_APY_PCT = 0.5
MAX_SANE_APY_PCT = 12.0

# Canonical NATIVE tokenized-Treasury issuer pools as (project, symbol). The symbol pins the
# fund token so an issuer's LP/other listings are excluded. Probed live 2026-06-25.
SELECTORS: Tuple[Dict[str, str], ...] = (
    {"project": "ondo-yield-assets", "symbol": "USDY"},   # Ondo USDY
    {"project": "ondo-yield-assets", "symbol": "OUSG"},   # Ondo OUSG
    {"project": "blackrock-buidl",   "symbol": "BUIDL"},  # BlackRock BUIDL
    {"project": "circle-usyc",       "symbol": "USYC"},   # Circle/Hashnote USYC
    {"project": "invesco-ustb",      "symbol": "USTB"},   # Superstate/Invesco USTB
    {"project": "openeden-tbill",    "symbol": "TBILL"},  # OpenEden TBILL
    {"project": "bitwise-uscc",      "symbol": "USCC"},   # Bitwise USCC
)

Fetcher = Callable[[str], object]


# ── schema validation (fail-CLOSED) ──────────────────────────────────────────────────────────
def _validate_pools(payload: object) -> List[dict]:
    if not isinstance(payload, dict):
        raise InvalidDataError(f"rwa pools: expected object, got {type(payload).__name__}")
    if payload.get("status") != "success":
        raise InvalidDataError(f"rwa pools: status={payload.get('status')!r}")
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        raise InvalidDataError("rwa pools: 'data' missing or empty")
    return data


def _qualifying_pools(pools: List[dict], tvl_floor: float) -> List[Tuple[str, float, float, str]]:
    """Return [(label, apy_pct, tvl_usd, pool_id)] for every selector that matched a pool with a
    sane apy AND tvl ≥ floor. Highest-TVL pool wins per (project, symbol). An issuer with no
    qualifying pool is simply absent (per-pool fail-closed); the overall emptiness check is the
    caller's job."""
    out: List[Tuple[str, float, float, str]] = []
    for sel in SELECTORS:
        proj, sym = sel["project"], sel["symbol"].upper()
        best: Optional[dict] = None
        best_tvl = float("-inf")
        for p in pools:
            if not isinstance(p, dict):
                continue
            if p.get("project") != proj:
                continue
            if (p.get("symbol") or "").upper() != sym:
                continue
            tvl = p.get("tvlUsd")
            tvl = float(tvl) if isinstance(tvl, (int, float)) else 0.0
            if tvl > best_tvl:
                best_tvl, best = tvl, p
        if best is None:
            continue
        apy = best.get("apy")
        tvl = best.get("tvlUsd")
        if not isinstance(apy, (int, float)) or not isinstance(tvl, (int, float)):
            continue
        apy = float(apy)
        tvl = float(tvl)
        if tvl < tvl_floor:
            continue
        if not (MIN_SANE_APY_PCT <= apy <= MAX_SANE_APY_PCT):
            continue
        pid = best.get("pool")
        pid = pid if isinstance(pid, str) else ""
        out.append((f"{proj}:{sym}", apy, tvl, pid))
    return out


def _tvl_weighted(rows: List[Tuple[str, float, float, str]]) -> float:
    """TVL-weighted mean APY (%) across qualifying pools. Caller guarantees rows non-empty."""
    total_tvl = sum(r[2] for r in rows)
    if total_tvl <= 0:
        raise InvalidDataError("rwa: qualifying pools have zero aggregate TVL")
    return sum(r[1] * r[2] for r in rows) / total_tvl


def _median(vals: List[float]) -> float:
    s = sorted(vals)
    n = len(s)
    mid = n // 2
    return float(s[mid]) if n % 2 == 1 else (s[mid - 1] + s[mid]) / 2.0


# ── atomic cache helpers ─────────────────────────────────────────────────────────────────────
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


def _read_cache(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:  # noqa: BLE001 — corrupt cache treated as absent (will refetch)
        return None


def _parse_floor_chart(payload: object, label: str) -> Dict[str, float]:
    """yields.llama.fi/chart/{pool} → {date(ISO): apy_pct}. One point per UTC day (last wins).
    Raises on bad schema; an empty/point-less chart is NOT fatal here (returns {})."""
    if not isinstance(payload, dict):
        raise InvalidDataError(f"rwa chart: expected object for {label}")
    if payload.get("status") != "success":
        raise InvalidDataError(f"rwa chart: status={payload.get('status')!r} for {label}")
    data = payload.get("data")
    if not isinstance(data, list):
        raise InvalidDataError(f"rwa chart: 'data' not a list for {label}")
    out: Dict[str, float] = {}
    for row in data:
        if not isinstance(row, dict):
            raise InvalidDataError(f"rwa chart: row not an object for {label}")
        ts = row.get("timestamp")
        apy = row.get("apy")
        if not isinstance(ts, str) or not ts:
            raise InvalidDataError(f"rwa chart: missing/invalid timestamp for {label}")
        if apy is None:
            continue  # a gap day in the pool's own history — skip, don't fabricate
        if not isinstance(apy, (int, float)) or apy < 0:
            raise InvalidDataError(f"rwa chart: invalid apy {apy!r} for {label}")
        try:
            d = (
                datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
                .astimezone(datetime.timezone.utc)
                .date()
                .isoformat()
            )
        except ValueError as exc:
            raise InvalidDataError(f"rwa chart: unparseable timestamp {ts!r} for {label}") from exc
        out[d] = round(float(apy), 6)
    return out


class RWAFeed:
    """Live tokenized-T-bill risk-free floor (APY %). Inject `fetcher` (url->json) in tests.

    `tvl_floor_usd` drops dust/mirror listings (default $5M). `min_pools` is the minimum number
    of qualifying issuer pools required before we trust the blend (default 2) — a single pool is
    not representative of the ~$15B market and is treated fail-closed."""

    def __init__(
        self,
        fetcher: Optional[Fetcher] = None,
        tvl_floor_usd: float = DEFAULT_TVL_FLOOR_USD,
        min_pools: int = 2,
        cache_path: Optional[Path] = None,
    ):
        self._fetch = fetcher or http_fetch
        self._tvl_floor = float(tvl_floor_usd)
        self._min_pools = int(min_pools)
        self._cache_path = Path(cache_path) if cache_path else _CACHE_PATH

    # ── compute (live) ──────────────────────────────────────────────────────────────────────
    def compute(self) -> Dict[str, object]:
        """Fetch /pools, match the tokenized-T-bill issuer pools, and return the blended floor.

        Returns a dict {floor_apy_pct, method, tvl_weighted_apy_pct, median_apy_pct, n_pools,
        total_tvl_usd, pools:[{label,apy_pct,tvl_usd,pool}], generated_at}. Schema-validates the
        payload (raises InvalidDataError on malformed). Raises InvalidDataError if fewer than
        `min_pools` pools qualify (fail-CLOSED — never a fabricated floor)."""
        pools = _validate_pools(self._fetch(POOLS_URL))
        rows = _qualifying_pools(pools, self._tvl_floor)
        if len(rows) < self._min_pools:
            raise InvalidDataError(
                f"rwa: only {len(rows)} tokenized-T-bill pool(s) qualified "
                f"(need ≥ {self._min_pools}, tvl_floor=${self._tvl_floor:,.0f})"
            )
        tvlw = _tvl_weighted(rows)
        med = _median([r[1] for r in rows])
        total_tvl = sum(r[2] for r in rows)
        return {
            "floor_apy_pct": round(tvlw, 6),
            "method": "tvl_weighted",
            "tvl_weighted_apy_pct": round(tvlw, 6),
            "median_apy_pct": round(med, 6),
            "n_pools": len(rows),
            "total_tvl_usd": round(total_tvl, 2),
            "pools": [
                {"label": r[0], "apy_pct": round(r[1], 6), "tvl_usd": round(r[2], 2), "pool": r[3]}
                for r in sorted(rows, key=lambda x: -x[2])
            ],
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

    # ── cache I/O ───────────────────────────────────────────────────────────────────────────
    def refresh(self) -> Dict[str, object]:
        """Compute the live floor and atomically write it to the cache. Returns the computed
        dict. Fail-CLOSED: a malformed/insufficient payload raises and NO cache is written."""
        result = self.compute()
        _atomic_write_json(self._cache_path, result)
        return result

    def cached(self) -> Optional[Dict[str, object]]:
        """Return the cached floor dict, or None if absent/corrupt. Does not fetch."""
        return _read_cache(self._cache_path)

    def current_rwa_floor_pct(self, max_age_hours: float = 24.0) -> float:
        """The current live tokenized-T-bill floor (%).

        Serves the cache when it is FRESH (younger than max_age_hours); otherwise refetches +
        rewrites the cache. Fail-CLOSED: if the fetch fails AND there is no cache, raises
        InvalidDataError — never fabricates. (config.rwa_floor_apy_pct catches this to fall
        back to the committed literal.)"""
        cache = self.cached()
        if cache is not None and self._is_fresh(cache, max_age_hours):
            return float(cache["floor_apy_pct"])
        try:
            return float(self.refresh()["floor_apy_pct"])
        except Exception:  # noqa: BLE001 — stale cache beats nothing; fail-closed if no cache
            if cache is not None and "floor_apy_pct" in cache:
                return float(cache["floor_apy_pct"])
            raise

    @staticmethod
    def _is_fresh(cache: dict, max_age_hours: float) -> bool:
        ts = cache.get("generated_at")
        if not isinstance(ts, str):
            return False
        try:
            gen = datetime.datetime.fromisoformat(ts)
        except ValueError:
            return False
        if gen.tzinfo is None:
            gen = gen.replace(tzinfo=datetime.timezone.utc)
        age = datetime.datetime.now(datetime.timezone.utc) - gen
        return age.total_seconds() <= max_age_hours * 3600.0

    # ── deep history ────────────────────────────────────────────────────────────────────────
    def history(self, start_date: str, end_date: str) -> Dict[str, float]:
        """Return {date(ISO): tvl_weighted_floor_apy_pct} over [start_date, end_date].

        Resolves the qualifying pools via /pools, fetches each pool's /chart APY series, and on
        every date computes the TVL-weighted mean across the pools that have a point that day
        (weights = the pools' current TVL, the best proxy we have for historical weighting).
        Schema-validates /pools and every chart (raises on malformed). Raises InvalidDataError
        if no qualifying pool produced any in-window point."""
        try:
            d0 = datetime.date.fromisoformat(start_date)
            d1 = datetime.date.fromisoformat(end_date)
        except ValueError as exc:
            raise InvalidDataError(
                f"rwa history: bad date(s) {start_date!r}..{end_date!r}"
            ) from exc
        if d1 < d0:
            raise InvalidDataError(f"rwa history: end {end_date} before start {start_date}")

        pools = _validate_pools(self._fetch(POOLS_URL))
        rows = _qualifying_pools(pools, self._tvl_floor)
        if len(rows) < self._min_pools:
            raise InvalidDataError(
                f"rwa history: only {len(rows)} tokenized-T-bill pool(s) qualified"
            )

        # per-pool {date: apy_pct} within the window, plus its TVL weight
        charts: List[Tuple[float, Dict[str, float]]] = []
        for label, _apy, tvl, pid in rows:
            if not pid:
                continue
            series = _parse_floor_chart(self._fetch(CHART_URL.format(pool=pid)), label)
            windowed = {d: a for d, a in series.items() if start_date <= d <= end_date}
            if windowed:
                charts.append((tvl, windowed))
        if not charts:
            raise InvalidDataError(
                f"rwa history: no qualifying pool chart had points in {start_date}..{end_date}"
            )

        # union of dates → TVL-weighted across pools present on each date
        all_dates = set()
        for _w, ser in charts:
            all_dates |= set(ser)
        out: Dict[str, float] = {}
        for d in sorted(all_dates):
            num = sum(w * ser[d] for w, ser in charts if d in ser)
            den = sum(w for w, ser in charts if d in ser)
            if den > 0:
                out[d] = round(num / den, 6)
        return out


# Module-level convenience (used by config wiring) ────────────────────────────────────────────
def current_rwa_floor_pct(max_age_hours: float = 24.0) -> float:
    """Live tokenized-T-bill floor (%) using the default cache. See RWAFeed.current_rwa_floor_pct."""
    return RWAFeed().current_rwa_floor_pct(max_age_hours=max_age_hours)


def history(start_date: str, end_date: str) -> Dict[str, float]:
    """Per-date TVL-weighted floor series. See RWAFeed.history."""
    return RWAFeed().history(start_date, end_date)


if __name__ == "__main__":  # manual real-network smoke test (run on the Mac)
    import socket

    socket.setdefaulttimeout(25)
    feed = RWAFeed()
    res = feed.compute()
    print(f"LIVE RWA floor = {res['floor_apy_pct']:.4f}%  "
          f"(tvl-weighted; median={res['median_apy_pct']:.4f}%; "
          f"n={res['n_pools']}; tvl=${res['total_tvl_usd']:,.0f})")
    for p in res["pools"]:
        print(f"  {p['label']:28} apy={p['apy_pct']:.4f}%  tvl=${p['tvl_usd']:,.0f}")
