# ADR-2026-002: Принятие действующего whitelist (Tier 1 + Tier 2)

Дата: 2026-05-02
Статус: Accepted
Owner: Юра
Связанные документы: Whitelist Policy v0.3 (раздел 9), Strategy Passport Stable Lending Core v0.3

---

## Контекст

Whitelist Policy v0.3 требует ADR для включения любого протокола. Whitelist был пуст — единственный блокер paper trading. Проведён multi-model due diligence (три модели независимо, результаты синтезированы):

- Регуляторная проверка (OFAC SDN, EU, UN) — все протоколы чисты
- Оценка TVL, возраста, аудитов, oracle, timelock
- Анализ incident history 2025–2026
- Оценка совместимости с drawdown ≤ 2% (ключевой Owner-параметр)

Структура портфеля: **70% Tier 1 / 30% Tier 2**.
Tail Risk Reserve 10% — отдельно, вне этих долей.

---

## Решение

### Tier 1 (70% рабочего портфеля)

| # | Протокол | Целевой вес | Хард-кап | Решение |
|---|---------|-------------|----------|---------|
| T1-01 | Aave V3 — USDC (Ethereum) | 43% T1 | 50% T1 | ✅ Active |
| T1-02 | Morpho Blue — Steakhouse Prime USDC | 29% T1 | 37% T1 | ✅ Active |
| T1-03 | Morpho Blue — Gauntlet USDC Core | в рамках T1-02 | — | ✅ Active |
| T1-04 | Compound V3 — USDC (Ethereum) | 28% T1 | 35% T1 | ✅ Active |
| T1-W1 | Sky/Spark — sUSDS | 0% | — | ⏸ Watch List |

**Sky/Spark — Watch List:** GSM Pause Delay = 24ч (требование ≥ 48ч не выполнено). Предложение об увеличении до 48ч вынесено на голосование 27 апреля 2026, on-chain исполнение не подтверждено. Активация при: on-chain GSM ≥ 48ч + 1 governance-цикл.

### Tier 2 (30% рабочего портфеля)

| # | Протокол | Макс. вес в T2 | Решение |
|---|---------|----------------|---------|
| T2-01 | Pendle PT-syrupUSDC (≤90д, hold-to-maturity) | 30% | ✅ Active |
| T2-02 | Pendle PT-sUSDe (≤90д, hold-to-maturity) | 30% совокупно с T2-01 | ✅ Active |
| T2-03 | Maple Finance — syrupUSDC | 25% | ✅ Active |
| T2-04 | Euler V2 — USDC (DAO-managed, Chainlink) | 15% | ⚠️ Conditional |
| T2-R | Резервный буфер (USDC / sUSDS) | мин. 20% T2 | ✅ Active |

**Euler V2 Conditional:** не увеличивать выше 15% T2 до 2 кварталов чистой работы после KelpDAO-инцидента.

---

## Ключевые исключения (зафиксированы)

- Все рынки с LRT-коллатералом (rsETH, weETH) — KelpDAO exploit апр 2026
- Resolv USR — exploit март 2026
- Ethena USDe (прямое держание) — несовместимо с drawdown ≤ 2%
- L2-deployments в Tier 1 — sequencer + bridge risk
- SparkLend lending markets — GSM Pause Delay 24ч < 48ч

Полный список — Whitelist Policy v0.3 раздел 9.4.

---

## Альтернативы, которые рассматривались

- **Только Aave V3 + Compound V3** — отклонено: недостаточная диверсификация yield-источников
- **Включить Sky sUSDS в Tier 1** — отклонено: GSM Pause Delay 24ч не соответствует требованию ≥ 48ч. Добавить после on-chain исправления.
- **Исключить Tier 2 полностью** — рассматривалось. Принято решение включить, т.к. при drawdown 2% Tier 2 сворачивается первым при любом признаке корреляции.
- **Исключить Morpho из Tier 1** — отклонено: curator-managed vaults (Steakhouse, Gauntlet) снижают риск per-market oracle; TVL и аудиты соответствуют Tier 1.

---

## Триггеры для внепланового ре-ревью

- Sky/Spark: on-chain подтверждение GSM Pause Delay ≥ 48ч → перевод в T1 через мини-ADR
- Aave V3: завершение bad debt resolution от KelpDAO → снятие каких-либо ограничений
- Euler V2: 2 квартала чистой работы → снятие Conditional статуса

---

## Последствия

- Whitelist Policy раздел 9 заполнен → блокер paper trading снят
- Paper trading запускается со структурой 70% T1 / 30% T2
- Следующий плановый ре-ревью: Q3 2026
- ADR-004 (запуск paper trading) разблокирован

---

## Подпись Owner

Дата утверждения: 2026-05-02
Owner: Юра
