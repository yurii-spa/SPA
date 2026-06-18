#!/bin/bash
# push_audit_v3.sh — пуш AGENT_AUDIT_V3.md + KANBAN.json в GitHub
# PAT: macOS Keychain (GITHUB_PAT_SPA) → env GITHUB_PAT → ~/.github_pat
# Без хардкода секретов (см. SECRETS POLICY в CLAUDE.md)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PUSH_SCRIPT="$REPO_ROOT/push_to_github.py"
PYTHON=/Users/yuriikulieshov/miniconda3/bin/python3

FILES=(
  "$REPO_ROOT/docs/AGENT_AUDIT_V3.md"
  "$REPO_ROOT/KANBAN.json"
)

MESSAGE="docs: AGENT_AUDIT_V3 — полный аудит агентов 2026-06-14 (19 агентов, 4 P0-багов, Tier 1 roadmap)"

# ── Проверка файлов ──────────────────────────────────────────────────────────
for f in "${FILES[@]}"; do
  if [ ! -f "$f" ]; then
    echo "ERROR: файл не найден: $f" >&2
    exit 1
  fi
done
echo "✅ Файлы найдены: ${#FILES[@]}"

# ── Проверка push_to_github.py ────────────────────────────────────────────────
if [ ! -f "$PUSH_SCRIPT" ]; then
  echo "ERROR: $PUSH_SCRIPT не найден" >&2
  exit 1
fi

# ── Проверка Python ───────────────────────────────────────────────────────────
if [ ! -x "$PYTHON" ]; then
  PYTHON=$(which python3)
  echo "⚠️  miniconda не найден, используем: $PYTHON"
fi

echo "Python: $PYTHON"
echo "Push: ${FILES[*]}"
echo "Message: $MESSAGE"
echo ""

# ── Запуск пуша ──────────────────────────────────────────────────────────────
cd "$REPO_ROOT"
"$PYTHON" "$PUSH_SCRIPT" \
  --files "${FILES[@]}" \
  --message "$MESSAGE"

STATUS=$?
if [ $STATUS -eq 0 ]; then
  echo ""
  echo "✅ Push завершён успешно"
else
  echo ""
  echo "❌ Push завершился с ошибкой (exit=$STATUS)" >&2
  exit $STATUS
fi
