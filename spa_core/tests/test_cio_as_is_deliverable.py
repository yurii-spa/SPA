"""Приёмка прибора §6 (ADR-1069): каждая проба — порванное звено с НАЗВАННЫМ именем.

Положительный контроль у класса есть и он настоящий: ДО этого цикла документа
`PORTFOLIO_CIO_AS_IS.md` в дереве не было вовсе (замер ADR-1067, 488 циклов), и
первый же прогон прибора по свежедописанному документу нашёл в нём ПЯТЬ дефектов —
три раздела без якоря и два якоря, выдуманных самим прибором из точечной ссылки на
символ. Обе находки закреплены пробами ниже (`test_a_dotted_symbol_reference_is_not_a_path`,
`test_a_section_without_an_anchor_is_prose`).

Проба НЕ проходит подстрокой (ADR-333): раздел, названный внутри абзаца, а не
заголовком, обязан считаться отсутствующим.
"""
# FROZEN-DATE-OK: golden — отметка снимка ЕСТЬ ПРЕДМЕТ, а не окружение. Литеральные
# `generated_at` ниже суть содержимое фикстуры, которое прибор читает КАК СВОЁ «сейчас»
# (`cio_as_is_deliverable.differential`, строка `now = _dt.fromisoformat(rat["generated_at"])`),
# и неразобранная отметка там — `NotMeasured`, а не подстановка часов. Замер цикла #1212
# ПЕРЕД этой пометкой: ни в приборе, ни в этом файле нет НИ ОДНОГО обращения к стенным
# часам (`grep -nE "now\(\)|utcnow|time\.time|date\.today"` по обоим файлам — пусто),
# то есть обе стороны каждого сравнения о сроке закреплены фикстурой. Это приём №3
# `.claude/rules/deployment.md` (дата является предметом), а не глушение храповика:
# приём №1 здесь неприменим — инъектировать нечего, часов нет вовсе.
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "cio_as_is_deliverable.py"


def _load():
    spec = importlib.util.spec_from_file_location("cio_as_is_deliverable", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


door = _load()

#: Минимальный ЦЕЛЫЙ документ: шесть разделов, у каждого якорь на существующий путь.
_WHOLE = "\n\n".join(
    [f"## {i + 1}. {name}\n\nтело раздела.\n\n*Замер: `scripts/cio_as_is_deliverable.py`.*"
     for i, name in enumerate(door.REQUIRED_SECTIONS)]
)


def _tree(tmp: Path, text: str | None = _WHOLE, name: str = door.DOC_NAME,
          where: str = "docs") -> Path:
    """Одноразовое дерево: документ + путь, на который ссылаются якоря."""
    (tmp / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp / "scripts" / "cio_as_is_deliverable.py").write_text("# заглушка\n", encoding="utf-8")
    if text is not None:
        d = tmp / where
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(text, encoding="utf-8")
    return tmp


class TestWholeContour(unittest.TestCase):
    """Целый контур зелен — иначе все красные пробы ниже ничего не значат."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = _tree(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_the_whole_contour_is_satisfied(self):
        got = door.audit(str(self.root))
        self.assertEqual(got["status"], door.SATISFIED, got["why"])
        self.assertEqual(got["why"], [])
        for name in door.REQUIRED_SECTIONS:
            self.assertTrue(got["sections"][name]["present"], name)
            self.assertTrue(got["sections"][name]["anchors"], name)

    def test_the_living_repository_satisfies_section_six(self):
        """Тот же вопрос — ЖИВОМУ дереву. Это и есть приёмка §6 приказа."""
        got = door.audit(str(_ROOT))
        self.assertEqual(got["status"], door.SATISFIED, got["why"])
        self.assertTrue(got["doc"].endswith(door.DOC_NAME), got["doc"])


class TestEachBrokenLinkIsNamed(unittest.TestCase):
    """На каждое порванное звено — своя проба и своё НАЗВАННОЕ имя в вердикте."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_missing_document_is_not_satisfied_and_says_so(self):
        got = door.audit(str(_tree(self.tmp, text=None)))
        self.assertEqual(got["status"], door.NOT_SATISFIED)
        self.assertEqual(got["copies"], [])
        self.assertIn(door.DOC_NAME, " ".join(got["why"]))

    def test_the_document_is_found_in_ANY_directory_not_only_docs(self):
        """Владелец назвал ИМЯ, а не путь: «нет» обязано приходить от дерева."""
        got = door.audit(str(_tree(self.tmp, where="research/sub")))
        self.assertEqual(got["status"], door.SATISFIED, got["why"])
        self.assertEqual(got["doc"], str(Path("research/sub") / door.DOC_NAME))

    def test_two_documents_with_one_name_are_UNMEASURED_not_a_verdict(self):
        root = _tree(self.tmp)
        second = root / "docs" / "archive"
        second.mkdir(parents=True, exist_ok=True)
        (second / door.DOC_NAME).write_text(_WHOLE, encoding="utf-8")
        with self.assertRaises(door.NotMeasured) as ctx:
            door.audit(str(root))
        self.assertIn("2", str(ctx.exception))

    def test_each_required_section_is_demanded_BY_NAME(self):
        for dropped in door.REQUIRED_SECTIONS:
            with self.subTest(dropped=dropped):
                kept = [n for n in door.REQUIRED_SECTIONS if n != dropped]
                text = "\n\n".join(
                    f"## {n}\n\nтело.\n\n*Замер: `scripts/cio_as_is_deliverable.py`.*"
                    for n in kept)
                import tempfile
                with tempfile.TemporaryDirectory() as td:
                    got = door.audit(str(_tree(Path(td), text=text)))
                self.assertEqual(got["status"], door.NOT_SATISFIED)
                self.assertIn(dropped, " ".join(got["why"]))
                self.assertFalse(got["sections"][dropped]["present"])

    def test_a_section_named_in_prose_only_does_NOT_count(self):
        """ADR-333: проба не проходит подстрокой."""
        text = _WHOLE.replace("## 2. Root cause", "### прочее")
        got = door.audit(str(_tree(self.tmp, text=text + "\n\nздесь обсуждается Root cause.\n")))
        self.assertEqual(got["status"], door.NOT_SATISFIED)
        self.assertIn("Root cause", " ".join(got["why"]))

    def test_a_section_without_an_anchor_is_prose(self):
        """Находка первого прогона по настоящему документу: три раздела без якоря."""
        text = _WHOLE.replace(
            "## 5. Policy conflicts\n\nтело раздела.\n\n*Замер: `scripts/cio_as_is_deliverable.py`.*",
            "## 5. Policy conflicts\n\nтело раздела без якоря.")
        got = door.audit(str(_tree(self.tmp, text=text)))
        self.assertEqual(got["status"], door.NOT_SATISFIED)
        self.assertIn("Policy conflicts", " ".join(got["why"]))
        self.assertIn("проза", " ".join(got["why"]))

    def test_an_anchor_on_a_path_that_does_not_exist_reddens(self):
        text = _WHOLE.replace("`scripts/cio_as_is_deliverable.py`",
                              "`spa_core/nowhere/absent_module.py`", 1)
        got = door.audit(str(_tree(self.tmp, text=text)))
        self.assertEqual(got["status"], door.NOT_SATISFIED)
        self.assertIn("absent_module.py", " ".join(got["why"]))

    def test_a_dotted_symbol_reference_is_not_a_path(self):
        """Находка прибора О СЕБЕ: `модуль.ИМЯ` читался как файл, которого нет."""
        self.assertEqual(
            door.anchors("*Замер: `spa_core/orchestrator/adapter_orchestrator.POLLED_ADAPTERS`.*"),
            [])
        self.assertEqual(
            door.anchors("*Замер: `spa_core/orchestrator/adapter_orchestrator.py` — имя `X`.*"),
            ["spa_core/orchestrator/adapter_orchestrator.py"])

    def test_a_runtime_data_anchor_is_counted_apart_not_called_missing(self):
        """`data/` в git не живёт: «файла нет» есть свойство ДЕРЕВА, не документа."""
        text = _WHOLE.replace(
            "*Замер: `scripts/cio_as_is_deliverable.py`.*",
            "*Замер: `scripts/cio_as_is_deliverable.py`, `data/current_positions.json`.*")
        got = door.audit(str(_tree(self.tmp, text=text)))
        self.assertEqual(got["status"], door.SATISFIED, got["why"])
        row = got["sections"]["Current architecture"]
        self.assertEqual(row["anchors_runtime"], ["data/current_positions.json"])
        self.assertEqual(row["anchors_missing"], [])

    def test_an_anchor_wrapped_over_several_lines_still_names_its_paths(self):
        """Находка прогона: перенос по ширине абзаца делал якорь «пустым»."""
        text = _WHOLE.replace(
            "*Замер: `scripts/cio_as_is_deliverable.py`.*",
            "*Замер: перечень путей, перенесённый\nпо ширине абзаца —\n"
            "`scripts/cio_as_is_deliverable.py`.*", 1)
        got = door.audit(str(_tree(self.tmp, text=text)))
        self.assertEqual(got["status"], door.SATISFIED, got["why"])

    def test_an_anchor_does_not_reach_past_a_blank_line(self):
        """Граница якоря объявлена: шире — он зачёл бы путь из соседней прозы."""
        self.assertEqual(
            door.anchors("Замер: нет путей.\n\nа тут `scripts/cio_as_is_deliverable.py`.\n"),
            [])

    def test_the_tail_of_the_last_section_stops_at_the_next_header(self):
        """Урок ADR-1067 (мутация M16): «до конца файла» — неверное умолчание."""
        text = _WHOLE + ("\n\n## Приёмка\n\n"
                         "*Замер: `scripts/cio_as_is_deliverable.py`.*\n")
        blocks = door.section_blocks(text)
        self.assertNotIn("Приёмка", blocks["Recommended architecture"])

    def test_a_tree_that_is_not_a_directory_is_UNMEASURED(self):
        with self.assertRaises(door.NotMeasured):
            door.audit(str(self.tmp / "no-such-tree"))

    def test_a_document_without_any_header_is_UNMEASURED_not_unsatisfied(self):
        """Ни одного заголовка ⇒ неизвестно, ЧТО здесь раздел. fail-CLOSED."""
        root = _tree(self.tmp, text="просто текст без заголовков, но про Root cause.\n")
        with self.assertRaises(door.NotMeasured):
            door.audit(str(root))


class TestExitCodes(unittest.TestCase):
    """Три исхода различимы кодом возврата (инв. #17)."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_satisfied_is_zero(self):
        self.assertEqual(door.main(["--root", str(_tree(self.tmp))]), 0)

    def test_not_satisfied_is_one(self):
        self.assertEqual(door.main(["--root", str(_tree(self.tmp, text=None))]), 1)

    def test_unmeasured_is_two(self):
        self.assertEqual(door.main(["--root", str(self.tmp / "absent")]), 2)

    def test_json_mode_carries_the_same_verdict(self):
        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = door.main(["--root", str(_tree(self.tmp)), "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(buf.getvalue())["status"], door.SATISFIED)


class TestDifferentialRefusesWithoutItsInputs(unittest.TestCase):
    """Дифференциал §2.3: нет входов ⇒ НЕ ИЗМЕРЕНО с причиной, а не вердикт."""

    def test_absent_data_dir_is_UNMEASURED(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(door.NotMeasured) as ctx:
                door.differential(str(Path(td) / "no-data"))
            self.assertIn("--data-dir", str(ctx.exception))

    def test_a_data_dir_without_the_two_trim_targets_is_UNMEASURED(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "allocation_rationale.json").write_text(
                json.dumps({"generated_at": "2026-01-01T00:00:00+00:00",
                            "admissible_trim": {}}), encoding="utf-8")
            (d / "current_positions.json").write_text("{}", encoding="utf-8")
            with self.assertRaises(door.NotMeasured) as ctx:
                door.differential(str(d))
            self.assertIn("трима", str(ctx.exception))


class TestTheSixNamesComeFromTheORDER(unittest.TestCase):
    """Паритет с ПРИКАЗОМ, а не с собой.

    `REQUIRED_SECTIONS` есть мерка, которой прибор мерит документ, — и если её
    единственным источником правды является она сама, то выбросить из неё раздел
    можно молча: уменьшится И требование, И фикстура, собранная из того же списка
    (дословный урок «объявление обязано нести СВОЙ контракт»). Поэтому список
    сверяется с §6 карточки приказа.

    Правило извлечения объявлено: внутри §6 названиями разделов являются строки без
    кириллицы, не кончающиеся на `.` или `:`, за вычетом имени документа и строк с
    цифрами (`39.7% portfolio at 2.7% APY` — цитата симптома, не раздел).
    """

    CARD = _ROOT / "nimbalyst-local" / "tracker" / \
        "inbox-task-portfolio-cio-dynamic-capital-alloc.md"

    def _names_from_the_order(self):
        import re
        text = self.CARD.read_text(encoding="utf-8")
        m = re.search(r"^6\. Deliverable.*?^Только после этого.*?$", text, re.S | re.M)
        self.assertIsNotNone(m, "§6 приказа не найден в карточке — паритет НЕ ИЗМЕРЕН")
        names = []
        for line in m.group(0).splitlines():
            s = line.strip()
            if (not s or re.search(r"[А-Яа-яЁё]", s) or s.endswith((".", ":"))
                    or s == door.DOC_NAME or re.search(r"\d", s)):
                continue
            names.append(s)
        return names

    def test_the_required_sections_are_exactly_the_owners_six(self):
        self.assertEqual(self._names_from_the_order(), list(door.REQUIRED_SECTIONS))

    def test_the_order_still_names_the_document_by_name(self):
        self.assertIn(door.DOC_NAME, self.CARD.read_text(encoding="utf-8"))


class TestTheCensusReadsThisDoor(unittest.TestCase):
    """Проводка: прибор зовёт НЕ только тест — его ось есть в переписи ADR-1067."""

    def test_the_census_carries_the_deliverable_axis(self):
        spec = importlib.util.spec_from_file_location(
            "cio_tz_section_census", _ROOT / "scripts" / "cio_tz_section_census.py")
        census = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(census)
        axis = census.deliverable_axis(str(_ROOT))
        self.assertTrue(axis["measured"], axis)
        self.assertEqual(axis["status"], door.SATISFIED, axis)
        self.assertEqual(axis["section"], 6)


def _census():
    spec = importlib.util.spec_from_file_location(
        "cio_tz_section_census", _ROOT / "scripts" / "cio_tz_section_census.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _econ_scene(tmp: Path, current, full, trimmed, recorded=None):
    """Одноразовый `data/` для дифференциала: входы ОДНИ, различается ЦЕЛЬ.

    `recorded` по умолчанию считается ТЕМ ЖЕ `evaluate`, что зовёт прибор, —
    то есть сцена даёт честный положительный контроль, а не угаданный.
    """
    import sys as _sys
    root = str(_ROOT)
    if root not in _sys.path:
        _sys.path.insert(0, root)
    from spa_core.allocator.rebalance_economics import evaluate, TriggerParams

    apy = {"a_proto": 3.0, "b_proto": 9.0, "c_proto": 5.0}
    capital = 100000.0
    chains = {k: "ethereum" for k in apy}

    def verdict(target):
        return evaluate(current_positions=current, target_positions=target,
                        apy_pct=apy, evidenced=set(apy), chains=chains,
                        capital_usd=capital, params=TriggerParams.for_mode(),
                        days_since_last_act=90.0, position_age_days={k: 90.0 for k in apy},
                        turnover_last_week_usd=0.0, turnover_today_usd=0.0,
                        last_move_legs={}, days_since_last_move=90.0,
                        tvl_evidenced=set(apy))

    if recorded is None:
        d = verdict(trimmed)
        recorded = {"decision": d.decision, "gain_pp": d.gain_pp}

    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "allocation_rationale.json").write_text(json.dumps({
        "generated_at": "2026-11-19T12:31:24.550278+00:00",
        "decision_shadow": recorded,
        "admissible_trim": {"target_before": full, "target_after": trimmed},
    }), encoding="utf-8")
    (tmp / "current_positions.json").write_text(json.dumps({
        "capital_usd": capital, "positions": current,
        "feed_coverage": {"apy_used_pct": apy,
                          "apy_sources": {k: "live" for k in apy}},
    }), encoding="utf-8")
    (tmp / "adapter_registry.json").write_text(json.dumps(
        {"adapters": {k: {"chain": "ethereum"} for k in apy}}), encoding="utf-8")
    (tmp / "adapter_orchestrator_status.json").write_text(json.dumps(
        {"adapters": [{"protocol": k, "tvl_usd": 9e8, "tvl_source": "live"} for k in apy]}),
        encoding="utf-8")
    (tmp / "trades.json").write_text("[]", encoding="utf-8")
    return tmp


class TestTheDifferentialAnswersOnlyWhatItMeasured(unittest.TestCase):
    """Выжившие мутации цикла #1211 (M13, M14) — дыры покрытия, закрытые здесь."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_broken_positive_control_is_UNMEASURED_and_prints_NO_full_run(self):
        """M13: без контроля прибор утверждал бы о мире, которого не видел."""
        d = _econ_scene(
            self.tmp / "data",
            current={"a_proto": 40000.0, "c_proto": 50000.0},
            full={"b_proto": 40000.0, "c_proto": 50000.0},
            trimmed={"a_proto": 30000.0, "b_proto": 10000.0, "c_proto": 50000.0},
            recorded={"decision": "ACT", "gain_pp": 99.0},   # заведомо НЕ то
        )
        with self.assertRaises(door.NotMeasured) as ctx:
            door.differential(str(d))
        self.assertIn("положительный контроль", str(ctx.exception))

    def test_the_trim_is_blamed_only_when_the_two_verdicts_DIFFER(self):
        """M14: «винить трим» обязано быть ЗАМЕРОМ, а не постоянной."""
        same = _econ_scene(
            self.tmp / "same",
            current={"a_proto": 40000.0, "c_proto": 50000.0},
            full={"a_proto": 39000.0, "c_proto": 51000.0},
            trimmed={"a_proto": 39500.0, "c_proto": 50500.0},
        )
        got = door.differential(str(same))
        self.assertTrue(got["control_reproduced"])
        self.assertEqual(got["trimmed"]["decision"], got["full"]["decision"])
        self.assertFalse(got["trim_is_the_cause"],
                         "оба вердикта совпали — трим причиной назван быть не может")

    # ЖИВОГО `data/` пробы здесь НЕТ намеренно. Такая проба зависела бы от ХОСТА:
    # на `ubuntu-latest` прод-дерева не существует, и единственным её исходом стал
    # бы `skipped` — то есть в дифференциальном замере она не краснела бы и не
    # проходила, а ИСЧЕЗАЛА (урок #465). Обе стороны `trim_is_the_cause` закреплены
    # синтетическими сценами выше; ответ о ЖИВОЙ книге даёт шаг цикла
    # `cio_as_is_deliverable.py --differential <прод>/data`, и он печатает
    # НАЗВАННОЕ дерево данных вместе с вердиктом.


class TestTheCensusCarriesTheAxisInITSREPORT(unittest.TestCase):
    """Выжившие мутации M15, M16 — ось обязана быть В ОТЧЁТЕ и честно молчать."""

    def test_the_report_itself_carries_the_axis(self):
        """M15: вызов функции ≠ ось в отчёте, который читает человек."""
        report = _census().census(str(_ROOT))
        axis = report["deliverable_axis"]
        self.assertTrue(axis.get("measured"), axis)
        self.assertEqual(axis["status"], door.SATISFIED, axis)

    def test_the_axis_is_rendered_for_the_reader(self):
        census = _census()
        text = census.render(census.census(str(_ROOT)))
        self.assertIn("ось ИСПОЛНЕНИЯ §6", text)

    def test_an_unimportable_door_is_UNMEASURED_not_satisfied(self):
        """M16: отсутствие инструмента — третий исход, а не «исполнен» (fail-OPEN)."""
        census = _census()
        def _boom():
            raise ImportError("прибор отнят сценой")
        census._import_deliverable_door = _boom
        axis = census.deliverable_axis(str(_ROOT))
        self.assertFalse(axis["measured"], axis)
        self.assertNotEqual(axis.get("status"), door.SATISFIED)
        self.assertIn("не ввезён", axis["reason"])


class TestTheRegisteredProbe(unittest.TestCase):
    """Проба реестра `card_acceptance` — контроль в ОБЕ стороны и три исхода.

    `.claude/rules/acceptance.md` п. 3: новая проба регистрируется только с тестом,
    где она зелена на целом контуре и красна на КАЖДОМ порванном звене, с названным
    звеном, и где она НЕ проходит подстрокой.
    """

    NAME = "cio_as_is_deliverable_is_whole"

    def _probe(self):
        from spa_core.monitoring.card_acceptance import PROBES
        self.assertIn(self.NAME, PROBES, "проба потеряла регистрацию в PROBES")
        return PROBES[self.NAME]

    def test_green_on_the_whole_contour(self):
        from spa_core.monitoring import card_acceptance as ca
        status, detail = self._probe()(None)
        self.assertEqual(status, ca.SATISFIED, detail)
        self.assertIn(door.DOC_NAME, detail)

    def test_red_with_a_NAMED_link_on_a_tree_without_the_document(self):
        import tempfile
        from spa_core.monitoring import card_acceptance as ca
        with tempfile.TemporaryDirectory() as td:
            status, detail = self._probe()(td)
        self.assertEqual(status, ca.NOT_SATISFIED)
        self.assertIn(door.DOC_NAME, detail)

    def test_red_with_a_NAMED_section_when_one_anchor_is_invented(self):
        import tempfile
        from spa_core.monitoring import card_acceptance as ca
        with tempfile.TemporaryDirectory() as td:
            root = _tree(Path(td))
            doc = root / "docs" / door.DOC_NAME
            doc.write_text(doc.read_text(encoding="utf-8").replace(
                "`scripts/cio_as_is_deliverable.py`", "`spa_core/nowhere/absent.py`", 1),
                encoding="utf-8")
            status, detail = self._probe()(str(root))
        self.assertEqual(status, ca.NOT_SATISFIED)
        self.assertIn("Current architecture", detail)
        self.assertIn("absent.py", detail)

    def test_red_with_a_NAMED_section_when_one_section_is_prose(self):
        import tempfile
        from spa_core.monitoring import card_acceptance as ca
        text = _WHOLE.replace(
            "## 5. Policy conflicts\n\nтело раздела.\n\n"
            "*Замер: `scripts/cio_as_is_deliverable.py`.*",
            "## 5. Policy conflicts\n\nтело без якоря.")
        with tempfile.TemporaryDirectory() as td:
            status, detail = self._probe()(str(_tree(Path(td), text=text)))
        self.assertEqual(status, ca.NOT_SATISFIED)
        self.assertIn("Policy conflicts", detail)

    def test_two_copies_of_the_name_are_UNMEASURED_not_a_verdict(self):
        import tempfile
        from spa_core.monitoring import card_acceptance as ca
        with tempfile.TemporaryDirectory() as td:
            root = _tree(Path(td))
            twin = root / "elsewhere"
            twin.mkdir(parents=True, exist_ok=True)
            (twin / door.DOC_NAME).write_text(_WHOLE, encoding="utf-8")
            status, detail = self._probe()(str(root))
        self.assertEqual(status, ca.UNMEASURED, detail)

    def test_the_probe_does_not_pass_by_substring(self):
        """Шесть названий, лежащих ПРОЗОЙ в одном абзаце, зеленью не являются."""
        import tempfile
        from spa_core.monitoring import card_acceptance as ca
        prose = ("# Документ\n\n## Раздел\n\n"
                 + " · ".join(door.REQUIRED_SECTIONS)
                 + "\n\n*Замер: `scripts/cio_as_is_deliverable.py`.*\n")
        with tempfile.TemporaryDirectory() as td:
            status, _ = self._probe()(str(_tree(Path(td), text=prose)))
        self.assertEqual(status, ca.NOT_SATISFIED)


if __name__ == "__main__":
    unittest.main()
