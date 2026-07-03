"""Direct unit tests for apply_soft_derisk_gate (COV-1, audit-2 follow-up).

The SOFT-derisk cap is exercised end-to-end by test_cycle_derisk_e2e, but the pure gate function
had no DIRECT unit test of its boundary. These are fast, precise regression guards on the exact
contract (ADR-034/048): in the soft band [5%,10%) the cycle may HOLD or REDUCE but never open a
NEW position nor INCREASE a held one. Deterministic, no I/O.
"""
from spa_core.paper_trading.cycle_gates import apply_soft_derisk_gate


def _apply(target, held, active=True):
    notes = []
    out = apply_soft_derisk_gate(dict(target), current_positions=dict(held),
                                 derisk_active=active, notes=notes)
    return out, notes


def test_noop_when_not_active():
    # inactive gate is a pure no-op — even brand-new protocols pass through untouched
    target = {"aave_v3": 5000.0, "brand_new": 9000.0}
    out, notes = _apply(target, {"aave_v3": 5000.0}, active=False)
    assert out == {"aave_v3": 5000.0, "brand_new": 9000.0}
    assert notes == []


def test_new_protocol_forced_to_zero():
    # not currently held → NO new position under de-risk
    out, notes = _apply({"brand_new": 12000.0}, {"aave_v3": 8000.0})
    assert out["brand_new"] == 0.0
    assert any("blocked_new=['brand_new']" in n for n in notes)


def test_held_increase_capped_to_held():
    # held $10k, allocator wants $23,250 → clamped to $10k (NO increase)
    out, notes = _apply({"aave_v3": 23250.0}, {"aave_v3": 10000.0})
    assert out["aave_v3"] == 10000.0
    assert any("capped_increase=['aave_v3']" in n for n in notes)


def test_reduction_left_intact():
    # held $10k, allocator wants $4k (a REDUCTION) → allowed, left at $4k
    out, _ = _apply({"aave_v3": 4000.0}, {"aave_v3": 10000.0})
    assert out["aave_v3"] == 4000.0


def test_unchanged_hold_left_intact():
    out, _ = _apply({"aave_v3": 10000.0}, {"aave_v3": 10000.0})
    assert out["aave_v3"] == 10000.0


def test_malformed_target_value_does_not_crash_and_zeroes():
    # a non-numeric target for a NON-held protocol → coerced to 0.0 (want=0 -> not blocked_new)
    out, notes = _apply({"weird": "not-a-number"}, {"aave_v3": 5000.0})
    assert out["weird"] == 0.0


def test_bool_position_is_not_treated_as_held():
    # a bool in current_positions must NOT count as a held size (isinstance-bool guard)
    out, _ = _apply({"aave_v3": 6000.0}, {"aave_v3": True})
    assert out["aave_v3"] == 0.0  # treated as new -> blocked


def test_mixed_book_hold_reduce_block_and_cap():
    target = {"aave_v3": 20000.0, "compound_v3": 3000.0, "new_a": 5000.0}
    held = {"aave_v3": 12000.0, "compound_v3": 8000.0}
    out, _ = _apply(target, held)
    assert out["aave_v3"] == 12000.0     # increase capped
    assert out["compound_v3"] == 3000.0  # reduction intact
    assert out["new_a"] == 0.0           # new blocked
    # never GROWS the book beyond what was held (no-increase guarantee)
    assert sum(out.values()) <= sum(held.values())
