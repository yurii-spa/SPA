# 12 — KNOWN ISSUES (owner-gated / open)

Canonical deep source: `PROJECT_PROBLEM_MAP.md` §12-14.

- **Opaque CF Pages build** → stale-site root; fix = CF dashboard (owner-only).
- **`SPA_PAT` GitHub secret invalid (401)** → Site Custodian auto-degrade push fails; owner set a valid token.
- **Local git drift** (100+ commits) → never `git reset`/`push` the tree without owner sign-off.
- **`.claude/settings.local.json` leaked a ghp_ token** → keep ignored, rotate.
- Systemic LOCAL-vs-UTC time labels in docs (real cycle 06:00 UTC).
- Stale `claude/*` branches; `feature/academy-course` retire post-merge.
- Script sprawl (legacy `git_*.sh`/`*.command`); possible duplicate test trees.
- Single-host SPOF (Mac Mini) for the API + real offsite.
