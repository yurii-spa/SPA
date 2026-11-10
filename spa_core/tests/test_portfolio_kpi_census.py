"""Батарея §33 ТЗ «Portfolio CIO» — ``spa_core/analytics/portfolio_kpi_census.py``.

Каждый KPI проверяется в обе стороны: сцена, где производитель ЕСТЬ, и сцена, где его нет
или он неполон, с названным звеном. Литеральных дат нет: отметки носителей строятся от
одного якоря ``_NOW`` и свежесть судится относительно него же (время — вход, не часы).
Носители подаются артефактами сцены, а не живыми файлами; модуль поиска «оптимума» —
текстом сцены, чтобы род его ответа спрашивался у НЕГО, а не предполагался.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import textwrap
from typing import Any

from spa_core.analytics import portfolio_kpi_census as PK
from spa_core.analytics.transaction_economics import UNMEASURED
from spa_core.monitoring import card_acceptance as CA

ROOT = PK.REPO_ROOT
PROBE = "every_declared_portfolio_kpi_has_a_producer"
_NOW = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
_D = [(_NOW.date() + dt.timedelta(days=i)).isoformat() for i in range(6)]


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
    32. Ошибки, которые необходимо измерять
    что-то
    33. Portfolio KPIs
    Ввести измеримые метрики Portfolio CIO.
    Минимум:
    Gross Portfolio APY

    Net Portfolio APY

    <!-- источник: inbox-x.md строки 1-2 -->

    Realized Portfolio Yield

    Optimal Policy-Compliant APY

    Yield Gap

    Transaction Cost Drag

    Portfolio Turnover

    False Rebalance Rate

    Missed Opportunity Cost

    Forecast Accuracy

    Average Break-even

    Risk Policy Violations
    Особенно важен:
    Yield Gap
    =
    Optimal Policy-Compliant Expected APY
    -
    Current Expected APY
    Это показывает, сколько доходности теряет текущая аллокация.


    ⸻


    34. Daily Report
    """

# ───────────────────────────── сцена каталога данных ─────────────────────────


def _replay(*, fr=None, mo=None, comparison="default", stamp_hours_ago=1.0,
            with_unchecked=True, with_unpriced=True) -> dict:
    pop: dict[str, Any] = {"horizon_days": 7, "common_scored_days": 7, "days_observed": 173}
    if with_unpriced:
        pop["unpriced_per_arm"] = {"current": ["x"], "cio_opt": []}
    doc: dict[str, Any] = {"generated_at": _iso(stamp_hours_ago), "population": pop}
    if with_unchecked:
        doc["unchecked"] = 0
    doc["false_rebalances"] = fr if fr is not None else {
        "checked": 13, "unchecked": 6, "false": 12, "max_payback_days": 30.0,
        "worst": [{"cycle_date": _D[1], "payback_days": 31.8}, {"cycle_date": _D[2], "payback_days": None}]}
    doc["missed_opportunities"] = mo if mo is not None else {"checked": 7, "missed": 0, "worst": []}
    if comparison == "default":
        comparison = {
            "charged": {"gross_apy_pct": {"current": 5.3431, "cio_hold": 5.4093, "cio_opt": 5.5664},
                        "net_apy_pct": {"current": -5.294, "cio_hold": 5.4093, "cio_opt": -4.8622},
                        "opt_minus_current_pp": 0.4318},
            "observed": {"gross_apy_pct": {"current": 5.3431, "cio_hold": 5.4093, "cio_opt": 5.5664},
                         "net_apy_pct": {"current": 0.3278, "cio_hold": 5.4093, "cio_opt": 0.7596},
                         "opt_minus_current_pp": 0.4318},
        }
    if comparison is not None:
        doc["comparison"] = comparison
    return doc


def _judge_row(date: str, **over) -> dict:
    r = {"cycle_date": date, "verdict": "HOLD", "reasons": ["payback_too_long:36.3d"],
         "counterfactual": "CHECKED", "outcome": "hit", "missed_usd": 0.0}
    r.update(over)
    return r


def _judge(rows=None) -> dict:
    rows = rows if rows is not None else [
        _judge_row(_D[0]), _judge_row(_D[1], missed_usd=12.5),
        _judge_row(_D[2], counterfactual="UNCHECKED", outcome="UNCHECKED", missed_usd=None),
    ]
    return {"params": {"horizon_days": 7}, "per_verdict": rows}


def _forecast(*, scoreable=149, observed=173, sign_n=32, with_unchecked=True, stamp_hours_ago=1.0) -> dict:
    doc = {"generated_at": _iso(stamp_hours_ago),
           "population": {"days_observed": observed, "scoreable": scoreable, "horizon_days": 7},
           "sign_disagreements": [{"cycle_date": _D[0]}] * sign_n,
           "magnitude": {"n": 25, "median": 3.2916}}
    if with_unchecked:
        doc["unchecked"] = []
    return doc


def _limits(*, statuses=("PASS", "PASS", "FAIL", "PASS", "PASS"), with_skip_key=True,
            stamp_hours_ago=1.0) -> dict:
    doc = {"gate": "WARN", "checked_at": _iso(stamp_hours_ago),
           "checks": [{"id": f"DL-0{i + 1}", "status": s} for i, s in enumerate(statuses)]}
    if with_skip_key:
        doc["skip_reasons"] = []
    return doc


def _record(i: int, *, book=4.0, target=4.4, gain=None, same_positions=False, **over) -> dict:
    cur = {"a": 50.0, "b": 50.0}
    tgt = dict(cur) if same_positions else {"a": 30.0, "b": 70.0}
    r = {"cycle_date": _D[i % len(_D)], "verdict": "HOLD", "cost_usd": 1.0 + i,
         "book_apy_pp": book, "target_apy_pp": target,
         "gain_pp": round(target - book, 6) if gain is None else gain,
         "turnover_usd": 100.0 * i, "turnover_frac": 0.1 * i, "payback_days": 3.0 + i,
         "current_positions": cur, "target_positions": tgt, "apy_unevidenced": []}
    r.update(over)
    return r


def _records(n=4, **over) -> list:
    return [_record(i, **over) for i in range(n)]


def _track(n=3, turnover_on=(0,), cost_on=(0,)) -> dict:
    daily = []
    for i in range(n):
        d: dict[str, Any] = {"date": _D[i], "positions": {"a": 50.0}, "apy_expected_pct": 4.0}
        if i in turnover_on:
            d["turnover_usd"] = 100.0
        if i in cost_on:
            d["cost_usd"] = 2.5
        daily.append(d)
    return {"daily": daily}


def _snapshot(*, state="MEASURED", stamp_hours_ago=1.0, with_period=True) -> dict:
    doc: dict[str, Any] = {"generated_at": _iso(stamp_hours_ago), "paper_apy_pct": 4.87,
                           "real_track_days": 140}
    if with_period:
        doc["track_period"] = {"state": state, "method": "NAV_RATIO",
                               "period": {"days_act": 141, "evidenced_bars": 140},
                               "period_return_pct": 1.85, "annualised_equivalent_pct": 4.87,
                               "annualised_formula": "(1 + R) ^ (365 / days_act) − 1",
                               "costs_paid_usd": 50.15}
    return doc


def _shelf(*, with_reportable=True) -> dict:
    fig: dict[str, Any] = {"kind": "замер", "value": 4.87, "window_days": 121.0,
                           "source": "track_snapshot.json → paper_apy_pct"}
    if with_reportable:
        fig["reportable"] = True
    return {"headline": {"apy": fig}, "published_at": _D[0]}


_LOWER_BOUND_MODULE = '"""ЖАДНЫЙ СПРЕД — НИЖНЯЯ ГРАНИЦА, а не оптимум (ADR-859).\n\nтекст\n"""\nX = 1\n'
_OPTIMUM_MODULE = '"""Точный оптимум книги (ЛП).\n"""\nX = 1\n'


def _manifest(slo: dict) -> dict:
    return {"artifacts": [{"path": path, "slo_hours": h} for path, h in slo.items()]}


_DEFAULT_SLO = {f"data/{PK.REPLAY_REL}": 9.28, f"data/{PK.FORECAST_REL}": 9.28,
                f"data/{PK.LIMITS_REL}": 26.0, PK.SNAPSHOT_REL: 26.0}


def _scene_dir(tmp, *, replay: Any = "default", judge: Any = "default", forecast: Any = "default",
               limits: Any = "default", blocks: Any = "default", records: Any = "default",
               books: Any = "default", track: Any = "default", snapshot: Any = "default",
               shelf: Any = "default", optimum_module: Any = "default",
               manifest: Any = "default") -> str:
    root = tmp / "root"
    data = root / "data"
    data.mkdir(parents=True)
    (root / "architecture").mkdir()
    (root / "landing" / "src" / "data").mkdir(parents=True)
    (root / "spa_core" / "paper_trading").mkdir(parents=True)

    def put(rel, doc):
        if doc is None:
            return
        (data / rel).write_text(json.dumps(doc), encoding="utf-8")

    def put_jsonl(rel, rows):
        if rows is None:
            return
        (data / rel).write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    put(PK.REPLAY_REL, _replay() if replay == "default" else replay)
    put(PK.EVAL_REL, _judge() if judge == "default" else judge)
    put(PK.FORECAST_REL, _forecast() if forecast == "default" else forecast)
    put(PK.LIMITS_REL, _limits() if limits == "default" else limits)
    put(PK.BLOCKS_REL, ([{"date": _D[0], "violations": ["x"]}, {"date": _D[1], "violations": []}]
                        if blocks == "default" else blocks))
    put(PK.TRACK_REL, _track() if track == "default" else track)
    put_jsonl(PK.RECORD_REL, _records() if records == "default" else records)
    if books == "default":
        books = {"balanced": _records(5, same_positions=True, gain=0.0, target=4.0),
                 "aggressive": _records(3)}
    for book, rows in (books or {}).items():
        put_jsonl(PK.BOOK_RECORD_RELS[book], rows)
    snap = _snapshot() if snapshot == "default" else snapshot
    if snap is not None:
        (root / PK.SNAPSHOT_REL).write_text(json.dumps(snap), encoding="utf-8")
    sh = _shelf() if shelf == "default" else shelf
    if sh is not None:
        (root / PK.SHELF_REL).write_text(json.dumps(sh), encoding="utf-8")
    mod = _LOWER_BOUND_MODULE if optimum_module == "default" else optimum_module
    if mod is not None:
        (root / PK.OPTIMUM_SEARCH_REL).write_text(mod, encoding="utf-8")
    man = _manifest(_DEFAULT_SLO) if manifest == "default" else manifest
    if man is not None:
        (root / PK.MANIFEST_REL).write_text(json.dumps(man), encoding="utf-8")
    return str(root)


def _kpis(root: str, now=_NOW) -> dict:
    from spa_core.analytics import error_class_census as ecc
    carriers = PK.load_carriers(os.path.join(root, "data"), root)
    return PK.measure_kpis(carriers, ecc.load_slo(root), now)


def _kpi(root: str, name: str, now=_NOW) -> dict:
    return _kpis(root, now)["kpis"][name]


def _findings(root: str, card: str, now=_NOW) -> tuple:
    return PK._findings(PK.parity(card), _kpis(root, now))


# ───────────────────────────── паритет ───────────────────────────────────────

def test_constants_agree_with_the_real_owner_card():
    p = PK.parity(os.path.join(ROOT, PK.CARD_REL))
    assert p["parsed"]["measured"], p["parsed"].get("reason")
    assert p["agrees"] is True, p["mismatches"]
    assert len(PK.OWNER_KPIS) == PK.OWNER_KPIS_DECLARED == 12
    assert p["parsed"]["emphasis"] == PK.OWNER_EMPHASIS == "Yield Gap"
    assert p["order_undercount"] is None  # заказ G966 числа не называл


def test_measurers_cover_every_declared_kpi_and_kinds_are_closed():
    assert set(PK.MEASURERS) == set(PK.OWNER_KPIS)
    assert set(PK.FRESHNESS_CARRIER) <= set(PK.OWNER_KPIS)
    assert set(PK.PRODUCED_KINDS) <= set(PK.KPI_KINDS) and UNMEASURED in PK.KPI_KINDS


def test_parity_on_a_faithful_scene_card_skips_html_comments(tmp_path):
    p = PK.parity(_card(tmp_path, _GOOD_CARD))
    assert p["agrees"] is True, p["mismatches"]
    assert p["parsed"]["formula_terms_present"] == list(PK.OWNER_FORMULA_TERMS)


def test_parity_names_a_missing_kpi(tmp_path):
    p = PK.parity(_card(tmp_path, _GOOD_CARD.replace("Portfolio Turnover\n", "")))
    assert p["agrees"] is False
    assert any("KPI карточки" in m for m in p["mismatches"])


def test_parity_names_a_lost_floor_word(tmp_path):
    p = PK.parity(_card(tmp_path, _GOOD_CARD.replace("Минимум:\n", "Перечень:\n")))
    assert p["agrees"] is False
    assert any("Минимум" in m for m in p["mismatches"])


def test_parity_names_a_lost_emphasis(tmp_path):
    p = PK.parity(_card(tmp_path, _GOOD_CARD.replace("Особенно важен:\n    Yield Gap\n",
                                                      "Особенно важен:\n    Net Portfolio APY\n")))
    assert p["agrees"] is False
    assert any("Особенно важен" in m for m in p["mismatches"])


def test_parity_names_a_lost_formula_term(tmp_path):
    p = PK.parity(_card(tmp_path, _GOOD_CARD.replace("Current Expected APY\n", "Book APY\n")))
    assert p["agrees"] is False
    assert any("члены формулы" in m for m in p["mismatches"])


def test_missing_second_border_refuses_to_count(tmp_path):
    parsed = PK.owner_section_from_card(_card(tmp_path, _GOOD_CARD.replace("34. Daily Report", "")))
    assert parsed["measured"] is False
    assert "вторая граница" in parsed["reason"]


def test_unreadable_card_is_a_third_outcome(tmp_path):
    p = PK.parity(str(tmp_path / "nope.md"))
    assert p["agrees"] is None
    assert "не прочитана" in p["parsed"]["reason"]


# ───────────────────────────── Gross / Net Portfolio APY ─────────────────────

def test_gross_apy_from_the_replay_current_arm_is_produced(tmp_path):
    r = _kpi(_scene_dir(tmp_path), "Gross Portfolio APY")
    assert r["kind"] == "produced"
    assert r["population"] == 7
    assert r["value"] == {"charged": 5.3431, "observed": 5.3431}
    assert r["carriers"][0]["third_outcome_present"] is True


def test_net_apy_reads_the_net_key_not_the_gross_one(tmp_path):
    r = _kpi(_scene_dir(tmp_path), "Net Portfolio APY")
    assert r["kind"] == "produced"
    assert r["value"] == {"charged": -5.294, "observed": 0.3278}


def test_rate_without_replay_comparison_falls_to_the_unnamed_expectation(tmp_path):
    r = _kpi(_scene_dir(tmp_path, replay=_replay(comparison=None)), "Gross Portfolio APY")
    assert r["kind"] == "produced_under_other_name"
    assert "gross оно или net" in r["reason"]
    assert any(c["carrier"].endswith("book_apy_pp") for c in r["carriers"])


def test_rate_without_third_outcome_in_the_replay_is_named_so(tmp_path):
    r = _kpi(_scene_dir(tmp_path, replay=_replay(with_unchecked=False, with_unpriced=False)),
             "Net Portfolio APY")
    assert r["kind"] == "produced_without_third_outcome"


def test_rate_without_any_carrier_is_unmeasured(tmp_path):
    r = _kpi(_scene_dir(tmp_path, replay=None, records=None, track=None), "Gross Portfolio APY")
    assert r["kind"] == UNMEASURED
    assert "не прочитан" in r["reason"]


# ───────────────────────────── Realized Portfolio Yield ──────────────────────

def test_realized_yield_from_a_measured_snapshot_is_produced(tmp_path):
    r = _kpi(_scene_dir(tmp_path), "Realized Portfolio Yield")
    assert r["kind"] == "produced"
    assert r["population"] == 140 and r["number_kind"] == PK.NUMBER_REALISED
    assert r["value"] == 4.87
    assert r["carriers"][0]["carrier"].endswith("track_period")


def test_realized_yield_when_the_snapshot_says_not_measured_and_no_shelf_is_unmeasured(tmp_path):
    root = _scene_dir(tmp_path, snapshot=_snapshot(state="UNCHECKED"), shelf=None, track=None)
    r = _kpi(root, "Realized Portfolio Yield")
    assert r["kind"] == UNMEASURED
    assert "state='UNCHECKED'" in r["reason"]


def test_realized_yield_shelf_without_reportable_lacks_the_third_outcome(tmp_path):
    root = _scene_dir(tmp_path, snapshot=None, shelf=_shelf(with_reportable=False), track=None)
    assert _kpi(root, "Realized Portfolio Yield")["kind"] == "produced_without_third_outcome"


def test_realized_yield_from_the_raw_track_only_is_under_other_name(tmp_path):
    root = _scene_dir(tmp_path, snapshot=None, shelf=None)
    assert _kpi(root, "Realized Portfolio Yield")["kind"] == "produced_under_other_name"


def test_realized_yield_without_any_carrier_is_unmeasured(tmp_path):
    root = _scene_dir(tmp_path, snapshot=None, shelf=None, track=None)
    assert _kpi(root, "Realized Portfolio Yield")["kind"] == UNMEASURED


# ───────────────────────────── Optimal Policy-Compliant APY ──────────────────

def test_optimal_apy_is_a_lower_bound_when_the_search_module_says_so(tmp_path):
    r = _kpi(_scene_dir(tmp_path), "Optimal Policy-Compliant APY")
    assert r["kind"] == "lower_bound_of_declared"
    assert r["population"] == 4 and "НИЖНЯЯ ГРАНИЦА" in r["reason"]
    assert r["search"]["kind"] == "lower_bound_of_declared"


def test_optimal_apy_is_unmeasured_when_the_module_no_longer_declares_its_kind(tmp_path):
    r = _kpi(_scene_dir(tmp_path, optimum_module=_OPTIMUM_MODULE), "Optimal Policy-Compliant APY")
    assert r["kind"] == UNMEASURED
    assert "перемерить" in r["reason"]


def test_optimal_apy_is_unmeasured_when_the_module_is_unreadable(tmp_path):
    r = _kpi(_scene_dir(tmp_path, optimum_module=None), "Optimal Policy-Compliant APY")
    assert r["kind"] == UNMEASURED
    assert "не прочитан" in r["reason"]


def test_optimal_apy_without_record_and_replay_is_unmeasured(tmp_path):
    r = _kpi(_scene_dir(tmp_path, records=None, replay=None), "Optimal Policy-Compliant APY")
    assert r["kind"] == UNMEASURED and r["carriers"] == []


# ───────────────────────────── Yield Gap ─────────────────────────────────────

def test_yield_gap_is_a_lower_bound_and_the_formula_agrees_on_every_record(tmp_path):
    r = _kpi(_scene_dir(tmp_path), "Yield Gap")
    assert r["kind"] == "lower_bound_of_declared"
    assert r["population"] == 4
    f = r["per_book"]["conservative"]["formula"]
    assert (f["agree"], f["disagree"], f["unjudged"]) == (4, 0, 0)
    assert any("opt_minus_current_pp" in c["carrier"] for c in r["carriers"])


def test_yield_gap_formula_disagreement_is_counted_not_hidden(tmp_path):
    recs = _records(3) + [_record(3, gain=9.9)] + [_record(4, book=None, gain=0.0)]
    f = _kpi(_scene_dir(tmp_path, records=recs), "Yield Gap")["per_book"]["conservative"]["formula"]
    assert (f["agree"], f["disagree"], f["unjudged"]) == (3, 1, 1)


def test_yield_gap_self_comparison_share_is_measured_per_book(tmp_path):
    pb = _kpi(_scene_dir(tmp_path), "Yield Gap")["per_book"]
    assert pb["balanced"]["self_compared"]["share"] == 1.0
    assert pb["balanced"]["self_compared"]["gain_zero"] == 5
    assert pb["aggressive"]["self_compared"]["share"] == 0.0


def test_yield_gap_missing_book_file_is_unmeasured_for_that_book_only(tmp_path):
    r = _kpi(_scene_dir(tmp_path, books={"aggressive": _records(2)}), "Yield Gap")
    assert r["kind"] == "lower_bound_of_declared"
    assert r["per_book"]["balanced"]["kind"] == UNMEASURED
    assert r["per_book"]["aggressive"]["population"] == 2


def test_yield_gap_is_unmeasured_when_the_search_kind_is_unmeasured(tmp_path):
    r = _kpi(_scene_dir(tmp_path, optimum_module=None), "Yield Gap")
    assert r["kind"] == UNMEASURED


# ───────────────────────────── Transaction Cost Drag ─────────────────────────

def test_cost_drag_components_are_present_but_not_composed(tmp_path):
    r = _kpi(_scene_dir(tmp_path), "Transaction Cost Drag")
    assert r["kind"] == "components_not_composed"
    names = {c["carrier"] for c in r["carriers"]}
    assert any("daily.cost_usd" in n for n in names) and any("costs_paid_usd" in n for n in names)
    assert any("gross−net" in n for n in names)
    track = next(c for c in r["carriers"] if "daily.cost_usd" in c["carrier"])
    assert (track["rows_with_value"], track["rows_without_column"], track["sum_usd"]) == (1, 2, 2.5)


def test_cost_drag_without_any_carrier_is_unmeasured(tmp_path):
    r = _kpi(_scene_dir(tmp_path, records=None, track=None, snapshot=None, replay=None),
             "Transaction Cost Drag")
    assert r["kind"] == UNMEASURED


# ───────────────────────────── Portfolio Turnover ────────────────────────────

def test_turnover_components_count_days_without_the_column(tmp_path):
    r = _kpi(_scene_dir(tmp_path), "Portfolio Turnover")
    assert r["kind"] == "components_not_composed"
    track = next(c for c in r["carriers"] if "turnover_usd" in c["carrier"] and c["role"].endswith("realised"))
    assert (track["population"], track["rows_with_value"], track["rows_without_column"]) == (3, 1, 2)


def test_turnover_without_any_carrier_is_unmeasured(tmp_path):
    assert _kpi(_scene_dir(tmp_path, records=None, track=None), "Portfolio Turnover")["kind"] == UNMEASURED


# ───────────────────────────── False Rebalance Rate ──────────────────────────

def test_false_rebalance_rate_is_produced_with_numerator_and_denominator(tmp_path):
    r = _kpi(_scene_dir(tmp_path), "False Rebalance Rate")
    assert r["kind"] == "produced"
    assert (r["population"], r["numerator"], r["value"]) == (13, 12, 0.9231)


def test_false_rebalance_rate_without_unchecked_key_lacks_the_third_outcome(tmp_path):
    fr = {"checked": 13, "false": 12, "max_payback_days": 30.0, "worst": []}
    assert _kpi(_scene_dir(tmp_path, replay=_replay(fr=fr)), "False Rebalance Rate")["kind"] == \
        "produced_without_third_outcome"


def test_false_rebalance_rate_when_the_replay_refused_is_unmeasured(tmp_path):
    fr = {"verdict": "UNCHECKED", "reason": "горизонт не прочитан"}
    r = _kpi(_scene_dir(tmp_path, replay=_replay(fr=fr)), "False Rebalance Rate")
    assert r["kind"] == UNMEASURED and r["value"] is None if "value" in r else r["kind"] == UNMEASURED


# ───────────────────────────── Missed Opportunity Cost ───────────────────────

def test_missed_opportunity_cost_is_produced_from_the_judge_rows(tmp_path):
    r = _kpi(_scene_dir(tmp_path), "Missed Opportunity Cost")
    assert r["kind"] == "produced"
    # Блок реплея (как и живой) без ключа `unchecked` ⇒ производитель с третьим исходом — судья.
    assert (r["population"], r["numerator"]) == (2, 1)
    assert {c["kind"] for c in r["carriers"]} == {"measured_without_third_outcome", "measured"}


def test_missed_opportunity_cost_without_replay_and_judge_is_unmeasured(tmp_path):
    assert _kpi(_scene_dir(tmp_path, replay=None, judge=None), "Missed Opportunity Cost")["kind"] == UNMEASURED


# ───────────────────────────── Forecast Accuracy ─────────────────────────────

def test_forecast_accuracy_is_produced_with_magnitude(tmp_path):
    r = _kpi(_scene_dir(tmp_path), "Forecast Accuracy")
    assert r["kind"] == "produced"
    assert (r["population"], r["sign_disagreements"], r["magnitude_median"], r["magnitude_n"]) == (149, 32, 3.2916, 25)


def test_forecast_accuracy_without_the_forecast_is_unmeasured(tmp_path):
    assert _kpi(_scene_dir(tmp_path, forecast=None), "Forecast Accuracy")["kind"] == UNMEASURED


# ───────────────────────────── Average Break-even ────────────────────────────

def test_average_break_even_components_are_not_composed_and_the_threshold_is_named(tmp_path):
    r = _kpi(_scene_dir(tmp_path), "Average Break-even")
    assert r["kind"] == "components_not_composed"
    rep = next(c for c in r["carriers"] if c["role"] == "component_fact")
    assert rep["threshold_days"] == 30.0 and "ПОРОГ" in rep["note"]
    rec = next(c for c in r["carriers"] if c["role"] == "component_forecast_t0")
    assert (rec["rows_with_value"], rec["rows_without"]) == (4, 0)


def test_average_break_even_without_carriers_is_unmeasured(tmp_path):
    assert _kpi(_scene_dir(tmp_path, records=None, replay=None), "Average Break-even")["kind"] == UNMEASURED


# ───────────────────────────── Risk Policy Violations ────────────────────────

def test_risk_violations_are_produced_from_the_limits_snapshot(tmp_path):
    r = _kpi(_scene_dir(tmp_path), "Risk Policy Violations")
    assert r["kind"] == "produced"
    assert (r["population"], r["numerator"], r["failing_today"]) == (5, 1, ["DL-03"])
    assert r["history"]["third_outcome_present"] is False and r["history"]["rows"] == 2


def test_risk_violations_from_the_blocks_history_alone_lack_the_third_outcome(tmp_path):
    r = _kpi(_scene_dir(tmp_path, limits=None), "Risk Policy Violations")
    assert r["kind"] == "produced_without_third_outcome"


def test_risk_violations_without_carriers_is_unmeasured(tmp_path):
    assert _kpi(_scene_dir(tmp_path, limits=None, blocks=None), "Risk Policy Violations")["kind"] == UNMEASURED


# ───────────────────────────── свежесть ──────────────────────────────────────

def test_stale_replay_is_a_warn_on_every_kpi_it_produces(tmp_path):
    root = _scene_dir(tmp_path, replay=_replay(stamp_hours_ago=186.0))
    findings, _ = _findings(root, _card(tmp_path, _GOOD_CARD))
    stale = {f["code"] for f in findings if f["code"].startswith("producer_stale:")}
    assert stale == {"producer_stale:Gross Portfolio APY", "producer_stale:Net Portfolio APY",
                     "producer_stale:False Rebalance Rate", "producer_stale:Missed Opportunity Cost"}


def test_fresh_replay_yields_no_stale_finding(tmp_path):
    findings, _ = _findings(_scene_dir(tmp_path), _card(tmp_path, _GOOD_CARD))
    assert not [f for f in findings if f["code"].startswith("producer_stale:")]


def test_missing_slo_makes_freshness_unmeasured_not_fresh(tmp_path):
    root = _scene_dir(tmp_path, manifest=_manifest({}))
    _, unmeasured = _findings(root, _card(tmp_path, _GOOD_CARD))
    assert any("SLO для data/cio_shadow_replay.json" in u for u in unmeasured)
    assert _kpi(root, "Gross Portfolio APY")["freshness"]["fresh"] is None


def test_missing_stamp_makes_freshness_unmeasured(tmp_path):
    rep = _replay()
    del rep["generated_at"]
    fr = _kpi(_scene_dir(tmp_path, replay=rep), "Gross Portfolio APY")["freshness"]
    assert fr["fresh"] is None and "отметка" in fr["reason"]


def test_freshness_at_judges_against_a_full_manifest_path():
    slo = {PK.SNAPSHOT_REL: 26.0}
    assert PK.freshness_at(_iso(1.0), PK.SNAPSHOT_REL, slo, _NOW)["fresh"] is True
    assert PK.freshness_at(_iso(27.0), PK.SNAPSHOT_REL, slo, _NOW)["fresh"] is False
    assert PK.freshness_at(_iso(1.0), "data/other.json", slo, _NOW)["fresh"] is None


# ───────────────────────────── находки ───────────────────────────────────────

def test_summary_finding_names_the_missing_kpis_and_the_emphasis_kind(tmp_path):
    findings, unmeasured = _findings(_scene_dir(tmp_path), _card(tmp_path, _GOOD_CARD))
    s = next(f for f in findings if f["code"] == "kpis_declared_vs_produced")
    assert s["severity"] == "CRITICAL"
    assert "производится 7" in s["message"] and "«Yield Gap» → lower_bound_of_declared" in s["message"]
    assert "«Transaction Cost Drag»→components_not_composed" in s["message"]
    assert "«Optimal Policy-Compliant APY»→lower_bound_of_declared" in s["message"]
    assert "«Yield Gap»→lower_bound_of_declared" in s["message"]
    assert unmeasured == []


def test_self_comparison_warn_fires_only_above_the_share(tmp_path):
    findings, _ = _findings(_scene_dir(tmp_path), _card(tmp_path, _GOOD_CARD))
    codes = {f["code"] for f in findings}
    assert "yield_gap_zero_by_self_comparison:balanced" in codes
    assert "yield_gap_zero_by_self_comparison:aggressive" not in codes


def test_formula_disagreement_is_a_warn(tmp_path):
    root = _scene_dir(tmp_path, records=_records(3) + [_record(3, gain=9.9)])
    findings, _ = _findings(root, _card(tmp_path, _GOOD_CARD))
    assert any(f["code"] == "yield_gap_formula_disagrees:conservative" for f in findings)


def test_blocks_history_without_third_outcome_is_a_warn_and_todays_fail_is_info(tmp_path):
    findings, _ = _findings(_scene_dir(tmp_path), _card(tmp_path, _GOOD_CARD))
    codes = {f["code"]: f["severity"] for f in findings}
    assert codes.get("violations_history_without_third_outcome") == "WARN"
    assert codes.get("risk_limit_failing_today") == "INFO"


def test_unmeasured_kpi_is_not_turned_into_a_finding(tmp_path):
    root = _scene_dir(tmp_path, optimum_module=None)
    findings, unmeasured = _findings(root, _card(tmp_path, _GOOD_CARD))
    assert not [f for f in findings if "Yield Gap»→" in f["message"] or "Optimal Policy-Compliant APY»→" in f["message"]]
    assert not [f for f in findings if "Yield Gap" in f["code"] or "yield_gap" in f["code"]]
    assert any("KPI «Yield Gap»" in u for u in unmeasured)


# ───────────────────────────── run / main ────────────────────────────────────

def test_run_writes_the_artifact_atomically_and_reports_the_live_shape(tmp_path):
    root = _scene_dir(tmp_path)
    doc = PK.run(root=root, card_path=_card(tmp_path, _GOOD_CARD), write=True, now=_NOW)
    assert doc["overall"] == "CRITICAL" and doc["applied"] is False
    assert doc["kpis"]["declared"] == 12 and doc["kpis"]["produced"] == 7
    assert doc["kpis"]["emphasis_kind"] == "lower_bound_of_declared"
    assert doc["carriers_read"]["snapshot"] is True and doc["carriers_read"]["optimum_search_text"] is True
    saved = json.loads((tmp_path / "root" / PK.REPORT_REL).read_text(encoding="utf-8"))
    assert saved["schema"] == "portfolio_kpi_census/v1" and saved["generated_at"] == _NOW.isoformat()


def test_run_no_write_leaves_no_artifact(tmp_path):
    root = _scene_dir(tmp_path)
    PK.run(root=root, card_path=_card(tmp_path, _GOOD_CARD), write=False, now=_NOW)
    assert not (tmp_path / "root" / PK.REPORT_REL).exists()


def test_main_returns_one_on_critical(tmp_path, capsys):
    root = _scene_dir(tmp_path)
    rc = PK.main(["--root", root, "--card", _card(tmp_path, _GOOD_CARD), "--no-write",
                  "--now", _NOW.isoformat()])
    out = capsys.readouterr().out
    assert rc == 1 and "производится 7" in out and "паритет с карточкой: СОВПАЛ" in out


def test_main_returns_two_when_nothing_can_be_measured(tmp_path, capsys):
    root = tmp_path / "root"
    (root / "data").mkdir(parents=True)
    rc = PK.main(["--root", str(root), "--card", _card(tmp_path, _GOOD_CARD), "--no-write",
                  "--now", _NOW.isoformat()])
    assert rc == 2
    assert "[НЕ ИЗМЕРЕНО]" in capsys.readouterr().out


def test_main_refuses_an_unparseable_now(tmp_path, capsys):
    rc = PK.main(["--root", _scene_dir(tmp_path), "--no-write", "--now", "вчера"])
    assert rc == 2 and "НЕ ИЗМЕРЕНО" in capsys.readouterr().out


def test_main_prints_every_kpi_with_its_kind(tmp_path, capsys):
    PK.main(["--root", _scene_dir(tmp_path), "--card", _card(tmp_path, _GOOD_CARD), "--no-write",
             "--now", _NOW.isoformat()])
    out = capsys.readouterr().out
    for name in PK.OWNER_KPIS:
        assert f"«{name}»:" in out


# ───────────────────────────── проба приёмки ─────────────────────────────────

def test_probe_is_registered_with_data_dir_as_input():
    assert PROBE in CA.PROBES
    assert "data_dir" in CA.probe_tree_inputs(PROBE)


def test_probe_on_the_scene_is_not_satisfied_and_names_the_kpis(tmp_path):
    root = _scene_dir(tmp_path)
    verdict, why = CA.run_probe(PROBE, data_dir=os.path.join(root, "data"))
    assert verdict == CA.NOT_SATISFIED
    assert "Yield Gap" in why and "Transaction Cost Drag" in why and "производится 7" in why


def test_probe_satisfied_only_when_every_kpi_is_produced(tmp_path, monkeypatch):
    root = _scene_dir(tmp_path)
    real = PK.measure_kpis

    def all_produced(carriers, slo, now):
        doc = real(carriers, slo, now)
        for r in doc["kpis"].values():
            r["kind"] = "produced"
        doc["produced"] = len(doc["kpis"])
        return doc

    monkeypatch.setattr(PK, "measure_kpis", all_produced)
    verdict, why = CA.run_probe(PROBE, data_dir=os.path.join(root, "data"))
    assert verdict == CA.SATISFIED, why


def test_probe_unmeasured_kpi_is_unmeasured_not_a_verdict(tmp_path):
    root = _scene_dir(tmp_path, optimum_module=None)
    verdict, why = CA.run_probe(PROBE, data_dir=os.path.join(root, "data"))
    assert verdict == UNMEASURED
    assert "Yield Gap" in why


def test_probe_without_any_carrier_is_unmeasured(tmp_path):
    root = _scene_dir(tmp_path, replay=None, judge=None, forecast=None, limits=None, records=None,
                      track=None, snapshot=None, shelf=None)
    verdict, why = CA.run_probe(PROBE, data_dir=os.path.join(root, "data"))
    assert verdict == UNMEASURED
    assert "НЕ ИЗМЕРЕНО" in why


def test_probe_refuses_an_argument():
    verdict, why = CA.run_probe(f"{PROBE}:foo")
    assert verdict == UNMEASURED
    assert "аргумент" in why


def test_probe_is_not_a_substring_check(tmp_path):
    """Файл с нужными словами, но без структуры носителя — не производитель."""
    root = _scene_dir(tmp_path, replay={"generated_at": _iso(1.0),
                                        "note": "gross_apy_pct net_apy_pct produced Yield Gap"},
                      judge=None, forecast=None, limits=None, blocks=None, records=None, books={},
                      track=None, snapshot=None, shelf=None)
    verdict, why = CA.run_probe(PROBE, data_dir=os.path.join(root, "data"))
    assert verdict == UNMEASURED
