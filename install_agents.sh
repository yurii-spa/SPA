#!/bin/bash
# SPA Agent Topology — установка ВСЕХ launchd агентов.
# Запуск: bash scripts/install_agents.sh
# Безопасно: idempotent (unload перед load).
#
# Стратегия: авто-обнаружение. Скрипт устанавливает КАЖДЫЙ файл
# scripts/com.spa.*.plist, который физически существует. Так ни один
# новый агент не будет пропущен из-за забытой записи в хардкод-списке
# (история бага: fund-api / daily-paper-report / weekly_backup /
#  analytics_tier_c / checkpoint-7day не устанавливались).

PLIST_DIR="$(cd "$(dirname "$0")" && pwd)"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
PYTHON="/Users/yuriikulieshov/miniconda3/bin/python3"

# Проверяем python (большинство агентов запускают python-модули)
if [ ! -f "$PYTHON" ]; then
    echo "⚠️  WARN: python3 не найден по пути: $PYTHON"
    echo "    Python-агенты могут падать. Проверь путь miniconda."
else
    echo "✅ Python: $($PYTHON --version 2>&1)"
fi

mkdir -p "$LAUNCH_AGENTS"

echo ""
echo "=== SPA Agent Topology — Install (auto-discovery) ==="
echo "Plist dir:    $PLIST_DIR"
echo "LaunchAgents: $LAUNCH_AGENTS"
echo ""

# Собираем все plist-ы автоматически
shopt -s nullglob
PLISTS=("$PLIST_DIR"/com.spa.*.plist)
shopt -u nullglob

if [ ${#PLISTS[@]} -eq 0 ]; then
    echo "ERROR: не найдено ни одного com.spa.*.plist в $PLIST_DIR"
    exit 1
fi

echo "Найдено plist-файлов: ${#PLISTS[@]}"
echo ""

INSTALLED=0
SKIPPED=0
ERRORS=()

for PLIST_SRC in "${PLISTS[@]}"; do
    BASENAME="$(basename "$PLIST_SRC")"      # com.spa.X.plist
    AGENT="${BASENAME%.plist}"               # com.spa.X
    PLIST_DST="$LAUNCH_AGENTS/$BASENAME"

    # Защита: проверяем, что файл реально существует и читаем
    if [ ! -f "$PLIST_SRC" ]; then
        echo "⚠️  SKIP  $AGENT — файл исчез: $PLIST_SRC"
        SKIPPED=$((SKIPPED + 1))
        continue
    fi

    # Валидация синтаксиса перед установкой (не ставим битый plist)
    if command -v plutil >/dev/null 2>&1; then
        if ! plutil -lint "$PLIST_SRC" >/dev/null 2>&1; then
            echo "❌ FAIL  $AGENT — невалидный plist (plutil -lint)"
            ERRORS+=("$AGENT (lint)")
            continue
        fi
    fi

    # Копируем
    cp "$PLIST_SRC" "$PLIST_DST"

    # Unload (idempotent — если уже загружен)
    launchctl unload "$PLIST_DST" 2>/dev/null || true

    # Load
    if launchctl load "$PLIST_DST" 2>/dev/null; then
        echo "✅ LOADED $AGENT"
        INSTALLED=$((INSTALLED + 1))
    else
        echo "❌ FAIL  $AGENT — launchctl load вернул ошибку"
        ERRORS+=("$AGENT")
    fi
done

echo ""
echo "=== Результат ==="
echo "Всего plist:  ${#PLISTS[@]}"
echo "Установлено:  $INSTALLED"
echo "Пропущено:    $SKIPPED"
echo "Ошибок:       ${#ERRORS[@]}"
if [ ${#ERRORS[@]} -gt 0 ]; then
    echo "Ошибки в: ${ERRORS[*]}"
fi

echo ""
echo "=== Статус всех spa агентов (launchctl list) ==="
launchctl list | grep com.spa | sort || echo "(нет загруженных com.spa агентов)"

echo ""
echo "=== Логи (последние 3 строки каждого) ==="
for LOG in /tmp/spa_*.log; do
    [ -f "$LOG" ] && echo "--- $LOG ---" && tail -3 "$LOG" 2>/dev/null
done

echo ""
echo "Готово. Если агент в статусе с ненулевым exit-кодом — смотри"
echo "соответствующий /tmp/spa_<name>_err.log"
