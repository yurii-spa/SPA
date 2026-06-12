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
# MP-430: Frax sFRAX ERC-4626 T2 adapter (peg gate)
from .sfrax_adapter import SfraxAdapter
# MP-376: Spark Protocol sUSDS ERC-4626 T1 adapter
from .spark_susds_adapter import SparkSusdsAdapter
# MP-460: Ethena sUSDe ERC-4626 T3 adapter (peg gate, 7d unstake cooldown)
from .susde_adapter import SusdeAdapter
# MP-559: Mountain Protocol wUSDM ERC-4626 RWA T-bill-backed T2 adapter (peg gate)
from .wusdm_adapter import WusdmAdapter  # MP-559
# MP-560: Curve Savings crvUSD (scrvUSD) ERC-4626 T2 adapter (soft-peg gate 1%)
from .scrvusd_adapter import ScrvusdAdapter  # MP-560
# MP-561: Angle Staked USDA (stUSD) ERC-4626 T2 adapter (hard-peg gate 0.5%)
from .stusd_adapter import StusdAdapter  # MP-561
# MP-562: MakerDAO Savings DAI (sDAI) ERC-4626 T2 adapter (hard-peg gate 0.5%, DSR yield)
from .sdai_adapter import SdaiAdapter  # MP-562
# MP-448: Aave V3 Base chain T2 adapter (Coinbase L2, ~$400M USDC TVL)
try:
    from .aave_v3_base_adapter import AaveV3BaseAdapter
    _AAVE_V3_BASE_AVAILABLE = True
except ImportError:
    _AAVE_V3_BASE_AVAILABLE = False

# MP-450: Morpho Blue Base chain T2 adapter (Coinbase L2, ~$180M TVL)
try:
    from .morpho_blue_base_adapter import MorphoBlueBaseAdapter
    _MORPHO_BLUE_BASE_AVAILABLE = True
except ImportError:
    _MORPHO_BLUE_BASE_AVAILABLE = False

# MP-463: Moonwell Finance Base chain T2 adapter (Coinbase L2, ~$500M TVL)
try:
    from .moonwell_base_adapter import MoonwellBaseAdapter
    _MOONWELL_BASE_AVAILABLE = True
except ImportError:
    _MOONWELL_BASE_AVAILABLE = False

# MP-510: Extra Finance XLend Base chain T3 adapter (ADR-026 Phase 1, isolated lending vault)
try:
    from .extra_finance_base_adapter import ExtraFinanceBaseAdapter  # MP-510
    _EXTRA_FINANCE_BASE_AVAILABLE = True
except ImportError:
    _EXTRA_FINANCE_BASE_AVAILABLE = False

# ADR-025 Phase 1: Base chain read-only APY feeds (no capital allocation)
# Populated at import time with whichever Base adapters are available.
BASE_CHAIN_ADAPTERS: dict = {}  # ADR-025: key -> adapter instance, read-only
if _AAVE_V3_BASE_AVAILABLE:
    BASE_CHAIN_ADAPTERS["aave-v3-base"] = AaveV3BaseAdapter()
if _MORPHO_BLUE_BASE_AVAILABLE:
    BASE_CHAIN_ADAPTERS["morpho-blue-base"] = MorphoBlueBaseAdapter()
if _MOONWELL_BASE_AVAILABLE:
    BASE_CHAIN_ADAPTERS["moonwell-base"] = MoonwellBaseAdapter()
if _EXTRA_FINANCE_BASE_AVAILABLE:
    BASE_CHAIN_ADAPTERS["extra-finance-base"] = ExtraFinanceBaseAdapter()

# Read-only adapter registry: (protocol_key, tier, adapter_class). The
# orchestrator polls these; SPA-V405 adds the Aave V3 T1 anchor; SPA-V411 adds
# Compound V3 (Comet USDC) as the second T1 anchor for T1 diversification and
# extra remainder-fill headroom for the allocator.
# MP-201: PendleAdapter added as T2 (tier is dynamic — may be T3 for smaller
# TVL markets; declared as T2 here as the registry-level default).
# MP-356: AaveArbitrumAdapter added as T1 (L2 Arbitrum anchor, $1.2B TVL).
# MP-448: AaveV3BaseAdapter added as T2 (Base chain, $400M TVL, bridge risk).
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
    ("sfrax",         "T2", SfraxAdapter),
    ("spark_susds",   "T1", SparkSusdsAdapter),  # MP-376
    ("susde",         "T3", SusdeAdapter),  # MP-460
    ("wusdm",         "T2", WusdmAdapter),  # MP-559
    ("scrvusd",       "T2", ScrvusdAdapter),  # MP-560
    ("stusd",         "T2", StusdAdapter),  # MP-561
    ("sdai",          "T2", SdaiAdapter),   # MP-562
]

# MP-448/MP-450: добавляем Base адаптеры если импорт успешен
if _AAVE_V3_BASE_AVAILABLE:
    ADAPTER_REGISTRY.append(("aave_v3_base", "T2", AaveV3BaseAdapter))
if _MORPHO_BLUE_BASE_AVAILABLE:
    ADAPTER_REGISTRY.append(("morpho_blue_base", "T2", MorphoBlueBaseAdapter))
# MP-463: Moonwell Finance Base T2 (ADR-025 Phase 1 monitoring)
if _MOONWELL_BASE_AVAILABLE:
    ADAPTER_REGISTRY.append(("moonwell_base", "T2", MoonwellBaseAdapter))
# MP-510: Extra Finance XLend Base T3 (ADR-026 Phase 1 monitoring)
if _EXTRA_FINANCE_BASE_AVAILABLE:
    ADAPTER_REGISTRY.append(("extra_finance_base", "T3", ExtraFinanceBaseAdapter))  # MP-510

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
    "SfraxAdapter",
    "SparkSusdsAdapter",  # MP-376
    "SusdeAdapter",  # MP-460
    "WusdmAdapter",  # MP-559
    "ScrvusdAdapter",  # MP-560
    "StusdAdapter",  # MP-561
    "SdaiAdapter",   # MP-562
    "AaveV3BaseAdapter",
    "MorphoBlueBaseAdapter",
    "MoonwellBaseAdapter",
    "ExtraFinanceBaseAdapter",  # MP-510
    "BASE_CHAIN_ADAPTERS",
    "ADAPTER_REGISTRY",
]
