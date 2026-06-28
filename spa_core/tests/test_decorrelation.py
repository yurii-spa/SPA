"""
spa_core/tests/test_decorrelation.py — WS-4.4 empirical cross-sleeve decorrelation + honest capacity.

Pins: the matrix is a VALID correlation matrix (symmetric, diag=1, |corr|<=1); a thin pair is UNKNOWN
(never a degenerate 2-point correlation); the decorrelation-aware capacity ceiling credits a BOUNDED
benefit ONLY from measured correlations and ZERO uplift on unmeasured tracks (fail-CLOSED); no inflated
number; a malformed series is DROPPED (never a fabricated correlation row).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime

from spa_core.strategy_lab import decorrelation as dec


def _day(offset: int) -> str:
    return (datetime.date(2026, 6, 1) + datetime.timedelta(days=offset)).isoformat()


def _series(equities, start=0):
    return {"series": [
        {"date": _day(start + i), "equity_usd": float(e)} for i, e in enumerate(equities)]}


# ── PROPERTY: a valid correlation matrix ──────────────────────────────────────────────────────
def test_matrix_is_valid():
    books = {
        "a": _series([100000, 100010, 100025, 100045, 100060]),
        "b": _series([100000, 100012, 100020, 100050, 100055]),
    }
    mat = dec.decorrelation_matrix(books)
    v = dec.validate_matrix(mat)
    assert v["valid"] is True
    assert v["symmetric"] and v["diag_ok"] and v["in_range"]
    # diagonal is exactly 1.0, off-diagonal symmetric
    assert mat["matrix"]["a"]["a"] == 1.0
    assert mat["matrix"]["a"]["b"] == mat["matrix"]["b"]["a"]
    assert -1.0 <= mat["matrix"]["a"]["b"] <= 1.0


def test_thin_pair_is_unknown():
    """A pair with < MIN_OVERLAP_RETURNS aligned returns → correlation UNKNOWN (None), never ±1."""
    books = {"a": _series([100000, 100010]), "b": _series([100000, 100012])}  # 1 aligned return
    mat = dec.decorrelation_matrix(books)
    assert mat["matrix"]["a"]["b"] is None
    assert mat["n_known_pairs"] == 0
    assert mat["n_unknown_pairs"] == 1
    # still a valid matrix (symmetry holds for None==None, diag=1)
    assert dec.validate_matrix(mat)["valid"] is True


def test_malformed_series_dropped():
    """A book whose series fails integrity is DROPPED — never a fabricated correlation row."""
    books = {
        "a": _series([100000, 100010, 100025, 100045]),
        "bad": {"series": [{"date": "2026-06-01", "equity_usd": float("inf")},
                           {"date": "2026-06-02", "equity_usd": 100010.0}]},
    }
    mat = dec.decorrelation_matrix(books)
    assert "bad" not in mat["books"]
    assert mat["books"] == ["a"]


# ── PROPERTY: the capacity ceiling is bounded + fail-CLOSED ───────────────────────────────────
def test_ceiling_measured_is_bounded_uplift():
    books = {
        "a": _series([100000, 100010, 100025, 100045, 100060]),
        "b": _series([100000, 100012, 100020, 100050, 100055]),
    }
    mat = dec.decorrelation_matrix(books)
    c = dec.capacity_ceiling(400_000.0, mat)
    assert c["measured"] is True
    # the uplift is bounded by MAX_DECORR_BENEFIT_FRAC and >= 0
    assert 0.0 <= c["benefit_frac"] <= dec.MAX_DECORR_BENEFIT_FRAC
    assert c["decorrelated_ceiling_usd"] >= c["structural_deployable_usd"]
    assert c["decorrelated_ceiling_usd"] <= c["structural_deployable_usd"] * (1 + dec.MAX_DECORR_BENEFIT_FRAC) + 1e-6


def test_ceiling_unmeasured_zero_uplift():
    """fail-CLOSED: no measured pair → ZERO uplift, ceiling == structural (no inflation)."""
    books = {"a": _series([100000, 100010]), "b": _series([100000, 100012])}  # thin → UNKNOWN
    mat = dec.decorrelation_matrix(books)
    c = dec.capacity_ceiling(400_000.0, mat)
    assert c["measured"] is False
    assert c["benefit_frac"] == 0.0
    assert c["uplift_usd"] == 0.0
    assert c["decorrelated_ceiling_usd"] == c["structural_deployable_usd"]


def test_higher_correlation_smaller_benefit():
    """The diversification benefit SHRINKS as correlation rises (perfectly correlated → ~0 benefit)."""
    # nearly-identical books → high correlation → small benefit
    high = {
        "a": _series([100000, 100010, 100020, 100030, 100040]),
        "b": _series([100000, 100010, 100020, 100030, 100040]),
    }
    # anti-correlated-ish books → lower |corr| → larger benefit
    low = {
        "a": _series([100000, 100020, 100010, 100030, 100015]),
        "b": _series([100000, 100005, 100025, 100008, 100035]),
    }
    ch = dec.capacity_ceiling(400_000.0, dec.decorrelation_matrix(high))
    cl = dec.capacity_ceiling(400_000.0, dec.decorrelation_matrix(low))
    # both measured; the lower-correlation book is credited at least as much benefit
    assert ch["measured"] and cl["measured"]
    assert cl["benefit_frac"] >= ch["benefit_frac"]


# ── determinism + full report ─────────────────────────────────────────────────────────────────
def test_build_report_deterministic_and_valid():
    books = {
        "a": _series([100000, 100010, 100025, 100045, 100060]),
        "b": _series([100000, 100012, 100020, 100050, 100055]),
    }
    a = dec.build_report(book_series=books, structural_deployable_usd=400_000.0, write=False,
                         now_iso="2026-06-28T00:00:00+00:00")
    b = dec.build_report(book_series=books, structural_deployable_usd=400_000.0, write=False,
                         now_iso="2026-06-28T00:00:00+00:00")
    assert a == b
    assert a["matrix_validity"]["valid"] is True
    assert a["is_advisory"] is True
