"""Тесты замера «кто ЕЩЁ производит цель» (§41 ТЗ CIO, остаток ADR-250).

Каждый тест здесь — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: он воспроизводит дефект, который
этот модуль реально имел в цикле #511 и который был найден замером, а не
рассуждением. Проверка, никогда не видевшая настоящей поломки, — украшение
(`.claude/rules/deployment.md`).

Дефекты, закреплённые здесь:

1. **Ложная находка от структурного признака.** Первая редакция объявляла
   производителем цели ``export_data.py`` — за то, что тот пишет ключ
   ``positions``. А он пишет drift-ОТЧЁТ из уже принятого решения. Ложная
   находка такого рода не краснеет никогда: она выглядит как успех.
2. **Сцена, нарушающая НЕ ТО ограничение.** Первая сетевая сцена давала два
   имени по 30 %, и гейт отвергал её за КОНЦЕНТРАЦИЮ — а в отчёт это шло как
   «сетевой потолок связывает», хотя сети гейт не судит вовсе (ADR-250).
   Верный ответ на не тот вопрос.
3. **Разбор дерева считал вложенные рабочие деревья.** 60 «сайтов» из 5
   реальных: число зависело от того, сколько копий репозитория лежит сегодня
   на машине.
4. **Роль «решает» ≠ роль «записывает».** Требование сайта записи от каждого
   объявленного производителя объявляло пропавшим ``StrategyAllocator``.
5. **Молчание имеет ДВА смысла.** «Принял нарушающую цель» и «нарушающая цель
   до него не доходит» — разные ответы; слить их значит либо выдумать находку,
   либо спрятать её.
"""
# FROZEN-DATE-OK: injected-clock — все проверки времени идут через run(now=...),
# а фикстуры книг несут явный equity/notional без единой отметки времени.
from __future__ import annotations

import ast
import datetime as dt
import json
import os
import tempfile
import unittest

from spa_core.monitoring import cio_target_producers as mod


_FROZEN = dt.datetime(2026, 9, 7, 12, 0, 0, tzinfo=dt.timezone.utc)


class TestProvenanceDiscriminator(unittest.TestCase):
    """Дефект 1: форма книги ≠ решение о книге."""

    def _writes(self, src: str) -> list[dict]:
        tree = ast.parse(src)
        return mod._book_shaped_writes("probe.py", tree, mod._string_constants(tree))

    def test_describing_writer_is_not_a_producer(self):
        """Пишет ключ `positions` из ЗАГРУЖЕННОГО состояния ⇒ DESCRIBES.

        Это дословная форма ``export_data.export_drift_report``, из-за которой
        первая редакция выдала ложный CRITICAL.
        """
        src = (
            "def export_drift_report(ctx):\n"
            "    state = ctx.trader._load_portfolio_state()\n"
            "    drift = ctx.trader.calculate_drift(state.positions, 100.0)\n"
            "    atomic_save({'positions': drift}, 'data/drift_report.json')\n")
        writes = self._writes(src)
        self.assertEqual(len(writes), 1, "сайт записи обязан быть найден")
        self.assertEqual(writes[0]["provenance"], "DESCRIBES")

    def test_deciding_writer_is_a_producer(self):
        """Пишет `positions`, происходящие из решателя ⇒ DECIDES."""
        src = (
            "def rebalance():\n"
            "    book, opened, closed = sleeve_book.rebalance_book([], c, 100.0)\n"
            "    atomic_save({'positions': book}, 'data/hy_paper_trading.json')\n")
        writes = self._writes(src)
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]["provenance"], "DECIDES")

    def test_unestablished_origin_is_a_third_outcome_not_a_finding(self):
        """Происхождение не установлено ⇒ UNKNOWN, а НЕ «производитель».

        Fail-OPEN в сторону ложной находки не краснеет никогда — поэтому третий
        исход обязателен, и он не должен маскироваться ни под DECIDES, ни под
        DESCRIBES.
        """
        src = ("def f(x):\n"
               "    atomic_save({'positions': x}, 'data/whatever.json')\n")
        writes = self._writes(src)
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]["provenance"], "UNKNOWN")

    def test_payload_bound_to_a_variable_is_still_seen(self):
        """Нагрузка-переменная разворачивается до литерала.

        Без этого проход не видел бы НИ ОДНОГО настоящего писателя книги и
        исправно находил бы только тех, кто пишет словарь прямо в вызове.
        """
        src = ("def f():\n"
               "    book = sleeve_book.rebalance_book([], [], 1.0)\n"
               "    doc = {'positions': book, 'equity': 1.0}\n"
               "    atomic_save(doc, 'data/x.json')\n")
        writes = self._writes(src)
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]["provenance"], "DECIDES")


class TestSceneIsolatesTheRightConstraint(unittest.TestCase):
    """Дефект 2: сцена обязана нарушать ИМЕННО своё ограничение."""

    def setUp(self):
        self.scenes = mod._scenes(mod.REPO_ROOT)

    def test_chain_scene_breaks_no_per_protocol_cap(self):
        """Ни одно имя сетевой сцены не упирается в потолок концентрации.

        Первая редакция брала 30 % на имя — и гейт отвергал сцену за
        концентрацию, а отчёт читал это как работающий потолок СЕТИ.
        """
        scene = self.scenes["chain"]
        if "unchecked" in scene:
            self.skipTest("сетевая сцена не собрана: " + scene["unchecked"])
        for name, weight in scene["weights"].items():
            self.assertLessEqual(
                weight, 0.20,
                f"{name} = {weight:.0%} упирается в потолок концентрации T2 (20 %) — "
                f"сцена нарушала бы соседнее ограничение, а не сетевое")

    def test_chain_scene_holds_no_t3_name(self):
        """В сетевой сцене нет имени, которое T3 хоть для одной поверхности."""
        scene = self.scenes["chain"]
        if "unchecked" in scene:
            self.skipTest("сетевая сцена не собрана: " + scene["unchecked"])
        pops = mod._t3_populations()
        t3_any = pops["policy_enforcer"] | pops["tier_map"]
        self.assertFalse(
            set(scene["names"]) & t3_any,
            "имя из сцены сети считается T3 — сработал бы суммарный потолок тира")

    def test_t3_scene_breaks_no_per_protocol_cap(self):
        """НАРУШАЮЩИЕ имена сцены T3 не упираются в потолок концентрации.

        Проверяются именно они, а не вся сцена: наполнитель `aave_v3` — T1, у
        него потолок 40 %, и требовать от него 20 % значило бы мерить не тот
        порог (ровно та ошибка, ради которой этот класс тестов и написан).
        """
        scene = self.scenes["t3_total"]
        if "unchecked" in scene:
            self.skipTest("сцена T3 не собрана: " + scene["unchecked"])
        for name in scene["names"]:
            weight = scene["weights"][name]
            self.assertLessEqual(
                weight, 0.20,
                f"{name} = {weight:.0%} упирается в потолок концентрации — "
                f"срез шёл бы от него, а не от суммарного потолка тира")

    def test_scene_control_actually_measures_the_violation(self):
        """Контроль сцены считает нарушение САМ, а не верит объявлению."""
        for key in ("t3_total", "chain"):
            scene = self.scenes[key]
            if "unchecked" in scene:
                continue
            ok, detail = mod._scene_really_violates(key, scene, mod.REPO_ROOT)
            self.assertTrue(ok, f"{key}: сцена не нарушает порог — {detail}")

    def test_scene_control_rejects_a_compliant_scene(self):
        """Обратный контроль: соблюдающая сцена обязана быть названа таковой.

        Без него контроль сцены зеленел бы на чём угодно и не защищал ни от чего.
        """
        compliant = {"weights": {"aave_v3": 0.30, "compound_v3": 0.30}}
        ok, _ = mod._scene_really_violates("t3_total", compliant, mod.REPO_ROOT)
        self.assertFalse(ok, "сцена без единого T3-имени объявлена нарушающей")


class TestEnumerationIsHostIndependent(unittest.TestCase):
    """Дефект 3: разбор не должен считать вложенные рабочие деревья."""

    def test_nested_worktrees_are_skipped(self):
        with tempfile.TemporaryDirectory() as root:
            for rel in ("spa_core/analytics/real.py",
                        ".claude/worktrees/copy-a/spa_core/analytics/real.py",
                        ".claude/worktrees/copy-b/spa_core/analytics/real.py"):
                path = os.path.join(root, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write("x = 1\n")
            seen = [rel for rel, _ in mod._iter_runtime_modules(root)]
        self.assertEqual(seen, ["spa_core/analytics/real.py"],
                         "копии репозитория считались как отдельные модули — "
                         "число находок зависело бы от уборки деревьев, а не от кода")


class TestDeclaredProducersAreVerifiedByRole(unittest.TestCase):
    """Дефект 4: «решает» и «записывает» — разные роли."""

    def test_every_declared_producer_is_accounted_for(self):
        e = mod._enumerate_producers(mod.REPO_ROOT)
        self.assertEqual(
            e["missing_declared"], [],
            "объявленный производитель не подтверждён разбором — либо список "
            "устарел, либо проба его не видит; и то и другое обязано быть "
            "громким, а не тихим")

    def test_allocator_is_confirmed_though_it_writes_no_book(self):
        """StrategyAllocator книгу не пишет — и обязан остаться производителем."""
        e = mod._enumerate_producers(mod.REPO_ROOT)
        found = e["declared_writes_found"].get("spa_core/allocator/allocator.py")
        self.assertTrue(found, "аллокатор объявлен пропавшим — проба требует от "
                               "него роли, которой у него нет")
        self.assertEqual(found[0]["provenance"], "DECIDES")


class TestSilenceHasTwoMeanings(unittest.TestCase):
    """Дефект 5: принял нарушающее ≠ нарушающее до него не доходит."""

    _SCENE = {"weights": {"aave_v3": 0.30, "susde": 0.25},
              "names": ["susde"], "violates": "—"}

    def test_accepted_and_reachable_is_SILENT(self):
        outcome, _ = mod._classify(
            dict(self._SCENE["weights"]), self._SCENE, {"susde", "aave_v3"}, "")
        self.assertEqual(outcome, mod.SILENT)

    def test_accepted_but_unreachable_is_not_SILENT(self):
        outcome, _ = mod._classify(
            dict(self._SCENE["weights"]), self._SCENE, {"aave_v3"}, "")
        self.assertEqual(outcome, mod.UNREACHABLE)

    def test_unmeasured_universe_is_UNCHECKED_not_a_verdict(self):
        """Вселенная не измерена ⇒ третий исход, а не «принял» и не «отверг»."""
        outcome, detail = mod._classify(
            dict(self._SCENE["weights"]), self._SCENE, set(), "файл не прочитан")
        self.assertEqual(outcome, mod.UNCHECKED)
        self.assertIn("файл не прочитан", detail)

    def test_trimmed_target_is_BINDING(self):
        trimmed = {"aave_v3": 0.30, "susde": 0.10}
        outcome, _ = mod._classify(trimmed, self._SCENE, {"susde"}, "")
        self.assertEqual(outcome, mod.BINDING)

    def test_rejected_target_is_BINDING(self):
        outcome, _ = mod._classify({}, self._SCENE, {"susde"}, "")
        self.assertEqual(outcome, mod.BINDING)


class TestPositiveControlGatesTheWholeReport(unittest.TestCase):
    """Сломанный контроль обязан гасить СЧЁТ, а не только свою строку."""

    def test_a_producer_rejecting_the_healthy_target_voids_the_tally(self):
        original = mod.PRODUCERS
        mod.PRODUCERS = original + (
            ("probe/always_rejects.py", "проба, отвергающая всё",
             lambda weights: {}),)
        try:
            doc = mod.run(root=mod.REPO_ROOT, write=False, now=_FROZEN)
        finally:
            mod.PRODUCERS = original
        self.assertFalse(doc["control"]["passed"])
        self.assertEqual(doc["overall"], mod.UNCHECKED)
        self.assertTrue(all(r["outcome"] == mod.UNCHECKED for r in doc["matrix"]),
                        "счёт по производителям читается при непройденном контроле")

    def test_a_non_violating_scene_voids_the_tally(self):
        """Сцена, которая ничего не нарушает, обязана обрушить контроль.

        Иначе «принял нарушающую цель» было бы сказано над целью, которая
        ничего не нарушает — та самая тихая зелень, ради которой контроль и есть.
        """
        original = mod._scenes

        def _compliant_scenes(root):
            scenes = original(root)
            scenes["t3_total"] = {"weights": {"aave_v3": 0.30},
                                  "violates": "—", "names": ["aave_v3"]}
            return scenes

        mod._scenes = _compliant_scenes
        try:
            doc = mod.run(root=mod.REPO_ROOT, write=False, now=_FROZEN)
        finally:
            mod._scenes = original
        self.assertFalse(doc["control"]["passed"])
        self.assertEqual(doc["overall"], mod.UNCHECKED)


class TestLiveBooksSeparateTheoryFromState(unittest.TestCase):
    """`live_books` — единственное место, где замер отличает «правила нет» от
    «правила нет И книга уже за потолком». Без положительного контроля здесь
    отчёт молча читался бы как рассуждение о коде."""

    def _root_with(self, equity, positions):
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "data"), exist_ok=True)
        for name in ("hy_paper_trading.json", "lp_paper_trading.json"):
            with open(os.path.join(root, "data", name), "w", encoding="utf-8") as fh:
                json.dump({"equity": equity, "positions": positions}, fh)
        return root

    def test_book_over_the_declared_cap_is_reported(self):
        """25 % в T3 при потолке 15 % ⇒ `over_declared_cap`."""
        books = mod._live_books(self._root_with(
            100_000.0, [{"protocol": "pendle_yt_susde", "notional_usd": 25_000.0},
                        {"protocol": "aave_v3", "notional_usd": 75_000.0}]))
        self.assertEqual(len(books), 2)
        for b in books:
            self.assertNotIn("unchecked", b)
            self.assertAlmostEqual(b["t3_share"], 0.25, places=4)
            self.assertTrue(b["over_declared_cap"])

    def test_book_within_the_cap_is_not_reported(self):
        """Обратный контроль: книга в пределах потолка НЕ объявляется нарушающей.

        Без него проверка выше зеленела бы на любой книге и не значила ничего.
        """
        books = mod._live_books(self._root_with(
            100_000.0, [{"protocol": "pendle_yt_susde", "notional_usd": 10_000.0},
                        {"protocol": "aave_v3", "notional_usd": 90_000.0}]))
        for b in books:
            self.assertAlmostEqual(b["t3_share"], 0.10, places=4)
            self.assertFalse(b["over_declared_cap"])

    def test_unreadable_book_is_UNCHECKED_not_zero(self):
        """«Книгу не прочли» и «книга пуста» — разные ответы, и второе НЕ ноль."""
        root = tempfile.mkdtemp()
        os.makedirs(os.path.join(root, "data"), exist_ok=True)
        books = mod._live_books(root)
        self.assertEqual(len(books), 2)
        for b in books:
            self.assertIn("unchecked", b)
            self.assertNotIn("t3_share", b)

    def test_zero_equity_is_UNCHECKED_not_a_clean_pass(self):
        books = mod._live_books(self._root_with(0.0, []))
        for b in books:
            self.assertIn("unchecked", b)
            self.assertNotIn("t3_share", b)


class TestReportShape(unittest.TestCase):

    def setUp(self):
        self.doc = mod.run(root=mod.REPO_ROOT, write=False, now=_FROZEN)

    def test_report_does_not_write_live_state(self):
        """``write=False`` не создаёт отчёт; живой data/ не трогается."""
        path = os.path.join(mod.REPO_ROOT, mod.REPORT_REL)
        before = os.path.exists(path)
        mod.run(root=mod.REPO_ROOT, write=False, now=_FROZEN)
        self.assertEqual(os.path.exists(path), before)

    def test_clock_is_injected(self):
        self.assertEqual(self.doc["generated_at"], _FROZEN.isoformat())

    def test_every_pair_has_an_outcome(self):
        pairs = {(r["producer"], r["constraint"]) for r in self.doc["matrix"]}
        self.assertEqual(len(pairs), len(mod.PRODUCERS) * len(mod.CONSTRAINTS))
        for r in self.doc["matrix"]:
            self.assertIn(r["outcome"],
                          (mod.BINDING, mod.SILENT, mod.UNREACHABLE, mod.UNCHECKED))
            if r["outcome"] == mod.UNCHECKED:
                self.assertTrue(r["unchecked_reason"],
                                "UNCHECKED без причины — это скип, а не третий исход")

    def test_report_is_json_serialisable(self):
        json.dumps(self.doc, ensure_ascii=False)

    def test_advisory_is_stated(self):
        self.assertIn("ADVISORY", self.doc["advisory"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TestLiveReachability(unittest.TestCase):
    """Дефект 6 (цикл #512): «происхождение не установлено» ≠ «производитель».

    Замер #511 оставил ЧЕТЫРЕ сайта в третьем исходе `UNKNOWN`, и перепись
    честно называла себя частичной. Разбор #512 показал, что все четыре —
    демо-CLI и доказательство NAV, которых не запускает ни одна точка входа
    флота. Второй вопрос («исполняется ли этот код вообще») закрывает разрыв,
    НЕ угадывая происхождение.

    Опаснее самой находки здесь механика ответа: «недостижим» ЗАКРЫВАЕТ строку,
    поэтому сломавшаяся проба объявила бы недостижимым ВСЁ и изготовила тишину.
    Ради этого — положительный контроль и третий исход, и оба проверяются ниже.
    """

    def _tree(self, wrappers: dict[str, str], modules: dict[str, str]) -> str:
        """Крошечное дерево: обёртки флота + модули рантайма."""
        root = tempfile.mkdtemp(prefix="reach_")
        os.makedirs(os.path.join(root, "scripts"), exist_ok=True)
        for name, body in wrappers.items():
            with open(os.path.join(root, "scripts", name), "w",
                      encoding="utf-8") as fh:
                fh.write(body)
        for rel, body in modules.items():
            full = os.path.join(root, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(body)
        return root

    def test_module_run_by_a_wrapper_is_reachable(self):
        """Положительный контроль пробы: живой модуль обязан быть достижим."""
        root = self._tree(
            {"agent_x.sh": "exec bash agent_template.sh x spa_core.live.entry --run\n"},
            {"spa_core/live/entry.py": "import spa_core.live.helper\n",
             "spa_core/live/helper.py": "x = 1\n"})
        reach, why = mod._live_reachable(root)
        self.assertIsNotNone(reach, why)
        self.assertIn("spa_core.live.entry", reach)
        self.assertIn("spa_core.live.helper", reach,
                      "достижимость обязана идти ПО ИМПОРТАМ, а не по одному корню")

    def test_script_target_wrapper_is_a_root_too(self):
        """Регрессия дефекта САМОЙ этой правки (цикл #512).

        Первая редакция читала у обёртки только модульную цель `spa_core.*` и
        пропускала цель-СКРИПТ. Из-за этого недостижимыми оказывались
        `allocator` и `portfolio_rebalancer` — ГЛАВНЫЕ производители цели, —
        и положительный контроль правильно запретил применять вердикт.
        Тест держит вторую форму обёртки.
        """
        root = self._tree(
            {"agent_y.sh": "exec python3 /abs/scripts/daily_cycle.py --run\n"},
            {"scripts/daily_cycle.py": "import spa_core.alloc.core\n",
             "spa_core/alloc/core.py": "y = 1\n"})
        reach, why = mod._live_reachable(root)
        self.assertIsNotNone(reach, why)
        self.assertIn("spa_core.alloc.core", reach,
                      "цель-скрипт обёртки обязана быть корнем достижимости")

    def test_module_nobody_runs_is_not_reachable(self):
        """Обратная сторона: модуль без единого запускающего — недостижим."""
        root = self._tree(
            {"agent_x.sh": "exec bash agent_template.sh x spa_core.live.entry --run\n"},
            {"spa_core/live/entry.py": "z = 1\n",
             "spa_core/analytics/demo_cli.py": "w = 1\n"})
        reach, why = mod._live_reachable(root)
        self.assertIsNotNone(reach, why)
        self.assertNotIn("spa_core.analytics.demo_cli", reach)

    def test_no_wrapper_parsed_is_the_third_outcome_not_silence(self):
        """Ни одной обёртки ⇒ НЕ ИЗМЕРЕНО с причиной, а не «все недостижимы».

        Без этой ветки поломка пробы выглядела бы как полная перепись — то есть
        сторож замолчал бы ровно от того дефекта, против которого написан.
        """
        root = self._tree({}, {"spa_core/live/entry.py": "q = 1\n"})
        reach, why = mod._live_reachable(root)
        self.assertIsNone(reach, "пустой набор корней обязан давать НЕ ИЗМЕРЕНО")
        self.assertTrue(why.strip(), "третий исход обязан нести причину")


class TestReachabilityIsGuardedByItsControl(unittest.TestCase):
    """Вердикт «недостижим» не применяется, если проба не видит живых."""

    def test_declared_producers_are_reachable_in_the_real_tree(self):
        """Настоящее дерево: все объявленные производители обязаны быть видны.

        Это тот самый контроль, который поймал пропуск скриптовых корней. Он
        меряет НАСТОЯЩЕЕ дерево — на синтетическом он не поймал бы ничего.
        """
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(mod.__file__))))
        reach, why = mod._live_reachable(root)
        self.assertIsNotNone(reach, f"достижимость не измерена: {why}")
        blind = [mod._module_dotted(m) for _, m, _ in mod.DECLARED_BOOKS
                 if mod._module_dotted(m) not in reach]
        self.assertEqual(blind, [], f"проба не видит живых производителей: {blind}")

    def test_unreachable_unknown_site_becomes_offline_not_unknown(self):
        """Недостижимый сайт с неустановленным происхождением ⇒ OFFLINE."""
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(mod.__file__))))
        enum = mod._enumerate_producers(root)
        still_unknown = [w for w in enum["unresolved"]
                         if w.get("provenance") == "UNKNOWN"]
        self.assertEqual(
            still_unknown, [],
            "сайты, которых не исполняет никто, обязаны получать измеренный "
            f"исход, а не оставаться в третьем: {still_unknown}")

    def test_reachable_unknown_site_stays_loud(self):
        """Достижимый сайт с неустановленным происхождением ОСТАЁТСЯ громким.

        Иначе новая ветка была бы не измерением, а глушителем: она обязана
        закрывать только то, чего никто не исполняет.
        """
        self.assertIn("_OFFLINE", dir(mod))
        src = open(mod.__file__, encoding="utf-8").read()
        self.assertIn("and _module_dotted(rel) not in reachable", src,
                      "исход OFFLINE обязан быть обусловлен НЕдостижимостью")

    def test_control_refuses_the_verdict_when_a_live_producer_is_invisible(self):
        """ПРОВОДКА самого контроля: слеп к живому ⇒ вердикт не применяется.

        Эта ветка на здоровом дереве не срабатывает НИКОГДА, поэтому снятие
        контроля не красило ни один тест (мутация #4 цикла #512 прошла зелёной)
        — ровно класс «сторож не проверен, потому что состояние по умолчанию
        делает его лишним». Здесь проба заставлена ослепнуть на объявленном
        производителе, и от контроля требуется отказать в закрытии строк.
        """
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(mod.__file__))))
        full, why = mod._live_reachable(root)
        self.assertIsNotNone(full, why)
        blinded = set(full) - {mod._module_dotted(mod.DECLARED_BOOKS[0][1])}

        original = mod._live_reachable
        mod._live_reachable = lambda _root: (blinded, "")
        try:
            enum = mod._enumerate_producers(root)
        finally:
            mod._live_reachable = original

        offline = [w for ws in enum.values() if isinstance(ws, list) for w in ws
                   if isinstance(w, dict) and w.get("provenance") == mod._OFFLINE]
        self.assertEqual(
            offline, [],
            "контроль обязан ЗАПРЕТИТЬ вердикт «недостижим», когда проба не "
            f"видит живого производителя, а он закрыл строки: {offline}")
        still_unknown = [w for w in enum["unresolved"]
                         if w.get("provenance") == "UNKNOWN"]
        self.assertTrue(
            still_unknown,
            "при неисправной пробе сайты обязаны ОСТАТЬСЯ в третьем исходе, "
            "а не тихо исчезнуть")
