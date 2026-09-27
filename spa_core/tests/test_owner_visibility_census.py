"""Тесты §49 `Owner visibility` — `spa_core/monitoring/owner_visibility_census.py`.

Каждый тест — положительный контроль: либо воспроизводит то, что замер
2026-09-27 нашёл на живых данных, либо ломает РОВНО ОДНУ координату контура и
требует, чтобы вердикт изменился с названным звеном (`.claude/rules/acceptance.md`
п. 3).

Живой `data/` не читается и не пишется ни одним тестом — каталог состояния
всегда `tmp_path`, иначе вердикт зависел бы от хоста. Журнал решений собирается
НАСТОЯЩИМ писательским правилом имени (`allocation_rationale.history_filename`),
а читается НАСТОЯЩИМ загрузчиком и НАСТОЯЩИМ слоем отображения: контур гоняется
целиком, а не пересказывается (урок ADR-480 — `measured=True` при отсутствующем
артефакте).

Время сюда не входит ни одним литералом-якорем: предмет замера — доставка
числа, а не её свежесть. Единственные даты — поле `cycle_date` внутри
сфабрикованной записи, и оно не сравнивается ни с какими часами.
"""
# FROZEN-DATE-OK: injected-clock — литерал NOW передаётся аргументом `now=` в
# M.run_census(...) и M.run(...); обе стороны закреплены, стенных часов файл не
# спрашивает ни разу. Даты внутри LIVE_RECORD (`cycle_date`, `generated_at`) ни с
# какими часами не сравниваются: предмет замера — доставка числа, не её свежесть.
from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import owner_visibility_census as M

#: Часы передаются аргументом ВСЕГДА — ни один тест не спрашивает время у хоста.
NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)

#: Дословно те четыре предмета, что несёт живая запись `shadow-hist-v2` книги
#: conservative на день замера. Ни одно число здесь не придумано.
LIVE_RECORD = {
    "schema": "shadow-hist-v2",
    "book_id": "conservative",
    "cycle_date": "2026-09-27",
    "generated_at": "2026-09-27T06:00:04.413951+00:00",
    "decision_id": "adr060-shadow-2026-09-27",
    "policy_version": "v1.1",
    "mode": "paper",
    "capital_usd": 100000.0,
    "book_apy_pp": 4.62636,
    "target_apy_pp": 4.856832,
    "gain_pp": 0.230472,
    "required_gain_pp": 0.5,
    "verdict": "HOLD",
    "cost_usd": 90.91,
    "payback_days": 143.97,
    "turnover_usd": 32894.74,
    "turnover_frac": 0.328947,
    "warnings_count": 0,
    "reasons": ["gain_below_band:0.230pp<0.500pp", "payback_too_long:144.0d"],
    "legs": [{"protocol": "aave_v3", "delta_usd": 32894.74,
              "direction": "increase"}],
    "current_positions": {"compound_v3": 40000.0, "maple": 20000.0},
    "target_positions": {"aave_v3": 37894.74, "compound_v3": 33157.89},
    "gates": {"gain_above_band": False, "has_legs": True,
              "payback_within_horizon": False, "cooldown_ok": True,
              "min_hold_ok": True, "move_amount_ok": False,
              "move_turnover_ok": False, "week_turnover_ok": False,
              "day_turnover_ok": False, "target_fully_evidenced": True},
}


def _write_ledger(data_dir: Path, record: dict, book_id: str) -> None:
    """Журнал книги — НАСТОЯЩИМ правилом имени писателя, не своей копией."""
    from spa_core.paper_trading.allocation_rationale import history_filename
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / history_filename(book_id)
    row = dict(record, book_id=book_id)
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n",
                    encoding="utf-8")


# ─────────────────── предмет: доставка одного числа ──────────────────────────

class TestSubjectDelivery(unittest.TestCase):
    """Зачёт — равенство ЗНАЧЕНИЙ, а не совпадение подстроки (ADR-333)."""

    def _score(self, subject_key: str, delivered: dict) -> dict:
        spec = {s[0]: s for s in M.SUBJECTS}[subject_key]
        return M.score_subject(spec[0], spec[1], spec[2], spec[3],
                               LIVE_RECORD, delivered)

    def test_own_field_with_equal_value_is_the_only_pass(self):
        row = self._score("current_apy",
                          {"available": True, "apy_now_pp": 4.62636})
        self.assertEqual(row["delivery"], M.DELIVERY_FIELD)
        self.assertEqual(row["delivered_as"], "apy_now_pp")

    def test_a_field_holding_the_number_as_TEXT_is_not_a_pass(self):
        """Строка «4.62636» полем не является: подписать её как число нельзя.

        Иначе прибор зачёл бы прозу, переложенную в отдельный ключ, — тот же
        обход, что запрещает ADR-333.
        """
        row = self._score("current_apy",
                          {"available": True, "apy_text": "4.62636"})
        self.assertEqual(row["delivery"], M.DELIVERY_PROSE)

    def test_number_only_inside_prose_is_prose_only_not_field(self):
        """Живой случай книги conservative: Yield Gap живёт кодом причины."""
        row = self._score("yield_gap", {
            "available": True, "verdict": "HOLD",
            "why": "gain_below_band:0.230pp<0.500pp; payback_too_long:144.0d",
        })
        self.assertEqual(row["delivery"], M.DELIVERY_PROSE)
        self.assertEqual(row["prose_form"], "0.230")

    def test_number_nowhere_is_absent(self):
        row = self._score("optimal_apy", {
            "available": True, "verdict": "HOLD",
            "why": "no_material_legs. Критерии: не пройдено: has_legs.",
        })
        self.assertEqual(row["delivery"], M.DELIVERY_ABSENT)

    def test_recommendation_reaches_the_owner_as_a_field(self):
        """То, что ДОХОДИТ на живых данных, обязано читаться как зачёт."""
        row = self._score("recommendation",
                          {"available": True, "verdict": "HOLD"})
        self.assertEqual(row["delivery"], M.DELIVERY_FIELD)

    def test_a_decorated_recommendation_is_not_an_equal_field(self):
        row = self._score("recommendation",
                          {"available": True, "verdict": "HOLD (advisory)"})
        self.assertNotEqual(row["delivery"], M.DELIVERY_FIELD)

    def test_journal_without_the_key_is_UNMEASURED_not_absent(self):
        """Нет предмета — нет замера. «Не записано» ≠ «не доходит» (инв. #17)."""
        row = M.score_subject("current_apy", "book_apy_pp", "current APY",
                              "number", {"verdict": "HOLD"},
                              {"available": True})
        self.assertEqual(row["delivery"], M.DELIVERY_UNMEASURED)
        self.assertFalse(row["recorded"])
        self.assertIn("book_apy_pp", row["reason"])

    def test_book_the_display_layer_calls_unavailable_is_UNMEASURED(self):
        row = self._score("current_apy",
                          {"available": False,
                           "reason": "no_decision_record_for_book"})
        self.assertEqual(row["delivery"], M.DELIVERY_UNMEASURED)
        self.assertIn("no_decision_record_for_book", row["reason"])

    def test_zero_is_a_value_and_delivers(self):
        """Ноль — ЗНАЧЕНИЕ, а не отсутствие (инв. #17)."""
        row = M.score_subject("yield_gap", "gain_pp", "Yield Gap", "number",
                              {"gain_pp": 0.0}, {"available": True,
                                                 "gain_pp": 0.0})
        self.assertEqual(row["delivery"], M.DELIVERY_FIELD)

    def test_a_DIFFERENT_number_in_the_field_is_not_delivery(self):
        """Мутация «допуск равенства настежь» (1e-9 → 1e9) пережила первую
        редакцию батареи: ни один тест не требовал, чтобы ДРУГОЕ число полем не
        зачлось. Без этого прибор объявил бы доставленным любое числовое поле.
        """
        row = self._score("current_apy",
                          {"available": True, "apy_now_pp": 9.99})
        self.assertNotEqual(row["delivery"], M.DELIVERY_FIELD)

    def test_a_neighbouring_number_within_a_hair_is_still_not_it(self):
        row = self._score("current_apy",
                          {"available": True, "apy_now_pp": 4.62637})
        self.assertNotEqual(row["delivery"], M.DELIVERY_FIELD)

    def test_a_bool_is_not_the_number(self):
        row = M.score_subject("yield_gap", "gain_pp", "Yield Gap", "number",
                              {"gain_pp": 1.0}, {"available": True,
                                                 "gain_pp": True})
        self.assertNotEqual(row["delivery"], M.DELIVERY_FIELD)


class TestProseMatching(unittest.TestCase):
    """Ось прозы — ровно та поломка, которую нашла приёмка этого же цикла."""

    def test_a_single_rounded_digit_is_NOT_the_number(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ на МОЮ поломку.

        Первая редакция округляла `4.62636` до `"5"`, находила односимвольную
        подстроку в любой прозе и объявляла предмет дошедшим «прозой» — ошибка
        в сторону ОПРАВДАНИЯ. Проза, в которой есть цифра 5 и нет числа, обязана
        читаться как `absent`.
        """
        row = M.score_subject("current_apy", "book_apy_pp", "current APY",
                              "number", {"book_apy_pp": 4.62636},
                              {"available": True,
                               "where": "Держит: 5 позиций на $95,000."})
        self.assertEqual(row["delivery"], M.DELIVERY_ABSENT)

    def test_form_glued_to_another_digit_is_not_a_hit(self):
        self.assertFalse(M._found_in_prose("0.230", "выгода 10.2304 пп"))

    def test_form_at_a_digit_boundary_is_a_hit(self):
        self.assertTrue(M._found_in_prose("0.230", "gain:0.230pp<0.500pp"))

    def test_renderings_never_go_below_two_decimals(self):
        for form in M._renderings(4.62636):
            head = form.split(".")[0]
            if "." in form:
                self.assertGreaterEqual(len(form.split(".")[1]), 2, form)
            else:  # pragma: no cover — целых форм перечень не содержит
                self.fail(f"целая форма опознаёт цифру, а не число: {head}")


# ─────────────────────── ось поверхностей владельца ──────────────────────────

class TestSurfaceAxis(unittest.TestCase):
    """Читатель — АРГУМЕНТ вызова. Упоминание пути читателем не является."""

    def _tree(self, root: Path, files: dict) -> Path:
        for rel, body in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        return root

    def test_a_call_argument_is_a_caller(self):
        with TemporaryDirectory() as td:
            root = self._tree(Path(td), {
                "landing/src/pages/admin/portfolio-summary.astro":
                    "const r = await jget('/api/live/books/brief');\n",
            })
            axis = M.measure_surfaces(root)
            self.assertEqual(
                axis["callers"],
                ["landing/src/pages/admin/portfolio-summary.astro"])
            self.assertEqual(axis["mentions_only"], [])

    def test_a_comment_mention_is_NOT_a_caller(self):
        """Живая форма: у настоящей страницы путь встречается и в шапке."""
        with TemporaryDirectory() as td:
            root = self._tree(Path(td), {
                "docs/STATE.md": "читает /api/live/books/brief\n",
            })
            axis = M.measure_surfaces(root)
            self.assertEqual(axis["callers"], [])
            self.assertEqual(axis["mentions_only"], ["docs/STATE.md"])

    def test_a_file_that_both_mentions_and_calls_counts_as_a_caller(self):
        with TemporaryDirectory() as td:
            root = self._tree(Path(td), {
                "landing/src/pages/admin/portfolio-summary.astro":
                    "// /api/live/books/brief — phase C\n"
                    "const r = await jget('/api/live/books/brief');\n",
            })
            axis = M.measure_surfaces(root)
            self.assertEqual(len(axis["callers"]), 1)
            self.assertEqual(axis["mentions_only"], [])

    def test_the_probe_lives_outside_the_scanned_population(self):
        """ADR-333: прибор, нашедший себя, объявил бы доставку налаженной.

        Здесь стоял тест на перечень-исключение из двух своих путей, и мутация
        показала его ВЫРОЖДЕННЫМ: снятие перечня не меняло вердикта, потому что
        обоих файлов в населении нет и так. Настоящая защита — население: ни
        `spa_core/monitoring/`, ни `spa_core/tests/` в `SURFACE_DIRS` не входят.
        Мерится ИМЕННО она, и добавление своего каталога в население покраснит
        этот тест.
        """
        own = Path(M.__file__).resolve()
        repo_root = own.parents[2]
        own_rel = own.relative_to(repo_root).as_posix()
        for scanned in M.SURFACE_DIRS:
            self.assertFalse(
                own_rel.startswith(scanned.rstrip("/") + "/"),
                f"прибор {own_rel} попал в население оси через {scanned} — "
                f"он найдёт САМ СЕБЯ и объявит доставку налаженной")

    def test_the_probes_own_endpoint_constant_is_not_a_caller(self):
        """Форма, которой прибор нашёл бы себя: константа рядом с вызовом."""
        with TemporaryDirectory() as td:
            root = self._tree(Path(td), {
                "scripts/some_probe.py":
                    "BRIEF_ENDPOINT = '/api/live/books/brief'\n",
            })
            axis = M.measure_surfaces(root)
            self.assertEqual(axis["callers"], [])
            self.assertEqual(axis["mentions_only"], ["scripts/some_probe.py"])

    def test_a_test_file_is_not_an_owner_surface(self):
        with TemporaryDirectory() as td:
            root = self._tree(Path(td), {
                "scripts/tests/test_x.py": "jget('/api/live/books/brief')\n",
            })
            self.assertEqual(M.measure_surfaces(root)["callers"], [])

    def test_no_repo_root_is_UNMEASURED_with_a_named_reason(self):
        axis = M.measure_surfaces(None)
        self.assertFalse(axis["measured"])
        self.assertTrue(axis["reason"])

    def test_missing_repo_root_is_UNMEASURED_not_empty(self):
        axis = M.measure_surfaces(Path("/nonexistent-tree-owner-visibility"))
        self.assertFalse(axis["measured"])
        self.assertIn("корня дерева нет", axis["reason"])


class TestNeighbourRates(unittest.TestCase):
    """Место, занятое похожим именем, владелец не заметит пустым."""

    def test_names_the_other_rate_the_surface_prints(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            rel = "landing/src/pages/admin/portfolio-summary.astro"
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text("fmtPct(b.annualized_apy_pct)\n",
                                    encoding="utf-8")
            axis = M.measure_neighbour_rates(root, [rel])
            self.assertEqual(axis["by_surface"][rel], ["annualized_apy_pct"])

    def test_no_surfaces_is_UNMEASURED_not_clean(self):
        axis = M.measure_neighbour_rates(Path("."), [])
        self.assertFalse(axis["measured"])
        self.assertTrue(axis["reason"])


# ──────────────────────── контур целиком, на диске ───────────────────────────

class TestWholeContour(unittest.TestCase):
    """Настоящий загрузчик + настоящий слой отображения + настоящий артефакт."""

    def test_live_shape_loses_all_three_numbers_and_is_CRITICAL(self):
        """Воспроизводит замер 27.09 на КАЖДОЙ из трёх книг."""
        with TemporaryDirectory() as td:
            root = Path(td)
            data = root / "data"
            for book in M.BOOKS:
                _write_ledger(data, LIVE_RECORD, book)
            report = M.run_census(data, now=NOW, repo_root=root)
            self.assertTrue(report["measured"])
            self.assertEqual(report["status"], M.STATUS_CRITICAL)
            self.assertEqual(report["subjects_total"], 12)
            #: рекомендация доходит по каждой книге — и только она
            self.assertEqual(report["delivered_as_field"], 3)
            for book, data_row in report["books"].items():
                self.assertEqual(data_row["delivered_as_field"],
                                 ["recommendation"], book)
            self.assertEqual(report["prose_only"] + report["absent"], 9)
            self.assertEqual(report["recorded_but_not_delivered"], 9)

    def test_a_display_layer_that_passes_the_numbers_is_OK(self):
        """Обратная сторона: доставь поля — и сторож ЗЕЛЕНЕЕТ.

        Без этого теста прибор был бы красен по построению, а такой учит себя
        игнорировать.
        """
        with TemporaryDirectory() as td:
            root = Path(td)
            data = root / "data"
            for book in M.BOOKS:
                _write_ledger(data, LIVE_RECORD, book)

            def fixed_payload(_data_dir):
                return {book: {"available": True, "verdict": "HOLD",
                               "apy_now_pp": LIVE_RECORD["book_apy_pp"],
                               "apy_opt_pp": LIVE_RECORD["target_apy_pp"],
                               "gain_pp": LIVE_RECORD["gain_pp"]}
                        for book in M.BOOKS}

            import spa_core.paper_trading.cio_brief as brief_mod
            original = brief_mod.build_books_brief
            brief_mod.build_books_brief = fixed_payload
            try:
                report = M.run_census(data, now=NOW, repo_root=root)
            finally:
                brief_mod.build_books_brief = original
            self.assertEqual(report["status"], M.STATUS_OK)
            self.assertEqual(report["delivered_as_field"], 12)
            self.assertEqual(report["recorded_but_not_delivered"], 0)

    def test_no_ledger_at_all_is_UNMEASURED_with_a_reason(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            data = root / "data"
            data.mkdir()
            report = M.run_census(data, now=NOW, repo_root=root)
            self.assertFalse(report["measured"])
            self.assertEqual(report["status"], M.STATUS_UNMEASURED)
            self.assertTrue(report["reason"])
            #: третий исход НЕ выдаётся за «доходит»
            self.assertEqual(report["delivered_as_field"], 0)

    def test_missing_data_dir_is_UNMEASURED_not_clean(self):
        report = M.run_census(Path("/nonexistent-owner-visibility"), now=NOW,
                              repo_root=Path("."))
        self.assertFalse(report["measured"])
        self.assertIn("каталога данных нет", report["reason"])

    def test_unmeasurable_surface_axis_never_reads_as_OK(self):
        """Сломано ОДНО звено — ось поверхностей — и вердикт обязан измениться."""
        with TemporaryDirectory() as td:
            root = Path(td)
            data = root / "data"
            for book in M.BOOKS:
                _write_ledger(data, LIVE_RECORD, book)
            report = M.run_census(data, now=NOW, repo_root=None)
            self.assertEqual(report["status"], M.STATUS_UNMEASURED)
            self.assertFalse(report["surfaces"]["measured"])

    def test_stage_leaves_the_artifact_ON_DISK(self):
        """Урок ADR-480: `measured=True` при отсутствующем артефакте.

        Проверяется ФАЙЛ, а не возвращённый словарь.
        """
        with TemporaryDirectory() as td:
            root = Path(td)
            data = root / "data"
            for book in M.BOOKS:
                _write_ledger(data, LIVE_RECORD, book)
            out = M.run(root=str(root), now=NOW)
            self.assertTrue(out["measured"])
            path = data / M.ARTIFACT_NAME
            self.assertTrue(path.is_file(), "артефакта нет НА ДИСКЕ")
            doc = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(doc["schema"], M.SCHEMA)
            self.assertEqual(doc["status"], M.STATUS_CRITICAL)

    def test_stage_leaves_an_artifact_even_when_UNMEASURED(self):
        """Иначе шаг 0-офис не отличит «не измерено» от «ступень не запускалась»."""
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "data").mkdir()
            out = M.run(root=str(root), now=NOW)
            self.assertFalse(out["measured"])
            path = root / "data" / M.ARTIFACT_NAME
            self.assertTrue(path.is_file())
            doc = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(doc["status"], M.STATUS_UNMEASURED)
            self.assertTrue(doc["reason"])


class TestReport(unittest.TestCase):
    """Отчёт шага 0-офис: находка обязана быть НАЗВАНА, а не посчитана."""

    def _report(self, root: Path) -> dict:
        data = root / "data"
        for book in M.BOOKS:
            _write_ledger(data, LIVE_RECORD, book)
        return M.run_census(data, now=NOW, repo_root=root)

    def test_summary_line_names_the_criterion_and_the_counts(self):
        with TemporaryDirectory() as td:
            report = self._report(Path(td))
            line = M.summary_line(report)
            self.assertIn("Owner visibility", line)
            self.assertIn("CRITICAL", line)

    def test_unmeasured_summary_says_so_in_words(self):
        doc = M._unmeasured("журнал решений не прочитан", NOW)
        self.assertIn("НЕ ИЗМЕРЕНО", M.summary_line(doc))

    def test_report_names_the_owners_OWN_words_and_the_journal_key(self):
        with TemporaryDirectory() as td:
            lines = M.format_report(self._report(Path(td)))
            body = "\n".join(lines)
            self.assertIn("current APY", body)
            self.assertIn("book_apy_pp", body)
            self.assertIn("target_apy_pp", body)

    def test_report_states_what_it_does_NOT_measure(self):
        with TemporaryDirectory() as td:
            lines = M.format_report(self._report(Path(td)))
            self.assertTrue(any("НЕ ДОКЛАДЫВАЕТ" in ln for ln in lines))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
