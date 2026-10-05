# ADR-564 · RM-EVIDENCE-01 · Research evidence + paper admission v1 (Sherlock)

**Status:** ACCEPTED — frozen after the independent architecture review; implemented, post-implementation review + two re-reviews closed (number moved from 562 to 564 on delivery: 562/563 were taken on origin meanwhile) · **Date:** 2026-10-04 · **Owner:** @yurii
**Boundary:** real capital $0. Nothing moves money, signs, broadcasts, orders or approves tokens. RiskPolicy, leverage,
stops, tiers and cio-policy-v1 are untouched. PAPER_ACTIVE means only "evaluated forward with simulated capital"; it is
never live authorization and never CIO eligibility (that still needs ADR-560's 30 counted forward periods and gates).

## Role identity
The owner named the research lead **Sherlock**: `role_id head_of_research`, title Head of Research, authority over
capital NONE (`architecture/roles.json`). Sherlock is a role identity over DETERMINISTIC research governance — evidence
bundles, gates and the `ResearchAdmissionDecision` — not a free-form agent. No LLM decides a gate or a number.
Oracle (`chief_investment_officer`) may later consider only CIO_ELIGIBLE candidates on paper; the owner alone approves
real-capital action.

## Phase 0 — evidence gap map (two independent audits, 2026-10-04; citations in the journal)

| Candidate | Return today | Real independent origins | Roles documentable (cited) | Fees | Exit | Realised series | Verdict |
|---|---|---|---|---|---|---|---|
| **USYC** (Hashnote/Circle) | DeFiLlama pool **of the BSC class** joined to the Ethereum contract | **1** (Hashnote NAV: oracle = API = DeFiLlama) | issuer, custodian (Marex/Customers Bank), redemption (Teller T+0), legal (SDYF Cayman) — issuer claims | 10 % perf + 4/3 bps (issuer docs); price is net | redemption only, KYC non-US, $100k | **on-chain oracle** `0x74f2…1f53` `latestRoundData` | closest — feasible |
| **USDY** (Ondo) | correct Ethereum pool | 1 (Ondo oracle) | issuer ambiguous (LLC vs BVI), redemption, collateral agent Ankura; **custodian UNKNOWN** | spread undisclosed (net) | redemption only | on-chain `getPriceData()` | needs custodian + issuer resolution |
| **OUSG** (Ondo) | DeFiLlama pool **of the XRPL class** | 1 (OndoOracle) | issuer, redemption, legal entity (Ondo I LP — link inferred); **custodian UNKNOWN** | 0.15 % mgmt (waived to 2027-01-01) | redemption only, QP | on-chain `getAssetPrice` (no timestamp) | needs custodian |
| **BUIDL** (BlackRock/Securitize) | DeFiLlama pool **of the Solana class** | 1 (issuer accrual via RedStone) | issuer + legal (SEC Form D), custodian BNY + transfer agent Securitize (issuer release) | no official figure | redemption only, 3(c)(7) | **none on-chain** (NAV $1, dividend mints) | not feasible with free evidence |
| **BTC/ETH funding capture** | `perp:*:median5` | 5 venues fetched, **0 persisted** — the stored "median" is one venue's print | custodian = venue (Binance ADGM entities documented; Bybit/OKX entity UNKNOWN) | KuCoin API 0.06 %, Hyperliquid docs; Binance/Bybit/OKX not verified | measurable from public books | settlement rows exist upstream but discarded | not admissible until per-venue + hedge leg |

Defects found (not in ADR-560's debts): wrong-chain pool joins (BUIDL/OUSG/USYC); `rwa_floor` keyed by symbol; repo's
`redemption_fee_bps = 0` contradicted by official sources; `onchain.realised_index` supports only ERC-4626 (none of the
four is a vault); admission gates `return_source_understood` / `not_advertised_only` read `base_return` and fail by
construction for funding mechanisms; the funding "median" pools entries so one venue's single print wins; Hyperliquid
partial days understated; a 25 % relative conflict tolerance does not fit funding rates (needs an absolute band).

## Decision

1. **Contract** `spa_core/research_factory/evidence_contract.py` (frozen with this ADR; ADR-560's `contract.py` stays
   in force): `CandidateEvidenceBundle`, `CounterpartyProfile` (IDENTIFIED · DOCUMENTED · OBSERVED · UNKNOWN ·
   NOT_APPLICABLE per role, with citations and attributes), per-dimension GRADES (no average), origin-based
   independence, `PaperAdmissionReport v2` (17 gates), `ResearchAdmissionDecision`, paper-accounting shapes.
2. **Independence is by ORIGIN.** An issuer-posted on-chain oracle, the issuer's API and an aggregator relaying them
   are ONE origin. For PAPER one PRIMARY channel (on-chain / official API) with a true upstream timestamp is enough,
   and the circularity is recorded as a named concern; CIO eligibility needs two independent origins for return,
   reserves and custody (`MIN_ORIGINS_CIO`).
3. **Fees.** Fee terms are documented by nature: a fee DOCUMENTED from the origin's official terms with a citation
   ≤ 30 days old grades COST ADEQUATE for paper. Unknown fees are NOT_MEASURED and block — never 0. The repo's 0 bps
   figures are superseded by cited terms or by NOT_MEASURED.
4. **Instrument identity** is verified on-chain (name/symbol/decimals at a block) and joined to the pool / oracle of
   THE SAME chain and contract; a symbol join is forbidden. Wrappers and share classes resolve to their fund root.
5. **Realised series** come from on-chain NAV readers: ERC-4626, Chainlink-interface `latestRoundData` (with
   `updatedAt`), Ondo `getPriceData` / `getAssetPrice` (block time when the oracle carries none). BUIDL has none ⇒ its
   forward series is NOT_MEASURED and it cannot be admitted.
6. **Funding capture** becomes one candidate PER VENUE (`perp:BTC:binance`, …), from persisted per-venue settlement
   rows with true settlement timestamps (append-only, revisions kept), dispersion visible, conflicts by an ABSOLUTE
   band in bps/8h; the median becomes a display aggregate and `perp:*:median5` is SUPERSEDED. The hedge leg (spot and
   perp book walks, mark/index) is collected forward per venue; a delta-neutral paper position is opened only when
   entry evidence for BOTH legs exists — never manufactured. Venues without an official fee source stay HOLD.
7. **Paper ledger + accounting.** ADMIT ⇒ immutable admission snapshot ⇒ `paper_open` (units = notional / entry
   price, entry fees from cited terms) ⇒ daily `paper_mark` (price from the realised series) and `paper_cashflow`
   (funding) ⇒ `paper_close`. Backfill is stored, never counted (ADR-560 `period_countable`). No row is rewritten.
8. **Sherlock daily run** inside the existing agent (`com.spa.research_factory`, 09:05): scan → evidence refresh →
   bundle → grades → v2 gates → decision → admission (ADMIT only) → paper marks → read model. Collectors use only the
   allow-listed keyless RPC client and HTTP GET to `HTTP_ALLOWED_HOSTS`.
9. **Oracle boundary unchanged.** Oracle sees RESEARCH_ONLY / PAPER_ACTIVE / CIO_ELIGIBLE; only CIO_ELIGIBLE could ever
   be considered, and none exists. cio-policy-v1 is not modified; weights stay byte-identical (differential test).
10. **Mission Control.** The Research Universe card gains "Sherlock — Head of Research" (reviewed today,
    evidence-ready, PAPER_ACTIVE, CIO_ELIGIBLE, counterparty UNKNOWN, conflicts, stale evidence, top blockers, recent
    decisions with reasons) and a per-candidate detail (who pays, counterparties, measured / documented / unknown,
    blockers). No execute controls.

## Runtime
Same agent and schedule as ADR-560 (09:05, before the CIO at 09:30). New collectors are keyless and read-only.

## Binding revision after the independent architecture review (2026-10-04) — supersedes conflicting text above

All 15 findings accepted and applied to `evidence_contract.py` (`research-evidence-contract/1`, now FROZEN) and, where
stated, to ADR-560's `contract.py` (amendment). Key bindings:

1. **ADMIT is the only door into paper.** Lifecycle accepts as gate_ref into PAPER_ACTIVE / EVIDENCE_ACCUMULATING only
   an admission snapshot `paper-admission/2` carrying `decision_id`, `bundle_digest`, `policy_version`, for which the
   ledger holds a `research-admission-decision/1` row with `ADMIT_TO_PAPER`, the same candidate and bundle digest.
   ADR-560's v1 `write_admission_snapshot` refuses once this ADR is in force. Positive-control test: an all-PASS v1
   report cannot open a position.
2. **v2 role semantics are versioned** (`counterparty-profile/2` on every role); v1 DOCUMENTED migrates to IDENTIFIED
   unless a non-issuer citation exists; v1 readers refuse v2 profiles.
3. **Validators.** DOCUMENTED = an independent document (regulator / auditor / administrator / the named counterparty,
   not affiliated with the issuer) whose quote names the identity; an issuer's own regulatory filing lifts only
   `legal_entity` / `issuer`. OBSERVED = an on-chain binding of a chain-native fact or the counterparty's OWN API; an
   issuer's API caps at IDENTIFIED. An inferred link (e.g. OUSG ↔ Ondo I LP) is UNKNOWN with its reason. Document
   citations carry a ≤ 200-char quote of the fact only — no page text is stored.
4. **Issuer-asserted is labelled.** Every bundle, decision, paper position and Mission Control row carries
   `evidence_ceiling` (ISSUER_ASSERTED / THIRD_PARTY_DOCUMENTED / OBSERVED), `issuer_asserted_roles` and
   `circularity_concerns`; the UI prints "issuer-asserted, not verified".
5. **Holder eligibility.** New dimension HOLDER_ELIGIBILITY (SPA_ELIGIBLE / NOT_ELIGIBLE / UNKNOWN with KYC,
   investor class, jurisdiction, minimum). SPA has no entity, KYC or investor class on record, so KYC-gated funds are
   NOT_ELIGIBLE/UNKNOWN: they can only be admitted as `paper_mode = REFERENCE_TRACK` (tracking NAV, not a holdable
   position) and are barred from CIO_ELIGIBLE. A measured zero secondary depth is `NONE (measured)`, never adequate.
6. **Frozen values.** An oracle without a timestamp is dated by its LAST VALUE CHANGE; `latestRoundData` by
   `updatedAt`; business-day NAVs may stay flat over weekends but > 3 unchanged business days is STALE (one freshness
   table, `FRESHNESS`).
7. **The decision is a function**: precedence REJECT > HOLD (conflict) > STALE > NEEDS_MORE_EVIDENCE > ADMIT with
   machine predicates; `GATE_INPUTS` fixes what each gate reads; `GATE_NA` names mechanisms per gate; v2 = 20 gates, a
   superset of v1 (keeps `leverage_known`, `not_advertised_only`, adds `holder_eligibility_recorded`).
8. **Funding.** Settlement rows keyed (venue, symbol, settlement_ts, interval_h), normalised per 8 h, a day counts only
   with the venue's expected settlement count, predicted funding is never a settlement, aggregates need ≥ 3 venues and
   show n; conflicts only between channels of the SAME venue (absolute 0.5 bps/8h band). A candidate is a
   (perp venue × spot venue) PAIR; all pairs of an asset are one `exposure_family`, deduped at family level, every
   member reported, admission order by evidence completeness — never by trailing APY. A leg without a fee source ⇒
   COST UNKNOWN ⇒ NEEDS_MORE_EVIDENCE. A test replays the median5 single-print defect.
9. **Paper accounting** adds unit-change events (dividend mints, rebases), leg ids, exit at NAV − redemption fee −
   delay haircut, funding at each settlement on that settlement's mark, margin / liquidation distance / collateral
   yield, performance-fee accrual where the price is not net, STALE mark rows without a price (no forward-fill),
   `mark_origin` + `mark_circular`, one-off bps amortised only by a declared holding period.
10. **Fees** carry components (entry / exit / management / performance / spread) with `effective_from` and
    `subject_to_change`; "price is net" needs its own citation; an undisclosed spread stays NOT_MEASURED.
11. **Origins** live in a git-tracked registry (`registry/origins.json`) with affiliation groups and `appointed_by`;
    independence is counted over groups; `chain:` is an origin only for chain-native facts.
12. New dimensions **RESERVES** and **LEGAL** (shown for paper, ≥ ADEQUATE for CIO).
13. **ADR-560 amendment:** `CIO_ELIGIBILITY_GATES` += `min_origins_cio`, `counterparty_grade_strong_for_credit_like`,
    `holder_eligibility_documented`, `not_reference_track`.
14. **One HTTP client** with a (host, method, path-prefix, body-type) allow-list, redirect re-check, size cap;
    collectors import only it (AST test); DeFiLlama only on the aggregator channel. Document/filing facts enter only
    through the curated fact registry.
15. **Interfaces frozen:** collector rows (`OBS_ROW_FIELDS`), curated facts (`FACT_FIELDS`, reviewed by a different
    session, re-retrieval: quote still found ⇒ re-confirmed; not found ⇒ CONFLICTED), and replay (a decision
    reproduces byte-identically from its stored bundle, code identity, policy version, `now` and input digests).
    Import-graph tests: the decision module imports no CIO / allocation / execution / site module; paper NAV never
    feeds the main track or the site; cio-policy-v1 weights stay byte-identical.

## Appendix I — implementation packages and frozen interfaces

Files under `spa_core/research_factory/` unless noted. Each package owns ONLY its files.

* **E1 · evidence core**: `http_client.py`, `registry_loader.py` (origins.json + facts.jsonl loaders and validators),
  `profile.py` (CounterpartyProfile v2 builder from facts + scanner hints), `grades.py`, `bundle.py`,
  `admission_v2.py`, `decision.py` (Sherlock, incl. `replay(decision_id)`), changes to `lifecycle.py` (v2 gate_ref),
  `admission.py` (v1 snapshot refusal), `eligibility.py` (4 amended CIO gates), `run.py` (Sherlock daily sequence),
  `read.py` (additions below). Tests `test_research_evidence_core.py`.
* **E2 · paper ledger + accounting**: `paper.py` — `open_position(data_dir, decision, admission, bundle, now)`,
  `mark(data_dir, position_id, obs, now)`, `cashflow(...)`, `unit_change(...)`, `close(...)`, `nav(...)`,
  `positions(data_dir)`; all rows on the factory ledger under `PAPER_KINDS`, keyed for idempotency. Plus
  `failure_matrix_v2.py` (≥ 25 induced cases over the whole path) and tests `test_research_paper.py`,
  `test_research_evidence_failures.py`.
* **E3 · collectors + tracks**: `registry/origins.json`, `registry/facts.jsonl` (curated, cited — from the Phase-0
  citation seed), `instruments.py` (instrument registry: chain, address, decimals, oracle reader kind + address, pool
  join by chain AND contract, wrapper/share-class roots), `onchain.py` (new readers: chainlink_round, ondo_price_data,
  ondo_asset_price with last-value-change tracking), `collectors/treasury.py`, `collectors/funding_venues.py`
  (settlement rows per venue), `collectors/books.py` (spot/perp book walks + mark/index), `scanners/rwa.py`,
  `scanners/basis.py` (pairs + exposure_family; median5 SUPERSEDED), `scanners/cash_treasury.py` (chain-correct joins).
  Tests `test_research_evidence_tracks.py`.
* **E4 · integration**: Mission Control (Sherlock block + candidate detail in the Research Universe card),
  `investment_cio/research_universe.py` (RESEARCH_ONLY / PAPER_ACTIVE / CIO_ELIGIBLE, differential weights test),
  `architecture/provenance.json` + manifest notes, roles single-source test. Tests in
  `test_mission_control_contract.py`, `test_investment_cio_research_universe.py`.

**Read-model additions (E1 → E4)** in `read.latest()`:
`sherlock = {"role_id", "display_name", "reviewed_today", "evidence_ready", "paper_active", "cio_eligible",
"counterparty_unknown", "conflicts", "stale_evidence", "top_blockers": [{"gate", "count"}],
"decisions_today": [{"candidate_id", "instrument", "decision", "failed_gates", "required_next_evidence",
"evidence_ceiling", "paper_mode"}]}` and per candidate `evidence = {"grades": {dim: grade}, "evidence_ceiling",
"issuer_asserted_roles", "circularity_concerns", "who_pays", "counterparties": {role: {state, identity}},
"measured": [...], "documented": [...], "unknown": [...], "blocking_gaps": [...], "paper_mode",
"latest_decision", "paper_position": {nav_usd, realised_return, unrealised_return, mark_state}|None}`.

**Integration amendment (2026-10-04).** The internal shape of `paper_accounting_evidence` is frozen as
`PAPER_ACCOUNTING_EVIDENCE_FIELDS` / `FEE_COMPONENT_FIELDS` (E2's shape — paper accounting is its only consumer;
E1's bundle builds it from E3's cited fee components and the realised series).

## Live integration findings (2026-10-04, production-data copy, real keyless RPC + HTTP)

The first end-to-end live run (89 candidates, every one reviewed by Sherlock) exposed defects that offline tests
had not; each is fixed with a test red without the fix:

* **Unit mixing in the net return** (ADR-560 `contract.net_expected_return`): one-off fees in bps were subtracted from
  an annual funding rate — net = −2697 — which produced a FALSE REJECT for the KuCoin pairs. The formula is now
  unit-aware (`ANNUAL_RATE_UNITS`); a one-off cost is netted only after amortisation over a DECLARED paper holding
  period (ESTIMATED_WITH_METHOD), otherwise NOT_MEASURED.
* **Paper mode never switched to REFERENCE_TRACK**: KYC-gated funds failed only `liquidity_measured` because SPA is not
  an eligible holder. Per binding #5 they are evaluated as REFERENCE_TRACK (a NAV tracker, no exit claim, barred from
  CIO), never as a holdable position.
* **Timestamp-less oracle graded fresh on its first read** (OUSG `getAssetPrice`): the first read now has no known
  change time; a later changed value is dated by the previous fetch (conservative lower bound).
* **USDY's `getPriceData` timestamp is the block time of an issuer-scheduled accrual**, not an update time; its advance
  is a formula, not a new report, so it is not fresh evidence of a NAV report.
* **Perp contract identity** was not collected, so every funding pair failed `identity_verified`; venue contract specs
  are now read from the venues' public APIs.
* **OUSG pool join** was ambiguous (a third-party money market lists the same contract); resolved deterministically
  by the declared issuer project slug, never by guessing.

## Post-implementation review (2026-10-04) — verdict CLOSE AFTER FIXES; remediation

The independent reviewer re-ran the factory live and reproduced each defect. Contract changes (owned here):
`origin_group()` — aggregator / model / missing origins are never independent, an UNREGISTERED origin fails closed
(never its own group), an origin `appointed_by` another party belongs to the appointer's group (an issuer's
administrator or custodian is not independent of it); `GATE_NA_REFERENCE_TRACK` frozen; `HTTP_SCHEMES = https`;
facts require an independent review (`reviewed_by` ≠ `curated_by`) and an origin matching the publisher of the
cited page. Fixed in code (each with a positive-control test):

* **H1** HTTP redirects bypassed the allow-list (urllib followed 30x itself) — redirects are refused and re-checked
  per hop; https only.
* **H2** funding pairs passed `fees_measured` on the perp fee alone and carried a fill PRICE in a cost cell — per-leg
  fee components in one-off units; slippage as a cost in bps; a leg without an official fee source keeps COST below
  ADEQUATE.
* **H3** paper marks were FRESH whatever the price's age, and keyed by wall clock — freshness is judged in `mark()`
  (STALE ⇒ no price), marks keyed by the upstream reading.
* **H4** the performance fee was deducted from a price already net of it — a cited "price is net" fact is honoured.
* **H5** an aggregator / missing / unregistered cross-check upgraded RETURN to STRONG — never independent now.
* **H6** facts naming a custodian / administrator / auditor on the ISSUER's own pages counted as third-party
  documents — origins follow the page's publisher; appointed parties are affiliated; unreviewed facts are unusable
  until an independent session re-retrieves them and confirms the quote.
* **M1** the CIO minimum grades and group counts are enforced gates; **M2** `not_advertised_only` needs a primary
  return source; **M3** replay recomputes the gates from the stored bundle and reports a code change separately;
  **M4** a non-ADMIT decision on a paper candidate pauses it (PAUSED_PAPER); **M5** one validated fact loader;
  **M6** paper duplicates are caught by `underlying_root`; **M7** collectors import only the allowed clients
  (transitive check); plus re-screening only when a failed gate's inputs change.

## Independent fact review and re-review rounds (2026-10-04)

**Fact review (three rounds, separate Opus sessions, every ref re-retrieved).** Round 1: 43 facts — 30 CONFIRMED,
13 REJECTED. The review itself exposed a fail-open: 32 of 43 refs were free text ("docs.ondo.finance (OUSG fees)")
and skipped the origin/host check entirely. Refs were re-curated to exact https URLs (curated by this session,
never self-reviewed); fact-017 origin → `agent:securitize` (every BUIDL prnewswire release is "News provided by
Securitize"; appointed by BlackRock, so still the BlackRock group), fact-029 → `issuer:ondo`. Round 2 (25 re-curated):
20 CONFIRMED, 5 REJECTED for quotes stronger than the cited page. Round 3 re-confirmed three facts whose
`page_sha256` had been nulled after round 2 (the stored hashes belonged to other pages). **Usable now: 30 of 43.**
Rejected and therefore unusable until corrected and re-reviewed: USYC oracle (two oracles in the issuer's own docs),
USYC "price net of fees", USYC custodian (the page says prime broker), USYC Teller T+0, USDY spread, USDY redemption
(two paths conflated), BUIDL RedStone (contradicted — on-chain NAV feeds exist), BUIDL transfer agent, OUSG issuer
(Ondo I LP, not "Ondo Finance"), OUSG↔Ondo I LP link (documented, not inferred), USDY/OUSG oracle values and the
OUSG InstantManager address (not on the cited page). Records: `spa_core/research_factory/registry/fact_reviews/`.

**Re-review of the remediation (same reviewer as the post-implementation review): CLOSE AFTER FIXES**, then fixed:

* **H2 not closed** — `grade_cost` read only the v1 fee cells, so funding pairs passed `fees_measured` with no
  spot (and often no perp) fee. COST now folds every entry/exit fee component of every leg of
  `paper_accounting_evidence` (built before grading); an unlisted leg fee is WEAK, never zero. Live: every
  funding pair now fails `fees_measured`.
* **H5 residual** — `chain:` counted as an independent group for any claim. `origin_group(origin, registry,
  claim_type)`: a chain is a witness only to `CHAIN_NATIVE_CLAIMS`; an ungrouped RETURN primary caps at ADEQUATE.
  Conservative consequence, accepted: an on-chain lending-index return no longer establishes independence on its
  own — follow-up: classify contract-computed protocol state explicitly.
* **H6, two holes** — (a) chain-native refs skipped the host check whatever the channel: now only with channel
  `on_chain` and a chain-native claim; (b) a review stamp was not bound to content: `fact_sha256` must equal
  `fact_content_sha256(row)` and a committed `fact-review/1` record by `reviewed_by` must CONFIRM that fact at that
  hash; a malformed record halts the load.
* **N1 (new, HIGH)** — a PAUSED_PAPER candidate kept counting forward periods toward CIO maturity. Observations
  while paused are recorded `counted=False` ("tracking only").
* **M6** — paused positions and same-run admissions now block a duplicate copy of the same fund. **M3** — replay
  separates `VERDICT_DRIFT` (field diff) from `CODE_CHANGED`. **N2** — a resume writes `resume_evidence`
  (admission, new decision, bundle digest). LOWs: redirect port checked and relative `Location` resolved; group
  gates PASS when the dimension is NOT_APPLICABLE; a partial fee-fact set is NOT_MEASURED, never 0; the OUSG
  management-fee waiver is NOT_MEASURED from 2027-01-01.
* **Live re-run finding** — the v1 fingerprint re-screen moved every held funding pair through
  SCREENED → RESEARCH_READY → back each run (~80 transitions/run). Removed: hold states are Sherlock's call alone;
  a candidate already at its hold target does not move. Third consecutive live run: 0 transitions.
* PAUSED_PAPER had no exit: a Sherlock re-ADMIT resumes to `paused_from` under the same admission, only with an
  OPEN paper position; a pause from CIO_ELIGIBLE resumes to EVIDENCE_ACCUMULATING.
* The six CIO grade/group bars proposed in the first remediation are amended into `CIO_ELIGIBILITY_GATES`.

**Result on a fresh production-data copy (three `--live-rpc` runs):** 73 candidates reviewed, ADMIT 0,
PAPER_ACTIVE 0, CIO_ELIGIBLE 0. USYC: NEEDS_MORE_EVIDENCE — no failed gate, unknown COUNTERPARTY / CUSTODY /
LEGAL / REDEMPTION / RESERVES, exactly the facts review rejected. BUIDL / OUSG / USDY: fees and net return not
computable. Funding pairs: fees, leverage, paper accounting. The full path (ADMIT → paper_open → FRESH mark) was
exercised live earlier the same day on USYC and is covered by both failure matrices; the honest final count is 0.

**Second re-review: every item CLOSED; one new MEDIUM, fixed.** N3 — rows recorded while PAUSED_PAPER counted as
"misses" in the three-not-counted ⇒ STALE rule, so a resumed position went STALE on its first honestly quiet day;
paused rows are now neither a count nor a miss (`forward.PAUSED_REASON`, positive control + mutation check). The
reviewer's own live run on the production copy: 73 NEEDS_MORE_EVIDENCE, 0 ADMIT, 0 transitions, all 40 funding
pairs COST=WEAK, `decision.replay` 157/157 MATCH.

**Carried forward (named, not fixed here — one inbox card):** N4 (LOW) — the observation of the run on which
evidence lapses is recorded before Sherlock pauses the candidate, so at most one period may count; trust boundary
(LOW) — anyone who can commit can add a review record under any reviewer name, and `role_entry` accepts OBSERVED
from any chain-native citation without binding the role's identity; the initial URL path is not normalised
(`/api/../x`, caller-built URLs only); the OUSG waiver end is a constant because facts have no structured
`effective_until`; on-chain lending-index returns need an explicit "contract-computed state" class to count as
independent again.

## CIO eligibility gates added by this ADR — the complete list (closeout, 2026-10-05)

`contract.CIO_ELIGIBILITY_GATES` (ADR-560's seven) gains **ten** gates here: four from the architecture review
(`min_origins_cio` — at least `MIN_GROUPS_CIO["return"] = 2` independent groups, `counterparty_grade_strong_for_credit_like`,
`holder_eligibility_documented`, `not_reference_track`) and six from the post-implementation review M1
(`return_grade_strong_for_cio`, `custody_grade_strong_for_cio`, `reserves_grade_adequate_for_cio`,
`legal_grade_adequate_for_cio`, `reserves_groups_sufficient_for_cio`, `custody_groups_sufficient_for_cio`).
A fresh-session proof listed only the first four — this section exists so the list has one place.

## Delivery and acceptance (2026-10-05)

Commit `cc0d3914` (66 files, one commit). Production: `deployment_acceptance` OK before and after; code-sync of 59
files with an import probe and drift 0; `com.spa.research_factory` run via launchd exit 0 — 89 candidates
discovered, 73 reviewed by Sherlock, all NEEDS_MORE_EVIDENCE, PAPER_ACTIVE 0, CIO_ELIGIBLE 0, integrity OK,
`real_capital_usd` 0, `live_authorized` false; Oracle's view OK with RESEARCH_ONLY 5 / PAPER_ACTIVE 0 /
CIO_ELIGIBLE 0. Mission Control: rebuilt bundle served on loopback `:8790/mission.json` with the Sherlock block
and no execute/approve control; the external `mc.earn-defi.com` page is behind Cloudflare Access and the browser
session had expired ("НЕ ИЗМЕРЕНО / нет связи") — re-checking it needs the owner's own sign-in. Recovery drill on a
copy of post-deploy production data: 9/9 (tamper ⇒ BROKEN and exit 2; read model rebuilt from the ledger; corrupt
index ignored; same-time restart appends nothing; concurrent run exit 75; admission gate cannot be skipped; stale
read model revokes readiness and Oracle gains nothing; terminal candidates stay visible; decision reasons survive a
restart). Fresh-session proof: 20/20 answered from files, 19 fully right, CIO gate list incomplete (fixed above).

## Tail closed (2026-10-05) — card `inbox-hvost-adr-564-pyat-defektov-fabriki-issl`

Acceptance probe `research_evidence_tail_closed` (`spa_core/monitoring/card_acceptance.py`) was declared on the card
BEFORE the work and read `not_satisfied` on all six links; it reads `satisfied` now. Each link is a scene on real
code, and its test (`spa_core/tests/test_research_evidence_tail_probe.py`) turns exactly that link red under a
mutation. An independent review (CLOSE AFTER FIXES) and its re-review (CLOSE) shaped the final form.

* **N4 — the period of the lapse day.** A pause voids every counted observation not yet confirmed by a completed
  run — LEDGER ORDER (a later `run` row), never a timestamp, so a crashed run's period and a future-dated run row
  are both handled — by an appended `observation_void` row. Promotion to EVIDENCE_ACCUMULATING and the CIO recheck
  now run after Sherlock's review, never on a period the same run may void.
* **Trust boundary.** `FACT_REVIEWERS` allow-list (a new reviewer is a visible contract change; a curator is never a
  reviewer). OBSERVED is bound to the role: on-chain only when the chain is the origin, the claim fits the role
  (`ROLE_OBSERVABLE_CLAIMS`) and the ref's method actually reads that claim (`ref_claim_type`); via an API only from
  a registered origin of the role's own type (`ROLE_API_ORIGIN_PREFIXES`) independent of a KNOWN issuer group —
  taken from the issuer's own `issuer:*` publications, no longer from whichever fact names the issuer role (BUIDL's
  was the SEC). `legal_entity` has no own-API route: it is DOCUMENTED by an independent filing or it is not.
* **URLs.** Paths must match `^[A-Za-z0-9._~/-]*$` with no `.`/`..` segment on every hop (refuses `..;/`, `%2e`,
  `%252e`, `%2f`, `%5c`, fullwidth dots, NUL); no userinfo; explicit ports only from `HTTP_PORTS`.
* **`effective_until`.** `FACT_OPTIONAL_FIELDS`: absent ⇒ not hashed (existing reviews stay bound), present ⇒ hashed,
  null ⇒ absent; an ended fact is never "the present". The OUSG management-fee waiver end moved from a `rwa.py`
  constant to fact-012 (re-curated, confirmed by an independent round-4 review).
* **Contract-computed returns.** `protocol_state` is chain-native; `CONTRACT_COMPUTED_RETURN_MECHANISMS` (LENDING,
  LOOPED_LENDING, STABLECOIN_SAVINGS — sUSDS/sDAI, whose rate the savings contract enforces) count a `chain:` return
  read as an independent witness; a tokenised fund's posted NAV still does not.
* Found on the way: `read.latest` fell back to the WALL CLOCK for "today" when a ledger had no run row (a date bomb
  that went off at midnight) — now the ledger's newest entry; the RM-EXPAND-01 discovery scanner read the candidate
  registry around its canonical reader — now through `read_candidate_registry` (unread ⇒ UNAVAILABLE), flagged PARTIAL
  if its two reads disagree.

**Still named, not fixed:** a completed run confirms a period even if Sherlock skipped this candidate (only a
malformed snapshot is skipped); the reviewer allow-list authenticates names, not authors (visible in review);
`return_claim_type` keys on the mechanism, not the method read. Result on production data unchanged: 73 candidates,
PAPER_ACTIVE 0, CIO_ELIGIBLE 0, 30 of 43 facts usable.

## Evidence round 5 (2026-10-05) — corrected facts; the first candidate on paper

Card `inbox-ispravlennye-fakty-vmesto-otvergnutyh-pr`, probe `curated_facts_usable:fact-043..fact-055` (declared
before the work; a new, generic outcome probe — a named fact counts only if the REAL loader accepts it: reviewed,
content-bound, publisher-checked, unexpired; a range must have every index). Thirteen corrected replacements for
review-rejected facts, each quoting only its exact page and naming what it `supersedes`; an independent round-5
review CONFIRMED 13/13 at their content hashes. **Usable facts: 43 of 56.**

* USYC: both published Ethereum oracles — `0x74f2…` (contracts page; the factory's reader) and `0x4c48…` (price
  page). Read on-chain 2026-10-05 they report the same NAV for the same date (1.1390028153 vs 1.13900281): two
  channels of one NAV, not a conflict. Custody "segregated custodial accounts at our prime broker" (no firm named on
  that page), Teller redemption 24/7/365, T+0, the Teller address.
* OUSG: issuer **Ondo I LP**, stated by Ondo itself (the link is documented, not inferred); redemption terms; the
  InstantManager and oracle addresses. USDY: the oracle-wrapper address; the USD bank-wire redemption path.
* Not curated (no page states them): USYC "price net of fees", the USDY "small spread", BUIDL's transfer agent and
  RedStone feed. Binance/Bybit/OKX fee pages render only by script — another official source is needed.

**Result on production data:** USYC is **PAPER_ACTIVE — a REFERENCE_TRACK paper position** (Sherlock
ADMIT_TO_PAPER, no failed gate; evidence ceiling ISSUER_ASSERTED; mark circular, labelled). LEGAL and RESERVES stay
UNKNOWN, which the CIO bars require, so USYC cannot become CIO_ELIGIBLE on this evidence. Whether USYC's price is net
of its 10% performance fee is unknown, so paper accrues the fee on gains (understates, never overstates). Oracle sees
it under PAPER_ACTIVE; `research_sleeve_allocatable` is False. OUSG / USDY / BUIDL: NEEDS_MORE_EVIDENCE (fees and
net return not computable). PAPER_ACTIVE means only "evaluated forward with simulated capital"; real capital $0.

