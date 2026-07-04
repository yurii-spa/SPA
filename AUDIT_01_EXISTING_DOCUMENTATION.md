# AUDIT_01 — EXISTING DOCUMENTATION DISCOVERY

**Generated:** 2026-07-04 · read-only · PHASE 1
**Principle honored:** this project already has EXTENSIVE documentation — do **not** recreate as if nothing exists. Consolidate/canonicalize instead.

---

## Scale of existing documentation (verified counts)

| Location | Count | Nature |
|---|---|---|
| Root-level `*.md` | 14 | Control / plan / rules / handoff |
| `docs/*.md` | **206** | Yield-Lab research layer (numbered `00`–`60+`) + system docs |
| `docs/adr/*.md` | **55** | Architecture Decision Records (ADR-034, ADR-048, ADR-YL-011…) |
| `docs/audit/*.md` | 2 | Prior audit reports (e.g. `AUDIT_2026-07-03.md`) |
| `MEMORY.md` + `~/.claude/…/memory/*.md` | many | Auto-memory (persists across sessions, per-fact files) |

**There is already a large, layered doc system.** The risk is not absence — it is drift, duplication, and no single unambiguous "read-this-first for BOTH agent systems" entrypoint.

## Key documents (path · purpose · currency · does code follow it · do agents know to read it)

| File | Purpose | Currency | Code follows? | Agents told to read? |
|---|---|---|---|---|
| **`CLAUDE.md`** (root) | THE Claude Code CLI agent charter — architecture, agents, RiskPolicy, FORBIDDEN list, secrets | **Current-ish** but self-admits *doc-drift* (state numbers "may drift", pinned to `golive_status.json`) | Mostly yes (it IS the operating contract) | ✅ auto-loaded every Claude Code session |
| **`MASTER_PLAN_v1.md`** | Source-of-truth for tasks (MP-xxx) → `KANBAN.json` | Current (declared canonical) | Partially (KANBAN concurrently rewritten) | Referenced by CLAUDE.md |
| **`docs/SYSTEM_BRIEFING.md`** | Live operational state, auto-updated every 30 min by `com.spa.system_briefing` | **Freshest state doc** (auto) | It reflects code, not drives it | ✅ CLAUDE.md mandates reading it first |
| **`docs/00_index.md`** | Authoritative index for the Yield-Lab / AI-Investment-OS research layer | Current | The 206 numbered docs formalize existing modules | ✅ per `prompts/claude_code/yield_lab_master.md` |
| **`prompts/claude_code/yield_lab_master.md`** | Charter for the research/docs layer (Builder OS workflow) | Current | Guides research-layer work | Referenced by CLAUDE.md |
| **`HANDOFF_PARALLEL_CC.md`** | Handoff between parallel Claude Code sessions (and, by extension, Dispatch) | UNKNOWN currency — **verify** | N/A | ⚠ not clearly wired into a startup checklist |
| **`RULES.md`** | Global rules | Possibly overlaps CLAUDE.md FORBIDDEN list — **duplication risk** | Partial | Not explicitly loaded |
| **`CURRENT_STATE.md`** | Snapshot of state numbers (track days, gates) | Drifts (pinned by a doc-drift test to `golive_status.json`) | Enforced by `test_doc_drift.py` | Not an agent entrypoint |
| **`README.md`** | Repo readme | UNKNOWN currency — **verify vs PHASE 10** | N/A | Standard first-read, but not agent-specific |
| `GRAND_VISION_v1.md` | Long-term vision ($1M/yr → $100M AUM) | Aspirational, stable | N/A | No |
| `MACMINI_ONBOARD.md` | Mac Mini host onboarding | UNKNOWN currency | Ops | No |
| `PROGRESS.md` / `MEMORY_FACTS.md` / `PUBLIC_API.md` / `ERROR_CODE_REFERENCE.md` / `SECURITY_REMEDIATION.md` | Progress log / facts / public API / error catalog / secrets-incident remediation | Mixed | Partial | No |
| `docs/adr/*` (55) | Decisions (kill-switch two-tier ADR-034/048, **Site Custodian ADR-YL-011**, deploy path) | Authoritative for their decision | Yes (ADRs are honored) | On demand |

## Observations / problems (documentation)

1. **No single canonical "START HERE" spanning BOTH agent layers.** `CLAUDE.md` is the de-facto entrypoint for Claude Code CLI (auto-loaded). Claude **Dispatch** has no clearly-wired equivalent; `HANDOFF_PARALLEL_CC.md` exists but isn't obviously part of a mandatory startup checklist. → This is exactly the gap the proposed `PROJECT_CONTROL/00_START_HERE.md` (later phase) should fill by **pointing to existing docs**, not replacing them.
2. **Duplication risk:** `RULES.md` vs `CLAUDE.md` FORBIDDEN section vs `docs/06_spa_core_invariants.md` — three places assert hard rules. Candidate for canonicalization (Phase 12), not deletion.
3. **Deliberate doc-drift management already exists:** CLAUDE.md + CURRENT_STATE + README are pinned to `golive_status.json` / `kill_switch.py` by `spa_core/tests/test_doc_drift.py`. This is a GOOD existing control — extend it, don't reinvent.
4. **Deploy topology is documented but was costly to discover** — it now lives in `docs/adr/ADR-YL-011-site-custodian.md` ("Deploy path (canonical)") + auto-memory. This should be surfaced into any control index.
5. **Two prior audits already exist** in `docs/audit/` — this new `AUDIT_0x` series should reference/supersede them, not silently duplicate.

## Recommendation (do NOT act yet — PHASE 9+)

Canonicalize the EXISTING entrypoints rather than create a parallel doc system:
- Keep `CLAUDE.md` as the Claude-Code charter; add a one-line pointer to a future `PROJECT_CONTROL/00_START_HERE.md`.
- Make the deploy-topology + source-of-truth (`origin/main`, CF Pages) explicit in that START_HERE.
- Fold `RULES.md` / duplicated rule lists into one canonical rules file referenced by all.
