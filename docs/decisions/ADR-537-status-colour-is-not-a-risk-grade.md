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
   - The calculator is one column, at the realized Conservative rate. The target projection and its typed `0.20` are removed.
   - The comparison bar shows the realized rate large and the targets small.
   - The section title is «Three paper portfolios, three different mechanics».
8. **Observation journal.** `missed_runs` counts misses from the INTERVALS between runs. launchd `StartInterval` drifts a few seconds per run, so a run at 05:59:59 followed by one at 07:00:10 leaves slot 06 empty with no run missed. This was measured on both sleeves on 2026-10-02; the old slot count reported one false miss.

## Kept on purpose (owner gate, class E)

Lines carrying honesty tokens are kept byte-for-byte. Rewording them needs an owner card:
- the home-page Aggressive chip «Paper-tested · refused for live» and its line «paper-tested in Aggressive Lab · refused for live capital»;
- the /packages Aggressive research label;
- the strategy-page banners;
- the page meta descriptions.

They are now placed as the live-admission line, next to the new status. The rewording is in the consolidated owner package (ADR-537 §Owner package, journal 2026-W40).

## Verification

- **Real CSS viewports through CDP** (`Emulation.setDeviceMetricsOverride`) at 375 / 390 / 430 / 1280, EN and RU, after JS and fonts. Six pages were checked: `/`, `/packages`, `/strategies`, and the three strategy pages.
- On every page, `innerWidth == clientWidth == scrollWidth` at each width, with no element outside the viewport except inside horizontal-scroll tables.
