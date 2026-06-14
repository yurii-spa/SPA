# Push to GitHub

## One command (when you have your token):

```bash
export GITHUB_TOKEN=ghp_your_token_here
python -m spa_core.tools.github_pusher
```

Or using the shell wrapper:

```bash
export GITHUB_TOKEN=ghp_your_token_here
bash spa_core/tools/push_all.sh
```

Or pass the token inline:

```bash
python -m spa_core.tools.github_pusher --token ghp_your_token_here
```

---

## Get a token (takes 2 minutes):

1. Go to: https://github.com/settings/tokens
2. Click **Generate new token (classic)**
3. Name it something like `spa-pusher`
4. Check the **`repo`** scope (full control of private repositories)
5. Click **Generate token**
6. Copy the token — it starts with `ghp_`

> ⚠️ You only see the token once — copy it immediately.

---

## Dry run (no writes, just checks which files exist):

```bash
python -m spa_core.tools.github_pusher --dry-run
```

---

## What gets pushed: 52 files

| Group | Count |
|-------|-------|
| Frontend (`index.html`) | 1 |
| `spa_core/` Python modules | 28 |
| `spa_core/tests/` | 5 |
| `docs/` | 9 |
| `.github/workflows/` | 1 |
| `run_server.py` | 1 |
| `SPA_sprint_log.md` | 1 |
| `spa_core/requirements.txt` | 1 |

---

## Expected time: ~3–5 minutes

The GitHub Contents API only supports one file per commit, so files are
pushed sequentially. The script prints live progress:

```
  [01/52] pushing index.html … ✓
  [02/52] pushing spa_core/export_data.py … ✓
  …
Push complete: 52/52 files pushed
Repo:      https://github.com/yurii-spa/SPA
Dashboard: https://yurii-spa.github.io/SPA/
```

---

## Troubleshooting

| Error | Fix |
|-------|-----|
| `401 Bad credentials` | Token is wrong or expired — generate a new one |
| `404 Not Found` on repo | Make sure the repo `yurii-spa/SPA` exists on GitHub |
| `HTTP 422` on a file | File content issue — check the file locally |
| `429 Rate Limited` | Script auto-waits 60s and retries |
