# Day-30 Review — SPA go-live track

> **AUTO-GENERATED · deterministic · hash-anchored · read-only · advisory · INERT re: cutover.** The comprehensive review a reviewer/funder reads the moment the evidenced track reaches 30 continuous days. Paper/advisory — not investment advice.

**State:** `TRACK_MATURING` — 11/30 evidenced continuous days — 19 more must accrue before the day-30 review can flip REVIEW_READY (time-gated wait; nothing to fix in code)

**Review readiness:** 36.67% (11/30 evidenced continuous days · 19 to go)

**Review hash:** `e8ad1b5f25e0098da3108dcbafa9eb444f1d313731a2b421dfb7ea708fa779b7`

## 1. The honest reset story

The track was HONESTLY RESET to evidenced-only on 2026-06-26: every bar before the anchor (2026-06-22) — flat-rate backfill, reconstructed placeholders, pre-teardown warmup/seed bars — was flagged non-evidenced and EXCLUDED by rule. Only a day with a real daily_cycle log counts. So this review reports 11/30 evidenced continuous days, not an inflated raw bar-count. A backfilled or future-dated day can never lift this number.

- Anchor: `2026-06-22` · last evidenced: `2026-07-02`
- Continuous: **True** (span 11 days, 0 missing)

## 2. Realized risk-adjusted metrics (evidenced-only)

- Sharpe/Sortino: **THIN → None** (only 10 of 20 evidenced daily returns) — a small-sample ratio is degenerate, so it is REFUSED, never fabricated.
- Realized total return: 0.1208% · realized max drawdown: 0.0%

## 3. Edge at scale — the honest verdict

The edge is NOT raw yield. On the realized forward record the desk does not demonstrably clear the RWA floor by a fundable margin via APY alone — a neutral book is a DIVERSIFIER, not an alpha. The honest edge is the CHASSIS + the MEASUREMENT MOAT: a deterministic, LLM-free, fail-closed refusal engine that harvests real mispriced carry and REFUSES tail-comp yield, with a public, hash-anchored refusal record. That is what scales without a capacity ceiling; APY does not.

- RWA floor: 3.3526% · beats-floor tracks: 4/8 · carry book survives all stress: **True**

## 4. Honest fundability framing

Honest fundability target: RWA floor + ~50–150 bps at ~$5,000,000 of gated capacity — NOT floor + 1000 bps (that would be a fantasy this review refuses to print). The $10M valuation is scale across many gated books + trust (custody / audit / legal / relationships) — OFF-CODE, not more APY. A single rates book does not clear $10M; the moat is scale across many gated books plus off-code trust.

## 5. Refusal record + proof surfaces (don't trust us, check us)

- Refusal record: the public, hash-chained refusal log — every toxic book the desk refused on the live track is a data point that IS the product's credibility
  - API: `/api/refusal · /api/rates-desk/decisions (entries + refusals + proof_hash)` · data: `data/refusal_status.json · data/rates_desk/`
- Equity-chain head: `3774d5b34bc9b2742bbabbb704cad88f3b51b988f5adb9b3111f6c7928339a64` (11 evidenced rows)
- Day-30 artifact proof_hash: `f87057656cd802ceb69fc1c6c13eba74d8800e87c712713f6238e18b5e310f71`
- Verify: `python3 verify_spa.py data/rates_desk/`

## 6. Honest caveats

- Paper/advisory track on a virtual $100k base — $0 real capital is deployed.
- Every number is sourced live from the evidenced record; a missing source reads UNKNOWN, never a fabricated value.
- The evidenced day-count excludes backfill / reconstructed / future-dated bars BY RULE (track_evidence) — a padded day can never inflate readiness.
- The track is THIN: 11/30 evidenced days — 19 more must accrue before the day-30 verdict can read READY_FOR_REVIEW. Nothing here is fixable in code; it is a time-gated wait.
- Risk-adjusted ratios (Sharpe/Sortino) read THIN/UNKNOWN until 20 evidenced daily returns accrue — a small-sample or locked-volatility ratio is a degenerate artifact, so it is refused rather than fabricated.
- The carry edge is capacity-bound (a single rates book does NOT clear $10M); the moat is scale across many gated books plus the trust earned by a transparent refusal engine — off-code (custody / audit / legal / relationships) gates the business, not more APY.

---

_Auto-generated DAY-30 REVIEW pack (RISKWIRE WS1.3). The comprehensive review a real reviewer/funder reads the moment the evidenced track reaches 30 continuous days. Every number is sourced live from the evidenced go-live track + the hardened analytics; a backfilled / reconstructed / future-dated / gapped day can NEVER produce a REVIEW_READY verdict (the continuity assertion refuses it). The review_hash anchors the pack's content (everything except review_hash + generated_at); re-running the pipeline over the same track reproduces it, and any tampered bar breaks it. INERT re: cutover — flips nothing. Paper/advisory — not investment advice._
