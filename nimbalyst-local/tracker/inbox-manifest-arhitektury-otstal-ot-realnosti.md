---
trackerStatus:
  type: inbox
title: "Манифест архитектуры отстал от РЕАЛЬНОСТИ: три агента стали reboot-safe, тест красный на чистом origin"
status: done
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

---

## Закрыто циклом #132 (2026-08-06)

**Поправка к карточке:** описанный дрейф трёх агентов (`competitive_watch` / `novel_edge_rnd` /
`reboot_verify`) на момент взятия УЖЕ вылечен чужими коммитами между #131 и #132. На свежем
`origin/main` 57d0928aa красным был другой агент — `com.spa.morning_digest` с
`plist_source`/`schedule`/`program` = `null` при живом `launchd/com.spa.morning_digest.plist`.
Отчёт карточки на веру не принят: падение перемерено на чистом чекауте.

**Это третий рецидив одного поля**, и причина не в генераторе. История по коммитам манифеста:
`11432fa32`(#126) заполнено → `cbf295fdf` null → `7d752e741`(#128) заполнено → `cddc9417e`
null → `74236734f`(#130) заполнено → `e923c61ed` null. Plist лежит в репозитории во ВСЕХ этих
коммитах, генератор с дефолтными каталогами заполняет поля верно. Манифест — **производный**
файл: сессия генерирует его от своего дерева и отправляет пофайлово, поэтому дерево, созданное
до чужой починки, приносит старую механику обратно.

**Сделано.** (1) `--write`: изменены РОВНО три строки (diff 3+/3−, только `morning_digest`),
курируемые поля не тронуты; контроль #130 в обе стороны зелёный — `producer` артефакта
`data/agent_registry.json` = `com.spa.agent_health`, и он же декларирует артефакт в `produces`.
(2) Новая герметичная проверка `test_repo_plist_mechanical_fields_equal_the_plist` сверяет
ЗНАЧЕНИЯ `schedule`/`program` (тем же парсером, что у генератора) и `reboot_safe`, а не только
«поле не null»: отредактированный plist оставлял манифест непустым и правдоподобным, но лгущим.
Приоритет каталогов повторяет генератор (`launchd/` раньше `scripts/`) — шесть label'ов лежат в
обоих. Существующая проверка #130 не изменена ни на символ (инв. #16).

**Критерий «как понять, что готово» выполнен:** `pytest spa_core/tests/test_architecture_manifest.py`
= 25 passed на этой машине; на предфиксном манифесте новая проверка КРАСНАЯ (положительный
контроль на реальной аварии); две мутации сторожа красят ровно свою цель; откат sha256
байт-в-байт.

---

## Закрыто циклом #136 (2026-08-06): уже СДЕЛАНО, дубля не завожу

Шаг 1a протокола, вердикт **DONE** — и проверен прогоном, а не чтением.

`python3 -m pytest spa_core/tests/test_architecture_manifest.py -q` на ЧИСТОМ
чекауте `origin/main` (056320f9e, отдельный worktree, эта же машина) —
**25 passed**, включая
`RealManifest::test_generator_check_passes_on_this_machine_or_skips`,
который карточка описывала как красный. В манифесте у всех трёх агентов
`plist_source: launch_agents`, `reboot_safe: true`.

Дрейф вылечил цикл **#132** (коммит `a4b7f088f`) — он же прямо это записал:
«Карточка #131 описывала дрейф трёх агентов
(competitive_watch/novel_edge_rnd/reboot_verify) — он уже вылечен чужими
коммитами». Красным на тот момент был ДРУГОЙ агент (`com.spa.morning_digest`),
и #132 закрыл его, изменив ровно 3 строки и не тронув курируемые поля.

Контроль #130 в обе стороны тоже держится: `producer` артефакта
`data/agent_registry.json` = `com.spa.agent_health`, и он же продолжает
декларировать этот артефакт в `produces` — то есть требование «как понять,
что готово» выполнено целиком.
