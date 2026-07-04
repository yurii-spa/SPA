# 08 — DEPLOYMENT / AUTOPUSH / AUTOSYNC

Canonical deep source: `AUDIT_07_DEPLOYMENT_AUTOPUSH_AUTOSYNC.md`.

- 90-min `com.spa.autopush` → `scripts/auto_push.sh` → `push_v*.sh` → `push_to_github.py` → `main`. Heartbeat `logs/auto_push.log`.
- Failure modes: silent `pushed=0` (launchd PATH), missing `--branch`, two copies of `push_to_github.py`, 409 stale-sha.
- **Push to `main` ≠ live deploy** — Cloudflare Pages must rebuild (opaque). #1 recurring failure = GitHub fresh, domain stale.
- Canonical push = `push_to_github_batch.py`; legacy `git_*.sh`/`*.command` helpers are archive candidates (PHASE 12).
