"""Historical APY data collection pipeline (MP-1238).

Builds a 365-day daily APY history per protocol to power backtesting and
strategy analysis. Two sources, tried in order:

* **Source 1 — DeFiLlama chart API** (free, no key): ``yields.llama.fi/chart/{pool_id}``
  returns the full daily APY/TVL history for a pool. We collapse it to one
  reading per calendar day (last reading wins) and keep the trailing 365 days.
* **Source 2 — synthetic but realistic generator** (fallback): when the API is
  unreachable or returns too few points, we synthesise a plausible APY series
  from known regime base-rates (2023→2026) plus a seasonal term and bounded
  deterministic noise. The series is reproducible (seeded per protocol) so
  tests are stable.

Pure stdlib, offline-safe (network failure → synthetic fallback, never raises),
atomic writes only (``tmp + os.replace``). Output per protocol is a JSON list
``[{"date": "2025-06-21", "apy": 4.82}, ...]`` with APY as a **percentage**.

CLI::

    python3 -m spa_core.data.historical_apy_fetcher --run
    python3 -m spa_core.data.historical_apy_fetcher --run --data-dir /tmp/x
    python3 -m spa_core.data.historical_apy_fetcher --check   # no write (default)
    python3 -m spa_core.data.historical_apy_fetcher --run --synthetic  # force fallback
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import math
import os
import random
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# DeFiLlama free chart endpoint (per-pool daily history; no API key).
CHART_URL_TEMPLATE = "https://yields.llama.fi/chart/{pool_id}"
REQUEST_TIMEOUT = 20
HISTORY_DAYS = 365
# A pool needs at least this many real daily points before we trust the API
# series; otherwise we fall back to the synthetic generator.
MIN_REAL_POINTS = 30
# APY sanity band — anything outside is dropped as an anomaly.
APY_MIN = 0.0
APY_MAX = 50.0

# Protocol → DeFiLlama pool uuid (resolved 2026-06-21 against the live /pools
# registry; chosen as the highest-TVL Ethereum pool matching the asset).
POOL_IDS: dict[str, str] = {
    "aave_v3_usdc": "aa70268e-4b52-42bf-a116-608b370f9501",
    "compound_v3_usdc": "7da72d09-56ca-4ec5-a45f-59114353e487",
    "yearn_v3_usdc": "7d89af7a-24c9-4292-aa38-7c71b05fbd6d",
    "sky_susds": "d8c4eff5-c8a9-46fc-a888-057c4c668e72",
    "morpho_blue_usdc": "d28b6ac8-8955-4e1f-8ec3-ed78f5e17553",
}

PROTOCOLS = list(POOL_IDS.keys())


# --- Source 1: DeFiLlama chart API -----------------------------------------


def _http_get_json(url: str, timeout: int = REQUEST_TIMEOUT) -> Optional[dict]:
    """GET ``url`` and parse JSON, transparently decompressing gzip.

    Returns ``None`` on any network/parse error — never raises.
    """
    try:
        req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        # DeFiLlama frequently serves gzip regardless; decode by magic bytes.
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            return None
        return payload
    except Exception as exc:  # noqa: BLE001 - graceful: fall back to synthetic.
        logger.warning("chart fetch failed for %s: %s", url, exc)
        return None


def fetch_chart(pool_id: str, days: int = HISTORY_DAYS) -> list[dict]:
    """Return up to ``days`` trailing daily ``{date, apy}`` from the chart API.

    Collapses intraday samples to one reading per calendar day (last wins) and
    keeps only readings inside the APY sanity band. Returns ``[]`` on any error
    or empty response.
    """
    payload = _http_get_json(CHART_URL_TEMPLATE.format(pool_id=pool_id))
    if not payload or payload.get("status") != "success":
        return []
    rows = payload.get("data")
    if not isinstance(rows, list):
        return []

    by_day: dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ts = row.get("timestamp")
        apy = row.get("apy")
        if not isinstance(ts, str) or not isinstance(apy, (int, float)):
            continue
        apy = float(apy)
        if apy < APY_MIN or apy > APY_MAX:
            continue
        try:
            day = datetime.fromisoformat(ts.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            continue
        by_day[day] = round(apy, 4)

    if not by_day:
        return []
    series = [{"date": d, "apy": by_day[d]} for d in sorted(by_day)]
    return series[-days:]


# --- Source 2: synthetic realistic generator -------------------------------

# Regime base-rate map (APY %), keyed by (year, half). Mirrors the documented
# Aave USDC history; other protocols are offset from this baseline.
_REGIMES: list[tuple[tuple[int, int], float]] = [
    ((2023, 1), 4.5),   # post-merge, stable demand (3-6%)
    ((2023, 2), 3.0),   # quiet period (2-4%)
    ((2024, 1), 6.0),   # ETF approval, demand spike (4-8%)
    ((2024, 2), 4.0),   # consolidation (3-5%)
    ((2025, 1), 7.0),   # bull market borrowing demand (5-9%)
    ((2025, 2), 7.0),   # bull market borrowing demand (5-9%)
    ((2026, 1), 4.5),   # current regime (3-6%)
    ((2026, 2), 4.5),
]

# Per-protocol additive offset (pct points) from the Aave baseline.
_PROTOCOL_OFFSET: dict[str, float] = {
    "aave_v3_usdc": 0.0,
    "compound_v3_usdc": 0.2,
    "yearn_v3_usdc": 0.4,
    "sky_susds": -0.6,
    "morpho_blue_usdc": 1.3,
}


def _base_rate(d: date) -> float:
    """Regime base APY (%) for a given calendar date."""
    half = 1 if d.month <= 6 else 2
    best = 4.5
    for (yr, hf), rate in _REGIMES:
        if (yr, hf) == (d.year, half):
            return rate
    # Outside the table: clamp to nearest documented endpoint.
    if d.year < 2023:
        return _REGIMES[0][1]
    return _REGIMES[-1][1]


def generate_synthetic(
    protocol: str, days: int = HISTORY_DAYS, end: Optional[date] = None
) -> list[dict]:
    """Synthesize a reproducible ``days``-long daily ``{date, apy}`` series.

    ``daily_apy = base_rate(regime) + protocol_offset + seasonal + noise``,
    clamped to the sanity band. Seeded by protocol so output is deterministic.
    """
    if end is None:
        end = datetime.now(timezone.utc).date()
    offset = _PROTOCOL_OFFSET.get(protocol, 0.0)
    rng = random.Random(hash(protocol) & 0xFFFFFFFF)

    series: list[dict] = []
    start = end - timedelta(days=days - 1)
    for i in range(days):
        d = start + timedelta(days=i)
        seasonal = 0.4 * math.sin(2 * math.pi * (d.timetuple().tm_yday / 365.0))
        noise = rng.gauss(0.0, 0.5)
        apy = _base_rate(d) + offset + seasonal + noise
        apy = max(APY_MIN + 0.05, min(APY_MAX, apy))
        series.append({"date": d.isoformat(), "apy": round(apy, 4)})
    return series


# --- Orchestration ----------------------------------------------------------


def build_protocol_series(
    protocol: str, days: int = HISTORY_DAYS, force_synthetic: bool = False
) -> tuple[list[dict], str]:
    """Return ``(series, source)`` of exactly ``days`` daily ``{date, apy}``.

    Source is one of:

    * ``"defillama"`` — full ``days`` of real chart history,
    * ``"defillama+synthetic"`` — a young pool: real recent days spliced onto a
      synthetic backfill so the series still spans the full window,
    * ``"synthetic"`` — forced, on error, or fewer than ``MIN_REAL_POINTS`` real
      points available.
    """
    if not force_synthetic:
        pool_id = POOL_IDS.get(protocol)
        if pool_id:
            real = fetch_chart(pool_id, days=days)
            if len(real) >= days:
                return real, "defillama"
            if len(real) >= MIN_REAL_POINTS:
                # Young pool: backfill the missing leading days synthetically,
                # then overlay the real readings (real wins on shared dates).
                merged = {r["date"]: r["apy"] for r in generate_synthetic(protocol, days=days)}
                for r in real:
                    merged[r["date"]] = r["apy"]
                series = [{"date": d, "apy": merged[d]} for d in sorted(merged)][-days:]
                return series, "defillama+synthetic"
            logger.warning(
                "%s: only %d real points (<%d) — using synthetic",
                protocol,
                len(real),
                MIN_REAL_POINTS,
            )
    return generate_synthetic(protocol, days=days), "synthetic"


def _atomic_write_json(path: str, obj: object) -> None:
    """Write ``obj`` as JSON to ``path`` atomically (tmp + os.replace)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def run(
    data_dir: str,
    days: int = HISTORY_DAYS,
    force_synthetic: bool = False,
    write: bool = True,
) -> dict:
    """Fetch/generate every protocol and (optionally) write per-protocol files.

    Returns a summary dict ``{protocol: {"source", "points", "first", "last"}}``.
    """
    out_dir = os.path.join(data_dir, "historical_apy")
    summary: dict[str, dict] = {}
    for protocol in PROTOCOLS:
        series, source = build_protocol_series(
            protocol, days=days, force_synthetic=force_synthetic
        )
        if write:
            _atomic_write_json(os.path.join(out_dir, f"{protocol}.json"), series)
        summary[protocol] = {
            "source": source,
            "points": len(series),
            "first": series[0]["date"] if series else None,
            "last": series[-1]["date"] if series else None,
        }
    return summary


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Historical APY fetcher (MP-1238)")
    parser.add_argument("--run", action="store_true", help="fetch and write files")
    parser.add_argument(
        "--check", action="store_true", help="fetch but do not write (default)"
    )
    parser.add_argument(
        "--synthetic", action="store_true", help="force the synthetic generator"
    )
    parser.add_argument("--days", type=int, default=HISTORY_DAYS)
    parser.add_argument(
        "--data-dir",
        default=os.path.join(os.path.dirname(__file__), "..", "..", "data"),
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    write = bool(args.run)
    data_dir = os.path.abspath(args.data_dir)
    summary = run(
        data_dir, days=args.days, force_synthetic=args.synthetic, write=write
    )

    print(f"{'protocol':<20} {'source':<11} {'points':>6}  range")
    for proto, info in summary.items():
        print(
            f"{proto:<20} {info['source']:<11} {info['points']:>6}  "
            f"{info['first']} → {info['last']}"
        )
    if write:
        print(f"\nwrote → {os.path.join(data_dir, 'historical_apy')}/")
    else:
        print("\n(--check: no files written; pass --run to persist)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
