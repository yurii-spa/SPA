#!/bin/bash
# Установщик старого callback-бота `com.spa.bot_commands`. ОТКАЗЫВАЕТ по умолчанию.
#
# Почему (замер цикла #218)
# ---------------------------------------------------------------------------
# `bot_commands` читает обновления через `getUpdates` — как и живой `com.spa.telegram_bot`,
# который его ЗАМЕНИЛ (см. докстринг `spa_core/telegram/bot.py`). Токен у них один, а
# Telegram отдаёт длинный опрос ровно одному читателю: второй поллер на том же токене —
# это 409 Conflict и ПОТЕРЯННЫЕ КОМАНДЫ ВЛАДЕЛЬЦА. Ровно это и случилось 13.08 (цикл #185),
# когда гейт «запустить разок» поднял второго бота на ~3 минуты.
#
# Измерено сегодня, а не предположено:
#   * `launchd/com.spa.bot_commands.plist` в репозитории НЕТ и не было ни в одном коммите;
#   * на хосте в ~/Library/LaunchAgents его тоже нет, загружен только com.spa.telegram_bot;
#   * поэтому `cp` ниже падал под `set -e` — установщик и так не работал, просто МОЛЧА и
#     по неверной причине («нет файла» вместо «второй поллер запрещён»).
#
# Отказ поставлен вслух: скрипт, который выглядит рабочим и роняет канал владельца при
# первой удаче, опаснее отсутствующего. Осознанный обход — SPA_ALLOW_SECOND_POLLER=1, и
# перед ним обязана быть выгружена `com.spa.telegram_bot` (иначе два читателя одного токена).

set -euo pipefail

if [ "${SPA_ALLOW_SECOND_POLLER:-0}" != "1" ]; then
  echo "⛔ ОТКАЗ: com.spa.bot_commands — второй читатель ТОГО ЖЕ токена Telegram." >&2
  echo "   Живой бот: com.spa.telegram_bot (он заменил этот модуль)." >&2
  echo "   Поднять второго = 409 Conflict у getUpdates = команды владельца теряются (#185)." >&2
  echo "   Если это действительно нужно: сначала выгрузить com.spa.telegram_bot," >&2
  echo "   затем SPA_ALLOW_SECOND_POLLER=1 bash scripts/install_bot_commands.sh" >&2
  exit 3
fi

PLIST=~/Documents/SPA_Claude/launchd/com.spa.bot_commands.plist
if [ ! -f "$PLIST" ]; then
  echo "⛔ ОТКАЗ: $PLIST отсутствует (его нет и в истории репозитория)." >&2
  exit 4
fi

if launchctl list | grep -q "com.spa.telegram_bot"; then
  echo "⛔ ОТКАЗ: com.spa.telegram_bot загружен — два поллера на одном токене." >&2
  exit 5
fi

mkdir -p ~/Documents/SPA_Claude/logs
cp "$PLIST" ~/Library/LaunchAgents/com.spa.bot_commands.plist
launchctl unload ~/Library/LaunchAgents/com.spa.bot_commands.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.spa.bot_commands.plist

echo "✅ SPA Bot Commands installed and running"
echo "📋 Logs: ~/Documents/SPA_Claude/logs/bot_commands.log"
echo "🔍 Status: launchctl list | grep spa.bot"
