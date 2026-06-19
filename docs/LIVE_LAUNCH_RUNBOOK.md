# SPA Live Launch Runbook

## Version: 1.0 | 2026-06-19

> **Purpose**: Step-by-step operator guide for transitioning SPA from paper trading to live.
> This runbook covers T-1 (pre-launch day), T (launch day), and Day 1 monitoring.
>
> **Owner**: Yurii Kulieshov  
> **Governance**: ADR-002 (go-live transfer rule)  
> **Prerequisite**: GoLiveChecker ≥ 24/26 pass; gap_monitor 30 days clean; manual Owner review

---

## Prerequisites

Before executing this runbook, all of the following must be true:

- [ ] `python3 -m spa_core.paper_trading.golive_checker` → **READY** (≥ 24/26 pass)
- [ ] `python3 -m spa_core.backtesting.pre_launch_validation --save` → **LAUNCH_READY**
- [ ] 30 consecutive honest paper-trading days in gap_monitor (no gaps)
- [ ] ADR-002 go-live transfer rule reviewed and Owner approval obtained
- [ ] Gnosis Safe multisig address confirmed and tested (non-zero balance dry run)

---

## Pre-Launch Day (T-1)

> Day before live capital deployment. All steps **must** complete before T-Day.

### T-1: Validation

- [ ] **validate** — Run `python3 -m spa_core.backtesting.pre_launch_validation --save` → all GREEN

  ```bash
  python3 -m spa_core.backtesting.pre_launch_validation --save
  # Expected: LAUNCH_READY, blocking_count=0
  ```

- [ ] **backup** — Backup all config files

  ```bash
  cp -r data/ data_backup_$(date +%Y%m%d)/
  cp spa_core/risk/policy.py spa_core/risk/policy.backup.$(date +%Y%m%d).py
  ```

- [ ] **gnosis** — Confirm Gnosis Safe address and multisig quorum

  ```bash
  python3 scripts/gnosis_safe_checklist.py
  # Confirm: address, owners, threshold (e.g. 2-of-3)
  ```

- [ ] **kill_switch** — Test kill switch latency (target ≤ 5ms)

  ```bash
  python3 scripts/kill_switch_drill.py --dry-run
  # Expected: latency < 5ms, status: OK
  ```

- [ ] **telegram** — Verify Telegram alerts working

  ```bash
  python3 -m spa_core.family_fund.telegram_blast --test
  # Expected: test message delivered to family fund group
  ```

- [ ] **http_server** — Confirm dashboard accessible at http://localhost:8765

  ```bash
  curl -s http://localhost:8765/health | python3 -m json.tool
  # Expected: {"status": "ok", ...}
  ```

---

## Launch Day (T)

> Capital deployment day. Follow steps in sequence — **do not skip blocking steps**.

### 09:00 — System Check

- [ ] **system_check** — Run CPA health dashboard

  ```bash
  python3 -m spa_core.analytics.cpa_health_dashboard --check-only
  # Expected: all systems GREEN
  ```

- [ ] **regime** — Verify market regime (bull/bear/neutral)

  ```bash
  python3 -m spa_core.analytics.market_regime_gate --status
  # Record: regime, confidence, recommended_risk_level
  ```

- [ ] Gas prices check — Ethereum mainnet + Arbitrum

  ```bash
  # Check https://etherscan.io/gastracker
  # If gas > 50 gwei, consider delaying capital deployment
  ```

### 09:15 — Capital Deployment

> ⚠️ **BLOCKING**: All system checks must be GREEN before proceeding.

- [ ] **capital** — Deploy capital via Gnosis Safe

  Steps:
  1. Navigate to [Gnosis Safe App](https://app.safe.global)
  2. Connect hardware wallet (Ledger/Trezor)
  3. Initiate transfer: $100,000 USDC to SPA strategy vault address
  4. Collect signatures from all required owners
  5. Execute transaction; wait for confirmation (≥ 3 blocks)

- [ ] Confirm transaction on Etherscan / Arbiscan

  ```bash
  # Record txhash:
  TX_HASH="0x..."
  echo "Launch receipt: $TX_HASH" >> data/live/launch_log.txt
  ```

- [ ] Record txhash and block number in `data/live/launch_receipt.json`

  ```json
  {
    "txhash": "0x...",
    "block": 1234567,
    "amount_usdc": 100000,
    "deployed_at": "2026-08-01T09:15:00Z",
    "gnosis_safe_address": "0x..."
  }
  ```

### 09:30 — Strategy Activation

- [ ] **activate** — Activate RS-001 slots (per regime allocation)

  ```bash
  # If bull regime: RS-001 full allocation
  # If neutral:     RS-001 at 70%, cash buffer 30%
  # If bear:        hold cash, do not activate
  python3 -m spa_core.analytics.rs001_live_apy_engine --activate --regime <regime>
  ```

- [ ] Record initial positions in `data/live/initial_positions.json`

  ```bash
  cp data/current_positions.json data/live/initial_positions_$(date +%Y%m%d).json
  ```

- [ ] Set up monitoring alerts

  ```bash
  # Verify launchd daily cycle plist is loaded
  launchctl list | grep com.spa.daily_cycle
  ```

### 10:00 — Post-Launch Verification

- [ ] **verify** — Verify all positions opened correctly

  ```bash
  python3 -m spa_core.paper_trading.cycle_runner --verbose
  # Check: positions match target allocation
  # Check: no risk_policy_blocks.json new entries
  ```

- [ ] Check initial APY readings

  ```bash
  python3 -m spa_core.paper_trading.multi_strategy_runner --verbose
  # Expected: at least one strategy with APY > 1%
  ```

- [ ] **notify** — Send launch Telegram notification

  ```bash
  python3 -m spa_core.family_fund.telegram_blast \
    --message "🚀 SPA is LIVE! Capital deployed. Monitoring begins now."
  ```

### 10:30 — Runbook State Save

- [ ] Save completed runbook state:

  ```bash
  python3 -c "
  from spa_core.backtesting.launch_runbook import LaunchRunbook
  rb = LaunchRunbook()
  for step_id in ['backup','validate','gnosis','system_check','regime','capital','activate','notify','verify']:
      rb.complete_step(step_id, notes='Completed on launch day')
  rb.save()
  print(rb.progress())
  "
  ```

---

## Day 1 Monitoring

> Continuous checks through first 24 hours after launch.

### Every 4 Hours

- [ ] Kill switch status: `python3 scripts/kill_switch_drill.py --status`
- [ ] NAV check: confirm portfolio_nav within expected range
- [ ] Drift check: no position has drifted >5% from target

  ```bash
  python3 -m spa_core.paper_trading.golive_checker
  # Monitor: drawdown_below_kill check must remain PASS
  ```

### Daily

- [ ] `python3 -m spa_core.backtesting.paper_day_counter` — confirm day counter incrementing
- [ ] `python3 -m spa_core.analytics.cpa_health_dashboard` — full daily health check
- [ ] Check `/tmp/spa_cycle.log` for any errors
- [ ] Verify Telegram daily digest was sent

### First Week

- [ ] Day 3: Review initial performance vs. paper trading baseline
- [ ] Day 7: Run `python3 -m spa_core.analytics.weekly_paper_report_v2`
- [ ] Day 7: Confirm ADR-002 READY status maintained for 7 days

### Kill Switch Triggers (act immediately)

The live cycle will auto-trigger the kill switch on:

- Portfolio drawdown ≥ **5%** from peak NAV
- Any T1 protocol TVL drops below **$5M**
- Per-protocol concentration exceeds **40%** (T1) or **20%** (T2)

Manual override: **never** — `approved=False` from RiskPolicy cannot be overridden.

---

## Rollback Procedure

If a critical issue is found within first 24 hours:

1. **Immediate**: Trigger kill switch — close all positions to USDC
2. **Notify**: Telegram blast to family fund participants
3. **Diagnose**: Check `data/risk_policy_blocks.json`, `/tmp/spa_cycle_err.log`
4. **DR Procedure**: Follow `DR_PROCEDURE_v2.md`
5. **ADR**: Document incident, create new ADR if policy change needed

---

## References

- `ADR-002-golive-transfer-rule.md` — Transfer rule and READY criteria
- `DR_PROCEDURE_v2.md` — Disaster recovery procedure
- `docs/TOKEN_ROTATION_RUNBOOK.md` — PAT rotation (if needed during launch)
- `spa_core/golive/activate.py` — Live activation script (manual `"I CONFIRM LIVE TRADING"`)
- `spa_core/backtesting/pre_launch_validation.py` — Pre-launch validation suite
- `spa_core/backtesting/launch_runbook.py` — Automated runbook state tracking

---

*MP-1368 v9.84 — Sprint v9.84 | Generated: 2026-06-19*
