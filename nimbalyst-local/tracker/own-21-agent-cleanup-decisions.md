---
trackerStatus:
  type: owner-decision
title: Навести порядок в агентах — реши по каждому пункту (сводка инвентаризации)
status: needs-owner
priority: high
owner: yuriycooleshov@gmail.com
blocks: Чистота агентского контура
created: 2026-07-15
legacy_id: AGENT-CLEANUP
---

## ✅ Оркестратор: выполнено 2026-07-15 (по ответу владельца)
- **П.1 — 3 retired ВЫГРУЖЕНЫ:** `digest_weekly`, `tier1_digest`, `weekly_backup` → `launchctl bootout`
  + plist'ы убраны из `~/Library/LaunchAgents/` (бэкап в `data/retired_plists_backup/`) + install-блоки
  удалены из `install_all_agents.sh`. self_heal их не оживит (в RETIRED_LABELS). Fleet 57→54.
- **П.2 — `novel-edge-rnd` ПЕРЕПОДЧИНЁН:** в его `SKILL.md` добавлен блок «НОВЫЙ ПРОТОКОЛ» (announce
  владения, запрет молча-править-тесты, owner-gated карточками, читать STATE, деплой агента только по карточке).

**Осталось (реши когда захочешь):** п.3 (возобновлять ли roadmap-loop — рекомендую НЕТ, см. `MIGRATION_FREEZE.md`);
п.4 (агенты «НЕПОНЯТНО»: bts-feed/monitor, dfb_capture, analytics_tier_b/c, base_gas_monitor,
governance_watcher, hy_cycle/lp_cycle, tier1_governance, checkpoint-7day — важны или в утиль). Карточка
остаётся `needs-owner` до твоего слова по п.3/п.4 (можно и «закрой, остальное потом»).

---

## Что случилось и почему это важно
Провёл полную инвентаризацию (глубже Этапа 0) — детали в `docs/AGENT_REGISTRY.md`. Нашёл несколько
вещей, требующих твоего решения. Автономный roadmap-loop уже остановлен (по твоему п.2), остальное
без твоего слова не трогаю.

## Что от тебя нужно (реши по каждому)

**1. Три RETIRED-агента загружены вопреки статусу** — `digest_weekly`, `tier1_digest`, `weekly_backup`
(помечены RETIRED в коде, но крутятся в launchctl).
→ Рекомендую: **выгрузить** (`launchctl bootout`) — они дублируют/устарели. Ответь «выгрузи 3 retired».

**2. `novel-edge-rnd`** — автономная Claude-R&D-задача (2×/нед, сама пишет в docs, тот же класс риска,
что и остановленный roadmap-loop).
→ Рекомендую: **переподчинить новому протоколу** (announce-лог, запрет молчать-править-тесты, owner-gated
через карточки) ИЛИ пока остановить. Ответь: «останови novel-edge» / «переподчини» / «оставь как есть».

**3. Автономный roadmap-loop** (`1345fef8`) — остановлен, состояние в `MIGRATION_FREEZE.md`.
→ Возобновлять? Рекомендую: **не возобновлять как есть**; если нужен — только под новым протоколом. Ответь.

**4. Агенты «НЕПОНЯТНО»** (нужна твоя ясность, живы ли по смыслу): `bts-feed`/`bts-monitor` (что за «bts»?),
`dfb_capture`, `analytics_tier_b`/`_c`, `base_gas_monitor`, `governance_watcher`, `hy_cycle`/`lp_cycle`,
`tier1_governance`, `checkpoint-7day`.
→ Рекомендую: по каждому скажи «важен» / «в утиль». Могу помочь разобраться, если что-то забыл.

## Как понять, что готово
Ты дал вердикт по пунктам 1–4 (хотя бы по 1–3; по 4 можно позже).

## Что будет после
Исполню: выгружу retired, переподчиню/остановлю novel-edge по твоему выбору, разберусь с «непонятными».
Каждое действие с агентами — через gate (`check_agent_before_deploy.sh`) и с записью.
