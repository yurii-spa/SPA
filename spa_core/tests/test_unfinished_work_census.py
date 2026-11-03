"""Батарея прибора замера класса «объявлено, но НЕ СОЗДАНО» (ADR-908, заказ G900 п. 1).

Каждая проверка — положительный контроль НАСТОЯЩЕГО наблюдения 2026-11-03, а не
украшение (`.claude/rules/deployment.md`, «Проверка сторожа сторожей»):

* три цикла подряд (#1019/#1020/#1021) объявили `tree_content_class_baseline.json`,
  умерли, и файла не было ни в одном из пяти их деревьев — а имя на базе ПОЯВИЛОСЬ
  позже, когда работу доделал #1022. Спроси сегодняшнюю базу — и предмет класса
  читается как «удаление». Контроль: `..._name_born_after_the_announcement`;
* вложенное дерево `<прод>/.claude/worktrees/cycle-331-orch/…` снято, поиск корня по
  `.git` доходит до ПРОД-дерева и начинает судить чужой путь его историей — так замер
  получил 12 ложных членов. Контроль: `..._directory_gone`;
* первый прогон писателя ушёл умолчанием в ПРОД-дерево (запись туда принадлежит
  владельцу). Контроль: `..._writes_into_the_instrument_tree`;
* первая дверь оси 2 читала трекер прод-дерева, где 668 карточек из 1569 нет вовсе, и
  артефакт `/private/tmp/c1020_diff_base.log` не нашёлся. Контроль:
  `..._reads_the_given_tracker`.

FROZEN-DATE-OK: injected-clock — якорь сцены `NOW` передаётся прибору входом
`now=`/`announced=` у каждой проверки, и обе стороны сравнения закреплены: отметки
объявлений и истории выводятся ИЗ `NOW`, подпроцессов эти пробы не поднимают вовсе.
"""

# FROZEN-DATE-OK: injected-clock — якорь `NOW` передаётся прибору входом
# `now=`/`announced=`/`first_seen=` у каждой проверки, и обе стороны сравнения
# выведены ИЗ него; подпроцессов эти пробы не поднимают вовсе, а проба
# существования файлов инъектируется (`_exists`), поэтому живого диска здесь нет.
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts import unfinished_work_census as census

NOW = datetime(2026, 11, 3, 19, 0, 0, tzinfo=timezone.utc)
LONG_AGO = NOW - timedelta(days=30)
YESTERDAY = NOW - timedelta(days=1)
TREE = Path("/private/tmp/spa_c999")


def _exists(present):
    """Проба существования — ВХОД прибора, а не живой диск.

    Прибор, спрашивающий настоящий диск, судил бы о том, что сегодня лежит в `/tmp`:
    тот же класс, что литеральный pid, отданный живой ОС.
    """
    known = {Path(p) for p in present}
    return lambda path: Path(path) in known


class ClassifyTest(unittest.TestCase):

    def _call(self, path, *, present=(), announced=LONG_AGO, first_seen=None, cwd=None):
        return census.classify_declared_path(
            path, announced=announced, now=NOW, grace_hours=3.0,
            first_seen=first_seen or {}, exists=_exists(present), cwd=cwd)

    def test_a_file_that_exists_in_the_declaring_tree_is_present(self):
        state, why = self._call(
            str(TREE / "spa_core/tests/x.py"),
            present=[TREE / ".git", TREE / "spa_core/tests", TREE / "spa_core/tests/x.py"])
        self.assertEqual(census.PRESENT, state)
        self.assertIn(str(TREE), why)

    def test_a_name_never_in_base_history_was_never_created(self):
        state, why = self._call(
            str(TREE / "spa_core/tests/x.py"),
            present=[TREE / ".git", TREE / "spa_core/tests"])
        self.assertEqual(census.DECLARED_NEVER_CREATED, state)
        self.assertIn("НИКОГДА", why)

    def test_a_name_born_after_the_announcement_was_not_there_at_the_time(self):
        """Предмет #1019/#1020/#1021: артефакт довёз СЛЕДУЮЩИЙ цикл."""
        state, why = self._call(
            str(TREE / "spa_core/tests/baseline.json"),
            present=[TREE / ".git", TREE / "spa_core/tests"],
            announced=LONG_AGO,
            first_seen={"spa_core/tests/baseline.json": NOW})
        self.assertEqual(census.DECLARED_NEVER_CREATED, state)
        self.assertIn("ПОЗЖЕ объявления", why)

    def test_a_name_that_was_on_base_before_the_announcement_is_a_deletion(self):
        state, why = self._call(
            str(TREE / "spa_core/tests/old.py"),
            present=[TREE / ".git", TREE / "spa_core/tests"],
            announced=YESTERDAY,
            first_seen={"spa_core/tests/old.py": LONG_AGO})
        self.assertEqual(census.ABSENT_KNOWN_NAME, state)
        self.assertIn("удаление", why)

    def test_a_fresh_announcement_is_not_judged_at_all(self):
        state, why = self._call(str(TREE / "spa_core/tests/x.py"),
                                announced=NOW - timedelta(hours=1))
        self.assertEqual(census.FRESH, state)
        self.assertIn("работа может идти", why)

    def test_a_record_without_a_stamp_is_unmeasured_not_a_member(self):
        state, _why = self._call(str(TREE / "x.py"), announced=None)
        self.assertEqual(census.UNMEASURED_ROOT, state)

    def test_a_relative_path_without_cwd_cannot_name_its_tree(self):
        state, why = self._call("spa_core/tests/x.py")
        self.assertEqual(census.UNMEASURED_ROOT, state)
        self.assertIn("`cwd`", why)

    def test_a_relative_path_with_cwd_is_judged(self):
        state, _why = self._call(
            "spa_core/tests/x.py", cwd=str(TREE),
            present=[TREE / ".git", TREE / "spa_core/tests",
                     TREE / "spa_core/tests/x.py"])
        self.assertEqual(census.PRESENT, state)

    def test_a_directory_gone_is_unmeasured_not_never_created(self):
        """Предмет 12 ложных членов: снятое ВЛОЖЕННОЕ дерево под живым корнем."""
        prod = Path("/Users/x/SPA_Claude")
        state, why = self._call(
            str(prod / ".claude/worktrees/cycle-331/spa_core/risk/daily_limits.py"),
            present=[prod / ".git"])
        self.assertEqual(census.UNMEASURED_TREE_GONE, state)
        self.assertIn("снят вместе с деревом", why)

    def test_a_tree_that_is_gone_entirely_is_unmeasured(self):
        state, why = self._call("/private/tmp/spa_c777/spa_core/x.py",
                                present=[Path("/private/tmp")])
        self.assertEqual(census.UNMEASURED_TREE_GONE, state)
        self.assertIn("рабочего дерева над путём нет", why)


class HistoryTest(unittest.TestCase):

    def test_git_failure_is_unmeasured_with_a_reason_not_an_empty_set(self):
        names, why = census.history_first_seen(
            TREE, git=lambda root, args: (128, "", "fatal: bad revision"))
        self.assertIsNone(names)
        self.assertIn("не прочитана", why)

    def test_history_without_a_single_name_is_unmeasured_too(self):
        names, why = census.history_first_seen(TREE, git=lambda root, args: (0, "", ""))
        self.assertIsNone(names)
        self.assertIn("ни одного имени", why)

    def test_the_earliest_appearance_wins_because_git_walks_newest_first(self):
        out = ("@2026-11-03T10:00:00+00:00\na.py\n\n"
               "@2026-07-01T10:00:00+00:00\na.py\nb.py\n")
        names, why = census.history_first_seen(TREE, git=lambda root, args: (0, out, ""))
        self.assertIsNotNone(names)
        self.assertEqual(census.parse_ts("2026-07-01T10:00:00+00:00"), names["a.py"])
        self.assertIn("2 имён", why)


class AxisOneTest(unittest.TestCase):

    def test_without_history_the_axis_refuses_instead_of_guessing(self):
        got = census.census_axis_one([], now=NOW, first_seen=None)
        self.assertEqual("unmeasured", got["verdict"])
        self.assertIn("не измерена", got["reason"])
        self.assertEqual([], got["members"])

    def test_a_member_carries_its_tree_kind(self):
        prod = Path("/Users/x/SPA_Claude")
        records = [{"ts": LONG_AGO.strftime("%Y-%m-%dT%H:%M:%SZ"), "session": "s1",
                    "files": [str(TREE / "spa_core/a.py"), str(prod / "spa_core/b.py")]}]
        got = census.census_axis_one(
            records, now=NOW, first_seen={},
            exists=_exists([TREE / ".git", TREE / "spa_core",
                            prod / ".git", prod / "spa_core"]),
            long_lived=[prod])
        self.assertEqual(2, len(got["members"]))
        self.assertEqual(1, got["members_disposable_tree"])
        self.assertEqual(1, got["members_long_lived_tree"])

    def test_tree_kind_calls_a_declared_root_long_lived(self):
        self.assertEqual("long_lived", census.tree_kind(TREE, long_lived=[TREE]))
        self.assertEqual("disposable", census.tree_kind(TREE, long_lived=[]))

    def test_a_handoff_is_matched_by_the_repo_path_not_the_basename(self):
        """`STATE.md` в двух разных деревьях передачей работы НЕ является."""
        other = Path("/private/tmp/spa_c998")
        by_card = {"c.md": [
            {"session": "s1", "ts": "2026-11-01T00:00:00Z",
             "paths": [(census.DECLARED_NEVER_CREATED, str(TREE / "docs/STATE.md"), "")]},
            {"session": "s2", "ts": "2026-11-02T00:00:00Z",
             "paths": [(census.PRESENT, str(other / "docs/STATE.md"), "")]}]}
        hand = census._handoffs(by_card)
        self.assertEqual(1, len(hand))
        self.assertEqual("docs/STATE.md", hand[0]["completed_later"][0]["artifact"])
        self.assertEqual(2, hand[0]["sessions"])

    def test_a_single_session_card_is_never_a_handoff(self):
        by_card = {"c.md": [
            {"session": "s1", "ts": "2026-11-01T00:00:00Z",
             "paths": [(census.DECLARED_NEVER_CREATED, str(TREE / "docs/a.md"), "")]},
            {"session": "s1", "ts": "2026-11-02T00:00:00Z",
             "paths": [(census.PRESENT, str(TREE / "docs/a.md"), "")]}]}
        self.assertEqual([], census._handoffs(by_card))


class AxisTwoTest(unittest.TestCase):

    def test_trailing_punctuation_is_not_part_of_the_path(self):
        self.assertEqual(["/private/tmp/a.log"],
                         census.mentioned_paths("лежит в /private/tmp/a.log, 437 КБ"))

    def test_supply_skips_directories_that_are_working_trees(self):
        found, skipped = census.supply_on_disk(
            ["/tmp"],
            lister=lambda d: {Path("/tmp"): [Path("/tmp/wt"), Path("/tmp/a.log")],
                              Path("/tmp/wt"): [Path("/tmp/wt/b.log")]}[d],
            is_tree=lambda d: d == Path("/tmp/wt"))
        self.assertEqual([Path("/tmp/a.log")], found)
        self.assertEqual([], skipped)

    def test_an_unreadable_directory_is_named_not_silently_empty(self):
        def _boom(_d):
            raise PermissionError("нет доступа")
        found, skipped = census.supply_on_disk(["/tmp"], lister=_boom,
                                               is_tree=lambda d: False)
        self.assertEqual([], found)
        self.assertEqual(1, len(skipped))
        self.assertIn("PermissionError", skipped[0])

    def test_the_record_and_the_supply_are_two_different_numbers(self):
        got = census.census_axis_two(
            [{"session": "s1", "ts": "x", "summary": "вывод в /private/tmp/a.log"}],
            exists=_exists([Path("/private/tmp"), Path("/private/tmp/a.log"),
                            Path("/private/tmp/b.log")]),
            supply=([Path("/private/tmp/a.log"), Path("/private/tmp/b.log")], []))
        self.assertEqual(2, got["supply_on_disk"])
        self.assertEqual(1, got["supply_named_by_the_record"])

    def test_the_card_door_reads_the_tracker_it_is_given(self):
        """Первая дверь читала ПРОД-трекер, где карточки нет вовсе."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tracker = Path(tmp) / "tracker"
            tracker.mkdir()
            (tracker / "card.md").write_text("смотри /private/tmp/x.log", encoding="utf-8")
            self.assertEqual(1, len(census.card_corpus(tracker)))
            self.assertEqual([], census.card_corpus(Path(tmp) / "нет-такого"))


class ExitCodeTest(unittest.TestCase):

    def _report(self, *, verdict="measured", members=(), axis2=(), unparsed=()):
        return {"unparsed_lines": list(unparsed),
                "axis_one": {"verdict": verdict, "members": list(members),
                             "reason": "—"},
                "axis_two": {"members": list(axis2)}}

    def test_three_outcomes_are_distinguishable(self):
        self.assertEqual(0, census.exit_code(self._report()))
        self.assertEqual(1, census.exit_code(self._report(members=[{"a": 1}])))
        self.assertEqual(2, census.exit_code(self._report(verdict="unmeasured")))
        self.assertEqual(2, census.exit_code(self._report(unparsed=["строка 7"])))


class DeclarationWriterTest(unittest.TestCase):

    def _report(self, *, members=None, verdict="measured", unparsed=()):
        rows = members if members is not None else [
            {"session": "s1", "ts": "2026-11-03T11:00:00Z",
             "path": str(TREE / "spa_core/tests/baseline.json"), "tree": str(TREE),
             "card": "c.md", "tree_kind": "disposable", "detail": "—", "summary": "—"}]
        return {"measured_at": "2026-11-03T19:00:00Z", "records": 10,
                "history_names": "18738 имён", "unparsed_lines": list(unparsed),
                "axis_one": {"verdict": verdict, "members": rows, "reason": "нет двери",
                             "members_long_lived_tree": 0, "judged_paths": 5,
                             "unmeasured_paths": 1, "handoffs": []},
                "axis_two": {"supply_on_disk": 1470, "named_total": 14,
                             "supply_named_by_the_record": 14, "supply_skipped": []}}

    def _spec(self, **over):
        spec = {"adr": "ADR-908", "order": "G900 п. 1", "measured_in": "цикл #1023",
                "instrument": "scripts/unfinished_work_census.py",
                "base_sha": "138c26117",
                "classification": {"s1:baseline.json": {
                    "verdict": census.CLASS, "evidence": "прямой ls: файла нет"}},
                "seam": {"chosen": "в", "why": "точность 3/5",
                         "refused": [{"option": "б", "price": "40 % ложных"}]}}
        spec.update(over)
        return spec

    def _write(self, report, spec):
        return census.build_declaration(
            report, adr=spec["adr"], order=spec["order"],
            measured_in=spec["measured_in"], instrument=spec["instrument"],
            base_sha=spec["base_sha"], classification=spec["classification"],
            seam=spec["seam"])

    def test_the_whole_contour_writes_the_measured_numbers(self):
        got = self._write(self._report(), self._spec())
        self.assertEqual(1, got["axis_one"]["class_members"])
        self.assertEqual("1/1", got["axis_one"]["sign_precision"])
        self.assertEqual(1470, got["axis_two"]["supply_on_disk"])
        self.assertEqual("ADR-908", got["adr"])

    def test_a_false_positive_is_counted_as_one_not_dropped(self):
        report = self._report(members=[
            {"session": "s1", "ts": "t", "path": str(TREE / "a/baseline.json"),
             "tree": str(TREE), "card": "", "tree_kind": "disposable",
             "detail": "", "summary": ""},
            {"session": "s2", "ts": "t", "path": str(TREE / "a/renamed.py"),
             "tree": str(TREE), "card": "", "tree_kind": "disposable",
             "detail": "", "summary": ""}])
        spec = self._spec(classification={
            "s1:baseline.json": {"verdict": census.CLASS, "evidence": "ls"},
            "s2:renamed.py": {"verdict": census.RENAME, "evidence": "уехал как _x.py"}})
        got = self._write(report, spec)
        self.assertEqual(1, got["axis_one"]["class_members"])
        self.assertEqual(1, got["axis_one"]["sign_false_positives"])
        self.assertEqual("1/2", got["axis_one"]["sign_precision"])

    def test_an_unmeasured_axis_refuses(self):
        with self.assertRaises(census.DeclarationRefused) as box:
            self._write(self._report(verdict="unmeasured"), self._spec())
        self.assertIn("не измерена", str(box.exception))

    def test_an_unparsed_journal_refuses(self):
        with self.assertRaises(census.DeclarationRefused) as box:
            self._write(self._report(unparsed=["строка 7"]), self._spec())
        self.assertIn("НЕ ПОЛНОСТЬЮ", str(box.exception))

    def test_an_empty_class_refuses_because_the_prover_is_the_instrument(self):
        with self.assertRaises(census.DeclarationRefused) as box:
            self._write(self._report(members=[]), self._spec())
        self.assertIn("ни одного члена", str(box.exception))

    def test_every_named_field_is_required(self):
        for field in ("adr", "order", "measured_in", "base_sha"):
            with self.subTest(field=field), \
                    self.assertRaises(census.DeclarationRefused) as box:
                self._write(self._report(), self._spec(**{field: ""}))
            self.assertIn(field, str(box.exception))

    def test_an_unclassified_strong_row_refuses(self):
        with self.assertRaises(census.DeclarationRefused) as box:
            self._write(self._report(), self._spec(classification={}))
        self.assertIn("НЕ РАЗОБРАН", str(box.exception))

    def test_a_verdict_without_evidence_refuses(self):
        spec = self._spec(classification={
            "s1:baseline.json": {"verdict": census.CLASS, "evidence": "  "}})
        with self.assertRaises(census.DeclarationRefused) as box:
            self._write(self._report(), spec)
        self.assertIn("ДОКАЗАТЕЛЬСТВА", str(box.exception))

    def test_an_unknown_verdict_refuses(self):
        spec = self._spec(classification={
            "s1:baseline.json": {"verdict": "наверное", "evidence": "—"}})
        with self.assertRaises(census.DeclarationRefused) as box:
            self._write(self._report(), spec)
        self.assertIn("наверное", str(box.exception))

    def test_a_seam_without_a_choice_a_reason_or_a_price_refuses(self):
        for seam, needle in (
                ({"why": "—", "refused": [{"option": "б", "price": "p"}]}, "шов не назван"),
                ({"chosen": "в", "refused": [{"option": "б", "price": "p"}]}, "нет причины"),
                ({"chosen": "в", "why": "—"}, "цена отвергнутых"),
                ({"chosen": "в", "why": "—", "refused": [{"option": "б"}]}, "ЦЕНА")):
            with self.subTest(needle=needle), \
                    self.assertRaises(census.DeclarationRefused) as box:
                self._write(self._report(), self._spec(seam=seam))
            self.assertIn(needle, str(box.exception))


class DeliveredDeclarationTest(unittest.TestCase):
    """Объявление, уехавшее с этим решением, читается и держится."""

    def test_the_declaration_names_both_axes_with_numbers_and_a_date(self):
        path = Path(census.PROJECT_ROOT) / census.DECLARATION_REL
        self.assertTrue(path.is_file(), f"объявление не найдено: {path}")
        doc = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(1, doc["schema_version"])
        for field in ("adr", "order", "instrument", "measured_in", "base_sha",
                      "measured_at"):
            self.assertTrue(str(doc.get(field) or "").strip(), field)
        self.assertGreaterEqual(doc["axis_one"]["class_members"], 1)
        self.assertGreaterEqual(doc["axis_two"]["supply_on_disk"], 1)
        self.assertTrue(doc["seam"]["refused"], "цена альтернатив не названа")
        for row in doc["axis_one"]["rows"]:
            self.assertIn(row["verdict"], census.VERDICTS)
            self.assertTrue(row["evidence"].strip(), row["path"])

    def test_the_writer_is_the_only_author_of_this_file(self):
        """Поле `instrument` называет писателя — рука здесь не автор."""
        doc = json.loads((Path(census.PROJECT_ROOT) / census.DECLARATION_REL)
                         .read_text(encoding="utf-8"))
        self.assertEqual("scripts/unfinished_work_census.py", doc["instrument"])


if __name__ == "__main__":
    unittest.main()
