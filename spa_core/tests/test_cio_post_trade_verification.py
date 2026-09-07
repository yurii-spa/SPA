"""Тесты §5 ТЗ CIO — последняя ступень цепи (post-trade verification).

Литеральных дат здесь НЕТ намеренно (приём №2 `.claude/rules/deployment.md`):
модуль сравнивает две отметки, ПРИШЕДШИЕ ИЗ ФАЙЛОВ, и стенных часов в его
суждении не участвует вовсе — поэтому фикстуры выражены возрастом
(`_freshness.ts`), и календарь на вердикт повлиять не может. Пометка
`FROZEN-DATE-OK` не нужна не потому, что «мы решили не ставить», а потому что
файл в класс не входит: проверено отсутствием литералов, а не намерением.
"""
from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import cio_post_trade_verification as m
from spa_core.tests._freshness import ts


# ─────────────────────────────── сцены ───────────────────────────────────────

def _tree(base: Path, *, resulting: str = "dict(target)",
          trades: list | None = None, artifact: dict | None = None,
          book: dict | None = None, caller: str | None = None) -> Path:
    """Собрать дерево-сцену: два модуля сверки, вызыватель, данные."""
    base.mkdir(parents=True, exist_ok=True)
    (base / "data").mkdir(exist_ok=True)
    (base / "spa_core" / "execution").mkdir(parents=True, exist_ok=True)
    (base / "spa_core" / "paper_trading").mkdir(parents=True, exist_ok=True)
    (base / "scripts").mkdir(exist_ok=True)

    (base / "spa_core/execution/reconciliation.py").write_text(
        "def reconcile(target, resulting, nav_before):\n"
        "    return {'matches_target': target == resulting}\n", encoding="utf-8")
    (base / "spa_core/paper_trading/pre_cutover_gate.py").write_text(
        "def nav_reconcile(target, resulting):\n"
        "    return {'matches_target': target == resulting}\n", encoding="utf-8")

    if caller is None:
        caller = (
            "from spa_core.execution.reconciliation import reconcile\n"
            "\n"
            "def load(path):\n"
            "    return {}\n"
            "\n"
            "def go(allocation, path):\n"
            "    target = dict(allocation)\n"
            f"    resulting = {resulting}\n"
            "    return reconcile(target, resulting, 100.0)\n")
    (base / "scripts/caller.py").write_text(caller, encoding="utf-8")

    if trades is None:
        trades = [{"trade_id": "T1", "ts": ts(hours_ago=100.0),
                   "is_demo": False, "diff_usd": 500.0}]
    (base / "data/trades.json").write_text(json.dumps(trades), encoding="utf-8")

    if book is None:
        book = {"generated_at": ts(hours_ago=1.0), "deployed_usd": 100.0,
                "positions_detail": {"aave_v3": {"usd": 100.0}}}
    (base / "data/current_positions.json").write_text(
        json.dumps(book), encoding="utf-8")

    if artifact is not None:
        (base / "data/execution_reconciliation.json").write_text(
            json.dumps(artifact), encoding="utf-8")
    return base


def _artifact(*, hours_ago: float = 500.0, positions: dict | None = None) -> dict:
    return {"generated_at": ts(hours_ago=hours_ago), "n_trades": 0,
            "matches_target": True, "go_live_ready": True,
            "nav_before_usd": 50.0,
            "resulting_positions": positions
            if positions is not None else {"euler_v2": 50.0}}


def _prov(tree: Path) -> str:
    got = m.measure_inputs(tree)
    prod = [s for s in got["sites"] if not s["is_test"]]
    return prod[0]["provenance"] if prod else "НЕТ ВЫЗОВА"


def _ident(tree: Path) -> str:
    got = m.measure_inputs(tree)
    prod = [s for s in got["sites"] if not s["is_test"]]
    if prod:
        return prod[0]["identity"]
    return got["shadowed"][0]["identity"] if got["shadowed"] else "НЕТ ВЫЗОВА"


class TestProvenance(unittest.TestCase):
    """Происхождение второго аргумента сверки."""

    def test_copy_of_target_is_self(self):
        with TemporaryDirectory() as td:
            t = _tree(Path(td) / "a", resulting="dict(target)")
            self.assertEqual(m.PROV_SELF, _prov(t))

    def test_bare_target_is_self(self):
        with TemporaryDirectory() as td:
            t = _tree(Path(td) / "a", resulting="target")
            self.assertEqual(m.PROV_SELF, _prov(t))

    def test_origin_is_traced_through_a_chain_of_assignments(self):
        """`resulting = step["k"]`, где step собран из target тремя строками выше.

        Это форма настоящего производителя (`golive_dry_run`): без слежения до
        неподвижной точки она выглядела бы независимой от цели.
        """
        caller = (
            "from spa_core.execution.reconciliation import reconcile\n"
            "def plan(a, b):\n"
            "    return []\n"
            "def apply(a, b):\n"
            "    return {'resulting_positions': a}\n"
            "def go(allocation):\n"
            "    target = dict(allocation)\n"
            "    current = {}\n"
            "    trades = plan(current, target)\n"
            "    step = apply(current, trades)\n"
            "    resulting = step['resulting_positions']\n"
            "    return reconcile(target, resulting, 1.0)\n")
        with TemporaryDirectory() as td:
            t = _tree(Path(td) / "a", caller=caller)
            self.assertEqual(m.PROV_SELF, _prov(t))

    def test_observed_outcome_is_not_a_finding(self):
        """ОБРАТНАЯ половина: сверка с наблюдением не смеет объявляться находкой."""
        with TemporaryDirectory() as td:
            t = _tree(Path(td) / "a", resulting="load(path)")
            self.assertEqual(m.PROV_OBSERVED, _prov(t))

    def test_observed_by_name_is_recognised(self):
        caller = (
            "from spa_core.execution.reconciliation import reconcile\n"
            "def go(allocation, observed_positions):\n"
            "    target = dict(allocation)\n"
            "    return reconcile(target, observed_positions, 1.0)\n")
        with TemporaryDirectory() as td:
            t = _tree(Path(td) / "a", caller=caller)
            self.assertEqual(m.PROV_OBSERVED, _prov(t))

    def test_dict_literal_is_literal(self):
        caller = (
            "from spa_core.execution.reconciliation import reconcile\n"
            "def go(allocation):\n"
            "    target = dict(allocation)\n"
            "    return reconcile(target, {'aave_v3': 1.0}, 1.0)\n")
        with TemporaryDirectory() as td:
            t = _tree(Path(td) / "a", caller=caller)
            self.assertEqual(m.PROV_LITERAL, _prov(t))

    def test_too_few_positional_args_is_unchecked_not_a_pass(self):
        caller = (
            "from spa_core.execution.reconciliation import reconcile\n"
            "def go(target):\n"
            "    return reconcile(target)\n")
        with TemporaryDirectory() as td:
            t = _tree(Path(td) / "a", caller=caller)
            self.assertEqual(m.PROV_UNCHECKED, _prov(t))


class TestIdentity(unittest.TestCase):
    """Та ли это функция — или просто СОВПАЛО ИМЯ (ложные срабатывания #517)."""

    def test_same_name_different_function_is_dropped(self):
        """`reconcile(floor, ceiling)` про часы SLO предметом замера не является."""
        caller = (
            "def reconcile(floor, ceiling):\n"
            "    return ceiling\n"
            "def go(a, b):\n"
            "    return reconcile(a, b)\n")
        with TemporaryDirectory() as td:
            t = _tree(Path(td) / "a", caller=caller)
            got = m.measure_inputs(t)
            self.assertEqual([], [s for s in got["sites"] if not s["is_test"]])
            self.assertEqual("shadowed", got["shadowed"][0]["identity"])

    def test_call_through_a_module_alias_is_OUR_function(self):
        """ОБРАТНАЯ половина: `rc.reconcile(...)` — настоящий вызов, не совпадение.

        Первая редакция знала одну форму ввоза и объявила «совпадением имени»
        51 настоящий вызов. Отброшенное обязано быть чужим, а не своим.
        """
        caller = (
            "from spa_core.execution import reconciliation as rc\n"
            "def go(allocation):\n"
            "    target = dict(allocation)\n"
            "    return rc.reconcile(target, dict(target), 1.0)\n")
        with TemporaryDirectory() as td:
            t = _tree(Path(td) / "a", caller=caller)
            self.assertEqual("imported", _ident(t))
            self.assertEqual(m.PROV_SELF, _prov(t))

    def test_definition_inside_its_own_module_is_own(self):
        with TemporaryDirectory() as td:
            t = _tree(Path(td) / "a")
            (t / "spa_core/execution/reconciliation.py").write_text(
                "def reconcile(target, resulting, nav_before):\n"
                "    return {}\n"
                "def run(current):\n"
                "    target = dict(current)\n"
                "    return reconcile(target, dict(target), 1.0)\n",
                encoding="utf-8")
            got = m.measure_inputs(t)
            own = [s for s in got["sites"]
                   if s["file"] == "spa_core/execution/reconciliation.py"]
            self.assertEqual(1, len(own))
            self.assertEqual("own", own[0]["identity"])

    def test_import_and_own_definition_is_ambiguous_not_a_guess(self):
        caller = (
            "from spa_core.execution.reconciliation import reconcile\n"
            "def reconcile(a, b):\n"
            "    return a\n"
            "def go(t):\n"
            "    return reconcile(t, dict(t))\n")
        with TemporaryDirectory() as td:
            t = _tree(Path(td) / "a", caller=caller)
            self.assertEqual("ambiguous", _ident(t))
            self.assertEqual(m.PROV_UNCHECKED, _prov(t))


class TestSubject(unittest.TestCase):
    """Вопрос 1: есть ли что верифицировать."""

    def test_moves_present(self):
        with TemporaryDirectory() as td:
            t = _tree(Path(td) / "a")
            s = m.measure_subject(t)
            self.assertEqual("SUBJECT_EXISTS", s["verdict"])
            self.assertEqual(1, s["moves"])

    def test_empty_track_is_no_subject_and_that_is_a_full_answer(self):
        with TemporaryDirectory() as td:
            t = _tree(Path(td) / "a", trades=[])
            s = m.measure_subject(t)
            self.assertEqual("NO_SUBJECT", s["verdict"])

    def test_demo_moves_do_not_count_as_subject(self):
        with TemporaryDirectory() as td:
            t = _tree(Path(td) / "a", trades=[
                {"trade_id": "D1", "ts": ts(hours_ago=10.0),
                 "is_demo": True, "diff_usd": 1.0}])
            s = m.measure_subject(t)
            self.assertEqual("NO_SUBJECT", s["verdict"])
            self.assertEqual(1, s["moves_demo_skipped"])

    def test_missing_journal_is_unchecked_not_no_subject(self):
        with TemporaryDirectory() as td:
            t = _tree(Path(td) / "a")
            (t / "data/trades.json").unlink()
            self.assertEqual(m.PROV_UNCHECKED, m.measure_subject(t)["verdict"])

    def test_wrong_shape_is_unchecked(self):
        with TemporaryDirectory() as td:
            t = _tree(Path(td) / "a")
            (t / "data/trades.json").write_text("42", encoding="utf-8")
            self.assertEqual(m.PROV_UNCHECKED, m.measure_subject(t)["verdict"])

    def test_both_senses_of_execution_are_named(self):
        """Смысл ОБЪЯВЛЕН данными — иначе «исполнения нет» звучало бы полным ответом."""
        with TemporaryDirectory() as td:
            s = m.measure_subject(_tree(Path(td) / "a"))
            self.assertEqual({"onchain", "paper_book"}, set(s["senses"]))
            self.assertEqual("paper_book", s["verifies_sense"])


class TestStage(unittest.TestCase):
    """Вопрос 2а: ступень §46 и её продукт."""

    def test_artifact_read(self):
        with TemporaryDirectory() as td:
            t = _tree(Path(td) / "a", artifact=_artifact())
            st = m.measure_stage(t)
            self.assertEqual("OK", st["verdict"])
            self.assertEqual({"euler_v2": 50.0}, st["book_in_artifact"])

    def test_missing_artifact_is_unchecked_not_clean(self):
        with TemporaryDirectory() as td:
            t = _tree(Path(td) / "a")
            self.assertEqual(m.PROV_UNCHECKED, m.measure_stage(t)["verdict"])

    def test_stage_composition_comes_from_the_map_not_a_local_copy(self):
        """§3 ТЗ: не заводить параллельную модель — состав берётся из §46."""
        from spa_core.monitoring.cio_component_map import STAGES
        stage = next(s for s in STAGES if s.key == m.STAGE_KEY)
        with TemporaryDirectory() as td:
            t = _tree(Path(td) / "a", artifact=_artifact())
            st = m.measure_stage(t)
            self.assertEqual(stage.module, st["module"])
            self.assertEqual(f"data/{stage.product}", st["artifact"])


class TestContent(unittest.TestCase):
    """Вопрос 3: книга артефакта против сегодняшней."""

    def test_divergence_named_position_by_position(self):
        with TemporaryDirectory() as td:
            t = _tree(Path(td) / "a", artifact=_artifact())
            c = m.measure_content(t, m.measure_stage(t))
            self.assertEqual("DIVERGED", c["verdict"])
            self.assertEqual(["euler_v2"], c["gone"])
            self.assertEqual(["aave_v3"], c["new"])

    def test_identical_book_is_ok(self):
        with TemporaryDirectory() as td:
            t = _tree(Path(td) / "a",
                      artifact=_artifact(positions={"aave_v3": 100.0}))
            c = m.measure_content(t, m.measure_stage(t))
            self.assertEqual("OK", c["verdict"])

    def test_moves_after_the_artifact_are_counted(self):
        with TemporaryDirectory() as td:
            t = _tree(Path(td) / "a", artifact=_artifact(hours_ago=500.0),
                      trades=[{"trade_id": "T1", "ts": ts(hours_ago=600.0),
                               "is_demo": False, "diff_usd": 1.0},
                              {"trade_id": "T2", "ts": ts(hours_ago=100.0),
                               "is_demo": False, "diff_usd": 2.0}])
            c = m.measure_content(t, m.measure_stage(t))
            self.assertEqual(1, c["moves_after_artifact"])

    def test_unparsable_book_is_unchecked(self):
        with TemporaryDirectory() as td:
            t = _tree(Path(td) / "a", artifact=_artifact(),
                      book={"generated_at": ts(), "positions_detail": {}})
            c = m.measure_content(t, m.measure_stage(t))
            self.assertEqual(m.PROV_UNCHECKED, c["verdict"])


class TestFindings(unittest.TestCase):
    """Гейтинг находок — главное свойство: находка только при наличии предмета."""

    def _run(self, tree: Path) -> dict:
        return m.run(root=tree, write=False)

    def test_never_asked_about_reality_fires(self):
        with TemporaryDirectory() as td:
            t = _tree(Path(td) / "a", artifact=_artifact())
            codes = [f["code"] for f in self._run(t)["findings"]]
            self.assertIn("NEVER_ASKED_ABOUT_REALITY", codes)

    def test_observed_input_removes_the_critical(self):
        """ОБРАТНАЯ половина: подали наблюдение — главной находки быть не должно."""
        with TemporaryDirectory() as td:
            t = _tree(Path(td) / "a", resulting="load(path)",
                      artifact=_artifact())
            codes = [f["code"] for f in self._run(t)["findings"]]
            self.assertNotIn("NEVER_ASKED_ABOUT_REALITY", codes)
            self.assertIn("OBSERVED_INPUT_EXISTS", codes)

    def test_empty_track_gives_no_staleness_finding(self):
        """ОБРАТНАЯ половина: нет предмета — возраст артефакта не находка."""
        with TemporaryDirectory() as td:
            t = _tree(Path(td) / "a", trades=[], artifact=_artifact())
            codes = [f["code"] for f in self._run(t)["findings"]]
            self.assertNotIn("STALE_VS_EXECUTIONS", codes)
            self.assertIn("NO_SUBJECT", codes)

    def test_staleness_fires_when_a_subject_exists(self):
        with TemporaryDirectory() as td:
            t = _tree(Path(td) / "a", artifact=_artifact(hours_ago=500.0),
                      trades=[{"trade_id": "T1", "ts": ts(hours_ago=10.0),
                               "is_demo": False, "diff_usd": 7.0}])
            codes = [f["code"] for f in self._run(t)["findings"]]
            self.assertIn("STALE_VS_EXECUTIONS", codes)

    def test_no_call_sites_is_unchecked_not_ok(self):
        with TemporaryDirectory() as td:
            t = _tree(Path(td) / "a", artifact=_artifact())
            (t / "scripts/caller.py").unlink()
            codes = [f["code"] for f in self._run(t)["findings"]]
            self.assertIn("NO_CALL_SITES", codes)


class TestReport(unittest.TestCase):
    """Форма отчёта и проводка положительного контроля."""

    def test_positive_control_passes_on_the_real_tree(self):
        self.assertTrue(m.positive_control()["passed"])

    def test_control_has_inverse_halves(self):
        """Контроль, который только НАХОДИТ, проходит и у штампа (урок #515)."""
        names = [c["name"] for c in m.positive_control()["checks"]]
        self.assertTrue(any("НЕ является" in n for n in names))
        self.assertTrue(any("НЕ даёт" in n for n in names))

    def test_failed_control_makes_the_whole_report_unchecked(self):
        """ПРОВОДКА: ослепим контроль — вердикт обязан пойти за ним."""
        orig = m.positive_control
        try:
            m.positive_control = lambda: {"passed": False, "checks": []}
            with TemporaryDirectory() as td:
                t = _tree(Path(td) / "a", artifact=_artifact())
                self.assertEqual("UNCHECKED", m.run(root=t, write=False)["overall"])
        finally:
            m.positive_control = orig

    def test_now_is_an_input(self):
        """`now` доходит до отчёта. Якорь СЧИТАН, а не записан литералом.

        Литеральная дата здесь была бы ровно тем классом, против которого стои́т
        `test_frozen_date_ratchet` — и он её поймал. Предмет теста «значение
        аргумента доехало до поля», а НЕ конкретная дата: любой якорь отвечает
        на этот вопрос одинаково, поэтому литерал не нужен вовсе.
        """
        from datetime import timedelta
        from spa_core.tests._freshness import now_utc
        anchor = (now_utc() + timedelta(days=365)).replace(microsecond=0)
        with TemporaryDirectory() as td:
            t = _tree(Path(td) / "a", artifact=_artifact())
            doc = m.run(root=t, write=False, now=anchor)
            self.assertEqual(anchor.isoformat(), doc["generated_at"])

    def test_write_false_writes_nothing(self):
        with TemporaryDirectory() as td:
            t = _tree(Path(td) / "a", artifact=_artifact())
            m.run(root=t, write=False)
            self.assertFalse((t / m.REPORT_REL).exists())

    def test_write_true_writes_the_artifact(self):
        with TemporaryDirectory() as td:
            t = _tree(Path(td) / "a", artifact=_artifact())
            m.run(root=t, write=True)
            doc = json.loads((t / m.REPORT_REL).read_text(encoding="utf-8"))
            self.assertEqual("cio_post_trade_verification/v1", doc["schema"])

    def test_measurer_excludes_itself(self):
        """Сторож, читающий свой корпус, находит себя (урок ADR-253 №4).

        Сцена НАСТОЯЩАЯ: в дерево кладётся файл с именем измерителя, и он
        СОДЕРЖИТ вызов сверки. Первая редакция этого теста спрашивала о живом
        дереве, где у измерителя вызовов нет вовсе, — и проходила одинаково
        со сторожем и без него (украшение, пойманное харнессом мутаций).
        """
        with TemporaryDirectory() as td:
            t = _tree(Path(td) / "a", artifact=_artifact())
            (t / "spa_core/monitoring").mkdir(parents=True, exist_ok=True)
            (t / "spa_core/monitoring/cio_post_trade_verification.py").write_text(
                "from spa_core.execution.reconciliation import reconcile\n"
                "def probe(target):\n"
                "    return reconcile(target, dict(target), 1.0)\n",
                encoding="utf-8")
            files = [s["file"] for s in m.measure_inputs(t)["sites"]]
            self.assertNotIn(
                "spa_core/monitoring/cio_post_trade_verification.py", files)
            # И контроль на саму сцену: без исключения вызов был бы виден —
            # тот же файл под другим именем в тех же условиях находится.
            (t / "spa_core/monitoring/other_probe.py").write_text(
                "from spa_core.execution.reconciliation import reconcile\n"
                "def probe(target):\n"
                "    return reconcile(target, dict(target), 1.0)\n",
                encoding="utf-8")
            files = [s["file"] for s in m.measure_inputs(t)["sites"]]
            self.assertIn("spa_core/monitoring/other_probe.py", files)

    def test_advisory_is_stated(self):
        with TemporaryDirectory() as td:
            t = _tree(Path(td) / "a", artifact=_artifact())
            self.assertIn("money-path", m.run(root=t, write=False)["advisory"])


class TestNoLiteralDates(unittest.TestCase):
    """Собственный контроль на класс «литеральная дата» (без пометки-обещания)."""

    def test_this_file_holds_no_literal_date_in_either_spelling(self):
        """ОБЕ формы, а не одна.

        Первая редакция знала только строковую форму (ISO в кавычках) и
        пропустила вызов конструктора с литеральным годом — храповик поймал
        файл, а этот тест молчал, то есть отвечал на СВОЙ вопрос честно и не на
        нужный. Формы две, и сторож обязан знать обе.

        Примеры форм здесь НЕ приводятся намеренно: пример литеральной даты в
        тексте сторожа — сам литеральная дата, и он отравил бы собственный
        корпус. Ровно на этом тест и храповик покраснели оба.
        """
        import re
        src = Path(__file__).read_text(encoding="utf-8")
        self.assertEqual([], re.findall(r'"20\d\d-\d\d-\d\d', src),
                         "строковый литерал даты")
        self.assertEqual([], re.findall(r'datetime\(\s*\d{4}\s*,', src),
                         "конструктор datetime с литеральным годом")

    def test_module_under_test_parses(self):
        src = Path(m.__file__).read_text(encoding="utf-8")
        self.assertTrue(ast.parse(src).body)


if __name__ == "__main__":
    unittest.main()
