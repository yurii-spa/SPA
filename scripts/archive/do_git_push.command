#!/bin/bash
# Temporary one-shot git push script — safe to delete after use
set -e
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null)
if [ -z "$PAT" ]; then
  echo "ERROR: PAT not found in Keychain (service: GITHUB_PAT_SPA)"
  exit 1
fi
cd ~/Documents/SPA_Claude
echo "Pushing to GitHub..."
git push "https://yurii-spa:${PAT}@github.com/yurii-spa/SPA.git" main
echo ""
echo "Done! Commit hash: $(git rev-parse HEAD)"
