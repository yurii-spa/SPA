"""
spa_core/strategy_lab/rates_desk/contracts.py — the Rate/Basis Sleeve dataclasses + enums.

The "on-chain rates desk" type system. EVERY money/rate field is a `Decimal` (replay-determinism:
floats are not associative under summation across replays). Every dataclass is FROZEN — an
Opportunity / GateResult / KillState produced by the pure engine cannot be mutated after the fact,
so the proof-chain hash of a verdict is stable.

Conventions inherited from the Strategy Lab + the repo rules:
  - PURE: nothing in this module reads the wall clock, does IO, or uses RNG. `as_of` is always an
    explicit input (an ISO date/timestamp string), never `datetime.now()`.
  - stdlib only.
  - LLM-FORBIDDEN in any pricing/policy path.
  - fail-CLOSED: malformed inputs are treated as MAX risk by the engine, never a silent pass.

All rates are DECIMAL fractions (0.053 == 5.3%/yr), all money is USD Decimal.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import enum
import hashlib
import json
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Dict, Optional, Tuple

# ── canonical zero/one Decimals (avoid re-parsing literals everywhere) ─────────────────────────
D0 = Decimal("0")
D1 = Decimal("1")


# ── enums ──────────────────────────────────────────────────────────────────────────────────────
class UnderlyingKind(enum.Enum):
    """What the tokenized yield is fundamentally backed by — drives the baseline-yield model."""
    STABLE_RWA = "stable_rwa"        # t-bill / RWA-backed stable (USDY, sUSDS via RWA): baseline = t-bill
    STABLE_SYNTH = "stable_synth"    # synthetic-dollar carry (sUSDe/USDe): baseline = funding carry (hedged)
    LST = "lst"                      # liquid staking token (stETH/rETH): baseline = staking yield
    LRT = "lrt"                      # liquid restaking token (ezETH/rsETH): baseline = STAKING ONLY (restaking premium NOT in baseline)


class RateVenue(enum.Enum):
    """Where the fixed/implied rate is quoted."""
    PENDLE_PT = "pendle_pt"          # Pendle Principal Token (fixed-rate)
    PENDLE_YT = "pendle_yt"          # Pendle Yield Token
    BOROS = "boros"                  # forward-funding venue (hedge / forward reference)
    LENDING = "lending"              # money-market borrow/supply (for levered carry)
    SPOT = "spot"


class TradeShape(enum.Enum):
    """The desk's trade archetypes. Phase-0 ships FIXED_CARRY; the rest are declared next."""
    FIXED_CARRY = "fixed_carry"      # buy PT, hold to maturity — lock a fixed rate (Phase 0)
    LEVERED_CARRY = "levered_carry"  # borrow stable, buy PT — amplify the spread (NEXT)
    BASIS_HEDGE = "basis_hedge"      # PT long vs forward-funding short — isolate the basis (NEXT)
    RATE_MATRIX = "rate_matrix"      # cross-venue rate arbitrage matrix (NEXT)


class KillReason(enum.Enum):
    """Why an entry was REFUSED or a held position was unwound. REFUSAL-FIRST ordering: the tail/
    structural vetoes precede the economic ones — a toxic book is killed even with great economics."""
    NONE = "none"
    TAIL_VETO = "tail_veto"                  # total_haircut > max (the fair-value REFUSE — vetoes everything)
    UNDERLYING_DEPEG = "underlying_depeg"    # the underlying token has depegged (NAV/market gap)
    ORACLE_STALE = "oracle_stale"            # the price/rate oracle is stale beyond tolerance
    STABLE_DEPEG = "stable_depeg"            # the debt/quote stable has depegged
    FUNDING_FLIP = "funding_flip"            # negative-funding streak (carry unwinding) past hysteresis
    ECONOMICS = "economics"                  # net edge below hurdle / edge not persistent
    SIZE_FLOOR = "size_floor"                # exit-capacity-bound size collapses below a tradeable floor
    # — hold-only continuous kills —
    CARRY_COMPRESSION = "carry_compression"  # the locked carry/basis has compressed away
    MATURITY_BUFFER = "maturity_buffer"      # too close to maturity to safely hold/roll
    UTILIZATION_TRAP = "utilization_trap"    # pool utilization too high to exit (levered/lending)
    CONCENTRATION = "concentration"          # position too large vs current exit liquidity
    EXIT_CAPACITY = "exit_capacity"          # current exit liquidity < position size — cannot get out


# ── market quote / risk inputs ──────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class RateQuote:
    """A fixed/implied-rate market on one underlying at one `as_of`. PURE input — `as_of` is given,
    never read from the clock. All rates Decimal fractions; all money Decimal USD."""
    underlying: str                  # symbol, e.g. "susde", "ezeth"
    kind: UnderlyingKind
    venue: RateVenue
    protocol: str                    # e.g. "pendle"
    market_id: str                   # e.g. PT address / market key
    tenor_seconds: int               # time to maturity in seconds (>=0)
    as_of: str                       # ISO date / timestamp the quote is valid for (explicit input)
    quoted_rate: Decimal             # the market-offered implied/fixed APY (decimal fraction)
    tvl_usd: Decimal                 # market TVL
    exit_liquidity_usd: Decimal      # USD that can be exited in one tick without undue impact
    hedge_available: bool = False    # is a forward-funding / Boros hedge available for this carry
    utilization: Decimal = D0        # pool utilization 0..1 (lending / levered legs)
    ltv: Decimal = D0                # max loan-to-value for the underlying as collateral (levered)
    cap_headroom_usd: Decimal = D0   # remaining supply/borrow cap room


@dataclass(frozen=True)
class UnderlyingRisk:
    """The per-underlying risk surface at `as_of`. Combines the validated tail-risk scorer's signals
    (peg distance / drift / funding) with the structural facts the desk needs (NAV vs market, oracle
    health, nesting, concentration). PURE input."""
    underlying: str
    as_of: str
    nav_redemption_value: Decimal    # protocol-honest redemption value per unit (the "real" peg ref)
    market_price: Decimal            # secondary-market price per unit
    peg_distance: Decimal            # |market - nav| / nav  (>=0 fraction) — the depeg signal
    peg_vol_30d: Decimal             # 30d vol of the peg (downside-drift proxy, fraction)
    redemption_sla_seconds: int      # how long a direct NAV redemption takes (liquidity backstop)
    reserve_fund_ratio: Decimal      # protocol reserve / insurance fund as fraction of TVL
    funding_neg_frac_90d: Decimal    # fraction of last 90d with NEGATIVE perp funding (carry-unwind signal)
    oracle_kind: str                 # "chainlink" | "twap" | "redstone" | "unknown" ...
    oracle_staleness_seconds: int    # age of the latest oracle update at as_of
    nested_protocol_count: int       # how many protocols this yield is stacked on (composability tail)
    top_borrower_share: Decimal      # largest single borrower's share of the pool (concentration tail)


# ── yield decomposition (baseline + haircuts) ─────────────────────────────────────────────────────
@dataclass(frozen=True)
class YieldDecomposition:
    """The fair-value breakdown: an honest baseline minus five risk haircuts → the fair yield. The
    quoted rate is only harvestable carry to the extent it CLEARS this fair yield + cost. Frozen +
    hashable so it joins the proof chain verbatim. Each haircut is a Decimal APY (>=0)."""
    underlying: str
    as_of: str
    baseline: Decimal                # honest expected yield absent mispricing (Decimal APY)
    peg_haircut: Decimal             # k_peg * peg risk
    funding_flip_haircut: Decimal    # k_funding * funding-unwind risk
    oracle_haircut: Decimal          # k_oracle * oracle-staleness risk
    liquidity_haircut: Decimal       # k_liq * (position vs exit liquidity) risk
    protocol_haircut: Decimal        # k_proto * (nesting + concentration) risk

    @property
    def total_haircut(self) -> Decimal:
        return (self.peg_haircut + self.funding_flip_haircut + self.oracle_haircut
                + self.liquidity_haircut + self.protocol_haircut)

    @property
    def fair_yield(self) -> Decimal:
        """baseline - total_haircut (may go negative → the asset is uninvestable at any rate)."""
        return self.baseline - self.total_haircut

    def proof(self) -> Dict[str, str]:
        """A hashable, string-exact view of the decomposition for the audit/proof chain."""
        return {
            "underlying": self.underlying,
            "as_of": self.as_of,
            "baseline": str(self.baseline),
            "peg_haircut": str(self.peg_haircut),
            "funding_flip_haircut": str(self.funding_flip_haircut),
            "oracle_haircut": str(self.oracle_haircut),
            "liquidity_haircut": str(self.liquidity_haircut),
            "protocol_haircut": str(self.protocol_haircut),
            "total_haircut": str(self.total_haircut),
            "fair_yield": str(self.fair_yield),
        }


# ── opportunity / gate / kill ───────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Opportunity:
    """A candidate trade the desk evaluates: a quote + the shape the desk would express it as +
    the requested size. PURE input."""
    quote: RateQuote
    shape: TradeShape
    requested_size_usd: Decimal


@dataclass(frozen=True)
class GateResult:
    """The verdict of the refusal-first gate for one Opportunity at one as_of. `approved` is the
    only thing that can let capital move; it is fail-CLOSED. `detail` is a string-exact dict that is
    hashable for the proof chain (joins YieldDecomposition.proof())."""
    approved: bool
    reason: KillReason
    as_of: str
    underlying: str
    shape: TradeShape
    net_edge: Decimal                       # fair-cleared, cost-net edge (Decimal APY; may be <0)
    approved_size_usd: Decimal              # exit-capacity-bound size (0 when refused)
    decomposition: YieldDecomposition
    detail: Dict[str, str] = field(default_factory=dict)

    def proof_hash(self) -> str:
        """Deterministic SHA-256 over the FULL verdict (decomposition + gate fields + detail). Two
        identical (inputs, as_of) runs produce the identical hash — the proof-chain anchor."""
        payload = {
            "approved": self.approved,
            "reason": self.reason.value,
            "as_of": self.as_of,
            "underlying": self.underlying,
            "shape": self.shape.value,
            "net_edge": str(self.net_edge),
            "approved_size_usd": str(self.approved_size_usd),
            "decomposition": self.decomposition.proof(),
            "detail": dict(sorted(self.detail.items())),
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class KillState:
    """The carry-forward state the gate threads between ticks so hysteresis (funding-flip streak) and
    continuous-kill memory survive across `evaluate_*` calls WITHOUT any hidden mutable global. FROZEN
    — the gate returns a NEW KillState each tick (pure state transition)."""
    neg_funding_streak: int = 0      # consecutive ticks with negative funding (funding-flip hysteresis)
    killed: bool = False             # has a continuous kill fired on a held position
    kill_reason: KillReason = KillReason.NONE
    last_as_of: str = ""             # the as_of of the last evaluation (audit)
    entry_carry: Optional[Decimal] = None  # the carry/basis locked at entry (compression baseline)
    high_util_since: Optional[int] = None  # epoch-seconds the pool first crossed max utilization
                                           # (continuous utilization-trap tracking); None == not high

    def proof(self) -> Dict[str, str]:
        return {
            "neg_funding_streak": str(self.neg_funding_streak),
            "killed": str(self.killed),
            "kill_reason": self.kill_reason.value,
            "last_as_of": self.last_as_of,
            "entry_carry": "" if self.entry_carry is None else str(self.entry_carry),
            "high_util_since": "" if self.high_util_since is None else str(self.high_util_since),
        }


# ── policy parameters ─────────────────────────────────────────────────────────────────────────────
def _cal(name: str, fallback: str) -> "Decimal":
    """Read a CALIBRATED_* constant from config.py as a Decimal (the calibration sweep's pinned value),
    fail-CLOSED to the documented fallback if config is unavailable. Kept module-local so the policy
    params stay Decimal-exact while their numeric values live in config.py (auditable / version-pinned,
    not hardcoded in the engine). LLM-forbidden, pure."""
    try:
        from spa_core.strategy_lab.rates_desk import config as _cfg
        return Decimal(str(getattr(_cfg, name)))
    except Exception:  # noqa: BLE001 — fail-CLOSED to the documented default
        return Decimal(fallback)


@dataclass(frozen=True)
class RatePolicyParams:
    """All RatePolicy thresholds in one frozen, version-pinned block (mirrors config.py constants but
    as Decimals so the whole policy path is Decimal-exact). The RatePolicy composes UNDER the global
    RiskPolicy and can only ever be MORE restrictive. Changing any value = a research-config change
    (record before any capital).

    The refusal threshold + haircut coefficients (`max_total_haircut`, `k_*`, `cap_*`) default to the
    CALIBRATED values pinned in config.py (the calibration sweep's robust-center output, §9) via the
    `_cal` factory — they are NOT hardcoded here, so a re-calibration updates config.py and the policy
    follows. The literal fallbacks equal the committed calibrated values (fail-CLOSED)."""
    # — refusal-first vetoes —
    max_total_haircut: Decimal = field(  # total_haircut above this → TAIL_VETO (the REFUSE) — CALIBRATED
        default_factory=lambda: _cal("CALIBRATED_MAX_TOTAL_HAIRCUT", "0.12"))
    max_peg_distance: Decimal = Decimal("0.01")       # |market-nav|/nav above this → UNDERLYING_DEPEG (1%)
    max_oracle_staleness_s: int = 3600                # oracle older than this → ORACLE_STALE (1h)
    max_stable_depeg: Decimal = Decimal("0.005")      # debt/quote stable depeg above this → STABLE_DEPEG (0.5%)
    funding_flip_streak_kill: int = 5                 # consecutive neg-funding ticks → FUNDING_FLIP (hysteresis)

    # — economics —
    cost_buffer: Decimal = Decimal("0.005")           # round-trip cost + safety margin (0.5%/yr)
    edge_hurdle: Decimal = Decimal("0.0")             # net_edge must clear this (after fair + cost)
    rwa_floor: Decimal = Decimal("0.034")             # the ~3.4% risk-free floor the book must beat

    # — sizing —
    max_size_frac_of_exit: Decimal = Decimal("0.25")  # never take more than 25% of one-tick exit liquidity
    min_tradeable_size_usd: Decimal = Decimal("1000") # below this the approved size is a SIZE_FLOOR refuse

    # — hold-side continuous kills —
    carry_compression_frac: Decimal = Decimal("0.5")  # locked carry compressed below this frac of entry → kill
    maturity_buffer_seconds: int = 86400 * 2          # within 2 days of maturity → MATURITY_BUFFER unwind
    max_hold_utilization: Decimal = Decimal("0.97")   # pool utilization above this → UTILIZATION_TRAP
    max_utilization_seconds: int = 0                  # util must stay above max CONTINUOUSLY this long
                                                      # before UTILIZATION_TRAP fires. DEFAULT 0 == fire on
                                                      # the first high tick (back-compat); set > 0 to require
                                                      # a sustained streak (transient-spike hysteresis).
    max_hold_concentration: Decimal = Decimal("0.40") # single-borrower share above this → CONCENTRATION

    # — haircut coefficients (k_*): haircut = k * normalized_risk, each clamped [0, cap] — CALIBRATED —
    k_peg: Decimal = field(default_factory=lambda: _cal("CALIBRATED_K_PEG", "4.0"))           # peg tail
    cap_peg: Decimal = field(default_factory=lambda: _cal("CALIBRATED_CAP_PEG", "0.10"))
    k_funding: Decimal = field(default_factory=lambda: _cal("CALIBRATED_K_FUNDING", "0.10"))  # fund overlay
    cap_funding: Decimal = field(default_factory=lambda: _cal("CALIBRATED_CAP_FUNDING", "0.06"))
    k_oracle: Decimal = field(default_factory=lambda: _cal("CALIBRATED_K_ORACLE", "0.04"))    # oracle stale
    cap_oracle: Decimal = field(default_factory=lambda: _cal("CALIBRATED_CAP_ORACLE", "0.04"))
    k_liquidity: Decimal = field(default_factory=lambda: _cal("CALIBRATED_K_LIQUIDITY", "0.06"))  # size/exit
    cap_liquidity: Decimal = field(default_factory=lambda: _cal("CALIBRATED_CAP_LIQUIDITY", "0.06"))
    k_protocol: Decimal = field(default_factory=lambda: _cal("CALIBRATED_K_PROTOCOL", "0.02"))  # nest+conc
    cap_protocol: Decimal = field(default_factory=lambda: _cal("CALIBRATED_CAP_PROTOCOL", "0.05"))

    # — baseline-model parameters —
    tbill_rate: Decimal = Decimal("0.044")            # current 3m t-bill (STABLE_RWA baseline)
    synth_conservative_floor: Decimal = Decimal("0.01")  # unhedged synthetic-stable conservative baseline
    staking_yield: Decimal = Decimal("0.029")         # ETH staking yield (LST/LRT baseline)


def to_proof_dict(obj) -> Dict[str, str]:
    """Best-effort string-exact view of any rates-desk dataclass for the proof chain (Decimals →
    str, enums → .value). Used by tests / audit to confirm a verdict is hashable + stable."""
    out: Dict[str, str] = {}
    for k, v in asdict(obj).items():
        if isinstance(v, Decimal):
            out[k] = str(v)
        elif isinstance(v, enum.Enum):
            out[k] = v.value
        else:
            out[k] = str(v)
    return out
