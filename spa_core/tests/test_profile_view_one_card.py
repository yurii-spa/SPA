"""PRODUCT-UX-01 — the product surfaces' profile view is built ON TOP of the canonical card model
(landing/src/lib/package_card.js, ADR-537 «one card»), not beside it.

Invariants (independent review of the candidate, 2026-10-07):
  1. profile_view.js takes target / tail / maturity / result from package_card.js — it never reads the
     target band or the tail strings from tier_bands.json itself (names only);
  2. a research target is shown in the result block ONLY for a mature profile; for an immature profile
     target and tail sit together in the collapsed research detail («no target without its tail»);
  3. a tail is labelled «earlier version, not this strategy» at the number;
  4. Conservative renders no backtest tail (the canonical card returns tail = None for it).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "landing/src/lib"
UX = ROOT / "landing/src/components/ux"


def _src(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_profile_view_is_built_on_the_canonical_card():
    pv = _src(LIB / "profile_view.js")
    assert re.search(r"import\s*\{[^}]*cardModels[^}]*\}\s*from\s*'\./package_card\.js'", pv)
    # never the target band / tail strings straight from tier_bands (names are allowed)
    for key in ("band_en", "band_ru", "tail_en", "tail_ru", "nav_band_en", "dd_short_en"):
        assert f".{key}" not in pv and f"['{key}']" not in pv, f"profile_view reads tier_bands.{key} directly"


def test_canonical_card_has_no_tail_for_conservative():
    pc = _src(LIB / "package_card.js")
    assert re.search(r"export function researchTail\(key, ru\) \{\s*if \(key === 'conservative'\) return null;", pc)


def test_target_only_with_maturity_and_tail_only_labelled_as_earlier_version():
    ms = _src(UX / "MetricStack.astro")
    measured, immature = ms.split(") : (", 1)
    # mature branch: the target is guarded by target_shown and no tail is rendered there
    assert "v.target_shown && v.target_en" in measured
    assert "tail_en" not in measured
    # immature branch: tail only next to the «earlier version, not this strategy» label, inside research detail
    assert "earlier version, not this strategy" in immature and "<details" in immature
    assert immature.index("<details") < immature.index("{v.tail_en}")
    pc = _src(UX / "ProfileCompare.astro")
    assert "v.tail" not in pc, "the comparison cards never show a tail (it belongs to the detail, with its label)"
    assert "v.target_shown && v.target_en" in pc


def test_profile_view_shows_the_target_only_for_mature_profiles():
    pv = _src(LIB / "profile_view.js")
    assert "target_shown: mat.state === 'MATURE'" in pv
