# ADR-590 · Canonical Trading Research lineage + BTC systems disposition (RM-TRUTH-01 · CAPITAL)

- **Status:** Accepted — implemented (worker W2, Trading Lab track; findings from worker C1, read-only).
- **Date:** 2026-10-05
- **Context ADRs:** ADR-525 (Trading Research Engine v0), ADR-102 (btc_cycle archive), ADR-118 (btc_nav),
  ADR-260 (SPA `/api/btc-engine` pass-through), ADR-554 (investment_cio), ADR-560 (research_factory),
  ADR-580 C7 (forward clocks immutable) and C10 (ledger backup coverage).
- **Boundary (ADR-285):** nothing here moves money, publishes a public yield number, renames a tier
  or deletes data. Everything below is agent-decidable except the two rows marked **OWNER** in
  "Owner-reserved".

## Context

SPA has had five BTC/trading systems: `research/btc_cycle`, SPA `btc_nav`, the earn-defi BTC Signal
Engine, the SPA Trading Research Engine v0, and the LOGOS desk — plus `strategy_lab` carry sleeves
and gold/anti-crisis placeholders alongside them. A reader could not tell which system is *the*
indicator lab. Two different things were both called "v0.3" with no namespace. Readers of the
engine's own `status.json` showed a forward-bar count off by one, and a daily backtest refresh was
quietly absorbing forward-paper bars into what it called out-of-sample evidence.

Measured 2026-10-05 11:04Z (worker C1, `C1_trading_canon.md`, read-only): the engine is healthy
(440/440 ok ticks, max gap 15.5 min, 138 chains / 6,394 observations verify); the forward clock has
never been reset (one registration time, 8 append-only triggers, 0 stage changes since 09-30); 5
candidates are `FORWARD_PAPER`, 0 `ROBUST`, 0 champions.

## Decision

1. **Canonical lineage.** The SPA **Trading Research Engine v0** (ADR-525; `spa_core/trading_research`,
   `com.spa.trading_research`, `data/trading_research/`) is the ONE canonical active lineage of the
   Owner's *Indicator & Directional Trading Lab*. Any new indicator, timeframe, asset or execution
   model enters as a new candidate identity (`family@vN` + `def_hash`) in this engine. No parallel
   indicator engine is to be built.

2. **Disposition of the other systems.**

   | System | Class | Consequence |
   |---|---|---|
   | earn-defi BTC Signal Engine | **SEPARATE_PRODUCT** | Not superseded by SPA and not merged into the Lab. The Lab card shows it only as a labeled external row (`earn-defi:btc_engine@<cfg>`, with its `system_mode`) and never adds it to Lab totals. Same BTC beta, so any future cross-sleeve view must de-duplicate exposure |
   | `research/btc_cycle` | **SUPERSEDED_HISTORY** (archive-as-evidence) | Keep the files and the ADR-102 numbers with their provenance and the label "champion v0.1 files never delivered; unreproducible". No code revival |
   | SPA `btc_nav` (ADR-118) | **SUPERSEDED_HISTORY** | Manifest `intent` corrected (fix C below). Code stays in place, uninstalled |
   | LOGOS desk | **BROKEN** (zombie since 2026-07-29), out of Lab scope | KILL or REPAIR is **OWNER** (outside every repo; its own README sets kill criteria) |
   | `strategy_lab` BTC/ETH sleeves | **LEGACY_REFERENCE** | Belongs to Market-Neutral/Basis, not the Lab. Not re-labeled by this ADR — separate card |
   | `gold_proxy_research` / `s20_anticrisis_research` | **UNKNOWN_PURPOSE** | Separate card — not addressed here |

3. **Namespacing.** Versions are always written qualified: `btc_cycle:v0.3` (rejected research
   variant) and `earn-defi:btc_engine@0.3` (live product config). A bare "v0.3" is forbidden in
   registers and cards.

4. **Return typing.** Every Lab number carries one of these types: `BACKTEST_*`,
   `REALIZED_PAPER_RETURN` (forward, mark-to-market, with N closed trades), `DIAGNOSTIC_BREADTH`,
   `EXTERNAL_PRODUCT_REFERENCE`. No cell mixes types. 7d/30d paper performance are shown only once
   the forward span reaches 7/30 days; otherwise `NOT_ENOUGH_HISTORY` with the days elapsed. Paper
   returns are never annualised under 30 days.

## Fixes implemented by this ADR (all autonomous; none touch money or rewrite evidence)

**A · D1 reader fix — no ledger rewrite.** `forward.forward_metrics()` still prepends the seed
equity 1.0 for correct `net_return`/`max_drawdown` math, but the engine now also publishes
`evidence.observation_count(conn, cand_id)` — a plain `COUNT(*)` — and `write_status` writes it as
`forward_observations` on every shortlist/`forward_candidates` row, instead of the old,
off-by-one `forward_bars`. The three readers (`studio_os/director_report.py`,
`research_factory/scanners/trading_research.py`, `investment_cio/sleeves.py`) now read
`forward_observations` (falling back to the legacy `forward_bars` only for a `status.json` written
before this ADR). `observations` and `lifecycle_events` are untouched — the append-only triggers
would refuse a rewrite anyway. Test: `test_forward_observations_is_the_true_count_not_the_seeded_metrics_bars`
(positive control: asserts the old seeded `bars` value and the new count actually differ).

**B · D2 methodology — OOS end frozen at forward_start.** `backtest.run_candidate`/`run_all` take
an `oos_end_ms` parameter; `forward.tick` passes `MIN(candidates.registered_at_ms)` from the
evidence db (the forward clock's start — one fixed instant, since every candidate registers in the
same tick today). The out-of-sample slice and the 3×-cost OOS slice now stop at that instant
instead of growing with `data_to_ms` on every daily refresh; a new, clearly labeled
`post_registration` slice reports what happened after, but it is diagnostic only and never a gate
input. The backtest manifest now carries `oos_end_ms`. Qualification-time metrics
(IS/OOS/OOS@3×-costs Sharpe + full-history max drawdown) are captured once, inside the
append-only `BACKTEST_QUALIFIED` lifecycle event, and because `_derive_stages` only appends an
event on a stage *change*, a candidate that stays qualified through a later, drifted backtest
never gets a second event — the original snapshot is never rewritten. `backtest.json` itself is
now also saved as an immutable, uniquely-named copy under `data/trading_research/backtest_history/`
(`save_versioned`), so the qualification-time manifest survives the next day's overwrite.
Tests: `test_oos_end_ms_excludes_bars_at_or_after_the_freeze_point` (bar count + a positive control
that contamination measurably changes OOS Sharpe), `test_run_all_freezes_oos_at_min_registered_at_ms`,
`test_backtest_qualified_evidence_is_frozen_on_requalification`.

Measured fact (RM-TRUTH-01 Wave 2 integration, 2026-10-06): with the OOS freeze in place, the
qualified set on the live ledger copy is unchanged after this ADR's deploy (same 5 candidates) —
so the first daily tick after deploy appends NO new stage event, exactly as fix B above predicts
for a candidate that "stays qualified through a later, drifted backtest".

**C · Manifest correction for btc_nav.** `architecture/manifest.json`'s `com.spa.btc_nav` entry:
`intent` `"designed"` → `"retired"`, with a `notes` addendum recording why (superseded by ADR-525
§5; plist never installed, `reboot_safe:false`; `data/btc_paper_trading.json` absent
(MEASURED-ZERO); the owner's separate-BTC-NAV intent is fulfilled by earn-defi). Hand-edited per
the generator's own rule (`intent` is a curated field, preserved across regenerations); the
validator does not flag `intent=retired` here because the plist was never in
`~/Library/LaunchAgents`. `test_architecture_manifest.py` (44 tests) green.

**F · D7/D8 reader honesty.** `write_status` now also publishes `forward_candidates`: the actual
set of `FORWARD_PAPER`/`ROBUST` candidate ids read from `lifecycle_events` (not from `shortlist`,
the backtest top-5 after correlation de-dup — they coincide today at 5=5 but are a different set
by construction). Each entry carries both `full_max_drawdown` (the binding q_drawdown gate) and
`oos_max_drawdown` side by side, instead of the Director report showing only the shallower OOS
number as "просадка". The three readers switched from `shortlist` to `forward_candidates` (with a
graceful fallback to `shortlist` for old files). Test:
`test_forward_candidates_come_from_lifecycle_not_from_the_backtest_shortlist` (6 FORWARD_PAPER
candidates vs. a 5-entry shortlist that dropped one — proves the sets diverge and the fix reads the
right one).

**C7 failure-injection (immutability).** All four evidence tables already refuse UPDATE/DELETE via
SQLite triggers created by `evidence.connect()` itself (pre-existing, re-verified here). Added:
`test_reregistering_a_candidate_cannot_silently_change_its_forward_start` (a second `register()`
call for the same id with a different clock/definition is silently ignored — `INSERT OR IGNORE` —
and a direct `UPDATE candidates SET registered_at_ms=...` is refused by the trigger) and
`test_backfill_bars_before_registration_are_never_counted_as_forward_observations` (direct call to
`advance_candidate` with bars before `registered_at_ms`: none are stored). All four tests run only
against a `tmp_path` schema created by `evidence.connect()` itself — never the live db.

**7 · Director OS v2 read model.** `spa_core/trading_research/read_model.py::trading_lab_view(data_dir)`
returns the 21-field Trading Lab card (per `C1_tradinglab_readmodel.json`) as
`{value, metric_type, as_of, source, state}` cells (`MEASURED` / `MEASURED_ZERO` / `NOT_MEASURED` /
`NOT_ENOUGH_HISTORY`, invariant #17). It opens `evidence.db` with the sqlite URI `mode=ro` (never
`evidence.connect()`, whose schema-creation DDL a read-only connection would refuse), reads
`status.json`/`backtest.json` defensively, separates `BACKTEST_RETURN` from
`REALIZED_PAPER_RETURN`, shows full and OOS drawdown side by side (fix F), gates 7d/30d windows on
elapsed span, and leaves `related_products` (earn-defi) `NOT_MEASURED` unless a caller supplies an
already-fetched track snapshot — this module makes no network call itself and never sums earn-defi
into a Lab total. Tested in `test_trading_research_read_model.py` against a *second* tmp directory
that only ever receives a read-only copy of a real engine run's files — the directory the engine
wrote into is never reopened by the view.

## Owner-reserved (OWNER) — unchanged by this ADR

1. **Lifting the earn-defi INCIDENT** (open since 2026-09-19; root cause fixed in `21c125e`):
   earn-defi ADR-006. This ADR neither lifts nor recommends lifting it.
2. **LOGOS desk KILL or REPAIR.**
3. Any future `ROBUST` → `CHAMPION_CANDIDATE` → `SHADOW` transition (already YELLOW in
   `lifecycle.py`). `LIMITED_LIVE`/`PRODUCTION` stay refused in code.

## Out of scope for this ADR (other RM-TRUTH-01 Trading Lab workers)

D3 (`market.db` backup coverage — the integration-branch change is not yet on `origin/main`), D6
(per-candidate hash-chain anchor / `ticks` hash-chaining), and G (earn-defi `track.json` carrying
`system_mode`) are tracked by the ADR draft's fixes D/E/G but are **not** implemented by this ADR —
they belong to other workers' tracks and are left as found.

## Consequences

- One answer to "where is the indicator lab": the ADR-525 engine. The other five systems have
  explicit classes, and earn-defi keeps its own status as a separate product.
- The ROBUST comparison is methodologically clean: the engine no longer quietly drifts its
  qualification scores with its own forward data.
- No evidence is rewritten. Fixes A and F touch only readers and the status.json producer (a
  derived, atomically-overwritten file). Fixes B and C add fields / correct a curated manifest
  field and append events; nothing already written is replaced.
- `spa_core/tests/test_trading_research.py` (36 tests) and `spa_core/tests/test_trading_research_read_model.py`
  (5 tests) green, alongside the existing `test_owner_control_plane.py`,
  `test_investment_cio_sleeves.py`, `test_research_factory_scanners.py` and
  `test_architecture_manifest.py` (321 tests total, 1 pre-existing unrelated failure deselected —
  `test_origin_manifest_refuses_outside_a_repo`, reproducible on `origin/main` before this change).
