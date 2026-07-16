"""Regression tests for ``EthenaSusdeAdapter`` (T2 read-only APY/TVL feed).

Focus: the ``_norm_apy`` unit-normaliser and its fail-CLOSED contract.

Background — the bug these tests lock down
------------------------------------------
``_norm_apy`` normalises a raw APY to a decimal with a ``>1.0 → percent`` guess.
A percent yield-collapse to <1% (e.g. DeFiLlama ``apy=0.9`` meaning 0.9%) is
mis-classified by that heuristic as an already-decimal ``0.9`` == 90%, which was
then *silently clamped* to a plausible-looking 50% by ``_clamp`` — fabricating a
healthy-looking APY and defeating the advisory anomaly flag (``apy < 3%``)
exactly when a collapse is happening.

The fix makes ``_norm_apy`` reject an out-of-band normalised value (``None``,
fail-CLOSED per invariant #2 / the ``apy_contract`` philosophy) so the caller
falls through to the next source / cached-stale instead of publishing a made-up
number. These tests assert both the unit-level normalisation and the end-to-end
``fetch()`` fail-closed behaviour, and guard that the *normal* 0–50% band is
entirely unaffected.

The adapter exposes an ``http_get(url, timeout)`` injection seam, so every test
here is fully offline / deterministic (no live network).
"""
from __future__ import annotations

import math

import pytest

from spa_core.adapters.ethena_susde_adapter import EthenaSusdeAdapter


# ---------------------------------------------------------------------------
# _norm_apy — unit normalisation + fail-closed band
# ---------------------------------------------------------------------------


class TestNormApy:
    def test_percent_value_becomes_decimal(self):
        # 12.5% arrives as a percent magnitude -> 0.125 decimal.
        assert EthenaSusdeAdapter._norm_apy(12.5) == pytest.approx(0.125)

    def test_decimal_value_passthrough(self):
        # An already-decimal 12% stays 0.12 (heuristic keeps v <= 1.0 as-is).
        assert EthenaSusdeAdapter._norm_apy(0.12) == pytest.approx(0.12)

    def test_zero_is_kept_not_rejected(self):
        # 0% is a legitimate in-band value (MIN_APY == 0.0), not a bad read.
        assert EthenaSusdeAdapter._norm_apy(0.0) == 0.0

    def test_upper_boundary_percent_kept(self):
        # 50% (percent) -> 0.50 sits exactly on MAX_APY -> kept.
        assert EthenaSusdeAdapter._norm_apy(50.0) == pytest.approx(0.50)

    def test_percent_collapse_below_one_pct_fails_closed(self):
        # THE regression: 0.9% as a percent magnitude is mis-scaled by the
        # >1.0 heuristic into 0.9 == 90% -> out-of-band -> REJECTED (was clamped
        # to a fabricated 50%).
        assert EthenaSusdeAdapter._norm_apy(0.9) is None

    def test_out_of_band_high_fails_closed(self):
        # 200% (percent) -> 2.0 decimal -> above MAX_APY -> rejected, not
        # silently clamped to 0.50.
        assert EthenaSusdeAdapter._norm_apy(200.0) is None

    def test_negative_fails_closed(self):
        assert EthenaSusdeAdapter._norm_apy(-5.0) is None

    def test_nan_fails_closed(self):
        assert EthenaSusdeAdapter._norm_apy(float("nan")) is None

    def test_inf_fails_closed(self):
        assert EthenaSusdeAdapter._norm_apy(float("inf")) is None
        assert EthenaSusdeAdapter._norm_apy(float("-inf")) is None

    def test_bool_fails_closed(self):
        # bool is an int subclass; must not be treated as a 1.0/0.0 APY.
        assert EthenaSusdeAdapter._norm_apy(True) is None
        assert EthenaSusdeAdapter._norm_apy(False) is None

    def test_non_numeric_fails_closed(self):
        assert EthenaSusdeAdapter._norm_apy("12.5") is None
        assert EthenaSusdeAdapter._norm_apy(None) is None
        assert EthenaSusdeAdapter._norm_apy({"value": 12.5}) is None

    def test_result_never_out_of_band(self):
        # Property: whatever _norm_apy returns (when not None) is always within
        # the adapter's declared sanity band -> _clamp downstream is a no-op.
        for raw in [0.0, 0.5, 12.0, 30.0, 50.0, 0.05, 0.9, 90.0, 200.0, -1.0]:
            out = EthenaSusdeAdapter._norm_apy(raw)
            if out is not None:
                assert EthenaSusdeAdapter.MIN_APY <= out <= EthenaSusdeAdapter.MAX_APY


# ---------------------------------------------------------------------------
# fetch() end-to-end — fail-closed instead of fabricating a clamped number
# ---------------------------------------------------------------------------


def _make_http(*, primary_value=None, primary_fail=False,
               dl_apy=None, dl_tvl=1_000_000_000.0, dl_fail=False):
    """Build an ``http_get(url, timeout)`` fake dispatching on the URL host."""

    def _get(url, timeout):  # noqa: ARG001 - timeout unused in fake
        if "ethena" in url:
            if primary_fail:
                raise RuntimeError("primary outage")
            return {"stakingYield": {"value": primary_value}}
        if "llama" in url:
            if dl_fail:
                raise RuntimeError("defillama outage")
            return {"data": [{
                "project": "ethena-usde",
                "symbol": "SUSDE",
                "apy": dl_apy,
                "tvlUsd": dl_tvl,
            }]}
        raise RuntimeError(f"unexpected url {url}")

    return _get


class TestFetchFailClosed:
    def test_healthy_primary_is_live(self):
        adapter = EthenaSusdeAdapter(http_get=_make_http(primary_value=12.0))
        rec = adapter.fetch()
        assert rec["live_data"] is True
        assert rec["stale"] is False
        assert rec["source"] == "ethena_api"
        assert rec["apy"] == pytest.approx(0.12)
        assert rec["anomaly"] is False

    def test_out_of_band_primary_falls_to_cached_stale_not_clamped(self):
        # A percent yield-collapse to 0.9% is mis-scaled -> out-of-band -> the
        # primary + defillama both yield nothing usable -> honest cached-stale,
        # NOT a fabricated live 50%.
        adapter = EthenaSusdeAdapter(
            http_get=_make_http(primary_value=0.9, dl_apy=None)
        )
        rec = adapter.fetch()
        assert rec["live_data"] is False
        assert rec["stale"] is True
        assert rec["source"] == "cached"
        assert rec["error"] == "live_feed_unavailable"
        assert rec["apy"] == pytest.approx(EthenaSusdeAdapter.FALLBACK_APY)
        # The old bug produced a live, non-stale 0.50 here.
        assert rec["apy"] != pytest.approx(0.50)

    def test_defillama_fallback_used_when_primary_dead(self):
        adapter = EthenaSusdeAdapter(
            http_get=_make_http(primary_fail=True, dl_apy=9.0, dl_tvl=2.0e9)
        )
        rec = adapter.fetch()
        assert rec["live_data"] is True
        assert rec["source"] == "defillama"
        assert rec["apy"] == pytest.approx(0.09)
        assert rec["tvl"] == pytest.approx(2.0e9)

    def test_inband_low_yield_trips_anomaly_flag(self):
        # A genuine, correctly-scaled low read (2%) stays in-band and is what
        # the advisory anomaly floor (3%) is meant to catch.
        adapter = EthenaSusdeAdapter(http_get=_make_http(primary_value=2.0))
        rec = adapter.fetch()
        assert rec["live_data"] is True
        assert rec["apy"] == pytest.approx(0.02)
        assert rec["anomaly"] is True

    def test_apy_is_never_out_of_band_or_nan(self):
        for pv in [0.9, 200.0, -3.0, float("nan"), 12.0, 2.0]:
            adapter = EthenaSusdeAdapter(http_get=_make_http(primary_value=pv))
            apy = adapter.fetch()["apy"]
            assert apy is not None
            assert not math.isnan(apy)
            assert EthenaSusdeAdapter.MIN_APY <= apy <= EthenaSusdeAdapter.MAX_APY
