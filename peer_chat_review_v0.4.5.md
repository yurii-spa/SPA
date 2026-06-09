# Peer Chat Review — SPA v0.4.5

Рецензия из соседнего чата Claude (другой sub-agent), проведённая в начале мая 2026 на документацию v0.4 + предложенные изменения v0.4.5.

---

## Резюме

Рецензент идентифицировал **4 ключевые проблемы** в документации v0.4 / proposed v0.4.5. Все они были обработаны через ADR-2026-009 (Financial Targets Reconciliation).

---

## Problem 1: Заявленный 8% vs фактически достижимый

**Issue.** Документация v0.4 в разделе Risk Policy декларирует `target_net_APY: ≥8%`. Однако weighted average по предложенному whitelist v0.4.5:

```
T1 (60%): Aave 4.8% × 0.25 + Morpho 6.5% × 0.15 + Compound 4.5% × 0.10 + Sky 4.25% × 0.10 = 3.27%
T2 (40%): Pendle-sUSDe 10% × 0.15 + Pendle-syrupUSDC 9% × 0.10 + Maple 8.5% × 0.08 + Euler 6% × 0.07 = 3.50%
Gross weighted: ~6.8% (v0.4 без Yearn)
```

С добавлением Yearn V3 yvUSDC и rebalancing долей: **gross ~7.4%**. Это **не 8%**, и это **gross**, не net.

**Resolution.** ADR-009 явно discloses: 7.4% gross is baseline target, 8% net не достижим на малых капиталах.

---

## Problem 2: Operational costs игнорированы в Risk Policy

**Issue.** Risk Policy v0.4 не упоминает provider subscriptions ($110–125/мес), gas costs, bridge fees. На малом капитале это съедает значительную часть yield.

При капитале $10K:
- Op cost $2,500/yr = **25% capital base**
- Net APY работает в минус против gross yield

**Resolution.** ADR-009 включает explicit op cost breakdown:

- Провайдеры: $1,320–1,500/yr
- Gas: $880–2,330/yr
- Pendle roll: $160–320/yr
- Bridge: $60–360/yr
- **Total: $2,500–4,500/yr**

И Net APY таблица по уровням капитала.

---

## Problem 3: Yearn V3 performance fee transparency

**Issue.** Yearn V3 берёт 15% performance fee на yield. В quote APY на yearn.fi это уже включено. Но в документации v0.4.5 (proposed) не указано явно — пользователь может предположить, что 7% APY это gross.

Также: эффективная "double exposure" — если yvUSDC = 50% Aave underlying, а у нас есть 20% Aave direct + 10% yvUSDC, реальная Aave exposure = 25%.

**Resolution.** ADR-008 явно decline что:
- 15% perf fee включён в published 7% APY.
- В accounting yvUSDC quoted APY используется напрямую (no double-counting fee).
- Weekly report включает "effective underlying concentration" table.

---

## Problem 4: Tail Risk Reserve consistency между версиями

**Issue.** v0.3 определяет TRR = 10% внутри 100% portfolio. v0.4 определяет TRR = 8% **отдельно** от working capital (т.е. working capital = 92% от total). Это меняет формулу расчёта portfolio APY:

- v0.3 portfolio APY = (working APY × 0.9) + (0% × 0.1) = working APY × 0.9
- v0.4 portfolio APY = (working APY × 0.92) + (4.25% × 0.08) = working APY × 0.92 + 0.34%

Документация v0.4 нигде не указала, что "working APY targets" теперь относятся только к 92% от total, не к 100%.

**Resolution.** ADR-009 устанавливает единую формулу:
```
Portfolio gross effective APY = Working APY × 0.92 + 4.25% × 0.08
Portfolio net APY = Portfolio gross effective − (Op cost / Capital)
```

И в `08_Accounting_and_PnL_v0.4.5.md` это явно прописано.

---

## Дополнительные observations рецензента

### Концентрация в Morpho ecosystem

Через v0.4.5 ecosystem Morpho touch points:
- T1-02: Morpho Steakhouse Prime USDC direct (15%)
- T1-05: Yearn V3 yvUSDC (часть стратегий через Morpho)
- T2-02: Pendle PT-syrupUSDC ← Maple syrupUSDC ← возможно Morpho exposure через DAO collateral

Рекомендация: добавить **monitoring effective Morpho concentration** в weekly report (>30% combined → review).

**Status:** Принято в принципе, реализация в `15_Monitoring_and_Alerts_v0.4.5.md`.

### Oracle concentration

Большинство whitelist протоколов используют Chainlink price feeds (Aave, Compound, Morpho). Oracle concentration risk не достаточно покрыт.

**Status:** Принято к сведению, не блокирует v0.4.5. Рекомендация для будущего: при Chainlink event (governance compromise, oracle freeze) — manual review всех T1 позиций.

### Stream xUSD November 2025

Рецензент напомнил про contagion event Stream xUSD на Morpho curator vaults в ноябре 2025. Это не блокировало Steakhouse/Gauntlet/Block Analitica (они xUSD не держали), но подсветило risk permissionless curator vaults.

**Status:** Whitelist v0.4.5 явно ограничивает Morpho exposure тремя curator (Steakhouse, Gauntlet, Block Analitica). Permissionless markets — НЕ в whitelist.

---

## Outcome

ADR-2026-009 принят и закрыл все 4 ключевые проблемы. Рецензент считает v0.4.5 (с ADR-009) operationally consistent.

**Открытые items для следующего ревью:**

- Sky GSM Pause Delay подтверждение (см. Memory Facts).
- Quarterly Yearn V3 strategy roster review.
- Morpho concentration monitoring imple­mentation.
- Oracle concentration mitigation strategy.
