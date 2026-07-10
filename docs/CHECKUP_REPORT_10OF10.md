# DeFi Checkup — "10/10 Report" spec triage & build queue

**Source:** external product spec (20 points) for making the AI report a decision-ready investment
conclusion, not just pretty text. **This doc triages it against what the engine ALREADY does and
against the product's hard invariants**, then queues the genuinely-valuable, honestly-implementable
work. Feeds the autonomous roadmap-v2 loop.

## The governing constraint (why we can't just copy the spec)
DeFi Checkup's entire moat is **honesty**: deterministic, fail-closed, non-custodial, evidence-tagged,
**no fabricated numbers**, **no LLM in the risk path**, and **we measure risk, we do not advise a trade
or hold keys**. Several spec ideas are excellent; a few would *destroy* that moat (a fabricated 68/100
score, prescriptive "sell $170k" orders, scenario probabilities, Safe-transaction buttons). Adopting
those would drop us from "the tool you can check" to "another confident-sounding advisor" — a net
*liability* for the exact institutional reader we want. So each point below is SHIPPED / BUILD (honest
form) / REJECT (with reason).

## Legend
✅ **SHIPPED** — already in the engine/report · 🟡 **BUILD** — valuable + honest, queued · ⛔ **REJECT** — violates an invariant

| # | Spec idea | Status | Honest note / what we actually do |
|---|---|---|---|
| 1 | Moment summary (value, yield, risk, main problem, potential loss, action) | 🟡 BUILD | Lead with **quantified real drivers** (capital under elevated risk in $, top concentration %/$, top-3 issues) + the existing qualitative band. **NO fabricated composite "68/100"** (doc 21 §6 forbids a health score — false precision). "Potential loss" = the **real stress Exit-NAV delta** we already compute, framed as a range, never a fabricated point estimate. |
| 2 | One clear verdict | ✅ PARTIAL | Banded verdict shipped (`AnalysisSummary` high/elevated/clear). BUILD: sharpen wording — but verdict stays a **posture**, never a prescriptive trade order (that's #6). |
| 3 | Plain-language explanation of each risk | 🟡 BUILD | Deterministic plain-language templates keyed to `reason_code` (what / why / capital affected / what-could-happen). **No LLM** (hard invariant) — template lookup, not generation. |
| 4 | Concrete dollar figures | ✅ MOSTLY | Exit-NAV $ (current+stress), shares %, coverage % all real. BUILD: add "**capital under elevated risk $**" (derivable). Net-yield / time-to-exit need data we don't have → flag, never fabricate. |
| 5 | Prioritize Critical / Important / Watch + top-3 | 🟡 BUILD | Bucket the already-severity-ranked risks into 3 tiers, surface top-3 first. Clean, deterministic, presentation-level. |
| 6 | Action plan (what/which/amount/deadline/why/after) | 🟡 CAREFUL | Non-prescriptive only. We can show the **deterministic math** ("to get under your concentration threshold you'd reduce by ~$X") as decision-support **fact**. A directive "sell $170k in 24h" is **advice + implies custody** → legal-gated, non-custodial invariant. |
| 7 | Before / after comparison | 🟡 CAREFUL | Before/after on a **real deterministic metric** (concentration % after a clearly-labeled *hypothetical* reduction) is honest. Before/after on a fabricated score is ⛔. |
| 8 | **Hidden dependency / composability analysis** | 🟡 BUILD **(P1 — the differentiator)** | Shared-**issuer** is ALREADY computed (`stablecoin.by_issuer`). Gap: cross-position **shared-oracle** and **shared-bridge** detection ("3 'diversified' positions, one underlying"). Deterministic via static registries; unknown → not asserted (fail-closed). The spec correctly calls this what separates a serious product. |
| 9 | Exit-liquidity check | ✅ PARTIAL | Exit-NAV models size-based haircut + stress. "Amount exitable at <0.5% slippage" and "time to full exit" need pool-depth/withdrawal-queue data we don't currently pull → **flag as data-gap, never fabricate**. |
| 10 | Yield decomposition (base/incentives/gas/decay/net) | 🟡 RA-GATED | Today `yield_quality` is an honest data-gap. Full decomposition needs yield-source classification + **RA sign-off** on the numbers (roadmap Q2-13). Do not print a net APY we can't stand behind. |
| 11 | Scenario analysis (base/negative/critical) | 🟡 PARTIAL | Tail-risk scanned + stress Exit-NAV exist (scenario **impact**). Scenario **probabilities** = ⛔ fabrication without a calibrated model. Keep/expand impact; never assign a % likelihood we didn't measure. |
| 12 | Changes since last report | ✅ SHIPPED | `computeReportDelta` (DC-16) — risk/coverage/position deltas across reports. |
| 13 | Sources & evidence | ✅ SHIPPED | Provenance per field, methodology + policy version, `proof`/`output_hash`, last-verified, `/verify` page. |
| 14 | Confidence level per conclusion | ✅ PARTIAL | Exit-NAV carries confidence; data-gaps are explicit. BUILD: explicit confidence tag on each major conclusion. |
| 15 | No invented data | ✅ CORE INVARIANT | This IS our discipline (data-gaps, unknown≠safe, evidence L0–L6). The spec agrees with us; nothing to change, everything to defend. |
| 16 | Personalize to client Risk Policy | 🟡 BUILD **(P2)** | Let a user/treasury set thresholds (max concentration, min TVL, banned protocols, min liquidity, allowed chains) → evaluate the report against **their** policy. Deterministic, honest, high-value for the treasury buyer. Larger feature. |
| 17 | Separate facts / interpretation / recommendation | 🟡 BUILD | Structure each finding: **fact → interpretation → suggested direction (non-prescriptive) → expected effect**. Presentation-level, honest, pairs with #3/#5. |
| 18 | 3-level readability (30s / 5min / 20min) | ✅ PARTIAL | `AnalysisSummary` → `ReportDashboard` → full `ReportView` (in details) already tiers it. BUILD: label/formalize the tiers. |
| 19 | Role-based versions (exec / risk / technical) | 🟡 LOW | Maps onto the #18 tiers; low incremental value now. Queue-low. |
| 20 | Immediate next actions | 🟡 PARTIAL / ⛔ | **Non-custodial actions OK**: export PDF ✅, add-to-watchlist ✅ (built), compare ✅ (`/compare`), set-alert 🟡 (RESEND owner-gated). **Safe-transactions / execute buttons = ⛔ REJECT** — AI never signs, `execution/` never in read-only path (hard invariant). |

## Build queue (valuable AND honest), prioritized
- **P1 · #8 cross-position shared-dependency** — add shared-**oracle** + shared-**bridge** detection (engine `calculators/` + static registries), surfaced as a "hidden concentration" finding. Issuer axis already done. *The single highest-value, most-differentiating, fully-honest item.*
- **P1 · #1 + #4 + #5 decision-ready headline** — quantified real drivers (capital-under-elevated-risk $, top concentration $/%), Critical/Important/Watch buckets, top-3 first. `AnalysisSummary` + light engine derivation. No composite score.
- **P2 · #3 + #17 plain-language + fact/interpretation separation** — deterministic templates keyed to `reason_code`. No LLM.
- **P2 · #16 client Risk-Policy personalization** — user/treasury thresholds → report evaluated against their policy.
- **P3 · #14 per-conclusion confidence tags · #18/#19 tier labels.**

## Explicit REJECTS (protect the moat — do NOT build)
- ⛔ Fabricated composite risk **score** (68/100) and score-based before/after — false precision, violates the no-score rule.
- ⛔ Scenario **probabilities** — fabrication without a calibrated model.
- ⛔ Prescriptive dollar **trade orders** ("sell $170k now") — advice + custody implication; non-custodial + legal-gated.
- ⛔ **Safe-transaction / execute** buttons — AI holds no keys, is never a signer, `execution/` never imported into read-only code.

All queued items honor: deterministic + fail-closed, no LLM in the risk path, non-custodial, no fabricated
APY/TVL/addresses (evidence L0–L6), engine methodology versioned + fixtures regenerated on schema change.

## Monetization — freemium split (free partial · paid full 10/10)
The full decision-ready report is the paid product; the free tier is a **true partial** that builds trust
and top-of-funnel. **Hard ethics line: the free tier must never leave a user falsely reassured** — if a
CRITICAL risk exists, the free verdict + count MUST say so (we just don't hand over the full remediation
depth for free). We never paywall the *existence* of danger, only its full analysis. This keeps the
honesty moat intact while giving a real reason to upgrade.

| Tier | What it shows | Maps to |
|---|---|---|
| **FREE** (trust hook / funnel) | Moment summary + qualitative band; top-3 issue **titles**; refusal/flag **counts**; coverage %; Exit-NAV headline range; **full `/verify` proof chain (must stay free — the "check us yourself" differentiator is the hook)** | #1(partial) #2 #5(titles) #13 #18(30s) |
| **PAID** (decision-ready depth) | Full cross-position **dependency analysis** (#8); per-position **plain-language** what/why/capital/impact (#3); quantified **capital-at-risk** breakdown (#4); **client Risk-Policy personalization** (#16); scenario **impact** detail (#11); labeled before/after **hypotheticals** (#7); role-based **exports / PDF / committee report** (#19/#20); **retention alerts** delivery (#12) | the whole depth |

**Code vs owner-gated:** the *feature-gating* (free vs paid surfaces, entitlement flag, "upgrade for full
analysis" CTA) is **buildable now** and pairs with the funnel work. The *actually-charging* part —
payments, pricing, terms of service, entity, refund/consumer law — is **owner + legal-gated** (same gate as
the funnel terminal). Build the gating + upgrade surface behind a flag; do not take payment until legal.
Never gate a critical safety signal in a way that misleads (see ethics line above).
