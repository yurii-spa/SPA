"""Portfolio of Return Sources — PAPER (CAPITAL-SOURCES-01 §10–§12, ADR-641).

One module, three pure answers over the ADR-640 Capital Sources contract:

  * :func:`assess`   — the Oracle's multi-source eligibility verdict per source (§11): source type, maturity,
    NET return (never gross), drawdown, risk, correlation, evidence duration, confidence, freshness. A source
    either "would qualify for up to X % PAPER allocation under current evidence" or "does not qualify: <blockers>".
    X is a CAP the evidence permits, not a recommendation; weights stay with the ADR-554 policy, which never
    executes and still excludes every source the contract marks ``allocatable=False``.
  * :func:`paper_portfolio` — the paper NAV of a set of weights over the sources' own daily return series (§10):
    weights, contribution, net return, max drawdown, volatility, Sharpe/Sortino (≥30 days only), correlation
    matrix, diversification and risk contribution, cash, evidence maturity. A non-zero weight on a source the
    assessment does not admit is REFUSED (fail-closed), never "just small".
  * :func:`frontier` — the §12 research objective "≈10–15 % annualised NET without unacceptable drawdown?" as a
    typed frontier: REALIZED_PAPER points (evidence), MIXED/BACKTEST hypothetical points (never evidence, never
    allocation), and the sources that are NOT_MEASURED. The verdict is computed, and is allowed to be NO.

Everything here is a pure function of its inputs (no files, no clock besides the ``as_of`` handed in, no RNG):
the same inputs give byte-identical output. The loaders that READ files (:func:`load_inputs`) are separate and
only run inside the Oracle's daily build, whose output is snapshotted — so every figure is reproducible from
the snapshot.

Boundary (unchanged by this module): REAL CAPITAL = $0, ``executes`` is always False, no import of
``spa_core.execution``; a document that claims real capital or a non-PAPER mode is refused as a whole.

# LLM_FORBIDDEN — deterministic statistics and rules over already-measured, typed figures.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from spa_core.investment_cio import contract

SCHEMA_VIEW = "capital-sources-view/1"
MS_POLICY_VERSION = "multi-source-v1"

#: Multi-source parameters. Maturity thresholds and caps are the ADR-554 ones (reused, not invented); the
#: Trading Alpha mechanism cap is NEW and uncalibrated (ADR-641) — a directional book never gets more than this
#: share of the paper portfolio from this policy version, whatever its evidence.
MS_POLICY: Dict[str, Any] = {
    "version": MS_POLICY_VERSION,
    "maturity_developing_min_days": contract.POLICY["maturity_developing_min"],   # 30
    "maturity_mature_min_days": contract.POLICY["maturity_mature_min"],           # 90
    "cap_developing": contract.POLICY["cap_developing"],                          # 0.20
    "cap_mature": contract.POLICY["cap_mature"],                                  # 0.50
    "mechanism_caps": {"directional_trading": 0.10, "leveraged_loop": 0.10},
    "cash_floor": contract.POLICY["cash_floor"],                                  # 0.05
    "min_days_for_rate": 30,                                                      # ADR-590 §4
    "correlation_min_overlap_days": contract.POLICY["correlation_min_overlap_days"],
    "correlation_min_distinct_returns": contract.POLICY["correlation_min_distinct_returns"],
    "research_target_net_annual": [0.10, 0.15],                                   # §12 — a QUESTION, not a goal
    "unacceptable_drawdown": -0.10,                                               # = HARD_KILL (ADR-034/048)
}

_MECHANISM_BY_SOURCE = {sid: v.get("mechanism_class") for sid, v in contract.SLEEVES.items()}
_MECHANISM_BY_SOURCE["trading_alpha"] = "directional_trading"


class PaperBoundaryRefused(Exception):
    """A document claims real capital / a non-PAPER mode / execution — refused as a whole (fail-CLOSED)."""


class AllocationRefused(Exception):
    """A weight was asked for a source the multi-source assessment does not admit — refused, never clipped."""


# ── small helpers ──────────────────────────────────────────────────────────────────────────────────────────
def _val(cell: Any) -> Any:
    return contract.value_of(cell)


def _state(cell: Any) -> Optional[str]:
    return cell.get("state") if isinstance(cell, dict) else None


def _num(x: Any) -> Optional[float]:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) else None


def _r(x: float, nd: int = 8) -> float:
    return round(float(x), nd)


def _m(value: Any, *, unit: Optional[str], n: Optional[int] = None, note: Optional[str] = None,
       kind: Optional[str] = None) -> Dict:
    c = contract.measured(value, unit=unit, source="investment_cio.sources_portfolio", as_of=None, n=n, note=note)
    if kind:
        c["kind"] = kind
    return c


def _a(state: str, reason: str, n: Optional[int] = None) -> Dict:
    return contract.absent(state, reason=reason, source="investment_cio.sources_portfolio", n=n)


def _check_paper_boundary(registry: Dict) -> None:
    if not isinstance(registry, dict):
        raise PaperBoundaryRefused("capital sources registry missing or unreadable")
    rc = registry.get("real_capital_usd", 0)
    if rc is not None and (isinstance(rc, bool) or not isinstance(rc, (int, float)) or rc != 0):
        raise PaperBoundaryRefused(f"registry real_capital_usd={rc!r} — this policy is PAPER only ($0)")
    if registry.get("executes") not in (False, None):
        raise PaperBoundaryRefused("registry claims execution authority — refused")
    if registry.get("capital_mode") not in ("PAPER", None):
        raise PaperBoundaryRefused(f"registry capital_mode={registry.get('capital_mode')!r} — PAPER only")
    for s in registry.get("sources") or []:
        if s.get("capital_mode") != "PAPER":
            raise PaperBoundaryRefused(f"source {s.get('source_id')} capital_mode={s.get('capital_mode')!r} — "
                                       "a live flag on any source refuses the whole assessment")
        if s.get("live") or s.get("live_enabled"):
            raise PaperBoundaryRefused(f"source {s.get('source_id')} carries a live flag — refused")


def _evidence_days(src: Dict) -> Optional[float]:
    """Calendar days of evidence for the CURRENT economics. DeFi: valid_periods (one per day); Trading Alpha:
    sleeve calendar days. Observation counts are NOT days (§8)."""
    return _num(_val(src.get("evidence_days")))


def _is_stale(src: Dict) -> Tuple[bool, Optional[str]]:
    f = src.get("freshness")
    if _state(f) == contract.STALE:
        return True, f"freshness STALE ({f.get('reason')})"
    v = _val(f)
    if isinstance(v, dict) and v.get("state") == "STALE":
        return True, f"freshness STALE (last {v.get('last_tick') or v.get('as_of')}, age {v.get('age_hours')} h)"
    return False, None


def _net_return_problem(src: Dict) -> Optional[str]:
    """Oracle uses NET return only (§7, §11). Accepted: a measured cumulative ``net_return``, or — for a book
    that publishes no cumulative figure (capital basis not measured) — its measured annualised REALIZED rate,
    which is net of the book's modelled costs (ADR-593). Refused: a figure labelled gross under the net name,
    or a net figure ABOVE the gross one (impossible with non-negative costs)."""
    net, gross, ann = src.get("net_return"), src.get("gross_return"), src.get("annualized_return")
    cell = net if _state(net) == contract.MEASURED else (ann if _state(ann) == contract.MEASURED else None)
    if cell is None:
        return (f"net return not measured (cumulative {_state(net) or 'missing'}, annualised "
                f"{_state(ann) or 'missing'}) — gross is never used")
    # the label test reads ONLY the descriptive fields (unit/kind), never free-text notes: a note may say
    # anything («net of costs» next to a gross figure must not whitelist it — review 07.10)
    label = " ".join(str(cell.get(k) or "") for k in ("unit", "kind")).lower()
    if "gross" in label:
        return "the return offered as net is labelled gross — refused (Oracle consumes NET return only)"
    nv, gv = _num(cell.get("value")), _num(_val(gross))
    if nv is None:
        return "net return value not numeric"
    if cell is net and gv is not None and nv > gv + 1e-9:
        return f"net_return {nv} exceeds gross_return {gv} — a gross figure under the net name; refused"
    if cell is ann:
        # the annualised fallback must ALSO not exceed a gross figure where one exists (cumulative gross is not
        # comparable to an annual rate, so compare like with like: only an annualised gross can refuse it)
        g_ann = _num(_val(src.get("annualized_gross_return")))
        if g_ann is not None and nv > g_ann + 1e-9:
            return f"annualised net {nv} exceeds annualised gross {g_ann}; refused"
    return None


def _cap_for(sid: str, days: Optional[float]) -> Optional[float]:
    if days is None or days < MS_POLICY["maturity_developing_min_days"]:
        return None
    cap = MS_POLICY["cap_mature"] if days >= MS_POLICY["maturity_mature_min_days"] else MS_POLICY["cap_developing"]
    mcap = MS_POLICY["mechanism_caps"].get(_MECHANISM_BY_SOURCE.get(sid))
    return min(cap, mcap) if mcap is not None else cap


# ── §11 assessment ─────────────────────────────────────────────────────────────────────────────────────────
def assess(registry: Dict) -> Dict:
    """Per-source multi-source verdict. Pure. Raises PaperBoundaryRefused on a live/real-capital claim."""
    _check_paper_boundary(registry)
    out: Dict[str, Dict] = {}
    for src in registry.get("sources") or []:
        sid = src.get("source_id")
        stype = src.get("source_type")
        if sid == "cash":
            out[sid] = {"source_type": stype, "qualifies": True, "max_paper_weight": 1.0, "blockers": [],
                        "statement": "cash (paper, uninvested) — always admissible; the policy keeps ≥ "
                                     f"{MS_POLICY['cash_floor']:.0%}"}
            continue
        blockers: List[str] = []
        days = _evidence_days(src)
        if days is None:
            blockers.append("evidence duration NOT_MEASURED")
        elif days < MS_POLICY["maturity_developing_min_days"]:
            blockers.append(f"immature: {days:g} days of evidence < {MS_POLICY['maturity_developing_min_days']}")
        np_ = _net_return_problem(src)
        if np_:
            blockers.append(np_)
        stale, why = _is_stale(src)
        if stale:
            blockers.append(why)
        if _state(src.get("drawdown")) != contract.MEASURED:
            blockers.append(f"drawdown {_state(src.get('drawdown')) or 'missing'}")
        for b in src.get("blockers") or []:   # the source's own blockers (unknown costs, gates, maturity)
            if b not in blockers:
                blockers.append(b)
        cap = _cap_for(sid, days)
        qualifies = not blockers and cap is not None
        if qualifies:
            statement = (f"{src.get('name')} would qualify for up to {cap:.0%} PAPER allocation under current "
                         f"evidence ({days:g} days, NET return measured) — a cap, not a recommendation")
            if src.get("status") == "RESEARCH_ONLY":
                statement += "; the ADR-554 contract keeps it research-only (allocatable=False) until an ADR"
        else:
            statement = f"{src.get('name')} does not qualify: " + "; ".join(blockers[:6]) + \
                        (f" (+{len(blockers) - 6} more)" if len(blockers) > 6 else "")
        out[sid] = {"source_type": stype, "qualifies": qualifies,
                    "max_paper_weight": cap if qualifies else 0.0,
                    "evidence_days": days, "net_return": _val(src.get("net_return")),
                    "annualized_return": _val(src.get("annualized_return")),
                    "drawdown": _val(src.get("drawdown")),
                    "confidence": _val(src.get("confidence")),
                    "blockers": blockers, "statement": statement}
    return {"policy_version": MS_POLICY_VERSION, "by_source": dict(sorted(out.items())),
            "qualifying": sorted(k for k, v in out.items() if v["qualifies"] and k != "cash"),
            "executes": False, "real_capital_usd": 0}


# ── series statistics ──────────────────────────────────────────────────────────────────────────────────────
def _calendar_span(dates: List[str]) -> Tuple[int, int]:
    """(calendar days covered, number of missing dates inside the window) — annualisation uses CALENDAR time,
    never the observation count; a gap is reported, not hidden."""
    if not dates:
        return 0, 0
    d0 = datetime.strptime(dates[0], "%Y-%m-%d")
    d1 = datetime.strptime(dates[-1], "%Y-%m-%d")
    span = (d1 - d0).days + 1
    return span, span - len(dates)


def _stats(rets: List[float], *, days: int) -> Dict:
    """``days`` = CALENDAR days covered by the returns (not their count)."""
    nav, peak, mdd = 1.0, 1.0, 0.0
    for r in rets:
        nav *= 1.0 + r
        peak = max(peak, nav)
        mdd = min(mdd, nav / peak - 1.0)
    n = len(rets)
    out = {"nav": _m(_r(nav), unit="paper NAV units (1.0 at window start)", n=n),
           "net_return": _m(_r(nav - 1.0), unit="fraction, cumulative over the window", n=n, kind="NET"),
           "max_drawdown": _m(_r(mdd), unit="fraction", n=n)}
    if days >= MS_POLICY["min_days_for_rate"] and n >= 2:
        mu = sum(rets) / n
        sd = math.sqrt(sum((r - mu) ** 2 for r in rets) / n)
        dn = math.sqrt(sum(min(0.0, r) ** 2 for r in rets) / n)
        out["annualized_return"] = _m(_r(nav ** (365.0 / days) - 1.0), unit="fraction per year, compound", n=n,
                                      kind="NET")
        out["volatility"] = _m(_r(sd * math.sqrt(365)), unit="fraction per year", n=n)
        out["sharpe"] = (_m(_r(mu / sd * math.sqrt(365), 4), unit="ratio, rf=0", n=n) if sd > 0 else
                         _a(contract.UNDEFINED, "zero volatility over the window", n=n))
        out["sortino"] = (_m(_r(mu / dn * math.sqrt(365), 4), unit="ratio, rf=0", n=n) if dn > 0 else
                          _a(contract.UNDEFINED, "no down day in the window", n=n))
    else:
        why = f"{days} day(s) < {MS_POLICY['min_days_for_rate']} (ADR-590 §4: no annualised figure)"
        for k in ("annualized_return", "volatility", "sharpe", "sortino"):
            out[k] = _a(contract.NOT_ENOUGH_HISTORY, why, n=n)
    return out


def _pearson(xs: List[float], ys: List[float]) -> Optional[float]:
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = sum((x - mx) ** 2 for x in xs)
    sy = sum((y - my) ** 2 for y in ys)
    if sx == 0 or sy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(sx * sy)


def _corr_cell(a: Dict[str, float], b: Dict[str, float]) -> Dict:
    common = sorted(set(a) & set(b))
    n = len(common)
    if n < MS_POLICY["correlation_min_overlap_days"]:
        return _a(contract.NOT_ENOUGH_HISTORY,
                  f"only {n} overlapping day(s) < {MS_POLICY['correlation_min_overlap_days']}", n=n)
    xs, ys = [a[d] for d in common], [b[d] for d in common]
    if min(len(set(xs)), len(set(ys))) < MS_POLICY["correlation_min_distinct_returns"]:
        return _a(contract.UNDEFINED, "too few distinct daily returns (constant accrual)", n=n)
    r = _pearson(xs, ys)
    if r is None:
        return _a(contract.UNDEFINED, "zero variance", n=n)
    return _m(_r(r, 4), unit="pearson on daily returns", n=n)


def correlation_matrix(series: Dict[str, Optional[Dict[str, float]]]) -> Dict:
    ids = sorted(series)
    out: Dict[str, Dict[str, Any]] = {}
    for i in ids:
        out[i] = {}
        for j in ids:
            if i == j:
                continue
            si, sj = series.get(i), series.get(j)
            if not si or not sj:
                missing = [k for k, s in ((i, si), (j, sj)) if not s]
                out[i][j] = _a(contract.NOT_MEASURED, f"no daily return series for {missing}", n=0)
            else:
                out[i][j] = _corr_cell(si, sj)
    return out


# ── §10 paper portfolio ────────────────────────────────────────────────────────────────────────────────────
#: diversification credit is only computed above these: accrual returns barely move, and a ratio of two
#: near-zero volatilities is noise, not diversification (review 07.10)
DIVERSIFICATION_MIN_VOL = 1e-4              # daily σ of a risky source (≈1.9 % annualised)
DIVERSIFICATION_MIN_DISTINCT = 10           # distinct daily returns per risky source


def _history_lookup(history: Any):
    """Weight history → lookup(date) -> weights or None. Two shapes:
      * compact (what the Oracle snapshot stores): {"coverage": [first, last], "changes": [{"date", "weights"}]}
        — a step function over the ledger's own coverage (one row per CHANGE, so the snapshot stays small);
      * plain {date: weights} (tests, ad-hoc callers)."""
    if not history:
        return lambda d: None
    if isinstance(history, dict) and "changes" in history:
        cov = history.get("coverage") or [None, None]
        changes = sorted(history.get("changes") or [], key=lambda r: r["date"])

        def look(d: str):
            if not cov[0] or not cov[1] or not (cov[0] <= d <= cov[1]):
                return None
            cur = None
            for r in changes:
                if r["date"] <= d:
                    cur = r["weights"]
                else:
                    break
            return cur
        return look
    return lambda d: history.get(d)


def _causal_weight_fn(sid: str, final_weight: float, evidenced_dates: List[str], history: Any):
    """weight DECIDED on date d, as it was knowable then — never today's cap applied backwards (review P1-1):
      * the Oracle's own recommendation for d if the ledger covers d, else
      * the policy cap ladder by EVIDENCED days on d — the same count assess() uses (one per evidenced
        observation, gaps do not count): 0 below 30, the DEVELOPING cap to 89, the MATURE cap from 90 —
        never above the weight the policy uses today.
    The caller applies the weight decided on d to the return of the NEXT observation (a decision taken at or
    after d's close cannot earn d's return)."""
    look = _history_lookup(history)
    ev = sorted(evidenced_dates)

    def w_at(d: str) -> Tuple[float, str]:
        h = look(d)
        if h is not None:
            return float(h.get(sid, 0.0)), "oracle_ledger"
        days = sum(1 for x in ev if x <= d)
        if days == 0:
            return 0.0, "no_evidence"
        cap = _cap_for(sid, days)
        return (min(final_weight, cap) if cap is not None else 0.0), "cap_ladder"
    return w_at


def paper_portfolio(registry: Dict, series: Dict[str, Optional[Dict[str, float]]], weights: Dict[str, float],
                    *, as_of: str, assessment: Optional[Dict] = None, basis: str = "",
                    weight_history: Optional[Dict[str, Dict[str, float]]] = None) -> Dict:
    """Paper NAV of a portfolio over each source's own daily returns, truncated to dates ≤ ``as_of``. Pure.

    ``weights`` are the weights the policy uses TODAY; they are validated against today's assessment (a weight
    on a source that does not qualify, or above its cap, is refused — never clipped). The NAV PATH is causal:
    on each past date the weight is the one knowable then (:func:`_causal_weight_fn`) — the Oracle ledger's
    own recommendation for that date if ``weight_history`` has it, else the cap ladder by evidence age at that
    date. The difference between «today's weights from day 1» and this path was the lookahead the review found.
    Raises AllocationRefused / PaperBoundaryRefused."""
    _check_paper_boundary(registry)
    assessment = assessment or assess(registry)
    by = assessment["by_source"]
    w = {k: float(v) for k, v in (weights or {}).items() if _num(v) is not None and float(v) > 0}
    for sid, wt in sorted(w.items()):
        if sid == "cash":
            continue
        if sid not in by or not by[sid]["qualifies"]:
            raise AllocationRefused(f"{sid}: weight {wt} asked for a source that does not qualify "
                                    f"({'; '.join((by.get(sid) or {}).get('blockers') or ['unknown source'])})")
        if wt > by[sid]["max_paper_weight"] + 1e-9:
            raise AllocationRefused(f"{sid}: weight {wt} exceeds its evidence cap {by[sid]['max_paper_weight']}")
    total = sum(w.values())
    if total > 1.0 + 1e-6:
        raise AllocationRefused(f"weights sum to {total} > 1")
    cash = 1.0 - sum(v for k, v in w.items() if k != "cash")
    risky = sorted(k for k in w if k != "cash")
    day = as_of[:10]
    if not risky:
        return {"basis": basis, "weights": {"cash": 1.0}, "cash": 1.0, "window": None,
                "note": "no qualifying risk source: the paper portfolio is 100 % cash (earns nothing in the model "
                        "— no treasury source evidence exists)",
                "metrics": {k: _a(contract.NOT_MEASURED, "nothing invested") for k in
                            ("nav", "net_return", "max_drawdown", "annualized_return", "volatility", "sharpe",
                             "sortino")},
                "contribution": {}, "risk_contribution": {}, "diversification": _a(contract.NOT_MEASURED,
                                                                                  "nothing invested"),
                "maturity": {}, "weight_path": []}
    missing = [k for k in risky if not series.get(k)]
    if missing:
        raise AllocationRefused(f"weighted source(s) {missing} publish no daily return series — refused")
    dates = sorted(set.intersection(*[set(d for d in series[k] if d <= day) for k in risky]))
    if not dates:
        raise AllocationRefused(f"no common dated window ≤ {day} across {risky}")
    src_views = {s.get("source_id"): s for s in registry.get("sources") or []}
    wfn = {k: _causal_weight_fn(k, w[k], [d for d in series[k] if d <= day], weight_history) for k in risky}
    # the weight that EARNS date d's return is the one decided on the PREVIOUS observation date; nothing was
    # decided before the first one, so the first return is earned at weight 0 (review: one-observation shift)
    wt_at, basis_at = {}, {}
    for i, d in enumerate(dates):
        if i == 0:
            wt_at[d], basis_at[d] = {k: 0.0 for k in risky}, ["nothing_decided_before_first_observation"]
        else:
            prev = dates[i - 1]
            wt_at[d] = {k: wfn[k](prev)[0] for k in risky}
            basis_at[d] = sorted({wfn[k](prev)[1] for k in risky})
    port = [sum(wt_at[d][k] * series[k][d] for k in risky) for d in dates]   # cash leg returns 0 by construction
    span, gaps = _calendar_span(dates)
    metrics = _stats(port, days=span)
    contribution = {k: _m(_r(sum(wt_at[d][k] * series[k][d] for d in dates)), unit="fraction, arithmetic sum of w·r",
                          n=len(dates)) for k in risky}
    contribution["cash"] = _m(0.0, unit="fraction", n=len(dates), note="uninvested paper cash earns nothing in "
                                                                       "the model")
    # weight path: one row per change (compact), what was knowable and on what basis
    path, prev = [], None
    for d in dates:
        row = {k: _r(v, 6) for k, v in wt_at[d].items()}
        if (row, basis_at[d]) != prev:
            path.append({"from": d, "weights": row, "basis": basis_at[d]})
            prev = (row, basis_at[d])
    risk_contrib: Dict[str, Dict] = {}
    n = len(dates)
    mp = sum(port) / n
    var_p = sum((x - mp) ** 2 for x in port) / n
    sig, distinct = {}, {}
    for k in risky:
        xs = [series[k][d] for d in dates]
        mk = sum(xs) / n
        sig[k] = math.sqrt(sum((x - mk) ** 2 for x in xs) / n)
        distinct[k] = len(set(xs))
        if span < MS_POLICY["min_days_for_rate"]:
            risk_contrib[k] = _a(contract.NOT_ENOUGH_HISTORY, f"{span} day(s) < {MS_POLICY['min_days_for_rate']}",
                                 n=n)
        elif var_p <= 0:
            risk_contrib[k] = _a(contract.UNDEFINED, "portfolio variance is zero", n=n)
        else:
            cov = sum((series[k][d] - mk) * (port[i] - mp) for i, d in enumerate(dates)) / n
            wk = sum(wt_at[d][k] for d in dates) / n
            risk_contrib[k] = _m(_r(wk * cov / var_p, 6), unit="share of portfolio variance (mean weight)", n=n)
    if span < MS_POLICY["min_days_for_rate"]:
        divers = _a(contract.NOT_ENOUGH_HISTORY, f"{span} day(s) < {MS_POLICY['min_days_for_rate']}", n=n)
    elif len(risky) < 2:
        divers = _m({"ratio": 1.0, "credit": 0.0}, unit=None, n=n,
                    note="one risk source: nothing to diversify (credit 0, by construction)")
    elif any(sig[k] < DIVERSIFICATION_MIN_VOL or distinct[k] < DIVERSIFICATION_MIN_DISTINCT for k in risky):
        low = [k for k in risky if sig[k] < DIVERSIFICATION_MIN_VOL or distinct[k] < DIVERSIFICATION_MIN_DISTINCT]
        divers = _a(contract.UNDEFINED, f"accrual-like series {low}: daily σ < {DIVERSIFICATION_MIN_VOL} or fewer "
                                        f"than {DIVERSIFICATION_MIN_DISTINCT} distinct returns — a ratio of near-zero "
                                        "volatilities is not diversification", n=n)
    else:
        wbar = {k: sum(wt_at[d][k] for d in dates) / n for k in risky}
        wsig = sum(wbar[k] * sig[k] for k in risky)
        sp = math.sqrt(var_p)
        if wsig <= 0 or sp <= 0:
            divers = _a(contract.UNDEFINED, "zero volatility", n=n)
        else:
            divers = _m({"ratio": _r(wsig / sp, 6), "credit": _r(max(0.0, 1.0 - sp / wsig), 6)}, unit=None, n=n,
                        note="ratio = Σw̄σ / σ_p (mean weights); credit = 1 − σ_p/Σw̄σ (0 when the sources move as one)")
    maturity = {k: {"evidence_days": by[k]["evidence_days"], "qualifies": by[k]["qualifies"]} for k in risky}
    return {"basis": basis, "weights": {k: _r(v, 6) for k, v in sorted(w.items())} | {"cash": _r(cash, 6)},
            "weights_meaning": "the weights the policy uses TODAY; the NAV path uses the weights knowable on each "
                               "date (weight_path)",
            "cash": _r(cash, 6),
            "window": {"from": dates[0], "to": dates[-1], "observations": n, "calendar_days": span,
                       "missing_dates": gaps},
            "weight_path": path,
            "reconstruction": ("CAUSAL: the weight decided on each observation date (Oracle ledger where it covers the "
                               "date, else the policy cap ladder by EVIDENCED days then: 0 below 30, 20 % to 89, 50 % "
                               "from 90; never above today's weight) earns the NEXT observation's return"),
            "metrics": metrics, "contribution": contribution, "risk_contribution": risk_contrib,
            "diversification": divers, "maturity": maturity,
            "metrics_caveat": ("volatility, Sharpe and Sortino are computed on daily ACCRUAL returns: the DeFi books "
                               "have 0 % mark-to-market coverage (ADR-554), so these understate risk and are not a "
                               "risk measure; the drawdown that matters is the stop/stress worst case, not this"),
            "note": "PAPER only — reproduced from each source's own daily returns; no real capital, no execution"}


# ── §12 frontier ───────────────────────────────────────────────────────────────────────────────────────────
FRONTIER_MAX_EVIDENCED_SOURCES = 4      # grid combinations grow as 10^k; beyond this the grid is refused
FRONTIER_STEP = 0.1


def _grid(step: float, cap: float) -> List[float]:
    out, x = [], 0.0
    while x <= cap + 1e-9:
        out.append(round(x, 6))
        x += step
    return out


def _efficient(points: List[Dict]) -> List[Dict]:
    """Keep only points no other point dominates (higher-or-equal return AND shallower-or-equal drawdown,
    one strictly better) — the stored frontier stays small whatever the grid size."""
    keep = []
    for p in points:
        r, d = p.get("annualized_net"), p.get("max_drawdown")
        if r is None or d is None:
            continue
        dominated = any(q is not p and q.get("annualized_net") is not None and q.get("max_drawdown") is not None
                        and q["annualized_net"] >= r and q["max_drawdown"] >= d
                        and (q["annualized_net"] > r or q["max_drawdown"] > d) for q in points)
        if not dominated:
            keep.append(p)
    return sorted(keep, key=lambda p: (p["annualized_net"], p["max_drawdown"]))


def frontier(registry: Dict, series: Dict[str, Optional[Dict[str, float]]], *, as_of: str,
             assessment: Optional[Dict] = None, trading_backtest: Optional[Dict] = None) -> Dict:
    """§12: can a diversified portfolio of independently evidenced sources reach ≈10–15 % NET a year without
    unacceptable drawdown? Typed points only; the verdict reads REALIZED_PAPER points WITHIN policy caps and
    nothing else. Static weights over the window (a what-if of fixed weights, labelled so)."""
    _check_paper_boundary(registry)
    assessment = assessment or assess(registry)
    by = assessment["by_source"]
    day = as_of[:10]
    lo, hi = MS_POLICY["research_target_net_annual"]
    dd_limit = MS_POLICY["unacceptable_drawdown"]
    evidenced = [k for k in sorted(by) if k != "cash" and by[k]["qualifies"] and series.get(k)]
    realized_points: List[Dict] = []
    grid_note = None
    if len(evidenced) > FRONTIER_MAX_EVIDENCED_SOURCES:
        grid_note = (f"{len(evidenced)} evidenced sources > {FRONTIER_MAX_EVIDENCED_SOURCES}: the 10^k grid is not "
                     "run (bounded size); the verdict is UNKNOWN until a bounded search replaces it")
        evidenced = []
    window = None
    if evidenced:
        dates = sorted(set.intersection(*[set(d for d in series[k] if d <= day) for k in evidenced]))
        span, gaps = _calendar_span(dates)
        window = {"from": dates[0] if dates else None, "to": dates[-1] if dates else None,
                  "observations": len(dates), "calendar_days": span, "missing_dates": gaps}
        grids = [_grid(FRONTIER_STEP, 1.0 - MS_POLICY["cash_floor"]) for _ in evidenced]
        combos: List[Tuple[float, ...]] = [()]
        for g in grids:
            combos = [c + (x,) for c in combos for x in g]
        for combo in combos:
            if sum(combo) > 1.0 - MS_POLICY["cash_floor"] + 1e-9 or sum(combo) <= 0 or not dates:
                continue
            wts = dict(zip(evidenced, combo))
            rets = [sum(wts[k] * series[k][d] for k in evidenced) for d in dates]
            st = _stats(rets, days=span)
            within_caps = all(wts[k] <= by[k]["max_paper_weight"] + 1e-9 for k in evidenced)
            realized_points.append({"weights": {k: v for k, v in wts.items() if v > 0},
                                    "evidence_type": "REALIZED_PAPER (static weights over the window)",
                                    "within_policy_caps": within_caps,
                                    "annualized_net": _val(st["annualized_return"]),
                                    "max_drawdown": _val(st["max_drawdown"]),
                                    "volatility": _val(st["volatility"])})
    hypothetical: List[Dict] = []
    tb = trading_backtest or {}
    tb_series = tb.get("daily_returns") if isinstance(tb, dict) else None
    cons = series.get("defi_conservative")
    hyp_window = None
    if isinstance(tb_series, dict) and tb_series and cons:
        common = sorted(d for d in set(tb_series) & set(cons) if d <= day)
        span_h, gaps_h = _calendar_span(common)
        hyp_window = {"from": common[0] if common else None, "to": common[-1] if common else None,
                      "observations": len(common), "calendar_days": span_h, "missing_dates": gaps_h}
        lr = tb.get("long_run") or {}
        cons_src = next((x for x in registry.get("sources") or [] if x.get("source_id") == "defi_conservative"), {})
        cons_ann, cons_dd = _val(cons_src.get("annualized_return")), _val(cons_src.get("drawdown"))
        cons_cap = (by.get("defi_conservative") or {}).get("max_paper_weight", 0.0)
        ta_cap = MS_POLICY["mechanism_caps"]["directional_trading"]
        for wt in (0.0, 0.05, 0.10, 0.20, 0.30, 0.50):
            # DeFi at most its own cap (the rest stays cash) — a hypothetical point never breaches today's caps by
            # construction of the DeFi leg; the trading leg is flagged when it exceeds its mechanism cap
            wc = round(min(cons_cap, 1.0 - MS_POLICY["cash_floor"] - wt), 6)
            rets = [wc * cons[d] + wt * tb_series[d] for d in common]
            st = _stats(rets, days=span_h) if common else None
            bound = None
            if _num(lr.get("mean_oos_cagr")) is not None and _num(lr.get("mean_oos_max_drawdown")) is not None \
                    and _num(cons_ann) is not None and _num(cons_dd) is not None:
                # the tail a short window cannot show: members' long-run OOS drawdown, co-moving (ρ=1 bound)
                bound = {"annualized_net_approx": _r(wc * cons_ann + wt * lr["mean_oos_cagr"], 6),
                         "max_drawdown_bound_rho1": _r(wc * cons_dd + wt * lr["mean_oos_max_drawdown"], 6),
                         "basis": "BACKTEST long-run OOS member means (selection-biased) + REALIZED DeFi; ρ=1 "
                                  "worst-case drawdown bound"}
            hypothetical.append({
                "weights": {"defi_conservative": wc, "trading_alpha": wt},
                "within_policy_caps": wc <= cons_cap + 1e-9 and wt <= ta_cap + 1e-9,
                "evidence_type": "MIXED: REALIZED_PAPER DeFi + BACKTEST trading — hypothetical, never evidence, "
                                 "never allocation",
                "annualized_net": _val(st["annualized_return"]) if st else None,
                "max_drawdown": _val(st["max_drawdown"]) if st else None,
                "volatility": _val(st["volatility"]) if st else None,
                "long_run_bound": bound})
    trading_long_run = None
    if isinstance(tb, dict) and tb.get("long_run"):
        trading_long_run = dict(tb["long_run"])
        trading_long_run["evidence_type"] = "BACKTEST (out-of-sample window, 1× modelled costs)"
    not_measured = sorted(k for k in by if k != "cash" and not by[k]["qualifies"])
    in_cap = [p for p in realized_points if p["within_policy_caps"] and p["annualized_net"] is not None
              and p["max_drawdown"] is not None and p["max_drawdown"] >= dd_limit]
    best = max(in_cap, key=lambda p: p["annualized_net"], default=None)
    best_any = max((p for p in realized_points if p["annualized_net"] is not None),
                   key=lambda p: p["annualized_net"], default=None)
    hyp_hits = [p for p in hypothetical if p["within_policy_caps"] and p["annualized_net"] is not None
                and p["annualized_net"] >= lo and p["max_drawdown"] is not None and p["max_drawdown"] >= dd_limit]
    if best is None:
        answer = "UNKNOWN"
        text = ("No evidenced point with an annualised NET return exists yet (fewer than 30 calendar days or no "
                "qualifying source) — the question cannot be answered from evidence." + (f" {grid_note}." if grid_note
                                                                                          else ""))
    elif best["annualized_net"] >= lo:
        answer = "YES"
        text = (f"Evidenced points reach {best['annualized_net']:.2%} annualised NET within policy caps "
                f"({best['weights']}) and drawdown no worse than {dd_limit:.0%}.")
    else:
        answer = "NO"
        cash_in_best_any = round(1.0 - sum(best_any["weights"].values()), 6)
        text = (f"NO — current evidence supports at most {best['annualized_net']:.2%} annualised NET within policy "
                f"caps ({best['weights']}, the rest cash); even outside the caps the best grid point is "
                f"{best_any['annualized_net']:.2%} ({best_any['weights']}, {cash_in_best_any:.0%} cash). "
                f"{lo:.0%}–{hi:.0%} is not reached by any evidenced combination. Sources without qualifying evidence: "
                f"{', '.join(not_measured) or 'none'}.")
    if hyp_hits:
        worst = min((p["long_run_bound"]["max_drawdown_bound_rho1"] for p in hyp_hits if p.get("long_run_bound")),
                    default=None)
        text += (f" {len(hyp_hits)} hypothetical MIXED/BACKTEST point(s) within policy caps reach ≥{lo:.0%} over a "
                 f"{hyp_window['calendar_days']}-day window — backtest figures on selection-biased members, not "
                 "evidence" + (f"; their long-run tail bound reaches {worst:.1%} drawdown" if worst is not None else "")
                 + ".")
    return {"question": f"Can a diversified portfolio of independently evidenced return sources reach "
                        f"≈{lo:.0%}–{hi:.0%} annualised NET without unacceptable drawdown (worse than "
                        f"{dd_limit:.0%})?",
            "status": "RESEARCH_TARGET — not a public promise, not a target to force",
            "answer": answer, "verdict": text,
            "realized_window": window, "hypothetical_window": hyp_window,
            "realized_points": _efficient(realized_points),
            "realized_points_total": len(realized_points),
            "realized_best_within_caps": best, "realized_best_any": best_any,
            "hypothetical_points": hypothetical,
            "trading_backtest_long_run": trading_long_run,
            "not_measured_sources": not_measured,
            "rules": {"no_leverage_or_tail_increase_to_hit_a_number": True,
                      "verdict_reads_only": "REALIZED_PAPER points within policy caps",
                      "stored_points": "efficient (non-dominated) points only"}}


# ── one view for the Oracle record (pure) ──────────────────────────────────────────────────────────────────
def view(cs_inputs: Dict, oracle_weights: Dict[str, float], stance: str, alternatives: Dict,
         as_of: str) -> Dict:
    """The capital-sources part of the Oracle recommendation. Pure over the snapshotted inputs.

    Portfolio weights: the Oracle's own recommended weights when it recommends; otherwise its
    EVIDENCE_ONLY alternative (MATURE eligible sleeves, capped) — so the paper portfolio always uses the
    ADR-554 policy's weights, never a second allocator. Any of those weights on a source this assessment does
    not admit is refused (§15: an immature source never gets a non-zero allocation)."""
    registry = cs_inputs.get("registry") or {}
    series = cs_inputs.get("series") or {}
    try:
        assessment = assess(registry)
    except PaperBoundaryRefused as exc:
        return {"schema": SCHEMA_VIEW, "policy_version": MS_POLICY_VERSION, "state": "REFUSED",
                "reason": f"paper boundary: {exc}", "executes": False, "real_capital_usd": 0}
    if oracle_weights:
        weights, basis = dict(oracle_weights), f"Oracle recommended weights (stance {stance})"
    else:
        ev = ((alternatives or {}).get("EVIDENCE_ONLY") or {}).get("weights") or {"cash": 1.0}
        weights, basis = dict(ev), (f"Oracle EVIDENCE_ONLY alternative (stance {stance}: no recommendation, so the "
                                    "paper portfolio shows the evidence-only one — MATURE eligible sources, capped)")
    try:
        portfolio = paper_portfolio(registry, series, weights, as_of=as_of, assessment=assessment, basis=basis,
                                    weight_history=cs_inputs.get("weight_history"))
    except AllocationRefused as exc:
        portfolio = {"state": "REFUSED", "reason": str(exc), "basis": basis}
    sources_series = {k: v for k, v in series.items()}
    return {
        "schema": SCHEMA_VIEW, "policy_version": MS_POLICY_VERSION, "policy": MS_POLICY, "state": "MEASURED",
        "as_of": as_of, "capital_mode": "PAPER", "executes": False, "real_capital_usd": 0,
        "sources": [{k: s.get(k) for k in contract.CAPITAL_SOURCE_FIELDS} for s in registry.get("sources") or []],
        "assessment": assessment,
        "paper_portfolio": portfolio,
        "correlation_matrix": correlation_matrix(sources_series),
        "correlation_backtest_estimate": cs_inputs.get("correlation_backtest_estimate"),
        "frontier": frontier(registry, series, as_of=as_of, assessment=assessment,
                             trading_backtest=cs_inputs.get("trading_backtest")),
        "trading_alpha_refusal": cs_inputs.get("trading_alpha_refusal"),
        "previous_sleeve_check": cs_inputs.get("previous_sleeve_check"),
    }


# ── loaders (READ files; used only by the Oracle's daily build, whose output is snapshotted) ────────────────
def _epoch_day_to_date(k: str) -> Optional[str]:
    try:
        return datetime.fromtimestamp(int(k) * 86400, tz=timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _trading_backtest(data_dir: Path, members: List[str]) -> Optional[Dict]:
    """BACKTEST-typed view of the CURRENT sleeve members (admitted causally by the lifecycle — not chosen
    here by backtest result): their OOS daily returns, equal-weight across members. Selection-biased by
    construction (the members qualified on these OOS statistics) and labelled so."""
    import json
    if not members:
        return None
    try:
        doc = json.loads((Path(data_dir) / "trading_research" / "backtest.json").read_bytes())
    except (OSError, ValueError):
        return None
    rows = {r.get("id"): r for r in (doc.get("results") or []) if isinstance(r, dict)}
    picked = [rows[m] for m in members if m in rows and isinstance(rows[m].get("oos_daily_returns"), dict)]
    if not picked:
        return None
    per = []
    for r in picked:
        per.append({(_epoch_day_to_date(k)): float(v) for k, v in r["oos_daily_returns"].items()
                    if _epoch_day_to_date(k) and _num(v) is not None})
    days = sorted(set.intersection(*[set(p) for p in per]))
    daily = {d: sum(p[d] for p in per) / len(per) for d in days}
    oos = [r.get("out_of_sample") or {} for r in picked]

    def mean_of(key: str) -> Optional[float]:
        vals = [_num(o.get(key)) for o in oos]
        vals = [v for v in vals if v is not None]
        return _r(sum(vals) / len(vals), 6) if vals else None
    man = doc.get("manifest") or {}
    return {"members": [r.get("id") for r in picked], "daily_returns": daily,
            "long_run": {"members": len(picked), "mean_oos_cagr": mean_of("cagr"),
                         "mean_oos_max_drawdown": mean_of("max_drawdown"),
                         "mean_oos_volatility": mean_of("volatility"), "mean_oos_sharpe": mean_of("sharpe"),
                         "oos_years": mean_of("years"),
                         "backtest_generated_at_ms": man.get("generated_at_ms"),
                         "code_version": man.get("code_version"),
                         "caveat": "selection-biased: these members were admitted on these OOS statistics; "
                                   "BTC only, one regime period; equal-weight mean of member statistics, not a "
                                   "portfolio backtest"}}


def series_start(data_dir: Path, sleeves: Dict) -> Optional[str]:
    """Earliest dated daily return among the sources' own series — the start of any portfolio window."""
    from spa_core.investment_cio import correlation
    data_dir = Path(data_dir)
    firsts = []
    for s in (correlation._series_conservative(data_dir) if "defi_conservative" in (sleeves or {}) else None,
              correlation._series_from_daily_history(data_dir, "hy_paper_trading.json"),
              correlation._series_from_daily_history(data_dir, "lp_paper_trading.json")):
        if s:
            firsts.append(min(s))
    return min(firsts) if firsts else None


def weight_history_from_ledger(entries: List[Dict], *, since: Optional[str] = None) -> Dict:
    """The weights the Oracle stood behind each day (its recommendation, else its EVIDENCE_ONLY alternative —
    the basis the paper portfolio uses today), read from the immutable ledger, as a COMPACT step function:
    {"coverage": [first, last], "changes": [{"date", "weights"}]} — one row per change, restricted to dates
    ≥ ``since`` (the portfolio window), so the snapshot does not carry the whole ledger every day."""
    rows: List[Tuple[str, Dict[str, float]]] = []
    for e in entries or []:
        rec = (e or {}).get("recommendation") or {}
        d = rec.get("date")
        if not d or (since and d < since):
            continue
        w = rec.get("recommended_weights") or \
            (((rec.get("alternatives_considered") or {}).get("EVIDENCE_ONLY") or {}).get("weights")) or {}
        rows.append((d, {k: float(v) for k, v in sorted(w.items()) if _num(v) is not None}))
    rows.sort(key=lambda r: r[0])
    if not rows:
        return {}
    changes, prev = [], None
    for d, w in rows:
        if w != prev:
            changes.append({"date": d, "weights": w})
            prev = w
    return {"coverage": [rows[0][0], rows[-1][0]], "changes": changes,
            "source": "investment_cio ledger (immutable): recommended weights, else EVIDENCE_ONLY alternative"}


def load_inputs(data_dir: Path, sleeves: Dict, now: datetime, *, previous_alpha: Optional[Dict] = None,
                previous_check: Optional[Dict] = None, weight_history: Optional[Dict] = None) -> Dict:
    """Build the snapshot-able inputs: the Trading Alpha sleeve (from evidence.db, read-only), the Capital
    Sources registry and each source's daily return series. Never raises: a refused sleeve is recorded."""
    from spa_core.investment_cio import capital_sources, correlation
    from spa_core.trading_research import alpha_sleeve
    data_dir = Path(data_dir)
    now_ms = int(now.timestamp() * 1000)
    alpha, refusal = None, None
    try:
        alpha = alpha_sleeve.build_from_path(data_dir / "trading_research" / "evidence.db", as_of_ms=now_ms,
                                             now_ms=now_ms, previous=previous_alpha)
    except alpha_sleeve.SleeveRefused as exc:
        refusal = f"{exc.code}: {exc.detail}"
    except Exception as exc:  # noqa: BLE001 — a broken sleeve must not stop the Oracle; it is named instead
        refusal = f"UNEXPECTED: {type(exc).__name__}: {exc}"
    registry = capital_sources.registry(sleeves, trading_alpha=alpha, trading_alpha_refusal=refusal,
                                        generated_at=now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    cons = correlation._series_conservative(data_dir) if "defi_conservative" in sleeves else None
    series: Dict[str, Optional[Dict[str, float]]] = {
        "defi_conservative": cons,
        "defi_balanced": correlation._series_from_daily_history(data_dir, "hy_paper_trading.json"),
        "defi_aggressive": correlation._series_from_daily_history(data_dir, "lp_paper_trading.json"),
        "market_neutral_basis": None,
    }
    ta_daily = None
    if alpha and isinstance(alpha.get("daily_nav"), list):
        prev, ta_daily = 1.0, {}
        for row in alpha["daily_nav"]:
            v = _num(row.get("nav"))
            if v is None or prev <= 0:
                continue
            ta_daily[row["date"]] = v / prev - 1.0
            prev = v
    series["trading_alpha"] = ta_daily or None
    members = [m.get("candidate_id") for m in (alpha or {}).get("members") or [] if m.get("candidate_id")]
    tb = _trading_backtest(data_dir, members)
    corr_bt = None
    if tb and cons:
        corr_bt = _corr_cell(tb["daily_returns"], cons)
        corr_bt["kind"] = ("MIXED: BACKTEST trading (OOS, selection-biased) vs REALIZED_PAPER DeFi Conservative — "
                           "never used for allocation")
    return {"registry": registry, "series": series, "trading_alpha": alpha, "trading_alpha_refusal": refusal,
            "trading_backtest": tb, "correlation_backtest_estimate": corr_bt,
            "weight_history": weight_history or {},
            "previous_sleeve_check": previous_check or {"state": "NOT_MEASURED",
                                                        "reason": "no previous sleeve reference was supplied"}}
