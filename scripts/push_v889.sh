#!/usr/bin/env bash
# scripts/push_v889.sh
# Sprint v8.89 — MP-1243 Investor Cabinet React SPA (cabinet/) + v8.89 reconcile bookkeeping
# Run on Mac: bash scripts/push_v889.sh
# PAT is resolved at runtime from a fallback chain — NEVER hardcoded.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# ── resolve PAT: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat ──
GITHUB_PAT=""
GITHUB_PAT="$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || true)"
if [ -z "$GITHUB_PAT" ]; then GITHUB_PAT="${GITHUB_PAT_SPA:-}"; fi
if [ -z "$GITHUB_PAT" ]; then GITHUB_PAT="${SPA_GITHUB_PAT:-}"; fi
if [ -z "$GITHUB_PAT" ] && [ -f "$HOME/.github_pat" ]; then GITHUB_PAT="$(tr -d "\r\n" < "$HOME/.github_pat" || true)"; fi
if [ -z "$GITHUB_PAT" ]; then
  echo "ERROR: GitHub PAT not found." >&2
  echo "       Tried: Keychain(GITHUB_PAT_SPA) → \$GITHUB_PAT_SPA → \$SPA_GITHUB_PAT → ~/.github_pat" >&2
  exit 1
fi
export GITHUB_PAT

FILES=(
  "cabinet/.env.development"
  "cabinet/.env.production"
  "cabinet/.gitignore"
  "cabinet/deploy.command"
  "cabinet/dist/_redirects"
  "cabinet/dist/assets/index-CkiTojIS.css"
  "cabinet/dist/assets/index-I9sz5MLe.js"
  "cabinet/dist/favicon.svg"
  "cabinet/dist/index.html"
  "cabinet/index.html"
  "cabinet/package-lock.json"
  "cabinet/package.json"
  "cabinet/postcss.config.js"
  "cabinet/public/_redirects"
  "cabinet/public/favicon.svg"
  "cabinet/src/App.jsx"
  "cabinet/src/api/client.js"
  "cabinet/src/auth/AuthContext.jsx"
  "cabinet/src/auth/ProtectedRoute.jsx"
  "cabinet/src/components/EquityCurve.jsx"
  "cabinet/src/components/KpiCard.jsx"
  "cabinet/src/components/PositionsTable.jsx"
  "cabinet/src/components/SystemStatus.jsx"
  "cabinet/src/components/YieldTable.jsx"
  "cabinet/src/components/ui/Badge.jsx"
  "cabinet/src/components/ui/Button.jsx"
  "cabinet/src/components/ui/Card.jsx"
  "cabinet/src/components/ui/Spinner.jsx"
  "cabinet/src/index.css"
  "cabinet/src/lib/format.js"
  "cabinet/src/main.jsx"
  "cabinet/src/pages/DashboardPage.jsx"
  "cabinet/src/pages/LoginPage.jsx"
  "cabinet/tailwind.config.js"
  "cabinet/vite.config.js"
  "cabinet/wrangler.toml"
  "sprint_log.md"
  "KANBAN.json"
  "scripts/push_v888.sh"
  "scripts/push_v889.sh"
)

ABS_FILES=()
for f in "${FILES[@]}"; do ABS_FILES+=("${REPO_ROOT}/${f}"); done

MSG="v8.89 MP-1243 Investor Cabinet — React SPA (cabinet/): Vite + React 18, Tailwind, TanStack Query v5, Recharts, React Router v6; in-memory access token + httpOnly-cookie refresh, ProtectedRoute, Login + Dashboard (5 KPI cards, equity AreaChart, positions/yield tables, system status); dark DeFi theme; consumes Family Fund API :8766; prod build green; CF Pages app.earn-defi.com [skip ci]"

echo "Pushing ${#ABS_FILES[@]} files..."
python3 "${REPO_ROOT}/push_to_github.py" \
  --files "${ABS_FILES[@]}" \
  --message "${MSG}"

echo "Push complete."
