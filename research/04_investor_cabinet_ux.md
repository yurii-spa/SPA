# Investor Cabinet UX — Research Report
## DeFi Yield Fund Investor Portal Design

**Prepared:** 2026-06-18  
**Scope:** UX patterns in DeFi (Nexo, Maple Finance, Enzyme, dHEDGE, Yearn) and TradFi (Interactive Brokers, Schwab, Fidelity), synthesized into a design spec for a DeFi yield fund serving participants with $25K–$250K deposits and daily yield accrual (SPA family fund context).

---

## Part 1: Platform Analysis

### 1.1 DeFi Platforms

#### Nexo
- **Approach:** Minimalist, product-group model. Real-time portfolio snapshot, credit line balance, and total interest earned are the three above-the-fold hero metrics.
- **Navigation:** Features grouped around the account (savings, credit, card, trading) rather than as separate apps — reduces context-switching but risks complexity for users who came only for yield.
- **Mobile:** App mirrors desktop design faithfully. Navigation is accessible in ≤3 taps from home to any feature.
- **Strength:** Clean onboarding, progressive disclosure, beginner-accessible.
- **Weakness:** Multi-product integration (futures, token loyalty tiers) adds cognitive load for pure yield investors. Not a clean model for a focused yield fund.

#### Maple Finance (via Securitize)
- **Approach:** Institutional-grade investor portal at `maplefinance.invest.securitize.io`. Targets accredited investors and institutions.
- **Core UX promise:** "Depositors have full visibility of their balance and transaction history in one place." Real-time balance updates.
- **KYC/access:** Gated through Securitize — creates friction but builds regulatory trust.
- **Yield display:** Net APY prominently shown per product. 2024 flagship (High Yield Secured) delivered 16.83% net APY; BTC Yield product shows 5.13% APY paid in BTC.
- **Strength:** Clean separation of product discovery and portfolio view. Institutional-grade document trail (Securitize handles compliance docs).
- **Weakness:** UI built on Securitize template — limited customization, generic feel, not DeFi-native.

#### Enzyme Finance / dHEDGE
- **Approach:** Vault-centric UI. Each vault card shows current NAV, APY, deposits, and strategy name.
- **Transparency:** Shows underlying protocol exposure and strategy logic.
- **Charts:** Per-vault performance charts available with period selectors.
- **Weakness:** No investor-grade document generation (no PDF statements, no tax reporting). Crypto-native only — assumes MetaMask fluency. No notification system.

#### Yearn Finance
- **Approach:** Clean vault list with net APY prominently displayed (after fees, after compounding).
- **UX principle:** Minimalist — only the data a vault depositor needs.
- **Weakness:** No investor portal at all — just a vault list. No P&L tracking, no history, no documents. Users must use third-party trackers (Zerion, DeBank) to see portfolio context.

#### General DeFi Tracker Pattern (Zerion, DeBank, CoinStats)
The DeFi tracker ecosystem has converged on a pattern that any investor portal should learn from:
- Pull all positions into one unified view, regardless of chain or protocol
- Decode on-chain activity into human-readable terms (not raw transaction hashes)
- Display performance over time as a net worth curve
- Show pending/claimable rewards prominently
- Display net yield after gas costs where calculable
- Cross-protocol APY may differ across trackers (different calculation methods) — transparency about methodology matters

---

### 1.2 TradFi Platforms

#### Fidelity
- **Dashboard:** Widgetized landing page surfaces the financial picture at a glance without feeling overwhelming. Highest usability scores among major brokers (93rd percentile, SUPR-Q benchmark).
- **2024–2025 update:** Unified Managed Household platform — migrated 1M+ accounts to goal-based, cross-account portfolio management.
- **Strength:** Tax reporting, full document archive, auto-generated statements.
- **Weakness:** Product pages lack a top-level comparison view — users must navigate to each product page individually, creating confusion for less experienced investors.

#### Charles Schwab
- **Dashboard:** Sets the 2026 industry standard for UX according to StockBrokers.com. Broad investments, strong account support, friction-reducing flows.
- **Clarity:** 94% of users agree "my portfolio dashboard is clear and understandable" — highest in the industry.
- **Weakness:** Steep initial learning curve; jargon-heavy for new investors.

#### Interactive Brokers
- **Dashboard:** 360-degree account view with up to 35 default reports (time period performance, risk measures, projected income). Fully customizable.
- **Target audience:** Active, sophisticated traders. NOT a good model for a family yield fund.
- **Strength:** Deepest reporting capabilities of any retail broker — time-period performance, risk decomposition, tax lot tracking, CSV export.
- **Weakness:** Overwhelming for non-professional investors.

#### Key Metrics from Brokerage UX Research (MeasuringU, 2018 — still highly cited)
- Top investor tasks: checking balances (27%), reviewing recent performance (24%)
- Mobile usage: ~35% of brokerage users access primarily via mobile app
- #1 UX driver: information security (explains 16% of satisfaction variance)
- #2 UX driver: clear portfolio dashboard (explains 12% of satisfaction variance)
- All top brokers score 88–94% on "dashboard is clear and understandable"
- Learning curve and jargon are the most common complaints across all platforms
- Customer service calls most commonly triggered by: login issues, product research, fund transfers

---

## Part 2: Design Specification — SPA Investor Cabinet

**Target user:** Family/friends fund participants, $25K–$250K deposits, daily yield accrual. Some DeFi familiarity but not necessarily crypto-native. Priorities: trust, yield visibility, document completeness.

---

### 2.1 Information Architecture (Sitemap)

```
Investor Cabinet (Root)
├── Dashboard (Home)
│   ├── 5-KPI hero section
│   ├── Equity curve chart
│   ├── Recent activity feed
│   └── Yield attribution mini-table
│
├── Portfolio
│   ├── Current Positions (by protocol)
│   ├── Allocation View (T1 / T2 / Cash breakdown)
│   └── Performance Analytics (Sharpe, drawdown, benchmark)
│
├── Yield & Returns
│   ├── Yield History (chart + table)
│   ├── Yield Attribution (by protocol)
│   └── Benchmark Comparison (vs USDC savings rate)
│
├── Transactions
│   ├── Deposits & Withdrawals
│   ├── Rebalance Log
│   └── Fee History
│
├── Documents
│   ├── Monthly Statements (PDF, auto-generated)
│   ├── Annual Reports (PDF)
│   ├── Tax Documents
│   └── Data Exports (CSV)
│
├── Notifications
│   ├── Alert Preferences (per-type channel selection)
│   └── Notification History
│
├── Account
│   ├── Profile (name, email, Telegram handle)
│   ├── Security (2FA, session management)
│   └── KYC Status
│
└── Support
    ├── FAQ / Knowledge Base
    └── Contact (email/Telegram)
```

**Navigation model:** Persistent left sidebar on desktop (collapsible), bottom tab bar on mobile. Maximum depth: 2 levels from any screen. Account/Settings in user avatar dropdown (top-right). Breadcrumb trail on all sub-pages.

**Top-level tabs (5):** Dashboard · Portfolio · Yield · Transactions · Documents  
**Secondary access:** Notifications bell icon in header; Account avatar dropdown; Support in footer.

---

### 2.2 Dashboard Screen (Wireframe)

**Design principle:** Security-first visual trust, then yield performance, then system health.

**5 KPIs above the fold:**

| # | KPI | Label | Value example | Why this |
|---|-----|-------|---------------|---------|
| 1 | **Total Portfolio Value** | "Your Balance" | $127,432.18 | Primary investor concern (27% of visits) |
| 2 | **Yield Earned This Month** | "This Month's Yield" | $398.20 (+$13.42 today) | Daily compounding — most emotionally engaging metric |
| 3 | **Net APY (since inception)** | "Annual Return Rate" | 12.4% | The single number investors share with others |
| 4 | **Allocation vs Target** | "Portfolio Composition" | T1: 72% · T2: 18% · Cash: 10% | Risk visibility; reassures participant money is deployed |
| 5 | **Cycle / System Status** | "Last Updated" | ✅ Jun 18, 08:02 AM · Next: Jun 19, 08:00 | Proves the fund is actively managed; critical for trust |

**Wireframe text layout:**

```
┌─────────────────────────────────────────────────────────────────────┐
│  [≡ SPA]  Smart Passive Aggregator          [🔔 3]  [YK ▾]         │
├──────────┬──────────────────────────────────────────────────────────┤
│ Dashboard│                                                           │
│ Portfolio│  Good morning, Yurii · Thursday, June 18 · 14:23         │
│ Yield    │  ─────────────────────────────────────────────────────   │
│ Transact.│                                                           │
│ Documents│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐    │
│          │  │ Your Balance │ │ Month Yield  │ │   Net APY    │    │
│          │  │              │ │              │ │              │    │
│          │  │ $127,432.18  │ │   $398.20    │ │   12.4%      │    │
│          │  │ ▲ +$13.42    │ │ Today: $13.42│ │  Since Jun 10│    │
│          │  │   today      │ │ Proj: $406/mo│ │  (8 days)    │    │
│          │  └──────────────┘ └──────────────┘ └──────────────┘    │
│          │                                                           │
│          │  ┌──────────────────┐  ┌──────────────────────────────┐ │
│          │  │  Allocation      │  │  System Status               │ │
│          │  │  T1  ████████ 72%│  │  ✅ Cycle OK · Jun 18 08:02  │ │
│          │  │  T2  ███      18%│  │  📊 GoLive: 16/26 criteria   │ │
│          │  │  Cash ██      10%│  │  ⏰ Next cycle: Jun 19 08:00  │ │
│          │  └──────────────────┘  └──────────────────────────────┘ │
│          │                                                           │
│          │  Portfolio Performance  [7D] [30D] [90D] [1Y] [All]      │
│          │  ┌──────────────────────────────────────────────────┐    │
│          │  │                                          ●        │    │
│          │  │                                   ●────           │    │
│          │  │                              ────                 │    │
│          │  │   $100K ──────────●────                          │    │
│          │  │   Jun 10                             Jun 18       │    │
│          │  └──────────────────────────────────────────────────┘    │
│          │                                                           │
│          │  Recent Activity                 Yield by Protocol       │
│          │  ──────────────────              ──────────────────────  │
│          │  Jun 18  +$13.42 yield            Aave V3      $5.14/d  │
│          │  Jun 17  +$13.29 yield            Compound V3  $4.19/d  │
│          │  Jun 16  Rebalance –3.2%          Morpho       $3.11/d  │
│          │  Jun 15  +$13.18 yield            Other        $1.00/d  │
│          │                     [View all transactions →]            │
└──────────┴──────────────────────────────────────────────────────────┘
```

**Design notes:**
- KPI card #1 (Balance) is visually largest — 40% more whitespace than others
- Green for positive delta, red for negative (with non-color secondary indicator: ▲/▼ symbol for colorblind users)
- Data freshness timestamp always visible (ISO 8601 format; human-readable tooltip on hover: "Updated 5 hours 58 minutes ago")
- System Status card uses traffic-light colors with icon fallback (✅/⚠️/🔴) for accessibility
- Equity curve area chart: smooth bezier, filled area below line in brand color at 20% opacity

---

### 2.3 Yield History Screen (Wireframe)

**Recommended approach: Dual-mode (Chart default + Table toggle).** Research confirms chart for trend recognition, table for precise value retrieval (tax/accounting). The two serve different cognitive jobs and should both be available.

**Default period: 30 days.** Rationale: long enough to see meaningful trend, short enough to load fast and stay relevant for daily-accrual funds. First-time visitors see the full track record (8 days at launch).

```
Yield History                                         [⬇ Export CSV]
──────────────────────────────────────────────────────────────────
Period: [7D] [30D▼] [90D] [1Y] [All] [Custom: 📅]  View: [📈 Chart] [📋 Table]

━━━━━━━━━━━━━━━━━━━━━━ CHART VIEW (default) ━━━━━━━━━━━━━━━━━━━━━

  Cumulative Yield Earned ($)
  
  $450 ┤                                                  ●
  $375 ┤                                          ●────
  $300 ┤                                  ●────
  $225 ┤                          ●────
  $150 ┤                  ●────
   $75 ┤          ●────
    $0 ┤  ●────
       └──────────────────────────────────────────────────
        Jun 10  Jun 12  Jun 14  Jun 16  Jun 18

  ── Cumulative yield     ·· Daily rate (right axis)
  Toggle: [By Protocol ▸]    Hover tooltip: "Jun 18 · +$13.42 · APY: 12.4%"

━━━━━━━━━━━━━━━━━━━━━━ TABLE VIEW (toggle) ━━━━━━━━━━━━━━━━━━━━━

  Date ↓       Daily Yield    APY (ann.)   Top Protocol       Cumulative
  ──────────   ──────────     ──────────   ──────────────     ──────────
  Jun 18       $13.42         12.4%        Aave V3 (38%)      $398.20
  Jun 17       $13.29         12.3%        Aave V3 (37%)      $384.78
  Jun 16       $13.45         12.5%        Morpho  (24%)      $371.49
  Jun 15       $13.18         12.2%        Aave V3 (38%)      $358.04
  Jun 14       $13.31         12.3%        Compound (31%)     $344.86
  Jun 13       $13.22         12.2%        Aave V3 (36%)      $331.55
  Jun 12       $13.28         12.3%        Aave V3 (37%)      $318.33
  Jun 11       $13.19         12.2%        Compound (30%)     $305.05
  Jun 10       $13.11         12.1%        Aave V3 (38%)      $291.86

  Showing 9 of 9 rows  (full track record)                     [⬇ CSV]
```

**Chart design notes:**
- Period selector uses pill buttons, active state has filled background
- Chart has two y-axes: left = cumulative USD, right = daily rate USD
- Hover tooltip shows: date, daily amount, annualized rate, top protocol that day
- "By Protocol" toggle switches to stacked area chart showing protocol contribution breakdown
- Chart must be keyboard-navigable: Tab steps through data points; screen reader announces values
- Patterns/textures used in stacked chart view (not color-only) for accessibility

**Table design notes:**
- Default sort: date descending (most recent first)
- All columns sortable with clear sort indicator (▲▼)
- APY column tooltip explains: "Annualized rate based on this day's yield as percentage of total AUM"
- CSV export includes: date, daily_yield_usd, apy_annualized, top_protocol, cumulative_yield_usd, portfolio_value_eod

---

### 2.4 Documents Section (Wireframe)

**Design principle:** Fidelity-level document completeness with DeFi-native CSV export capability.

```
Documents
──────────────────────────────────────────────────────────────────
[Monthly Statements] [Annual Reports] [Tax Documents] [Data Exports]

━━━━━━━━━━━━━━━━━━━ MONTHLY STATEMENTS ━━━━━━━━━━━━━━━━━━━━━━━━━

  Period              Type                Generated         
  ─────────────       ─────────────────   ───────────────   ──────────
  Jul 2026            Portfolio Statement  Aug 1, 2026       [Pending]
  Jun 2026            Portfolio Statement  Jul 1, 2026       [Pending]
  
  ℹ Track record began June 10, 2026. First complete statement 
    available August 1, 2026 (covering June 10–July 31).
  
  Statement contents: Portfolio value, yield earned, allocation 
  breakdown, protocol exposure, risk policy status, transaction log.
  Format: Tagged PDF (screen-reader compatible, print-ready).

━━━━━━━━━━━━━━━━━━━━ DATA EXPORTS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Date range:    From [ Jun 10, 2026 ]  To [ Jun 18, 2026 ]
  
  Export type:
  ◉ Yield History (daily accruals)
  ○ All Transactions (deposits, withdrawals, rebalances)
  ○ Position Snapshots (daily AUM by protocol)
  ○ Full Data Bundle (all of the above, ZIP)
  
  Format:  ◉ CSV (Excel-compatible UTF-8)  ○ JSON
  
  Fields included: date · type · amount_usd · protocol · 
                   apy_annualized · running_balance_usd
  
                                              [⬇ Download Export]
  
  ─────────────────────────────────────────
  Export history (last 5):
  Jun 18, 2026 14:31 · Yield History Jun 10–18 · CSV  [↻ Re-download]
  Jun 15, 2026 09:12 · All Transactions Jun 10–14 · CSV [↻ Re-download]
```

**Access controls:**
- Document download requires active authenticated session (re-auth prompt if session idle >15 min)
- No document URLs are shareable/guessable — use signed URLs with 60-second expiry
- Audit log: all downloads recorded and visible to user in "Export history"
- PDFs are tagged (ISO 32000-1 compliant, WCAG PDF/UA) — required for screen reader access

---

### 2.5 Notification Preferences (Wireframe)

**Design principle:** Per-event-type channel selection. Granular control prevents opt-out fatigue. Security alerts are non-configurable.

**Channel priority (research-backed):**
- Push notifications: 50–60% open rate, 90% view rate — use for time-sensitive alerts
- Email: standard for reports, statements — higher trust for compliance docs
- Telegram: DeFi-native channel — primary for daily digest and rebalance alerts
- Rule: 64% of users disable push after irrelevant notifications → granular defaults matter

```
Notification Preferences
──────────────────────────────────────────────────────────────────
Connected channels:
  ✅ Email    yuriycooleshov@gmail.com                     [Change]
  ✅ Telegram @yurii_spa_bot  (connected Jun 10)           [Disconnect]
  ○  Push     Not enabled on this device          [Enable Push Notifications]

  ┌───────────────────────────────────────────────────────────────┐
  │                          Email    Telegram    Push            │
  │ ─────────────────────────────────────────────────────────     │
  │ 🔒 Security Alerts          ✅       —           ✅  [locked] │
  │    (login, 2FA, withdrawal)                                   │
  │ 📄 Monthly Statement Ready  ✅       ○           ○            │
  │ 📈 Daily Yield Digest        ○       ✅          ○            │
  │ ⚖️  Rebalance Executed       ✅       ○           ✅          │
  │ 🚨 Risk Policy Block         ✅       ✅          ✅          │
  │ 📉 Drawdown Alert (>2%)      ✅       ✅          ✅          │
  │ 💰 Deposit Confirmed         ○        ○           ✅          │
  │ ℹ️  System Maintenance       ✅       ○           ○            │
  └───────────────────────────────────────────────────────────────┘

  Quiet Hours:  Start [22:00]  End [07:00]  Applies to: [Push only ▾]
  
  Note: Security alerts bypass quiet hours.
  
  Telegram setup guide: [How to connect the SPA Telegram bot →]
  
                                              [Save Preferences]
```

**UX notes:**
- Locked row (security alerts) shows lock icon and tooltip: "Cannot be disabled — required for account security"
- Telegram column only active once bot is connected; otherwise cells show "─" with tooltip: "Connect Telegram to enable"
- "Daily Yield Digest" default = Telegram ON (DeFi-native users expect this)
- Drawdown alerts default = all channels ON (highest-stakes event)
- Quiet hours apply to push only; email and Telegram respect their own platforms' delivery
- Notification history tab shows last 30 days of sent notifications with delivery status

---

### 2.6 Mobile Considerations

**Non-negotiable mobile requirements:**

1. **Dashboard KPIs** — All 5 KPIs visible without horizontal scroll. Mobile layout: 2-column grid (2×2 cards + 1 full-width hero for Total Balance). Hero card gets ~48px font size.

2. **Equity curve chart** — Full-width area chart. Period selector becomes horizontal scroll-picker below the chart (touch target: 44×44px minimum per Apple HIG and WCAG). Pinch-to-zoom disabled (confusing in financial context) — use period buttons instead.

3. **Yield feed** — Scrollable list of last 14 days of yield entries. Each row shows date, amount, APY. Tappable row expands to show protocol breakdown.

4. **Push notification delivery** — Required for drawdown alerts and security events. Deep-link from notification opens directly to relevant screen (e.g., drawdown alert → Yield History; rebalance → Transactions).

5. **Document download** — PDF/CSV opens in native viewer or triggers share sheet (iOS/Android). No in-app PDF viewer required — use OS-native.

6. **Biometric auth** — Face ID / Touch ID / fingerprint for login and document download auth. Fallback to PIN. No full password entry on mobile except initial setup.

7. **Notification preferences** — Full configuration available on mobile, not just view.

**Mobile navigation:** Bottom tab bar with 5 tabs:
```
[🏠 Dashboard] [📊 Portfolio] [📈 Yield] [📄 Docs] [⋯ More]
```
"More" expands to: Transactions · Notifications · Account · Support

**Mobile-specific cuts (not required on mobile):**
- Advanced analytics (Sharpe, Ulcer index) → desktop-only or "Advanced" tab
- Benchmark comparison charts → progressive disclosure behind "Compare" button
- Bulk CSV export with custom date range → still present but simplified UI

---

### 2.7 Accessibility Requirements (WCAG 2.1 AA Minimum)

**Legal context:** WCAG 2.1 Level AA is required under the EU European Accessibility Act (EAA, effective June 2025) and cited in US DOJ 2024 final rule for ADA digital services. Only 31% of European fintechs currently meet basic requirements — compliance is a competitive differentiator.

**Mandatory requirements for SPA investor cabinet:**

| Requirement | Standard | Implementation |
|-------------|----------|---------------|
| Color contrast (text) | WCAG 1.4.3 | ≥4.5:1 for body text, ≥3:1 for large text (18pt+) |
| Color contrast (UI components, charts) | WCAG 1.4.11 | ≥3:1 for chart bars/lines vs background |
| Color not sole conveyor of information | WCAG 1.4.1 | Add ▲/▼ symbols alongside green/red; patterns in charts |
| Keyboard navigation | WCAG 2.1.1 | Every interactive element reachable via Tab; logical Tab order |
| Focus visible | WCAG 2.4.7 | Clear focus ring on all interactive elements (min 3px offset outline) |
| Chart accessibility | WCAG 1.4.1 + 1.1.1 | Hover tooltips must also trigger on keyboard focus; provide data table alternative |
| Screen reader labels | WCAG 4.1.2 | ARIA labels on all financial values: `aria-label="Total portfolio value $127,432.18"` |
| Form labels | WCAG 1.3.1 | Visible labels on all inputs (not just placeholders) |
| Error messages | WCAG 3.3.1 | Inline text errors, not color-only; describe what went wrong and how to fix it |
| Session timeouts | WCAG 2.2.1 | Warn 60 seconds before auto-logout; no session shorter than 15 minutes without warning |
| Touch targets | WCAG 2.5.5 | Minimum 44×44px for all tappable elements (mobile and touch screens) |
| PDF accessibility | WCAG + PDF/UA | Tagged PDFs (ISO 32000-1) — required for screen reader access to statements |
| Text resize | WCAG 1.4.4 | All text functional at 200% zoom without horizontal scrolling |
| Language identification | WCAG 3.1.1 | `<html lang="uk">` or `lang="en"` correctly set for localization |

**Chart-specific accessibility implementation:**
- Bar/area charts: use texture patterns (hatching, dots) in addition to color fills
- Line charts: use different line styles (solid, dashed, dotted) alongside color coding
- All charts have an accessible data table alternative (toggle: "View as table")
- Tooltips: triggered on both hover AND keyboard focus (no hover-only disclosure)
- Color palette tested against deuteranopia and protanopia (green/red confusion): use blue/orange as primary data pair, not green/red alone

---

## Part 3: TradFi vs DeFi Comparison

### Where TradFi Wins

| Dimension | TradFi Advantage | Application to SPA |
|-----------|-----------------|-------------------|
| **Document completeness** | Auto-generated monthly/annual statements, 1099 tax forms, full audit trail | Must-build: PDF statement generator, CSV export with tax-compatible fields |
| **Accessibility** | Legal exposure drives investment in WCAG compliance | Adopt WCAG 2.1 AA as minimum; test with screen reader before launch |
| **Dashboard research** | Years of A/B data on what investors actually check (balances 27%, performance 24%) | Copy the 5-KPI layout from proven Schwab/Fidelity patterns |
| **Jargon management** | E*Trade/Schwab use progressive disclosure — "learn more" tooltips on technical terms | Add ℹ️ tooltip to APY, T1/T2, RiskPolicy terms; don't assume DeFi fluency |
| **Multi-device consistency** | Fidelity/Schwab maintain near-identical flows across web and mobile | Design mobile-first, then desktop expansion — not the other way around |
| **Customer support integration** | Chat/phone embedded within portal | Provide in-portal support link (email or Telegram support bot), not Discord |
| **Product overview page** | E*Trade's "overview + learn more" pattern beats Fidelity's silo pattern | Single "How your money is working" page with protocol descriptions for newcomers |

### Where DeFi Wins

| Dimension | DeFi Advantage | Application to SPA |
|-----------|---------------|-------------------|
| **Real-time transparency** | Vault balances update in real-time; investors can verify on-chain independently | Add "Verify on Etherscan" link next to each position — builds trust, costs nothing |
| **Protocol attribution** | Shows exactly where yield comes from (Aave: 38%, Morpho: 23%) | Yield attribution table is a competitive differentiator vs TradFi black-box |
| **Telegram-native notifications** | Bot-based notifications; crypto users already use them, higher open rates | Telegram daily digest is a first-class feature, not an afterthought |
| **Open data** | Public APIs/subgraphs enable third-party verification | Expose a read-only public API or JSON endpoint for portfolio status (optional) |
| **No business hours** | Instant deposit/withdrawal visibility, 24/7 | Real-time cycle status widget on dashboard (not a T+1 update like TradFi) |
| **Community governance transparency** | Protocol changes verifiable on-chain | Link to relevant ADR documents from UI: "Why did we rebalance?" → ADR-019 |

### Strategic Whitespace for SPA

**No major DeFi yield fund currently offers all three of:**
1. Auto-generated investor-grade PDF statements
2. Telegram daily digest with per-protocol attribution
3. WCAG 2.1 AA-accessible dashboard

This combination sits in the gap between crypto-native tools (no documents, no accessibility) and TradFi portals (no Telegram, no real-time on-chain attribution). It is the most defensible UX positioning for the $25K–$250K segment.

---

## Part 4: Key Recommendations Summary

1. **Build the dashboard as a trust artifact first, yield display second.** The #1 driver of brokerage UX quality is security perception (16% variance). Show: last cycle timestamp, GoLive criteria status, RiskPolicy status — all above the fold.

2. **Use Fidelity's widgetized layout, not IBKR's complexity.** Widgetized KPI cards + equity curve is proven at scale. IBKR's 35-report model is for professional traders, not family fund participants.

3. **Yield history: chart + table, 30D default, with protocol-stacked toggle.** Chart for trends; table for tax. Neither alone is sufficient for the $25K+ investor who will need to share data with an accountant.

4. **Daily yield digest via Telegram is non-negotiable for DeFi audience.** It costs ~0 to implement (Python Telegram bot, stdlib-only) and has 2–3× the engagement of equivalent email. Default it ON.

5. **Build PDF statements from day one, even if they're simple.** The absence of a professional PDF statement is the #1 UX signal that a yield fund is not institutional. Auto-generate on month close using Python reportlab or html→PDF.

6. **Mobile-first for portfolio checking, desktop-first for exports/analytics.** The research is unambiguous: 35% of investors check balances on mobile; they use desktop for research and exports. Design the mobile view as the primary experience, not a stripped-down version.

7. **WCAG 2.1 AA compliance is legally required (EU EAA) and a trust signal.** Implement: 4.5:1 contrast, keyboard nav, ARIA labels, texture-pattern charts. Only 31% of fintechs comply — standing out is easy.

8. **Protocol attribution is the key DeFi differentiator.** No TradFi product shows you "38% of your return came from Aave V3 today." This is the one thing the investor cabinet should make impossible to miss.

---

## Sources

- [Nexo Review 2026 — Coin Bureau](https://coinbureau.com/review/nexo-review)
- [Nexo Review 2026 — CoinSpeaker](https://www.coinspeaker.com/reviews/nexo-review/)
- [Welcome to the Maple Finance Investor Dashboard — Securitize](https://maplefinance.invest.securitize.io/)
- [Maple Finance — The Leader in Onchain Asset Management](https://maple.finance/)
- [Maple Yield Performance 2024](https://maple.finance/insights/maple-yield-performance-2024)
- [Turning Vision Into Action: Scaling Maple in 2025](https://maple.finance/insights/turning-vision-into-action-scaling-maple-in-2025)
- [Fintech UX Design: 10 Best Practices for Dashboards 2026 — WildNetEdge](https://www.wildnetedge.com/blogs/fintech-ux-design-best-practices-for-financial-dashboards)
- [Investment Website Graphic Design: 8 Practices — RonDesignLab](https://rondesignlab.com/blog/design-news/most-sucessful-practices-for-investment-platform-ui-ux)
- [Financial UX Design — UXDA](https://www.theuxda.com/blog/tag/financial-dashboard-design)
- [Fintech UX Design: A Complete Guide 2026 — WebStacks](https://www.webstacks.com/blog/fintech-ux-design)
- [The UX of Brokerage Websites — MeasuringU (Sauro, 2018)](https://measuringu.com/ux-brokerage/)
- [Interactive Brokers vs. Schwab — SmartAsset](https://smartasset.com/investing/interactive-brokers-vs-schwab)
- [StockBrokers.com Awards: Best Brokers for User Experience](https://www.stockbrokers.com/guides/user-experience)
- [Fidelity vs Interactive Brokers 2026 — StockBrokers.com](https://www.stockbrokers.com/compare/fidelityinvestments-vs-interactivebrokers)
- [Fidelity Wealthscape brokerage platform](https://clearingcustody.fidelity.com/solutions/technology/brokerage)
- [Financial Dashboard Examples 2026 — UseDataBrain](https://www.usedatabrain.com/blog/financial-dashboard-examples)
- [Fintech Dashboard: 6 Examples by Segment — UseDataBrain](https://www.usedatabrain.com/blog/fintech-dashboards)
- [DeFi Portfolio Tracker by Zerion](https://zerion.io/defi-portfolio-tracker)
- [DeFi Portfolio Tracker 2026: 6 Best Tools Compared — Portals.fi](https://blog.portals.fi/defi-portfolio-tracker-comparison/)
- [DefiLlama — DeFi Dashboard & Crypto Analytics](https://defillama.com/)
- [Top 10 Wealth Management Apps 2025 — Prateeksha](https://prateeksha.com/blog/top-10-wealth-management-apps-to-optimize-your-finances-in-2025)
- [Features Every Self-Investing App Should Include 2025 — InvestSuite](https://www.investsuite.com/insights/blogs/features-every-self-investing-app-should-include-in-2025)
- [6 Wealthtech Apps with the Best UX — Windmill Digital](https://windmill.digital/six-wealthtech-apps-with-outstanding-ux/)
- [How to Make Your Fintech ADA Compliant — Netguru](https://www.netguru.com/blog/ada-compliance-for-fintech)
- [Financial Services Accessibility: Banking Website WCAG Requirements — TestParty](https://testparty.ai/blog/financial-services-accessibility)
- [Only 31% of Fintech Platforms Meet Basic Web Accessibility Requirements — TestDevLab](https://www.testdevlab.com/blog/only-31-percent-of-fintech-companies-meet-digital-accessibility-requirements)
- [Accessible Data Visualization in Fintech — HackerNoon](https://hackernoon.com/accessible-data-visualization-in-fintech-why-it-matters)
- [Accessible Charts Guide for WCAG Compliance — ADA Compliance Pros](https://www.adacompliancepros.com/blog/accessible-charts)
- [How Accessibility Standards Can Empower Better Chart Visual Design — Smashing Magazine](https://www.smashingmagazine.com/2024/02/accessibility-standards-empower-better-chart-visual-design/)
- [Fintech Push Notifications: How to Engage Users — Upshot.ai](https://upshot-ai.medium.com/fintech-push-notifications-how-to-engage-users-in-real-time-018859843c00)
- [How Push Notifications in Fintech Drive Engagement — CleverTap](https://clevertap.com/blog/push-notifications-in-fintech/)
- [Investor Portal Software — iTransition](https://www.itransition.com/portals/investor)
- [UX Tips for Finance App Charts — Extej Agency](https://medium.com/@extej/ux-tips-for-enhancing-the-usability-of-finance-app-charts-and-graphs-0843d723b57f)
- [Fintech UX Best Practices 2026 — Eleken](https://www.eleken.co/blog-posts/fintech-ux-best-practices)

---

*Report generated: 2026-06-18 · Research depth: 14+ sources across 5 search angles · Adversarial verification applied to factual claims.*
