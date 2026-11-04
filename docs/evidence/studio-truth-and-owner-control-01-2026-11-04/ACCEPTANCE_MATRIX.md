# Матрица приёмки → тесты

| Сценарий ТЗ §17 | Тест |
|---|---|
| INCIDENT + все службы здоровы → обзор не «всё в норме» | SPA `InvestmentAxis.test_overview_headline_cannot_say_all_is_well_under_incident` |
| INCIDENT: причина, дата, снимает владелец; повторы видны; снятый не цепляется; битая запись | `InvestmentAxis.*` (6 тестов) |
| нет ledger → NOT_MEASURED, не OK | `test_missing_ledger_is_not_measured_never_ok` |
| неизменный INCIDENT при повторных прогонах; изменение тяжести/текста; напоминание | earn-defi `test_unchanged_incident_is_reminded_not_repeated`, `test_changed_finding_is_sent_and_escalation_is_immediate` |
| снятое / заменённое / ответ на Mac / возраст не причина | `test_company_truth_open_questions.OpenQuestions.*` |
| тестовые карточки — по полям, не по заголовку | `test_fixture_markers_are_fields_not_title_guesses` |
| одобрено ≠ ждёт решения | Bridge `ApprovedIsNotAwaitingDecision.*` |
| счётчик пульта = Bridge /needs (паритет) | существующий `test_owner_queue_count_matches_the_telegram_director` |
| «сделано» ≠ «проверено» | `RecordOutcomeIsNotSelfContradictory.*` |
| свежий снимок со старым источником; timestamp из будущего; DST Мадрид | `FreshnessAndTime.*`, `BookFreshness.*` |
| старая тревога без подтверждения | `test_incident_actuality_against_last_cycle` |
| 29/29 ≠ live; WARNING ≠ OK; известные коды | `StatusWords.*` |
| сигнал без исполнения / с исполнением / HOLD не событие | `SignalEvents.*` |
| 5 из 5 кандидатов | `TradingCandidatesShownInFull` |
| годовая ставка с окном | `test_annualised_rate_names_its_window` |
| повтор сторожа сайта: тот же набор / новый / нет состояния | `SiteWatchdogRepeats.*` |
| кнопки правкой; отказ правки → новое сообщение | `HealEditsTheOriginal.*` |
| навигация правит своё сообщение; «Домой» | Bridge `NavigationEditsInPlace.*` |
| отсутствие наблюдения не выходит пустотой | существующий храповик `test_absent_observation_ratchet` |
| никаких отправок в тестах | все прогоны — `security` заглушён, `SPA_TRACKER_DIR` — ловушка |

Не автоматизировано: 296 px; живой маршрут туннель→вход→iPhone (IPHONE_ACCEPTANCE — вручную).
