# A3 · EARN DEFI PRODUCT TRUTH (RM-TRUTH-01, Phase 1, read-only)

Audit time: 2026-10-05 08:12–08:20 UTC. Code is from `~/Documents/SPA_mirror` @ `b36acda46`, which equals `origin/main` (`git ls-remote https://github.com/yurii-spa/SPA` → `b36acda46c17…`). Runtime is `~/Documents/SPA_Claude/data`. Live site: `curl -L https://earn-defi.com/<page>/`; raw dumps are in `rmtruth/live/`. API: `https://api.earn-defi.com/…`.
Nothing was written to any repo tree. Note: the mirror has untracked `spa_core/database/spa.db-shm`/`-wal` with mtime 10:13 CEST. That is before my first command touching that tree, so they were not created by this audit.

---

## 0. Executive verdict

1. **Names.** The public profiles are now **Conservative / Balanced / Aggressive**. Preserve / Core / Max Yield were **SUPERSEDED on 2026-07-11** by an owner decision (`ADR-OWN-2026-07-owner-decisions-batch.md` "Tier naming"; executed in `c1207ac26`). They survive only as `alt_en` in `tier_bands.json`, as `strategy_config.json` ids (`preserve`/`core`/`max-yield`), and as meta-refresh redirect pages.
2. **Core was never the evidenced book in the current definition.** On 2026-06-19 Core was the "paper-tracked" flagship (`0d3139e49` `strategy_config.json`: core `paper-tracked`, target 10). On 2026-07-11 the owner moved the evidenced $100k track (anchor 2026-06-22) to **Conservative** (`6ca6cf282`, "UX-26 resolved (owner: Conservative is the evidenced book)"). This was by commit message only; no separate ADR exists.
3. **APY inversion: root cause found.** It is still live on owner surfaces today. Three independent mechanisms each made the higher-risk package show a lower % (§2):
   - (a) the published sleeve books 2026-09-13…09-27, caused by the v1 cost-model defect (ADR-530 P0-1). The public site no longer shows this since `1a2d79252` (2026-10-01, ADR-531).
   - (b) **still live:** `/api/live/books` → `/admin/portfolio-summary` and the Telegram daily "📚 Пакеты" block. Right now they show **Conservative 4.15 % · Balanced −4.36 % · Aggressive 1.36 %**. `books_summary.py` annualises the whole book life linearly, including the 39 distorted v1 days. It is not v2-aware and has no maturity gate.
   - (c) structural: ADR-292/ADR-125 admit that the sleeve universe holds no 12 %/20 % yields, so the "up to 12/20 %" ladder is a **TARGET only**. No accepted realized risk-return ladder exists.
4. **Publication is stuck inside the repo, not at Cloudflare.**
   - `deploy_site_snapshot.py` has failed every daily cycle since 2026-10-02 with `ModuleNotFoundError: No module named 'spa_core'` (`logs/daily_cycle_2026100{2,3,4,5}.log`). The cause is the lazy import at `generate_track_snapshot.py:159`, introduced in `c673b3df3`/`1a2d79252`, combined with script-path `sys.path[0]`. This is the ADR-148 class.
   - The prod-local shelf (`site_numbers.json`, 2026-10-04, untracked in prod) never reached origin; origin is still 2026-10-01.
   - `site_freshness` is WARNING (exit 1) and raises `PUBLISHER_STUCK` CRITICAL. Its text, "лекарство вне репозитория — Cloudflare Pages", is **a wrong diagnosis**: the shelf it compares against exists only in the prod working tree.
5. **Three different "current APY" numbers are published for the same Conservative book:**
   - 4.9 % (compound from anchor, the shelf)
   - **4.2 %** (single-day accrual rate; JS overwrites the home "Current APY" and the dashboard "Paper APY")
   - 4.15 % (linear, `/api/live/books`)
   - Plus 3.7 % (BACKTEST blend s61/s27/s62/s77), mislabelled `kind: замер` in `site_numbers.packages`.

---

## 1. Public profile ↔ internal book mapping

### 1.1 Timeline of names (with decision source)

| Date | Event | Source |
|---|---|---|
| 2026-06-19 | Preserve/Core/Max Yield product site created. `strategy_config.json`: preserve `target-profile` 6 %, **core `paper-tracked` 10 % (flagship)**, max-yield `coming-soon` 15 % | commits `33d09c29b`/`0d3139e49` (v9.10), `bc32030d6` (v9.11a pages) |
| 2026-06-22 | Evidenced paper track anchor (main book, `cycle_runner`) | `track_snapshot.json.evidenced_anchor` |
| 2026-07-11 16:53 | Agent brief: two name sets ship side by side; owner asked to pick | `docs/SITE_TAXONOMY_NUMBERS_DECISION.md` (`7916e7f1f`) |
| 2026-07-11 22:03 | **Owner decision: Conservative/Balanced/Aggressive everywhere; APY display "up to {max}%" (6/12/20); tail shown** | `docs/decisions/ADR-OWN-2026-07-owner-decisions-batch.md` (backfilled 07-15); executed `c1207ac26`, `d7395f46`, `d84ad71b`, `c63ee627` |
| 2026-07-11 22:30 | **Owner: Conservative = the evidenced book** (UX-26). Balanced → research, Aggressive → research/refused | commit `6ca6cf282` message (no ADR; decision lives in git log + `strategy_config.json`) |
| 2026-07-16 | Owner: Conservative headline = "up to 6 %", realized (~3.3 %) as context | `docs/OWNER_BACKLOG_2026-07-16.md` item 5 — **SUPERSEDED** by ADR-548 item 8b (hero = measured result) |
| 2026-08-23 | Balanced (`hy_cycle`, "package Core") and Aggressive (`lp_cycle`, "package Max-Yield") start real $100k paper books; "aggression" = concentration + −25 % budget, NOT directional | `ADR-125` |
| 2026-10-01 | v1 sleeve history declared DISTORTED; only `sleeve-econ-v2` days published (Option A) | `ADR-531`, `1a2d79252` |
| 2026-10-02 | New experiments: `balanced-fixed-carry-v1@2026-10-02`, `aggressive-susde-loop-v1@2026-10-02` | `ADR-533`; `track_snapshot.paper_tracks.*.experiment_id` |
| 2026-10-03 | 6/12/20 are **RESEARCH TARGETS only**; ≤3/≤10/≤25 % DD budgets removed from bands | `ADR-548` item 6a; `tier_bands.json._note` |
| 2026-10-04 | Published rate rounds DOWN | `ADR-563` (owner, Telegram) |

The separate repo `~/Documents/earn-defi` (BTC Signal Engine) has **no** Preserve/Core/Max Yield history: `git log --all -S` is empty. It only publishes `/btc-engine/*` into SPA `landing/public` via `deploy/publish_static_pages.sh`.

### 1.2 Mapping table

| PUBLIC PROFILE (now) | Legacy public name | Legacy id / S-ids | INTERNAL BOOK / engine | EFFECTIVE DATE | DECISION | TRACK SOURCE | STATUS (2026-10-05) |
|---|---|---|---|---|---|---|---|
| **Conservative** | Preserve (SUPERSEDED 07-11). Was `target-profile` 6 % on 06-19 | `strategy_config` id `preserve`. Backtest blend in `data/tier1_packages.json`: `s61_hybrid_income_shield`, `s27_stablecoin_carry`, `s62_yield_ladder_v2`, `s77_points_farming` | Main book `spa_core/paper_trading/cycle_runner.py` → `data/equity_curve_daily.json`, RiskPolicy v1.0, kill −5/−10 % | evidenced anchor 2026-06-22; label from 07-11 | ADR-OWN-2026-07 + `6ca6cf282` | `generate_track_snapshot.py` → `track_snapshot.paper_apy_pct` → `build_site_numbers.py` → `site_numbers.headline.apy` | `REPORTABLE`, 104 valid days (`/api/v1/packages/status`). Realized 4.90 % compound (prod snapshot 10-05); public 4.9 % (shelf 10-01) |
| **Balanced** | Core (SUPERSEDED 07-11). Was the paper-tracked flagship 06-19…07-11 | id `core`. Earlier: "Engine B — HY/carry sleeve" (`/api/strategy-lab` `engine_b`), sleeve "B" | `hy_cycle.py` → `data/hy_paper_trading.json`, outside RiskPolicy, stop −8 % from experiment peak | book 2026-08-24 (ADR-125); current experiment 2026-10-02 | ADR-125, ADR-531, ADR-533, ADR-548 | `_sleeve_paper_track()` → `track_snapshot.paper_tracks.balanced` → `site_numbers.books.balanced` | `ACCUMULATING`, 4 v2 days; 39 v1 days DISTORTED. Public: "accumulating", no number |
| **Aggressive** | Max Yield (SUPERSEDED 07-11). Was `coming-soon` 15 % | id `max-yield`. Earlier: "Engine C — LP sleeve" (`engine_c`), sleeve "C"; also the separate **Aggressive Lab** (10 research books) | `lp_cycle.py` → `data/lp_paper_trading.json` (lending + simulated sUSDe/PYUSD loop), stop −25 % | book 2026-08-24; experiment 2026-10-02 | ADR-125, ADR-533, ADR-548 | same path, `paper_tracks.aggressive` | `ACCUMULATING`, 4 v2 days, evidence L2, refused for live |

Residual name defects:
- `scripts/tier_paper_rollup.py:7` calls the Conservative track "Core" (audit `docs/audits/defi_gap_2026-10-01/1_packages_site.md` §A).
- `generate_track_snapshot.py:80,343` comments still say "Preserve/Core/Max-Yield".
- `strategy_config` ids remain the legacy slugs.

---

## 2. APY root cause: "the higher-risk package shows a lower %"

### 2.1 Where it is shown, measured

| Surface | Conservative | Balanced | Aggressive | Number type | As of | Status |
|---|---|---|---|---|---|---|
| **`/api/live/books`** (feeds `/admin/portfolio-summary` and the Telegram daily "📚 Пакеты") | **4.1483** | **−4.3571** | **1.3612** | "annualized_apy_pct" = REALIZED_PAPER, **linear** `return_pct·365/days`, whole book life incl. 39 DISTORTED v1 days | 2026-10-05 08:17Z | **LIVE NOW, inverted** |
| site `/packages`, home cards (weekly shelf `site_numbers.books`) | 4.92 / 4.96 / 4.97 / 5.01 | −3.44 (09-27) · −1.13 (09-20) · −0.69 (09-19) · 2.8 (09-13) | 2.83 · 4.59 · 4.93 · 7.62 | REALIZED_PAPER compound | shelves `ef111ccec`, `c315958c7`, `6916ba90a`, `4811c3ee3` | Inverted from the 09-13 shelf (Balanced < Conservative) and 09-19 (Aggressive < Conservative). **Removed** by `1a2d79252` (10-01) |
| daily `track_snapshot.paper_tracks` (origin history) | ~4.9–5.0 | 4.51 → −4.35 | 8.92 → 2.13 | REALIZED_PAPER compound | 09-11 … 10-01 | Aggressive < Conservative from snapshot `6916ba90a` (09-19) |
| prod-local snapshot (not on origin) | 4.90 | **−7.08** (4 v2 days) | 6.45 (4 v2 days) | REALIZED_PAPER, 4-day annualised | 2026-10-05 06:01Z | Balanced still inverted; not public (30-day rule) |
| prod-local shelf (not on origin) | 4.909 | **−11.5** | 7.18 | same, 3 days | measured 10-04 | latent: the shelf carries numbers the page rule forbids showing |
| `/api/aggressive-lab/paper` (dashboard tab, `/aggressive-lab`) | — | — | 10 books, `return_pct` 0.19–1.6 % cumulative over 83–97 d (e.g. `leverage_loop` 0.19 % / 83 d, `lrt_neutral` −2.70 %) | REALIZED_PAPER cumulative | 2026-10-05 04:01Z | 8/10 research books below Conservative's pace |
| `/api/strategy-lab` (`/strategies` sleeve cards, dashboard "Sleeve comparison") | engine_a 3.43 | engine_b 8.33 | engine_c 8.87 | BACKTEST 2024-06-05→2026-06-24 | generated **2026-06-26** (101 d) | not inverted, but stale and badged "Active" |

### 2.2 Causal chain

1. **Cost-model defect (v1, ADR-530 P0-1).**
   - `sleeve_book.book_move_cost` charged full gas ($12/leg) on daily accrual-drift re-sizes, with no dust band.
   - Balanced paid $48/day against ~$14 yield; Aggressive paid $24/day.
   - Both books lost money by construction (`docs/audits/defi_gap_2026-10-01/1_packages_site.md` A1).
   - Balanced has 4 legs and so pays twice the gas of Aggressive. That made Balanced fall below even Aggressive.
2. **No yield premium exists in the observable universe.**
   - ADR-292 (`sleeve_book.py:271-273`, quoted in the audit): "обе книги дадут примерно столько же, сколько консервативная, потому что 12 % и 20 % в наблюдаемой вселенной нет".
   - ADR-125: "агрессия = концентрация + широкий бюджет просадки, а НЕ directional-риск".
   - So gross ≈ 5 % in all three, and any cost difference flips the order.
3. **Owner surfaces never adopted the ADR-531 fix.**
   - `spa_core/reporting/books_summary.py::_book_from_seed_equity` uses `seed_equity` → `equity` with a linear annualisation over `(now − _accrual_anchor_date)`.
   - It has no `economics_model`, `experiment_id` or `reportable_after` filter.
   - Result: `/api/live/books` and `daily_telegram_report._books_lines` (`~X% год.`) still print the distorted inverted figures.
   - The response also stamps `start_date: 2026-06-22` on all three books, while the B/A books began 2026-08-24.
4. **Short-window annualisation (v2).**
   - Balanced paid a $67.91 rebalance on 2026-10-03 (turnover $24,892, `hy_paper_trading.json`); 4-day compounding turns that into −7 %.
   - The snapshot/shelf gate is **≥2 bars** (`generate_track_snapshot.py` `_sleeve_paper_track`: `if len(honest) >= 2`), not 30. Only the page layer (`package_status.history.reportable_after = 30`) suppresses it.

### 2.3 Governing product decision

- Accepted: the **6/12/20 % ladder is a research TARGET**, not a realized or expected ladder:
  - ADR-OWN-2026-07 "up to {max}%"
  - ADR-548 6a "RESEARCH TARGETS only"
  - `tier_bands.json`
- `data/tier1_packages.json` defines a **different target ladder** for backtest packaging: [2,6] / [6,12] / [12,999], with `max_dd_limit_pct` 3 / 10 / 25.
  - It is still served at `/api/tier1/packages`, although ADR-548 removed the 3/10/25 budgets from the site.
- **No ADR asserts that realized APY must be monotone in risk.** The inversion is therefore a *truth/labelling* problem (UNKNOWN whether the owner expects a monotone ladder), not a policy breach. Recommendation: owner question under предмет №2.

---

## 3. Field-level reconciliation

AGE is relative to 2026-10-05 08:15Z. Prod canonical = `~/Documents/SPA_Claude/data` + prod snapshot 2026-10-05T06:01Z.

| # | PUBLIC FIELD | PUBLIC VALUE | EXPECTED CANONICAL SOURCE | CANONICAL VALUE | AS_OF | AGE | VERDICT | SEV |
|---|---|---|---|---|---|---|---|---|
| 1 | Home hero "Conservative realized" | 4.9 % (measured 2026-10-01) | shelf `headline.apy` ← snapshot `paper_apy_pct` | 4.9165 (origin shelf); 4.9032 (prod 10-05) | 10-01 | 4 d (weekly cadence) | MATCH (floor) | — |
| 2 | Home "Current APY" (Transparency), static | ~4.9 % | same | 4.9165 | 10-01 | 4 d | MATCH | — |
| 3 | Home "Current APY" after JS (`loadHealth` → `/api/health-public.ytd_apy_pct`) | ~4.2 % | track-to-date compound | 4.9032 | 10-05 | 0 | **MISMATCH**: single-day accrual (`cycle_runner.py:2556` `_apy_accrued_pct`) labelled "ytd … annualized, not a daily figure" | **HIGH · PRODUCT_TRUTH_INCIDENT** |
| 4 | Home "Max drawdown" after JS | "—" (static −0.04 %) | snapshot `max_drawdown_pct` | −0.0393 | 10-05 | — | MISMATCH: `health-public` reads `tear_sheet.json` (frozen 2026-06-30, key `drawdown` not `max_drawdown_pct`) → null | MEDIUM |
| 5 | Home "Evidenced days" | 100 static → 104 live | `golive_status.real_track_days` | 104 | 10-05 | 0 | MATCH live / static stale by design | LOW |
| 6 | Home "Go-live progress" / gates | 29/29 | `golive_status` | 29/29 | 10-05 | 0 | MATCH | — |
| 7 | Home Conservative card "Paper result" | 4.9 %, "100 days … measured 2026-10-01" + "101 valid days" | shelf + `package_status` | 104 days | 10-01/10-02 | 3–4 d | MATCH value; **two day counts on one card** (shelf vs status) | LOW |
| 8 | Home cards status (static, no-JS) | "data out of date — no confirmed run for 64.1 h" (all 3) | `/api/v1/packages/status` | RUNNING, last run 10-05 | 10-02 baked | 3 d | MISMATCH for no-JS/crawlers (baked from a stale `package_status`, publisher stuck §4) | MEDIUM |
| 9 | Home/`/packages` Balanced result | "accumulating, 1 of 30" static → 4 live | `package_status.history.valid_periods` | 4 | 10-05 | 0 | MATCH live | — |
| 10 | Balanced/Aggressive target | "up to 12 %" / "up to 20 %" | `tier_bands.json` (ADR-548 6a) | 12 / 20 TARGET | 10-03 | — | MATCH (TARGET labelled) | — |
| 11 | Calculator "$50,000 → ~$2,458/yr" | 4.9165 % applied | ADR-563 floor (4.9 %) | 50,000 × 4.9 % = $2,450 | 10-01 | 4 d | MISMATCH (+$8 above the floored rate; ADR-563 spirit) | LOW |
| 12 | Home "Bank savings ~0.4 %", "US T-bills ~3.5 %" | literals `index.astro:118,122` | none declared | RWA floor 3.43 (`/api/strategy-lab rwa_floor`, June) | — | — | UNKNOWN (magic numbers, no as-of) | LOW |
| 13 | Dashboard "Paper APY", static | 4.92 % | shelf 4.9165, ADR-563 floor | 4.9 | 10-01 | 4 d | MISMATCH: `toFixed(2)` rounds UP 4.9165 → 4.92 (`DashboardSPAApp.jsx:50`) | LOW · ADR-563 breach |
| 14 | Dashboard "Paper APY", live | 4.22 % | `paper_apy_pct` | 4.9032 | 10-05 | 0 | **MISMATCH**: `/api/ssot/facts` has no `paper_apy_pct` → falls back to `apy_today_pct` (`DashboardSPAApp.jsx:288`) | **HIGH · PRODUCT_TRUTH_INCIDENT** |
| 15 | Dashboard NAV (live) | $101,525.98 | `paper_trading_status.current_equity` | 101,525.98 | 10-05 | 0 | MATCH. `/api/ssot/facts.nav` 101,564.39 = stale nav-proof (`reconciliation_ok false`, Δ $50.15 = the 09-11 cost) | LOW |
| 16 | Dashboard "Track days" | 100/30 → 104 | golive | 104 | — | — | MATCH | — |
| 17 | `/api/live/books` Conservative | 4.1483 % | compound track | 4.9032 | 10-05 | 0 | MISMATCH (linear formula) | MEDIUM |
| 18 | `/api/live/books` Balanced / Aggressive (+ Telegram "~X% год.") | −4.3571 / 1.3612 | v2-only, ≥30-day reportable | not reportable (4 d) | 10-05 | 0 | **MISMATCH: distorted v1 rows, not maturity-gated → inversion** | **HIGH · PRODUCT_TRUTH_INCIDENT** (owner-facing) |
| 19 | `site_numbers.packages.conservative.apy` | 3.7 `kind: замер`, annualisation "from track anchor" | `tier1_packages.blended_net_apy_pct` (BACKTEST) | 3.709 BACKTEST | 10-05 | — | **MISLABEL** (BACKTEST tagged as measurement) | MEDIUM · PRODUCT_TRUTH_INCIDENT (latent) |
| 20 | `/packages` Conservative tail "Worst drawdown x % realized to date" | from `snap.packages.dd_pct` (`packages.astro:81-94`) | realized `max_drawdown_pct` | −0.0393 realized vs 0.047 BACKTEST | — | — | MISLABEL (backtest DD printed as realized; rounding hides it) | MEDIUM |
| 21 | `/api/tier1/packages` Conservative | 3.709, bands [2,6]/[6,12]/[12,999], DD limits 3/10/25 | labelled backtest | — | 10-05 04:30Z | 4 h | MATCH as BACKTEST; ladder diverges from ADR-548 6a | LOW |
| 22 | `/api/strategy-lab` (sleeve cards "Active") | engine_b 8.33, engine_c 8.87, engine_a 3.43 | — | BACKTEST, `generated_at` 2026-06-26 | 06-26 | 101 d | STALE | MEDIUM |
| 23 | `/strategies/balanced` "Aave V3 ~3.5 % · Compound V3 ~4.8 % · Morpho Steakhouse ~6.5 %" | literals `balanced.astro:122-130` | `apy_ranking.json` live | compound_v3 3.80 % (allocation auditor 10-05); others UNKNOWN | 10-05 | — | MISMATCH / magic numbers | MEDIUM |
| 24 | `/packages` "tail in numbers: 15 % vs the real ~4.9 %" | 15 % = leverage-loop headline backtest | `leverage-loops.astro` `LL.headline_apy_pct` (literal 15.0) | BACKTEST headline | — | — | OK as illustrative; literal in page | LOW |
| 25 | `/packages` Balanced "Pendle principal tokens (today PT-sUSDS)" | copy | `package_status` decision | "no PT bought — waiting for entry" | 10-02 | — | MISMATCH copy vs state | LOW |
| 26 | `/packages` "Join early-access to get in the day it clears" | copy | ADR-548 item 5 / site-copy solicitation rule | removed elsewhere (`/snapshot`) | — | — | MISMATCH (solicitation-adjacent; предмет №2) | MEDIUM |
| 27 | Kill-switch soft/hard | −5 % / −10 % | `constitution.json` ← ADR-034/048 | 5 / 10 | — | — | MATCH | — |
| 28 | `/api/aggressive-lab/paper` books | `return_pct` cumulative; roster `net_apy_pct` = cumulative return mislabelled APY (audit B6, `roster.py:229-233`) | — | — | 10-05 | — | UNKNOWN whether any page still prints it as APY (renderer uses `return_pct`) | LOW |

---

## 4. Publication pipeline

```
cycle_runner (08:00 local)  → data/equity_curve_daily.json, golive_status.json, paper_trading_status.json
  └ in-process: generate_track_snapshot → prod landing/src/data/track_snapshot.json   (works: log "track_snapshot.json regenerated")
run_daily_paper_cycle.sh:133 → scripts/deploy_site_snapshot.py
  └ subprocess scripts/generate_track_snapshot.py → **ModuleNotFoundError 'spa_core'** (10-02, 10-03, 10-04, 10-05)
  └ (would) safe_site_push.py → origin/main landing/** → CF Pages git build (+ GitHub Pages job in deploy-landing.yml)
orchestrator step (1е) build_site_numbers.py --if-due → prod landing/src/data/site_numbers.json (10-04, untracked) — NOT on origin
site_freshness_monitor (com.spa.site_freshness, every 6 h) reads the PROD-LOCAL shelf → PUBLISHER_STUCK CRITICAL, "fix at Cloudflare"
```

- **Why WARNING.**
  - `agent_health.json`: `com.spa.site_freshness` status WARNING, `last_exit=1`.
  - `data/site_freshness_report.json` (05:01Z) has 5 fails: 4× `SITE_BEHIND_SNAPSHOT` (site as-of 10-01 vs shelf 10-04; 100 vs 103 days) and 1× `PUBLISHER_STUCK` CRITICAL (lag 3, site age 101 h). A Telegram alert was sent (msg 10602).
- **The real defect sits in the producer leg, not in Cloudflare.**
  - Origin shelf `1a2d79252` (10-01, next 10-08) is *within cadence*.
  - The prod-local shelf has its own tact (10-04 → next 10-12) and was never delivered.
  - Daily snapshots stopped reaching origin after 10-02 (last origin snapshot `7b3ef0016`, generated 10-02 02:06Z, carried in by a session commit, not by the custodian).
  - This repeats the ADR-478 lesson: wrong operand, wrong remedy text. It also repeats the ADR-148 import class.
- **Duplicated number sources** (all for "Conservative APY"):
  - `paper_apy_pct` (compound)
  - `apy_today_pct` (one day)
  - `books_summary.annualized_apy_pct` (linear)
  - `tier1_packages.blended_net_apy_pct` (backtest)
  - `paper_tracks.conservative.apy_pct` (compound, 2 dp)
  - `SSOT key_facts` (has no paper_apy)
- **Two deploy paths.** `deploy-landing.yml` comments "CANONICAL = Cloudflare Pages git integration" but runs `actions/deploy-pages@v4` (GitHub Pages). The live host serves via Cloudflare (`cf-ray`).
- **Magic numbers:** `index.astro:118,122` (bank/T-bill), `balanced.astro:122-130` (per-protocol APYs), `leverage-loops.astro:39-40` (15.0/−8.95), `tier_bands.json.dd_short_*` literal "0.0% (live)", "~4.5%", "~50%". The provenance tool reports `UNDECLARED 0` (`no_claims 76 · declared 19 · sourced 46`), so these pass as "not about us" or declared.

---

## 5. Defects (classified)

| ID | Defect | Class | Sev | Evidence | Recommended |
|---|---|---|---|---|---|
| D1 | Owner surfaces (`/api/live/books`, Telegram "📚 Пакеты", `/admin/portfolio-summary`) show Balanced −4.36 % / Aggressive 1.36 % < Conservative 4.15 %, from distorted v1 rows, linear annualisation, no maturity gate | **PRODUCT_TRUTH_INCIDENT** | HIGH | live API 08:17Z; `books_summary.py:75-104`; `daily_telegram_report.py:480-505` | REPAIR: reuse `_sleeve_paper_track` semantics (v2 + experiment + reportable) |
| D2 | Home "Current APY" and dashboard "Paper APY" overwritten with the single-day accrual rate (4.22 %), labelled annual/ytd | **PRODUCT_TRUTH_INCIDENT** | HIGH | `misc.py:200-225`, `index.astro:620-628`, `DashboardSPAApp.jsx:288`, `/api/ssot/facts` | REPAIR: expose `paper_apy_pct` in health-public/ssot; drop the day-rate fallback |
| D3 | Snapshot deploy broken since 10-02 (`ModuleNotFoundError`); prod shelf 10-04 not delivered; site frozen at 10-01 | PIPELINE | HIGH | daily_cycle logs 10-02…10-05 | REPAIR (sys.path / module run) |
| D4 | `site_freshness` operand = prod-local shelf; remedy text points at Cloudflare | MONITOR_MISDIAGNOSIS | MEDIUM | `site_freshness_monitor.py:571-575`; report 05:01Z | REPAIR: compare to origin shelf, name the producer |
| D5 | `site_numbers.packages.*` = tier1 BACKTEST tagged `kind: замер` with track annualisation; `/packages` prints backtest DD as "realized" | PRODUCT_TRUTH_INCIDENT (latent) | MEDIUM | `build_site_numbers.py:254`, `generate_track_snapshot.py:77-92`, `packages.astro:81-94` | REPAIR: relabel as BACKTEST or drop |
| D6 | Sleeve APY gate is ≥2 bars in snapshot/shelf (−11.5 % in prod shelf) while the page rule is 30 | LATENT | MEDIUM | `generate_track_snapshot.py` `_sleeve_paper_track` | REPAIR: null until `reportable_after` |
| D7 | `/api/strategy-lab` backtest 101 d stale, rendered as "Active" cards | STALE | MEDIUM | `generated_at` 2026-06-26 | RECONNECT or SUPERSEDED |
| D8 | `health-public.max_drawdown_pct` from `tear_sheet.json` (frozen 06-30) → home DD "—" | STALE | MEDIUM | `tear_sheet.json` mtime 2026-06-30 | RECONNECT |
| D9 | ADR-563 floor not applied: dashboard 4.92 %, calculator $2,458 | ROUNDING | LOW | `DashboardSPAApp.jsx:50` | REPAIR |
| D10 | Hardcoded per-protocol APYs on `/strategies/balanced`; bank/T-bill literals on home | MAGIC_NUMBER | MEDIUM/LOW | page lines above | REPAIR (render from ranking) or declare illustrative with date |
| D11 | Solicitation-adjacent "get in the day it clears" still on `/packages` | LEGAL_COPY (предмет №2) | MEDIUM | `txt_packages.txt:162,168` | owner card |
| D12 | Two target ladders ([2,6]/[6,12]/[12,999] + DD 3/10/25 in tier1 API vs 6/12/20 targets on site) | DUPLICATE | LOW | `/api/tier1/packages` | MERGE |
| D13 | Evidenced-book move Core→Conservative (07-11) recorded only in a commit message, no ADR | DECISION_GAP | LOW | `6ca6cf282` | backfill ADR |
| D14 | `deploy-landing.yml` deploys GitHub Pages while saying CF Pages is canonical | DUPLICATE | LOW | workflow lines 3-57 | UNKNOWN which serves; verify |

## 6. UNKNOWNs

- The exact surface where the owner saw the inversion. The candidates are D1 (live today) and the 09-13…09-27 public shelves. No owner message was found in the files I read.
- Whether the owner expects a monotone realized ladder. No ADR states it.
- The exact build time of the live CF deploy. Static "64.1 h" suggests a build at ≈2026-10-05 02:00Z; not verified.
- The live values of aave_v3 and morpho_steakhouse APY vs the `balanced.astro` literals.
- Whether any page still renders the Aggressive Lab roster `net_apy_pct` (cumulative return mislabelled as APY).
- I did not run the company-memory assembler: building its index would write `data/memory/index.db` into the mirror.
