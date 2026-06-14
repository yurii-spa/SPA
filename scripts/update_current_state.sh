#!/bin/bash
# update_current_state.sh — обновляет статус инфраструктуры в CURRENT_STATE.md
# Запускается из com.spa.uptime_monitor после записи uptime_status.json.
#
# Источник данных: data/uptime_status.json (atomic, поля: ts | all_ok | checks).
# Идемпотентно: если строка "Last uptime check:" уже есть — заменяет её,
# иначе вставляет сразу после заголовка раздела "## Инфраструктура (launchd)".
#
# Безопасно: при отсутствии/повреждении JSON ничего не ломает (no-op + ненулевой выход не критичен).

set -u

UPTIME="$HOME/Documents/SPA_Claude/data/uptime_status.json"
STATE="$HOME/Documents/SPA_Claude/CURRENT_STATE.md"

[ -f "$UPTIME" ] || { echo "update_current_state: $UPTIME не найден, skip"; exit 0; }
[ -f "$STATE" ]  || { echo "update_current_state: $STATE не найден, skip"; exit 0; }

# Читаем ts (epoch float) и all_ok. uptime_status.json использует ключ "ts".
# Форматируем ts в читаемый UTC ISO-таймстемп. Если ts нет — '?'.
TS=$(/usr/bin/python3 - "$UPTIME" <<'PY' 2>/dev/null
import json, sys, datetime
try:
    d = json.load(open(sys.argv[1]))
    t = d.get("ts")
    if t is None:
        print("?")
    else:
        print(datetime.datetime.utcfromtimestamp(float(t)).strftime("%Y-%m-%dT%H:%M:%SZ"))
except Exception:
    print("?")
PY
)

OK=$(/usr/bin/python3 - "$UPTIME" <<'PY' 2>/dev/null
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    print("✅" if d.get("all_ok") else "⚠️")
except Exception:
    print("⚠️")
PY
)

LINE="> Last uptime check: $TS ($OK)"

if grep -q "Last uptime check:" "$STATE" 2>/dev/null; then
    # Заменяем существующую строку (BSD sed на macOS требует пустой аргумент -i '')
    sed -i '' "s/^> Last uptime check:.*/$LINE/" "$STATE" 2>/dev/null \
        || sed -i '' "s/Last uptime check:.*/Last uptime check: $TS ($OK)/" "$STATE" 2>/dev/null \
        || true
else
    # Вставляем после заголовка раздела инфраструктуры (если он есть)
    if grep -q "^## Инфраструктура (launchd)" "$STATE" 2>/dev/null; then
        sed -i '' "/^## Инфраструктура (launchd)/a\\
$LINE
" "$STATE" 2>/dev/null || true
    fi
fi

echo "Updated CURRENT_STATE.md: $TS $OK"
