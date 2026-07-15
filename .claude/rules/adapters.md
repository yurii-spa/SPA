# Rule · Adapters (`spa_core/adapters/`)

**Читать перед работой с адаптерами протоколов / фидами.**

- **Read-only домен.** Адаптеры НИКОГДА не пишут в `data/adapter_status.json` (это
  execution-домен). Не импортировать `spa_core/execution/` отсюда.
- **Реестр** — `ADAPTER_REGISTRY` в `spa_core/adapters/__init__.py`. Проверка количества:
  `python3 -c "from spa_core.adapters import ADAPTER_REGISTRY; print(len(ADAPTER_REGISTRY))"`.
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
