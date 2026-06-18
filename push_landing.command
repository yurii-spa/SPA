#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "=== SPA: push landing/ to GitHub ==="

# Remove stale lock if present
[ -f .git/index.lock ] && rm -f .git/index.lock && echo "Removed stale index.lock"

# Load PAT from Keychain
PAT=$(security find-generic-password -s 'GITHUB_PAT_SPA' -w 2>/dev/null)
if [ -z "$PAT" ]; then
  echo "ERROR: Could not load GITHUB_PAT_SPA from Keychain"
  read -n 1 -s -r -p "Press any key to close..."
  exit 1
fi
echo "PAT loaded: ${#PAT} chars"

# Stage landing/
git add landing/
echo "Staged:"
git status --short | grep landing

# Commit
git commit -m "feat: add Astro 4 landing page (earn-defi.com)

- 19 files: Astro 4 + Tailwind CSS + React islands
- Hero with 'Autonomous Yield Infrastructure' copy
- LiveStats widget (60s polling, graceful fallback)
- Competitor comparison table vs Enzyme/dHEDGE/Yearn
- Fee structure section (1.5% mgmt + 15% perf + HWM)
- Risk disclosure page (regulatory compliant)
- Cloudflare Pages ready (output=static, _redirects)
- ADR-006: Astro chosen over Next.js (8KB vs 85KB JS bundle)"

echo "Committed: $(git log --oneline -1)"

# Push
REMOTE_URL="https://${PAT}@github.com/yurii-spa/SPA.git"
git push "$REMOTE_URL" main 2>&1 | tail -5

echo ""
echo "=== DONE ==="
git log --oneline -3
echo ""
read -n 1 -s -r -p "Press any key to close..."
