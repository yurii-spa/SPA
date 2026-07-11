# SPA / earn-defi — one-pager for a crypto/fintech lawyer

*Hand this to counsel to make the first call productive. Jurisdiction-agnostic — the lawyer answers the
numbered questions for the relevant jurisdiction(s). Everything below is factual as-built; no marketing.*

---

## What it is (one line)
A **non-custodial** DeFi **risk + yield decision-support** product: we analyze a user's on-chain wallet,
show risk with the downside always stated, and give recommendations **the user executes themselves**.
We are software/advisory — **not** a custodian and **not** a manager of pooled funds.

## The load-bearing legal fact: NON-CUSTODIAL, human-in-the-loop
- We **never hold user funds, private keys, or seed phrases.** Wallet connection is read-only (a signed
  login message proves address ownership — no signing authority granted).
- **The user signs and sends every transaction in their own wallet.** Our software only *prepares* a
  transaction (e.g. "revoke this risky token approval"); it **never signs or moves funds**. No AI signing.
- We collect **no PII to use the product** — the wallet address is the account (no email/name required).

## What is built + live today
1. **Free DeFi Checkup** (`checkup.earn-defi.com`) — a wallet risk diagnostic (approvals, concentration,
   leverage, exit liquidity). The funnel / hook. No payment, no account.
2. **Paid Signals Cabinet** — wallet-login (Sign-In-With-Ethereum), the user's own risk analysis +
   de-risking recommendations (e.g. one-click revoke) the user signs themselves. **Non-custodial.**
3. **Personal execution track (owner's OWN capital, not clients')** — a separate, isolated path where
   transactions are proposed to a **Gnosis Safe multisig** and a human co-signs (never a bot with a key).

## Revenue model
**Freemium + crypto-subscription:** free checkup; premium cabinet features behind a small **USDC/month**
subscription **paid on-chain by the user to our address** (we read the chain to confirm; we never custody
the payment). No performance fee, no AUM fee, no pooled capital today.

## Track record posture (evidence)
- **Paper-trading only** (virtual $100,000), not client money: **20 of 30 evidenced days** (anchor
  2026-06-22, target ~2026-07-21). Equity $100,150.66 → $100,379.50.
- Every performance number is **reproducible/auditable** by an independent party (a standalone
  `verify_spa.py` re-derives the track + decision log; hash-chained). We never present paper as realized;
  the tail/drawdown is always shown alongside any yield.

---

## Questions for you (the point of this doc)
1. **Regulatory class:** In [jurisdiction], is *non-custodial DeFi recommendation-for-a-fee* (user
   self-executes) a regulated activity? Investment advice? Financial-promotion? Or unregulated software?
2. **Entity + first paying client:** What legal entity + terms + disclaimers do I need to take a **first
   paying non-custodial customer** for the signals cabinet?
3. **Where's the line:** Does giving specific "recommended actions for your wallet" (which the user
   executes) cross into regulated investment advice vs. general information? How do I stay on the safe side?
4. **Disclaimers:** What exact disclaimers must appear on the site + inside the cabinet (not advice,
   own-risk, non-custodial, no guarantee, DYOR)?
5. **External capital later:** When/if I manage or pool **client** capital (not just recommend), what
   changes — custody rules, fund structure, licensing? What's the cleanest structure to grow into?
6. **My own execution:** I intend to run a small **live test with MY OWN capital** via a Gnosis Safe
   multisig (I co-sign). Any issue treating that purely as my own trading before any client money?
7. **Marketing constraints:** Any limits on how I present the paper track / a future audited track to
   prospects (e.g. "audited 30-day track") without triggering a prospectus/solicitation rule?

## Honest guardrails already in place (so counsel sees the risk posture)
- No fabricated APY/addresses (evidence-tagged); paper never shown as live; the tail is always shown.
- Non-custodial + human-in-the-loop is a hard design invariant, not a marketing claim.
- Accepting external capital is treated as **legal-gated** — nothing pooled or managed for others yet.

*Companion internal docs if counsel wants depth: `docs/LEGAL_STRUCTURE_v1.md`, `docs/COMPLIANCE_POLICY.md`,
`docs/22_compliance_surface.md`, `docs/20_human_in_the_loop_governance.md`. Reproducibility: `scripts/verify_spa.py` + `docs/DD_PACK.md`.*
