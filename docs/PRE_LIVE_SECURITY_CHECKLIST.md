# Pre-Live Security Checklist (MUST complete before real-money / live execution)

> The system is PAPER-phase. These items are deferred by decision but are HARD blockers
> for `ready_for_live` (see spa_core/execution/readiness_audit.py). Do ALL before live.

- [ ] **Rotate GitHub PAT** — a `ghp_…` token was pasted in plaintext in chat on 2026-06-24
      (compromised). Revoke at github.com/settings/tokens, issue a new `repo`-scoped token,
      store ONLY in Keychain: `security add-generic-password -s GITHUB_PAT_SPA -a spa -w <new> -U`.
- [ ] Rotate ALL secrets (Telegram bot token, CF tunnel token, JWT secret) and confirm none
      are in any file (re: 2026-06-10 incident — secrets only in Keychain).
- [ ] Custody / MPC 2-of-3 multisig wallet connected (execution dual-control cryptographic).
- [ ] External smart-contract + track-record audit passed (external_audit_attestation.json).
- [ ] ≥30 honest paper-track days + golive 29/29.
- [ ] Second host / HA + offsite DR backup copy (single Mac mini = SPOF today).
- [ ] Full SECURITY review of execution path (keys never logged, fail-safe verified).
