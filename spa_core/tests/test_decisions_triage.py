"""spa_core/tests/test_decisions_triage.py — RM-TRUTH-01 / ADR-580 C5/C6: owner-decision triage
by DECLARED ``subject:`` only (never guessed from title/body keywords — ``subject.subject_of``
is the one shared classifier). Groups: your subject · undeclared (agent triages) · answered ·
accepted · prod-only (on the Mac, not yet on origin). The count shown on Home equals the count
on the Решения tab — one function, read twice, never two.
"""
from __future__ import annotations

from spa_core.studio_os import company_truth as ct


def _card(title, status, subject=None, type_="owner-decision"):
    fm = {"title": title, "status": status, "type": type_}
    if subject is not None:
        fm["subject"] = subject
    return {"fm": fm, "body": "", "trail": [], "path": None}


def test_declared_subject_goes_to_your_subject_group():
    cards = {"own-a.md": _card("Переключить приложение", "needs-owner", subject="physical_action")}
    out = ct.decisions_triage(cards, None, None)
    assert out["counts"]["owner"] == 1
    assert out["groups"]["owner"][0]["subject"] == "PHYSICAL_ACTION"


def test_missing_subject_goes_to_undeclared_agent_triages():
    cards = {"own-b.md": _card("Закрыть три PR", "needs-owner")}  # no subject: declared at all
    out = ct.decisions_triage(cards, None, None)
    assert out["counts"]["undeclared"] == 1
    assert out["counts"]["owner"] == 0
    assert out["groups"]["undeclared"][0]["subject"] == "UNKNOWN"


def test_the_keyword_that_used_to_cause_a_false_money_classification_is_now_undeclared():
    """The historical bug this closes: a card about PR access ("ключ" in the body) used to be
    classified as subject #1 (money) by a keyword guesser. The new classifier reads ONLY the
    declared ``subject:`` field — this card (no field) must be UNDECLARED, never MONEY."""
    cards = {"own-c.md": {"fm": {"title": "Закрыть три PR", "status": "needs-owner", "type": "owner-decision"},
                          "body": "не хватает прав ключу PAT", "trail": [], "path": None}}
    out = ct.decisions_triage(cards, None, None)
    assert out["groups"]["undeclared"][0]["subject"] == "UNKNOWN"
    assert out["counts"]["owner"] == 0


def test_owner_accepted_status_goes_to_accepted_group_regardless_of_subject():
    cards = {"own-d.md": _card("Принято", "owner-accepted", subject="money")}
    out = ct.decisions_triage(cards, None, None)
    assert out["counts"]["accepted"] == 1
    assert out["groups"]["accepted"][0]["subject"] == "MONEY"


def test_prod_only_cards_are_shown_in_their_own_group():
    # Wave 2 integration fix (RM-TRUTH-01): a prod-only row used to be a bare card-id STRING, and the v2
    # Решения tab renders every row through the same `renderDecisionItem(d)` that reads
    # `d.title_ru`/`d.id` — a string has neither, so every prod-only card rendered as a blank
    # «не измерено» card. The row is a dict with a real title now, like every other group.
    origin = {"own-a.md": _card("A", "needs-owner", subject="money")}
    prod = {"own-a.md": _card("A", "needs-owner", subject="money"),
           "own-only-on-mac.md": _card("Только на Маке", "needs-owner")}
    out = ct.decisions_triage(origin, prod, None)
    assert out["counts"]["prod_only"] == 1
    assert out["groups"]["prod_only"] == [
        {"id": "own-only-on-mac", "title_ru": "Только на Маке", "title_en": "Только на Маке"}]


def test_no_tracker_is_not_measured_not_zero():
    out = ct.decisions_triage(None, None, None)
    assert out["state"] == ct.NOT_MEASURED
    assert out["counts"] == {}


def test_home_needs_tile_count_equals_the_triage_counts_one_function():
    cards = {"own-a.md": _card("A", "needs-owner", subject="money"),
            "own-b.md": _card("B", "needs-owner")}
    triage = ct.decisions_triage(cards, None, None)
    tile = ct.tile_needs(triage)
    summary = ct.studio_decisions_summary(triage)
    assert tile["value"] == summary["value"] == triage["counts"]
    assert tile["value"]["owner"] == 1 and tile["value"]["undeclared"] == 1


def test_only_needs_owner_and_owner_decision_type_cards_are_considered():
    cards = {"inbox-unrelated.md": _card("Задача агента", "in-progress", type_="agent-task")}
    out = ct.decisions_triage(cards, None, None)
    assert out["counts"]["owner"] == 0 and out["counts"]["undeclared"] == 0


def test_owner_group_is_ordered_subject_then_oldest_first():
    """P1 recovery: the owner group was alphabetical by file name, so the order of real owner
    questions on the Решения tab said nothing about which matters first. ADR-285 order now:
    money → public numbers/naming/legal → irreversible → physical, oldest first within one."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    spec = {"own-a-disk": ("irreversible", 20), "own-b-cash": ("money", 19), "own-c-base": ("money", 17),
            "own-d-site": ("public", 12), "own-e-app": ("physical_action", 30)}
    cards = {f"{k}.md": _card(k, "needs-owner", subject=s) for k, (s, _) in spec.items()}
    v1 = {"pending": [{"id": k, "title": k, "created_at": (now - timedelta(days=d)).isoformat()}
                      for k, (_, d) in spec.items()]}
    out = ct.decisions_triage(cards, None, now, v1)
    assert [r["id"] for r in out["groups"]["owner"]] == [
        "own-b-cash", "own-c-base", "own-d-site", "own-a-disk", "own-e-app"]


def test_full_card_text_passes_through_read_only_end_to_end():
    """ARB 09.10 (DIRECTOR-OS-UX-02 round 4): tracker card body → mission_control.decision_item →
    decisions_triage row: the WHOLE card, section by section, unchanged and not truncated at 400."""
    from spa_core.studio_os import mission_control as mc
    long_reason = "Длинное объяснение. " * 60
    body = f"## Что случилось и почему это важно\n{long_reason}\n\n## Что от тебя нужно\n1. да\n2. нет\n"
    card = {"fm": {"title": "T", "status": "needs-owner", "type": "owner-decision", "subject": "money"},
            "body": body, "trail": []}
    v1 = mc.decision_item("own-x.md", card, None, None, None)
    assert len(v1["reason"]) <= 400 and len(v1["full_sections"][0]["text"]) > 400
    out = ct.decisions_triage({"own-x.md": card}, None, None, decisions_v1={"pending": [v1], "recently_resolved": []})
    row = out["groups"]["owner"][0]
    assert row["full_sections_ru"] == v1["full_sections"]
    assert row["full_sections_ru"][1] == {"heading": "Что от тебя нужно", "text": "1. да\n2. нет"}


# moved from test_owner_view.py (ARB 09.10 round 4): company_truth may only be imported by its own
# allow-listed tests (test_company_truth_import_ratchet) — the seam test belongs here.
def test_company_truth_passes_the_board_rows_read_only():
    """The model seam: mission_control's board rows → studio_tasks.blocked_items, unchanged and without invention."""
    board = {"counts": {"blocked": 2}, "queued": 0,
             "blocked": [{"id": "a", "title": "A", "last_transition": None, "created": "2026-09-01",
                          "blocked_by": "ждёт ключ", "next_step": "получить ключ"},
                         {"id": "b", "title": "B", "last_transition": None, "created": None,
                          "blocked_by": None, "next_step": None}]}
    cell = ct.studio_tasks(board, None)
    assert [x["card"] for x in cell["blocked_items"]] == ["a", "b"]
    assert cell["blocked_items"][0]["reason"] == "ждёт ключ" and cell["blocked_items"][1]["reason"] is None
    assert ct.studio_tasks({"counts": {"blocked": 1}}, None)["blocked_items"] is None   # older board: not invented
