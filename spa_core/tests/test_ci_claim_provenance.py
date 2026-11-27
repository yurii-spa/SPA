"""Претензия о CI, не называющая прогон, обязана читаться как НЕОПРОВЕРЖИМАЯ.

# LLM_FORBIDDEN

Батарея устроена ПАРАМИ: у каждой оси есть сцена, где исход один, и сцена,
отличающаяся РОВНО этой осью, где исход ДРУГОЙ. Проверка «исход такой-то» без
обратной половины зелена и на приборе, который всегда отвечает одно и то же
(урок ADR-1060/1073: мутация без РАЗЛИЧАЮЩЕЙ сцены выживает).
"""
from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import ci_claim_provenance as mod

_ROOT = Path(__file__).resolve().parents[2]
_OFFICE = _ROOT / "scripts" / "consume_office_reports.py"

#: Дословная претензия, с которой класс найден (замер 27.11, цикл #1268).
INCIDENT = ("daily 90% audit 27.11: метрика 230/671=34,3%; флот 97,8%; "
            "CI control RED 140 имён (вчера 58), худший — f-string "
            "SyntaxError на py3.11 ×26")

#: Та же претензия, НАЗВАВШАЯ прогон. Отличается от `INCIDENT` ровно личностью.
NAMED = ("daily 90% audit 27.11: флот 97,8%; CI control 45967869368 RED 84 "
         "имён")


def _canon(run_id: str = "45967869368", failed: int = 84,
           worst=(("spa_core/tests/test_reachability_of_the_rest_wiring.py", 26),)):
    return {"run": {"id": int(run_id)}, "failed": failed,
            "red_census": {"worst": [list(w) for w in worst]}}


def _kind(line: str, **kw) -> str:
    seg = mod.claim_segments(line)
    assert seg, "маркер претензии не найден — сцена не собралась"
    return mod.classify_claim(seg[0]["segment"], line=line,
                              start=seg[0]["start"], **kw)["kind"]


def _write_log(dirpath: Path, records: list[dict], extra_lines=()) -> None:
    dirpath.mkdir(parents=True, exist_ok=True)
    with (dirpath / "session_changes.jsonl").open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        for raw in extra_lines:
            fh.write(raw + "\n")


class TheIdentityAxisDecides(unittest.TestCase):
    """Личность претензии — НОМЕР ПРОГОНА, и ось различает в обе стороны."""

    def test_a_number_without_a_run_is_unfalsifiable(self):
        self.assertEqual(_kind(INCIDENT, canonical=_canon()),
                         mod.UNFALSIFIABLE)

    def test_the_same_claim_naming_its_run_is_remeasured(self):
        # Обратная половина: отличие от сцены выше — РОВНО номер прогона.
        self.assertEqual(_kind(NAMED, canonical=_canon()), mod.COUNT_AGREES)

    def test_a_differing_count_is_a_finding_and_names_both_numbers(self):
        seg = mod.claim_segments(NAMED)[0]
        row = mod.classify_claim(seg["segment"], line=NAMED,
                                 start=seg["start"],
                                 canonical=_canon(failed=59))
        self.assertEqual(row["kind"], mod.COUNT_DIFFERS)
        self.assertIn("84", row["reason"])
        self.assertIn("59", row["reason"])

    def test_a_run_id_outside_the_segment_does_not_make_it_remeasurable(self):
        # Форма аварии: номер в строке ЕСТЬ, но он о ДРУГОМ предмете (здесь —
        # заказанный прогон соседней фразы). Догадка была бы ошибкой в сторону
        # «чисто».
        line = ("контрольный прогон 45967869368 заказан; CI control RED 140 "
                "имён")
        seg = [s for s in mod.claim_segments(line)
               if s["mark"].lower().startswith("ci")][0]
        row = mod.classify_claim(seg["segment"], line=line,
                                 start=seg["start"], canonical=_canon())
        self.assertEqual(row["kind"], mod.UNFALSIFIABLE)
        self.assertEqual(row["run_id_outside_segment"], ["45967869368"])
        self.assertIn("мимо сегмента", row["reason"])

    def test_a_run_id_in_a_LATER_clause_is_outside_the_segment_too(self):
        """Различающая половина к сцене выше: номер стоит ПОСЛЕ претензии.

        Без неё мутация «границу сегмента снять» выживает: в сцене выше номер
        стоял ДО маркера, и срез `summary[mark:]` его не захватывал ни с
        границей, ни без неё — проводка была зелена, а ОСЬ не спрашивалась
        ни разу (форма, названная заказом G1097 п. 5).
        """
        line = ("CI control RED 140 имён, худший — f-string ×26; контрольный "
                "прогон 45967869368 заказан")
        seg = [x for x in mod.claim_segments(line)
               if x["mark"].lower().startswith("ci")][0]
        self.assertNotIn("45967869368", seg["segment"])
        row = mod.classify_claim(seg["segment"], line=line,
                                 start=seg["start"], canonical=_canon())
        self.assertEqual(row["kind"], mod.UNFALSIFIABLE)
        self.assertEqual(row["run_ids"], [])

    def test_the_segment_starts_at_the_mark_not_at_the_line(self):
        """Срез начинается У МАРКЕРА: иначе претензии достаётся чужая фраза."""
        line = "контрольный прогон 45967869368 заказан; CI control RED 140"
        seg = [x for x in mod.claim_segments(line)
               if x["mark"].lower().startswith("ci")][0]
        self.assertTrue(seg["segment"].lower().startswith("ci control"))
        self.assertNotIn("45967869368", seg["segment"])

    def test_a_number_of_another_width_is_named_and_is_not_a_run_id(self):
        # Запись 27.10 несла `908015739` — это НЕ прогон (API отвечает 404),
        # и промолчать об этом значило бы оставить читателя в уверенности, что
        # прогон назван.
        line = "CI control на main 908015739 RED 68 failed/2 error"
        seg = mod.claim_segments(line)[0]
        row = mod.classify_claim(seg["segment"], line=line,
                                 start=seg["start"], canonical=_canon())
        self.assertEqual(row["kind"], mod.UNFALSIFIABLE)
        self.assertEqual(row["run_ids"], [])
        self.assertIn("908015739", row["reason"])


class TheCauseIsProseAndSaysSo(unittest.TestCase):
    """Совпавшее число не есть подтверждённая причина."""

    def test_named_run_with_a_cause_is_a_finding_even_when_the_count_agrees(self):
        line = ("CI control 45967869368 RED 84 имён, худший — f-string "
                "SyntaxError на py3.11 ×26")
        seg = mod.claim_segments(line)[0]
        row = mod.classify_claim(seg["segment"], line=line,
                                 start=seg["start"], canonical=_canon())
        self.assertEqual(row["kind"], mod.CAUSE_UNVERIFIED)
        self.assertIn(mod.CAUSE_UNVERIFIED, mod.FINDING_KINDS)
        self.assertIn("РОД", row["reason"])

    def test_the_same_claim_without_a_cause_is_not_a_finding(self):
        # Различающая половина: убрана РОВНО причинная часть.
        self.assertEqual(_kind(NAMED, canonical=_canon()), mod.COUNT_AGREES)
        self.assertNotIn(mod.COUNT_AGREES, mod.FINDING_KINDS)

    def test_the_cause_multiplicity_is_read_as_a_number(self):
        got = mod.read_claim("CI control RED 140 имён, худший — f-string ×26")
        self.assertEqual(got["count"], 140)
        self.assertEqual(got["cause_mult"], 26)
        self.assertIsNotNone(got["cause"])


class TheQuotationAxisDoesNotDoubleThePopulation(unittest.TestCase):
    """Цитата чужой претензии принадлежит ДРУГОЙ записи."""

    def test_a_quoted_claim_is_not_the_authors_claim(self):
        line = ("цикл #1270: разбираю сводку «CI control RED 140 имён, худший "
                "— f-string ×26» — число у канонического читателя другое")
        self.assertEqual(_kind(line, canonical=_canon()), mod.QUOTED)
        self.assertNotIn(mod.QUOTED, mod.FINDING_KINDS)

    def test_the_same_text_unquoted_is_a_finding(self):
        line = ("цикл #1270: разбираю сводку CI control RED 140 имён, худший "
                "— f-string ×26 — число у канонического читателя другое")
        self.assertEqual(_kind(line, canonical=_canon()), mod.UNFALSIFIABLE)

    def test_quotation_axis_is_not_asked_when_position_is_unknown(self):
        # Третий исход оси: положения нет (−1) ⇒ ось не спрашивается, и это
        # НАЗВАНО полем, а не выдано за «цитаты нет».
        seg = mod.claim_segments(INCIDENT)[0]
        row = mod.classify_claim(seg["segment"], line=INCIDENT,
                                 canonical=_canon())
        self.assertFalse(row["quoted"])
        self.assertEqual(row["kind"], mod.UNFALSIFIABLE)


class ThirdOutcomesAreDistinguishable(unittest.TestCase):
    """«Не измерено» — отдельное значение, а не ноль и не вердикт (инв. #17)."""

    def test_no_claim_is_not_a_finding(self):
        line = ("контрольный прогон 45967869368 заказан, вердикт НЕ ИЗМЕРЕН "
                "(читать следующему циклу)")
        self.assertEqual(_kind(line, canonical=_canon()), mod.NO_CLAIM)
        self.assertNotIn(mod.NO_CLAIM, mod.FINDING_KINDS)

    def test_a_run_outside_the_readers_window_is_unmeasured_not_agreement(self):
        row_kind = _kind(NAMED, canonical=_canon(run_id="45131349632",
                                                 failed=63))
        self.assertEqual(row_kind, mod.OUT_OF_WINDOW)
        self.assertIn(mod.OUT_OF_WINDOW, mod.UNMEASURED_KINDS)
        self.assertNotIn(mod.OUT_OF_WINDOW, mod.FINDING_KINDS)

    def test_an_unasked_canonical_reader_is_unmeasured_with_a_reason(self):
        seg = mod.claim_segments(NAMED)[0]
        row = mod.classify_claim(seg["segment"], line=NAMED,
                                 start=seg["start"], canonical=None,
                                 canonical_reason="сеть не спрашивалась")
        self.assertEqual(row["kind"], mod.NO_CANONICAL)
        self.assertIn("сеть не спрашивалась", row["reason"])

    def test_kind_sets_are_disjoint_and_declared(self):
        self.assertEqual(mod.FINDING_KINDS & mod.UNMEASURED_KINDS, frozenset())
        for k in mod.FINDING_KINDS | mod.UNMEASURED_KINDS:
            self.assertIn(k, mod.KINDS)

    def test_every_kind_the_classifier_can_return_is_declared(self):
        """Перечень родов сверяется с ИСХОДНИКОМ, а не с литералом рядом.

        Иначе мерка мерила бы сама себя: новый род, присвоенный в
        `classify_claim` и не объявленный в `KINDS`, прошёл бы молча и выпал
        бы из знаменателя отчёта.
        """
        src = Path(mod.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "classify_claim")
        assigned = set()
        for node in ast.walk(fn):
            if not isinstance(node, ast.Assign):
                continue
            for tgt in node.targets:
                if (isinstance(tgt, ast.Subscript)
                        and isinstance(tgt.slice, ast.Constant)
                        and tgt.slice.value == "kind"
                        and isinstance(node.value, ast.Name)):
                    assigned.add(node.value.id)
        self.assertTrue(assigned, "роды не разобраны — сцена не собралась")
        declared = {n for n in dir(mod) if n.isupper()}
        for name in assigned:
            self.assertIn(name, declared,
                          "род " + name + " присваивается, но не объявлен")
            self.assertIn(getattr(mod, name), mod.KINDS,
                          "род " + name + " не входит в KINDS")


class TheNamedDataDirReachesTheReader(unittest.TestCase):
    """Каталог — ВХОД, и выбор ПЕЧАТАЕТСЯ (урок ADR-1107/1108)."""

    def test_a_named_dir_is_read_and_printed_as_named(self):
        with TemporaryDirectory() as tmp:
            d = Path(tmp) / "data"
            _write_log(d, [{"ts": "t", "summary": INCIDENT}])
            doc = mod.run_census(data_dir=d, canonical=_canon())
            self.assertTrue(doc["data_dir_named"])
            self.assertEqual(doc["by_kind"][mod.UNFALSIFIABLE], 1)
            self.assertIn("НАЗВАН", "\n".join(mod.format_report(doc)))

    def test_a_missing_log_is_unmeasured_not_an_empty_population(self):
        with TemporaryDirectory() as tmp:
            doc = mod.run_census(data_dir=tmp, canonical=_canon())
            self.assertEqual(doc["status"], "UNMEASURED")
            self.assertEqual(doc["records"], 0)
            self.assertTrue(doc["unmeasured"])
            self.assertIn("НЕ ИЗМЕРЕНО", "\n".join(mod.format_report(doc)))

    def test_a_named_dir_that_is_not_a_dir_refuses_with_code_two(self):
        with TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "нет-такого")
            self.assertEqual(mod.main(["--data-dir", missing]), 2)

    def test_unreadable_lines_are_counted_and_named_not_dropped(self):
        with TemporaryDirectory() as tmp:
            d = Path(tmp) / "data"
            _write_log(d, [{"ts": "t", "summary": NAMED}],
                       extra_lines=["{не json", "[1, 2]"])
            doc = mod.run_census(data_dir=d, canonical=_canon())
            self.assertEqual(doc["unparsed_records"], 2)
            self.assertTrue(any("НЕ РАЗОБРАНО" in u for u in doc["unmeasured"]))

    def test_a_record_without_a_summary_does_not_crash(self):
        with TemporaryDirectory() as tmp:
            d = Path(tmp) / "data"
            _write_log(d, [{"ts": "t"}, {"ts": "u", "summary": INCIDENT}])
            doc = mod.run_census(data_dir=d, canonical=_canon())
            self.assertEqual(len(doc["claims"]), 1)


class EveryPrintedNumberHasAScene(unittest.TestCase):
    """Печатаемое число без сцены — форма, которую мутация переживает молча.

    Поэтому у КАЖДОГО числа отчёта есть пара сцен, различающихся ровно тем,
    что это число меряет.
    """

    def test_the_cause_subaxis_distinguishes_in_both_directions(self):
        with TemporaryDirectory() as tmp:
            with_cause = Path(tmp) / "a"
            _write_log(with_cause, [{"ts": "t", "summary": INCIDENT}])
            doc = mod.run_census(data_dir=with_cause, canonical=_canon())
            self.assertEqual(doc["unfalsifiable_with_cause"], 1)
            self.assertIn("РОД падения: 1", "\n".join(mod.format_report(doc)))

            no_cause = Path(tmp) / "b"
            _write_log(no_cause, [{"ts": "t", "summary":
                                   "CI control RED 140 имён (вчера 58)"}])
            doc2 = mod.run_census(data_dir=no_cause, canonical=_canon())
            self.assertEqual(doc2["by_kind"][mod.UNFALSIFIABLE], 1)
            self.assertEqual(doc2["unfalsifiable_with_cause"], 0)

    def test_the_population_equals_the_sum_of_kinds(self):
        # Иначе род, выпавший из `by_kind`, уменьшал бы знаменатель молча.
        with TemporaryDirectory() as tmp:
            d = Path(tmp) / "data"
            _write_log(d, [
                {"ts": "1", "summary": INCIDENT},
                {"ts": "2", "summary": NAMED},
                {"ts": "3", "summary": "контрольный прогон 45967869368 заказан"},
                {"ts": "4", "summary": "цикл: сводка «CI control RED 9 имён»"},
            ])
            doc = mod.run_census(data_dir=d, canonical=_canon())
            self.assertEqual(sum(doc["by_kind"].values()), len(doc["claims"]))
            self.assertEqual(len(doc["claims"]), 4)

    def test_two_claims_in_one_line_are_two_claims(self):
        line = ("CI control RED 7; контрольный прогон 45967869368 RED 84 имён")
        self.assertEqual(len(mod.claim_segments(line)), 2)


class ExitCodesSeparateTheThreeOutcomes(unittest.TestCase):
    def test_findings_give_one_and_a_clean_log_gives_zero(self):
        with TemporaryDirectory() as tmp:
            dirty = Path(tmp) / "dirty"
            _write_log(dirty, [{"ts": "t", "summary": INCIDENT}])
            self.assertEqual(mod.main(["--data-dir", str(dirty)]), 1)

            clean = Path(tmp) / "clean"
            _write_log(clean, [{"ts": "t", "summary":
                                "контрольный прогон 45967869368 заказан"}])
            self.assertEqual(mod.main(["--data-dir", str(clean)]), 0)


class TheCanonicalReaderIsADoorNotACopy(unittest.TestCase):
    """Своей копии разбора у прибора нет — читатель ОДИН."""

    def test_empty_stdout_is_a_reason_not_a_crash(self):
        class _R:
            stdout = ""
            returncode = 2
        doc, why = mod.canonical_verdict(_ROOT, runner=lambda: _R())
        self.assertIsNone(doc)
        self.assertIn("не отдал документ", why)

    def test_unparsable_stdout_is_a_reason(self):
        class _R:
            stdout = "не json"
            returncode = 0
        doc, why = mod.canonical_verdict(_ROOT, runner=lambda: _R())
        self.assertIsNone(doc)
        self.assertIn("не разобран", why)

    def test_a_raising_runner_is_a_reason(self):
        def _boom():
            raise OSError("сеть недоступна")
        doc, why = mod.canonical_verdict(_ROOT, runner=_boom)
        self.assertIsNone(doc)
        self.assertIn("OSError", why)

    def test_the_door_points_at_the_canonical_reader_by_path(self):
        src = Path(mod.__file__).read_text(encoding="utf-8")
        self.assertIn("ci_control_verdict.py", src)


class TheOfficeStepActuallyCallsTheProber(unittest.TestCase):
    """Сторож, которого никто не зовёт, — файл, а не сторож.

    Вопрос задаётся AST, а не подстрокой (ADR-333): упоминание имени в
    докстроке соседа проводкой не является.
    """

    def test_the_office_step_imports_and_calls_the_census(self):
        tree = ast.parse(_OFFICE.read_text(encoding="utf-8"))
        imported = any(
            isinstance(n, ast.ImportFrom)
            and (n.module or "").endswith("ci_claim_provenance")
            for n in ast.walk(tree))
        self.assertTrue(imported, "шаг 0-офис не ввозит прибор")
        called = {n.func.id for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertTrue({"_cicp_census", "_cicp_report"} <= called,
                        "шаг 0-офис ввозит прибор, но не зовёт его")


if __name__ == "__main__":
    unittest.main()
