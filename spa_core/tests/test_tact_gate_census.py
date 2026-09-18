"""Перепись гейтов такта: ГДЕ у производителя лежит решение «пора ли».

Заказ **G39 п. 3** приказа владельца «Portfolio CIO», решение — ADR-415.

## Что проверяется и почему именно так

У каждой проверки здесь **обратная сторона**: целый контур зелёный, порванное
звено красное. Проверка, никогда не видевшая поломки, — украшение
(`.claude/rules/deployment.md`).

Стенды одноразовые и синтетические: предмет прибора — ФОРМА чужого кода, и
писать стенд текстом честнее, чем ловить живой модуль, который завтра починят.
Живое дерево трогается ровно одним контролем — «прибор не холост на настоящем
населении», и он намеренно не закрепляет ЧИСЛО находок: закрепить его значило
бы сделать красным тот цикл, который находку УСТРАНИТ.

## Положительный контроль на СОБСТВЕННУЮ ошибку этого цикла

Первая редакция `classify` считала находкой сам факт «предикат зовётся и из
`main`, и из производителя», и первый же прогон показал ложное срабатывание:
у `ceo_agent_v2` `should_run` — ОДНА чистая функция, `run_ceo` ею гейтится, а
`main --check` зовёт её, чтобы ПОКАЗАТЬ вердикт. Два вызова одного правила и
две копии правила — разные вещи. Ошибку нашёл замер, а не перечитывание,
поэтому она закреплена тестом `test_same_predicate_in_main_and_producer_is_not_a_finding`.

Часы инъектируются (`measure(now=)`), литеральных дат в фикстурах нет.
"""
# LLM_FORBIDDEN
# FROZEN-DATE-OK: injected-clock — NOW уезжает аргументом в `measure(now=)` и
# `run(now=)`, других источников времени у предмета нет; календарь хоста в
# вердикте не участвует ни одной веткой.
from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import tact_gate_census as tgc

#: Часы — ВХОД, а не окружение.
NOW = dt.datetime(2026, 9, 18, 11, 0, tzinfo=dt.timezone.utc)

REPO = Path(__file__).resolve().parents[2]


def _tree(files: dict) -> Path:
    """Одноразовое дерево с каталогами населения. Живое `data/` не трогается."""
    root = Path(tempfile.mkdtemp(prefix="tgc_stand_"))
    for sub in tgc.SCAN_DIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return root


GATE_IN_RUN = '''
TACT_DAYS = 7


def measurement_due(out, now=None):
    return True, "срок"


def run(root, if_due=True):
    if if_due:
        due, why = measurement_due(root)
        if not due:
            return {"measured": False}
    return {"measured": True}


def main(argv=None):
    return run(".", if_due=True)
'''

GATE_IN_MAIN_ONLY = '''
def publication_due(today=None):
    return True, "срок"


def build(published_at=None):
    return {"doc": 1}


def main(argv=None):
    due, why = publication_due()
    if not due:
        return 0
    return build()
'''

TWO_DIFFERENT_RULES = '''
def measurement_due(out):
    return True, "одно правило"


def publication_due(out):
    return True, "другое правило"


def run(root):
    if measurement_due(root)[0]:
        return 1
    return 0


def main(argv=None):
    if publication_due(None)[0]:
        return run(".")
    return 0
'''

SAME_RULE_SHOWN_IN_MAIN = '''
def should_run(context, now):
    return True, "weekly"


def run_ceo(now_fn):
    due, trigger = should_run({}, now_fn())
    if not due:
        return 0
    return 1


def main(argv=None):
    # --check: зовёт предикат, чтобы ПОКАЗАТЬ его вердикт, а не гейтить
    due, trigger = should_run({}, None)
    print({"should_run": due})
    return run_ceo(lambda: None)
'''

NO_GATE = '''
def build():
    return 1
'''

SURFACE = '''
MAX_AGE_HOURS = 12


def build(age):
    if age > MAX_AGE_HOURS:
        return None
    atomic_save({"a": 1}, "/tmp/x.json")
'''

SURFACE_CONST_BUT_NO_BRANCH = '''
MAX_AGE_HOURS = 12


def build():
    atomic_save({"slo": MAX_AGE_HOURS}, "/tmp/x.json")
'''

SURFACE_BRANCH_BUT_NO_WRITE = '''
MAX_AGE_HOURS = 12


def look(age):
    if age > MAX_AGE_HOURS:
        return "старо"
    return "свежо"
'''


class GateNameIsTokenised(unittest.TestCase):
    """Имя предиката — по ТОКЕНАМ. Подстрока даёт находку из слова (урок #556)."""

    def test_predicate_names_are_recognised(self):
        for name in ("measurement_due", "publication_due", "reveal_due",
                     "is_due", "should_run", "_refresh_market_data_if_due"):
            with self.subTest(name=name):
                self.assertTrue(tgc.is_gate_name(name))

    def test_substring_due_is_not_a_predicate(self):
        # ОБРАТНАЯ СТОРОНА: «due» подстрокой живёт в словах, сроком не
        # управляющих. Признай их — и перепись найдёт гейт в слове.
        for name in ("overdue_at", "residue", "dues", "due_date", "duel",
                     "run", "build", "should_have_been"):
            with self.subTest(name=name):
                self.assertFalse(tgc.is_gate_name(name))


class ClassifyAnswersWhereTheGateLives(unittest.TestCase):

    def test_no_calls_is_not_in_population(self):
        self.assertIsNone(tgc.classify([]))

    def test_gate_only_in_main_is_the_finding(self):
        self.assertEqual(
            tgc.classify([("publication_due", "main", 10)]), tgc.CLASS_CLI_ONLY)

    def test_gate_in_producer_passes(self):
        self.assertEqual(
            tgc.classify([("measurement_due", "run", 10)]), tgc.CLASS_IN_PRODUCER)

    def test_same_predicate_in_main_and_producer_is_not_a_finding(self):
        """Положительный контроль на СОБСТВЕННУЮ ошибку первой редакции.

        Два ВЫЗОВА одного правила — не две копии правила. Верни сюда прежнюю
        мерку («`main` в держателях ⇒ находка»), и перепись объявит находкой
        `ceo_agent_v2`, где `main --check` предикат лишь показывает.
        """
        self.assertEqual(
            tgc.classify([("should_run", "run_ceo", 10),
                          ("should_run", "main", 40)]),
            tgc.CLASS_IN_PRODUCER)

    def test_different_predicates_are_two_rules(self):
        # ОБРАТНАЯ СТОРОНА предыдущего: разные предикаты — это уже два правила,
        # и разойтись они могут молча.
        self.assertEqual(
            tgc.classify([("measurement_due", "run", 10),
                          ("publication_due", "main", 40)]),
            tgc.CLASS_TWO_RULES)

    def test_module_level_gate_is_not_credited_to_a_function(self):
        self.assertEqual(
            tgc.classify([("is_due", "<module>", 3)]), tgc.CLASS_IN_PRODUCER)


class MeasureKeepsTheAccountingIdentity(unittest.TestCase):
    """Каждый вход обязан куда-то лечь: молча уронить файл нельзя."""

    def test_every_scanned_file_lands_in_exactly_one_bucket(self):
        root = _tree({
            "spa_core/a.py": GATE_IN_RUN,
            "scripts/b.py": GATE_IN_MAIN_ONLY,
            "spa_core/c.py": NO_GATE,
            "scripts/broken.py": "def f(:\n",
        })
        doc = tgc.measure(root, now=NOW)
        c = doc["counts"]
        self.assertEqual(
            doc["scanned"],
            c[tgc.CLASS_IN_PRODUCER] + c[tgc.CLASS_CLI_ONLY]
            + c[tgc.CLASS_TWO_RULES] + c["no_gate"] + c["unreadable"])

    def test_unparsable_file_is_named_with_a_reason_not_skipped(self):
        root = _tree({"spa_core/a.py": GATE_IN_RUN, "scripts/broken.py": "def f(:\n"})
        doc = tgc.measure(root, now=NOW)
        self.assertEqual(doc["counts"]["unreadable"], 1)
        (row,) = doc["unreadable"]
        self.assertEqual(row["module"], "scripts/broken.py")
        self.assertTrue(row["reason"], "третий исход обязан нести ПРИЧИНУ")

    def test_verdicts_on_a_known_stand(self):
        root = _tree({
            "spa_core/in_run.py": GATE_IN_RUN,
            "scripts/cli_only.py": GATE_IN_MAIN_ONLY,
            "spa_core/two_rules.py": TWO_DIFFERENT_RULES,
            "spa_core/shown.py": SAME_RULE_SHOWN_IN_MAIN,
            "spa_core/none.py": NO_GATE,
        })
        doc = tgc.measure(root, now=NOW)
        verdicts = {r["module"]: r["verdict"] for r in doc["rows"]}
        self.assertEqual(verdicts, {
            "spa_core/in_run.py": tgc.CLASS_IN_PRODUCER,
            "scripts/cli_only.py": tgc.CLASS_CLI_ONLY,
            "spa_core/two_rules.py": tgc.CLASS_TWO_RULES,
            "spa_core/shown.py": tgc.CLASS_IN_PRODUCER,
        })
        self.assertEqual(doc["status"], "FINDING")

    def test_finding_names_what_stays_ungated(self):
        """Находка обязана назвать функцию, которую второй звавший позовёт."""
        root = _tree({"scripts/cli_only.py": GATE_IN_MAIN_ONLY})
        (row,) = tgc.measure(root, now=NOW)["rows"]
        self.assertEqual(row["ungated_producers"], ["build"])

    def test_main_is_not_called_an_ungated_producer(self):
        # ОБРАТНАЯ СТОРОНА: `main` — это CLI, а не та функция, которую позовёт
        # ступень моста; назвав её, находка советовала бы чинить не то.
        root = _tree({"spa_core/in_run.py": GATE_IN_RUN})
        (row,) = tgc.measure(root, now=NOW)["rows"]
        self.assertNotIn("main", row["ungated_producers"])

    def test_clean_tree_is_clean(self):
        root = _tree({"spa_core/a.py": GATE_IN_RUN, "spa_core/b.py": NO_GATE})
        doc = tgc.measure(root, now=NOW)
        self.assertEqual(doc["status"], "CLEAN")
        self.assertEqual(doc["rows"][0]["verdict"], tgc.CLASS_IN_PRODUCER)

    def test_tests_are_excluded_from_the_population(self):
        root = _tree({"spa_core/tests/test_x.py": GATE_IN_MAIN_ONLY,
                      "spa_core/a.py": NO_GATE})
        doc = tgc.measure(root, now=NOW)
        self.assertEqual(doc["scanned"], 1)
        self.assertEqual(doc["rows"], [])


class SurfaceOutsideTheNameRuleIsMeasured(unittest.TestCase):
    """Слепота правила имени — ЧИСЛО, а не обещание: «не нашли» ≠ «нет»."""

    def test_producer_with_an_unnamed_gate_is_counted(self):
        root = _tree({"spa_core/s.py": SURFACE})
        doc = tgc.measure(root, now=NOW)
        self.assertEqual(doc["surface_outside_name_rule"], ["spa_core/s.py"])

    def test_constant_without_a_branch_is_not_surface(self):
        # ОБРАТНАЯ СТОРОНА: объявленная константа может стоять в отчёте. Признай
        # её следом гейта — и граница раздуется, перестав что-либо ограничивать.
        root = _tree({"spa_core/s.py": SURFACE_CONST_BUT_NO_BRANCH})
        self.assertEqual(tgc.measure(root, now=NOW)["surface_outside_name_rule"], [])

    def test_branch_without_an_artifact_write_is_not_surface(self):
        root = _tree({"spa_core/s.py": SURFACE_BRANCH_BUT_NO_WRITE})
        self.assertEqual(tgc.measure(root, now=NOW)["surface_outside_name_rule"], [])

    def test_named_predicate_leaves_the_surface(self):
        # У модуля с НАЗВАННЫМ предикатом граница ни при чём: он уже в населении.
        root = _tree({"spa_core/a.py": GATE_IN_RUN})
        self.assertEqual(tgc.measure(root, now=NOW)["surface_outside_name_rule"], [])


class ThirdOutcomeIsNeverGreen(unittest.TestCase):
    """«Не измерено» не выдаётся ни за «чисто», ни за ноль (инв. #17)."""

    def test_missing_root_raises_not_measured(self):
        with self.assertRaises(tgc.NotMeasured):
            tgc.measure(Path("/nonexistent/spa/tree"), now=NOW)

    def test_missing_population_dir_raises_not_measured(self):
        root = Path(tempfile.mkdtemp(prefix="tgc_empty_"))
        (root / "spa_core").mkdir()
        with self.assertRaises(tgc.NotMeasured):
            tgc.measure(root, now=NOW)

    def test_empty_population_raises_not_measured(self):
        root = _tree({})
        with self.assertRaises(tgc.NotMeasured):
            tgc.measure(root, now=NOW)

    def test_run_records_unmeasured_and_says_why(self):
        out = Path(tempfile.mkdtemp(prefix="tgc_out_")) / "a.json"
        res = tgc.run(Path("/nonexistent/spa/tree"), dest=out, now=NOW)
        self.assertFalse(res["measured"])
        doc = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(doc["status"], "UNMEASURED")
        self.assertTrue(doc["reason"])
        self.assertNotIn("counts", doc, "у неизмеренного документа корзин быть не может")


class ReportAndExitCodes(unittest.TestCase):

    def test_exit_codes_separate_three_outcomes(self):
        clean = _tree({"spa_core/a.py": GATE_IN_RUN})
        finding = _tree({"scripts/b.py": GATE_IN_MAIN_ONLY})
        self.assertEqual(tgc.main(["--root", str(clean), "--no-write"]), 0)
        self.assertEqual(tgc.main(["--root", str(finding), "--no-write"]), 1)
        self.assertEqual(
            tgc.main(["--root", "/nonexistent/spa/tree", "--no-write"]), 2)

    def test_report_prints_the_accounting_identity(self):
        root = _tree({"scripts/b.py": GATE_IN_MAIN_ONLY, "spa_core/c.py": NO_GATE})
        lines = tgc.report(tgc.measure(root, now=NOW))
        self.assertTrue(any("[УЧЁТ]" in ln for ln in lines))
        self.assertTrue(any("[НАХОДКА]" in ln and "cli_only" in ln for ln in lines))

    def test_clean_rows_are_never_labelled_as_findings(self):
        """Выживший мутант мини-батареи: печатай прибор ВСЕ строки — и модуль
        со здоровым гейтом вышел бы под знаком `[НАХОДКА]`. Число в шапке
        осталось бы верным, а перечень под ним звал бы чинить исправное."""
        root = _tree({"spa_core/a.py": GATE_IN_RUN, "scripts/b.py": GATE_IN_MAIN_ONLY})
        named = [ln for ln in tgc.report(tgc.measure(root, now=NOW))
                 if ln.startswith("[НАХОДКА]")]
        self.assertEqual(len(named), 1)
        self.assertIn("scripts/b.py", named[0])
        self.assertNotIn("spa_core/a.py", " ".join(named))

    def test_report_states_the_name_rule_boundary_even_when_empty(self):
        # Строка о границе печатается ВСЕГДА: исчезни она при нуле, читатель
        # прочёл бы «нашли одного» как «он один и есть».
        root = _tree({"spa_core/a.py": GATE_IN_RUN})
        lines = tgc.report(tgc.measure(root, now=NOW))
        self.assertTrue(any("[ГРАНИЦА ПРАВИЛА ИМЕНИ]" in ln for ln in lines))

    def test_unmeasured_report_says_so_and_stops(self):
        doc = tgc.run(Path("/nonexistent/spa/tree"), write=False, now=NOW)["doc"]
        lines = tgc.report(doc)
        self.assertEqual(len(lines), 1)
        self.assertIn("НЕ ИЗМЕРЕНО", lines[0])

    def test_office_rendering_delegates_and_does_not_copy_the_rule(self):
        """У офиса НЕТ второй копии правила отрисовки — иначе «в консоли одно,
        в отчёте другое» расходилось бы молча (ровно класс этой переписи)."""
        root = _tree({"scripts/b.py": GATE_IN_MAIN_ONLY})
        doc = tgc.measure(root, now=NOW)
        plain = tgc.report(doc, max_rows=5)
        office = tgc.format_report(doc, max_rows=5)
        self.assertEqual(office[1:], plain[1:])
        self.assertTrue(office[0].startswith("⚠️"))
        self.assertEqual(office[0][2:].strip(), plain[0])

    def test_clean_report_is_not_marked_as_a_finding(self):
        root = _tree({"spa_core/a.py": GATE_IN_RUN})
        office = tgc.format_report(tgc.measure(root, now=NOW))
        self.assertFalse(office[0].startswith("⚠️"))


class TruncationCannotHideTheFinding(unittest.TestCase):
    """Отчёт усекается, и усечение режет ХВОСТ — значит голова обязана нести
    сильнейшее свидетельство.

    Положительный контроль на ЖИВОЙ дефект, найденный контролем чтения 18.09:
    порядок обхода дерева ставил `scripts/` после `spa_core/`, находка падала в
    хвост, и офис печатал «только в CLI 1», НЕ НАЗЫВАЯ кого. Число было верным,
    а действовать по нему было нельзя.
    """

    def _tree_with_late_finding(self):
        files = {f"spa_core/p{i}.py": GATE_IN_RUN for i in range(6)}
        files["scripts/zzz_last.py"] = GATE_IN_MAIN_ONLY
        return _tree(files)

    def test_finding_is_named_even_though_it_is_scanned_last(self):
        doc = tgc.measure(self._tree_with_late_finding(), now=NOW)
        lines = tgc.format_report(doc, max_rows=5)
        self.assertTrue(any("scripts/zzz_last.py" in ln for ln in lines),
                        "находка обязана попасть в голову отчёта")

    def test_findings_lead_the_rows_of_the_artifact(self):
        doc = tgc.measure(self._tree_with_late_finding(), now=NOW)
        verdicts = [r["verdict"] for r in doc["rows"]]
        self.assertEqual(verdicts[0], tgc.CLASS_CLI_ONLY)
        self.assertNotIn(tgc.CLASS_CLI_ONLY, verdicts[1:])

    def test_truncation_announces_itself(self):
        # ОБРАТНАЯ СТОРОНА: умолчание об укорочении и есть способ соврать
        # усечением — перечень прочёлся бы как полный.
        files = {f"scripts/f{i}.py": GATE_IN_MAIN_ONLY for i in range(4)}
        doc = tgc.measure(_tree(files), now=NOW)
        lines = tgc.report(doc, max_rows=2)
        self.assertEqual(sum(1 for ln in lines if ln.startswith("[НАХОДКА]")), 2)
        self.assertTrue(any(ln.startswith("[…]") and "из 4" in ln for ln in lines))

    def test_complete_list_is_not_announced_as_truncated(self):
        files = {f"scripts/f{i}.py": GATE_IN_MAIN_ONLY for i in range(2)}
        lines = tgc.report(tgc.measure(_tree(files), now=NOW), max_rows=5)
        self.assertFalse(any(ln.startswith("[…]") for ln in lines))


class LiveControlOnTheRealTree(unittest.TestCase):
    """Один живой контроль: прибор не холост на настоящем населении.

    ЧИСЛО находок здесь намеренно НЕ закрепляется — закрепив его, я покрасил бы
    тот цикл, который находку устранит (заказ G40 п. 1 именно об этом).
    Закрепляется то, что от починки не меняется: перепись видит население,
    учёт сходится, и каждая названная строка указывает на существующий файл.
    """

    def test_real_tree_is_measured_and_accounted_for(self):
        doc = tgc.measure(REPO, now=NOW)
        c = doc["counts"]
        self.assertGreater(doc["scanned"], 500, "население не должно быть холостым")
        self.assertEqual(
            doc["scanned"],
            c[tgc.CLASS_IN_PRODUCER] + c[tgc.CLASS_CLI_ONLY]
            + c[tgc.CLASS_TWO_RULES] + c["no_gate"] + c["unreadable"])
        self.assertGreaterEqual(
            c[tgc.CLASS_IN_PRODUCER] + c[tgc.CLASS_CLI_ONLY] + c[tgc.CLASS_TWO_RULES],
            1, "хотя бы один гейт такта в этом дереве существует")
        for row in doc["rows"]:
            self.assertTrue((REPO / row["module"]).is_file())


if __name__ == "__main__":
    unittest.main()
