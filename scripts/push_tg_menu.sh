#!/usr/bin/env bash
# push_tg_menu.sh — Push updated Telegram bot (v2.1) to GitHub.
#
# Usage:
#   bash scripts/push_tg_menu.sh
#
# PAT is read from macOS Keychain (service GITHUB_PAT_SPA, account spa).
# Falls back to GITHUB_PAT env var. Never stored in any file.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

BOT_FILE="${REPO_ROOT}/spa_core/telegram/bot.py"

# ── Resolve PAT ──────────────────────────────────────────────────────────────

PAT=""

# 1. Try macOS Keychain (same account used by push_to_github.py)
if command -v security &>/dev/null; then
    PAT="$(security find-generic-password -s GITHUB_PAT_SPA -a spa -w 2>/dev/null || true)"
fi

# 2. Fallback to environment variable
if [[ -z "${PAT}" ]]; then
    PAT="${GITHUB_PAT:-}"
fi

if [[ -z "${PAT}" ]]; then
    echo "ERROR: No GitHub PAT found." >&2
    echo "       Add it with:  bash setup_pat.sh" >&2
    echo "       Or export:    export GITHUB_PAT=<token>" >&2
    exit 1
fi

export GITHUB_PAT="${PAT}"

# ── Syntax-check before push ─────────────────────────────────────────────────

echo "→ Syntax check: ${BOT_FILE}"
python3 -m py_compile "${BOT_FILE}"
echo "   OK"

# ── Push ─────────────────────────────────────────────────────────────────────

COMMIT_MSG="feat(telegram): bot v2.1 — /menu, /why, agents detail, setMyCommands"

echo "→ Pushing ${BOT_FILE}"
python3 "${REPO_ROOT}/push_to_github.py" \
    --files "${BOT_FILE}" \
    --message "${COMMIT_MSG}"

echo "Done."
