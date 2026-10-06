# P1 · Profile lineage — public name ↔ internal book ↔ track source ↔ decision (RM-TRUTH-01)

Auditor: P1 (Product Truth), read-only. Code: `~/Documents/SPA_mirror` @ `b36acda46` (= origin/main,
verified by `A3_product.md`/`A2_capital.md`, not re-verified here). Builds on `A3_product.md` §1,
`A2_capital.md` (Core ambiguity, §6), `REVIEW_1.md` §3.1 ("Core" three meanings). Nothing written to
any repo tree; new evidence below was pulled by `git log`, `git show`, `grep` on the mirror and by
reading the already-captured live dumps in `scratchpad/rmtruth/live/`.

## 0. Narrative (what actually happened, in order)

1. **2026-06-19** — site launches with **Preserve / Core / Max Yield** (`strategy_config.json`,
   commit `0d3139e49`). Core is the flagship, `paper-tracked`, target 10%.
2. **2026-06-22** — the evidenced $100k paper track (`cycle_runner`) anchors. At this point the
   anchor is *not yet* bound to any single public name — see step 4.
3. **2026-07-11 22:03** — owner decision (recorded in `docs/decisions/ADR-OWN-2026-07-owner-decisions-batch.md`,
   backfilled 07-15; batch executed same day in commits `c1207ac26`, `d7395f46`, `d84ad71b`, `c63ee627`):
   **tier names become Conservative / Balanced / Aggressive everywhere**; APY display = "up to {max}%";
   tail always shown. This is the taxonomy decision — it does **not** say which of the three new names
   carries the live evidenced track.
4. **2026-07-11 22:30** (27 minutes later, same evening) — a second, narrower owner decision, commit
   `6ca6cf282` only, message "**UX-26 resolved (owner: Conservative is the evidenced book)**". Context
   that made this a live decision, not a rename detail: the live go-live book is *compositionally*
   T1+T2 (would read as Balanced), but *realizes* in the conservative range (~3.3-4.2%); two source
   files disagreed (`strategy_config.json` said Balanced=paper-tracked, `tier_bands.json`/`/packages`
   said Conservative=LIVE) — a live self-contradiction, laid out in
   `docs/SITE_TAXONOMY_NUMBERS_DECISION.md` ("UX-26 … needs 1 owner line"). The owner picked
   **Conservative** for the evidenced book. **No ADR document exists for this decision** — it lives only
   in the commit message and in the (consistent) code state it produced. §4 below drafts the backfill.
5. **2026-08-23/24** — ADR-125: Balanced (`hy_cycle`) and Aggressive (`lp_cycle`) start *actually*
   counting paper days (both had sat at 0 positions for ~920 cycles). Owner-approved clean $100k reset
   on 08-24.
6. **2026-10-01/02** — ADR-531 (sleeve-econ-v2) marks the 08-24→10-01 history of Balanced/Aggressive
   `DISTORTED` (gas-on-drift cost bug); ADR-533 (2026-10-02) re-versions both as new experiments
   (`balanced-fixed-carry-v1@2026-10-02`, `aggressive-susde-loop-v1@2026-10-02`), closing the old rows
   as `*-legacy-lending`.
7. **2026-10-03** — ADR-548 item 6a: 6/12/20% are **research targets only**, not expected or realized
   ladders; the ≤3/10/25% drawdown budgets glued to them are removed from the site (they remain in a
   *different*, still-served ladder — see §2).
8. **Throughout** — a parallel, uncoordinated id space exists: `S7` ("Diversified Max", equal-weight
   6-adapter strategy, `strategy_registry.py:266`) is stamped on every row of `data/paper_evidence.json`
   even though the live book runs `optimized_yield`/mandate `conservative-lending-v1` — internal-only
   mislabel, not public. Separately, `data/tier1_packages.json` packages a **backtest** blend of
   `s61_hybrid_income_shield` / `s27_stablecoin_carry` / `s62_yield_ladder_v2` / `s77_points_farming`
   under the label `"Conservative"` (`blended_net_apy_pct: 3.709`, `basis: "validated … backtest"`) —
   this is a *third* "Conservative" number, a BACKTEST, that reaches the public shelf mislabelled
   `kind: "замер"` (measurement) — already flagged by A2 finding #5 / A3 §5 D5/D19.
9. **`scripts/tier_paper_rollup.py`** (daily, 06:01, **no reader found** by grep in spa_core/scripts/
   landing — confirmed again below) defines a **fourth, conflicting** naming: `Core (~6%) = the LIVE
   go-live track` (i.e. what is now publicly called Conservative), and separately blends
   `aggressive_lab` strategies under the names `Balanced`/`Aggressive` — a mapping that has nothing to
   do with the `hy_cycle`/`lp_cycle` books that actually carry those names on the site today. This file
   is dead-but-present: it writes `data/tier_paper_rollup.json` and nothing reads it.

## 1. Mapping table (effective-dated)

| # | PUBLIC PROFILE (now) | Legacy public name | Legacy id / S-id | INTERNAL BOOK / ENGINE | TRACK RECORD SOURCE | EFFECTIVE DATE | DECISION | STATUS |
|---|---|---|---|---|---|---|---|---|
| 1 | — (pre-taxonomy) | Preserve / Core / Max Yield | `strategy_config` ids `preserve`/`core`/`max-yield` | site content only, no book bound yet | n/a | 2026-06-19 | commits `33d09c29b`/`0d3139e49` | SUPERSEDED (07-11) |
| 2 | — | — | — | main book `cycle_runner.py` (anchor only, name not yet assigned) | `equity_curve_daily.json` | 2026-06-22 | n/a (anchor event, not a naming decision) | CURRENT (anchor itself) |
| 3 | **Conservative / Balanced / Aggressive** (taxonomy) | replaces Preserve/Core/Max Yield | `tier_bands.json` keys `conservative`/`balanced`/`aggressive` | n/a (naming layer) | n/a | 2026-07-11 22:03 | `ADR-OWN-2026-07-owner-decisions-batch.md` ("Tier naming"); executed `c1207ac26`, `d7395f46`, `d84ad71b`, `c63ee627` | CURRENT |
| 4 | **Conservative** | was "Core" candidate per T1+T2 composition (rejected) | `strategy_config` id `conservative` | main book, `cycle_runner.py` → `allocator`/`risk/policy.py`/`governance/kill_switch.py`, mandate `conservative-lending-v1` (ADR-533) | `equity_curve_daily.json` (canonical) · `track_snapshot.json → paper_apy_pct` · site shelf `site_numbers.headline.apy` | 2026-07-11 22:30 (label bound to the pre-existing 06-22 anchor) | commit `6ca6cf282` message only, **no ADR** — backfill drafted §4 | CURRENT, but see residue R1–R3 |
| 5 | **Balanced** | was "Core" 06-19→07-11 (flagship); "Engine B — HY sleeve" pre-ADR-125 | `strategy_config` id `balanced`; earlier `engine_b` | `hy_cycle.py` → `data/hy_paper_trading.json`, outside RiskPolicy, mandate `balanced-fixed-carry-v1` | `_sleeve_paper_track()` → `track_snapshot.paper_tracks.balanced` → `site_numbers.books.balanced` | book start 2026-08-24 (clean reset); current experiment 2026-10-02 | ADR-125 (2026-08-23), ADR-531 (2026-10-01), ADR-533 (2026-10-02), ADR-548 (2026-10-03) | ACCUMULATING (4 valid v2 days as of 10-05) |
| 6 | **Aggressive** | was "Max Yield" (coming-soon, 06-19); "Engine C — LP sleeve" pre-ADR-125 | `strategy_config` id `max-yield`/`aggressive`; earlier `engine_c`; also the unrelated **Aggressive Lab** (10 research books, different system) | `lp_cycle.py` → `data/lp_paper_trading.json`, mandate `aggressive-susde-loop-v1` | same path, `paper_tracks.aggressive` | book start 2026-08-24; current experiment 2026-10-02 | ADR-125, ADR-531, ADR-533, ADR-548 | ACCUMULATING (4 valid v2 days) |
| 7 | *(label "Conservative" reused for a different number)* | n/a | `s61_hybrid_income_shield`/`s27_stablecoin_carry`/`s62_yield_ladder_v2`/`s77_points_farming` | `data/tier1_packages.json` backtest packager (`basis: "validated … backtest"`) — **not** `cycle_runner` | `tier1_packages.blended_net_apy_pct` = 3.709 → `generate_track_snapshot.py::_tier_packages()` → `track_snapshot.packages.conservative` → `site_numbers.packages.conservative.apy` (mislabelled `kind: "замер"`) | generated continuously (last 2026-10-05T04:30Z); no single "effective date" — a live backtest re-run, not a decision | no ADR asserts this blend represents "Conservative"; it is a packaging convenience that collided with the taxonomy name | **AMBIGUOUS** (same word, different number, different evidence class — BACKTEST vs REALIZED_PAPER) |
| 8 | *(internal id collision, not public)* | n/a | `S7` "Diversified Max" (`strategy_registry.py:266`, equal-weight 6-adapter strategy) | stamped on every row of `data/paper_evidence.json` (88 rows) | n/a — the live book's actual model is `optimized_yield`, mandate `conservative-lending-v1` (`current_positions.json`) | stamped since the file's first row; not re-dated by any decision | no ADR; looks like a copy-paste default from an earlier harness | **AMBIGUOUS / internal defect** (wrong label, not a naming decision) |
| 9 | *(dead naming layer, not public, not internal-live either)* | `tier_paper_rollup.py` comment: "Core (~6%) = the LIVE go-live track" = today's Conservative; separately blends `aggressive_lab` strategies as "Balanced"/"Aggressive" | n/a | `scripts/tier_paper_rollup.py` → `data/tier_paper_rollup.json` | n/a — **confirmed again by this audit: no reader found** (`grep -rln tier_paper_rollup --include=*.py spa_core scripts landing` → only the writer itself and its own plist/shell wrapper) | written daily 06:01, unchanged in meaning since it was authored | no ADR; the file's own docstring states the mapping as fact ("the owner asked to see") but no linked decision found | **LEGACY_ALIAS / UNKNOWN_PURPOSE** — a fourth definition that nothing consumes |
| 10 | `/strategies/preserve`, `/strategies/core`, `/strategies/max-yield` (URLs) | legacy slugs | n/a | static `noindex` meta-refresh redirect pages → `/strategies/{conservative,balanced,aggressive}/`, `rel=canonical` set correctly | n/a | present since the 07-11 batch (exact commit not individually dated; verified live 2026-10-05) | part of ADR-OWN-2026-07 batch execution | CURRENT / **harmless alias** (confirmed: redirect targets match the §1 row 4-6 mapping exactly) |
| 11 | `tier_bands.json.*.alt_en/alt_ru` = "Preserve"/"Core"/"Max Yield" | legacy display names kept as a documented alias field | n/a | `landing/src/lib/tier_bands.json` | n/a | present since the 07-11 batch; file's own `_note` field documents the 07-11 and 10-03 decisions inline | part of the same ADR-OWN-2026-07 batch | CURRENT / **harmless alias, and dead**: confirmed by this audit — `grep -rn "alt_en\|alt_ru" landing/src` → **zero** references outside the file that defines them. No page renders it. |

## 2. Residue inventory — classified

Scope: every place the legacy names (Preserve/Core/Max Yield) or a conflicting "Core" meaning survive
today, on public surfaces (live site pages, public API JSON) and owner surfaces (Telegram, Mission
Control / owner_remote).

| ID | Where | What it is | Classification | Why |
|---|---|---|---|---|
| R1 | `landing/src/lib/tier_bands.json` fields `alt_en`/`alt_ru` ("Preserve", "Core", "Max Yield") | Legacy alias field, documented in-file (`_note`) as owner choice history | **harmless alias** | Confirmed zero readers in `landing/src` (grep). Cannot mislead a visitor because it is never rendered. |
| R2 | `/strategies/preserve/`, `/strategies/core/`, `/strategies/max-yield/` live URLs | `noindex`, immediate meta-refresh + `canonical` to the current slug | **harmless alias** | Verified live (`page_strategies_preserve.html` etc. in `live/`): redirects to the correct current name 1:1 (preserve→conservative, core→balanced, max-yield→aggressive — matches the owner's 07-11 decision exactly, not a stale mapping). |
| R3 | `data/tier1_packages.json` + `site_numbers.packages.conservative` — a **BACKTEST** blend (s61/s27/s62/s77) labelled "Conservative" and `kind: "замер"` | Public API (`/api/tier1/packages` returns it live) and public shelf number | **misleading → Product Truth defect, owner subject №2 (public number)** | This is not a naming residue, it is a *second, different* number sharing the "Conservative" name with the real evidenced track (4.90% REALIZED_PAPER) while itself being a backtest (3.709% estimated-with-method) printed as a measurement. Already raised as A2 #5 / A3 D5/D19; carried here because the *lineage* question ("who decided 'Conservative' means this blend") has no decision owner — it is AMBIGUOUS by drift, not by design. |
| R4 | `data/paper_evidence.json` rows all stamped `strategy_id: "S7"` ("Diversified Max") | Internal evidence file, not public, not owner-dashboard-rendered as a strategy name (owner sees NAV/APY numbers, not the S7 id, on the surfaces checked) | **internal only** | Wrong label but confirmed not surfaced to the owner by name in Telegram/Mission Control/dashboard (grep: zero hits for "S7"/"Diversified Max" in `spa_core/telegram`, `spa_core/owner_remote`, `spa_core/studio_os`). Still a data-integrity defect (A2 #3), just not a naming-residue defect. |
| R5 | `scripts/tier_paper_rollup.py` → `data/tier_paper_rollup.json` ("Core (~6%) = the LIVE go-live track" + aggressive_lab blends relabelled Balanced/Aggressive) | Writer runs daily (`agent_aggressive_lab.sh`), output file exists, but **no reader anywhere** (re-confirmed this audit) | **internal only / dead** (not "misleading" in practice because nothing reads it to display it) | If a reader is ever added without reviewing the file's docstring literally, it would silently resurface the pre-07-11 "Core" meaning and a fourth definition of Balanced/Aggressive. Recommend RECONNECT-by-ADR-or-delete, per `REVIEW_1.md` §8 and A2 §12 — not touched here (read-only). |
| R6 | `spa_core/reporting/report_sections.py:65` — static tournament fallback catalogue entry `"S3", "T2 Max Yield"` | Internal strategy-tournament id list (`S0`-`S12`, a *third*, independent id namespace unrelated to `strategy_registry.py`'s `S0`-`S10`), used only when `tournament_results.json` is absent | **false positive — not a taxonomy residue** | Checked: this "Max Yield" is a coincidental substring in an unrelated strategy name, not a reference to the legacy public tier. No caller renders it as a product-tier label (grep of callers: `analytics_runner.py`, `_untiered_census.py`, tests). Listed here only to close the grep, not as a defect. |
| R7 | Telegram daily report / humanize.py / Mission Control / owner_remote | Checked directly: `grep -rn "Preserve\|Max Yield\|Max-Yield" spa_core/telegram spa_core/owner_remote spa_core/studio_os` → **zero hits**. `grep -rn "Core" spa_core/telegram` → one hit, `"SPA Core Agent DOWN:"` (an infra alert string, unrelated to the product tier) | **harmless / not a residue at all** | Owner-facing bot and Mission Control do not carry the legacy tier names. The live inversion/mislabel problems on owner surfaces (Telegram "📚 Пакеты", `/admin/portfolio-summary`) are a *numbers* defect (A3 D1), not a *naming* residue — out of this task's scope, cross-referenced only. |

**Net reading:** the **naming** migration (Preserve/Core/Max Yield → Conservative/Balanced/Aggressive)
is clean and complete on every surface checked — public pages, redirects, owner bot, Mission Control.
The only genuine defects that survive are (a) **R3**, a different number colliding with the
"Conservative" name (owner subject №2, already flagged elsewhere, cross-referenced not re-opened), and
(b) **R5**, a dead file that still encodes the *pre-decision* meaning and would resurrect it if ever
wired up. Neither is a case of the owner's 07-11 decision being disobeyed; both are leftover plumbing
the decision never touched.

## 3. "Core" — full disambiguation (closes `REVIEW_1.md` §3.1's three-meanings note, adds a fourth)

| Meaning | Where | Status |
|---|---|---|
| (1) 06-19 site flagship ("Core", 10% target, paper-tracked) | `strategy_config.json` pre-07-11 | SUPERSEDED 2026-07-11 by taxonomy decision |
| (2) ADR-125 "пакет Core" = today's **Balanced** | `ADR-125` narrative text | CURRENT (ADR-125 uses "Core" as a colloquial stand-in for the already-renamed Balanced book; not a separate decision) |
| (3) `tier_paper_rollup.py` "Core (~6%) = the LIVE go-live track" = today's **Conservative** | `scripts/tier_paper_rollup.py` docstring/comment | LEGACY_ALIAS, dead (no reader) — see R5 |
| (4) `tier_bands.json.balanced.alt_en` = "Core" | `landing/src/lib/tier_bands.json` | LEGACY_ALIAS, dead (no reader) — see R1 |

Meanings (3) and (4) agree with each other's *target* (both point at the pre-07-11 name for the
*respective* tier they sit on: rollup's "Core"→Conservative-slot, tier_bands' "Core"→Balanced-slot) —
they are not internally contradictory as *aliases of the 06-19 scheme*, but they map to **different
public tiers** (rollup: Core=tier formerly called Conservative's live book; tier_bands: Core=alt name
*for* Balanced). This is exactly the pre-07-11 confusion (`strategy_config` said Balanced-composition
book was paper-tracked flagship "Core", while `tier_bands`/`/packages` said the evidenced book was
"Conservative") preserved verbatim in two dead files, which is why REVIEW_1 counted it as live-feeling
even though neither file is read. No action needed beyond what R5/R1 already recommend (read-only here).

## 4. Backfill ADR — draft text (number to be assigned by the integrator)

```markdown
# ADR-<TBD> · Backfill: Conservative is the evidenced go-live book (UX-26, 2026-07-11)

- **Status:** Accepted (backfilled <integrator fills date>, from commit message only — no ADR existed)
- **Date of decision:** 2026-07-11 22:30 CEST
- **Author/approved by:** owner
- **Executed by:** commit `6ca6cf282` ("UX-26 resolved (owner: Conservative is the evidenced book)")
- **Related:** ADR-OWN-2026-07-owner-decisions-batch.md (same-day taxonomy decision, 22:03, 27 min
  earlier — names the three tiers but does not say which carries the evidenced track);
  `docs/SITE_TAXONOMY_NUMBERS_DECISION.md` (the investigation that produced the owner question, "UX-26")

## Context

Same evening as the Conservative/Balanced/Aggressive taxonomy decision, the site carried a live
self-contradiction: `strategy_config.json` said the evidenced, paper-tracked flagship was
**Balanced** (by composition: the live go-live book holds T1+T2 — aave_v3 + pendle + susde + morpho,
~$100,379 equity), while `tier_bands.json` and `/packages` said the evidenced, LIVE book was
**Conservative** (by realized return: ~3.3-4.2% at the time, which reads as conservative-range).
Three signals said Conservative, two said Balanced. `docs/SITE_TAXONOMY_NUMBERS_DECISION.md` laid out
both readings and asked the owner to pick one, explicitly flagging it as a product-definition /
public-claim decision (owner subject — public numbers), not something the agent should infer.

## Decision

**The evidenced $100k go-live paper track (anchor 2026-06-22, `cycle_runner.py`) is publicly labelled
Conservative.** Composition (T1+T2 mix) does not override realized-return framing for the public tier
label. `strategy_config.json` was aligned same day: `conservative` → "Paper Tracked · evidenced",
`balanced` → "Research / Paper", `max-yield` → "Research · refused". The homepage Conservative card
became green "Paper-tracked · evidenced"; the Balanced card became amber "Research / paper · not in
go-live track".

## Consequences

- Every surface agreed, as of 2026-07-11 22:30, on exactly one meaning of "the evidenced book":
  Conservative. This ADR backfills the record so that meaning has a decision document, not only a
  commit message.
- This decision does **not** cover what number represents "Conservative's APY" day to day — that is a
  separate, still-open set of defects (three/four live numbers for the same book: `paper_apy_pct`
  compound, `apy_today_pct` single-day, `books_summary.annualized_apy_pct` linear,
  `tier1_packages.blended_net_apy_pct` backtest — see RM-TRUTH-01 A2 finding #5, A3 §2/§5 D1/D2/D5,
  and this report's §1 row 7 / §2 R3). Those are number-provenance defects, governed by
  `.claude/rules/site-numbers.md`, and are explicitly out of scope for this backfill.
- `scripts/tier_paper_rollup.py` and `tier_bands.json.alt_en/alt_ru` still encode the *pre-decision*
  "Core = the live go-live track" framing as dead text (no reader on the rollup file; no renderer for
  the alias fields). This ADR does not require their deletion — flagged to the owner-subject queue as
  RECONNECT-or-ARCHIVE (already named in `REVIEW_1.md` §3.2 item 8 and A2 §12); not actioned by a
  read-only audit.

## Acceptance

`strategy_config.json.conservative.status == "evidenced"` AND
`landing/src/pages/packages.astro` + home Conservative card both render "LIVE · evidenced" for the
Conservative tier, as they do today (verified live, `page_packages.html`/`page_home.html`,
2026-10-05).
```

## 5. UNKNOWNs (named, not guessed)

1. Whether the owner has ever seen `scripts/tier_paper_rollup.py`'s output or its "Core" framing since
   07-11 — if not, it is pure dead code, confirmed by this audit's own re-grep (no reader).
2. Why `data/tier1_packages.json`'s backtest blend was ever allowed to publish under the key
   `"conservative"` identical to the live track's public name — no commit or ADR discusses this
   specific collision; it looks like independent authorship of a backtest-packaging script that reused
   the taxonomy's key names without coordinating with the 07-11/UX-26 decisions. NOT MEASURED further
   here (would require git-blaming `tier1_packages` generator authorship, out of this task's slice).
3. Exact commit/date `/strategies/{preserve,core,max-yield}.astro` redirects were added — the batch
   commits (`c1207ac26`, `d7395f46`, `d84ad71b`, `c63ee627`) were not individually diffed for this file;
   confirmed only that the files exist today and are correct.
