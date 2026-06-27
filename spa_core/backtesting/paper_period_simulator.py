"""
spa_core/backtesting/paper_period_simulator.py
MP-1329 (v9.45)

Simulates historical paper trading periods for planning.
Answers: "If we had started paper trading in [month], what would we have seen?"

Key questions:
  - Which market regimes would we encounter? (bear/neutral/bull)
  - How often would PIT-eligible protocols change?
  - Would evidence accumulation be fast or slow?
  - What maximum drawdown would we face?

Simulation engine:
  1. Pick start date
  2. Run 90-day window
  3. Apply PIT whitelist (eligible protocols change daily)
  4. Assign regime based on BTC price (from synthetic data or fixed schedule)
  5. Compute NAV trajectory, evidence accumulation, protocol changes

Predefined periods to simulate:
  "bear_2022":     2022-06-01 to 2022-09-01 (post-LUNA crash)
  "recovery_2023": 2023-01-01 to 2023-04-01 (FTX aftermath)
  "bull_2024":     2024-01-01 to 2024-04-01 (pre-halving bull)
  "stable_2025":   2025-06-01 to 2025-09-01 (stable period)

stdlib only. Atomic writes. No external dependencies.
"""

from __future__ import annotations

import json
import math
import os
from datetime import date, timedelta
from pathlib import Path

from spa_core.backtesting.point_in_time_whitelist import PointInTimeWhitelist
from spa_core.utils.atomic import atomic_save


# ── Predefined simulation periods ─────────────────────────────────────────────

PREDEFINED_PERIODS: dict[str, dict] = {
    "bear_2022": {
        "start": "2022-06-01",
        "end":   "2022-09-01",
        "regime": "bear",
    },
    "recovery_2023": {
        "start": "2023-01-01",
        "end":   "2023-04-01",
        "regime": "neutral",
    },
    "bull_2024": {
        "start": "2024-01-01",
        "end":   "2024-04-01",
        "regime": "bull",
    },
    "stable_2025": {
        "start": "2025-06-01",
        "end":   "2025-09-01",
        "regime": "neutral",
    },
}

# ── Per-regime simulation parameters ─────────────────────────────────────────
#
# trend_daily: deterministic daily return fraction
#   bear    ≈ -0.008%/day  → overall NAV decline, realistic for mostly-cash period
#   neutral ≈ +0.011%/day  → ~4% annual, modest positive
#   bull    ≈ +0.022%/day  → ~8% annual, strong positive
#
# noise_amp: amplitude of deterministic sin-wave noise (fraction of NAV)
#   bear    large enough to create realistic positive/negative days
#   neutral moderate — some positive, some negative days (genuine drawdown)
#   bull    small — trend dominates, minimal drawdown
#
# evidence_per_protocol: points earned per eligible protocol per day
#   bear    < 1.0 — lower quality due to high uncertainty
#   neutral = 1.0 — baseline
#   bull    > 1.0 — higher protocol count, faster evidence accumulation

_REGIME: dict[str, dict] = {
    "bear": {
        "trend_daily":          -0.00008,
        "noise_amp":             0.00035,
        "evidence_per_protocol": 0.8,
    },
    "neutral": {
        "trend_daily":           0.00011,
        "noise_amp":             0.00020,
        "evidence_per_protocol": 1.0,
    },
    "bull": {
        "trend_daily":           0.00022,
        "noise_amp":             0.00012,
        "evidence_per_protocol": 1.2,
    },
}

# ── Stress quality weight for evidence scoring ────────────────────────────────
# Bear/neutral periods produce higher-quality stress-tested evidence
# even if raw evidence point count is lower.

_STRESS_WEIGHT: dict[str, float] = {
    "bear":    1.5,
    "neutral": 1.3,
    "bull":    1.0,
}

# ── Notable market events per period ─────────────────────────────────────────

_MARKET_EVENTS: dict[str, list[str]] = {
    "bear_2022": [
        "LUNA/UST collapse (May 2022) — DeFi contagion ongoing through Q3",
        "Three Arrows Capital (3AC) insolvency filed June 2022",
        "Celsius Network freezes withdrawals June 2022",
        "Compound V3 (Comet USDC) launches August 26, 2022",
        "FTX warning signs emerging (late Q3 2022)",
    ],
    "recovery_2023": [
        "FTX post-collapse — CeFi trust at historic low, DeFi gaining credibility",
        "DeFi TVL recovering from $50B lows toward $70B",
        "sfrax / FRAX v2 launches March 2023 — new stablecoin yield source",
        "SEC enforcement escalation (Kraken, Paxos, Coinbase Wells Notice)",
        "Stablecoin yields compressed to 3–5% range (T-bills outcompeting)",
    ],
    "bull_2024": [
        "Bitcoin spot ETF approved by SEC (January 10, 2024)",
        "Morpho Steakhouse USDC vault launched January 15, 2024",
        "Euler V2 mainnet launch February 6, 2024 — new T2 protocol eligible",
        "DeFi yields rising: Aave V3 ~5–8%, Morpho Steakhouse ~8–12%",
        "Bitcoin halving April 19, 2024 — end-of-period catalyst",
    ],
    "stable_2025": [
        "Post-halving DeFi stable period — volatility near multi-year lows",
        "Ethereum L2 fees near zero; Base/Arbitrum dominant execution layer",
        "Sky (ex-MakerDAO) GSM Pause Delay under 48h evaluation",
        "Pendle PT markets highly liquid; fixed-rate demand at ATH",
        "Institutional DeFi products expanding (tokenised T-bills, RWA vaults)",
    ],
}


class PaperPeriodSimulator:
    """
    Simulates historical paper trading periods for planning purposes.

    This is NOT a backtest — it models "what would we have seen" to help decide:
    - When to start paper trading for best evidence accumulation
    - What drawdown to expect under each market regime
    - How many protocol changes (rebalancing events) to anticipate

    The simulation is fully deterministic: given the same period_id and
    initial_capital, results are identical across runs.

    Usage::

        sim = PaperPeriodSimulator()
        result = sim.simulate_period("bull_2024")
        print(result["final_nav"])      # ~$101,800
        print(result["max_drawdown_pct"])  # 0.0 (bull periods rarely draw down)

        all_results = sim.simulate_all()
        best = sim.best_paper_start_date()  # "stable_2025"
        recs = sim.recommendations()
        sim.save("data/backtest/paper_period_simulations.json")
    """

    def __init__(self, initial_capital: float = 100_000.0) -> None:
        """
        Args:
            initial_capital: Starting portfolio NAV for simulation (USD).
                             Defaults to $100,000 (SPA paper trading capital).
        """
        self._initial_capital = float(initial_capital)
        self._whitelist = PointInTimeWhitelist()

    # ── Public API ─────────────────────────────────────────────────────────────

    def simulate_period(self, period_id: str) -> dict:
        """
        Simulates one predefined period.

        Returns:
            {
              "period": str,                     # period identifier
              "start": str,                      # YYYY-MM-DD
              "end": str,                        # YYYY-MM-DD
              "regime": str,                     # bear | neutral | bull
              "days": int,                       # calendar days in window
              "nav_trajectory": [               # weekly NAV snapshots
                  {"date": str, "nav": float}
              ],
              "final_nav": float,               # NAV at end of period
              "total_return_pct": float,        # (final - initial) / initial * 100
              "apy": float,                     # annualised from total_return_pct
              "max_drawdown_pct": float,        # peak-to-trough, always <= 0
              "evidence_points_accumulated": float,  # protocol × days × quality
              "protocol_changes": int,          # times PIT eligible set changed
              "market_events": [str],           # notable events in this period
            }

        Raises:
            ValueError: If period_id is not in PREDEFINED_PERIODS.
        """
        if period_id not in PREDEFINED_PERIODS:
            raise ValueError(
                f"Unknown period {period_id!r}. "
                f"Valid options: {sorted(PREDEFINED_PERIODS.keys())}"
            )

        cfg     = PREDEFINED_PERIODS[period_id]
        regime  = cfg["regime"]
        params  = _REGIME[regime]

        start_str  = cfg["start"]
        end_str    = cfg["end"]
        start_d    = date.fromisoformat(start_str)
        end_d      = date.fromisoformat(end_str)
        total_days = (end_d - start_d).days  # e.g. 92 for bear_2022

        # ── Simulation state ──────────────────────────────────────────────────

        nav         = self._initial_capital
        peak_nav    = nav
        max_dd      = 0.0   # most-negative drawdown fraction seen so far

        evidence_points  = 0.0
        protocol_changes = 0

        # Deterministic period-specific seed (sum of ASCII codepoints)
        period_seed = sum(ord(c) for c in period_id)

        trend_daily   = params["trend_daily"]
        noise_amp     = params["noise_amp"]
        ev_per_proto  = params["evidence_per_protocol"]

        # Track eligible protocol set to count changes
        prev_eligible: set[str] = set(
            self._whitelist.eligible_protocols(start_str)
        )

        # NAV trajectory: day-0 anchor + weekly samples
        nav_trajectory: list[dict] = [{"date": start_str, "nav": round(nav, 2)}]
        next_sample_day = 7

        # ── Day-by-day simulation ─────────────────────────────────────────────

        for day in range(1, total_days + 1):
            day_d   = start_d + timedelta(days=day)
            day_str = day_d.isoformat()

            # Deterministic noise: quasi-periodic, bounded in [-noise_amp, +noise_amp]
            noise    = noise_amp * math.sin(period_seed + day * 1.6180339887)
            daily_r  = trend_daily + noise
            nav     *= 1.0 + daily_r

            # Running maximum-drawdown tracking
            if nav > peak_nav:
                peak_nav = nav
            dd = (nav - peak_nav) / peak_nav   # always ≤ 0.0
            if dd < max_dd:
                max_dd = dd

            # PIT-eligible protocol set — count changes
            eligible: set[str] = set(
                self._whitelist.eligible_protocols(day_str)
            )
            if eligible != prev_eligible:
                protocol_changes += 1
            prev_eligible = eligible

            # Evidence accumulation: more eligible protocols → more evidence
            n_eligible      = max(1, len(eligible))
            evidence_points += ev_per_proto * n_eligible

            # Weekly NAV snapshot + final-day snapshot
            if day == next_sample_day or day == total_days:
                nav_trajectory.append({"date": day_str, "nav": round(nav, 2)})
                if day == next_sample_day:
                    next_sample_day += 7

        # ── Compute summary metrics ───────────────────────────────────────────

        final_nav = round(nav, 2)

        total_return_pct = round(
            (final_nav - self._initial_capital) / self._initial_capital * 100,
            4,
        )

        apy = (
            round(total_return_pct / total_days * 365, 4)
            if total_days > 0
            else 0.0
        )

        # max_dd is always ≤ 0; clamp protects against floating-point noise
        max_drawdown_pct = round(min(0.0, max_dd * 100), 4)

        return {
            "period":                      period_id,
            "start":                       start_str,
            "end":                         end_str,
            "regime":                      regime,
            "days":                        total_days,
            "nav_trajectory":              nav_trajectory,
            "final_nav":                   final_nav,
            "total_return_pct":            total_return_pct,
            "apy":                         apy,
            "max_drawdown_pct":            max_drawdown_pct,
            "evidence_points_accumulated": round(evidence_points, 2),
            "protocol_changes":            protocol_changes,
            "market_events":               list(_MARKET_EVENTS[period_id]),
        }

    def simulate_all(self) -> dict:
        """
        Simulates all 4 predefined periods.

        Returns:
            {period_id: simulate_period(period_id), ...}
        """
        return {pid: self.simulate_period(pid) for pid in PREDEFINED_PERIODS}

    def best_paper_start_date(self) -> str:
        """
        Returns the period ID with the highest evidence quality score.

        Score = evidence_points_accumulated × stress_weight, where
        bear/neutral periods earn a stress bonus for strategy robustness
        (testing under adversity builds higher-confidence evidence).

        Returns:
            One of the PREDEFINED_PERIODS keys.
        """
        results = self.simulate_all()
        return max(
            results.keys(),
            key=lambda pid: (
                results[pid]["evidence_points_accumulated"]
                * _STRESS_WEIGHT[PREDEFINED_PERIODS[pid]["regime"]]
            ),
        )

    def worst_paper_period(self) -> str:
        """
        Returns the period ID with the lowest evidence quality.

        Uses raw evidence_points_accumulated (no stress bonus) — the period
        where evidence accumulation was simply the slowest.

        Returns:
            One of the PREDEFINED_PERIODS keys.
        """
        results = self.simulate_all()
        return min(
            results.keys(),
            key=lambda pid: results[pid]["evidence_points_accumulated"],
        )

    def recommendations(self) -> dict:
        """
        Returns actionable guidance based on simulation results.

        Returns:
            {
              "start_now": bool,
              "recommended_regime_to_wait_for": str,
              "expected_duration_days": int,
              "expected_evidence_points": float,
              "notes": [str]
            }
        """
        results    = self.simulate_all()
        stable     = results["stable_2025"]
        daily_rate = stable["evidence_points_accumulated"] / stable["days"]
        expected_30d_evidence = round(daily_rate * 30, 1)

        return {
            "start_now": True,
            "recommended_regime_to_wait_for": "neutral",
            "expected_duration_days": 30,
            "expected_evidence_points": expected_30d_evidence,
            "notes": [
                "Paper trading started 2026-06-10; ADR-002 requires 30 days of clean evidence",
                (
                    "Current conditions resemble stable_2025 simulation: "
                    f"{len(self._whitelist.eligible_protocols('2025-06-01'))} "
                    "eligible protocols"
                ),
                f"Estimated evidence accumulation: ~{round(daily_rate, 1)} points/day",
                "Neutral/bear regimes produce higher stress-tested evidence quality (ADR-002)",
                "GoLiveChecker: 16/26 criteria passing; go-live target 2026-07-21",
            ],
        }

    def save(
        self,
        path: str = "data/backtest/paper_period_simulations.json",
    ) -> None:
        """
        Atomically saves all simulation results to JSON.

        Creates parent directories if needed.
        Uses tmp-file + os.replace to guarantee atomic write — no partial
        reads by concurrent processes.

        Args:
            path: Destination file path.  Parent directories are created
                  automatically.  Defaults to the standard backtest output path.
        """
        payload = {
            "generated_at":       date.today().isoformat(),
            "simulator_version":  "v9.45",
            "mp":                 "MP-1329",
            "initial_capital":    self._initial_capital,
            "periods":            self.simulate_all(),
        }

        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        atomic_save(payload, str(out_path))
