# E2.1 — карта писателей карточек трекера (29.10, ветка autonomy/s1, база origin/main `fe77594cb`)

Метод: из 24 модулей, которые и упоминают трекер, и что-то пишут, отобраны реально пишущие `*.md` карточки;
для каждого — функция, путь запуска и граница. Чтение кода, без запуска. «atomic» — tmp + `os.replace`
(`spa_core/utils/atomic.py::atomic_save_text`): защищает от порванного файла, НЕ от потерянного обновления.

| Писатель | Функция | Через `queue.set_status`? | Граница до S1 | После S1 (ADR-857) | Кто запускает |
|---|---|---|---|---|---|
| `owner_queue/queue.py` | `set_status`, `create_card`, `set_acceptance_probe` | это и есть общий путь | atomic; проверка жизненного цикла; блокировки нет | **`set_status`: блокировка на карточку + `expected_revision`** | библиотека |
| `scripts/orchestrator_queue.py` | `set-status`, ingest, probe, deliver-new | да | как у queue.py | наследует (без `expected_revision` у вызовов — прежнее поведение) | `com.spa.orchestrator`, `orchestrator2`, CLI |
| `scripts/check_card_claim.py` | `claim_card`, `release_card`, `_set_claim_fields` | нет, напрямую | `O_EXCL <card>.md.claimlock` (соблюдает только он сам) | не изменён | cockpit_loop, orchestrator2, CLI |
| `owner_queue/cockpit_loop.py` | `_set_fields`, `set_status`, `claim_card` | смешанно | atomic на `_set_fields` | `set_status`-часть охвачена; `_set_fields` — НЕТ | диспетчер пульта в `agent_orchestrator.sh` |
| `owner_queue/intake.py` | `_stamp_seen`, `set_status` | смешанно | atomic; свой mkdir-замок `/tmp/spa_inbox_intake.lock.d`, не пересекается с замком цикла | `set_status`-часть охвачена; `_stamp_seen` — НЕТ | `com.spa.inbox_watch` |
| `owner_queue/owner_answer.py` | `_write_answer`, `carry_owner_answer` | нет | atomic; сверка версии вопроса только у `record_session_answer` | не изменён | обратный вызов Telegram |
| `telegram/owner_decisions.py` | `refresh_live_copy_from_ref`, `materialize_card`, `record_owner_answer` | нет | atomic; перезапись карточки целиком из git-ссылки | не изменён | бот (`com.spa.telegram_bot`, замок одного экземпляра) |
| `scripts/safe_site_push.py` | `create_card` | да | queue.py | наследует | цикл, novel_edge_rnd |
| `goal_graph` (новое) | журнал прогона | — | — | **flock + ожидаемое состояние + поколение захвата** | стенд, CLI, пульт |

Не пишут карточки (артефакты/отчёты/темп-каталоги): `build_tracker_board.py` (`_BOARD.md`), `cockpit_dispatch.py`
(файл ид. в mktemp), `resend.py`, `first_delivery.py`, `check_owner_order_starvation.py`, все 10 модулей
`monitoring/*` из выборки, `mission_control.py`, `director_report.py`, `card_lookup.py`, `reports/daily.py`.

## Непокрытые пути (названы, не спрятаны) и что из этого следует

1. Редакторы frontmatter мимо `set_status`: `cockpit_loop._set_fields`, `intake._stamp_seen`,
   `check_card_claim._set_claim_fields`, `owner_answer._write_answer`, `owner_decisions.materialize_card` /
   `refresh_live_copy_from_ref`. Блокировку S1 они НЕ соблюдают ⇒ гонка «последний пишет» между ними и
   `set_status` остаётся возможной. Перевод их на общий протокол — E2.6 (канарейка по одному писателю).
2. Ответ кнопкой (`record_owner_answer`) не сверяет версию вопроса — E3.4.
3. Замок приёма и замок цикла не пересекаются; `cockpit_dispatch rewake` идёт до замка цикла.
4. `create_card` — окно между проверкой существования и записью (суффиксный цикл).

Следствие (E2.6): ОПАСНАЯ общая операция над трекером (прежний `repair --apply`, массовые переходы) остаётся
ЗАКРЫТОЙ — охват писателей неполон.
