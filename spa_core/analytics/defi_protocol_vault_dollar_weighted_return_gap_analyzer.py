"""
MP-1202: DeFiProtocolVaultDollarWeightedReturnGapAnalyzer
========================================================
Advisory/read-only analytics module.

A vault advertises a headline trailing APY that is a TIME-WEIGHTED return (TWR):
it geometrically LINKS the per-period returns and is INDEPENDENT of the timing of
depositor cash flows — it measures the manager's per-dollar-over-time performance:

    twr_period_geom_mean = (prod_i (1 + r_i/100))^(1/n) - 1
    twr_apr_pct          = ((1 + twr_period_geom_mean)^periods_per_year - 1) * 100

But the return the AVERAGE DEPOSITOR actually earns is the DOLLAR-WEIGHTED (money-
weighted) return (DWR / MWR), which weights each period's return by the CAPITAL
actually invested during that period. Simulate the balance path (apply r_i to the
beginning balance, then add the end-of-period external flow), and the realised
per-period experience is the capital-weighted arithmetic mean of the per-period %:

    capital_i = beginning balance exposed to r_i
    dwr_period = sum(capital_i * r_i) / sum(capital_i)
    dwr_apr_pct = dwr_period * periods_per_year

When large inflows arrive RIGHT BEFORE low-return periods (capital chases a hot
streak that then mean-reverts), or capital leaves before high-return periods, the
depositor's realised dollar-weighted return diverges BELOW the advertised TWR. This
gap is the classic "behavior gap" / "investor-return gap" (Morningstar investor
returns vs fund returns) applied to a DeFi vault:

    behavior_gap_pct = twr_apr_pct - dwr_apr_pct   (positive = depositors earned LESS)

Angle: "a vault advertises a 30% trailing TWR, but most TVL arrived right before the
yield mean-reverted to 8%, so the dollar-weighted return the average depositor
actually earned was only ~14% — a ~16pp behavior gap from adverse flow timing;
discount the headline toward the dollar-weighted experience."

HIGHER score = dollar-weighted return ≈ time-weighted headline (flow timing
neutral/aligned → depositors realise the headline). LOWER score = large positive
behavior gap (adverse flow timing → depositors realise far below the headline).

Distinct from:
  * time_weighted_return_calculator (MP-718, Tier-C) — that module merely COMPUTES a
    TWR by geometrically linking per-period returns to STRIP OUT flow timing. HERE we
    COMPARE that TWR against the dollar-weighted (money-weighted) return and quantify
    the behavior gap a depositor actually realises FROM flow timing — the opposite
    question (flow timing is the signal we measure, not the thing we remove).
  * defi_protocol_vault_deployment_ramp_drag_analyzer — that concerns the VAULT'S OWN
    capital ramp-up dragging freshly deposited capital's yield (idle/undeployed
    capital). HERE it is the DEPOSITOR-COHORT cashflow timing (dollar-weighting) gap
    vs the published TWR, independent of any deployment ramp.
  * defi_protocol_vault_marginal_deposit_apr_dilution_analyzer — that concerns new
    deposits DILUTING a fixed reward emission across more capital (a MECHANISM that
    lowers the realised rate). HERE the rate PATH is taken as given and we measure how
    flow TIMING makes the realised dollar-weighted return diverge from the TWR.
  * defi_protocol_vault_price_return_contamination_analyzer (MP-1199) — that decomposes
    NAV growth into recurring yield vs one-off price return (a FIRST-MOMENT component
    SPLIT). HERE it is a TWR-vs-DWR cashflow-timing gap, not a yield-vs-price split.
  * defi_protocol_vault_yield_variance_drag_realization_analyzer — that converts the
    DISPERSION of a return series into a geometric-vs-arithmetic SECOND-MOMENT
    compounding penalty on a SINGLE capital base. HERE the gap arises from CAPITAL
    WEIGHTING across periods (flow timing), not from the variance of returns.

Pure stdlib, read-only/advisory, atomic ring-buffer log, sentinels (no inf/NaN).
"""

import json
import math
import os
import statistics
from datetime import datetime, timezone
from typing import List, Optional, Tuple

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "vault_dollar_weighted_return_gap_log.json"
)
LOG_CAP = 100

# Minimum valid per-period return samples required to use the sample path.
MIN_SAMPLES = 2

# Default annualisation factor (sub-periods per year).
DEFAULT_PERIODS_PER_YEAR = 365.0

# Default starting balance when flows are given but initial_capital is omitted.
DEFAULT_INITIAL_CAPITAL = 1.0

# Classification thresholds on the scale-free gap_fraction in [0, 1].
ALIGNED_FRACTION = 0.05      # at/below → aligned (dwr ≈ twr)
MILD_FRACTION = 0.20         # at/below → mild behavior gap
MODERATE_FRACTION = 0.50     # at/below → moderate; above → severe gap

# A single late inflow at/above this fraction of total positive flows is "late & large".
LARGE_LATE_INFLOW_FRAC = 0.5
# Total positive flows at/above this multiple of initial capital → flows dominate.
FLOWS_DOMINATE_MULT = 5.0
# Flow coefficient-of-variation at/below this → "stable flows".
STABLE_FLOW_CV = 0.25

# Small epsilon to keep normalisers finite.
EPS = 1e-12


# ── helpers ───────────────────────────────────────────────────────────────────

def _f(val, default: float = 0.0) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _safe_div(num: float, den: float, sentinel):
    if den <= 0:
        return sentinel
    return num / den


def _coerce_num(val) -> Optional[float]:
    """
    Coerce a single sample to a finite float, or None if it is not interpretable
    (skipped). Accepts int/float/numeric-string; rejects bool, None, NaN, inf,
    and non-numeric values.
    """
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        try:
            fv = float(val)
        except (TypeError, ValueError):
            return None
        return fv if math.isfinite(fv) else None
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None
        try:
            fv = float(s)
        except (TypeError, ValueError):
            return None
        return fv if math.isfinite(fv) else None
    return None


def _coerce_returns(raw) -> List[float]:
    """
    Coerce a list of per-sub-period RETURN (% per sub-period) samples to finite
    floats. NEGATIVE returns are VALID (a period can lose), so only non-finite /
    non-numeric / bool entries are skipped. Order is preserved (newest LAST).
    """
    out: List[float] = []
    if not raw:
        return out
    for v in list(raw):
        cv = _coerce_num(v)
        if cv is None:
            continue
        out.append(cv)
    return out


def _coerce_flows(raw, n: int) -> Optional[List[float]]:
    """
    Coerce a list of per-sub-period external net flows (deposit positive,
    withdrawal negative) to finite floats, requiring length == n. A flow can be
    any finite sign; a single uninterpretable element makes the whole flow vector
    invalid (return None) so we do not silently misalign flows with returns.
    Returns None if `raw` is falsy (→ caller treats all flows as 0).
    """
    if not raw:
        return None
    flows: List[float] = []
    for v in list(raw):
        cv = _coerce_num(v)
        if cv is None:
            return None
        flows.append(cv)
    if len(flows) != n:
        return None
    return flows


def _pstdev(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    try:
        sd = statistics.pstdev(values)
    except statistics.StatisticsError:
        return 0.0
    return sd if math.isfinite(sd) else 0.0


def _geom_mean_period(returns_pct: List[float]) -> Optional[float]:
    """
    Geometric mean per-period return (as a FRACTION) of a list of per-period %
    returns: (prod (1 + r_i/100))^(1/n) - 1. Returns None if any growth factor is
    non-positive (a period that loses >= 100% breaks the geometric link) or the
    result is non-finite.
    """
    if not returns_pct:
        return None
    log_sum = 0.0
    for r in returns_pct:
        factor = 1.0 + r / 100.0
        if factor <= 0.0:
            return None
        log_sum += math.log(factor)
    gm = math.exp(log_sum / len(returns_pct)) - 1.0
    return gm if math.isfinite(gm) else None


def _annualise_geom(period_frac: float, ppy: float) -> Optional[float]:
    """
    Annualise a geometric per-period fractional return to an APR % by compounding:
    ((1 + period_frac)^ppy - 1) * 100. Returns None if non-finite or the base is
    non-positive.
    """
    base = 1.0 + period_frac
    if base <= 0.0:
        return None
    try:
        apr = (math.exp(ppy * math.log(base)) - 1.0) * 100.0
    except (ValueError, OverflowError):
        return None
    return apr if math.isfinite(apr) else None


def _simulate_balances(
    returns_pct: List[float],
    flows: Optional[List[float]],
    initial_capital: float,
) -> Tuple[List[float], List[float], float]:
    """
    Simulate the balance path. The balance starts at `initial_capital`. For period
    i (oldest→newest): capital_i = the BEGINNING balance (exposed to r_i); apply
    the return (balance *= 1 + r_i/100); then add the END-of-period external flow.
    Returns (capitals, balances_after, final_balance), where capitals[i] is the
    capital exposed to r_i. `flows` of None is treated as all-zero.
    """
    capitals: List[float] = []
    balances_after: List[float] = []
    balance = initial_capital
    n = len(returns_pct)
    for i in range(n):
        capitals.append(balance)
        balance = balance * (1.0 + returns_pct[i] / 100.0)
        flow_i = flows[i] if flows is not None else 0.0
        balance += flow_i
        balances_after.append(balance)
    return capitals, balances_after, balance


def _build_default_cfg(overrides: Optional[dict] = None) -> dict:
    cfg = {"log_path": LOG_PATH, "log_cap": LOG_CAP}
    if overrides:
        cfg.update(overrides)
    return cfg


def _grade_from_score(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    if score >= 40:
        return "D"
    return "F"


# ── main class ────────────────────────────────────────────────────────────────

class DeFiProtocolVaultDollarWeightedReturnGapAnalyzer:
    """
    Measures the "behavior gap" between a vault's advertised TIME-WEIGHTED return
    (TWR — the headline trailing APY, independent of depositor flow timing) and the
    DOLLAR-WEIGHTED (money-weighted) return (DWR) the AVERAGE DEPOSITOR actually
    realises once each period's return is weighted by the capital invested during it:

        twr_period = (prod_i (1 + r_i/100))^(1/n) - 1
        twr_apr_pct = ((1 + twr_period)^ppy - 1) * 100
        capital_i   = beginning balance exposed to r_i (from a simulated balance path)
        dwr_period  = sum(capital_i * r_i) / sum(capital_i)
        dwr_apr_pct = dwr_period * ppy
        behavior_gap_pct = twr_apr_pct - dwr_apr_pct
        gap_fraction = clamp(behavior_gap_pct / twr_apr_pct, 0, 1)   (twr > 0)

    When inflows land right before low-return periods (capital chases a hot streak
    that mean-reverts), the depositor's DWR diverges below the TWR. With zero flows
    DWR == TWR exactly (gap 0 → ALIGNED).

    HIGHER score = DWR ≈ TWR (flow timing neutral/aligned). LOWER score = large
    positive behavior gap (adverse flow timing → depositors realise below headline).

    Per-position input dict fields:
        vault / token       : str
        period_returns      : list — per-sub-period % returns (e.g. 2.0 = +2%),
                              newest LAST. Negative returns are VALID; non-finite /
                              non-numeric / bool entries are skipped. MIN_SAMPLES = 2.
        period_flows        : list — OPTIONAL per-sub-period external NET flows
                              (deposit positive, withdrawal negative), END-of-period,
                              length == len(period_returns). Omitted → all flows 0
                              (then DWR == TWR exactly). A single uninterpretable
                              element or a length mismatch invalidates the vector.
        initial_capital     : float — OPTIONAL starting balance (default 1.0 when
                              flows are given). If 0 / invalid AND no positive flow
                              anywhere → INSUFFICIENT_DATA.
        periods_per_year    : float — annualisation factor (default 365).
        twr_apr_pct         : float — OPTIONAL direct override of the headline TWR.
        dollar_weighted_apr_pct : float — OPTIONAL direct override of the DWR.
                              Override path REQUIRES BOTH (one alone cannot derive
                              the other) — else INSUFFICIENT_DATA.

    MIN_SAMPLES = 2 valid return samples are required to use the sample path.
    """

    # ── public API ────────────────────────────────────────────────────────────

    def analyze(
        self,
        position: dict,
        cfg: Optional[dict] = None,
        write_log: bool = False,
    ) -> dict:
        cfg = _build_default_cfg(cfg)
        result = self._analyze_one(position)
        if write_log:
            self._write_log([result], self._aggregate([result]), cfg)
        return result

    def analyze_portfolio(
        self,
        positions: List[dict],
        cfg: Optional[dict] = None,
        write_log: bool = False,
    ) -> dict:
        cfg = _build_default_cfg(cfg)
        results = [self._analyze_one(p) for p in positions]
        agg = self._aggregate(results)
        if write_log:
            self._write_log(results, agg, cfg)
        return {"positions": results, "aggregate": agg}

    # ── per-position ───────────────────────────────────────────────────────────

    def _analyze_one(self, p: dict) -> dict:
        token = p.get("vault", p.get("token", "UNKNOWN"))

        ppy = _f(p.get("periods_per_year"), default=DEFAULT_PERIODS_PER_YEAR)
        if not math.isfinite(ppy) or ppy <= 0:
            ppy = DEFAULT_PERIODS_PER_YEAR

        returns = _coerce_returns(p.get("period_returns"))
        n = len(returns)
        used_samples = n >= MIN_SAMPLES

        if used_samples:
            return self._analyze_samples(token, p, returns, n, ppy)
        return self._analyze_override(token, p, n, ppy)

    # ── sample path ─────────────────────────────────────────────────────────────

    def _analyze_samples(
        self, token: str, p: dict, returns: List[float], n: int, ppy: float
    ) -> dict:
        flows = _coerce_flows(p.get("period_flows"), n)
        has_positive_flow = (
            flows is not None and any(f > 0.0 for f in flows))

        # Resolve initial capital. Default 1.0 when omitted; but if it is explicitly
        # supplied as 0 / invalid AND there is no positive flow to bootstrap a
        # balance, there is no capital base to dollar-weight → INSUFFICIENT_DATA.
        ic_present = "initial_capital" in p
        ic_raw = _coerce_num(p.get("initial_capital"))
        if ic_raw is not None and ic_raw > 0.0:
            initial_capital = ic_raw
        elif ic_present and not has_positive_flow:
            # Explicit 0 / invalid capital and nothing flows in.
            return self._insufficient(token)
        else:
            # Omitted (or zero-but-bootstrapped-by-inflow): use the unit base. With
            # zero flows this still yields the (flow-neutral) DWR baseline.
            initial_capital = DEFAULT_INITIAL_CAPITAL

        # Degenerate: every return identical → DWR == TWR regardless of flows, but
        # still a valid (aligned) measurement; only treat as INSUFFICIENT if the
        # geometric link breaks.
        twr_period = _geom_mean_period(returns)
        if twr_period is None:
            return self._insufficient(token)
        twr_apr_pct = _annualise_geom(twr_period, ppy)
        if twr_apr_pct is None or not math.isfinite(twr_apr_pct):
            return self._insufficient(token)

        capitals, _balances, final_balance = _simulate_balances(
            returns, flows, initial_capital)

        # Dollar-weighted per-period return = capital-weighted arithmetic mean of r_i,
        # using the ACTUAL (flow-driven) capital path.
        sum_cap = sum(capitals)
        weighted = _safe_div(
            sum(c * r for c, r in zip(capitals, returns)), sum_cap, sentinel=None)
        if weighted is None or not math.isfinite(weighted):
            # sum(capital_i) <= 0 (e.g. capital withdrawn / wiped out) — no
            # meaningful dollar-weighted experience.
            return self._insufficient(token)
        dwr_period_pct = weighted          # already a % per period
        dwr_apr_pct = dwr_period_pct * ppy

        # FLOW-NEUTRAL baseline: the capital-weighted mean over the SAME returns but
        # with ZERO external flows (capital weighted purely by compounding, no
        # depositor timing). The behavior gap is measured against THIS baseline so
        # that all-zero flows give an EXACTLY ZERO gap for any return path — the gap
        # isolates flow TIMING, not the geometric-vs-arithmetic compounding artefact.
        neutral_caps, _nb, _nf = _simulate_balances(returns, None, initial_capital)
        sum_ncap = sum(neutral_caps)
        neutral_weighted = _safe_div(
            sum(c * r for c, r in zip(neutral_caps, returns)),
            sum_ncap, sentinel=None)
        if neutral_weighted is None or not math.isfinite(neutral_weighted):
            return self._insufficient(token)
        neutral_dwr_period_pct = neutral_weighted
        neutral_dwr_apr_pct = neutral_dwr_period_pct * ppy

        if not (math.isfinite(dwr_apr_pct) and math.isfinite(neutral_dwr_apr_pct)):
            return self._insufficient(token)

        twr_period_pct = twr_period * 100.0

        return self._finish(
            token=token,
            twr_apr_pct=twr_apr_pct,
            dwr_apr_pct=dwr_apr_pct,
            gap_baseline_apr_pct=neutral_dwr_apr_pct,
            twr_period_pct=twr_period_pct,
            dwr_period_pct=dwr_period_pct,
            returns=returns,
            flows=flows,
            capitals=capitals,
            initial_capital=initial_capital,
            ppy=ppy,
            n=n,
            used_samples=True,
            used_override=False,
        )

    # ── override path ─────────────────────────────────────────────────────────

    def _analyze_override(self, token: str, p: dict, n: int, ppy: float) -> dict:
        twr_o_raw = p.get("twr_apr_pct")
        dwr_o_raw = p.get("dollar_weighted_apr_pct")
        # Both are required on the override path — one alone cannot derive the other.
        if twr_o_raw is None or dwr_o_raw is None:
            return self._insufficient(token)
        twr_o = _coerce_num(twr_o_raw)
        dwr_o = _coerce_num(dwr_o_raw)
        if twr_o is None or dwr_o is None:
            return self._insufficient(token)

        # On the override path the two supplied APRs ARE the like-for-like pair, so
        # the gap baseline is the supplied TWR itself.
        return self._finish(
            token=token,
            twr_apr_pct=twr_o,
            dwr_apr_pct=dwr_o,
            gap_baseline_apr_pct=twr_o,
            twr_period_pct=None,
            dwr_period_pct=None,
            returns=None,
            flows=None,
            capitals=None,
            initial_capital=None,
            ppy=ppy,
            n=n,
            used_samples=False,
            used_override=True,
        )

    # ── shared finisher ─────────────────────────────────────────────────────────

    def _finish(
        self,
        token: str,
        twr_apr_pct: float,
        dwr_apr_pct: float,
        gap_baseline_apr_pct: float,
        twr_period_pct: Optional[float],
        dwr_period_pct: Optional[float],
        returns: Optional[List[float]],
        flows: Optional[List[float]],
        capitals: Optional[List[float]],
        initial_capital: Optional[float],
        ppy: float,
        n: int,
        used_samples: bool,
        used_override: bool,
    ) -> dict:
        # The behavior gap is the LIKE-FOR-LIKE gap between the flow-neutral baseline
        # (what a flow-neutral depositor over the same returns would realise) and the
        # actual dollar-weighted return — it isolates flow TIMING. With all-zero
        # flows the baseline equals the actual DWR → gap is EXACTLY zero (ALIGNED).
        behavior_gap_pct = gap_baseline_apr_pct - dwr_apr_pct
        base = gap_baseline_apr_pct

        # realization_ratio: fraction of the (flow-neutral) baseline the depositor
        # realises after their flow timing; gap_fraction: scale-free behaviour gap.
        if base > EPS:
            realization_ratio = _clamp(dwr_apr_pct / base, 0.0, 1.0)
            gap_fraction = _clamp(behavior_gap_pct / base, 0.0, 1.0)
        else:
            # Non-positive baseline: a gap is not meaningfully scale-free. Treat
            # near-equal / non-positive baseline as fully realised (no behavior gap
            # to discount); any divergence leans on flags below.
            realization_ratio = 1.0 if abs(behavior_gap_pct) <= EPS else (
                _clamp(dwr_apr_pct / base, 0.0, 1.0)
                if base < -EPS else 1.0)
            gap_fraction = 0.0

        depositor_return_negative = (dwr_apr_pct < 0.0 and base > 0.0)

        # ── flow / capital descriptive metrics ──
        total_net_flow: Optional[float] = None
        peak_capital: Optional[float] = None
        mean_capital: Optional[float] = None
        flow_volatility: Optional[float] = None
        coefficient_of_variation: Optional[float] = None
        chasing_detected = False
        large_late_inflow = False
        flows_dominate = False
        stable_flows = False

        if used_samples and capitals is not None and returns is not None:
            peak_capital = max(capitals) if capitals else 0.0
            mean_capital = _mean(capitals)
            flow_list = flows if flows is not None else [0.0] * len(returns)
            total_net_flow = sum(flow_list)
            flow_volatility = _pstdev(flow_list)
            mean_flow = _mean(flow_list)
            if abs(mean_flow) > EPS:
                cov = flow_volatility / abs(mean_flow)
                coefficient_of_variation = (
                    round(cov, 4) if math.isfinite(cov) else None)
            # CHASING heuristic: positive correlation between a period's inflow and
            # the SUBSEQUENT period's return landing BELOW the mean return. We use a
            # simple deterministic sign-count: inflow (flow_i > 0) followed by a
            # below-mean next return counts as "chasing"; if the majority of positive
            # inflows precede below-mean returns, flag it.
            chasing_detected = self._detect_chasing(returns, flow_list)
            # LARGE_LATE_INFLOW: a single LATE (second half) positive flow that is
            # >= LARGE_LATE_INFLOW_FRAC of total positive flows.
            large_late_inflow = self._detect_large_late_inflow(flow_list)
            # FLOWS_DOMINATE: total positive flows >> initial capital.
            total_pos_flow = sum(f for f in flow_list if f > 0.0)
            if (initial_capital is not None and initial_capital > EPS
                    and total_pos_flow
                    >= FLOWS_DOMINATE_MULT * initial_capital):
                flows_dominate = True
            # STABLE_FLOWS: low flow coefficient of variation (steady contributions).
            if (coefficient_of_variation is not None
                    and coefficient_of_variation <= STABLE_FLOW_CV):
                stable_flows = True

        classification = self._classify(
            gap_fraction, depositor_return_negative, base)
        score = self._score(
            realization_ratio, flow_volatility, mean_capital, used_override)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags_out = self._flags(
            classification,
            depositor_return_negative,
            chasing_detected,
            large_late_inflow,
            flows_dominate,
            stable_flows,
            used_override,
        )

        return {
            "token": token,
            "twr_apr_pct": round(twr_apr_pct, 4),
            "dollar_weighted_apr_pct": round(dwr_apr_pct, 4),
            "gap_baseline_apr_pct": round(base, 4),
            "behavior_gap_pct": round(behavior_gap_pct, 4),
            "realization_ratio": round(realization_ratio, 4),
            "gap_fraction": round(gap_fraction, 4),
            "twr_period_pct": (
                round(twr_period_pct, 6) if twr_period_pct is not None else None),
            "dwr_period_pct": (
                round(dwr_period_pct, 6) if dwr_period_pct is not None else None),
            "total_net_flow": (
                round(total_net_flow, 4) if total_net_flow is not None else None),
            "peak_capital": (
                round(peak_capital, 4) if peak_capital is not None else None),
            "mean_capital": (
                round(mean_capital, 4) if mean_capital is not None else None),
            "flow_volatility": (
                round(flow_volatility, 4) if flow_volatility is not None else None),
            "coefficient_of_variation": coefficient_of_variation,
            "periods_per_year": round(ppy, 4),
            "sample_count": n,
            "used_samples": used_samples,
            "used_override": used_override,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags_out,
        }

    # ── chasing / inflow heuristics ─────────────────────────────────────────────

    def _detect_chasing(
        self, returns: List[float], flows: List[float]
    ) -> bool:
        """
        Deterministic "chasing" heuristic: capital that flows IN right before a
        below-average return period. For each period i with a POSITIVE inflow, look
        at the SUBSEQUENT period's return (i+1); if it lands BELOW the mean return,
        that inflow "chased" a streak that then cooled. If the MAJORITY of positive
        inflows (that have a following period) precede below-mean returns, flag it.
        Pure stdlib, no correlation library.
        """
        if len(returns) < 2:
            return False
        mean_r = _mean(returns)
        chasing = 0
        considered = 0
        for i in range(len(returns) - 1):
            if flows[i] > 0.0:
                considered += 1
                if returns[i + 1] < mean_r:
                    chasing += 1
        if considered == 0:
            return False
        return chasing > considered / 2.0

    def _detect_large_late_inflow(self, flows: List[float]) -> bool:
        """
        Flag a single LATE (second-half) positive flow that is >= a large fraction
        of all positive flows — a big chunk of capital arriving near the end of the
        window (the most behavior-gap-prone pattern).
        """
        total_pos = sum(f for f in flows if f > 0.0)
        if total_pos <= EPS:
            return False
        n = len(flows)
        half = n // 2  # second half indices: half .. n-1
        for i in range(half, n):
            if flows[i] > 0.0 and flows[i] >= LARGE_LATE_INFLOW_FRAC * total_pos:
                return True
        return False

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        realization_ratio: float,
        flow_volatility: Optional[float],
        mean_capital: Optional[float],
        used_override: bool,
    ) -> float:
        """
        0–100, HIGHER = the dollar-weighted return the depositor realises is close
        to the time-weighted headline (flow timing neutral/aligned). Two components:
          * realisation = clamp(realization_ratio, 0, 1) — how much of the headline
            TWR the average depositor actually keeps (1 → DWR ≈ TWR, 0 → DWR ≤ 0),
          * stability = clamp(1 − normalised_flow_vol, 0, 1), where
                normalised_flow_vol = flow_vol / (mean_capital + flow_vol + eps)
            penalises a jumpy flow path (large, lumpy contributions relative to the
            capital base are the source of behavior-gap risk).
        Weighted 70/30 toward realisation (it directly maps to the return a depositor
        keeps); flow stability corroborates how exposed the cohort is to timing. On
        the override path (no flow series) the stability component is NEUTRAL (full
        weight), matching how MP-1201 handles a missing volatility series.
        """
        realisation = _clamp(realization_ratio, 0.0, 1.0)
        if used_override or flow_volatility is None or mean_capital is None:
            stability = 1.0
        else:
            denom = abs(mean_capital) + flow_volatility + EPS
            normalised_flow_vol = _clamp(flow_volatility / denom, 0.0, 1.0)
            stability = _clamp(1.0 - normalised_flow_vol, 0.0, 1.0)
        return _clamp(70.0 * realisation + 30.0 * stability, 0.0, 100.0)

    def _classify(
        self,
        gap_fraction: float,
        depositor_return_negative: bool,
        twr_apr_pct: float,
    ) -> str:
        if depositor_return_negative:
            # DWR negative while TWR positive is the worst behavior gap.
            return "SEVERE_GAP"
        if twr_apr_pct <= EPS:
            # Non-positive headline: no meaningful positive behavior gap to grade.
            return "ALIGNED"
        if gap_fraction <= ALIGNED_FRACTION:
            return "ALIGNED"
        if gap_fraction <= MILD_FRACTION:
            return "MILD_GAP"
        if gap_fraction <= MODERATE_FRACTION:
            return "MODERATE_GAP"
        return "SEVERE_GAP"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_OR_VERIFY"
        if classification == "ALIGNED":
            return "TRUST_HEADLINE"
        if classification == "MILD_GAP":
            return "DISCOUNT_HEADLINE_SLIGHTLY"
        if classification == "MODERATE_GAP":
            return "DISCOUNT_HEADLINE"
        # SEVERE_GAP
        return "AVOID_OR_VERIFY"

    def _flags(
        self,
        classification: str,
        depositor_return_negative: bool,
        chasing_detected: bool,
        large_late_inflow: bool,
        flows_dominate: bool,
        stable_flows: bool,
        used_override: bool,
    ) -> List[str]:
        flags: List[str] = []

        # Classification flag (ALIGNED → ALIGNED_TIMING for good cases).
        if classification == "ALIGNED":
            flags.append("ALIGNED_TIMING")
        else:
            flags.append(classification)

        if depositor_return_negative:
            flags.append("DEPOSITOR_RETURN_NEGATIVE")
        # Sample-only flags must NOT appear on the override path.
        if not used_override:
            if chasing_detected:
                flags.append("CHASING_DETECTED")
            if large_late_inflow:
                flags.append("LARGE_LATE_INFLOW")
            if flows_dominate:
                flags.append("FLOWS_DOMINATE")
            if stable_flows:
                flags.append("STABLE_FLOWS")
        if used_override:
            flags.append("GAP_FROM_OVERRIDE")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "twr_apr_pct": None,
            "dollar_weighted_apr_pct": None,
            "gap_baseline_apr_pct": None,
            "behavior_gap_pct": None,
            "realization_ratio": None,
            "gap_fraction": None,
            "twr_period_pct": None,
            "dwr_period_pct": None,
            "total_net_flow": None,
            "peak_capital": None,
            "mean_capital": None,
            "flow_volatility": None,
            "coefficient_of_variation": None,
            "periods_per_year": None,
            "sample_count": 0,
            "used_samples": False,
            "used_override": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID_OR_VERIFY",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [
            r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "most_aligned_vault": None,
                "widest_gap_vault": None,
                "avg_score": 0.0,
                "negative_depositor_count": 0,
                "position_count": len(results),
            }
        # Higher score = DWR ≈ TWR → highest score is most aligned.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        negative = sum(
            1 for r in results
            if "DEPOSITOR_RETURN_NEGATIVE" in r.get("flags", []))
        return {
            "most_aligned_vault": by_score[-1]["token"],
            "widest_gap_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "negative_depositor_count": negative,
            "position_count": len(results),
        }

    # ── ring-buffer log ───────────────────────────────────────────────────────

    def _write_log(self, results: List[dict], agg: dict, cfg: dict) -> None:
        log_path = cfg["log_path"]
        cap = cfg["log_cap"]
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "position_count": len(results),
            "aggregate": agg,
            "snapshots": [
                {
                    "token": r["token"],
                    "classification": r["classification"],
                    "score": r["score"],
                    "recommendation": r["recommendation"],
                    "flags": r["flags"],
                }
                for r in results
            ],
        }

        log: List[dict] = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r") as fh:
                    log = json.load(fh)
                if not isinstance(log, list):
                    log = []
            except (json.JSONDecodeError, OSError):
                log = []

        log.append(entry)
        if len(log) > cap:
            log = log[-cap:]

        tmp = log_path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(log, fh, indent=2)
        os.replace(tmp, log_path)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _demo_positions() -> List[dict]:
    return [
        {
            # ALIGNED: zero flows and a flat return path → the dollar-weighted
            # per-period experience equals the time-weighted per-period return
            # exactly (no flow timing to create a behavior gap).
            "vault": "USDC-Vault-NoFlows",
            "period_returns": [2.0, 2.0, 2.0, 2.0, 2.0, 2.0],
            "periods_per_year": 12.0,
        },
        {
            # ALIGNED-ish: steady contributions across a stable return path.
            "vault": "stETH-Vault-SteadyDCA",
            "period_returns": [1.5, 1.6, 1.4, 1.55, 1.5, 1.45],
            "period_flows": [10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
            "initial_capital": 100.0,
            "periods_per_year": 12.0,
        },
        {
            # SEVERE_GAP: a big late inflow lands right before the yield mean-reverts
            # down — most capital experiences the low-return periods (behavior gap).
            "vault": "GOV-Vault-ChasedHotStreak",
            "period_returns": [6.0, 6.5, 6.0, 0.5, 0.4, 0.3],
            "period_flows": [0.0, 0.0, 1000.0, 0.0, 0.0, 0.0],
            "initial_capital": 50.0,
            "periods_per_year": 12.0,
        },
        {
            # Override path: TWR + DWR supplied directly (a moderate behavior gap).
            "vault": "LST-Vault-OverrideGap",
            "twr_apr_pct": 30.0,
            "dollar_weighted_apr_pct": 18.0,
        },
        {
            # INSUFFICIENT_DATA: only one return sample and no full override.
            "vault": "MYSTERY-Vault-NoData",
            "period_returns": [2.0],
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1202 Vault Dollar-Weighted Return Gap Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultDollarWeightedReturnGapAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
