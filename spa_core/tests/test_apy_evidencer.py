# FROZEN-DATE-OK: injected-clock — единственный якорь времени это NOW, он передаётся
# в run(now=)/level_for(now=), а все отметки строк ВЫЧИСЛЯЮТСЯ из него (NOW - timedelta).
# Обе стороны закреплены одним значением, календарь на вердикт не влияет.
"""APY Evidencer: уровень доказательности каждому записанному числу доходности.

# LLM_FORBIDDEN

ADR-YL-006: «No APY may be stated, displayed, or recorded without an explicit
evidence level». Тесты сторожат ГРАНИЦЫ этого правила и — отдельно — третий
исход: «не измерено» никогда не схлопывается в L0. «Не наблюдено» и «судить
нечем» — разные вещи, и путать их значит выдавать отказ за факт.

Все входы во временных файлах: живой `data/` не читается и не пишется.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from spa_core.agents import apy_evidencer as ae
from spa_core.agents.apy_evidencer import L0, L1, L2, UNCHECKED, ApyEvidencer, level_for

NOW = datetime(2030, 6, 1, 12, 0, tzinfo=timezone.utc)


def _row(**kw):
    base = {
        "protocol": "aave_v3",
        "apy_pct": 4.5,
        "apy_source": "live",
        "last_updated": (NOW - timedelta(hours=1)).isoformat(),
    }
    base.update(kw)
    return base


def _ranking(tmp_path, rows, name="apy_ranking.json"):
    p = tmp_path / name
    p.write_text(json.dumps({"generated_at": NOW.isoformat(), "by_apy": rows}),
                 encoding="utf-8")
    return p


# ── уровни ───────────────────────────────────────────────────────────────
def test_observed_fresh_and_sane_is_l2():
    assert level_for(_row(), NOW)[0] == L2


def test_l2_is_the_ceiling_provenance_can_reach():
    """Выше L2 провенанс не поднимает НИКОГДА: L3 — наш трек, L4+ — реальный капитал."""
    for hours in (0, 1, 35):
        lvl, _ = level_for(_row(last_updated=(NOW - timedelta(hours=hours)).isoformat()), NOW)
        assert lvl == L2


def test_observed_but_stale_is_l1():
    lvl, why = level_for(_row(last_updated=(NOW - timedelta(hours=48)).isoformat()), NOW)
    assert lvl == L1 and "старше окна" in why


@pytest.mark.parametrize("hours,expect", [(35.9, L2), (36.1, L1)])
def test_the_freshness_boundary_is_where_the_documented_window_says(hours, expect):
    assert level_for(_row(last_updated=(NOW - timedelta(hours=hours)).isoformat()), NOW)[0] == expect


@pytest.mark.parametrize("src", ["fallback", "unchecked", "fallback_over_observed", "live_ish"])
def test_anything_not_observed_is_l0(src):
    """Незнакомый источник тоже L0: доверие по умолчанию не выдаётся."""
    lvl, why = level_for(_row(apy_source=src), NOW)
    assert lvl == L0 and "не наблюдено" in why


def test_the_2026_08_29_shape_top_of_ranking_is_l0():
    """Положительный контроль: самое высокое число ранжирования было литералом."""
    lvl, _ = level_for(_row(protocol="pendle_yt_susde", apy_pct=14.0,
                            apy_source="fallback", last_updated=None), NOW)
    assert lvl == L0, "литерал 14% обязан быть нецитируемым"


# ── третий исход: «не измерено» ≠ «не наблюдено» ─────────────────────────
def test_missing_provenance_is_unchecked_not_l0():
    """Молчание о провенансе — не то же самое, что «источник это литерал»."""
    lvl, why = level_for(_row(apy_source=None), NOW)
    assert lvl == UNCHECKED and "не объявлен" in why


def test_unparseable_timestamp_on_an_observation_is_unchecked():
    assert level_for(_row(last_updated="вчера"), NOW)[0] == UNCHECKED


def test_timestamp_from_the_future_is_unchecked_not_fresh():
    lvl, why = level_for(_row(last_updated=(NOW + timedelta(hours=5)).isoformat()), NOW)
    assert lvl == UNCHECKED and "будущего" in why


@pytest.mark.parametrize("apy", [0.0, -1.0, 250.0])
def test_observation_outside_the_sanity_band_is_unchecked(apy):
    assert level_for(_row(apy_pct=apy), NOW)[0] == UNCHECKED


@pytest.mark.parametrize("apy", [None, "4.5", float("nan"), float("inf"), True])
def test_non_numeric_apy_is_unchecked(apy):
    assert level_for(_row(apy_pct=apy), NOW)[0] == UNCHECKED


def test_row_without_a_protocol_is_unchecked():
    assert level_for(_row(protocol=""), NOW)[0] == UNCHECKED


# ── отчёт ────────────────────────────────────────────────────────────────
def test_report_counts_and_quotable_share(tmp_path):
    rows = [_row(protocol="a"), _row(protocol="b"),
            _row(protocol="c", apy_source="fallback"),
            _row(protocol="d", last_updated=(NOW - timedelta(hours=99)).isoformat())]
    rep = ApyEvidencer(ranking_path=_ranking(tmp_path, rows)).run(now=NOW)
    assert rep.counts == {L0: 1, L1: 1, L2: 2, UNCHECKED: 0}
    assert rep.quotable_pct == 50.0, "показывать можно только L2"


def test_missing_ranking_is_unchecked_never_clean(tmp_path):
    rep = ApyEvidencer(ranking_path=tmp_path / "нет.json").run(now=NOW)
    assert rep.counts[UNCHECKED] == 1 and rep.counts[L2] == 0
    assert rep.quotable_pct is None, "доли не бывает там, где нечего делить"


def test_malformed_ranking_document_is_unchecked(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text('["не объект"]', encoding="utf-8")
    assert ApyEvidencer(ranking_path=p).run(now=NOW).counts[UNCHECKED] == 1


def test_artifact_is_written_atomically_and_reloads(tmp_path):
    ev = ApyEvidencer(ranking_path=_ranking(tmp_path, [_row()]))
    out = ev.save(ev.run(now=NOW), tmp_path / "evidence.json")
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["generated_at"] == NOW.isoformat()
    assert doc["items"][0]["level"] == L2 and doc["items"][0]["reason"]
    assert not list(tmp_path.glob("*.tmp")), "временный файл не убран за собой"


def test_exit_codes_separate_all_three_situations(tmp_path):
    """CLI ходит по РЕАЛЬНЫМ часам — значит и отметки строятся от них.

    Инъекция часов кончается на границе `main()`, и это правильно: наружу
    агент обязан судить по настоящему времени. Поэтому здесь предпочтение №2
    правила доставки — относительные отметки, а не литеральная дата.
    """
    real_now = datetime.now(timezone.utc)
    fresh = (real_now - timedelta(hours=1)).isoformat()
    clean = _ranking(tmp_path, [_row(last_updated=fresh)], "clean.json")
    dirty = _ranking(tmp_path, [_row(apy_source="fallback", last_updated=fresh)], "dirty.json")
    unk = _ranking(tmp_path, [_row(apy_source=None, last_updated=fresh)], "unk.json")
    assert ae.main(["--ranking", str(clean), "--no-write"]) == 0
    assert ae.main(["--ranking", str(dirty), "--no-write"]) == 1
    assert ae.main(["--ranking", str(unk), "--no-write"]) == 2


def test_contract_is_declared_and_llm_forbidden():
    from pathlib import Path
    assert ae.PRODUCES == ("data/apy_evidence.json",)
    assert "# LLM_FORBIDDEN" in Path(ae.__file__).read_text(encoding="utf-8")


def test_window_mirrors_the_documented_one():
    """Окно не выдумано здесь: 36 ч — ADR-060 §3, зеркалит аллокатор."""
    from spa_core.allocator import allocator as alloc
    assert ae.EVIDENCE_MAX_AGE_H == alloc._EVIDENCE_MAX_AGE_H
    assert ae.APY_SANE_MAX_PCT == alloc._LIVE_APY_MAX_DECIMAL * 100
