# SPA Structural Desk — the research arc (canonical index)

**Date:** 2026-06-26 · **Status:** research arc, advisory only. Everything below is read-only /
paper, moves **no live capital**, and never touches the go-live track. stdlib-only, deterministic,
**LLM-forbidden** in risk/kill, **fail-CLOSED**.

This is the human-readable top-level summary of the Structural Desk arc. Each thesis has its own
detail doc (linked); this page is the map.

---

## The convergent thesis

We asked one question (`docs/RESEARCH_PROMPT_MOAT.md`): *what non-obvious DeFi edge could scale to
~$10M/year with a structural moat, built on SPA's read-only / deterministic stack?*

Our own deep backtest (2024-06→2026-06, real data incl. the Aug-2024 crash) had already killed the
obvious answer: **plain crypto-yield is a diversifier, not an edge** — neutral books don't beat the
~3.4% tokenized-T-bill floor risk-adjusted, directional books eat the full drawdown, LRT restaking
dies in crashes (ezETH depeg). "More APY" is a dead end.

The arc converges on a single insight:

> **The edge is not yield. The edge is the structural role of honest measurement / underwriting —
> being the party that can correctly price and refuse risk others don't see, and prove it.**

So each thesis is a *measurement / underwriting* play, and the cheap, code-only question for each is
the same: *can we MEASURE the mispricing for free, and does the model REFUSE the toxic version?* If
yes, the cheap measurement layer is worth owning; if the measured opportunity is too small or the
real business is gated on off-code legs, the thesis dies (or stays a probe) for free.

---

## The three theses + honest verdicts

| # | Thesis | Module | Verdict | One-line finding |
|---|---|---|---|---|
| 1 | **Rates Desk** — refusal-first fair-value for tokenized rates/carry | `spa_core/strategy_lab/rates_desk/` | ✅ **GO** | FixedCarry validated and runs live-paper; refusal fires on every toxic LRT book; carry leg is real → **fundable**. |
| 2 | **RWA Repo Backstop** — liquidation-NAV underwriter for tokenized-RWA collateral | `spa_core/strategy_lab/rwa_backstop/` | ◐ **measurement-GO / book NO-GO** | 10/10 RWA assets are **not cash-like** on an executable on-chain exit; Safety Board (measurement) is GO; the underwriting book is relationships+capital+legal, off-code. |
| 3 | **Liquidator** — balance-sheet liquidator for long-tail / nested collateral | `spa_core/strategy_lab/liquidator/` | ⛔ **NO-GO** | Addressable long-tail penalty ≈ **$2–4M/yr gross**, ~5–10× **below** the $20M bar → too small to justify the custody + CEX + balance-sheet build. |

---

### #1 — Rates Desk · **GO** · `docs/RATES_DESK.md`, `docs/RATES_DESK_VALIDATION.md`

The edge is a **risk-adjusted fair-value model for tokenized yield** that **(a)** harvests
genuinely-mispriced carry and **(b)** REFUSES yield that is just tail-risk compensation (the
ezETH / over-levered-USDe pattern). A live `RateSurface` (Pendle PT / lending / Boros) feeds a
kind-aware `FairValueEngine` (baseline − 5 structural haircuts → fair implied yield), then a
**refusal-first gate** (`rate_policy.py`, composed *under* the global `RiskPolicy`, only stricter).
Every decision — entry **and** refusal — is hashed into a public **proof chain**.

Validation over real 2024→2026 history (849 survivor days, 2927 pooled carry days, all 3 stress
events in-sample):
- **Assertion 1 (refusal fires early) → PASS.** Toxic LRT PT books (ezETH / rsETH) were refused
  **100% of days** on structural grounds — never held into the depegs; a huge quoted rate never
  rescued a tail-vetoed book.
- **Assertion 2 (survivor book beats the floor) → GO.** Survivor carry book mean ≈ **23.8%/yr** vs
  the **3.4%** RWA floor, beating it in-sample, out-of-sample, and through every stress window.
  (Sharpe is structurally degenerate for held-to-maturity carry — reported as a not-noise check
  only; the verdict rests on the realized book APY.)
- **Calibration pinned** (`max_total_haircut=0.12`, `k_peg=4.0`, `k_protocol=0.02`) confirmed
  optimal by an exhaustive sweep (100% toxic coverage, 100% healthy fire-rate).
- **Exit-liquidity (§9) validated** — the proxy was miscalibrated (stale depth constant) and is now
  tied to contemporaneous per-day pool TVL; the 0.25× sizing cap + `CONCENTRATION` derisk + new
  `EXIT_CAPACITY` hold-kill kept every Oct-2025-stress position out of an illiquid bag.

**4 trade shapes:** `FIXED_CARRY` (A — **the validated, live-paper sleeve**), `LEVERED_CARRY`
(B — PAPER_CANDIDATE but GATED-LEVERAGE-DEPENDENT, "last to enable"), `BASIS_HEDGE` (C —
**BLOCKED-NO-HEDGE**, CEX forward-funding leg not built), `RATE_MATRIX` (D — research-only).
Agent: `com.spa.rates_desk_paper` (hourly forward carry track) + `com.spa.refusal` (daily refusal
scorer).

### #2 — RWA Repo Backstop · **measurement-GO / book NO-GO** · `docs/RWA_BACKSTOP_DERISK.md`

The edge is **not yield** — it is being the transparent liquidation underwriter for tokenized-RWA
collateral: *"lend against Liquidation NAV, not marketing NAV."* The cheap, code-only question:
is RWA collateral genuinely **not cash-like** on an executable exit, and can we **measure** the gap
between marketing NAV ($1.00) and real Liquidation NAV from free data?

The **RWA Collateral Safety Board** (`liquidation_nav.py` + `safety_board.py`, 10 assets) answers
**yes, and the gap is large and measurable**: `LiqNAV = min(on-chain DEX exit, issuer redemption) −
operational haircut`, fail-closed. Result: **not-cash-like on an executable on-chain exit: 10/10**
(0 LIQUID · 1 THIN · 7 REDEMPTION_ONLY · 2 UNSAFE). 9 of 10 have **$0** public on-chain DEX exit a
forced liquidator could execute — cash is reachable only through the relationship-gated redemption
queue.

- **Measurement / Safety-Board layer (cheap, code-only): GO** — deterministic, fail-closed, proves
  the thesis from free data, runs continuously (`com.spa.rwa_safety_board` → `data/rwa_safety_board.json`).
- **The underwriting BUSINESS: NO-GO read-only** — *being* the backstop needs whitelisting +
  redemption agreements, capital to warehouse seized collateral through T+n, and legal (collateral
  perfection, force-redemption). None of it is buildable in code; it is exactly where the value sits.

### #3 — Liquidator · **NO-GO** · `docs/LIQUIDATOR_DERISK.md`

The thesis: be the **delta-neutral, balance-sheet liquidator** for long-tail / nested collateral on
isolated lending (Morpho Blue / Euler V2) — clear bad debt when atomic single-block MEV bots *fail*
(illiquid collateral that can't be routed through a DEX in one tick), hedge via perps, unwind over
hours/days, capture the penalty + OEV the bots can't.

The cheap test measures the **opportunity size** read-only (`market_monitor.py` +
`opportunity_estimator.py`, reusing the `rwa_backstop` slippage primitives; the **exit-gap** is the
real live-measurable signal). Live DeFiLlama `/pools`, Morpho Blue + Euler V2, 784 markets, $9.9B
TVL:

- **TOTAL addressable** (illiquid-gated) penalty ≈ **$3.8M/yr gross**; **top-20 ≈ $2.2M/yr** — both
  ~5–10× **below** the Alt-1 kill bar of **≥ $20M/yr**.
- Honesty correction: a naive symbol-classification gave a **$18M** top-line, but that was an
  artifact of MetaMorpho **curator supply vaults** (stable deposit wrappers, not volatile
  collateral); excluding them collapses it to $3.8M — and $3.8M is an **upper bound**.

**VERDICT: NO-GO.** The cheap read-only monitor/exit-gap is a keeper as a research probe; the
long-tail liquidation opportunity is too small to justify the custody + CEX-execution +
balance-sheet build. Per-position RPC/subgraph indexing is **not yet justified** (it would refine a
number already far on the wrong side of go/no-go).

---

## The shared engine

All three theses run on **one** stack, by design — the de-risk of each is cheap *because* it reuses
what already exists:

- **Read-only data layer** — DeFiLlama `/pools` + `/yields`, `coins.llama.fi` prices, 5-venue perp
  funding (median), tokenized-T-bill (RWA) yields, deep Pendle PT implied-yield history
  (expired+live markets, 2024→2026). All schema-validated, fail-CLOSED, never fabricated.
- **One slippage / exit primitive** — the constant-product DEX-discovery + slippage model lives in
  `rwa_backstop/liquidation_nav.py` and is reused by the liquidator's exit-gap (one source of truth).
- **Refusal-first risk** — a deterministic gate that composes *under* the global `RiskPolicy`, only
  ever stricter; LLM-forbidden in risk/kill; fail-CLOSED (missing/invalid data → max tail-risk,
  never a silent pass).
- **Proof chain** — entries AND refusals hashed into a tamper-evident record (the public "what we
  traded AND what we refused + why").
- **Strategy Lab harness** — pluggable `Strategy` ABC + one shared backtest harness + one live
  paper service; sleeves are `IS_ADVISORY=True` and never move capital pre-go-live.

**API surface** (`spa_core/api/server.py`): `/api/rates-desk/{surface,opportunities,decisions,proof}`,
`/api/refusal`, `/api/rwa-safety-board`, `/api/strategy-lab/promotion`.
**Site pages:** `/rates-desk`, `/rwa-backstop`, `/structural-desk`.

---

## The honest framing — where $10M actually lives

The code did its job: it took each thesis to an **honest verdict** for free. But across all three,
the same boundary appears — **the code can measure and refuse; the $10M is off-code.**

- Thesis #1 is GO and *fundable*, but scaling carry to real size needs **capital + custody +
  execution**, and the levered/basis shapes need a **CEX hedge leg** that isn't built.
- Thesis #2's measurement is GO, but the underwriting book is **relationships (whitelisting) +
  capital + legal** — the redemption leg we can only *document*, not *execute*.
- Thesis #3 is NO-GO on size alone, and even if it weren't, it is gated on **custody + CEX +
  balance-sheet + bad-debt underwriting**.

So the convergent, honest conclusion: **the moat the research asked for is real, but it is a
scale / trust / relationships play, not a code play.** SPA's contribution is the cheapest, most
defensible first layer — the transparent, fail-closed *measurement and refusal* engine that proves
the mispricing — and an honest record of exactly which off-code legs gate the business. The code
builds the proof; the proof is what earns the trust; the trust + capital + relationships are what
turn it into $10M.

---

*RESEARCH ONLY. Everything in the Structural Desk arc is advisory / read-only / paper. Detail docs:
`docs/RATES_DESK.md`, `docs/RATES_DESK_VALIDATION.md`, `docs/RWA_BACKSTOP_DERISK.md`,
`docs/LIQUIDATOR_DERISK.md`, `docs/RESEARCH_PROMPT_MOAT.md`.*
</content>
</invoke>
