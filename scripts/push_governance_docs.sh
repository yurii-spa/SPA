#!/bin/bash
# Push Governance Documentation Package (docs/governance/)
# Created by Architect Audit session — separate script to avoid collision with push_v681.sh (RRR5)
COMMIT_MSG="docs(governance): governance package v1.1 — SPRINT_NAMING added, DEVELOPMENT_RULES updated (SECRETS POLICY + sprint naming ref), KANBAN sprint_naming_convention field"
FILES="docs/governance/DEVELOPMENT_RULES.md \
docs/governance/GIT_WORKFLOW.md \
docs/governance/AI_ASSISTANT_RULES.md \
docs/governance/ARCHITECTURE.md \
docs/governance/ANTI_PATTERNS.md \
docs/governance/KNOWN_ISSUES.md \
docs/governance/PROJECT_STATE.md \
docs/governance/AUDIT_REPORT.md \
docs/governance/SPRINT_NAMING.md \
KANBAN.json \
CURRENT_STATE.md"
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "❌ PAT не найден"; exit 1; }
echo "📦 Pushing Governance Documentation Package..."
cd "$(dirname "$0")/.." || exit 1
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "✅ Governance docs pushed"
