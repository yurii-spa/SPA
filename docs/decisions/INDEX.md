# ADR INDEX — реестр архитектурных решений

> Каждое решение, меняющее инвариант / risk-логику / контур, оформляется ADR по шаблону
> `_TEMPLATE.md` (Контекст → Решение → Последствия). **Перед изменением risk-логики —
> прочитать соответствующий ADR.**

| ADR | Заголовок | Статус | Файл |
|---|---|---|---|
| ADR-029 | Research strategies framework | Accepted | [ADR-029](ADR-029-research-strategies-framework.md) |
| ADR-030 | PIT backtest standard | Accepted | [ADR-030](ADR-030-pit-backtest-standard.md) |
| ADR-034 | Two-tier kill-switch (исходный) | Superseded by ADR-048 | *(историческое, см. ADR-048)* |
| ADR-048 | Two-tier kill-switch SOFT −5% / HARD −10% inclusive | Accepted | [ADR-048](ADR-048-two-tier-kill-switch.md) |
| ADR-050 | RiskPolicy → governance-слой; API auth; exec-bypass закрыт | Accepted | [ADR-050](ADR-050-riskpolicy-governance-layer.md) |
| ADR-053 | RTMR real-time monitoring sense-loop | Accepted | [ADR-053](ADR-053-rtmr-sense-loop.md) |
| ADR-054 | ADR-054 — Kill-Switch Authority & Ownership | Accepted | [ADR-054](ADR-054-kill-switch-authority.md) (RFC `docs/rfcs/RFC-054-kill-switch-authority.md`; impl plan `docs/rfcs/RFC-054-implementation-plan.md`) |
| ADR-055 | ADR-055 — Head-of-Investment agent layer (dynamic tiers · capital-per-tier · yield maximization · decider) | Accepted | [ADR-055](ADR-055-head-of-investment-agent-layer.md) |
| ADR-056 | ADR-056 — rules_watchdog circuit-breaker reads the REAL kill-switch state files | Accepted | [ADR-056](ADR-056-rules-watchdog-real-killswitch-files.md) |
| ADR-057 | ADR-057 — go-live gate verifies adapters by IMPORT, not just compile() | Accepted | [ADR-057](ADR-057-golive-gate-import-based-adapter-checks.md) |
| ADR-058 | ADR-058 — fabricated track-evidence: flag (not delete) + milestones from real days only | Accepted | [ADR-058](ADR-058-fabricated-evidence-honesty.md) |
| ADR-059 | ADR-059 — S23 reads the LIVE MP-201 Pendle feed; go-live gate criterion re-pointed | Accepted | [ADR-059](ADR-059-s23-live-pendle-mp201.md) |
| ADR-060 | ADR-060 · Триггер ребаланса по улучшению доходности (гистерезис · стоимость переключения · анти-churn) | Accepted | [ADR-060](ADR-060-yield-improvement-rebalance-trigger.md) |
| ADR-061 | ADR-061 · Гейт доказанности APY + advisory/GSM-гейт в money-path аллокаторе (D1–D4) | Accepted | [ADR-061](ADR-061-apy-evidence-gate.md) |
| ADR-062 | ADR-062 · Покрытие защитного слоя: тир-зависимый per-protocol кэп + лимиты по цепочкам (W4.1) | Accepted | [ADR-062](ADR-062-enforcer-coverage-caps.md) |
| ADR-063 | ADR-063 · Адаптеры читают `adapter_status.json` по РЕАЛЬНОЙ схеме и не подставляют литерал (D1) | Accepted | [ADR-063](ADR-063-adapter-status-schema-and-no-fake-fallback.md) |
| ADR-064 | ADR-064 — Закреплённая личность пула как условие TVL-доказательства | Accepted | [ADR-064](ADR-064-pinned-pool-identity-for-tvl-evidence.md) |
| ADR-065 | ADR-065 — Sky/sUSDS повышен из watch-list в T1 (условие инварианта 10 выполнено) | Accepted | [ADR-065](ADR-065-sky-susds-promoted-to-t1.md) |
| ADR-067 (дубль) | ADR-067 (номер занят) → решение перенумеровано в ADR-087 | Superseded | [ADR-067→087](ADR-067-golive-blocks-on-active-gaps-only.md) |
| ADR-066 | ADR-066 · Контур архитектурного соответствия и замыкание петли решений | Accepted | [ADR-066](ADR-066-architecture-conformance-and-decision-loop.md) |
| ADR-067 | ADR-067 · Пакет решений владельца 2026-08-06: судьба 9 агентов + мандат автопилота | Accepted | [ADR-067](ADR-067-owner-decisions-2026-08-06-autopilot-mandate.md) |
| ADR-068 | ADR-068 · Intraday-сенсор просадки: лестница kill-switch видит день, а не только утро | Accepted | [ADR-068](ADR-068-intraday-drawdown-sensor.md) |
| ADR-069 | ADR-069 — Кнопки действий под алертом: проблема приходит с вариантами, нажатие заводит карточку | Accepted | [ADR-069](ADR-069-alert-action-buttons.md) |
| ADR-070 | ADR-070 · Пакет решений владельца 2026-08-07: очередь разобрана полностью (22 решения) | Accepted | [ADR-070](ADR-070-owner-decisions-2026-08-07-queue-clearance.md) |
| ADR-072 | ADR-072 · Срезанный гейтом бюджет не выбрасывается: перераздача под повторным гейтом | Accepted | [ADR-072](ADR-072-gate-freed-budget-redistribution.md) |
| ADR-073 | ADR-073 · Перераздача срезанного бюджета обязана соблюдать лимиты сети | Accepted | [ADR-073](ADR-073-redistribution-must-respect-chain-limits.md) |
| ADR-073 (дубль) | Указатель: номер 073 занят перераздачей бюджета; решение о Телеграме перенумеровано в ADR-075. Файл не удалён — ссылка уже уехала в коммит 949dfcb8, мёртвая ссылка хуже указателя | Superseded | [ADR-073→075](ADR-073-owner-decisions-in-telegram.md) |
| ADR-074 | ADR-074 · Демоушен тиров по относительному рангу вместо абсолютного порога | Accepted | [ADR-074](ADR-074-rank-based-tier-demotion.md) |
| ADR-075 | ADR-075 — Решения владельца приходят в Телеграм с вариантами ответа | Accepted | [ADR-075](ADR-075-owner-decisions-in-telegram.md) |
| ADR-076 | ADR-076 · Живые фиды вне Ethereum — условие того, чтобы кэш вообще было куда положить | Accepted | [ADR-076](ADR-076-live-feeds-outside-ethereum.md) |
| ADR-077 | ADR-077 — Сторож Телеграма: замечает поломку связи с владельцем и чинит одну вещь | Accepted | [ADR-077](ADR-077-telegram-health-watchdog.md) |
| ADR-078 | ADR-078 · Мандат десятидневной автономии (2026-08-09 … ~2026-08-19) | Accepted | [ADR-078](ADR-078-ten-day-autonomy-mandate.md) |
| ADR-079 | ADR-079 — Кворум EB-02 поднят с 3 до 4 (решение владельца, вариант 3) | Accepted | [ADR-079](ADR-079-eb02-quorum-raised-to-four.md) |
| ADR-080 | ADR-080 · Доставка карточек переносит правку на прочитанный `origin`, а не пушит вслепую | Accepted | [ADR-080](ADR-080-card-delivery-rebases-onto-origin.md) |
| ADR-081 | ADR-081 · У провалившейся доставки карточек есть долг, и он повторяется | Accepted | [ADR-081](ADR-081-card-delivery-debt-retries.md) |
| ADR-082 | ADR-082 — Текстовый ответ владельца на карточку решения | Accepted | [ADR-082](ADR-082-owner-text-answer.md) |
| ADR-083 | ADR-083 — Параллельная работа — норма, а не исключение | Accepted | [ADR-083](ADR-083-parallel-work-is-the-norm.md) |
| ADR-084 | ADR-084 — Штатная самопочинка не зовёт владельца; наш собственный штамп времени не входит в ключ повтора | Accepted | [ADR-084](ADR-084-routine-selfheal-does-not-call-the-owner.md) |
| ADR-085 | ADR-085 — Site Custodian получает тело на Маке: снятие таблички честности обязано быть исполнимо | Accepted | [ADR-085](ADR-085-site-custodian-runs-on-the-mac.md) |
| ADR-086 | ADR-086 — След решения владельца обязан попадать в git: везём СЛЕД, а не карточку | Accepted | [ADR-086](ADR-086-owner-answer-trace-delivery.md) |
| ADR-087 | ADR-087 — Гейт go-live блокируют только АКТИВНЫЕ дыры трека | Accepted | [ADR-087](ADR-087-golive-blocks-on-active-gaps-only.md) |
| ADR-088 | ADR-088 — Мандат самостоятельной работы НЕ продлён: возврат к базовому протоколу | Accepted | [ADR-088](ADR-088-autonomy-mandate-not-renewed.md) |
| ADR-089 | ADR-089 — Пакет решений владельца 19.08.2026 (девять ответов за одиннадцать минут) | Accepted | [ADR-089](ADR-089-owner-decisions-batch-2026-08-19.md) |
| ADR-096 | ADR-096 · Просьба владельца снимает наши заслоны; открытые вопросы считаются по КАРТОЧКЕ | Accepted | [ADR-096](ADR-096-owner-solicited-resend-and-honest-open-count.md) |
| ADR-097 | ADR-097 — Политика возврата в рынок после жёсткой остановки: снятие за владельцем, но со СРОКОМ | Accepted | [ADR-097](ADR-097-killswitch-rearm-policy.md) |
| ADR-098 | ADR-098 — Site Custodian публикует из СВЕЖЕЙ копии: у таблички честности впервые есть путь вниз | Accepted | [ADR-098](ADR-098-site-custodian-publishes-from-fresh-checkout.md) |
| ADR-099 | ADR-099 · Номер решения занят и на ветке; судьба восьми ADR с `work-status-check` | Accepted | [ADR-099](ADR-099-adr-numbers-taken-on-branches.md) |
| ADR-100 | ADR-100 · Ветка — третье вместилище недоставленной работы; решение владельца по неполному замеру возвращается замером | Accepted | [ADR-100](ADR-100-step0a-sees-remote-branches.md) |
| ADR-101 | ADR-101 — Мандат автономии №2: 30 дней (2026-08-20 → 2026-09-19), и у мандата появился СРОК, который знает код | Accepted | [ADR-101](ADR-101-autonomy-mandate-2.md) |
| ADR-102 | ADR-102 · BTC-движок: чемпион v0.1 принят как замер, реализация НЕ начинается — просадка не помещается под стоп-кран | Accepted | [ADR-102](ADR-102-btc-cycle-backtest-archived-not-built.md) (материалы `research/btc_cycle/`) |
| ADR-103 | ADR-103 — Настоящая paper-книга рукавов B/C + директива CIO двигает paper-цикл | Accepted | [ADR-103](ADR-103-paper-book-and-cio-directive.md) |
| ADR-104 | ADR-104 — CIO следит за каждым движением актива, а не раз в день | Accepted | [ADR-104](ADR-104-cio-continuous-movement-watch.md) |
| ADR-105 | ADR-105 · «Дневной убыток посчитать нельзя» ⇒ цикл НЕ торгует (fail-CLOSED) | Accepted | [ADR-105](ADR-105-unmeasurable-daily-loss-halts.md) |
| ADR-106 | ADR-106 · Автопочинщик кода обезоружен: библиотека остаётся, точки запуска нет | Accepted | [ADR-106](ADR-106-auto-fixer-disarmed.md) |
| ADR-107 | ADR-107 · Файл аварийной остановки снят с git: тормоз должен переживать восстановление | Accepted | [ADR-107](ADR-107-halt-file-out-of-git.md) |
| ADR-108 | ADR-108 · Аварийная книга исключает протокол только против ДОКАЗАТЕЛЬСТВА | Accepted | [ADR-108](ADR-108-safe-fallback-evidence-gate.md) |
| ADR-109 | ADR-109 · Показываемая просадка считается той же функцией, что и допуск к деньгам | Accepted | [ADR-109](ADR-109-displayed-drawdown-is-the-gate-drawdown.md) |
| ADR-110 | ADR-110 · Общий фид обязан опознавать пул по личности актива, а не по трём строкам | Accepted | [ADR-110](ADR-110-asset-identity-in-the-shared-feed.md) |
| ADR-111 | ADR-111 · Книга прошлого дня берётся у датированного источника; разрешённая дозапись исполнена и дала НОЛЬ строк | Accepted | [ADR-111](ADR-111-outcomes-book-from-the-dated-curve.md) |
| ADR-112 | ADR-112 — Проверка дневного лимита, УПАВШАЯ с ошибкой, останавливает цикл | Accepted | [ADR-112](ADR-112-crashed-daily-limit-check-halts.md) |
| ADR-113 | ADR-113 — `telegram_watcher` оставлен, но обезоружен | Accepted | [ADR-113](ADR-113-telegram-watcher-disarmed.md) |
| ADR-114 | ADR-114 — Внутридневной paper-актор: DERISK рукавов между суточными циклами | Accepted | [ADR-114](ADR-114-intraday-paper-actor.md) |
| ADR-115 | ADR-115 — У карточки-ПОРУЧЕНИЯ есть кнопка ответа: «✅ Принято» / «🚫 Не надо» | Accepted | [ADR-115](ADR-115-ack-button-for-instruction-cards.md) |
| ADR-118 | ADR-118 — Отдельный paper-NAV трек BTC/USDT-движка (двухслойная граница) | Accepted | [ADR-118](ADR-118-btc-paper-nav-track.md) |
| ADR-119 | ADR-119 — Пакет решений владельца 2026-08-22: две доставки на машину | Accepted | [ADR-119](ADR-119-owner-decisions-2026-08-22-delivery.md) |
| ADR-116 | ADR-116 — Стоящее одобрение владельца: числа и legal на сайте меняются без карточки (фаза стройки) | Accepted | [ADR-116](ADR-116-standing-approval-site-numbers-legal.md) |
| ADR-117 | ADR-117 — Бот сам замечает обновление своего кода и чисто выходит под респавн launchd | Accepted | [ADR-117](ADR-117-bot-code-freshness-self-restart.md) |
| ADR-120 | ADR-120 · Protection Lab: историческая библиотека кризисов + replay поверх настоящего governance-слоя | Accepted | [ADR-120](ADR-120-protection-lab.md) |
| ADR-121 | ADR-121 — Пакет решений владельца 2026-08-22 (вторая партия): кэш, кредитный канал, канал заявок | Accepted | [ADR-121](ADR-121-owner-decisions-2026-08-22-batch2.md) |
| ADR-123 | ADR-123 · Одно число — один вердикт: композитный portfolio health ниже пола = WARNING у обоих сторожей | Accepted | [ADR-123](ADR-123-portfolio-health-verdict-alignment.md) |
| ADR-124 | ADR-124 · «Принято — беру в работу» перестало закрывать карточку | Accepted | [ADR-124](ADR-124-owner-accepted-non-terminal-status.md) |
| ADR-122 | ADR-122 — Решение владельца 2026-08-22: бесплатный чекап ПОХОРОНЕН (вариант 1) | Accepted | [ADR-122](ADR-122-owner-decision-2026-08-22-bury-checkup.md) |
| ADR-125 | ADR-125 · Три пакета начинают реальный paper-трек (Balanced + Aggressive деплоят сплошным) | Accepted | [ADR-125](ADR-125-three-tier-paper-tracks-start.md) |
| ADR-126 | ADR-126 — Два решения владельца от 18.08, не исполненные месяц, исполнены (вариант 1) | Accepted | [ADR-126](ADR-126-owner-decisions-2026-08-23-two-unexecuted.md) |
| ADR-127 | ADR-127 — Страница `/changelog` снята с сайта (решение владельца, вариант 1) | Accepted | [ADR-127](ADR-127-changelog-page-retired.md) |
| ADR-128 | ADR-128 — Два решения владельца от 2026-08-23 (доска карточек · две записи о деньгах) | Accepted | [ADR-128](ADR-128-owner-decisions-2026-08-23-batch3.md) |
| ADR-129 | ADR-129 — Шесть решений владельца от 2026-08-23 (вечерний пакет) | Accepted | [ADR-129](ADR-129-owner-decisions-2026-08-23-batch4.md) |
| ADR-130 | ADR-130 · Ежедневный аудит аналитики — обязательный шаг цикла оркестратора | Accepted | [ADR-130](ADR-130-daily-analytics-audit-as-cycle-step.md) |
| ADR-147 | ADR-147 — Сторож расхождения двух фидов адаптеров (D6 ADR-060 получил измеритель) | Accepted | [ADR-147](ADR-147-adapter-feed-divergence-guard.md) |
| ADR-YL-011 | Site Custodian — защита earn-defi.com от stale-чисел | Accepted | [ADR-YL-011](ADR-YL-011-site-custodian.md) |
| ADR-YL-012 | SPA Swarm — 5-слойный рой над aggressive-доменом (advisory) | Accepted | [ADR-YL-012](ADR-YL-012-spa-swarm.md) (charter `docs/SWARM_ARCHITECTURE.md`) |
| ADR-OWN-2026-07 | Пакет закрытых решений владельца (июль 2026) | Accepted | [ADR-OWN-2026-07](ADR-OWN-2026-07-owner-decisions-batch.md) |
| ADR-131 | Ограничение в шаблоне договора — общее правило governance-предусловия, без имени протокола (решение владельца 25.08, вариант 2) | Accepted | [ADR-131](ADR-131-contract-governance-precondition-rule.md) |
| ADR-132 | ADR-132 · Ротация ключа GitHub: чеклист ведёт в ТУ связку, а «поменял» — наблюдение, а не слово | Accepted | [ADR-132](ADR-132-pat-rotation-keychain-identity.md) |
| ADR-133 | ADR-133 — Tier-C: девять константных списаны, сто шестьдесят два записаны как «не знаем» | Accepted | [ADR-133](ADR-133-tier-c-nine-written-off-162-frozen.md) |
| ADR-134 | ADR-134 — Проверка книги доложена до симметрии с проверкой перед сделкой | Accepted | [ADR-134](ADR-134-portfolio-gate-symmetry.md) |
| ADR-135 | ADR-135 — Кураторы: сначала разметка как данные, потолок — следующим решением | Accepted | [ADR-135](ADR-135-curator-markup-before-cap.md) |
| ADR-136 | ADR-136 — Сетевые потолки у подборщика И у аллокатора | Accepted | [ADR-136](ADR-136-chain-caps-in-tuner-and-allocator.md) |
| ADR-137 | ADR-137 — Fluid: чужой GSM-гейт снят, допуск по общему ключу | Accepted | [ADR-137](ADR-137-fluid-alien-gsm-gate-removed.md) |
| ADR-138 | ADR-138 — Аллокатор отбирает лучшие N осознанно, строго после проверок | Accepted | [ADR-138](ADR-138-allocator-selects-best-n-after-gates.md) |
| ADR-139 | ADR-139 — Курс лаборатории считается по отметке времени, а не по календарному дню | Accepted | [ADR-139](ADR-139-lab-ratio-source-timestamp-paired.md) |
| ADR-140 | ADR-140 — Тридцатидневный отчёт оживлён шагом цикла, два других в архив | Accepted | [ADR-140](ADR-140-evidence-report-30d-revived.md) |
| ADR-141 | ADR-141 — У сторожа переходов статусов появился свой агент (подготовлен, не установлен) | Accepted | [ADR-141](ADR-141-tracker-status-sentinel-agent.md) |
| ADR-142 | ADR-142 — Поиск источников доходности: расписание И настоящий читатель | Accepted | [ADR-142](ADR-142-source-discovery-scheduled-with-a-reader.md) |
| ADR-144 | ADR-144 — Тюнер зеркалит RiskPolicy без собственных запасов (решение владельца 26.08) | Accepted | [ADR-144](ADR-144-tuner-mirrors-policy-margins-removed.md) |
| ADR-148 | ADR-148 — Приёмка проверяет, что агент импортирует СВОЮ цель так, как его запускает launchd | Accepted | [ADR-148](ADR-148-entrypoint-import-probe.md) |
| ADR-149 | ADR-149 — Оркестратор допускает 2 параллельных цикла (решение владельца 26.08) | Accepted | [ADR-149](ADR-149-orchestrator-two-concurrent-cycles.md) |
| ADR-145 (дубль) | ADR-145 (номер занят) → решение перенумеровано в ADR-149 | Superseded | [ADR-145 (дубль)](ADR-145-orchestrator-two-concurrent-cycles.md) |
| ADR-OWN-2026-07 (autoship) | Автономный авто-шип сайта под owner-gate (full auto-ship, owner-approved) | Accepted | [ADR-OWN-2026-07-autoship](ADR-OWN-2026-07-autoship.md) |
| ADR-OWN-2026-07 (lead-pings) | Мгновенный Telegram-пинг о крупных/B2B заявках (Q-OWN-16, one-shot key) | Accepted | [ADR-OWN-2026-07-lead-pings](ADR-OWN-2026-07-lead-pings.md) |
| ADR-OWN-2026-07 (repo-freeze) | Инцидент freeze-main-phase0: пуши восстановлены (bypass admin), запрет молчаливых изменений настроек репо/launchd | Accepted | [ADR-OWN-2026-07-repo-freeze-incident](ADR-OWN-2026-07-repo-freeze-incident.md) |
| ADR-OWN-2026-10-23 | ADR-OWN-2026-10-23 · Model-independent Studio OS and bounded verification | 2026-10-23 · Owner directive (приоритет и дизайн; реализация не заявлена) | [ADR-OWN-2026-10-23-model-independent-studio](ADR-OWN-2026-10-23-model-independent-studio.md) |
| ADR-OWN-2026-10-27 | TRADING-PROCESS-01: идеи trader-skill в бэклог; воспроизводимость, совокупный риск, версии намерений, свежесть, paper-эксперименты. Без live/смены лимитов. | 2026-10-27 · Owner intake / accepted for backlog; implementation not claimed | [ADR-OWN-2026-10-27-trader-patterns](ADR-OWN-2026-10-27-trader-patterns.md) |
| ADR-OWN-2026-10-28 | TELEGRAM-OWNER-UX-01: понятные сообщения владельцу в бэклог — смысл состояния, русская сводка, объединение по инциденту, earn-defi. Готово к работе, не начато. | 2026-10-28 · Owner intake / accepted for backlog; implementation not claimed | [ADR-OWN-2026-10-28-telegram-owner-ux](ADR-OWN-2026-10-28-telegram-owner-ux.md) |
| ADR-OWN-2026-10-28 | MAC-STORAGE-AUDIT-01: что заполняет диск Mac — аудит только чтением и план без очистки в бэклог. Бэклог, не начато. | 2026-10-28 · Owner intake / accepted for backlog; implementation not claimed | [ADR-OWN-2026-10-28-mac-storage-audit](ADR-OWN-2026-10-28-mac-storage-audit.md) |
| ADR-OWN-2026-07 (readiness-truth) | Публичный READY ⇔ реальный гейт ready:true И score ≥80 (вариант А) | Accepted | [ADR-OWN-2026-07-readiness-truth](ADR-OWN-2026-07-readiness-truth.md) |
| ADR-143 | ADR-143 — Владелец снял с себя ручные шаги: мердж и установку двух агентов делает агент | Accepted | [ADR-143](ADR-143-owner-authorised-self-merge-and-agent-install.md) |
| ADR-146 | ADR-146 — Агент закрывает карточки сам; уцелевшая половина запрета — «закрыто = проверено» | Accepted | [ADR-146](ADR-146-agent-may-close-cards.md) |
| ADR-145 | ADR-145 — «А прогон-то БЫЛ?» — сторож живости CI на PR | Accepted | [ADR-145](ADR-145-pr-ci-liveness-guard.md) |
| ADR-150 | ADR-150 — Интерлок номеров ADR стоит на КАЖДОЙ двери доставки, а не на одной из двух | Accepted | [ADR-150](ADR-150-adr-interlock-on-every-delivery-door.md) |
| ADR-151 | ADR-151 — Якорь сессии обязан умирать вместе с сессией: будильник живостью не считается | Accepted | [ADR-151](ADR-151-session-anchor-must-die-with-the-session.md) |
| ADR-152 | ADR-152 · Зеркало origin для локальных сессий | Принято | [ADR-152](ADR-152-origin-mirror-for-local-sessions.md) |
| ADR-153 | ADR-153 — Очередь была слепа по СОСТАВУ: «карточки нет в дереве» и «копия устарела» — один вопрос, а ответы были разные | Принято | [ADR-153](ADR-153-queue-blind-by-composition.md) |
| ADR-154 | ADR-154 · Контракты раньше оркестрации: паспорт агента и пакет передачи | Принято | [ADR-154](ADR-154-contracts-before-orchestration.md) |
| ADR-155 | ADR-155 — «origin закрыл раньше нас» — это не долг доставки | Accepted | [ADR-155](ADR-155-same-outcome-on-origin-is-not-delivery-debt.md) |
| ADR-157 | Пустой разбор артефакта — НЕ чтение: третий исход и молчание квитанции | Accepted | [ADR-157](ADR-157-hollow-parse-is-not-a-read.md) |
| ADR-158 | ADR-158 · Срок годности артефакта назначают две роли по согласованию | Принято | [ADR-158](ADR-158-slo-assigned-by-two-roles-in-agreement.md) |
| ADR-159 | ADR-159 · Доля Pendle остаётся, но нарушение названо вслух | Принято | [ADR-159](ADR-159-pendle-held-below-its-own-tvl-floor-named-aloud.md) |
| ADR-160 | ADR-160 · Срезанное защитами перераздаётся, но НЕ обратно в срезанные пулы | Принято | [ADR-160](ADR-160-redistribute-trimmed-capital-but-not-back-into-trimmed-pools.md) |
| ADR-161 | ADR-161 — Закрытие карточки моста требует РЯДА молчаливых прогонов, а не одного | Принято | [ADR-161](ADR-161-closing-a-card-needs-a-streak-not-one-silence.md) |
| ADR-162 | ADR-162 · Pendle-адаптер отказывает вместо ярлыка — ADR-159 пересмотрен | Принято | [ADR-162](ADR-162-pendle-tier-refusal-supersedes-adr-159.md) |
| ADR-163 | ADR-163 · Вытеснение ответа владельца — ОБЪЯВЛЕННЫЙ регистр, а не проза, и у сторожа есть для него третий исход | Принято | [ADR-163](ADR-163-superseded-owner-answer-is-a-declared-register.md) |
| ADR-164 | ADR-164 · Сверки контрактов подключены к живому сторожу: тревога — только противоречие, «не измерено» — строка отчёта | Принято | [ADR-164](ADR-164-b7-soft-outcomes-are-report-lines.md) |
| ADR-165 | ADR-165 — Знаменатель метрики 90 %: перепись внетировых и разметка Tier-B | Принято (замер) · решение по Tier-B ОТКРЫТО | [ADR-165](ADR-165-untiered-census-and-tier-b-writeoff.md) |
| ADR-166 | ADR-166 · Код возврата `orchestrator_queue.py list` отвечает на вопрос «состав измерен?» | Принято | [ADR-166](ADR-166-list-exit-code-answers-composition-measured.md) |
| ADR-209 | ADR-209 — Читатель без писателя: сторож приёмки карточек прожил сутки без единого предмета | Accepted | [ADR-209](ADR-209-a-reader-without-a-writer-is-an-ornament.md) |
| ADR-210 | ADR-210 — Регистр вытеснения обязан читаться на КАЖДОЙ двери, а не на одной из двух | Accepted | [ADR-210](ADR-210-superseded-register-must-be-read-at-every-door.md) |
| ADR-211 | ADR-211 — Цена сторожа выключила сторожа: сверка трекера с origin возвращается в умолчание | Accepted | [ADR-211](ADR-211-the-price-of-a-guard-switched-the-guard-off.md) |
| ADR-212 | ADR-212 · Числа сторожа просадки заработаны внутри собственного бара — сторож не тронут, пересчитаны ЧИСЛА | Accepted | [ADR-212](ADR-212-guardian-numbers-were-earned-inside-their-own-bar.md) |
| ADR-213 | ADR-213 · Объявить ФАЙЛ карточки — не значит взять карточку | Accepted | [ADR-213](ADR-213-announcing-a-card-file-is-not-claiming-the-card.md) |
| ADR-214 | ADR-214 · Инструкции — часть доставки, а не фон: `CLAUDE.md` и `.claude/rules/` возит синхронизатор | Accepted | [ADR-214](ADR-214-instructions-are-delivered-like-code.md) |
| ADR-220 | ADR-220 · Отказ моста «перенести нечем» — вердикт РЕШАТЕЛЯ, и у него есть срок годности | Accepted | [ADR-220](ADR-220-bridge-refusal-is-a-verdict-of-its-decider.md) |
| ADR-221 | ADR-221 · Карточка, открытая в прод-дереве и уже закрытая на origin, — не поручение и не вопрос | Accepted | [ADR-221](ADR-221-open-here-closed-on-origin.md) |
| ADR-223 | ADR-223 · Факт, записанный в объявлении, обязан доезжать до КАЖДОГО его потребителя | Accepted | [ADR-223](ADR-223-announce-cwd-reaches-every-consumer.md) |
| ADR-224 | ADR-224 — «Кто новее» у разошедшейся карточки ИЗМЕРЯЕТСЯ, а не объявляется неизмеримым | Accepted | [ADR-224](ADR-224-diverged-card-order-is-measurable.md) |
| ADR-225 | ADR-225 — Сторож голодания читает ОБЕ копии очереди, а статус «в работе» для него вопрос, а не ответ | Accepted | [ADR-225](ADR-225-starvation-guard-reads-both-copies-and-questions-in-progress.md) |
| ADR-226 | ADR-226 — У числа приёмки появился производитель, и его двойник назван вслух | Accepted | [ADR-226](ADR-226-acceptance-metric-gets-a-producer.md) |
| ADR-227 | ADR-227 — Два ключа протокола могут быть ОДНИМ предметом риска, и это измеряется | Accepted | [ADR-227](ADR-227-two-keys-one-contract.md) |
| ADR-228 | ADR-228 — «Взвод ещё не набрал дней» и «взвод недостижим» — разные ответы, и до сих пор их печатало одно слово | Accepted | [ADR-228](ADR-228-arming-reachability-is-a-measured-question.md) |
| ADR-AI1-004 | ADR-AI1-004: Машиночитаемый бизнес SPA (AI1 Stack) | Предложено (ждёт владельца) | [ADR-AI1-004](ADR-AI1-004.md) |
| ADR-167 | ADR-167 — Принудительное сокращение позиции в протоколе, переставшем наблюдаться | Принято | [ADR-167](ADR-167-forced-derisk-on-hard-stale-evidence.md) |
| ADR-168 | ADR-168 · Ограничитель частоты перекладок на живом пути | Принято | [ADR-168](ADR-168-churn-damper-on-the-live-path.md) |
| ADR-169 | ADR-169 · Обвал покрытия наблюдений — поломка производителя, а не сигнал бежать | Принято | [ADR-169](ADR-169-evidence-coverage-collapse-is-our-fault.md) |
| ADR-170 | ADR-170 · Надзор попадает в отчёт, который владелец и так читает | Принято | [ADR-170](ADR-170-oversight-lands-in-the-report-the-owner-already-reads.md) |
| ADR-171 | ADR-171 · Кэш-буфер сравнивается в центах: план РОВНО на 5 % — не нарушение | Принято | [ADR-171](ADR-171-cash-buffer-compared-in-cents.md) |
| ADR-172 | ADR-172 · Aave на Arbitrum: рынок переведён с USDC.e на нативный USDC | Принято | [ADR-172](ADR-172-aave-arbitrum-moves-to-native-usdc.md) |
| ADR-173 | ADR-173 · Ответ владельца по security-скану risk-гейта: чинить обе находки, каждую своим ADR | Принято | [ADR-173](ADR-173-risk-axes-and-tier-drift-fixed-in-tandem.md) |
| ADR-174 | ADR-174 · Предмет сторожа — ЖИВОЕ дерево; дефолт не смеет быть каталогом собственного кода | Принято | [ADR-174](ADR-174-guard-subject-is-the-live-tree-not-the-tree-it-runs-from.md) |
| ADR-175 | ADR-175 · «Как записан ответ» — не «какой ответ»: провенанс перестаёт звать человека | Принято | [ADR-175](ADR-175-provenance-of-an-answer-is-not-the-answer.md) |
| ADR-176 | ADR-176 · Пустое поле на origin — не отсутствующая СТРОКА: отказ вместо дописанного дубля | Принято | [ADR-176](ADR-176-empty-key-on-origin-is-not-an-absent-line.md) |
| ADR-177 | ADR-177 · Многовыборная карточка — своё состояние отсутствия кнопок, а не «мы не прочитали выбор» | Принято | [ADR-177](ADR-177-multiselect-card-is-its-own-buttonless-state.md) |
| ADR-178 | ADR-178 · Сторож журнала отправок называет ФАКТ; лекарство — только в своём домене | Принято | [ADR-178](ADR-178-buttonless-audit-states-fact-not-remedy.md) |
| ADR-179 | ADR-179 · Отметка времени — не решение: правило ADR-175 доезжает до ВТОРОГО сторожа | Принято | [ADR-179](ADR-179-a-timestamp-is-not-a-decision.md) |
| ADR-180 | ADR-180 · Бот записывает то вытеснение, которое производит САМ | Принято | [ADR-180](ADR-180-the-bot-records-the-supersede-it-causes.md) |
| ADR-181 | ADR-181 · Размещение простаивающего кэша — не перекладка | Принято | [ADR-181](ADR-181-placing-idle-cash-is-not-churn.md) |
| ADR-182 | ADR-182 · Точка безубыточности по капиталу: где может жить первый пилот на реальных деньгах | Принято | [ADR-182](ADR-182-pilot-breakeven-capital.md) |
| ADR-183 | ADR-183 · Решение владельца: пилот ждёт агента цены газа; целевая сеть пилота — Base | Принято | [ADR-183](ADR-183-pilot-waits-for-gas-agent-base-is-target.md) |
| ADR-184 | ADR-184 — Доска читает статус ТАМ ЖЕ, где его читает очередь; выключенная сверка называет себя | Accepted | [ADR-184](ADR-184-the-board-reads-status-where-the-cli-reads-it.md) |
| ADR-185 | ADR-185 — Часы анти-черна остаются тупыми до 2 сентября (решение владельца, вариант 1) | Accepted | [ADR-185](ADR-185-antichurn-clock-stays-dumb-until-sept-2.md) |
| ADR-186 | ADR-186 · Значение без автора — не ответ владельца: пятый исход сторожа доставки | Accepted | [ADR-186](ADR-186-an-unattributed-choice-is-not-an-owner-answer.md) |
| ADR-187 | ADR-187 · Агент `com.spa.dashboard` раздавал репозиторий в локальную сеть: инжест ответа владельца (вариант 1) | Accepted | [ADR-187](ADR-187-dashboard-served-the-repo-to-the-network.md) |
| ADR-188 | ADR-188 · Перенос следа обязан ЗАМЕНЯТЬ объявленное отсутствие на месте | Accepted | [ADR-188](ADR-188-carry-replaces-a-declared-absence-in-place.md) |
| ADR-189 | ADR-189 — Списание владельца сильнее машинной разметки: Tier-B подключён | Accepted | [ADR-189](ADR-189-owner-writeoff-outranks-the-measurement-markup.md) |
| ADR-190 | ADR-190 — Инженерного пути к 90 % нет: перепись, закрывающая вопрос | Принято (замер) · остаток ОТКРЫТ | [ADR-190](ADR-190-no-engineering-path-to-ninety.md) |
| ADR-191 | ADR-191 — Ответ владельца пишет только владелец: закрыта дверь ПИСАТЕЛЯ и назван маршрут починки | Accepted | [ADR-191](ADR-191-only-the-owner-writes-the-owners-answer.md) |
| ADR-192 | ADR-192 — «Виден» ≠ «дойдёт»: полнота очереди владельца меряется достижимостью, а не именем файла | Accepted | [ADR-192](ADR-192-visible-is-not-reachable.md) |
| ADR-193 | ADR-193 — Сетевая подрезка НЕ является приговором каждому протоколу на этой сети | Accepted | [ADR-193](ADR-193-a-network-cut-is-not-a-verdict-on-each-protocol.md) |
| ADR-194 | ADR-194 — У подтверждающего инструмента должна быть измерена СВОЯ цена ошибки | Accepted | [ADR-194](ADR-194-a-corroborating-instrument-needs-its-own-error-rate.md) |
| ADR-195 | ADR-195 — Список — это список ЧЕГО: инструмент обвинял модули в собственных выдуманных вызовах | Accepted | [ADR-195](ADR-195-a-list-is-a-list-of-what.md) |
| ADR-196 | ADR-196 — Плечо coverage краснело на СОБСТВЕННОМ контракте вызова: факт протокола ≠ служебная проводка | Accepted | [ADR-196](ADR-196-protocol-fact-vs-service-wiring.md) |
| ADR-197 | ADR-197 — У графы «не измерено» есть ПОЛ: ноль этим инструментом недостижим и целью не является | Accepted | [ADR-197](ADR-197-unmeasured-column-has-a-floor.md) |
| ADR-199 | ADR-199 — Третий исход был только у всего множества, но не у агента | Accepted | [ADR-199](ADR-199-the-third-outcome-was-only-for-the-whole-set.md) |
| ADR-201 | ADR-201 · Слив Aggressive-пакета: теневая книга 50/30/20 под постоянным CIO-надзором пропорций | Accepted | [ADR-201](ADR-201-aggressive-sleeve-shadow-with-cio-proportion-lever.md) |
| ADR-202 | ADR-202 · Тот же текст, слово в слово, стал вопросом владельцу второй раз — и это стоило решения | Accepted | [ADR-202](ADR-202-exact-repeat-of-an-owner-question-is-found-deterministically.md) |
| ADR-203 | ADR-203 · `notify` отчитывается о СВОЁМ прогоне, а не о жизни карточки | Принято | [ADR-203](ADR-203-notify-reports-this-run-not-the-cards-life.md) |
| ADR-200 | ADR-200 — Второй контейнер того же слова: вердикт «не измерено» стоял, причина молчала | Accepted | [ADR-200](ADR-200-the-second-container-of-the-same-word.md) |
| ADR-198 | ADR-198 — Третий деплой-вопрос получил вызывающего: «способен ли флот стартовать» больше не зависит от того, вспомнит ли о нём сессия | Accepted | [ADR-198](ADR-198-the-third-deployment-question-gets-a-caller.md) |
| ADR-204 | ADR-204 · Тождество актива — точное совпадение, а не «имя содержит» | Accepted | [ADR-204](ADR-204-asset-identity-is-exact-not-a-substring.md) |
| ADR-205 | ADR-205 — «Простоя нет» — это НАЗВАННЫЙ отказ, и он лежал в том же файле | Accepted | [ADR-205](ADR-205-no-idle-capital-is-a-named-refusal.md) |
| ADR-TEST | Smoke-test контура владельца (ENV_SETUP v3, Этап 8) | Accepted | [ADR-TEST](ADR-TEST-smoke-2026-07-15.md) |
| ADR-206 | ADR-206 · Сторож просадки не заходит на книгу, чья просадка мельче его собственного круга | Accepted | [ADR-206](ADR-206-guardian-does-not-enter-a-book-flatter-than-its-own-round-trip.md) |
| ADR-207 | ADR-207 · Сторожу расхождения фидов дана память: «мигает» и «живёт» — разные ответы | Accepted | [ADR-207](ADR-207-a-guard-without-memory-cannot-say-flickering-or-permanent.md) |
| ADR-208 | ADR-208 — Открытая карточка, чей собственный критерий уже выполнен, называется сторожем, а не находится случайно | Accepted | [ADR-208](ADR-208-otkrytaya-kartochka-s-vypolnennym-kriteriem.md) |
| ADR-215 | ADR-215 · Реестр решений — общая тетрадь, и запись в ней СТРОКА, а не заголовок | Accepted | [ADR-215](ADR-215-registry-index-is-shared-memory.md) |
| ADR-216 | ADR-216 · Отметка маячка из будущего читалась как «цикл не крутится» — и сторож перезапускал ЗДОРОВОГО бота | Accepted | [ADR-216](ADR-216-beacon-from-the-future-read-as-a-wedged-loop.md) |
| ADR-217 | ADR-217 — Вопрос владельцу, у которого ДВЕ рекомендации и усечённое тело | Accepted | [ADR-217](ADR-217-two-recommendations-and-a-truncated-question.md) |
| ADR-218 | ADR-218 · Эталонная планка семьи не докупает никого насильно: конвенция `cash` вместо `prorata` | Принято (владелец, Telegram 03.09) | [ADR-218](ADR-218-benchmark-does-not-force-buy-anybody.md) |
| ADR-219 | ADR-219 · Перенос закрытия карточки на ОБОГНАВШИЙ origin: доказательство покрытием, а не равенством | Accepted | [ADR-219](ADR-219-card-delivery-rebases-onto-an-ahead-origin.md) |
| ADR-229 | ADR-229 · Тир, объявленный не атрибутом, был невидим сторожу с «нулевым допуском» | Accepted | [ADR-229](ADR-229-class-tier-declared-without-the-attribute.md) |
| ADR-230 | ADR-230 · Ставка адаптера раскладывается на доход и эмиссию; сторож `apy_composition` | Accepted | [ADR-230](ADR-230-apy-composition-emission-vs-yield.md) |
| ADR-231 | ADR-231 · Приёмка §5 отвечала «100 %» по одной книге из трёх; популяция объявлена и измеряется | Accepted | [ADR-231](ADR-231-acceptance-population-was-one-book-of-three.md) |
| ADR-232 | ADR-232 · `spark_susds` — кредитный рынок, а не ферма SPK (решение владельца, вариант А) | Accepted | [ADR-232](ADR-232-spark-susds-is-the-credit-market.md) |
| ADR-233 | ADR-233 — Один ключ адаптера, разрешённый в ДВА РАЗНЫХ ПУЛА: личность становится записанной величиной | Accepted | [ADR-233](ADR-233-one-key-resolved-into-two-different-pools.md) |
| ADR-234 | ADR-234 · Буквенный пункт с точкой — владелец видел прозу вместо кнопок, а один раз ОДНУ кнопку из трёх | Accepted | [ADR-234](ADR-234-lettered-dot-options-lost-the-owners-choice.md) |
| ADR-235 | ADR-235 · Канал устаревания наблюдения получает потребителя: тревога ADR-167 наконец может прозвучать | Accepted | [ADR-235](ADR-235-evidence-staleness-channel-gets-a-consumer.md) |
| ADR-236 | ADR-236 — Пин размещает кэш тем, что УБИРАЕТ обречённую заявку, а не тем, что размораживает пул | Accepted | [ADR-236](ADR-236-pin-places-cash-by-removing-a-doomed-bid.md) |
| ADR-237 | ADR-237 — Ключ, ранжируемый ЛИТЕРАЛОМ, тоже имеет тождество; его просто никто не спрашивал | Accepted | [ADR-237](ADR-237-a-literal-priced-key-still-has-an-identity.md) |
| ADR-238 | ADR-238 — Подпись тождества была, и её выбрасывал потребитель | Accepted | [ADR-238](ADR-238-the-consumer-still-said-none.md) |
| ADR-243 | ADR-243 — «Costs»: стоимость перекладки заряжается литералом, а газ наблюдается живьём в той же единице | Accepted | [ADR-243](ADR-243-costs-charged-by-literal-observed-live.md) |
| ADR-244 | ADR-244 — Точность прогноза: измерена впервые; знак бывает противоположным, а величина съедает 99.8 % зазора гейта | Accepted | [ADR-244](ADR-244-forecast-accuracy-measured-first-time.md) |
| ADR-245 | ADR-245 — Исторический прогон: НЕсделанная перекладка обошла живую книгу, и разницу создал оборот, а не ставки | Accepted | [ADR-245](ADR-245-historical-replay-hold-beats-the-churning-book.md) |
| ADR-246 | ADR-246 — Audit trail: на девять вопросов владельца данные отвечают тремя | Accepted | [ADR-246](ADR-246-audit-trail-answers-three-of-nine.md) |
| ADR-247 | ADR-247 — Failure modes: путь решения отказывает на трёх деградациях из десяти, а на двух сам СОЗДАЁТ перекладку | Accepted | [ADR-247](ADR-247-failure-modes-refuse-on-three-of-ten.md) |
| ADR-248 | ADR-248 — Explainability: объяснение произносит два факта из восьми, а семь из восьми система уже знает | Accepted | [ADR-248](ADR-248-cio-explainability.md) |
| ADR-249 | ADR-249 — Kill switch: из трёх органов остановки у владельца ОДИН, и кнопка «Пауза» не ставит на паузу, а опустошает книгу | Accepted | [ADR-249](ADR-249-kill-switch-one-door-of-three.md) |
| ADR-250 | ADR-250 — Auto-execution limits: из двенадцати ограничений владельца полностью выполнены четыре, и половина остальных связывает НЕ на той поверхности, где их стали бы искать | Accepted | [ADR-250](ADR-250-auto-execution-limits-four-of-twelve.md) |
| ADR-251 | ADR-251 — Производителей цели ПЯТЬ, и у двух из них не стои́т ни одно из трёх ограничений владельца | Accepted | [ADR-251](ADR-251-target-producers-two-books-unguarded.md) |
| ADR-253 | ADR-253 — §46 выполнен по составу и НЕ выполнен по связи: все десять ступеней есть, но две производят в пустоту | Accepted | [ADR-253](ADR-253-component-map-two-stages-produce-into-a-void.md) |
| ADR-254 | ADR-254 — §48 исполняется, но его продукт не находят: единственное ослабление политики объяснено решением, которого нет в каноническом реестре | Accepted | [ADR-254](ADR-254-policy-change-proposals-live-outside-the-registry.md) |
| ADR-255 | ADR-255 — Post-trade verification сравнивает величину с самой собой | Accepted | [ADR-255](ADR-255-post-trade-verification-compares-a-value-to-itself.md) |
| ADR-256 | ADR-256 — Три ответа владельца: реестр решений, сторож номеров, подписывающие адаптеры | Accepted | [ADR-256](ADR-256-owner-answers-three-registry-and-signing-questions.md) |
| ADR-257 | ADR-257 — Независимого наблюдения исхода книги не существует, и машинерия, которая им была бы, ПОДСТАВЛЯЕТ число вместо отказа | Accepted | [ADR-257](ADR-257-no-independent-observation-of-the-book-exists.md) |
| ADR-260 | ADR-260 · Read-API `/api/btc-engine/*` для paper-трека BTC Signal Engine (отдельный репозиторий earn-defi) | Accepted | [ADR-260](ADR-260-btc-engine-read-api.md) |
| ADR-258 | ADR-258 — Подстановка вместо отказа: класс измерен деревом, и в книге она уносит числа отвергнутой аллокации | Accepted | [ADR-258](ADR-258-substitution-instead-of-refusal-reaches-the-book.md) |
| ADR-259 | ADR-259 · Объявленный продукт, который никто не вычисляет: измеритель ADR-257 не был подключён ни к одному вызову | Accepted | [ADR-259](ADR-259-declared-product-with-no-code-that-computes-it.md) |
| ADR-263 | ADR-263 — Вердикт контракта — про АРТЕФАКТ, а не про агента | Accepted | [ADR-263](ADR-263-contract-verdict-is-per-artifact-not-per-agent.md) |
| ADR-265 | ADR-265 · «В отчёте нет блока X» — находка только после того, как производитель отработал | принято · цикл #528 · 2026-09-08 | [ADR-265](ADR-265-absent-block-is-a-finding-only-after-the-producer-ran.md) |
| ADR-266 | ADR-266 — Третий исход у ВЕРДИКТ-ДАННЫХ: наблюдение — это ЗАМЕР, а не прогон моста | Accepted | [ADR-266](ADR-266-verdict-data-third-outcome-census.md) |
| ADR-267 | ADR-267 · Третий носитель вердикта — код возврата: перепись у ПОТРЕБИТЕЛЯ | Accepted | [ADR-267](ADR-267-exit-code-verdict-census.md) |
| ADR-268 | ADR-268 · «Пин невидим гейту финансирования» — симптом с ТРЕМЯ причинами, и они чинятся по-разному | Accepted | [ADR-268](ADR-268-pin-invisibility-decomposed-by-cause.md) |
| ADR-269 | ADR-269 · Проверяемость трека: сторож подключён, входы начисления архивируются, кривая пересчитывается из архива (перенос практики из earn-defi) | 2026-09-08 · Accepted | [ADR-269](ADR-269-track-verifiability-transfer-from-earn-defi.md) |
| ADR-270 | ADR-270 · Кастодиан сайта сравнивает APY «как с как»: трековый APY из цепочки, а не APY одного дня | 2026-09-09 · Accepted | [ADR-270](ADR-270-site-custodian-apy-leg-like-for-like.md) |
| ADR-271 | ADR-271 · Блокада взвода называет ГЕЙТ; связывает его на 11 днях из 21 собственный ход тени, а причина лежит в неустойчивости цели | 2026-09-09 · Accepted | [ADR-271](ADR-271-shadow-blockade-names-the-wrong-dial.md) |
| ADR-264 | ADR-264 — «Предмет сменился» — находка только после того, как производитель ПРОСРОЧИЛ такт | Accepted | [ADR-264](ADR-264-subject-drift-is-a-finding-only-after-the-producer-is-overdue.md) |
| ADR-262 | ADR-262 — «Файла нет на диске»: один вердикт на всех читателей, и объявление вместо вывода | Accepted | [ADR-262](ADR-262-one-absence-verdict-for-every-reader.md) |
| ADR-261 | ADR-261 — «Артефакта нет на диске» — находка только после того, как производитель отработал | Accepted | [ADR-261](ADR-261-absent-artifact-is-not-a-finding-until-the-producer-ran.md) |
| ADR-252 | ADR-252 — §45 выполняется, но держится НЕ сторожем: единственная проверка инварианта #3 слепа к двери, которой система пользуется | Accepted | [ADR-252](ADR-252-architecture-constraints-guard-blind-to-the-real-door.md) |
| ADR-242 | ADR-242 — «Marginal return»: ставка не зависит от нашего размера, и это ограничено политикой, а не удачей | Accepted | [ADR-242](ADR-242-marginal-return-is-bounded-by-policy-not-by-luck.md) |
| ADR-241 | ADR-241 — «Воспроизводим ли расчёт» перестал быть вопросом без ответчика | Accepted | [ADR-241](ADR-241-decision-reproducibility-measured.md) |
| ADR-240 | ADR-240 — Слой триггеров ребаланса отвечал «не надо» ИЗ ПУСТОТЫ | Accepted | [ADR-240](ADR-240-rebalance-triggers-answer-from-vacuum.md) |
| ADR-239 | ADR-239 — Два пространства имён сведены ЗАМЕРОМ: «один ли это рынок» стало разрешимым вопросом | Accepted | [ADR-239](ADR-239-pendle-identity-namespace-crossing.md) |
| ADR-272 | ADR-272 · ECON-10 меряет медиану ELIGIBLE-набора, а не медиану книги | 2026-09-09 · Accepted | [ADR-272](ADR-272-econ10-median-of-the-eligible-universe.md) |
| ADR-273 | ADR-273 · Дописывание в хеш-цепочку аудита — за O(1), а обрыв хвоста называется вслух | 2026-09-09 · Accepted | [ADR-273](ADR-273-hash-chain-append-is-o1.md) |
| ADR-274 | ADR-274 · Вселенная RT-05 — только то, что гейт может профинансировать | 2026-09-09 · Accepted | [ADR-274](ADR-274-rt05-universe-respects-the-tvl-floor.md) |
| ADR-275 | ADR-275 · Секрет не читается из рабочего дерева | 2026-09-09 · Accepted | [ADR-275](ADR-275-no-secret-is-read-from-inside-the-tree.md) |
| ADR-276 | ADR-276 · Пустое окно ≠ ноль работы: экономика цеха не имеет права рапортовать ложный ноль | 2026-09-09 · Accepted | [ADR-276](ADR-276-empty-window-is-not-zero-work.md) |
| ADR-277 | ADR-277 · Обнулённый срок go-live — это ОТВЕТ гейта, а не отсутствие входа | 2026-09-09 · Accepted | [ADR-277](ADR-277-a-null-target-date-is-an-answer.md) |
| ADR-278 | ADR-278 · Commit-reveal раскладки главной книги: хеш решения ложится на запись ДО виртуального исполнения, пакет раскрывается следующим циклом (перенос практики из earn-defi) | 2026-09-09 · Accepted | [ADR-278](ADR-278-book-commit-reveal.md) |
| ADR-284 | ADR-284 — Буква заказа отобрала восемь пар и НОЛЬ долларов: ярлык «в пределах маржи» отвечает верно не на тот вопрос | 2026-09-09 · Accepted | [ADR-284](ADR-284-ranking-tie-census-letter-of-the-order-answers-the-wrong-question.md) |
| ADR-279 | ADR-279 — Неустойчивость цели живёт не в недетерминизме, а в ФОРМЕ оптимизатора | 2026-09-09 · Accepted | [ADR-279](ADR-279-target-instability-is-the-optimizers-shape.md) |
| ADR-281 | ADR-281 · Публичные по построению строки — не учётные данные | 2026-09-09 · Accepted | [ADR-281](ADR-281-public-shapes-are-not-credentials.md) |
| ADR-282 | ADR-282 · Публичный верификатор не судит журнал, для которого у него нет рецепта | 2026-09-09 · Accepted | [ADR-282](ADR-282-verifier-never-judges-a-foreign-chain.md) |
| ADR-283 | ADR-283 · Скрипт, который правит запись о деньгах, ОБЪЯВЛЯЕТ режим, а не выводит его | 2026-09-09 · Accepted | [ADR-283](ADR-283-a-writing-script-must-declare-its-mode.md) |
| ADR-285 | ADR-285 · Граница «решай сам» / «спроси меня» проходит ПО ПРЕДМЕТУ | 2026-09-09 · Accepted | [ADR-285](ADR-285-owner-decision-boundary-by-subject.md) |
| ADR-286 | ADR-286 · Пакет решений владельца от 2026-09-09 (семь ответов кнопками) | 2026-09-09 · Accepted | [ADR-286](ADR-286-owner-decisions-2026-09-09.md) |
| ADR-287 | ADR-287 — Ничья оказалась РЕЖИМОМ, но журнал отвечает за три пары переписи, и единственная постоянная ничья объясняется тождеством пула | 2026-09-09 · Accepted | [ADR-287](ADR-287-tie-persistence-the-journal-answers-for-three-pairs-of-the-census.md) |
| ADR-288 | ADR-288 — Владелец разрешил подключить к опросу два пула, отвечающих живыми числами (вариант 1) | 2026-09-09 · Accepted | [ADR-288](ADR-288-owner-connects-two-live-answering-pools-to-the-poll.md) |
| ADR-290 | ADR-290 — Население журнала решений — это КНИГА, а не ранжированный набор; чинится одной строкой у писателя и переизлагает числа шести потребителей | 2026-09-09 · Accepted | [ADR-290](ADR-290-decision-journal-population-is-the-book-not-the-ranked-set.md) |
| ADR-291 | ADR-291 · Пакет решений владельца от 2026-09-09 (второй заход, четыре ответа) — и один вопрос, который кнопка похоронила | 2026-09-09 · Accepted | [ADR-291](ADR-291-owner-decisions-2026-09-09-second-package.md) |
| ADR-292 | ADR-292 · Balanced и Aggressive получают НАСТОЯЩИЙ бумажный трек, а не начисление по литералам | 2026-09-09 · Accepted | [ADR-292](ADR-292-real-paper-tracks-for-both-advisory-books.md) |
| ADR-295 | ADR-295 — Расширение записи решения не двигает ВЕРДИКТ, но двигает НАСЕЛЕНИЕ, на котором он посчитан | 2026-09-09 · Accepted | [ADR-295](ADR-295-decision-record-widening-does-not-move-the-verdict-but-moves-its-population.md) |
| ADR-293 | ADR-293 · Фактическая ставка на сайте берётся из снимка, а не печатается руками | 2026-09-09 · Accepted | [ADR-293](ADR-293-one-source-for-the-realized-rate-on-the-site.md) |
| ADR-294 | ADR-294 · Balanced и Aggressive: наблюдаемые ставки, списанные издержки, шов переоценки | 2026-09-09 · Accepted | [ADR-294](ADR-294-observable-rates-costs-and-marks-for-both-books.md) |
| ADR-296 | ADR-296 · Пин верификатора сверяется с ЖИВОЙ страницей, а не с локальным исходником | 2026-09-09 · Accepted | [ADR-296](ADR-296-verifier-pin-is-read-from-the-live-page.md) |
| ADR-297 | ADR-297 · Дни книг Balanced и Aggressive пересчитываются из сохранённых входов | 2026-09-09 · Accepted | [ADR-297](ADR-297-replay-for-both-advisory-books.md) |
| ADR-298 | ADR-298 · Ненаблюдаемая ставка начисляет ноль, а перекладка стоит денег | 2026-09-09 · Accepted | [ADR-298](ADR-298-literals-out-of-accrual-and-costs-charged.md) |
| ADR-299 | ADR-299 — `hit_rate` смещён систематически, и критерий взвода на нём не решается | 2026-09-10 · принято | [ADR-299](ADR-299-hit-rate-is-systematically-biased-and-the-criterion-is-undecidable.md) |
| ADR-300 | ADR-300 — Закрытие G1 поднимает НОЛЬ дней журнала: блокируют ноги, которые оркестратор уже спрашивает | 2026-09-10 · принято | [ADR-300](ADR-300-closing-g1-recovers-zero-journal-days-the-blockers-are-already-polled.md) |
| ADR-301 | ADR-301 · «APY за сегодня» у прогона ОДИН — и это заработанное, а не ожидаемое | 2026-09-10 · Accepted | [ADR-301](ADR-301-one-apy-for-today-per-run.md) |
| ADR-302 | ADR-302 — Ставки нет не потому, что фид молчал: 41 блокирующая пара из 44 — нога ВНЕ книг того дня | 2026-09-10 · принято | [ADR-302](ADR-302-the-missing-rate-is-a-transcription-hole-not-a-feed-outage.md) |
| ADR-303 | ADR-303 · Объявленный запрет действует независимо от пути загрузки | 2026-09-10 · Accepted | [ADR-303](ADR-303-declared-ban-is-enforced-on-both-load-paths.md) |
| ADR-304 | ADR-304 · Брошенные прогоны получают РАСПИСАНИЕ, а не палача | 2026-09-10 · Accepted | [ADR-304](ADR-304-orphaned-pytest-runs-get-a-schedule-not-an-executioner.md) |
| ADR-306 | ADR-306 — Стена записи связывает ТОЛЬКО ниже бюджета, и снять её предложенным расширением — не решённый вопрос | 2026-09-10 · принято | [ADR-306](ADR-306-the-record-wall-binds-only-downstream-of-the-budget.md) |
| ADR-305 | ADR-305 — У дыры переписи ЕСТЬ чем закрыться задним числом (40 пар из 41), но материал ДРУГОЙ ПРОБЫ — и без этого замера карточка владельцу была бы вопросом с неполным входом | 2026-09-10 · принято (ADVISORY, money-path не тронут) | [ADR-305](ADR-305-the-transcription-hole-has-material-but-not-of-the-same-grade.md) |
| ADR-307 | ADR-307 · Пересчёт обязан видеть ТО ЖЕ, что видело начисление | 2026-09-10 · Accepted | [ADR-307](ADR-307-replay-must-see-what-the-accrual-saw.md) |
| ADR-308 | ADR-308 — main красный четырнадцатые сутки из-за одной проверки, которая не отличала код от прозы | 2026-09-10 · принято | [ADR-308](ADR-308-ci-red-14-days-one-test-that-could-not-tell-code-from-prose.md) |
| ADR-309 | ADR-309 · Население записи решения — весь живой набор дня (ответ владельца «Б») | 2026-09-10 · Accepted | [ADR-309](ADR-309-the-record-population-is-the-live-set-owner-answer-b.md) |
| ADR-310 | ADR-310 — у утренней сводки появился прибор для утверждения, которое она сочиняла | 2026-09-10 · принято | [ADR-310](ADR-310-digest-gets-an-instrument-for-the-claim-it-was-inventing.md) |
| ADR-311 | ADR-311 — Проводка не объясняет НИ ОДНОЙ ноги, а «нет провенанса ВООБЩЕ» оказалось трёхдневной регрессией | 2026-09-10 · принято · 2026-09-10 · цикл #549 | [ADR-311](ADR-311-wiring-explains-nothing-and-the-missing-provenance-is-a-three-day-regression.md) |
| ADR-312 | ADR-312 — Минута снимка решает ЦЕЛЬ, а не только число; а потеря значения по дороге не измерена ни на одной паре | 2026-09-10 · принято | [ADR-312](ADR-312-the-minute-decides-the-target-not-just-the-number.md) |
| ADR-313 | ADR-313 — Ответ владельца «Вариант 2»: дописанные ставки СЧИТАЮТСЯ в hit_rate, но проба объявляется СМЕШАННОЙ | 2026-09-10 · принято (решение владельца) | [ADR-313](ADR-313-owner-answer-2-backfilled-rates-count-toward-hit-rate-on-a-mixed-sample.md) |
| ADR-314 | ADR-314 — Запись видит ОДИН снимок — снимок своего прогона; а её отметка есть отметка НАЧАЛА этого прогона, поэтому любой артефакт того же прогона выглядит новее | 2026-09-10 · принято | [ADR-314](ADR-314-the-record-stamp-is-the-cycle-start-so-every-same-run-artifact-looks-newer.md) |
| ADR-315 | ADR-315 — у каждого числа на сайте есть происхождение (идея владельца) | 2026-09-10 · принято | [ADR-315](ADR-315-every-number-on-the-site-has-a-provenance.md) |
| ADR-316 | ADR-316 · Знаменатель `hit_rate` стои́т на ОДНОМ выжившем прогоне дня, и вердикты остальных не существуют ни в одном носителе | 2026-09-10 · принято | [ADR-316](ADR-316-hit-rate-denominator-stands-on-one-surviving-run-of-the-day.md) |
| ADR-317 | ADR-317 · «19 из 19 красных» есть утверждение о СПИСКЕ автора: шесть координат ПРОВОДКИ пережили тот же набор | 2026-09-10 · принято | [ADR-317](ADR-317-a-mutation-battery-is-a-claim-about-the-authors-list-not-about-the-wiring.md) |
| ADR-318 | ADR-318 — Носитель ставок не свидетельствует НИ ОБ ОДНОМ дне знаменателя | 2026-09-10 · принято (ADVISORY — прибор, ничего не двигает) | [ADR-318](ADR-318-the-rate-carrier-cannot-testify-about-a-single-day-of-the-denominator.md) |
| ADR-319 | ADR-319 — У трейла есть ось прогонов и нет величины: 0 пар из 75, и отказ ОБРАТЕН соседнему | 2026-09-10 · принято (ADVISORY — прибор, ничего не двигает) | [ADR-319](ADR-319-the-trail-has-the-run-axis-and-not-the-quantity.md) |
| ADR-320 | ADR-320 — Ось, названная числом, не названа вовсе: сшивка состоялась и не перенесла ничего | 2026-09-11 · принято | [ADR-320](ADR-320-the-axis-named-by-a-number-was-not-named-at-all.md) |
| ADR-321 | ADR-321 — Независимый носитель прогонов, которого ветка не читала; и «ноль» оказался верным ровно там, где заказ и предполагал | 2026-09-11 · принято (ADVISORY — прибор, ничего не двигает) | [ADR-321](ADR-321-the-independent-run-carrier-nobody-read.md) |
| ADR-322 | ADR-322 — Граничный день полного кольцевого буфера есть НИЖНЯЯ ГРАНИЦА, а не счёт | 2026-09-11 · принято (ADVISORY — прибор, ничего не двигает) | [ADR-322](ADR-322-the-boundary-day-of-a-full-ring-buffer-is-a-floor.md) |
| ADR-323 | ADR-323 — Окно, которого никто не назвал: класс ADR-322 не одиночный, и второй носитель утверждал ПОЛНОТУ | 2026-09-11 · принято (ADVISORY — прибор + оговорка в сторожа; ничего не двигает) | [ADR-323](ADR-323-the-window-nobody-named.md) |
| ADR-324 | ADR-324 — CIO взведён: его вердикт решает перекладку книги | 2026-09-11 · принято — решение владельца | [ADR-324](ADR-324-cio-armed-its-verdict-decides-the-reshuffle.md) |
| ADR-325 | ADR-325 — Блок, читающий то, чего никто не объявил: схема стережёт 51 артефакт и молчит о 214 чтениях | 2026-09-11 · принято (ADVISORY — статическая перепись + храповик; ничего не двигает) | [ADR-325](ADR-325-the-block-that-reads-what-nobody-declared.md) |
| ADR-326 | ADR-326 — Корень, значивший у двух вызывающих разное: две переписи клали артефакт мимо читателя | 2026-09-11 · принято (починка проводки; ничего не двигает) | [ADR-326](ADR-326-the-root-that-meant-two-different-things.md) |
| ADR-327 | ADR-327 — Храповик, чьё население было случайностью имени переменной | 2026-09-11 · принято | [ADR-327](ADR-327-the-guard-whose-population-was-a-naming-accident.md) |
| ADR-328 | ADR-328 — CIO взведён на Balanced и Aggressive; во всех книгах перетасовку пропускают ОБА вердикта | 2026-09-11 · принято — решение владельца (продолжение ADR-324) | [ADR-328](ADR-328-cio-armed-on-balanced-and-aggressive-and-both-verdicts-gate.md) |
| ADR-329 | ADR-329 — Одно имя — один контракт: два ключа одного пула не обходят потолок на протокол | 2026-09-11 · принято | [ADR-329](ADR-329-one-name-one-contract-pool-aliases-cannot-bypass-the-cap.md) |
| ADR-330 | ADR-330 — Объявленный запрет реестра действует и в книгах Balanced/Aggressive | 2026-09-11 · принято | [ADR-330](ADR-330-registry-ban-reaches-the-sleeve-books.md) |
| ADR-331 | ADR-331 — Книга держит один ключ на пул: второе имя fluid убрано из книги при чтении | 2026-09-11 · ❌ ОТМЕНЁН в тот же день (код откачен, см. раздел «Отмена» в конце) | [ADR-331](ADR-331-the-book-holds-one-key-per-pool.md) |
| ADR-332 | ADR-332 — PT Pendle допустим только на основные стейблкоины | 2026-09-11 · принято — список предложен агентом, владелец: «бери делай все» | [ADR-332](ADR-332-pendle-pt-only-on-mainstream-stables.md) |
| ADR-333 | ADR-333 — Сторожа, чьё население выведено из ТЕКСТА соседа: сколько их и сколько слепы | 2026-09-11 · принято | [ADR-333](ADR-333-the-population-that-came-from-a-neighbours-text.md) |
| ADR-334 | ADR-334 — Владелец разрешил ОДИН пробный ход сверх бюджета оборота (инжест решения) | 2026-09-11 · принято (решение владельца зафиксировано) | [ADR-334](ADR-334-owner-grants-one-trial-move-above-the-turnover-budget.md) |
| ADR-335 | ADR-335 — Один пул — один ключ у всех писателей денежного пути (fluid, исполнение «одно имя — один контракт») | 2026-09-11 · принято | [ADR-335](ADR-335-one-pool-one-key-for-every-money-path-writer.md) |
| ADR-336 | ADR-336 — Пробный ход CIO: разовое разрешение владельца реализовано | 2026-09-11 · принято — реализация решения владельца ADR-334 (вариант 1) | [ADR-336](ADR-336-cio-trial-move-one-shot-grant-implemented.md) |
| ADR-337 | ADR-337 — Объявленный потолок тира T3 (15 %) впервые исполняется гейтом RiskPolicy | 2026-09-11 · принято (владелец: «бери делай все») | [ADR-337](ADR-337-the-declared-t3-total-cap-is-finally-enforced.md) |
| ADR-338 | ADR-338 — Утверждения, судящие о СТРУКТУРЕ соседа по ПОДСТРОКЕ её текста: сколько их и сколько обрываются | 2026-09-11 · принято | [ADR-338](ADR-338-assertions-that-judge-a-structure-by-a-substring.md) |
| ADR-339 | ADR-339 — Путь решения о сделке живёт по часам цикла, а не по настенным | 2026-09-11 · принято (владелец: «почини демпфер с часами тоже») | [ADR-339](ADR-339-the-decision-path-runs-on-the-cycle-clock.md) |
| ADR-340 | ADR-340 — Шаг псевдонимов пула судит ключ под тиром RiskPolicy, а не своим литералом | 2026-09-11 · принято (агент, ADR-285: не деньги, не публичные числа, обратимо; поправка к собственному шагу ADR-329/335) | [ADR-340](ADR-340-the-alias-gate-judges-a-key-under-the-policy-tier.md) |
| ADR-341 | ADR-341 — «Трогает execution» в паспорте конвейера судится структурой, а не подстрокой | 2026-09-11 · принято (агент, ADR-285: сторож паспортов, не деньги и не публичные числа) | [ADR-341](ADR-341-execution-touch-is-judged-by-structure-not-substring.md) |
| ADR-342 | ADR-342 — Пять скриптов без вызывающего: разобраны поимённо, база храповика не выросла | 2026-09-11 · принято (агент, ADR-285: инструменты и сторожа, не деньги и не публичные числа) | [ADR-342](ADR-342-five-unwired-scripts-resolved-by-measurement.md) |
| ADR-343 | ADR-343 · Откуда пришло содержимое стога: сосед под корнем или байты самого теста | 2026-09-11 · принято | [ADR-343](ADR-343-where-the-haystack-content-came-from.md) |
| ADR-344 | ADR-344 — Инвариант #17 исчез из конституции на 16 суток; дверь доставки теперь видит и её | 2026-09-11 · принято (агент, ADR-285: восстановление утраченного правила и сторож к нему) | [ADR-344](ADR-344-invariant-17-vanished-from-the-constitution.md) |
| ADR-345 | ADR-345 — Баланс без личности — это ОТКАЗ, а не правдоподобное число | 2026-09-11 · принято (агент, ADR-285: исполнительный код на бумажной стадии; капитал не двигается, | [ADR-345](ADR-345-a-balance-without-identity-is-a-refusal-not-a-mock.md) |
| ADR-346 | ADR-346 — Доставка унесла проводку, которой автор не видел: «я удалил» ≠ «я не видел» | 2026-09-12 · принято (агент, ADR-285: восстановление утраченного кода и сторож к нему) | [ADR-346](ADR-346-a-delivery-lost-a-wiring-nobody-had-seen.md) |
| ADR-347 | ADR-347 — Крах сторожа был предъявлен сессии как его НАХОДКА | 2026-09-12 · Accepted | [ADR-347](ADR-347-a-crashed-guard-was-reported-as-its-finding.md) |
| ADR-348 | ADR-348 — Якорь времени на импорте: бомба с фитилём «длительность прогона» | 2026-09-12 · принято | [ADR-348](ADR-348-import-time-clock-anchor-is-a-bomb-fused-by-run-length.md) |
| ADR-349 | ADR-349 — Мнимая вторая запись о деньгах снята: «готов к live» больше не печатается при нуле наблюдений | 2026-09-12 · принято | [ADR-349](ADR-349-the-phantom-second-record-of-money-is-removed.md) |
| ADR-350 | ADR-350 — Второй записи о книге нет за 63 из 81 доказанного дня, и теперь это меряется каждый цикл | 2026-09-12 · принято | [ADR-350](ADR-350-the-book-has-no-second-record-for-63-of-81-evidenced-days.md) |
| ADR-351 | ADR-351 — Сторож утраты имён не смотрел на оболочку, и мой же пуш откатил чужую правку через шесть часов после того, как я написал про этот класс | 2026-09-12 · принято | [ADR-351](ADR-351-the-name-loss-guard-did-not-look-at-shell.md) |
| ADR-352 | ADR-352: Перепись дверей доставки — посылка заказа была получена подсчётом вхождений и оказалась неверна в обе стороны | 2026-09-12 · Accepted | [ADR-352](ADR-352-delivery-door-census.md) |
| ADR-353 | ADR-353 — База стража перезаписи — это HEAD, а не то, что видел автор | 2026-09-12 · Принято | [ADR-353](ADR-353-the-base-is-head-not-what-the-author-saw.md) |
| ADR-354 | ADR-354 · Две системы координат внутри одного зова git: перепись населения и наблюдаемая слепота | 2026-09-12 · принято | [ADR-354](ADR-354-two-coordinate-systems-in-one-git-call.md) |
| ADR-355 | ADR-355 — Перепись зовов git в shell по ИСТОЧНИКУ каталога запуска | 2026-09-12 · принято | [ADR-355](ADR-355-shell-git-calls-by-cwd-source.md) |
| ADR-356 | ADR-356 — «Каталог задан» и «каталог тот самый» — разные утверждения | 2026-09-12 · Принято (прибор наблюдения, money-path не трогает) | [ADR-356](ADR-356-shell-cd-target-is-it-the-repo-root.md) |
| ADR-357 | ADR-357 · Пакет решений владельца от 2026-09-12 (три вопроса автоторговли, старт трека двух книг, установка по числам сайта) | 2026-09-12 · Accepted | [ADR-357](ADR-357-owner-decisions-2026-09-12.md) |
| ADR-358 | ADR-358 — Потолок суммы одного хода и дневной бюджет оборота: две ручки из ответа владельца | 2026-09-12 · принято | [ADR-358](ADR-358-dollar-cap-and-daily-turnover-budget.md) |
| ADR-359 | ADR-359 — Незнакомый тир — отказ, а не потолок T2; и правило разбора тира стало ОДНИМ | 2026-09-12 · принято | [ADR-359](ADR-359-unknown-tier-is-a-refusal-and-the-tier-rule-is-one.md) |
| ADR-360 | ADR-360 — ЛИЧНОСТЬ репозитория, в который ведёт доказанный `cd`: 33 из 33, но основание у 23 не путешествует | 2026-09-12 · Accepted | [ADR-360](ADR-360-repo-identity-of-the-cd-target.md) |
| ADR-361 | ADR-361 — `origin/main` есть КЭШ, а не вопрос к серверу: 0 из 12, и две оси доказательства РАСХОДЯТСЯ | 2026-09-12 · Accepted | [ADR-361](ADR-361-remote-tracking-ref-is-a-cache.md) |
| ADR-362 | ADR-362 — `origin/main` из python: 0 из 53, и решает это ЧУЖОЙ `fetch` | 2026-09-12 · принято | [ADR-362](ADR-362-python-git-ref-provenance.md) |
| ADR-364 | ADR-364 — Приёмка G1 приказа «Portfolio CIO»: доля капитала на наблюдённых числах измерена ВПЕРВЫЕ, и она 100 % — а второй артефакт о тех же деньгах спорит | 2026-09-13 · Accepted | [ADR-364](ADR-364-capital-observability-census-g1-acceptance.md) |
| ADR-365 | ADR-365 — Одна витрина на все числа сайта: недельный такт, годовая форма, два источника за ней | 2026-09-13 · принято | [ADR-365](ADR-365-one-shelf-for-every-site-number.md) |

| ADR-366 | ADR-366 — Знаменатель `hit_rate` стои́т на 100 % наблюдённого капитала ПО ПОСТРОЕНИЮ: критерий взвода ни разу не оценивался в режиме деградации входов | 2026-09-13 · Accepted | [ADR-366](ADR-366-capital-observability-over-history.md) |
| ADR-367 | ADR-367 — «`lsof -d 1` отвязан ⇒ вердикт не прочитает никто» НЕВЕРНО: это свойство захвата pytest, а не судьбы прогона | 2026-09-13 · Accepted | [ADR-367](ADR-367-fd1-unlinked-is-a-property-of-pytest-capture.md) |
| ADR-368 | ADR-368 — Отказы по слепоте входов СОРАЗМЕРНЫ: 91.48 % предложенного оборота держалось на ненаблюдённой ноге, и «$200-случая» в истории нет ни одного | 2026-09-13 · Accepted | [ADR-368](ADR-368-unobserved-turnover-dependence.md) |
| ADR-369 | ADR-369 — Развилка приказа разрешена замером и НЕ в одну сторону: $185 000 из $195 000 слепого оборота поднимает НАШ код, $10 000 не поднимает никогда | 2026-09-13 · Accepted | [ADR-369](ADR-369-unobserved-leg-remedy-class.md) |
| ADR-371 | ADR-371 — Сколько ДНЕЙ вернул бы знаменателю `hit_rate` рычаг писателя (заказ #591/G8) | 2026-09-13 · Принято (ADVISORY, money-path не тронут) | [ADR-371](ADR-371-hit-rate-denominator-recovery.md) |
| ADR-370 | ADR-370 · Три решения владельца от 2026-09-13: критерий C012, скрипт живого агента, три страницы сайта | 2026-09-13 · Accepted · **Дата:** 2026-09-13 | [ADR-370](ADR-370-owner-decisions-2026-09-13.md) |
| ADR-372 | ADR-372 — Недельный такт дошёл до страниц; и четыре заголовка печатали подстановку буквально | 2026-09-13 · принято | [ADR-372](ADR-372-weekly-cadence-reached-the-pages-and-titles-printed-a-placeholder.md) |
| ADR-373 | ADR-373 — Двадцать четыре страницы читают витрину, а не дневной снимок | 2026-09-13 · принято | [ADR-373](ADR-373-every-page-reads-the-weekly-shelf.md) |
| ADR-374 | ADR-374 — Прибор без следа: «запускался ли он» было неотвечаемым вопросом | 2026-09-13 · принято | [ADR-374](ADR-374-an-instrument-without-a-trace-cannot-be-asked-whether-it-ran.md) |
| ADR-375 | ADR-375 — Раскладка слепого оборота по правилу ОДНОГО форвардного дня (заказ #592/G9) | 2026-09-13 · принято, замер 2026-09-13 | [ADR-375](ADR-375-remedy-class-single-forward-day.md) |
| ADR-376 | ADR-376 — Объявить ступень и не позвать её: четыре прибора ряда G6→G9 не запускались ни разу | принято, замер 2026-09-13 (цикл #595) | [ADR-376](ADR-376-declared-stage-was-never-called.md) |
| ADR-377 | ADR-377 — Носитель гасят, а не берут в работу: правило приёмки ловило три разных случая как один | 2026-09-14 · принято | [ADR-377](ADR-377-a-carrier-is-retired-not-taken-into-work.md) |
| ADR-378 | ADR-378 — Дешёвый рычаг `writer_universe` поднимает ПОЛОВИНУ: потолок доказанно пуст на $100 000 | принято | [ADR-378](ADR-378-writer-universe-lever-floor.md) |
| ADR-379 | ADR-379 — Кого мы опрашиваем и не слышали ни разу: это ИМЯ, а не класс | принято | [ADR-379](ADR-379-polled-never-observed-census.md) |
| ADR-380 | ADR-380 — Честная цена починки молчащей ноги: в ДНЯХ, а не в долларах (заказ #598/G12) | Принято (ADVISORY, money-path не тронут) | [ADR-380](ADR-380-silent-leg-day-price.md) |
| ADR-381 | ADR-381 — Доля населения критерия: считать по ПОЛУ, а не по потолку (заказ #599/G13) | Принято (ADVISORY, money-path не тронут) | [ADR-381](ADR-381-criterion-population-floor.md) |
| ADR-382 | ADR-382 — Значение критерия ДВУМЯ границами: отдача починок, а не их цена (заказ #600/G14) | Принято (ADVISORY, money-path не тронут) | [ADR-382](ADR-382-criterion-value-interval.md) |
| ADR-383 | ADR-383 — Единственный ACT за 40 дней стёрт из журнала позднейшим прогоном того же дня (заказ #601/G15) | принято | [ADR-383](ADR-383-act-day-erased-from-the-journal.md) |
| ADR-384 | ADR-384 — Цена отмены двойного счёта: ключ, который переименовывает дату, и правило, живущее второй копией у читателя | принято (замер), 2026-09-14, цикл #602 | [ADR-384](ADR-384-run-identity-key-price.md) |
| ADR-385 | ADR-385 — Цена третьей половины рычага: наследники считают СТРОКИ, а не состояние | принято | [ADR-385](ADR-385-heir-all-rows-price.md) |
| ADR-386 | ADR-386 — Цена починки СУДЬИ отдельно от остальных: сегодня ноль, ёмкость 15, и ни один из пятнадцати не окупается (заказ #605/G18) | принято | [ADR-386](ADR-386-judge-alone-price.md) |
| ADR-387 | ADR-387 — Цена починки адаптеров: сегодня НОЛЬ ACT-дней, на ёмкости десять, и починка эта НЕ адаптерная (заказ #606/G19) | принято | [ADR-387](ADR-387-adapter-repair-price.md) |
| ADR-388 | ADR-388 — Ни одно состояние гейтов не закрывает критерий №3, и держит знак ВЫГОДА, а не цена и не горизонт (заказ #607/G20) | принято | [ADR-388](ADR-388-criterion-sign-price.md) |
| ADR-389 | ADR-389 — «Наблюдённой цены хода» не существует: записанное число есть выход модели, и знак критерия держит ОДНА её константа (заказ #608/G21) | принято | [ADR-389](ADR-389-move-cost-composition-price.md) |
| ADR-390 | ADR-390 — Цена операции, которой не было: чем платит критерий за своп, которого нет | принято | [ADR-390](ADR-390-swap-existence-price.md) |
| ADR-391 | ADR-391 — Цена двух разрывов: ключ без актива и ноль, неотличимый от отсутствия | ACCEPTED — замер, ADVISORY. Ни один порог, гейт и файл `data/` не тронут. | [ADR-391](ADR-391-asset-registry-gap-price.md) |
| ADR-392 | ADR-392 — Пакет ответов владельца 15.09: три решения по судье и журналу решений | ACCEPTED | [ADR-392](ADR-392-owner-answers-2026-09-15.md) |
| ADR-393 | ADR-393 — Записанный ноль в цене хода — ЦЕНА, а не её отсутствие (ответ владельца 15.09, вариант 1) | принято | [ADR-393](ADR-393-recorded-zero-is-a-price.md) |
| ADR-394 | ADR-394 — Четыре красных сторожа на main, и каждый по своей причине | 2026-09-15 · принято | [ADR-394](ADR-394-four-red-guards-on-main-each-for-its-own-reason.md) |
| ADR-395 | ADR-395 — Журнал решений: ключ ПРОГОНА, и вторая копия правила у читателя | Accepted | [ADR-395](ADR-395-decision-journal-run-identity.md) |
| ADR-396 | ADR-396 — Перепись читателей журнала: одна причина «не измерено» была шестью, а вердикт единственному схлопывающему читателю был монетой | Accepted | [ADR-396](ADR-396-journal-reader-census-causes.md) |
| ADR-397 | ADR-397 — Класс инварианта #17 закрыт в собственных приборах лестницы CIO, и у него появилась проба приёмки | Accepted | [ADR-397](ADR-397-absent-observation-class-closed-in-the-cio-instruments.md) |
| ADR-398 | ADR-398 · Второй артефакт наблюдает TVL двух крупнейших книг, а не штампует литерал | Accepted | [ADR-398](ADR-398-second-artifact-tvl-observed-not-literal.md) |
| ADR-399 | ADR-399 — Перепись читателей журнала дошла до HTTP-маршрутов, и своя же проверка нашла у неё слепоту потише | Accepted | [ADR-399](ADR-399-journal-reader-census-reaches-http-routes.md) |
| ADR-400 | ADR-400 · Кнопки владельцу гейтит УМЕНИЕ бота, а не его пульс в минутах; неизвестный глагол не стирает вопрос | Accepted | [ADR-400](ADR-400-buttons-survive-the-bot-restart-window.md) |
| ADR-401 | ADR-401 — Часы прогона доходят до читателя журнала: цена приёма была уплачена, не хватало проводки | Accepted | [ADR-401](ADR-401-census-clock-reaches-the-reader.md) |
| ADR-402 | ADR-402 — Агент правит свой свод правил сам, но только вместе со следом | 2026-09-16 · принято | [ADR-402](ADR-402-self-commit-of-the-rulebook-comes-with-its-trace.md) |
| ADR-403 | ADR-403 · Вердикт owner-gate — из отчёта СВОЕГО запуска; код 2 — только вердикт | 2026-09-16 · Accepted | [ADR-403](ADR-403-owner-gate-verdict-is-this-runs-report-exit-2-is-only-the-verdict.md) |
| ADR-404 | ADR-404 — HTTP-ветвь переписи: часы закреплены у двери, ответ-объект читается по телу | Accepted | [ADR-404](ADR-404-http-census-clock-pin-and-response-body.md) |
| ADR-405 | ADR-405 — HTTP-ветвь переписи: момент выдачи узнаётся по окну зова | Accepted | [ADR-405](ADR-405-http-census-call-moment-by-call-window.md) |
| ADR-406 | ADR-406 — Двери часов, связанные на импорте: их ТРИ, и у двух из трёх параметра не существует вовсе | Accepted | [ADR-406](ADR-406-import-bound-clock-doors-in-the-python-readers.md) |
| ADR-407 | ADR-407 — Мандат автономии продлён БЕЗ СРОКА, и «без срока» стало выразимо кодом | Accepted | [ADR-407](ADR-407-autonomy-mandate-open-ended.md) |
| ADR-408 | ADR-408 — Цена закрытия двери часов: дверей три, а закрывать можно две | Accepted | [ADR-408](ADR-408-price-of-closing-a-clock-door.md) |
| ADR-409 | ADR-409 — Две дешёвые двери закрыты, координата стала личностной, у числа появился такт | Accepted | [ADR-409](ADR-409-two-cheap-doors-closed-identity-and-the-tact.md) |
| ADR-410 | ADR-410 — Перепись личности списков: нынешний список имён промахивается мимо трёх четвертей | Accepted | [ADR-410](ADR-410-list-identity-census-the-whitelist-misses-three-quarters.md) |
| ADR-411 | ADR-411 — У переписи личности списков появились ЧИТАТЕЛЬ и настоящий производитель | Accepted | [ADR-411](ADR-411-list-identity-census-gets-a-reader-and-a-real-producer.md) |
| ADR-415 | ADR-415 — Перепись гейтов такта: где живёт решение «пора ли производить» | Accepted | [ADR-415](ADR-415-tact-gate-census-where-the-due-decision-lives.md) |
| ADR-416 | ADR-416 — Гейт такта переехал в производителя; и рядом нашлась ВТОРАЯ КОПИЯ правила приёмки | Accepted | [ADR-416](ADR-416-tact-gate-moves-into-the-producer-and-a-second-copy-of-the-acceptance-rule.md) |
| ADR-417 | ADR-417 — Одно правило, две копии: перепись пар «исполнитель × сторож» | Accepted | [ADR-417](ADR-417-one-rule-two-copies-census-executor-versus-guard.md) |
| ADR-418 | ADR-418 — Форма починки второй копии правила измеряется, а не угадывается | Accepted | [ADR-418](ADR-418-remedy-form-of-a-second-copy-is-measured-not-guessed.md) |
| ADR-419 | ADR-419 · Второй свидетель ПОВЕДЕНЧЕСКИЙ, а зонд мерит ВРЕД, а не независимость | Accepted | [ADR-419](ADR-419-second-witness-is-behavioural-and-the-probe-measures-harm-not-independence.md) |
| ADR-420 | ADR-420 · Зелёный сторож на ОПУСТОШЁННОМ входе — это класс, и он измерен | Accepted | [ADR-420](ADR-420-a-guard-green-on-an-emptied-input-is-a-class-and-it-is-measured.md) |
| ADR-421 | ADR-421 · Перечень, собранный ВЫЗОВОМ, пустеет без единой правки — и вопрос не «достижима ли пустота», а «что сторож при ней ДЕЛАЕТ» | Accepted | [ADR-421](ADR-421-a-list-built-by-a-call-empties-without-any-edit.md) |
| ADR-422 | ADR-422 · У headless-запуска Claude не было срока, а у его потомков — владельца | Accepted | [ADR-422](ADR-422-claude-worker-timeout-and-process-ownership.md) |
| ADR-423 | ADR-423 · Локальные LLM и провайдер-роутер — ОТЛОЖЕНЫ; Claude Subscription остаётся единственным провайдером | Accepted | [ADR-423](ADR-423-local-llm-and-provider-router-deferred.md) |
| ADR-424 | ADR-424 · Прогон опроверг статику у КАЖДОГО входа-файла, а 43 % невычисленных путей оказались лесами, а не входами | Accepted | [ADR-424](ADR-424-a-behavioural-probe-refutes-the-static-door-and-the-uncomputed-paths-are-mostly-scaffolding.md) |
| ADR-425 | ADR-425 · Четыре слепых сторожа из девяти никогда не были слепыми: их тест был ПРОПУЩЕН, а признак у пропуска и у слепоты один | Accepted | [ADR-425](ADR-425-four-of-nine-blind-guards-were-never-blind-their-test-was-skipped.md) |
| ADR-426 | ADR-426 · Вопрос «бежал ли собственный тест строки» задан ВСЕМУ населению, и журнал зонда перемерен целиком | Accepted | [ADR-426](ADR-426-the-own-test-question-goes-to-the-whole-population-and-the-ledger-is-remeasured.md) |
| ADR-427 | ADR-427 · Общая проводка прогонов резала голову перечня и не говорила об этом ничего | Accepted | [ADR-427](ADR-427-the-shared-runner-cut-the-head-off-a-list-and-said-nothing.md) |
| ADR-428 | ADR-428 — Вторая проводка режет СВОЕЙ РУКОЙ, и сторона разреза здесь не свойство, а поле | Accepted | [ADR-428](ADR-428-the-second-wiring-cuts-by-hand-and-the-side-of-the-cut-is-a-field.md) |
| ADR-429 | ADR-429 — Дверь, считающая длину КОМАНДЫ, дверью не является: правило сужено у ИСТОЧНИКА | Accepted | [ADR-429](ADR-429-a-door-that-counts-the-command-is-not-a-door.md) |
| ADR-430 | ADR-430 — «Одна копия» было не ответом: перепись молчит о паре, которую не видит ПО ПОСТРОЕНИЮ | Accepted | [ADR-430](ADR-430-the-silence-of-a-census-about-a-pair-it-cannot-see.md) |
| ADR-431 | ADR-431 — Ноль пересечения осей был формой ВОПРОСА, а не свойством дерева | Accepted | [ADR-431](ADR-431-a-zero-that-was-the-shape-of-the-question.md) |
| ADR-414 | ADR-414 — У прибора «двери часов» появились производящий ВЫЗОВ и ЧИТАТЕЛЬ; рука убрана с его такта | Accepted | [ADR-414](ADR-414-clock-doors-instrument-gets-a-producing-call-and-a-reader.md) |
| ADR-413 | ADR-413 — Два цикла построили одно и то же, а карточка приказа была закрыта по чужому телу | Accepted | [ADR-413](ADR-413-two-cycles-built-the-same-thing-and-the-card-was-closed-on-the-wrong-body.md) |
| ADR-412 | ADR-412 — Наблюдение, поставленное на 25.09, не умело назвать звавшего | Accepted | [ADR-412](ADR-412-the-planned-observation-could-not-name-its-caller.md) |
| ADR-432 | ADR-432 — Право чинить спрашивалось у ОДНОЙ поверхности решения из двух | Accepted | [ADR-432](ADR-432-the-right-to-fix-was-asked-of-one-surface-out-of-two.md) |
| ADR-433 | ADR-433 — Население поверхностей решения ОБЪЯВЛЕНО; а сверка величины шла ТЕКСТОМ | Accepted | [ADR-433](ADR-433-the-population-of-decision-surfaces-is-declared-and-the-comparison-was-textual.md) |
| ADR-434 | ADR-434 — Поверхность решения объявляется ИМЕНЕМ, а широкий абзац не читал никто | Accepted | [ADR-434](ADR-434-a-decision-surface-can-be-declared-by-name-and-the-wide-paragraph-was-never-read.md) |
| ADR-435 | ADR-435 — Цена широкого абзаца — тринадцать пар, и держит её ОДНА таблица | Accepted | [ADR-435](ADR-435-the-cost-of-the-wide-paragraph-is-thirteen-pairs-and-one-table-holds-it.md) |
| ADR-436 | ADR-436 — «Одна таблица» оказалась свойством выборки: форма живёт и вне объявленного канала | Accepted | [ADR-436](ADR-436-one-table-was-a-property-of-the-sample-not-the-repository.md) |
| ADR-437 | ADR-437 — Канал имени был ОДНОЯЗЫЧНЫМ, а репозиторий двуязычен: вне объявленного канала стои́т третья копия порога | Accepted | [ADR-437](ADR-437-the-naming-channel-was-monolingual-and-the-repository-is-not.md) |
| ADR-438 | ADR-438 — Одноязычие НЕ свойство каждого свидетеля имени: оно кусается там, где у спрашиваемого токена есть слово в языке | Accepted | [ADR-438](ADR-438-monolinguality-is-not-a-property-of-every-witness-of-a-name.md) |
| ADR-439 | ADR-439 — Точность двуязычного канала имени есть ИНТЕРВАЛ, а размечающее правило читает ИМЯ, а не текст | Accepted | [ADR-439](ADR-439-precision-of-the-bilingual-name-channel-is-an-interval-and-the-rule-reads-the-name.md) |
| ADR-440 | ADR-440 — Кандидат «двух токенов» удаляет население, а не решает его, и стоит трёх настоящих пар из четырёх | Accepted | [ADR-440](ADR-440-the-two-token-candidate-deletes-the-population-instead-of-deciding-it.md) |
| ADR-441 | ADR-441 — Третий свидетель, читающий АБЗАЦ, существует; у действующих свидетелей правила частоты ошибки не мерил никто | Accepted | [ADR-441](ADR-441-a-third-witness-that-reads-the-paragraph-exists-and-the-incumbents-were-never-measured.md) |
| ADR-442 | ADR-442 — Цена допуска свидетеля платится в ПАРАХ, и сама база этой цены никем не мерена | Accepted | [ADR-442](ADR-442-the-price-of-admitting-a-witness-is-paid-in-pairs-and-the-base-of-that-price-was-never-measured.md) |
| ADR-443 | ADR-443 — Каждый читатель переписи берёт СВОЮ базу, а одно слово называет две из них | Accepted | [ADR-443](ADR-443-each-reader-of-the-census-takes-a-different-base-and-one-word-names-two-of-them.md) |
| ADR-444 | ADR-444 — Реестр читателей ОБЪЯВЛЕН, а единственный читатель, доносящий перепись до оркестратора, соседу невидим | Accepted | [ADR-444](ADR-444-the-reader-registry-is-declared-and-the-one-reader-that-reaches-the-orchestrator-is-invisible-to-the-neighbour.md) |
| ADR-445 | ADR-445 — Невидимый потребитель не аномалия одной переписи, а ФОРМА шага 0-офис | Accepted | [ADR-445](ADR-445-the-invisible-consumer-is-not-an-anomaly-of-one-census-it-is-the-shape-of-the-office-step.md) |
| ADR-447 | ADR-447 — У остатка была цена и был бюджет, и не было ЧАСТНОГО | Accepted | [ADR-447](ADR-447-the-remainder-had-a-price-and-a-budget-and-no-quotient.md) |
| ADR-448 | ADR-448 — У отказа была ПРИЧИНА, и причину не мерил никто | Accepted | [ADR-448](ADR-448-the-refusal-had-a-reason-and-the-reason-was-never-measured.md) |
| ADR-449 | ADR-449 — Хвост координаты не есть имя поля: разница правил измерена, и она ноль по НАЗВАННОЙ причине | Accepted | [ADR-449](ADR-449-tail-of-a-coordinate-is-not-the-name-of-a-field.md) |
| ADR-450 | ADR-450 — «Хвостов 115, многозначен 1» оказалось свойством ПРАВИЛА уплощения: при развёртывании списков 121 и 16 | Accepted | [ADR-450](ADR-450-the-tail-count-was-a-property-of-the-flattening-rule.md) |
| ADR-446 | ADR-446 — Занижение повсеместно, а у ИСХОДА доходит до двух тестов | Accepted | [ADR-446](ADR-446-the-understatement-is-everywhere-and-at-the-outcome-it-reaches-only-two-tests.md) |
| ADR-451 | ADR-451 — Идентичность рантайма Director против внешних канонических входов | Accepted | [ADR-451](ADR-451-director-v131-runtime-dependency-and-provenance.md) |
| ADR-452 | ADR-452 — Принадлежность процесса и безопасное завершение | Accepted | [ADR-452](ADR-452-process-ownership-safe-termination.md) |
| ADR-453 | ADR-453 — Целостность доставки общих канонических файлов | Accepted | [ADR-453](ADR-453-shared-canonical-file-delivery-integrity.md) |
| ADR-454 | ADR-454 — Идентичность рантайма против идентичности канонической доставки | Accepted | [ADR-454](ADR-454-runtime-identity-vs-canonical-delivery-identity.md) |
| ADR-455 | ADR-455 — G17 (ADR-385) против ADR-395: устаревший контракт теста | Accepted | [ADR-455](ADR-455-g17-stale-test-contract-debt.md) |
| ADR-456 | ADR-456 — Негерметичные тесты: долг тест-инфраструктуры | Accepted | [ADR-456](ADR-456-non-hermetic-test-debt.md) |
| ADR-457 | ADR-457 — Доля многозначных хвостов есть свойство ДОКУМЕНТА, а не реестра; и у тринадцати документов она уже стоит читателю решения | Accepted | [ADR-457](ADR-457-ambiguity-share-is-a-property-of-the-document-not-the-registry.md) |
| ADR-458 | ADR-458 — Многозначные хвосты РАСХОДЯТСЯ (34 из 38), но ни один вердикт их не видит | Accepted | [ADR-458](ADR-458-ambiguous-tails-diverge-but-no-verdict-can-see-them.md) |
| ADR-459 | ADR-459 · Ненаблюдённая достижимость была исходом с именем «None» (заказ G75 п. 4) | Accepted | [ADR-459](ADR-459-absent-reachability-was-an-outcome-named-none.md) |
| ADR-460 | ADR-460 · Счётчик, открытый любой строке: класс закрыли у одного поля, население — 158 (заказ G76 п. 1) | Accepted | [ADR-460](ADR-460-a-counter-open-to-any-string-population-158.md) |
| ADR-461 | ADR-461 · Вред лежит у ЧИТАТЕЛЯ: из 158 открытых счётчиков класс делят 44, а у 95 читатель НЕ ИЗМЕРЕН (заказ G77 п. 1) | Accepted | [ADR-461](ADR-461-harm-lives-at-the-reader-forty-four-of-158.md) |
| ADR-462 | ADR-462 (заказ G78 п. 1) — ОДИН шаг не разрешает НИ ОДНОГО из 66, и премиссa заказа измерена неверной | Accepted | [ADR-462](ADR-462-one-step-resolves-none-of-the-sixty-six.md) |
| ADR-463 | ADR-463 (заказ G79 п. 1) — ОДИН шаг переноса ПОЛЕМ не разрешает НИ ОДНОГО из 53, и ошиблась не премисса, а ГЛУБИНА | Accepted | [ADR-463](ADR-463-one-field-step-resolves-none-of-the-fifty-three.md) |
| ADR-464 | ADR-464 — Гейт запрещённых импортов: одно правило, один прибор (подстрока → AST) | Accepted | [ADR-464](ADR-464-forbidden-import-gate-one-rule-one-instrument.md) |
| ADR-465 | ADR-465 (заказ G80 п. 1) — разбор ПО ИМЕНИ ПОЛЯ разрешает ТРИ из 26, а форм чтения оказалось не две, а ТРИ | Accepted | [ADR-465](ADR-465-document-field-reader-three-of-twenty-six.md) |
| ADR-466 | ADR-466 (заказ G81 п. 1) — шаг по СВЯЗАННОМУ ИМЕНИ разрешает СЕМЬ из 16, и у восьми остатка имя отказа было НЕ ТО | 2026-09-23 · принято | [ADR-466](ADR-466-bound-name-step-seven-of-sixteen.md) |
| ADR-467 | ADR-467 (заказ G82 п. 1) — шаг за ЗАЩИТНЫЙ ХВОСТ разрешает ТРИ из 6, и впервые в ряду появился БЕЗВРЕДНЫЙ | 2026-09-24 · принято | [ADR-467](ADR-467-defensive-tail-binding-three-of-six.md) |
| ADR-468 | ADR-468 · Вердикт теневого гейта доставки получил ТРЕТИЙ исход | 2026-09-24 · принято | [ADR-468](ADR-468-shadow-verdict-third-outcome.md) |
| ADR-469 | ADR-469 · Форма вреда у ПИСАТЕЛЯ: из 158 «открытых» счётчиков 36 не открыты вовсе | 2026-09-24 · принято | [ADR-469](ADR-469-writer-harm-form-silent-or-loud.md) |
| ADR-470 | ADR-470 — Вердикт CI о вершине `main` обязан быть ИЗМЕРЕН, а не предположен | 2026-09-24 · принято | [ADR-470](ADR-470-ci-verdict-about-main-is-measured-every-cycle.md) |
| ADR-471 | ADR-471 · Один вопрос о неизменившемся дереве — один ответ | 2026-09-24 · принято | [ADR-471](ADR-471-one-question-about-an-unchanged-tree-one-answer.md) |
| ADR-472 | ADR-472 — Красный `main` падал НЕ там, где сказано в карточке: сканер мёртвого кода, 30 с, и цена НА УЗЕЛ | 2026-09-25 · принято | [ADR-472](ADR-472-scanner-cost-per-node-not-per-walk.md) |
| ADR-473 | ADR-473 · Бюджет переписи мерили не в том окне: разрыв не 73 с, а больше чем вчетверо | 2026-09-25 · принято | [ADR-473](ADR-473-census-budget-measured-in-the-wrong-window.md) |
| ADR-474 | ADR-474 — Шаг тестов ОБРЫВАЛСЯ, а не падал: «не измерено» месяц выдавалось за «красное» | 2026-09-25 · принято | [ADR-474](ADR-474-step-verdict-abort-is-not-red.md) |
| ADR-475 | ADR-475 — Публичный сайт пять суток отдавал завышенный APY, и сторож называл это «лагом доставки» | 2026-09-25 · принято | [ADR-475](ADR-475-publisher-stuck-is-not-deploy-lag.md) |
| ADR-476 | ADR-476 — Оборванная сессия обязана НАЗВАТЬ, что она успела уронить и на чём её сняли | 2026-09-25 · принято | [ADR-476](ADR-476-a-cut-session-must-still-name-what-it-was-running.md) |
| ADR-477 | ADR-477 · Открытый PR — это НЕ доставленная работа: перепись доставки | 2026-09-25 · принято | [ADR-477](ADR-477-otkrytyi-pr-ne-est-dostavlennaya-rabota.md) |
| ADR-478 | ADR-478 — Сторож сверял страницу с производителем, которого она не читает | 2026-09-26 · принято | [ADR-478](ADR-478-the-guard-compared-the-page-to-a-producer-it-does-not-read.md) |
| ADR-479 | ADR-479 — Вердикт CI решало git-окружение, которого не объявлял никто: 24 падения из 59 воспроизведены пофамильно, и ни одно не про код | 2026-09-26 · принято | [ADR-479](ADR-479-git-environment-is-an-undeclared-input-of-the-suite.md) |
| ADR-480 | ADR-480 — §49 `Anti-churn` приказа CIO измерен ИСХОДОМ: книга возвращалась туда, откуда ушла, 12 раз, и семь возвратов гистерезису нечем увидеть | 2026-09-26 · принято | [ADR-480](ADR-480-anti-churn-criterion-measured-by-outcome.md) |

| ADR-484 | ADR-484 — §49 `Economics` приказа CIO измерен ИСХОДОМ: опубликованный «оптимум» шесть раз проиграл решению ничего не делать | 2026-09-27 · принято | [ADR-484](ADR-484-cio-economics-optimum-loses-to-do-nothing.md) |
| ADR-485 | ADR-485 — Критерий §49 `Persistence` измерен ИСХОДОМ: преимущество не пережило горизонт ни у одного хода | 2026-09-26 · принято | [ADR-485](ADR-485-persistence-criterion-measured-no-advantage-outlived-the-horizon.md) |
| ADR-486 | ADR-486 · Критерий §49 `Risk` измерен ИСХОДОМ: потолок обходят не доводом, а ЯРЛЫКОМ | 2026-09-27 · принято | [ADR-486](ADR-486-risk-criterion-measured-by-outcome-the-cap-is-bypassed-by-a-label.md) |
| ADR-487 | ADR-487 — Критерий §49 `Pre-trade safety` измерен ИСХОДОМ: второго наблюдения входов не было ни у одного из 46 исполнений | 2026-09-27 · принято | [ADR-487](ADR-487-cio-pre-trade-safety-measured-by-outcome.md) |
| ADR-488 | ADR-488 · §49 `Owner visibility`: рекомендация доходит, все три числа — нет | 2026-09-27 · принято | [ADR-488](ADR-488-owner-visibility-three-numbers-do-not-reach-the-owner.md) |
| ADR-489 | ADR-489 — Три числа §49 доставлены, и последний шаг до владельца стал измеримым | 2026-09-28 · принято | [ADR-489](ADR-489-owner-visibility-numbers-delivered-and-the-last-step-measured.md) |
| ADR-490 | ADR-490 — Владельца решения на уровне ПОРТФЕЛЯ не существует: два доллара из трёх лежат вне самого широкого решения | 2026-09-28 · принято | [ADR-490](ADR-490-portfolio-level-decision-owner-does-not-exist.md) |
| ADR-491 | ADR-491 — Критерий §49 `No regression` измерен ПО ИСХОДУ: НЕ ВЫПОЛНЕН, и правило принадлежности пришлось переписать ДВАЖДЫ | 2026-09-28 · принято | [ADR-491](ADR-491-no-regression-criterion-measured-by-outcome.md) |
| ADR-497 | Relationship Registry (per-task LINK records, provenance-typed EXPLICIT/DERIVED/HEURISTIC/UNKNOWN, no silent fail) + per-session handoff records — concurrency-safe for parallel AI branches | Accepted | [ADR-497](ADR-497-relationship-registry-and-handoff-records.md) |
| ADR-496 | Wire studio_shell/ tests (read-model invariants · classifier parity · RED safety · CSRF guards) into canonical CI — owner-approved 2026-09-28; removes _ALLOWED_UNCOVERED exemption | Accepted | [ADR-496](ADR-496-wire-studio-shell-tests-into-ci.md) |
| ADR-495 | ADR-495: Studio OS Core V1 — Project Registry, Context Pack, Decision seam, Handoff | Accepted | [ADR-495](ADR-495-studio-os-core-v1-registry-context-decisions.md) |
| ADR-494 | ADR-494: Canonical repository, branch, and deployment/promotion policy (P0) | Accepted | [ADR-494](ADR-494-canonical-repository-and-deployment-policy.md) |
| ADR-493 | ADR-493: Owner Remote — voice production seams (local STT, canonical task, decision/idea) | Accepted | [ADR-493](ADR-493-owner-remote-voice-production-seams.md) |
| ADR-492 | ADR-492: Studio OS Hybrid Shell / Cockpit — architecture & read-only v0 | Accepted | [ADR-492](ADR-492-studio-os-hybrid-shell-cockpit.md) |
| ADR-498 | ADR-498 — Цена класса «две сессии на одном предмете»: измерена, и она не там, где её искали | 2026-09-28 · принято | [ADR-498](ADR-498-price-of-the-two-sessions-on-one-subject-class.md) |
| ADR-499 | ADR-499 — Предмет прибора G17 снят У ИСТОЧНИКА: десять красных двенадцати суток были утверждением о загрузчике, напечатанным про каждого наследника | 2026-09-28 · принято | [ADR-499](ADR-499-g17-subject-removed-at-the-source.md) |
| ADR-500 | ADR-500: Production activation boundary — Canonical ≠ Staging ≠ Activation | Accepted | [ADR-500](ADR-500-production-activation-boundary.md) |
| ADR-501 | ADR-501 — Освобождение носителя: одна копия условия, одна система координат | 2026-09-28 · принято | [ADR-501](ADR-501-one-copy-of-the-carried-release-condition.md) |
| ADR-502 | ADR-502 — Личность, которая не есть поле: список скаляров назвал себя, цена этого измерена, а правило пришлось свести к ОДНОЙ копии | 2026-09-29 · принято | [ADR-502](ADR-502-identity-that-is-not-a-field.md) |
| ADR-503 | ADR-503 — Расширение `_IDENTITY_FIELDS` замером: длина списка есть признак НЕОБХОДИМЫЙ и не достаточный | 2026-09-29 · принято | [ADR-503](ADR-503-identity-fields-extended-by-measurement.md) |
| ADR-504 | ADR-504 · Тавтологичная сверка копий — это «не измерено», а не «сошлись» | 2026-09-29 · принято | [ADR-504](ADR-504-a-tautological-comparison-is-not-a-green.md) |
| ADR-505 | ADR-505 — Тринадцать вердиктов прозой сводкой НЕ ЯВЛЯЮТСЯ: сводный замер §49 сделан машиной, и он говорит 0 из 13 | 2026-09-29 · принято | [ADR-505](ADR-505-thirteen-verdicts-in-prose-are-not-a-tally.md) |
| ADR-511 | ADR-511 — Четвёртая привязка §49: `Anti-churn` перестал быть НЕ ИЗМЕРЕНО, а вопрос о свежести сменил ЗНАК | 2026-09-29 · принято | [ADR-511](ADR-511-the-fourth-binding-and-the-false-green-a-quiet-journal-would-have-given.md) |
| ADR-512 | ADR-512 — Пятая привязка §49: вопрос о законности задаётся ТОЛЬКО зелёному ответу | 2026-09-29 · принято | [ADR-512](ADR-512-the-fifth-binding-and-the-legitimacy-question-asked-only-of-the-green-answer.md) |
| ADR-515 | ADR-515 — Последняя привязка цены `WORDING`: зелёный ответ, померенный на трети книги | 2026-09-29 · принято | [ADR-515](ADR-515-the-last-wording-binding-and-a-green-answer-measured-on-a-third-of-the-book.md) |
| ADR-517 | ADR-517 (заказ G85 п. 1) — ЧЕТЫРЕ раскола из девяти НЕДОСТИЖИМЫ, и один из них ряд предъявлял как образцово доказанный | 2026-09-29 · принято | [ADR-517](ADR-517-split-at-the-reader-unreachable-at-the-writer.md) |
| ADR-518 | ADR-518 (заказ G85 п. 2) — из СЕМНАДЦАТИ третьих исходов ни один не был назван верно, а ПЯТЬ вообще не счётчики класса | 2026-09-30 · принято | [ADR-518](ADR-518-accumulator-kind-asked-of-the-binding.md) |
| ADR-519 | ADR-519 (заказ G85 п. 4) — последний дешёвый остаток ряда разрешён ЦЕЛИКОМ, и тем же звеном найден ЛОЖНЫЙ член его знаменателя | 2026-09-30 · принято | [ADR-519](ADR-519-loop-key-over-a-declared-list.md) |
| ADR-520 | ADR-520 — Пин, ВИДИМЫЙ гейту, не есть пин, которому гейт ПОДЧИНЯЕТСЯ | 2026-09-30 · принято | [ADR-520](ADR-520-a-pin-visible-to-the-gate-is-not-a-pin-obeyed-by-it.md) |
| ADR-521 | ADR-521: Telegram Owner Control Plane — SPA seams for the Bridge bot, SPA bot safety, paused ≠ down | ACCEPTED | [ADR-521](ADR-521-telegram-owner-control-plane.md) |
| ADR-522 | ADR-522 (заказ G100 п. 3) — вердикт, читающий счётчик классов ПОИМЁННО: аварии ADR-468 в дереве нет ни одной, а полного перечня нет ни у одного из ТРЁХ разрешённых | 2026-09-30 · принято | [ADR-522](ADR-522-verdict-over-named-keys-of-a-class-counter.md) |
| ADR-516 | ADR-516 — Immutable release ≠ mutable operational state; acceptance models interpreter-mediated launch and the fleet interpreter | 2026-09-29 · принято | [ADR-516](ADR-516-immutable-release-not-mutable-operational-state.md) |
| ADR-514 | ADR-514 — Вторая привязка цены `WORDING`: претензия, которая была НАПЕЧАТАНА, а не измерена | 2026-09-29 · принято | [ADR-514](ADR-514-the-second-wording-binding-and-a-claim-that-was-typed-in-rather-than-measured.md) |
| ADR-513 | ADR-513 — Первая привязка цены `WORDING`: дом порога спрашивали в ОДНОМ из двух мест | 2026-09-29 · принято | [ADR-513](ADR-513-the-first-wording-binding-and-the-home-of-a-threshold-asked-in-only-one-of-two-places.md) |
| ADR-510 | ADR-510 — третья привязка §49, и вопрос о свежести, заданный СТОЯЩЕЙ КНИГЕ | 2026-09-29 · принято | [ADR-510](ADR-510-the-third-binding-and-the-freshness-question-asked-of-the-standing-book.md) |
| ADR-509 | ADR-509 — приёмка §49 меряется в ОТДЕЛЬНОМ дереве только для чтения (решение владельца) | 2026-09-29 · принято | [ADR-509](ADR-509-a-read-only-acceptance-tree-for-the-cio-order.md) |
| ADR-508 | ADR-508 — вторая привязка §49 уехала из прозы в поле, и вопрос о свежести сменил адрес | 2026-09-29 · принято | [ADR-508](ADR-508-the-second-binding-and-the-freshness-question-that-changed-address.md) |
| ADR-507 | ADR-507 — Первая привязка §49 уехала из прозы в поле: «Economics» перестал быть НЕ ИЗМЕРЕНО | 2026-09-29 · принято | [ADR-507](ADR-507-the-first-binding-moved-out-of-prose.md) |
| ADR-506 | ADR-506 — Десять «НЕ ИЗМЕРЕНО» оказались ТРЕМЯ разными ценами, и дешёвая из них стоит одно поле | 2026-09-29 · принято | [ADR-506](ADR-506-the-price-of-an-unmeasured-s49-criterion.md) |
| ADR-523 | ADR-523 — Сверка читала страницу, на которой числа нет; молчание считалось согласием | 2026-09-30 · принято | [ADR-523](ADR-523-the-operand-page-of-a-comparison.md) |
| ADR-524 | ADR-524 — «Предыдущий прогон», взятый из git-tracked артефакта: класс измерен, и в CI он населён ОДНИМ членом | 2026-09-30 · принято | [ADR-524](ADR-524-a-prior-run-operand-read-from-a-committed-artifact.md) |
| ADR-525 | ADR-525: Capital Architecture v1 and the Trading Research Engine v0 | ACCEPTED | [ADR-525](ADR-525-capital-architecture-v1-and-trading-research-engine.md) |
| ADR-526 | ADR-526 — У произведённой находки нет читателя внутри цикла | 2026-09-30 · принято | [ADR-526](ADR-526-a-finding-with-no-reader-inside-the-cycle.md) |
| ADR-527 | ADR-527: Memory & Context Architecture v1 | ACCEPTED | [ADR-527](ADR-527-memory-and-context-architecture-v1.md) |
| ADR-528 | ADR-528 — Имена упавших тестов обязаны переживать раннер; мерить это у ПИСАТЕЛЯ | 2026-10-01 · принято | [ADR-528](ADR-528-failed-test-names-must-outlive-the-runner.md) |
| ADR-529 | ADR-529 — Односторонность правила принадлежности §49 ИЗМЕРЕНА: правило видит 129 дорог из 1112 | 2026-10-01 · принято | [ADR-529](ADR-529-one-sidedness-of-the-membership-rule-measured-not-declared.md) |
| ADR-530 | ADR-530: DeFi Architecture Gap Audit — findings, priorities and the vNext input | ACCEPTED | [ADR-530](ADR-530-defi-architecture-gap-audit.md) |
| ADR-531 | ADR-531: DeFi Engine vNext — Phase 0: P0 safety & data-integrity repair | ACCEPTED | [ADR-531](ADR-531-defi-vnext-phase0-p0-repair.md) |
| ADR-532 | ADR-532: DeFi Engine vNext — Phase 1 foundation (derived, advisory) | ACCEPTED | [ADR-532](ADR-532-defi-vnext-phase1-foundation.md) |
| ADR-533 | ADR-533: Three DeFi paper portfolios — different mechanics, own versions, one status read model | ACCEPTED | [ADR-533](ADR-533-three-defi-paper-portfolios.md) |
| ADR-534 | ADR-534 — Куда уходит время шага `spa_core/tests/`: замер, а не экстраполяция | 2026-10-02 · принято | [ADR-534](ADR-534-where-the-time-of-the-test-step-goes.md) |
| ADR-535 | ADR-535 — Читатель квитанции, которую никто не пишет: посылка заказа была неверна | 2026-10-02 · принято | [ADR-535](ADR-535-the-reader-of-a-receipt-that-nobody-writes.md) |
| ADR-536 | ADR-536 — Освобождение адресовано ДЕРЖАТЕЛЮ, а не КАРТОЧКЕ | 2026-10-02 · принято | [ADR-536](ADR-536-a-release-addressed-to-the-holder-not-to-the-card.md) |
| ADR-537 | ADR-537: Status colour is not a risk grade — one card format and live status for the three paper portfolios | ACCEPTED | [ADR-537](ADR-537-status-colour-is-not-a-risk-grade.md) |
| ADR-538 | ADR-538 — Две из семи «потерянных координат» потеряны не были, а поднять остальные было уже нечем | 2026-10-02 · принято | [ADR-538](ADR-538-two-of-seven-lost-coordinates-were-never-lost.md) |
| ADR-539 | ADR-539 — Род поля спрошен у КОДА производителя, и приставленное к нему правило отвергнуто замером | 2026-10-02 · принято | [ADR-539](ADR-539-the-kind-of-a-field-asked-of-the-producers-code.md) |
| ADR-540 | ADR-540 — Пара чисел измерена, и правилом она быть не может | 2026-10-02 · принято | [ADR-540](ADR-540-a-pair-of-numbers-cannot-be-the-rule.md) |
| ADR-541 | ADR-541 — Четвёрка истлела прежде, чем её успели рассудить: «замер» стал машинным, правило при нём отвергнуто | 2026-10-02 · принято | [ADR-541](ADR-541-the-quadruple-rotted-before-it-was-adjudicated.md) |
| ADR-542 | ADR-542 — Каталог, который назвал читатель, ДОХОДИТ до пробы | 2026-10-02 · принято | [ADR-542](ADR-542-the-directory-the-reader-named-reaches-the-probe.md) |
| ADR-543 | ADR-543 — Класс «зелёный по построению» ИЗМЕРЕН, и прописанный заказом метод отвечает на СОСЕДНИЙ вопрос | 2026-10-03 · принято | [ADR-543](ADR-543-the-prescribed-method-answers-a-neighbouring-question.md) |
| ADR-544 | ADR-544 — «Кто новее» мерилось часами и отвечало на СОСЕДНИЙ вопрос: восемь уверенных вердиктов неверны, и все восемь — в опасную сторону | 2026-10-03 · принято | [ADR-544](ADR-544-the-order-axis-answered-a-neighbouring-question.md) |
| ADR-545 | ADR-545 — Дерево приёмки §49 существует и ИЗМЕРЕНО; «его нет» верно у 2 критериев из 13, а не у тринадцати | 2026-10-03 · принято | [ADR-545](ADR-545-the-acceptance-tree-is-measured-not-absent.md) |
| ADR-546 | ADR-546 — Прибор, бросавший свой стенд: 87 ГБ за трое суток, и дважды названная не та причина | 2026-10-03 · принято | [ADR-546](ADR-546-the-instrument-that-left-its-stand-behind.md) |
| ADR-547 | ADR-547 — Такт сводки §49 ВЫЧИСЛЕН из её входов: пол 7 ч, единственный зовущий звал в 27 раз реже | 2026-10-03 · принято | [ADR-547](ADR-547-the-tact-of-the-s49-tally-is-computed-not-declared.md) |
| ADR-548 | ADR-548 · Three paper portfolios — owner gate applied, epic closed | 2026-10-03 · принято | [ADR-548](ADR-548-three-portfolios-owner-gate-applied.md) |
| ADR-549 | ADR-549 · Объявленный срок годности — против НАБЛЮДЁННОГО такта, а не против расписания | 2026-10-03 · принято | [ADR-549](ADR-549-a-declared-expiry-measured-against-the-observed-tact.md) |
| ADR-550 | ADR-550 — Население привязок, держащихся прозой, посчитано ДО объявления поля | 2026-10-03 · принято | [ADR-550](ADR-550-the-population-of-prose-bindings-counted-before-a-field-is-declared.md) |
| ADR-551 | ADR-551 · Build Loop v1 + agent output governance + resource guardrails | 2026-10-03 · принято | [ADR-551](ADR-551-build-loop-governance-resource-guardrails.md) |
| ADR-552 | ADR-552 · Owner Remote / Mission Control v1 | 2026-10-03 · принято | [ADR-552](ADR-552-owner-remote-mission-control-v1.md) |
| ADR-554 | ADR-554 · Chief Investment Officer (Штирлиц) — cross-sleeve capital allocation v1 (ADVISORY / PAPER) | 2026-10-04 · принято | [ADR-554](ADR-554-investment-cio-capital-allocation-v1.md) |
| ADR-553 | ADR-553 — Четвёртая дверь: предпосылка сцены, взятая из ЖИВОГО реестра проб | 2026-10-03 | [ADR-553](ADR-553-the-fourth-door-a-scene-premise-from-the-live-registry.md) |
| ADR-555 | ADR-555 — Адресат отказа: «НЕ ВЫПОЛНЕН» обязан называть, за кем починка | 2026-10-04 · принято | [ADR-555](ADR-555-the-addressee-of-a-refused-owner-criterion.md) |
| ADR-556 | ADR-556 · RM-LIVE-01 — Shadow execution + limited capital pilot readiness | 2026-10-04 · принято | [ADR-556](ADR-556-shadow-execution-and-pilot-readiness.md) |
| ADR-557 | ADR-557 — Шаг подорожал, а работы не прибавилось: вывод ADR-534 «помещается в 240» ОПРОВЕРГНУТ замером | 2026-10-04 · принято | [ADR-557](ADR-557-the-step-got-dearer-without-the-work-growing.md) |
| ADR-558 | ADR-558 — Якорь, о котором не спросили: применённость мутационной подмены измерена | 2026-10-04 · принято | [ADR-558](ADR-558-the-anchor-nobody-asked-about.md) |
| ADR-559 | ADR-559 — Чья мера произвела вердикт пробы: род измерен, а не объявлен | 2026-10-04 · принято | [ADR-559](ADR-559-whose-measure-produced-the-verdict.md) |
| ADR-560 | ADR-560 · RM-EXPAND-01 · Capital universe expansion + Research Factory v1 | 2026-10-04 · принято | [ADR-560](ADR-560-research-factory-capital-universe-expansion.md) |
| ADR-561 | ADR-561 — Кто спрашивает «та ли это книга»: население измерено, а не предположено | 2026-10-04 · принято | [ADR-561](ADR-561-who-asks-whether-this-is-the-standing-book.md) |
| ADR-562 | ADR-562 — Доходит ли инъектированный `now` до САМОЙ отметки: гипотеза заказа опровергнута замером | 2026-10-04 · принято | [ADR-562](ADR-562-does-the-injected-clock-reach-the-stamp-itself.md) |
| ADR-563 | ADR-563 — Публичная ставка доходности округляется ВНИЗ (решение владельца) | 2026-10-04 · принято | [ADR-563](ADR-563-published-rate-rounds-down.md) |
| ADR-564 | ADR-564 · RM-EVIDENCE-01 · Research evidence + paper admission v1 (Sherlock) | 2026-10-04 · принято | [ADR-564](ADR-564-research-evidence-and-paper-admission.md) |
| ADR-565 | ADR-565 (заказ G98 п. 1) — у четырёх недостижимых расколов незнакомый класс в артефакте НЕ ВСТРЕЧАЛСЯ ни разу, и это наблюдение, а не теория | 2026-10-05 · принято | [ADR-565](ADR-565-unknown-class-in-the-live-artifact.md) |
| ADR-566 | ADR-566 (заказ G98 п. 2) — у остальных открытых счётчиков две оси лежали рядом и не смотрели друг на друга; 33 раскола достижимы, и предпосылка заказа опровергнута ровно наоборот | 2026-10-05 · принято | [ADR-566](ADR-566-the-same-question-asked-of-the-rest.md) |
| ADR-568 | ADR-568 (заказ G99 п. 1) — знаменатель ряда G78…G98 ПОПРАВЛЕН замером: ложных членов шесть из 206, а не шестьдесят, и доля 29 % не переносится потому, что ей НЕГДЕ быть | 2026-10-05 · принято | [ADR-568](ADR-568-the-denominator-of-the-series-measured.md) |
| ADR-572 | ADR-572 (заказ G99 п. 2) — честность имени спрошена у ВСЕХ чисел ряда, а не у двух: подданного не называет ни одно из 43, и уверенно назван он у 16 из 28 | 2026-10-05 · принято | [ADR-572](ADR-572-the-subject-of-a-series-number.md) |
| ADR-573 | ADR-573 (заказ G99 п. 3) — второе звено над зовущим: род накопителя у ЧЕТЫРЁХ из пяти доказывается одним шагом вверх, а пятый ждёт ТРЕТЬЕГО — и оно объявлено не разбираемым заранее | 2026-10-05 · принято | [ADR-573](ADR-573-the-second-link-above-the-caller.md) |
| ADR-574 | ADR-574 (заказ G100 п. 1) — короткое замыкание правила ключа НЕСУЩЕЕ: переставить вопрос значит не починить знаменатель, а испортить его на 34 | 2026-10-06 · принято | [ADR-574](ADR-574-what-holds-the-denominator-up.md) |
| ADR-575 | ADR-575 (заказ G100 п. 2) — судью достижимости достаётся не всем: из 16 расколов ряда он спрошен о 9, и ПЯТЬ непереданных уже существовали к его зову | 2026-10-06 · принято | [ADR-575](ADR-575-who-gets-the-reachability-judge.md) |
| ADR-580 | ADR-580 · RM-TRUTH-01: контракты правды компании (C1–C12), заморожены после независимого ревью | 2026-10-05 · принято | [ADR-580](ADR-580-company-truth-contracts-rm-truth-01.md) |
| ADR-581 | ADR-581 (заказ G102 п. 1) — права ли ДРУГАЯ дорога: к более мягкому вердикту не ведёт НИ ОДНА, а трёх классов из восьми не судит НИКТО | 2026-10-06 · принято | [ADR-581](ADR-581-is-the-other-road-right.md) |
| ADR-582 | ADR-582 (заказ G102 п. 2) — «в население НЕ попадает вовсе» неверно: хвост цепочки входит как ЦЕЛЫЙ вердикт у 4 из 6, и двое из них — те самые площадки, на которых отвечал ADR-581 | 2026-10-06 · принято | [ADR-582](ADR-582-the-verdict-form-outside-the-closed-list.md) |
| ADR-590 | ADR-590 · Canonical Trading Research lineage + BTC systems disposition (RM-TRUTH-01 · CAPITAL) | 2026-10-05 · принято | [ADR-590](ADR-590-canonical-trading-research-lineage.md) |
| ADR-591 | ADR-591 · Память (RM-TRUTH-01, трек M): HYBRID_BORROW_COMPONENTS — чинить stdlib FTS5, не менять на MemPalace | 2026-10-05 · принято | [ADR-591](ADR-591-memory-hybrid-borrow-components.md) |
| ADR-592 | ADR-592 · Director OS v2 = Mission Control evolved: one read-only owner cockpit, Company Truth computed on read | 2026-10-06 · принято | [ADR-592](ADR-592-director-os-v2-mission-control.md) |
| ADR-593 | ADR-593 · Backfill: Conservative is the evidenced go-live book (UX-26, 2026-07-11) | 2026-10-06 · принято | [ADR-593](ADR-593-conservative-is-the-evidenced-book-backfill.md) |
| ADR-594 | ADR-594 (заказ G103 п. 1) — реестр источников сайта был верен шесть дней: живая страница ОПРОВЕРГАЕТ 3 объявления из 11, и все три молчат, потому что отвечает сосед по label | 2026-10-06 · принято | [ADR-594](ADR-594-the-registry-of-site-numbers-asked-of-the-live-page.md) |
| ADR-599 | ADR-599 · OpenClaw удалён: неиспользуемый агент с доступом к shell (решение владельца) | 2026-10-07 · принято | [ADR-599](ADR-599-openclaw-removed.md) |
| ADR-610 | ADR-610 · ARB continuity: a fresh AI session recovers the company from canonical files, and knows when that context is stale | 2026-10-07 · принято | [ADR-610](ADR-610-arb-continuity.md) |
| ADR-611 | ADR-611 · Классы архивов: FULL и CRITICAL больше нельзя перепутать (ARB-CONTINUITY-01, волна B) | 2026-10-07 · принято | [ADR-611](ADR-611-backup-archive-classes.md) |
| ADR-612 | ADR-612 · Telegram Capital surface (read-only) + плайн-язык владельца в Director OS | 2026-10-07 · принято | [ADR-612](ADR-612-telegram-capital-surface-and-plain-owner-language.md) |
| ADR-613 | ADR-613 · Инжест 13 карточек `owner-done`: запись была у 11 из 13, не хватало СТАТУСА — и две карточки назвали носителями работы слуги, которых не существует | 2026-10-07 · принято | [ADR-613](ADR-613-thirteen-owner-closures-the-status-lagged-the-record.md) |
| ADR-614 | ADR-614 · Сторож инварианта №3 учится видеть ВТОРУЮ дверь: запуск бинаря LLM подпроцессом (решение владельца 09.09, исполнено на 28-е сутки) | 2026-10-07 · принято | [ADR-614](ADR-614-invariant-3-guard-learns-the-second-door.md) |
| ADR-620 | ADR-620 (заказ G103 п. 2) — класс оказался шире кустодиана в ОДИННАДЦАТЬ раз: 40 претензий к чужой разметке, из них 8 не подтверждает ничто, кроме самого читателя | 2026-10-07 · принято | [ADR-620](ADR-620-the-class-is-wider-than-the-custodian.md) |
| ADR-621 | ADR-621 — Заметил бы хостовой читатель подмену операнда КАНОНОМ: по возрасту — НИ ОДИН из 217 | 2026-10-07 · принято | [ADR-621](ADR-621-would-the-host-reader-notice-the-canon.md) |
| ADR-630 | ADR-630 · Правда продукта: одно сопоставление профилей, один такт публикации, типизированная и проверяемая витрина (PRODUCT-TRUTH-02) | 2026-10-07 · принято | [ADR-630](ADR-630-product-truth-publication-pipeline.md) |
| ADR-622 | ADR-622 — У скольких git-tracked артефактов ВООБЩЕ нет объявленного писателя: из 475 — у ОДНОГО есть | 2026-10-07 · принято | [ADR-622](ADR-622-which-tracked-artifacts-have-no-declared-writer.md) |
| ADR-623 | ADR-623 — Читатель ЧУЖОГО прошлого прогона: класс ПУСТ, и ноль добыт одной ногой | 2026-10-07 · принято | [ADR-623](ADR-623-the-reader-of-someone-elses-prior-run.md) |
| ADR-643 | ADR-643 — Последнее звено плана самолечения не имело читателя внутри цикла | 2026-10-08 · принято | [ADR-643](ADR-643-the-last-link-of-the-self-healing-plane-had-no-reader.md) |
| ADR-644 | ADR-644 — Находка сторожа переходов статусов не имела читателя внутри цикла | Accepted · 2026-10-08 | [ADR-644](ADR-644-the-status-transition-sentinels-finding-had-no-reader.md) |
| ADR-642 | ADR-642 — У сторожа свежести своя находка была без читателя | 2026-10-07 · принято | [ADR-642](ADR-642-the-freshness-custodians-own-finding-had-no-reader.md) |
| ADR-640 | ADR-640 · Капитальные источники доходности и торговый рукав Trading Alpha (CAPITAL-SOURCES-01, волны A+B) | Accepted · 2026-10-07 | [ADR-640](ADR-640-capital-sources-trading-alpha-sleeve.md) |
| ADR-641 | ADR-641 · Oracle consumes all return sources; paper Portfolio of Sources; the 10–15 % research question (CAPITAL-SOURCES-01, wave C) | Accepted · 2026-10-07 | [ADR-641](ADR-641-oracle-multi-source-paper-portfolio.md) |

| ADR-645 | ADR-645 · Отчёт монитора доступности не имел читателя внутри цикла — и перечень ADR-526 назвал не тот файл | 2026-10-08 · принято | [ADR-645](ADR-645-the-uptime-monitors-report-had-no-reader.md) |
| ADR-646 | ADR-646 · Порог сенсора ниже такта предмета: сторож, красный по построению, гасится читателем так же, как молчащий | 2026-10-08 · принято | [ADR-646](ADR-646-a-sensor-threshold-below-the-tact-of-its-subject.md) |
| ADR-647 | ADR-647 — СИЛЬНЫЙ захват без объявленной личности не стареет, и приказ владельца был неберущимся 634 цикла | 2026-10-08 · принято | [ADR-647](ADR-647-a-strong-claim-without-an-anchor-never-aged.md) |
| ADR-648 | ADR-648 — Объявленный потребитель, который не читает: двадцать рядов переписи стояли на объявлении | 2026-10-08 · принято | [ADR-648](ADR-648-a-declared-consumer-that-does-not-read.md) |
| ADR-649 | ADR-649 — Пять шагов CI не писали перечень имён ВОВСЕ: закрыто поимённо, и прибор не видит рабочего каталога | 2026-10-08 · принято | [ADR-649](ADR-649-five-ci-steps-wrote-no-record-of-failed-names.md) |
| ADR-650 | ADR-650 — Ноль, измеренный односторонне, есть НИЖНЯЯ ГРАНИЦА: читателя лога шага спросили с другой стороны | 2026-10-08 · принято | [ADR-650](ADR-650-a-one-sided-zero-is-a-lower-bound.md) |
| ADR-660 | ADR-660 — Политика представления владельца: проценты с двумя знаками (ROUND_HALF_UP) и время Europe/Madrid | 2026-10-08 · принято | [ADR-660](ADR-660-owner-presentation-policy-pct-two-decimals-madrid-time.md) |
| ADR-661 | ADR-661 · P1: публичная утечка внутренней кухни, сверка NAV, ложные нули воронки, пульт владельца | 2026-10-08 · принято | [ADR-661](ADR-661-p1-truth-and-safety-recovery.md) |
| ADR-662 | ADR-662 — `retention-days` есть ВЫБОР: спрос на возраст записи измерен у читателя, и хранилищ оказалось три | 2026-10-08 · принято | [ADR-662](ADR-662-retention-days-is-a-choice-the-demand-for-record-age-measured-at-the-reader.md) |
| ADR-670 | ADR-670 — Захват во frontmatter переживал СЛОВА САМОГО ДЕРЖАТЕЛЯ, и этим был заперт приказ владельца | 2026-10-08 · принято | [ADR-670](ADR-670-a-frontmatter-claim-outlived-its-holders-own-done.md) |
| ADR-671 | ADR-671 — Ставка, отказанная ПОЛИТИКОЙ, печаталась как мёртвый фид (приказ владельца «Portfolio CIO», п. G1) | 2026-10-08 · принято | [ADR-671](ADR-671-an-apy-refused-by-policy-is-not-a-dead-feed.md) |
| ADR-672 | ADR-672 · Правило принадлежности, видящее ТОЛЬКО прямой импорт: население измерено, и односторонностей у него ДВЕ | 2026-10-08 · принято | [ADR-672](ADR-672-a-membership-rule-that-sees-only-the-direct-import.md) |
| ADR-673 | ADR-673 · Расширение населения §49 МЕНЯЕТ вердикт — у двух поверхностей из трёх | 2026-10-09 · принято | [ADR-673](ADR-673-widening-the-population-changes-the-verdict.md) |
| ADR-674 | ADR-674 · Дорога есть достижимость, а не ИСПОЛНЕНИЕ — измерено У ТЕСТА, и ответом служит ВИЛКА | 2026-10-09 · принято | [ADR-674](ADR-674-a-road-is-reachability-not-execution.md) |
| ADR-675 | ADR-675 · Провал фазы `call` сводится к дефекту ПРИЧИНОЙ, и ответом служит вилка | 2026-10-09 · принято | [ADR-675](ADR-675-the-cause-of-a-call-phase-failure.md) |
| ADR-676 | ADR-676 — Дверь, которой случай переживает `--timeout`: это не блокировка в C-коде, а ПРОГЛОЧЕННЫЙ вердикт срока | 2026-10-09 · принято | [ADR-676](ADR-676-the-door-that-outlives-the-deadline.md) |
| ADR-677 | ADR-677 — Бюджет ноги 3.12 ИЗМЕРЕН, и «≥245 мин» было числом ГРАНИЦЫ, а не ноги | 2026-10-09 · принято | [ADR-677](ADR-677-the-budget-of-a-leg-and-the-speed-of-a-runner.md) |
| ADR-678 | ADR-678 · Предмет захвата — НОМЕР ЗАКАЗА, а не путь карточки: дверь шага 0a/0b его НЕ ВИДИТ (замер по исходу) | 2026-10-09 · принято | [ADR-678](ADR-678-the-subject-of-a-claim-is-the-order-not-the-file.md) |
| ADR-679 | ADR-679 · Запись прогона теряет не ВЕС, а УСЛОВИЕ шага | 2026-10-09 · принято | [ADR-679](ADR-679-the-record-is-lost-to-a-condition-not-to-its-weight.md) |
| ADR-680 | ADR-680 — Порог, который СВЯЗАЛ, и отметка, которая соврала: три оси перенесены и перемерены | 2026-10-09 · принято | [ADR-680](ADR-680-the-threshold-that-bound-and-the-stamp-that-lied.md) |
| ADR-681 | ADR-681 · Заголовочное число меряло ДВЕРЬ, а не вопрос — и дверь не называет сама инструкция | 2026-10-09 · принято | [ADR-681](ADR-681-the-headline-number-measured-the-door.md) |
| ADR-682 | ADR-682 — Одно поле, девять дверей часов, и согласие между ними не проверяет никто | 2026-10-10 · принято | [ADR-682](ADR-682-one-field-nine-clock-doors-and-nobody-checks-they-agree.md) |
| ADR-683 | ADR-683 — Дорог отрисовки было ДВЕ, и счётчик «ПРОЧИТАН ВХОЛОСТУЮ» перестал значить вред | 2026-10-10 · принято | [ADR-683](ADR-683-two-roads-of-rendering-made-the-hollow-counter-meaningless.md) |
| ADR-684 | ADR-684 — Цена КАНАЛА квитанции, спрошенная у ЧИТАТЕЛЯ: третье состояние записи вред не снимает | 2026-10-10 · принято | [ADR-684](ADR-684-the-cost-of-a-receipt-channel-asked-at-the-reader.md) |
| ADR-685 | ADR-685 — Цена ветви «освобождение по КАРТОЧКЕ», измеренная на живом журнале | 2026-10-10 · принято | [ADR-685](ADR-685-the-cost-of-releasing-by-card-measured-on-the-live-journal.md) |
| ADR-686 | ADR-686 — Почему освобождение не сняло НИЧЕГО: разбор 118 пустых освобождений по ПИСАТЕЛЮ | 2026-10-10 · принято | [ADR-686](ADR-686-why-an-empty-release-removed-nothing-broken-down-by-writer.md) |
| ADR-687 | ADR-687 — Вторая сторона цены оси D: две двери замера и объявленный неизмеримый остаток | 2026-10-10 · принято | [ADR-687](ADR-687-the-other-side-of-axis-d-two-doors-and-a-declared-unmeasurable-remainder.md) |
| ADR-688 | ADR-688 — Откуда ступень берёт историю: три двери, и слепая прятала пять потерь за нулём | 2026-10-10 · принято | [ADR-688](ADR-688-where-the-stage-takes-history-three-doors-and-a-false-zero.md) |
| ADR-689 | ADR-689 — Срок годности объявления владения: клок не `/tmp`, а остаток не число | 2026-10-10 · принято | [ADR-689](ADR-689-the-lifting-window-is-not-tmp-and-the-remainder-is-not-a-number.md) |
| ADR-690 | ADR-690 — Каталог никогда и не прятал доставку: цена ширины двери родни измерена, и ось заказа платит ДОКАЗАТЕЛЬСТВОМ | 2026-10-10 · принято | [ADR-690](ADR-690-the-directory-was-never-what-hid-the-delivery.md) |
| ADR-691 | ADR-691 — Слабая ось читает ЧУЖОЕ отображение: доля «вход против часов» измерена, и она против оси | 2026-10-11 · принято | [ADR-691](ADR-691-the-weak-axis-reads-someone-elses-mapping.md) |
| ADR-692 | ADR-692 — «Ряд или запись» перестало быть прозой: день различает элементы у 30 списков из 129, и три четверти рядов поля не имеют вовсе | 2026-10-11 · принято | [ADR-692](ADR-692-is-it-a-series-the-day-as-a-measured-discriminator.md) |
| ADR-693 | ADR-693 — Род кандидата встал РЯДОМ с его населением и длиной: 19 имён из 49 несут род, и три из пяти сильнейших — среди них | 2026-10-11 · принято | [ADR-693](ADR-693-the-kind-of-a-candidate-beside-its-population-and-length.md) |
| ADR-694 | ADR-694 — Третья ось кандидата измерена: у 44 имён из 49 население собрано из ОДНОГО читателя | Accepted | [ADR-694](ADR-694-the-third-axis-of-a-candidate-is-its-readers.md) |
| ADR-695 | ADR-695 — Население кандидата было верным числом под чужим именем: разница «поле ЕСТЬ» против «поле ГОДНО» ИЗМЕРЕНА, и мерило ADR-503 рассудило три имени из шести по узкому числу | Accepted | [ADR-695](ADR-695-the-population-of-a-name-was-right-for-another-question.md) |
| ADR-696 | ADR-696 — Адрес находки измерен: 12 из 71 разрешимы ТОЛЬКО местом, три отказа подряд были отказами ИМЕНИ, и цена пары — производитель, которого нет ни в одной области вызова | Accepted | [ADR-696](ADR-696-the-address-of-a-finding-place-against-name.md) |
| ADR-697 | ADR-697 — Третья односторонность оси ИЗМЕРЕНА: 33 места ось не видит, и ни одно из них не пишет поле, о котором идёт спор | Accepted | [ADR-697](ADR-697-the-modular-constant-the-axis-cannot-see.md) |
| ADR-698 | ADR-698 — Объявленный путь, которого фикстура не несёт: форма измерена, 301 пара | Accepted | [ADR-698](ADR-698-the-declared-path-no-fixture-carries.md) |
| ADR-699 | ADR-699 — Имя фикстуры связывалось ФАЙЛОМ, а не областью: операнд заказа G698 п. 1 был неверен в ОБЕ стороны | Accepted | [ADR-699](ADR-699-names-bound-by-the-file-not-the-scope.md) |
| ADR-700 | ADR-700 — Объединение по ИМЕНИ жило у ДВУХ дверей, и третья его форма отвечала зов имитатором: население вердикта 0, но операнд был неверен | Accepted | [ADR-700](ADR-700-the-by-name-union-lived-at-two-doors.md) |
| ADR-701 | ADR-701 — Вложенный контейнер, собранный вызовом: 18 ключей разобраны по природе, 34 пары были обвинены ложно | Accepted | [ADR-701](ADR-701-the-nested-container-built-by-a-call.md) |
| ADR-702 | ADR-702 — Цена СВОЕЙ односторонности измерена: 1 постоянная, 0 площадок; и рядом нашлась вторая дверь, промахом в ОБРАТНУЮ сторону | Accepted | [ADR-702](ADR-702-the-price-of-the-own-one-sidedness.md) |
| ADR-703 | ADR-703 — Шаги от постоянной до поля измерены (26 из 26), и ПРЕДЕЛ обхода, молчавший как «арифметики нет», получил своё число | Accepted | [ADR-703](ADR-703-the-limit-that-says-no-arithmetic.md) |
| ADR-704 | ADR-704 — Население ТРЁХ других дверей объявления измерено, и у двери манифеста офис искал объявление НЕ ПО ТОМУ АДРЕСУ: 13 артефактов из 133 | Accepted | [ADR-704](ADR-704-the-office-looked-for-the-declaration-at-the-wrong-address.md) |
| ADR-705 | ADR-705 — Цена слепоты к мутации после копии: мутируют документ 27 площадок из 78, вердикт неверен у ТРЁХ — и у одной в ОБРАТНУЮ сторону | Accepted | [ADR-705](ADR-705-the-mutation-after-the-copy-is-another-document.md) |
| ADR-706 | ADR-706 — у оси APY контракта провенанса не было ВООБЩЕ, и приёмка владельца читала догадку | Accepted | [ADR-706](ADR-706-the-apy-axis-had-no-provenance-contract-at-all.md) |
| ADR-707 | ADR-707 — Литерал производителя доезжал до числа, которое тот же путь читал назад | Accepted | [ADR-707](ADR-707-the-producers-literal-reached-the-number-it-read-back.md) |
| ADR-708 | ADR-708 — Ось TVL теневого блока: род оторван, литерал приезжал модульным словарём, и сторож ослеп от починки СОСЕДНЕЙ оси | Accepted | [ADR-708](ADR-708-the-tvl-axis-of-the-shadow-block-had-no-rod.md) |
| ADR-709 | ADR-709 — Ось APY отчёта владельцу: рода не было, а сам отчёт показывал 2 протокола из 36 | Accepted | [ADR-709](ADR-709-the-apy-axis-of-the-owners-report-had-no-rod-and-the-report-itself-was-nearly-empty.md) |
| ADR-710 | ADR-710 — Отчёт владельцу читал раздел СПИСКОМ, пока производитель писал СЛОВАРЬ | Accepted | [ADR-710](ADR-710-the-owners-report-read-the-section-as-a-list-while-the-producer-wrote-a-dict.md) |
| ADR-711 | ADR-711 — Отчёт владельцу `/protocols` не имел читателя ВОВСЕ; дверь построена и мерится у двери | 2026-10-13 · ACCEPTED | [ADR-711](ADR-711-the-owners-protocols-report-had-no-reader-at-all.md) |
| ADR-712 | ADR-712 — Набор команд владельца был объявлен ТРИЖДЫ; прибор органов владельца читал ту копию, которой Telegram не показывает | 2026-10-13 | [ADR-712](ADR-712-the-owner-organs-instrument-counted-a-list-telegram-never-shows.md) |
| ADR-713 | ADR-713 — Ярлык тира читался как СЫРЬЁ: 33 записи из 34 печатались владельцу заголовками `*1*`/`*2*`/`*3*`, а отсутствие тира подставлялось как T2 | 2026-10-13 | [ADR-713](ADR-713-tier-label-read-as-raw-33-of-34-records-outside-the-canon.md) |
| ADR-714 | ADR-714 — Доставка стёрла 56 записей циклов стоячего приказа владельца, и ни один сторож у двери об этом не сказал | 2026-10-13 | [ADR-714](ADR-714-delivery-erased-56-cycle-records-of-the-owners-standing-order.md) |
| ADR-715 | ADR-715 — «Кто новее» не защищает память: прибор расхождения копий называет НАПРАВЛЕНИЕ потери записей цикла | 2026-10-13 | [ADR-715](ADR-715-drift-instrument-names-the-direction-of-record-loss.md) |
| ADR-716 | ADR-716 — У оси ПАМЯТИ не было читателя: шаг 1 печатал `origin_check` и молчал про 94 пропавшие записи цикла | 2026-10-13 | [ADR-716](ADR-716-queue-reader-names-record-memory-loss.md) |
| ADR-717 | ADR-717 — «Не измерено» у оси памяти наследовалось молчанием от соседа | 2026-10-13 | [ADR-717](ADR-717-unmeasured-memory-axis-gets-its-own-cause.md) |
| ADR-718 | ADR-718 — Ось ПОРЯДКА гасла вместе с соседом, и класс был измерен на одной оси из трёх | 2026-10-14 | [ADR-718](ADR-718-order-axis-gets-its-own-word-when-nothing-was-compared.md) |
| ADR-719 | ADR-719 — Вердикт порядка не говорил, КАКАЯ из двух мерок его добыла | 2026-10-14 | [ADR-719](ADR-719-order-basis-names-which-axis-spoke.md) |
| ADR-720 | ADR-720 — Замок цикла обязан пережить РАБОТНИКА, а не ЗАПУСКАТЕЛЯ | 2026-10-14 | [ADR-720](ADR-720-cycle-lock-must-outlive-the-worker-not-the-launcher.md) |
| ADR-721 | ADR-721 — Захват карточки обязан мерить РАБОТНИКА, а не ЗАПУСКАТЕЛЯ | 2026-10-14 | [ADR-721](ADR-721-card-claim-must-measure-the-worker-not-the-launcher.md) |
| ADR-722 | ADR-722 — Запись журнала обязана нести РАБОТНИКА, а не запускателя; у совпадения метки появилось ПРОИСХОЖДЕНИЕ, у оси — измеренная частота | 2026-10-14 | [ADR-722](ADR-722-the-journal-entry-must-carry-the-worker-not-the-launcher.md) |
| ADR-723 | ADR-723 — ТРЕТЬЯ запись захвата (пересечение по объявленным ФАЙЛАМ) обязана мерить РАБОТНИКА; решение «чья метка» названо замером, а не аналогией | 2026-10-14 | [ADR-723](ADR-723-the-file-overlap-must-measure-the-worker-not-the-launcher.md) |
| ADR-724 | ADR-724 — ИЗМЕРЕННОЕ отсутствие работника обязано доезжать до вердикта: ось РАБОТНИКА спрашивалась там, где её ответ уже ничего не решал | принято · 2026-10-14 (#868) | [ADR-724](ADR-724-the-measured-absence-of-the-worker-must-reach-the-verdict.md) |
| ADR-725 | ADR-725 — Якорь ЗАПУСКАТЕЛЯ обязан доезжать до карточки: он измерялся и выбрасывался, а читатель брал его взаймы из журнала, которого на origin нет | принято · 2026-10-14 (#869) | [ADR-725](ADR-725-the-launcher-anchor-must-reach-the-card.md) |
| ADR-726 | ADR-726 — Прибор мутационного замера обязан быть ВВЕЗЁН: «убито 12» писали в ADR приборами, которые выбрасывали вместе с деревом | принято · 2026-10-15 (#870, доставлено #871) | [ADR-726](ADR-726-the-delta-mutation-instrument-must-be-committed.md) |
| ADR-727 | ADR-727 — `anchored` пересказывал ВХОД там, где читают ЗАПИСЬ, и у контракта писателя захвата не было сторожа ни одного | принято · 2026-10-15 (#872) | [ADR-727](ADR-727-anchored-must-measure-the-write-not-restate-the-input.md) |
| ADR-728 | ADR-728 — контракт якоря спрашивал ОДИН читатель из трёх, и у двух остальных вход вне контракта МОЛЧА выключал опознание своих объявлений | принято · 2026-10-15 (#873) | [ADR-728](ADR-728-the-anchor-contract-must-be-asked-by-every-reader.md) |
| ADR-729 | ADR-729 — у двери доставки была ОДНА единица смысла карточки, и она жила у двух карточек из ста трёх | принято · 2026-10-15 (#874) | [ADR-729](ADR-729-a-card-section-is-the-second-unit-of-meaning-at-the-delivery-door.md) |
| ADR-730 | ADR-730 — сторож канона тира судил о НАБОРЕ БАЙТ, был красен на верном состоянии 13 суток, и в другую сторону не видел двух форм ввоза из одиннадцати | принято · 2026-10-15 (#875) | [ADR-730](ADR-730-the-tier-canon-guard-must-judge-code-not-bytes.md) |
| ADR-760 | ADR-760 · Пульт: голосовой и текстовый ввод во входящие — первое и единственное действие пульта | 2026-10-15 · принято (включено владельцем на текущем пульте) | [ADR-760](ADR-760-cockpit-voice-and-text-intake-only-write-action.md) |
| ADR-761 | ADR-761 — перечень классов потери содержимого нигде не сверялся с перечнем вызовов двери | принято · 2026-10-15 (#876) | [ADR-761](ADR-761-every-content-loss-class-must-be-called-by-the-door.md) |
| ADR-762 | ADR-762 · Пульт владельца: детерминированное представление над Company Truth и граница защиты подтверждения | 2026-10-09 · предложено | [ADR-762](ADR-762-director-os-owner-view-model-and-version-bound-confirmation.md) |
| ADR-763 | ADR-763 · STUDIO-OS-NEXT-01: следующий этап Earn DeFi Studio OS по плану ARB (директива владельца 16.10) | 2026-10-16 · Accepted | [ADR-763](ADR-763-studio-os-next-stage-owner-directive-2026-10-16.md) |
| ADR-764 | ADR-764 · Достижимость взвода меряется ПОКРЫТИЕМ дней, а не 100 %-полосой одного гейта: мера глохла по мере накопления доказательств | принято 2026-10-16 (#877 → доставлено #880) | [ADR-764](ADR-764-arming-blockade-measured-by-coverage.md) |
| ADR-765 | ADR-765 — Советник, сравнивавший книгу с самой собой: «взвешивать было нечего» обязано быть ОТДЕЛЬНЫМ исходом | принято 2026-10-16 (#881) | [ADR-765](ADR-765-the-advisor-that-compared-the-book-with-itself.md) |
| ADR-766 | ADR-766 — Единица у читателей ленты вердиктов: кто считает ЗАПИСИ под словом «день» | принято 2026-10-16 (#882) | [ADR-766](ADR-766-the-unit-of-the-verdict-ledger-readers.md) |
| ADR-767 | ADR-767 — Бюджет дал прогону КОНЕЦ, но не дал ОТВЕТА: предмет мерится дешевле, а не бюджетом щедрее | принято 2026-10-16 (#883) | [ADR-767](ADR-767-a-budget-gave-the-run-an-end-not-an-answer.md) |
| ADR-768 | ADR-768 · Контрольный прогон CI по частям — единственный источник ПОЛНОГО вердикта набора | 2026-10-16 · Accepted | [ADR-768](ADR-768-ci-control-sharded-verdict.md) |
| ADR-769 | ADR-769 · Объявление агента обязано уметь сказать «намеренно выключен владельцем» | 2026-10-16 · Accepted (#884) | [ADR-769](ADR-769-agent-declaration-can-say-intentionally-off.md) |
| ADR-770 | ADR-770 — Критерий §49 `No regression` молча перестал отвечать: записи прогона не производил никто | 2026-10-17 · Accepted (#885) | [ADR-770](ADR-770-no-regression-criterion-went-silent-because-nobody-produced-the-record.md) |
| ADR-771 | ADR-771 — Строка, которая ничего не сказала, проходила за ответ: «не измерено» судится ПО ПРЕДМЕТУ | 2026-10-17 · Accepted (#887) | [ADR-771](ADR-771-a-row-that-said-nothing-passed-as-an-answer.md) |
| ADR-772 | ADR-772 — Окно мутационного прибора переживает процесс, его открывший: мутанта называет ЗАПИСЬ, а не восстановитель | 2026-10-17 · Accepted (#888) | [ADR-772](ADR-772-the-mutation-window-outlives-the-process-that-opened-it.md) |
| ADR-773 | ADR-773 — Второй мутирующий прибор несёт ТУ ЖЕ форму, и мутирует он money-path: окно у `mutation_gate.py` | 2026-10-17 · Accepted (#889) | [ADR-773](ADR-773-the-second-mutating-tool-carried-the-same-form-over-the-money-path.md) |
| ADR-774 | ADR-774 — У самой доставки окна не было: гейт судил одни байты, уехать собрались другие | 2026-10-17 · Accepted (#890) | [ADR-774](ADR-774-the-delivery-itself-had-no-window-between-the-gate-and-the-bytes.md) |
| ADR-775 | ADR-775 — Сторож читал УСТАНОВКУ pytest как прогон тестов и месяц держал `main` красным | 2026-10-17 · Accepted (#891) | [ADR-775](ADR-775-the-guard-read-an-installer-as-a-test-run.md) |
| ADR-776 | ADR-776 — Слепок доставки держал БАЙТЫ, но не РЕЖИМ: x-бит уезжал мимо всех гейтов | 2026-10-17 · Accepted (#892) | [ADR-776](ADR-776-the-pin-held-the-bytes-but-not-the-file-mode.md) |
| ADR-777 | ADR-777 · Лекарство доехало до ОДНОГО читателя, а цена жила в читающей модели | 2026-10-17 · Accepted | [ADR-777](ADR-777-the-remedy-reached-one-reader-while-the-cost-lived-in-the-read-model.md) |
| ADR-778 | ADR-778 · Порядок ADR-777 живёт в ОДНОЙ ленте из четырёх, а цена растёт сама | 2026-10-18 · Accepted | [ADR-778](ADR-778-the-remedy-lives-in-one-of-four-ledgers-and-the-cost-grows-by-itself.md) |
| ADR-779 | ADR-779 · Полная цена есть ПРОИЗВЕДЕНИЕ, и второй множитель не мерил никто | 2026-10-18 · Accepted (#896) | [ADR-779](ADR-779-the-full-price-is-a-product-and-nobody-measured-the-second-factor.md) |
| ADR-780 | ADR-780 · Цену считали у объявленного ВИДА, а файл разбирался вдвое чаще — и третий множитель нашёлся сразу за этим | 2026-10-18 · Accepted (#898) | [ADR-780](ADR-780-the-price-was-counted-at-the-declared-view-while-the-file-was-parsed-twice-as-often.md) |
| ADR-781 | ADR-781 · Карточка, которой на origin нет ВООБЩЕ, не была ничьим провалом — и поэтому не была ничьей работой | 2026-10-18 · Accepted (#899) | [ADR-781](ADR-781-a-card-absent-from-origin-entirely-was-nobodys-failure-and-therefore-nobodys-work.md) |
| ADR-782 | ADR-782 · Находка стояла постоянно, потому что объявить второй вид ленты было НЕЧЕМ | 2026-10-21 · Accepted (#900) | [ADR-782](ADR-782-the-finding-stood-because-declaring-the-second-view-was-impossible.md) |
| ADR-783 | ADR-783 · Упоминание вида считалось читателем, и мера неполноты врала в ОБЕ стороны | 2026-10-21 · Accepted (#901) | [ADR-783](ADR-783-a-mention-of-the-view-was-counted-as-a-reader.md) |
| ADR-784 | ADR-784 — запас печатался в РАЗАХ, а вопрос был в СУТКАХ; ряд всё это время лежал внутри ленты | 2026-10-22 · Accepted (#903) | [ADR-784](ADR-784-the-margin-was-printed-in-multiples-while-the-question-was-in-days.md) |
| ADR-785 | ADR-785 · Прибор печатал СРОК, а прочитать его было некому — пять решений без читателя | 2026-10-22 · Accepted (#906) | [ADR-785](ADR-785-the-instrument-printed-a-deadline-no-one-could-read.md) |
| ADR-786 | ADR-786 — сторож доставки не видел ВТОРОГО КЛОНА, и работа целого цикла была невидима | 2026-10-22 · Accepted (#907) | [ADR-786](ADR-786-the-delivery-guard-could-not-see-the-other-clone.md) |
| ADR-787 | ADR-787 · Те же байты разбирались дважды, потому что `verify()` выбрасывал свою работу | 2026-10-22 · Accepted (#908) | [ADR-787](ADR-787-the-same-bytes-were-parsed-twice-because-verify-threw-its-work-away.md) |
| ADR-788 | ADR-788 · Сторож публичных чисел 19,7 суток краснел на вопрос СВОЕГО ОКРУЖЕНИЯ, и 69-я тревога была бы неотличима от настоящей | 2026-10-23 · Accepted (#910) | [ADR-788](ADR-788-the-custodian-could-not-name-its-own-operand-in-ci.md) |
| ADR-789 | ADR-789 · Сцена доставки НИКОГДА не была рабочим деревом, и шесть суток сторож публичных чисел падал по чужой причине | 2026-10-23 · Accepted (#911) | [ADR-789](ADR-789-the-delivery-scene-was-never-a-working-tree.md) |
| ADR-792 | ADR-792 — Сторож вычета «ручного R&D» мерил ДОЛЮ, а его предмет — ПРАВИЛО | Accepted | [ADR-792](ADR-792-the-carve-out-watch-measured-a-ratio-not-its-subject.md) |
| ADR-791 | ADR-791 · Живость мутационного прогона спрашивали у ПАДДИНГА колонки, и возврат байтов пошёл под работающим прибором | Accepted | [ADR-791](ADR-791-window-restore-refuses-a-live-owner.md) |
| ADR-793 | ADR-793 — Усечение ленты по ВОЗРАСТУ: цена измерена, безопасного N нет | Accepted | [ADR-793](ADR-793-ledger-age-truncation-has-no-safe-window.md) |
| ADR-790 | ADR-790 — Производитель записи §49 `No regression` был написан и не позван: проводки не было ПО ПОСТРОЕНИЮ | Accepted | [ADR-790](ADR-790-no-regression-producer-wiring.md) |
| ADR-794 | ADR-794 — Цена ПЕРЕСЪЁМКИ описания измерена; окна она не открывает, и мешает не цена, а ФОРМА | Accepted | [ADR-794](ADR-794-the-price-of-re-recording-the-description-and-the-shape-that-blocks-it.md) |
| ADR-795 | ADR-795 — строка УПЛОТНЕНИЯ истории кандидата: мешала ФОРМА, и форма вылечена | 2026-10-24 · ПРИНЯТО · собрано циклом **#917**, ДОСТАВЛЕНО **ПОДЪЁМОМ цикла #918** | [ADR-795](ADR-795-the-compaction-record-that-opens-the-truncation-window.md) |
| ADR-796 | ADR-796 — дерево, из которого пушер читает байты, обязано быть НАЗВАНО | 2026-10-24 · ПРИНЯТО · собрано и ДОСТАВЛЕНО циклом #919, `origin/main 6d61e4d0` | [ADR-796](ADR-796-the-delivery-tree-must-be-named.md) |
| ADR-797 | ADR-797 — Отрезание ленты есть ПЕРЕНОС, и точка отрезания ИЗМЕРЯЕТСЯ, а не объявляется | 2026-10-24 · принято, доставлено | [ADR-797](ADR-797-the-ledger-cut-is-a-move-and-its-point-is-measured.md) |
| ADR-798 | ADR-798 — Трое недостающих писателей построены, и причина закрытого окна НАЗВАНА: мешает ПОРЯДОК списка, а не описание кандидата | 2026-10-24 · принято, доставлено | [ADR-798](ADR-798-the-three-missing-writers-and-the-order-that-blocks-the-cut.md) |
| ADR-799 | ADR-799 — Порядок кандидатов в ответе есть функция МНОЖЕСТВА, а не префикса ленты; и порядко-слепая мера оказалась не предсказанием, а другим вопросом | 2026-10-24 · принято, доставлено | [ADR-799](ADR-799-candidate-order-is-a-function-of-the-set.md) |
| ADR-800 | ADR-800 — население списков ответа, адресуемых по МЕСТУ: 37, носителей 0, и это ЗАМЕР | 2026-10-24 · принято · цикл #923 · 2026-10-24 · заказ **G799 п. 2** | [ADR-800](ADR-800-the-population-of-position-addressed-lists.md) |
| ADR-801 | ADR-801 — у переписи порядка появился ЧИТАТЕЛЬ, и проводка открыла седьмое звено: отметку ставили стенные часы | 2026-10-24 · принято · цикл #924 · 2026-10-24 · заказ **G800 п. 2** | [ADR-801](ADR-801-the-order-census-gets-a-reader.md) |
| ADR-802 | ADR-802 — у сторожа состава ступени появился МАШИННЫЙ критерий, и расхождение, из-за которого он молчал, закрыто | 2026-10-24 · принято · цикл #925 · 2026-10-24 · карточка | [ADR-802](ADR-802-the-stage-declaration-gets-a-machine-criterion.md) |
| ADR-803 | ADR-803 — операнд «площадок двери» СЛОЖЕН машинно, а не перепечатан, и сдвиг НАЗЫВАЕТ ведро с направлением | 2026-10-24 · принято · цикл #926 · 2026-10-24 · карточка | [ADR-803](ADR-803-the-door-operand-is-summed-not-reprinted.md) |
| ADR-804 | ADR-804 — у переписи порядка появилась запись о ЗВАВШЕМ, и вторая ось заказа перестала быть неизмеримой | 2026-10-24 · принято · цикл #927 · 2026-10-24 · карточка | [ADR-804](ADR-804-the-order-census-names-its-caller.md) |
| ADR-805 | ADR-805 — у класса «ступень с ТАКТОМ не называет ЗВАВШЕГО» появился ЧИТАТЕЛЬ, а грубая мерка класса ПЕРЕМЕРЕНА разбором | 2026-10-25 · принято · цикл #928 · 2026-10-25 · заказ **G804 п. 3** · карточка | [ADR-805](ADR-805-a-tact-stage-must-name-its-caller.md) |
| ADR-806 | ADR-806 · У ЗАКРЫТИЯ карточки появился и измеритель, и возчик — а зелёная строка сторожа стояла на ЧУЖОМ знаменателе | 2026-10-25 · Accepted | [ADR-806](ADR-806-the-closure-of-a-card-gets-both-a-meter-and-a-carrier.md) |
| ADR-807 | ADR-807 · Два owner-approved правила противоречили на одной карточке — у вопроса интейка появилась НАЗВАННАЯ ретракция | 2026-10-25 · Accepted | [ADR-807](ADR-807-the-intake-born-question-gets-a-named-retraction.md) |
| ADR-808 | ADR-808 · Критерий §49 `Auditability` приказа «Portfolio CIO» получил МЕРУ — оба прибора, мерившие его дословные слова, читателя не имели | 2026-10-25 · Accepted | [ADR-808](ADR-808-the-auditability-criterion-had-no-measure.md) |
| ADR-809 | ADR-809 · Последний критерий §49 приказа «Portfolio CIO» получил МЕРУ — прибор его дословных слов работал с 06.09 и читателя не имел | 2026-10-25 · Accepted | [ADR-809](ADR-809-the-shadow-verification-criterion-had-no-measure.md) |
| ADR-810 | ADR-810 · Сводка §49 слила «не измерено по существу» с «вердикт снят НЕ О ТОМ ДЕРЕВЕ» — и на этом предыдущий цикл назвал долгом критерий, который ВЫПОЛНЕН | 2026-10-25 · Accepted | [ADR-810](ADR-810-the-tally-merged-two-unmeasured-states.md) |
| ADR-811 | ADR-811 · Мера критерия §49 `Architecture` 27 дней не производилась: у писателя не было ЗВАВШЕГО, и ни один сторож не мог этого увидеть | 2026-10-25 · Accepted | [ADR-811](ADR-811-the-measure-of-a-criterion-had-no-caller.md) |
| ADR-812 | ADR-812 · Мера прихода производящего кода стояла на СОСЕДНЕМ файле — и ошибалась в ОБЕ стороны | 2026-10-25 · Accepted | [ADR-812](ADR-812-the-arrival-clock-stood-on-the-neighbouring-file.md) |
| ADR-814 | ADR-814 · Пол срока годности выводился из ОБЪЯВЛЕННОГО расписания — а объявление про такт врёт | 2026-10-26 · ACCEPTED | [ADR-814](ADR-814-the-floor-of-an-slo-came-from-the-declared-schedule.md) |
| ADR-815 | ADR-815 — запас поверх такта был откалиброван ТОЛЬКО по медленным производителям | 2026-10-26 · ACCEPTED | [ADR-815](ADR-815-the-margin-over-a-tact-was-calibrated-on-slow-producers-only.md) |
| ADR-816 | ADR-816 · У ОТРИЦАНИЯ объявленной оси должно быть ПРАВОМОЧИЕ (ADVISORY / приборы наблюдения) | 2026-10-26 · ACCEPTED | [ADR-816](ADR-816-a-denial-on-the-declared-axis-needs-standing.md) |
| ADR-817 | ADR-817 · У ВОЗДЕРЖАНИЯ была предпосылка, и её не проверял никто (ADVISORY / приборы наблюдения) | 2026-10-26 · ACCEPTED | [ADR-817](ADR-817-the-standing-of-an-abstention-was-never-checked-against-reality.md) |
| ADR-818 | ADR-818 · Объявленная ось судила сроки ОТСТАВНЫХ агентов (ADVISORY / приборы наблюдения) | 2026-10-26 · ACCEPTED | [ADR-818](ADR-818-the-declared-axis-judged-retired-producers.md) |
| ADR-819 | ADR-819 — Внутри ВЕРНОГО воздержания жил второй вопрос: а файл-то кто-нибудь пишет? | 2026-10-26 · принято | [ADR-819](ADR-819-the-second-question-inside-a-correct-abstention.md) |
| ADR-820 | ADR-820 — Канал атрибуции записи: он ЕСТЬ в системе и его НЕТ у населения вопроса | 2026-10-26 · принято | [ADR-820](ADR-820-is-there-a-channel-that-attributes-a-write-to-an-agent.md) |
| ADR-821 | ADR-821 — Чего стоил бы штамп атрибуции: дверь ОДНА у двух третей, и не там, где вопрос | 2026-10-26 · принято | [ADR-821](ADR-821-what-the-attribution-stamp-would-cost.md) |
| ADR-822 | ADR-822 — Кто прочтёт штамп атрибуции: правка дёшева, и 144 штампа из 153 пришли бы НЕМЫМИ | 2026-10-26 · принято | [ADR-822](ADR-822-who-would-read-the-attribution-stamp.md) |
| ADR-823 | ADR-823 — Дойдёт ли до цикла строка отчёта: цена ПОЛОЖИТЕЛЬНА, а один отчёт доезжал ПОСИМВОЛЬНО | 2026-10-26 · принято | [ADR-823](ADR-823-does-the-producers-report-line-reach-the-cycle.md) |
| ADR-824 | ADR-824 — Строка отчёта не называла каталог, по которому измерена: цена одна строка, читатель измерен | 2026-10-27 · принято | [ADR-824](ADR-824-the-report-line-that-did-not-name-its-data-directory.md) |
| ADR-825 | ADR-825 — Четвёрка, умевшая пожаловаться и не умевшая прочесть: 4 → 0 | 2026-10-27 · принято | [ADR-825](ADR-825-the-four-that-could-complain-but-not-read.md) |
| ADR-826 | ADR-826 — Третья строка сводки, которую не читал ни один прибор цикла: `SUBFAILED` | 2026-10-27 · принято | [ADR-826](ADR-826-the-third-line-of-the-summary-nobody-read.md) |
| ADR-827 | ADR-827 — У пропущенного теста был НОМЕР вместо имени | 2026-10-27 · принято | [ADR-827](ADR-827-the-skipped-test-that-had-a-number-instead-of-a-name.md) |
| ADR-828 | ADR-828 — Красный вердикт, который не мог назвать причину | Accepted | [ADR-828](ADR-828-the-red-verdict-that-could-not-name-a-reason.md) |
| ADR-829 | ADR-829 — Третий исход, у которого оказалось три двери | Accepted | [ADR-829](ADR-829-the-third-outcome-that-had-three-doors.md) |
| ADR-813 | ADR-813 · «Не выдерживаем 139» было ОДНИМ словом на ДВА состояния — и у 70 это слово было неверным | 2026-10-25 · Accepted | [ADR-813](ADR-813-one-word-for-two-states-of-an-unkeepable-slo.md) |
| ADR-830 | ADR-830 · Строка реестра решений судится по ФОРМЕ, а не по числу чёрточек; статус вне формы — НЕ ИЗМЕРЕН | принято | [ADR-830](ADR-830-the-registry-row-that-held-by-a-pipe.md) |
| ADR-831 | ADR-831 · Реестр решений приведён к объявленной форме целиком: статус измерен у каждой из 683 строк, а «не объявлен» трижды оказался свойством ЧИТАТЕЛЯ | принято | [ADR-831](ADR-831-registry-rows-brought-into-the-declared-form.md) |
| ADR-832 | ADR-832 · Ответ владельца 09.09 по лицензии данных — вариант 1, по первичной записи | Accepted | [ADR-832](ADR-832-license-answer-of-09-09-is-option-1-by-the-primary-record.md) |
| ADR-833 | ADR-833 · Ответы владельца 27.10 в сессии Claude Code (четыре вопроса пакета STUDIO-OS-DELIVERY-AND-BACKLOG-01) | Accepted | [ADR-833](ADR-833-owner-answers-2026-10-27-in-session.md) |
| ADR-834 | ADR-834 · Карточки решений закрывает Claude — по ЗАПИСАННОМУ ответу владельца | Accepted | [ADR-834](ADR-834-claude-closes-decision-cards-by-recorded-owner-answer.md) |
| ADR-835 | ADR-835 — путь тест-файла проводкой не является, и сторож, который так считал, предписал снять с учёта четыре настоящие сироты | Accepted | [ADR-835](ADR-835-a-test-file-path-is-not-a-caller.md) |
| ADR-836 | ADR-836 · Ответы владельца 27.10 в сессии Claude Code — шестнадцать вопросов очереди | Accepted | [ADR-836](ADR-836-owner-answers-2026-10-27-queue.md) |
| ADR-837 | ADR-837 · Предел `docs/STATE.md` меряет цену ЧТЕНИЯ, а не число строк | Accepted | [ADR-837](ADR-837-state-read-cost-is-what-the-limit-was-for.md) |
| ADR-838 | Предел цены чтения стоял на одном файле: реестр решений — 1 574 806 символов | Accepted | [ADR-838](ADR-838-the-read-price-limit-was-set-on-one-file.md) |
| ADR-839 | ADR-839 — Ответ из сессии — по точной записи реестра; «проверено» — по фактическому запуску пробы (ARB 27.10, R1/R2) | Accepted | [ADR-839](ADR-839-session-answer-and-work-packet-bound-to-exact-record-and-real-probe-run.md) |
| ADR-840 | ADR-840 — Колонка «Заголовок» реестра решений приведена к заголовку: 1 574 973 → 136 610 символов | Accepted | [ADR-840](ADR-840-register-title-column-is-a-title.md) |
| ADR-841 | ADR-841 — Вердикта CI на `main` не было четыре прогона подряд: версию pytest выбирал календарь, а не дерево | Accepted | [ADR-841](ADR-841-ci-pins-the-pytest-it-installs.md) |
| ADR-842 | ADR-842 — Освобождение, заработанное замером, до своего файла не доезжало: запись R&D-реестра не называла свой скрипт | Accepted | [ADR-842](ADR-842-earned-carve-out-did-not-reach-its-script.md) |
| ADR-843 | ADR-843 — Прибор оси РАБОТНИКА был написанной и не позванной проверкой; теперь его зовёт ступень моста | Accepted | [ADR-843](ADR-843-worker-axis-census-is-called-not-just-written.md) |
| ADR-844 | ADR-844 — Вердикт `SPA CI` на `main` система уничтожает САМА: приёмку ADR-841 даёт только контрольный прогон | Accepted | [ADR-844](ADR-844-the-ci-verdict-on-main-is-destroyed-by-the-next-push.md) |
| ADR-845 | ADR-845 — У вердикта контрольного прогона появился ЧИТАТЕЛЬ, и `conclusion` вердиктом не является | Accepted | [ADR-845](ADR-845-ci-control-verdict-gets-a-reader.md) |
| ADR-846 | ADR-846 — Разрешение владельца на пробный ход НЕ МОГЛО сработать ни в один день после выдачи | Accepted | [ADR-846](ADR-846-trial-grant-reachability.md) |
| ADR-847 | ADR-847 — Ответ владельца «допуск ×3» получил ИСПОЛНИТЕЛЯ, и на нём вскрылся зелёный критерий при расхождении ×97 | Accepted | [ADR-847](ADR-847-owner-answer-of-27-10-gets-an-executor.md) |
| ADR-848 | ADR-848 — Потолок размера читается как ФИЛЬТР предложений, а не как РАЗМЕР хода (вариант А приказа «Portfolio CIO» опровергнут) | Accepted | [ADR-848](ADR-848-proposal-is-never-cut-to-the-admissible-size.md) |
| ADR-849 | ADR-849 — Эксплуатация 28.10: launchd в синхронизации кода, тесты не пишут в рабочие данные, стенды decision_loop клоном APFS | Accepted | [ADR-849](ADR-849-ops-launchd-sync-test-isolation-decision-loop.md) |
| ADR-850 | ADR-850 — Предложение урезается до допустимого РАЗМЕРА хода ПЕРЕД вердиктом CIO (вариант Г; пороги владельца не ослаблены, RiskPolicy переспрошена) | Accepted | [ADR-850](ADR-850-proposal-is-cut-to-the-admissible-size-before-the-verdict.md) |

## Соглашения

- Нумерация: `ADR-NNN` (сквозная) либо `ADR-YL-NNN` (Yield Lab слой), `ADR-OWN-YYYY-MM` (пакеты owner-решений).
- Новый ADR: скопировать `_TEMPLATE.md` → `ADR-NNN-slug.md`, добавить строку в эту таблицу.

- Superseded-ADR не удаляем — помечаем статус и ссылку на заменяющий.
- `backfill TODO` — решение действует (описано в CLAUDE.md / коде), отдельный ADR-файл ещё не выписан.
