"""
spa_core/strategy_lab/rates_desk/config.py — all Rates-Desk thresholds in one place.

No magic numbers in the scorer/fair-value logic — every cutoff lives here so it is auditable
and version-pinned. Changing any value is a research-config change (record in the de-risk doc /
a new ADR before any capital). Pure data; LLM-forbidden.

Calibration note: the depeg signal is measured on a SHORT TRAILING MEDIAN of the X/ETH ratio
(the same false-depeg remedy as strategies/eth_lst_neutral.py + variant_n.py — DeFiLlama logs
the LST/LRT and ETH at different intraday moments, producing spurious 1-day ratio spikes). The
ratio is NOT assumed to be ~1.0: value-accruing wrappers (weETH, rETH, ezETH) drift ABOVE 1.0
over time, so "depeg" is measured as a DRAWDOWN from the ratio's own trailing peak, never as
absolute distance from 1.0.
"""
# LLM_FORBIDDEN
from __future__ import annotations

# ── tail-risk scorer ────────────────────────────────────────────────────────────────────────
RATIO_MEDIAN_WINDOW = 5      # trailing-median window (days) to de-noise the X/ETH ratio
RATIO_PEAK_WINDOW = 30       # trailing window (days) for the "peg reference" peak (depeg = DD vs it)
DRIFT_VOL_WINDOW = 30        # trailing window (days) for downside-drift volatility
FUNDING_WINDOW = 30          # trailing window (days) for funding-flip probability

# Score-component normalizers (a component hits ~1.0 of its sub-score at these magnitudes).
# Calibrated from the real 2024-2026 series (LST proper ~0.45% downside-drift vol, LRT ~0.85%;
# LRT ratio drawdowns reach 5-6%, LST proper ~3-4%). Conservative = a modest toxic signal already
# pushes the score up.
DEPEG_DD_FULL = 0.06         # a 6% drawdown-from-trailing-peak of the smoothed ratio → full depeg sub-score
DRIFT_VOL_FULL = 0.009       # 0.9% daily downside-drift vol → full drift sub-score
FUNDING_FLIP_FULL = 0.40     # 40% of recent days with NEGATIVE funding → full funding sub-score

# Sub-score weights (sum to 1.0). The per-underlying signals (depeg drawdown + downside-drift
# vol of the smoothed X/ETH ratio) MUST dominate, because they are what actually discriminate a
# toxic LRT from a tight-peg LST in the real 2024-2026 data (downside-drift vol: ezETH/eETH
# ~0.84%, stETH ~0.46%). Funding-flip is a SYSTEMIC regime overlay — it is the SAME shared ETH
# perp funding for every token, so it does NOT discriminate between underlyings; it only flags
# WHEN the broad carry regime is unwinding (negative funding = a delta-neutral short hedge
# BLEEDS). It therefore gets a small weight: it raises everyone's score in a bad regime without
# washing out the per-token ranking. (Calibration finding, recorded in RATES_DESK_DERISK.md: at
# the original 0.20 funding weight the uniform ~0.07 funding floor collapsed the toxic-vs-safe
# separation; dropping it to 0.10 and lifting the drift weight restored a clean ranking.)
W_DEPEG = 0.30
W_DRIFT = 0.60
W_FUNDING = 0.10

# Tail-risk classification cutoff: score >= this → "toxic" (REFUSE the yield on tail grounds).
TAIL_REFUSE_THRESHOLD = 0.45

# "Stays low" band for the SAFE LSTs: a single systemic crash (Aug-2024) briefly spikes EVERY
# staked-ETH token — that is honest market behavior, not a scorer failure. The discriminating
# test is therefore the MEDIAN (typical-regime) score, which must stay below this for a safe LST.
SAFE_MEDIAN_BAND = 0.30

# ── fair value ──────────────────────────────────────────────────────────────────────────────
# Fair implied yield = baseline_yield - tail_risk_haircut. The haircut is the extra yield a
# rational lender would DEMAND per unit of tail score (i.e. how much of a high quoted yield is
# just tail compensation). 12%/yr at full tail score is the max haircut.
MAX_TAIL_HAIRCUT_APY = 0.12  # haircut at tail_score == 1.0 (linear in the score)

# A market is CARRY (safe to harvest) when quoted_implied - fair > COST_BUFFER AND tail < refuse.
# It is REFUSE when tail >= refuse (the high yield is explained by tail-comp) OR the spread does
# not clear cost. COST_BUFFER bundles round-trip cost + a margin of safety.
COST_BUFFER_APY = 0.005      # 0.5%/yr round-trip cost + safety margin

# The RWA risk-free floor the carry book must beat risk-adjusted (per the thesis / our rwa feed).
RWA_FLOOR_APY = 0.034        # ~3.4%/yr
