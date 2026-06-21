"""
spa_core/strategies/s44_spike_harvester.py — S44 Yield Spike Harvester
======================================================================

S44: Yield Spike Harvester
==========================
A regime-rotating strategy that captures *temporary* APY spikes. DeFi lending
rates occasionally spike 3–4× above their baseline during high-utilization
events (mass borrow demand, leverage unwinds, incentive bursts). These spikes
are short-lived — days to a couple of weeks — then mean-revert.

Real historical evidence (data/historical_apy/, 365 days each):
  Aave V3 USDC      mean  3.64%  max 12.60%   (spike 2026-04-19 → 04-26)
  Compound V3 USDC  mean  3.78%  max 11.70%   (multiple 1–3 day bursts)
  Yearn V3 USDC     mean  4.93%  max 16.05%   (Jul–Aug high-util window)

S44 leans hard into whichever protocol is spiking, parks the rest in the
Sky sUSDS stable refuge, and rotates back to a diversified book once the spike
mean-reverts.

Regime detection (evaluated every cycle, on *lagged* data — see Risk below):
  SPIKE_ACTIVE   any monitored protocol APY > SPIKE_MULTIPLE × its rolling
                 30-day average AND absolute APY > SPIKE_ABS_FLOOR_PCT (6%).
  SPIKE_INACTIVE all monitored protocols inside their normal range.

Allocation:
  SPIKE_ACTIVE                      SPIKE_INACTIVE (normal diversified)
    60% spiking protocol              40% Aave V3
    25% Sky sUSDS (stable refuge)     30% Compound V3
    15% remaining T1                  20% Sky sUSDS
                                      10% cash

  The 60% concentration deliberately overrides the normal 40% T1 per-protocol
  preference for the *duration of a spike only*. This is a raw strategy
  preference; the deterministic RiskPolicy gate in cycle_runner remains the
  final authority and may clip it — approved=False is never overridden here.

Risk management:
  * Spike detection uses LAGGED data (yesterday's APY) so S44 never chases a
    day-1 print it cannot actually have allocated into.
  * MAX_HOLD_DAYS (7): soft horizon — once a spike has been held 7 days, S44
    rotates out as soon as the APY normalizes.
  * MAX_CONSECUTIVE_SPIKE_DAYS (14): hard cap — after 14 consecutive spike-mode
    days S44 force-normalizes regardless of the signal (stale-spike guard).
  * TVL kill switch: if the spiking protocol's TVL drops > TVL_KILL_DROP_PCT
    (20%) from the level at spike entry, exit the concentration immediately
    (a draining pool is a liquidity/withdrawal risk, not an opportunity).

Rules:
  * stdlib only — no external dependencies in runtime code
  * read-only / advisory — never imports execution/ or risk agents
  * LLM FORBIDDEN in this module
  * atomic writes (tmp + os.replace) for any JSON output

Date: 2026-06-21
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Sequence, Tuple

# ─── Identity ─────────────────────────────────────────────────────────────────

STRATEGY_ID   = "S44"
STRATEGY_NAME = "Yield Spike Harvester"
TIER          = "T3"   # T3: aggressive single-protocol concentration during spikes
DESCRIPTION   = (
    "Yield Spike Harvester: detects temporary APY spikes (>2x the 30-day average "
    "and >6% absolute) and concentrates 60% into the spiking protocol with a 25% "
    "Sky sUSDS refuge, rotating back to a diversified book on mean-reversion. "
    "Lagged detection, 7-day soft / 14-day hard hold caps, TVL kill switch. "
    "Advisory only — paper trading until Owner approval."
)

# ─── Detection thresholds ─────────────────────────────────────────────────────

#: A protocol's APY must exceed this multiple of its rolling average to qualify.
SPIKE_MULTIPLE: float = 2.0
#: …and also clear this absolute floor (percent) — filters low-base noise.
SPIKE_ABS_FLOOR_PCT: float = 6.0
#: Rolling-average window length (days).
ROLLING_WINDOW_DAYS: int = 30

# ─── Hold / exit controls ─────────────────────────────────────────────────────

#: Soft hold horizon: after this many days in spike mode, rotate out on normalize.
MAX_HOLD_DAYS: int = 7
#: Hard cap: force-normalize after this many consecutive spike-mode days.
MAX_CONSECUTIVE_SPIKE_DAYS: int = 14
#: Kill switch: exit if the spiking protocol's TVL drops more than this fraction
#: below its level at spike entry.
TVL_KILL_DROP_PCT: float = 0.20

# ─── Allocation weights ───────────────────────────────────────────────────────

#: Concentration into the spiking protocol (overrides normal T1 cap during spike).
SPIKE_CONCENTRATION_PCT: float = 0.60
#: Stable refuge weight during a spike.
SPIKE_REFUGE_PCT: float = 0.25
#: Remaining T1 spread during a spike.
SPIKE_REMAINING_T1_PCT: float = 0.15

#: Normal diversified book (SPIKE_INACTIVE). Cash is the unallocated remainder.
NORMAL_WEIGHTS: Dict[str, float] = {
    "aave_v3":     0.40,
    "compound_v3": 0.30,
    "sky_susds":   0.20,
    # remaining 0.10 → cash
}
NORMAL_CASH_PCT: float = 0.10

# ─── Universe ─────────────────────────────────────────────────────────────────

#: Protocols monitored for spikes (the high-variance T1 lending venues).
MONITORED_PROTOCOLS: Tuple[str, ...] = ("aave_v3", "compound_v3", "yearn_v3")
#: Stable refuge — Sky sUSDS (low variance, ~4.2% mean, never spikes).
STABLE_REFUGE: str = "sky_susds"
#: T1 venues used to fill the "remaining T1" sleeve during a spike.
REMAINING_T1: Tuple[str, ...] = ("aave_v3", "compound_v3")

PROTOCOL_TIERS: Dict[str, str] = {
    "aave_v3":     "T1",
    "compound_v3": "T1",
    "yearn_v3":    "T2",
    "sky_susds":   "T1",
}

# Display labels for human-readable spike reports.
PROTOCOL_LABELS: Dict[str, str] = {
    "aave_v3":     "Aave",
    "compound_v3": "Compound",
    "yearn_v3":    "Yearn",
    "sky_susds":   "Sky sUSDS",
}

# ─── Regime constants ─────────────────────────────────────────────────────────

REGIME_SPIKE  = "spike_active"
REGIME_NORMAL = "spike_inactive"

TARGET_APY_MIN:   float = 4.0
TARGET_APY_MAX:   float = 12.0
RISK_SCORE:       float = 0.62
MAX_DRAWDOWN_PCT: float = 8.0


# ─── Pure helpers ─────────────────────────────────────────────────────────────

def rolling_average(series: Sequence[float], window: int = ROLLING_WINDOW_DAYS) -> Optional[float]:
    """Simple mean of the trailing ``window`` observations.

    Returns ``None`` when the series is empty (no basis for a spike comparison).
    Uses whatever history is available if shorter than ``window``.
    """
    vals = [float(x) for x in series if x is not None]
    if not vals:
        return None
    tail = vals[-window:]
    return sum(tail) / len(tail)


def spike_magnitude_pct(apy: float, avg: float) -> float:
    """Percent above the rolling average: ``(apy/avg - 1) * 100``.

    Returns 0.0 when ``avg`` is non-positive (undefined baseline).
    """
    if avg is None or avg <= 0.0:
        return 0.0
    return (apy / avg - 1.0) * 100.0


def format_spike_report(protocol: str, apy: float, avg: float) -> str:
    """Human-readable spike line, e.g.::

        spike: Aave at 12.60% vs 30d avg 3.64% = +248% above average
    """
    label = PROTOCOL_LABELS.get(protocol, protocol)
    mag = spike_magnitude_pct(apy, avg)
    return (
        f"spike: {label} at {apy:.2f}% vs 30d avg "
        f"{(avg or 0.0):.2f}% = {mag:+.0f}% above average"
    )


def is_spiking(apy: float, avg: Optional[float]) -> bool:
    """True iff ``apy`` clears both the relative (×SPIKE_MULTIPLE) and absolute
    (>SPIKE_ABS_FLOOR_PCT) gates against the rolling ``avg``."""
    if avg is None or avg <= 0.0:
        return False
    if apy <= SPIKE_ABS_FLOOR_PCT:
        return False
    return apy > SPIKE_MULTIPLE * avg


# ─── Config ───────────────────────────────────────────────────────────────────

@dataclass
class S44Config:
    """Tunable parameters for the Spike Harvester (defaults mirror module consts)."""
    spike_multiple: float          = SPIKE_MULTIPLE
    spike_abs_floor_pct: float      = SPIKE_ABS_FLOOR_PCT
    rolling_window_days: int        = ROLLING_WINDOW_DAYS
    max_hold_days: int              = MAX_HOLD_DAYS
    max_consecutive_spike_days: int = MAX_CONSECUTIVE_SPIKE_DAYS
    tvl_kill_drop_pct: float        = TVL_KILL_DROP_PCT
    spike_concentration_pct: float  = SPIKE_CONCENTRATION_PCT
    spike_refuge_pct: float         = SPIKE_REFUGE_PCT
    spike_remaining_t1_pct: float   = SPIKE_REMAINING_T1_PCT

    def __post_init__(self) -> None:
        if self.spike_multiple <= 1.0:
            raise ValueError(f"spike_multiple must be > 1.0, got {self.spike_multiple}")
        if self.spike_abs_floor_pct < 0.0:
            raise ValueError(f"spike_abs_floor_pct must be >= 0, got {self.spike_abs_floor_pct}")
        if self.rolling_window_days < 1:
            raise ValueError(f"rolling_window_days must be >= 1, got {self.rolling_window_days}")
        if self.max_consecutive_spike_days < self.max_hold_days:
            raise ValueError("max_consecutive_spike_days must be >= max_hold_days")
        if not 0.0 < self.spike_concentration_pct <= 1.0:
            raise ValueError("spike_concentration_pct must be in (0, 1]")
        total = (self.spike_concentration_pct + self.spike_refuge_pct
                 + self.spike_remaining_t1_pct)
        if total > 1.0 + 1e-9:
            raise ValueError(f"spike weights sum {total} exceeds 1.0")


# ─── Strategy (stateful) ──────────────────────────────────────────────────────

@dataclass
class S44SpikeHarvester:
    """S44 — Yield Spike Harvester.

    Stateful across a daily cycle: tracks how long it has been concentrated in a
    spike, which protocol, and that protocol's TVL at entry (for the kill switch).

    Typical use is via :meth:`simulate_day` (one call per day) or :meth:`backtest`
    (drives ``simulate_day`` across a per-protocol APY history). All detection is
    done on the ``lagged`` APY map the caller passes in (yesterday's print).
    """

    STRATEGY_ID   = STRATEGY_ID
    STRATEGY_NAME = STRATEGY_NAME
    TIER          = TIER
    RISK_SCORE    = RISK_SCORE

    capital: float = 100_000.0
    config: S44Config = field(default_factory=S44Config)

    # ── internal state ──
    regime: str                       = REGIME_NORMAL
    spiking_protocol: Optional[str]   = None
    consecutive_spike_days: int       = 0
    days_held: int                    = 0          # days held in the *current* spike
    entry_tvl: Optional[float]        = None       # spiking protocol TVL at entry

    def __post_init__(self) -> None:
        if self.capital < 0:
            raise ValueError(f"capital must be >= 0, got {self.capital}")

    # ── detection ─────────────────────────────────────────────────────────────

    def detect_regime(
        self,
        lagged_apy_map: Dict[str, float],
        rolling_avg_map: Dict[str, float],
    ) -> Dict:
        """Classify the regime from lagged APYs vs their rolling averages.

        Returns a dict::

            {
              "regime": "spike_active" | "spike_inactive",
              "spiking_protocol": str | None,
              "spike_apy": float | None,
              "rolling_avg": float | None,
              "magnitude_pct": float,
              "report": str | None,
              "candidates": [ {protocol, apy, avg, magnitude_pct}, ... ],
            }

        When several monitored protocols spike at once, the one with the highest
        magnitude above its own average wins the concentration.
        """
        candidates: List[Dict] = []
        for proto in MONITORED_PROTOCOLS:
            apy = lagged_apy_map.get(proto)
            avg = rolling_avg_map.get(proto)
            if apy is None:
                continue
            if is_spiking(apy, avg):
                candidates.append({
                    "protocol": proto,
                    "apy": float(apy),
                    "avg": float(avg),
                    "magnitude_pct": spike_magnitude_pct(float(apy), float(avg)),
                })

        if not candidates:
            return {
                "regime": REGIME_NORMAL,
                "spiking_protocol": None,
                "spike_apy": None,
                "rolling_avg": None,
                "magnitude_pct": 0.0,
                "report": None,
                "candidates": [],
            }

        winner = max(candidates, key=lambda c: c["magnitude_pct"])
        return {
            "regime": REGIME_SPIKE,
            "spiking_protocol": winner["protocol"],
            "spike_apy": winner["apy"],
            "rolling_avg": winner["avg"],
            "magnitude_pct": winner["magnitude_pct"],
            "report": format_spike_report(winner["protocol"], winner["apy"], winner["avg"]),
            "candidates": candidates,
        }

    # ── allocation ────────────────────────────────────────────────────────────

    def get_allocation(
        self,
        regime: str,
        spiking_protocol: Optional[str] = None,
    ) -> Dict[str, float]:
        """Target weights (fractions, may sum to < 1.0 — remainder is cash).

        SPIKE_ACTIVE concentrates ``spike_concentration_pct`` into the spiking
        protocol, ``spike_refuge_pct`` into the Sky sUSDS refuge, and spreads
        ``spike_remaining_t1_pct`` across the remaining T1 venues. If the spiking
        protocol is itself one of the remaining-T1 venues, that venue is excluded
        from the spread (no double count).
        """
        if regime == REGIME_SPIKE and spiking_protocol:
            cfg = self.config
            weights: Dict[str, float] = {
                spiking_protocol: cfg.spike_concentration_pct,
                STABLE_REFUGE: cfg.spike_refuge_pct,
            }
            # spread remaining-T1 across venues other than the spiking one
            spread_pool = [p for p in REMAINING_T1 if p != spiking_protocol]
            if spread_pool and cfg.spike_remaining_t1_pct > 0:
                each = cfg.spike_remaining_t1_pct / len(spread_pool)
                for p in spread_pool:
                    weights[p] = weights.get(p, 0.0) + each
            else:
                # no distinct remaining-T1 venue → fold the sleeve into the refuge
                weights[STABLE_REFUGE] = weights.get(STABLE_REFUGE, 0.0) + cfg.spike_remaining_t1_pct
            return {k: round(v, 8) for k, v in weights.items() if v > 0}

        # SPIKE_INACTIVE — normal diversified book
        return {k: round(v, 8) for k, v in NORMAL_WEIGHTS.items() if v > 0}

    # ── daily simulation ──────────────────────────────────────────────────────

    def step(
        self,
        lagged_apy_map: Dict[str, float],
        rolling_avg_map: Dict[str, float],
        tvl_map: Optional[Dict[str, float]] = None,
    ) -> Dict:
        """Advance one day and decide the regime + allocation.

        State machine (all on lagged data):
          1. Detect the raw spike signal.
          2. Apply the hard 14-day consecutive cap → force-normalize if exceeded.
          3. Apply the TVL kill switch if we're already concentrated and the
             spiking protocol's TVL has drained > tvl_kill_drop_pct from entry.
          4. Otherwise enter/extend the spike (recording entry TVL on day 1).

        Returns a state snapshot dict (regime, allocation, report, flags …).
        """
        det = self.detect_regime(lagged_apy_map, rolling_avg_map)
        raw_spike = det["regime"] == REGIME_SPIKE
        winner = det["spiking_protocol"]

        forced_normalize = False
        kill_switch = False

        # A spike on a *different* protocol resets the per-spike day counter.
        if raw_spike and self.spiking_protocol and winner != self.spiking_protocol:
            self.days_held = 0
            self.entry_tvl = None

        effective_spike = raw_spike

        # (2) hard consecutive-day cap
        if effective_spike and self.consecutive_spike_days >= self.config.max_consecutive_spike_days:
            effective_spike = False
            forced_normalize = True

        # (3) TVL kill switch — only meaningful while already concentrated
        if effective_spike and tvl_map is not None and winner is not None:
            cur_tvl = tvl_map.get(winner)
            ref_tvl = self.entry_tvl if (self.spiking_protocol == winner and self.entry_tvl) else cur_tvl
            if cur_tvl is not None and ref_tvl and ref_tvl > 0:
                if cur_tvl < ref_tvl * (1.0 - self.config.tvl_kill_drop_pct):
                    effective_spike = False
                    kill_switch = True

        if effective_spike:
            if self.spiking_protocol == winner:
                self.days_held += 1
            else:
                self.days_held = 1
                self.entry_tvl = (tvl_map or {}).get(winner) if tvl_map else None
            self.spiking_protocol = winner
            self.consecutive_spike_days += 1
            self.regime = REGIME_SPIKE
        else:
            self.spiking_protocol = None
            self.days_held = 0
            self.consecutive_spike_days = 0
            self.entry_tvl = None
            self.regime = REGIME_NORMAL

        alloc = self.get_allocation(self.regime, self.spiking_protocol)
        return {
            "regime": self.regime,
            "spiking_protocol": self.spiking_protocol,
            "allocation": alloc,
            "cash_pct": round(max(0.0, 1.0 - sum(alloc.values())), 8),
            "days_held": self.days_held,
            "consecutive_spike_days": self.consecutive_spike_days,
            "forced_normalize": forced_normalize,
            "kill_switch": kill_switch,
            "magnitude_pct": det["magnitude_pct"],
            "report": det["report"],
        }

    # ── one-shot allocation snapshot (advisory) ───────────────────────────────

    def simulate(
        self,
        capital_usd: float,
        lagged_apy_map: Dict[str, float],
        rolling_avg_map: Dict[str, float],
        tvl_map: Optional[Dict[str, float]] = None,
    ) -> Dict:
        """Single advisory snapshot: USD positions for the detected regime."""
        if capital_usd <= 0.0:
            return {
                "strategy_id": STRATEGY_ID,
                "total_capital": capital_usd,
                "regime": REGIME_NORMAL,
                "allocation": {},
                "status": "no_capital",
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            }
        st = self.step(lagged_apy_map, rolling_avg_map, tvl_map)
        positions = {p: round(capital_usd * w, 6) for p, w in st["allocation"].items()}
        # blended expected APY from the live lagged map (refuge/cash use map or 0)
        exp_apy = 0.0
        for p, w in st["allocation"].items():
            exp_apy += w * float(lagged_apy_map.get(p, 0.0))
        return {
            "strategy_id": STRATEGY_ID,
            "total_capital": capital_usd,
            "regime": st["regime"],
            "spiking_protocol": st["spiking_protocol"],
            "allocation": positions,
            "cash_usd": round(capital_usd * st["cash_pct"], 6),
            "expected_apy_pct": round(exp_apy, 4),
            "spike_report": st["report"],
            "status": "ok",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }

    # ── backtest over real per-protocol APY history ───────────────────────────

    def backtest(
        self,
        apy_series: Dict[str, List[float]],
        initial_capital: float = 100_000.0,
        tvl_series: Optional[Dict[str, List[float]]] = None,
    ) -> Dict:
        """Run S44 day-by-day over aligned per-protocol APY series.

        ``apy_series`` maps ``protocol -> [apy_day0, apy_day1, ...]`` (percent,
        chronological). All series must be the same length N. Detection at day
        ``t`` uses day ``t-1`` (lagged); yield is accrued at day ``t``'s actual
        APY on the allocated weights. The first day is warm-up (cash).

        Returns a metrics dict including the daily equity curve, spike-window
        accounting, and the realised annualised return.
        """
        protos = list(apy_series.keys())
        lengths = {len(v) for v in apy_series.values()}
        if len(lengths) != 1:
            raise ValueError(f"apy_series lengths differ: {{p: len for ...}} -> {lengths}")
        n = lengths.pop()
        if n < 2:
            raise ValueError("need at least 2 days of history")

        cfg = self.config
        capital = float(initial_capital)
        curve = [capital]
        regimes: List[str] = []
        spike_days = 0
        spike_interest = 0.0
        normal_interest = 0.0

        for t in range(1, n):
            lagged = {p: apy_series[p][t - 1] for p in protos}
            # Baseline = the 30 days *preceding* the lagged print (excludes the
            # lagged day itself), so a spike is measured against the normal level
            # rather than a window the spike has already inflated.
            roll = {}
            hi = t - 1                               # exclusive end (drops lagged day)
            lo = max(0, hi - cfg.rolling_window_days)
            for p in protos:
                window = apy_series[p][lo:hi]
                roll[p] = rolling_average(window, cfg.rolling_window_days) if window else None
            tvl_map = None
            if tvl_series is not None:
                tvl_map = {p: tvl_series[p][t - 1] for p in protos if p in tvl_series}

            st = self.step(lagged, roll, tvl_map)
            alloc = st["allocation"]

            # accrue one day of interest at *today's* realised APY on each weight
            day_interest = 0.0
            for p, w in alloc.items():
                apy_today = apy_series.get(p, [0.0] * n)[t]
                day_interest += capital * w * (apy_today / 100.0) / 365.0
            capital += day_interest
            curve.append(capital)
            regimes.append(st["regime"])

            if st["regime"] == REGIME_SPIKE:
                spike_days += 1
                spike_interest += day_interest
            else:
                normal_interest += day_interest

        days = n - 1
        total_return_pct = (curve[-1] - curve[0]) / curve[0] * 100.0 if curve[0] else 0.0
        ann = ((curve[-1] / curve[0]) ** (365.0 / days) - 1.0) * 100.0 if days > 0 and curve[0] > 0 else 0.0
        mdd = _max_drawdown_pct(curve)

        return {
            "strategy_id": STRATEGY_ID,
            "backtest_days": days,
            "initial_capital_usd": round(curve[0], 2),
            "final_capital_usd": round(curve[-1], 2),
            "total_interest_usd": round(curve[-1] - curve[0], 2),
            "total_return_pct": round(total_return_pct, 4),
            "annualised_return_pct": round(ann, 4),
            "max_drawdown_pct": round(mdd, 4),
            "spike_days": spike_days,
            "normal_days": days - spike_days,
            "spike_interest_usd": round(spike_interest, 2),
            "normal_interest_usd": round(normal_interest, 2),
            "equity_curve": [round(v, 4) for v in curve],
            "regimes": regimes,
        }

    # ── metadata ──────────────────────────────────────────────────────────────

    def to_dict(self) -> Dict:
        return {
            "strategy_id":       STRATEGY_ID,
            "strategy_name":     STRATEGY_NAME,
            "tier":              TIER,
            "description":       DESCRIPTION,
            "monitored_protocols": list(MONITORED_PROTOCOLS),
            "stable_refuge":     STABLE_REFUGE,
            "protocol_tiers":    dict(PROTOCOL_TIERS),
            "spike_multiple":    self.config.spike_multiple,
            "spike_abs_floor_pct": self.config.spike_abs_floor_pct,
            "rolling_window_days": self.config.rolling_window_days,
            "max_hold_days":     self.config.max_hold_days,
            "max_consecutive_spike_days": self.config.max_consecutive_spike_days,
            "tvl_kill_drop_pct": self.config.tvl_kill_drop_pct,
            "spike_concentration_pct": self.config.spike_concentration_pct,
            "normal_weights":    dict(NORMAL_WEIGHTS),
            "target_apy_min":    TARGET_APY_MIN,
            "target_apy_max":    TARGET_APY_MAX,
            "risk_score":        RISK_SCORE,
            "max_drawdown_pct":  MAX_DRAWDOWN_PCT,
            "timestamp":         datetime.now(timezone.utc).isoformat(),
        }


# ─── small numeric helpers ────────────────────────────────────────────────────

def _max_drawdown_pct(curve: Sequence[float]) -> float:
    """Largest peak-to-trough decline of an equity curve, as a positive percent."""
    peak = float("-inf")
    mdd = 0.0
    for v in curve:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak
            if dd > mdd:
                mdd = dd
    return mdd * 100.0


# ─── Auto-registration ────────────────────────────────────────────────────────

def _register() -> None:
    try:
        from spa_core.strategies.strategy_registry import REGISTRY, StrategyMeta
        REGISTRY.register(StrategyMeta(
            id=STRATEGY_ID,
            name=STRATEGY_NAME,
            type="lending",
            risk_tier=TIER,
            target_apy_min=TARGET_APY_MIN,
            target_apy_max=TARGET_APY_MAX,
            max_drawdown_pct=MAX_DRAWDOWN_PCT,
            description=DESCRIPTION,
            module="spa_core.strategies.s44_spike_harvester",
            handler_class="S44SpikeHarvester",
            tags=["spike", "regime_rotation", "high_utilization", "concentration",
                  "aave", "compound", "yearn", "sky_refuge", "t3", "s44", "advisory"],
        ))
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(
            "S44SpikeHarvester auto-registration failed: %s", exc
        )


_register()


if __name__ == "__main__":
    import json
    h = S44SpikeHarvester(capital=100_000.0)
    # demo: Aave spiking to 12.60% against a 3.64% baseline
    snap = h.simulate(
        100_000.0,
        lagged_apy_map={"aave_v3": 12.60, "compound_v3": 3.8, "yearn_v3": 4.9, "sky_susds": 4.2},
        rolling_avg_map={"aave_v3": 3.64, "compound_v3": 3.78, "yearn_v3": 4.93, "sky_susds": 4.2},
    )
    print(json.dumps(snap, indent=2))
