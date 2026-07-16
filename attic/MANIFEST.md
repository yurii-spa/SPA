# attic/ — обратимый карантин (НЕ удаление)

Сюда переезжают подтверждённо-ненужные файлы во время аудита (программа
`docs/SYSTEM_AUDIT_AND_ARCHITECTURE_PROGRAM.md`). **Ничего не удаляем** — всё обратимо.
Удаление чего-либо из attic/ — только отдельным owner-решением позже.

| Дата | Файл (откуда) | Причина подозрения | Как вернуть |
|---|---|---|---|
| 2026-07-16 | com.spa.morning_digest.plist + agent_morning_digest.sh (launchd/, scripts/) | Переиспользовал РЕТАЙРЕННЫЙ лейбл morning_digest (в RETIRED_LABELS) под work-digest → коллизия/drift. Переименован в com.spa.work_digest. | вернуть = git mv назад + re-bootstrap |
