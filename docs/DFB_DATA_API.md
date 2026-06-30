# DFB Data API — Developer Documentation (`/api/dfb/v1/*`)

> **DeBank Cloud sells you the RAW data. DFB sells you the RISK TRUTH + the proof.**
>
> The DFB Data API is the *risk-graded* developer surface for the DeFi Board: programmatic,
> versioned, key-gated access to the per-pool risk overlay — every pool's **A/B/C/D risk
> grade**, its **exit-liquidity-by-size** schedule, its deterministic **refusal verdict**, and a
> **reproducible proof hash**. Risk-graded data is scarcer and more defensible than raw yield data
> (DefiLlama gives you the raw numbers; DFB gives you the risk truth *and* lets you re-derive it).

- **Status:** BUILT, behind the owner-gated flag `SPA_DFB_DATA_API` (default **OFF**).
- **Public launch** (key issuance, billing, SLA, ToS) is **OWNER-GATED** — see
  [§ Owner-gated launch](#owner-gated-launch). No usage or pricing is fabricated here.
- **Posture:** read-only, GET-only, deterministic, **LLM-free**, fail-CLOSED, no `execution/`
  import, never writes a file. **NO-FORK:** the v1 surface serves the SAME overlay the public
  `/api/dfb/*` router serves, byte-identical (one source of the graded universe — a red-team test
  asserts byte-equality).

---

## 1. Flag gating — `SPA_DFB_DATA_API` (default OFF)

The entire `/api/dfb/v1/*` surface only operates when the owner sets `SPA_DFB_DATA_API` to a
truthy value (`1` / `true` / `on` / `yes`).

| State | Behavior |
|---|---|
| flag **OFF** (default) | **Total 404** on every `/api/dfb/v1/*` path — even with a valid key. No surface leaks. |
| flag **ON** + key configured + valid credential | **200** — risk-graded data served. |
| flag **ON** + key configured + missing/invalid/spoofed credential | **401** |
| flag **ON** + **NO** key configured on the server | **401** — fail-CLOSED, the surface is **never silently opened** |

This mirrors the underwriting router's owner-gate. The flag governs *public surfacing*; the
underlying overlay (`/api/dfb/*`) and its proof chains exist regardless.

---

## 2. Authentication

Every `/api/dfb/v1/*` request requires an API key. Two accepted forms (either):

```
X-API-Key: <your-api-key>
Authorization: Bearer <hmac-token>          # HMAC-SHA256 timestamped token (±300s window)
```

- The key is read on the **server** from `SPA_API_KEY` (env → macOS Keychain). It is **NEVER
  hardcoded** and never appears in source or logs.
- Responses carry only a **non-reversible fingerprint** of your key (`sha256(key)[:16]`) in the
  `key` field — never the raw key.
- The Data API **always** enforces the key when the surface is live (unlike the dashboard's write
  endpoints, which a dev-mode flag can relax). A paid product surface is not opened by a dev flag.

**Fail-CLOSED guarantees (red-team-verified):**
- flag OFF → 404 everywhere (no leak),
- flag ON + no key configured → 401 (never open),
- a wrong / rotated / spoofed key → 401 (constant-time compare, no information leak),
- a flood → 429 (see rate limits).

Example:

```bash
curl -s https://api.earn-defi.com/api/dfb/v1/pools \
     -H "X-API-Key: $DFB_API_KEY" | jq .
```

---

## 3. Rate limits — per-key tiers (free / pro)

Throughput is gated **per API key** (a token bucket), on top of the app-wide per-IP limiter. Two
conceptual tiers; an unknown/unlisted key defaults to **free** (fail to the cheaper tier).

| Tier | Default limit | Env knob |
|---|---|---|
| free | 30 req/min | `SPA_DFB_API_FREE_PER_MIN` |
| pro | 600 req/min | `SPA_DFB_API_PRO_PER_MIN` |

Tier assignment is by key **fingerprint** (`sha256(key)[:16]`) via `SPA_DFB_API_PRO_KEYS` (a
comma-separated allow-list of fingerprints — never raw keys). Over-limit → `429 Too Many Requests`
with a `Retry-After` header. The free/pro split is the *mechanism*; real key→tier issuance is wired
at the owner-gated launch.

---

## 4. Endpoints

All responses carry the standard envelope: `api_version`, `is_advisory: true`, `disclaimer`,
`key` (your fingerprint), `served_at`.

### `GET /api/dfb/v1`
Self-describing index — the pitch, the endpoint catalog, the auth/reproduce story.

### `GET /api/dfb/v1/pools`
The full **risk-graded universe** — one overlay row per followed market. Byte-identical to the
public `/api/dfb/pools` (no-fork). Fail-CLOSED: missing/corrupt universe → `200` with an honest
empty `pools: []` (never fabricated rows).

```json
{
  "api_version": "v1",
  "endpoint": "pools",
  "available": true,
  "n_pools": 35,
  "pools": [ { /* overlay row — see §5 */ } ],
  "is_advisory": true,
  "key": "9f1c2a…",
  "served_at": "2026-06-30T..."
}
```

### `GET /api/dfb/v1/pool/{pool_id}`
One pool's **full overlay** + exit-liquidity schedule + refusal decomposition + `row_hash`.
Fail-CLOSED: invalid or unknown `pool_id` → `404` (a guess is a lie; absence is honest).

### `GET /api/dfb/v1/pool/{pool_id}/history?limit=365`
One pool's **proof-chained historical series** (APY base/reward · TVL · refusal-state over time),
verified as one chain (the `chain` block reports `verified` / `head_hash` / `broken_at`). Delegates
to the public history reader (no-fork). Invalid id → `404`; absent history → `200` with a vacuously
valid empty chain.

### `GET /api/dfb/v1/refusals`  ← the differentiator
The **refused-pools feed** — every pool the deterministic desk would **REFUSE**, with its reason
code, tail-veto flag, structural/total haircuts, and `row_hash`. No incumbent publishes a
programmatic "pools the desk refuses" feed. Pure filter over the same universe (no risk math).

```json
{
  "endpoint": "refusals",
  "n_refused": 3,
  "n_universe": 35,
  "refusals": [
    { "pool_id": "...", "protocol": "...", "chain": "...", "risk_class": "D",
      "refusal": { "verdict": "REFUSE", "reason": "structural_tail", "tail_veto": true },
      "structural_haircut": 0.09, "total_haircut": 0.18, "row_hash": "..." }
  ]
}
```

### `GET /api/dfb/v1/screener`
Filtered query over the graded universe. All filters are pure FILTERS over the overlay rows
(no risk math); unknown values match nothing (an empty result is honest).

| Param | Meaning |
|---|---|
| `risk_class` | `A`/`B`/`C`/`D` (comma-separated ok) |
| `refused` | `true` → only refused; `false` → only non-refused |
| `chain` | e.g. `ethereum`, `arbitrum` |
| `protocol` | e.g. `aave_v3` |
| `limit` | max rows (default 500, ≤ 5000) |

```bash
curl -s "https://api.earn-defi.com/api/dfb/v1/screener?risk_class=A,B&refused=false&chain=ethereum" \
     -H "X-API-Key: $DFB_API_KEY" | jq '.pools[].pool_id'
```

---

## 5. The risk-overlay schema

Each pool row (served verbatim from the deterministic overlay — no fabrication):

| Field | Meaning |
|---|---|
| `pool_id` | stable, path-safe id minted from protocol/chain/asset |
| `protocol`, `chain`, `asset`, `tier` | identity (tier = T1/T2/T3) |
| `apy` | `{ total, base, reward }` (normalized units) |
| `tvl_usd` | total value locked |
| `risk_class` | **A / B / C / D** (see § risk grades) |
| `structural_haircut`, `total_haircut` | the deterministic haircuts behind the grade |
| `exit_liquidity` | list of `{ ticket_usd, absorbable_usd, dex_exit_frac, flagged }` (see § exit-by-size) |
| `refusal` | `{ verdict, reason, tail_veto }` (see § refusal) |
| `as_of`, `data_source`, `feed_coverage` | provenance |
| `prev_hash`, `row_hash` | the per-row proof chain (see § proof) |

### Risk grades A/B/C/D
A deterministic, LLM-free classification of a pool's structural risk (the desk's own taxonomy):

- **A** — lowest structural risk (deep liquidity, no tail veto, healthy exit at size).
- **B** — sound, with minor haircuts.
- **C** — elevated risk (thin depth at size, watch-grade signals) — caution.
- **D** — the desk would **refuse** (structural tail beyond the veto cap, depeg/peg risk, etc.).

The grade is a presentation of the same structural haircuts + tail-veto the desk applies to its own
book — never a black-box "AI score."

### Exit-liquidity-by-size
For each ticket size (e.g. $1M / $5M / $10M **OUT**), `absorbable_usd` is a **conservative lower
bound** on what that market's *own* on-chain depth can absorb (never aggregated across markets).
If depth is too thin/stale to bound honestly, the cell is a **visible hole**: `flagged: true` with
`absorbable_usd: null` — **never a fabricated fill**. A toxic pool cannot be "sized around": the
structural-haircut veto caps it regardless of ticket size.

### Refusal verdict
`refusal.verdict` ∈ `ALLOW` / `WATCH` / `REFUSE`. A `REFUSE` carries a `reason` code and a
`tail_veto` flag — the deterministic "would-the-desk-refuse-this" decision (5 structural haircuts +
tail veto), the same gate the desk runs against its own positions. **Not an LLM. Not a score.**

---

## 6. Proof — re-derive a pool's `proof_hash` yourself

Every overlay row carries a `row_hash` over its canonical-JSON payload, and each pool's history is a
prev_hash/row_hash chain (genesis `"0"*64`). Canonical JSON rule:

```python
json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
hash = sha256(canonical_json).hexdigest()
```

Re-derive without trusting us — with **zero `spa_core` import** — using the standalone verifier:

```bash
python3 scripts/verify_spa.py dfb/pools.json dfb/history/<pool_id>.jsonl
```

A tampered cell breaks the chain (tamper-evident). Spec: `docs/PROOF_CHAIN_SPEC.md`.
*"Don't trust us, check us."*

---

## 7. Owner-gated launch

The Data API is **built and flag-gated OFF**. The following are explicitly **owner-gated** — a
commercial decision + owner infra, **not** auto-activated by this code:

- **Issuing API keys** to developers (and mapping keys → tiers),
- **Billing / metering for revenue** (the per-key buckets exist; a billing backend does not),
- **SLA / uptime commitments**,
- **Terms of Service**,
- binding the real domain (`SPA_DFB_DOMAIN`).

Until the owner flips `SPA_DFB_DATA_API` (and stands up key issuance/billing/SLA/ToS), the surface
is a total 404. This document describes the *built* product, not a launched one — no usage numbers,
no pricing, no customer claims are stated because none exist yet.

---

## 8. Server-side configuration reference (owner)

| Env var | Default | Purpose |
|---|---|---|
| `SPA_DFB_DATA_API` | OFF | master flag — turns the `/v1` surface on |
| `SPA_API_KEY` | (Keychain) | the API key (env → macOS Keychain; never hardcoded) |
| `SPA_DFB_API_FREE_PER_MIN` | 30 | free-tier per-key rate (req/min) |
| `SPA_DFB_API_PRO_PER_MIN` | 600 | pro-tier per-key rate (req/min) |
| `SPA_DFB_API_PRO_KEYS` | (empty) | comma-separated **fingerprints** (`sha256(key)[:16]`) of pro-tier keys |

---

*Advisory: the DFB Data API is read-only risk analytics — NOT financial advice, NOT a
recommendation, NOT realized capital. Exit-liquidity is a conservative lower bound or a visible
hole, never a fabricated fill. Every number is reproducible. Don't trust us, check us.*
