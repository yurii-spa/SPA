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

## 0. Two files named `audit_*` — which is the tamper-evidence? (read this first)

A reviewer grepping `data/` will find **two** append-only `.jsonl` ledgers with similar
names. They do **different** jobs; only one is the tamper-evident hash chain this spec
verifies. Do not confuse them:

| File | What it is | Tamper-evident? | Verified by `verify_spa.py`? |
|---|---|---|---|
| **`data/audit_chain.jsonl`** | The **SHA-256 hash chain** — each entry carries `prev_hash`/`entry_hash`, so altering any past row breaks the chain (`spa_core/audit/hash_chain.py`). The authoritative append-only producer ledger the public `decision_log.jsonl` mirror is re-based from (§5, §6a). | **YES** — this is *the* tamper-evidence. | Yes — the public mirror (`decision_log.jsonl`) is a re-based projection of this chain; the chain recipe is §3/§5. |
| **`data/audit_trail.jsonl`** | The **UUID-/correlation-id-linked operational trail** (`spa_core/audit/audit_trail.py`, MP-310). Threads one paper-cycle's events (`cycle_start → allocation_proposal → risk_verdict → trade_*`) via `correlation_id` + `prev_event_id`. It is for **operational traceability / debugging a cycle**, *not* hash-chained tamper-evidence. | **No** — linked by UUIDs, **not** by `prev_hash`/`entry_hash`. A forged historical row is **not** detectable from the file alone. | No. It is out of scope for the proof verifier. |

**Mnemonic:** *`audit_chain` = the **chain** (hashes, tamper-evident).
`audit_trail` = the **trail** (UUIDs, operational).* Everything in §1–§7 below is about the
hash chain and its public mirror. `audit_trail.jsonl` is mentioned here only so it is never
mistaken for the tamper-evidence.

---

## 1. The public file

`data/rates_desk/decision_log.jsonl` — JSON Lines (one JSON object per line, UTF-8). It is also
served live at `GET /api/rates-desk/proof` (machine) and `GET /api/rates-desk/refusals`
(human-readable).

> **The public file is ONE coherent chain (re-based, single genesis).** The published mirror is a
> faithful projection of the desk's decisions: the **decision body** of every row (`kind`, `reason`,
> `decomposition`, `proof_hash`, … — everything in the *payload* group below) is verbatim what the
> gate produced, but the **chain-linkage envelope** (`seq`, `prev_hash`, `entry_hash`) is *re-based*
> into a single contiguous chain on every write — `seq` runs `0..N` with no gaps, `prev_hash` links
> each row to the previous row's `entry_hash`, and the genesis row's `prev_hash` is `"0"*64`. This is
> why §5 below verifies the file **standalone**, with a single genesis and `head_hash` = the **last**
> row's `entry_hash`. (The authoritative append-only producer ledger lives separately at
> `data/audit_chain.jsonl`; the public file is the re-based, ring-buffered human-readable mirror of it.)

Each line is **one decision** (an `ENTRY` or a `REFUSAL`) and has this shape:

```json
{
  "seq": 111,
  "ts": "2026-06-26T06:27:28.571374+00:00",
  "prev_hash": "38686a8a…a832",
  "entry_hash": "ae498925…56e8",
  "kind": "ENTRY",
  "approved": true,
  "reason": "none",
  "as_of": "2026-06-26",
  "underlying": "susds",
  "shape": "fixed_carry",
  "net_edge": "0.09474696329061730666666666667",
  "approved_size_usd": "6924.1019958808305625",
  "decomposition": { … see §4 … },
  "detail": { … },
  "proof_hash": "6dc2b810…879d"
}
```

> The hashes/values above are the **real** row at `seq == 111` in the current published log (truncated
> for readability); §3's worked example recomputes its full `entry_hash` from the raw line.

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

> **Worked example (real row, seq=111).** Running the recipe above on the row whose `seq == 111` in the
> *current* published log (`underlying: "susds"`, `kind: "ENTRY"`,
> `prev_hash: 38686a8a97b80d7995de8c048a54fdd76e515f92f712f6309e29692fd0c5a832`) yields
> `ae49892550006e0dff2252d7d84da61230451e2e2e7380ce0b818b7e766556e8`, which equals that row's stored
> `entry_hash`. (Confirmed in the test suite — see §7.)
>
> **Derive-it-yourself (don't trust the literal above — recompute it):** the published log is a
> ring-buffered mirror, so the row at any fixed `seq` changes as the chain grows; rather than trust a
> pinned literal, recompute it from whatever the log holds *right now*:
> ```bash
> python3 - <<'PY'
> import json, hashlib
> ENVELOPE = ("seq", "ts", "entry_hash", "prev_hash"); EVENT_TYPE = "rates_desk_decision"
> rows = [json.loads(l) for l in open("data/rates_desk/decision_log.jsonl") if l.strip()]
> row = rows[111]                                    # the row at seq == 111
> payload = {k: v for k, v in row.items() if k not in ENVELOPE}
> canonical = json.dumps({"seq": row["seq"], "ts": row["ts"], "event_type": EVENT_TYPE,
>                         "payload": payload, "prev_hash": row["prev_hash"]},
>                        sort_keys=True, separators=(",", ":"), ensure_ascii=False)
> got = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
> print("recomputed:", got); print("stored    :", row["entry_hash"]); print("MATCH:", got == row["entry_hash"])
> PY
> ```
> prints `MATCH: True` — the recompute equals the stored `entry_hash` of whatever row currently sits at
> `seq == 111`. (The whole chain is verified the same way by `scripts/verify_spa.py`; see §5/§7.)

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

> **Anchoring caveat — `head_hash` is a *sliding-window* head, not an immutable all-time commitment.**
> Because the public file is a re-based, **ring-buffered** mirror (`LOG_CAP = 2000` rows), `head_hash`
> is stable *across normal appends* (each append extends the same single-genesis chain), but it
> **re-bases — and so shifts — when the ring-buffer evicts the oldest rows** (past 2000 decisions, the
> genesis moves forward and every `seq`/`prev_hash`/`entry_hash` is recomputed). Therefore the
> "anchor the head now and re-check it later" recipe is a valid immutability proof **only within the
> current window**: it proves nobody rewrote in-window history between your two checks. **Cross-eviction**
> immutability — the all-time guarantee that no decision was ever silently dropped or altered, even
> after it falls out of the window — is provided by the separate authoritative **append-only** producer
> ledger `data/audit_chain.jsonl`, which is never re-based or truncated. The public file remains, at
> *any* point in time, one coherent, single-genesis, forge-rejecting chain (§5 verifies it standalone);
> the only nuance is that its head is a window head, so do not read it as a permanent all-time anchor.

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

## 6. The `exit-nav` `proof_hash` (a separate published proof_hash)

`GET /api/rates-desk/exit-nav` publishes a per-ticket liquidation schedule, and **every schedule row
carries its own `proof_hash`** (the adversarial note: every published `proof_hash` should be spec'd).
It is *not* part of the decision chain above — it is a standalone, reproducible digest computed with
the **same canonical-JSON + SHA-256 rule** (§2).

> **TAMPER-EVIDENCE (spec v1.0 hardening).** The `proof_hash` is taken over the row's published
> **INPUTS *and* OUTPUTS *and* its `prev_hash`** — not the inputs alone. This closes two attacks a
> skeptic demonstrated against an inputs-only hash:
> 1. **Forged output:** publishing a fabricated `net_proceeds_usd` / `haircut_pct` /
>    `price_impact_frac` / `flagged` / `flag_reason` / `time_to_exit_days` on a real row. With the
>    outputs INSIDE the hashed object, any such forgery diverges the recompute.
> 2. **Unchained row:** reordering, dropping, or inserting a row. Every row carries a `prev_hash`
>    linking it to the previous row's `proof_hash` (the first row in each schedule uses the genesis
>    `prev_hash = "0"*64`), so the schedule is a **verifiable chain** — a reordered/dropped/inserted
>    row breaks the linkage.

The hashed object is `{ "inputs", "outputs", "prev_hash" }`:

```python
import json, hashlib

def exit_nav_proof_hash(proof_obj: dict) -> str:
    # proof_obj = { "inputs": {...}, "outputs": {...}, "prev_hash": "<hex64>" }
    blob = json.dumps(proof_obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
```

where the three groups are reconstructed verbatim from the published row:

```
inputs   = { "ticket_usd", "gross_usd", "depth_usd", "as_of", "model", "model_params", "data_source" }
outputs  = { "net_proceeds_usd", "haircut_pct", "price_impact_frac", "flagged", "flag_reason",
             "time_to_exit_days" }
prev_hash = the row's "prev_hash" field   ("0"*64 for the first row of each schedule)
```

and `model_params = { dex_routing_cost_bps, operational_haircut_bps, max_size_frac_of_exit,
min_dex_pool_tvl_usd }`. All of these fields are present verbatim in the published schedule row, so a
third party reconstructs `{inputs, outputs, prev_hash}` from the row and recomputes `proof_hash` —
confirming both that the published number was derived from the stated inputs/model **and** that no
output was forged after the fact, and (via the chain) that no row was reordered or dropped.

**Verify the chain** (per schedule section): walk rows in order; row 0's `prev_hash` must be `"0"*64`;
each subsequent row's `prev_hash` must equal the previous row's `proof_hash`; and every row's
`proof_hash` must recompute from its `{inputs, outputs, prev_hash}`. The first row that fails either
check is the break.

> **The rule applies to EVERY schedule section, each its own chain.** `exit_nav.json` carries three
> schedule groups; **every row in all three** carries its own §6 `proof_hash` + `prev_hash`, and each
> group is an independent chain (its own genesis):
> 1. `schedule[]` — the desk's OWN open book (single live market);
> 2. `illustrative.schedule[]` — a labeled hypothetical on the deepest real market (demonstration);
> 3. `portfolio.markets[*].schedule[]` — the **portfolio-wide** schedule: EVERY open position **and**
>    EVERY priced market on the surface, each row against **that market's own single-market depth**.
>    `depth_usd` in any portfolio row is the market's resolved single-market contemporaneous depth —
>    **NEVER** the `portfolio.aggregate_depth_usd` (which is disclosure-only; depths are never summed,
>    since a forced unwind cannot route one market's exit through another's pool). The verifier
>    recomputes the `proof_hash` AND the `prev_hash` chain of all rows across all three groups.

---

## 6a. Cross-eviction immutability anchors (`anchors.jsonl`)

`data/rates_desk/anchors.jsonl` (served at `GET /api/rates-desk/anchors`) is the **append-only,
monotonic** ledger that closes the §5 *sliding-window* caveat. Each line is one anchor:

```json
{ "event_type": "rates_desk_anchor", "seq": 0, "ts": "2026-06-28T02:51:06+00:00",
  "head_hash": "0bbfe1fd…3984c", "chain_length": 394,
  "note": "GENESIS RESET 2026-06-28: pre-correction anchors invalidated by the structural tail-veto security correction (see below)" }
```

> **One-time documented GENESIS RESET (2026-06-28).** The public `decision_log.jsonl` was legitimately
> REGENERATED for a SECURITY fix — the structural tail-comp veto was corrected, removing a toxic-LRT
> (ezETH) approval — which produced a NEW chain head. Every PRE-correction anchor (the old genesis
> `head_hash 91af3076… @ chain_length 386`) checkpointed a head that the *corrected* chain no longer
> reproduces, so it became **structurally invalid** (case (b) below would reject it). The ledger was
> therefore RESET to a fresh `seq:0` genesis anchor over the corrected head, carrying a mandatory `note`
> that records the invalidation reason. This is NOT a silent rewrite: the reset is recorded on the
> anchor itself and in this spec, and the ledger is **append-only from this new genesis** going forward.
> A genesis reset is sanctioned ONLY when the underlying decision log is itself legitimately regenerated
> for a correctness/security fix — never to paper over a tamper. The `note` field is purely informational
> (the verifier ignores it; it participates in no hash).

- `head_hash` is the **public decision chain's `head_hash`** (§5 — the last row's `entry_hash`) at the
  moment the anchor was minted; a value a third party RE-DERIVES with the §5 recipe.
- `chain_length` is the public mirror's row count at that checkpoint.
- `seq` is the anchor's own monotonic `0..N` index in **this** ledger (append-only, never re-based).

**Verify the anchor ledger** (what `scripts/verify_spa.py` and `GET /api/rates-desk/anchors` both do):
1. **Append-only / monotonic** — `anchor.seq == index` (0-based, contiguous), and `chain_length` is
   non-decreasing across anchors (the chain only grows).
2. **Head consistency, as far as the PUBLIC files allow.** Because the public mirror is a single-genesis,
   re-based chain, the head at **any in-window length K** equals `rows[K-1].entry_hash` (§5). So:
   - **(a) Current head** — the anchor whose `chain_length` equals the re-derived current chain length
     must carry that exact re-derived `head_hash`.
   - **(b) Historical, still in-window** — an anchor whose `chain_length = K < current_length` and whose
     checkpointed prefix is **still present** in the published file (row `K-1` exists) must carry
     `head_hash == rows[K-1].entry_hash`. This IS independently checkable, so a **fabricated historical
     anchor** (a wrong head at an older in-window length) is **REJECTED** — it does *not* silently pass.
   - **(c) Uncheckable from public files** — an anchor whose prefix has been **evicted** from the ring
     buffer (`K-1` no longer present, e.g. the genesis moved past it), or that claims **more** rows than
     the published chain, **cannot** be re-derived from the public files alone. The verifier marks it
     `uncheckable` and **reports the count** (`n_uncheckable`) rather than passing it off as proven.

> **HONEST SCOPE — what one anchor proves TODAY.** With a single in-window anchor, the verifier proves
> exactly an **in-window head checkpoint**: that the published chain at the checkpointed length still
> hashes to the recorded head. It does **NOT**, by itself, deliver **cross-eviction immutability** —
> the all-time guarantee that no decision was ever silently dropped or altered after it fell out of the
> ring-buffer window. Case (c) anchors are precisely the ones that *would* require that stronger proof,
> and the public ring-buffered files cannot supply it. **Cross-eviction proof requires the authoritative
> append-only producer ledger** (`data/audit_chain.jsonl`, never re-based or truncated). Until that
> producer ledger (or a verifiable tail of it that re-derives the public mirror) is published, the
> marketing/spec claim is limited to: *each in-window anchor is a re-derivable head checkpoint; a
> fabricated in-window anchor is rejected; cross-eviction immutability is backed by the (not-yet-public)
> producer ledger, not by these files.* No over-claim.

Because the anchor file is append-only and never truncated, recording an anchor now and re-running the
verifier later proves no in-window history was rewritten between the two checks. Extending that to a
full **cross-eviction** guarantee requires the producer ledger above.

---

## 6b. Proof-breadth surfaces — the SAME recipe on the other desks (WORKSTREAM 2)

The verifiable hash-chain pattern is extended from the rates desk to the OTHER desks, so a third
party verifies EVERY published surface with ONE command (`python3 scripts/verify_spa.py data/` — it
recursively auto-discovers all of them, one exit code). Each learns from the two flaws the rates-desk
red-team caught: the proof covers the **OUTPUTS** (the user-facing numbers), not just the inputs,
**and** the rows are **chained** (per-row `prev_hash`); and every published artifact is regenerated
together with its producer so it never rots.

### (E) Tournament ranking chain — `data/tournament/decision_log.jsonl`

One row per ranked strategy per daily ranking, in a single-genesis chain. `entry_hash` uses the §3
recipe with `event_type = "tournament_ranking_row"` and `payload` = the row minus the four envelope
keys `{seq, ts, entry_hash, prev_hash}`. The payload carries the OUTPUTS — `rank`, `strategy_id`,
`sharpe`, `net_annual_return_pct` (+ `strategy_key`/`name`/`sharpe_display`/`max_dd_pct`/
`is_shadow_active`/`ranking_generated_at`) — so forging a published rank/strategy/sharpe/net-return,
or reordering a ranking, diverges the recompute (precise `broken_at`). Verify exactly as §5.

### (F) RWA-backstop NAV forward-record proof — `data/rwa_backstop/nav_proof.jsonl`

One row per daily forward NAV point, using the §6 exit-NAV recipe (`proof_hash` over
`{inputs, outputs, prev_hash}`, `default=str`), chained. `inputs = {date, ts, n_assets,
onchain_4626_count, off_chain_estimate_count}`; `outputs = {tvl_weighted_nav, liq_nav_gap_pct}`;
`prev_hash` links each point to the previous row's `proof_hash` (genesis `"0"*64`). Forging
`tvl_weighted_nav` / `liq_nav_gap_pct`, or reordering/dropping a forward point, diverges the
recompute / breaks the chain. Verify exactly as §6 (the chain walk).

### (G) Sleeve forward-series proofs — `data/rates_desk/paper/<sleeve>_series_proof.jsonl`

One chain PER sleeve (auto-discovered — there may be many). `entry_hash` uses the §3 recipe with
`event_type = "sleeve_forward_point"`, keyed by `date`, `payload` = the row minus `{seq, date,
entry_hash, prev_hash}`. The payload carries the OUTPUT forward numbers the promotion ladder reads —
`equity_usd`, `net_apy_pct`, `open_books`, `closed_books`, `approvals`, `refusals` (+ `sleeve_id`/
`ts`) — so forging a forward equity/apy/book-count, or reordering/back-dating a day, diverges the
recompute. Verify exactly as §5.

> **Never-rot (F1):** each producer regenerates its own proof artifact immediately after producing
> (folded into `agent_tournament_engine.sh` / `agent_rwa_safety_board.sh`), and the hourly
> `scripts/refresh_published_proof.py` regenerates ALL of them from their producers' latest data and
> self-verifies the whole `data/` dir — so the published proofs never go stale relative to the data.

---

## 7. Determinism & test anchor

The recipe is deterministic: same file → same hashes on any machine, any language, any year. The repo
proves the recipe is correct in `spa_core/tests/test_public_refusal_log.py`
(`test_proof_chain_spec_reproducible` recomputes a stored `entry_hash` straight from the raw JSONL,
following *only* this document, and asserts the match).

**Invariants** (never silently change without a new spec version):
canonical JSON = `sort_keys=True, separators=(",",":"), ensure_ascii=False`; `event_type =
"rates_desk_decision"`; hash = SHA-256 hex; genesis `prev_hash = "0"*64`; envelope keys =
`{seq, ts, entry_hash, prev_hash}`; all money/rate values are exact decimal **strings**.
