"""
spa_core/tests/test_sleeve_capture.py — WS1.3 captured-paper FixedCarry sleeve.

Proves the captured-paper sleeve:
  • bounds the allocation (≤5% notional, hard-capped + RiskPolicy-gated);
  • keeps a SEPARATE book — the go-live $100k evidenced equity curve is BYTE-UNTOUCHED;
  • accrues at the REAL live net carry, and is fail-CLOSED (no fabricated yield) when the
    validated track has no carry / a malformed carry;
  • is approved by deterministic RiskPolicy under the T2 caps;
  • carries advisory / owner-gated / honest labeling.

stdlib + pytest only. Hermetic: all paths are tmp-injected, the live data/ tree is never touched.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from spa_core.paper_trading import sleeve_capture as sc


# ── fixtures ────────────────────────────────────────────────────────────────────────────────
def _write_rates_state(path: Path, books: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"state": {"books": books}}), encoding="utf-8")


def _good_books() -> dict:
    # two open carry books at known locked rates → size-weighted APY is exact.
    return {
        "0xaaa": {"size": "6000", "entry_rate": "0.04", "quote": {"tvl_usd": "9000000"}},
        "0xbbb": {"size": "4000", "entry_rate": "0.05", "quote": {"tvl_usd": "6000000"}},
    }


@pytest.fixture()
def rates_state(tmp_path) -> Path:
    p = tmp_path / "rates_state.json"
    _write_rates_state(p, _good_books())
    return p


@pytest.fixture()
def capture_path(tmp_path) -> Path:
    return tmp_path / "captured_sleeves" / "rates_fixed_carry_capture.json"


# ── bounded allocation ───────────────────────────────────────────────────────────────────────
def test_bounded_notional_is_at_most_5pct():
    n = sc.bounded_notional(100_000.0, 0.05)
    assert n == pytest.approx(5_000.0)
    # an over-large frac is clamped to the 5% ceiling (never exceeds the bound).
    assert sc.bounded_notional(100_000.0, 0.50) == pytest.approx(5_000.0)
    # a non-positive base → zero notional (fail-CLOSED).
    assert sc.bounded_notional(0.0, 0.05) == 0.0


def test_capture_notional_never_exceeds_bound(rates_state, capture_path):
    res = sc.run_capture_cycle(dry_run=False, capture_path=capture_path,
                               rates_state_path=rates_state)
    assert res["accrued"] is True
    assert res["notional_usd"] <= sc.CAPTURE_CAPITAL_BASE * sc.MAX_NOTIONAL_FRAC + 1e-6


# ── real-APY accrual ───────────────────────────────────────────────────────────────────────────
def test_accrues_at_real_size_weighted_carry(rates_state, capture_path):
    # size-weighted: (6000*0.04 + 4000*0.05)/10000 = 0.044
    saved = sc._RATES_STATE_PATH
    sc._RATES_STATE_PATH = rates_state  # direct read for the helper
    try:
        live = sc.live_fixed_carry_apy()
    finally:
        sc._RATES_STATE_PATH = saved
    assert live == pytest.approx(0.044)

    res = sc.run_capture_cycle(dry_run=False, capture_path=capture_path,
                               rates_state_path=rates_state)
    notional = res["notional_usd"]
    expected_daily = notional * 0.044 / 365.0
    assert res["daily_carry_usd"] == pytest.approx(expected_daily, abs=1e-5)
    assert res["live_apy_decimal"] == pytest.approx(0.044)


def test_fail_closed_on_missing_state(tmp_path, capture_path):
    missing = tmp_path / "does_not_exist.json"
    res = sc.run_capture_cycle(dry_run=False, capture_path=capture_path,
                               rates_state_path=missing)
    assert res["accrued"] is False
    assert res["reason"] == "no_live_carry_fail_closed"
    assert res["live_apy_decimal"] is None
    assert res["equity_usd"] == 0.0  # NO fabricated yield


def test_fail_closed_on_no_open_book(tmp_path, capture_path):
    empty = tmp_path / "empty.json"
    _write_rates_state(empty, {})  # zero books
    res = sc.run_capture_cycle(dry_run=False, capture_path=capture_path,
                               rates_state_path=empty)
    assert res["accrued"] is False
    assert res["live_apy_decimal"] is None


def test_fail_closed_on_malformed_carry(tmp_path, capture_path):
    bad = tmp_path / "bad.json"
    _write_rates_state(bad, {"0xaaa": {"size": "1000", "entry_rate": "not-a-number"}})
    res = sc.run_capture_cycle(dry_run=False, capture_path=capture_path,
                               rates_state_path=bad)
    assert res["accrued"] is False
    assert res["live_apy_decimal"] is None


def test_fail_closed_below_floor(tmp_path, capture_path):
    low = tmp_path / "low.json"
    # 0.2% carry — below the 1% honest floor → fail-CLOSED, no accrual.
    _write_rates_state(low, {"0xaaa": {"size": "1000", "entry_rate": "0.002",
                                       "quote": {"tvl_usd": "9000000"}}})
    res = sc.run_capture_cycle(dry_run=False, capture_path=capture_path,
                               rates_state_path=low)
    assert res["accrued"] is False
    assert res["live_apy_decimal"] is None


# ── RiskPolicy approval ────────────────────────────────────────────────────────────────────────
def test_riskpolicy_approves_bounded_capture():
    approval = sc.riskpolicy_approves(5_000.0, 0.044, pool_tvl_usd=9_000_000.0)
    assert approval.approved is True
    assert approval.violations == []
    assert approval.tier == "T2"


def test_sub_floor_tvl_book_excluded_no_accrual(tmp_path, capture_path):
    # the ONLY held book is on a sub-$5M pool → excluded from the eligible set → fail-CLOSED.
    thin_tvl = tmp_path / "thin.json"
    _write_rates_state(thin_tvl, {"0xaaa": {"size": "5000", "entry_rate": "0.04",
                                            "quote": {"tvl_usd": "1000000"}}})  # $1M < $5M floor
    res = sc.run_capture_cycle(dry_run=False, capture_path=capture_path,
                               rates_state_path=thin_tvl)
    assert res["accrued"] is False
    assert res["reason"] == "no_live_carry_fail_closed"
    assert res["live_apy_decimal"] is None


def test_only_floor_eligible_books_set_the_carry(tmp_path, capture_path):
    # mixed book: one ELIGIBLE ($9M, 4%) + one SUB-FLOOR ($2M, 8%). The captured carry must
    # reflect ONLY the eligible book (4%), NOT be inflated by the sub-floor 8% pool.
    mixed = tmp_path / "mixed.json"
    _write_rates_state(mixed, {
        "0xelig": {"size": "5000", "entry_rate": "0.04", "quote": {"tvl_usd": "9000000"}},
        "0xthin": {"size": "5000", "entry_rate": "0.08", "quote": {"tvl_usd": "2000000"}},
    })
    saved = sc._RATES_STATE_PATH
    sc._RATES_STATE_PATH = mixed
    try:
        apy = sc.live_fixed_carry_apy()
    finally:
        sc._RATES_STATE_PATH = saved
    assert apy == pytest.approx(0.04)  # only the eligible book counts, not the 8% sub-floor one
    res = sc.run_capture_cycle(dry_run=False, capture_path=capture_path, rates_state_path=mixed)
    assert res["accrued"] is True
    assert res["live_apy_decimal"] == pytest.approx(0.04)


# ── separate-book: go-live track BYTE-UNTOUCHED ─────────────────────────────────────────────────
def test_go_live_track_byte_untouched(rates_state, capture_path):
    """RED-TEAM: running the captured cycle must NOT touch the go-live equity curve (md5 + mtime)."""
    project_root = Path(sc.__file__).resolve().parents[2]
    golive = project_root / "data" / "equity_curve_daily.json"
    if not golive.exists():
        pytest.skip("go-live equity curve not present in this checkout")
    before_md5 = hashlib.md5(golive.read_bytes()).hexdigest()
    before_mtime = golive.stat().st_mtime_ns

    # full cycle, persisted, against the SEPARATE captured path (not the live default).
    sc.run_capture_cycle(dry_run=False, capture_path=capture_path, rates_state_path=rates_state)

    after_md5 = hashlib.md5(golive.read_bytes()).hexdigest()
    after_mtime = golive.stat().st_mtime_ns
    assert before_md5 == after_md5, "captured sleeve MUTATED the go-live equity curve (md5 changed)"
    assert before_mtime == after_mtime, "captured sleeve touched the go-live equity curve (mtime)"


def test_separate_book_written_not_co_mingled(rates_state, capture_path):
    sc.run_capture_cycle(dry_run=False, capture_path=capture_path, rates_state_path=rates_state)
    assert capture_path.exists()
    doc = json.loads(capture_path.read_text())
    assert doc["separate_book"] is True
    assert doc["co_mingled_with_golive"] is False
    # the captured book is its OWN file, not the go-live equity curve.
    assert capture_path.name == "rates_fixed_carry_capture.json"
    assert "equity_curve_daily" not in str(capture_path)


# ── advisory / honest labeling + idempotency ────────────────────────────────────────────────────
def test_advisory_and_owner_gated_labeling(rates_state, capture_path):
    res = sc.run_capture_cycle(dry_run=False, capture_path=capture_path, rates_state_path=rates_state)
    assert res["is_advisory"] is True
    assert res["capture_mode"] == "PAPER"
    summary = sc.get_capture_summary(capture_path=capture_path)
    assert summary["is_advisory"] is True
    assert summary["owner_gated_real_capital"] is True
    assert summary["capture_mode"] == "PAPER"
    assert summary["co_mingled_with_golive"] is False


def test_accrual_idempotent_per_day(rates_state, capture_path):
    r1 = sc.run_capture_cycle(dry_run=False, capture_path=capture_path, rates_state_path=rates_state)
    eq1 = r1["equity_usd"]
    # second run same UTC day → no double-accrual.
    r2 = sc.run_capture_cycle(dry_run=False, capture_path=capture_path, rates_state_path=rates_state)
    assert r2["equity_usd"] == pytest.approx(eq1)
    summary = sc.get_capture_summary(capture_path=capture_path)
    assert summary["days_tracked"] == 1


def test_dry_run_does_not_persist(rates_state, capture_path):
    sc.run_capture_cycle(dry_run=True, capture_path=capture_path, rates_state_path=rates_state)
    assert not capture_path.exists()
