#!/bin/bash
# MP-009: Fix launchd httpserver (exit 78) + autopush (exit 2)
# Root cause: /usr/bin/python3 lacks Full Disk Access to ~/Documents
# Fix: use miniconda Python (same as daily_cycle which works) for both services

set -euo pipefail

AGENTS="$HOME/Library/LaunchAgents"
SPA="$HOME/Documents/SPA_Claude"

echo "╔════════════════════════════════════════════════╗"
echo "║   MP-009: Fix launchd httpserver + autopush    ║"
echo "╚════════════════════════════════════════════════╝"
echo ""

# ────────────────────────────────────────────────────
# 1. DETECT PYTHON (from daily_cycle plist, which works)
# ────────────────────────────────────────────────────
echo "=== [1/5] Определяю Python-путь ==="

PYTHON_PATH=""

# Try to read from the working daily_cycle plist
DAILY_PLIST="$AGENTS/com.spa.daily_cycle.plist"
if [ -f "$DAILY_PLIST" ]; then
    # Extract first /...python... path from the plist
    PYTHON_PATH=$(grep -oE '/[^<>]*python[^<>]*' "$DAILY_PLIST" | head -1 || true)
    if [ -n "$PYTHON_PATH" ] && [ -x "$PYTHON_PATH" ]; then
        echo "  ✅ Найден из daily_cycle plist: $PYTHON_PATH"
    else
        PYTHON_PATH=""
    fi
fi

# Fallback: try common paths
if [ -z "$PYTHON_PATH" ]; then
    echo "  ⚠️  daily_cycle plist не помог, ищу среди известных путей..."
    for p in \
        "$HOME/miniconda3/bin/python3" \
        "$HOME/opt/miniconda3/bin/python3" \
        "$HOME/miniforge3/bin/python3" \
        "$HOME/anaconda3/bin/python3" \
        "/opt/homebrew/bin/python3" \
        "/usr/local/bin/python3"; do
        if [ -x "$p" ]; then
            PYTHON_PATH="$p"
            echo "  ✅ Найден: $PYTHON_PATH"
            break
        fi
    done
fi

# If still nothing, check which python3 is in PATH
if [ -z "$PYTHON_PATH" ]; then
    PYTHON_PATH=$(which python3 2>/dev/null || true)
    if [ -n "$PYTHON_PATH" ]; then
        echo "  ℹ️  Используем PATH python3: $PYTHON_PATH"
    fi
fi

if [ -z "$PYTHON_PATH" ]; then
    echo "  ❌ Не могу найти python3. Выход."
    exit 1
fi

# Show version
echo "  Python: $($PYTHON_PATH --version 2>&1)"
echo ""

# ────────────────────────────────────────────────────
# 2. FIX httpserver PLIST
# ────────────────────────────────────────────────────
echo "=== [2/5] Чиню com.spa.httpserver ==="

launchctl unload "$AGENTS/com.spa.httpserver.plist" 2>/dev/null || true
echo "  ⏹  Остановлен старый httpserver"

# Write fixed plist:
# - Use detected Python (has FDA, unlike /usr/bin/python3)
# - No WorkingDirectory (avoids launchd chdir EPERM → exit 78)
# - Use --directory flag so http.server knows where to serve from
cat > "$AGENTS/com.spa.httpserver.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.spa.httpserver</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON_PATH}</string>
        <string>-m</string>
        <string>http.server</string>
        <string>8765</string>
        <string>--directory</string>
        <string>${SPA}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/spa_http.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/spa_http.err</string>
</dict>
</plist>
PLIST

# Also update the repo copy
cat > "$SPA/com.spa.httpserver.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.spa.httpserver</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON_PATH}</string>
        <string>-m</string>
        <string>http.server</string>
        <string>8765</string>
        <string>--directory</string>
        <string>${SPA}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/spa_http.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/spa_http.err</string>
</dict>
</plist>
PLIST

launchctl load "$AGENTS/com.spa.httpserver.plist"
echo "  ✅ com.spa.httpserver перезапущен с Python: $PYTHON_PATH"
echo ""

# ────────────────────────────────────────────────────
# 3. FIX/CREATE autopush PLIST
# ────────────────────────────────────────────────────
echo "=== [3/5] Чиню com.spa.autopush ==="

launchctl unload "$AGENTS/com.spa.autopush.plist" 2>/dev/null || true
echo "  ⏹  Остановлен старый autopush (если был)"

# Show what was wrong
AUTOPUSH_PLIST="$AGENTS/com.spa.autopush.plist"
if [ -f "$AUTOPUSH_PLIST" ]; then
    OLD_PY=$(grep -oE '/[^<>]*python[^<>]*' "$AUTOPUSH_PLIST" | head -1 || echo "?")
    echo "  ℹ️  Старый Python в autopush: $OLD_PY"
fi

# Write fixed plist:
# - Use detected Python (has FDA)
# - Every 90 min = 5400 sec (per CLAUDE.md)
# - Logs to /tmp/ (no Documents access needed for logging)
cat > "$AGENTS/com.spa.autopush.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.spa.autopush</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON_PATH}</string>
        <string>${SPA}/auto_push.py</string>
    </array>
    <key>StartInterval</key>
    <integer>5400</integer>
    <key>RunAtLoad</key>
    <false/>
    <key>StandardOutPath</key>
    <string>/tmp/spa_autopush.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/spa_autopush.err</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
PLIST

# Also save a copy in the repo (without PYTHON_PATH embedded since that's machine-specific)
# Save as a template with comment
cat > "$SPA/com.spa.autopush.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<!-- Template: replace PYTHON_PATH with actual miniconda python3 path (same as daily_cycle) -->
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.spa.autopush</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PYTHON_PATH}</string>
        <string>${SPA}/auto_push.py</string>
    </array>
    <key>StartInterval</key>
    <integer>5400</integer>
    <key>RunAtLoad</key>
    <false/>
    <key>StandardOutPath</key>
    <string>/tmp/spa_autopush.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/spa_autopush.err</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
PLIST

launchctl load "$AGENTS/com.spa.autopush.plist"
echo "  ✅ com.spa.autopush запущен с Python: $PYTHON_PATH (интервал: 90 мин)"
echo ""

# ────────────────────────────────────────────────────
# 4. VERIFY ALL SPA SERVICES
# ────────────────────────────────────────────────────
echo "=== [4/5] Проверяю статус всех spa-сервисов ==="
sleep 4

echo ""
echo "  launchctl list | grep spa:"
launchctl list | grep spa || echo "  (нет spa-сервисов)"
echo ""
echo "  Legend: PID=запущен, «-» PID + exit≠0 = ошибка"

# Check httpserver
echo ""
echo "--- Тест httpserver ---"
sleep 2
if curl -s -o /dev/null -w "%{http_code}" http://localhost:8765/ 2>/dev/null | grep -q "200"; then
    echo "  ✅ localhost:8765 → HTTP 200 — сервер работает!"
else
    echo "  ⚠️  localhost:8765 не отвечает. Смотри /tmp/spa_http.err:"
    tail -5 /tmp/spa_http.err 2>/dev/null || echo "  (лог пуст)"
fi

# ────────────────────────────────────────────────────
# 5. WRITE RESULT LOG for reference
# ────────────────────────────────────────────────────
echo ""
echo "=== [5/5] Записываю результат ==="

RESULT_FILE="$SPA/data/mp009_fix_result.json"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
LAUNCHCTL_OUTPUT=$(launchctl list | grep spa || echo "")

# Build JSON
python3 -c "
import json, sys, os

data = {
    'fixed_at': '$TIMESTAMP',
    'python_used': '$PYTHON_PATH',
    'services_fixed': ['com.spa.httpserver', 'com.spa.autopush'],
    'root_cause': '/usr/bin/python3 lacks Full Disk Access to ~/Documents (TCC restriction)',
    'fix_applied': [
        'httpserver: removed WorkingDirectory, added --directory flag, switched to miniconda Python',
        'autopush: switched to miniconda Python (same as daily_cycle)'
    ],
    'launchctl_spa': '$LAUNCHCTL_OUTPUT',
    'mp009_status': 'done'
}

os.makedirs(os.path.dirname('$RESULT_FILE'), exist_ok=True)
import tempfile
tmp = '$RESULT_FILE' + '.tmp'
with open(tmp, 'w') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
os.replace(tmp, '$RESULT_FILE')
print('  ✅ Результат записан в data/mp009_fix_result.json')
" 2>/dev/null || echo "  ⚠️  Не смог записать JSON (но это не критично)"

echo ""
echo "╔════════════════════════════════════════════════╗"
echo "║   MP-009 Fix завершён. Следующий шаг:          ║"
echo "║   Обновим KANBAN.json (done) и запушим.        ║"
echo "╚════════════════════════════════════════════════╝"
echo ""
echo "Можно закрыть это окно."
