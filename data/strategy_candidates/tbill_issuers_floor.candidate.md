# Strategy Candidate — Tokenized T-bill issuers as floor-realizing rungs → ADVANCE (USYC/BUIDL/USTB) · REFUSE-as-floor (USDY)

> Auto-sprint batch (research agent, 2026-07-02). The tokenized-T-bill issuers ARE the floor constituents —
> none generates spread *over* the floor; "ADVANCE" here = which is the cleanest/deepest/lowest-fee vehicle
> to REALIZE the floor with instant liquidity + bounded issuer/custody risk. Names the best cash-floor rungs.

- **candidate_id:** `CAND-TBILL-ISSUERS-001` · **strategy_type:** `RWA floor realization` · **chains:** Ethereum + multi

| Issuer / token | Net APY | AUM | Custody / redemption | Verdict |
|---|---|---|---|---|
| **Circle/Hashnote USYC** | ~4.0%+ (verify) | ~$3.0B | Circle Intl Bermuda; **T+0 atomic → USDC** | ✅ **ADVANCE (best rung)** — deepest, native-USDC atomic redemption |
| **BlackRock BUIDL** | ~3.5-4% | ~$2.85B | BNY Mellon custody; T+0 for APs; **~$5M min** | ✅ **ADVANCE (gated)** — most credible custody, institutional-only |
| **Superstate USTB** | 7d ~3.36% / 30d ~3.44% | ~$814M | USD/USDC daily, **no min**; Invesco PM Q2-2026 | ✅ **ADVANCE** — low-fee, no-min practical pick (watch Invesco transition) |
| **Ondo OUSG** | ~3.45% | ~$692M | 24/7 instant→stable, $5K min, KYC-per-transfer; fee waived to 2027 | ◐ CONDITIONAL — nested-issuer (into BUIDL) + transfer-KYC |
| **Franklin BENJI** | 7d ~3.5% | ~$0.83B fund | US-registered '40-Act mutual fund; app/broker redemption (non-atomic) | ◐ CONDITIONAL — best reg wrapper, weaker as a *liquid* rung |
| **Ondo USDY** | ~4.65% | >$1B | **NOTE (debt claim)** + bank deposits; $100K min; non-US | ⛔ **REFUSE-as-floor** — the excess over floor = note/bank/jurisdiction tail-comp, not clean T-bill risk |

- **verdict:** floor-realizing ADVANCE = **USYC + BUIDL** (deep, credible, T+0), **USTB** the no-min practical choice. `reason_code: floor_realizer_liquidity_custody`. **USDY refused as a "floor" holding** (`excess_is_tailcomp_note_structure`) — it's a directional yield product, not clean cash-floor.
- **honest note:** no issuer beats the floor — they DEFINE it. The ADVANCE is on liquidity + custody quality only. Ladder implication: name **USYC** as the floor rung's realizer (T+0 USDC atomic), not a generic "RWA floor."

*sources: Circle/USYC, Securitize/BUIDL, Superstate/USTB (+Fortune Invesco), Ondo OUSG/USDY docs, Franklin FOBXX, WisdomTree WTGXX — accessed 2026-07-02. AUM/APY partly secondary (Eco/CCN) → reconcile vs RWA.xyz before sizing. + underwriting_rubric.md.*
