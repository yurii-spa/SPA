---
trackerStatus:
  type: agent
title: Потолок «T2 суммарно ≤ 50 %» не перепроверяется на уровне портфеля — 60 % в T2 проходит с нулём нарушений
status: backlog
source: замер 2026-08-18 (побочная находка при разборе agent-morpho-curator-concentration)
created: 2026-08-18
priority: medium
domain: risk (диагностика; правка порогов/гейта — money-path, только через ADR)
---

## Факт

`RiskPolicy.check_new_position` проверяет `max_total_t2_allocation` (0.50) на входе
(`spa_core/risk/policy.py:427–433`). `RiskPolicy.check_portfolio_health` этой проверки **не
делает** вовсе: цикл по позициям (`policy.py:624–637`) сверяет только потолок на отдельный
протокол (T1 40 % / T2 20 %), суммарного T2 там нет.

Замер в песочнице (`$100k`, книга `aave_v3` T1 35 % + три T2 по 20 %):

```
[A] 3×20% morpho + aave 35% → approved=True
    violations: []
    warnings: []
    t2_total=60.0% cash=5.0%
```

60 % в T2 при потолке 50 % — отчёт о здоровье портфеля полностью зелёный.

Через сделки такая книга сегодня не собирается: инкрементальный вход третьего T2 отказывает
(`Total T2 allocation 60.0% would exceed limit 50.0%`). То есть дыра не в пути входа, а в
пути **проверки уже существующей книги**: книга, приехавшая любым другим способом (миграция
состояния, ручная правка `data/`, дрейф тира протокола после входа), не будет опротестована.
Тир — динамический (ADR-055), так что «протокол переехал в T2 после входа» — не гипотетика.

## Что сделать

1. Не трогать пороги. Вопрос только в том, проверяется ли уже действующий потолок ещё и на
   портфеле.
2. Прежде чем добавлять проверку — понять, не станет ли она красной на живой книге
   (сегодня T2 ≈ 40 %, запас есть) и не гейтит ли она де-риск: `check_portfolio_health`
   участвует в money-path, поэтому правка идёт через `pre_cutover_gate` и требует ADR + решения
   владельца.
3. Положительный контроль обязателен: тест, который на книге 60 % T2 краснеет, и тест, который
   на книге 50 % T2 остаётся зелёным.

## Перемер 2026-08-18 — числа подтверждены, класс ШИРЕ одного порога

Замер карточки воспроизведён дословно (`$100k`, `aave_v3` T1 35 % + три T2 по 20 %):

```
[A] 3x20pct T2 + aave 35pct -> approved=True
    violations: []
    warnings:   []
    t2_total=60.0% cash=5.0%

[B] same book via check_new_position(3rd T2 20pct) -> approved=False
    X Total T2 allocation 60.0% would exceed limit 50.0%
    X Chain concentration on ethereum after trade 95.0% exceeds single-chain limit 90.0%
```

Прогон по ВСЕМ порогам (E = `check_new_position`, P = `check_portfolio_health`,
N = `policy_enforcer.validate_positions`) показал, что T2-total — лишь один случай класса:

```
THRESHOLD                      ENTRY       PORTFOLIO   ENFORCER    enforcer rules
per-protocol T1 cap 40%        VIOLATION   VIOLATION   VIOLATION   per_protocol_max_pct
per-protocol T2 cap 20%        VIOLATION   VIOLATION   VIOLATION   per_protocol_max_pct
T2 TOTAL cap 50%               VIOLATION   SILENT      VIOLATION   single_chain_max_pct,t2_max_pct
T3 TOTAL cap 15%               warn-only   SILENT      VIOLATION   t3_max_pct
single-chain cap 90%           VIOLATION   warn-only   VIOLATION   single_chain_max_pct
L2 total cap 50%               VIOLATION   SILENT      VIOLATION   l2_total_max_pct,t3_max_pct
BASE chain cap 20%             SILENT      SILENT      VIOLATION   base_chain_max_pct,t3_max_pct
min cash buffer 5%             VIOLATION   warn-only   VIOLATION   cash_min_pct,single_chain_max_pct
max_protocols = 8              VIOLATION*  SILENT      VIOLATION   max_protocols,t2_max_pct
APY ceiling 30%                VIOLATION   SILENT      SILENT
APY floor 1%                   VIOLATION   SILENT      SILENT
TVL floor $5M                  VIOLATION   SILENT      SILENT
single-position drawdown 3%    n/a         warn-only   SILENT
portfolio drawdown SOFT 5%     VIOLATION   VIOLATION   SILENT
```

`*` — девятая позиция отказывает по кэш-буферу, а НЕ по числу протоколов: `max_protocols`
в `policy.py` не читается ни на одном пути. То же с `max_total_t3_allocation` (блок 8 гейтит
только `tier == "T2"`) и `BASE_CHAIN_CAP`.

Симметричны как VIOLATION на обоих путях только 3 порога из 14: per-protocol T1/T2 и лестница
просадки. Отдельный подкласс — **понижение severity**: кэш-буфер и single-chain на портфеле
живут в `warnings` при `approved=True`, то есть отчёт «пройден», а нарушение не гейтит.

## Второй сторож есть, но слеп ровно к целевому сценарию

`policy_enforcer.validate_positions` (ADR-062) суммарные T2/T3 на КНИГЕ проверяет и вызывается
из `cycle_runner.py:1156,2166`, `risk_gate.py:125`, `portfolio_rebalancer.py:354`. Но тир он
берёт из статических литеральных множеств `T1_ADAPTERS`/`T3_ADAPTERS` (`_normalize_tier`,
строки 206–228), а не из фактического тира позиции. В сценарии ADR-055 (куратор демоутит
удерживаемый протокол T1 → T2) молчат ОБА портфельных сторожа:

```
TRUE t2_total after curator demotion = 75.0% (cap 50%)
enforcer static tiers: {'aave_v3': 'T1', 'compound_v3': 'T1', 'spark_susds': 'T1', 'morpho_blue': 'T2'}
check_portfolio_health -> approved=True violations=[] warnings=[]
policy_enforcer        -> passed=True violations=[]
```

## Цена на живой книге — ноль

`data/current_positions.json` (generated_at 2026-08-02): pendle 20 %, susde 10 %,
extra_finance_base 5 %, morpho_steakhouse 40 %, spark_susds 5 %, кэш 20 %.

```
by enforcer tier: T2 total = 20.0% (cap 50%)  T3 total = 15.0% (cap 15%)
check_portfolio_health TODAY: approved=True violations=[] warnings=[]
COUNTERFACTUAL: T2-total check on portfolio path would fire today? False (20.0% vs cap 50%)
```

Ни одна сегодняшняя позиция не стала бы нарушением. Запас по T2 — 30 п.п.; по T3 запаса нет
вовсе (15.0 % ровно на потолке 15 %).

## Сделано / не сделано

- **Сделано (без владельца, поведение не меняет):** характеризационный тест
  `spa_core/tests/test_risk_policy_gate_symmetry.py` — 12 тестов, зелёный. Фиксирует асимметрию
  как ИЗМЕРЕННЫЙ ФАКТ (докстринг прямо говорит: «фиксация, не одобрение»), плюс три позитивных
  контроля на симметричные пороги. Любая попытка закрыть дыру покрасит тест и потребует ADR.
- **НЕ сделано (money-path, только владелец):** сама проверка в `check_portfolio_health`.
  Карточка владельцу — `owner-decision-proverka-knigi-slabee-proverki-pered-sde.md`.
- **Неполнота замера, честно:** (1) 14 порогов — это пороги `RiskConfig`; оси риска MP-208
  (`check_axes=True`) и capacity MP-209 не разбирались, они опциональны и warn-only;
  (2) не проверено, вызывается ли `check_portfolio_health` в цикле с `check_axes=True`;
  (3) живая книга от 2026-08-02, на момент замера ей 16 дней — свежесть книги разбирается
  отдельной карточкой.
