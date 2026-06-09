# Strategy Passport: Stable Lending Core

Project: Smart Passive Aggregator (SPA)
Version: v0.3
Status: Draft
Owner: Юра
Last updated: 2026-05-01
Depends on: Risk Policy v0.3, Mode Policy v0.3, Whitelist Policy v0.3, Strategy Passport Template v0.3, Execution Cost Model v0.3, Paper Trading & Simulation Plan v0.3

Changelog from v0.2:
- Исправлено противоречие статуса.
- Раздел 5 переписан под трёхуровневую структуру.
- Добавлен раздел 4.3 «Governance / oracle / regulatory checks» — заполнен для 3 кандидатов.
- Добавлен раздел 4.4 «Tier классификация».
- Добавлен раздел 5.2 «Drawdown-лимиты стратегии» строже общих (1%/2%/3%).
- Раздел 11 «Kill Criteria» с числовыми порогами.
- Добавлен раздел 12 «Paper trading milestones».
- ADR references добавлены.

---

## 1. Общая информация

- **Название:** Stable Lending Core
- **Режим:** A (только стейблы)
- **Статус:** Draft (целевой — Paper после ADR-004)
- **Дата создания:** 2026-02 (исходный v0.1)
- **Автор:** Owner
- **ADR утверждения:** ADR-2026-002 (whitelist) + ADR-2026-004 (запуск paper)

Кратко: размещение USDC/USDT в крупных lending-протоколах с защитой через quarterly re-review и tight drawdown-лимиты.

---

## 2. Цель и логика

### 2.1. Цель
Стратегия должна давать **net APY ≥ 4% годовых при $10K** (см. ADR-009 для других уровней капитала) при drawdown ≤ 2% годовых.

Источник дохода: lending interest от заёмщиков на Aave V3, Compound V3 + SSR (Sky Savings Rate) от Sky.

### 2.2. Когда стратегия НЕ работает
- bear DeFi (нет заёмщиков → APY падает к 0);
- panic gas (ребалансировки не оправданы);
- регуляторный SEV-1 на USDC/USDT.

---

## 3. Активы и протоколы

### 3.1. Активы
- USDC (primary)
- USDT (secondary)

### 3.2. Протоколы (первый whitelist через ADR-002)

**Active whitelist v0.3 — три протокола:**
- **Aave V3 USDC** (Ethereum L1) — lending top-1. ⚠️ Начальный лимит 5% портфеля (90 дней) из-за KelpDAO инцидента апр 2026.
- **Compound V3 USDC** (Ethereum L1) — lending консервативный. ✅ Стандартные лимиты.
- **Sky sUSDS** (Ethereum L1) — yield-bearing stable, SSR ~4.25%. ✅ Стандартные лимиты. *Использовать sUSDS, не sDAI.*

**Резерв для следующих ADR:** Morpho Blue, Spark Protocol.

### 3.3. Governance / oracle / regulatory checks

| Протокол | Governance | Oracle | Timelock | Regulatory | Audits |
|----------|-----------|--------|----------|------------|--------|
| Aave V3 | DAO активен, доли распределены, последний proposal: 2026-04 | Chainlink (multi-feed) + CAPO risk-stewards | ≥48ч (соответствует Tier 1) | OFAC ✅ 2026-05-02 | Trail of Bits, OpenZeppelin, Certora, ChainSecurity |
| Compound V3 | DAO активен, COMP holders, timelock проверен | Chainlink (multi-feed) | ≥48ч | OFAC ✅ 2026-05-02 | OpenZeppelin, ChainSecurity |
| Sky sUSDS | Sky DAO (бывший Maker), MKR holders | Sky PSM (peg-arbitrage stability mechanism) + Chainlink overlay | GSM Pause Delay 24ч (отметка: для Tier 1 требуется 48ч; включён по решению Owner с пониманием) | OFAC ✅ 2026-05-02 | многочисленные исторические + ChainSecurity |

### 3.4. Tier классификация
Все протоколы — Tier 1 (через ADR-002).

---

## 4. Ограничения и лимиты

### 4.1. Структура лимитов

| Параметр | Целевая | Максимальная | Жёсткая |
|----------|---------|--------------|---------|
| Доля стратегии в портфеле | 70% | 80% | 85% |
| Aave V3 USDC | 30% от стратегии | 40% | 50% (но фактически 5% портфеля 90 дней) |
| Compound V3 USDC | 30% от стратегии | 40% | 50% |
| Sky sUSDS | 40% от стратегии | 50% | 60% |
| Один актив (USDC vs USDT) | 70% | 80% | 90% |

### 4.2. Drawdown-лимиты стратегии (строже общих)

| Метрика | Порог | Действие |
|---------|-------|----------|
| Daily DD стратегии | 1% | alert |
| Weekly DD | 2% | freeze (Paused) |
| Monthly DD | 3% | mandatory review |

### 4.3. Прочие лимиты
- любой новый протокол: 1-3% портфеля + 90-дневный мониторинг.

---

## 5. Ребаланс

- триггеры: drift > 10% от целевой, APY изменение > 30% относительно;
- частота: ожидаемо 1-2 раза в месяц;
- частые ребалансы — негативный сигнал.

---

## 6. Бенчмарк

- USDC удерживается на CEX или non-yielding кошельке = 0% APY;
- наш target: net APY ≥ 4% (для $10K, см. ADR-009).

---

## 7. Жизненный цикл

Текущий статус: **Draft** → ADR-002 + ADR-004 → **Paper** → (после 8 недель) → ADR на live → **Active**.

---

## 8. Доходность

- **Целевой gross APY:** ~5.0% (weighted Aave+Compound+Sky);
- **Целевой net APY (для $10K):** ≥ 4% (после газа);
- **Стоп-уровень:** если net APY ниже 2% за 30+ дней → Paused.

### 8.1. Yearn V3 yvUSDC fee note (контекст из v0.4.5)
*(применимо если стратегия будет расширена)*

APY Yearn V3 yvUSDC в прогнозах SPA — net of 15% performance fee, как публикуется на yearn.fi.

---

## 9. Триггеры остановки

См. Risk Policy 7. Любой SEV-1 для протокола стратегии = немедленный pause.

---

## 10. Kill Criteria (численные)

Стратегия **закрывается** (Retired) при:
- 3+ Active → Paused циклов за 90 дней;
- Net APY < 2% за 60 дней;
- Кумулятивный drawdown стратегии > 5% от стартового capital;
- Все 3 Tier 1 протокола стратегии исключены из whitelist (regulatory или audit reasons).

Решение — Owner через ADR.

Закрытие = запрет новых входов + плановый выход 30 дней + post-mortem.

---

## 11. Paper trading milestones

- **Week 0:** Baseline зафиксирован (см. Paper_Trading_Week0_Baseline);
- **Week 2:** первый weekly report;
- **Week 4:** mid-point review, симуляция accuracy check;
- **Week 8:** финальный отчёт + готовность к live ADR.

---

## 12. Условия выхода в Active

См. Strategy Passport Template 13. Текущий статус — Draft → Paper.

---

## 13. ADR references

- **ADR-2026-002** (whitelist Tier 1 — основа стратегии);
- **ADR-2026-004** (запуск paper trading);
- **ADR-2026-005..009** (расширения в v0.4 / v0.4.5).

---

## 14. Strategy Owner

- **Strategy Owner:** Юра (Owner проекта на Self-Capital).
- **Backup:** не определён.

---

## 15. Решение о запуске

- Risk Policy v0.3: ✅ соответствует;
- Mode Policy v0.3 (Режим A): ✅ соответствует;
- Whitelist Policy v0.3: ✅ через ADR-002;
- Execution Cost Model v0.3: ✅ соответствует.

**Решение:** **Approved for Paper Trading** (через ADR-004, 2026-05-02).

---

## 16. Статус

Статус: Draft → Paper Trading (с 2026-05-02 при условии setup).
