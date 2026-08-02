# RFC-054 — Implementation Plan (Kill-Switch Authority)

> **⛔ NON-EXECUTABLE DRAFT.** Design and planning only. This document implements nothing: no production code, no runtime or kill-switch state, no thresholds, no RiskPolicy, no execution gate, no money-path, no config, no launchd, no backup action, no commit / push / merge. The only next executable task is a **read-only preflight** (`PREFLIGHT-RFC054-006A`, §16); every implementation task (T1…T11) is a separate, individually-authorized step (§13). All future code work must obey CLAUDE.md §Инварианты #1–#5 and `.claude/rules/risk-engine.md`.

## 1. Status and design summary

- **ADR-054:** ACCEPTED (owner decision 2026-07-20; D-01…D-07 = option 1). Not reopened here.
- **Design source:** `docs/rfcs/RFC-054-kill-switch-authority.md` (§CLOSURE-005A…005D) + `docs/decisions/ADR-054-kill-switch-authority.md`.
- **Design (one paragraph).** Four latch files `data/kill_switch/{manual_pause,risk_kill,threat_kill,execution_kill}.json` (Model B), each single-owner and single-writer. `effective_halt = OR(normalized latches)` is computed by ONE Investment-Engine reducer; `data/kill_switch_effective.json` is a derived cache with Authority NONE. One global lock `data/kill_switch/.state.lock` (readers SHARED, writers EXCLUSIVE) makes fractured reads impossible. Every mutation is a durable cross-file transaction with a write-ahead marker `data/kill_switch/transaction.json` and a dedicated serialized hash-chained audit `data/kill_switch/kill_switch_events.jsonl`; the transaction **marker COMMITTED is written LAST**. Any missing / corrupt / pending / mismatched state ⇒ HALTED (fail-CLOSED). Product Studio (Telegram) may set/clear only `manual_pause`; engine latches are cleared only by Investment-Engine governance (`threat_kill`/`execution_kill` via request→approve; `risk_kill` auto-clears deterministically).
- **Never changed by this work:** kill thresholds and drawdown ladder (ADR-034/048), RiskPolicy v1.0, execution arming gates, money-path; no LLM in the kill path; stdlib-only; atomic writes.

## 2. Mandatory read-only preflight

No implementation begins until `PREFLIGHT-RFC054-006A` (§16) returns its report and the Architecture Review Board reviews it. Components to pre-verify (read-only):

| # | Component | Why verify first |
|---|---|---|
| 1 | `spa_core/governance/kill_switch.py` (`activate/deactivate`, `check_manual_trigger`, `run_kill_switch_check`, `check_drawdown_trigger`, re-arm/tier) | writers/readers + trigger order; **exact risk re-arm parameters (§8)** |
| 2 | `spa_core/monitoring/threat_reactor.py` | 2nd writer → must become SET-only |
| 3 | `spa_core/telegram/bot.py` + `router.py` | PS writer → scope to `manual_pause`; **U-17 identity model (§7)** |
| 4 | **every** reader of `data/kill_switch_active.json` (exhaustive grep) | all must move to the reducer (reader-fan-out risk) |
| 5 | `spa_core/execution/readiness_audit.py` + execution arming gates + env flags + live adapters + launchd + process list | `execution_kill` source AND **real-execution isolation (§9)** |
| 6 | `spa_core/audit/{hash_chain,audit_trail_signer}.py` | reuse hash primitives; do NOT write kill events into the shared multi-writer chain (F-CON-1) |
| 7 | `spa_core/utils/atomic.py` (`atomic_save`) + flock semantics across launchd processes | atomic write + lock compatibility |
| 8 | backup scripts (`scripts/daily_backup.py`, `spa_core/persistence/backup.py`, `spa_core/backtesting/tier1/dr_backup.py`) + whether a backup architecture is already ACCEPTED | latch/marker/audit coverage; decide T9A vs T9B (§10) |
| 9 | `scripts/kill_switch_drill.py` + `scripts/verify_spa.py` | per-latch drills + `verify_kill_audit` |
| 10 | `.gitignore` | git-tracking decision for latch/marker/audit files |
| 11 | CI: `llm_forbidden_lint`, `stdlib_contract_guard`, `migrate_callsites` | new modules must pass |

**Verification gate:** no edit until the preflight returns the full writer/reader/authority maps + the real-execution isolation evidence + the exact re-arm parameters, and the ARB signs off.

## 3. Candidate files (confirm in preflight)

**New:** `governance/kill_switch_latches.py` (**Latch Schema v1 — ADR-054 D-08 / RFC §6** + per-latch single-writer API), `kill_switch_reducer.py` (`compute_effective_halt`), `kill_switch_txn.py` (global lock + transaction marker + commit protocol), `kill_switch_audit.py` (serialized hash-chained events + verify + non-destructive recovery), `kill_switch_idempotency.py` (idempotency index, §5), `kill_switch_recovery.py`, `scripts/migrate_kill_switch_latches.py`, tests `spa_core/tests/test_kill_switch_*`.

**Modify:** `governance/kill_switch.py`, `monitoring/threat_reactor.py`, `telegram/bot.py` + `router.py`, `paper_trading/cycle_runner.py` + monitors + live API (read via reducer), `execution/readiness_audit.py`, backup scripts, `scripts/{verify_spa,kill_switch_drill}.py`, `.gitignore`.

**Never touch:** RiskPolicy thresholds, drawdown ladder constants (ADR-034/048), `spa_core/execution/` arming gates, money-path.

## 4. Normalized reducer model

`compute_effective_halt` is a **pure function**. Before it runs, an I/O layer maps each latch's filesystem state to exactly one normalized input:

```
VALID_ACTIVE · VALID_INACTIVE · MISSING · CORRUPT · UNKNOWN_SCHEMA · PENDING_TRANSACTION · RECOVERY_REQUIRED
```

The pure reducer treats **only `VALID_INACTIVE` as a non-halting latch**; every other normalized input (`VALID_ACTIVE`, `MISSING`, `CORRUPT`, `UNKNOWN_SCHEMA`, `PENDING_TRANSACTION`, `RECOVERY_REQUIRED`) makes that latch effective-ACTIVE. `effective_halt = OR(per-latch effective-ACTIVE)`. All I/O ambiguity is resolved in the input layer, so the fail-CLOSED behaviour is unit-testable as a pure function with no I/O.

**Read-result → normalized-state mapping (ADR-054 D-08 §7):** valid Schema v1 `active=true` ⇒ `VALID_ACTIVE`; valid `active=false` ⇒ `VALID_INACTIVE`; file absent ⇒ `MISSING`; invalid JSON / unreadable ⇒ `CORRUPT`; missing/extra field, unsupported `schema_version`, filename↔`latch_id` mismatch, invalid field type/value ⇒ `UNKNOWN_SCHEMA`; pending transaction affecting the latch ⇒ `PENDING_TRANSACTION`; recovery flag / unresolved durable-state mismatch ⇒ `RECOVERY_REQUIRED`. Only `VALID_INACTIVE` contributes `false`.

## 5. Transaction and historical idempotency model

### 5.1 Current transaction vs immutable history

`data/kill_switch/transaction.json` holds **only the current transaction** and is not a complete history.

- `data/kill_switch/transactions/<transaction_id>.json` = **immutable archive of finally-completed transaction markers.**
- The previous `COMMITTED` marker must be **atomically archived and fsync-confirmed before a new transaction begins.**
- A new transaction **must not begin** if the previous committed marker is not archived or fails verification.
- Archived committed markers are **never modified or deleted by ordinary runtime code.**
- Retention or deletion of archived committed markers requires a **separate architecture and owner approval.**
- A single audit event `MUTATION_COMMITTED` is **not standalone proof of completion**, because it is written *before* the final `marker.status = COMMITTED`.

### 5.2 Commit ordering (fail-CLOSED)

Lock order per mutation: global `.state.lock` (EXCLUSIVE) → latch write → dedicated audit append. The write-ahead marker progresses `PREPARED → AUDIT_WRITTEN → STATE_WRITTEN → COMMITTED`, and **marker COMMITTED is written LAST** — only after the latch is durable AND both audit events (`MUTATION_PREPARED`, then `MUTATION_COMMITTED`) are fsync-durable. A pending SET ⇒ latch ACTIVE; a pending CLEAR ⇒ prior active still honored; an un-audited or partially-audited clear can never become authoritative.

### 5.3 Historical idempotency rule (completed-ID verification)

An old `correlation_id` is considered **completed** only when ALL of these hold:

- a current OR immutable-archived marker with `status = COMMITTED`;
- matching `transaction_id`;
- matching `correlation_id`;
- matching `latch_id`, `action`, and request-payload hash;
- a corresponding audit event;
- a valid audit entry hash AND hash-chain linkage;
- a consistent result hash between the marker and the audit event.

**Do NOT compare the historical `new_state_hash` against the current latch file** — that latch may have been legitimately changed by later transactions. The current latch hash is verified **only for the latest transaction that defines the latch's present state**.

### 5.4 Idempotency index (cache, not authority)

`data/kill_switch/idempotency_index.json` is a **cache only, never authority.** Minimal record:

```
correlation_id · transaction_id · latch_id · action · request_payload_hash ·
result_hash · committed_marker_path · audit_segment · audit_sequence · audit_entry_hash
```

**Lookup:** (1) find the record in the index; (2) open the referenced immutable committed marker; (3) open the specific audit event; (4) verify hashes and chain linkage; (5) return the stored result **only after** verification.

**Rules:**
- same ID + same payload ⇒ return the prior result **without re-mutating**;
- same ID + different payload ⇒ **reject + security audit**;
- corrupt index ⇒ **rebuild** from the committed-marker archive + audit;
- ambiguous marker / audit / index ⇒ **HALTED + RECOVERY_REQUIRED**;
- steady-state lookup must be **bounded**;
- a full scan is allowed **only for recovery/rebuild**.

## 6. Implementation tasks T1–T11

Each task is one PR behind its own authorization gate (§13); the kill-switch drill must be green before and after. Tasks are never run as a batch.

- **T1 (E1):** normalized-input boundary + `compute_effective_halt` pure reducer (§4). *AC:* pure-function unit tests; no I/O.
- **T2 (E1):** global state lock (SHARED/EXCLUSIVE) + per-latch single-writer API over the accepted **Latch Schema v1 (ADR-054 D-08, RFC §6)** — 7 mandatory fields, integer `schema_version=1`, monotonic `revision` (init `1`, `+1`/mutation, CAS), RFC3339 6-digit-`Z` timestamps, canonical `sort_keys`/`separators=(",",":")` serialization; durable atomic write (tmp + `fsync` + `os.replace` + dir-fsync). Missing production latch stays `MISSING ⇒ HALTED` (T2 does **not** auto-initialize; init is the owner-approved T10 migration); tests use `tmp_path` fixtures. **The earlier `T2_SCHEMA_BLOCKED` condition is RESOLVED by D-08 (2026-07-21).** *AC:* a reader never sees a partial write; unknown/extra/missing field ⇒ `UNKNOWN_SCHEMA`; stale expected-revision rejected.
- **T3 (E2):** transaction marker + commit protocol (marker COMMITTED last) + dedicated serialized audit + immutable committed-marker archive (§5), over the accepted **Transaction Marker & Audit Schema v1 (ADR-054 D-09, ACCEPTED WITH MODIFICATION 2026-07-22)** — 17-field marker (incl. owner-added `old_state_hash`), 20-field event, marker statuses {PREPARED, AUDIT_WRITTEN, STATE_WRITTEN, COMMITTED, ABORTED, RECOVERY_REQUIRED}, audit events {MUTATION_PREPARED, STATE_WRITTEN, MUTATION_COMMITTED, ABORTED, RECOVERY_REQUIRED} (`AUDIT_WRITTEN` marker-only), UUIDv4 ids (injectable), `sequence` = ordering authority, D-08 canonical rules; reuse ONLY `hash_chain.compute_entry_hash`/`verify_chain` logic (never `hash_chain.append()`/shared `audit_chain.jsonl`); T3 records attribution, T4 enforces it; retention deferred to **D-10** (no runtime deletion/compaction). **The T3 schema blocker is RESOLVED by D-09.** Audit corruption quarantine + recovery + segments follow **Audit Recovery & Segment Schema v1 (ADR-054 D-11, ACCEPTED WITH MODIFICATION 2026-07-22)** — auto RECOVERY_REQUIRED marking, authorized quarantine/segment/completion, 16-field recovery metadata, `kill_switch_events.corrupt.<TS>` naming, segments only from recovery, recovery metadata ≠ audit authority, reducer never reads recovery.json. **The T3.2b.2 schema blocker is RESOLVED by D-11.** *AC:* crash matrix (§11) passes; SUCCESS only after durable state + audit.
- **T4 (E2):** domain-scoped authorization (PS → `manual_pause` only; deny cross-domain clears → `UnauthorizedClearAttempt`). *AC:* simulated PS clear of `risk_kill` denied + audited.
- **T5 (E5):** committed-reader verification + derived `kill_switch_effective.json` (Authority NONE) + `/status`. *AC:* mismatch ⇒ RECOVERY_REQUIRED / HALTED.
- **T6 (E3) — BLOCKED by U-17 (§7):** Telegram `/pause`, `/resume` → `manual_pause`; `/ack`; `/request-risk-clear`. *AC:* `/resume` cannot clear an engine latch; U-17 resolved first.
- **T7 (governance) — BLOCKED by re-arm parameters (§8):** `risk_kill` deterministic auto-clear (D-03); `threat_kill`/`execution_kill` request→approve (D-07); `threat_reactor` SET-only. *AC:* thresholds + re-arm byte-identical; operator cannot clear.
- **T8 (E4):** dual-read + fail-safe OR (legacy boolean + all valid/new latches + pending transaction); legacy-write ban lint; divergence alarm. *AC:* legacy active=true ⇒ HALTED; an unknown source cannot be cleared by PS.
- **T9A (E6) — integration only (§10):** register the latch/marker/audit files with the sets defined by an already-ACCEPTED backup architecture; restore drill; non-destructive audit recovery. *AC:* restore drill green.
- **T9B — OUTSIDE this authorization (§10):** a new encrypted/offsite backup architecture is a **separate RFC/ADR + separate owner approval**; not part of the kill-switch implementation.
- **T10 (E7) — cutover requires SEPARATE owner approval:** migration runner (preflight → dual-read parity → cutover → fail-safe rollback → removal per §12). *AC:* parity gate; rollback per §12.
- **T11 (E8):** full safety proof — per-latch drills, unauthorized-clear denial, fractured-read, crash + rollback matrices, idempotency, reboot fail-CLOSED, no-threshold-change golden test. **T11 is evidence/proof, NOT permission to deploy.**

## 7. Telegram U-17 gate

T6 may not start until ONE of:

- **Option A — read-only evidence** proves the bot operates exclusively in a private DM and `chat_id` maps unambiguously to the owner (verified by `PREFLIGHT-RFC054-006A`; the `TELEGRAM_CHAT_ID_SPA` value is a secret — evidence concerns the chat *type*, not the value).
- **Option B — user-scoped authorization added to the plan:** allowlisted `from.id`; check `chat_id + from.id`; **deny by default**; unauthorized attempts audited (`UnauthorizedActor`); **secrets/IDs never hardcoded in the repo** (Keychain/env at runtime).

**Neither option is chosen without evidence (A) or an explicit owner decision (B).** Until resolved, T6 stays BLOCKED and the bot's current `/pause`/`/resume` behaviour is unchanged.

## 8. Risk re-arm gate

Preflight must find, from current code + tests: the current hysteresis, the re-arm band, the healthy-cycle count, the **owner** of these parameters, and the tests that pin existing behaviour.

- **If the parameters already exist:** preserve them **byte-identical**; no change without a separate ADR. T7 proceeds only after they are confirmed.
- **If they do NOT exist:** do **not** invent values — raise an **owner decision packet** for the re-arm parameters and keep **T7 BLOCKED** until the owner decides. D-03 accepts that `risk_kill` auto-clears; the concrete safe parameters remain a separate risk-domain decision.

## 9. Real-execution isolation gate

`PREFLIGHT-RFC054-006A` must gather evidence on execution arming gates (`SPA_EXEC_ARMED`, `SPA_EXECUTION_MODE`), environment flags, live execution adapters, launchd services, the current process list/config, and **every path that can submit or execute a real order**.

- Until this evidence exists, the plan may NOT claim "real operations are unaffected." The only permitted statement is: *"impact on real execution is not yet proven; implementation remains blocked."*
- Expectation (to be verified, not assumed): paper phase; execution triple-gated OFF (E-027); `execution_kill` is a new latch that must arm nothing. If preflight finds ANY reachable real-order path, implementation stays BLOCKED pending an owner decision.

## 10. Backup boundary T9A / T9B

- **T9A** (in scope) = **integration with an already-ACCEPTED backup architecture only.** May run ONLY if that architecture is confirmed and accepted for kill-state coverage; the kill-switch work merely registers the new files with the sets that architecture already defines.
- **T9B** (out of scope) = a **new encrypted/offsite backup architecture** ⇒ a separate RFC + ADR + separate owner approval.
- The kill-switch implementation **may NOT itself choose** a cloud/offsite provider, an encryption/key-management scheme, a retention policy, credentials, or any paid service.
- Until the backup gap (AUDIT-004 F-REC-1/2: no verified offsite, no encryption) is resolved, it remains an **explicit BLOCKER** on durable kill-state recovery OR an **owner-accepted temporary risk** recorded as such — never silently assumed away.

## 11. Tests, crash and rollback matrices

### 11.1 Crash / failure test matrix

| Injected fault | Expected outcome |
|---|---|
| crash after marker PREPARED, before latch write | pending ⇒ HALTED; SET ⇒ ACTIVE, CLEAR ⇒ prior active honored |
| crash after latch write, before `MUTATION_COMMITTED` audit | pending ⇒ HALTED; clear not authoritative |
| crash after `MUTATION_COMMITTED` audit, before marker COMMITTED | pending ⇒ HALTED (audit event alone is not completion) |
| crash after marker COMMITTED, before archive of previous marker | next transaction refuses to begin until archive verified |
| fractured read (concurrent mutation) | shared lock ⇒ reader sees a complete pre- or post-state; never a false `HALTED=false` |
| PS attempts to clear an engine latch | denied → `UnauthorizedClearAttempt` audited; latch unchanged |
| committed-reader verification mismatch (revision / hash / missing audit) | RECOVERY_REQUIRED / HALTED |
| duplicate correlation_id, same payload | prior result returned, no re-mutation |
| duplicate correlation_id, different payload | rejected + security audit |
| UNINITIALIZED vs runtime missing/corrupt latch | UNINITIALIZED ⇒ HALTED until owner-approved migration; runtime missing/corrupt ⇒ that latch ACTIVE + RECOVERY_REQUIRED |
| audit tail corruption | non-destructive quarantine + RECOVERY_REQUIRED (never auto-truncate) |
| reboot with any non-COMMITTED marker | HALTED + authorized recovery; recovery never auto-clears an engine latch |
| no-threshold-change golden test | kill thresholds / RiskPolicy / money-path byte-identical |

### 11.2 Rollback failure matrix

| Rollback scenario | Latch files | Legacy boolean | Effective halt | PS can clear engine latch? | Recovery |
|---|---|---|---|---|---|
| rollback with valid new latches present | kept, read-only | read-only | `legacy OR latches OR pending` | **NO** | normal reads; re-enable writers only via re-cutover (owner) |
| rollback mid-cutover (pending transaction) | present + pending marker | read | **HALTED** (pending) | **NO** | authorized finalize/abort of the pending transaction |
| rollback with a corrupt latch/marker | corrupt one ⇒ ACTIVE | read | **HALTED** | **NO** | quarantine + authorized recovery (§CLOSURE-005B) |
| attempted "delete latch files" rollback | **FORBIDDEN** | — | — | — | rejected; not a valid rollback |
| attempted "legacy-only shared clear path" rollback | **FORBIDDEN** | — | — | — | rejected; authority separation is invariant |

## 12. Migration and fail-safe rollback

**Migration:** preflight → read-only validation → **dual-read** (`effective_halt = legacy OR all valid/new latches OR pending transaction`, fail-safe OR) → legacy interpretation (legacy `active=true` ⇒ halt held as an `unknown_or_legacy` latch PS cannot clear; unknown-source `active=false` never auto-clears an engine latch) → **cutover (separate owner approval)** → fail-safe rollback (below) → **removal (separate owner approval after demonstrated parity)**.

**Fail-safe rollback — the ONLY permitted rollback model** is `effective_halt = legacy OR all valid/new latches OR pending transaction`, with these mandatory rules:

- created latch files are **always honored in the reduction (never dropped)** and **never deleted** during rollback;
- audit and transaction evidence are always preserved;
- Product Studio **never** gains the ability to clear an engine latch, in any rollback state;
- returning to the old shared clear-path is **forbidden**;
- missing / corrupt / ambiguous state ⇒ **HALTED**;
- rollback may **reduce the write surface** (writers stop mutating via the new API) but **never undoes authority separation** — it is not a re-opening of the PS→IE clear crossing.

(Rollback failure matrix: §11.2.)

## 13. Staged authorization and dependencies

**Staged authorization.** No prompt in this document authorizes running the implementation tasks as a batch. The only next executable task is the read-only `PREFLIGHT-RFC054-006A`; each implementation task is authorized separately with an ARB/owner gate between steps:

```
PREFLIGHT-RFC054-006A (READ-ONLY)  → ARB review
IMPLEMENT-RFC054-T1                → ARB review + acceptance
IMPLEMENT-RFC054-T2                → ARB review
IMPLEMENT-RFC054-T3                → ARB review   (incl. idempotency model §5)
IMPLEMENT-RFC054-T4 / T5           → ARB review
IMPLEMENT-RFC054-T6                → requires U-17 resolved (§7)
IMPLEMENT-RFC054-T7                → requires confirmed re-arm parameters or new owner decision (§8)
IMPLEMENT-RFC054-T8                → ARB review
IMPLEMENT-RFC054-T9A               → requires an accepted backup architecture (§10); T9B is a separate RFC/ADR
IMPLEMENT-RFC054-T10 (cutover)     → SEPARATE owner approval
Legacy removal                     → SEPARATE owner approval after demonstrated parity
IMPLEMENT-RFC054-T11               → evidence/proof only; NOT deployment permission
```

**Dependency graph (with gates):**

```
PREFLIGHT-006A → ARB → T1 → review → T2 → review → T3(+idempotency §5) → review → T4 → T5
                                                         T5 → T8 (dual-read)
T2,T4 → T7 [BLOCKED until §8 re-arm parameters]   T4,T5 → T6 [BLOCKED by U-17 §7]
T1–T3 → T9A [requires §10 accepted backup]        (T9B out of scope)
T5,T8 → T10 [cutover = separate owner approval] → legacy removal [separate owner approval]
all → T11 (proof only, not deployment permission)
```

## 14. Acceptance criteria

No Product-Studio path clears an IE latch (proven); `effective_halt = OR` under a shared global lock (no fractured read); durable cross-file transaction with marker COMMITTED written last; SUCCESS only after durable state + audit; **a single `MUTATION_COMMITTED` audit event is never treated as completion**; completed correlation_ids are verified against a current or **immutable-archived** committed marker + the specific audit event (§5.3), and a **historical transaction is never compared to the current latch state**; the idempotency index is a rebuildable cache, never authority; un-audited/partially-audited clear never authoritative; committed-reader verification + fail-CLOSED on mismatch; non-destructive audit recovery; UNINITIALIZED/missing/corrupt ⇒ HALTED; **fail-safe rollback never re-opens the PS→IE clear crossing and never deletes latch/audit evidence**; U-17 resolved before Telegram changes; risk re-arm parameters byte-identical or owner-decided; **real-execution isolation proven before any "unaffected" claim**; T9A only against an accepted backup architecture; cutover + legacy removal each behind a separate owner approval; kill thresholds / RiskPolicy / money-path byte-identical; no LLM in the kill path; stdlib-only.

## 15. Risks and blocking unknowns

- **U-17 (hard gate):** chat-scoped Telegram auth; blocks T6 until Option A evidence or Option B owner decision (§7).
- **Risk re-arm parameters:** block T7 until confirmed byte-identical or owner-decided; never invented (§8).
- **Real-execution isolation:** cannot claim "unaffected" without preflight evidence; blocks progress if any real-order path is reachable (§9).
- **Backup gap (AUDIT-004 F-REC-1/2):** no verified offsite/encryption; T9B is out of scope; must be an explicit blocker or an owner-accepted temporary risk (§10).
- **Reader fan-out:** every legacy reader must be migrated; a missed reader bypasses the reducer (mitigated by dual-read + a legacy-read lint).
- **Global-lock / flock correctness across launchd processes:** drill-verify.
- **Committed-marker archive integrity:** an unarchived or unverifiable previous marker blocks the next transaction; archive corruption ⇒ HALTED / RECOVERY_REQUIRED.
- **Idempotency index/chain unreadable or unbounded:** ⇒ HALTED / RECOVERY_REQUIRED (never guess completion).

## 16. `PREFLIGHT-RFC054-006A` prompt (the ONLY next executable task, READ-ONLY)

> **TASK: PREFLIGHT-RFC054-006A — READ-ONLY audit. Change NOTHING.** No code, no runtime/kill-switch state, no config, no launchd, no backup/restore, no commit/push/merge, no implementation. Static analysis + read-only inspection only; obey CLAUDE.md invariants (risk domain). Produce a report with exactly these deliverables:
> 1. **Full writer map** of the current kill-switch state (every component that writes `data/kill_switch_active.json`, file:line).
> 2. **Full reader map** (every component that reads it — exhaustive grep).
> 3. **Authority map** (who sets/clears today; the Product-Studio→Investment-Engine crossing).
> 4. **Telegram identity model** — evidence on chat-scoped vs user-scoped auth; whether the bot is DM-only (U-17 Option A) or needs Option B (do NOT print the chat-id value).
> 5. **Exact risk re-arm behaviour** — current hysteresis, re-arm band, healthy-cycle count, their owner, and pinning tests (or an explicit "parameters absent" finding → owner packet).
> 6. **Real-execution isolation evidence** — execution arming gates, env flags, live adapters, launchd services, process list, and every real-order-submit path; conclude either "no reachable real-order path (evidence: …)" or "impact not yet proven → blocked".
> 7. **Backup coverage map** for kill-state — is a backup architecture already accepted? (T9A vs T9B) — flag the backup gap as blocker or owner-accepted temporary risk.
> 8. **Filesystem/lock compatibility** — flock semantics across launchd processes; atomic-write pattern.
> 9. **Current legacy-state interpretation** — how `active=true/false` is read today; migration fail-safe implications.
> 10. **Blocking unknowns** — U-17, re-arm parameters, backup gap, reader-fan-out, real-order paths.
> 11. **Confirmation that no files or runtime state were changed** (read-only), with a final `git status` (no git actions).
> Deliver the report to the ARB. Do NOT proceed to T1 — that is a separate authorization.
