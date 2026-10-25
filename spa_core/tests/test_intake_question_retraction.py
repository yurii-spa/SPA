"""ADR-807 — вопрос, заведённый ИНТЕЙКОМ, снимается агентом как дефект очереди ADR-285.

**Что воспроизводится.** Замер цикла #930 (2026-10-25): из **29** карточек `needs-owner` на
`origin/main` **11** не относятся ни к одному из трёх предметов ADR-285 — шесть уточнений о
ТЕСТОВЫХ заметках владельца («купить зонт в пятницу» ×5 и «это просто тест, никакой задачи
нету») и пять носителей интейка, чей предмет уже стои́т отдельной `inbox`-карточкой. ADR-285
поручает такие карточки агенту дословно; гейт ADR-551 отказывал всем одиннадцати ОДНИМ текстом
(«an owner decision is closed only on the owner's recorded answer»). Поручение владельца было
НЕВЫПОЛНИМО кодом очереди.

**У каждой проверки здесь контроль в обе стороны:** она краснеет на настоящей форме вреда и
молчит на здоровой. Проверяется ИСХОД (закрылась ли карточка), а не наличие параметра.

Литеральных дат и номеров процессов в файле нет — ни одна проверка не зависит от календаря
и от того, какой pid занят на хосте (`.claude/rules/deployment.md`).
"""
from __future__ import annotations

import pytest

from spa_core.owner_queue import queue as Q

RULE = Q.RETRACTION_RULE_TOKEN
INTAKE = {"source": sorted(Q.INTAKE_SOURCES)[0]}
WHO = "agent:orchestrator cycle-test"
WHY = f"дефект очереди {RULE}: вопрос интейка вне трёх предметов владельца"


def _close(fm: dict, *, new: str = "done", closed_by: str | None = WHO,
           evidence: str | None = WHY, old: str = "needs-owner") -> None:
    Q.check_lifecycle("owner-decision", old, new, fm=fm, closed_by=closed_by,
                      evidence=evidence, name="card.md")


class TestTheRefusalThatBlockedTheOwnersOwnRule:
    def test_positive_control_the_pre_adr807_shape_is_still_refused(self):
        """Карточка БЕЗ заявленной ретракции закрывается по-прежнему только ответом владельца.

        Это и есть прежнее поведение гейта ADR-551: снимать его целиком было нельзя.
        """
        with pytest.raises(Q.LifecycleRefused) as got:
            _close(dict(INTAKE), evidence="просто закрываю")
        assert "owner's recorded answer" in str(got.value)

    def test_the_refusal_now_names_the_way_out(self):
        """Отказ обязан НАЗВАТЬ ретракцию: иначе сессия идёт искать обход, а не правило."""
        with pytest.raises(Q.LifecycleRefused) as got:
            _close(dict(INTAKE), evidence="просто закрываю")
        text = str(got.value)
        assert RULE in text and "ADR-807" in text and "--evidence" in text

    def test_negative_control_the_retraction_passes(self):
        """Здоровая форма: вопрос интейка, никем не тронутый, снят с названным правилом."""
        _close(dict(INTAKE))  # не поднимает

    def test_owner_answer_path_is_untouched(self):
        """Ответ владельца закрывает карточку как раньше — ретракция ничего ему не меняет."""
        _close({"owner_choice": "2"}, evidence="ответ владельца разобран")


class TestConditionsAreAsTightAsTheBridges:
    """Условия ретракции — той же тесноты, что у ретракции моста (ADR-066 C2)."""

    def test_only_an_intake_born_question(self):
        with pytest.raises(Q.LifecycleRefused) as got:
            _close({"source": "telegram"})
        assert "производитель карточки" in str(got.value)

    def test_a_card_without_a_producer_is_not_retractable(self):
        """`source` пуст ⇒ производитель НЕ НАЗВАН. Угадывать его запрещено."""
        with pytest.raises(Q.LifecycleRefused) as got:
            _close({})
        assert "производитель карточки" in str(got.value)

    def test_a_card_someone_already_moved_is_not_retractable(self):
        """Тронутую карточку мог тронуть владелец — то же условие, что у моста."""
        fm = dict(INTAKE, status_trail_items=[{"old": "needs-owner", "new": "in-progress"}])
        with pytest.raises(Q.LifecycleRefused) as got:
            _close(fm)
        assert "уже двигали" in str(got.value)

    def test_only_done_never_an_owner_status(self):
        """`owner-done` остаётся словом владельца: ретракция его не выдаёт (инв. #14)."""
        with pytest.raises(Q.LifecycleRefused) as got:
            _close(dict(INTAKE), new=Q.AGENT_CLOSABLE_STATUS)
        assert "только `done`" in str(got.value)

    def test_the_retraction_must_be_attributed(self):
        """Без `closed_by` ретракция анонимна — журнал аудита не узнает, кто снял."""
        with pytest.raises(Q.LifecycleRefused) as got:
            Q.check_lifecycle("owner-decision", "needs-owner", "done", fm=dict(INTAKE),
                              closed_by=None, evidence=WHY, name="card.md")
        # Отказ приходит раньше — у любого закрытия обязаны быть closed_by И evidence.
        assert "closed_by" in str(got.value)


class TestThreeOutcomesAreDistinguishable:
    """Инв. #17: «не заявлена» и «заявлена и не прошла» — РАЗНЫЕ исходы, а не один."""

    def test_not_claimed_returns_an_empty_reason(self):
        ok, why = Q.intake_retraction_verdict(
            new="done", fm=dict(INTAKE), closed_by=WHO, evidence="без правила", items=[])
        assert (ok, why) == (False, "")

    def test_claimed_and_failed_names_the_condition(self):
        ok, why = Q.intake_retraction_verdict(
            new="done", fm={"source": "voice"}, closed_by=WHO, evidence=WHY, items=[])
        assert ok is False and why, "заявленная и непрошедшая ретракция обязана назвать причину"
        assert "voice" in why

    def test_claimed_and_passed_has_no_reason_to_give(self):
        assert Q.intake_retraction_verdict(
            new="done", fm=dict(INTAKE), closed_by=WHO, evidence=WHY, items=[]) == (True, "")

    def test_every_unmet_condition_is_named_at_once(self):
        """Назвать ОДНО условие из трёх значило бы отправить сессию по кругу."""
        ok, why = Q.intake_retraction_verdict(
            new=Q.AGENT_CLOSABLE_STATUS, fm={"source": "voice", "status_trail_items": [{}]},
            closed_by="", evidence=WHY, items=[{}])
        assert ok is False
        for needle in ("только `done`", "производитель карточки", "уже двигали", "closed_by"):
            assert needle in why, needle


class TestTheFirstRetractionStillWorks:
    def test_bridge_retraction_is_not_broken(self):
        """Ретракция моста (ADR-066 C2) существовала до этой правки и обязана уцелеть."""
        Q.check_lifecycle("owner-decision", "needs-owner", "done",
                          fm={"finding_key": "k", "source": "findings_bridge"},
                          closed_by=sorted(Q.BRIDGE_CLOSERS)[0],
                          evidence="находка исчезла", name="card.md")

    def test_bridge_closer_without_a_finding_key_is_still_refused(self):
        with pytest.raises(Q.LifecycleRefused):
            Q.check_lifecycle("owner-decision", "needs-owner", "done", fm={},
                              closed_by=sorted(Q.BRIDGE_CLOSERS)[0],
                              evidence="находка исчезла", name="card.md")


class TestTheContractIsDeclaredOnce:
    def test_the_rule_token_is_not_retyped(self):
        """Правило названо ОДНИМ местом: перепечатка развела бы отказ и прибор."""
        assert RULE and Q.RETRACTION_RULE_TOKEN == RULE

    def test_done_is_reversible_so_a_wrong_judgement_is_repairable(self):
        """Суждение о предмете машинно не проверяется — значит оно обязано быть обратимым."""
        assert "new" in Q.CARD_TRANSITIONS["done"]
