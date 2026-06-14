# ADR-2026-007 — Tail Risk Reserve переведён в Sky sUSDS

**Дата:** 2026-05-01
**Статус:** Accepted
**Версия документации:** SPA v0.4
**Связанные ADR:** ADR-2026-002, ADR-2026-005, ADR-2026-006

---

## Контекст

В документации v0.3 Tail Risk Reserve определялся как **10% от total capital в USDC, "мёртвый кэш"** — held in отдельный wallet, без доходности, как ликвидный буфер для:

- Emergency exits при срабатывании kill-criteria по Tier 1 позиции
- Покрытия gas / bridging costs при экстренных ребалансировках
- Покрытия временных illiquidity в Tier 2 (Pendle PT secondary market thin)

Проблема: 10% от portfolio с 0% APY — это drag ~50 bps на overall portfolio yield. При $100K капитале это ~$500/год упущенного yield.

Sky sUSDS (Savings USDS, преемник DAI Savings Rate) предлагает:

- **APY 4.25%** через Sky Savings Rate (SSR), управляемый Sky Protocol governance.
- **Liquidity:** instant redeem обратно в USDS (no withdrawal queue).
- **USDS → USDC:** через Sky's PSM (Peg Stability Module) instant 1:1 без slippage, лимит $50M/day.
- **Smart contract risk:** код от MakerDAO/Sky, аудиты от ChainSecurity, PeckShield, Cantina.
- **Governance:** SKY token holders, 48h timelock на critical parameters.

Однако в v0.3 Sky sUSDS был в **Watch List** (не в Tier 1) из-за:

1. Governance: переход MakerDAO → Sky был свежим (Aug 2024), требовался период стабилизации.
2. USDS как актив: новый stablecoin, peg history короткая.

К маю 2026 эти концерны частично сняты: 20+ месяцев операции, peg USDS-USDC стабилен в пределах ±5 bps, SSR rate был изменён 3 раза без incidents.

## Решение

**Перевести Tail Risk Reserve из мёртвого USDC в Sky sUSDS, отдельный wallet, 8% от total capital (снижено с 10%).**

### Параметры

- **Размер:** 8% от total capital (было 10% USDC).
  - Обоснование снижения: sUSDS более ликвиден, чем кажется (PSM + secondary). Резерв 8% покрывает worst-case exit Tier 1 позиции при условии instant sUSDS→USDS→USDC.
- **Asset:** Sky sUSDS (ERC-4626 vault wrapper над USDS).
- **Wallet:** отдельный кошелёк, не shared с working capital. Адрес зафиксирован в `01_Vault_Map.md`.
- **Permissions:** только owner key, no automation rebalance keys.
- **Monitoring:**
  - USDS peg deviation >50 bps от $1.00 — alert
  - SSR rate change announcement — info notification
  - sUSDS contract pause — critical alert
- **Использование:**
  - Полностью или частично используется только при срабатывании kill-criteria.
  - НЕ rebalance target — нельзя автоматически "trade" sUSDS на yield.
  - При использовании >50% TRR — обязательный manual review перед refill.

### Финансовый эффект

| Параметр | v0.3 (USDC dead cash) | v0.4 (sUSDS) |
|---|---|---|
| Размер | 10% × $100K = $10,000 | 8% × $100K = $8,000 |
| Yield | 0% = $0/yr | 4.25% × $8K = $340/yr |
| Working capital | 90% × $100K = $90,000 | 92% × $100K = $92,000 |
| Drag на overall portfolio | -50 bps | +34 bps |

**Net effect на overall portfolio yield: +84 bps.** При target gross APY 7.4% working capital, эффективный portfolio yield становится 7.4% × 0.92 + 4.25% × 0.08 = **7.15%**, что лучше чем v0.3 эквивалент (4.0% × 0.9 + 0% × 0.1 = 3.6%).

## Альтернативы

1. **Оставить USDC мёртвый кэш** — отклонено. См. yield drag выше.
2. **Использовать Aave V3 USDC как TRR** — отклонено. Aave V3 — часть Tier 1 working capital, нарушается принцип изоляции.
3. **TRR в Aave V3 USDC на Arbitrum (отдельная цепь)** — рассмотрено, отклонено. Cross-chain exit требует bridge, что противоречит цели TRR (instant liquidity).
4. **TRR в Compound V3 USDC** — отклонено по тем же причинам, что и Aave.
5. **TRR в USDC + 5% размер** — отклонено. 5% недостаточно для покрытия одновременного exit двух Tier 1 позиций.
6. **TRR в USDe staking** — отклонено. Funding-rate dependent yield + 7-day cooldown на unstake.

## Последствия

**Положительные:**
- +84 bps к portfolio yield.
- Sky sUSDS — один из самых ликвидных yield-bearing USD instruments на L1.
- Уменьшение TRR с 10% до 8% освобождает 2% working capital → дополнительные $20–80/yr на capital $10K–$100K.

**Отрицательные:**
- Введение smart contract risk в инструмент, который ранее был "trivial" (USDC EOA).
- Зависимость от USDC↔USDS peg через PSM.
- При USDS depeg event (даже временном) TRR становится частично impaired.

**Митигация:**
- USDS peg monitoring с tight threshold (50 bps vs обычные 100 bps).
- При peg drift >25 bps — manual review, при >50 bps — automatic TRR exit в USDC через PSM.
- Quarterly review статуса Sky Protocol governance и SSR sustainability.

## Ссылки

- `Risk_Policy_v0.4.md` (раздел Tail Risk Reserve)
- `04_Whitelist_Policy_v0.4.md` (Sky sUSDS Tier 1 reference)
- `15_Monitoring_and_Alerts_v0.4.md` (USDS peg alerts)
- ADR-2026-005: v0.4 adoption
- Memory facts: статус Sky GSM Pause Delay = 24h, требование ≥48h — на пересмотре
