---
trackerStatus:
  type: agent-task
title: "Включить агента com.spa.site_freshness — код по ADR-098 доставлен, тело не загружено"
status: backlog
source: cycle-319-ingest
created: 2026-08-20
priority: high
tags: [site-custodian, deploy, adr-098, adr-085, manifest, launchd]
---

## Что уже сделано (не переделывать)

Цикл #319 исполнил решение владельца 20.08 12:34Z, вариант 1
(`owner-decision-storozh-saita-odnoi-komandy-ne-hvatilo-r`): Site Custodian публикует из **свежей
копии** с точкой отсчёта `origin/main`, а не из рабочей папки, отставшей на 665 коммитов.
Решение — **[ADR-098](../../docs/decisions/ADR-098-site-custodian-publishes-from-fresh-checkout.md)**.
Код в `scripts/site_freshness_monitor.py`, 14 тестов
(`spa_core/tests/test_site_custodian_fresh_checkout.py`), 13 краснеют на чистом origin, 3 мутации.

## Что осталось — и почему это отдельный заход

**Агент `com.spa.site_freshness` НЕ загружен.** Табличка «числа устарели» продолжает висеть на
`/track-record/` (`degraded: true`). Загрузка агента — деплой, а деплой автономная сессия не
делает (базовый протокол + п.6 правила `.claude/rules/deployment.md`: прод-дерево только с
разрешения владельца). Владелец разрешение на ВКЛЮЧЕНИЕ уже дал — этой же карточкой-предком
(«доделаю включение агента до конца тем же заходом» стояло в её разделе «Что будет после»), —
но #319 упёрся в честную границу: до включения код обязан ДОЕХАТЬ до прод-дерева, а автосинк
`launchd/` не возит.

## Acceptance (порядок обязателен)

1. `python3 -m spa_core.monitoring.deployment_acceptance` — **ДО** любого изменения дерева.
   Не `OK` ⇒ дальше не идти.
2. Синхронизировать `scripts/` **каталогом целиком** (правило доставки, п.2: копирование
   отдельных файлов между версиями дерева запрещено). `data/` не трогать (п.4).
   Проверить, что `scripts/agent_site_freshness.sh` и `launchd/com.spa.site_freshness.plist`
   реально лежат в прод-дереве — plist-а там не было вовсе (`launchd/` не синкается).
3. **Права — часть доставки** (п.3): `agent_site_freshness.sh` и `agent_template.sh` обязаны быть
   исполняемыми. Режим `100644` у точки входа launchd = агент мёртв (exit 126) и это не видно
   ни по одному пульсу (капкан 04.08). Если режим неверен на origin — чинить **на origin**.
4. Обязательный гейт (инв. #12): `bash scripts/check_agent_before_deploy.sh site_freshness`.
5. `launchctl bootstrap` — и **тем же заходом** перевести агента в `architecture/manifest.json`
   из `intent: designed` в `active`. Без этого шага сторож соответствия даст **ложную CRITICAL**
   «активация мимо ADR» на верное действие (ловушка названа в notes манифеста и в ADR-098).
6. `deployment_acceptance` — **ПОСЛЕ**. Плюс сверка кодов выхода `launchctl list | grep spa`.

## Как понять, что готово

Табличка «числа устарели» снимается с `/track-record/` **сама**, без человека, и это видно
прогоном: `degraded: false` в `landing/src/data/track_snapshot.json` **на origin**, а не только
локально. Критерий владельца дословно тот же, что в карточке-предке.

## Чего делать НЕЛЬЗЯ

- `--exit-zero` у агента (запрещён тестом): после ADR-084 ненулевой код возврата — ЕДИНСТВЕННЫЙ
  канал, которым недоставка сообщает о себе;
- снимать облачный прогон `.github/workflows/site_freshness.yml` — он остаётся вторым,
  независимым глазом (ADR-085);
- трогать числа, тиры, legal на сайте — owner-gated, к этой задаче отношения не имеет.
