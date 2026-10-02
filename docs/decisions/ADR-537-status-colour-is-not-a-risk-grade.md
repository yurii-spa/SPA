# ADR-537: Status colour is not a risk grade — one card format and live status for the three paper portfolios

- **Status:** ACCEPTED · 2026-10-02 · owner: @yurii (owner epic «THREE DEFI PAPER PORTFOLIOS —
  INSTITUTIONAL-GRADE CLOSEOUT», continuing ADR-533; the owner's own words: «цвет эксплуатационного
  статуса не является оценкой риска»)
- **Builds on:** ADR-533 (three mechanics, one read model), ADR-357 п. 5 / ADR-365 (one shelf for
  site numbers), ADR-116 (standing approval for classes B/D).
- **Not changed:** RiskPolicy v1.0, tiers, limits, stops, the money path, any book's history, the
  Trading Research Engine, live capital (0). No new service: the status endpoint is a route in the
  existing API server.

## What the owner saw (home page, 2026-10-02)

| Problem | Measured |
|---|---|
| One badge answered different questions | Conservative: green «evidenced»; Balanced: yellow «research / paper»; Aggressive: yellow «refused for live». The same operational state (all three RUNNING) looked different |
| Result and target in the same big font | 4.9 % (realized) next to «up to 12 %» and «up to 20 %» (research targets) |
| Drawdown meant three things | measured 0.0 % (Conservative), backtest ~4.5 % and ~50 % (other books and mechanics) |
| A third copy of public numbers | `strategy_config.target_apy` = 6/5/15 against `tier_bands` = 6/12/20; the home-page calculator typed `0.20` into JS and projected «up to $10,000/yr» from a target |
| Mobile | home at 375 CSS px: `scrollWidth` 396 (the two-column calculator). Production had the same defect; the earlier 500 px check could not see it |
| Freshness | status came only from the daily snapshot; a stopped process would have stayed green for a day |

## Decision

1. **Seven separate fields** in `defi_engine.package_status`:
   - work: RUNNING / PAUSED / FAILED / UNKNOWN / NOT_STARTED. FAILED is used **only for a confirmed fault**; an overdue run with exit 0 is UNKNOWN;
   - data: HEALTHY / DEGRADED / WAITING_FOR_DATA / STALE;
   - decision: OPEN / HOLD / EXIT / NONE, with the position and the reason. A correct HOLD is a decision, not a data fault;
   - history: WARMUP / ACCUMULATING / REPORTABLE (current version only);
   - mode: PAPER_ONLY plus live NOT_APPROVED / REFUSED, from the mandate's `live_admission`;
   - freshness: schedule, `stale_after_h`, `last_successful_run_at`, `source_observed_at`, `stale_at`;
   - known decision defects are attached to the row they affect (`DECISION_DEFECTS`). The row itself is never rewritten.
2. **One sanitised projection, `public_view`.** It is served by:
   - the daily site snapshot;
   - the new `GET /api/v1/packages/status`, rebuilt per request, `Cache-Control: no-store`, a named 503 on failure.

   No local paths, process labels or raw logs leave the machine; tests pin this.
3. **One card rule, `landing/src/lib/package_card.js`, plus one component, `PackageStatusRows.astro`.**
   - Used on the home page, /packages, /strategies (StrategyCard) and the three strategy pages.
   - Fixed order: status → real-capital admission → mechanic → position/decision → result → statistics → risk profile → observed drawdown → stop rule and its action → last successful run → research target (secondary).
   - Colour: green = confirmed working with fresh data; yellow = a named warning or missing data; red = a confirmed fault; neutral = paper, accumulation, a HOLD.
4. **Freshness is judged by the reader's clock.**
   - The card script re-renders every minute and re-fetches the API every 5 min and on tab focus.
   - A record past `stale_at` turns UNKNOWN / STALE whatever `generated_at` says.
   - When the API is unreachable, the card names its source: «status from the published snapshot <time> — live status unavailable».
5. **Result: one definition for all three.**
   - The result is the current version's realized, annualised paper rate, **from the shelf only** (`site_numbers.js`). It is shown only when REPORTABLE (≥ 30 valid days); before that the card says «statistics of the current version are accumulating — N of 30».
   - The period line uses the shelf's NAV and the start capital. No new number is computed and no third source is added (owner reminder, 2026-10-02: «все цифры… берутся с одного источника»).
6. **Drawdown, stop and target are three different lines.**
   - **Observed drawdown:** from the shelf, labelled «a past observation, not a loss limit».
   - **Stop rule:** names its action; thresholds come from the shelf / constitution.
   - **Research target:** from `tier_bands`, labelled «not a result, not a forecast».
   - The backtest tail of the earlier Aggressive Lab book stays next to the target on /packages.
7. **Home page.**
   - The calculator is one column. **Superseded by CR-537-1 (second pass):** the first pass removed the research-target scenario with its typed `0.20`; the typed constant and the same-size comparison stay removed, the scenario capability is RESTORED as a secondary labelled block whose rate comes from `tier_bands`.
   - The hero lead: the first pass (`40d9cdf6`) replaced the owner's J3 framing; **restored verbatim by CR-537-3**, the choice is in the owner package.
   - The comparison bar shows the realized rate large and the targets small (owner instruction 02.10: no measured-vs-target comparison in large type on the home page).
   - A protocol-tier row is shown separately from the mechanic, MEASURED from the registry labels of the held positions (CR-537-2); `code_identity` (from the code-sync receipt) names the code the runs execute.
   - The section title is «Three paper portfolios, three different mechanics».
8. **Observation journal.** `missed_runs` counts misses from the INTERVALS between runs. launchd `StartInterval` drifts a few seconds per run, so a run at 05:59:59 followed by one at 07:00:10 leaves slot 06 empty with no run missed. This was measured on both sleeves on 2026-10-02; the old slot count reported one false miss.

## Kept on purpose (owner gate, class E)

Lines carrying honesty tokens are kept byte-for-byte. Rewording them needs an owner card:
- the home-page Aggressive chip «Paper-tested · refused for live» and its line «paper-tested in Aggressive Lab · refused for live capital»;
- the /packages Aggressive research label;
- the strategy-page banners;
- the page meta descriptions.

They are now placed as the live-admission line, next to the new status. The rewording is in the consolidated owner package (`docs/owner_packages/2026-10-02-three-portfolios-closeout.md`).

## Verification

- **Real CSS viewports through CDP** (`Emulation.setDeviceMetricsOverride`) at 375 / 390 / 430 / 1280, EN and RU, after JS and fonts. Six pages were checked: `/`, `/packages`, `/strategies`, and the three strategy pages.
- On every page, `innerWidth == clientWidth == scrollWidth` at each width, with no element outside the viewport except inside horizontal-scroll tables.

## Change records — memory-before-change review of this epic's own removals (2026-10-02, second pass)

Owner instruction the same day: «существующая функция не должна исчезать только потому, что новая
сессия не понимает, зачем её когда-то сделали». The first pass (commits `acacff4f`, `a0a826aa`,
`40d9cdf6`) removed and replaced site elements WITHOUT looking up why they existed. The memory
assembler could not have answered: the redesign specs were outside its allow-list (measured: «NOT
covered: калькулятор»). Origins below were restored from git history across all refs; the first
appearance on `main` (`f1c089ed4`, 2026-09-30, 8 206 files) is a bulk re-add, NOT a creation, and is
not cited as one. From this commit on, the delivery path refuses a significant removal without a
record (`scripts/check_change_evidence.py`, wired into both pushers).

```change-record
id: CR-537-1
task: epic «three DeFi paper portfolios» · role: site / product copy
component: home-page yield calculator (landing/src/pages/index.astro, section M3)
purpose: let a visitor size the realized Conservative paper result for their own amount AND see what a research target would mean, with its tail inside the component («the user sells himself, fabrication-proof by construction»)
purpose_source: docs/redesign/01_PHASE0_SELL_SPRINT_SPEC.md e3263507b docs/redesign/STATUS.md
defect: (1) the scenario's 20 % was typed into the script — a third copy of a public number; (2) the scenario sat next to the measured result at the same size and in the result's colour, as if both were the same kind of number; (3) the two-column grid overflowed a 375 px screen (scrollWidth 396, measured on production)
decision: first pass a0a826aa removed the scenario column entirely — that removed the capability, not only the defects, and was wrong. Corrected here: the scenario is restored as a separate, smaller block labelled «scenario, not a result», its rate parsed from the canonical band (tier_bands.json), its assumptions named (whole amount, before real execution costs, current version N of 30 days), its tail the band's own tail string; one column
alternative: (a) restore the July two-column form verbatim — rejected: brings back the typed constant and the same-size comparison the owner asked to remove; (b) keep it removed — rejected: removes an approved capability whose purpose is still valid
preserved: slider, realized-rate line (shelf), the scenario capability with its tail, the «not an offer» small print
changed: the scenario's size, label, colour, source of its rate, layout (one column)
removes: id:calc-agg
consumers: home-page readers; no API, no snapshot field
owner_approval: not required for restoring an approved feature with the same numbers from their canonical source; listed in the owner package as «confirm or remove» because a dollar scenario is subject №2 presentation
reversible: yes (git revert of this commit; the July form is in e3263507b)
rollback: revert the commit
```

```change-record
id: CR-537-2
task: epic «three DeFi paper portfolios» · role: site
component: home-page package cards (tier-apy, tier-dl rows, tier-who lines, loadPackages(), meta chip) and the comparison bar's two SPA cells (redesign M2: «up to ~6%/yr target», «up to 20% target» in large type)
purpose: tier cards of the redesign (design system 2026-06-25, then SELL SPRINT N1/M10): one number + one chip + one line per tier; loadPackages() refreshed the cards from /api/tier1/packages; the meta chip labelled the numbers «validated backtest, not realized»
purpose_source: 8dfa17724 d11ffa0f8 f7c81e0bb docs/redesign/01_PHASE0_SELL_SPRINT_SPEC.md
defect: research targets in the result's font next to a measured rate; «Max drawdown» mixed a measured 0.0 % with backtest worsts of OTHER books; «Tier mix: T1 + T2» printed for all three, and false for Balanced (it holds `susde`, T3 in ADAPTER_REGISTRY); loadPackages() wrote a backtest blend and a backtest drawdown into the live cards
decision: one shared row set (components/PackageStatusRows.astro) from the one status record and the one shelf
alternative: relabel the old rows in place — rejected: the same badge would still answer different questions per card
preserved: risk band (row «risk profile»); the tail (research tail now next to the research target; measured drawdown for the current version); protocol tiers (row «protocol tiers held», measured from ADAPTER_REGISTRY labels of the held positions — restored in this commit after the first pass dropped it); live refresh (now /api/v1/packages/status); the honesty meta chip (text changed: colour is not a risk grade); every honesty-token line byte-for-byte
changed: what the big number is (the current version's result, one definition), where the target lives (secondary, labelled); in the comparison bar the realized rate is large and the targets small (explicit owner instruction 02.10)
removes: fn:landing/src/pages/index.astro:loadPackages
consumers: home-page readers; /api/tier1/packages keeps serving its other readers
owner_approval: not required (structure; numbers unchanged and sourced); honesty-token rewording is in the owner package
reversible: yes (git revert a0a826aa and this commit)
rollback: revert
```

```change-record
id: CR-537-3
task: epic «three DeFi paper portfolios» · role: site copy
component: home-page hero lead sentence
purpose: owner wish J3 (2026-07-12, «брать максимум»): the hero LEADS with the maximum research aspiration («Target up to ~20 %/yr», paper, tail shown) on the realized floor
purpose_source: docs/CUSTOMER_JOURNEY_MAP.md 5bd4fd1de 9c5070d17
defect: none established. 40d9cdf6 replaced it by a session's own reading of the owner's CARD instruction of 02.10; the hero framing is subject №2 and its exact sign-off is UNKNOWN in canon (journey map: «owner-gated on how aggressive»)
decision: RESTORED verbatim in this commit; the choice between J3 and a mechanics-first lead goes to the owner package
alternative: keep the mechanics-first lead — rejected: an agent would be overriding an owner framing decision by interpretation
preserved: the J3 sentence and its numbers
changed: nothing versus the July state (a comment records why)
removes: none
consumers: home-page readers
owner_approval: required for any change of this sentence — owner package item
reversible: yes
rollback: revert
```

```change-record
id: CR-537-4
task: epic «three DeFi paper portfolios» · role: status read model
component: spa_core/defi_engine/package_status.py (acacff4f)
purpose: ONE read model of the three paper portfolios for the site and the Director (ADR-533)
purpose_source: docs/decisions/ADR-533-three-defi-paper-portfolios.md
defect: one `data` field carried both input quality and a correct HOLD; an overdue run was FAILED (red) without a confirmed fault; missed runs were counted by empty clock-hour slots (launchd drift gave a false miss); the Conservative kill switch was read from keys its writer never writes
decision: seven fields (work / data / decision / history / mode / freshness / composition), missed runs by interval, kill switch from triggered/state + derisk_status + the manual flag
alternative: keep data=HOLD and add a second field — rejected: two fields answering one question
preserved: work/data/history names and states; gaps() (slot view) kept beside missed_runs(); headlines; the Director section
changed: HOLD moved to `decision`; overdue = UNKNOWN; _slot_24h_ago replaced by missed_runs(since=)
removes: py:spa_core/defi_engine/package_status.py:_slot_24h_ago
consumers: generate_track_snapshot (site snapshot), /api/v1/packages/status, director_report
owner_approval: not required (no money path, no RiskPolicy, no public number)
reversible: yes
rollback: revert acacff4f
```

```change-record
id: CR-537-5
task: epic «three DeFi paper portfolios» · role: site copy
component: StrategyCard target number; strategy pages «Target APY» sections; strategy_config does_not / yield_sources; Balanced «RiskPolicy» section
purpose: target profile per strategy card (Foundation Sprint 2026-06-19); «what it does not do» lists; Balanced risk-controls table
purpose_source: 7465a22d9 docs/decisions/ADR-530-defi-architecture-gap-audit.md
defect: strategy_config.target_apy 6/5/15 contradicted the canonical bands 6/12/20 (third copy); the target sat as the headline number; «does not bypass RiskPolicy» and «every allocation passes RiskPolicy» were false for the Balanced and Aggressive sleeves — they were outside RiskPolicy in the OLD version too (ADR-530), so this corrects a statement, it does not rewrite history
decision: cards and pages show the research target from tier_bands as a labelled secondary line; the false RiskPolicy claims replaced by what holds the sleeves (their own stops and rules)
alternative: change target_apy values to 6/12/20 — rejected: a second copy of the band remains a copy
preserved: the research target (canonical), the research label, the target note, the RiskPolicy table (now titled as the Conservative gate)
changed: the 6/5/15 field is no longer rendered (the field stays in the JSON; deleting it is in the owner package)
removes: none
consumers: /strategies, /strategies/{conservative,balanced,aggressive}
owner_approval: not required (copy correction; numbers unchanged and sourced)
reversible: yes
rollback: revert a0a826aa
```
