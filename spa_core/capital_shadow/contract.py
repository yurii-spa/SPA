"""RM-LIVE-01 · capital shadow — the frozen contract of ADR-556 (incl. its binding review revision).

This layer stands between an investment recommendation and any future real-capital action. It constructs UNSIGNED
intents, simulates them read-only, executes them in SHADOW (hypothetically), reconciles, and evaluates pilot
readiness. It never holds a key, never signs, never broadcasts, never submits an order, never moves funds.

Values follow the ADR-554 cell discipline: a measurement or an explicit absence — never a silent 0/[]/healthy.

# LLM_FORBIDDEN — every decision here is deterministic and reproducible.
"""
from __future__ import annotations

from spa_core.investment_cio.contract import (MEASURED, NOT_ENOUGH_HISTORY, NOT_MEASURED, STALE, UNDEFINED,  # noqa: F401
                                              absent, measured, value_of)

SCHEMA_INTENT = "capital-intent/1"
SCHEMA_SIMULATION = "capital-simulation/1"
SCHEMA_RECONCILIATION = "capital-reconciliation/1"
SCHEMA_READINESS = "pilot-readiness/1"
SCHEMA_RUNBOOK = "pilot-runbook/1"
POLICY_VERSION = "shadow-policy-v1"
ADR = "ADR-556"
EPIC = "RM-LIVE-01"
SOURCE_ROLE_ID = "chief_investment_officer"

# ── execution modes (WP-A00) — there is NO auto-live mode ────────────────────────────────────────
MODE_RESEARCH = "RESEARCH"
MODE_PAPER = "PAPER"
MODE_SHADOW = "SHADOW"
MODE_MANUAL_PILOT_READY = "MANUAL_PILOT_READY"
MODE_BLOCKED = "BLOCKED"
MODE_LIVE_AUTOMATION_PROHIBITED = "LIVE_AUTOMATION_PROHIBITED"
MODES = (MODE_RESEARCH, MODE_PAPER, MODE_SHADOW, MODE_MANUAL_PILOT_READY, MODE_BLOCKED,
         MODE_LIVE_AUTOMATION_PROHIBITED)
#: the layer's own operating mode — a constant, not a setting
LAYER_MODE = MODE_SHADOW
AUTOMATED_LIVE_EXECUTION = "PROHIBITED"
REAL_CAPITAL_USD = 0

# ── action types ──────────────────────────────────────────────────────────────────────────────────
ACTION_SUPPLY = "SUPPLY"
ACTION_WITHDRAW = "WITHDRAW"
ACTION_DEPOSIT_4626 = "DEPOSIT_4626"
ACTION_REDEEM_4626 = "REDEEM_4626"
ACTION_APPROVE = "APPROVE"
ACTION_SPOT_ORDER = "SPOT_ORDER"
ACTION_NO_ACTION = "NO_ACTION"
ACTIONS = (ACTION_SUPPLY, ACTION_WITHDRAW, ACTION_DEPOSIT_4626, ACTION_REDEEM_4626, ACTION_APPROVE,
           ACTION_SPOT_ORDER, ACTION_NO_ACTION)

SCENARIO_CURRENT = "CURRENT_STATE"
SCENARIO_TEST_PREFIX = "TEST_SCENARIO:"

# ── state machine (WP-A04) ────────────────────────────────────────────────────────────────────────
S_DRAFT = "DRAFT"
S_VALIDATED = "VALIDATED"
S_SIMULATED = "SIMULATED"
S_SHADOW_READY = "SHADOW_READY"
S_SHADOW_EXECUTED = "SHADOW_EXECUTED"
S_RECONCILED = "RECONCILED"
S_MANUAL_PILOT_READY = "MANUAL_PILOT_READY"
S_OWNER_GATE = "OWNER_GATE"
S_INVALID = "INVALID"
S_STALE = "STALE"
S_SIMULATION_FAILED = "SIMULATION_FAILED"
S_RISK_BLOCKED = "RISK_BLOCKED"
S_RECONCILIATION_FAILED = "RECONCILIATION_FAILED"
S_EXPIRED = "EXPIRED"
S_CANCELLED = "CANCELLED"
S_INCIDENT = "INCIDENT"
HAPPY_PATH = (S_DRAFT, S_VALIDATED, S_SIMULATED, S_SHADOW_READY, S_SHADOW_EXECUTED, S_RECONCILED,
              S_MANUAL_PILOT_READY, S_OWNER_GATE)
FAILURE_STATES = (S_INVALID, S_STALE, S_SIMULATION_FAILED, S_RISK_BLOCKED, S_RECONCILIATION_FAILED, S_EXPIRED,
                  S_CANCELLED, S_INCIDENT)
TERMINAL_STATES = FAILURE_STATES + (S_OWNER_GATE,)
#: allowed transitions; anything else is refused. No state leads to execution — OWNER_GATE is terminal.
TRANSITIONS: dict = {
    S_DRAFT: (S_VALIDATED, S_INVALID, S_STALE, S_EXPIRED, S_CANCELLED, S_INCIDENT),
    S_VALIDATED: (S_SIMULATED, S_SIMULATION_FAILED, S_RISK_BLOCKED, S_STALE, S_EXPIRED, S_CANCELLED, S_INCIDENT),
    S_SIMULATED: (S_SHADOW_READY, S_SIMULATION_FAILED, S_RISK_BLOCKED, S_STALE, S_EXPIRED, S_CANCELLED, S_INCIDENT),
    S_SHADOW_READY: (S_SHADOW_EXECUTED, S_RISK_BLOCKED, S_STALE, S_EXPIRED, S_CANCELLED, S_INCIDENT),
    S_SHADOW_EXECUTED: (S_RECONCILED, S_RECONCILIATION_FAILED, S_RISK_BLOCKED, S_EXPIRED, S_CANCELLED, S_INCIDENT),
    S_RECONCILED: (S_MANUAL_PILOT_READY, S_RISK_BLOCKED, S_STALE, S_EXPIRED, S_CANCELLED, S_INCIDENT),
    S_MANUAL_PILOT_READY: (S_OWNER_GATE, S_RISK_BLOCKED, S_STALE, S_EXPIRED, S_CANCELLED, S_INCIDENT),
}
#: TEST_SCENARIO intents stop here (review #12) — never MANUAL_PILOT_READY, never a runbook
SCENARIO_MAX_STATE = S_SHADOW_EXECUTED

# ── CapitalActionIntent (WP-A01) ──────────────────────────────────────────────────────────────────
INTENT_FIELDS = (
    "schema_version", "intent_id", "created_at", "expires_at", "pinned_block", "source_recommendation_id",
    "source_role_id", "source_book_decision", "sleeve_id", "strategy_id", "action_type", "network_or_venue",
    "instrument", "from_asset", "to_asset", "notional", "notional_unit", "expected_price", "max_slippage",
    "expected_fees", "expected_gas", "expected_position_after", "risk_snapshot", "constraints", "evidence_refs",
    "simulation_required", "owner_action_required", "execution_mode", "reason", "unknowns", "scenario",
    "policy_version",
)
#: fields hashed into intent_id (semantic content + pinned block — review #5)
INTENT_ID_FIELDS = ("sleeve_id", "strategy_id", "action_type", "network_or_venue", "instrument", "from_asset",
                    "to_asset", "notional", "scenario", "pinned_block", "source_recommendation_id",
                    "source_book_decision")
INTENT_TTL_SHADOW_S = 6 * 3600
INTENT_TTL_PILOT_S = 3600                      # review #9: a pilot runbook expires in ≤ 1 h

# ── simulation (WP-S02/S03) ───────────────────────────────────────────────────────────────────────
SIM_LABEL = "SIMULATED_UNDER_ASSUMED_STATE"
SIM_PASS = "PASS"
SIM_FAIL = "FAIL"
SIM_NOT_SIMULATABLE = "NOT_SIMULATABLE"
NOT_PROVEN = (
    "the real wallet's balance, allowance and nonce",
    "Safe threshold, owners and modules",
    "gas price at inclusion",
    "MEV / sandwiching",
    "oracle or rate movement between simulation and inclusion",
    "allow-list / KYC / blacklist behaviour for the real sender",
)
TRUST_MODEL = "consistency of public RPCs at a pinned block, not verified state — no light client"
#: JSON-RPC methods the client may send — exact match, no batch (review #13)
RPC_ALLOWED_METHODS = frozenset({"eth_chainId", "eth_blockNumber", "eth_getBlockByNumber", "eth_call",
                                 "eth_estimateGas", "eth_getCode"})
#: declared operators of the override-capable endpoints (review #3); an aggregator never counts twice
RPC_OPERATORS = {
    1: (("https://ethereum-rpc.publicnode.com", "Allnodes"), ("https://eth.drpc.org", "dRPC"),
        ("https://1rpc.io/eth", "Automata")),
}
RPC_MIN_INDEPENDENT_OPERATORS = 2
PERMISSIONED_VENUES = frozenset({"maple"})     # NOT_SIMULATABLE (synthetic sender reverts on allow-lists)

# ── reconciliation (WP-A05) ───────────────────────────────────────────────────────────────────────
REC_MATCHED = "MATCHED"
REC_PARTIAL = "PARTIAL"                         # reserved for the real-execution reconciler (review #4)
REC_MISMATCH = "MISMATCH"
REC_NOT_MEASURED = "NOT_MEASURED"
REC_FAILED = "FAILED"
REC_OUTCOMES = (REC_MATCHED, REC_PARTIAL, REC_MISMATCH, REC_NOT_MEASURED, REC_FAILED)
RECONCILE_FIELDS = ("cash_before", "position_before", "intended_delta", "fees", "gas", "slippage", "fills",
                    "cash_after", "position_after", "nav_impact", "unrealised_pnl", "realised_pnl",
                    "residual_exposure", "drift_vs_target")
AWAITING_RECONCILIATION = "AWAITING_RECONCILIATION"

# ── readiness (WP-A02, revised) ───────────────────────────────────────────────────────────────────
R_NOT_READY = "NOT_READY"
R_SHADOW_READY = "SHADOW_READY"
R_MANUAL_PILOT_READY = "MANUAL_PILOT_READY"     # displayed «Eligible for owner review — NOT authorized»
R_BLOCKED = "BLOCKED"
READINESS_STATES = (R_NOT_READY, R_SHADOW_READY, R_MANUAL_PILOT_READY, R_BLOCKED)
READINESS_DISPLAY = {R_MANUAL_PILOT_READY: "Eligible for owner review — NOT authorized"}
GATE_PASS, GATE_FAIL, GATE_UNKNOWN = "PASS", "FAIL", "UNKNOWN"
#: the frozen list of mandatory SYSTEM gates — evaluated by set equality (review #7)
SYSTEM_GATES = (
    "data_freshness", "strategy_evidence", "risk_evidence", "protocol_evidence", "counterparty_evidence",
    "liquidity_evidence", "mark_to_market_evidence", "reconciliation_readiness", "execution_simulation_readiness",
    "unwind_path", "incident_response_readiness", "observability_readiness", "offhost_anchor", "kill_switch_clear",
)
#: gates a SHADOW_READY verdict needs (subset)
SHADOW_GATES = ("data_freshness", "execution_simulation_readiness", "reconciliation_readiness")
#: owner decisions — reported separately, never folded into system_checks (review #6)
OWNER_PRECONDITIONS = ("golive_decision", "live_admission", "custody", "pilot_amount")
PRECONDITION_GRANTED, PRECONDITION_PENDING = "GRANTED", "PENDING"
READINESS_FIELDS = (
    "schema", "generated_at", "candidate_sleeve", "candidate_strategy", "readiness_state", "readiness_display",
    "execution_mode", "required_owner_action", "system_checks", "owner_preconditions", "data_freshness",
    "strategy_evidence", "risk_evidence", "protocol_evidence", "counterparty_evidence", "liquidity_evidence",
    "mark_to_market_evidence", "reconciliation_readiness", "execution_simulation_readiness", "custody_readiness",
    "unwind_path", "incident_response_readiness", "observability_readiness", "blocking_conditions", "warnings",
    "unknowns", "evidence_refs", "trust_model", "authorization",
)
AUTHORIZATION_TEXT = "Readiness is not authorization · real capital $0 · automated live execution PROHIBITED"

# ── storage ───────────────────────────────────────────────────────────────────────────────────────
DATA_SUBDIR = "capital_shadow"
ANCHORS_SUBDIR = "capital_shadow_anchors"
LEDGER = "ledger.jsonl"
LATEST = "latest.json"
INCIDENTS = "incidents.jsonl"
SIM_DIR = "simulations"
LOCK = ".ledger.lock"
EXIT_OK, EXIT_FAIL, EXIT_LOCKED = 0, 2, 75
