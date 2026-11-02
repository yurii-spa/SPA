---
trackerStatus:
  type: inbox
title: Тесты пишут в git-tracked data/ — сессионный сторож отказывает в КАЖДОМ прогоне CI (12 из 12 шардов), и зелёный контрольный прогон недостижим
status: in-progress
source: nimbalyst
created: 2026-11-02
finding_adr: ADR-899
twin_key: "sha256:890437eb234220571bcb6c0c765977fc00d0874ed9d489f51c11f8d60f625b9c"
acceptance_probe: tracked_data_untouched_by_declared_runs:run
claimed_by: cycle-95431
claimed_at: 2026-11-02T15:02:14Z
claimed_run_id: orchestrator-95431-A534AC2182534C44AA8D223D9B092A97
claimed_pid: 95431
claimed_pid_start: Mon Nov  2 15:46:22 2026
intake_kind: task
status_trail:
  - "2026-11-02T15:02:14.207499+00:00 new -> in-progress · queue.set_status · cycle-95431"
  - "2026-11-02T16:20:01.272683+00:00 in-progress -> new · queue.set_status · cycle-95431"
  - "2026-11-02T16:20:48.479968+00:00 new -> in-progress · queue.set_status · cycle-95431"
---

## Что измерено

Сессионный сторож `spa_core/tests/tracked_write_guard.py` отказывает в КАЖДОМ
контрольном прогоне CI, и его отказ не доходит до свода НИ ОДНОЙ строкой.

Замер 2026-11-02 по логам джоб (цикл #1012, ADR-899):

| прогон | sha | шардов с «НОВОЕ (вне базы)» | нарушений | назвал отчёт |
|---|---|---|---|---|
| 41435243848 | `8f34a8894` | **12 из 12** | 68 | **0** |
| 41410492012 | `539bccdd4` | ≥1 (шард 11) | 7 | 0 (как «незавершён») |

Семь модулей, пишущих в git-tracked `data/*.json` вне базы (шард 11,
прогон 41410492012): `test_concurrent_fetch` → `data/chains_status.json` ·
`test_defi_liquidation_cascade_risk_analyzer` → `data/liquidation_cascade_log.json` ·
`test_defi_points_to_token_conversion_analyzer` → `data/points_conversion_log.json` ·
`test_defi_protocol_stablecoin_peg_arbitrage_analyzer` →
`data/stablecoin_peg_arbitrage_log.json` ·
`test_protocol_defi_yield_source_sustainability_ranker` →
`data/yield_sustainability_rank_log.json` · `test_protocol_fee_structure_analyzer` →
`data/fee_structure_log.json` · `test_signal_aggregator_entrypoint_typing` → СЕМЬ
файлов `data/` сразу.

База `spa_core/tests/tracked_write_baseline.json` ПУСТА (`modules: {}`), то есть любой
такой модуль есть нарушение по построению. Дописывать в базу ЗАПРЕЩЕНО (инв. #16) —
чинить надо ТЕСТЫ: они обязаны писать в свою песочницу, а не в дерево.

## Почему это не косметика

Прогон CI не может быть зелёным, пока отказ жив: код выхода шарда всегда 1. ADR-899
сделал этот род ВИДИМЫМ для свода, но не починил его причину — пока модули пишут в
дерево, каждый шард кончается ненулевым кодом, и «зелёный контрольный прогон» в
проекте недостижим ПО ПОСТРОЕНИЮ.

## Две части работы (разные предметы, не смешивать)

1. **Починить семь модулей** — писать в `tmp_path`/песочницу. Мера — та же: прогон
   этих файлов не меняет `git status` дерева.
2. **ADR-899 оставил названную границу:** ветка свода стои́т под `shard_fails == 0`,
   поэтому отказ сторожа на шарде С ПРОВАЛАМИ по-прежнему невидим. Нужен ли отдельный
   канал от самого сторожа (чтобы свод называл ВИНОВНИКА, а не только род) — вопрос
   с ценой, и решать его надо замером населения, а не расширением наугад.

## Как понять, что готово

`SPA_ENV=ci PYTHONHASHSEED=0 python3 -m pytest <семь файлов> -q` не оставляет ни одной
строки в `git status -- data/`, а шард, их несущий, кончается кодом 0.

## Замер цикла #1013 (ADR-900)

**Предмет карточки (семь модулей) ЗАКРЫТ:** прогон семи — код процесса **1 → 0**,
`git status -- data/` **13 файлов → пусто**, `515 passed` как и было.

**Знаменатель карточки был НЕВЕРЕН, и это замер.** Семь — срез ОДНОГО шарда (11).
Население класса по логам всех двенадцати джоб прогона `41435243848` (`8f34a8894`):
**68 тест-модулей / 71 файл `data/`**. Закрыто **50 из 68** (падений 0,
`7645 passed, 1 skipped`); остаток 18 с НАЗВАННЫМ писателем вынесен в
`inbox-ostatok-klassa-test-pishet-v-git-tracked`.

**Часть 2 карточки (виновник в канале сторожа) НЕ тронута НАМЕРЕННО** — она стои́т
на замере населения сессионных сторожей, и расширять прибор наугад запрещено своей
же формулировкой. Остаётся заказом (G896 п. 4).

**Почему починены ПИСАТЕЛИ, а не тесты.** Карточка предлагала «писать в `tmp_path`».
Замер показал, что так уже сделано местами и протекло: у
`test_defi_protocol_stablecoin_peg_arbitrage_analyzer` есть фикстура `tmp_log`, у
`test_protocol_defi_yield_source_sustainability_ranker` — `_patch_log_path`, и оба
модуля ВСЁ РАВНО писали в дерево из других своих тестов. А
`test_signal_aggregator_entrypoint_typing` по построению гоняет ВСЕ модули Tier-C
реестра: подмена путей со стороны теста означала бы, что следующий добавленный
модуль реестра возвращает дефект молча. Поэтому закрыт писатель — через
единственную объявленную дверь `SPA_DATA_DIR` (ADR-849 §2), которую autouse-фикстура
`_isolate_data_dir` уже выставляет каждому тесту обоих корней.

## Почему критерий переобъявлен (п. 2 `.claude/rules/acceptance.md` исполнен, не обойдён)

Объявленная сначала проба `tracked_data_untouched_by_declared_runs` (без аргумента)
оказалась НЕИЗМЕРИМОЙ по цене: `test_card_acceptance.py::TestRegisteredProbesAreReal`
зовёт КАЖДУЮ пробу реестра, то есть сцену ~156 МБ и вложенный pytest по 50 модулям
строил бы КАЖДЫЙ из 12 шардов CI — ровно класс карточки
`inbox-pribory-brosayut-odnorazovyi-stend-87-gb`.

Правка самой пробы в работе запрещена, поэтому карточка возвращена в `new`, причина
названа здесь, и объявлен критерий `tracked_data_untouched_by_declared_runs:run`:
та же проба, тот же исход, но тяжёлый замер идёт ТОЛЬКО по явному аргументу. Без
аргумента проба отвечает «НЕ ИЗМЕРЕНО» с названной причиной — не «чисто».
Предмет критерия не ослаблен: `:run` мерит то же и тем же.
