# GitHub credentials — inventory (audit 2026-09-30 · capability remeasured 2026-11-28)

> Secrets never live in this file or anywhere in the repo. Tokens are identified by type and by the
> first 10 hex chars of their sha256 (fingerprint), never by value.

## The one credential the system needs

| Keychain item | Type | Fingerprint | Expires | Repo access | Used by |
|---|---|---|---|---|---|
| generic `GITHUB_PAT_SPA` | fine-grained | `bfc62c83a7` | **not declared by the service** (measured 2026-11-28) | `yurii-spa/SPA`, `yurii-spa/defi-checkup` | `push_to_github.py` (canonical writer), `push_to_github_batch.py`, `scripts/safe_site_push.py`, `scripts/auto_push.sh` (`com.spa.autopush`), `scripts/git_push.sh`, `scripts/git_autopush.sh`, `spa_core/tools/github_pusher.py`, `spa_core/utils/keychain.py`, `scripts/morning_work_digest.py`, `scripts/deploy_site_snapshot.py` |
| internet `github.com` / `x-access-token` | **NOT MEASURED since the 2026-11-26 rotation** | unknown | unknown | same | git `credential-osxkeychain` for raw `git push` over https — pinned by `git config --global credential.https://github.com.username x-access-token` |

The token in the table is the one the owner issued **2026-11-26**, after the 2026-11-24 lapse
(ADR-1093); the previous fingerprint was `e2f8065e6a` with a literal 2026-11-24 expiry. This one
declares **no** expiration header, which is why the column says so instead of carrying a date we
made up.

The **internet** item is a separate observation and it is NOT MEASURED: reading it with
`security find-internet-password -s github.com -w` blocks on a Keychain GUI prompt that a
non-interactive session cannot answer (measured 2026-11-28 — the call hung until it was killed).
So whether raw `git push` still authenticates is unknown, and the generic item being alive says
nothing about it: they are two Keychain entries, and the 2026-11-26 rotation is only proven for the
generic one. Unknown is written here as unknown.

`yurii-spa/SPA` is **public**, so fetch/pull (code sync, mirror, pre-push `ls-remote`) need no
credential at all. GitHub Actions use the built-in `secrets.GITHUB_TOKEN` only — no PAT is stored
in repository secrets.

## What this key can and cannot do (measured 2026-11-28, ADR-1128)

"Alive" is not "capable", and the difference cost us the CI verdict. `python3
scripts/pat_rotation_helper.py --probe-capabilities` asks GitHub door by door; a write permission
is probed by a request of the **same shape at a deliberately absent target**, because the grant is
checked before the target exists, so nothing is written in any outcome:

| Door the system uses | Permission | Answer 2026-11-28 | How it was measured |
|---|---|---|---|
| deliver a commit to origin (`git/blobs` · `git/trees` · `git/commits` · `PATCH git/refs`) | Contents: Read and write | **can** | `PATCH /git/refs/heads/__spa_capability_probe_absent__` → `422 Reference does not exist` |
| **order a control CI run about our own commit** (`ci_control_verdict.py`) | **Actions: Read and write** | **CANNOT** | `POST /actions/workflows/ci-control.yml/dispatches` → **`403 Resource not accessible by personal access token`** |
| deliver a workflow file (`.github/workflows/**`) | Workflows: Read and write | not measured | the grant is checked against the commit **content**, so a probe would have to write a workflow file; we know no harmless probe |
| read a file from origin · read a run verdict and artifacts | Contents: Read · Actions: Read | answered by repo visibility | the same GET answers `200` with **no key at all** (the repo is public); a `200` here is visibility, not a grant |

The missing `Actions` permission is why "the CI verdict about my commit" comes out UNMEASURED for
every cycle, and the cause was the instruction below, not the owner: it asked for Contents and
Workflows, and `workflow_dispatch` is gated by **Actions**. Open with the owner:
`owner-decision-novomu-klyuchu-github-ne-hvataet-odnogo` (asked 2026-11-26).

## Removed / unused

| Credential | State | Consumer found | Action |
|---|---|---|---|
| `GITHUB_PAT_MCP_CLAUDE` (fine-grained «spa-mcp-fine-grained», fp `11b2e89da3`) | **expired (401)** | only `~/.zshrc` → `GITHUB_PERSONAL_ACCESS_TOKEN` → Claude Code github MCP plugin (+ a stale `launchctl setenv` copy) | Keychain item deleted; `.zshrc` export commented out; launchctl env unset; plugin `github@claude-plugins-official` disabled. SPA / Studio OS / Bridge never used it. Not re-issued. |
| `GITHUB_PAT_WORKFLOW` + internet `github.com`/`yurii-spa` (classic, `repo, workflow`, **no expiry**, all repos; fp `4a6fc7bb45`) | **removed** — owner cleanup 2026-09-30 | none in code; git helper no longer selects it | Both Keychain items deleted by the owner; verified 2026-09-30: only `GITHUB_PAT_SPA` + `github.com/x-access-token` remain (same token, fp `e2f8065e6a`). |
| token-shaped string in old local `.claude/worktrees/*/docs/governance/ANTI_PATTERNS.md` (classic, fp `46eb12352e`) | dead (401) | none; not on `origin/main` | none needed |

## Rules

- New GitHub automation reads `GITHUB_PAT_SPA` from Keychain at runtime; never a file, never argv.
- Do not add a second PAT for a capability the existing one already has — prove the missing
  permission first (endpoint + 403 body).
- **Rotation asks for FOUR permissions, and the fourth is the one we forgot.** When the owner
  re-issues a fine-grained token (repositories `yurii-spa/SPA`, `yurii-spa/defi-checkup`), the
  permissions are **Contents RW · Workflows RW · Metadata R · Actions RW**, and `Pull requests RW`
  if PR tooling is used. `Actions` is not decoration: `workflow_dispatch` — the only way we order a
  control CI run about our own commit — is gated by it, and `Workflows` is a different permission
  (it governs writing workflow *files*). Every instruction we had, including the rotation card the
  owner followed on 2026-11-26, named Contents + Workflows and omitted Actions; the result was a
  live key that could deliver code and could not order the run that judges it.
- **Acceptance of a rotation is a measurement, not a 200.** After replacing the key, run all three
  questions — they are three, not one: `--check` (calendar) · `--probe-token` (does GitHub accept
  it) · `--probe-capabilities` (can it do what we use it for). Only the third would have caught
  2026-11-28. Hourly, `spa_core/monitoring/system_health_monitor` asks all three.
