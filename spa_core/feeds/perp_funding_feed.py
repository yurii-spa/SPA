"""
spa_core/feeds/perp_funding_feed.py — Hyperliquid perp funding rate feed.

Fetches live funding rates for ETH, BTC, SOL from Hyperliquid REST API.
No auth required. Stdlib only (urllib). Fail-safe: returns None on any error.
Output: data/perp_funding_rates.json

Design constraints (FORBIDDEN rules):
    * stdlib only — no external dependencies (requests, httpx, …)
    * Never raises — all errors are caught and logged; caller gets None
    * Never mocks — returns None when live data unavailable; no hardcoded funding
    * Atomic writes — tmp + os.replace via spa_core.utils.atomic
    * Ring buffer — history capped at HISTORY_MAX entries

Hyperliquid API contract (POST, JSON body, no auth):
    URL:  https://api.hyperliquid.xyz/info
    Body: {"type": "metaAndAssetCtxs"}
    Returns: [meta, assetCtxs]
      - meta.universe[i].name = coin name (e.g. "ETH")
      - assetCtxs[i].funding = hourly funding rate as string
      - assetCtxs[i].openInterest = string
      - assetCtxs[i].markPx = string
      - assetCtxs[i].premium = string (optional)
    Index alignment: assetCtxs[i] corresponds to meta.universe[i]

Annualization: funding_annual = float(funding_1h) * 8760
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("spa.feeds.bts")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HYPERLIQUID_INFO_URL: str = "https://api.hyperliquid.xyz/info"

TRACKED_ASSETS: tuple = ("ETH", "BTC", "SOL", "ARB")

DATA_FILE: str = "perp_funding_rates.json"

HISTORY_FILE: str = "perp_funding_rate_history.json"

HISTORY_MAX: int = 96

STALE_AFTER_S: int = 3600

REQUEST_TIMEOUT: int = 10

MAX_RETRIES: int = 3

BACKOFF_BASE: float = 1.0

HOURS_PER_YEAR: int = 8760

_USER_AGENTS: list = [
    "Mozilla/5.0 (compatible; SPA-funding-tracker/1.0)",
    (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "curl/7.88.1",
]


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class PerpFundingRate:
    """Normalized funding rate for one asset."""

    asset: str
    funding_rate_1h: float
    funding_rate_8h: float
    funding_rate_annual: float
    open_interest_usd: float
    mark_price: float
    premium: float
    timestamp: str

    def to_dict(self) -> dict:
        return {
            "funding_rate_1h": self.funding_rate_1h,
            "funding_rate_8h": self.funding_rate_8h,
            "funding_rate_annual": self.funding_rate_annual,
            "open_interest_usd": self.open_interest_usd,
            "mark_price": self.mark_price,
            "premium": self.premium,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Atomic helpers (reuse centralized module when available)
# ---------------------------------------------------------------------------


def _atomic_save(data: Any, path: str) -> None:
    """Atomic JSON write via tmp + os.replace."""
    try:
        from spa_core.utils.atomic import atomic_save
        atomic_save(data, path)
    except ImportError:
        _dir = os.path.dirname(os.path.abspath(path)) or "."
        os.makedirs(_dir, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp, path)


def _atomic_load(path: str, default: Any = None) -> Any:
    """Load JSON, return default on any error."""
    try:
        from spa_core.utils.atomic import atomic_load
        return atomic_load(path, default=default if default is not None else {})
    except ImportError:
        pass
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


# ---------------------------------------------------------------------------
# PerpFundingFeed
# ---------------------------------------------------------------------------


class PerpFundingFeed:
    """Hyperliquid perp funding rate feed with retry/backoff.

    Fetches live funding rates for tracked assets (ETH, BTC, SOL, ARB).
    Writes data/perp_funding_rates.json atomically. Never raises.
    """

    def __init__(
        self,
        info_url: str = HYPERLIQUID_INFO_URL,
        assets: tuple = TRACKED_ASSETS,
        data_dir: Optional[Path] = None,
        timeout: int = REQUEST_TIMEOUT,
        enabled: bool = True,
    ) -> None:
        self.info_url = info_url
        self.assets = assets
        self.data_dir = Path(data_dir) if data_dir else Path("data")
        self.data_file = self.data_dir / DATA_FILE
        self.history_file = self.data_dir / HISTORY_FILE
        self.timeout = timeout
        self.enabled = enabled

    # ── network (stdlib urllib, POST) ──

    def _post_info(self, body: dict) -> Optional[bytes]:
        """POST JSON to Hyperliquid with retry/backoff. None on failure."""
        payload = json.dumps(body).encode("utf-8")
        for attempt in range(MAX_RETRIES):
            try:
                ua = _USER_AGENTS[attempt % len(_USER_AGENTS)]
                req = urllib.request.Request(
                    self.info_url,
                    data=payload,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": ua,
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read()
                    encoding = resp.headers.get("Content-Encoding", "")
                    if encoding == "gzip":
                        import gzip
                        raw = gzip.decompress(raw)
                    return raw
            except Exception as exc:
                delay = BACKOFF_BASE * (2 ** attempt)
                logger.warning(
                    "Hyperliquid POST attempt %d/%d failed: %s — backoff %.1fs",
                    attempt + 1, MAX_RETRIES, exc, delay,
                )
                if attempt < MAX_RETRIES - 1:
                    time.sleep(delay)
        return None

    def _fetch_meta_and_ctxs(self) -> Optional[tuple]:
        """Return (universe, assetCtxs) or None."""
        raw = self._post_info({"type": "metaAndAssetCtxs"})
        if raw is None:
            return None
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, list) or len(parsed) < 2:
                logger.error("Unexpected Hyperliquid response shape: %s", type(parsed))
                return None
            meta = parsed[0]
            ctxs = parsed[1]
            universe = meta.get("universe", []) if isinstance(meta, dict) else meta
            return (universe, ctxs)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.error("Failed to parse Hyperliquid response: %s", exc)
            return None

    # ── normalization ──

    @staticmethod
    def _annualize(funding_1h: float) -> float:
        """Annualize hourly funding rate."""
        return round(funding_1h * HOURS_PER_YEAR, 8)

    def _normalize(self, universe: list, ctxs: list) -> List[PerpFundingRate]:
        """Map tracked assets to PerpFundingRate. Skips missing/malformed."""
        asset_index: Dict[str, int] = {}
        for i, item in enumerate(universe):
            name = item.get("name", "") if isinstance(item, dict) else str(item)
            asset_index[name] = i

        now_iso = datetime.now(timezone.utc).isoformat()
        results = []
        for asset in self.assets:
            idx = asset_index.get(asset)
            if idx is None or idx >= len(ctxs):
                continue
            ctx = ctxs[idx]
            if not isinstance(ctx, dict):
                continue
            try:
                funding_1h = float(ctx.get("funding", "0"))
                oi_raw = ctx.get("openInterest", "0")
                mark_raw = ctx.get("markPx", "0")
                premium_raw = ctx.get("premium", "0")

                mark_price = float(mark_raw)
                oi_coins = float(oi_raw)
                oi_usd = oi_coins * mark_price
                premium = float(premium_raw)

                results.append(PerpFundingRate(
                    asset=asset,
                    funding_rate_1h=funding_1h,
                    funding_rate_8h=round(funding_1h * 8, 8),
                    funding_rate_annual=self._annualize(funding_1h),
                    open_interest_usd=round(oi_usd, 2),
                    mark_price=mark_price,
                    premium=premium,
                    timestamp=now_iso,
                ))
            except (ValueError, TypeError) as exc:
                logger.warning("Failed to normalize %s: %s", asset, exc)
                continue
        return results

    # ── public API ──

    def fetch(self) -> Optional[List[PerpFundingRate]]:
        """Live fetch + normalize. None if Hyperliquid unreachable."""
        if not self.enabled:
            return None
        try:
            result = self._fetch_meta_and_ctxs()
            if result is None:
                return None
            universe, ctxs = result
            rates = self._normalize(universe, ctxs)
            return rates if rates else None
        except Exception as exc:
            logger.error("Unexpected error in fetch(): %s", exc)
            return None

    def get_rate(self, asset: str) -> Optional[float]:
        """funding_rate_annual for one asset. Reads cache first, fetches if stale."""
        try:
            data = self.load()
            if data and not data.get("stale", True):
                assets = data.get("assets", {})
                if asset in assets:
                    return assets[asset].get("funding_rate_annual")
        except Exception:
            pass
        rates = self.fetch()
        if rates is None:
            return None
        for r in rates:
            if r.asset == asset:
                return r.funding_rate_annual
        return None

    def run(self) -> dict:
        """Fetch → write data/perp_funding_rates.json + history ring. Returns payload."""
        rates = self.fetch()
        now_iso = datetime.now(timezone.utc).isoformat()
        fetched_at = time.time()

        if rates is not None:
            assets_dict = {r.asset: r.to_dict() for r in rates}
            payload = {
                "timestamp": now_iso,
                "fetched_at": fetched_at,
                "stale": False,
                "assets": assets_dict,
            }
            logger.info(
                "Fetched funding rates for %d assets: %s",
                len(rates), ", ".join(r.asset for r in rates),
            )
        else:
            last = self.load()
            payload = {
                "timestamp": now_iso,
                "fetched_at": fetched_at,
                "stale": True,
                "error": "All Hyperliquid retries failed",
                "assets": last.get("assets", {}) if last else {},
            }
            logger.warning("All retries failed — writing stale payload")

        self.data_dir.mkdir(parents=True, exist_ok=True)
        _atomic_save(payload, str(self.data_file))

        self._append_history(payload)

        return payload

    def _append_history(self, payload: dict) -> None:
        """Append snapshot to ring-buffer history file."""
        try:
            history = _atomic_load(str(self.history_file), default=[])
            if not isinstance(history, list):
                history = []
            snapshot = {
                "timestamp": payload.get("timestamp", ""),
                "fetched_at": payload.get("fetched_at", 0),
                "stale": payload.get("stale", True),
            }
            for asset, info in payload.get("assets", {}).items():
                if isinstance(info, dict):
                    snapshot[asset] = info.get("funding_rate_annual", 0.0)
                else:
                    snapshot[asset] = 0.0
            history.append(snapshot)
            if len(history) > HISTORY_MAX:
                history = history[-HISTORY_MAX:]
            _atomic_save(history, str(self.history_file))
        except Exception as exc:
            logger.warning("Failed to append history: %s", exc)

    def load(self) -> dict:
        """Read data/perp_funding_rates.json, {} on error. Sets stale by age."""
        try:
            data = _atomic_load(str(self.data_file), default={})
            if not data:
                return {}
            fetched_at = data.get("fetched_at", 0)
            if fetched_at and (time.time() - fetched_at) > STALE_AFTER_S:
                data["stale"] = True
            return data
        except Exception:
            return {}


# ---------------------------------------------------------------------------
# Module-level convenience API
# ---------------------------------------------------------------------------

_SINGLETON: Optional[PerpFundingFeed] = None


def _get_feed(data_dir: Optional[Path] = None) -> PerpFundingFeed:
    """Get or create singleton feed instance."""
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = PerpFundingFeed(data_dir=data_dir)
    return _SINGLETON


def fetch_and_save(data_dir: Optional[Path] = None) -> Optional[dict]:
    """Fetch live rates and save to disk. Returns payload or None."""
    try:
        feed = PerpFundingFeed(data_dir=data_dir or Path("data"))
        result = feed.run()
        return result
    except Exception as exc:
        logger.error("fetch_and_save failed: %s", exc)
        return None


def get_funding_annual(asset: str, data_dir: Optional[Path] = None) -> Optional[float]:
    """Get annualized funding rate for an asset from cached data."""
    try:
        feed = PerpFundingFeed(data_dir=data_dir or Path("data"))
        data = feed.load()
        if not data or data.get("stale", True):
            return None
        assets = data.get("assets", {})
        info = assets.get(asset, {})
        if isinstance(info, dict):
            return info.get("funding_rate_annual")
        return None
    except Exception:
        return None


def load_latest(data_dir: Optional[Path] = None) -> dict:
    """Load latest funding data from disk."""
    try:
        feed = PerpFundingFeed(data_dir=data_dir or Path("data"))
        return feed.load()
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main() -> None:
    """CLI entry point: --run (fetch+write) or --show (read-only)."""
    import argparse
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="Hyperliquid perp funding feed")
    parser.add_argument("--run", action="store_true", help="Fetch and write to data/")
    parser.add_argument("--show", action="store_true", help="Show current cached data")
    parser.add_argument("--data-dir", default="data", help="Data directory")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)

    if args.run:
        result = fetch_and_save(data_dir)
        if result:
            print(json.dumps(result, indent=2))
            sys.exit(0)
        else:
            print("ERROR: fetch failed", file=sys.stderr)
            sys.exit(1)
    elif args.show:
        data = load_latest(data_dir)
        print(json.dumps(data, indent=2))
    else:
        parser.print_help()


if __name__ == "__main__":
    _main()
