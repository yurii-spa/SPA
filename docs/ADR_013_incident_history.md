# ADR-013 — Incident History Database (FEAT-RISK-002)

**Status:** Accepted
**Date:** 2026-05-27
**Sprint:** v3.13
**Author:** Dispatch orchestrator (autonomous run)
**Supersedes:** —
**Superseded by:** —

## Context

The Risk Layer roadmap (KANBAN update 2026-05-27 21:00) defines a Risk Scoring
Engine (FEAT-RISK-001) that grades every whitelisted protocol on 15 parameters.
One of those parameters is **hack history** — has the protocol been exploited
before, how much was lost, when was the most recent incident, was it patched.

Until now the project had no canonical hack-history input. Risk scoring was
implicit — the operator's mental model. Without a structured incident store
the engine cannot:

* score the "operational history" parameter (incidents per protocol per year);
* derive the "amount-at-risk" parameter (cumulative losses relative to current
  TVL);
* surface a comparable peer-incident in a digest (the lender that just got
  exploited is the third in the same class this year);
* warn that a fresh post-mortem changed a protocol's risk profile (governance
  watcher in FEAT-MON-002 needs an existing record to enrich).

This ADR documents the design of that store and how downstream features will
consume it.

## Decision

Introduce a thin **incidents fetcher module** (`spa_core/data_pipeline/incidents_fetcher.py`)
that owns the canonical schema and one output file (`data/incidents.json`).
No DB tables, no migrations — the file is the source of truth, identical to
how `sky_status.json` and `protocols.json` already work.

### Data source

* **Primary:** DefiLlama hacks API at `https://api.llama.fi/hacks`. Public,
  unauthenticated, free, no rate-limit issues observed in M5.
* **Fallback:** A curated `BOOTSTRAP_INCIDENTS` list embedded in the module.
  Compiled from public post-mortems (rekt.news, project blogs, DefiLlama).
  Covers the highest-signal incidents that touch SPA-whitelisted families
  (Aave/Compound/Curve/Euler/Yearn/Pendle/MakerDAO/Sky/USDC depeg).

The fallback exists because (a) GitHub Actions cron runners occasionally fail
DNS to `api.llama.fi`, and (b) the Risk Scoring Engine must produce a score on
day one — before the first successful refresh.

### Output schema (`data/incidents.json`)

```jsonc
{
  "updated_at": "2026-05-27T20:14:27Z",
  "source": "DefiLlama hacks API (+ bootstrap fallback)",
  "fetched_from_api": false,                // true once a live refresh succeeds
  "total_incidents": 10,
  "total_amount_lost_usd": 40527000000.0,
  "incidents": [
    {
      "id":              "defillama-1234"   // or "bootstrap-<slug>-<year>"
      "protocol":        "Curve Finance",
      "protocol_slug":   "curve-finance",
      "date":            "2023-07-30",
      "amount_lost_usd": 73500000.0,
      "type":            "exploit",         // hack | exploit | rugpull | depeg
      "technique":       "Vyper reentrancy",
      "chain":           "ethereum",
      "source_url":      "https://...",
      "status":          "fixed",           // fixed | ongoing | unknown
      "spa_protocols_affected": ["curve"]   // subset of SPA_PROTOCOL_SLUGS
    },
    ...
  ],
  "by_protocol_summary": {
    "aave":         {"incidents": 0, "total_lost_usd": 0.0, "last_incident": null},
    "aave-v3":      {"incidents": 0, "total_lost_usd": 0.0, "last_incident": null},
    "compound":     {"incidents": 1, "total_lost_usd": 80000000.0, "last_incident": "2021-09-29"},
    ...
  }
}
```

`by_protocol_summary` is pre-initialised for every slug in `SPA_PROTOCOL_SLUGS`
so consumers can iterate without `KeyError`. The slug list is the SPA whitelist
plus closely-watched LP venues (Curve, Uniswap) that feed the S2 strategy.

### Normalisation rules

| Field             | Rule                                                                     |
|------------------|--------------------------------------------------------------------------|
| `protocol_slug`  | lowercase, non-alphanumeric → `-`, trimmed                                |
| `amount_lost_usd`| float; if input < 1e6 and > 0, treated as millions and ×1e6              |
| `date`           | `YYYY-MM-DD`; accepts ISO-8601, unix seconds, unix ms, common date forms |
| `type`           | tokenised substring match (`rug`→rugpull, `depeg`→depeg, `hack`/`phish`→hack, else exploit) |
| `spa_protocols_affected` | substring match (both ways) against `SPA_PROTOCOL_SLUGS`         |

### Determinism

Output is sorted by `(date DESC, protocol_slug ASC)`. Duplicates collapsed by
`(protocol_slug, date, technique)` — the record with the higher
`amount_lost_usd` or non-empty `source_url` wins. Two consecutive runs against
the same upstream data produce a byte-identical file.

## Integration plan

1. **This sprint (v3.13)** — ship the fetcher, the seed `incidents.json`, the
   test suite, and this ADR. The CI cron job (existing) will pick up the
   command in a follow-up integration commit when ADR sign-off lands.
2. **Sprint v3.14** — wire `incidents_fetcher.build_incidents_snapshot()` into
   `spa_core/export_data.py` cycle (section 19, after `apy_tracker` section
   18). Cycle adds < 4s and is fully async-safe — no DB locks.
3. **FEAT-RISK-001** consumes `by_protocol_summary[<slug>]` directly. The
   "hack history" sub-score formula will live in the Risk Scoring Engine
   module and is out of scope for this ADR. (Sketch: `score = piecewise on
   (incidents_count, last_incident_age_days, status_fixed_ratio)`.)
4. **FEAT-MON-002 (Governance Watcher)** will read `incidents.json` to enrich
   alerts ("the protocol with the active governance proposal had a $73.5M
   exploit 22 months ago, fixed").

## CLI

```bash
# Refresh from network, write data/incidents.json
python -m spa_core.data_pipeline.incidents_fetcher

# Offline mode — bootstrap only (used by tests / cold-start)
python -m spa_core.data_pipeline.incidents_fetcher --offline

# Dry-run — log the snapshot, do not write
python -m spa_core.data_pipeline.incidents_fetcher --dry-run --verbose
```

Exit code: 0 on success, non-zero only on argument errors. Network failures
fall back to bootstrap and still exit 0 — this is intentional so the cycle
does not halt downstream sections.

## Alternatives considered

1. **SQLite table `incidents`** — rejected. The file is read-only signal for
   downstream consumers; introducing a table adds schema migrations for no
   query benefit (the file is < 200 KB even with 5 years of full DefiLlama
   data).
2. **External hacks.io / rekt.news scraping** — rejected. Both ToS-restrict
   scraping. DefiLlama hacks API is the de-facto public mirror and covers the
   same incidents.
3. **Per-incident commit history (git as the store)** — rejected. Loses the
   ability to recompute summaries on demand and bloats the repo.
4. **LLM-classified incident descriptions** — rejected for this layer. The
   classifier is needed for FEAT-INT-001 (audit findings) where DefiLlama
   does not have structured data. For hacks the API already supplies
   `classification` and `technique` — no LLM call required, which keeps the
   risk-scoring path deterministic.

## Risks

* **Stale data on API outage** — mitigated by bootstrap fallback and
  `fetched_from_api` flag. The Risk Scoring Engine should down-weight (not
  reject) protocols when `updated_at > 7 days old`.
* **Protocol name drift** — DefiLlama occasionally renames entries
  (`Compound` → `Compound V3`). Substring matching is symmetric so both
  match the `compound` slug, but the normalisation regex must stay in sync
  with `defillama_fetcher.POOL_WHITELIST` slugs. The test suite asserts the
  whitelist family is captured.
* **DefiLlama dollar units inconsistency** — the API serves "millions" on the
  `/hacks` endpoint but plain USD on some derivative endpoints. `_safe_amount`
  treats `< 1e6` as millions; the test suite documents the convention.

## Tests

`spa_core/tests/test_incidents_fetcher.py` — 58 deterministic tests, fully
offline, < 0.1s. Covers slugification, type classification, amount/date
normalisation, SPA whitelist matching, dedupe semantics, summary roll-up, HTTP
fetch (mocked), snapshot composition (offline + online merge), and disk
round-trip. All tests pass.

## Rollout

* This ADR ships with the fetcher, tests, and seed `incidents.json` in commit
  `feat(v3.13): FEAT-RISK-002 — Incident History Database`.
* No env flag required — the fetcher is opt-in via CLI / explicit import.
  Wiring into the 4 h cycle (step 2 above) is a follow-up commit and a
  separate ADR sign-off.
* No data migration. The file is written from scratch on every run.

## Acceptance criteria

- [x] `spa_core/data_pipeline/incidents_fetcher.py` exists and is importable.
- [x] `data/incidents.json` exists with the schema documented above.
- [x] Every SPA whitelist slug appears in `by_protocol_summary`.
- [x] CLI `--offline` produces a file when api.llama.fi is unreachable.
- [x] Test suite at 58/58 pass.
- [x] ADR (this file) committed alongside the code.
