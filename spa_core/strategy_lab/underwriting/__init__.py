# LLM_FORBIDDEN
"""spa_core.strategy_lab.underwriting — Lane C: the productized, hash-anchored,
publicly-verifiable UNDERWRITING REPORT.

The desk's durable moat is NOT a higher yield (proven not to scale) — it is being the party
that can PROVE what it refuses, sold as underwriting-grade risk infrastructure. This package
builds that verifiable artifact: ``data/underwriting/underwriting_report.json`` +
``report_proof.jsonl`` (hash-anchored, every section carries a proof_hash, verify_spa-checkable).

HONESTY RULE (critical): Lane C reads Lane B's verdict (``data/rates_desk/realized_at_size.json``)
VERBATIM — it MUST NOT recompute a happy number. A guard test asserts C's published
``survives_at_aum_usd`` equals B's value byte-for-byte (kills happy-laundering).

stdlib-only · deterministic · fail-CLOSED · atomic · IS_ADVISORY=True · LLM-FORBIDDEN ·
NO execution/ import · owner-gated publication (SPA_UNDERWRITING_PUBLISH, default OFF).
"""
from spa_core.strategy_lab.underwriting.report import (  # noqa: F401
    IS_ADVISORY,
    PUBLISH_FLAG_ENV,
    UNDERWRITING_EVENT_TYPE,
    build_report,
    is_publish_enabled,
    write_report,
)

# Deliberate package-level re-export surface: callers/tests do
# ``from spa_core.strategy_lab.underwriting import build_report``. The ``# noqa: F401``
# above states that intent for flake8, but pyflakes — which the unused-import ratchet
# (``scripts/tests/test_unused_import_ratchet.py``) actually runs — does not honour noqa,
# so the six names read as dead imports there. ``__all__`` says the same thing in the form
# pyflakes understands, and is the convention the ratchet's own docstring names for
# re-exports. Same set, same order: `from … import *` behaviour is unchanged.
__all__ = [
    "IS_ADVISORY",
    "PUBLISH_FLAG_ENV",
    "UNDERWRITING_EVENT_TYPE",
    "build_report",
    "is_publish_enabled",
    "write_report",
]
