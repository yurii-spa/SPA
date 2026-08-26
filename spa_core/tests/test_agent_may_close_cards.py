"""Агенту разрешено ЗАКРЫВАТЬ карточки — но только с проверенным основанием (ADR-146).

Решение владельца 2026-08-26, дословно: «**Карточки тоже закрывай сам, разрешаю**».

Запрет снят не потому, что авария #350 перестала быть аварией, а потому, что он
защищал не то. Замер #350: нажатие «✅ Принято» поставило терминальный статус в
момент, когда критерий приёмки НЕ был выполнен (карточка требовала «`curl -I …`
больше не отвечает 404», спустя 18 минут он всё ещё отвечал 404), и обещанной
перепроверки делать стало некому — пункт выбыл из очереди. Закрыл карточку
**ВЛАДЕЛЕЦ кнопкой**, не агент.

Значит охраняемое свойство — не «кто нажал», а **«терминальный статус означает
проверенный критерий»**. Оно и оставлено машинным. Этот файл проверяет ОБА конца:
что разрешение действительно дано и что уцелевшая половина запрета уцелела.
"""
from __future__ import annotations

import pytest

from spa_core.monitoring import tracker_status_sentinel as tss
from spa_core.owner_queue import queue as qmod
from spa_core.owner_queue.queue import (
    AGENT_CLOSABLE_STATUS,
    ATTRIBUTION_CRITICAL_STATUSES,
    OWNER_ACCEPTED_STATUS,
    OWNER_ONLY_STATUSES,
    OwnerDoneForbidden,
    create_card,
    set_status,
)
from spa_core.owner_queue.status_audit import read_status, read_trail

#: ВНИМАНИЕ при добавлении классов сюда: имя обязано начинаться с `Test`.
#
# В проекте нет `python_classes` в конфиге, поэтому pytest собирает ТОЛЬКО `Test*`. Первая
# редакция этого файла звалась `TheOwnerDelegatedClosing` и собрала НОЛЬ тестов — файл был
# зелёным, не проверив ничего. Ровно тот же молчаливый проход, что 26.08 нашёлся в
# `test_no_new_agent_was_introduced` (пустой glob под другим CWD): «не измерено» становится
# неотличимо от «прошло», и неотличимо в безопасную сторону.
#
# Соседние файлы уцелели по другой причине: они наследуют `unittest.TestCase`, а такие классы
# pytest собирает независимо от имени. Здесь наследования нет — значит держит только имя.


def _card(tmp_path, status="needs-owner"):
    return create_card("owner-decision", "проба", "тело", status=status,
                       tracker_dir=tmp_path)


class TestOwnerDelegatedClosing:
    """Первая половина: разрешение действительно дано, а не описано словами."""

    def test_an_agent_can_close_a_card_with_evidence(self, tmp_path):
        card = _card(tmp_path)
        set_status(card, AGENT_CLOSABLE_STATUS,
                   closed_by="agent", evidence="критерий проверен: тест зелёный")
        assert read_status(card) == "owner-done"

    def test_the_closure_names_who_closed_it_and_on_what_grounds(self, tmp_path):
        """Иначе закрытие неотличимо от пропажи вопроса — ровно цена аварии #350."""
        card = _card(tmp_path)
        set_status(card, AGENT_CLOSABLE_STATUS,
                   closed_by="agent", evidence="curl отвечает 200")
        trail = " ".join(i["raw"] for i in read_trail(card.read_text(encoding="utf-8")))
        assert "closed_by:agent" in trail
        assert "curl отвечает 200" in trail

    def test_the_evidence_cannot_break_the_trail_format(self, tmp_path):
        """Основание с разделителем следа внутри развалило бы разбор строки на поля."""
        card = _card(tmp_path)
        set_status(card, AGENT_CLOSABLE_STATUS,
                   closed_by="agent", evidence="было · стало · снова")
        raws = [i["raw"] for i in read_trail(card.read_text(encoding="utf-8"))]
        assert raws, "след не записан вовсе"
        assert read_status(card) == "owner-done"


class TestTheHalfOfTheGuardThatSurvives:
    """Вторая половина, и она важнее: терминальный статус = проверенный критерий."""

    def test_closing_without_evidence_is_refused(self, tmp_path):
        card = _card(tmp_path)
        with pytest.raises(OwnerDoneForbidden):
            set_status(card, AGENT_CLOSABLE_STATUS)
        assert read_status(card) == "needs-owner", "карточка закрылась вопреки отказу"

    def test_closing_with_a_name_but_no_grounds_is_refused(self, tmp_path):
        """«Закрыл агент» без «на каком основании» — подпись под пустым местом."""
        card = _card(tmp_path)
        with pytest.raises(OwnerDoneForbidden):
            set_status(card, AGENT_CLOSABLE_STATUS, closed_by="agent")

    def test_owner_accepted_stays_owner_only(self, tmp_path):
        """Это дословно СЛОВА владельца — агент, ставящий их, выдумывает чужую реплику.

        И владельцу это ничего не стоит: статус нетерминален (ADR-124), закрывать
        через него было нечего.
        """
        card = _card(tmp_path)
        with pytest.raises(OwnerDoneForbidden):
            set_status(card, OWNER_ACCEPTED_STATUS,
                       closed_by="agent", evidence="сколь угодно убедительное")
        assert OWNER_ACCEPTED_STATUS in OWNER_ONLY_STATUSES

    def test_a_card_is_never_born_closed(self, tmp_path):
        """У новорождённой карточки проверять ещё нечего.

        Карточка, рождённая закрытой, — это вопрос, которого никогда не задавали;
        обойти требование основания через `create_card` нельзя.
        """
        for status in sorted(ATTRIBUTION_CRITICAL_STATUSES):
            with pytest.raises(OwnerDoneForbidden):
                create_card("owner-decision", f"мертворождённая {status}",
                            status=status, tracker_dir=tmp_path)


class TestTheSentinelDidNotGoQuiet:
    """Разрешение сняло вопрос «кому можно», но не вопрос «осталась ли запись»."""

    def test_an_unattributed_close_is_still_critical(self):
        """Сторож, оставшийся на суженном наборе, замолчал бы о самом терминальном."""
        assert tss._severity("new", "owner-done") == "CRITICAL"
        assert tss._severity("new", "owner-accepted") == "CRITICAL"

    def test_leaving_the_owner_queue_without_closing_is_still_critical(self):
        assert tss._severity("needs-owner", "ingested") == "CRITICAL"

    def test_an_ordinary_transition_is_still_only_warn(self):
        """Обратный контроль: громкость не размазана на всё подряд."""
        assert tss._severity("new", "in-progress") == "WARN"

    def test_the_sentinel_reads_the_attribution_set_from_the_queue(self):
        """Два разъехавшихся перечня — способ замолчать ровно о новом члене класса.

        Тот же сторож стоял над `OWNER_ONLY_STATUSES` (#143–#145); после ADR-146
        связка перешла на более широкий набор, и она нужна там же.
        """
        assert tss.ATTRIBUTION_CRITICAL_STATUSES == qmod.ATTRIBUTION_CRITICAL_STATUSES

    def test_the_attribution_set_is_strictly_wider_than_owner_only(self):
        """Иначе переход на новое имя — переименование, а не расширение."""
        assert OWNER_ONLY_STATUSES < ATTRIBUTION_CRITICAL_STATUSES
        assert AGENT_CLOSABLE_STATUS in ATTRIBUTION_CRITICAL_STATUSES
