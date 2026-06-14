#!/bin/bash
# push_agent_audit_v2.sh — Push AGENT_AUDIT_V2.md + KANBAN.json to GitHub
# PAT chain: macOS Keychain (GITHUB_PAT_SPA) → env $GITHUB_PAT → ~/.github_pat
# No hardcoded secrets.
# Usage: bash scripts/push_agent_audit_v2.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON="/Users/yuriikulieshov/miniconda3/bin/python3"

echo "╔══════════════════════════════════════════════════════╗"
echo "║  SPA — Push Agent Audit v2.0                        ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ─────────────────────────────────────────────────────────
# 1. Проверяем Python
# ─────────────────────────────────────────────────────────
if [ ! -x "$PYTHON" ]; then
    # Fallback: системный python3
    PYTHON="$(command -v python3 2>/dev/null || true)"
    if [ -z "$PYTHON" ]; then
        echo "❌ ERROR: python3 не найден. Проверь miniconda или PATH."
        exit 1
    fi
fi
echo "✅ Python: $($PYTHON --version 2>&1)"

# ─────────────────────────────────────────────────────────
# 2. Получаем PAT (Keychain → env → ~/.github_pat)
# ─────────────────────────────────────────────────────────
echo ""
echo "[1/3] Получаем PAT..."
PAT=""

# Попытка 1: macOS Keychain
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || true)
if [ -n "$PAT" ]; then
    echo "  ✅ PAT из Keychain (GITHUB_PAT_SPA)"
fi

# Попытка 2: env переменная
if [ -z "$PAT" ] && [ -n "${GITHUB_PAT:-}" ]; then
    PAT="$GITHUB_PAT"
    echo "  ✅ PAT из env \$GITHUB_PAT"
fi

# Попытка 3: ~/.github_pat файл
if [ -z "$PAT" ] && [ -f "$HOME/.github_pat" ]; then
    PAT=$(cat "$HOME/.github_pat" | tr -d '[:space:]')
    echo "  ✅ PAT из ~/.github_pat"
fi

if [ -z "$PAT" ]; then
    echo "  ❌ PAT не найден!"
    echo "     Варианты:"
    echo "     1. Keychain: security add-generic-password -s GITHUB_PAT_SPA -w <PAT>"
    echo "     2. env: export GITHUB_PAT=<PAT>"
    echo "     3. файл: echo '<PAT>' > ~/.github_pat && chmod 600 ~/.github_pat"
    exit 1
fi

# ─────────────────────────────────────────────────────────
# 3. Проверяем что файлы существуют
# ─────────────────────────────────────────────────────────
echo ""
echo "[2/3] Проверяем файлы..."

FILES=(
    "$PROJECT_DIR/docs/AGENT_AUDIT_V2.md"
    "$PROJECT_DIR/KANBAN.json"
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

# Передаём PAT через env переменную (не через файл, не через аргументы)
# push_to_github.py читает PAT из Keychain сам — просто запускаем
RESULT=0
"$PYTHON" "$PROJECT_DIR/push_to_github.py" \
    --files \
    "$PROJECT_DIR/docs/AGENT_AUDIT_V2.md" \
    "$PROJECT_DIR/KANBAN.json" \
    --message "AGENT_AUDIT_V2: полный аудит агентной системы (19 агентов, 11 задач P0/P1) [2026-06-14]" \
    || RESULT=$?

echo ""
if [ "$RESULT" -eq 0 ]; then
    echo "╔══════════════════════════════════════════════════════╗"
    echo "║  ✅ Пуш успешен!                                     ║"
    echo "╚══════════════════════════════════════════════════════╝"
    echo ""
    echo "Запушено:"
    echo "  • docs/AGENT_AUDIT_V2.md"
    echo "  • KANBAN.json"
else
    echo "╔══════════════════════════════════════════════════════╗"
    echo "║  ❌ Пуш завершился с ошибкой (exit $RESULT)          ║"
    echo "╚══════════════════════════════════════════════════════╝"
    echo ""
    echo "Диагностика:"
    echo "  1. PAT актуален? → security find-generic-password -s GITHUB_PAT_SPA -w"
    echo "  2. Ротация PAT:  → bash setup_pat.sh"
    echo "  3. Runbook:      → docs/TOKEN_ROTATION_RUNBOOK.md"
    exit 1
fi
