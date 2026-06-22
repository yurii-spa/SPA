#!/bin/bash
# start_claude_on_macmini.command — двойной клик на Mac mini.
#
# Назначение: запустить Claude Code (CLI) ЛОКАЛЬНО на самом Mac mini, в каталоге
# этого репозитория. Только так у Claude появляется реальный доступ к машине:
# launchctl, Keychain (PAT), локальный туннель и локальные MCP. Облачная
# веб-сессия Claude к Mac mini дотянуться не может — это другой дата-центр.
#
# Безопасность: скрипт НЕ содержит и НЕ просит секретов. Логин в Anthropic
# происходит в браузере при первом запуске `claude` (OAuth), без вставки ключей
# в файлы. PAT остаётся в Keychain.
#
# Идемпотентно: повторный двойной клик просто заново откроет сессию.

set -euo pipefail

# ── Самолокация: каталог, где лежит сам .command (= корень репо) ──────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
cd "$SCRIPT_DIR"

echo "═══════════════════════════════════════════════════════════════"
echo " SPA · запуск Claude Code на Mac mini"
echo " Каталог проекта: $SCRIPT_DIR"
echo "═══════════════════════════════════════════════════════════════"
echo

# ── 1. Node.js (нужен 18+) ───────────────────────────────────────────────────
if ! command -v node >/dev/null 2>&1; then
  echo "⚠️  Node.js не найден."
  if command -v brew >/dev/null 2>&1; then
    echo "→ Ставлю через Homebrew: brew install node"
    brew install node
  else
    echo "❌ Нет ни node, ни brew."
    echo "   Поставь Node 18+ : https://nodejs.org  (или сперва Homebrew: https://brew.sh)"
    echo "   Потом запусти этот файл снова."
    read -r -p "Нажми Enter, чтобы закрыть..."
    exit 1
  fi
fi

NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
echo "✓ Node $(node -v)  (major=$NODE_MAJOR)"
if [ "$NODE_MAJOR" -lt 18 ]; then
  echo "⚠️  Нужен Node 18+. Обнови Node и запусти снова."
  read -r -p "Нажми Enter, чтобы закрыть..."
  exit 1
fi

# ── 2. Claude Code CLI ───────────────────────────────────────────────────────
if ! command -v claude >/dev/null 2>&1; then
  echo "⚠️  Claude Code CLI не найден — ставлю глобально через npm…"
  if npm install -g @anthropic-ai/claude-code; then
    echo "✓ Claude Code установлен."
  else
    echo "❌ npm install не прошёл (возможно нужны права)."
    echo "   Попробуй вручную:  sudo npm install -g @anthropic-ai/claude-code"
    read -r -p "Нажми Enter, чтобы закрыть..."
    exit 1
  fi
fi
echo "✓ Claude Code: $(command -v claude)"
echo

# ── 3. Запуск интерактивной сессии Claude в каталоге проекта ─────────────────
echo "→ Запускаю claude. При первом старте будет вход через браузер (OAuth)."
echo "  После входа Claude работает ВНУТРИ Mac mini: launchctl / Keychain / туннель доступны."
echo
exec claude
