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
# Корень репозитория в PYTHONPATH. Без него find_defillama_sources.py падает на
# `import spa_core` (ModuleNotFoundError), и гейт отказывает в установке — замерено 27.08.
# Шаблон запускает СКРИПТ ПО ПУТИ, а не модуль через -m, поэтому рабочий каталог сам по
# себе пакет не находит.
#
# Правка обязана жить НА ORIGIN: локальную копию синхронизация затирает перед запуском
# агентов (проверено в тот же день — правка исчезла за минуты).
export PYTHONPATH="/Users/yuriikulieshov/Documents/SPA_Claude${PYTHONPATH:+:$PYTHONPATH}"

exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh \
    source_discovery \
    /Users/yuriikulieshov/Documents/SPA_Claude/scripts/find_defillama_sources.py \
    --save
