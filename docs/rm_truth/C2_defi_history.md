# RM-TRUTH-01 · C2 — DeFi books / history integrity (read-only)

Worker C2. Measured 2026-10-05, read-only (`~/Documents/SPA_Claude` prod `data/` read but never
written; code from `~/Documents/SPA_mirror`; sqlite opened read-only only; no agents, no pytest).
Builds on prior evidence `scratchpad/rmtruth/A2_capital.md` / `REVIEW_1.md`; this file re-verifies
and goes one level deeper on history/backups/day-by-day gap causes. Outcome vocabulary: MEASURED ·
NOT MEASURED · UNKNOWN (named, not guessed).

---

## 1. Main track continuity (Conservative, anchor 2026-06-22) — RE-VERIFIED

`data/equity_curve_daily.json`: **136 bars**, 2026-05-21 → 2026-10-05, zero duplicate dates.
`source` field: `warmup` 20 (05-21..06-09) · `backfill` 11 (06-10..06-20) · `reconstructed` 1
(06-21, flagged `reconstruction_note: "interpolated — no daily_cycle log for this date; bounded by
real 06-20 and 06-22 close"`) · `cycle`/evidenced **104** (06-22..10-05). All pre-anchor/interpolated
bars are labelled, none deleted — confirms A2 claim #1.

**Calendar holes (no bar at all): exactly `2026-07-19` and `2026-07-27`.** Both explained by their
own daily_cycle log, not by data loss:
- `logs/daily_cycle_20260719.log`, `logs/daily_cycle_20260727.log`: `no_live_data: orchestrator
  returned no usable adapter APY — skipped trade & yield accrual for this cycle`, `cycle_runner
  exit=1`. Honest refusal (invariant #2 fail-CLOSED), not a write that was later lost.

**The 2026-06-27..29 "wipe": re-verified against the actual commit.** `git show 902c1e7c6` (mirror,
2026-07-01 02:50:22+02:00): *"equity_curve_daily.json is owner-gated git-TRACKED; repeated 'git
reset --hard origin/main' (local↔origin sync after API-pushes) clobbered the live track with
origin's STALE committed copy missing the locally-run 06-27/28/29 bars … 06-27/28/29 recovered from
the durable daily_cycle logs (equity 100201.66/100212.99/100224.36 — EXACTLY matching the logs AND
the pre-reset git checkpoint)"* — and `track_self_heal.py` was added, wired into `cycle_runner`
(post-write) + `cycle_gap_monitor` (Step 0), so a repeat clobber on *this* file self-heals within a
day. Confirmed: current bars for 06-27/28/29 carry `source:"cycle", evidenced:true`, no residual
`reconstructed` flag (only 06-21 still carries it — the one day outside that self-heal's reach,
since no log existed for it at all).

**Backups checked, as instructed, via `scripts/daily_backup.py` config + `dr_offsite_status.json`.**
Both read code-level (not guessed): `MUST_HAVE` in `daily_backup.py` names
`equity_curve_daily.json`, `golive_status.json`, `paper_evidence_history.json`,
`current_positions.json`, `track.db` — `paper_evidence.json` is **not** in `MUST_HAVE` (it is
captured only because the daily glob over `data/*.json` is broad). `dr_offsite_status.json`:
`is_real_remote: false` (same disk, `~/Documents/SPA_Claude` → `~/spa_offsite_backups`).
Archives on host: local `data/backups/spa_state_*.tar.gz` back to **2026-09-05**; offsite
`~/spa_offsite_backups/spa_state_*.tar.gz` back to **2026-09-22**. Nothing older survives (30-day
retention; the 2026-08-23 05:30Z archive the 08-24 incident restored from, and the ad-hoc
`~/SPA_backups/c361_data_clobber_20260823T231409Z/` damage snapshot, are both still on disk and
were read — see §3).

**No hidden reset on the main curve.** Every evidenced bar's `close_equity`/`positions` for the
08-10..08-22 window (checked individually) shows normal multi-position books and rising equity —
*not* the flat $100k/0-position "halted" state a later cycle's book briefly held mid-day (see §3);
the daily bar captures the day's *final* cycle snapshot, and trading resumed same-day after the
EB-02 self-clear (§3), so the curve is honest and continuous. Nothing in the curve itself was
silently reset during this slice.

## 2. Every paper_evidence-missing day, classified (28 of 104)

`data/paper_evidence.json` has **88 rows**, all dated, covering 06-10..10-05, but **missing 28 of
the 104 evidenced curve days**: `2026-06-22..2026-06-29` (8) and `2026-08-03..2026-08-22` (20).
Full per-day table: `scratchpad/rmtruth/C2_gap_classification.json`.

**Verdict for all 28: `DATA_LOST`, and recoverable — not a producer failure.** For *every single
one* of the 28 dates, `logs/daily_cycle_<YYYYMMDD>.log` on the host contains a live
`INFO spa.cycle_runner: MP-416 evidence recorded: date=<date> apy=<x>% equity=<y>` line (checked by
direct grep, not sampled) — proof the row was written to disk, with real numbers, the day it
happened. The writer (`cycle_reporting._record_paper_evidence`) only skips a day when
`apy_today_pct` is not a finite real number (refusal-first, invariants #2/#8); these days never hit
that refusal path.

**Mechanism (measured, not guessed) — same clobber class documented by commit 902c1e7c6, but never
healed for this file:**
- `data/paper_evidence.json` IS git-tracked (`git ls-files` confirms) and has had exactly **two**
  commits ever: `be5252349` (2026-06-21) and `eefe25314`. `git show eefe25314:data/paper_evidence.json`
  has **44 rows, 2026-06-10..2026-06-21, then 2026-06-30..2026-08-02** — the *same* 06-22..06-29
  gap already baked into the git-committed canon, and ending exactly at 2026-08-02.
- The live file (and every backup, 09-05 and 09-22 alike) has **88 rows** = 44 git-canon rows
  (06-10..08-02, gap included) + 44 fresh rows (2026-08-23..2026-10-05). The arithmetic is exact
  (44+44=88) and the break points line up precisely with the git commit's last date and the
  observed resume date — the fingerprint of the live file having been reverted to its own stale
  git-committed copy at some point between 08-22 (last confirmed live write) and 08-23 (first
  confirmed resumed write), then simply continuing forward from that stale copy.
- `scripts/reconcile_paper_evidence.py` and `scripts/fix_fabricated_evidence.py` (the only two
  writers besides the live tracker) only *patch fields in place*; neither deletes rows — ruled out
  as the mechanism.
- `spa_core/paper_trading/track_self_heal.py` (the fix 902c1e7c6 built) **only touches
  `equity_curve_daily.json`** — `paper_evidence.json` has no equivalent self-heal, so an identical
  clobber against it is never auto-repaired, unlike the curve.
- A **literal, confirmed** occurrence of this exact clobber class exists in the window:
  `docs/journal/2026-W35.md` (cycle #361, 2026-08-24 night) — *"В 01:05 я, убирая мусор `data/`
  после прогона, выполнил `git checkout -- data/ spa_core/data/ …` в БОЕВОМ дереве… откатились 116
  файлов живого состояния"* (≈2026-08-23T23:05Z). **However**, `data/paper_evidence.json` is **not**
  among the 116 files that session's own damage inventory lists
  (`~/SPA_backups/c361_data_clobber_20260823T231409Z/`, I enumerated all 116 — verified absent).
  So this specific session is the right *class* and the right *week*, but is **not proven** as the
  exact cause of this file's loss — flagged UNKNOWN at that level of precision, not guessed.
- Independently, a **production HALT** also sits inside the same window and is fully documented:
  emergency breaker **EB-02 "Oracle Divergence Cascade"** fired `data/kill_switch_active.json` at
  **2026-08-10 00:52 UTC** (`docs/journal/2026-W33.md`, cycles #190/#191), self-cleared the same day
  (quorum 3 of 11 hard-coded constants lost a member as the market moved) but the file is sticky
  (manual `/resume` required) while the owner was traveling until ~08-19 — root-caused and fixed by
  **ADR-079** (quorum 3→4). This explains *why* some of these 20 days show thin/flat trading, not
  why the *rows vanished from paper_evidence.json* specifically — the cycle logs show MP-416 wrote
  them regardless.

No row was fabricated and none needs to be invented to close this gap: the exact `apy_pct` and
`equity_value` for all 28 dates are sitting, verbatim, in the daily_cycle logs on this host.
**Recoverable: yes, for all 28.**

## 3. Balanced / Aggressive timelines — RE-VERIFIED

- **Created 2026-06-22** (`git 4f1f98906`, `a39a6abd4`, EPIC-1 S1.3 "Engine B HY" $66k / EPIC-2
  S2.2 "Engine C LP" $33k).
- **918–929 idle cycles, 2026-06-22→08-23**, confirmed by ADR-125's own measurement table: Balanced
  gated on `regime != "ENTER" → skip` against a non-existent perp-funding feed (always `EXIT`,
  0 positions, 918 cycles); Aggressive filtered on LP-named candidates absent from the live
  whitelist (0 positions, 929 cycles).
- **2026-08-23, owner-approved restart — cited decision: ADR-125** (*"Три пакета начинают реальный
  paper-трек"*, dated 2026-08-23, author "оркестратор по прямому мандату владельца — «начинай» /
  «Гоу B»"). Balanced = **"пакет Core"**, Aggressive = **"пакет Max-Yield"** in this ADR's own
  naming — a *third* use of "Core", distinct from both Conservative (`tier_paper_rollup.json`) and
  from the design-doc tier taxonomy (§4). Seeded $100k each (`sleeve_book.PACKAGE_SEED_USD`),
  continuous deploy, tier-specific kill-switch (Balanced −8%, Aggressive −25%).
- **Row-count check across backups (requested in task): no deletion, confirmed by direct extraction.**
  `data/hy_paper_trading.json` / `lp_paper_trading.json` today: **43** `daily_history` rows each,
  2026-08-24→2026-10-05 (continuous, no gap). Offsite backup `spa_state_2026-09-22.tar.gz`: **30**
  rows each, 2026-08-24→2026-09-22. 30 then → 43 now is exactly the +13 days elapsed; monotonically
  growing, nothing removed.
- **2026-10-02T00:55Z re-versioning — ADR-533**: 39 of those rows (08-24..10-01) are kept but closed
  as `*-legacy-lending` and explicitly flagged `DISTORTED` (sleeve-econ-v1 charged gas on accrual
  drift, per ADR-531) — `data/defi_engine/status.json` books.*.note: *"equity carried from the
  closed legacy-lending experiment: the floating legs are kept, the fixed-rate (PT) part / the
  simulated loop starts … empty/flat"*. Current experiments (Pendle PT fixed carry for Balanced,
  simulated sUSDe/PYUSD Morpho loop for Aggressive) have **4 valid days** as of 2026-10-05 (entered
  2026-10-02T00:55Z / 2026-10-03), i.e. 4/30 — matches A2's investment_cio figure
  (`balanced/aggressive IMMATURE 4/30`, `defi_conservative` MATURE at realized 4.90% ≥ hurdle 3.6%).
- **The misleading `start_date` field — re-confirmed live:** both `hy_paper_trading.json` and
  `lp_paper_trading.json` still carry `"start_date": "2026-06-22"` today even though real history
  starts 2026-08-24 (62 days later) and the *current* experiment starts 2026-10-02/03. Three
  different "start" dates live in one field name across readers.

## 4. Legacy Core / S-strategy lineage

- **"S7" resolved to source.** Every row in `paper_evidence.json` (all 88) carries
  `strategy_id: "S7"`. This is **not** a lookup of which strategy actually ran that day — it is a
  **hard-coded literal** at the single call site that writes the file:
  `spa_core/paper_trading/cycle_reporting.py:526-532`
  (`_et.record_day(..., strategy_id="S7", notes="auto-recorded by cycle_runner v4.73")`). `S7` does
  resolve in the registry (`spa_core/paper_trading/strategy_registry.py:261-282`, `S7_DIVERSIFIED_MAX`
  = "Equal weight: Aave/Compound/Morpho/Yearn/Euler 16.7% each, Maple 11.7%, target ~6-8% APY") —
  but the book that has actually been running under every regime since (warmup allocation,
  anchor-day allocation, and today's `optimized_yield` / `conservative-lending-v1` book:
  compound_v3 40k / maple 20k / fluid_fusdc 20k / morpho_blue_base 10k / aave_v3 5k / cash 5k) never
  matches S7's declared equal-weight allocation. **"S7" on these rows is a fixed stamp, not a
  record of the strategy that actually produced the day's number** — confirms and sharpens A2's
  finding #3 ("NOT the book that runs").
- **Separately, `scripts/fix_fabricated_evidence.py` documents a real, owner-decided prior incident
  on this same field (ADR-058, 2026-07-23, Variant A):** the cycle used to inject a *different*
  literal, the S7 *backtest* value `10.115%`, as a fallback whenever it could not read a live APY.
  Owner decision: flag (`fabricated: true` + reason), never delete, recompute milestones from real
  days only. This is a distinct, already-resolved defect from the row-loss in §2 — it explains why
  some surviving rows carry a `fabricated` flag, not why 28 rows are missing.
- **"Pre-07-11 Core paper history" — premise not confirmed; no separate ledger ever existed to
  lose.** Searched for the earliest uses of "Core" as a product/tier name: `docs/17_portfolio_
  construction.md` (created 2026-07-02, `git log --diff-filter=A`) defines a portfolio-construction
  taxonomy **Preserve → Core → Enhanced → ETH-yield → Experimental**, where "Core" = *"Conservative
  optimizer; small, fully-explained spread… Preserve set + validated T1/T2 lending & PT
  fixed-carry"* — a **design-doc risk-tier label**, not a distinct running paper-trading engine with
  its own ledger. No file named `core_*paper*`/`core_cycle*` exists anywhere in the mirror (grep,
  zero hits). The main $100k track (what later became "Conservative") is the closest real referent,
  and its own history is intact back to 2026-05-21 (§1) — nothing before 07-11 is missing because
  nothing before 07-11 under the name "Core" was ever a separate ledger. What *did* happen to the
  word "Core": it was independently re-used twice more later — `scripts/tier_paper_rollup.json`
  calls Conservative "Core (~6%)" (no reader found, per A2), and ADR-125 (08-23) calls **Balanced**
  "пакет Core". Three live meanings of one word, zero lost history behind any of them — this is a
  **naming collision**, not a data-loss case. (Matches and sharpens A2 finding #10 / REVIEW_1 §3.1.)

## 5. Summary table

| Area | Verdict |
|---|---|
| Main curve continuity 06-22→10-05 | SURVIVING, complete except 2 honest refusal holes (07-19, 07-27). Warmup/backfill/reconstructed labelled, not deleted. |
| 06-27..29 curve clobber | HEALED (commit 902c1e7c6, 2026-07-01), self-heal wired so it cannot recur silently on this file. |
| `paper_evidence.json` 06-22..06-29 (8d) + 08-03..08-22 (20d) | **DATA_LOST, 100% recoverable from daily_cycle logs.** Same clobber *class* as 902c1e7c6, never healed for this file. Exact responsible session **not pinned** (candidate cycle #361 git-checkout measured and ruled OUT by its own file inventory; EB-02 HALT measured and explains trading pattern, not row loss). |
| Balanced/Aggressive history | Intact since 2026-08-24 restart (ADR-125), row counts verified non-decreasing across two backups, current experiment 4/30 days (ADR-533), `start_date` field misleading on both books. |
| "Core" naming | Collision across 3 live meanings (design-doc tier / `tier_paper_rollup` label for Conservative / ADR-125 label for Balanced); no separate lost ledger found. |
| "S7" on paper_evidence rows | Hard-coded literal stamp at the write site, not a lookup of the actual running strategy; distinct from the already-resolved ADR-058 fabricated-10.115% incident. |

## 6. UNKNOWNs (named)

1. The exact command/session that reverted `data/paper_evidence.json` to its git-committed canon
   between 2026-08-22 and 2026-08-23 — class and week are measured, the specific session is not
   (cycle #361's own 116-file inventory excludes this file).
2. Whether any *other* git-tracked `data/*.json` file suffered the identical silent clobber in the
   same window without ever being flagged (not surveyed here — out of this slice's scope).
3. Whether `paper_evidence.json` has any additional protection today against a repeat of this exact
   clobber (not measured; `track_self_heal.py` provably does not cover it).
