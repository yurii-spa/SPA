#!/usr/bin/env python3
# LLM_FORBIDDEN
"""Unit tests for scripts/check_owner_gate.py — the owner-gate auto-ship guard.

Tests the PURE detectors (no git / no network): tier_bands field-diff (Classes B/C/E),
free-text scan (A/B/C/D/E), the dynamic-read suppression of Class B, and the owner-
approval scope filter. The custodian-equivalence exemption + git-diff acquisition are
covered by the red-team integration checks in the build log, not here (they need data/
canon + git refs).
"""
import importlib.util
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_GUARD = _REPO / "scripts" / "check_owner_gate.py"
_spec = importlib.util.spec_from_file_location("check_owner_gate", _GUARD)
og = importlib.util.module_from_spec(_spec)
sys.modules["check_owner_gate"] = og
_spec.loader.exec_module(og)


# ── tier_bands.json field-diff (structured) ─────────────────────────────────
def _tb(**over):
    base = {
        "conservative": {"key": "conservative", "en": "Conservative", "ru": "Консервативный",
                         "alt_en": "Preserve", "alt_ru": "Preserve",
                         "band_en": "up to 6% net APY", "band_ru": "up to 6% net APY",
                         "nav_band_en": "x", "nav_band_ru": "x", "dd_short_en": "~1%",
                         "dd_short_ru": "~1%", "tail_en": "t", "tail_ru": "t",
                         "evidence_en": "L4 · live", "evidence_ru": "L4 · live"},
    }
    for tier, fields in over.items():
        base.setdefault(tier, {}).update(fields)
    return base


def test_tier_number_change_gates_B():
    old = _tb()
    new = _tb(conservative={"band_en": "up to 9% net APY"})
    vs = og._tier_bands_violations(old, new)
    assert any(v["klass"] == "B" for v in vs), vs


def test_tier_name_change_gates_C():
    old = _tb()
    new = _tb(conservative={"en": "Ultra Safe"})
    vs = og._tier_bands_violations(old, new)
    assert any(v["klass"] == "C" for v in vs), vs


def test_tier_evidence_removal_gates_E():
    old = _tb()
    new = _tb(conservative={"evidence_en": ""})
    vs = og._tier_bands_violations(old, new)
    assert any(v["klass"] == "E" for v in vs), vs


def test_tier_identical_is_clean():
    assert og._tier_bands_violations(_tb(), _tb()) == []


# ── free-text scan ──────────────────────────────────────────────────────────
def _added(path, text):
    return og._scan_free_text(path, [("+", 10, text)])


def _removed(path, text):
    return og._scan_free_text(path, [("-", 10, text)])


def test_solicitation_gates_A():
    vs = _added("landing/src/pages/x.astro", "Minimum investment $10,000 to start")
    assert any(v["klass"] == "A" for v in vs), vs


def test_solicitation_ru_gates_A():
    vs = _added("landing/src/pages/x.astro", "Вывод в течение 3 дней, без блокировки")
    assert any(v["klass"] == "A" for v in vs), vs


def test_baked_yield_literal_gates_B():
    vs = _added("landing/src/pages/x.astro", "<p>Earn up to 25% net APY today</p>")
    assert any(v["klass"] == "B" for v in vs), vs


def test_dynamic_yield_read_is_clean():
    # A dynamic read of the number is NOT a baked literal → no Class B.
    vs = _added("landing/src/pages/x.astro", "value={snap.paper_apy_pct.toFixed(2) + '%'}")
    assert not any(v["klass"] == "B" for v in vs), vs


def test_baked_literal_with_dynamic_token_same_line_gates_B():
    # FAIL-OPEN closer: a hardcoded "30% net APY" must gate even when an UNRELATED
    # dynamic token sits elsewhere on the same line. The old line-level suppressor let
    # this ship silently (any {snap.x} on the line killed the Class-B match).
    vs = _added("landing/src/pages/x.astro",
                "<p>Fixed 30% net APY — live now: {snap.paper_apy_pct}%</p>")
    assert any(v["klass"] == "B" for v in vs), vs


def test_dynamic_token_adjacent_to_percent_still_exempt():
    # The exemption still holds when the dynamic read is ADJACENT to the percent — the
    # span window keeps genuine dynamic reads out of Class B.
    vs = _added("landing/src/pages/x.astro", "APY up to {snap.max}% net")
    assert not any(v["klass"] == "B" for v in vs), vs


def test_spa_expansion_change_gates_C():
    vs = _added("landing/src/pages/x.astro", "SPA — Super Profit Alliance")
    assert any(v["klass"] == "C" for v in vs), vs


def test_canonical_spa_expansion_is_clean():
    vs = _added("landing/src/pages/x.astro", "SPA — Smart Passive Aggregator")
    assert not any(v["klass"] == "C" for v in vs), vs


def test_legal_path_any_change_gates_D():
    vs = _added("landing/src/components/Disclaimer.astro", "<p>anything at all</p>")
    assert any(v["klass"] == "D" for v in vs), vs


def test_honesty_token_removal_gates_E():
    vs = _removed("landing/src/pages/x.astro", "L2 · backtest · refused for live")
    assert any(v["klass"] == "E" for v in vs), vs


def test_ordinary_copy_is_clean():
    # Plain marketing prose (mentions research/paper but no gated tokens) → clean.
    vs = _added("landing/src/pages/x.astro",
                "<p>Paper research dashboard — one live hub for the track.</p>")
    assert vs == [], vs


def test_removing_marketing_prose_with_advice_phrase_is_clean():
    # The false-positive we fixed: removing prose that merely says 'not investment
    # advice' must NOT gate (the real Disclaimer is path-protected).
    vs = _removed("landing/src/pages/dashboard.astro",
                  "every ~15s and honestly flags live / offline. All paper, not investment advice.")
    assert vs == [], vs


# ── owner-approval scope filter (pure logic via check_owner_gate integration) ─
def test_approved_scope_parses_trailer_absent():
    assert og._approved_scope(None, _REPO) is None
    assert og._approved_scope("no trailer here", _REPO) is None


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-q"]))
