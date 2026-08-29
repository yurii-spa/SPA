---
trackerStatus:
  type: agent
title: Страж дрейфа флота не запускался 25 суток — у скрипта нет расписания, его просто некому звать
status: blocked
source: session-2026-08-05-daily-90pct-audit
created: 2026-08-05
priority: medium
domain: monitoring / деплой (advisory, НЕ money-path)
---

## Что нашли (замер 2026-08-05, аудит 90%)

`data/agent_health.json` в `system_issues` честно пишет:
`fleet parity stale 595.0h (>26h) — drift guard not re-run`.

595 часов = **24.8 суток**. `data/fleet_parity.json` последний раз записан **2026-07-11 15:45**.

Причина не в поломке проверки, а в том, что **её нечему запускать**:

- продюсер — `scripts/fleet_parity_check.py`, обычный скрипт;
- в `launchd/` **нет ни одного plist**, который бы его звал (`ls launchd/ | grep -i parity` — пусто);
- в дневном цикле (`scripts/run_daily_paper_cycle.sh`) вызова тоже нет.

То есть проверка «объявленный установщиком флот == plist'ы на диске == не-снятые агенты»
живёт как ручная команда. Её позвали один раз в июле и с тех пор не звали.

## Почему это важно

Это третий сторож из таблицы `.claude/rules/deployment.md` — тот, который отвечает на вопрос
«тот ли у нас СОСТАВ флота». `deployment_drift_monitor` отвечает про содержимое кода,
`deployment_acceptance` — про способность стартовать, `agent_health` — про пульс. Ни один из них
не заметит, что агент объявлен установщиком, но его plist не установлен (или наоборот — на диске
живёт plist давно снятого агента). Ровно этот класс аварий разбирался 2026-08-04.

Сейчас сторож не сломан и не врёт — он молчит, а `agent_health` про его молчание честно
предупреждает. Но предупреждение висит 25 суток и никем не закрывается: классический
«сигнал есть, адресата нет».

## Что сделать

1. Дать `scripts/fleet_parity_check.py` расписание — либо свой plist в `launchd/`
   (по образцу соседних агентов: bash-wrapper, логи в `/tmp/`, деплой через
   `scripts/check_agent_before_deploy.sh`), либо шаг в `run_daily_paper_cycle.sh`
   рядом с прочими сторожами. Второй вариант дешевле и не увеличивает флот на единицу.
2. Прогнать проверку **до** этого и записать, что она вообще показывает на текущем составе
   (за 25 суток состав менялся: карточка `agent-deployment-drift-guard`, синхронизации 03.08 и
   04.08, восстановление exec-бита у 67 entrypoints). Если она краснеет — сначала разобрать
   находку, а не гасить порог.
3. Положительный контроль по правилу `.claude/rules/deployment.md`: тест, который снимает
   plist у объявленного агента и убеждается, что проверка это ловит.

## Как понять, что готово

`data/fleet_parity.json` обновляется не реже раза в сутки, и `system_issues` в
`data/agent_health.json` больше не содержит строки `fleet parity stale`.

## Границы

Advisory-слой, money-path не трогает. RiskPolicy / kill-switch / пороги / живой трек —
не касаться. Прод-дерево двигать только по правилу `.claude/rules/deployment.md`
(acceptance до и после, каталогами целиком).

## Сделано 2026-08-05 (цикл #119): расписание есть — и оно сразу нашло расхождение

**Пункт 1 (расписание) — закрыт.** Вариант 2 карточки: шаг в `scripts/run_daily_paper_cycle.sh`
(Step 4), non-fatal, **без нового агента** — флот не растёт ради наблюдения за самим собой,
и `launchctl` из автономной сессии не трогается (мандат). Прод получает шаг сам: цикл на Step 0
синкает `scripts/` с origin перед запуском.

**Пункт 2 (что показывает на текущем составе) — измерено ДО того, как что-либо менять**
(2026-08-05 12:29Z, прод-дерево):

```
status DRIFT · declared 56 / plist 82 / retired 10
orphan_plist_not_declared (22): artifact_freshness, auto_push, cmo_editorial, competitive_watch,
  cpa_daily, fund-api, io_chief_investment, io_health, io_liquidity, io_market_regime,
  io_market_structure, io_onchain, io_protocol_risk, io_quant, io_red_team, io_reporting,
  io_stablecoin_yield, io_yield_quality, novel_edge_rnd, reboot_verify, telegram_watcher, work_digest
broken_declared_no_plist: []   ·   retired_but_installed: []   (обе — чисто)
live (хост): running 70 · declared_not_running: [redteam_rotation]
  · running_not_declared (15): весь блок io_* (12) + artifact_freshness, cmo_editorial, work_digest
```

Смысл простыми словами: **15 работающих агентов установщик не знает** — восстановление флота
установщиком их молча не вернёт. Порог не гасил, состав не трогал (правило
`.claude/rules/deployment.md` запрещает и то и другое). Решение о составе ушло владельцу
в уже существующую карточку `owner-decision-storozh-rashozhdeniya-flota-ne-zapuskals`
(новую заводить не стал — дубль; §1a протокола).

**Пункт 3 (положительный контроль) — закрыт.** `spa_core/tests/test_fleet_parity_scheduled.py`,
8 тестов. Существующий `test_fleet_parity_check.py` проверял ЛОГИКУ на подменённых множествах
(`monkeypatch` над `declared_labels`/`plist_labels`) и не покраснел бы ни от 597ч тишины, ни от
поломки разбора установщика. Новые тесты закрывают именно это:
- расписание: дневной цикл обязан звать проверку (мутация «убрать строку» → красный — **проверено**);
- шаг обязан оставаться non-fatal и `set -e` в цикле появиться не должно (мутация «сделать
  фатальным» → красный — **проверено**);
- отдельного агента-наблюдателя быть не должно (закрепляет выбранный вариант, чтобы следующая
  сессия не завела его молча);
- суточный кадэнс обязан помещаться в окно свежести `agent_health` (`FLEET_PARITY_STALE_H` 26ч),
  а пропуск суток обязан снова поднимать тревогу — контроль в обе стороны;
- **на настоящем дереве** (реальный разбор `install_all_agents.sh` + реальный glob по каталогам,
  без подмены множеств): сносим plist объявленного агента → `broken_declared_no_plist` ловит;
  кладём необъявленный plist → `orphan_plist_not_declared` ловит; та же метка в `RETIRED_LABELS` →
  снова OK (сторож не кричит на by-design);
- сквозной: штатный запуск оставляет файл, который `agent_health` читает как СВЕЖИЙ.

**Статус `blocked`:** инженерная часть доставлена; критерий «`system_issues` без строки
`fleet parity`» закрывается только решением владельца о составе флота. Строка
`fleet parity stale 597h` уже исчезла — файл обновлён; на её месте теперь честный `DRIFT`.
