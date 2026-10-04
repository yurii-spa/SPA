"""Research Factory — the frozen contract of ADR-560 (RM-EXPAND-01), revised after the independent
architecture review (16 findings, all applied — see the ADR's "Binding revision").

One reusable factory that discovers capital opportunities outside the three DeFi books, groups them by
ECONOMIC MECHANISM, records where the return comes from and what is measured vs assumed, and moves them
through a deterministic research lifecycle. RESEARCH / PAPER only:

* nothing here moves money, signs, broadcasts or submits an order;
* nothing here changes RiskPolicy, stops, leverage limits, tiers or live admission;
* ``CIO_ELIGIBLE`` means only that Oracle (role ``chief_investment_officer``) MAY consider the sleeve in
  PAPER/ADVISORY allocation — never that real money is approved;
* an advertised APY is never a verified return; an issuer's own terms are DOCUMENTED, never MEASURED.

Every number is a CELL with an explicit state; a missing measurement is never 0, an unknown counterparty
is never safe. LLM_FORBIDDEN, stdlib only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

CONTRACT_VERSION = "research-factory-contract/1"
SCHEMA_CANDIDATE = "research-candidate/1"
SCHEMA_ADMISSION = "paper-admission/1"
SCHEMA_OBSERVATION = "forward-observation/1"
SCHEMA_STATUS = "research-factory-status/1"

LAYER_MODE = "RESEARCH_PAPER"
REAL_CAPITAL_USD = 0
LIVE_AUTHORIZED = False            # no candidate is ever live-authorized by this package (import-graph tested)
AUTHORIZATION_TEXT = ("RESEARCH ≠ APPROVED · PAPER ≠ LIVE · CIO_ELIGIBLE ≠ REAL-MONEY APPROVED · "
                      "real capital $0")

# ── sources / provenance (WP-A04, review #4/#7) ──────────────────────────────────────────────────
PRIMARY_PROTOCOL = "PRIMARY_PROTOCOL"
PRIMARY_CHAIN = "PRIMARY_CHAIN"
PRIMARY_VENUE = "PRIMARY_VENUE"
OFFICIAL_API = "OFFICIAL_API"
AUDITED_DOCUMENT = "AUDITED_DOCUMENT"
REPUTABLE_AGGREGATOR = "REPUTABLE_AGGREGATOR"
SECONDARY_SOURCE = "SECONDARY_SOURCE"
ISSUER_CLAIM = "ISSUER_CLAIM"      # the issuer's own marketing/terms — never evidence on its own
MODELLED = "MODELLED"
UNKNOWN_SOURCE = "UNKNOWN"
SOURCE_CLASSES = (PRIMARY_PROTOCOL, PRIMARY_CHAIN, PRIMARY_VENUE, OFFICIAL_API, AUDITED_DOCUMENT,
                  REPUTABLE_AGGREGATOR, SECONDARY_SOURCE, ISSUER_CLAIM, MODELLED, UNKNOWN_SOURCE)
PRIMARY_CLASSES = (PRIMARY_PROTOCOL, PRIMARY_CHAIN, PRIMARY_VENUE, OFFICIAL_API)
#: a MEASURED cell may never cite these
NOT_MEASURABLE_CLASSES = (MODELLED, UNKNOWN_SOURCE, ISSUER_CLAIM)

#: source_root = the UPSTREAM origin of a value, named by origin — never by the in-repo module that relays
#: it (adapter_status, rwa_feed, discovery all relay DeFiLlama ⇒ root ``defillama:yields``).
SOURCE_ROOT_RE = re.compile(r"^(defillama:[a-z_]+|chain:\d+|venue:[a-z0-9_]+|issuer:[a-z0-9_\-]+|"
                            r"doc:[a-z0-9_\-]+|model:[a-z0-9_\-]+|engine:[a-z0-9_\-]+)$")

#: the four kinds of return — never interchangeable
RETURN_ADVERTISED = "advertised"
RETURN_OBSERVED = "observed"
RETURN_REALISED_PAPER = "realised_paper"
RETURN_MODELLED = "modelled"
RETURN_KINDS = (RETURN_ADVERTISED, RETURN_OBSERVED, RETURN_REALISED_PAPER, RETURN_MODELLED)
#: what window a return value describes (review #15)
RETURN_WINDOWS = ("spot", "mean_7d", "mean_30d", "since_admission", "per_period")

# ── value cells (WP-A01, review #7/#16) ──────────────────────────────────────────────────────────
MEASURED = "MEASURED"
DOCUMENTED = "DOCUMENTED"            # stated by a document/issuer/aggregator, not independently measured
ESTIMATED_WITH_METHOD = "ESTIMATED_WITH_METHOD"
NOT_MEASURED = "NOT_MEASURED"
NOT_APPLICABLE = "NOT_APPLICABLE"
STALE = "STALE"
CONFLICTED = "CONFLICTED"            # independent roots disagree beyond tolerance — fail-closed (review #15)
VALUE_STATES = (MEASURED, DOCUMENTED, ESTIMATED_WITH_METHOD, NOT_MEASURED, NOT_APPLICABLE, STALE, CONFLICTED)
VALUED_STATES = (MEASURED, DOCUMENTED, ESTIMATED_WITH_METHOD)
CLOCK_SKEW_S = 300


def parse_ts(ts: Any) -> Optional[datetime]:
    if not isinstance(ts, str) or not ts:
        return None
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def cell(state: str, value: Any = None, *, unit: Optional[str] = None, source_ref: Optional[str] = None,
         source_class: Optional[str] = None, source_root: Optional[str] = None, as_of: Optional[str] = None,
         recorded_at: Optional[str] = None, method: Optional[str] = None, reason: Optional[str] = None,
         n: Optional[int] = None, window: Optional[str] = None, precision: Optional[float] = None,
         embedded_in_return: Optional[bool] = None, now: Optional[datetime] = None) -> dict:
    """One value with its state and provenance.

    * MEASURED: finite value + source_ref + source_class (not MODELLED/UNKNOWN/ISSUER_CLAIM) + source_root +
      a parseable as_of that is not in the future.
    * DOCUMENTED: value + source_ref + source_class + source_root (issuer terms, aggregator-stated facts).
    * ESTIMATED_WITH_METHOD: finite value + a named method.
    * every other state: NO value, a reason."""
    if state not in VALUE_STATES:
        raise ValueError(f"unknown value state {state!r}")
    if source_class is not None and source_class not in SOURCE_CLASSES:
        raise ValueError(f"unknown source class {source_class!r}")
    if source_root is not None and not SOURCE_ROOT_RE.match(source_root):
        raise ValueError(f"source_root must name an upstream origin, got {source_root!r}")
    if window is not None and window not in RETURN_WINDOWS:
        raise ValueError(f"unknown return window {window!r}")
    if state in VALUED_STATES:
        if value is None or isinstance(value, bool):
            raise ValueError(f"{state} cell needs a real value")
        if isinstance(value, (int, float)) and not math.isfinite(value):
            raise ValueError(f"{state} cell value must be finite")
        if state in (MEASURED, DOCUMENTED) and not (source_ref and source_class and source_root):
            raise ValueError(f"{state} cell needs source_ref, source_class and source_root")
        if state == MEASURED:
            if source_class in NOT_MEASURABLE_CLASSES:
                raise ValueError(f"a MEASURED cell cannot cite {source_class}")
            t = parse_ts(as_of)
            if t is None:
                raise ValueError("MEASURED cell needs a parseable as_of")
            if t > (now or datetime.now(timezone.utc)) + timedelta(seconds=CLOCK_SKEW_S):
                raise ValueError("MEASURED cell as_of is in the future")
        if state == ESTIMATED_WITH_METHOD and not method:
            raise ValueError("ESTIMATED_WITH_METHOD cell needs a method")
    else:
        if value is not None:
            raise ValueError(f"{state} cell must not carry a value")
        if not reason:
            raise ValueError(f"{state} cell must name its reason")
    return {"state": state, "value": value, "unit": unit, "source_ref": source_ref, "source_class": source_class,
            "source_root": source_root, "as_of": as_of, "recorded_at": recorded_at, "method": method,
            "reason": reason, "n": n, "window": window, "precision": precision,
            "embedded_in_return": embedded_in_return}


def value_of(c: Any) -> Any:
    """The number inside a MEASURED / DOCUMENTED / ESTIMATED cell, else None (display use)."""
    return c.get("value") if isinstance(c, dict) and c.get("state") in VALUED_STATES else None


def measured_value_of(c: Any) -> Any:
    """The number inside a MEASURED cell ONLY. The only read a gate may use."""
    return c.get("value") if isinstance(c, dict) and c.get("state") == MEASURED else None


# ── networks (review #2) ─────────────────────────────────────────────────────────────────────────
#: canonical network id ← every alias seen in the feeds. Unknown network ⇒ no exposure key.
CHAIN_ALIASES = {
    "ethereum": "1", "mainnet": "1", "eth": "1",
    "arbitrum": "42161", "arbitrum one": "42161",
    "optimism": "10", "op mainnet": "10",
    "base": "8453", "polygon": "137", "polygon pos": "137",
    "bsc": "56", "bnb chain": "56", "bnb smart chain": "56",
    "avalanche": "43114", "gnosis": "100", "solana": "solana", "tron": "tron", "sui": "sui",
    "monad": "143", "hyperliquid l1": "hyperliquid", "hyperliquid": "hyperliquid",
    "robinhood chain": "robinhood", "offchain": "offchain", "cex": "cex",
}


def canonical_network(name: Any) -> Optional[str]:
    """Alias → canonical id; idempotent on an already-canonical id (a stored ``network`` re-fed is accepted)."""
    k = " ".join(str(name or "").strip().lower().split())
    if k in CHAIN_ALIASES:
        return CHAIN_ALIASES[k]
    return k if k and k in set(CHAIN_ALIASES.values()) else None


# ── taxonomy (WP-A02, review #10) ────────────────────────────────────────────────────────────────
ASSET_CLASSES = ("CASH_TREASURY", "DEFI_STABLE_YIELD", "RWA", "MARKET_NEUTRAL", "CRYPTO_DIRECTIONAL",
                 "EQUITIES", "OPTIONS")
#: mechanism_id → asset class, who pays, defi_engine mechanic, whether leverage must be MEASURED, and the
#: counterparty roles that MUST be named (paper) / must not be UNKNOWN (CIO)  (review #9/#10)
MECHANISMS: dict = {
    "LENDING": {"asset_class": "DEFI_STABLE_YIELD", "defi_mechanic": "supply", "leverage_required": False,
                "required_roles": ("borrower", "oracle_provider"),
                "who_pays": "borrowers on an over-collateralised lending market"},
    "STABLECOIN_SAVINGS": {"asset_class": "CASH_TREASURY", "defi_mechanic": "savings_rate",
                           "leverage_required": False, "required_roles": ("issuer",),
                           "who_pays": "the stablecoin issuer's savings rate (protocol revenue passed through)"},
    "TOKENISED_TREASURY": {"asset_class": "CASH_TREASURY", "defi_mechanic": "rwa_tbill", "leverage_required": False,
                           "required_roles": ("issuer", "custodian", "redemption_agent", "legal_entity"),
                           "who_pays": "short-dated government debt held by an off-chain issuer/fund"},
    "FIXED_MATURITY_CARRY": {"asset_class": "DEFI_STABLE_YIELD", "defi_mechanic": "pt_fixed",
                             "leverage_required": False, "required_roles": ("issuer",),
                             "who_pays": "the floating-yield buyer of a split yield instrument"},
    "LOOPED_LENDING": {"asset_class": "DEFI_STABLE_YIELD", "defi_mechanic": "loop", "leverage_required": True,
                       "required_roles": ("borrower", "oracle_provider"),
                       "who_pays": "the spread between collateral yield and borrow cost, levered"},
    "VAULT_AGGREGATOR": {"asset_class": "DEFI_STABLE_YIELD", "defi_mechanic": "vault_aggregator",
                         "leverage_required": True, "required_roles": ("issuer", "borrower"),
                         "who_pays": "the vault's underlying strategies, net of the curator fee"},
    "RWA_CREDIT": {"asset_class": "RWA", "defi_mechanic": "rwa_credit", "leverage_required": True,
                   "required_roles": ("issuer", "borrower", "custodian", "legal_entity"),
                   "who_pays": "off-chain borrowers on private credit"},
    "SPOT_PERP_BASIS": {"asset_class": "MARKET_NEUTRAL", "defi_mechanic": "basis", "leverage_required": True,
                        "required_roles": ("exchange", "custodian"),
                        "who_pays": "leveraged longs paying the perp premium over spot"},
    "FUNDING_CAPTURE": {"asset_class": "MARKET_NEUTRAL", "defi_mechanic": "delta_neutral",
                        "leverage_required": True, "required_roles": ("exchange", "custodian"),
                        "who_pays": "the side of the perp market paying funding"},
    "DELTA_NEUTRAL_CARRY": {"asset_class": "MARKET_NEUTRAL", "defi_mechanic": "staked_synthetic",
                            "leverage_required": True, "required_roles": ("issuer", "exchange", "custodian"),
                            "who_pays": "funding + staking yield passed through a synthetic dollar"},
    "STABLE_LP": {"asset_class": "DEFI_STABLE_YIELD", "defi_mechanic": "lp_stable", "leverage_required": False,
                  "required_roles": ("issuer",), "who_pays": "traders' swap fees on a stable pool"},
    "INCENTIVE_EMISSION": {"asset_class": "DEFI_STABLE_YIELD", "defi_mechanic": None, "leverage_required": False,
                           "required_roles": ("issuer",),
                           "who_pays": "token emissions (dilution) — not a durable return"},
    "DIRECTIONAL_TREND": {"asset_class": "CRYPTO_DIRECTIONAL", "defi_mechanic": None, "leverage_required": True,
                          "required_roles": ("exchange",), "who_pays": "market price moves (directional exposure)"},
    "EQUITY_TOTAL_RETURN": {"asset_class": "EQUITIES", "defi_mechanic": None, "leverage_required": False,
                            "required_roles": ("custodian", "exchange"),
                            "who_pays": "equity price return + dividends"},
    "OPTIONS_PREMIUM": {"asset_class": "OPTIONS", "defi_mechanic": None, "leverage_required": True,
                        "required_roles": ("exchange", "custodian"),
                        "who_pays": "option buyers paying for convexity (seller carries tail risk)"},
}
#: mechanisms whose RWA/credit nature raises the CIO counterparty bar (review #9)
CREDIT_LIKE_MECHANISMS = ("TOKENISED_TREASURY", "RWA_CREDIT", "VAULT_AGGREGATOR", "DELTA_NEUTRAL_CARRY")

DOMAINS = ("CASH_TREASURY", "MARKET_NEUTRAL_BASIS", "RWA_STABLE_YIELD", "DEFI_DISCOVERY",
           "TRADING_RESEARCH", "EQUITIES", "OPTIONS")
#: domain → evidence-based build decision (WP-S05). Changing one is an ADR.
DOMAIN_DECISIONS = {
    "CASH_TREASURY": "BUILD_NOW",
    "MARKET_NEUTRAL_BASIS": "BUILD_NOW",
    "RWA_STABLE_YIELD": "BUILD_NOW",
    "DEFI_DISCOVERY": "BUILD_NOW",
    "TRADING_RESEARCH": "PROJECT_ONLY",    # pre-existing engine (ADR-525), projected read-only
    "EQUITIES": "ARCHITECTURE_ONLY",
    "OPTIONS": "ARCHITECTURE_ONLY",
}

# ── identity (review #2/#3) ──────────────────────────────────────────────────────────────────────
EXPOSURE_KEY_VERSION = 1
#: an instrument id names the HELD thing, never a ticker:
#:   <network>:0x<40 hex>      a token/receipt/vault contract
#:   llama:<pool uuid>         a DeFiLlama pool (a specific market/vault)
#:   perp:<asset>:<venueset>   a perp funding leg (e.g. perp:ETH:median5)
#:   fund:<slug>               an off-chain fund behind tokens (e.g. fund:blackrock-buidl)
#:   engine:<engine>:<id>      a candidate owned by another engine (trading_research)
INSTRUMENT_ID_RE = re.compile(r"^([a-z0-9]+:0x[0-9a-f]{40}|llama:[0-9a-f\-]{36}|perp:[A-Z0-9]+:[a-z0-9]+|"
                              r"fund:[a-z0-9\-]+|engine:[a-z_]+:[A-Za-z0-9_\-]+)$")


def instrument_id_ok(instrument_id: Any) -> bool:
    return isinstance(instrument_id, str) and bool(INSTRUMENT_ID_RE.match(instrument_id))


def exposure_key(mechanism_id: str, instrument_id: str, network: Any) -> str:
    """The ECONOMIC identity: mechanism + the HELD instrument (canonical id, never a symbol) + canonical
    network. Protocol name and URL are not part of it. Unresolvable ⇒ ValueError (the caller records the
    candidate as DATA_INSUFFICIENT; it never falls back to the symbol)."""
    if mechanism_id not in MECHANISMS:
        raise ValueError(f"unknown mechanism {mechanism_id!r}")
    if not instrument_id_ok(instrument_id):
        raise ValueError(f"instrument id must be canonical (address / llama pool / perp / fund / engine), "
                         f"got {instrument_id!r}")
    net = canonical_network(network)
    if net is None:
        raise ValueError(f"unknown network {network!r}")
    return f"v{EXPOSURE_KEY_VERSION}|{mechanism_id}|{instrument_id.lower()}|{net}"


def candidate_id(exposure: str) -> str:
    return hashlib.sha256(exposure.encode("utf-8")).hexdigest()[:20]


def sorted_legs(symbol: str) -> str:
    """LP legs in canonical order ("USDT-USDC" == "USDC-USDT") — for display/driver keys only."""
    return "-".join(sorted(p.strip().upper() for p in str(symbol or "").split("-") if p.strip()))


# ── candidate record (WP-A01, review #3/#6/#10/#15) ──────────────────────────────────────────────
#: return/cost cells. base_return excludes incentives; incentive_return never counts for admission.
CELL_FIELDS = (
    "quoted_return", "base_return", "incentive_return", "measured_return", "realised_return",
    "fees", "gas", "funding", "hedging_cost", "net_expected_return",
    "liquidity", "time_to_exit", "capacity", "duration", "leverage", "liquidation_distance",
)
RISK_FIELDS = (
    "protocol_risk", "strategy_risk", "market_risk", "counterparty_risk", "liquidity_risk", "execution_risk",
    "smart_contract_risk", "oracle_risk", "regulatory_dependency", "data_model_risk",
)
IDENTITY_FIELDS = (
    "candidate_id", "exposure_key", "exposure_key_version", "mechanism_id", "asset_class", "domain",
    "strategy_family", "network", "venue_or_protocol", "instrument", "instrument_id", "underlying_assets",
    "underlying_root", "economic_driver_key", "yield_source", "return_window", "collateral",
    "correlation_features", "regime_dependency", "superseded_by",
)
#: ``source_refs`` is a list of the candidate's provenance CELLS (each a ``cell()`` dict with source_class /
#: source_root / value) — admission reads roots and classes from it; never plain strings.
STATE_FIELDS = ("source_quality", "data_freshness", "evidence_maturity", "unknowns", "source_refs",
                "paper_status", "admission_state")
CANDIDATE_FIELDS = IDENTITY_FIELDS + CELL_FIELDS + RISK_FIELDS + STATE_FIELDS
#: cost cells subtracted by NET_RETURN unless embedded_in_return is True
COST_FIELDS = ("fees", "gas", "hedging_cost")
#: fields EXCLUDED from the snapshot fingerprint (they change without the candidate changing) — review #16
SNAPSHOT_FINGERPRINT_EXCLUDES = ("admission_state", "paper_status", "evidence_maturity", "data_freshness")
#: keys inside every cell that are excluded from the fingerprint (timestamps of re-observation)
CELL_FINGERPRINT_EXCLUDES = ("as_of", "recorded_at")


#: annual-rate units the net formula accepts, as a multiplier to a fraction per year
ANNUAL_RATE_UNITS = {"fraction_apy": 1.0, "fraction": 1.0, "pct_apy": 0.01, "pct_apy_annualised": 0.01,
                     "frac/yr": 1.0, "bps_apy": 0.0001}
#: ONE-OFF cost units (a subscription/redemption/entry/exit fee, paid once, never recurring) —
#: deliberately NOT in ANNUAL_RATE_UNITS. ADR-564 Round 5 Issue #2 (live-validation finding,
#: 2026-10-04): a prior run netted a one-off bps fee AS IF it were an annual rate (net=-2697);
#: `net_expected_return` below never does that — a one-off cost is either SKIPPED (REFERENCE_TRACK:
#: "not netted, a reference track holds no position to pay it from") or AMORTISED over an explicitly
#: declared holding period (HOLDABLE), never silently annualised.
ONE_OFF_RATE_UNITS = {"bps_one_off": 0.0001, "fraction_one_off": 1.0}
#: mirrors evidence_contract.PAPER_MODE_REFERENCE_TRACK's value — contract.py cannot import
#: evidence_contract (evidence_contract imports contract as c1; the reverse would be circular).
_PAPER_MODE_REFERENCE_TRACK = "REFERENCE_TRACK"


def _annual_fraction(x: dict):
    """The cell's value as a fraction per year, or None when its unit is not a declared annual rate."""
    if not isinstance(x, dict) or x.get("value") is None or isinstance(x.get("value"), bool):
        return None
    m = ANNUAL_RATE_UNITS.get(x.get("unit"))
    return None if m is None else float(x["value"]) * m


def _one_off_fraction(x: dict):
    """The cell's value as a one-off fraction (never annualised on its own), or None when its unit
    is not a declared one-off rate."""
    if not isinstance(x, dict) or x.get("value") is None or isinstance(x.get("value"), bool):
        return None
    m = ONE_OFF_RATE_UNITS.get(x.get("unit"))
    return None if m is None else float(x["value"]) * m


def net_expected_return(c: dict, *, paper_mode: Optional[str] = None,
                        holding_period_days: Optional[float] = None) -> dict:
    """NET = base_return − Σ COST_FIELDS (unless the cost is embedded_in_return) [+ funding only when the
    mechanism does NOT already embed it]. Any applicable input NOT_MEASURED/STALE/CONFLICTED ⇒ the result is
    NOT_MEASURED and names it. incentive_return is never added (review #6).

    ``paper_mode``/``holding_period_days`` are OPTIONAL — every existing caller that omits them keeps
    TODAY's behaviour exactly (a one-off-unit cost with no mode given is NOT_MEASURED, "needs
    amortisation"). ADR-564 Round 5 Issue #2: when a cost cell's unit is a recognised ONE-OFF rate
    (``ONE_OFF_RATE_UNITS``, never an annual rate on its own):
      * ``paper_mode == "REFERENCE_TRACK"`` — the one-off cost is SKIPPED (never subtracted, never
        fails the computation by itself) and named in the result's ``method`` as "not netted" — a
        reference track holds no position for a one-off entry/exit cost to apply AGAINST;
      * otherwise (HOLDABLE or unspecified) — amortised into an annual-equivalent drag over
        ``holding_period_days`` when a POSITIVE one is declared; no declared holding period ⇒
        NOT_MEASURED (unchanged pre-fix behaviour — never silently annualised)."""
    base = c.get("base_return") if isinstance(c.get("base_return"), dict) else {}
    funding = c.get("funding") if isinstance(c.get("funding"), dict) else {}
    if base.get("state") == NOT_APPLICABLE:
        # a funding-leg mechanism has no base leg: the return IS the funding (not embedded anywhere).
        # Starting from 0 here is not a missing-as-zero: the base leg does not exist by mechanism.
        if funding.get("state") not in VALUED_STATES or funding.get("embedded_in_return") is True:
            return cell(NOT_MEASURED, reason="base_return not applicable and funding not valued")
        total, used = 0.0, []
    elif base.get("state") not in VALUED_STATES:
        return cell(NOT_MEASURED, reason="base_return not valued")
    else:
        if _annual_fraction(base) is None:
            return cell(NOT_MEASURED, reason=f"base_return unit {base.get('unit')!r} is not an annual rate")
        total, used = _annual_fraction(base), ["base_return"]
    not_netted = []
    for f in COST_FIELDS + ("funding",):
        x = c.get(f) or {}
        st = x.get("state")
        if st == NOT_APPLICABLE or x.get("embedded_in_return") is True:
            continue
        if st not in VALUED_STATES:
            return cell(NOT_MEASURED, reason=f"{f} is {st or 'missing'} — net return not computable")
        # ADR-564 integration finding: costs and the rate must be in ONE annual unit. A one-off fee (bps per
        # trade, USD) or a unit-less value can only be netted after amortisation over a DECLARED holding period —
        # never subtracted from an annual rate as is (a live run produced net = -2697 from exactly that).
        if _annual_fraction(x) is None:
            one_off = _one_off_fraction(x)
            if one_off is None:
                return cell(NOT_MEASURED, reason=f"{f} unit {x.get('unit')!r} is not an annual rate comparable "
                                                 f"with the return — needs amortisation over a declared holding "
                                                 f"period")
            if paper_mode == _PAPER_MODE_REFERENCE_TRACK:
                not_netted.append(f)
                continue
            if not (isinstance(holding_period_days, (int, float)) and not isinstance(holding_period_days, bool)
                   and holding_period_days > 0):
                return cell(NOT_MEASURED, reason=f"{f} unit {x.get('unit')!r} is a one-off cost — needs a "
                                                 f"declared holding_period_days to amortise, none given")
            delta = one_off * (365.0 / float(holding_period_days))
            total -= delta
            used.append(f"{f}(amortised/{holding_period_days:g}d)")
            continue
        if _annual_fraction(base if used else funding) is None:
            return cell(NOT_MEASURED, reason=f"{f} unit {x.get('unit')!r} is not an annual rate comparable with the "
                                             f"return — needs amortisation over a declared holding period")
        delta = _annual_fraction(x)
        total = total + delta if f == "funding" else total - delta
        used.append(f)
    states = {(c.get(f) or {}).get("state") for f in used + not_netted}
    st = ESTIMATED_WITH_METHOD
    method = ("base_return − costs (+ funding when not embedded); inputs: " + ",".join(used)
             + "; input states: " + ",".join(sorted(s for s in states if s)))
    if not_netted:
        method += ("; not netted (REFERENCE_TRACK holds no position to apply a one-off cost against): "
                  + ",".join(not_netted))
    return cell(st, round(total, 10), unit="fraction_apy", method=method)


# ── lifecycle (WP-A03, review #1/#13) ────────────────────────────────────────────────────────────
DISCOVERED = "DISCOVERED"
SCREENED = "SCREENED"
RESEARCH_READY = "RESEARCH_READY"
PAPER_CANDIDATE = "PAPER_CANDIDATE"
PAPER_ACTIVE = "PAPER_ACTIVE"
EVIDENCE_ACCUMULATING = "EVIDENCE_ACCUMULATING"
CIO_ELIGIBLE = "CIO_ELIGIBLE"
REJECTED = "REJECTED"
STALE_STATE = "STALE"
DATA_INSUFFICIENT = "DATA_INSUFFICIENT"
RISK_UNRESOLVED = "RISK_UNRESOLVED"
COUNTERPARTY_UNKNOWN = "COUNTERPARTY_UNKNOWN"
DUPLICATE_EXPOSURE = "DUPLICATE_EXPOSURE"
PAUSED_PRE_PAPER = "PAUSED_PRE_PAPER"
PAUSED_PAPER = "PAUSED_PAPER"
SUPERSEDED = "SUPERSEDED"
DISAPPEARED = "DISAPPEARED"        # a paper candidate whose source vanished — terminal, loss UNKNOWN (review #12)
OBSERVE_ONLY = "OBSERVE_ONLY"      # a projected candidate owned by another engine — always, whatever its stage

FORWARD_STATES = (DISCOVERED, SCREENED, RESEARCH_READY, PAPER_CANDIDATE, PAPER_ACTIVE,
                  EVIDENCE_ACCUMULATING, CIO_ELIGIBLE)
HOLD_STATES = (REJECTED, STALE_STATE, DATA_INSUFFICIENT, RISK_UNRESOLVED, COUNTERPARTY_UNKNOWN,
               DUPLICATE_EXPOSURE, PAUSED_PRE_PAPER, PAUSED_PAPER, SUPERSEDED, DISAPPEARED, OBSERVE_ONLY)
LIFECYCLE_STATES = FORWARD_STATES + HOLD_STATES
PAPER_STATES = (PAPER_ACTIVE, EVIDENCE_ACCUMULATING, CIO_ELIGIBLE)
TERMINAL_STATES = (SUPERSEDED, DISAPPEARED)

TRANSITIONS = {
    # OBSERVE_ONLY: entry for candidates projected from another engine (trading_research) — only from
    # DISCOVERED, and the lifecycle admits it only for the TRADING_RESEARCH domain
    DISCOVERED: {SCREENED, REJECTED, DATA_INSUFFICIENT, DUPLICATE_EXPOSURE, STALE_STATE, OBSERVE_ONLY},
    SCREENED: {RESEARCH_READY, REJECTED, DATA_INSUFFICIENT, RISK_UNRESOLVED, COUNTERPARTY_UNKNOWN,
               DUPLICATE_EXPOSURE, STALE_STATE},
    RESEARCH_READY: {PAPER_CANDIDATE, REJECTED, DATA_INSUFFICIENT, RISK_UNRESOLVED, COUNTERPARTY_UNKNOWN,
                     DUPLICATE_EXPOSURE, STALE_STATE, PAUSED_PRE_PAPER},
    PAPER_CANDIDATE: {PAPER_ACTIVE, REJECTED, DATA_INSUFFICIENT, STALE_STATE, PAUSED_PRE_PAPER},
    PAPER_ACTIVE: {EVIDENCE_ACCUMULATING, STALE_STATE, PAUSED_PAPER, REJECTED, SUPERSEDED, DISAPPEARED},
    EVIDENCE_ACCUMULATING: {CIO_ELIGIBLE, STALE_STATE, PAUSED_PAPER, REJECTED, SUPERSEDED, DISAPPEARED},
    CIO_ELIGIBLE: {EVIDENCE_ACCUMULATING, STALE_STATE, PAUSED_PAPER, REJECTED, SUPERSEDED, DISAPPEARED},
    # holds: back to SCREENED only through a re-screen whose failed-gate inputs CHANGED, or terminal
    REJECTED: {SCREENED, SUPERSEDED},
    STALE_STATE: {SCREENED, SUPERSEDED, REJECTED, DISAPPEARED},
    DATA_INSUFFICIENT: {SCREENED, SUPERSEDED, REJECTED},
    RISK_UNRESOLVED: {SCREENED, SUPERSEDED, REJECTED},
    COUNTERPARTY_UNKNOWN: {SCREENED, SUPERSEDED, REJECTED},
    DUPLICATE_EXPOSURE: {SCREENED, SUPERSEDED},
    PAUSED_PRE_PAPER: {SCREENED, REJECTED, SUPERSEDED},
    # resume only to the recorded paused_from state, and only through that state's gate
    PAUSED_PAPER: {PAPER_ACTIVE, EVIDENCE_ACCUMULATING, REJECTED, SUPERSEDED, DISAPPEARED},
    SUPERSEDED: set(),
    DISAPPEARED: set(),
    OBSERVE_ONLY: set(),
}
#: target → the gate that must have produced the transition (machine-checked)
GATED_TARGETS = {
    PAPER_ACTIVE: "admission",                 # needs a PASS admission snapshot id
    EVIDENCE_ACCUMULATING: "admission",        # needs the SAME valid admission snapshot id
    CIO_ELIGIBLE: "cio_eligibility",           # needs every CIO gate PASS, re-checked every run
    SCREENED: "rescreen_inputs_changed",       # from a hold state only
}
#: the only entry into PAPER_STATES from outside PAPER_STATES
PAPER_ENTRY = (PAPER_CANDIDATE, PAPER_ACTIVE)


def transition_allowed(frm: str, to: str) -> bool:
    return frm in TRANSITIONS and to in TRANSITIONS[frm]


# ── counterparty model (WP-A05, review #9) ───────────────────────────────────────────────────────
COUNTERPARTY_ROLES = ("issuer", "custodian", "borrower", "market_maker", "exchange", "redemption_agent",
                      "legal_entity", "oracle_provider", "bridge")
COUNTERPARTY_DIMENSIONS = ("reserve_transparency", "proof_or_audit", "redemption_restrictions",
                           "concentration", "historical_incidents", "legal_dependence")
CP_OBSERVED = "OBSERVED"
CP_DOCUMENTED = "DOCUMENTED"
CP_UNKNOWN = "UNKNOWN"            # NEVER read as safe
CP_NOT_APPLICABLE = "NOT_APPLICABLE"
CP_STATES = (CP_OBSERVED, CP_DOCUMENTED, CP_UNKNOWN, CP_NOT_APPLICABLE)
#: no blended rating exists by design; the summary is counts + named concerns only
CP_SUMMARY_FIELDS = ("roles_named", "roles_unknown", "required_roles_missing", "dimensions_observed",
                     "dimensions_documented", "dimensions_unknown", "concerns")
#: CIO bar for credit-like mechanisms: these dimensions ≥ DOCUMENTED from a non-ISSUER_CLAIM source, and at
#: least one dimension OBSERVED
CIO_CREDIT_DIMENSIONS = ("reserve_transparency", "redemption_restrictions")

# ── paper admission (WP-A06, review #4/#6/#10/#15) ──────────────────────────────────────────────
ADMISSION_GATES = (
    "mechanism_understood", "return_source_understood", "source_provenance_acceptable", "data_fresh",
    "fees_measurable", "liquidity_measurable", "counterparty_named", "no_duplicate_exposure",
    "paper_accounting_feasible", "exit_path_defined", "not_advertised_only", "leverage_known",
    "no_conflicted_inputs",
)
GATE_PASS = "PASS"
GATE_FAIL = "FAIL"
GATE_UNKNOWN = "UNKNOWN"   # an UNKNOWN gate never passes
#: provenance rule: one PRIMARY_* root, OR a REPUTABLE_AGGREGATOR root + an INDEPENDENT second root
#: (different source_root); a cross-check from the same root counts once
CONFLICT_TOLERANCE_REL = 0.25          # independent roots disagreeing by >25% relative ⇒ CONFLICTED
#: the immutable admission snapshot carries exactly these keys
ADMISSION_SNAPSHOT_FIELDS = ("admission_id", "candidate_id", "exposure_key", "exposure_key_version",
                             "contract_version", "code_identity", "as_of", "recorded_at", "gates",
                             "gate_input_digests", "source_refs", "thresholds", "candidate_digest")

# ── forward evidence (WP-S06, review #5/#11) ─────────────────────────────────────────────────────
#: a forward period COUNTS only if ALL hold:
#:   source as_of > admission.as_of, and strictly newer than the previous counted period's as_of;
#:   the observed value was fresh when recorded; the row is not backfill; the cell is MEASURED.
#: The first-recorded value per (candidate, period) is frozen; a later revision is a `revises` row that
#: never changes maturity or outcome. Realised return must come from an independent series (share price /
#: exchange-rate delta); otherwise it is MODELLED and `realised_vs_observed_consistent` is UNKNOWN ⇒ fails.
MIN_FORWARD_PERIODS_CIO = 30          # same threshold as the CIO's DEVELOPING maturity (ADR-554)
STALE_PERIODS_TO_STALE_STATE = 3      # a stale period is not counted; 3 consecutive ⇒ STALE
MATURITY_ON_READMISSION = 0           # re-admission restarts maturity at 0
CIO_ELIGIBILITY_GATES = ("forward_periods", "admission_still_valid", "data_fresh", "counterparty_no_unknown_role",
                         "counterparty_credit_bar", "no_duplicate_exposure", "realised_vs_observed_consistent",
                         # ADR-564 amendment (architecture review #13): paper admission must never quietly become
                         # CIO eligibility on issuer-only evidence or on a position SPA could not hold
                         "min_origins_cio", "counterparty_grade_strong_for_credit_like",
                         "holder_eligibility_documented", "not_reference_track",
                         # ADR-564 post-implementation review M1 amendment: every CIO_MIN_GRADE /
                         # MIN_GROUPS_CIO bar is ENFORCED, not just declared
                         "return_grade_strong_for_cio", "custody_grade_strong_for_cio",
                         "reserves_grade_adequate_for_cio", "legal_grade_adequate_for_cio",
                         "reserves_groups_sufficient_for_cio", "custody_groups_sufficient_for_cio")
CIO_VISIBILITY = (OBSERVE_ONLY, PAPER_ACTIVE, CIO_ELIGIBLE)
#: the CIO may trust the read model only if fresher than this and its ledger-head hash matches
CIO_READ_MODEL_MAX_AGE_H = 26.0

# ── freshness (review #11) ───────────────────────────────────────────────────────────────────────
FRESHNESS_MAX_AGE_H = {"rate": 36.0, "funding": 12.0, "documented_terms": 24.0 * 30, "counterparty": 24.0 * 90,
                       "engine_status": 26.0}
#: source_root prefix → freshness family (default "rate")
SOURCE_FAMILY = {"venue:": "funding", "doc:": "documented_terms", "issuer:": "documented_terms",
                 "engine:": "engine_status"}


def freshness_family(source_root: Optional[str], *, counterparty: bool = False) -> str:
    if counterparty:
        return "counterparty"
    for prefix, fam in SOURCE_FAMILY.items():
        if (source_root or "").startswith(prefix):
            return fam
    return "rate"


def is_fresh(c: Any, now: datetime, *, counterparty: bool = False) -> Optional[bool]:
    """True/False for a valued cell with a parseable as_of; None when it cannot be judged."""
    if not isinstance(c, dict) or c.get("state") not in VALUED_STATES:
        return None
    t = parse_ts(c.get("as_of"))
    if t is None:
        return None
    if t > now + timedelta(seconds=CLOCK_SKEW_S):
        return False
    lim = FRESHNESS_MAX_AGE_H[freshness_family(c.get("source_root"), counterparty=counterparty)]
    return (now - t).total_seconds() <= lim * 3600


# ── storage ──────────────────────────────────────────────────────────────────────────────────────
DATA_SUBDIR = "research_factory"
ANCHORS_SUBDIR = "research_factory_anchors"
LEDGER = "ledger.jsonl"
INDEX = "index.json"          # disposable, rebuilt from the ledger
STATUS = "status.json"        # read model (disposable), carries ledger_head_hash
LEDGER_KINDS = ("candidate_snapshot", "transition", "admission", "observation", "revision", "counterparty",
                "disappearance", "run")
#: status.json denominators — survivor-bias guard (review #12)
STATUS_DENOMINATORS = ("scanned", "discovered", "truncated", "rejected", "disappeared", "paper_active",
                       "cio_eligible", "observe_only")

EXIT_OK = 0
EXIT_BROKEN = 2
EXIT_LOCKED = 75


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def digest(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


# ── when a forward period may count (post-implementation review H1/H4, binding #5 made executable) ─
#: A relayed aggregator rate carries only OUR fetch time, not an upstream time: the bytes can be frozen
#: for months while the fetch time advances daily (the susde_dn failure). So a period counts only when
#: the upstream itself demonstrably advanced:
#:   (a) a MEASURED realised_index (on-chain share price / exchange rate) whose as_of (block time) is
#:       strictly newer than the previous counted period's index as_of; or
#:   (b) a MEASURED observed_return from a PRIMARY_* source whose as_of is a TRUE upstream time (e.g. the
#:       date of the latest funding settlement in the venue series) strictly newer than the previous one.
#: An aggregator-only observation never counts, however fresh its fetch time looks.
def period_countable(obs: dict, prev_counted: Optional[dict], admission_as_of: Optional[str],
                     now: datetime) -> tuple:
    """(countable: bool, reason: str). ``obs`` = {"observed_return": cell, "realised_index": cell|None,
    "backfill": bool}; ``prev_counted`` = the previous COUNTED observation (same shape) or None."""
    if not isinstance(obs, dict) or obs.get("backfill") is True:
        return False, "backfill or malformed observation never counts"
    adm = parse_ts(admission_as_of)
    idx = obs.get("realised_index")
    if isinstance(idx, dict) and idx.get("state") == MEASURED and (
            idx.get("source_class") != PRIMARY_CHAIN or not str(idx.get("source_root") or "").startswith("chain:")):
        return False, "realised index is not a primary on-chain read"
    if isinstance(idx, dict) and idx.get("state") == MEASURED:
        t = parse_ts(idx.get("as_of"))
        prev = parse_ts((prev_counted or {}).get("realised_index", {}).get("as_of")
                        if isinstance((prev_counted or {}).get("realised_index"), dict) else None)
        if t is None or (adm is not None and t <= adm):
            return False, "realised index not after admission"
        if prev is not None and t <= prev:
            return False, "realised index did not advance"
        if is_fresh(idx, now) is not True:
            return False, "realised index stale at recording"
        return True, "realised index advanced"
    ob = obs.get("observed_return")
    if not (isinstance(ob, dict) and ob.get("state") == MEASURED and ob.get("source_class") in PRIMARY_CLASSES):
        return False, "no realised index and the observed rate is not a primary upstream measurement"
    t = parse_ts(ob.get("as_of"))
    pob = (prev_counted or {}).get("observed_return")
    prev = parse_ts(pob.get("as_of")) if isinstance(pob, dict) else None
    if t is None or (adm is not None and t <= adm):
        return False, "observation not after admission"
    if prev is not None and t <= prev:
        return False, "upstream time did not advance"
    if is_fresh(ob, now) is not True:
        return False, "observation stale at recording"
    return True, "primary upstream observation advanced"
