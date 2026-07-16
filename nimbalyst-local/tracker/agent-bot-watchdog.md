---
trackerStatus:
  type: agent-task
title: Починка Telegram-бота (watchdog)
status: done
source: owner-2026-07-16
created: 2026-07-16
---

Telegram-бот завис (тихий висяк 15ч, PID жив). Добавил watchdog-поток: форс-рестарт при застое петли → launchd поднимает. Самолечение.
