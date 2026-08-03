---
trackerStatus:
  type: agent-task
title: "CI-Lite красный с 02.08: mypy на allocator.py:244 — ADR-061 читает JSON, не проверяя, что это объект"
status: done
source: session-2026-08-03-cycle95
created: 2026-08-03
---

## Как найдено

Шаг 0a/0b цикла #95 прошли, очередь на origin ПУСТА (inbox `new`=0 / owner-done=0 /
promotions=0 / заметок=0), все четыре backlog-карточки взять нельзя (две помечены «не брать,
пока владелец не ответил», одна `UNCHECKED` по fail-CLOSED, одна занята свежим захватом).
Сверка реального состояния CI на `main` через Actions API показала **два разных красных**, а не
один: помимо известного `agent-spark-apy-tests-assert-a-fallback-adr-063-removed` (`SPA Tests` /
`SPA CI`) красным стоит **третий workflow — `SPA CI-Lite`**, и на него карточки нет.

## Что измерено (дословно)

Прогон `SPA CI-Lite (syntax + import)` `30781439364` (sha `49d0d1122`, 2026-08-03T03:17Z),
джоб `Syntax & Import Check` → **шаг 9 `Type check — mypy on key modules` = failure**:

```
spa_core/allocator/allocator.py:244: error: Returning Any from function declared to return
    "dict[Any, Any]"  [no-any-return]
Found 1 error in 1 file (checked 4 source files)
```

Падение шага 9 обрывает джоб — шаги 10 (`Import check — all spa_core modules`) и 11
(`Registry check — >= 20 strategies`) уходят в `skipped`, т.е. **две проверки гейта не
выполняются вообще** (тот же механизм, что описан в цикле #31 для CI-Lite).

**Это свежая регрессия, а не «предсуществующее».** История прогонов CI-Lite:

```
success 4b5a0e45d 2026-08-02T13:26:36Z
failure 19666683a 2026-08-02T19:14:04Z   ← первый красный
failure 49d0d1122 2026-08-03T03:17:15Z
```

`git log -S "def _read(path: Path) -> dict:"` даёт ровно один коммит — **`f35ff96ed`
«ADR-061: evidence gate in money-path allocator»** (2026-08-02 18:40 +0200). Он и внёс функцию.

## Что не так (по существу, не только про типы)

```python
def _read(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning(...)
        return {}
```

`json.loads` отдаёт `Any`, и аннотация `-> dict` ничего не проверяет — **валидный JSON,
который не является объектом, проходит насквозь**. Докстринг `_load_evidenced_apy` обещает:
«Never raises: any unreadable/invalid input contributes nothing». Обещание неверно: `try`
накрывает только чтение и разбор, а не форму результата. Файл-источник доказательств
(`adapter_orchestrator_status.json` / `adapter_status.json`), содержащий, например, `[]` или
`"text"` (валидный JSON, не объект), даёт `AttributeError` на `orch.get("generated_at")` —
**неперехваченное исключение в money-path аллокаторе**, ровно там, где ADR-061 требует
fail-CLOSED-отказа. Это тот же класс, что #29/#31/#35–#38: контракт утверждает свойство,
которого измерение не даёт.

## Что предлагается сделать

Сузить `_read` до фактического контракта: не-`dict` — такой же «нечитаемый вход», как битый
JSON (лог + `{}`), с вербатим-цитированием фактического типа. Одна правка закрывает и mypy
(`Any` больше не возвращается), и латентный `AttributeError`. Поведение на всех валидных
объектных входах — байт-в-байт прежнее.

## Acceptance criteria

- `MYPYPATH=. mypy` набором ключевых модулей из `ci-lite.yml` — **0 ошибок** (шаги 10/11 гейта
  снова выполняются);
- не-объектный валидный JSON в любом из двух источников доказательств больше не роняет
  `_load_evidenced_apy`, а честно не даёт доказательств (fail-CLOSED, инв. #2);
- герметичные тесты: красные на коде `origin/main` до фикса + положительные контроли, что
  нормальный объектный вход НЕ клампится и книга не сдвигается;
- ни один существующий тест не ослаблен и не изменён (инв. #16);
- RiskPolicy, пороги, kill-switch, живой трек `data/equity_curve_daily.json` — не трогать.

---

## Сделано (автономный цикл #95, 2026-08-03)

**Воспроизведено на чистом `origin/main` `49d0d1122` ДО правок — шесть падений**, не одна ошибка
типов:

```
orch = []             -> AttributeError: 'list' object has no attribute 'get'
orch = "text"         -> AttributeError: 'str' object has no attribute 'get'
orch = 5              -> AttributeError: 'int' object has no attribute 'get'
orch adapters = 5     -> TypeError: 'int' object is not iterable
status = []           -> AttributeError: 'list' object has no attribute 'get'
status adapters=[1,2] -> AttributeError: 'list' object has no attribute 'items'
```

**Фикс.** `_read` сузила контракт до фактического: не-объект = такой же нечитаемый вход, что и
битые байты (лог + `{}`), фактический тип цитируется вербатим — тихий `{}` иначе неотличим от
«продюсеры ничего не наблюдали» (класс #29/#31/#35–#38). Та же дыра этажом ниже закрыта для
контейнера `adapters` обоих продюсеров: `_as_list` (оркестратор) / `_as_map`
(`adapter_status.json`); пустой/отсутствующий контейнер дефектом не считается и не логируется.

**Осознанное отличие от «просто починить mypy»:** мэппинг в `adapters` оркестратора теперь
отвергается ЯВНО. Раньше он итерировался по ключам (строки), которые `isinstance(a, dict)`
отбрасывал ⇒ доказательств всё равно не появлялось. Исход не изменился, появилась видимая
причина.

**Проверка (все acceptance criteria закрыты):**

| проверка | результат |
|---|---|
| mypy набором ключевых модулей `ci-lite.yml` | **Success, 0 ошибок** (было 1) |
| новые герметичные тесты | **27 passed**; на коде origin — **20 failed / 7 passed** |
| положительные контроли | **7** (здоровый вход не клампится; per-entry мусор не выбрасывает соседей; отсутствующий ключ `adapters`, битые байты и отсутствующий файл отказывают как прежде) |
| `--collect-only` `spa_core/tests/` | 91 705 → **91 732 = ровно +27** |
| смежный срез (10 файлов тестов аллокатора) | **107 passed** |
| полный срез CI `spa_core/tests/` | **91 158 passed / 3 failed** (15:12); контроль на чистом `origin/main` — **91 131 passed / 3 failed** (14:58) ⇒ те же три падения, дельта **ровно +27** |
| `lint_llm_forbidden` | 166 файлов / 0 нарушений |
| `pre_cutover_gate` (money-path) | вывод base vs fixed **побайтово идентичен** (различается только имя случайного sandbox-каталога) |
| живой смоук на КОПИИ прод-данных | карта доказательств **идентична до и после**: 15 протоколов, те же значения и источники ⇒ книга не сдвинется |
| существующие тесты | **ни один не изменён и не ослаблен** (инв. #16), правки строго аддитивные |

**Три падения полного среза — предсуществующие, ни одно не мой домен:**

- `test_e2e_integration::TestAdapterBehavior::test_spark_get_apy_pct_{positive,returns_float}` —
  известная карточка `agent-spark-apy-tests-assert-a-fallback-adr-063-removed` (занята, не брал);
- `test_no_live_network_in_tests::TestGuardIsInstalled::test_telegram_guard_stays_outermost` —
  тест требует `_live_net.attempts() == []`, то есть ПУСТОЙ глобальный журнал сетевых попыток;
  в полном прогоне к этому моменту накоплено **2267** записей от более ранних тестов (первая —
  `urlopen https://yields.llama.fi/pools`). Это зависимость от состояния соседей, а не от моей
  правки: она не добавляет ни одной сетевой попытки. Подтверждено контрольным полным прогоном
  на чистом `origin/main` — см. отметку в журнале `2026-W32`.

RiskPolicy, пороги, kill-switch, живой трек `data/equity_curve_daily.json`, launchd/деплой — не
трогал; `data/**` не публиковал. ADR не требуется: код приведён к действующим инвариантам
#2 (fail-CLOSED) и #16.

## Подтверждено РЕАЛЬНЫМ Actions, а не локалью

Доставлено одним атомарным коммитом `b413fc764` (8 файлов, `skipped=0`, все 8 сверены с origin
побайтово 8/8, стрэев в корне нет, чистый чекаут доставленного коммита — 27 passed + mypy
Success). После доставки `workflow_dispatch` на `main`:

```
run 30784470365  SPA CI-Lite  b413fc764  2026-08-03T04:27:05Z  ->  SUCCESS
```

**Все 11 шагов джоба `Syntax & Import Check` = success**, включая шаг 9 (`Type check — mypy`) и,
что важнее, шаги **10 `Import check — all spa_core modules import cleanly`** и
**11 `Registry check — >= 20 strategies registered`**, которые всё время красноты уходили в
`skipped`. Предыдущие два прогона на `49d0d1122` и `19666683a` — `failure`. Красный CI-Lite
закрыт.

**Статус карточки → `done`.**
