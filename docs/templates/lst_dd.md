# LST / LRT Due-Diligence — <ASSET>

> ETH-002 template. Due diligence for a liquid-staking (LST) or liquid-restaking (LRT) token before it
> may be used in a sleeve. Fill-in; **no invented numbers** — every APY/peg/TVL is `requires
> verification`. The desk **prefers plain LST over LRT** for hedged books; LRT stays isolated /
> research-only ([`../33_yield_thesis_map.md`](../33_yield_thesis_map.md) C1/C2). Cross-refs:
> [`../35_screening_rubric.md`](../35_screening_rubric.md), [`../37_apy_realism_and_evidence_standard.md`](../37_apy_realism_and_evidence_standard.md),
> [`../adr/ADR-YL-008-unified-yield-lab-mandate.md`](../adr/ADR-YL-008-unified-yield-lab-mandate.md).

## Subject
- **asset / ticker:** `<>` · **type:** `<LST | LRT>` · **issuer/protocol:** `<>` · **chain(s):** `<>`
- **analyst / date:** `<>` / `<YYYY-MM-DD>`
- **candidate_id (if from a scan):** `<>`

## 1. Peg mechanism
- **how the token tracks ETH:** `<rebasing | reward-bearing exchange rate | wrapper>`
- **redemption path to ETH:** `<native unstake queue | secondary market only | issuer redemption>`
- **arbitrage that holds the peg:** `<who closes a discount, and how fast>`
- **de-peg history (dated):** `<events + magnitude>` `requires verification`

## 2. Slashing risk
- **slashing surface:** `<consensus only (LST) | + AVS/restaking (LRT)>`
- **operator diversification:** `<how slashing is diversified away; single-operator exposure?>`
- **worst-case slashing loss:** `<estimate + method>` `requires verification`
- **who bears the loss:** `<socialized | insurance | holder>`

## 3. Validator / operator set
- **operator set size & concentration:** `<> requires verification`
- **selection / governance of operators:** `<who adds/removes; permissioned?>`
- **AVS set (LRT only):** `<which services secured; are their rewards proven or speculative?>`

## 4. Withdrawal / exit
- **native unstake queue length (stress):** `<> requires verification`
- **secondary liquidity / depth:** `<> requires verification` (thinner for LRT)
- **exit at size (tier):** `<slippage at intended capital tier — method>` ([`../34_capital_tiers_strategy.md`](../34_capital_tiers_strategy.md))
- **behavior of exit under a de-peg:** `<you exit into the discounted asset — quantify>`

## 5. Points vs realized yield (LRT critical)
- **realized base staking yield:** `<> requires verification` (real economic — issuance + fees + MEV)
- **restaking/AVS yield:** `<proven cashflow? or unproven>` `requires verification`
- **points / airdrop portion:** `<speculative — do points convert to cash? at what rate?>`
- **honest realized-only APY:** `<base + proven only, points EXCLUDED>` `requires verification`
- > Points/airdrop are **subsidy/speculation, not yield** ([`../33`](../33_yield_thesis_map.md) A5/C2) —
  > never carded as sustainable. Hard-reject if the spread depends on unconverted points
  > ([`../35_screening_rubric.md`](../35_screening_rubric.md) §1).

## 6. Depeg-residual when hedged (for neutral sleeves)
- **hedge instrument:** `<short ETH perp / other>`
- **residual β after hedge:** `<target ≈0>` — LRTs de-peg more than LSTs → larger residual
- **funding cost of the hedge:** `<> requires verification`

## 7. Spread-over-floor attribution (ADR-YL-008)
- **live RWA floor (baseline):** `<pct> requires verification` · source `data/rwa_feed.py` @ `<ts>`
- **spread = realized-only APY − floor:** `<bps>`
- **risks that explain the spread (priced):** `<slashing · depeg-residual · exit-queue · contract · AVS>`
- **unexplained spread:** `<bps>` → **if > tolerance: REJECT** (unpriced tail risk; log refusal)
- **spread_fully_explained:** `<true | false>`

## 8. Red team (mandatory for LRT / restaking)
- how do we lose money · de-peg magnitude & recovery · slashing cascade · AVS reward collapse ·
  points never convert · withdrawal-queue freeze · ETH −50% · contract/oracle · most-fragile assumption.
- → run `spa_core/redteam/` battery ([`../35_screening_rubric.md`](../35_screening_rubric.md) §3).

## 9. Verdict
- **evidence level:** `L0–L6` ([`../37`](../37_apy_realism_and_evidence_standard.md))
- **product-line fit:** `<Preserve/Core for plain LST · Max/Experimental isolated for LRT>`
- **verdict:** `REJECT | HOLD | RED-TEAM | PASS` · **next_action:** `<>`
- **notes / codified refusals referenced:** `<e.g. LBTC-restaking rejected, WBTC excluded>`
