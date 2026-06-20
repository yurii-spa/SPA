#!/usr/bin/env bash
# Sprint v12.54 — Replace dead Arbitrum protocols (Radiant/GMX GLP) with live ones
# (Silo Finance + Dolomite). Live DeFiLlama scan 2026-06-21.
#
# Findings (DeFiLlama /pools, 2026-06-21):
#   - Radiant Capital      : DEAD — 0 pools on DeFiLlama (any chain) → removed
#   - GMX GLP              : deprecated (rolled into GM/GLV perps LP) → removed
#   - Silo Finance (Arb)   : USDC best 7.43% APY but TVL ~$12K  (< $5M floor)
#   - Dolomite (Arb)       : USDC 3.98% APY, TVL ~$1.47M        (< $5M floor)
# Both new adapters register as read-only monitoring feeds (sub-floor TVL →
# RiskPolicy will not allocate until TVL grows ≥ $5M). Live DeFiLlama fetch with
# honest fallbacks (Silo 4.5%, Dolomite 4.0%, require on-chain confirmation).
#
# NOTE: push_to_github.py is create/update only (no delete API). The removed
# radiant_arbitrum_adapter.py / gmx_glp_arbitrum_adapter.py are deleted locally;
# on the remote they linger but are orphaned (the pushed __init__.py no longer
# imports them). SECURITY: never push scripts/cf_install_token.command.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 "${REPO_ROOT}/push_to_github.py" \
  --files \
    "${REPO_ROOT}/spa_core/adapters/silo_arbitrum_usdc_adapter.py" \
    "${REPO_ROOT}/spa_core/adapters/dolomite_arbitrum_usdc_adapter.py" \
    "${REPO_ROOT}/spa_core/adapters/__init__.py" \
    "${REPO_ROOT}/tests/test_silo_dolomite_arb.py" \
    "${REPO_ROOT}/tests/test_multichain_adapters.py" \
    "${REPO_ROOT}/scripts/push_v1254.sh" \
  --message "feat(v1.254): replace dead Radiant/GMX-GLP Arbitrum with live Silo+Dolomite (read-only, sub-\$5M-floor feeds)"
