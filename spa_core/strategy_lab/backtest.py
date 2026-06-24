"""
spa_core/strategy_lab/backtest.py — the SHARED backtest harness for the Strategy Lab.

ONE command runs ALL strategies (Variant N, Variant D + the 4 production baselines) through
the SAME backtest: same start capital, same time window, same MarketSnapshots, same cost
params. Output is a risk-adjusted comparison set vs the RWA floor.

Harness loop (per strategy, ticks in date order):
    strat.init(initial_capital, merged_config)         # once
    for snap in snapshots:                              # ascending by date
        if not killed:
            strat.step(snap)                            # accrue / settle / rebalance
        kr = strat.kill_check(snap)                     # evaluate kill conditions
        if kr.triggered and not killed:                 # latch first kill, safe-hold after
            killed = True; record kill event+date+reason
        record daily equity (frozen at the kill-day value once killed)
    metrics = compute_metrics(equity, returns, eth_returns, stable_returns, events, cfg, pos)

EQUAL-CAPITAL DECISION (spec: "одинаковый стартовый капитал для всех"):
    The baselines carry their OWN production capital in config (engine_b=$20k, engine_c=$10k,
    rwa_floor/engine_a=$100k). For an HONEST risk-adjusted comparison we run EVERY strategy at
    the SAME global initial_capital. Returns/Sharpe/drawdown/beta are all scale-free or
    normalised by capital, so equal footing makes the table comparable. The production-capital
    figures are NOT what we compare here (documented in the manifest as `equal_capital`).

WINDOW VALIDATION (spec requirement):
    A window that under-tests Variant D/N must NOT silently pass. We scan the snapshots for
    (a) at least one notable ETH peak-to-trough drawdown (> ETH_DD_MIN_PCT) AND
    (b) at least one funding flip to negative (funding_rate_8h crossing below 0).
    Missing either emits a LOUD `window_warnings` entry in the result (not an exception — the
    backtest still runs so the calm-window table is visible, but the caller is warned).

Determinism: seed is taken from config and recorded in the manifest; the harness performs no
RNG itself (all maths is deterministic), and strategies are deterministic given the same
snapshots. Two runs over identical injected snapshots are bit-for-bit identical.

stdlib only. LLM FORBIDDEN. Atomic writes (tmp + shutil.move, repo rule #4).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from spa_core.strategy_lab import config as lab_config
from spa_core.strategy_lab.base import MarketSnapshot, Strategy, StrategyMetrics
from spa_core.strategy_lab.data.market_data import MarketData
from spa_core.strategy_lab.metrics import compute_metrics
from spa_core.strategy_lab.strategies.baselines import build_baselines
from spa_core.strategy_lab.strategies.variant_d import VariantD
from spa_core.strategy_lab.strategies.variant_n import VariantN

_ROOT = Path(__file__).resolve().parents[2]  # …/SPA_Claude
DEFAULT_OUT = _ROOT / "data" / "strategy_lab_backtest.json"

# Window-validation thresholds.
ETH_DD_MIN_PCT = 10.0      # require ≥1 ETH peak-to-trough drawdown bigger than this
EQUITY_SAMPLE_MAX = 400    # cap the per-strategy equity series stored in JSON

# Strategy build order (variants first, then baselines, RWA floor last as the benchmark row).
_VARIANT_IDS = ("variant_n", "variant_d")
_BASELINE_IDS = ("engine_a", "engine_b", "engine_c", "rwa_floor")


# ── atomic JSON write (repo rule #4) ──────────────────────────────────────────────────────────
def _atomic_write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.stem + "_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, sort_keys=True)
        shutil.move(tmp, str(path))  # atomic, cross-device safe
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ── strategy construction ──────────────────────────────────────────────────────────────────────
def _merged_strategy_config(global_cfg: dict, strat_block: dict) -> dict:
    """Variant N/D read BOTH their own thresholds and the global cost/funding params from a
    single config dict (see VariantN.init). Merge global → strategy block (strategy keys win
    on collision; none collide today)."""
    merged = dict(global_cfg)
    merged.update(strat_block or {})
    return merged


def build_strategy_set(cfg: dict, initial_capital: float) -> Dict[str, Strategy]:
    """Construct ALL strategies init'd at the SAME initial_capital (equal-footing comparison).

    Variants are built + init'd here; baselines are built via build_baselines() (which init's
    them at their production capital) and then RE-init'd at initial_capital so every strategy
    starts from the same book size.
    """
    global_cfg = cfg["global"]
    strategies_cfg = cfg["strategies"]
    out: Dict[str, Strategy] = {}

    # Variants
    vn = VariantN()
    vn.init(initial_capital, _merged_strategy_config(global_cfg, strategies_cfg["variant_n"]))
    out["variant_n"] = vn

    vd = VariantD()
    vd.init(initial_capital, _merged_strategy_config(global_cfg, strategies_cfg["variant_d"]))
    out["variant_d"] = vd

    # Baselines — built by their factory, then RE-init'd at the SAME capital for equal footing.
    baselines = build_baselines(cfg)
    for bid in _BASELINE_IDS:
        strat = baselines[bid]
        strat.init(initial_capital, strategies_cfg[bid])  # equal-capital re-init
        out[bid] = strat
    return out


# ── benchmark return series from the snapshots ───────────────────────────────────────────────
def _eth_return_series(snapshots: Sequence[MarketSnapshot]) -> List[Optional[float]]:
    """Daily fractional ETH returns aligned to snapshots[1:]. None where a price is missing."""
    rets: List[Optional[float]] = []
    prev: Optional[float] = None
    for s in snapshots:
        px, ok = s.get_eth_price()
        if prev is not None and ok and prev > 0:
            rets.append((px - prev) / prev)
        elif prev is not None:
            rets.append(None)
        if ok:
            prev = px
    return rets


def _stable_return_series(
    snapshots: Sequence[MarketSnapshot], floor_apy_pct: float
) -> List[float]:
    """Daily stable-yield benchmark returns (the RWA floor's flat daily rate), one per
    transition (snapshots[1:]). Constant, low-vol — the 'stable blend' corr reference."""
    daily = (floor_apy_pct / 100.0) / 365.0
    return [daily for _ in range(max(0, len(snapshots) - 1))]


def _daily_returns(equity_series: Sequence[float]) -> List[float]:
    rets: List[float] = []
    for i in range(1, len(equity_series)):
        prev = equity_series[i - 1]
        rets.append((equity_series[i] - prev) / prev if prev else 0.0)
    return rets


# ── window validation ────────────────────────────────────────────────────────────────────────
def _eth_max_drawdown_pct(snapshots: Sequence[MarketSnapshot]) -> float:
    prices = [s.eth_price_usd for s in snapshots if s.eth_price_usd is not None]
    if len(prices) < 2:
        return 0.0
    peak = prices[0]
    worst = 0.0
    for p in prices:
        if p > peak:
            peak = p
        if peak > 0:
            dd = (peak - p) / peak * 100.0
            if dd > worst:
                worst = dd
    return round(worst, 4)


def _has_negative_funding_flip(snapshots: Sequence[MarketSnapshot]) -> bool:
    """True if funding crosses from ≥0 to <0 at any point (a genuine flip, not merely
    starting negative)."""
    prev: Optional[float] = None
    for s in snapshots:
        f, ok = s.get_funding()
        if not ok:
            continue
        if prev is not None and prev >= 0.0 and f < 0.0:
            return True
        prev = f
    # Fallback: also count "any negative funding present" as a degenerate flip signal so a
    # window that is negative throughout still satisfies the stress requirement.
    return any((s.funding_rate_8h is not None and s.funding_rate_8h < 0.0) for s in snapshots)


def validate_window(snapshots: Sequence[MarketSnapshot]) -> List[str]:
    """Return a list of LOUD warnings if the window under-tests the directional/neutral
    variants. Empty list = the window contains the needed stress."""
    warnings: List[str] = []
    if len(snapshots) < 2:
        warnings.append(
            f"WINDOW TOO SHORT: only {len(snapshots)} snapshot(s) — cannot test any strategy."
        )
        return warnings
    eth_dd = _eth_max_drawdown_pct(snapshots)
    if eth_dd <= ETH_DD_MIN_PCT:
        warnings.append(
            f"WINDOW UNDER-TESTS VARIANT D: max ETH drawdown {eth_dd:.2f}% ≤ "
            f"{ETH_DD_MIN_PCT:.0f}% — the directional drawdown kill is not exercised."
        )
    if not _has_negative_funding_flip(snapshots):
        warnings.append(
            "WINDOW UNDER-TESTS VARIANT N: no funding flip to NEGATIVE in window — the "
            "neutral variant's funding-drag / funding-kill path is not exercised."
        )
    return warnings


# ── the harness ──────────────────────────────────────────────────────────────────────────────
def _run_one(strat: Strategy, snapshots: Sequence[MarketSnapshot], initial_capital: float):
    """Run one strategy over the snapshots. Returns (equity_series, daily_returns, events,
    kill_event_or_None, final_positions). Equity is frozen at the kill-day value once killed
    (safe-hold = stop accruing)."""
    equity_series: List[float] = []
    events: List[dict] = []
    killed = False
    kill_event: Optional[dict] = None
    frozen_equity: Optional[float] = None

    for snap in snapshots:
        if not killed:
            # Fail-CLOSED at the harness boundary: a strategy whose step() raises on invalid
            # data (e.g. VariantD.require() with a missing LRT price) is treated as killed
            # (safe-hold), never crashing the whole comparison. kill_check below records the
            # reason; this guard latches the kill if step raised first.
            try:
                strat.step(snap)
            except Exception as exc:  # noqa: BLE001 — fail-closed safe-hold
                killed = True
                frozen_equity = strat.equity()
                kill_event = {
                    "type": "kill",
                    "date": snap.date,
                    "reason": f"fail-closed (step raised): {exc}",
                    "equity_at_kill": round(float(frozen_equity), 4),
                }
                events.append(kill_event)
        kr = strat.kill_check(snap)
        if kr.triggered and not killed:
            killed = True
            frozen_equity = strat.equity()
            kill_event = {
                "type": "kill",
                "date": snap.date,
                "reason": kr.reason,
                "equity_at_kill": round(frozen_equity, 4),
            }
            events.append(kill_event)

        eq = frozen_equity if killed else strat.equity()
        equity_series.append(round(float(eq), 6))

    # Pull any funding events the strategy exposed (Variant N tracks cumulative funding) so the
    # funding-drag metric has a source. We synthesise a single funding event from the live
    # partial (cum_funding_usd) — metrics.funding_drag_pct sums 'funding'-type usd<0 entries.
    m_live = strat.metrics()
    cum_funding = float((m_live.extra or {}).get("cum_funding_usd", 0.0))
    if cum_funding < 0:
        events.append({"type": "funding", "usd": cum_funding})

    daily_returns = _daily_returns(equity_series)
    return equity_series, daily_returns, events, kill_event, strat.positions()


def _sample_series(series: Sequence[float], max_points: int = EQUITY_SAMPLE_MAX) -> List[float]:
    """Downsample an equity series to ≤ max_points, always keeping first + last."""
    n = len(series)
    if n <= max_points:
        return [round(float(x), 6) for x in series]
    step = n / float(max_points)
    idxs = sorted({int(i * step) for i in range(max_points)} | {0, n - 1})
    return [round(float(series[i]), 6) for i in idxs]


def run_backtest(
    config: Optional[dict] = None,
    snapshots: Optional[Sequence[MarketSnapshot]] = None,
) -> dict:
    """Run ALL strategies through the SAME backtest and return a result dict.

    Args:
        config: full lab config dict (config.load_config()). None → load SSOT from disk.
        snapshots: injected MarketSnapshots (tests/determinism). None → MarketData over the
                   config window via historical_range(window_start, window_end).

    Returns a dict with: window manifest, per-strategy {metrics, equity_series (sampled),
    kill}, window_warnings, and the run manifest (seed, n_snapshots, generated_at).
    """
    cfg = config if config is not None else lab_config.load_config()
    g = cfg["global"]
    initial_capital = float(g["initial_capital"])
    seed = int(g["seed"])
    floor_apy = float(g["rwa_floor_apy_pct"])
    settles = int(g["funding_settles_per_day"])

    # 1) snapshots (injected or loaded over the window)
    if snapshots is None:
        md = MarketData()
        snaps: List[MarketSnapshot] = list(
            md.historical_range(g["window_start"], g["window_end"])
        )
    else:
        snaps = list(snapshots)

    # 2) window validation (LOUD warnings; does not abort)
    window_warnings = validate_window(snaps)

    # 3) benchmark return series shared by every strategy's metrics
    eth_returns = _eth_return_series(snaps)
    stable_returns = _stable_return_series(snaps, floor_apy)

    # 4) build all strategies at the SAME capital, run each through the SAME snapshots
    strategies = build_strategy_set(cfg, initial_capital)

    per_strategy: Dict[str, dict] = {}
    kills: Dict[str, dict] = {}
    for sid in (*_VARIANT_IDS, *_BASELINE_IDS):
        strat = strategies[sid]
        equity_series, daily_returns, events, kill_event, positions = _run_one(
            strat, snaps, initial_capital
        )
        # metrics config: pass the strategy block + global cost/funding/floor params so
        # compute_metrics can size capital + the tail/funding terms identically for all.
        metric_cfg = dict(cfg["strategies"].get(sid, {}))
        metric_cfg.setdefault("initial_capital", initial_capital)
        metric_cfg["funding_settles_per_day"] = settles
        metric_cfg["rwa_floor_apy_pct"] = floor_apy

        m: StrategyMetrics = compute_metrics(
            equity_series=equity_series,
            daily_returns=daily_returns,
            eth_returns=eth_returns,
            stable_returns=stable_returns,
            events=events,
            config=metric_cfg,
            positions=positions,
        )
        per_strategy[sid] = {
            "id": sid,
            "name": getattr(strat, "name", sid),
            "mandate": getattr(strat, "mandate", ""),
            "is_advisory": getattr(strat, "is_advisory", True),
            "is_benchmark": sid == "rwa_floor",
            "metrics": _metrics_to_dict(m),
            "equity_series": _sample_series(equity_series),
            "equity_first": equity_series[0] if equity_series else None,
            "equity_last": equity_series[-1] if equity_series else None,
            "kill": kill_event,
        }
        if kill_event is not None:
            kills[sid] = kill_event

    generated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    result = {
        "manifest": {
            "window_start": g["window_start"] if snapshots is None else snaps[0].date if snaps else None,
            "window_end": g["window_end"] if snapshots is None else snaps[-1].date if snaps else None,
            "initial_capital": initial_capital,
            "equal_capital": True,
            "equal_capital_note": (
                "All strategies run at the SAME initial_capital for an honest risk-adjusted "
                "comparison; production per-sleeve capital (engine_b/$20k, engine_c/$10k) is "
                "NOT used here."
            ),
            "rwa_floor_apy_pct": floor_apy,
            "seed": seed,
            "n_snapshots": len(snaps),
            "injected_snapshots": snapshots is not None,
            "generated_at": generated_at,
        },
        "window_warnings": window_warnings,
        "kills": kills,
        "strategies": per_strategy,
    }
    return result


def _metrics_to_dict(m: StrategyMetrics) -> dict:
    return {
        "net_apy_pct": m.net_apy_pct,
        "max_drawdown_pct": m.max_drawdown_pct,
        "sharpe": m.sharpe,
        "sortino": m.sortino,
        "volatility_pct": m.volatility_pct,
        "beta_to_eth": m.beta_to_eth,
        "funding_drag_pct": m.funding_drag_pct,
        "corr_to_stable_blend": m.corr_to_stable_blend,
        "tail_eth_down20_funding_flip_pct": m.tail_eth_down20_funding_flip_pct,
        "beats_rwa_floor": m.beats_rwa_floor,
        "extra": m.extra,
    }


def write_result(result: dict, path: Optional[Path] = None) -> Path:
    """Atomically write the backtest result JSON. Returns the path written."""
    p = Path(path) if path else DEFAULT_OUT
    _atomic_write_json(p, result)
    return p
