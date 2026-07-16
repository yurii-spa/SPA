"""spa_core/cmo — CMO / Editorial product-layer (owner-directed 2026-07-12, docs/CMO_EDITORIAL_LAYER.md).

Turns the dry auto-journal facts into engaging copy — but ONLY within the honesty floor. This package
is the PRODUCT-promotion layer; it never touches risk/execution/monitoring/kill (LLM forbidden there),
never moves capital, and NEVER auto-publishes (flow B: draft → owner approves → publish).

Build order (docs/CMO_EDITORIAL_LAYER.md §Build order):
  1. honesty_gate  — deterministic, stdlib, fail-CLOSED safety (THIS FIRST).  ← done
  2. editorial_agent — facts → "richer than dry" rewrite behind the gate.
  3. draft store (data/cmo_drafts/) + review surface.
  4. Kanban approval board (owner ask) — later.
  5. publish-on-approval → /blog.
"""
