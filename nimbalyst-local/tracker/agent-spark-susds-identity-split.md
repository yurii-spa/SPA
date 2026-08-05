---
trackerStatus:
  type: agent
title: spark_susds наблюдает чужой инструмент (sparklend lending vs sUSDS vault) — развести идентичности до допуска Sky
status: backlog
source: feeds-second-pass-2026-08-05
created: 2026-08-05
priority: medium
domain: adapters; ВАЖНО до снятия инварианта 10 (допуск Sky)
---

Находка второго прохода фидов: адаптер spark_susds моделирует sUSDS savings-vault (0xa3931d…fbD,
~3.52%), но hint (spark, USDS, Ethereum) резолвится в sparklend USDS LENDING-рынок ($543M @
3.22%) — другой продукт. Настоящий sUSDS-пул d8c4eff5 уже запинен под ключом sky_susds ⇒
spark_susds/sky_susds — вероятный дубликат инструмента (класс frax/sfrax). Сейчас не опасно:
tvl_source=static ⇒ ADR-053 не пускает капитал; допуск Sky owner-gated (инвариант 10). НО при
открытии Sky ранжирование пойдёт по числу НЕ ТОГО рынка. Задача: развести идентичности (либо
spark_susds = sparklend-рынок как отдельный протокол со своим тиром, либо честно удалить
дубликат через карточку), тесты «два ключа ≠ один пул» уже есть — расширить на этот случай.

## Как понять, что готово
Каждый ключ реестра наблюдает ровно свой инструмент; тест закрепляет пары ключ↔пул.
