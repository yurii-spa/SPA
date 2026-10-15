"""DIRECTOR-OS-UX-02 (ADR-762, RFC-690): the owner view — a deterministic presentation layer over
Company Truth — and the acceptance probe that judges it.

All scenes are the FIXED fixture (a read-only snapshot of one real bundle) and a fixed clock; nothing
here reads production files. Every guard has a control in the other direction.
"""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from spa_core.monitoring import card_acceptance as ca
from spa_core.studio_os import owner_view as ov

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "owner_view" / "mission_fixture.json"
NOW = datetime(2026, 10, 9, 7, 15, tzinfo=timezone.utc)  # FROZEN-DATE-OK: injected-clock — ov.build(model, NOW)
PROBE = ca.PROBES["director_os_owner_view_section"]


@pytest.fixture()
def scene():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _view(model):
    return ov.build(model, NOW)


# ── determinism & shape ─────────────────────────────────────────────────────────────────────────
def test_same_input_same_output(scene):
    assert _view(copy.deepcopy(scene)) == _view(copy.deepcopy(scene))


def test_every_metric_carries_source_time_unit_confidence(scene):
    ms = ov.metrics(_view(scene)["sections"])
    assert len(ms) >= 15
    for m in ms:
        for k in ("source", "measured_at", "updated_at", "unit", "confidence", "confidence_ru"):
            assert k in m, (m.get("label"), k)
        assert m["confidence"] in ov.CONFIDENCE


def test_main_texts_carry_no_jargon(scene):
    hits = [(p, ov.jargon_hits(t)) for p, t in ov.main_texts(_view(scene)["sections"]) if ov.jargon_hits(t)]
    assert hits == []


def test_jargon_scan_is_able_to_fail():
    # positive control: the same scanner catches every token class the owner listed
    for raw in ("NAV 101", "APY 4%", "ADR-417", "P1 bug", "CI red", "E2E", "READY", "BLOCKED",
                "launchctl bootout", "com.spa.resource_guard", "exit_nonzero:1", "intent=active",
                "COMPARISON_NOT_MEASURED"):
        assert ov.jargon_hits(raw), raw
    assert ov.jargon_hits("Стоимость портфеля") == []


def test_plain_translates_or_neutralises_every_jargon_class():
    s = ov.plain("**ADR-417**: `com.spa.resource_guard` exit_nonzero:1, APY и NAV, COMPARISON_NOT_MEASURED")
    assert ov.jargon_hits(s) == [], s
    assert "решение № 417" in s and "фоновая задача" in s


def test_main_texts_skip_technical_details(scene):
    # the raw codes are still there for the curious — one tap away, never on the main level
    view = _view(scene)["sections"]
    tech = json.dumps([m["technical"] for m in ov.metrics(view)], ensure_ascii=False)
    assert "LIVE_NOT_APPROVED" in tech
    assert all("LIVE_NOT_APPROVED" not in t for _, t in ov.main_texts(view))


# ── real money: only from capital.real_capital, never a literal ───────────────────────────────────
def test_real_money_reads_the_canon(scene):
    scene["capital"]["real_capital"]["usd"] = 1234
    real = _view(scene)["sections"]["money"]["real"]
    assert real["confidence"] == ov.MEASURED and real["text"].startswith("$1 234")
    assert real["source"].startswith("capital.real_capital")


def test_absent_real_money_is_not_measured_not_zero(scene):
    scene["capital"].pop("real_capital")
    scene["overview"]["capital"].pop("real_capital")
    real = _view(scene)["sections"]["money"]["real"]
    assert real["confidence"] == ov.NOT_MEASURED and "$" not in real["text"]


def test_unknown_real_money_sum_is_not_measured(scene):
    scene["capital"]["real_capital"]["usd"] = None
    real = _view(scene)["sections"]["overview"]["money"]["real"]
    assert real["confidence"] == ov.NOT_MEASURED and real["text"].startswith("Не измерено")


def test_unrecognised_real_money_state_is_an_interpretation_problem(scene):
    scene["capital"]["real_capital"]["state"] = "SOMETHING_NEW"
    real = _view(scene)["sections"]["money"]["real"]
    assert real["confidence"] == ov.INTERPRETATION_PROBLEM and "Проблема отображения" in real["text"]


def test_no_money_literal_in_owner_view_source():
    src = (Path(ov.__file__)).read_text(encoding="utf-8")
    assert not re.search(r"usd\s*=\s*0\b|\"\$0\"|'\$0'", src)


# ── unknown stays unknown ─────────────────────────────────────────────────────────────────────────
def test_not_measured_cell_reads_as_words(scene):
    scene["truth"]["capital"]["defi"]["books"]["conservative"]["state"] = "NOT_MEASURED"
    m = _view(scene)["sections"]["money"]["paper"]["items"][0]
    assert m["confidence"] == ov.NOT_MEASURED and m["text"].startswith("Не измерено")
    assert not re.search(r"\d+,\d\d", m["text"])


def test_unknown_cell_state_is_never_success(scene):
    scene["truth"]["studio"]["tasks"]["state"] = "WHATEVER"
    t = _view(scene)["sections"]["work"]["now"]["items"][2]
    assert t["confidence"] == ov.INTERPRETATION_PROBLEM and t["tone"] == "problem"


def test_stale_cell_names_the_last_value_time(scene):
    b = scene["truth"]["capital"]["defi"]["books"]["conservative"]
    b["freshness"] = {"age_min": 5000, "stale_after_min": 1560, "rule": "fallback"}
    m = _view(scene)["sections"]["money"]["paper"]["items"][0]
    assert m["confidence"] == ov.STALE and "Нет свежих данных (последнее значение: 2026-10-09 08:00 Мадрид" in m["text"]


def test_accumulating_book_says_how_far_not_zero(scene):
    m = _view(scene)["sections"]["money"]["paper"]["items"][1]
    assert m["confidence"] == ov.NOT_MEASURED and "копится история: 8 из 30" in m["text"]


# ── overview / work semantics ─────────────────────────────────────────────────────────────────────
def test_owner_questions_only_from_the_owner_group_money_first(scene):
    q = _view(scene)["sections"]["overview"]["questions"]
    assert q["count"] == len(scene["truth"]["decisions"]["groups"]["owner"]) == 3
    assert [r["subject"] for r in q["items"]] == ["Реальные деньги", "Реальные деньги",
                                                  "Необратимое или внешнее действие"]
    assert [r["age_days"] for r in q["items"]][:2] == [20, 18]


def test_undeclared_subject_is_named_not_hidden(scene):
    scene["truth"]["decisions"]["groups"]["owner"][0]["subject_key"] = None
    q = _view(scene)["sections"]["overview"]["questions"]
    assert any(r["subject"] == "Тема не объявлена" for r in q["items"])


def test_headline_points_at_the_oldest_money_question(scene):
    hl = _view(scene)["sections"]["overview"]["headline"]
    assert hl["main"] == "Ждут вашего решения: 3" and "Пять процентов кэша" in hl["next"]


def test_release_feed_limit_is_not_a_count(scene):
    s = _view(scene)["sections"]["work"]["done"]["summary"]
    assert len(scene["release_feed"]["items"]) >= ov.RELEASE_FEED_LIMIT
    assert s["text"].startswith(f"не меньше {ov.RELEASE_FEED_LIMIT}")
    scene["release_feed"]["items"] = scene["release_feed"]["items"][:3]
    assert _view(scene)["sections"]["work"]["done"]["summary"]["text"] == "3"


def test_plan_has_no_percent_and_states_are_words(scene):
    plan = _view(scene)["sections"]["work"]["plan"]
    assert all("%" not in r["state"] for r in plan["rows"])
    # ARB 09.10: a «queued» row whose own note says done is a named contradiction, not a plain state
    allowed = set(ov.ROADMAP_STATE_RU.values()) | {"Противоречие: в плане «в очереди», а в заметке — «сделано»"}
    assert {r["state"] for r in plan["rows"]} <= allowed


def test_blocked_work_names_the_stopped_task_and_that_its_card_has_no_reason(scene):
    """ARB 09.10: the stopped task is named from the board; its card has no reason field filled
    (measured on a copy of the live tracker: 1 blocked card, 0 with blocked_by / «Следующий шаг»)."""
    b = _view(scene)["sections"]["work"]["blocking"]
    assert b["known_reason"] is False and b["reason_state"] == "not_in_card"
    assert "нет отдельного поля для причины" in b["text"]
    (x,) = b["stopped"]
    assert x["title"].startswith("Страж дрейфа флота")
    assert x["reason_text"] == "Причина не указана в карточке"
    assert x["next_text"] == "Следующий шаг не указан в карточке"
    assert "orchestrator_queue" not in json.dumps({k: v for k, v in b.items() if k != "technical"}, ensure_ascii=False)
    assert "orchestrator_queue" in json.dumps(b["technical"], ensure_ascii=False)


def test_blocked_work_shows_the_reason_and_next_step_the_card_gives(scene):
    items = scene["truth"]["studio"]["tasks"]["blocked_items"]
    items[0]["reason"] = "ждёт ответа владельца по лимиту кэша"
    items[0]["next_step"] = "после ответа — свести правило в одно место"
    b = _view(scene)["sections"]["work"]["blocking"]
    (x,) = b["stopped"]
    assert x["reason_text"] == "Причина: ждёт ответа владельца по лимиту кэша"
    assert x["next_text"].startswith("Следующий шаг: после ответа")
    assert b["reason_state"] == "known" and b["known_reason"] is True


def test_older_model_without_the_list_still_says_not_measured(scene):
    scene["truth"]["studio"]["tasks"].pop("blocked_items")
    b = _view(scene)["sections"]["work"]["blocking"]
    assert "не измерено" in b["text"] and b["reason_state"] == "not_in_model" and b["stopped"] == []


def test_board_carries_the_cards_own_reason_and_next_step(tmp_path):
    from spa_core.studio_os import build_loop as bl
    (tmp_path / "a.md").write_text("---\ntitle: A\nstatus: blocked\nblocked_by: ждёт ключ\ncreated: 2026-09-01\n---\n"
                                   "## Следующий шаг\nполучить ключ\n\n## Прочее\nx\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("---\ntitle: B\nstatus: blocked\n---\nтекст\n", encoding="utf-8")
    rows = {r["card"]: r for r in bl.board(tmp_path)["blocked"]}
    assert rows["a"]["blocked_by"] == "ждёт ключ" and rows["a"]["next_step"] == "получить ключ"
    assert rows["b"]["blocked_by"] is None and rows["b"]["next_step"] is None


def test_paper_money_is_labelled_as_a_model(scene):
    p = _view(scene)["sections"]["money"]["paper"]
    assert "реальные деньги здесь не двигаются" in p["note"] and "Модель" in p["note"]
    # Wave 2 method (ARB 09.10): the limitation is the unrecorded start time, not «method not in force»
    assert any("Время начальной оценки" in x for x in p["limitations"])


# ── the acceptance probe, both directions (.claude/rules/acceptance.md п. 3) ────────────────────────
@pytest.mark.parametrize("sec", ["overview", "work", "money", "decisions", "protection"])
def test_probe_is_green_on_the_whole_contour(sec):
    verdict, why = PROBE(sec)
    assert verdict == ca.SATISFIED, why


def test_probe_refuses_an_unnamed_section():
    # task D made «decisions» and «protection» real sections; an unknown name is still refused
    assert PROBE("")[0] == ca.UNMEASURED and PROBE("settings")[0] == ca.UNMEASURED


def test_probe_without_a_scene_is_unmeasured(tmp_path):
    v, why = ca._probe_director_os_owner_view_section("money", fixture=str(tmp_path / "none.json"))
    assert v == ca.UNMEASURED and "не прочитана" in why


def test_probe_red_when_a_metric_loses_its_source(monkeypatch):
    real = ov.metric

    def broken(*a, **k):
        m = real(*a, **k)
        m.pop("source")
        return m
    monkeypatch.setattr(ov, "metric", broken)
    v, why = PROBE("work")
    assert v == ca.NOT_SATISFIED and "источника" in why


def test_probe_red_when_jargon_reaches_a_main_text(monkeypatch):
    monkeypatch.setattr(ov, "plain", lambda s: s if isinstance(s, str) else None)
    v, why = PROBE("overview")
    assert v == ca.NOT_SATISFIED and "жаргон" in why


def test_probe_red_when_real_money_is_a_literal(monkeypatch):
    lit = lambda model, updated: ov.metric("Реальные деньги", "$0 — не разрешены", confidence=ov.MEASURED,
                                           source="capital.real_capital", measured_at=None, updated_at=updated,
                                           unit="USD")
    monkeypatch.setattr(ov, "real_money", lit)
    v, why = PROBE("money")
    assert v == ca.NOT_SATISFIED and "capital.real_capital" in why


def test_probe_red_when_unknown_becomes_a_number(monkeypatch):
    real = ov._cell_confidence
    monkeypatch.setattr(ov, "_cell_confidence", lambda cell: (ov.MEASURED, None) if isinstance(cell, dict)
                        else real(cell))
    v, why = PROBE("work")
    assert v == ca.NOT_SATISFIED and "не измерено" in why


def test_probe_red_when_the_section_is_missing(monkeypatch):
    monkeypatch.setattr(ov, "work", lambda model, updated: None)
    v, why = PROBE("work")
    assert v == ca.NOT_SATISFIED and "не построен" in why



# ── task D: Решения ───────────────────────────────────────────────────────────────────────────────
def _dec(scene):
    return _view(scene)["sections"]["decisions"]


def test_decisions_list_only_the_owner_queue_money_first(scene):
    d = _dec(scene)
    assert [i["id"] for i in d["owner"]] == [i["id"] for i in _view(scene)["sections"]["overview"]["questions"]["items"]]
    assert {g["key"]: g["count"] for g in d["groups"]} == {"undeclared": 11, "accepted": 1, "prod_only": 11}


def test_card_version_is_deterministic_and_follows_content(scene):
    c = scene["truth"]["decisions"]["groups"]["owner"][0]
    v1, v2 = ov.card_version(dict(c)), ov.card_version(dict(c))
    assert v1["fingerprint"] == v2["fingerprint"] and re.fullmatch(r"[0-9a-f]{64}", v1["fingerprint"])
    # ARB 09.10: with the full canonical text the fingerprint follows THAT text …
    full = [dict(x) for x in c["full_sections_ru"]]
    full[0]["text"] += " "
    assert ov.card_version(dict(c, full_sections_ru=full))["fingerprint"] != v1["fingerprint"]
    # … and without it, the shortened fields (the earlier path) still move it
    bare = {k: v for k, v in c.items() if k != "full_sections_ru"}
    assert ov.card_version(dict(bare, action_ru=c["action_ru"] + " "))["fingerprint"] != ov.card_version(bare)["fingerprint"]
    # a field the cockpit does not see cannot move the version — and that limit is NAMED
    assert ov.card_version(dict(c, telegram_link="x"))["fingerprint"] == v1["fingerprint"]
    # ARB 09.10: it is a fingerprint of the VISIBLE text, explicitly not the version of the full decision
    # with the full canonical text: not partial, still explicitly NOT a decision version (ARB 09.10)
    assert v1["partial"] is False and "не привязан" in v1["text"] and v1["is_decision_version"] is False
    vb = ov.card_version(bare)
    assert vb["partial"] is True and "сокращённый" in vb["text"] and "не версия полного решения" in vb["text"]


def test_card_without_text_has_an_unmeasured_version_not_a_hash():
    v = ov.card_version({"id": "x"})
    assert v["measured"] is False and v["fingerprint"] is None and "не посчитан" in v["text"]


def test_ready_card_routes_only_to_telegram(scene):
    for it in _dec(scene)["owner"]:
        assert it["answer"]["kind"] == "READY" and it["answer"]["link"].startswith("https://t.me/")


@pytest.mark.parametrize("field", ["action_ru", "reason_ru", "done_when_ru", "title_ru"])
def test_unprepared_card_is_blocked_in_words(scene, field):
    scene["truth"]["decisions"]["groups"]["owner"][0][field] = ""
    it = _dec(scene)["owner"][0] if field != "title_ru" else next(
        i for i in _dec(scene)["owner"] if i["title"] == "Без названия")
    assert it["answer"]["kind"] == "BLOCKED_UNPREPARED" and it["answer"]["link"] is None
    assert "не хватает" in it["answer"]["reason"]


def test_undeclared_subject_blocks_the_answer(scene):
    scene["truth"]["decisions"]["groups"]["owner"][0]["subject_key"] = None
    it = next(i for i in _dec(scene)["owner"] if i["subject"] == "Тема не объявлена")
    assert it["answer"]["kind"] == "BLOCKED_UNPREPARED" and "тема владельца" in it["answer"]["reason"]


def test_card_without_a_route_is_blocked(scene):
    scene["truth"]["decisions"]["groups"]["owner"][0]["telegram_link"] = "javascript:alert(1)"
    it = _dec(scene)["owner"][0]
    assert it["answer"]["kind"] == "BLOCKED_UNPREPARED" and "механизм ответа" in it["answer"]["reason"]


def test_answered_card_offers_no_second_answer(scene):
    g = scene["truth"]["decisions"]["groups"]
    first = g["owner"][0]
    g["answered"].append({"id": first["id"], "title_ru": first["title_ru"], "owner_answer_ru": "2",
                          "answered_at": "2026-10-09T06:00:00+00:00"})
    it = next(i for i in _dec(scene)["owner"] if i["id"] == first["id"])
    assert it["answer"]["kind"] == "ANSWERED" and it["answer"]["link"] is None
    assert "Ответ уже записан 2026-10-09 08:00 Мадрид" in it["answer"]["text"]
    assert "не записывает" in it["answer"]["reason"]


def test_history_names_answers_and_that_their_version_is_not_recorded(scene):
    h = _dec(scene)["history"]
    assert [x["answer"] for x in h] == ["Ответ: вариант 1", "Ответ: вариант 1", "Ответ: нет", "Ответ: нет"]
    assert all(x["version"] == "на какой текст дан ответ — не записано" and "Мадрид" in x["at_ru"] for x in h)


def test_missing_fields_say_not_in_card_never_invented(scene):
    it = _dec(scene)["owner"][0]
    assert it["rollback"] == "не указано в карточке"
    assert len(it["options"]) == 2 and it["consequences"] == "описаны в вариантах ответа"
    # ARB 09.10: the second card's options were invisible in the shortened text; with the full
    # canonical text in the cockpit nothing is «hidden in Telegram» any more
    full_card = _dec(scene)["owner"][1]
    assert full_card["full_available"] and "сокращённом тексте" not in str(full_card["alternatives"])
    sc = copy.deepcopy(scene)
    sc["truth"]["decisions"]["groups"]["owner"][1].pop("full_sections_ru", None)
    cut = _dec(sc)["owner"][1]
    assert cut["options"] == [] and "сокращённом тексте" in cut["alternatives"]


def test_queue_not_read_is_not_measured(scene):
    scene["truth"]["decisions"].pop("groups")
    d = _dec(scene)
    assert d["owner"] == [] and d["summary"]["confidence"] == ov.NOT_MEASURED


# ── task D: Защита ────────────────────────────────────────────────────────────────────────────────
def _prot(scene, now=NOW):
    return ov.build(scene, now)["sections"]["protection"]


def test_partially_checked_system_is_never_all_right(scene):
    p = _prot(scene)
    assert p["verdict"]["confidence"] == ov.PARTIAL
    assert "в порядке" not in p["verdict"]["text"].lower()
    fleet = next(c for c in p["checks"] if c["label"] == "Фоновые задачи")
    assert fleet["confidence"] == ov.PARTIAL and "85 из 92" in fleet["text"]


def test_fully_checked_system_can_say_all_right(scene):
    p = _prot(ca._owner_view_all_healthy(scene))
    assert p["verdict"]["confidence"] == ov.MEASURED and "Всё в порядке" in p["verdict"]["text"]


def test_backups_are_honest_about_the_off_host_copy(scene):
    b = _prot(scene)["backups"]
    assert b["off_host"]["confidence"] == ov.PARTIAL and "не измерено" in b["off_host"]["text"]
    assert b["recovery"]["text"] == "Учебное восстановление прошло: 2026-10-09 06:56 Мадрид (CEST)"
    assert b["local"]["text"].startswith("Последняя копия: 2026-10-09 07:15 Мадрид")


def test_failed_or_unknown_drill_is_not_success(scene):
    rec = scene["truth"]["studio"]["backups"]["recovery"]
    rec["drill_result"] = "FAILED"
    assert _prot(scene)["backups"]["recovery"]["tone"] == "problem"
    rec["drill_result"] = "SOMETHING"
    assert _prot(scene)["backups"]["recovery"]["confidence"] == ov.INTERPRETATION_PROBLEM


def test_stale_snapshot_says_so(scene):
    late = datetime(2026, 10, 9, 9, 0, tzinfo=timezone.utc)
    c = _prot(scene, late)["checks"][0]
    assert c["confidence"] == ov.STALE and "Нет свежих данных" in c["text"]


def test_unknown_system_state_is_an_interpretation_problem(scene):
    scene["overview"]["system"]["state"] = "PURPLE"
    c = _prot(scene)["checks"][1]
    assert c["confidence"] == ov.INTERPRETATION_PROBLEM


def test_problems_say_what_to_do_and_keep_commands_in_details(scene):
    rows = _prot(scene)["problems"]["rows"]
    assert len(rows) == 8 and all(r["action"] for r in rows)
    retired = next(r for r in rows if r["technical"]["code"] == "retired_but_loaded")
    assert "launchctl" in retired["technical"]["commands"] and "launchctl" not in retired["action"]


def test_decisions_and_protection_main_texts_carry_no_jargon(scene):
    v = _view(scene)["sections"]
    for sec in ("decisions", "protection"):
        hits = [(p, ov.jargon_hits(t)) for p, t in ov.main_texts(v[sec]) if ov.jargon_hits(t)]
        assert hits == [], (sec, hits[:3])


# ── task D: the probe, red per broken link ─────────────────────────────────────────────────────────
def test_probe_red_when_version_ignores_content(monkeypatch):
    monkeypatch.setattr(ov, "card_version", lambda card: {"measured": True, "fingerprint": "0" * 64,
                                                          "short": "00000000", "partial": False, "text": "Версия"})
    v, why = PROBE("decisions")
    assert v == ca.NOT_SATISFIED and "версию" in why


def test_probe_red_when_unprepared_card_keeps_its_button(monkeypatch):
    monkeypatch.setattr(ov, "_REQUIRED", ())
    v, why = PROBE("decisions")
    assert v == ca.NOT_SATISFIED and "неподготовленная" in why


def test_probe_red_when_answered_card_is_offered_again(monkeypatch):
    real = ov._decision_card
    monkeypatch.setattr(ov, "_decision_card", lambda d, answered, updated: real(d, {}, updated))
    v, why = PROBE("decisions")
    assert v == ca.NOT_SATISFIED and "повторно" in why


def test_probe_red_when_partial_is_called_all_right(monkeypatch):
    real = ov.protection

    def lying(model, updated, now):
        p = real(model, updated, now)
        p["verdict"] = ov.metric("Итог", "Всё в порядке", confidence=ov.MEASURED, source="x",
                                 measured_at=None, updated_at=updated)
        return p
    monkeypatch.setattr(ov, "protection", lying)
    v, why = PROBE("protection")
    assert v == ca.NOT_SATISFIED and "в порядке" in why


def test_probe_red_when_the_icloud_copy_is_overclaimed(monkeypatch):
    real = ov.backups

    def over(truth, updated):
        b = real(truth, updated)
        b["off_host"] = ov.metric("Копия вне Mac", "Копия в iCloud сверена", confidence=ov.MEASURED, source="x",
                                  measured_at=None, updated_at=updated)
        return b
    monkeypatch.setattr(ov, "backups", over)
    v, why = PROBE("protection")
    assert v == ca.NOT_SATISFIED and "iCloud" in why


def test_probe_red_when_the_verdict_can_never_be_all_right(monkeypatch):
    real = ov.protection

    def never(model, updated, now):
        p = real(model, updated, now)
        p["verdict"]["text"] = "Есть замечания"
        p["verdict"]["confidence"] = ov.PARTIAL
        return p
    monkeypatch.setattr(ov, "protection", never)
    v, why = PROBE("protection")
    assert v == ca.NOT_SATISFIED and "итог сломан" in why


# ── task E: the five owner scenarios — green on the full contour, red on each broken link ──────────
def _sections(scene):
    return ov.build(copy.deepcopy(scene), NOW)["sections"]


def test_scenario_probe_is_satisfied_on_the_fixture():
    verdict, why = PROBE("scenarios")
    assert verdict == ca.SATISFIED, why


def _break(path, value):
    def fn(s):
        cur = s
        for k in path[:-1]:
            cur = cur[k] if not isinstance(k, int) else cur[k]
        if value is _DROP:
            cur.pop(path[-1], None)
        else:
            cur[path[-1]] = value
        return s
    return fn


_DROP = object()


@pytest.mark.parametrize("name,mutate,needle", [
    ("1-no-next-step", _break(["overview", "headline", "next"], ""), "сценарий 1"),
    ("1-jargon-headline", _break(["overview", "headline", "main"], "ADR-762 READY"), "сценарий 1"),
    ("1-no-time", _break(["overview", "headline", "updated_at_ru"], None), "сценарий 1"),
    ("2-question-missing", lambda s: (s["overview"]["questions"]["items"].pop(), s)[1], "сценарий 2"),
    ("2-no-consequences", _break(["decisions", "owner", 0, "consequences"], ""), "сценарий 2"),
    ("2-no-version", _break(["decisions", "owner", 0, "version"], {}), "сценарий 2"),
    ("2-unknown-answer", _break(["decisions", "owner", 0, "answer"], {"kind": "MAYBE"}), "сценарий 2"),
    ("3-real-not-canon", _break(["money", "real", "source"], "app.js fallback"), "сценарий 3"),
    ("3-paper-not-model", _break(["money", "paper", "note"], "Портфель"), "сценарий 3"),
    ("3-backtest-as-money", _break(["money", "research", "note"], "Доходность"), "сценарий 3"),
    ("4-no-blocking", _break(["work", "blocking", "text"], ""), "сценарий 4"),
    ("4-unknown-reason-unnamed", lambda s: (s["work"]["blocking"].update(text="Остановлено задач: 1.", stopped=[]), s)[1],
     "сценарий 4"),
    ("4-card-silence-unnamed", _break(["work", "blocking", "stopped", 0, "reason_text"], "Причина: —"), "сценарий 4"),
    ("4-card-reason-hidden", lambda s: (s["work"]["blocking"]["stopped"][0].update(reason="ждёт ключ"), s)[1],
     "сценарий 4"),
    ("4-reason-claimed-known", _break(["work", "blocking", "reason_state"], "known"), "сценарий 4"),
    ("4-stopped-untitled", _break(["work", "blocking", "stopped", 0, "title"], ""), "сценарий 4"),
    ("5-no-recovery", _break(["protection", "backups", "recovery"], {}), "сценарий 5"),
    ("5-recovery-undated", _break(["protection", "backups", "recovery", "measured_at_ru"], None), "сценарий 5"),
])
def test_scenario_contour_names_each_broken_link(scene, name, mutate, needle):
    s = _sections(scene)
    assert ca.owner_view_scenarios_contour(ov, s) is None          # control: the whole contour is green
    bad = ca.owner_view_scenarios_contour(ov, mutate(s))
    assert bad and bad.startswith(needle), (name, bad)


def test_scenario_probe_unmeasured_without_a_scene(tmp_path):
    verdict, why = ca._probe_owner_view_scenarios(fixture=str(tmp_path / "absent.json"))
    assert verdict == ca.UNMEASURED and "сцена" in why


# ── ARB 09.10: safe decision variant, dictionary, check groups ───────────────────────────────────
from spa_core.studio_os import owner_dictionary as od  # noqa: E402

_LATIN_RUN = re.compile(r"(?:\b[A-Za-z][A-Za-z&/().'-]*\b[\s·:,-]*){3,}")
# Brand/product names the owner reads as names, not as English text.
_LATIN_OK = re.compile(r"\b(Earn DeFi|DeFi|iCloud|Mac|Base|Oracle|Telegram|iPhone)\b")


def test_every_roadmap_stage_in_the_fixture_has_a_russian_name(scene):
    unknown = [it["epic"] for it in scene["truth"]["studio"]["roadmap"]["value"]["items"]
               if not od.stage_title(it["epic"])["known"]]
    assert unknown == [], f"нет строки в owner_dictionary.ROADMAP_RU для: {unknown}"


def test_dictionary_is_deterministic_and_unknown_english_is_neutral_not_shown():
    a, b = od.stage_title("RM-TRUTH-01 · Company truth"), od.stage_title("RM-TRUTH-01 · Company truth")
    assert a == b and a["known"] and a["original"] == "RM-TRUTH-01 · Company truth"
    x = od.stage_title("Brand new engine nobody translated")
    assert x["known"] is False and x["text"] == od.UNKNOWN_STAGE and "Brand" not in x["text"]
    assert od.stage_title("Уже по-русски")["text"] == "Уже по-русски"


def test_no_english_stage_names_on_main_screens(scene):
    v = _view(scene)["sections"]
    texts = [t for sec in ("overview", "work") for _p, t in ov.main_texts(v[sec])]
    bad = [t for t in texts if isinstance(t, str) and _LATIN_RUN.search(_LATIN_OK.sub("", t))]
    assert bad == []


def test_plan_contradiction_is_named_and_groups_cover_every_row(scene):
    plan = _view(scene)["sections"]["work"]["plan"]
    assert sum(g["count"] for g in plan["groups"]) == len(plan["rows"])
    conflict = [r for r in plan["rows"] if r["group"] == "conflict"]
    assert conflict and all("Противоречие" in r["state"] and r["state_known"] is False for r in conflict)


def test_blocked_reason_names_what_is_missing_and_how_to_get_it(scene):
    # ARB 09.10: «only the number» is now true only for an OLDER model without blocked_items
    scene["truth"]["studio"]["tasks"].pop("blocked_items")
    b = _view(scene)["sections"]["work"]["blocking"]
    assert "не измерено" in b["text"] and "только число" in b["text"]
    assert "orchestrator_queue.py list --status blocked" in str(b["technical"])
    assert "orchestrator_queue" not in b["text"]          # the command lives in details only


def test_check_groups_partition_every_check_once(scene):
    p = _view(scene)["sections"]["protection"]
    groups = {g["key"]: g for g in p["check_groups"]}
    assert set(groups) == {"verified", "unverified", "problem"}
    names = [n for g in p["check_groups"] for n in g["items"]]
    assert sorted(names) == sorted(c["label"] for c in p["checks"])


def test_partial_and_unknown_checks_are_never_counted_as_verified(scene):
    p = _view(scene)["sections"]["protection"]
    verified = next(g for g in p["check_groups"] if g["key"] == "verified")["items"]
    for c in p["checks"]:
        if c["confidence"] != ov.MEASURED or c["tone"] in ("warn", "problem"):
            assert c["label"] not in verified


def test_decision_texts_promise_no_version_bound_confirmation(scene):
    d = _dec(scene)
    assert "Пульт не проверяет ответ в Телеграме" in d["note"]
    for it in d["owner"]:
        assert it["version"]["is_decision_version"] is False
        if it["answer"]["kind"] == "READY":
            assert it["answer"]["reason"] == ov.HONEST_ANSWER_NOTE
    flat = json.dumps(d, ensure_ascii=False)
    for claim in ("относится к той версии", "Версия карточки", "версия решения", "Вы отвечаете на версию"):
        assert claim not in flat


# ── ARB 09.10 round 4 (DIRECTOR-OS-UX-02 over Wave 2): money labels, first screen, full decision text ──
def test_money_leads_with_the_period_return_not_a_bar_count_rate(scene):
    m = _view(scene)["sections"]["money"]["paper"]["items"][0]
    assert m["text"].startswith("+1,41\u00a0% за 22.06.2026–08.10.2026 (модель, бумага)")
    assert "−0,04" in m["text"] or "-0,04" in m["text"]
    assert m["secondary_short"] == "Оценочный годовой эквивалент: 4,85\u00a0%"
    for w in ("ACT/365 Fixed", "время начальной оценки не записано", "не прогноз"):
        assert w in m["secondary"]
    assert m["data_date_ru"] == "Данные на 08.10.2026"


def test_no_old_rate_or_bar_count_wording_anywhere_owner_facing(scene):
    view = _view(scene)
    texts = " | ".join(t for _, t in ov.main_texts(view["sections"]))
    for bad in ("4,90", "4.90", "засчитанным дням", "по числу засчитанных", "засчитанных дней"):
        assert bad not in texts, bad


def test_first_screen_says_real_money_and_the_mode_from_the_canon(scene):
    hl = _view(scene)["sections"]["overview"]["headline"]
    assert hl["real_line"] == "Настоящие деньги: $0"
    assert hl["mode_line"] == "Сейчас система работает на виртуальном капитале"
    # unknown real money is said, never filled with $0
    sc = copy.deepcopy(scene)
    sc["capital"]["real_capital"] = {"state": "UNKNOWN", "usd": None}
    sc.get("overview", {}).get("capital", {}).pop("real_capital", None)
    hl2 = ov.build(sc, NOW)["sections"]["overview"]["headline"]
    assert hl2["real_line"] == "Настоящие деньги: не измерено" and "не измерен" in hl2["mode_line"]


def test_decision_full_text_equals_the_canonical_card(scene):
    it = _dec(scene)["owner"][0]
    src = scene["truth"]["decisions"]["groups"]["owner"][0]["full_sections_ru"]
    assert it["full_available"] is True and it["full"] == src
    assert all(not x["text"].endswith("…") for x in it["full"]), "full text must not be cut"
    # short list text is a whole first sentence, never a cut
    assert it["short_why"] and not it["short_why"].endswith("…")
    assert it["short_next"].startswith("Ответь, одна это величина или две разные")


def test_full_text_reads_the_whole_card_body_from_the_tracker():
    from spa_core.studio_os import mission_control as mc
    body = "## Что случилось и почему это важно\n" + ("Длинный текст. " * 80) + "\n## Что от тебя нужно\n1. да\n2. нет\n"
    secs = mc.full_sections(body)
    assert [s["heading"] for s in secs] == ["Что случилось и почему это важно", "Что от тебя нужно"]
    assert len(secs[0]["text"]) > 400 and secs[1]["text"] == "1. да\n2. нет"


def test_fingerprint_is_named_not_a_decision_version(scene):
    v = _dec(scene)["owner"][0]["version"]
    assert v["is_decision_version"] is False and "не привязан" in v["text"]


# ── ARB 09.10 round 5: «Деньги» opens with two plain lines; the mode limitation is said once ──────
def test_money_screen_opens_with_real_money_and_virtual_capital(scene):
    m = _view(scene)["sections"]["money"]
    assert m["head"]["real_line"] == "Настоящие деньги: $0"
    assert m["head"]["mode_line"] == "Сейчас система работает на виртуальном капитале"
    # the explanation (incl. the readiness count) lives once, in the expandable detail
    assert "бумажная симуляция" in m["head"]["mode_detail"]
    assert "До настоящих денег:" in m["head"]["mode_detail"]


def test_money_head_never_fills_unknown_real_money_with_zero(scene):
    sc = copy.deepcopy(scene)
    sc["capital"]["real_capital"] = {"state": "UNKNOWN", "usd": None}
    sc.get("overview", {}).get("capital", {}).pop("real_capital", None)
    m = ov.build(sc, NOW)["sections"]["money"]
    assert m["head"]["real_line"] == "Настоящие деньги: не измерено"
    assert "$0" not in m["head"]["real_line"]


def test_money_head_amount_comes_from_the_canon_not_a_literal(scene):
    sc = copy.deepcopy(scene)
    sc["capital"]["real_capital"] = dict(sc["capital"]["real_capital"], usd=1234)
    sc.get("overview", {}).get("capital", {}).pop("real_capital", None)
    assert ov.build(sc, NOW)["sections"]["money"]["head"]["real_line"] == "Настоящие деньги: $1\u00a0234"


def test_owner_metric_uses_a_typographic_minus_but_leaves_dates_alone():
    m = ov.metric("x", "худшая просадка -0,04 % · с 2026-06-22", confidence=ov.MEASURED, source="s",
                  measured_at=None, updated_at=None)
    assert "−0,04 %" in m["text"] and "-0,04" not in m["text"]
    assert "2026-06-22" in m["text"]


def test_overview_money_block_does_not_repeat_the_virtual_capital_line(scene):
    o = _view(scene)["sections"]["overview"]
    assert "виртуальн" not in (o["money"].get("note") or "")
    assert o["headline"]["mode_line"] == "Сейчас система работает на виртуальном капитале"
