#!/usr/bin/env bash
# scripts/push_v1231.sh
# Sprint v12.31 — MP-1231 Kelly Criterion position sizing + strategy parameter optimization
# Run on Mac: bash scripts/push_v1231.sh
# PAT is resolved at runtime from a fallback chain — NEVER hardcoded.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# ── resolve PAT: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat ──
GITHUB_PAT=""
# 1) macOS Keychain
GITHUB_PAT="$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || true)"
# 2) env GITHUB_PAT_SPA
if [ -z "$GITHUB_PAT" ]; then
  GITHUB_PAT="${GITHUB_PAT_SPA:-}"
fi
# 3) env SPA_GITHUB_PAT
if [ -z "$GITHUB_PAT" ]; then
  GITHUB_PAT="${SPA_GITHUB_PAT:-}"
fi
# 4) file ~/.github_pat
if [ -z "$GITHUB_PAT" ] && [ -f "$HOME/.github_pat" ]; then
  GITHUB_PAT="$(tr -d '\r\n' < "$HOME/.github_pat" || true)"
fi

if [ -z "$GITHUB_PAT" ]; then
  echo "ERROR: GitHub PAT not found." >&2
  echo "       Tried: Keychain(GITHUB_PAT_SPA) → \$GITHUB_PAT_SPA → \$SPA_GITHUB_PAT → ~/.github_pat" >&2
  echo "       See docs/TOKEN_ROTATION_RUNBOOK.md" >&2
  exit 1
fi
export GITHUB_PAT

# ── files changed in v12.31 (MP-1231) ────────────────────────────────────────
# Dependency closure: the three modules import only already-committed code
# (allocator.allocator, risk.policy, utils.atomic) — no extra deps to push.
FILES=(
  "spa_core/allocator/kelly_sizer.py"
  "spa_core/allocator/parameter_optimizer.py"
  "spa_core/allocator/dynamic_allocator.py"
  "tests/test_kelly_optimizer.py"
  "data/optimized_params.json"
  "scripts/push_v1231.sh"
)

# Convert to absolute paths (relative paths collapse to basename in pusher).
ABS_FILES=()
for f in "${FILES[@]}"; do
  ABS_FILES+=("${REPO_ROOT}/${f}")
done

MSG="v12.31 MP-1231 Kelly Criterion sizing + parameter optimizer (43 tests) — half-Kelly f*=(p·b−q)/b with tier hack-rates T1=0.5%/T2=2%/T3=5%; DynamicAllocator 50/50 Kelly×equal blend under RiskConfig caps; grid-search optimizer (81 combos) → data/optimized_params.json"

echo "Pushing ${#ABS_FILES[@]} files..."
python3 "${REPO_ROOT}/push_to_github.py" \
  --files "${ABS_FILES[@]}" \
  --message "${MSG}"

echo "Push v12.31 complete."
