"""Research evidence + paper admission — the frozen contract of ADR-564 (RM-EVIDENCE-01), revised after the
independent architecture review (15 findings, all applied — see ADR-564 "Binding revision").

Extends ADR-560's Research Factory; ``contract.py`` stays in force and is AMENDED here only where stated
(CIO gates, review #13). Adds: the evidence bundle, the counterparty profile, per-dimension grades,
origin-based independence over an affiliation registry, holder eligibility, paper admission v2, Sherlock's
deterministic decision, paper accounting, the collector / curated-fact / replay interfaces, and the HTTP
allow-list.

Sherlock (``head_of_research``) is a role identity over DETERMINISTIC research governance: no LLM decides a
gate or a number; the role has NO capital authority. PAPER_ACTIVE = "evaluated forward with simulated
capital", never live authorization, never CIO eligibility. LLM_FORBIDDEN, stdlib only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import hashlib
import json
import re
from typing import Optional

from spa_core.research_factory import contract as c1

EVIDENCE_CONTRACT_VERSION = "research-evidence-contract/1"
SCHEMA_BUNDLE = "candidate-evidence-bundle/1"
SCHEMA_PROFILE = "counterparty-profile/2"        # v2 role semantics (review #2) — distinct from ADR-560's
SCHEMA_DECISION = "research-admission-decision/1"
SCHEMA_ADMISSION_V2 = "paper-admission/2"
SCHEMA_PAPER = "paper-position/1"
SCHEMA_FACT = "curated-fact/1"
SCHEMA_OBS_ROW = "evidence-observation/1"
POLICY_VERSION = "sherlock-admission-v1"

ROLE_ID = "head_of_research"
ROLE_DISPLAY_NAME = "Sherlock"        # = architecture/roles.json (tested); display metadata only
AUTHORITY_OVER_CAPITAL = "NONE"

# ── origins, channels, affiliation (WP-A04, review #3/#11) ──────────────────────────────────────
#: an ORIGIN is the party whose report a claim ultimately is; a CHANNEL is how it reached us.
ORIGIN_RE = re.compile(r"^(issuer|venue|regulator|auditor|administrator|custodian|agent|chain|aggregator|model|"
                       r"engine):[a-z0-9_\-\.]+$")
CHANNEL_ON_CHAIN = "on_chain"
CHANNEL_OFFICIAL_API = "official_api"
CHANNEL_OFFICIAL_DOC = "official_doc"
CHANNEL_REGULATORY_FILING = "regulatory_filing"
CHANNEL_AGGREGATOR = "aggregator"
CHANNEL_MODEL = "model"
CHANNELS = (CHANNEL_ON_CHAIN, CHANNEL_OFFICIAL_API, CHANNEL_OFFICIAL_DOC, CHANNEL_REGULATORY_FILING,
            CHANNEL_AGGREGATOR, CHANNEL_MODEL)
#: ``chain:`` may be an ORIGIN only for chain-native facts; a value an issuer POSTS on-chain has the issuer as
#: origin and on_chain as channel (review #11)
CHAIN_NATIVE_CLAIMS = ("bytecode", "token_identity", "supply", "balance", "event", "protocol_state")
#: tail of ADR-564 (card inbox-hvost-adr-564): `protocol_state` = a value the contract COMPUTES from its own
#: state (a lending index, a savings-rate accumulator) — chain-native, unlike a value a party POSTS to an oracle.
#: It counts as an independent RETURN witness ONLY for these mechanisms, whose return the contract computes:
CONTRACT_COMPUTED_RETURN_MECHANISMS = ("LENDING", "LOOPED_LENDING", "STABLECOIN_SAVINGS")
#: the chain-native claims that can make a given ROLE "OBSERVED" — a citation must bind the role it is offered
#: for (a bytecode read proves a contract exists, not who holds the assets). Roles absent here cannot be
#: observed on-chain at all (OBSERVED for them needs the counterparty's own API).
ROLE_OBSERVABLE_CLAIMS = {
    "issuer": ("token_identity", "bytecode", "supply"),
    "custodian": ("balance",),
    "borrower": ("balance", "event"),
    "redemption_agent": ("event",),
    "oracle_provider": ("bytecode", "event"),
    "bridge": ("bytecode", "event", "balance"),
}
#: second re-review (M4 residual): the API route to OBSERVED is the counterparty's OWN API — its origin must be
#: of that role's TYPE. Roles absent here (issuer, legal_entity, borrower, oracle_provider) have no own-API route.
ROLE_API_ORIGIN_PREFIXES = {
    "exchange": ("venue:",),
    "market_maker": ("venue:", "agent:"),
    "custodian": ("custodian:",),
    "redemption_agent": ("agent:",),
    "bridge": ("agent:",),
}
#: second re-review (M4a): the claim an on-chain ref ACTUALLY reads, from its method segment
#: (`chain:<id>:<address>:<method>` / `eth_call:<id>:<address>:<m1()/m2()>[:block:<n>]`). A declared claim_type
#: that disagrees with the method read is refused; an unrecognised method cannot back an OBSERVED role.
METHOD_CLAIMS = {
    "balanceof": "balance", "balance": "balance",
    "getcode": "bytecode", "bytecode": "bytecode",
    "totalsupply": "supply", "supply": "supply",
    "name": "token_identity", "symbol": "token_identity", "decimals": "token_identity",
    "token_identity": "token_identity",
    "event": "event", "getlogs": "event", "logs": "event",
    "protocol_state": "protocol_state",
}


def ref_claim_type(ref: Optional[str]) -> Optional[str]:
    """The single claim an on-chain ref reads, or None (not a recognised on-chain ref, or methods of
    different claims mixed in one ref)."""
    if not ref or not ref.startswith(("chain:", "eth_call:")):
        return None
    parts = ref.split(":")
    if len(parts) < 4:
        return None
    methods = [m.strip().lower().replace("()", "") for m in parts[3].split("/") if m.strip()]
    claims = {METHOD_CLAIMS.get(m) for m in methods}
    return claims.pop() if len(claims) == 1 and None not in claims else None
#: git-tracked origin registry: canonical id → {"group": affiliation group, "affiliated_with": [...],
#: "appointed_by": origin|None, "note"}; independence is computed over GROUPS (e.g. issuer:hashnote and
#: issuer:circle share group circle; an administrator appointed by the issuer is NOT independent of it)
ORIGIN_REGISTRY_PATH = "spa_core/research_factory/registry/origins.json"
#: the curated fact registry (git-tracked JSONL) — the ONLY door for official_doc / regulatory_filing facts
FACT_REGISTRY_PATH = "spa_core/research_factory/registry/facts.jsonl"
QUOTE_MAX_CHARS = 200                  # the fact sentence only; never page text (copyright) — review #15
QUOTE_REQUIRED_CHANNELS = (CHANNEL_OFFICIAL_DOC, CHANNEL_REGULATORY_FILING)


def citation(*, origin: str, channel: str, ref: str, retrieved_at: str, quote: Optional[str] = None,
             block: Optional[int] = None, claim_type: Optional[str] = None) -> dict:
    """One provenance pointer. ``ref`` = URL or ``chain:<id>:<address>:<method>``. A document/filing citation
    must carry a short ``quote`` (≤ QUOTE_MAX_CHARS) holding the fact itself."""
    if not ORIGIN_RE.match(origin or ""):
        raise ValueError(f"origin must name the producing party, got {origin!r}")
    if channel not in CHANNELS:
        raise ValueError(f"unknown channel {channel!r}")
    if not ref or c1.parse_ts(retrieved_at) is None:
        raise ValueError("a citation needs a ref and an ISO-8601 retrieved_at")
    if channel in QUOTE_REQUIRED_CHANNELS and not quote:
        raise ValueError(f"a {channel} citation must carry the quoted fact")
    if quote is not None and len(quote) > QUOTE_MAX_CHARS:
        raise ValueError(f"quote longer than {QUOTE_MAX_CHARS} chars — store the fact sentence only")
    if origin.startswith("chain:") and claim_type not in CHAIN_NATIVE_CLAIMS:
        raise ValueError("chain: is an origin only for chain-native facts; an issuer-posted value has the issuer "
                         "as origin and on_chain as channel")
    if channel == CHANNEL_AGGREGATOR and not origin.startswith(("issuer:", "venue:", "administrator:", "aggregator:")):
        raise ValueError("an aggregator citation must name the origin it relays")
    return {"origin": origin, "channel": channel, "ref": ref, "retrieved_at": retrieved_at, "quote": quote,
            "block": block, "claim_type": claim_type}


def origin_group(origin: Optional[str], registry: dict, claim_type: Optional[str] = None) -> Optional[str]:
    """The affiliation group of one origin, or None when it cannot count as a source at all (post-implementation
    review H5/H6): aggregator/model/missing origins are never independent; an UNREGISTERED origin fails closed
    (None, never a group of its own — two names for one party must not count twice); an origin APPOINTED BY
    another party (an issuer's administrator / custodian) belongs to the appointer's group."""
    if not origin or origin.startswith(("aggregator:", "model:")):
        return None
    # re-review H5 residual (2026-10-04): a chain is a witness only to what it natively records
    # (CHAIN_NATIVE_CLAIMS — the same rule citation() enforces); a NAV/rate read off an issuer's
    # oracle is the issuer's claim, so `chain:` counts as no group for anything else
    if origin.startswith("chain:") and claim_type not in CHAIN_NATIVE_CLAIMS:
        return None
    entry = registry.get(origin) if isinstance(registry, dict) else None
    if not isinstance(entry, dict) or not entry.get("group"):
        return None
    appointer = entry.get("appointed_by")
    if appointer:
        a = registry.get(appointer) if isinstance(registry, dict) else None
        if isinstance(a, dict) and a.get("group"):
            return a["group"]
    return entry["group"]


def return_claim_type(origin: Optional[str], mechanism_id: Optional[str]) -> Optional[str]:
    """The claim type a RETURN reading carries for independence counting: `protocol_state` when it is read
    off a chain for a mechanism whose return the contract itself computes (CONTRACT_COMPUTED_RETURN_MECHANISMS),
    otherwise None — so a `chain:` read of a POSTED value (an oracle NAV) still counts as no group."""
    if origin and origin.startswith("chain:") and mechanism_id in CONTRACT_COMPUTED_RETURN_MECHANISMS:
        return "protocol_state"
    return None


def origin_groups(citations: list, registry: dict) -> list:
    """Distinct affiliation GROUPS among the citations' origins (see ``origin_group``: aggregator/model/missing/
    unregistered origins add nothing; appointed parties count as their appointer)."""
    out = []
    for ct in citations or []:
        o = ct.get("origin") if isinstance(ct, dict) else None
        g = origin_group(o, registry, ct.get("claim_type") if isinstance(ct, dict) else None)
        if g is not None and g not in out:
            out.append(g)
    return out


#: claims needing ≥ N independent GROUPS (review #11/#13)
HIGH_IMPACT_CLAIMS = ("return", "reserves", "redemption", "custody")
MIN_GROUPS_PAPER = {"return": 1, "reserves": 0, "redemption": 1, "custody": 1}
MIN_GROUPS_CIO = {"return": 2, "reserves": 2, "redemption": 1, "custody": 2}

# ── counterparty profile v2 (WP-A02, review #2/#3/#4) ───────────────────────────────────────────
CP_IDENTIFIED = "IDENTIFIED"     # named only by the issuer/venue (or its affiliates) — issuer-asserted
CP_DOCUMENTED = "DOCUMENTED"     # named by an independent party's document (regulator/auditor/administrator not
                                 # appointed-and-affiliated, or the named counterparty itself), quote required
CP_OBSERVED = "OBSERVED"         # machine-observed and NOT authored by the claimant (on-chain binding, or the
                                 # counterparty's own API) — an issuer's own API caps at IDENTIFIED
CP_UNKNOWN = "UNKNOWN"           # never safe; an INFERRED link is UNKNOWN with a reason
CP_NOT_APPLICABLE = "NOT_APPLICABLE"   # only where MECHANISMS[m].required_roles omits the role
CP_ROLE_STATES = (CP_IDENTIFIED, CP_DOCUMENTED, CP_OBSERVED, CP_UNKNOWN, CP_NOT_APPLICABLE)
CP_STRENGTH = {CP_UNKNOWN: 0, CP_IDENTIFIED: 1, CP_DOCUMENTED: 2, CP_OBSERVED: 3}
ROLES = c1.COUNTERPARTY_ROLES
ROLE_ATTRIBUTES = ("identity", "role", "jurisdiction", "custody_relationship", "redemption_dependency",
                   "reserve_audit_evidence", "concentration", "restrictions", "historical_incidents")
#: a filing whose filer is the issuer may lift ONLY these roles to DOCUMENTED (review #3)
ISSUER_FILING_LIFTS = ("legal_entity", "issuer")
#: evidence ceiling over required roles (review #4) — printed in every bundle/decision/position/UI row
CEILING_ISSUER_ASSERTED = "ISSUER_ASSERTED"
CEILING_THIRD_PARTY_DOCUMENTED = "THIRD_PARTY_DOCUMENTED"
CEILING_OBSERVED = "OBSERVED"
EVIDENCE_CEILINGS = (CEILING_ISSUER_ASSERTED, CEILING_THIRD_PARTY_DOCUMENTED, CEILING_OBSERVED)
ISSUER_ASSERTED_LABEL = "issuer-asserted, not verified"


def role_entry(state: str, *, identity: Optional[str] = None, citations: Optional[list] = None,
               attributes: Optional[dict] = None, unknowns: Optional[list] = None, role: Optional[str] = None,
               issuer_group: Optional[str] = None, registry: Optional[dict] = None,
               reason: Optional[str] = None) -> dict:
    """A v2 role entry. Validation enforces the state's evidence bar (review #3)."""
    if state not in CP_ROLE_STATES:
        raise ValueError(f"unknown role state {state!r}")
    cits = list(citations or [])
    if state in (CP_IDENTIFIED, CP_DOCUMENTED, CP_OBSERVED) and (not identity or not cits):
        raise ValueError(f"{state} role needs an identity and at least one citation")
    if state == CP_UNKNOWN and not reason:
        raise ValueError("an UNKNOWN role must name its reason (an inferred link is UNKNOWN, not DOCUMENTED)")
    reg = registry or {}

    def _group(o):
        return origin_group(o, reg)

    if state == CP_DOCUMENTED:
        ok = False
        for ct in cits:
            o, ch = str(ct.get("origin", "")), ct.get("channel")
            if ch not in QUOTE_REQUIRED_CHANNELS or not ct.get("quote") or identity.lower() not in ct["quote"].lower():
                continue
            # independent only if the origin is REGISTERED, not appointed by/affiliated with the issuer (review H6)
            g = _group(o)
            independent = (o.startswith(("regulator:", "auditor:", "administrator:", "custodian:", "agent:"))
                           and g is not None and g != issuer_group)
            issuer_filing = (ch == CHANNEL_REGULATORY_FILING and role in ISSUER_FILING_LIFTS)
            if independent or issuer_filing:
                ok = True
        if not ok:
            raise ValueError("DOCUMENTED needs an independent document (or, for legal_entity/issuer only, a "
                             "regulatory filing) whose quote names the identity; issuer-only ⇒ IDENTIFIED")
    if state == CP_OBSERVED:
        ok = False
        for ct in cits:
            o, ch = str(ct.get("origin", "")), ct.get("channel")
            # tail of ADR-564 (re-review M4): an on-chain binding counts only when the CHAIN is the origin (an
            # issuer posting a value on-chain is the issuer speaking) and the claim fits the role; the
            # counterparty's own API counts only from a REGISTERED origin, against a KNOWN issuer group it
            # differs from — an unregistered name, or no issuer group to compare with, fails closed.
            if ch == CHANNEL_ON_CHAIN and o.startswith("chain:") \
                    and ct.get("claim_type") in ROLE_OBSERVABLE_CLAIMS.get(role or "", ()) \
                    and ref_claim_type(ct.get("ref")) == ct.get("claim_type"):
                ok = True
            g = _group(o)
            if ch == CHANNEL_OFFICIAL_API and g is not None and issuer_group is not None and g != issuer_group \
                    and o.startswith(ROLE_API_ORIGIN_PREFIXES.get(role or "", ())):
                ok = True
        if not ok:
            raise ValueError("OBSERVED needs an on-chain binding OF THIS ROLE (ROLE_OBSERVABLE_CLAIMS) or the "
                             "counterparty's own API (an issuer API caps at IDENTIFIED)")
    attrs = dict(attributes or {})
    bad = set(attrs) - set(ROLE_ATTRIBUTES)
    if bad:
        raise ValueError(f"unknown role attributes {sorted(bad)}")
    return {"profile_schema": SCHEMA_PROFILE, "state": state, "identity": identity, "citations": cits,
            "attributes": attrs, "unknowns": list(unknowns or []), "reason": reason}


def migrate_v1_role(v1_state: str, has_non_issuer_citation: bool) -> str:
    """ADR-560 v1 states → v2 (review #2): v1 DOCUMENTED becomes IDENTIFIED unless a non-issuer citation exists;
    v1 OBSERVED is re-validated by role_entry (caller); UNKNOWN/NOT_APPLICABLE unchanged."""
    if v1_state == c1.CP_DOCUMENTED:
        return CP_DOCUMENTED if has_non_issuer_citation else CP_IDENTIFIED
    return {c1.CP_OBSERVED: CP_OBSERVED, c1.CP_UNKNOWN: CP_UNKNOWN, c1.CP_NOT_APPLICABLE: CP_NOT_APPLICABLE}.get(
        v1_state, CP_UNKNOWN)


# ── holder eligibility + paper mode (review #5) ─────────────────────────────────────────────────
SPA_ELIGIBLE = "SPA_ELIGIBLE"
NOT_ELIGIBLE = "NOT_ELIGIBLE"
ELIGIBILITY_UNKNOWN = "UNKNOWN"
HOLDER_ELIGIBILITY_STATES = (SPA_ELIGIBLE, NOT_ELIGIBLE, ELIGIBILITY_UNKNOWN)
ELIGIBILITY_REQUIREMENTS = ("kyc", "investor_class", "jurisdiction", "minimum_usd")
#: SPA has no legal entity, KYC or investor classification on record ⇒ any KYC/investor-class/minimum-above-
#: notional requirement makes SPA NOT_ELIGIBLE or UNKNOWN — never assumed eligible
PAPER_MODE_HOLDABLE = "HOLDABLE"             # SPA could hold and exit the instrument as modelled
PAPER_MODE_REFERENCE_TRACK = "REFERENCE_TRACK"   # tracks the instrument's NAV; not a position SPA could hold
PAPER_MODES = (PAPER_MODE_HOLDABLE, PAPER_MODE_REFERENCE_TRACK)
SECONDARY_EXIT_NONE_MEASURED = "NONE (measured)"   # measured zero secondary depth — never folded into adequate

# ── evidence grades (WP-A03, review #7/#12) ─────────────────────────────────────────────────────
STRONG, ADEQUATE, WEAK, UNKNOWN, CONFLICTED, STALE = "STRONG", "ADEQUATE", "WEAK", "UNKNOWN", "CONFLICTED", "STALE"
NOT_APPLICABLE = "NOT_APPLICABLE"
GRADES = (STRONG, ADEQUATE, WEAK, UNKNOWN, CONFLICTED, STALE, NOT_APPLICABLE)
GRADE_ORDER = {UNKNOWN: 0, STALE: 0, CONFLICTED: 0, WEAK: 1, ADEQUATE: 2, STRONG: 3}
DIMENSIONS = ("PRIMARY_IDENTITY", "RETURN", "COST", "LIQUIDITY", "COUNTERPARTY", "REDEMPTION", "CUSTODY",
              "CONTRACT", "FORWARD_SERIES", "RESERVES", "LEGAL", "HOLDER_ELIGIBILITY")
#: PAPER minimum per dimension (None = shown, not gated for paper). No average exists anywhere.
PAPER_MIN_GRADE = {"PRIMARY_IDENTITY": ADEQUATE, "RETURN": ADEQUATE, "COST": ADEQUATE, "LIQUIDITY": ADEQUATE,
                   "COUNTERPARTY": ADEQUATE, "REDEMPTION": ADEQUATE, "CUSTODY": ADEQUATE, "CONTRACT": ADEQUATE,
                   "FORWARD_SERIES": ADEQUATE, "RESERVES": None, "LEGAL": None, "HOLDER_ELIGIBILITY": None}
#: CIO minimum (review #12/#13) — enforced by the amended ADR-560 eligibility gates
CIO_MIN_GRADE = {"RETURN": STRONG, "COUNTERPARTY": STRONG, "CUSTODY": STRONG, "RESERVES": ADEQUATE,
                 "LEGAL": ADEQUATE, "HOLDER_ELIGIBILITY": ADEQUATE}
#: dimension → mechanisms where it is NOT_APPLICABLE (listed by name — review #7)
DIMENSION_NA = {
    "REDEMPTION": ("FUNDING_CAPTURE", "SPOT_PERP_BASIS"),
    "RESERVES": ("FUNDING_CAPTURE", "SPOT_PERP_BASIS", "LENDING", "STABLE_LP", "DIRECTIONAL_TREND"),
    "CONTRACT": ("DIRECTIONAL_TREND",),
}
GRADING_RULES = {
    "PRIMARY_IDENTITY": "STRONG = on-chain name/symbol/decimals at a block AND a matching cited official address; "
                        "ADEQUATE = on-chain verified; WEAK = cited only; perp: venue contract spec from the venue API",
    "RETURN": "ADEQUATE = MEASURED observed return via a PRIMARY channel with a TRUE upstream timestamp that ADVANCED "
              "(see frozen-value rule); STRONG = ≥2 independent groups agree within the family tolerance; "
              "WEAK = aggregator only; CONFLICTED = independent groups disagree; STALE = upstream older than the "
              "calendar-aware limit",
    "COST": "ADEQUATE = every applicable cost component (entry, exit, management, performance, spread, gas, funding "
            "fees) MEASURED or DOCUMENTED from the origin's official terms with effective_from and fresh; any "
            "undisclosed component (e.g. a mint/redeem spread) ⇒ NOT_MEASURED ⇒ COST WEAK (blocks)",
    "LIQUIDITY": "ADEQUATE = an exit path SPA is ELIGIBLE for is measured (book depth) or documented with settlement "
                 "time, minimum, gates/suspension/caps; a path SPA is not eligible for never grades ADEQUATE "
                 "(the candidate can then only be admitted as REFERENCE_TRACK, whose LIQUIDITY is NOT_APPLICABLE "
                 "for paper and blocks CIO)",
    "COUNTERPARTY": "ADEQUATE = every required role ≥ IDENTIFIED with citations; STRONG = every required role ≥ "
                    "DOCUMENTED; UNKNOWN = any required role UNKNOWN",
    "REDEMPTION": "ADEQUATE = redemption agent ≥ IDENTIFIED and terms cited incl. gates/suspension/caps; a missing "
                  "caveat field ⇒ WEAK",
    "CUSTODY": "ADEQUATE = custodian ≥ IDENTIFIED; STRONG = DOCUMENTED",
    "CONTRACT": "ADEQUATE = the NAV/yield mechanism is readable on a declared reader with verified decimals/units",
    "FORWARD_SERIES": "ADEQUATE = a collector exists on a PRIMARY channel, the last value is fresh by the calendar "
                      "rule and the value is not frozen",
    "RESERVES": "ADEQUATE = an attestation/audit with date and origin; STRONG = independent auditor group; else UNKNOWN",
    "LEGAL": "ADEQUATE = entity + jurisdiction + exemption ≥ DOCUMENTED; else UNKNOWN",
    "HOLDER_ELIGIBILITY": "ADEQUATE = SPA_ELIGIBLE documented; WEAK = requirements known, SPA NOT_ELIGIBLE; "
                          "UNKNOWN = requirements unknown",
}

# ── frozen-value / calendar freshness (review #6/#10) — the ONE freshness table ─────────────────
#: family → (max age, calendar). "business_days": NAVs may stay flat over weekends/holidays; a value unchanged
#: for more than N business days is STALE. Funding uses settlement counts (below).
FRESHNESS = {
    "nav_business_day": {"max_unchanged_business_days": 3, "max_age_h": 96.0},
    "rate": {"max_age_h": 36.0},
    "funding_settlement": {"max_age_h": 12.0},
    "book_snapshot": {"max_age_h": 2.0},
    "documented_terms": {"max_age_h": 24.0 * 30},
    "curated_fact": {"max_age_h": 24.0 * 30},
    "counterparty": {"max_age_h": 24.0 * 30},
}
#: an oracle WITHOUT its own timestamp: as_of = the time of the LAST VALUE CHANGE (recorded diff or update event),
#: never the read block; an unchanged value is not "advanced". latestRoundData uses updatedAt only.

# ── paper admission v2 (WP-A05, review #1/#7) — superset of ADR-560 v1 ───────────────────────────
ADMISSION_V2_GATES = (
    "identity_verified", "mechanism_understood", "return_source_verified", "net_return_computable",
    "source_independence_sufficient", "data_fresh", "counterparty_roles_sufficient", "redemption_understood",
    "custody_understood", "fees_measured", "liquidity_measured", "exit_path_defined",
    "contract_identity_verified_or_not_applicable", "paper_accounting_feasible", "forward_collection_ready",
    "duplicate_exposure_clear", "no_conflicted_critical_inputs",
    # kept from v1 (review #7)
    "leverage_known", "not_advertised_only", "holder_eligibility_recorded",
)
PASS, FAIL, GATE_UNKNOWN, GATE_NA_VERDICT = "PASS", "FAIL", "UNKNOWN", "NOT_APPLICABLE"
GATE_VERDICTS = (PASS, FAIL, GATE_UNKNOWN, GATE_NA_VERDICT)
#: gate → (dimensions/fields it reads) — implementers may not read anything else (review #7)
GATE_INPUTS = {
    "identity_verified": ("PRIMARY_IDENTITY",),
    "mechanism_understood": ("mechanism_id",),
    "return_source_verified": ("RETURN",),
    "net_return_computable": ("COST", "RETURN", "net_expected_return"),
    "source_independence_sufficient": ("RETURN", "COUNTERPARTY", "MIN_GROUPS_PAPER"),
    "data_fresh": ("RETURN", "FORWARD_SERIES"),
    "counterparty_roles_sufficient": ("COUNTERPARTY",),
    "redemption_understood": ("REDEMPTION",),
    "custody_understood": ("CUSTODY",),
    "fees_measured": ("COST",),
    "liquidity_measured": ("LIQUIDITY", "paper_mode"),
    "exit_path_defined": ("LIQUIDITY", "REDEMPTION", "paper_mode"),
    "contract_identity_verified_or_not_applicable": ("CONTRACT", "PRIMARY_IDENTITY"),
    "paper_accounting_feasible": ("CONTRACT", "COST", "paper_mode"),
    "forward_collection_ready": ("FORWARD_SERIES",),
    "duplicate_exposure_clear": ("exposure_family", "underlying_root", "existing_book_roots"),
    "no_conflicted_critical_inputs": ("RETURN", "COST", "COUNTERPARTY", "PRIMARY_IDENTITY"),
    "leverage_known": ("leverage", "liquidation_distance"),
    "not_advertised_only": ("RETURN",),
    "holder_eligibility_recorded": ("HOLDER_ELIGIBILITY", "paper_mode"),
}
#: gate → mechanisms for which it is NOT_APPLICABLE (by name); everything else must PASS
#: paper-mode rule (binding #5), frozen here (review LOW): under REFERENCE_TRACK these gates are NOT_APPLICABLE
#: — a NAV tracker makes no exit-liquidity claim; it is barred from CIO by the not_reference_track gate
GATE_NA_REFERENCE_TRACK = ("liquidity_measured", "exit_path_defined")
GATE_NA = {
    "redemption_understood": ("FUNDING_CAPTURE", "SPOT_PERP_BASIS"),
    "contract_identity_verified_or_not_applicable": ("DIRECTIONAL_TREND",),
    "leverage_known": tuple(m for m, v in c1.MECHANISMS.items() if not v.get("leverage_required")),
}

# ── Sherlock decision (WP-A06, review #7/#15) ───────────────────────────────────────────────────
ADMIT_TO_PAPER = "ADMIT_TO_PAPER"
HOLD = "HOLD"
REJECT = "REJECT"
DECISION_STALE = "STALE"
NEEDS_MORE_EVIDENCE = "NEEDS_MORE_EVIDENCE"
DECISIONS = (ADMIT_TO_PAPER, HOLD, REJECT, DECISION_STALE, NEEDS_MORE_EVIDENCE)
#: precedence — the FIRST matching rule wins (a function, not a list of overlapping wishes)
DECISION_PRECEDENCE = (REJECT, HOLD, DECISION_STALE, NEEDS_MORE_EVIDENCE, ADMIT_TO_PAPER)
DECISION_PREDICATES = {
    REJECT: "mechanism not in contract.MECHANISMS, OR on-chain identity contradicts the claimed instrument, OR "
            "net_expected_return is MEASURED/ESTIMATED and ≤ 0",
    HOLD: "any critical input (RETURN, COST, COUNTERPARTY, PRIMARY_IDENTITY) is CONFLICTED",
    DECISION_STALE: "any gated dimension is STALE AND a prior bundle for this candidate had it ≥ ADEQUATE",
    NEEDS_MORE_EVIDENCE: "any gate FAIL or UNKNOWN not covered above",
    ADMIT_TO_PAPER: "every ADMISSION_V2_GATES gate PASS (or NOT_APPLICABLE where GATE_NA lists the mechanism)",
}
DECISION_FIELDS = ("schema_version", "decision_id", "candidate_id", "generated_at", "evidence_cutoff", "decision",
                   "failed_gates", "unknowns", "conflicts", "rationale", "evidence_refs", "required_next_evidence",
                   "policy_version", "source_snapshot_digest", "bundle_digest", "code_identity", "now",
                   "input_digests", "paper_mode", "evidence_ceiling", "issuer_asserted_roles",
                   "circularity_concerns", "decided_by_role", "authority_over_capital")
#: the admission snapshot v2 — the ONLY row lifecycle accepts as gate_ref into PAPER_ACTIVE (review #1)
ADMISSION_V2_FIELDS = ("schema", "admission_id", "candidate_id", "decision_id", "bundle_digest", "policy_version",
                       "paper_mode", "evidence_ceiling", "as_of", "recorded_at", "code_identity")

# ── evidence bundle (WP-A01, review #4) ─────────────────────────────────────────────────────────
EVIDENCE_SECTIONS = ("identity_evidence", "return_evidence", "cost_evidence", "liquidity_evidence",
                     "counterparty_evidence", "redemption_evidence", "custody_evidence", "contract_evidence",
                     "market_evidence", "paper_accounting_evidence", "forward_series_evidence",
                     "reserves_evidence", "legal_evidence", "holder_eligibility_evidence")
BUNDLE_FIELDS = (("schema_version", "candidate_id", "exposure_key", "exposure_family", "mechanism_id",
                  "generated_at", "evidence_cutoff") + EVIDENCE_SECTIONS +
                 ("source_roots", "origin_groups", "independent_root_count", "conflicts", "stale_evidence",
                  "unknowns", "blocking_gaps", "grades", "paper_mode", "evidence_ceiling", "issuer_asserted_roles",
                  "circularity_concerns", "evidence_digest"))

# ── funding (review #8) ─────────────────────────────────────────────────────────────────────────
#: settlement rows keyed (venue, symbol, settlement_ts_ms, interval_h); predicted/current funding is never a
#: settlement; a day counts only with the venue's expected settlement count; partial days are flagged.
FUNDING_ROW_KEY = ("venue", "symbol", "settlement_ts_ms", "interval_h")
EXPECTED_SETTLEMENTS_PER_DAY = {"binance": 3, "bybit": 3, "okx": 3, "kucoin": 3, "hyperliquid": 24}
FUNDING_NORMALISE = "rate_per_8h = rate × 8 / interval_h"
#: conflicts only BETWEEN CHANNELS FOR THE SAME VENUE (absolute band); a cross-venue spread is information
FUNDING_SAME_VENUE_BAND_BPS_8H = 0.5
FUNDING_AGGREGATE_MIN_VENUES = 3
#: a funding candidate is a (perp venue × spot venue) PAIR; all pairs of one asset form ONE exposure_family —
#: dedup at family level; every member reported; admission order is by evidence completeness (recorded),
#: never by trailing APY
FUNDING_PAIR_ID = "perp:{asset}:{perp_venue}+spot:{spot_venue}"

# ── paper accounting (WP-S07/S08, review #9) ────────────────────────────────────────────────────
PAPER_NOTIONAL_USD = 10_000.0          # simulated capital per admitted candidate; never real
PAPER_KINDS = ("paper_open", "paper_mark", "paper_cashflow", "paper_unit_change", "paper_close")
PAPER_FIELDS = ("position_id", "candidate_id", "decision_id", "admission_id", "paper_mode", "leg_id", "opened_at",
                "initial_notional_usd", "units", "entry_price", "entry_value_usd", "entry_fees_usd", "cash_usd",
                "position_value_usd", "nav_usd", "realised_return", "unrealised_return", "exit_value_usd",
                "exit_fees_usd", "redemption_delay_haircut_usd", "slippage_usd", "funding_usd", "margin_usd",
                "liquidation_distance", "collateral_yield_usd", "performance_fee_accrual_usd", "price_source",
                "mark_origin", "mark_circular", "fee_source", "holding_period_days_declared")
#: mark rows: a stale mark is a paper_mark in state STALE with NO price — never a forward-filled fresh price.
#: funding cashflows land at each settlement timestamp on notional at that settlement's mark.
#: one-off entry/exit bps are stored as one-off values and amortised only by the DECLARED holding period.

# ── interfaces (review #14/#15) ─────────────────────────────────────────────────────────────────
#: collector:  collect(now, client) -> list[observation_row]; rows are SCHEMA_OBS_ROW with fields below,
#: append-only; history fetched at first collection is forced backfill=True; a changed value for the same
#: key is a `revises` row
OBS_ROW_FIELDS = ("schema", "candidate_id", "claim", "value", "unit", "window", "upstream_ts", "fetched_at",
                  "origin", "channel", "ref", "raw_sha256", "backfill", "revises", "state", "reason")
#: curated fact (git-tracked JSONL, the only door for doc/filing facts; reviewed by a different session)
FACT_FIELDS = ("schema", "fact_id", "entity", "candidate_ids", "role", "claim_type", "value", "origin", "channel",
               "ref", "quote", "retrieved_at", "effective_from", "page_sha256", "fact_sha256", "curated_by",
               "reviewed_by", "supersedes", "expires_at", "subject_to_change")
#: replay: replay(decision_id) must reproduce the decision byte-identically from the stored bundle (content
#: addressed), code_identity, policy_version, now and input digests

#: one HTTP client (research_factory/http_client.py): every collector imports ONLY it (AST-tested)
HTTP_ALLOW = (
    # (host, method, path prefix, body type)
    ("fapi.binance.com", "GET", "/fapi/v1/", None),
    ("api.binance.com", "GET", "/api/v3/", None),
    ("api.bybit.com", "GET", "/v5/market/", None),
    ("www.okx.com", "GET", "/api/v5/", None),
    ("api-futures.kucoin.com", "GET", "/api/v1/", None),
    ("api.kucoin.com", "GET", "/api/v1/", None),
    ("api.hyperliquid.xyz", "POST", "/info", "hyperliquid_info"),
    ("usyc.hashnote.com", "GET", "/api/", None),
    ("yields.llama.fi", "GET", "/", None),          # aggregator channel ONLY (grade WEAK at best)
)
HYPERLIQUID_INFO_TYPES = ("metaAndAssetCtxs", "fundingHistory", "l2Book")
HTTP_SCHEMES = ("https",)
HTTP_PORTS = (443,)                     # tail of ADR-564: an explicit port must be one of these               # review H1: plain http to an allowed host is refused
HTTP_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
HTTP_TIMEOUT_S = 15

# ── ADR-560 amendment: CIO eligibility gates added by ADR-564 (review #13) ──────────────────────
CIO_GATES_ADDED = ("min_origins_cio", "counterparty_grade_strong_for_credit_like", "holder_eligibility_documented",
                   "not_reference_track")

# ── binding amendment (integration, 2026-10-04): the INTERNAL shape of paper_accounting_evidence ─────
#: E1 (bundle) and E2 (paper) had invented different shapes for this ADR-named section; this freezes E2's,
#: because paper accounting is its only consumer. Two-leg candidates use {"legs": {leg_id: <same shape>}}.
PAPER_ACCOUNTING_EVIDENCE_FIELDS = (
    "entry_price",                      # cell, VALUED states only
    "entry_fee_components",             # non-empty list of FEE_COMPONENT
    "exit_fee_components",              # non-empty iff paper_mode HOLDABLE
    "redemption_delay_days",            # cell, required iff HOLDABLE
    "price_is_net_of_performance_fee",  # cell (a CITED fact) or None
    "performance_fee_rate",             # cell or None
    "leverage", "maintenance_margin_rate", "collateral_yield_rate",   # cells or None
    "fee_source", "holding_period_days_declared", "return_origin_group",
)
FEE_COMPONENT_FIELDS = ("kind", "cell", "unit", "effective_from", "subject_to_change", "one_off")
FEE_COMPONENT_KINDS = ("entry", "exit", "management", "performance", "spread")
#: per-host response caps where the default is measured too small (live 2026-10-04: yields.llama.fi /pools =
#: 11.6 MB). Aggregator channel only.
HTTP_MAX_RESPONSE_BYTES_BY_HOST = {"yields.llama.fi": 32 * 1024 * 1024}

#: curated facts (review H6): a fact's ORIGIN must match the publisher of its ``ref`` — the origin registry lists
#: each origin's ``hosts``; an issuer-hosted page is the issuer's claim whatever party it names. A fact is
#: usable only when ``reviewed_by`` is set by a DIFFERENT session than ``curated_by``.
FACT_REQUIRES_INDEPENDENT_REVIEW = True

# ── re-review H6 (2026-10-04): a review is bound to the fact CONTENT it confirmed ────────────────────────
#: a reviewed_by string alone was a self-certification: editing value/quote kept the stamp. The fact's
#: fact_sha256 is the canonical hash of its content (every field except the two below); a fact is reviewed
#: only when (1) fact_sha256 equals that recomputed hash AND (2) a committed review record by `reviewed_by`
#: CONFIRMED exactly that fact_id at exactly that fact_sha256. Records: registry/fact_reviews/*.json.
FACT_HASH_EXCLUDED_FIELDS = ("fact_sha256", "reviewed_by")
#: optional fact fields (tail of ADR-564): absent ⇒ absent from the content hash, so adding one to the contract
#: never unbinds an existing review; present ⇒ hashed like any other field. `effective_until` = when the stated
#: claim itself ends (a fee waiver's end date) — the fact is unusable on/after it, distinct from `expires_at`
#: (when WE must re-verify it).
FACT_OPTIONAL_FIELDS = ("effective_until",)
#: the only identities whose review records the loader accepts. A new reviewer is a code change to this
#: contract (visible, tested), never a free string in a data file; curators may not appear here.
FACT_REVIEWERS = (
    "RM-EVIDENCE-01 independent fact review (Opus, separate session)",
    "RM-EVIDENCE-01 independent fact review round 2 (Opus, separate session)",
    "RM-EVIDENCE-01 independent fact review round 3 (Opus, separate session)",
    "RM-EVIDENCE-01 independent fact review round 4 (Opus, separate session)",
    "RM-EVIDENCE-01 independent fact review round 5 (Opus, separate session)",
)
SCHEMA_FACT_REVIEW = "fact-review/1"
FACT_REVIEW_FIELDS = ("schema", "reviewer", "reviewed_at", "facts")
FACT_REVIEW_ENTRY_FIELDS = ("fact_id", "fact_sha256", "verdict", "method", "evidence", "issue")
FACT_REVIEW_VERDICTS = ("CONFIRMED", "REJECTED", "UNVERIFIABLE")
#: a ref with no HTTP host is checkable only as a chain-native read: channel on_chain AND a CHAIN_NATIVE claim
CHAIN_NATIVE_REF_PREFIXES = ("eth_call:", "chain:")


def fact_content_sha256(row: dict) -> str:
    """Canonical content hash of a curated fact (sorted keys, compact separators, UTF-8), excluding
    FACT_HASH_EXCLUDED_FIELDS — so stamping a review never changes the hash, and any content edit does."""
    body = {k: v for k, v in row.items() if k not in FACT_HASH_EXCLUDED_FIELDS}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()
