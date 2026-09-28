"""Проба `g17_subject_state_is_measured` — критерий карточки G37 п. 5 ([ADR-499]).

Прибор G17 с 16.09 печатал на живом дереве одну строку `UNMEASURED`
«схлопывающих наследников не найдено», и за ней прятались ТРИ разных
состояния: измеренный пустой класс, спор переписи с источником и настоящее
«не измерено». Проба меряет ИСХОД в живом артефакте — назван ли предмет
измеренно, — а не наличие кода.

Обе стороны закреплены у каждого правила; все «не измерено» проверены
отдельно, и отдельно же проверено, что проба НЕ проходит подстрокой
(ADR-333): состояние источника обязано быть словом из ЗАКРЫТОГО перечня.

# FROZEN-DATE-OK: injected-clock — проба принимает `now=` параметром, и каждый
# тест передаёт и фиксированный `now`, и фиксированный `generated_at` отчёта:
# обе стороны закреплены, календарь на вердикт не влияет.
"""
from __future__ import annotations

from datetime import datetime, timezone

from spa_core.monitoring import card_acceptance as CA
from spa_core.monitoring import heir_all_rows_price as G17

NOW = datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)
PROBE = "g17_subject_state_is_measured"


def report(*, state=G17.SUBJECT_NO_COLLAPSE, status=G17.STATUS_OK,
           pop=0, measured=19, unmeasured=98,
           made="2026-09-28T11:00:00Z", subject=True) -> dict:
    doc = {"generated_at": made, "status": status, "heirs_population": pop,
           "census_measured": measured, "census_unmeasured": unmeasured,
           "unmeasured_reason": "схлопывающих наследников не найдено"}
    if subject:
        doc["subject"] = {"state": state, "reason": "по построению теста",
                          "rows_on_s_one": 4, "rows_on_s_true": 5}
    return doc


def verdict(doc, *, now=NOW, arg=None):
    return CA._probe_g17_subject_state_is_measured(arg, now=now, report=doc)


class TestRegistered:
    def test_the_probe_is_in_the_registry(self):
        assert PROBE in CA.PROBES

    def test_registry_entry_is_this_function(self):
        assert CA.PROBES[PROBE] is CA._probe_g17_subject_state_is_measured


class TestTheWholeLoopIsGreen:
    def test_a_measured_empty_class_satisfies(self):
        state, why = verdict(report())
        assert state == CA.SATISFIED, why
        assert "no_collapse_at_source" in why and "98" in why

    def test_a_collapsing_source_with_heirs_also_satisfies(self):
        """Предмет ЕСТЬ и население непусто — прибор снова мерит цену."""
        state, why = verdict(report(state=G17.SUBJECT_COLLAPSES,
                                    status=G17.STATUS_CRITICAL, pop=3))
        assert state == CA.SATISFIED, why


class TestEachBrokenLinkIsRed:
    def test_no_subject_section_is_the_old_silent_form(self):
        state, why = verdict(report(subject=False))
        assert state == CA.NOT_SATISFIED, why
        assert "не спрашивали" in why

    def test_an_empty_population_still_called_unmeasured_is_a_regression(self):
        state, why = verdict(report(status=G17.STATUS_UNMEASURED, pop=0))
        assert state == CA.NOT_SATISFIED, why
        assert "ADR-499" in why

    def test_a_missing_census_breakdown_is_red(self):
        doc = report()
        del doc["census_unmeasured"]
        state, why = verdict(doc)
        assert state == CA.NOT_SATISFIED, why

    def test_a_census_breakdown_that_is_not_a_number_is_red(self):
        state, why = verdict(report(unmeasured="много"))
        assert state == CA.NOT_SATISFIED, why


class TestTheThirdOutcomeIsNeverACleanPass:
    def test_an_unmeasured_subject_is_unmeasured_and_not_satisfied(self):
        state, why = verdict(report(state=G17.SUBJECT_UNMEASURED))
        assert state == CA.UNMEASURED, why

    def test_a_stale_artifact_is_unmeasured(self):
        state, why = verdict(report(made="2026-09-27T12:00:00Z"))
        assert state == CA.UNMEASURED and "старше предела" in why

    def test_a_fresh_artifact_inside_the_limit_is_judged(self):
        """Обратная сторона предела: внутри него вердикт ВЫНОСИТСЯ."""
        state, _ = verdict(report(made="2026-09-28T01:30:00Z"))
        assert state == CA.SATISFIED

    def test_an_unreadable_timestamp_is_unmeasured_and_not_fresh(self):
        state, why = verdict(report(made="позавчера"))
        assert state == CA.UNMEASURED and "возраст записи НЕ ИЗМЕРЕН" in why

    def test_a_report_that_is_not_a_dict_is_unmeasured(self):
        state, why = verdict(["не словарь"])
        assert state == CA.UNMEASURED, why

    def test_an_argument_is_refused_because_the_subject_has_no_file_form(self):
        state, why = verdict(report(), arg="spa_core/monitoring/heir_all_rows_price.py")
        assert state == CA.UNMEASURED and "не принимает аргумента" in why


class TestItDoesNotPassBySubstring:
    def test_a_state_outside_the_closed_vocabulary_is_unmeasured(self):
        """«Похожее» слово не есть измеренное состояние (ADR-333)."""
        state, why = verdict(report(state="no_collapse_at_source_probably"))
        assert state == CA.UNMEASURED, why
        assert "закрытого перечня" in why

    def test_an_empty_state_is_read_as_no_subject_section(self):
        state, why = verdict(report(state=""))
        assert state == CA.NOT_SATISFIED, why
