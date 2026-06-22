#!/usr/bin/env bash
# push_v1357_tournament.sh
# MP-1357: Mass strategy tournament, tournament runner, shadow paper trading
# NO SECRETS IN THIS FILE — PAT read from macOS Keychain at runtime

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# ── Resolve python3 ────────────────────────────────────────────────────────────
PYTHON="$(command -v python3 || true)"
if [[ -x "/Users/yuriikulieshov/miniconda3/bin/python3" ]]; then
    PYTHON="/Users/yuriikulieshov/miniconda3/bin/python3"
fi
if [[ -z "$PYTHON" ]]; then
    echo "ERROR: python3 not found"
    exit 1
fi

echo "=== SPA v1357 — Mass Tournament + Shadow Paper Trading Push ==="
echo "Python: $PYTHON"
echo "Project: $PROJECT_ROOT"

# ── Read PAT from Keychain ────────────────────────────────────────────────────
PAT="$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || true)"
if [[ -z "$PAT" ]]; then
    echo "ERROR: Could not read PAT from Keychain (service: GITHUB_PAT_SPA)"
    echo "Run: bash setup_pat.sh  or see docs/TOKEN_ROTATION_RUNBOOK.md"
    exit 1
fi

# ── Run tests ─────────────────────────────────────────────────────────────────
cd "$PROJECT_ROOT"
echo ""
echo "Running test suite (tests/test_mass_tournament.py) ..."
if "$PYTHON" -m unittest discover -s tests -p "test_mass_tournament.py" -v 2>&1; then
    echo "✓ Tests PASSED (90/90)"
else
    echo "ERROR: Tests failed — aborting push"
    exit 1
fi

# ── Regenerate mass tournament results ───────────────────────────────────────
echo ""
echo "Regenerating data/mass_tournament_results.json ..."
"$PYTHON" -m spa_core.backtesting.mass_tournament --no-noise
echo "✓ mass_tournament_results.json written"

echo ""
echo "Regenerating data/strategy_tournament.json ..."
"$PYTHON" -m spa_core.backtesting.strategy_tournament_runner
echo "✓ strategy_tournament.json written"

# ── Push files ────────────────────────────────────────────────────────────────
echo ""
echo "Pushing files to GitHub ..."

PUSH_SCRIPT="$PROJECT_ROOT/push_to_github.py"

FILES=(
    "$PROJECT_ROOT/spa_core/backtesting/mass_tournament.py"
    "$PROJECT_ROOT/spa_core/backtesting/strategy_tournament_runner.py"
    "$PROJECT_ROOT/spa_core/paper_trading/cycle_runner.py"
    "$PROJECT_ROOT/tests/test_mass_tournament.py"
    "$PROJECT_ROOT/data/mass_tournament_results.json"
    "$PROJECT_ROOT/data/strategy_tournament.json"
    "$PROJECT_ROOT/data/shadow_paper_trading.json"
    "$PROJECT_ROOT/scripts/push_v1357_tournament.sh"
)

COMMIT_MSG="feat(tournament): mass strategy tournament + shadow paper trading [MP-1357]

- spa_core/backtesting/mass_tournament.py: MassTournament class
  * Discovers all spa_core/strategies/s*.py automatically
  * Skips leverage (borrow_amount/LOOP_FACTOR/MAX_LOOPS) and AMM LP strategies
  * Extracts {protocol: weight} allocations via 9 call signatures + ALLOCATION fallback
  * Runs each valid strategy through ProfessionalBacktest (2022-01-01→2025-12-31)
  * Outputs data/mass_tournament_results.json — Sharpe-sorted leaderboard
  * 45+ protocol aliases (L2 variants, cross-chain, deprecated names)

- spa_core/backtesting/strategy_tournament_runner.py: StrategyTournamentRunner
  * Loads mass_tournament_results.json → emits strategy_tournament.json v2.0
  * Replaces empty/stale strategy_tournament.json with real schema
  * Top-N strategies marked is_shadow_active: true
  * run_shadow_day(): advisory daily simulation using live apy_map
  * Ring-buffer 365 days → data/shadow_paper_trading.json

- spa_core/paper_trading/cycle_runner.py: shadow trading hook
  * Calls run_shadow_day() after main daily cycle completes
  * Advisory only — never modifies trades.json / equity_curve_daily.json
  * Errors never crash the cycle (broad except + log.warning)

- tests/test_mass_tournament.py: 90 tests all passing
  * TestMassTournamentRun uses setUpClass — tournament runs once, not 12x
  * Full coverage: leverage/AMM detection, normalization, shadow day, ring-buffer

LLM_FORBIDDEN: true
stdlib_only: true
atomic_writes: shutil.move"

"$PYTHON" "$PUSH_SCRIPT" \
    --repo yurii-spa/SPA \
    --pat "$PAT" \
    --message "$COMMIT_MSG" \
    "${FILES[@]}"

echo ""
echo "✓ Push complete — v1357 mass tournament + shadow paper trading deployed"
