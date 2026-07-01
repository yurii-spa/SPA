# RISKWIRE — the Measurement-as-a-Product program · 3-Month Charter

> **Type:** Charter / program plan for the next SPA 3-month arc. Authored by the Senior Architect.
> **Date:** 2026-07-01. **Status:** APPROVED-TO-EXECUTE (owner-independent / read-only / advisory /
> paper-safe / NO-FORK on the risk engine / never touches the go-live track).
> **Re-grounding:** `CLAUDE.md`, `docs/DFB_CHARTER.md` + `DFB_METHODOLOGY.md`, `docs/FUNDABILITY.md` +
> `CARRY_TRUTH.md` + `STRUCTURAL_DESK.md`, `docs/research/DEBANK_RESEARCH.md`, recent git (~40 commits),
> `spa_core/{dfb,strategy_lab,adapters,api}/`, `landing/`.
>
> **One sentence:** *The desk proved its own edge is honest measurement, not yield; DFB proved that
> measurement can be a public product. **RISKWIRE productizes the measurement layer into an
> institutional-grade, self-verifying risk-underwriting line** — the L3 moat that scales without a
> capacity ceiling — while a track-continuity spine guarantees the day-30 milestone actually lands.*

---

## 0. The brutally honest starting point (read this first)

The system is **extremely mature**. In this multi-week session we shipped: the honest edge verdict
(measurement > yield), the full hardening/audit/DR/kill-switch/proof-chain/red-team-as-infrastructure
layer, ~100k green tests, /academy, and an **entire 3-month sub-project (DFB) COMPLETE**. There is no
vanity code left that would move the needle.

**The real blockers are, in order:**
1. **TIME** — the evidenced track is 6/30 days (anchor 2026-06-22, target ~2026-07-21). No code
   accelerates this.
2. **A LIVE track-continuity bug** — `gap_monitor.json` shows a real gap **2026-06-26 → 2026-06-30
   (3 days missed)**; `real_track_days` is **stuck at 6**, `consecutive_ready_days: 0`. The daily
   cycle is not reliably banking a day per day. **If this is not fixed, the day-30 milestone slips
   indefinitely** regardless of everything else. This is the single most urgent thing in the whole
   program and it is owner-independent.
3. **OFF-CODE trust** — custody, external audit, legal, relationships, real CEX execution. Deferred
   by hard constraint; no code closes these.

**So the honest highest-value arc is a fusion, not a single candidate:** the **L3 measurement moat,
productized** (candidate arc #1 — the Investment Director's #1 conclusion, and the only line with **no
capacity ceiling**), **spined by track-continuity + day-30 readiness hardening** (candidate arc #3's
readiness half — building readiness, never flipping). DFB (arc #2) is *done*; we extend its engine, we
do not rebuild it. Deepening desk yield (arc #5) is explicitly de-prioritized — `CARRY_TRUTH.md` and
`FUNDABILITY.md` already proved yield is a dead end past ~$1M; chasing +bps is the vanity trap this
charter refuses.

> **Is it genuinely 3 months?** **Yes — the productization is.** But **Phase 1 is front-loaded with
> the track-continuity fix and could stand alone in ~3 weeks**; if the owner wants to stop after Phase
> 1 and simply let the track mature, that is a legitimate, honest exit. Phases 2–3 are the real
> 3-month bet on the moat. I commit to the full arc but flag the natural early-exit at the Phase-1
> gate.

---

## 1. The arc — RISKWIRE, and WHY it is highest-value

**RISKWIRE = the measurement/underwriting/proof layer (L3), turned into a coherent product line.**

Today the L3 moat exists as **three disconnected seeds**:
- **DFB** (`spa_core/dfb/`) — public pool risk-explorer (A/B/C/D + exit-by-size + refusal + proof).
- **RWA Safety Board** (`spa_core/strategy_lab/rwa_backstop/safety_board.py`) — per-asset
  LIQUID/THIN/REDEMPTION_ONLY/UNSAFE verdicts.
- **Underwriting Report** (`spa_core/strategy_lab/underwriting/`, `data/underwriting/`,
  `/api/underwriting/*`) — a hash-anchored, flag-gated institutional report.

They share the SAME engine (`rates_desk/{exit_nav,depth_at_size,rate_policy,proof_chain}`) but there is
**no unified product, no cross-surface consistency guarantee, no institutional-grade deliverable, no
self-verifying report generator that a fund's risk team could actually consume.** RISKWIRE is that
product: **one risk-truth engine → many provable, self-verifying deliverables**, each carrying the
"don't trust us, check us" proof chain.

**Why highest-value (honest):**
- It is the **only** line with **no capacity ceiling** — L1 caps at ~$50-100M at-floor, L2 carry caps
  at ~$1.5-1.7M by venue depth, but *measurement/underwriting/proof sells to N clients with zero
  capital deployed*. This is the $10M-through-trust path the Investment Director named.
- It is built **entirely from data SPA already produces** — no new capital, no custody, no execution.
- It is **deterministic + LLM-free + fail-closed + reproducible** — the one thing "AI risk scoring"
  incumbents structurally cannot match, and the exact thing a due-diligence buyer needs.
- It **compounds the track**: every day the desk refuses a toxic book on the live track is a data
  point in the public refusal record that IS the product's credibility. Productizing L3 and maturing
  the track are the same flywheel.

**Everything is behind owner flags** (public launch is an owner + off-code decision — keys, billing,
SLA, legal). We build the product to genuinely-ready; the owner flips it. Building ≠ launching.

---

## 2. Scope — IN vs OUT

### ✅ IN (owner-independent, on-identity)
- A **unified RISKWIRE engine facade** over the three seeds — one entry, one taxonomy, guaranteed
  cross-surface consistency (NO-FORK; a thin facade over the existing engine, never a copy).
- A **self-verifying institutional risk/underwriting report generator** (per-protocol, per-portfolio,
  per-collateral) — every claim cites the engine line that computed it + a reproduce block, extending
  the existing `underwriting/report.py` proof-chain pattern.
- A **standing risk-oracle surface**: continuously-updated per-market risk verdicts + refusal state +
  exit-by-size, versioned and hash-anchored over time (the scarce time series).
- A **cross-protocol contagion / dependency lens** (read-only): which followed markets share
  collateral / oracle / bridge / issuer roots → shared-risk graph, deterministic.
- A **depeg / refusal-flip early-warning** layer over the standing surface (extends `dfb/alerts.py`).
- The **track-continuity + day-30 readiness spine** (self-healing daily cycle, gap backfill guardrails,
  a day-30 review pipeline, fundability artifact refresh).
- All public surfaces **flag-gated**; all report/API deliverables **self-verifying**.

### ⛔ OUT (deferred by hard constraint — design behind flags only)
Real capital/custody/MPC · external audit · `is_live`/`SPA_EXEC_ARMED` flip · real CEX execution ·
public Data-API launch (keys/billing/SLA) · real domains · paid data sources · wallet-connect/signing ·
investor-cabinet launch · kill-switch threshold VALUES · public competitor-NAMING · git-tag/GPG.
Also OUT: chasing desk yield above the honest floor+50-150bps (proven dead end).

---

## 3. NO-FORK & Tier-1 invariants (every workstream)

Every task inherits: **stdlib-only runtime** (FastAPI/Astro exceptions) · **no LLM in risk/kill** ·
**fail-CLOSED** · **atomic writes** (`atomic_save`, same-dir tmp + `os.replace`) · **no `execution/`
import** · **read-only / paper-safe** · **NEVER touches the go-live track** · **NO-FORK** — anything
touching the risk verdict calls the existing engine, byte-identical, never a copy · every deliverable
**self-verifying** (reproduce-with-zero-`spa_core`-import) · every public surface **owner-flag-gated**.

**Baked-in verification per workstream** (non-negotiable — no workstream is "done" without all three):
- **property test** — an invariant that must hold for all inputs (monotonicity, fail-closed, no-fork
  byte-identity, flag-OFF-no-leak).
- **red-team probe** — an adversarial attempt to make the surface lie (size-down exploit, tamper →
  broken_at, fabricate-a-number, hide-toxicity-in-UI, flag-bypass).
- **smoke** — an end-to-end run against live `data/` proving the surface renders honestly and never
  500s.

---

## 4. Owner-only NEW flags (default OFF; building behind them is owner-independent)

| Flag | Governs | Default |
|---|---|---|
| `SPA_RISKWIRE_REPORTS` | public serving of RISKWIRE institutional report deliverables | OFF → 404 |
| `SPA_RISKWIRE_ORACLE` | public serving of the standing risk-oracle time-series surface | OFF → 404 |
| `SPA_RISKWIRE_CONTAGION` | public serving of the cross-protocol contagion/dependency graph | OFF → 404 |

Reuse existing: `SPA_DFB_DATA_API`, `SPA_DFB_BREADTH`, `SPA_UNDERWRITING_PUBLISH`. No flag flip is in
scope; the owner owns every flip. The report/oracle/contagion data files are ALWAYS written (proof
chains grow, verifiability accrues); flags govern **public surfacing only**.

---

## 5. The three monthly phases

### PHASE 1 (Month 1) — Spine + Engine Facade: "the track banks a day every day, and the three L3 seeds become one engine"
**Theme:** fix the continuity bug, guarantee the day-30 milestone, and unify the L3 engine so Phases
2-3 build on ONE surface. This phase is front-loaded and can stand alone.

**WS1.1 — Track-continuity self-heal (HIGHEST-VALUE WORKSTREAM, see §6)**
- *What+why:* Root-cause the 2026-06-26→06-30 gap (`gap_monitor.json` `history_gap`, `real_track_days`
  stuck at 6). Make the daily cycle **provably bank exactly one evidenced day per UTC day** or emit a
  loud, self-healing recovery — a missed cycle must auto-recover on the next run without corrupting the
  track (respect the `PAPER_REAL_START_DATE` guard; NEVER backfill fabricated bars). Add a
  continuity-watchdog that HALTS-loud (Telegram + `system_health`) on any gap, and a `data/`-safe
  recovery path that re-banks a genuinely-missed real day from live adapter state.
- *Effort:* L (root-cause + fix + drill). *Files:* `spa_core/paper_trading/{cycle_runner,gap_monitor}.py`,
  `spa_core/monitoring/{cycle_health,system_health_monitor}.py`, new `spa_core/paper_trading/continuity_guard.py`,
  `scripts/drill_track_gap.py`.
- *Success:* a fresh-machine drill simulates a missed daily cycle → next run banks the missed real day
  (or refuses with a loud honest reason) → `gap_monitor` returns `no_gap` → `real_track_days` advances.
- *Verify:* **property** = "for any missed-day sequence, `real_track_days` is monotonic non-decreasing
  and never double-counts a UTC day"; **red-team** = "inject a fabricated bar / a future-dated bar →
  guard REFUSES, track untouched"; **smoke** = run the drill against a sandbox copy of live `data/`.

**WS1.2 — RISKWIRE engine facade (NO-FORK unifier)**
- *What+why:* One module `spa_core/riskwire/engine.py` exposing `assess(market) -> RiskwireVerdict`
  that composes the EXISTING `rates_desk` engine + `dfb.risk_overlay.classify` + `rwa_backstop`
  verdict into ONE canonical verdict object (A/B/C/D + exit-by-size + refusal decomposition + collateral
  safety + proof hash). It CALLS the seeds; it never copies logic. DFB, safety board, and underwriting
  report all re-route through it → guaranteed cross-surface consistency.
- *Effort:* M. *Files:* new `spa_core/riskwire/{__init__,engine,contracts}.py`; adapt callers in
  `spa_core/dfb/risk_overlay.py`, `strategy_lab/underwriting/report.py`, `rwa_backstop/safety_board.py`.
- *Success:* the same market assessed via DFB overlay, the report, and the facade returns
  **byte-identical** verdict + proof hash across all three.
- *Verify:* **property** = no-fork byte-identity across surfaces; **red-team** = perturb one surface's
  input → all three diverge identically (no surface silently "fixes" a worse number); **smoke** = assess
  all ~38 followed markets end-to-end.

**WS1.3 — Day-30 review pipeline + fundability refresh**
- *What+why:* An owner-independent, deterministic pipeline that, on the day the track reaches
  N-evidenced-days, regenerates `FUNDABILITY.md` + `CARRY_TRUTH.md` from realized-only data and emits a
  self-verifying "day-30 review pack" (the honest verdict the owner reviews before any cutover thought).
  INERT re: cutover (never flips anything).
- *Effort:* M. *Files:* `spa_core/strategy_lab/{fundability,carry_truth_table}.py`, new
  `spa_core/paper_trading/day30_review.py`, `scripts/day30_review.py`.
- *Success:* pipeline runs on a sandbox track at day-30 → emits a hash-anchored review pack whose every
  number is realized-or-INSUFFICIENT_DATA, no fabrication.
- *Verify:* **property** = every cell traces to a realized source or is INSUFFICIENT_DATA; **red-team** =
  feed a thin track → pack reads INSUFFICIENT_DATA, never a fabricated verdict; **smoke** = run on live.

**WS1.4 — RISKWIRE proof-chain unification + verifier extension**
- *What+why:* One proof chain the standalone `scripts/verify_spa.py` verifies for ALL RISKWIRE
  deliverables (reports, oracle snapshots, contagion graphs) — extend the existing chain, don't fork it.
  "Don't trust us, check us" must hold across the new product line with zero new trust assumptions.
- *Effort:* M. *Files:* `scripts/verify_spa.py`, `spa_core/strategy_lab/rates_desk/proof_chain.py`,
  new `spa_core/riskwire/proof.py`.
- *Success:* `verify_spa.py` on a clean machine reproduces every RISKWIRE hash; tamper → `broken_at`.
- *Verify:* **property** = tamper-evidence (any byte change → chain break at exact index); **red-team** =
  splice a fabricated section → verifier flags it; **smoke** = clean-machine reproduce.

**WS1.5 — d_riskwire health domain**
- *What+why:* A fail-CLOSED health domain (like `d_dfb`) over the RISKWIRE surfaces: facade-fresh,
  chain-valid, continuity-guard-armed, flag-OFF-no-leak canary. Auto-surfaced in SYSTEM_BRIEFING.
- *Effort:* S. *Files:* `spa_core/monitoring/system_health_monitor.py`, `scripts/update_system_briefing.py`.
- *Success:* `d_riskwire` reports OK only when all checks pass; missing artifact → WARNING.
- *Verify:* **property** = fail-closed (missing → not-OK); **red-team** = stale snapshot → WARNING;
  **smoke** = appears in SYSTEM_BRIEFING.

**PHASE-1 FINAL TIER-1 GATE:** track banks a day per UTC day on a drill (WS1.1) · facade returns
byte-identical verdicts across all three seeds (WS1.2) · `verify_spa.py` reproduces every RISKWIRE hash
on a clean machine (WS1.4) · `d_riskwire` green in SYSTEM_BRIEFING (WS1.5) · full suite green · red-team
sweep (5 probes) all PASS. **→ Natural early-exit point: if the owner wants to stop and let the track
mature, Phase 1 delivered is a complete, valuable increment.**

---

### PHASE 2 (Month 2) — The Deliverables: "one engine → institutional-grade, self-verifying products"
**Theme:** turn the unified facade into the actual sellable-but-flag-gated deliverables.

**WS2.1 — Self-verifying institutional risk report generator**
- *What+why:* Extend `underwriting/report.py` into a general RISKWIRE report generator that produces a
  per-protocol / per-portfolio / per-collateral **risk-underwriting report** a fund's risk desk could
  consume: exit-by-size schedule, refusal decomposition, contagion exposure, historical refusal record,
  every claim citing the engine line + a one-command reproduce. Hash-anchored, flag-gated
  (`SPA_RISKWIRE_REPORTS`).
- *Effort:* L. *Files:* new `spa_core/riskwire/report.py`, `spa_core/api/routers/underwriting.py` (extend),
  `docs/RISKWIRE_METHODOLOGY.md`. *Success:* generate a report for a real protocol; a skeptic reproduces
  every number with zero `spa_core` import. *Verify:* **property** = every claim cites a reproduce hash;
  **red-team** = alter a served number → doesn't match reproduce → caught; **smoke** = flag-OFF → 404.

**WS2.2 — Standing risk-oracle time-series surface**
- *What+why:* A continuously-updated, versioned, hash-anchored per-market risk-verdict series (the
  scarce data: refusal-state-over-time, exit-capacity-over-time). A standing agent captures a snapshot
  per cycle. Flag-gated (`SPA_RISKWIRE_ORACLE`). *Effort:* L. *Files:* new
  `spa_core/riskwire/oracle.py`, `scripts/riskwire_capture.py`, `launchd/com.spa.riskwire_capture.plist`,
  `data/riskwire/oracle/`. *Success:* daily snapshots accrue, each verifiable, gaps loud. *Verify:*
  **property** = snapshot append-only + monotonic hash chain; **red-team** = rewrite a past snapshot →
  chain break; **smoke** = agent heartbeat in `d_riskwire`. (Agent deploy via `check_agent_before_deploy.sh`.)

**WS2.3 — Cross-protocol contagion / dependency lens**
- *What+why:* A deterministic read-only shared-risk graph: which followed markets share collateral /
  oracle / bridge / issuer roots → contagion exposure per market. The measurement no incumbent
  publishes. Flag-gated (`SPA_RISKWIRE_CONTAGION`). *Effort:* L. *Files:* new
  `spa_core/riskwire/contagion.py`, `data/riskwire/contagion/`, `/api/riskwire/contagion`. *Success:* a
  known shared root (e.g. a common oracle) surfaces as shared exposure across the right markets.
  *Verify:* **property** = graph is deterministic + acyclic-where-expected; **red-team** = inject a
  phantom edge → not present without a real dependency source; **smoke** = renders for live universe.

**WS2.4 — RISKWIRE site surfaces (design-system reuse)**
- *What+why:* `/riskwire` hub + `/riskwire/reports` + `/riskwire/oracle` + `/riskwire/contagion` on the
  existing Astro site, canonical SiteHeader/Footer, EN|RU, cross-linked from `/board` and
  `/structural-desk`. Public data only where the flag is ON; otherwise an honest "owner-gated" state.
  *Effort:* M. *Files:* `landing/src/pages/riskwire/*.astro`. *Success:* builds; flag-OFF pages show the
  honest gated state, never leak flagged data. *Verify:* **property** = flag-OFF-no-leak; **red-team** =
  view-source for hidden flagged data → none; **smoke** = `astro build` clean.

**WS2.5 — Red-team lane: deliverable-integrity sweep**
- *What+why:* A rotating adversarial suite specifically against the Phase-2 deliverables: can a report
  understate a toxic book? can the oracle be rewound? can contagion hide a shared root? Wire into the
  existing `redteam.py` router + `verify_spa.py`. *Effort:* M. *Files:* `spa_core/api/routers/redteam.py`,
  `spa_core/riskwire/tests/`. *Success:* every probe fails to make a surface lie. *Verify:* the sweep IS
  the verification.

**PHASE-2 FINAL TIER-1 GATE:** report generator produces a real self-verifying report reproduced on a
clean machine · oracle series accrues + is chain-verifiable · contagion graph renders for the live
universe · all flag-OFF surfaces leak nothing · deliverable-integrity red-team (≥6 probes) all PASS ·
full suite green.

---

### PHASE 3 (Month 3) — Productization + Consumability: "a due-diligence buyer could actually use this (behind a flag)"
**Theme:** make RISKWIRE a coherent, consumable product line, hardened for a real (owner-flipped) launch.

**WS3.1 — RISKWIRE Data API v1 (flag-gated, no-fork of DFB Data API)**
- *What+why:* `/api/riskwire/v1/*` (report / oracle / contagion / verdict) behind
  `SPA_DFB_DATA_API`-style auth (reuse `auth.py` + Keychain key + rate-limit tiers), byte-identical to
  the public overlay (no-fork). Owner-gated launch (keys/billing/SLA remain owner + off-code). *Effort:*
  L. *Files:* new `spa_core/api/routers/riskwire_v1.py`, `docs/RISKWIRE_DATA_API.md`. *Success:*
  flag-ON returns key-authed, rate-limited, byte-identical data; flag-OFF → total 404. *Verify:*
  **property** = byte-identity with overlay; **red-team** = no-key / over-limit / flag-OFF bypass all
  refused; **smoke** = key-authed round-trip.

**WS3.2 — Self-verifying DD/risk-report pack generator (the "check us" deliverable)**
- *What+why:* A one-command generator that produces a full institutional DD pack for a named
  protocol/portfolio: RISKWIRE report + proof chain + the standalone verifier + reproduce instructions,
  as a self-contained bundle a skeptic runs offline. Extends the existing self-verifying-DD pattern.
  *Effort:* M. *Files:* new `scripts/riskwire_dd_pack.py`, `docs/RISKWIRE_DD.md`. *Success:* the pack
  reproduces every number on a clean machine with zero `spa_core` import. *Verify:* **property** =
  offline-reproducible; **red-team** = tamper the bundle → verifier flags; **smoke** = end-to-end pack.

**WS3.3 — Standing perf + O(1) snapshot reads + capacity-honest framing**
- *What+why:* Snapshot-O(1) reads (no recompute on the wire — like DFB Month-3), p95 tripwire, and an
  honest capacity/positioning doc: RISKWIRE is depth+truth on a whitelist, breadth grows behind the
  identical overlay, and it is a *measurement product with no capital deployed* — never oversold.
  *Effort:* M. *Files:* `spa_core/riskwire/oracle.py` (snapshot reads), `docs/RISKWIRE_METHODOLOGY.md`.
  *Success:* p95 read < ~50ms, no-recompute tripwire green. *Verify:* **property** = served == snapshot
  (no wire recompute); **red-team** = force a recompute path → tripwire fires; **smoke** = load probe.

**WS3.4 — Day-30 landing + fundability integration (spine payoff)**
- *What+why:* If the track has matured to day-30 within the program window, run WS1.3's review pipeline
  for real, refresh the fundability/carry-truth artifacts, and fold the honest verdict into the
  RISKWIRE credibility story (the live refusal record IS the product's proof). INERT re: cutover.
  *Effort:* M. *Files:* `spa_core/paper_trading/day30_review.py`, `docs/FUNDABILITY.md`. *Success:*
  day-30 pack emitted honestly (or, if the track is still short, an honest INSUFFICIENT_DATA pack).
  *Verify:* realized-only property + thin-track red-team + live smoke (as WS1.3).

**WS3.5 — Program consolidation + final red-team sweep + STRUCTURAL_DESK integration**
- *What+why:* Fold RISKWIRE into the canonical maps (`STRUCTURAL_DESK.md`, `CLAUDE.md`, SYSTEM_BRIEFING),
  cross-link the site, and run the FINAL adversarial sweep across the entire product line (no-fork
  byte-identity, tamper→break, fail-closed 0-fabrication, flag-OFF-no-leak, UI-can't-hide-toxicity,
  size-down-not-exploitable, oracle-not-rewindable). *Effort:* M. *Files:* `docs/STRUCTURAL_DESK.md`,
  `CLAUDE.md`, `spa_core/api/routers/redteam.py`. *Success:* final sweep (≥8 probes) all PASS; docs
  coherent; one narrative from desk → DFB → RISKWIRE. *Verify:* the sweep + a full clean-machine
  verify_spa run.

**PHASE-3 FINAL TIER-1 GATE:** RISKWIRE Data API v1 byte-identical + flag-gated + auth-enforced · DD
pack reproduces offline on a clean machine · O(1) snapshot reads with tripwire · day-30 pack emitted
honestly (realized-or-INSUFFICIENT_DATA) · RISKWIRE in all canonical maps · FINAL red-team sweep (≥8
probes) all PASS · full suite green · `verify_spa.py` reproduces every RISKWIRE hash on a clean machine.

---

## 6. The SINGLE highest-value workstream

**WS1.1 — Track-continuity self-heal.** Brutally: the entire $10M thesis rests on a **30-day evidenced
honest track**, and right now the track **is not banking a day per day** (real gap 06-26→06-30,
`real_track_days` frozen at 6, `consecutive_ready_days: 0`). Every other piece of the program — the
fundability verdict, the RISKWIRE credibility story, the day-30 milestone, any future cutover thought —
is **downstream of a continuous track**. A beautiful measurement product on top of a broken track proves
nothing. This is owner-independent, it is the cheapest high-leverage fix in the system, and it must be
Task #1. Fix the spine before building on it.

---

## 7. Cross-phase dependencies

- **WS1.2 (facade) blocks all of Phase 2** — reports/oracle/contagion route through the facade.
- **WS1.4 (proof unification) blocks WS2.1/WS3.1/WS3.2** — every deliverable needs the unified chain.
- **WS1.1 (continuity) blocks WS1.3 & WS3.4** — the day-30 pipeline is meaningless on a broken track.
- **WS1.5 (d_riskwire) consumes WS2.2's capture heartbeat** — health domain matures across phases.
- **WS2.4 (site) depends on WS2.1-2.3 data**; **WS3.4 (day-30 landing) depends on WS1.1 + WS1.3.**

---

## 8. Execution model

Parallel agent lanes per phase (WS lanes run concurrently once their deps clear) + a **rotating
red-team lane** adversarial-reviewing every merge + continuous push + **monthly integration** at each
FINAL TIER-1 GATE. The go-live track is **byte-untouched** by everything except WS1.1's guarded,
honest, real-day recovery path (which only ever re-banks a genuinely-missed real day or refuses loud).

---

## 9. Honest bottom line

RISKWIRE is the right 3-month bet **because it is the one line that scales without a capacity ceiling
and is 100% owner-independent to build.** But the charter is honest twice over: (1) the most urgent
thing is a **track-continuity bug**, not a product — fixed first; and (2) **the moat's payoff is
off-code** (trust, custody, legal, relationships) and the track's maturation is **time**, neither of
which code closes. So we build the provable product and fix the spine — **the two things code *can*
do** — and we do not pretend either the track or the trust can be rushed. If the owner reads Phase 1
and says "just fix the track and let it mature," that is a legitimate, honest stop. The full arc is the
bet that when the track lands and the trust is earned, the *product that makes the trust legible* is
already built.
