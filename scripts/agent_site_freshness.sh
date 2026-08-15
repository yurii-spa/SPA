#!/bin/bash
# scripts/agent_site_freshness.sh — launchd wrapper for com.spa.site_freshness
#
# Решение владельца 2026-08-14T12:26:56Z, вариант 1 (карточка
# `owner-decision-stranitsa-treka-chetvertyi-den-pryachet`): дать снятие таблички
# честности Маку.
#
# ПОЧЕМУ АГЕНТ ВООБЩЕ НУЖЕН. Site Custodian (ADR-YL-011) умеет обе стороны правила
# честности — ПОВЕСИТЬ табличку «живые данные временно недоступны» и СНЯТЬ её, — но
# жил он только в GitHub Actions. Снятие оттуда невозможно НЕ ПО ПОЛОМКЕ, А ПО
# ПОСТРОЕНИЮ: обе стороны доставляются пушером, а `push_to_github.repo_relative_path`
# по контракту (fail-CLOSED) берёт файл только из живого дерева Мака или его worktree —
# в раннере путь `/home/runner/work/SPA/SPA`, и отказ гарантирован при любой погоде.
# Итог, замеренный 14.08: работала ровно ПОЛОВИНА защиты. Табличка провисела на
# /track-record/ четвёртый день, снять её было некому и неоткуда.
#
# Здесь дерево есть, поэтому обе стороны доезжают. Облачный прогон
# (`.github/workflows/site_freshness.yml`) НЕ снимается — он остаётся вторым,
# независимым глазом: если Мак спит или сеть у него легла, красный job виден.
#
# КОД ВОЗВРАТА НЕ ГАСИМ (`--exit-zero` здесь запрещён и закреплён тестом). Тревога
# владельцу для направления «не уехало СНЯТИЕ» запрещена осознанно (ADR-084: гасится
# МАРШРУТ, не проверка), и после этого у недоставки остался ровно один канал —
# ненулевой код возврата. Обернуть его в ноль значит вернуть ту самую аварию, где
# «снять табличку отсюда нечем» выглядело как чистый прогон.
#
# Канонический bash-wrapper (launchd не может exec'нуть miniconda-python напрямую,
# exit 78). Лог: /tmp/spa_site_freshness.log
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh \
    site_freshness \
    /Users/yuriikulieshov/Documents/SPA_Claude/scripts/site_freshness_monitor.py
