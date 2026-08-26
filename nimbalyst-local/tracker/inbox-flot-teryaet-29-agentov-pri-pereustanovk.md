---
trackerStatus:
  type: inbox
title: Флот теряет 29 агентов при переустановке — plist есть, в установщике нет
status: new
source: nimbalyst
created: 2026-08-26
---

Сторож паритета флота `scripts/fleet_parity_check.py` держит `DRIFT` из-за **29 plist'ов,
которых нет ни в установщике `scripts/install_all_agents.sh`, ни в списке отставных**
(`agent_health_monitor.RETIRED_LABELS`). Замер 2026-08-26: `declared 60 / plist 93 / retired 10`.

Значение сироты по определению самого сторожа: агент либо работает на Маке, но **не переживёт
чистую переустановку или перезагрузку**, либо не работает вовсе, а его plist лежит и вводит в
заблуждение. Различить эти два случая из репозитория нельзя — нужен `launchctl list` на проде.

Список (29):

```
architecture_conformance  artifact_freshness  auto_push        btc_nav
cmo_editorial             competitive_watch   cpa_daily        decision_loop
fund-api                  intraday_equity     io_chief_investment
io_health                 io_liquidity        io_market_regime io_market_structure
io_onchain                io_protocol_risk    io_quant         io_red_team
io_reporting              io_stablecoin_yield io_yield_quality monthly_statement
novel_edge_rnd            reboot_verify       swarm_dwell      swarm_rank_demotion
telegram_watcher          work_digest
```

Тринадцать из них — слой `io_*` (продуктовые аналитики). Это ровно тот слой, про который
`.claude/rules/design-docs.md` отдельно оговаривает, что он ЖИВОЙ (в отличие от девяти
несуществующих слоёв) — тем неприятнее, что флот его теряет при переустановке.

**Почему отдельной задачей, а не мимоходом.** Каждое имя требует своего решения: подключить в
установщик · внести в `RETIRED_LABELS` как осознанно отставного · удалить plist. Угадать за 29
агентов разом нельзя, а «подключить все» превратило бы переустановку флота в загрузку 29
непроверенных агентов сразу — прямое нарушение «деплоить ≤3 агентов за раз» (инв. #12).

**Первый шаг:** снять на Маке `launchctl list | grep com.spa` и сверить с этим списком —
он разделит 29 на «работает, но потеряется» и «не работает, plist мусор». Без этого замера
решение по любому имени будет угадыванием.

Найдено при исполнении ADR-143 (подключение двух своих агентов); эти 29 — чужие, к пакету
ADR-133…142 отношения не имеют и существовали до него.
