# Strategy Candidate — Spark / Sky ecosystem (sDAI / sUSDS / SparkLend) → REFUSE (inherits sUSDS gov-safety) + same-underlying concentration

> Auto-sprint batch (research agent, 2026-07-02). All Spark/Sky rungs inherit the desk's existing sUSDS
> REFUSE (`governance_safety_precondition`) and are the SAME Sky underlying (concentration, not diversification).

- **candidate_id:** `CAND-SPARK-001` · chains: Ethereum
- **venues:** sDAI/DSR ~2.75-3.25%; **sUSDS/SSR 3.75%** (Spark Savings ~$6.4B); **SparkLend USDC ~3.9-4.7%** (SSR floor + utilization; Spark TVL $4.39B live).
- **yield source:** all three = the same Sky Savings Rate engine (RWA T-bills + DAI/USDS PSM [USDC-backed] + protocol revenue). SparkLend's extra ~15-95bps = utilization premium, not a different risk.
- **governance-safety (the flagged concern):** Sky **GSM Pause Delay** was 48h → cut to 16h (2024-03), now ~24h (Feb-2026 execs; sources inconsistent 16/24/30h — read on-chain `Pause.delay()` to confirm). **In every case BELOW the desk's 48h bar** → the sUSDS refusal reason is NOT cured (if anything the delay is lower than at the original hold).
- **verdict:** **REFUSE** — `governance_safety_precondition` (GSM pause delay < 48h), inherited by sDAI/sUSDS/SparkLend. Spread over floor exists (~+0.35pp / SparkLend clears cleanest) but the safety precondition is unmet → spread irrelevant.
- **concentration:** sDAI + sUSDS + SparkLend-USDC all resolve to the **same Sky underlying** (SSR, USDS/PSM, same GSM surface) → treating them as distinct = false diversification; cap the whole Spark/Sky complex as ONE exposure.

*sources: Sky Forum (GSM 48h→16h 2024-03), Sky execs Feb-2026 (~24h), DeFiLlama (Spark $4.39B), Cryptobriefing (Savings $6.4B/SparkLend $3.6B), Eco (SSR 3.75%) — L2. Exact GSM value + live SSR require on-chain verification.*
