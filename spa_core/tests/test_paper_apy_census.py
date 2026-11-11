"""Батарея §35 ТЗ «Portfolio CIO» — ``spa_core/analytics/paper_apy_census.py``.

Каждая величина владельца проверяется в обе стороны: сцена, где производитель ЕСТЬ, величина
стои́т на поверхности владельца С ОПРЕДЕЛЕНИЕМ и слова не сталкиваются, — и сцена, где
определения нет / слово носит две величины / одна величина ходит двумя числами — с названным
звеном. Литеральных дат нет: отметки носителей строятся от одного якоря ``_NOW``, свежесть
судится относительно него же (время — вход, не часы). Сборщик отчёта — ВХОД ``reader=``:
живой зовётся ровно в тех тестах, чей предмет — он сам.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import textwrap
from typing import Any

from spa_core.analytics import paper_apy_census as PA
from spa_core.analytics.transaction_economics import UNMEASURED
from spa_core.monitoring import card_acceptance as CA

PROBE = "paper_apy_quantities_defined_and_distinct"
_NOW = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
_D = [(_NOW.date() - dt.timedelta(days=i)).isoformat() for i in range(9)][::-1]


def _iso(hours_ago: float) -> str:
    return (_NOW - dt.timedelta(hours=hours_ago)).isoformat()


def _card(tmp, body: str) -> str:
    p = tmp / "card.md"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return str(p)


_GOOD_CARD = """\
    ---
    title: x
    ---
    34. Daily Report
    что-то
    35. Paper APY cleanup
    Отдельно исправить или документировать текущий Paper APY.
    Owner должен четко видеть различие:
    Current displayed weighted APY

    <!-- источник: inbox-x.md строки 1-2 -->

    Expected Net APY

    Realized APY

    7-day realized/estimated APY

    Optimal policy-compliant APY
    Не использовать неочевидную метрику без понятного определения.


    ⸻


    36. Owner UI
    """

# ───────────────────────────── сцена каталога данных ─────────────────────────


def _record(i: int, **over) -> dict:
    r = {"schema": "shadow-hist-v2", "cycle_date": _D[i % len(_D)], "generated_at": _iso(1.0 + i),
         "book_id": "conservative", "verdict": "HOLD", "book_apy_pp": 3.905455, "target_apy_pp": 4.008985,
         "gain_pp": 0.10353, "capital_usd": 100000.0, "cost_usd": 107.8, "payback_days": 91.8,
         "legs": [], "reasons": ["gain_below_band"], "current_positions": {"aave_v3": 5000.0},
         "target_positions": {"aave_v3": 5000.0}, "gates": {"has_legs": False}}
    r.update(over)
    return r


def _records(n=3, **over) -> list:
    return [_record(i, **over) for i in range(n)]


def _bars(n=8, *, expected: Any = "same", today: float = 3.8286) -> list:
    out = []
    for i in range(n):
        b = {"date": _D[i], "open_equity": 100000.0 + i, "close_equity": 100500.0 + i,
             "equity": 100500.0 + i, "apy_today": today, "positions": {"aave_v3": 5000.0}}
        if expected == "same":
            b["apy_expected_pct"] = today
        elif expected is None:
            pass
        else:
            b["apy_expected_pct"] = expected
        out.append(b)
    return out


def _track(bars: Any = "default") -> dict:
    return {"daily": _bars() if bars == "default" else bars,
            "summary": {"end_equity": 102017.37, "total_return_pct": 2.0174}}


def _replay(net=-5.294, gross=5.3431, hours_ago=2.0) -> dict:
    return {"generated_at": _iso(hours_ago),
            "comparison": {"charged": {"net_apy_pct": {"current": net, "cio_hold": 5.4, "cio_opt": -4.8},
                                       "gross_apy_pct": {"current": gross, "cio_hold": 5.4, "cio_opt": 5.5}}}}


_SHELF_FIGURE = {"value": 4.8921, "unit": "%", "kind": "замер",
                 "source": "landing/src/data/track_snapshot.json → paper_apy_pct (= track_period.annualised_equivalent_pct)",
                 "annualised": True, "annualisation": "годовой ЭКВИВАЛЕНТ доходности за фактический период",
                 "window_days": 136.0, "metric_type": "REALIZED_PAPER_RETURN", "evidence": "paper"}


def _shelf(figure: Any = "default") -> dict:
    fig = dict(_SHELF_FIGURE) if figure == "default" else figure
    return {"measured_at": _D[-3], "published_at": _D[-2], "cadence": "weekly",
            "headline": {"apy": fig}, "books": {"conservative": {"apy": fig}}}


def _snapshot(apy=4.8614) -> dict:
    return {"generated_at": _iso(2.0), "paper_apy_pct": apy,
            "track_period": {"state": "MEASURED" if apy is not None else "UNMEASURED"}}


def _manifest(slo: dict) -> dict:
    return {"artifacts": [{"path": path, "slo_hours": h} for path, h in slo.items()]}


_DEFAULT_SLO = {f"data/{PA.RECORD_REL}": 26.0, f"data/{PA.REPLAY_REL}": 9.28}


def _scene_dir(tmp, *, records: Any = "default", track: Any = "default", replay: Any = "default",
               shelf: Any = "default", snapshot: Any = "default", manifest: Any = "default",
               doc: bool = True) -> str:
    root = tmp / "root"
    data = root / "data"
    data.mkdir(parents=True)
    (root / "architecture").mkdir()
    (root / "landing" / "src" / "data").mkdir(parents=True)
    (root / "docs" / "decisions").mkdir(parents=True)
    if records == "default":
        records = _records()
    if records is not None:
        (data / PA.RECORD_REL).write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    tr = _track() if track == "default" else track
    if tr is not None:
        (data / PA.TRACK_REL).write_text(json.dumps(tr), encoding="utf-8")
    rp = _replay() if replay == "default" else replay
    if rp is not None:
        (data / PA.REPLAY_REL).write_text(json.dumps(rp), encoding="utf-8")
    sh = _shelf() if shelf == "default" else shelf
    if sh is not None:
        (root / PA.SHELF_REL).write_text(json.dumps(sh, ensure_ascii=False), encoding="utf-8")
    sn = _snapshot() if snapshot == "default" else snapshot
    if sn is not None:
        (root / PA.SNAPSHOT_REL).write_text(json.dumps(sn), encoding="utf-8")
    man = _manifest(_DEFAULT_SLO) if manifest == "default" else manifest
    if man is not None:
        (root / PA.MANIFEST_REL).write_text(json.dumps(man), encoding="utf-8")
    if doc:
        (root / PA.DOC_REL).write_text("# ADR-953\n", encoding="utf-8")
    return str(root)


# ───────────────────────────── читатели сцены ────────────────────────────────

_RATE_DICT = {"value": 4.8614, "metric_type": "REALIZED_PAPER", "window_days": 142, "annualisation": "compound",
              "as_of": _D[-1], "source": "data/equity_curve_daily.json (evidenced bars)"}
_LIVE_LIKE_DATA = {"equity_usd": 102017.37, "apy_today_pct": 3.8286, "apy_expected_pct": 3.8286,
                   "apy_7day_avg_pct": 3.9958,
                   "books_summary": {"books": {"conservative": {"annualized_apy_pct": 4.8614,
                                                                 "annualized_apy_pct_rate": _RATE_DICT}}}}
#: Текст, повторяющий ФОРМУ живого отчёта 11.11: голые ярлыки, без рода.
_LIVE_LIKE_TEXT = ("$102,017 · +$11 за день\nAPY сегодня 3,83 % · среднее за 7 дн. 4,00 %\n"
                   "📈 APY (paper): 3,83 % (среднее за 7 дней: 4,00 %)\n"
                   "  • Conservative: $102,017 (+2.02%, ~4.9% год.)\n"
                   "  • Balanced: $99,988 (-0.01%, ~3.8% год. (paper, капитал не двигают))\n")
#: Текст, где КАЖДАЯ величина стои́т с определением (род · окно · метод) и без слова «paper».
_DEFINED_TEXT = ("APY сегодня (начисленная за день, доход ÷ NAV): 3,83 %\n"
                 "Expected Net APY (ожидание за сегодня, взвешенная по позициям за вычетом стоимости): 3,91 %\n"
                 "Realized APY (замер за период, годовой эквивалент ACT/365): 4,86 %\n"
                 "среднее за 7 дн. (начисленные дневные ставки, простое среднее): 4,00 %\n"
                 "Optimal policy-compliant APY (ожидание за сегодня, нижняя граница перебора): 4,01 %\n")


def _reader_with(text: str, data: dict | None = None):
    def read(data_dir: str, now: dt.datetime):
        return "ЗАГОЛОВОК\n" + text, "ПОДРОБНОСТИ", data if data is not None else {}, None
    return read


def _reader_failing(data_dir: str, now: dt.datetime):
    return None, None, None, "сборщик сцены отказал"


def _run(root: str, tmp, *, reader=None, card=_GOOD_CARD, now=_NOW, write=False) -> dict:
    return PA.run(root=root, card_path=_card(tmp, card), write=write, now=now,
                  reader=reader if reader is not None else _reader_with(_LIVE_LIKE_TEXT, _LIVE_LIKE_DATA))


def _codes(doc: dict) -> set:
    return {f["code"] for f in doc["findings"]}


def _sev(doc: dict, code: str) -> str | None:
    return next((f["severity"] for f in doc["findings"] if f["code"] == code), None)


# ───────────────────────────── паритет с карточкой ────────────────────────────

def test_parity_agrees_on_the_owner_section(tmp_path):
    p = PA.parity(_card(tmp_path, _GOOD_CARD))
    assert p["agrees"] is True, p["mismatches"]
    assert p["parsed"]["quantities"] == list(PA.OWNER_QUANTITIES)
    assert p["order_undercount"] == {"quantities": 0}


def test_html_comment_is_not_a_quantity(tmp_path):
    p = PA.parity(_card(tmp_path, _GOOD_CARD))
    assert all(not q.startswith("<!--") for q in p["parsed"]["quantities"])


def test_missing_see_line_is_a_mismatch(tmp_path):
    body = _GOOD_CARD.replace("Owner должен четко видеть различие:", "Owner видит:")
    p = PA.parity(_card(tmp_path, body))
    assert p["agrees"] is False and any("не объявлен" in m for m in p["mismatches"])


def test_quantity_difference_lead_and_rule_are_mismatches(tmp_path):
    p = PA.parity(_card(tmp_path, _GOOD_CARD.replace("Realized APY\n", "Realised APY\n")))
    assert any("≠ константам" in m for m in p["mismatches"])
    p = PA.parity(_card(tmp_path, _GOOD_CARD.replace("Отдельно исправить или документировать текущий Paper APY.", "x")))
    assert any("нет строки" in m for m in p["mismatches"])
    p = PA.parity(_card(tmp_path, _GOOD_CARD.replace(
        "Не использовать неочевидную метрику без понятного определения.", "Использовать что угодно.")))
    assert any("нет правила" in m for m in p["mismatches"])


def test_missing_second_boundary_is_unmeasured_not_a_count(tmp_path):
    p = PA.parity(_card(tmp_path, _GOOD_CARD.replace("36. Owner UI", "")))
    assert p["agrees"] is None and "вторая граница" in p["parsed"]["reason"]


def test_unreadable_card_is_unmeasured(tmp_path):
    p = PA.parity(str(tmp_path / "nope.md"))
    assert p["agrees"] is None and "не прочитана" in p["parsed"]["reason"]


# ───────────────────────────── определение: оценка ───────────────────────────

def test_text_grade_defined_needs_all_three_parts():
    g = PA.grade_text("APY сегодня (начисленная за день, доход ÷ NAV): 3,83 %", ("APY сегодня",))
    assert g["grade"] == "defined" and all(g["parts"].values())


def test_text_grade_partial_names_the_missing_part_and_bare_has_none():
    g = PA.grade_text("APY сегодня 3,83 %", ("APY сегодня",))
    assert g["grade"] == "partial" and g["parts"]["род"] is False and g["parts"]["окно"] is True
    g = PA.grade_text("• Conservative: $102,017 (+2.02%, ~4.9% год.)", ("год.",))
    assert g["grade"] == "bare"


def test_text_grade_judges_the_label_segment_not_the_neighbour():
    """«среднее за 7 дн.» в той же строке — слово СОСЕДНЕЙ величины, не метод этой."""
    g = PA.grade_text("APY сегодня 3,83 % · среднее за 7 дн. 4,00 %", ("APY сегодня",))
    assert g["parts"]["метод"] is False
    g7 = PA.grade_text("APY сегодня 3,83 % · среднее за 7 дн. 4,00 %", ("среднее за 7 дн",))
    assert g7["parts"]["метод"] is True and g7["parts"]["окно"] is True and g7["grade"] == "partial"


def test_text_grade_cuts_a_parenthesis_that_carries_a_percent_value():
    """«(среднее за 7 дней: 4,00 %)» после «APY (paper)» — СОСЕДНЯЯ величина: ни окно, ни метод этой."""
    g = PA.grade_text("📈 APY (paper): 3,83 % (среднее за 7 дней: 4,00 %)", ("APY (paper)",))
    assert g["parts"] == {"род": False, "окно": False, "метод": False} and g["grade"] == "bare"
    assert g["segments"] == ["APY (paper): 3,83 %"]


def test_text_grade_reads_the_arrow_continuation_and_lists_every_label_line():
    g = PA.grade_text("📈 APY (paper): 3,83 %\n   ↳ начисленная ставка за день, доход ÷ NAV\nAPY сегодня 3,83 %",
                      ("APY (paper)", "APY сегодня"))
    assert g["grade"] == "defined" and len(g["lines"]) == 2 and g["segments"][0].startswith("APY (paper)")


def test_text_grade_absent_and_unmeasured_are_distinct():
    assert PA.grade_text("ничего про ставки", ("APY сегодня",))["grade"] == "absent"
    assert PA.grade_text(None, ("APY сегодня",))["grade"] == UNMEASURED


def test_dict_grade_shelf_figure_is_defined_and_brief_is_partial():
    assert PA.grade_dict(_SHELF_FIGURE)["grade"] == "defined"
    brief = {"current_apy_pp": 3.9, "numbers_unit": "процентные пункты годовой ставки (pp, annual)"}
    g = PA.grade_dict(brief)
    assert g["grade"] == "partial" and g["parts"] == {"род": False, "окно": True, "метод": False}
    assert PA.grade_dict({"value": 1.0})["grade"] == "bare"
    assert PA.grade_dict(None)["grade"] == "absent"


# ───────────────────────────── носители и роды ───────────────────────────────

def test_every_quantity_is_produced_on_the_scene_with_its_kind(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path)
    m = doc["measured"]
    assert m["produced"] == 5 and m["declared"] == 5
    q = m["quantities"]
    assert q["Current displayed weighted APY"]["carriers"][0]["kind"] == PA.KIND_ACCRUED
    assert q["Optimal policy-compliant APY"]["carriers"][0]["kind"] == PA.KIND_LOWER_BOUND
    assert q["Realized APY"]["carriers"][0]["value"] == 4.8614


def test_third_outcome_is_read_from_bars_and_ledger(tmp_path):
    bars = _bars(expected=None)
    bars[-1]["apy_expected_pct"] = 3.8286
    doc = _run(_scene_dir(tmp_path, track=_track(bars)), tmp_path)
    v = doc["measured"]["values"]
    assert "только отсутствием ключа" in v["bar.apy_expected_pct"]["third_outcome"]
    assert "не наблюдён" in v["bar.apy_today"]["third_outcome"]
    assert "не наблюдён" in v["record.target_apy_pp"]["third_outcome"]


def test_missing_track_makes_current_unmeasured_not_absent(tmp_path):
    doc = _run(_scene_dir(tmp_path, track=None), tmp_path)
    q = doc["measured"]["quantities"]["Current displayed weighted APY"]
    assert q["carriers"][0]["state"] == UNMEASURED
    # запись ленты всё ещё несёт book_apy_pp — величина производится ею
    assert q["kind"] == "produced"
    assert any("не прочитан" in u for u in doc["unmeasured"]) is False or doc["measured"]["values"]["bar.apy_today"]["reason"]


def test_quantity_without_any_carrier_value_is_absent(tmp_path):
    doc = _run(_scene_dir(tmp_path, records=_records(target_apy_pp=None)), tmp_path)
    q = doc["measured"]["quantities"]["Optimal policy-compliant APY"]
    assert q["kind"] == "absent" and _sev(doc, "quantity_absent:Optimal policy-compliant APY") == "CRITICAL"


def test_replay_missing_makes_expected_net_rest_on_the_record(tmp_path):
    doc = _run(_scene_dir(tmp_path, replay=None), tmp_path)
    q = doc["measured"]["quantities"]["Expected Net APY"]
    assert q["carriers"][0]["state"] == UNMEASURED and q["kind"] == "produced"


def test_seven_day_period_return_is_components_only_and_named(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path)
    assert _sev(doc, "quantity_components_only:7-day realized/estimated APY") == "WARN"


# ───────────────────────────── поверхности ───────────────────────────────────

def test_live_like_report_reaches_four_quantities_and_defines_only_realized_on_the_shelf(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path)
    m = doc["measured"]
    assert m["on_owner_surface"] == 4 and m["defined"] == 1
    q = m["quantities"]
    assert q["Realized APY"]["surfaces"]["shelf"]["definition"]["grade"] == "defined"
    assert q["Realized APY"]["surfaces"]["digest"]["definition"]["grade"] == "bare"
    assert q["Expected Net APY"]["reach_surfaces"] == []
    assert q["Optimal policy-compliant APY"]["reach_surfaces"] == ["brief"]


def test_weighted_reach_is_judged_by_its_marker_not_by_the_coinciding_number(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path)
    sec = doc["measured"]["quantities"]["Current displayed weighted APY"]["surfaces"]["digest"]["secondary"]
    assert sec["coincides_with_primary"] is True and sec["reach"] is False
    text = _LIVE_LIKE_TEXT + "   ↳ ставка не наблюдается у: x · ожидание при полной наблюдаемости 4,10 %\n"
    doc2 = _run(_scene_dir(tmp_path / "b", track=_track(_bars(expected=4.1))), tmp_path / "b",
                reader=_reader_with(text, _LIVE_LIKE_DATA))
    sec2 = doc2["measured"]["quantities"]["Current displayed weighted APY"]["surfaces"]["digest"]["secondary"]
    assert sec2["reach"] is True and sec2["coincides_with_primary"] is False


def test_value_in_text_is_reported_separately_from_label_reach(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path)
    d = doc["measured"]["quantities"]["Current displayed weighted APY"]["surfaces"]["digest"]
    assert d["reach"] is True and d["value_in_text"] is True
    r = doc["measured"]["quantities"]["Realized APY"]["surfaces"]["digest"]
    assert r["value_in_text"] is True  # «~4.9% год.» — рендер в один знак


def test_defined_report_makes_every_quantity_defined(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path, reader=_reader_with(_DEFINED_TEXT, _LIVE_LIKE_DATA))
    m = doc["measured"]
    assert m["defined"] == 5, {n: q["definition_grade"] for n, q in m["quantities"].items()}
    assert "quantities_declared_vs_defined" not in _codes(doc)


def test_no_report_text_means_reach_is_unmeasured_not_false(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path, reader=_reader_failing)
    d = doc["measured"]["quantities"]["7-day realized/estimated APY"]["surfaces"]["digest"]
    assert d["reach"] is None and d["definition"]["grade"] == UNMEASURED
    assert any("не собран" in u for u in doc["unmeasured"])


def test_shelf_missing_is_unmeasured_and_named(tmp_path):
    doc = _run(_scene_dir(tmp_path, shelf=None), tmp_path)
    sh = doc["measured"]["quantities"]["Realized APY"]["surfaces"]["shelf"]
    assert sh["reach"] is None and sh["definition"]["grade"] == UNMEASURED
    assert any(PA.SHELF_REL in u for u in doc["unmeasured"])


def test_brief_is_the_real_cio_brief_and_carries_current_and_optimal(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path)
    q = doc["measured"]["quantities"]
    assert q["Current displayed weighted APY"]["surfaces"]["brief"]["value"] == 3.905455
    assert q["Optimal policy-compliant APY"]["surfaces"]["brief"]["value"] == 4.008985
    assert q["Optimal policy-compliant APY"]["surfaces"]["brief"]["definition"]["grade"] == "partial"


def test_live_reader_is_the_default_and_builds_the_real_digest_without_writing(tmp_path):
    root = _scene_dir(tmp_path)
    data = os.path.join(root, "data")
    before = sorted(os.listdir(data))
    doc = PA.run(root=root, card_path=_card(tmp_path, _GOOD_CARD), write=False, now=_NOW)
    assert sorted(os.listdir(data)) == before
    assert doc["declared"]["report_reader"].startswith("spa_core.telegram.reports.daily")
    assert doc["report"]["built"] in (True, False)


# ───────────────────────────── различимость ──────────────────────────────────

def test_paper_word_collision_is_critical_and_judged_by_segments(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path)
    c = doc["distinctness"]["collisions"]["paper"]
    assert c["collides"] is True
    assert set(c["bearers"]) == {"Current displayed weighted APY", "Realized APY"}
    assert "shelf" in c["bearers"]["Realized APY"]["surfaces"]
    assert c["bearers"]["Current displayed weighted APY"]["surfaces"] == ["digest"]
    assert _sev(doc, "one_word_two_quantities:paper") == "CRITICAL"


def test_paper_word_on_one_quantity_is_not_a_collision(tmp_path):
    text = _LIVE_LIKE_TEXT.replace("APY (paper)", "APY (начисленная)")
    doc = _run(_scene_dir(tmp_path), tmp_path, reader=_reader_with(text, _LIVE_LIKE_DATA))
    c = doc["distinctness"]["collisions"]["paper"]
    assert c["collides"] is False and list(c["bearers"]) == ["Realized APY"]
    assert _sev(doc, "one_word_one_quantity:paper") == "INFO"


def test_one_quantity_two_values_is_warn_when_unexplained_and_info_when_defined(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path)
    d = doc["distinctness"]["divergences"]
    cur = d["Current displayed weighted APY"]
    assert cur["diverges"] is True and cur["explained_by_definition"] is False
    assert abs(cur["spread_pp"] - 0.076855) < 1e-6
    assert _sev(doc, "one_quantity_two_values:Current displayed weighted APY") == "WARN"
    rl = d["Realized APY"]
    assert rl["diverges"] is True and rl["explained_by_definition"] is True
    assert _sev(doc, "one_quantity_two_values_explained:Realized APY") == "INFO"


def test_values_within_tolerance_do_not_diverge(tmp_path):
    doc = _run(_scene_dir(tmp_path, records=_records(book_apy_pp=3.8300)), tmp_path)
    d = doc["distinctness"]["divergences"]["Current displayed weighted APY"]
    assert d["diverges"] is False
    assert "one_quantity_two_values:Current displayed weighted APY" not in _codes(doc)


def test_displayed_and_weighted_coincidence_is_info(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path)
    assert _sev(doc, "displayed_and_weighted_coincide_today") == "INFO"
    doc2 = _run(_scene_dir(tmp_path / "b", track=_track(_bars(expected=4.1))), tmp_path / "b")
    assert "displayed_and_weighted_coincide_today" not in _codes(doc2)


# ───────────────────────────── свежесть и документ ───────────────────────────

def test_replay_staleness_is_judged_against_the_manifest_slo(tmp_path):
    doc = _run(_scene_dir(tmp_path, replay=_replay(hours_ago=200.0)), tmp_path)
    assert _sev(doc, "stale:replay") == "WARN"
    doc2 = _run(_scene_dir(tmp_path / "b"), tmp_path / "b")
    assert "stale:replay" not in _codes(doc2)


def test_missing_slo_is_unmeasured_not_fresh(tmp_path):
    doc = _run(_scene_dir(tmp_path, manifest=_manifest({})), tmp_path)
    assert doc["freshness"]["replay"]["fresh"] is None
    assert any("SLO" in u for u in doc["unmeasured"])


def test_formula_documentation_for_agents_only_and_missing_are_distinct(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path)
    assert _sev(doc, "formula_documented_for_agents_only") == "WARN"
    doc2 = _run(_scene_dir(tmp_path / "b", doc=False), tmp_path / "b")
    assert _sev(doc2, "formula_documentation_missing") == "WARN"
    doc3 = _run(_scene_dir(tmp_path / "c"), tmp_path / "c",
                reader=_reader_with(_LIVE_LIKE_TEXT + "формула: ADR-953\n", _LIVE_LIKE_DATA))
    assert "formula_documented_for_agents_only" not in _codes(doc3)


# ───────────────────────────── находки ───────────────────────────────────────

def test_live_like_scene_reproduces_the_six_criticals(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path)
    crit = {f["code"] for f in doc["findings"] if f["severity"] == "CRITICAL"}
    assert crit == {"quantity_without_definition:Current displayed weighted APY",
                    "quantity_not_on_owner_surface:Expected Net APY",
                    "quantity_without_definition:7-day realized/estimated APY",
                    "quantity_without_definition:Optimal policy-compliant APY",
                    "one_word_two_quantities:paper",
                    "quantities_declared_vs_defined"}
    assert doc["overall"] == "CRITICAL"


def test_definition_dropped_by_renderer_is_the_adr_488_form(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path)
    assert _sev(doc, "definition_dropped_by_renderer:Realized APY") == "WARN"
    data = json.loads(json.dumps(_LIVE_LIKE_DATA))
    del data["books_summary"]["books"]["conservative"]["annualized_apy_pct_rate"]
    doc2 = _run(_scene_dir(tmp_path / "b"), tmp_path / "b", reader=_reader_with(_LIVE_LIKE_TEXT, data))
    assert "definition_dropped_by_renderer:Realized APY" not in _codes(doc2)


def test_net_sign_differing_from_gross_is_warn_and_same_sign_is_not(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path)
    assert _sev(doc, "expected_net_sign_differs_from_gross") == "WARN"
    doc2 = _run(_scene_dir(tmp_path / "b", replay=_replay(net=4.9, gross=5.3)), tmp_path / "b")
    assert "expected_net_sign_differs_from_gross" not in _codes(doc2)


def test_unmeasured_quantities_are_not_findings(tmp_path):
    doc = _run(_scene_dir(tmp_path, records=None, track=None), tmp_path)
    q = doc["measured"]["quantities"]
    assert q["Optimal policy-compliant APY"]["kind"] == UNMEASURED
    assert not any("Optimal" in f["code"] for f in doc["findings"])
    assert any("Optimal" in u for u in doc["unmeasured"])


def test_empty_scene_is_unchecked_not_critical(tmp_path):
    root = _scene_dir(tmp_path, records=None, track=None, replay=None, shelf=None, snapshot=None)
    doc = _run(root, tmp_path, reader=_reader_failing)
    assert doc["overall"] == "UNCHECKED" and doc["counts"]["critical"] == 0


def test_qualifiers_are_warn(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path)
    assert _sev(doc, "quantity_qualifier:Expected Net APY") == "WARN"
    assert _sev(doc, "quantity_qualifier:Optimal policy-compliant APY") == "WARN"


# ───────────────────────────── run / main ────────────────────────────────────

def test_run_writes_the_artifact_atomically(tmp_path):
    root = _scene_dir(tmp_path)
    doc = _run(root, tmp_path, write=True)
    path = os.path.join(root, PA.REPORT_REL)
    assert os.path.isfile(path)
    on_disk = json.loads(open(path, encoding="utf-8").read())
    assert on_disk["schema"] == "paper_apy_census/v1" and on_disk["applied"] is False
    assert on_disk["counts"] == doc["counts"]


def test_run_no_write_leaves_no_artifact(tmp_path):
    root = _scene_dir(tmp_path)
    _run(root, tmp_path, write=False)
    assert not os.path.exists(os.path.join(root, PA.REPORT_REL))


def test_main_returns_one_on_critical_with_a_scene_reader(tmp_path, monkeypatch, capsys):
    root = _scene_dir(tmp_path)
    monkeypatch.setattr(PA.drc, "live_report_reader", _reader_with(_LIVE_LIKE_TEXT, _LIVE_LIKE_DATA))
    rc = PA.main(["--root", root, "--card", _card(tmp_path, _GOOD_CARD), "--no-write", "--now", _NOW.isoformat()])
    out = capsys.readouterr().out
    assert rc == 1 and "CRITICAL" in out and "КОЛЛИЗИЯ" in out and "Realized APY" in out


def test_main_returns_two_when_nothing_can_be_measured(tmp_path, monkeypatch, capsys):
    root = _scene_dir(tmp_path, records=None, track=None, replay=None, shelf=None, snapshot=None)
    monkeypatch.setattr(PA.drc, "live_report_reader", _reader_failing)
    rc = PA.main(["--root", root, "--card", _card(tmp_path, _GOOD_CARD), "--no-write", "--now", _NOW.isoformat()])
    assert rc == 2 and "UNCHECKED" in capsys.readouterr().out


def test_main_refuses_an_unparseable_now(tmp_path, capsys):
    rc = PA.main(["--root", str(tmp_path), "--no-write", "--now", "вчера"])
    assert rc == 2 and "НЕ ИЗМЕРЕНО" in capsys.readouterr().out


# ───────────────────────────── проба приёмки ─────────────────────────────────

def test_probe_is_registered_with_data_dir_as_input():
    assert PROBE in CA.PROBES
    assert "data_dir" in CA.probe_tree_inputs(PROBE)


def test_probe_on_the_scene_is_not_satisfied_and_names_the_quantities(tmp_path, monkeypatch):
    root = _scene_dir(tmp_path)
    monkeypatch.setattr(PA.drc, "live_report_reader", _reader_with(_LIVE_LIKE_TEXT, _LIVE_LIKE_DATA))
    verdict, why = CA.run_probe(PROBE, data_dir=os.path.join(root, "data"))
    assert verdict == CA.NOT_SATISFIED
    assert "с определением 1" in why and "Expected Net APY" in why and "paper" in why


def test_probe_satisfied_when_every_quantity_is_defined_and_words_do_not_collide(tmp_path, monkeypatch):
    shelf = _shelf({**_SHELF_FIGURE, "source": "track_snapshot.json → realised equivalent", "evidence": "measured"})
    root = _scene_dir(tmp_path, shelf=shelf, records=_records(book_apy_pp=3.8300))
    monkeypatch.setattr(PA.drc, "live_report_reader", _reader_with(_DEFINED_TEXT, _LIVE_LIKE_DATA))
    real = PA.grade_dict

    def brief_defined(fig):
        g = real(fig)
        if isinstance(fig, dict) and "current_apy_pp" in fig:
            g = {"grade": "defined", "parts": {"род": True, "окно": True, "метод": True}, "keys": ["kind", "method"]}
        return g

    monkeypatch.setattr(PA, "grade_dict", brief_defined)
    verdict, why = CA.run_probe(PROBE, data_dir=os.path.join(root, "data"))
    assert verdict == CA.SATISFIED, why


def test_probe_one_undefined_quantity_alone_is_not_satisfied(tmp_path, monkeypatch):
    """Коллизий нет, разброса нет — одна величина без определения уже не даёт satisfied."""
    shelf = _shelf({**_SHELF_FIGURE, "source": "track_snapshot.json → realised equivalent", "evidence": "measured"})
    root = _scene_dir(tmp_path, shelf=shelf, records=_records(book_apy_pp=3.8300))
    text = "\n".join(ln for ln in _DEFINED_TEXT.splitlines() if not ln.startswith("Optimal")) + "\n"
    monkeypatch.setattr(PA.drc, "live_report_reader", _reader_with(text, _LIVE_LIKE_DATA))
    verdict, why = CA.run_probe(PROBE, data_dir=os.path.join(root, "data"))
    assert verdict == CA.NOT_SATISFIED
    assert "Optimal policy-compliant APY" in why and "слово носит две величины: {}" in why


def test_probe_without_shelf_is_unmeasured_even_with_a_report(tmp_path, monkeypatch):
    root = _scene_dir(tmp_path, shelf=None)
    monkeypatch.setattr(PA.drc, "live_report_reader", _reader_with(_LIVE_LIKE_TEXT, _LIVE_LIKE_DATA))
    verdict, why = CA.run_probe(PROBE, data_dir=os.path.join(root, "data"))
    assert verdict == UNMEASURED and PA.SHELF_REL in why


def test_probe_without_track_or_report_is_unmeasured(tmp_path, monkeypatch):
    root = _scene_dir(tmp_path, track=None)
    verdict, why = CA.run_probe(PROBE, data_dir=os.path.join(root, "data"))
    assert verdict == UNMEASURED and PA.TRACK_REL in why
    monkeypatch.setattr(PA.drc, "live_report_reader", _reader_failing)
    verdict, why = CA.run_probe(PROBE, data_dir=os.path.join(_scene_dir(tmp_path / "b"), "data"))
    assert verdict == UNMEASURED and "не собран" in why


def test_probe_refuses_an_argument():
    verdict, why = CA.run_probe(f"{PROBE}:foo")
    assert verdict == UNMEASURED and "аргумент" in why


def test_probe_is_not_a_substring_check(tmp_path, monkeypatch):
    """Файлы с нужными словами, но без структуры носителей — не производители."""
    root = _scene_dir(tmp_path, records=None, track=None)
    (tmp_path / "root" / "data" / PA.RECORD_REL).write_text("book_apy_pp target_apy_pp Realized APY paper\n", encoding="utf-8")
    (tmp_path / "root" / "data" / PA.TRACK_REL).write_text("apy_today apy_expected_pct\n", encoding="utf-8")
    monkeypatch.setattr(PA.drc, "live_report_reader", _reader_with(_DEFINED_TEXT, _LIVE_LIKE_DATA))
    verdict, _ = CA.run_probe(PROBE, data_dir=os.path.join(root, "data"))
    assert verdict == UNMEASURED
