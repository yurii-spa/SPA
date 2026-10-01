# Memory & Context Architecture v1

> Decision: [ADR-527](decisions/ADR-527-memory-and-context-architecture-v1.md) · code:
> `spa_core/studio_os/memory/` · index: `data/memory/index.db` (disposable) · CLI:
> `python -m spa_core.studio_os.memory {build|search|assemble|passport|why|lineage|bench|answer-bench|coverage}`.
>
> **AI sessions are temporary workers, not company memory.** A new session (Claude, Codex, a local model)
> must reconstruct the project from files, never from an old chat.

## Layers

| Layer | What it is | Where | Authority |
|---|---|---|---|
| **CANONICAL** | what is CURRENTLY true | `CLAUDE.md`, `.claude/rules/`, `docs/decisions/ADR-*.md`, `docs/ROADMAP.md`, `docs/CAPITAL_ARCHITECTURE.md`, `docs/TRADING_RESEARCH_ENGINE.md`, `architecture/manifest.json` (agents), Bridge `docs/adr` + `docs/releases`, earn-defi `docs/DECISIONS.md`, Company Memory decisions | decides |
| **EPISODIC** | what happened | `docs/journal/`, `docs/ideas/`, tracker cards, Bridge `CURRENT-HANDOFF.md`, Claude auto-memory, the shadow worktree `studio-os-scratch/v03` (UNKNOWN status) | evidence, never a decision |
| **SEMANTIC** | stable facts distilled from evidence, each pointing back to provenance | `architecture/memory_truth.json` (facts, overrides, external agents), agent passports (assembled), lineage (derived) | as strong as its cited evidence |
| **RETRIEVAL** | replaceable index | `data/memory/index.db` (SQLite FTS5/BM25 + light stemming + RU/EN glossary) | none — rebuildable in seconds |
| **WORKING** | per-task context package | `assembler.assemble(task)` → JSON / markdown | never stored |

Allowed sources are an explicit allow-list (`memory/sources.py`). Never ingested: `data/` runtime state,
Keychain, secrets, chat transcripts, personal files, the whole disk. Credential-shaped lines are dropped
before indexing (the build manifest counts them).

## Truth / status semantics

`PROPOSED` · `ACCEPTED` · `ACTIVE` · `SUPERSEDED` · `REJECTED` · `OBSERVED` · `UNKNOWN`. Status comes from
(1) `architecture/memory_truth.json` overrides, (2) supersession written in canon («Supersedes ADR-N»),
(3) the source's own status line, (4) the layer (episodic ⇒ OBSERVED). A chat statement is not a
decision; a proposal is not an accepted decision; a past permission is not a new one. A proposed feature
is not an implemented one: design docs carry a maturity level (L2 = document only … L4 = code + tests +
data, L5 = live agent — `.claude/rules/design-docs.md`). Insufficient evidence ⇒ **UNKNOWN**.

## Lineage

`IDEA → RFC/research → DECISION → TASK → IMPLEMENTATION → TEST/EVIDENCE → RELEASE → OUTCOME`, derived
on demand from identifiers already in use (ADR ids in cards and commit messages, release tags, the
production sync), merged with the ADR-497 overlay. `python -m spa_core.studio_os.memory lineage ADR-525`.

## Agent passports

`python -m spa_core.studio_os.memory why <label> [--live]` assembles a passport from the existing
manifest passport, the agent's own code (ADR refs), the truth registry and launchd — with an origin per
field (EXPLICIT / DERIVED / MEASURED / HEURISTIC / UNKNOWN). No second registry.

## Context assembler

`assemble(task)` returns truth policy, current permissions, matched semantic facts, ranked sources (with
status, SUPERSEDED flagged), passports and lineage for named agents/decisions, and an evidence-sufficiency
verdict (SUFFICIENT / PARTIAL / INSUFFICIENT), capped to a character budget (default 12 000).

## Recovery

The index is derived: deleting `data/memory/index.db` loses nothing — `build` recreates it from the
sources and its manifest records the sources digest. Canonical sources live in git (SPA on origin);
local-only repositories and Bridge/mission state are covered by `scripts/memory_backup.py` (git bundles
+ state snapshots, restore-checked). See ADR-527 for the rehearsal.
