#!/usr/bin/env python3
"""Контроль прибора `_scalar_identity_price` и сам инвариант цены (ADR-502).

Прибор отвечает на вопрос «кто держит позиционную координату через прогон», и
цена правила личности-по-значению равна его находке. Поэтому у него обязаны быть
обе стороны: **ноль на исправном контуре** и **находка на каждом порванном
звене, с названным звеном** (`.claude/rules/acceptance.md` §3).

Отдельно закреплён дефект ПЕРВОЙ редакции меры: она искала координату без
кавычек и объявила чужими держателями 615 координат, из которых настоящих было
ноль — под меру попал питоний код `Path(__file__).resolve().parents[1]`. Тот
контроль (`test_python_source_is_not_a_holder`) и есть положительный контроль
самого замера: без него «грубость в сторону находки» снова сойдёт за строгость.

Сцена каждого теста — СВОЙ одноразовый репозиторий. Имя ветки задаётся явно
(`git init -b`): `init.defaultBranch` у хоста разный (Apple Git на Маке даёт
`main`, git на `ubuntu-latest` — `master`), и фикстура, промолчавшая о нём, зелена
здесь и красна в CI (`.claude/rules/deployment.md`, раздел про git-окружение).

Только stdlib, оффлайн.
"""
# FROZEN-DATE-OK: литеральных дат в файле нет — предмет не время, а координата
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.tests import _scalar_identity_price as price  # noqa: E402

#: Имя ветки одноразовой сцены — объявлено, а не унаследовано у хоста.
_BRANCH = "scalar-price-stand"


def _repo(tmp: Path, files: dict) -> Path:
    """Одноразовый репозиторий с названными файлами, все — git-tracked."""
    root = tmp / "stand"
    root.mkdir()
    subprocess.run(["git", "init", "-b", _BRANCH, str(root)],
                   check=True, capture_output=True)
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.email=t@t",
                    "-c", "user.name=t", "commit", "-m", "stand"],
                   check=True, capture_output=True)
    return root


class TheInstrumentIsGreenOnAHealthyContour(unittest.TestCase):

    def test_no_holder_at_all_is_OK_and_says_the_zero_was_measured(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp), {"scripts/a.py": "x = 1\n"})
            doc = price.measure(root)
        self.assertEqual(doc["status"], "OK")
        self.assertEqual(doc["counts"], {})
        self.assertIn("измерено", doc["reason"])

    def test_a_coordinate_without_a_position_is_not_a_holder(self):
        """`.findings` места не называет — менять ему имя правило не будет."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp), {"scripts/a.py": 'C = ".findings.severity"\n'})
            doc = price.measure(root)
        self.assertEqual(doc["status"], "OK")


class EveryTornLinkIsAFindingAndTheLinkIsNamed(unittest.TestCase):

    def test_a_card_criterion_holding_a_position_is_the_price(self):
        """Единственная форма, в которой карточка сверяет координату машинно."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp), {
                "nimbalyst-local/tracker/inbox-x.md":
                    "---\nfinding_key: .books[0].facts\n---\n"})
            doc = price.measure(root)
        self.assertEqual(doc["status"], "FINDING")
        self.assertEqual(doc["holders"]["foreign"],
                         {"nimbalyst-local/tracker/inbox-x.md": [".books[0].facts"]})

    def test_an_acceptance_probe_holding_a_position_is_the_price_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp), {
                "nimbalyst-local/tracker/inbox-y.md":
                    "---\nacceptance_probe: some_probe:.rows[3]\n---\n"})
            doc = price.measure(root)
        self.assertEqual(doc["status"], "FINDING")

    def test_a_ratchet_baseline_holding_a_position_is_the_price(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp), {
                "scripts/thing_baseline.json": json.dumps([".rows[2].code"])})
            doc = price.measure(root)
        self.assertEqual(doc["status"], "FINDING")
        self.assertIn("scripts/thing_baseline.json", doc["holders"]["foreign"])

    def test_ordinary_code_holding_a_coordinate_string_is_the_price(self):
        """Координата ДАННЫМИ в коде — тот, кто будет её сверять."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp),
                         {"spa_core/monitoring/m.py": 'WATCH = ".rows[0].v"\n'})
            doc = price.measure(root)
        self.assertEqual(doc["status"], "FINDING")


class TheRoadsOfHoldingAreSeparatedNotLumped(unittest.TestCase):
    """Три рода держателя различимы — иначе ноль чужих ничего не значит."""

    def test_python_source_is_not_a_holder(self):
        """ДЕФЕКТ ПЕРВОЙ РЕДАКЦИИ, дословно: `.parents[1]` — код, а не координата.

        Без кавычек мера нашла 615 «чужих держателей» и НИ ОДНОГО настоящего.
        Это и есть положительный контроль самого замера.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp), {
                "scripts/a.py":
                    "from pathlib import Path\n"
                    "_ROOT = Path(__file__).resolve().parents[1]\n"
                    "x = some.list[0].attr\n"})
            doc = price.measure(root)
        self.assertEqual(doc["status"], "OK", doc.get("holders"))

    def test_prose_in_a_document_is_quoted_not_held(self):
        """Цитата устаревает громко — её читает человек, а не сверяет мост."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp), {
                "docs/why.md": 'Координата ".findings[8].severity" врёт.\n',
                "nimbalyst-local/tracker/inbox-z.md":
                    'В теле карточки координата ".rows[0].v" только цитируется.\n'})
            doc = price.measure(root)
        self.assertEqual(doc["status"], "OK", doc.get("holders"))
        self.assertEqual(doc["counts"].get("quoted"), 2)
        self.assertNotIn("foreign", doc["counts"])

    def test_a_regenerated_artifact_is_not_a_holder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp),
                         {"data/some_census.json": json.dumps({"c": ".rows[0].v"})})
            doc = price.measure(root)
        self.assertEqual(doc["status"], "OK")
        self.assertEqual(doc["counts"].get("regenerated"), 1)

    def test_a_test_literal_is_counted_but_is_not_the_price(self):
        """Тест меняется осознанно и вслух (инв. #16), а не ломается молча."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp),
                         {"spa_core/tests/test_a.py": 'C = ".rows[0].v"\n'})
            doc = price.measure(root)
        self.assertEqual(doc["status"], "OK")
        self.assertEqual(doc["counts"].get("test_literal"), 1)


class AbsenceIsItsOwnOutcomeNeitherEmptyNorUnmeasured(unittest.TestCase):

    def test_a_tracked_file_missing_from_disk_is_read_from_the_commit(self):
        """В боевом дереве так лежат четыре файла: git знает, диска нет.

        Ни «пусто» (тихо вынесло бы файл из знаменателя), ни «не измерено» на
        всю перепись (прибор молчал бы именно там, где нужен) — содержимое
        спрашивается у коммита, потому что вопрос про репозиторий.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp), {
                "scripts/thing_baseline.json": json.dumps([".rows[2].code"])})
            (root / "scripts/thing_baseline.json").unlink()
            doc = price.measure(root)
        self.assertEqual(doc["status"], "FINDING")
        self.assertEqual(doc["files_read_from_commit"], 1)

    def test_a_file_absent_from_both_disk_and_HEAD_is_UNMEASURED(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp), {"scripts/a.py": "x = 1\n"})
            # Файл добавлен в индекс и НЕ закоммичен, затем убран с диска:
            # `ls-files` о нём знает, а `HEAD` — нет.
            (root / "scripts/b.py").write_text('C = ".rows[0]"\n', encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "scripts/b.py"],
                           check=True, capture_output=True)
            (root / "scripts/b.py").unlink()
            doc = price.measure(root)
        self.assertEqual(doc["status"], "UNMEASURED")
        self.assertIn("scripts/b.py", doc["reason"])

    def test_no_git_at_the_root_is_UNMEASURED_with_a_named_cause(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc = price.measure(Path(tmp))
        self.assertEqual(doc["status"], "UNMEASURED")
        self.assertIn("ls-files", doc["reason"])

    def test_an_empty_repository_is_UNMEASURED_not_clean(self):
        """«Мерить нечего» не имеет права печататься как «держателей нет».

        Причина СВЕРЯЕТСЯ, а не только исход: мутация «пустой список — не отказ»
        этот тест ПЕРЕЖИЛА, потому что `UNMEASURED` получался окольно (выдуманный
        путь не читался с диска и попадал в «не прочитано»). Исход совпал, ответ
        был о другом — ровно тот дефект, который весь этот прибор и меряет.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "empty"
            root.mkdir()
            subprocess.run(["git", "init", "-b", _BRANCH, str(root)],
                           check=True, capture_output=True)
            doc = price.measure(root)
        self.assertEqual(doc["status"], "UNMEASURED")
        self.assertIn("пустой список", doc["reason"])
        self.assertNotIn("не прочитано", doc["reason"])


class ThreeOutcomesStayThreeAndEachIsReachable(unittest.TestCase):
    """Слей любые два, и «не измерено» станет неотличимо от «держателей нет»."""

    def test_the_three_names_are_distinct(self):
        self.assertEqual(len(set(price.STATUSES)), 3)

    def test_each_of_the_three_is_actually_reachable(self):
        """Имя, до которого нельзя дойти, — украшение, а не исход.

        Сцена на каждое: чистый контур · храповиковая база с позиционной
        координатой · каталог без git.
        """
        seen = set()
        with tempfile.TemporaryDirectory() as tmp:
            seen.add(price.measure(
                _repo(Path(tmp), {"scripts/a.py": "x = 1\n"}))["status"])
        with tempfile.TemporaryDirectory() as tmp:
            seen.add(price.measure(_repo(
                Path(tmp),
                {"scripts/b_baseline.json": json.dumps([".r[0]"])}))["status"])
        with tempfile.TemporaryDirectory() as tmp:
            seen.add(price.measure(Path(tmp))["status"])
        self.assertEqual(seen, set(price.STATUSES))


class ThePriceOfTheIdentityRuleStaysZeroInThisRepository(unittest.TestCase):
    """САМ ИНВАРИАНТ, а не только прибор — и читатель у него этот прогон.

    Правило `BY_VALUE` (ADR-502) безопасно ровно пока позиционную координату
    никто не держит ЧЕРЕЗ прогон. Замер 28.09 при доставке: чужих держателей
    НОЛЬ. Появится держатель — тест назовёт его файл, и решать придётся до того,
    как «ничего не снято» начнёт читаться как «нечего было снимать».
    """

    def test_no_foreign_holder_of_a_positional_coordinate_exists(self):
        doc = price.measure(_ROOT)
        # «Не измерено» здесь обязано ПАДАТЬ, а не проходить: зелёный тест на
        # непрочитанном дереве и есть подделка доказательства (класс ADR-468).
        self.assertIn(doc["status"], ("OK", "FINDING"), doc.get("reason"))
        self.assertEqual(doc["counts"].get("foreign", 0), 0,
                         price.render(doc))

    def test_the_report_names_what_it_does_not_prove(self):
        """Односторонность — часть ответа, а не сноска для внимательных."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp), {"scripts/a.py": "x = 1\n"})
            text = price.render(price.measure(root))
        self.assertIn("НЕ ДОКАЗЫВАЕТ", text)


if __name__ == "__main__":                                    # pragma: no cover
    unittest.main()
