"""SPA protocol adapters."""
from .base_adapter import BaseAdapter, YieldInfo
from .defillama_feed import DeFiLlamaFeed
from .morpho_blue import MorphoBlueAdapter
from .yearn_v3 import YearnV3Adapter
from .euler_v2 import EulerV2Adapter
from .maple import MapleAdapter
from .compound_v3 import CompoundV3Adapter
from .aave_v3 import AaveV3Adapter

# Read-only adapter registry: (protocol_key, tier, adapter_class). The
# orchestrator polls these; SPA-V405 adds the Aave V3 T1 anchor; SPA-V411 adds
# Compound V3 (Comet USDC) as the second T1 anchor for T1 diversification and
# extra remainder-fill headroom for the allocator.
ADAPTER_REGISTRY = [
    ("aave_v3", "T1", AaveV3Adapter),
    ("compound_v3", "T1", CompoundV3Adapter),
    ("morpho_blue", "T2", MorphoBlueAdapter),
    ("yearn_v3", "T2", YearnV3Adapter),
    ("euler_v2", "T2", EulerV2Adapter),
    ("maple", "T2", MapleAdapter),
]

__all__ = [
    "BaseAdapter",
    "YieldInfo",
    "DeFiLlamaFeed",
    "MorphoBlueAdapter",
    "YearnV3Adapter",
    "EulerV2Adapter",
    "MapleAdapter",
    "CompoundV3Adapter",
    "AaveV3Adapter",
    "ADAPTER_REGISTRY",
]
