"""Наблюдённая угроза доезжает до владельца — вариант А (ADR-146).

Карточка `own-red-team-nablyudennaya-ugroza-ne-doezzhaet`, решение владельца
2026-08-26 («карточки тоже закрывай сам, разрешаю»), рекомендация карточки — А.

Замер 18.08, четыре состояния подряд:

| что произошло на самом деле | слово аналитика | доезжало ли карточкой |
|---|---|---|
| разведка НАШЛА угрозу | `THREATS_PRESENT` | **НЕТ** |
| критика в симуляции атак | `CRITICAL` | да |
| мы сами остановлены выключателем | `CRITICAL` | да, каждый цикл |
| тихо | `NO_THREAT_OBSERVED` | нет (и правильно) |

Канал был ПЕРЕВЁРНУТ: эхо нашей же остановки шумело ежедневно, а настоящая
наблюдённая угроза молчала. Это fail-OPEN в канале тревоги.

Файл, который называла карточка, на `main` не существовал — он жил на удалённой
ветке (тот же класс, что и трижды в пакете ADR-133…142). Написан заново.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from spa_core.investment_os.agents.chief_investment import _RANK, _synthesise_posture
from spa_core.monitoring import house_view_gap as hvg

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)  # FROZEN-DATE-OK: injected-clock — часы
# инъектируются ПАРОЙ со «свежим» возрастом входа: обе стороны закреплены, сдвиг календаря тест
# не трогает.

#: Возраст входа, заведомо проходящий потолок свежести офиса, — иначе сверка честно ОТКАЖЕТСЯ
#: объявлять красноту в настоящем времени, и находки не будет по совсем другой причине.
FRESH = {"analyst:red_team": {"age_s": 60.0}}


def _analyst_findings(posture: str) -> list:
    """Сквозной прогон сборщика: постура аналитика → находки типа `analyst_red`.

    Именно СКВОЗНОЙ, а не проверка кортежа: тест, сторожащий константу, зеленеет и
    тогда, когда до этой константы больше никто не доходит.
    """
    doc = hvg.compute_gaps(
        chief=None, positions=None, rationale=None, registry_keys=None,
        analysts={"red_team": {"posture": posture, "posture_reason": ["threats_present"]}},
        now=NOW, ages=FRESH,
    )
    return [g for g in doc.get("gaps", []) if g.get("type") == "analyst_red"]


class TheObservedThreatNowReachesTheOwner(unittest.TestCase):
    """Главное утверждение файла — и ровно тот исход, которого не было."""

    def test_a_found_threat_produces_a_finding(self):
        """Сердце карточки: разведка НАШЛА угрозу ⇒ владелец узнаёт.

        До правки этот прогон давал ПУСТО — при том что эхо нашей же остановки
        давало находку каждый цикл.
        """
        found = _analyst_findings("THREATS_PRESENT")
        self.assertEqual(len(found), 1, f"наблюдённая угроза не доехала: {found}")
        self.assertEqual(found[0]["key"], "gap:analyst_red:red_team")
        self.assertIn("THREATS_PRESENT", found[0]["message"])

    def test_quiet_produces_nothing_end_to_end(self):
        """Обратный конец той же проверки: тишина не будит владельца."""
        self.assertEqual(_analyst_findings("NO_THREAT_OBSERVED"), [])

    def test_fail_closed_posture_produces_nothing_end_to_end(self):
        """«Не знаем» — не «нашли». Инвариант #17 на выходе канала тревоги."""
        self.assertEqual(_analyst_findings("UNKNOWN_CAUTIOUS"), [])

    def test_critical_still_produces_a_finding_end_to_end(self):
        """Вариант А только ПОДНИМАЕТ; ничего ранее доезжавшего не потеряно."""
        self.assertEqual(len(_analyst_findings("CRITICAL")), 1)

    def test_threats_present_is_an_analyst_red_token(self):
        self.assertIn("THREATS_PRESENT", hvg._ANALYST_RED_TOKENS,
                      "наблюдённая угроза снова не доезжает до владельца — исходный дефект")

    def test_the_echo_of_our_own_stop_still_reaches_too(self):
        """Обратный контроль: вариант А НИЧЕГО не понижает, он только поднимает.

        Если бы правка заодно убрала `CRITICAL`, мы бы починили одну половину и
        сломали другую — а карточка просила именно поднять, а не переставить.
        """
        for word in ("RED", "CRITICAL"):
            with self.subTest(word=word):
                self.assertIn(word, hvg._ANALYST_RED_TOKENS)

    def test_quiet_stays_quiet(self):
        """`NO_THREAT_OBSERVED` — наблюдение, а не тревога. Оно доезжать НЕ должно."""
        self.assertNotIn("NO_THREAT_OBSERVED", hvg._ANALYST_RED_TOKENS)

    def test_unknown_cautious_does_not_become_an_alarm(self):
        """Fail-closed постура — это «не знаем», а не «нашли». Карточку она не заводит.

        Инвариант #17 в лицах: «не измерено» обязано остаться отличимым от
        «измерено и плохо», в том числе на выходе канала тревоги.
        """
        self.assertNotIn("UNKNOWN_CAUTIOUS", hvg._ANALYST_RED_TOKENS)


class TheOtherLadderDidNotMove(unittest.TestCase):
    """Положительный контроль на ЧУЖУЮ лестницу — самое ценное в этом файле.

    `_RED_TOKENS` читают ТРИ места, и второе — `posture_vs_book` над постурой
    ОФИСА. Офис синтезирует свою постуру из режима и угрозы, поэтому
    `overall_posture` умеет быть буквально `THREATS_PRESENT`, а ранг у него **2**
    (наравне с `YELLOW`), не 3. Одна строка в общем кортеже молча приравняла бы
    ранг 2 к ранг-3 в чужой лестнице и завела вторую находку, которой карточка не
    просила.
    """

    def test_the_office_posture_gate_was_left_alone(self):
        self.assertEqual(hvg._RED_TOKENS, ("RED", "CRITICAL"),
                         "набор постуры офиса изменён — правка уехала за пределы карточки")

    def test_the_two_sets_actually_differ(self):
        """Иначе разделение — украшение: два имени над одним и тем же объектом."""
        self.assertNotEqual(set(hvg._RED_TOKENS), set(hvg._ANALYST_RED_TOKENS))

    def test_threats_present_ranks_below_critical_in_the_office_table(self):
        """Замер, ради которого наборы и разведены. Ранги — из живой таблицы."""
        self.assertEqual(_RANK["THREATS_PRESENT"], 2)
        self.assertEqual(_RANK["CRITICAL"], 3)
        self.assertEqual(_RANK["YELLOW"], _RANK["THREATS_PRESENT"])

    def test_the_office_can_really_emit_threats_present(self):
        """Не гипотеза: синтез офиса ВОЗВРАЩАЕТ это слово на реальном входе.

        Это и делает общий кортеж опасным — без такого замера разделение наборов
        выглядело бы предосторожностью на всякий случай.
        """
        posture, _ = _synthesise_posture("STABLE", "THREATS_PRESENT")
        self.assertEqual(posture, "THREATS_PRESENT")


class TheCauseIsNamedNotJustTheWord(unittest.TestCase):
    """Поднятая тревога обязана говорить ПОЧЕМУ — иначе вернётся авария #197.

    Читатель получает слово `CRITICAL` и разумно читает его как «нашли врага»,
    тогда как единственной причиной может быть, что остановлены МЫ САМИ.
    """

    def test_threats_present_has_a_human_reason_string(self):
        self.assertIn("threats_present", hvg._REASON_RU)
        self.assertTrue(hvg._REASON_RU["threats_present"].strip())

    def test_our_own_stop_is_named_as_an_echo_not_as_recon(self):
        self.assertIn("эхо", hvg._REASON_RU["kill_switch_already_active"])

    def test_an_unknown_reason_code_is_not_swallowed(self):
        """Сверка обязана быть ШИРЕ подопечного, иначе она его эхо (#197).

        Незнакомый код печатается вербатим, а не выбрасывается: аналитик волен
        назвать причину, о которой сверка не знает.
        """
        phrase = hvg.cause_phrase(["prichina_kotoroy_sverka_ne_znaet"])
        self.assertIn("prichina_kotoroy_sverka_ne_znaet", phrase)


if __name__ == "__main__":
    unittest.main()
