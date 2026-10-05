"""spa_core/research_factory/run.py — orchestrator: scanners -> registry -> lifecycle -> admission
-> forward -> eligibility -> status.json.

``python -m spa_core.research_factory.run [--data-dir D] [--now ISO] [--live-rpc]``

Default data dir: ``$SPA_DATA_DIR`` if set, else THIS code tree's own ``data/`` — never another
tree (``Path(__file__).resolve().parents[2] / "data"``).

Scanner modules live in ``spa_core.research_factory.scanners`` (Package B, built in parallel) and
are discovered DYNAMICALLY — an empty or missing ``scanners`` package is tolerated (status
NOT_MEASURED for the run, never a crash). Every scanner is called as
``scan(data_dir, now, rpc_client=None)`` unless ``--live-rpc`` is given.

ADR-564 (RM-EVIDENCE-01) adds Sherlock's daily sequence (ADR §8), run in two stages:

1. Evidence refresh, BEFORE the scanners run: ``collectors.funding_venues``/``collectors.books``
   (per-venue funding settlements + spot/perp book walks, decision #6) are passed straight into
   ``scanners.basis.scan(..., funding_rows=, book_rows=)`` so the (perp venue × spot venue) PAIR
   candidates actually get built and the legacy median5 candidate gets labelled
   ``superseded_by``; ONE ``yields.llama.fi/pools`` fetch (``http_client``, 32 MiB host cap) feeds
   both ``scanners.rwa.scan(..., raw_pools=)`` (decision #4's chain-correct join) and
   ``collectors.treasury.collect(..., pools=)``. Every collector tolerates ``client=None`` (no
   ``--live-rpc``) — every claim comes back NOT_MEASURED and the run still exits 0.
2. Sherlock's universal review (``_sherlock_review_all``), AFTER the v1 scanner/lifecycle pass:
   EVERY candidate not in a terminal state and not OBSERVE_ONLY — regardless of what v1's own
   admission pre-screen did to it this run — gets bundle (``bundle.build_bundle``) -> grades
   (``grades.grade_all``) -> the 20-gate v2 report (``admission_v2.evaluate``) -> a decision
   (``decision.decide_and_record``, written ONLY when the bundle's content digest changed —
   otherwise the previous decision stays current). ADMIT_TO_PAPER -> the v2 admission snapshot
   (``decision.write_admission_snapshot_v2``, the ONLY thing that may open PAPER_ACTIVE now,
   binding #1 — v1's ``admission.write_admission_snapshot`` always refuses) -> PAPER_ACTIVE ->
   ``paper.open_position``. Every other decision routes to the hold state the FIRST failed gate
   (``evidence_contract.ADMISSION_V2_GATES`` order) names, wherever the frozen
   ``contract.TRANSITIONS`` graph allows that move from the candidate's CURRENT state; a hold-
   state candidate whose bundle digest CHANGED re-screens back to SCREENED instead (the decision
   row's bundle digests are the gate_ref evidence), letting v1's own pre-screen look again.

# LLM_FORBIDDEN
"""
from __future__ import annotations

import argparse
import importlib
import inspect
import pkgutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from spa_core.research_factory import contract, decision, eligibility, forward, \
    lifecycle, profile as profile_mod, read, registry, registry_loader
from spa_core.research_factory import bundle as bundle_mod
from spa_core.research_factory import evidence_contract as ec
from spa_core.research_factory._common import iso, ledger_for
from spa_core.utils.atomic import atomic_save
from spa_core.utils.hash_ledger import DuplicateKey, LedgerError, RunLocked

try:  # Package E3, built in parallel — absence is tolerated exactly like a missing scanner
    from spa_core.research_factory.collectors import books, contract_identity, funding_venues, treasury
except Exception:  # noqa: BLE001
    books = contract_identity = funding_venues = treasury = None
try:  # Package E3
    from spa_core.research_factory import instruments
except Exception:  # noqa: BLE001
    instruments = None
try:  # Package E2
    from spa_core.research_factory import paper
except Exception:  # noqa: BLE001
    paper = None

def _default_data_dir() -> Path:
    import os
    env = os.environ.get("SPA_DATA_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "data"


def _discover_scanners():
    try:
        pkg = importlib.import_module("spa_core.research_factory.scanners")
    except ModuleNotFoundError:
        return []
    mods = []
    for info in pkgutil.iter_modules(pkg.__path__, pkg.__name__ + "."):
        try:
            mod = importlib.import_module(info.name)
        except Exception:  # noqa: BLE001 — a broken scanner module must not crash the run
            continue
        if hasattr(mod, "scan"):
            mods.append(mod)
    return mods


#: collector module name -> True once explicitly wired below (treasury/funding_venues/books). Any
#: OTHER collector Package E3 adds later still gets a tolerant, generic fold — never a crash, and
#: never silently ignored (it is "collected but unfolded", not "collected and acted on").
_EXPLICITLY_WIRED_COLLECTORS = ("treasury", "funding_venues", "books")
#: claim-name substrings the GENERIC fold recognises as a RETURN signal, for any future collector
#: NOT in _EXPLICITLY_WIRED_COLLECTORS.
_RETURN_CLAIM_HINTS = ("nav", "price", "funding", "oracle")
_CHANNEL_RETURN_FAMILY = {"on_chain": "nav_business_day", "official_api": "rate", "aggregator": "rate"}


def _discover_other_collectors():
    try:
        pkg = importlib.import_module("spa_core.research_factory.collectors")
    except ModuleNotFoundError:
        return []
    mods = []
    for info in pkgutil.iter_modules(pkg.__path__, pkg.__name__ + "."):
        name = info.name.rsplit(".", 1)[-1]
        if name in _EXPLICITLY_WIRED_COLLECTORS:
            continue
        try:
            mod = importlib.import_module(info.name)
        except Exception:  # noqa: BLE001 — a broken collector module must not crash the run
            continue
        if hasattr(mod, "collect"):
            mods.append(mod)
    return mods


def _call_collect(mod, now: datetime, client, rpc_client):
    try:
        params = inspect.signature(mod.collect).parameters
    except (TypeError, ValueError):
        params = {}
    kwargs = {"rpc_client": rpc_client} if "rpc_client" in params else {}
    return mod.collect(now, client, **kwargs)


def _run_other_collectors(now: datetime, client=None, rpc_client=None) -> tuple:
    """The GENERIC, tolerant fold for any collector NOT explicitly wired. Returns ``(rows,
    v2_overrides, errors)``."""
    all_rows: list = []
    overrides: dict = {}
    errors: list = []
    for mod in _discover_other_collectors():
        try:
            rows = _call_collect(mod, now, client, rpc_client) or []
        except Exception as exc:  # noqa: BLE001 — one broken collector must not sink the run
            errors.append({"collector": getattr(mod, "__name__", "?"), "error": f"{type(exc).__name__}: {exc}"})
            continue
        if not isinstance(rows, list):
            continue
        all_rows.extend(r for r in rows if isinstance(r, dict))

    for row in all_rows:
        cid = row.get("candidate_id")
        claim = str(row.get("claim") or "")
        if not cid or row.get("state") != contract.MEASURED:
            continue
        if not any(hint in claim.lower() for hint in _RETURN_CLAIM_HINTS):
            continue
        family = _CHANNEL_RETURN_FAMILY.get(row.get("channel"), "rate")
        slot = overrides.setdefault(cid, {})
        entry = {"origin": row.get("origin"), "value": row.get("value")}
        if row.get("channel") in ("on_chain", "official_api") and "return_primary_origin" not in slot:
            slot["return_primary_origin"] = row.get("origin")
            slot["return_last_change_at"] = row.get("upstream_ts") or row.get("fetched_at")
            slot["return_family"] = family
        else:
            slot.setdefault("return_cross_checks", []).append(entry)
    return all_rows, overrides, errors


# ── ADR-564 integration: DeFiLlama pools (one fetch, shared) + funding/books + treasury ─────────

def _fetch_defillama_pools(client) -> Optional[list]:
    """ONE fetch of ``yields.llama.fi/pools`` (32 MiB cap via
    ``evidence_contract.HTTP_MAX_RESPONSE_BYTES_BY_HOST``), shared by ``scanners.rwa``'s
    ``raw_pools`` (chain+contract join) and ``collectors.treasury``'s own aggregator-APY row.
    ``client=None`` (no ``--live-rpc``) or any fetch failure -> ``None``, never a crash; callers
    already treat ``None`` as "no pools this run", not as an empty, measured list."""
    if client is None:
        return None
    try:
        doc = client.get("yields.llama.fi", "/pools", {})
    except Exception:  # noqa: BLE001 — fail-CLOSED to "no pools", not a run-ending crash
        return None
    data = doc.get("data") if isinstance(doc, dict) else None
    return data if isinstance(data, list) else None


def _collect_funding_and_books(client, now: datetime) -> tuple:
    """``(funding_rows, book_rows)`` — ``collectors.funding_venues``/``collectors.books``, passed
    straight to ``scanners.basis.scan(..., funding_rows=, book_rows=)`` so the (perp venue × spot
    venue) PAIR candidates and the median5 ``superseded_by`` labelling actually happen. Both
    collectors already tolerate ``client=None`` (every venue call becomes NOT_MEASURED, never a
    crash) — this function adds the SAME tolerance for the module being absent."""
    funding_rows = funding_venues.collect(now, client) if funding_venues is not None else []
    book_rows = books.collect(now, client) if books is not None else []
    return funding_rows, book_rows


def _collect_contract_identity(client, now: datetime) -> list:
    """``collectors.contract_identity`` — "venue contract spec from the venue API"
    (``evidence_contract.GRADING_RULES["PRIMARY_IDENTITY"]``'s own perp carve-out), the evidence
    a funding-pair candidate's PRIMARY_IDENTITY needs to clear ADEQUATE. Tolerates the module
    being absent exactly like every other collector."""
    return contract_identity.collect(now, client) if contract_identity is not None else []


def _funding_pair_identity_overrides(all_candidates: dict, identity_rows: list) -> dict:
    """``{pair_candidate_id: {"identity": {...}}}`` — PRIMARY_IDENTITY is ADEQUATE for a funding
    PAIR candidate only when BOTH its perp venue's perp-identity row AND its spot venue's
    spot-identity row are MEASURED (collected successfully THIS run — these rows carry no
    upstream timestamp of their own, ``contract_identity.py``'s own docstring; "fresh" IS "just
    collected"). A missing/failed EITHER leg keeps it at WEAK (cited-only, never ADEQUATE) —
    never STRONG, which GRADING_RULES reserves for an ON-CHAIN verification a CEX perp has no
    equivalent of."""
    if not identity_rows:
        return {}
    measured_by_key: dict = {}  # (asset, venue, leg) -> True
    for row in identity_rows:
        claim = str(row.get("claim") or "")
        if row.get("state") != "MEASURED" or ":" not in claim:
            continue
        leg_claim, asset = claim.split(":", 1)
        leg = "perp" if leg_claim == contract_identity.PERP_IDENTITY_CLAIM else \
            "spot" if leg_claim == contract_identity.SPOT_IDENTITY_CLAIM else None
        origin = str(row.get("origin") or "")
        if leg is None or not origin.startswith("venue:"):
            continue
        venue = origin.removeprefix("venue:")
        measured_by_key[(asset, venue, leg)] = True

    overrides: dict = {}
    for cid, candidate in all_candidates.items():
        if candidate.get("mechanism_id") != "FUNDING_CAPTURE":
            continue
        venue_pair = str(candidate.get("venue_or_protocol") or "")
        driver = str(candidate.get("economic_driver_key") or "")
        if "+" not in venue_pair or not driver.endswith("_PERP_FUNDING"):
            continue  # the legacy 5-venue-median candidate, not a (perp venue x spot venue) pair
        perp_venue, spot_venue = venue_pair.split("+", 1)
        asset = driver[: -len("_PERP_FUNDING")]
        perp_ok = measured_by_key.get((asset, perp_venue, "perp"), False)
        spot_ok = measured_by_key.get((asset, spot_venue, "spot"), False)
        overrides[cid] = {"identity": {"on_chain_verified": False, "address_cited": True,
                                      "venue_spec_cited": bool(perp_ok and spot_ok)}}
    return overrides


def _treasury_prior_readings(data_dir: Path) -> dict:
    """``{symbol: {"value": float, "as_of": iso|None, "fetched_at": iso}}`` — the last-recorded
    ``nav_oracle`` reading PER INSTRUMENT, read back from the ledger's own ``evidence_observation``
    provenance rows (never a separate cache file). Feeds ``onchain.ondo_asset_price``'s
    frozen-value tracking (via ``collectors.treasury.collect(..., prior=...)``) across process
    restarts, not just within one run.

    E3 live-validation finding (2026-10-04): a FIRST read of a new oracle is honestly
    ``state=NOT_MEASURED``/``as_of=None`` (``onchain.py``'s own fix for that), but it STILL
    carries its raw VALUE (``onchain._unanchored_cell`` deliberately bypasses ``contract.cell()``'s
    "no value on a non-valued state" rule for exactly this reason) — filtering this loader by
    ``state == "MEASURED"`` discarded that first read every time, so the diff chain could never
    bootstrap past it. The filter is therefore "does this row carry a value at all", never the
    cell's own state."""
    if instruments is None or treasury is None:
        return {}
    ledger = ledger_for(data_dir)
    rows = [e for e in ledger.read_all() if e.get("kind") == "evidence_observation"]
    prior: dict = {}
    for symbol in instruments.INSTRUMENTS:
        cid = instruments.candidate_id_for(symbol)
        matches = [e for e in rows if (e.get("payload") or {}).get("candidate_id") == cid
                  and (e.get("payload") or {}).get("claim") == treasury.CLAIM_NAV_ORACLE
                  and (e.get("payload") or {}).get("value") is not None]
        if not matches:
            continue
        latest = max(matches, key=lambda e: e["seq"])
        payload = latest["payload"]
        prior[symbol] = {"value": payload.get("value"), "as_of": payload.get("upstream_ts"),
                         "fetched_at": payload.get("fetched_at")}
    return prior


def _treasury_v2_overrides(data_dir: Path, facts_all: list, rpc_client, client, pools, now: datetime) -> dict:
    """``{candidate_id: v2_evidence overrides}`` for the four Phase-0 tokenised-Treasury
    instruments (BUIDL/USYC/OUSG/USDY): on-chain identity (``instruments.verify_identity``), the
    oracle as the PRIMARY return channel (issuer origin, with circularity named via the facts'
    own origin group — ``bundle.py`` computes the actual circularity concern from
    ``return_primary_origin`` vs. the profile's issuer citations), the official API / DeFiLlama
    aggregator rows as cross-checks, and redemption/legal facts from the registry. Returns ``{}``
    (never raises) if ``instruments``/``treasury`` are not importable (Package E3 not present)."""
    if instruments is None or treasury is None:
        return {}
    prior = _treasury_prior_readings(data_dir)
    rows = treasury.collect(now, client, rpc_client=rpc_client, prior=prior, pools=pools)
    _persist_observation_rows(data_dir, rows, now)

    overrides: dict = {}
    for symbol, meta in instruments.INSTRUMENTS.items():
        cid = instruments.candidate_id_for(symbol)
        by_claim = {}
        for row in rows:
            if row.get("candidate_id") != cid:
                continue
            by_claim.setdefault(row.get("claim"), []).append(row)
        oracle_rows = by_claim.get(treasury.CLAIM_NAV_ORACLE) or []
        agg_rows = by_claim.get(treasury.CLAIM_NAV_AGGREGATOR_APY) or []
        api_rows = [r for claim, group in by_claim.items()
                   if str(claim or "").startswith(treasury.CLAIM_NAV_OFFICIAL_API) for r in group]

        identity_cell = instruments.verify_identity(symbol, rpc_client=rpc_client, now=now)
        identity_state = identity_cell.get("state")
        identity = {"on_chain_verified": identity_state == contract.MEASURED,
                   "mismatch": identity_state == contract.CONFLICTED, "address_cited": True}

        oracle_row = oracle_rows[0] if oracle_rows else None
        oracle_measured = oracle_row is not None and oracle_row.get("state") == "MEASURED"
        return_last_change_at = oracle_row.get("upstream_ts") if oracle_row else None

        # the ORACLE is the PRIMARY return channel (issuer origin) for GRADING (grades.grade_return
        # reads this override, never the v1 candidate's own `base_return` — a DeFiLlama AGGREGATOR
        # join that can never grade past WEAK, review #2's "an issuer-posted on-chain oracle ...
        # is ONE origin"). Built DIRECTLY from the observation row (never ``contract.cell()``,
        # which forbids a value on a non-MEASURED state) because a first-ever read is honestly
        # NOT_MEASURED/as_of=None yet STILL carries its raw value (``onchain._unanchored_cell``'s
        # own deliberate escape, E3's live-validation finding) — grade_return must see that value
        # to report an honest UNKNOWN, not have it silently dropped to "no override at all".
        oracle_cell = None
        if oracle_row is not None and isinstance(oracle_row.get("value"), (int, float)):
            oracle_cell = {
                "state": oracle_row.get("state"), "value": float(oracle_row["value"]),
                "unit": oracle_row.get("unit") or "usd_per_unit",
                "source_ref": oracle_row.get("ref") or f"chain:1:{meta.get('address', '').lower()}",
                "source_class": contract.PRIMARY_CHAIN, "source_root": "chain:1",
                "as_of": oracle_row.get("upstream_ts"), "recorded_at": iso(now),
                "method": "on-chain NAV/price oracle reader (ADR-564 decision #5)",
                "reason": oracle_row.get("reason"), "n": None, "window": None, "precision": None,
                "embedded_in_return": None,
            }

        # agg_rows (DeFiLlama) reports an APY, a DIFFERENT KIND of quantity than the oracle's own
        # NAV/price reading above — comparing a price to a yield is a unit mismatch, not a return
        # disagreement, so only the OFFICIAL API (when it is itself a price, e.g. USYC's) is a
        # legitimate cross-check; the aggregator reading is still persisted (evidence_observation)
        # for provenance, just never folded in as if it were the same measurement.
        cross_checks = []
        for row in api_rows:
            if row.get("state") == "MEASURED" and isinstance(row.get("value"), (int, float)):
                cross_checks.append({"origin": row.get("origin"), "value": row.get("value")})

        facts = registry_loader.facts_for(facts_all, cid, now=now)
        redemption_fact = next((f for f in facts if f.get("claim_type") == "redemption_terms"), None)
        legal_fact = next((f for f in facts if f.get("role") == "legal_entity"), None)

        overrides[cid] = {
            "identity": identity,
            "return_family": "nav_business_day", "return_last_change_at": return_last_change_at,
            "return_primary_origin": meta.get("oracle_origin"), "return_cross_checks": cross_checks,
            # GRADING only, never net_expected_return (see grades.grade_return's docstring) — a
            # raw NAV/price reading is not an annual rate and must never be netted as one (found
            # by the integration acceptance run: swapping the v1 base_return cell itself made
            # net_expected_return honestly NOT_MEASURED once it became unit-aware).
            "return_primary_cell_override": oracle_cell,
            # the paper entry price / daily mark source (MEASURED NAV reading only — see bundle.py)
            "nav_price_cell": oracle_cell, "nav_origin": meta.get("oracle_origin"),
            # KYC-gated redemption (review #5): an exit path is never assumed ELIGIBLE for SPA —
            # that is read from holder_eligibility_hint (merged separately), not guessed here.
            "liquidity_eligible_path_measured": False,
            "redemption": {"terms_cited": redemption_fact is not None,
                          "caveats_complete": redemption_fact is not None},
            "contract_reader_verified": oracle_measured,
            "forward_series": {"collector_exists": oracle_row is not None,
                              "last_change_at": return_last_change_at, "family": "nav_business_day"},
            "reserves": {},  # no attestation fact in this repo's citation seed — honestly UNKNOWN
            "legal": {"entity": legal_fact is not None, "jurisdiction": False, "exemption": False,
                     "documented": legal_fact is not None
                     and legal_fact.get("channel") == ec.CHANNEL_REGULATORY_FILING},
        }
    return overrides


def _persist_observation_rows(data_dir: Path, rows: list, now: datetime) -> None:
    """Every collected row is recorded on the ledger for provenance (kind ``evidence_observation``,
    schema ``evidence_contract.SCHEMA_OBS_ROW``), append-only and idempotently keyed — a collector
    re-observing the SAME (candidate, claim, upstream_ts) this run is a no-op, never a duplicate."""
    if not rows:
        return
    ledger = ledger_for(data_dir)
    at = iso(now)
    for row in rows:
        key = ["evidence_observation", row.get("candidate_id"), row.get("claim"), row.get("upstream_ts"),
              row.get("fetched_at")]
        try:
            ledger.append("evidence_observation", key, row, at)
        except DuplicateKey:
            pass




def _registry_view_for(data_dir: Path, exclude_id: str, all_candidates: dict, existing_book_roots: list) -> dict:
    view = {cid: {**c, "admission_state": lifecycle.current_state(data_dir, cid)}
           for cid, c in all_candidates.items() if cid != exclude_id}
    view["_existing_book_roots"] = existing_book_roots
    return view


# ── ADR-564: Sherlock's evidence refresh + bundle + grades + v2 decision ────────────────────────
#: mechanisms whose exposure_family is NOT its own exposure_key (the shared family root a scanner
#: records on `underlying_root` — ADR-564 decision #6 — e.g. "perp:BTC:family" for every (perp
#: venue × spot venue) pair of BTC).
_FAMILY_ROOTED_MECHANISMS = ("FUNDING_CAPTURE", "SPOT_PERP_BASIS")
#: gate (in evidence_contract.ADMISSION_V2_GATES order) -> the hold state its failure names.
#: "First failed gate" routing reads evidence_contract.ADMISSION_V2_GATES order, never the
#: stored (alphabetically sorted, for digest stability) decision.failed_gates order.
_GATE_DIM_HOLD = {
    "identity_verified": contract.DATA_INSUFFICIENT,
    "duplicate_exposure_clear": contract.DUPLICATE_EXPOSURE,
    # NEEDS_MORE_EVIDENCE on freshness means the evidence was NEVER fresh (DATA_INSUFFICIENT). STALE is reserved
    # for a DECISION_STALE, whose predicate requires a prior bundle at >= ADEQUATE (live-run finding: 17
    # never-fresh candidates were mislabelled STALE).
    "data_fresh": contract.DATA_INSUFFICIENT,
    "forward_collection_ready": contract.DATA_INSUFFICIENT,
    "counterparty_roles_sufficient": contract.COUNTERPARTY_UNKNOWN,
    "redemption_understood": contract.COUNTERPARTY_UNKNOWN,
    "custody_understood": contract.COUNTERPARTY_UNKNOWN,
    "leverage_known": contract.RISK_UNRESOLVED,
    "no_conflicted_critical_inputs": contract.RISK_UNRESOLVED,
    "holder_eligibility_recorded": contract.DATA_INSUFFICIENT,
}
_FRESHNESS_GATES = ("data_fresh", "forward_collection_ready")
#: hold states a hold-state candidate may re-screen FROM once its bundle digest changes
#: (contract.GATED_TARGETS[SCREENED] == "rescreen_inputs_changed", gated by a real digest change).
_RESCREENABLE_HOLD_STATES = (contract.REJECTED, contract.STALE_STATE, contract.DATA_INSUFFICIENT,
                             contract.RISK_UNRESOLVED, contract.COUNTERPARTY_UNKNOWN,
                             contract.DUPLICATE_EXPOSURE, contract.PAUSED_PRE_PAPER)


def _gate_input_value(name: str, bundle: dict, candidate: dict):
    """One GATE_INPUTS entry's current value, for the LOW-item churn fix below (post-
    implementation review, 2026-10-04). Unmapped names (``existing_book_roots``,
    ``other_admitted_exposure_families``/``other_admitted_underlying_roots``,
    ``MIN_GROUPS_PAPER`` — all RUN-level/external, not this candidate's own bundle/cell) return
    ``None`` uniformly: a change there is simply not detected by this optimisation, which only
    ever makes re-screening MORE selective, never less — a missed external change still gets a
    re-screen the next time something IN the bundle also changes, and the inputs this function
    DOES resolve are exactly the ones every currently-failed/unknown gate actually reads."""
    if name in ec.DIMENSIONS:
        return (bundle.get("grades") or {}).get(name)
    if name == "mechanism_id":
        return bundle.get("mechanism_id")
    if name == "net_expected_return":
        return (bundle.get("return_evidence") or {}).get("net_expected_return")
    if name == "paper_mode":
        return bundle.get("paper_mode")
    if name == "exposure_family":
        return bundle.get("exposure_family")
    if name == "underlying_root":
        return candidate.get("underlying_root")
    return None


def _failed_gate_inputs_digest(bundle: dict, candidate: dict, gate_names: set) -> str:
    """A digest over ONLY the inputs the named gates actually read (``evidence_contract.
    GATE_INPUTS``) — never the whole bundle. Two bundles that differ ONLY in a dimension/field no
    currently-failed gate reads hash the SAME here, by design."""
    values = {}
    for gate in sorted(gate_names):
        for inp in ec.GATE_INPUTS.get(gate, ()):
            values[inp] = _gate_input_value(inp, bundle, candidate)
    return contract.digest(values)


def _decision_for_bundle_digest(data_dir: Path, cid: str, bundle_digest: str) -> Optional[dict]:
    """The admission_decision payload recorded FOR this exact bundle digest — never simply
    ``decision.latest_decision`` (which, called after this run's OWN fresh decision is already
    written, would return THAT one, not the one belonging to ``prior_bundle``)."""
    best = None
    for e in ledger_for(data_dir).read_all():
        if e.get("kind") == "admission_decision":
            p = e.get("payload") or {}
            if p.get("candidate_id") == cid and p.get("bundle_digest") == bundle_digest:
                if best is None or e["seq"] > best["seq"]:
                    best = e
    return best.get("payload") if best else None
#: states from which SUPERSEDED (a scanner's own superseded_by, e.g. the funding median5 legacy
#: candidate) is a transition the frozen contract.TRANSITIONS graph actually allows.
_SUPERSEDE_ELIGIBLE_STATES = (contract.REJECTED, contract.STALE_STATE, contract.DATA_INSUFFICIENT,
                              contract.RISK_UNRESOLVED, contract.COUNTERPARTY_UNKNOWN,
                              contract.DUPLICATE_EXPOSURE, contract.PAUSED_PRE_PAPER, contract.PAUSED_PAPER,
                              contract.PAPER_ACTIVE, contract.EVIDENCE_ACCUMULATING, contract.CIO_ELIGIBLE)


def _default_v2_evidence(data_dir: Path, cid: str, candidate: dict) -> dict:
    """The CONSERVATIVE default evidence a candidate gets absent any Package-E3 collector
    (``collect(now, client)``) for it: never claims OBSERVED/STRONG without a real source. A
    scanner/collector that DOES supply richer v2 evidence for this candidate overrides this
    entirely (``res.get("v2_evidence")``, mirroring the ``observations`` convention) — tolerated
    being absent, exactly like a missing scanner module."""
    mechanism_id = candidate.get("mechanism_id")
    is_perp = mechanism_id in _FAMILY_ROOTED_MECHANISMS
    primary_field = "funding" if is_perp else "base_return"
    primary = candidate.get(primary_field)
    if not isinstance(primary, dict):
        primary = {}
    primary_measured = primary.get("state") == contract.MEASURED

    rows = forward.counted_rows(data_dir, cid)
    last_change_at = None
    if rows:
        last_payload = rows[-1].get("payload")
        if not isinstance(last_payload, dict):
            last_payload = {}
        realised_index = last_payload.get("realised_index")
        last_change_at = realised_index.get("as_of") if isinstance(realised_index, dict) else None
        if not last_change_at:
            observed_return = last_payload.get("observed_return")
            last_change_at = observed_return.get("as_of") if isinstance(observed_return, dict) else None
    if not last_change_at:
        last_change_at = primary.get("as_of")

    fam = contract.freshness_family(primary.get("source_root"))
    v2_family = {"funding": "funding_settlement"}.get(fam, "rate")

    cost_components = {}
    for field_name in ("fees", "gas", "hedging_cost"):
        cell = candidate.get(field_name)
        if isinstance(cell, dict) and cell.get("state"):
            cost_components[field_name] = cell

    identity = {"on_chain_verified": primary.get("source_class") == contract.PRIMARY_CHAIN,
               "address_cited": bool(candidate.get("instrument_id"))}
    if is_perp:
        # GRADING_RULES' own perp carve-out ("venue contract spec from the venue API") — a CEX
        # perp has no on-chain contract to verify; a MEASURED settlement row from the venue's own
        # API this run IS that confirmation. Never claimed without a real, fresh venue reading.
        identity["venue_spec_cited"] = primary_measured

    v2 = {
        "identity": identity,
        "return_family": v2_family, "return_last_change_at": last_change_at,
        "return_primary_origin": primary.get("source_root"), "return_cross_checks": [],
        "cost_components": cost_components,
        # a CEX perp leg has no SPA-eligibility/KYC concept distinct from "the venue answered";
        # a Treasury/MMF fund's redemption IS potentially KYC-gated and is never assumed eligible
        # (review #5) — left False here, overridden per-instrument by _treasury_v2_overrides.
        "liquidity_eligible_path_measured": is_perp,
        "redemption": {"terms_cited": False, "caveats_complete": False},
        # CONTRACT has no GATE_NA/DIMENSION_NA carve-out for FUNDING_CAPTURE/SPOT_PERP_BASIS (only
        # DIRECTIONAL_TREND is listed) — a MEASURED settlement row IS this run's confirmation that
        # the funding-rate mechanism reads as documented; never claimed without one.
        "contract_reader_verified": is_perp and primary_measured,
        "forward_series": {"collector_exists": bool(rows), "last_change_at": last_change_at, "family": v2_family},
        "reserves": {}, "legal": {}, "holder_eligibility": {},
    }
    # ADR-564 integration (2026-10-04): a scanner's own paper_accounting_hints (frozen
    # PAPER_ACCOUNTING_EVIDENCE_FIELDS/FEE_COMPONENT shape) is a DIRECT Appendix-I HINT into
    # bundle.py's paper_accounting_evidence — copied through, never re-derived.
    hints = candidate.get("paper_accounting_hints")
    if isinstance(hints, dict):
        v2["paper_accounting"] = hints
    return v2


def _build_profile_for(candidate: dict, facts: list, origins: dict, now: datetime) -> dict:
    """The v2 ``CounterpartyProfile``. A CURATED FACT (reviewed by a different session, ADR-564
    binding #15) always wins over a v1-migrated role for the SAME role, even when the fact's
    honestly-reached state (e.g. IDENTIFIED — the issuer's own document, no independent citation)
    scores LOWER than v1's migration would via a synthetic citation: that synthetic citation's
    origin is a sanitised, FABRICATED string (``profile.migrate_role_from_v1``'s
    ``agent:<identity>``), never the REAL origin a fact names — preferring it over a real fact
    on strength alone would silently swap a true origin for a fabricated one (found by the
    integration acceptance run: USYC's issuer role lost its real ``issuer:hashnote`` origin to a
    synthetic ``agent:circle_/_hashnote`` one, hiding the oracle/issuer circularity the ADR
    explicitly wants named). v1-migration is therefore used ONLY where no fact exists for a role
    at all."""
    mechanism_id = candidate.get("mechanism_id")
    v1_profile_source = candidate.get("counterparty")
    if not isinstance(v1_profile_source, dict):
        v1_profile_source = {}
    # tail of ADR-564 (re-review M4): the issuer's group is the group of the issuer's OWN publications
    # (origins `issuer:*`), never the origin of whichever fact names the issuer ROLE — for BUIDL that is an
    # SEC filing, and the regulator then posed as "the issuer". No issuer publication ⇒ None, and
    # evidence_contract.role_entry then refuses API-based OBSERVED (independence cannot be judged).
    issuer_group = None
    for f in facts:
        origin_id = f.get("origin") or ""
        if origin_id.startswith("issuer:"):
            issuer_group = ec.origin_group(origin_id, origins)
            if issuer_group:
                break

    v1_based_profile = profile_mod.migrate_profile_from_v1(v1_profile_source, mechanism_id, now=now,
                                                           issuer_group=issuer_group, registry=origins)
    fact_profile = profile_mod.build_profile(mechanism_id, facts, issuer_group=issuer_group, registry=origins)
    has_fact = {role: any(f.get("role") == role for f in facts) for role in ec.ROLES}
    return {role: (fact_profile[role] if has_fact[role] else v1_based_profile[role]) for role in ec.ROLES}


def _paper_mode_for(v2_evidence: dict) -> str:
    """ADR-564 binding #5: a candidate whose holder eligibility is RECORDED as anything other
    than SPA_ELIGIBLE (NOT_ELIGIBLE, or UNKNOWN with the requirement itself named — a genuine
    KYC/investor-class/jurisdiction/minimum restriction is on record) is admitted only as
    REFERENCE_TRACK — tracking NAV, never a position SPA could actually hold, and barred from
    CIO_ELIGIBLE (``eligibility.py``'s ``not_reference_track`` gate). A candidate with NO
    holder-eligibility evidence recorded at all (the overwhelming majority of mechanisms — this
    is simply not a KYC-gated instrument) defaults to HOLDABLE: nothing suggests a restriction,
    so none is assumed."""
    state = (v2_evidence.get("holder_eligibility") or {}).get("state")
    if state is None:
        return ec.PAPER_MODE_HOLDABLE
    return ec.PAPER_MODE_HOLDABLE if state == ec.SPA_ELIGIBLE else ec.PAPER_MODE_REFERENCE_TRACK


def _exposure_family_for(candidate: dict) -> Optional[str]:
    if candidate.get("mechanism_id") in _FAMILY_ROOTED_MECHANISMS:
        return candidate.get("underlying_root")
    return None  # bundle.build_bundle defaults to the candidate's own exposure_key


def _ideal_hold_target(outcome: dict, bundle: dict) -> Optional[str]:
    """The hold state Sherlock's decision NAMES, before checking whether the current lifecycle
    state can actually reach it (``_route_sherlock_outcome`` does that check)."""
    decision_kind = outcome["decision"]
    if decision_kind == ec.REJECT:
        return contract.REJECTED
    if decision_kind == ec.DECISION_STALE:
        return contract.STALE_STATE
    if decision_kind == ec.HOLD:
        conflicts = set(bundle.get("conflicts") or [])
        return contract.COUNTERPARTY_UNKNOWN if "COUNTERPARTY" in conflicts else contract.RISK_UNRESOLVED
    if decision_kind == ec.NEEDS_MORE_EVIDENCE:
        failed_fail = set(outcome.get("failed_gates") or [])
        failed = failed_fail | set(outcome.get("unknowns") or [])
        for gate in ec.ADMISSION_V2_GATES:  # declared order — "the FIRST failed gate"
            if gate in failed and gate in _GATE_DIM_HOLD:
                # freshness: a JUDGED-too-old source (gate FAIL) is STALE — "we know it and it aged out";
                # no judgeable time at all (gate UNKNOWN) is DATA_INSUFFICIENT (live-run finding: never-fresh
                # candidates were mislabelled STALE)
                if gate in _FRESHNESS_GATES and gate in failed_fail:
                    return contract.STALE_STATE
                return _GATE_DIM_HOLD[gate]
        return contract.DATA_INSUFFICIENT
    return None  # ADMIT_TO_PAPER — handled separately


def _admit_walk(data_dir: Path, cid: str, frm_state: str, bundle: dict, prior_bundle: Optional[dict],
                outcome: dict, digest_changed: bool, now: datetime) -> None:
    """ADR-564 binding #1 (live-validation finding, 2026-10-04): v1's pass no longer gates
    anything, so ADMIT must walk the WHOLE allowed chain itself, in one call, from wherever the
    candidate currently sits — re-screen (if a hold state with a CHANGED bundle digest, the
    decision's own bundle digests as the gate_ref evidence) -> SCREENED -> RESEARCH_READY ->
    PAPER_CANDIDATE -> the v2 snapshot -> PAPER_ACTIVE -> ``paper.open_position``. A
    ``PaperRefusal`` is logged and LEAVES the candidate at PAPER_CANDIDATE — never PAPER_ACTIVE
    without an actual position; a position is opened BEFORE the lifecycle moves, never after, so
    this is a real guarantee, not a race."""
    state = frm_state
    if state == contract.PAPER_ACTIVE:
        return  # already admitted — idempotent no-op

    if state == contract.PAUSED_PAPER:
        _resume_paused(data_dir, cid, outcome, now)
        return

    if state in _RESCREENABLE_HOLD_STATES:
        if not (digest_changed and prior_bundle is not None):
            return  # a hold state needs a genuine evidence change to re-screen from; none here
        gate_ref = {"prev_digest": prior_bundle["evidence_digest"], "new_digest": bundle["evidence_digest"]}
        try:
            lifecycle.transition(data_dir, cid, contract.SCREENED, gate_ref=gate_ref,
                                reason="Sherlock ADMIT_TO_PAPER: evidence changed, re-screening", now=now)
        except lifecycle.InvalidTransition:
            return
        state = contract.SCREENED

    if state == contract.SCREENED:
        lifecycle.transition(data_dir, cid, contract.RESEARCH_READY,
                            reason="Sherlock ADMIT_TO_PAPER: proceeding to admission", now=now)
        state = contract.RESEARCH_READY

    if state == contract.RESEARCH_READY:
        lifecycle.transition(data_dir, cid, contract.PAPER_CANDIDATE,
                            reason="Sherlock ADMIT_TO_PAPER: proceeding to admission", now=now)
        state = contract.PAPER_CANDIDATE

    if state != contract.PAPER_CANDIDATE or not contract.transition_allowed(state, contract.PAPER_ACTIVE):
        return  # not (or no longer) reachable from here — named by the decision row, not forced

    snap = decision.write_admission_snapshot_v2(data_dir, outcome, bundle, now)
    admission_id = snap["payload"]["admission_id"]
    if paper is None:
        return  # Package E2 not importable — the v2 snapshot is recorded; no position to open
    try:
        paper.open_position(data_dir, outcome, snap["payload"], bundle, now)
    except paper.PaperRefusal as exc:
        # a real gap between the 20-gate admission report and paper.py's OWN stricter accounting
        # validation — named, not silently swallowed. The candidate stays at PAPER_CANDIDATE
        # (never PAPER_ACTIVE without a position); the next run's re-evaluation surfaces it again.
        ledger_for(data_dir).append_idempotent(
            "run_warning", ["run_warning", cid, iso(now)],
            {"candidate_id": cid, "warning": f"paper.open_position refused: {exc}"}, iso(now))
        return
    lifecycle.transition(data_dir, cid, contract.PAPER_ACTIVE, gate_ref=admission_id,
                        reason="Sherlock ADMIT_TO_PAPER", now=now)


def _resume_paused(data_dir: Path, cid: str, outcome: dict, now: datetime) -> None:
    """ADR-564 post-impl remediation (M4 follow-up): PAUSED_PAPER had a way in and no way out —
    a candidate Sherlock re-ADMITs resumes to its recorded ``paused_from`` (CIO_ELIGIBLE re-enters
    EVIDENCE_ACCUMULATING; lifecycle enforces both) through the SAME admission door it was paused
    under: the active paper-admission/2 snapshot, re-validated by ``lifecycle.transition``. Resume
    only while that admission's paper position is still OPEN — never PAPER_ACTIVE without a
    position; otherwise a named run_warning and the candidate stays paused."""
    admission_id = lifecycle.active_admission_id(data_dir, cid)
    open_positions = [] if paper is None else [
        p for p in paper.positions(data_dir) if p.get("candidate_id") == cid and p.get("status") == "OPEN"]
    paused_row = lifecycle._last_transition_to(ledger_for(data_dir), cid, contract.PAUSED_PAPER)
    paused_from = ((paused_row or {}).get("payload") or {}).get("paused_from")
    target = contract.EVIDENCE_ACCUMULATING if paused_from == contract.CIO_ELIGIBLE else paused_from
    reason = None
    if admission_id is None:
        reason = "no active admission to resume under"
    elif not open_positions:
        reason = "no OPEN paper position for the active admission"
    elif target not in (contract.PAPER_ACTIVE, contract.EVIDENCE_ACCUMULATING):
        reason = f"recorded paused_from {paused_from!r} is not resumable"
    if reason is None:
        try:
            lifecycle.transition(data_dir, cid, target, gate_ref=admission_id,
                                 reason=f"Sherlock ADMIT_TO_PAPER {outcome.get('decision_id')}: resuming "
                                        f"from PAUSED_PAPER to {target}", now=now)
            # N2 (post-implementation review, 2026-10-04): the resume reuses the PRE-pause
            # admission_id (gate_ref above, by design — same admission door), so the NEW
            # ADMIT_TO_PAPER decision that triggered this resume (``outcome``) is otherwise
            # nowhere on the transition row itself — only in its free-text ``reason``, which is
            # not a field a reader can rely on. lifecycle.transition's signature carries no extra
            # payload slot beyond gate_ref/reason, so this is a separate, idempotent ledger row
            # naming it structurally.
            ledger_for(data_dir).append_idempotent(
                "resume_evidence", ["resume_evidence", cid, admission_id, outcome.get("decision_id")],
                {"candidate_id": cid, "admission_id": admission_id,
                 "decision_id": outcome.get("decision_id"), "bundle_digest": outcome.get("bundle_digest")},
                iso(now))
            return
        except lifecycle.InvalidTransition as exc:
            reason = f"resume refused: {exc}"
    ledger_for(data_dir).append_idempotent(
        "run_warning", ["run_warning", cid, iso(now)],
        {"candidate_id": cid, "warning": f"PAUSED_PAPER not resumed: {reason}"}, iso(now))


def _route_sherlock_outcome(data_dir: Path, cid: str, candidate: dict, frm_state: str, bundle: dict,
                            prior_bundle: Optional[dict], outcome: dict, digest_changed: bool,
                            now: datetime) -> None:
    """Applies Sherlock's decision to the lifecycle wherever the FROZEN ``contract.TRANSITIONS``
    graph actually permits it from ``frm_state`` — the decision is always RECORDED (the bundle +
    decision rows already are, by the caller), but the graph is never bent to force a move it
    does not already allow. ADMIT walks the whole chain (``_admit_walk``). A non-ADMIT decision
    on an ALREADY-admitted candidate (``contract.PAPER_STATES``) demotes it straight to
    PAUSED_PAPER (post-implementation review M4) — uniformly for every non-ADMIT decision kind
    (REJECT/HOLD/DECISION_STALE/NEEDS_MORE_EVIDENCE alike), never the mixed, reachability-
    dependent outcome ``_ideal_hold_target`` would otherwise give an admitted candidate (REJECTED
    and STALE_STATE happen to be directly reachable FROM PAPER_ACTIVE in the frozen graph, the
    other hold targets are not — that inconsistency is exactly the gap this fixes). Everywhere
    else: the ideal hold target if reachable; else, for a hold-state candidate whose bundle digest
    CHANGED, a re-screen (failed gate inputs changed, the decision row is the gate_ref evidence)
    back to SCREENED; else the state is left untouched this run."""
    if outcome["decision"] == ec.ADMIT_TO_PAPER:
        _admit_walk(data_dir, cid, frm_state, bundle, prior_bundle, outcome, digest_changed, now)
        return

    if frm_state in contract.PAPER_STATES:
        lifecycle.transition(data_dir, cid, contract.PAUSED_PAPER,
                            reason=f"Sherlock decision={outcome['decision']} on an admitted candidate: "
                                  + "; ".join(outcome["rationale"]), now=now)
        # tail of ADR-564 (N4): this run's observation was recorded before this review — it does not count
        forward.void_unconfirmed_periods(data_dir, cid, now,
                                         f"evidence lapsed in this run (decision={outcome['decision']})")
        return

    target = _ideal_hold_target(outcome, bundle)
    if target is not None and target == frm_state:
        # live re-run finding (2026-10-04): hourly funding data changes a failed gate's inputs
        # every run, so 28 pairs cycled <hold> -> SCREENED -> RESEARCH_READY -> <same hold> (84
        # transitions a run). The decision row already records the new evidence; a candidate
        # already sitting in the state Sherlock would send it to does not move.
        return
    if target is not None and contract.transition_allowed(frm_state, target):
        lifecycle.transition(data_dir, cid, target, reason="; ".join(outcome["rationale"]), now=now)
        return

    if frm_state in _RESCREENABLE_HOLD_STATES and digest_changed and prior_bundle is not None:
        # LOW (post-implementation review, 2026-10-04): ~30 candidates were cycling
        # <hold state> -> SCREENED -> <same hold state> EVERY run, because ANY bundle-digest
        # change re-screened them — including a change to a dimension/field no currently-failed
        # gate even reads. Re-screen only when the inputs of the gate(s) that are ACTUALLY
        # failed/unknown right now changed; no prior decision to scope to (or a gate name that
        # isn't a v2 gate, e.g. the frozen reserved ones) fails OPEN to the old, safe behaviour —
        # this is strictly a reduction in churn, never a reduction in correctness.
        prior_decision = _decision_for_bundle_digest(data_dir, cid, prior_bundle["evidence_digest"])
        relevant_gates = None
        if prior_decision is not None:
            relevant_gates = {g for g in (prior_decision.get("failed_gates") or []) if g in ec.GATE_INPUTS} | \
                {g for g in (prior_decision.get("unknowns") or []) if g in ec.GATE_INPUTS}
        inputs_changed = True
        if relevant_gates:
            inputs_changed = (_failed_gate_inputs_digest(prior_bundle, candidate, relevant_gates)
                             != _failed_gate_inputs_digest(bundle, candidate, relevant_gates))
        if not inputs_changed:
            return  # the bundle changed, but nothing the currently-failing gate(s) read did
        gate_ref = {"prev_digest": prior_bundle["evidence_digest"], "new_digest": bundle["evidence_digest"]}
        try:
            lifecycle.transition(data_dir, cid, contract.SCREENED, gate_ref=gate_ref,
                                reason=f"Sherlock evidence changed (decision={outcome['decision']}): "
                                      + "; ".join(outcome["rationale"]), now=now)
        except lifecycle.InvalidTransition:
            return  # already re-screened this run via another path, or the digests tied — not an error
        # live-run finding: the re-screen stopped at SCREENED (OUSG/USDY sat there). The decision names its hold
        # target; SCREENED may reach every hold state, so finish the move in the same call.
        if target is not None and contract.transition_allowed(contract.SCREENED, target):
            lifecycle.transition(data_dir, cid, target, reason="; ".join(outcome["rationale"]), now=now)


def _sherlock_review_candidate(data_dir: Path, cid: str, candidate: dict, existing_book_roots: list,
                               other_admitted_exposure_families: dict, origins: dict, facts_all: list,
                               v2_overrides: dict, now: datetime, *,
                               other_admitted_underlying_roots: Optional[dict] = None) -> None:
    """ADR-564 §8: Sherlock reviews EVERY candidate not in a terminal state and not OBSERVE_ONLY,
    every run — builds the bundle -> grades -> v2 report -> decision, writes a NEW decision row
    ONLY when the bundle's content digest changed since the last evaluation (idempotent on an
    unchanged bundle), and applies the decision to the lifecycle (``_route_sherlock_outcome``).

    ``other_admitted_underlying_roots`` (post-implementation review M6, 2026-10-04): a wrapper
    or other-chain copy of the SAME fund shares ``underlying_root`` but — for a mechanism not in
    ``_FAMILY_ROOTED_MECHANISMS`` — gets its OWN ``exposure_family`` (bundle.py defaults it to
    the candidate's own exposure_key), so the existing exposure_family dedup never catches it.
    ``admission_v2._duplicate_exposure_clear`` reads this dict (``{root: holder_cid}``) the SAME
    way it already reads ``other_admitted_exposure_families``."""
    frm_state = lifecycle.current_state(data_dir, cid)
    if frm_state is None or frm_state in contract.TERMINAL_STATES or frm_state == contract.OBSERVE_ONLY:
        return

    superseded_by = candidate.get("superseded_by")
    if superseded_by and frm_state in _SUPERSEDE_ELIGIBLE_STATES:
        lifecycle.transition(data_dir, cid, contract.SUPERSEDED,
                            reason=f"superseded by {superseded_by}", now=now)
        return

    mechanism_id = candidate.get("mechanism_id")
    if mechanism_id not in contract.MECHANISMS or not candidate.get("exposure_key"):
        return  # not yet identity-resolved; v1's own DISCOVERED->SCREENED gate names this

    facts = registry_loader.facts_for(facts_all, cid, now=now)
    profile = _build_profile_for(candidate, facts, origins, now)
    v2_evidence = dict(_default_v2_evidence(data_dir, cid, candidate))
    v2_evidence.update(v2_overrides.get(cid) or {})
    paper_mode = _paper_mode_for(v2_evidence)
    exposure_family = _exposure_family_for(candidate)

    # NOTE: v2_evidence may carry "return_primary_cell_override" (e.g. the on-chain oracle
    # reading for a NAV-reader instrument, ADR-564 decision #5) — grades.grade_return and
    # bundle.py's return_evidence.primary_cell use it for GRADING; the candidate dict itself is
    # NEVER swapped, so contract.net_expected_return() keeps netting costs against the v1 cell's
    # own declared ANNUAL rate, not a raw NAV/price reading (a real regression found and fixed
    # by the integration acceptance run — see grades.grade_return's docstring).
    bundle = bundle_mod.build_bundle(candidate, profile=profile, v2_evidence=v2_evidence, facts=facts,
                                     paper_mode=paper_mode, registry=origins, now=now,
                                     exposure_family=exposure_family)

    prior_bundle = bundle_mod.latest_bundle(data_dir, cid)
    digest_changed = prior_bundle is None or prior_bundle.get("evidence_digest") != bundle["evidence_digest"]

    extra = {"existing_book_roots": existing_book_roots,
            "other_admitted_exposure_families": other_admitted_exposure_families,
            "other_admitted_underlying_roots": other_admitted_underlying_roots or {}}
    if digest_changed:
        bundle_mod.write_bundle(data_dir, bundle, now)
        outcome = decision.decide_and_record(data_dir, bundle, candidate, extra=extra, now=now)
    else:
        outcome = decision.latest_decision(data_dir, cid)
        if outcome is None or outcome.get("bundle_digest") != bundle["evidence_digest"]:
            outcome = decision.decide_and_record(data_dir, bundle, candidate, extra=extra, now=now)

    _route_sherlock_outcome(data_dir, cid, candidate, frm_state, bundle, prior_bundle, outcome,
                           digest_changed, now)



def _mark_open_positions(data_dir: Path, v2_overrides: dict, origins: dict, now: datetime) -> None:
    """Live-run finding: open paper positions were never marked. Every OPEN position gets one mark per run
    from THIS run's MEASURED NAV reading (``nav_price_cell``). No measured reading ⇒ a STALE mark with NO price
    (paper.mark never forward-fills). Idempotent: paper keys a mark by (position_id, timestamp)."""
    if paper is None:
        return
    try:
        open_positions = [p for p in paper.positions(data_dir) if p.get("status") == "OPEN"]
    except Exception:  # noqa: BLE001 — no paper ledger yet
        return
    for pos in open_positions:
        cid = pos.get("candidate_id")
        ov = v2_overrides.get(cid) if isinstance(v2_overrides, dict) else None
        nav_cell = ov.get("nav_price_cell") if isinstance(ov, dict) else None
        origin = ov.get("nav_origin") if isinstance(ov, dict) else None
        if not (isinstance(nav_cell, dict) and nav_cell.get("state") == contract.MEASURED):
            nav_cell = contract.cell(contract.NOT_MEASURED, reason="no MEASURED NAV reading this run")
        groups = ec.origin_groups([{"origin": origin}], origins) if origin else []
        try:
            paper.mark(data_dir, pos["position_id"],
                       {"price": nav_cell, "mark_origin": origin or "unknown", "origin_group": groups[0] if groups else None,
                        "leg_id": pos.get("leg_id")}, now)
        except paper.PaperRefusal as exc:
            ledger_for(data_dir).append("run_warning", ["paper_mark", pos["position_id"], iso(now)],
                                        {"candidate_id": cid, "warning": f"paper.mark refused: {exc}"}, iso(now))

#: M6 (post-implementation review, 2026-10-04): a candidate PAUSED off a non-ADMIT decision is
#: STILL a held paper position — its paper.py position is still OPEN, it only stopped maturing
#: (N1 above). contract.PAPER_STATES alone under-counted "what is held" for dedup purposes: a
#: second copy of a paused fund admitted later in the SAME run was not caught as a duplicate.
_HELD_ON_PAPER_STATES = contract.PAPER_STATES + (contract.PAUSED_PAPER,)


def _record_held_exposure(data_dir: Path, cid: str, candidate: dict, exposure_families: dict,
                          underlying_roots: dict) -> None:
    bundle = bundle_mod.latest_bundle(data_dir, cid)
    family = (bundle or {}).get("exposure_family") or _exposure_family_for(candidate) \
        or candidate.get("exposure_key")
    exposure_families[family] = cid
    root = candidate.get("underlying_root")
    if root:
        underlying_roots[root] = cid


def _sherlock_review_all(data_dir: Path, all_candidates: dict, existing_book_roots: list, origins: dict,
                         facts_all: list, v2_overrides: dict, now: datetime) -> None:
    other_admitted_exposure_families: dict = {}
    other_admitted_underlying_roots: dict = {}  # M6: a wrapper/other-chain copy of the SAME fund
    for other_cid, other_candidate in all_candidates.items():
        other_state = lifecycle.current_state(data_dir, other_cid)
        if other_state in _HELD_ON_PAPER_STATES:
            _record_held_exposure(data_dir, other_cid, other_candidate,
                                  other_admitted_exposure_families, other_admitted_underlying_roots)

    for cid, candidate in all_candidates.items():
        other_families_excl_self = {fam: holder for fam, holder in other_admitted_exposure_families.items()
                                    if holder != cid}
        other_roots_excl_self = {root: holder for root, holder in other_admitted_underlying_roots.items()
                                 if holder != cid}
        _sherlock_review_candidate(data_dir, cid, candidate, existing_book_roots, other_families_excl_self,
                                   origins, facts_all, v2_overrides, now,
                                   other_admitted_underlying_roots=other_roots_excl_self)
        # M6 (b): a candidate ADMITTED just now, during THIS loop, is a held exposure for every
        # later candidate in the SAME loop too — without this, two copies of the same fund
        # discovered/admitted in the same run slip past each other (built-before-loop snapshot
        # only ever saw candidates admitted on a PRIOR run).
        if lifecycle.current_state(data_dir, cid) == contract.PAPER_ACTIVE:
            _record_held_exposure(data_dir, cid, candidate,
                                  other_admitted_exposure_families, other_admitted_underlying_roots)


def _process_candidate(data_dir: Path, cid: str, all_candidates: dict, existing_book_roots: list,
                       new_obs: dict, now: datetime) -> None:
    """ADR-564 binding #1 (live-validation finding, 2026-10-04): v1 admission
    (``admission.evaluate()``/``_route_hold_state``) is DISPLAY-ONLY now — it NEVER moves the
    lifecycle to a hold state. This pass only does the FORWARD, gate-free unlocking a brand-new
    candidate needs to become REVIEWABLE (DISCOVERED -> SCREENED -> RESEARCH_READY, unconditional
    once identity/mechanism are resolved — and STOPS at RESEARCH_READY, never walks on to
    PAPER_CANDIDATE here; see the inline comment at that step for why) and the post-admission
    bookkeeping (observation recording, EVIDENCE_ACCUMULATING promotion, CIO eligibility
    recheck). EVERY lifecycle consequence beyond RESEARCH_READY — ADMIT (including the
    RESEARCH_READY -> PAPER_CANDIDATE -> PAPER_ACTIVE walk), and every hold state a candidate
    sits in (COUNTERPARTY_UNKNOWN, DATA_INSUFFICIENT, RISK_UNRESOLVED, ...) — is Sherlock's
    decision alone (``_sherlock_review_all``), which runs after this pass over the WHOLE
    candidate set, every run. A candidate with no resolved identity simply stays DISCOVERED
    (never DATA_INSUFFICIENT from here — that label is Sherlock's call too, the instant it has
    a bundle to judge)."""
    candidate = all_candidates.get(cid)
    if candidate is None:
        return
    state = lifecycle.current_state(data_dir, cid)
    if state == contract.DISCOVERED:
        if candidate.get("mechanism_id") in contract.MECHANISMS and candidate.get("exposure_key"):
            lifecycle.transition(data_dir, cid, contract.SCREENED,
                                reason="identity resolved, mechanism known", now=now)
            state = contract.SCREENED
        else:
            return  # stays DISCOVERED; nothing to unlock yet, and this is not a hold-state call

    if state == contract.SCREENED:
        lifecycle.transition(data_dir, cid, contract.RESEARCH_READY, reason="admission evaluable", now=now)
        state = contract.RESEARCH_READY

    # STOPS at RESEARCH_READY, never walks on to PAPER_CANDIDATE here (found verifying failure_matrix.py
    # against this round's fix): every OTHER hold state (COUNTERPARTY_UNKNOWN/DATA_INSUFFICIENT/
    # RISK_UNRESOLVED/STALE/REJECTED/DUPLICATE_EXPOSURE) IS reachable from RESEARCH_READY per the frozen
    # contract.TRANSITIONS graph but NOT from PAPER_CANDIDATE (which only reaches DATA_INSUFFICIENT/
    # PAPER_ACTIVE/PAUSED_PRE_PAPER/REJECTED/STALE) — forcing every brand-new candidate on to
    # PAPER_CANDIDATE unconditionally, in THIS pass, before Sherlock ever looks at it, would silently
    # strand a counterparty-unknown/risk-unresolved/duplicate-exposure candidate at PAPER_CANDIDATE
    # forever (_ideal_hold_target's own transition_allowed check refuses the move and does nothing).
    # Sherlock's OWN admit walk (_admit_walk) is the one and only thing that takes the RESEARCH_READY ->
    # PAPER_CANDIDATE step now, as part of walking all the way to PAPER_ACTIVE on ADMIT_TO_PAPER.
    if state == contract.RESEARCH_READY:
        return  # Sherlock's universal review decides ADMIT/hold from here — never this pass

    # post-implementation review M4 (2026-10-04): a PAUSED_PAPER candidate (Sherlock demoted it
    # off a non-ADMIT decision, _route_sherlock_outcome below) keeps being MARKED — "marks
    # continue only as labelled tracking": forward.record works from any state (it reads
    # lifecycle.active_admission_id, which looks at the latest PAPER_ACTIVE row regardless of
    # the CURRENT state), and PAUSED_PAPER itself already IS the "this is tracking only, not
    # active" label a reader needs — no separate flag required.
    if state in (contract.PAPER_ACTIVE, contract.EVIDENCE_ACCUMULATING, contract.CIO_ELIGIBLE,
                contract.PAUSED_PAPER):
        # H4: an observation row is written EVERY run for EVERY paper-state candidate — a
        # NOT_MEASURED cell when no scanner supplied one this run, rather than silently writing
        # nothing at all. A silent gap could never trip the 3-consecutive-not-counted -> STALE
        # rule (forward._maybe_mark_stale); a feed that goes quiet would then look no different
        # from one with no activity to report, forever.
        obs = new_obs.get(cid)
        if obs is None:
            obs = {"period": now.strftime("%Y-%m-%d"), "backfill": False, "realised_index": None,
                  "observed_return": contract.cell(contract.NOT_MEASURED,
                                                    reason="no observation from any scanner this run")}
        forward.record(data_dir, cid, obs, now)


def _promote_after_review(data_dir: Path, cid: str, all_candidates: dict, existing_book_roots: list,
                          now: datetime) -> None:
    """Re-review M1 (tail of ADR-564): promotion PAPER_ACTIVE → EVIDENCE_ACCUMULATING and the CIO eligibility
    recheck run AFTER Sherlock's review, never on a period the same run's review may void — before, a lapsed
    run's period promoted the candidate and the pause then left EVIDENCE_ACCUMULATING with 0 periods."""
    candidate = all_candidates.get(cid)
    if candidate is None:
        return
    state = lifecycle.current_state(data_dir, cid)
    if state == contract.PAPER_ACTIVE and forward.forward_periods(data_dir, cid) >= 1:
        admission_id = lifecycle.active_admission_id(data_dir, cid)
        lifecycle.transition(data_dir, cid, contract.EVIDENCE_ACCUMULATING, gate_ref=admission_id,
                            reason="first counted forward period recorded", now=now)
        state = contract.EVIDENCE_ACCUMULATING

    if state in (contract.EVIDENCE_ACCUMULATING, contract.CIO_ELIGIBLE):
        view = _registry_view_for(data_dir, cid, all_candidates, existing_book_roots)
        eligibility.recheck_and_apply(data_dir, candidate, view, now)


def run_once(data_dir: Path, now: datetime, *, rpc_client=None, http_client_=None) -> dict:
    ledger = ledger_for(data_dir)
    with ledger.run_lock():
      try:
        verdict = ledger.verify()
        if not verdict["ok"]:
            raise LedgerError(f"ledger BROKEN (reason={verdict.get('reason')}); refusing to run")
        # M7: one full chain+anchor walk for the WHOLE run, not one per append. The anchors are
        # still extended on every write below, so a LATER, independent verify() still catches a
        # torn/tampered history — only the redundant re-walk inside an already-verified run is
        # skipped.
        ledger.mark_verified()

        # ADR-564 §8: Sherlock's evidence refresh runs BEFORE the scanners, because two scanners
        # (basis/rwa) need its output passed straight into their OWN scan() call (decision #6's
        # funding PAIR candidates; decision #4's chain-correct RWA pool join) — `client` stays
        # None (every collector tolerates that) unless the caller opted into live network via
        # `http_client_=` (mirrors `rpc_client`'s own --live-rpc opt-in — never constructed here).
        origins = registry_loader.load_origins()
        fact_refusals = []  # H6: a fact lacking independent review / an origin-host match is
        # EXCLUDED from facts_all but named here, same discipline as scanner_errors below —
        # never a silent drop, never a whole-file halt for a semantic (not structural) gap.
        facts_all = registry_loader.load_facts(origins=origins, refused_out=fact_refusals)
        scanner_errors = []  # H0: logged into the run row, never silently swallowed

        raw_pools = _fetch_defillama_pools(http_client_)
        funding_rows, book_rows = _collect_funding_and_books(http_client_, now)
        _persist_observation_rows(data_dir, funding_rows + book_rows, now)
        treasury_overrides = _treasury_v2_overrides(data_dir, facts_all, rpc_client, http_client_, raw_pools, now)
        other_rows, v2_overrides, collector_errors = _run_other_collectors(now, http_client_, rpc_client)
        _persist_observation_rows(data_dir, other_rows, now)
        for cid, override in treasury_overrides.items():
            v2_overrides.setdefault(cid, {}).update(override)
        scanner_errors.extend(collector_errors)

        #: scanner module name -> extra kwargs this run's collected evidence supplies (signature-
        #: checked below, same discipline as _call_collect — never a blind kwarg that would
        #: TypeError a scanner that does not declare it).
        _scanner_extra_kwargs = {
            "basis": {"funding_rows": funding_rows, "book_rows": book_rows},
            "rwa": {"raw_pools": raw_pools},
        }

        scanners = _discover_scanners()
        scan_results = []
        for mod in scanners:
            mod_short_name = (getattr(mod, "__name__", "") or "").rsplit(".", 1)[-1]
            extra = {}
            declared = _scanner_extra_kwargs.get(mod_short_name) or {}
            if declared:
                try:
                    params = inspect.signature(mod.scan).parameters
                except (TypeError, ValueError):
                    params = {}
                extra = {k: v for k, v in declared.items() if k in params}
            try:
                scan_results.append(mod.scan(data_dir, now, rpc_client=rpc_client, **extra))
            except Exception as exc:  # noqa: BLE001 — one broken scanner must not sink the run
                name = getattr(mod, "__name__", "?")
                detail = f"{type(exc).__name__}: {exc}"
                scanner_errors.append({"scanner": name, "error": detail})
                scan_results.append({"scanner": name, "domain": None,
                                     "as_of": iso(now), "status": "UNAVAILABLE", "reason": detail,
                                     "denominators": {"scanned": None, "discovered": 0, "truncated": None},
                                     "candidates": [], "unresolved": [], "observations": {}, "counterparty": {},
                                     "existing_book_roots": []})

        existing_book_roots: list = []
        new_obs: dict = {}
        seen_this_run: dict = {}  # scanner_name -> {candidate_id, ...}
        discovered_ids_by_domain: dict = {}
        total_scanned = total_truncated = 0
        any_scanned = any_truncated = False

        for res in scan_results:
            denom = res.get("denominators") or {}
            if denom.get("scanned") is not None:
                total_scanned += denom["scanned"]
                any_scanned = True
            if denom.get("truncated") is not None:
                total_truncated += denom["truncated"]
                any_truncated = True
            existing_book_roots.extend(res.get("existing_book_roots") or [])

            scanner_name = res.get("scanner")
            ids_this_scanner = set()
            for cand in res.get("candidates") or []:
                full = {f: cand.get(f) for f in contract.CANDIDATE_FIELDS}
                # H3: the field disappearance is keyed by is the PRODUCING SCANNER, never
                # `venue_or_protocol` (a protocol name, not a scanner name — comparing it
                # against `seen_this_run` (keyed by scanner) silently never matched, so
                # disappearance never fired). Not part of contract.CANDIDATE_FIELDS (frozen); an
                # extra key on the dict, set here at ingestion as instructed.
                full["producing_scanner"] = scanner_name
                cp_map = res.get("counterparty")
                cp = cp_map.get(full["candidate_id"]) if isinstance(cp_map, dict) else None
                if cp is not None:
                    full["counterparty"] = cp
                # ADR-564 integration (2026-10-04): a scanner hint in evidence_contract's frozen
                # PAPER_ACCOUNTING_EVIDENCE_FIELDS/FEE_COMPONENT shape — not part of
                # contract.CANDIDATE_FIELDS (frozen), an extra key exactly like producing_scanner.
                hints = cand.get("paper_accounting_hints")
                if isinstance(hints, dict):
                    full["paper_accounting_hints"] = hints
                # ADR-564 decision #6: a scanner's own superseded_by (e.g. the funding median5
                # legacy candidate, superseded by its per-venue-pair family) — not part of
                # contract.CANDIDATE_FIELDS (frozen), an extra key exactly like producing_scanner.
                superseded_by = cand.get("superseded_by")
                if superseded_by:
                    full["superseded_by"] = superseded_by
                if res.get("domain") == "TRADING_RESEARCH":
                    full["admission_state"] = contract.OBSERVE_ONLY
                registry.upsert(data_dir, full, now)
                ids_this_scanner.add(full["candidate_id"])
                discovered_ids_by_domain.setdefault(res.get("domain"), set()).add(full["candidate_id"])
                # live re-run finding (2026-10-04): the v1 fingerprint re-screen moved every held
                # funding pair (live rate in its snapshot) <hold> -> SCREENED each run, only for
                # Sherlock to send it back — ~80 transitions a run. Hold states are Sherlock's
                # call alone (ADR-564 binding #1); _route_sherlock_outcome re-screens, scoped to
                # the failed gates' inputs, and _admit_walk handles an ADMIT from any hold state.

                if res.get("domain") == "TRADING_RESEARCH":
                    lifecycle.transition(data_dir, full["candidate_id"], contract.OBSERVE_ONLY,
                                        reason="projected read-only from trading_research", now=now)

            for u in res.get("unresolved") or []:
                registry.record_unresolved(data_dir, scanner_name, res.get("domain"), u, now)

            for cid, obs in (res.get("observations") or {}).items():
                new_obs[cid] = obs

            holder_eligibility_map = res.get("holder_eligibility")
            if isinstance(holder_eligibility_map, dict):
                for cid, hint in holder_eligibility_map.items():
                    if isinstance(hint, dict):
                        v2_overrides.setdefault(cid, {})["holder_eligibility"] = hint

            for cid, v2 in (res.get("v2_evidence") or {}).items():
                if isinstance(v2, dict):
                    v2_overrides.setdefault(cid, {}).update(v2)

            if res.get("status") == "OK":
                seen_this_run[scanner_name] = ids_this_scanner

        all_candidates = {cid: (registry.current_candidate(data_dir, cid) or {})
                          for cid in registry.all_candidate_ids(ledger)}

        # disappearance: a paper-state candidate missing from its OWN PRODUCING SCANNER's output
        # this run, for a run where THAT scanner's status was OK (H3) — never UNAVAILABLE.
        for cid, candidate in all_candidates.items():
            state = lifecycle.current_state(data_dir, cid)
            if state not in contract.PAPER_STATES:
                continue
            producing_scanner = candidate.get("producing_scanner")
            if producing_scanner in seen_this_run and cid not in seen_this_run[producing_scanner]:
                ledger.append_idempotent("disappearance", ["disappearance", cid, iso(now)],
                                        {"candidate_id": cid, "last_state": state,
                                         "producing_scanner": producing_scanner}, iso(now))
                lifecycle.transition(data_dir, cid, contract.DISAPPEARED,
                                    reason="absent from an OK scanner's output this run", now=now)

        for cid in list(all_candidates):
            _process_candidate(data_dir, cid, all_candidates, existing_book_roots, new_obs, now)

        # ADR-564 §8: Sherlock's universal review — EVERY candidate not in a terminal state and
        # not OBSERVE_ONLY, regardless of what the v1 pass just did to it (including one that
        # reached PAPER_CANDIDATE only THIS run, and one still sitting in a v1 hold state).
        all_candidates = {cid: (registry.current_candidate(data_dir, cid) or {})
                          for cid in registry.all_candidate_ids(ledger)}

        # collectors.contract_identity: PRIMARY_IDENTITY's own "venue contract spec from the
        # venue API" evidence for a funding PAIR candidate — run AFTER scanners.basis.scan() so
        # the pair candidates (built from THIS run's funding_rows/book_rows) actually exist to
        # match against.
        identity_rows = _collect_contract_identity(http_client_, now)
        _persist_observation_rows(data_dir, identity_rows, now)
        for cid, override in _funding_pair_identity_overrides(all_candidates, identity_rows).items():
            v2_overrides.setdefault(cid, {}).update(override)

        _sherlock_review_all(data_dir, all_candidates, existing_book_roots, origins, facts_all,
                            v2_overrides, now)
        for cid in list(all_candidates):
            _promote_after_review(data_dir, cid, all_candidates, existing_book_roots, now)
        _mark_open_positions(data_dir, v2_overrides, origins, now)

        run_payload = {
            "generated_at": iso(now),
            "denominators": {"scanned": total_scanned if any_scanned else None,
                            "discovered": sum(len(v) for v in discovered_ids_by_domain.values()),
                            "truncated": total_truncated if any_truncated else None},
            "scanners": [r.get("scanner") for r in scan_results],
            "scanner_errors": scanner_errors,  # H0: logged, never silently dropped
            "fact_refusals": fact_refusals,  # H6: logged, never silently dropped
        }
        ledger.append_idempotent("run", ["run", iso(now)], run_payload, iso(now))

        status = read.latest(data_dir)
        atomic_save(status, str(ledger.root() / contract.STATUS))
        registry.rebuild_index(data_dir)
        return status
      finally:
        # N3: trust (and the read_all() cache it permits) is scoped to EXACTLY this run — revoke
        # it the instant the run ends (success OR failure), still under the run lock, so no
        # later call in THIS process (e.g. a second run_once after an outside tamper) can ever
        # be served a stale cache. "The cache may serve reads only inside a run, under the run
        # lock" (N3) -- this is the other half of that sentence.
        ledger.invalidate_cache()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--now", default=None)
    parser.add_argument("--live-rpc", action="store_true")
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir) if args.data_dir else _default_data_dir()
    now = contract.parse_ts(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        print(f"unparseable --now {args.now!r}", file=sys.stderr)
        return 2

    rpc_client = None
    if args.live_rpc:
        # H0: this must be an instance, never the bare MODULE — onchain.py calls
        # rpc_client.pin_block()/.quorum()/.request()/.endpoints, none of which exist on the
        # module object itself (`capital_shadow.rpc` has no top-level `pin_block`). Passing the
        # module silently turned every call into an AttributeError, which run_once's per-scanner
        # try/except then swallowed as a (wrongly) UNAVAILABLE scanner — every single day, for
        # every scanner that touches the chain.
        from spa_core.capital_shadow.rpc import RpcClient
        rpc_client = RpcClient(1)  # chain_id 1 = Ethereum mainnet (the only chain onchain.py reads)

    http_client_ = None
    if args.live_rpc:
        # same opt-in as rpc_client above: a real, allow-listed network client for the
        # collectors' evidence refresh (ADR-564 §8) — never constructed by default.
        from spa_core.research_factory.http_client import Client as HttpClient
        http_client_ = HttpClient(now=now)

    try:
        status = run_once(data_dir, now, rpc_client=rpc_client, http_client_=http_client_)
    except RunLocked as exc:
        print(str(exc), file=sys.stderr)
        return contract.EXIT_LOCKED
    except LedgerError as exc:
        print(str(exc), file=sys.stderr)
        return contract.EXIT_BROKEN

    # H0: exit 0 ONLY when the ledger's own integrity is OK — a scanner crash never blocks a
    # clean exit (it is recorded, not fatal), but a BROKEN ledger must never report success even
    # if run_once somehow returned a status dict for it.
    if status.get("integrity") != "OK":
        print(f"research_factory run: integrity={status.get('integrity')!r}, refusing a clean exit",
             file=sys.stderr)
        return contract.EXIT_BROKEN

    print(f"research_factory run ok: {status['denominators']}")
    return contract.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
