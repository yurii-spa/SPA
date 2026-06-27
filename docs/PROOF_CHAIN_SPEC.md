# SPA Rates-Desk Proof-Chain Specification

**Status:** canonical · stdlib-only · deterministic · LLM-FORBIDDEN
**Audience:** any third party who wants to **independently re-derive and verify every hash** in our
public decision log — *without running our code*.

The SPA rates-desk publishes a tamper-evident record of every trade it **approved** and, more
importantly, every trade it **refused** — and why. This document is the exact, self-contained recipe
to recompute each hash from the public file and confirm the chain is intact. If you follow it and your
recomputed hashes match the stored ones, you have proven the log was not altered after the fact. If a
single byte of any historical decision were changed, your recompute would diverge at that row.

---

## 1. The public file

`data/rates_desk/decision_log.jsonl` — JSON Lines (one JSON object per line, UTF-8). It is also
served live at `GET /api/rates-desk/proof` (machine) and `GET /api/rates-desk/refusals`
(human-readable). Each line is **one decision** (an `ENTRY` or a `REFUSAL`) and has this shape:

```json
{
  "seq": 111,
  "ts": "2026-06-26T00:00:00+00:00",
  "prev_hash": "20cbeb9b…d2c9",
  "entry_hash": "90d939fd…912e",
  "kind": "REFUSAL",
  "approved": false,
  "reason": "tail_veto",
  "as_of": "2026-06-25",
  "underlying": "eeth",
  "shape": "fixed_carry",
  "net_edge": "-0.1357377866666666666666666667",
  "approved_size_usd": "0",
  "decomposition": { … see §4 … },
  "detail": { … },
  "proof_hash": "462e7ee4…1eaf"
}
```

Two groups of fields:

| group | fields | role |
|---|---|---|
| **envelope** | `seq`, `ts`, `entry_hash`, `prev_hash` | the chain linkage |
| **payload** | *everything else* (`kind`, `approved`, `reason`, `as_of`, `underlying`, `shape`, `net_edge`, `approved_size_usd`, `decomposition`, `detail`, `proof_hash`) | the signed decision body |

> All monetary/rate values are emitted as **strings** (e.g. `"net_edge": "-0.1357…"`). They are exact
> `Decimal` values rendered with `str()`; never parse them as floats before hashing — hash the bytes
> as published.

---

## 2. The canonical-JSON rule (the only rule that matters)

Every hash is computed over a **canonical JSON** string built with these exact options:

```python
json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
```

- `sort_keys=True` — object keys in lexicographic order, **recursively** (nested objects too).
- `separators=(",", ":")` — no whitespace after `,` or `:`.
- `ensure_ascii=False` — non-ASCII characters emitted as UTF-8, not `\uXXXX` escapes.
- The string is then UTF-8 encoded and hashed with **SHA-256**, hex digest (lowercase).

Any conforming JSON serializer in any language reproduces this byte-for-byte as long as it sorts keys
recursively, uses compact separators, preserves UTF-8, and does **not** re-format the numeric strings
(they are already strings in the file, so no float round-trip can corrupt them).

---

## 3. Recomputing `entry_hash` for one row

`entry_hash` is the SHA-256 over the canonical JSON of **exactly these five fields, in this set**
(key order is handled by `sort_keys`):

```
{ "seq", "ts", "event_type", "payload", "prev_hash" }
```

where:

- `seq`, `ts`, `prev_hash` are taken **verbatim** from the row's envelope,
- `event_type` is the constant string **`"rates_desk_decision"`** (it is *not* stored per-row; it is
  fixed for this log),
- `payload` is the row **with the four envelope keys removed** (`seq`, `ts`, `entry_hash`,
  `prev_hash`), i.e. everything in the "payload" group of §1, passed through unchanged.

### Reference recompute (language-agnostic pseudo-Python)

```python
import json, hashlib

ENVELOPE = ("seq", "ts", "entry_hash", "prev_hash")
EVENT_TYPE = "rates_desk_decision"

def recompute_entry_hash(row: dict) -> str:
    payload = {k: v for k, v in row.items() if k not in ENVELOPE}
    canonical = json.dumps(
        {
            "seq":        row["seq"],
            "ts":         row["ts"],
            "event_type": EVENT_TYPE,
            "payload":    payload,
            "prev_hash":  row["prev_hash"],
        },
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

A row is authentic iff `recompute_entry_hash(row) == row["entry_hash"]`.

> **Worked example (real row, seq=111).** Running the recipe above on the first line of the published
> log yields `90d939fdfc4b233fe0eaca2c10e39a1bd3aa5236214a4a54ec76b8cfcde6912e`, which equals the
> stored `entry_hash`. (Confirmed in the test suite — see §6.)

---

## 4. The `decomposition` sub-object and `proof_hash`

`decomposition` is the fair-value breakdown the verdict was based on — an honest `baseline` minus five
risk haircuts → a `fair_yield`:

```json
"decomposition": {
  "underlying": "eeth", "as_of": "2026-06-25",
  "baseline": "0.029",
  "peg_haircut": "0.024071120",
  "funding_flip_haircut": "0.06",
  "oracle_haircut": "0.006666666666666666666666666668",
  "liquidity_haircut": "0.06",
  "protocol_haircut": "0.014",
  "total_haircut": "0.1647377866666666666666666667",
  "fair_yield": "-0.1357377866666666666666666667"
}
```

`total_haircut = peg + funding_flip + oracle + liquidity + protocol`, and
`fair_yield = baseline − total_haircut`. These are the numbers the human-readable refusal log cites
verbatim (e.g. *"peg 2.41% + funding 6.00% + … = total 16.47% haircut vs 12.00% cap"*). Because they
live **inside** the hashed `payload`, altering any haircut changes `entry_hash` — so every published
explanation number is hash-anchored.

`proof_hash` is an **independent** digest produced by the gate over the full verdict (decomposition +
gate fields + detail) using the same canonical-JSON + SHA-256 rule. It is included **inside** the
payload, so it too is covered by `entry_hash`. It lets a verifier confirm the verdict body separately
from the chain linkage.

---

## 5. Verifying the whole chain

Walk the file in `seq` order from the genesis row and check three things at each row:

1. **Monotonic seq** — `row.seq == index` (0-based, no gaps, no reordering).
2. **Prev-linkage** — `row.prev_hash == previous_row.entry_hash`; the genesis row's `prev_hash` is
   `"0" * 64` (64 zero hex chars).
3. **Self-recompute** — `recompute_entry_hash(row) == row.entry_hash` (§3).

The first row that fails any check is `broken_at`. If all rows pass, the chain is intact and the
`head_hash` is the last row's `entry_hash`. An empty file is vacuously valid.

```python
def verify_chain(rows: list) -> dict:
    expected_prev = "0" * 64
    for idx, row in enumerate(rows):
        if row.get("seq") != idx:                       return {"valid": False, "broken_at": idx}
        if row.get("prev_hash") != expected_prev:       return {"valid": False, "broken_at": idx}
        if recompute_entry_hash(row) != row.get("entry_hash"):
                                                        return {"valid": False, "broken_at": idx}
        expected_prev = row["entry_hash"]
    head = rows[-1]["entry_hash"] if rows else None
    return {"valid": True, "broken_at": None, "head_hash": head}
```

This is exactly what `GET /api/rates-desk/proof` and `GET /api/rates-desk/refusals` run server-side
and report as `verified` / `head_hash` / `broken_at`. You do **not** have to trust that endpoint — the
whole point of this spec is that you can run the recipe above on the raw file and reach the same
verdict independently.

---

## 6. Determinism & test anchor

The recipe is deterministic: same file → same hashes on any machine, any language, any year. The repo
proves the recipe is correct in `spa_core/tests/test_public_refusal_log.py`
(`test_proof_chain_spec_reproducible` recomputes a stored `entry_hash` straight from the raw JSONL,
following *only* this document, and asserts the match).

**Invariants** (never silently change without a new spec version):
canonical JSON = `sort_keys=True, separators=(",",":"), ensure_ascii=False`; `event_type =
"rates_desk_decision"`; hash = SHA-256 hex; genesis `prev_hash = "0"*64`; envelope keys =
`{seq, ts, entry_hash, prev_hash}`; all money/rate values are exact decimal **strings**.
