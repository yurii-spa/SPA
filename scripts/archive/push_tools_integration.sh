#!/bin/bash
# push_tools_integration.sh — пуш интеграции инструментов (markitdown, Graphify, фазы)
set -euo pipefail
cd ~/Documents/SPA_Claude

PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || true)
PAT=${PAT:-${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}}
if [ -z "$PAT" ] && [ -f ~/.github_pat ]; then PAT=$(cat ~/.github_pat); fi
if [ -z "$PAT" ]; then echo "❌ PAT не найден"; exit 1; fi

python3 scripts/push_to_github.py \
  --pat "$PAT" \
  --repo "yurii-spa/SPA" \
  --branch "main" \
  --message "feat(tools): markitdown pipeline + Graphify setup (from real README)

1. scripts/convert_analyst_sources.py — PDF/DOCX/XLSX/YouTube → Markdown
   Output: docs/analyst_sources/. Usage: python3 scripts/convert_analyst_sources.py file.pdf
   Requires: pip install markitdown[all]

2. .graphify.yml — NOTE: Graphify has no config file. This file explains the actual
   setup: Claude Code skill, invoked via /graphify inside Claude Code sessions.
   Install: pip install graphifyy && graphify install

3. docs/GRAPHIFY_GUIDE.md — rewritten from real README (safishamsi/graphify).
   Real commands: /graphify . --mode deep, /graphify query '...', /graphify path 'A' 'B'
   Output goes to graphify-out/ (graph.html, graph.json, GRAPH_REPORT.md)

Source: https://github.com/safishamsi/graphify (real README verified)" \
  --files \
    "scripts/convert_analyst_sources.py" \
    "docs/analyst_sources/README.md" \
    "docs/GRAPHIFY_GUIDE.md" \
    ".graphify.yml"

echo "✅ SPA_Claude push готов"

echo ""
echo "── SPA_Dev phase docs нужно пушить отдельно из SPA_Dev репо ──"
echo "Эти файлы только локально:"
echo "  ~/Documents/SPA_Dev/phases/PHASE_paper_test.md"
echo "  ~/Documents/SPA_Dev/phases/PHASE_research_strategies.md"
echo "  ~/Documents/SPA_Dev/phases/PHASE_evidence_pipeline.md"
echo "  ~/Documents/SPA_Dev/phases/PHASE_investor_reports.md"
