# STUDIO-TRUTH-AND-OWNER-CONTROL-01 · матрица 29 находок (QA 04.11)

База: `origin/main` `71498dc26`. Ветки: SPA `truth/owner-control-01`, earn-defi `truth01/alert-state-change`,
Studio Bridge (локальный репо) `b19.7-truth-owner-control`. Статусы: **FIXED** — исправлено в ветке и
закреплено тестом · **PARTIAL** — исправлено частично, остаток назван · **NOT A DEFECT** — с доказательством ·
**OPEN** — не исправлено, есть причина · **OWNER** — нужен ответ владельца.

Тесты: `spa_core/tests/test_truth_owner_control_01.py` (SPA), `tests/test_truth_owner_control_01.py` (Bridge),
`tests/test_a4_a5_monitoring_report.py` (earn-defi).

## Классы общих причин

| Класс | Находки | Доказанная первопричина |
|---|---|---|
| **R1 · финансовая блокировка невидима** | F2, T01, T02, T10, T11 | Read models SPA (`mission_control` overview/system, `views/home.py`, `warnings.py`) читают только файлы SPA; режим earn-defi (`earn_defi.db#system_state`) не попадал ни в одну ось, кроме вкладки «Капитал». `views/home.py:35` печатал «✅ система OK» безусловно. Сам KC-1 — защёлкнутый инцидент 19.09 из незакрытой дневной свечи Coinbase (баг исправлен в earn-defi `21c125e` 30.09, ложная цена 78 084,36 в `market_data` не перезаписывается, инцидент никто не снял) |
| **R2 · «вопрос открыт» решает каждый по-своему** | F1, F7, T03, T04, T05, F8 | У карточки нет машиночитаемого «снято/заменено»; `company_truth.decisions_triage` фильтровал по статусу на origin, игнорируя ответ на Mac (v1) и `supersedes`; `overview.needs_owner.top` брал первые три без фильтра; prod-only брал все карточки; признака теста нет; Bridge считал `owner_only` + одобренное как «ждёт решения» |
| **R3 · свежесть снимка выдаётся за свежесть данных** | F3, F14, T08, D3 | `_meta(state, src, now, now)` у ряда разделов; `as_of` книги = начало окна v2 (02.10); `short_ts` отбрасывал дату (09:11Z 01.07 → «11:11»); GoLive искал `generated_at`, а пишется `timestamp` |
| **R4 · словарь статусов неполон и смешан** | F5, F9, F10, F11, T12 | Нет кодов HOLD/CRITICAL/SHELF_NOT_DELIVERED; «29/29 ready» печатался «✅ ГОТОВ»; знаменатели флота не подписаны; `cycle_failed` никогда не закрывается (`resolve("cycle_failed")` не вызывается нигде); «никто не работает» по журналу при живой сессии |
| **R5 · повтор = таймер, а не событие** | T01, T03, T14, C4 | earn-defi `_due` 6 ч < интервала 12:10/22:10; сторож сайта level-triggered с меткой времени в тексте; досылка кнопок — второе сообщение |

## Director OS

| ID | Sev | Root cause | Fix (ветка) | Тест | Статус |
|---|---|---|---|---|---|
| F1 | P1 | R2: v1-ответ на Mac и `supersedes` игнорировались; `top` без фильтра | `company_truth.question_closed_reason`, `superseded_ids`, группа `closed_elsewhere`; `top` = только NEEDS_OWNER | `OpenQuestions.*` | FIXED — на живых данных обе дисковые карточки ушли в `closed_elsewhere` (одна — ответ на Mac, вторая — заменена) |
| F2 | P1 | R1 | ось `system.investment` + `overview.investment`; `owner_view.investment_blocks` первым пунктом проблем и в «Главное сейчас» | `InvestmentAxis.*` | FIXED (отображение); **снятие инцидента — OWNER** |
| F3 | P1 | R3: `as_of` книги = 02.10; «34 и 62 дня» — разные определения без подписи | `as_of` = `last_cycle_at`, STALE через 26 ч; `window_from`, `days_definition_ru`; текст «за N дн. с ДД.ММ» | `FreshnessAndTime.test_book_as_of…` | FIXED. 62 дня earn-defi = `COUNT(DISTINCT date) nav_daily` с 02.09 (вкл. v1) — подписано в блоке движка как «наблюдённых дней» |
| F4 | P1 | R4: SHELF_NOT_DELIVERED не распознан, следующий шаг не назван | `PROBLEM_RU["SHELF_NOT_DELIVERED"]`: публикация — решение владельца, ничего не публикуется автоматически | `StatusWords.test_known_codes…` | FIXED. Витрину 28.10 владелец отклонил (ADR-901 п. 9); открытая карточка `site_numbers…-2` — в «Решениях» |
| F5 | P2 | R4: 29/29 = «готов» | GoLive: «критерии пройдены · live НЕ разрешён — решения владельца нет» | `StatusWords.test_golive…` | FIXED |
| F6 | P2 | `plain()` превращал `site_numbers.json` в «(служебное имя)», «полным CI» → «полным автотесты», заглушки `<id>` | `KNOWN_FILES_RU`, замена заглушек, грамматика CI, `ru_plural` («34 бара») | `TradingCandidatesShownInFull` | PARTIAL — исправлены найденные; полная вычитка RU/EN не проводилась |
| F7 | P2 | R2: нет признака теста | `test_or_fixture_reason` (поля рождения: `submission_id demo-e2e-/auto-e2e-`, `claimed_by arb-demo`, `fixture: true`); «Мои записи» и prod-only их исключают, история — в группе `test_or_fixture` | `OpenQuestions.test_fixture…` | FIXED. «Купить зонт» — настоящая запись владельца из Telegram (не помечена тестом): по заголовку не угадываем |
| F8 | P2 | два источника истины (`verified_by_probe` в frontmatter и `execution.verified` ADR-839) | `done_recorded_unverified`: «итог записан, запуск проверки не привязан» | `RecordOutcome…` | FIXED |
| F9 | P2 | R4: «никто не работает» по журналу задач при живой интерактивной сессии | `count_interactive_claude`; текст называет оба измерения | — (отображение) | FIXED |
| F10 | P2 | R4: DEGRADED без всех причин; `cycle_failed` вечный; 91/91 vs 91/92 | все оси названы; `incident_row` — актуальность по последнему циклу (`NOT_CONFIRMED`); знаменатели подписаны, WARNING вне манифеста виден | `FreshnessAndTime.test_incident_actuality…` | PARTIAL — `resolve("cycle_failed")` в `cycle_runner` НЕ добавлен (денежный путь, отдельная задача) |
| F11 | P2 | R4 | `ORACLE_STANCE_RU` (HOLD), CRITICAL у проверки сайта, STALE/NOT_MEASURED системы | `StatusWords.test_known_codes…` | FIXED |
| F12 | P2 | `LIMIT 1` + `action` пишется ПОСЛЕ исполнения (строка с fill несёт HOLD) | `read_model.signal_events` — пары «сигнал → исполнение» по строке с `fill_price`; лента в карточке; строки по кандидатам видны и при незрелом результате; годовая ставка с длиной окна | `SignalEvents.*`, `test_annualised…` | FIXED (на живом ledger: 14 событий, все EXECUTED) |
| F13 | P2 | версия не выводилась; «одобренный релиз» = доверенный корень S2, к флоту не подключён | `system.code.versions` (код флота · сборка пульта · раздатчик UNKNOWN · доверенный корень); строка «Версия системы» | — | FIXED (раздатчик честно UNKNOWN) |
| F14 | P2 | R3 | `overview.freshness` по всем `_meta`; движки — по самому старому `as_of` | `test_fresh_snapshot…` | FIXED |
| P3 | P3 | мобильная ширина, форматы, локализация | — | — | OPEN — см. RELEASE_READINESS «не сделано» |

## Telegram

| ID | Sev | Root cause | Fix | Тест | Статус |
|---|---|---|---|---|---|
| T01 | P1 | R1+R5: earn-defi шлёт через Keychain SPA сырым POST, 92 доставки `system.mode` (замер `earn_defi.db#alerts`, 19.09–03.11, 2/сутки) | earn-defi D-62: по состоянию, напоминание раз в 72 ч с датой начала | earn-defi `test_unchanged_incident_is_reminded…` | FIXED (ветка earn-defi) |
| T02 | P1 | R1+R4 | главный экран бота: строка «Движки» + честный флот | `StatusWords.test_fleet…` | FIXED |
| T03 | P1 | R2+R5. Замер журнала решений: 200 записей, Σ send_count 303, 10 упёрлись в потолок 5. Цифры аудита 1672/1463 старше кольцевых журналов — НЕ ИЗМЕРИМЫ локально | досылка кнопок правит исходное сообщение | `HealEditsTheOriginal.*` | PARTIAL — исторические повторы до введения 6-ч окна не воспроизводятся; повтор по ответу «что на мне?» (`owner_requested`) оставлен — это запрос владельца |
| T04 | P1 | R2 + Bridge: `owner_only` всегда OWNER_BLOCKED, одобренное считалось «ждёт» | Bridge: `owner_approved_awaiting_execution`; SPA: одно определение; карточки без темы (ADR-285) не в счёте, их число печатается рядом — пульт «0 + 2 без темы» = бот «2» | Bridge `ApprovedIsNotAwaitingDecision`, SPA `test_triage…` | FIXED. «0» — старое сообщение `/decisions` (маршрута нет) — NOT A DEFECT сегодняшнего состояния |
| T05 | P2 | R2 | как F7 | как F7 | FIXED |
| T06 | P2 | push сигналов не существует | лента read-only; архитектура push — RFC в OWNER_TRUTH_CONTRACT §6, **OFF** | — | FIXED (лента) · push — OWNER |
| T07 | P2 | `director_report.py:779` `fwd[:3]` | все, «N из M» | `TradingCandidatesShownInFull` | FIXED |
| T08 | P2 | R3 | `short_ts` с датой, «позже текущего», GoLive `timestamp`, DeFi «данные в норме (на …)» | `FreshnessAndTime.test_short_ts…` (вкл. DST) | FIXED |
| T09 | P2 | как F13 | `render_system`: код флота vs доверенный корень | — | FIXED |
| T10 | HYP | два ≈$99 891 | — | — | **NOT A DEFECT**: earn-defi `nav_daily` id=62 $99 891,23 и SPA Balanced `hy_paper_trading.json equity` $99 891,20 — разные объекты, разница $0,03; ловушка: −0,11 % = cum_return earn-defi И drawdown Balanced |
| T11 | HYP | $103 182,82 | — | — | **ЧАСТИЧНО ВЕРНО**: законный NAV earn-defi за 18.09 по coinmetrics (`nav_daily` id=17, записан 19.09 10:10:01Z, той же секундой, что инцидент); KC-1 сравнил его с NAV по незакрытой свече Coinbase 78 084,36 → $100 681,99 |
| T12 | P3 | R4 | подписанные знаменатели | — | FIXED |
| T13 | P3 | — | — | — | NOT REPRODUCED в окне замера: 500 сообщений `alert_history` (24.09–04.11) — 0 сырого HTML, 0 Python-словарей, 0 JSON; «live» только в «Go-Live». Старее окна измерить нечем |
| T14 | P3 | R5: 113 сообщений сторожа за 41 день | отпечаток набора кодов, напоминание раз в 24 ч | `SiteWatchdogRepeats.*` | PARTIAL — копия сторожа в GitHub Actions живого состояния не имеет и дедупа не получает (решение — в пакете вопросов) |
| T15 | P3 | Bridge `dr:` всегда новое сообщение, нет «Домой» | правка на месте + «🏛 Домой» | Bridge `NavigationEditsInPlace` | FIXED |
