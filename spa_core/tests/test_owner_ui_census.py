"""Батарея §36 ТЗ «Portfolio CIO» — ``spa_core/analytics/owner_ui_census.py``.

Каждый запрещённый класс и каждый вывод владельца проверяется в обе стороны: сцена, где
основной экран ЧИСТ и вывод ДОХОДИТ (читатель сцены печатает значения словами владельца), и
сцена, где класс присутствует / производителя нет / вывод не доходит — с названным звеном.
Литеральных дат нет: отметки носителей строятся от одного якоря ``_NOW`` (время — вход, не
часы). Сборщик отчёта — ВХОД ``reader=``, рендеримые ключи дашборда — ВХОД ``page_keys=``;
живые зовутся ровно в тех тестах, чей предмет — они сами.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import textwrap
from typing import Any

from spa_core.analytics import owner_ui_census as OU
from spa_core.analytics.transaction_economics import UNMEASURED
from spa_core.monitoring import card_acceptance as CA

PROBE = "owner_main_screen_is_owner_first"
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
    35. Paper APY cleanup
    что-то
    36. Owner UI
    Следовать owner-first принципу.
    Owner не должен видеть:
    optimizer internals
    JSON
    policy hashes
    technical IDs
    implementation paths
    internal states
    на основном экране.
    Основной вывод:
    Текущая доходность

    Потенциальная доходность

    Есть ли проблема

    Что система предлагает сделать

    <!-- источник: inbox-x.md строки 1-2 -->

    Сколько это даст

    Сколько стоит

    Когда окупится

    Изменится ли риск

    Нужна ли моя реакция
    Technical details скрыть в:
    Подробнее


    ⸻


    37. Testing scenarios
    """

# ───────────────────────────── сцена каталога данных ─────────────────────────

_LEGS = [{"delta_usd": 9545.0, "direction": "increase", "protocol": "aave_v3"},
         {"delta_usd": -9545.0, "direction": "decrease", "protocol": "compound_v3"}]
_REASONS = ["gain_below_band:0.104pp<0.500pp", "payback_too_long:196.2d"]


def _record(i: int, **over) -> dict:
    r = {"schema": "shadow-hist-v2", "cycle_date": _D[i % len(_D)], "generated_at": _iso(1.0 + i),
         "decision_id": f"adr060-shadow-{_D[i % len(_D)]}", "book_id": "conservative",
         "verdict": "HOLD", "book_apy_pp": 3.905455, "target_apy_pp": 4.008985, "gain_pp": 0.10353,
         "capital_usd": 100000.0, "cost_usd": 55.65, "payback_days": 196.2,
         "turnover_usd": 15000.0, "turnover_frac": 0.15, "legs": list(_LEGS), "reasons": list(_REASONS),
         "current_positions": {"aave_v3": 5000.0, "compound_v3": 40000.0},
         "target_positions": {"aave_v3": 14545.0, "compound_v3": 30455.0},
         "gates": {"has_legs": True, "target_fully_evidenced": True}, "apy_unevidenced": [],
         "admissible_trim": {"policy": {"approved": True}}, "policy_version": "v1.2", "mode": "paper"}
    r.update(over)
    return r


def _records(n=3, **over) -> list:
    return [_record(i, **over) for i in range(n)]


def _track() -> dict:
    return {"daily": [{"date": _D[i], "open_equity": 100000.0 + i, "close_equity": 100500.0 + i,
                       "equity": 100500.0 + i, "positions": {"aave_v3": 5000.0, "compound_v3": 40000.0},
                       "apy_today": 4.0} for i in range(3)]}


def _health(status="WARNING") -> dict:
    return {"overall_status": status, "generated_at": _iso(1.0), "domains": {}}


def _scene_dir(tmp, *, records: Any = "default", track: Any = "default", health: Any = "default") -> str:
    root = tmp / "root"
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)       # сцена перестраивается в том же tmp_path
    for rel in (OU.RECORD_REL, OU.TRACK_REL, OU.SYSTEM_HEALTH_REL):
        (data / rel).unlink(missing_ok=True)
    if records == "default":
        records = _records()
    if records is not None:
        (data / OU.RECORD_REL).write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    tr = _track() if track == "default" else track
    if tr is not None:
        (data / OU.TRACK_REL).write_text(json.dumps(tr), encoding="utf-8")
    h = _health() if health == "default" else health
    if h is not None:
        (data / OU.SYSTEM_HEALTH_REL).write_text(json.dumps(h), encoding="utf-8")
    return str(root)


# ───────────────────────────── читатели сцены ────────────────────────────────

#: Основной экран, на котором ВСЕ девять выводов стоят словами владельца и ни одного
#: запрещённого класса нет. Значения — из `_record(0)`; `apy_today_pct` — из `data`.
_CLEAN_MAIN = ("🟠 Система: есть предупреждения · аварий нет\n"
               "APY сегодня 3,83 % · возможная доходность 4,01 %\n"
               "Система предлагает оставить как есть: разрыв 0,104 пп, переложить стоило бы $55,65 "
               "и окупилось бы за 196 дней; риск не меняется; реакция не нужна.\n"
               "📄 Подробности — следующим сообщением.")
_CLEAN_DETAILS = "📊 отчёт за день\nПозиции: Compound V3 $40,000\n"
_CLEAN_DATA = {"apy_today_pct": 3.8286, "equity_usd": 102017.0}

#: Живой заголовок 11.11 в сокращении — на нём три запрещённых отрезка и два вывода.
_LIVE_MAIN = ("🟠 Система: есть предупреждения — предупреждения: данные\n"
              "⚠️ Нарушение: доходность 3.19 % ниже медианы eligible-набора 4.62 % (ECON-10, compound_v3)\n"
              "🧑‍⚖️ Ждут тебя: карточек 12\n"
              "APY сегодня 3,83 % · среднее за 7 дн. 4,00 %\n"
              "📄 Подробности — следующим сообщением.")
_LIVE_DETAILS = ("📊 отчёт\n⚡ Цикл: ok\n🏛 Офис: постура YELLOW\n"
                 "• ⚠️ Agent WARNING (not stopped): com.spa.orchestrator ×2\n")

_PAGE_KEYS = ["available", "current_apy_pp", "cycle_date", "numbers_evidenced", "numbers_missing",
              "optimal_apy_pp", "verdict", "why", "why_now", "yield_gap_pp"]


def _reader_with(main: str, details: str = _CLEAN_DETAILS, data: dict | None = None):
    def read(data_dir: str, now: dt.datetime):
        return main, details, dict(_CLEAN_DATA if data is None else data), None
    return read


def _reader_failing(data_dir: str, now: dt.datetime):
    return None, None, None, "сборщик сцены отказал"


def _run(root: str, tmp, *, reader=None, card=_GOOD_CARD, now=_NOW, write=False, page_keys=_PAGE_KEYS) -> dict:
    return OU.run(root=root, card_path=_card(tmp, card), write=write, now=now,
                  reader=reader if reader is not None else _reader_with(_CLEAN_MAIN), page_keys=page_keys)


def _rows(doc: dict) -> dict:
    return doc["outputs"]["outputs"]


def _codes(doc: dict) -> set:
    return {f["code"] for f in doc["findings"]}


# ───────────────────────────── паритет с карточкой ────────────────────────────

def test_parity_agrees_on_the_owner_section(tmp_path):
    p = OU.parity(_card(tmp_path, _GOOD_CARD))
    assert p["agrees"] is True, p["mismatches"]
    parsed = p["parsed"]
    assert parsed["forbidden"] == list(OU.FORBIDDEN_CLASSES) and len(parsed["forbidden"]) == OU.FORBIDDEN_CLASSES_DECLARED
    assert parsed["outputs"] == list(OU.OWNER_OUTPUTS) and len(parsed["outputs"]) == OU.OWNER_OUTPUTS_DECLARED
    assert parsed["hide_in"] == [OU.OWNER_HIDE_WORD]
    assert p["order_undercount"] is None and p["order_tail_read"] is True


def test_html_comment_inside_the_outputs_list_is_not_an_output(tmp_path):
    parsed = OU.owner_section_from_card(_card(tmp_path, _GOOD_CARD))
    assert not [o for o in parsed["outputs"] if o.startswith("<!--")]
    assert len(parsed["outputs"]) == 9


def test_forbidden_list_difference_is_a_mismatch(tmp_path):
    p = OU.parity(_card(tmp_path, _GOOD_CARD.replace("policy hashes\n", "")))
    assert p["agrees"] is False and any("запрещённые классы" in m for m in p["mismatches"])


def test_outputs_list_difference_is_a_mismatch(tmp_path):
    p = OU.parity(_card(tmp_path, _GOOD_CARD.replace("Когда окупится\n", "")))
    assert p["agrees"] is False and any("выводы основного экрана" in m for m in p["mismatches"])


def test_hide_word_principle_and_tail_are_checked(tmp_path):
    p = OU.parity(_card(tmp_path, _GOOD_CARD.replace("Подробнее\n", "Детали\n")))
    assert any("Подробнее" in m for m in p["mismatches"])
    p = OU.parity(_card(tmp_path, _GOOD_CARD.replace("Следовать owner-first принципу.\n", "")))
    assert any("owner-first" in m for m in p["mismatches"])
    p = OU.parity(_card(tmp_path, _GOOD_CARD.replace("на основном экране.\n", "везде.\n")))
    assert any("на основном экране" in m for m in p["mismatches"])


def test_missing_lead_lines_are_mismatches(tmp_path):
    p = OU.parity(_card(tmp_path, _GOOD_CARD.replace("Owner не должен видеть:", "Owner не видит:")))
    assert any("Owner не должен видеть" in m for m in p["mismatches"])
    p = OU.parity(_card(tmp_path, _GOOD_CARD.replace("Основной вывод:", "Главный вывод:")))
    assert any("Основной вывод" in m for m in p["mismatches"])


def test_missing_second_boundary_is_unmeasured_not_a_count(tmp_path):
    p = OU.parity(_card(tmp_path, _GOOD_CARD.replace("37. Testing scenarios", "37. Другое")))
    assert p["agrees"] is None and "вторая граница" in p["parsed"]["reason"]


def test_unreadable_card_is_unmeasured(tmp_path):
    p = OU.parity(str(tmp_path / "нет.md"))
    assert p["agrees"] is None and "не прочитана" in p["parsed"]["reason"]


# ───────────────────────────── детекторы запрещённых классов ─────────────────

def test_clean_owner_text_has_no_forbidden_class():
    d = OU.detect_classes(_CLEAN_MAIN)
    assert d["measured"] is True and d["total"] == 0, d["hits"]


def test_each_forbidden_class_is_detected_and_named():
    samples = {
        "implementation paths": "см. spa_core/paper_trading/cio_brief.py и data/x.json",
        "JSON": 'ответ: {"verdict": "HOLD", "gain": 0.1}',
        "policy hashes": "отпечаток d458d912af; policy_version v1.2",
        "optimizer internals": "причина gain_below_band:0.104pp<0.500pp, поле target_apy_pp, tuner",
        "technical IDs": "ECON-10 у compound_v3; агент com.spa.orchestrator; cycle-94199; "
                         "7da72d09-56ca-4ec5-a45f-59114353e487; adr060-shadow-2026-11-11",
        "internal states": "вердикт HOLD, стоп-кран SOFT_DERISK, статус CRITICAL",
    }
    for cls, text in samples.items():
        d = OU.detect_classes(text)
        assert d["hits"][cls], (cls, d["hits"])


def test_one_span_falls_into_exactly_one_class():
    # код причины — внутренности оптимизатора; тот же snake_case не должен ВТОРОЙ раз стать технич. ID
    d = OU.detect_classes("gain_below_band:0.104pp<0.500pp")
    assert d["hits"]["optimizer internals"] == ["gain_below_band:0.104pp<0.500pp"]
    assert d["hits"]["technical IDs"] == [] and d["total"] == 1
    # путь к файлу — путь, а не идентификатор и не хэш
    d = OU.detect_classes("файл data/allocation_rationale_history.jsonl")
    assert d["hits"]["implementation paths"] and not d["hits"]["technical IDs"]


def test_owner_decision_words_are_not_internal_states():
    d = OU.detect_classes("Decision: KEEP · альтернатива REBALANCE")
    assert d["total"] == 0, d["hits"]


def test_numbers_dates_and_money_are_not_hashes_or_ids():
    d = OU.detect_classes("$102,017 · +1,88 % · 2026-11-11 · 141 дн. · 07:10 · 3.19 %")
    assert d["total"] == 0, d["hits"]
    # длинное ЧИСЛО (8 цифр без буквы) — не хэш: отпечаток обязан нести хотя бы одну букву a…f
    d = OU.detect_classes("отметка 20261111 · сумма 10000000 · d458d912")
    assert d["hits"]["policy hashes"] == ["d458d912"], d["hits"]


def test_russian_prose_with_underscore_is_named_so_it_can_be_disputed():
    # детектор ошибается в сторону находки и ПЕЧАТАЕТ отрезок — спорить можно глазами
    d = OU.detect_classes("статус site_freshness")
    assert d["hits"]["technical IDs"] == ["site_freshness"]


def test_empty_screen_is_unmeasured_not_clean():
    d = OU.detect_classes(None)
    assert d["measured"] is False and d["total"] is None


def test_live_headline_shape_yields_three_spans_in_two_classes():
    d = OU.detect_classes(_LIVE_MAIN)
    assert d["hits"]["optimizer internals"] == ["eligible"]
    assert d["hits"]["technical IDs"] == ["ECON-10", "compound_v3"]
    assert d["total"] == 3 and d["classes_present"] == ["optimizer internals", "technical IDs"]


# ───────────────────────────── поверхности ───────────────────────────────────

def test_clean_scene_is_free_of_forbidden_classes_on_the_main_screen(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path)
    main = doc["surfaces"]["surfaces"][OU.SURFACE_MAIN]
    assert main["total"] == 0
    assert "main_screen_free_of_forbidden_classes" in _codes(doc)
    assert not [c for c in _codes(doc) if c.startswith("forbidden_on_main_screen")]


def test_live_shaped_headline_is_critical_per_class_on_the_main_screen(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path, reader=_reader_with(_LIVE_MAIN, _LIVE_DETAILS))
    codes = _codes(doc)
    assert "forbidden_on_main_screen:optimizer internals" in codes
    assert "forbidden_on_main_screen:technical IDs" in codes
    assert "forbidden_on_main_screen:internal states" not in codes
    sev = {f["code"]: f["severity"] for f in doc["findings"]}
    assert sev["forbidden_on_main_screen:technical IDs"] == "CRITICAL"
    assert doc["overall"] == "CRITICAL"


def test_details_message_may_carry_technical_classes_as_info(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path, reader=_reader_with(_CLEAN_MAIN, _LIVE_DETAILS))
    fnd = {f["code"]: f for f in doc["findings"]}
    assert fnd["technical_details_in_details_message"]["severity"] == "INFO"
    assert "internal states" in fnd["technical_details_in_details_message"]["message"]
    assert not [c for c in fnd if c.startswith("forbidden_on_main_screen")]


def test_details_separation_is_measured_from_the_headline(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path)
    assert doc["surfaces"]["details_separated"] is True
    no_footer = _CLEAN_MAIN.replace("📄 Подробности — следующим сообщением.", "")
    doc = _run(_scene_dir(tmp_path), tmp_path, reader=_reader_with(no_footer))
    assert doc["surfaces"]["details_separated"] is False
    assert "details_not_announced" in _codes(doc)


def test_dashboard_judges_only_rendered_keys_and_names_hidden_ones(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path)
    dash = doc["surfaces"]["surfaces"][OU.SURFACE_DASHBOARD]
    # `why` рендерится и несёт коды причин; `verdict` — HOLD
    assert dash["hits"]["optimizer internals"] == sorted(_REASONS)
    assert dash["hits"]["internal states"] == ["HOLD"]
    sev = {f["code"]: f["severity"] for f in doc["findings"]}
    assert sev["forbidden_on_dashboard:optimizer internals"] == "WARN"
    hidden = doc["surfaces"]["dashboard_carried_not_rendered"]
    assert "decision_id" in hidden and "policy_version" in hidden and "mode" in hidden
    assert "dashboard_carries_but_hides" in _codes(doc)


def test_dashboard_with_only_clean_keys_rendered_is_clean(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path, page_keys=["current_apy_pp", "optimal_apy_pp", "yield_gap_pp"])
    assert doc["surfaces"]["surfaces"][OU.SURFACE_DASHBOARD]["total"] == 0
    assert "dashboard_free_of_forbidden_classes" in _codes(doc)


def test_dashboard_rendered_keys_are_read_from_the_page(tmp_path):
    root = tmp_path / "root"
    page = root / OU.DASHBOARD_PAGE_REL
    page.parent.mkdir(parents=True)
    page.write_text("const x = br.verdict + br.why; if (br.available) {} br.yield_gap_pp", encoding="utf-8")
    keys, why = OU.dashboard_rendered_keys(str(root))
    assert why is None and keys == ["available", "verdict", "why", "yield_gap_pp"]
    page.write_text("ничего про brief", encoding="utf-8")
    keys, why = OU.dashboard_rendered_keys(str(root))
    assert keys is None and "НЕ ИЗМЕРЕНО" in why
    keys, why = OU.dashboard_rendered_keys(str(tmp_path / "нет"))
    assert keys is None and "не прочитана" in why


def test_unreadable_page_makes_dashboard_unmeasured_not_clean(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path, page_keys=None)
    assert doc["surfaces"]["surfaces"][OU.SURFACE_DASHBOARD]["measured"] is False
    assert any("рендеримые ключи дашборда" in u for u in doc["unmeasured"])
    assert "dashboard_free_of_forbidden_classes" not in _codes(doc)


# ───────────────────────────── выводы владельца ──────────────────────────────

def test_clean_scene_puts_seven_produced_outputs_on_the_main_screen(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path)
    o = doc["outputs"]
    assert o["declared"] == 9 and o["produced"] == 7 and o["reach_main"] == 7
    rows = _rows(doc)
    for name in ("Текущая доходность", "Потенциальная доходность", "Есть ли проблема",
                 "Что система предлагает сделать", "Сколько это даст", "Сколько стоит", "Когда окупится"):
        assert rows[name]["kind"] == "produced" and rows[name]["main_reach"] is True, (name, rows[name])
    for name in ("Изменится ли риск", "Нужна ли моя реакция"):
        assert rows[name]["kind"] == "absent"


def test_live_shaped_headline_reaches_two_outputs(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path, reader=_reader_with(_LIVE_MAIN, _LIVE_DETAILS))
    assert doc["outputs"]["reach_main_names"] == ["Текущая доходность", "Есть ли проблема"]
    rows = _rows(doc)
    assert rows["Сколько стоит"]["main_reach"] is False
    assert "output_not_on_main_screen:Сколько стоит" in _codes(doc)
    assert "outputs_declared_vs_on_main_screen" in _codes(doc)


def test_internal_verdict_word_on_the_screen_is_not_the_owner_answer(tmp_path):
    main = _CLEAN_MAIN.replace(
        "Система предлагает оставить как есть: разрыв 0,104 пп, переложить стоило бы $55,65 "
        "и окупилось бы за 196 дней",
        "Вердикт: HOLD: разрыв 0,104 пп, цена хода $55,65, окупаемость 196 дней")
    doc = _run(_scene_dir(tmp_path), tmp_path, reader=_reader_with(main))
    rows = _rows(doc)
    assert rows["Что система предлагает сделать"]["main_reach"] is False
    assert "forbidden_on_main_screen:internal states" in _codes(doc)


def test_problem_answer_is_a_phrase_from_the_owner_vocabulary(tmp_path):
    main = _CLEAN_MAIN.replace("🟠 Система: есть предупреждения · аварий нет", "статус WARNING")
    doc = _run(_scene_dir(tmp_path), tmp_path, reader=_reader_with(main))
    assert _rows(doc)["Есть ли проблема"]["main_reach"] is False


def test_number_reach_needs_three_significant_digits(tmp_path):
    # «4,0» вместо «4,01» — рендера с тремя значащими цифрами нет: НЕ ИЗМЕРЕНО, не «доходит»
    main = _CLEAN_MAIN.replace("возможная доходность 4,01 %", "возможная доходность 4,0 %")
    doc = _run(_scene_dir(tmp_path), tmp_path, reader=_reader_with(main))
    assert _rows(doc)["Потенциальная доходность"]["main_reach"] is False
    recs = _records(target_apy_pp=0.43)
    doc = _run(_scene_dir(tmp_path, records=recs), tmp_path, reader=_reader_with(main.replace("4,0 %", "0,43 %")))
    assert _rows(doc)["Потенциальная доходность"]["main_reach"] is None
    assert any("Потенциальная доходность" in u for u in doc["unmeasured"])


def test_output_reaching_details_or_dashboard_is_named_in_the_finding(tmp_path):
    main = _CLEAN_MAIN.replace("переложить стоило бы $55,65", "переложить стоило бы немного")
    details = _CLEAN_DETAILS + "стоимость $55,65\n"
    doc = _run(_scene_dir(tmp_path), tmp_path, reader=_reader_with(main, details))
    f = {x["code"]: x for x in doc["findings"]}["output_not_on_main_screen:Сколько стоит"]
    assert "доходит до «Подробнее»" in f["message"]
    main2 = _CLEAN_MAIN.replace("возможная доходность 4,01 %", "")
    doc = _run(_scene_dir(tmp_path), tmp_path, reader=_reader_with(main2))
    f = {x["code"]: x for x in doc["findings"]}["output_not_on_main_screen:Потенциальная доходность"]
    assert "дашборда" in f["message"] and "ADR-808" in f["message"]


def test_field_absent_from_every_record_is_absent_with_the_ledger_named(tmp_path):
    recs = [{k: v for k, v in r.items() if k != "payback_days"} for r in _records()]
    doc = _run(_scene_dir(tmp_path, records=recs), tmp_path)
    r = _rows(doc)["Когда окупится"]
    assert r["kind"] == "absent" and "payback_days" in r["reason"]
    assert "output_absent:Когда окупится" in _codes(doc)


def test_third_outcome_is_read_from_the_ledger(tmp_path):
    recs = _records()
    recs[0]["payback_days"] = None
    doc = _run(_scene_dir(tmp_path, records=recs), tmp_path)
    r = _rows(doc)["Когда окупится"]
    assert r["kind"] == "produced" and r["third_outcome"].startswith("наблюдён")
    doc = _run(_scene_dir(tmp_path), tmp_path)
    assert _rows(doc)["Когда окупится"]["third_outcome"].startswith("не наблюдён")


def test_current_yield_comes_from_the_report_data_not_the_record(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path, reader=_reader_with(_CLEAN_MAIN, data={"equity_usd": 1.0}))
    r = _rows(doc)["Текущая доходность"]
    assert r["kind"] == "absent" and "apy_today_pct" in r["carrier"]


def test_problem_output_comes_from_system_health(tmp_path):
    doc = _run(_scene_dir(tmp_path, health=None), tmp_path)
    r = _rows(doc)["Есть ли проблема"]
    assert r["kind"] == UNMEASURED and OU.SYSTEM_HEALTH_REL in r["reason"]
    doc = _run(_scene_dir(tmp_path, health={"generated_at": _iso(1.0)}), tmp_path)
    assert _rows(doc)["Есть ли проблема"]["kind"] == "absent"


def test_reaction_phrase_about_the_queue_is_named_as_another_question(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path, reader=_reader_with(_LIVE_MAIN, _LIVE_DETAILS))
    r = _rows(doc)["Нужна ли моя реакция"]
    assert r["kind"] == "absent" and r["phrase_on_main_screen"] is True and r["main_reach"] is None
    f = {x["code"]: x for x in doc["findings"]}["output_absent:Нужна ли моя реакция"]
    assert "другой вопрос" in f["message"]


def test_qualifiers_are_warns_not_criticals(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path)
    sev = {f["code"]: f["severity"] for f in doc["findings"]}
    assert sev["output_qualifier:Потенциальная доходность"] == "WARN"
    assert sev["output_qualifier:Что система предлагает сделать"] == "WARN"
    # а вывод БЕЗ производителя — CRITICAL: владелец заказал его словами §36, и его нечем напечатать
    assert sev["output_absent:Изменится ли риск"] == "CRITICAL"
    assert sev["output_absent:Нужна ли моя реакция"] == "CRITICAL"


def test_dashboard_reach_is_false_when_the_page_hides_the_key(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path)
    rows = _rows(doc)
    assert rows["Сколько стоит"]["dashboard_reach"] is False          # how_much не рендерится
    assert rows["Потенциальная доходность"]["dashboard_reach"] is True
    assert rows["Когда окупится"]["dashboard_reach"] is None            # ключа у слоя нет


# ───────────────────────────── третий исход прибора ──────────────────────────

def test_report_not_built_is_unmeasured_not_a_dirty_screen(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path, reader=_reader_failing)
    assert doc["surfaces"]["surfaces"][OU.SURFACE_MAIN]["measured"] is False
    assert not [c for c in _codes(doc) if c.startswith("forbidden_on_main_screen")]
    assert "main_screen_free_of_forbidden_classes" not in _codes(doc)
    assert any("не собран" in u for u in doc["unmeasured"])
    assert doc["outputs"]["main_screen_built"] is False
    assert "outputs_declared_vs_on_main_screen" not in _codes(doc)


def test_empty_ledger_makes_record_outputs_unmeasured(tmp_path):
    doc = _run(_scene_dir(tmp_path, records=None), tmp_path)
    rows = _rows(doc)
    assert rows["Сколько стоит"]["kind"] == UNMEASURED
    assert rows["Текущая доходность"]["kind"] == "produced"     # сборщик отчёта — другой носитель
    assert doc["carriers_read"]["records"] is False


def test_card_mismatch_is_a_warn_not_a_block(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path, card=_GOOD_CARD.replace("JSON\n", ""))
    assert "card_parity_mismatch" in _codes(doc)
    assert doc["outputs"]["declared"] == 9


def test_overall_and_exit_codes(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path)
    # чистый экран, семь выводов из девяти — два отсутствующих производителя дают CRITICAL
    assert doc["overall"] == "CRITICAL"
    doc = _run(_scene_dir(tmp_path), tmp_path, reader=_reader_failing, page_keys=None)
    assert doc["overall"] in ("CRITICAL", "WARNING", "UNCHECKED")


def test_main_exit_codes(tmp_path, capsys):
    root = _scene_dir(tmp_path)
    card = _card(tmp_path, _GOOD_CARD)
    rc = OU.main(["--root", root, "--card", card, "--no-write", "--now", _NOW.isoformat()])
    assert rc == 1
    out = capsys.readouterr().out
    assert "§36" in out and "основной экран собран" in out
    assert OU.main(["--root", root, "--card", card, "--no-write", "--now", "вчера"]) == 2


def test_write_puts_the_artifact_at_report_rel(tmp_path):
    root = _scene_dir(tmp_path)
    OU.run(root=root, card_path=_card(tmp_path, _GOOD_CARD), write=True, now=_NOW,
           reader=_reader_with(_CLEAN_MAIN), page_keys=_PAGE_KEYS)
    doc = json.loads((tmp_path / "root" / OU.REPORT_REL).read_text(encoding="utf-8"))
    assert doc["schema"] == "owner_ui_census/v1" and doc["applied"] is False


def test_declared_block_names_surfaces_and_order(tmp_path):
    doc = _run(_scene_dir(tmp_path), tmp_path)
    d = doc["declared"]
    assert d["forbidden_declared"] == 6 and d["outputs_declared"] == 9 and d["hide_in"] == "Подробнее"
    assert d["surfaces"] == [OU.SURFACE_MAIN, OU.SURFACE_DETAILS, OU.SURFACE_DASHBOARD]
    assert d["order_g969_named"]["tail_read"] is True


# ───────────────────────────── живые читатели (предмет — они сами) ───────────

def test_live_report_reader_builds_the_digest_without_writing(tmp_path):
    root = _scene_dir(tmp_path)
    data = os.path.join(root, "data")
    before = sorted(os.listdir(data))
    headline, details, d, why = OU.drc.live_report_reader(data, _NOW)
    assert why is None, why
    assert isinstance(headline, str) and isinstance(details, str) and isinstance(d, dict)
    assert OU.HEADLINE_FOOTER_WORDS in headline
    assert sorted(os.listdir(data)) == before


def test_live_dashboard_page_is_read_from_the_repo():
    keys, why = OU.dashboard_rendered_keys(OU.REPO_ROOT)
    assert why is None, why
    assert "why" in keys and "verdict" in keys


# ───────────────────────────── проба приёмки ─────────────────────────────────

def _probe_scene(tmp, monkeypatch, reader, **scene) -> str:
    """Сцена пробы: каталог данных + карточка по каноническому пути от корня (родителя
    `data_dir`); живой сборщик отчёта подменён читателем сцены через ЕДИНСТВЕННУЮ дверь."""
    root = _scene_dir(tmp, **scene)
    card = os.path.join(root, OU.CARD_REL)
    os.makedirs(os.path.dirname(card), exist_ok=True)
    with open(card, "w", encoding="utf-8") as fh:
        fh.write(textwrap.dedent(_GOOD_CARD))
    monkeypatch.setattr(OU, "live_report_reader", reader)
    return os.path.join(root, "data")


def test_probe_is_registered_with_data_dir_as_input():
    assert PROBE in CA.PROBES
    assert "data_dir" in CA.probe_tree_inputs(PROBE)


def test_probe_rejects_an_argument():
    status, why = CA.PROBES[PROBE]("x")
    assert status == CA.UNMEASURED and "аргумента" in why


def test_probe_is_not_satisfied_on_a_live_shaped_screen(tmp_path, monkeypatch):
    data = _probe_scene(tmp_path, monkeypatch, _reader_with(_LIVE_MAIN, _LIVE_DETAILS))
    status, why = CA.run_probe(PROBE, data_dir=data)
    assert status == CA.NOT_SATISFIED, why
    assert "запрещённых отрезков 3" in why and "на основном экране 2" in why
    assert "compound_v3" in why and "Сколько стоит" in why


def test_probe_is_not_satisfied_while_a_producer_is_missing(tmp_path, monkeypatch):
    data = _probe_scene(tmp_path, monkeypatch, _reader_with(_CLEAN_MAIN))
    status, why = CA.run_probe(PROBE, data_dir=data)
    assert status == CA.NOT_SATISFIED and "Изменится ли риск" in why and "запрещённых отрезков 0" in why


def test_probe_is_satisfied_only_when_screen_is_clean_and_every_output_reaches(tmp_path, monkeypatch):
    data = _probe_scene(tmp_path, monkeypatch, _reader_with(_CLEAN_MAIN))
    spec = dict(OU.OUTPUT_SPEC)
    spec["Изменится ли риск"] = {"field": "verdict", "value_kind": "phrase", "phrases": ("риск не меняется",),
                                 "brief_key": None, "number_kind": "x"}
    spec["Нужна ли моя реакция"] = {"field": "verdict", "value_kind": "phrase", "phrases": ("реакция не нужна",),
                                    "brief_key": None, "number_kind": "x"}
    monkeypatch.setattr(OU, "OUTPUT_SPEC", spec)
    status, why = CA.run_probe(PROBE, data_dir=data)
    assert status == CA.SATISFIED, why
    # тот же экран с ОДНИМ запрещённым отрезком — уже не исполнено
    monkeypatch.setattr(OU, "live_report_reader", _reader_with(_CLEAN_MAIN + "\n(ECON-10)"))
    status, why = CA.run_probe(PROBE, data_dir=data)
    assert status == CA.NOT_SATISFIED and "ECON-10" in why


def test_probe_is_unmeasured_without_a_report(tmp_path, monkeypatch):
    data = _probe_scene(tmp_path, monkeypatch, _reader_failing)
    status, why = CA.run_probe(PROBE, data_dir=data)
    assert status == CA.UNMEASURED and "не собран" in why


def test_probe_is_unmeasured_without_the_ledger(tmp_path, monkeypatch):
    data = _probe_scene(tmp_path, monkeypatch, _reader_with(_CLEAN_MAIN), records=None)
    status, why = CA.run_probe(PROBE, data_dir=data)
    assert status == CA.UNMEASURED and OU.RECORD_REL in why


def test_probe_unmeasured_reach_is_unmeasured_not_a_verdict(tmp_path, monkeypatch):
    main = _CLEAN_MAIN.replace("возможная доходность 4,01 %", "возможная доходность 0,43 %")
    data = _probe_scene(tmp_path, monkeypatch, _reader_with(main), records=_records(target_apy_pp=0.43))
    status, why = CA.run_probe(PROBE, data_dir=data)
    assert status == CA.UNMEASURED and "Потенциальная доходность" in why


def test_probe_does_not_pass_by_substring(tmp_path, monkeypatch):
    # экран, где все слова владельца перечислены ИМЕНАМИ, но значения не напечатаны
    names_only = " · ".join(OU.OWNER_OUTPUTS) + "\n" + OU.HEADLINE_FOOTER_WORDS
    data = _probe_scene(tmp_path, monkeypatch, _reader_with(names_only))
    status, why = CA.run_probe(PROBE, data_dir=data)
    assert status == CA.NOT_SATISFIED
