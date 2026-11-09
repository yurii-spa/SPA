"""Батарея §25 «Decision payload» (ADR-968).

Каждый тест — утверждение о ПРИБОРЕ, а не о сегодняшнем состоянии дерева:
число полей сверяется с ПРОИЗВОДИТЕЛЕМ (карточкой приказа), ловушка наивного
счёта ИЗМЕРЯЕТСЯ, а не описывается, и у каждой оси есть контроль в обе стороны —
сцена, на которой ось отвечает «есть», и сцена, на которой она отвечает «нет».

🪤 Время здесь не является предметом, и литеральных дат в файле нет: сцены
строятся из литералов СОДЕРЖИМОГО, а не из отметок времени, поэтому бомба
замороженной даты этому файлу не грозит по построению (а не по записке).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from spa_core.analytics import decision_payload_census as dpc

UNMEASURED = dpc.UNMEASURED
REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def report():
    """Перепись БЕЗ живого каталога: ось B носителей с артефактом — третий исход."""
    return dpc.census(REPO)


@pytest.fixture
def fixture_data_dir(tmp_path):
    """Каталог данных СЦЕНЫ: по одной настоящей записи на каждого носителя.

    🪤 Первая редакция батареи звала перепись на АМБИЕНТНОМ ``<дерево>/data``,
    и два теста честно покраснели: в git-замороженном каноне дерева доставки
    ``allocation_rationale_history.jsonl`` отсутствует, а в прод-дереве есть.
    То есть вердикт теста был свойством СОДЕРЖИМОГО дерева, а не кода — ровно
    класс ADR-905. Сцена кладёт записи сама, поэтому ответ одинаков на любом
    дереве и на любой машине.
    """
    data = tmp_path / "data"
    data.mkdir()
    shadow, why = dpc.shadow_scene_record()
    assert why is None, why
    (data / "allocation_rationale_history.jsonl").write_text(
        json.dumps(shadow, ensure_ascii=False) + "\n", encoding="utf-8")
    (data / "trades.json").write_text(json.dumps([{
        "trade_id": "PT-SCENE-1", "ts": "scene", "type": "rebalance",
        "from_allocation": {"aave_v3": 2000.0},
        "to_allocation": {"morpho_blue": 2000.0},
        "diff_usd": 2000.0, "delta_abs": 2000.0, "reason": "orchestrator_cycle",
        "model_used": "scene", "strategy_loop_active": True,
        "capital": 100000.0, "is_demo": False,
    }], ensure_ascii=False), encoding="utf-8")
    (data / "audit_trail.jsonl").write_text("\n".join(
        json.dumps(row, ensure_ascii=False) for row in (
            {"event_type": "allocation_proposal", "timestamp": "scene",
             "snapshot_id": "scene:1",
             "data": {"target_usd": {"aave_v3": 1.0}, "model_used": "scene",
                      "strategy_loop_active": True}},
            {"event_type": "risk_verdict", "timestamp": "scene",
             "snapshot_id": "scene:1",
             "data": {"approved": True, "violations": ["scene"],
                      "warnings": [], "trimmed": False,
                      "tvl_unverified": [], "gate_error": None}},
            {"event_type": "trade_executed", "timestamp": "scene",
             "snapshot_id": "scene:1",
             "data": {"trade_id": "PT-SCENE-1", "diff_usd": 2000.0,
                      "delta_abs": 2000.0,
                      "from_allocation": {"aave_v3": 2000.0},
                      "to_allocation": {"morpho_blue": 2000.0}}},
            {"event_type": "trade_blocked", "timestamp": "scene",
             "snapshot_id": "scene:1",
             "data": {"reason": "scene", "detail": "scene"}},
        )) + "\n", encoding="utf-8")
    return data


@pytest.fixture
def report_scene(fixture_data_dir):
    """Перепись по СЦЕНЕ — тот же код, что на живом треке, но вход объявлен."""
    return dpc.census(REPO, fixture_data_dir)


# ── перечень владельца: число снято ПРОИЗВОДИТЕЛЕМ, не памятью ──────────────

def test_declared_count_matches_the_card_parse(report):
    """Константа 28 обязана совпасть с РАЗБОРОМ карточки приказа.

    Сторож, сравнивающий свои константы сам с собой, не мерит ничего
    (ADR-913/919): мерка стоит в паритете с производителем.
    """
    assert "unmeasured" not in report["card"], report["card"]
    assert report["fields_parsed_from_card"] == dpc.OWNER_FIELDS_DECLARED == 28
    assert report["count_parity"] is True


def test_the_naive_count_trap_is_measured_not_described(report):
    """Наивный счёт обязан дать 29 — иначе ловушка описана словами, а не измерена."""
    assert report["card"]["naive_count"] == dpc.ORDER_G956_NAIVE == 29
    assert report["card"]["naive_count"] == report["fields_parsed_from_card"] + 1


def test_the_extra_naive_line_is_the_next_section_header():
    """Двадцать девятой строкой наивного счёта стоит заголовок §26, и это ПРОВЕРЕНО."""
    card = (REPO / dpc.CARD_REL).read_text(encoding="utf-8").splitlines()
    fields, meta = dpc.owner_fields_from_card(REPO)
    stop = meta["line_span"][1]
    assert card[stop].strip() == dpc.NEXT_SECTION_HEAD
    assert dpc.NEXT_SECTION_HEAD not in fields


def test_order_g956_count_matches_and_zero_is_reported(report):
    """«Сошлось» — это замер, и он печатается наравне с расхождением."""
    assert report["order_g956_named"] == dpc.OWNER_FIELDS_DECLARED
    assert report["order_undercount"] == 0
    assert "order_undercount" in report


def test_owner_words_are_verbatim_and_in_tz_order(report):
    """Формулировки владельца не переводятся и не переставляются."""
    fields, _ = dpc.owner_fields_from_card(REPO)
    assert [r["owner_words"] for r in report["fields"]] == list(fields)


def test_an_unreadable_card_is_unmeasured_not_the_constant(tmp_path):
    """Карточка нечитаема ⇒ третий исход, а НЕ молчаливый возврат к константе."""
    fields, meta = dpc.owner_fields_from_card(tmp_path)
    assert fields == ()
    assert "unmeasured" in meta
    rep = dpc.census(tmp_path)
    assert rep["count_parity"] is None
    assert dpc.verdict_code(rep) == 2


def test_a_card_without_the_next_section_header_is_unmeasured(tmp_path):
    """Нет ВТОРОЙ границы ⇒ счёт наивен ⇒ fail-CLOSED, а не 29 под видом 28."""
    card = tmp_path / dpc.CARD_REL
    card.parent.mkdir(parents=True, exist_ok=True)
    card.write_text("\n".join([dpc.SECTION_HEAD, "timestamp", "source"]),
                    encoding="utf-8")
    fields, meta = dpc.owner_fields_from_card(tmp_path)
    assert fields == ()
    assert dpc.NEXT_SECTION_HEAD in meta["unmeasured"]


# ── ввоз словарей: у каждого есть читатель ──────────────────────────────────

def test_no_vocabulary_import_failed(report):
    assert report["vocab_errors"] == [], report["vocab_errors"]


def test_every_import_has_a_reader_in_the_report(report):
    """Ввоз без читателя есть ложное усиление — каждый ввезённый словарь ПЕЧАТАЕТСЯ."""
    assert report["delegate_24_dictionary"] == list(dpc.OWNER_DECISION_TYPES)
    assert report["delegate_24_types_declared"] == dpc.OWNER_TYPES_DECLARED
    assert report["shadow_schema"] == dpc.HISTORY_SCHEMA != ""
    assert report["trail_filename"] == dpc.AUDIT_FILENAME
    assert set(report["trail_valid_event_types"]) == set(
        dpc.VALID_EVENT_TYPES)
    assert report["shadow_filename"] == dpc.history_filename()
    assert UNMEASURED in dpc.PRESENCE_KINDS  # ввезённая шкала §13


def test_vocab_errors_alone_make_the_verdict_unmeasured(report):
    broken = dict(report, vocab_errors=["сцена"])
    assert dpc.verdict_code(broken) == 2


# ── шкалы: третий исход объявлен у каждой ───────────────────────────────────

@pytest.mark.parametrize("scale", [
    dpc.PRESENCE_KINDS, dpc.RECORD_KINDS, dpc.FIELD_VERDICT_KINDS,
    dpc.LIVE_ARTIFACT_KINDS,
])
def test_every_scale_declares_the_third_outcome(scale):
    assert UNMEASURED in scale


def test_report_uses_only_declared_kinds(report):
    for row in report["fields"]:
        assert row["verdict"] in dpc.FIELD_VERDICT_KINDS, row
        for carrier, cell in row["carriers"].items():
            assert cell["presence"]["kind"] in dpc.PRESENCE_KINDS, (carrier, row)
            assert cell["record"]["kind"] in dpc.RECORD_KINDS, (carrier, row)
    assert (report["sqlite_live_artifact"]["kind"]
            in dpc.LIVE_ARTIFACT_KINDS)


# ── носители: перечень, расширение, способ измерения ────────────────────────

def test_four_carriers_and_the_extension_is_named(report):
    """Заказ назвал три носителя; четвёртый ОБЪЯВЛЕН, а не подставлен молча."""
    assert report["carriers"] == ["shadow", "journal", "sqlite", "trail"]
    assert set(report["carrier_extension"]) == {"trail"}
    assert "заказ G956" in report["carrier_extension"]["trail"]


def test_every_carrier_names_how_axis_a_was_measured(report):
    """Способ измерения есть часть утверждения — носитель без него читался бы
    измеренным способом соседа."""
    for carrier in report["carriers"]:
        assert report["carrier_probe"][carrier].strip()
        assert carrier in report["writer_vocabulary_sizes"]


def test_writer_vocabularies_are_read_and_diverge(report):
    """Словари носителей РАЗНЫЕ — слить их в один значило бы придумать носитель."""
    assert report["writer_vocabulary_unreadable"] == [], report[
        "writer_vocabulary_unreadable"]
    sizes = report["writer_vocabulary_sizes"]
    assert all(v > 0 for v in sizes.values()), sizes
    assert len(set(sizes.values())) > 1, sizes


def test_shadow_vocabulary_comes_from_the_writer_itself():
    """Словарь тени — ключи записи НАСТОЯЩЕГО писателя, не копия перечня."""
    rec, why = dpc.shadow_scene_record()
    assert why is None, why
    assert rec is not None
    assert rec["schema"] == dpc.HISTORY_SCHEMA
    paths = set(dpc._flat_paths(rec))
    assert "admissible_trim.target_after" in paths  # вложенный путь виден
    assert "cost_usd" in paths


def test_journal_vocabulary_comes_from_the_ast_of_the_writer():
    runner = REPO / "spa_core/paper_trading/cycle_runner.py"
    keys, why = dpc._dict_literal_keys(runner, "trades", "append")
    assert why is None, why
    assert {"trade_id", "ts", "type", "from_allocation", "to_allocation",
            "delta_abs", "reason"} <= set(keys)


def test_a_missing_ast_callsite_is_unmeasured_not_empty(tmp_path):
    """Зова нет ⇒ причина НАЗВАНА; пустой словарь молча читался бы как «полей нет»."""
    f = tmp_path / "m.py"
    f.write_text("x = 1\n", encoding="utf-8")
    keys, why = dpc._dict_literal_keys(f, "trades", "append")
    assert keys == ()
    assert why and "не найден" in why


def test_an_unparsable_writer_is_unmeasured(tmp_path):
    f = tmp_path / "broken.py"
    f.write_text("def f(:\n", encoding="utf-8")
    keys, why = dpc._dict_literal_keys(f, "trades", "append")
    assert keys == ()
    assert why and "не разобран" in why


def test_trail_payload_keys_are_grouped_by_event_type():
    runner = REPO / "spa_core/paper_trading/cycle_runner.py"
    payloads, why = dpc._record_event_payload_keys(runner)
    assert why is None, why
    assert "trade_executed" in payloads and "risk_verdict" in payloads
    assert "from_allocation" in payloads["trade_executed"]
    assert "approved" in payloads["risk_verdict"]
    # Группировка — предмет: ключ одного события не смеет засчитаться другому.
    assert "from_allocation" not in payloads["risk_verdict"]


def test_a_broken_writer_vocabulary_makes_presence_unmeasured(monkeypatch):
    """Словарь писателя не снят ⇒ ось A третий исход у ЭТОГО носителя.

    Причина ищется ПРИ НОСИТЕЛЕ, а не подстрокой в общем списке: до правки
    #1086 проверка искала своё имя в чужой строке — тот же дефект, что мерить
    вердикт подстрокой (ADR-333).
    """
    monkeypatch.setattr(dpc, "shadow_scene_record",
                        lambda: (None, "сцена сломана намеренно"))
    rep = dpc.census(REPO)
    assert any("shadow" in u for u in rep["writer_vocabulary_unreadable"])
    row = next(r for r in rep["fields"] if r["field"] == "transaction_cost")
    assert row["carriers"]["shadow"]["presence"]["kind"] == UNMEASURED
    # соседний носитель при этом НЕ отравлен
    assert row["carriers"]["journal"]["presence"]["kind"] != UNMEASURED
    assert dpc.verdict_code(rep) == 2


# ── ось B: третий исход «объявлено, но всегда пусто» ────────────────────────

def test_axis_b_distinguishes_three_outcomes_on_a_real_record():
    rec, why = dpc.shadow_scene_record()
    assert why is None
    assert dpc._axis_b("shadow", ("cost_usd",), [rec])["kind"] == (
        "present_with_value")
    assert dpc._axis_b(
        "shadow", ("cost_usd",),
        [{k: v for k, v in rec.items() if k != "cost_usd"}])["kind"] == (
            "absent_from_record")
    assert dpc._axis_b("shadow", ("cost_usd",),
                       [dict(rec, cost_usd=None)])["kind"] == (
                           "present_always_empty")


def test_a_measured_zero_stays_an_observation():
    """Инв. #17: ноль — наблюдение, а не отсутствие."""
    assert dpc._is_empty(0) is False
    assert dpc._is_empty(0.0) is False
    assert dpc._is_empty(False) is False
    assert dpc._is_empty(None) is True
    assert dpc._is_empty({}) is True
    assert dpc._is_empty([]) is True
    assert dpc._is_empty("") is True
    rec, _ = dpc.shadow_scene_record()
    assert dpc._axis_b("shadow", ("cost_usd",),
                       [dict(rec, cost_usd=0.0)])["kind"] == (
                           "present_with_value")


def test_no_records_is_unmeasured_not_absent():
    assert dpc._axis_b("shadow", ("cost_usd",), [])["kind"] == UNMEASURED


def test_axis_b_without_a_data_dir_is_unmeasured_for_artifact_carriers(report):
    """Каталог не назван ⇒ записи НЕ НАБЛЮДАЛИСЬ, и это не «полей нет»."""
    for carrier in ("shadow", "journal", "trail"):
        assert report["observed"][carrier]["unmeasured"], carrier
        assert report["observed"][carrier]["how"] == "observed_artifact"
    assert report["observed"]["sqlite"]["how"] == "built_scene"
    assert dpc.verdict_code(report) == 2


def test_trail_scoping_never_credits_one_event_to_another():
    rows = [{"event_type": "risk_verdict", "data": {"approved": True}},
            {"event_type": "trade_executed", "data": {"delta_abs": 7.0}}]
    assert dpc._axis_b("trail", ("trade_executed:data.delta_abs",),
                       rows)["kind"] == "present_with_value"
    assert dpc._axis_b("trail", ("risk_verdict:data.delta_abs",),
                       rows)["kind"] == "absent_from_record"
    assert dpc._axis_b("trail", ("*:event_type",),
                       rows)["kind"] == "present_with_value"


def test_trail_split_reads_the_envelope_marker():
    assert dpc._trail_split("*:timestamp") == (None, "timestamp")
    assert dpc._trail_split("risk_verdict:data.approved") == (
        "risk_verdict", "data.approved")


# ── положительный контроль прибора ──────────────────────────────────────────

def test_control_passes_on_the_real_writer(report):
    assert report["control"]["passed"] is True, report["control"]


def test_control_fails_when_axis_b_stops_distinguishing(monkeypatch):
    """Контроль обязан КРАСНЕТЬ, если ось B перестала различать исходы.

    Мутация: `_axis_b` всегда отвечает «значение есть». Проверка, никогда не
    видевшая настоящей поломки, — украшение (`.claude/rules/deployment.md`).
    """
    monkeypatch.setattr(dpc, "_axis_b",
                        lambda *a, **k: {"kind": "present_with_value",
                                         "why": "мутация"})
    ok, why = dpc.control(dpc.writer_vocabulary(REPO)[0])
    assert ok is False
    assert "НЕ ПРОШЁЛ" in why


def test_control_fails_when_a_measured_zero_is_read_as_empty(monkeypatch):
    """Вторая половина контроля: подмена семантики нуля обязана краснеть."""
    monkeypatch.setattr(dpc, "_is_empty",
                        lambda v: v is None or v == 0 or not v)
    ok, why = dpc.control(dpc.writer_vocabulary(REPO)[0])
    assert ok is False
    assert "инвариант #17" in why


def test_control_not_built_is_not_a_pass():
    ok, why = dpc.control({"shadow": {"paths": (), "unreadable": []}})
    assert ok is False
    assert "НЕ ПОСТРОЕН" in why


def test_failed_control_alone_makes_the_verdict_unmeasured(report):
    broken = dict(report, control={"passed": False, "reason": "сцена"})
    assert dpc.verdict_code(broken) == 2


# ── делегирование: один предмет — одна шкала ────────────────────────────────

def test_exactly_two_fields_are_delegated_and_not_remeasured(report):
    delegated = [r for r in report["fields"]
                 if r["verdict"] == "delegated_to_another_section"]
    assert {r["field"] for r in delegated} == {"decision_type",
                                               "decision_expiry"}
    assert report["tally"]["delegated_to_another_section"] == 2
    for row in delegated:
        # вердикт делегата ПЕЧАТАЕТСЯ: делегирование без печати есть умолчание
        assert row["delegate_verdict"].strip()
        assert row["delegate_adr"].startswith("ADR-")
        assert row["why_not_remeasured"].strip()
        # у делегированного поля НЕТ собственного вердикта присутствия
        for cell in row["carriers"].values():
            assert cell["presence"]["kind"] == "delegated"
            assert cell["record"]["kind"] == "delegated"


def test_delegated_fields_declare_no_mapping(report):
    """Соответствие у делегированного поля не объявляется — иначе прибор выдал
    бы ответ, ПРОТИВОПОЛОЖНЫЙ делегату, о том же предмете."""
    for key in dpc.DELEGATED_FIELDS:
        assert all(not paths for paths in dpc.FIELD_MAP[key].values())


# ── соответствие объявлено, а не угадано ────────────────────────────────────

def test_every_owner_field_has_a_declared_mapping_and_a_reason():
    keys = [k for k, _ in dpc.OWNER_FIELDS_25]
    assert len(keys) == len(set(keys)) == dpc.OWNER_FIELDS_DECLARED
    for key in keys:
        assert key in dpc.FIELD_MAP, key
        assert set(dpc.FIELD_MAP[key]) == set(dpc.CARRIERS_25), key
        assert dpc.MAP_REASONS.get(key, "").strip(), key


def test_the_mapping_declares_no_path_outside_the_writer_vocabulary(report):
    """Объявленный путь, которого у писателя нет, обязан быть НАЗВАН, а не
    тихо засчитан."""
    vocab, _ = dpc.writer_vocabulary(REPO)
    for key, per in dpc.FIELD_MAP.items():
        for carrier, paths in per.items():
            declared = set(vocab[carrier]["paths"])
            for path in paths:
                assert path in declared, (key, carrier, path)


def test_sqlite_is_never_credited_with_source_and_destination():
    """Одна колонка `protocol_key` не различает концы хода — и утверждать
    обратное запрещено тем же правилом, что в §24 (не переводить по сходству)."""
    assert dpc.FIELD_MAP["source"]["sqlite"] == ()
    assert dpc.FIELD_MAP["destination"]["sqlite"] == ()
    rec, why = dpc.sqlite_scene_record()
    assert why is None, why
    assert "protocol_key" in rec


def test_near_misses_are_named_with_reasons_and_are_not_mappings(report):
    assert len(report["near_miss_not_the_field"]) >= 4
    mapped = {p for per in dpc.FIELD_MAP.values() for paths in per.values()
              for p in paths}
    for place, why in report["near_miss_not_the_field"].items():
        assert why.strip(), place
        assert place not in mapped


def test_what_is_not_claimed_is_written_down(report):
    text = " ".join(report["not_claimed"])
    assert "ПРАВИЛЬНОСТЬ" in text
    assert "ЧИТАЕТ" in text
    assert "§43" in text


# ── живой артефакт носителя `sqlite` — отдельный вопрос ─────────────────────

def test_sqlite_live_artifact_is_unmeasured_without_a_data_dir(report):
    assert report["sqlite_live_artifact"]["kind"] == UNMEASURED


def test_sqlite_live_artifact_reports_a_present_table(tmp_path):
    from spa_core.agents.decision_logger import DecisionLogger
    from spa_core.database.init_db import init_database
    db = tmp_path / "scene.db"
    init_database(db)
    DecisionLogger(db, "Probe").log_allocate("aave_v3", 1.0, 5.0, "T1", "r",
                                             True)
    out = dpc.sqlite_live_artifact(tmp_path)
    assert out["kind"] == "table_present"
    assert "scene.db" in out["why"]


def test_sqlite_live_artifact_reports_an_absent_table(tmp_path):
    db = tmp_path / "other.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE unrelated (x INTEGER)")
    conn.commit()
    conn.close()
    out = dpc.sqlite_live_artifact(tmp_path)
    assert out["kind"] == "table_absent_from_every_database"
    assert "agent_decisions" in out["why"]


def test_sqlite_live_artifact_reports_no_database_at_all(tmp_path):
    assert dpc.sqlite_live_artifact(tmp_path)["kind"] == "no_database_at_all"


def test_an_absent_live_table_alone_is_a_finding(report):
    """«Писатель умеет» и «писатель написал» — разные наблюдения."""
    clean = dict(
        report,
        card=dict(report["card"]),
        count_parity=True,
        writer_vocabulary_unreadable=[],
        tally={k: 0 for k in dpc.FIELD_VERDICT_KINDS},
        sqlite_live_artifact={"kind": "table_absent_from_every_database",
                              "why": "сцена"},
    )
    assert dpc.verdict_code(clean) == 1
    assert dpc.verdict_code(dict(clean, sqlite_live_artifact={
        "kind": "table_present", "why": "сцена"})) == 0


# ── вердикт ─────────────────────────────────────────────────────────────────

def test_an_absent_field_alone_turns_the_verdict_into_a_finding(report):
    clean = dict(
        report, count_parity=True, writer_vocabulary_unreadable=[],
        tally={**{k: 0 for k in dpc.FIELD_VERDICT_KINDS},
               "absent_from_every_carrier": 1},
        sqlite_live_artifact={"kind": "table_present", "why": "сцена"})
    assert dpc.verdict_code(clean) == 1


def test_a_declared_but_never_filled_field_alone_is_a_finding(report):
    clean = dict(
        report, count_parity=True, writer_vocabulary_unreadable=[],
        tally={**{k: 0 for k in dpc.FIELD_VERDICT_KINDS},
               "declared_but_never_filled": 1},
        sqlite_live_artifact={"kind": "table_present", "why": "сцена"})
    assert dpc.verdict_code(clean) == 1


def test_a_count_mismatch_alone_is_unmeasured(report):
    assert dpc.verdict_code(dict(report, count_parity=False)) == 2


def test_an_unmeasured_field_alone_is_unmeasured(report):
    clean = dict(
        report, count_parity=True, writer_vocabulary_unreadable=[],
        tally={**{k: 0 for k in dpc.FIELD_VERDICT_KINDS}, UNMEASURED: 1},
        sqlite_live_artifact={"kind": "table_present", "why": "сцена"})
    assert dpc.verdict_code(clean) == 2


def test_verdict_is_zero_only_when_every_axis_is_clean(report):
    clean = dict(
        report, count_parity=True, writer_vocabulary_unreadable=[],
        vocab_errors=[], control={"passed": True, "reason": "сцена"},
        tally={**{k: 0 for k in dpc.FIELD_VERDICT_KINDS},
               "carried_with_value": 28},
        sqlite_live_artifact={"kind": "table_present", "why": "сцена"})
    assert dpc.verdict_code(clean) == 0


# ── печать ──────────────────────────────────────────────────────────────────

def test_render_prints_every_field_and_every_carrier(report):
    text = dpc.render(report)
    for _, words in dpc.OWNER_FIELDS_25:
        assert words in text, words
    for carrier in dpc.CARRIERS_25:
        assert carrier in text
    assert "ЖИВОЙ АРТЕФАКТ" in text
    assert "ДЕЛЕГИРОВАННЫЕ ПОЛЯ" in text
    assert "наивный счёт" in text


def test_render_names_the_unmeasured_card(tmp_path):
    text = dpc.render(dpc.census(tmp_path))
    assert "ПЕРЕЧЕНЬ НЕ СНЯТ" in text


def test_cli_returns_the_verdict_code(capsys):
    code = dpc.main(["--root", str(REPO), "--json"])
    out = json.loads(capsys.readouterr().out)
    assert code == dpc.verdict_code(out)
    assert out["section"] == "§25 Decision payload"


# ── прибор только ЧИТАЕТ ────────────────────────────────────────────────────

def test_module_writes_nothing_into_the_live_data_dir():
    """Сцены живут в одноразовом каталоге; живой `data/` только читается."""
    live = REPO / "data"
    before = {p.name: p.stat().st_mtime for p in live.glob("*.json")} if (
        live.exists()) else {}
    dpc.census(REPO, live if live.exists() else None)
    after = {p.name: p.stat().st_mtime for p in live.glob("*.json")} if (
        live.exists()) else {}
    assert before == after


def test_module_declares_llm_forbidden():
    src = Path(dpc.__file__).read_text(encoding="utf-8")
    assert "# LLM_FORBIDDEN" in src


# ── живой замер (если каталог данных читаем) ────────────────────────────────

def test_scene_run_names_every_axis(report_scene):
    """На полной сцене НЕ ИЗМЕРЕНО обязано быть нулём, а сумма — равной 28."""
    assert report_scene["tally"][UNMEASURED] == 0, report_scene["tally"]
    assert sum(report_scene["tally"].values()) == dpc.OWNER_FIELDS_DECLARED
    for carrier in ("shadow", "journal", "trail"):
        assert report_scene["observed"][carrier]["unmeasured"] is None, carrier
        assert report_scene["observed"][carrier]["rows"] > 0, carrier
        assert report_scene["observed"][carrier]["how"] == "observed_artifact"


def test_scene_run_finds_the_shadow_is_the_richest_carrier(report_scene):
    """Словари носителей РАСХОДЯТСЯ, и тень несёт больше всех. Это и есть
    находка о составе записи решения, а не свойство конкретного дерева."""
    per = report_scene["tally_per_carrier"]
    values = {c: per[c]["present_with_value"] for c in dpc.CARRIERS_25}
    assert values["shadow"] == max(values.values()), values
    assert len(set(values.values())) > 1, values
    assert values["shadow"] > values["journal"], values


def test_scene_run_reproduces_the_eight_absent_fields(report_scene):
    """Восемь полей не несёт НИ ОДИН носитель — перечень ИМЕНАМИ, не числом.

    Числом он читался бы как счётчик, а счётчик роста не замечает: имя,
    ушедшее из класса, и имя, в него пришедшее, дают ту же восьмёрку
    (урок ADR-910 — «65 = 65 нетто, а по именам дельта 2»).
    """
    absent = sorted(r["field"] for r in report_scene["fields"]
                    if r["verdict"] == "absent_from_every_carrier")
    assert absent == [
        "concentration_change",
        "confidence",
        "destination_conservative_apy",
        "destination_marginal_apy",
        "expected_holding_period",
        "expected_net_profit",
        "gross_incremental_profit",
        "risk_change",
    ], absent
    assert report_scene["tally"]["absent_from_every_carrier"] == len(absent)


def test_scene_run_verdict_is_a_named_finding(report_scene):
    assert dpc.verdict_code(report_scene) == 1


def test_a_record_that_lost_a_key_changes_the_verdict_of_that_field(
        fixture_data_dir):
    """Дифференциальный контроль сцены: снять ОДИН ключ у носителя — и вердикт
    ЭТОГО поля обязан измениться, а соседних — нет."""
    path = fixture_data_dir / "allocation_rationale_history.jsonl"
    row = json.loads(path.read_text(encoding="utf-8").strip())
    before = dpc.census(REPO, fixture_data_dir)
    row.pop("cost_usd")
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    after = dpc.census(REPO, fixture_data_dir)

    def verdicts(rep):
        return {r["field"]: r["verdict"] for r in rep["fields"]}

    vb, va = verdicts(before), verdicts(after)
    assert vb["transaction_cost"] == "carried_with_value"
    assert va["transaction_cost"] == "absent_from_every_carrier"
    changed = {k for k in vb if vb[k] != va[k]}
    assert changed == {"transaction_cost"}, changed
