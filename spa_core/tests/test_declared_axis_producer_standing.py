"""ОБЪЯВЛЕННАЯ ось судила сроки ОТСТАВНЫХ агентов (ADR-818).

Заказ **G817 п. 2** стоячего приказа владельца «Portfolio CIO» требовал ЗАМЕРИТЬ
население одного случая, «прежде чем решать, лечится ли оно правилом»:
со-производитель, объявленный не ``active``, получает ``None`` по построению, и
артефакт, объявленный за живым и отставным, имеет РОВНО ОДНОГО действительного
производителя.

**Ответ на букву заказа: население этого случая НОЛЬ** — замер 26.10 на живой
конституции (107 агентов, 231 пара «агент × артефакт» со сроком): артефактов,
объявленных и за живым, и за отставным, **0**. Это «измерено и равно нулю»
(инв. #17), а не «не нашли, потому что не смотрели».

**Тот же замер назвал ДРУГОЕ, и оно есть предмет этого файла.** Артефактов с
РОВНО ОДНИМ объявленным производителем, и тот отставной, — **девять**, и все
девять объявленная ось судила: ``curated_above_floor`` ×9, то есть УТВЕРЖДЕНИЕ
«этот агент срок держит» про агента, который не запускается вовсе. Девять пар
лежали внутри числа **225**, которое шаг 0-офис печатает как «срок не ниже пола»;
после правки 225 = **216 + 9**, и ни одно другое число прибора не двинулось.

**Правило не ново, ново его ИСПОЛНЕНИЕ — третий раз подряд этот класс.**
Соседняя ось (``slo_keepability.measure``) правило исполняет и объявляет дословно
в докстроке ``ACTIVE``: «``retired``/``designed`` такта не имеют по построению, и
судить их сроки значило бы печатать находку о том, чего нет». Объявленная ось
(ADR-816) обходит ``agents[]`` целиком и про ``intent`` не спрашивала НИЧЕГО.
У правила был один исполнитель из двух — у записки не было читателя.

**Находки сегодня НОЛЬ, и это не «по построению».** Ближайшая из девяти пар
(``com.spa.btc_nav`` × ``data/btc_paper_trading.json``) стои́т РОВНО на полу:
срок 26 ч при поле 26,0 ч. Один час в любую сторону — и ось напечатала бы
находку про агента, которого нет. «Ноль сегодня» здесь держится на часе запаса,
а не на устройстве прибора, и ровно поэтому лечится правилом, а не наблюдением.

Литеральных дат и стенных часов в предметной части НЕТ: предмет — чистые функции
«ярлык состояния · такт · срок → вердикт». Единственный литерал даты — `_ANCHOR`,
и он уходит прибору аргументом ``now=``.
"""
# FROZEN-DATE-OK: injected-clock — часы входом: единственный литерал даты здесь
# `_ANCHOR` (простое имя уровня модуля), и он передаётся `sk.measure(..., now=)`;
# отметки прогонов в стенде ВЫЧИСЛЯЮТСЯ от него, своих литералов не имеют.
from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import slo_keepability as sk
from spa_core.monitoring import slo_proposal as sp

_ANCHOR = dt.datetime(2026, 10, 26, 9, 0, 0, tzinfo=dt.timezone.utc)

#: ИЗМЕРЕННЫЕ 26.10 числа живой конституции — чтобы сцена была воспроизведением
#: аварии, а не выдумкой (`.claude/rules/deployment.md`, «проверка сторожа сторожей»).
_RETIRED_PAIRS = 9              # пар «отставной агент × артефакт со сроком»
_ABOVE_BEFORE = 225             # `curated_above_floor` до правки
_ABOVE_AFTER = 216              # после: 216 + 9 = 225, ни одна пара не потеряна
_ON_THE_FLOOR_SLO = 26          # срок ближайшей из девяти пар
_ON_THE_FLOOR_SCHEDULE = "calendar:08:40"   # её расписание ⇒ пол ровно 26,0 ч
_MIXED_LIVE_AND_RETIRED = 0     # население случая, о котором спрашивал заказ G817 п. 2

_DAILY = "calendar:08:00"
_SLO_ABOVE_FLOOR = 48.0         # заведомо выше пола суточного агента (26 ч)
_SLO_BELOW_FLOOR = 15.0         # заведомо ниже него — поагентно вышла бы находка
_MEDIAN = 12.0


class TheDoorHasThreeOutcomes(unittest.TestCase):
    """`producer_standing` — идёт ли агент вообще. Три исхода (инв. #17)."""

    def test_an_active_agent_has_a_cadence(self):
        runs, why = sp.producer_standing(sp.PRODUCER_ACTIVE)
        self.assertIs(runs, True, why)

    def test_a_retired_agent_has_none_and_the_label_is_named(self):
        runs, why = sp.producer_standing("retired")
        self.assertIs(runs, False, why)
        self.assertIn("retired", why, "ярлык состояния обязан быть НАЗВАН в причине")

    def test_every_non_active_label_is_refused_not_only_the_two_known_ones(self):
        """`paused` — живой ярлык конституции, и он НЕ в паре retired/designed.

        Прежняя редакция `measure` знала ровно два ярлыка и всё остальное
        называла `intent_absent`. Правило же здесь одно: «не active ⇒ такта нет»,
        и оно обязано действовать на ЛЮБОЙ ярлык, а не на перечисленные.
        """
        for label in ("retired", "designed", "paused", "planned", "disabled"):
            with self.subTest(label=label):
                runs, why = sp.producer_standing(label)
                self.assertIs(runs, False, why)

    def test_an_unreadable_label_is_the_third_outcome_not_an_assumed_one(self):
        """Молчащий ярлык одинаково похож на «забыли» и на «вывели».

        ВНИМАНИЕ: утверждение под ``subTest`` мутациям по дельте НЕВИДИМО
        (урок ADR-761) — носители ниже отдельными тестами.
        """
        for form in (None, "", 0, 1, True, [], {}, 3.5):
            with self.subTest(form=form):
                runs, why = sp.producer_standing(form)
                self.assertIsNone(runs, why)
                self.assertTrue(why.strip(), "третий исход обязан назвать причину")

    def test_a_missing_label_is_unmeasured(self):
        """Носитель п. 1 предыдущего теста — видимый мутациям."""
        self.assertIsNone(sp.producer_standing(None)[0])

    def test_an_empty_label_is_unmeasured(self):
        """Носитель п. 2: пустая строка — это строка, и подстановка «идёт» тут
        была бы ровно тем угадыванием, против которого дверь написана."""
        self.assertIsNone(sp.producer_standing("")[0])

    def test_a_boolean_label_is_unmeasured(self):
        """Носитель п. 3: `True` в Python есть `int`, и проверка на тип без
        отсечения `bool` пропустила бы его как число."""
        self.assertIsNone(sp.producer_standing(True)[0])


class TheDoorIsSymmetricUnlikeCoProductionStanding(unittest.TestCase):
    """Отличие от ADR-816, и оно ПРЕДМЕТ, а не оттенок.

    Правомочие со-производства нужно было только ОТРИЦАНИЮ: «этот агент ОДИН
    способен держать срок» для файла достаточно. Здесь же не обосновано НИ ОДНО
    утверждение любого знака: у отставного агента нет такта, значит нет и пола, и
    «держит» беспредметно ровно так же, как «не держит».
    """

    def test_a_retired_agent_gets_no_positive_verdict_either(self):
        axis, note = sp.audit_declared(_SLO_ABOVE_FLOOR, _DAILY, _MEDIAN, 1,
                                       intent="retired")
        self.assertEqual(axis, sp.DECLARED_PRODUCER_NOT_RUNNING, note)
        self.assertNotEqual(axis, sp.CURATED_ABOVE,
                            "«срок держит» про агента, которого не запускают")

    def test_the_very_same_scene_with_an_active_agent_answers_the_opposite(self):
        """Обратная сторона на ТЕХ ЖЕ входах: сцена, дающая один ответ обеими
        ветками, не различает ничего (урок ADR-817, «выжил 1»)."""
        axis, note = sp.audit_declared(_SLO_ABOVE_FLOOR, _DAILY, _MEDIAN, 1,
                                       intent=sp.PRODUCER_ACTIVE)
        self.assertEqual(axis, sp.CURATED_ABOVE, note)

    def test_a_retired_agent_gets_no_finding_either(self):
        axis, note = sp.audit_declared(_SLO_BELOW_FLOOR, _DAILY, _MEDIAN, 1,
                                       intent="retired")
        self.assertEqual(axis, sp.DECLARED_PRODUCER_NOT_RUNNING, note)
        self.assertNotIn(axis, (sp.CURATED_BELOW, sp.CURATED_MARGIN_ONLY),
                         "находка о том, чего нет")

    def test_the_same_scene_with_an_active_agent_does_give_a_finding(self):
        """Положительный контроль симметрии с другой стороны: находка на тех же
        входах ЖИВА, значит правка не глушит сторожа (инв. #16)."""
        axis, note = sp.audit_declared(_SLO_BELOW_FLOOR, _DAILY, _MEDIAN, 1,
                                       intent=sp.PRODUCER_ACTIVE)
        self.assertIn(axis, (sp.CURATED_BELOW, sp.CURATED_MARGIN_ONLY), note)

    def test_the_abstention_names_the_label_and_the_deadline(self):
        _, note = sp.audit_declared(_SLO_BELOW_FLOOR, _DAILY, _MEDIAN, 1,
                                    intent="retired")
        self.assertIn("retired", note, "не назван ярлык состояния")
        self.assertIn("15", note, "не назван срок, о котором шла речь")
        self.assertIn("НЕ О ЧЕМ", note, "не сказано, что судить нечего")


class TheQuestionIsAskedFirstAndThatIsTheSubject(unittest.TestCase):
    """Порядок вопросов — предмет, а не стиль (тот же урок, что в ADR-816).

    У отставного агента нет такта ⇒ пол считать не из чего ⇒ и сравнение, и
    правомочие со-производства теряют предмет РАНЬШЕ, чем их задают.
    """

    def test_an_unparsable_schedule_does_not_mask_the_retirement(self):
        """Иначе пара ушла бы в `CURATED_UNMEASURED` — «различить нечем» вместо
        «судить не о чем», то есть в другой, неверный третий исход."""
        axis, note = sp.audit_declared(_SLO_BELOW_FLOOR, "по понедельникам",
                                       _MEDIAN, 1, intent="retired")
        self.assertEqual(axis, sp.DECLARED_PRODUCER_NOT_RUNNING, note)

    def test_the_same_unparsable_schedule_on_an_active_agent_is_the_floors_outcome(self):
        axis, note = sp.audit_declared(_SLO_BELOW_FLOOR, "по понедельникам",
                                       _MEDIAN, 1, intent=sp.PRODUCER_ACTIVE)
        self.assertEqual(axis, sp.CURATED_UNMEASURED, note)

    def test_co_production_does_not_mask_the_retirement(self):
        axis, note = sp.audit_declared(_SLO_BELOW_FLOOR, _DAILY, _MEDIAN, 2,
                                       intent="retired")
        self.assertEqual(axis, sp.DECLARED_PRODUCER_NOT_RUNNING, note)

    def test_the_same_co_production_on_an_active_agent_abstains_for_its_own_reason(self):
        axis, note = sp.audit_declared(_SLO_BELOW_FLOOR, _DAILY, _MEDIAN, 2,
                                       intent=sp.PRODUCER_ACTIVE)
        self.assertEqual(axis, sp.DECLARED_CO_PRODUCED, note)

    def test_an_unmeasured_label_also_precedes_an_unmeasured_standing(self):
        """Два третьих исхода РАЗНЫЕ и лечатся разным: «ярлык не прочитан»
        против «производителей не посчитали»."""
        axis, note = sp.audit_declared(_SLO_BELOW_FLOOR, _DAILY, _MEDIAN, None,
                                       intent=None)
        self.assertEqual(axis, sp.DECLARED_PRODUCER_STANDING_UNMEASURED, note)
        self.assertNotEqual(axis, sp.DECLARED_STANDING_UNMEASURED)


class IntentIsRequiredNotDefaulted(unittest.TestCase):
    """Умолчание вернуло бы дефект ТИХО, у первого же нового читателя.

    Это контроль ДВЕРИ, а не «одного определения» (заказ G814 п. 3): проверяется
    движение через дверь — вызов без ярлыка обязан не состояться.
    """

    def test_calling_without_an_intent_fails_loudly(self):
        with self.assertRaises(TypeError):
            sp.audit_declared(_SLO_BELOW_FLOOR, _DAILY, _MEDIAN, 1)

    def test_the_intent_cannot_be_passed_positionally_by_accident(self):
        """Именованный-только: иначе ярлык состояния встал бы пятым позиционным
        рядом со счётом производителей, и перепутать их стало бы делом опечатки."""
        with self.assertRaises(TypeError):
            sp.audit_declared(_SLO_BELOW_FLOOR, _DAILY, _MEDIAN, 1, "retired")

    def test_one_literal_for_the_running_label(self):
        """У соседней оси своей копии литерала больше нет — мерится ПО ИСТОЧНИКУ.

        **Этот контроль переписан после того, как мутация его ПЕРЕЖИЛА**, и
        переживание было поучительнее самой правки. Первая редакция утверждала
        ``assertIs(sk.ACTIVE, sp.PRODUCER_ACTIVE)``, и притязание было ВЕРНО — но
        CPython ИНТЕРНИРУЕТ короткие строковые литералы, поэтому при возвращённой
        копии ``ACTIVE = "active"`` тождество остаётся ИСТИННЫМ, и тест не
        различал ничего. Тот же урок, что ADR-817 записал про сцену, дающую один
        ответ обеими ветками: **верное притязание в тесте не есть работающий
        контроль, и прозой одно от другого не отличить.**

        Предмет здесь — ФОРМА объявления, а не значение, поэтому и мерится
        AST-ом: правая часть обязана быть обращением к чужому имени
        (``slo_proposal.PRODUCER_ACTIVE``), а не литералом. Значение сверяется
        рядом — одно без другого ничего не доказывает.
        """
        import ast
        tree = ast.parse(Path(sk.__file__).read_text())
        found = [node.value for node in tree.body
                 if isinstance(node, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "ACTIVE"
                         for t in node.targets)]
        self.assertEqual(len(found), 1,
                         "у `ACTIVE` обязано быть РОВНО одно объявление уровня модуля")
        self.assertIsInstance(
            found[0], ast.Attribute,
            "`ACTIVE` объявлен ЛИТЕРАЛОМ — копия правила вернулась; "
            "тождество этого не покажет, короткие строки интернируются")
        self.assertEqual(found[0].attr, "PRODUCER_ACTIVE")
        self.assertEqual(sk.ACTIVE, sp.PRODUCER_ACTIVE)


class _Stand:
    """Одноразовый стенд: конституция + обёртки + записи прогонов.

    Отметки ВЫЧИСЛЯЮТСЯ от впрыснутого `_ANCHOR`, своих литералов не имеют.
    """

    _WRAPPER = '#!/bin/bash\nAGENT_NAME="{name}"\nexec python3 -m spa_core.x\n'

    def __init__(self, tmp: Path):
        self.root = tmp
        for sub in ("architecture", "scripts", "logs"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        self.agents: list = []

    def agent(self, label, produces, *, intent="active", schedule="calendar:08:00"):
        short = label.split(".")[-1]
        (self.root / "scripts" / f"agent_{short}.sh").write_text(
            self._WRAPPER.format(name=short))
        self.agents.append({"label": label, "intent": intent, "schedule": schedule,
                            "program": f"agent_{short}.sh",
                            "produces": [{"artifact": a, "slo_hours": s}
                                         for a, s in produces]})
        return short

    def ballast(self):
        """Живой агент, чтобы у вопроса было население.

        `measure` отказывает (`Unmeasured`), когда ни одного артефакта со сроком
        не осталось, — и отказывает ВЕРНО. Сцена из одних отставных агентов
        проверяла бы этот отказ, а не предмет файла, поэтому балласт объявлен
        ЯВНО и его артефакт в утверждениях назван по имени.
        """
        self.agent("com.spa.ballast", [("data/ballast.json", _SLO_ABOVE_FLOOR)])
        self.runs("ballast", (0, 24, 48))
        return "data/ballast.json"

    def runs(self, short, hours_ago):
        text = ""
        for h in sorted(hours_ago, reverse=True):
            at = _ANCHOR - dt.timedelta(hours=h)
            stamp = at.strftime("%Y-%m-%dT%H:%M:%SZ")
            text += (f"[{stamp}] START agent={short} pid=1\n"
                     f"[{stamp}]   exec: python3 -m spa_core.x\n")
        (self.root / "logs" / f"spa_{short}.log").write_text(text)

    def measure(self):
        target = self.root / "architecture" / "manifest.json"
        target.write_text(json.dumps({"agents": self.agents, "artifacts": []},
                                     ensure_ascii=False))
        return sk.measure(target, log_dir=self.root / "logs",
                          scripts_dir=self.root / "scripts", now=_ANCHOR)


class TheCensusKeepsTheTwoAbstentionsApart(unittest.TestCase):
    """Пара отставного агента НЕ попадает в население вопроса ADR-817.

    `abstained` есть население вопроса «существует ли объявленное
    со-производство в действительности». Пара отставного агента в нём стала бы
    вопросом, которого никто не задавал: со-производства у неё нет по построению.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.stand = _Stand(Path(self._tmp.name))
        self.addCleanup(self._tmp.cleanup)

    def _scene(self):
        """Живой со-производимый артефакт + отставной одиночка. Сцена отвечает
        РАЗНОЕ по двум перечням — иначе она не различала бы ничего."""
        self.stand.agent("com.spa.morning", [("data/shared.json", _SLO_BELOW_FLOOR)],
                         schedule="calendar:08:00")
        self.stand.agent("com.spa.evening", [("data/shared.json", _SLO_BELOW_FLOOR)],
                         schedule="calendar:20:00")
        self.stand.agent("com.spa.gone", [("data/orphan.json", _SLO_BELOW_FLOOR)],
                         intent="retired", schedule=_ON_THE_FLOOR_SCHEDULE)
        return self.stand.measure()["declared_axis"]

    def test_the_retired_pair_lands_in_its_own_list(self):
        axis = self._scene()
        self.assertEqual([(r["agent"], r["artifact"]) for r in axis["not_running"]],
                         [("com.spa.gone", "data/orphan.json")])

    def test_the_retired_pair_is_absent_from_the_co_production_population(self):
        axis = self._scene()
        self.assertNotIn("com.spa.gone",
                         {r["agent"] for r in axis["abstained"]},
                         "пара отставного агента попала в население ADR-817")

    def test_the_co_produced_pairs_still_abstain_for_their_own_reason(self):
        """Положительный контроль обратной стороны: население ADR-817 на месте."""
        axis = self._scene()
        self.assertEqual(len(axis["abstained"]), 2)
        for row in axis["abstained"]:
            self.assertEqual(row["declared_vs_floor"], sp.DECLARED_CO_PRODUCED)

    def test_the_retired_pair_is_not_a_finding(self):
        axis = self._scene()
        self.assertNotIn("com.spa.gone", {r["agent"] for r in axis["findings"]})

    def test_the_pair_is_named_not_merely_counted(self):
        """Пара, просто исчезнувшая из отчёта, неотличима от пары, которой не
        было, — то же требование, что ADR-816 предъявил воздержаниям."""
        row = self._scene()["not_running"][0]
        self.assertEqual(row["intent"], "retired")
        self.assertTrue(row["note"].strip())
        self.assertIn("retired", row["note"])

    def test_nothing_is_lost_from_the_population(self):
        """Сумма разрядов обязана сходиться с населением: девять пар ПЕРЕШЛИ из
        «срок не ниже пола» в названное воздержание, а не исчезли."""
        axis = self._scene()
        self.assertEqual(sum(axis["tally"].values()), axis["population"])

    def test_an_active_agent_in_the_same_slot_is_judged(self):
        """Та же сцена, но одиночка ИДЁТ — и ось про него отвечает.

        Без этого контроля проверки выше зеленели бы и у прибора, который молчит
        про ВСЕХ. Прогоны агенту даны намеренно: без наблюдённой медианы отрицание
        не делится на два состояния и пара уходит в `CURATED_UNMEASURED` — тоже
        «не находка», то есть сцена не различала бы предмет.
        """
        short = self.stand.agent(
            "com.spa.here", [("data/orphan.json", _SLO_BELOW_FLOOR)],
            intent="active", schedule=_ON_THE_FLOOR_SCHEDULE)
        self.stand.runs(short, (0, 40, 80))
        axis = self.stand.measure()["declared_axis"]
        self.assertEqual(axis["not_running"], [])
        self.assertEqual([(r["agent"], r["artifact"]) for r in axis["findings"]],
                         [("com.spa.here", "data/orphan.json")])


class BothAxesAskTheSameDoor(unittest.TestCase):
    """Правило жило в двух копиях: одна исполнялась, второй не было вовсе."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.stand = _Stand(Path(self._tmp.name))
        self.addCleanup(self._tmp.cleanup)

    def test_the_observed_axis_still_excludes_the_retired_agent(self):
        """Поведение соседней оси правкой НЕ двинуто — она и прежде исключала."""
        alive = self.stand.ballast()
        self.stand.agent("com.spa.gone", [("data/orphan.json", _SLO_BELOW_FLOOR)],
                         intent="retired")
        doc = self.stand.measure()
        self.assertEqual([r["artifact"] for r in doc["rows"]], [alive])
        self.assertEqual(doc["excluded_by_intent"].get("retired"), 1)

    def test_a_paused_agent_is_reported_under_its_own_label(self):
        """Прежде `paused` докладывался как `intent_absent` — «состояние не
        объявлено» про агента, чьё состояние объявлено дословно. Население этого
        случая на живой конституции НОЛЬ (пар со сроком у `paused`-агента нет),
        поэтому ни одно число замера правкой не двинулось."""
        self.stand.ballast()
        self.stand.agent("com.spa.held", [("data/held.json", _SLO_BELOW_FLOOR)],
                         intent="paused")
        doc = self.stand.measure()
        self.assertEqual(doc["excluded_by_intent"].get("paused"), 1)
        # Ведро «не прочитан» ОСТАЁТСЯ и честно показывает НОЛЬ: исчезни оно,
        # «такого не было» стало бы неотличимо от «не считали» (инв. #17).
        self.assertEqual(doc["excluded_by_intent"].get("intent_absent"), 0)

    def test_an_unreadable_label_still_goes_to_the_unmeasured_bucket(self):
        """Обратная сторона: ведро `intent_absent` не исчезло, оно сузилось до
        своего настоящего предмета."""
        self.stand.ballast()
        self.stand.agent("com.spa.mute", [("data/mute.json", _SLO_BELOW_FLOOR)],
                         intent=None)
        doc = self.stand.measure()
        self.assertEqual(doc["excluded_by_intent"].get("intent_absent"), 1)


class TheNumberHasAReader(unittest.TestCase):
    """Находка без читателя — класс, который этот приказ закрывает уже восьмой
    цикл подряд. Число обязано доходить до шага 0-офис."""

    def test_the_office_line_reports_the_not_running_count(self):
        line = sk.declared_axis_line({"declared_axis": {
            "population": 231, "tally": {sp.CURATED_ABOVE: _ABOVE_AFTER},
            "findings": [], "abstained": [{}] * 4,
            "not_running": [{}] * _RETIRED_PAIRS}})
        self.assertIn(str(_RETIRED_PAIRS), line)
        self.assertIn("НЕ ИДЁТ", line)
        self.assertIn(str(_ABOVE_AFTER), line)

    def test_a_missing_key_is_not_printed_as_zero(self):
        """Прибор СТАРОЙ версии и прибор без населения обязаны быть различимы."""
        line = sk.declared_axis_line({"declared_axis": {
            "population": 231, "tally": {sp.CURATED_ABOVE: _ABOVE_AFTER},
            "findings": [], "abstained": []}})
        self.assertIn("НЕ ИДЁТ НЕ ИЗМЕРЕНО", line)
        self.assertNotIn("НЕ ИДЁТ 0", line)

    def test_an_empty_population_is_printed_as_a_measured_zero(self):
        """Обратная сторона: ноль ЕСТЬ наблюдение, и прятать его нельзя."""
        line = sk.declared_axis_line({"declared_axis": {
            "population": 231, "tally": {sp.CURATED_ABOVE: _ABOVE_BEFORE},
            "findings": [], "abstained": [], "not_running": []}})
        self.assertIn("НЕ ИДЁТ 0", line)


class TheMeasuredArithmeticOfTheLiveConstitution(unittest.TestCase):
    """Числа замера 26.10 — ЗАПИСЬ, а не украшение: по ним следующий цикл
    отличит «правка на месте» от «прибор переписан»."""

    def test_the_nine_pairs_came_out_of_the_reassurance_number(self):
        self.assertEqual(_ABOVE_AFTER + _RETIRED_PAIRS, _ABOVE_BEFORE,
                         "девять пар обязаны ПЕРЕЙТИ, а не исчезнуть")

    def test_the_case_the_order_asked_about_has_zero_population(self):
        """Заказ G817 п. 2: артефакт за живым И отставным. Ноль ИЗМЕРЕН."""
        self.assertEqual(_MIXED_LIVE_AND_RETIRED, 0)

    def test_the_nearest_pair_sits_exactly_on_the_floor(self):
        """«Находок ноль сегодня» держится на ЧАСЕ запаса, а не на построении —
        поэтому класс лечится правилом, а не наблюдением."""
        floor, why = sp.architect_floor(_ON_THE_FLOOR_SCHEDULE)
        self.assertEqual(floor, float(_ON_THE_FLOOR_SLO), why)
        below, why_cmp = sp.below_floor(_ON_THE_FLOOR_SLO, floor)
        self.assertIs(below, False, why_cmp)
        self.assertIs(sp.below_floor(_ON_THE_FLOOR_SLO - 1, floor)[0], True,
                      "один час в другую сторону — и это была бы НАХОДКА")


if __name__ == "__main__":
    unittest.main()
