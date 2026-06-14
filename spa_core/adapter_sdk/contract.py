"""Formal ProtocolAdapter contract for the Adapter SDK (SPA-V417 / MP-204).

Defines the single contract every SDK adapter implements::

    fetch_pools()  -> list[PoolInfo]   # live pools that passed quality gates
    exit_latency() -> dict             # declarative exit profile (SPA-V412 style)
    health()       -> dict             # ok / degraded / error + last_fetch_ts

and the :class:`PoolInfo` normalized pool snapshot. Field names deliberately
mirror the *actual* shapes already used in the repo so SDK output plugs into
existing consumers without translation:

* ``protocol`` / ``tier`` / ``tvl_usd`` / ``apy_pct`` — same units and names as
  the per-adapter records in ``data/adapter_orchestrator_status.json``
  (``apy_pct`` is a **percentage**, e.g. ``8.5`` == 8.5%);
* ``PoolInfo.apy`` property — APY as a **decimal** (e.g. ``0.085``), matching
  ``spa_core.adapters.base_adapter.YieldInfo.apy`` and ``DeFiLlamaFeed.get_apy``;
* ``exit_latency_hours`` — same declarative profile as
  ``YieldInfo.exit_latency_hours`` / ``spa_core/adapters/exit_latency_policy.py``;
* ``defillama_pool_id`` — the DeFiLlama pool uuid (``fetch_pool()['pool_id']``).

STRICTLY READ-ONLY (SPA-BL-011): the contract is advisory metadata over public
yield data. Implementations never move capital, never touch ``execution/``,
``risk/``, ``allocator/`` or feed-health.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, List, Optional, Protocol, runtime_checkable

# Risk tiers recognised across the repo (see ADAPTER_REGISTRY / allocator caps).
VALID_TIERS = ("T1", "T2", "T3")

# Conservative default per-protocol portfolio caps by tier — mirrors the
# existing convention (Aave/Compound T1_CAP=0.40, T2 adapters capped at 0.20).
DEFAULT_TIER_CAPS: Dict[str, float] = {"T1": 0.40, "T2": 0.20, "T3": 0.10}

# Health statuses an adapter may report.
HEALTH_STATUSES = ("ok", "degraded", "error")


@dataclass(frozen=True)
class PoolInfo:
    """Normalized snapshot of a single live pool.

    ``apy_pct`` is the raw DeFiLlama **percentage** (``8.5`` == 8.5%) or ``None``
    when no live data is available — never a mock (SPA-V398). ``tvl_usd`` is USD.
    ``pool_id`` is the stable SPA identifier (``{protocol}-{symbol}-{chain}``,
    lowercase — same convention as ``aave-v3-usdc-ethereum``);
    ``defillama_pool_id`` is the upstream DeFiLlama pool uuid, when known.
    """

    protocol: str
    pool_id: str
    chain: str
    symbol: str
    apy_pct: Optional[float]
    tvl_usd: Optional[float]
    tier: str
    defillama_pool_id: Optional[str] = None
    exit_latency_hours: Optional[float] = None
    source: str = "defillama"
    fetched_at: Optional[str] = None  # ISO-8601 UTC timestamp of the fetch

    @property
    def apy(self) -> Optional[float]:
        """APY as a decimal fraction (``0.085`` == 8.5%) — YieldInfo convention."""
        if isinstance(self.apy_pct, (int, float)):
            return float(self.apy_pct) / 100.0
        return None

    def to_dict(self) -> dict:
        """Plain JSON-serialisable dict (includes the derived decimal ``apy``)."""
        out = asdict(self)
        out["apy"] = self.apy
        return out


@runtime_checkable
class ProtocolAdapter(Protocol):
    """The Adapter SDK v1 contract.

    Any object exposing these three methods (plus a ``name``) is a valid SDK
    adapter — :class:`~spa_core.adapter_sdk.declarative_adapter.DeclarativeAdapter`
    is the manifest-driven reference implementation. ``runtime_checkable`` so
    tests can assert ``isinstance(adapter, ProtocolAdapter)``.
    """

    name: str

    def fetch_pools(self) -> List[PoolInfo]:
        """Return live pools that passed the quality gates; ``[]`` on feed loss.

        Must NEVER raise on feed failure and NEVER substitute mock data.
        """
        ...

    def exit_latency(self) -> Dict[str, object]:
        """Declarative exit profile, ``exit_latency_policy.py``-compatible::

            {"protocol", "exit_latency_hours", "bucket", "profile",
             "threshold_hours"}
        """
        ...

    def health(self) -> Dict[str, object]:
        """Health report::

            {"protocol", "status": "ok"|"degraded"|"error", "last_fetch_ts",
             "source", "pools_live", "pools_expected", "tier", "error"}

        ``error`` (no live pools) / ``degraded`` (some expected pools missing)
        must be reported honestly — a dead feed is an error, not silent zeros.
        """
        ...
