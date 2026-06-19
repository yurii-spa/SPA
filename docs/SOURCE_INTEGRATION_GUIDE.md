# Source Integration Guide

> **Purpose:** After reading this guide you will be able to independently find
> a DeFiLlama pool ID and wire it into the SPA data pipeline for any new yield
> source — without asking for help.

---

## Overview

To exit `RESEARCH_ONLY` status, a strategy slot (RS-001 / RS-002) needs a
**CLEAN** data source. CLEAN means live, verifiable data on DeFiLlama or
directly on-chain, fetched by a stdlib-only adapter.

**The three-part checklist:**

1. Pool ID confirmed on DeFiLlama (`find_defillama_sources.py`)
2. APY time-series verified against live chart endpoint
3. Adapter code merged and cycle_runner picking it up

---

## Step 1: Find the Pool ID

Run the discovery script:

```bash
# Search a specific protocol by name
python3 scripts/find_defillama_sources.py --protocol gmx_v2_btc

# Search all target protocols at once
python3 scripts/find_defillama_sources.py --all

# Search all and save results to data/source_discovery.json
python3 scripts/find_defillama_sources.py --all --save
```

The script prints a box for each matching pool:

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Pool ID: abc123-def4-5678-90ab-cdef01234567                             │
│ Project: gmx-v2                                                         │
│ Symbol:  BTC-USD-GM                                                     │
│ Chain:   Arbitrum                                                        │
│ APY:     18.2%                                                           │
│ TVL:     $45.2M                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

**What to look for:**

- `TVL > $1M` — hard floor enforced by the script; larger is better.
- `Project` matches the protocol you expect (e.g. `gmx-v2`, not `gmx-v1`).
- `Symbol` contains the asset you want (e.g. `BTC`, `USDC`).
- `Chain` is correct (Arbitrum, Ethereum, etc.).

Write down the **Pool ID** (the UUID-format string in the first field).

---

## Step 2: Verify the Pool ID

Confirm the pool has live historical data:

```bash
python3 -c "
import urllib.request, json
POOL_ID = 'PASTE_YOUR_POOL_ID_HERE'
url = f'https://yields.llama.fi/chart/{POOL_ID}'
data = json.loads(urllib.request.urlopen(url, timeout=10).read())
rows = data.get('data', [])
print(f'Data points: {len(rows)}')
if rows:
    print('Latest entry:', rows[-1])
"
```

**Expected output:**

```
Data points: 183
Latest entry: {'timestamp': '2026-06-19T00:00:00.000Z', 'tvlUsd': 45200000.0, 'apy': 18.2}
```

If `data points: 0` or a 404 error → the pool ID is wrong. Go back to Step 1
and pick a different result.

---

## Step 3: Update the Adapter

### 3a. Find the right adapter file

| Protocol | Adapter file |
|---|---|
| GMX v2 (Arbitrum) | `spa_core/adapters/gmx_v2_arbitrum.py` *(create if missing)* |
| Aave v3 (Arbitrum) | `spa_core/adapters/aave_v3_arbitrum.py` |
| Morpho (Ethereum) | `spa_core/adapters/morpho_steakhouse_adapter.py` |
| Pendle PT | `spa_core/adapters/pendle_pt_rest.py` |
| Sky/sUSDS | `spa_core/data_pipeline/sky_monitor.py` |
| Ondo OUSG | Create new: `spa_core/adapters/ondo_ousg.py` |

### 3b. Add the pool ID to the adapter

Typical pattern (stdlib only):

```python
# At module top — the pool ID confirmed via find_defillama_sources.py
DEFILLAMA_POOL_ID = "abc123-def4-5678-90ab-cdef01234567"

def fetch_apy(timeout: int = 10) -> dict:
    """Returns {'apy': float, 'tvl_usd': float, 'source': str}."""
    url = f"https://yields.llama.fi/chart/{DEFILLAMA_POOL_ID}"
    try:
        raw = urllib.request.urlopen(url, timeout=timeout).read()
        data = json.loads(raw)
        latest = data["data"][-1]
        return {
            "apy": float(latest["apy"]),
            "tvl_usd": float(latest.get("tvlUsd", 0)),
            "source": f"defillama:{DEFILLAMA_POOL_ID}",
        }
    except Exception:
        return {"apy": None, "tvl_usd": None, "source": "error"}
```

You can also use the helper to generate this snippet automatically:

```bash
python3 -c "
from spa_core.analytics.source_integration_helper import SourceIntegrationHelper
h = SourceIntegrationHelper()
print(h.generate_adapter_snippet(
    source_name='gmx_v2_btc',
    pool_id='abc123-def4-5678-90ab-cdef01234567',
    fallback_apy=18.0,
))
"
```

### 3c. Register in ADAPTER_REGISTRY

Open `spa_core/adapters/__init__.py` and add your adapter to `ADAPTER_REGISTRY`:

```python
from spa_core.adapters.gmx_v2_arbitrum import GmxV2ArbitrumAdapter

ADAPTER_REGISTRY = {
    ...
    "gmx_v2_btc": GmxV2ArbitrumAdapter(asset="BTC"),
}
```

### 3d. Validate the integration

```bash
# Run the helper checklist
python3 -c "
from spa_core.analytics.source_integration_helper import SourceIntegrationHelper
h = SourceIntegrationHelper()
for step in h.integration_checklist('gmx_v2_btc'):
    print(step)
"

# Run a dry-run cycle to confirm adapter is picked up
python3 -m spa_core.paper_trading.cycle_runner --verbose
```

---

## Step 4: Update Source Pipeline Status

After the adapter is confirmed working, update the pipeline tracker:

```bash
python3 -c "
from spa_core.analytics.source_integration_helper import SourceIntegrationHelper
h = SourceIntegrationHelper()
h.update_source_pipeline(
    source_id='gmx_v2_btc',
    pool_id='abc123-def4-5678-90ab-cdef01234567',
    status='INTEGRATED',
)
"
```

Status values: `PENDING` → `TESTING` → `INTEGRATED` → `CLEAN`.

---

## Step 5: Push and Track

```bash
python3 push_to_github.py \
  --files /abs/path/spa_core/adapters/gmx_v2_arbitrum.py \
          /abs/path/data/backtest/source_pipeline.json \
  --message "feat: gmx_v2_btc source integrated (DeFiLlama pool abc123-def4)"
```

Update `KANBAN.json` to reflect the slot transitioning from `RESEARCH_ONLY`
to `DATA_READY`.

---

## Priority Queue (Current as of 2026-06-19)

| Priority | Source name | Expected DeFiLlama project | Symbol | Chain | Status |
|---|---|---|---|---|---|
| 1 | `gmx_v2_btc` | `gmx-v2` | `BTC-USD-GM` | Arbitrum | SOURCE_NEEDED |
| 2 | `gmx_v2_eth` | `gmx-v2` | `ETH-USD-GM` | Arbitrum | SOURCE_NEEDED |
| 3 | `ondo_ousg` | `ondo` | `OUSG` | Ethereum | SOURCE_NEEDED |
| 4 | `btc_stablepool` | `uniswap-v3` | `BTC-USDC` | Arbitrum | SOURCE_NEEDED |
| 5 | `gold_proxy_paxg` | `uniswap-v3` | `PAXG` | Ethereum | SOURCE_NEEDED |
| 6 | `aave_usdc_arb` | `aave-v3` | `USDC` | Arbitrum | SOURCE_NEEDED |
| 7 | `morpho_usdc` | `morpho` | `USDC` | Ethereum | SOURCE_NEEDED |
| 8 | `pendle_pt` | `pendle` | `PT` | Ethereum | SOURCE_NEEDED |

Run `python3 scripts/find_defillama_sources.py --protocol <name>` to start
discovery for any row above.

---

## Already CLEAN (Do Not Touch)

These sources are confirmed and feeding live data into the cycle. No changes
needed:

| Source | Project | Symbol | Chain | Verified |
|---|---|---|---|---|
| `sky_susds` | `sky` | `sUSDS` | Ethereum | ✅ DeFiLlama pool |
| `spark_susds` | `spark` | `sUSDS` | Ethereum | ✅ DeFiLlama pool |
| `aave_usdc_eth` | `aave-v3` | `USDC` | Ethereum | ✅ `aave_v3.py` adapter |
| `compound_usdc` | `compound-v3` | `USDC` | Ethereum | ✅ `compound_v3.py` adapter |
| `morpho_steakhouse` | `morpho` | `USDC` | Ethereum | ✅ `morpho_steakhouse_adapter.py` |

---

## Troubleshooting

**`find_defillama_sources.py` returns no pools for my protocol**

- DeFiLlama project names are exact. Try variations: `gmx` vs `gmx-v2` vs
  `gmx-v2-arbitrum`. Run `--all` and grep the output.
- The pool may have TVL < $1M (recently launched or migrated). Lower threshold
  temporarily: edit `MIN_TVL` in the script.

**Chart endpoint returns 404**

- The pool ID format is wrong. Pool IDs are UUIDs; copy from the `Pool ID`
  field in the script output, not from the DeFiLlama website URL.

**cycle_runner doesn't pick up the new adapter**

- Check `ADAPTER_REGISTRY` in `spa_core/adapters/__init__.py`.
- Check that the adapter module has no import errors:
  `python3 -c "from spa_core.adapters.your_adapter import YourAdapter"`.

**RiskPolicy blocks the new pool**

- Check `data/risk_policy_blocks.json` for the most recent block reason.
- Common causes: TVL < $5M (policy floor), APY out of 1%–30% range,
  per-protocol cap exceeded.

---

## Constraints (from CLAUDE.md — do not violate)

- **Stdlib only** in all adapter code. No `requests`, `aiohttp`, or other
  third-party packages.
- **Atomic writes** for all state files: use `tmp + os.replace`, never
  `open(..., "w")` directly on `data/*.json`.
- **Sky/sUSDS stays at 0% allocation** until on-chain GSM Pause Delay ≥ 48h
  is confirmed.
- **LLM forbidden** in risk / execution / monitoring components.
- **Do not import** `spa_core/execution/` from adapter or analytics code.

---

*Updated: 2026-06-19 — MP-1358 v9.74*
