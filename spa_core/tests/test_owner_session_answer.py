"""Ответ владельца из сессии Claude Code закрывает карточку решения — только по ЗАПИСИ ответа (ADR-834).

Владелец 27.10: «я не хочу сам закрывать карточки руками, я хочу, чтобы это делал Claude». Граница:
ответ придумать нельзя — карточку закрывает только ADR, где ответ записан и карточка названа по имени.
"""
from datetime import datetime, timezone

import pytest

from spa_core.owner_queue import owner_answer as oa

NOW = datetime(2026, 10, 27, 19, 30, tzinfo=timezone.utc)  # FROZEN-DATE-OK: injected-clock — record_session_answer(now=NOW)
CARD = "owner-decision-demo-vopros"


def _card(tmp_path):
    p = tmp_path / f"{CARD}.md"
    p.write_text("---\ntitle: Демо\nstatus: needs-owner\n---\n\n## Что от тебя нужно\n1. Закрыть\n", encoding="utf-8")
    return p


def _adr(tmp_path, names_card=True):
    p = tmp_path / "ADR-999-owner-answers.md"
    p.write_text(f"# ADR-999\n| 1 | {CARD if names_card else 'другая-карточка'} | закрыть |\n", encoding="utf-8")
    return p


def test_recorded_session_answer_closes_the_card_with_its_source(tmp_path):
    card = _card(tmp_path)
    r = oa.record_session_answer(card, choice_num="1", choice_label="закрыть как устаревшую",
                                 adr_path=_adr(tmp_path), now=NOW)
    text = card.read_text(encoding="utf-8")
    assert r["status"] == "owner-done" and "status: owner-done" in text
    assert f"owner_answer_via: {oa.SESSION_VIA}" in text and "ADR-999" in text
    assert "закрыл агент" in text and "не агентом" not in text


@pytest.mark.parametrize("names_card", [False, None])
def test_no_recorded_answer_means_no_closure(tmp_path, names_card):
    card = _card(tmp_path)
    before = card.read_bytes()
    adr = _adr(tmp_path, names_card=bool(names_card)) if names_card is not None else tmp_path / "нет.md"
    with pytest.raises(oa.NotTheOwner):
        oa.record_session_answer(card, choice_num="1", choice_label="x", adr_path=adr, now=NOW)
    assert card.read_bytes() == before


def test_repeat_is_idempotent(tmp_path):
    card, adr = _card(tmp_path), _adr(tmp_path)
    oa.record_session_answer(card, choice_num="1", choice_label="x", adr_path=adr, now=NOW)
    once = card.read_bytes()
    assert oa.record_session_answer(card, choice_num="1", choice_label="x", adr_path=adr, now=NOW)["already"]
    assert card.read_bytes() == once
