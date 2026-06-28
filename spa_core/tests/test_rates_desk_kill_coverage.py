"""
spa_core/tests/test_rates_desk_kill_coverage.py — T8 SAFETY-PATH coverage hardening.

The refusal gate (evaluate_entry) + every continuous hold-kill (evaluate_hold) is the ENTIRE safety
story of the rates desk. This module gives EACH KillReason an ISOLATED unit test that fires exactly
that kill with minimal inputs, plus a FAIL-CLOSED edge case (missing / None / malformed data on that
input must REFUSE, never silently allow), plus refusal-FIRST ORDERING assertions (a book that is both
toxic AND has spectacular economics is refused on the structural reason, never on economics).

These complement (do not duplicate) the kills already exercised in test_rates_desk_engine.py and
test_rates_desk_sleeves.py. Pure synthetic, Decimal end-to-end, deterministic, no network/clock.
Tests ONLY — rate_policy semantics are not changed.

Per-KillReason map (E=entry path, H=hold path, FC=fail-closed edge here):
  TAIL_VETO          E, FC(engine max-haircut on malformed risk)
  UNDERLYING_DEPEG   E, H, FC(None/negative peg) both paths
  ORACLE_STALE       E, H, FC(non-int staleness) both paths   <-- NEW (was uncovered)
  STABLE_DEPEG       E, H, FC(malformed debt price) both paths <-- NEW (was uncovered)
  FUNDING_FLIP       H (entry already covered), FC(malformed funding -> engine cap haircut)
  ECONOMICS          E, FC(malformed quoted_rate)             <-- NEW (was uncovered)
  SIZE_FLOOR         E (covered), FC(malformed exit/req)      <-- NEW fail-closed
  CARRY_COMPRESSION  H (covered), FC(malformed current_carry) <-- NEW fail-closed
  MATURITY_BUFFER    H (covered), FC(non-int tenor)           <-- NEW fail-closed
  UTILIZATION_TRAP   H (covered), FC(unparseable as_of while high-util) <-- NEW fail-closed
  CONCENTRATION      H (covered), FC(malformed top_borrower_share surfaced) <-- NEW + FINDING
  EXIT_CAPACITY      H (covered), FC(zero exit covered; malformed req here)
"""
# LLM_FORBIDDEN
from __future__ import annotations

from decimal import Decimal as D

from spa_core.strategy_lab.rates_desk.contracts import (
    D0,
    KillReason,
    KillState,
    Opportunity,
    RatePolicyParams,
    RateQuote,
    RateVenue,
    TradeShape,
    UnderlyingKind,
    UnderlyingRisk,
)
from spa_core.strategy_lab.rates_desk.fair_value_engine import FairValueEngine
from spa_core.strategy_lab.rates_desk.rate_policy import evaluate_entry, evaluate_hold

P = RatePolicyParams()
ENG = FairValueEngine(P)
AS_OF = "2026-06-01"

# economics kwargs that make a healthy STABLE_SYNTH book CLEAR the hurdle (so a refusal we observe is
# never an accidental ECONOMICS kill — the structural veto is what fired).
_ECON = dict(engine=ENG, trailing_yield=D("0.05"), boros_forward=D("0.048"))


def _risk(**over) -> UnderlyingRisk:
    """A structurally HEALTHY susde risk surface — every field benign so a single overridden field is
    the SOLE cause of any kill (isolation)."""
    base = dict(
        underlying="susde", as_of=AS_OF,
        nav_redemption_value=D("1"), market_price=D("1.0003"), peg_distance=D("0.0003"),
        peg_vol_30d=D("0.001"), redemption_sla_seconds=86400, reserve_fund_ratio=D("0.05"),
        funding_neg_frac_90d=D("0.05"), oracle_kind="chainlink", oracle_staleness_seconds=300,
        nested_protocol_count=1, top_borrower_share=D("0.1"),
    )
    base.update(over)
    return UnderlyingRisk(**base)


def _quote(**over) -> RateQuote:
    base = dict(
        underlying="susde", kind=UnderlyingKind.STABLE_SYNTH, venue=RateVenue.PENDLE_PT, protocol="p",
        market_id="PT-susde", tenor_seconds=86400 * 60, as_of=AS_OF, quoted_rate=D("0.09"),
        tvl_usd=D("5e7"), exit_liquidity_usd=D("2e6"), hedge_available=True, utilization=D("0.5"),
    )
    base.update(over)
    return RateQuote(**base)


def _opp(q=None, size="100000") -> Opportunity:
    return Opportunity(quote=q or _quote(), shape=TradeShape.FIXED_CARRY, requested_size_usd=D(size))


def _entry(risk, debt=D("1"), exit_liq=D("2e6"), opp=None, params=P, state=None):
    return evaluate_entry(opp or _opp(), risk, debt, exit_liq, params, state or KillState(), **_ECON)


def _hold(risk, debt=D("1"), exit_liq=D("2e6"), carry=D("0.05"), opp=None, params=P, state=None,
          engine=ENG):
    return evaluate_hold(opp or _opp(), risk, debt, exit_liq, carry, params,
                         state or KillState(entry_carry=D("0.05")), engine=engine)


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# ORACLE_STALE — entry + hold + fail-closed  (was entirely UNCOVERED)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_oracle_stale_entry_fires():
    # staleness just over the 1h tolerance; peg/stable/funding all benign so ONLY oracle can veto.
    res, _ = _entry(_risk(oracle_staleness_seconds=P.max_oracle_staleness_s + 1))
    assert res.approved is False
    assert res.reason == KillReason.ORACLE_STALE


def test_oracle_stale_entry_fail_closed_on_missing():
    # missing staleness (None) → cannot prove the oracle is fresh → treat as stale → REFUSE.
    res, _ = _entry(_risk(oracle_staleness_seconds=None))
    assert res.approved is False
    assert res.reason == KillReason.ORACLE_STALE


def test_oracle_stale_entry_fail_closed_on_negative():
    res, _ = _entry(_risk(oracle_staleness_seconds=-5))
    assert res.approved is False
    assert res.reason == KillReason.ORACLE_STALE


def test_oracle_stale_hold_fires_and_kills():
    res, ns = _hold(_risk(oracle_staleness_seconds=P.max_oracle_staleness_s + 9999))
    assert res.approved is False
    assert res.reason == KillReason.ORACLE_STALE
    assert ns.killed is True


def test_oracle_stale_hold_fail_closed_on_missing():
    res, ns = _hold(_risk(oracle_staleness_seconds=None))
    assert res.approved is False
    assert res.reason == KillReason.ORACLE_STALE
    assert ns.killed is True


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# STABLE_DEPEG — entry + hold + fail-closed  (was entirely UNCOVERED)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_stable_depeg_entry_fires():
    # debt/quote stable at 0.99 → 1% off peg > 0.5% tolerance.
    res, _ = _entry(_risk(), debt=D("0.99"))
    assert res.approved is False
    assert res.reason == KillReason.STABLE_DEPEG


def test_stable_depeg_entry_fail_closed_on_malformed_price():
    # an unparseable debt price → cannot assess the stable's peg → REFUSE (never assume pegged).
    res, _ = _entry(_risk(), debt="not-a-number")
    assert res.approved is False
    assert res.reason == KillReason.STABLE_DEPEG
    assert res.detail["debt_asset_price"] == "malformed"


def test_stable_depeg_hold_fires_and_kills():
    res, ns = _hold(_risk(), debt=D("0.98"))
    assert res.approved is False
    assert res.reason == KillReason.STABLE_DEPEG
    assert ns.killed is True


def test_stable_depeg_hold_fail_closed_on_malformed_price():
    res, ns = _hold(_risk(), debt=None)
    assert res.approved is False
    assert res.reason == KillReason.STABLE_DEPEG
    assert ns.killed is True


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# ECONOMICS (EDGE_BELOW_HURDLE) — entry + fail-closed  (was UNCOVERED)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_economics_entry_fires_below_hurdle():
    # structurally pristine book but a quoted rate that does NOT clear fair_yield + cost → ECONOMICS.
    q = _quote(quoted_rate=D("0.02"))  # below the ~5% fair carry → net edge negative
    res, _ = _entry(_risk(), opp=_opp(q))
    assert res.approved is False
    assert res.reason == KillReason.ECONOMICS
    assert res.net_edge < D0


def test_economics_entry_fail_closed_on_malformed_quoted_rate():
    # a malformed quoted rate cannot be shown to beat fair value → REFUSE (never assume positive edge).
    q = _quote(quoted_rate="bad")
    res, _ = _entry(_risk(), opp=_opp(q))
    assert res.approved is False
    assert res.reason == KillReason.ECONOMICS
    assert res.detail["quoted_rate"] == "malformed"


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# SIZE_FLOOR — fail-closed on malformed/zero exit & requested size  (kill itself covered elsewhere)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_size_floor_fail_closed_on_malformed_exit_liquidity():
    # missing exit liquidity → cannot size against exit capacity → REFUSE.
    res, _ = _entry(_risk(), exit_liq="garbage")
    assert res.approved is False
    assert res.reason == KillReason.SIZE_FLOOR
    assert res.detail["exit_liquidity"] == "malformed"


def test_size_floor_fail_closed_on_zero_exit_liquidity():
    res, _ = _entry(_risk(), exit_liq=D("0"))
    assert res.approved is False
    assert res.reason == KillReason.SIZE_FLOOR


def test_size_floor_fail_closed_on_malformed_requested_size():
    res, _ = _entry(_risk(), opp=_opp(size="0"))
    assert res.approved is False
    assert res.reason == KillReason.SIZE_FLOOR


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# FUNDING_FLIP — hold path + fail-closed via the engine funding haircut
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_funding_flip_hold_fires_on_sustained_streak():
    # carry forward a streak one short of the kill; one more hostile tick on hold trips FUNDING_FLIP.
    st = KillState(entry_carry=D("0.05"), neg_funding_streak=P.funding_flip_streak_kill - 1)
    res, ns = _hold(_risk(funding_neg_frac_90d=D("0.60")), state=st)
    assert res.approved is False
    assert res.reason == KillReason.FUNDING_FLIP
    assert ns.neg_funding_streak >= P.funding_flip_streak_kill


def test_funding_flip_fail_closed_via_engine_haircut():
    # FAIL-CLOSED: a malformed funding signal cannot prove funding is benign → the engine charges the
    # MAX funding haircut (cap_funding), never a silent zero. This maxed haircut is exactly what feeds
    # the TAIL_VETO aggregate (test_tail_veto_fail_closed_on_fully_malformed_risk proves the gate-level
    # refusal when malformed inputs STACK past max_total_haircut). The hysteresis FUNDING_FLIP kill is
    # a separate, streak-based veto (covered by test_funding_flip_hold_fires_on_sustained_streak and
    # the entry hysteresis test in test_rates_desk_engine.py).
    bad = ENG.fair(_risk(funding_neg_frac_90d="bad"), UnderlyingKind.STABLE_SYNTH, 86400 * 60, True,
                   D("100000"), D("2e6"), AS_OF, trailing_yield=D("0.05"), boros_forward=D("0.048"))
    benign = ENG.fair(_risk(funding_neg_frac_90d=D("0.05")), UnderlyingKind.STABLE_SYNTH, 86400 * 60,
                      True, D("100000"), D("2e6"), AS_OF, trailing_yield=D("0.05"),
                      boros_forward=D("0.048"))
    assert bad.funding_flip_haircut == P.cap_funding          # malformed → MAX haircut
    assert bad.funding_flip_haircut > benign.funding_flip_haircut  # never silently the benign zero


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# MATURITY_BUFFER — fail-closed on a non-int tenor  (kill itself covered elsewhere)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_maturity_buffer_hold_fail_closed_on_non_int_tenor():
    # a malformed tenor → cannot prove there is enough runway to safely hold/roll → UNWIND.
    res, ns = _hold(_risk(), opp=_opp(_quote(tenor_seconds=None)))
    assert res.approved is False
    assert res.reason == KillReason.MATURITY_BUFFER
    assert ns.killed is True


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# UTILIZATION_TRAP — fail-closed when as_of is unparseable while utilization is high
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_utilization_trap_hold_fail_closed_on_unparseable_as_of():
    # With a sustained-streak window configured, a high-util tick whose as_of cannot be parsed means
    # the high-util DURATION cannot be measured → kill immediately (fail-CLOSED), do not wait it out.
    Pu = RatePolicyParams(max_utilization_seconds=3600)
    q = _quote(utilization=D("0.99"), as_of="not-a-date")
    res, ns = evaluate_hold(_opp(q), _risk(), D("1"), D("2e6"), D("0.05"), Pu,
                            KillState(entry_carry=D("0.05")), engine=FairValueEngine(Pu))
    assert res.approved is False
    assert res.reason == KillReason.UTILIZATION_TRAP
    assert ns.killed is True


def test_utilization_trap_hold_fires_immediately_default_window():
    # DEFAULT max_utilization_seconds == 0 → a single high tick traps at once (back-compat).
    res, ns = _hold(_risk(), opp=_opp(_quote(utilization=D("0.99"))))
    assert res.approved is False
    assert res.reason == KillReason.UTILIZATION_TRAP


def test_utilization_trap_hold_empty_as_of_is_fail_closed():
    # an EMPTY as_of is unparseable (_as_of_epoch → None) → high-util duration cannot be measured →
    # kill immediately (fail-CLOSED), proving the empty-string branch of _as_of_epoch.
    Pu = RatePolicyParams(max_utilization_seconds=3600)
    q = _quote(utilization=D("0.99"), as_of="")
    res, ns = evaluate_hold(_opp(q), _risk(as_of=""), D("1"), D("2e6"), D("0.05"), Pu,
                            KillState(entry_carry=D("0.05")), engine=FairValueEngine(Pu))
    assert res.approved is False
    assert res.reason == KillReason.UTILIZATION_TRAP


def test_utilization_trap_streak_accrues_then_fires_across_ticks():
    """Hysteresis carry-forward: with a sustained-streak window, a high-util tick does NOT trap yet —
    it stamps high_util_since; a LATER tick (still high) past the window then traps. Proves the
    'carry the original crossing timestamp forward' branch and that the streak HOLDS the position
    (approved) until the duration is met."""
    Pu = RatePolicyParams(max_utilization_seconds=3600)  # must stay high for 1h
    eng = FairValueEngine(Pu)
    # tick 1 at T0: high util, fresh streak → HOLD (not yet long enough), stamps high_util_since.
    q1 = _quote(utilization=D("0.99"), as_of="2026-06-01T00:00:00Z")
    res1, st1 = evaluate_hold(_opp(q1), _risk(as_of="2026-06-01T00:00:00Z"), D("1"), D("2e6"),
                              D("0.05"), Pu, KillState(entry_carry=D("0.05")), engine=eng)
    assert res1.approved is True            # high but not yet trapped
    assert st1.high_util_since is not None  # streak stamped (full-timestamp as_of parsed)
    # tick 2 at T0+2h: still high, original crossing carried forward → elapsed >= window → TRAP.
    q2 = _quote(utilization=D("0.99"), as_of="2026-06-01T02:00:00Z")
    res2, st2 = evaluate_hold(_opp(q2), _risk(as_of="2026-06-01T02:00:00Z"), D("1"), D("2e6"),
                              D("0.05"), Pu, st1, engine=eng)
    assert res2.approved is False
    assert res2.reason == KillReason.UTILIZATION_TRAP
    assert st2.high_util_since == st1.high_util_since  # the ORIGINAL crossing ts was carried forward


def test_utilization_trap_naive_timestamp_as_of_is_anchored_utc():
    """A full timestamp WITHOUT a tz suffix is treated as UTC (naive→UTC anchor branch of
    _as_of_epoch), so high-util duration is still measurable across two such ticks → trap fires."""
    Pu = RatePolicyParams(max_utilization_seconds=3600)
    eng = FairValueEngine(Pu)
    q1 = _quote(utilization=D("0.99"), as_of="2026-06-01T00:00:00")  # no Z, no offset → naive
    res1, st1 = evaluate_hold(_opp(q1), _risk(as_of="2026-06-01T00:00:00"), D("1"), D("2e6"),
                              D("0.05"), Pu, KillState(entry_carry=D("0.05")), engine=eng)
    assert res1.approved is True and st1.high_util_since is not None
    q2 = _quote(utilization=D("0.99"), as_of="2026-06-01T02:00:00")
    res2, _ = evaluate_hold(_opp(q2), _risk(as_of="2026-06-01T02:00:00"), D("1"), D("2e6"),
                            D("0.05"), Pu, st1, engine=eng)
    assert res2.approved is False and res2.reason == KillReason.UTILIZATION_TRAP


def test_utilization_streak_resets_when_util_drops():
    """When utilization falls back to/below the ceiling the high-util streak RESETS (high_util_since
    cleared) — a transient spike never accumulates toward a trap."""
    Pu = RatePolicyParams(max_utilization_seconds=3600)
    eng = FairValueEngine(Pu)
    st = KillState(entry_carry=D("0.05"), high_util_since=1700000000)  # pretend mid-streak
    # util now benign → streak must reset.
    res, ns = evaluate_hold(_opp(_quote(utilization=D("0.50"), as_of="2026-06-01T05:00:00Z")),
                            _risk(as_of="2026-06-01T05:00:00Z"), D("1"), D("2e6"), D("0.05"), Pu, st,
                            engine=eng)
    assert res.approved is True
    assert ns.high_util_since is None  # reset


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# EXIT_CAPACITY — fail-closed on a malformed/non-positive position size  (zero-exit covered elsewhere)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_exit_capacity_hold_fail_closed_on_zero_position_size():
    # a non-positive position size is malformed input → kill (cannot reason about exit at size).
    res, ns = _hold(_risk(), opp=_opp(size="0"))
    assert res.approved is False
    assert res.reason == KillReason.EXIT_CAPACITY
    assert ns.killed is True


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# CARRY_COMPRESSION — fail-closed on a malformed current carry  (kill itself covered elsewhere)
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_carry_compression_hold_fail_closed_on_malformed_carry():
    # if the realized carry cannot be measured we cannot prove the basis still holds → UNWIND.
    res, ns = _hold(_risk(), carry="garbage")
    assert res.approved is False
    assert res.reason == KillReason.CARRY_COMPRESSION
    assert ns.killed is True


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# CONCENTRATION (BORROWER_CONCENTRATION) — fires on over-exit; malformed borrower-share surfaced.
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_concentration_hold_fires_on_size_over_exit():
    # position 100k, exit 300k → NOT a collapse (300k > 100k, so not EXIT_CAPACITY) but 100k/300k=0.33
    # exceeds the 0.25 max_size_frac_of_exit → CONCENTRATION (early derisk before an illiquid bag).
    res, _ = _hold(_risk(), exit_liq=D("300000"), opp=_opp(_quote(exit_liquidity_usd=D("300000"))))
    assert res.approved is False
    assert res.reason == KillReason.CONCENTRATION


def test_concentration_hold_fail_closed_surfaces_malformed_borrower_share():
    """FAIL-CLOSED edge for the borrower-concentration input. A malformed top_borrower_share is
    surfaced as 'malformed' in the CONCENTRATION detail when the position is ALSO over its exit cap.

    FINDING (not changed — tests only): a malformed top_borrower_share ALONE does not fail-closed.
    `over_borrower = (topb is not None and ...)` is False when topb is None, so if exit liquidity is
    healthy the gate returns NONE rather than refusing — the only branch in the safety story that does
    NOT fail closed on a missing input. Here we pin the actual behavior (CONCENTRATION via over_exit,
    with the malformed share reported); see test_concentration_malformed_share_alone_does_not_refuse
    which documents the gap explicitly."""
    res, _ = _hold(_risk(top_borrower_share="bad"), exit_liq=D("300000"),
                   opp=_opp(_quote(exit_liquidity_usd=D("300000"))))
    assert res.approved is False
    assert res.reason == KillReason.CONCENTRATION
    assert res.detail["top_borrower_share"] == "malformed"


def test_concentration_malformed_share_alone_refuses_for_borrow_bearing_shape():
    """SHAPE-AWARE fail-CLOSED (hardened): for a shape that carries a BORROW/lending leg
    (LEVERED_CARRY / RATE_MATRIX) borrower concentration is a real tail. A bare malformed/None
    top_borrower_share — even with otherwise healthy inputs (healthy exit liquidity) — means we
    cannot confirm the pool is not crowded by one borrower → REFUSE (BORROWER_CONCENTRATION).
    This is the fix for the former SOURCE GAP (over_borrower short-circuited to False on None)."""
    levered = Opportunity(quote=_quote(), shape=TradeShape.LEVERED_CARRY,
                          requested_size_usd=D("100000"))
    res, ns = _hold(_risk(top_borrower_share="bad"), opp=levered)  # healthy exit, only share malformed
    assert res.approved is False
    assert res.reason == KillReason.CONCENTRATION
    assert res.detail["top_borrower_share"] == "malformed"
    assert ns.killed is True

    # RATE_MATRIX is the other borrow-bearing shape — same fail-closed behavior.
    matrix = Opportunity(quote=_quote(), shape=TradeShape.RATE_MATRIX,
                         requested_size_usd=D("100000"))
    res2, ns2 = _hold(_risk(top_borrower_share="bad"), opp=matrix)
    assert res2.approved is False
    assert res2.reason == KillReason.CONCENTRATION
    assert ns2.killed is True


def test_concentration_malformed_share_alone_is_na_for_fixed_carry():
    """N/A side of the shape-aware rule: for a NO-borrow-leg shape (FIXED_CARRY held-to-maturity PT)
    borrower concentration is irrelevant, so a None/malformed top_borrower_share with otherwise
    healthy inputs is legitimately not-applicable and must NOT spuriously refuse — the gate HOLDS."""
    # default _opp() shape is FIXED_CARRY, healthy exit liquidity, only the share malformed.
    res, ns = _hold(_risk(top_borrower_share="bad"))
    assert res.approved is True
    assert res.reason == KillReason.NONE
    assert ns.killed is False


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# REFUSAL-FIRST ORDERING — structural vetoes precede economics even with spectacular quotes
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_ordering_stable_depeg_beats_great_economics_entry():
    # a 50% quote (economics would clearly pass) on a book whose debt-stable has depegged → the
    # STRUCTURAL veto fires, never ECONOMICS / approval.
    res, _ = _entry(_risk(), debt=D("0.90"), opp=_opp(_quote(quoted_rate=D("0.50"))))
    assert res.approved is False
    assert res.reason == KillReason.STABLE_DEPEG


def test_ordering_oracle_stale_beats_great_economics_entry():
    res, _ = _entry(_risk(oracle_staleness_seconds=P.max_oracle_staleness_s + 1),
                    opp=_opp(_quote(quoted_rate=D("0.50"))))
    assert res.approved is False
    assert res.reason == KillReason.ORACLE_STALE


def test_ordering_tail_veto_precedes_every_other_veto_entry():
    """A book that simultaneously trips the TAIL haircut, the peg veto, the oracle veto AND the
    stable-depeg veto must report TAIL_VETO — it is checked first and short-circuits."""
    toxic = _risk(peg_distance=D("0.02"), peg_vol_30d=D("0.05"), funding_neg_frac_90d=D("0.5"),
                  oracle_staleness_seconds=999999, nested_protocol_count=5, top_borrower_share=D("0.7"))
    res, _ = _entry(toxic, debt=D("0.90"), opp=_opp(_quote(quoted_rate=D("0.50"))))
    assert res.approved is False
    assert res.reason == KillReason.TAIL_VETO


def test_ordering_entry_veto_chain_peels_in_documented_order():
    """Peel the vetoes one at a time: fixing the higher-priority structural input each time reveals
    the NEXT veto in the exact documented order — proving the short-circuit chain
    TAIL_VETO → UNDERLYING_DEPEG → ORACLE_STALE → STABLE_DEPEG → FUNDING_FLIP → ECONOMICS."""
    great = _opp(_quote(quoted_rate=D("0.50")))

    # (1) everything broken → TAIL_VETO
    r = _risk(peg_distance=D("0.02"), peg_vol_30d=D("0.05"), funding_neg_frac_90d=D("0.6"),
              oracle_staleness_seconds=999999, nested_protocol_count=5, top_borrower_share=D("0.7"))
    res, _ = _entry(r, debt=D("0.90"), opp=great, state=KillState(neg_funding_streak=99))
    assert res.reason == KillReason.TAIL_VETO

    # (2) heal the haircut (benign tail) but keep peg JUST over the 1% gate → UNDERLYING_DEPEG.
    #     NOTE (structural-veto fix): the peg must be only just over 1% so the STRUCTURAL haircut
    #     (peg+funding+oracle+protocol) stays <= max_structural_haircut — otherwise the size-proof
    #     TAIL_VETO (which now precedes UNDERLYING_DEPEG and catches a large depeg as toxicity at any
    #     size) fires first. A 2% peg is now correctly a structural tail breach; a ~1.05% peg trips
    #     only the hard UNDERLYING_DEPEG gate while the structural haircut stays under the toxicity cap.
    r = _risk(peg_distance=D("0.0105"))  # over the 1% peg gate, structural haircut still < toxicity cap
    res, _ = _entry(r, opp=great)
    assert res.reason == KillReason.UNDERLYING_DEPEG

    # (3) heal peg, break oracle → ORACLE_STALE
    res, _ = _entry(_risk(oracle_staleness_seconds=P.max_oracle_staleness_s + 1), opp=great)
    assert res.reason == KillReason.ORACLE_STALE

    # (4) heal oracle, break the debt stable → STABLE_DEPEG
    res, _ = _entry(_risk(), debt=D("0.90"), opp=great)
    assert res.reason == KillReason.STABLE_DEPEG

    # (5) heal the stable, drive a sustained funding streak → FUNDING_FLIP
    st = KillState(neg_funding_streak=P.funding_flip_streak_kill - 1)
    res, _ = _entry(_risk(funding_neg_frac_90d=D("0.6")), opp=great, state=st)
    assert res.reason == KillReason.FUNDING_FLIP

    # (6) heal funding → ONLY now do economics matter; a great quote is finally APPROVED.
    res, _ = _entry(_risk(), opp=great)
    assert res.approved is True
    assert res.reason == KillReason.NONE


def test_ordering_hold_structural_beats_economic_compression():
    """On the hold side, a book that is BOTH oracle-stale AND carry-compressed must report the
    STRUCTURAL kill (oracle), never the economic compression — refusal-before-economics on hold too."""
    res, _ = _hold(_risk(oracle_staleness_seconds=999999), carry=D("0.001"))  # also compressed
    assert res.reason == KillReason.ORACLE_STALE


def test_ordering_hold_exit_capacity_beats_funding_and_compression():
    """A true exit-capacity collapse outranks both a funding streak and carry compression on hold."""
    st = KillState(entry_carry=D("0.05"), neg_funding_streak=P.funding_flip_streak_kill - 1)
    res, _ = _hold(_risk(funding_neg_frac_90d=D("0.6")), exit_liq=D("50000"), carry=D("0.001"),
                   opp=_opp(_quote(exit_liquidity_usd=D("50000")), size="100000"), state=st)
    assert res.reason == KillReason.EXIT_CAPACITY


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# UNDERLYING_DEPEG fail-closed (both paths) — explicit None / negative coverage
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_underlying_depeg_entry_fail_closed_on_malformed_peg():
    # fail-CLOSED: a malformed peg makes the engine clamp peg_haircut to its cap (0.10), so the
    # SIZE-INDEPENDENT structural haircut breaches max_structural_haircut and the size-proof TAIL_VETO
    # fires FIRST (a malformed peg IS a max-toxicity signal). Still REFUSED (the safety outcome is
    # preserved and strengthened) — the structural veto now precedes the UNDERLYING_DEPEG gate.
    res, _ = _entry(_risk(peg_distance="bad"))
    assert res.approved is False
    assert res.reason == KillReason.TAIL_VETO
    assert res.detail["max_structural_haircut"] == str(P.max_structural_haircut)


def test_underlying_depeg_hold_fail_closed_on_negative_peg():
    res, ns = _hold(_risk(peg_distance=D("-0.01")))
    assert res.approved is False
    assert res.reason == KillReason.UNDERLYING_DEPEG
    assert ns.killed is True


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# TAIL_VETO fail-closed — a malformed risk surface produces a MAX-haircut decomposition → refuse
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_tail_veto_fail_closed_on_fully_malformed_risk():
    # every haircut input malformed → each haircut clamps to its cap → total >> max → TAIL_VETO.
    bad = _risk(peg_distance="x", peg_vol_30d="x", funding_neg_frac_90d="x",
                oracle_staleness_seconds=None, nested_protocol_count=None, top_borrower_share="x")
    dec = ENG.fair(bad, UnderlyingKind.STABLE_SYNTH, 86400 * 60, True, D("100000"), D("2e6"), AS_OF,
                   trailing_yield=D("0.05"), boros_forward=D("0.048"))
    assert dec.peg_haircut == P.cap_peg
    assert dec.funding_flip_haircut == P.cap_funding
    assert dec.oracle_haircut == P.cap_oracle
    assert dec.protocol_haircut == P.cap_protocol
    assert dec.total_haircut > P.max_total_haircut
    res, _ = _entry(bad)
    assert res.approved is False
    assert res.reason == KillReason.TAIL_VETO
