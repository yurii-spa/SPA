# ADR-002: Pendle PT Integration

| Field       | Value                                    |
|-------------|------------------------------------------|
| **Status**  | PROPOSED — paper test only; not live     |
| **Date**    | 2026-05-21                               |
| **Author**  | SPA Engineering                          |
| **Relates** | ADR-001 (Risk Policy), README §ADR-009   |

---

## Context

### The Gap

SPA's target APY is **7.3%** on $100K (per README ADR-009). Current paper trading achieves approximately **4.2% APY** because the portfolio only uses vanilla variable-rate lending pools (Aave V3, Compound V3, Morpho, Yearn, Maple, Euler). The gap is ~3.1%.

### Root Cause

The Tier 2 whitelist includes `T2-02: Pendle, Ethereum/Arbitrum, PT-stablecoin`, but this protocol has had no implementation. Pendle PT offers **fixed 8–12% APY** on USDC-equivalent assets with predictable, locked returns — the highest-quality fixed-rate instrument available in DeFi at our risk tier.

### What Pendle PT Is

Pendle Finance splits yield-bearing tokens into two components:

- **PT (Principal Token)** — trades at a discount to par; redeems for $1.00 at maturity → implied fixed APY locked at entry
- **YT (Yield Token)** — receives all variable yield until maturity → high variance, speculative

SPA uses **PT only**. YT is excluded from the mandate due to variable/leveraged yield exposure.

**Example**: PT-USDC-30Nov2026 trades at $0.935 today → redeems $1.00 at maturity = ~7.0% APY locked in. Economically equivalent to a DeFi T-bill.

---

## Decision

Add Pendle PT (Principal Tokens) to the SPA Tier 2 allocation, subject to the following constraints:

### Inclusion Criteria (`pendle_fetcher.py`)

| Criterion          | Threshold                            | Rationale                              |
|--------------------|--------------------------------------|----------------------------------------|
| Underlying asset   | USDC, USDT, sUSDe, USDe, DAI, FRAX  | Stable-only; no volatile collateral    |
| Minimum APY        | ≥ 6%                                 | Must clear T1 baseline + 2% premium   |
| Minimum TVL        | ≥ $5M                                | Liquidity floor for exit               |
| Maximum maturity   | ≤ 180 days                           | No long-dated illiquid positions       |
| Minimum maturity   | ≥ 14 days                            | Avoid illiquidity at expiry            |
| Chains             | Arbitrum, Ethereum only              | Audited deployments, deep liquidity    |

### Allocation Logic (`pendle_strategy.py`)

```
premium = pendle_apy - t1_baseline_apy
if premium < 2%: allocate $0 (not worth T2 risk)
else: allocation = capital × min(premium / 4%, 20%)
```

This scales exposure proportionally to the yield premium over the T1 baseline:
- 6% APY (2% premium) → 10% of capital ($10K)
- 7% APY (3% premium) → 15% of capital ($15K)
- 8%+ APY (4%+ premium) → 20% of capital ($20K, T2 cap)

### Position Characteristics

Pendle PT positions are modelled differently from variable-rate lending:
- APY is **fixed at entry** — no daily fluctuation
- Accrual is **linear** (simple interest)
- Position is logically **locked until maturity** — early exit requires selling PT at market price (potential slippage)

---

## Expected Impact

| Metric                          | Current | Post-Pendle (est.) |
|---------------------------------|---------|---------------------|
| Portfolio APY                   | ~4.2%   | ~5.7–6.5%           |
| APY improvement (weighted)      | —       | +1.5–2.5%           |
| Remaining gap to 7.3% target    | ~3.1%   | ~0.8–1.6%           |
| T2 allocation used              | ~15%    | ~25–30%             |

Note: further gap closure requires either higher-APY T2 positions or additional whitelisted protocols (separate ADR required).

---

## Risks

### Liquidity Risk
PT positions are less liquid than Aave/Compound deposits. Exit before maturity requires selling PT on Pendle's AMM, which may incur slippage — especially near maturity when liquidity thins. **Mitigation**: 14-day minimum maturity filter; TVL ≥ $5M floor.

### Smart Contract Risk
Pendle V2 has been audited by **ABDK** and **Dedaub** (reports public on Pendle docs). Protocol is live since 2023, $500M+ TVL at peak. **Mitigation**: T2 allocation cap limits exposure.

### APY Compression Risk
If Pendle PT APY compresses below threshold (e.g. due to increased demand), the fetcher returns no eligible pools and no new positions are opened. Existing positions retain the fixed APY locked at entry — this is not a risk for open positions, only for new entries.

### Maturity Cliff Risk
At maturity, PT redeems at $1.00. If the underlying pool has liquidity issues at that moment, redemption may be delayed. **Mitigation**: 14-day minimum maturity filter ensures we exit the liquidity risk zone before it becomes critical.

### Oracle/API Risk
Data sourced from DeFiLlama `/pools` API. If API is unavailable, `PendleFetcher` returns `[]` silently and no new positions are opened. Existing positions are unaffected (APY fixed at entry).

---

## Rollback Plan

1. Set `PENDLE_MIN_APY = 999.0` in `pendle_fetcher.py` → no new positions opened
2. Existing PT positions continue to accrue at fixed APY until maturity
3. If urgent exit needed: sell PT back to Pendle AMM (accept slippage vs. maturity)
4. Maximum loss scenario: T2 cap (20% = $20K) × slippage (est. 1–3% at panic exit) = ~$200–600

---

## Paper Test Plan

Before any live allocation:

1. Run Pendle PT alongside existing positions in paper trading for **4 weeks**
2. Monitor: pool APY stability, TVL changes, maturity date parsing accuracy
3. Track weighted portfolio APY weekly vs. 7.3% target
4. If paper APY improves to ≥ 6.0% sustained over 4 weeks → escalate for owner approval
5. Owner approval required (separate sign-off) before any real capital allocated

**Implementation status**: `pendle_fetcher.py`, `pendle_strategy.py` deployed. Engine integration active in `auto_allocate()`. Export pipeline updated in `export_data.py`.

---

## Alternatives Considered

| Alternative                     | Why Rejected                                          |
|---------------------------------|-------------------------------------------------------|
| Pendle YT (yield tokens)        | Variable, leveraged exposure — violates stable mandate |
| Longer-dated PT (> 180 days)    | Liquidity risk too high for SPA's 60–90d position horizon |
| Other fixed-rate DeFi (e.g. Notional) | Lower TVL, less auditing history vs. Pendle V2 |
| Increase T1 allocation only     | T1 APY ~3–5% — insufficient to close 3.1% gap alone  |
