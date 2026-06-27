"""
spa_core/data_pipeline/yield_aggregator_v2.py

Sprint v11.20 — MP-1504: Yield Aggregator v2 — multi-source + source quality scoring.

Combines DeFiLlama feed with direct protocol API stubs (aave_api, compound_api,
morpho_api).  For each protocol, selects the highest-reliability source that
successfully returns an APY.  Falls back to FALLBACK_APY if all sources fail.

Source quality model
--------------------
Each source has two quality weights:
  freshness_weight  – how fresh the data is expected to be (0–1).
  reliability       – probability of successful fetch (0–1).

get_best_apy() iterates sources in descending reliability order and returns
the first successful result together with quality metadata.

Architecture
------------
- Strictly read-only / advisory — never touches allocator, risk, or execution.
- Pure stdlib.  Only uses DeFiLlamaClient for the "defillama" source.
- Inherits BaseAnalytics for atomic save/load.
- CLI:  python3 -m spa_core.data_pipeline.yield_aggregator_v2 --check | --run
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from spa_core.base import BaseAnalytics
from spa_core.utils import clock

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Source quality registry
# ---------------------------------------------------------------------------

SOURCE_QUALITY: dict[str, dict] = {
    "aave_api": {
        "freshness_weight": 1.0,
        "reliability": 0.95,
        "description": "Direct Aave V3 API",
    },
    "compound_api": {
        "freshness_weight": 1.0,
        "reliability": 0.95,
        "description": "Direct Compound V3 API",
    },
    "morpho_api": {
        "freshness_weight": 1.0,
        "reliability": 0.90,
        "description": "Direct Morpho API",
    },
    "defillama": {
        "freshness_weight": 0.8,
        "reliability": 0.85,
        "description": "DeFiLlama yields aggregator",
    },
}

# Known protocol → primary source mapping (hint only; all sources still tried)
PROTOCOL_SOURCE_HINTS: dict[str, str] = {
    "aave-v3": "aave_api",
    "aave_v3": "aave_api",
    "compound-v3": "compound_api",
    "compound_v3": "compound_api",
    "morpho": "morpho_api",
    "morpho-steakhouse": "morpho_api",
}

FALLBACK_APY: float = 0.04  # 4% conservative fallback


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class YieldAggregatorV2(BaseAnalytics):
    """Aggregates yield data from multiple sources with quality scoring.

    Parameters
    ----------
    base_dir:
        Project root directory (default ".").
    defillama_client:
        Optional injected DeFiLlamaClient instance (for testing / DI).
    """

    OUTPUT_PATH = "data/yield_aggregator_v2.json"

    def __init__(
        self,
        base_dir: str = ".",
        defillama_client=None,
    ) -> None:
        super().__init__(base_dir)
        self._dl_client = defillama_client  # injected or lazy-created
        self._data: dict = {
            "sources": {},
            "aggregated_apys": {},
            "quality_scores": {},
            "last_update": None,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_best_apy(
        self,
        protocol: str,
        chain: str = "ethereum",
    ) -> dict:
        """Return best available APY for *protocol* from highest-quality source.

        Iterates sources in descending reliability order.  Falls back to
        FALLBACK_APY if every source fails or returns nothing.

        Returns
        -------
        dict with keys:
            apy          – float (fraction, e.g. 0.035 = 3.5%)
            apy_pct      – float (percentage, e.g. 3.5)
            source       – str  (source name or "fallback")
            quality      – float (reliability score 0–1)
            sources_tried – list[str]  (logged attempts)
        """
        sorted_sources = sorted(
            SOURCE_QUALITY.items(),
            key=lambda kv: kv[1]["reliability"],
            reverse=True,
        )
        sources_tried: list[str] = []

        for source_name, quality in sorted_sources:
            try:
                apy_pct = self._fetch_from_source(source_name, protocol, chain)
                if apy_pct is not None:
                    logger.info(
                        "YieldAggregatorV2: %s/%s → %.2f%% from %s",
                        protocol, chain, apy_pct, source_name,
                    )
                    return {
                        "apy": apy_pct / 100.0,
                        "apy_pct": apy_pct,
                        "source": source_name,
                        "quality": quality["reliability"],
                        "sources_tried": sources_tried,
                    }
                sources_tried.append(f"{source_name}:empty")
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "YieldAggregatorV2: source %s failed for %s: %s",
                    source_name, protocol, exc,
                )
                sources_tried.append(f"{source_name}:{type(exc).__name__}")

        # All sources failed
        logger.warning(
            "YieldAggregatorV2: all sources failed for %s/%s — using fallback %.1f%%",
            protocol, chain, FALLBACK_APY * 100,
        )
        return {
            "apy": FALLBACK_APY,
            "apy_pct": FALLBACK_APY * 100,
            "source": "fallback",
            "quality": 0.0,
            "sources_tried": sources_tried,
        }

    def aggregate_all(self, protocols: list[str], chain: str = "ethereum") -> dict:
        """Aggregate best APYs for a list of protocols.

        Populates internal _data and optionally saved via save().

        Returns
        -------
        dict mapping protocol → get_best_apy() result.
        """
        results: dict = {}
        for protocol in protocols:
            results[protocol] = self.get_best_apy(protocol, chain)

        self._data = {
            "sources": {k: v["description"] for k, v in SOURCE_QUALITY.items()},
            "aggregated_apys": {k: v["apy_pct"] for k, v in results.items()},
            "quality_scores": {k: v["quality"] for k, v in results.items()},
            "last_update": clock.utcnow().isoformat(),
            "detail": results,
        }
        return results

    def quality_for_source(self, source_name: str) -> dict:
        """Return quality metadata for a named source."""
        return SOURCE_QUALITY.get(source_name, {})

    def to_dict(self) -> dict:
        return self._data

    # ------------------------------------------------------------------
    # Internal source fetchers
    # ------------------------------------------------------------------

    def _fetch_from_source(
        self,
        source: str,
        protocol: str,
        chain: str,
    ) -> Optional[float]:
        """Dispatch fetch to the appropriate source handler.

        Returns APY as a percentage (e.g. 3.5 for 3.5%) or None on failure.
        """
        if source == "defillama":
            return self._fetch_defillama(protocol, chain)
        elif source == "aave_api":
            return self._fetch_aave_api(protocol, chain)
        elif source == "compound_api":
            return self._fetch_compound_api(protocol, chain)
        elif source == "morpho_api":
            return self._fetch_morpho_api(protocol, chain)
        return None

    def _fetch_defillama(self, protocol: str, chain: str) -> Optional[float]:
        """Fetch APY from DeFiLlama for given protocol/chain."""
        try:
            client = self._get_defillama_client()
            pools = client.get_yields(chain=chain)
            protocol_l = protocol.lower()
            matching = [
                p for p in pools
                if protocol_l in str(p.get("project", "")).lower()
            ]
            if not matching:
                return None
            # Return highest APY among matching pools
            apys = [
                float(p["apy"]) for p in matching
                if isinstance(p.get("apy"), (int, float))
            ]
            return max(apys) if apys else None
        except Exception as exc:  # noqa: BLE001
            logger.debug("DeFiLlama fetch failed: %s", exc)
            return None

    def _fetch_aave_api(self, protocol: str, chain: str) -> Optional[float]:
        """Stub: fetch APY from direct Aave API.

        In paper-trading mode returns None (no live API integration).
        Override in tests or live-integration subclass.
        """
        return None

    def _fetch_compound_api(self, protocol: str, chain: str) -> Optional[float]:
        """Stub: fetch APY from direct Compound API."""
        return None

    def _fetch_morpho_api(self, protocol: str, chain: str) -> Optional[float]:
        """Stub: fetch APY from direct Morpho API."""
        return None

    def _get_defillama_client(self):
        """Return injected or lazily-created DeFiLlamaClient."""
        if self._dl_client is None:
            from spa_core.utils.defillama import DeFiLlamaClient
            self._dl_client = DeFiLlamaClient()
        return self._dl_client


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Yield Aggregator v2 — multi-source APY aggregation"
    )
    parser.add_argument("--check", action="store_true",
                        help="Compute and print without saving (default)")
    parser.add_argument("--run", action="store_true",
                        help="Compute and atomically save to data/")
    parser.add_argument("--data-dir", default=".",
                        help="Project root directory")
    args = parser.parse_args(argv)

    aggregator = YieldAggregatorV2(base_dir=args.data_dir)
    protocols = ["aave-v3", "compound-v3", "morpho", "yearn"]
    results = aggregator.aggregate_all(protocols)

    print(json.dumps(aggregator.to_dict(), indent=2))

    if args.run:
        path = aggregator.save()
        print(f"\n[yield_aggregator_v2] Saved → {path}")


if __name__ == "__main__":
    import sys
    _main(sys.argv[1:])
