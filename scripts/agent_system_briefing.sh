#!/bin/bash
# scripts/agent_system_briefing.sh - launchd wrapper for com.spa.system_briefing
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this
# bash wrapper runs it correctly. Log: /tmp/spa_system_briefing.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
# ── Зеркало origin для чтения (ADR-152, дизайн владельца 27.08) ──────────────
# Локальные сессии рассуждали по УСТАРЕВШИМ docs/: рабочее дерево на Маке отстаёт от
# origin на 1139 коммитов, и это ШТАТНО — пуши уходят в origin напрямую через API и
# локального индекса не касаются, а синхронизация возит только spa_core/scripts/tests/
# architecture. `docs/` и `nimbalyst-local/` не синхронизируются НИКОГДА и не должны:
# они пишутся локально, и любой merge затёр бы незапушенное.
#
# Замерено 27.08: сессия честно доложила «последний ADR — 078», тогда как на origin их
# 129, включая ADR-125 о старте трёх пакетов. Сессия не проглядела — у неё физически
# не было файла.
#
# Лечение — ОТДЕЛЬНОЕ read-only зеркало, а не синхронизация рабочего дерева. Шаг живёт
# в СУЩЕСТВУЮЩЕМ получасовом агенте: плодить флот ради git fetch не нужно.
# Отказ зеркала НЕ должен ронять брифинг — отсюда `|| true`.
_MIRROR=/Users/yuriikulieshov/Documents/SPA_mirror
if [ -d "$_MIRROR/.git" ]; then
    ( cd "$_MIRROR" \
      && git fetch --quiet origin main \
      && git reset --quiet --hard origin/main ) >/dev/null 2>&1 || true
fi

exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh system_briefing /Users/yuriikulieshov/Documents/SPA_Claude/scripts/update_system_briefing.py
