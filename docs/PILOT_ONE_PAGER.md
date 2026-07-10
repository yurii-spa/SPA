# SPA — Design-Partner Pilot (one-pager)

> **Status:** DRAFT for a first non-custodial design-partner / DAO-treasury conversation.
> Every number here is either **evidenced** (checkable with our public verifier) or explicitly
> labelled as backtest/target. This is a research desk in paper validation — **not** an offering,
> solicitation, or investment advice. External capital is gated on legal review (not yet cleared).

---

## What we are
A deterministic, **refusal-first** on-chain stablecoin-yield desk whose edge is **honest risk
measurement**, not a higher headline rate. We harvest carry that is mispriced *and refuse the yield
that is merely compensation for tail risk* (depeg / unwind / liquidation). The whole desk is
**fail-closed** and **LLM-forbidden in the risk/execution path**.

## Why this is different — we lead with what we REFUSE
- **Liquidator thesis: NO-GO, published.** ~$3.8M/yr gross addressable, ~5–10× below our $20M bar → we did not build it. We publish our kills, not only our ships.
- **RWA Repo Backstop: measurement-GO / book NO-GO.** The measurement is real; the underwriting is a relationships+capital+legal play, off-code.
- **Rates Desk: GO (paper).** Refusal-first fair-value engine; toxic LRT PT-books refused on structural grounds over the real 2024–2026 history.

## The honest constraints (stated up front — a first LP hears these before any number)
- **The track is THIN and paper.** ~19 evidenced days of a 30-day honest paper track ($100k **virtual** capital, $0 real). Day-30 readiness verdict: **NOT_READY** (~63% evidenced fraction), hash-anchored.
- **The realized forward edge does not yet beat the RWA floor at fundable scale.** Optimizer uplift is a ~$100k artifact; sleeves read INSUFFICIENT_DATA to date. We do **not** claim single-strategy alpha.
- **Capacity is bounded.** Honest addressable is small today (~sub-$100k/yr net) — this is a *scale-across-many-capacity-bound-books + trust* play over years, not a today-rate play.

## What is already PROVEN (checkable, not asserted)
- **"Don't trust us, check us."** A zero-dependency verifier reproduces every published proof surface: `python3 scripts/verify_spa.py data/rates_desk/` (decision chain, exit-nav, equity track, tournament, sleeves) — exit 0 or it names the exact broken row.
- **The safety machinery is proven to FIRE.** `python3 scripts/defenses_exercised_report.py` → **11/11 defenses fire** through the *same* production governance code the daily cycle uses: two-tier kill ladder (SOFT −5% de-risk / HARD −10% all-cash), soft-de-risk blocks every NEW position and INCREASE. The live curve is monotonic (0% drawdown) — the gates are dormant because it never stressed, **not** because they are absent.
- **Public refusal log + proof chain** (hash-anchored, tamper-evident) — we can hand a skeptical reviewer the whole chain without a manual ask.

## The pilot ask (non-custodial, human-in-the-loop)
A small **non-custodial, advisory** allocation as a design partner:
- **We never take custody, never hold keys, never sign.** Execution is human-in-the-loop; the desk produces deterministic, evidence-tagged recommendations + a refusal log.
- You keep full control of funds (your Safe / your signers). We provide the measurement, the refusals, and a reproducible proof of every decision.
- Success = a shared, honest track: the desk's refusals and carry decisions, checkable by you, over a real (small) book.

## What has to be true first (we will not skip these)
1. The 30-day honest paper track completes (evidenced, not backfilled).
2. **Legal review** of entity, disclosure and no-guarantee framing (the fail-closed gate before any external capital).
3. Owner-side custody (2-of-3 Safe, human signers) + an external audit of the execution domain.

---

*Contact via earn-defi.com. Paper research, advisory only — not investment advice, not an offer or
solicitation. Past paper performance does not indicate future results. APY is variable and not
guaranteed. See /disclaimer and docs/FUNDABILITY.md for the full, checkable picture.*
