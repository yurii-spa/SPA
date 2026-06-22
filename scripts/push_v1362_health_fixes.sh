#!/usr/bin/env bash
# push_v1362_health_fixes.sh — Пуш фиксов v1362 в GitHub
#
# Что пушит:
#   1. spa_core/monitoring/system_health_monitor.py  (Bug 1: LOCAL_API /health)
#   2. data/adapter_status.json                      (Bug 2: sky_susds APY 4.75)
#   3. data/adapter_registry.json                    (Bug 2: fallback_apy 0.0475)
#   4. scripts/install_all_agents.sh                 (Bug 3: полный список агентов)
#
# Использование:
#   bash scripts/push_v1362_health_fixes.sh
#   bash scripts/push_v1362_health_fixes.sh --dry-run
#
# PAT читается из Keychain: security find-generic-password -s GITHUB_PAT_SPA -w
# СЕКРЕТЫ В ФАЙЛАХ ЗАПРЕЩЕНЫ (инцидент 2026-06-10).

set -euo pipefail

REPO="/Users/yuriikulieshov/Documents/SPA_Claude"
DRY_RUN=0

# Парсинг --dry-run
for arg in "$@"; do
    if [[ "$arg" == "--dry-run" ]]; then
        DRY_RUN=1
    fi
done

echo "=== Push v1362: health fixes ==="
[[ "$DRY_RUN" == "1" ]] && echo "(DRY-RUN MODE — пуш не выполняется)" || true
echo ""

# ---------------------------------------------------------------------------
# Синтаксис-проверка Python файлов
# ---------------------------------------------------------------------------
PYTHON="/Users/yuriikulieshov/miniconda3/bin/python3"

echo "--- py_compile проверки ---"
for pyfile in \
    "$REPO/spa_core/monitoring/system_health_monitor.py"; do
    if "$PYTHON" -m py_compile "$pyfile" 2>&1; then
        echo "  [OK] $pyfile"
    else
        echo "  [FAIL] $pyfile — синтаксическая ошибка, пуш отменён"
        exit 1
    fi
done

# ---------------------------------------------------------------------------
# JSON-валидация
# ---------------------------------------------------------------------------
echo ""
echo "--- JSON валидация ---"
for jsonfile in \
    "$REPO/data/adapter_status.json" \
    "$REPO/data/adapter_registry.json"; do
    if "$PYTHON" -c "import json, sys; json.load(open('$jsonfile'))" 2>&1; then
        echo "  [OK] $jsonfile"
    else
        echo "  [FAIL] $jsonfile — невалидный JSON, пуш отменён"
        exit 1
    fi
done

# ---------------------------------------------------------------------------
# Bash синтаксис-проверка
# ---------------------------------------------------------------------------
echo ""
echo "--- bash -n проверка shell-скриптов ---"
for shfile in \
    "$REPO/scripts/install_all_agents.sh" \
    "$REPO/scripts/push_v1362_health_fixes.sh"; do
    if bash -n "$shfile" 2>&1; then
        echo "  [OK] $shfile"
    else
        echo "  [FAIL] $shfile — синтаксическая ошибка shell, пуш отменён"
        exit 1
    fi
done

if [[ "$DRY_RUN" == "1" ]]; then
    echo ""
    echo "DRY-RUN завершён. Все проверки пройдены."
    echo "Запусти без --dry-run для реального пуша."
    exit 0
fi

# ---------------------------------------------------------------------------
# Push
# ---------------------------------------------------------------------------
echo ""
echo "--- Пуш файлов в GitHub ---"
cd "$REPO"

"$PYTHON" push_to_github.py \
    --files \
        "/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/monitoring/system_health_monitor.py" \
        "/Users/yuriikulieshov/Documents/SPA_Claude/data/adapter_status.json" \
        "/Users/yuriikulieshov/Documents/SPA_Claude/data/adapter_registry.json" \
        "/Users/yuriikulieshov/Documents/SPA_Claude/scripts/install_all_agents.sh" \
    --message "v1362: 3 bug fixes — health check URL /health, sky_susds APY 4.75%, install_all_agents full list"

echo ""
echo "=== Push v1362 завершён ==="
