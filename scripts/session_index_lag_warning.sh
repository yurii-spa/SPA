#!/bin/bash
# scripts/session_index_lag_warning.sh — SessionStart-хук (ADR-152).
#
# Сессия обязана узнать о своей слепоте ДО того, как начнёт рассуждать по устаревшим
# документам. Замерено 27.08: сессия честно доложила владельцу «последний ADR — 078»,
# тогда как на origin их 129 — включая ADR-125 о старте трёх пакетов, о котором владелец
# и спрашивал. Сессия не проглядела: у неё физически не было файла.
#
# Отставание индекса — ШТАТНО (пуши идут в origin через API, минуя локальный индекс),
# поэтому текст не тревога, а указатель: читай ADR/STATE/карточки из зеркала.
#
# Хук НИКОГДА не должен мешать старту сессии: любая ошибка гасится, выход всегда 0.
ROOT=/Users/yuriikulieshov/Documents/SPA_Claude
MIRROR=/Users/yuriikulieshov/Documents/SPA_mirror

{
    cd "$ROOT" 2>/dev/null || exit 0
    git fetch --quiet origin main 2>/dev/null
    BEHIND=$(git rev-list --count HEAD..origin/main 2>/dev/null)

    if [ -z "$BEHIND" ]; then
        echo "⚠️  Отставание git-индекса НЕ ИЗМЕРЕНО (git недоступен). Считай docs/ возможно устаревшими."
    elif [ "$BEHIND" -gt 0 ]; then
        echo "⚠️  Локальный git-индекс отстаёт от origin/main на $BEHIND коммит(ов) — это ШТАТНО."
        if [ -d "$MIRROR/.git" ]; then
            echo "    ADR / STATE / карточки читай из зеркала: $MIRROR"
        else
            echo "    Зеркала $MIRROR НЕТ — сверяться не с чем, docs/ могут быть устаревшими."
        fi
        echo "    Рабочее дерево НЕ синхронизировать: docs/ и nimbalyst-local/ пишутся локально."
    fi
} 2>/dev/null

exit 0
