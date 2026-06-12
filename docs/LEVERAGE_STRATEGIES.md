# LEVERAGE_STRATEGIES — SPA Advanced Yield Engineering
**Дата:** 2026-06-12 | **Автор:** SPA Quant Module | **Версия:** v1.0
**Статус:** Paper Trading Research | **Классификация:** Internal — Tournament Candidates

---

## 0. Краткое Резюме

| Стратегия | Target APY | Режим рынка | Реализуемость | Min Capital |
|-----------|-----------|-------------|--------------|------------|
| S8: Delta-Neutral sUSDe | 13–24% | Bull only | 2/5 | $20K |
| S9: Aave E-Mode Loop | 7–10% | All markets | 3/5 | $20K |
| S10: Pendle YT/PT Note | –23%..+67% | Bull only | 2/5 | $10K |

**Ключевой вывод:** S9 — единственная из трёх, работающая в любом market regime и масштабируемая до $1M. S8 и S10 требуют устойчивого bull-рынка (ETH funding > 0.005%/8h в течение 14+ дней) и активного мониторинга. Для tournament — тестировать все три, но реальный капитал направлять только в S9 и S8 при подтверждённом bull.

---

## 1. Стратегия S8: Delta-Neutral sUSDe Funding Harvest

### 1.1 Механика

Ethena (sUSDe) — синтетический доллар с встроенной delta-neutral позицией:

```
sUSDe yield = stETH staking yield (~4%) + ETH perp short funding rate

Bull market (funding > 0):  sUSDe APY = 15–25%
Bear market (funding → 0):  sUSDe APY = 4–7%
Extreme bear (negative):    sUSDe APY может упасть до 0–2%
```

**Добавочный слой SPA — Basis Trade Overlay:**
Поверх sUSDe открывается SHORT ETH perp на GMX v2 / Gains Network / Vertex:
- Когда рынок в contango → long pays short → SPA получает дополнительный funding
- Захватывается **спред между implied perp funding и realized sUSDe funding**
- Net ETH delta = sUSDe (уже hedged через Ethena) + GMX short = 0.0 ETH

**Что это НЕ такое:** стратегия не создаёт leverage на цену ETH. Единственный P&L source — funding rates. Потенциальный убыток от «price движения» минимален, доминирует yield capture.

### 1.2 P&L Расчёт ($30K капитал, 1 год)

**Предположения:**
- $30,000 конвертированы в sUSDe (on-chain, ERC-4626 deposit)
- GMX v2 SHORT ETH perp: $30K notional, margin $3K (10× leverage на hedge — умеренно)
- Gas на rebalance: $20/транзакцию × 12 раз в год = $240
- Entry/exit slippage: 0.1% от суммы × 2 стороны = $60

| Параметр | Bear | Base | Bull | Extreme Bull |
|---------|------|------|------|-------------|
| sUSDe rolling APY | 5% | 15% | 22% | 28% |
| GMX short funding (ann.) | –3% | +1% | +3% | +5% |
| Gas + slippage | –1.0% | –1.0% | –1.0% | –1.0% |
| **Net APY** | **1.0%** | **15.0%** | **24.0%** | **32.0%** |
| **P&L за 30 дней** | **+$25** | **+$370** | **+$592** | **+$789** |
| **P&L за год** | **+$300** | **+$4,500** | **+$7,200** | **+$9,600** |

**Детальный bull P&L ($30K, год):**
```
sUSDe yield:          $30,000 × 22.0% = +$6,600
GMX short funding:    $30,000 ×  3.0% = +$900
Gas (12 rebalances):                   –$240
Slippage (entry+exit):                 –$60
──────────────────────────────────────────────
Net P&L:                               +$7,200
Net APY на $30K:                        24.0%
Sharpe ratio (est.):                    ~1.8 (low vol, funding is mean-reverting)
```

**Детальный base P&L ($30K, год):**
```
sUSDe yield:          $30,000 × 15.0% = +$4,500
GMX short funding:    $30,000 ×  1.0% = +$300
Gas:                                   –$240
Slippage:                              –$60
──────────────────────────────────────────────
Net P&L:                               +$4,500
Net APY:                                15.0%
```

### 1.3 Entry / Exit Условия

**Открытие позиции (ВСЕ условия AND):**
```python
ENTRY_CONDITIONS = {
    "susde_7day_rolling_apy"  : ">= 12%",      # Ethena dashboard / DeFiLlama
    "gmx_net_funding_annualized": "> -1%",      # Не хуже –1% для shorts
    "ethena_tvl_usd"          : ">= 500_000_000",  # $500M circuit breaker
    "susde_usdc_peg_deviation" : "< 0.005",     # |price – 1.00| < 0.5%
    "spread_net"              : ">= 10%",       # sUSDe_APY + GMX_funding – gas > 10%
}
```

**Закрытие позиции (ЛЮБОЕ условие OR):**
```python
EXIT_CONDITIONS = {
    "susde_48h_apy_below"      : "< 8%",        # Rotate → Aave/Morpho
    "gmx_funding_negative_days": ">= 3",         # Funding отрицательный 3+ дня подряд
    "susde_depeg"              : "> 0.5%",       # Экстренный exit
    "portfolio_drawdown"       : ">= 5%",        # SPA kill-switch
    "spread_net_below"         : "< 6%",         # Margin сжался → не выгодно
}
```

**Funding Rate Threshold Matrix:**

| Spread (sUSDe APY + GMX funding - costs) | Действие |
|------------------------------------------|---------|
| ≥ 15% | Full position ($30K) |
| 10–15% | Reduced position ($15–20K) |
| 6–10% | Hold, не добавлять |
| < 6% | Начать wind-down за 24ч |
| < 0% (net negative) | Немедленный exit |

### 1.4 Риск-Матрица

| Риск | P(год) | Magnitude | Mitigation |
|------|--------|-----------|-----------|
| Ethena smart contract exploit | 3–5% | Полная потеря $30K | Cap 20% портфеля; мониторинг Ethena governance |
| sUSDe depeg (temporary, < 24ч) | 10–15% | –0.5–3% | Auto-exit при 0.5% depeg; Chainlink oracle |
| sUSDe depeg (severe, bank run) | 1–2% | –10–30% | $500M TVL floor; exit при первом сигнале |
| Funding turns negative (bear) | 40–60% | –1–5% APY drag | Funding threshold; rotate T1 |
| GMX liquidation on hedge | < 1% | –$3K (margin only) | 10× leverage max; мониторинг каждые 4ч |
| GMX smart contract | 2–3% | –$3K (margin) | Hedge position only, не основной капитал |
| Regulatory / Ethena blacklist | < 1% | Forced full exit | Мониторинг governance |

**Максимальный APY (bull, всё благоприятно):** 30–35%
**Минимальный APY (bear, funding умеренно отрицательный):** 1–3%
**Break-even:** sUSDe APY > 3% (исторически выполнялось 80%+ времени)

### 1.5 On-Chain Реализуемость (Python + Gnosis Safe)

**Ключевые контракты (Ethereum Mainnet):**

```python
# Ethena
USDE_MINTING      = "0xe3490297a08d6fC8Da46Edb7B6142E4F461b62D3"
SUSDE             = "0x9D39A5DE30e57443BfF2A8307A4256c8797A3497"  # ERC-4626

# GMX v2
GMX_ROUTER        = "0x7452c558d45f8afC8c83dAe62C3f8A5BE19c71f6"  # ExchangeRouter
GMX_FUNDING_STORE = "0xD7c4c7F2BdFFC4BDE1f4baF4f22A4d7C23F3EB3"
ETH_USDC_MARKET   = "0x70d95587d40A2caf56bd97485aB3Eec10Bee6336"

# --------------------------------------------------------------------------
# Шаг 1: USDC → USDe → sUSDe
# --------------------------------------------------------------------------
# 1a. USDC approve → USDeMinting
usdc.approve(USDE_MINTING, 30_000e6)

# 1b. Mint USDe (требует whitelist или использовать Curve pool)
# Альтернатива: swap USDC→USDe через Curve pool (0x...3pool_usde)
curve_pool.exchange(USDC_INDEX, USDE_INDEX, 30_000e6, min_out)

# 1c. USDe deposit → sUSDe (ERC-4626 стандарт)
susde.deposit(assets=usde_balance, receiver=safe_address)

# --------------------------------------------------------------------------
# Шаг 2: Открыть SHORT ETH perp на GMX v2
# --------------------------------------------------------------------------
gmx_router.createOrder(
    CreateOrderParams(
        addresses={
            "receiver"         : safe_address,
            "callbackContract" : ZERO_ADDRESS,
            "market"           : ETH_USDC_MARKET,
            "initialCollateralToken": USDC,
        },
        numbers={
            "sizeDeltaUsd"               : int(30_000 * 1e30),   # $30K notional
            "initialCollateralDeltaAmount": int(3_000 * 1e6),    # $3K margin
            "triggerPrice"               : 0,
            "acceptablePrice"            : 0,                    # market order
            "executionFee"               : WEI_FEE,
            "callbackGasLimit"           : 0,
            "minOutputAmount"            : 0,
        },
        orderType  = OrderType.MarketIncrease,
        decreasePositionSwapType = SwapType.NoSwap,
        isLong     = False,   # SHORT
        shouldUnwrapNativeToken = False,
        referralCode = ZERO_BYTES32,
    )
)

# --------------------------------------------------------------------------
# Мониторинг (read-only, 4ч интервал)
# --------------------------------------------------------------------------
def get_funding_rate_annualized():
    """GMX v2: funding_rate в %/8h → annualise"""
    market_info = gmx_reader.getMarketInfo(datastore, prices, ETH_USDC_MARKET)
    rate_per_8h = market_info.nextFunding.shortFundingFeeAmountPerSize / 1e30
    return rate_per_8h * (24 / 8) * 365 * 100  # %/year

def get_susde_apy_7day():
    """DeFiLlama yields API — только stdlib urllib"""
    import urllib.request, json
    url = "https://yields.llama.fi/poolsEnriched?pool=susde-ethena"
    with urllib.request.urlopen(url, timeout=10) as r:
        data = json.loads(r.read())
    return data['data'][0]['apy']  # 7-day rolling APY

# --------------------------------------------------------------------------
# Шаг 3: Exit (полное закрытие)
# --------------------------------------------------------------------------
# 3a. Закрыть GMX short (createOrder с MarketDecrease)
# 3b. Вывести sUSDe: susde.redeem(shares, receiver, owner)
# 3c. Swap USDe → USDC через Curve
```

**Gnosis Safe совместимость:**
- Все вызовы принимают `receiver`/`onBehalfOf` = Safe address ✓
- Batch TX: approve + swap + deposit + GMX order = 4 actions в одном Safe batch ✓
- GMX v2 подтверждённо работает с multisig адресами ✓
- Мониторинг: read-only через `eth_call`, не требует Safe

**Минимальный капитал:** $20K (gas < 0.5% от позиции). Оптимально: $25–40K. Максимум: $40K при $100K portfolio (40% cap T1 per RiskPolicy, но sUSDe = T2 by protocol).

---

## 2. Стратегия S9: Aave E-Mode USDC Looping (2× Leverage)

### 2.1 Механика

Aave V3 Stablecoin E-Mode (Category 1, Ethereum Mainnet):

```
LTV максимальный:        93%
Liquidation Threshold:   95%
Liquidation Penalty:     1%
Доступные активы:        USDC, USDT, DAI, GHO, LUSD, USDE
```

**Стратегия 3-шага:**
1. Deposit USDC в Aave (earn supply APY ~3%)
2. Borrow DAI/USDT в e-mode на 90% LTV (low liquidation risk при stablecoin-to-stablecoin)
3. Redeploy borrowed capital в более высокодоходный протокол (Morpho Blue, Pendle PT)

**Почему E-Mode критичен:** стандартный Aave USDC LTV = 77%. E-mode даёт 93% → на $50K можно занять $46.5K vs $38.5K стандартного → +$8K на работе → существенная разница в yield.

### 2.2 P&L При Разных LTV

**Базовые параметры:**
- Initial capital: $50,000 USDC
- Supply APY (Aave USDC): 3.0%
- Borrow APY (DAI variable rate): 4.5%
- Redeployment target: Morpho Blue USDC market — 9.0% APY (conservative) или 10% (base)

| LTV | Borrowed | Supply Earn | Borrow Cost | Redeploy Earn | Gas | **Net P&L** | **Net APY** |
|-----|---------|------------|-----------|--------------|-----|------------|------------|
| 70% | $35,000 | +$1,500 | –$1,575 | +$3,150 | –$150 | +$2,925 | **5.85%** |
| 80% | $40,000 | +$1,500 | –$1,800 | +$3,600 | –$150 | +$3,150 | **6.30%** |
| 85% | $42,500 | +$1,500 | –$1,913 | +$3,825 | –$150 | +$3,262 | **6.52%** |
| 90% | $45,000 | +$1,500 | –$2,025 | +$4,050 | –$150 | +$3,375 | **6.75%** |
| 90% | $45,000 | +$1,500 | –$2,025 | +$4,500* | –$150 | +$3,825 | **7.65%** |
| 90% | $45,000 | +$1,500 | –$2,025 | +$5,400** | –$150 | +$4,725 | **9.45%** |

\* Redeployment в Morpho Blue при 10% APY (оптимальный сезон).
\** Redeployment в Pendle sUSDe PT при 12% fixed APY (bull market PT discount).

**Полный P&L при 90% LTV + 10% Morpho ($50K, год):**
```
Deposit:              $50,000 USDC → Aave E-Mode
Borrow:               $45,000 DAI → Morpho Blue

Supply yield:         $50,000 × 3.0%  = +$1,500
Borrow cost:         –$45,000 × 4.5%  = –$2,025
Redeploy yield:       $45,000 × 10.0% = +$4,500
Gas (monthly checks): 12 × $12.5/tx   = –$150
──────────────────────────────────────────────────
Annual Net P&L:                        +$3,825
Net APY on $50K:                         7.65%
Effective leverage:                      1.9×
Capital efficiency vs S0 Aave:           +4.65% APY gain
```

**При favourable conditions (DAI borrow rate drops to 3%):**
```
Borrow cost:         –$45,000 × 3.0%  = –$1,350
Net P&L:              +$1,500 – $1,350 + $4,500 – $150 = +$4,500
Net APY:               9.0%
```

**При unfavourable conditions (DAI borrow spikes to 7%):**
```
Borrow cost:         –$45,000 × 7.0%  = –$3,150
Net P&L:              +$1,500 – $3,150 + $4,500 – $150 = +$2,700
Net APY:               5.4% → marginal benefit vs risk
```

**Breakeven borrow rate:** DAI borrow APY при котором S9 = S0 Aave:
```
0 = (supply_apy × $50K) – (borrow_rate × $45K) + (redeploy_apy × $45K) – gas
borrow_rate = (supply_apy × $50K + redeploy_apy × $45K – gas) / $45K
breakeven_borrow = ($1,500 + $4,500 – $150) / $45,000 = 13.0%
```
Позиция прибыльна пока DAI borrow < 13% — очень комфортный буфер.

### 2.3 Liquidation Risk Analysis

**Health Factor:**
```
HF = (collateral × liquidation_threshold) / total_debt
HF = ($50,000 × 95%) / $45,000 = 1.056
```

При LTV = 90% в e-mode, HF = 1.056 — опасно мало. Ликвидация при HF < 1.0.

**Сценарии угрозы ликвидации:**

| Событие | Воздействие на HF | HF после | Статус |
|---------|-----------------|---------|--------|
| Стабильный рынок | Нет | 1.056 | ✅ Safe |
| USDC временный depeg –1% | Collateral –$500 | 1.046 | ⚠️ Мониторинг |
| USDC depeg –2% (2023 SVB уровень) | Collateral –$1,000 | 1.034 | 🔴 Alert |
| USDC depeg –3% | Collateral –$1,500 | 1.022 | 🔴🔴 Deleverage NOW |
| USDC depeg –5.4% | Collateral –$2,700 | 1.000 | ☠️ LIQUIDATION |
| DAI borrow interest accrual (1 год) | Debt +$2,025 | 1.013 | 🔴 Медленная эрозия |

**Критический вывод:** При 90% LTV стандартный USDC depeg события 2023 (–8%) вызвал бы ликвидацию. Для реального деплоя рекомендуется:
- **Рабочий LTV: 82%** → HF = 1.155 → буфер 15.5%
- Автоматический deleverage начинается при HF < 1.12 (буфер 12%)

**LTV 82% P&L перерасчёт:**
```
Borrow: $41,000 DAI
Supply earn: +$1,500
Borrow cost: –$41,000 × 4.5% = –$1,845
Redeploy yield: +$41,000 × 10% = +$4,100
Gas: –$150
Net: +$3,605 = 7.21% APY (хорошо с адекватным буфером безопасности)
```

### 2.4 Auto-Deleverage Logic (Python, stdlib)

```python
class EModeLeverageController:
    """
    Мониторинг здоровья позиции + принятие решений о deleveraging.
    Read-only; write action через Gnosis Safe пропозал.
    """

    # Health factor пороги
    HF_TARGET    = 1.20   # Целевой HF при нормальной работе
    HF_WARN      = 1.12   # Алерт → notify владельца
    HF_DELEVERAGE= 1.06   # Начать частичный repay
    HF_EMERGENCY = 1.02   # Полный немедленный deleverage

    # Borrow rate порог (деплой теряет смысл)
    BORROW_RATE_WARN     = 7.0   # % APY — алерт
    BORROW_RATE_UNWIND   = 9.0   # % APY — начать ветровку
    BORROW_RATE_EMERGENCY= 12.0  # % APY — немедленно закрыть

    def evaluate(self, on_chain_data: dict) -> dict:
        hf = on_chain_data["health_factor"]
        borrow_rate = on_chain_data["dai_borrow_rate_apy"]
        spread = on_chain_data["morpho_supply_apy"] - borrow_rate

        # Приоритет 1: Угроза ликвидации
        if hf < self.HF_EMERGENCY:
            return {
                "action": "FULL_DELEVERAGE",
                "urgency": "IMMEDIATE",
                "description": "Withdraw all Morpho → repay all Aave debt → redeem collateral"
            }

        if hf < self.HF_DELEVERAGE:
            # Repay 30% долга, чтобы восстановить HF до 1.15
            repay_pct = min(0.30, (self.HF_TARGET - hf) / hf)
            return {
                "action": "PARTIAL_REPAY",
                "repay_fraction": repay_pct,
                "urgency": "HIGH",
                "description": f"Repay {repay_pct*100:.0f}% of Morpho → repay Aave debt"
            }

        # Приоритет 2: Borrow rate erosion
        if borrow_rate >= self.BORROW_RATE_EMERGENCY or spread < 1.0:
            return {
                "action": "FULL_DELEVERAGE",
                "urgency": "SCHEDULED_24H",
                "description": "Spread collapsed; uneconomical to maintain leverage"
            }

        if borrow_rate >= self.BORROW_RATE_UNWIND:
            return {
                "action": "REDUCE_POSITION_50PCT",
                "urgency": "WITHIN_48H",
            }

        # Приоритет 3: HF мягкое предупреждение
        if hf < self.HF_WARN:
            return {"action": "ALERT", "urgency": "LOW"}

        return {
            "action": "HOLD",
            "current_hf": hf,
            "current_apy": spread,
            "net_apy_est": spread + on_chain_data["usdc_supply_apy"]
        }
```

### 2.5 On-Chain Реализуемость

**Контракты (Ethereum Mainnet):**
```python
AAVE_POOL          = "0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2"
AAVE_DATA_PROVIDER = "0x7B4EB56E7CD4b454BA8ff71E4518426369a138a3"
MORPHO_BLUE        = "0xBBBBBbbBBb9cC5e90e3b3Af64bdAF62C37EEFFCb"

# --------------------------------------------------------------------------
# Полный деплой (4 tx → 1 Gnosis Safe batch)
# --------------------------------------------------------------------------

# 1. Supply USDC в Aave
aave_pool.supply(
    asset=USDC, amount=50_000e6,
    onBehalfOf=safe_address, referralCode=0
)

# 2. Включить Stablecoin E-Mode (category = 1)
aave_pool.setUserEMode(categoryId=1)

# 3. Borrow DAI (variable rate mode = 2)
aave_pool.borrow(
    asset=DAI, amount=45_000e18,
    interestRateMode=2, referralCode=0,
    onBehalfOf=safe_address
)

# 4. Supply borrowed DAI в Morpho Blue
# Market params: DAI/USDC с Chainlink оракулом
morpho_blue.supply(
    marketParams=MarketParams(
        loanToken=DAI, collateralToken=USDC,
        oracle=CHAINLINK_DAI_USDC,
        irm=MORPHO_ADAPTIVE_IRM,
        lltv=int(0.86e18)
    ),
    assets=45_000e18, shares=0,
    onBehalfOf=safe_address, data=b""
)

# --------------------------------------------------------------------------
# Мониторинг Health Factor (read-only)
# --------------------------------------------------------------------------
(totalCollateralBase,
 totalDebtBase,
 availableBorrowsBase,
 currentLiquidationThreshold,
 ltv,
 healthFactor) = aave_pool.getUserAccountData(safe_address)

hf = healthFactor / 1e18  # HF < 1.0 → ликвидация

# Borrow rate
reserve_data = aave_pool.getReserveData(DAI)
borrow_rate_apy = (reserve_data.currentVariableBorrowRate / 1e27) * 100  # в %
```

**Gnosis Safe:** все 4 операции батчуются в 1 Safe multisig TX ✓. `setUserEMode` принимает `msg.sender` = Safe ✓. Morpho принимает `onBehalfOf` = Safe ✓.

**Минимальный капитал:** $20K (gas < 0.5%). Оптимально: $30–60K. Максимум: $80K (40% T1 cap per RiskPolicy — Aave T1).

---

## 3. Стратегия S10: Pendle YT/PT Structured Note

### 3.1 Механика

Pendle V2 разделяет yield-bearing SY (Standardized Yield) токен на два:

```
SY (Standardized Yield) = underlying asset wrapper
   ├── PT (Principal Token):  право получить 1 SY при maturity
   └── YT (Yield Token):      право получить ВСЕ yield от 1 SY за период
```

**Ценообразование YT — ключевая формула:**
```
YT_price ≈ implied_APY × (days_to_maturity / 365)

Пример (sUSDe Pendle pool, 90-day maturity, implied APY = 20%):
YT_price ≈ 0.20 × (90/365) ≈ 0.0493 per 1 SY (4.93% от face value)
YT leverage ≈ 1 / 0.0493 ≈ 20.3× на yield
```

**КРИТИЧНО — как работает P&L от YT:**

YT — это **ставка на то, что realized APY > implied APY при покупке**. Это НЕ просто leveraged yield. Механика:
- $9,000 в YT at 4.93% → представляет $182,600 sUSDe face value
- Каждый день: получаешь sUSDe_daily_yield на $182,600
- При maturity: YT стоит $0 (вся yield исчерпана)
- Return = Σ(daily yields collected) – $9,000 (YT cost)

**Если realized = implied (20%):** $182,600 × 20% × 90/365 = $9,003 → P&L ≈ $0 (break-even, доходность уже в цене)
**Если realized > implied:** surplus × leverage = прибыль
**Если realized < implied:** shortfall × leverage = убыток (до –$9,000 max)

### 3.2 Portfolio Structure ($30K: 70% PT / 30% YT)

```
$30,000 total allocation:
├── $21,000 → sUSDe PT (fixed yield 10% annualized, 90-day maturity)
│    Fixed return/quarter: $21,000 × 10% × 90/365 = +$517
│    Risk: ZERO (получаешь $21,000 + $517 при maturity, без исключений)
└── $9,000 → sUSDe YT (implied APY = 20%, 20× yield leverage)
     Face value: $182,600 sUSDe
     P&L = (realized_APY – implied_APY) × $182,600 × 90/365
```

### 3.3 Три Сценария P&L

**BULL SCENARIO** (ETH funding на максимуме, sUSDe APY = 28%)
```
realized_APY = 28%, implied при покупке = 20%
Spread: +8%

PT return (90 days):    $21,000 × 10% × 90/365        = +$517
YT yield collected:     $182,600 × 28% × 90/365        = +$12,605
YT cost:                                                 –$9,000
YT P&L:                                                  +$3,605
Gas + slippage (est.):                                   –$150
──────────────────────────────────────────────────────────────
Total 90-day P&L:                                        +$3,972
Annualized P&L (×4):                                    +$15,888
Ann. APY на $30K:                                        +53%

Note: если продать YT досрочно (через 45 дней), когда APY > implied,
      YT рыночная цена уже выросла → дополнительный capital gain.
```

**NORMAL SCENARIO** (умеренный bull, sUSDe APY = 20% = implied)
```
realized_APY = 20% = implied_APY
Spread: 0%

PT return:                                               +$517
YT yield collected:     $182,600 × 20% × 90/365         = +$9,003
YT cost:                                                 –$9,000
YT P&L:                                                  +$3 (≈ break-even)
Gas + slippage:                                          –$150
──────────────────────────────────────────────────────────
Total 90-day P&L:                                        +$370
Ann. APY на $30K:                                        +4.9%

Note: весь upside приходит от PT (фиксированная доходность).
      YT в normal сценарии — пустышка относительно риска.
```

**BEAR SCENARIO** (funding отрицательный, sUSDe APY = 7%)
```
realized_APY = 7%, implied при покупке = 20%
Spread: –13%

PT return (фиксированный, не затронут):                 +$517
YT yield collected:     $182,600 × 7% × 90/365          = +$3,151
YT cost:                                                 –$9,000
YT P&L:                                                  –$5,849
Gas:                                                     –$150
──────────────────────────────────────────────────────────
Total 90-day P&L:                                        –$5,482
Ann. equiv. на $30K:                                     –73%
Maximum possible loss:  –$8,483 (YT = $0 + gas) если APY → 0%
```

**Полная P&L таблица:**

| realized APY | PT P&L | YT yield | YT cost | Gas | Total | Ann. APY |
|-------------|--------|---------|---------|-----|-------|---------|
| 35% (extreme bull) | +$517 | +$15,782 | –$9,000 | –$150 | +$7,149 | **+95%** |
| 28% (bull) | +$517 | +$12,605 | –$9,000 | –$150 | +$3,972 | **+53%** |
| 22% (mild bull) | +$517 | +$9,905 | –$9,000 | –$150 | +$1,272 | **+17%** |
| 20% (normal) | +$517 | +$9,003 | –$9,000 | –$150 | +$370 | **+5%** |
| 15% (mild bear) | +$517 | +$6,752 | –$9,000 | –$150 | –$1,881 | **–25%** |
| 7% (bear) | +$517 | +$3,151 | –$9,000 | –$150 | –$5,482 | **–73%** |
| 0% (black swan) | +$517 | $0 | –$9,000 | –$150 | –$8,633 | **–115%*** |

\* Максимальный убыток ограничен $8,633 (весь YT + gas). PT $517 гарантирован.

### 3.4 Entry Условия (строгие)

**Покупать YT только при ВСЕХ условиях:**

```python
YT_ENTRY_CONDITIONS = {
    # 1. Рынок недооценивает текущую yield (YT дёшев)
    # realized APY должен быть ВЫШЕ implied при покупке
    "yield_momentum": "susde_7day_realized_apy >= pendle_implied_apy + 3%",

    # 2. Bull-режим подтверждён
    "eth_funding_14day_avg": "> 0.005% per 8h",  # = 22%/year annualized
    "susde_tvl_usd": ">= 3_000_000_000",  # $3B minimum

    # 3. Оптимальное время до maturity
    "days_to_maturity": "45 <= days <= 120",  # слишком близко → theta decay убивает

    # 4. Достаточная ликвидность в YT pool
    "pendle_pool_liquidity_usd": ">= 50_000_000",  # $50M

    # 5. Implied APY не «перекуплен»
    "implied_vs_realized_spread": "implied <= realized * 1.20",  # не более 20% premium
}
```

### 3.5 Exit Условия

```python
YT_EXIT_CONDITIONS = {
    # Stop loss — жёсткий
    "yt_value_decline": "> 35%",       # YT потерял > 35% → немедленный sell

    # Yield режим сломан
    "susde_apy_drop": "< 12%",         # APY ниже 12% → YT leverage невыгоден

    # Take profit (досрочная фиксация)
    "realized_vs_implied_excess": "> 10%",  # realized обогнал implied на 10%+ → зафиксировать

    # Maturity approach
    "days_to_maturity": "< 14",        # Держать до maturity (продажа невыгодна из-за spread)

    # Funding flip
    "eth_funding_negative_3days": True, # Funding отрицательный 3+ дня → rotate to Aave
}
```

### 3.6 On-Chain Реализуемость (Pendle V2)

```python
PENDLE_ROUTER_V4   = "0x00000000005BBB0EF59571E58418F9a4357b68A0"
PENDLE_ORACLE      = "0x9A9Fa8338dd5E5B2188006f1Cd2Ef26d921650C2"
# Конкретный market — проверить актуальный адрес на app.pendle.finance
# SUSDE_MARKET_90D  = "0x..."  # sUSDe с nearest maturity

# --------------------------------------------------------------------------
# 1. Купить PT (fixed yield, безрисковый для данного периода)
# --------------------------------------------------------------------------
pendle_router.swapExactTokenForPt(
    receiver     = safe_address,
    market       = SUSDE_MARKET_90D,
    minPtOut     = int(21_000e18 * 0.99),  # 1% slippage tolerance
    guessPtOut   = ApproxParams(
        guessMin=int(20_500e18), guessMax=int(21_500e18),
        guessOffchain=int(21_000e18), maxIteration=256, eps=int(1e15)
    ),
    input        = TokenInput(
        tokenIn=USDC, netTokenIn=21_000e6,
        tokenMintSy=USDC, pendleSwap=ZERO_ADDRESS, swapData=b""
    ),
    limit        = LimitOrderData(limitRouter=ZERO_ADDRESS, epsSkipMarket=0, ...)
)

# --------------------------------------------------------------------------
# 2. Купить YT (leveraged yield speculation)
# --------------------------------------------------------------------------
pendle_router.swapExactTokenForYt(
    receiver     = safe_address,
    market       = SUSDE_MARKET_90D,
    minYtOut     = int(expected_yt_amount * 0.98),  # 2% slippage (YT pool thinner)
    guessYtOut   = ApproxParams(...),
    input        = TokenInput(tokenIn=USDC, netTokenIn=9_000e6, ...),
    limit        = LimitOrderData(...)
)

# --------------------------------------------------------------------------
# 3. Мониторинг implied APY через Pendle Oracle
# --------------------------------------------------------------------------
def get_implied_apy(market_address: str, twap_duration: int = 1800) -> float:
    """TWAP 30 мин для защиты от манипуляций"""
    # getPtToAssetRate возвращает discount factor
    (pt_rate, _, _) = pendle_oracle.getPtToAssetRate(market_address, twap_duration)
    # pt_rate < 1.0 → PT торгуется с дисконтом → implied yield
    remaining_days = get_days_to_maturity(market_address)
    implied_apy = ((1.0 / (pt_rate / 1e18)) - 1) * (365 / remaining_days)
    return implied_apy * 100  # в %

# --------------------------------------------------------------------------
# 4. Exit YT досрочно (если stop-loss или take-profit triggered)
# --------------------------------------------------------------------------
pendle_router.swapExactYtForToken(
    receiver    = safe_address,
    market      = SUSDE_MARKET_90D,
    exactYtIn   = yt_balance,
    minTokenOut = int(expected_usdc_out * 0.98),
    output      = TokenOutput(tokenOut=USDC, ...),
    limit       = LimitOrderData(...)
)
```

**Gnosis Safe совместимость:**
- Pendle Router принимает любой `receiver` (в т.ч. Safe) ✓
- Batch: buy PT + buy YT в одном Safe TX ✓
- Exit: автоматический мониторинг → формирует Safe пропозал ✓
- Maturity redeem: `redeemPyToToken` после истечения — одна стандартная TX ✓

**Минимальный капитал:** $10K ($7K PT + $3K YT — ниже нецелесообразно из-за gas и spread). Оптимально: $20–30K. Максимум: $40K (liquidity risk в тонком YT market).

---

## 4. Сравнительная Матрица S0–S10

| # | Стратегия | Target APY | Max DD | Leverage | Реализ. | Риск | Min Capital | Режим |
|---|-----------|-----------|--------|---------|---------|------|------------|-------|
| S0 | Aave V3 USDC Supply | 3–4% | 0.5% | 1× | 5/5 | Low | $1K | All |
| S1 | Compound V3 Comet | 3.5–4.5% | 0.5% | 1× | 5/5 | Low | $1K | All |
| S2 | Morpho Blue USDC | 4–6% | 1.0% | 1× | 4/5 | Low | $5K | All |
| S3 | Yearn V3 USDC Vault | 5–8% | 2.0% | 1–1.5× | 4/5 | Low-Med | $5K | All |
| S4 | Euler V2 USDC | 4–7% | 1.5% | 1× | 4/5 | Med | $5K | All |
| S5 | Maple Finance | 8–12% | 5.0% | 1× | 3/5 | Med-High | $25K | All |
| S6 | Curve/Convex 3pool | 8–12% | 3.0% | 1× | 3/5 | Med | $10K | All |
| S7 | Aave Recursive 1.5× | 5–7% | 3.0% | 1.5× | 4/5 | Med | $10K | All |
| S8 | Delta-Neutral sUSDe | 13–24% | 8.0% | 1× (perp hedge) | 2/5 | High | $20K | Bull |
| S9 | Aave E-Mode Loop 2× | 7–10% | 5.0% | 2× | 3/5 | Med | $20K | All |
| S10 | Pendle YT/PT Note | –23%..+67% | 30%+ | 20× (YT) | 2/5 | High | $10K | Bull |

**Легенда реализуемости (1–5):**
- **5** — Trivial: один ERC-20 call, широко документировано
- **4** — Easy: один протокол, стандартный интерфейс, zap доступен
- **3** — Medium: два протокола + мониторинг + threshold logic
- **2** — Hard: custom перп логика / Pendle V2 API + active management
- **1** — Expert: multi-hop арбитраж, MEV-sensitive, требует форк-тест

**Risk Score (composite):**
```
Risk_Score = Leverage_Factor × Protocol_Risk × Market_Regime_Dependency

S0:  1.0 × 1.0 × 1.0 =  1.0  (reference)
S1:  1.0 × 1.0 × 1.0 =  1.0
S2:  1.0 × 1.2 × 1.0 =  1.2  (curator risk)
S3:  1.3 × 1.3 × 1.1 =  1.9  (internal leverage + vault risk)
S4:  1.0 × 1.5 × 1.0 =  1.5  (newer protocol)
S5:  1.0 × 2.5 × 1.2 =  3.0  (credit risk)
S6:  1.0 × 1.8 × 1.3 =  2.3  (CRV token reward dilution)
S7:  1.5 × 1.0 × 1.2 =  1.8  (rate squeeze + liquidation)
S8:  1.0 × 3.5 × 2.5 =  8.8  (Ethena protocol + bull-only)
S9:  2.0 × 1.0 × 1.5 =  3.0  (liquidation + rate sensitivity)
S10: 20× × 2.0 × 3.0 = 120   (YT extreme leverage; NOT for main capital)
```

---

## 5. Tournament Portfolio: $100K Allocation

### 5.1 Цель Теста (30 дней)

Определить **2–3 стратегии-победителя** для реального деплоя (ADR-002 go-live). Критерии:
1. Реализованный APY ≥ 10% при max drawdown ≤ 5%
2. Полная автоматизируемость (нулевое ручное вмешательство)
3. Масштабируемость до $500K–$1M (проверить slippage в test)
4. Статистически значимый Sharpe ratio при n=30 дней

### 5.2 Распределение 9 vPortfolio

| vPortfolio | Стратегия | Аллокация | Капитал | Ключевой вопрос |
|-----------|----------|---------|--------|----------------|
| **vP0** | Aave V3 USDC (S0) | 10% | $10,000 | Baseline benchmark |
| **vP1** | Morpho Blue (S2) | 10% | $10,000 | Лучший T1 без leverage |
| **vP2** | Maple Finance (S5) | 5% | $5,000 | Институциональная yield |
| **vP3** | Curve/Convex 3pool (S6) | 5% | $5,000 | LP доходность vs риск |
| **vP4** | S9 Conservative (LTV 82%) | 15% | $15,000 | Safe leverage — базовая |
| **vP5** | S9 Aggressive (LTV 90%) | 10% | $10,000 | Max leverage, stress test |
| **vP6** | S8 Delta-Neutral full | 15% | $15,000 | Funding harvest live test |
| **vP7** | S10 Conservative (85/15 PT/YT) | 15% | $15,000 | Structured: защитный |
| **vP8** | S10 Aggressive (60/40 PT/YT) | 10% | $10,000 | Structured: agressive |
| **Reserve** | Aave USDC (dry powder) | 5% | $5,000 | Gas + opportunistic |
| **TOTAL** | | **100%** | **$100,000** | |

### 5.3 Ожидаемый P&L Range (30 дней)

Допущения: Bear = sUSDe 5%, DAI borrow 6%, funding negative. Base = sUSDe 15%, DAI borrow 4.5%, funding neutral. Bull = sUSDe 22%, DAI borrow 3.5%, funding positive.

| vP | Стратегия | Bear (30d) | Base (30d) | Bull (30d) |
|----|----------|-----------|-----------|-----------|
| vP0 | Aave V3 | +$25 | +$25 | +$28 |
| vP1 | Morpho | +$33 | +$41 | +$49 |
| vP2 | Maple | +$33 | +$41 | +$49 |
| vP3 | Curve LP | +$21 | +$37 | +$49 |
| vP4 | S9 Conservative | +$62 | +$88 | +$99 |
| vP5 | S9 Aggressive | +$49 | +$65 | +$82 |
| vP6 | S8 Delta-Neutral | +$19 | +$185 | +$296 |
| vP7 | S10 Conservative | –$457 | +$105 | +$405 |
| vP8 | S10 Aggressive | –$951 | +$49 | +$582 |
| Reserve | Aave | +$12 | +$12 | +$12 |
| **ИТОГО** | | **–$1,154** | **+$648** | **+$1,651** |
| **Ann. APY** | | **–13.8%** | **+7.8%** | **+19.8%** |

**Ключевые наблюдения:**
- Bear сценарий: S10 агрессивный уничтожает портфель (–$951 за 30 дней). vP8 — тест дисциплины стоп-лоссов.
- Base сценарий: vP4 (S9 Conservative) показывает лучший risk-adjusted результат на размер позиции.
- Bull сценарий: vP6 (S8) и vP7/vP8 (S10) доминируют, но только при bull-режиме.

### 5.4 Критерии Выбора Победителя (День 30)

```python
WINNER_CRITERIA = {
    # Обязательные (все OR для прохода)
    "realized_monthly_apy": ">= 10% annualized",
    "max_drawdown_30d": "<= 5%",
    "human_interventions": "== 0",  # Полная автоматизация

    # Желательные (для приоритизации)
    "sharpe_30d_daily": ">= 1.5",
    "slippage_at_2x_size": "<= 0.5%",  # Масштабируемость
    "correlation_with_baseline": "<= 0.3",  # Диверсификация
}

EXPECTED_WINNERS_BASE_SCENARIO = [
    "vP4",  # S9 Conservative — надёжный 7%+ при нулевом вмешательстве
    "vP6",  # S8 Delta-Neutral — 15%+ если bull подтвердится
    "vP1",  # Morpho Blue — простой baseline outperformer
]

CONDITIONAL_WINNER = "vP5"  # S9 Aggressive — если DAI borrow rate < 5%
SPECULATIVE = ["vP7", "vP8"]  # S10 — только при bull; не масштабировать без трек-рекорда
```

### 5.5 Критические Зависимости Tournament

**Проверить ДО запуска:**

1. **sUSDe APY и ETH funding regime:**
   ```bash
   python3 -c "
   import urllib.request, json
   with urllib.request.urlopen('https://yields.llama.fi/poolsEnriched?pool=susde-ethena') as r:
       data = json.loads(r.read())
   apy = data['data'][0]['apy']
   print(f'sUSDe 7d APY: {apy:.2f}%')
   print('S8/S10 go: YES' if apy >= 12 else 'S8/S10 go: NO — stay in Aave/Morpho')
   "
   ```

2. **Aave DAI borrow rate:**
   - Если DAI borrow > 6% → снизить S9 LTV до 75% или отложить
   - Проверить: Aave app → DAI → Variable borrow rate

3. **Pendle sUSDe pool liquidity:**
   - Если TVL < $50M → не запускать S10, заменить vP7 на S3 (Yearn)

4. **GMX v2 availability:**
   - Альтернативы для S8 hedge: Gains Network (gTrade), Vertex Protocol, Kwenta

**Rollout рекомендация:**
```
День 1: Запустить vP0, vP1, vP4 (проверить автоматизацию)
День 3: Добавить vP5, vP2, vP3 (расширить coverage)
День 7: Решение по S8/S10: только если sUSDe APY ≥ 12%
         → добавить vP6, vP7, vP8
День 30: Финальный аудит → отбор 2–3 победителей → Owner manual review (ADR-002)
```

---

## Приложение А: APY Диапазоны По Рыночным Режимам

```
                Pessimistic    Base      Optimistic
S9 (E-Mode):       5.9%       7.6%        9.5%
S8 (sUSDe):        1.0%      15.0%       24.0%
S10 (YT/PT):     –73.0%       5.0%       53.0%

Портфель mix:      –3.2%       9.1%       18.2%
```

## Приложение Б: Реализуемость в SPA Framework

| Компонент | S8 | S9 | S10 |
|-----------|----|----|-----|
| Python stdlib only | ✅ (urllib для мониторинга) | ✅ | ✅ |
| Gnosis Safe batch | ✅ 4 actions | ✅ 4 actions | ✅ 2 actions |
| Read-only monitoring | ✅ GMX + DeFiLlama | ✅ Aave getUserAccountData | ✅ Pendle Oracle |
| Auto-deleverage logic | ✅ threshold-based | ✅ HF-based | ✅ YT value-based |
| Kill-switch compatible | ✅ | ✅ | ✅ |
| LLM_FORBIDDEN compliant | ✅ все решения детерминированы | ✅ | ✅ |
| RiskPolicy v1.0 compliance | ⚠️ sUSDe = T2, cap 20% | ✅ T1 Aave, cap 40% | ⚠️ новый тип актива |

**Для S10 (Pendle):** потребуется ADR для классификации PT/YT как нового типа актива. Предлагается: PT = T2 (фиксированный yield), YT = T3 (спекулятивный), с отдельным cap 10% для T3.

---

*Документ подготовлен: 2026-06-12 | SPA Quant Module v1.0*
*Следующий review: после 30-дневного tournament (~2026-07-12)*
*Approval required: Owner manual review перед любым реальным деплоем (ADR-002)*
*Все стратегии — paper trading только. Реальный деплой после трек-рекорда и Owner sign-off.*
