# 01 — MASTER RULES (hard, non-negotiable)

Read after `00_START_HERE.md`. These bind Claude Code CLI, Claude Dispatch, and every automated agent equally.

## Source-of-truth & git

1. **`origin/main` is truth, not the local tree.** Read origin via the GitHub API. Never trust `git show origin/main` (stale local ref).
2. **NEVER `git reset --hard`, `git checkout .`, `git clean`, `git push`, or `--force` this working tree** without explicit owner sign-off. It drifts 100+ commits from origin and holds 200+ uncommitted files.
3. **Push only via `push_to_github_batch.py` / `push_to_github.py`** (absolute paths). No traditional branch-merge for day-to-day work.
4. **Do not assume GitHub == production.** A push is not a deploy. Cloudflare Pages builds `main`; verify the live site before claiming a deploy.

## Product / risk / execution

5. **Do not modify product DeFi logic, RiskPolicy thresholds, or strategy rules** unless the task specifically asks — and then only with an ADR. RiskPolicy version stays `v1.0` all paper-period.
6. **RiskPolicy is deterministic; LLM FORBIDDEN in risk / execution / monitoring / kill.**
7. **Never import `spa_core/execution/`** from read-only/paper/research code. No private keys, seed phrases, signing, or fund movement anywhere.
8. **Runtime is stdlib-only.** FastAPI/argon2/eth-account/etc. are exceptions confined to the API / academy / cabinet / tests — never the paper/risk runtime.
9. **New strategies are `IS_ADVISORY=True`** until go-live.

## Deploy / agents / data

10. **Do not modify deployment logic or agent schedules** unless the task specifically asks.
11. **Deploy an agent ONLY through `scripts/check_agent_before_deploy.sh`** (exit 0 → log created → then `launchctl load`), ≤3 at a time, always via the bash-wrapper (never direct `python3 -m` in `ProgramArguments` → exit-78), logs to `/tmp/` (never `~/Documents` → TCC exit-78).
12. **Never revive RETIRED agents** (`bot_commands`, `httpserver`, `telegram_daily`/`weekly`, `morning_digest`, `daily-paper-report`) → Telegram-409 / flood.
13. **Do not change the paper-test source of truth** (`data/golive_status.json:real_track_days`) without updating docs + the drift test.
14. **Atomic writes only** (`spa_core.utils.atomic.atomic_save`, same-dir tmp + `os.replace`) for state files. Re-read `KANBAN.json` before writing (concurrent writer).

## Documentation / honesty

15. **Do not create duplicate docs / dashboards.** Update the canonical one. Do not create a parallel control system.
16. **Do not assume docs or code comments are current — check the code / live state.**
17. **APY/track claims require an evidence level** (never present paper/backtest as live; always show source + risk + last-verified).
18. **Do not claim the site is updated unless production freshness was verified** (`15_CANONICAL_COMMANDS`).
19. **Secrets never in files.** Keychain only. Never expose `.claude/settings.local.json`.
20. **Always update `11_CHANGELOG.md` after a meaningful change**, and report changed files + verification results.

## When blocked / uncertain

Write UNKNOWN + how to verify; stop and ask the owner before any hard-to-reverse or outward-facing action (merge, force-push, delete, deploy, external send). Approval in one context does not carry to the next.
