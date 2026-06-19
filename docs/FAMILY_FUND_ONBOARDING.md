# SPA Family Fund — Investor Onboarding Guide

**Version:** v1.0  
**Updated:** 2026-06-19 (MP-1417)  
**Portal:** http://localhost:8765 (local) | cloudflare tunnel (remote)  
**Legal templates:** `docs/legal/`  

---

## 1. What is the SPA Family Fund?

The SPA Family Fund is a private investment pool for family members and
trusted close associates. It operates on top of the Smart Passive Aggregator (SPA)
paper-trading infrastructure during the track-record accumulation phase, and will
transition to live DeFi yield farming once go-live criteria are met (target: 2026-08-01).

**Key facts:**

| Parameter | Value |
|-----------|-------|
| Current phase | Paper trading (virtual capital) |
| Virtual AUM | $100,000 USDC |
| Target go-live | 2026-08-01 (pending 30 clean paper days) |
| Minimum participation | TBD (set before go-live) |
| Governance structure | Owner-managed; ADR-002 transfer rule |

---

## 2. Onboarding Steps

### Step 1: Review Legal Documents

Before participating, read the following documents in `docs/legal/`:

1. **DOGOVIR_PROSTOGO_TOVARYSTVA_TEMPLATE.md** — Partnership agreement template
2. **ONBOARDING_CHECKLIST.md** — Investor onboarding checklist

### Step 2: Register with the Fund

Contact the fund operator (Yurii) to be added to the participant registry:

```python
# Registry: spa_core/family_fund/registry.py
# Fields per participant: name, wallet_address, initial_usd, join_date
```

### Step 3: Access the Dashboard

The investor portal is available at:
- **Local network:** http://localhost:8765
- **Remote access:** via Cloudflare tunnel (URL in `data/cloudflared_url.txt`)

The dashboard shows:
- Current portfolio equity curve
- Daily APY and yield earned
- Strategy tournament rankings (S0–S10)
- GoLive readiness status
- Your personal P&L attribution

### Step 4: Telegram Notifications

Daily performance summaries are sent via Telegram. Provide your Telegram
username to the operator to be added to the broadcast list.

---

## 3. Investor Portal Features

| Feature | Description |
|---------|-------------|
| Equity curve | Daily NAV chart since paper-trading start |
| P&L Attribution | `spa_core/family_fund/pnl_attribution.py` |
| Strategy rankings | Tournament evaluator (Sharpe/Calmar/Ulcer/Rachev) |
| Risk dashboard | RiskPolicy block log, kill-switch status |
| GoLive countdown | Days remaining to target go-live |
| Position summary | Current allocations across protocols |

---

## 4. P&L Attribution

Each investor's P&L is calculated proportionally to their share of the fund:

- **Gross yield:** Sum of daily yield across all positions
- **Net yield:** Gross yield minus management fees (TBD)
- **Attribution file:** `data/pnl_attribution.json`

During the paper-trading phase, P&L is notional (virtual USDC).

---

## 5. Risk Disclosures

**IMPORTANT — READ CAREFULLY:**

1. **Paper trading phase:** All current P&L is virtual. No real capital is at risk until go-live.
2. **DeFi risks:** Smart contract vulnerabilities, oracle failures, liquidity crises.
3. **Kill switch:** Portfolio drawdown ≥5% triggers automatic position exit.
4. **No guarantees:** Past APY performance does not guarantee future returns.
5. **Regulatory:** DeFi regulations vary by jurisdiction. Consult your local tax/legal advisor.
6. **Concentration risk:** Per ADR-019, T2 protocols are capped at 50% of AUM.

---

## 6. Reporting

| Report | Frequency | Delivery |
|--------|-----------|---------|
| Daily summary | Every day after cycle run | Telegram |
| Weekly performance | Every Monday | Dashboard + Telegram |
| Monthly P&L attribution | 1st of each month | Dashboard PDF export |
| Go-live readiness | On request | `python3 -m spa_core.analytics.golive_readiness_report --check` |

---

## 7. Go-Live Transition

When go-live criteria are met (ADR-002):
1. Owner manual review and sign-off required
2. Real USDC must be deposited to Gnosis Safe multisig (ADR-022)
3. Investor confirmations collected
4. `python3 -m spa_core.golive.activate` run with `"I CONFIRM LIVE TRADING"` passphrase
5. Execution domain switches from paper to live trading

**No automatic go-live.** All transitions require explicit human approval.

---

## 8. Contact

For questions, onboarding, or reporting issues:
- **Operator:** Yurii (yuriycooleshov@gmail.com)
- **Telegram:** Contact operator for channel invite
- **Issues:** Create GitHub issue in the SPA repository

---

*Document maintained by SPA Engineering. For legal documents see `docs/legal/`.*
