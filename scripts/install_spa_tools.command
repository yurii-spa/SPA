#!/bin/bash
# install_spa_tools.command — установка markitdown, graphify, spec-kit
# Двойной клик в Finder для запуска

cd ~/Documents/SPA_Claude
LOG="logs/install_spa_tools_$(date +%Y%m%d_%H%M%S).log"
mkdir -p logs
exec > >(tee -a "$LOG") 2>&1

echo "════════════════════════════════════════════════"
echo " SPA — Установка инструментов"
echo " $(date '+%Y-%m-%d %H:%M:%S')"
echo "════════════════════════════════════════════════"
echo ""

# ── 1. markitdown ─────────────────────────────────
echo "▶ 1/3 markitdown (Microsoft)"
if python3 -c "import markitdown" 2>/dev/null; then
  echo "✅ markitdown уже установлен"
else
  pip3 install 'markitdown[all]' --quiet && \
    echo "✅ markitdown установлен" || \
    echo "❌ ошибка установки markitdown"
fi
echo ""

# ── 2. graphify ───────────────────────────────────
echo "▶ 2/3 graphify (Claude Code skill)"
if python3 -c "import graphify" 2>/dev/null; then
  echo "✅ graphify уже установлен"
else
  pip3 install graphifyy --quiet && \
    echo "✅ graphifyy установлен" || \
    echo "❌ ошибка установки graphify"
fi
echo ""

# ── 3. specify-cli (Spec Kit) ─────────────────────
echo "▶ 3/3 specify-cli (Spec Kit от GitHub)"
if command -v specify-cli &>/dev/null; then
  echo "✅ specify-cli уже установлен: $(specify-cli --version 2>/dev/null || echo 'ok')"
else
  if command -v uv &>/dev/null; then
    uv tool install specify-cli \
      --from "git+https://github.com/github/spec-kit.git" \
      --quiet 2>&1 && \
      echo "✅ specify-cli установлен" || \
      echo "❌ ошибка установки specify-cli"
  else
    echo "⚠️  uv не найден — установи uv сначала:"
    echo "   curl -LsSf https://astral.sh/uv/install.sh | sh"
    echo "   Затем перезапусти этот скрипт."
  fi
fi
echo ""

# ── Итог ──────────────────────────────────────────
echo "════════════════════════════════════════════════"
echo " Проверка после установки:"
python3 -c "import markitdown; print('  ✅ markitdown:', markitdown.__version__)" 2>/dev/null || echo "  ❌ markitdown не импортируется"
python3 -c "import graphify; print('  ✅ graphify: OK')" 2>/dev/null || echo "  ⚠️  graphify не импортируется (может быть норм — это CLI skill)"
command -v specify-cli &>/dev/null && echo "  ✅ specify-cli: OK" || echo "  ⚠️  specify-cli не в PATH"
echo ""
echo " Лог: $LOG"
echo "════════════════════════════════════════════════"
read -rp "Нажми Enter для закрытия..."
