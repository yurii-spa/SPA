"""Проба `subject_taking_leaves_a_guard_receipt` — критерий карточки заказа G38 п. 3.

Проба закрывает карточку не ЦЕНОЙ класса (она потрачена и задним числом не
меняется), а ПРОВОДКОЙ: пока у взятия предмета нет наблюдаемого следа обращения
к сторожу захвата, будущее столкновение не будет отличимо от передачи.

Обе стороны закреплены у каждого правила, и все пять «не измерено» проверены
отдельно — включая ВЫРОЖДЕННЫЙ проход (взятий в окне ноль: «квитанция есть у
всех» верно по построению и ответом не является).

# FROZEN-DATE-OK: injected-clock — проба принимает `now=` параметром, и каждый
# тест передаёт и фиксированный `now`, и фиксированный `generated_at` отчёта:
# обе стороны закреплены, календарь на вердикт не влияет.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from spa_core.monitoring import card_acceptance as CA
from spa_core.monitoring import duplicate_subject_census as M

NOW = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)
PROBE = "subject_taking_leaves_a_guard_receipt"


def report(*, measured=True, takings=10, without=0, lost=0, sessions=0,
           made="2026-09-28T11:00:00Z", receipts=True, numbers=True) -> dict:
    doc = {"generated_at": made, "measured": measured,
           "status": M.STATUS_OPEN if (without or lost) else M.STATUS_CLOSED,
           "reason": None if measured else "журнала нет",
           "price": {"lost_coordinates": lost,
                     "sessions_on_lost_coordinates": sessions},
           "guard_wiring": {"measured": True}}
    if receipts:
        section = {"window_days": 30}
        if numbers:
            section["window_takings"] = takings
            section["window_takings_without_receipt"] = without
        doc["receipts"] = section
    return doc


def verdict(doc, *, now=NOW, arg=None):
    return CA._probe_subject_taking_leaves_a_guard_receipt(arg, now=now, report=doc)


class TestRegistered:
    def test_the_probe_is_in_the_registry(self):
        assert PROBE in CA.PROBES

    def test_registry_entry_is_this_function(self):
        assert CA.PROBES[PROBE] is CA._probe_subject_taking_leaves_a_guard_receipt


class TestVerdicts:
    def test_every_taking_has_a_receipt_is_satisfied(self):
        state, why = verdict(report(takings=7, without=0))
        assert state == CA.SATISFIED and "7" in why

    def test_a_taking_without_a_receipt_is_a_finding(self):
        state, why = verdict(report(takings=310, without=256, lost=7, sessions=9))
        assert state == CA.NOT_SATISFIED
        assert "256" in why and "310" in why and "7" in why

    def test_the_price_is_named_but_does_not_decide_the_verdict(self):
        """Цена НЕ входит в критерий: она потрачена, и закрыть её нечем."""
        state, _ = verdict(report(takings=5, without=0, lost=7, sessions=9))
        assert state == CA.SATISFIED


class TestThirdOutcomes:
    def test_empty_window_is_unmeasured_not_satisfied(self):
        state, why = verdict(report(takings=0, without=0))
        assert state == CA.UNMEASURED and "по построению" in why

    def test_census_not_measured_is_unmeasured(self):
        state, why = verdict(report(measured=False))
        assert state == CA.UNMEASURED and "журнала нет" in why

    def test_stale_artifact_is_unmeasured(self):
        state, why = verdict(report(made="2026-09-20T11:00:00Z"))
        assert state == CA.UNMEASURED and "старше предела" in why

    def test_fresh_artifact_at_the_limit_is_still_read(self):
        """Обратная сторона предела: ровно на границе проба ещё судит."""
        state, _ = verdict(report(made="2026-09-26T13:00:00Z"))
        assert state == CA.SATISFIED

    def test_unreadable_timestamp_is_unmeasured(self):
        state, why = verdict(report(made="не-дата"))
        assert state == CA.UNMEASURED and "отметки времени" in why

    def test_missing_receipts_section_is_unmeasured(self):
        state, why = verdict(report(receipts=False))
        assert state == CA.UNMEASURED and "receipts" in why

    def test_missing_numbers_are_unmeasured_not_zero(self):
        state, why = verdict(report(numbers=False))
        assert state == CA.UNMEASURED and "сказать нечем" in why

    def test_an_argument_is_refused_not_ignored(self):
        state, why = verdict(report(), arg="spa_core/x.py")
        assert state == CA.UNMEASURED and "не принимает аргумента" in why

    def test_a_non_dict_report_is_unmeasured(self):
        state, why = CA._probe_subject_taking_leaves_a_guard_receipt(
            None, now=NOW, report={"measured": True})
        assert state == CA.UNMEASURED

    def test_absent_artifact_on_disk_is_unmeasured(self, tmp_path):
        state, why = CA._probe_subject_taking_leaves_a_guard_receipt(
            None, now=NOW, repo_root=str(tmp_path))
        assert state == CA.UNMEASURED and "НЕ НАБЛЮДЁН" in why

    def test_artifact_on_disk_is_read_when_no_report_is_injected(self, tmp_path):
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / M.ARTIFACT_NAME).write_text(
            json.dumps(report(takings=3, without=1), ensure_ascii=False),
            encoding="utf-8")
        state, why = CA._probe_subject_taking_leaves_a_guard_receipt(
            None, now=NOW, repo_root=str(tmp_path))
        assert state == CA.NOT_SATISFIED and "1 из 3" in why
