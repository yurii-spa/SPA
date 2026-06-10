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
    """

    protocol: str
    asset: str
    apy: Optional[float]
    tvl_usd: Optional[float]
    tier: str
    risk_score: float


class BaseAdapter(ABC):
    """Abstract base for all protocol adapters."""

    PROTOCOL: str = "base"

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
