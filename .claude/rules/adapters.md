# Rule · Adapters (`spa_core/adapters/`)

**Читать перед работой с адаптерами протоколов / фидами.**

- **Read-only домен.** Адаптеры НИКОГДА не пишут в `data/adapter_status.json` (это
  execution-домен). Не импортировать `spa_core/execution/` отсюда.
- **Реестр** — `ADAPTER_REGISTRY` в `spa_core/adapters/__init__.py`. Проверка количества:
  `python3 -c "from spa_core.adapters import ADAPTER_REGISTRY; print(len(ADAPTER_REGISTRY))"`.
- **Одно имя — один объект (цикл #274).** Рядом живут ещё два набора, и у каждого теперь
  СВОЁ имя; раньше все три звались `ADAPTER_REGISTRY`, и потребитель получал тот, чьё имя
  короче набрать (на этом три месяца врал `house_view_gap`, #206):

  | Имя | Где | Форма · размер | Как зовут крупнейшую позицию книги |
  |---|---|---|---|
  | `ADAPTER_REGISTRY` | `spa_core/adapters/__init__.py` | список кортежей · 36 | `aave_v3` |
  | `ADAPTER_METADATA` | `spa_core/adapters/registry.py` | dict метаданных · 22 | `aave_usdc` (`aave_v3` там НЕТ) |
  | `POLLED_ADAPTERS` | `spa_core/orchestrator/adapter_orchestrator.py` | список кортежей · 8 | что цикл реально опрашивает |

  Составы РАЗНЫЕ и совпадать не обязаны — но сверять «книга ↔ реестр» по `ADAPTER_METADATA`
  нельзя: она честно доложит, что 40 % книги не зарегистрировано. Держит храповик
  `spa_core/tests/test_adapter_registry_single_name.py` (новое определение имени = красный).
- **Никаких fake-fallback'ов.** Если фид недоступен / данные не пришли — адаптер возвращает
  `None` (by design), система fail-close'ится, а не подставляет выдуманное значение.
- **APY-единицы непоследовательны:** новые адаптеры возвращают percent, старые
  (aave/yearn/euler/maple) — decimal. Нормализовать перед смешиванием.
- **DeFiLlama feed** (`defillama_feed.py`, TTL 300с): pinned `Accept-Encoding: gzip` → ответ
  надо декомпрессировать (иначе все `apy=None`). Pendle `tvl:null` → брать `liquidity.usd`.
  Chain-лейблы: Optimism = «OP Mainnet».
- **Sky/sUSDS = 0%** до подтверждённого GSM Pause Delay ≥ 48h on-chain (инвариант).
- **Только stdlib** в рантайме. Атомарные записи через `atomic_save`.
- Новые адаптеры T2/T3 — `IS_ADVISORY=True` / `RESEARCH_ONLY=True` до go-live.
- Тесты инжектят `FakeFeed` (DeFiLlama gzip падает офлайн) — не завязывать тесты на живую сеть.
