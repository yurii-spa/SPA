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
- **P3 · Paywall / monetization.** Model CONFIRMED by owner (2026-07-11): **freemium + USDC/mo crypto-subscription**, non-custodial (user pays on-chain to our receive address; we read the chain, never custody).
  - P3a — ✅ **DONE** (checkup `683dc05`): `subscription.ts` (pure state machine over on-chain payments, fail-closed on underpay/wrong-recipient/wrong-wallet/non-USDC) + `subscriptionConfig.ts` (env; price/period defaults). +12 tests, vitest 353 green.
  - P3b — ✅ **DONE** (checkup `c308c5a`): payment mechanism + gate. `paymentTx.buildUsdcPaymentTx` (USDC transfer to receiveAddress, canonical USDC per chain, +4 tests) → `SubscribeButton` (user signs in own wallet). `getWalletSubscription` fail-closed resolver (+3 tests) with an INJECTABLE payment reader. `PremiumGate` wired into `/cabinet` (premium ↔ subscribe ↔ "coming soon" while unconfigured). vitest 364 green.
  - P3b-read — ✅ **DONE** (checkup `543dbde`): `alchemyPaymentReader` (alchemy_getAssetTransfers wallet→receiveAddress, USDC) wired into the cabinet's `getWalletSubscription`. +6 tests, fail-closed (no key / bad chain / RPC error → locked). vitest 370 green.
  - **P3 subscription is FUNCTIONALLY COMPLETE end-to-end** (pay → read on-chain → unlock premium). Goes live the moment the owner sets `SUBSCRIPTION_RECEIVE_ADDRESS` (ALCHEMY_API_KEY already present). Until then: honest "coming soon".
  - ⚠️ **OWNER-GATED:** set `SUBSCRIPTION_RECEIVE_ADDRESS` (a real address you control) in prod env — the feature is OFF (fail-closed) until then; we never fabricate a payment target.
- **P4 · Alerts (optional, non-custodial).** XMTP / Push Protocol (wallet-native) or opt-in email; "new signal, log in to review" — the signal + signing stay in the cabinet.

### Track 2 — Execution A/B (repo: SPA, `spa_core/execution/`, ISOLATED)
**INVENTORY (2026-07-11): the infra LARGELY EXISTS — do not rebuild; the real remaining work is owner-setup, not code.**
- `execution/safe_tx_builder.py` — builds Gnosis Safe **2-of-3** proposals (ADR-022/010); `is_paper_mode()` when `SPA_EXECUTION_MODE != 'live'`. **This is level B.**
- `execution/arming.py` — `SPA_EXEC_ARMED` = THE owner-gated cutover switch; default **OFF**, guards `_sign_and_send`. Nothing signs/sends unless the owner arms it.
- `execution/eth_signer.py` + `wallet.py` — capital primitives (sign/send, Safe SDK). `router.py` + adapters (aave/compound/yearn/morpho) — the venues.

- **E1 · Unsigned draft (level A).** ✅ **BUILT 2026-07-11** (owner explicit go-ahead) — `spa_core/execution/draft_prep.py` `prepare_draft(recommendation: dict) → DraftReview`: takes a de-risking recommendation as **plain DATA** (advisory→execution boundary crossed as a dict/JSON, NOT a code import → isolation preserved) and returns an **UNSIGNED, human-reviewable draft** (exact `approve(spender,0)` calldata for `revoke_approval` via a self-contained stdlib encoder; review-only draft for reduce/withdraw/exit — never fabricated calldata). **Hard contract, 33 tests:** never signs/sends (`signed=False`, `requires_human_signature=True` always), **de-risk-ONLY** (exposure-increasing kinds refused), no-fabrication (bad/missing address → fail-closed refusal), evidence L0–L6 + tail mandatory, imports NO capital primitive (`eth_signer`/`wallet`/`mev_protection` never loaded — verified), reads `SPA_EXEC_ARMED` read-only for posture display. CLI: `scripts/prepare_execution_draft.py` (JSON in → draft out, exit 2 on refusal). Full suite 1403 passed.
  - **E1 loop CLOSED 2026-07-11** (`d0e20041`): `recommendations_from_checkup_approvals()` turns REAL checkup output (`{unlimited, to_unknown}` approval findings) into `revoke_approval` recommendations → `prepare_draft` → unsigned draft. CLI `--from-checkup <report.json>` emits a draft per finding. This is the owner-requested flow: checkup finds risky approvals → user signs the revoke in their OWN wallet. Pure data transform (no cross-import), fail-closed, de-risk-only, +7 tests (end-to-end).
  - Still owner-setup-gated for anything BEYOND a draft: level-B Safe co-sign (`safe_tx_builder`, exists) + `SPA_EXEC_ARMED` (OFF) + funded wallet. E1 itself moves nothing and needs no arming — it only prepares.
- **E2 · Safe 2-of-N (level B).** ✅ **covered by `safe_tx_builder` (2-of-3)**. Needs: owner deploys the Safe (ADR-010) + co-signer set.
- **E3 · Caps + kill-switch.** Partly present (`rate_limiter.py`, kill-switch in governance). Needs owner config: tiny capital, per-tx/daily cap, only after 30-day track. **Level C (auto hot-wallet key) permanently REJECTED.**

**⚠️ E1/E2 are OWNER-SETUP-gated, not code-gated:** (1) deploy a Gnosis Safe + choose co-signers (ADR-010); (2) set `SPA_EXECUTION_MODE=live` + arm `SPA_EXEC_ARMED` only when ready; (3) fund the live-test wallet tiny. Until then everything is paper/OFF by design. The code path (build draft → owner signs via Safe) already exists; I will only add the thin per-recommendation draft wrapper WITH your explicit go-ahead (it touches the isolated execution/ layer).

## Verify gates (per repo)
- Checkup: `(cd apps/web && npx vitest run)` + `npm run build -w @spa/web` — both exit 0 before push.
- SPA: `pytest` green.

## Owner env-setup runbook (the OWNER-GATED switches — you run these, never me)
*These are the only things standing between "built" and "on". Secrets are generated BY YOU and pasted
ONLY into Railway's env — never into any file, chat, or the repo (secrets policy).*

### 1. `SIWE_SESSION_SECRET` — ✅ DONE by owner 2026-07-11 (prod now runs a real secret, not the dev fixture). Also HARDENED: `siweSession.ts` now fail-closes in production — if the var is ever unset/typo'd in a future deploy it uses a per-process random fallback, NEVER the publicly-known `DEV_SECRET` (which would let anyone forge a session). Steps kept below for future rotation.
### 1. `SIWE_SESSION_SECRET` — signs cabinet login sessions (do this before real logins)
The cabinet already accepts wallet logins; sessions are HMAC-signed. Until you set a dedicated secret it
falls back to `WALLET_REF_SALT`, then a dev fixture (`siweSession.ts` — resolution order, fail-closed).
Set a strong dedicated one:
1. **Generate a 256-bit secret on your Mac** (run it yourself; do NOT paste the output anywhere but Railway):
   ```bash
   openssl rand -hex 32      # → 64 hex chars, e.g. 3f9a...  (unique, keep private)
   ```
2. **Railway → your `defi-checkup` service → Variables → New Variable:**
   - Name: `SIWE_SESSION_SECRET`
   - Value: the 64-char hex from step 1
   (CLI alternative: `railway variables set SIWE_SESSION_SECRET=<hex>` in the checkup repo.)
3. **Redeploy** — Railway auto-redeploys on a variable change; if not, hit **Deploy**.
4. **Verify:** open `checkup.earn-defi.com/cabinet`, connect wallet, sign in → you land in the cabinet.
   (The secret is server-side; you confirm by a working login, not by reading it back.)
- **Note:** setting/rotating this invalidates any existing sessions → users just re-login. With ~no live
  users yet, zero impact. Rotate the same way anytime.

### 2. `SUBSCRIPTION_RECEIVE_ADDRESS` — turns ON the USDC subscription (deferred by owner — clients far off)
The whole pay→read-on-chain→unlock path is built + fail-closed OFF until this is set (`subscriptionConfig.ts`).
When you want to accept the first paying user: Railway → Variables → `SUBSCRIPTION_RECEIVE_ADDRESS` = a real
address YOU control (the one users pay USDC to). `ALCHEMY_API_KEY` is already present (reads the chain).
Until set: cabinet honestly shows "coming soon", never a fabricated payment target. **Owner deferred 2026-07-11.**

### 3. `ETHERSCAN_API_KEY` — enables the approvals scan for whale wallets (owner-gated, see memory)
Free key from etherscan.io/apis → Railway → Variables on the **correct** checkup service+env → redeploy.
Alchemy `eth_getLogs` fallback already covers light retail wallets; the key gives full-history one-call indexing.

## Status log
- 2026-07-11: charter recorded; **Track-1 P1a (SIWE verify backend + tests) started.**
- 2026-07-11: **Owner env-setup runbook added** (SIWE_SESSION_SECRET / SUBSCRIPTION_RECEIVE_ADDRESS /
  ETHERSCAN_API_KEY step-by-step); owner **deferred** the subscription receive-address (clients far off),
  requested the SIWE_SESSION_SECRET how-to. Lawyer one-pager shipped as **PDF** (`docs/LAWYER_ONE_PAGER.pdf`).
