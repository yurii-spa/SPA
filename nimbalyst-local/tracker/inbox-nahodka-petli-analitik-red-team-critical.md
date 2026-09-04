---
trackerStatus:
  type: inbox
title: "Находка петли: аналитик red_team: CRITICAL — требует реакции (карточка/решение), не п"
status: done
source: nimbalyst
created: 2026-08-10
finding_key: "gap:analyst_red:red_team"
status_trail:
  - "2026-09-04T08:32:27.343096+00:00 new -> done · queue.set_status · cycle-51832"
---

Находка петли ADR-066 (house_view_gap, WARN, подтверждена 2 прогонами подряд):

аналитик red_team: CRITICAL — требует реакции (карточка/решение), не пролистывания

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `gap:analyst_red:red_team` · ADR-066_

---

## Перепроверка (cloud-сессия владельца, 26.08) — не измерено статикой, нужны живые данные

`spa_core/investment_os/agents/red_team.py` + `spa_core/monitoring/house_view_gap.py`:
находка идёт от ЖИВОГО `data/investment_os/red_team.json` (посадка RED/CRITICAL) и
`data/threat_reactor_status.json` (`kill_switch_already_active`) — оба файла в `.gitignore`,
в git их нет (только устаревшая фикстура `attack_simulation_log.json` со `critical_count: 0`).

Коммит `faa26b703` (10.08, тот же день) починил ТОЛЬКО текст объяснения (`posture_reason`
называет причину CRITICAL — свой стоп-кран или реальная угроза), но собственный текст
коммита прямо говорит: «CRITICAL остаётся CRITICAL, ослабления нет». `finding_key` намеренно
не менялся, чтобы не создать вторую карточку.

Мост закрывает такие карточки САМ, когда находка перестаёт появляться в свежем прогоне —
по коду это должно произойти автоматически, если сегодня посадка уже не RED/CRITICAL.
Живым прогоном на хосте это не перепроверялось (данные gitignored, из cloud-сессии не видны).
Settle-файлы: `data/investment_os/red_team.json` (поле posture) +
`data/threat_reactor_status.json` (`kill_switch_already_active`).

Карточка остаётся `new` — честно «не измерено» из cloud-сессии, а не «решено».

---

## ЖИВОЙ ЗАМЕР С ХОСТА — цикл #480 (2026-09-04), карточка закрыта

Карточка ждала ровно того, чего cloud-сессия 26.08 честно не могла сделать: замера по
gitignored-файлам. Сделан на хосте, из прод-дерева.

| что | значение | откуда |
|---|---|---|
| `red_team.json` → `posture` | **`NO_THREAT_OBSERVED`** (не CRITICAL) | `data/investment_os/red_team.json`, 2026-09-03T23:32:54Z |
| `posture_reason` | `[]` — называть нечего | там же |
| `threat_reactor_status.kill_switch_already_active` | **`False`** | `data/threat_reactor_status.json` |
| находка `gap:analyst_red:red_team` в свежем отчёте | **ОТСУТСТВУЕТ** | `data/house_view_gap.json`, 2026-09-04T05:48:48Z — в нём только `gap:opportunity_explained:spark_susds` и `gap:opportunity_no_idle_capital:pendle_pt_susde` |

Критерий карточки («находка исчезает из отчёта источника при следующем прогоне») **выполнен**.

**Почему карточка простояла `new` 25 дней после того, как работа была сделана.** Мост её
ЗАКРЫЛ — в прод-дереве она `status: done`, а `data/findings_bridge_state.json` держит по ключу
`gap:analyst_red:red_team` запись `status: closed`, `last_seen: 2026-08-11T07:03:01Z`. Но
`nimbalyst-local/` из прода на origin не возит никто (мост везёт только своё за прогон,
ADR-081), поэтому на origin осталась копия от 10.08 в статусе `new` — и каждый цикл, читающий
очередь из worktree на origin/main (как велит §3.4), видел живую находку там, где её давно нет.
Это НЕ ошибка моста и не расхождение следов: на origin следа (`status_trail`) нет вовсе,
стирать нечего, и настоящее закрытие в проде эта запись не трогает.

Закрыто по СВОЕМУ замеру, а не переносом чужого статуса.
