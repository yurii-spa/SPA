#!/bin/bash
# scripts/agent_redteam_rotation.sh - launchd wrapper for com.spa.redteam_rotation
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this bash
# wrapper runs it correctly. Log: /tmp/spa_redteam_rotation.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
#
# Runs the rotating red-team: a DIFFERENT attack surface is probed each UTC day
# (deterministic rotation), the verdict is hash-anchored, and data/redteam_status
# .json is written atomically. Read-only against live data/ (scenarios mutate only
# their own tmp sandboxes; the runner snapshots live files before/after and FAILS
# CLOSED if any changed). Exit 0 = every forgery on today's surface was caught.
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh redteam_rotation spa_core.redteam.rotation
