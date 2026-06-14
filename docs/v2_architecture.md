# SPA v2.0 Architecture: Real Capital Deployment

**Version:** 2.0-draft  
**Status:** Design — Not Yet Active  
**Target Activation:** 2026-07-15 (after paper trading phase ends)  
**Owner:** Yurii Kulieshov

---

## 1. Overview

SPA v2.0 transitions the Smart Passive Aggregator from paper trading simulation to real DeFi yield farming on Ethereum mainnet. The core agent logic, risk policy, and decision framework carry over unchanged from v1.x — what changes is the execution layer.

### Capital Deployment Plan

| Phase | Capital | Condition |
|---|---|---|
| Seed | $1,000 | Aave V3 only, first 30 days live |
| Phase 1 | $2,000 | PnL > 0 AND no issues after seed phase |
| Phase 2 | $5,000 | Sharpe > 1.0 AND drawdown < 2% for 30 days |
| Full Allocation | Per strategy passport | All phase criteria met |

### Protocols in Scope (same 7 as paper trading)

1. Aave V3
2. Compound V3
3. Morpho
4. Yearn V3 (yvUSDC)
5. Maple Finance
6. Euler
7. Spark Protocol

### Chain

- **Primary:** Ethereum mainnet
- **Future consideration:** Arbitrum, Base (L2s) after mainnet stability is proven — requires separate ADR

---

## 2. Technical Stack for Real Execution

### 2.1 Core Libraries

**`web3.py`** — Ethereum RPC interface.  
All blockchain reads (balances, positions, APY) and transaction construction go through web3.py. Connects to a mainnet RPC endpoint (Infura or Alchemy — credentials in GitHub Secrets, never hardcoded).

```python
from web3 import Web3
w3 = Web3(Web3.HTTPProvider(os.environ["ETH_RPC_URL"]))
```

**Direct Contract ABI Calls** — For protocols without maintained Python SDKs, supply/withdraw interactions are executed via ABI-encoded calls to protocol contracts. ABIs are vendored into `spa_core/execution/abis/`.

Aave V3 key contract addresses (mainnet):
- Pool: `0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2`
- PoolAddressesProvider: `0x2f39d218133AFaB8F2B819B1066c7E434Ad94E9E`

### 2.2 Wallet Infrastructure

**Gnosis Safe (multisig)** — Primary vault for all funds. Requires M-of-N owner approval for transactions above $500. Hot wallet is added as a delegate with limited permissions. Safe address stored in `SAFE_ADDRESS` GitHub Secret.

**Hot Wallet (MetaMask)** — Funded with ETH for gas only (no USDC). Used for small transactions (≤ $500) and as a Safe delegate. Address stored in `WALLET_ADDRESS` GitHub Secret. Private key managed via hardware wallet or environment secret — **never committed to git**.

### 2.3 Transaction Simulation

**Tenderly** — Every transaction is dry-run through Tenderly's simulation API before submission. A failed simulation hard-blocks execution. Free tier: 100 simulations/month. Project configured at `spa-v2` under Tenderly account.

```python
# Example simulation call structure
POST https://api.tenderly.co/api/v1/account/{account}/project/{project}/simulate
{
  "network_id": "1",
  "from": "<hot_wallet>",
  "to": "<protocol_contract>",
  "input": "<encoded_calldata>",
  "gas": 500000,
  "save": false
}
```

### 2.4 MEV Protection

**Flashbots** — Transactions exceeding $1,000 in value are submitted via the Flashbots RPC endpoint (`https://rpc.flashbots.net`) instead of the public mempool. This prevents sandwich attacks and front-running on larger deposits/withdrawals.

---

## 3. Safety Architecture (CRITICAL)

Every real-capital transaction must traverse this pipeline in order. Any BLOCKING failure halts the transaction immediately — no exceptions, no overrides from the agent layer.

```
┌─────────────────────────────────────────────┐
│          User / Agent Decision Request       │
└───────────────────┬─────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│  [1] RiskPolicy v1.0 check (BLOCKING)       │
│  Same RiskPolicy used in paper trading.      │
│  Checks: concentration, protocol whitelist,  │
│  drawdown headroom, position size limits.    │
└───────────────────┬─────────────────────────┘
                    │ PASS
                    ▼
┌─────────────────────────────────────────────┐
│  [2] Kill Switch Check (BLOCKING)           │
│  Portfolio drawdown < 5% (hard stop).        │
│  If triggered: no new transactions allowed.  │
└───────────────────┬─────────────────────────┘
                    │ PASS
                    ▼
┌─────────────────────────────────────────────┐
│  [3] Rate Limit Check (BLOCKING)            │
│  Max 3 transactions per hour.                │
│  Prevents runaway agent loops.               │
└───────────────────┬─────────────────────────┘
                    │ PASS
                    ▼
┌─────────────────────────────────────────────┐
│  [4] Tenderly Simulation (BLOCKING)         │
│  Dry-run must succeed on mainnet fork.       │
│  Failed simulation = transaction rejected.   │
└───────────────────┬─────────────────────────┘
                    │ PASS
                    ▼
┌─────────────────────────────────────────────┐
│  [5] Gas Estimation Check (BLOCKING)        │
│  Gas cost must be < 2% of transaction value. │
│  Prevents uneconomical micro-transactions.   │
└───────────────────┬─────────────────────────┘
                    │ PASS
                    ▼
┌─────────────────────────────────────────────┐
│  [6] Amount Routing                         │
│  amount > $500 → Gnosis Safe multisig       │
│  amount ≤ $500 → auto-execute via hot wallet │
└───────┬───────────────────────┬─────────────┘
        │ Multisig               │ Auto-execute
        ▼                        ▼
┌──────────────────┐  ┌──────────────────────┐
│ Queue Safe tx.   │  │ Submit via web3.py.   │
│ Wait for owner   │  │ Flashbots if > $1K.  │
│ approval.        │  └──────────┬───────────┘
└──────┬───────────┘             │
       │ Approved                │
       ▼                        ▼
┌─────────────────────────────────────────────┐
│  [7] Post-Execution Verification            │
│  Read on-chain state after tx confirms.      │
│  Verify balance / position matches expected. │
│  Alert if mismatch detected.                 │
└───────────────────┬─────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│  [8] DecisionLogger Entry                   │
│  Same logger as paper trading.               │
│  Records: tx hash, protocol, amount, gas,   │
│  safety check results, on-chain confirmation.│
└─────────────────────────────────────────────┘
```

### 3.1 Implementation Mapping

| Safety Step | Module | Class/Function |
|---|---|---|
| RiskPolicy check | `spa_core/risk/policy.py` | `RiskPolicy.check_new_position()` |
| Kill switch | `spa_core/execution/safety_checks.py` | `PreExecutionSafety.check_not_in_kill_switch()` |
| Rate limit | `spa_core/execution/safety_checks.py` | `PreExecutionSafety.check_rate_limit()` |
| Tenderly simulation | `spa_core/execution/wallet.py` | `SPAWallet.simulate_transaction()` |
| Gas check | `spa_core/execution/safety_checks.py` | `PreExecutionSafety.check_gas_reasonable()` |
| Multisig routing | `spa_core/execution/safety_checks.py` | `PreExecutionSafety.check_amount_requires_multisig()` |
| Post-execution | `spa_core/execution/position_monitor.py` | `PositionMonitor.verify_post_execution()` |
| Decision log | `spa_core/agents/decision_logger.py` | `DecisionLogger.log()` |

---

## 4. Kill Switch Architecture

### 4.1 Software Kill Switch

The software kill switch is embedded in `RiskPolicy`. When triggered, it blocks all new transaction requests at safety check step [1].

**Trigger condition:** Portfolio drawdown ≥ 5% (configurable via `RiskConfig.max_drawdown_stop`)

**Trigger mechanism:**
```python
# In RiskPolicy.check_new_position():
if portfolio.total_drawdown_pct >= self.config.max_drawdown_stop:
    raise KillSwitchTriggered(
        f"Drawdown {portfolio.total_drawdown_pct:.1%} ≥ stop threshold "
        f"{self.config.max_drawdown_stop:.1%}. All new transactions blocked."
    )
```

**Reset procedure:** Owner must manually set `RiskConfig.max_drawdown_stop` back to 0.05 after reviewing positions. No automatic reset.

### 4.2 Hardware Kill Switch (Gnosis Safe)

The Safe owner can revoke the hot wallet's delegate permissions at any time via the Gnosis Safe UI or CLI. Once revoked, the hot wallet cannot submit transactions on behalf of the Safe — all auto-execute paths are immediately disabled.

**Revocation steps:** See `docs/emergency.md` § Gnosis Safe Emergency.

### 4.3 Emergency Fund Recovery

If both software and hardware kill switches have been engaged and the SPA system is fully offline, funds can be recovered directly through protocol UIs:
- Aave V3: https://app.aave.com (connect Safe wallet)
- Compound: https://app.compound.finance
- Yearn: https://yearn.fi

All recovery steps are documented in `docs/emergency.md`.

---

## 5. Migration Plan: Paper Trading → Real Capital

### Phase 0 — Activation Gate (before any real capital)

All items in `docs/v2_activation_checklist.md` must be completed and verified. Go-live readiness check must return `READY` or `ALMOST_READY`.

### Phase 1 — Seed Deployment (Week 1–2)

- Deploy **$1,000 USDC** to **Aave V3 only**
- Single protocol, single asset, safest protocol in the whitelist
- Monitor on-chain every 15 minutes via `PositionMonitor`
- No agent-initiated rebalancing during this phase — positions are static
- Success criteria: 14 days elapsed, position intact, PnL ≥ 0, no anomalies

### Phase 2 — Add Compound (Weeks 3–4)

- If Phase 1 criteria met: add **$1,000 USDC** to **Compound V3**
- Total deployed: $2,000 across 2 protocols
- Enable agent-initiated rebalancing (within the 2-protocol subset only)
- Success criteria: 14 more days, combined PnL > 0, Sharpe trending > 0.5

### Phase 3 — Full Paper Trading Ratio (Month 2)

- Expand to all 3 initial protocols (Aave, Compound, Morpho) at paper trading allocation ratios
- Total deployed: $3,000–$5,000
- All 7 protocols enabled for consideration (allocation determined by strategy agent)
- Full safety pipeline active on every transaction

### Phase 4 — Scale (Month 3+)

Scale allocation only when ALL of the following are met for 30 consecutive days:
- Sharpe ratio > 1.0
- Max drawdown < 2%
- No critical alerts
- PnL positive

Scale increments: $5K → $10K → $25K → full target allocation. Each step requires owner review and explicit approval.

---

## 6. Monitoring

### 6.1 On-Chain Position Monitoring

| Metric | Paper Trading | v2.0 Real |
|---|---|---|
| Poll interval | 4 hours | **15 minutes** |
| Data source | Simulated APY feed | **On-chain via web3.py** |
| Position verification | DB record | **Etherscan + contract read** |

`PositionMonitor.get_positions()` reads directly from protocol contracts every 15 minutes. Any deviation from expected state triggers an alert.

### 6.2 Telegram Alerts

Alerts sent for:
- Any transaction submitted (with tx hash)
- Any position change > 5% of deployed capital
- Gas price spike > 50 gwei (delay non-urgent transactions)
- APY deviation > 20% from 7-day moving average
- Kill switch triggered
- Post-execution verification failure

Alert format:
```
🔔 SPA ALERT [2026-07-20 14:32 UTC]
Protocol: Aave V3
Event: Supply executed
Amount: $1,000.00 USDC
Tx: 0xabc...def
Gas: $4.20 (0.42% of trade)
New balance: $2,000.00 USDC
```

### 6.3 Weekly Investor Report

Same PDF generator as paper trading (`spa_core/reports/`), but populated with real PnL figures sourced from on-chain state. Report includes:
- Real vs. paper trading performance comparison (for the first 90 days)
- Gas costs as a drag on returns
- Safety events log (any kill switch triggers, failed simulations, multisig approvals)

---

## 7. Security Considerations

### 7.1 Key Management

| Secret | Storage | Never in |
|---|---|---|
| ETH RPC URL | GitHub Secret: `ETH_RPC_URL` | Code, logs, docs |
| Hot wallet private key | Hardware wallet OR GitHub Secret: `HOT_WALLET_KEY` | Git history |
| Safe address | GitHub Secret: `SAFE_ADDRESS` | (also safe to put in config) |
| Anthropic API key | GitHub Secret: `ANTHROPIC_API_KEY` | Code |

**Pre-commit hook:** `.git/hooks/pre-commit` scans for private key patterns. See `scripts/install_hooks.sh`.

### 7.2 Blast Radius Limits

- Hot wallet holds **ETH for gas only** — max $50 ETH value at any time
- Hot wallet cannot initiate Safe transactions unilaterally for amounts > $500
- All USDC capital lives in the Gnosis Safe
- GitHub Actions runner has no access to Safe — it can only queue transactions; the Safe owner signs them

### 7.3 Audit Trail

Every transaction, simulation, safety check result, and post-execution verification is written to the `DecisionLogger` (same as paper trading). The decision log is append-only and written to `data/decision_log.json` before the transaction is submitted.

---

## 8. Related Documents

- `docs/emergency.md` — Emergency runbook and kill switch procedures
- `docs/v2_activation_checklist.md` — Pre-deployment checklist
- `spa_core/execution/wallet.py` — Wallet interface (scaffold, not yet active)
- `spa_core/execution/safety_checks.py` — Pre-execution safety pipeline
- `spa_core/golive/checklist.py` — Automated go-live readiness checks
- `SPA/01_Docs/Risk_Policy_v0.3.md` — RiskPolicy documentation
