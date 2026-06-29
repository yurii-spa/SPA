# SPA Underwriting Report Specification (Lane C — the Layer-3 moat)

**Status:** canonical · stdlib-only · deterministic · LLM-FORBIDDEN · fail-CLOSED · IS_ADVISORY
**Audience:** any third party who wants to **independently re-derive and verify** the desk's
underwriting report — *without running our code* — and a buyer evaluating it as risk infrastructure.

The desk's durable moat is **not** a higher yield (proven not to scale). It is being the party that
can **PROVE what it refuses**, sold as **underwriting-grade risk infrastructure**. This scales without
a capacity ceiling because what is sold is the **MEASUREMENT + the PROOF**, not deployed capital.

This document is the exact, self-contained recipe to recompute every hash in
`data/underwriting/report_proof.jsonl` from the public file and confirm the report was not altered
after the fact — and to confirm the desk never sells, as underwritten capacity, a market it refused.

---

## 0. The two artifacts

| File | What it is |
|---|---|
| **`data/underwriting/underwriting_report.json`** | The full report document (pretty, sorted JSON). The human/buyer-facing artifact: meta, per-market refusal verdicts, depth-at-size, the realized-at-size verdict, and the underwritten-capacity list — each section carrying its own `proof_hash` and chain envelope. |
| **`data/underwriting/report_proof.jsonl`** | The **proof chain**: one JSON line per report SECTION, single-genesis, contiguous `seq`, prev-linked. This is the file `scripts/verify_spa.py` (surface **H**) re-derives. |

Both are **always written to `data/`** (so the proof chain grows and stays verifiable). Public
surfacing (API / landing / commercial sale) is **owner-gated** — see §5.

---

## 1. The honesty rule (the whole point of Lane C)

Lane C **READS Lane B's killer verdict VERBATIM** and **MUST NOT recompute a happy number.**

The realized-at-size verdict — `verdict` (`SURVIVES_AT` / `DOES_NOT_SURVIVE_PAST` /
`INSUFFICIENT_DATA`), `survives_at_aum_usd`, `floor_plus_bps_at_5M` — is copied **byte-for-byte** from
Lane B's `data/rates_desk/realized_at_size.json` into the report's `realized` section. There is, by
construction, **no arithmetic** in the report builder that touches B's numbers
(`report.read_realized_verbatim` is a pure passthrough; a structural AST test asserts it contains no
arithmetic op or `round/sum/max/min` call).

A guard test (`test_underwriting_report.py::test_survives_at_aum_usd_is_byte_for_byte_lane_b`) asserts
the published value equals the raw JSON value byte-for-byte. **A recompute path would diverge and the
test fails loudly** — this kills happy-laundering at the source.

---

## 2. The frozen data contract

Lane C **READS** (verbatim, never recomputes):

| Input | Source | Used for section |
|---|---|---|
| killer verdict | `data/rates_desk/realized_at_size.json` (Lane B) | `realized` |
| depth-at-size | `data/rates_desk/depth_at_size.json` (Lane B) | `depth` |
| per-market refusal verdicts | `data/refusal_status.json` | `refusals` + capacity exclusion |

> If Lane B's files are not present yet, the report is built against a documented fixture matching the
> schema (`spa_core/tests/fixtures/underwriting/`). The fixture `realized_at_size.json` carries
> `verdict`, `survives_at_aum_usd`, `floor_plus_bps_at_5M`, and a `markets[]` list — the exact shape
> Lane B publishes.

Lane C **PRODUCES**: `underwriting_report.json` + `report_proof.jsonl` (above).

fail-CLOSED: a missing/corrupt `realized_at_size.json`, or a `verdict` outside Lane B's vocabulary,
→ **no report is written** (no partial/forged artifact). A corrupt refusal file also fails closed (we
cannot prove refusal-consistency without it). The depth section degrades to `available: false` rather
than failing the report (it is supporting, not load-bearing).

---

## 3. The report sections (in chain order)

| seq | `section_id` | content |
|---|---|---|
| 0 | `meta` | schema version, advisory flags, the publish gate (`published`, `publish_gate: "owner"`), the honesty-rule statement |
| 1 | `refusals` | the per-market refusal verdicts (VERBATIM) — the desk's discipline |
| 2 | `depth` | depth-at-size (VERBATIM, Lane B) |
| 3 | `realized` | the killer verdict + `survives_at_aum_usd` + `floor_plus_bps_at_5M` (**VERBATIM, Lane B**) |
| 4 | `capacity` | the underwritten-capacity markets, with **every REFUSED market EXCLUDED** + an auditable `excluded_refused_markets` list |
| 5 | `per_market` | **W2 (C2.1)** — THE PRODUCT: EVERY market in the universe (realized ∪ refusals ∪ depth) appears ONCE with its `refusal_verdict`/`refusal_reason`/`tail_score`, its `depth` row, its `realized` row, a `status` ∈ {`REFUSED`,`UNDERWRITTEN`,`WATCH`,`NO_REALIZED_TRACK`}, and a plain `why`. Every field is **VERBATIM** — the only synthesis is a deterministic join + a labelled status; **no arithmetic** touches a Lane-B number. A `REFUSE` market is pinned `status: REFUSED`, `underwritten: false` (never sold as capacity). A flagged-insufficient depth row keeps its NULL bounds (no fabricated number). |
| 6 | `fundability` | **W2 (C2.4)** — the honest thesis number: `thesis_floor_plus_bps_band: [50, 150]` at `target_aum_usd: 5,000,000` — emphatically **NOT** `not_claimed_floor_plus_bps: 1000`. Embeds Lane B's realized verdict **VERBATIM** (`lane_b_verdict` / `lane_b_survives_at_aum_usd` / `lane_b_floor_plus_bps_at_5M`) so a funder reads the truth, including `INSUFFICIENT_DATA` / a null at a thin track. |

> **W2 honest-framing rule:** the report states a THESIS band (floor + 50-150 bps) as a thesis, and Lane B's REALIZED verdict as the realized fact — never blends them. The realized number is never "upgraded" (a `DOES_NOT_SURVIVE_PAST` / a sub-floor `floor_plus_bps_at_5M` flows through unchanged). See `docs/FUNDABLE_HONEST.md`.

---

## 4. The hash recipes (re-derive with zero dependencies)

The **canonical-JSON rule** is the one from `PROOF_CHAIN_SPEC.md` §2:
`json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`, UTF-8, SHA-256, lower hex.

**Per-section `proof_hash`** — over the section body alone:

```python
body = {k: v for k, v in section.items() if k not in ("proof_hash","seq","prev_hash","entry_hash")}
proof_hash = sha256(canonical(body))
```

**Chain `entry_hash`** — binds the section (incl. its `proof_hash`) into the prev-linked chain:

```python
payload = {k: v for k, v in section.items() if k not in ("seq","prev_hash","entry_hash")}
entry_hash = sha256(canonical({
    "seq": section["seq"], "section_id": section["section_id"],
    "event_type": "underwriting_report_section", "payload": payload,
    "prev_hash": section["prev_hash"],
}))
```

**Verify the whole chain** (`PROOF_CHAIN_SPEC.md` §5 shape): walk in `seq` order; at each section
require (1) `seq == idx`, (2) `prev_hash == previous.entry_hash` (genesis `"0"*64`), (3) the
per-section `proof_hash` recomputes, (4) the chain `entry_hash` recomputes. `head_hash` = last
section's `entry_hash`. The first failing section is `broken_at`.

---

## 4a. Refusal-consistency (the property a re-sealed chain cannot fake)

A market the `refusals` section published as **`REFUSE`** must **never** appear in the `capacity`
section's `capacity_markets`. The verifier enforces this as a **cross-section property** over the
*verified* sections:

```
refused      = { v.symbol for v in refusals.verdicts if v.verdict == "REFUSE" }
capacity_syms= { m.symbol for m in capacity.capacity_markets }
refusal_consistent = (refused ∩ capacity_syms) == ∅
```

This is the hardest red-team to defeat: even if an attacker smuggles a REFUSED market into capacity
**and fully re-seals the chain** (every per-section + chain hash valid), the verifier still rejects it
(`refusal_consistent = False`, naming the smuggled market) — because the attacker would have to also
relabel the published `REFUSE` verdict, which is itself a published, hash-anchored fact. The desk
cannot sell as underwritten capacity a market its own refusal log says it refused.

---

## 5. Owner-gated publication (`SPA_UNDERWRITING_PUBLISH`, default OFF)

The report is **always generated and written to `data/`** (the proof chain must grow + be verifiable),
but it is **NOT surfaced publicly** (no API/landing exposure) until the owner flips
`SPA_UNDERWRITING_PUBLISH` to a truthy value (`1`/`true`/`yes`/`on`). When OFF (the default, and any
non-truthy/unset value), the report carries `"published": false` and `"publish_gate": "owner"`.
**Commercial sale of the underwriting report is owner-gated.**

**W2 (C2.3) — the flag-gated API surface.** Three GET endpoints (registered in `server.py` via
`routers/underwriting.py`) surface the report — but ONLY when the flag is ON; otherwise every route
returns **404** (`{"error": "underwriting_surface_disabled"}`):

| endpoint | content |
|---|---|
| `GET /api/underwriting/report` | the full `underwriting_report.json` served **VERBATIM** (the honesty rule reaches the wire — the API never laundters a happier number than the file) |
| `GET /api/underwriting/proof` | the `report_proof.jsonl` section chain + a LIVE verification (per-section proof_hash + entry_hash chain + refusal-consistency) whose verdict matches `verify_spa.py` byte-for-byte |
| `GET /api/underwriting/full-chain` | the COMPLETE `report_proof.jsonl` bytes (uncapped, `text/plain`) for clean-machine reproduction |

Posture (WS2): GET-only, read-only, graceful, fail-CLOSED (never a 500), defense-in-depth key
redaction. The CORS/rate-limit middleware is inherited from the app factory. A missing report (flag
ON) is an honest `available: false`, never a fabricated payload.

---

## 6. Verify it yourself (zero dependency)

```bash
python3 scripts/verify_spa.py data/underwriting/                 # exit 0 on a clean chain
python3 scripts/verify_spa.py data/underwriting/ --expect-surfaces H   # fail CLOSED if H absent
python3 scripts/verify_spa.py data/                              # surface H discovered alongside A–G
```

A tampered value (without re-seal) → precise `broken_at`. A smuggled REFUSED market (even fully
re-sealed) → `refusal_consistent: False` with the smuggled market named. No `spa_core` import, no
network.

### 6a. The public-verifiability dry run (W2 / C2.2)

`scripts/underwriting_verify_dryrun.py` simulates a **third party** who has none of our code: it copies
**ONLY** `scripts/verify_spa.py` + `data/underwriting/report_proof.jsonl` into a fresh `/tmp` dir and
runs the verifier there with `PYTHONPATH` cleared and cwd = the clean dir (so `spa_core` is
unimportable), asserting (1) exit 0 on the clean chain, (2) a tamper is caught (negative control),
(3) the verifier file contains no `import spa_core`.

```bash
python3 scripts/underwriting_verify_dryrun.py            # run the dry run → "PASS"
python3 scripts/underwriting_verify_dryrun.py --recipe   # print the reviewer recipe only
```

**Reviewer recipe** (what a skeptic actually does):

```bash
mkdir /tmp/clean && cd /tmp/clean
cp <spa>/scripts/verify_spa.py .
cp <spa>/data/underwriting/report_proof.jsonl .
python3 verify_spa.py report_proof.jsonl                       # exit 0 ⇒ verified
python3 verify_spa.py report_proof.jsonl --expect-surfaces H   # fail-CLOSED if H absent
```

---

## 7. Build / CLI

```bash
python3 -m spa_core.strategy_lab.underwriting.report --build    # write both artifacts
python3 -m spa_core.strategy_lab.underwriting.report --check    # in-memory, print head, write nothing
# explicit Lane-B inputs (e.g. before B's canonical files land):
python3 -m spa_core.strategy_lab.underwriting.report --build \
    --realized data/rates_desk/realized_at_size.json \
    --depth    data/rates_desk/depth_at_size.json \
    --refusal  data/refusal_status.json
```

Deterministic: same inputs + same `--generated-at` → byte-identical artifacts (incl. all hashes).

---

## 8. Safety contract

stdlib-only · deterministic · fail-CLOSED · atomic (tmp + `os.replace`, same-dir) · **IS_ADVISORY**
(moves no capital, touches no risk/execution, **never** the go-live track) · **LLM-FORBIDDEN** · **NO
`spa_core.execution` import** · owner-gated publication.

**Cross-lane contract note (for the weekly sync):** §1/§4 fix the exact field names Lane C reads from
Lane B (`verdict` ∈ {`SURVIVES_AT`,`DOES_NOT_SURVIVE_PAST`,`INSUFFICIENT_DATA`},
`survives_at_aum_usd`, `floor_plus_bps_at_5M`, `markets[].symbol`). If Lane B's emitted schema differs
(e.g. a different verdict spelling or per-market key), the verbatim reader fail-CLOSES — so the schema
must be agreed at the sync before B's canonical `realized_at_size.json` lands.
