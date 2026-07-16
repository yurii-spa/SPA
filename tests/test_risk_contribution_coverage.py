"""
tests/test_risk_contribution_coverage.py

MP-1468 (v10.84) — Coverage tests for spa_core/paper_trading/risk_contribution.py
(839 lines, previously untested in tests/).

15 tests on pure utility functions: _num, normalize_protocol, _classify_risk,
_build_cov_index, _match_instrument.

stdlib-only, no external dependencies.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from spa_core.analytics_lab.risk_contribution import (
    _num,
    normalize_protocol,
    _classify_risk,
    _build_cov_index,
    _match_instrument,
    content_fingerprint,
)


# ─── _num ─────────────────────────────────────────────────────────────────────


def test_01_num_valid_int():
    """Integer → float."""
    assert _num(42) == 42.0


def test_02_num_valid_float():
    """Float → same float."""
    assert _num(3.14) == 3.14


def test_03_num_bool_rejected():
    """bool is not a number (Python bool is subclass of int)."""
    assert _num(True) is None
    assert _num(False) is None


def test_04_num_nan_rejected():
    """NaN → None."""
    assert _num(float("nan")) is None


def test_05_num_inf_rejected():
    """Inf → None."""
    assert _num(float("inf")) is None


def test_06_num_string_rejected():
    """String → None."""
    assert _num("1.23") is None


# ─── normalize_protocol ───────────────────────────────────────────────────────


def test_07_normalize_aave():
    """'Aave V3' → 'aave_v3'."""
    assert normalize_protocol("Aave V3") == "aave_v3"


def test_08_normalize_with_dashes():
    """'aave-v3-usdc-ethereum' → 'aave_v3_usdc_ethereum'."""
    result = normalize_protocol("aave-v3-usdc-ethereum")
    assert "-" not in result, f"dash still in: {result!r}"
    assert result == "aave_v3_usdc_ethereum", f"got: {result!r}"


def test_09_normalize_already_normal():
    """Already normalized string is unchanged."""
    assert normalize_protocol("compound_v3") == "compound_v3"


def test_10_normalize_none_input():
    """None input → string conversion, no error."""
    result = normalize_protocol(None)
    assert isinstance(result, str)


# ─── _classify_risk ───────────────────────────────────────────────────────────


def test_11_classify_diversified():
    """HHI < 1500 → 'diversified'."""
    assert _classify_risk(1000) == "diversified"


def test_12_classify_moderate():
    """1500 ≤ HHI ≤ 2500 → 'moderate'."""
    assert _classify_risk(2000) == "moderate"
    assert _classify_risk(1500) == "moderate"


def test_13_classify_concentrated():
    """HHI > 2500 → 'concentrated'."""
    assert _classify_risk(3000) == "concentrated"
    assert _classify_risk(2501) == "concentrated"


def test_14_classify_none_input():
    """None input → None output."""
    assert _classify_risk(None) is None


# ─── _build_cov_index ─────────────────────────────────────────────────────────


def test_15_build_cov_index_valid():
    """Valid covariance_summary doc → non-empty slug_index and cov matrix."""
    cov_doc = {
        "covariance_matrix": {
            "aave-v3-usdc-ethereum": {
                "aave-v3-usdc-ethereum": 0.5,
                "compound-v3-usdc": 0.1,
            },
            "compound-v3-usdc": {
                "aave-v3-usdc-ethereum": 0.1,
                "compound-v3-usdc": 0.3,
            },
        }
    }
    slug_index, cov = _build_cov_index(cov_doc)
    assert len(slug_index) >= 2
    assert len(cov) == 2
    # All values must be finite
    for row in cov.values():
        for v in row.values():
            assert math.isfinite(v)
