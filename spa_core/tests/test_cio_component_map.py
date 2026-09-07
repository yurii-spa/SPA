"""Тесты §46 — карта компонентов (:mod:`spa_core.monitoring.cio_component_map`).

Каждая сцена разбирается в памяти либо в ОТДЕЛЬНОМ временном дереве: живое
``data/`` не читается и не пишется. Время — ВХОД (``now=``), поэтому ни один тест
не зависит от календаря.

Разделение, ради которого тестов столько: у модуля ТРИ прибора (сайт продукта ·
носитель в памяти · род ступени), и у каждого своя цена ошибки. Прибор, который
не умеет сказать «нет», молча превращает разрыв цепи в зелёный отчёт.
"""

from __future__ import annotations

import ast
import json
import textwrap
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import cio_component_map as mod

# FROZEN-DATE-OK: injected-clock — все отметки приходят из этого якоря через
# параметр ``now=`` функции :func:`cio_component_map.run`; стенных часов в файле нет.
_NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


def _t(src: str) -> ast.AST:
    return ast.parse(textwrap.dedent(src))


class ResolverTests(unittest.TestCase):
    """Происхождение строки: путь почти никогда не лежит литералом в аргументе."""

    def test_literal_in_arg_is_a_write_site(self):
        t = _t('''
            from spa_core.utils.atomic import atomic_save
            def w(d):
                atomic_save({}, str(d / "x.json"))
        ''')
        self.assertTrue(mod.product_sites(t, "x.json")["write"])

    def test_module_constant_reaches_the_call(self):
        t = _t('''
            from spa_core.utils.atomic import atomic_save
            NAME = "x.json"
            def w(d):
                atomic_save({}, str(d / NAME))
        ''')
        self.assertTrue(mod.product_sites(t, "x.json")["write"])

    def test_helper_return_reaches_the_call(self):
        """``_out_path() → _OUT → литерал`` — форма ``reconciliation.py``."""
        t = _t('''
            from spa_core.utils.atomic import atomic_save
            _OUT = "x.json"
            def _out_path():
                return _OUT
            def w():
                path = _out_path()
                atomic_save({}, str(path))
        ''')
        self.assertTrue(mod.product_sites(t, "x.json")["write"])

    def test_parameter_default_reaches_the_call(self):
        """Форма ``allocator.py``: путь вывода живёт в умолчании параметра."""
        t = _t('''
            from spa_core.utils.atomic import atomic_save
            _DEFAULT_OUT = "x.json"
            def w(result, path=_DEFAULT_OUT):
                atomic_save(result, str(path))
        ''')
        self.assertTrue(mod.product_sites(t, "x.json")["write"])

    def test_receiver_of_a_method_call_is_a_site(self):
        """``path.read_text()`` не имеет аргументов вовсе — путь тут получатель.

        Пока обход смотрел только в аргументы, читатели снимка оркестратора были
        невидимы и ТРИ стыка подряд выходили ложно односторонними.
        """
        t = _t('''
            from pathlib import Path
            NAME = "x.json"
            def r(d):
                return (Path(d) / NAME).read_text()
        ''')
        self.assertTrue(mod.product_sites(t, "x.json")["read"])

    def test_container_is_not_a_provenance(self):
        """ОБРАТНАЯ половина: элемент словаря путём не становится.

        Живой образец аварии — сам этот модуль: имя ``risk_policy_blocks.json``
        лежит в его таблице ступеней, и пока обход спускался в контейнеры, он
        объявлял СЕБЯ писателем чужого артефакта.
        """
        t = _t('''
            from spa_core.utils.atomic import atomic_save
            TABLE = {"stage": "x.json"}
            def w(d):
                atomic_save(TABLE, str(d / "report.json"))
        ''')
        self.assertFalse(mod.product_sites(t, "x.json")["write"])

    def test_cross_module_constant_is_resolved(self):
        """Форма ``risk_gate.py``: литерал объявлен в СОСЕДНЕМ модуле."""
        owner = _t('RISK_BLOCKS_FILENAME = "risk_policy_blocks.json"\n')
        user = _t('''
            from spa_core.reporting.daily_telegram_report import RISK_BLOCKS_FILENAME
            from spa_core.utils.atomic import atomic_save
            def w(ddir):
                atomic_save([], str(ddir / RISK_BLOCKS_FILENAME))
        ''')
        modules = {"spa_core/reporting/daily_telegram_report.py": owner}
        ext = mod._external_names(user, modules)
        self.assertTrue(
            mod.product_sites(user, "risk_policy_blocks.json", ext)["write"])
        # …и без внешней таблицы прибор ЧЕСТНО не видит писателя:
        self.assertFalse(mod.product_sites(user, "risk_policy_blocks.json")["write"])

    def test_docstring_is_not_a_mention(self):
        t = _t('''
            """Модуль ОПИСЫВАЕТ x.json, но не трогает его."""
        ''')
        self.assertFalse(mod.product_sites(t, "x.json")["mention"])

    def test_mention_without_a_call_is_not_a_site(self):
        t = _t('TABLE = ["x.json"]\n')
        sites = mod.product_sites(t, "x.json")
        self.assertTrue(sites["mention"])
        self.assertFalse(sites["write"])
        self.assertFalse(sites["read"])


class InProcessCarrierTests(unittest.TestCase):
    """Носитель в памяти обязан быть СТРОГО сильнее импорта."""

    _UP_DOWN = {"run"}, {"read"}

    def test_value_passed_is_a_carrier(self):
        t = _t('''
            def cycle(d):
                res = run(d)
                return read(res)
        ''')
        self.assertTrue(mod.in_process_carrier(t, *self._UP_DOWN))

    def test_calling_both_without_passing_is_not_a_carrier(self):
        """🪤 Ловушка заказа #514 в её самой дорогой форме.

        Оркестратор ввёз обе ступени и позвал обе — по графу импортов и даже по
        графу вызовов цепь «связана». Значение при этом не передано, и стык
        существует только на бумаге.
        """
        t = _t('''
            def cycle(d):
                run(d)
                return read(d)
        ''')
        self.assertFalse(mod.in_process_carrier(t, *self._UP_DOWN))

    def test_provenance_travels_through_a_field(self):
        """``alloc = x.allocate()`` → ``target = alloc.target_usd`` → вниз.

        Без переноса через поле носитель «оптимизатор → цель» невидим: в
        ``cycle_runner`` вниз уезжает именно поле результата.
        """
        t = _t('''
            def cycle(d):
                alloc = obj.allocate()
                target = alloc.target_usd
                return write_shadow_rationale(target_positions=target)
        ''')
        self.assertTrue(mod.in_process_carrier(t, {"allocate"},
                                               {"write_shadow_rationale"}))

    def test_unknown_entries_give_no_carrier(self):
        t = _t('def cycle(d):\n    res = run(d)\n    return read(res)\n')
        self.assertFalse(mod.in_process_carrier(t, set(), {"read"}))
        self.assertFalse(mod.in_process_carrier(t, {"run"}, set()))

    def test_value_reaching_a_third_party_is_not_a_carrier(self):
        """Обратная половина: результат передан, но НЕ следующей ступени."""
        t = _t('''
            def cycle(d):
                res = run(d)
                log(res)
                return read(d)
        ''')
        self.assertFalse(mod.in_process_carrier(t, *self._UP_DOWN))


class EntryAndContractTests(unittest.TestCase):
    """Объявление обязано ПРОВЕРЯТЬСЯ, иначе устаревает молча."""

    def test_defines_reports_only_what_exists(self):
        t = _t('def a():\n    pass\n')
        self.assertEqual({"a"}, mod._defines(t, ("a", "b")))

    def test_human_contract_must_be_visible_in_the_module(self):
        ok = _t('def prepare(r):\n    return {"signed": False,'
                ' "requires_human_signature": True}\n')
        self.assertTrue(mod.has_contract(ok, ("requires_human_signature", "signed")))

    def test_human_contract_absent_is_not_assumed(self):
        bad = _t('def prepare(r):\n    return {}\n')
        self.assertFalse(mod.has_contract(bad, ("requires_human_signature",)))

    def test_empty_contract_is_never_satisfied(self):
        """Пустой контракт не должен зеленеть через ``all(())``."""
        self.assertFalse(mod.has_contract(_t("x = 1\n"), ()))

    def test_contract_in_a_docstring_does_not_count(self):
        t = _t('"""Здесь сказано requires_human_signature, но кода нет."""\n')
        self.assertFalse(mod.has_contract(t, ("requires_human_signature",)))


class PositiveControlTests(unittest.TestCase):
    """Контроль — условие ВСЕГО отчёта, и он обязан УПРАВЛЯТЬ вердиктом."""

    def test_all_five_pass_on_the_shipped_code(self):
        c = mod.positive_control()
        self.assertTrue(c["passed"], c["checks"])
        self.assertEqual(5, len(c["checks"]))

    _CLEAN = {"role": {}, "readers": {}, "registry": {}, "entries": {}, "edges": []}

    def _overall_with(self, passed: bool) -> str:
        """Вердикт :func:`run` на ЧИСТОМ замере при заданном исходе контроля.

        Замер подменяется намеренно: на пустом дереве все десять ступеней честно
        выходят ``UNCHECKED``, поэтому ``overall`` там равен ``UNCHECKED`` и БЕЗ
        гашения по контролю. Тест, сравнивавший вердикт на пустом дереве, был
        верным утверждением о НЕ ТОЙ ветке — он проходил и со сторожем, и без
        него (мутация «провал контроля больше не гасит отчёт» его пережила).
        """
        orig_c, orig_m = mod.positive_control, mod.measure
        try:
            mod.positive_control = lambda: {"passed": passed, "checks": {"k1": passed}}
            mod.measure = lambda *a, **k: dict(self._CLEAN)
            with TemporaryDirectory() as td:
                return mod.run(root=td, write=False, now=_NOW)["overall"]
        finally:
            mod.positive_control, mod.measure = orig_c, orig_m

    def test_failed_control_forces_unchecked_overall(self):
        """ПРОВОДКА: ослепим контроль — вердикт обязан пойти за ним.

        Без этого теста контроль можно чинить в своей функции и оставить вторую
        копию решения внутри :func:`run` — украшение вместо сторожа.
        """
        self.assertEqual("UNCHECKED", self._overall_with(passed=False))

    def test_passing_control_does_not_force_unchecked(self):
        """ОБРАТНАЯ половина: две ветки обязаны быть РАЗЛИЧИМЫ.

        Без неё достаточно вернуть ``UNCHECKED`` всегда, и первый тест снова
        станет верным утверждением о любой из веток.
        """
        self.assertEqual("OK", self._overall_with(passed=True))

    def test_k3_and_k5_are_the_two_halves_of_the_same_trap(self):
        c = mod.positive_control()["checks"]
        self.assertTrue(c["k3_import_is_not_wiring"])
        self.assertTrue(c["k5_calling_both_is_not_carrying"])


class EdgeVerdictTests(unittest.TestCase):
    """Исходы стыка на СИНТЕТИЧЕСКОМ дереве — каждый вердикт достижим."""

    def _tree(self, files: dict[str, str]) -> Path:
        self._td = TemporaryDirectory()
        root = Path(self._td.name)
        for rel, src in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(textwrap.dedent(src), encoding="utf-8")
        return root

    def tearDown(self):
        td = getattr(self, "_td", None)
        if td is not None:
            td.cleanup()

    _STAGES = (
        mod.Stage("up", "Up", "spa_core/up.py", "u.json", "artifact",
                  entry=("produce",)),
        mod.Stage("down", "Down", "spa_core/down.py", "d.json", "artifact",
                  entry=("consume",)),
    )

    def test_reader_of_the_product_gives_wired(self):
        root = self._tree({
            "spa_core/up.py": '''
                from spa_core.utils.atomic import atomic_save
                def produce(d):
                    atomic_save({}, str(d / "u.json"))
            ''',
            "spa_core/down.py": '''
                from spa_core.utils.atomic import atomic_save
                def consume(d):
                    atomic_save({}, str(d / "d.json"))
                    return open(str(d / "u.json")).read()
            ''',
        })
        edge = mod.measure(root, self._STAGES)["edges"][0]
        self.assertEqual("WIRED", edge["verdict"])
        self.assertEqual("artifact", edge["carrier"])

    def test_no_reader_at_all_gives_dead_end(self):
        root = self._tree({
            "spa_core/up.py": '''
                from spa_core.utils.atomic import atomic_save
                def produce(d):
                    atomic_save({}, str(d / "u.json"))
            ''',
            "spa_core/down.py": '''
                from spa_core.utils.atomic import atomic_save
                def consume(d):
                    atomic_save({}, str(d / "d.json"))
            ''',
        })
        edge = mod.measure(root, self._STAGES)["edges"][0]
        self.assertEqual("DEAD_END", edge["verdict"])

    def test_reader_that_is_not_the_next_stage_gives_one_way(self):
        root = self._tree({
            "spa_core/up.py": '''
                from spa_core.utils.atomic import atomic_save
                def produce(d):
                    atomic_save({}, str(d / "u.json"))
            ''',
            "spa_core/down.py": '''
                from spa_core.utils.atomic import atomic_save
                def consume(d):
                    atomic_save({}, str(d / "d.json"))
            ''',
            "spa_core/side.py": '''
                def look(d):
                    return open(str(d / "u.json")).read()
            ''',
        })
        edge = mod.measure(root, self._STAGES)["edges"][0]
        self.assertEqual("ONE_WAY", edge["verdict"])
        self.assertEqual(["spa_core/side.py"], edge["readers"])

    def test_stale_entry_declaration_is_loud(self):
        """Объявленный вход, которого нет, — ``UNCHECKED``, а не тихий пропуск."""
        root = self._tree({
            "spa_core/up.py": 'def other():\n    pass\n',
            "spa_core/down.py": 'def consume():\n    pass\n',
        })
        meas = mod.measure(root, self._STAGES)
        self.assertEqual("UNCHECKED", meas["role"]["up"]["verdict"])
        self.assertIn("produce", meas["role"]["up"]["reason"])
        self.assertEqual("UNCHECKED", meas["edges"][0]["verdict"])

    def test_human_endpoint_makes_the_edge_by_design(self):
        """Стык к ступени рода ``human`` не требует машинного носителя."""
        stages = (
            self._STAGES[0],
            mod.Stage("hand", "Hand", "spa_core/down.py", "", "human",
                      entry=("consume",), contract=("signed",)),
        )
        root = self._tree({
            "spa_core/up.py": '''
                from spa_core.utils.atomic import atomic_save
                def produce(d):
                    atomic_save({}, str(d / "u.json"))
            ''',
            "spa_core/down.py": 'def consume(d):\n    return {"signed": False}\n',
        })
        self.assertEqual("BY_DESIGN_HUMAN",
                         mod.measure(root, stages)["edges"][0]["verdict"])

    def test_writer_via_orchestrator_counts_as_performing(self):
        """Урок ADR-251: решать и записывать — РАЗНЫЕ роли."""
        root = self._tree({
            "spa_core/up.py": 'def produce(d):\n    return {"v": 1}\n',
            "spa_core/down.py": 'def consume(d):\n    return 0\n',
            "spa_core/orch.py": '''
                from spa_core.up import produce
                from spa_core.utils.atomic import atomic_save
                def cycle(d):
                    verdict = produce(d)
                    atomic_save(verdict, str(d / "u.json"))
            ''',
        })
        role = mod.measure(root, self._STAGES)["role"]["up"]
        self.assertEqual("PERFORMED_VIA_ORCHESTRATOR", role["verdict"])
        self.assertEqual("spa_core/orch.py", role["writer"])

    def test_tests_are_not_counted_as_readers(self):
        root = self._tree({
            "spa_core/up.py": '''
                from spa_core.utils.atomic import atomic_save
                def produce(d):
                    atomic_save({}, str(d / "u.json"))
            ''',
            "spa_core/down.py": 'def consume(d):\n    return 0\n',
            "spa_core/tests/test_up.py": '''
                def test_x(d):
                    return open(str(d / "u.json")).read()
            ''',
        })
        self.assertEqual("DEAD_END", mod.measure(root, self._STAGES)["edges"][0]["verdict"])


class SelfExclusionTests(unittest.TestCase):
    """Сторож не имеет права кормить свой же корпус."""

    def test_the_measurer_is_excluded_from_the_measured_tree(self):
        root = Path(mod.__file__).resolve().parents[2]
        rels = {rel for rel, _ in mod._iter_modules(root)}
        self.assertNotIn(mod._SELF, rels)
        self.assertIn("spa_core/paper_trading/cycle_runner.py", rels)

    def test_self_would_otherwise_mention_every_product(self):
        """ПОЛОЖИТЕЛЬНЫЙ контроль исключения: без него измеритель — «читатель».

        Именно так и случилось на первом прогоне: единственным «потребителем»
        ``execution_reconciliation.json`` оказался сам этот файл.
        """
        tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
        for st in mod.STAGES:
            if st.product:
                self.assertTrue(mod.product_sites(tree, st.product)["mention"],
                                f"{st.product} должен упоминаться в таблице ступеней")


class ReportTests(unittest.TestCase):
    """Форма отчёта, вес находок и запись артефакта.

    Живой замер стоит ~30 с, поэтому он делается ОДИН раз на класс: четыре
    независимых прогона отвечали на один и тот же вопрос вчетверо дороже.
    """

    @classmethod
    def setUpClass(cls):
        cls.live = mod.run(root=Path(mod.__file__).resolve().parents[2],
                           write=False, now=_NOW)

    def test_now_is_an_input(self):
        with TemporaryDirectory() as td:
            doc = mod.run(root=td, write=False, now=_NOW)
        self.assertEqual(_NOW.isoformat(), doc["generated_at"])

    def test_writes_the_artifact_where_declared(self):
        with TemporaryDirectory() as td:
            mod.run(root=td, write=True, now=_NOW)
            out = Path(td) / mod.REPORT_REL
            self.assertTrue(out.exists())
            doc = json.loads(out.read_text())
        self.assertEqual("cio_component_map/v1", doc["schema"])

    def test_island_is_critical_and_divergence_is_warn(self):
        """Два РАЗНЫХ веса: остров ≠ расхождение с картой.

        Продукт, которого не читает НИКТО, и продукт, который берут пятьдесят
        модулей мимо следующей ступени, — разные состояния; один счёт на оба
        стёр бы именно то различие, ради которого замер и делается.
        """
        island = mod._findings({"edges": [{
            "from_name": "A", "to_name": "B", "product": "p.json",
            "verdict": "ONE_WAY", "readers": [], "registry_consumers": ["office.py"],
            "note": ""}], "role": {}})
        diverge = mod._findings({"edges": [{
            "from_name": "A", "to_name": "B", "product": "p.json",
            "verdict": "ONE_WAY", "readers": ["a.py", "b.py"], "note": ""}],
            "role": {}})
        self.assertEqual("critical", island[0]["severity"])
        self.assertEqual("warn", diverge[0]["severity"])

    def test_unchecked_role_reaches_the_findings(self):
        f = mod._findings({"edges": [], "role": {
            "s": {"verdict": "UNCHECKED", "reason": "вход не определён"}}})
        self.assertEqual(1, len(f))
        self.assertEqual("unchecked", f[0]["severity"])
        self.assertIn("вход не определён", f[0]["text"])

    def test_every_declared_stage_is_measured(self):
        doc = self.live
        self.assertEqual(len(mod.STAGES), len(doc["stages"]))
        self.assertEqual(len(mod.STAGES) - 1, doc["edges_total"])
        for st in mod.STAGES:
            self.assertIn(st.key, doc["stages"])

    def test_owner_names_are_verbatim_from_the_spec(self):
        """Имена ступеней — дословно §46; переименование ломает сверку с ТЗ."""
        self.assertEqual(
            ["Opportunity Data", "Portfolio State", "Portfolio Optimizer",
             "Target Allocation", "Rebalance Evaluator", "Risk Gate",
             "Execution Planner", "Execution Agent", "Post-Trade Monitor",
             "Reporting"],
            [s.owner_name for s in mod.STAGES])

    def test_counts_and_findings_agree(self):
        doc = self.live
        for sev in ("critical", "warn", "unchecked"):
            self.assertEqual(
                doc["counts"][sev],
                sum(1 for f in doc["findings"] if f["severity"] == sev), sev)

    def test_advisory_is_stated_in_the_artifact(self):
        doc = self.live
        self.assertIn("ADVISORY", doc["advisory"])


class LiveTreeTests(unittest.TestCase):
    """Замер на ЖИВОМ дереве: числа не закрепляем, закрепляем ФОРМУ."""

    @classmethod
    def setUpClass(cls):
        cls.doc = mod.run(root=Path(mod.__file__).resolve().parents[2],
                          write=False, now=_NOW)

    def test_control_passes_on_the_live_tree(self):
        self.assertTrue(self.doc["positive_control"]["passed"])

    def test_every_stage_of_the_owner_map_has_an_equivalent(self):
        """§46 «не создавать новые компоненты» — у всех десяти эквивалент ЕСТЬ.

        Это и есть прямой ответ владельцу: строить нечего. Если тест покраснеет,
        значит либо ступень исчезла, либо объявление устарело — оба случая
        требуют разбора, а не правки числа.
        """
        unchecked = {k: v["reason"] for k, v in self.doc["stages"].items()
                     if v["verdict"] == "UNCHECKED"}
        self.assertEqual({}, unchecked)

    def test_verdicts_come_from_the_declared_vocabulary(self):
        allowed = {"WIRED", "WIRED_IN_PROCESS", "ONE_WAY", "DEAD_END",
                   "BY_DESIGN_HUMAN", "UNCHECKED"}
        self.assertTrue(allowed.issuperset(e["verdict"] for e in self.doc["edges"]))

    def test_orchestrator_is_declared_and_present(self):
        self.assertEqual(["spa_core/paper_trading/cycle_runner.py"],
                         self.doc["orchestrators"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
