# PHASE 2 — CONVERSION SURFACES SPEC (Checkup snapshot / demo / report + SEO)

## C2 — Stablecoin Safety Snapshot (no-wallet micro-quiz) `[P0][M]`

**The product for the W3 audience** (USDT holder, no wallet to scan, non-technical).
Standalone cheap HTML+island — NOT gated behind the kit. Lives on checkup home + linked from
landing (`/#analyze` area gets a second tab: `No wallet? Take the 60-second snapshot`).

**Exactly 4 questions (one screen each, progress dots, ~60s):**
1. `How much do you hold in stablecoins?` / `Сколько у вас в стейблкоинах?` — bands
   `<$10k / $10–50k / $50–250k / $250k+` (same bands as /pilot + F3 segmentation).
2. `Where do they sit right now?` / `Где они лежат сейчас?` — multi:
   `Exchange (CEX) / Own wallet, idle / DeFi protocols / Bank-linked (fintech)`.
3. `Which stablecoins?` / `Какие стейблкоины?` — multi: `USDT / USDC / DAI / other-algo`.
4. `What matters most?` / `Что важнее всего?` — `Don't lose it / Steady income / Max growth`.

**Result (ungated, instant, personalized from a decision matrix — NO free-text LLM):**
- Risk notes per answer combo (e.g. CEX → custody risk note + withdrawal test advice; USDT →
  depeg history sparkline + issuer-risk note; idle → the yield-gap line).
- Yield-gap: band midpoint × realized rate → `~$X/yr left on the table`.
- One matched next step: `Don't lose it` → Conservative page; `Steady income` → packages;
  `Max growth` → aggressive-lab + early-access (M7).
- CTAs: `Email me my snapshot` (optional → `/api/pilot/request`, `source=snapshot`) +
  `Talk to a human` → /pilot?src=snapshot. `data-track="snapshot_complete|snapshot_email"`.
**Acceptance:** completable in <90s on mobile; result renders all 4 answer dimensions; both
CTAs wired; EN|RU. Completion % tracked (F2 target).

## CHK-DEMO — no-scan demo report `[P0][M]`

- Route: main site `/checkup-demo` (styled by the Phase-1 shell) + linked from checkup home
  (`See a sample report`) and homepage (`See what you'd get`).
- Content: a REAL report rendered from a frozen fixture wallet (commit a
  `demo_wallet_report.json` fixture — realistic mixed portfolio: some Aave, idle USDT, one
  risky approval, one dead token). Banner top: `SAMPLE DATA — run your own free scan →` /
  `ОБРАЗЕЦ ДАННЫХ — запустите свой бесплатный скан →` (persistent, amber).
- Every panel identical to the real report (same components — this doubles as the B6 test bed).
- `data-track="demo_view"`, CTA clicks tracked.
**Acceptance:** indistinguishable from a real report except the banner; fixture data plausible
but clearly sample-labeled; loads with zero wallet/API dependency.

## B6 — Checkup report rebuild on the shell `[P1][L]` (checkup repo)

- Tabs: `Overview / Approvals / Positions / Risk / History`.
- KPI strip: Wallet Health Score (existing) · total value · idle stables · est. APY ·
  risk flags count.
- Hero condensed 400px → ~120px (score + one-line verdict + share button E3).
- Tables → sortable DataTable + row Drawer (kit from A1/A2 token sync).
- M8 yield-gap block stays the closing element of every tab's bottom.
- Approvals tab: honest state when scanner degraded (`approvals not scanned — [why]`) — never
  silently empty (known prod issue: Etherscan key, Q-OWN-06).

## E1 — SEO/answer-engine pages (5 briefs) `[P0][M]`

Location: `landing/src/pages/learn/` (or blog/). Each: 1200–1800 words, EN+RU, one honest
expert answer, snapshot CTA embedded mid-page + end, FAQ schema markup, internal links to
packages/trust. Titles:
1. `Is USDT safe in 2026? An honest risk breakdown` — depeg history, issuer risk, what we watch.
2. `What is a stablecoin depeg — and how fast does it happen?` — USDC 2023 case, RTMR angle.
3. `The stablecoin holder's risk checklist (10 checks, 10 minutes)` — leads into snapshot.
4. `CEX vs self-custody for stablecoins: what actually gets people` — approvals, custody.
5. `Why "20% APY on stables" usually means tail risk` — OUR refusal thesis as content — the
   most on-brand piece; links aggressive-lab + refusal log.
**Acceptance:** each page scores green on a Lighthouse SEO pass, has the snapshot CTA, and
fires `data-track="learn_view"` / `learn_cta_click`.

## C5–C8, E3, I1 (kept from roadmap-v2, short specs)

- **C5** every report/snapshot result ends naming the ONE un-fixable gap ("we can't fix custody
  concentration — here's how a desk thinks about it") → bridge link. No promised returns.
- **C6** bridge page `How we think about stablecoin yield (honestly)` — the §2 reframe in long
  form; links from every C5 panel.
- **C7** dual-CTA rule: every conversion surface offers self-serve next step AND `Talk to a
  human`; audit all surfaces once, add missing.
- **C8** trust band (non-custodial · honest-first · public track · "we show the bad news") —
  one component reused on checkup home + report + snapshot result.
- **E3** share card: OG-image endpoint rendering score + one stat (no wallet address unless
  user opts in); `Share your score` button on report + demo.
- **I1** post-lead ops: response SLA (owner answers within 24h — Telegram already pings),
  qualification = holdings band + source; weekly digest of leads by source/band on /admin
  (extend funnels page). Q-OWN if owner wants auto-acknowledge email (needs RESEND key,
  Q-OWN-07).
