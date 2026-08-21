---
trackerStatus:
  type: agent-task
title: "Включить redteam_rotation: 1021 строка состязательных сценариев написана и не бегает ни разу"
status: in-progress
priority: medium
source: аудит «без дела, но важно» 2026-08-21 (docs/AUDIT_IDLE_BUT_IMPORTANT_2026-08-21.md)
created: 2026-08-21
---

## Замер
`spa_core/redteam/` — 6 файлов / 1021 строка, тесты есть (2 файла), `scenarios.py` глубоко
импортирует rates_desk. Обёртка `scripts/agent_redteam_rotation.sh` и plist НАПИСАНЫ,
но агента НЕТ среди загруженных (AGENT_REGISTRY), в манифесте intent=retired; единственный
вызывающий (`scripts/smoke.py`) сам лежит в unwired-базе. Состязательная ротация против
proof-chain — ровно тот механизм, который в этом проекте многократно находил то, что
пропускали тесты (см. PR #11: 14 дефектов нашёл разбор, не CI).

## Что сделать
1. Прогнать runner вручную в песочнице — жив ли код против сегодняшнего rates_desk.
2. Решить судьбу: включить по расписанию (через гейт деплоя, инв. #12) ИЛИ честно
   удалить с plist'ом (правило: молча-мёртвого не держим). Рекомендация — включить:
   advisory, капитал не двигает, стоимость — один слот launchd.

## Как понять, что готово
`launchctl list | grep redteam` жив И артефакт ротации свежее 7 суток — либо каталога нет.


---

## Шаг 1 исполнен (2026-08-21): код ЖИВ — прогон в песочнице PASS

`python3 -m spa_core.redteam.runner` на свежем main: **8/8 сценариев поймали свои
подделки** (proof_chain_forge, exit_nav_output_forge, optimizer_over_concentration,
toxic_lrt_structural_veto, feed_nan_fabrication, sleeve_track_mutation,
kill_switch_ladder HARD_KILL на −12.4%, dashboard_tampered_integrity),
`live_data_untouched=True`, exit 0, секунды. Код не протух — включать безопасно.

## Остался шаг 2 — включение на Маке (действие владельца, инв. #12)

plist уже есть: `scripts/com.spa.redteam_rotation.plist` + обёртка
`scripts/agent_redteam_rotation.sh`. В манифесте агент помечен retired — при
включении intent надо поднять (курация, отдельный мини-ADR или строка решения).
Команда владельцу подготовится следующим циклом после решения; деплоить ≤3 агентов
за раз, через гейт (`check_agent_before_deploy.sh` — агент НЕ долгожитель, гейт можно).
