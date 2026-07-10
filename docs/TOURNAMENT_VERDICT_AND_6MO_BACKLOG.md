# SPA Yield Product — Tournament Verdict & 6-Month Backlog

> Synthesis over 6 scout domains. Owner directive: sellable 3-tier yield product (Conservative ~3.3% / Balanced ~8–12% / Aggressive REAL paper-tested ~15–20%+), customer chooses risk/return, tail ALWAYS shown, separate rules per tier, RiskPolicy v1.0 untouched. DeFi Checkup = top-of-funnel. Invariants: no LLM in risk/exec/monitoring, non-custodial, no fabricated APY (evidence L0–L6), deterministic + fail-closed, stdlib-only runtime, atomic writes.

---

## PART A — TOURNAMENT ARCHITECTURAL VERDICT

### Verdict (one line)

**RESHAPE — do not RETIRE. HIDE from public product surface (keep it out of `SiteHeader` top nav), KEEP it operator/admin-facing on the cockpit + footer, and REWIRE it from a dead-end advisory flag into the honest, risk-adjusted breadth-scanner that feeds the Strategy-Lab / 3-tier promotion ladder — but only after its input data is made trustworthy.**

### What it actually does today (grounded)

- Standalone advisory subsystem: `spa_core/tournament/tournament_engine.py` (`TournamentEngine.run_daily`), launchd `com.spa.tournament_engine` @ 09:00 UTC via `scripts/agent_tournament_engine.sh`.
- Each day: self-regenerates `data/strategy_tournament.json` from `data/mass_tournament_results.json`, runs one shadow-paper day into `data/shadow_paper_trading.json` (11 days tracked), runs a **fail-closed** promotion gate, writes `data/tournament_engine_state.json`.
- `IS_ADVISORY=True`. Grep confirms **nothing** in `spa_core/execution/` or the real allocator reads `strategy_tournament.json` / `check_promotions()` / `shadow_active_strategies`. Its "promotion to live" is an advisory flag only — no capital is ever routed by it.
- Telegram pushes are **RETIRED** (routed to digest, returns False) — consistent with RETIRED-agent discipline. Keep retired.
- Public surface: `landing/src/pages/tournament.astro` (`/tournament`), reachable only via cockpit tab bar (`CockpitNav.astro:29`) + footer. `SiteHeader.astro:15-18` deliberately removed it from the public top nav. API `spa_core/api/routers/tournament.py` serves `/api/tournament` + `/api/tournament/status`, polled 15s by `DashboardLive.jsx` / `TournamentCockpit.jsx`. Plumbing works end-to-end.

### Is the ranking trustworthy? — No (by its own stamp), and it handles that honestly

- Live data is **degenerate**: `mass_tournament_results.json` and `strategy_tournament.json` both carry `trustworthy=False`, `data_source_regime=LOW_VOL_YIELD`, top strategies at Sharpe 44–80 (`s12_base_layer_yield=80.36`). On near-constant/low-vol yield series Sharpe is mathematically degenerate → the leaderboard ranking below the trust flag is **noise**.
- The engine handles this **correctly**: `_dataset_trustworthy` is fail-closed (missing/false stamp or `DEGENERATE_MOCK`/`LOW_VOL_YIELD` → refuse all), and `_is_degenerate_sharpe` independently vetoes `|Sharpe|>10`. Result: **0 promotions across all logged runs** — the correct outcome, not a bug.
- The public `tournament.astro` page is unusually honest: it renders the `trustworthy`/`data_source_regime`/`sharpe_degenerate` flags and states "0 promotions = correct honest outcome," explicitly says the desk holds a steady ~4.5% RWA book and the tournament is "paper research, advisory, not a yield promise." **No fabricated live winner is shown.**

**Conclusion:** the engine, gate, and honest UI are solid and near-zero cost. The single defect is the **input data**. Retiring would throw away a genuinely honest "we refuse on bad data" showcase — a DD asset.

### Does it duplicate Strategy Lab / Aggressive Lab / multi_strategy_runner? — Partially, and that overlap must be resolved

| Framework | Where | Data | Wired to product? |
|---|---|---|---|
| **Tournament** | `spa_core/tournament/` | `LOW_VOL_YIELD` mock → degenerate Sharpe, `trustworthy=False` | No — dead-end advisory flag |
| **PromotionEngine** (MP-373) | `spa_core/paper_trading/promotion_engine.py`, in-cycle @ `cycle_reporting.py:526` | daily-cycle series | Separate threshold (Sharpe>0.8/14d) |
| **Strategy Lab / Rates Desk / aggressive_lab** | `spa_core/strategy_lab/` | REAL forward/historical feeds (Pendle PT history, 5-venue funding) | Yes — feeds `/packages` + `/api/strategy-lab/promotion` |

- Tournament vs PromotionEngine = **two overlapping promotion frameworks** (Sharpe 1.5 vs 0.8, two data files) — genuine drift risk. Both documented live (`docs/DECISIONS.md:290`). Not literal duplicates, but they invite divergence.
- Tournament vs Strategy/Aggressive Lab = **conceptual duplication** ("compete → paper → promote vs RWA floor"). The Lab does it on **trustworthy** data and drives the actual product; the Tournament does it on **untrustworthy** data and drives nothing.
- Tournament's *unique* asset: **breadth** — 63 registry strategies backtested + a top-5 shadow track. The Lab sleeves don't have that breadth. But breadth is worth ~nothing while it runs on `LOW_VOL_YIELD` data.

### Target design (if kept/reshaped — the concrete plan)

**Reposition the Tournament as the breadth-scanner FEEDING the Lab promotion ladder, ranked by a tail-penalized metric, gated per tier — never a parallel product.**

1. **Fix the root cause (data feed).** Make the backtest that produces `mass_tournament_results.json` run on the **same real forward/historical feeds** the Strategy Lab / Rates Desk / aggressive_lab already use (Pendle PT implied-yield history, 5-venue funding, real APY series). Only then can Sharpe stop being degenerate and `trustworthy` flip True. Until then the leaderboard is untrustworthy **by its own stamp** and is not a signal.

2. **Rank by tail-penalized metric, not raw Sharpe.** Score entrants by **Calmar / return-per-unit-worst-drawdown** (reuse `aggressive_lab/tail_overlay.py` worst_tail_dd across canonical stress windows) so a fat yield can never outrank a catastrophic tail — the same discipline `scorecard._verdict` already enforces. This avoids re-importing the degenerate-Sharpe trap.

3. **Wire survivors into the ONE promotion ladder.** Trustworthy-data survivors flow into the Strategy-Lab promotion ladder (`/api/strategy-lab/promotion`) as **candidates per tier**, not a dead-end flag. A strategy earns a Balanced/Aggressive slot only after: trustworthy Sharpe/Calmar → ≥30d forward paper → bounded tail shown → **human approval** (the `docs/07` lifecycle). The Tournament proposes; the Lab lifecycle disposes.

4. **Drive tier composition, tail shown.** Tournament output becomes the ranked candidate pool that `tier_policy.py` (Part B, Month 1) draws from when composing each tier's sleeve-of-sleeves. The tail (`worst_tail_dd_pct`, NOT_RECOVERED flags) rides alongside every ranked entry so tier composition is tail-aware end to end.

5. **Converge the two promotion frameworks.** Decide which is authoritative for candidate vetting (recommend: **PromotionEngine authoritative for in-cycle live-track vetting; Tournament authoritative for research-breadth candidate discovery**), make the other consume/reference it, and add a **parity test**. At minimum document both explicitly (remove the drift).

6. **Add a data-trust monitor.** Alert if `strategy_tournament.json` ever flips `trustworthy=True` **or** if any promotion ever fires — because "promotions=0 forever" is expected today, so a future non-zero promotion is the signal that the data-fix landed and needs human review before it means anything.

7. **Site policy:** **HIDE** from public product/tier-choice surface (already done — keep out of `SiteHeader` top nav). **KEEP** on operator/admin cockpit + footer as a credibility/DD asset ("watch us refuse degenerate data"). When data becomes trustworthy, surface a **read-only "how we vet" snippet** on `/research` or `/due-diligence` — never a public yield claim, never a buy signal.

8. **Housekeeping:** fix CLAUDE.md drift — it names `docs/tournament.html` (**does not exist**); the real surface is `landing/src/pages/tournament.astro` + cockpit components (`TournamentCockpit.jsx`, `TournamentLeaderboard.jsx`). Note current data is `trustworthy=False / LOW_VOL_YIELD`. Keep Telegram retired.

**Net:** near-zero cost to keep running honestly (0 promotions = correct). Fix its feed → it becomes the breadth engine that ranks strategies *within* each tier and drives tier composition, tail shown; until then it stays operator-only and implies no public yield.

---

## PART B — 6-MONTH BACKLOG (SIX MONTHLY THEMES)

Tags: `[tier: C/B/A/all/none]` · `[owner-gated: …]` or `[code]` · `[effort: S/M/L]` · mapped file/subsystem. "C/B/A" = Conservative/Balanced/Aggressive.

---

### MONTH 1 — Foundations: per-tier policy, honesty-correctness, number reconciliation
**Goal:** close the owner's #1 gap (separate enforced rules per tier), kill the fabricated/inflated/volatile-number risks, and make one canonical tier identity. Nothing customer-facing changes value without these.

1. **Build `tier_policy.py` — enforced per-tier policy profiles.** `[tier:all][code][effort:L]` `spa_core/strategy_lab/aggressive_lab/tier_policy.py`. Deterministic stdlib data structure: Conservative delegates to RiskPolicy v1.0 unchanged; Balanced caps leverage ≤2x + requires hedge/depeg-guard + tighter DD-kill; Aggressive allows PT/YT loops + LRT + points BUT requires non-empty `tail_overlay` + stamps risk_class C/D. This is the owner's headline ask, entirely outside RiskPolicy v1.0.
2. **Enforce tier_policy in `build_roster`.** `[tier:all][code][effort:M]` `aggressive_lab/roster.py`. Reject/park any book whose config violates its assigned tier band (leverage, hedge-required, tail-required).
3. **Isolation test for tier_policy.** `[tier:all][code][effort:S]` `aggressive_lab/isolation.py` + tests. Assert `tier_policy` cannot import `spa_core.execution` and cannot write any `PROTECTED_FILES` path; take protected-file md5 witness. Preserve the go-live-track wall.
4. **Fix `net_apy_pct` mislabel end-to-end.** `[tier:all][code][effort:M]` `aggressive_lab/harness.py`, `scorecard.py`. The field named `*apy*` stores cumulative `net_return`. Rename → `net_return_pct`; compute a **separate** annualized CAGR (`n_points/365`) for any customer-facing number. Correctness/honesty bug (+1394% total was being read as APY).
5. **Cap/clamp annualization on <30-day windows in scorecard.** `[tier:all][code][effort:M]` `data/aggressive_lab/scorecard.json` producer. No more 217%/155% artifacts; present period-return + explicit `INSUFFICIENT_HISTORY_FOR_APY` instead. Public-honesty gate.
6. **Adopt ONE canonical tier identity across all surfaces.** `[tier:all][owner-gated: name choice][effort:M]` `index.astro`, `packages.astro`, `SiteHeader.astro`, `strategies/*.astro`. Pick Conservative/Balanced/Aggressive OR Preserve/Core/Max-Yield; rename the other set everywhere. (Owner: pick the name set.)
7. **Single source for tier APY bands.** `[tier:all][code][effort:M]` drive all bands from `track_snapshot.json` packages + `/api/tier1/packages`; delete hardcoded band strings so index cards / `/packages` / nav / strategies can't diverge.
8. **Fix the volatile LIVE badge.** `[tier:C][owner-gated: APY definition][effort:S]` `packages.astro:12/82`, `generate_track_snapshot.py:121`. Replace `snap.paper_apy_pct` (single-day annualized, swings daily, exceeds the "2–6%" band) with a **stable track-to-date APY**; reconcile ~3.3% vs ~4.1% vs 2.7% into ONE definition. (Owner: pick track-to-date vs today vs blended.)
9. **Regenerate `scorecard.json` + `annual_contrast.json` against the CURRENT 10-strat roster.** `[tier:B/A][code][effort:M]` both are stale at 8 strats; add `lp_eth_stable` + `levered_restaking`. Wire `com.spa.aggressive_lab` to refresh both daily.
10. **Model YT theta before trusting `pendle_yt_susde`.** `[tier:A][code][effort:L]` `roster.py:384`. `yt_leverage=8.0` is a silent default multiplying real funding 8x; YT decay-to-zero-at-maturity is NOT modelled. Add the theta leg to `_daily_yield_pct`; make `yt_leverage` a disclosed, tier-gated config. Re-run backtest — the +53% CAGR will fall toward defensible. **Never surface the leverage-8 figure.**
11. **Tier-consistency build guard (WARN-ONLY).** `[tier:all][code][effort:S]` CF prebuild script asserting tier name set + band strings + realized-number source match across surfaces. **WARN-only** (exit 1 only under a STRICT flag) — per the CF-prebuild-freshness lesson: never exit-1 in CF prebuild.
12. **Fix CLAUDE.md Tournament drift.** `[tier:none][code][effort:S]` replace `docs/tournament.html` → `landing/src/pages/tournament.astro` + cockpit components; note live data `trustworthy=False / LOW_VOL_YIELD`.

---

### MONTH 2 — Tournament reshape + strategy-universe consolidation
**Goal:** execute Part A (make the Tournament trustworthy + feed the ladder) and collapse two strategy universes into one authoritative map.

13. **Point Tournament backtest at real feeds.** `[tier:none][code][effort:L]` `tournament_engine.py` + `mass_tournament_results.json` producer. Use the same real forward/historical feeds as Strategy Lab / Rates Desk (Pendle PT history, real APY series) so Sharpe stops being degenerate and `trustworthy` can flip True.
14. **Switch Tournament ranking to tail-penalized (Calmar).** `[tier:all][code][effort:M]` rank by return-per-unit-worst-DD reusing `tail_overlay.py` worst_tail_dd; keep `_is_degenerate_sharpe` veto as backstop.
15. **Wire Tournament survivors → `/api/strategy-lab/promotion`.** `[tier:all][code][effort:L]` add an entrant path so trustworthy survivors become tier candidates in the ONE ladder (not a dead-end flag).
16. **Data-trust monitor + alert.** `[tier:none][code][effort:S]` `spa_core/monitoring/`. Alert on `trustworthy=True` flip OR any promotion ever firing — a future non-zero promotion needs human review.
17. **Converge the two promotion frameworks + parity test.** `[tier:none][code][effort:M]` document Tournament (research breadth) vs PromotionEngine (in-cycle live-track); make one reference the other; add parity test.
18. **Resolve id-collision duplicates.** `[tier:none][code][effort:M]` `spa_core/strategies/` — s1/s2/s3/s20/s21 each have TWO files sharing a number. Pick canonical per concept, delete/rename loser with an ADR note.
19. **Quarantine the 65-strat S1–S77 shadow registry.** `[tier:none][code][effort:L]` move `s*.py` behind `spa_core/strategies/_archive/` (or `enabled=False` sweep), keeping only what the allocator/backtest genuinely references. Removes ~60 files of maintenance surface. Shadow-only → no live impact.
20. **Delete or alias S71–S77 stubs.** `[tier:B/A][code][effort:S]` they are shallow duplicates of the real mark-to-market Aggressive Lab entries (S71↔susde_dn, S73↔leverage_loop, S75↔pendle_yt, S76↔lp_eth_stable, S77↔points_farm). Keeping both invites APY-projection drift.
21. **Make Strategy Lab the single strategy source-of-truth + index doc.** `[tier:all][code][effort:M]` one doc mapping every Lab strategy → product tier → verdict → live-paper track file. Kill the two-universe confusion.
22. **Automated "strategy census" CI test.** `[tier:all][code][effort:M]` assert (a) which strategies the LIVE allocator can select, (b) which are advisory/shadow, (c) each strategy's tier + last-verified track; fail CI if a new S-file lands without a verdict. Prevents the S1→S77 accretion recurring.
23. **Repair the two dead Aggressive feeds.** `[tier:A][code][effort:M]` `leverage_loop` + `levered_restaking` sit at 0 days (stETH-ratio/restaking history starts after the Pendle window). Backfill to Pendle-window start OR mark `INSUFFICIENT_DATA` on scorecard/page — never show a 0% line that reads like a real result.
24. **Freeze rwa_backstop / liquidator (documented verdicts).** `[tier:none][code][effort:S]` keep as-is (measurement-GO / NO-GO), stop code investment; redirect effort to the Rates Desk carry leg.

---

### MONTH 3 — Evidence engine: give every tier its own 30-day paper track
**Goal:** convert backtest-heavy tiers into evidenced paper tracks with the tail shown, mirroring the conservative go-live discipline per tier. No tier is "realized" until it earns it.

25. **Run `com.spa.aggressive_lab` continuously + guard continuity.** `[tier:B/A][code][effort:S]` daily tick, self-heal coverage, gap alert. Forward tracks are 0–11 days today — start accumulating honestly.
26. **Per-tier ≥30-day forward-day gate before any "realized" label.** `[tier:B/A][code][effort:M]` `scorecard.py` / `packages.astro`. Show "research/paper, N days" until ≥30 forward days; keep backtest CAGR clearly labelled backtest.
27. **Dedicated ≥30-day `susde_dn` Balanced paper track.** `[tier:B][code][effort:M]` best risk-adjusted profile (9% CAGR / near-zero maxDD / funding-flip kill at −0.0003/8h). Honest (non-inflated) metrics → graduate Balanced from "research-paper" toward a real offering.
28. **Compose the measured Aggressive sleeve-of-sleeves (do NOT stamp one strategy at 20%).** `[tier:A][code][effort:L]` e.g. 50% `pendle_pt_levered` @ disclosed leverage + 30% `susde_dn` + 20% bounded-leverage YT. Report the **blend's** realized trailing-12m CAGR + blended worst_tail_dd across all stress windows. That is the honest ~15–20% tier number.
29. **Attribute every offered strategy a measured 12m CAGR + tail before it can appear on `/packages`.** `[tier:B/A][code][effort:M]` `annual_contrast.json` must cover all offered strategies (incl. `lp_eth_stable`, `levered_restaking`).
30. **Consolidate Aggressive Lab + Rates Desk onto ONE promotion state machine.** `[tier:all][code][effort:L]` unify `promotion.py` + `promotion_rates.py` + one forward-analytics scorecard so tier/verdict/track derive in one place.
31. **Harden the Rates Desk carry leg toward beating the floor.** `[tier:B][code][effort:L]` FixedCarry is −247bps / −2.57pp under the RWA floor (`forward_analytics.json`, 16d). Prioritize decorrelation research (`venue_expansion.py`, `depth_at_size.py`) over new sleeve invention — new thin sleeves don't move the above-floor number.
32. **Surface realized paper number + tail on `packages.astro` for Balanced + Aggressive.** `[tier:B/A][code][effort:M]` feed from regenerated `scorecard.json`/`annual_contrast.json` (headline CAGR, maxDD, worst stress-window loss, verdict). Meets honesty-gate #2 (tail beside yield). Remove the phantom `evaluator.PACKAGES` reference.
33. **Standardize a 3-line tier-card contract on index + packages.** `[tier:all][code][effort:M]` (1) HEADLINE band + evidence-level tag (L6 live / L2 paper / L0 target), (2) REALIZED = stable track-to-date figure, (3) TAIL = worst realized/measured DD inline, **never "—" at first paint** (server-render worst-DD).
34. **eth_directional out of any "yield" tier.** `[tier:A][code][effort:S]` pure beta (−32%/66% DD, or −51% in backtest); scorecard correctly labels DIRECTIONAL_BETA / SEVERE_TAIL. Keep it out of tier composition entirely.

---

### MONTH 4 — Checkup funnel: close the retention loop + illuminate the dark signals
**Goal:** turn Checkup from a run-once diagnostic into a durable, measurable top-of-funnel into the 3-tier product. (DeFi Checkup repo: `apps/web` + `packages/riskdesk`.)

35. **Owner: land `ETHERSCAN_API_KEY` on the correct Railway service+env + redeploy.** `[tier:none][owner-gated: Etherscan key][effort:S]` `approvals.ts:180`. Re-illuminates the #1 drain-risk signal (currently dark; keyless Etherscan V2 retired). Verify by curling a heavy wallet's approvals section, not HTTP status.
36. **Harden Alchemy approvals fallback for whales.** `[tier:none][code][effort:M]` `approvals.ts scanViaAlchemy`. Replace single `fromBlock:0x0` full-range with block-range chunking + pagination; any failed chunk → "not scanned" (fail-closed), never partial-zero.
37. **Wire `POST /api/watch` route.** `[tier:none][owner-gated: WALLET_REF_SALT][effort:M]` `apps/web`. Calls `addWatch(address,email,capturedAt)`. **Do NOT store real hashed addresses under the public dev salt** — gate on `WALLET_REF_SALT` being set.
38. **Scheduled re-scan worker (close the watch loop).** `[tier:none][code][effort:L]` Railway cron/worker: for each `listWatched()` → `analyzeWallet` → `computeReportDelta` vs stored `last_report_id` → `isAlertWorthy`. The three deterministic pieces exist; only the loop is unclosed.
39. **Owner: set `RESEND_API_KEY` + wire alert email.** `[tier:none][owner-gated: RESEND][effort:S]` `email.ts` (currently no-op). On alert, send the "what got worse" lines; opt-in, one-click unsubscribe (reuse waitlist token pattern), non-custodial.
40. **Expand approvals `KNOWN_SPENDERS` to Arbitrum/Optimism/Polygon.** `[tier:none][code][effort:M]` dedicated per-chain maps (not just `KNOWN_SPENDERS_L2_SHARED`), web-verified canonical singletons; continue the fail-closed Base-omission test pattern. Fewer "unknown spender" false positives.
41. **Extend leverage coverage to Morpho + Fluid (Euler next).** `[tier:none][code][effort:M]` `lending.ts` (Aave/Spark/Compound only today). Long-tail lending is the highest-severity blind spot; keep "unreachable Pool → data gap, never debt-free."
42. **Add 2–3 chains to fixed-watchlist capture.** `[tier:none][code][effort:M]` `chains.ts` — candidates Blast/Scroll/Linea/zkSync Era; prioritize where retail holds idle stables/LSTs (the positions the funnel monetizes). Disclose `token_coverage`/`chain_capture` gaps identically.
43. **Anti-fabrication regression gate on Checkup yield surfaces.** `[tier:none][code][effort:S]` `yield/quality.ts`, `protocol_apy.ts`. Assert pool positions render "unassessed" and reference-APY is always "not realised yield." The funnel must never appear to promise a yield it didn't verify.
44. **Reconcile Checkup docs with shipped reality.** `[tier:none][code][effort:S]` README §"How it works", `analyze.ts:13` docstring, `18_BACKLOG.md` still say "Ethereum and Base only / not scanned" though 5-chain + approvals + lending shipped. A verifiability product must not UNDER-state itself.
45. **Repo hygiene in Checkup.** `[tier:none][code][effort:S]` gitignore/remove `.buildtmp/`, `.tmp-ci/`, `zbuild-*.log`, `write-test.txt`, vitest timestamp files so real diffs are legible.

---

### MONTH 5 — Site/product presentation: honest tier choice + checkup→tier bridge
**Goal:** make the informed tier choice happen at the point of decision (name + realized number + tail all visible), instrument it, and bridge checkup → tier. Everything here is buildable now; capital intake stays inert.

46. **Render the tail at the point of tier choice on the homepage.** `[tier:all][code][effort:M]` move `packages.astro` per-tier "bad month" copy into `index.astro` tier cards; server-render worst-DD so it shows before the live fetch. Aggressive card's "~50% ETH-crash / liquidation-cascade" must be impossible to miss.
47. **Instrument tier choice with `data-track`.** `[tier:all][code][effort:S]` `index.astro:190/203/217` + `/packages` cards: `tier_view_conservative/_balanced/_aggressive`; `tier_compare` on the nav Packages link. The single most important funnel signal is currently unmeasured.
48. **Checkup → tier bridge (mid-funnel).** `[tier:all][code][effort:M]` after checkup, route visitor to a recommended tier with UTM carrying their risk-score bucket (beacon already captures UTM on arrival). Show recommended tier with headline+realized+tail + a "why this tier for you" one-liner tied to their idle-capital/risk-score. Biggest conversion gap, no legal gate.
49. **Turn `policyCheck.ts` personalization into the funnel router.** `[tier:all][code][effort:M]` use the reader's chosen thresholds (or a retail-vs-treasury persona toggle) to pick which SPA tier the Checkup CTA points at, extending existing signal-specific SPA-5 deep-links. Non-custodial, engine-computed numbers only.
50. **Add a compact "proof" strip on `/packages`.** `[tier:all][code][effort:S]` link `/track-record`, `/refusals`, `/exit-nav` — "don't trust us, check us." Reuse the `fund_to_*` pattern.
51. **Make "we refuse the 15% others sell you" the explicit Aggressive headline.** `[tier:A][code][effort:S]` `packages.astro` — the sellable asset is the refusal + measurement discipline; show tail as a selling point, not fine print.
52. **Reconcile the five Conservative numbers into one.** `[tier:C][owner-gated: business number][effort:S]` 2.7% (index) / 4.10% (LIVE badge) / "2–6% + ~3.3%" (packages) / "6–8%" (nav) / "~6%" (preserve.astro) → ONE realized definition wired once. (Owner: the public APY definition.)
53. **Draft the "choose a tier & fund" flow as DESIGN-ONLY, inert.** `[tier:all][owner-gated: legal review, custody, KYC/AML][effort:M]` ship the informed-choice presentation; hold the intake button behind a documented legal gate (invariant E-18). Funnel complete-but-inert until owner sign-off.
54. **Site Custodian freshness monitor covers tier numbers.** `[tier:all][code][effort:S]` extend ADR-YL-011 freshness/degraded-kill rules to the tier realized numbers so stale/overstated tier APY auto-degrades. WARN-only in CF prebuild.
55. **Package the moat into a public DD pack.** `[tier:none][code][effort:M]` `/fundability` + `/proof-of-reserves`: hash-chained refusal log, published NO-GO (liquidator ~$3.8M/yr << $20M), standalone `scripts/verify_spa.py`, 11/11 `defenses_exercised_report.py`. Lean go-to-market on the moat, not the yield.

---

### MONTH 6 — Go-live + first-AUM path + infra/reliability
**Goal:** cross the 30-day conservative go-live line, protect track continuity, prep the off-code AUM gates in parallel, and harden reliability. First AUM enters the conservative core, not the aggressive tier.

56. **Protect track CONTINUITY through go-live (P0).** `[tier:C][code][effort:S]` go-live is time-gated only (27/29 PASS; `gap_monitor_30d` + `min_track_days_30` resolve at 30 evidenced days ~2026-07-21). A single missed daily cycle resets the count. Harden `self_heal`; add "days-to-go-live at current continuity" alert; treat any gap as P0.
57. **Ship the SELLABLE Conservative product first ("floor + measurement").** `[tier:C][code][effort:M]` ~3.3–4% with a live 30-day evidenced track + hash-chained proof + published refusal log. First external AUM realistically enters here. The moat sells trust; the yield is floor-level and honestly labelled.
58. **Be explicit about the two ceilings with any allocator.** `[tier:all][code doc][effort:S]` `docs/34` — conservative core scales ~$50–100M at floor-level; exotic edge caps ~$1–2M and goes NEGATIVE past ~$1M (`FUNDABILITY.md`). Pitch must not rely on edge sleeves as material yield at scale.
59. **Attack the `RWA_YIELD_TOO_LOW` binding constraint (only real above-floor lever).** `[tier:C][code][effort:L]` `STRUCTURAL_DESK.md` — close the gap-to-$10M via deeper PT markets + more venues/chains to decorrelate exit rails (deep + carry become additive) + real AUM at floor. Prioritize `venue_expansion.py` / `depth_at_size.py` decorrelation over new sleeves.
60. **Keep Aggressive permanently refused-for-live until full lifecycle + legal.** `[tier:A][owner-gated: Red Team + human approval + legal disclosure][effort:S]` never let a ~20% marketing desire short-circuit `docs/07`/THREE_TIER honesty gates. The eth_directional −51% / lrt_neutral-depeg-kill backtests are exactly why.
61. **Owner: begin counsel engagement + entity/structure + disclosures NOW (parallel).** `[tier:all][owner-gated: legal review, entity, disclosures][effort:L]` `docs/42` 9-item fail-closed checklist; every item owner-accountable, months of lead time. Start so it lands near the 30-day go-live, not after.
62. **Owner: select custody model + KYC/AML + jurisdiction.** `[tier:all][owner-gated: custody, KYC/AML, jurisdiction][effort:L]` institutional custody mandatory at $5–10M (`docs/34`). Non-custodial today; any intake needs this off-code.
63. **Resilience: verify offsite/restore/fleet drills stay green through go-live.** `[tier:none][code][effort:S]` `resilience_status.py` rollup (`dr_offsite_status`, `restore_drill_status`, `fleet_drill_status`) — fail-closed OK only if all fresh + passed. SPOF (single host) remains owner-flagged.
64. **Checkup infra: shared store before multi-node scale.** `[tier:none][code][effort:M]` `reportStore.ts` + in-process `rateLimit.ts` + file `watchlist.ts` are single-node-shaped; move to KV/DB before horizontal scaling or a durable multi-node watch scheduler.
65. **Pre-cutover readiness gate stays INERT + advisory.** `[tier:none][code][effort:S]` `pre_cutover_gate.py` — keep `would_cutover=False`, no execution import, refuses live `data/`. Run as advisory CI step proving all money-path defenses fire before any cutover discussion.
66. **Post-go-live: first-30-day evidenced-track publication.** `[tier:C][code][effort:S]` auto-publish the crossed 30/30 evidenced track to `/track-record` with hash-chained proof — the cheapest highest-trust milestone for a first allocator.
67. **Wire Tournament "how we vet" read-only snippet to `/research` IF data trustworthy.** `[tier:none][code][effort:S]` only after Month-2 data-fix flips `trustworthy=True`; still never a public yield claim.

---

## OWNER-ONLY CRITICAL PATH (off-code, months of lead time — start in parallel NOW)

1. **Legal counsel engagement + entity/structure + disclosures** (`docs/42`, invariant E-18) — the true gate to first external AUM. Nothing in code advances it.
2. **Custody model selection + KYC/AML + jurisdiction** — mandatory at $5–10M AUM (`docs/34`).
3. **The public APY definition** — reconcile 2.7% / 4.10% / ~3.3% / ~6% into ONE track-to-date number (blocks honest tier presentation).
4. **Canonical tier name set** — Conservative/Balanced/Aggressive vs Preserve/Core/Max-Yield (blocks the consistency guard).
5. **`ETHERSCAN_API_KEY`** on the correct Railway service+env — re-lights the #1 Checkup drain-risk signal.
6. **`WALLET_REF_SALT`** — required before storing any real hashed wallet in the watch loop.
7. **`RESEND_API_KEY`** — required before the retention email loop can deliver.
8. **Aggressive-tier live approval** — Red Team + human approval + high-risk legal disclosure before ANY live use (kept refused otherwise).

## TOP RISKS

1. **Track-continuity break before 2026-07-21** — go-live is time-gated only; a single missed daily cycle resets `gap_monitor_30d`. P0. (Mitigation: M6 #56.)
2. **Fabricated/inflated public number** — `net_apy_pct` mislabel (+1394% total as APY), 217%/155% annualization artifacts, and the volatile LIVE badge exceeding its own band are live L0–L6 honesty violations on the exact page that sells tiers. (Mitigation: M1 #4/#5/#8.)
3. **Four-number / two-name tier drift** — same tier shown 5 ways across 4 surfaces; a customer can't map `/packages` to the homepage. First-AUM credibility killer. (Mitigation: M1 #6/#7 + guard #11.)
4. **Tail hidden at point of choice** — only `packages.astro` shows the tail; homepage cards render "—" until a live fetch. First-impression choice made without the tail. (Mitigation: M3 #33, M5 #46.)
5. **Aggressive tier has no evidenced track** — 0–11 forward days; only above-15% books are a leverage-8 artifact or cumulative-total. Any "realized ~20%" claim is currently unfoundable. (Mitigation: M3 #26/#28.)
6. **Above-floor edge is thin and shrinks with size** — FixedCarry −247bps under floor; optimizer +1.08pp goes NEGATIVE past ~$1M; combined above-floor ~$34k/yr. The moat (measurement/refusal), not the yield, is the fundable story. (Mitigation: M3 #31, M6 #59.)
7. **Checkup retention loop unclosed + top drain signal dark** — watch loop 60% built but no route/scheduler/email; approvals dark in prod without `ETHERSCAN_API_KEY`. Funnel leaks. (Mitigation: M4 #35–#39.)
8. **Tournament data untrustworthy if surfaced** — Sharpe 44–80 leaderboard is noise under `trustworthy=False`; keep operator-only until the data-fix lands and a credible-data promotion actually fires. (Mitigation: Part A + M2 #13–#16.)
9. **Two-universe / two-promotion-framework drift** — 65 shadow S-strategies with id-collisions + duplicate stubs, plus Tournament vs PromotionEngine divergence. (Mitigation: M2 #17–#22.)
10. **SPOF (single host)** and the resilience posture must stay green through go-live and any first-AUM operational-trust window. (Mitigation: M6 #63; real offsite remains owner-flagged.)
