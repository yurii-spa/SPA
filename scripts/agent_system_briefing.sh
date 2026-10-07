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

# ── Memory index freshness (ADR-591 §A1) ─────────────────────────────────────
# This IS the mirror sync's existing 30-min tick — the least-invasive hook, chosen over a new
# agent because `ensure_fresh()` is cheap when nothing changed (a stat-only walk, no file reads)
# and the mirror above just moved the ONE thing the staleness check cares about (origin/main
# content). Measured 2026-10-05 pre-fix: the live prod index was 44h stale and nothing on the
# 30-min cadence ever looked at it. `SPA_MEMORY_ROOT_SPA` points the rebuild at the mirror (not
# the prod tree, which lags origin by design — ADR-152) so the index matches what a session
# actually reads. `|| true`: an index rebuild failure must never take the briefing down with it;
# `perl alarm 120` (macOS has no `timeout`): a hung rebuild cannot block the briefing agent either.
( cd /Users/yuriikulieshov/Documents/SPA_Claude \
  && SPA_MEMORY_ROOT_SPA="$_MIRROR" /usr/bin/perl -e 'alarm 120; exec @ARGV' \
       /Users/yuriikulieshov/miniconda3/bin/python3 -m spa_core.studio_os.memory ensure-fresh \
  ) >/tmp/spa_memory_ensure_fresh.log 2>&1 || true

# ── ARB continuity read model (ADR-610) ──────────────────────────────────────
# Rebuilds data/continuity/{CURRENT_STATE.md,ARCHITECT_DECISION_INDEX.md,state.json} from the mirror
# (canon) + the code-sync receipt + the published Mission Control bundle, on this same existing tick —
# no new agent or scheduler. A refusal (a canonical source missing, a metric-type crossing …) leaves the
# previous copy untouched and is visible in the log; `|| true` + `perl alarm 60` keep the briefing alive.
( cd /Users/yuriikulieshov/Documents/SPA_Claude \
  && SPA_MEMORY_ROOT_SPA="$_MIRROR" /usr/bin/perl -e 'alarm 60; exec @ARGV' \
       /Users/yuriikulieshov/miniconda3/bin/python3 -m spa_core.studio_os.memory continuity build \
  ) >/tmp/spa_continuity_build.log 2>&1 || true

exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh system_briefing /Users/yuriikulieshov/Documents/SPA_Claude/scripts/update_system_briefing.py
