"""F9 (ADR-580 §C10, REVIEW_1 amendment): SAME_HOST is its own honest icon.

Авария, который это чинит: заголовочная ячейка резилиенса несла СВОЮ,
более узкую карту значков без ``SAME_HOST`` и падала на ``❓`` ("не измерено")
там, где детальная секция (`build_resilience_section`) уже честно печатала 🟡
("все пробы прошли, офсайт — тот же хост"). Два читателя одного поля —
два разных ответа, молча.

Положительный контроль ниже воспроизводит ровно эту форму: ОДИН и тот же
``resilience_status.json`` подаётся в обе поверхности, и обе обязаны
согласиться — на 🟡, не на ❓ и не на ✅.
"""
from __future__ import annotations

import update_system_briefing as usb


def _doc(overall, notes=None):
    return {"overall": overall, "generated_at": "2026-10-05T08:00:00Z",
            "notes": notes or []}


def test_same_host_header_cell_is_the_amber_icon_not_unknown():
    cell = usb.resilience_header_cell(_doc("SAME_HOST"))
    assert cell.startswith("🟡"), f"SAME_HOST обязан печатать 🟡, получено: {cell!r}"
    assert "SAME_HOST" in cell


def test_header_cell_and_section_agree_on_the_same_icon_for_every_overall():
    """Обе поверхности читают ОДНУ карту — расхождение не воспроизводимо."""
    for overall in ("OK", "SAME_HOST", "WARNING", "UNKNOWN", "SOMETHING_NEW"):
        header_icon = usb.resilience_header_cell(_doc(overall)).split(" ", 1)[0]
        assert header_icon == usb._RESILIENCE_ICON.get(overall, "❓")


def test_ok_and_warning_are_unaffected_by_the_refactor():
    assert usb.resilience_header_cell(_doc("OK")).startswith("✅")
    assert usb.resilience_header_cell(_doc("WARNING")).startswith("⚠️")


def test_missing_rollup_is_unknown_not_crash():
    assert usb.resilience_header_cell({}) == (
        "❓ rollup unavailable (resilience_status.json missing)")
    assert usb.resilience_header_cell(None) == (
        "❓ rollup unavailable (resilience_status.json missing)")
