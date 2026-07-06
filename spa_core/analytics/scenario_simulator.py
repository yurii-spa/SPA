#!/usr/bin/env python3
"""Scenario Simulator — portfolio stress-testing via historical and
hypothetical scenarios (SPA-V509 / MP-586).

Applies APY shocks, TVL shocks, and peg-break events to a portfolio snapshot
to estimate portfolio returns under stress, identify risk-limit breaches, and
surface advisory warnings.

Design constraints
------------------
* Pure stdlib + math — no numpy / scipy / requests / web3 / pandas.
* Advisory only — never touches allocator / risk / execution.
* Strictly read-only except :meth:`ScenarioSimulator.save_report` which writes
  atomically (tmp + ``os.replace``) to ``data/scenario_report.json``.
* LLM_FORBIDDEN: NOT imported from risk / execution / monitoring.

Scenario schema
---------------
A scenario is a plain ``dict``::

    {
        "name":        str,                      # human-readable name
        "description": str,                      # optional
        "apy_shocks":  {key: multiplier},        # APY × multiplier per adapter/group
        "tvl_shocks":  {key: multiplier},        # TVL × multiplier per adapter/group
        "peg_breaks":  [key, ...],               # adapters that depeg (large loss)
    }

Wildcard keys accepted in ``apy_shocks``, ``tvl_shocks``, ``peg_breaks``
-------------------------------------------------------------------------
* ``"*"``       — all adapters.
* ``"T1"``      — Tier-1 adapters.
* ``"T2"``      — Tier-2 adapters.
* ``"T3"``      — Tier-3 adapters.
* ``"mainnet"`` — Ethereum mainnet adapters (chain empty or "ethereum"/"eth").
* ``"usdc"``    — USDC-based adapters (adapter_id or chain contains "usdc").
* ``"l2"``      — L2 adapters (chain contains arbitrum / optimism / base / polygon).

A specific ``adapter_id`` key overrides any wildcard for that adapter.
Multiple non-overridden wildcards are compounded (multiplied together).

Peg-break return model
----------------------
A peg break is modelled as a ``-50 %`` capital return on that adapter,
regardless of its stated APY. This conservative assumption covers a severe
but not complete depeg event.

Risk limits applied (from RiskPolicy v1.0)
------------------------------------------
* TVL floor:            shocked TVL ≥ $5M per active pool.
* Per-protocol cap:     T1 ≤ 40 %, T2/T3 ≤ 20 % of portfolio.
* T2/T3 total cap:      combined T2 + T3 weight ≤ 50 %.
* Kill switch:          shocked portfolio return ≤ −5 %.

CLI (offline, exit 0 always)::

    python3 -m spa_core.analytics.scenario_simulator --check    # print report, no write
    python3 -m spa_core.analytics.scenario_simulator --run      # print + atomic write
    python3 -m spa_core.analytics.scenario_simulator --run --data-dir <dir>

Scope / safety: STRICTLY READ-ONLY (SPA-BL-011) and advisory. Pure stdlib +
math (json / os / math / datetime / argparse / tempfile / logging / pathlib /
dataclasses / typing) — no requests / web3 / LLM SDK / sockets / network.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from spa_core.utils.atomic import atomic_save
from spa_core.adapters.tier_map import tier_of  # canonical tier (registry-hygiene)

log = logging.getLogger("spa.analytics.scenario_simulator")

_REPO_ROOT = Path(__file__).resolve().parents[3]  # spa_core/analytics/ → repo root
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

SCHEMA_VERSION: int = 1
SOURCE_NAME: str = "scenario_simulator"
STATUS_FILENAME: str = "scenario_report.json"
HISTORY_MAX: int = 90  # run-history ring-buffer size

# ── Risk-policy constants (RiskPolicy v1.0 — read-only mirror) ───────────────
TVL_FLOOR_USD: float = 5_000_000.0   # $5M minimum per pool
T1_CAP: float = 0.40                  # 40% per T1 protocol
T2_T3_CAP: float = 0.20              # 20% per T2/T3 protocol
T2_TOTAL_CAP: float = 0.50           # 50% T2+T3 combined
KILL_SWITCH_PCT: float = -5.0        # portfolio return ≤ −5% → kill switch
APY_EXTREME_WARN_MULT: float = 3.0   # warn when shocked APY > 3× APY_MAX_PCT

# Reasonable APY bounds (RiskPolicy new-position gate mirrors)
APY_MIN_PCT: float = 1.0
APY_MAX_PCT: float = 30.0

# Peg-break instantaneous capital loss
PEG_BREAK_RETURN_PCT: float = -50.0

DISCLAIMER: str = "NOT investment advice"

# Known wildcard keys (case-insensitive)
_WILDCARD_KEYS: frozenset = frozenset(
    {"*", "t1", "t2", "t3", "mainnet", "usdc", "l2"}
)

# L2 chain identifiers
_L2_CHAINS: frozenset = frozenset(
    {"arbitrum", "optimism", "base", "polygon", "l2", "op mainnet", "arb"}
)


# ─── ScenarioResult ───────────────────────────────────────────────────────────

@dataclass
class ScenarioResult:
    """Outcome of running one stress scenario against a portfolio."""

    scenario_name: str
    portfolio_return_pct: float
    worst_adapter: str      # adapter_id with the lowest shocked return
    best_adapter: str       # adapter_id with the highest shocked return
    breached_limits: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict (JSON-safe)."""
        return {
            "scenario_name": self.scenario_name,
            "portfolio_return_pct": round(self.portfolio_return_pct, 6),
            "worst_adapter": self.worst_adapter,
            "best_adapter": self.best_adapter,
            "breached_limits": list(self.breached_limits),
            "warnings": list(self.warnings),
        }


# ─── Low-level helpers ────────────────────────────────────────────────────────

class _Missing:
    """Sentinel for absent attributes."""


_MISSING = _Missing()


def _safe_float(v: Any, default: float = 0.0) -> float:
    """Convert *v* to float; return *default* on failure, NaN, or Inf."""
    if isinstance(v, bool):
        return float(v)
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def _get_attr(obj: Any, *keys: str, default: Any = None) -> Any:
    """Try each key in order on a dict or object; return *default* if none found."""
    for k in keys:
        if isinstance(obj, dict):
            if k in obj:
                return obj[k]
        else:
            val = getattr(obj, k, _MISSING)
            if not isinstance(val, _Missing):
                return val
    return default


def _get_adapter_id(adapter: Any) -> str:
    return str(_get_attr(adapter, "adapter_id", "id", "protocol_id", "name", default="unknown"))


def _get_adapter_tier(adapter: Any) -> str:
    """Normalise tier to one of T1 / T2 / T3 (default T2)."""
    raw = str(_get_attr(adapter, "tier", "adapter_tier", default="T2")).strip().upper()
    if raw in ("T1", "TIER1", "TIER 1", "1"):
        return "T1"
    if raw in ("T3", "TIER3", "TIER 3", "3"):
        return "T3"
    return "T2"


def _get_adapter_apy_pct(adapter: Any) -> float:
    """Return APY as a *percentage* (e.g. 3.5 for 3.5%).

    If the stored value is in [−1, 1] it is assumed to be a decimal fraction
    and is multiplied by 100.
    """
    raw = _safe_float(
        _get_attr(adapter, "apy", "apy_pct", "current_apy", default=0.0), 0.0
    )
    if -1.0 <= raw <= 1.0:
        return raw * 100.0
    return raw


def _get_adapter_tvl(adapter: Any) -> float:
    return _safe_float(
        _get_attr(adapter, "tvl", "tvl_usd", "total_value_locked", default=0.0), 0.0
    )


def _get_adapter_chain(adapter: Any) -> str:
    return str(_get_attr(adapter, "chain", "network", "chain_id", default="")).lower().strip()


# ─── Shock matching helpers ───────────────────────────────────────────────────

def _is_wildcard_key(key: str) -> bool:
    """Return True if *key* is a recognised wildcard (not an adapter ID)."""
    return key.strip().lower() in _WILDCARD_KEYS


def _matches_wildcard(key: str, adapter: Any) -> bool:
    """Return True if *adapter* matches wildcard *key*.

    Only call this for keys that pass :func:`_is_wildcard_key`.
    """
    wc = key.strip().lower()
    if wc == "*":
        return True

    tier = _get_adapter_tier(adapter)
    if wc == "t1":
        return tier == "T1"
    if wc == "t2":
        return tier == "T2"
    if wc == "t3":
        return tier == "T3"

    adapter_id = _get_adapter_id(adapter).lower()
    chain = _get_adapter_chain(adapter)

    if wc == "usdc":
        return "usdc" in adapter_id or "usdc" in chain

    if wc == "mainnet":
        # Match adapters explicitly on Ethereum mainnet or with no chain set
        # (L2 adapters should declare their chain; mainnet adapters often don't)
        return chain in ("ethereum", "mainnet", "eth", "") and not any(
            l2 in chain for l2 in _L2_CHAINS
        )

    if wc == "l2":
        return any(l2 in chain for l2 in _L2_CHAINS)

    return False  # pragma: no cover — exhaustive set already handled above


def _compute_shock_multiplier(
    adapter: Any,
    shocks: Dict[str, Any],
) -> float:
    """Return the shock multiplier for *adapter* given the shocks dict.

    Resolution order
    ----------------
    1. Exact ``adapter_id`` match → return that multiplier immediately.
    2. Recognised wildcard keys → compound (multiply) all matching wildcards.
    3. No match → 1.0 (no shock).
    """
    if not shocks:
        return 1.0

    adapter_id_lower = _get_adapter_id(adapter).lower()

    # Exact match overrides everything
    for key, mult in shocks.items():
        if key.lower() == adapter_id_lower:
            return _safe_float(mult, 1.0)

    # Compound wildcard matches
    accumulated = 1.0
    applied = False
    for key, mult in shocks.items():
        if _is_wildcard_key(key) and _matches_wildcard(key, adapter):
            accumulated *= _safe_float(mult, 1.0)
            applied = True

    return accumulated if applied else 1.0


def _applies_peg_break(adapter: Any, peg_breaks: List[str]) -> bool:
    """Return True if *adapter* is targeted by any entry in *peg_breaks*."""
    adapter_id_lower = _get_adapter_id(adapter).lower()
    for pb in peg_breaks:
        if pb.lower() == adapter_id_lower:
            return True
        if _is_wildcard_key(pb) and _matches_wildcard(pb, adapter):
            return True
    return False


def _normalise_weights(weights: Dict[str, Any]) -> Dict[str, float]:
    """Return weights normalised to sum = 1.0.

    Negative weights are clipped to 0. If the total is 0 after clipping,
    all adapters receive equal weight.
    """
    if not weights:
        return {}
    cleaned: Dict[str, float] = {
        k: max(0.0, _safe_float(v, 0.0)) for k, v in weights.items()
    }
    total = sum(cleaned.values())
    if total <= 0.0:
        n = len(cleaned)
        return {k: 1.0 / n for k in cleaned} if n > 0 else {}
    return {k: v / total for k, v in cleaned.items()}


# ─── ScenarioSimulator ────────────────────────────────────────────────────────

class ScenarioSimulator:
    """Stress-test a portfolio snapshot against named shock scenarios.

    Parameters
    ----------
    data_dir :
        Directory for :meth:`save_report`; defaults to ``<repo_root>/data``.
    """

    def __init__(self, data_dir: Optional[str] = None) -> None:
        self._data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR

    # ── Scenario catalogue ────────────────────────────────────────────────────

    @staticmethod
    def get_builtin_scenarios() -> List[Dict[str, Any]]:
        """Return the 7 built-in stress scenarios.

        Each scenario is a plain dict with keys: ``name``, ``description``,
        ``apy_shocks``, ``tvl_shocks``, ``peg_breaks``.
        """
        return [
            {
                "name": "defi_bear",
                "description": (
                    "DeFi bear market: all protocol APYs compressed −50 %, "
                    "TVL contracts −20 % as capital exits the space"
                ),
                "apy_shocks": {"*": 0.5},
                "tvl_shocks": {"*": 0.8},
                "peg_breaks": [],
            },
            {
                "name": "usdc_depeg",
                "description": (
                    "USDC depeg event: USDC-based adapters suffer large capital "
                    "impairment (peg break −50 %), TVL on USDC pools collapses "
                    "−70 %, overall APYs collapse −70 % during panic"
                ),
                "apy_shocks": {"*": 0.3},
                "tvl_shocks": {"usdc": 0.3, "*": 0.85},
                "peg_breaks": ["usdc"],
            },
            {
                "name": "eth_crash",
                "description": (
                    "ETH crash: mainnet TVL falls −60 % in USD terms as ETH "
                    "price collapses; mainnet APYs compressed −40 %, T1 "
                    "lending APYs fall −25 %"
                ),
                "apy_shocks": {"mainnet": 0.6, "T1": 0.75},
                "tvl_shocks": {"mainnet": 0.4},
                "peg_breaks": [],
            },
            {
                "name": "rate_spike",
                "description": (
                    "Interest-rate spike: traditional rate hike drives borrow "
                    "demand into T1 lending; T1 APYs triple (+200 %), "
                    "T2 APYs increase +50 %"
                ),
                "apy_shocks": {"T1": 3.0, "T2": 1.5},
                "tvl_shocks": {"T1": 1.1},
                "peg_breaks": [],
            },
            {
                "name": "black_swan",
                "description": (
                    "Black-swan / systemic contagion: APYs collapse −80 %, "
                    "TVL −70 % across all protocols; severe portfolio impairment"
                ),
                "apy_shocks": {"*": 0.2},
                "tvl_shocks": {"*": 0.3},
                "peg_breaks": [],
            },
            {
                "name": "regulatory_shock",
                "description": (
                    "Regulatory crackdown: T2/T3 protocols halted or restricted; "
                    "T1 APYs halved; T2 TVL −80 %, T3 TVL −90 %"
                ),
                "apy_shocks": {"T1": 0.5, "T2": 0.1, "T3": 0.05},
                "tvl_shocks": {"T2": 0.2, "T3": 0.1},
                "peg_breaks": [],
            },
            {
                "name": "liquidity_crisis",
                "description": (
                    "Liquidity crisis: TVL −40 % across all; T2 APY spike "
                    "+150 % as risk premium surges; T1 APYs up +30 %; "
                    "T3 APYs halved as exotic pools dry up"
                ),
                "apy_shocks": {"T1": 1.3, "T2": 2.5, "T3": 0.5},
                "tvl_shocks": {"*": 0.6},
                "peg_breaks": [],
            },
        ]

    # ── Single scenario execution ─────────────────────────────────────────────

    def run_scenario(
        self,
        scenario: Dict[str, Any],
        weights: Dict[str, float],
        adapters: List[Any],
    ) -> ScenarioResult:
        """Run one scenario and return a :class:`ScenarioResult`.

        Parameters
        ----------
        scenario :
            Scenario definition dict (name, apy_shocks, tvl_shocks, peg_breaks).
        weights :
            ``{adapter_id: weight}`` mapping (any positive scale; normalised
            internally).  Keys must match adapter IDs in *adapters*.
        adapters :
            List of adapter dicts or objects providing ``adapter_id`` / ``apy``
            / ``tvl`` / ``tier`` attributes.

        Returns
        -------
        ScenarioResult
            Shocked portfolio return, extremes, breaches, and warnings.

        Never raises; degenerate input → zero return + warnings.
        """
        name = str(scenario.get("name") or "unnamed_scenario")
        apy_shocks: Dict[str, float] = dict(scenario.get("apy_shocks") or {})
        tvl_shocks: Dict[str, float] = dict(scenario.get("tvl_shocks") or {})
        peg_breaks: List[str] = list(scenario.get("peg_breaks") or [])

        warnings_out: List[str] = []
        breached_limits: List[str] = []

        # ── Degenerate input guards ──────────────────────────────────────────
        if not adapters:
            warnings_out.append("No adapters provided; portfolio return is 0 %")
            return ScenarioResult(
                scenario_name=name,
                portfolio_return_pct=0.0,
                worst_adapter="",
                best_adapter="",
                breached_limits=[],
                warnings=warnings_out,
            )

        # ── Per-adapter shocked return and TVL ───────────────────────────────
        adapter_shocked_return: Dict[str, float] = {}
        adapter_shocked_apy: Dict[str, float] = {}
        adapter_shocked_tvl: Dict[str, float] = {}
        adapter_tier_map: Dict[str, str] = {}

        for adapter in adapters:
            aid = _get_adapter_id(adapter)
            base_apy = _get_adapter_apy_pct(adapter)
            base_tvl = _get_adapter_tvl(adapter)
            tier = _get_adapter_tier(adapter)

            apy_mult = _compute_shock_multiplier(adapter, apy_shocks)
            tvl_mult = _compute_shock_multiplier(adapter, tvl_shocks)

            shocked_apy = base_apy * apy_mult
            shocked_tvl = base_tvl * tvl_mult

            # Peg break overrides APY return with a capital-loss figure
            if _applies_peg_break(adapter, peg_breaks):
                shocked_return = PEG_BREAK_RETURN_PCT
                warnings_out.append(
                    f"Peg break applied to '{aid}': "
                    f"return set to {PEG_BREAK_RETURN_PCT:.1f} %"
                )
            else:
                shocked_return = shocked_apy

            adapter_shocked_return[aid] = shocked_return
            adapter_shocked_apy[aid] = shocked_apy
            adapter_shocked_tvl[aid] = shocked_tvl
            adapter_tier_map[aid] = tier

        # ── Portfolio-return calculation ──────────────────────────────────────
        norm_weights = _normalise_weights(weights)

        # Restrict to adapters present in both weights and adapters list
        common_ids = set(norm_weights.keys()) & set(adapter_shocked_return.keys())

        if not common_ids and weights:
            warnings_out.append(
                "No overlap between weights keys and adapter IDs; "
                "portfolio return is 0 %"
            )

        # Re-normalise over common IDs (handles partial overlap gracefully)
        sub_weights = {k: norm_weights[k] for k in common_ids}
        sub_total = sum(sub_weights.values())
        if sub_total > 0.0:
            sub_weights = {k: v / sub_total for k, v in sub_weights.items()}

        portfolio_return = sum(
            sub_weights.get(aid, 0.0) * adapter_shocked_return[aid]
            for aid in common_ids
        )

        # ── Extremes ─────────────────────────────────────────────────────────
        worst_adapter = ""
        best_adapter = ""
        if adapter_shocked_return:
            worst_adapter = min(
                adapter_shocked_return, key=lambda k: adapter_shocked_return[k]
            )
            best_adapter = max(
                adapter_shocked_return, key=lambda k: adapter_shocked_return[k]
            )

        # ── Risk-limit checks ────────────────────────────────────────────────

        # 1. TVL floor — only check adapters active in the portfolio
        for aid in common_ids:
            st = adapter_shocked_tvl.get(aid, 0.0)
            if st == 0.0:
                warnings_out.append(
                    f"TVL unknown/zero for '{aid}'; TVL floor check skipped"
                )
            elif st < TVL_FLOOR_USD:
                breached_limits.append(
                    f"TVL floor breach: '{aid}' shocked TVL "
                    f"${st:,.0f} < ${TVL_FLOOR_USD:,.0f}"
                )

        # 2. Per-protocol and T2/T3 total cap
        t2_t3_total = 0.0
        for aid, w in sub_weights.items():
            tier = tier_of(aid) or adapter_tier_map.get(aid, "T2")  # canonical first, local fallback, then T2
            if tier == "T1":
                cap = T1_CAP
            else:
                cap = T2_T3_CAP
                t2_t3_total += w

            if w > cap + 1e-9:  # small epsilon to avoid float noise
                breached_limits.append(
                    f"Per-protocol cap breach: '{aid}' ({tier}) "
                    f"weight {w:.1%} > {cap:.0%}"
                )

        if t2_t3_total > T2_TOTAL_CAP + 1e-9:
            breached_limits.append(
                f"T2/T3 total cap breach: combined T2+T3 weight "
                f"{t2_t3_total:.1%} > {T2_TOTAL_CAP:.0%}"
            )

        # 3. Kill switch — shocked portfolio return too negative
        if portfolio_return <= KILL_SWITCH_PCT:
            breached_limits.append(
                f"Kill switch triggered: portfolio return "
                f"{portfolio_return:.2f} % ≤ {KILL_SWITCH_PCT:.0f} %"
            )

        # ── Advisory warnings ────────────────────────────────────────────────

        # Warn on extremely high shocked APYs (e.g. rate spike)
        extreme_apy_threshold = APY_MAX_PCT * APY_EXTREME_WARN_MULT
        for aid in common_ids:
            sapy = adapter_shocked_apy.get(aid, 0.0)
            if sapy > extreme_apy_threshold:
                warnings_out.append(
                    f"Extreme shocked APY for '{aid}': "
                    f"{sapy:.1f} % (>{extreme_apy_threshold:.0f} %)"
                )

        # Warn on severe portfolio return
        if portfolio_return < -10.0:
            warnings_out.append(
                f"Severe scenario: portfolio return "
                f"{portfolio_return:.2f} % < −10 %"
            )

        return ScenarioResult(
            scenario_name=name,
            portfolio_return_pct=round(portfolio_return, 6),
            worst_adapter=worst_adapter,
            best_adapter=best_adapter,
            breached_limits=breached_limits,
            warnings=warnings_out,
        )

    # ── Batch run ─────────────────────────────────────────────────────────────

    def run_all_scenarios(
        self,
        weights: Dict[str, float],
        adapters: List[Any],
    ) -> List[ScenarioResult]:
        """Run every built-in scenario and return a list of results."""
        return [
            self.run_scenario(sc, weights, adapters)
            for sc in self.get_builtin_scenarios()
        ]

    # ── Full simulation report ────────────────────────────────────────────────

    def get_simulation_report(
        self,
        weights: Dict[str, float],
        adapters: List[Any],
        custom_scenarios: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Run all built-in plus any custom scenarios and return a full report.

        Parameters
        ----------
        weights, adapters :
            Portfolio inputs (same semantics as :meth:`run_scenario`).
        custom_scenarios :
            Optional extra scenarios appended after the built-ins.

        Returns
        -------
        dict
            Keys: ``generated_at``, ``schema_version``, ``n_scenarios``,
            ``results``, ``worst_case``, ``best_case``, ``avg_return_pct``,
            ``scenarios_with_breaches``, ``scenarios_with_warnings``,
            ``custom_scenario_count``, ``disclaimer``.
        """
        all_scenarios: List[Dict[str, Any]] = list(self.get_builtin_scenarios())
        custom_count = 0
        if custom_scenarios:
            all_scenarios.extend(custom_scenarios)
            custom_count = len(custom_scenarios)

        results: List[ScenarioResult] = []
        for sc in all_scenarios:
            try:
                results.append(self.run_scenario(sc, weights, adapters))
            except Exception as exc:  # pragma: no cover – belt-and-braces
                results.append(
                    ScenarioResult(
                        scenario_name=str(sc.get("name", "unknown")),
                        portfolio_return_pct=0.0,
                        worst_adapter="",
                        best_adapter="",
                        breached_limits=[],
                        warnings=[f"Internal error: {exc}"],
                    )
                )

        timestamp = datetime.now(timezone.utc).isoformat()

        if not results:
            return {
                "generated_at": timestamp,
                "schema_version": SCHEMA_VERSION,
                "n_scenarios": 0,
                "results": [],
                "worst_case": None,
                "best_case": None,
                "avg_return_pct": 0.0,
                "scenarios_with_breaches": 0,
                "scenarios_with_warnings": 0,
                "custom_scenario_count": custom_count,
                "disclaimer": DISCLAIMER,
            }

        worst = min(results, key=lambda r: r.portfolio_return_pct)
        best = max(results, key=lambda r: r.portfolio_return_pct)
        avg = sum(r.portfolio_return_pct for r in results) / len(results)
        n_breaches = sum(1 for r in results if r.breached_limits)
        n_warnings = sum(1 for r in results if r.warnings)

        return {
            "generated_at": timestamp,
            "schema_version": SCHEMA_VERSION,
            "n_scenarios": len(results),
            "results": [r.to_dict() for r in results],
            "worst_case": worst.to_dict(),
            "best_case": best.to_dict(),
            "avg_return_pct": round(avg, 6),
            "scenarios_with_breaches": n_breaches,
            "scenarios_with_warnings": n_warnings,
            "custom_scenario_count": custom_count,
            "disclaimer": DISCLAIMER,
        }

    # ── Persistence ───────────────────────────────────────────────────────────

    def save_report(self, report: Dict[str, Any]) -> Path:
        """Atomically write *report* to ``data/scenario_report.json``.

        Maintains a ``history`` ring-buffer of up to :data:`HISTORY_MAX`
        previous runs inside the document.  Returns the path written.
        """
        out_path = self._data_dir / STATUS_FILENAME
        self._data_dir.mkdir(parents=True, exist_ok=True)

        # Load existing document for history accumulation
        existing: Dict[str, Any] = {}
        if out_path.exists():
            try:
                existing = json.loads(out_path.read_text(encoding="utf-8"))
            except Exception:
                existing = {}

        history: List[Dict[str, Any]] = list(existing.get("history", []))

        # Archive the previous report into history (excluding its own history)
        if existing:
            prev = {k: v for k, v in existing.items() if k != "history"}
            history.append(prev)
            if len(history) > HISTORY_MAX:
                history = history[-HISTORY_MAX:]

        document = dict(report)
        document["history"] = history


        # Atomic write: temp file → os.replace
        atomic_save(document, str(out_path))
        log.info("scenario_report written → %s", out_path)
        return out_path


# ─── CLI ──────────────────────────────────────────────────────────────────────

def _sample_portfolio():
    """Return (weights, adapters) for a demo CLI run."""
    adapters = [
        {
            "adapter_id": "aave_v3",
            "apy": 3.5,
            "tvl": 8_000_000_000.0,
            "tier": "T1",
            "chain": "ethereum",
        },
        {
            "adapter_id": "compound_v3",
            "apy": 4.8,
            "tvl": 3_000_000_000.0,
            "tier": "T1",
            "chain": "ethereum",
        },
        {
            "adapter_id": "morpho_steakhouse_usdc",
            "apy": 6.5,
            "tvl": 500_000_000.0,
            "tier": "T1",
            "chain": "ethereum",
        },
        {
            "adapter_id": "maple_usdc",
            "apy": 8.0,
            "tvl": 100_000_000.0,
            "tier": "T2",
            "chain": "ethereum",
        },
    ]
    weights = {a["adapter_id"]: 0.25 for a in adapters}
    return weights, adapters


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover
    parser = argparse.ArgumentParser(
        prog="spa_core.analytics.scenario_simulator",
        description="Portfolio scenario stress-tester (MP-586)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=True,
        help="Compute and print report — no write (default)",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        default=False,
        help="Compute, print, AND atomically write to data/",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Override data directory path",
    )
    args = parser.parse_args(argv)

    sim = ScenarioSimulator(data_dir=args.data_dir)
    weights, adapters = _sample_portfolio()
    report = sim.get_simulation_report(weights, adapters)

    printable = {k: v for k, v in report.items() if k != "history"}
    print(json.dumps(printable, indent=2, ensure_ascii=False))

    if args.run:
        out = sim.save_report(report)
        print(f"\n✅ Written → {out}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
