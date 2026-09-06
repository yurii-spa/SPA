"""Тесты §44 ТЗ CIO — `spa_core/monitoring/cio_explainability.py`.

Каждый тест — положительный контроль на замер 2026-09-06: либо воспроизводит
то, что замер нашёл в живом объяснении, либо ломает ровно одну координату
модуля и требует, чтобы вердикт изменился.

Время сюда не входит ни одним литералом: предмет замера — состав фразы, а не
её свежесть. Живой `data/` не читается и не пишется ни одним тестом — каталог
состояния всегда `tmp_path`, иначе вердикт зависел бы от хоста.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from spa_core.monitoring import cio_explainability as M


# ─────────────────────── сцена: живое объяснение 06.09 ──────────────────────
#
# Дословно то, что `cio_brief` выдал по книге conservative в день замера, и
# запись, из которой он построен. Ни одно число здесь не придумано.

LIVE_BRIEF = {
    "available": True,
    "where": ("Держит: compound_v3 ($40,000), fluid_usdc ($20,000), maple "
              "($20,000). Предложенный ход: −compound_v3 ($2,105), "
              "−fluid_usdc ($12,632), −morpho_blue_base ($7,368), "
              "+pendle ($20,000)."),
    "how_much": "Оборот $22,105 (22.1% капитала), стоимость $64.89.",
    "why": ("reversal_of_recent_move:['compound_v3', 'fluid_usdc', "
            "'morpho_blue_base']; move_turnover_over_budget:22.1%>15%; "
            "week_turnover_over_budget. Критерии: не пройдено: оборот хода в "
            "бюджете, недельный оборот в бюджете."),
    "why_now": "рутинно — без заметных изменений.",
}

LIVE_RECORD = {
    "cycle_date": "2026-09-06",
    "verdict": "HOLD",
    "legs": [
        {"protocol": "compound_v3", "direction": "decrease", "delta_usd": -2105.26},
        {"protocol": "fluid_usdc", "direction": "decrease", "delta_usd": -12631.58},
        {"protocol": "morpho_blue_base", "direction": "decrease", "delta_usd": -7368.42},
        {"protocol": "pendle", "direction": "increase", "delta_usd": 20000.0},
    ],
    "apy_evidenced_pct": {"aave_v3": 3.5946, "compound_v3": 4.8179,
                          "fluid_usdc": 4.87, "maple": 4.9794,
                          "morpho_blue_base": 4.2405, "pendle": 14.0048},
    "book_apy_pp": 4.50082,
    "target_apy_pp": 6.263275,
    "cost_usd": 64.89,
    "payback_days": 13.44,
    "current_positions": {"compound_v3": 40000.0, "fluid_usdc": 20000.0,
                          "maple": 20000.0},
    "gates": {"move_turnover_ok": False, "week_turnover_ok": False,
              "gain_above_band": True},
}

MARGINAL = {"measurements": [{"apy_at_size_pct": 13.91}]}
RISK_CHECK = {"gate": "WARN"}


def _measure(brief=None, rec=None, **kw):
    kw.setdefault("marginal", MARGINAL)
    kw.setdefault("risk_check", RISK_CHECK)
    return M.measure_brief(brief or LIVE_BRIEF, rec or LIVE_RECORD, **kw)


def _outcome(got: dict, fact: str) -> str:
    return next(f["outcome"] for f in got["facts"] if f["fact"] == fact)


# ─────────────────────────── положительный контроль ─────────────────────────

class TestPositiveControl(unittest.TestCase):
    """Детекторы обязаны УМЕТЬ увидеть факт. Иначе «не произнесено» — не
    находка, а неисправность измерителя."""

    def test_owner_own_example_scores_eight_of_eight(self):
        got = M.run_control()
        self.assertTrue(got["passed"], got["reason"])
        self.assertEqual(got["spoken"], len(M.OWNER_FACTS))
        self.assertEqual(got["machine_tokens"], [])

    def test_control_is_not_an_ornament_broken_detector_fails_it(self):
        """Сломанный поиск числа обязан ронять контроль. Без этого теста
        контроль мог бы проходить по причинам, к детекторам не относящимся."""
        with mock.patch.object(M, "_find_number", return_value=None):
            got = M.run_control()
        self.assertFalse(got["passed"])
        self.assertIn("source_rate", got["missed"])

    def test_control_outranks_a_critical_finding(self):
        """Сорванный контроль обязан гасить отчёт ПЕРВОЙ ветвью. Без этого
        теста вердикт `UNCHECKED` приходил вторым путём — из непустого списка
        `unchecked`, — и подмена самой ветви оставалась незамеченной."""
        with mock.patch.object(M, "run_control",
                               return_value={"passed": False, "spoken": 0,
                                             "expected": 8, "missed": ["x"],
                                             "machine_tokens": [],
                                             "reason": "сломан"}), \
             mock.patch.object(M, "_findings",
                               return_value=([{"severity": "CRITICAL",
                                               "code": "c", "message": "m"}],
                                             [])):
            doc = M.run(root=M.REPO_ROOT, data_dir="/nonexistent", write=False)
        self.assertEqual(doc["counts"]["critical"], 1)
        self.assertEqual(doc["overall"], "UNCHECKED")

    def test_failed_control_makes_the_whole_report_unchecked(self):
        """Fail-CLOSED: детектор, не увидевший факт там, где он заведомо есть,
        не имеет права утверждать, что где-то его нет."""
        with mock.patch.object(M, "_find_number", return_value=None):
            doc = M.run(root=str(Path(M.REPO_ROOT)), data_dir="/nonexistent",
                        write=False)
        self.assertEqual(doc["overall"], "UNCHECKED")
        self.assertFalse(doc["control"]["passed"])
        self.assertEqual(doc["findings"], [])
        self.assertTrue(any("положительный контроль" in u
                            for u in doc["unchecked"]))


# ──────────────────────── поиск числа: границы и щедрость ───────────────────

class TestNumberDetection(unittest.TestCase):

    def test_a_number_at_the_very_start_of_the_text_is_found(self):
        """Найдено мутацией: `before in ".,"` истинно на пустой строке, потому
        что пустая строка — подстрока любой. Число, стоящее ПЕРВЫМ, не
        находилось никогда, и снятие соседнего ограждения ничего не меняло —
        до него не доходило."""
        self.assertIsNotNone(M._find_number("13.44 дн. окупаемость", "13.44"))

    def test_leading_digit_alone_blocks_the_match(self):
        """Ограждение СЛЕВА проверяется отдельно: в `14.8` у `4.8` слева цифра,
        а справа пробел — правое ограждение здесь не при чём."""
        self.assertIsNone(M._find_number("ставка 14.8 пп", "4.8"))

    def test_trailing_digit_alone_blocks_the_match(self):
        """И ограждение СПРАВА отдельно: у `13.44` в `13.442` слева начало
        строки, справа цифра."""
        self.assertIsNone(M._find_number("13.442 дн.", "13.44"))

    def test_a_decimal_point_before_the_number_blocks_it(self):
        self.assertIsNone(M._find_number("0.13.44", "13.44"))

    def test_percent_renderings_never_include_a_bare_integer(self):
        """Целочисленная форма процента — щедрая сторона ошибки: `4.8179`
        превратилось бы в `5`, и любая случайная пятёрка в тексте объявила бы
        ставку произнесённой."""
        self.assertEqual(M._renderings(4.8179, "pct"), ["4.82", "4.8"])

    def test_short_rendering_does_not_match_inside_a_longer_number(self):
        """`4.8` не должно находиться внутри `14.87`. Это не гипотеза: в день
        замера pendle=14.0048 стоял рядом с compound_v3=4.8179."""
        self.assertIsNone(M._find_number("ставка 14.87 пп", "4.8"))
        self.assertIsNone(M._find_number("ставка 14.0048 пп", "4.00"))
        self.assertIsNotNone(M._find_number("ставка 4.8 пп", "4.8"))

    def test_trailing_digits_are_a_boundary_too(self):
        self.assertIsNone(M._find_number("13.442", "13.44"))
        self.assertIsNotNone(M._find_number("окупаемость 13.44 дн.", "13.44"))

    def test_thousands_separator_form_is_recognised(self):
        hit = M._speaks("Оборот $22,105 капитала", [22105.26], "usd")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["rendering"], "22,105")

    def test_a_percent_about_something_else_is_not_the_rate(self):
        """Главный дефект, которого замер обязан избегать: в живой фразе есть
        `22.1%`, но это оборот, а не ставка пула."""
        got = _measure()
        self.assertEqual(_outcome(got, "source_rate"), M.SILENT)
        self.assertEqual(_outcome(got, "target_expected_rate"), M.SILENT)


# ───────────────────── SILENT против ABSENT: главный разрез ─────────────────

class TestSilentVersusAbsent(unittest.TestCase):
    """Разрыв ОТОБРАЖЕНИЯ и разрыв ИЗМЕРЕНИЯ звучат одинаково, а стоят
    разного. Модуль обязан их различать."""

    def test_measured_but_unspoken_rate_is_silent(self):
        got = _measure()
        fact = next(f for f in got["facts"] if f["fact"] == "source_rate")
        self.assertEqual(fact["outcome"], M.SILENT)
        self.assertIn("compound_v3=4.8179", fact["detail"])

    def test_rate_nobody_measures_is_absent(self):
        rec = dict(LIVE_RECORD)
        rec.pop("apy_evidenced_pct")
        rec.pop("book_apy_pp")
        got = _measure(rec=rec)
        self.assertEqual(_outcome(got, "source_rate"), M.ABSENT)

    def test_spoken_rate_flips_to_spoken(self):
        """Обратная сторона: допиши ставку во фразу — и вердикт изменится.
        Проверка, которая не умеет позеленеть, ничего не измеряет."""
        brief = dict(LIVE_BRIEF)
        brief["how_much"] = brief["how_much"] + " compound_v3 даёт 4.82%."
        got = _measure(brief=brief)
        self.assertEqual(_outcome(got, "source_rate"), M.SPOKEN)

    def test_break_even_is_silent_and_names_its_field(self):
        got = _measure()
        fact = next(f for f in got["facts"] if f["fact"] == "break_even")
        self.assertEqual(fact["outcome"], M.SILENT)
        self.assertIn("13.44", fact["detail"])

    def test_post_move_rate_without_the_sibling_artifact_is_absent(self):
        got = _measure(marginal=None)
        fact = next(f for f in got["facts"] if f["fact"] == "post_move_rate")
        self.assertEqual(fact["outcome"], M.ABSENT)
        self.assertIn("ADR-242", fact["detail"])

    def test_post_move_rate_with_the_sibling_artifact_is_silent(self):
        got = _measure()
        self.assertEqual(_outcome(got, "post_move_rate"), M.SILENT)


class TestPersistence(unittest.TestCase):
    """Единственный факт, которого не считает никто, — и проба обязана уметь
    сказать обратное, иначе её вердикт не измерение, а константа."""

    def test_absent_on_the_live_record(self):
        got = _measure()
        fact = next(f for f in got["facts"]
                    if f["fact"] == "advantage_persistence")
        self.assertEqual(fact["outcome"], M.ABSENT)
        self.assertIn("why_now", fact["detail"])

    def test_flips_to_spoken_when_the_value_exists_and_is_said(self):
        rec = dict(LIVE_RECORD, advantage_persist_hours=36.0)
        brief = dict(LIVE_BRIEF, why_now="преимущество держится 36 часов.")
        got = _measure(brief=brief, rec=rec)
        self.assertEqual(_outcome(got, "advantage_persistence"), M.SPOKEN)

    def test_flips_to_silent_when_the_value_exists_but_is_not_said(self):
        rec = dict(LIVE_RECORD, advantage_persist_hours=36.0)
        got = _measure(rec=rec)
        self.assertEqual(_outcome(got, "advantage_persistence"), M.SILENT)

    def test_a_trigger_params_dial_alone_is_not_the_value(self):
        """Порог устойчивости в дилах — не то же, что измеренная длительность.
        Наличие порога не имеет права закрыть вопрос владельца."""
        got = _measure(params_fields={"min_persistence_hours"})
        self.assertEqual(_outcome(got, "advantage_persistence"), M.SILENT)


class TestRiskWithinLimits(unittest.TestCase):
    """«Risk remains inside existing limits» — про запрет RiskPolicy, а не про
    экономические дилы ADR-060, которые сегодня стоя́т во фразе."""

    def test_silent_and_names_the_gates_that_stand_in_its_place(self):
        got = _measure()
        fact = next(f for f in got["facts"] if f["fact"] == "risk_within_limits")
        self.assertEqual(fact["outcome"], M.SILENT)
        self.assertIn("move_turnover_ok", fact["detail"])
        self.assertIn("другой вопрос", fact["detail"])

    def test_absent_when_the_verdict_is_nowhere(self):
        got = _measure(risk_check=None)
        self.assertEqual(_outcome(got, "risk_within_limits"), M.ABSENT)

    def test_spoken_when_the_verdict_reaches_the_sentence(self):
        brief = dict(LIVE_BRIEF, why=LIVE_BRIEF["why"] + " Лимиты: WARN.")
        got = _measure(brief=brief)
        self.assertEqual(_outcome(got, "risk_within_limits"), M.SPOKEN)


# ────────────────────────── плохая форма по владельцу ───────────────────────

class TestMachineTokens(unittest.TestCase):
    """Владелец назвал плохую форму дословно: внутренний токен вместо фразы."""

    def test_internal_keys_in_the_live_sentence_are_found(self):
        got = _measure()
        self.assertIn("reversal_of_recent_move", got["machine_tokens"])
        self.assertIn("move_turnover_over_budget", got["machine_tokens"])

    def test_protocol_names_are_not_findings(self):
        """`compound_v3` и `fluid_usdc` — тоже snake_case, но это НАЗВАНИЯ
        предметов, которые владелец читает как имена пулов."""
        got = _measure()
        for name in ("compound_v3", "fluid_usdc", "morpho_blue_base"):
            self.assertNotIn(name, got["machine_tokens"])

    def test_a_plain_word_is_not_a_token(self):
        self.assertEqual(M._machine_tokens("держит capital и cash", set()), [])

    def test_clean_prose_yields_no_tokens(self):
        self.assertEqual(
            M._machine_tokens("Aave сейчас зарабатывает 2.70%.", set()), [])


# ───────────────────── третий исход: объяснять нечего ───────────────────────

class TestNothingToExplain(unittest.TestCase):
    """Книга без предложенного хода не проваливает §44 — ей нечего объяснять.
    «Не измерено» обязано быть отличимо и от «прошло», и от «нет величины»."""

    def test_book_without_legs_is_unchecked_not_absent(self):
        rec = dict(LIVE_RECORD, legs=[])
        got = _measure(rec=rec)
        for fact in ("source_rate", "target_expected_rate", "switching_cost",
                     "break_even", "recommendation", "advantage_persistence"):
            self.assertEqual(_outcome(got, fact), M.UNCHECKED, fact)
        self.assertFalse(got["has_recommendation"])

    def test_the_recommendation_probe_itself_says_unchecked_without_legs(self):
        """Проба проверяется НАПРЯМУЮ: через `measure_brief` её собственная
        ветка недостижима — общий пересчёт книги без хода закрывает её собой,
        и мутация ветки оставалась незамеченной."""
        got = M._probe_recommendation("любой текст", dict(LIVE_RECORD, legs=[]))
        self.assertEqual(got["outcome"], M.UNCHECKED)

    def test_risk_fact_is_still_judged_without_a_move(self):
        """Вердикт лимитов относится к книге, а не к ходу, поэтому он
        измерим и в день без перекладки."""
        rec = dict(LIVE_RECORD, legs=[])
        got = _measure(rec=rec)
        self.assertEqual(_outcome(got, "risk_within_limits"), M.SILENT)

    def test_unavailable_brief_is_unchecked_across_the_board(self):
        got = M.measure_brief({"available": False, "reason": "нет журнала"},
                              None)
        self.assertTrue(all(f["outcome"] == M.UNCHECKED for f in got["facts"]))
        self.assertIn("нет журнала", got["facts"][0]["detail"])

    def test_no_book_with_a_move_yields_unchecked_report(self):
        with mock.patch.object(M, "measure_brief") as mm:
            mm.return_value = {"text": "", "facts": [
                M._fact(k, M.UNCHECKED, "хода нет") for k, _ in M.OWNER_FACTS],
                "machine_tokens": [], "has_recommendation": False}
            doc = M.run(root=M.REPO_ROOT, data_dir="/nonexistent", write=False)
        self.assertEqual(doc["overall"], "UNCHECKED")
        self.assertIsNone(doc["subject_book"])


# ──────────────────────── у объяснения должен быть читатель ─────────────────

class TestConsumers(unittest.TestCase):
    """§44 про то, что владелец ЧИТАЕТ. Объяснение без читателя объяснением
    не является, поэтому читатели считаются замером, а не списком из головы."""

    def _tree(self, tmp: Path, files: dict) -> str:
        for rel, src in files.items():
            path = tmp / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(src, encoding="utf-8")
        return str(tmp)

    def test_a_comment_mention_is_not_a_consumer(self):
        """Замер 06.09: hy_cycle/lp_cycle называют функцию в КОММЕНТАРИИ и
        брифа не показывают. Поиск подстрокой объявил бы их читателями."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(Path(td), {
                "spa_core/paper_trading/hy_cycle.py":
                    "# пишем журнал, чтобы build_books_brief() его прочитал\n"
                    "x = 1\n",
            })
            self.assertEqual(M._brief_consumers(root), [])

    def test_a_function_passed_as_an_object_is_a_consumer(self):
        """Настоящий читатель, api/routers/live.py, функцию не ВЫЗЫВАЕТ — он
        передаёт её в asyncio.to_thread. Проверка по форме вызова объявила бы
        объяснительный слой вовсе без читателей."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(Path(td), {
                "spa_core/api/routers/live.py":
                    "from spa_core.paper_trading.cio_brief import "
                    "build_books_brief\n"
                    "r = asyncio.to_thread(build_books_brief, dd)\n",
            })
            self.assertEqual(M._brief_consumers(root),
                             ["spa_core/api/routers/live.py"])

    def test_direct_call_is_a_consumer(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(Path(td), {
                "scripts/show.py":
                    "from spa_core.paper_trading.cio_brief import "
                    "build_books_brief\nprint(build_books_brief(dd))\n",
            })
            self.assertEqual(M._brief_consumers(root), ["scripts/show.py"])

    def test_tests_directory_is_not_a_consumer(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = self._tree(Path(td), {
                "spa_core/tests/test_x.py": "build_books_brief(dd)\n",
            })
            self.assertEqual(M._brief_consumers(root), [])

    def test_the_measurer_does_not_count_itself(self):
        """Измеритель зовёт `build_books_brief`, чтобы его ЗАМЕРИТЬ. Считать
        себя читателем значило бы объявить объяснение прочитанным ровно тем,
        что мы проверяем, есть ли у него читатель."""
        self.assertNotIn("spa_core/monitoring/cio_explainability.py",
                         M._brief_consumers(M.REPO_ROOT))

    def test_self_exclusion_survives_a_symlinked_root(self):
        """`/tmp` на macOS — ссылка на `/private/tmp`, и рабочие деревья живут
        именно там. Сравнение путей без разворота ссылок пропускало измеритель
        в собственный список читателей; под pytest это не проявлялось, потому
        что обе стороны сравнения приходили из одного написания."""
        import tempfile, os as _os
        with tempfile.TemporaryDirectory() as td:
            link = _os.path.join(td, "link")
            _os.symlink(M.REPO_ROOT, link)
            self.assertNotIn("spa_core/monitoring/cio_explainability.py",
                             M._brief_consumers(link))

    def test_live_tree_has_exactly_one_consumer_and_it_is_not_the_daily_report(self):
        """Замер на настоящем дереве: объяснение доходит до дашборда и НЕ
        доходит до ежедневного отчёта, которым владелец читает систему."""
        consumers = M._brief_consumers(M.REPO_ROOT)
        self.assertIn("spa_core/api/routers/live.py", consumers)
        self.assertNotIn(M._DAILY_CHANNEL, consumers)


# ─────────────────────────────── отчёт целиком ──────────────────────────────

class TestReport(unittest.TestCase):

    def _doc(self, tmp_path: Path) -> dict:
        ddir = tmp_path / "state"
        ddir.mkdir()
        (ddir / "allocation_rationale_history.jsonl").write_text(
            json.dumps(LIVE_RECORD, ensure_ascii=False) + "\n", encoding="utf-8")
        (ddir / "marginal_apy_at_size.json").write_text(
            json.dumps(MARGINAL), encoding="utf-8")
        (ddir / "risk_limits_check.json").write_text(
            json.dumps(RISK_CHECK), encoding="utf-8")
        return M.run(root=M.REPO_ROOT, data_dir=str(ddir), write=False)

    def test_live_scene_reports_two_spoken_five_silent_one_absent(self):
        got = _measure()
        tally = {o: sum(1 for f in got["facts"] if f["outcome"] == o)
                 for o in (M.SPOKEN, M.SILENT, M.ABSENT, M.UNCHECKED)}
        self.assertEqual(tally, {M.SPOKEN: 2, M.SILENT: 5,
                                 M.ABSENT: 1, M.UNCHECKED: 0})

    def test_the_two_spoken_facts_are_cost_and_the_amount(self):
        got = _measure()
        spoken = {f["fact"] for f in got["facts"] if f["outcome"] == M.SPOKEN}
        self.assertEqual(spoken, {"switching_cost", "recommendation"})

    def test_owner_facts_are_eight_and_verbatim(self):
        """Список — критерий ВЛАДЕЛЬЦА. Расширить его своим представлением о
        хорошем объяснении значило бы мерить не то, что он просил."""
        self.assertEqual(len(M.OWNER_FACTS), 8)
        self.assertEqual(M.OWNER_FACTS[0][1], "Aave currently earns 2.7%")
        self.assertEqual(M.OWNER_FACTS[-1][1], "Recommendation: move $12k")

    def test_report_writes_atomically_under_the_given_root(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "data").mkdir()
            M.run(root=str(root), data_dir=str(root / "data"), write=True)
            out = root / M.REPORT_REL
            self.assertTrue(out.exists())
            doc = json.loads(out.read_text(encoding="utf-8"))
            self.assertIn("overall", doc)
            self.assertIn("control", doc)

    def test_run_does_not_touch_the_live_data_dir(self):
        """Герметичность: вердикт обязан зависеть от входа, а не от хоста."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "data").mkdir()
            real_open = open
            touched: list[str] = []

            def watching_open(file, *a, **kw):
                p = str(file)
                if f"{M.REPO_ROOT}/data/" in p:
                    touched.append(p)
                return real_open(file, *a, **kw)

            with mock.patch("builtins.open", watching_open):
                M.run(root=str(root), data_dir=str(root / "data"), write=True)
            self.assertEqual(touched, [])


class TestArtifactHome(unittest.TestCase):
    """Дом артефакта — ДВЕ записи манифеста. Парити-тест краснеет только на
    второй, поэтому проверяются обе."""

    def _manifest(self) -> dict:
        with open(Path(M.REPO_ROOT) / "architecture" / "manifest.json",
                  encoding="utf-8") as fh:
            return json.load(fh)

    def test_artifact_is_registered_in_artifacts(self):
        man = self._manifest()
        paths = {a.get("path") for a in man.get("artifacts", [])}
        self.assertIn(M.REPORT_REL, paths)

    def test_artifact_is_registered_in_the_producing_agent(self):
        man = self._manifest()
        produced = {p.get("artifact")
                    for ag in man.get("agents", [])
                    for p in (ag.get("produces") or [])}
        self.assertIn(M.REPORT_REL, produced)

    def test_office_step_knows_the_producer_and_the_schema(self):
        src = (Path(M.REPO_ROOT) / "scripts" / "consume_office_reports.py").read_text(
            encoding="utf-8")
        self.assertIn("cio_explainability.json", src)
        self.assertIn("spa_core/monitoring/cio_explainability.py", src)

    def test_findings_bridge_computes_it(self):
        """Проводка проверяется РАЗБОРОМ, а не упоминанием имени: подмена
        импорта псевдонимом (`import cio_failure_modes as cio_explainability`)
        оставляет имя в файле на месте, а считаться начинает чужой замер."""
        import ast
        src = (Path(M.REPO_ROOT) / "spa_core" / "monitoring"
               / "findings_bridge.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        imported = any(
            isinstance(n, ast.ImportFrom)
            and any(a.name == "cio_explainability" and a.asname is None
                    for a in n.names)
            for n in ast.walk(tree))
        self.assertTrue(imported, "мост не импортирует cio_explainability "
                                  "под собственным именем")
        called = any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "run"
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "cio_explainability"
            for n in ast.walk(tree))
        self.assertTrue(called, "мост не вызывает cio_explainability.run")


class TestNoMoneyPathChange(unittest.TestCase):
    """Модуль объявлен advisory. Проверяем это формой, а не обещанием."""

    def test_module_does_not_import_execution(self):
        src = (Path(M.REPO_ROOT) / "spa_core" / "monitoring"
               / "cio_explainability.py").read_text(encoding="utf-8")
        self.assertNotIn("spa_core.execution", src)

    def test_module_declares_llm_forbidden(self):
        src = (Path(M.REPO_ROOT) / "spa_core" / "monitoring"
               / "cio_explainability.py").read_text(encoding="utf-8")
        self.assertIn("# LLM_FORBIDDEN", src)

    def test_report_carries_the_advisory_line(self):
        doc = M.run(root=M.REPO_ROOT, data_dir="/nonexistent", write=False)
        self.assertIn("ADVISORY", doc["advisory"])


if __name__ == "__main__":
    unittest.main()
