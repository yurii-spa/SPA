# ADR-2026-008 — Добавление Yearn V3 yvUSDC в Tier 1 (v0.4.5)

**Дата:** 2026-05-03
**Статус:** Accepted
**Версия документации:** SPA v0.4.5
**Связанные ADR:** ADR-2026-005, ADR-2026-006, ADR-2026-009

---

## Контекст

После двух недель paper trading на v0.4 whitelist обнаружились две тенденции:

1. **Tier 1 yield underperformance** относительно ожиданий. Aave V3 и Compound V3 USDC supply rates на L1 в апреле–мае 2026 колеблются в диапазоне 3.8–5.2%, тогда как baseline закладывал 4.5–5.5%. Сжатие происходит из-за роста supply без proportional borrow demand.

2. **Yearn V3 yvUSDC** стабилизировался на 6.8–7.3% net APY (после 15% performance fee). Yearn V3 — это новая архитектура (Vault V3 + Strategies as independent contracts), где yvUSDC автоматически распределяет ликвидность между Aave V3, Compound V3, Morpho и Sky sUSDS на основе текущих rates. Эффективно это **active aggregator** на тех же базовых протоколах, что уже в whitelist.

Параметры Yearn V3 yvUSDC к маю 2026:

- **TVL:** $480M (на Ethereum L1)
- **Аудиты:** Trail of Bits (V3 core, март 2024), ChainSecurity (V3 strategies, июнь 2024), yAcademy (continuous).
- **История:** Yearn V1 с 2020, V2 с 2021, V3 с 2024 без exploit в production V3 vaults.
- **Стратегии в yvUSDC:** Aave V3 Lender, Compound V3 Lender, Morpho Steakhouse Lender, Sky sUSDS Lender (все из whitelist v0.4!).
- **Performance fee:** 15% on yield (включён в публикуемый APY на yearn.fi).
- **Management fee:** 0% (snowed since V3 launch).
- **Withdrawal:** instant, no lockup.
- **Governance:** yearnDAO, multisig 6-of-9 на critical ops, timelock 48h на strategy additions.

Ключевой нюанс: yvUSDC увеличивает yield через **active rebalancing** между протоколами, которые уже в нашем whitelist. То есть это **layer-2 aggregator**, не новый базовый риск. Smart contract risk Yearn добавляется поверх существующих risks.

## Решение

**Добавить Yearn V3 yvUSDC в Tier 1 с долей 10% working capital (T1-05), pushing v0.4 → v0.4.5.**

### Обновлённая Tier 1 структура

| Код | Протокол | Доля v0.4 | Доля v0.4.5 | Δ |
|---|---|---|---|---|
| T1-01 | Aave V3 USDC | 25% | 20% | −5% |
| T1-02 | Morpho Blue Steakhouse | 15% | 15% | 0 |
| T1-03 | Compound V3 USDC | 10% | 10% | 0 |
| T1-04 | Sky sUSDS | 10% | 10% | 0 |
| T1-05 | **Yearn V3 yvUSDC** | — | **10%** | **+10%** |
| **Tier 1 total** | **60%** | **65%** | **+5%** |

Tier 2 соответственно: 40% → 35% (Pendle PT-sUSDe 15% → 12%, остальное без изменений).

### Параметры мониторинга

- **TVL alert:** yvUSDC TVL drop >30% за 24h.
- **Strategy concentration alert:** одна underlying strategy >50% от yvUSDC AUM.
- **Performance deviation:** yvUSDC published APY vs предсказание (weighted avg underlying strategies) разница >2 percentage points → review.
- **Governance:** monitor yearnDAO proposals to add new strategies; новые strategies НЕ из нашего whitelist → exit position.

### Performance fee transparency

15% performance fee Yearn включён в публикуемый APY на yearn.fi. То есть если интерфейс показывает 7.0% APY, gross yield от underlying ~8.2%, Yearn забирает ~1.2% как fee.

В нашем accounting (`07_Accounting_and_PnL_v0.x.md`):

- **Gross yield** = published APY × allocation × time
- **Yearn fee** = 0 (уже учтено в published APY)
- **Net yield** = published APY × allocation × time

То есть для целей portfolio APY используется published net APY ~7%.

## Альтернативы

1. **Не добавлять Yearn, ожидать восстановления native Aave/Compound rates** — отклонено. Сжатие rates — структурное (рост supply USDC), не циклическое.
2. **Добавить Yearn V3 в Tier 2 с долей 15%** — отклонено. Underlying strategies — все Tier 1 уровня; классификация Tier 2 не соответствует профилю риска.
3. **Использовать Yearn V3 yvUSDC как 100% Tier 1 (заменить native позиции)** — отклонено. Концентрация в одном смарт-контракте (Yearn V3 vault) превышает risk limits.
4. **Добавить Morpho meta-vault или Spectra aggregator** — рассмотрено, отклонено. Morpho meta-vaults слишком новые (<6 мес.). Spectra — не пройдена due diligence на момент решения.

## Последствия

**Положительные:**
- Tier 1 weighted APY: ~5.5% → ~6.0% (+50 bps).
- Active rebalancing между underlying protocols без manual вмешательства.
- Полный whitelist v0.4.5 weighted gross APY ~7.4% (см. ADR-009).

**Отрицательные:**
- Добавлен smart contract layer (Yearn V3 vault + strategy contracts) поверх underlying protocols.
- "Hidden" концентрация: если yvUSDC = 50% Aave underlying, реальная экспозиция на Aave: 20% (T1-01 direct) + 5% (через yvUSDC) = 25%.
- 15% performance fee — это явный yield drag (~1.2 percentage points).
- При Yearn V3 strategy migration, мы наследуем decisions yearnDAO governance.

**Митигация:**
- Effective exposure tracking: weekly report включает таблицу "true underlying concentration" с учётом yvUSDC composition.
- При concentration по одному underlying protocol >35% (всех источников вместе) — temporary exit yvUSDC.
- Quarterly review Yearn V3 strategy roster.

## Ссылки

- `04_Whitelist_Policy_v0.4.5.md`
- `15_Monitoring_and_Alerts_v0.4.5.md` (новые алерты Yearn)
- ADR-2026-005, ADR-2026-006 (v0.4 baseline)
- ADR-2026-009: финансовая сверка с учётом v0.4.5
- yearn.fi vault page: yvUSDC на Ethereum
- Audit reports: TrailOfBits Yearn V3 (March 2024), ChainSecurity Yearn V3 strategies (June 2024)
