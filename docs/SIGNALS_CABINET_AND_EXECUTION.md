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
- **P1 · Web3 auth (SIWE / EIP-4361).** ✅ **COMPLETE end-to-end** (checkup P1a `181ca5c` + P1b-backend `79c1216` + P1b-frontend `e3c4569`). 22 tests, vitest 323 green, build compiled. Wallet = account, non-custodial, no PII.
  - P1a — ✅ **DONE** (checkup `181ca5c`): `apps/web/src/lib/siwe.ts` — nonce + canonical EIP-4361 message + fail-closed `verifySiwe` (viem `verifyMessage`). +7 unit tests (round-trip accept / impersonation reject / nonce-replay reject / malformed fail-closed). Full vitest 303 green, build exit 0.
  - P1b-backend — ✅ **DONE** (checkup `79c1216`): `/api/auth/nonce` (issue signed nonce cookie) + `/api/auth/verify` (verify wallet sig + nonce → HMAC session cookie); `siweSession.ts` (stateless, mirrors waitlistTokens HMAC; SIWE_SESSION_SECRET→WALLET_REF_SALT→dev). +12 tests (session tamper/expiry, full flow, impersonation/no-cookie/bad-body). Vitest 318 green, build exit 0.
  - P1b-frontend — NEXT: "Connect wallet + Sign in" button (injected provider / viem `personal_sign`): GET nonce → build message → sign → POST verify → logged in. *(browser UI — can't fully unit-test here)*
  - ⚠️ **OWNER-GATED secret:** set `SIWE_SESSION_SECRET` (or reuse `WALLET_REF_SALT`) in prod env before real logins — dev fallback is only safe pre-launch.
- **P2 · Cabinet view.** `[IN PROGRESS]`
  - P2a — ✅ **DONE** (checkup `59cc7cb`): gated `/cabinet` page. `sessionServer.ts` (getSessionAddress + pure fail-closed addressFromCookieHeader). Signed-out → WalletLogin gate; signed-in → cabinet shell (connected wallet + "run my checkup"). +4 tests, vitest 329 green, build compiled, route registered.
  - P2b — ✅ **DONE** (checkup `bc32ac5`): the wallet's FULL checkup analysis now renders behind the gate — `/cabinet` runs the same proven `analyzeWallet` pipeline as `/check` (cache→analyze→saveReport→CheckReport) for the SESSION address (no typed input), under Suspense + AnalyzeError→ErrorState. Signed-in users see their live positions + risk + tail. Build compiled, vitest 329 green.
  - P2c — ✅ **DONE** (checkup `08ff469`): recommended-actions layer + one-click NON-CUSTODIAL revoke. `CabinetActions` surfaces the wallet's own risky approvals (unlimited + unlabeled-spender) with the tail per row + a refusal note (de-risking only, never acquire/chase-yield). `RevokeApprovalButton` builds `approve(spender,0)` (`revokeTx.ts`, +3 tests) → user signs in their OWN wallet via raw `eth_sendTransaction`. We never sign/hold a key/move funds. Full vitest 335 green.
  - **P2 cabinet is functionally complete: login → analysis → de-risk actions the user executes themselves.** Later polish: reduce-concentration/leverage prepare-tx, per-action evidence links.
  - P2-polish — ✅ **DONE** (checkup `fa1305c` sign-out + `ee02118` nav link): `/api/auth/logout` + SignOutButton (clears session); `/cabinet` added to the site nav (bilingual, discoverable site-wide). Vitest 338 green.
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
