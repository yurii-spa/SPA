"""ПОЛЯРНОСТЬ третьего исхода в переписи класса ADR-875 (ADR-883).

# LLM_FORBIDDEN

Предмет — не «есть ли вето», а РАЗЛИЧАЕТ ли мера две формы, которые в
исходнике выглядят почти одинаково:

* **авария ADR-875** — присутствие файла КУПИЛО утверждение о наблюдении;
* **эталон ADR-879** — присутствие дало ТРЕТИЙ ИСХОД («метка лежит, подписи
  нет — судить нечем», инв. #17), то есть не купило ничего.

Каждая сцена здесь — положительный контроль, и пары отличаются РОВНО
полярностью исхода. Условий у вето три, и у КАЖДОГО свой разрыв: контроль,
который не умеет порвать ровно одно звено, мерил бы собственный словарь, а не
проводку (урок циклов #944/#945).

Литеральных дат здесь нет вовсе: предмет меры — форма кода, а не календарь.
НАСТОЯЩЕЕ дерево батарея не обходит — читается ОДИН исходник
(`spa_core/golive/checklist.py`), ради которого вето и написано; обход 2500
модулей внутри модульного теста однажды уронил шард CI по SIGSEGV (замер #994,
прогон 41193530395), и платить им за ответ, которого он не даёт, значило бы
вернуть ту аварию.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", ".."))

from spa_core.monitoring import card_acceptance as ca              # noqa: E402
from spa_core.monitoring import presence_as_observation_census as c  # noqa: E402

PROBE = "presence_census_names_the_third_outcome"


def outcomes(source: str) -> set[str]:
    report = c.measure_module(source, rel="scene.py")
    assert "unmeasured" not in report, report
    return {site["outcome"] for site in report["sites"]}


#: Эталон ADR-879 в сжатой форме: присутствие метки ⇒ WARN «подписи нет».
#: Утверждение (PASS) зарабатывается ЧТЕНИЕМ содержимого, а WARN тем же кодом
#: назван и там, где судить нечем по другой причине.
THIRD_OUTCOME = '''
import json, os
PASS, WARN, PENDING = "PASS", "WARN", "PENDING"
def check(signed, mark):
    if os.path.exists(signed):
        record = json.loads(open(signed).read())
        if record.get("approved_by"):
            return {"name": "Wallet Ready", "status": PASS, "value": "approved"}
        return {"name": "Wallet Ready", "status": WARN, "value": "unmeasured"}
    if os.path.exists(mark):
        return {"name": "Wallet Ready", "status": WARN,
                "value": "mark_without_signature"}
    return {"name": "Wallet Ready", "status": PENDING, "value": "not_verified"}
'''

#: Дословная авария ADR-875: присутствие ⇒ «прочитано».
DEFECT = '''
import os
REPORT = "data/office_report.json"
def step():
    if os.path.exists(REPORT):
        return "прочитано: писатель был"
    return "НЕ ПРОЧИТАН"
'''


class PolarityOfTheVerdict(unittest.TestCase):
    """Пара сцен, отличающаяся РОВНО полярностью исхода."""

    def test_the_third_outcome_form_is_not_a_finding(self):
        """«Метка есть, подписи нет» — эталон инв. #17, а не находка."""
        got = outcomes(THIRD_OUTCOME)
        self.assertIn(c.VERDICT_IS_THIRD_OUTCOME, got)
        self.assertNotIn(c.PRESENCE_TO_OBSERVED, got)

    def test_the_adr875_defect_stays_a_finding(self):
        """Вторая сторона той же пары: ноль обязан быть ответом, не слепотой."""
        self.assertIn(c.PRESENCE_TO_OBSERVED, outcomes(DEFECT))

    def test_presence_buying_the_strongest_status_is_still_a_finding(self):
        """ЛАЗЕЙКА: рядом приписан вердикт с другим статусом — не выход.

        Здесь присутствие метки покупает САМЫЙ СИЛЬНЫЙ статус функции (`PASS`,
        «подтверждено»), а чтение содержимого зарабатывает слабый. Это дефект
        ADR-875, и вето обязано молчать: иначе из класса выходил бы любой, кто
        допишет соседний вердикт.
        """
        self.assertIn(c.PRESENCE_TO_OBSERVED, outcomes(c.SCENE_LOOPHOLE))


class EachConditionIsLoadBearing(unittest.TestCase):
    """Условий три, и БЕЗ КАЖДОГО вето обязано НЕ срабатывать."""

    def test_a_readiness_score_in_the_branch_defeats_the_veto(self):
        """Условие 1: ветка, НАЧИСЛИВШАЯ балл, купила утверждение."""
        got = outcomes('''
import json, os
PASS, WARN = "PASS", "WARN"
def check(signed, mark):
    score = 0
    if os.path.exists(signed):
        record = json.loads(open(signed).read())
        return {"status": PASS, "value": "approved"}
    if os.path.exists(mark):
        score += 2
        return {"name": "Wallet Ready", "status": WARN, "score": score}
    return {"status": WARN, "value": "не измерено"}
''')
        self.assertIn(c.PRESENCE_TO_OBSERVED, got)
        self.assertNotIn(c.VERDICT_IS_THIRD_OUTCOME, got)

    def test_without_a_content_earned_verdict_the_veto_does_not_fire(self):
        """Условие 2: утверждение функции тоже стоит на ПРИСУТСТВИИ.

        Тогда присутствие и есть единственный критерий всей функции — вето
        сняло бы с класса место, которое класс и описывает.
        """
        got = outcomes('''
import os
PASS, WARN = "PASS", "WARN"
def check(signed, mark):
    if os.path.exists(signed):
        return {"name": "Wallet Ready", "status": PASS, "value": "approved"}
    if os.path.exists(mark):
        return {"name": "Wallet Ready", "status": WARN, "value": "подписи нет"}
    return {"name": "Wallet Ready", "status": WARN, "value": "не измерено"}
''')
        self.assertIn(c.PRESENCE_TO_OBSERVED, got)
        self.assertNotIn(c.VERDICT_IS_THIRD_OUTCOME, got)

    def test_a_status_that_never_names_absence_does_not_earn_the_veto(self):
        """Условие 3: статус ветки нигде больше не говорит «судить нечем».

        Тот же статус обязан стоять у вердикта, который НАЗЫВАЕТ отсутствие, —
        иначе «WARN» здесь может быть утверждением функции, и мера этого не
        знает.
        """
        got = outcomes('''
import json, os
PASS, WARN, OTHER = "PASS", "WARN", "OTHER"
def check(signed, mark):
    if os.path.exists(signed):
        record = json.loads(open(signed).read())
        return {"name": "Wallet Ready", "status": PASS, "value": "approved"}
    if os.path.exists(mark):
        return {"name": "Wallet Ready", "status": WARN, "value": "одобрено"}
    return {"name": "Wallet Ready", "status": OTHER, "value": "не измерено"}
''')
        self.assertIn(c.PRESENCE_TO_OBSERVED, got)
        self.assertNotIn(c.VERDICT_IS_THIRD_OUTCOME, got)

    def test_a_branch_without_a_status_constant_is_never_vetoed(self):
        """Статуса-константы нет ⇒ сравнивать нечем, и вето молчит."""
        got = outcomes('''
import json, os
def check(signed, mark):
    if os.path.exists(signed):
        record = json.loads(open(signed).read())
        return {"status": "PASS", "value": "подтверждено"}
    if os.path.exists(mark):
        return {"status": "WARN", "value": "готов, подписи нет"}
    return {"status": "WARN", "value": "не измерено"}
''')
        self.assertIn(c.PRESENCE_TO_OBSERVED, got)
        self.assertNotIn(c.VERDICT_IS_THIRD_OUTCOME, got)


class TheRealPlace(unittest.TestCase):
    """Сцена руками мерила бы свой словарь — спрашивается НАСТОЯЩИЙ исходник."""

    def test_the_real_wallet_criterion_carries_the_third_outcome(self):
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
        rel = "spa_core/golive/checklist.py"
        with open(os.path.join(root, rel), encoding="utf-8") as handle:
            report = c.measure_module(handle.read(), rel=rel)
        self.assertNotIn("unmeasured", report, report)
        sites = [s for s in report["sites"]
                 if s["function"] == "check_wallet_ready"]
        self.assertTrue(sites, "предмет вето в исходнике не найден")
        kinds = {s["outcome"] for s in sites}
        self.assertIn(c.VERDICT_IS_THIRD_OUTCOME, kinds)
        self.assertNotIn(c.PRESENCE_TO_OBSERVED, kinds)

    def test_the_veto_carries_its_evidence_and_not_a_bare_word(self):
        """Вето обязано НАЗВАТЬ, чем обосновано: статус, где заработано, где отказ."""
        vetoed = [s for s in c.measure_module(THIRD_OUTCOME, rel="scene.py")["sites"]
                  if s["outcome"] == c.VERDICT_IS_THIRD_OUTCOME]
        self.assertEqual(1, len(vetoed), vetoed)
        third = vetoed[0]["third_outcome"]
        self.assertEqual(["WARN"], third["status"])
        self.assertEqual(["PASS"], third["earned_elsewhere"])
        self.assertTrue(third["earned_at"])
        self.assertTrue(third["same_status_names_absence_at"])


class TheVetoIsNamedNotSilent(unittest.TestCase):
    """Вето, о котором прибор молчит, и есть список исключений."""

    def _scene_root(self) -> str:
        import tempfile
        root = tempfile.mkdtemp(prefix="spa_third_outcome_")
        self.addCleanup(__import__("shutil").rmtree, root, True)
        area = os.path.join(root, "spa_core")
        os.makedirs(area)
        with open(os.path.join(area, "door.py"), "w", encoding="utf-8") as handle:
            handle.write(THIRD_OUTCOME)
        return root

    def test_the_report_lists_the_vetoed_site_by_name(self):
        report = c.measure(self._scene_root(), scope=("spa_core",))
        self.assertEqual("clean", report["verdict"])
        self.assertEqual(1, report["counts"][c.VERDICT_IS_THIRD_OUTCOME])
        named = [c.finding_key(s) for s in report["third_outcome_sites"]]
        self.assertEqual(1, len(named), named)
        self.assertIn("[check]", named[0])

    def test_render_prints_the_veto_and_never_a_bare_zero(self):
        lines = c.render(c.measure(self._scene_root(), scope=("spa_core",)))
        body = "\n".join(lines)
        self.assertIn("вето «вердикт ветки САМ есть третий исход»: 1", body)
        self.assertIn("spa_core/door.py", body)
        self.assertIn("САМ есть третий исход", body)

    def test_the_outcome_is_in_the_declared_dictionary(self):
        """Храповик сверяет род с СЛОВАРЁМ — новый род обязан в нём быть."""
        self.assertIn(c.VERDICT_IS_THIRD_OUTCOME, c.OUTCOMES)
        self.assertIn(c.VERDICT_IS_THIRD_OUTCOME, c.SHELL_OUTCOMES)


class DriveAxis(unittest.TestCase):
    """Положительный контроль САМОЙ меры: пять сцен, любое звено порвано ⇒ blind."""

    def test_the_drive_distinguishes_all_five_scenes(self):
        drive = c.drive_both_directions()
        self.assertEqual(c.DRIVE_DISTINGUISHES, drive["kind"], drive)
        self.assertIn(c.VERDICT_IS_THIRD_OUTCOME, drive["third_outcome"])
        self.assertIn(c.PRESENCE_TO_OBSERVED, drive["loophole"])

    def test_a_disabled_veto_is_reported_blind_on_the_third_outcome_link(self):
        """Вето снято ⇒ эталон снова числится находкой, и звено НАЗВАНО."""
        saved = c.verdict_is_third_outcome
        try:
            c.verdict_is_third_outcome = lambda *a, **k: None
            drive = c.drive_both_directions()
        finally:
            c.verdict_is_third_outcome = saved
        self.assertEqual(c.DRIVE_BLIND, drive["kind"], drive)
        self.assertEqual("third_outcome", drive["link"])

    def test_dropping_the_anti_loophole_condition_is_reported_blind(self):
        """Условие 3 снято ⇒ лазейка открыта, и blind приходит именно на неё.

        Рвётся РОВНО одно звено из трёх: предикат условия 3 подменяется
        всегда-истинным. Остальные два условия и все пять сцен — настоящие.
        """
        saved = c._verdicts_sharing_status_with_absence
        try:
            c._verdicts_sharing_status_with_absence = lambda others, status: list(others)
            drive = c.drive_both_directions()
        finally:
            c._verdicts_sharing_status_with_absence = saved
        self.assertEqual(c.DRIVE_BLIND, drive["kind"], drive)
        self.assertEqual("loophole", drive["link"])
        self.assertIn("лазейк", drive["reason"])


class AcceptanceProbe(unittest.TestCase):
    """Проба карточки: зелёная на целом контуре, красная на каждом звене."""

    def test_the_whole_circuit_is_satisfied(self):
        verdict, reason = ca.PROBES[PROBE](None)
        self.assertEqual(ca.SATISFIED, verdict, reason)

    def test_link_one_broken_a_blind_polarity_is_not_satisfied(self):
        saved = c.verdict_is_third_outcome
        try:
            c.verdict_is_third_outcome = lambda *a, **k: None
            verdict, reason = ca.PROBES[PROBE](None)
        finally:
            c.verdict_is_third_outcome = saved
        self.assertEqual(ca.NOT_SATISFIED, verdict, reason)
        self.assertIn("third_outcome", reason)

    def test_link_two_broken_the_real_place_losing_the_kind_is_not_satisfied(self):
        """Сцены зелены, а НАСТОЯЩЕЕ место рода не несёт ⇒ НЕ выполнено."""
        saved = c.measure_module

        def _blind(source, *, rel):
            report = saved(source, rel=rel)
            if rel.endswith("golive/checklist.py"):
                for site in report.get("sites", []):
                    if site["outcome"] == c.VERDICT_IS_THIRD_OUTCOME:
                        site["outcome"] = c.PRESENCE_TO_OBSERVED
            return report

        try:
            c.measure_module = _blind
            verdict, reason = ca.PROBES[PROBE](None)
        finally:
            c.measure_module = saved
        self.assertEqual(ca.NOT_SATISFIED, verdict, reason)
        self.assertIn("check_wallet_ready", reason)

    def test_link_three_broken_a_silent_veto_is_not_satisfied(self):
        """Вето сработало, но места не назвало ⇒ список исключений, НЕ выполнено."""
        saved = c.measure

        def _silent(*args, **kwargs):
            report = dict(saved(*args, **kwargs))
            report["third_outcome_sites"] = []
            return report

        try:
            c.measure = _silent
            verdict, reason = ca.PROBES[PROBE](None)
        finally:
            c.measure = saved
        self.assertEqual(ca.NOT_SATISFIED, verdict, reason)
        self.assertIn("НЕ НАЗВАНО", reason)

    def test_an_unreadable_source_is_unmeasured_not_satisfied(self):
        saved = ca.REPO_ROOT
        try:
            ca.REPO_ROOT = os.path.join(saved, "нет-такого-дерева")
            verdict, reason = ca.PROBES[PROBE](None)
        finally:
            ca.REPO_ROOT = saved
        self.assertEqual(ca.UNMEASURED, verdict, reason)
        self.assertIn("не прочитан", reason)

    def test_the_probe_refuses_an_argument(self):
        verdict, reason = ca.PROBES[PROBE]("spa_core/golive/checklist.py")
        self.assertEqual(ca.UNMEASURED, verdict, reason)

    def test_the_probe_is_registered_under_its_declared_name(self):
        self.assertIn(PROBE, ca.PROBES)


if __name__ == "__main__":
    unittest.main()
