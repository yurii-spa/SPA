# CHANGELOG v0.4 и v0.4.5

Изменения относительно `CHANGELOG_v0.3.md` (последний baseline).

---

## SPA v0.4 — 2026-05-01

**Главная тема:** переход с консервативного режима на агрессивный.

### Added

- **Tier 2 категория** в whitelist: Pendle PT-sUSDe, Pendle PT-syrupUSDC, Maple syrupUSDC, Euler V2 USDC.
- **Multi-chain поддержка:** Aave V3 на Arbitrum, Compound V3 на Base. Bridges: только canonical (Arbitrum Bridge, Base Bridge).
- **Event-driven rebalance:** threshold 7% от целевой аллокации.
- **Tier 2 Reporting section** в weekly template.
- **Pendle maturity tracking** — alerts при maturity ≤14 дней.
- **Morpho cap change monitoring** — особый внимание к decreasing caps (не timelocked).

### Changed

- **Target net APY:** 4% → **8%** (см. позже ADR-009 reconciliation).
- **Max drawdown:** 2% → **5%**.
- **Tier 1 / Tier 2 split:** 100/0 → **60/40**.
- **Rebalance cadence:** weekly → **bi-weekly + event-driven**.
- **Sky sUSDS:** Watch List → **Tier 1 с долей 10%** (см. ADR-007).
- **Tail Risk Reserve:** USDC dead cash 10% → **sUSDS 8%** (см. ADR-007).
- **Reporting:** weekly template расширен Tier 2 секцией + операционные costs.

### Removed

- Принцип "100% Tier 1" (заменён на 60/40).

### ADR ссылки

- ADR-2026-005: Adopt v0.4
- ADR-2026-006: Extended Whitelist v0.4
- ADR-2026-007: Tail Risk Reserve в sUSDS

---

## SPA v0.4.5 — 2026-05-03

**Главная тема:** добавление aggregator-уровня + финансовая сверка.

### Added

- **Yearn V3 yvUSDC** в Tier 1 (T1-05, 10% working capital).
- **Effective exposure tracking** в weekly report: учёт underlying composition yvUSDC.
- **Operational costs section** в weekly report: rolling 30-day в bps от capital.
- **Net APY таргеты по уровням капитала** ($10K → $250K).
- **Net APY формула** в `08_Accounting_and_PnL_v0.4.5.md`.
- **Aspirational target ≥9%** — explicitly помечен как upside, не baseline.

### Changed

- **Tier 1 / Tier 2 split:** 60/40 → **65/35**.
- **T1-01 Aave V3 USDC доля:** 25% → **20%**.
- **T2-01 Pendle PT-sUSDe доля:** 15% → **12%** (компенсация Yearn).
- **Net APY claim:** unconditional "≥8%" → **per-tier таблица** в зависимости от капитала.
- **Risk_Policy:** добавлено explicit minimum viable capital ($25K).

### Reconciliations (ADR-009)

- **Net APY $10K:** 4.0%
- **Net APY $25K:** 6.2%
- **Net APY $50K:** 6.9%
- **Net APY $100K:** 7.3%
- **Net APY $250K:** 7.5%
- **Gross APY working capital:** 7.4% (consistent).

### ADR ссылки

- ADR-2026-008: Yearn V3 yvUSDC
- ADR-2026-009: Financial Targets Reconciliation

---

## Pending / future versions

### Под мониторингом для следующих версий

- **Sky GSM Pause Delay** — текущий 24h. При on-chain подтверждении 48h timelock → пересмотр Sky T1 share с 10% до 30%, и понижение других T1 позиций.
- **Yearn V3 strategy roster** — quarterly review.
- **Pendle ecosystem на Base/Arbitrum** — мониторинг TVL roll, ожидание $300M threshold.
- **Spark sUSDS** — после миграции Sky.
- **Paper trading Week 4 → Week 6 small-live** — переход на $5K real capital перед full deploy.
