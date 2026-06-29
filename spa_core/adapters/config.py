"""Adapter-layer configuration, read from environment variables.

Centralizes runtime config for the SPA adapter layer. Values are read from
env vars at import time with sensible defaults so the package works without
any environment setup.
"""
import os

# --- MEV protection (Sprint v3.26 / SPA-V326) ---
# When enabled, mainnet (chain_id == 1) signed transactions are routed through
# the Flashbots Protect RPC instead of the public mempool to defend against
# frontrunning / sandwich attacks. See spa_core/execution/eth_signer.py.
MEV_PROTECTION_ENABLED = os.getenv("MEV_PROTECTION_ENABLED", "true").lower() == "true"
FLASHBOTS_PROTECT_RPC = os.getenv("FLASHBOTS_PROTECT_RPC", "https://rpc.flashbots.net/fast")
# Fall back to the public RPC if the Protect RPC call fails.
# WS-5.3 fail-CLOSED: default is now OFF — a Protect-RPC failure ABORTS rather
# than silently leaking the tx into the public mempool (which would defeat MEV
# protection). The owner must EXPLICITLY set MEV_PROTECT_FALLBACK=true to opt in.
# This matches the adapter path's fail-CLOSED MEV posture (consistent everywhere).
MEV_PROTECT_FALLBACK = os.getenv("MEV_PROTECT_FALLBACK", "false").lower() == "true"

# --- Rebalancer ---
REBALANCE_INTERVAL_SEC = int(os.getenv("REBALANCE_INTERVAL_SEC", "3600"))
REBALANCE_MIN_DELTA = float(os.getenv("REBALANCE_MIN_DELTA", "0.005"))

# --- DeFiLlama yields feed ---
DEFILLAMA_ENABLED = os.getenv("DEFILLAMA_ENABLED", "true").lower() == "true"
DEFILLAMA_API_URL = os.getenv("DEFILLAMA_API_URL", "https://yields.llama.fi/pools")
DEFILLAMA_CACHE_TTL = int(os.getenv("DEFILLAMA_CACHE_TTL", "300"))
DEFILLAMA_TIMEOUT = int(os.getenv("DEFILLAMA_TIMEOUT", "10"))

# end of file
