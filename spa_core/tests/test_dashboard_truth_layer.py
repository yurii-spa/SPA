#!/usr/bin/env python3
# LLM_FORBIDDEN
"""Regression guard for the dashboard TRUTH LAYER (Dashboard Arch. Phases 0-2).

These are static-source assertions over index.html (+ app.html). They lock in the
honesty fixes so the two original LIES cannot silently come back:

  LIE #1 — the hero rendered ~17/30 from paper_trading_status.days_running instead
           of the honest evidenced 5/30 (golive_status.real_track_days /
           /api/ssot/facts.real_track_days).
  LIE #2 — go-live rendered "—/29" because the code read the DEAD keys
           golive.criteria_met / golive.total_criteria; the file ships
           passed (27) / total (29).

Phase 1 = a first-class freshness banner sourced from /api/live/health.
Phase 2 = ONE canonical client (SPA_API) all headline fetches go through.

No live data / no network: pure source inspection (hermetic, fast).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INDEX = _REPO_ROOT / "index.html"
_APP = _REPO_ROOT / "landing" / "public" / "app.html"


@pytest.fixture(scope="module")
def index_src() -> str:
    return _INDEX.read_text(encoding="utf-8")


def _strip_comments(src: str) -> str:
    """Remove JS line/block comments so we test ACTIVE code, not explanations."""
    # block comments /* ... */
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    # line comments  // ...   (best-effort; fine for our key-name checks)
    src = re.sub(r"//[^\n]*", "", src)
    return src


# ── LIE #2: the dead go-live keys must not appear in ACTIVE code ──────────────
def test_dead_golive_keys_not_in_active_code(index_src: str) -> None:
    active = _strip_comments(index_src)
    assert "criteria_met" not in active, "dead key criteria_met still read in active code (LIE #2)"
    assert "total_criteria" not in active, "dead key total_criteria still read in active code (LIE #2)"


# ── LIE #2 fixed: go-live now reads the canonical passed/total ─────────────────
def test_golive_reads_passed_total(index_src: str) -> None:
    assert "golive_passed" in index_src, "go-live must read golive_passed (canonical)"
    assert "golive_total" in index_src, "go-live must read golive_total (canonical)"


# ── LIE #1 fixed: the hero track-days is the honest evidenced count ───────────
def test_hero_track_uses_real_track_days(index_src: str) -> None:
    assert "real_track_days" in index_src, "hero must use real_track_days (honest 5/30)"
    # The dominant hero (initSpaHero) must NOT compute the day count from a
    # wall-clock elapsed-days expression any more.
    assert "Math.floor((Date.now() - start.getTime()) / 86400000)" not in index_src, (
        "wall-clock day-count lie still present in initSpaHero"
    )


# ── Phase 2: the ONE canonical client exists and is the headline source ───────
def test_canonical_client_present(index_src: str) -> None:
    assert "const SPA_API = (function ()" in index_src, "canonical SPA_API client missing"
    assert "/api/ssot/facts" in index_src, "SPA_API must source the canonical /api/ssot/facts"
    assert "getFacts" in index_src and "getHealth" in index_src, "SPA_API getters missing"


def test_hero_routes_through_spa_api(index_src: str) -> None:
    # initSpaHero (dominant hero) and loadPerformance (perf hero) both call getFacts.
    assert index_src.count("SPA_API.getFacts()") >= 2, (
        "headline renderers must source numbers via SPA_API.getFacts()"
    )


# ── Phase 1: honest freshness banner sourced from /api/live/health ────────────
def test_freshness_banner_wired(index_src: str) -> None:
    assert "/api/live/health" in index_src, "freshness must consume /api/live/health"
    assert 'id="spa-freshness-banner"' in index_src, "freshness banner element missing"
    assert "renderFreshnessBanner" in index_src, "renderFreshnessBanner missing"
    # Offline must be LABELED, never silently rendered as live.
    assert "OFFLINE SNAPSHOT" in index_src, "offline snapshot must be explicitly labeled"
    assert 'id="spa-hero-asof"' in index_src, "offline as-of label element missing"


# ── No silent fabrication: the offline path carries an as-of stamp, not 'now' ──
def test_offline_snapshot_is_dated_not_now(index_src: str) -> None:
    assert "offline_snapshot" in index_src, "offline snapshot source flag missing"
    assert "as_of" in index_src, "offline snapshot must carry an as-of timestamp"


# ── app.html stays in lock-step with index.html (one editable source) ─────────
@pytest.mark.skipif(not _APP.exists(), reason="app.html not present")
def test_app_html_in_sync_with_index() -> None:
    assert _APP.read_bytes() == _INDEX.read_bytes(), (
        "landing/public/app.html diverged from index.html — re-sync "
        "(cp index.html landing/public/app.html). /app must show the SAME truth."
    )
