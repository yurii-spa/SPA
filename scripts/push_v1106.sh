#!/usr/bin/env bash
# Push Sprint v11.06 — MP-1490 Cross-chain dashboard panel
# Usage: bash scripts/push_v1106.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=== Sprint v11.06 — MP-1490 Cross-chain dashboard panel ==="

python3 "${REPO_ROOT}/push_to_github.py" \
  --files \
    "${REPO_ROOT}/landing/src/pages/dashboard.astro" \
  --message "Sprint v11.06 — MP-1490 Cross-chain dashboard panel"

echo "✅  v11.06 pushed."
