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


# ── CALIBRATED refusal threshold + haircut coefficients (§9 — the most consequential params) ──
# These are the OUTPUT of the deterministic calibration sweep (calibrate.py) over the DEEP 2024→2026
# data: the values that VETO 100% of toxic restaking (ezETH/rsETH) PT days before every stress event
# while FIRING 100% of the healthy sUSDe/USDe carry — chosen at the ROBUST CENTER of the admissible
# band (max min-distance to either failure cliff), NOT its loose edge.
#
# Measured cliffs on this data (k_peg=4.0, k_protocol=0.02):
#   • healthy sUSDe book total_haircut ≈ 0.0903  → strangles healthy carry below ~0.09
#   • toxic LRT book   total_haircut ≈ 0.1947    → leaks a toxic book at/above ~0.19
#   → admissible band [0.09, 0.18]; robust center ≈ 0.14; the pinned 0.12 sits with ~0.03 margin above
#     the strangle cliff and ~0.07 below the toxic-leak cliff (both healthy-side and toxic-side safe).
# The sweep CONFIRMS the prior defaults are at the robust optimum (it would not churn a risk cutoff for
# a cosmetic APY tick — repo rule #7). Changing any value here is a research-config / ADR event.
# Source-of-truth verdict + the full trade-off curve: docs/RATES_DESK_VALIDATION.md (calibration sweep).
CALIBRATED_MAX_TOTAL_HAIRCUT = 0.12   # total_haircut above this → TAIL_VETO (the REFUSE)
CALIBRATED_K_PEG = 4.0                 # peg-distance → APY haircut coefficient (the LRT depeg tail)
CALIBRATED_CAP_PEG = 0.10
CALIBRATED_K_FUNDING = 0.10            # funding-flip systemic overlay coefficient
CALIBRATED_CAP_FUNDING = 0.06
CALIBRATED_K_LIQUIDITY = 0.06          # size-vs-exit liquidity haircut coefficient
CALIBRATED_CAP_LIQUIDITY = 0.06
CALIBRATED_K_PROTOCOL = 0.02           # nesting + concentration tail coefficient
CALIBRATED_CAP_PROTOCOL = 0.05
CALIBRATED_K_ORACLE = 0.04
CALIBRATED_CAP_ORACLE = 0.04


# ════════════════════════════════════════════════════════════════════════════════════════════
# ── DATA-LAYER constants (feeds.py — the RateSurface assembler) ─────────────────────────────
# ════════════════════════════════════════════════════════════════════════════════════════════
# These are PURE DATA inputs the feeds stamp onto RateQuote / UnderlyingRisk rows. They are NOT
# judgment/haircuts (those live in the engine); they are documented facts about each underlying
# (redemption SLA, reserve fund, oracle, nesting) + the exit-liquidity proxy parameters. Every
# value here is auditable + version-pinned; changing one is a research-config change (record it).

# ── §9 exit-liquidity model ──────────────────────────────────────────────────────────────────
# exit_liquidity = pool_depth * (impact band as depth fraction) * sla_discount.
# The band is the price-impact tolerance: how far we let the marginal price move on the exit. The
# SLA discount linearly shrinks usable one-tick depth as the redemption cooldown grows (a long
# cooldown removes the redemption backstop intratick → only secondary depth absorbs the exit).
# PROXY — to be VALIDATED against the Oct-2025 restaking de-risk fills (RATES_DESK_DERISK.md).
EXIT_PRICE_IMPACT_BAND_BPS = 50      # 50 bps default price-impact band
SLA_DISCOUNT_PER_DAY = 0.05          # usable-depth haircut per day of redemption cooldown
SLA_DISCOUNT_FLOOR = 0.20            # never discount usable depth below 20% of the band slice

# Historical PT pool-depth proxy: the deep implied-yield history (pendle_pt_history) carries no TVL,
# so backtest days use this documented constant for the exit model. Live days use the real /active
# liquidity. Conservative (PT pools are concentrated): $5M nominal depth.
PENDLE_HIST_POOL_DEPTH_USD = 5_000_000

# ── per-underlying documented constants (UnderlyingRiskFeed) ─────────────────────────────────
# kind drives the baseline model in the engine (STABLE_RWA t-bill / STABLE_SYNTH carry / LST
# staking / LRT staking-only). Keys are lowercase symbols.
UNDERLYING_KINDS = {
    "susde": "stable_synth",     # Ethena staked-USDe (synthetic-dollar carry)
    "usde":  "stable_synth",     # Ethena USDe
    "usdy":  "stable_rwa",       # Ondo USDY (t-bill backed)
    "susds": "stable_rwa",       # Sky sUSDS (RWA backed)
    "usdc":  "stable_rwa",       # plain USD reference (lending quote stable)
    "eeth":  "lst",              # ether.fi (matched as PT-weETH; LST baseline)
    "weeth": "lst",
    "ezeth": "lrt",              # Renzo restaking
    "rseth": "lrt",              # KelpDAO restaking
    "steth": "lst",
    "reth":  "lst",
}

# Direct NAV-redemption SLA (seconds): how long a redemption-at-NAV actually takes. Documented per
# protocol; the exit-liquidity model discounts secondary depth by this. (sUSDe = Ethena's 7-day
# cooldown; RWA stables ~T+1; LRTs have multi-day restaking exit queues.)
REDEMPTION_SLA_SECONDS = {
    "susde": 86400 * 7,          # Ethena sUSDe 7-day unstake cooldown
    "usde":  86400 * 1,          # USDe mint/redeem ~T+0/T+1
    "usdy":  86400 * 2,          # Ondo USDY redemption ~T+2
    "susds": 86400 * 1,
    "usdc":  86400 * 1,
    "eeth":  86400 * 3,          # ether.fi withdrawal queue (~days)
    "weeth": 86400 * 3,
    "ezeth": 86400 * 7,          # Renzo restaking exit queue (multi-day)
    "rseth": 86400 * 7,          # KelpDAO restaking exit queue
    "steth": 86400 * 3,          # Lido withdrawal queue
    "reth":  86400 * 2,
}
DEFAULT_REDEMPTION_SLA_SECONDS = 86400 * 7   # fail-CLOSED default: assume the LONG cooldown

# Protocol reserve / insurance fund as a fraction of TVL. PLACEHOLDER constants — "pull live later"
# (Ethena reserve fund ~1.1% of TVL per their dashboard; others conservative/0 until a live feed).
RESERVE_FUND_RATIO = {
    "susde": 0.011,              # Ethena reserve fund ~1.1% (pull live later)
    "usde":  0.011,
    "usdy":  0.0,                # RWA backing is 1:1 t-bills, not a reserve buffer
    "susds": 0.0,
    "usdc":  0.0,
}
DEFAULT_RESERVE_FUND_RATIO = 0.0   # fail-CLOSED: no credited buffer unless documented

# Oracle kind + best-effort staleness tolerance baseline (seconds). Best-effort/documented; a live
# on-chain oracle-age probe can replace these later.
ORACLE_KIND = {
    "susde": "chainlink", "usde": "chainlink", "usdy": "chainlink",
    "susds": "chainlink", "usdc": "chainlink",
    "eeth": "redstone", "weeth": "redstone", "ezeth": "redstone",
    "rseth": "redstone", "steth": "chainlink", "reth": "chainlink",
}
DEFAULT_ORACLE_KIND = "unknown"
ORACLE_STALENESS_SECONDS = {
    # best-effort typical update age at as_of (seconds); chainlink ETH feeds ~heartbeat 3600s,
    # redstone LRT feeds push on deviation (~hourly). Documented baselines, not live ages.
    "susde": 300, "usde": 300, "usdy": 600, "susds": 600, "usdc": 300,
    "eeth": 600, "weeth": 600, "ezeth": 600, "rseth": 600, "steth": 300, "reth": 300,
}
DEFAULT_ORACLE_STALENESS_SECONDS = 3600   # fail-CLOSED: assume the worst tolerated age

# How many protocols a yield is STACKED on (composability tail). sUSDe = 1 (Ethena). A PT OF sUSDe =
# 2 (Pendle on Ethena). An LRT-PT is higher (restaking layer + Pendle). Documented per underlying.
NESTED_PROTOCOL_COUNT = {
    "susde": 1, "usde": 1, "usdy": 1, "susds": 1, "usdc": 0,
    "eeth": 1, "weeth": 1,
    "ezeth": 2,                  # Renzo (restaking) — restaking layer on top of staking
    "rseth": 2,                  # KelpDAO
    "steth": 1, "reth": 1,
}
DEFAULT_NESTED_PROTOCOL_COUNT = 2   # fail-CLOSED: unknown → assume nested

# Largest single-borrower share of a pool (concentration tail). Documented placeholder per
# underlying; a live on-chain top-borrower probe can replace it. Conservative non-zero defaults.
TOP_BORROWER_SHARE = {
    "susde": 0.10, "usde": 0.10, "usdy": 0.10, "susds": 0.10, "usdc": 0.10,
    "eeth": 0.20, "weeth": 0.20, "ezeth": 0.30, "rseth": 0.30, "steth": 0.15, "reth": 0.15,
}
DEFAULT_TOP_BORROWER_SHARE = 0.30   # fail-CLOSED: unknown concentration → assume high

# Map an underlying symbol to its price_feed X/ETH ratio key (eeth trades/prices as weeth).
RATIO_TOKEN = {"eeth": "weeth", "weeth": "weeth", "ezeth": "ezeth",
               "rseth": "ezeth", "steth": "steth", "reth": "reth"}

# ── LendingRateFeed targets (USDC money-markets + PT-collateral markets) ─────────────────────
# (project, chain, symbol) selectors like restaking_feed/btc_lending_feed. underlying = the quote
# stable for the levered/lending leg; kind drives the engine baseline. Highest-TVL match wins.
LENDING_TARGETS = [
    {"underlying": "usdc", "kind": "stable_rwa", "project": "aave-v3",
     "chain": "Ethereum", "symbol": "USDC"},
    {"underlying": "usdc", "kind": "stable_rwa", "project": "morpho-blue",
     "chain": "Ethereum", "symbol": "USDC"},
    {"underlying": "usdc", "kind": "stable_rwa", "project": "euler-v2",
     "chain": "Ethereum", "symbol": "USDC"},
]


# ── accessors (fail-CLOSED defaults) ─────────────────────────────────────────────────────────
from decimal import Decimal as _Dec  # noqa: E402


def exit_price_impact_band() -> _Dec:
    """Price-impact band as a Decimal depth FRACTION (bps/10000)."""
    return _Dec(str(EXIT_PRICE_IMPACT_BAND_BPS)) / _Dec("10000")


def underlying_kind(underlying: str):
    """UnderlyingKind for a symbol. fail-CLOSED: an unknown symbol RAISES (never a benign default —
    a mis-tagged kind would silently pick the wrong baseline model)."""
    from spa_core.strategy_lab.rates_desk.contracts import UnderlyingKind
    u = (underlying or "").lower()
    if u not in UNDERLYING_KINDS:
        raise ValueError(f"rates_desk config: unknown underlying kind for {underlying!r}")
    return UnderlyingKind(UNDERLYING_KINDS[u])


def redemption_sla_seconds(underlying: str) -> int:
    return int(REDEMPTION_SLA_SECONDS.get((underlying or "").lower(), DEFAULT_REDEMPTION_SLA_SECONDS))


def reserve_fund_ratio(underlying: str) -> float:
    return float(RESERVE_FUND_RATIO.get((underlying or "").lower(), DEFAULT_RESERVE_FUND_RATIO))


def oracle_kind(underlying: str) -> str:
    return ORACLE_KIND.get((underlying or "").lower(), DEFAULT_ORACLE_KIND)


def oracle_staleness_seconds(underlying: str) -> int:
    return int(ORACLE_STALENESS_SECONDS.get((underlying or "").lower(),
                                            DEFAULT_ORACLE_STALENESS_SECONDS))


def nested_protocol_count(underlying: str) -> int:
    return int(NESTED_PROTOCOL_COUNT.get((underlying or "").lower(), DEFAULT_NESTED_PROTOCOL_COUNT))


def top_borrower_share(underlying: str) -> float:
    return float(TOP_BORROWER_SHARE.get((underlying or "").lower(), DEFAULT_TOP_BORROWER_SHARE))


def ratio_token_for(underlying: str) -> str:
    """price_feed X/ETH ratio key for a staked-ETH underlying. fail-CLOSED: unknown → the symbol
    itself (so the feed's missing-series check fires honestly rather than silently aliasing)."""
    u = (underlying or "").lower()
    return RATIO_TOKEN.get(u, u)
