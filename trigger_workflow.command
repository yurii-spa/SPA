#!/usr/bin/env bash
# trigger_workflow.command
# Manually triggers the spa-run.yml workflow via GitHub Actions workflow_dispatch API.
# Uses the existing project token (repo scope).
# Run by double-clicking in Finder (or: bash trigger_workflow.command)

set -euo pipefail

REPO="yurii-spa/SPA"
WORKFLOW="spa-run.yml"
BRANCH="main"
TOKEN="$(security find-generic-password -s GITHUB_PAT_SPA -w)"
API_URL="https://api.github.com/repos/$REPO/actions/workflows/$WORKFLOW/dispatches"

echo ""
echo "========================================"
echo "  SPA — Trigger GitHub Actions Workflow"
echo "========================================"
echo ""
echo "Workflow: $WORKFLOW"
echo "Repo:     $REPO"
echo "Branch:   $BRANCH"
echo ""
echo "Sending workflow_dispatch event..."
echo ""

RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.github+json" \
  -H "Content-Type: application/json" \
  -d "{\"ref\": \"$BRANCH\"}" \
  "$API_URL")

echo ""
if [[ "$RESPONSE" == "204" ]]; then
  echo "SUCCESS! (HTTP 204) Workflow triggered."
  echo ""
  echo "Monitor the run at:"
  echo "  https://github.com/$REPO/actions"
  echo ""
  echo "It may take 10-30 seconds to appear in the Actions tab."
elif [[ "$RESPONSE" == "404" ]]; then
  echo "FAILED (HTTP 404) — Workflow file not yet pushed to GitHub."
  echo ""
  echo "You need to run push_workflow.command first to upload the"
  echo "workflow file, then try triggering again."
  exit 1
elif [[ "$RESPONSE" == "422" ]]; then
  echo "FAILED (HTTP 422) — Workflow exists but dispatch is not enabled,"
  echo "or the branch '$BRANCH' does not exist."
  exit 1
else
  echo "FAILED (HTTP $RESPONSE)"
  echo ""
  echo "Possible causes:"
  echo "  • Token doesn't have 'workflow' or 'actions' scope"
  echo "  • Workflow file not yet on GitHub (run push_workflow.command first)"
  exit 1
fi

echo ""
read -rp "Press Enter to close..." _
