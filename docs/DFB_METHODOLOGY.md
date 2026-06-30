# DFB — DeFi Board · Methodology & Self-Verifying DD

> **Type:** Methodology / due-diligence reference for the DFB sub-project (WS-3.3 + WS-3.5).
> **Date:** 2026-06-30. **Status:** read-only / advisory / paper-safe.
> **One sentence:** *DeBank shows you the yield; **DFB shows you the risk behind it — provably.**
> Don't trust us — check us.*
>
> **Honest framing up front:** DFB is **depth + risk-truth on a curated whitelist** (~38 live
> followed markets today), **not** a 10,000-pool DeBank/DefiLlama clone. Breadth grows *behind the
> identical risk overlay* (`SPA_DFB_BREADTH`, owner-gated) — breadth never relaxes the grade. DFB is
> 100% read-only, advisory, paper-project: it moves **no capital** and never touches the go-live track.

This document is the public, self-verifying explanation of **how DFB grades risk** — every claim
below cites the exact engine code that computes it, and ends with a one-command reproduce so a
skeptic re-derives any published number with zero `spa_core` import.

---

## 0. The differentiator (why DFB is not a yield screener)

Every other DeFi analytics product answers **"what does this earn?"** Only Exponential.fi grades
risk, and it does so **opaquely** (a black-box A–F over a dependency graph). **Nobody publishes, per
pool, all three of:**

1. a **conservative exit-liquidity-by-size schedule** ("$1M / $5M / $10M OUT → absorbable / exit
   fraction, against that market's *own* on-chain depth, never aggregated"),
2. a **deterministic would-the-desk-refuse-it verdict** (5 structural haircuts + a size-independent
   tail-veto — **not** an LLM score), and
3. a **reproducible per-row proof hash** ("re-derive it yourself").

SPA already computes all three for its own book in `spa_core/strategy_lab/rates_desk/`. **DFB is the
generalization of that engine from the desk's own positions to any followed market** — surfaced as a
public, risk-first pool explorer. The risk path is **deterministic + LLM-free + fail-closed**
(auditable, unlike "AI risk scoring"), and exit-by-size + refusal are surfaces no incumbent
publishes in full. That is the moat.

---

## 1. The A/B/C/D taxonomy — exact criteria

The risk class is **not a DFB-invented score.** It is a deterministic *presentation map* of the
engine's own `GateResult` (approval / kill-reason / decomposition), defined in
[`spa_core/dfb/risk_overlay.py::classify`](../spa_core/dfb/risk_overlay.py). Labels live in
[`spa_core/dfb/__init__.py::RISK_CLASS_LABELS`](../spa_core/dfb/__init__.py).

| Class | Engine condition (`classify`) | Meaning |
|---|---|---|
| **A** — alpha | `approved` **and** `net_edge > rwa_floor` | Desk would enter; structurally clean, harvestable edge over the ~3.4% RWA floor. |
| **B** — beta-floor | `approved` **and** `net_edge ≤ rwa_floor` | Desk would enter; ~baseline yield ("own-the-floor", no real edge). |
| **C** — risk-comp | REFUSED on `ECONOMICS` / `SIZE_FLOOR` (size/liquidity, hold-only kills) | Desk refuses — the yield is mostly risk compensation, or it is unexitable at size. |
| **D** — incentive | REFUSED on a **structural** kill (`TAIL_VETO` / `UNDERLYING_DEPEG` / `ORACLE_STALE` / `STABLE_DEPEG` / `FUNDING_FLIP`) | Desk REFUSES on structural toxicity — **at ANY size** (the tail-veto; cannot be sized around). |
| **UNKNOWN** | data too thin / stale / unresolvable underlying-kind | **fail-CLOSED:** never silently graded safe, never a fabricated number — published as a visible hole. |

The **D-vs-C split is the load-bearing one.** A structural refusal (D) is size-independent; a
size/economics refusal (C) is not. DFB reads this off the engine's `KillReason` enum — it never
re-derives toxicity. `net_edge` and `rwa_floor` are the engine's own
([`contracts.RatePolicyParams.rwa_floor = 0.034`](../spa_core/strategy_lab/rates_desk/contracts.py)).

---

## 2. The structural haircut + tail-veto (size-independent toxicity)

The refusal gate is **refusal-first**: it vetoes tail-comp *before* it ever looks at the economics
([`spa_core/strategy_lab/rates_desk/rate_policy.py::evaluate_entry`](../spa_core/strategy_lab/rates_desk/rate_policy.py)).
The fair-value decomposition (`YieldDecomposition` in
[`contracts.py`](../spa_core/strategy_lab/rates_desk/contracts.py)) is **baseline minus five
haircuts**:

```
total_haircut      = peg + funding_flip + oracle + liquidity + protocol
structural_haircut = peg + funding_flip + oracle + protocol      (EXCLUDES the size-dependent liquidity term)
```

Two vetoes fire (in order, short-circuiting on the first failure):

1. **`TAIL_VETO` (1a — toxicity, size-PROOF):** `structural_haircut > max_structural_haircut`
   (`= 0.06`, calibrated in `config.py`). Because the structural haircut **excludes** the
   size-dependent liquidity term, a tail-toxic book is refused at **any** requested size — sizing
   down only shrinks the liquidity haircut, never the toxicity verdict.
2. **`TAIL_VETO` (1b — economics, size-AWARE):** `total_haircut > max_total_haircut` (`= 0.12`).

Then `UNDERLYING_DEPEG` (peg > 1%), `ORACLE_STALE` (> 1h), `STABLE_DEPEG` (> 0.5%), `FUNDING_FLIP`
(neg-funding streak ≥ 5), `ECONOMICS` (net edge clears the hurdle), `SIZE` (≤ 25% of one-tick exit
liquidity; below `min_tradeable_size_usd` → `SIZE_FLOOR`).

**This is where the highest-severity bug class lives** — "DFB grades a toxic pool as safe (size-down
exploit)". The §5 red-team battery proves it cannot: a toxic LRT-shaped surface is class D + REFUSE +
`tail_veto` at every probe size from $1M down to $100, structural haircut fixed (size-independent).

---

## 3. Exit-liquidity-by-size (the conservative lower bound)

Per pool, DFB publishes the exit schedule at **$1M / $5M / $10M OUT** via the engine's
[`depth_at_size.compute_market_depth_row`](../spa_core/strategy_lab/rates_desk/depth_at_size.py) —
DFB computes **none** of these numbers (`risk_overlay._exit_rows_from_depth` only *presents* them).
The depth engine applies a **conservative constant-product impact fraction** against that market's
*own* on-chain one-tick exit liquidity (TVL × the documented impact band, or a carried surface depth)
— **never an aggregated cross-venue number**, so the bound is a *lower* bound: the real market is at
least this deep, often deeper.

**fail-CLOSED is the load-bearing rule here:** a ticket the market cannot absorb is published as a
**flagged hole** (`absorbable_usd: null`, `flagged: true`) — **never** backfilled with a fabricated
fill. A thin/stale market → the whole row flags `insufficient_contemporaneous_depth`. There is no
code path that synthesizes a green exit cell over a depth hole.

---

## 4. The refusal gate + the NO-FORK guarantee (AST-enforced)

DFB's verdict object (`PoolOverlay`) is built by **calling** the engine, never by re-implementing it:

| DFB field | Engine entrypoint it calls |
|---|---|
| `refusal.verdict` / `reason` / `tail_veto` | `rate_policy.evaluate_entry` (refusal-first gate) |
| `structural_haircut` / `total_haircut` | `GateResult.decomposition` (fair_value_engine) |
| `exit_liquidity[]` (by-size) | `depth_at_size.compute_market_depth_row` |
| `risk_class` (A/B/C/D) | `classify()` — a presentation map of the engine's own `GateResult` |
| `engine_proof_hash` | `GateResult.proof_hash()` — **byte-identical to the desk** |

> **The NO-FORK guarantee:** *DFB's verdict on a pool == the desk's verdict on the same market, to
> the byte.* This is AST-enforced by
> [`spa_core/tests/test_dfb_no_fork.py`](../spa_core/tests/test_dfb_no_fork.py): it asserts no DFB
> module *defines* any banned risk-math primitive (`evaluate_entry`, `haircuts`, `dex_exit_frac`, …),
> that the entrypoints DFB uses **are the engine's own objects** (same module identity, not a
> re-implementation), and that `overlay(pool).engine_proof_hash == evaluate_entry(...).proof_hash()`
> reconstructed from DFB's own `engine_inputs`. If a pool-shaped input needs an entrypoint the engine
> lacks, the engine is **extended in place** (engine-side tests) and DFB calls it — so the two
> products can never drift.

`evaluate_entry` (the verdict) and `evaluate_hold` (the continuous-kill side that drives the alert
feed — APY collapse / TVL drain / IL-peg spike / **refusal-state flip**) are the same two functions
the desk runs on its own book.

---

## 5. The proof / verify chain — "don't trust us, check us"

Every published pool row carries a **per-row proof chain** (the
[`proof_chain`](../spa_core/strategy_lab/rates_desk/proof_chain.py) pattern):

- **`engine_proof_hash`** — the `GateResult.proof_hash()`, byte-identical to the desk's own verdict.
- **`row_hash`** = `sha256( json.dumps({"body": <row minus prev_hash/row_hash>, "prev_hash": …},
  sort_keys=True, separators=(",",":"), default=str) )` — binds **both** the published inputs
  (apy/tvl/…) **and** the published outputs (risk_class / refusal / exit_liquidity / haircuts /
  engine_proof_hash). Forge any one cell → the recompute diverges.
- **`prev_hash`** — chains each row to the previous (`pools.json` and each history JSONL), genesis
  `"0"*64`, so a reordered / dropped / inserted / back-fitted row is caught.

Anyone re-derives any pool's proof with **zero `spa_core` import** via
[`scripts/verify_dfb_pool.py`](../scripts/verify_dfb_pool.py) — a standalone, stdlib-only sibling of
`verify_spa.py` that follows only the public canonical-JSON + SHA-256 recipe (reproduced inline in
its own header):

```bash
# whole DFB data dir (pools.json + pool/*.json + history/*.jsonl):
python3 scripts/verify_dfb_pool.py data/dfb

# one pool by id, or its detail file, or its history:
python3 scripts/verify_dfb_pool.py pendle__ethereum__susde
python3 scripts/verify_dfb_pool.py data/dfb/pool/aave-arbitrum__arbitrum__usdc.json
```

Exit `0` = every supplied row reproduces byte-for-byte (and every chain links); `1` = any mismatch
(with the precise `broken_at` pool_id + field-level note); `2` = no input found (fail-CLOSED). The
recipe in `verify_dfb_pool.py::_row_hash` mirrors `risk_overlay._row_hash` to the byte — so the
desk's number and an independent recompute agree with zero shared code. That is the "don't trust us,
check us" brand applied per pool.

---

## 6. Hard guarantees DFB inherits (CLAUDE.md, enforced)

- **stdlib-only** runtime (FastAPI/Astro are the documented exceptions).
- **No LLM** anywhere in risk / classification / refusal (`# LLM_FORBIDDEN` headers; lint-enforced).
- **fail-CLOSED** everywhere: thin/stale/unresolvable → a visible `UNKNOWN`/flagged hole, never a
  fabricated grade or number.
- **deterministic:** same `(pool, as_of, inputs)` → byte-identical overlay incl. every hash
  (`test_dfb_no_fork.py::test_overlay_deterministic`).
- **read-only / no-execution:** no DFB module imports `spa_core.execution`
  (`test_dfb_no_fork.py::test_dfb_no_execution_import`); writes confined to `data/dfb/`.
- **atomic writes** (`_io.atomic_write_json`, same-dir tmp + `os.replace`).
- **owner-gated flags** (`SPA_DFB_PORTFOLIO_LENS`, `SPA_DFB_DATA_API`, `SPA_DFB_BREADTH`,
  `SPA_DFB_DOMAIN`) — flag-OFF means total 404 / no surface leak.

---

## 7. FINAL RED-TEAM SWEEP (the charter's program-completion gate)

A rotating-red-team sweep across **every** DFB surface, run 2026-06-30. The deliverable of Lane-3 is
to **be the skeptic**: each surface gets ≥ 1 adversarial check designed to make it *lie*; the result
is documented honestly below. The highest-severity class is **"a toxic pool graded safe (size-down)"**
and **"a forged / stale proof shown as fresh."**

| # | Surface | Adversarial check | Result |
|---|---|---|---|
| RT-1 | **risk_overlay (the seam)** | Feed a toxic LRT-shaped surface (peg 3% + vol 5% + funding 0.4 + nesting 3 + concentration 0.5 → structural haircut 0.18 ≫ cap 0.06). Probe at $1M, $100k, $10k, $1k, **$100**. | **PASS** — class **D** + **REFUSE** + `tail_veto=True`, `structural_haircut=0.18` *fixed* at **every** size. The size-down exploit cannot grade it safe (the veto is the size-independent structural one). |
| RT-2 | **per-pool proof (the chain)** | Re-derive all live artifacts (`data/dfb/`) on a **clean machine** with `spa_core` stripped from `sys.path`, via `verify_dfb_pool.py`. | **PASS** — every `pools.json` row + every `pool/*.json` + every `history/*.jsonl` reproduces byte-for-byte; chain links; exit 0. Zero `spa_core` import. |
| RT-3 | **tamper-evidence** | Forge a published cell — flip a class-**C** pool to class **A** + `verdict:SAFE` (the worst lie: "this refused/risky pool is safe"), keep its `row_hash`, run the clean-machine verifier. | **PASS** — `row_hash mismatch … (a published cell was altered after the fact)`, precise `broken_at` pool_id, exit 1. A back-fitted safe-grade is caught. |
| RT-4 | **NO-FORK / byte-identity** | Assert (AST + recompute) that DFB defines no risk math, uses the engine's own objects, and `overlay().engine_proof_hash == evaluate_entry(...).proof_hash()`. | **PASS** — `test_dfb_no_fork.py` (all guards) + `test_api_dfb.py` green (38 passed). DFB's verdict == the desk's verdict. |
| RT-5 | **fail-CLOSED on missing data** | Overlay the full live universe (38 pools) incl. pools whose APY/kind/depth is unavailable. | **PASS** — 8 pools graded `UNKNOWN` (flagged holes), 0 fabricated cells; `chain_valid=True`. A missing number is a visible hole, never a 0-coerced safe value. |
| RT-6 | **UI cannot hide toxicity** | Inspect the screener color map: does a D-class / REFUSE / UNKNOWN row render visually indistinguishable from an A-class SAFE row? | **PASS** — `CLASS_STYLE` D = red `#F26D6D` vs A = green `#34D399`; `VERDICT_STYLE` REFUSE = red, SAFE = green; an unknown/unmapped verdict falls through to a **neutral grey** `VERDICT_FALLBACK`, **never** green. A toxic pool can never paint itself benign. |
| RT-7 | **flag-OFF leak** | With the owner-gated flags OFF (default), is any flagged surface (Data API / portfolio lens / breadth) reachable, or does any always-on endpoint leak ungraded breadth data as graded? | **PASS** — `test_api_dfb.py` asserts the flag-OFF posture (no surface leak); the breadth count is 0 with `SPA_DFB_BREADTH` off; every breadth pool that *is* ingested still passes the identical overlay (0 bypass by construction in `build_and_write`). |

### Finding (documented, honest) — `WATCH` is an aspirational verdict the engine does not emit

The screener's intro copy and the `DfbScreener` `VERDICT_STYLE` map carry a **three-state** verdict
vocabulary — **SAFE / WATCH / REFUSE** — and the alerts router references a "SAFE/WATCH→REFUSE"
crossing. **But `risk_overlay.overlay()` only ever emits `SAFE` / `REFUSE` / `UNKNOWN`** (see
`refusal.verdict` assignment in `risk_overlay.py`); there is no `WATCH` state in the engine's
`evaluate_entry` output today.

- **Severity: LOW — not a safety leak.** A `WATCH` would render amber (between green and red), and an
  `UNKNOWN` (which *can* appear) falls through to a neutral grey — **neither paints a risky pool
  green.** No toxic pool is mis-styled benign. The defect is *honesty/consistency*, not safety: the
  public copy implies a tier the engine doesn't produce.
- **Disposition:** the `WATCH` token is **dormant/forward-compatible** styling (it would be the
  natural home for a future `evaluate_hold` de-risk-but-not-kill signal). It is documented here as a
  known gap so the public copy is not read as over-claiming a live 3-tier verdict. The **methodology
  page (this surface) states the verdict vocabulary the engine actually emits today: SAFE / REFUSE /
  UNKNOWN** — and notes WATCH is reserved-not-yet-emitted. No code change is made to another lane's
  surface (the `DfbScreener` styling map and the alerts router are Lane-2 / Lane-A files — **flagged,
  not fixed**, per the lane-confinement rule). See §8.

**Sweep verdict:** the full red-team battery (size-down toxicity, forged hash, stale/tampered-as-fresh,
fabricated fill, fail-closed holes, UI mis-styling, flag-OFF leak) is **caught**. One LOW honesty gap
found (`WATCH` aspirational vocabulary) — documented + flagged cross-lane, not a safety defect.

---

## 8. Cross-lane flags (lane-confinement honored — flagged, NOT fixed here)

Lane-3 is confined to `docs/` + `landing/src/pages/board/` + landing components. The following live in
**other lanes** and are **flagged for the owning lane**, not edited here:

1. **`WATCH` verdict vocabulary mismatch (LOW, honesty).** `landing/src/components/DfbScreener.jsx`
   (`VERDICT_STYLE.WATCH`) and `spa_core/api/routers/dfb.py` (alerts "SAFE/WATCH→REFUSE" copy) imply
   a 3-state verdict the engine never emits (`risk_overlay` emits SAFE/REFUSE/UNKNOWN only). Either
   add a real `WATCH` state to `evaluate_entry`/`evaluate_hold` (engine extension, with NO-FORK
   preserved), or remove the `WATCH` token + copy so the public surface matches the engine. **Not a
   safety leak** (no toxic pool renders benign). → Lane-A/Lane-2 decision.

---

## 9. Bottom line

DFB is **not** a DeBank/DefiLlama clone. It is **depth + risk-truth on a curated whitelist** that
breadth-extends later behind the **same risk overlay** — the one surface no incumbent publishes:
per-pool exit-liquidity-by-size + a deterministic refusal verdict + a reproducible proof hash, built
from data SPA already produces, **LLM-free, fail-closed, read-only, advisory**, never touching the
go-live track. The whole product is downstream of one function — `risk_overlay.overlay()` — which is
why the NO-FORK guarantee (DFB's verdict == the desk's verdict, AST-enforced) is the spine, and why
the red-team value concentrates on the seam.

*"DeBank shows you the yield. DFB shows you the risk behind it — provably. Don't trust us, check us."*
