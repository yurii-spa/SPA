#!/usr/bin/env bash
# setup_pat.sh — сохраняет новый GitHub PAT в macOS Keychain
#
# Использование:
#   bash setup_pat.sh ghp_YOUR_NEW_TOKEN
#
# Или без аргумента — введи токен интерактивно (не попадёт в историю shell):
#   bash setup_pat.sh
#
# После сохранения скрипт push_to_github.py будет читать PAT автоматически
# через: security find-generic-password -s GITHUB_PAT_SPA -w

set -e

PAT="$1"

# Если аргумент не передан — спросить интерактивно (не попадёт в history)
if [ -z "$PAT" ]; then
  echo "Введи новый GitHub PAT (ввод скрыт):"
  read -rs PAT
  echo ""
fi

if [ -z "$PAT" ]; then
  echo "❌ PAT не введён. Отмена."
  exit 1
fi

# Валидация формата (классические PAT начинаются с ghp_, fine-grained с github_pat_)
if [[ ! "$PAT" =~ ^(ghp_|github_pat_)[A-Za-z0-9_]{10,}$ ]]; then
  echo "❌ Неверный формат PAT (ожидается ghp_... или github_pat_...)"
  exit 1
fi

# Сохраняем в Keychain с account=$USER (нужно для -a "$USER" в push-скриптах)
# Сначала удаляем старые записи с аккаунтом "spa" если они есть
security delete-generic-password -s "GITHUB_PAT_SPA" -a "spa" 2>/dev/null || true

security add-generic-password \
  -s "GITHUB_PAT_SPA" \
  -a "$USER" \
  -w "$PAT" \
  -U

echo ""
echo "✅ PAT сохранён в macOS Keychain"
echo "   Сервис: GITHUB_PAT_SPA"
echo "   Аккаунт: $USER"
echo ""
echo "Теперь можно пушить:"
echo "  python3 /Users/yuriikulieshov/Documents/SPA_Claude/push_to_github.py \\"
echo "    --files path/to/file.py \\"
echo "    --message 'feat: описание'"
echo ""
echo "Проверка (покажет первые 4 символа):"
TOKEN=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null)
echo "  Сохранено: ${TOKEN:0:4}... (длина ${#TOKEN})"

# Обнуляем переменную — не оставляем PAT в памяти процесса дольше нужного
PAT=""
TOKEN=""
