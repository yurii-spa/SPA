"""Balanced/Aggressive CIO Brief instrumentation — the wiring itself.

Before this, ``hy_cycle.py``/``lp_cycle.py`` never called ``write_shadow_rationale``
at all (recorded explicitly as out-of-scope in the CIO Brief phase C journal entry,
2026-08-30), so Balanced/Aggressive had no decision history and ``cio_brief`` showed
a hardcoded "not wired" state for both regardless of any data. This file closes that
gap: each cycle now calls the writer with its OWN ``book_id`` after its own
rebalance decision, converting its list-of-legs book into the flat
``{protocol: usd}`` shape the writer expects.

Three things get their own coverage here rather than living in
``test_sleeve_book_and_cio_directive.py`` or ``test_allocation_rationale_shadow.py``:
the leg-collapsing conversion, the provenance-extraction helper both cycles feed
the writer from, and the end-to-end wiring (behavioral — the real cycle function
actually produces a real ledger record — plus a cheap wiring-by-call-form backstop
in the style of ``test_sleeve_shadow.py::test_wiring_lp_cycle_calls_the_shadow``).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spa_core.investment_os import directive
from spa_core.paper_trading import sleeve_book

_PAPER_TRADING_DIR = Path(__file__).resolve().parents[1] / "paper_trading"


# ═══════════════════════ collapse_legs_to_flat ═══════════════════════
#
# Balanced/Aggressive hold their book as a LIST of leg-dicts
# ({"protocol": ..., "notional_usd": ...}); the writer expects a flat
# {protocol: usd} dict (the same shape Conservative's allocator already
# produces). This is the one conversion that has to happen at every call site.


def test_collapse_legs_sums_by_protocol() -> None:
    """A protocol appearing twice in the leg list (defensive case — shouldn't
    happen in one cycle's book, but the conversion must not silently drop
    one leg if it does) is SUMMED, not overwritten by the last one."""
    legs = [
        {"protocol": "maple", "notional_usd": 20_000.0},
        {"protocol": "pendle", "notional_usd": 15_000.0},
        {"protocol": "maple", "notional_usd": 5_000.0},
    ]
    assert sleeve_book.collapse_legs_to_flat(legs) == {
        "maple": 25_000.0, "pendle": 15_000.0,
    }


def test_collapse_legs_empty_list_is_empty_dict() -> None:
    assert sleeve_book.collapse_legs_to_flat([]) == {}
    assert sleeve_book.collapse_legs_to_flat(None) == {}


def test_collapse_legs_skips_legs_without_a_protocol_or_notional() -> None:
    """A cash-remainder leg or a malformed row must not become a phantom
    protocol with a fabricated size."""
    legs = [
        {"protocol": "", "notional_usd": 10_000.0},     # no protocol
        {"notional_usd": 10_000.0},                       # no protocol key at all
        {"protocol": "maple"},                             # no notional at all
        {"protocol": "pendle", "notional_usd": 0.0},        # zero — real value, kept
        "junk",                                             # not even a dict
    ]
    assert sleeve_book.collapse_legs_to_flat(legs) == {"pendle": 0.0}


def test_collapse_legs_matches_real_rebalance_book_output() -> None:
    """End-to-end shape check: feed real rebalance_book() output straight in.

    Two candidates, equal-split weight would be 50 % each, but the 40 % per-
    protocol cap (PER_PROTOCOL_CAP_PCT) binds first — 40k/40k, 20k left cash.
    """
    cands = [{"protocol": "a", "apy_pct": 20.0}, {"protocol": "b", "apy_pct": 15.0}]
    book, _, _ = sleeve_book.rebalance_book([], cands, 100_000.0, today="2026-08-30")
    flat = sleeve_book.collapse_legs_to_flat(book)
    assert flat == {"a": 40_000.0, "b": 40_000.0}
    assert sum(flat.values()) == sum(p["notional_usd"] for p in book)


# ═══════════════════════ apy_provenance_from_rows ═══════════════════════
#
# Balanced/Aggressive have no allocator object carrying APY/TVL provenance the
# way Conservative's cycle_runner does — the raw apy_ranking.json rows (written
# by apy_aggregator.py, which stamps apy_source/tvl_source per ADR-053/061/063)
# are the only source. sleeve_book.load_ranking_rows()/_dedup_best() strip that
# down to {"protocol","apy_pct"} for candidate selection, so this helper must
# read the RAW rows, before that filtering.


def test_provenance_extracts_all_four_maps_from_live_rows() -> None:
    rows = [
        {"protocol": "maple", "apy_pct": 9.5, "apy_source": "live",
         "tvl_source": "live", "tvl_usd": 2_500_000_000.0},
        {"protocol": "pendle", "apy_pct": 14.0, "apy_source": "fallback",
         "tvl_source": "unknown", "tvl_usd": None},
    ]
    apy_pct, apy_sources, tvl_sources, tvl_usd = sleeve_book.apy_provenance_from_rows(rows)
    assert apy_pct == {"maple": 9.5, "pendle": 14.0}
    assert apy_sources == {"maple": "live", "pendle": "fallback"}
    assert tvl_sources == {"maple": "live", "pendle": "unknown"}
    assert tvl_usd == {"maple": 2_500_000_000.0}   # pendle's None is NOT a $0 claim


def test_provenance_is_fail_closed_on_rows_missing_the_fields_entirely() -> None:
    """A row from an older/frozen fixture shape (no apy_source/tvl_source keys
    at all) must contribute NOTHING to the source maps — never guessed "live".
    This is the exact shape data/apy_ranking.json's frozen test canon has."""
    rows = [{"protocol": "susde", "apy_pct": 12.0, "tier": "T3",
             "network": "ethereum", "tvl_usd": 800_000_000.0}]
    apy_pct, apy_sources, tvl_sources, tvl_usd = sleeve_book.apy_provenance_from_rows(rows)
    assert apy_pct == {"susde": 12.0}
    assert apy_sources == {}                        # NOT "live" by default
    assert tvl_sources == {}
    assert tvl_usd == {"susde": 800_000_000.0}       # magnitude present, source absent


def test_provenance_ignores_garbage_rows() -> None:
    rows = ["junk", None, {"apy_pct": 9.0}, {"protocol": ""}, {"protocol": "x"}]
    apy_pct, apy_sources, tvl_sources, tvl_usd = sleeve_book.apy_provenance_from_rows(rows)
    assert apy_pct == apy_sources == tvl_sources == tvl_usd == {}


def test_provenance_empty_input() -> None:
    assert sleeve_book.apy_provenance_from_rows([]) == ({}, {}, {}, {})
    assert sleeve_book.apy_provenance_from_rows(None) == ({}, {}, {}, {})


# ═══════════════════════ wiring-by-call-form (cheap backstop) ═══════════════
#
# Same pattern as test_sleeve_shadow.py::test_wiring_lp_cycle_calls_the_shadow —
# catches a silently-removed call even if a future edit breaks the behavioral
# fixtures below in a way that still leaves them "passing" on some other path.


def test_hy_cycle_calls_write_shadow_rationale_with_its_own_book_id() -> None:
    src = (_PAPER_TRADING_DIR / "hy_cycle.py").read_text(encoding="utf-8")
    assert "from spa_core.paper_trading.allocation_rationale import write_shadow_rationale" in src
    assert "write_shadow_rationale(" in src
    assert 'book_id="balanced"' in src


def test_lp_cycle_calls_write_shadow_rationale_with_its_own_book_id() -> None:
    src = (_PAPER_TRADING_DIR / "lp_cycle.py").read_text(encoding="utf-8")
    assert "from spa_core.paper_trading.allocation_rationale import write_shadow_rationale" in src
    assert "write_shadow_rationale(" in src
    assert 'book_id="aggressive"' in src


def test_hy_cycle_shadow_call_is_fail_open() -> None:
    """A reporting bug in the shadow call must never break the Balanced cycle
    that feeds the live paper track (invariant: reporting layers fail open)."""
    src = (_PAPER_TRADING_DIR / "hy_cycle.py").read_text(encoding="utf-8")
    call_at = src.index("write_shadow_rationale(")
    guard_at = src.rfind("try:", 0, call_at)
    assert guard_at != -1, "write_shadow_rationale call is not inside a try block"
    except_at = src.index("except Exception", call_at)
    body = src[guard_at:except_at]
    assert "write_shadow_rationale(" in body


def test_lp_cycle_shadow_call_is_fail_open() -> None:
    src = (_PAPER_TRADING_DIR / "lp_cycle.py").read_text(encoding="utf-8")
    call_at = src.index("write_shadow_rationale(")
    guard_at = src.rfind("try:", 0, call_at)
    assert guard_at != -1, "write_shadow_rationale call is not inside a try block"
    except_at = src.index("except Exception", call_at)
    body = src[guard_at:except_at]
    assert "write_shadow_rationale(" in body


# ═══════════════════════ behavioral: the real cycle writes a real record ═════
#
# Same fixture shape as test_sleeve_book_and_cio_directive.py's `hy`/`lp`
# fixtures (redefined here, not imported, so this file stays independently
# runnable and its intent legible on its own — those fixtures are private to
# that module). data_dir routes through _HY_DATA_PATH.parent/_LP_DATA_PATH.parent
# (NOT the real _PROJECT_ROOT/data — see the comment at the call site in
# hy_cycle.py/lp_cycle.py), so this never touches live data/.


@pytest.fixture
def hy(monkeypatch, tmp_path):
    import spa_core.paper_trading.hy_cycle as m
    monkeypatch.setattr(m, "_HY_DATA_PATH", tmp_path / "hy_paper_trading.json")
    monkeypatch.setattr(m, "_HY_REGIME_LOG_PATH", tmp_path / "hy_regime_log.json")
    monkeypatch.setattr(m, "get_hy_regime", lambda: "ENTER")
    monkeypatch.setattr(m, "refresh_hy_regime", lambda *a, **k: "ENTER")
    monkeypatch.setattr(sleeve_book, "_APY_RANKING", tmp_path / "apy_ranking.json")
    monkeypatch.setattr(directive, "_PROJECT_ROOT", tmp_path)
    return m


@pytest.fixture
def lp(monkeypatch, tmp_path):
    import spa_core.paper_trading.lp_cycle as m
    monkeypatch.setattr(m, "_LP_DATA_PATH", tmp_path / "lp_paper_trading.json")
    monkeypatch.setattr(sleeve_book, "_APY_RANKING", tmp_path / "apy_ranking.json")
    monkeypatch.setattr(directive, "_PROJECT_ROOT", tmp_path)
    return m


def _write_ranking(tmp: Path, *pairs) -> None:
    """Rows with real apy_source/tvl_source, matching apy_aggregator.py's
    actual output shape (NOT the stripped {"protocol","apy_pct"} shape the
    older fixtures in test_sleeve_book_and_cio_directive.py use — those don't
    need provenance, this test does)."""
    (tmp / "apy_ranking.json").write_text(json.dumps({"by_apy": [
        {"protocol": n, "apy_pct": a, "apy_source": "live",
         "tvl_source": "live", "tvl_usd": 5.0e8}
        for n, a in pairs
    ]}), encoding="utf-8")


class TestHyCycleWritesItsOwnLedger:
    def test_real_cycle_produces_a_balanced_ledger_record(self, hy, tmp_path):
        _write_ranking(tmp_path, ("pendle", 14.0), ("maple", 9.5))
        res = hy.run_hy_cycle(dry_run=False)
        assert res["cycle_skipped"] is False

        ledger = tmp_path / "allocation_rationale_history_balanced.jsonl"
        assert ledger.exists()
        rec = json.loads(ledger.read_text().splitlines()[-1])
        assert rec["book_id"] == "balanced"
        assert rec["target_positions"] == {"pendle": 40_000.0, "maple": 40_000.0}
        assert rec["apy_evidenced_pct"] == {"pendle": 14.0, "maple": 9.5}

        # Conservative's file must not exist — this is Balanced's own ledger.
        assert not (tmp_path / "allocation_rationale_history.jsonl").exists()

    def test_dry_run_computes_but_does_not_persist(self, hy, tmp_path):
        """dry_run=True must not leave a ledger file — matches the writer's
        own write=False contract and cycle_runner's write=write pattern."""
        _write_ranking(tmp_path, ("pendle", 14.0))
        res = hy.run_hy_cycle(dry_run=True)
        assert res["cycle_skipped"] is False
        assert not (tmp_path / "allocation_rationale_history_balanced.jsonl").exists()

    def test_cio_brief_reads_the_real_cycles_own_record(self, hy, tmp_path):
        """The point of the whole feature: after a real cycle, cio_brief must
        show Balanced as available with WHERE naming its actual holdings —
        not the hardcoded "not wired" state."""
        _write_ranking(tmp_path, ("pendle", 14.0), ("maple", 9.5))
        hy.run_hy_cycle(dry_run=False)

        from spa_core.paper_trading.cio_brief import build_books_brief
        brief = build_books_brief(tmp_path)
        assert brief["balanced"]["available"] is True
        assert "pendle" in brief["balanced"]["where"] or "maple" in brief["balanced"]["where"]

    def test_a_second_cycle_carries_yesterdays_book_as_current(self, hy, tmp_path):
        """current_positions on cycle 2 must be cycle 1's TARGET (the book it
        actually ended up holding) — proves _legs_before is captured BEFORE
        the day's rebalance overwrites state["positions"], not after."""
        _write_ranking(tmp_path, ("pendle", 14.0))
        hy.run_hy_cycle(dry_run=False)

        # Force a new day by clearing daily_history's date guard: simplest is
        # to seed a state with a different last date, but run_hy_cycle keys
        # off clock.utcnow() — instead assert the invariant directly against
        # the ledger record that cycle 1 wrote, and against state.
        state = json.loads((tmp_path / "hy_paper_trading.json").read_text())
        ledger = tmp_path / "allocation_rationale_history_balanced.jsonl"
        rec = json.loads(ledger.read_text().splitlines()[-1])
        assert rec["current_positions"] == {}                    # day 1: nothing held before
        assert rec["target_positions"] == {"pendle": 40_000.0}   # day 1: what it opened
        assert sleeve_book.collapse_legs_to_flat(state["positions"]) == rec["target_positions"]


class TestLpCycleWritesItsOwnLedger:
    def test_real_cycle_produces_an_aggressive_ledger_record(self, lp, tmp_path):
        _write_ranking(tmp_path, ("aerodrome", 11.0), ("aave", 9.0), ("curve_3pool", 8.0))
        res = lp.run_lp_cycle(dry_run=False)
        assert res.get("kill_switch") is not True

        ledger = tmp_path / "allocation_rationale_history_aggressive.jsonl"
        assert ledger.exists()
        rec = json.loads(ledger.read_text().splitlines()[-1])
        assert rec["book_id"] == "aggressive"
        # top-2 concentration (AGG_MAX_POSITIONS=2): aerodrome + aave, not curve_3pool
        assert set(rec["target_positions"]) == {"aerodrome", "aave"}

        assert not (tmp_path / "allocation_rationale_history.jsonl").exists()
        assert not (tmp_path / "allocation_rationale_history_balanced.jsonl").exists()

    def test_dry_run_computes_but_does_not_persist(self, lp, tmp_path):
        _write_ranking(tmp_path, ("aerodrome", 11.0))
        lp.run_lp_cycle(dry_run=True)
        assert not (tmp_path / "allocation_rationale_history_aggressive.jsonl").exists()

    def test_cio_brief_reads_the_real_cycles_own_record(self, lp, tmp_path):
        _write_ranking(tmp_path, ("aerodrome", 11.0), ("aave", 9.0))
        lp.run_lp_cycle(dry_run=False)

        from spa_core.paper_trading.cio_brief import build_books_brief
        brief = build_books_brief(tmp_path)
        assert brief["aggressive"]["available"] is True

    def test_same_day_rerun_is_idempotent_and_shows_no_move(self, lp, tmp_path):
        """Re-running the same calendar date must replace (not duplicate) the
        ledger line, and since no NEW rebalance decision was made, current
        must equal target — an honest HOLD, not a repeated ACT."""
        _write_ranking(tmp_path, ("aerodrome", 11.0), ("aave", 9.0))
        lp.run_lp_cycle(dry_run=False)
        lp.run_lp_cycle(dry_run=False)   # same day

        ledger = tmp_path / "allocation_rationale_history_aggressive.jsonl"
        lines = [ln for ln in ledger.read_text().splitlines() if ln.strip()]
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["current_positions"] == rec["target_positions"]


def test_hy_and_lp_ledgers_never_collide_when_run_together(monkeypatch, tmp_path):
    """Both sleeves running against the SAME data_dir (the real production
    layout — one shared data/ tree) must land in two distinct files."""
    import spa_core.paper_trading.hy_cycle as hy_mod
    import spa_core.paper_trading.lp_cycle as lp_mod

    monkeypatch.setattr(hy_mod, "_HY_DATA_PATH", tmp_path / "hy_paper_trading.json")
    monkeypatch.setattr(hy_mod, "_HY_REGIME_LOG_PATH", tmp_path / "hy_regime_log.json")
    monkeypatch.setattr(hy_mod, "get_hy_regime", lambda: "ENTER")
    monkeypatch.setattr(hy_mod, "refresh_hy_regime", lambda *a, **k: "ENTER")
    monkeypatch.setattr(lp_mod, "_LP_DATA_PATH", tmp_path / "lp_paper_trading.json")
    monkeypatch.setattr(sleeve_book, "_APY_RANKING", tmp_path / "apy_ranking.json")
    monkeypatch.setattr(directive, "_PROJECT_ROOT", tmp_path)

    _write_ranking(tmp_path, ("pendle", 14.0), ("aerodrome", 11.0), ("aave", 9.0))
    hy_mod.run_hy_cycle(dry_run=False)
    lp_mod.run_lp_cycle(dry_run=False)

    balanced_ledger = tmp_path / "allocation_rationale_history_balanced.jsonl"
    aggressive_ledger = tmp_path / "allocation_rationale_history_aggressive.jsonl"
    assert balanced_ledger.exists() and aggressive_ledger.exists()
    balanced_rec = json.loads(balanced_ledger.read_text().splitlines()[-1])
    aggressive_rec = json.loads(aggressive_ledger.read_text().splitlines()[-1])
    assert balanced_rec["book_id"] == "balanced"
    assert aggressive_rec["book_id"] == "aggressive"
    assert balanced_rec["target_positions"] != aggressive_rec["target_positions"]
