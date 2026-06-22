"""
MP-1145  DeFiProtocolTVLYieldElasticityAnalyzer
-----------------------------------------------
Quantify how much a pool's APR *compresses* as its TVL grows. For incentive- or
fee-driven yield, the incentive component of APR behaves roughly like a fixed
reward flow divided by TVL: ``incentive_apr ~= fixed_reward_flow / TVL``. So if
the TVL doubles, the incentive component of the APR roughly halves. A *base*
component (e.g. organic trading-fee yield that scales with volume, or a real
lending rate) is not diluted the same way. This module separates the diluting
incentive part from the sticky base part and projects what the APR becomes once
your own deposit and any expected external inflow land in the pool — including
*self-crowding*: your own capital dilutes the very yield you are chasing.

For a single market the module computes:
- the incentive share of the current APR,
- the implied fixed reward flow (USD/year) backing the incentive component,
- the post-deposit TVL (current + your deposit + projected external inflow),
- the projected incentive and total APR after that TVL change,
- the *self-dilution*: the APR drop caused by *your* deposit alone,
- the *external-dilution*: the APR drop caused by projected external inflow,
- the total APR compression,
- a *yield elasticity* (approx. % change in APR per % change in TVL),
- a 0-100 *elasticity score* (higher = the yield is sticky / resists
  compression as TVL grows).

Genuine gap: the analytics package has a supply-cap proximity analyser (headroom
to a hard supply cap) and TVL-momentum trackers (direction/speed of TVL change),
but none models the *yield elasticity* of APR to TVL — separating the diluting
incentive component from a sticky base, pricing self-crowding from your own
deposit, and scoring how compression-prone the yield is. A grep for
"tvl_yield_elasticity" / "yield_elasticity" across the package confirms no
existing module covers this angle.

The module returns:
- name (input echo) and the input echoes
- base_apr_pct                   - current APR minus incentive APR (>=0)
- incentive_share_of_apr_pct     - incentive APR as a share of current APR
- fixed_reward_flow_usd_per_year - implied reward flow backing the incentive
- post_deposit_tvl_usd           - TVL after your deposit + external inflow
- projected_incentive_apr_pct    - incentive APR at the post-deposit TVL
- projected_apr_pct              - total projected APR (base + incentive)
- self_dilution_pct              - APR drop from your deposit alone
- external_dilution_pct          - APR drop from projected external inflow
- total_apr_compression_pct      - current APR minus projected APR
- yield_elasticity               - approx %dAPR per %dTVL (<=0 typically)
- elasticity_score               - 0-100, higher = sticky / resists compression
- classification                 - STICKY_YIELD .. SEVERE_COMPRESSION
- grade                          - A-F letter grade
- flags / recommendations        - advisory verdicts

Advisory / read-only. Pure stdlib. Atomic ring-buffer JSON log (100 entries).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data",
    "tvl_yield_elasticity_log.json",
)
_LOG_CAP = 100

# Small epsilon to guard divisions.
_EPS = 1e-9

# Sentinel for "no meaningful elasticity" (keeps JSON finite, no inf/NaN).
ELASTICITY_SENTINEL = 0.0

# Defaults.
_DEFAULT_PROJECTED_EXTERNAL_INFLOW_USD = 0.0

# Classification bands (on total APR compression as a share of current APR).
CLASS_STICKY_YIELD = "STICKY_YIELD"
CLASS_MILD_COMPRESSION = "MILD_COMPRESSION"
CLASS_MODERATE_COMPRESSION = "MODERATE_COMPRESSION"
CLASS_HIGH_COMPRESSION = "HIGH_COMPRESSION"
CLASS_SEVERE_COMPRESSION = "SEVERE_COMPRESSION"
CLASS_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

ALL_CLASSIFICATIONS = (
    CLASS_STICKY_YIELD,
    CLASS_MILD_COMPRESSION,
    CLASS_MODERATE_COMPRESSION,
    CLASS_HIGH_COMPRESSION,
    CLASS_SEVERE_COMPRESSION,
    CLASS_INSUFFICIENT_DATA,
)

# Flags
FLAG_SEVERE_COMPRESSION = "SEVERE_COMPRESSION"
FLAG_INCENTIVE_DOMINATED = "INCENTIVE_DOMINATED"
FLAG_BASE_YIELD_STICKY = "BASE_YIELD_STICKY"
FLAG_LARGE_SELF_DILUTION = "LARGE_SELF_DILUTION"
FLAG_HIGH_EXTERNAL_INFLOW_RISK = "HIGH_EXTERNAL_INFLOW_RISK"
FLAG_LOW_TVL_FRAGILE = "LOW_TVL_FRAGILE"
FLAG_STICKY_YIELD = "STICKY_YIELD"
FLAG_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

ALL_FLAGS = (
    FLAG_SEVERE_COMPRESSION,
    FLAG_INCENTIVE_DOMINATED,
    FLAG_BASE_YIELD_STICKY,
    FLAG_LARGE_SELF_DILUTION,
    FLAG_HIGH_EXTERNAL_INFLOW_RISK,
    FLAG_LOW_TVL_FRAGILE,
    FLAG_STICKY_YIELD,
    FLAG_INSUFFICIENT_DATA,
)

ALL_GRADES = ("A", "B", "C", "D", "F")

# Thresholds (module constants).
# Compression bands as a share of current APR (pct of APR lost):
_STICKY_COMPRESSION_PCT = 5.0       # < 5% of APR lost -> sticky
_MILD_COMPRESSION_PCT = 15.0        # < 15% -> mild
_MODERATE_COMPRESSION_PCT = 35.0    # < 35% -> moderate
_HIGH_COMPRESSION_PCT = 60.0        # < 60% -> high; >= 60% severe
# Incentive-share flag thresholds:
_INCENTIVE_DOMINATED_SHARE_PCT = 70.0   # incentive >= 70% of APR -> dominated
_BASE_STICKY_SHARE_PCT = 50.0           # base >= 50% of APR -> sticky base
# Self-dilution flag (pct of APR lost to your own deposit):
_LARGE_SELF_DILUTION_PCT = 10.0
# External inflow risk: projected external inflow >= this multiple of current TVL
_HIGH_EXTERNAL_INFLOW_MULTIPLE = 0.5
# Low-TVL fragility: a pool below this TVL is fragile to single deposits.
_LOW_TVL_FRAGILE_USD = 100_000.0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _atomic_log(log_path: str, entry: dict) -> None:
    """Append *entry* to ring-buffer JSON array (cap=100), atomic write."""
    abs_path = os.path.abspath(log_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    try:
        with open(abs_path, "r", encoding="utf-8") as fh:
            data: list = json.load(fh)
        if not isinstance(data, list):
            data = []
    except (FileNotFoundError, json.JSONDecodeError):
        data = []

    data.append(entry)
    if len(data) > _LOG_CAP:
        data = data[-_LOG_CAP:]

    dir_name = os.path.dirname(abs_path)
    atomic_save(data, str(abs_path))
def _safe_float(value: Any, default: float = 0.0) -> float:
    """Coerce *value* to float, returning *default* on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    """Clamp *value* to the inclusive range [lo, hi]."""
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# Sub-calculators (defensive division everywhere)
# ---------------------------------------------------------------------------

def _incentive_share_of_apr_pct(
    incentive_apr_pct: float,
    current_apr_pct: float,
) -> float:
    """
    Incentive component as a share of the current total APR, in pct.

        share = incentive_apr / current_apr * 100

    Defensive: when the current APR is ~0 the share is undefined; return 0.0.
    Clamped to [0, 100] (incentive cannot exceed total APR meaningfully).
    """
    incentive = max(0.0, incentive_apr_pct)
    current = current_apr_pct
    if current <= _EPS:
        return 0.0
    return _clamp(incentive / current * 100.0, 0.0, 100.0)


def _fixed_reward_flow_usd_per_year(
    incentive_apr_pct: float,
    current_tvl_usd: float,
) -> float:
    """
    Implied fixed reward flow (USD/year) backing the incentive component.

        flow = (incentive_apr/100) * current_tvl

    This is the dollar amount of incentives distributed per year; dividing it by
    a future TVL gives the future incentive APR. Defensive: clamps TVL at 0.
    """
    tvl = max(0.0, current_tvl_usd)
    return (max(0.0, incentive_apr_pct) / 100.0) * tvl


def _projected_incentive_apr_pct(
    fixed_reward_flow_usd_per_year: float,
    post_deposit_tvl_usd: float,
) -> float:
    """
    Incentive APR at a future TVL, holding the fixed reward flow constant.

        projected_incentive_apr = flow / post_tvl * 100

    Defensive: a non-positive future TVL means the incentive APR is undefined;
    return 0.0.
    """
    flow = max(0.0, fixed_reward_flow_usd_per_year)
    tvl = max(0.0, post_deposit_tvl_usd)
    if tvl <= _EPS:
        return 0.0
    return flow / tvl * 100.0


def _self_dilution_pct(
    base_apr_pct: float,
    fixed_reward_flow_usd_per_year: float,
    current_tvl_usd: float,
    your_deposit_usd: float,
) -> float:
    """
    APR drop (pct points) caused by *your* deposit alone (self-crowding).

        apr_before = base + flow / current_tvl * 100
        apr_after  = base + flow / (current_tvl + your_deposit) * 100
        self_dilution = apr_before - apr_after

    Defensive: divisions guarded; clamps TVL and deposit at 0. Returns 0.0 when
    the current TVL is ~0 (cannot meaningfully measure).
    """
    tvl = max(0.0, current_tvl_usd)
    deposit = max(0.0, your_deposit_usd)
    flow = max(0.0, fixed_reward_flow_usd_per_year)
    if tvl <= _EPS:
        return 0.0
    incentive_before = flow / tvl * 100.0
    after_tvl = tvl + deposit
    incentive_after = flow / after_tvl * 100.0 if after_tvl > _EPS else 0.0
    return max(0.0, incentive_before - incentive_after)


def _external_dilution_pct(
    fixed_reward_flow_usd_per_year: float,
    current_tvl_usd: float,
    your_deposit_usd: float,
    projected_external_inflow_usd: float,
) -> float:
    """
    APR drop (pct points) caused by projected *external* inflow, measured on top
    of your own deposit (the incremental dilution from outside capital).

        tvl_self = current + your_deposit
        tvl_all  = current + your_deposit + external_inflow
        external_dilution = flow/tvl_self*100 - flow/tvl_all*100

    Defensive: divisions guarded; clamps inputs at 0.
    """
    tvl = max(0.0, current_tvl_usd)
    deposit = max(0.0, your_deposit_usd)
    inflow = max(0.0, projected_external_inflow_usd)
    flow = max(0.0, fixed_reward_flow_usd_per_year)
    tvl_self = tvl + deposit
    tvl_all = tvl + deposit + inflow
    incentive_self = flow / tvl_self * 100.0 if tvl_self > _EPS else 0.0
    incentive_all = flow / tvl_all * 100.0 if tvl_all > _EPS else 0.0
    return max(0.0, incentive_self - incentive_all)


def _yield_elasticity(
    current_apr_pct: float,
    projected_apr_pct: float,
    current_tvl_usd: float,
    post_deposit_tvl_usd: float,
) -> float:
    """
    Approximate elasticity of APR to TVL: (%dAPR) / (%dTVL).

        d_apr_pct = (projected_apr - current_apr) / current_apr
        d_tvl_pct = (post_tvl - current_tvl) / current_tvl
        elasticity = d_apr_pct / d_tvl_pct

    For a pure incentive yield (flow/TVL) this tends toward -1 (a 1% TVL rise
    cuts APR ~1%); a sticky base pushes it toward 0. Defensive: guarded
    divisions; when there is no TVL change or no current APR, return the
    ELASTICITY_SENTINEL (0.0).
    """
    cur_apr = current_apr_pct
    cur_tvl = current_tvl_usd
    if abs(cur_apr) <= _EPS or abs(cur_tvl) <= _EPS:
        return ELASTICITY_SENTINEL
    d_tvl = post_deposit_tvl_usd - cur_tvl
    if abs(d_tvl) <= _EPS:
        return ELASTICITY_SENTINEL
    d_apr_pct = (projected_apr_pct - cur_apr) / cur_apr
    d_tvl_pct = d_tvl / cur_tvl
    if abs(d_tvl_pct) <= _EPS:
        return ELASTICITY_SENTINEL
    return d_apr_pct / d_tvl_pct


def _total_apr_compression_pct(
    current_apr_pct: float,
    projected_apr_pct: float,
) -> float:
    """Total APR compression (pct points): current APR minus projected APR."""
    return current_apr_pct - projected_apr_pct


def _compression_share_of_apr_pct(
    total_apr_compression_pct: float,
    current_apr_pct: float,
) -> float:
    """
    Compression as a share of current APR, in pct (for classification).

        share = compression / current_apr * 100

    Defensive: when current APR is ~0 the share is undefined; return 0.0.
    Negative compression (APR rising) reports 0.0.
    """
    current = current_apr_pct
    if current <= _EPS:
        return 0.0
    return max(0.0, total_apr_compression_pct / current * 100.0)


def _elasticity_score(
    compression_share_of_apr_pct: float,
    incentive_share_of_apr_pct: float,
    has_data: bool,
) -> float:
    """
    0-100: higher = the yield is sticky / resists compression as TVL grows.

    Blends two drivers:
    - low-compression component (0-65): full 65 when no APR is lost to the TVL
      change; 0 when all (or more) of the APR is compressed away.
    - sticky-base component (0-35): full 35 when the base (non-incentive) share
      is the whole APR; 0 when the APR is entirely incentive (fully dilutable).

    Returns 0.0 when there is no usable data.
    """
    if not has_data:
        return 0.0

    # Low-compression component (0..65): invert compression share capped at 100.
    comp_share = _clamp(compression_share_of_apr_pct / 100.0, 0.0, 1.0)
    comp_component = (1.0 - comp_share) * 65.0

    # Sticky-base component (0..35): base share = 100 - incentive share.
    base_share = _clamp(100.0 - incentive_share_of_apr_pct, 0.0, 100.0) / 100.0
    base_component = base_share * 35.0

    return _clamp(comp_component + base_component)


def _classify(
    compression_share_of_apr_pct: float,
    has_data: bool,
) -> str:
    """
    Assign an advisory compression classification band on the share of current
    APR lost to the projected TVL change.

      no data                 -> INSUFFICIENT_DATA
      < 5    -> STICKY_YIELD
      < 15   -> MILD_COMPRESSION
      < 35   -> MODERATE_COMPRESSION
      < 60   -> HIGH_COMPRESSION
      >= 60  -> SEVERE_COMPRESSION
    """
    if not has_data:
        return CLASS_INSUFFICIENT_DATA

    share = compression_share_of_apr_pct
    if share < _STICKY_COMPRESSION_PCT:
        return CLASS_STICKY_YIELD
    if share < _MILD_COMPRESSION_PCT:
        return CLASS_MILD_COMPRESSION
    if share < _MODERATE_COMPRESSION_PCT:
        return CLASS_MODERATE_COMPRESSION
    if share < _HIGH_COMPRESSION_PCT:
        return CLASS_HIGH_COMPRESSION
    return CLASS_SEVERE_COMPRESSION


def _grade(elasticity_score: float) -> str:
    """Map elasticity_score (higher = stickier) to an A-F letter grade."""
    s = elasticity_score
    if s >= 90.0:
        return "A"
    if s >= 70.0:
        return "B"
    if s >= 50.0:
        return "C"
    if s >= 30.0:
        return "D"
    return "F"


def _flags(
    compression_share_of_apr_pct: float,
    incentive_share_of_apr_pct: float,
    self_dilution_pct: float,
    current_apr_pct: float,
    current_tvl_usd: float,
    your_deposit_usd: float,
    projected_external_inflow_usd: float,
    classification: str,
    has_data: bool,
) -> list:
    """Return only the relevant advisory flags."""
    flags: list[str] = []

    if not has_data:
        flags.append(FLAG_INSUFFICIENT_DATA)
        return flags

    if classification == CLASS_SEVERE_COMPRESSION:
        flags.append(FLAG_SEVERE_COMPRESSION)

    if incentive_share_of_apr_pct >= _INCENTIVE_DOMINATED_SHARE_PCT:
        flags.append(FLAG_INCENTIVE_DOMINATED)

    base_share = 100.0 - incentive_share_of_apr_pct
    if base_share >= _BASE_STICKY_SHARE_PCT:
        flags.append(FLAG_BASE_YIELD_STICKY)

    # Large self-dilution: your deposit alone cuts a big chunk of APR.
    if current_apr_pct > _EPS:
        self_share = self_dilution_pct / current_apr_pct * 100.0
        if self_share >= _LARGE_SELF_DILUTION_PCT:
            flags.append(FLAG_LARGE_SELF_DILUTION)

    # High external inflow risk: projected external inflow is large vs TVL.
    if (current_tvl_usd > _EPS
            and projected_external_inflow_usd
            >= current_tvl_usd * _HIGH_EXTERNAL_INFLOW_MULTIPLE):
        flags.append(FLAG_HIGH_EXTERNAL_INFLOW_RISK)

    # Low-TVL fragile: a small pool dilutes hard on single deposits.
    if 0.0 < current_tvl_usd < _LOW_TVL_FRAGILE_USD:
        flags.append(FLAG_LOW_TVL_FRAGILE)

    if classification == CLASS_STICKY_YIELD:
        flags.append(FLAG_STICKY_YIELD)

    return flags


def _recommendations(
    classification: str,
    flags: list,
    current_apr_pct: float,
    projected_apr_pct: float,
    total_apr_compression_pct: float,
    incentive_share_of_apr_pct: float,
    self_dilution_pct: float,
    external_dilution_pct: float,
    yield_elasticity: float,
    has_data: bool,
) -> list:
    """Return advisory recommendation strings based on the verdict."""
    recs: list[str] = []

    if not has_data:
        recs.append(
            "Insufficient data: no current TVL / APR signal or data marked "
            "unreliable. Cannot assess TVL-yield elasticity for this market."
        )
        return recs

    if classification == CLASS_SEVERE_COMPRESSION:
        recs.append(
            f"Severe compression: APR falls from ~{current_apr_pct:.2f}% to "
            f"~{projected_apr_pct:.2f}% (a ~{total_apr_compression_pct:.2f}pp "
            "drop) once the projected TVL change lands. The headline yield is "
            "not what you will actually earn at scale."
        )
    elif classification == CLASS_HIGH_COMPRESSION:
        recs.append(
            f"High compression: the APR compresses by "
            f"~{total_apr_compression_pct:.2f}pp to ~{projected_apr_pct:.2f}% "
            "after the TVL change. Size in carefully and re-check the realised "
            "yield."
        )
    elif classification == CLASS_MODERATE_COMPRESSION:
        recs.append(
            f"Moderate compression: APR eases ~{total_apr_compression_pct:.2f}pp "
            f"to ~{projected_apr_pct:.2f}% as TVL grows. Material but workable."
        )
    elif classification == CLASS_MILD_COMPRESSION:
        recs.append(
            f"Mild compression: APR slips only ~{total_apr_compression_pct:.2f}pp "
            f"to ~{projected_apr_pct:.2f}%. The yield is fairly resilient."
        )
    else:  # STICKY_YIELD
        recs.append(
            f"Sticky yield: APR barely moves (~{total_apr_compression_pct:.2f}pp) "
            f"to ~{projected_apr_pct:.2f}% even as TVL grows. The yield resists "
            "dilution well."
        )

    if FLAG_INCENTIVE_DOMINATED in flags:
        recs.append(
            f"Incentive-dominated: ~{incentive_share_of_apr_pct:.1f}% of the APR "
            "is dilutable incentive flow. Expect this part to fall as TVL rises "
            "or incentives wind down."
        )

    if FLAG_BASE_YIELD_STICKY in flags:
        recs.append(
            "Sticky base: a large share of the APR is base (non-incentive) "
            "yield that does not dilute with TVL. This part is more durable."
        )

    if FLAG_LARGE_SELF_DILUTION in flags:
        recs.append(
            f"Large self-dilution: your own deposit alone cuts the APR by "
            f"~{self_dilution_pct:.2f}pp. You are crowding the very yield you "
            "are chasing; size down or split entry."
        )

    if FLAG_HIGH_EXTERNAL_INFLOW_RISK in flags:
        recs.append(
            f"High external-inflow risk: projected outside capital adds "
            f"~{external_dilution_pct:.2f}pp of further dilution. The realised "
            "APR depends heavily on how much others pile in."
        )

    if FLAG_LOW_TVL_FRAGILE in flags:
        recs.append(
            "Low-TVL fragile: this pool is small, so even modest deposits move "
            "the APR sharply. Treat the headline APR as unstable."
        )

    return recs


# ---------------------------------------------------------------------------
# Public analyse function
# ---------------------------------------------------------------------------

def analyze(
    token: dict | None = None,
    config: dict | None = None,
    *,
    current_tvl_usd: float | None = None,
    current_apr_pct: float | None = None,
    incentive_apr_pct: float | None = None,
    your_deposit_usd: float | None = None,
    projected_external_inflow_usd: float | None = None,
    data_quality: Any = None,
    name: str | None = None,
) -> dict:
    """
    Analyse the TVL-yield elasticity of a single market / pool.

    Inputs may be supplied as a ``token`` dict and/or via keyword arguments
    (keywords take precedence over dict values). All inputs are optional with
    sane defaults.

    Recognised keys / keywords (all with safe defaults):
    - name                          : str
    - current_tvl_usd               : float (current pool TVL, USD)
    - current_apr_pct               : float (current total APR)
    - incentive_apr_pct             : float (dilutable incentive part of APR; if
                                      omitted, the whole APR is treated as
                                      incentive, i.e. base = 0)
    - your_deposit_usd              : float (the deposit you are considering)
    - projected_external_inflow_usd : float (expected outside inflow, default 0)
    - data_quality                  : truthy/"ok" => trusted; falsy/"poor"

    config : dict, optional
        - log_path : str  (override default log path)

    Returns
    -------
    dict
        Full analysis result. Never raises to the caller.
    """
    cfg = config or {}
    log_path = cfg.get("log_path", _LOG_PATH)

    t = token if isinstance(token, dict) else {}

    def _pick(kw: Any, key: str, default: float) -> float:
        if kw is not None:
            return _safe_float(kw, default)
        return _safe_float(t.get(key, default), default)

    name_val = name if name is not None else str(t.get("name", "UNKNOWN"))

    current_tvl = max(0.0, _pick(current_tvl_usd, "current_tvl_usd", 0.0))
    current_apr = _pick(current_apr_pct, "current_apr_pct", 0.0)

    # Incentive APR: if not provided, default to the whole current APR
    # (i.e. assume the entire APR is dilutable incentive, base = 0). Clamp to
    # [0, current_apr] so base APR cannot go negative.
    incentive_provided = (
        incentive_apr_pct is not None or "incentive_apr_pct" in t
    )
    if incentive_provided:
        incentive_apr = max(0.0, _pick(incentive_apr_pct, "incentive_apr_pct", 0.0))
    else:
        incentive_apr = max(0.0, current_apr)
    # Incentive cannot exceed the current APR.
    incentive_apr = min(incentive_apr, max(0.0, current_apr))

    your_deposit = max(0.0, _pick(your_deposit_usd, "your_deposit_usd", 0.0))
    external_inflow = max(0.0, _pick(
        projected_external_inflow_usd, "projected_external_inflow_usd",
        _DEFAULT_PROJECTED_EXTERNAL_INFLOW_USD))

    dq_raw = data_quality if data_quality is not None else t.get("data_quality", "ok")
    if isinstance(dq_raw, str):
        data_quality_ok = dq_raw.strip().lower() not in ("poor", "bad", "low", "")
    else:
        data_quality_ok = bool(dq_raw)

    # base APR = current - incentive, clamped >= 0.
    base_apr = max(0.0, current_apr - incentive_apr)

    # Data sufficiency: need a positive current TVL and a positive current APR,
    # and the data-quality flag must not mark the inputs as unreliable.
    has_signal = current_tvl > _EPS and current_apr > _EPS
    has_data = has_signal and data_quality_ok

    incentive_share = _incentive_share_of_apr_pct(incentive_apr, current_apr)
    fixed_flow = _fixed_reward_flow_usd_per_year(incentive_apr, current_tvl)
    post_deposit_tvl = current_tvl + your_deposit + external_inflow
    projected_incentive_apr = _projected_incentive_apr_pct(
        fixed_flow, post_deposit_tvl)
    projected_apr = base_apr + projected_incentive_apr
    self_dilution = _self_dilution_pct(
        base_apr, fixed_flow, current_tvl, your_deposit)
    external_dilution = _external_dilution_pct(
        fixed_flow, current_tvl, your_deposit, external_inflow)
    total_compression = _total_apr_compression_pct(current_apr, projected_apr)
    compression_share = _compression_share_of_apr_pct(
        total_compression, current_apr)
    elasticity = _yield_elasticity(
        current_apr, projected_apr, current_tvl, post_deposit_tvl)
    classification = _classify(compression_share, has_data)
    score = _elasticity_score(compression_share, incentive_share, has_data)
    grade = _grade(score)
    flags = _flags(
        compression_share,
        incentive_share,
        self_dilution,
        current_apr,
        current_tvl,
        your_deposit,
        external_inflow,
        classification,
        has_data,
    )
    recs = _recommendations(
        classification,
        flags,
        current_apr,
        projected_apr,
        total_compression,
        incentive_share,
        self_dilution,
        external_dilution,
        elasticity,
        has_data,
    )

    result: dict[str, Any] = {
        "name": name_val,
        "current_tvl_usd": current_tvl,
        "current_apr_pct": current_apr,
        "incentive_apr_pct": incentive_apr,
        "base_apr_pct": base_apr,
        "your_deposit_usd": your_deposit,
        "projected_external_inflow_usd": external_inflow,
        "data_quality_ok": data_quality_ok,
        "incentive_share_of_apr_pct": incentive_share,
        "fixed_reward_flow_usd_per_year": fixed_flow,
        "post_deposit_tvl_usd": post_deposit_tvl,
        "projected_incentive_apr_pct": projected_incentive_apr,
        "projected_apr_pct": projected_apr,
        "self_dilution_pct": self_dilution,
        "external_dilution_pct": external_dilution,
        "total_apr_compression_pct": total_compression,
        "compression_share_of_apr_pct": compression_share,
        "yield_elasticity": elasticity,
        "elasticity_score": score,
        "classification": classification,
        "grade": grade,
        "flags": flags,
        "recommendations": recs,
        "timestamp": time.time(),
    }

    try:
        _atomic_log(log_path, result)
    except Exception:
        pass  # advisory: never crash caller

    return result


# ---------------------------------------------------------------------------
# Public batch analyse function
# ---------------------------------------------------------------------------

def analyze_portfolio(markets: list, config: dict | None = None) -> dict:
    """
    Analyse TVL-yield elasticity across a batch of markets and summarise.

    Returns
    -------
    dict
        - total_markets                  : int
        - results                        : list[dict]  (per-market analysis)
        - most_compression_prone_market  : str | None  (lowest elasticity score)
        - least_compression_prone_market : str | None  (highest elasticity score)
        - avg_elasticity_score           : float
        - severe_compression_count       : int
        - timestamp                      : float
    """
    if not isinstance(markets, list):
        markets = []

    results = [
        analyze(m if isinstance(m, dict) else {}, config=config)
        for m in markets
    ]
    total = len(results)

    if total == 0:
        return {
            "total_markets": 0,
            "results": [],
            "most_compression_prone_market": None,
            "least_compression_prone_market": None,
            "avg_elasticity_score": 0.0,
            "severe_compression_count": 0,
            "timestamp": time.time(),
        }

    # Most compression-prone = lowest elasticity score; least = highest.
    most = min(results, key=lambda r: r["elasticity_score"])
    least = max(results, key=lambda r: r["elasticity_score"])
    avg = sum(r["elasticity_score"] for r in results) / total
    severe = sum(
        1 for r in results
        if r["classification"] == CLASS_SEVERE_COMPRESSION
    )

    return {
        "total_markets": total,
        "results": results,
        "most_compression_prone_market": most["name"],
        "least_compression_prone_market": least["name"],
        "avg_elasticity_score": avg,
        "severe_compression_count": severe,
        "timestamp": time.time(),
    }


# ---------------------------------------------------------------------------
# Class wrapper
# ---------------------------------------------------------------------------

class DeFiProtocolTVLYieldElasticityAnalyzer:
    """
    Object-oriented wrapper around the functional ``analyze`` /
    ``analyze_portfolio`` functions.

    >>> a = DeFiProtocolTVLYieldElasticityAnalyzer()
    >>> r = a.analyze({"name": "FARM-pool", "current_tvl_usd": 1_000_000.0,
    ...                "current_apr_pct": 20.0, "incentive_apr_pct": 16.0,
    ...                "your_deposit_usd": 250_000.0})
    """

    def __init__(self, config: dict | None = None) -> None:
        self._config = config or {}

    def analyze(self, token: dict | None = None, **kwargs: Any) -> dict:
        """Delegate to module-level ``analyze``."""
        return analyze(token, config=self._config, **kwargs)

    def analyze_portfolio(self, markets: list) -> dict:
        """Delegate to module-level ``analyze_portfolio``."""
        return analyze_portfolio(markets, config=self._config)


# ---------------------------------------------------------------------------
# CLI demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    _demo_markets = [
        {
            "name": "FARM-pool (incentive-heavy, small)",
            "current_tvl_usd": 500_000.0,
            "current_apr_pct": 40.0,
            "incentive_apr_pct": 36.0,
            "your_deposit_usd": 250_000.0,
            "projected_external_inflow_usd": 500_000.0,
        },
        {
            "name": "stETH (base-heavy, deep)",
            "current_tvl_usd": 50_000_000.0,
            "current_apr_pct": 4.0,
            "incentive_apr_pct": 0.5,
            "your_deposit_usd": 100_000.0,
            "projected_external_inflow_usd": 0.0,
        },
    ]

    import json as _json
    print(_json.dumps(analyze(_demo_markets[0]), indent=2, default=str))
    print("---- portfolio ----")
    summary = analyze_portfolio(_demo_markets)
    summary_view = {k: v for k, v in summary.items() if k != "results"}
    print(_json.dumps(summary_view, indent=2, default=str))
    sys.exit(0)
