# SPA v2.0 Activation Checklist

**Target Date:** 2026-07-15  
**Owner:** Yurii Kulieshov  
**Status:** IN PROGRESS — paper trading phase

> Complete every item on this checklist before deploying real capital.
> Mark each item as done by replacing `[ ]` with `[x]`.
> The GoLive readiness check must return `READY` or `ALMOST_READY` before proceeding to Step 10.

---

## Section A — Paper Trading Completion

- [ ] Paper trading completed ≥ 50 days (target: 2026-07-09)
- [ ] GoLive readiness check verdict = `READY` or `ALMOST_READY`
- [ ] Total PnL from paper trading is positive (run `python -m spa_core.golive.checklist`)
- [ ] No CRITICAL alerts in the last 7 days of paper trading
- [ ] Max drawdown during paper trading was < 3%
- [ ] Strategy Sharpe ratio ≥ 1.0 (from backtest_results.json)

---

## Section B — Wallet Infrastructure

- [ ] **Gnosis Safe wallet created**
  - Go to https://app.safe.global → Create new Safe
  - Set threshold: 1-of-1 (single owner for initial deployment; increase later)
  - Note your Safe address: `0x_____________________________`
  - Store in GitHub Secret: `SAFE_ADDRESS`

- [ ] **Safe tested with a $10 test transaction**
  - Send $10 USDC from Safe to your personal wallet and back
  - Verify on Etherscan that both transactions confirmed

- [ ] **Hot wallet created (MetaMask)**
  - Create a fresh wallet — do NOT reuse a personal wallet
  - Fund with **ETH only** (no USDC) — enough for ~20 transactions (~0.05 ETH)
  - USDC must never sit in the hot wallet; it lives in the Safe
  - Note hot wallet address: `0x_____________________________`
  - Store in GitHub Secret: `WALLET_ADDRESS`

- [ ] **Hot wallet added as Safe delegate**
  - Safe UI → Settings → Delegates → Add Delegate → paste hot wallet address
  - Optionally: use Zodiac Roles module for granular permission control

- [ ] **Private key secured**
  - Hardware wallet (Ledger/Trezor) recommended for the Safe owner key
  - Hot wallet private key stored ONLY in GitHub Secret `HOT_WALLET_KEY`
  - Verified with `git log --all --full-history -- "*.env"` that no key is in git history

---

## Section C — Development Infrastructure

- [ ] **Tenderly account created**
  - Sign up at https://dashboard.tenderly.co
  - Create project: `spa-v2`
  - Generate API key → store in GitHub Secret: `TENDERLY_API_KEY`
  - Add `TENDERLY_ACCOUNT` and `TENDERLY_PROJECT` to GitHub Secrets

- [ ] **Tenderly simulation tested manually**
  - Use the Tenderly dashboard to simulate an Aave V3 `supply(USDC, 100)` call
  - Verify the simulation succeeds and shows expected state change

- [ ] **`ANTHROPIC_API_KEY` confirmed in GitHub Secrets**
  - Verify the key has sufficient quota for the agent's expected call volume
  - Test: `curl -H "x-api-key: $ANTHROPIC_API_KEY" https://api.anthropic.com/v1/models`

- [ ] **Ethereum mainnet RPC configured**
  - Create account at Infura (https://infura.io) OR Alchemy (https://alchemy.com)
  - Store RPC URL in GitHub Secret: `ETH_RPC_URL`
  - Test connectivity:
    ```python
    from web3 import Web3
    w3 = Web3(Web3.HTTPProvider(os.environ["ETH_RPC_URL"]))
    assert w3.is_connected(), "RPC not connected"
    print(f"Block: {w3.eth.block_number}")
    ```

- [ ] **`web3.py` installed and importable**
  - `pip install web3`
  - Test: `python -c "from web3 import Web3; print('OK')`

---

## Section D — Execution Layer Validation

- [ ] **`SPAWallet` simulation mode passes all basic checks**
  ```python
  from spa_core.execution.wallet import SPAWallet
  w = SPAWallet(mode="simulation")
  print(w.get_balance())
  print(w.estimate_gas("aave-v3", "supply", 1000.0))
  print(w.simulate_transaction("aave-v3", "supply", 1000.0))
  # SPAWallet(mode="live") must raise NotImplementedError
  ```

- [ ] **`PreExecutionSafety` pipeline runs without errors**
  ```python
  from spa_core.execution.safety_checks import PreExecutionSafety
  safety = PreExecutionSafety()
  result = safety.run_all(
      protocol="aave-v3",
      action="supply",
      amount_usd=1000.0,
      portfolio_state={"total_drawdown_pct": 0.01},
  )
  print(result.all_passed, result.requires_multisig, result.blocking_reasons)
  ```

- [ ] **`PositionMonitor` health check passes**
  ```python
  from spa_core.execution.position_monitor import PositionMonitor
  m = PositionMonitor(data_dir="data")
  print(m.health_check())
  print(m.get_positions())
  print(m.detect_anomalies())
  ```

- [ ] **GoLive checklist criterion 9 (Wallet Ready) reviewed**
  - This criterion is always `PENDING` — it is a manual setup task
  - Manually confirm all wallet items in Section B above are complete

---

## Section E — First Real Transaction

- [ ] **Test transaction: $100 → Aave V3 supply**
  - Manually send $100 USDC from Safe → Aave V3 supply (via Aave UI, not SPA agent)
  - Verify on Etherscan: supply transaction confirmed
  - Verify on Aave UI: aUSDC balance shows $100
  - Note tx hash: `0x_____________________________`

- [ ] **Test withdrawal: $100 ← Aave V3 withdraw**
  - Withdraw the $100 USDC back to Safe
  - Verify USDC returned to Safe on Etherscan
  - This confirms the full supply/withdraw lifecycle works with your wallet

---

## Section F — Gradual Capital Ramp

Complete each step and wait at least 14 days before proceeding to the next.

- [ ] **Week 1–2: $1,000 → Aave V3 (single protocol seed)**
  - Only Aave V3, no agent-initiated rebalancing
  - Monitor: check positions daily, review Telegram alerts
  - Success gate: 14 days elapsed, PnL ≥ 0, no anomalies

- [ ] **Week 3–4: Add $1,000 → Compound V3**
  - Enable 2-protocol agent rebalancing (Aave + Compound only)
  - Monitor as above
  - Success gate: 14 more days, combined PnL > 0, Sharpe > 0.5

- [ ] **Month 2: Full protocol set at paper trading ratios**
  - Expand to all 3 initial protocols (Aave, Compound, Morpho)
  - Total deployed: $3,000–$5,000
  - All 7 protocols available for strategy agent consideration
  - Full safety pipeline active on every transaction

- [ ] **Scale gate check (Month 3+): Only scale when ALL criteria met for 30 days**
  - Sharpe ratio > 1.0
  - Max drawdown < 2%
  - No critical alerts
  - PnL positive
  - Owner explicitly approves each scale step

---

## Quick Reference: GitHub Secrets Required

| Secret Name | What It Is | Where to Get It |
|---|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key | console.anthropic.com |
| `ETH_RPC_URL` | Ethereum mainnet RPC endpoint | Infura or Alchemy |
| `WALLET_ADDRESS` | Hot wallet address (MetaMask) | MetaMask |
| `HOT_WALLET_KEY` | Hot wallet private key | MetaMask (export) — HANDLE WITH CARE |
| `SAFE_ADDRESS` | Gnosis Safe address | app.safe.global |
| `TENDERLY_API_KEY` | Tenderly API key | dashboard.tenderly.co |
| `TENDERLY_ACCOUNT` | Tenderly account slug | Tenderly dashboard |
| `TENDERLY_PROJECT` | Tenderly project slug | `spa-v2` |

**Reminder:** GitHub Actions secrets are encrypted and not visible in logs. Never print or log secret values in code.
