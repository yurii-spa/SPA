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


# ═══════════════════ ADR-990: о ТОМ ли ходе объяснение (ось §44) ═══════════════════
#
# Восемь фактов выше судят СОСТАВ фразы. Ось ADR-990 судит её ПРЕДМЕТ: фраза
# строится из записи ТЕНИ (ADR-060 shadow), а деньги двигает цикл по другому
# журналу. Сцены ниже — замер #1107 на живом трейле: из 190 дней тени книга
# исполняла ход на 11, и во все 11 фраза говорила HOLD. Каждая сцена ломает
# ровно одну координату и требует, чтобы вердикт изменился.

_MOVE = {"event_type": "trade_executed", "timestamp": "2026-08-27T08:00:00+00:00",
         "data": {"trade_id": "T020", "diff_usd": 302105.26,
                  "to_allocation": {"pendle": 18947.37, "maple": 18947.37,
                                    "compound_v3": 40000.0, "morpho_steakhouse": 12105.26}}}
_HOLD_REC = {"cycle_date": "2026-08-27", "verdict": "HOLD", "legs": [],
             "current_positions": {"pendle": 18947.37, "maple": 18947.37,
                                   "compound_v3": 40000.0, "morpho_steakhouse": 12105.26}}
_MOVE_REC = {"cycle_date": "2026-08-27", "verdict": "MOVE",
             "legs": [{"protocol": "aave", "direction": "increase", "delta_usd": 12000.0}],
             "target_positions": {"pendle": 18947.37, "maple": 18947.37,
                                  "compound_v3": 40000.0, "morpho_steakhouse": 12105.26},
             "current_positions": {"compound_v3": 40000.0}}


class TestExecutedAxisDay(unittest.TestCase):

    def test_hold_while_the_book_moved_is_named(self):
        got = M.explained_vs_executed_day(_HOLD_REC, [_MOVE])
        self.assertEqual(got["status"], M.DAY_HOLD_WHILE_BOOK_MOVED)
        self.assertEqual(got["executed_moves"], 1)
        self.assertAlmostEqual(got["executed_diff_usd"], 302105.26)

    def test_hold_and_a_quiet_book_are_consistent(self):
        self.assertEqual(M.explained_vs_executed_day(_HOLD_REC, [])["status"],
                         M.DAY_CONSISTENT)

    def test_a_move_equal_to_the_executed_book_is_consistent(self):
        self.assertEqual(M.explained_vs_executed_day(_MOVE_REC, [_MOVE])["status"],
                         M.DAY_CONSISTENT)

    def test_a_cent_apart_is_still_consistent_a_dollar_is_not(self):
        near = dict(_MOVE, data=dict(_MOVE["data"],
                                     to_allocation=dict(_MOVE["data"]["to_allocation"],
                                                        pendle=18947.375)))
        self.assertEqual(M.explained_vs_executed_day(_MOVE_REC, [near])["status"],
                         M.DAY_CONSISTENT)
        far = dict(_MOVE, data=dict(_MOVE["data"],
                                    to_allocation=dict(_MOVE["data"]["to_allocation"],
                                                       pendle=18948.37)))
        self.assertEqual(M.explained_vs_executed_day(_MOVE_REC, [far])["status"],
                         M.DAY_DIFFERENT_MOVE)

    def test_a_move_the_book_never_made_is_named(self):
        self.assertEqual(M.explained_vs_executed_day(_MOVE_REC, [])["status"],
                         M.DAY_MOVE_NOT_EXECUTED)

    def test_a_record_without_a_verdict_is_unmeasured_not_consistent(self):
        rec = dict(_HOLD_REC); rec.pop("verdict")
        self.assertEqual(M.explained_vs_executed_day(rec, [])["status"], M.DAY_UNMEASURED)
        self.assertEqual(M.explained_vs_executed_day(rec, [_MOVE])["status"], M.DAY_UNMEASURED)

    def test_a_non_numeric_book_is_unmeasured_not_different(self):
        bad = dict(_MOVE, data=dict(_MOVE["data"],
                                    to_allocation=dict(_MOVE["data"]["to_allocation"],
                                                       pendle="18947.37")))
        self.assertEqual(M.explained_vs_executed_day(_MOVE_REC, [bad])["status"],
                         M.DAY_UNMEASURED)

    def test_the_last_move_of_the_day_is_the_executed_book(self):
        """Семь ходов за день (27.08) — книга дня это ПОСЛЕДНИЙ to_allocation."""
        first = dict(_MOVE, data=dict(_MOVE["data"], to_allocation={"aave": 1.0}))
        got = M.explained_vs_executed_day(_MOVE_REC, [first, _MOVE])
        self.assertEqual(got["status"], M.DAY_CONSISTENT)
        self.assertEqual(got["executed_moves"], 2)


class TestHeldBookVersusTrail(unittest.TestCase):

    def test_the_phrase_holds_the_trail_book(self):
        got = M.held_book_vs_trail(_HOLD_REC, _MOVE["data"]["to_allocation"])
        self.assertEqual(got["status"], M.HELD_MATCHES)

    def test_a_book_the_trail_never_had_is_named_with_its_width(self):
        """Сцена 06.08: тень «держит» 24 дробных позиции, трек — три."""
        rec = dict(_HOLD_REC, current_positions={"aave_v3": 4791.06, "sdai": 2546.29,
                                                 "maple": 2231.48})
        got = M.held_book_vs_trail(rec, {"maple": 20000.0, "pendle": 20000.0,
                                         "morpho_steakhouse": 40000.0})
        self.assertEqual(got["status"], M.HELD_DIFFERS)
        self.assertEqual(got["positions_differing"], 5)

    def test_no_trail_book_yet_is_unmeasured_not_a_mismatch(self):
        self.assertEqual(M.held_book_vs_trail(_HOLD_REC, None)["status"], M.HELD_UNMEASURED)

    def test_a_record_without_positions_is_unmeasured(self):
        rec = dict(_HOLD_REC); rec.pop("current_positions")
        self.assertEqual(M.held_book_vs_trail(rec, {"a": 1.0})["status"], M.HELD_UNMEASURED)

    def test_book_as_of_takes_the_last_move_on_or_before_the_day(self):
        by_day = M.moves_by_day([
            dict(_MOVE, timestamp="2026-08-20T08:00:00+00:00",
                 data=dict(_MOVE["data"], to_allocation={"a": 1.0})),
            _MOVE,
            dict(_MOVE, timestamp="2026-09-11T08:00:00+00:00",
                 data=dict(_MOVE["data"], to_allocation={"z": 9.0})),
        ])
        self.assertEqual(M.book_as_of("2026-08-27", by_day), _MOVE["data"]["to_allocation"])
        self.assertEqual(M.book_as_of("2026-08-26", by_day), {"a": 1.0})
        self.assertIsNone(M.book_as_of("2026-08-01", by_day))

    def test_moves_by_day_ignores_other_events_and_undated_rows(self):
        by_day = M.moves_by_day([_MOVE, {"event_type": "allocation_proposal",
                                         "timestamp": "2026-08-27T07:00:00+00:00"},
                                 {"event_type": "trade_executed"}])
        self.assertEqual(list(by_day), ["2026-08-27"])
        self.assertEqual(len(by_day["2026-08-27"]), 1)


class TestExecutedAxisPopulation(unittest.TestCase):
    """Замер #1107: 190 дней тени · 11 с ходом · 11 HOLD · 18 чужих книг."""

    def _records(self):
        quiet = [dict(_HOLD_REC, cycle_date=f"2026-09-{d:02d}") for d in range(12, 20)]
        return [_HOLD_REC] + quiet

    def test_population_counts_sum_to_the_shadow_days(self):
        got = M.explained_vs_executed(self._records(), [_MOVE])
        self.assertEqual(got["status"], "measured")
        self.assertEqual(got["shadow_days"], 9)
        self.assertEqual(sum(got["days"].values()), 9)
        self.assertEqual(got["days"][M.DAY_HOLD_WHILE_BOOK_MOVED], 1)
        self.assertEqual(got["days"][M.DAY_CONSISTENT], 8)
        self.assertEqual(got["days_with_executed_moves"], 1)

    def test_worst_day_is_the_largest_executed_sum_among_hold_days(self):
        small = dict(_MOVE, timestamp="2026-09-12T08:00:00+00:00",
                     data=dict(_MOVE["data"], diff_usd=40263.16))
        got = M.explained_vs_executed(self._records(), [small, _MOVE])
        self.assertEqual(got["worst"]["date"], "2026-08-27")
        self.assertAlmostEqual(got["worst"]["executed_diff_usd"], 302105.26)
        self.assertEqual(got["days"][M.DAY_HOLD_WHILE_BOOK_MOVED], 2)

    def test_a_move_without_a_sum_cannot_become_the_worst_day(self):
        unsummed = dict(_MOVE, data={k: v for k, v in _MOVE["data"].items() if k != "diff_usd"})
        got = M.explained_vs_executed([_HOLD_REC], [unsummed])
        self.assertEqual(got["days"][M.DAY_HOLD_WHILE_BOOK_MOVED], 1)
        self.assertIsNone(got["worst"])

    def test_trail_days_outside_the_shadow_history_are_not_judged(self):
        early = dict(_MOVE, timestamp="2026-06-12T08:00:00+00:00")
        got = M.explained_vs_executed(self._records(), [early, _MOVE])
        self.assertEqual(got["trail_move_days_total"], 2)
        self.assertEqual(got["days_with_executed_moves"], 1)

    def test_no_trail_is_unmeasured_with_the_trail_named(self):
        got = M.explained_vs_executed(self._records(), None)
        self.assertEqual(got["status"], "unmeasured")
        self.assertIn(M.TRAIL_NAME, got["reason"])

    def test_empty_history_is_unmeasured_not_zero_findings(self):
        self.assertEqual(M.explained_vs_executed([], [_MOVE])["status"], "unmeasured")

    def test_held_book_mismatch_span_is_dated(self):
        recs = [dict(_HOLD_REC, cycle_date="2026-08-28",
                     current_positions={"aave_v3": 4791.06}),
                dict(_HOLD_REC, cycle_date="2026-08-29",
                     current_positions={"aave_v3": 4791.06}),
                dict(_HOLD_REC, cycle_date="2026-08-30")]
        got = M.explained_vs_executed(recs, [_MOVE])
        self.assertEqual(got["held_book"], {M.HELD_MATCHES: 1, M.HELD_DIFFERS: 2,
                                            M.HELD_UNMEASURED: 0})
        self.assertEqual(got["held_differs_span"], ["2026-08-28", "2026-08-29"])
        self.assertEqual(got["latest"]["held"]["status"], M.HELD_MATCHES)

    def test_axis_control_passes_on_its_own_scenes(self):
        got = M.run_axis_control()
        self.assertTrue(got["passed"], got)
        self.assertEqual(got["failed"], [])

    def test_a_broken_detector_fails_the_axis_control(self):
        with mock.patch.object(M, "explained_vs_executed_day",
                               return_value={"status": M.DAY_CONSISTENT}):
            got = M.run_axis_control()
        self.assertFalse(got["passed"])
        self.assertTrue(any("hold_while_moved" in f for f in got["failed"]))


class TestTrimProbe(unittest.TestCase):
    """Запись тени с 28.10 несёт `admissible_trim` (ADR-850): k=0.27 у 26 из 27."""

    TRIM_REC = {"admissible_trim": {"k": 0.272727, "damper_reason": "weekly_turnover_budget",
                                    "cost": {"full_turnover_usd": 55000.0,
                                             "final_turnover_usd": 15000.0}}}
    LIVE_TEXT = ("Предложенный ход: +aave_v3 ($9,545). Оборот $15,000 (15.0% капитала), "
                 "стоимость $55.65. payback_too_long:196.2d.")

    def test_live_phrase_explains_the_trimmed_move_and_is_silent_about_the_trim(self):
        got = M._probe_trim(self.LIVE_TEXT, self.TRIM_REC)
        self.assertEqual(got["outcome"], M.SILENT)
        self.assertAlmostEqual(got["evidence"]["k"], 0.272727)
        self.assertEqual(got["evidence"]["full_turnover_usd"], 55000.0)

    def test_naming_the_full_sum_flips_to_spoken(self):
        got = M._probe_trim(self.LIVE_TEXT + " Урезано с $55,000.", self.TRIM_REC)
        self.assertEqual(got["outcome"], M.SPOKEN)

    def test_naming_k_as_a_percent_flips_to_spoken(self):
        got = M._probe_trim(self.LIVE_TEXT + " Ход урезан до 27% от предложенного.",
                            self.TRIM_REC)
        self.assertEqual(got["outcome"], M.SPOKEN)

    def test_a_percent_about_the_turnover_is_not_the_trim(self):
        """«15.0% капитала» во фразе — доля оборота, а не k; k=0.15 совпало бы."""
        rec = {"admissible_trim": {"k": 0.15, "cost": {"full_turnover_usd": 100000.0}}}
        got = M._probe_trim("Оборот $15,000 (15.0% капитала).", rec)
        # 15.0 — рендер k·100 с одной цифрой; это ЩЕДРАЯ сторона детектора и она
        # названа здесь вслух, а не спрятана: совпадение по значению слепо к смыслу.
        self.assertEqual(got["outcome"], M.SPOKEN)

    def test_untrimmed_move_is_nothing_to_explain(self):
        rec = {"admissible_trim": {"k": 1.0, "cost": {"full_turnover_usd": 15000.0}}}
        self.assertEqual(M._probe_trim(self.LIVE_TEXT, rec)["outcome"], M.UNCHECKED)

    def test_no_trim_record_is_absent(self):
        self.assertEqual(M._probe_trim(self.LIVE_TEXT, LIVE_RECORD)["outcome"], M.ABSENT)

    def test_trim_record_without_k_is_unchecked_not_silent(self):
        rec = {"admissible_trim": {"cost": {"full_turnover_usd": 55000.0}}}
        self.assertEqual(M._probe_trim(self.LIVE_TEXT, rec)["outcome"], M.UNCHECKED)

    def test_measure_brief_judges_the_trim_only_for_a_book_with_a_move(self):
        rec = dict(LIVE_RECORD, **self.TRIM_REC)
        self.assertEqual(_measure(rec=rec)["trim"]["outcome"], M.SILENT)
        no_legs = dict(rec, legs=[])
        self.assertEqual(_measure(rec=no_legs)["trim"]["outcome"], M.UNCHECKED)


class TestStageProbe(unittest.TestCase):
    FIELDS = ("stage", "release_stage", "cio_stage", "armed", "cio_armed")

    def test_live_record_carries_no_stage_field_and_mode_is_not_one(self):
        got = M._probe_stage("Держит: compound_v3.", dict(LIVE_RECORD, mode="paper"),
                             self.FIELDS)
        self.assertEqual(got["outcome"], M.ABSENT)
        self.assertIn("mode=paper", got["detail"])
        self.assertIn("не стадия", got["detail"])

    def test_a_recorded_but_unspoken_stage_is_silent(self):
        got = M._probe_stage("Держит: compound_v3.", dict(LIVE_RECORD, stage="shadow"),
                             self.FIELDS)
        self.assertEqual(got["outcome"], M.SILENT)
        self.assertEqual(got["evidence"], {"stage": "shadow"})

    def test_a_spoken_stage_flips_to_spoken(self):
        got = M._probe_stage("Решение тени (shadow).", dict(LIVE_RECORD, stage="shadow"),
                             self.FIELDS)
        self.assertEqual(got["outcome"], M.SPOKEN)

    def test_a_boolean_arming_is_spoken_by_its_word(self):
        got = M._probe_stage("Советник не взведён.", dict(LIVE_RECORD, armed=False),
                             self.FIELDS)
        self.assertEqual(got["outcome"], M.SPOKEN)
        got = M._probe_stage("Советник предлагает.", dict(LIVE_RECORD, armed=False),
                             self.FIELDS)
        self.assertEqual(got["outcome"], M.SILENT)

    def test_no_dictionary_is_unchecked_and_names_its_owner(self):
        got = M._probe_stage("x", LIVE_RECORD, None)
        self.assertEqual(got["outcome"], M.UNCHECKED)
        self.assertIn("release_stage_census", got["source"])

    def test_the_dictionary_is_imported_from_its_owner_not_copied(self):
        from spa_core.analytics.release_stage_census import STAGE_RECORD_FIELDS
        self.assertEqual(M._stage_fields(), tuple(str(f) for f in STAGE_RECORD_FIELDS))

    def test_measure_brief_carries_the_stage_for_a_book_without_a_move_too(self):
        got = _measure(rec=dict(LIVE_RECORD, legs=[], stage="shadow"),
                       stage_fields=self.FIELDS)
        self.assertEqual(got["stage"]["outcome"], M.SILENT)


class TestExecutedAxisInTheReport(unittest.TestCase):
    """`run()` на одноразовом каталоге: трейл есть / нет, раздел и находки."""

    def _doc(self, tmp: Path, with_trail: bool) -> dict:
        ddir = tmp / "state"
        ddir.mkdir()
        rec = dict(LIVE_RECORD, cycle_date="2026-08-27",
                   current_positions=_HOLD_REC["current_positions"])
        (ddir / "allocation_rationale_history.jsonl").write_text(
            json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
        if with_trail:
            (ddir / M.TRAIL_NAME).write_text(json.dumps(_MOVE) + "\n", encoding="utf-8")
        return M.run(root=M.REPO_ROOT, data_dir=str(ddir), write=False)

    def test_hold_while_moved_reaches_the_report_as_critical(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            doc = self._doc(Path(td), with_trail=True)
        ax = doc["executed_move"]
        self.assertEqual(ax["status"], "measured")
        self.assertEqual(ax["book"], "conservative")
        self.assertEqual(ax["days"][M.DAY_HOLD_WHILE_BOOK_MOVED], 1)
        codes = {f["code"]: f["severity"] for f in doc["findings"]}
        self.assertEqual(codes.get("explanation_says_hold_while_book_moved"), "CRITICAL")
        self.assertIn("ADR-990", ax["provenance"])
        self.assertTrue(ax["control"]["passed"])

    def test_no_trail_is_unmeasured_and_said_aloud(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            doc = self._doc(Path(td), with_trail=False)
        self.assertEqual(doc["executed_move"]["status"], "unmeasured")
        self.assertTrue(any("ADR-990" in u and "НЕ ИЗМЕРЕНО" in u for u in doc["unchecked"]))
        self.assertFalse(any(f["code"].startswith("explanation_says_hold")
                             for f in doc["findings"]))

    def test_stage_and_trim_findings_reach_the_report(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            doc = self._doc(Path(td), with_trail=True)
        codes = {f["code"] for f in doc["findings"]}
        self.assertIn("stage_not_recorded", codes)
        self.assertIn("trim_not_recorded", codes)

    def test_the_eight_owner_facts_are_untouched_by_the_axis(self):
        """Ось ADR-990 не девятый факт: знаменатель владельца остаётся восемь."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            doc = self._doc(Path(td), with_trail=True)
        self.assertEqual(doc["facts_total"], 8)
        self.assertEqual(sum(doc["tally"].values()), 8)
        self.assertNotIn("trim", {f["fact"] for f in doc["books"][0]["facts"]})

    def test_a_failed_axis_control_makes_only_the_axis_unmeasured(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(M, "run_axis_control",
                                   return_value={"passed": False, "scenes": 7,
                                                 "failed": ["x"], "reason": "сломан"}):
                doc = self._doc(Path(td), with_trail=True)
        self.assertEqual(doc["executed_move"]["status"], "unmeasured")
        self.assertTrue(doc["control"]["passed"])      # восемь фактов судятся как прежде
        self.assertIsNotNone(doc["tally"])


class TestCriterionCarriesTheAxis(unittest.TestCase):
    """§49 Auditability (половина «explanation»): ось ADR-990 — член конъюнкции."""

    def _satisfied_doc(self, **axis) -> dict:
        doc = {"control": {"passed": True}, "facts_total": 8,
               "books": [{"book": "conservative", "has_recommendation": True,
                          "tally": {M.SPOKEN: 8, M.SILENT: 0, M.ABSENT: 0, M.UNCHECKED: 0},
                          "machine_tokens": []}]}
        if axis:
            doc["executed_move"] = axis
        return doc

    def test_a_pre_adr990_artifact_is_judged_as_before_and_says_the_axis_is_not_taken(self):
        got = M.criterion_verdict(self._satisfied_doc())
        self.assertEqual(got["status"], M.CRITERION_SATISFIED)
        self.assertIn("до ADR-990", got["reason"])

    def test_hold_while_moved_makes_the_half_not_satisfied(self):
        got = M.criterion_verdict(self._satisfied_doc(
            status="measured", days_with_executed_moves=11,
            days={M.DAY_HOLD_WHILE_BOOK_MOVED: 11, M.DAY_DIFFERENT_MOVE: 0}))
        self.assertEqual(got["status"], M.CRITERION_NOT_SATISFIED)
        self.assertIn("в 11 говорило HOLD", got["reason"])

    def test_a_consistent_axis_keeps_satisfied_and_says_so(self):
        got = M.criterion_verdict(self._satisfied_doc(
            status="measured", days_with_executed_moves=3,
            days={M.DAY_HOLD_WHILE_BOOK_MOVED: 0, M.DAY_DIFFERENT_MOVE: 0}))
        self.assertEqual(got["status"], M.CRITERION_SATISFIED)
        self.assertIn("говорила о них", got["reason"])

    def test_an_unmeasured_axis_turns_satisfied_into_unmeasured(self):
        got = M.criterion_verdict(self._satisfied_doc(status="unmeasured", reason="трейла нет"))
        self.assertEqual(got["status"], M.CRITERION_UNMEASURED)
        self.assertIn("трейла нет", got["reason"])

    def test_an_unmeasured_axis_does_not_hide_a_not_satisfied_half(self):
        doc = self._satisfied_doc(status="unmeasured", reason="трейла нет")
        doc["books"][0]["tally"][M.SPOKEN] = 3
        got = M.criterion_verdict(doc)
        self.assertEqual(got["status"], M.CRITERION_NOT_SATISFIED)
        self.assertIn("НЕ ИЗМЕРЕНА", got["reason"])

    def test_an_unreadable_day_count_is_unmeasured_not_consistent(self):
        got = M.criterion_verdict(self._satisfied_doc(status="measured", days={}))
        self.assertEqual(got["status"], M.CRITERION_UNMEASURED)


class TestMeasurerCopyIsNotAConsumer(unittest.TestCase):

    def test_a_copy_of_the_measurer_under_another_root_is_excluded_by_its_path(self):
        """Замер #1107: прибор из рабочего дерева с `--root <прод>` записал
        прод-копию самого себя читателем объяснения."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "spa_core" / "monitoring").mkdir(parents=True)
            (root / "scripts").mkdir()
            (root / "spa_core" / "monitoring" / "cio_explainability.py").write_text(
                "x = build_books_brief\n", encoding="utf-8")
            (root / "spa_core" / "monitoring" / "reader.py").write_text(
                "x = build_books_brief\n", encoding="utf-8")
            got = M._brief_consumers(str(root))
        self.assertEqual(got, ["spa_core/monitoring/reader.py"])


class TestTrimValueCollision(unittest.TestCase):
    """Сцена 12.11: полная сумма предложения $40,000 равна позиции «держит
    compound_v3 ($40,000)». Совпавшее число — не свидетельство о триме."""

    REC = {"admissible_trim": {"k": 0.375, "cost": {"full_turnover_usd": 40000.0,
                                                    "final_turnover_usd": 15000.0}},
           "current_positions": {"compound_v3": 40000.0, "maple": 20000.0},
           "legs": [{"protocol": "aave_v3", "direction": "increase", "delta_usd": 13125.0}]}
    TEXT = "Держит: compound_v3 ($40,000), maple ($20,000). Оборот $15,000, стоимость $43.80."

    def test_a_colliding_full_sum_does_not_make_the_trim_spoken(self):
        got = M._probe_trim(self.TEXT, self.REC)
        self.assertEqual(got["outcome"], M.SILENT)
        self.assertIn("числом не свидетельствует", got["detail"])

    def test_k_still_flips_it_to_spoken(self):
        got = M._probe_trim(self.TEXT + " Ход урезан до 37.5% от предложенного.", self.REC)
        self.assertEqual(got["outcome"], M.SPOKEN)

    def test_a_non_colliding_full_sum_is_evidence(self):
        rec = dict(self.REC, current_positions={"compound_v3": 41000.0})
        got = M._probe_trim(self.TEXT + " Предложено было $40,000.", rec)
        self.assertEqual(got["outcome"], M.SPOKEN)
