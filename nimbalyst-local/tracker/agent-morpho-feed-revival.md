---
trackerStatus:
  type: agent
title: Оживить живой TVL/фид morpho-семейства (own-29 вариант 1, дедлайн 2026-08-08)
status: done
source: own-29-decision-2026-08-05
created: 2026-08-05
priority: high
domain: adapters (read-only домен); дедлайн 08.08 → иначе демоут T1→T2 по own-29
---

Решение владельца по own-29: чинить фид. morpho_steakhouse ($40k, 40% капитала) держится с
tvl_source=static; morpho_blue — status=error live_feed_unavailable. Задача: найти корень
(маппинг пула DeFiLlama? gzip? chain-лейбл? pool-id устарел?), вернуть живой TVL+APY обоим.
Правила: .claude/rules/adapters.md (никаких fake-fallback: нет данных → None; тесты на
FakeFeed, не на живую сеть). Если к 2026-08-08 живого TVL нет — СТОП, возврат в own-29 к
варианту 2 (ADR + демоут). Контроль дедлайна — ежедневный 10:00-аудит.

## Как понять, что готово
adapter_orchestrator_status.json показывает morpho_steakhouse tvl_source=live (и floor $5M
пройден живым числом), morpho_blue без status=error; сигнал кураторов гаснет на следующем цикле.

> ВЫПОЛНЕНО 05.08 (41b6ebe0, за 3 дня до дедлайна): корень — DeFiLlama перевёл Morpho Blue на vault-символы; живой замер steakhouse: apy 3.51%, TVL $106M, tvl_source=live. Критерий own-29 выполнен — DEMOTE_SIGNAL погаснет следующим циклом (владелец закрывает own-29 после проверки). Находка: blue и steakhouse смотрят на ОДИН vault (оверлап концентрации) — advisory-заметка.
