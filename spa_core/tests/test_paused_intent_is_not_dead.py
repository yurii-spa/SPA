"""Объявление агента обязано уметь сказать «намеренно выключен владельцем» (ADR-769).

Positive control — настоящая авария, а не придуманная: с 2026-09-30 по 2026-10-16
(46 суток) сторож `architecture_conformance` печатал

    [CRITICAL] com.spa.mission_tick: intent=active, но НЕ загружен во флоте

и находка была ВЕРНА — объявление и реальность действительно расходились. Неверна
была единственная резолюция, закрывающая её: «загрузить агента во флот». Агента
выключил САМ ВЛАДЕЛЕЦ, намеренно и устойчиво к перезагрузке (`launchctl bootout` +
`launchctl disable`, 30.09, канон `architecture/memory_truth.json`), так что
«починка» отменила бы его решение, прикрываясь закрытием CRITICAL. Запись манифеста
при этом противоречила сама себе: `"intent": "active"` рядом с прозой
`"notes": "...paused by the owner..."` — проза говорила правду, поле врало, сторож
читал поле.

У намерения было ТРИ значения (`active` · `retired` · `designed`/`unresolved`), и ни
одно не выражало «намеренно выключен»: `retired` значит «убран навсегда». Это ровно
форма инварианта #17 — три состояния обязаны быть РАЗЛИЧИМЫ:

  должен работать и не работает      ⇒ CRITICAL (как было);
  убран навсегда                     ⇒ во флоте не ждём;
  намеренно выключен владельцем      ⇒ отсутствие во флоте ЕСТЬ заданное состояние,
                                       а находкой становится ОБРАТНОЕ.

Каждый тест ниже — одно звено, и у каждого звена есть обратная сторона с НАЗВАННЫМ
звеном (`.claude/rules/acceptance.md` п. 3). Сторона «четвёртое значение не роняет счёт
флота молча» живёт в `test_typed_fleet_counts.py`: `company_truth` вправе ввозить только
`mission_control` и ПОИМЕНОВАННЫЙ список тестов (ADR-580 §1 правило 3, храповик
`test_company_truth_import_ratchet`), и расширять этот список ради удобства одного файла
значило бы ослабить правило архитектуры. Освобождение, которое резало бы только в
одну сторону, было бы не четвёртым значением, а способом выключить сторожа (инв. #16),
поэтому `paused` проверяется ЗАМЕРОМ (`launchctl print-disabled` — та же дверь, на
которую ссылается канон), а не одним объявлением.

Дверь к ОС — ВХОД (`disabled_labels=`), а не окружение: `.claude/rules/deployment.md`
(«все ли двери к ОС закрыты для того пути, который идёт тест»). Часы тоже вход.
"""
from __future__ import annotations

import datetime as dt
import unittest

from spa_core.monitoring import architecture_conformance as ac

NOW = dt.datetime(2030, 1, 15, 12, 0, tzinfo=dt.timezone.utc)  # FROZEN-DATE-OK: injected-clock — часы передаются аргументом now=, отметок-якорей в сцене нет

LABEL = "com.spa.mission_tick"


def agent(label, intent="active", reboot_safe=True):
    return {"label": label, "intent": intent, "reboot_safe": reboot_safe,
            "plist_source": "launch_agents" if reboot_safe else "repo:launchd/x.plist",
            "schedule": "interval:900s", "program": "x.sh", "layer": "product",
            "role": "other", "produces": [], "consumes": [],
            "consumer_required": False, "governed_by": [], "curation": "none",
            "notes": ""}


def b1(manifest, fleet, disabled):
    """Только вердикты B1 и только строки `unchecked` про B1 — остальные проверки
    этого сторожа к предмету не относятся и шумели бы в обе стороны.

    Возвращается ПАРА «ключ + severity», а не один ключ: замер мутациями по дельте
    показал, что ключа мало — понижение `CRITICAL` до `INFO` оставляет находку на
    месте и МОЛЧА лишает её силы, и утверждение про один ключ такую правку пережило.
    """
    rep = ac.run_checks(manifest, fleet, lambda p: None, {}, NOW,
                        disabled_labels=disabled)
    return ({(f["key"], f["severity"]) for f in rep["findings"] if f["check"] == "B1"},
            {u["check"] for u in rep["unchecked"] if str(u.get("check")).startswith("B1")})


def man(*agents):
    return {"schema_version": 1, "agents": list(agents), "artifacts": [],
            "designed_architectures": []}


class PausedAgentIsNotDead(unittest.TestCase):
    """Сама авария и её обратная сторона."""

    def test_paused_and_absent_with_the_pause_measured_is_not_a_finding(self):
        """ТА САМАЯ авария: 46 суток CRITICAL, чьё закрытие отменило бы решение владельца."""
        found, unchecked = b1(man(agent(LABEL, intent="paused")),
                              fleet=set(), disabled=frozenset({LABEL}))
        self.assertEqual(found, set(), "пауза, подтверждённая замером, находкой не является")
        self.assertEqual(unchecked, set(), "и «не измерено» тут тоже неуместно")

    def test_same_agent_declared_active_is_still_critical(self):
        """ОБРАТНАЯ СТОРОНА звена «ярлык»: ослабления не было — `active` краснеет как прежде.

        Порвано ровно одно звено: значение `intent`. Всё остальное в сцене то же.
        """
        found, _ = b1(man(agent(LABEL, intent="active")),
                      fleet=set(), disabled=frozenset({LABEL}))
        self.assertEqual(found, {(f"B1:dead:{LABEL}", "CRITICAL")},
                         "агент, который ДОЛЖЕН работать и не работает, — по-прежнему CRITICAL")

    def test_paused_but_loaded_is_critical(self):
        """ОБРАТНАЯ СТОРОНА звена «направление»: агента оживили против решения владельца.

        Освобождение обязано резать в обе стороны, иначе `paused` есть глушилка.
        """
        found, _ = b1(man(agent(LABEL, intent="paused")),
                      fleet={LABEL}, disabled=frozenset({LABEL}))
        self.assertEqual(found, {(f"B1:revived:{LABEL}", "CRITICAL")})

    def test_paused_claim_refuted_by_the_measurement_is_critical(self):
        """ОБРАТНАЯ СТОРОНА звена «замер»: объявили паузу, а ОС её не подтверждает.

        Порвано одно звено: метки нет в `launchctl print-disabled`. Без этой ветки
        достаточно было бы ВПИСАТЬ `paused`, чтобы любой настоящий отказ замолчал.
        """
        found, _ = b1(man(agent(LABEL, intent="paused")),
                      fleet=set(), disabled=frozenset())
        self.assertEqual(found, {(f"B1:pause_unproven:{LABEL}", "CRITICAL")})

    def test_pause_not_measured_keeps_the_finding_and_says_so(self):
        """ТРЕТИЙ ИСХОД (инв. #17): дверь к ОС не прочитана.

        «Не измерено» не выдаётся ни за «пауза подтверждена», ни за «паузы нет»:
        освобождение не выдаётся по непроверенному притязанию (fail-CLOSED — та же
        сторона, что у `agent_health_monitor.launchd_disabled_labels`), и причина
        НАЗВАНА отдельной строкой, а не молчанием.
        """
        found, unchecked = b1(man(agent(LABEL, intent="paused")),
                              fleet=set(), disabled=None)
        self.assertEqual(found, {(f"B1:dead:{LABEL}", "CRITICAL")})
        self.assertEqual(unchecked, {"B1_paused"})

    def test_unmeasured_door_is_silent_when_nobody_claims_a_pause(self):
        """ОБРАТНАЯ СТОРОНА предыдущего: строка «не измерено» появляется по ПРЕДМЕТУ.

        Нечитаемый список отключённых не о чем, если ни один агент паузы не объявлял, —
        иначе строка стояла бы всегда и перестала бы что-либо значить.
        """
        _, unchecked = b1(man(agent(LABEL, intent="active")),
                          fleet={LABEL}, disabled=None)
        self.assertEqual(unchecked, set())

    def test_retired_is_not_quietly_promoted_to_paused(self):
        """Звено «значения не склеились»: `retired` остаётся «убран навсегда».

        Загруженный `retired` — зомби и был им до ADR-769; четвёртое значение его
        вердикт не трогает.
        """
        found, _ = b1(man(agent(LABEL, intent="retired")),
                      fleet={LABEL}, disabled=frozenset({LABEL}))
        self.assertEqual(found, {(f"B1:zombie:{LABEL}", "CRITICAL")})


class TheRuleAboutPauseLivesInOneCopy(unittest.TestCase):
    """Правило «что такое пауза» обязано иметь ОДНУ копию.

    Второй разбор `launchctl print-disabled` рядом разъехался бы с первым МОЛЧА, и два
    сторожа отвечали бы на один вопрос по-разному (класс «одно имя — один объект»).
    """

    def test_conformance_borrows_the_siblings_door(self):
        """Мерится ТЕЛО функции, а не её проза.

        Проверка подстрокой по исходнику сравнивала бы текст с собственной
        docstring (та объясняет, почему второй копии быть не должно, и потому
        содержит все искомые слова) — утверждение, которое не способно упасть.
        Поэтому разбор идёт по AST с выброшенной строкой документации.
        """
        import ast, inspect, textwrap
        tree = ast.parse(textwrap.dedent(inspect.getsource(ac.gather_disabled)))
        fn = tree.body[0]
        body = fn.body[1:] if (fn.body and isinstance(fn.body[0], ast.Expr)
                               and isinstance(fn.body[0].value, ast.Constant)
                               and isinstance(fn.body[0].value.value, str)) else fn.body
        self.assertTrue(body, "у двери нет тела — мерить нечего, падаем громко")
        names = {n.id for b in body for n in ast.walk(ast.Module(body=[b], type_ignores=[]))
                 if isinstance(n, ast.Name)}
        imported = {alias.name for b in body for n in ast.walk(ast.Module(body=[b], type_ignores=[]))
                    if isinstance(n, (ast.Import, ast.ImportFrom)) for alias in n.names}
        self.assertIn("launchd_disabled_labels", names | imported,
                      "дверь обязана быть зовом соседа, а не вторым разбором")
        literals = {n.value for b in body
                    for n in ast.walk(ast.Module(body=[b], type_ignores=[]))
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        self.assertEqual([x for x in literals if "print-disabled" in x], [],
                         "вторая копия команды launchctl в этом модуле и есть расхождение")
        self.assertNotIn("subprocess", names | imported,
                         "свой вызов ОС рядом с зовом соседа — та же вторая копия")

    def test_the_sibling_reports_not_measured_as_none(self):
        """Сторона отказа у соседа — та, на которую опирается ветка «не измерено» выше."""
        from spa_core.monitoring.agent_health_monitor import launchd_disabled_labels
        self.assertEqual(launchd_disabled_labels(text=""), frozenset(),
                         "пустой вывод — это ИЗМЕРЕНО и пусто, а не «не измерено»")
        self.assertEqual(launchd_disabled_labels(text='"com.spa.x" => disabled'),
                         frozenset({"com.spa.x"}))


class ManifestAcceptsTheFourthValue(unittest.TestCase):
    """Генератор конституции обязан принимать `paused` и не обещать невозможного."""

    def test_paused_is_a_valid_intent(self):
        import importlib.util, os
        here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        spec = importlib.util.spec_from_file_location(
            "bam", os.path.join(here, "scripts", "build_architecture_manifest.py"))
        bam = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bam)
        self.assertIn("paused", bam.INTENTS)
        # пауза обратима ТОЛЬКО если plist на месте — иначе это `retired` под другим именем
        plists = {LABEL: {"plist_source": "launch_agents"}}
        self.assertEqual(
            [p for p in bam.validate(man(agent(LABEL, intent="paused")), plists)
             if LABEL in p], [])
        problems = [p for p in bam.validate(man(agent(LABEL, intent="paused")), {})
                    if LABEL in p]
        self.assertTrue(any("возобновить нечем" in p for p in problems), problems)


class TheProbeMeasuresTheOutcome(unittest.TestCase):
    """Контроль самой пробы приёмки (`.claude/rules/acceptance.md` п. 3).

    Проба обязана быть зелёной на ЦЕЛОМ контуре и красной на КАЖДОМ порванном звене,
    с названным звеном; и она не имеет права проходить подстрокой (ADR-333) — здесь
    сверяется ВЕРДИКТ (`satisfied` / `not_satisfied` / `unmeasured`), а причина
    читается только как объяснение владельцу.
    """

    @staticmethod
    def _run(manifest, label=LABEL):
        import json as _json
        import tempfile
        from spa_core.monitoring.card_acceptance import PROBES
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as fh:
            _json.dump(manifest, fh, ensure_ascii=False)
            path = fh.name
        try:
            return PROBES["paused_agent_is_not_a_dead_agent"](
                label, now=NOW, manifest_path=path)
        finally:
            import os as _os
            _os.unlink(path)

    def test_probe_is_registered_under_the_declared_name(self):
        from spa_core.monitoring.card_acceptance import PROBES
        self.assertIn("paused_agent_is_not_a_dead_agent", PROBES,
                      "карточка объявляет эту пробу — потеряв регистрацию, она измерять "
                      "уже ничего не может")

    def test_whole_circuit_is_satisfied(self):
        verdict, why = self._run(man(agent(LABEL, intent="paused")))
        self.assertEqual(verdict, "satisfied", why)

    def test_declaration_still_saying_active_is_not_satisfied(self):
        """ЗВЕНО: сам ярлык. Это и есть состояние, в котором карточка была 46 суток."""
        verdict, why = self._run(man(agent(LABEL, intent="active")))
        self.assertEqual(verdict, "not_satisfied", why)
        self.assertIn("active", why)

    def test_absent_agent_is_unmeasured_not_satisfied(self):
        """ЗВЕНО: предпосылка сцены. «Агента нет» — третий исход, а не успех."""
        verdict, why = self._run(man(agent("com.spa.someone_else", intent="paused")))
        self.assertEqual(verdict, "unmeasured", why)

    def test_unreadable_manifest_is_unmeasured(self):
        """ЗВЕНО: дверь к конституции. Не прочитали ⇒ НЕ ИЗМЕРЕНО с причиной."""
        from spa_core.monitoring.card_acceptance import PROBES
        verdict, why = PROBES["paused_agent_is_not_a_dead_agent"](
            LABEL, now=NOW, manifest_path="/nonexistent/spa-probe-scene/manifest.json")
        self.assertEqual(verdict, "unmeasured", why)
        self.assertIn("НЕ ОБЕСПЕЧЕНА", why)

    @staticmethod
    def _run_through_origin(tree_intent, origin_intent):
        """Та же проба, но ЧЕРЕЗ ту дверь курации, которой пользуется прод.

        `manifest_path` НЕ подаётся намеренно: он включает ветку «сцена» и примирение
        с origin обходит, а здесь примирение и есть предмет. Поэтому подменяются ровно
        две вещи — корень дерева и ответ `origin_manifest`.
        """
        import json as _json
        import os as _os
        import tempfile
        from unittest import mock
        from spa_core.monitoring import card_acceptance as ca

        root = tempfile.mkdtemp(prefix="spa_probe_origin_")
        _os.makedirs(_os.path.join(root, "architecture"))
        with open(_os.path.join(root, "architecture", "manifest.json"), "w",
                  encoding="utf-8") as fh:
            _json.dump(man(agent(LABEL, intent=tree_intent)), fh, ensure_ascii=False)
        origin = man(agent(LABEL, intent=origin_intent))
        with mock.patch.object(ac, "origin_manifest", return_value=(origin, "")), \
             mock.patch.object(ca, "REPO_ROOT", root):
            return ca.PROBES["paused_agent_is_not_a_dead_agent"](LABEL, now=NOW)

    def test_edit_that_never_reached_origin_is_not_satisfied(self):
        """ЗВЕНО: доставка. Прод читает курацию с `origin/main`, не из рабочего дерева.

        Проба, читавшая дерево, объявила бы НЕДОСТАВЛЕННУЮ правку выполненным критерием —
        ровно класс шага 0a («объявил → доставил?»), на котором работа четырёх сессий
        подряд однажды осталась в /tmp.
        """
        verdict, why = self._run_through_origin(tree_intent="paused",
                                                origin_intent="active")
        self.assertEqual(verdict, "not_satisfied", why)
        self.assertIn("origin/main", why)

    def test_delivered_declaration_is_satisfied(self):
        """ОБРАТНАЯ СТОРОНА: порвано одно звено — значение на origin."""
        verdict, why = self._run_through_origin(tree_intent="paused",
                                                origin_intent="paused")
        self.assertEqual(verdict, "satisfied", why)

    def test_unreadable_origin_is_unmeasured(self):
        """ТРЕТИЙ ИСХОД: конституция на origin не прочитана ⇒ доставка НЕ ИЗМЕРЕНА."""
        import json as _json, os as _os, tempfile
        from unittest import mock
        from spa_core.monitoring import card_acceptance as ca
        root = tempfile.mkdtemp(prefix="spa_probe_origin_")
        _os.makedirs(_os.path.join(root, "architecture"))
        with open(_os.path.join(root, "architecture", "manifest.json"), "w",
                  encoding="utf-8") as fh:
            _json.dump(man(agent(LABEL, intent="paused")), fh, ensure_ascii=False)
        with mock.patch.object(ac, "origin_manifest", return_value=(None, "git недоступен")), \
             mock.patch.object(ca, "REPO_ROOT", root):
            verdict, why = ca.PROBES["paused_agent_is_not_a_dead_agent"](LABEL, now=NOW)
        self.assertEqual(verdict, "unmeasured", why)
        self.assertIn("НЕ ИЗМЕРЕНО", why)

    def test_probe_dies_when_the_guard_is_weakened(self):
        """ЗВЕНО: сам сторож. Проба обязана ловить ОСЛАБЛЕНИЕ, а не только ярлык.

        Если `paused` перестанет быть различим от `active` внутри сторожа, сцена 1
        пробы останется зелёной, а сцена 2 (обратная сторона) — нет. Здесь это
        проверяется подменой самого вердикта сторожа: функция, никогда не находящая
        ничего, обязана дать `not_satisfied`, а не «всё в порядке».
        """
        from unittest import mock
        from spa_core.monitoring.card_acceptance import PROBES

        blind = {"findings": [], "unchecked": [], "exit_code": 0}
        with mock.patch.object(ac, "run_checks", return_value=blind):
            verdict, why = self._run(man(agent(LABEL, intent="paused")))
        self.assertEqual(verdict, "not_satisfied", why)
        self.assertIn("ОСЛАБЛЕН", why)


if __name__ == "__main__":
    unittest.main()
