# FILES PROPOSED FOR CONSOLIDATION (proposals only)

| Files involved | Duplication type | Recommended canonical | Risk | Recommended action |
|---|---|---|---|---|
| `RULES.md` + `CLAUDE.md` (FORBIDDEN section) + `docs/06_spa_core_invariants.md` | Triplicated hard rules | `PROJECT_CONTROL/01_MASTER_RULES.md` (new) references all | LOW | make 01_MASTER_RULES canonical; leave others but add "see 01" pointer |
| `scripts/*push*.sh` + `*.command` + `push_to_github.py`×2 (root + scripts/) + `push_to_github_batch.py` | Overlapping push helpers | `push_to_github_batch.py` | MED | keep batch as canonical; keep the two `push_to_github.py` in sync OR archive helpers (verify callers first) |
| `AUDIT_00-07` + prior `docs/audit/*` | Overlapping audits | this `AUDIT_0x` series + `PROJECT_PROBLEM_MAP` | LOW | reference prior audits from PROJECT_CONTROL; don't delete |
| Doc state-numbers scattered (`CLAUDE.md`, `CURRENT_STATE.md`, `README.md`, `SYSTEM_BRIEFING.md`) | Mirrored track/day/gate numbers | `data/golive_status.json` (pinned by `test_doc_drift.py`) | LOW | never hand-edit; the drift test is the guard |
| `HANDOFF_PARALLEL_CC.md` | Handoff instructions | `PROJECT_CONTROL/13_AGENT_HANDOFF_TEMPLATE.md` | LOW | point handoff doc → 13_; keep both |

**Rule:** consolidate = point-to-canonical + add cross-references. Do NOT delete the non-canonical copies in this pass (low-risk archival only, owner-gated).
