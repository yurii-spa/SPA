# Signals Cabinet + Web3 Auth + Execution A/B — initiative charter & backlog

**Owner-greenlit 2026-07-11.** Two linked product tracks, both **non-custodial, human-in-the-loop, AI-never-signs**:

1. **Signals cabinet** — deliver evidence-tagged recommendations to a user on THEIR own wallet (read-only), extend DeFi Checkup into a logged-in cabinet. User keeps funds, signs their own execution. We are the recommendation + proof layer, never the executor.
2. **Execution A/B (owner's OWN assets, live test)** — an isolated component that PREPARES transactions; a human (or a Safe 2-of-2) signs. NEVER a hot-wallet auto-key agent (level C rejected).

---

## Hard invariants (non-negotiable, superset of the global list)
- **Non-custodial always.** We never hold private keys / seed phrases. Wallet connection is **read-only** (address / SIWE signature), never signing authority.
- **AI never signs / never moves funds.** Execution = AI *prepares* an unsigned draft; a HUMAN signs (level A) or a **Safe 2-of-2** co-signs (level B). Level C (agent holds key, auto-moves) is REJECTED.
- **No PII required.** Web3 (SIWE) auth = the wallet address IS the account; no email/password/name. Optional opt-in alerts only.
- **Every recommendation is evidence-tagged (L0–L6) + shows the tail + carries the refusal log.** Never sell risk as safety.
- **Execution code stays isolated in `spa_core/execution/`** — never imported by advisory/paper/monitoring. RiskPolicy v1.0 untouched.

## Monetization (owner-preferred: freemium + crypto-subscription)
- **Free:** the DeFi Checkup diagnosis (the funnel / hook).
- **Paid (USDC/month paid FROM the user's wallet, non-custodial):** the signals cabinet — premium recommendations, alerts, multi-wallet, refusal log. Payment is on-chain to a receive address; we never custody it.
- Alternatives kept on file: NFT/pass token-gate; performance/AUM fee (custody-world, later).

---

## Phased backlog

### Track 1 — Signals Cabinet (repo: DeFi Checkup, Next.js)
- **P1 · Web3 auth (SIWE / EIP-4361).** `[P1a DONE]`
  - P1a — ✅ **DONE** (checkup `181ca5c`): `apps/web/src/lib/siwe.ts` — nonce + canonical EIP-4361 message + fail-closed `verifySiwe` (viem `verifyMessage`). +7 unit tests (round-trip accept / impersonation reject / nonce-replay reject / malformed fail-closed). Full vitest 303 green, build exit 0.
  - P1b — NEXT: API routes (`/api/auth/nonce` issue+store, `/api/auth/verify` → session cookie) + "Connect wallet + Sign in" button. Wallet address = account.
- **P2 · Cabinet view.** Logged-in wallet (read-only) → its positions (reuse checkup analyze) → "Recommended actions for YOUR wallet" (evidence + tail) + refusal log → "prepare transaction" opens the user's OWN wallet to sign. We never sign.
- **P3 · Paywall / monetization.** Crypto-subscription (USDC/mo) or token-gate over the cabinet (owner confirms model before build).
- **P4 · Alerts (optional, non-custodial).** XMTP / Push Protocol (wallet-native) or opt-in email; "new signal, log in to review" — the signal + signing stay in the cabinet.

### Track 2 — Execution A/B (repo: SPA, `spa_core/execution/`, ISOLATED)
- **E1 · Unsigned draft-transaction builder.** Given a recommendation, assemble the exact on-chain calldata as an UNSIGNED draft (level A). Never signs. Owner reviews + signs in their own wallet.
- **E2 · Safe 2-of-2 flow (level B).** Draft → proposed to a Gnosis Safe (ADR-010) where the owner co-signs; nothing executes on one signature.
- **E3 · Hard caps + kill-switch on the live-test wallet.** Tiny capital, per-tx cap, daily cap, kill-switch, only after 30-day track. Level C (auto hot-wallet) permanently REJECTED.

## Verify gates (per repo)
- Checkup: `(cd apps/web && npx vitest run)` + `npm run build -w @spa/web` — both exit 0 before push.
- SPA: `pytest` green.

## Status log
- 2026-07-11: charter recorded; **Track-1 P1a (SIWE verify backend + tests) started.**
