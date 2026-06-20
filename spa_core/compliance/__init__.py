"""spa_core.compliance — institutional-grade audit & statement reporting.

Read-only / advisory domain. These modules NEVER modify allocator, risk,
execution, or cycle_runner state. They consume the JSON state files produced
by the daily cycle and the SHA-256 audit hash chain
(:mod:`spa_core.audit.audit_trail_signer`) and emit human- and machine-readable
compliance artifacts under ``data/``.

Pure stdlib. Atomic writes (tmp + os.replace). Exit 0 always (fail-safe).
LLM FORBIDDEN in this domain (SPA security policy).
"""

from __future__ import annotations

__all__ = ["audit_report_generator", "monthly_statement"]
