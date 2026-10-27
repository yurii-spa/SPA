"""АДРЕС ЗАМЕРА в строке отчёта `slo_keepability` (ADR-824, заказ G824 п. 1).

Находка цикла #948 (хвост ADR-823): тот же код, то же дерево, РАЗНЫЕ каталоги
данных дают разные числа у всех строк семейства ADR-819…823 — живой прод-`data/`
даёт «дошла бы 89 · НЕ ИЗМЕРЕНО 14», замороженная git-копия `data/` в worktree
«0 · 137». Fail-OPEN при этом НЕТ, инвариант #17 соблюдён, но у «НЕ ИЗМЕРЕНО» не
названа ПРИЧИНА: каталог лежит в `measured_from` и в `data_dir` каждой секции, а
в ЧИТАЕМУЮ циклом строку не попадает ни разу (замер этого цикла: **0** строк из
27 называли каталог при **четырёх** секциях-носителях из пяти). Читатель не
отличает «система такова» от «прогон был слеп».

Форму набора держат три урока предшественников:

* «контроль строки на словаре РУКАМИ мерит свой словарь» ⇒ класс
  :class:`LineIsWiredIntoTheRealReport` зовёт НАСТОЯЩИЙ ``measure()`` и
  НАСТОЯЩИЙ ``report()``, а не собранный руками словарь: мутация «ключ под
  другим именем» обязана краснеть;
* «проверка, зелёная при любом значении» ⇒ ни один контроль не ищет один лишь
  ярлык «НЕ ИЗМЕРЕНО» (он есть в выводе всегда): сцены сравниваются
  ПРОТИВОПОЛОЖНЫМИ ответами;
* «не измерено, выданное за ответ» ⇒ :class:`IncidentOf27October` при неудавшемся
  откате падает ГРОМКО, а не скипает (урок #465: скип неотличим от «прошло»).

Читателя этой строки мерит ЧУЖОЙ прибор — настоящая дверь шага 0-офис
(:class:`TheLineReachesTheCycle`), и мерит ИСХОДОМ: строка обязана прийти в её
вывод ОТДЕЛЬНОЙ строкой, а не буквами (авария ADR-823).

Время — ВХОД, а не окружение (`.claude/rules/deployment.md`, приём №1).
"""
# LLM_FORBIDDEN
# FROZEN-DATE-OK: injected-clock — `_ANCHOR` уезжает параметром `now=` в каждый
# зов `measure()` и каждую отрисовку двери; отметок, считанных от настенных
# часов, в файле нет ни одной.
from __future__ import annotations

import io
import json
import contextlib
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from spa_core.monitoring import slo_keepability as keep

_REPO = Path(__file__).resolve().parents[2]
_ANCHOR = datetime(2026, 10, 27, 1, 0, 0, tzinfo=timezone.utc)
#: Байты проводки — ровно та строка, которой закрыта находка #948. Откат именно
#: её и есть положительный контроль (`IncidentOf27October`).
_WIRING = "    lines.append(measured_from_line(doc))"


def _tree(tmp: Path, *, data_dir: Path | None = None) -> tuple:
    """Одноразовая сцена: своё дерево, своя конституция, свой каталог данных.

    Каталог данных ОТДЕЛЁН от дерева намеренно: предмет набора — умеет ли
    отчёт назвать каталог, НЕ совпадающий с `data/` своего дерева, а сцена, где
    они совпадают, этот вопрос не задаёт вовсе.
    """
    root = tmp / "tree"
    (root / "architecture").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "data").mkdir()
    (root / "architecture" / "manifest.json").write_text(json.dumps({
        "agents": [{"label": "com.spa.probe", "intent": "active",
                    "program": "scripts/probe.sh",
                    "produces": [{"artifact": "data/probe.json",
                                  "slo_hours": 24}]}],
        "artifacts": [{"path": "data/probe.json", "producer": "com.spa.probe",
                       "slo_hours": 24}],
    }, ensure_ascii=False), encoding="utf-8")
    elsewhere = data_dir if data_dir is not None else (tmp / "elsewhere")
    elsewhere.mkdir(parents=True, exist_ok=True)
    return root, elsewhere, tmp / "logs"


def _measured(tmp: Path, **kwargs) -> tuple:
    root, data_dir, log_dir = _tree(tmp, **kwargs)
    doc = keep.measure(root=root, data_dir=data_dir, log_dir=log_dir,
                       now=_ANCHOR)
    return doc, root, data_dir


class AddressOfTheMeasurementIsNamed(unittest.TestCase):
    """Три исхода строки адреса, каждый своей сценой (инв. #17)."""

    def test_the_directory_is_named_when_the_measurement_recorded_it(self):
        line = keep.measured_from_line({
            "measured_from": {"data_dir": "/живой/data",
                              "manifest": "/дерево/architecture/manifest.json",
                              "log_dir": "/tmp"},
            "declared_stamp_reader": {"data_dir_readable": True},
        })
        self.assertIn("/живой/data", line)
        self.assertIn("ЧИТАЕМ", line)
        # Строка обязана СКАЗАТЬ, что числа ниже про ЭТОТ каталог: назвать путь
        # и промолчать о том, зачем он здесь, значило бы оставить читателю ту
        # же работу, из-за которой находка #948 и появилась.
        self.assertIn("об ЭТОМ каталоге", line)

    def test_section_absent_is_its_own_outcome_not_a_missing_directory(self):
        line = keep.measured_from_line({"status": "OK"})
        self.assertIn("НЕ ИЗМЕРЕНО", line)
        self.assertIn("ДО ADR-824", line)
        # И НЕ выдаёт себя за «каталога нет»: это разные состояния.
        self.assertNotIn("каталог данных НЕ ИЗМЕРЕН", line)

    def test_inputs_without_a_directory_is_a_third_outcome_of_its_own(self):
        line = keep.measured_from_line({
            "measured_from": {"manifest": "/дерево/architecture/manifest.json"},
        })
        self.assertIn("каталог данных НЕ ИЗМЕРЕН", line)
        self.assertIn("/дерево/architecture/manifest.json", line)
        self.assertNotIn("ДО ADR-824", line)

    def test_a_directory_of_the_wrong_kind_is_unmeasured_not_printed_raw(self):
        """Род значения спрашивается, а не предполагается.

        Путь, записанный не строкой, напечатанный как есть, читался бы как
        настоящий адрес — то есть «не измерено» выдавалось бы за ответ.
        """
        line = keep.measured_from_line({"measured_from": {"data_dir": ["/x"]}})
        self.assertIn("каталог данных НЕ ИЗМЕРЕН", line)
        self.assertNotIn("/x", line)

    def test_the_three_outcomes_are_distinguishable_from_one_another(self):
        """Различимость проверяется СРАВНЕНИЕМ, а не наличием слов в каждом.

        Три ветки, совпавшие текстом, прошли бы три проверки выше поодиночке и
        не различали бы ничего.
        """
        named = keep.measured_from_line({
            "measured_from": {"data_dir": "/живой/data"}})
        no_dir = keep.measured_from_line({"measured_from": {"manifest": "/м"}})
        no_section = keep.measured_from_line({})
        self.assertEqual(len({named, no_dir, no_section}), 3)


class ReadabilityComesByReferenceNotFromThisMachine(unittest.TestCase):
    """Отрисовка идёт над ДОКУМЕНТОМ и файловую систему спрашивать не вправе.

    Замер делается в одном процессе, отрисовка — в другом и, вообще говоря, на
    другой машине. Спросить здесь `Path(data_dir).is_dir()` значило бы ответить
    про дерево ЧИТАТЕЛЯ и выдать ответ за дерево ЗАМЕРА.
    """

    def test_a_directory_absent_on_this_host_is_still_reported_as_read(self):
        line = keep.measured_from_line({
            "measured_from": {"data_dir": "/нет/такого/каталога/на/этой/машине"},
            "declared_write_attribution": {"data_dir_readable": True},
        })
        self.assertIn("(ЧИТАЕМ)", line)

    def test_an_existing_directory_is_reported_unreadable_if_the_measurement_said_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            line = keep.measured_from_line({
                "measured_from": {"data_dir": tmp},
                "declared_producer_reality": {"data_dir_readable": False},
            })
        self.assertIn("(НЕ ЧИТАЕТСЯ)", line)

    def test_a_later_section_answers_when_the_first_one_did_not_observe(self):
        """Перебор ищет НАБЛЮДЕНИЕ, а не первую попавшуюся секцию.

        Секция, чей замер не состоялся, читаемости не несёт вовсе — остановись
        перебор на ней, ответ соседа, который НАБЛЮДАЛ каталог, пропал бы, и
        «не измерено» встало бы на место измеренного.
        """
        line = keep.measured_from_line({
            "measured_from": {"data_dir": "/живой/data"},
            # первая по порядку перебора — замер не состоялся, поля нет
            "declared_producer_reality": {"status": "trace_unmeasured"},
            "declared_write_attribution": {"data_dir_readable": False},
        })
        self.assertIn("(НЕ ЧИТАЕТСЯ)", line)
        self.assertNotIn("читаемость НЕ ИЗМЕРЕНА", line)

    def test_no_section_observed_readability_leaves_it_unmeasured(self):
        line = keep.measured_from_line({"measured_from": {"data_dir": "/x/data"}})
        self.assertIn("читаемость НЕ ИЗМЕРЕНА", line)
        self.assertNotIn("(ЧИТАЕМ)", line)


class LineIsWiredIntoTheRealReport(unittest.TestCase):
    """Проводка меряется НАСТОЯЩИМ `measure()`, а не словарём из теста."""

    def test_a_real_measurement_names_its_data_directory_in_the_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc, _root, data_dir = _measured(Path(tmp))
            # Ключ спрашивается ПРИСУТСТВИЕМ: переименуй его мутация — и эта
            # строка покраснеет, чего разбор текста не обещает.
            self.assertIn("measured_from", doc)
            self.assertEqual(doc["measured_from"]["data_dir"], str(data_dir))
            lines = keep.report(doc)
            naming = [i for i, line in enumerate(lines) if str(data_dir) in line]
            self.assertEqual(len(naming), 1, lines)

    def test_the_address_stands_before_the_numbers_it_qualifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc, _root, data_dir = _measured(Path(tmp))
            lines = keep.report(doc)
        self.assertIn("Выдерживаем ли объявленный срок годности", lines[0])
        self.assertIn(str(data_dir), lines[1])

    def test_format_report_keeps_the_address_line(self):
        """Дверь зовёт `format_report`, а не `report` — предмет именно её."""
        with tempfile.TemporaryDirectory() as tmp:
            doc, _root, data_dir = _measured(Path(tmp))
            rendered = keep.format_report(doc)
        self.assertEqual(sum(1 for line in rendered if str(data_dir) in line), 1)


class CliCanAskAboutAnotherDataDirectory(unittest.TestCase):
    """`--data-dir` у CLI: две сцены с ПРОТИВОПОЛОЖНЫМИ ответами.

    До ADR-824 флага не было вовсе: `measure` принимал каталог с ADR-819, а
    спросить его извне было нечем — любой прогон из worktree мерил замороженную
    git-копию `data/` и об этом не говорил ни строкой.
    """

    def _run(self, argv) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            keep.main(argv, now=_ANCHOR)
        return out.getvalue()

    def test_the_flag_moves_the_measurement_to_the_named_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, elsewhere, log_dir = _tree(Path(tmp))
            printed = self._run([
                "--manifest", str(root / "architecture" / "manifest.json"),
                "--log-dir", str(log_dir), "--scripts-dir", str(root / "scripts"),
                "--data-dir", str(elsewhere)])
            self.assertIn(str(elsewhere), printed)

    def test_without_the_flag_the_measurement_stays_in_its_own_tree(self):
        """Противоположная сцена: умолчание не трогается правкой.

        Живой агент зовёт CLI без флага, и молчаливая смена его каталога была
        бы правкой поведения прода под видом правки отчёта.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root, elsewhere, log_dir = _tree(Path(tmp))
            printed = self._run([
                "--manifest", str(root / "architecture" / "manifest.json"),
                "--log-dir", str(log_dir), "--scripts-dir", str(root / "scripts")])
            self.assertNotIn(str(elsewhere), printed)
            self.assertIn(str(Path(keep._REPO_ROOT) / "data"), printed)


class TheLineReachesTheCycle(unittest.TestCase):
    """Читателя мерит ЧУЖОЙ прибор — НАСТОЯЩАЯ дверь шага 0-офис.

    Тот же выбор двери и та же причина, что у ADR-822/823: ветка
    ``_summarize_json``, а не ``main()`` (``main`` пишет квитанции, и спросить
    ими читателя значило бы изменить состояние системы вопросом о ней).
    """

    def setUp(self):
        self.door, why = keep.stamp_reader_door(_REPO)
        if self.door is None:  # предпосылка не обеспечена — ГРОМКО, не скип
            self.fail(f"дверь шага 0-офис НЕ ОПРОШЕНА: {why}")

    def test_the_address_arrives_as_a_line_of_its_own_not_as_letters(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc, _root, data_dir = _measured(Path(tmp))
            carrier = Path(tmp) / "data" / "slo_keepability.json"
            carrier.parent.mkdir(parents=True, exist_ok=True)
            carrier.write_text(json.dumps(doc, ensure_ascii=False),
                               encoding="utf-8")
            out = self.door._summarize_json(
                str(carrier), doc, now=_ANCHOR, root=str(_REPO),
                artifact_root=str(carrier.parent.parent)) or []
            lines = [str(line) for line in out]
            whole = "".join(lines)
            # Буквы доехали И строка доехала — между этими двумя ответами
            # живёт авария ADR-823 (`out.extend(<строка>)`, 727 букв столбиком).
            self.assertIn(str(data_dir), whole)
            self.assertEqual(
                sum(1 for line in lines if str(data_dir) in line), 1, lines)


class IncidentOf27October(unittest.TestCase):
    """Положительный контроль: откат ПРАВКИ обязан дать ПРОТИВОПОЛОЖНЫЙ ответ.

    Авария воспроизводится на КОПИИ модуля, в которой снята ровно одна строка
    проводки. Откат не применился ⇒ громкий отказ «предпосылка НЕ ОБЕСПЕЧЕНА».
    """

    def _module_without_the_wiring(self, tmp: Path):
        import importlib.util

        source = (_REPO / "spa_core" / "monitoring" / "slo_keepability.py").read_text(
            encoding="utf-8")
        if source.count(_WIRING) != 1:
            self.fail("ПРЕДПОСЫЛКА НЕ ОБЕСПЕЧЕНА: строки проводки "
                      f"{_WIRING!r} в модуле ровно одной не нашлось "
                      f"({source.count(_WIRING)} вхождений) — откат мерил бы "
                      "не то, что закрывает находку")
        copy = tmp / "slo_keepability_before.py"
        copy.write_text(source.replace(_WIRING, "    pass"), encoding="utf-8")
        spec = importlib.util.spec_from_file_location(
            "spa_slo_keepability_before_adr824", copy)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_before_the_edit_no_line_named_the_directory_and_after_exactly_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc, _root, data_dir = _measured(Path(tmp))
            before = self._module_without_the_wiring(Path(tmp))
            was = [line for line in before.report(doc) if str(data_dir) in line]
            now = [line for line in keep.report(doc) if str(data_dir) in line]
        self.assertEqual(was, [], "откат не состоялся: каталог назван и ДО правки")
        self.assertEqual(len(now), 1)


if __name__ == "__main__":
    unittest.main()
