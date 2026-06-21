# SPA Auto-Push Report — 2026-06-15 02:06 UTC

**Result: Pending work found, but PAT not usable — auto-push skipped (no GitHub writes).**

## Pending scripts
- Scanned: `scripts/push_v*.sh` (versions v809–v823)
- `.push_log` entries: up to and including `push_v822.sh`
- Pending (present but not in `.push_log`): **1**
  - `push_v823.sh` — feat(v8.23): MP-1164 VaultGasBreakevenAnalyzer + MP-1165 VaultDepegRecoveryAnalyzer (353 tests)

## Why nothing was pushed
The PAT file at `~/Documents/SPA_Claude/.github_pat` exists but contains the **placeholder value `ghp_ТВОЙ_ТОКЕН`** ("ghp_YOUR_TOKEN" in Cyrillic), not a real GitHub token:
- 14 characters long (a real classic PAT is `ghp_` + 36 alphanumerics = 40 chars)
- Body contains non-ASCII Cyrillic characters, which are invalid in a GitHub token

Pushing with this value would fail with HTTP 401, so no credential was injected into the browser and **no GitHub API calls were made**.

Note: the actual `push_v823.sh` resolves its token from the **macOS Keychain** (service `GITHUB_PAT_SPA`), not from `.github_pat`. The Keychain is on your Mac and is not reachable from the auto-push sandbox, and the sandbox has no direct network route to `api.github.com` either — so this scheduled agent depends on a valid token being present in `.github_pat`.

## To enable auto-push
Put a real GitHub PAT (with `repo`/`contents` write scope for `yurii-spa/SPA`) into the file:

```
echo 'ghp_<your_real_token>' > ~/Documents/SPA_Claude/.github_pat
chmod 600 ~/Documents/SPA_Claude/.github_pat
```

Alternatively, run `push_v823.sh` yourself on your Mac, where it can read the token from the Keychain.

## File sizes for the pending push (all within limits)
- 8 source/test/data/registry files: 3 B – 102 KB each
- `KANBAN.json`: 595 KB (base64 ~793 KB, under the 1 MB cap)
- `sprint_log.md`: 167 KB
- `scripts/push_v823.sh`: 2.7 KB

No file exceeded the 800 KB / 1 MB-base64 skip threshold.

**Summary: 0 pushed · 0 failed · 1 pending (skipped — PAT placeholder).**
