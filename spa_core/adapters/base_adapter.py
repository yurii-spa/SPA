"""Base classes for SPA protocol adapters.

Defines the :class:`YieldInfo` dataclass returned by adapters and the
:class:`BaseAdapter` abstract base every protocol adapter extends.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class YieldInfo:
    """Normalized yield snapshot for a single protocol/asset.

    apy and tvl_usd are decimals/USD respectively (apy is a decimal, e.g.
    0.085 == 8.5%). tier is the protocol risk tier (T1/T2/T3). risk_score is
    a normalized score in [0.0, 1.0].

    ``apy`` is ``None`` (and ``tvl_usd`` may be ``None``) when the live feed is
    unavailable — adapters never substitute a mock value (SPA-V398). Consumers
    must treat ``apy is None`` as "no live data", not as 0%.

    ``exit_latency_hours`` (SPA-V412) declares the protocol's exit profile — the
    typical wall-clock time to fully withdraw a USDC position back to liquid
    cash. ``0.0`` means same-block/instant (blue-chip lending pools); a large
    value means a withdrawal queue (e.g. Maple's epoch-based redemption). It is
    declarative metadata only — this module never moves capital. A value of
    ``None`` means the adapter has not declared a profile.
    """

    protocol: str
    asset: str
    apy: Optional[float]
    tvl_usd: Optional[float]
    tier: str
    risk_score: float
    # SPA-V412: declarative exit profile (hours to fully exit to liquid cash).
    # Optional with a default so the field is strictly additive — existing
    # YieldInfo(...) call sites that omit it keep working unchanged.
    exit_latency_hours: Optional[float] = None


class BaseAdapter(ABC):
    """Abstract base for all protocol adapters."""

    PROTOCOL: str = "base"
    # SPA-V412: default exit profile; concrete adapters override with a measured
    # value (e.g. Aave ~0h instant, Maple ~weeks via withdrawal queue).
    EXIT_LATENCY_HOURS: Optional[float] = None

    def __init__(self, asset: str = "USDC"):
        self.asset = asset
        self.tier = "T2"

    @abstractmethod
    def get_apy(self) -> Optional[float]:
        """Return the current APY as a decimal, or ``None`` if no live data."""
        raise NotImplementedError

    @abstractmethod
    def get_yield_info(self) -> YieldInfo:
        """Return a fully-populated :class:`YieldInfo`."""
        raise NotImplementedError
