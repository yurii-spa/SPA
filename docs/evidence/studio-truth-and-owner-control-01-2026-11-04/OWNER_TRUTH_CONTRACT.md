# Контракт правды для поверхностей владельца (Director OS · SPA Monitor · Studio Bridge)

Решение: [ADR-917](../../decisions/ADR-917-owner-truth-contract-separate-axes.md). Это расширение существующих
конвертов (`_meta` в `mission_control`, `cell` в `company_truth`, `metric` в `owner_view`), а не новая модель.

## 1. Оси состояния — раздельно, без GLOBAL_STATUS

| Ось | Где в модели | Источник | Что НЕ означает |
|---|---|---|---|
| system_health (службы) | `system._meta`, `overview.system` | launchctl, agent_health, code_sync, backups, resources | ≠ «инвестиционный контур в норме» |
| investment_engine_mode | `system.investment`, `overview.investment` | ledger движка (`earn_defi.db#system_state,incidents`) | ≠ «риск-лимиты соблюдены» (RiskPolicy — своя ось) |
| risk_gate_state | `overview.system.kill_switch/derisk`, paper_trading_status | SPA kill_switch / derisk | ≠ «движок не заблокирован» |
| data_freshness | `overview.freshness` (по каждому `_meta`) | `observed_at` каждого раздела | возраст снимка ≠ возраст данных |
| owner_actions | `truth.decisions` → `owner_view.questions` | origin-карточки + ответы на Mac + `supersedes` | тестовые записи и снятые вопросы не считаются |
| studio_execution | `owner_view.work` | журнал задач + процессы Claude | «никто» только если пусты ОБА измерения |
| trading_research | `capital.trading_engines.blocks[spa]` + `signal_events` | `evidence.db` (ro) | сигнал ≠ допуск ≠ виртуальная сделка ≠ реальная |
| release_state | `system.code.versions`, `system.features` | `code_sync_status.json`, launchd, обёртки | «реализовано» ≠ «работает»; доверенный корень S2 ≠ код флота |

Верхний обзор поднимает материальное: блокировка движка — первым пунктом «Существенных проблем» и в «Главное
сейчас», но технические службы не перекрашиваются в красный.

## 2. Оценки

`OK/HEALTHY · WARNING/DEGRADED · CRITICAL · INCIDENT · BLOCKED · STALE · UNKNOWN · NOT_MEASURED · NOT_APPLICABLE`.
Отображение: существующие `COLOUR`/`CONFIDENCE_RU`. Неизвестный код — «не удалось понять» (проблема отображения),
никогда не OK. Добавлены известные: HOLD (позиция советника), CRITICAL (проверка сайта), SHELF_NOT_DELIVERED,
PUBLISHER_STUCK, STALE/NOT_MEASURED системы.

## 3. Факт на экране

Каждый `metric`: `label · text · confidence · source · measured_at (+_ru Мадрид) · updated_at · unit · technical`.
`measured_at` — момент замера источника, `updated_at` — сборка снимка. Время владельцу — Europe/Madrid (ADR-660);
в Telegram дата печатается всегда, когда отметка не сегодняшняя, отметка из будущего помечается.

## 4. Решения владельца — одно определение

Открытый вопрос = карточка `owner-decision`/`own-*` со статусом `needs-owner` на origin, **минус** закрытые ответом
на Mac (ANSWERED/INGESTED), **минус** заменённые (`supersedes` у новой карточки), **минус** тест/демо
(`test_or_fixture_reason`: только поля рождения). Предмет не объявлен ⇒ в счёт вопросов владельцу не входит (ADR-285: сначала разбирает агент), число печатается рядом. Возраст причиной закрытия не является. Bridge: одобренное (`owner_approved_awaiting_execution`)
≠ «ждёт решения».

## 5. Повторы уведомлений — по событию

Идентичность = ключ события; версия = тяжесть + текст (без меток времени). Новое и изменившееся — сразу (эскалация —
немедленно); неизменное — напоминание с датой начала: earn-defi 72 ч, сторож сайта 24 ч. Кнопки к ушедшему без кнопок
решению — правкой исходного сообщения. Существующие механизмы (`push_policy`, `guard_outbound`, журнал решений) не
заменялись.

## 6. RFC: push о BUY/SELL — спроектирован, ВЫКЛЮЧЕН

* Событие = строка ledger с `action != HOLD`; `event_id = sha256(candidate_id + bar_close_time + action)`.
* Доставка после записи строки исполнения (или с пометкой «ждёт исполнения»); несколько сигналов одного такта —
  одно сообщение-сводка.
* Дедуп — durable состояние «последний отправленный event_id по кандидату»; после рестарта сверка с ledger, отправка
  только новых. Потолок: 1 сводка на такт, не более 6 в сутки.
* Важность: информационная (paper, $0); не CRITICAL.
* Флаг `TR_SIGNAL_PUSH=off` по умолчанию; включение — отдельное решение владельца. Тестовых отправок нет.

## 7. Управление с телефона (Epic I) — что реально работает

| Сценарий | Сегодня | Путь |
|---|---|---|
| Идея / задача / голос | работает | Studio Bridge, подтверждение владельцем (ADR-521) |
| Ответ на решение | работает | кнопки SPA-бота (журнал решений) |
| Наблюдение жизненного цикла | работает (read-only) | Director OS «Мои записи», Bridge |
| Назначение роли / запуск / приёмка с телефона | **нет** | нужен write-path → RFC ниже |

RFC write-path (не включается этой программой): полномочия по предмету ADR-285; авторизация Cloudflare Access +
owner chat id; поручение версионируется (`question_version` уже есть у ответов); идемпотентность по `decision_id`;
запись в канонический трекер только через `orchestrator_queue`; отказ на устаревшую версию; компенсация — обратный
переход статуса с записью; приёмка — машинная проба (`acceptance.md`). ADR-762 остаётся OFF.
