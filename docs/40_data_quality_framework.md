# 40 — Data Quality Framework (§32)

**Purpose.** Define the data-quality framework that gates research inputs *before* they inform any card,
score, or memo. It sets the dimensions (reliability, freshness, cross-source agreement, staleness,
outliers), the deterministic fallback policy, the lineage requirement, and how a quality state (pass /
warn / fail) blocks or annotates downstream artifacts. This is the gate the source catalogue
([`23_data_architecture.md`](23_data_architecture.md)) feeds and whose metadata the schema
([`24_database_schema.md`](24_database_schema.md)) persists.

**Scope discipline.** Research-layer only. **Fail-closed by default:** an input that fails quality
checks is treated as unknown / requiring verification, never silently trusted. **Never invent APY/TVL.**
No LLM sits in the quality/validation path (deterministic bookkeeping, [`37`](37_apy_realism_and_evidence_standard.md) rule 10).

**Cross-references (already built — do not duplicate):**
- `spa_core/data_trust/` — existing source-reliability / freshness / validation culture.
- `data/rwa_feed.py`, `data/funding_feed.py` — existing fail-closed feed patterns (committed-literal
  fallback flagged; median across venues).
- [`23_data_architecture.md`](23_data_architecture.md) (the source catalogue this grades),
  [`24_database_schema.md`](24_database_schema.md) (`data_lineage` / `ingestion_runs` where quality
  metadata persists), [`37`](37_apy_realism_and_evidence_standard.md) (evidence standard downstream).

---

## 1. Quality dimensions

| Dimension | What it checks | Fail behavior |
|---|---|---|
| **Source reliability** | Per-source trust tier + track record (has the source been accurate/available historically?) | Low-trust source → its value is `warn`, needs a second-source confirm |
| **Freshness** | Value age vs the source's cadence + staleness threshold; last-verified timestamp present | Past staleness window → **downgrade to unknown** (fail-closed) |
| **Cross-source validation** | Agreement across independent sources (e.g. APY from protocol API vs DeFiLlama; price CoinGecko vs CEX) | Divergence beyond tolerance → `warn`, flag for review |
| **Stale-data detection** | Frozen/lagging feed (value unchanged past expected update, or timestamp not advancing) | Treat as stale → fail-closed to unknown |
| **Outlier detection** | Implausible APY/TVL/price (out of the doc-37 sanity band, sudden unexplained spike) | Flag for review; never auto-accept an outlier as a number |
| **Completeness** | Required fields present (source, timestamp, unit) | Missing field → cannot promote past current evidence level |

**Quality state** is the aggregate: **pass** (all dimensions clear), **warn** (a soft check flagged;
usable with annotation), **fail** (a hard check failed; value = unknown, downstream must not render it).

---

## 2. Cross-source validation & tolerance

- Where two or more independent sources exist for the same quantity, they are compared; agreement within
  a documented tolerance → pass; divergence → `warn` and the point is flagged for human review.
- **Unit normalization is a prerequisite** — a known SPA hazard is APY returned as *percent* by some
  adapters and *decimal* by others, and DeFiLlama chain-label variants ("OP Mainnet" vs "Optimism");
  values are normalized ([`23`](23_data_architecture.md)) before any cross-source comparison, or the
  comparison is invalid.
- For feeds that are already multi-source (the 5-venue funding feed), the **median** is the validated
  value and a venue whose value diverges wildly is dropped from the median.

---

## 3. Fallback policy (deterministic)

Explicit, ordered, and never fabricating:

1. **Live value** (passes all dimensions) → use it.
2. **Cached last-good** (within staleness window) → use it with an **age marker**.
3. **Committed literal** — only where one exists and it is **clearly flagged** as fallback (the pattern
   `rwa_feed.py` already uses for the RWA floor).
4. **Unknown / requires verification** — if none of the above apply, the value is unknown; downstream
   must render nothing rather than a fabricated number.

---

## 4. Lineage / provenance

Every data point traces to: **source id · fetch timestamp · last-verified date · quality state**
(persisted in `data_lineage` + `ingestion_runs`, [`24`](24_database_schema.md)). Any card/evidence
figure can therefore be walked back to its origin and its verification date — a precondition for the
evidence standard's "last-verified date required on every public APY" rule
([`37`](37_apy_realism_and_evidence_standard.md) §3).

---

## 5. Quality gating of downstream artifacts

- **fail** → the input is unknown; no card, score, memo, API response, or dashboard cell may render a
  value derived from it (it shows `unknown / requires verification`).
- **warn** → usable but **annotated** (age/divergence marker); may not by itself promote a strategy's
  evidence level.
- **pass** → eligible to inform cards/evidence/scores, still subject to the evidence-level rules
  ([`37`](37_apy_realism_and_evidence_standard.md)).
- **Staleness downgrade is automatic** — if a strategy's underlying data ages past its freshness window,
  its effective claimable evidence level drops until re-verified (fail-closed, matching doc 37 rule 8).
