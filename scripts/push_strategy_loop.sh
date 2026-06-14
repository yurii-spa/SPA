#!/bin/bash
# SPA Push — ADR-033 Strategy Loop Activation (shadow mode)
#
# ADR-033: tournament S0-S19 runs in shadow mode (evaluated + logged each cycle,
# advisory-only). Real allocation unchanged until a shadow strategy reaches
# medium confidence (>=15 days with a valid Sortino).
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_strategy_loop.sh

set -e

COMMIT_MSG="feat(ADR-033): strategy-loop activation policy — shadow mode | data/strategy_config.json (strategy_loop_mode: off|shadow|active, default shadow) + fail-safe reader strategy_config.py + cycle_runner wiring (logs mode, records note, enforces safety invariant, builds allocator with strategy_loop_enabled from mode) | tournament S0-S19 evaluated+logged advisory-only, real allocation unchanged until a shadow strategy reaches >=15d medium confidence | 17 tests (unittest) | read-only/stdlib, degrades to shadow on bad config"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/docs/adr/ADR-033-strategy-loop-activation.md
/Users/yuriikulieshov/Documents/SPA_Claude/data/strategy_config.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/strategies/strategy_config.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/cycle_runner.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_strategy_loop_activation.py
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_strategy_loop.sh"

# PAT resolution: Keychain -> env GITHUB_PAT_SPA -> env SPA_GITHUB_PAT -> ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push — ADR-033 strategy-loop activation (shadow mode) + config + reader + cycle_runner + tests"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push ADR-033 strategy_loop complete!"
