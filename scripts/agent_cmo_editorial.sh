#!/bin/bash
# scripts/agent_cmo_editorial.sh — launchd wrapper for com.spa.cmo_editorial
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern; launchd cannot exec
# miniconda-python directly → exit 78, so we go through /bin/bash + agent_template.sh).
#
# CMO editorial DRAFT agent (AAA product-layer, docs/CMO_EDITORIAL_LAYER.md): turns the dry
# auto-changelog facts into "richer than dry" copy, validates it through the deterministic
# HONESTY-GATE, and stores a DRAFT (data/cmo_drafts/<date>.json, status "draft"). It NEVER
# publishes — flow B (owner approves → publish) is a later step.
# ADVISORY / draft-only — moves NO capital, writes NO runtime state, never touches the site or
# the go-live track. Fail-CLOSED (no source data → no draft).
# Log: /tmp/spa_cmo_editorial.log
export AGENT_NAME="cmo_editorial"
export MODULE="spa_core.cmo.editorial_agent"
/bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh
