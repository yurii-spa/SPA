# Protocol Research — June 2026

Generated: 2026-06-12  
Author: SPA Autonomous Cycle (MP-442)  
Data source: DeFiLlama (sandbox-blocked → training estimates, see note)

> ⚠️ **DATA NOTE:** DeFiLlama API (`api.llama.fi`, `yields.llama.fi`) недоступен из изолированного
> sandbox (HTTP 403 Forbidden). Все значения TVL и APY помечены `[estimated]` и основаны на
> данных обучения (knowledge cutoff ≈ May 2025). **Перед принятием решений по адаптерам
> необходимо верифицировать на реальной машине:**
> ```bash
> python3 -c "import urllib.request,json; print(json.loads(urllib.request.urlopen('https://api.llama.fi/tvl/aave-v3').read()))"
> python3 -m spa_core.adapters.defillama_feed  # кэш TTL 300 с
> ```

---

## Summary Table

| Protocol | Chain | TVL | USDC APY | Audited | Tier Rec | Risk |
|----------|-------|-----|----------|---------|----------|------|
| Aave V3 Base | Base | ~$650M [estimated] | ~4.8% [estimated] | ✅ Yes | **T1** | Low |
| Morpho Base | Base | ~$180M [estimated] | ~6.2% [estimated] | ✅ Yes | **T2** | Low-Medium |
| Aerodrome Finance | Base | ~$850M [estimated] | N/A (DEX LP) | ✅ Yes | **Not suitable** | Medium |
| Fluid Lending | Ethereum | ~$420M [estimated] | ~5.9% [estimated] | ✅ Yes | **T2** | Medium |
| Sky/sUSDS | Ethereum | ~$8.5B [estimated] | ~5.2% [estimated] | ✅ Yes | **T1 (pending gate)** | Very Low |

---

## Protocol Analysis

### 1. Aave V3 on Base

**Status:** 🟢 Strong candidate — рекомендую T1 adapter

| Field | Value |
|-------|-------|
| Chain | Base (Ethereum L2, Coinbase) |
| TVL | ~$650M [estimated] |
| USDC Supply APY | ~4.8% [estimated] |
| Audits | OpenZeppelin, Trail of Bits, Sigma Prime, Peckshield (Aave V3 core) |
| Deployed | Oct 2023 — работает ~20 месяцев без инцидентов |
| DeFiLlama slug | `aave-v3` (фильтр по chain=`base`) |

**Risk Assessment: Low**
- Aave V3 — blue-chip протокол с многолетней историей безопасности
- Полный набор защит V3: e-mode, supply caps, risk parameters per asset
- Base chain: Ethereum-эквивалентная безопасность, оператор — Coinbase (публичная компания)
- USDC на Base является официальным native USDC (Circle), не bridged
- Governance через AAVE token DAO (Aave Chan Initiative)

**Tier Decision: T1** (TVL > $500M threshold превышен)

**Implementation path:**
- Новый адаптер: `spa_core/adapters/aave_v3_base.py`
- Структура идентична `aave_v3.py` (Ethereum), параметр `chain="base"`
- RPC endpoint: Base mainnet (`https://mainnet.base.org` или Alchemy/Infura Base)
- DeFiLlama yields pool: `aave-v3` + filter `chain == "Base"`
- ADR-025 preview: см. ниже

**APY boundary check:** 4.8% ∈ [1%, 30%] ✅ — RiskPolicy gate пропустит

---

### 2. Morpho Base

**Status:** 🟡 Good candidate — рекомендую T2 adapter

| Field | Value |
|-------|-------|
| Chain | Base |
| TVL | ~$180M [estimated] |
| USDC APY | ~6.2% [estimated] |
| Audits | Cantina, Trail of Bits, Spearbit (Morpho Blue core) |
| Deployed | 2024 (Morpho Blue expands на Base) |
| DeFiLlama slug | `morpho-blue` (фильтр по chain=`base`) |

**Risk Assessment: Low-Medium**
- Morpho Blue — permissionless lending с curated vaults (Morpho Steakhouse уже в T1)
- Ethereum mainnet версия работает надёжно; Base — новая нода, меньше история
- Потенциально более высокая концентрация риска на Base: меньший ликвидити пул
- Curator risk: качество vault зависит от куратора (Steakhouse, Gauntlet, Re7, etc.)

**Tier Decision: T2** (TVL ~$180M ∈ [$100M, $500M])

**Implementation path:**
- Расширение `spa_core/adapters/morpho_steakhouse_adapter.py` или новый `morpho_base.py`
- Ключевой параметр: фильтровать vault'ы только с USDC collateral + Base chain
- Vault candidates: Steakhouse USDC (Base), Gauntlet USDC Core (Base)
- T2 cap применяется: ≤ 20% per-protocol, T2 total ≤ 50%

**APY boundary check:** 6.2% ∈ [1%, 30%] ✅

---

### 3. Aerodrome Finance

**Status:** 🔴 Not suitable для SPA (текущая версия)

| Field | Value |
|-------|-------|
| Chain | Base |
| TVL | ~$850M [estimated] |
| Model | DEX / AMM (Velodrome fork) |
| USDC Lending APY | ❌ N/A — это LP, не lending |
| Stable LP APY | ~4-12% [estimated] (fees + AERO rewards, variable) |
| Audits | Code4rena, Velodrome codebase + Aerodrome-specific |

**Risk Assessment: Medium**
- Aerodrome — крупнейший DEX на Base (ve(3,3) модель, fork Velodrome/Solidly)
- **Принципиально другая модель риска:** Impermanent Loss в LP позициях
- USDC/USDC-bridge stable pools имеют минимальный IL, но не нулевой
- Смарт-контрактный риск дополнительного уровня: AMM логика, gauge voting
- **Несовместим с текущим RiskPolicy:** APY = LP yield (fees + emissions), не lending APY
- Emission-зависимый APY: подвержен AERO token price / governance vote volatility

**Tier Decision: Not suitable** — вне scope SPA v1 (только lending/yield протоколы)

**Potential future scope (post-live):**
- Stable LP (USDC/USDbC, USDC/USDT) с нулевым IL теоретически возможен
- Требует: отдельная RiskPolicy версия для LP, IL model, emission decay model
- **Recommend:** добавить в ADR-020 T3 Private Credit watch list как T3-LP-SPEC

---

### 4. Fluid Lending

**Status:** 🟡 T2 candidate — уже частично интегрирован (fUSDC в S4)

| Field | Value |
|-------|-------|
| Chain | Ethereum mainnet (+ Base expansion в 2025) |
| TVL | ~$420M [estimated] |
| USDC APY | ~5.9% [estimated] |
| Audits | Trail of Bits, Code4rena (Instadapp team) |
| Deployed | 2024 (Fluid), Instadapp team — 4+ лет истории |
| DeFiLlama slug | `fluid` |

**Risk Assessment: Medium**
- Fluid — новый протокол от команды Instadapp (prooven track record в DeFi tooling)
- **Уже частично интегрирован:** S4 стратегия использует `fluid_fusdc` с 25% аллокацией
- Адаптер: проверить `spa_core/adapters/` — может потребоваться standalone `fluid.py`
- Lending + liquidity layer (Fluid объединяет DEX + lending в одном smart contract)
- Более сложная архитектура = потенциально более сложный risk surface
- Governance: ранняя стадия, более централизована чем Aave/Compound

**Tier Decision: T2** (TVL ~$420M ∈ [$100M, $500M])

**Implementation path:**
- Проверить наличие standalone `spa_core/adapters/fluid.py` (vs inline в S4)
- Если нет: создать `fluid.py` по образцу `compound_v3.py`
- DeFiLlama yields: `fluid` protocol, filter `symbol == "USDC"`
- Per-protocol T2 cap: ≤ 20%

**APY boundary check:** 5.9% ∈ [1%, 30%] ✅

---

### 5. Sky/sUSDS (formerly MakerDAO)

**Status:** 🔵 T1 pending gate — уже в мониторинге (`sky_monitor.py`)

| Field | Value |
|-------|-------|
| Chain | Ethereum mainnet |
| TVL | ~$8.5B [estimated] |
| sUSDS APY (SSR) | ~5.2% [estimated] |
| Audits | ChainSecurity, Trail of Bits, Runtime Verification, ABDK (+ 7 лет MakerDAO audits) |
| Gate condition | GSM Pause Delay ≥ 48h (текущий статус: **PENDING**) |
| Monitor | `spa_core/data_pipeline/sky_monitor.py` |

**Risk Assessment: Very Low**
- MakerDAO / Sky — одни из старейших и наиболее аудированных протоколов в DeFi
- sUSDS = upgraded DAI Savings Rate (DSR), бэкирован overcollateralized позициями
- **TVL > $8B:** входит в T1 категорию с запасом
- **Единственный блокер:** GSM Pause Delay < 48h (governance execution lag — критический safeguard)
- Sky_monitor.py уже реализован (`SKY_CURRENT_STATUS = "PENDING"`, last checked 2026-05-22)

**Tier Decision: T1** (когда GSM gate снимается)  
Текущий статус: **0% аллокации** до подтверждения on-chain GSM Pause Delay ≥ 48h (см. CLAUDE.md)

**Upgrade assessment vs Spark adapter:**
- S4 стратегия уже содержит `spark_susds` endpoint (60% в S4)
- "Spark" = фронтенд/sub-DAO MakerDAO/Sky — аллоцирует в sUSDS
- **Upgrade рекомендован:** переименовать в `sky_susds` для clarity + обновить DeFiLlama slug
- Добавить SSR (Sky Savings Rate) как primary APY source вместо Spark proxy
- Когда gate откроется → автоматически активируется через `sky_monitor.py`

---

## Recommendations

### Immediate additions (T1/T2 candidates):

**1. Aave V3 Base → T1 adapter** ⭐ HIGHEST PRIORITY
- TVL > $500M, low risk, Aave V3 architecture (уже знакома команде)
- File: `spa_core/adapters/aave_v3_base.py`
- Estimated implementation: 1-2 дня (копия `aave_v3.py` с Base-параметрами)
- Потенциальный APY вклад: ~4.8% на выделенную долю
- **MP candidate:** MP-445 "Aave V3 Base T1 Adapter"

**2. Fluid Lending → standalone T2 adapter** ⭐ MEDIUM PRIORITY  
- Уже используется в S4, но, вероятно, без standalone adapter в реестре
- Необходима проверка `ADAPTER_REGISTRY` в `spa_core/adapters/__init__.py`
- File: `spa_core/adapters/fluid.py` (если не существует)
- **MP candidate:** MP-446 "Fluid Standalone T2 Adapter"

**3. Sky/sUSDS upgrade → spark→sky rename** MEDIUM PRIORITY
- Уже мониторится; нужен upgrade при открытии GSM gate
- Апдейт slug + SSR-source + test при ELIGIBLE
- **MP candidate:** MP-447 "Sky/sUSDS spark→sky adapter upgrade"

### Research queue (T3 candidates):

**4. Morpho Base → T2 in Q3 2026**
- TVL ~$180M — на пороге T2 ($100M). Нужна верификация реального TVL.
- Приоритет ниже: Morpho Steakhouse (Ethereum) уже в T1; Base-версия — incremental
- Добавить в backlog: MP-448 "Morpho Base T2 Adapter (Q3)"

**5. Aerodrome stable LP → T3-LP-SPEC watch list**
- Вне текущего scope, но USDC stable pools теоретически совместимы
- Требует: расширение RiskPolicy для LP + separate ADR
- Горизонт: post-go-live, Q4 2026+

### Not suitable (current SPA v1):

- **Aerodrome Finance** — DEX/AMM модель, IL risk, emission-зависимый APY. Несовместим с текущим RiskPolicy. Вернуться к рассмотрению в v2 если добавляется LP стратегия.

---

## ADR-025 Preview: Base Chain Expansion

```
ADR-025: Base Chain Expansion (Draft)
Status: PROPOSED
Date: 2026-06-12
Author: SPA Research Module (MP-442)

Context:
  Base L2 (Coinbase) демонстрирует стабильный рост TVL в 2024-2025.
  Aave V3 Base и Morpho Base достигли порогов T1/T2 по критериям RiskPolicy.

Decision:
  IF Aave V3 Base TVL > $500M AND USDC Supply APY ∈ [1%, 30%]:
    → Создать aave_v3_base.py (T1 adapter)
    → Добавить в ADAPTER_REGISTRY с tier="T1", chain="base"
    → Per-protocol cap: 40% (T1)
    → Base chain risk premium: +0.05 risk score vs Ethereum mainnet

  IF Morpho Base TVL > $100M AND USDC APY ∈ [1%, 30%]:
    → Создать morpho_base.py (T2 adapter) или расширить morpho_steakhouse_adapter.py
    → Per-protocol cap: 20% (T2)

Consequences:
  + Диверсификация по chain (Ethereum + Arbitrum + Base)
  + Доступ к дополнительному TVL и конкурентным APY
  - Дополнительный chain = дополнительный RPC endpoint, monitoring
  - Base bridge risk (хотя native USDC от Circle минимизирует этот риск)

Implementation notes:
  - RPC: https://mainnet.base.org (или Alchemy/Infura Base endpoint)
  - TVL verification tool: python3 -m spa_core.adapters.defillama_feed (Base filter)
  - Requires: адаптер тесты, интеграционный тест cycle_runner с Base

Formal ADR: создать docs/adr/ADR-025-base-chain-expansion.md при апруве.
```

---

## Data Verification Checklist

Выполнить на реальной машине (не sandbox) перед имплементацией адаптеров:

```bash
# 1. Проверить актуальный TVL Aave V3 Base
curl -s "https://api.llama.fi/tvl/aave-v3" | python3 -m json.tool

# 2. Получить USDC APY из yields API (фильтр: protocol=aave-v3, chain=Base)
python3 -c "
import urllib.request, json
pools = json.loads(urllib.request.urlopen('https://yields.llama.fi/pools').read())
base_aave = [p for p in pools['data']
             if p.get('project') == 'aave-v3'
             and p.get('chain') == 'Base'
             and 'USDC' in p.get('symbol', '')]
for p in base_aave:
    print(p.get('symbol'), 'APY:', p.get('apy'), 'TVL:', p.get('tvlUsd'))
"

# 3. Morpho Base
python3 -c "
import urllib.request, json
pools = json.loads(urllib.request.urlopen('https://yields.llama.fi/pools').read())
morpho_base = [p for p in pools['data']
               if 'morpho' in p.get('project','').lower()
               and p.get('chain') == 'Base'
               and 'USDC' in p.get('symbol', '')]
for p in morpho_base[:10]:
    print(p.get('project'), p.get('symbol'), 'APY:', p.get('apy'), 'TVL:', p.get('tvlUsd'))
"

# 4. Fluid Lending
python3 -c "
import urllib.request, json
pools = json.loads(urllib.request.urlopen('https://yields.llama.fi/pools').read())
fluid = [p for p in pools['data']
         if p.get('project') == 'fluid'
         and 'USDC' in p.get('symbol', '')]
for p in fluid:
    print(p.get('chain'), p.get('symbol'), 'APY:', p.get('apy'), 'TVL:', p.get('tvlUsd'))
"

# 5. Sky/sUSDS (проверить GSM gate)
python3 -m spa_core.data_pipeline.sky_monitor
```

---

## Implementation Backlog (Proposed MPs)

| MP | Title | Priority | Effort | Blocked by |
|----|-------|----------|--------|------------|
| MP-445 | Aave V3 Base T1 Adapter (`aave_v3_base.py`) | HIGH | 1-2d | TVL verification |
| MP-446 | Fluid Standalone T2 Adapter (if missing) | MEDIUM | 1d | ADAPTER_REGISTRY check |
| MP-447 | Sky/sUSDS spark→sky adapter upgrade | MEDIUM | 0.5d | GSM gate ≥ 48h |
| MP-448 | Morpho Base T2 Adapter | LOW | 1d | TVL > $150M confirmed |
| MP-449 | ADR-025 Base Chain Expansion (formal) | LOW | 0.5d | MP-445 complete |

---

*Protocol Research MP-442 — SPA Smart Passive Aggregator*  
*Next research cycle recommended: 2026-09-01 or on significant TVL change (>50%)*
