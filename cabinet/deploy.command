#!/bin/bash
# Deploy the Investor Cabinet SPA to Cloudflare Pages (project: earn-defi-cabinet).
#
# One-time setup (CF dashboard):
#   1. Create a Pages project named "earn-defi-cabinet" (Direct Upload).
#   2. Add custom domain: app.earn-defi.com → this project.
#
# Auth: wrangler reads CLOUDFLARE_API_TOKEN from env, or runs `wrangler login`.
# This script writes NO secrets to disk.
set -euo pipefail

CABINET_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$CABINET_DIR"

echo "==> Investor Cabinet — Cloudflare Pages deploy"
echo "    dir: $CABINET_DIR"

# 1. Install deps if missing (isolated cache avoids root-owned ~/.npm issues).
if [ ! -d node_modules ]; then
  echo "==> Installing dependencies..."
  npm install --cache /tmp/npm-cache-cabinet
fi

# 2. Production build (uses .env.production → VITE_API_URL=https://api.earn-defi.com).
echo "==> Building (production)..."
npm run build

# 3. Deploy the static output to Cloudflare Pages.
echo "==> Deploying dist/ to Cloudflare Pages (earn-defi-cabinet)..."
npx --yes wrangler@latest pages deploy dist \
  --project-name=earn-defi-cabinet \
  --commit-dirty=true

echo "==> Done. Live at: https://app.earn-defi.com (once custom domain is attached)."
