#!/bin/bash
# scripts/agent_apiserver.sh - launchd wrapper for com.spa.apiserver
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this
# bash wrapper runs it correctly. Log: /tmp/spa_apiserver.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
# Academy onboarding sub-app (mounted at /academy in server.py) reads its SQLite path from
# SPA_ACADEMY_DB. Without it, create_academy_app() raises and the mount is skipped (fail-safe). Export
# it here so a plain kickstart brings the academy backend up alongside the main API.
export SPA_ACADEMY_DB="/Users/yuriikulieshov/Documents/SPA_Claude/data/academy.db"
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh apiserver uvicorn spa_core.api.server:app --host 127.0.0.1 --port 8765 --log-level warning
