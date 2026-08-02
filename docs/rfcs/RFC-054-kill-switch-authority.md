# RFC-054 — Kill-Switch Authority & Ownership

- **Status:** PROPOSED (design-only; no code/state changed)
- **Date:** 2026-07-20
- **Owner (decision):** Owner + Investment-Engine governance (risk domain — ADR + owner card required)
- **Companion ADR:** `docs/decisions/ADR-054-kill-switch-authority.md` — **ACCEPTED 2026-07-20** (owner answered D-01…D-07, all option 1 / ARB). This RFC remains the design record; implementation plan: `docs/rfcs/RFC-054-implementation-plan.md` (NON-EXECUTABLE DRAFT).
- **Canonical location:** `docs/rfcs/RFC-054-kill-switch-authority.md` (RFC convention established by this file; single RFC root). Superseded design choices are marked inline; see **§CLOSURE-005A** for the resolved persistence (Model B), audit (Audit B), and owner decision packet.
- **Supersedes/extends:** ADR-034 / ADR-048 (two-tier kill-switch), ADR-050 (RiskPolicy → governance layer). Does NOT change either — this RFC governs *who may set/clear* the switch, not its thresholds.

## Problem
`data/kill_switch_active.json` is the Investment-Engine hard-gate halt state, but it is a **single shared boolean file with three unarbitrated writers** — the risk engine, `threat_reactor`, and the **Product-Studio Telegram bot** (`/pause`,`/resume`). There is no independent risk-domain authorization, no structured source/actor attribution, and no source-aware arbitration; the reader keys off the `active` boolean. Consequently **Product Studio can write/clear an Investment-Engine protection state** with only a chat-scoped transport gate. This RFC proposes an ownership model that separates *manual operator pause* from *engine kill* while keeping the iPhone/Telegram operator interface.

## Current evidence
| Fact | Evidence |
|---|---|
| Kill store = `data/kill_switch_active.json`, IE hard-gate | E-093 |
| 3 writers: `governance/kill_switch.activate/deactivate` (:743,750); `threat_reactor` (:129,143); `telegram/bot.cmd_pause/cmd_resume` (:782,796) | E-093/E-103 |
| Reader `check_manual_trigger` (:498,529) reads only `active` boolean; manual is first in trigger order | E-104 |
| Transport authz = `is_owner(chat_id)` default-DENY, **chat-scoped (no `from.id`)**, chat type UNKNOWN | E-066/E-104/U-17 |
| Independent risk-domain authz ABSENT; source-aware arbitration ABSENT; only free-text `reason` stored | E-104 |
| `/resume` clears the **manual** trigger (VERIFIED); drawdown/threat re-assert after clear **UNPROVEN** | E-104/U-19a |
| Only VERIFIED PS→IE write-crossing today = this file (but 735 unknown-writer stores keep "only crossing" scoped) | E-103/E-107/U-24 |

## Safety boundary (this RFC obeys)
Read-only/design-only. No change to RiskPolicy v1.0, kill thresholds (SOFT −5% / HARD −10%), execution gates, or money-path. No LLM/Claude/Anthropic in any kill decision (invariant #3). Stdlib-only runtime (invariant #4). Atomic writes (invariant #5). Fail-CLOSED (invariant #2).

## Goals
1. Separate **manual operator pause** from **engine kill** (risk / threat / execution).
2. Give **Investment Engine exclusive authority** to clear engine-owned latches.
3. Preserve **iPhone/Telegram** as an operator interface **without** granting Product Studio authority over IE protection state.
4. Structured **source/actor/reason/timestamp/correlation** attribution on every mutation.
5. Deterministic **fail-CLOSED** effective-halt computation; robust reboot/host-loss recovery.

## Non-goals
- Not changing kill thresholds, RiskPolicy, or drawdown ladder (ADR-034/048 unchanged).
- Not enabling real-capital execution (paper phase; invariant on `SPA_EXEC_ARMED`).
- Not adding any LLM to the kill path.
- Not selecting a final SSOT for unrelated stores; not implementing anything (ADR stays PROPOSED).

## Current architecture (model, §2)
```
Telegram /pause,/resume  (PRODUCT_STUDIO) ──┐
Risk engine activate/deactivate (IE) ───────┼─► data/kill_switch_active.json  ──► IE readers (check_manual_trigger)
Threat reactor activate (IE monitor) ───────┘        (boolean `active`; manual first in trigger order)
```
| Writer | Domain | Trigger | Authorization | Can set | Can clear | Source attrib | Reason attrib | Locking | Failure mode | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|
| governance/kill_switch | IE | drawdown/programmatic | engine-internal | YES | YES | none (file-level) | free-text | atomic_save, no lock | fail-toward-halt | E-093 |
| threat_reactor | IE (monitor) | CRITICAL held-protocol threat | monitor-internal | YES | (writes active) | none | free-text | atomic_save, no lock | fail-toward-halt | E-093 |
| telegram bot `/pause` | **PRODUCT_STUDIO** | owner Telegram msg | chat-scoped `is_owner` | YES | — | `reason:"manual_telegram"` | free-text | atomic_save | arms (safe) | E-093/E-104 |
| telegram bot `/resume` | **PRODUCT_STUDIO** | owner Telegram msg | chat-scoped `is_owner` | — | **YES (active:false)** | `reason:"manual_telegram_resume"` | free-text | atomic_save | **clears manual; may suppress re-arm — U-19a** | E-104 |

**The defect:** one boolean, no per-source latch, no risk-domain authz on the clear path → `/resume` (Product Studio) clears the shared flag the engine reads.

## Alternatives (§3) & decision matrix (§4)

- **Option A — keep shared boolean file (status quo).** Rejected: no source separation, PS can clear IE state, no attribution, no arbitration.
- **Option B — single IE arbiter (PS requests, IE decides, IE-owned canonical state).** Strong ownership; higher coupling (PS must round-trip through an IE service; more moving parts).
- **Option C — source-separated latches; `HALTED = OR(active latches)`; each source clears only its own latch.** Strong least-privilege + fail-CLOSED + simple; engine owns the risk/threat/execution latches.
- **Option D — append-only command/event stream; current state = replay.** Best auditability; needs snapshot+replay, higher complexity/perf, harder fail-CLOSED on corrupt stream.

| Criterion | A | B | C | D |
|---|---|---|---|---|
| Fail-closed safety | ~ | + | **+** | ~ (replay risk) |
| Independent ownership | − | + | **+** | + |
| Least privilege | − | + | **+** | + |
| Auditability | − | + | + | **++** |
| Source attribution | − | + | **+** | ++ |
| Clear-authority enforcement | − | + | **+** | + |
| Atomicity | + | + | **+** | ~ |
| Concurrency | − | + | **+** (per-latch) | ~ |
| Recovery / Reboot | ~ | + | **+** | ~ (needs snapshot) |
| iPhone operability | + | + | **+** | + |
| No Anthropic API / model-independent | + | + | **+** | + |
| Local-first / stdlib | + | ~ (service) | **+** | + |
| IE separation | − | + | **+** | + |
| Migration complexity | 0 | high | **low-med** | high |
| Backward compatibility | + | ~ | **+** (legacy map) | ~ |
| Operational simplicity | + | − | **+** | − |

**Recommended: Option C (source-separated latches) + Investment-Engine-owned effective state**, optionally layering Option D's append-only audit *events* into the existing hash-chained `audit_chain.jsonl` (best of C's simplicity + D's auditability, without a replay-based current state).

## Recommended design (§5)
- **Four latches:** `manual_pause` (PRODUCT_STUDIO-owned), `risk_kill`, `threat_kill`, `execution_kill` (all IE-owned).
- **Effective state:** `HALTED = OR(manual_pause, risk_kill, threat_kill, execution_kill)`; unknown/corrupt/missing ⇒ `HALTED=true` (fail-CLOSED).
- **Clear authority:** each source clears only its own latch; **no Product-Studio path clears an IE latch**; `threat_kill` clear requires a separate IE authorization path.
- **Attribution:** every mutation records source, actor, reason_code, timestamp, correlation_id; appended to the hash-chained audit (`audit_chain.jsonl`, tamper-evident, E-095).

### Invariant confirmations (§5)
| Inv | Verdict | Note |
|---|---|---|
| KS-01 (effective = OR) | **CONFIRM** | |
| KS-02 (no PS clears risk/threat/execution) | **CONFIRM** | core of the fix |
| KS-03 (/pause sets only manual_pause) | **CONFIRM** | |
| KS-04 (/resume clears only manual_pause) | **CONFIRM** | |
| KS-05 (risk engine ↔ risk_kill only) | **CONFIRM** | |
| KS-06 (threat_reactor sets threat_kill) | **CONFIRM** | set-only for the reactor |
| KS-07 (threat_kill clear = separate IE authz) | **CONFIRM + REFINE** | clear via governance auto-clear when threat gone AND a cool-down/confirm; never via operator transport |
| KS-08 (unknown/corrupt/missing = fail-CLOSED) | **CONFIRM** | |
| KS-09 (mutation carries source/actor/reason/ts/correlation) | **CONFIRM** | |
| KS-10 (no LLM/Claude in kill decisions) | **CONFIRM** | invariant #3 |
| KS-11 (no threshold change) | **CONFIRM** | |
| KS-12 (no real-capital execution) | **CONFIRM** | |
| — added KS-13 | **PROPOSE** | manual_pause has NO auto-clear; only explicit operator `/resume` clears it (avoids silent un-pause) |

## State model (§6 — Latch Schema v1, D-08 ACCEPTED 2026-07-21)
Each latch file `<state_dir>/{manual_pause,risk_kill,threat_kill,execution_kill}.json` holds ONLY the current authoritative snapshot with **exactly these 7 mandatory fields (no additional, no missing)**:
```json
{"schema_version":1,"latch_id":"risk_kill","active":true,"revision":3,"created_at":"2026-07-21T18:42:10.123456Z","updated_at":"2026-07-21T18:45:02.654321Z","reason_code":"drawdown_limit"}
```
Field rules (exact):
- `schema_version` — JSON int, only `1` valid in v1 (a Python `bool` is NOT accepted as int); other ⇒ `UNKNOWN_SCHEMA`.
- `latch_id` — JSON string ∈ {manual_pause,risk_kill,threat_kill,execution_kill}, **must equal the filename stem** (mismatch ⇒ fail-CLOSED).
- `active` — JSON boolean only (no coercion).
- `revision` — JSON int (bool invalid), ≥ `1`, init `1` (T10 migration), `+1` per accepted mutation, strictly monotonic, never decreases/skips; CAS on expected revision (stale ⇒ reject). **(This resolves the prior contradiction where a monotonic revision was required by Model B but absent from the logical record — `revision` is now a first-class snapshot field.)**
- `created_at` / `updated_at` — UTC RFC3339, exactly six fractional-second digits + uppercase `Z`; `created_at` immutable after init; `updated_at` ≥ `created_at`, bumped each mutation.
- `reason_code` — non-empty JSON string matching `^[a-z][a-z0-9_]*$` (no closed enum in D-08).

**Additional OR missing field ⇒ `UNKNOWN_SCHEMA` ⇒ HALTED.** Canonical serialization: UTF-8, `sort_keys=True`, `ensure_ascii=False`, `separators=(",", ":")`, no indent, no trailing newline.

**Layer separation (do NOT put these in the latch snapshot):**
- **Latch snapshot (D-08 / T2)** — the 7 fields above; the current authoritative per-latch state only.
- **Transaction marker (T3)** — `transaction_id, correlation_id, latch_id, action, old_revision, new_revision, old_active, new_active, new_state_hash, status, created_at, actor, authorization` (§CLOSURE-005C).
- **Audit evidence (T3)** — hash-chained events (`event_id, correlation_id, sequence, previous_hash, event_hash, latch_id, …, actor_domain, actor_id, authorization_result, reason_code, timestamp, state_file_hash, schema_version`) in the dedicated serialized log.
- **Actor / domain authorization (T4)** — `source`, `actor_type`, `actor_id`, approval data live in the authorization layer, not the snapshot.

The `severity`, `reason_text`, `actor_type`, `actor_id`, `source`, `correlation_id`, `evidence_ref` fields from the earlier logical sketch are **excluded** from the v1 latch snapshot (they belong to the transaction/audit/authz layers above) — the snapshot must not become a duplicate audit record.

Effective document (derived cache, Authority NONE) = `{schema_version, latches:[...], effective_halt: OR(...), computed_at}`. **The pure reducer computes `effective_halt` and performs no I/O. A later T5 cache-writer / I/O layer may persist `data/kill_switch_effective.json` from the reducer result. The derived cache has Authority NONE and is never an authoritative writable state.**

## State machine (§7) — per latch
**manual_pause** (owner: PRODUCT_STUDIO via transport):
| Current | Event | Authorized actor | Guard | Next | Audit | Failure |
|---|---|---|---|---|---|---|
| inactive | `/pause` | operator (transport authz) | is_owner + (future) user-scoped | active | ManualPauseSet | write fails ⇒ keep-safe (retry; if unknown ⇒ halt) |
| active | `/resume` | operator | is_owner | inactive | ManualPauseCleared | — |
| any | corrupt/missing | — | — | **treated active** | StateCorrupt | fail-CLOSED |

**risk_kill** (owner: IE governance):
| Current | Event | Actor | Guard | Next | Audit |
|---|---|---|---|---|---|
| inactive | drawdown ≥ HARD | risk engine | deterministic threshold (ADR-048) | active | RiskKillActivated |
| active | drawdown recovers < re-arm band | risk engine | engine-internal only | inactive | RiskKillCleared |
| active | `/resume` from Telegram | — | **DENIED** (KS-02) | active | UnauthorizedClearAttempt |

**threat_kill** (owner: IE monitor set / IE governance clear):
| Current | Event | Actor | Guard | Next | Audit |
|---|---|---|---|---|---|
| inactive | CRITICAL held-protocol threat | threat_reactor | detection | active | ThreatKillActivated |
| active | threat cleared | IE governance (KS-07, separate path + cool-down) | not operator | inactive | ThreatKillCleared |
| active | operator clear | — | **DENIED** | active | UnauthorizedClearAttempt |

**execution_kill** (owner: IE; paper phase = latent):
| inactive | execution readiness fail | execution/governance | gate | active | ExecutionKillActivated |
| active | readiness restored | IE governance | not operator | inactive | ExecutionKillCleared |

**Cross-cutting events:** host restart ⇒ read latch doc; if missing/corrupt ⇒ fail-CLOSED (effective HALTED). Conflicting simultaneous mutations ⇒ per-latch file lock (only one writer per latch) + atomic replace; last-writer-wins is safe because writers are partitioned by latch.

## Authority matrix (§8)
| Latch | May SET | May CLEAR | May ACK | May VIEW | Required evidence | Approval |
|---|---|---|---|---|---|---|
| manual_pause | Operator (Telegram/iPhone) | **Operator only** | Operator | Operator, IE, dashboards | operator identity | none (operator-owned) |
| risk_kill | Risk engine | **Risk engine only** | Operator (ack, no clear) | all | drawdown snapshot | engine deterministic |
| threat_kill | threat_reactor | **IE governance only (KS-07)** | Operator (ack) | all | threat id | IE authz + cool-down |
| execution_kill | IE execution/governance | **IE only** | Operator (ack) | all | readiness audit | IE authz |

**Hard rule:** Product Studio may set/clear `manual_pause` only; Investment Engine owns `risk_kill`/`threat_kill`/`execution_kill`.

## Operator interface (§9) — safe iPhone/Telegram semantics
| Command | Transport authz | User authz | Risk-domain authz | Approval | Operator response | Audit |
|---|---|---|---|---|---|---|
| `/pause` | is_owner(chat) + (future) user-scoped | operator | n/a (operator-owned latch) | none | "manual_pause ON" | ManualPauseSet |
| `/resume` | is_owner | operator | n/a | none | "manual_pause OFF (engine latches unaffected)" | ManualPauseCleared |
| `/status` | is_owner | operator | read-only | none | shows each latch + effective HALTED + who set it | (read) |
| `/ack` | is_owner | operator | read-only | none | acknowledges an engine kill (no clear) | KillAcknowledged |
| `/request-risk-clear` | is_owner | operator | **request only — cannot clear** | creates an IE-side request; IE governance decides | "request logged; IE will decide" | RiskClearRequested |

**Telegram can NEVER directly clear an engine-owned latch.** `/request-risk-clear` creates a request record only.

## Persistence & recovery (§10) — JSON vs SQLite compared by evidence
| Dimension | Structured JSON (+ atomic_save) | SQLite |
|---|---|---|
| stdlib-only (invariant #4) | ✅ (matches existing pattern) | ✅ (sqlite3 stdlib) but adds a DB dependency for tiny state |
| atomic mutation | ✅ tmp+os.replace (existing `atomic_save`) | ✅ txn |
| per-latch locking | ✅ per-latch file + flock (like KANBAN, E-088) | ✅ row lock |
| append-only audit | ✅ reuse hash-chained `audit_chain.jsonl` (E-095, tamper-evident) | would duplicate an audit table |
| backup inclusion | ✅ `data/*.json` glob + should add to iCloud MUST_HAVE | needs `_SQLITE_FILES` addition |
| recovery / corrupt handling | ✅ small doc, easy fail-CLOSED default | fine |
| divergence risk (two spa.db lesson) | low (single small doc) | adds a 3rd DB / path-drift risk (U-04) |
| **Recommendation** | **SUPERSEDED by CLOSURE-005A → Model B (separate latch files).** (The earlier "single doc + per-latch flock" combination is explicitly disallowed — a single document must use ONE global lock; per-latch locks require per-latch files. See §CLOSURE-005A.) | not recommended (extra DB dependency, path-drift risk) |

- **Recovery precedence:** effective state = read latch doc; if missing/corrupt/stale ⇒ **fail-CLOSED (HALTED)** until an authorized actor re-asserts. Snapshot = the latch doc itself (current), audit = the hash-chained event log (history). Backup: include the latch doc in the iCloud MUST_HAVE set + DR set (currently kill_switch is daily-tar-only and NOT_OBSERVED, E-101/E-112). Encrypted backup: fold into the accepted encrypted-backup architecture.
- **Compatibility with the current boolean file:** legacy `active:true` ⇒ interpreted as `manual_pause=active OR unknown` (fail-safe, halt remains); legacy `active:false` from an unknown source ⇒ **must NOT auto-clear engine latches**.

## Migration strategy (§11) — designed, not executed
Preflight (backup prerequisite: durable+offsite backup of current kill state) → read-only validation (parse legacy file, log) → **dual-read period** (readers compute effective halt from BOTH legacy boolean and new latch doc, taking the fail-safe OR) → legacy-file interpretation rules (above) → write cutover (writers move to per-latch API) → rollback (revert readers/writers to legacy boolean; latch doc ignored) → post-cutover verification (drills for each latch + unauthorized-clear denial) → removal criteria (legacy file removed only after N cycles of dual-read agreement + a kill-switch drill passing). **Fail-safe during migration:** legacy `active=true` ⇒ halt stays; unknown source ⇒ Product Studio cannot clear.

## Failure modes (§12)
| Failure | Impact | Detection | Prevention | Recovery | Residual |
|---|---|---|---|---|---|
| Lost update (concurrent writers) | wrong effective state | audit gap | per-latch flock + atomic replace; writers partitioned by latch | recompute from latch doc | low |
| Simultaneous pause+clear | race on manual_pause | audit | single-owner latch (operator) | last-write-wins (both operator) | low |
| Stale Telegram command | clears a newer pause | correlation_id/nonce | command TTL + correlation | ignore stale | med (needs nonce) |
| Unauthorized group member | non-owner acts | — | **user-scoped authz (U-17)** + owner-DM confirmation | deny | HIGH until U-17 fixed |
| State corruption / missing | ambiguous halt | schema check | fail-CLOSED default | halt until re-assert | low |
| Clock skew | ordering wrong | UTC + monotonic seq | server UTC only | audit reorder | low |
| Duplicate / replay command | double action | correlation_id dedup | idempotent set/clear | dedup | low |
| Partial migration | mixed readers | dual-read parity check | dual-read gate | rollback | med |
| Old component writes legacy file | bypasses latches | dual-read divergence alarm | cutover lint + legacy-write ban | fail-safe OR | med |
| Backup restore of stale state | resurrects cleared kill / clears live one | restore drill | fail-safe interpretation on restore | re-assert from engine | med |
| **Risk latch cleared via manual path** | **protection removed** | UnauthorizedClearAttempt audit | **KS-02 (no PS clear of IE latch)** | deny at API | **the core risk — eliminated by design** |

## Security considerations
- Transport authz (`is_owner`) is necessary but **not** risk-domain authz; user-scoped authz (U-17) is a prerequisite for trusting operator identity.
- No LLM/Claude in the kill path (KS-10); the live AI path (ask_router) must never write a latch.
- Fail-CLOSED everywhere; arming is always safe, clearing is always privileged.

## Open decisions (→ ADR-054, §13)
D-01 Can `/resume` clear anything but manual_pause? **ARB: NO.** · D-02 Who clears threat_kill? **ARB: IE governance only (KS-07).** · D-03 Does risk/threat clear need human approval? **ARB: engine auto-clear for risk (deterministic), IE-authorized for threat; operator may only `/ack` or `/request-risk-clear`.** · D-04 Canonical persistence? **ARB: structured JSON latch doc + hash-chained audit (not SQLite).** · D-05 Legacy file during migration? **ARB: fail-safe OR; unknown source cannot clear.** · D-06 Authoritative state after reboot? **ARB: latch doc; missing/corrupt ⇒ fail-CLOSED.** · D-07 Two-step request→approve for engine clears? **ARB: YES for threat/execution; risk clears deterministically by the engine.**

## Acceptance criteria (for the future implementation)
Set/clear authority separated per latch; no PS path clears an IE latch (proven by test); effective=OR; fail-CLOSED on corrupt/missing; every mutation attributed + hash-chain-audited; `/resume` clears only manual_pause; drawdown/threat re-assert proven by drill; iPhone `/pause`,`/resume`,`/status`,`/ack`,`/request-risk-clear` work; migration dual-read parity + rollback verified; **no threshold/money-path change**.

## Implementation epics (§16) — decomposed, not executed
- **Epic 1 — Canonical state & schema:** latch doc schema + effective-halt computation (fail-CLOSED) + read API. Stories: schema module; `compute_effective_halt`; corrupt/missing handling; unit tests.
- **Epic 2 — IE arbiter:** per-latch set/clear API with domain-scoped authorization; deny cross-domain clears. Stories: latch API; authz guard; UnauthorizedClearAttempt audit.
- **Epic 3 — Telegram request boundary:** `/pause`,`/resume` → manual_pause only; `/ack`, `/request-risk-clear` (request record, no clear). Stories: command handlers; request store; deny engine-latch clear.
- **Epic 4 — Legacy compatibility:** dual-read of legacy boolean + latch doc (fail-safe OR); legacy interpretation rules. Stories: dual-read reader; legacy-write ban lint; divergence alarm.
- **Epic 5 — Audit & observability:** append latch events to `audit_chain.jsonl`; `/status` view; dashboard latch panel. Stories: audit emitter; status summary; verify_spa coverage.
- **Epic 6 — Backup & recovery:** add latch doc to iCloud MUST_HAVE + DR + encrypted-backup; restore drill with fail-safe interpretation. Stories: backup-set change; restore drill; recovery precedence test.
- **Epic 7 — Migration & rollback:** preflight → dual-read → cutover → rollback → removal criteria. Stories: migration runbook; parity gate; rollback script; removal gate.
- **Epic 8 — Tests & safety proof:** kill-switch drills per latch; unauthorized-clear denial; reboot/corrupt fail-CLOSED; concurrency; no-threshold-change assertion. Stories: drill suite; property tests; CI safety gate.

## Rollback principles
Any step reverts to the legacy boolean file with readers taking the fail-safe OR; the latch doc is ignored on rollback; no threshold or money-path is ever touched; a kill-switch drill must pass before and after each step.

## Evidence references
E-066, E-093, E-095, E-101, E-103, E-104, E-107, E-112, U-17, U-19, U-19a, U-24. Code: `governance/kill_switch.py:335,498,529,743,750,829`; `monitoring/threat_reactor.py:129,143`; `telegram/bot.py:65-70,782,796`; `audit/hash_chain.py`.

---

## Appendix — Future implementation prompt

> **⛔ NON-EXECUTABLE DRAFT — BLOCKED ON ADR-054 ACCEPTANCE.** This is not a runnable assignment. The next task after owner approval is **`PHASE1-KILL-SWITCH-IMPLEMENTATION-PLAN-005B`** (prepare the exact implementation plan; still DESIGN-ONLY, no implementation). Actual code work happens only in a later, separately-authorized task once the plan is approved. The prompt below is retained as a non-executable seed for 005B, updated for Model B / Audit B.

> **[NON-EXECUTABLE DRAFT] IMPLEMENT-KILL-SWITCH-LATCHES (post-005B, requires ACCEPTED ADR-054 + owner answers to D-01…D-07):**
> Preconditions: ADR-054 status = ACCEPTED; owner card answering D-01…D-07; a durable+offsite (encrypted) backup of the current `data/kill_switch_active.json` taken first. Do NOT change RiskPolicy v1.0, kill thresholds (ADR-034/048), execution gates, or any money-path; no LLM in the kill path (invariant #3); stdlib-only (#4); atomic writes (#5); fail-CLOSED (#2).
> Execute the epics in order with a passing kill-switch drill before and after each: **E1** latch schema + `compute_effective_halt` (fail-CLOSED) → **E2** IE arbiter set/clear API with domain-scoped authz (deny cross-domain clears; emit UnauthorizedClearAttempt) → **E3** Telegram boundary (`/pause`,`/resume` → manual_pause only; `/ack`, `/request-risk-clear` = request record, no clear) → **E4** dual-read legacy compatibility (fail-safe OR; legacy-write ban lint) → **E5** hash-chained latch audit + `/status` view → **E6** backup/recovery (add latch doc to iCloud MUST_HAVE + DR + encrypted set; restore drill with fail-safe interpretation) → **E7** migration (preflight → dual-read parity → cutover → rollback → removal criteria) → **E8** safety proof (drills per latch, unauthorized-clear denial, reboot/corrupt fail-CLOSED, concurrency, no-threshold-change assertion).
> Gate: every PR must (a) prove no Product-Studio path clears an IE latch, (b) keep thresholds/money-path byte-identical, (c) pass the kill-switch drill. Any ambiguity → owner card, do not guess in the risk domain.

---

## CLOSURE-005A — resolved design (supersedes earlier persistence/audit/impl choices)

**Canonical locations (§1):** ADR = `docs/decisions/ADR-054-kill-switch-authority.md` (existing ADR convention). **RFC convention established: `docs/rfcs/RFC-<n>-<slug>.md`** (this is the first RFC; single root; recorded here + in ExecutiveSummary — no competing RFC roots). The prior root `RFC/` and `Decisions/` copies were removed after content was preserved here; no decision history lost.

### §2 Persistence — DECISION: **Model B (separate latch files)**
Four files, each single-owner + single-writer-API + its own lock:
```
data/kill_switch/manual_pause.json     (owner: PRODUCT_STUDIO)
data/kill_switch/risk_kill.json        (owner: INVESTMENT_ENGINE)
data/kill_switch/threat_kill.json      (owner: INVESTMENT_ENGINE)
data/kill_switch/execution_kill.json   (owner: INVESTMENT_ENGINE)
```
| Criterion | Model A (aggregate doc, 1 global lock, CAS) | **Model B (separate latch files)** |
|---|---|---|
| Lost-update safety | good (CAS/revision) | **good** (each latch = single writer, own lock; no cross-latch RMW) |
| Atomicity | whole-doc atomic | **per-latch atomic** (tmp+os.replace) |
| Cross-latch consistency | strong (one doc) | derived via reducer (eventually-consistent; safe because effective = OR) |
| Recovery | one doc to restore | per-file; missing/corrupt latch ⇒ that latch treated ACTIVE (fail-CLOSED) |
| Migration | moderate | **low** (add files incrementally; legacy dual-read) |
| Observability | one doc | **per-latch history + owner clear** |
| Testability | mock 1 API | **mock per-latch API** |
| **Ownership enforcement** | weak (all domains share one API/doc) | **strong — PS writes ONLY manual_pause.json; engine files PS never touches (OS perms can enforce)** |

**Chosen: Model B** — decisive for the security goal (least-privilege ownership at the file boundary). The forbidden **"single document + per-latch locks"** combination is explicitly NOT used: a single doc would take ONE global lock (Model A); per-latch locks require per-latch files (Model B). Requirements adopted: one writer API per latch; **no direct writes** (all mutations via the latch API); each latch has `active` + a monotonic `revision`; writer does compare-and-check on `revision`; atomic replace; **missing/corrupt latch ⇒ fail-CLOSED (that latch = ACTIVE)**.

### §5 Effective-state reducer — one owner, derived-only
- **Reducer owner:** the **Investment Engine** (`spa_core/governance/`), the only component that computes `effective_halt`.
- **Rule:** `effective_halt = OR(normalize(manual_pause), normalize(risk_kill), normalize(threat_kill), normalize(execution_kill))`.
- **Input paths:** the four latch files. **Schema validation:** each latch parsed + schema-checked; **unknown schema / corrupt / missing ⇒ normalize to ACTIVE (fail-CLOSED)**; **stale latch** (updated_at older than a max-age for a latch that must refresh, e.g. threat) ⇒ treated ACTIVE. **Read caching:** short TTL read cache allowed for readers; the authoritative recompute happens in the engine each cycle. **Derived status output:** the pure reducer computes `effective_halt` and performs **no I/O**; a later **T5 cache-writer / I/O layer** may persist `data/kill_switch_effective.json` from the reducer result. The derived cache has **Authority NONE** and is **never an authoritative writable state** — no component may mutate a latch by writing the derived snapshot; writers use the per-latch API only. (This replaces the legacy `kill_switch_status.json` mirror role.)

### §3 Audit — DECISION: **Audit B (dedicated serialized event file)**
`data/kill_switch_events.jsonl` — **isolated from the 25-producer shared `audit_chain.jsonl`** (which has an un-serialized whole-file RMW lost-update risk, F-CON-1; it must NOT be the safety-critical kill writer target).
| Field | Design |
|---|---|
| Writer | a single `kill_audit.append()` API (the ONLY writer of this file) |
| Lock / txn | one global kill-audit lock (`flock` on `kill_switch_events.jsonl.lock`) around read-tail → append → replace |
| Sequence number | monotonic `seq` (last seq + 1, read under lock) |
| Previous hash / event hash | SHA-256 `prev_hash` (genesis `0*64`) + `entry_hash` over canonical-JSON event |
| Fsync | fsync the file + directory after append, before releasing the lock |
| Crash recovery | on start, verify chain tail; a torn last line is truncated to the last valid `seq`/hash |
| Duplicate correlation_id | idempotent — a repeated (latch, correlation_id, action) is a no-op (deduped) |
| Verification | `verify_kill_audit` (re-derive the chain) + fold into `scripts/verify_spa.py` |
| Backup coverage | add `kill_switch_events.jsonl` + the 4 latch files to the iCloud MUST_HAVE + DR + encrypted set |
- **Tamper-evidence is only claimed because writes are serialized** (single writer + global lock + fsync) — no concurrent lost update is possible. Optional read-only mirror into `audit_chain.jsonl` is allowed but is NOT the source of truth.

### §4 Clear-authority semantics (per latch)
| | manual_pause | risk_kill | threat_kill | execution_kill |
|---|---|---|---|---|
| Who may SET | Operator (Telegram `/pause`) | Risk engine (drawdown ≥ HARD) | threat_reactor (CRITICAL held-protocol) | IE execution/governance (readiness fail) |
| Auto-clear? | **NO** (KS-13 — only explicit `/resume`) | **YES, deterministic** (see below) | **NO** (reactor may NOT self-clear) | **NO** |
| Who may CLEAR | Operator (`/resume`) only | Risk engine only (auto) | **IE governance only** (not the reactor, not the operator) | IE governance/execution only |
| Who may REQUEST clear | — | Operator `/request-risk-clear` (advisory) | Operator `/request-risk-clear` | Operator `/request-risk-clear` |
| Who may APPROVE clear | n/a (operator-owned) | engine (deterministic) | **IE governance + (D-03) owner ack** | IE governance + owner (D-07) |
| Health conditions | n/a | drawdown < re-arm band | threat absent | readiness restored |
| Min stable period | none | **N healthy cycles (hysteresis, ARB: 3)** | **clean period (ARB: ≥1 cycle + cooldown)** | readiness stable |
| Required evidence | operator identity | drawdown snapshot (< re-arm) | threat-cleared evidence (threat id resolved) | readiness audit pass |
| Cooldown | none | re-arm band (hysteresis prevents flap) | cooldown before clear | cooldown |
| Emergency override | none needed (arming is safe) | **PROHIBITED** — no manual override of risk_kill | prohibited via operator | prohibited via operator |
| Recovery from corruption | corrupt ⇒ ACTIVE (fail-CLOSED) | corrupt ⇒ ACTIVE | corrupt ⇒ ACTIVE | corrupt ⇒ ACTIVE |

- **manual_pause:** `/pause` sets, `/resume` clears; no auto-clear.
- **risk_kill — deterministic automatic clear = YES** (the engine owns it): clears only after **hysteresis** (drawdown recovers below a re-arm band that is strictly tighter than the trip band) sustained for **N healthy cycles** (ARB default 3); **owner acknowledgment is recorded but is NOT required** for the deterministic clear; **manual/operator override is PROHIBITED** (KS-02).
- **threat_kill:** the threat_reactor **may NOT clear it itself** (set-only); clear requires **IE governance** after a **clean period** with **threat-cleared evidence**; whether an additional **owner human approval** is required = **D-03** (ARB: owner `/ack` acknowledgment, engine-authorized clear).
- **execution_kill:** set by IE execution/governance; **does NOT auto-clear**; clear requires **explicit owner approval** (D-07) — this latch guards real-capital arming and stays fail-CLOSED by default.

### §8 Owner decision packet (standalone — Yurii can decide without reading the whole RFC)
| ID | Question | ARB recommendation | Alternative | Safety consequence | Operational consequence | Owner response |
|---|---|---|---|---|---|---|
| D-01 | Telegram `/resume` clears `manual_pause` only? | **YES** | allow `/resume` to clear engine latches (status quo) | YES ⇒ PS cannot remove IE protection (safe); NO ⇒ PS can clear a risk kill (unsafe) | YES ⇒ operator still pauses/resumes freely | ______ |
| D-02 | Who may clear `threat_kill`? | **IE governance only** (not reactor, not operator) | reactor self-clears | operator/reactor clear risks premature un-halt | IE-owned clear adds a governance step | ______ |
| D-03 | Can `risk_kill` clear automatically? | **YES — deterministic, hysteresis + N healthy cycles**; owner ack recorded, not required | require owner approval to clear | auto-clear with hysteresis avoids flap; manual-only risks stuck-halt | fewer manual interventions | ______ |
| D-04 | Aggregate document or separate latch files? | **Separate latch files (Model B)** | single aggregate doc (Model A) | Model B enforces per-latch ownership at the file boundary | Model B = simpler migration + per-latch observability | ______ |
| D-05 | Dedicated kill audit or shared audit writer? | **Dedicated serialized `kill_switch_events.jsonl` (Audit B)** | reuse shared `audit_chain.jsonl` | shared chain has a lost-update risk (F-CON-1) → not tamper-safe for kill | dedicated file = clean verify + backup | ______ |
| D-06 | Missing/corrupt state behavior? | **fail-CLOSED (that latch = ACTIVE; effective HALTED)** | fail-open (treat as inactive) | fail-open could silently disable protection | fail-CLOSED may require a manual re-assert after corruption | ______ |
| D-07 | Two-step request→approve for engine-latch clears? | **YES for threat_kill + execution_kill; risk_kill clears deterministically by the engine** | one-step clears | two-step prevents accidental/unauthorized un-halt | slightly slower engine-latch clears | ______ |

*(`Owner response` intentionally left blank — for Yurii to fill.)*

### §7 Implementation status
The implementation prompt in the Appendix is a **NON-EXECUTABLE DRAFT, BLOCKED ON ADR-054 ACCEPTANCE**. The immediate next task (post owner approval) is **`PHASE1-KILL-SWITCH-IMPLEMENTATION-PLAN-005B`** — prepare the exact implementation plan only (still design-only). No code, state, thresholds, or config are changed by this RFC or by 005B.

---

## CLOSURE-005B — safety mechanics (refines CLOSURE-005A; ADR stays PROPOSED)

### §1 Authoritative read path — DECISION: **Read Model A (direct reduction)**
Safety-critical Investment-Engine consumers read the **four latch files directly** and reduce; they never trust a derived snapshot.
```
read manual_pause.json, risk_kill.json, threat_kill.json, execution_kill.json
validate each schema + version
normalize each latch  (missing | unreadable | corrupt | unknown schema_version ⇒ ACTIVE)
HALTED = OR(all normalized latches)
```
| Criterion | Read A (direct reduction) | Read B (revision-verified snapshot) |
|---|---|---|
| stale-false prevention | **strong** (always reads source latches) | strong only if reader re-validates snapshot-vs-latch revisions |
| crash consistency | **simple** (no snapshot to desync) | snapshot can lag/desync a crash between latch write and snapshot write |
| complexity | **low** | higher (revision vectors, global mutation lock on read path) |
| read latency | 4 small reads (bounded; short TTL cache allowed for non-safety readers) | 1 read + revision check |
| testability | **high** | medium |
| recovery | trivial (source is the latches) | snapshot rebuild needed |
| operational clarity | **high** | medium |

**Chosen: Read Model A** for v1 (ARB preference). **`kill_switch_effective.json`, if written, is ONLY an observability cache** (Classification=DERIVED_CACHE, Authority=NONE); **safety consumers MUST recompute from the latch files and never decide on the cache alone.** A stale/missing/corrupt snapshot can NEVER un-halt execution — the reducer runs over the source latches each cycle and fails-CLOSED on any latch problem.

### §2 Mutation transaction (Model B latch + Audit B event) — exact sequence
```
1  authorize actor        (domain-scoped: PS may only touch manual_pause; IE owns risk/threat/execution)
2  validate command       (schema, allowed transition for this latch)
3  acquire locks          (LOCK ORDER: latch-file lock → global kill-audit lock; always this order to avoid deadlock)
4  read current latch      (+ current revision)
5  check revision          (compare-and-check; mismatch ⇒ abort, no write)
6  apply transition        (compute new latch doc, new_revision = old+1)
7  atomic write latch       (tmp + fsync + os.replace)  → state durable
8  fsync latch dir
9  append serialized audit  (kill_audit.append under the held global audit lock; seq, prev_hash, event_hash)
10 fsync audit file + dir    → audit durable
11 verify audit append       (re-read tail: seq + entry_hash match)
12 release locks (audit, then latch)
13 return result
```
- **A latch mutation is SUCCESS only after BOTH the latch write (7-8) AND the audit append (9-11) are durable** — never return SUCCESS before durable state write **and** durable audit result (safety requirement).
- **State written but audit NOT written (step 9/10 fails):** the mutation is **NOT** reported SUCCESS; the operation enters `RECOVERY_REQUIRED`; because effective-halt is recomputed from the latch (which did change), the system remains **fail-safe** (a set stays set; a clear that could not be audited is treated as **not durably cleared** → the reader still sees the pre-clear latch on the next reconcile, and the un-audited clear is rolled forward only after audit succeeds). Net: **no un-audited clear is ever trusted.**
- **Audit written but operator reply lost (step 13 return lost):** state + audit are durable and correct; the operator simply re-queries `/status` (idempotent) — no double effect because of correlation_id dedup.
- **Duplicate command:** a repeated `(latch_id, correlation_id, action)` is a **no-op** (deduped at step 2 against the audit's last events) — replay-safe.
- **Lock ordering:** latch-file lock first, then the single global kill-audit lock — consistent order everywhere. **A single global mutation lock is NOT required** in addition (per-latch locks + the global audit lock suffice, because writers are partitioned by latch and the audit is the only shared serialization point).

### §3 Non-destructive audit recovery — NO automatic truncation
The design **removes** any automatic "truncate torn last line." On an invalid tail:
```
detect invalid tail (seq gap / hash break / torn JSON)
PRESERVE original bytes untouched
copy corrupt file → kill_switch_events.corrupt.<timestamp>   (quarantine; record size + sha256)
record file metadata + checksum in kill_switch_events_recovery.json
identify last valid seq/hash (read-only scan; do NOT modify the live file)
enter RECOVERY_REQUIRED (system fail-CLOSED / HALTED)
require an AUTHORIZED recovery action (owner/IE governance) to proceed
on recovery: start a NEW linked chain SEGMENT whose genesis prev_hash = last-valid entry_hash (chain continues, quarantined segment retained)
```
**Artifacts — PINNED by D-11 (ACCEPTED WITH MODIFICATION 2026-07-22):** `kill_switch_events.jsonl` (live, name never changes), `kill_switch_events.corrupt.<TS>` (quarantined bytes; `<TS> = YYYYMMDDTHHMMSS.ffffffZ`, collisions ⇒ `.1/.2/…`, existing quarantine never overwritten, **atomic rename only**), `kill_switch_events_recovery.json` (recovery metadata — **Schema v1, exactly 16 mandatory fields**: schema_version, state ∈ {RECOVERY_REQUIRED, RECOVERING, RECOVERED}, reason ∈ {CORRUPT_BYTES, CHAIN_INVALID, MISSING_SEGMENT, UNCERTAIN_DURABILITY}, detected_at, detected_by, corrupt_file, corrupt_sha256, corrupt_size, last_valid_sequence, last_valid_event_hash, segments[], actor_domain, actor_id, authorization_result, created_at, updated_at; D-08 canonical rules). State machine: `auto→RECOVERY_REQUIRED →authorized→ RECOVERING →authorized→ RECOVERED`; new incident ⇒ auto back to RECOVERY_REQUIRED after archiving prior metadata; INVALID: REQUIRED→RECOVERED, RECOVERING→REQUIRED, RECOVERED→RECOVERING. Segments exist ONLY from recovery (no proactive rotation); post-recovery first event = `event_type=RECOVERY_REQUIRED`; **a non-genesis continuation is valid ONLY when justified by RECOVERED metadata**. ARB modifications: recovery metadata is **NOT audit authority**; **the reducer never reads recovery.json** (safety/committed reader maps it to `NormalizedLatchState.RECOVERY_REQUIRED`; reducer stays pure); retention → D-10. **Corrupt audit evidence is never destroyed; recovery is authorized, not automatic; the system stays HALTED until recovery completes.**

### §4 Audit transaction semantics (per event)
**Event Schema v1 (D-09, ACCEPTED WITH MODIFICATION 2026-07-22) — exactly 20 mandatory fields:**
`schema_version` (int `1`) · `sequence` (int ≥1, monotonic — ordering authority) · `event_id` (UUIDv4, injectable generator) · `event_type` ∈ {`MUTATION_PREPARED`, `STATE_WRITTEN`, `MUTATION_COMMITTED`, `ABORTED`, `RECOVERY_REQUIRED`} · `transaction_id` (UUIDv4) · `correlation_id` · `latch_id` · `action` (`SET`|`CLEAR`) · `old_revision` · `new_revision` · `old_active` · `new_active` · `state_file_hash` · `reason_code` (`^[a-z][a-z0-9_]*$`) · `actor_domain` · `actor_id` · `authorization_result` · `timestamp` (UTC RFC3339, 6-frac `Z`) · `previous_hash` (genesis `"0"*64`) · `event_hash` (sha256 over the D-08 canonical of sequence/timestamp/event_type/payload/previous_hash). Canonical serialization = D-08 rules. `AUDIT_WRITTEN` is a **marker status only, NOT an event type** (D-09 Q1). Hash-primitive reuse (D-09 Q2): `compute_entry_hash`/`verify_chain` logic from `spa_core/audit/hash_chain.py` ALLOWED; `hash_chain.append()` and the shared `audit_chain.jsonl` multi-writer path FORBIDDEN.
- **Single writer API** (`kill_audit.append`) is the ONLY writer of the event file; **one global audit lock** (flock) around read-tail→append→replace; **fsync** file+dir before releasing; **duplicate correlation** ⇒ no-op; **chain verification** = re-derive `prev_hash`/`event_hash` (`verify_kill_audit`, folded into `verify_spa`); **chain-segment linking** = a new segment's genesis `previous_hash` = the last valid segment's `entry_hash` (see §3); **backup inclusion** = the live event file + all segments + the 4 latch files added to iCloud MUST_HAVE + DR + encrypted set; **failure behavior** = any append/fsync/verify failure ⇒ mutation not SUCCESS + `RECOVERY_REQUIRED`. **Tamper-evidence is claimed ONLY because writes are serialized** (single writer + global lock + fsync) — no concurrent lost update is possible.

### §5 Initialization vs runtime failure (states)
States: `UNINITIALIZED · INITIALIZED · MIGRATING · OPERATIONAL · RECOVERY_REQUIRED · CORRUPT`.
- **First initialization** — only via **owner-approved migration** (not automatic): create all four latch files, pin schema + initial revisions, write an `initialization` audit event; **until initialization completes the system is HALTED** (UNINITIALIZED ⇒ fail-CLOSED). **Completed by:** owner/IE governance (the migration runner), never Product Studio.
- **Runtime missing/corrupt latch** (post-init): that latch = **ACTIVE**, system = **HALTED**, state = **RECOVERY_REQUIRED**; distinguished from UNINITIALIZED because the other latches + audit exist. **Recovery completed by:** IE governance (owner-authorized), never the operator transport.
- **Legacy migration:** legacy `active=true` ⇒ create an **`unknown_or_legacy` halt condition** on a fail-CLOSED latch that **Product Studio cannot clear** (only IE governance, after evidence). Missing/ambiguous legacy ⇒ HALTED.

### §6 Reducer ownership
- **Module owner:** Investment Engine — `spa_core/governance/kill_switch_reducer` (the ONLY component computing `effective_halt`).
- **Allowed callers:** IE readers (cycle_runner, monitors) call the reducer; Product Studio may READ the derived cache but never calls a mutation via it.
- **Input files:** the four latch files. **Schema validator:** per-latch schema+version check. **Revision handling:** reducer reads latest revision; does not write latches. **Missing ⇒ ACTIVE · corrupt ⇒ ACTIVE · unknown schema_version ⇒ ACTIVE** (fail-CLOSED). **Effective-halt result:** boolean + per-latch breakdown. **Observability output:** `data/kill_switch_effective.json` = **Classification `DERIVED_CACHE`, Authority `NONE`** — consumers must not decide on it alone.

### §7 Owner decision packet — updated D-04 & D-05 (D-01/02/03/06/07 unchanged)
| ID | Question | ARB recommendation | Owner response |
|---|---|---|---|
| D-01 | Telegram `/resume` clears `manual_pause` only? | **YES** | ______ |
| D-02 | Who may clear `threat_kill`? | **Investment-Engine governance only** (not reactor, not operator) | ______ |
| D-03 | Can `risk_kill` clear automatically? | **YES — deterministic, hysteresis + N healthy cycles**; owner ack recorded, not required; manual override PROHIBITED | ______ |
| **D-04** | Separate latch files confirmed. Should safety readers use **direct reduction** or **revision-verified snapshot**? | **Direct reduction (Read Model A)** — readers recompute from latch files; snapshot is cache-only | ______ |
| **D-05** | Dedicated serialized audit confirmed. Should corrupt audit tails be **preserved and require authorized recovery** (no auto-truncate)? | **YES** — quarantine bytes, fail-CLOSED, authorized recovery, new linked chain segment | ______ |
| D-06 | Missing/corrupt state behavior? | **fail-CLOSED** (that latch = ACTIVE; effective HALTED) | ______ |
| D-07 | Two-step request→approve for engine-latch clears? | **YES** for `threat_kill` + `execution_kill`; `risk_kill` deterministic | ______ |

### §8 Cross-reference correction
- `threat_kill` clear authority = **D-02** (who clears) + **D-07** (two-step request→approve), **NOT D-03**. D-03 governs **`risk_kill` automatic clear** only. The earlier RFC §4 text that tied threat_kill owner-approval to "D-03" is corrected: threat_kill owner acknowledgment/approval maps to **D-02/D-07**; risk_kill auto-clear maps to **D-03**.

---

## CLOSURE-005C — transaction consistency (supersedes 005B locking; ADR stays PROPOSED)

Fixes two gaps: **fractured reads** across the four latch files, and the **state↔audit cross-file transaction** (two files can diverge without a durable marker).

### §1 Global state lock (single lock for read + mutation)
One lock guards ALL safety-critical operations: `data/kill_switch/.state.lock`.
- **Readers:** acquire **SHARED** lock → read+validate all four latch files **+ the transaction marker** → compute OR → release.
- **Writers:** acquire **EXCLUSIVE** lock → run the full mutation transaction (§5) → release.
- **Per-latch locks are REMOVED** (superseding 005B's per-latch locking) — they may not replace the global lock; if retained at all, only *after* the global lock. **Uniform lock order:** `global state lock → (optional latch lock) → audit lock`. This is the single serialization point for both reads and writes.

### §2 Fractured-read prevention (proof)
Scenario: a writer transitions `risk_kill: true→false` and (separately) `manual_pause: false→true`.
- Because **every mutation holds the EXCLUSIVE global lock for its entire transaction**, and **every reader holds the SHARED global lock for its entire read**, a reader observes either the complete pre-state or the complete post-state of any single mutation — never a split.
- A reader can therefore **never** observe the impossible `risk_kill=false ∧ manual_pause=false` mid-way combination: those two changes are two separate exclusive-locked transactions; between them at least one latch is active, and within either transaction the reader is excluded.
- **Any lock failure / read failure / schema-validation failure / marker-unreadable ⇒ `HALTED=true`** (fail-CLOSED). The reader's snapshot is all-or-nothing.

### §3 Durable transaction marker (write-ahead)
`data/kill_switch/transaction.json` — written + fsync **before** any latch change.
**Marker Schema v1 (D-09, ACCEPTED WITH MODIFICATION 2026-07-22) — exactly 17 mandatory fields:**
`schema_version` (int `1`) · `transaction_id` (UUIDv4, injectable) · `correlation_id` (`^[A-Za-z0-9_.:-]{1,128}$`) · `latch_id` · `action` (`SET`|`CLEAR`) · `old_revision` (≥1) · `new_revision` (= old+1) · `old_active` · `new_active` · **`old_state_hash`** (sha256 of the OLD canonical latch bytes — owner modification, full before/after transition proof) · `new_state_hash` (sha256 of the NEW canonical latch bytes) · `status` · `actor_domain` · `actor_id` · `authorization_result` · `created_at` · `updated_at` (≥ created_at). Canonical serialization = D-08 rules; additional/missing field ⇒ `UNKNOWN_SCHEMA` ⇒ HALTED.
Statuses (D-09): `PREPARED → AUDIT_WRITTEN → STATE_WRITTEN → COMMITTED` · terminal `ABORTED` · fail `RECOVERY_REQUIRED`. The marker is the **commit point**: a latch change is authoritative only when the marker is `COMMITTED` (written LAST, per D-05/§CLOSURE-005D). Attribution fields are **recorded by T3 only; enforcement is T4** (D-09 Q5).

### §4 Fail-CLOSED pending-transaction semantics
The reader treats the marker as part of the authoritative safety read:
| Marker state | Reader interpretation of the affected latch |
|---|---|
| none / COMMITTED | use the latch file value |
| **pending SET** (action=set, status ∈ {PREPARED,STATE_WRITTEN,AUDIT_WRITTEN}) | **ACTIVE** ⇒ HALTED |
| **pending CLEAR** (action=clear, not COMMITTED) | **old_active (=true) still effective** ⇒ HALTED (the clear is NOT yet in force) |
| unknown / corrupt marker | **ACTIVE** ⇒ HALTED |
**An incomplete CLEAR never un-halts execution.** Pending ⇒ that latch is treated ACTIVE regardless of the latch file's on-disk value.

### §5 Exact mutation protocol (audit-before-state; marker is the commit point)
```
1  authorize actor (domain-scoped)
2  acquire EXCLUSIVE global state lock (data/kill_switch/.state.lock)
3  read + validate current state (all latches + marker)
4  check correlation_id / idempotency (persistent — §8)
5  persist PREPARED transaction marker (transaction.json)
6  fsync marker + directory
7  prepare new latch payload (new_revision, new_state_hash)
8  persist serialized audit evidence  → event = MUTATION_PREPARED (NOT committed)
9  fsync audit file + directory ; set marker.status = AUDIT_WRITTEN (fsync)
10 atomically publish latch state (tmp + os.replace) ; set marker.status = STATE_WRITTEN (fsync)
11 fsync latch file + directory
12 mark transaction COMMITTED (transaction.json) ; append audit event MUTATION_COMMITTED
13 fsync transaction marker (+ audit)
14 release global lock
15 return SUCCESS
```
**Crash-safety (proved for both):**
- **SET:** any crash at steps 5–13 leaves a *pending SET* ⇒ reader treats the latch ACTIVE ⇒ HALTED. Safe (a set that didn't finish still halts).
- **CLEAR:** any crash before step 12 (COMMITTED) leaves a *pending CLEAR* ⇒ reader honors `old_active=true` ⇒ HALTED. The clear takes effect **only** once the marker is COMMITTED (step 12) — so a half-done clear can never un-halt. Safe.

### §6 Failure matrix (crash after each step)
| Crash point | Effective halt | State visible to reader | Audit status | Recovery action | SUCCESS returnable? |
|---|---|---|---|---|---|
| after PREPARED (6) | **HALTED** (pending) | pre-state; marker=PREPARED | none yet | resume/abort under authz | **NO** |
| after audit write (8–9) | **HALTED** (pending) | pre-state; marker=AUDIT_WRITTEN | MUTATION_PREPARED | authorized recovery | **NO** |
| after latch write (10–11) | **HALTED** (pending — marker not COMMITTED) | latch changed on disk but marker≠COMMITTED ⇒ reader uses fail-safe (SET⇒active, CLEAR⇒old active) | MUTATION_PREPARED | authorized recovery: verify hashes, then COMMIT or ABORT | **NO** |
| before COMMITTED marker (12) | **HALTED** | as above | MUTATION_PREPARED | authorized recovery | **NO** |
| after COMMITTED marker (12–13) | new effective state in force | post-state | MUTATION_COMMITTED | none (verify hashes on next read) | **YES** |
| before operator response (14–15 return lost) | new state in force (durable) | post-state | MUTATION_COMMITTED | none — operator re-queries `/status` (idempotent) | already committed |
**Safety invariant: any ambiguity ⇒ HALTED.**

### §7 Audit event semantics
Events: `MUTATION_PREPARED · MUTATION_COMMITTED · MUTATION_ABORTED · RECOVERY_STARTED · RECOVERY_COMPLETED`. **`MUTATION_COMMITTED` is NEVER written before the state is actually published (step 10) and the marker is COMMITTED (step 12).** Because this protocol writes audit *before* state (step 8), that first event is **`MUTATION_PREPARED`** (never COMMITTED). An aborted/failed transaction gets `MUTATION_ABORTED`; recovery is bracketed by `RECOVERY_STARTED`/`RECOVERY_COMPLETED`.

### §8 Persistent idempotency (not process-local)
Keyed on `correlation_id`, resolved from the durable marker + audit chain (never process memory):
- **completed correlation_id** (a COMMITTED transaction exists) ⇒ return the previous committed result (idempotent replay).
- **pending correlation_id** (a non-COMMITTED marker exists) ⇒ resume recovery, or return `RECOVERY_REQUIRED`.
- **same correlation_id with a different payload** ⇒ **reject + append a security audit event** (`MUTATION_ABORTED` with an authorization/anomaly reason).

### §9 Transaction recovery on startup
| Marker on startup | Action |
|---|---|
| none | normal read |
| COMMITTED | verify state hash + audit chain (`new_state_hash` vs latch; `verify_kill_audit`) |
| PREPARED / STATE_WRITTEN / AUDIT_WRITTEN | **HALTED + authorized recovery** (owner/IE governance): re-derive last-valid, then COMMIT or ABORT explicitly |
| corrupt marker | **HALTED + preserve evidence** (quarantine, §CLOSURE-005B §3) |
**Recovery NEVER automatically clears an engine latch** — a pending CLEAR is only completed by an authorized recovery; otherwise it is ABORTED (latch stays active).

### §10 Owner packet additions (D-04, D-05 — appended, blanks preserved)
- **D-04 (append):** *Safety reads use direct reduction under a **shared global state lock** (fractured reads impossible).* — ARB: **YES.**
- **D-05 (append):** *Latch mutation and audit are bound by a **durable transaction marker**; any incomplete transaction is **always fail-closed** (pending SET⇒active; pending CLEAR⇒old-active honored).* — ARB: **YES.**
*(Owner response fields remain blank.)*

---

## CLOSURE-005D — final commit ordering (supersedes the 005C step-order; ADR stays PROPOSED)

Fixes the last transaction-order defect: in 005C the marker COMMITTED and the committed audit event were coincident; here **the marker COMMITTED is the FINAL durable step**, after BOTH audit events are durable.

### §1 Exact commit order (marker COMMITTED written LAST)
```
1  authorize + validate
2  acquire EXCLUSIVE global state lock (.state.lock)
3  read current latch state (+ marker)
4  check persistent correlation_id / idempotency
5  write transaction marker = PREPARED
6  fsync marker + directory
7  append MUTATION_PREPARED audit event
8  fsync audit
9  atomically publish latch state (tmp + os.replace)
10 fsync latch + directory
11 append MUTATION_COMMITTED audit event      (meaning: STATE DURABLE, ready for final commit)
12 fsync audit
13 change transaction marker → COMMITTED        (← THE final durable commit point)
14 fsync marker + directory
15 release global lock
16 return SUCCESS
```
**The marker may become COMMITTED (step 13) ONLY after: latch durable (10) AND MUTATION_PREPARED durable (8) AND MUTATION_COMMITTED durable (12).** Marker COMMITTED can never precede the durable final audit event.

### §2 Audit terminology (one internally-consistent model)
- **`MUTATION_COMMITTED` (step 11) means: "the state payload is durable and ready for final commit."** It is NOT the authoritative commit — **the transaction becomes authoritative only when `marker.status = COMMITTED` (step 13).**
- *(Equivalent naming, if preferred at implementation time: rename the step-11 event to `MUTATION_STATE_DURABLE` and append a separate post-commit `MUTATION_COMMITTED` acknowledgment for observability only. This RFC uses the first model — step-11 `MUTATION_COMMITTED` = state-durable-ready; marker COMMITTED = authoritative.)*

### §3 Committed-reader verification (never trust `status=COMMITTED` alone)
For a marker with `status=COMMITTED`, the reader MUST verify ALL of:
```
marker.transaction_id  matches
marker.correlation_id  matches
marker.latch_id        matches
marker.new_revision    == latch.revision
marker.new_state_hash  == sha256(latch bytes)
a MUTATION_COMMITTED audit event exists for this transaction_id
that committed audit event's hash chain is valid
```
**Any mismatch ⇒ `effective_halt = true`, state = `RECOVERY_REQUIRED`.** A `COMMITTED` marker is trusted only when the latch bytes/revision AND the durable committed audit event both corroborate it.

### §4 Crash matrix (every commit window)
| Crash window | Marker | Latch | Audit | Effective | Reader/recovery |
|---|---|---|---|---|---|
| **before latch publication** (≤ step 8) | PREPARED (pending) | **old latch remains** | MUTATION_PREPARED maybe | **HALTED** | pending ⇒ HALTED; authorized ABORT |
| **after latch publication, before committed audit** (10–11) | PREPARED/pending | new latch on disk (not authoritative) | MUTATION_PREPARED only | **HALTED** — pending CLEAR honors old `active=true` | authorized recovery may finalize or abort |
| **after committed audit, before marker COMMITTED** (12–13) | pending (not COMMITTED) | new latch durable | MUTATION_COMMITTED durable | **HALTED** | **authorized recovery may verify (§3) and finalize** (set marker COMMITTED) — or abort |
| **after marker COMMITTED** (13+) | **COMMITTED** | durable | durable | committed state may be used (after §3 verification) | normal |
**Any pending/ambiguous marker ⇒ HALTED.** An un-audited or partially-audited clear can never become authoritative.

### §5 Persistent idempotency — completion rule
A correlation_id is **completed** only if ALL hold: `marker.status == COMMITTED` **AND** the latch hash matches (`new_state_hash == sha256(latch)`) **AND** a valid `MUTATION_COMMITTED` audit event exists for that transaction. 
- completed ⇒ return the prior committed result.
- a correlation_id present **only in an audit event but not in a COMMITTED marker** ⇒ **PENDING, not completed** ⇒ resume recovery / `RECOVERY_REQUIRED`.
- same correlation_id + different payload ⇒ reject + security audit event.

### §6 Owner packet — D-05 updated
| ID | Question | ARB recommendation | Owner response |
|---|---|---|---|
| **D-05** | Approve the durable cross-file transaction protocol where the **latch state AND both audit events are durable BEFORE the marker becomes COMMITTED** (marker COMMITTED written last; readers verify marker+latch-hash+committed-audit; any mismatch ⇒ fail-CLOSED)? | **YES** | ______ |

*(D-01…D-04, D-06, D-07 unchanged; owner responses blank.)*
