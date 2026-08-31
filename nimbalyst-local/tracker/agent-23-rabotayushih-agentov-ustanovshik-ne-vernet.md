---
trackerStatus:
  type: inbox
title: 23 работающих агента установщик не вернёт — флот не соберётся заново с одного хоста
status: backlog
source: agent
created: 2026-08-31
---

## Что случилось

`data/fleet_parity.json` (31.08, 01:38): **объявлено установщиком 60 · plist на хосте 93 ·
работает 79**. Из работающих **23 отсутствуют в `scripts/install_all_agents.sh`**:

  · com.spa.architecture_conformance
  · com.spa.artifact_freshness
  · com.spa.cmo_editorial
  · com.spa.competitive_watch
  · com.spa.decision_loop
  · com.spa.intraday_equity
  · com.spa.io_chief_investment
  · com.spa.io_health
  · com.spa.io_liquidity
  · com.spa.io_market_regime
  · com.spa.io_market_structure
  · com.spa.io_onchain
  · com.spa.io_protocol_risk
  · com.spa.io_quant
  · com.spa.io_red_team
  · com.spa.io_reporting
  · com.spa.io_stablecoin_yield
  · com.spa.io_yield_quality
  · com.spa.monthly_statement
  · com.spa.novel_edge_rnd
  · com.spa.reboot_verify
  · com.spa.swarm_rank_demotion
  · com.spa.work_digest

Это значит: если машину придётся поднимать заново — переустановка вернёт 56 из 79 агентов,
а 23 не вернутся. Среди них не второстепенные: `architecture_conformance` (сторож
архитектуры), `artifact_freshness`, `decision_loop`, `intraday_equity`, весь ряд `io_*`.

Хост у нас **один** — это записанная SPOF. И заметить пропажу будет нечем: сторожа
здоровья знают лишь тех агентов, кого им объявили; не поднявшийся агент, которого никто
не ждёт, тишину не нарушит.

## Почему это отдельный вопрос, а не «сторож соврал»

В правиле доставки живут три вопроса — «та ли версия», «способен ли флот стартовать»,
«работают ли агенты». Ни один из них не отвечает на четвёртый: **соберётся ли флот заново.**
Приёмка честно говорит «79 точек входа, 0 сломанных» — про те 79, что уже стоят. О тех,
кто не встанет после переустановки, она молчать обязана: не её вопрос.

## Как чинить (предложение)

Дописать недостающие в `install_all_agents.sh` — но НЕ пачкой: у каждого проверить, что
он и должен работать (часть могла быть поставлена вручную для опыта и с тех пор не нужна).
Порядок: сверить список с манифестом (`intent`), отложить `retired`, остальных добавить
партиями с приёмкой после каждой; `launchctl` не трогать — установщик и так идемпотентен.

Обратный контроль обязателен: после правки `n_declared` обязано вырасти ровно на число
добавленных, а `running_not_declared` — уменьшиться на то же число. Тест — по артефакту
чётности, а не по глазам.

## Что уже сделано в эту ночь

Закрыт соседний путь: установщик больше не воскрешает отложенных в карантин (`af113900`).
Это была моя дыра — карантин исполнил, а путь возврата через штатную переустановку не закрыл.
