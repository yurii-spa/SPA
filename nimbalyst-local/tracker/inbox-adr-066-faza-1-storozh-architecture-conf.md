---
trackerStatus:
  type: inbox
title: "ADR-066 Фаза 1: сторож architecture_conformance (B1–B5) + positive controls"
status: done
source: nimbalyst
created: 2026-08-05
adr: ADR-066
phase: 1
claimed_by: cycle-76334
claimed_at: 2026-08-05T21:39:59Z
---

spa_core/monitoring/architecture_conformance.py: fleet↔manifest в обе стороны, свежесть продуктов по SLO, замыкание потребления (consumer_required ⇒ потребитель+ресит), designed-дрейф, ролевые нарушения ADR-004. Семантика OK/UNCHECKED/WARN/CRITICAL, exit 0/1/2, старение слабых сигналов, data/architecture_conformance.json, алерт через push_policy. Тесты — репродукции находок аудита 2026-08-05 (реестр 19 дней, swarm_dwell вне реестра, io_* без потребителя). Launchd 6ч через deploy-gate. Приёмка: на текущем проде сторож КРАСНЫЙ ровно по находкам аудита. ADR-066 Контур B.

---

## ВЫПОЛНЕНО циклом #124 (2026-08-05)

**Доставлено:** `spa_core/monitoring/architecture_conformance.py` (B1–B5, семантика
OK/UNCHECKED/WARN/CRITICAL, коды 0/1/2, старение слабых сигналов, атомарный
`data/architecture_conformance.json`, алерт только через `push_policy` —
`architecture_conformance_critical` добавлен в закрытый Tier-1-whitelist),
`spa_core/tests/test_architecture_conformance.py` (**+72 теста**),
`scripts/agent_architecture_conformance.sh` + `launchd/com.spa.architecture_conformance.plist`,
запись агента и его артефакта в `architecture/manifest.json`.

**Приёмка карточки выполнена — сторож КРАСНЫЙ ровно по находкам аудита 2026-08-05.**
Живой read-only прогон на проде (exit 2, CRITICAL): B1 CRITICAL ×2 (`swarm_dwell`,
`artifact_freshness` — active без ребут-стойкого plist), B1 WARN ×9 (`unresolved`, слабые,
стареют), B2 CRITICAL ×1 (`agent_registry.json` 475.9ч при SLO 26ч = 18.3×), B3 CRITICAL ×13
(12 `io_*` + `system_briefing` без единого ресита). **B4 и B5 чисты — ложных красных нет.**

**Осознанные отличия от карточки (каждое — измерение, не удобство):**

1. **Launchd-агент подготовлен, но НЕ развёрнут.** Автономному циклу деплой агентов запрещён
   (мандат протокола) — `check_agent_before_deploy.sh` жёстко зашит на прод-дерево и
   выполняется в момент bootstrap. Проверено всё, что проверяемо без прода: `plutil -lint` OK,
   exec-бит на месте, сквозной прогон через канонический `agent_template.sh` — отчёт пишется,
   код возврата 0. Развёртывание → карточка владельцу
   `owner-decision-zapustit-storozha-arhitektury-on-gotov-n`.
2. **В манифесте агент объявлен `intent: designed`, не `active`.** `active` до bootstrap было бы
   ложью, и собственный B1 честно покраснел бы «active без persistent plist». B4 теперь
   стережёт его же самовольную активацию.
3. **Под launchd находки НЕ считаются сбоем процесса** (`--exit-zero-on-findings`). Иначе агент
   вечно висел бы в `agent_health` как `last_exit=2` — и настоящая поломка сторожа стала бы
   неотличима от честной находки. CLI по умолчанию сохраняет требуемые карточкой 0/1/2.
4. **B3 не требует читателя от не-`active` агента** — иначе у retired/designed рождалась бы
   находка, которую невозможно закрыть (мёртвый груз в очереди, урок
   `irreversible-unchecked-starves-queue`).
5. **B5 уточнён до трёх измеримых нарушений** (dev пишет в продуктовое пространство · два
   продюсера одного артефакта · `produces` расходится с `producer`) — «ролевые нарушения»
   в общем виде неизмеримы.

**Проверка:** 72 герметичных теста; **17 мутаций — каждая краснит ровно свою проверку**,
после отката 72/72 (снятие любой из B1–B5, старения, вердикта и fail-CLOSED-веток
воспроизводит настоящую аварию). Файл доказан календарно-независимым: те же 72 passed при
`NOW` = 2019-01-01 / 2026-08-05 / 2031-03-07 ⇒ пометка `FROZEN-DATE-OK` — решение на
протоколе, ратчет дат зелёный. mypy на новом модуле и на `push_policy` — чисто;
`lint_llm_forbidden` 170/0; `pre_deploy_check` 15/15 critical; `deployment_acceptance` OK.
Генератор манифеста `--check` = OK (90 агентов) — попутно устранён предсуществующий дрейф
механических полей `com.spa.morning_digest` (плановая работа генератора, курация не тронута).

**Порождённые карточки:** `owner-decision-zapustit-storozha-arhitektury-on-gotov-n` (развернуть,
needs-owner) · `owner-decision-devyat-agentov-visyat-nereshennymi-zakry` (9 `unresolved` →
ретайр/активация, R4 owner-gated) · `agent-registry-has-no-producer` (бэклог: у
`agent_registry.json` нет продюсера — корень находки B2).

**НЕ трогал:** RiskPolicy, kill-switch, пороги, живой трек `data/equity_curve_daily.json`,
launchd прод-хоста, `data/**` прода (прогоны — только в sandbox-каталогах `/tmp`),
`landing/**` в цикле не было. Ни один существующий тест не изменён — правки строго аддитивные.
