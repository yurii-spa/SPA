"""test_card_acceptance.py — положительные контроли к ADR-208.

Каждый тест воспроизводит ЛИБО настоящую аварию 2026-09-01 (три открытые карточки с
выполненным критерием), ЛИБО способ, которым сторож мог бы соврать. Проверка, никогда
не видевшая настоящей поломки, — украшение (.claude/rules/deployment.md).
"""
from __future__ import annotations

import os
import unittest

from spa_core.monitoring import card_acceptance as ca


def _card(tmp: str, name: str, *, status: str, probe: str | None = None,
          extra: str = "") -> str:
    fm = ["type: inbox", f'title: "проверочная карточка {name}"', f"status: {status}"]
    if probe is not None:
        fm.append(f"acceptance_probe: {probe}")
    if extra:
        fm.append(extra)
    path = os.path.join(tmp, f"{name}.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("---\n" + "\n".join(fm) + "\n---\n\n# тело\n")
    return path


class TestFrontmatter(unittest.TestCase):
    def test_quoted_and_bare_values_both_parse(self):
        fm = ca.parse_frontmatter('---\nstatus: new\ntitle: "в кавычках"\n---\nтело')
        self.assertEqual(fm["status"], "new")
        self.assertEqual(fm["title"], "в кавычках")

    def test_no_frontmatter_is_empty_not_a_crash(self):
        self.assertEqual(ca.parse_frontmatter("# просто заголовок"), {})


class TestProbeDispatch(unittest.TestCase):
    """Реестр — белый список. Всё незнакомое обязано давать «не измерено»."""

    def test_unregistered_probe_is_unmeasured_never_satisfied(self):
        verdict, detail = ca.run_probe("проба_которой_нет")
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("не зарегистрирована", detail)

    def test_probe_argument_that_is_not_a_key_is_refused(self):
        # Аргумент — ключ, не выражение: путь исполнения через текст карточки закрыт.
        verdict, detail = ca.run_probe("artifact_contract_confirmed:__import__('os').system('x')")
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("отвергнут", detail)

    def test_probe_that_raises_is_unmeasured_not_a_verdict(self):
        def boom(_arg):
            raise RuntimeError("производитель недоступен")
        ca.PROBES["_взрывается"] = boom
        try:
            verdict, detail = ca.run_probe("_взрывается")
        finally:
            del ca.PROBES["_взрывается"]
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("RuntimeError", detail)

    def test_probe_returning_junk_verdict_is_unmeasured(self):
        ca.PROBES["_врёт"] = lambda _a: ("всё хорошо", "")
        try:
            verdict, _ = ca.run_probe("_врёт")
        finally:
            del ca.PROBES["_врёт"]
        self.assertEqual(verdict, ca.UNMEASURED)

    def test_empty_spec_is_unmeasured(self):
        self.assertEqual(ca.run_probe("")[0], ca.UNMEASURED)

    def test_artifact_contract_probe_without_argument_refuses(self):
        verdict, detail = ca.run_probe("artifact_contract_confirmed")
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("нужен агент", detail)

    def test_artifact_contract_probe_on_unknown_agent_is_unmeasured(self):
        """Агента нет среди сверенных ⇒ предмет НЕ измерен. Это не «критерий не выполнен»:
        перепутав их, сторож объявил бы отсутствие данных отрицательным ответом."""
        verdict, detail = ca.run_probe("artifact_contract_confirmed:com.spa.no-such-agent")
        self.assertEqual(verdict, ca.UNMEASURED)
        self.assertIn("не измерен", detail)


class TestAudit(unittest.TestCase):
    """Авария 2026-09-01: карточка `new`, а её критерий выполнен."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        ca.PROBES["_всегда_выполнен"] = lambda _a: (ca.SATISFIED, "выполнено")
        ca.PROBES["_ещё_нет"] = lambda _a: (ca.NOT_SATISFIED, "не выполнено")

    def tearDown(self):
        self._tmp.cleanup()
        ca.PROBES.pop("_всегда_выполнен", None)
        ca.PROBES.pop("_ещё_нет", None)

    def test_open_card_with_satisfied_criterion_is_the_finding(self):
        _card(self.tmp, "открытая", status="new", probe="_всегда_выполнен")
        res = ca.audit(self.tmp)
        self.assertEqual(res["counts"]["satisfied_but_open"], 1)
        self.assertIn("КРИТЕРИЙ ВЫПОЛНЕН, а карточка открыта",
                      "\n".join(ca.report_lines(res)))

    def test_closed_card_with_satisfied_criterion_is_not_a_finding(self):
        _card(self.tmp, "закрытая", status="done", probe="_всегда_выполнен")
        res = ca.audit(self.tmp)
        self.assertEqual(res["counts"]["satisfied_but_open"], 0)

    def test_open_card_whose_criterion_is_not_met_stays_quiet(self):
        _card(self.tmp, "живая", status="in-progress", probe="_ещё_нет")
        res = ca.audit(self.tmp)
        self.assertEqual(res["counts"]["satisfied_but_open"], 0)
        self.assertEqual(res["counts"]["not_satisfied"], 1)

    def test_owner_question_is_never_probed(self):
        """Инвариант #14: вопрос владельцу не снимается измерением, и потому даже
        выполненный критерий не имеет права предъявить его как «можно закрыть»."""
        _card(self.tmp, "вопрос", status="needs-owner", probe="_всегда_выполнен")
        res = ca.audit(self.tmp)
        self.assertEqual(res["counts"]["declared"], 0)
        self.assertEqual(res["counts"]["satisfied_but_open"], 0)

    def test_card_without_a_probe_is_scanned_but_not_judged(self):
        _card(self.tmp, "без_пробы", status="new")
        res = ca.audit(self.tmp)
        self.assertEqual(res["scanned"], 1)
        self.assertEqual(res["counts"]["declared"], 0)

    def test_unmeasured_is_counted_and_named_separately(self):
        _card(self.tmp, "неизмеримая", status="new", probe="проба_которой_нет")
        res = ca.audit(self.tmp)
        self.assertEqual(res["counts"]["unmeasured"], 1)
        self.assertEqual(res["counts"]["satisfied_but_open"], 0)
        self.assertIn("[НЕ ИЗМЕРЕНО]", "\n".join(ca.report_lines(res)))

    def test_index_files_are_skipped(self):
        _card(self.tmp, "_BOARD", status="new", probe="_всегда_выполнен")
        self.assertEqual(ca.audit(self.tmp)["scanned"], 0)

    def test_missing_tracker_dir_is_zero_not_a_crash(self):
        res = ca.audit(os.path.join(self.tmp, "нет-каталога"))
        self.assertEqual(res["scanned"], 0)

    def test_report_never_stays_silent_when_no_probes_declared(self):
        """Молчание неотличимо от «всё сошлось» — состояние «проб нет» обязано звучать."""
        res = ca.audit(self.tmp)
        self.assertIn("проб не объявлено", "\n".join(ca.report_lines(res)))

    def test_exit_codes_are_fail_closed(self):
        _card(self.tmp, "неизмеримая", status="new", probe="проба_которой_нет")
        self.assertEqual(ca.main(["--tracker-dir", self.tmp]), 2)
        _card(self.tmp, "открытая", status="new", probe="_всегда_выполнен")
        self.assertEqual(ca.main(["--tracker-dir", self.tmp]), 1)


class TestWiredIntoTheOfficeStep(unittest.TestCase):
    """Ответ обязан ехать ТУДА, ГДЕ ПРИНИМАЕТСЯ РЕШЕНИЕ (урок ADR-207).
    Память, которую надо спрашивать отдельной командой, неотличима от её отсутствия."""

    def test_office_step_calls_the_audit(self):
        import ast
        import pathlib
        src = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "consume_office_reports.py"
        tree = ast.parse(src.read_text(encoding="utf-8"))
        # Проводка меряется ФОРМОЙ ВЫЗОВА, а не упоминанием имени: имя в комментарии
        # вызовом не является.
        calls = {
            f"{node.func.value.id}.{node.func.attr}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
        }
        self.assertIn("card_acceptance.audit", calls)
        self.assertIn("card_acceptance.report_lines", calls)


class TestRegisteredProbesAreReal(unittest.TestCase):
    """Проба, чей производитель переименовали, обязана падать в «не измерено»,
    а не молча исчезать из реестра."""

    def test_every_registered_probe_returns_a_known_verdict(self):
        for name in list(ca.PROBES):
            with self.subTest(probe=name):
                arg = "com.spa.daily_cycle" if name == "artifact_contract_confirmed" else None
                spec = f"{name}:{arg}" if arg else name
                verdict, detail = ca.run_probe(spec)
                self.assertIn(verdict, (ca.SATISFIED, ca.NOT_SATISFIED, ca.UNMEASURED))
                self.assertTrue(detail, f"проба {name} обязана объяснить свой вердикт")


if __name__ == "__main__":
    unittest.main()
