# FILES PROPOSED FOR DELETION (proposals only — NOTHING deleted)

Risk levels: LOW = clearly obsolete + no references; MED = likely obsolete, verify; HIGH = do not touch.

| Path | Why it appears obsolete | References checked | Risk | Safe now? | Recommended action |
|---|---|---|---|---|---|
| `scripts/git_autopush.sh`, `scripts/git_push.sh`, `scripts/do_git_push.command`, `scripts/fix_and_push.command`, `scripts/install_auto_push.sh`, `scripts/diagnose_push.sh` | Pre-API-push git helpers; canonical push is `push_to_github_batch.py` | not yet grepped for callers | MED | **UNKNOWN** | grep callers; if none → archive to `scripts/legacy/`, don't delete |
| `scripts/DEPLOY.sh`, `scripts/deploy_all.sh` | Prod deploy is Cloudflare Pages (no repo script) | not grepped | MED | **UNKNOWN** | verify unused; archive |
| `claude/project-code-audit-9jyi9l`, `claude/project-overview-hcvh2k` (remote branches) | Stale June-22 Dispatch branches | last commit 2026-06-22 | LOW | **no (owner-gated)** | owner archives/deletes after confirming nothing needed |
| Legacy github.io dashboard artifacts (if any remain: root `index.html` blob, `spa_frontend/`, `deploy-pages.yml`) | Removed 2026-06-28 per CLAUDE.md | verify absence on `main` | LOW | verify first | confirm gone; if present, remove (owner) |
| Owner-gated tracked `data/*.json` (`equity_curve_daily.json`, `golive_status.json`, `paper_evidence_history.json`) | Volatile runtime state in git | legacy dashboard fallback (now gone) | MED | **owner decision** | `git rm --cached` only on owner sign-off |
| Possible duplicate test trees (`tests/` vs `spa_core/tests/`) | CI path confusion suggests duplication | not enumerated | HIGH | **no** | enumerate + diff before ANY action |

**Rule:** nothing here is deleted by this audit. Each needs a reference check + owner sign-off.
