"""Tests for the 6mo-M1 #11 tier-band consistency guard (scripts/check_tier_band_consistency.py).

Verifies: the LIVE landing tree is clean after #7 (all band strings single-sourced), the guard is
WARN-ONLY by default (exit 0) but STRICT under the env flag, and it correctly detects a re-hardcoded
band in a synthetic tree. Deterministic, no network.
"""
import importlib

import pytest

guard = importlib.import_module("scripts.check_tier_band_consistency")


def test_live_landing_tree_is_clean():
    """After #7, no .astro outside tier_bands.json carries a hardcoded band-shaped string."""
    hits = guard.scan()
    assert hits == [], f"unexpected hardcoded band strings: {hits}"


def test_default_is_warn_only_exit_0(monkeypatch, capsys):
    monkeypatch.delenv("STRICT_TIER_BANDS", raising=False)
    assert guard.main() == 0


def test_strict_flag_fails_on_drift(monkeypatch, tmp_path):
    # point the guard at a synthetic landing tree with a re-hardcoded band
    src = tmp_path / "landing" / "src"
    (src / "lib").mkdir(parents=True)
    (src / "lib" / "tier_bands.json").write_text("{}")
    (src / "pages").mkdir()
    (src / "pages" / "bad.astro").write_text("<div>Balanced 6–12% net APY · ≤10% drawdown</div>\n")
    monkeypatch.setattr(guard, "LANDING_SRC", src)
    monkeypatch.setattr(guard, "CANONICAL", src / "lib" / "tier_bands.json")
    hits = guard.scan()
    assert any("bad.astro" in h[0] for h in hits)
    monkeypatch.setenv("STRICT_TIER_BANDS", "1")
    assert guard.main() == 1              # strict → non-zero on drift
    monkeypatch.delenv("STRICT_TIER_BANDS")
    assert guard.main() == 0              # WARN-only → still 0


def test_nav_band_copy_detected(monkeypatch, tmp_path):
    src = tmp_path / "landing" / "src"
    (src / "lib").mkdir(parents=True)
    (src / "lib" / "tier_bands.json").write_text("{}")
    (src / "pages").mkdir()
    (src / "pages" / "nav.astro").write_text("desc: 'Capital protection first (6–8%)'\n")
    monkeypatch.setattr(guard, "LANDING_SRC", src)
    monkeypatch.setattr(guard, "CANONICAL", src / "lib" / "tier_bands.json")
    hits = guard.scan()
    assert any("nav.astro" in h[0] for h in hits)
