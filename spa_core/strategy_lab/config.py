"""
spa_core/strategy_lab/config.py — SINGLE SOURCE OF TRUTH loader for the Strategy Lab.

Reads data/strategy_lab_config.json and exposes:
  - load_config()        -> full validated dict (cached, fail-CLOSED on missing keys)
  - global_config()      -> the "global" block (capital, window, seed, cost params, rwa floor)
  - strategy_config(id)  -> a per-strategy config block (variant_n / variant_d / engine_* / rwa_floor)
  - risk_limits()        -> risk CAPS sourced from spa_core.risk.policy (NOT duplicated here)
  - rwa_floor_apy_pct()  -> the risk-free RWA benchmark rate: LIVE tokenized-T-bill yield
                            (spa_core.strategy_lab.data.rwa_feed) when available, else the
                            committed config literal as a conservative fallback.

Design rules:
  - stdlib-only, deterministic. LLM FORBIDDEN.
  - Atomic-safe reads (we only read; writes elsewhere use shutil.move temp→dst).
  - Fail-CLOSED: a missing required key raises ConfigError — never a silent default.
  - Risk LIMITS (TVL floor, concentration, drawdown stop, min cash) are NOT defined here.
    They are imported from spa_core.risk.policy (RiskConfig) so there is one source of truth.

RWA floor (2026-06-25): the floor every strategy must beat is the REAL tokenized-Treasury
yield (BUIDL/USYC/USDY/OUSG/USTB/TBILL — a ~$15B market at ~3.3–3.5%, per
docs/RESEARCH_EXPANSION_2026-06-25.md), NOT the old hardcoded 4.5%. rwa_floor_apy_pct() now
returns the live TVL-weighted rate from rwa_feed (cached, fresh). The literal kept in the JSON
is ONLY a conservative fail-safe used when the feed is unavailable (network down / cache empty)
— a backtest must never crash on a missing feed, so we fall back to the committed value.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

# Risk limits come from the canonical policy — never re-declared in the lab.
from spa_core.risk.policy import RiskConfig

# SSOT config. The committed default lives beside this module (version-controlled); an optional
# data/strategy_lab_config.json acts as a local runtime OVERRIDE (data/*.json is gitignored, so
# the committed copy is the source of truth a fresh clone uses).
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_COMMITTED_PATH = os.path.join(os.path.dirname(__file__), "strategy_lab_config.json")
_OVERRIDE_PATH = os.path.join(_REPO_ROOT, "data", "strategy_lab_config.json")
CONFIG_PATH = _OVERRIDE_PATH if os.path.exists(_OVERRIDE_PATH) else _COMMITTED_PATH

# Required schema (fail-closed). Keys that MUST be present after a load.
_REQUIRED_GLOBAL = (
    "initial_capital",
    "window_start",
    "window_end",
    "seed",
    "gas_usd_per_rebalance",
    "slippage_bps",
    "rebalance_bps",
    "funding_settles_per_day",
    "rwa_floor_apy_pct",
)
# Per-strategy required keys (the candidate thresholds X/Y/Z/N must exist).
_REQUIRED_STRATEGY: Dict[str, tuple] = {
    "variant_n": (
        "lrt_symbol",
        "hedge_ratio",
        "funding_kill_threshold",
        "funding_kill_hours",
        "lrt_depeg_kill_pct",
        "points_apy_assumption",
    ),
    "variant_d": (
        "lrt_symbol",
        "drawdown_kill_pct",
    ),
    "engine_a": ("capital_usd",),
    "engine_b": ("capital_usd",),
    "engine_c": ("capital_usd",),
    "rwa_floor": ("capital_usd", "apy_pct"),
}


class ConfigError(ValueError):
    """Raised when the SSOT config is missing a required key or is malformed (fail-CLOSED)."""


_CACHE: Optional[Dict[str, Any]] = None


def _validate(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Fail-CLOSED validation of the loaded config. Raises ConfigError on any missing key."""
    if not isinstance(cfg, dict):
        raise ConfigError("config root must be a JSON object")

    g = cfg.get("global")
    if not isinstance(g, dict):
        raise ConfigError("missing required 'global' block")
    for k in _REQUIRED_GLOBAL:
        if k not in g:
            raise ConfigError(f"global config missing required key: {k!r}")

    strategies = cfg.get("strategies")
    if not isinstance(strategies, dict):
        raise ConfigError("missing required 'strategies' block")
    for sid, required in _REQUIRED_STRATEGY.items():
        block = strategies.get(sid)
        if not isinstance(block, dict):
            raise ConfigError(f"strategies config missing required block: {sid!r}")
        for k in required:
            if k not in block:
                raise ConfigError(f"strategy {sid!r} missing required key: {k!r}")
    return cfg


def load_config(path: Optional[str] = None, force_reload: bool = False) -> Dict[str, Any]:
    """Load + validate the SSOT config. Cached after first read.

    Args:
        path: override config path (tests/hermetic). Bypasses + refreshes the cache.
        force_reload: re-read from disk even if cached.
    """
    global _CACHE
    p = path or CONFIG_PATH
    if _CACHE is not None and not force_reload and path is None:
        return _CACHE
    if not os.path.exists(p):
        raise ConfigError(f"config file not found: {p}")
    try:
        with open(p, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"config file is not valid JSON: {exc}") from exc
    cfg = _validate(raw)
    if path is None:
        _CACHE = cfg
    return cfg


def global_config(path: Optional[str] = None) -> Dict[str, Any]:
    """Return the validated 'global' block."""
    return load_config(path)["global"]


def strategy_config(strategy_id: str, path: Optional[str] = None) -> Dict[str, Any]:
    """Return a per-strategy config block by id. Raises ConfigError on unknown id (fail-closed)."""
    strategies = load_config(path)["strategies"]
    if strategy_id not in strategies:
        raise ConfigError(f"unknown strategy id: {strategy_id!r}")
    return strategies[strategy_id]


# Flip to False to pin the floor to the committed literal (e.g. for a fully reproducible,
# network-independent backtest run). Default True = use the live tokenized-T-bill feed.
_USE_LIVE_RWA_FLOOR = os.environ.get("SPA_LAB_LIVE_RWA_FLOOR", "1") != "0"


def rwa_floor_apy_pct(path: Optional[str] = None, live: Optional[bool] = None) -> float:
    """The risk-free RWA benchmark APY (%).

    Returns the LIVE tokenized-T-bill floor (TVL-weighted across BUIDL/USYC/USDY/OUSG/USTB/
    TBILL via spa_core.strategy_lab.data.rwa_feed; ~$15B market at ~3.3–3.5%) when the feed is
    available and fresh (cached). Falls back to the committed config literal
    (global.rwa_floor_apy_pct) when the feed is unavailable — network down, empty cache, or a
    fail-closed schema error — so a deterministic backtest is NEVER crashed by a missing feed.
    The literal is the conservative fail-safe, not the primary source.

    Args:
        path: optional config override path (tests/hermetic). Bypasses the config cache.
        live: force-enable (True) / disable (False) the live feed for this call; None → the
              module default (env SPA_LAB_LIVE_RWA_FLOOR, default on).
    """
    literal = float(global_config(path)["rwa_floor_apy_pct"])
    use_live = _USE_LIVE_RWA_FLOOR if live is None else bool(live)
    if not use_live:
        return literal
    try:
        # Imported lazily so the config module has no hard import-time dep on the feed/network.
        from spa_core.strategy_lab.data.rwa_feed import current_rwa_floor_pct
        return float(current_rwa_floor_pct())
    except Exception:  # noqa: BLE001 — feed unavailable → conservative committed literal
        return literal


def risk_limits() -> Dict[str, float]:
    """Risk CAPS, sourced from spa_core.risk.policy.RiskConfig — NOT duplicated in the lab.

    Returns the canonical limits the lab's strategies/metrics must respect:
      - tvl_floor_usd          : min pool TVL for entry
      - max_concentration_t1   : per-protocol T1 cap (fraction)
      - max_concentration_t2   : per-protocol T2 cap (fraction)
      - max_total_t2           : T2 aggregate cap (fraction)
      - max_drawdown_stop      : portfolio kill-switch drawdown (fraction)
      - min_cash_pct           : minimum cash buffer (fraction)
      - max_apy_pct / min_apy_pct : APY entry bounds (percent)
    """
    rc = RiskConfig()
    return {
        "tvl_floor_usd": rc.min_tvl_usd,
        "max_concentration_t1": rc.max_concentration_t1,
        "max_concentration_t2": rc.max_concentration_t2,
        "max_total_t2": rc.max_total_t2_allocation,
        "max_drawdown_stop": rc.max_drawdown_stop,
        "min_cash_pct": rc.min_cash_pct,
        "max_apy_pct": rc.max_apy_for_new_position,
        "min_apy_pct": rc.min_apy_for_new_position,
    }
