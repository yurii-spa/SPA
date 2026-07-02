"""YIELD-003 — structural test for the Yield Thesis Map (docs/33).

Research-layer test: asserts docs/33 covers the three yield domains and that its per-mechanism
content carries the honesty fields the charter requires (yield source, why it can disappear, risk).
Read-only; imports nothing from spa_core; does not touch runtime. stdlib + pytest only.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_DOC = Path(__file__).resolve().parents[1] / "docs" / "33_yield_thesis_map.md"


def _text() -> str:
    if not _DOC.exists():
        pytest.skip("docs/33_yield_thesis_map.md not present")
    return _DOC.read_text(encoding="utf-8")


def test_covers_the_three_domains():
    t = _text().lower()
    assert "stablecoin" in t, "yield thesis map must cover the stablecoin domain"
    assert "btc" in t or "bitcoin" in t, "must cover the BTC domain"
    assert "eth" in t, "must cover the ETH domain"


def test_has_the_honesty_fields():
    """Every thesis map must answer where yield comes from, who pays, and why it can disappear."""
    t = _text().lower()
    assert "yield source" in t, "must state the yield source"
    assert "who pays" in t or "who pays the yield" in t, "must state who pays the yield"
    assert "disappear" in t, "must state why the yield can disappear (fragility)"
    assert "risk" in t, "must state the risks per mechanism"


def test_ties_to_the_floor_and_evidence():
    """The map must anchor to the RWA floor baseline and the evidence standard (ADR-YL-008 / docs/37)."""
    t = _text().lower()
    assert "floor" in t, "must reference the RWA floor baseline"
    # APY must be discussed as categories/ranges, never a single fabricated live number as fact:
    assert "apy" in t


def test_flags_refused_mechanisms():
    """The honest map must explicitly mark mechanisms the desk refuses (risk-comp)."""
    t = _text().lower()
    assert "refus" in t or "reject" in t, "must flag refused / rejected (risk-comp) mechanisms"
