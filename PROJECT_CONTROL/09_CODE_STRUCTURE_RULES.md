# 09 — CODE STRUCTURE RULES

- `spa_core/` = stdlib-only product runtime. Do NOT add external deps to the paper/risk runtime.
- The ~100-file analyzer family is INTENTIONAL breadth (distinct analyzers) — do NOT "consolidate" it (a prior audit proved it drops coverage).
- Keep canonical long files long: `CLAUDE.md`, `spa_core/api/server.py`, `spa_core/risk/policy.py`, `cycle_runner.py`.
- Atomic writes for state files (`atomic_save`). Re-read `KANBAN.json` before writing.
- No refactor / split / merge of app files until PHASE 12 proves references are safe.
