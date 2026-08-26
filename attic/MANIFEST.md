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

## Отчёты доказательной базы, снятые 2026-08-26 (ADR-140)

Решение владельца 2026-08-25 (вариант 1) по карточке «Три отчёта о доказательной базе трека
молчат 2 месяца»: **оживить ТОЛЬКО тридцатидневный отчёт**, недельный и ежедневный — в архив.

| файл | что это было | последний живой результат |
|---|---|---|
| `attic/scripts/weekly_evidence_report.py` | недельный отчёт → `data/weekly_evidence/YYYY-WNN.md` | **20 июня 2026**, ровно один файл `2026-W24` |
| `attic/scripts/test_weekly_evidence_report.py` | его тесты | переехали за своим предметом |
| `attic/alerts/daily_evidence_report.py` | ежедневная сводка прогресса в Телеграм | **отправок не было ни разу** |
| `attic/alerts/test_daily_evidence_report.py` | его тесты | переехали за своим предметом |

**Откуда достать:** `git mv attic/scripts/<файл> scripts/` · `git mv attic/alerts/daily_evidence_report.py spa_core/alerts/`
(тесты — обратно в `tests/`). Прежде чем доставать — прочитать ADR-140: причина архивации не в
том, что отчёты плохие, а в том, что недельный и ежедневный дублируют живой брифинг системы и
утренний дайджест, а третий ежедневный канал сообщений владельцу стал бы шумом, который
перестают читать.

**Что осталось живым:** `scripts/generate_evidence_report.py` (тридцатидневный отчёт) — теперь
шаг дневного цикла в `cycle_reporting.run_post_cycle_advisory`, плюс сторож свежести
`data/evidence_report_30d_status.json`, чтобы «молчит 56 дней» больше не могло случиться
незамеченным.

**НЕ архивированы намеренно:** `scripts/run_daily_simulation.py` (общий мёртвый корень цепочки)
и `scripts/run_health_check.py`. Ни тот ни другой не входят в тройку отчётов, а решение владельца
было про отчёты. Замер, полученный попыткой: стоит убрать корень — и храповик неподключённых
скриптов немедленно объявляет `run_health_check` новым сиротой. То есть сегодня он числится
подключённым только потому, что его зовёт скрипт, который сам не зовёт никто; сторож этого не
видит, потому что мёртвый вызывающий для него всё ещё вызывающий. Это отдельная находка и
отдельное решение, а не побочный эффект архивации отчётов.
