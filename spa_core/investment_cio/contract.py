"""Investment CIO (Oracle) — the frozen contract of ADR-554.

Role ``chief_investment_officer``: a cross-sleeve, ADVISORY / PAPER capital-allocation layer. It projects the
engines' own published state into comparable sleeves, recommends (or abstains), records every recommendation in an
immutable ledger and scores it later against what actually happened. It never executes and never writes a book.

Every value a sleeve exposes is a :func:`measured` cell or an :func:`absent` cell — never a bare number. A missing
measurement is NOT_MEASURED (or NOT_ENOUGH_HISTORY / UNDEFINED / STALE) with a reason; it is never 0, ``[]`` or
HEALTHY (invariant #17).

# LLM_FORBIDDEN — numerical policy is deterministic and reproducible from the same inputs.
"""
from __future__ import annotations

from typing import Any, Optional

SCHEMA_SLEEVES = "investment-cio-sleeves/1"
SCHEMA_REC = "investment-cio-rec/1"
SCHEMA_OUTCOME = "investment-cio-outcome/1"
POLICY_VERSION = "cio-policy-v1"

ROLE_ID = "chief_investment_officer"
ROLE_TITLE = "Chief Investment Officer"
ROLE_DISPLAY_NAME = "Oracle"  # display metadata only (owner 2026-10-04; formerly «Штирлиц»); authority binds to ROLE_ID
MODE = "ADVISORY_PAPER"

# ── cell states (invariant #17: absence is its own value) ─────────────────────────────────────────
MEASURED = "MEASURED"
NOT_MEASURED = "NOT_MEASURED"
NOT_ENOUGH_HISTORY = "NOT_ENOUGH_HISTORY"
UNDEFINED = "UNDEFINED"          # mathematically undefined (e.g. correlation of a constant-accrual series)
STALE = "STALE"
CELL_STATES = (MEASURED, NOT_MEASURED, NOT_ENOUGH_HISTORY, UNDEFINED, STALE)


def measured(value: Any, *, unit: Optional[str], source: str, as_of: Optional[str], n: Optional[int] = None,
             note: Optional[str] = None) -> dict:
    """A measured cell. ``n`` = number of observations behind it (required for any rate or statistic)."""
    return {"state": MEASURED, "value": value, "unit": unit, "source": source, "as_of": as_of, "n": n, "note": note}


def absent(state: str, *, reason: str, source: Optional[str] = None, as_of: Optional[str] = None,
           n: Optional[int] = None) -> dict:
    """An absent cell: never carries a value. ``state`` ∈ NOT_MEASURED / NOT_ENOUGH_HISTORY / UNDEFINED / STALE."""
    if state == MEASURED or state not in CELL_STATES:
        raise ValueError(f"absent() needs a non-measured state, got {state!r}")
    if not reason:
        raise ValueError("an absent cell must name its reason")
    return {"state": state, "value": None, "unit": None, "source": source, "as_of": as_of, "n": n, "reason": reason}


def value_of(cell: Any) -> Any:
    """The value of a MEASURED cell, else None. The ONLY sanctioned way to read a number out of a cell."""
    return cell.get("value") if isinstance(cell, dict) and cell.get("state") == MEASURED else None


# ── sleeves (ADR-554 WP-A01) ──────────────────────────────────────────────────────────────────────
#: sleeve_id → static identity. Everything dynamic is projected from the engines at run time.
SLEEVES: dict = {
    "defi_conservative": {"name": "DeFi Conservative", "package": "conservative", "allocatable": True,
                          "mechanism_class": "unlevered_lending"},
    "defi_balanced": {"name": "DeFi Balanced", "package": "balanced", "allocatable": True,
                      "mechanism_class": "fixed_rate_pt"},
    "defi_aggressive": {"name": "DeFi Aggressive", "package": "aggressive", "allocatable": True,
                        "mechanism_class": "leveraged_loop"},
    "cash": {"name": "Cash / Treasury", "package": None, "allocatable": True, "mechanism_class": "cash"},
    "trading_research": {"name": "Trading (research)", "package": None, "allocatable": False,
                         "mechanism_class": "directional_trading"},
    "market_neutral_basis": {"name": "Market-Neutral / Basis (research)", "package": None, "allocatable": False,
                             "mechanism_class": "delta_neutral"},
}
DEFI_SLEEVES = ("defi_conservative", "defi_balanced", "defi_aggressive")

#: every sleeve exposes ALL of these keys; each value is a cell (measured/absent) unless noted as plain.
SLEEVE_FIELDS = (
    # identity (plain values)
    "sleeve_id", "name", "mechanism", "mechanism_class", "mode", "allocatable", "live_admission",
    "experiment_id", "experiment_start", "versions_closed",
    # cells
    "capital_basis", "current_equity", "observation_window", "valid_periods", "maturity",
    "expected_return", "realized_return", "volatility", "max_drawdown",
    "liquidity", "time_to_exit", "cash_share", "gross_exposure_over_nav", "leverage",
    "nearest_enforced_stop", "loss_budget", "stress_loss", "worst_case_loss",
    "mtm_coverage", "data_freshness", "evidence_state", "regime_fit", "confidence", "capacity",
    # structured (plain)
    "risk", "composition", "factors", "correlation_features", "gates", "warnings", "unknowns",
)

#: maturity of the CURRENT economics (valid_periods). 30 = package_status reportable_after (reused).
MATURITY_IMMATURE = "IMMATURE"
MATURITY_DEVELOPING = "DEVELOPING"
MATURITY_MATURE = "MATURE"

# ── risk taxonomy (ADR-554 WP-A04) ────────────────────────────────────────────────────────────────
RISK_AXES = ("PROTOCOL", "STRATEGY", "MARKET", "EXECUTION", "LIQUIDITY", "COUNTERPARTY", "LEVERAGE", "DATA_MODEL")
RISK_LEVELS = ("LOW", "MEDIUM", "HIGH", "UNKNOWN")
#: underlying factors — major_risks are keyed by these, so one factor hitting several axes is ONE risk
FACTORS = ("usde_peg", "maple_credit", "fluid", "usdc_peg", "pendle_pt", "smart_contract", "oracle",
           "funding_rate", "btc_direction", "data_model")

# ── policy (ADR-554 WP-A03, revised after the independent review) ──────────────────────────────────
POLICY: dict = {
    "version": POLICY_VERSION,
    "maturity_developing_min": 30,      # package_status reportable_after — reused, not invented
    "maturity_mature_min": 90,
    "cap_developing": 0.20,
    "cap_mature": 0.50,                 # uncalibrated v1 diversification parameter (labelled as such)
    "cash_floor": 0.05,                 # RiskPolicy min_cash_pct — reused
    "hysteresis_pp": 5.0,               # vs the PREVIOUS recommendation, never vs the seed split
    "min_eligible_for_recommend": 2,
    "weight_rounding_pp": 1.0,
    "rate_min_bars": 30,                # a rate on fewer bars is never displayed as a rate
    "high_confidence_reachable": False, # until MTM coverage and a measured price-risk correlation exist
    "outcome_horizons_days": (7, 30),
    "snapshot_retention_days": 400,
    "correlation_min_overlap_days": 30,
    "correlation_min_distinct_returns": 6,
}
POLICY_PARAMETER_NOTES = {
    "cap_mature": "uncalibrated v1 diversification parameter: no single sleeve above half; 90 calm accrual days with "
                  "no stress event prove nothing about the tail",
    "cash_floor": "RiskPolicy v1.0 min_cash_pct, applied on a look-through basis (advisory here, never enforced)",
    "maturity_developing_min": "package_status reportable_after",
}

# ── recommendation (ADR-554 WP-A02) ───────────────────────────────────────────────────────────────
STANCE_RECOMMEND = "RECOMMEND"
STANCE_HOLD = "HOLD"
STANCE_INSUFFICIENT = "INSUFFICIENT_EVIDENCE"
STANCE_NONE = "NO_RECOMMENDATION"
STANCES = (STANCE_RECOMMEND, STANCE_HOLD, STANCE_INSUFFICIENT, STANCE_NONE)
CONFIDENCE = ("LOW", "MEDIUM", "HIGH")

REC_FIELDS = (
    "schema", "recommendation_id", "generated_at", "date", "evidence_cutoff", "input_ages", "mode", "role_id",
    "stance", "recommended_weights", "seed_split_weights", "previous_recommendation_id", "change_vs_previous",
    "change_vs_seed_split", "portfolio_expected_return", "portfolio_risk_summary", "portfolio_drawdown_estimate",
    "liquidity_summary", "diversification_summary", "regime", "confidence", "confidence_reasons",
    "binding_constraints", "major_risks", "unknowns", "abstentions", "rationale", "explanation_facts",
    "alternatives_considered", "evidence_refs", "policy_version", "policy", "code_identity", "lineage",
    "executes", "real_capital_usd",
)

# ── storage (ADR-554 WP-S03) ──────────────────────────────────────────────────────────────────────
DATA_SUBDIR = "investment_cio"
LEDGER = "ledger.jsonl"
OUTCOMES = "outcomes.jsonl"
LATEST = "latest.json"
SNAPSHOT_DIR = "snapshots"
LOCK = ".ledger.lock"
