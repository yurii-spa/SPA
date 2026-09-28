# Studio OS Core V1 — status (ADR-494, ADR-495)

> **Statel:** L4 · owner: @yurii · acceptance: `spa_core/tests/test_studio_os.py` green (continuity gate +
> registry + decision seam + search + handoff)

The persistent company brain: a fresh AI session continues Earn DeFi from canon without the Owner
re-explaining. **Reuse-first** — an audit found all 12 persistent-project capabilities already exist
(mission ledger, ADRs×419, journal, roadmap, research, health, security). Core V1 adds *projections + one
small registry*, never a new database.

## What was built (spa_core/studio_os/)
| Piece | File | Reuses | Proof |
|---|---|---|---|
| Project Registry | `data/studio_projects.json` + `registry.py` | pointers to ledger/ADR/journal/roadmap | `test_registry_valid_and_has_three_projects` |
| Context Pack (CORE) | `context.py` → `studio_shell/project_context.json` | read_model ← mission ledger, docs/decisions, golive, journal | `test_fresh_session_continuity` |
| Decision seam | `decisions.py` (PROPOSED→Owner→ACCEPTED) | the ADR system (THE decision authority) | `test_decision_seam_proposed_then_owner_accepts` |
| Session handoff | `handoff.py` → `data/studio_handoffs.jsonl` | journal | `test_handoff_roundtrip` |
| Global search | `search.py` (deterministic, local) | all canon (749 objects) | `test_search_finds_cross_object_history` |
| Command Center | `studio_shell/studio_core.js` + `build_studio_core.py` | FounderOS shell | screenshots + overflow=0 |

## Boundaries (unchanged)
Studio OS manages **WORK ON** the Investment Engine; the **Investment Engine owns financial truth** — no
capital/RiskPolicy state is copied into Studio OS canon. Read-only cockpit, no money path. Decisions stay
in the ADR system; work stays in the mission ledger; one Telegram bot.

## Canonical repo/deployment (ADR-494, P0)
`origin/main` on `yurii-spa/SPA` is the ONE truth. The `~/studio-os-scratch/v03` worktree is a **candidate**;
production runs from `~/Documents/SPA_Claude` synced from `origin/main`. Promotion = `push_to_github.py` →
`origin/main` → autosync → **owner-gated** agent restart. Never copy between trees; rollback = revert commit.

## Desktop Command Center
Studio-OS-first nav taxonomy: **STUDIO OS** (Overview · Projects · Decisions · Memory · System) ·
**EARN DEFI** (Capital · Strategies · Aave/Pendle slices · Compare · Voice) · **GRAPH** · **TRACE**.
New flagship screens: **PROJECTS** (project home = Context Pack; understand the project in ≤30s) and
**MEMORY** (deterministic global search over 749 objects — "Position Passport", "kill switch", "canonical
repository"→ADR-494 all resolve). Zero horizontal overflow at 390/430.

## Continuity gate (the hard test)
`test_fresh_session_continuity` gives a worker ONLY the Context Pack and asserts it answers: what we're
building · what's in flight · boundaries · next/priority · key decisions · what NOT to redesign · last work.
Each section carries provenance. **PASS.**

## V1 scope / next increment (honest)
Dedicated WORK / TASK-DETAIL / DECISION-DETAIL / RESEARCH / RELEASES screens are **surfaced via** the Project
Home (Context Pack cards) + existing Decisions/System views in V1; promoting each to its own drill-down page
is the next UI increment. The context/registry/search/decision-seam/handoff **backends are complete and
tested**, so those screens are projection-only work.
