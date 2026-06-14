#!/bin/bash
# SPA full repo push
# Usage: SPA_GITHUB_TOKEN=ghp_xxx bash push_all.sh
# Or:    bash push_all.sh --token ghp_xxx
# Or:    bash push_all.sh --dry-run

set -euo pipefail

# Go to project root (two levels up from spa_core/tools/)
cd "$(dirname "$0")/../.."

echo "SPA GitHub Pusher — project root: $(pwd)"
echo ""

# Pass all CLI args through to the Python script
python -m spa_core.tools.github_pusher "$@"
