"""Батарея §34 ТЗ «Portfolio CIO» — ``spa_core/analytics/daily_report_census.py``.

Каждый пункт CIO-секции проверяется в обе стороны: сцена, где производитель ЕСТЬ и значение
ДОХОДИТ до отчёта (читатель сцены печатает значения), и сцена, где его нет / он неполон /
не доходит — с названным звеном. Литеральных дат нет: отметки носителей строятся от одного
якоря ``_NOW``, свежесть судится относительно него же (время — вход, не часы). Сборщик
отчёта — ВХОД ``reader=``: живой зовётся ровно в тех тестах, чей предмет — он сам.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import textwrap
from typing import Any

from spa_core.analytics import daily_report_census as DR
from spa_core.analytics.transaction_economics import UNMEASURED
from spa_core.monitoring import card_acceptance as CA

PROBE = "daily_report_carries_every_cio_item"
_NOW = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
_D = [(_NOW.date() - dt.timedelta(days=i)).isoformat() for i in range(6)][::-1]


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
    33. Portfolio KPIs
    что-то
    34. Daily Report
    Обновить SPA Daily Report.
    Сохранить существующие полезные части, но добавить CIO section.
    Пример:
    🧠 Portfolio CIO

    <!-- источник: inbox-x.md строки 1-2 -->

    Current expected net APY: 4.1%
    Optimal policy-compliant APY: 5.3%
    Yield gap: 1.2 pp

    Target allocation:
    Aave: 22%
    Pendle: 24%
    Maple: 20%
    Morpho: 19%
    Cash: 15%

    Decision: REBALANCE

    Recommended:
    Move $12,000
    Aave → Morpho

    Expected incremental return:
    7d: +$X
    30d: +$X
    90d: +$X

    Switching cost: $X
    Break-even: X days
    Expected persistence: X days

    Risk:
    before X
    after X

    Confidence: HIGH
    Если ничего делать не надо:
    Decision: KEEP

    Reason:
    No available rebalance currently exceeds required net economic threshold.


    ⸻


    35. Paper APY cleanup
    """

# ───────────────────────────── сцена каталога данных ─────────────────────────

_LEGS = [{"delta_usd": 35000.0, "direction": "increase", "protocol": "aave_v3"},
         {"delta_usd": -35000.0, "direction": "decrease", "protocol": "compound_v3"}]
_REASONS = ["gain_below_band:0.429pp<0.500pp", "payback_too_long:91.8d"]


def _record(i: int, **over) -> dict:
    r = {"schema": "shadow-hist-v2", "cycle_date": _D[i % len(_D)], "generated_at": _iso(1.0 + i),
         "decision_id": f"adr060-shadow-{_D[i % len(_D)]}", "book_id": "conservative",
         "verdict": "HOLD", "book_apy_pp": 4.011925, "target_apy_pp": 4.440525, "gain_pp": 0.4286,
         "capital_usd": 100000.0, "cost_usd": 107.8, "payback_days": 91.8,
         "turnover_usd": 55000.0, "turnover_frac": 0.55, "legs": list(_LEGS), "reasons": list(_REASONS),
         "current_positions": {"aave_v3": 5000.0, "compound_v3": 40000.0},
         "target_positions": {"aave_v3": 40000.0, "compound_v3": 5000.0},
         "gates": {"has_legs": True, "target_fully_evidenced": True}, "apy_unevidenced": [],
         "admissible_trim": {"policy": {"approved": True}}}
    r.update(over)
    return r


def _records(n=3, **over) -> list:
    return [_record(i, **over) for i in range(n)]


def _track() -> dict:
    return {"daily": [{"date": _D[i], "open_equity": 100000.0 + i, "close_equity": 100500.0 + i,
                       "equity": 100500.0 + i, "positions": {"aave_v3": 5000.0, "compound_v3": 40000.0},
                       "apy_today": 4.0} for i in range(3)]}


def _manifest(slo: dict) -> dict:
    return {"artifacts": [{"path": path, "slo_hours": h} for path, h in slo.items()]}


_DEFAULT_SLO = {f"data/{DR.RECORD_REL}": 26.0, f"data/{DR.ALERT_STATE_REL}": 26.0}


def _scene_dir(tmp, *, records: Any = "default", track: Any = "default", guard: Any = "default",
               manifest: Any = "default") -> str:
    root = tmp / "root"
    data = root / "data"
    data.mkdir(parents=True)
    (root / "architecture").mkdir()
    if records == "default":
        records = _records()
    if records is not None:
        (data / DR.RECORD_REL).write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    tr = _track() if track == "default" else track
    if tr is not None:
        (data / DR.TRACK_REL).write_text(json.dumps(tr), encoding="utf-8")
    g = {"date": _D[-1], "sent_at": _iso(2.0)} if guard == "default" else guard
    if g is not None:
        (data / DR.DIGEST_GUARD_REL).write_text(json.dumps(g), encoding="utf-8")
    man = _manifest(_DEFAULT_SLO) if manifest == "default" else manifest
    if man is not None:
        (root / DR.MANIFEST_REL).write_text(json.dumps(man), encoding="utf-8")
    return str(root)


# ───────────────────────────── читатели сцены ────────────────────────────────

def _render_all(rec: dict) -> str:
    """Текст, в котором КАЖДОЕ значение записи напечатано так, как мог бы напечатать отчёт."""
    legs = " ".join(f"{lg['protocol']} ${abs(lg['delta_usd']):,.0f}" for lg in rec["legs"])
    return (f"{DR.OWNER_SECTION_TITLE}\nCurrent: {rec['book_apy_pp']:.2f} %\nOptimal: {rec['target_apy_pp']:.3f}\n"
            f"Gap: {rec['gain_pp']:.3f} pp\nDecision: {rec['verdict']}\nMove: {legs}\n"
            f"Cost: ${rec['cost_usd']:,.2f}\nBreak-even: {rec['payback_days']:.1f} days\n"
            f"Reason: {'; '.join(rec['reasons'])}\n")


def _reader_with(text: str, data: dict | None = None):
    def read(data_dir: str, now: dt.datetime):
        return "ЗАГОЛОВОК\n" + text, "ПОДРОБНОСТИ", data or {}, None
    return read


def _reader_failing(data_dir: str, now: dt.datetime):
    return None, None, None, "сборщик сцены отказал"


_PLAIN_TEXT = "📊 отчёт за день\n$102,007 · APY 3,93 %\n"
_FULL_DATA = {"equity_usd": 102006.67, "apy_today_pct": 3.8904, "apy_7day_avg_pct": 4.1234,
              "positions": {"aave_v3": {"usd": 5000.0}, "compound_v3": {"usd": 40000.0}}}
_FULL_TEXT = "$102,007 · APY 3,89 % · 7 дн. 4,12 % · aave $5,000 · compound $40,000\n"


def _run(root: str, tmp, *, reader=None, card=_GOOD_CARD, now=_NOW, write=False) -> dict:
    return DR.run(root=root, card_path=_card(tmp, card), write=write, now=now,
                  reader=reader if reader is not None else _reader_with(_PLAIN_TEXT))


# ───────────────────────────── паритет с карточкой ────────────────────────────

def test_parity_agrees_on_the_owner_section(tmp_path):
    p = DR.parity(_card(tmp_path, _GOOD_CARD))
    assert p["agrees"] is True, p["mismatches"]
    parsed = p["parsed"]
    assert parsed["items"] == list(DR.OWNER_ITEMS) and len(parsed["items"]) == DR.OWNER_ITEMS_DECLARED
    assert parsed["horizons"] == list(DR.OWNER_HORIZONS)
    assert parsed["decision_words"] == list(DR.OWNER_DECISION_WORDS)
    assert "Cash" in parsed["allocation_rows"] and "Aave" in parsed["allocation_rows"]
    assert p["order_undercount"] is None and p["order_tail_read"] is True


def test_children_of_a_block_are_not_items(tmp_path):
    parsed = DR.owner_section_from_card(_card(tmp_path, _GOOD_CARD))
    assert "Aave" not in parsed["items"] and "Move $12" not in parsed["items"]
    assert "7d" not in parsed["items"]


def test_html_comment_is_not_an_item_nor_a_child(tmp_path):
    card = _GOOD_CARD.replace("<!-- источник: inbox-x.md строки 1-2 -->", "<!-- Fake item: 1 -->")
    card = card.replace("Cash: 15%\n", "Cash: 15%\n<!-- источник: строка 7 -->\n")
    parsed = DR.owner_section_from_card(_card(tmp_path, card))
    assert "Fake item" not in parsed["items"]
    assert not [r for r in parsed["allocation_rows"] if r.startswith("<!--")]
    assert parsed["allocation_rows"][-1] == "Cash"


def test_missing_example_word_is_a_mismatch(tmp_path):
    p = DR.parity(_card(tmp_path, _GOOD_CARD.replace("Пример:", "Образец:")))
    assert p["agrees"] is False and any("Пример:" in m for m in p["mismatches"])


def test_item_list_difference_is_a_mismatch(tmp_path):
    p = DR.parity(_card(tmp_path, _GOOD_CARD.replace("Confidence: HIGH\n", "")))
    assert p["agrees"] is False and any("пункты примера" in m for m in p["mismatches"])


def test_horizon_and_vocabulary_and_cash_differences_are_mismatches(tmp_path):
    p = DR.parity(_card(tmp_path, _GOOD_CARD.replace("90d: +$X\n", "")))
    assert any("горизонты" in m for m in p["mismatches"])
    p = DR.parity(_card(tmp_path, _GOOD_CARD.replace("Decision: KEEP", "Decision: HOLD")))
    assert any("словарь Decision" in m for m in p["mismatches"])
    p = DR.parity(_card(tmp_path, _GOOD_CARD.replace("Cash: 15%\n", "")))
    assert any("Cash" in m for m in p["mismatches"])


def test_keep_words_title_and_keep_branch_are_checked(tmp_path):
    p = DR.parity(_card(tmp_path, _GOOD_CARD.replace("Сохранить существующие полезные части", "Переписать всё")))
    assert any("Сохранить" in m for m in p["mismatches"])
    p = DR.parity(_card(tmp_path, _GOOD_CARD.replace("🧠 Portfolio CIO\n", "")))
    assert any("заголовка секции" in m for m in p["mismatches"])
    p = DR.parity(_card(tmp_path, _GOOD_CARD.replace("Если ничего делать не надо:\n", "")))
    assert any("ветки" in m for m in p["mismatches"])


def test_missing_second_boundary_is_unmeasured_not_a_count(tmp_path):
    p = DR.parity(_card(tmp_path, _GOOD_CARD.replace("35. Paper APY cleanup", "35. Другое")))
    assert p["agrees"] is None and "вторая граница" in p["parsed"]["reason"]


def test_unreadable_card_is_unmeasured(tmp_path):
    p = DR.parity(str(tmp_path / "нет.md"))
    assert p["agrees"] is None and "не прочитана" in p["parsed"]["reason"]


# ───────────────────────────── рендеры и доходимость ─────────────────────────

def test_renderings_require_three_significant_digits():
    assert DR.value_reaches(0.43, "rate", "gap 0.43 pp") is None       # две значащие — не измерено
    assert DR.value_reaches(0.4286, "rate", "gap 0.429 pp") is True
    assert DR.value_reaches(4.011925, "rate", "APY 4,01 %") is True     # RU-запись
    assert DR.value_reaches(4.011925, "rate", "APY 4.01%") is True
    assert DR.value_reaches(4.011925, "rate", "APY 4,0 %") is False


def test_money_renderings_cover_thousands_separators():
    assert DR.value_reaches(55000.0, "money", "Move $55,000") is True
    assert DR.value_reaches(55000.0, "money", "перенос 55 000 $") is True
    assert DR.value_reaches(55000.0, "money", "перенос 55 тыс.") is False


def test_word_allocation_legs_and_reasons_reach():
    assert DR.value_reaches("HOLD", "word", "Decision: HOLD") is True
    assert DR.value_reaches("HOLD", "word", "Decision: KEEP") is False
    assert DR.value_reaches({"a": 40000.0, "b": 5000.0}, "allocation", "a $40,000 b $5,000") is True
    assert DR.value_reaches({"a": 40000.0, "b": 5000.0}, "allocation", "a $40,000") is False
    assert DR.value_reaches({}, "allocation", "x") is None
    assert DR.value_reaches(_LEGS, "legs", "aave_v3 $35,000 compound_v3 $35,000") is True
    assert DR.value_reaches(_LEGS, "legs", "aave_v3 $35,000") is False
    assert DR.value_reaches(_REASONS, "reasons", "; ".join(_REASONS)) is True
    assert DR.value_reaches(_REASONS, "reasons", _REASONS[0]) is False
    assert DR.value_reaches([], "reasons", "x") is None


# ───────────────────────────── пункты: производитель ─────────────────────────

def _items(root: str, text: str | None, brief=None) -> dict:
    carriers = DR.load_carriers(os.path.join(root, "data"), root)
    return DR.measure_items(carriers, text, brief)


def test_eight_items_are_produced_two_components_only_three_absent(tmp_path):
    it = _items(_scene_dir(tmp_path), _PLAIN_TEXT)
    assert it["declared"] == 13 and it["produced"] == 8
    assert it["tally"] == {"produced": 8, "components_only": 2, "absent": 3, UNMEASURED: 0}
    rows = it["items"]
    assert rows["Target allocation"]["kind"] == "components_only"
    assert rows["Expected incremental return"]["kind"] == "components_only"
    for name in ("Expected persistence", "Risk", "Confidence"):
        assert rows[name]["kind"] == "absent" and rows[name]["reason"]
    assert rows["Switching cost"]["carrier"] == f"{DR.RECORD_REL}: cost_usd"
    assert rows["Reason"]["value"] == _REASONS


def test_third_outcome_is_read_from_the_ledger_not_assumed(tmp_path):
    recs = _records(3) + [_record(3, payback_days=None)]
    rows = _items(_scene_dir(tmp_path, records=recs), _PLAIN_TEXT)["items"]
    assert rows["Break-even"]["third_outcome"].startswith("наблюдён")
    assert rows["Break-even"]["ledger"]["null_rows"] == 1
    assert rows["Switching cost"]["third_outcome"].startswith("не наблюдён")
    old = {k: v for k, v in _record(0).items() if k != "cost_usd"}
    rows = _items(_scene_dir(tmp_path / "b", records=_records(2) + [old]), _PLAIN_TEXT)["items"]
    assert rows["Switching cost"]["third_outcome"].startswith("только отсутствием")


def test_field_without_any_value_in_the_ledger_is_absent(tmp_path):
    rows = _items(_scene_dir(tmp_path, records=_records(3, payback_days=None)), _PLAIN_TEXT)["items"]
    assert rows["Break-even"]["kind"] == "absent" and "ни в одной из 3" in rows["Break-even"]["reason"]


def test_decision_vocabulary_is_compared_with_the_owner_words(tmp_path):
    rows = _items(_scene_dir(tmp_path), _PLAIN_TEXT)["items"]
    assert rows["Decision"]["vocabulary"] == {"owner": ["REBALANCE", "KEEP"], "ledger": ["HOLD"], "agrees": False}
    rows = _items(_scene_dir(tmp_path / "b", records=_records(2, verdict="KEEP")), _PLAIN_TEXT)["items"]
    assert rows["Decision"]["vocabulary"]["agrees"] is True


def test_empty_ledger_makes_every_item_unmeasured(tmp_path):
    it = _items(_scene_dir(tmp_path, records=None), _PLAIN_TEXT)
    assert it["tally"][UNMEASURED] == 13 and it["produced"] == 0
    assert all("не прочитана" in r["reason"] for r in it["items"].values())


# ───────────────────────────── пункты: читатель-владелец ─────────────────────

def test_values_printed_by_the_reader_reach_the_report(tmp_path):
    rec = _record(0)
    it = _items(_scene_dir(tmp_path), _render_all(rec))
    assert it["reach_report"] == 8 and it["section_title_in_report"] is True
    assert all(it["items"][n]["report_reach"] is True
               for n, r in it["items"].items() if r["kind"] == "produced")


def test_values_not_printed_do_not_reach_and_section_is_absent(tmp_path):
    it = _items(_scene_dir(tmp_path), _PLAIN_TEXT)
    assert it["reach_report"] == 0 and it["section_title_in_report"] is False
    assert all(r["report_reach"] is False for r in it["items"].values() if r["kind"] == "produced")
    assert it["items"]["Target allocation"]["report_reach"] is None   # нечему доходить


def test_no_report_text_means_reach_is_unmeasured_not_false(tmp_path):
    it = _items(_scene_dir(tmp_path), None)
    assert it["report_built"] is False and it["section_title_in_report"] is None
    assert all(r["report_reach"] is None for r in it["items"].values())


def test_dashboard_brief_reach_is_measured_with_the_real_cio_brief(tmp_path):
    root = _scene_dir(tmp_path)
    carriers = DR.load_carriers(os.path.join(root, "data"), root)
    brief, why = DR.brief_for(carriers["records"])
    assert why is None and brief["available"] is True
    rows = DR.measure_items(carriers, _PLAIN_TEXT, brief)["items"]
    for name in ("Current expected net APY", "Optimal policy-compliant APY", "Yield gap", "Decision", "Reason",
                 "Recommended"):
        assert rows[name]["brief_reach"] is True, name
    for name in ("Switching cost", "Break-even", "Target allocation"):
        assert rows[name]["brief_reach"] is None, name          # слой дашборда их не несёт
    assert DR.measure_items(carriers, _PLAIN_TEXT, brief)["reach_dashboard"] == 6
    assert DR.measure_items(carriers, _PLAIN_TEXT, None)["reach_dashboard"] == 0


def test_brief_reach_for_legs_requires_names_and_amounts():
    spec = DR.ITEM_SPEC["Recommended"]
    assert DR._brief_reach(spec, _LEGS, {"available": True, "where": "+aave_v3 ($35,000), −compound_v3 ($35,000)"}) is True
    assert DR._brief_reach(spec, _LEGS, {"available": True, "where": "+aave_v3, −compound_v3"}) is False
    assert DR._brief_reach(spec, _LEGS, {"available": False}) is None
    assert DR._brief_reach(DR.ITEM_SPEC["Yield gap"], 0.4286, {"available": True, "yield_gap_pp": 0.4286}) is True
    assert DR._brief_reach(DR.ITEM_SPEC["Yield gap"], 0.4286, {"available": True, "yield_gap_pp": None}) is False


def test_live_reader_is_the_default_and_builds_the_real_digest_without_writing(tmp_path):
    root = _scene_dir(tmp_path)
    data = os.path.join(root, "data")
    before = sorted(os.listdir(data))
    guard_before = (tmp_path / "root" / "data" / DR.DIGEST_GUARD_REL).read_text(encoding="utf-8")
    doc = DR.run(root=root, card_path=_card(tmp_path, _GOOD_CARD), write=False, now=_NOW)
    assert doc["report"]["built"] is True and doc["report"]["details_chars"]
    assert doc["items"]["section_title_in_report"] is False and doc["items"]["reach_report"] == 0
    assert sorted(os.listdir(data)) == before
    assert (tmp_path / "root" / "data" / DR.DIGEST_GUARD_REL).read_text(encoding="utf-8") == guard_before


def test_failing_reader_is_unmeasured_not_a_finding(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path, reader=_reader_failing)
    assert doc["report"]["built"] is False
    assert any("отчёт владельцу не собран" in u for u in doc["unmeasured"])
    assert not [f for f in doc["findings"] if f["code"].startswith("item_not_in_report")]
    assert not [f for f in doc["findings"] if f["code"] == "cio_section_absent_from_daily_report"]


# ───────────────────────────── существующие части ────────────────────────────

def test_preserved_parts_present_when_values_reach():
    pr = DR.measure_preserved(_FULL_DATA, _FULL_TEXT)
    assert pr["all_reach"] is True and all(p["kind"] == "produced" for p in pr["parts"].values())


def test_preserved_part_missing_is_named(tmp_path):
    data = dict(_FULL_DATA)
    data.pop("apy_7day_avg_pct")
    pr = DR.measure_preserved(data, _FULL_TEXT)
    assert pr["parts"]["apy_7day_avg_pct"]["kind"] == "absent" and pr["all_reach"] is False
    doc = _run(_scene_dir(tmp_path), tmp_path, reader=_reader_with(_FULL_TEXT, data))
    f = next(f for f in doc["findings"] if f["code"] == "preserved_parts_missing")
    assert f["severity"] == "WARN" and "apy_7day_avg_pct" in f["message"]


def test_preserved_parts_without_report_are_unmeasured():
    pr = DR.measure_preserved(None, None)
    assert all(p["kind"] == UNMEASURED for p in pr["parts"].values())


def test_report_without_any_track_number_is_unmeasured_not_missing_parts(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path, reader=_reader_with(_PLAIN_TEXT, {}))
    assert "preserved_parts_missing" not in {f["code"] for f in doc["findings"]}
    assert any("без единого числа трека" in u for u in doc["unmeasured"])


# ───────────────────────────── свежесть ──────────────────────────────────────

def test_record_freshness_is_judged_against_the_manifest_slo(tmp_path):
    doc = _run(_scene_dir(tmp_path, records=_records(1, generated_at=_iso(40.0))), tmp_path)
    f = next(f for f in doc["findings"] if f["code"] == "stale:record")
    assert f["severity"] == "WARN" and "26.0" in f["message"]
    doc = _run(_scene_dir(tmp_path / "b"), tmp_path / "b")
    assert not [f for f in doc["findings"] if f["code"].startswith("stale:")]


def test_missing_slo_is_unmeasured_not_fresh(tmp_path):
    root = _scene_dir(tmp_path, manifest=_manifest({f"data/{DR.RECORD_REL}": 26.0}))
    doc = _run(root, tmp_path)
    assert any("отправка утреннего отчёта" in u and "не объявлен" in u for u in doc["unmeasured"])
    assert not [f for f in doc["findings"] if f["code"] == "stale:digest_sent"]


# ───────────────────────────── находки ───────────────────────────────────────

def test_section_absent_and_items_not_in_report_are_critical_and_name_the_dashboard(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path)
    codes = {f["code"]: f for f in doc["findings"]}
    assert codes["cio_section_absent_from_daily_report"]["severity"] == "CRITICAL"
    assert "до дашборда (/api/live/books/brief, ADR-488) — 6" in codes["cio_section_absent_from_daily_report"]["message"]
    f = codes["item_not_in_report:Yield gap"]
    assert f["severity"] == "CRITICAL" and "форма ADR-808" in f["message"]
    assert "форма ADR-808" not in codes["item_not_in_report:Switching cost"]["message"]
    assert codes["item_components_only:Target allocation"]["severity"] == "CRITICAL"
    assert codes["item_absent:Confidence"]["severity"] == "CRITICAL"
    s = codes["cio_items_declared_vs_reaching"]
    assert "производится 8" in s["message"] and "доходит 0" in s["message"]
    assert "«Expected persistence»→absent" in s["message"] and "«Target allocation»→components_only" in s["message"]
    assert "«Yield gap»→produced" in s["message"]


def test_items_that_reach_are_info_and_the_summary_names_only_the_rest(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path, reader=_reader_with(_render_all(_record(0))))
    codes = {f["code"]: f for f in doc["findings"]}
    assert codes["item_reaches_report:Yield gap"]["severity"] == "INFO"
    assert "cio_section_absent_from_daily_report" not in codes
    s = codes["cio_items_declared_vs_reaching"]
    assert "доходит 8" in s["message"] and "«Yield gap»" not in s["message"]
    assert "«Risk»→absent" in s["message"]


def test_qualifier_and_vocabulary_are_warn(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path)
    codes = {f["code"]: f["severity"] for f in doc["findings"]}
    assert codes["item_qualifier:Current expected net APY"] == "WARN"
    assert codes["item_qualifier:Optimal policy-compliant APY"] == "WARN"
    assert codes["decision_vocabulary_differs:Decision"] == "WARN"
    doc = _run(_scene_dir(tmp_path / "b", records=_records(2, verdict="KEEP")), tmp_path / "b")
    assert "decision_vocabulary_differs:Decision" not in {f["code"] for f in doc["findings"]}


def test_low_precision_value_is_unmeasured_reach_not_a_finding(tmp_path):
    doc = _run(_scene_dir(tmp_path, records=_records(2, gain_pp=0.43)), tmp_path)
    assert any("доходимость пункта «Yield gap»" in u for u in doc["unmeasured"])
    assert "item_not_in_report:Yield gap" not in {f["code"] for f in doc["findings"]}


def test_unmeasured_items_are_not_findings(tmp_path):
    doc = _run(_scene_dir(tmp_path, records=None), tmp_path)
    assert not [f for f in doc["findings"] if f["code"].startswith("item_")]
    assert any("пункт «Yield gap»" in u for u in doc["unmeasured"])
    assert doc["counts"]["critical"] == 0


# ───────────────────────────── run / main ────────────────────────────────────

def test_run_writes_the_artifact_atomically_and_reports_the_live_shape(tmp_path):
    root = _scene_dir(tmp_path)
    doc = _run(root, tmp_path, write=True)
    assert doc["overall"] == "CRITICAL" and doc["applied"] is False
    assert doc["items"]["declared"] == 13 and doc["items"]["produced"] == 8 and doc["items"]["reach_report"] == 0
    assert doc["carriers_read"]["records"] is True and doc["carriers_read"]["digest_guard"] is True
    saved = json.loads((tmp_path / "root" / DR.REPORT_REL).read_text(encoding="utf-8"))
    assert saved["schema"] == "daily_report_census/v1" and saved["generated_at"] == _NOW.isoformat()


def test_run_no_write_leaves_no_artifact(tmp_path):
    _run(_scene_dir(tmp_path), tmp_path, write=False)
    assert not (tmp_path / "root" / DR.REPORT_REL).exists()


def test_main_returns_one_on_critical_with_the_live_reader(tmp_path, capsys):
    rc = DR.main(["--root", _scene_dir(tmp_path), "--card", _card(tmp_path, _GOOD_CARD), "--no-write",
                  "--now", _NOW.isoformat()])
    out = capsys.readouterr().out
    assert rc == 1 and "производится 8" in out and "паритет с карточкой: СОВПАЛ" in out
    for name in DR.OWNER_ITEMS:
        assert f"«{name}»:" in out


def test_main_returns_two_when_nothing_can_be_measured(tmp_path, capsys):
    root = tmp_path / "root"
    (root / "data").mkdir(parents=True)
    rc = DR.main(["--root", str(root), "--card", _card(tmp_path, _GOOD_CARD), "--no-write",
                  "--now", _NOW.isoformat()])
    assert rc == 2 and "[НЕ ИЗМЕРЕНО]" in capsys.readouterr().out


def test_main_refuses_an_unparseable_now(tmp_path, capsys):
    rc = DR.main(["--root", _scene_dir(tmp_path), "--no-write", "--now", "вчера"])
    assert rc == 2 and "НЕ ИЗМЕРЕНО" in capsys.readouterr().out


# ───────────────────────────── проба приёмки ─────────────────────────────────

def test_probe_is_registered_with_data_dir_as_input():
    assert PROBE in CA.PROBES
    assert "data_dir" in CA.probe_tree_inputs(PROBE)


def test_probe_on_the_scene_is_not_satisfied_and_names_the_items(tmp_path):
    root = _scene_dir(tmp_path)
    verdict, why = CA.run_probe(PROBE, data_dir=os.path.join(root, "data"))
    assert verdict == CA.NOT_SATISFIED
    assert "производится 8" in why and "доходит 0" in why and "Confidence" in why and "Yield gap" in why


def test_probe_satisfied_only_when_every_item_is_produced_and_reaches(tmp_path, monkeypatch):
    root = _scene_dir(tmp_path)
    real = DR.measure_items

    def all_reach(carriers, text, brief):
        doc = real(carriers, text, brief)
        for r in doc["items"].values():
            r["kind"] = "produced"
            r["report_reach"] = True
        doc["produced"] = doc["reach_report"] = len(doc["items"])
        doc["reach_report_names"] = list(doc["items"])
        return doc

    monkeypatch.setattr(DR, "measure_items", all_reach)
    verdict, why = CA.run_probe(PROBE, data_dir=os.path.join(root, "data"))
    assert verdict == CA.SATISFIED, why


def test_probe_unmeasured_reach_is_unmeasured_not_a_verdict(tmp_path):
    root = _scene_dir(tmp_path, records=_records(2, gain_pp=0.43))
    verdict, why = CA.run_probe(PROBE, data_dir=os.path.join(root, "data"))
    assert verdict == UNMEASURED and "Yield gap" in why


def test_probe_without_records_or_report_is_unmeasured(tmp_path, monkeypatch):
    root = _scene_dir(tmp_path, records=None)
    verdict, why = CA.run_probe(PROBE, data_dir=os.path.join(root, "data"))
    assert verdict == UNMEASURED and "не прочитана" in why
    monkeypatch.setattr(DR, "live_report_reader", _reader_failing)
    verdict, why = CA.run_probe(PROBE, data_dir=os.path.join(_scene_dir(tmp_path / "b"), "data"))
    assert verdict == UNMEASURED and "не собран" in why


def test_probe_refuses_an_argument():
    verdict, why = CA.run_probe(f"{PROBE}:foo")
    assert verdict == UNMEASURED and "аргумент" in why


def test_probe_is_not_a_substring_check(tmp_path):
    """Файл с нужными словами, но без структуры ленты — не производитель."""
    root = _scene_dir(tmp_path, records=None)
    (tmp_path / "root" / "data" / DR.RECORD_REL).write_text(
        "book_apy_pp target_apy_pp gain_pp verdict HOLD 🧠 Portfolio CIO\n", encoding="utf-8")
    verdict, why = CA.run_probe(PROBE, data_dir=os.path.join(root, "data"))
    assert verdict == UNMEASURED
