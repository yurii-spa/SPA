"""Контроли переписи §-ов ТЗ приказа «Portfolio CIO» (ADR-1067).

Каждая проба здесь — положительный контроль НАСТОЯЩЕЙ ошибки, а не украшение
(`.claude/rules/deployment.md`, § «Проверка сторожа сторожей»):

* наивный греп по той же карточке даёт 80 кандидатов вместо 52 §-ов — население,
  которого нет (вложенные пункты владельца внутри §51 имеют ту же форму);
* реестр решений СОСТАВНОЙ (ADR-1046), и вопрос к ОДНОЙ его части объявил бы
  «адреса нет» у §, чей адрес уехал в архив;
* притязание на ДИАПАЗОН §-ов слабее строки про сам §, и слить оси значило бы
  зачесть адрес, которого нет;
* `§2.4` — раздел ЧУЖОГО документа, и зачесть его §2 ТЗ значило бы выдумать адрес;
* документ, НАЗВАННЫЙ владельцем внутри § и отсутствующий в дереве, обязан быть
  НАЗВАН — это и есть находка ADR-1067 про §6 (`PORTFOLIO_CIO_AS_IS.md`).

Сцены — одноразовые деревья в `$TMPDIR`; живое дерево читается только там, где
предмет пробы есть ЖИВОЙ ответ, и такая проба помечена явно.
"""

from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import unittest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import cio_tz_section_census as census  # noqa: E402


CARD_HEAD = """---
title: "TASK — Portfolio CIO"
status: in-progress
---

## Задание (из Telegram)

"""


def _card(sections, tail=""):
    """Карточка-сцена: §-ы цепью, затем произвольный хвост."""
    body = [CARD_HEAD]
    for number, title, inner in sections:
        body.append(f"{number}. {title}\n{inner}\n\n⸻\n\n")
    body.append(tail)
    return "".join(body)


def _scene(tmp, card_text, index_text="", archive_text="", chronicle=None):
    root = pathlib.Path(tmp)
    (root / "nimbalyst-local" / "tracker").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "decisions").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "journal").mkdir(parents=True, exist_ok=True)
    (root / census.CARD_REL).write_text(card_text, encoding="utf-8")
    (root / census.REGISTER_PARTS[0]).write_text(index_text, encoding="utf-8")
    (root / census.REGISTER_PARTS[1]).write_text(archive_text, encoding="utf-8")
    if chronicle is not None:
        (root / census.CHRONICLE_REL).write_text(chronicle, encoding="utf-8")
    return str(root)


class PopulationIsAChainNotAGrep(unittest.TestCase):
    """Население §-ов — ЦЕПЬ; вложенный перечень владельца §-ом не становится."""

    def test_nested_enumeration_inside_a_section_is_not_a_section(self):
        card = _card([
            (1, "Цель", "текст"),
            (2, "Проблема", "1. вложенный пункт\n2. второй вложенный"),
            (3, "Правило", "текст"),
        ])
        sections, naive = census.section_population(card)
        self.assertEqual([entry["section"] for entry in sections], [1, 2, 3])
        self.assertEqual(naive, 5, "наивная дверь обязана быть ИЗМЕРЕНА, а не спрятана")

    def test_the_naive_door_is_reported_so_the_next_reader_does_not_repeat_it(self):
        report = census.census(str(REPO_ROOT))  # ЖИВОЕ дерево: предмет — живой ответ
        self.assertGreater(report["naive_candidates"], report["population"])

    def test_a_card_without_a_chain_is_unmeasured_not_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(tmp, "## Задание\n\nникаких §-ов тут нет\n")
            with self.assertRaises(census.NotMeasured) as box:
                census.census(root)
            self.assertIn("цепь", str(box.exception))

    def test_a_section_body_ends_where_the_next_section_begins(self):
        card = _card([
            (1, "Первый", "тело ПЕРВОГО"),
            (2, "Второй", "тело ВТОРОГО"),
        ])
        sections, _ = census.section_population(card)
        self.assertIn("тело ПЕРВОГО", sections[0]["body"])
        self.assertNotIn("тело ВТОРОГО", sections[0]["body"])

    def test_the_tail_of_the_last_section_stops_at_the_next_header(self):
        """Ниже ТЗ живут заказы циклов — владельцем они не писаны.

        Замер 19.11: `PORTFOLIO_CIO_AS_IS.md`, названный в заказе G1056 ПОД ТЗ,
        зачёлся последнему §, потому что у него нет соседа и хвост шёл до EOF.
        """
        card = _card(
            [(1, "Первый", "тело"), (2, "Последний", "тело последнего")],
            tail="## Заказ следующему циклу\nподготовить APPENDED_DOCUMENT.md\n",
        )
        sections, _ = census.section_population(card)
        self.assertIn("тело последнего", sections[-1]["body"])
        self.assertNotIn("APPENDED_DOCUMENT.md", sections[-1]["body"])


class TheRegisterIsCompositeAndAnUnreadPartIsFailClosed(unittest.TestCase):
    """ADR-1046: реестр из двух частей; непрочитанная часть — НЕ «адреса нет»."""

    def test_an_address_living_only_in_the_archive_is_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(
                tmp,
                _card([(1, "Первый", "тело"), (2, "Второй", "тело")]),
                index_text="| ADR-999 | про другое |\n",
                archive_text="| ADR-500 | закрывает §2 приказа |\n",
            )
            report = census.census(root)
            row = report["sections"][1]
            self.assertEqual(row["verdict"], census.ADDRESSED)
            self.assertEqual(row["adr_exact"], ["500"])

    def test_a_missing_register_part_is_unmeasured_not_no_address(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(
                tmp,
                _card([(1, "Первый", "тело")]),
                index_text="| ADR-999 | про §1 приказа |\n",
            )
            os.remove(os.path.join(root, census.REGISTER_PARTS[1]))
            with self.assertRaises(census.NotMeasured) as box:
                census.census(root)
            self.assertIn("INDEX-ARCHIVE", str(box.exception))


class RangeIsItsOwnAxis(unittest.TestCase):
    """«ADR про §12…§14» не есть строка про §13 — оси РАЗНЫЕ."""

    def test_a_range_claim_lands_on_the_range_axis_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(
                tmp,
                _card([(number, f"§{number}", "тело") for number in range(1, 5)]),
                index_text="| ADR-700 | закрывает §2…§3 приказа |\n",
            )
            report = census.census(root)
            by_number = {row["section"]: row for row in report["sections"]}
            self.assertEqual(by_number[2]["adr_exact"], [])
            self.assertEqual(by_number[2]["adr_range_only"], ["700"])
            self.assertEqual(report["range_only"], [2, 3])

    def test_an_exact_row_outranks_the_range_so_the_weaker_claim_is_not_printed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(
                tmp,
                _card([(number, f"§{number}", "тело") for number in range(1, 5)]),
                index_text="| ADR-700 | §2…§3 |\n| ADR-701 | §2 точно |\n",
            )
            report = census.census(root)
            by_number = {row["section"]: row for row in report["sections"]}
            self.assertEqual(by_number[2]["adr_exact"], ["701"])
            self.assertEqual(by_number[2]["adr_range_only"], [])

    def test_a_section_of_a_foreign_document_is_not_credited_as_an_address(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(
                tmp,
                _card([(1, "Первый", "тело"), (2, "Второй", "тело")]),
                index_text="| ADR-800 | исполняет CLAUDE.md §2.4 |\n",
            )
            report = census.census(root)
            self.assertEqual(report["sections"][1]["verdict"], census.NO_ADDRESS)
            self.assertEqual(report["no_address_sections"], [1, 2])


class ANamedDocumentThatDoesNotExistIsNamed(unittest.TestCase):
    """Ось поручений: §, назвавший документ, и дерево, его не содержащее."""

    def test_a_named_missing_document_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(
                tmp,
                _card([(1, "Первый", "подготовить документ:\nPORTFOLIO_CIO_AS_IS.md\n")]),
                index_text="| ADR-900 | про §1 |\n",
            )
            report = census.census(root)
            self.assertEqual(
                report["named_artifacts_missing"], {"1": ["PORTFOLIO_CIO_AS_IS.md"]}
            )

    def test_the_axis_goes_quiet_once_the_document_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(
                tmp,
                _card([(1, "Первый", "подготовить документ:\nPORTFOLIO_CIO_AS_IS.md\n")]),
                index_text="| ADR-900 | про §1 |\n",
            )
            (pathlib.Path(root) / "docs" / "PORTFOLIO_CIO_AS_IS.md").write_text(
                "тело", encoding="utf-8"
            )
            report = census.census(root)
            self.assertEqual(report["named_artifacts_missing"], {})

    def test_a_lowercase_reference_is_not_mistaken_for_an_assignment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(
                tmp,
                _card([(1, "Первый", "см. docs/readme_local.md рядом\n")]),
                index_text="| ADR-900 | про §1 |\n",
            )
            report = census.census(root)
            self.assertEqual(report["named_artifacts_missing"], {})
            self.assertEqual(report["sections"][0]["named_artifacts"], [])


class TheChronicleAxisIsDeclaredUnmeasuredWithACause(unittest.TestCase):
    """Символ «§» не называет документ — и величина ошибки ИЗМЕРЕНА."""

    def test_the_axis_is_never_reported_as_measured(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(
                tmp,
                _card([(1, "Первый", "тело")]),
                index_text="| ADR-900 | §1 |\n",
                chronicle="цикл #1: ADR-980 § 6 исполнен; §1 приказа упомянут\n",
            )
            axis = census.census(root)["chronicle_axis"]
            self.assertFalse(axis["measured"])
            self.assertTrue(axis["reason"])
            self.assertEqual(axis["refs_total"], 2)
            self.assertEqual(axis["refs_owned_by_adr_sections"], 1)

    def test_an_absent_chronicle_is_still_a_named_cause_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(tmp, _card([(1, "Первый", "тело")]), index_text="| ADR-900 | §1 |\n")
            axis = census.census(root)["chronicle_axis"]
            self.assertFalse(axis["measured"])
            self.assertIn("не прочитан", axis["reason"])
            self.assertNotIn("refs_total", axis)


class ThreeOutcomesAreDistinguishableByExitCode(unittest.TestCase):
    """инв. #17: измерено · измерено и есть находка · НЕ ИЗМЕРЕНО."""

    def test_every_section_addressed_is_code_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(
                tmp,
                _card([(1, "Первый", "тело"), (2, "Второй", "тело")]),
                index_text="| ADR-900 | §1 и §2 |\n",
            )
            self.assertEqual(census.main(["--repo-root", root]), 0)

    def test_a_section_without_an_address_is_code_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(
                tmp,
                _card([(1, "Первый", "тело"), (2, "Второй", "тело")]),
                index_text="| ADR-900 | §1 |\n",
            )
            self.assertEqual(census.main(["--repo-root", root]), 1)

    def test_an_unreadable_tree_is_code_two_not_a_clean_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(census.main(["--repo-root", tmp]), 2)

    def test_the_blindness_is_printed_not_only_commented(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene(
                tmp,
                _card([(1, "Первый", "тело")]),
                index_text="| ADR-900 | §1 |\n",
            )
            text = census.render(census.census(root))
            self.assertIn("НЕ ЕСТЬ", text)


if __name__ == "__main__":
    unittest.main()
