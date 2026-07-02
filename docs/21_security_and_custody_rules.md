# 21 — Security & Custody Rules

> Research-layer document. This is the **consolidated custody-rules reference**: the permanent
> security and custody invariants the whole system — and every future session — preserves. It restates
> and cross-references the authoritative sources; it does not weaken or reinterpret them.
> Authoritative: [`06_spa_core_invariants.md`](06_spa_core_invariants.md) (sections B, A, D) and
> [`security_review.md`](security_review.md) (threat model + pre-commit checklist).
> Related ADRs: [`adr/ADR-YL-005-execution-support-is-non-custodial.md`](adr/ADR-YL-005-execution-support-is-non-custodial.md),
> [`adr/ADR-YL-002-llm-forbidden-in-execution-path.md`](adr/ADR-YL-002-llm-forbidden-in-execution-path.md),
> [`adr/ADR-YL-004-risk-scoring-v2-is-advisory-not-execution-gate.md`](adr/ADR-YL-004-risk-scoring-v2-is-advisory-not-execution-gate.md).

---

## 1. Custody invariants (hard, non-negotiable)

1. **No private-key handling, no seed phrases / mnemonics, no auto-signing, no fund movement, no
   withdrawals** anywhere in the codebase or in any agent (invariant B.5). This is a hard, permanent
   boundary and is not relaxed by any autonomy level ([`20`](20_human_in_the_loop_governance.md)).
2. **Non-custodial by construction.** Execution Support prepares checklists and **unsigned** drafts
   only; a human signs and executes through their own custody / multisig (ADR-YL-005,
   [`19`](19_execution_support.md)). The AI is never a signer and never holds funds.
3. **The AI never sees secrets.** Keys, seeds, and signing material live entirely outside the research
   layer.

## 2. Execution / gate isolation (hard)

4. **`spa_core/execution/` is NOT imported from read-only / paper / research code** (invariant B.6).
   Verify: `grep -rn "spa_core.execution" <changed research paths>` → no hits (test SECURITY-003,
   `tests/test_no_execution_import.py`).
5. **Research code never writes execution-owned state** (e.g. `data/adapter_status.json`); new research
   data goes to **NEW directories only** and runtime `data/*.json` is untouched (invariant D.10).
6. **The deterministic RiskPolicy is the sole hard execution gate** (invariant A.1). `version` stays
   **"v1.0"** for the whole paper period; caps (TVL ≥ $5M/pool; per-protocol 40% T1 / 20% T2; T2 total
   ≤ 50%; APY 1–30%; min cash ≥ 5%) and the two-tier kill-switch (SOFT ∈ [5%,10%) / HARD ≥ 10%
   inclusive) are non-overridable and owner/ADR-gated (A.1, A.3–A.4). No research code wires into
   `spa_core/risk/` or `spa_core/governance/kill_switch.py`.
7. **No LLM in the risk, execution, monitoring, or kill path** (invariant A.2, ADR-YL-002). **Risk
   Scoring v2 is advisory only** and never a hard gate, never on the execution path (ADR-YL-004).

## 3. Secrets hygiene (hard)

8. **No secrets in any file** — never write a PAT / token / API key / password / seed literal into any
   file. Read secrets from **Keychain at runtime** only. (The 2026-06-10 incident: a PAT replicated
   into 90+ files — the reason this rule is absolute.) Verify: secret-scan test SECURITY-002
   (`tests/test_no_secrets_in_research.py`) passes; grep for token patterns → none.
9. **No `push_*.html` / no embedded credentials** in any artifact.

## 4. Wallet separation & multisig (future, owner-gated)

10. **Wallet separation** (segregating operational, reserve, and — if applicable — external-capital
    wallets) and the **multisig topology / threshold** are **future** design, enabled only by an owner
    decision + ADR. They are not implemented by the research layer. Concrete parameters are marked as
    **requiring verification** until set by that decision. When enabled, human signers form the
    multisig; the AI is never a signer ([`19`](19_execution_support.md) §4, ADR-YL-005).

## 5. Platform hygiene (supporting)

11. **Atomic writes only** on state files — canonical `spa_core.utils.atomic.atomic_save` (same-dir
    tmp + `os.replace`); never a bare `open(..., "w")` on a state file (invariant D.11).
12. **stdlib-only** runtime code (documented exceptions: FastAPI/uvicorn/bcrypt/Astro for
    API/cabinet/site only) (invariant D.12).
13. **External capital requires legal review** before acceptance (invariant 18) — a separate gate on
    top of the custody boundary.

## 6. Pre-commit / escalation

- Before committing research-layer work, run the **pre-commit checklist** in
  [`security_review.md`](security_review.md) §3. Any line that cannot be answered **YES** ⇒ **do not
  commit; STOP and ask the owner** ([`security_review.md`](security_review.md) §4,
  [`28_claude_code_master_instructions.md`](28_claude_code_master_instructions.md) §13).
- Any change that would touch runtime execution, RiskPolicy, the kill-switch, keys/signing, funds, the
  public dashboard, or deployment is **out of scope for the research layer** and must be escalated.

> Verification-first: each rule above names its enforcement point (invariant, ADR, or test) so a future
> session can check it, not just assert it. Nothing here invents a fact; unknown parameters are marked
> as **requiring verification**.
</content>
