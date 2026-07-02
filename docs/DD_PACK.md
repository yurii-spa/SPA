# SPA — Due-Diligence Pack (DD_PACK)

_A structured, auto-generated, REAL-DATA data-room for an LP / investor due-diligence review. Every number below is either read live from a `data/` file or lifted verbatim from a SHA-256-hashed row of `data/rates_desk/decision_log.jsonl` — and a build test (`spa_core/tests/test_dd_pack.py`) FAILS if any numeric claim in this document is not resolvable to one of those sources (the no-unsourced-number guard). stdlib-only, deterministic, fail-CLOSED. Honest: the track is THIN, the capacity is bounded, the capital is paper ($0 real)._

> **Don't trust us — check us.** Every hashed row cited here is reproducible by a skeptical third party with one zero-dependency script and SPA's public JSON, on a clean machine with none of our code:
>
> ```
> python3 scripts/verify_spa.py data/
> ```
>
> The WHOLE-DIR form covers ALL 7 surfaces (rates-desk decision/exit-NAV/anchors/equity plus tournament, RWA-NAV, sleeve). Recipe: `docs/PROOF_CHAIN_SPEC.md`. Public surfaces: `/refusals` (the decision log), `/exit-nav` (liquidation-NAV by size), `/proof-of-reserves` (honest paper NAV), `/track-record` (the accruing series), `/fundability` (this case, live).

---

## 1. Executive verdicts (at a glance)

| thesis | module | verdict | the honest boundary |
|---|---|---|---|
| **#1 Rates Desk** (refusal-first carry) | `spa_core/strategy_lab/rates_desk/` | **GO** — FixedCarry validated, live-paper | carry leg is real -> fundable; capacity-bound |
| **#2 RWA Repo Backstop** (liquidation-NAV underwriter) | `spa_core/strategy_lab/rwa_backstop/` | **measurement-GO / book NO-GO** | underwriting needs custody+legal+capital (off-code) |
| **#3 Liquidator** (balance-sheet liquidator) | `spa_core/strategy_lab/liquidator/` | **NO-GO** (published) | addressable market ~5-10x below the fundability bar |

**DECISION-CHAIN HEAD (re-derived live, the fingerprint of the entire decision history — this is the `--expect-head` value):**

- chain valid: **yes** · length: **344** decisions
- decision-chain head: `66cb4eccb669669d02bdef4b083a9d1255dba1ff850548434bbe5998a8713f2e`

Reproduce + assert this exact head yourself (WHOLE data dir → covers ALL 7 surfaces):

```
python3 scripts/verify_spa.py --expect-head 66cb4eccb669669d02bdef4b083a9d1255dba1ff850548434bbe5998a8713f2e data/
```

**VERIFIER SCRIPT SHA-256 (a DIFFERENT 64-hex value — the checksum of `scripts/verify_spa.py` itself, NOT the chain head; pin it so you trust the verifier too):**

- verifier-v1.0 · `verify_spa.py` SHA-256: `9befddc69c046e022c9a00d4db6855c42ac763a97a683fd3476d6b02f42f3fa0`

```
shasum -a 256 verify_spa.py   # must equal the verifier SHA-256 above
```

> These two hashes answer different questions: the **decision-chain head** (`--expect-head`) proves the *history* is intact; the **verifier SHA-256** proves the *tool* checking it is authentic. They are never interchangeable.

---

## 2. The validated GO — a fully worked refused-vs-approved example

This is the differentiator made concrete: on the SAME engine, SAME day, the desk **refused** a toxic LRT carry book and **approved** a clean stable carry book — and BOTH decisions are hashed into the public chain. A great quoted rate cannot buy its way past a structural veto.

Worked example: _data unavailable_ (no adjacent REFUSAL->ENTRY pair found in decision_log.jsonl).

---

## 3. The decision record (refusals AND entries, all hashed)

The public, hash-linked `data/rates_desk/decision_log.jsonl` carries **344** logged decisions:

- **86 refusals** — of which **0** structural tail-vetoes (toxic carry refused before economics) and **86** size-floor declines (real carry, but below the fundable depth floor).
- **258 entries** — approved, depth-bounded carry books.

Every row — entry AND refusal — is hashed. This is the surface no competitor publishes: **what we refused, and why.** Live human-readable view: `/refusals`. Machine: `/api/rates-desk/refusals`.

---

## 4. Honest capacity — what this actually clears today

The standalone rates-desk carry edge is REAL and survives every stress window — but it is **capacity-bound** by exit depth. The honest current numbers, live from the capacity model:

- fundable independent books today: **22** (of **25** harvestable markets).
- total depth-bounded deployable AUM: **$330,315** at an aggregate **22.93%/yr** net.
- carry ABOVE the RWA floor (**3.4%/yr**): **$64,779/yr**.
- that is **0.65%** of the $10M/yr target — a gap of **$9,935,221/yr**.

**Stated plainly:** the current real Pendle PT carry market is **too thin** to fund $10M/yr above the floor on its own. The rates desk is **one diversifying sleeve** of a larger book, not a standalone $10M business at today's depth. $10M needs the market to GROW (deeper pools), MORE venues/books, and/or the other sleeves carrying the balance — **plus** the off-code scale legs in §6. Combined across sleeves, after a correlation haircut, the honest figure is lower still. We do not claim $10M is reachable today.

---

## 5. The other two theses — the measurement-GO and the published NO-GO

### 5a. RWA Repo Backstop — measurement-GO / book NO-GO

"Lend against Liquidation NAV, not marketing NAV." The Safety Board measures, from free data, that RWA collateral is genuinely **not cash-like** on an executable on-chain exit:

- **11/11** assets not cash-like — LIQUID **0** · THIN **1** · REDEMPTION_ONLY **9** · UNSAFE **1**.
- max on-chain ERC-4626 NAV divergence from $1.00 marketing NAV: **8.17%**.

**Verdict:** the *measurement* layer is GO (deterministic, fail-closed, runs continuously). The underwriting *book* is NO-GO read-only — it needs whitelisting + redemption agreements + capital + legal, none of it buildable in code (see §6).

### 5b. Liquidator — NO-GO (published — we publish what we kill)

The long-tail / nested-collateral liquidation opportunity was measured read-only and published as a kill:

- gross addressable: **~$3.8M/yr** (top-20 ~**$2.2M/yr**).
- fundability bar: **~$20M/yr** -> the opportunity is ~5-10x **below** the bar.

**Verdict: NO-GO, published.** Too small to justify the custody + CEX + balance-sheet build. Publishing the kill is itself the credibility signal. Source of record: `docs/LIQUIDATOR_DERISK.md`.

---

## 6. The off-code gates — honestly, what stands between here and $10M

The code took each thesis to an honest verdict for free. But the same boundary appears across all three — **the code can measure and refuse; the $10M is off-code.** Stated plainly:

- **Custody / MPC** — institutional key management for real capital; not buildable in read-only paper code.
- **External audit** — independent code + controls audit of the execution path.
- **Legal** — fund structure, collateral perfection, redemption agreements, force-redemption rights; the RWA underwriting leg can only be *documented*, not *executed*, without it.
- **Real capital + relationships** — whitelisting / subscription access to redemption queues; the carry edge needs scale across many capacity-bound books, which needs AUM.

SPA contributes the cheapest, most defensible first layer: the transparent, fail-closed measurement-and-refusal engine that PROVES the mispricing — plus an honest record of exactly which off-code legs gate the business. **$10M is scale + decorrelation + trust + AUM, NOT reachable today** on $0 real capital.

---

## 7. The track status — THIN, honestly labeled

- evidenced track days: **10/30** — **accruing, not yet 30**. Only days backed by a real daily-cycle log count; the earlier backfill bars were reset OUT. The low number IS the credibility.
- honest anchor: **2026-06-22** · go-live target: **2026-07-21**.
- go-live criteria: **27/29 pass** — NOT READY. The remaining blockers are **time-gated** (track days to accrue) — nothing to fix in code.

- forward-track integrity: **all_ok** — **8** forward tracks, **0** failing (no duplicates / gaps / out-of-order / future-dated points).

- go-live dry-run harness: gates verified **inert** — NAV reconciliation **PASS**, live-trading gate active **no**, moves_capital **no**. The fail-closed chain fires WITHOUT moving any capital.

- realized edge (REALIZED, not backtest): of **11** forward sleeves, **0** beat the RWA floor (**3.18%**/yr — sourced) and **11** are **INSUFFICIENT_DATA** at this track depth. The flagship FixedCarry book is **at-or-below the floor so far**. We do NOT claim the desk beats the floor on realized data yet — and a thin track yields INSUFFICIENT_DATA with a null bps, never a fabricated zero. Reproduce every realized bps from the raw series: `python3 scripts/verify_spa.py --check-fundability data/`.

Live, regenerating view: `/track-record` (hash-anchored series + per-bar source labels). Verify the underlying chain (whole dir → all 7 surfaces): `python3 scripts/verify_spa.py data/`.

---

## 8. How a hostile LP checks every claim here

1. Download `scripts/verify_spa.py` (zero dependencies, no `spa_core` import, no network), then pull SPA's public proof artifacts. NO repo checkout is needed — the live API serves every COMPLETE chain VERBATIM (uncapped) at `/api/rates-desk/full-chain/{surface}` (index at `/api/rates-desk/full-chain`), so an outsider reproduces every head end-to-end:

```
B=https://api.earn-defi.com/api/rates-desk/full-chain
mkdir -p data/rates_desk/paper data/tournament data/rwa_backstop
curl -s $B/decision_log > data/rates_desk/decision_log.jsonl
curl -s $B/exit_nav     > data/rates_desk/exit_nav.json
curl -s $B/anchors      > data/rates_desk/anchors.jsonl
curl -s $B/equity_track > data/rates_desk/equity_track.jsonl
curl -s $B/tournament   > data/tournament/decision_log.jsonl
curl -s $B/nav_proof    > data/rwa_backstop/nav_proof.jsonl
curl -s $B/sleeve       > data/rates_desk/paper/rates_desk_fixed_carry_series_proof.jsonl
```

2. Run it on a clean machine — point it at the WHOLE `data/` dir so it covers ALL 7 surfaces:

```
python3 verify_spa.py data/
```

(The narrower `data/rates_desk/` form only sees the 4 rates-desk surfaces; `--expect-surfaces A,D,E,F,G` fails CLOSED if a surface you require is absent, and a present producer with a missing/empty proof is a FAIL, never a silent pass.)

3. It re-derives EVERY decision `entry_hash`, every exit-NAV `proof_hash`, the tournament / RWA-NAV / sleeve chains, and the anchor head-checkpoints — and reports the precise `broken_at` if a single byte of history was altered after the fact. Exit 0 = everything reproduces. (Note: the verifier ALSO labels degenerate Sharpe / par-NAV points as ADVISORY — the proof proves a value was PUBLISHED, not that it is real.)
4. Cross-check the worked example in §2: its `proof_hash` values are emitted by the same recipe (`docs/PROOF_CHAIN_SPEC.md`).
5. **Reproduce every FUNDABILITY number from raw data** — run the verifier with `--check-fundability` and it re-derives every realized carry-above-floor bps in `carry_truth_table.json` directly from the raw `*_series.json` forward tracks (the same floor-leg/carry-leg residual split, inlined, no `spa_core`), and asserts they match:

```
python3 verify_spa.py --check-fundability data/
```

   A forged fundability number — or an INSUFFICIENT_DATA masked behind a rounded zero — does NOT survive: the recompute from the raw series diverges and the verifier FAILS CLOSED with the precise sleeve. This is what makes the realized FUNDABILITY sheet (`docs/FUNDABILITY.md` §2, `docs/FUNDABLE_HONEST.md`) literally checkable, not just asserted.

The append-only anchor ledger currently holds **3** head-checkpoint(s) (a genesis reset over the security-corrected chain head is auditable in the ledger note).

**Honesty contract for this doc:** every numeric token in DD_PACK.md is asserted (by `test_dd_pack.py`) to be present in the set of numbers sourced from `data/` files or hashed decision rows. A number that drifts from its source fails the build. There are no un-sourced claims.

---

_Regenerated 2026-07-01 18:52 UTC. All numbers live from `data/` (golive_status.json · rates_desk/{rates_desk_promotion,portfolio_capacity}.json · rates_desk/decision_log.jsonl · rates_desk/anchors.jsonl · rwa_safety_board.json · forward_track_integrity.json · golive_dry_run.json) and the hashed decision rows; Liquidator NO-GO figures from `docs/LIQUIDATOR_DERISK.md`. Regenerable via `python3 scripts/generate_dd_pack.py`. Mirror page: `/fundability`._