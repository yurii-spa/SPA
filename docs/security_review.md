# Security Review — research layer

> **Task:** SECURITY-001. A **research-layer** security review + a checklist a session runs **before
> committing research-layer work**. The research layer is **advisory / L0–L1 only**: docs, schemas,
> templates, tests, and non-runtime research modules in NEW directories. It never holds keys, never
> signs, never moves funds, and never touches the deterministic execution path.
> **Related:** `docs/06` (invariants B & F), `docs/28` §5/§13 (constraints, STOP-ask),
> `docs/adr/ADR-YL-004` (Risk Scoring advisory), tests SECURITY-002 (`tests/test_no_secrets_in_research.py`),
> SECURITY-003 (`tests/test_no_execution_import.py`).

## 1. Threat model for the research layer

The research layer's job is to *think*, not to *act*. The security posture is therefore about
**containment**: guaranteeing research code cannot become an execution, custody, or secrets surface —
by construction, not by good intentions. The failures that matter:

1. **Custody creep** — research code touching private keys, seeds, signing, or fund movement.
2. **Execution creep** — research code importing `spa_core.execution` or writing execution-owned
   state, so an advisory layer silently gains a live effect.
3. **Gate erosion** — research code weakening, bypassing, or wiring itself into the deterministic
   RiskPolicy / kill-switch.
4. **Secret leakage** — a PAT / token / seed / password written into any file (the 2026-06-10
   incident: a PAT replicated into 90+ files).
5. **Runtime contamination** — research code mutating runtime `data/*.json` or the live paper track.

## 2. Standing invariants (from `docs/06`, non-negotiable)

- **No private keys, seeds, auto-signing, fund movement, or withdrawals** anywhere (B.5).
- **`spa_core/execution/` is NOT imported from read-only / paper / research code** (B.6).
- **No LLM in risk / execution / monitoring / kill paths;** Risk Scoring v2 is **advisory only** and
  never a hard gate, never wired to execution (A.2, ADR-YL-004).
- **RiskPolicy `version` stays "v1.0";** hard gates and the kill-switch are non-overridable and
  owner/ADR-gated (A.1, A.3, A.4).
- **No secrets in files** — read Keychain at runtime; never write PAT/token/seed/password anywhere.
- **Atomic writes** on any state file; **stdlib-only** runtime; **research data in NEW dirs only**,
  runtime `data/*.json` untouched (D.10–D.12).
- **Default autonomy L0/L1** (research / recommendation); no execution automation introduced (E.19).

## 3. Pre-commit checklist (run before committing research-layer work)

Answer YES to every line. Any NO ⇒ **do not commit; STOP and ask the owner** (`docs/28` §13).

- [ ] **No private keys / seeds / mnemonics** introduced, referenced, or handled.
- [ ] **No signing** logic, and **no fund movement / withdrawal / transfer** logic of any kind.
- [ ] **No import of `spa_core.execution`** (nor any execution-domain module) from research code.
      *(Verify: `grep -rn "spa_core.execution" <changed research paths>` → no hits; SECURITY-003 test.)*
- [ ] **No write to execution-owned state** (e.g. `data/adapter_status.json`) and **no write/migrate/
      reshape of runtime `data/*.json`** or the live paper track. New research data goes to **NEW dirs**.
- [ ] **No secrets in any file** — no PAT / token / API key / password / seed literals.
      *(Verify: SECURITY-002 secret-scan test passes; grep for obvious token patterns → none.)*
- [ ] **RiskPolicy not touched** — `version` still `v1.0`; no change to caps, gates, or the kill-switch;
      nothing wired into `spa_core/risk/` or `spa_core/governance/kill_switch.py`.
- [ ] **No LLM in risk / execution / monitoring / kill paths;** any scoring added is **advisory-only**
      and demonstrably not a hard gate (ADR-YL-004).
- [ ] **Change is research-layer only** — docs / schemas / templates / tests / non-runtime modules in
      NEW dirs. It does **not** alter runtime execution, the public dashboard, or deployment.
      *(If it does → STOP and ask, per `docs/28` §13.)*
- [ ] **Atomic writes** used for any state file this change may write (`atomic_save`); no bare
      `open(..., "w")` on a state file.
- [ ] **stdlib-only** for any runtime code touched (documented exceptions: FastAPI/uvicorn/bcrypt/Astro
      for API/cabinet/site only).
- [ ] **Autonomy stays L0/L1** — no execution automation, no autonomous agent in production introduced.
- [ ] **Tests added/updated** for any code change and the suite stays green
      (`python3 -m pytest spa_core/tests/ -q`), with no network and no live-`data/` mutation.

## 4. Escalation

Any checklist item that cannot be answered YES, or any change that would touch runtime execution,
RiskPolicy, the kill-switch, keys/signing, funds, the public dashboard, or deployment, is **out of
scope for the research layer** and must be **escalated to the owner** before proceeding. Do **not**
commit or push without an owner request.
