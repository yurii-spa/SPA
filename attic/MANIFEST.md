# attic/ — обратимый карантин (НЕ удаление)

Сюда переезжают подтверждённо-ненужные файлы во время аудита (программа
`docs/SYSTEM_AUDIT_AND_ARCHITECTURE_PROGRAM.md`). **Ничего не удаляем** — всё обратимо.
Удаление чего-либо из attic/ — только отдельным owner-решением позже.

| Дата | Файл (откуда) | Причина подозрения | Как вернуть |
|---|---|---|---|
| 2026-07-16 | com.spa.morning_digest.plist + agent_morning_digest.sh (launchd/, scripts/) | Переиспользовал РЕТАЙРЕННЫЙ лейбл morning_digest (в RETIRED_LABELS) под work-digest → коллизия/drift. Переименован в com.spa.work_digest. | вернуть = git mv назад + re-bootstrap |
| 2026-07-16 | 49 одноразовых скриптов (push_*.sh, install one-shots, .command, migrate/backfill, .plist.disabled — все 0-ref) → scripts/archive/ | WS-A аудит: вытеснены push_to_github.py/install_all_agents.sh; 594 уже там | git mv назад из scripts/archive/ |
| 2026-07-16 | monitoring/{posture_gate,adapter_watchdog}.py + alerts/protocol_report.py + их посвящённые тесты; tests/test_json_to_sqlite.py (фикс фазы-1: осиротел от archive migrate_json_to_sqlite) | precise 0-import + collect-only 102593 clean + import-smoke OK; модуль+тест вместе (инв#16) | git mv назад |
| 2026-07-16 | spa_core/portfolio/ (drift_calculator,state_tracker,rebalance_signal,__init__) + tests/test_portfolio_state.py | мёртвый остров: externally 0-import, модули импортят только друг друга, тест посвящён только им; collect 102574 clean | git mv назад + mkdir portfolio |
