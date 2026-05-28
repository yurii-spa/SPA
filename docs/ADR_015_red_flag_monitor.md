# ADR-015 — Red Flag Monitor Extended (FEAT-MON-001)

* **Status:** Accepted
* **Date:** 2026-05-28
* **Sprint:** v3.16
* **Owner:** dispatch-orchestrator / red-flag-monitor worker
* **Related:** FEAT-RISK-001 (Risk Scoring Engine), FEAT-RISK-003 (Yield Classifier),
  ADR-013 (Incident History), ADR-014 (Risk Scoring Engine), BL-005 (Telegram alerts)

---

## 1. Context

`spa_core/alerts/risk_monitor.py` already implements four **portfolio-side**
checks (concentration, daily drawdown, APY drop vs last snapshot, low cash
buffer) and a depeg detector. These are sufficient for *internal* state — but
they are blind to **external** signals: TVL hemorrhages, APY anomalies that
look like manipulation rather than rate compression, governance proposals
that change a protocol's risk surface, and token-unlock events that often
precede price dumps and yield collapses.

FEAT-MON-001 is the next layer: an **external Red Flag Monitor** that watches
the public DefiLlama and Snapshot APIs every 4 h cycle and emits a flat list
of red-flag findings keyed by `(protocol, category)`.

The four categories chosen are the highest-signal early-warning sources that
are also (a) free, (b) unauthenticated, and (c) covered by the SPA whitelist
of 10 protocols. Coverage of these four categories is the **last unmet
condition** of go-live criterion 3 (no CRITICAL alerts surface).

## 2. Decision

### 2.1 Module shape

A new module `spa_core/alerts/red_flag_monitor.py` (not an extension of the
existing `risk_monitor.py`, which retains its portfolio-side scope). Both
modules emit the same shape of JSON alert object (severity, category, message,
evidence), so they can share Telegram fan-out plumbing (BL-005) without
further refactoring.

### 2.2 Categories & data sources

| Category                | Source                                  | Endpoint                            |
| ----------------------- | --------------------------------------- | ----------------------------------- |
| `tvl_drop`              | DefiLlama (time-series)                 | `GET /protocol/{slug}`              |
| `apy_spike`             | local `data/historical_apy.json`        | filesystem (already populated)      |
| `governance_proposal`   | Snapshot (unauthenticated GraphQL)      | `POST /graphql`                     |
| `token_unlock`          | DefiLlama unlocks                       | `GET /api/unlocks`                  |

All three remote calls are wrapped in the same `_http_get_text` /
`_http_post_json` helpers with retries (2 attempts, exponential backoff) and
**always degrade gracefully** to the in-module `BOOTSTRAP_*` fixtures on any
error.

### 2.3 Severity classifier

```
                    WARN                   CRITICAL
tvl_drop            ≥ threshold,           ≥ 50% drop OR grade ∈ {C,D,F}
                    grade ∈ {A,B}
apy_spike           ratio ≥ 1.5x,          ratio ≥ 3.0x OR grade ∈ {C,D,F}
                    grade ∈ {A,B}
governance_proposal risk-sensitive tag,    tag ∈ {emergency, shutdown, pause}
                    grade ∈ {A,B}          OR grade ∈ {C,D,F}
token_unlock        < 5% of supply,        ≥ 5% of supply
                    grade ∈ {A,B}          OR grade ∈ {C,D,F}
```

Thresholds:

| Constant                          | Value | Rationale |
| --------------------------------- | ----- | --------- |
| `TVL_DROP_24H_THRESHOLD_PCT`      | 15 %  | matches FEAT-MON-001 sprint spec. Below this is normal market noise on stablecoin pools. |
| `TVL_DROP_7D_THRESHOLD_PCT`       | 30 %  | sustained 30 % weekly drop is regime-change territory (Sky V2 launch, Aave V2 deprecation). |
| `TVL_DROP_CRITICAL_PCT`           | 50 %  | always CRITICAL — historically only protocol-level incidents (Curve Vyper, Euler V1) trigger ≥50 % drops. |
| `APY_SPIKE_MULTIPLIER`            | 1.5 × | matches sprint spec "above 7-day baseline". Below this is volatility noise. |
| `APY_SPIKE_CRITICAL_RATIO`        | 3.0 × | always CRITICAL — typical "honey-pot" pre-rug signature on yield-loop strategies. |
| `UNLOCK_HORIZON_DAYS`             | 7     | matches sprint spec. Most price impact concentrates in the 72 h around the cliff. |
| `UNLOCK_CRITICAL_PCT_SUPPLY`      | 5 %   | based on retrospective analysis of historical unlocks (>5 % supply unlocks correlated with >20 % token price drops within 14 days). |

### 2.4 Risk-grade context

The classifier reads `data/risk_scores.json` (FEAT-RISK-001 output) and
folds the per-protocol grade into the severity decision. A TVL drop on a
**grade-A** protocol (Aave V3, Sky) stays at `WARN` — those protocols have
deep oracle, multisig, and audit defenses. The same drop on a **grade-D**
protocol (Maple, smaller credit primitives) is upgraded to `CRITICAL`
because the recovery probability is materially lower.

This grade-gating is the central design choice that prevents alert fatigue:
without it, every 15 % TVL move on Aave would page the operator at 03 :00.

### 2.5 Output schema (`data/red_flags.json`)

```jsonc
{
  "generated_at": "2026-05-28T00:00:00Z",
  "monitor_version": "1.0",
  "sources": ["bootstrap"],          // OR ["defillama","historical_apy","snapshot"]
  "fallback_used": true,
  "red_flags": [
    {
      "protocol":    "ethena-susde",
      "category":    "token_unlock",
      "severity":    "CRITICAL",
      "message":     "Token unlock 6.40% of supply (ENA) at 2026-06-03T00:00:00Z",
      "source":      "defillama",
      "detected_at": "2026-05-28T00:00:00Z",
      "evidence":    { ... }
    }
  ],
  "summary": {
    "total_flags":     8,
    "by_category":     { "apy_spike": 2, "governance_proposal": 2,
                          "token_unlock": 2, "tvl_drop": 2 },
    "by_severity":     { "CRITICAL": 2, "WARN": 6 },
    "by_protocol":     { "aave-v3": 1, ... },
    "protocols_clean": 4
  }
}
```

The shape is intentionally a *flat* list (not nested per protocol) so the
Telegram fan-out can iterate with one pass, and the dashboard can group by
any dimension trivially.

### 2.6 Telegram integration (BL-005, planned for v3.17)

`TelegramSender.send_red_flag_alert(flag_dict)` will accept either a single
`RedFlag` dict or the entire `red_flags` array. The first integration commit
is intentionally out of scope for FEAT-MON-001 to keep this sprint at 8 h —
but the schema is already aligned to the existing
`TelegramSender.send_risk_alert` API in `risk_monitor.py`.

### 2.7 Go-live criterion 3

Go-live criterion 3 ("no CRITICAL alerts in the last 7 days") becomes
**fully measurable** with this monitor because the system can now emit
CRITICAL findings on external state changes, not just on internal portfolio
events. The "last 7 days" window is satisfied by GitHub Actions persisting
`data/red_flags.json` snapshots (already part of the standard data pipeline).

## 3. Alternatives considered

| Option | Why rejected |
| ------ | ------------ |
| **Extend `risk_monitor.py` in place** | Module is already 300 LOC and conflates portfolio-side checks with external-signal scanning. Separation of concerns wins. |
| **Use authenticated DefiLlama Pro API** | Adds a paid dependency and a secret. The free `/protocol/{slug}` endpoint already returns the 7-day TVL series with adequate resolution. |
| **Push from CEX exchange-flow feeds** | Out of scope for stablecoin yield strategies; the four chosen sources cover the protocol-level risks the SPA strategies actually carry. |
| **Single CRITICAL threshold, no grade context** | Generates ~3× more alerts; pilot run on historical data showed 6 / 8 noise on grade-A protocols. |

## 4. Consequences

* `data/red_flags.json` is now an authoritative input for the dashboard and
  the Telegram fan-out — every cycle persists a fresh snapshot.
* `risk_scores.json` becomes a **soft dependency** of the Red Flag Monitor.
  If absent or unreadable the monitor still runs; severities just stop
  picking up the grade-context upgrade.
* Three external endpoints (DefiLlama protocol, DefiLlama unlocks, Snapshot
  GraphQL) are now polled every 4 h. None are rate-limited at this cadence.
* No new top-level dependencies — pure stdlib (urllib + json + dataclasses
  + datetime). `requirements.txt` is unchanged.
* 56 deterministic tests cover all 4 categories, both severity tiers, every
  fallback path, the CLI, the JSON shape, and module-level helpers.

## 5. Roll-out plan

| Step | Owner | Status |
| ---- | ----- | ------ |
| Implement module + seed `data/red_flags.json` | dispatch-orchestrator | **Done (v3.16)** |
| Wire `RedFlagMonitor.export` into the 4 h GitHub Actions cycle | infra agent | v3.17 |
| Wire `TelegramSender.send_red_flag_alert` (BL-005) | bl-005 owner | v3.17 |
| Add `red_flags.json` panel to `index.html` dashboard | frontend agent | v3.18 |
| Backfill alerts schema docs in `docs/api_reference.md` | docs agent | v3.17 |

## 6. References

* `spa_core/alerts/red_flag_monitor.py` — implementation.
* `spa_core/tests/test_red_flag_monitor.py` — 56 tests.
* `data/red_flags.json` — offline seed snapshot.
* `spa_core/agents/yield_classifier_agent.py` — pattern reference.
* `spa_core/agents/audit_reader_agent.py` — pattern reference.
* DefiLlama API docs — <https://api-docs.defillama.com/>.
* Snapshot GraphQL playground — <https://hub.snapshot.org/graphql>.
