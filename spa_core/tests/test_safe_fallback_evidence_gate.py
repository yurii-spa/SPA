#!/usr/bin/env python3
"""ADR-108 — the emergency book drops a protocol only against EVIDENCE.

Owner decision of 2026-08-21 09:34Z (card
``own-2026-08-18-avariinaya-kniga-idet-mimo-geitov-svezhesti``, **вариант C**).

The shape of the decision matters more than the code
----------------------------------------------------
The emergency book (``_SAFE_FALLBACK_POSITIONS``) is a hand-approved static
allocation used when the tuner cannot produce a compliant one — i.e. exactly
when the data is already bad. A measurement showed it asked only ONE of three
gates: the adapter-class gate (advisory / RESEARCH_ONLY / GSM) was live, but
the observed-APY gate and the $5M live-pool floor were never consulted.

Closing that head-on was priced, and the price was the whole point: run the
book through the live-TVL floor as it stands and it deploys **$0 instead of
$75_852** — not because the protocols are bad, but because not one of the 34
adapters currently reports a live pool size at all. The strict reading turns
the emergency branch into "permanently all cash", so the emergency has no
answer. The owner chose C: drop a protocol when a live observation EXISTS and
contradicts the rule; keep it when there is no observation, because "no data"
is the situation this book was written for.

So the tests below pin **three** outcomes, and the middle one is the decision:

    observed & below floor  → dropped, share to cash
    not observed at all     → kept          ← this is variant C, not B
    observed & above floor  → kept

A test suite that only checked "bad protocol gets dropped" would pass just as
happily on variant B, which the owner declined.
"""
from __future__ import annotations

import pytest

from spa_core.tuner.portfolio_rebalancer import (
    _SAFE_FALLBACK_POSITIONS,
    _build_safe_fallback_positions,
)

CAP = 100_000.0
_ALL_ALLOWED = lambda _p: (True, "ok")          # noqa: E731 — class gate stub
_NEVER_OBSERVED = lambda _p, _d=None: None      # noqa: E731
_ALL_ABOVE_FLOOR = lambda _p, _d=None: True     # noqa: E731


def _build(**kw):
    kw.setdefault("class_gate", _ALL_ALLOWED)
    kw.setdefault("tvl_verdict_fn", _NEVER_OBSERVED)
    return _build_safe_fallback_positions(CAP, **kw)


def test_unobserved_protocols_are_kept():
    """Variant C, and the reason B was declined: silence is not evidence."""
    positions, cash = _build()

    assert set(positions) == set(_SAFE_FALLBACK_POSITIONS), (
        "no protocol was contradicted by an observation, yet the emergency book "
        "lost members — that is variant B (measured cost $75_852 → $0), which "
        "the owner explicitly did not choose"
    )
    assert sum(positions.values()) > 0.8 * CAP


def test_a_protocol_observed_below_the_floor_is_dropped():
    """The hole ADR-108 closes: a pool we KNOW is too small still got funded."""
    target = "maple"

    def _verdict(proto, _d=None):
        return False if proto == target else None

    positions, cash = _build(tvl_verdict_fn=_verdict)

    assert target not in positions, (
        f"{target} was observed below the $5M floor and the emergency book "
        f"funded it anyway — this is the branch that runs when data is already "
        f"bad, so the gates matter here most"
    )
    assert set(positions) == set(_SAFE_FALLBACK_POSITIONS) - {target}


def test_the_dropped_share_goes_to_cash_not_to_the_neighbours():
    """The emergency book must never concentrate harder because a peer failed."""
    target = "maple"
    kept_before, _ = _build()
    kept_after, cash_after = _build(
        tvl_verdict_fn=lambda p, _d=None: False if p == target else None
    )

    for proto, usd in kept_after.items():
        assert usd == pytest.approx(kept_before[proto]), (
            f"{proto} grew from {kept_before[proto]} to {usd} because a peer was "
            f"blocked — a degraded cycle must not answer by concentrating"
        )
    assert cash_after > _build()[1], "the blocked share did not land in cash"


def test_an_observation_above_the_floor_keeps_the_protocol():
    """A measured, healthy pool is not collateral damage."""
    positions, _ = _build(tvl_verdict_fn=_ALL_ABOVE_FLOOR)
    assert set(positions) == set(_SAFE_FALLBACK_POSITIONS)


def test_an_unreadable_observation_is_not_treated_as_evidence():
    """A reader that raises must not quietly deliver variant B.

    If a read error blocked the protocol, one unreadable file would empty the
    whole emergency book — which is precisely the outcome (deploy $0) the owner
    was shown and declined. "We could not look" is not "it fails".
    """
    def _boom(_proto, _d=None):
        raise OSError("adapter_status.json unreadable")

    positions, _ = _build(tvl_verdict_fn=_boom)
    assert set(positions) == set(_SAFE_FALLBACK_POSITIONS), (
        "an unreadable observation emptied the emergency book — that is "
        "variant B by accident"
    )


def test_the_class_gate_still_fails_closed():
    """ADR-108 must not have loosened the gate that carries invariants 9/10.

    The asymmetry is deliberate: an unread live-TVL observation keeps a
    protocol, but an unverifiable adapter CLASS still empties the book. Sky/sUSDS
    at 0 % until GSM is confirmed is an invariant, not an observation.
    """
    def _boom(_proto):
        raise RuntimeError("allocator import failed")

    positions, cash = _build(class_gate=_boom)
    assert positions == {}, (
        "the class gate stopped failing CLOSED — invariants 9/10 (advisory / "
        "RESEARCH_ONLY / GSM) must never be funded by an unverified path"
    )
    assert cash == CAP


def test_everything_contradicted_means_all_cash_never_a_partial_lie():
    """If every member is contradicted, hold cash — do not improvise a book."""
    positions, cash = _build(tvl_verdict_fn=lambda _p, _d=None: False)
    assert positions == {}
    assert cash == CAP
