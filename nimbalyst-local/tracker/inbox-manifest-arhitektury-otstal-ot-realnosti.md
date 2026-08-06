---
trackerStatus:
  type: inbox
title: "Манифест архитектуры отстал от РЕАЛЬНОСТИ: три агента стали reboot-safe, тест красный на чистом origin"
status: new
created: 2026-08-06
---

## Факт (измерено циклом #131, 2026-08-06)

`test_architecture_manifest.py::RealManifest::test_generator_check_passes_on_this_machine_or_skips`
**красный на ЧИСТОМ чекауте `origin/main` 11abfaf1c** (отдельный worktree без каких-либо
правок — падение воспроизведено байт-в-байт, к работе цикла #131 отношения не имеет):

```
DRIFT: com.spa.competitive_watch: plist_source 'repo:launchd/com.spa.competitive_watch.plist' → 'launch_agents'
DRIFT: com.spa.competitive_watch: reboot_safe False → True
DRIFT: com.spa.novel_edge_rnd:    plist_source 'repo:launchd/com.spa.novel_edge_rnd.plist'    → 'launch_agents'
DRIFT: com.spa.novel_edge_rnd:    reboot_safe False → True
DRIFT: com.spa.reboot_verify:     plist_source 'repo:scripts/com.spa.reboot_verify.plist'     → 'launch_agents'
DRIFT: com.spa.reboot_verify:     reboot_safe False → True
ИТОГ: манифест НЕ соответствует фактам (0 схемных, 6 дрейфовых)
```

## Чем это отличается от прошлого раза

Это НЕ повторение `agent-manifest-drift-morning-digest` (там агента забыли внести; цикл #130
закрыл его коммитом `74236734f`). Здесь дрейф в **другую сторону и по хорошей причине**:
три агента переехали из репо-plist в `~/Library/LaunchAgents`, то есть **перестали быть
reboot-unsafe** — ровно то, чего добивался блок 1 ADR-066. Реальность улучшилась, а манифест
об этом не знает. Сторож краснеет ПРАВИЛЬНО.

## Что сделать

Привести манифест к фактам (`scripts/build_architecture_manifest.py --write` лечит механические
поля `plist_source` / `reboot_safe`). **Внимание, грабли цикла #130:** генератор НЕ владеет полем
`producer` и курируемыми значениями — механический `--write` их затирал, и `main` от этого
краснел трижды. Перед пушем сверить `producer` у `data/agent_registry.json` и `produces`
у `com.spa.agent_health` (см. коммит `74236734f`).

## Почему цикл #131 не сделал этого сам

`architecture/manifest.json` объявлен в чужом владении: сессия `pid88160` объявила его
2026-08-06T08:20:31Z, за десять минут до начала цикла #131. Правка чужого файла без сверки —
ровно то столкновение, из-за которого одну задачу уже делали дважды. Плюс правка требует
проверки курируемых полей, а не «--write и в пуш».

## Как понять, что готово

`python3 -m pytest spa_core/tests/test_architecture_manifest.py -q` зелёный на чистом чекауте
origin НА ЭТОЙ МАШИНЕ, и при этом `producer` у реестра флота не `null`, а
`com.spa.agent_health` продолжает декларировать `data/agent_registry.json` в `produces`
(контроль в обе стороны, чтобы не повторить #130).

---

*Похоже на `agent-manifest-drift-morning-digest` (backlog) — тот же КЛАСС, другой набор агентов
и другая причина; проверь, не стоит ли закрыть их одной правкой. Найдено полным прогоном
`spa_core/tests/` цикла #131: 1 failed / 92205 passed, единственное падение — это.*
