"""Турнир опирается на ДОВЕРЯЕМЫЙ реальный APY (карточка agent-tournament-trustworthy-real-apy).

Дефект, измеренный 2026-08-17 на git-версии ``data/apy_ranking.json``: читатель
турнира (`tournament_engine._load_cached_apy`) брал ``float(row["apy_pct"])`` и

  * единицу ПОДРАЗУМЕВАЛ (докстринг «percent units», файл единицу не объявлял);
  * провенанс (``apy_source``) игнорировал — литеральный fallback входил как наблюдение;
  * свежесть не проверял (отметки от 2026-06-21, то есть 57 суток);
  * правдивый ноль терял (``if proto and apy`` — 0.0 falsy).

Теперь единственный вход — `spa_core.tournament.trusted_apy`, и «нет доверяемого
числа» = ИМЕНОВАННЫЙ отказ, а не подстановка.

Время — ВХОД: ``now`` передаётся во все проверки свежести, литеральных «сегодня»
здесь нет, стенные часы на уровне модуля не читаются.
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from spa_core.adapters.apy_contract import APY_UNIT_DECIMAL, APY_UNIT_PERCENT  # noqa: E402
from spa_core.tournament import trusted_apy as ta  # noqa: E402
from spa_core.tournament.tournament_engine import TournamentEngine  # noqa: E402

# Опорный момент теста. Фиксирован ВМЕСТЕ с отметками наблюдений ниже, поэтому
# тест бессмертен: календарь может двигаться, обе стороны сравнения — нет.
_NOW = datetime(2026, 8, 17, 12, 0, 0, tzinfo=timezone.utc)


def _row(protocol="aave_v3", apy_pct=5.0, source="live", age_hours=1.0, **kw):
    row = {
        "protocol": protocol,
        "apy_pct": apy_pct,
        "apy_source": source,
        "last_updated": (_NOW - timedelta(hours=age_hours)).isoformat(),
    }
    row.update(kw)
    return row


def _snapshot(rows, unit=APY_UNIT_PERCENT, **kw):
    snap = {"by_apy": rows}
    if unit is not None:
        snap[ta.SNAPSHOT_UNIT_KEY] = unit
    snap.update(kw)
    return snap


# ─────────────────────────────────────────────────────────────────────────────
# Единица объявляется ИСТОЧНИКОМ; необъявленная — отказ целиком
# ─────────────────────────────────────────────────────────────────────────────

def test_declared_percent_unit_is_converted_exactly_once():
    res = ta.trusted_apy_map(_snapshot([_row(apy_pct=5.0)]), now=_NOW)
    assert res.trusted is True
    assert res.unit == APY_UNIT_PERCENT
    assert res.apy_pct["aave_v3"] == pytest.approx(5.0)
    assert res.apy_decimal["aave_v3"] == pytest.approx(0.05)
    assert res.refusals == []


def test_declared_decimal_unit_is_converted_exactly_once():
    res = ta.trusted_apy_map(
        _snapshot([_row(apy_pct=0.05)], unit=APY_UNIT_DECIMAL), now=_NOW)
    assert res.apy_decimal["aave_v3"] == pytest.approx(0.05)
    assert res.apy_pct["aave_v3"] == pytest.approx(5.0)


def test_undeclared_unit_refuses_the_whole_snapshot():
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: ровно состояние живого файла до этого гейта."""
    res = ta.trusted_apy_map(_snapshot([_row()], unit=None), now=_NOW)
    assert res.trusted is False
    assert res.apy_pct == {}
    assert [r["reason"] for r in res.refusals] == [ta.REFUSAL_UNDECLARED_UNIT]
    assert "never" in res.refusals[0]["detail"]


def test_typo_in_declared_unit_is_undeclared_not_a_guess():
    res = ta.trusted_apy_map(_snapshot([_row()], unit="percentt"), now=_NOW)
    assert res.trusted is False
    assert res.refusals[0]["reason"] == ta.REFUSAL_UNDECLARED_UNIT


def test_unit_is_never_inferred_from_magnitude():
    """0.8 под объявлением «percent» — это 0.8%, а не 80%. Никакой эвристики."""
    res = ta.trusted_apy_map(_snapshot([_row(apy_pct=0.8)]), now=_NOW)
    assert res.apy_decimal["aave_v3"] == pytest.approx(0.008)
    res_dec = ta.trusted_apy_map(
        _snapshot([_row(apy_pct=0.8)], unit=APY_UNIT_DECIMAL), now=_NOW)
    assert res_dec.apy_decimal["aave_v3"] == pytest.approx(0.8)


# ─────────────────────────────────────────────────────────────────────────────
# Провенанс: литерал — не наблюдение
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("source", ["fallback", "fallback_over_observed", "unchecked", None])
def test_non_observed_provenance_is_refused(source):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ mock-класса: литерал не входит как живое число."""
    res = ta.trusted_apy_map(_snapshot([_row(source=source)]), now=_NOW)
    assert res.apy_pct == {}
    assert res.refusals[0]["reason"] == ta.REFUSAL_PROVENANCE_NOT_OBSERVED
    assert "aave_v3" == res.refusals[0]["protocol"]


def test_refusal_is_named_not_dropped():
    """Отвергнутая строка обязана иметь ИМЯ и причину, а не исчезнуть."""
    res = ta.trusted_apy_map(_snapshot([
        _row(protocol="aave_v3"),
        _row(protocol="maple", source="fallback"),
        _row(protocol="euler_v2", age_hours=1000.0),
    ]), now=_NOW)
    assert sorted(res.apy_pct) == ["aave_v3"]
    by_proto = {r["protocol"]: r["reason"] for r in res.refusals}
    assert by_proto == {
        "maple": ta.REFUSAL_PROVENANCE_NOT_OBSERVED,
        "euler_v2": ta.REFUSAL_STALE,
    }
    assert ta.refusal_summary(res.refusals) == {
        ta.REFUSAL_PROVENANCE_NOT_OBSERVED: 1,
        ta.REFUSAL_STALE: 1,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Свежесть: now — ВХОД
# ─────────────────────────────────────────────────────────────────────────────

def test_fresh_observation_accepted_stale_refused():
    fresh = ta.trusted_apy_map(
        _snapshot([_row(age_hours=35.0)]), now=_NOW, max_age_hours=36.0)
    assert fresh.trusted is True
    stale = ta.trusted_apy_map(
        _snapshot([_row(age_hours=37.0)]), now=_NOW, max_age_hours=36.0)
    assert stale.trusted is False
    assert stale.refusals[0]["reason"] == ta.REFUSAL_STALE
    assert "37.0h" in stale.refusals[0]["detail"]


def test_two_month_old_literal_is_refused_positive_control():
    """Точная реконструкция замера: отметка 2026-06-21 при now 2026-08-17."""
    row = _row(source="live")
    row["last_updated"] = "2026-06-21T01:23:21.211040+00:00"
    res = ta.trusted_apy_map(_snapshot([row]), now=_NOW)
    assert res.trusted is False
    assert res.refusals[0]["reason"] == ta.REFUSAL_STALE


def test_z_suffix_and_naive_timestamps_are_parsed():
    row_z = _row(protocol="a")
    row_z["last_updated"] = (_NOW - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    row_naive = _row(protocol="b")
    row_naive["last_updated"] = (_NOW - timedelta(hours=2)).replace(tzinfo=None).isoformat()
    res = ta.trusted_apy_map(_snapshot([row_z, row_naive]), now=_NOW)
    assert sorted(res.apy_pct) == ["a", "b"]


def test_unparseable_timestamp_is_refused():
    res = ta.trusted_apy_map(_snapshot([_row(last_updated="вчера")]), now=_NOW)
    assert res.refusals[0]["reason"] == ta.REFUSAL_NO_TIMESTAMP


# ─────────────────────────────────────────────────────────────────────────────
# Правдивый ноль и диапазон
# ─────────────────────────────────────────────────────────────────────────────

def test_honest_zero_apy_survives():
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: `if proto and apy` терял правдивый 0% (points-farm)."""
    res = ta.trusted_apy_map(_snapshot([_row(protocol="points_farm", apy_pct=0.0)]), now=_NOW)
    assert res.apy_pct == {"points_farm": 0.0}
    assert res.refusals == []
    assert res.trusted is True


def test_out_of_band_apy_is_refused_not_rescaled():
    """Процент >100% — ошибка единиц, а не «сильная доходность». Отказ, не пересчёт."""
    res = ta.trusted_apy_map(_snapshot([_row(apy_pct=5000.0)]), now=_NOW)
    assert res.apy_pct == {}
    assert res.refusals[0]["reason"] == ta.REFUSAL_OUT_OF_BAND


def test_negative_apy_is_refused():
    res = ta.trusted_apy_map(_snapshot([_row(apy_pct=-3.0)]), now=_NOW)
    assert res.refusals[0]["reason"] == ta.REFUSAL_OUT_OF_BAND


# ─────────────────────────────────────────────────────────────────────────────
# Кривая форма — отказ, НИКОГДА исключение
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("snapshot", [None, [], "junk", 42])
def test_garbage_snapshot_fails_closed_without_raising(snapshot):
    res = ta.trusted_apy_map(snapshot, now=_NOW)
    assert res.trusted is False
    assert res.refusals[0]["reason"] == ta.REFUSAL_NO_SNAPSHOT


def test_rows_not_a_list_fails_closed():
    res = ta.trusted_apy_map(_snapshot("not-a-list"), now=_NOW)
    assert res.refusals[0]["reason"] == ta.REFUSAL_BAD_ROW_SHAPE


def test_bad_rows_are_refused_individually():
    res = ta.trusted_apy_map(_snapshot([_row(), "junk", {"apy_pct": 5.0}]), now=_NOW)
    assert sorted(res.apy_pct) == ["aave_v3"]
    reasons = sorted(r["reason"] for r in res.refusals)
    assert reasons == [ta.REFUSAL_BAD_ROW_SHAPE, ta.REFUSAL_NO_PROTOCOL]


def test_all_refusal_reasons_are_registered():
    """Каждая причина отказа — из объявленного набора (читается дашбордом/тестами)."""
    res = ta.trusted_apy_map(_snapshot([
        _row(protocol="a", source="fallback"),
        _row(protocol="b", age_hours=9999.0),
        _row(protocol="c", apy_pct=9999.0),
        "junk",
    ]), now=_NOW)
    for r in res.refusals:
        assert r["reason"] in ta.ALL_REFUSAL_REASONS, r


# ─────────────────────────────────────────────────────────────────────────────
# Источник объявляет единицу САМ (writer-side declaration)
# ─────────────────────────────────────────────────────────────────────────────

def test_apy_aggregator_declares_its_unit(tmp_path):
    """`save_ranking` обязан объявлять единицу — иначе читатель откажет по делу."""
    from spa_core.adapters.apy_aggregator import APYAggregator, AdapterSnapshot

    agg = APYAggregator([AdapterSnapshot(
        protocol="aave_v3", tier="T1", apy_pct=5.0, network="ethereum",
        tvl_usd=1e9, last_updated=_NOW.isoformat(), risk_score=0.1,
        apy_source="live",
    )])
    out = tmp_path / "apy_ranking.json"
    agg.save_ranking(out)
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload[ta.SNAPSHOT_UNIT_KEY] == APY_UNIT_PERCENT
    # И круг замыкается: свой же файл проходит гейт доверия.
    res = ta.trusted_apy_map(payload, now=_NOW + timedelta(hours=1))
    assert res.apy_pct == {"aave_v3": pytest.approx(5.0)}


# ─────────────────────────────────────────────────────────────────────────────
# Движок турнира ходит только через гейт
# ─────────────────────────────────────────────────────────────────────────────

def _write(path: pathlib.Path, payload) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_engine_uses_only_trusted_observations(tmp_path):
    _write(tmp_path / "apy_ranking.json", _snapshot([
        _row(protocol="aave_v3", apy_pct=5.0),
        _row(protocol="maple", apy_pct=9.0, source="fallback"),
    ]))
    eng = TournamentEngine(data_dir=tmp_path)
    res = eng.load_trusted_apy(now=_NOW)
    assert res.apy_pct == {"aave_v3": pytest.approx(5.0)}
    assert eng.last_apy_trust["trusted"] is True
    assert eng.last_apy_trust["unit"] == APY_UNIT_PERCENT
    assert eng.last_apy_trust["refusals_by_reason"] == {
        ta.REFUSAL_PROVENANCE_NOT_OBSERVED: 1}
    assert [r["protocol"] for r in eng.last_apy_refusals] == ["maple"]


def test_engine_refuses_undeclared_snapshot_and_names_it(tmp_path):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: старый формат файла ⇒ пустая карта + названная причина.

    Пустая карта — законный ОТКАЗ. Проверяется главное: движок не подставил число.
    """
    _write(tmp_path / "apy_ranking.json", _snapshot([_row(apy_pct=5.0)], unit=None))
    eng = TournamentEngine(data_dir=tmp_path)
    res = eng.load_trusted_apy(now=_NOW)
    assert res.apy_pct == {}
    assert eng.last_apy_trust["trusted"] is False
    assert ta.REFUSAL_UNDECLARED_UNIT in eng.last_apy_trust["refusals_by_reason"]


def test_engine_no_longer_reads_undeclared_fallback_sources(tmp_path):
    """Снятые запасные источники не вернулись: они не объявляют ни единицу, ни провенанс."""
    _write(tmp_path / "apy_ranking.json", _snapshot([]))
    _write(tmp_path / "adapter_orchestrator_status.json",
           {"adapters": [{"protocol": "euler_v2", "apy_pct": 42.0}]})
    _write(tmp_path / "current_positions.json",
           [{"protocol": "maple", "current_apy": 33.0}])
    eng = TournamentEngine(data_dir=tmp_path)
    assert eng._load_cached_apy() == {}


def test_missing_snapshot_file_fails_closed(tmp_path):
    eng = TournamentEngine(data_dir=tmp_path)
    res = eng.load_trusted_apy(now=_NOW)
    assert res.trusted is False
    assert res.apy_pct == {}


def test_shadow_day_names_the_untrusted_part_of_the_book(tmp_path):
    """Нулевая оценка протокола обязана быть НАЗВАНА, а не растворяться в APY стратегии."""
    _write(tmp_path / "apy_ranking.json", _snapshot([_row(protocol="aave_v3", apy_pct=5.0)]))
    _write(tmp_path / "strategy_tournament.json", {
        "shadow_active_strategies": [{
            "rank": 1, "strategy_key": "s_test", "id": "s_test",
            "allocation": {"aave_v3": 0.5, "maple": 0.5},
        }],
    })
    eng = TournamentEngine(data_dir=tmp_path)
    day = eng.update_shadow_day(date="2026-08-17")
    row = day["strategies"][0]
    assert row["untrusted_protocols"] == ["maple"]
    assert row["untrusted_weight"] == pytest.approx(0.5)
    assert row["apy_fully_trusted"] is False
    # 0.5 × 5% = 2.5% — половина книги оценена нулём, и это сказано вслух.
    assert row["annualised_apy_pct"] == pytest.approx(2.5)
    assert day["apy_input"] == "trusted_snapshot"
    assert day["apy_trust"]["trusted"] is True


def test_injected_apy_map_is_labelled_as_injected(tmp_path):
    """Поданная карта помечается «injected» — её провенанс не выдаётся за снимок."""
    _write(tmp_path / "strategy_tournament.json", {
        "shadow_active_strategies": [{
            "rank": 1, "strategy_key": "s_test", "id": "s_test",
            "allocation": {"aave_v3": 1.0},
        }],
    })
    eng = TournamentEngine(data_dir=tmp_path)
    day = eng.update_shadow_day(date="2026-08-17", apy_map={"aave_v3": 6.0})
    assert day["apy_input"] == "injected"
    assert day["apy_trust"] == {}
    assert day["strategies"][0]["apy_fully_trusted"] is True


def test_status_surfaces_apy_trust(tmp_path):
    _write(tmp_path / "apy_ranking.json", _snapshot([_row(source="fallback")]))
    eng = TournamentEngine(data_dir=tmp_path)
    status = eng.get_tournament_status()
    assert status["apy_trust"]["trusted"] is False
    assert status["apy_refusals"]
    # Два РАЗНЫХ вопроса рядом: доверие датасету и доверие APY-входу.
    assert "data_trustworthy" in status and "apy_trust" in status


def test_no_wall_clock_at_module_level():
    """Стенные часы не читаются на уровне модуля (иначе тест — бомба с часовым механизмом)."""
    source = pathlib.Path(__file__).read_text(encoding="utf-8")
    offenders = [
        line for line in source.splitlines()
        if line and not line[0].isspace() and "datetime.now" in line
    ]
    assert not offenders, offenders


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
