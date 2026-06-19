"""
Real-Time Stablecoin Price Feeds (FEAT-006 Phase 2).

Pure-Python scaffold mirroring aave_v3_adapter.py / compound_v3_adapter.py
Phase 2 pattern:
  - Env-driven, 3-RPC fallback per coin (Chainlink / Pyth / RedStone)
  - Synthetic generator (deterministic gaussian noise around $1.00)
  - JSON dump for dashboard consumption (data/price_feeds.json)
  - No external deps; only stdlib (urllib, json, random, pathlib)

Phase 1 (shipped v3.0):
  * PriceFeedFetcher with synthetic generator (always works)
  * RPC fallback chain skeleton — returned None until Phase 2

Phase 2 (this file, v3.8):
  * Real Chainlink AggregatorV3.latestAnswer() decoding for the [0] endpoint
    of each coin (URL fragment "#chainlink:<feed_address>" carries the
    Aggregator contract). USDC/USDT/DAI Chainlink mainnet feeds all use
    8 decimals so we divide the int256 answer by 1e8.
  * Pyth / RedStone endpoints (slots [1] + [2]) remain pass-through None —
    they require different decoders and are deferred to a later sprint.
  * 3-RPC fallback round-robin via _fetch_price_rpc (per-endpoint),
    plus per-coin synthetic backup at the fetch_prices level.
  * Production safety: ALL live-path exceptions are caught and logged as
    [FALLBACK] WARNING, returning None so the next endpoint tries; if all
    three fail, the coin falls back to its synthetic backup. The pipeline
    never crashes if every RPC flakes.

Phase 3 (already shipped v3.1 — SPA-V31-001):
  * detect_depeg() wired into risk/policy.py kill-switch.

Depeg severity tiers (DEFAULT_DEPEG_THRESHOLD = 0.02):
  WARN     — |deviation| ∈ [2%, 4%)
  CRITICAL — |deviation| ≥ 4%
"""
from __future__ import annotations

import json
import logging
import random
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from spa_core.utils.errors import SourceError

log = logging.getLogger("spa.price_feeds")

# Output path (relative to repo root data/)
_DATA_DIR = Path(__file__).parent.parent.parent / "data"


class PriceFeedFetcher:
    """
    Fetch stablecoin spot prices with 3-RPC fallback (Chainlink/Pyth/RedStone)
    and a deterministic synthetic fallback for tests / offline runs.

    Phase 2 status:
      * ``fetch_prices(use_synthetic=False)`` with ``dry_run=False`` performs
        real on-chain ``eth_call`` requests to Chainlink AggregatorV3
        contracts for the [0] endpoint of each coin. Failures degrade to
        the next endpoint, and ultimately to the deterministic synthetic
        backup (logged WARNING with the ``[FALLBACK]`` tag) so the
        production pipeline never crashes if an RPC is unreachable.
      * Pyth / RedStone endpoints (slots [1] + [2]) still return None —
        their decoders are deferred to a follow-up sprint. They remain in
        the registry so the operator can see the intended fallback order.

    Fallback policy (live read methods):
      Per endpoint: any exception (network, timeout, malformed JSON-RPC,
      bad return data, etc.) is caught, logged at DEBUG, and the next
      endpoint is tried. At the ``fetch_prices`` level, if every endpoint
      for a coin yields None, that coin's price is taken from the
      deterministic synthetic generator. Callers always receive a finite
      float for every stablecoin and never see a raised exception from the
      live path.
    """

    # ─── Class constants ──────────────────────────────────────────────────────

    STABLECOINS: list[str] = ["USDC", "USDT", "DAI", "USDS"]

    # 2% deviation from $1.00 triggers WARN; 4% triggers CRITICAL
    DEFAULT_DEPEG_THRESHOLD: float = 0.02

    # Three RPC endpoints per coin — tried in order, first success wins.
    # The URL fragment "#chainlink:<feed_address>" carries the Aggregator
    # contract address for the Phase 2 eth_call (the fragment is stripped
    # before posting JSON-RPC). Pyth / RedStone gateway URLs remain as
    # forward-looking placeholders — their decoders ship in a later phase.
    RPC_ENDPOINTS: dict[str, list[str]] = {
        "USDC": [
            # Chainlink USDC/USD on Ethereum mainnet
            "https://eth.llamarpc.com#chainlink:0x8fFfFfd4AfB6115b954Bd326cbe7B4BA576818f6",
            # Pyth Hermes price service (price_id placeholder)
            "https://hermes.pyth.network/api/latest_price_feeds?ids[]=USDC",
            # RedStone gateway (symbol-based query placeholder)
            "https://api.redstone.finance/prices?symbol=USDC&provider=redstone",
        ],
        "USDT": [
            # Chainlink USDT/USD on Ethereum mainnet
            "https://eth.llamarpc.com#chainlink:0x3E7d1eAB13ad0104d2750B8863b489D65364e32D",
            "https://hermes.pyth.network/api/latest_price_feeds?ids[]=USDT",
            "https://api.redstone.finance/prices?symbol=USDT&provider=redstone",
        ],
        "DAI": [
            # Chainlink DAI/USD on Ethereum mainnet
            "https://eth.llamarpc.com#chainlink:0xAed0c38402a5d19df6E4c03F4E2DceD6e29c1ee9",
            "https://hermes.pyth.network/api/latest_price_feeds?ids[]=DAI",
            "https://api.redstone.finance/prices?symbol=DAI&provider=redstone",
        ],
        "USDS": [
            # USDS Chainlink feed (placeholder — feed may not exist on mainnet yet)
            "https://eth.llamarpc.com#chainlink:0x0000000000000000000000000000000000000000",
            "https://hermes.pyth.network/api/latest_price_feeds?ids[]=USDS",
            "https://api.redstone.finance/prices?symbol=USDS&provider=redstone",
        ],
    }

    # Function selectors (first 4 bytes of keccak256). Hardcoded so we
    # don't pull in an external keccak dependency.
    SELECTOR_LATEST_ANSWER: str = "0x50d25bcd"  # AggregatorV3.latestAnswer()

    # All Chainlink USDC/USDT/DAI USD feeds on Ethereum mainnet use 8 decimals.
    # If a future feed disagrees we can promote this to a per-feed dict, but
    # mirroring real on-chain config is sufficient for the current scope.
    CHAINLINK_DECIMALS: int = 8

    # JSON-RPC timeout (seconds) per endpoint try.
    RPC_TIMEOUT_SECONDS: float = 5.0

    # ─── Construction ─────────────────────────────────────────────────────────

    def __init__(self, dry_run: bool = True) -> None:
        """Initialise the price feed fetcher.

        Args:
            dry_run: If True (default) every RPC call short-circuits to None
                so the synthetic fallback is used — byte-identical to the
                Phase 1 behaviour. If False, the Chainlink leg of the
                fallback chain performs real eth_call requests; Pyth /
                RedStone legs still return None until their decoders ship.
        """
        self.dry_run = dry_run
        log.debug("PriceFeedFetcher init: dry_run=%s", self.dry_run)

    # ─── Synthetic generator ──────────────────────────────────────────────────

    def fetch_prices_synthetic(self, seed: int = 42) -> dict[str, float]:
        """
        Return deterministic synthetic prices for every stablecoin.

        Each price is ~1.00 + gaussian noise (mu=0, sigma=0.001), so they
        live well within the default ±2% depeg band. The output is fully
        determined by ``seed`` — same seed → same dict.
        """
        rng = random.Random(seed)
        return {
            sym: round(1.0 + rng.gauss(0.0, 0.001), 6)
            for sym in self.STABLECOINS
        }

    # ─── Phase 2: stdlib JSON-RPC helpers ─────────────────────────────────────

    @staticmethod
    def _strip_fragment_with_hint(url: str) -> tuple[str, str | None]:
        """Return ``(clean_url, hint_string)``.

        The class-level RPC_ENDPOINTS attach a ``#chainlink:0x...`` (or other
        provider) hint to each URL so the dispatch in ``_fetch_price_rpc``
        can route to the right decoder. JSON-RPC servers reject fragments,
        so we strip before posting. ``hint_string`` is the raw fragment text
        (e.g. ``"chainlink:0x8fFfFf..."``) or None when no fragment present.
        """
        idx = url.find("#")
        if idx == -1:
            return url, None
        return url[:idx], url[idx + 1:]

    @staticmethod
    def _pad_address(address: str) -> str:
        """Left-pad a 20-byte hex address to 32 bytes (no ``0x`` prefix)."""
        clean = address[2:] if address.lower().startswith("0x") else address
        return clean.lower().rjust(64, "0")

    def _eth_call(self, rpc_url: str, to: str, data: str) -> str:
        """Post a JSON-RPC ``eth_call`` and return the raw hex result.

        Stdlib-only: ``urllib.request`` + ``json``. 5-second timeout per call.
        Logs the RPC URL + selector at DEBUG.

        Args:
            rpc_url: Full JSON-RPC endpoint URL (URL fragment must already
                be stripped by the caller).
            to: Target contract address (``0x...``).
            data: ABI-encoded calldata (``0xSELECTOR + ARGS``).

        Returns:
            Raw hex string returned by the RPC (``0x...``).

        Raises:
            RuntimeError: On HTTP error, timeout, JSON-RPC error envelope,
                or missing ``result`` field.
        """
        selector = data[:10] if len(data) >= 10 else data
        log.debug("eth_call rpc=%s selector=%s to=%s", rpc_url, selector, to)

        payload = {
            "jsonrpc": "2.0",
            "id":      1,
            "method":  "eth_call",
            "params":  [
                {"to": to, "data": data},
                "latest",
            ],
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            rpc_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                req, timeout=self.RPC_TIMEOUT_SECONDS,
            ) as resp:
                raw = resp.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise SourceError("chainlink_rpc", f"eth_call HTTP failure: {exc}") from exc

        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise SourceError("chainlink_rpc", f"eth_call malformed JSON: {exc}") from exc

        if "error" in parsed:
            raise SourceError("chainlink_rpc", f"eth_call RPC error: {parsed['error']}")
        result = parsed.get("result")
        if not isinstance(result, str) or not result.startswith("0x"):
            raise SourceError("chainlink_rpc", f"eth_call missing/invalid result: {parsed!r}")
        return result

    @staticmethod
    def _decode_chainlink_answer(
        hex_result: str, decimals: int = 8,
    ) -> float:
        """Decode a Chainlink ``latestAnswer()`` int256 hex string.

        Args:
            hex_result: Raw hex returned by the eth_call (``0x...``). Must
                be a single 32-byte slot encoding a signed int256.
            decimals: Number of decimals the feed scales the answer by.
                USDC/USDT/DAI USD feeds on Ethereum mainnet all use 8.

        Returns:
            The decoded price as a float ($1.00-scale).

        Raises:
            RuntimeError: If the hex is malformed or too short.
        """
        body = hex_result[2:] if hex_result.startswith("0x") else hex_result
        if len(body) < 64:
            raise SourceError(
                "chainlink_rpc",
                f"latestAnswer return too short: {len(body)} hex chars",
            )
        # Take the last 32-byte slot in case the RPC returned extra padding.
        slot = body[-64:]
        raw = int(slot, 16)
        # Chainlink answers are int256 (signed). Convert two's-complement.
        if raw >= (1 << 255):
            raw -= 1 << 256
        return raw / float(10 ** decimals)

    # ─── RPC fallback chain ───────────────────────────────────────────────────

    def _fetch_price_rpc(
        self, symbol: str, rpc_url: str, timeout: int = 5,
    ) -> float | None:
        """
        Attempt to fetch a single stablecoin price from one RPC endpoint.

        Routing:
          * URL fragment ``#chainlink:<addr>`` → eth_call latestAnswer()
            on ``<addr>``, divide by 10**CHAINLINK_DECIMALS.
          * Any other fragment (Pyth / RedStone gateway URLs) → return None
            for now; their decoders are deferred to a later phase. The
            registry entries remain so the operator sees the intended
            fallback order.
          * No fragment at all → return None (cannot dispatch).

        Production safety: every exception raised inside this method is
        caught and logged at DEBUG; the method returns None so the caller
        can fall through to the next endpoint (and ultimately to synthetic).
        """
        # Phase 1 byte-identical behaviour: dry_run short-circuits.
        if self.dry_run:
            log.debug(
                "_fetch_price_rpc dry_run=True; returning None for %s @ %s",
                symbol, rpc_url,
            )
            return None

        try:
            clean_url, hint = self._strip_fragment_with_hint(rpc_url)
            if hint is None:
                log.debug(
                    "%s @ %s: no provider hint, skipping", symbol, rpc_url,
                )
                return None

            if hint.startswith("chainlink:"):
                feed_addr = hint[len("chainlink:"):]
                # Zero-address placeholder (e.g. USDS feed not deployed
                # yet) — short-circuit so we don't waste the timeout.
                if int(feed_addr, 16) == 0:
                    log.debug(
                        "%s @ %s: zero-address chainlink placeholder, "
                        "skipping",
                        symbol, rpc_url,
                    )
                    return None
                hex_result = self._eth_call(
                    clean_url, feed_addr, self.SELECTOR_LATEST_ANSWER,
                )
                price = self._decode_chainlink_answer(
                    hex_result, decimals=self.CHAINLINK_DECIMALS,
                )
                # Sanity gate: a stablecoin price must be a finite positive
                # number — anything else is RPC garbage we should reject so
                # the next endpoint can try.
                if price <= 0 or price > 1000:
                    raise SourceError(
                        "chainlink_rpc",
                        f"sanity-fail decoded price {price!r} for {symbol}",
                    )
                return price

            # Pyth / RedStone HTTP decoders deferred. Keep stub returning
            # None so the fallback chain continues.
            log.debug(
                "%s @ %s: provider %r not yet wired",
                symbol, rpc_url, hint.split(":", 1)[0],
            )
            return None

        except Exception as exc:  # noqa: BLE001 — production safety
            log.warning(
                "[FALLBACK] _fetch_price_rpc failed %s @ %s: %s",
                symbol, rpc_url, exc,
            )
            return None

    def fetch_prices(self, use_synthetic: bool = True) -> dict[str, float]:
        """
        Fetch live stablecoin prices.

        Args:
            use_synthetic: if True (default), short-circuit to the
                deterministic synthetic generator. If False, attempt the
                3-RPC fallback chain per stablecoin; if all three endpoints
                fail for a given coin, that coin's price is taken from the
                synthetic generator.

        Returns:
            dict mapping each STABLECOIN symbol to its spot price (USD).
        """
        if use_synthetic:
            return self.fetch_prices_synthetic()

        synthetic_backup = self.fetch_prices_synthetic()
        prices: dict[str, float] = {}
        for sym in self.STABLECOINS:
            endpoints = self.RPC_ENDPOINTS.get(sym, [])
            price: float | None = None
            for rpc in endpoints:
                price = self._fetch_price_rpc(sym, rpc)
                if price is not None:
                    log.info(f"{sym} price from {rpc}: {price:.6f}")
                    break
            if price is None:
                # All 3 RPCs failed — fall back to synthetic for this coin
                log.warning(
                    "[FALLBACK] %s: all RPC endpoints failed, "
                    "using synthetic backup",
                    sym,
                )
                price = synthetic_backup[sym]
            prices[sym] = price
        return prices

    # ─── Depeg detection ──────────────────────────────────────────────────────

    def detect_depeg(
        self,
        prices: dict[str, float],
        threshold: float | None = None,
    ) -> list[dict]:
        """
        Detect stablecoins whose price has drifted outside the peg band.

        Args:
            prices: mapping symbol → spot price (USD).
            threshold: deviation fraction (e.g. 0.02 = 2%). Falls back to
                DEFAULT_DEPEG_THRESHOLD when None.

        Returns:
            List of dicts (one per off-peg coin), each shaped:
                {
                    "symbol": str,
                    "price": float,
                    "deviation_pct": float,   # signed, percentage (e.g. -6.0)
                    "severity": "WARN" | "CRITICAL",
                }

            Pegged coins (|deviation| < threshold) are omitted.

            Severity tiers:
                WARN     — threshold ≤ |dev| < 2 * threshold
                CRITICAL — |dev| ≥ 2 * threshold
        """
        thr = threshold if threshold is not None else self.DEFAULT_DEPEG_THRESHOLD
        events: list[dict] = []
        for sym, price in prices.items():
            deviation = price - 1.0  # signed, fraction of $1.00
            abs_dev = abs(deviation)
            if abs_dev < thr:
                continue
            severity = "CRITICAL" if abs_dev >= 2 * thr else "WARN"
            events.append({
                "symbol": sym,
                "price": round(price, 6),
                "deviation_pct": round(deviation * 100.0, 4),
                "severity": severity,
            })
        return events

    # ─── JSON dump ────────────────────────────────────────────────────────────

    def dump_prices_json(self, out_path: Path | None = None) -> Path:
        """
        Write the current price snapshot to ``data/price_feeds.json``.

        Schema:
            {
                "timestamp": ISO-8601 UTC string,
                "prices": {symbol: float, ...},
                "depeg_events": [ {symbol, price, deviation_pct, severity}, ... ],
                "threshold": float
            }

        Args:
            out_path: optional override. Defaults to ``<repo>/data/price_feeds.json``.

        Returns:
            Path actually written.
        """
        prices = self.fetch_prices(use_synthetic=True)
        events = self.detect_depeg(prices)
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "prices": prices,
            "depeg_events": events,
            "threshold": self.DEFAULT_DEPEG_THRESHOLD,
        }

        if out_path is None:
            _DATA_DIR.mkdir(parents=True, exist_ok=True)
            out_path = _DATA_DIR / "price_feeds.json"
        else:
            out_path.parent.mkdir(parents=True, exist_ok=True)

        out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        log.info(f"price_feeds.json written → {out_path}  (depeg_events={len(events)})")
        return out_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    fetcher = PriceFeedFetcher()
    snapshot = fetcher.fetch_prices_synthetic()
    print("Synthetic prices:", snapshot)
    print("Depeg events:   ", fetcher.detect_depeg(snapshot))
    written = fetcher.dump_prices_json()
    print(f"Wrote: {written}")
