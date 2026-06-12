"""SPA protocol adapters."""
from .base_adapter import BaseAdapter, YieldInfo
from .defillama_feed import DeFiLlamaFeed
from .morpho_blue import MorphoBlueAdapter
from .yearn_v3 import YearnV3Adapter
from .euler_v2 import EulerV2Adapter
from .maple import MapleAdapter
from .compound_v3 import CompoundV3Adapter
from .aave_v3 import AaveV3Adapter
from .pendle_adapter import PendleAdapter
# MP-356: Aave V3 Arbitrum T1 anchor (L2, отдельный адаптер с allocate/withdraw)
from .aave_arbitrum_adapter import AaveArbitrumAdapter
# MP-377: Fluid Protocol fUSDC ERC-4626 vault (T2, GSM gate, spike normalization)
from .fluid_fusdc_adapter import FluidFUSDCAdapter

# Read-only adapter registry: (protocol_key, tier, adapter_class). The
# orchestrator polls these; SPA-V405 adds the Aave V3 T1 anchor; SPA-V411 adds
# Compound V3 (Comet USDC) as the second T1 anchor for T1 diversification and
# extra remainder-fill headroom for the allocator.
# MP-201: PendleAdapter added as T2 (tier is dynamic — may be T3 for smaller
# TVL markets; declared as T2 here as the registry-level default).
# MP-356: AaveArbitrumAdapter added as T1 (L2 Arbitrum anchor, $1.2B TVL).
ADAPTER_REGISTRY = [
    ("aave_v3",       "T1", AaveV3Adapter),
    ("compound_v3",   "T1", CompoundV3Adapter),
    ("aave_arbitrum", "T1", AaveArbitrumAdapter),
    ("morpho_blue",   "T2", MorphoBlueAdapter),
    ("yearn_v3",      "T2", YearnV3Adapter),
    ("euler_v2",      "T2", EulerV2Adapter),
    ("maple",         "T2", MapleAdapter),
    ("pendle",        "T2", PendleAdapter),
    ("fluid_fusdc",   "T2", FluidFUSDCAdapter),
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
    "PendleAdapter",
    "AaveArbitrumAdapter",
    "FluidFUSDCAdapter",
    "ADAPTER_REGISTRY",
]
