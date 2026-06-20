#!/usr/bin/env bash
# scripts/push_v1242.sh
# Session 2026-06-21 — ADR-042…047 + DECISIONS.md + ADR_INDEX.md
#
# Documents the six major decisions of this session:
#   ADR-042 Backtest Harness Design
#   ADR-043 New Protocol Adapters (Ethena/Fluid/Usual)
#   ADR-044 Bear-Market Hedge Strategy (S31/S32) — Proposed
#   ADR-045 Kelly Criterion Allocation
#   ADR-046 Multi-Chain Expansion Strategy
#   ADR-047 Site Privacy Hardening (earn-defi.com)
#
# SECURITY: scripts/cf_install_token.command is NEVER included in this push.
# Usage: bash scripts/push_v1242.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/docs/adr/ADR-042-backtest-harness-design.md" \
    "$REPO_ROOT/docs/adr/ADR-043-new-protocol-adapters-ethena-fluid-usual.md" \
    "$REPO_ROOT/docs/adr/ADR-044-bear-market-hedge-strategy.md" \
    "$REPO_ROOT/docs/adr/ADR-045-kelly-criterion-allocation.md" \
    "$REPO_ROOT/docs/adr/ADR-046-multi-chain-expansion-strategy.md" \
    "$REPO_ROOT/docs/adr/ADR-047-site-privacy-hardening.md" \
    "$REPO_ROOT/docs/adr/ADR_INDEX.md" \
    "$REPO_ROOT/docs/DECISIONS.md" \
    "$REPO_ROOT/scripts/push_v1242.sh" \
  --message "docs: ADR-042..047 session decisions (backtest harness, Ethena/Fluid/Usual adapters, bear hedge S31/S32, Kelly sizing, multi-chain, site privacy) + DECISIONS/ADR_INDEX"
