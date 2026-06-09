"""SPA protocol adapters."""
from .base_adapter import BaseAdapter, YieldInfo
from .defillama_feed import DeFiLlamaFeed
from .morpho_blue import MorphoBlueAdapter
from .yearn_v3 import YearnV3Adapter
from .euler_v2 import EulerV2Adapter
from .maple import MapleAdapter

__all__ = [
    "BaseAdapter",
    "YieldInfo",
    "DeFiLlamaFeed",
    "MorphoBlueAdapter",
    "YearnV3Adapter",
    "EulerV2Adapter",
    "MapleAdapter",
]
