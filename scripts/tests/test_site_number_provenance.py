"""Сторож провенанса чисел сайта (идея владельца 2026-09-10, ADR-312).

Авария, ради которой он написан: строка «~3,3 % фактических» была вписана руками
в ШЕСТНАДЦАТИ местах. Между собой шестнадцать литералов не расходились ни на йоту —
проверка на расхождение (`site_content_audit::METRIC_DIVERGENCE`) была зелёной.
Трек к тому дню давал 5,3 %. Согласованность не есть правда.

Каждый тест ниже — либо сцена этой аварии, либо соседний исход, которого у сторожа
обязано быть четыре: `sourced`, `declared`, `UNDECLARED`, `unmeasured`.
Герметичны: сеть не трогается, страницы — фикстуры во временном каталоге.
"""
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_REPO = Path(__file__).resolve().parents[2]
_TARGET = _REPO / "scripts" / "site_number_provenance.py"


def _load():
    spec = importlib.util.spec_from_file_location("spa_site_number_provenance", _TARGET)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _page(root: Path, rel: str, body: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


class FourOutcomes(unittest.TestCase):
    def setUp(self):
        self.m = _load()
        self.td = TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.root = Path(self.td.name)

    def test_a_typed_rate_with_no_source_is_a_finding(self):
        """СЦЕНА АВАРИИ: страница печатает «~3,3 % фактических» и ничего не импортирует."""
        _page(self.root, "pages/hero.astro",
              "---\n---\n<p>Our live track runs at ~3.3% realized.</p>\n")
        rep = self.m.scan(self.root)
        self.assertEqual(self.m.undeclared(rep), ["pages/hero.astro"])

    def test_sixteen_agreeing_literals_are_sixteen_findings_not_zero(self):
        """Согласованность — не провенанс: расхождения нет, а находок шестнадцать."""
        for i in range(16):
            _page(self.root, f"pages/p{i:02d}.astro", "---\n---\n<p>~3.3% realized</p>\n")
        rep = self.m.scan(self.root)
        self.assertEqual(len(self.m.undeclared(rep)), 16)

    def test_a_page_reading_the_snapshot_is_sourced(self):
        _page(self.root, "pages/track.astro",
              "---\nimport snap from '../data/track_snapshot.json';\n---\n"
              "<p>{snap.paper_apy_pct}% за {snap.real_track_days} дней · 3.3%</p>\n")
        rep = self.m.scan(self.root)
        self.assertEqual(self.m.undeclared(rep), [])
        self.assertEqual([r["verdict"] for r in rep["rows"]], ["sourced"])

    def test_a_page_reading_the_constitution_is_sourced(self):
        _page(self.root, "pages/risk.astro",
              "---\nimport c from '../lib/constitution.json';\n---\n<p>$100,000</p>\n")
        self.assertEqual(self.m.undeclared(self.m.scan(self.root)), [])

    def test_a_declared_illustrative_page_is_allowed(self):
        _page(self.root, "pages/academy/01.astro",
              "---\n// site-numbers: illustrative — учебный пример, не претензия о системе\n"
              "---\n<p>Если APY 20%, то…</p>\n")
        rep = self.m.scan(self.root)
        self.assertEqual(self.m.undeclared(rep), [])
        self.assertEqual(rep["rows"][0]["why"],
                         "illustrative: учебный пример, не претензия о системе")

    def test_a_declaration_without_a_reason_does_not_count(self):
        """«И так понятно» причиной не является — объявление без причины не разбирается."""
        _page(self.root, "pages/academy/02.astro",
              "---\n// site-numbers: illustrative\n---\n<p>20% APY</p>\n")
        self.assertEqual(self.m.undeclared(self.m.scan(self.root)), ["pages/academy/02.astro"])

    def test_an_unknown_class_does_not_count(self):
        _page(self.root, "pages/x.astro",
              "---\n// site-numbers: whatever — потому что\n---\n<p>20%</p>\n")
        self.assertEqual(self.m.undeclared(self.m.scan(self.root)), ["pages/x.astro"])

    def test_missing_pages_dir_is_unmeasured_not_clean(self):
        """ЧЕТВЁРТЫЙ исход: каталога нет ⇒ громко «не измерено», а не пустой список."""
        rep = self.m.scan(self.root / "нет-такого")
        self.assertTrue(rep["unmeasured"], rep)
        self.assertEqual(rep["rows"], [])
        v = self.m.verdict(rep, [])
        self.assertTrue(v["unmeasured"])

    def test_an_empty_pages_dir_is_unmeasured_not_clean(self):
        (self.root / "pages").mkdir()
        rep = self.m.scan(self.root)
        self.assertTrue(rep["unmeasured"], rep)

    def test_an_unreadable_baseline_is_unmeasured_not_an_empty_list(self):
        p = self.root / "нет.json"
        base, why = self.m.load_baseline(p)
        self.assertEqual(base, [])
        self.assertIn("не прочитана", why)


class WhatIsNotAClaim(unittest.TestCase):
    """Положительные контроли ОБРАТНОЙ стороны: сторож, краснеющий на всё, — не сторож."""

    def setUp(self):
        self.m = _load()
        self.td = TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.root = Path(self.td.name)

    def test_css_percentages_are_not_claims(self):
        _page(self.root, "pages/a.astro",
              "---\n---\n<div/>\n<style>.d{border-radius:50%; width:33.3%}</style>\n")
        self.assertEqual(self.m.undeclared(self.m.scan(self.root)), [])

    def test_a_computed_expression_is_not_a_literal(self):
        """`{s.apy}%` литералом не является вовсе: печатается не число, а вычисление.
        Вердикт поэтому `no_claims`, а не `sourced` — сторожу нечего засчитывать."""
        _page(self.root, "pages/b.astro",
              "---\nimport s from '../data/track_snapshot.json';\n---\n<p>{s.apy}%</p>\n")
        rows = self.m.scan(self.root)["rows"]
        self.assertEqual(rows[0]["verdict"], "no_claims")
        self.assertEqual(self.m.undeclared(self.m.scan(self.root)), [])

    def test_a_number_in_a_comment_is_not_printed(self):
        _page(self.root, "pages/c.astro",
              "---\n---\n<!-- было 3.3% -->\n{/* и тут 3.3% */}\n<p>текст</p>\n")
        rows = self.m.scan(self.root)["rows"]
        self.assertEqual(rows[0]["verdict"], "no_claims")

    def test_a_lesson_number_is_not_a_claim(self):
        _page(self.root, "pages/d.astro", "---\n---\n<h1>Урок 14 из 20, 2026 год</h1>\n")
        rows = self.m.scan(self.root)["rows"]
        self.assertEqual(rows[0]["verdict"], "no_claims")


class Ratchet(unittest.TestCase):
    """База может ТОЛЬКО уменьшаться. Дописывать в неё, чтобы погасить, запрещено."""

    def setUp(self):
        self.m = _load()

    def test_the_live_site_introduces_no_page_outside_the_baseline(self):
        rep = self.m.scan()
        base, why = self.m.load_baseline()
        self.assertEqual(why, "", f"база не прочитана: {why}")
        v = self.m.verdict(rep, base)
        self.assertEqual(v["unmeasured"], [], v["unmeasured"])
        self.assertEqual(
            v["new_undeclared"], [],
            "новая страница печатает число-претензию без источника и без объявления.\n"
            "Читать .claude/rules/site-numbers.md. Дописывать файл в базу ЗАПРЕЩЕНО:\n"
            + "\n".join(v["new_undeclared"]))

    def test_the_baseline_lists_no_page_that_is_already_sourced(self):
        """База, отставшая от дерева, тихо разрешала бы регресс на уже починенной странице."""
        rep = self.m.scan()
        base, why = self.m.load_baseline()
        self.assertEqual(why, "")
        v = self.m.verdict(rep, base)
        self.assertEqual(v["fixed_since_baseline"], [],
                         "эти страницы уже с провенансом — удалить их из базы: "
                         + ", ".join(v["fixed_since_baseline"]))

    def test_the_population_is_not_empty(self):
        """Пустой замер зеленил бы храповик, ничего не измерив."""
        rep = self.m.scan()
        self.assertGreater(len(rep["rows"]), 50, "страниц найдено подозрительно мало")
        self.assertGreater(sum(1 for r in rep["rows"] if r["verdict"] == "sourced"), 10)


if __name__ == "__main__":
    unittest.main()
