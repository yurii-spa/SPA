"""
spa_core/tests/test_alloc002_metamorphic.py — METAMORPHIC / INVARIANT property
tests for ``_compliant_target`` (risk_gate.py), the ALLOC-002 collapse-to-≤8 +
capital-redistribution component the daily cycle runs on the MONEY PATH.

WHY THIS FILE EXISTS (the D3-T1 mandate)
----------------------------------------
``_compliant_target`` is the component that NEARLY broke a downstream guarantee.
Day-1 (``test_cycle_derisk_e2e.py``) found that when it collapses an
over-diversified book to ≤8 protocols it REDISTRIBUTES the freed capital across a
fresh policy-compliant survivor book — RE-GROWING protocols (e.g. ``aave_v3``
$12,000 held → $23,250) and RE-OPENING un-held ones. That re-grow silently UNDID
the SOFT de-risk "no-new / no-increase" guarantee. The bug lives ONE LEVEL UP:
``_compliant_target`` itself makes NO held-size promise (by design it builds a
fresh compliant book); the fix is the caller re-applying the soft gate AFTER it.

So this suite does NOT (falsely) assert that ``_compliant_target`` respects held
sizes — that is not its contract and asserting it would mis-pin the component.
Instead it pins, with ~200 seeded-random cases per property, the invariants the
collapse+redistribution MUST hold so the re-grow can NEVER violate a *policy*
guarantee (cap, conservation, count) — the guarantees the downstream soft gate
and the persisted-write ALLOC-002 post-check rely on.

VERIFIED CONTRACT OF ``_compliant_target`` (read from risk_gate.py source)
--------------------------------------------------------------------------
Signature: ``_compliant_target(target_usd, capital_usd, ddir, write) -> (book, collapsed)``
  1. If the raw target PASSES policy_enforcer.validate_positions → returned
     UNCHANGED, ``collapsed=False`` (the idempotence / compliant-book no-op).
  2. If it FAILS but NOT on the ``max_protocols`` rule (e.g. a per-protocol or
     t1_min breach on an already-small book) → returned UNCHANGED,
     ``collapsed=False``. The helper ONLY intervenes on the count explosion that
     flaps the rebalance diff; other violations are left to the gate + post-check.
  3. If it FAILS on ``max_protocols`` (>8 with a count breach) → it derives a
     DETERMINISTIC compliant book: the rebalancer (no adapter snapshot in a
     hermetic sandbox → returns False) then the hard-coded safe-fallback
     portfolio, validated against the enforcer before adoption. Returns
     ``(safe_book, True)``.
  4. Fail-OPEN on any internal error → original target unchanged (the persisted
     ALLOC-002 post-check still guards the write).

STYLE (mirrors test_allocator_properties.py)
--------------------------------------------
NO 'hypothesis' (stdlib-only runtime contract). A single seeded
``random.Random(SEED)`` generates deterministic inputs; each property loops
N_CASES times. Bit-for-bit reproducible. Fail-CLOSED. Every cycle runs against a
per-test ``tempfile.TemporaryDirectory`` ddir — the live repo ``data/`` is NEVER
read or written (write=False throughout, and a no-adapter sandbox forces the
deterministic safe-fallback collapse path).

Pure stdlib + pytest. Deterministic (seed 42). LLM-forbidden.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import logging
import math
import random
import tempfile
from pathlib import Path

import pytest

from spa_core.paper_trading.risk_gate import _compliant_target
from spa_core.risk.policy_enforcer import RULES, _normalize_tier, validate_positions

N_CASES = 200
SEED = 42
CAP = 100_000.0
_TOL = 1e-6

MAX_PROTOCOLS = int(RULES["max_protocols"])          # 8
PER_PROTO_CAP = float(RULES["per_protocol_max_pct"])  # 25.0 (% of capital)
T2_MAX = float(RULES["t2_max_pct"])                   # 50.0
T3_MAX = float(RULES["t3_max_pct"])                   # 15.0
CASH_MIN = float(RULES["cash_min_pct"])               # 5.0

# A name pool with a deliberate mix: known T1 (anchors), known T3, and generic
# names that classify to the default T2 — so the generator naturally produces
# tier-diverse books the way a real allocator output does.
_T1_NAMES = ["aave_v3", "compound_v3", "spark_susds", "morpho_steakhouse",
             "aave_arbitrum", "aave_v3_optimism", "aave_v3_polygon", "aave_v3_base"]
_T3_NAMES = ["susde", "extra_finance_base", "moonwell_base", "stusd"]
_T2_NAMES = [f"t2_proto_{i}" for i in range(10)]
_ALL_NAMES = _T1_NAMES + _T3_NAMES + _T2_NAMES


def _rng() -> random.Random:
    return random.Random(SEED)


# ── deterministic harness: run _compliant_target in a fresh empty sandbox ─────
# The empty ddir has NO adapter_orchestrator_status.json, so rebalance_portfolio
# returns False and _compliant_target deterministically takes the safe-fallback
# collapse branch on a max_protocols breach. write=False → nothing is persisted.
def _run(target: dict, *, capital: float = CAP) -> tuple[dict, bool]:
    with tempfile.TemporaryDirectory() as d:
        return _compliant_target(dict(target), capital, Path(d), write=False)


def _tier_of(proto: str) -> str:
    return _normalize_tier(proto)


def _random_book(rng: random.Random, *, allow_degenerate: bool) -> dict:
    """A random allocator-style target book {protocol: usd}.

    Spans the full surface the mandate calls out:
      * varied protocol counts INCLUDING > 8 (forces the collapse branch);
      * varied weights;
      * degenerate shapes: all-equal, single-dominant, all-sub-cap, empty.
    """
    shape = rng.random()
    if allow_degenerate and shape < 0.10:
        return {}  # empty
    if allow_degenerate and shape < 0.20:
        # single-dominant: one big position
        return {rng.choice(_ALL_NAMES): rng.uniform(20_000.0, 60_000.0)}

    # count: bias toward > 8 so the collapse path is exercised often, but include
    # small books that must pass through unchanged.
    n = rng.randint(1, min(len(_ALL_NAMES), 14))
    names = rng.sample(_ALL_NAMES, n)

    if allow_degenerate and shape < 0.40:
        # all-equal book (the Day-1 over-diversified flavour)
        amt = rng.uniform(3_000.0, 9_000.0)
        return {p: amt for p in names}
    if allow_degenerate and shape < 0.55:
        # all sub-cap tiny amounts (each well under the 25% per-protocol cap)
        return {p: rng.uniform(500.0, 4_000.0) for p in names}

    # general: random per-protocol amounts that keep the book roughly deployable.
    # Headroom spans 0.5..1.05× capital so the helper's downstream guards are
    # exercised both under-deployed and slightly over-deployed.
    book: dict = {}
    remaining = CAP * rng.uniform(0.5, 1.05)
    for p in names:
        amt = rng.uniform(1_000.0, min(24_000.0, max(1_000.0, remaining)))
        book[p] = round(amt, 2)
        remaining = max(0.0, remaining - amt)
    return book


# ═══════════════════════════════════════════════════════════════════════════════
# INVARIANT 1 — CAPITAL CONSERVATION: Σ(target) ≤ capital, cash ≥ 0.
#   The collapse+redistribution must never CREATE capital.
# ═══════════════════════════════════════════════════════════════════════════════
def test_inv_capital_conservation():
    rng = _rng()
    logging.disable(logging.CRITICAL)
    try:
        for _ in range(N_CASES):
            book = _random_book(rng, allow_degenerate=True)
            out, _ = _run(book)
            total = sum(out.values())
            assert total <= CAP + 1e-4, f"created capital: Σ={total} > {CAP}\nbook={book}"
            assert (CAP - total) >= -1e-4, f"negative cash: {CAP - total}\nout={out}"
    finally:
        logging.disable(logging.NOTSET)


# ═══════════════════════════════════════════════════════════════════════════════
# INVARIANT 2 — ≤8 PROTOCOLS (the ALLOC-002 core).
#   A book that breached max_protocols must come back collapsed to ≤8. A book
#   that did NOT breach the count is allowed through (≤8 already, or returned
#   unchanged because the breach was a non-count rule).
# ═══════════════════════════════════════════════════════════════════════════════
def test_inv_at_most_8_protocols_when_collapsed():
    rng = _rng()
    logging.disable(logging.CRITICAL)
    try:
        collapses_seen = 0
        for _ in range(N_CASES):
            book = _random_book(rng, allow_degenerate=True)
            out, collapsed = _run(book)
            if collapsed:
                collapses_seen += 1
                assert len(out) <= MAX_PROTOCOLS, (
                    f"collapsed book still > {MAX_PROTOCOLS} protocols: "
                    f"n={len(out)}\nout={out}"
                )
            else:
                # pass-through: identical to the input (no fabricated change)
                assert out == {str(k): float(v) for k, v in book.items()} or out == book, (
                    f"non-collapse path mutated the book\nin={book}\nout={out}"
                )
        # proof the collapse branch (the risky redistribution) actually ran
        assert collapses_seen > 0, "collapse path never exercised — generator too tame"
    finally:
        logging.disable(logging.NOTSET)


# ═══════════════════════════════════════════════════════════════════════════════
# INVARIANT 3 — CONCENTRATION: no protocol over its tier cap post-collapse.
#   The collapsed book must pass the SAME policy_enforcer that flagged the input,
#   so by construction every per-protocol / tier-total cap holds. We assert it
#   directly on the output (per-protocol ≤25%, T2-total ≤50%, T3-total ≤15%).
# ═══════════════════════════════════════════════════════════════════════════════
def test_inv_no_protocol_over_tier_cap_post_collapse():
    rng = _rng()
    logging.disable(logging.CRITICAL)
    try:
        for _ in range(N_CASES):
            book = _random_book(rng, allow_degenerate=True)
            out, collapsed = _run(book)
            if not collapsed:
                continue  # pass-through books are validated elsewhere (idempotence)
            # per-protocol cap
            for p, usd in out.items():
                pct = usd / CAP * 100.0
                assert pct <= PER_PROTO_CAP + 1e-6, (
                    f"per-protocol breach post-collapse: {p}={pct:.2f}% > {PER_PROTO_CAP}%"
                )
            # tier-total caps
            t2 = sum(u for p, u in out.items() if _tier_of(p) == "T2") / CAP * 100.0
            t3 = sum(u for p, u in out.items() if _tier_of(p) == "T3") / CAP * 100.0
            assert t2 <= T2_MAX + 1e-6, f"T2-total breach post-collapse: {t2:.2f}% > {T2_MAX}%"
            assert t3 <= T3_MAX + 1e-6, f"T3-total breach post-collapse: {t3:.2f}% > {T3_MAX}%"
            # the collapsed book is, by contract, a full enforcer PASS
            chk = validate_positions(
                positions=out, capital_usd=CAP, cash_usd=CAP - sum(out.values())
            )
            assert chk.passed, (
                "collapsed book FAILS the enforcer it was built to satisfy: "
                f"{[v.rule for v in chk.violations]}\nout={out}"
            )
    finally:
        logging.disable(logging.NOTSET)


# ═══════════════════════════════════════════════════════════════════════════════
# INVARIANT 4 — IDEMPOTENCE: _compliant_target on an already-compliant book is a
#   no-op; running it TWICE == running it ONCE (the property the persisted-write
#   ALLOC-002 post-check relies on to avoid phantom churn).
# ═══════════════════════════════════════════════════════════════════════════════
def test_inv_idempotence_twice_equals_once():
    rng = _rng()
    logging.disable(logging.CRITICAL)
    try:
        idem_pairs = 0
        for _ in range(N_CASES):
            book = _random_book(rng, allow_degenerate=True)
            once, _ = _run(book)
            twice, collapsed2 = _run(once)
            assert twice == once, (
                f"NOT idempotent: f(f(x)) != f(x)\nonce={once}\ntwice={twice}"
            )
            # a book that is already the helper's own output must NOT collapse again
            assert collapsed2 is False, (
                f"already-compliant output collapsed on the 2nd pass\nonce={once}"
            )
            idem_pairs += 1
        assert idem_pairs == N_CASES
    finally:
        logging.disable(logging.NOTSET)


def test_inv_compliant_book_is_passthrough():
    """A KNOWN compliant book is returned byte-for-byte unchanged, collapsed=False
    — the exact no-op the idempotence property depends on (pinned explicitly)."""
    logging.disable(logging.CRITICAL)
    try:
        compliant = {
            "aave_v3": 22_000.0, "compound_v3": 15_000.0, "spark_susds": 13_000.0,
            "morpho_steakhouse": 10_000.0, "maple": 15_000.0, "euler_v2": 10_000.0,
            "yearn_v3": 3_000.0,
        }
        # precondition: this book really does pass the enforcer
        pre = validate_positions(
            positions=compliant, capital_usd=CAP, cash_usd=CAP - sum(compliant.values())
        )
        assert pre.passed, f"fixture not actually compliant: {[v.rule for v in pre.violations]}"
        out, collapsed = _run(compliant)
        assert collapsed is False
        assert out == compliant
    finally:
        logging.disable(logging.NOTSET)


# ═══════════════════════════════════════════════════════════════════════════════
# INVARIANT 5 — DETERMINISM: same input → same output (no hidden RNG/clock leak).
#   The redistribution uses random.Random(42) internally; identical inputs across
#   independent sandboxes must yield byte-identical books.
# ═══════════════════════════════════════════════════════════════════════════════
def test_inv_determinism_same_input_same_output():
    rng = _rng()
    logging.disable(logging.CRITICAL)
    try:
        for _ in range(N_CASES):
            book = _random_book(rng, allow_degenerate=True)
            a, ca = _run(book)
            b, cb = _run(book)
            assert a == b, f"non-deterministic output\na={a}\nb={b}\nbook={book}"
            assert ca == cb, "non-deterministic collapsed flag"
    finally:
        logging.disable(logging.NOTSET)


# ═══════════════════════════════════════════════════════════════════════════════
# INVARIANT 6 — NO NEGATIVE / NaN / Inf weights OUT (fail-closed on degenerate in).
# ═══════════════════════════════════════════════════════════════════════════════
def test_inv_no_negative_or_nonfinite_weights_out():
    rng = _rng()
    logging.disable(logging.CRITICAL)
    try:
        for _ in range(N_CASES):
            book = _random_book(rng, allow_degenerate=True)
            out, _ = _run(book)
            for p, w in out.items():
                assert isinstance(w, (int, float)) and not isinstance(w, bool)
                assert math.isfinite(w), f"non-finite weight out: {p}={w}"
                assert w >= -_TOL, f"negative weight out: {p}={w}"
    finally:
        logging.disable(logging.NOTSET)


def test_degenerate_nonfinite_input_fail_closed_no_crash():
    """NaN/Inf/negative AMOUNTS in the raw target must not crash _compliant_target
    nor leak a non-finite value into the output. The helper is fail-OPEN on
    internal error (returns the original target), so a degenerate input may pass
    through unchanged — but it must NEVER raise and never FABRICATE a non-finite
    weight that wasn't already present (we assert the collapsed branch, when it
    fires, is clean)."""
    logging.disable(logging.CRITICAL)
    try:
        cases = [
            {},
            {"aave_v3": float("nan")},
            {"aave_v3": float("inf"), "compound_v3": 10_000.0},
            {"aave_v3": -5_000.0, "compound_v3": 10_000.0},
            # >8 protocols WITH one non-finite amount mixed in
            {**{f"t2_proto_{i}": 6_000.0 for i in range(9)}, "aave_v3": float("nan")},
        ]
        for book in cases:
            out, collapsed = _run(book)  # MUST NOT RAISE
            assert isinstance(out, dict)
            if collapsed:
                # a real collapse always yields a finite, enforcer-passing book
                for p, w in out.items():
                    assert math.isfinite(w) and w >= -_TOL, f"dirty collapse: {p}={w}"
                chk = validate_positions(
                    positions=out, capital_usd=CAP, cash_usd=CAP - sum(out.values())
                )
                assert chk.passed
    finally:
        logging.disable(logging.NOTSET)


# ═══════════════════════════════════════════════════════════════════════════════
# METAMORPHIC 1 — ZEROING / REMOVING one input protocol never pushes ANOTHER
#   survivor ABOVE its per-protocol cap. This is the metamorphic shape of the
#   Day-1 re-grow: the bug was that collapse REDISTRIBUTION grew a protocol; here
#   we pin the guarantee the redistribution MUST still honour — no survivor may
#   ever cross the 25% per-protocol concentration cap as a RESULT of another
#   protocol's capital being freed.
# ═══════════════════════════════════════════════════════════════════════════════
def test_metamorphic_zeroing_input_never_breaches_a_cap():
    rng = _rng()
    logging.disable(logging.CRITICAL)
    try:
        exercised = 0
        for _ in range(N_CASES):
            # build an OVER-diversified book (>8) so both runs hit the collapse
            n = rng.randint(9, min(len(_ALL_NAMES), 14))
            names = rng.sample(_ALL_NAMES, n)
            amt = rng.uniform(4_000.0, 8_000.0)
            book = {p: amt for p in names}

            out_base, col_base = _run(book)
            # remove (zero) one input protocol
            drop = rng.choice(names)
            reduced = {p: v for p, v in book.items() if p != drop}
            out_red, col_red = _run(reduced)

            for src, tag in ((out_base, "base"), (out_red, "reduced")):
                for p, usd in src.items():
                    pct = usd / CAP * 100.0
                    assert pct <= PER_PROTO_CAP + 1e-6, (
                        f"[{tag}] redistribution pushed {p} to {pct:.2f}% "
                        f"> per-protocol cap {PER_PROTO_CAP}% (Day-1 re-grow class)"
                    )
            if col_base or col_red:
                exercised += 1
        assert exercised > 0, "removal/zeroing metamorphic never hit the collapse path"
    finally:
        logging.disable(logging.NOTSET)


# ═══════════════════════════════════════════════════════════════════════════════
# METAMORPHIC 2 — ADDING a SUB-FLOOR (tiny) protocol to an already-compliant ≤8
#   book that STAYS ≤8 is a NO-OP: the helper only intervenes on a max_protocols
#   breach, so a dust position that does not push the count over 8 leaves the book
#   byte-for-byte unchanged (collapsed=False). (If it pushes count past 8 the
#   collapse legitimately fires — that case is covered by the count invariant.)
# ═══════════════════════════════════════════════════════════════════════════════
def test_metamorphic_add_subfloor_within_count_is_noop():
    rng = _rng()
    logging.disable(logging.CRITICAL)
    try:
        checked = 0
        # a fixed compliant 7-protocol base (room for one more under the count cap)
        base = {
            "aave_v3": 22_000.0, "compound_v3": 15_000.0, "spark_susds": 13_000.0,
            "morpho_steakhouse": 10_000.0, "maple": 15_000.0, "euler_v2": 10_000.0,
            "yearn_v3": 3_000.0,
        }
        out_base, col_base = _run(base)
        assert col_base is False and out_base == base
        for _ in range(N_CASES):
            spare = rng.choice([n for n in _T2_NAMES if n not in base])
            # a DUST amount → adding an 8th protocol keeps count ≤ 8
            dust = rng.uniform(1.0, 50.0)
            with_dust = {**base, spare: round(dust, 2)}
            out, collapsed = _run(with_dust)
            assert collapsed is False, (
                f"adding dust (8th protocol, count ≤8) wrongly triggered collapse\n"
                f"with_dust={with_dust}"
            )
            assert out == with_dust, "non-collapse path mutated the book"
            checked += 1
        assert checked == N_CASES
    finally:
        logging.disable(logging.NOTSET)


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-p", "no:randomly", "-q"]))
