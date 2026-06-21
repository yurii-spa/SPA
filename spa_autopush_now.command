#!/usr/bin/env bash
# spa_autopush_now.command — немедленный запуск smart_autopush (push v1205-v1208)
set -e
cd ~/Documents/SPA_Claude

echo "=== SPA Smart Autopush — Manual Trigger ==="
echo "$(date)"

PAT=$(security find-generic-password -s "GITHUB_PAT_SPA" -w 2>/dev/null || true)
if [ -z "$PAT" ]; then
  echo "❌ PAT не найден"
  read -rp "Press Enter..."
  exit 1
fi
echo "✅ PAT найден"

echo ""
echo "Pending scripts (version > last_version):"
python3 -c "
import json, re
from pathlib import Path
state = json.loads(Path('data/autopush_state.json').read_text())
last_v = state['last_version']
print(f'  last_version={last_v}')
pending = sorted(
    (int(m.group(1)), p.name)
    for p in Path('scripts').glob('push_v*.sh')
    if (m := re.fullmatch(r'push_v(\d+)\.sh', p.name)) and int(m.group(1)) > last_v
)
for v, name in pending:
    print(f'  → v{v}: {name}')
print(f'  Total pending: {len(pending)}')
"

echo ""
echo "Запускаю smart_autopush.py..."
python3 scripts/smart_autopush.py

echo ""
echo "=== Done ==="
read -rp "Press Enter to close..."
