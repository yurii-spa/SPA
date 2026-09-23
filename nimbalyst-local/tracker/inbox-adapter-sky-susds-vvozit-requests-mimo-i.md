---
trackerStatus:
  type: inbox
title: "Адаптер sky_susds ввозит requests — мимо инварианта #4 и мимо сторожа сети в тестах"
status: new
source: nimbalyst
created: 2026-09-23
---

## Что случилось и почему это важно

`spa_core/adapters/sky_susds_feed.py` ввозит `requests` — третьестороннюю
библиотеку — в рантайм-домене адаптеров. Это нарушение инварианта #4
(«только stdlib в рантайме»), и жило оно тихо с появления модуля: инлайн-шаг
`ci-lite.yml` каталог адаптеров не смотрел вовсе, а `scripts/lint_llm_forbidden.py`
смотрит адаптеры, но про третьесторонние библиотеки не спрашивает. Нашёл его
новый прибор `scripts/lint_forbidden_imports.py` (цикл #686, 23.09).

**Вторая половина цены важнее первой.** `spa_core/tests/network_guard.py`
прямо объясняет, что ЭТОТ фид минует сторожа сети в тестах — именно потому,
что ходит не через `urlopen`. То есть один незаконный импорт стоит двух
дыр: инвариант #4 и охват сторожа «в тестах нет живой сети».

Соседний фид `spa_core/adapters/defillama_feed.py` — чистый stdlib
(`urllib.request` + `gzip`), хотя докстрока sky-фида ссылается на него как на
оправдание («requests уже используется defillama_feed»). Ссылка устарела:
проверено 23.09, `requests` там нет.

## Что от тебя нужно

Ничего — задача агенту, не решение владельца.

Шаг 1. Перевести единственную точку вызова (`requests.get`, строка 176) на
`urllib.request` по образцу `defillama_feed` — сохранив семантику отказа:
любая сетевая ошибка → `None` + лог, наружу не поднимается (правило
`.claude/rules/adapters.md`, «никаких fake-fallback'ов»).

Шаг 2. Переписать стабы: `spa_core/tests/test_sky_susds_feed.py` подменяет
`spa_core.adapters.sky_susds_feed.requests.get` в восьми местах по ИМЕНИ.

Шаг 3. Снять оговорку в `spa_core/tests/network_guard.py`: после перевода
фид перестаёт быть исключением, и сторож сети начинает его накрывать.
Положительный контроль обязателен — иначе «охват расширен» непроверяемо.

Шаг 4. Удалить запись `spa_core/adapters/sky_susds_feed.py::requests` из
`scripts/forbidden_import_baseline.json`. База может только убывать;
`scripts/tests/test_lint_forbidden_imports.py::test_baseline_has_no_stale_entries`
краснеет, если запись осталась, а нарушение исчезло.

## Как понять, что готово

`python3 scripts/lint_forbidden_imports.py` даёт код 0 при ПУСТОЙ базе
(`known` без единой записи), тесты `spa_core/tests/test_sky_susds_feed.py`
зелёные без единого `mock.patch` на `requests`, и сторож сети накрывает фид.

## Что будет после

Инвариант #4 в адаптерах перестаёт держаться на том, что его никто не мерил,
а «в тестах нет живой сети» перестаёт иметь именованное исключение.
