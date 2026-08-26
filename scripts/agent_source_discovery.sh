#!/bin/bash
# scripts/agent_source_discovery.sh — launchd wrapper for com.spa.source_discovery
#
# ADR-142 (решение владельца 2026-08-25, вариант A): поиск новых источников
# доходности встаёт на расписание — раз в неделю — и у его результата появляется
# НАСТОЯЩИЙ читатель (раздел «Кандидаты в источники доходности» в SYSTEM_BRIEFING).
# До этого инструмент был рабочим и покрыт 30 тестами, но запускать его было
# некому, а `data/source_discovery.json` не читал НИКТО.
#
# Канонический bash-wrapper (launchd не умеет exec'ить miniconda-python напрямую,
# иначе exit 78). Лог: /tmp/spa_source_discovery.log — в /tmp, не в ~/Documents.
#
# Инструмент advisory: он НАХОДИТ кандидатов и складывает их в файл. Адаптером
# кандидат не становится сам — это список для человека.
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh \
    source_discovery \
    /Users/yuriikulieshov/Documents/SPA_Claude/scripts/find_defillama_sources.py \
    --save
