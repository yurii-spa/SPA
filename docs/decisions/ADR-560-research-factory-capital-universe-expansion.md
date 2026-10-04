# ADR-560 · RM-EXPAND-01 · Capital universe expansion + Research Factory v1

**Status:** ACCEPTED — architecture frozen after independent review; implemented, reviewed (REWORK → CLOSED) · **Date:** 2026-10-04 · **Owner:** @yurii
**Boundary:** RESEARCH / PAPER only. Real capital $0. Nothing moves money, signs, broadcasts or orders. RiskPolicy,
stops, leverage limits, tiers and live admission are untouched. No candidate is live-authorized.
`CIO_ELIGIBLE` means only that Oracle (`chief_investment_officer`) may consider a sleeve in PAPER/ADVISORY allocation.

## Phase 0 — what already exists (audit 2026-10-04, three independent auditors)

The factory must extend what works and must not add a fifth basis engine or a third ledger copy.

| Found | State | Verdict |
|---|---|---|
| `trading_research/lifecycle.py` + `evidence.py` (ADR-525) — DISCOVERED→…→ROBUST auto, owner steps, LIVE refused in code, hash-chained SQLite evidence | live, BTC only, 138 candidates | **REUSE** — projected into the registry read-only (`OBSERVE_ONLY`); its evidence stays where it is |
| `adapter_sdk/discovery.py` via `paper_trading/discovery_step.py` → `data/candidate_registry.json` | live daily, 16,989 pools → 25 | **REUSE** as the DeFi intake; defects recorded (age gate never measured; Sky slug miss) |
| `defi_engine/mechanics.py` `MECHANICS` | live, advisory | **REUSE** — the factory's mechanism taxonomy maps onto it (`defi_mechanic`) |
| `investment_cio/contract.measured/absent` cells | live | pattern reused (factory cells add ESTIMATED_WITH_METHOD / NOT_APPLICABLE and a source class) |
| `strategy_lab/data/rwa_feed.py` → `rwa_floor_curve.json` (7 T-bill pools, 101 days) | live 5.5 h | **REUSE** — tokenised-treasury observed rates |
| `strategy_lab/rwa_backstop` → `rwa_safety_board.json` (11 RWA assets, exit verdicts, documented redemption) | live | **REUSE** — RWA facts (documented ≠ observed) |
| Sky/sUSDS live rate (`adapter_status.json`, `sky_status.json` GSM 48 h on-chain) | live | **REUSE** — savings rate |
| `strategy_lab/data/funding_feed.py` (5-venue keyless median) → `market_data/funding.json` | live 0.2 h, 167 d | **REUSE** — the ONE canonical funding source |
| `strategy_lab/strategies/variant_n.py` (LRT + short ETH perp paper) | live | REUSE (mislabelled "swarm blend" in the CIO — fixed here) |
| aggressive_lab `susde_dn` | inputs **frozen at 2026-07-05** (60/61 forward rows identical), funding counted twice, no ETH-leg P&L | **REPAIR honesty**: frozen forward rows are labelled; the factory never counts them as forward evidence |
| BTS chain (`bts-feed`, `bts-monitor`, `s_basis`), S71, S72, S8, aggressive_lab `lrt_neutral`, `hy_cycle` regime proxy | quarantined / stand-in / duplicate | **SUPERSEDE** (recorded, not deleted) |
| `capital_shadow/readiness.py:581` "stale Basis feed" | a hard-coded literal | **REPAIR** — derived from the factory's basis-track measurement |
| CIO `market_neutral_basis` strand "rates_desk (fixed carry)" | actually the go-live equity chain (double count) | **REPAIR** — strand removed; variant_n relabelled; freshness per strand (oldest input wins, not freshest) |
| Counterparty-risk source | **none exists** (confirmed) | **BUILD** — WP-A05 |
| Equities / options data | nothing in repo; no free survivorship-free equity universe; no free historical options chains | **ARCHITECTURE_ONLY** both (see WP-S05) |
| Hash-chained ledgers | two deliberate copies (`investment_cio`, `capital_shadow`) | **shared helper** `spa_core/utils/hash_ledger.py` for the factory; migrating the two live copies is recorded debt, not done here |

Security debt (fingerprint-only, no value printed): `~/bot.py` holds one Telegram bot token and
`~/Documents/push_v317.html` one classic GitHub PAT — **neither matches any active Keychain credential**
(8 compared); `~/Documents/spa_push.html` holds no credential-shaped string. Classification: STALE_CREDENTIAL
relative to the system (provider-side revocation not measured). No current exposure; recorded as a
**hard prerequisite before any real-money pilot**: revoke at the provider, then delete. Also preserved as live
blockers: the plaintext incident nonce (ADR-556 L6) and local-only anchors.

## Decision

### WP-A01 · `CapitalOpportunityCandidate` (`research-candidate/1`)
Fields: `contract.CANDIDATE_FIELDS` (identity, 12 value cells, 10 risk cells, state fields). Every value is a
`cell(state, …)` with state ∈ MEASURED · ESTIMATED_WITH_METHOD · NOT_MEASURED · NOT_APPLICABLE · STALE; only the
first two carry a number; MEASURED needs source_ref + source_class + as_of; an estimate needs a named method.
A missing value is never 0.

### WP-A02 · mechanism-first taxonomy
`contract.MECHANISMS` (15 ids after the review) each with asset class, who pays, and the `defi_engine` mechanic it maps to.
Identity is `exposure_key = mechanism | instrument exposure | network` — protocol name and URL are NOT part of
it, so the same exposure from two scanners or two front-ends is ONE candidate; `candidate_id = sha256(key)[:20]`.

### WP-A03 · lifecycle
`contract.TRANSITIONS` — DISCOVERED → SCREENED → RESEARCH_READY → PAPER_CANDIDATE → PAPER_ACTIVE →
EVIDENCE_ACCUMULATING → CIO_ELIGIBLE, with hold states REJECTED · STALE · DATA_INSUFFICIENT · RISK_UNRESOLVED ·
COUNTERPARTY_UNKNOWN · DUPLICATE_EXPOSURE · PAUSED · SUPERSEDED, and OBSERVE_ONLY for candidates owned by another
engine. A hold state goes back only to SCREENED (a fresh re-screen). PAPER_ACTIVE is reachable only through the
admission gate; CIO_ELIGIBLE only through the eligibility gate. Rejection is a successful outcome.

### WP-A04 · provenance
Source classes `contract.SOURCE_CLASSES`. Returns are four separate kinds — advertised · observed · realised
paper · modelled — never interchangeable. Admission needs an observed return from an admissible class; an
advertised-only candidate fails `not_advertised_only`. Freshness limits per source family (`FRESHNESS_MAX_AGE_H`).

### WP-A05 · counterparty model
Per candidate: the named roles (`COUNTERPARTY_ROLES`: issuer, custodian, borrower, market maker, exchange,
redemption agent, legal entity, oracle provider, bridge) and per dimension (`COUNTERPARTY_DIMENSIONS`) a state ∈
OBSERVED · DOCUMENTED · UNKNOWN · NOT_APPLICABLE with its source. **No blended rating.** The summary is counts and
named concerns. UNKNOWN is never safe: paper admission needs every APPLICABLE role NAMED (`counterparty_named`);
CIO eligibility needs no role UNKNOWN.

### WP-A06 · `PaperAdmissionReport` (`paper-admission/1`)
Gates `contract.ADMISSION_GATES`; each PASS / FAIL / UNKNOWN with evidence; UNKNOWN never passes. Admission writes
an **immutable admission snapshot** (candidate state + gate evidence + source refs) to the ledger; forward
evidence counts only from it.

### Storage / integrity
One append-only hash-chained ledger `data/research_factory/ledger.jsonl` (kinds: candidate_snapshot, transition,
admission, observation, counterparty, run) with sibling anchors `data/research_factory_anchors/`, built on the
new shared `spa_core/utils/hash_ledger.py` (keyed idempotency, flock, run lock exit 75). `index.json` and
`status.json` are disposable read models rebuilt from the ledger. Snapshot rows are written only when the
fingerprint changes (no daily duplicates); observations are keyed `(candidate_id, date)`.

### Tracks (WP-S02…S05)
* **Cash / Treasury** — STABLECOIN_SAVINGS (sUSDS, sDAI: live rate from `adapter_status`, GSM from `sky_status`)
  and TOKENISED_TREASURY (the T-bill pools behind `rwa_floor_curve`, issuer facts from `rwa_safety_board`).
  The 5 % cash buffer is not touched.
* **Market-neutral / basis** — FUNDING_CAPTURE (ETH, BTC) from the canonical funding median; the spot-perp basis
  leg is NOT_MEASURED (no client) and stays so; DELTA_NEUTRAL_CARRY (sUSDe) from the live DeFiLlama sUSDe rate +
  funding as a regime signal; susde_dn's frozen forward rows are NOT forward evidence. No new engine.
* **RWA / stable yield** — the 11 safety-board assets + discovery RWA pools: backing asset, obligor, redemption
  (documented vs observed), duration, liquidity, fees, jurisdiction, custody, issuer, on/off-chain dependency.
  "Tokenised treasury" is never treated as risk-free.
* **DeFi discovery** — `candidate_registry.json` rows become DISCOVERED candidates (deduped by exposure).
* **Trading research** — projected read-only (OBSERVE_ONLY), never re-admitted here.
* **Equities — ARCHITECTURE_ONLY:** no free survivorship-free universe or audited total-return series; a strategy
  on a survivor-biased free universe would manufacture flattering evidence. Contract slot only.
* **Options — ARCHITECTURE_ONLY:** no free historical chains; the three existing options analytics are written
  off as fixtures; `docs/43` #17 requires tail decomposition first. A forward-only Deribit public-chain collector
  is the named next step, not built here.

### WP-S06 · forward paper factory
Admission snapshot → daily forward observations (observed rate with source/as_of, accrual on a notional, costs as
cells) → realised paper outcome → maturity = count of valid forward periods recorded on/after admission with a
MEASURED observed rate. Backfill may be stored (`kind=observation`, `backfill=true`) and never counts. No row is
edited; corrections are new rows.

### WP-S07 · Oracle boundary
cio-policy-v1 is unchanged. The factory publishes a read model the CIO exposes as a separate, non-sleeve
`research_universe` view (OBSERVE_ONLY / PAPER_ACTIVE / CIO_ELIGIBLE). It is never an input to weights. A
research candidate can become an allocatable CIO sleeve only by a later ADR adding its sleeve row, and the
builder then enforces at run time `allocatable = contract flag AND factory state == CIO_ELIGIBLE` (fail-closed).

### WP-S08 · Mission Control
A "Research Universe" section in the existing Capital area — no new dashboard, no buttons — with the banner
`RESEARCH ≠ APPROVED · PAPER ≠ LIVE · CIO_ELIGIBLE ≠ REAL-MONEY APPROVED`.

### Runtime
Agent `com.spa.research_factory`, daily **09:05** (binding #11: before the CIO at 09:30 and shadow at 09:45),
`python -m spa_core.research_factory.run`; reads existing artifacts only — **no new network client**.

## Role identity
Owner selected the display name **Oracle** for `chief_investment_officer` (display metadata only; role_id,
modules, authority unchanged; historical ADRs keep «Штирлиц» where it was true at the time).

## Binding revision after the independent architecture review (2026-10-04) — supersedes conflicting text above

All 16 findings were accepted and applied to `spa_core/research_factory/contract.py`
(`CONTRACT_VERSION = research-factory-contract/1`). This contract is now FROZEN; changing it is an ADR.

1. **No admission bypass (CRITICAL).** PAUSED is split into `PAUSED_PRE_PAPER` (exits only to SCREENED / REJECTED /
   SUPERSEDED) and `PAUSED_PAPER` (entered only from paper states; resumes only to the recorded `paused_from`, through
   that state's gate). `GATED_TARGETS` covers PAPER_ACTIVE and EVIDENCE_ACCUMULATING (both need the same valid admission
   snapshot id), CIO_ELIGIBLE (all CIO gates, re-checked every run; any failure demotes) and SCREENED-from-a-hold (the
   failed gate's input fingerprint must have changed — no re-screen shopping). A test enumerates every path into the
   paper states.
2. **Identity is the held instrument, never a ticker (CRITICAL).** `instrument_id` is a canonical id (contract address,
   DeFiLlama pool uuid, `perp:<asset>:<venueset>`, `fund:<slug>`, `engine:<engine>:<id>`); the network is mandatory and
   canonicalised (`CHAIN_ALIASES`); the key carries `EXPOSURE_KEY_VERSION`. Unresolvable ⇒ DATA_INSUFFICIENT, never a
   symbol fallback. Six Midas "USDC" products stay six candidates.
3. **Economic dedup.** `underlying_root` (wrappers resolved to the root fund/token) and `economic_driver_key` (e.g.
   `SKY_SSR`, `UST_BILL`, `ETH_PERP_FUNDING`) are identity fields. `no_duplicate_exposure` fails on a shared key, a shared
   `underlying_root` with a paper-state candidate, or a holding already in the live books (read from the defi_engine
   exposure). A shared driver is a named correlation group shown to the CIO, not a block. Dedup merges sources into the
   existing record; it never picks a winner by return.
4. **Source roots.** Every cell names its upstream `source_root` (`defillama:yields`, `chain:<id>`, `venue:<name>`,
   `issuer:…`, `doc:…`), not the relaying module: `adapter_status`, `rwa_feed` and discovery all relay DeFiLlama and are
   REPUTABLE_AGGREGATOR. Provenance passes with one PRIMARY root, or an aggregator plus an independent second root;
   independent roots disagreeing by >25 % ⇒ CONFLICTED (fail-closed), never max/mean.
5. **Forward evidence is lookahead- and freeze-proof.** A period counts only if its source `as_of` is after the admission
   `as_of` and strictly newer than the previous counted period's, it was fresh when recorded, and it is not backfill. The
   first-recorded value is frozen; revisions are `revision` rows that never change maturity. Realised return must come
   from an independent series (ERC-4626 share price / exchange-rate delta, read on-chain through the existing
   allow-listed keyless RPC client `capital_shadow.rpc`, eth_call only, 2-of-N quorum); otherwise it is MODELLED and the
   consistency gate is UNKNOWN ⇒ fails. This is exactly the susde_dn failure mode (identical frozen rows) made impossible.
6. **No double counting.** Returns split into `base_return` and `incentive_return` (never counts for admission); every
   cost/funding cell carries `embedded_in_return`; `contract.net_expected_return()` is the one formula and returns
   NOT_MEASURED when any applicable input is not valued.
7. **Cell validation.** MEASURED forbids MODELLED / UNKNOWN / ISSUER_CLAIM sources, requires finite values and a parseable
   non-future `as_of`; new value state DOCUMENTED and source class ISSUER_CLAIM (issuer terms — e.g. the safety board's
   redemption fees/delays — are DOCUMENTED, never MEASURED); gates read only `measured_value_of()`; cells carry
   `recorded_at`, `window`, `precision`.
8. **The readiness repair never opens a pilot path.** `market_neutral_basis` stays in `capital_shadow.readiness`
   `_NEVER_CANDIDATE` unconditionally; only the REASON text is derived from the factory's basis-track measurement. A test
   proves a fresh basis track still yields NOT_READY.
9. **Counterparty bars are deterministic.** `MECHANISMS[m].required_roles` fixes which roles apply. Paper: every required
   role NAMED with a source — acceptable only because capital is $0. CIO: no required role UNKNOWN, and for credit-like
   mechanisms `reserve_transparency` and `redemption_restrictions` ≥ DOCUMENTED from a non-issuer source, with at least
   one dimension OBSERVED.
10. **Leverage.** New mechanisms VAULT_AGGREGATOR and INCENTIVE_EMISSION; basis/funding map to the existing
    `basis` / `delta_neutral` mechanics; gate `leverage_known` (MEASURED required where `leverage_required`); a
    `liquidation_distance` cell for perp legs.
11. **Freshness.** Families by source root (`SOURCE_FAMILY`), documented terms 30 d, counterparty 90 d; in paper states a
    stale period simply does not count and only 3 consecutive stale periods move the candidate to STALE; re-admission
    restarts maturity at 0. The factory runs at **09:05** (before the CIO at 09:30); the CIO trusts the read model only
    if ≤ 26 h old and its `ledger_head_hash` matches the ledger.
12. **Survivor bias.** Ledger kind `disappearance`: a paper candidate that vanishes is DISAPPEARED (terminal, loss
    UNKNOWN) and stays in every statistic; `status.json` reports the denominators (scanned, discovered, truncated,
    rejected, disappeared, …).
13. **Re-screen / dedup winner / re-check** — see 1 and 3.
14. **Oracle boundary.** A future research sleeve row binds `candidate_id` + `exposure_key_version`; `allocatable`
    additionally requires a fresh read model with a matching ledger head; projected candidates are always OBSERVE_ONLY.
    A differential test proves the CIO's weights are byte-identical with and without the research view.
15. **Admission snapshot** content is fixed (`ADMISSION_SNAPSHOT_FIELDS`: contract version, code identity, key version,
    thresholds, gate-input digests, source refs); renames/migrations create a new key with `superseded_by` (maturity is
    not transferred without an ADR); per-instrument T-bill rates come from per-pool data or are NOT_MEASURED — the
    `rwa_floor_curve` aggregate is never assigned to an instrument.
16. Precision field, fingerprint excludes timestamps/freshness, `TRADING_RESEARCH` = PROJECT_ONLY, and an import-graph
    test (no `spa_core.execution`, no capital_shadow writer; only the read-only `capital_shadow.rpc` client is allowed).

## Appendix I — frozen implementation interfaces (packages A core · B tracks · C integration)

**Package layout** (`spa_core/research_factory/`): `contract.py` (frozen) · A: `ledger.py`, `registry.py`,
`lifecycle.py`, `admission.py`, `forward.py`, `eligibility.py`, `counterparty.py`, `dedup.py`, `read.py`, `run.py`,
`failure_matrix.py` + `spa_core/utils/hash_ledger.py` · B: `scanners/{cash_treasury,rwa,basis,discovery,
trading_research}.py`, `counterparty_registry.py`, `onchain.py` · C: integration outside the package.

**Scanner interface (B → A).** Each scanner module exposes
`scan(data_dir: Path, now: datetime, *, rpc_client=None) -> dict` returning
```
{"scanner": "<name>", "domain": <contract.DOMAINS>, "as_of": iso, "status": "OK"|"PARTIAL"|"UNAVAILABLE",
 "reason": str|None,
 "denominators": {"scanned": int|None, "discovered": int, "truncated": int|None},
 "candidates": [<candidate dict: every contract.CANDIDATE_FIELDS key present; cells via contract.cell();
                 identity via contract.exposure_key()/candidate_id(); admission_state/paper_status/
                 evidence_maturity left None — A owns them>],
 "unresolved": [{"name": str, "reason": str}],   # could not build an exposure key ⇒ A records DATA_INSUFFICIENT
 "observations": {candidate_id: {"observed_return": cell, "realised_index": cell|None,   # share price / index
                                  "period": "YYYY-MM-DD"}},
 "counterparty": {candidate_id: {"roles": {role: {"state": CP_*, "name": str|None, "source_ref": str|None,
                                                   "source_class": str|None}},
                                 "dimensions": {dim: {"state": CP_*, "source_ref": str|None,
                                                      "source_class": str|None, "as_of": iso|None}}}},
 "existing_book_roots": [underlying_root, …]}    # holdings already in the live books (for dedup)
```
A scanner never raises on missing data: it returns `status` and cells with the honest state. It never writes files.
`trading_research` is projected: every candidate is `admission_state = OBSERVE_ONLY` by A regardless of stage.

**Read interface (A → C).** `research_factory.read.latest(data_dir: Path) -> dict`:
```
{"schema": SCHEMA_STATUS, "generated_at": iso, "integrity": "OK"|"BROKEN", "ledger_head_hash": str|None,
 "authorization": AUTHORIZATION_TEXT, "real_capital_usd": 0, "live_authorized": False,
 "denominators": {...STATUS_DENOMINATORS}, "by_state": {state: count}, "by_domain": {domain: count},
 "by_mechanism": {mechanism: count}, "counterparty_unknown_count": int, "stale_feeds": [{"source_root", "age_h"}],
 "candidates": [{"candidate_id", "exposure_key", "domain", "mechanism_id", "instrument", "venue_or_protocol",
                 "network", "admission_state", "economic_driver_key", "yield_source",
                 "base_return": cell, "net_expected_return": cell, "evidence_maturity": {"forward_periods": int,
                 "required": 30}, "counterparty_summary": {...CP_SUMMARY_FIELDS}, "reasons": [str],
                 "admission_id": str|None}],
 "rejections": [{"candidate_id", "state", "reasons"}], "domain_decisions": contract.DOMAIN_DECISIONS,
 "basis_track": {"state": "MEASURED"|"STALE"|"NOT_MEASURED", "funding_as_of": iso|None, "reason": str}}
```
and `research_factory.read.cio_view(data_dir: Path, now: datetime) -> dict` =
`{"state": "OK"|"STALE"|"BROKEN"|"NOT_MEASURED", "reason", "observe_only": [...], "paper_active": [...],
"cio_eligible": [...], "correlation_groups": {economic_driver_key: [candidate_id…]}, "ledger_head_hash"}` —
`cio_eligible` is non-empty only if the read model is ≤ 26 h old and its head hash matches the ledger.

## Post-implementation review (2026-10-04) — verdict REWORK; remediation

Findings H0–H6, M1–M7 and four LOW items (see journal W40). Binding outcome added to the contract:
`contract.period_countable()` — a forward period counts only when the upstream demonstrably advanced: a MEASURED
on-chain `realised_index` with a strictly newer block time, or a PRIMARY-source observation with a strictly newer
TRUE upstream time. An aggregator relay rate never counts, however fresh our fetch time looks (the susde_dn class).

### Remediation of the post-implementation review (all fixed, each with a test shown red without the fix)

- **H0** `--live-rpc` passed the rpc *module*: `run.main` builds `RpcClient(1)`; any chain-read failure is a
  NOT_MEASURED `realised_index`, scanner errors are recorded in the run row.
- **H1** scanners never stamp scan time as `as_of` (missing source time ⇒ NOT_MEASURED); funding `as_of` =
  `min(generated_at, end of latest series day, now)`; `forward.record` uses `contract.period_countable()` only.
  Frozen bytes for 4 days ⇒ 0 counted periods.
- **H2** the fingerprint strips timestamps recursively: an unchanged rerun appends only the run row.
- **H3/H4** disappearance keyed by `producing_scanner`; every paper-state candidate gets an observation row each run
  (NOT_MEASURED when absent); 3 consecutive not-counted periods ⇒ STALE.
- **H5** provenance compares only the primary return against a second return cell from a different non-MODELLED
  root, same unit and window; otherwise PASS only on a PRIMARY root.
- **H6** counterparty roles default to UNKNOWN per mechanism; repo-curated facts are SECONDARY_SOURCE, issuer terms
  ISSUER_CLAIM, no AUDITED_DOCUMENT; no reserve transparency from a NAV label; Ethena's venues UNKNOWN.
- **M1** one track per T-bill fund with one shared case-folded fund-root table; **M2** unit-aware consistency gate;
  **M3** no invented zeros (sUSDe funding NOT_MEASURED/embedded, no invented `time_to_exit`); **M4** no raise on a
  missing `generated_at`; **M5** the read model's time is the last run row, Mission Control STALE after 26 h;
  **M6** susde_dn strand judged by frozen-date age, the Pendle file kept out of the CIO inputs — `evidence_cutoff`,
  weights, stance and confidence byte-identical to the pre-ADR-560 tree (one-off subprocess comparison, recorded in
  the journal); **M7** one verified read per run (~0.1–0.4 s instead of 12→24 s), trust revoked in `finally`.
- **Second review** (re-verification + new findings): N1 a mid-ledger tamper hidden by the status cache ⇒ `read.latest`
  always verifies from disk and (N8) never serves `status.json` back; N2 `cio_view` derives its lists from ledger
  transitions; N3 `verify()` always reads disk, `run_once` invalidates its cache in `finally`; N4 the wrapper test
  can no longer reach the production tree (skip-sync flag, private stamp, private sync repo, private log); N5
  funding mechanisms judge `funding` freshness; N6 case-folded fund roots; N7 a counted index must be a PRIMARY_CHAIN
  read with a `chain:` root. Final round: SECOND REVIEW CLOSED (see journal).

## Outcome on production data (2026-10-04)

49 candidates from 17,147 scanned pools (158 truncated): CASH_TREASURY 5 · MARKET_NEUTRAL_BASIS 3 · RWA_STABLE_YIELD 11
· DEFI_DISCOVERY 25 · TRADING_RESEARCH 5 (OBSERVE_ONLY). States: COUNTERPARTY_UNKNOWN 30 · DATA_INSUFFICIENT 9 ·
DUPLICATE_EXPOSURE 5 (sUSDS/sDAI = the Sky savings exposure the Conservative book already holds; sUSDe = held by a
book) · OBSERVE_ONLY 5. **PAPER_ACTIVE 0 · CIO_ELIGIBLE 0** — no candidate yet names every required counterparty
role from a source, and aggregator-only rates fail provenance. This is the honest result: research rejection is a
valid outcome, and nothing was admitted on an advertised APY. Basis track: funding MEASURED (5-venue median).

## Role identity

No new human-facing role was created. A candidate is recorded for the owner (see journal / final report):
`head_of_research` — owns admission RESEARCH → PAPER; authority NONE over capital. `display_name` UNASSIGNED.

## Delivery and closeout (2026-10-04)

Code `ad283847b`; agent installed through the deploy gate; first production run exit 0 (49 candidates, ledger intact);
Mission Control and Oracle verified on production, including the external phone view; fresh-session proof PASS (16/16).

**Known debts (recorded, not blocking):** the run row's `denominators.discovered` (40) excludes the 9 unresolved
DATA_INSUFFICIENT entries that the read model counts (49) — one name, two measures; the read model's `rejections` list
holds HELD candidates (hold states), not terminal REJECTED ones; `counterparty_unknown_count` counts candidates with ANY
unknown role, unlike `by_state.COUNTERPARTY_UNKNOWN` (the hold state); the `counterparty` ledger kind is unused
(counterparty facts live inside candidate snapshots); Mission Control lists held candidates by id rather than name;
BUIDL-class nets use an issuer-documented 0 bps fee (labelled ESTIMATED, never MEASURED); migrating the
`investment_cio` and `capital_shadow` ledgers onto `utils/hash_ledger.py`; a forward-only Deribit public-chain
collector (options) is the named next step for that domain.
