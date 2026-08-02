# ADR-054 — Kill-Switch Authority & Ownership

- **Status:** ACCEPTED  (owner decision recorded 2026-07-20; implementation is a separate task — see `docs/rfcs/RFC-054-implementation-plan.md`, still NON-EXECUTABLE DRAFT)
- **Date:** 2026-07-20 (proposed) · **Accepted:** 2026-07-20
- **Deciders:** Owner (Yurii) + Investment-Engine governance (risk domain)
- **Owner decision:** D-01…D-07 all accepted per ARB recommendation ("вариант 1"), recorded in the packet below. Acceptance authorizes the design; it does NOT change any code, kill thresholds (ADR-034/048 unchanged), RiskPolicy, execution gate, or runtime state.
- **Context source:** `docs/rfcs/RFC-054-kill-switch-authority.md` (see §CLOSURE-005A for the resolved persistence/audit design + owner decision packet)
- **Related:** ADR-034 / ADR-048 (two-tier kill-switch — thresholds UNCHANGED), ADR-050 (RiskPolicy → governance layer), CLAUDE.md invariants #1 #2 #3 #4 #5.

## Context
`data/kill_switch_active.json` is the Investment-Engine hard-gate halt state written by three unarbitrated writers (risk engine, `threat_reactor`, Product-Studio Telegram bot) with no independent risk-domain authorization, no source attribution, and no arbitration; the reader keys off the `active` boolean, so **Product Studio (`/resume`) can clear an engine-set protection state** (E-093/E-103/E-104). Product Studio must not have unbounded authority to remove Investment-Engine protection.

## Decision (ACCEPTED 2026-07-20)
Adopt **source-separated latches with Investment-Engine-owned effective state** (RFC-054 Option C): four latches `manual_pause` (Product-Studio-owned), `risk_kill`, `threat_kill`, `execution_kill` (Investment-Engine-owned); `HALTED = OR(active latches)`; unknown/corrupt/missing ⇒ fail-CLOSED; each source clears only its own latch; every mutation is attributed and serialized to a dedicated audit. **Resolved by CLOSURE-005A:**
- **Persistence = Model B — separate latch files** (`data/kill_switch/{manual_pause,risk_kill,threat_kill,execution_kill}.json`), each single-owner + single-writer-API + own lock + monotonic revision. The "single document + per-latch locks" combination is explicitly **not** used. `effective_halt` is computed by ONE reducer (Investment-Engine-owned) and written **derived-only** to `data/kill_switch_effective.json` — never a writable authority.
- **Audit = Audit B — dedicated serialized `data/kill_switch_events.jsonl`** (single writer + global lock + hash chain + fsync), isolated from the multi-writer `audit_chain.jsonl` (which carries an un-serialized lost-update risk, F-CON-1). Tamper-evidence is claimed only because writes are serialized.

**Resolved by CLOSURE-005B:**
- **Read path = Read Model A (direct reduction)** — safety consumers read the four latch files and recompute `effective_halt` each cycle; **`kill_switch_effective.json` is a DERIVED_CACHE with Authority NONE and can never un-halt execution.** A stale/missing/corrupt snapshot is never trusted.
- **Mutation success boundary:** SUCCESS is returned only after BOTH the latch write and the audit append are durable (fsync). Lock order: latch-file lock → global kill-audit lock. An un-audited clear is never trusted (fail-safe).
- **Audit corruption is NEVER auto-truncated** — corrupt bytes are quarantined (`kill_switch_events.corrupt.<ts>` + `kill_switch_events_recovery.json`), the system enters RECOVERY_REQUIRED (fail-CLOSED), and recovery is **authorized (owner/IE governance), not automatic**, continuing via a new linked chain segment.
- **Initialization ≠ runtime failure:** UNINITIALIZED ⇒ HALTED until owner-approved migration completes; runtime missing/corrupt latch ⇒ that latch ACTIVE + RECOVERY_REQUIRED; legacy `active=true` ⇒ an `unknown_or_legacy` halt PS cannot clear.

**Resolved by CLOSURE-005C (transaction consistency):**
- **One global state lock** `data/kill_switch/.state.lock` — readers SHARED (read all four latches + transaction marker atomically), writers EXCLUSIVE (whole transaction). Per-latch locks removed; uniform order global→(latch)→audit. **Fractured reads are impossible** (a reader sees a complete pre- or post-state; any lock/read/schema failure ⇒ HALTED).
- **Durable transaction marker** `data/kill_switch/transaction.json` (write-ahead, fsync before latch change) binds the cross-file state↔audit change: PREPARED→AUDIT_WRITTEN→STATE_WRITTEN→COMMITTED; **the marker is the commit point.** A **pending SET ⇒ latch ACTIVE**; a **pending CLEAR ⇒ old active still honored** — an incomplete transaction is **always fail-CLOSED**, and an **un-audited/uncommitted clear can never un-halt.**
- **Audit-before-state** protocol: the first audit event is `MUTATION_PREPARED` (never COMMITTED before state is published); `MUTATION_COMMITTED` only after the latch is published and the marker is COMMITTED.
- **Persistent idempotency** (marker + audit, not process memory): completed correlation_id → return prior result; pending → resume/RECOVERY_REQUIRED; same id + different payload → reject + security audit.
- **Startup recovery:** COMMITTED ⇒ verify hashes; PREPARED/STATE_WRITTEN/AUDIT_WRITTEN ⇒ HALTED + authorized recovery; corrupt ⇒ HALTED + preserve evidence. **Recovery never auto-clears an engine latch.**

**Resolved by CLOSURE-005D (final commit ordering):** the transaction **marker COMMITTED is written LAST** (step 13/16) — only after the latch is durable AND both audit events (`MUTATION_PREPARED`, then `MUTATION_COMMITTED`="state durable, ready for final commit") are durable (fsync). **Marker COMMITTED can never precede the durable final audit event.** A `COMMITTED` marker is trusted only when the reader also verifies transaction_id/correlation_id/latch_id + `new_revision`==latch.revision + `new_state_hash`==sha256(latch) + a valid committed audit event exists — **any mismatch ⇒ fail-CLOSED (RECOVERY_REQUIRED)**; never trust `status=COMMITTED` alone. Persistent-idempotency **completion** requires marker COMMITTED **and** matching latch hash **and** a valid committed audit event; a correlation_id in an audit event but not in a COMMITTED marker is **pending, not completed**. An un-audited or partially-audited clear can never become authoritative.

**No threshold, RiskPolicy, execution-gate, or money-path change. No LLM in the kill path.**

## Owner decisions — ANSWERED 2026-07-20 (all option 1 / ARB); full packet with consequences in RFC §8
| ID | Question | ARB recommendation | Owner response |
|---|---|---|---|
| **D-01** | Telegram `/resume` clears `manual_pause` only? | **YES** (PS may never clear an IE latch; KS-02/KS-04) | **ACCEPTED (opt.1)** — /resume clears manual_pause only |
| **D-02** | Who may clear `threat_kill`? | **Investment-Engine governance only** (not the reactor, not the operator; KS-07) | **ACCEPTED (opt.1)** — IE governance only clears threat_kill |
| **D-03** | Can `risk_kill` clear automatically? | **YES — deterministic, hysteresis + N healthy cycles**; owner ack recorded, not required; manual override PROHIBITED | **ACCEPTED (opt.1)** — risk_kill auto-clears (deterministic + hysteresis + N healthy cycles) |
| **D-04** | Safety readers use **direct reduction under a shared global state lock** (`.state.lock` — fractured reads impossible)? | **YES** — direct reduction (Read Model A) under the shared lock; `kill_switch_effective.json` cache-only | **ACCEPTED (opt.1)** — separate latch files; safety reads under a shared global state lock |
| **D-05** | Approve the durable cross-file transaction protocol where **latch state AND both audit events are durable BEFORE the marker becomes COMMITTED** (marker written last; readers verify marker+latch-hash+committed-audit; any mismatch ⇒ fail-CLOSED)? | **YES** | **ACCEPTED (opt.1)** — no unlock until state+audit fully durable; marker COMMITTED written last |
| **D-06** | Missing/corrupt state behavior? | **fail-CLOSED** (that latch = ACTIVE; effective HALTED) | **ACCEPTED (opt.1)** — missing/corrupt state ⇒ fail-CLOSED / HALTED |
| **D-07** | Two-step request→approve for engine-latch clears? | **YES** for `threat_kill` + `execution_kill`; `risk_kill` clears deterministically by the engine | **ACCEPTED (opt.1)** — threat_kill + execution_kill clears via request → approve |
| **D-08** | Adopt the minimal **Latch Schema v1** (exact 7-field latch snapshot) to resolve the T2 schema blocker? | **Option 1** — accept minimal Schema v1 (audit/actor/evidence/approval fields live in T3/T4 layers, not the snapshot) | **ACCEPTED (opt.1) 2026-07-21** — minimal Latch Schema v1 adopted; resolves the T2 schema blocker |
| **D-09** | Adopt **Transaction Marker & Audit Schema v1** (T3: marker + dedicated hash-chained events + idempotency identifiers) to resolve the T3 schema blocker? | **D-09-A** — full attribution in v1; `AUDIT_WRITTEN` marker-status-only; reuse hash primitives only; UUIDv4 ids injectable; retention deferred | **ACCEPTED WITH MODIFICATION 2026-07-22** — packet accepted + **`old_state_hash` added to the marker** (full cryptographic before/after transition proof); retention/compaction deferred to future **D-10 Backup & Retention Policy**; resolves the T3 schema blocker |
| **D-11** | Adopt **Audit Recovery & Segment Schema v1** (quarantine + recovery metadata + segment linking for the dedicated audit chain) to resolve the T3.2b.2 schema blocker? | **D-11-A** — auto RECOVERY_REQUIRED marking (fail-closed only), authorized quarantine/segment/completion, segments born only from recovery | **ACCEPTED WITH MODIFICATION 2026-07-22** — Opt-A adopted + ARB modifications: (1) recovery metadata is **NOT audit authority** (describes an incident; never replaces events/hash-chain/evidence); (2) **reducer never reads recovery.json** (safety/committed reader maps it to `NormalizedLatchState.RECOVERY_REQUIRED`; reducer stays pure/no-I/O); (3) **D-10 stays separate** (no runtime deletion/compaction until D-10); resolves the T3.2b.2 schema blocker |

*(Owner responses RECORDED 2026-07-20 (D-01…D-07, all opt.1), 2026-07-21 (D-08, opt.1) and 2026-07-22 (D-09, accepted with modification). Cross-reference: `threat_kill` clear authority = D-02 + D-07; `risk_kill` auto-clear = D-03. Model B/Audit B are confirmed within D-04/D-05; legacy-file interpretation + init/recovery states are in RFC-054 §CLOSURE-005B. Latch Schema v1 = D-08; Transaction Marker & Audit Schema v1 = D-09; exact wire schemas in RFC-054 §6 + below.)*

## Latch Schema v1 — D-08 (ACCEPTED 2026-07-21)
Each latch file `<state_dir>/{manual_pause,risk_kill,threat_kill,execution_kill}.json` stores ONLY the current authoritative snapshot with **exactly these 7 mandatory fields — no more, no less**:

```json
{"schema_version":1,"latch_id":"risk_kill","active":true,"revision":3,"created_at":"2026-07-21T18:42:10.123456Z","updated_at":"2026-07-21T18:45:02.654321Z","reason_code":"drawdown_limit"}
```

- `schema_version` — JSON int, only `1` supported (a Python `bool` is NOT a valid int here); any other ⇒ `UNKNOWN_SCHEMA`.
- `latch_id` — JSON string ∈ {manual_pause, risk_kill, threat_kill, execution_kill}; **must equal the filename stem** (mismatch ⇒ fail-CLOSED).
- `active` — JSON boolean only (no numeric/string coercion).
- `revision` — JSON int (bool invalid), min `1`, initialized `1` by the T10 migration, `+1` per accepted mutation, monotonic, never decreases/skips; stale expected-revision rejected (CAS).
- `created_at` / `updated_at` — UTC RFC3339, exactly six fractional-second digits, uppercase `Z` (e.g. `2026-07-21T18:42:10.123456Z`); `created_at` immutable after init; `updated_at` ≥ `created_at`, bumped each mutation.
- `reason_code` — non-empty JSON string, `^[a-z][a-z0-9_]*$` (no closed enum in D-08; catalogs belong to writer/governance tasks).

**Any additional OR missing field ⇒ `UNKNOWN_SCHEMA` ⇒ effective HALTED.** Fields **excluded** from the snapshot (they belong to the T3 transaction/audit and T4 authorization layers, never duplicated into the latch): `source`, `severity`, `reason_text`, `actor_type`, `actor_id`, `correlation_id`, `evidence_ref`, approval data, audit history. Canonical serialization: UTF-8, `sort_keys=True`, `ensure_ascii=False`, `separators=(",", ":")`, no indent, no trailing newline (the canonical bytes are used for future transaction hashing). **Initialization is NOT automatic:** a missing production latch stays `MISSING ⇒ HALTED`; only the owner-approved **T10 migration** creates the four files (`schema_version=1`, correct `latch_id`, `revision=1`, equal valid `created_at`/`updated_at`, a migration-defined `reason_code` and fail-safe `active`). **This decision resolves the T2 schema blocker.**

## Transaction Marker & Audit Schema v1 — D-09 (ACCEPTED WITH MODIFICATION 2026-07-22)

Canonical rules reuse D-08 verbatim: `schema_version` = JSON int `1` (bool invalid) · UTC RFC3339 timestamps, exactly six fractional digits + uppercase `Z` · lowercase SHA-256 hex (64) · canonical bytes = UTF-8, `sort_keys=True`, `ensure_ascii=False`, `separators=(",",":")`, no indent, no trailing newline. Additional OR missing field ⇒ `UNKNOWN_SCHEMA` ⇒ HALTED.

**`data/kill_switch/transaction.json` — marker Schema v1 (exactly 17 mandatory fields):**
`schema_version` · `transaction_id` (UUIDv4) · `correlation_id` (caller idempotency key, `^[A-Za-z0-9_.:-]{1,128}$`) · `latch_id` (enum of the four) · `action` (`SET`|`CLEAR`) · `old_revision` (int ≥1) · `new_revision` (= old+1) · `old_active` (bool) · `new_active` (bool) · **`old_state_hash`** (sha256 of the OLD canonical latch bytes — owner modification: full before/after transition proof) · `new_state_hash` (sha256 of the NEW canonical latch bytes) · `status` · `actor_domain` (`INVESTMENT_ENGINE`|`PRODUCT_STUDIO`) · `actor_id` (opaque) · `authorization_result` · `created_at` · `updated_at` (≥ created_at).
**Marker `status` enum:** `PREPARED → AUDIT_WRITTEN → STATE_WRITTEN → COMMITTED` · terminal `ABORTED` · fail `RECOVERY_REQUIRED`. **`COMMITTED` is written LAST** (D-05); any non-COMMITTED/ABORTED marker = pending ⇒ HALTED. `AUDIT_WRITTEN` is **marker-status-ONLY** — it is NOT an audit event (Q1).

**`data/kill_switch/kill_switch_events.jsonl` — event Schema v1 (exactly 20 mandatory fields):**
`schema_version` · `sequence` (int ≥1, monotonic — the ORDERING AUTHORITY, Q3) · `event_id` (UUIDv4) · `event_type` · `transaction_id` · `correlation_id` · `latch_id` · `action` · `old_revision` · `new_revision` · `old_active` · `new_active` · `state_file_hash` · `reason_code` (`^[a-z][a-z0-9_]*$`) · `actor_domain` · `actor_id` · `authorization_result` · `timestamp` · `previous_hash` (entry_hash of seq-1; genesis `"0"*64`) · `event_hash` (sha256 over canonical of sequence/timestamp/event_type/payload/previous_hash).
**Audit `event_type` enum (5):** `MUTATION_PREPARED` · `STATE_WRITTEN` · `MUTATION_COMMITTED` · `ABORTED` · `RECOVERY_REQUIRED`.

**Q2 — hash-chain reuse boundary:** ALLOWED to reuse from `spa_core/audit/hash_chain.py`: `compute_entry_hash`, `verify_chain`(-style linkage verification), the canonical hash logic. FORBIDDEN: writing into the shared `audit_chain.jsonl`, reusing `hash_chain.append()`, or any shared multi-writer append path (F-CON-1) — the kill-switch events file is dedicated and appended ONLY serially under the T2 EXCLUSIVE global lock.
**Q3 — identifiers:** `transaction_id` and `event_id` are UUIDv4; both generators MUST be injectable for tests; ordering authority is the `sequence` field (never the ids).
**Q4 — retention/compaction:** NOT part of D-09 → future placeholder **D-10 “Backup & Retention Policy”**. Until D-10: the immutable `transactions/<transaction_id>.json` archive and the audit chain are **retained; no deletion/compaction by runtime**.
**Q5 — attribution:** `actor_domain`/`actor_id`/`authorization_result` are IN Schema v1, but **T3 records attribution only — authorization ENFORCEMENT is owned by T4** (do not implement authz in T3).

**This decision resolves the T3 schema blocker.**

## Audit Recovery & Segment Schema v1 — D-11 (ACCEPTED WITH MODIFICATION 2026-07-22)

Canonical rules inherit D-08/D-09 verbatim (int `schema_version=1`, D-08 timestamps, lowercase sha256-hex, canonical JSON, exact key set; extra/missing field ⇒ `UNKNOWN_SCHEMA` ⇒ HALTED).

**Recovery model (Opt-A):** AUTOMATIC (fail-closed only): corruption detection; transition to `RECOVERY_REQUIRED`; creation/update of recovery metadata with `authorization_result="PENDING"`. AUTHORIZED ONLY (owner/IE governance; T4 enforces, T3.2b.2 records attribution): quarantine rename, recovery-segment creation, `RECOVERING → RECOVERED`, new live segment, recovery completion, archive of prior recovery metadata. NEVER automatic: truncate, delete evidence, rewrite corrupt history, reconstruct missing events, auto-clear latches, auto-resume.

**`kill_switch_events_recovery.json` — Schema v1 (exactly 16 mandatory fields):** `schema_version` · `state` ∈ {`RECOVERY_REQUIRED`,`RECOVERING`,`RECOVERED`} · `reason` ∈ {`CORRUPT_BYTES`,`CHAIN_INVALID`,`MISSING_SEGMENT`,`UNCERTAIN_DURABILITY`} · `detected_at` · `detected_by` · `corrupt_file` · `corrupt_sha256` · `corrupt_size` · `last_valid_sequence` · `last_valid_event_hash` · `segments` (records: filename, first/last_sequence, first_previous_hash, last_event_hash, sha256, closed_at) · `actor_domain` · `actor_id` · `authorization_result` · `created_at` · `updated_at`.

**Quarantine naming:** `kill_switch_events.corrupt.<TS>`, `<TS> = YYYYMMDDTHHMMSS.ffffffZ` (filename-safe, no `:`); collision ⇒ suffix `.1`, `.2`, …; an existing quarantine file is NEVER overwritten; quarantine = **atomic rename only** (never copy+delete / truncate / rewrite).

**Segment rules:** NO proactive rotation — segments exist ONLY because of recovery; the live file remains `kill_switch_events.jsonl`; closed segments are the quarantine files referenced by recovery metadata. Verification: file exists → sha256 matches → internal hash chain valid → segment linkage valid → sequence continuity valid. The post-recovery first event is `event_type=RECOVERY_REQUIRED` (self-documenting gap). **A non-genesis continuation is valid ONLY when justified by RECOVERED recovery metadata** (prevents legitimized truncation).

**State machine:** `(no file) →auto→ RECOVERY_REQUIRED →authorized→ RECOVERING →authorized→ RECOVERED`; new incident: `RECOVERED →auto→ RECOVERY_REQUIRED` (prior metadata archived first). INVALID: `RECOVERY_REQUIRED→RECOVERED` (skip quarantine), `RECOVERING→RECOVERY_REQUIRED`, `RECOVERED→RECOVERING`.

**ARB modifications (the "WITH MODIFICATION"):** (1) recovery metadata is **NOT audit authority** — it describes an incident and never replaces audit events, hash-chain history, or immutable evidence; (2) **the reducer does NOT read recovery.json** — flow: recovery metadata → safety/committed reader → `NormalizedLatchState.RECOVERY_REQUIRED` → pure reducer (reducer stays pure, no I/O); (3) **D-10 Backup & Retention stays separate** — until D-10: no runtime deletion, no compaction; quarantine + segments retained. **This decision resolves the T3.2b.2 schema blocker.**

## Consequences
- **Positive:** eliminates the PS→IE clear-crossing (the core risk); least-privilege; fail-CLOSED; attributable + tamper-evident audit; iPhone/Telegram retained as operator interface for `manual_pause` + read/ack/request.
- **Negative:** a migration (dual-read → cutover → rollback) and a small state/schema change; discipline needed so no component writes the legacy boolean after cutover.
- **Neutral:** thresholds and money-path untouched; stdlib-only; model-independent (no Anthropic API).

## Invariants ratified (RFC §5): KS-01…KS-13 CONFIRM (KS-07 refined, KS-13 added). See RFC for per-invariant rationale.

## Alternatives rejected
- **A (shared boolean, status quo):** rejected — the defect itself.
- **B (IE arbiter service):** viable but higher coupling/complexity than needed at this scale.
- **D (pure event-replay for current state):** rejected as the *current-state* mechanism (replay/perf/fail-CLOSED risk); its append-only *audit* is adopted on top of Option C.

## Status note
This ADR is **ACCEPTED** (owner decisions on D-01…D-07 recorded 2026-07-20, **D-08 recorded 2026-07-21**, **D-09 recorded 2026-07-22 (accepted with modification: `old_state_hash` added)**, and **D-11 recorded 2026-07-22 (accepted with modification: recovery metadata ≠ audit authority; reducer never reads recovery.json; D-10 separate)**). D-08 (Latch Schema v1), D-09 (Transaction Marker & Audit Schema v1) and D-11 (Audit Recovery & Segment Schema v1, above) are part of the accepted architecture; D-08 **resolved the T2 schema blocker**, D-09 **resolved the T3 schema blocker**, D-11 **resolves the T3.2b.2 schema blocker**; D-01…D-09 are unchanged by D-11 (D-10 remains a reserved placeholder). Retention/compaction is deferred to the future **D-10 Backup & Retention Policy** (until then: no runtime deletion/compaction of the immutable archive or audit chain). Acceptance authorizes the design only — **no code, state, thresholds, RiskPolicy, execution gate, or configuration are changed by this ADR.** Implementation is a separate, still-NON-EXECUTABLE task (`docs/rfcs/RFC-054-implementation-plan.md`); any code work must obey CLAUDE.md §Инварианты #1 and rules/risk-engine.md (risk-domain: keep thresholds byte-identical, prove no PS clears an IE latch, pass the kill-switch drill).
