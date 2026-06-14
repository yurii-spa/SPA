#!/usr/bin/env python3
"""
ADR-025 Phase 1: Base chain APY monitoring script.

Fetches read-only APY snapshots from Base chain adapters (Aave V3 Base,
Morpho Blue Base) and prints a summary table. No allocation is performed;
this script is advisory only.

Usage:
    python3 scripts/base_chain_apy_fetch.py

Requires:
    - spa_core/adapters/aave_v3_base_adapter.py  (MP-448)
    - spa_core/adapters/morpho_blue_base_adapter.py  (MP-450)
"""
import sys
import os

# Add project root to path so spa_core is importable
sys.path.insert(0, os.path.expanduser("~/Documents/SPA_Claude"))

ADAPTERS = {}

try:
    from spa_core.adapters.aave_v3_base_adapter import AaveV3BaseAdapter
    ADAPTERS["aave-v3-base"] = AaveV3BaseAdapter()
except ImportError:
    pass

try:
    from spa_core.adapters.morpho_blue_base_adapter import MorphoBlueBaseAdapter
    ADAPTERS["morpho-blue-base"] = MorphoBlueBaseAdapter()
except ImportError:
    pass

if not ADAPTERS:
    print("No Base chain adapters available yet. Run after MP-448+MP-450.")
    sys.exit(0)

print("=== Base Chain APY (ADR-025 Phase 1) ===")
for name, adapter in ADAPTERS.items():
    try:
        apy = adapter.get_apy()
        state = adapter.get_write_state()
        tvl = state.get("tvl_usd", 0) or 0
        tier = state.get("tier", "?")
        print(
            f"  {name}: APY={apy:.2f}%, TVL=${tvl / 1e6:.0f}M, tier={tier}"
        )
    except Exception as e:
        print(f"  {name}: ERROR {e}")
print("=========================================")
