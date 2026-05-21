# SPA Emergency Runbook

**Version:** 1.0  
**Last updated:** 2026-05-21  
**Owner:** Yurii Kulieshov  
**Status:** Active from v2.0 go-live (2026-07-15)

> **This document describes how to halt SPA and recover capital in an emergency.**
> Read it before going live. Practice the steps with a test amount first.

---

## Table of Contents

1. [When to Use This Runbook](#1-when-to-use-this-runbook)
2. [Software Kill Switch](#2-software-kill-switch)
3. [Manual Emergency Exit (Protocol UIs)](#3-manual-emergency-exit-protocol-uis)
4. [Gnosis Safe Emergency: Revoke Hot Wallet](#4-gnosis-safe-emergency-revoke-hot-wallet)
5. [Contact and Support Channels](#5-contact-and-support-channels)
6. [Post-Mortem Template](#6-post-mortem-template)

---

## 1. When to Use This Runbook

Trigger an emergency response if ANY of the following occur:

| Situation | Severity | Action |
|---|---|---|
| SPA agent is making unexpected transactions | HIGH | § 2 immediately |
| Portfolio drawdown ≥ 5% in a short time | HIGH | § 2, then § 3 |
| Suspected private key compromise | CRITICAL | § 4 immediately, then § 3 |
| Protocol hack or exploit announced | HIGH | § 3 for affected protocol |
| GitHub Actions runner compromised | CRITICAL | § 4 immediately |
| APY drops to 0 unexpectedly | MEDIUM | § 3 for affected protocol |
| Gnosis Safe shows unauthorized pending transactions | CRITICAL | § 4, reject the transaction |

---

## 2. Software Kill Switch

The software kill switch is the fastest way to stop the SPA agent from submitting new transactions. It does NOT withdraw existing positions — it only prevents new ones.

### 2.1 Automatic Trigger

The kill switch fires automatically when portfolio drawdown reaches 5% (`RiskConfig.max_drawdown_stop = 0.05`). When triggered:
- `PreExecutionSafety.check_not_in_kill_switch()` returns a blocking failure
- All transaction attempts are rejected with a logged error
- A Telegram alert is sent (if configured)

### 2.2 Manual Trigger (Fastest — In-Process)

If you have a Python console or can modify a running process:

```python
from spa_core.execution.safety_checks import PreExecutionSafety
PreExecutionSafety.activate_kill_switch(reason="Manual emergency stop by owner")
```

This takes effect immediately within the running process. Does not persist across restarts.

### 2.3 Manual Trigger (Persistent — Recommended)

**Option A: Edit RiskConfig and redeploy**

1. Open `spa_core/risk/policy.py` (or wherever `RiskConfig` is defined)
2. Set `max_drawdown_stop = 0.0` — this makes ANY drawdown trigger the kill switch
3. Commit and push to trigger a GitHub Actions redeploy
4. Verify the new version is running (check logs or the dashboard)

```python
# In RiskConfig:
max_drawdown_stop: float = 0.0  # Emergency: block all transactions
```

**Option B: Cancel the GitHub Actions workflow**

1. Go to your GitHub repository → Actions tab
2. Find the currently running `spa-run` workflow
3. Click **Cancel workflow**
4. This immediately stops the agent run

### 2.4 Resetting the Kill Switch

ONLY reset after:
- Reviewing all positions manually
- Understanding what triggered the kill switch
- Being confident the situation is resolved

```python
# Reset: set max_drawdown_stop back to 0.05 (or appropriate value)
# Then redeploy / restart the agent
PreExecutionSafety.deactivate_kill_switch(reason="Root cause resolved: <describe>")
```

---

## 3. Manual Emergency Exit (Protocol UIs)

Use this to withdraw capital directly from protocol front-ends, bypassing SPA entirely. You will need access to your Gnosis Safe wallet.

### 3.1 Before You Start

- Have your hardware wallet (Ledger/Trezor) or MetaMask connected to the Safe
- Ensure you have ETH in your wallet for gas (withdrawals cost $10–$50 in gas)
- Note down your current positions from data/status.json or the SPA dashboard

### 3.2 Aave V3

1. Go to **https://app.aave.com**
2. Connect wallet → select **Gnosis Safe** → enter your Safe address
3. Click **Dashboard** to see supplied assets
4. Click the protocol you want to withdraw from
5. Click **Withdraw**
6. Enter amount (use MAX to withdraw everything)
7. Review and confirm via your Safe (requires multisig approval if M > 1)
8. Wait for transaction to confirm on Etherscan

### 3.3 Compound V3

1. Go to **https://app.compound.finance**
2. Connect your Safe wallet
3. Select the market you supplied to (e.g., USDC on Ethereum)
4. Click **Withdraw**
5. Enter amount and confirm

### 3.4 Morpho

1. Go to **https://app.morpho.org**
2. Connect Safe wallet
3. Navigate to your supplied position
4. Click **Withdraw** → MAX → Confirm

### 3.5 Yearn V3 (yvUSDC)

1. Go to **https://yearn.fi/vaults**
2. Connect Safe wallet
3. Find yvUSDC vault → click **Withdraw**
4. Select amount and confirm

### 3.6 Maple Finance

1. Go to **https://app.mapledao.io**
2. Note: Maple may have a withdrawal queue. Initiating withdrawal now starts a cooldown period (typically 10 days for some pools)
3. Connect Safe wallet → navigate to your position → click **Redeem**
4. After the cooldown, complete the withdrawal

### 3.7 Euler

1. Go to **https://app.euler.finance**
2. Connect Safe wallet → find your supply position
3. Click **Withdraw** → enter amount → confirm

### 3.8 Spark Protocol

1. Go to **https://app.spark.fi**
2. Connect Safe wallet
3. Click **Dashboard** → Withdraw → MAX → Confirm

### 3.9 After All Withdrawals

- Verify USDC balance returned to Safe on Etherscan
- Update `data/status.json` manually or wait for next agent run to refresh
- Document the emergency in the post-mortem template (§ 6)

---

## 4. Gnosis Safe Emergency: Revoke Hot Wallet Permissions

Use this if you suspect the hot wallet private key has been compromised, or if you want to fully disable the SPA agent's ability to auto-execute transactions.

### 4.1 What Revoking Does

- Removes the hot wallet address from the Safe's delegate list
- After revocation, the hot wallet CANNOT submit transactions to the Safe
- Existing funds in protocols remain untouched — only new transactions are blocked
- All auto-execute paths (amounts ≤ $500) are immediately disabled

### 4.2 Steps to Revoke

1. Go to **https://app.safe.global**
2. Connect your Safe owner wallet (hardware wallet recommended)
3. Open your Safe → **Settings** → **Modules** (or **Delegates** depending on setup)
4. Find the hot wallet address (stored in `WALLET_ADDRESS` GitHub Secret)
5. Click **Remove** or **Revoke**
6. Confirm the transaction with your hardware wallet
7. Wait for confirmation on Etherscan

### 4.3 If You Used a Safe Module for Delegation

If SPA uses a Safe Module (e.g., Zodiac Roles), you can disable the entire module:

1. Safe UI → Settings → Modules
2. Find the SPA module
3. Click **Disable Module** → confirm
4. This instantly removes all programmatic access

### 4.4 After Revoking

- The hot wallet can no longer interact with the Safe
- To restore access: re-add the hot wallet as a delegate (Safe Settings → Delegates → Add)
- Consider rotating the hot wallet private key before restoring access

---

## 5. Contact and Support Channels

### Protocol Support

| Protocol | Support Channel | Response Time |
|---|---|---|
| Aave V3 | https://discord.gg/7e4Tvg4 (Aave Discord, #support) | Hours |
| Compound | https://discord.gg/cU7CE2Zuwq (#help channel) | Hours |
| Morpho | https://discord.gg/morpho-protocol (#support) | Hours |
| Yearn | https://discord.gg/6PNv2nF7 (#support) | Hours |
| Maple Finance | https://discord.gg/maplefinance (#support) | Business hours |
| Euler | https://discord.gg/euler-finance (#support) | Hours |
| Spark | https://discord.gg/sparkdao (#support) | Hours |

### Gnosis Safe

- Documentation: https://help.safe.global
- Discord: https://discord.gg/TmkQGnrsmG

### Ethereum Infrastructure

- Infura status: https://status.infura.io
- Alchemy status: https://status.alchemy.com
- Etherscan: https://etherscan.io (transaction lookup)

### Emergency Resources

- DeFi incident tracker: https://rekt.news (to check if a protocol has been hacked)
- Ethereum mempool: https://etherscan.io/txs (verify pending transactions)
- Gas tracker: https://etherscan.io/gastracker

---

## 6. Post-Mortem Template

Use this template after any emergency response. Fill it in within 24 hours of the incident. Store completed post-mortems in `docs/post_mortems/YYYY-MM-DD_<brief_title>.md`.

```markdown
# Post-Mortem: [Brief Title]

**Date:** YYYY-MM-DD
**Severity:** HIGH | CRITICAL
**Duration:** From [time] to [time] UTC
**Capital at risk:** $X,XXX
**Capital lost (if any):** $X,XXX
**Author:** Yurii Kulieshov

---

## Summary

One paragraph. What happened, how it was detected, and how it was resolved.

---

## Timeline

| Time (UTC) | Event |
|---|---|
| HH:MM | First alert / detection |
| HH:MM | Kill switch activated |
| HH:MM | Withdrawals initiated |
| HH:MM | Funds secured |
| HH:MM | Root cause identified |

---

## Root Cause

Describe what caused the incident. Be specific — which protocol, which contract,
which configuration, which agent decision.

---

## Impact

- Protocols affected:
- Capital affected: $X,XXX (X% of portfolio)
- Revenue lost (estimated): $XX
- Downtime: X hours

---

## What Went Well

- (List things that worked correctly during the response)

---

## What Went Wrong

- (List things that failed, were slow, or made the response harder)

---

## Action Items

| Action | Owner | Due Date | Status |
|---|---|---|---|
| Fix root cause | Yurii | YYYY-MM-DD | Open |
| Update risk policy if needed | Yurii | YYYY-MM-DD | Open |
| Add new anomaly detection check | Yurii | YYYY-MM-DD | Open |

---

## Lessons Learned

What would you do differently next time?
```
