---
trackerStatus:
  type: agent
title: Манифест архитектуры не знает об агенте morning_digest — тест красный на origin
status: backlog
source: session-2026-08-06 (найдено при полном прогоне)
created: 2026-08-06
priority: medium
domain: архитектура / сторожа
---

## Факт

`test_architecture_manifest.py::RealManifest::test_generator_check_passes_on_this_machine_or_skips`
**красный на чистом origin** (проверено отдельным чекаутом без чужих правок):

```
DRIFT: com.spa.morning_digest: plist_source None → 'repo:launchd/com.spa.morning_digest.plist'
DRIFT: com.spa.morning_digest: schedule    None → 'calendar:09:00'
DRIFT: com.spa.morning_digest: program     None → 'agent_morning_digest.sh'
ИТОГ: манифест НЕ соответствует фактам (0 схемных, 3 дрейфовых)
```

Агент `com.spa.morning_digest` заведён, а в манифест архитектуры не внесён. Сторож честно
краснеет на верное состояние — чинить надо факт, а не сторожа.

## Почему это не мелочь

Манифест — единственное место, где записано, из чего система состоит. Агент, которого в нём нет,
невидим для всего, что опирается на манифест. Плюс красный тест на origin приучает не смотреть
на прогон, а это дороже самой поломки.

## Что сделать

Внести `com.spa.morning_digest` в манифест (источник plist, расписание `calendar:09:00`, программа
`agent_morning_digest.sh`) — то есть привести манифест в соответствие с фактом.

## Чего не делать

Не гасить проверку и не вносить агента в исключения: она краснеет правильно.
Карточка заведена сессией, которая агента НЕ заводила — если у автора есть причина держать его вне
манифеста, пусть запишет её здесь.
