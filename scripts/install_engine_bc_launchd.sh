#!/usr/bin/env bash
# install_engine_bc_launchd.sh — EPIC-8: установка LaunchAgent для Engine B (HY) и Engine C (LP)
#
# Что делает:
#   1. Копирует плисты из launchd/ → ~/Library/LaunchAgents/
#   2. Выгружает старый агент если был загружен (игнорируем ошибку)
#   3. Загружает новый агент
#   4. Выводит статус (PID + LastExit)
#
# Запуск:
#   bash ~/Documents/SPA_Claude/scripts/install_engine_bc_launchd.sh
#
# Проверить после установки:
#   bash ~/Documents/SPA_Claude/scripts/check_engine_bc_status.sh

set -euo pipefail

REPO="$HOME/Documents/SPA_Claude"
LAUNCHD_DIR="$HOME/Library/LaunchAgents"
LOG="$REPO/logs/agent_install_$(date +%Y%m%d_%H%M%S).log"

mkdir -p "$REPO/logs"

echo "=== EPIC-8: install Engine B+C LaunchAgents ===" | tee "$LOG"
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$LOG"
echo "" | tee -a "$LOG"

for LABEL in com.spa.hy_cycle com.spa.lp_cycle; do
    SRC="$REPO/launchd/$LABEL.plist"
    DST="$LAUNCHD_DIR/$LABEL.plist"

    echo "--- $LABEL ---" | tee -a "$LOG"

    # Проверяем что исходный plist существует
    if [[ ! -f "$SRC" ]]; then
        echo "ERROR: plist не найден: $SRC" | tee -a "$LOG"
        exit 1
    fi

    # Валидируем XML (plutil доступен на macOS)
    if command -v plutil &>/dev/null; then
        plutil -lint "$SRC" 2>&1 | tee -a "$LOG"
    else
        echo "plutil не найден — пропускаем lint" | tee -a "$LOG"
    fi

    echo "Копируем: $SRC → $DST" | tee -a "$LOG"
    cp "$SRC" "$DST"

    # Выгружаем если был загружен (ошибка нормальна при первой установке)
    echo "Выгружаем старый агент (если был)..." | tee -a "$LOG"
    launchctl unload "$DST" 2>/dev/null || true

    # Загружаем
    echo "Загружаем агент..." | tee -a "$LOG"
    launchctl load "$DST"

    # Статус
    echo "Статус $LABEL:" | tee -a "$LOG"
    launchctl list "$LABEL" 2>/dev/null | grep -E "Label|PID|LastExit" | tee -a "$LOG" || echo "  NOT LOADED (возможно нет прав или macOS 13+: используй launchctl bootstrap)" | tee -a "$LOG"
    echo "" | tee -a "$LOG"
done

echo "=== Engine B+C LaunchAgents установлены ===" | tee -a "$LOG"
echo "" | tee -a "$LOG"
echo "Логи циклов:" | tee -a "$LOG"
echo "  $REPO/logs/hy_cycle.log" | tee -a "$LOG"
echo "  $REPO/logs/hy_cycle_error.log" | tee -a "$LOG"
echo "  $REPO/logs/lp_cycle.log" | tee -a "$LOG"
echo "  $REPO/logs/lp_cycle_error.log" | tee -a "$LOG"
echo "" | tee -a "$LOG"
echo "Лог установки: $LOG" | tee -a "$LOG"
echo "" | tee -a "$LOG"
echo "Проверить статус:" | tee -a "$LOG"
echo "  bash $REPO/scripts/check_engine_bc_status.sh" | tee -a "$LOG"
