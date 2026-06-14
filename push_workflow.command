#!/usr/bin/env bash
# push_workflow.command
# Pushes .github/workflows/spa-run.yml to GitHub using a token with 'workflow' scope.
# Run this file by double-clicking it in Finder (or: bash push_workflow.command)

set -euo pipefail

REPO="yurii-spa/SPA"
FILE_PATH=".github/workflows/spa-run.yml"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_FILE="$SCRIPT_DIR/$FILE_PATH"
API_URL="https://api.github.com/repos/$REPO/contents/$FILE_PATH"

echo ""
echo "========================================"
echo "  SPA — Push Workflow File to GitHub"
echo "========================================"
echo ""
echo "This script pushes: $FILE_PATH"
echo "To repo: $REPO"
echo ""
echo "You need a GitHub token with the 'workflow' scope."
echo "Create one at: https://github.com/settings/tokens/new"
echo "  → Select scopes: [x] repo   [x] workflow"
echo ""
read -rp "Paste your GitHub token (ghp_...): " TOKEN
echo ""

if [[ -z "$TOKEN" ]]; then
  echo "ERROR: No token provided. Exiting."
  exit 1
fi

if [[ ! -f "$LOCAL_FILE" ]]; then
  echo "ERROR: Local file not found: $LOCAL_FILE"
  exit 1
fi

echo "Reading local file..."
CONTENT_B64=$(base64 < "$LOCAL_FILE" | tr -d '\n')

echo "Checking if file already exists on GitHub..."
EXISTING=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.github+json" \
  "$API_URL")

if [[ "$EXISTING" == "200" ]]; then
  echo "File exists — fetching current SHA..."
  SHA=$(curl -s \
    -H "Authorization: Bearer $TOKEN" \
    -H "Accept: application/vnd.github+json" \
    "$API_URL" | python3 -c "import sys,json; print(json.load(sys.stdin)['sha'])")
  echo "Current SHA: $SHA"
  JSON_BODY=$(python3 -c "
import json, sys
print(json.dumps({
  'message': 'ci: update spa-run.yml workflow',
  'content': sys.argv[1],
  'sha': sys.argv[2]
}))
" "$CONTENT_B64" "$SHA")
else
  echo "File does not exist yet — will create it."
  JSON_BODY=$(python3 -c "
import json, sys
print(json.dumps({
  'message': 'ci: add spa-run.yml workflow',
  'content': sys.argv[1]
}))
" "$CONTENT_B64")
fi

echo ""
echo "Pushing to GitHub..."
RESPONSE=$(curl -s -w "\n%{http_code}" \
  -X PUT \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.github+json" \
  -H "Content-Type: application/json" \
  -d "$JSON_BODY" \
  "$API_URL")

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | head -n -1)

echo ""
if [[ "$HTTP_CODE" == "200" || "$HTTP_CODE" == "201" ]]; then
  echo "SUCCESS! ($HTTP_CODE) Workflow file pushed to GitHub."
  echo ""
  echo "View it at: https://github.com/$REPO/blob/main/$FILE_PATH"
  echo "Actions:    https://github.com/$REPO/actions"
else
  echo "FAILED! HTTP $HTTP_CODE"
  echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print('Message:', d.get('message','?'))" 2>/dev/null || echo "$BODY"
  echo ""
  echo "Common causes:"
  echo "  • Token missing 'workflow' scope — regenerate with [x] workflow checked"
  echo "  • Token expired or revoked"
  exit 1
fi

echo ""
read -rp "Press Enter to close..." _
