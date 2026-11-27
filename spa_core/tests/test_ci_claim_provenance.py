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


def _EMPTY_TREE(tmp) -> str:
    """Дерево контента БЕЗ носителей — вход сцены, а не окружение.

    Сцены announce-лога обязаны быть герметичными: без названного дерева
    `run_census` читает ЖИВЫЕ карточки и журналы репозитория, и вердикт
    сцены начинает зависеть от того, что кто-то вчера записал в журнал, —
    та же бомба, что литеральная дата и литеральный pid, только от третьего
    счётчика (`.claude/rules/deployment.md`).
    """
    tree = Path(tmp) / "пустое-дерево-контента"
    tree.mkdir(exist_ok=True)
    return str(tree)


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
            doc = mod.run_census(data_dir=d, canonical=_canon(),
                                 carrier_root=_EMPTY_TREE(tmp))
            self.assertTrue(doc["data_dir_named"])
            self.assertEqual(doc["by_kind"][mod.UNFALSIFIABLE], 1)
            self.assertIn("НАЗВАН", "\n".join(mod.format_report(doc)))

    def test_a_missing_log_is_unmeasured_not_an_empty_population(self):
        with TemporaryDirectory() as tmp:
            doc = mod.run_census(data_dir=tmp, canonical=_canon(),
                                 carrier_root=_EMPTY_TREE(tmp))
            self.assertEqual(doc["status"], "UNMEASURED")
            self.assertEqual(doc["records"], 0)
            self.assertTrue(doc["unmeasured"])
            self.assertIn("НЕ ИЗМЕРЕНО", "\n".join(mod.format_report(doc)))

    def test_a_named_dir_that_is_not_a_dir_refuses_with_code_two(self):
        with TemporaryDirectory() as tmp:
            missing = str(Path(tmp) / "нет-такого")
            self.assertEqual(mod.main(["--data-dir", missing,
                                      "--carrier-root", _EMPTY_TREE(tmp)]), 2)

    def test_unreadable_lines_are_counted_and_named_not_dropped(self):
        with TemporaryDirectory() as tmp:
            d = Path(tmp) / "data"
            _write_log(d, [{"ts": "t", "summary": NAMED}],
                       extra_lines=["{не json", "[1, 2]"])
            doc = mod.run_census(data_dir=d, canonical=_canon(),
                                 carrier_root=_EMPTY_TREE(tmp))
            self.assertEqual(doc["unparsed_records"], 2)
            self.assertTrue(any("НЕ РАЗОБРАНО" in u for u in doc["unmeasured"]))

    def test_a_record_without_a_summary_does_not_crash(self):
        with TemporaryDirectory() as tmp:
            d = Path(tmp) / "data"
            _write_log(d, [{"ts": "t"}, {"ts": "u", "summary": INCIDENT}])
            doc = mod.run_census(data_dir=d, canonical=_canon(),
                                 carrier_root=_EMPTY_TREE(tmp))
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
            doc = mod.run_census(data_dir=with_cause, canonical=_canon(),
                                 carrier_root=_EMPTY_TREE(tmp))
            self.assertEqual(doc["unfalsifiable_with_cause"], 1)
            self.assertIn("РОД падения: 1", "\n".join(mod.format_report(doc)))

            no_cause = Path(tmp) / "b"
            _write_log(no_cause, [{"ts": "t", "summary":
                                   "CI control RED 140 имён (вчера 58)"}])
            doc2 = mod.run_census(data_dir=no_cause, canonical=_canon(),
                                  carrier_root=_EMPTY_TREE(tmp))
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
            doc = mod.run_census(data_dir=d, canonical=_canon(),
                                 carrier_root=_EMPTY_TREE(tmp))
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
            self.assertEqual(mod.main(["--data-dir", str(dirty),
                                      "--carrier-root", _EMPTY_TREE(tmp)]), 1)

            clean = Path(tmp) / "clean"
            _write_log(clean, [{"ts": "t", "summary":
                                "контрольный прогон 45967869368 заказан"}])
            self.assertEqual(mod.main(["--data-dir", str(clean),
                                      "--carrier-root", _EMPTY_TREE(tmp)]), 0)


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


#: Претензия без личности в markdown-носителе: число есть, прогона нет.
MD_CLAIM = ("контрольный прогон CI `main` **RED** (failed=67 из 137 166) — "
            "состав не читался")


class AMarkdownRecordIsTheAuthoredUnit(unittest.TestCase):
    """Запись markdown — ни строка, ни файл, и обе ошибки идут в РАЗНЫЕ стороны.

    Пары здесь различают именно ЭТО: перенос строки склеивается (иначе номер
    и число разъехались бы, и перемеряемая претензия числилась бы находкой),
    а новый пункт списка НЕ склеивается (иначе номер из соседнего пункта дал
    бы претензии чужую личность).
    """

    def test_a_hard_wrapped_sentence_is_one_record(self):
        text = ("контрольный прогон CI RED 67 упавших на прогоне\n"
                "45967869368 — состав прочитан\n")
        recs = mod.markdown_records(text)
        self.assertEqual(len(recs), 1)
        self.assertIn("45967869368", recs[0]["text"])

    def test_two_list_items_are_two_records(self):
        text = ("- контрольный прогон CI RED 67 упавших\n"
                "- прогон 45967869368 заказан\n")
        recs = mod.markdown_records(text)
        self.assertEqual(len(recs), 2)
        self.assertNotIn("45967869368", recs[0]["text"])

    def test_the_wrap_and_the_item_differ_in_the_verdict_not_only_in_shape(self):
        """Та же пара, но мерится ВЕРДИКТОМ: форма без исхода ничего не держит."""
        wrapped = ("контрольный прогон CI RED 67 упавших на прогоне\n"
                   "45967869368 — состав прочитан\n")
        split = ("- контрольный прогон CI RED 67 упавших\n"
                 "- прогон 45967869368 заказан\n")

        def kinds(text):
            out = []
            for rec in mod.markdown_records(text):
                for seg in mod.claim_segments(rec["text"]):
                    out.append(mod.classify_claim(
                        seg["segment"], line=rec["text"], start=seg["start"],
                        canonical=_canon(), markup=True,
                        fenced=rec["fenced"], blockquote=rec["blockquote"])["kind"])
            return out

        self.assertNotIn(mod.UNFALSIFIABLE, kinds(wrapped))
        self.assertIn(mod.UNFALSIFIABLE, kinds(split))

    def test_a_table_row_is_its_own_record(self):
        text = ("| шаг | что сказал |\n"
                "|---|---|\n"
                "| 0-офис | контрольный прогон CI RED 67 |\n"
                "| 1в | прогон 45967869368 зелёный |\n")
        recs = mod.markdown_records(text)
        self.assertEqual(len(recs), 4)
        row = next(r for r in recs if "RED 67" in r["text"])
        self.assertNotIn("45967869368", row["text"])

    def test_a_fence_is_one_record_and_is_marked(self):
        text = ("```\n"
                "CI control RED 140 имён\n"
                "\n"
                "худший — f-string ×26\n"
                "```\n")
        recs = mod.markdown_records(text)
        self.assertEqual(len(recs), 1, "пустая строка разорвала ограду")
        self.assertTrue(recs[0]["fenced"])

    def test_the_same_text_without_a_fence_is_not_marked(self):
        recs = mod.markdown_records("CI control RED 140 имён\n")
        self.assertEqual(len(recs), 1)
        self.assertFalse(recs[0]["fenced"])

    def test_a_blockquote_line_is_marked(self):
        recs = mod.markdown_records("> CI control RED 140 имён\n")
        self.assertTrue(recs[0]["blockquote"])
        self.assertFalse(mod.markdown_records("CI control RED 140\n")[0]["blockquote"])


class QuotationInMarkdownHasFourFormsNotOne(unittest.TestCase):
    """«…» — лишь ОДНА из форм пересказа; у каждой есть различающая пара."""

    def _kind(self, text, **kw):
        seg = mod.claim_segments(text)
        self.assertTrue(seg, "маркер не найден — сцена не собралась")
        return mod.classify_claim(seg[0]["segment"], line=text,
                                  start=seg[0]["start"], canonical=_canon(),
                                  **kw)["kind"]

    def test_inline_code_covering_the_whole_claim_is_a_quotation(self):
        # Дословная форма из `docs/journal/2026-W48.md`: разбор ADR-1124
        # цитирует строку аудита вставкой кода.
        text = ("Аудит доложил `CI control RED 140 имён, худший — f-string "
                "SyntaxError на py3.11 ×26`. Канонический читатель: 84")
        self.assertEqual(self._kind(text, markup=True), mod.QUOTED)

    def test_inline_code_covering_only_a_term_is_not_a_quotation(self):
        # Отличается РОВНО тем, что вставка кода накрывает `main`, а не
        # претензию: без этого различения ось объявила бы цитатой пол-журнала.
        self.assertEqual(self._kind(MD_CLAIM, markup=True), mod.UNFALSIFIABLE)

    def test_the_markup_axis_is_not_asked_of_a_flat_carrier(self):
        """announce-лог — ПЛОСКАЯ строка, и бэктик там цитатой не является."""
        text = ("Аудит доложил `CI control RED 140 имён`")
        self.assertEqual(self._kind(text, markup=True), mod.QUOTED)
        self.assertEqual(self._kind(text, markup=False), mod.UNFALSIFIABLE)

    def test_guillemets_around_a_term_only_do_not_quote_the_claim(self):
        # Дословная форма из архива карточки: в кавычках стоит ТЕРМИН, а
        # претензия — снаружи. Первая редакция оси (ADR-1124) спрашивала
        # только положение МАРКЕРА и объявляла такую претензию цитатой —
        # ошибка в сторону «чисто».
        text = "«контрольный прогон» RED 67 упавших, состав не читался"
        self.assertEqual(self._kind(text, markup=True), mod.UNFALSIFIABLE)

    def test_guillemets_around_the_whole_claim_do_quote_it(self):
        text = "сводка «контрольный прогон RED 67 упавших» разобрана"
        self.assertEqual(self._kind(text, markup=True), mod.QUOTED)

    def test_a_fenced_claim_is_a_quotation_and_the_same_text_unfenced_is_not(self):
        self.assertEqual(self._kind(MD_CLAIM, markup=True, fenced=True),
                         mod.QUOTED)
        self.assertEqual(self._kind(MD_CLAIM, markup=True, fenced=False),
                         mod.UNFALSIFIABLE)

    def test_a_blockquoted_claim_is_a_quotation_and_plain_text_is_not(self):
        self.assertEqual(self._kind(MD_CLAIM, markup=True, blockquote=True),
                         mod.QUOTED)
        self.assertEqual(self._kind(MD_CLAIM, markup=True, blockquote=False),
                         mod.UNFALSIFIABLE)

    def test_an_unclosed_opener_is_a_third_outcome_not_not_quoted(self):
        text = "сводка «контрольный прогон CI RED 67 упавших, состав не читался"
        self.assertEqual(self._kind(text, markup=True),
                         mod.QUOTATION_UNDECIDED)

    def test_closing_the_same_opener_decides_the_axis(self):
        text = "сводка «контрольный прогон CI RED 67 упавших», состав не читался"
        self.assertEqual(self._kind(text, markup=True), mod.QUOTED)

    def test_an_opener_AFTER_the_claim_does_not_make_it_undecided(self):
        # Иначе ось краснела бы на любой записи, где автор позже открыл
        # кавычку: «не ответила» обязано означать «накрыть МОГЛО БЫ».
        text = "контрольный прогон CI RED 67 упавших, далее «цитата без конца"
        self.assertEqual(self._kind(text, markup=True), mod.UNFALSIFIABLE)

    def test_nested_markup_inside_a_closed_pair_is_not_an_unclosed_opener(self):
        """«Внутри закрытой пары» — это ВНУТРИ ДИАПАЗОНА, а не «равно концу».

        Первая редакция `unclosed_opener` помечала закрытыми только КОНЦЫ
        пары, поэтому вложенный открыватель числился свободным и любая запись
        с вложенной разметкой уходила в `quotation_undecided` — то есть
        верхний край вилки раздувался формой разметки, а не незнанием.
        """
        self.assertEqual(mod.unclosed_opener("``тут `вложенный` бэктик``",
                                             markup=True), -1)
        self.assertEqual(mod.unclosed_opener("«внешняя «вложенная» закрыта»",
                                             markup=True), -1)
        # Обратная половина: та же разметка БЕЗ закрытия — открыватель назван.
        self.assertEqual(mod.unclosed_opener("``тут `вложенный` бэктик",
                                             markup=True), 0)
        self.assertEqual(mod.unclosed_opener("«внешняя «вложенная» не закрыта",
                                             markup=True), 0)

    def test_the_markup_axis_is_asked_only_of_a_markup_carrier(self):
        """У плоского носителя бэктик разметкой НЕ является."""
        self.assertEqual(mod.unclosed_opener("`не закрыт", markup=True), 0)
        self.assertEqual(mod.unclosed_opener("`не закрыт", markup=False), -1)

    def test_code_spans_pair_runs_of_equal_width(self):
        # ``текст с `бэктиком` внутри`` — законная форма markdown, и пара по
        # «любому следующему бэктику» разорвала бы её посередине.
        text = "``тут `вложенный` бэктик``"
        self.assertEqual(mod.code_spans(text), [(0, len(text) - 1)])

    def test_every_quotation_kind_the_door_can_return_is_declared(self):
        src = Path(mod.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "quotation_of")
        returned = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Tuple):
                first = node.value.elts[0]
                if isinstance(first, ast.Name):
                    returned.add(first.id)
        self.assertTrue(returned, "роды не разобраны — сцена не собралась")
        # Имена ЗАГЛАВНЫЕ — объявленные константы. Имя в нижнем регистре —
        # местная переменная, и у неё отдельный вопрос: ОТКУДА она берётся.
        local = {n for n in returned if not n.isupper()}
        for name in returned - local:
            self.assertIn(getattr(mod, name), mod.QUOTATION_KINDS,
                          "род " + name + " не объявлен в QUOTATION_KINDS")
        # Местная переменная приходит из перечня кандидатов, и каждый род в
        # нём обязан быть объявлен: иначе род, попавший в кандидаты мимо
        # QUOTATION_KINDS, вышел бы наружу молча.
        for node in ast.walk(fn):
            if not isinstance(node, ast.Tuple) or len(node.elts) != 2:
                continue
            second = node.elts[1]
            if isinstance(second, ast.Name) and second.id.isupper():
                self.assertIn(getattr(mod, second.id), mod.QUOTATION_KINDS,
                              "род " + second.id + " попал в кандидаты, "
                              "но не объявлен")

    def test_no_scene_makes_the_door_return_an_undeclared_kind(self):
        """Та же проверка ИСХОДОМ: статический разбор мог бы не увидеть род."""
        scenes = [
            (MD_CLAIM, dict(markup=True)),
            (MD_CLAIM, dict(markup=True, fenced=True)),
            (MD_CLAIM, dict(markup=True, blockquote=True)),
            ("сводка «контрольный прогон CI RED 67", dict(markup=True)),
            ("сводка «контрольный прогон CI RED 67»", dict(markup=True)),
            ("`контрольный прогон CI RED 67`", dict(markup=True)),
        ]
        seen = set()
        for text, kw in scenes:
            seg = mod.claim_segments(text)[0]
            ends = mod.read_claim(seg["segment"])
            end = seg["start"] + max(
                sp[1] for sp in (ends["count_span"], ends["cause_span"]) if sp)
            kind, why = mod.quotation_of(text, start=seg["start"],
                                        claim_end=end, **kw)
            self.assertIn(kind, mod.QUOTATION_KINDS)
            self.assertTrue(why, "род без причины")
            seen.add(kind)
        # Сцены обязаны РАЗЛИЧАТЬ: один и тот же ответ на всех — зелёная
        # проверка на приборе, который отвечает одно и то же.
        self.assertGreaterEqual(len(seen), 4)


class ADurationIsNotACountOfFailures(unittest.TestCase):
    """«красное 4 суток» и «красных 4» — РАЗНЫЕ утверждения."""

    def test_a_duration_carries_no_count_and_is_not_a_claim(self):
        seg = mod.claim_segments("автопроверка кода КРАСНАЯ, красное 4 суток")[0]
        got = mod.read_claim(seg["segment"])
        self.assertIsNone(got["count"])
        self.assertEqual(got["duration_not_a_count"], ["4"])

    def test_the_same_number_without_a_time_unit_is_a_count(self):
        seg = mod.claim_segments("автопроверка кода: красных 4 имени")[0]
        got = mod.read_claim(seg["segment"])
        self.assertEqual(got["count"], 4)
        self.assertEqual(got["duration_not_a_count"], [])

    def test_the_verdict_differs_and_not_only_the_reading(self):
        def kind(line):
            seg = mod.claim_segments(line)[0]
            return mod.classify_claim(seg["segment"], line=line,
                                      start=seg["start"],
                                      canonical=_canon())["kind"]
        self.assertEqual(kind("автопроверка кода КРАСНАЯ, красное 4 суток"),
                         mod.NO_CLAIM)
        self.assertEqual(kind("автопроверка кода КРАСНАЯ, красных 4 имени"),
                         mod.UNFALSIFIABLE)

    def test_a_fractional_duration_is_still_a_duration(self):
        seg = mod.claim_segments("автопроверка кода: красное 4.1 суток")[0]
        self.assertIsNone(mod.read_claim(seg["segment"])["count"])


def _md_tree(tmp, *, tracker=(), journal=(), digest: str | None = None,
             name: str = "дерево") -> str:
    """Одноразовое дерево контента: носители кладёт САМА сцена.

    ``name`` обязателен, когда сцена кладёт ДВА дерева: один каталог на обе
    половины пары оставил бы файл первой половины во второй, и «чисто»
    мерилось бы на грязном дереве — зелёная проверка ни о чём.
    """
    root = Path(tmp) / name
    for carrier, files in ((mod.CARRIER_TRACKER, tracker),
                           (mod.CARRIER_JOURNAL, journal)):
        rel, _mask = mod.CARRIER_PATHS[carrier]
        base = root / rel
        base.mkdir(parents=True, exist_ok=True)
        for name, text in files:
            (base / name).write_text(text, encoding="utf-8")
    if digest is not None:
        prod = root / mod.DIGEST_PRODUCER
        prod.parent.mkdir(parents=True, exist_ok=True)
        prod.write_text(digest, encoding="utf-8")
    return str(root)


class AllFourCarriersAreAnsweredOrNamedUnmeasured(unittest.TestCase):
    """ADR-1124 закрыл ОДИН носитель из четырёх; нулём остальные не считаются."""

    def _census(self, tmp, **kw):
        d = Path(tmp) / "data"
        _write_log(d, [{"ts": "t", "summary": NAMED}])
        return mod.run_census(data_dir=d, canonical=_canon(), **kw)

    def test_every_declared_carrier_gets_an_answer(self):
        with TemporaryDirectory() as tmp:
            doc = self._census(tmp, carrier_root=_md_tree(tmp))
            for carrier in mod.CARRIERS:
                self.assertIn(carrier, doc["carriers"],
                              f"носитель {carrier} объявлен, а ответа нет")

    def test_a_missing_carrier_directory_is_unmeasured_not_zero(self):
        with TemporaryDirectory() as tmp:
            doc = self._census(tmp, carrier_root=_EMPTY_TREE(tmp))
            c = doc["carriers"][mod.CARRIER_JOURNAL]
            self.assertEqual(c["status"], "UNMEASURED")
            self.assertTrue(c["unmeasured"])
            self.assertIn("НЕ ИЗМЕРЕНО", "\n".join(mod.format_report(doc)))

    def test_a_present_but_EMPTY_carrier_directory_is_unmeasured(self):
        """«Каталог есть, а файлов нет» — третий исход, а не пустое население.

        Отличается от сцены «каталога нет» (выше) и от «файл есть, претензий
        нет» (ниже) РОВНО одним: каталог создан, файлов по маске ноль. Без
        этой сцены мутация «вернуть пустую причину» выживает — ни одна
        проверка не спрашивала, чем «нечего читать» отличается от
        «прочитано и чисто» (замер #1271: мутация M17 ВЫЖИЛА на первом прогоне).
        """
        with TemporaryDirectory() as tmp:
            c = self._census(tmp, carrier_root=_md_tree(tmp))["carriers"]["journal"]
            self.assertEqual(c["status"], "UNMEASURED")
            self.assertEqual(c["files"], 0)
            self.assertTrue(any("ни одного файла по маске" in u
                                for u in c["unmeasured"]),
                            f"причина не названа: {c['unmeasured']}")

    def test_a_present_but_claimless_carrier_is_a_measured_zero(self):
        with TemporaryDirectory() as tmp:
            tree = _md_tree(tmp, journal=[("W01.md", "обычная запись без претензий\n")])
            c = self._census(tmp, carrier_root=tree)["carriers"][mod.CARRIER_JOURNAL]
            self.assertEqual(c["status"], "OK")
            self.assertEqual(c["population_floor"], 0)
            self.assertEqual(c["files"], 1)

    def test_a_carrier_claim_is_found_and_named_by_file_and_line(self):
        with TemporaryDirectory() as tmp:
            tree = _md_tree(tmp, journal=[("W02.md", "шапка\n\n" + MD_CLAIM + "\n")])
            c = self._census(tmp, carrier_root=tree)["carriers"][mod.CARRIER_JOURNAL]
            self.assertEqual(c["population_floor"], 1)
            self.assertEqual(c["findings"][0]["file"], "docs/journal/W02.md")
            self.assertEqual(c["findings"][0]["line"], 3)

    def test_the_bracket_ends_differ_only_when_the_axis_did_not_answer(self):
        decided = MD_CLAIM
        undecided = "сводка «контрольный прогон CI RED 67 упавших, состав не читался"
        with TemporaryDirectory() as tmp:
            a = self._census(tmp, carrier_root=_md_tree(
                tmp, journal=[("W03.md", decided + "\n")]))["carriers"]["journal"]
            self.assertEqual((a["population_floor"], a["population_ceiling"]),
                             (1, 1))
        with TemporaryDirectory() as tmp:
            b = self._census(tmp, carrier_root=_md_tree(
                tmp, journal=[("W04.md", undecided + "\n")]))["carriers"]["journal"]
            self.assertEqual((b["population_floor"], b["population_ceiling"]),
                             (0, 1))

    def test_an_unreadable_file_is_named_and_not_folded_into_zero(self):
        with TemporaryDirectory() as tmp:
            tree = _md_tree(tmp, journal=[("W05.md", "запись\n")])
            rel, _m = mod.CARRIER_PATHS[mod.CARRIER_JOURNAL]
            (Path(tree) / rel / "битый.md").write_bytes(b"\xff\xfe\x00CI control RED 5")
            c = self._census(tmp, carrier_root=tree)["carriers"]["journal"]
            self.assertEqual(len(c["unread_files"]), 1)
            self.assertTrue(any("НЕ ПРОЧИТАНО" in u for u in c["unmeasured"]))

    def test_the_unclosed_opener_counter_proves_the_axis_can_fire(self):
        """Ноль в «ось не ответила» обязан отличаться от закрытой дороги."""
        with TemporaryDirectory() as tmp:
            tree = _md_tree(tmp, journal=[
                ("W06.md", "«незакрытая кавычка в записи без претензии\n\n"
                           + MD_CLAIM + "\n")])
            c = self._census(tmp, carrier_root=tree)["carriers"]["journal"]
            self.assertEqual(c["by_kind"][mod.QUOTATION_UNDECIDED], 0)
            self.assertEqual(c["records_with_unclosed_opener"], 1)

    def test_an_unread_announce_log_does_not_lock_the_other_carriers(self):
        """«Один носитель не прочитан» ≠ «о классе ничего не известно»."""
        with TemporaryDirectory() as tmp:
            tree = _md_tree(tmp, journal=[("W07.md", MD_CLAIM + "\n")])
            doc = mod.run_census(data_dir=tmp, canonical=_canon(),
                                 carrier_root=tree)
            self.assertEqual(doc["carriers"]["announce"]["status"], "UNMEASURED")
            self.assertEqual(doc["carriers"]["journal"]["population_floor"], 1)
            self.assertEqual(doc["findings_total"], 1)

    def test_a_carrier_finding_alone_gives_exit_code_one(self):
        """Дорога до кода возврата проведена, а не только до документа."""
        with TemporaryDirectory() as tmp:
            d = Path(tmp) / "data"
            _write_log(d, [{"ts": "t", "summary":
                            "контрольный прогон 45967869368 заказан"}])
            dirty = _md_tree(tmp, journal=[("W08.md", MD_CLAIM + "\n")],
                             name="грязное")
            self.assertEqual(
                mod.main(["--data-dir", str(d), "--carrier-root", dirty]), 1)
            clean = _md_tree(tmp, journal=[("W09.md", "тихая запись\n")],
                             name="чистое")
            self.assertEqual(
                mod.main(["--data-dir", str(d), "--carrier-root", clean]), 0)

    def test_a_named_carrier_root_that_is_not_a_dir_refuses_with_code_two(self):
        with TemporaryDirectory() as tmp:
            d = Path(tmp) / "data"
            _write_log(d, [{"ts": "t", "summary": NAMED}])
            missing = str(Path(tmp) / "нет-дерева")
            self.assertEqual(
                mod.main(["--data-dir", str(d), "--carrier-root", missing]), 2)

    def test_the_carrier_root_choice_is_printed_both_ways(self):
        with TemporaryDirectory() as tmp:
            named = self._census(tmp, carrier_root=_EMPTY_TREE(tmp))
            self.assertIn("НАЗВАНО", "\n".join(mod.format_carriers(named)))
            default = mod.run_census(
                data_dir=Path(tmp) / "нет", canonical=_canon(),
                carrier_root=None)
            self.assertIn("УМОЛЧАНИЕ", "\n".join(mod.format_carriers(default)))

    def test_a_document_without_carriers_says_unmeasured_not_nothing(self):
        self.assertIn("НЕ ИЗМЕРЕНО", "\n".join(mod.format_carriers({})))

    def test_the_printed_bracket_shows_both_ends_when_they_differ(self):
        """Вилка обязана ДОЕЗЖАТЬ до читателя строкой, а не только в документе.

        Различающая половина — ниже: при сошедшихся краях печатается одно
        число, иначе «НЕ МЕНЬШЕ 5 и НЕ БОЛЬШЕ 5» читалось бы как незнание
        там, где знание полное.
        """
        undecided = "сводка «контрольный прогон CI RED 67 упавших, состав не читался"
        with TemporaryDirectory() as tmp:
            doc = self._census(tmp, carrier_root=_md_tree(
                tmp, journal=[("W10.md", undecided + "\n")]))
            line = next(l for l in mod.format_carriers(doc)
                        if l.strip().startswith("· journal"))
            self.assertIn("НЕ МЕНЬШЕ 0 и НЕ БОЛЬШЕ 1", line)

    def test_the_printed_bracket_shows_one_number_when_the_ends_agree(self):
        with TemporaryDirectory() as tmp:
            doc = self._census(tmp, carrier_root=_md_tree(
                tmp, journal=[("W11.md", MD_CLAIM + "\n")]))
            line = next(l for l in mod.format_carriers(doc)
                        if l.strip().startswith("· journal"))
            self.assertIn("ПРЕДМЕТ 1 ·", line)
            self.assertNotIn("НЕ МЕНЬШЕ", line)

    def test_a_declared_carrier_absent_from_the_answer_is_named(self):
        with TemporaryDirectory() as tmp:
            doc = self._census(tmp, carrier_root=_EMPTY_TREE(tmp))
            doc["carriers"].pop(mod.CARRIER_JOURNAL)
            self.assertIn("НЕ ИЗМЕРЕНО",
                          "\n".join(mod.format_carriers(doc)))


class TheDigestCarrierKeepsNoTextAndSaysSo(unittest.TestCase):
    """«Что сводка СКАЗАЛА» и «СПОСОБНА ли сказать» — разные вопросы."""

    def test_the_observed_population_is_unmeasured_with_a_reason(self):
        with TemporaryDirectory() as tmp:
            doc = digest = mod.digest_census(Path(_md_tree(tmp, digest="x = 1\n")))
            self.assertEqual(doc["status"], "UNMEASURED")
            self.assertTrue(any("не хранит своего текста" in u
                                for u in digest["unmeasured"]))

    def test_a_missing_producer_is_named_not_silent(self):
        with TemporaryDirectory() as tmp:
            doc = mod.digest_census(Path(_EMPTY_TREE(tmp)))
            self.assertTrue(any("производитель не прочитан" in u
                                for u in doc["unmeasured"]))

    def test_a_plain_literal_claim_is_counted_as_a_literal(self):
        with TemporaryDirectory() as tmp:
            src = 'MSG = "АВТОПРОВЕРКА КОДА: КРАСНАЯ, красных 7"\n'
            doc = mod.digest_census(Path(_md_tree(tmp, digest=src)))
            self.assertEqual(doc["literals_with_mark"], 1)
            self.assertEqual(doc["literals_with_count"], 1)
            self.assertEqual(doc["templates_with_computed_number"], 0)

    def test_a_computed_number_is_a_third_outcome_not_a_zero(self):
        with TemporaryDirectory() as tmp:
            src = ('def f(n):\n'
                   '    return f"АВТОПРОВЕРКА КОДА: КРАСНАЯ, красных {n}"\n')
            doc = mod.digest_census(Path(_md_tree(tmp, digest=src)))
            self.assertEqual(doc["literals_with_count"], 0)
            self.assertEqual(doc["templates_with_computed_number"], 1)
            self.assertTrue(any("ВЫЧИСЛЯЕМЫМ" in u for u in doc["unmeasured"]))

    def test_an_unparsable_producer_is_a_reason_not_a_crash(self):
        with TemporaryDirectory() as tmp:
            doc = mod.digest_census(Path(_md_tree(tmp, digest="def (:\n")))
            self.assertTrue(any("не разобран" in u for u in doc["unmeasured"]))

    def test_the_placeholder_itself_is_not_readable_as_a_count(self):
        """Знак подстановки проверяется ТОЙ ЖЕ дверью чтения.

        Иначе проверка «знак на месте» тавтологична: знак только что вставлен,
        поэтому `MARK in text` истинно при ЛЮБОМ его значении — вакуумный
        сторож (замер #1271: мутация «знак = „7“» выжила именно на нём).
        """
        got = mod.read_claim("автопроверка кода: красных " + mod.COMPUTED_MARK)
        self.assertIsNone(got["count"],
                          "знак подстановки читается как число упавших")

    def test_a_placeholder_that_reads_as_a_number_is_a_defect_of_the_measure(self):
        src = ('def f(n):\n'
               '    return f"АВТОПРОВЕРКА КОДА: КРАСНАЯ, красных {n}"\n')
        with TemporaryDirectory() as tmp:
            tree = Path(_md_tree(tmp, digest=src))
            good = mod.digest_census(tree)
            self.assertEqual(good["templates_with_computed_number"], 1)
            self.assertFalse(any("знак подстановки" in u
                                 for u in good["unmeasured"]))
            saved = mod.COMPUTED_MARK
            try:
                mod.COMPUTED_MARK = "7"
                bad = mod.digest_census(tree)
            finally:
                mod.COMPUTED_MARK = saved
            self.assertEqual(bad["templates_with_computed_number"], 0)
            self.assertTrue(any("знак подстановки" in u
                                for u in bad["unmeasured"]),
                            f"дефект мерки не назван: {bad['unmeasured']}")

    def test_a_literal_count_inside_an_fstring_is_not_a_third_outcome(self):
        """Подстановка стои́т ДО маркера, поэтому в сегмент она НЕ попадает.

        Порядок здесь — предмет сцены, а не оформление: держи подстановку
        ПОСЛЕ маркера, и сегмент нёс бы её всегда, а ось «литерал против
        вычисляемого» не спрашивалась бы ни разу (замер #1271: мутация M31
        на такой сцене ВЫЖИЛА — зелена была ПРОВОДКА, а не ОСЬ).
        """
        src = ('def f(x):\n'
               '    return f"{x} — АВТОПРОВЕРКА КОДА: КРАСНАЯ, красных 7"\n')
        with TemporaryDirectory() as tmp:
            doc = mod.digest_census(Path(_md_tree(tmp, digest=src)))
            self.assertEqual(doc["literals_with_count"], 1)
            self.assertEqual(doc["templates_with_computed_number"], 0)
            self.assertFalse(any("знак подстановки" in u
                                 for u in doc["unmeasured"]))

    def test_the_marker_alone_does_not_invent_a_computed_number(self):
        with TemporaryDirectory() as tmp:
            src = ('def f(n):\n'
                   '    return f"итог за {n} дней"\n')
            doc = mod.digest_census(Path(_md_tree(tmp, digest=src)))
            self.assertEqual(doc["templates_with_computed_number"], 0)


class TheOfficeStepPrintsTheCarriersToo(unittest.TestCase):
    """Проводка меряется AST: носитель, не попавший в печать, не прочитан никем."""

    def test_format_report_calls_the_carrier_formatter(self):
        tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
        fn = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "format_report")
        called = {n.func.id for n in ast.walk(fn)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("format_carriers", called)

    def test_the_markdown_carriers_go_through_one_parsing_door(self):
        """Своей копии разбора у носителя нет: разойдись она — вердикты разные."""
        tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
        fn = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "carrier_census")
        called = {n.func.id for n in ast.walk(fn)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("claim_segments", called)
        self.assertIn("classify_claim", called)

    def test_the_announce_carrier_uses_the_same_door_as_the_rest(self):
        """Своя копия обхода у «главного» носителя рождала ЛОЖНЫЙ ноль."""
        tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
        fn = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "run_census")
        called = {n.func.id for n in ast.walk(fn)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("carrier_census", called)


if __name__ == "__main__":
    unittest.main()
