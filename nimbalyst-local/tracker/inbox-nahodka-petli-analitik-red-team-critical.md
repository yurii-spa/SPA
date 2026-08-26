---
trackerStatus:
  type: inbox
title: "Находка петли: аналитик red_team: CRITICAL — требует реакции (карточка/решение), не п"
status: new
source: nimbalyst
created: 2026-08-10
finding_key: "gap:analyst_red:red_team"
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
