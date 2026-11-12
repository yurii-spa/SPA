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
        # ADR-991: к пяти сценам стыка добавлены четыре — переписчики (К6/К7)
        # и порядок (К8/К9). Число проверяется, чтобы сцену нельзя было снять молча.
        self.assertEqual(9, len(c["checks"]))

    # ``order`` — третья ось (ADR-991); пустой словарь = «оркестраторов нет»,
    # а не «инверсий ноль»: :func:`run` считает инверсии по измеренным записям.
    _CLEAN = {"role": {}, "readers": {}, "registry": {}, "entries": {}, "edges": [],
              "order": {}}

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

    def test_k6_requires_the_hidden_stage_to_be_seen(self):
        """К6 — о ЧУВСТВИТЕЛЬНОСТИ пробы, а не о её вердикте.

        Проба, ответившая ``measured`` и НЕ увидевшая ``clamp``, слепа — К6
        обязан упасть; иначе контроль подтверждает любую пробу, умеющую сказать
        «измерено» (M18 ADR-991 пережила батарею #1109). Вторая половина: та же
        слепая проба К7 устраивает — две сцены различимы.
        """
        orig = mod.carrier_rewriters
        try:
            mod.carrier_rewriters = lambda *a, **k: {"verdict": "measured",
                                                      "hidden": [], "sites": []}
            checks = mod.positive_control()["checks"]
        finally:
            mod.carrier_rewriters = orig
        self.assertFalse(checks["k6_rewriter_probe_sees_a_hidden_stage"])
        self.assertTrue(checks["k7_alias_and_derivative_are_not_rewriters"])


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
        # v2 с ADR-991: артефакт несёт третью ось (скрытые ступени · порядок);
        # читатель шага 0-офис объявляет её поля в ``_READ_SCHEMA``.
        self.assertEqual("cio_component_map/v2", doc["schema"])

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




# ───────────────── третья ось (ADR-991): переписчики носителя и порядок ─────────────────

_DECL = {"run": "up", "read": "down", "gate": "gate"}


def _rw(src: str, up=("run",), down=("read",)):
    return mod.carrier_rewriters(_t(src), set(up), set(down), _DECL)


class CarrierRewriterTests(unittest.TestCase):
    """Кто пересвязывает носитель между входом верхней ступени и входом нижней.

    Живой образец — ``cycle_runner`` между ``allocate()`` и
    ``write_shadow_rationale``: девять присваиваний ``target_usd`` (ADR-989), семь
    из них — функции, которых в карте владельца нет.
    """

    def test_hidden_rewriter_is_named_with_its_line(self):
        r = _rw('''
            def cycle(d):
                res = run(d)
                res = clamp(res, d)
                return read(res)
        ''')
        self.assertEqual("measured", r["verdict"])
        self.assertEqual(["clamp"], r["hidden"])
        self.assertEqual(1, len(r["sites"]))
        self.assertEqual("hidden", r["sites"][0]["kind"])
        self.assertEqual(4, r["sites"][0]["line"])
        self.assertEqual(["res"], r["carried"])
        self.assertEqual("cycle", r["function"])

    def test_declared_stage_on_the_wrong_edge_is_not_hidden(self):
        """Вызов входа ДРУГОЙ прописанной ступени — «не на своём стыке», не скрытая."""
        r = _rw('''
            def cycle(d):
                res = run(d)
                res = gate(res)
                return read(res)
        ''')
        self.assertEqual([], r["hidden"])
        self.assertEqual(["gate"], r["declared_out_of_place"])
        self.assertEqual("declared", r["sites"][0]["kind"])

    def test_copy_ctor_is_attributed_to_the_binder(self):
        """``target = dict(gate["target"])`` переписал не ``dict`` — тот, кто связал ``gate``.

        Без этого оба трима RiskPolicy в ``cycle_runner`` читались бы как «dict».
        """
        r = _rw('''
            def cycle(d):
                res = run(d)
                g = gate(res)
                res = dict(g["target"])
                return read(res)
        ''')
        self.assertEqual(1, len(r["sites"]))
        self.assertEqual("gate", r["sites"][0]["callee"])
        self.assertEqual("g", r["sites"][0]["via"])
        self.assertEqual("declared", r["sites"][0]["kind"])

    def test_tuple_unpack_rebinding_counts(self):
        """``target, extra = f(target)`` — форма ``_compliant_target`` и трима ADR-850."""
        r = _rw('''
            def cycle(d):
                res = run(d)
                res, rec = trim(res)
                return read(res)
        ''')
        self.assertEqual(["trim"], r["hidden"])

    def test_alias_without_a_call_is_not_a_rewriter(self):
        r = _rw('''
            def cycle(d):
                res = run(d)
                same = res
                return read(same)
        ''')
        self.assertEqual("measured", r["verdict"])
        self.assertEqual([], r["sites"])

    def test_rebinding_to_a_plain_name_without_a_call_is_not_a_site(self):
        """ПЕРЕсвязывание носителя псевдонимом (``res = d``) — не площадка.

        Сцена ``same = res`` выше этого НЕ различает: ``same`` — ПЕРВОЕ
        связывание и отсеивается раньше, чем прибор смотрит на вызовы (мутация
        M05 ADR-991 пережила батарею #1109). Здесь имя носителя связано ВТОРОЙ
        раз и без вызова — прибор обязан дойти до этой ветки и промолчать, а не
        упасть на пустом списке вызываемых.
        """
        r = _rw('''
            def cycle(d):
                res = run(d)
                res = clamp(res)
                res = d
                return read(res)
        ''')
        self.assertEqual("measured", r["verdict"])
        self.assertEqual([4], [s["line"] for s in r["sites"]])
        self.assertEqual(["clamp"], r["hidden"])

    def test_first_binding_of_a_derivative_is_not_a_rewriter(self):
        """Найдено на себе: ``_policy_refusals = quantify(...)`` — производная, не переписчик."""
        r = _rw('''
            def cycle(d):
                res = run(d)
                extra = quantify(res)
                return read(res, extra)
        ''')
        self.assertEqual([], r["sites"])
        self.assertIn("extra", r["carried"])

    def test_sites_outside_the_span_are_ignored(self):
        r = _rw('''
            def cycle(d):
                res = run(d)
                res = clamp(res)
                out = read(res)
                res = after(res)
                return out
        ''')
        self.assertEqual(["clamp"], r["hidden"])

    def test_sites_are_sorted_by_line_and_repeated_callee_is_one_hidden_stage(self):
        r = _rw('''
            def cycle(d):
                res = run(d)
                res = soft(res)
                res = other(res)
                res = soft(res)
                return read(res)
        ''')
        self.assertEqual([4, 5, 6], [s["line"] for s in r["sites"]])
        self.assertEqual(["other", "soft"], r["hidden"])

    def test_import_alias_resolves_to_the_entry(self):
        r = mod.carrier_rewriters(_t('''
            from spa_core.a import run as _r
            from spa_core.b import read as _w
            def cycle(d):
                res = _r(d)
                res = clamp(res)
                return _w(res)
        '''), {"run"}, {"read"}, _DECL)
        self.assertEqual(["clamp"], r["hidden"])

    def test_entries_in_different_functions_are_unmeasured(self):
        """Строка между функциями порядком не является — третий исход, не ноль."""
        r = _rw('''
            def a(d):
                res = run(d)
                return res
            def b(res):
                return read(res)
        ''')
        self.assertEqual("unmeasured", r["verdict"])
        self.assertIn("разных функциях", r["reason"])
        self.assertEqual([], r["sites"])

    def test_down_entry_without_the_product_is_unmeasured(self):
        r = _rw('''
            def cycle(d):
                res = run(d)
                return read(d)
        ''')
        self.assertEqual("unmeasured", r["verdict"])

    def test_no_up_call_is_unmeasured(self):
        r = _rw('''
            def cycle(d):
                return read(d)
        ''')
        self.assertEqual("unmeasured", r["verdict"])


def _order(src: str, order=("a", "b", "c"), entries=None, skip=frozenset()):
    entries = entries or {"a": {"first"}, "b": {"second"}, "c": {"third"}}
    return mod.stage_order(_t(src), entries, order, skip)


class StageOrderTests(unittest.TestCase):
    """Порядок первого вызова входов на сквозном пути против порядка владельца."""

    def test_owner_order_gives_zero_inversions(self):
        o = _order('''
            def cycle(d):
                first(d)
                second(d)
                third(d)
        ''')
        self.assertEqual("measured", o["verdict"])
        self.assertEqual([], o["inversions"])
        self.assertEqual(["a", "b", "c"], o["live_order"])
        self.assertEqual("cycle", o["root"])

    def test_calls_on_one_line_tie_and_are_not_an_inversion(self):
        """Мера — строка; равные строки равны, и выдумывать порядок внутри строки нельзя."""
        o = _order('''
            def cycle(d):
                third(d); first(d); second(d)
        ''')
        self.assertEqual([], o["inversions"])

    def test_inversion_is_a_named_pair(self):
        o = _order('''
            def cycle(d):
                third(d)
                first(d)
                second(d)
        ''')
        self.assertEqual([["a", "c"], ["b", "c"]], o["inversions"])
        self.assertEqual(["c", "a", "b"], o["live_order"])

    def test_helper_call_is_positioned_where_the_helper_is_called(self):
        """Вызов внутри помощника стои́т там, где стои́т вызов помощника."""
        o = _order('''
            def helper(d):
                third(d)
            def cycle(d):
                first(d)
                helper(d)
                second(d)
        ''')
        self.assertEqual("cycle", o["root"])
        # строки сцены: 1 пустая · 2 def helper · 3 third · 4 def cycle · 5 first · 6 helper
        self.assertEqual([6, 3], o["positions"]["c"]["first"])
        self.assertEqual([["b", "c"]], o["inversions"])

    def test_early_exit_branch_is_off_path_not_a_position(self):
        """``if not live: … return`` — ветка «данных нет» порядком торгового дня не является."""
        o = _order('''
            def cycle(d, live):
                if not live:
                    third(d)
                    return 0
                first(d)
                second(d)
        ''')
        self.assertEqual([], o["inversions"])
        self.assertIn("c", o["off_path"])
        self.assertNotIn("c", o["positions"])
        self.assertEqual(4, o["off_path"]["c"]["first"][-1])   # строка ``third(d)``

    def test_function_tail_return_is_not_an_early_exit(self):
        """``return`` последним оператором — хвост функции, не ранний выход."""
        o = _order('''
            def cycle(d):
                first(d)
                second(d)
                return third(d)
        ''')
        self.assertEqual(["a", "b", "c"], o["live_order"])
        self.assertEqual({}, o["off_path"])

    def test_on_path_call_is_preferred_over_an_early_exit_call(self):
        """``main`` зовёт ``_main_inner`` дважды — сперва в ветке ``--dry-run``."""
        o = _order('''
            def inner(d):
                first(d)
                second(d)
            def main(d, dry):
                if dry:
                    return inner(d)
                third(d)
                inner(d)
        ''')
        self.assertEqual("main", o["root"])
        # ``inner(d)`` на сквозном пути — строка 9, ``first`` внутри — строка 3
        self.assertEqual([9, 3], o["positions"]["a"]["first"])
        self.assertEqual([["a", "c"], ["b", "c"]], o["inversions"])

    def test_attribute_call_does_not_close_the_call_graph_into_a_ring(self):
        """``_mod2.main()`` — чужой модуль; считать его своим ``main`` = кольцо без корня."""
        o = _order('''
            def pack(d):
                _mod2.main()
            def inner(d):
                first(d)
                second(d)
                third(d)
                pack(d)
            def main(d):
                return inner(d)
        ''')
        self.assertEqual("main", o["root"])
        self.assertEqual([], o["inversions"])

    def test_direct_ring_is_cut_without_a_root(self):
        o = _order('''
            def a_fn(d):
                b_fn(d)
            def b_fn(d):
                a_fn(d)
                first(d)
                second(d)
            def main(d):
                third(d)
                a_fn(d)
        ''')
        self.assertEqual("main", o["root"])
        self.assertEqual(["c", "a", "b"], o["live_order"])

    def test_ring_does_not_lengthen_a_position(self):
        """Позиция ступени, достижимой через кольцо, — ПРЯМОЙ путь к корню.

        Сцена «кольцо обрывается без корня» мутацию «кольцо не обрывается» НЕ
        различила (M13 ADR-991): предел глубины гасит зацикливание, а живой
        порядок двух ступеней от лишнего круга не менялся. Различает ТОЧНАЯ
        позиция: без обрыва кольцо даёт более длинный путь с меньшей строкой на
        третьем месте, и он сортируется ПЕРВЫМ.
        """
        o = _order('''
            def a_fn(d):
                b_fn(d)
                second(d)
            def b_fn(d):
                a_fn(d)
                first(d)
            def main(d):
                a_fn(d)
        ''')
        self.assertEqual("main", o["root"])
        # строки сцены: 2 def a_fn · 3 b_fn · 4 second · 5 def b_fn · 6 a_fn · 7 first · 8 def main · 9 a_fn
        self.assertEqual([9, 3, 7], o["positions"]["a"]["first"])
        self.assertEqual([9, 4], o["positions"]["b"]["first"])
        self.assertEqual([], o["inversions"])

    def test_import_alias_is_an_entry_call(self):
        o = _order('''
            from spa_core.x import second as _rb
            def cycle(d):
                first(d); _rb(d); third(d)
        ''')
        self.assertEqual([], o["inversions"])
        self.assertIn("b", o["positions"])

    def test_unreached_stage_is_named_not_counted(self):
        o = _order('''
            def cycle(d):
                first(d); second(d)
        ''')
        self.assertEqual(["c"], o["unreached"])
        self.assertEqual([], o["inversions"])

    def test_skipped_human_stage_is_neither_unreached_nor_positioned(self):
        o = _order('''
            def cycle(d):
                first(d); second(d)
        ''', skip=frozenset({"c"}))
        self.assertEqual([], o["unreached"])
        self.assertEqual(["a", "b"], o["owner_order"])

    def test_fewer_than_two_positions_is_unmeasured(self):
        o = _order('''
            def cycle(d):
                first(d)
        ''')
        self.assertEqual("unmeasured", o["verdict"])

    def test_no_calls_at_all_is_unmeasured(self):
        o = _order('''
            def cycle(d):
                return 0
        ''')
        self.assertEqual("unmeasured", o["verdict"])
        self.assertEqual(["a", "b", "c"], o["unreached"])


class ThirdAxisReportTests(unittest.TestCase):
    """Проводка оси в отчёт: находки, счётчики, схема."""

    def _edge(self, **rw):
        return {"from": "u", "to": "d", "from_name": "U", "to_name": "D",
                "product": "p.json", "verdict": "WIRED_IN_PROCESS", "readers": [],
                "carrier": "in_process:orch.py", "note": "",
                "rewriters": {"verdict": "measured", "reason": "", "function": "cycle",
                              "span": [2, 9], "carried": ["res"], "sites": [],
                              "hidden": [], "declared_out_of_place": [], **rw}}

    def test_hidden_stage_is_critical_and_names_the_functions(self):
        e = self._edge(hidden=["clamp", "trim"],
                       sites=[{"line": 3, "bound": ["res"], "callee": "clamp", "via": "",
                               "stage": "", "kind": "hidden"},
                              {"line": 4, "bound": ["res"], "callee": "trim", "via": "",
                               "stage": "", "kind": "hidden"}])
        f = mod._findings({"edges": [e], "role": {}, "order": {}})
        crit = [x for x in f if x["severity"] == "critical"]
        self.assertEqual(1, len(crit))
        self.assertIn("СКРЫТЫЕ СТУПЕНИ", crit[0]["text"])
        self.assertIn("clamp, trim", crit[0]["text"])
        self.assertIn("2 функций", crit[0]["text"])
        self.assertIn("2 площадках", crit[0]["text"])

    def test_declared_out_of_place_is_warn(self):
        e = self._edge(declared_out_of_place=["risk_gate"],
                       sites=[{"line": 3, "bound": ["res"], "callee": "_apply_risk_policy_gate",
                               "via": "gate", "stage": "risk_gate", "kind": "declared"}])
        f = mod._findings({"edges": [e], "role": {}, "order": {}})
        self.assertEqual(["warn"], [x["severity"] for x in f])
        self.assertIn("Risk Gate", f[0]["text"])

    def test_zero_sites_on_a_measured_edge_is_no_finding(self):
        f = mod._findings({"edges": [self._edge()], "role": {}, "order": {}})
        self.assertEqual([], f)

    def test_unmeasured_rewriters_are_unchecked_not_zero(self):
        e = self._edge()
        e["rewriters"] = {"verdict": "unmeasured", "reason": "входы в разных функциях"}
        f = mod._findings({"edges": [e], "role": {}, "order": {}})
        self.assertEqual(["unchecked"], [x["severity"] for x in f])

    def test_order_inversion_and_off_path_are_warn(self):
        od = {"orch.py": {"verdict": "measured", "root": "main", "positions": {},
                          "inversions": [["target_allocation", "risk_gate"]],
                          "off_path": {"reporting": {"first": [1, 523], "function": "_r",
                                                     "calls": 1, "reason": ""}},
                          "unreached": []}}
        f = mod._findings({"edges": [], "role": {}, "order": od})
        self.assertEqual(["warn", "warn"], [x["severity"] for x in f])
        self.assertIn("«Target Allocation» после «Risk Gate»", f[0]["text"])
        self.assertIn("Reporting", f[1]["text"])
        self.assertIn("раннего выхода", f[1]["text"])

    def test_unmeasured_order_is_unchecked(self):
        od = {"orch.py": {"verdict": "unmeasured", "reason": "корня нет"}}
        f = mod._findings({"edges": [], "role": {}, "order": od})
        self.assertEqual(["unchecked"], [x["severity"] for x in f])

    def test_run_counts_hidden_sites_inversions_and_unmeasured_separately(self):
        orig_c, orig_m = mod.positive_control, mod.measure
        edge_ok = self._edge(hidden=["clamp"],
                             sites=[{"line": 3, "bound": ["res"], "callee": "clamp",
                                     "via": "", "stage": "", "kind": "hidden"}])
        edge_un = self._edge()
        edge_un["rewriters"] = {"verdict": "unmeasured", "reason": "r"}
        meas = {"role": {}, "readers": {}, "registry": {}, "entries": {},
                "edges": [edge_ok, edge_un],
                "order": {"orch.py": {"verdict": "measured", "root": "main",
                                      "positions": {}, "inversions": [["a", "b"]],
                                      "off_path": {"c": {}}, "unreached": []}}}
        try:
            mod.positive_control = lambda: {"passed": True, "checks": {"k1": True}}
            mod.measure = lambda *a, **k: meas
            with TemporaryDirectory() as td:
                doc = mod.run(root=td, write=False, now=_NOW)
        finally:
            mod.positive_control, mod.measure = orig_c, orig_m
        self.assertEqual(["clamp"], doc["hidden_stages"])
        self.assertEqual(1, doc["hidden_stage_sites"])
        self.assertEqual(1, doc["rewriters_unmeasured_edges"])
        self.assertEqual(1, doc["order_inversions"])
        self.assertEqual(1, doc["stages_off_path"])
        self.assertEqual("cio_component_map/v2", doc["schema"])
        self.assertEqual("CRITICAL", doc["overall"])

    def test_measure_marks_file_carrier_edges_not_applicable(self):
        """У файлового носителя переписчиков нет ПО ПОСТРОЕНИЮ — это не ноль и не unmeasured."""
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "spa_core" / "up").mkdir(parents=True)
            (root / "spa_core" / "up" / "__init__.py").write_text("")
            (root / "spa_core" / "up" / "a.py").write_text(
                "from spa_core.utils.atomic import atomic_save\n"
                "def run(d):\n    atomic_save({}, str(d / 'p.json'))\n")
            (root / "spa_core" / "up" / "b.py").write_text(
                "import json\ndef read(d):\n    return json.loads(open(str(d / 'p.json')).read())\n")
            stages = (
                mod.Stage("u", "U", "spa_core/up/a.py", "p.json", "artifact", entry=("run",)),
                mod.Stage("d", "D", "spa_core/up/b.py", "q.json", "artifact", entry=("read",)),
            )
            meas = mod.measure(root, stages)
        self.assertEqual("WIRED", meas["edges"][0]["verdict"])
        self.assertEqual("not_applicable", meas["edges"][0]["rewriters"]["verdict"])
        self.assertEqual({}, meas["order"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
