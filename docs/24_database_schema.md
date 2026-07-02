# 24 — Database Schema (§33)

**Purpose.** Define the target persistent-store schema for the Yield Lab / AI Investment OS research
layer: the store choice, the tables and their key columns, how the L0–L6 evidence model
([`37`](37_apy_realism_and_evidence_standard.md)) and the spread-attribution model
([`adr/ADR-YL-008-unified-yield-lab-mandate.md`](adr/ADR-YL-008-unified-yield-lab-mandate.md)) are
represented, the relationships between artifacts, and the phased migration sequencing.

**Scope discipline — non-migration boundary.** Today the research layer runs on runtime `data/*.json`
state files, and **those remain the source of truth**. A relational store is a later-stage (MVP 2-3+)
concern and is **read-only mirror first**: runtime JSON is **not** migrated into a database unless the
owner explicitly requests it ([`06_spa_core_invariants.md`](06_spa_core_invariants.md), invariant
D-10). This document changes no current storage. **No invented data** — column examples never assert
APY/TVL values.

**Cross-references:** [`23_data_architecture.md`](23_data_architecture.md) (data flow),
[`40_data_quality_framework.md`](40_data_quality_framework.md) (lineage/freshness that these tables
persist), [`25_api_specification.md`](25_api_specification.md) (read surface over these tables),
[`37`](37_apy_realism_and_evidence_standard.md) (evidence model), [`11_strategy_card_system.md`](11_strategy_card_system.md).

---

## 1. Store choice

- **Target:** PostgreSQL for the research layer (relational integrity for card ↔ evidence ↔ decision
  linkage; JSONB columns for semi-structured card bodies).
- **Boundary:** the store backs the *research/decision-support* layer only. It never sits in the
  execution path, never holds keys, and is populated by a read-only mirror of research artifacts
  (fail-closed; if the mirror lags, consumers fall back to the JSON source, doc 23).
- **Determinism:** evidence-level and spread-attribution fields are deterministic bookkeeping, no LLM
  in the write path ([`37`](37_apy_realism_and_evidence_standard.md) rule 10).

---

## 2. Target tables (~30, names indicative — column detail finalized at MVP 2-3)

### Strategy & lifecycle
| Table | Key columns |
|---|---|
| `strategies` | `id`, `name`, `domain` (stable/BTC/ETH), `product_line`, `status` (lifecycle) |
| `strategy_cards` | `strategy_id`→, `card_body` (JSONB), `evidence_level`, `risk_category`, `floor_baseline_pct`, `spread_over_floor_bps`, `unexplained_spread_bps`, `spread_fully_explained` (bool), `last_verified_date` |
| `strategy_lifecycle_events` | `strategy_id`→, `from_status`, `to_status`, `actor`, `ts`, `decision_id`→ |

### Discovery
| Table | Key columns |
|---|---|
| `candidates` | `id`, `source`, `hypothesis`, `intake_ts`, `status` |
| `candidate_screens` | `candidate_id`→, `screen_type`, `result` (pass/warn/fail), `ts` |

### Due diligence
| Table | Key columns |
|---|---|
| `protocols` | `id`, `name`, `chain`, `tier` (T1/T2/T3) |
| `protocol_cards` | `protocol_id`→, `card_body` (JSONB), `governance_model`, `admin_key_status`, `timelock` |
| `protocol_audits` | `protocol_id`→, `auditor`, `report_url`, `findings_summary`, `date` |
| `stablecoins` | `id`, `symbol`, `backing_type` |
| `stablecoin_cards` | `stablecoin_id`→, `backing_disclosure`, `attestation_cadence`, `peg_mechanism` |
| `peg_events` | `stablecoin_id`→, `ts`, `depeg_bps`, `duration`, `note` |

### Yield & evidence
| Table | Key columns |
|---|---|
| `yield_sources` | `id`, `bucket` (borrow-demand / risk-premium / basis-funding / incentives / real-economic — doc 33 §0) |
| `apy_observations` | `strategy_id`→, `taxonomy_type` (advertised/observed/executable/net/sustainable/risk-adjusted — doc 37 §2), `value`, `source`, `ts` |
| `apy_evidence` | `strategy_id`→, `evidence_level` (L0–L6), `promoted_ts`, `basis_vs_incentive_split`, `capital_compression_flag` |

### Risk
| Table | Key columns |
|---|---|
| `risk_scores` | `strategy_id`→, `overall` (0–100, **advisory**), `band` (green/yellow/red), `ts` |
| `risk_subscores` | `risk_score_id`→, `dimension`, `value`, `spread_attribution_score` |
| `red_team_reviews` | `strategy_id`→, `reviewer`, `loss_scenarios` (JSONB), `spread_attribution_finding`, `verdict`, `ts` |

### Capital & portfolio
| Table | Key columns |
|---|---|
| `capital_tiers` | `tier` ($100k…$100M+), `allowed`, `forbidden`, `mandatory_thresholds` (doc 34) |
| `allocations` | `strategy_id`→, `tier`, `target_pct`, `cap_pct`, `ts` (recommendation only, L0/L1) |
| `portfolio_snapshots` | `ts`, `equity`, `positions` (JSONB), `drawdown_pct` |

### Agents & governance
| Table | Key columns |
|---|---|
| `agents` | `id`, `name`, `role`, `autonomy_level` (L0–L5, default L0/L1) |
| `agent_runs` | `agent_id`→, `started_ts`, `ended_ts`, `exit_status` |
| `agent_outputs` | `agent_run_id`→, `artifact_type`, `body` (JSONB) |
| `ic_memos` | `strategy_id`→, `memo_body` (JSONB), `stage` (doc 39), `ts` |
| `approvals` | `ic_memo_id`→, `approver`, `decision`, `ts` |
| `decisions` | `id`, `subject`, `outcome`, `reason_code`, `prev_hash`, `hash` (hash-chained refusal/decision log) |

### Ops, reporting, lineage
| Table | Key columns |
|---|---|
| `alerts` | `id`, `severity`, `subject`, `ts`, `resolved` |
| `reports` | `id`, `period`, `body` (JSONB), `generated_ts` |
| `data_sources` | `id`, `name`, `access_model`, `rate_limit`, `trust_tier` (doc 23/40) |
| `data_lineage` | `datapoint_id`, `source_id`→, `fetch_ts`, `last_verified_date` |
| `ingestion_runs` | `source_id`→, `started_ts`, `rows`, `quality_state` (pass/warn/fail) |

---

## 3. Relationships & modeling

- **Card ↔ evidence ↔ decision.** `strategy_cards` ← `apy_evidence`/`apy_observations` (the numbers) ←
  `data_lineage` (provenance); `strategy_lifecycle_events` and `approvals` reference `decisions`
  (hash-chained) so every status change is auditable.
- **Evidence-level modeling.** `apy_evidence.evidence_level` is an ordered enum L0–L6; promotion is
  one level at a time ([`37`](37_apy_realism_and_evidence_standard.md) §1) — a `strategy_lifecycle_event`
  row records each promotion with actor + timestamp. A public read may render an APY only when the card
  has risk category + last-verified date + yield-source + `evidence_level >= L2`.
- **Spread-attribution modeling.** `strategy_cards.spread_fully_explained` gates advancement to
  Enhanced/Max; `red_team_reviews.spread_attribution_finding` records any unexplained-spread finding
  ([`ADR-YL-008`](adr/ADR-YL-008-unified-yield-lab-mandate.md)).

---

## 4. Migration phases (indicative sequencing)

| Phase | Scope |
|---|---|
| **A** | Schema + **read-only mirror** of existing research artifacts (no write-back to JSON). |
| **B** | Candidate / strategy-card tables. |
| **C** | Protocol / stablecoin due-diligence tables. |
| **D** | Risk-scoring / red-team / evidence tables. |
| **E** | IC / approvals / decision-log (hash-chained) tables. |
| **F** | Agent-runs / reporting / lineage tables. |

**Non-migration boundary (stays JSON, not migrated without owner decision):** the runtime state files
that drive the live cycle and public surfaces — `golive_status.json`, `equity_curve_daily.json`,
`paper_evidence_history.json`, `current_positions.json`, `paper_trading_status.json`,
`audit_trail.jsonl`, and the append-only refusal / decision logs. These remain the source of truth;
the database is a downstream mirror only ([`06`](06_spa_core_invariants.md) D-10).
