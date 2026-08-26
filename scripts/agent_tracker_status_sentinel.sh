#!/bin/bash
# scripts/agent_tracker_status_sentinel.sh — launchd wrapper for com.spa.tracker_status_sentinel
#
# ADR-141 (решение владельца 2026-08-25, вариант 1): у сторожа переходов статусов
# появляется СВОЙ агент, раз в час. До этого его двигали только циклы оркестратора,
# когда до него доходили руки, — то есть сторож, ловящий аварию через сутки-двое.
# Переходы статусов происходят десятками в день; час — принятая цена запоздания.
#
# Канонический bash-wrapper (launchd НЕ умеет exec'ить miniconda-python напрямую,
# иначе exit 78). Лог: /tmp/spa_tracker_status_sentinel.log — в /tmp, не в ~/Documents
# (инвариант #12).
#
# Сторож ничего не чинит и капитал не двигает: он ЧИТАЕТ трекер и НАЗЫВАЕТ переходы,
# которые никто не объяснил. Коды возврата: 0 — OK · 1 — WARN · 2 — CRITICAL либо
# НЕ ИЗМЕРЕНО (fail-CLOSED; «не измерено» никогда не значит «в порядке»).
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh \
    tracker_status_sentinel spa_core.monitoring.tracker_status_sentinel
