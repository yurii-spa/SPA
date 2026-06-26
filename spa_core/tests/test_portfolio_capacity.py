"""
spa_core/tests/test_portfolio_capacity.py — the COMBINED multi-sleeve portfolio-capacity model.

Covers spa_core/strategy_lab/portfolio_capacity.py — the deterministic model that aggregates capacity
across the THREE sleeve families (rates-desk PT carry + the deep tokenized-T-bill RWA floor + the stable
engines), applies a CORRELATION HAIRCUT where families share exit-liquidity / venues, and states the
honest $10M/yr-above-floor verdict + binding constraint.

PURE / no network / deterministic / fail-CLOSED. The model is exercised with an INJECTED rates-desk
report (a tiny synthetic portfolio dict) and an injected floor so the tests are hermetic and do not
touch the live deep dataset / network. Proves:

  • combined total_deployable == naive sum of per-family deployable MINUS the correlation haircut,
  • blended APY is consistent with the above-floor identity (floor + above_floor / deployable),
  • combined above-floor == Σ per-family above-floor − the haircut's above-floor loss (the identity),
  • the correlation haircut strictly REDUCES the combined book vs the naive sum,
  • the model is deterministic (same inputs → identical numbers),
  • fail-CLOSED on a missing rates-desk deep dataset.
"""
# LLM_FORBIDDEN
from __future__ import annotations

from decimal import Decimal

import pytest

from spa_core.strategy_lab import portfolio_capacity as PC
from spa_core.strategy_lab.rates_desk import pendle_pt_history as pph


# ── hermetic injected rates-desk report (shaped like rates_desk.portfolio.build_report output) ──────
def _rates_report(total_deployable: float = 330_000.0, net_apy: float = 20.0,
                  floor_pct: float = 3.4, n_books: int = 20) -> dict:
    """A minimal rates_desk.portfolio report carrying just the fields portfolio_capacity reads."""
    return {
        "rwa_floor_pct": floor_pct,
        "total_deployable_usd": total_deployable,
        "aggregate_net_apy_pct": net_apy,
        "n_fundable_books": n_books,
    }


@pytest.fixture
def report():
    """A combined report built from an injected rates report + an injected floor (fully hermetic)."""
    return PC.build_report(write=False, rates_report=_rates_report(), floor_pct=3.4)


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# structure
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_three_families_present(report):
    """The report aggregates exactly the three sleeve families, sorted by name."""
    fams = [f["family"] for f in report["families"]]
    assert fams == sorted(fams)
    assert set(fams) == {"rates_desk", "rwa_floor", "stable_engines"}


def test_each_family_above_floor_identity(report):
    """Per family: above_floor_usd_per_yr == deployable · max(0, net_apy − floor)/100."""
    floor = report["rwa_floor_pct"]
    for f in report["families"]:
        expect = f["deployable_usd"] * max(0.0, f["net_apy_pct"] - floor) / 100.0
        assert abs(f["above_floor_usd_per_yr"] - round(expect, 2)) < 1e-2


def test_rwa_floor_family_is_at_floor(report):
    """The RWA family yields AT the floor by construction → ~$0 above floor despite the deepest book."""
    rwa = next(f for f in report["families"] if f["family"] == "rwa_floor")
    assert abs(rwa["net_apy_pct"] - report["rwa_floor_pct"]) < 1e-9
    assert rwa["above_floor_usd_per_yr"] == 0.0
    # and it IS the deepest family (the deep base-yield engine)
    assert rwa["deployable_usd"] == max(f["deployable_usd"] for f in report["families"])


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# combined aggregation identities
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_combined_deployable_is_naive_sum_minus_haircut(report):
    """combined.total_deployable_usd == Σ per-family deployable − correlation_haircut_usd."""
    c = report["combined"]
    naive = sum(f["deployable_usd"] for f in report["families"])
    assert abs(c["naive_sum_deployable_usd"] - naive) < 1e-2
    assert abs(c["total_deployable_usd"] - (naive - c["correlation_haircut_usd"])) < 1e-2


def test_combined_above_floor_identity(report):
    """combined above-floor == Σ per-family above-floor − the haircut's above-floor loss.

    The haircut constrains the SMALLER shared-venue leg (rates_desk here), so the above-floor lost is
    the haircut depth valued at the rates carry rate (net_apy − floor)."""
    c = report["combined"]
    floor = report["rwa_floor_pct"]
    naive_above = sum(f["above_floor_usd_per_yr"] for f in report["families"])
    shared = [f for f in report["families"]
              if f["family"] in PC._SHARED_VENUE_FAMILIES and f["shares_exit_venue"]]
    binding = min(shared, key=lambda f: f["deployable_usd"])
    rate = max(0.0, binding["net_apy_pct"] - floor)
    haircut_loss = c["correlation_haircut_usd"] * rate / 100.0
    expect = max(0.0, naive_above - haircut_loss)
    assert abs(c["total_above_floor_usd_per_yr"] - expect) < 1.0


def test_blended_apy_consistent_with_above_floor(report):
    """blended_net_apy == floor + combined_above_floor / combined_deployable · 100 (the realized rate)."""
    c = report["combined"]
    floor = report["rwa_floor_pct"]
    if c["total_deployable_usd"] > 0:
        expect = floor + c["total_above_floor_usd_per_yr"] / c["total_deployable_usd"] * 100.0
        assert abs(c["blended_net_apy_pct"] - round(expect, 4)) < 1e-3
    # blended APY sits between the floor and the richest family's APY (a real weighted blend)
    assert floor - 1e-6 <= c["blended_net_apy_pct"] <= max(f["net_apy_pct"] for f in report["families"])


def test_pct_of_target_and_gap_consistent(report):
    """pct_of_10m_target and gap_to_10m_usd are consistent with the combined above-floor and the target."""
    c = report["combined"]
    target = report["target_above_floor_per_yr_usd"]
    above = c["total_above_floor_usd_per_yr"]
    assert abs(c["pct_of_10m_target"] - round(above / target * 100.0, 4)) < 1e-3
    assert abs(c["gap_to_10m_usd"] - round(max(0.0, target - above), 2)) < 1e-2


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# the correlation haircut reduces vs the naive sum
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_correlation_haircut_reduces_combined(report):
    """The correlation haircut is applied (shared stablecoin venues) and strictly REDUCES the combined
    deployable below the naive sum — the whole point: real desks share rails, so it is NOT additive."""
    c = report["combined"]
    assert c["correlation_haircut_applied"] is True
    assert c["correlation_haircut_usd"] > 0
    assert c["total_deployable_usd"] < c["naive_sum_deployable_usd"]


def test_haircut_is_half_of_smaller_shared_leg(report):
    """The haircut == CORRELATION_HAIRCUT_FRAC × the SMALLER shared-venue family's deployable (rates)."""
    c = report["combined"]
    shared = [f for f in report["families"]
              if f["family"] in PC._SHARED_VENUE_FAMILIES and f["shares_exit_venue"]]
    smaller = min(f["deployable_usd"] for f in shared)
    expect = smaller * float(PC.CORRELATION_HAIRCUT_FRAC)
    assert abs(c["correlation_haircut_usd"] - expect) < 1e-2


def test_stable_engines_not_haircut(report):
    """The stable engines run on DISTINCT venues → not flagged as sharing exit liquidity (no haircut)."""
    eng = next(f for f in report["families"] if f["family"] == "stable_engines")
    assert eng["shares_exit_venue"] is False


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# the honest $10M verdict + binding constraint
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_honest_far_short_of_10m(report):
    """The combined book is honestly WELL short of $10M/yr above floor at today's depth (no inflation)."""
    c = report["combined"]
    assert c["total_above_floor_usd_per_yr"] < float(PC.TARGET_ABOVE_FLOOR_PER_YR)
    assert c["pct_of_10m_target"] < 5.0  # nowhere near the target
    assert c["gap_to_10m_usd"] > 0


def test_binding_constraint_is_known_label(report):
    """The binding constraint is one of the three honest root causes, with an explanation."""
    c = report["combined"]
    assert c["binding_constraint"] in {
        PC.BINDING_RATES_DEPTH, PC.BINDING_RWA_YIELD, PC.BINDING_CORRELATION}
    assert isinstance(c["binding_constraint_explanation"], str) and c["binding_constraint_explanation"]


def test_deep_rwa_at_floor_drives_rwa_yield_binding(report):
    """With the real-shaped inputs (deep RWA at floor ≫ thin rates carry) the binding constraint is the
    RWA family yielding at the floor — its huge depth adds ~$0 above floor."""
    assert report["combined"]["binding_constraint"] == PC.BINDING_RWA_YIELD


def test_note_is_honest_and_nonempty(report):
    """The note states the combined numbers, the gap, and what would close it — never fabricated."""
    note = report["note"]
    assert "$10M/yr" in note
    assert "COMBINED" in note
    assert "correlation haircut" in note.lower()


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# determinism + fail-CLOSED
# ══════════════════════════════════════════════════════════════════════════════════════════════════
def test_deterministic_same_inputs_same_numbers():
    """Same injected (rates_report, floor) → identical combined numbers (no RNG, no clock in numbers)."""
    a = PC.build_report(write=False, rates_report=_rates_report(), floor_pct=3.4)
    b = PC.build_report(write=False, rates_report=_rates_report(), floor_pct=3.4)
    assert a["combined"]["total_deployable_usd"] == b["combined"]["total_deployable_usd"]
    assert a["combined"]["total_above_floor_usd_per_yr"] == b["combined"]["total_above_floor_usd_per_yr"]
    assert a["combined"]["blended_net_apy_pct"] == b["combined"]["blended_net_apy_pct"]
    assert a["combined"]["correlation_haircut_usd"] == b["combined"]["correlation_haircut_usd"]
    assert a["combined"]["binding_constraint"] == b["combined"]["binding_constraint"]
    assert [f["deployable_usd"] for f in a["families"]] == [f["deployable_usd"] for f in b["families"]]


def test_richer_rates_book_more_above_floor():
    """A deeper rates-desk carry book (the only above-floor edge) → MORE combined above-floor $/yr."""
    thin = PC.build_report(write=False, rates_report=_rates_report(total_deployable=100_000.0), floor_pct=3.4)
    deep = PC.build_report(write=False, rates_report=_rates_report(total_deployable=900_000.0), floor_pct=3.4)
    assert (deep["combined"]["total_above_floor_usd_per_yr"]
            > thin["combined"]["total_above_floor_usd_per_yr"])


def test_fail_closed_missing_deep_dataset(tmp_path, monkeypatch):
    """fail-CLOSED: with no rates report injected AND no deep dataset on disk, build RAISES — the
    combined book is never fabricated (the reused rates_desk.portfolio.load() fail-closes)."""
    missing = tmp_path / "does_not_exist.json"
    monkeypatch.setattr(pph, "_OUT", missing)
    with pytest.raises(FileNotFoundError):
        PC.build_report(write=False)


def test_write_is_atomic_and_roundtrips(tmp_path):
    """write=True persists the report atomically and it round-trips as valid JSON."""
    import json
    out = tmp_path / "combined.json"
    PC.build_report(write=True, rates_report=_rates_report(), floor_pct=3.4, out_path=out)
    assert out.exists()
    with open(out, encoding="utf-8") as fh:
        loaded = json.load(fh)
    assert loaded["model"] == "strategy_lab_combined_portfolio_capacity"
    assert loaded["llm_forbidden"] is True
    assert "combined" in loaded and "families" in loaded
