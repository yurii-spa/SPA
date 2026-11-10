"""Контроли §28 ТЗ «Portfolio CIO» — ADR-971.

Каждая проверка — контроль ОДНОГО звена прибора
:mod:`spa_core.analytics.decision_expiry_census`, и у каждой несущей претензии есть
контроль В ОБЕ СТОРОНЫ: зелёный на целом контуре и КРАСНЫЙ на порванном звене, с
названным звеном (`.claude/rules/acceptance.md`, п. 3).

ВРЕМЯ — ВХОД, А НЕ ОКРУЖЕНИЕ. Литеральных дат нет: единственный якорь берётся в
рантайме и передаётся прибору аргументом ``now=``; возраст ответа владельца считается
от отметки карточки до этого якоря.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import textwrap
import types

import pytest

from spa_core.analytics import decision_expiry_census as DX
from spa_core.analytics import pre_trade_check_census as PC
from spa_core.analytics.transaction_economics import UNMEASURED
from spa_core.monitoring import pre_trade_recheck_census as S49
from spa_core.monitoring import card_acceptance as CA


# ───────────────────────────── сцены ─────────────────────────────────────────

def _anchor() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def _event(eid: str, etype: str, ts: dt.datetime, snap: str,
           prev: str | None = None, data: dict | None = None) -> dict:
    return {"event_id": eid, "correlation_id": f"c-{eid}", "snapshot_id": snap,
            "event_type": etype, "timestamp": ts.isoformat(),
            "data": data or {}, "prev_event_id": prev}


def _chain(anchor: dt.datetime, *, window_s: float = 0.6) -> list[dict]:
    t0 = anchor - dt.timedelta(hours=1)
    snap = "scene:snapshot"
    return [
        _event("p", S49.EVENT_PROPOSAL, t0, snap),
        _event("v", S49.EVENT_VERDICT, t0 + dt.timedelta(seconds=0.2), snap, "p"),
        _event("x", S49.EVENT_EXECUTED, t0 + dt.timedelta(seconds=window_s), snap, "v",
               {"trade_id": "T1"}),
    ]


def _data_dir(tmp, rows: list[dict] | None, record: dict | None = None) -> str:
    d = tmp / "data"
    d.mkdir(parents=True, exist_ok=True)
    if rows is not None:
        (d / S49.CHAIN_FILENAME).write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    if record is not None:
        (d / DX._s25.CARRIER_ARTIFACT[DX.RECORD_CARRIER]).write_text(
            json.dumps(record) + "\n", encoding="utf-8")
    return str(d)


def _live_like_record(anchor: dt.datetime) -> dict:
    day = anchor.date().isoformat()
    return {"schema": "x", "book_id": "conservative", "decision_id": f"adr060-shadow-{day}",
            "cycle_date": day, "generated_at": anchor.isoformat(), "apy_as_of": anchor.isoformat(),
            "verdict": "HOLD", "capital_usd": 100_000.0}


def _card(tmp, body: str) -> str:
    p = tmp / "card.md"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return str(p)


_GOOD_CARD = """\
    ---
    title: x
    ---
    27. Pre-trade check
    что-то
    28. Decision expiry
    Каждое investment decision должно иметь TTL.
    Например:
    valid_until
    Если execution не произошел до TTL:
    решение нельзя выполнять без нового расчета.


    ⸻


    29. Emergency mode
    Обычная yield optimization и emergency risk management — разные процессы.
    """


def _root_with_register(tmp, records: list[dict], *, card_fm: str | None = None) -> str:
    """Одноразовый корень: реестр ответов + карточка ответа с шапкой."""
    root = tmp / "root"
    (root / "docs" / "decisions").mkdir(parents=True)
    (root / "nimbalyst-local" / "tracker").mkdir(parents=True)
    (root / DX.OWNER_ANSWER_REGISTER_REL).write_text(
        json.dumps({"schema": "owner-session-answers/1", "answers": records}),
        encoding="utf-8")
    if card_fm is not None:
        (root / DX.OWNER_ANSWER_CARD_REL).write_text(card_fm, encoding="utf-8")
    return str(root)


def _good_record(**over) -> dict:
    rec = {"card": DX.OWNER_ANSWER_CARD, "adr": "ADR-836", "choice": "А",
           "label": "свежесть 60 с на бумаге / 15 с вживую; срок годности решения 10 мин",
           "owner_text": "60 с на бумаге / 15 с вживую, решение 10 мин", "kind": "option"}
    rec.update(over)
    return rec


def _card_fm(answered_at: dt.datetime | None, status: str = "ingested") -> str:
    lines = ["---", "trackerStatus:", "  type: owner-decision", f"status: {status}"]
    if answered_at is not None:
        lines.append(f"owner_answered_at: {answered_at.isoformat()}")
    lines += ["---", "", "## Что случилось", "x"]
    return "\n".join(lines) + "\n"


# ───────────────────── паритет: константа ↔ карточка ─────────────────────────

def test_constants_agree_with_the_real_owner_card():
    """Несущая претензия: 1 требование / пример `valid_until` / 1 следствие — ПО КАРТОЧКЕ."""
    card = os.path.join(DX.REPO_ROOT, DX.CARD_REL)
    if not os.path.isfile(card):
        pytest.fail(f"карточка приказа не найдена: {card} — паритет НЕ ИЗМЕРЕН")
    r = DX.parity(card)
    assert r["parsed"]["measured"], r["parsed"]["reason"]
    assert r["agrees"] is True, r["mismatches"]
    assert r["parsed"]["examples"] == [DX.OWNER_EXAMPLE_FIELD]
    # Счёт заказа G959 СОШЁЛСЯ — и это измерено, а не предположено.
    assert r["order_undercount"] == 0


def test_parity_on_a_faithful_scene_card(tmp_path):
    r = DX.parity(_card(tmp_path, _GOOD_CARD))
    assert r["agrees"] is True, r["mismatches"]


def test_parity_names_a_missing_example(tmp_path):
    r = DX.parity(_card(tmp_path, _GOOD_CARD.replace("valid_until\n", "")))
    assert r["agrees"] is False
    assert any("число примеров: карточка 0" in m for m in r["mismatches"]), r["mismatches"]


def test_parity_names_a_second_consequence(tmp_path):
    body = _GOOD_CARD.replace("решение нельзя выполнять без нового расчета.\n",
                              "решение нельзя выполнять без нового расчета.\nи ещё одно.\n")
    r = DX.parity(_card(tmp_path, body))
    assert r["agrees"] is False
    assert any("число следствий: карточка 2" in m for m in r["mismatches"])
    assert r["order_undercount"] == 1


def test_unreadable_card_is_a_third_outcome_not_a_fallback(tmp_path):
    r = DX.parity(str(tmp_path / "нет-такого.md"))
    assert r["agrees"] is None
    assert "не прочитана" in r["parsed"]["reason"]
    assert r["order_undercount"] is None


def test_missing_second_border_refuses_to_count(tmp_path):
    r = DX.parity(_card(tmp_path, _GOOD_CARD.replace("29. Emergency mode", "29. Другое")))
    assert r["agrees"] is None
    assert "вторая граница" in r["parsed"]["reason"]


def test_missing_anchor_is_named(tmp_path):
    r = DX.parity(_card(tmp_path, _GOOD_CARD.replace("Например:", "К примеру:")))
    assert r["agrees"] is None
    assert "Например:" in r["parsed"]["reason"]


# ───────────────────────────── ось A: ответ владельца ────────────────────────

def test_axis_a_live_register_carries_the_owner_answer_and_its_numbers_agree():
    """Несущая претензия: владелец ОТВЕТИЛ (вариант А), числа реестра = константы прибора."""
    a = DX.import_owner_answer(DX.REPO_ROOT, now=_anchor())
    assert a["measured"], a.get("reason")
    assert a["record"] is not None, a.get("reason")
    assert a["record"]["choice"] == DX.OWNER_CHOICE
    assert a["parity"]["agrees"] is True, a["parity"]["mismatches"]
    assert a["parity"]["register_numbers"] == {"seconds": [60.0, 15.0], "minutes": [10.0]}
    assert isinstance(a["age_days"], float) and a["age_days"] > 0
    assert a["card_status"] == "ingested"


def test_axis_a_number_drift_between_register_and_constants_is_named(tmp_path):
    rec = _good_record(label="свежесть 90 с на бумаге / 15 с вживую; срок годности решения 10 мин")
    a = DX.import_owner_answer(_root_with_register(tmp_path, [rec], card_fm=_card_fm(_anchor())),
                               now=_anchor())
    assert a["parity"]["agrees"] is False
    assert any("допуски свежести" in m for m in a["parity"]["mismatches"])


def test_axis_a_choice_drift_is_named(tmp_path):
    rec = _good_record(choice="Б")
    a = DX.import_owner_answer(_root_with_register(tmp_path, [rec], card_fm=_card_fm(_anchor())),
                               now=_anchor())
    assert any("выбор" in m for m in a["parity"]["mismatches"])


def test_axis_a_card_name_is_compared_whole_not_by_substring(tmp_path):
    """ADR-839 R1: более длинное имя карточки — НЕ та запись."""
    rec = _good_record(card=DX.OWNER_ANSWER_CARD + "-2")
    a = DX.import_owner_answer(_root_with_register(tmp_path, [rec], card_fm=_card_fm(_anchor())),
                               now=_anchor())
    assert a["record"] is None and a["kind"] == "not_answered"


def test_axis_a_two_records_are_unmeasured_not_the_first_one(tmp_path):
    a = DX.import_owner_answer(_root_with_register(tmp_path, [_good_record(), _good_record()],
                                                   card_fm=_card_fm(_anchor())), now=_anchor())
    assert a["record"] is None and a["kind"] == UNMEASURED
    assert "2 записей" in a["reason"]


def test_axis_a_missing_register_is_unmeasured(tmp_path):
    a = DX.import_owner_answer(str(tmp_path), now=_anchor())
    assert a["measured"] is False and "реестр" in a["reason"]


def test_axis_a_age_is_computed_from_the_injected_now(tmp_path):
    now = _anchor()
    answered = now - dt.timedelta(days=13, hours=12)
    a = DX.import_owner_answer(_root_with_register(tmp_path, [_good_record()],
                                                   card_fm=_card_fm(answered)), now=now)
    assert a["age_days"] == pytest.approx(13.5, abs=0.01)


def test_axis_a_missing_answered_at_gives_no_age_not_zero(tmp_path):
    a = DX.import_owner_answer(_root_with_register(tmp_path, [_good_record()],
                                                   card_fm=_card_fm(None)), now=_anchor())
    assert a["age_days"] is None and a["answered_at"] is None


def test_axis_a_missing_card_keeps_the_register_answer_and_marks_status_unmeasured(tmp_path):
    a = DX.import_owner_answer(_root_with_register(tmp_path, [_good_record()]), now=_anchor())
    assert a["record"] is not None
    assert a["card_status"] == UNMEASURED and a["age_days"] is None


# ───────────────────── ось B: колонка владельца и её читатель ────────────────

def test_axis_b_live_column_carries_the_owner_dials_and_the_reader_reads_values():
    """ИЗМЕНЕНО НАМЕРЕННО (ADR-972, инв. #16). Несущая претензия #1089 («ручки нет,
    читатель берёт имя») была находкой, и находка закрыта исполнением ответа владельца:
    колонка v1.2 несёт обе ручки, читатель берёт значения, числа сходятся с ответом."""
    b = DX.measure_owner_column()
    assert b["measured"], b.get("reason")
    assert b["ttl_dial"] == "decision_ttl_s" and b["ttl_s"] == DX.OWNER_TTL_S
    assert b["tolerance_dial"] == "input_freshness_tolerance_s"
    assert b["tolerance_s"] == DX.OWNER_FRESHNESS_S["paper"]
    assert b["dials_n"] >= 16
    assert b["loader"]["kind"] == "reads_value", b["loader"]
    assert b["column_matches_answer"]["kind"] == "matches", b["column_matches_answer"]


def test_axis_b_names_dial_only_is_still_reachable_through_a_reader_that_drops_the_value(monkeypatch):
    """Контроль в обратную сторону: читатель, забывший значение, снова даёт names_dial_only."""
    real = S49.load_owner_tolerance

    def naming_only(params=None):
        out = real(params)
        out["tolerance_s"] = None
        out["ttl_s"] = None
        return out

    monkeypatch.setattr(S49, "load_owner_tolerance", naming_only)
    b = DX.measure_owner_column()
    assert b["loader"]["kind"] == "names_dial_only", b["loader"]
    assert "decision_ttl_s" in b["loader"]["reason"]


def test_axis_b_column_with_a_foreign_number_is_misexecution_not_execution():
    """Ручка есть, число чужое ⇒ `differs` с названным расхождением, а не «исполнено»."""
    scene = types.SimpleNamespace(decision_ttl_s=300.0, input_freshness_tolerance_s=60.0,
                                  version="scene", mode="paper")
    b = DX.measure_owner_column(params=scene)
    par = b["column_matches_answer"]
    assert par["kind"] == "differs"
    assert "300.0" in par["reason"] and "600" in par["reason"]
    pilot = types.SimpleNamespace(decision_ttl_s=600.0, input_freshness_tolerance_s=60.0,
                                  version="scene", mode="pilot")
    assert DX.measure_owner_column(params=pilot)["column_matches_answer"]["kind"] == "differs"
    unknown = types.SimpleNamespace(decision_ttl_s=600.0, input_freshness_tolerance_s=60.0,
                                    version="scene", mode="sandbox")
    assert DX.measure_owner_column(params=unknown)["column_matches_answer"]["kind"] == UNMEASURED


def test_axis_b_a_dial_in_the_column_would_be_seen():
    """Порванное звено наоборот: колонка С ручкой — прибор её называет."""
    scene = types.SimpleNamespace(decision_ttl_s=600.0, version="scene", mode="paper")
    b = DX.measure_owner_column(params=scene)
    assert b["ttl_dial"] == "decision_ttl_s"


def test_axis_b_reader_that_returns_a_value_flips_the_control(monkeypatch):
    real = S49.load_owner_tolerance

    def reading(params=None):
        out = real(params)
        if out.get("ttl_dial"):
            out["tolerance_s"] = 60.0
        return out

    monkeypatch.setattr(S49, "load_owner_tolerance", reading)
    b = DX.measure_owner_column()
    assert b["loader"]["kind"] == "reads_value"


def test_axis_b_reader_crash_is_unmeasured(monkeypatch):
    def boom(params=None):
        raise RuntimeError("сцена")

    monkeypatch.setattr(S49, "load_owner_tolerance", boom)
    b = DX.measure_owner_column()
    assert b["measured"] is False and "упала" in b["reason"]


def test_axis_b_reader_that_does_not_recognise_the_scene_dial_is_unmeasured(monkeypatch):
    monkeypatch.setattr(S49, "_TOLERANCE_HINTS", ("нет_такого_слова",))
    b = DX.measure_owner_column()
    assert b["loader"]["kind"] == UNMEASURED
    assert "опознана загрузчиком" in b["loader"]["reason"]


# ───────────────────── ось C: роли полей времени ─────────────────────────────

def test_axis_c_scene_record_has_identity_birth_and_input_but_no_expiry(tmp_path):
    a = _anchor()
    c = DX.measure_record_time_fields(_data_dir(tmp_path, None, _live_like_record(a)), DX.REPO_ROOT)
    assert c["measured"]
    assert c["fields"] == {"apy_as_of": "input_stamp", "cycle_date": "identity_date",
                          "decision_id": "identity_date", "generated_at": "birth_stamp"}
    assert c["expiry_fields"] == [] and c["owner_example_present"] is False
    assert c["writer_claim"]["kind"] == "confirmed", c["writer_claim"]
    assert c["s25_field_28_named"] is True
    assert c["s25_delegated"]["verdict"]


def test_axis_c_valid_until_on_the_record_is_an_expiry_field(tmp_path):
    a = _anchor()
    rec = dict(_live_like_record(a), valid_until=(a + dt.timedelta(minutes=10)).isoformat())
    c = DX.measure_record_time_fields(_data_dir(tmp_path, None, rec), DX.REPO_ROOT)
    assert c["expiry_fields"] == ["valid_until"] and c["owner_example_present"] is True
    assert c["roles_tally"]["expiry"] == 1


def test_axis_c_an_unknown_time_like_field_has_no_role_and_says_so(tmp_path):
    rec = dict(_live_like_record(_anchor()), frozen_time="x")
    c = DX.measure_record_time_fields(_data_dir(tmp_path, None, rec), DX.REPO_ROOT)
    assert c["fields"]["frozen_time"] == UNMEASURED


def test_axis_c_empty_and_missing_carrier_are_third_outcomes(tmp_path):
    d = _data_dir(tmp_path, None)
    c = DX.measure_record_time_fields(d, DX.REPO_ROOT)
    assert c["fields"] is None and "не прочитана" in c["reason"]
    (tmp_path / "data" / DX._s25.CARRIER_ARTIFACT[DX.RECORD_CARRIER]).write_text("", encoding="utf-8")
    c2 = DX.measure_record_time_fields(d, DX.REPO_ROOT)
    assert c2["fields"] is None and "пуст" in c2["reason"]


def test_axis_c_writer_claim_is_refuted_when_the_writer_lacks_the_label(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "spa_core" / "paper_trading").mkdir(parents=True)
    (root / "spa_core" / "paper_trading" / "allocation_rationale.py").write_text(
        "x = 1\n", encoding="utf-8")
    c = DX.measure_record_time_fields(_data_dir(tmp_path, None, _live_like_record(_anchor())),
                                      str(root))
    assert c["writer_claim"]["kind"] == "refuted"
    assert any("decision_id" in p for p in c["writer_claim"]["problems"])


# ───────────────────── ось D: похожие на TTL ─────────────────────────────────

def test_axis_d_every_declared_window_is_confirmed_and_none_ages_a_decision():
    d = DX.measure_lookalikes(DX.REPO_ROOT)
    unm = {k: v.get("reason") for k, v in d["windows"].items() if v["kind"] == UNMEASURED}
    assert not unm, unm
    assert d["tally"]["decision"] == 0
    assert d["tally"][UNMEASURED] == 0
    assert d["windows"]["сроки годности артефактов в паспортах агентов"]["declarations"] > 0


def test_axis_d_declaration_drift_is_unmeasured_not_a_kind(monkeypatch):
    bad = dict(DX.LOOKALIKE_MAP)
    bad["окно свежести свидетельства (гейт годности)"] = dict(
        bad["окно свежести свидетельства (гейт годности)"],
        evidence={"spa_core/allocator/allocator.py": ("НЕТ_ТАКОГО_ИМЕНИ",)})
    monkeypatch.setattr(DX, "LOOKALIKE_MAP", bad)
    d = DX.measure_lookalikes(DX.REPO_ROOT)
    row = d["windows"]["окно свежести свидетельства (гейт годности)"]
    assert row["kind"] == UNMEASURED and "разошлось" in row["reason"]


def test_axis_d_json_key_absent_or_file_missing_are_unmeasured(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "architecture").mkdir(parents=True)
    (root / "architecture" / "manifest.json").write_text('{"agents": []}', encoding="utf-8")
    monkeypatch.setattr(DX, "LOOKALIKE_MAP", {
        "a": {"kind": "artifact", "json": ("architecture/manifest.json", "slo_hours"), "ages": "x"},
        "b": {"kind": "artifact", "json": ("architecture/нет.json", "slo_hours"), "ages": "x"},
    })
    d = DX.measure_lookalikes(str(root))
    assert d["windows"]["a"]["kind"] == UNMEASURED and "нет ни разу" in d["windows"]["a"]["reason"]
    assert d["windows"]["b"]["kind"] == UNMEASURED


# ───────────────────── ось E: дверь принуждения ──────────────────────────────

def test_axis_e_live_tree_has_no_enforcement_door_and_the_ttl_is_unreachable(tmp_path):
    a = _anchor()
    e = DX.measure_enforcement_door(_data_dir(tmp_path, _chain(a)), DX.REPO_ROOT, now=a)
    assert e["door"]["kind"] == "no_gate_on_path", e["door"]
    assert e["gate_words"]["kind"] == "absent"
    assert e["surface_tokens"]["kind"] == "absent", e["surface_tokens"]
    tv = e["ttl_vs_window"]
    assert tv["reachable_on_paper"] is False
    assert tv["ttl_over_window"] == pytest.approx(DX.OWNER_TTL_S / 0.6, rel=0.05)


def test_axis_e_window_longer_than_the_ttl_makes_it_reachable(tmp_path):
    a = _anchor()
    e = DX.measure_enforcement_door(_data_dir(tmp_path, _chain(a, window_s=700.0)),
                                    DX.REPO_ROOT, now=a)
    assert e["ttl_vs_window"]["reachable_on_paper"] is True


def test_axis_e_missing_chain_leaves_reachability_unmeasured(tmp_path):
    e = DX.measure_enforcement_door(_data_dir(tmp_path, None), DX.REPO_ROOT, now=_anchor())
    assert e["ttl_vs_window"]["reachable_on_paper"] is None
    assert e["ttl_vs_window"]["reason"]


def test_axis_e_surface_token_is_exact_not_a_prefix(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "spa_core" / "paper_trading").mkdir(parents=True)
    (root / "spa_core" / "paper_trading" / "cycle_runner.py").write_text(
        "valid_until_x = 1\n", encoding="utf-8")
    monkeypatch.setattr(PC, "CALLER_SURFACE", ("spa_core/paper_trading/cycle_runner.py",))
    hits, unm = DX._callers_mention(str(root), DX.EXPIRY_TOKENS, {}, exact=True)
    assert hits == [] and unm == []
    (root / "spa_core" / "paper_trading" / "cycle_runner.py").write_text(
        "valid_until = 1\n", encoding="utf-8")
    hits2, _ = DX._callers_mention(str(root), DX.EXPIRY_TOKENS, {}, exact=True)
    assert hits2 == ["spa_core/paper_trading/cycle_runner.py:valid_until"]


def test_axis_e_instrument_asks_the_surface_with_exact_tokens(tmp_path, monkeypatch):
    """Мутация M10 #1089 ВЫЖИЛА на первом прогоне: дверь проверялась напрямую, а вызов
    прибора — нет. Здесь прибор ЦЕЛИКОМ: `valid_until_x` на поверхности ≠ `valid_until`."""
    root = tmp_path / "root"
    (root / "spa_core" / "paper_trading").mkdir(parents=True)
    (root / "spa_core" / "paper_trading" / "cycle_runner.py").write_text(
        "valid_until_x = 1\n", encoding="utf-8")
    monkeypatch.setattr(PC, "CALLER_SURFACE", ("spa_core/paper_trading/cycle_runner.py",))
    e = DX.measure_enforcement_door(_data_dir(tmp_path, None), str(root), now=_anchor())
    assert e["surface_tokens"]["kind"] == "absent", e["surface_tokens"]


def test_axis_e_gate_that_reads_ttl_and_is_called_from_the_path(tmp_path, monkeypatch):
    """Порванное звено наоборот: гейт знает `valid_until` и зовётся с пути."""
    root = tmp_path / "root"
    (root / "spa_core" / "execution").mkdir(parents=True)
    (root / "spa_core" / "risk").mkdir(parents=True)
    (root / "spa_core" / "execution" / "safety_checks.py").write_text(
        "def check(d, now):\n    return d['valid_until'] > now\n", encoding="utf-8")
    (root / "spa_core" / "risk" / "policy.py").write_text(
        "from spa_core.execution import safety_checks\n", encoding="utf-8")
    monkeypatch.setattr(PC, "CALLER_SURFACE", ("spa_core/risk/policy.py",))
    e = DX.measure_enforcement_door(_data_dir(tmp_path, None), str(root), now=_anchor())
    assert e["door"]["kind"] == "gate_reads_ttl_on_path", e["door"]


# ───────────────────── ось F: часы ───────────────────────────────────────────

def test_axis_f_imports_section_27_clock_and_names_the_section_24_word():
    f = DX.measure_clock(DX.REPO_ROOT)
    assert f["measured"]
    assert f["subjects"] == {"allocator": "unpinnable_ambient", "tuner": "unpinnable_ambient"}
    assert f["cycle_entry"]["kind"] == "pinnable_named"
    assert f["s24_type_for_stale"] == "DEFER"
    assert f["fifth_input"] == DX.FIFTH_INPUT


# ───────────────────── прогон целиком ─────────────────────────────────────────

def test_run_on_scene_data_with_a_column_without_the_dials_is_critical_unexecuted_first(tmp_path):
    """ИЗМЕНЕНО НАМЕРЕННО (ADR-972, инв. #16): до 10.11 сцена читала ЖИВУЮ колонку и
    «ответ не исполнен» был её свойством; ответ исполнен — колонка без ручек подаётся
    входом, чтобы находка оставалась ДОСТИЖИМОЙ (контроль в обе стороны)."""
    a = _anchor()
    column_1089 = types.SimpleNamespace(min_hold_days=3, version="v1.1", mode="paper")
    doc = DX.run(root=DX.REPO_ROOT, data_dir=_data_dir(tmp_path, _chain(a), _live_like_record(a)),
                 write=False, now=a, params=column_1089)
    assert doc["overall"] == "CRITICAL"
    codes = [f["code"] for f in doc["findings"]]
    assert "owner_answer_unexecuted" in codes
    crit = [f for f in doc["findings"] if f["severity"] == "CRITICAL"]
    assert [f["code"] for f in crit] == ["owner_answer_unexecuted"]
    assert "decision_record_has_no_expiry_field" in codes
    assert "owner_ttl_unreachable_on_paper" in codes
    assert "expiry_needs_now_and_it_is_not_an_input" in codes
    assert "every_ttl_in_tree_ages_something_else" in codes
    assert doc["unmeasured"] == [], doc["unmeasured"]
    assert doc["applied"] is False
    assert doc["generated_at"] == a.isoformat()


def test_run_on_scene_data_with_the_live_column_has_the_answer_executed(tmp_path):
    """ADR-972: на живой колонке ответ исполнен — CRITICAL про исполнение уходит,
    остальные находки §28 (поле expiry у записи, TTL на бумаге недостижим…) остаются."""
    a = _anchor()
    doc = DX.run(root=DX.REPO_ROOT, data_dir=_data_dir(tmp_path, _chain(a), _live_like_record(a)),
                 write=False, now=a)
    codes = [f["code"] for f in doc["findings"]]
    assert "owner_answer_unexecuted" not in codes
    assert "owner_answer_misexecuted" not in codes
    assert "column_reader_names_dial_but_never_reads_value" not in codes
    assert "decision_record_has_no_expiry_field" in codes
    assert "owner_ttl_unreachable_on_paper" in codes
    assert doc["unmeasured"] == [], doc["unmeasured"]
    assert doc["applied"] is False


def test_run_on_a_column_with_a_foreign_number_reports_misexecution(tmp_path):
    a = _anchor()
    foreign = types.SimpleNamespace(decision_ttl_s=60.0, input_freshness_tolerance_s=60.0,
                                    version="scene", mode="paper")
    doc = DX.run(root=DX.REPO_ROOT, data_dir=_data_dir(tmp_path, _chain(a), _live_like_record(a)),
                 write=False, now=a, params=foreign)
    codes = [f["code"] for f in doc["findings"] if f["severity"] == "CRITICAL"]
    assert "owner_answer_misexecuted" in codes and "owner_answer_unexecuted" not in codes


def test_run_every_kind_printed_belongs_to_a_declared_vocabulary(tmp_path):
    a = _anchor()
    doc = DX.run(root=DX.REPO_ROOT, data_dir=_data_dir(tmp_path, _chain(a), _live_like_record(a)),
                 write=False, now=a)
    assert doc["axis_b_owner_column"]["loader"]["kind"] in DX.LOADER_KINDS
    for role in doc["axis_c_record_time_fields"]["fields"].values():
        assert role in DX.TIME_FIELD_ROLES
    for row in doc["axis_d_lookalikes"]["windows"].values():
        assert row["kind"] in DX.AGED_KINDS
    assert doc["axis_e_enforcement"]["door"]["kind"] in DX.ENFORCEMENT_KINDS
    assert doc["axis_f_clock"]["cycle_entry"]["kind"] in DX.PIN_KINDS


def test_run_write_true_calls_atomic_save_with_data_then_path(tmp_path, monkeypatch):
    """Порядок (data, path) — дефект-возврат §26 (#1088, M13) ловится здесь."""
    import spa_core.utils.atomic as atomic
    seen = {}

    def fake_save(data, path, *a, **k):
        seen["data"], seen["path"] = data, path

    monkeypatch.setattr(atomic, "atomic_save", fake_save)
    a = _anchor()
    DX.run(root=DX.REPO_ROOT, data_dir=_data_dir(tmp_path, _chain(a), _live_like_record(a)),
           write=True, now=a)
    assert isinstance(seen["data"], dict) and seen["data"]["schema"] == "decision_expiry_census/v1"
    assert isinstance(seen["path"], str) and seen["path"].endswith(DX.REPORT_REL)


def test_run_unreadable_card_is_unmeasured_not_a_critical(tmp_path):
    a = _anchor()
    doc = DX.run(root=DX.REPO_ROOT, data_dir=_data_dir(tmp_path, _chain(a), _live_like_record(a)),
                 card_path=str(tmp_path / "нет.md"), write=False, now=a)
    assert any("паритет с карточкой" in u for u in doc["unmeasured"])
    assert "owner_text_drifted" not in [f["code"] for f in doc["findings"]]


def test_parse_now_is_an_input_and_refuses_garbage():
    ts, why = DX.parse_now(None)
    assert ts is None and why is None
    ts, why = DX.parse_now(_anchor().isoformat())
    assert ts is not None and why is None
    ts, why = DX.parse_now("вчера")
    assert ts is None and "не разбирается" in why
    ts, why = DX.parse_now("   ")
    assert ts is None and why


def test_main_refuses_an_unparsable_now_with_code_2(capsys):
    assert DX.main(["--now", "мусор", "--no-write"]) == 2
    assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().out


# ───────────────────── проба приёмки (ADR-971) ───────────────────────────────

def test_probe_is_registered_and_validates():
    assert "decision_expiry_answer_executed" in CA.PROBES
    assert CA.validate_spec("decision_expiry_answer_executed") is None


def test_probe_on_the_live_tree_is_satisfied_after_adr_972():
    """ИЗМЕНЕНО НАМЕРЕННО (ADR-972, инв. #16): проба объявлена ДО работы и не правилась;
    сменился ИСХОД на живом дереве — ответ владельца исполнен."""
    status, reason = CA.PROBES["decision_expiry_answer_executed"](None)
    assert status == CA.SATISFIED, reason
    assert "decision_ttl_s" in reason and "v1.2" in reason


def test_probe_three_outcomes_are_distinct(monkeypatch):
    def col(**over):
        base = {"measured": True, "ttl_dial": None, "dials_n": 15, "version": "v1.1",
                "tolerance_s": None, "loader": {"kind": "names_dial_only", "reason": "r"}}
        base.update(over)
        return lambda: base

    monkeypatch.setattr(DX, "measure_owner_column", col(measured=False, reason="нет колонки"))
    assert CA.PROBES["decision_expiry_answer_executed"](None)[0] == CA.UNMEASURED
    monkeypatch.setattr(DX, "measure_owner_column",
                        col(loader={"kind": UNMEASURED, "reason": "сцена не опознана"}))
    assert CA.PROBES["decision_expiry_answer_executed"](None)[0] == CA.UNMEASURED
    monkeypatch.setattr(DX, "measure_owner_column", col(ttl_dial="decision_ttl_s"))
    status, reason = CA.PROBES["decision_expiry_answer_executed"](None)
    assert status == CA.NOT_SATISFIED and "половина" in reason
    monkeypatch.setattr(DX, "measure_owner_column",
                        col(ttl_dial="decision_ttl_s", tolerance_s=600.0,
                            loader={"kind": "reads_value", "reason": "r"}))
    assert CA.PROBES["decision_expiry_answer_executed"](None)[0] == CA.SATISFIED
