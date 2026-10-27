"""Ответ владельца из сессии Claude Code закрывает карточку решения — только по ЗАПИСИ ответа (ADR-834, ADR-839).

Владелец 27.10: «я не хочу сам закрывать карточки руками, я хочу, чтобы это делал Claude». Граница:
ответ придумать нельзя. ARB 27.10 (R1) воспроизвёл три обхода прежней сверки «имя карточки есть в
тексте ADR» — упоминание без ответа, другой вариант, карточка с совпадающим префиксом; каждый здесь
отказывает, ничего не записав. Выбор берётся из реестра, не из вызова; запись — импорт оператора.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from spa_core.owner_queue import owner_answer as oa

NOW = datetime(2026, 10, 27, 19, 30, tzinfo=timezone.utc)  # FROZEN-DATE-OK: injected-clock — record_session_answer(now=NOW)
CARD = "owner-decision-demo-vopros"
QUESTION = "\n## Что от тебя нужно\n1. Закрыть\n2. Оставить\n"


def _card(tmp_path, name=CARD, body=QUESTION):
    p = tmp_path / f"{name}.md"
    p.write_text("---\ntitle: Демо\nstatus: needs-owner\nowner_choice: \"\"\n---\n" + body, encoding="utf-8")
    return p


def _register(tmp_path, *, card=CARD, choice="1", question=None, drop=(), **top):
    entry = {"card": card, "adr": "ADR-999", "choice": choice, "label": "закрыть как устаревшую",
             "owner_text": "Закрыть как устаревшую (Recommended)", "event": "toolu_demo#1",
             "question_sha256": question or oa.question_version("---\n---\n" + QUESTION), "kind": "option"}
    for k in drop:
        entry.pop(k)
    doc = {"schema": oa.SESSION_REGISTER_SCHEMA, "adr": "ADR-999", "trust": oa.TRUST_OPERATOR_IMPORT,
           "channel": oa.SESSION_VIA, "answers": [entry], **top}
    p = tmp_path / "owner-answers-demo.json"
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return p


def test_recorded_session_answer_closes_the_question_as_operator_import(tmp_path):
    card = _card(tmp_path)
    r = oa.record_session_answer(card, register_path=_register(tmp_path), choice_num="1", now=NOW)
    text = card.read_text(encoding="utf-8")
    assert r["status"] == "owner-done" and "status: owner-done" in text
    assert f"owner_answer_via: {oa.SESSION_VIA}" in text
    assert f"owner_answer_trust: {oa.TRUST_OPERATOR_IMPORT}" in text
    assert "owner_answer_event: toolu_demo#1" in text
    assert f"owner_choice_execution: {oa.EXECUTION_SEPARATE}" in text
    assert "закрыть как устаревшую" in text and "импорт оператора" in text
    assert "исполнение выбранной работы — отдельная задача" in text


def _refused(card, **kw):
    before = card.read_bytes()
    with pytest.raises(oa.SessionAnswerRefused):
        oa.record_session_answer(card, now=NOW, **kw)
    assert card.read_bytes() == before, "отказ обязан ничего не писать"


def test_arb_case_1_mention_without_an_answer_is_refused(tmp_path):
    card = _card(tmp_path)
    adr = tmp_path / "ADR-999-example.md"
    adr.write_text("# Notes\n" + CARD, encoding="utf-8")
    _refused(card, register_path=adr, choice_num="2")


def test_arb_case_2_record_says_1_caller_says_2_is_refused(tmp_path):
    _refused(_card(tmp_path), register_path=_register(tmp_path, choice="1"), choice_num="2")


def test_arb_case_3_longer_card_id_with_matching_prefix_is_refused(tmp_path):
    _refused(_card(tmp_path), register_path=_register(tmp_path, card=CARD + "-other"), choice_num="1")
    longer = _card(tmp_path, name=CARD + "-2")
    _refused(longer, register_path=_register(tmp_path, card=CARD), choice_num="1")


def test_changed_question_does_not_inherit_the_answer(tmp_path):
    card = _card(tmp_path, body=QUESTION + "3. Новый вариант\n")
    _refused(card, register_path=_register(tmp_path), choice_num="1")


@pytest.mark.parametrize("missing", ["owner_text", "event", "question_sha256", "choice"])
def test_entry_without_source_or_version_is_refused(tmp_path, missing):
    _refused(_card(tmp_path), register_path=_register(tmp_path, drop=(missing,)), choice_num="1")


@pytest.mark.parametrize("top", [{"trust": "owner-verified"}, {"channel": "telegram"}, {"schema": "x"}])
def test_register_not_declared_as_operator_import_is_refused(tmp_path, top):
    _refused(_card(tmp_path), register_path=_register(tmp_path, **top), choice_num="1")


def test_same_event_is_idempotent_and_a_different_answer_is_refused(tmp_path):
    card, reg = _card(tmp_path), _register(tmp_path)
    oa.record_session_answer(card, register_path=reg, choice_num="1", now=NOW)
    once = card.read_bytes()
    assert oa.record_session_answer(card, register_path=reg, choice_num="1", now=NOW)["already"]
    assert card.read_bytes() == once
    other = _register(tmp_path, choice="2")
    _refused(card, register_path=other, choice_num="2")


def test_closed_cards_are_verified_against_the_register(tmp_path):
    card = _card(tmp_path)
    reg = _register(tmp_path)
    oa.record_session_answer(card, register_path=reg, choice_num="1", now=NOW)
    assert oa.verify_session_answers(reg, tmp_path) == [(CARD, None)]
    card.write_text(card.read_text(encoding="utf-8").replace("owner_choice: 1", "owner_choice: 2"), encoding="utf-8")
    assert "выбор" in oa.verify_session_answers(reg, tmp_path)[0][1]


def test_the_real_register_is_complete_and_exact():
    """Реестр 18 ответов 27.10: каждая запись полна, имена уникальны, выбор совпадает с ADR."""
    reg = oa.load_session_register(Path(__file__).resolve().parents[2]
                                   / "docs/decisions/owner-answers-2026-10-27-session.json")
    names = [e["card"] for e in reg["answers"]]
    assert len(names) == 18 and len(set(names)) == 18
    for name in names:
        oa.session_entry(reg, name)
