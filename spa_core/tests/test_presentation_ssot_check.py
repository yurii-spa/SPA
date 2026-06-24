#!/usr/bin/env python3
# LLM_FORBIDDEN
"""Hermetic tests for the presentation-vs-SSOT guard (scripts/check_presentation_ssot.py).

All tests are self-contained: they write tiny presentation files into a tmp dir
and pin canon by monkeypatching key_facts (so they don't depend on live data/).
This mirrors the Law-3 contract: the site may not show a number contradicting
canon, but dynamic placeholders that fetch live values are fine.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

# Import the script module by path (it lives in scripts/, not a package).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "check_presentation_ssot.py"
_spec = importlib.util.spec_from_file_location("check_presentation_ssot", _SCRIPT)
guard = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(guard)


# Canonical facts used across tests (pin: golive 27/29, day 15, apy 3.6%).
_CANON = {
    "ssot_version": "v1.0",
    "golive_total": 29,
    "golive_passed": 27,
    "track_days": 15,
    "apy_today_pct": 3.6,
    "paper_start_date": "2026-06-10",
}


@pytest.fixture(autouse=True)
def _pin_canon(monkeypatch):
    """Pin canon for every test so results don't depend on live data/."""
    monkeypatch.setattr(guard, "key_facts", lambda data_dir=None: dict(_CANON))


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def _run(tmp_path: Path, files):
    return guard.check_presentation(repo_root=tmp_path, files=files)


# ── golive total divergence ────────────────────────────────────────────────


def test_flags_wrong_criteria_total(tmp_path):
    f = _write(
        tmp_path,
        "bad.astro",
        '<p>GoLiveChecker: 26 criteria before real capital</p>\n',
    )
    rep = _run(tmp_path, [f])
    assert rep["ok"] is False
    assert rep["divergence_count"] == 1
    d = rep["divergences"][0]
    assert d["kind"] == "golive_total"
    assert d["claimed"] == 26
    assert d["canonical"] == 29
    assert d["line"] == 1


def test_correct_total_not_flagged(tmp_path):
    f = _write(
        tmp_path,
        "ok.astro",
        '<p>GoLiveChecker: 29 criteria before real capital</p>\n',
    )
    rep = _run(tmp_path, [f])
    assert rep["ok"] is True
    assert rep["divergence_count"] == 0


def test_criteria_total_requires_golive_context(tmp_path):
    # A JS comment about array slicing ("first 4 criteria") must NOT be flagged.
    f = _write(
        tmp_path,
        "code.html",
        "    // Mini breakdown — first 4 criteria\n"
        "    const items = checks.slice(0, 4);\n",
    )
    rep = _run(tmp_path, [f])
    assert rep["ok"] is True


def test_flags_wrong_pass_count_denominator(tmp_path):
    f = _write(tmp_path, "x.astro", "<span>16 / 26 criteria met</span>\n")
    rep = _run(tmp_path, [f])
    kinds = {d["kind"] for d in rep["divergences"]}
    # Denominator 26 != 29 → flagged as golive_total drift.
    assert "golive_total" in kinds
    assert any(d["claimed"] == 26 for d in rep["divergences"])


# ── golive passed divergence ───────────────────────────────────────────────


def test_flags_wrong_pass_numerator(tmp_path):
    f = _write(tmp_path, "p.astro", "<p>25/29 criteria currently passing</p>\n")
    rep = _run(tmp_path, [f])
    assert rep["ok"] is False
    d = rep["divergences"][0]
    assert d["kind"] == "golive_passed"
    assert d["claimed"] == 25
    assert d["canonical"] == 27


def test_correct_pass_count_not_flagged(tmp_path):
    f = _write(tmp_path, "p.astro", "<p>27/29 criteria currently passing</p>\n")
    rep = _run(tmp_path, [f])
    assert rep["ok"] is True


def test_bare_fraction_not_flagged(tmp_path):
    # "20/30" with no criteria/pass suffix is a generic fraction → ignore.
    f = _write(tmp_path, "p.astro", "<div>progress 20/30 days elapsed</div>\n")
    rep = _run(tmp_path, [f])
    assert rep["ok"] is True


# ── paper APY divergence ───────────────────────────────────────────────────


def test_flags_apy_divergence(tmp_path):
    # canon 3.6% ; claim 8.5% → > 1pp → flagged.
    f = _write(tmp_path, "a.astro", "<p>Current paper APY: ~8.5% (variable)</p>\n")
    rep = _run(tmp_path, [f])
    assert rep["ok"] is False
    d = rep["divergences"][0]
    assert d["kind"] == "paper_apy"
    assert d["claimed"] == 8.5
    assert d["canonical"] == 3.6


def test_apy_within_tolerance_not_flagged(tmp_path):
    # canon 3.6% ; claim 3.5% within 1pp → OK.
    f = _write(tmp_path, "a.astro", "<p>Current paper APY: ~3.5%</p>\n")
    rep = _run(tmp_path, [f])
    assert rep["ok"] is True


def test_unrelated_apy_not_flagged(tmp_path):
    # A strategy target APY ("~15% APY") is not the headline paper APY → ignore.
    f = _write(tmp_path, "a.astro", "<p>Target APY ~15% for max-yield sleeve</p>\n")
    rep = _run(tmp_path, [f])
    assert rep["ok"] is True


# ── paper day literal + dynamic placeholder ────────────────────────────────


def test_flags_wrong_paper_day_literal(tmp_path):
    f = _write(tmp_path, "d.astro", "<p>Paper day 9 from 2026-06-10</p>\n")
    rep = _run(tmp_path, [f])
    assert rep["ok"] is False
    d = rep["divergences"][0]
    assert d["kind"] == "paper_day"
    assert d["claimed"] == 9
    assert d["canonical"] == 15


def test_correct_paper_day_not_flagged(tmp_path):
    f = _write(tmp_path, "d.astro", "<p>Paper day 15 from 2026-06-10</p>\n")
    rep = _run(tmp_path, [f])
    assert rep["ok"] is True


def test_dynamic_placeholder_not_flagged(tmp_path):
    # The placeholder fetches live value at runtime → static text inside is OK.
    f = _write(
        tmp_path,
        "h.astro",
        '<span id="hero-paper-day">Paper day 9 · started Jun 10</span>\n',
    )
    rep = _run(tmp_path, [f])
    assert rep["ok"] is True


# ── clean repo path + determinism ──────────────────────────────────────────


def test_clean_multifile(tmp_path):
    files = [
        _write(tmp_path, "a.astro", "<p>29 criteria · 27/29 pass</p>\n"),
        _write(tmp_path, "b.jsx", "Go-live requires all 29 criteria to pass\n"),
        _write(tmp_path, "c.html", "<p>Current paper APY: ~3.6%</p>\n"),
    ]
    rep = _run(tmp_path, files)
    assert rep["ok"] is True
    assert rep["divergence_count"] == 0
    assert rep["scanned_files"] == 3


def test_determinism(tmp_path):
    files = [
        _write(tmp_path, "z.astro", "<p>GoLiveChecker 26-criterion</p>\n"),
        _write(tmp_path, "a.astro", "<p>25/29 criteria passing</p>\n"),
    ]
    r1 = _run(tmp_path, files)
    r2 = _run(tmp_path, files)
    # Drop the timestamp before comparing.
    r1.pop("generated_at")
    r2.pop("generated_at")
    assert r1 == r2
    # Ordering is by (file, line, kind) → deterministic across runs.
    order = [(d["file"], d["line"], d["kind"]) for d in r1["divergences"]]
    assert order == sorted(order)


def test_report_shape(tmp_path):
    f = _write(tmp_path, "p.astro", "<p>25/29 criteria passing</p>\n")
    rep = _run(tmp_path, [f])
    assert rep["llm_forbidden"] is True
    assert rep["model"] == "presentation_ssot_check"
    assert set(rep["canonical"]) == {
        "golive_total",
        "golive_passed",
        "track_days",
        "apy_today_pct",
        "paper_start_date",
    }
    for d in rep["divergences"]:
        assert set(d) >= {"file", "line", "kind", "claimed", "canonical", "context"}
