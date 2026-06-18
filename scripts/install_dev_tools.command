#!/bin/bash
# install_dev_tools.command — установка dev инструментов для SPA
# Двойной клик для запуска или: bash ~/Documents/SPA_Claude/scripts/install_dev_tools.command

set -uo pipefail
cd ~/Documents/SPA_Claude

LOG="$HOME/Documents/SPA_Claude/logs/install_dev_tools_$(date +%Y%m%d_%H%M%S).log"
mkdir -p "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1

echo "════════════════════════════════════════════"
echo " SPA Dev Tools Install — $(date '+%Y-%m-%d %H:%M:%S')"
echo "════════════════════════════════════════════"

PYTHON="/Users/yuriikulieshov/miniconda3/bin/python3"
PIP="/Users/yuriikulieshov/miniconda3/bin/pip"

# ── 1. markitdown ─────────────────────────────
echo ""
echo "▶ [1/6] markitdown (Microsoft) — PDF/DOCX/YouTube → Markdown"
if "$PYTHON" -c "import markitdown" 2>/dev/null; then
  echo "  ✅ уже установлен, обновляю..."
  "$PIP" install --upgrade 'markitdown[all]' --quiet
else
  "$PIP" install 'markitdown[all]' --quiet
fi
"$PYTHON" -c "from markitdown import MarkItDown; print('  ✅ markitdown OK')"

# ── 2. Graphify ───────────────────────────────
echo ""
echo "▶ [2/6] Graphify — knowledge graph (Claude Code skill)"
if command -v graphify &>/dev/null; then
  echo "  ✅ graphify CLI уже есть, обновляю pip пакет..."
  "$PIP" install --upgrade graphifyy --quiet
else
  "$PIP" install graphifyy --quiet
  # graphify install ставит SKILL.md в ~/.claude/skills/
  if command -v graphify &>/dev/null; then
    graphify install && echo "  ✅ graphify install OK"
  else
    # Fallback: manual skill install
    mkdir -p ~/.claude/skills/graphify
    curl -fsSL https://raw.githubusercontent.com/safishamsi/graphify/v1/skills/graphify/skill.md \
      > ~/.claude/skills/graphify/SKILL.md 2>/dev/null && echo "  ✅ graphify SKILL.md установлен вручную"
  fi
fi

# ── 3. Scrapling ──────────────────────────────
echo ""
echo "▶ [3/6] Scrapling — адаптивный скрапер для DeFi данных"
if "$PYTHON" -c "import scrapling" 2>/dev/null; then
  echo "  ✅ уже установлен, обновляю..."
  "$PIP" install --upgrade scrapling --quiet
else
  "$PIP" install scrapling --quiet
fi
"$PYTHON" -c "import scrapling; print('  ✅ scrapling OK')"
# Установить браузерные движки для Scrapling (опционально)
if command -v scrapling &>/dev/null; then
  scrapling install 2>/dev/null && echo "  ✅ scrapling browsers OK" || echo "  ⚠️ scrapling install browsers — пропущено (не критично)"
fi

# ── 4. Spec Kit ───────────────────────────────
echo ""
echo "▶ [4/6] Spec Kit — Spec-Driven Development CLI"
if command -v uv &>/dev/null; then
  echo "  uv найден: $(uv --version)"
  if command -v specify &>/dev/null; then
    echo "  ✅ specify-cli уже установлен, обновляю..."
    uv tool install --force specify-cli --from "git+https://github.com/github/spec-kit.git@v0.9.0" 2>&1 | tail -3
  else
    uv tool install specify-cli --from "git+https://github.com/github/spec-kit.git@v0.9.0" 2>&1 | tail -3
  fi
  if command -v specify &>/dev/null; then
    echo "  ✅ specify $(specify --version 2>/dev/null || echo 'installed') OK"
    # Инициализировать SPA_Dev если .specify ещё не создан
    if [ ! -d ~/Documents/SPA_Dev/.specify ]; then
      echo "  Инициализирую SPA_Dev с интеграцией claude..."
      (cd ~/Documents/SPA_Dev && specify init . --integration claude --force) \
        && echo "  ✅ SPA_Dev/.specify создан" \
        || echo "  ⚠️ specify init — ошибка, запусти вручную: cd ~/Documents/SPA_Dev && specify init . --integration claude"
    else
      echo "  ✅ SPA_Dev/.specify уже существует"
    fi
  else
    echo "  ⚠️ specify не в PATH после установки. Попробуй: uv tool update-shell"
  fi
else
  echo "  ⚠️ uv не найден — устанавливаю uv сначала..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  source ~/.zprofile 2>/dev/null || true
  source ~/.bashrc 2>/dev/null || true
  if command -v uv &>/dev/null; then
    uv tool install specify-cli --from "git+https://github.com/github/spec-kit.git@v0.9.0" && \
      echo "  ✅ Spec Kit OK"
  else
    echo "  ❌ uv установить не удалось. Установи вручную: https://docs.astral.sh/uv/"
  fi
fi

# ── 5. ccpi — менеджер Claude Code плагинов ───
echo ""
echo "▶ [5/6] ccpi — Claude Code plugin manager (425 plugins / 2810 skills)"
if command -v pnpm &>/dev/null; then
  echo "  pnpm найден: $(pnpm --version)"
  if command -v ccpi &>/dev/null; then
    echo "  ✅ ccpi уже установлен"
  else
    pnpm add -g @intentsolutionsio/ccpi 2>&1 | tail -3
    command -v ccpi &>/dev/null && echo "  ✅ ccpi OK" || echo "  ⚠️ ccpi — проверь pnpm global bin в PATH"
  fi
elif command -v npm &>/dev/null; then
  echo "  npm найден, устанавливаю через npm..."
  npm install -g @intentsolutionsio/ccpi 2>&1 | tail -3
  command -v ccpi &>/dev/null && echo "  ✅ ccpi OK" || echo "  ⚠️ ccpi — проверь npm global bin"
else
  echo "  ⚠️ pnpm/npm не найдены — ccpi пропущен (установи Node.js)"
fi

# ── 6. CodeGraph ──────────────────────────────
echo ""
echo "▶ [6/6] CodeGraph — knowledge graph (-58% tool calls)"
if command -v npx &>/dev/null; then
  # CodeGraph устанавливается как npx инструмент (разово)
  echo "  npx найден, проверяю CodeGraph..."
  npx --yes @colbymchenry/codegraph --version 2>/dev/null && echo "  ✅ CodeGraph OK" \
    || echo "  ✅ CodeGraph доступен через: npx @colbymchenry/codegraph"
else
  echo "  ⚠️ npx не найден — CodeGraph пропущен (установи Node.js)"
fi

# ── Итог ─────────────────────────────────────
echo ""
echo "════════════════════════════════════════════"
echo " Установка завершена — $(date '+%H:%M:%S')"
echo "════════════════════════════════════════════"
echo ""
echo "Проверка:"
echo "  markitdown:  $("$PYTHON" -c "import markitdown; print(markitdown.__version__)" 2>/dev/null || echo 'не найден')"
echo "  graphify:    $(command -v graphify &>/dev/null && echo OK || echo 'не найден')"
echo "  scrapling:   $("$PYTHON" -c "import scrapling; print(scrapling.__version__)" 2>/dev/null || echo 'не найден')"
echo "  specify:     $(command -v specify &>/dev/null && specify --version 2>/dev/null || echo 'не найден')"
echo "  ccpi:        $(command -v ccpi &>/dev/null && echo OK || echo 'не найден')"
echo "  npx:         $(command -v npx &>/dev/null && echo OK || echo 'не найден')"
echo ""
echo "Лог: $LOG"
echo ""
echo "Следующие шаги:"
echo "  • Graphify: открой Claude Code в ~/Documents/SPA_Claude и запусти /graphify ."
echo "  • Spec Kit: открой Claude Code в ~/Documents/SPA_Dev и запусти /speckit.constitution"
echo "  • Claude Code плагины: /plugin install feature-dev@claude-plugins-official"
