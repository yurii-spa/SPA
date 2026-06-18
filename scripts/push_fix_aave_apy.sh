#!/bin/bash
# push_fix_aave_apy.sh — Push Aave V3 stale-APY DL-04 fix to GitHub
# Fixes the spurious "aave_v3 APY 0.00% below sanity floor 0.5% (stale data?)"
# warning by excluding adapters with no live data from the DL-04 sanity map.
# PAT chain: macOS Keychain (GITHUB_PAT_SPA) → env $GITHUB_PAT → ~/.github_pat
# No hardcoded secrets.
# Usage: bash scripts/push_fix_aave_apy.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON="/Users/yuriikulieshov/miniconda3/bin/python3"

echo "╔══════════════════════════════════════════════════════╗"
echo "║  SPA — Push Aave V3 APY stale-data fix              ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ─────────────────────────────────────────────────────────
# 1. Python
# ─────────────────────────────────────────────────────────
if [ ! -x "$PYTHON" ]; then
    PYTHON="$(command -v python3 2>/dev/null || true)"
    if [ -z "$PYTHON" ]; then
        echo "❌ ERROR: python3 не найден. Проверь miniconda или PATH."
        exit 1
    fi
fi
echo "✅ Python: $($PYTHON --version 2>&1)"

# ─────────────────────────────────────────────────────────
# 2. PAT (Keychain → env → ~/.github_pat)
# ─────────────────────────────────────────────────────────
echo ""
echo "[1/3] Получаем PAT..."
PAT=""

PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || true)
if [ -n "$PAT" ]; then
    echo "  ✅ PAT из Keychain (GITHUB_PAT_SPA)"
fi

if [ -z "$PAT" ] && [ -n "${GITHUB_PAT:-}" ]; then
    PAT="$GITHUB_PAT"
    echo "  ✅ PAT из env \$GITHUB_PAT"
fi

if [ -z "$PAT" ] && [ -f "$HOME/.github_pat" ]; then
    PAT=$(cat "$HOME/.github_pat" | tr -d '[:space:]')
    echo "  ✅ PAT из ~/.github_pat"
fi

if [ -z "$PAT" ]; then
    echo "  ❌ PAT не найден!"
    echo "     1. Keychain: security add-generic-password -s GITHUB_PAT_SPA -w <PAT>"
    echo "     2. env: export GITHUB_PAT=<PAT>"
    echo "     3. файл: echo '<PAT>' > ~/.github_pat && chmod 600 ~/.github_pat"
    exit 1
fi

# ─────────────────────────────────────────────────────────
# 3. Файлы
# ─────────────────────────────────────────────────────────
echo ""
echo "[2/3] Проверяем файлы..."

FILES=(
    "$PROJECT_DIR/spa_core/paper_trading/cycle_runner.py"
    "$PROJECT_DIR/tests/test_aave_v3_apy_feed.py"
    "$PROJECT_DIR/data/paper_trading_status.json"
)

for f in "${FILES[@]}"; do
    if [ -f "$f" ]; then
        size=$(wc -c < "$f" 2>/dev/null | tr -d ' ')
        echo "  ✅ $(basename "$f") (${size} bytes)"
    else
        echo "  ❌ Не найден: $f"
        exit 1
    fi
done

# ─────────────────────────────────────────────────────────
# 4. Пуш через push_to_github.py
# ─────────────────────────────────────────────────────────
echo ""
echo "[3/3] Пуш в GitHub..."

RESULT=0
"$PYTHON" "$PROJECT_DIR/push_to_github.py" \
    --files \
    "$PROJECT_DIR/spa_core/paper_trading/cycle_runner.py" \
    "$PROJECT_DIR/tests/test_aave_v3_apy_feed.py" \
    "$PROJECT_DIR/data/paper_trading_status.json" \
    --message "fix(aave_v3): exclude no-live-data adapters from DL-04 sanity map — kills spurious 'APY 0.00% stale data' warning; +15 tests [2026-06-14]" \
    || RESULT=$?

echo ""
if [ "$RESULT" -eq 0 ]; then
    echo "╔══════════════════════════════════════════════════════╗"
    echo "║  ✅ Пуш успешен!                                     ║"
    echo "╚══════════════════════════════════════════════════════╝"
    echo ""
    echo "Запушено:"
    echo "  • spa_core/paper_trading/cycle_runner.py"
    echo "  • tests/test_aave_v3_apy_feed.py"
    echo "  • data/paper_trading_status.json"
else
    echo "╔══════════════════════════════════════════════════════╗"
    echo "║  ❌ Пуш завершился с ошибкой (exit $RESULT)          ║"
    echo "╚══════════════════════════════════════════════════════╝"
    echo ""
    echo "Диагностика:"
    echo "  1. PAT актуален? → security find-generic-password -s GITHUB_PAT_SPA -w"
    echo "  2. Ротация PAT:  → bash setup_pat.sh"
    exit 1
fi
