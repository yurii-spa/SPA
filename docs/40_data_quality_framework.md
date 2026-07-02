# 40 — Data Quality Framework (§32)

**Status: STUB.** This document is a Priority-3 placeholder for the data-quality framework that gates
research inputs before they inform any card, score, or memo. It lists the framework's dimensions
only; thresholds and detection logic are deferred.

**Scope discipline.** Research-layer only. Fail-closed by default: an input that fails quality checks
is treated as unknown / requiring verification, never silently trusted. Never invent APY/TVL.

**Cross-references (already built — do not duplicate):**
- `spa_core/data_trust/` — existing source-reliability / freshness / validation culture.
- `docs/23_data_architecture.md` — the source catalogue this framework grades.
- `docs/24_database_schema.md` — where lineage/quality metadata will persist.

## Planned contents (outline only)

- **Source reliability** — per-source trust tiering and track record.
- **Freshness** — staleness thresholds per source/cadence; "last-verified" timestamps.
- **Cross-source validation** — agreement checks across independent sources (e.g. APY from
  protocol API vs DeFiLlama); divergence handling.
- **Stale-data detection** — detecting frozen/lagging feeds; fail-closed on staleness.
- **Outlier detection** — flagging implausible APY/TVL/price values for review.
- **Fallback policy** — deterministic fallback behavior; committed-literal only when a live feed is
  unavailable and clearly labelled; never fabricate.
- **Lineage / provenance** — trace every data point to source + timestamp; auditability.
- **Quality gating** — how quality state (pass / warn / fail) blocks or annotates downstream
  research artifacts.

TODO: expand at MVP 2-3 stage.
