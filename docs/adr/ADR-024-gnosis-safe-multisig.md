# ADR-024: Gnosis Safe Multisig для go-live

**Статус:** Accepted  
**Дата:** 2026-06-12  
**Автор:** SPA System

## Контекст

SPA управляет $100K USDC. Единоличный EOA кошелёк = bus factor 1, нет аудит трейла, невозможно для Family Fund (Договір простого товариства).

## Решение

Использовать Gnosis Safe 2/3 multisig на Ethereum mainnet.

## Конфигурация

- **Threshold:** 2-of-3
- **Signers:** Owner (primary), Owner (backup device), Co-investor (silent)  
- **Сеть:** Ethereum mainnet (основная), Arbitrum One (L2 операции)
- **Upgrade time-lock:** 24 часов для изменения threshold

## Типы транзакций

| Тип | Подписей нужно | Описание |
|-----|----------------|----------|
| Rebalance < 5% капитала | 1 (owner EOA в paper phase) | Частые операции |
| Rebalance >= 5% | 2/3 | Крупные движения |  
| Withdraw | 2/3 | Любой вывод |
| Upgrade контракта | 2/3 + 24h timelock | Изменение логики |

## Модули Safe

- **Zodiac Roles** — разграничение прав SPA automation vs Owner
- **Guards** — spending limit 10% в день без multisig

## Этапы внедрения

1. Deploy Safe (2026-07-01) — до go-live
2. Transfer paper equity tracker address → Safe (2026-07-12)
3. First live tx через Safe (2026-08-01)

## Последствия

**Позитивные:** аудит трейл, bus factor 3, Family Fund compliance, investor trust  
**Негативные:** latency (2-3 мин на каждый tx vs 30 сек), setup complexity

## Альтернативы рассмотрены

- EOA + hardware wallet: отклонено (нет аудит трейла для Family Fund)
- 3-of-5: отклонено (слишком медленно для rebalancing)
