"""SPA protocol adapters."""
from .base_adapter import BaseAdapter, YieldInfo
from .defillama_feed import DeFiLlamaFeed
from .morpho_blue import MorphoBlueAdapter
from .yearn_v3 import YearnV3Adapter
from .euler_v2 import EulerV2Adapter
from .maple import MapleAdapter
# MP-564: upgraded to BaseAdapter with peg-gate, is_eligible, simulate_deposit/withdraw, get_health
from .compound_v3_adapter import CompoundV3Adapter
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
# MP-563: Frax Finance FraxLend USDC T2 adapter (hard-peg gate 0.5%, utilisation-based yield)
from .frax_adapter import FraxAdapter  # MP-563
# MP-565: Aave V3 Optimism USDC lending T1 L2 adapter (hard-peg gate 0.5%, gas 95% cheaper)
from .aave_v3_optimism_adapter import AaveV3OptimismAdapter  # MP-565
# MP-593: Aave V3 Polygon USDC.e lending T1 L2 adapter (hard-peg gate 0.5%, gas 90% cheaper, USDC.e bridge note)
from .aave_v3_polygon_adapter import AaveV3PolygonAdapter  # MP-593
# MP-1227: Ethena sUSDe T2 adapter (delta-neutral; live Ethena API + DeFiLlama fallback, anomaly flag)
from .ethena_susde_adapter import EthenaSusdeAdapter  # MP-1227
# MP-1227: Fluid Protocol USDC lending T2 adapter (Fluid API + DeFiLlama fallback)
from .fluid_usdc_adapter import FluidUSDCAdapter  # MP-1227
# MP-1227: Usual Protocol USD0++ RWA-backed T2 adapter (Usual API + DeFiLlama fallback)
from .usual_usd0pp_adapter import UsualUSD0PPAdapter  # MP-1227
# MP-1250: Pendle PT fixed-rate adapters (T2, DeFiLlama feed + fallback, maturity-aware)
from .pendle_pt_susde_adapter import PendlePTSusdeAdapter  # MP-1250
from .pendle_pt_usdc_adapter import PendlePTUsdcAdapter    # MP-1250
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

# Multichain expansion — Arbitrum / Optimism new-protocol read-only APY feeds
# (DeFiLlama live fetch + cached fallback). NOTE: Aave V3 Arbitrum (aave_arbitrum)
# and Aave V3 Optimism (aave_v3_optimism) already exist above and are NOT
# duplicated here — these add genuinely new pools (Radiant, GMX GLP, Velodrome).
try:
    from .radiant_arbitrum_adapter import RadiantArbitrumAdapter
    _RADIANT_ARBITRUM_AVAILABLE = True
except ImportError:
    _RADIANT_ARBITRUM_AVAILABLE = False

try:
    from .gmx_glp_arbitrum_adapter import GmxGlpArbitrumAdapter
    _GMX_GLP_ARBITRUM_AVAILABLE = True
except ImportError:
    _GMX_GLP_ARBITRUM_AVAILABLE = False

try:
    from .velodrome_optimism_adapter import VelodromeOptimismAdapter
    _VELODROME_OPTIMISM_AVAILABLE = True
except ImportError:
    _VELODROME_OPTIMISM_AVAILABLE = False

# MP v12.51: Aerodrome Finance Base USDC-USDT stable-pool T2 adapter (ve(3,3) DEX)
try:
    from .aerodrome_usdc_adapter import AerodromeUsdcAdapter
    _AERODROME_BASE_AVAILABLE = True
except ImportError:
    _AERODROME_BASE_AVAILABLE = False

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
    ("frax",          "T2", FraxAdapter),   # MP-563
    ("aave_v3_optimism", "T1", AaveV3OptimismAdapter),  # MP-565
    ("aave_v3_polygon",  "T1", AaveV3PolygonAdapter),   # MP-593
    ("ethena_susde",     "T2", EthenaSusdeAdapter),     # MP-1227
    ("fluid_usdc",       "T2", FluidUSDCAdapter),       # MP-1227
    ("usual_usd0pp",     "T2", UsualUSD0PPAdapter),     # MP-1227
    ("pendle_pt_susde",  "T2", PendlePTSusdeAdapter),   # MP-1250
    ("pendle_pt_usdc",   "T2", PendlePTUsdcAdapter),    # MP-1250
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

# Multichain expansion: new Arbitrum / Optimism protocol pools (all T2).
# These are genuinely new pools (no pre-existing registry entry), so registering
# them does not double-count an existing Aave-Arbitrum/Optimism position.
MULTICHAIN_L2_ADAPTERS: dict = {}  # key -> adapter instance, read-only feeds
if _RADIANT_ARBITRUM_AVAILABLE:
    ADAPTER_REGISTRY.append(("radiant_arbitrum", "T2", RadiantArbitrumAdapter))
    MULTICHAIN_L2_ADAPTERS["radiant-arbitrum"] = RadiantArbitrumAdapter()
if _GMX_GLP_ARBITRUM_AVAILABLE:
    ADAPTER_REGISTRY.append(("gmx_glp_arbitrum", "T2", GmxGlpArbitrumAdapter))
    MULTICHAIN_L2_ADAPTERS["gmx-glp-arbitrum"] = GmxGlpArbitrumAdapter()
if _VELODROME_OPTIMISM_AVAILABLE:
    ADAPTER_REGISTRY.append(("velodrome_optimism", "T2", VelodromeOptimismAdapter))
    MULTICHAIN_L2_ADAPTERS["velodrome-optimism"] = VelodromeOptimismAdapter()
# MP v12.51: Aerodrome USDC-USDT stable LP on Base (T2 AMM)
if _AERODROME_BASE_AVAILABLE:
    ADAPTER_REGISTRY.append(("aerodrome_base", "T2", AerodromeUsdcAdapter))
    MULTICHAIN_L2_ADAPTERS["aerodrome-base"] = AerodromeUsdcAdapter()

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
    "FraxAdapter",   # MP-563
    "AaveV3OptimismAdapter",  # MP-565
    "AaveV3PolygonAdapter",   # MP-593
    "EthenaSusdeAdapter",     # MP-1227
    "FluidUSDCAdapter",       # MP-1227
    "UsualUSD0PPAdapter",     # MP-1227
    "PendlePTSusdeAdapter",   # MP-1250
    "PendlePTUsdcAdapter",    # MP-1250
    "AaveV3BaseAdapter",
    "MorphoBlueBaseAdapter",
    "MoonwellBaseAdapter",
    "ExtraFinanceBaseAdapter",  # MP-510
    "RadiantArbitrumAdapter",       # multichain expansion (Arbitrum)
    "GmxGlpArbitrumAdapter",        # multichain expansion (Arbitrum)
    "VelodromeOptimismAdapter",     # multichain expansion (Optimism)
    "AerodromeUsdcAdapter",         # MP v12.51 (Base AMM stable LP)
    "BASE_CHAIN_ADAPTERS",
    "MULTICHAIN_L2_ADAPTERS",
    "ADAPTER_REGISTRY",
]
