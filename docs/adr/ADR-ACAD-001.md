# ADR-ACAD-001: Academy Accounts & On-chain Verified Learning

**Status:** Proposed (pending merge of `feature/academy-course` → `main`)
**Date:** 2026-07-04
**Scope:** `spa_core/academy/**`, `landing/src/**/academy/**`, `data/academy.db`

## Context

SPA needs a hands-on onboarding path that takes a non-technical person from "no
wallet" to a self-custodial user who has actually supplied and withdrawn from a
real lending protocol on Base — safely, within a strict learning limit, and with
**proof**. Course "completion" for existing crypto MOOCs is a self-reported
checkbox: click *Next*, get a certificate. That is worthless as evidence and
teaches nothing about the one thing that matters on-chain — that a claim is only
real if the chain confirms it.

The Academy: Real-Money Onboarding contour makes completion mean *"the block that
mined your transaction is strictly newer than the moment you started the lesson"*.
It is a small, invite-gated, **non-custodial** FastAPI sub-application mounted at
`/academy`, isolated from the public :8765 API (its own CORS, its own credentialed
cookie flow), backed by its own SQLite database (`data/academy.db`).

Nine modules (M0–M8) walk the learner from a risk-free testnet transaction to a
full supply→monitor→withdraw capstone; each module's practice is graded by a
deterministic, read-only on-chain verifier.

## Invariants (do NOT weaken)

1. **The server never stores private keys or seed phrases.** Non-custodial by
   construction. A `SeedPhraseGuard` ASGI middleware rejects (HTTP 400) any
   request body that looks like a raw 32-byte key or a BIP39 mnemonic, and the
   offending content is NEVER logged. Sign-in is by signature (SIWE), never by
   key upload. This is the same principle as SPA's own runtime: signing and fund
   movement are forbidden in read-only code.
2. **Progress is server-derived, not self-reported.** A lesson advances to
   `verified` only through the verify router calling an on-chain verifier — never
   by a client asserting completion.
3. **Completion = blockchain proof, not a checkbox.** Every real-money module is
   gated by a confirmed on-chain event (tx receipt, Aave `Supply`/`Withdraw`
   logs, USDC `Transfer`/`Approval` logs) read directly from the chain.
4. **The `events` table is append-only.** `BEFORE UPDATE`/`BEFORE DELETE`
   triggers `RAISE(ABORT, 'events is append-only')`. It is the audit log AND the
   substrate for the certificate hash-chain (below).
5. **A tx counts only if `block.timestamp > started_at`.** This defeats replaying
   an old, pre-course transaction as fresh proof. `used_tx_hashes` (PK
   `tx_hash+chain`) additionally blocks cross-user / cross-lesson replay.
6. **Verifiers fail-CLOSED.** Any RPC outage → `unavailable`, never a silent
   pass. Read-only RPC only; no state-changing calls, no keys.
7. **LLM is forbidden** in every academy module (auth, verifiers, middleware,
   routes) — deterministic code only, matching the repo-wide invariant.
8. **Learning limit ≤ $150.** Every real-money module's copy states it; amounts
   over the cap are *advisory-flagged*, never silently rejected, so a learner is
   warned but never loses a legitimately-completed lesson.

## Schema (brief — authoritative: `spa_core/academy/migrations/0001_initial.sql`)

| Table | Purpose |
|---|---|
| `users` | email + argon2id `password_hash` + `is_owner`; invite-gated |
| `invite_codes` | single/multi-use registration gate |
| `sessions` | opaque session id + per-session CSRF token, TTL, revocation |
| `progress` | per-(user,lesson) status + `evidence_json` (verified proof) |
| `wallets` | SIWE-bound addresses; partial unique index on verified (addr,chain) |
| `siwe_nonces` | single-use, 10-min TTL nonces |
| `quiz_results` | every attempt (score, answers, attempt_n) |
| `notes` | per-(user,lesson) free-text reflection |
| `events` | **append-only** audit log + certificate anchor chain |
| `used_tx_hashes` | replay guard (PK tx_hash+chain) |

## Endpoints

Auth / progress / practice (stages 2–7):
`POST /auth/register|login|logout`, `GET /auth/me`, `GET|POST /progress`,
`GET|PUT /notes/{id}`, `GET|POST /quiz/{id}`, `POST /wallet/siwe/nonce|verify`,
`GET /wallet`, `POST /verify/{lesson_id}`.

Stage 9 (this ADR):

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/export` | user | Full personal-data takeout (own data only), 5/hr |
| GET | `/admin/users` | owner | All users, without `password_hash` |
| GET | `/admin/progress` | owner | All progress rows + user email |
| GET | `/admin/events?since=&limit=` | owner | Recent audit events (limit ≤ 1000) |
| GET | `/certificate` | user | Certificate (404 until all 9 verified) |
| POST | `/certificate/publish` | user + CSRF | Publish + hash + anchor (idempotent) |
| GET | `/certificate/public/{token}` | **none** | Published snapshot (shareable) |

### Certificate & hash-chain anchoring

A certificate exists only when all 9 modules are `verified`. It is **private by
default** (owner-only via `GET /certificate`). Publishing:

1. mints `public_token = secrets.token_urlsafe(24)`;
2. freezes a **deterministic** snapshot of the certificate content (sorted keys,
   compact separators — no wall-clock, no random token in the hashed body);
3. computes `cert_hash = sha256(canonical_json)`;
4. appends a `cert_published` event carrying `{public_token, cert_hash,
   cert_data_snapshot}` — the frozen snapshot the public view serves;
5. appends a `cert_anchor` event `{cert_hash, prev_hash, anchored_at}`, where
   `prev_hash` is the previous anchor's `cert_hash` (or `"genesis"`).

Because `events` is append-only at the DB layer, the `cert_anchor` rows form a
tamper-evident chain **inside the academy's own boundary** — no cross-domain
write into the main SPA audit trail is needed. This mirrors SPA's existing
proof-chain pattern (`spa_core/tournament/tournament_proof_chain.py`). The chain
ships in every daily backup because `academy.db` is now captured by
`scripts/daily_backup.py`. Publishing is **idempotent**: a second publish returns
the same token/hash and writes no second snapshot.

## Multi-user plan

The contour is already multi-user: `users` is a real table, every query is scoped
by `user_id`, and admin endpoints return the cross-user picture. Onboarding a
second learner needs **no code change** — only `gen-invite`. Scaling further:

- **Invite codes** already gate registration (single or multi-use).
- **Sharding by `user_id`** is the natural horizontal split if the single-file
  SQLite ever becomes a bottleneck (it will not at course scale).
- Per-user rate-limit buckets (login/register/verify/quiz/export) already key on
  `user_id`, so isolation between learners holds under load.

## Security

- **Passwords:** argon2id (`argon2-cffi`), constant-time authentication (dummy
  verify on unknown email), transparent re-hash on parameter upgrade.
- **CSRF:** double-submit — every mutating request must echo the per-session
  `X-CSRF-Token`; constant-time compare.
- **Rate limiting:** deterministic token buckets — login 5/15min (per-IP AND
  per-email), register 5/15min, verify 10/hr, quiz 20/hr, export 5/hr, default
  60/min. A trip → 429 + `Retry-After` + a `lockout` audit event.
- **SIWE:** strict EIP-4361 domain/chain/nonce/freshness validation; single-use
  nonces with a 10-min TTL; a verified (address, chain) is globally unique (no
  silent wallet hijack).
- **Seed-phrase guard:** middleware tripwire (above), with a legitimate top-level
  `tx_hash` / `signature` field explicitly exempted.
- **Isolation:** the academy is a separate FastAPI app with its own CORS and
  credentialed cookies, mounted under a `try/except` so a broken/absent
  `academy.db` degrades gracefully and never takes down the public API.

## Consequences

- One new SQLite file (`data/academy.db`), now in the daily backup set (optional
  member — absent-host safe, never a MUST_HAVE fail-close).
- One new runtime dependency for the academy path: `argon2-cffi` (auth) and
  `eth-account`/`eth-utils` (SIWE recovery). The main runtime stays stdlib-only;
  these load only inside the academy sub-app.
- The public certificate URL (`/academy/onboarding/certificate/{token}`) is a
  new public, unauthenticated surface — it serves only the frozen, non-sensitive
  snapshot (email + module titles + tx evidence + gas estimate), never secrets.
