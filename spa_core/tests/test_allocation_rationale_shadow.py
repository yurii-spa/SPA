"""ADR-060 phase 0 — the SHADOW writer: reports, never acts.

The whole point of the shadow phase is that a fortnight of real verdicts can be
read before any capital depends on them. So the two properties that matter most
here are: it changes nothing, and it cannot break the cycle.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from spa_core.paper_trading.allocation_rationale import (
    RATIONALE_FILENAME,
    _history_from_trades,
    _position_ages,
    _resolve_tier_caps,
    write_shadow_rationale,
)

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
BOOK = {"morpho_steakhouse": 40_000.0, "maple": 20_000.0, "pendle": 20_000.0,
        "compound_v3": 5_000.0}
APY = {"morpho_steakhouse": 3.4657, "maple": 5.1097, "pendle": 13.9419,
       "compound_v3": 3.2984}
SRC = {k: "live" for k in APY}


def _write(tmp_path: Path, **kw):
    kw.setdefault("current_positions", BOOK)
    kw.setdefault("target_positions", BOOK)
    kw.setdefault("apy_pct", APY)
    kw.setdefault("apy_sources", SRC)
    # РАЗМЕР TVL (08.08) — второй обязательный вход пригодности после провенанса
    # (тот добавили в Y2 2026-08-05 ровно так же). Пулы здесь заведомо крупные:
    # эти тесты про водопад и про идею «простой обязан быть назван», а не про
    # порог $5M — он проверяется в обе стороны в test_tvl_floor_one_definition.py.
    kw.setdefault("tvl_usd", {k: 1_000_000_000.0 for k in APY})
    kw.setdefault("capital_usd", 100_000.0)
    kw.setdefault("cycle_date", "2026-08-02")
    kw.setdefault("run_ts", NOW.isoformat())
    kw.setdefault("now", NOW)
    return write_shadow_rationale(data_dir=tmp_path, **kw)


def test_artifact_is_written_and_labelled_advisory(tmp_path: Path) -> None:
    doc = _write(tmp_path)
    on_disk = json.loads((tmp_path / RATIONALE_FILENAME).read_text(encoding="utf-8"))
    assert on_disk == doc
    assert doc["mode"] == "SHADOW"
    assert "no position was changed" in doc["note"]
    assert doc["decision_shadow"]["decision"] in ("ACT", "HOLD")


def test_writer_never_raises_on_broken_input(tmp_path: Path) -> None:
    """A reporting layer must not be able to break the cycle that feeds the track."""
    doc = write_shadow_rationale(
        data_dir=tmp_path / "does-not-exist",
        current_positions=None, target_positions=None,      # type: ignore[arg-type]
        apy_pct=None, apy_sources=None,                     # type: ignore[arg-type]
        capital_usd=float("nan"), cycle_date="x", run_ts="y", now=NOW, write=False)
    assert doc["mode"] == "SHADOW"


def test_write_false_leaves_no_file(tmp_path: Path) -> None:
    _write(tmp_path, write=False)
    assert not (tmp_path / RATIONALE_FILENAME).exists()


def test_only_live_sourced_protocols_count_as_evidence(tmp_path: Path) -> None:
    """Provenance comes from the allocator, which ADR-061/063 made truthful."""
    doc = _write(tmp_path, apy_sources={**SRC, "morpho_steakhouse": "fallback_stale"})
    assert doc["decision_shadow"]["evidence"]["unevidenced_held"] == ["morpho_steakhouse"]


def test_below_median_rule_is_not_inert(tmp_path: Path) -> None:
    """Caps are resolved when the caller omits them.

    Without them the rule silently reports nothing and the book LOOKS compliant —
    the failure mode this project calls fail-OPEN.
    """
    doc = _write(tmp_path)
    flagged = {r["protocol"] for r in doc["below_median_cap"]}
    assert "morpho_steakhouse" in flagged      # 3.47 % below median, yet holds 40 %


def test_tier_caps_come_from_riskconfig() -> None:
    caps = _resolve_tier_caps(["morpho_steakhouse", "maple"])
    from spa_core.risk.policy import RiskConfig
    cfg = RiskConfig()
    assert set(caps.values()) <= {cfg.max_concentration_t1, cfg.max_concentration_t2}


def test_idle_cash_above_the_buffer_is_reported(tmp_path: Path) -> None:
    """Idle cash the allocator COULD have deployed is still the loud alarm.

    DELIBERATE CHANGE (инв. 16, Y2 2026-08-05, justified): before the Y2
    attribution this asserted UNEXPLAINED_CASH on a book with NO TVL provenance
    at all — i.e. the old code called cash "unexplained" without knowing whether
    the idle protocols were even fundable (ADR-053 freezes pools without live
    TVL). That verdict was a guess in alarm's clothing. The check is STRENGTHENED,
    not weakened: with live TVL supplied the same book must still scream
    UNEXPLAINED_CASH — and now also name the fundable headroom it is ignoring —
    while the no-provenance case is pinned separately below as fail-closed
    ``attribution_incomplete`` (never a silent "explained").
    """
    doc = _write(tmp_path, current_positions={"maple": 20_000.0},
                 tvl_sources={k: "live" for k in APY})
    assert doc["cash"]["excess_pct"] == pytest.approx(75.0)
    assert doc["cash"]["status"] == "UNEXPLAINED_CASH"
    kinds = {c["kind"]: c for c in doc["cash"]["components"]}
    assert kinds["unexplained_deployable"]["usd"] > 0


def test_unverifiable_tvl_makes_attribution_incomplete_not_explained(tmp_path: Path) -> None:
    """No TVL provenance ⇒ UNCHECKED component, never zero (fail-closed, task Y2 §3)."""
    doc = _write(tmp_path, current_positions={"maple": 20_000.0})   # no tvl map, no snapshot
    assert doc["cash"]["status"] == "attribution_incomplete"
    assert "tvl_provenance_unavailable" in doc["cash"]["unchecked"]
    assert doc["cash"]["unexplained_pct"] is None                   # unknown ≠ 0
    assert any(c.get("status") == "UNCHECKED" for c in doc["cash"]["components"])


def test_tvl_that_cleared_the_floor_on_a_literal_is_surfaced(tmp_path: Path) -> None:
    """Only a DECLARED live TVL counts; a bare number is a literal.

    Фикстура правлена 2026-08-09 (обоснование обязательно, `CLAUDE.md` §16;
    запись — `docs/journal/2026-W32.md`). Смысл теста не изменился: у `maple`
    настоящий замер, у `morpho_steakhouse` — литерал. Изменилось то, ЧЕМ этот
    замер объявляется.

    Прежняя фикстура опиралась на посылку «всё, что лежит в снимке оркестратора,
    — настоящий TVL». Посылка неверна, и это записано в самом аллокаторе
    (`allocator.py:920`): «оркестратор отдаёт то, что дал адаптер, а 11 адаптеров
    отдают захардкоженную константу `TVL_USD`». То есть старая фикстура выражала
    ровно тот дефект, который закрыт 09.08: число без объявления засчитывалось
    наблюдением.

    Проверка НЕ ослаблена — она стала точнее: теперь `maple` проходит потому, что
    провенанс объявлен, а не потому, что запись просто существует.
    """
    (tmp_path / "adapter_orchestrator_status.json").write_text(json.dumps(
        {"adapters": [{"protocol": "maple", "tvl_usd": 2_554_487_183.0,
                       "tvl_source": "live"}]}), encoding="utf-8")
    doc = _write(tmp_path)
    unsound = doc["decision_shadow"]["evidence"]["tvl_unevidenced_in_target"]
    assert "morpho_steakhouse" in unsound and "maple" not in unsound


# ── history derived from trades.json ────────────────────────────────────────


def _trade(ts: str, frm: dict, to: dict, delta: float) -> dict:
    return {"type": "rebalance", "ts": ts, "from_allocation": frm,
            "to_allocation": to, "delta_abs": delta}


def test_history_counts_only_the_last_seven_days_of_turnover() -> None:
    hist = _history_from_trades([
        _trade("2026-07-01T00:00:00+00:00", {}, {}, 50_000.0),   # old, excluded
        _trade("2026-07-30T00:00:00+00:00", {}, {}, 5_000.0),
        _trade("2026-08-01T00:00:00+00:00", {"a": 10.0}, {"b": 10.0}, 3_000.0),
    ], NOW)
    assert hist["turnover_last_week_usd"] == pytest.approx(8_000.0)
    assert hist["days_since_last_act"] == pytest.approx(1.5)
    assert hist["last_move_legs"] == {"a": -10.0, "b": 10.0}


def test_history_is_empty_without_trades() -> None:
    hist = _history_from_trades([], NOW)
    assert hist["days_since_last_act"] is None
    assert hist["turnover_last_week_usd"] == 0.0


def test_position_age_is_measured_from_the_last_increase() -> None:
    ages = _position_ages([
        _trade("2026-07-20T12:00:00+00:00", {"a": 0.0}, {"a": 100.0}, 100.0),
        _trade("2026-08-01T12:00:00+00:00", {"a": 100.0}, {"a": 300.0}, 200.0),
    ], {"a": 300.0}, NOW)
    assert ages["a"] == pytest.approx(1.0)   # the most recent increase, not the entry


def test_malformed_trade_rows_are_skipped_not_fatal() -> None:
    hist = _history_from_trades(
        ["junk", {"type": "rebalance", "ts": "not-a-date"}, None], NOW)  # type: ignore[list-item]
    assert hist["days_since_last_act"] is None
