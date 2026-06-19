#!/usr/bin/env bash
# scripts/push_v888.sh
# Sprint v8.88 — MP-1242 Family Fund Investor Cabinet FastAPI backend (:8766)
# Run on Mac: bash scripts/push_v888.sh
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
  "spa_core/family_fund/api/__init__.py"
  "spa_core/family_fund/api/app.py"
  "spa_core/family_fund/api/auth.py"
  "spa_core/family_fund/api/dependencies.py"
  "spa_core/family_fund/api/file_store.py"
  "spa_core/family_fund/api/keychain.py"
  "spa_core/family_fund/api/middleware.py"
  "spa_core/family_fund/api/models.py"
  "spa_core/family_fund/api/rate_limiter.py"
  "spa_core/family_fund/api/routes/__init__.py"
  "spa_core/family_fund/api/routes/auth.py"
  "spa_core/family_fund/api/routes/health.py"
  "spa_core/family_fund/api/routes/portfolio.py"
  "spa_core/family_fund/api/routes/yield_history.py"
  "spa_core/family_fund/run_api.py"
  "spa_core/family_fund/manage_users.py"
  "spa_core/family_fund/users.json"
  "spa_core/tests/test_family_fund_api/__init__.py"
  "spa_core/tests/test_family_fund_api/conftest.py"
  "spa_core/tests/test_family_fund_api/test_auth.py"
  "spa_core/tests/test_family_fund_api/test_infra.py"
  "spa_core/tests/test_family_fund_api/test_portfolio.py"
  "spa_core/tests/test_family_fund_api/test_yield_history.py"
)

ABS_FILES=()
for f in "${FILES[@]}"; do ABS_FILES+=("${REPO_ROOT}/${f}"); done

MSG="v8.88 MP-1242 Family Fund Investor Cabinet — FastAPI backend (auth/portfolio/yield), JWT HS256 stdlib, RBAC owner/admin/investor/readonly, TokenBucket rate-limit, file_store data/*.json, port 8766; 107 tests green [skip ci]"

echo "Pushing ${#ABS_FILES[@]} files..."
python3 "${REPO_ROOT}/push_to_github.py" \
  --files "${ABS_FILES[@]}" \
  --message "${MSG}"

echo "Push complete."
