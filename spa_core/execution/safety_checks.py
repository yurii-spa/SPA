"""
Pre-execution safety pipeline for real capital transactions.

Every real-capital transaction MUST pass ALL blocking checks before execution.
Non-blocking checks produce warnings that are logged but do not halt the transaction.

Pipeline order (see docs/v2_architecture.md § 3 for the full diagram):
  1. RiskPolicy check          (BLOCKING)
  2. Kill switch check         (BLOCKING)
  3. Rate limit check          (BLOCKING)
  4. Tenderly simulation       (BLOCKING — wired up in v2.0)
  5. Gas reasonableness check  (BLOCKING)
  6. Multisig routing check    (INFORMATIONAL — determines execution path)

Usage:
    safety = PreExecutionSafety()
    results = safety.run_all(
        protocol="aave-v3",
        action="supply",
        amount_usd=1000.0,
        portfolio_state=portfolio_dict,
    )
    if any(r.blocking and not r.passed for r in results):
        raise TransactionBlocked("One or more safety checks failed")
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

# CONVERGENCE (WS-B1/B2, ADR-049): the execution kill-switch consults the ONE
# canonical governance source — the owner-approved two-tier ladder constants and
# the shared boundary classifier — instead of a private flat-5% hard-block. We
# import the SAME constants / classifier; we never re-define the threshold values.
from spa_core.governance.kill_switch import (
    DRAWDOWN_THRESHOLD_PCT as _GOV_HARD_PCT,
    SOFT_DERISK_THRESHOLD_PCT as _GOV_SOFT_PCT,
    TIER_HARD_KILL as _GOV_TIER_HARD,
    TIER_NONE as _GOV_TIER_NONE,
    TIER_SOFT_DERISK as _GOV_TIER_SOFT,
    classify_drawdown_pct as _gov_classify_drawdown_pct,
)


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class SafetyCheckResult:
    """Result of a single pre-execution safety check."""
    passed:      bool           # Did the check pass?
    check_name:  str            # Human-readable check name
    details:     str            # Explanation of the result
    blocking:    bool           # If True, a failed check MUST halt the transaction
    severity:    str = "INFO"   # "INFO" | "WARN" | "ERROR"
    value:       Any = None     # The measured value (for logging)
    threshold:   Any = None     # The threshold used (for logging)

    @property
    def is_hard_block(self) -> bool:
        """True if this check failed AND is blocking — transaction must not proceed."""
        return self.blocking and not self.passed


@dataclass
class SafetyPipelineResult:
    """Aggregated result from running all safety checks."""
    all_passed:      bool
    blocked:         bool                    # Any hard block present
    checks:          list[SafetyCheckResult] = field(default_factory=list)
    requires_multisig: bool = False          # True if amount > $500
    blocking_reasons:  list[str] = field(default_factory=list)

    @classmethod
    def from_checks(cls, checks: list[SafetyCheckResult]) -> "SafetyPipelineResult":
        hard_blocks = [c for c in checks if c.is_hard_block]
        multisig_check = next(
            (c for c in checks if c.check_name == "Multisig Routing"), None
        )
        requires_multisig = bool(
            multisig_check and not multisig_check.passed  # "not passed" = needs multisig
        )
        # For the multisig check specifically, "not passed" is informational, not a block
        real_blocks = [c for c in hard_blocks if c.check_name != "Multisig Routing"]

        return cls(
            all_passed=len(real_blocks) == 0,
            blocked=len(real_blocks) > 0,
            checks=checks,
            requires_multisig=requires_multisig,
            blocking_reasons=[c.details for c in real_blocks],
        )


# ── Rate limit state (module-level, resets on process restart) ───────────────

_tx_timestamps: list[float] = []   # Unix timestamps of recent transactions

_RATE_LIMIT_WINDOW_SECONDS = 3600  # 1 hour
_RATE_LIMIT_MAX_TX         = 3     # max transactions per hour

# ── Kill-switch state (PERSISTED — WS-B2, ADR-049) ───────────────────────────
# The manual kill is NO LONGER a process-local boolean (a crash silently reset
# it). The authoritative state is the atomic ``data/kill_switch_active.json``
# governed by ``spa_core.governance.kill_switch`` — read on every check, so it
# survives a process restart and is consistent with governance's file lifecycle
# (file ABSENT = OFF; file with ``active=False`` = explicitly OFF).
#
# ``_kill_switch_active`` is kept ONLY as a DEPRECATED advisory shim: it no
# longer drives the verdict (the persisted file does). It exists so legacy
# callers / tests that still poke the module attribute do not break. activate /
# deactivate now write / clear the persisted file (the source of truth).
_kill_switch_active: bool = False

MULTISIG_THRESHOLD_USD = 500.0     # amounts above this require Safe multisig approval
GAS_MAX_PCT_OF_TRADE   = 2.0       # gas cost must be < 2% of transaction value


# Module-level data-dir override — lets tests / sandbox / a dry-run point the
# persisted kill-switch state at a throwaway dir so the LIVE ``data/`` is NEVER
# touched. ``None`` → the real repo ``data/``. Set via ``set_data_dir_override``.
_DATA_DIR_OVERRIDE: "Any" = None


def set_data_dir_override(data_dir: "Any") -> None:
    """Point the persisted kill-switch state at ``data_dir`` (or reset with None).

    Test / sandbox hook ONLY — production leaves this None so the real repo
    ``data/`` is used. Keeps live data untouched while still exercising the
    persisted (B2) path end-to-end.
    """
    global _DATA_DIR_OVERRIDE
    _DATA_DIR_OVERRIDE = data_dir


def _resolve_data_dir() -> "Any":
    """Repo ``data/`` dir (two levels up from this file), or the test override."""
    if _DATA_DIR_OVERRIDE is not None:
        from pathlib import Path
        return Path(_DATA_DIR_OVERRIDE)
    from pathlib import Path
    return Path(__file__).resolve().parents[2] / "data"


def _read_persisted_manual_kill() -> tuple[bool, str]:
    """Read the PERSISTED manual kill via the canonical governance lifecycle.

    Delegates to ``KillSwitchChecker.check_manual_trigger`` so the execution
    layer honours EXACTLY governance's ``data/kill_switch_active.json`` contract
    (file absent = OFF; ``active=False`` = explicitly OFF; otherwise ON with its
    recorded reason). Fail-CLOSED: any error reading the governance state is
    treated as an ACTIVE kill (you cannot move capital if you cannot confirm the
    kill is off).

    Returns ``(active, reason)``.
    """
    try:
        from spa_core.governance.kill_switch import KillSwitchChecker
        return KillSwitchChecker(data_dir=_resolve_data_dir()).check_manual_trigger()
    except Exception as exc:  # noqa: BLE001 — unreadable state → fail CLOSED
        return True, (
            f"FAIL-CLOSED: cannot read persisted kill-switch state "
            f"({type(exc).__name__}: {exc})"
        )


# ── RiskPolicy wiring helpers (read-only registry + live feed) ───────────────

def _normalize_protocol(protocol: str) -> str:
    """Normalise a gate protocol label to a registry-style key candidate."""
    return str(protocol).strip().lower().replace("-", "_")


def _registry_tier_map() -> dict:
    """Protocol-key → tier map from the read-only ADAPTER_REGISTRY (fail-safe)."""
    try:
        from spa_core.adapters import ADAPTER_REGISTRY
        return {key: tier for key, tier, _cls in ADAPTER_REGISTRY}
    except Exception:  # noqa: BLE001 — never let wiring shape the result
        return {}


def _resolve_protocol(protocol: str) -> tuple[Optional[str], Optional[str]]:
    """Resolve a gate protocol label to ``(registry_key, tier)``.

    Returns ``(None, None)`` for the registry_key when no exact registry key
    matches; the tier is best-effort (None if it cannot be determined). The
    caller MUST fail closed when the tier is None.
    """
    tier_map = _registry_tier_map()
    norm = _normalize_protocol(protocol)

    # Exact registry-key match (e.g. "aave_v3").
    if norm in tier_map:
        return norm, tier_map[norm]

    # Prefix match for whitelist family labels (e.g. "aave-v3" -> "aave_v3",
    # "compound" -> "compound_v3", "morpho" -> "morpho_blue", "spark" ->
    # "spark_susds"). Pick the deterministic (sorted) first match.
    candidates = sorted(k for k in tier_map if k == norm or k.startswith(norm + "_") or k.startswith(norm))
    if candidates:
        key = candidates[0]
        return key, tier_map[key]

    return None, None


def _resolve_chain(protocol_key: str) -> str:
    """Best-effort chain for a protocol key (defaults to ethereum)."""
    pk = _normalize_protocol(protocol_key)
    if "arbitrum" in pk:
        return "arbitrum"
    if "base" in pk:
        return "base"
    if "optimism" in pk:
        return "optimism"
    if "polygon" in pk:
        return "polygon"
    return "ethereum"


def _fetch_protocol_metrics(protocol_key: str) -> tuple[Optional[float], Optional[float]]:
    """Fetch live ``(apy_percent, tvl_usd)`` for a protocol from its adapter.

    Returns ``(None, None)`` when no adapter matches or the live feed is
    unavailable. APY is normalised to PERCENT (adapters report a decimal).
    Never raises — the caller fails closed on a ``None`` result.
    """
    try:
        from spa_core.adapters import ADAPTER_REGISTRY
    except Exception:  # noqa: BLE001
        return None, None

    norm = _normalize_protocol(protocol_key)
    cls = None
    for key, _tier, adapter_cls in ADAPTER_REGISTRY:
        if key == norm or norm.startswith(key) or key.startswith(norm):
            cls = adapter_cls
            break
    if cls is None:
        return None, None

    try:
        adapter = cls()
        data = adapter.fetch()
    except Exception:  # noqa: BLE001 — live feed problems → fail closed upstream
        return None, None

    apy = data.get("apy") if isinstance(data, dict) else None
    tvl = data.get("tvl") if isinstance(data, dict) else None
    if not isinstance(apy, (int, float)) or not isinstance(tvl, (int, float)):
        return None, None
    # Adapter APY is a decimal (e.g. 0.052); RiskPolicy expects percent.
    return float(apy) * 100.0, float(tvl)


def _build_portfolio_state(portfolio_state: dict):
    """Build a ``risk.policy.PortfolioState`` from the gate's portfolio dict.

    Accepts the legacy gate dict (``total_capital_usd`` / ``cash_usd`` /
    ``total_drawdown_pct``) and, when present, a ``positions`` list of dicts.
    When only cash/capital are supplied we synthesise a single aggregate
    "deployed" position so cash-buffer and capital maths stay correct without
    fabricating per-protocol concentration. Raises on malformed input — the
    caller treats any exception as fail-closed.
    """
    from spa_core.risk.policy import PortfolioState, Position

    total_capital = float(portfolio_state.get("total_capital_usd") or 0.0)
    positions_in = portfolio_state.get("positions")
    positions: list = []

    if isinstance(positions_in, list) and positions_in:
        for p in positions_in:
            positions.append(Position(
                protocol_key=str(p.get("protocol_key") or p.get("protocol") or "unknown"),
                tier=str(p.get("tier") or "T2"),
                asset=str(p.get("asset") or "USDC"),
                amount_usd=float(p.get("amount_usd") or p.get("usd") or 0.0),
                apy_at_open=float(p.get("apy_at_open") or p.get("current_apy") or 0.0),
                current_apy=float(p.get("current_apy") or p.get("apy_at_open") or 0.0),
                unrealized_pnl_usd=float(p.get("unrealized_pnl_usd") or 0.0),
                days_held=float(p.get("days_held") or 0.0),
                chain=str(p.get("chain") or "ethereum"),
            ))
    elif "cash_usd" in portfolio_state and total_capital > 0:
        # No per-position detail: synthesise the deployed remainder as an opaque
        # aggregate so cash_usd / cash_pct reconcile. PnL derives drawdown.
        cash = float(portfolio_state.get("cash_usd") or 0.0)
        deployed = max(0.0, total_capital - cash)
        drawdown = float(portfolio_state.get("total_drawdown_pct") or 0.0)
        pnl = -drawdown * total_capital  # negative pnl reproduces the drawdown
        if deployed > 0:
            positions.append(Position(
                protocol_key="__aggregate_deployed__",
                tier="T2",
                asset="USDC",
                amount_usd=deployed,
                apy_at_open=0.0,
                current_apy=0.0,
                unrealized_pnl_usd=pnl,
                days_held=0.0,
                chain="ethereum",
            ))

    return PortfolioState(total_capital_usd=total_capital, positions=positions)


# ── PreExecutionSafety ────────────────────────────────────────────────────────

class PreExecutionSafety:
    """
    Runs the full pre-execution safety pipeline before any real-capital transaction.

    Instantiate once and reuse across the agent lifecycle. All state (rate limits,
    kill switch) is module-level so it persists across multiple calls within a
    single process.

    Example:
        safety = PreExecutionSafety()
        pipeline = safety.run_all("aave-v3", "supply", 1000.0, portfolio)
        if pipeline.blocked:
            # DO NOT PROCEED
            for reason in pipeline.blocking_reasons:
                logger.error(f"Safety block: {reason}")
        elif pipeline.requires_multisig:
            # Queue for Gnosis Safe approval
            safe_client.queue_transaction(...)
        else:
            # Auto-execute via hot wallet
            wallet.execute(...)
    """

    def check_risk_policy(
        self,
        protocol:        str,
        action:          str,
        amount_usd:      float,
        portfolio_state: dict,
        current_apy:     Optional[float] = None,
        tvl_usd:         Optional[float] = None,
        tier:            Optional[str]   = None,
    ) -> SafetyCheckResult:
        """
        Verify the transaction is permitted by the live, deterministic RiskPolicy v1.0.

        This stage delegates to ``spa_core.risk.policy.RiskPolicy.check_new_position``
        — the single source of truth for TVL floor, APY bounds, per-protocol /
        per-tier concentration caps, cash buffer and drawdown kill-switch. The
        whitelist + amount sanity checks below are defence-in-depth pre-filters,
        NOT the gate: the real policy is always consulted before a pass.

        FAIL-CLOSED CONTRACT (RULE #1):
          * If the protocol cannot be resolved to a known tier, or
          * the policy's required inputs (current_apy / tvl_usd) cannot be
            obtained (caller did not supply them AND the live adapter feed is
            unavailable), or
          * the RiskPolicy module cannot be imported / raises for any reason,
          then this check BLOCKS (passed=False, blocking=True, severity ERROR).
          We never fall through to a pass when policy cannot be evaluated — you
          cannot move capital if you cannot check policy.

        Args:
            protocol:        Protocol key (e.g. "aave-v3" or registry key "aave_v3").
            action:          "supply" | "withdraw".
            amount_usd:      Transaction amount in USD.
            portfolio_state: Portfolio state dict. Recognised keys:
                               total_capital_usd, cash_usd, total_drawdown_pct,
                               positions (list of {protocol_key,tier,asset,
                               amount_usd,apy_at_open,current_apy,chain,...}).
            current_apy:     Live APY for the protocol, in PERCENT (e.g. 5.2).
                               If None, fetched from the live adapter feed.
            tvl_usd:         Live pool TVL in USD. If None, fetched from the feed.
            tier:            Risk tier ("T1"|"T2"|"T3"). If None, resolved from the
                               read-only ADAPTER_REGISTRY tier map.

        Returns:
            SafetyCheckResult (blocking=True).
        """
        WHITELISTED_PROTOCOLS = {
            "aave-v3", "compound", "morpho", "yearn", "maple", "euler", "spark"
        }

        # ── Pre-filter 1: protocol whitelist (defence-in-depth) ──────────────
        if protocol not in WHITELISTED_PROTOCOLS:
            return SafetyCheckResult(
                passed=False,
                check_name="RiskPolicy",
                details=f"Protocol '{protocol}' is not in the whitelist: {WHITELISTED_PROTOCOLS}",
                blocking=True,
                severity="ERROR",
                value=protocol,
                threshold=WHITELISTED_PROTOCOLS,
            )

        # ── Pre-filter 2: amount sanity ──────────────────────────────────────
        if not isinstance(amount_usd, (int, float)) or amount_usd <= 0:
            return SafetyCheckResult(
                passed=False,
                check_name="RiskPolicy",
                details=f"Invalid amount_usd={amount_usd!r}. Must be a number > 0.",
                blocking=True,
                severity="ERROR",
                value=amount_usd,
                threshold=0,
            )

        # ── Resolve the protocol key + tier from the read-only registry ──────
        protocol_key, resolved_tier = _resolve_protocol(protocol)
        if tier is None:
            tier = resolved_tier
        if tier is None:
            # Cannot determine concentration caps → cannot evaluate policy → BLOCK.
            return SafetyCheckResult(
                passed=False,
                check_name="RiskPolicy",
                details=(
                    f"FAIL-CLOSED: cannot resolve a risk tier for protocol "
                    f"'{protocol}'. RiskPolicy cannot be evaluated without a tier."
                ),
                blocking=True,
                severity="ERROR",
                value=protocol,
                threshold="known tier",
            )

        # ── Obtain the live policy inputs (APY %, TVL $) ─────────────────────
        # Caller-supplied values win; otherwise fetch from the live adapter feed.
        if current_apy is None or tvl_usd is None:
            fed_apy, fed_tvl = _fetch_protocol_metrics(protocol_key or protocol)
            if current_apy is None:
                current_apy = fed_apy
            if tvl_usd is None:
                tvl_usd = fed_tvl

        if not isinstance(current_apy, (int, float)) or not isinstance(tvl_usd, (int, float)):
            # No live data and the caller supplied none → cannot run the TVL floor
            # / APY-bounds checks → FAIL CLOSED. Never pass blind.
            return SafetyCheckResult(
                passed=False,
                check_name="RiskPolicy",
                details=(
                    f"FAIL-CLOSED: live RiskPolicy inputs unavailable for "
                    f"'{protocol}' (current_apy={current_apy!r}, tvl_usd={tvl_usd!r}). "
                    f"Cannot evaluate TVL floor / APY bounds — blocking."
                ),
                blocking=True,
                severity="ERROR",
                value={"current_apy": current_apy, "tvl_usd": tvl_usd},
                threshold="live APY% + TVL$ required",
            )

        # ── Call the REAL deterministic RiskPolicy ───────────────────────────
        try:
            from spa_core.risk.policy import RiskPolicy
            state = _build_portfolio_state(portfolio_state)
            chain = _resolve_chain(protocol_key or protocol)
            policy = RiskPolicy()
            result = policy.check_new_position(
                state=state,
                protocol_key=protocol_key or protocol,
                tier=tier,
                amount_usd=float(amount_usd),
                current_apy=float(current_apy),
                tvl_usd=float(tvl_usd),
                chain=chain,
            )
        except Exception as policy_exc:  # noqa: BLE001 — fail CLOSED on ANY error
            # Import failure, malformed portfolio, signature error, anything:
            # we cannot confirm the policy approved → we must NOT proceed.
            return SafetyCheckResult(
                passed=False,
                check_name="RiskPolicy",
                details=(
                    f"FAIL-CLOSED: RiskPolicy could not be evaluated "
                    f"({type(policy_exc).__name__}: {policy_exc}). Blocking — you "
                    f"cannot move capital if you cannot check policy."
                ),
                blocking=True,
                severity="ERROR",
                value=str(policy_exc),
                threshold="v1.0 policy",
            )

        # ── Use the deterministic verdict ────────────────────────────────────
        if not getattr(result, "approved", False):
            reasons = "; ".join(getattr(result, "violations", []) or ["policy rejected"])
            return SafetyCheckResult(
                passed=False,
                check_name="RiskPolicy",
                details=f"RiskPolicy v1.0 REJECTED {action} ${amount_usd:,.0f} on {protocol}: {reasons}",
                blocking=True,
                severity="ERROR",
                value=reasons,
                threshold="v1.0 policy",
            )

        return SafetyCheckResult(
            passed=True,
            check_name="RiskPolicy",
            details=(
                f"RiskPolicy v1.0 PASS — {action} ${amount_usd:,.0f} on {protocol} "
                f"(tier={tier}, apy={current_apy:.2f}%, tvl=${tvl_usd:,.0f})"
            ),
            blocking=True,
            severity="INFO",
            value=amount_usd,
            threshold="v1.0 policy",
        )

    def check_gas_reasonable(
        self,
        gas_cost_usd: float,
        amount_usd:   float,
    ) -> SafetyCheckResult:
        """
        Verify gas cost is less than 2% of the transaction value.

        Small transactions are gas-uneconomical on mainnet and should be batched
        or delayed until gas prices fall.

        Args:
            gas_cost_usd: Estimated gas cost in USD (from SPAWallet.estimate_gas)
            amount_usd:   Transaction value in USD

        Returns:
            SafetyCheckResult (blocking=True)
        """
        if amount_usd <= 0:
            return SafetyCheckResult(
                passed=False,
                check_name="Gas Reasonableness",
                details="amount_usd must be > 0",
                blocking=True,
                severity="ERROR",
                value=amount_usd,
                threshold=f"< {GAS_MAX_PCT_OF_TRADE}% of trade",
            )

        gas_pct = (gas_cost_usd / amount_usd) * 100

        if gas_pct < GAS_MAX_PCT_OF_TRADE:
            return SafetyCheckResult(
                passed=True,
                check_name="Gas Reasonableness",
                details=(
                    f"Gas ${gas_cost_usd:.2f} = {gas_pct:.2f}% of trade "
                    f"(threshold: < {GAS_MAX_PCT_OF_TRADE}%)"
                ),
                blocking=True,
                severity="INFO",
                value=round(gas_pct, 3),
                threshold=GAS_MAX_PCT_OF_TRADE,
            )
        else:
            return SafetyCheckResult(
                passed=False,
                check_name="Gas Reasonableness",
                details=(
                    f"Gas ${gas_cost_usd:.2f} = {gas_pct:.2f}% of trade — exceeds "
                    f"{GAS_MAX_PCT_OF_TRADE}% threshold. Delay or batch this transaction."
                ),
                blocking=True,
                severity="ERROR",
                value=round(gas_pct, 3),
                threshold=GAS_MAX_PCT_OF_TRADE,
            )

    def check_simulation_passes(
        self,
        simulation_result: dict,
    ) -> SafetyCheckResult:
        """
        Verify the Tenderly (or local) simulation succeeded.

        The caller must obtain a simulation result from SPAWallet.simulate_transaction()
        first, then pass it here. A failed simulation is a hard block.

        Args:
            simulation_result: Dict returned by SPAWallet.simulate_transaction()

        Returns:
            SafetyCheckResult (blocking=True)
        """
        success  = simulation_result.get("success", False)
        sim_mode = simulation_result.get("mode", "unknown")
        error    = simulation_result.get("error")
        sim_id   = simulation_result.get("sim_id")

        if success:
            detail = f"Simulation PASSED (mode: {sim_mode})"
            if sim_id:
                detail += f", Tenderly ID: {sim_id}"
            return SafetyCheckResult(
                passed=True,
                check_name="Transaction Simulation",
                details=detail,
                blocking=True,
                severity="INFO",
                value=sim_mode,
                threshold="must succeed",
            )
        else:
            return SafetyCheckResult(
                passed=False,
                check_name="Transaction Simulation",
                details=f"Simulation FAILED (mode: {sim_mode}): {error or 'unknown error'}",
                blocking=True,
                severity="ERROR",
                value=error,
                threshold="must succeed",
            )

    def check_amount_requires_multisig(
        self,
        amount_usd: float,
    ) -> SafetyCheckResult:
        """
        Determine whether the transaction requires Gnosis Safe multisig approval.

        Amounts > $500 must be routed through the Gnosis Safe. This check is
        INFORMATIONAL (not blocking) — it tells the caller which execution path to use.

        Args:
            amount_usd: Transaction value in USD

        Returns:
            SafetyCheckResult where:
              passed=True  → auto-execute via hot wallet (amount ≤ $500)
              passed=False → must queue in Gnosis Safe (amount > $500)
              blocking=False always — this is routing information, not a block
        """
        if amount_usd <= MULTISIG_THRESHOLD_USD:
            return SafetyCheckResult(
                passed=True,
                check_name="Multisig Routing",
                details=(
                    f"${amount_usd:,.0f} ≤ ${MULTISIG_THRESHOLD_USD:,.0f} threshold — "
                    f"auto-execute via hot wallet"
                ),
                blocking=False,
                severity="INFO",
                value=amount_usd,
                threshold=MULTISIG_THRESHOLD_USD,
            )
        else:
            return SafetyCheckResult(
                passed=False,
                check_name="Multisig Routing",
                details=(
                    f"${amount_usd:,.0f} > ${MULTISIG_THRESHOLD_USD:,.0f} threshold — "
                    f"must route through Gnosis Safe multisig"
                ),
                blocking=False,    # not a block — just determines execution path
                severity="INFO",
                value=amount_usd,
                threshold=MULTISIG_THRESHOLD_USD,
            )

    def check_not_in_kill_switch(
        self,
        portfolio_state:       dict,
        max_drawdown_stop:     float = 0.05,
        action:                str   = "supply",
    ) -> SafetyCheckResult:
        """
        Verify the portfolio is not in kill-switch territory — CONVERGED onto the
        ONE canonical governance source of truth (WS-B1/B2, ADR-049).

        This NO LONGER applies a private flat ``max_drawdown_stop`` hard-block nor
        a process-local ``_kill_switch_active`` boolean. Instead it consults:

          1. **Persisted manual kill** — ``data/kill_switch_active.json`` via the
             governance lifecycle (survives a process restart; file absent = OFF;
             ``active=False`` = explicitly OFF). Active → BLOCK all.
          2. **Governance TWO-TIER drawdown ladder** (ADR-034 + ADR-048) — the
             SAME constants and the SAME shared classifier
             ``governance.kill_switch.classify_drawdown_pct``:
               • ``TIER_NONE``      (drawdown < 5%)        → PASS
               • ``TIER_SOFT_DERISK`` ([5%, 10%))          → block NEW / INCREASING
                 exposure ONLY (``supply``); HOLD / REDUCE (``withdraw``) is
                 ALLOWED — this is a de-risk, not an all-cash kill.
               • ``TIER_HARD_KILL`` (drawdown ≥ 10%)        → block ALL.

        The execution verdict on a given drawdown therefore EQUALS the governance
        ``drawdown_tier()`` verdict on the same equity (no divergence) — both go
        through ``classify_drawdown_pct``.

        ``max_drawdown_stop`` is RETAINED in the signature for call-site
        compatibility but is **no longer the threshold** (the owner-set 5%/10%
        governance constants are). It is ignored for the verdict; passing it has
        no effect on which tier fires.

        Args:
            portfolio_state:   Portfolio state dict (reads ``total_drawdown_pct``,
                               a FRACTION e.g. 0.06 == 6%).
            max_drawdown_stop: DEPRECATED / ignored for the verdict (kept for
                               signature compatibility).
            action:            ``"supply"`` (increases exposure — blocked by SOFT)
                               or ``"withdraw"`` (reduces exposure — allowed by
                               SOFT). Anything not recognised as a reduction is
                               treated as increasing exposure (fail-CLOSED).

        Returns:
            SafetyCheckResult (blocking=True)
        """
        # ── 1. Persisted manual kill (survives restart) ──────────────────────
        manual_active, manual_reason = _read_persisted_manual_kill()
        if manual_active:
            return SafetyCheckResult(
                passed=False,
                check_name="Kill Switch",
                details=(
                    f"Manual kill switch is ACTIVE (persisted governance state): "
                    f"{manual_reason}. No new transactions permitted."
                ),
                blocking=True,
                severity="ERROR",
                value="manual",
                threshold="kill switch inactive",
            )

        # ── 2. Governance TWO-TIER drawdown ladder (same constants) ──────────
        try:
            drawdown_frac = float(portfolio_state.get("total_drawdown_pct", 0.0) or 0.0)
        except (TypeError, ValueError) as exc:
            # Non-numeric drawdown must NOT silently pass — propagate (fail-CLOSED).
            raise ValueError(
                f"total_drawdown_pct is not numeric: "
                f"{portfolio_state.get('total_drawdown_pct')!r}"
            ) from exc

        # Drawdown is stored as a FRACTION; governance classifies a PERCENTAGE.
        drawdown_pct = drawdown_frac * 100.0
        tier, tier_reason = _gov_classify_drawdown_pct(drawdown_pct)

        # A reduction (withdraw / close) reduces exposure → allowed under SOFT.
        is_reduction = str(action).strip().lower() in ("withdraw", "redeem", "close", "reduce", "exit")

        if tier == _GOV_TIER_HARD:
            return SafetyCheckResult(
                passed=False,
                check_name="Kill Switch",
                details=(
                    f"HARD kill (governance ADR-048): {tier_reason}. ALL "
                    f"transactions blocked → all-cash. See docs/emergency.md."
                ),
                blocking=True,
                severity="ERROR",
                value=drawdown_frac,
                threshold=_GOV_HARD_PCT / 100.0,
            )

        if tier == _GOV_TIER_SOFT:
            if is_reduction:
                # SOFT de-risk permits REDUCING exposure (hold / withdraw).
                return SafetyCheckResult(
                    passed=True,
                    check_name="Kill Switch",
                    details=(
                        f"SOFT de-risk (governance ADR-034): {tier_reason}. "
                        f"Reducing/closing action '{action}' ALLOWED (de-risk, "
                        f"not all-cash)."
                    ),
                    blocking=True,
                    severity="WARN",
                    value=drawdown_frac,
                    threshold=_GOV_SOFT_PCT / 100.0,
                )
            return SafetyCheckResult(
                passed=False,
                check_name="Kill Switch",
                details=(
                    f"SOFT de-risk (governance ADR-034): {tier_reason}. New / "
                    f"increasing-exposure action '{action}' BLOCKED (hold / "
                    f"reduce only)."
                ),
                blocking=True,
                severity="ERROR",
                value=drawdown_frac,
                threshold=_GOV_SOFT_PCT / 100.0,
            )

        # TIER_NONE → no action.
        return SafetyCheckResult(
            passed=True,
            check_name="Kill Switch",
            details=(
                f"No kill switch active. {tier_reason} "
                f"(governance two-tier ladder: SOFT={_GOV_SOFT_PCT}%, "
                f"HARD={_GOV_HARD_PCT}%)."
            ),
            blocking=True,
            severity="INFO",
            value=drawdown_frac,
            threshold=_GOV_SOFT_PCT / 100.0,
        )

    def check_rate_limit(self) -> SafetyCheckResult:
        """
        Enforce a maximum of 3 transactions per rolling hour.

        This prevents runaway agent loops from submitting an unlimited number of
        transactions. The window is rolling (not fixed hourly bucket).

        Returns:
            SafetyCheckResult (blocking=True)
        """
        global _tx_timestamps

        now = time.time()
        window_start = now - _RATE_LIMIT_WINDOW_SECONDS

        # Purge timestamps outside the rolling window
        _tx_timestamps = [ts for ts in _tx_timestamps if ts >= window_start]
        current_count = len(_tx_timestamps)

        if current_count < _RATE_LIMIT_MAX_TX:
            return SafetyCheckResult(
                passed=True,
                check_name="Rate Limit",
                details=(
                    f"{current_count}/{_RATE_LIMIT_MAX_TX} transactions in last hour. "
                    f"Rate limit not reached."
                ),
                blocking=True,
                severity="INFO",
                value=current_count,
                threshold=_RATE_LIMIT_MAX_TX,
            )
        else:
            oldest_in_window = min(_tx_timestamps)
            retry_in_seconds = int(oldest_in_window + _RATE_LIMIT_WINDOW_SECONDS - now)
            return SafetyCheckResult(
                passed=False,
                check_name="Rate Limit",
                details=(
                    f"Rate limit reached: {current_count}/{_RATE_LIMIT_MAX_TX} transactions "
                    f"in last hour. Retry in {retry_in_seconds}s."
                ),
                blocking=True,
                severity="ERROR",
                value=current_count,
                threshold=_RATE_LIMIT_MAX_TX,
            )

    def record_transaction(self) -> None:
        """
        Record a successful transaction submission in the rate limit tracker.
        Call this AFTER a transaction is submitted, not before.
        """
        _tx_timestamps.append(time.time())

    # ── Kill switch control ───────────────────────────────────────────────────

    @staticmethod
    def activate_kill_switch(reason: str = "Manual activation") -> None:
        """
        Manually activate the kill switch — PERSISTED (WS-B2, ADR-049).

        Writes the canonical ``data/kill_switch_active.json`` via the governance
        lifecycle so the activation SURVIVES a process restart (a crash must NOT
        silently reset the kill). All subsequent transactions are blocked until
        :meth:`deactivate_kill_switch` is called.

        Args:
            reason: Human-readable reason for activation (recorded + logged)
        """
        global _kill_switch_active
        _kill_switch_active = True  # deprecated advisory shim (not authoritative)
        from spa_core.governance.kill_switch import KillSwitchChecker
        KillSwitchChecker(data_dir=_resolve_data_dir()).activate_kill_switch(reason)
        print(f"[KILL SWITCH ACTIVATED] {datetime.now(timezone.utc).isoformat()} — {reason}")

    @staticmethod
    def deactivate_kill_switch(reason: str = "Manual deactivation by owner") -> None:
        """
        Deactivate the kill switch — clears the PERSISTED state (WS-B2, ADR-049).

        Removes ``data/kill_switch_active.json`` via the governance lifecycle.
        CAUTION: Only call after reviewing positions and resolving the root cause.

        Args:
            reason: Human-readable reason for deactivation (must be owner-initiated)
        """
        global _kill_switch_active
        _kill_switch_active = False  # deprecated advisory shim (not authoritative)
        from spa_core.governance.kill_switch import KillSwitchChecker
        KillSwitchChecker(data_dir=_resolve_data_dir()).deactivate_kill_switch()
        print(f"[KILL SWITCH DEACTIVATED] {datetime.now(timezone.utc).isoformat()} — {reason}")

    @staticmethod
    def is_kill_switch_active() -> bool:
        """Returns True iff the PERSISTED manual kill switch is active.

        Reads the canonical ``data/kill_switch_active.json`` (governance
        lifecycle) — NOT the deprecated process-local flag — so the answer is
        consistent across restarts. Fail-CLOSED: an unreadable persisted state is
        reported as ACTIVE.
        """
        active, _reason = _read_persisted_manual_kill()
        return active

    # ── Full pipeline ─────────────────────────────────────────────────────────

    def run_all(
        self,
        protocol:          str,
        action:            str,
        amount_usd:        float,
        portfolio_state:   dict,
        gas_cost_usd:      Optional[float] = None,
        simulation_result: Optional[dict]  = None,
        max_drawdown_stop: float = 0.05,
        current_apy:       Optional[float] = None,
        tvl_usd:           Optional[float] = None,
        tier:              Optional[str]   = None,
    ) -> SafetyPipelineResult:
        """
        Run the full pre-execution safety pipeline.

        Executes all checks in order. If a blocking check fails, subsequent checks
        are still run (for logging completeness), but the result will have
        `blocked=True` and `all_passed=False`.

        The caller MUST check `pipeline.blocked` before submitting any transaction.
        If `pipeline.requires_multisig` is True, route through Gnosis Safe.

        Args:
            protocol:          Protocol key (e.g. "aave-v3")
            action:            Action type ("supply" | "withdraw")
            amount_usd:        Transaction value in USD
            portfolio_state:   Portfolio state dict (from data/status.json or on-chain)
            gas_cost_usd:      Gas cost estimate in USD (from SPAWallet.estimate_gas)
                               If None, gas check is skipped with a WARN result
            simulation_result: Result from SPAWallet.simulate_transaction()
                               If None, simulation check is skipped with a WARN result
            max_drawdown_stop: Kill switch drawdown threshold (default 0.05 = 5%)
            current_apy:       Live APY (PERCENT) for the protocol. If None the
                               RiskPolicy stage fetches it from the live adapter
                               feed; if that is unavailable the stage FAILS CLOSED.
            tvl_usd:           Live pool TVL (USD). Same fetch / fail-closed rule.
            tier:              Risk tier override; resolved from the registry if None.

        Returns:
            SafetyPipelineResult with all check results and routing decision
        """
        checks: list[SafetyCheckResult] = []

        # 1. Kill switch — checked first, highest priority. The action is passed
        # so the SOFT de-risk tier blocks only NEW/increasing exposure (supply),
        # while a reducing action (withdraw) is permitted under SOFT.
        checks.append(
            self.check_not_in_kill_switch(portfolio_state, max_drawdown_stop, action=action)
        )

        # 2. Rate limit
        checks.append(self.check_rate_limit())

        # 3. RiskPolicy — the real deterministic policy is consulted here.
        checks.append(
            self.check_risk_policy(
                protocol, action, amount_usd, portfolio_state,
                current_apy=current_apy, tvl_usd=tvl_usd, tier=tier,
            )
        )

        # 4. Transaction simulation
        if simulation_result is not None:
            checks.append(self.check_simulation_passes(simulation_result))
        else:
            checks.append(SafetyCheckResult(
                passed=False,
                check_name="Transaction Simulation",
                details="Simulation result not provided — skipping. Run SPAWallet.simulate_transaction() first.",
                blocking=True,
                severity="WARN",
                value=None,
                threshold="must succeed",
            ))

        # 5. Gas reasonableness
        if gas_cost_usd is not None:
            checks.append(self.check_gas_reasonable(gas_cost_usd, amount_usd))
        else:
            checks.append(SafetyCheckResult(
                passed=True,
                check_name="Gas Reasonableness",
                details="Gas cost not provided — skipping check (simulation mode).",
                blocking=False,
                severity="WARN",
                value=None,
                threshold=f"< {GAS_MAX_PCT_OF_TRADE}%",
            ))

        # 6. Multisig routing (informational — not blocking)
        checks.append(self.check_amount_requires_multisig(amount_usd))

        return SafetyPipelineResult.from_checks(checks)
