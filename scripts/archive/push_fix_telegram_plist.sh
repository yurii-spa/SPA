#!/bin/bash
# push_fix_telegram_plist.sh — Push P0-2 fix: resolve 3x com.spa.bot_commands.plist conflict.
# Canonical plist lives in scripts/; the two duplicates (root + launchd/) were renamed to .bak.
# PAT chain: macOS Keychain (GITHUB_PAT_SPA) → env $GITHUB_PAT_SPA / $GITHUB_PAT → ~/.github_pat
# No hardcoded secrets.
# Usage: bash scripts/push_fix_telegram_plist.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON="/Users/yuriikulieshov/miniconda3/bin/python3"

echo "╔══════════════════════════════════════════════════════╗"
echo "║  SPA — Push P0-2 fix: Telegram bot plist conflict   ║"
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
# 3. Файлы для пуша: canonical plist + .bak (фиксируем переименование дублей)
# ─────────────────────────────────────────────────────────
echo ""
echo "[2/3] Проверяем файлы..."

FILES=(
    "$PROJECT_DIR/scripts/com.spa.bot_commands.plist"
)

# .bak файлы добавляем только если существуют
for bak in \
    "$PROJECT_DIR/com.spa.bot_commands.plist.bak" \
    "$PROJECT_DIR/launchd/com.spa.bot_commands.plist.bak"
do
    [ -f "$bak" ] && FILES+=("$bak")
done

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
    --message "fix(P0-2): resolve 3x com.spa.bot_commands.plist conflict — canonical in scripts/" \
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
