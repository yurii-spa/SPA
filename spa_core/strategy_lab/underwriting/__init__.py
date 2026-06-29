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
