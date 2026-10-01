"""Studio OS memory & context — Memory & Context Architecture v1 (ADR-527, docs/MEMORY_ARCHITECTURE.md).

Layers (the model every module here respects):

    CANONICAL   files in git that decide what is CURRENTLY true (ADRs, CLAUDE.md, rules, architecture/,
                roadmap, capital/engine docs, Bridge ADRs/releases, earn-defi decisions)
    EPISODIC    what happened (journals, handoffs, ideas, cards, Claude auto-memory) — never authority
    SEMANTIC    distilled facts that POINT BACK to canonical/episodic provenance (agent passports,
                lineage, the truth registry architecture/memory_truth.json)
    RETRIEVAL   this package's index (data/memory/index.db) — disposable, rebuilt from the sources
    WORKING     the per-task context package (assembler.py) — never stored as memory

AI sessions are temporary workers, not company memory: nothing here reads chat transcripts, and a
retrieved chunk carries its source, layer and status so an old statement cannot pose as a decision.
Stdlib only. LLM FORBIDDEN in indexing, ranking and assembly.
"""
