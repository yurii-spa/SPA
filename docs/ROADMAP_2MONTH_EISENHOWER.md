# 2-Month Development Roadmap — Eisenhower Matrix

**Generated:** 2026-07-10 via a 5-scout + synthesis planning sprint (grounded in the real repos).
**Scope:** DeFi Checkup (`checkup.earn-defi.com`) + SPA / earn-defi.com.
**Horizon:** 8 weeks — four fortnightly sprints.

---

## North Star
A 30-day **honest evidenced paper track** that reaches **go-live** and converts SPA's already-built
measurement/refusal moat into the **first real-counsel conversation and first non-custodial design-partner
pilot** — with **DeFi Checkup as a trustworthy, recurring top-of-funnel** feeding warm, verified traffic
into that first-capital pipeline.

**How urgency vs importance were judged:** Urgency = time-critical / blocking / decaying (go-live is ~11
days out; anything a diligence reviewer would find *today*, like an unauth `/admin`, scores high). Importance
= moves the north-star chain **track → go-live → first external AUM → durable measurement/trust moat**.
Discipline: most go-live blockers are **time-gated (waiting)** or **owner/legal**, so pure waiting sits in
Q1-as-guard (not as code) and owner blockers are split into a dedicated list. **Q1 is kept small; Q2 (the
strategic core) is large.** Hard invariants honored throughout (no LLM in risk/exec/monitoring, non-custodial,
no fabricated APY, deterministic + fail-closed, RiskPolicy v1.0 untouched).

---

## 🔴 Q1 — Urgent + Important · DO FIRST (small by design)
> Crises, deadline-gating, and defects a reviewer finds today.

| # | Initiative | Effort | Weeks | Owner-gated |
|---|---|---|---|---|
| 1 | **Guard 30-day track continuity to go-live** — never run cycle_runner/backtests against live `data/` (documented anchor-reset hazard). The first credibility artifact. | S | W1–8 | — |
| 2 | **Fix the live-track concentration breach** (aave_v3 ~50% vs 40% T1 cap) in the `optimized_yield` allocator — a warn today becomes a HARD `approved=False` at go-live. RiskPolicy v1.0 untouched. | M | W1–2 | — |
| 3 | **Reconcile the public APY story** to ONE evidence-tagged (L3) number across /packages, /track-record, /fundability — conflicting yields are the exact crack first-LP diligence can't afford. | S | W1–2 | ✅ owner picks the number |
| 4 | **De-index + CF-Access-prepare the unauth `/admin`** console (analytics/funnels/leads). noindex shipped; real lock is owner CF Access. | S | W1–2 | ✅ owner enables CF Access |
| 5 | **Schedule resilience rollup + drills as a launchd agent; clear CRITICAL agent_health** — resilience_status is 7d stale, fleet is CRITICAL. Most embarrassing pre-launch failure mode. | S | W1–2 | — |

## 🟡 Q2 — Important, Not Urgent · SCHEDULE (the strategic core)
> The real work that builds the moat + first-capital pipeline. Sequenced deliberately.

| # | Initiative | Effort | Weeks | Owner-gated |
|---|---|---|---|---|
| 1 | **Prove the safety machinery on REAL data** — replay historical stress/adversarial fixtures through the *same* governance code; publish a reproducible "defenses-exercised" report. A monotonic 49/0-day, 0% drawdown curve with zero exercised defenses is a bigger liability than APY. | M | W3–4 | — |
| 2 | **Add the funnel's missing terminal** — go-live interest / allocator-notify capture on earn-defi (checkup graduates + UTM + /fundability readers all dead-end today). The only mechanism that converts trust → first-capital conversation. | M | W3–4 | ✅ legal + copy |
| 3 | **One public go-live-readiness surface** — wire pre_cutover_gate (16/16 money-path defenses) + cutover_scorecard (code-readiness% + owner-only blockers) together. Honest "what code proved vs what only the owner can do." | M | W3–4 | — |
| 4 | **Publish evidence-levels (L0–L6) trust page** + reconcile the 3.18%/3.4% RWA-floor doc drift. Cheapest durable-trust win; de-risks the APY ambiguity. | S | W3–4 | — |
| 5 | **Sync stale checkup self-description** to shipped reality (5 chains + approvals + leverage) — understating capability is a credibility hole for a "check us" brand. | S | W3–4 | — |
| 6 | **Checkup retention loop** — deterministic wallet-watch re-scan + material-change alert via `computeReportDelta` (already built). The single biggest PMF/return-visit lever; the product is 100% one-shot today. | L | W5–6 | — |
| 7 | **Checkup email report + alert delivery** — activate the existing Resend layer (only sends waitlist acks today). The notification channel that makes the watch loop valuable. | M | W5–6 | — |
| 8 | **Surface the DD-pack / data-room on /due-diligence** — verifier command + refusal-chain head + honest capacity. Ready-made first-conversation asset that leads with what we REFUSE, not APY. | M | W5–6 | — |
| 9 | **Capture inbound checkup→earn-defi UTM** — campaign-aware landings + persist utm_* to the beacon; a routed "idle stables" visitor sees a matching message, not a generic page. | M | W5–6 | — |
| 10 | **Harden checkup infra** — `/api/health` + Railway healthcheckPath + permalink durability (ephemeral disk 404s after redeploy); install site_freshness launchd backstop; restore-from-offsite drill. | S–M | W5–6 | ✅ Railway volume |
| 11 | **Draft the first design-partner / DAO-treasury pilot one-pager** — public-proof-only, refusal-led, honest capacity (~$64.8k/yr = 0.65% of $10M). The concrete first-AUM funnel. | M | W7–8 | — |
| 12 | **Dry-run the full LIVE_LAUNCH_RUNBOOK (inert)** + reconcile 26-vs-29-criteria / kill-switch doc drift, so T-day is proven green not discovered broken. | M | W7–8 | — |
| 13 | **Wire yield-quality + tail-risk into the live checkup report** (engine ships them; analyze.ts doesn't invoke them). Adds depth vs balance-only scanners. | M | W7–8 | ✅ RA sign-off |
| 14 | **Expand L2 KNOWN_SPENDERS registries** — cut "unknown" approval noise; pairs with the Etherscan-key unblock. | M | W7–8 | — |
| 15 | **Banded, evidence-tagged headline verdict** on the checkup report + sharper OG share card — instant legibility + cheapest organic top-of-funnel growth. | M | W7–8 | — |

## 🟢 Q3 — Urgent, Not Important · MINIMIZE / BATCH
| Initiative | Note |
|---|---|
| Bilingual RU/EN parity for the checkup UI | Widens reach but broad copy.ts work; batch after retention/approvals land. |
| Fix two RU-defaulting inline i18n scripts (packages/monitoring.astro) | Real polish bug (EN visitor sees RU on the money page); small, batch with next push. |
| Page-specific OG images for 4–5 flagship pages | Image busywork; only pays off behind the headline-verdict/share-card work. |
| Direct "Open the full tool ↗" nav link | Trivial; fold into any header edit. |

## ⚪ Q4 — Neither · DROP / DEFER past the 2 months
| Initiative | Why |
|---|---|
| Systemic low-contrast WCAG-AA pass (~479 uses) | Least needle-moving by every scout's rating; revisit under real institutional scrutiny. |
| Defer two `client:load` Astro islands (~265KB) | Pure perf cleanup, no north-star impact this window. |
| Raise checkup web coverage floor (55%→) | Engine is well-covered + CI gates exist; defer unless a retention regression surfaces. |

---

## 📅 8-Week Timeline

### Sprint 1 · W1–2 — *Unblock the blockers: protect the track, close credibility defects, green the fleet*
- Guard track continuity; fix aave_v3 → ≤40% T1 in the allocator; reconcile ONE headline APY (L3-tagged) everywhere; `/admin` noindex-ready + hand owner the CF-Access ask; deploy `com.spa.resilience` + retire dead agents → agent_health green.
- **Owner:** land ETHERSCAN_API_KEY + WALLET_REF_SALT; book first counsel consult.
- **Exit:** gap_monitor clean; allocator ≤40% T1 no DL-03 warn; one consistent evidence-tagged APY public; agent_health OVERALL green + resilience fresh (<48h); Etherscan key verified by curling a real whale's approvals section.

### Sprint 2 · W3–4 — *Prove the safety story + build the first-capital terminal*
- Public "defenses-exercised on real data" replay report; pre_cutover_gate + cutover_scorecard readiness surface; go-live interest-capture terminal (behind counsel/CF-Access); evidence-levels (L0–L6) page + RWA-floor doc reconcile; sync checkup self-description.
- **Exit:** safety report third-party-reproducible; readiness surface shows 16/16 + owner blockers honestly; interest-capture live + storing consented submissions safely; no conflicting APY/RWA number remains public.

### Sprint 3 · W5–6 — *Retention engine + diligence-ready proof (go-live window)*
- Wallet-watch re-scan + material-change alert loop; Resend report/alert email (double-opt-in); UTM continuation + campaign-aware landings; DD-pack on /due-diligence; checkup infra hardening + site_freshness backstop + restore-from-offsite drill.
- **Exit:** a worsening watched wallet triggers exactly one alert email; /due-diligence exposes the full verifier chain unprompted; inbound UTM visitors see a diagnosis-matched landing; permalinks survive redeploy; **go-live criteria hit 30/30 if the track matured on schedule.**

### Sprint 4 · W7–8 — *First-conversation assets + moat depth + T-day dress rehearsal*
- Pilot one-pager (public-proof-only, refusal-led); inert LIVE_LAUNCH_RUNBOOK dry-run + doc reconcile; yield-quality/tail-risk wired (post RA sign-off); L2 KNOWN_SPENDERS + banded headline verdict + OG card; batch the Q3 items.
- **Exit:** pilot one-pager has zero un-evidenced numbers; runbook dry-run green on every non-owner step + docs match the authoritative gate; checkup shows a legible banded verdict with far fewer L2 "unknown" approvals; owner holds a current list of exactly what only they can unblock.

---

## 👤 Owner-Only Actions (nothing downstream moves without these)
1. **ETHERSCAN_API_KEY** on the correct prod Railway service+env → re-lights the checkup's flagship (dark) approvals dimension. Verify by curling a real whale's approvals section.
2. **WALLET_REF_SALT** prod secret → gates the entire retention loop + interest-capture (safe durable keying).
3. **Cloudflare Access on `/admin`** (both sites) → closes the clearest security defect a reviewer finds.
4. **First counsel consult** (entity, paper-track disclosure/marketing limits, no-guarantee framing) + DefiLlama commercial-ToS question → the fail-closed legal gate before ANY external capital.
5. **Real off-machine backup dest** (2nd disk/NAS/S3) + `SPA_OFFSITE_DEST` → kills the single-host SPOF; makes the restore drill a TRUE DR proof.
6. **RA sign-off** on Exit-NAV haircuts + yield-quality (5 reference wallets) → converts "hypotheses" into calibrated risk numbers; unlocks the moat artifact.
7. **True cutover stack** — Gnosis Safe 2-of-3 custody (human signers), external audit of `spa_core/execution/`, legal/entity/terms for external capital. No code satisfies these (AI holds no keys, is never a signer).
8. **Decide the headline APY number** (~3.3% real vs annualized paper) + Railway volume for permalinks (or accept best-effort).

---

## ⚠️ Top Risks
1. **Track corruption** is the highest-consequence risk — one ad-hoc run against live `data/` resets the anchor and pushes go-live weeks out. The whole roadmap depends on continuity.
2. **Owner-gated critical path** — Etherscan key, WALLET_REF_SALT, CF Access, counsel, RA sign-off, custody/audit are all human-only; if they slip, ready code stalls.
3. **The realized edge is unproven** — sleeves read INSUFFICIENT_DATA, FixedCarry −247bps below floor, optimizer goes negative past ~$1M, honest capacity ~0.65% of the $10M target. **Go-live ≠ fundable-at-scale**; the pilot must lead with measurement/refusal, not yield.
4. **Zero exercised defenses on a monotonic real curve** is a credibility liability; the real-data replay must land or "we measure risk honestly" stays asserted, not demonstrated.
5. **Silent DR/fleet decay** — resilience 7d stale + agent_health CRITICAL now; a disk failure or dormant kill-rule pre-go-live is the worst failure mode.
6. **APY-story inconsistency** decays trust exactly as go-live traffic + first-LP diligence arrive; reconcile before outreach.
7. **Checkup ephemeral-disk permalink loss + no healthcheck** can silently break the public share/retention loop on any redeploy.

---

## Q1 Execution Log (2026-07-10)

**Q1-1 · Track continuity — VERIFIED (no code needed).** golive 27/29, 19 evidenced days, gap_monitor `ok`. The two open criteria are pure time to ~2026-07-21. Guard holds; nothing run against live `data/`.

**Q1-2 · Concentration "breach" — INVESTIGATED, false flag (no action).** aave_v3 is $40k = 50% of *deployed* but **40% of total capital** — and RiskPolicy measures concentration against total capital (`policy.py:183`) with a strict `>` operator, so exactly 40% is **compliant by design**. The optimizer is *supposed* to fill the best protocol to its 40% cap (`allocation_models.py:222`); go-live is not blocked on it (the 2 open criteria are time-gated, not concentration). Forcing a live rebalance to "fix" a non-breach right before go-live is riskier than the cosmetic "approaching-limit" note. No safe/valuable change.

**Q1-3 · APY story — MOSTLY DONE, one owner call.** The volatile-badge bug was already fixed (SPA-3, `7fd71ad9`): all surfaces read `paper_apy_pct` = stable evidenced **~4.10%**. Residual: `/packages` copy says "**~3.3% real**" (the conservative RWA-floor claim) next to the ~4.10% evidenced badge. Both are true but read as a mild conflict. **Owner decision:** headline the evidenced ~4.1%, or frame "~3.3% conservative floor · ~4.1% evidenced to date (variable)". Not changed unilaterally — it is the flagship public business number.

**Q1-4 · `/admin` de-index — DONE (code) / owner (lock).** All 6 admin pages emit `noindex, nofollow` (verified in `dist`) + `robots.txt` `Disallow: /admin`. **Owner action — Cloudflare Access:** CF dashboard → Zero Trust → Access → Applications → Add self-hosted → domain `earn-defi.com`, path `/admin*` → policy (allow your email/identity) → save. That is the real lock; noindex only keeps it out of search.

**Q1-5 · Resilience + agent_health — DONE (`62d678ef`).** New `com.spa.resilience` agent (every 6h, deploy-gate verified, live track untouched by hash) exercises R6/R7/R4 drills then the R8 rollup → `resilience_status.json` now **provably fresh** (was 7d stale). `tier1_digest`+`digest_weekly` retired (not firing; telegram-consolidation) → **agent_health CRIT 0, WARNING** (was CRITICAL). 50 `com.spa` agents.
- **RESOLVED (2026-07-10, `fcff45f0`):** the R7 restore-drill failure `anchors: broken at index 0` was REAL (fails on live too), root-caused to the rates_desk anchor ledger checkpointing the RE-BASED ring-buffer mirror head (breaks every producer write; 4 anchors orphaned from a defunct incarnation). Fixed: reset orphaned ledger → empty (archived) → verify_spa passes, restore-drill PASSES, resilience_status **OK**. verify_spa unchanged (a verifier tweak was gameable + broke a fabrication test); append_anchor flagged DORMANT-BY-DESIGN. Advisory sleeve, not money-path. See [[rates-desk-anchor-mirror-unsound]].
- **Owner/flag:** `com.spa.weekly_backup` is a WARNING ("never ran?") — left in place (backup = don't retire blindly); investigate vs the existing `daily_backup`. Real off-machine backup dest (`SPA_OFFSITE_DEST`) still owner-gated (offsite writes to a local stand-in → SPOF).

---

## Autonomous Q2/Q3/Q4 Ship Log (2026-07-10, self-driving loop 3537c8d7)

**Shipped:** Q2-1 defenses-exercised proof (`80773c6d`) + FUNDABILITY §3d (`56fbbb8c`) · Q2-3 readiness surface `/readiness`+`/api/readiness` (`aec143ef`) · Q2-5 checkup self-desc (`2fcdb40`) + copy.ts follow-up · Q2-8 verify-yourself on /due-diligence (`10b5b415`) · Q2-9 UTM campaign attribution (`b041f634`) · Q2-10 /api/health + Railway healthcheck (`811ae07`) · Q2-11 pilot one-pager (`db41ad36`) · Q2-12 runbook reconcile 24/26→29 + two-tier kill (`34eef4f1`) · Q2-6 retention alert core `isAlertWorthy` (`72c0aa0`) + delta teaser (`c0ca518`) · Q4 WCAG-AA contrast pass /30→/50 /40→/55 across 26 pages (`4594339e`).
**Verified already-done (no rework):** Q2-4 evidence-levels (methodology) · Q2-13 tail-risk scanned live + yield-quality honest data-gap (fail-closed; full populate needs yield-source classification + RA) · Q2-15 OG image shows posture/verdict + banded posture badge · Q3 RU-default i18n (`2764056a`).
**Owner-gated (mechanism built/flagged):** Q2-2 funnel terminal (legal) · Q2-6 wallet-watch STORE + scheduler + delivery (WALLET_REF_SALT durable keying + RESEND — email.ts already graceful no-op) · Q2-7 email (RESEND).
**Remaining clean-but-large / skipped-with-reason:** Q4 coverage-floor RATCHET (roadmap Q4 says defer unless a retention regression surfaces) · Q2-14 KNOWN_SPENDERS (needs REAL verified L2 spender addresses — cannot fabricate per AVOID-list; pairs with the owner Etherscan-key unblock) · RWA-floor 3.18/3.4 reconcile (docs already ~3.4% consistent).
**Finding fixed:** restore-drill/anchor — re-based mirror anchoring unsound; orphaned ledger reset; verify_spa/restore-drill/resilience all green (`fcff45f0`).

### Ship Log — continuation (loop `3537c8d7`, 2026-07-10 PM)
Later autonomous firings CLOSED the items previously parked as "clean-but-large":
- **Q3 bilingual checkup UI — DONE.** 134 `data-ru` across the whole human-readable UI (hero/forms/all report sections/permalink) + lang-aware client forms (`dc_lang`+`dc:lang`). Only interpolated data-values + the counsel-gated legal disclaimer stay EN by design.
- **Q3 page-specific OG cards — DONE (`9bef9a3`).** `/verify` ("don't trust us, check us" · SHA-256 in-browser), `/compare`, `/sample-report` — code-generated via next/og (NO design assets; the "need design assets" note was wrong). `/check/[reportId]` OG already existed. Copy mirrors each page's own heading (no overstatement).
- **Q3 direct-nav-link — already present** as the persistent `Dashboard↗` CTA in `SiteHeader.astro` (not redundant-skip — it was already shipped).
- **Q3 RU-default i18n — CONFIRMED fixed** (`packages.astro`/`monitoring.astro` inline scripts default `|| 'en'`).
- **Q4 island-defer — DONE (`1b6488a5`).** Academy `Quiz` + `RiskClassifier` islands `client:load`→`client:visible` (below-fold, hydrates immediately if visible → zero behavior risk). `ModuleProgress` correctly left `client:load` (top-of-page). Dashboard/monitoring/board islands are above-fold primary content → left `client:load` on purpose (flipping would delay first paint).
- **Q4 fail-closed coverage — DONE (`383bd42`).** Test for the prices-unavailable branch in `analyzeWallet`: no price source → 200 balances-only, `pricesUnavailable:true`, positions keep their `price_usd` gap (never guessed). 266 web tests pass.

**Net:** the entire cleanly-doable Q2+Q3+Q4 roadmap is now shipped and verified in code. Q3 + Q4 are COMPLETE. What remains is strictly owner-gated (Etherscan key · WALLET_REF_SALT · CF Access · counsel · RA sign-off · offsite dest · custody/audit · headline-APY decision) plus Q2-14 (needs verified addresses, honesty-blocked). Mechanisms for every gated item are built and flagged. Loop stays alive as watchdog.
