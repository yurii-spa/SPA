# ADR-003: Rate Limiting and Circuit Breaker for External API Calls

Date: 2026-05-22
Status: ACCEPTED
Deciders: SPA Owner (Yurii Kulieshov)

## Context
SPA fetches data from DeFiLlama and Pendle APIs every 4 hours via GitHub Actions.
These are public APIs with undocumented rate limits. A circuit breaker prevents
cascading failures when an API is temporarily unavailable.

## Decision
Implement a two-layer protection:
1. Retry with exponential backoff (max 3 attempts, 2^n seconds between attempts)
2. Circuit breaker: after 3 consecutive failures, skip that data source for 1 cycle
   and use last-known-good cached data instead.

Cache TTL: 1 hour for normal operation, 4 hours for circuit-broken fallback.

## Rationale
- DeFiLlama is free/public — aggressive retries could get IP banned
- Cached data avoids presenting stale dashboard during transient outages  
- Circuit breaker prevents spending 45+ seconds on timeouts per cycle
- Exponential backoff (1s, 2s, 4s) totals max 7s overhead per failing endpoint

## Consequences
Good:
- GitHub Actions runs won't fail due to API flakiness
- Dashboard stays populated during outages (cached data)
- Operator sees DEGRADED badge but not ERROR state

Bad:
- Cached data can be up to 4 hours stale during outage
- Circuit state is not persisted across Actions runs (stateless)

## Implementation
See: spa_core/data_pipeline/defillama_fetcher.py (retry_request function)
See: spa_core/data_pipeline/pendle_fetcher.py (uses retry_request)
See: spa_core/export_data.py (pipeline_health.json tracking)
See: spa_core/alerts/risk_monitor.py (alert_pipeline_failure)
