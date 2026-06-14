#!/bin/bash
# push_fix_cloudflared_agents.sh — Push P0-3 + P1 fixes.
#   P0-3: cloudflared plist получил EnvironmentVariables (HOME/PATH), wrapper
#         расширен (~/.local/bin, command -v fallback). StandardErrorPath уже
#         был — диагностика exit 19968 теперь возможна, плюс устранена корневая
#         причина (отсутствие HOME → cloudflared не находил ~/.cloudflared).
#   P1:   install_agents.sh переписан на авто-обнаружение ВСЕХ com.spa.*.plist
#         (раньше хардкод-список пропускал fund-api/daily-paper-report/
#          weekly_backup/analytics_tier_c/checkpoint-7day).
#
# Cycle-мониторы (cycle_health/cycle_gap) проверены — оба exit 0, код не менялся.
#
# PAT chain: macOS Keychain (GITHUB_PAT_SPA) → env $GITHUB_PAT_SPA /
#            $GITHUB_PAT → ~/.github_pat. Без хардкод-секретов.
# Usage: bash scripts/push_fix_cloudflared_agents.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON="/Users/yuriikulieshov/miniconda3/bin/python3"

echo "╔══════════════════════════════════════════════════════╗"
echo "║  SPA — Push P0-3 (cloudflared) + P1 (install_agents) ║"
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
# 2. PAT (Keychain → env GITHUB_PAT_SPA → env GITHUB_PAT → ~/.github_pat)
# ─────────────────────────────────────────────────────────
echo ""
echo "[1/3] Получаем PAT..."
PAT=""

PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || true)
if [ -n "$PAT" ]; then
    echo "  ✅ PAT из Keychain (GITHUB_PAT_SPA)"
fi

if [ -z "$PAT" ] && [ -n "${GITHUB_PAT_SPA:-}" ]; then
    PAT="$GITHUB_PAT_SPA"
    echo "  ✅ PAT из env \$GITHUB_PAT_SPA"
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
    echo "     2. env: export GITHUB_PAT_SPA=<PAT>"
    echo "     3. файл: echo '<PAT>' > ~/.github_pat && chmod 600 ~/.github_pat"
    exit 1
fi

# ─────────────────────────────────────────────────────────
# 3. Файлы для пуша
# ─────────────────────────────────────────────────────────
echo ""
echo "[2/3] Проверяем файлы..."

FILES=(
    "$PROJECT_DIR/scripts/com.spa.cloudflared.plist"
    "$PROJECT_DIR/scripts/run_cloudflared.sh"
    "$PROJECT_DIR/scripts/install_agents.sh"
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
    --files "${FILES[@]}" \
    --message "fix(P0-3,P1): cloudflared stderr logging + install_agents all 19 + cycle monitors" \
    --pat "$PAT" \
    || RESULT=$?

echo ""
if [ "$RESULT" -eq 0 ]; then
    echo "╔══════════════════════════════════════════════════════╗"
    echo "║  ✅ Пуш успешен!                                     ║"
    echo "╚══════════════════════════════════════════════════════╝"
    echo ""
    echo "Запушено:"
    for f in "${FILES[@]}"; do
        echo "  • ${f#$PROJECT_DIR/}"
    done
else
    echo "╔══════════════════════════════════════════════════════╗"
    echo "║  ❌ Пуш завершился с ошибкой (exit $RESULT)          ║"
    echo "╚══════════════════════════════════════════════════════╝"
    exit 1
fi
