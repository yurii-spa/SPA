#!/bin/bash
# Sync the live dashboard (root index.html) into the Astro landing so Cloudflare
# Pages serves it at earn-defi.com/app.html. Run after editing the dashboard.
# LLM_FORBIDDEN. stdlib only.
set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cp "$ROOT/index.html" "$ROOT/landing/public/app.html"
echo "synced index.html -> landing/public/app.html ($(wc -c <"$ROOT/landing/public/app.html" | tr -d ' ') bytes)"
