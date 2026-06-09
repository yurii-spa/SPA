# ADR-2026-006 — Расширенный whitelist v0.4 (60/40 Tier1/Tier2, multi-chain)

**Дата:** 2026-05-01
**Статус:** Accepted
**Версия документации:** SPA v0.4
**Связанные ADR:** ADR-2026-002 (v0.3 whitelist), ADR-2026-005 (v0.4 adoption)

---

## Контекст

В рамках перехода на v0.4 (агрессивный режим, ADR-005) исходный whitelist v0.3 (Aave V3 + Compound V3 + Sky sUSDS as watch list) требует расширения для достижения таргета net APY ≥8%. При этом расширение должно сохранять принципы risk management v0.3.

Критерии для добавления протокола в whitelist v0.4:

- **TVL:** ≥$300M на конкретном instance (chain + asset)
- **Аудит:** минимум 2 независимых аудита (Trail of Bits, ChainSecurity, Spearbit, OpenZeppelin, Cantina)
- **История:** ≥12 месяцев operation без exploit
- **Oracle independence:** минимум 2 источника цены
- **Governance:** timelock ≥48h на критические параметры (исключения см. ниже)

## Решение

**Принять расширенный whitelist v0.4 со структурой 60% Tier 1 / 40% Tier 2 working capital + 8% Tail Risk Reserve (sUSDS, отдельный кошелёк).**

### Tier 1 (60% working capital) — Core Lending

| Код | Протокол | Chain | Доля | Target APY | Обоснование |
|---|---|---|---|---|---|
| T1-01 | Aave V3 USDC | Ethereum + Arbitrum | 25% | 4.5–5.5% | Эталон рынка. Multi-chain expansion для diversification. |
| T1-02 | Morpho Blue (Steakhouse Prime USDC) | Ethereum | 15% | 6–7% | Curated vault от Steakhouse Financial с конкретной кредитной политикой. См. caveat ниже. |
| T1-03 | Compound V3 USDC | Ethereum + Base | 10% | 4–5% | Base — для дешёвых ребалансировок. |
| T1-04 | Sky sUSDS | Ethereum | 10% | 4.25% | Повышен из Watch List (ADR-007). |

**Caveat по Morpho Blue:** immutable core означает, что параметры markets фиксированы при создании, но MetaMorpho vaults управляются curators. Decreasing caps на vault — НЕ timelocked (в отличие от increasing caps). Это допустимый риск для Steakhouse/Gauntlet/Block Analitica vaults, но НЕ для permissionless curators. В whitelist v0.4 — только три указанных curator.

### Tier 2 (40% working capital) — Yield Enhancement

| Код | Протокол | Chain | Доля | Target APY | Обоснование |
|---|---|---|---|---|---|
| T2-01 | Pendle PT-sUSDe | Ethereum | 15% | 9–11% | Fixed-rate yield, maturity ≤90 дней. Ethena underlying. |
| T2-02 | Pendle PT-syrupUSDC | Ethereum | 10% | 8–10% | Fixed-rate, Maple underlying. |
| T2-03 | Maple syrupUSDC (direct) | Ethereum | 8% | 8–9% | Overcollateralized institutional lending. |
| T2-04 | Euler V2 USDC | Ethereum | 7% | 5–7% | Возврат после 2023 hack, два цикла аудитов, ReentrancyGuard rework. |

### Tail Risk Reserve (8% от total capital)

См. **ADR-2026-007**: Sky sUSDS в отдельном кошельке, не часть working capital, не учитывается в target APY working portfolio.

### Что НЕ вошло в v0.4 whitelist

- **Ethena USDe staking прямо** — синтетический stablecoin, funding-rate dependent yield. Только через Pendle PT-sUSDe (с фиксацией yield на maturity).
- **Lido stETH / Aave против stETH** — за рамками stablecoin scope.
- **Curve / Convex stablecoin LP** — IL риск (хоть и малый) + governance complexity.
- **Stargate, Across, third-party bridges** — только canonical bridges.
- **Любой protocol на L2 ≤6 месяцев деплоя** (Linea, Scroll, Mantle на L2 USDC — не достаточно истории).

### Watch List v0.4 (мониторинг без аллокации)

- Pendle PT на Base (TVL растёт, пока <$300M на отдельный PT)
- Yearn V3 yvUSDC (добавлен в v0.4.5 → ADR-008)
- Spark sUSDS (после миграции Sky)
- fxUSD от Aladdin (новый, требует ≥6 мес. истории)

## Альтернативы

1. **Tier 1 70% / Tier 2 30%** — отклонено. При target APY 8% слишком много давления на Tier 2 концентрацию.
2. **Добавить Curve 3CRV LP в Tier 2** — отклонено. Governance complexity + risk modelling сложнее, чем lending.
3. **Permissionless Morpho markets** — отклонено. Curator risk слишком высок для Tier 1.

## Последствия

**Положительные:**
- Weighted average target APY (working capital): ~7.4% gross.
- Диверсификация по типам yield (lending floating, fixed-rate, RWA-backed).
- Multi-chain снижает Ethereum gas concentration risk.

**Отрицательные:**
- 7 протоколов vs 3 в v0.3 → 2.3× больше операционной нагрузки.
- Pendle PT требует roll/exit logic ближе к maturity.
- Morpho curator risk требует отдельного мониторинга vault metadata.

## Ссылки

- `04_Whitelist_Policy_v0.4.md`
- ADR-2026-002: исходный Tier 1 whitelist v0.3
- ADR-2026-007: Tail Risk Reserve в sUSDS
- ADR-2026-008: добавление Yearn V3 в v0.4.5
- `15_Monitoring_and_Alerts_v0.4.md` (новые алерты для Pendle maturity, Morpho cap changes)
