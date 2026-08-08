---
trackerStatus:
  type: inbox
title: Оживить фиды вне Ethereum — путь к снятию остатка кэша (решение владельца 08.08)
status: new
source: nimbalyst
created: 2026-08-08
priority: high
---

Цель: живые TVL+APY для не-Ethereum протоколов, чтобы chain-лимит 90% перестал быть потолком размещения. Сейчас отсеяны: 5 пулов на СТАТИЧЕСКОМ TVL (aave_arbitrum, aave_v3_base, aave_v3_optimism, aave_v3_polygon, spark_susds — ADR-053 не даёт свежий капитал), morpho_blue_base + silo_arbitrum с аномальным APY 0.00% (пулы по UUID отдают ноль — проверить pinned UUID по ADR-064), moonwell_base под TVL-floor $5M, aerodrome_base по глубине ($1M пул, лимит 1% TVL). Порядок: (1) починить APY 0.00% у morpho_blue_base/silo_arbitrum (вероятно неверный UUID пула или чтение поля); (2) добиться live TVL для aave-семейства L2 (pinned UUID DeFiLlama, ADR-064); (3) замерить, сколько кэша размещается после каждого шага. Money-path: тесты обе стороны, sandbox-прогон, pre_cutover_gate.
