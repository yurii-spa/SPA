# SPA — STATE (текущее состояние проекта)

> Живой файл состояния. Оркестратор читает в начале цикла и обновляет в конце.
> Живые оперативные цифры — `docs/SYSTEM_BRIEFING.md` (auto, 30 мин). Здесь — фокус,
> задачи, решения, вопросы. **Максимум ~150 строк.**

_Обновлено: 2026-07-15 (ручной снимок при setup среды v3, ветка `env-setup-v3`)._

---

## 🎯 Текущий фокус

- **ENV_SETUP_BRIEF_v3 — ЗАВЕРШЁН (все 8 этапов + smoke-test пройден 2026-07-15).** Files-first
  контур владельца живой: Owner Decisions + Inbox трекеры, протокол оркестратора, наблюдение :4455,
  Obsidian-база знаний. Ветка `env-setup-v3` (не запушена — мягкая заморозка).
  **Открытые owner-решения:** (1) вооружить автономный `com.spa.orchestrator` (сейчас INERT) или
  оставить attended; (2) мержить/пушить ветку `env-setup-v3`.
- **Go-live трек** — идёт фоном: ~24/30 evidenced дней (anchor 2026-06-22, target ~2026-07-21).
  Осталось просто дождать честных трек-дней. Кодом чинить нечего.

## 📊 Оперативный снимок (дрейфует — истина в SYSTEM_BRIEFING)

| Поле | Значение |
|---|---|
| GoLive | ⛔ **27/29 pass** — NOT READY (2 time-gated блокера) |
| Трек | **24/30** evidenced (anchor 2026-06-22, target ~2026-07-21) |
| Portfolio | ~$100,456 (+0.46%/24d), deployed 80% / cash 20%, ✅ policy-compliant |
| Аллокация | T1 45% · T2 35% · cash 20% · expected APY ~8.35% |
| Агенты | 56 загружено (`launchctl`), agent_health 46/46 nominal |
| KANBAN | v12.80 · done 1358 · 65 стратегий · 33 адаптера |

**GoLive блокеры (только ожидание, не баги):** `gap_monitor_30d`, `min_track_days_30` — оба
= 24/30 evidenced трек-дней, ждать ещё 6.

## 📋 Активные задачи

- [in progress] ENV_SETUP_BRIEF_v3 — Этапы 1–4, 6, 7 выполнены (память / Owner Decisions / протокол
  оркестратора / наблюдение :4455 / Inbox 3-входа / Obsidian-база знаний + промоушен `#promote`);
  остался **Этап 8 (smoke-test)** — по подтверждению владельца.
- [waiting] Go-live — накопление трек-дней до 30 (пассивно).

**⚠️ Амендмент к Этапу 6.3 (owner, 2026-07-15) — реализовать при Этапе 6:** разбор inbox
классифицирует сообщение на ЗАДАЧА → карточка с критериями / ИДЕЯ → `docs/ideas/` с датой (без
задачи) / НЕПОНЯТНО → `Needs Owner`. Telegram-бот отвечает: «создал задачу…» / «записал как идею» /
«есть вопрос — смотри карточку». Детали — journal `2026-W29.md`.

## 🗂️ Последние решения (одной строкой → ADR)

- **Правило (owner, 2026-07-15):** ничего «в воздухе» — любое решение/договорённость/пожелание из
  любой сессии фиксировать до её конца (решение→ADR+STATE, задача→Inbox, идея→docs/ideas/). Внесено в CLAUDE.md §Протокол-сессии п.4.
- **STOP автономного ROADMAP-loop (owner, 2026-07-15):** сессия `1345fef8` (PID 2853, запущена 02.07,
  «full autonomy») ОСТАНОВЛЕНА, полномочия отозваны. Состояние заморожено в `MIGRATION_FREEZE.md`
  (8 ships, остаток owner-gated, in-flight работы не было). Пережила Этап-0 т.к. это не LaunchAgent.
- **Единственная активная сессия SPA (owner, 2026-07-15):** первое окно закрыто, roadmap-loop
  полностью завершён; env-setup сессия (PID 94256) — теперь главная и единственная сессия SPA.
  Конкурентного клоббера больше нет. Работа — под новым протоколом (owner-gated карточками, announce,
  тесты не трогать молча). _(LOGOS `scanner.run` — отдельный проект, не SPA.)_
- **Ветка `yield-lab-scaffolding` на ревью (артефакт остановленной сессии):** локальная (не на origin),
  ~116 коммитов / 173 файла, docs-first Yield Lab research-слой, последний коммит 03.07. НЕ смержена.
  Мержить/нет — карточка `own-22` (риски: docs-overlap с origin, CLAUDE.md-конфликт, API-push-only).
  Точка восстановления — `PROGRESS.md` на ветке. Детали — `MIGRATION_FREEZE.md`.

## ⏸️ Отложено до MVP 2–3 (не потерять)

- **P3-стабы Yield Lab** (`docs/23,24,26,39–43`) на ветке `yield-lab-scaffolding` — оставлены как
  заглушки «TODO: expand at MVP 2-3» (часть 23/24/25/26/39–44 уже расширена в remediation-sprint;
  остаток — по мере строительства Yield Lab). Разворачивать при MVP 2–3, не раньше.
- **Остаток ROADMAP v2 (незавершённое остановленной сессии)** — durably в `docs/ROADMAP_2MONTH_EISENHOWER_v2.md`
  (не потеряется). Сессия аннотировала: `🔎 VERIFIED` = сделано (Q1-12,Q2-5b,8,9,15,17,18), `⚠️ NOTE` = отложено.
  Реально открытые код-задачи: Q2-7 (public /pilot+DD), Q2-11/12 (Uniswap-LP detection, отложены),
  Q2-13 (defenses→RTMR), Q2-14 (research-changelog → карточка own-20), Q2-16 (per-refusal SEO), Q2-19
  (non-custodial advisory pilot), Q3-7 (page-sprawl dedupe). Owner-gated Q1-5/6, Q2-3/4/5 → карточки own-*.
  **НЕ подхватываю автоматически** — приоритеты выбирает владелец (карточками, по одной, под новым протоколом).
- ENV_SETUP_BRIEF_v3 smoke-test пройден (owner-done→ingested, голосовой inbox, декомпозиция) → [ADR-TEST](decisions/ADR-TEST-smoke-2026-07-15.md).
- Two-tier kill-switch SOFT −5% / HARD −10% inclusive → [ADR-048](decisions/ADR-048-two-tier-kill-switch.md) (+ADR-034).
- RiskPolicy → governance-слой, API auth, exec-bypass закрыт → ADR-050.
- RTMR real-time monitoring sense-loop → ADR-053.
- Site Custodian (защита earn-defi.com от stale-чисел) → [ADR-YL-011](decisions/ADR-YL-011-site-custodian.md).
- SPA Swarm (5-слойный рой, advisory) → ADR-YL-012.
- Tier naming Conservative/Balanced/Aggressive; APY «up to {max}%»; /pilot = терминал воронки
  (форма, не mailbox); FAQ переписан под paper-стадию; /admin за Cloudflare Access;
  per-sleeve BELOW_FLOOR вердикты скрыты до улучшения → см. закрытые Q-OWN (ADR-OWN-2026-07).

## ❓ Открытые вопросы владельцу (трекер `nimbalyst-local/tracker/own-*.md`, статус `needs-owner`)

- **own-07** — включить письма-подтверждения подписки: `RESEND_API_KEY` + `WALLET_REF_SALT` на прод Railway.
- **own-08** — единая расшифровка «SPA» на сайте (3 варианта, дрейф). Рекомендация: «Smart Passive Aggregator» везде.
- **own-11** — /pilot «живой человек» (имя/фото/календарь) + рабочая почта (напр. `invest@earn-defi.com`).
- **own-13** — подтвердить формулировку early-access waitlist (M7). Рекомендация: ДА, честно.
- ~~own-06~~ — **РЕШЕНО/ingested:** проверил вживую — approvals на проде `status=scanned`, ключ работает.
  Возврат задачи был петлёй ежечасного `defi-checkup-build-cycle`; в его SKILL.md добавлен LOOP GUARD
  (проверять вживую перед докладом). Действий владельца не требуется.

> Мигрировано в files-first трекер (Этап 2). `docs/OWNER_DECISIONS_NEEDED.md` — теперь указатель.
> Отвечать: перевести карточку `needs-owner → owner-done` (в Nimbalyst или правкой `status:`).

## 👁️ Наблюдение (Этап 4)

- **Резервный монитор сессий/задач:** `claude-code-kanban` → **http://localhost:4455**
  (агент `com.spa.cc-kanban`, KeepAlive, read-only над `~/.claude`). Наблюдает headless-сессии
  оркестратора, которые Nimbalyst НЕ показывает.
- **Nimbalyst vs headless (проверено 4.2):** Nimbalyst трекает только сессии, которые запускает
  сам (`ai_sessions` = 1 строка на запущенную им сессию; 165 внешних SPA-транскриптов в `~/.claude`
  он не видит). Вывод: **headless — через claude-code-kanban:4455**; Nimbalyst — для интерактива,
  очереди, задач и мобильных аппрувов.

## 🔗 Ориентиры

- Инварианты: `CLAUDE.md` + `.claude/rules/`. Реестр решений: `docs/decisions/INDEX.md`.
- Живой статус: `docs/SYSTEM_BRIEFING.md`. Журнал: `docs/journal/`.
- Идеи (не действовать): `docs/ideas/`. Черновики правил: `docs/rules-draft/`.
- Протокол оркестратора: `docs/ORCHESTRATOR_PROTOCOL.md`. Очередь: `nimbalyst-local/tracker/`.
