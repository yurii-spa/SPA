---
trackerStatus:
  type: inbox
title: "ADR-070.17-18: frax удалить, notional_v3 вывести"
status: in-progress
source: nimbalyst
created: 2026-08-07
adr: ADR-070
---

Дубль frax (закреплён за sfrax) удалить из реестра; notional_v3 не ERC-4626 — вывести до отдельного разбора (решение владельца 2026-08-07, ADR-070 п.17)

---

## Исполнено 2026-08-18 (кодовый слой)

Позиций под обоими ключами НЕТ (живая книга `data/current_positions.json` от 02.08: pendle, susde,
extra_finance_base, morpho_steakhouse, spark_susds) — снятие ключей никого не продаёт.

- **`frax` удалён** из канонического `ADAPTER_REGISTRY` (`spa_core/adapters/__init__.py`): импорт,
  кортеж и экспорт `FraxAdapter`. Реестр 36 → 35. Убран литерал `"frax": 100_000_000.0` из
  `_TVL_ESTIMATES` — $100M выше порога $5M, константа проходила floor тавтологически (ADR-053).
- **`notional_v3` выведен** (не удалён): запись остаётся в `ADAPTER_METADATA` с
  `withdrawn/withdrawn_adr/withdrawn_reason`, `get_adapter()` отказывает `WithdrawnAdapterError`,
  добавлены `is_withdrawn` / `list_withdrawn` / `list_eligible`, `withdrawn_count` в summary.
- Тест, пинивший `frax`, ПЕРЕВЁРНУТ открыто (инвариант 16), обоснование в теле файла + журнал
  `docs/journal/2026-W34.md`.
- Положительный контроль: `spa_core/tests/test_adr070_frax_notional.py` — краснеет и на возврат
  ключа, и на задетого соседа; обе мутации проверены на себе.

## Осталось (не в мандате этой сессии)

`data/adapter_registry.json` — фактический набор фида (34 записи) — до сих пор держит `frax`
(`status: active`, `research_only: false`) и `notional_v3`. Правка `data/` была запрещена заданием;
это отдельный шаг владельца, без него решение на уровне фида не действует.
