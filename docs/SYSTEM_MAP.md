# SYSTEM MAP — живая карта SPA (что где, зачем, статус)

> Durable-память проекта: чтобы любая сессия заходила как CEO+архитектор, а не «новый сотрудник».
> Растёт инкрементально по мере аудита (программа: `docs/SYSTEM_AUDIT_AND_ARCHITECTURE_PROGRAM.md`).
> Источник правды — git. Каждая подсистема получает секцию: **что · зачем · статус · проблемы**.
> Обновляется после каждого прохода архитектора. Начато 2026-07-16.

## Легенда статусов
🟢 живой/используется · 🟡 частично/сомнительно · 🔴 мёртвый/дубль/лишний (→ карантин `attic/`) ·
🔵 нужен-но-не-работает (чинить) · ⚪ не проверен (ждёт прохода).

---

## WS-B · Флот агентов + инфра (аудит 2026-07-16)
**SSOT: `data/agent_registry.json`** (авто-генерится `scripts/build_agent_registry.py`) + визуальный
дашборд `/admin/agents`. **58 агентов загружено, exit-78 антипаттерн полностью вычищен** (все bash-wrapper,
/tmp логи), нет `-9`/`78`. По ролям: monitoring 28 · allocation 9 · research 8 · infra 7 · reporting 6.
Живых KeepAlive-демонов с PID: apiserver:8765, cloudflared, dashboard:8767, familyfund:8766, cc-kanban,
rtmr_sense, telegram_bot.

**Проблемы (7, → карточки):**
- 🔴 **5 swarm + golive_freshness + resilience — загружены, но НЕ переживут reboot** (нет plist в
  `~/Library`; `self_heal.py:107` глобит только оттуда → не оживит). Инсталлер починен (swarm добавлены);
  golive_freshness/resilience — plist отсутствуют в репо (нужна реконструкция). → карточка fleet-hardening.
- 🟢 **morning_digest — ПОЧИНЕНО:** переиспользованный ретайренный лейбл → переименован в `work_digest` (attic).
- 🟡 **orchestrator 1ч** (owner 2026-07-16, осознанно) — ARMED code-writer, ежечасно.
- **install_all_agents.sh** — баг битого пути (aggressive_lab/rates_desk_paper) ПОЧИНЕН + 5 swarm добавлены.
- **Рассинхрон:** plists лежат и в `scripts/`, и в `launchd/` (installer читает из `scripts/`) — почистить.
- **SPOF:** весь live-слой на одном Mac Mini (owner-gated: offsite/HA).

**GitHub/CI (`yurii-spa/SPA`):** ci.yml + test.yml (частичный дубль) + ci-lite (cron-дубль) + spa-lint +
proof-gate + owner-gate + numbers-lint + site_freshness + site_content_audit + spa_alerts. `deploy-landing.yml`
= НЕ canonical (mirror, dispatch-only). Канонический деплой сайта = CF Pages git-integration (не workflow).

## WS-A · Файлы репозитория (по подсистемам)
_spa_core/{adapters,risk,governance,paper_trading,strategy_lab,swarm,monitoring,execution,api,reporting,
telegram,owner_queue} · scripts/ · data/ · docs/ · корень. Инвентарь каждого файла: роль, живой/мёртвый,
кто использует, дубли/junk._

⚪ _ждёт_

## WS-C · Сайт (аудит 2026-07-16)
**~103 `.astro`-страницы** + 2 генератора (sitemap/rss, детерминированные). noindex через meta: 12
(404, cockpit-kit, cockpit, dashboard-preview, 3 redirect-стаба тиров, 6×admin).

**Проблемы (→ карточки):**
- 🔴 **`/admin/*` БЕЗ аутентификации** (по комменту файла «access control = Phase 5, no auth yet»).
  Раскрывает аналитику/воронки/лог решений/RTMR. Защита только `robots.txt` + noindex (от индексации, НЕ
  доступа). Cloudflare Access не подтверждён в репо. **Главная дыра доступа.** → карточка (owner: CF Access).
- 🔴 **Осиротевшие leftover-страницы (0 входящих ссылок):** `/cockpit-kit` (синтетические фикстур-числа —
  trust-liability для «never fabricated» продукта) + `/dashboard-preview` (leftover app-shell). → в attic.
- 🟡 **`/board/*` + `/cockpit/*` подстраницы** отдают `index,follow` вопреки robots-Disallow (несогласов. noindex).
- 🟡 **Числа не сходятся:** conservative цитируется 7+ способами (2.7…6%), RWA-floor 3.3 vs 3.4, /packages
  LIVE-бейдж на волатильном дневном APY. + две таксономии тиров (Preserve/Core/Max vs Cons/Bal/Aggr). → owner-gated.
- 🟡 **`/pilot`** — конверсия без контактного механизма + вне top-nav (orphaned из главной).
Ключевые: `SiteHeader/SiteFooter/Layout.astro`, `pages/admin/index.astro`, `public/robots.txt`, `SITE_UIUX_BACKLOG.md`.

## WS-D · Архитектурная память
_Этот файл + PROJECT_CONTROL/ + Claude-memory + Obsidian-зеркало. Как всё связано и ПОЧЕМУ так устроено._

⚪ _в процессе (этот документ — начало)_
