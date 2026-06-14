# Paper Trading Week 0 Baseline (2026-05-02)

Project: Smart Passive Aggregator (SPA)
Version: v0.4.5
Дата фиксации: 2026-05-02
Owner: Юра
Связанный ADR: ADR-2026-004 (запуск paper trading)

---

## Назначение

Без baseline первый weekly report не с чем сравнивать — невозможно отделить движение от рынка от ошибок стратегии.

Этот документ создаётся **один раз** на старте и больше не редактируется. Все сравнения в weekly reports делаются относительно этих цифр.

---

## Стартовое размещение виртуального капитала

Согласно ADR-2026-004 и Whitelist Policy v0.4.5 раздел 9.

**Total virtual capital:** 10 000 USDT
**Working capital (T1+T2):** 9 200 USDT (92%)
**Tail Risk Reserve:** 800 USDT (8%)

### Tier 1 (60% от working capital = 5 520 USDT)

| Протокол | Целевая доля working | Виртуальный USDT | APY на 2026-05-02 (gross) | Источник |
|----------|----------------------|------------------|---------------------------|----------|
| Aave V3 USDC (Ethereum) | 20% | 1 840 | 5.20% | DeFiLlama 2026-05-02 |
| Morpho Blue Steakhouse Prime USDC | 12% | 1 104 | 6.80% | Morpho UI 2026-05-02 |
| Compound V3 USDC (Ethereum) | 8% | 736 | 4.50% | DeFiLlama 2026-05-02 |
| Sky sUSDS (Sky Savings Rate) | 10% | 920 | 4.25% | sky.money 2026-05-02 |
| Yearn V3 yvUSDC | 10% | 920 | 7.00% net of 15% fee | yearn.fi 2026-05-02 |

### Tier 2 (40% от working capital = 3 680 USDT)

| Протокол | Целевая доля | Виртуальный USDT | APY (gross) | Источник |
|----------|--------------|------------------|-------------|----------|
| Pendle PT-sUSDe (≤90д до maturity) | 15% | 1 380 | 13.50% | pendle.finance |
| Pendle PT-syrupUSDC (≤90д) | 10% | 920 | 10.50% | pendle.finance |
| Maple Finance syrupUSDC | 8% | 736 | 8.80% | maple.finance |
| Euler V2 USDC | 7% | 644 | 7.50% | euler.finance |

### Tail Risk Reserve (8% от total = 800 USDT)

| Размещение | Виртуальный USDT | APY (gross) |
|-----------|------------------|-------------|
| Sky sUSDS (отдельный кошелёк) | 800 | 4.25% |

---

## Weighted gross APY baseline

```
Tier 1 contribution:
  Aave 0.184 × 5.20%      = 0.957%
  Morpho 0.110 × 6.80%    = 0.748%
  Compound 0.074 × 4.50%  = 0.333%
  Sky T1 0.092 × 4.25%    = 0.391%
  Yearn 0.092 × 7.00%     = 0.644%
  Subtotal:                 3.073%

Tier 2 contribution:
  Pendle PT-sUSDe 0.138 × 13.50%     = 1.863%
  Pendle PT-syrupUSDC 0.092 × 10.50% = 0.966%
  Maple 0.074 × 8.80%                = 0.651%
  Euler 0.064 × 7.50%                = 0.480%
  Subtotal:                            3.960%

Reserve contribution:
  sUSDS 0.080 × 4.25%     = 0.340%

Total weighted gross APY baseline: 7.37%
```

(Доли от полного портфеля. Working capital × 0.92 = доля от total.)

---

## Net APY baseline (после газа)

При $10K virtual + 12 ребалансировок/год + $25/op газ + final exit:
- Total annual gas: ~$350
- **Net APY baseline: 4.0%** (см. ADR-009 net targets)

Это baseline целевой показатель для сравнения в weekly reports.

---

## Рыночные условия на 2026-05-02

(Заполняется Owner вручную на день старта.)

| Метрика | Значение | Источник |
|---------|----------|----------|
| ETH price | TBD | CoinGecko |
| Gas price (median) | TBD gwei | Etherscan gas tracker |
| Total DeFi TVL | TBD | DeFiLlama |
| USDC peg | TBD | Chainlink/Pyth |
| USDT peg | TBD | Chainlink/Pyth |
| USDS peg | TBD | sky.money |

---

## Что измеряется в Week 1+ relative to baseline

Каждый weekly report сравнивается с этим baseline по:

1. **Реализованный yield vs прогноз** (за неделю и cumulative)
2. **Изменения APY каждого протокола** (drift от baseline)
3. **Drawdown** (если был — относительно стартового capital $10K)
4. **Отклонение долей от целевых** (если ребаланс случился)
5. **Количество выполненных операций vs план** (12 ребалансировок/год = ~1/месяц)

---

## Условия пересмотра baseline

Baseline пересматривается **только** при:
- изменении состава whitelist через ADR (например, новый протокол активирован);
- существенном изменении target долей (> 5pp по одному протоколу);
- окончании paper trading периода (Week 8) — тогда создаётся новый baseline для live.

В обычной работе baseline **не меняется** в течение всего paper trading периода (8 недель).

---

## Подпись Owner

Дата фиксации: 2026-05-02
Owner: Юра
Связанный ADR: ADR-2026-004
