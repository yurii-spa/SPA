# SPA + DeFi Checkup — 2-Month Development Roadmap (Eisenhower Matrix)

**Generated:** 2026-07-10
**Scope:** `earn-defi.com` (SPA landing/Astro/CF Pages · `spa_core/*` runtime · agents/DR) + `checkup.earn-defi.com` (DeFi Checkup, `yurii-spa/defi-checkup` repo)
**Horizon:** 8 weeks (2026-07-10 → 2026-09-04), four fortnightly sprints
**Supersedes:** `docs/ROADMAP_2MONTH_EISENHOWER.md` (prior plan — largely shipped/owner-gated). This is a fresh forward plan; already-shipped work is NOT re-listed.
**Companion (checkup report quality):** `docs/CHECKUP_REPORT_10OF10.md` — triage of the "10/10 decision-ready report" spec vs engine+invariants, with a prioritized honest build queue (P1 cross-position shared-oracle/bridge dependency; P1 decision-ready quantified headline + Critical/Important/Watch; P2 plain-language + fact/interpretation; P2 client Risk-Policy personalization) + a freemium split (free true-partial, paid depth, critical risk never paywalled). The loop pulls these into Q2 checkup-depth work.

---

## 1. North Star & How Urgency-vs-Importance Was Judged

**North star chain:** honest evidenced paper track (19/30 → 30/30) → **go-live cutover** → **first non-custodial design-partner / first external AUM** → **durable measurement/refusal moat**, with **DeFi Checkup as recurring top-of-funnel** feeding qualified intent into that chain.

**The single hardest honest truth this plan is built around:** the measurement/refusal engine is world-class, but **the desk does not beat the RWA floor at fundable scale** — every sleeve is `INSUFFICIENT_DATA` on realized data, FixedCarry is −247bps realized, the optimizer's +1.08pp is a $100k artifact that goes negative past ~$1M, and the combined book clears only **~$34k/yr above floor** (0.34% of the $10M thesis). Therefore the fundable product is **measurement + refusal (a trust/underwriting moat), not a rate**. Every Q2 initiative either (a) hardens that moat into a number a funder can underwrite, or (b) proves/demonstrates scale rather than asserting it, or (c) builds the funnel that converts trust into a first conversation.

**Judging rubric:**
- **Urgent** = time-critical (the 11-day go-live window, cutover-day trust), blocking a downstream link in the chain, or decaying (stale blog, dark approvals dimension eroding checkup credibility today).
- **Important** = moves the north-star chain materially (track→go-live→first-AUM→moat). A thing can be urgent-but-trivial (batch it, Q3) or important-but-patient (schedule it, Q2).
- **Discipline:** pure *waiting* (the 11 remaining track days) is not a code task — it sits in **Q1-as-guard** (protect continuity, do nothing that touches live `data/`). **Owner/legal/custody blockers are NOT in the code quadrants** — they live in §8 Owner-Only, because code can only *track* them, not *do* them.

---

## 2. 🔴 Q1 — Urgent + Important (DO FIRST, small & decisive)

These are small, unblock-the-chain, or protect the single most fragile asset (the track + cutover trust + checkup credibility). Ship in W1–W2.

| # | Initiative | File / Subsystem | Effort | Weeks | Owner-gated |
|---|---|---|---|---|---|
| Q1-1 | **Protect track continuity (guard-only, do nothing risky)** — freeze all ad-hoc cycle/backtest runs against live `data/`; verify daily cycle heartbeat fresh each day 19→30 | `spa_core/paper_trading/cycle_runner.py`, `data/equity_curve_daily.json`, `PAPER_REAL_START_DATE` guard | S | W1–8 | No |
| Q1-2 | ✅ SHIPPED 2026-07-11 (transient <48h gap→WARN; 3 artifact-fails already PASS) — **Reconcile `golive_preflight` noise** — separate genuine blockers from 3 artifact-fails (synthetic-6%-curve drawdown, `sprint_log_md`/`cycle_runner_imports` doc/env drift) so preflight agrees with the authoritative 27/29 gate | `scripts/golive_preflight*`, `spa_core/paper_trading/golive_checker.py` | M | W1 | No |
| Q1-3 ✅ SHIPPED 2026-07-11 (plist persisted to installer + gate-validated + loaded exit 0; agent_health coverage) — | **Fix orphaned `com.spa.resilience` agent** — persist its plist to `~/Library/LaunchAgents/`, add to `install_all_agents.sh`, bring under `agent_health` coverage (DR proof-chain must survive reboot) | `scripts/*.plist`, `install_all_agents.sh`, `agent_health_monitor.py` | S | W1 | No |
| Q1-4 | **Activate dormant anchor ledger** — `data/rates_desk/anchors.jsonl` is 0 bytes; write periodic append-only anchors so tamper-evidence goes from within-window → all-time checkable | `spa_core/strategy_lab/rates_desk/` (anchor writer), `scripts/verify_spa.py` | S | W1 | No |
| Q1-5 | **Land `ETHERSCAN_API_KEY` on prod (checkup)** — approvals is the #1 drain-risk signal; Alchemy `eth_getLogs` fromBlock:0 fallback is fragile on whales → real users see "not scanned" | `apps/web/src/lib/approvals.ts` (verify path once key lands) | S | W1 | **Yes** — owner sets key on correct Railway service+env + redeploy |
| Q1-6 | **Fix volatile `/packages` LIVE-APY badge** — reads `apy_today_pct` (single-day annualized, swings past 2–6% band, contradicts "Real ~3.3%"); switch to stable track-to-date figure pending owner's canonical number | `scripts/generate_track_snapshot.py:121`, `landing/src/pages/packages.astro` | S | W1 | **Yes** — owner picks canonical public business number |
| Q1-7 | ✅ SHIPPED 2026-07-11 (data-track now on all 7 proof pages) — **Conversion instrumentation on proof pages** — add `data-track` to `/fundability`, `/due-diligence`, `/track-record`, `/verify`, `/exit-nav`, `/refusals`; funnel is currently unmeasurable at the bottom | `landing/src/pages/*.astro`, `spa_core/api/routers/analytics.py` | S | W2 | No |
| Q1-8 | **Self-clearing gap-recovery state** — clear stale `2026-06-30 cycle_ran_but_gap_persists` record; add auto-clear rule so a resolved gap never leaves a scary artifact on the readiness surface | `spa_core/paper_trading/gap_monitor.py`, `data/gap_monitor.json` | S | W2 | No |
| Q1-9 | **Owner-only blocker status tracker** (custody/audit/legal/HSM-key) — code surfaces which of the 4 true go-live gates are open so owner runs procurement in parallel with remaining track days | `spa_core/execution/readiness_audit.py`, `data/owner_blockers.json`, `landing/src/pages/readiness.astro` | S | W2 | Partial — code tracks; owner must actually procure |
| Q1-10 | **Escalate stale/failed `resilience_status` into `agent_health` WARNING** — a rotting DR posture currently only writes JSON nobody is paged on | `resilience_status.py`, `agent_health_monitor.py` | S | W2 | No |
| Q1-11 | **Dedicated agent for `golive_checker` + `pre_cutover_gate` freshness** — readiness verdict + money-path proof always fresh & dated, not a daily-cycle side-effect | new `com.spa.golive_freshness` plist + wrapper, `pre_cutover_gate.py` | S | W2 | No |
| Q1-12 | **Finding-aware checkup→earn-defi routing** — deep-link on actual diagnosis (refusal-heavy→`/refusals`, tail-risk→`/risk`, clean-low-yield→`/packages`) with UTM tags; turns free scan into segmented top-of-funnel | `ReportDashboard.tsx` (checkup repo), `landing` UTM capture | S | W2 | Partial — checkup is separate owner-deploy repo |

---

## 3. 🟡 Q2 — Important, Not Urgent (SCHEDULE — the large strategic core)

This is the bulk of the 8 weeks: the moat-hardening, funnel-completion, checkup-depth, and pilot-machinery work that moves the north star but is patient. Sequenced across W3–W8.

| # | Initiative | File / Subsystem | Effort | Weeks | Owner-gated |
|---|---|---|---|---|---|
| Q2-1 | **N-book capacity aggregator** — deterministic model showing achievable above-floor $ as gated-carry book-count grows (distinct maturities/venues, correlation-haircut per `portfolio_capacity.py`); converts "$250k artifact" objection into a measured scale curve | `spa_core/strategy_lab/rates_desk/`, new `n_book_capacity.py`, `capacity.json` | M | W3–4 | No |
| Q2-2 | ✅ SHIPPED 2026-07-11 first increment (--replay re-derives verdicts; 2000/2000; site-surfaced) — **Independent `--replay` verifier** — third party re-derives REFUSED/APPROVED verdicts from published Pendle history + pinned calibration, not just re-hashes them; strongest possible measurement-moat proof | `scripts/verify_spa.py` (add replay mode), `rates_desk` refusal engine | M | W3–4 | No |
| Q2-3 | **Activate wallet-watch retention loop end-to-end (checkup)** — wire built `watchlist.ts`/`computeReportDelta`/`alertPolicy.ts` core to opt-in UI + add-watch API route + scheduled re-scan + alert email; THE #1 PMF lever (run-once tool → monitoring habit) | `apps/web` (new route+UI), `watchlist.ts`, `reportDelta.ts`, re-scan cron | L | W3–5 | **Yes** — `WALLET_REF_SALT` + `RESEND_API_KEY` on prod Railway + cron provisioned |
| Q2-4 | **Funnel terminal: honest expression-of-interest surface** — the missing last mile; convinced fundability/checkup graduates currently dead-end into a proof loop or bare `mailto`. "Request a conversation / research access", NOT an offer | new `landing/src/pages/pilot.astro` terminal section | M | W4–5 | **Yes** — owner+legal approve exact non-solicitation copy |
| Q2-5 | **Interest-capture backend endpoint** — stdlib+FastAPI append-only PII-minimal JSONL sink mirroring `analytics.py`; intent durably recorded, readable in `/admin` | new `spa_core/api/routers/interest.py`, `data/interest.jsonl` | S | W4 | **Yes** — owner decides PII/storage policy (brand is zero-PII) |
| Q2-5b| **Avoided-loss refusal P&L ledger** — per historical stress event (ezETH/rsETH depegs Aug-24/Oct-25/Apr-26), price what a naive book WOULD have lost holding refused toxic PTs vs carry foregone; makes refusal moat a P&L number, not a philosophy | new `spa_core/strategy_lab/rates_desk/refusal_value.py`, `FUNDABILITY.md §2d` | M | W5–6 | No |
| Q2-6 | **Coverage/blind-spot meter (checkup)** — prominent "we checked X% of your value, here's what's dark" banner; turns `coverageGaps` honesty invariant into a trust headline + deeper-scan upsell | `packages/riskdesk/src/report/assemble.ts`, `ReportDashboard.tsx` | M | W4–5 | No |
| Q2-7 | **Public `/pilot` page + downloadable DD pack** — `PILOT_ONE_PAGER.md` lives only in repo; live always-fresh guard-checked surface (like `/fundability`) lets warm intros self-serve honest story + reproducible proof | `landing/src/pages/pilot.astro`, `docs/PILOT_ONE_PAGER.md`, no-unsourced-number guard | M | W5–6 | No |
| Q2-8 | **Design-partner pilot pipeline tracker (CRM-lite)** — `data/pilot/` prospect list + stage + last-touch + DD-artifact-sent state; mechanical difference between a plan and a first-AUM funnel | new `spa_core/pilot/`, `data/pilot/`, `/admin` view | M | W6 | No |
| Q2-9 | **One-command hostile-reviewer DD bundle** — `scripts/build_dataroom.py` emits timestamped self-verifying zip (verifier + full-chain curl + `DD_PACK` + refusal log); makes "check us" turnkey | new `scripts/build_dataroom.py`, `generate_dd_pack.py`, `verify_spa.py` | S | W6 | No |
| Q2-10 | ✅ SHIPPED 2026-07-11 (verify_spa.py --offline: checksummed frozen snapshot, +6 tests, site-surfaced) — **Self-contained reproducible DD data snapshot** — frozen checksummed dataset (decision log + Pendle history + calibration + expected hashes) a funder clones & replays OFFLINE; reproducibility no longer depends on live API | new `data/dd_snapshot/`, `verify_spa.py --offline` | M | W6–7 | No |
| Q2-11 | **Uniswap V3 LP / concentrated-liquidity detection (checkup)** — largest DeFi risk surface (out-of-band ranges, IL) is entirely invisible; cover dominant AMM's NFT positions, fail-closed | `apps/web/src/lib/` new `positions.ts`, `recognizeProtocolPositions` | L | W5–7 | No |
| Q2-12 | **Extend leverage scan to Morpho Blue + Fluid (checkup)** — `lending.ts` covers only Aave-family+Compound-V3; undetected leverage is highest-severity blind spot; "unreachable → data gap, never zero" | `apps/web/src/lib/lending.ts` | M | W5–6 | No |
| Q2-13 | **Extend defenses-exercised to RTMR sensors + refusal gate on REAL data** — replay peg/tvl/oracle/liquidity sensors + reaction ladder over Aug-24/Oct-25/Apr-26 events with asserted de-risk output; extends "brakes provably work" from paper-kills to live monitoring plane | `scripts/defenses_exercised_report.py`, `spa_core/monitoring/sensors/` | M | W6–7 | No |
| Q2-14 | **Auto-generated research changelog from live pipeline** — blog is hardcoded 3-post array frozen 2026-06-20; weekly track-record + refusal digest auto-published gives crawlers a re-index reason & the track a public heartbeat | `landing/src/pages/blog/`, new generator agent, track/refusal data | M | W4–5 | No |
| Q2-15 | **RSS/Atom feed + BlogPosting/Article JSON-LD** — `robots.txt` welcomes GPTBot/ClaudeBot/PerplexityBot but there's no feed/Article schema; cheapest discoverability multiplier, feeds AI answer engines | `landing/src/pages/rss.xml.ts`, `Layout.astro` schema | S | W4 | No |
| Q2-16 | **Programmatic per-refusal / per-protocol SEO pages** — hash-chained refusal log is the unique honest asset trapped in one `/refusals` view; templated indexable pages capture "is ezETH safe" / "Pendle PT exit liquidity" long-tail nobody else can answer | new `landing/src/pages/refusals/[id].astro`, `protocols/[id].astro` | M | W6–7 | No |
| Q2-17 | **Days-to-verdict countdown on realized carry track** — `FUNDABILITY.md §2` shows every sleeve `INSUFFICIENT_DATA`; harden `com.spa.rates_desk_paper` continuity + surface per-sleeve countdown to first above-floor verdict | `spa_core/strategy_lab/forward_analytics.py`, `paper_rates`, `/fundability` | S | W5 | No |
| Q2-18 | **Dated evidenced-track ledger (19→30) with per-day dd/return** — reproducible day-by-day artifact so the 30-day claim is independently verifiable, not just a count; hardens the last binding go-live blocker into a moat artifact | new `spa_core/paper_trading/track_ledger.py`, `data/track_ledger.json`, `readiness.astro` | M | W3 | No |
| Q2-19 | **Non-custodial advisory pilot workflow** — the product a first partner actually uses: how the desk hands an evidence-tagged recommendation + refusal log a partner executes on their OWN Safe (AI never signs); operational loop, not just narrative | new `spa_core/pilot/advisory_loop.py`, `docs/42`, `execution/` (unsigned drafts only — never import into read-only) | L | W7–8 | No |

---

## 4. 🟢 Q3 — Urgent, Not Important (MINIMIZE / BATCH)

Time-sensitive or noisy but low north-star leverage — batch into a single housekeeping pass, don't let them consume strategic weeks.

| # | Initiative | File / Subsystem | Effort | Weeks | Owner-gated |
|---|---|---|---|---|---|
| Q3-1 | **Reconcile `weekly_backup` WARNING** — retire it (redundant with `daily_backup`) or repair plist so `agent_health` reaches clean all-OK; kills alert-fatigue before go-live | `scripts/daily_backup.py`, `com.spa.weekly_backup.plist` | S | W3 | No |
| Q3-2 | **Fleet-parity self-check** — `tier1_governance`/`tier1_digest`/`checkpoint-7day` loaded-not-installed, resilience reverse; deterministic assert declared-fleet == running-fleet (like doc-drift guard) | `install_all_agents.sh`, new `scripts/fleet_parity_check.py` | M | W3 | No |
| Q3-3 | **Complete `KNOWN_SPENDERS` + per-chain routers (ARB/OP/POLY, checkup)** — those chains only match cross-chain-canonical spenders → Uniswap/Aerodrome/Camelot routers classify "unknown", inflating noise; deterministic registry work improving signal-to-noise | `apps/web/src/lib/approvals.ts` KNOWN_SPENDERS | M | W4 | No |
| Q3-4 | **Consecutive-ready-days stability tracker on readiness page** — `consecutive_ready_days=0`; surface rolling ready-streak (runbook wants 7 sustained) → makes remaining waiting a visible de-risking proof | `readiness.astro`, `golive_checker.py` | S | W3 | No |
| Q3-5 | **Kill-switch latency + drill-evidence artifact** — `kill_switch_drill.py` exists but no dated latency artifact wired to readiness; record measured latency + last-drill date → emergency-stop auditable | `scripts/kill_switch_drill.py`, `resilience_cycle.py`, `readiness.astro` | S | W3 | No |
| Q3-6 | **Scheduled `kill_switch_drill` in `resilience_cycle`** — folds the money-path brake (sandboxed, de-risk-only) into the provably-exercised 6h list alongside offsite/restore/fleet | `scripts/resilience_cycle.py` | S | W3 | No |
| Q3-7 | **Coherence pass: dedupe risk/proof page sprawl** — ~40 footer links incl. overlapping `/risk`, `/risk-disclosure`, `/disclaimer`, `/trust`, `/security` + 5 proof surfaces; consolidate to one linear "the case → terminal" spine, reduce leakage | `landing/src/layouts/Layout.astro` footer, page consolidation | M | W7 | No |
| Q3-8 ✅ SHIPPED 2026-07-11 (status-capture JSON done; login-agent mechanism built, owner bootstraps via gate) — | **Post-reboot verify auto-trigger + status capture** — login-triggered `verify_fleet_after_reboot.sh` that writes a status JSON → "probably recovered" becomes proven/auditable | `scripts/verify_fleet_after_reboot.sh`, login LaunchAgent | M | W4 | No |
| Q3-9 | **Farcaster Frame + richer verifiable OG risk-card (checkup)** — `ShareButton` only copies a permalink; "check your wallet" Frame + hash-verifiable OG card = organic loop in DeFi-native channels, non-custodial-safe | `check/[reportId]/opengraph-image.tsx`, new Frame route | M | W7 | No |

---

## 5. ⚪ Q4 — Neither Urgent Nor Important (DROP / DEFER)

| # | Initiative | Verdict | Why |
|---|---|---|---|
| Q4-1 | **Solana / Sui / BSC / zkchain balance coverage (checkup)** | DEFER to post-go-live | Widens TAM but the 5 EVM chains cover the fundable-partner segment; new RPC surface + gap-contract work is L-effort for low north-star leverage now. Revisit once retention loop (Q2-3) proves the habit. |
| Q4-2 | **Sanctioned/scam-token registry dimension (checkup)** | DEFER | High-share finding but **owner-gated on a licensed attacker/scam registry** (data-licensing decision) — cannot be built fail-closed & non-fabricated without the source. Blocked, not droppable. |
| Q4-3 | **Second-host / warm-standby (break single-host SPOF)** | DESIGN-ONLY now, infra DEFER | Real answer to acknowledged SPOF & an allocator will ask — but **owner budget + custody/security review gated**, and premature before any real capital. Ship the *runbook/topology doc*; defer the infra spend until first-AUM is in sight. |
| Q4-4 | **Second independent depth source for exit-NAV cross-check** | DEFER | Hardens the most load-bearing input, but L-effort keyless-RPC pool-reserve work; the `--replay` verifier (Q2-2) + anchor ledger (Q1-4) buy more trust per hour now. Schedule for month 3. |
| Q4-5 | **Buyer-intent comparison/education content ("best stablecoin yield 2026")** | DEFER | Captures commercial-intent search but L-effort content authoring competes with the auto-changelog (Q2-14) which reuses live data for near-zero marginal cost. Let programmatic SEO (Q2-16) prove the channel first. |
| Q4-6 | **Waitlist nurture drip sequence** | DEFER | Low urgency + **owner-gated on email infra/consent-scope**; the wallet-watch alert email (Q2-3) already lands the transactional-email plumbing — reuse it later rather than a parallel marketing stack. |
| Q4-7 | **Campaign-aware landing routing (UTM→content switch)** | DEFER to W8+ | Nice conversion lift but instrumentation (Q1-7) + funnel-stage view must exist FIRST to know which campaigns even warrant custom heroes. Data-before-optimization. |
| Q4-8 | **Capacity-honesty standalone public one-pager** | FOLD into Q2-1/Q2-7 | The per-book→aggregate ceiling belongs inside the N-book aggregator output surfaced on `/pilot` — a separate page is sprawl the coherence pass (Q3-7) would just re-merge. |

---

## 6. 📅 8-Week Timeline — Four Fortnightly Sprints

### Sprint 1 · W1–W2 (2026-07-10 → 07-24) — "Green the gate, guard the track, stop the bleeding"
**Goal:** Enter the go-live window (~07-21) with a trustworthy readiness surface, a surviving DR proof-chain, and checkup's credibility restored. Nothing that risks the live track.
- **Tasks:** Q1-1 (continuity guard, all-sprint), Q1-2 (preflight reconcile), Q1-3 (resilience agent persist), Q1-4 (anchor ledger activate), Q1-8 (gap self-clear), Q1-10 (DR→agent_health escalate), Q1-11 (golive freshness agent), Q1-7 (proof-page instrumentation), Q1-12 (finding-aware checkup routing).
- **Owner actions:** Q1-5 (set `ETHERSCAN_API_KEY` on prod Railway), Q1-6 (pick canonical public APY number), Q1-9 (start custody/audit/legal/HSM procurement in parallel).
- **Exit criteria:** `golive_preflight` shows only the 2 genuine time-gated PENDINGs (zero artifact-fails); `com.spa.resilience` present in `~/Library/LaunchAgents/` + installer + agent_health; `anchors.jsonl` non-empty and `verify_spa` reports anchors length > 0; checkup approvals dimension substantive on a whale test wallet; `/packages` badge stable & within band; every proof page emits `data-track`.

### Sprint 2 · W3–W4 (07-24 → 08-07) — "Prove scale & replayability; wake the funnel & the blog"
**Goal:** Convert the "edge is a $100k artifact" objection into a measured scale curve, make refusals independently replayable, and turn on the retention loop + content heartbeat. (Track hits 30/30 ~07-21 → **owner cutover decision live this sprint** — see §8.)
- **Tasks:** Q2-1 (N-book capacity aggregator), Q2-2 (`--replay` verifier), Q2-18 (dated track ledger 19→30), Q2-3 START (wallet-watch loop), Q2-15 (RSS + Article JSON-LD), Q2-14 START (auto-changelog), Q2-5 (interest-capture endpoint), Q3-1/Q3-2/Q3-4/Q3-5/Q3-6 (agent/DR housekeeping batch), Q3-3 (KNOWN_SPENDERS), Q3-8 (reboot verify capture).
- **Owner actions:** provision `WALLET_REF_SALT` + `RESEND_API_KEY` + re-scan cron (unblocks Q2-3); **retain crypto securities counsel** (hard gate — must start now); approve interest-endpoint PII policy.
- **Exit criteria:** N-book capacity curve published showing above-floor $ vs book-count with correlation haircuts; `verify_spa --replay` re-derives refusal verdicts from published data with matching outputs; RSS live + validated + Article schema on posts; auto-changelog agent shipping first weekly digest; agent_health all-OK (no `weekly_backup` WARNING); fleet-parity check green.

### Sprint 3 · W5–W6 (08-07 → 08-21) — "Deepen checkup, quantify the refusal moat, build pilot machinery"
**Goal:** Make checkup's diagnostic genuinely deep (LP + Morpho/Fluid + coverage meter) and make the refusal moat a P&L number; stand up the pilot funnel terminal + tracker + DD bundle.
- **Tasks:** Q2-11 (Uniswap V3 LP), Q2-12 (Morpho/Fluid leverage), Q2-6 (coverage meter), Q2-5b (avoided-loss refusal ledger), Q2-4 (funnel terminal), Q2-7 (`/pilot` page), Q2-8 (pilot CRM-lite), Q2-9 (DD bundle export), Q2-10 START (offline DD snapshot), Q2-17 (days-to-verdict countdown), Q2-16 START (programmatic SEO pages), Q2-3 FINISH (retention loop live + first alert fires).
- **Owner actions:** approve funnel-terminal non-solicitation copy (legal); confirm DefiLlama commercial-ToS/data-licensing stance; name Gnosis Safe 2-of-3 signers.
- **Exit criteria:** checkup detects a live Uniswap V3 position + a Morpho/Fluid borrow on test wallets fail-closed; coverage meter renders "%-of-value scanned" headline; refusal P&L ledger prints avoided-loss $ per 2024–2026 stress event; `/pilot` live & guard-checked; `build_dataroom.py` emits a self-verifying zip; wallet-watch alert email delivered end-to-end.

### Sprint 4 · W7–W8 (08-21 → 09-04) — "Close loops: advisory product, harden monitoring proof, coherence & distribution"
**Goal:** Ship the actual non-custodial advisory loop a first partner uses, extend the "brakes provably work" story to the live monitoring plane, and clean the funnel into one linear case with organic distribution.
- **Tasks:** Q2-19 (non-custodial advisory workflow), Q2-13 (defenses-exercised on RTMR + real-data refusals), Q2-16 FINISH (per-refusal/per-protocol pages indexed), Q2-10 FINISH (offline DD snapshot published), Q3-7 (page-sprawl coherence pass → linear spine), Q3-9 (Farcaster Frame + verifiable OG card).
- **Owner actions:** finalize Gnosis Safe topology + non-AI signer runbook sign-off; decide second-host/SPOF budget (Q4-3 design → infra); authorize social accounts for distribution seeding.
- **Exit criteria:** advisory loop produces an evidence-tagged, refusal-annotated **unsigned** recommendation a partner could execute on their own Safe (AI never signs — no `execution/` import into read-only code); RTMR sensors + reaction ladder replay asserts de-risk output over 3 real stress events; footer consolidated to a single "the case → terminal" spine; a first hostile-reviewer DD bundle handed to a warm intro; Farcaster Frame renders a hash-verifiable risk card.

---

## 7. 👤 Owner-Only Actions (the human-only critical path)

These CANNOT be code-done. They gate first-AUM downstream of everything above. Start the legal + custody items **in W1–W2, in parallel with the remaining track days** — they have the longest lead times.

| Priority | Owner action | Gates / Unblocks | Start by |
|---|---|---|---|
| 🔴 P0 | **Retain crypto securities counsel → pre-outreach legal memo + entity decision** (Delaware LLC vs ES-SL/AIFMD-sub-threshold vs Cayman; `LEGAL_STRUCTURE_v1.md`) | Invariant E-18 (`docs/42`) — absolute prerequisite for ANY external-capital conversation; gates the funnel terminal copy (Q2-4) and every pilot ask | W1 |
| 🔴 P0 | **Pick the canonical public APY business number** (stable track-to-date vs relabel "today" vs reconcile 3.3%-vs-7%) | Q1-6, and every first-capital conversation opening on a defensible figure | W1 |
| 🔴 P0 | **Set `ETHERSCAN_API_KEY` on correct prod Railway service+env + redeploy** | Q1-5 — checkup approvals credibility (the #1 drain signal) | W1 |
| 🟠 P1 | **Commission external audit of `spa_core/execution/`** (Trail of Bits / OpenZeppelin / Spearbit) — code will draft the RFP scope + attestation schema for you | `readiness_audit.check_*` → `ready_for_live`; `external_audit_attestation.json` | W2 |
| 🟠 P1 | **Provision custody: Gnosis Safe 2-of-3, name 3 human signers, migrate signing key to HSM/MPC** (AI never a signer) | `check_custody_connected` + `check_multisig_control`; the single hardest go-live gate | W2 |
| 🟠 P1 | **Provision retention infra:** `WALLET_REF_SALT` + `RESEND_API_KEY` on prod Railway + re-scan cron | Q2-3 — the #1 checkup PMF lever | W3 |
| 🟠 P1 | **Wire real `SPA_OFFSITE_DEST`** (NAS mount / cloud bucket / rsync target) → flip `is_real_remote:true` | Backups actually survive host loss before real AUM | W3 |
| 🟠 P1 | **Create off-host dead-man's-switch account** (healthchecks.io/cronitor) + provide ping URL via Keychain | External observer for the single-host SPOF | W3 |
| 🟡 P2 | **Approve funnel-terminal non-solicitation copy** (request-a-conversation / research-access framing, NOT an offer) + interest-endpoint PII policy | Q2-4, Q2-5 public ship | W5 |
| 🟡 P2 | **Confirm/obtain DefiLlama commercial data license / ToS clearance** for external-facing DD_PACK / `/pilot` / DFB Data API | Latent legal/reputational landmine at first AUM | W5 |
| 🟡 P2 | **THE CUTOVER (day-0):** sign the dated checklist binding `pre_cutover_gate` 16/16 → owner-only blockers all-clear → flip `SPA_EXEC_ARMED` / unlock `LiveTradingGate` | Go-live itself — only after 30/30 track AND all P0/P1 above are met | when ready |
| 🟢 P3 | **Authorize social accounts + community seeding**; decide second-host/SPOF budget | Distribution (Q3-9) + SPOF remediation (Q4-3) | W7–8 |

---

## 8. ⚠️ Top Risks

1. **Unproven edge at fundable scale (the defining risk).** Combined book clears only **~$34k/yr above floor**; 0/11 sleeves beat the floor on realized data; optimizer edge goes negative past ~$1M. A sophisticated LP finds this in minutes. **Mitigation:** lead every conversation with the **measurement/refusal moat, not the rate** (Q2-5b avoided-loss P&L, Q2-1 honest capacity curve, Q2-2 replay proof, Q3-7/Q2-7 crisp framing). Do NOT let the funnel terminal (Q2-4) open on a rate claim.

2. **Track-continuity fragility.** A single missed daily cycle or an ad-hoc run mutating live `data/` (a documented hazard that corrupted the track on 2026-06-25) resets the 30-day countdown and blows the go-live window. **Mitigation:** Q1-1 guard is non-negotiable; run all dev/QA in sandbox; `PAPER_REAL_START_DATE` guard enforced.

3. **Single-host SPOF with capital deployed.** Everything — `daily_cycle`, apiserver, cloudflared, RTMR, ~50 agents — lives on one Mac mini; every monitor runs on the host it monitors. A power/network loss is a silent unbounded outage. **Mitigation:** Q1-3 (DR chain survives reboot), off-host dead-man's-switch (§8 P1), real offsite dest (§8 P1), warm-standby *design* now (Q4-3) before capital.

4. **Owner/legal critical path is un-started and long-lead.** Legal memo, external audit, custody/HSM are hard fail-closed gates that code can only *track*. If they don't start in W1–W2, they — not the track — become the binding go-live blocker. **Mitigation:** §8 P0/P1 kicked off in parallel with the 11 remaining track days; Q1-9 tracker keeps them visible.

5. **Funnel terminal legal exposure.** The funnel is currently safe *because* it never solicits capital; any interest-capture surface that reads as an offer jeopardizes the honesty moat and the go-live path. **Mitigation:** Q2-4 copy is owner+legal-gated (§8 P2); ship instrumentation (Q1-7, pure code, no gate) first; frame strictly as "request a conversation".

6. **Checkup credibility decay right now.** With `ETHERSCAN_API_KEY` unset, the approvals dimension is dark/fragile for real (whale) wallets — the product's #1 differentiator silently degrades on exactly the users worth converting. **Mitigation:** §8 P0 (owner sets key W1); Q2-6 coverage meter turns remaining blind spots into an honest headline rather than a silent gap.

7. **Deploy-verification blind spots (recurring institutional failure mode).** Prior incidents: CF prebuild exit-1 froze the whole site for days; untracked-dir collapse in API-push lists served a 200-OK 404 all day. Any new page (Q2-4/7, Q2-16, RSS) risks a silent non-deploy. **Mitigation:** verify deploys by real content + Actions run conclusion (never curl status); recursive git-tree diff local↔origin before trusting a push; keep freshness checks WARN-ONLY unless `STRICT_SNAPSHOT_FRESHNESS=1`.

8. **Invariant erosion under delivery pressure.** Fast fan-out risks slipping an LLM into risk/exec/monitoring, a fabricated APY/address, a non-atomic write, or a non-stdlib runtime import. **Mitigation:** every code change honors — deterministic + fail-closed, no LLM in risk/exec/monitoring/kill, non-custodial (AI never signs, `execution/` never imported into read-only code), no fabricated APY/TVL/addresses (evidence levels L0–L6), `atomic_save` only, stdlib-only runtime, **RiskPolicy v1.0 untouched** (Risk Scoring v2 stays advisory, never a gate).
