---
trackerStatus:
  type: agent
title: Построить слой инвест-агентов «Head of Investment» (кураторы тиров + капитал-по-тирам + максимизаторы + решающий)
status: backlog
source: owner-directive-2026-07-23
created: 2026-07-23
priority: high
domain: money-path / governance (RiskPolicy НЕ трогать; ADR + pre_cutover_gate обязательны)
---

## Что это

Владелец-директива (2026-07-23): целевая многоагентная инвест-структура. Полное видение —
`docs/ideas/2026-07-23-head-of-investment-agent-layer.md`. Четыре роли:
1. **Кураторы тиров** — ведут T1/T2/T3, периодически пере-проверяют и ДВИГАЮТ протоколы между тирами
   (T3→T2→T1 и обратно при деградации).
2. **Капитал-по-тирам** — какой % в T1/T2/T3, зависит от типа стратегии.
3. **Максимизаторы доходности** — не держать 40% в 3%, если рядом тот же тир даёт 6% (с анти-churn).
4. **Head of Investment** — финальное решение «куда/сколько/почему», залогировано, синтез входов.

## Что нужно (поэтапно, не big-bang)

- Промоушен владельцем (#promote в idea-файле) → ADR нового слоя.
- Первый кирпич: yield-improvement триггер ребаланса — `agent-allocator-yield-frozen-rootcause.md`.
- Затем: формализация тир-курации (динамические тиры), капитал-по-тирам по типу стратегии, дирижёр.
- Всё внутри потолков RiskPolicy v1.0, детерминированно, LLM запрещён, fail-CLOSED, money-path через
  `pre_cutover_gate` + ADR, в изолированном workspace.

## Как понять, что готово

ADR принят; первый кирпич (yield-триггер) в проде paper-трека и доказан тестом; тир-курация двигает
протокол между тирами по критериям; Head-of-Investment пишет обоснование каждого решения.

## Что будет после

Разбивка на подзадачи по 4 ролям после промоушена. Блокирует полноценную «умную» аллокацию к go-live.

---

## Волна 0 триажа, 16.08 — что эта карточка теперь покрывает

Схлопнута сюда (кластер К14 `docs/BACKLOG_TRIAGE_2026-08-16.md`, переведена в `done`, с диска
не удалена):

- **`inbox-task-portfolio-cio-dynamic-capital-alloc`** — «TASK — Portfolio CIO: Dynamic
  Capital Allocation & Rebalancing», подробная спецификация владельца из Телеграма к ролям
  3 и 4 этой карточки (максимизаторы доходности + решающий). Требует: net expected return
  вместо raw APY, учёт стоимости ребаланса / gas / slippage / exit cost, устойчивость APY
  (transient spikes не вызывают сделок), влияние размера позиции, невозможность обойти
  Risk Policy, детерминизм. Полный текст задания — в теле схлопнутой карточки.

**Цепочка ссылок интейка ведёт сюда.** Шесть мусорных карточек, на которые интейк разорвал
тот же документ владельца (`inbox-why-it-exists`, `inbox-actual-costs`,
`inbox-apy-persistence-confidence`, `inbox-100-zapuskov-na-odnom-snapshot`,
`inbox-dlya-kazhdogo-etapa-pokazat`, `inbox-esli-tot-zhe-target-mozhno-priblizit-pro`),
уже закрыты; они адресуются к `inbox-task-portfolio-cio-dynamic-capital-alloc`, а та — сюда.

**Уже принятое по теме, чтобы не переделывать:**
`docs/decisions/ADR-088-portfolio-cio-advisory-layer.md` и
`ADR-089-portfolio-cio-followups-2026-08-15.md` — Portfolio CIO остаётся на ступени SHADOW
до эвиденса на живых данных; правило ADR-055 «ниже медианы — не максить потолок» применяется
в расчёте весов СНАЧАЛА в shadow и зависит от сведения двух путей APY.
