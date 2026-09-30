# GitHub credentials — inventory (audit 2026-09-30)

> Secrets never live in this file or anywhere in the repo. Tokens are identified by type and by the
> first 10 hex chars of their sha256 (fingerprint), never by value.

## The one credential the system needs

| Keychain item | Type | Fingerprint | Expires | Repo access | Used by |
|---|---|---|---|---|---|
| generic `GITHUB_PAT_SPA` | fine-grained | `e2f8065e6a` | **2026-11-24** | `yurii-spa/SPA`, `yurii-spa/defi-checkup` | `push_to_github.py` (canonical writer), `push_to_github_batch.py`, `scripts/safe_site_push.py`, `scripts/auto_push.sh` (`com.spa.autopush`), `scripts/git_push.sh`, `scripts/git_autopush.sh`, `spa_core/tools/github_pusher.py`, `spa_core/utils/keychain.py`, `scripts/morning_work_digest.py`, `scripts/deploy_site_snapshot.py` |
| internet `github.com` / `x-access-token` | same token | `e2f8065e6a` | same | same | git `credential-osxkeychain` for raw `git push` over https — pinned by `git config --global credential.https://github.com.username x-access-token` |

Proven sufficient (not assumed): the canonical writer pushed `.github/workflows/ci.yml` with it
(commits `b90fad8d`, `c9423e9f`, 2026-09-12), so it carries Contents **and** Workflows write; raw
`git push --dry-run` authenticates with it. `yurii-spa/SPA` is **public**, so fetch/pull (code sync,
mirror, pre-push `ls-remote`) need no credential at all. GitHub Actions use the built-in
`secrets.GITHUB_TOKEN` only — no PAT is stored in repository secrets.

## Removed / unused

| Credential | State | Consumer found | Action |
|---|---|---|---|
| `GITHUB_PAT_MCP_CLAUDE` (fine-grained «spa-mcp-fine-grained», fp `11b2e89da3`) | **expired (401)** | only `~/.zshrc` → `GITHUB_PERSONAL_ACCESS_TOKEN` → Claude Code github MCP plugin (+ a stale `launchctl setenv` copy) | Keychain item deleted; `.zshrc` export commented out; launchctl env unset; plugin `github@claude-plugins-official` disabled. SPA / Studio OS / Bridge never used it. Not re-issued. |
| `GITHUB_PAT_WORKFLOW` + internet `github.com`/`yurii-spa` (classic, `repo, workflow`, **no expiry**, all repos; fp `4a6fc7bb45`) | valid, **over-privileged, now unused** | none in code; git helper no longer selects it | Owner: revoke on github.com and delete both Keychain items (agent was not permitted to write the secret store). |
| token-shaped string in old local `.claude/worktrees/*/docs/governance/ANTI_PATTERNS.md` (classic, fp `46eb12352e`) | dead (401) | none; not on `origin/main` | none needed |

## Rules

- New GitHub automation reads `GITHUB_PAT_SPA` from Keychain at runtime; never a file, never argv.
- Do not add a second PAT for a capability the existing one already has — prove the missing
  permission first (endpoint + 403 body).
- `GITHUB_PAT_SPA` expires **2026-11-24**: before then the owner re-issues a fine-grained token with
  the same scope (repositories `yurii-spa/SPA`; permissions Contents RW, Workflows RW, Metadata R,
  Pull requests RW if PR tooling is used) and replaces BOTH Keychain entries above.
