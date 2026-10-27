#!/bin/bash
# scripts/agent_mission_control.sh — launchd wrapper for com.spa.mission_control (ADR-552).
#
# One finishing step, every 5 minutes: spa_core.studio_os.mission_build writes a NEW bundle
# (mission.json + a copy of mission_ui/) and moves the current.json pointer to it. On failure
# it exits 2 and leaves the previous bundle/pointer untouched (fail-CLOSED) — this wrapper does
# not retry or mask that; agent_template.sh propagates the exit code to launchd unchanged.
#
# Canonical bash wrapper (launchd cannot exec miniconda python directly → exit 78); logs in /tmp.
# ARB 26.10 task-prep display (scoped to this agent only; remove both lines to switch off)
export SPA_TASK_PREP_ROOT="$HOME/studio-os-serve/task_prep"
export SPA_TASK_PREP_CODE_ROOT="$HOME/studio-os-serve/task_prep_root"
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh \
    mission_control spa_core.studio_os.mission_build
