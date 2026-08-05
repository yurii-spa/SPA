#!/bin/bash
# scripts/agent_architecture_conformance.sh — launchd wrapper for
# com.spa.architecture_conformance (ADR-066, Фаза 1).
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this
# bash wrapper runs it correctly. Log: /tmp/spa_architecture_conformance.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
#
# --exit-zero-on-findings: расхождение флота с манифестом — СОДЕРЖАНИЕ отчёта, а не
# сбой процесса. Иначе агент вечно висел бы в agent_health как last_exit=2, и настоящая
# поломка сторожа стала бы неотличима от честной находки. Вердикт живёт в
# data/architecture_conformance.json и уходит владельцу через push_policy.
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh \
    architecture_conformance spa_core.monitoring.architecture_conformance \
    --alert --exit-zero-on-findings
