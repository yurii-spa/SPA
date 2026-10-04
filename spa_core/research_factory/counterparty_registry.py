"""spa_core/research_factory/counterparty_registry.py — the counterparty model (ADR-560 WP-A05).

A curated, SOURCED table of who stands behind each instrument the Package-B scanners emit. Per
the contract (``contract.COUNTERPARTY_ROLES`` / ``COUNTERPARTY_DIMENSIONS``): every fact is
OBSERVED (measured on-chain/primary, THIS run) or DOCUMENTED (cites a real source — see the
source-class discipline below) or UNKNOWN — **never invented**, and there is no blended rating.
A role this repo simply does not document is UNKNOWN, named as such, not guessed at or left out.

Post-implementation review, H6:

(a) **Roles default to UNKNOWN, not NOT_APPLICABLE.** A role is NOT_APPLICABLE only when
    ``contract.MECHANISMS[mechanism_id]["required_roles"]`` says the mechanism does not even call
    for it (e.g. STABLECOIN_SAVINGS has no "exchange" role). Every function here therefore takes
    (or is given, by its caller) the candidate's ``mechanism_id`` and builds its floor from
    :func:`_empty`, which reads ``required_roles`` — it is never a blanket NOT_APPLICABLE.
(b) **Source-class discipline.** This repo holds no audit letter, attestation or regulator filing
    for ANY of these instruments — ``AUDITED_DOCUMENT`` is therefore never used here. A fact read
    from an in-repo ``.py`` module or its prose (venue lists, protocol-design descriptions, which
    symbol maps to which contract) is ``SECONDARY_SOURCE`` (repo-curated, once removed from
    primary). A fact that is literally the ISSUER'S OWN published term — the safety board's
    redemption delay/fee, Sky governance's GSM minimum-delay parameter — is ``ISSUER_CLAIM``
    (never ``MEASURED``; ``ISSUER_CLAIM`` is a valid class for ``DOCUMENTED``, contract.py forbids
    it only for ``MEASURED``).
(c) **``reserve_transparency`` is never upgraded by an on-chain NAV-per-share read.** NAV per
    share is a price fact, not a reserve-transparency fact (it says nothing about what backs the
    fund off-chain) — a clean on-chain read is recorded as its own thing
    (``observations[cid]["realised_index"]`` in the scanner, entirely separate from this module),
    never folded into this dimension. ``reserve_transparency`` here is DOCUMENTED only when this
    repo names a concrete reserve-composition fact, UNKNOWN otherwise — it is not inferred from a
    share-price read of any kind.
(d) **Never name one entity's facts as another's.** ``delta_neutral_carry_susde`` must not claim
    the funding feed's CEX venue list as Ethena's own hedging venues — nothing in this repo
    documents which exchanges Ethena itself hedges on, so that role stays UNKNOWN.

Each public function returns the full
``{"roles": {role: {state, name, source_ref, source_class}}, "dimensions": {dim: {state,
source_ref, source_class, as_of}}}`` shape the scanner interface's ``counterparty[candidate_id]``
expects — every role in ``contract.COUNTERPARTY_ROLES`` and every dimension in
``contract.COUNTERPARTY_DIMENSIONS`` is present on every return; the function never silently
drops a key.

LLM_FORBIDDEN, stdlib only, no network, no file I/O — every fact here is a hand-curated literal
with its own ``source_ref`` naming the in-repo module/file it was read from.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from typing import Optional

from spa_core.research_factory import contract


def _empty(mechanism_id: str) -> dict:
    """The honest floor every candidate starts from: a role is NOT_APPLICABLE only if
    ``mechanism_id``'s own ``required_roles`` says so (review H6a) — every OTHER role, and every
    dimension, is UNKNOWN until a specific fact below says otherwise."""
    required = contract.MECHANISMS[mechanism_id]["required_roles"]
    return {
        "roles": {r: {"state": (contract.CP_UNKNOWN if r in required else contract.CP_NOT_APPLICABLE),
                     "name": None, "source_ref": None, "source_class": None}
                 for r in contract.COUNTERPARTY_ROLES},
        "dimensions": {d: {"state": contract.CP_UNKNOWN, "source_ref": None, "source_class": None,
                           "as_of": None} for d in contract.COUNTERPARTY_DIMENSIONS},
    }


def _role(out: dict, role: str, state: str, *, name: Optional[str] = None,
          source_ref: Optional[str] = None, source_class: Optional[str] = None) -> None:
    out["roles"][role] = {"state": state, "name": name, "source_ref": source_ref, "source_class": source_class}


def _dim(out: dict, dim: str, state: str, *, source_ref: Optional[str] = None,
          source_class: Optional[str] = None, as_of: Optional[str] = None) -> None:
    out["dimensions"][dim] = {"state": state, "source_ref": source_ref, "source_class": source_class,
                              "as_of": as_of}


# ── STABLECOIN_SAVINGS (sUSDS, sDAI) ────────────────────────────────────────────────────────────
def stablecoin_savings(symbol: str, *, gsm_hours: Optional[float] = None,
                        gsm_as_of: Optional[str] = None) -> dict:
    """Sky/MakerDAO savings vault counterparty facts. ``gsm_hours``/``gsm_as_of`` — when the
    caller has a fresh on-chain GSM pause-delay reading (``data/sky_status.json``) — upgrade
    ``redemption_restrictions`` from DOCUMENTED to OBSERVED (a genuine on-chain read THIS run)."""
    out = _empty("STABLECOIN_SAVINGS")
    _role(out, "issuer", contract.CP_DOCUMENTED, name="Sky (MakerDAO) governance",
          source_ref="spa_core/adapters/sky_susds_feed.py", source_class=contract.SECONDARY_SOURCE)
    if gsm_hours is not None:
        _dim(out, "redemption_restrictions", contract.CP_OBSERVED,
             source_ref="data/sky_status.json (gsm_hours, on-chain)",
             source_class=contract.PRIMARY_CHAIN, as_of=gsm_as_of)
    else:
        # the GSM minimum-delay (48h) is Sky governance's OWN published parameter, not our repo's
        # analysis of it — ISSUER_CLAIM, never AUDITED_DOCUMENT (review H6b).
        _dim(out, "redemption_restrictions", contract.CP_DOCUMENTED,
             source_ref="GSM Pause Delay documented minimum (48h) — spa_core/adapters/sky_susds_feed.py",
             source_class=contract.ISSUER_CLAIM)
    # a repo-curated description of the protocol's design (over-collateralised on-chain vaults),
    # not an audit of actual reserves — SECONDARY_SOURCE.
    _dim(out, "reserve_transparency", contract.CP_DOCUMENTED,
         source_ref="MakerDAO/Sky vaults are over-collateralised on-chain positions (public)",
         source_class=contract.SECONDARY_SOURCE)
    _dim(out, "legal_dependence", contract.CP_DOCUMENTED,
         source_ref="Sky governance (DSPause/GSM) controls the savings rate and withdrawal delay",
         source_class=contract.SECONDARY_SOURCE)
    # proof_or_audit / concentration / historical_incidents: not documented anywhere in this repo
    # for the Sky savings vaults specifically — stay CP_UNKNOWN (the honest floor), named as such.
    return out


# ── TOKENISED_TREASURY / RWA_CREDIT (the 11 safety-board assets + non-board T-bill pools) ──────
def tokenised_treasury(symbol: str, issuer: Optional[str], *, source_ref: str,
                        mechanism_id: str = "TOKENISED_TREASURY",
                        redemption_documented: bool = False,
                        redemption_delay_days: Optional[float] = None,
                        redemption_fee_bps: Optional[float] = None,
                        transfer_restricted: Optional[bool] = None,
                        as_of: Optional[str] = None) -> dict:
    """A tokenised-Treasury / MMF fund's counterparty facts, built from exactly what
    ``spa_core/strategy_lab/rwa_backstop/collateral_registry.py`` and ``rwa_safety_board.json``
    document for ``symbol`` — never more. ``mechanism_id`` is the CANDIDATE's own mechanism (the
    caller may route a credit-like asset through RWA_CREDIT instead) so the UNKNOWN/NOT_APPLICABLE
    floor matches the required roles for THAT mechanism, not always TOKENISED_TREASURY's.

    ``reserve_transparency`` is never set here from an on-chain NAV read (review H6c): a share-
    price read is not a reserve-composition fact, and it is recorded separately by the scanner
    (``observations[cid]["realised_index"]``), never folded into this dimension. Absent a concrete
    documented reserve-composition fact (this repo has none), it stays at the UNKNOWN floor."""
    out = _empty(mechanism_id)
    # the issuer's NAME is asserted by our own repo's collateral_registry.py — a repo-curated fact
    # (once removed from the issuer itself), not an audit — SECONDARY_SOURCE (review H6b).
    if issuer:
        _role(out, "issuer", contract.CP_DOCUMENTED, name=issuer, source_ref=source_ref,
              source_class=contract.SECONDARY_SOURCE)
    # custodian / legal_entity: this repo documents the ISSUER and the redemption TERMS, never a
    # separately named custodian bank or legal entity — UNKNOWN (the _empty() floor), honest.
    if redemption_documented:
        # redemption delay/fee are the ISSUER'S OWN published terms (collateral_registry.py's own
        # docstring: "we encode the issuer's PUBLISHED terms") — ISSUER_CLAIM, never
        # AUDITED_DOCUMENT and never SECONDARY_SOURCE (review H6b).
        _role(out, "redemption_agent", contract.CP_DOCUMENTED, name=issuer, source_ref=source_ref,
              source_class=contract.ISSUER_CLAIM)
        _dim(out, "redemption_restrictions", contract.CP_DOCUMENTED,
             source_ref=f"{source_ref} (delay_days={redemption_delay_days}, fee_bps={redemption_fee_bps})",
             source_class=contract.ISSUER_CLAIM, as_of=as_of)
    if transfer_restricted is not None:
        # transfer-restriction is a repo-curated reading of the token's own design, not an issuer
        # TERM as such — SECONDARY_SOURCE.
        _dim(out, "legal_dependence", contract.CP_DOCUMENTED,
             source_ref=f"{source_ref} (transfer_restricted={transfer_restricted})",
             source_class=contract.SECONDARY_SOURCE, as_of=as_of)
    # reserve_transparency / proof_or_audit / concentration / historical_incidents: no audit
    # letter, reserve-composition statement or incident log is carried in this repo for any of
    # these funds — CP_UNKNOWN (the floor), never inferred from a price read.
    return out


# ── FUNDING_CAPTURE (ETH / BTC perp funding, 5-venue median) ────────────────────────────────────
#: named per spa_core/strategy_lab/data/funding_feed.py's own venue list (module docstring) — this
#: is OUR funding feed's venue set, not a claim about any other party's hedging venues.
FUNDING_VENUES = "Binance, Bybit, OKX, KuCoin + Hyperliquid (median of all that answer)"


def funding_capture(*, source_ref: str = "spa_core/strategy_lab/data/funding_feed.py") -> dict:
    out = _empty("FUNDING_CAPTURE")
    _role(out, "exchange", contract.CP_DOCUMENTED, name=FUNDING_VENUES, source_ref=source_ref,
          source_class=contract.SECONDARY_SOURCE)
    # custodian: which venue custodies margin for a given leg is not documented — UNKNOWN (floor).
    # a perp funding leg has no redemption concept and no reserve concept of its own.
    out["dimensions"]["redemption_restrictions"] = {"state": contract.CP_NOT_APPLICABLE, "source_ref": None,
                                                     "source_class": None, "as_of": None}
    out["dimensions"]["reserve_transparency"] = {"state": contract.CP_NOT_APPLICABLE, "source_ref": None,
                                                 "source_class": None, "as_of": None}
    # proof_or_audit / concentration / historical_incidents / legal_dependence of the exchanges
    # themselves: not documented in this repo — CP_UNKNOWN (the honest floor).
    return out


# ── DELTA_NEUTRAL_CARRY (sUSDe) ──────────────────────────────────────────────────────────────────
def delta_neutral_carry_susde(*, source_ref: str = "spa_core/adapters/susde_adapter.py") -> dict:
    """Review H6d: Ethena's OWN hedging venues are not documented anywhere in this repo — this
    repo's funding feed (Binance/Bybit/OKX/KuCoin/Hyperliquid) is OUR median data source, not a
    claim about where Ethena itself hedges. The ``exchange`` role is therefore left at the
    UNKNOWN floor, never filled with our venue list."""
    out = _empty("DELTA_NEUTRAL_CARRY")
    _role(out, "issuer", contract.CP_DOCUMENTED, name="Ethena Labs", source_ref=source_ref,
          source_class=contract.SECONDARY_SOURCE)
    # exchange / custodian: UNKNOWN (the floor) — see docstring above.
    _dim(out, "reserve_transparency", contract.CP_DOCUMENTED,
         source_ref=f"{source_ref} (delta-neutral collateral backing is Ethena's documented design, "
                    "per this repo's own description — not an audit of Ethena's actual reserves)",
         source_class=contract.SECONDARY_SOURCE)
    # redemption / proof_or_audit / concentration / historical_incidents / legal_dependence: not
    # independently documented in this repo beyond the adapter's own peg/cooldown gate — UNKNOWN.
    return out


# ── DeFi discovery (freshly-scanned DeFiLlama pools) ────────────────────────────────────────────
#: the handful of discovered projects this repo can actually name a counterparty fact for — every
#: other discovered project is CP_UNKNOWN across the board (that IS the honest state of a pool we
#: have never looked at before admission; the ADR's required_roles/UNKNOWN gates handle it).
_KNOWN_DISCOVERY_ISSUERS = {
    "sky-lending": ("Sky (MakerDAO) governance", "spa_core/adapters/sky_susds_feed.py"),
}


def discovery_default(project: str, *, source_ref: str, mechanism_id: str) -> dict:
    out = _empty(mechanism_id)
    known = _KNOWN_DISCOVERY_ISSUERS.get(str(project or "").strip().lower())
    if known:
        name, doc = known
        _role(out, "issuer", contract.CP_DOCUMENTED, name=name, source_ref=doc,
              source_class=contract.SECONDARY_SOURCE)
    # everything else about a freshly discovered pool is simply not known yet — CP_UNKNOWN by
    # the _empty() floor (or NOT_APPLICABLE where the mechanism itself does not call for the role).
    return out


# ── trading_research (projected, OBSERVE_ONLY — never admitted here) ───────────────────────────
def trading_research_default() -> dict:
    """The projected engine names no counterparty of its own (it trades a modelled BTC price
    series, not a specific custodied exchange account, per ``trading_research/status.json``) —
    CP_UNKNOWN (or NOT_APPLICABLE per DIRECTIONAL_TREND's required_roles) throughout; it is
    OBSERVE_ONLY and never reaches a gate that reads this."""
    return _empty("DIRECTIONAL_TREND")
