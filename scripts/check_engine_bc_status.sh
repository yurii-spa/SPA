#!/usr/bin/env bash
# check_engine_bc_status.sh — EPIC-8: быстрая проверка статуса Engine B и C
#
# Выводит:
#   - launchctl статус агентов (PID, LastExit)
#   - последнюю строку лога каждого цикла
#   - paper trading state из data/ (equity, дни, режим/IL)
#
# Запуск: bash ~/Documents/SPA_Claude/scripts/check_engine_bc_status.sh

REPO="$HOME/Documents/SPA_Claude"

echo "=== Engine B (HY/Carry) — com.spa.hy_cycle ==="
launchctl list com.spa.hy_cycle 2>/dev/null | grep -E "Label|PID|LastExit" || echo "  NOT LOADED"
echo "  Лог (последняя строка):"
tail -1 "$REPO/logs/hy_cycle.log" 2>/dev/null && true || echo "    (лог пуст или не существует)"
echo "  Ошибки (последняя строка):"
tail -1 "$REPO/logs/hy_cycle_error.log" 2>/dev/null && true || echo "    (нет ошибок или файл не существует)"
echo ""

echo "=== Engine C (LP/Liquidity) — com.spa.lp_cycle ==="
launchctl list com.spa.lp_cycle 2>/dev/null | grep -E "Label|PID|LastExit" || echo "  NOT LOADED"
echo "  Лог (последняя строка):"
tail -1 "$REPO/logs/lp_cycle.log" 2>/dev/null && true || echo "    (лог пуст или не существует)"
echo "  Ошибки (последняя строка):"
tail -1 "$REPO/logs/lp_cycle_error.log" 2>/dev/null && true || echo "    (нет ошибок или файл не существует)"
echo ""

echo "=== HY paper trading state (data/hy_paper_trading.json) ==="
python3 -c "
import json, sys
from pathlib import Path
f = Path('$REPO/data/hy_paper_trading.json')
if not f.exists():
    print('  (файл не существует — цикл ещё не запускался)')
    sys.exit(0)
try:
    d = json.loads(f.read_text())
    equity = d.get('equity', 0.0)
    peak   = d.get('peak_equity', 0.0)
    dd     = d.get('drawdown_pct', 0.0)
    days   = len(d.get('daily_history', []))
    regime = d.get('regime', 'UNKNOWN')
    cycles = d.get('cycles_completed', 0)
    last   = d.get('last_cycle_at', 'never')
    print(f'  equity=\${equity:,.2f}  peak=\${peak:,.2f}  drawdown={dd:.2%}')
    print(f'  days={days}  regime={regime}  cycles={cycles}  last_cycle={last}')
except Exception as e:
    print(f'  ERROR: {e}')
" 2>/dev/null || echo "  python3 не найден или ошибка"
echo ""

echo "=== LP paper trading state (data/lp_paper_trading.json) ==="
python3 -c "
import json, sys
from pathlib import Path
f = Path('$REPO/data/lp_paper_trading.json')
if not f.exists():
    print('  (файл не существует — цикл ещё не запускался)')
    sys.exit(0)
try:
    d = json.loads(f.read_text())
    equity  = d.get('equity', 0.0)
    il_dd   = d.get('il_drawdown_pct', 0.0)
    days    = len(d.get('daily_history', []))
    cycles  = d.get('cycles_completed', 0)
    last    = d.get('last_cycle_at', 'never')
    pos_cnt = len(d.get('positions', []))
    print(f'  equity=\${equity:,.2f}  il_drawdown={il_dd:.2%}  positions={pos_cnt}')
    print(f'  days={days}  cycles={cycles}  last_cycle={last}')
except Exception as e:
    print(f'  ERROR: {e}')
" 2>/dev/null || echo "  python3 не найден или ошибка"
echo ""

echo "=== GoLive дни трека Engine B+C ==="
python3 -c "
import json
from pathlib import Path
for name, fname in [('HY (Engine B)', 'hy_paper_trading.json'), ('LP (Engine C)', 'lp_paper_trading.json')]:
    f = Path('$REPO/data') / fname
    if not f.exists():
        print(f'  {name}: нет данных (0/14 дней)')
        continue
    d = json.loads(f.read_text())
    days = len(d.get('daily_history', []))
    need = 14
    status = 'PASS' if days >= need else f'NEED {need - days} more days'
    print(f'  {name}: {days}/{need} дней — {status}')
" 2>/dev/null || echo "  python3 не найден"
