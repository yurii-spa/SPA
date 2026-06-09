# 21_Strategy_Sandbox

Project: Smart Passive Aggregator (SPA)
Version: v1.0
Status: Draft
Owner: Юра
Last updated: 2026-05-20
Depends on: 18_Agent_Architecture v0.3, Risk_Policy v0.3, Strategy_Passport_Template v0.3, Paper_Trading_and_Simulation_Plan v0.3

---

## 1. Цель

Strategy Sandbox — среда для параллельного тестирования нескольких стратегий без риска для капитала. Позволяет сравнивать стратегии объективно на одних и тех же рыночных условиях.

---

## 2. Принципы

- До **10 стратегий** работают параллельно в paper trading
- Каждая стратегия описана в **YAML-файле** (Strategy Passport, формат по шаблону `Strategy_Passport_Template v0.3`)
- Стратегии **не меняют код** системы — только конфигурацию
- Каждая paper trade тегируется `strategy_id` для изолированного A/B анализа
- Strategy Agent **не различает** paper trading и future live — одна и та же логика, разный режим исполнения (флаг `paper_trading: true`)

Это устраняет классический разрыв "backtest works, live breaks".

---

## 3. Жизненный цикл стратегии

```
DRAFT → PAPER_TESTING → REVIEW → [PROMOTED | ELIMINATED]
```

- **DRAFT**: стратегия написана, не запущена
- **PAPER_TESTING**: параллельный запуск, минимум 8 недель (требование Paper_Trading_and_Simulation_Plan v0.3)
- **REVIEW**: Owner анализирует результаты после минимального срока
- **PROMOTED**: стратегия переходит в кандидаты на live (отдельная процедура согласования)
- **ELIMINATED**: стратегия исключена по Kill Criteria

---

## 4. Критерии оценки

**Минимальный срок теста:** 8 недель (56 дней) — согласно Paper_Trading_and_Simulation_Plan v0.3.

**Критерии элиминации (Kill Criteria):** определяются в каждом Strategy Passport индивидуально. Общие примеры:
- Drawdown превысил лимит стратегии
- Net APY ниже минимального порога 3 недели подряд
- Стратегия нарушила Risk Policy (даже в paper)

**Критерии успеха для продвижения:**
- По типу passive (lending): Sharpe ≥ 2.0, N ≥ 15 сделок, drawdown ≤ установленного лимита
- По типу active (rebalancing): Sharpe ≥ 1.0, N ≥ 30 сделок, drawdown ≤ установленного лимита
- Outperform baseline v1_passive по net APY

---

## 5. Источники данных для backtest

**Исторические данные:**
- DeFiLlama API — APY, TVL, исторические ставки протоколов
- The Graph — on-chain события, liquidations, utilization rates
- Данные берутся с момента деплоя протокола:
  - Aave V3 Ethereum: март 2022+
  - Compound V3: август 2022+
  - Morpho: январь 2023+
  - Yearn V3: середина 2023+

**Воспроизводимость:** каждый backtest запускается на версионированном снимке данных (snapshot_id). Snapshot обновляется еженедельно, но не изменяет уже существующие снимки. Результаты backtest всегда указывают snapshot_id.

---

## 6. Hot-reload стратегий

Изменение YAML-файла стратегии подхватывается системой через watchdog без перезапуска.

**Аудит-лог:** каждое изменение файла стратегии фиксируется:
```
[2026-05-20 10:00:00] strategy_modified: v2_aggressive.yaml
  changed_by: file_watcher
  hash_before: abc123
  hash_after: def456
  diff_summary: max_position_size_usd 800→1200
```

**Ограничение:** hot-reload только для PAPER_TESTING стратегий. Изменение стратегии в статусе PROMOTED требует ADR.

---

## 7. Параллельный запуск и распределение капитала

Каждая стратегия работает в изолированном виртуальном портфеле:
- Стратегии не конкурируют за капитал (paper trading — виртуальные деньги)
- Стандартный виртуальный капитал на стратегию: **$10,000**
- Итоговый baseline для сравнения: `v1_passive` (Stable Lending Core)

---

## 8. Структура папки strategies/

```
strategies/
├── v1_passive.yaml           — baseline, Stable Lending Core (активна)
├── v2_aggressive.yaml        — расширенный whitelist T1+T2 (draft)
├── v3_pendle_focused.yaml    — акцент на Pendle PT (draft)
└── _template.yaml            — шаблон для новых стратегий
```
