#!/usr/bin/env bash
# run_autopush_now.command — запускает smart_autopush.py немедленно
set -e
cd ~/Documents/SPA_Claude

echo "=== SPA Autopush Manual Run ==="
echo "$(date)"
echo ""

# Проверяем PAT
PAT=$(security find-generic-password -s "GITHUB_PAT_SPA" -w 2>/dev/null || true)
if [ -z "$PAT" ]; then
  echo "❌ PAT не найден в Keychain"
  read -rp "Press Enter..."
  exit 1
fi
echo "✅ PAT найден"
unset PAT

# Показываем что будет пушиться
echo ""
echo "Pending push scripts:"
python3 -c "
import json, re, pathlib
state = json.load(open('data/autopush_state.json'))
last = state.get('last_version', 0)
scripts = []
for p in sorted(pathlib.Path('scripts').glob('push_v*.sh')):
    m = re.fullmatch(r'push_v(\d+)\.sh', p.name)
    if m and int(m.group(1)) > last:
        scripts.append((int(m.group(1)), p.name))
scripts.sort()
print(f'last_version={last}, pending={len(scripts)}')
for v, n in scripts:
    print(f'  v{v}: {n}')
" 2>/dev/null || echo "(ошибка проверки)"

echo ""
echo "Запускаем autopush..."
/Users/yuriikulieshov/miniconda3/bin/python3 \
  /Users/yuriikulieshov/Documents/SPA_Claude/scripts/smart_autopush.py

echo ""
echo "=== Готово ==="
cat data/autopush_state.json 2>/dev/null | python3 -m json.tool 2>/dev/null || true

read -rp "Press Enter to close..."
