"""ADR-884 — вето СОДЕРЖИМОГО спрашивается у ТРЕТЬЕГО исхода переписи.

Батарея положительных контролей: каждый тест воспроизводит РЕАЛЬНОЕ состояние,
измеренное 31.10 на `origin/main` c9686b342, и краснеет, если мера вернётся к
нему. Проверка, никогда не видевшая настоящей поломки, — украшение
(`.claude/rules/deployment.md`, «Проверка сторожа сторожей»).

Контроль идёт в ОБЕ стороны, и это существенно: вето, проглотившее честное
«НЕ ИЗМЕРЕНО», купило бы зелень тишиной — ровно наоборот предмету класса
(инв. #17).

Время и личность процесса здесь не участвуют: мера читает ИСХОДНИКИ, часов и
pid не спрашивает, поэтому ни фиксированных дат, ни литеральных номеров в
батарее нет.
"""

import os
import unittest

from spa_core.monitoring import presence_as_observation_census as m

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))


def _outcomes(source: str, rel: str = "scene.py") -> set[str]:
    report = m.measure_module(source, rel=rel)
    assert "unmeasured" not in report, report
    return {site["outcome"] for site in report["sites"]}


def _with_old_behaviour(call):
    """Прогнать `call` так, будто вето задают ТОЛЬКО ярусу наблюдения.

    Дословное прежнее поведение (до ADR-884), а не ослепление двери целиком:
    дверь ОДНА на оба яруса, и слепая целиком она ломает ПЕРВОЕ по порядку
    звено драйвера, то есть отвечает про другую поломку.
    """
    original = m._verdict_stands_on_content

    def only_strongest_tier(present, test):
        if (m._match(m.branch_tokens(present), m._OBSERVATION_WORDS)
                or m._readiness_counters(present)):
            return original(present, test)
        return set()

    m._verdict_stands_on_content = only_strongest_tier
    try:
        return call()
    finally:
        m._verdict_stands_on_content = original


def _with_always_answering(call):
    """Прогнать `call` так, будто вето отвечает ВСЕГДА — на третьем исходе.

    Ярус наблюдения оставлен прежним по той же причине: контроль обязан
    ломать РОВНО одно звено и слышать, какое именно.
    """
    original = m._verdict_stands_on_content

    def always_on_the_third_outcome(present, test):
        if (m._match(m.branch_tokens(present), m._OBSERVATION_WORDS)
                or m._readiness_counters(present)):
            return original(present, test)
        return {"open"}

    m._verdict_stands_on_content = always_on_the_third_outcome
    try:
        return call()
    finally:
        m._verdict_stands_on_content = original


def _with_body_only_veto(call):
    """Прогнать `call` так, будто вето смотрит ТОЛЬКО тело ветки.

    Нужен, чтобы порвать РОВНО звено «чтение в УСЛОВИИ»: при полном ослеплении
    драйвер краснеет на предыдущем звене и отвечает про другую поломку.
    """
    original = m._verdict_stands_on_content

    def body_only(present, test):
        return m._called_names(present) & m._CONTENT_READERS

    m._verdict_stands_on_content = body_only
    try:
        return call()
    finally:
        m._verdict_stands_on_content = original


class ContentVetoReachesTheThirdOutcome(unittest.TestCase):
    """Ярус родового «прошло» спрашивает вето содержимого — обе формы."""

    def test_generic_pass_reading_content_in_the_body_is_vetoed(self):
        """Дословная форма `reporting_agent` / `allocator`: читает ТЕЛО ветки."""
        self.assertIn(m.CONTENT_CHECKED,
                      _outcomes(m.SCENE_GENERIC_ON_CONTENT))

    def test_generic_pass_reading_content_in_the_condition_is_vetoed(self):
        """Дословная форма `release_activation` / `release_state`.

        До ADR-884 вето не задавали вопроса ВОВСЕ; но даже заданное, оно
        обязано смотреть и в САМО УСЛОВИЕ — `if p.exists() and
        p.read_text() == sha` ставит вердикт на содержимом.
        """
        self.assertIn(m.CONTENT_CHECKED,
                      _outcomes(m.SCENE_GENERIC_IN_CONDITION))

    def test_the_veto_reads_the_condition_not_only_the_body(self):
        """Шов: убрав чтение из УСЛОВИЯ, место обязано вернуться в третий исход.

        Это контроль на то, что предыдущий тест проходит НЕ случайно (в сцене
        нет второго читателя содержимого в теле).
        """
        bare = m.SCENE_GENERIC_IN_CONDITION.replace(
            ' and (dest / ".release_sha").read_text().strip() == sha', "")
        self.assertNotIn('read_text', bare.split("if ")[1].split(":")[0])
        self.assertIn(m.PRESENCE_GENERIC_PASS, _outcomes(bare))


class TheThirdOutcomeSurvives(unittest.TestCase):
    """Обратная сторона: вето НЕ проглатывает честное «НЕ ИЗМЕРЕНО»."""

    def test_generic_pass_without_a_content_read_stays_the_third_outcome(self):
        self.assertEqual({m.PRESENCE_GENERIC_PASS},
                         _outcomes(m.SCENE_GENERIC_BARE))

    def test_a_content_read_without_any_verdict_stays_the_cost(self):
        """ЦЕНА меры не прячется под вето.

        Сослаться на вето там, где вердикта нет вовсе, значило бы заставить
        счётчик `content_checked` означать ДВЕ разные вещи.
        """
        self.assertEqual({m.NO_OBSERVATION_VERDICT},
                         _outcomes(m.SCENE_CONTENT_WITHOUT_VERDICT))

    def test_the_tautology_tier_is_not_moved(self):
        """Решение НЕ трогать ярус тавтологии закреплено, а не подразумевается.

        `presence_restated` — уже ОТВЕТ, а не незнание; перенос поменял бы один
        ответ на другой. Цена решения измерена и названа в ADR-884: 3 места из
        32 несут читателя содержимого, и их вето остаётся неиспользованным.
        """
        source = '''
import json, os
def check(path):
    if os.path.exists(path):
        payload = json.loads(open(path).read())
        return f"файл найден, записей {len(payload)}"
    return "файла нет"
'''
        self.assertEqual({m.PRESENCE_RESTATED}, _outcomes(source))


class ScenesStayGreenForTheOlderVetoes(unittest.TestCase):
    """Прежние пять сцен ADR-875…883 не сдвинуты правкой ADR-884."""

    def test_the_literal_adr_875_failure_is_still_a_finding(self):
        self.assertIn(m.PRESENCE_TO_OBSERVED, _outcomes(m.SCENE_DEFECT))

    def test_the_honest_refusal_is_still_not_a_finding(self):
        self.assertNotIn(m.PRESENCE_TO_OBSERVED, _outcomes(m.SCENE_HONEST))

    def test_the_loophole_is_still_a_finding(self):
        self.assertIn(m.PRESENCE_TO_OBSERVED, _outcomes(m.SCENE_LOOPHOLE))


class TheDriverNamesTheBrokenLink(unittest.TestCase):
    """Порвав РОВНО одно звено, драйвер обязан назвать ИМЕННО его.

    Без этого звена существующий тест краснел бы с верным вердиктом и неверным
    ИМЕНЕМ — урок порядка звеньев из ADR-883.
    """

    def test_all_nine_python_scenes_distinguish(self):
        drive = m.drive_both_directions()
        self.assertEqual(m.DRIVE_DISTINGUISHES, drive["kind"], drive)
        for label in ("generic_on_content", "generic_in_condition",
                      "generic_bare", "content_without_verdict"):
            self.assertIn(label, drive, drive)

    def test_all_shell_forms_distinguish(self):
        drive = m.drive_shell_both_directions()
        self.assertEqual(m.DRIVE_DISTINGUISHES, drive["kind"], drive)
        forms = {row["form"] for row in drive["forms"]}
        self.assertEqual({"if", "operator", "negated"}, forms, drive)
        scenes = {row["scene"] for row in drive["content_veto"]}
        self.assertIn("content_in_cond", scenes, drive)

    def test_restoring_the_old_behaviour_names_the_content_link(self):
        """ПРЕЖНЕЕ поведение — вето задают ТОЛЬКО самому сильному ярусу.

        Ослеплять дверь целиком нельзя: она ОДНА на оба яруса, и слепая мера
        краснит ПЕРВОЕ по порядку звено (`defect`), то есть отвечает про
        другую поломку. Поэтому контроль воспроизводит дефект ТОЧНО: ярус
        наблюдения спрашивает вето как прежде, третий исход — не спрашивает.
        """
        drive = _with_old_behaviour(m.drive_both_directions)
        self.assertEqual(m.DRIVE_BLIND, drive["kind"], drive)
        self.assertEqual("generic_on_content", drive["link"], drive)

    def test_blinding_the_shell_veto_door_names_the_shell_link(self):
        original = m._shell_verdict_stands_on_content
        m._shell_verdict_stands_on_content = lambda present, cond: False
        try:
            drive = m.drive_shell_both_directions()
        finally:
            m._shell_verdict_stands_on_content = original
        self.assertEqual(m.DRIVE_BLIND, drive["kind"], drive)
        self.assertEqual("shell_content_in_cond", drive["link"], drive)

    def test_the_condition_link_is_named_when_only_it_is_broken(self):
        """Звено `generic_in_condition` — НЕСУЩЕЕ, а не украшение.

        Вето, смотрящее только тело ветки, отвечает на сцене чтения в теле и
        молчит на сцене чтения в условии. Драйвер обязан назвать ИМЕННО второе
        звено: убери его из проверки — и форма `exists() and read_text()`
        вернулась бы в третий исход молча.
        """
        drive = _with_body_only_veto(m.drive_both_directions)
        self.assertEqual(m.DRIVE_BLIND, drive["kind"], drive)
        self.assertEqual("generic_in_condition", drive["link"], drive)

    def test_the_overreach_link_is_named_when_the_cost_scene_gets_a_verdict(self):
        """Звено `content_without_verdict` — НЕСУЩЕЕ.

        Ослеплением двери его не порвать: там, где вердикта нет вовсе, вето не
        спрашивают по построению. Поэтому звено проверяется подменой САМОЙ
        СЦЕНЫ на такую, которая вето ЗАСЛУЖИВАЕТ: драйвер обязан сказать, что
        ЦЕНА меры спряталась под вето, а не промолчать.
        """
        original = m.SCENE_CONTENT_WITHOUT_VERDICT
        m.SCENE_CONTENT_WITHOUT_VERDICT = m.SCENE_GENERIC_ON_CONTENT
        try:
            drive = m.drive_both_directions()
        finally:
            m.SCENE_CONTENT_WITHOUT_VERDICT = original
        self.assertEqual(m.DRIVE_BLIND, drive["kind"], drive)
        self.assertEqual("content_without_verdict", drive["link"], drive)

    def test_the_shell_third_outcome_link_is_named_when_the_veto_always_answers(self):
        """У оси оболочки звено «третий исход ЦЕЛ» тоже НЕСУЩЕЕ.

        Подменяется ТОЛЬКО путь третьего исхода: вето, отвечающее всем ярусам,
        порвало бы сперва сцены ТРЁХ ФОРМ, и драйвер ответил бы про другую
        поломку — та же причина, что у python-оси.
        """
        original = m._shell_verdict_stands_on_content

        def always_on_the_third_outcome(present_text, cond):
            if m._match(m._shell_tokens(present_text), m._OBSERVATION_WORDS):
                return original(present_text, cond)
            return True

        m._shell_verdict_stands_on_content = always_on_the_third_outcome
        try:
            drive = m.drive_shell_both_directions()
        finally:
            m._shell_verdict_stands_on_content = original
        self.assertEqual(m.DRIVE_BLIND, drive["kind"], drive)
        self.assertEqual("shell_content_in_cond_bare", drive["link"], drive)

    def test_a_veto_that_swallows_the_third_outcome_is_named_too(self):
        """Вето, отвечающее ВСЕГДА, краснит звено `generic_bare`.

        Обратное направление того же шва: мера, из которой третий исход исчез,
        обязана быть названа слепой, а не зелёной. Подменяется только путь
        третьего исхода — по той же причине, что в тесте выше.
        """
        drive = _with_always_answering(m.drive_both_directions)
        self.assertEqual(m.DRIVE_BLIND, drive["kind"], drive)
        self.assertEqual("generic_bare", drive["link"], drive)


class RealSourcesNotHandBuiltScenes(unittest.TestCase):
    """Замер на НАСТОЯЩИХ исходниках — сцена руками мерила бы свой словарь."""

    def _module(self, rel: str) -> dict:
        full = os.path.join(REPO_ROOT, rel)
        with open(full, encoding="utf-8") as handle:
            report = m.measure_module(handle.read(), rel=rel)
        self.assertNotIn("unmeasured", report, report)
        return report

    def test_release_activation_is_vetoed_by_content_in_the_condition(self):
        report = self._module("spa_core/studio_os/release_activation.py")
        sites = [s for s in report["sites"]
                 if s["function"] == "materialise_release"]
        self.assertTrue(sites, "предмет не найден — это НЕ «выполнено»")
        self.assertIn(m.CONTENT_CHECKED, {s["outcome"] for s in sites})

    def test_release_state_is_vetoed_by_content_in_the_condition(self):
        report = self._module("spa_core/studio_os/release_state.py")
        sites = [s for s in report["sites"]
                 if s["function"] == "active_from_process"]
        self.assertTrue(sites, "предмет не найден — это НЕ «выполнено»")
        self.assertIn(m.CONTENT_CHECKED, {s["outcome"] for s in sites})

    def test_card_instruction_lint_stays_in_the_third_outcome(self):
        """Девять мест остались, и это ОТВЕТ: мера про них правда не знает.

        Предмет лина — «есть ли такой путь в дереве», и `OK` там верный ответ;
        но объявлен критерий НЕ кодом ветки, поэтому исход честно третий.
        """
        report = self._module("spa_core/owner_queue/card_instruction_lint.py")
        sites = [s for s in report["sites"] if s["function"] == "resolve"]
        self.assertTrue(sites, "предмет не найден — это НЕ «выполнено»")
        self.assertIn(m.PRESENCE_GENERIC_PASS, {s["outcome"] for s in sites})


class TheProbeMeasuresTheOutcome(unittest.TestCase):
    """Проба приёмки карточки — зелена на целом контуре, красна на порванном."""

    def _probe(self):
        from spa_core.monitoring.card_acceptance import PROBES
        return PROBES["presence_census_asks_the_content_veto_of_the_third_outcome"]

    def test_probe_is_satisfied_on_the_whole_loop(self):
        status, detail = self._probe()(None)
        self.assertEqual("satisfied", status, detail)

    def test_probe_refuses_an_argument(self):
        status, detail = self._probe()("spa_core")
        self.assertEqual("unmeasured", status, detail)

    def test_probe_is_red_on_the_old_behaviour(self):
        probe = self._probe()
        status, detail = _with_old_behaviour(lambda: probe(None))
        self.assertEqual("not_satisfied", status, detail)
        self.assertIn("generic_on_content", detail)

    def test_probe_is_red_when_the_real_place_loses_its_kind(self):
        """Замер №2 (НАСТОЯЩИЙ исходник) — несущий, а не декорация.

        Сцены зелены, а место `materialise_release` рода лишилось: проба
        обязана ОТКАЗАТЬ. Сними этот замер — и «сцены работают» выдавалось бы
        за «настоящее место починено» (урок #944/#945).
        """
        probe = self._probe()
        original = m.measure_module

        def without_the_kind(source, *, rel):
            report = original(source, rel=rel)
            if rel.endswith("release_activation.py") and "sites" in report:
                report = {**report, "sites": [
                    {**site, "outcome": m.PRESENCE_GENERIC_PASS}
                    for site in report["sites"]]}
            return report

        m.measure_module = without_the_kind
        try:
            status, detail = probe(None)
        finally:
            m.measure_module = original
        self.assertEqual("not_satisfied", status, detail)
        self.assertIn("materialise_release", detail)

    def test_probe_is_red_when_the_third_outcome_list_is_empty(self):
        """Замер №3 («третий исход ЦЕЛ и НАЗВАН») — несущий.

        Перепись отдаёт пустой перечень: это тишина, а не ответ, и проба
        обязана ОТКАЗАТЬ.
        """
        probe = self._probe()
        original = m.measure

        def without_the_list(root=None, scope=None):
            report = (original(root, scope) if scope is not None
                      else original(root))
            return {**report, "generic_pass_sites": []}

        m.measure = without_the_list
        try:
            status, detail = probe(None)
        finally:
            m.measure = original
        self.assertEqual("not_satisfied", status, detail)
        self.assertIn("ПУСТ", detail)

    def test_probe_is_red_when_the_third_outcome_is_swallowed(self):
        probe = self._probe()
        status, detail = _with_always_answering(lambda: probe(None))
        self.assertEqual("not_satisfied", status, detail)
        self.assertIn("generic_bare", detail)


class OneDoorNotTwoCopies(unittest.TestCase):
    """Вето содержимого — ОДНА дверь на оба яруса (AST, не подстрока).

    Разойдись копии — ярус наблюдения и третий исход отвечали бы на один и тот
    же вопрос по-разному, и это была бы ровно та ошибка, что мера мерит.
    """

    def test_both_tiers_call_the_same_door(self):
        import ast
        src = open(os.path.join(
            REPO_ROOT, "spa_core/monitoring/presence_as_observation_census.py"),
            encoding="utf-8").read()
        tree = ast.parse(src)
        classify = next(n for n in ast.walk(tree)
                        if isinstance(n, ast.FunctionDef)
                        and n.name == "classify_site")
        called = {n.func.id for n in ast.walk(classify)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("_verdict_stands_on_content", called)
        inline = [n for n in ast.walk(classify)
                  if isinstance(n, ast.Name) and n.id == "_CONTENT_READERS"]
        self.assertEqual([], inline,
                         "словарь читателей используется В ОБХОД двери — "
                         "появилась вторая копия вето")


if __name__ == "__main__":
    unittest.main()
