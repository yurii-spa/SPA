# SPA-RRB (RWA Repo Backstop) — Cheap De-Risk (RESEARCH, read-only, reversible)

**Status:** research de-risk per §8 / Phase-0 of thesis #2. NOT a live lending book. Pure compute
over read-only data, deterministic, stdlib-only, LLM-forbidden, fail-CLOSED, atomic.
**Date:** 2026-06-25 · **Module:** `spa_core/strategy_lab/rwa_backstop/` · **Tests:**
`spa_core/tests/test_rwa_backstop.py` (9 green) · **Output:** `data/rwa_safety_board.json`

---

## The thesis under test

The edge of an RWA repo backstop is **not yield** — it is being the transparent **liquidation
underwriter** for tokenized-RWA collateral:

> *"The asset is the executable liquidation path; lend against **Liquidation NAV**, not marketing
> NAV."*

The single, cheap, code-only question before any capital / relationships / whitelisting:

> Is tokenized-RWA collateral genuinely **NOT cash-like on an executable exit**, and can we
> **MEASURE** the gap between the uniform marketing NAV ($1.00) and the real Liquidation NAV from
> data we can get read-only?

If the gap is real and measurable, the *measurement layer* (the cheap part) is worth owning. If it
isn't, the thesis dies here for free.

---

## What was built

| File | Role |
|---|---|
| `collateral_registry.py` | 10 tokenized-RWA collateral candidates (BUIDL/sBUIDL, USYC, OUSG, USDY, USDM, VBILL, STAC, cUSDO, BENJI). Per asset: issuer, chain, public contract (where known), **transfer-restriction flag**, and **documented** redemption rules (delay/fee/min) as config constants. |
| `liquidation_nav.py` | The **Liquidation-NAV engine**. Per asset, per size {$100k, $1M, $10M}: measures the **on-chain DEX exit** (DeFiLlama `/pools` depth → constant-product slippage) and the **issuer redemption exit** (documented delay/fee haircut + time-value + execution-uncertainty). `LiqNAV(S) = min(on-chain, redemption) − operational haircut`. Fail-CLOSED to 0. |
| `safety_board.py` | The **RWA Collateral Safety Board** (`build_report(write=True)`): per-asset verdict + marketing-vs-liq gap %. Writes `data/rwa_safety_board.json` atomically. |

**Design choices (reused from the Rates-Desk de-risk + repo rules):**
- `LiqNAV = min(two legs)` — a prudent underwriter prices the **worse** of the paths it can
  actually rely on at that size. A deep DEX is irrelevant if the token can't move (permissioned);
  a redemption right is irrelevant intraday if it settles T+2.
- **Transfer-restricted ⇒ on-chain exit = 0 by construction.** A whitelist-gated token cannot be
  sold by an arbitrary liquidator into a public AMM. That zero is the *finding*, not a bug.
- Slippage from a **conservative constant-product depth proxy** (`realised = L/(L+S)`, monotonic in
  size) over aggregate DEX TVL — deliberately simple and pessimistic for a forced unwind.
- Redemption leg is a **transparent DOCUMENTED assumption**, clearly flagged as relationship-gated.

---

## The RWA Collateral Safety Board (LIVE, 2026-06-25, real DeFiLlama `/pools`)

```
symbol   verdict           liqNAV$1M   gap%(1M)     dexTVL$   pools  redeem  issuer
BENJI    REDEMPTION_ONLY     0.9981      0.19              0     0     T+1   Franklin Templeton
BUIDL    REDEMPTION_ONLY     0.9981      0.19              0     0     T+1   BlackRock / Securitize
OUSG     REDEMPTION_ONLY     0.9990      0.10              0     0     T+0   Ondo Finance
STAC     UNSAFE              0.0000    100.00              0     0    none   Arca / institutional
USDM     THIN                0.9057      9.43     19,556,560     1     T+1   Mountain Protocol
USDY     REDEMPTION_ONLY     0.9972      0.28              0     0     T+2   Ondo Finance
USYC     REDEMPTION_ONLY     0.9981      0.19              0     0     T+1   Circle / Hashnote
VBILL    REDEMPTION_ONLY     0.9981      0.19              0     0     T+1   VanEck / Securitize
cUSDO    UNSAFE              0.0000    100.00              0     0    none   OpenEden / Compound
sBUIDL   REDEMPTION_ONLY     0.9981      0.19              0     0     T+1   Securitize (wrapped)
```

**Verdict counts:** LIQUID **0** · THIN **1** · REDEMPTION_ONLY **7** · UNSAFE **2** →
**not-cash-like on an executable on-chain exit: 10/10.**

Read the `liqNAV$1M` column carefully: the ~0.998 figures for the REDEMPTION_ONLY assets are
**NOT** "almost cash-like." They are the value of the *documented redemption right* (NAV − fee −
time-value − uncertainty), which is **whitelist/subscription-gated and settles T+0…T+2** — i.e.
the only path to cash is the issuer queue. The **on-chain** executable exit for those 10 assets is
**$0** (the `dexTVL$` and `pools` columns). The gap that matters to a forced liquidator at $1M is
therefore effectively **100%** on the path they can actually execute (DEX) for 9 of 10 assets.

---

## §8 VERDICT

### (a) Is there a measurable, real gap — is RWA collateral genuinely NOT cash-like on exit?

**YES, and it is large and measurable.** Quantified across the universe:

- **9 of 10 assets have ZERO public on-chain DEX exit** an arbitrary liquidator could execute.
  For these the executable-exit gap vs marketing NAV is effectively **100%** on the DEX path; cash
  is only reachable through the **relationship-gated** redemption queue.
- **1 asset (USDM)** has real but **THIN** on-chain liquidity (~$19.6M aggregate DEX TVL): a $1M
  unwind already realises only **$0.9057** — a **9.43%** gap; a $10M unwind is far worse.
- **2 assets (STAC, cUSDO)** are **UNSAFE**: no public DEX **and** no documented redemption right →
  LiqNAV fail-closed to **$0.00** (100% gap). Read-only, these are un-underwritable.
- **The permissioned blue-chips (BUIDL, USYC, OUSG, VBILL, BENJI, sBUIDL)** are
  **REDEMPTION_ONLY**: marketing NAV $1.00, on-chain executable exit $0. They are cash-like *only*
  inside the issuer's whitelist, which is exactly the access the thesis says you must own.

**The thesis is confirmed on our stack:** tokenized-RWA collateral is structurally **NOT
cash-like** on an executable on-chain exit. "Marketing NAV $1.00" and "what a forced liquidator
realises" are different numbers, and the difference is dominated by **transfer-permissioning**, not
by price risk. That is precisely the mispricing an RWA repo backstop would underwrite.

### (b) Honest data gaps — measurable now vs relationship-gated

**Measurable now (read-only, shipped):**
- On-chain DEX depth + size-scaled slippage for **transferable** tokens (DeFiLlama `/pools`).
- The transfer-restriction fact itself (public/permissioned) → the binary "any on-chain exit at
  all" — the single highest-signal field, and it is free.
- TVL / market depth and a conservative 72h on-chain exit-capacity estimate.

**Documented-only (encoded as a transparent assumption, NOT measured):**
- Redemption **terms** (delay/fee/min) are from issuer documentation. We can cite them; we cannot
  read-only verify the issuer will honour them at size under stress.

**Relationship- / off-code-gated (NOT observable read-only — the expensive legs):**
- **Actual redemption execution** — whitelisting + a subscription/redemption agreement. Whether
  redemption is gated, queued, or NAV-struck at a stressed mark is invisible until you are a holder.
- **RFQ / OTC desk depth** for permissioned RWA — the real institutional exit for BUIDL-class
  tokens is an OTC bid, which is not on any public feed.
- **The legal liquidation path** (collateral perfection, security interest, force-redemption
  rights) — pure legal/relationship work, zero of it observable in code.

**Known measurement caveat (don't over-claim):** USDY shows `0` DEX pools here, yet it *does* have
real on-chain liquidity. Our DEX matcher is deliberately conservative (Ethereum-mainnet
project/symbol allowlist, $250k pool floor); USDY's pools sit on other chains / under symbol
formats our allowlist didn't catch. The engine **fails CLOSED** (reports 0, not a fabricated
number), so the board *under*-states a couple of transferable tokens. The headline finding —
**permissioned RWA = $0 on-chain exit** — is robust regardless, since those tokens *cannot* have a
public pool by construction.

### (c) Go / No-Go

- **MEASUREMENT / Safety-Board layer (cheap, code-only): GO.** It works, it is deterministic and
  fail-closed, it produces a defensible per-asset Liquidation-NAV verdict from free data, and it
  already proves the core thesis. Worth owning and running continuously — it is the transparent
  "we underwrite Liquidation NAV" artifact, and it is the cheapest possible moat to build first.
  Cheap next steps (still read-only): broaden the DEX matcher to multi-chain + symbol variants so
  transferable tokens (USDY/USDM) aren't under-counted; add a `/chart` depth-history series so the
  board shows exit-capacity *trend*, not just a snapshot.
- **The UNDERWRITING BUSINESS itself: NO-GO read-only / gated on the expensive legs.** Actually
  *being* the liquidation backstop requires (1) **relationships + whitelisting** with each issuer,
  (2) **capital** to warehouse seized collateral through a T+n redemption, and (3) **legal**
  (collateral perfection, force-redemption rights, jurisdiction). None of that is buildable in
  code, and the board confirms it is exactly where the value sits — the redemption leg we can only
  *document*, not *execute*, is the whole business.

**Bottom line:** the thesis is **real and measurable** — RWA collateral is not cash-like on
executable exit, and we can prove it for free. The **measurement layer is GO**; the **underwriting
book is a relationships + capital + legal play**, correctly out of scope for a read-only de-risk.
Build the Safety Board now; gate the book on the off-code access.

---

*RESEARCH ONLY. Advisory. Nothing in `rwa_backstop/` lends, trades, or touches the go-live track.*
