# DFB — DeFi Board · 3-Month Program Charter

> **Type:** Charter / program plan for a new SPA sub-project. Authored by the Senior Architect.
> **Date:** 2026-06-30. **Status:** APPROVED-TO-EXECUTE (read-only / advisory / paper-safe).
> **Re-grounding:** `docs/research/DEBANK_RESEARCH.md`, `CLAUDE.md`, `spa_core/adapters/`,
> `spa_core/strategy_lab/rates_desk/` (`exit_nav.py` / `depth_at_size.py` / `rate_policy.py` /
> `proof_chain.py` / `contracts.py`), `spa_core/api/` (FastAPI), `landing/` (Astro + `/academy`).
>
> **One sentence:** *DeBank shows you the yield; **DFB shows you the RISK behind the yield** —
> per pool, with its A/B/C/D class, its exit-liquidity-by-size, and a deterministic
> would-the-desk-refuse-it verdict, each row carrying a reproducible proof hash. Don't trust us —
> check us.*

---

## 0. Name

**Pick: `DFB — "DeFi Board"`.** Keep **DFB** as the acronym (owner already leans here).
"Board" carries the double meaning we want: a *trading desk's board* (the risk board you read before
you size in) and a *leaderboard/screener* (the pool table). It's neutral, institution-credible, and
doesn't over-promise breadth.

- **Alt 1 — "DeFi Risk Board" (still DFB):** maximally on-message (risk-first), but slightly narrower;
  use as the tagline (`DFB — the DeFi Risk Board`) rather than the wordmark.
- **Alt 2 — "DeFiBoar / DFB" (owner's):** memorable mascot potential, but reads as a typo of "Board"
  and weakens the institutional tone we're selling to a future Data-API buyer. Keep as an internal
  codename / 404-easter-egg at most.

> **Decision:** wordmark **DFB**, expansion **DeFi Board**, tagline **"the DeFi Risk Board —
> provably."** Real domain (`dfb.earn-defi.com` or `board.earn-defi.com`) is **OWNER-FLAGGED**
> (§ Flags); until then DFB ships at the path **`/board`** on the existing `earn-defi.com` Astro site.

---

## 1. Vision & the risk-first differentiator

Every DeFi analytics product on the market answers **"what does this earn?"** DeBank (portfolio +
pool API), DefiLlama (yields, `apyBase`/`apyReward`/`ilRisk`/prediction), Vaults.fyi (base/reward/
reputation), APY.vision (IL + fee + LP P&L), Exponential.fi (A–F letter grade). Of these, only
Exponential grades risk — and **opaquely** (a black-box score on a dependency graph).

**Nobody publishes, per pool, all three of:**
1. a **conservative exit-liquidity-by-size schedule** ("$1M / $5M / $10M OUT → net %, days, against
   that market's *own* on-chain depth, never aggregated"),
2. a **deterministic would-the-desk-refuse-it verdict** (the 5 structural haircuts + tail-veto, not an
   LLM score), and
3. a **reproducible per-row proof hash** ("re-derive it yourself; don't trust us").

**SPA already computes all three** — for its own book — in `spa_core/strategy_lab/rates_desk/`
(`exit_nav.compute_ticket_row` → per-row `proof_hash`; `depth_at_size.compute_market_depth_row` →
lower-bound + monotonic asserts; `rate_policy.evaluate_entry/evaluate_hold` → refusal verdict;
`proof_chain` → tamper-evident chain). **DFB is the generalization of that engine from the desk's own
positions to *any followed market* — surfaced as a public, risk-first pool explorer.**

That is the moat: it is built from data SPA *already produces*, the risk path is **deterministic +
LLM-free + fail-closed** (auditable, unlike "AI risk scoring"), and exit-by-size + refusal are
surfaces **no incumbent publishes in full**.

---

## 2. Scope — IN (on-identity) vs OUT (off-identity)

### ✅ IN — on-identity, buildable inside SPA's constraints
- Public **pool / yield RISK-EXPLORER** (screener): one row per followed market, every row risk-first.
- **Pool detail pages**: full exit-NAV-by-size schedule + refusal decomposition + reproduce/verify block.
- **Historical capture + charts**: APY base/reward, TVL, IL flag, **refusal-state over time** (the scarce series).
- **Alerts / watchlists** driven by `evaluate_hold` kill signals (APY collapse, TVL drain, IL/peg spike, refusal flip).
- **Read-only portfolio lens** (paste a *read-only address* → positions, each risk-graded) — **later** (needs balance adapters; no wallet-connect, no signing).
- **Risk-graded Data API** (the on-identity monetization) — **behind a flag** (`SPA_DFB_DATA_API`), owner-gated for public launch.

### ❌ OUT — off-identity, do NOT build
- **Token approvals / revoke** — needs a connected signing wallet → breaks no-custody/read-only.
- **Own L2 chain** (DeBank Chain) — infra company, not a measurement desk.
- **Social layer** (ID / Hi! / Stream) — different company; attention-market is off-identity.
- **Wallet / swap / custody / top-ups** (Rabby-style) — execution/custody, explicitly forbidden.
- **Wallet-connect for signing** — even for the portfolio lens: **read-only address lookup ONLY.**

### ◐ OWNER-GATED — designed behind flags, not launched without an owner decision
Wallet-connect/balance-read for arbitrary addresses (read-only addr is fine; *connect* is gated),
any **paid data source** (keyless/free only by default), **public launch of the Data API** product
(keys/billing/SLA), real domain. See § Flags.

---

## 3. How DFB relates to SPA

```
SPA (the desk)                              DFB (the board)
─────────────────────────────              ──────────────────────────────────
spa_core/adapters/  ────────┐               spa_core/dfb/            (NEW pkg — read-only)
  ADAPTER_REGISTRY (~35)     │ feeds          pool_universe.py        ← curated whitelist model
spa_core/adapters/             ├──reuse──►     risk_overlay.py         ← maps a pool → A/B/C/D + refusal
  defillama_feed.py (keyless) │               history.py              ← append-only capture (proof-chained)
spa_core/strategy_lab/         │               alerts.py              ← evaluate_hold-driven (Phase 2)
  rates_desk/exit_nav.py ─────┤               portfolio_lens.py       ← read-only addr (Phase 3, flagged)
  rates_desk/depth_at_size ───┤
  rates_desk/rate_policy.py ──┤  CALLED        spa_core/api/routers/dfb.py   (NEW router /api/dfb/*)
  rates_desk/proof_chain.py ──┤  NOT FORKED    landing/src/pages/board/      (NEW Astro section)
  rates_desk/contracts.py ────┘
spa_core/risk/policy.py (RiskPolicy, LLM-forbidden) ──── the deterministic spine, imported, never copied
```

**Hard rules DFB inherits verbatim from `CLAUDE.md`:**
- **Separate sub-project**, separate package `spa_core/dfb/`, separate router/pages — but it **shares
  the risk engine, it does not fork it**. The single rule: *DFB imports `rates_desk` / `risk` /
  `adapters`; it never copies their math.* If DFB needs a number the engine can't yet produce, we
  **extend the engine in place** (with its own tests) and DFB calls the extended function — so SPA's
  desk and DFB always agree to the byte. A `test_dfb_no_fork.py` AST-asserts no duplicated risk math.
- **Never touches paper-trading capital / the go-live track.** DFB is 100% read-only + advisory. It
  reads `data/` snapshots and live keyless feeds; it **never** writes `equity_curve_daily.json`,
  `golive_status.json`, `trades.json`, or any execution-domain file. A guard test asserts DFB's write
  set is confined to `data/dfb/`.
- **stdlib-only runtime** (FastAPI/Astro are the documented exceptions, same as the rest of SPA).
- **No LLM** in risk / classification / refusal anywhere in DFB. **Fail-CLOSED** (a pool with thin/
  stale depth shows a *visible hole*, never a fabricated fill — already the `exit_nav` rule).
- **Atomic writes** (`spa_core.utils.atomic.atomic_save`, same-dir tmp + `os.replace`).
- **No `execution/` import** from any DFB module (AST-asserted, same lint as the rest of read-only SPA).
- **All advisory.** Every DFB surface carries the `IS_ADVISORY` banner + "not financial advice" + EN|RU.

---

## 4. The single highest-value workstream — and why

> **🏆 WS-1.3 — The Per-Pool Risk-Overlay Pipeline (`spa_core/dfb/risk_overlay.py`).**

This is the function that takes a single pool (protocol, chain, symbol, live APY base/reward, TVL,
IL flag, exposure) and returns the **risk-first verdict object**: `{ class: A/B/C/D, refuse: bool,
reason_code, exit_schedule: [...], structural_haircuts: {...}, proof_hash }` — by calling the existing
rates-desk + RiskPolicy engine, never re-deriving it.

**Why it is the crux:**
- It **IS** the differentiator. Every other DFB feature (screener rows, detail pages, alerts, the
  portfolio lens, the Data API) is a *presentation* of this object. Build it once, correctly,
  proof-chained, and the entire product is downstream of it.
- It is the **shared-engine contract**: it's the single seam where DFB touches the SPA risk engine.
  Getting this seam right (import-not-fork, byte-identical to the desk, fail-closed) is what keeps DFB
  honest and keeps the two products from drifting apart.
- It is where **red-team value concentrates**: the highest-severity bug class in this whole program is
  "DFB grades a toxic pool as safe" (the size-down exploit MEMORY already caught once: toxic-LRT
  size-down → structural-haircut veto cap 0.09). The overlay is where that veto must fire. Harden here
  and the blast radius everywhere else shrinks.

Everything in Month 1 exists to stand this pipeline up and prove it; Months 2–3 scale and surface it.

---

## 5. Program shape — how we execute

Per the team's established rhythm (recent git history): **parallel agent lanes** (3–5 workstreams/
month run concurrently), a **rotating red-team** that adversarially attacks each workstream's output,
**continuous push** via `push_to_github.py` (absolute paths, dep-closure, retry on 409), and a
**monthly integration gate**. Every workstream below bakes in three verifications:
- **Property** — an invariant the code must always satisfy (deterministic, in `spa_core/dfb/tests/`).
- **Red-team** — an adversarial input designed to make the feature *lie* (toxic pool graded safe,
  forged proof hash, stale-as-fresh, fabricated fill). It must be *caught*, not merely handled.
- **Smoke** — an end-to-end run (router boots, page renders, real feed flows through, hole shows as a hole).

Effort key: **S** ≈ ½–1 day, **M** ≈ 2–3 days, **L** ≈ 4–6 days, **XL** ≈ 1.5+ weeks (one agent-lane).

---

# MONTH 1 — The Phase-1 LP Risk-Explorer + the data backbone

**Theme:** stand up the risk-overlay pipeline and ship a public screener + pool-detail pages from data
SPA already produces (~35 followed markets). No new data sources. Honest framing: *depth + risk-truth
on a curated whitelist, not a 10,000-pool clone.*

### WS-1.1 — Pool-universe model & data backbone (`spa_core/dfb/pool_universe.py`)
- **What + why:** A deterministic model of the *followed* pool universe, derived from
  `ADAPTER_REGISTRY` + `MULTICHAIN_L2_ADAPTERS` + `BASE_CHAIN_ADAPTERS` + the `defillama_feed`. One
  canonical `Pool` dataclass (`pool_id`, protocol, chain, symbol, tier T1/T2/T3, apy_base, apy_reward,
  tvl_usd, il_risk, exposure, source, as_of). This is the spine every other module reads. Curated
  whitelist now; breadth grows later behind the same overlay.
- **Effort:** M. **Files:** `spa_core/dfb/pool_universe.py`, `spa_core/dfb/contracts.py`.
- **Success:** `build_universe()` returns ≥ 35 pools from the live registry; every field present or
  explicitly `None` (never fabricated); APY units normalized (MEMORY: adapters mix percent vs decimal).
- **Verify:** *Property* — every `pool_id` unique + stable across runs (deterministic id). *Red-team* —
  inject an adapter returning `apy=None` / negative TVL → must surface as `None`/hole, never 0-coerced.
  *Smoke* — `python3 -m spa_core.dfb.pool_universe` prints the live table, 0 fabricated cells.

### WS-1.2 — Risk-overlay pipeline (`spa_core/dfb/risk_overlay.py`) 🏆 *highest-value*
- **What + why:** The crux (§4). `overlay(pool) -> RiskVerdict` calling `rate_policy.evaluate_entry`
  (refusal + reason code + structural haircuts), `depth_at_size.compute_market_depth_row` +
  `exit_nav.compute_ticket_row` (exit-by-size schedule with per-row `proof_hash`), and the tier→A/B/C/D
  map (reuse the academy/`risk_score.py` taxonomy). **Imports the engine, never forks it.**
- **Effort:** L. **Files:** `spa_core/dfb/risk_overlay.py`; minimal *additive* extensions to
  `rates_desk/` if a pool-shaped input needs a new entrypoint (with engine-side tests).
- **Success:** for every pool in the universe, `overlay()` returns A/B/C/D + refuse-bool + reason +
  exit schedule + proof_hash; byte-identical to what the desk computes for the same market.
- **Verify:** *Property* — `proof_hash` reproducible from the verdict's stated inputs+outputs (re-hash
  == stored). *Red-team* — feed a toxic-LRT-shaped pool (ezETH structural tail > cap): must REFUSE at
  **any** size (the size-down exploit), class D, veto cap 0.09 — assert it cannot be sized around.
  *Smoke* — overlay the full live universe end-to-end, 0 exceptions, every hole flagged.

### WS-1.3 — `/api/dfb/*` FastAPI router (`spa_core/api/routers/dfb.py`)
- **What + why:** Surface the universe + overlay over HTTP, reusing the `rates_desk.py` router pattern
  (`APIRouter`, `_shared` readers, `_reproduce_block`, fail-closed JSON). Endpoints: `GET /api/dfb/pools`
  (the screener payload), `GET /api/dfb/pool/{pool_id}` (detail: full exit-NAV schedule + refusal
  decomposition + reproduce block), `GET /api/dfb/proof/{pool_id}` (the per-pool proof chain).
- **Effort:** M. **Files:** `spa_core/api/routers/dfb.py`; register in `spa_core/api/server.py`
  (`app.include_router(dfb.router)`).
- **Success:** all three endpoints return well-formed JSON on the live universe; detail endpoint's
  `reproduce` block lets a third party re-derive the hash; 404 on unknown pool_id (fail-closed).
- **Verify:** *Property* — response schema stable + every numeric cell has a unit + as_of. *Red-team* —
  request a pool_id with stale/thin depth → JSON must carry `insufficient_contemporaneous_depth`, never
  a synthesized fill; tamper with a stored proof and hit `/proof` → mismatch surfaced. *Smoke* — boot
  the server, curl all three, assert 200/200/200 + one 404.

### WS-1.4 — Astro screener + pool-detail pages (`landing/src/pages/board/`)
- **What + why:** The public face. `landing/src/pages/board/index.astro` = the screener table (per row:
  protocol · chain · symbol · TVL · APY base/reward split · A/B/C/D badge · IL flag · exit-by-size
  mini-cell · refuse verdict badge · proof-hash link). `board/[pool].astro` = the detail page (APY/TVL
  history placeholder for M2, full exit-NAV schedule, refusal decomposition, reproduce/verify block).
  Reuse `Layout.astro` + `SiteHeader`/`SiteFooter` + the design system + EN|RU patterns + the
  fail-closed offline-fallback pattern from `exit-nav.astro`.
- **Effort:** L. **Files:** `landing/src/pages/board/index.astro`, `board/[pool].astro`, a
  `BoardTable.jsx` island (sort/filter, like `DashboardLive.jsx`).
- **Success:** `/board` renders the live universe; clicking a row → detail page; holes render *as holes*;
  reward-heavy pools visibly flagged; advisory banner + EN|RU present; `npm run build` 0 errors.
- **Verify:** *Property* — page renders with API offline (graceful fallback, no blank). *Red-team* —
  a D-class refused pool must NOT be visually indistinguishable from an A-class pool (color/label
  contrast asserted); no row can show a green exit-cell over a depth-hole. *Smoke* — full `astro build`
  + one rendered-row snapshot.

### WS-1.5 — Historical capture (`spa_core/dfb/history.py` + `com.spa.dfb_capture`)
- **What + why:** Append-only, proof-chained daily capture of `(pool_id, apy_base, apy_reward, tvl,
  il_risk, class, refuse_state, proof_hash)` → `data/dfb/history/*.jsonl`. The **refusal-state series
  is the scarce asset** (Month 2's charts + Month 3's "this pool *became* refused" alerts depend on it),
  so we start capturing day-1 of the program. New launchd agent via the mandatory deploy gate
  (`scripts/check_agent_before_deploy.sh`, bash-wrapper, `/tmp` logs — CLAUDE.md rule #11).
- **Effort:** M. **Files:** `spa_core/dfb/history.py`, `scripts/agent_dfb_capture.sh`,
  `launchd/com.spa.dfb_capture.plist`, register in `scripts/install_all_agents.sh`.
- **Success:** one capture run appends one dated record per pool, idempotent per UTC day, proof-chained
  (genesis `0`*64), atomic write to `data/dfb/`.
- **Verify:** *Property* — chain verifies (each `prev_hash` links); re-running same day is a no-op.
  *Red-team* — a transient/sandbox run must be REFUSED from polluting the published chain (reuse
  `proof_chain._is_sandbox()` guard). *Smoke* — gate-validate the plist (exit 0, log written) before any
  `launchctl bootstrap`.

**🚦 MONTH-1 TIER-1 GATE:** `/board` is live and public, every row carries A/B/C/D + exit-by-size +
refuse verdict + a *re-derivable* proof hash; the overlay is byte-identical to the desk's own numbers
on shared markets; the toxic-pool red-team REFUSES at any size; all holes show as holes; capture agent
is gate-passed and chaining; full test suite + `npm build` green; `test_dfb_no_fork` + `test_dfb_write_
confinement` + `test_dfb_no_execution_import` pass.

---

# MONTH 2 — Depth + breadth: history, alerts, the portfolio lens, verify

**Theme:** make it *useful over time* and *broader* — still keyless/deterministic — and add the
read-only portfolio lens (the one genuinely new code surface).

### WS-2.1 — Historical charts & APY-trend surface
- **What + why:** Consume `data/dfb/history/` → per-pool APY (base/reward) + TVL + **refusal-state**
  timelines on the detail page; add `apyPct1D/7D/30D` + 30d-mean style trend cells to the screener
  (parity with DefiLlama's trend columns, computed from our own captured series, fail-closed on thin
  history → `INSUFFICIENT_DATA`, never extrapolated).
- **Effort:** L. **Files:** `spa_core/dfb/trends.py`, `/api/dfb/pool/{id}/history`, extend
  `board/[pool].astro` (reuse the academy `AnimatedChart` draw-in pattern with REAL series).
- **Success:** detail pages show real captured history once ≥ 2 points exist; thin history labeled
  `INSUFFICIENT_DATA` not faked. **Verify:** *Property* — trend % matches recompute from raw series.
  *Red-team* — a one-point series must NOT render a trend line (insufficient → labeled). *Smoke* —
  render a pool with seeded multi-day history.

### WS-2.2 — Breadth behind the same overlay (keyless DeFiLlama pools)
- **What + why:** Grow the universe beyond the ~35 desk-followed markets by ingesting *read-only,
  keyless* DeFiLlama yield pools — but **every new pool passes through the identical `risk_overlay`**
  (same A/B/C/D, same refusal, same exit-by-size-or-hole). Breadth never relaxes the risk overlay.
  Honest cap: only pools where we can compute (or fail-closed) an exit bound get a full row; others are
  clearly marked "yield only, risk not yet measured."
- **Effort:** XL. **Files:** `spa_core/dfb/breadth_feed.py` (extend `defillama_feed.py`, keyless),
  `pool_universe.build_universe(include_breadth=True)`.
- **Success:** universe grows to hundreds of pools; **0** breadth pools bypass the overlay. **Verify:**
  *Property* — every breadth pool has a verdict object or an explicit "unmeasured" flag. *Red-team* — a
  high-APY toxic breadth pool must still REFUSE (overlay applies uniformly). *Smoke* — ingest a live
  DeFiLlama page, overlay all, 0 ungraded-but-shown-as-safe rows.

### WS-2.3 — Alerts & watchlists on `evaluate_hold` kill signals
- **What + why:** Per-pool alert rules driven by the desk's *own* `rate_policy.evaluate_hold` kill
  reasons (APY collapse, TVL drain, IL/peg spike, funding flip, **refusal-state flip** — the killer
  alert: "a pool you watch just became one the desk would refuse"). Deterministic, keyless. Watchlists
  stored in `data/dfb/watchlists/`. Delivery reuses SPA's existing channels (deterministic triggers,
  **no LLM**, no new social/notification infra beyond what SPA has).
- **Effort:** L. **Files:** `spa_core/dfb/alerts.py`, `/api/dfb/alerts`, `/api/dfb/watchlist`.
- **Success:** a pool crossing a kill threshold fires exactly one alert (edge-triggered, deduped).
  **Verify:** *Property* — idempotent (same state → no re-fire). *Red-team* — flapping APY across the
  threshold must not spam (debounce). *Smoke* — replay a real depeg series (Oct-2025 Ethena, like the
  academy DepegEventPlayer) → refusal-flip alert fires once on the real date.

### WS-2.4 — Read-only portfolio lens (`spa_core/dfb/portfolio_lens.py`) — *genuinely new code*
- **What + why:** Paste a **read-only address** → DFB reads its on-chain positions and risk-grades each
  with the same overlay ("DeBank tells you what you hold; DFB tells you how risky it is and whether the
  desk would hold it"). **Read-only address ONLY — no wallet-connect, no signing, no custody.** This is
  the one feature needing new code: per-protocol *balance* adapters (read user positions, not protocol
  APY) + token pricing — designed to mirror the existing read-only adapter pattern.
- **Effort:** XL (the largest single lift). **Files:** `spa_core/dfb/portfolio_lens.py`,
  `spa_core/dfb/balance_adapters/` (new, read-only), `/api/dfb/portfolio/{address}` (flagged
  `SPA_DFB_PORTFOLIO_LENS`, default-OFF until balance-adapter coverage is honest),
  `landing/src/pages/board/portfolio.astro`.
- **Success:** for a known test address, returns positions across ≥ 3 protocols, each risk-graded; no
  signing path exists anywhere in the call graph. **Verify:** *Property* — read-only: grep/AST asserts
  no signer/tx/private-key import in the lens. *Red-team* — feed a malformed/EOA-only/contract address →
  fail-closed empty, never crash, never invent positions. *Smoke* — resolve a real read-only address.

### WS-2.5 — "Verify this pool" public surface
- **What + why:** Extend the standalone `scripts/verify_spa.py` philosophy to DFB: a `verify-pool`
  surface (script + `/board/verify` page) where anyone re-derives a pool's risk verdict + exit-by-size +
  proof hash **with zero `spa_core` import** (clean-machine, stdlib-only), proving the published number.
  This is the "don't trust us, check us" brand applied per-pool.
- **Effort:** M. **Files:** `scripts/verify_dfb_pool.py`, `landing/src/pages/board/verify.astro`.
- **Success:** on a clean machine, `verify_dfb_pool.py <pool_id>` reproduces the published proof_hash,
  exit 0, zero `spa_core` import. **Verify:** *Property* — output hash == published hash. *Red-team* —
  tamper a published cell → verifier exits non-zero with the mismatch (tamper-evident). *Smoke* — run in
  a fresh venv with no SPA deps.

**🚦 MONTH-2 TIER-1 GATE:** detail pages show real captured history (thin → `INSUFFICIENT_DATA`);
breadth ingestion live with **0** pools bypassing the overlay; refusal-flip alert fires once on a
replayed real depeg; the portfolio lens resolves a read-only address with **no signing path** (AST-
proven) behind its flag; `verify_dfb_pool.py` reproduces a published hash on a clean machine; all
red-teams caught; suite + build green.

---

# MONTH 3 — The product layer: Data API, polish, the DD story, scale, the DFB section

**Theme:** turn the proven engine + surfaces into a *product* — monetizable (behind a flag), fast,
self-verifying, and presented as a coherent DFB section/site.

### WS-3.1 — Risk-graded Data API (behind `SPA_DFB_DATA_API`, owner-gated launch)
- **What + why:** The on-identity monetization. A clean, documented, *risk-graded* pool-data API
  (the wedge: risk-graded data is scarcer + more defensible than raw data — DeBank Cloud sells raw).
  Reuse SPA's existing `api_security.py` / `rate_limit.py` / `auth.py` / `whitelabel_api.py`. Endpoints
  mirror `/api/dfb/*` but key-gated + metered. **Default-OFF; public launch is OWNER-GATED** (needs
  key issuance/billing/SLA — explicitly owner infra, not buildable autonomously).
- **Effort:** L. **Files:** `spa_core/api/routers/dfb_data_api.py` (flagged), reuse `api_security`/
  `rate_limit`. **Success:** with the flag ON in a test, a keyed request is metered + risk-graded; flag
  OFF → 404 everywhere (no surface leaks). **Verify:** *Property* — flag-OFF = total 404 (no endpoint
  reachable). *Red-team* — unkeyed/over-limit request rejected; a key cannot exfiltrate ungraded data.
  *Smoke* — flag-ON integration test, one metered call.

### WS-3.2 — Public pool-explorer polish & performance/scale
- **What + why:** Make the breadth universe fast and pleasant: server-side pagination/caching of
  `/api/dfb/pools`, precomputed overlay snapshots (`data/dfb/snapshots/`, atomic, refreshed by the
  capture agent), screener sort/filter/search, responsive + motion polish (reuse academy patterns),
  full EN|RU. **Performance is a Tier-1 concern at breadth.**
- **Effort:** L. **Files:** `spa_core/dfb/snapshots.py`, extend `dfb.py` router + `BoardTable.jsx`.
- **Success:** `/api/dfb/pools` p95 < 300ms at full breadth (served from snapshot, not live-recompute);
  screener filters client-side instantly. **Verify:** *Property* — snapshot byte-equals a fresh
  recompute (no drift). *Red-team* — a stale snapshot must be detected + refused (freshness window, like
  `resilience_status`). *Smoke* — load test the pools endpoint at breadth.

### WS-3.3 — The DD / proof story (DFB methodology + self-verifying DD pack)
- **What + why:** A `/board/methodology` page + a self-verifying DFB DD pack (mirroring SPA's existing
  `due-diligence.astro` + `verify_spa.py` story): exactly how the A/B/C/D class, the refusal verdict,
  and the exit-by-size bound are computed; the LLM-free + fail-closed guarantees; the hash-chain; and a
  one-command reproduce. This is what converts a skeptical institutional reader (the future Data-API
  buyer) into a believer.
- **Effort:** M. **Files:** `landing/src/pages/board/methodology.astro`, `docs/DFB_METHODOLOGY.md`,
  extend `scripts/verify_dfb_pool.py` into a `--dd-pack` mode. **Success:** the DD page's every claim
  links to a reproduce step. **Verify:** *Property* — every stated number on the page is reproducible.
  *Red-team* — a claim with no reproduce step fails a doc-lint. *Smoke* — DD-pack reproduces clean.

### WS-3.4 — The DFB section / site & integration
- **What + why:** Tie it together as a coherent **DFB section**: a `/board` landing/console homepage
  (DFB wordmark + tagline + "the risk behind the yield, provably"), nav integration (header/footer link,
  like the academy rollout), the public proof surfaces cross-linked, and the **owner-flagged real
  domain** (`dfb.earn-defi.com`) wired but behind a flag. Monthly integration: DFB + SPA cross-link
  (the desk's own exit-NAV page references DFB; DFB references the desk's track-record).
- **Effort:** M. **Files:** `landing/src/pages/board/index.astro` (homepage), `SiteHeader.astro` /
  `SiteFooter.astro` nav, `astro.config` (domain behind flag). **Success:** DFB is a findable, coherent
  section; `npm build` 0 errors; cross-links resolve. **Verify:** *Property* — all DFB internal links
  resolve. *Red-team* — no DFB page leaks a flagged surface (Data API / domain) when its flag is OFF.
  *Smoke* — full site build + link-check.

### WS-3.5 — Hardening, red-team sweep & monitoring
- **What + why:** A final rotating-red-team sweep across the whole DFB surface (the highest-severity
  class stays "toxic pool graded safe" + "forged/stale proof shown as fresh"); add a `d_dfb` health
  domain to `system_health_monitor.py` (DFB capture freshness, overlay determinism, snapshot freshness,
  flag-OFF leak check); a `verify_dfb` clean-machine surface in the verifier family.
- **Effort:** M. **Files:** `spa_core/monitoring/system_health_monitor.py` (+`d_dfb`),
  `spa_core/dfb/tests/test_redteam_sweep.py`. **Success:** health domain green; sweep finds 0
  unmitigated highs. **Verify:** *Property* — determinism (same inputs → same verdict + hash across
  runs). *Red-team* — the full attack battery (size-down toxicity, forged hash, stale-as-fresh,
  fabricated fill, flag leak) all caught. *Smoke* — `system_health_monitor` reports `d_dfb` OK.

**🚦 MONTH-3 TIER-1 GATE (program completion):** DFB is a coherent public `/board` section serving the
breadth universe fast (p95 < 300ms from snapshots, drift-free); every pool risk-first + re-derivable;
the Data API is built + flag-gated (OFF = total 404), launch owner-gated; the DD/methodology story is
self-verifying on a clean machine; `d_dfb` health domain green; full red-team battery caught; suite +
build green; `DFB_CHARTER`/`DFB_METHODOLOGY` docs match the shipped surface.

---

## 6. Cross-phase dependencies

```
WS-1.1 pool_universe ──► WS-1.2 risk_overlay (🏆) ──► WS-1.3 router ──► WS-1.4 Astro pages
                                  │                         │
                                  ▼                         ▼
                          WS-1.5 history(capture) ──► WS-2.1 charts/trends
                                  │                         │
                                  ├──► WS-2.2 breadth (same overlay)
                                  ├──► WS-2.3 alerts (evaluate_hold)
                                  ▼
                          WS-2.4 portfolio lens (new balance adapters, flagged)
                          WS-2.5 verify-pool ──────────► WS-3.3 DD story
                          WS-2.2 breadth ──► WS-3.2 perf/scale (snapshots)
                          WS-1.2+1.3 ──► WS-3.1 Data API (flagged) ──► WS-3.4 section/site ──► WS-3.5 sweep
```

**Critical path:** `pool_universe → risk_overlay → router → pages` (all Month 1). Everything else hangs
off the overlay. **`history` must start capturing in Month 1** (its series is the only non-recomputable
asset — you cannot backfill a refusal-state timeline).

**How DFB reuses the SPA risk engine without forking it:**
- DFB **imports** `rate_policy.evaluate_entry/evaluate_hold`, `exit_nav.compute_ticket_row`,
  `depth_at_size.compute_market_depth_row`, `proof_chain`, `risk/policy.RiskPolicy`,
  `rates_desk/contracts` (`GateResult`, `KillReason`, `YieldDecomposition`, `RatePolicyParams`).
- If a pool-shaped input needs an entrypoint the engine lacks, we **extend the engine in place**
  (engine-side tests), and DFB calls it — so the desk and DFB are always byte-identical.
- `test_dfb_no_fork.py` (AST) asserts DFB defines **no** risk/refusal/exit math of its own; it only
  composes engine calls. This is the guarantee the two products never drift.

---

## 7. New OWNER-ONLY flags (all default-OFF, designed-behind, never auto-launched)

| Flag | Gates | Why owner-only |
|---|---|---|
| `SPA_DFB_PORTFOLIO_LENS` | the read-only portfolio-lens endpoint/page | balance-adapter coverage must be honest before exposing; owner signs off on coverage claims |
| `SPA_DFB_DATA_API` | the risk-graded Data API surface | public launch needs key issuance / billing / SLA = owner infra + a commercial decision |
| `SPA_DFB_BREADTH` | breadth ingestion of keyless DeFiLlama pools beyond the curated whitelist | scope/identity decision (whitelist-depth vs breadth) + load implications |
| `SPA_DFB_DOMAIN` | binding `dfb.earn-defi.com` / `board.earn-defi.com` | real DNS/domain = owner infra |

> All four are **buildable behind the flag now**; only their *public activation* is owner-gated.
> Flag-OFF must mean **total 404 / no surface leak** (red-team asserts).

---

## 8. Honest buildable-now vs needs-owner-infra split

- **Now, read-only / keyless, autonomous (the bulk — Months 1–2 + most of 3):** the risk-overlay
  pipeline, screener, pool-detail pages, per-pool proof, the `/api/dfb/*` router, historical capture +
  charts, alerts on `evaluate_hold`, breadth ingestion (behind its flag), verify-pool, the DD story,
  performance/snapshots, the DFB section. *All from existing SPA data + modules + the documented
  FastAPI/Astro exceptions.*
- **New code, still no-custody, autonomous:** the read-only portfolio lens (balance adapters + pricing) —
  the one genuinely new data surface; ships behind `SPA_DFB_PORTFOLIO_LENS`.
- **Genuinely needs owner infra / a commercial decision (DEFER, design-behind-flags):** public launch
  of the **Data API** (keys/billing/SLA), the **real domain**, any **paid data source** (we stay
  keyless by default), and **wallet-connect for signing** (we never build this — read-only address only).

---

## 9. Bottom line

DFB is **not** a DeBank/DefiLlama clone. It is **depth + risk-truth on a curated whitelist** that
breadth-extends later behind the **same risk overlay** — the one surface no incumbent publishes:
per-pool exit-liquidity-by-size + a deterministic refusal verdict + a reproducible proof hash, built
from data SPA already produces, LLM-free, fail-closed, read-only, advisory, never touching the go-live
track. The whole product is downstream of one function — the risk-overlay pipeline (WS-1.2) — which is
why Month 1 exists to build and prove it, and Months 2–3 exist to scale and sell it.

*"DeBank shows you the yield. DFB shows you the risk behind it — provably. Don't trust us, check us."*
