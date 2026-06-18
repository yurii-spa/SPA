#!/usr/bin/env bash
# deploy_landing.command — деплой лендинга earn-defi.com на Cloudflare Pages.
# ЕДИНСТВЕННЫЙ скрипт, который должен триггерить CF Pages билд.
# Все остальные пуши содержат [skip ci] и CF Pages не билдит.
set -e
cd ~/Documents/SPA_Claude

PAT=$(security find-generic-password -s 'GITHUB_PAT_SPA' -w 2>/dev/null)
REMOTE="https://${PAT}@github.com/yurii-spa/SPA.git"

echo "► Синхронизируем с remote перед деплоем..."
git fetch "$REMOTE" main 2>/dev/null || true
git rebase "$REMOTE/main" 2>/dev/null || git pull --rebase "$REMOTE" main 2>/dev/null || true

# Проверяем наличие landing/ директории
if [ ! -d "landing" ]; then
    echo "❌ Директория landing/ не найдена!"
    exit 1
fi

echo "► Стейджим landing/ и wrangler.toml..."
git add landing/ wrangler.toml

if git diff --staged --quiet; then
    echo "ℹ️  Нет изменений в landing/ для деплоя"
    echo "   Если нужно принудительно передеплоить — запусти:"
    echo "   git commit --allow-empty -m 'chore: force redeploy landing' && git push"
    exit 0
fi

# Commit БЕЗ [skip ci] — CF Pages должен увидеть этот коммит и сбилдить
git commit -m "deploy: update earn-defi.com landing page"

echo "► Пушим в GitHub (CF Pages триггернётся автоматически)..."
git push "$REMOTE" main

echo ""
echo "✅ Лендинг запушен! CF Pages начнёт билд через ~30с."
echo "   Следи за статусом: https://dash.cloudflare.com/$CLOUDFLARE_ACCOUNT_ID/pages/view/earn-defi"
