#!/bin/bash
# SPA Push — v12.25 High-APY Strategy Expansion S22–S25 (2026-06-21)
#
# Four new yield strategies targeting APY above the current ~3.9%:
#   S22 Ethena Yield Maximizer  — sUSDe 40% + Sky 30% + Aave 30%, depeg kill switch
#   S23 Pendle PT Fixed Rate    — PT 50% + Sky 30% + Aave 20%, fixed YTM / 7% mock
#   S24 Base Chain Maximizer    — Morpho/Aave/Moonwell Base L2, phase-gated
#   S25 Yield Ladder            — barbell 60% T1 + 40% dynamic best T2
# Registered in both strategy_registry.py (StrategyMeta) and
# paper_trading/strategy_registry.py (StrategyConfig). 113 tests pass.
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
# DO NOT push scripts/cf_install_token.command (excluded by design).
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v1225.sh

set -e

COMMIT_MSG="feat: S22-S25 high-APY strategies (Ethena/PendlePT/Base/YieldLadder), 113 tests pass"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/strategies/s22_ethena_yield_max.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/strategies/s23_pendle_pt_fixed.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/strategies/s24_base_chain_max.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/strategies/s25_yield_ladder.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/strategies/strategy_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/strategy_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/tests/test_s22_s25_strategies.py
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v1225.sh"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push — v12.25 High-APY Strategy Expansion S22–S25"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v12.25 S22–S25 complete!"
