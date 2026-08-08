"""Swarm — FORWARD paper book for the dwell-hysteresis latch (registry idea #36's control).

Charter: docs/DYNAMIC_LEVERAGE_GUARDIAN.md entry #36 (RARE) — RARE itself was refuted, but its
CONTROL survived every check that killed #35 and #37 on the real 10-book panel (852 days):

    dwell(k=2) on top of the SLOWEST exit signal ecdr#23(10/30):
      exit  : EMA_10(equity) < SMA_30(equity), both causal (through t−1)
      latch : once out, re-enter ONLY after 2 consecutive positive days (observed through t−1);
              an up-print never overrules a still-asserted trigger

    Full panel: maxDD −5.44% → −3.37%, APY 17.94% → 18.94% (net of #10 costs 17.62% — BELOW raw:
    the win is DRAWDOWN, not return), Calmar 3.30 → 5.62, switches 1.7 → 1.4/yr.
    k=2 was selected on the TRAIN half only (≤ 2025-06-30); on the unseen TEST half the latch's
    own contribution is ΔCalmar +4.10; leave-one-out positive in all 10 book-drop portfolios.

This module runs that rule FORWARD, daily, per owner decision on card
`own-rnd-dwell-hysteresis-paper-module` (variant 1). It reads the SAME live forward paper series
the fleet already produces — `data/aggressive_lab/<book>/realized_series.jsonl`, phase="forward"
rows ONLY — and keeps its own paper book `data/swarm/dwell_hysteresis_book.jsonl` (append-only,
hash-chained, one line per UTC day, idempotent per day).

Every line carries BOTH arms so the latch effect is measurable by construction:
  • baseline — ecdr#23(10/30) flag-only overlay (the latch removed),
  • dwell    — the same signal + the k=2 latch,
  • raw      — the untouched equal-weight portfolio, for context.
Per-book overlay, equal-weight daily-rebalanced combination, cash 0%/day — the registry's own
conservative convention, so forward numbers are comparable to #36's backtest table.

THERE IS NO BACKTEST MODE — by construction (class-Y1 protection). The loader keeps
phase=="forward" rows only, so backtest bars can never feed this book; the module exposes no
replay/backtest entry point and `main()` takes no mode argument. Backtest evidence lives in
`scripts/edge_drift_gated_overlay.py` (read-only) and is not re-runnable from here.

Fail-CLOSED: a missing/unreadable book → NO_DATA line with the reason; no live feed for the
tick's day → NO_DATA line (an honest recorded gap, never an invented bar); the exit signal is
DISARMED until 30 common forward days exist (no de-risk on an unmeasured state — all arms equal
during warm-up, which is itself part of the honest track).

ADVISORY / paper-only / OUTSIDE_RISKPOLICY: moves no capital, never touches the go-live track,
writes ONLY data/swarm/. Deterministic, stdlib-only. LLM FORBIDDEN.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from spa_core.strategy_lab.swarm.common import append_daily_proof, apy_pct, max_drawdown_pct
from spa_core.utils.atomic import atomic_save

__all__ = [
    "run_forward_tick", "load_panel", "sig_ecdr", "overlay_weights", "compute_arms",
    "ECDR_FAST", "ECDR_SLOW", "DWELL_K", "EXPECTED_BOOKS",
]

REPO_ROOT = Path(__file__).resolve().parents[3]
PANEL_DIR = REPO_ROOT / "data" / "aggressive_lab"
SWARM_DIR = REPO_ROOT / "data" / "swarm"
BOOK_NAME = "dwell_hysteresis_book.jsonl"
STATUS_NAME = "dwell_hysteresis_status.json"

NOTIONAL_USD = 100_000.0
CASH_DAILY_RETURN = 0.0  # registry convention: cash earns 0%/day (conservative)

# Parameters are PINNED to registry entry #36 (docs/DYNAMIC_LEVERAGE_GUARDIAN.md). The signal is
# ecdr#23(10/30) — the slowest exit signal and the only #32 survivor; k=2 was selected on the
# TRAIN half only (≤ 2025-06-30). Changing any of these is a NEW experiment: new registry entry
# + new owner card, never a silent edit.
ECDR_FAST = 10
ECDR_SLOW = 30
DWELL_K = 2

# The validated panel: the 10 real aggressive_lab books #36 was measured on (leave-one-out held
# on exactly this set). A new book joining the fleet does NOT silently join this panel — that
# would change the measured object.
EXPECTED_BOOKS: Tuple[str, ...] = (
    "eth_directional", "leverage_loop", "levered_restaking", "lp_eth_stable", "lrt_neutral",
    "pendle_pt_levered", "pendle_yt_susde", "points_farm", "susde_dn", "susde_spot",
)

HONEST_LIMITS = (
    "forward paper over live paper legs, not realized capital; validated on backtest only "
    "(L0, #36) — this forward window is the test and it starts small; the backtest win is "
    "DRAWDOWN (−5.44%→−3.37%), netAPY after costs is BELOW raw (17.62% vs 17.94%) — never sell "
    "this as 'more return'; duty in cash rises to ~45%; the exit signal is disarmed for the "
    "first 30 forward days (all arms equal — warm-up is part of the track); if the effect is "
    "not confirmed after ~30 armed forward days the module is retired by card, not left asleep."
)


# ── forward-only panel loader (backtest rows can NEVER feed this book) ─────────────────────────
def _load_forward_returns(path: Path) -> Dict[str, float]:
    """{date: daily_return} from phase=="forward" rows only; fail-closed to {}.

    The day's return is the row's own `mtm_today_pct` (the return ON that date), never an
    equity diff across rows — so the backtest→forward re-anchor glue (the −31…−84% phantom day
    that poisoned phase-blind loaders, cf. idea #32) is unrepresentable here by construction.
    """
    out: Dict[str, float] = {}
    try:
        with path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    doc = json.loads(line)
                except ValueError:
                    continue
                if (isinstance(doc, dict) and doc.get("phase") == "forward"
                        and isinstance(doc.get("mtm_today_pct"), (int, float)) and doc.get("date")):
                    out[str(doc["date"])] = float(doc["mtm_today_pct"]) / 100.0
    except OSError:
        return {}
    return out


def load_panel(panel_dir: Path = PANEL_DIR,
               books: Sequence[str] = EXPECTED_BOOKS,
               ) -> Tuple[Dict[str, Dict[str, float]], List[str]]:
    """(panel, missing): forward returns per expected book; books with no forward rows listed
    in `missing` (fail-closed — the caller records NO_DATA, it never shrinks the panel)."""
    panel: Dict[str, Dict[str, float]] = {}
    missing: List[str] = []
    for book in books:
        series = _load_forward_returns(panel_dir / book / "realized_series.jsonl")
        if series:
            panel[book] = series
        else:
            missing.append(book)
    return panel, sorted(missing)


# ── signal + latch (both strictly causal: exposure on day i uses returns[:i] only) ─────────────
def _ema(values: Sequence[float], span: int) -> List[float]:
    a = 2.0 / (span + 1.0)
    out: List[float] = []
    cur: Optional[float] = None
    for v in values:
        cur = v if cur is None else a * v + (1 - a) * cur
        out.append(cur)
    return out


def _sma(values: Sequence[float], window: int) -> List[float]:
    out: List[float] = []
    for i in range(len(values)):
        w = values[max(0, i - window + 1):i + 1]
        out.append(sum(w) / len(w))
    return out


def sig_ecdr(returns: Sequence[float], fast: int = ECDR_FAST, slow: int = ECDR_SLOW) -> List[bool]:
    """ecdr#23: EMA_fast(equity) < SMA_slow(equity), both built from equity THROUGH t−1.

    Fail-CLOSED on warm-up: no flag before `slow` observed days — an unmeasured trend is not
    permission to de-risk (same guard as the audited scripts/edge_calm_fp_tax.py::sig_ecdr).
    """
    eq: List[float] = [1.0]
    for r in returns:
        eq.append(eq[-1] * (1.0 + r))
    causal = eq[:len(returns)]  # causal[i] = wealth after returns[:i]
    ef, ss = _ema(causal, fast), _sma(causal, slow)
    return [(i >= slow) and (ef[i] < ss[i]) for i in range(len(returns))]


def overlay_weights(returns: Sequence[float], defend: Sequence[bool],
                    k_latch: Optional[int]) -> List[float]:
    """Exposure weights (1.0 invested / 0.0 cash) for one book.

    k_latch=None — the BASELINE arm: flag-only overlay, out exactly while `defend` is asserted.
    This IS "the latch removed", so the dwell-vs-baseline difference is attributable to the
    latch alone by construction (and the positive-control test pins that equivalence).

    k_latch>=1 — the dwell latch (same semantics as the audited
    scripts/edge_drift_gated_overlay.py::dwell_weights):
        IN  → OUT : defend[i] is True
        OUT → IN  : the last k observed days (…, r[i−1]) were ALL > 0 — evaluated BEFORE the
                    flag, so a still-asserted trigger re-arms the latch the same day (an
                    up-print does not overrule a live trigger).
    """
    if k_latch is None:
        return [0.0 if f else 1.0 for f in defend]
    if k_latch < 1:
        raise ValueError("k_latch must be >= 1 — a re-entry rule with no evidence is not a rule")
    out: List[float] = []
    state_out = False
    for i in range(len(returns)):
        if state_out:
            window = returns[max(0, i - k_latch):i]
            if len(window) == k_latch and all(r > 0.0 for r in window):
                state_out = False
        if not state_out and defend[i]:
            state_out = True
        out.append(0.0 if state_out else 1.0)
    return out


# ── portfolio arms (per-book overlay, equal-weight, daily rebalance, cash 0%/day) ──────────────
def _portfolio_equity(dates: Sequence[str], panel: Dict[str, Dict[str, float]],
                      weights: Dict[str, List[float]]) -> List[float]:
    """Equity path (len == len(dates)+1, starts at NOTIONAL): r_p(t) = mean_b(w_b·r_b + (1−w_b)·cash)."""
    books = sorted(panel)
    eq = [NOTIONAL_USD]
    for i in range(len(dates)):
        r = sum(weights[b][i] * panel[b][dates[i]] + (1.0 - weights[b][i]) * CASH_DAILY_RETURN
                for b in books) / len(books)
        eq.append(eq[-1] * (1.0 + r))
    return eq


def _arm_weights(dates: Sequence[str], panel: Dict[str, Dict[str, float]],
                 k_latch: Optional[int]) -> Dict[str, List[float]]:
    out: Dict[str, List[float]] = {}
    for book in sorted(panel):
        rets = [panel[book][d] for d in dates]
        out[book] = overlay_weights(rets, sig_ecdr(rets), k_latch)
    return out


def _largest_position_pct(w: Dict[str, List[float]], books: Sequence[str],
                          i: int) -> Optional[float]:
    """Доля самой крупной позиции на день ``i``, в процентах капитала.

    Веса плеча — это флаги «в рынке / вне рынка»; фактическая доля книги равна
    её весу, делённому на сумму весов дня. Все книги выключены ⇒ ``None``
    (позиции нет, а не «ноль процентов» — это разные утверждения).
    """
    total = sum(float(w[b][i]) for b in books)
    if total <= 0.0:
        return None
    return round(100.0 * max(float(w[b][i]) for b in books) / total, 4)


def _duty_out_pct(w: Dict[str, List[float]], books: Sequence[str],
                  n_days: int) -> Optional[float]:
    """Доля книго-дней, проведённых «выключенными», за всё окно, в процентах."""
    cells = len(books) * n_days
    if cells <= 0:
        return None
    out = sum(1 for b in books for i in range(n_days) if float(w[b][i]) == 0.0)
    return round(100.0 * out / cells, 4)


def compute_arms(dates: Sequence[str], panel: Dict[str, Dict[str, float]]) -> dict:
    """raw / baseline (latch removed) / dwell (latch k=2) over the common forward dates."""
    books = sorted(panel)
    raw_w = {b: [1.0] * len(dates) for b in books}
    base_w = _arm_weights(dates, panel, None)
    dwell_w = _arm_weights(dates, panel, DWELL_K)

    def view(w: Dict[str, List[float]]) -> dict:
        eq = _portfolio_equity(dates, panel, w)
        return {
            "equity_usd": round(eq[-1], 2),
            "apy_pct": apy_pct(eq, len(dates)),
            "max_dd_pct": max_drawdown_pct(eq),
            "books_out_today": sorted(b for b in books if w[b][-1] == 0.0),
            # Требование владельца 2026-08-08 (карточка
            # `own-rnd-duty-is-concentration-adr055`, подтверждено вместе с
            # вариантом A): каждый день писать фактическую концентрацию и долю
            # времени «выключено». Без них через 30 дней форварда результат
            # неразличим — правило его дало или премия за размер позиций.
            # На поведение модуля не влияет: обе величины ЧИТАЮТСЯ из уже
            # посчитанных весов.
            "concentration_pct": _largest_position_pct(w, books, -1),
            "duty_out_pct": _duty_out_pct(w, books, len(dates)),
        }

    arms = {"raw": view(raw_w), "baseline": view(base_w), "dwell": view(dwell_w)}
    arms["raw"].pop("books_out_today")  # raw is never out by definition
    # Books held out purely by the latch (trigger cleared, rebound not yet confirmed):
    arms["dwell"]["latched_out_today"] = sorted(
        set(arms["dwell"]["books_out_today"]) - set(arms["baseline"]["books_out_today"]))
    return arms


# ── the daily forward tick ─────────────────────────────────────────────────────────────────────
def _last_book_day(book_path: Path) -> Optional[str]:
    last = None
    try:
        with book_path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    last = json.loads(line).get("date", last)
                except ValueError:
                    continue
    except OSError:
        return None
    return last


def run_forward_tick(panel_dir: Path = PANEL_DIR, out_dir: Path = SWARM_DIR,
                     as_of: Optional[str] = None) -> dict:
    """One forward tick for one UTC day. Appends ONE hash-chained line to the paper book
    (idempotent per day, append-only by date) + writes the status JSON. Returns the status doc."""
    now = datetime.now(timezone.utc)
    day = as_of or now.date().isoformat()
    panel, missing = load_panel(panel_dir)

    doc: dict = {
        "domain": "swarm.dwell_hysteresis_forward",
        "label": ("SWARM dwell-hysteresis latch (idea #36 control, forward) / ADVISORY / paper / "
                  "OUTSIDE_RISKPOLICY"),
        "is_advisory": True,
        "outside_riskpolicy": True,
        "as_of_utc": now.isoformat(timespec="seconds"),
        "day": day,
        "params": {"signal": "ecdr#23", "ema_fast": ECDR_FAST, "sma_slow": ECDR_SLOW,
                   "dwell_k": DWELL_K,
                   "provenance": ("docs/DYNAMIC_LEVERAGE_GUARDIAN.md #36 — k=2 selected on the "
                                  "TRAIN half only (<= 2025-06-30)")},
        "honest_limits": HONEST_LIMITS,
    }

    common = sorted(d for d in set.intersection(*(set(s) for s in panel.values()))
                    if d <= day) if panel and not missing else []

    payload: dict = {"phase": "forward", "is_advisory": True, "outside_riskpolicy": True,
                     "params": {"ema_fast": ECDR_FAST, "sma_slow": ECDR_SLOW, "dwell_k": DWELL_K}}
    if missing:
        doc.update({"state": "NO_DATA",
                    "reason": f"books with no live forward rows: {missing}",
                    "missing_books": missing, "common_days": 0})
        payload.update({"status": "no_data", "reason": doc["reason"]})
    elif not common or common[-1] != day:
        last_feed = common[-1] if common else None
        doc.update({"state": "NO_DATA",
                    "reason": f"no live forward feed for {day} across the panel "
                              f"(freshest common date: {last_feed})",
                    "last_feed_date": last_feed, "common_days": len(common)})
        payload.update({"status": "no_data", "reason": doc["reason"]})
    else:
        arms = compute_arms(common, panel)
        signal_armed = len(common) > ECDR_SLOW
        doc.update({
            "state": "TRACKING",
            "common_days": len(common),
            "window": {"start": common[0], "end": common[-1]},
            "signal_armed": signal_armed,
            "arms": arms,
            "latch_effect": {
                "dd_delta_pp": (None if arms["dwell"]["max_dd_pct"] is None
                                or arms["baseline"]["max_dd_pct"] is None else
                                round(arms["dwell"]["max_dd_pct"]
                                      - arms["baseline"]["max_dd_pct"], 4)),
                "note": "dwell maxDD minus baseline maxDD, pp (positive = shallower drawdown "
                        "under the latch); the forward claim of #36 lives or dies here",
            },
        })
        payload.update({"status": "tracking", "days": len(common),
                        "window": doc["window"], "signal_armed": signal_armed,
                        "arms": arms, "latch_effect": doc["latch_effect"]})

    book_path = out_dir / BOOK_NAME
    last_day = _last_book_day(book_path)
    if last_day is not None and day < last_day:
        # Append-only BY DATE: a tick for an older day must never write after a newer line.
        doc.update({"state": "REFUSED_OUT_OF_ORDER",
                    "reason": f"tick day {day} precedes last book day {last_day}"})
        doc["book_appended"] = False
    else:
        out_dir.mkdir(parents=True, exist_ok=True)
        doc["book_appended"] = append_daily_proof(payload, book_path, day=day)

    atomic_save(doc, str(out_dir / STATUS_NAME))
    return doc


def main() -> int:
    """Forward tick only. Deliberately takes NO arguments: there is no backtest/replay mode."""
    doc = run_forward_tick()
    line = (f"swarm.dwell_hysteresis_forward: state={doc['state']}"
            f" common_days={doc.get('common_days', 0)} appended={doc['book_appended']}")
    if doc.get("arms"):
        a = doc["arms"]
        line += (f" raw=${a['raw']['equity_usd']:,.2f}"
                 f" baseline=${a['baseline']['equity_usd']:,.2f}"
                 f" dwell=${a['dwell']['equity_usd']:,.2f}"
                 f" ddΔ={doc['latch_effect']['dd_delta_pp']}pp armed={doc['signal_armed']}")
    print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
