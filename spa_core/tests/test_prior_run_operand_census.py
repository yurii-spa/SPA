"""Батарея переписи «предыдущий прогон из git-tracked артефакта» (заказ G86 п. 3).

Каждый тест — либо положительный контроль РЕАЛЬНОЙ формы (авария ADR-475, идиомы
паритета и валидатора, три дефекта чернового прибора, найденные контролем), либо
контроль в ОБРАТНУЮ сторону: исход обязан меняться от порванного звена, и рвать
надо каждое звено поимённо.

Часов в приборе нет ВОВСЕ, поэтому литеральных дат в батарее нет по построению —
`FROZEN-DATE-OK` не нужен и не ставится. Литеральных pid здесь тоже нет: прибор ни
одного процесса не спрашивает.
"""

from __future__ import annotations

import ast
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from spa_core.monitoring import prior_run_operand_census as census  # noqa: E402

C = census


# ──────────────────────────────────────────────────────────────────────────────
# Сцены
# ──────────────────────────────────────────────────────────────────────────────

#: Форма аварии ADR-475 ДОСЛОВНО: запись через ЛОКАЛЬНОГО помощника, чтение своего же
#: артефакта, прошлый операнд встречается с ЖИВЫМ наблюдением в решении, возраст
#: прошлого артефакта не спрашивается.
SCENE_ADR475 = '''
import json, pathlib, urllib.request
REPORT = pathlib.Path("data") / "guard_report.json"
SNAP = pathlib.Path("data") / "snapshot.json"

def _atomic_write(path, obj):
    path.write_text(json.dumps(obj))

def evaluate(*, snapshot, prev_report, live):
    stale_now = snapshot.get("age_h", 0) > 48
    prev_stale = bool(prev_report and prev_report.get("stale"))
    degrade = stale_now and prev_stale
    return {"degrade": degrade, "live": live}

def run():
    prev = None
    if REPORT.exists():
        prev = json.loads(REPORT.read_text())
    snapshot = json.loads(SNAP.read_text())
    live = urllib.request.urlopen("https://example.invalid").read()
    report = evaluate(snapshot=snapshot, prev_report=prev, live=live)
    _atomic_write(REPORT, report)
    return report
'''

#: То же, но читатель СПРАШИВАЕТ ВОЗРАСТ прошлого артефакта — состояние кустодиана
#: ПОСЛЕ ADR-475. Единственное отличие от сцены выше, и исход обязан отличаться.
SCENE_AGE_NAMED = SCENE_ADR475.replace(
    '''def evaluate(*, snapshot, prev_report, live):
    stale_now = snapshot.get("age_h", 0) > 48''',
    '''MAX_AGE_H = 24

def evaluate(*, snapshot, prev_report, live):
    import datetime
    prev_ts = datetime.datetime.fromisoformat(prev_report.get("ts")) if prev_report else None
    prev_age_h = prev_ts.timestamp() if prev_ts else None
    if prev_age_h is not None and prev_age_h > MAX_AGE_H:
        prev_report = None
    stale_now = snapshot.get("age_h", 0) > 48''',
)

#: Идиома ПАРИТЕТА: закоммиченная копия читается как ПРЕДМЕТ, рядом строится свежая
#: тем же производителем модуля, расхождение и есть вердикт.
SCENE_PARITY = '''
import json, pathlib
OUT = pathlib.Path("data") / "guard_report.json"

def build_payload(generated):
    return {"generated": generated, "rows": [1, 2, 3]}

def main(check):
    if check:
        committed = json.loads(OUT.read_text())
        fresh = build_payload(generated=committed.get("generated", ""))
        if committed != fresh:
            return 1
        return 0
    out = build_payload(generated="today")
    with open(OUT, "w") as fh:
        json.dump(out, fh)
    return 0
'''

#: Идиома ВАЛИДАТОРА: прошлое содержимое сверяется с ЛИТЕРАЛАМИ, ни одного наблюдения
#: этого прогона в решении нет. Это проверка документа, а не решение о мире.
SCENE_VALIDATOR = '''
import json, pathlib
BOARD = pathlib.Path("board.json")

def check(board):
    if board.get("done_count", 0) < 0:
        return ["negative"]
    return []

def main():
    board = json.loads(BOARD.read_text())
    issues = check(board)
    board["checked"] = True
    BOARD.write_text(json.dumps(board))
    return 1 if issues else 0
'''

WORKFLOW_CALLS_READER = """
name: guard
on: [push]
jobs:
  run:
    permissions:
      contents: read
    steps:
      - run: python3 scripts/guard.py
"""

WORKFLOW_SILENT = """
name: other
on: [push]
jobs:
  run:
    steps:
      - run: echo nothing to do here
"""

WORKFLOW_COMMITS_BACK = """
name: guard
on: [push]
jobs:
  run:
    permissions:
      contents: write
    steps:
      - run: python3 scripts/guard.py
      - run: git commit -am "carry data/guard_report.json forward"
"""


class _Scene:
    """Одноразовое дерево. Имя ветки объявляется ВХОДОМ (`git init -b`).

    Причина в правиле доставки: `init.defaultBranch` хоста не объявлен, Apple Git даёт
    `main`, git на `ubuntu-latest` — `master`, и фикстура, назвавшая потом `origin/main`,
    зелена здесь и красна там (ADR-479).
    """

    BRANCH = "scene"

    def __init__(self, reader_source, *, workflow=WORKFLOW_CALLS_READER,
                 track=("data/guard_report.json", "data/snapshot.json"),
                 reader_rel="scripts/guard.py", extra_files=()):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="spa_prior_run_scene_"))
        (self.root / "scripts").mkdir(parents=True, exist_ok=True)
        (self.root / "spa_core").mkdir(parents=True, exist_ok=True)
        (self.root / "data").mkdir(parents=True, exist_ok=True)
        (self.root / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
        reader = self.root / reader_rel
        reader.parent.mkdir(parents=True, exist_ok=True)
        reader.write_text(reader_source, encoding="utf-8")
        if workflow is not None:
            (self.root / ".github" / "workflows" / "guard.yml").write_text(
                workflow, encoding="utf-8")
        for rel, body in extra_files:
            target = self.root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
        subprocess.run(["git", "init", "-b", self.BRANCH], cwd=self.root,
                       check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "scene@example.invalid"],
                       cwd=self.root, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "scene"], cwd=self.root,
                       check=True, capture_output=True)
        for rel in track:
            target = self.root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}", encoding="utf-8")
            subprocess.run(["git", "add", "-f", rel], cwd=self.root,
                           check=True, capture_output=True)
        subprocess.run(["git", "add", "-f", reader_rel], cwd=self.root,
                       check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "scene"], cwd=self.root,
                       check=True, capture_output=True)

    def measure(self):
        return C.measure(self.root)

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)


def _verdict_of(doc, reader="scripts/guard.py", artifact="guard_report.json"):
    """Единственный исход, в который лёг именно этот читатель.

    Читается не по счётчику (счётчики совпадают у разных клеток), а по НЕНУЛЕВОМУ
    исходу при населении из одной значащей пары — плюс проверяется, что сумма равна
    населению. «Имя не есть адрес» (ADR-465), поэтому адресуемся образцами.
    """
    for row in doc["findings"]:
        if row["reader"] == reader and artifact in row["artifact"]:
            return C.OUT_CONST_TRUSTED
    for row in doc["named_sample"]:
        if row["reader"] == reader and artifact in row["artifact"]:
            return C.OUT_CONST_NAMED
    for row in doc["committed_sample"]:
        if row["reader"] == reader and artifact in row["artifact"]:
            return C.OUT_COMMITTED_BACK
    for row in doc.get("excluded_sample", ()):
        if row["reader"] == reader and artifact in row["artifact"]:
            return row["why"]
    nonzero = [k for k, v in doc["outcomes"].items() if v]
    return nonzero[0] if len(nonzero) == 1 else f"ambiguous:{nonzero}"


# ──────────────────────────────────────────────────────────────────────────────
# Положительные контроли самой аварии
# ──────────────────────────────────────────────────────────────────────────────

class TheAdr475FormIsFound(unittest.TestCase):
    """Авария 25.09 обязана находиться ДОСЛОВНОЙ своей формой."""

    def setUp(self):
        self.scene = _Scene(SCENE_ADR475)
        self.addCleanup(self.scene.close)

    def test_the_guard_that_trusts_a_committed_prior_report_is_a_finding(self):
        doc = self.scene.measure()
        self.assertTrue(doc["measured"], doc)
        self.assertEqual(_verdict_of(doc), C.OUT_CONST_TRUSTED)
        self.assertEqual(doc["outcomes"][C.OUT_CONST_TRUSTED], 1, doc["outcomes"])

    def test_the_finding_names_reader_artifact_and_job(self):
        doc = self.scene.measure()
        row = doc["findings"][0]
        self.assertEqual(row["reader"], "scripts/guard.py")
        self.assertEqual(row["artifact"], "data/guard_report.json")
        self.assertEqual(row["workflows"], ["guard.yml"])
        self.assertTrue(row["read_lines"] and row["write_lines"], row)

    def test_a_finding_makes_the_exit_code_one(self):
        self.assertEqual(C.verdict(self.scene.measure()), C.RC_FINDING)

    def test_the_report_prints_the_finding_in_full(self):
        text = C.format_report(self.scene.measure())
        self.assertIn("scripts/guard.py", text)
        self.assertIn("data/guard_report.json", text)
        self.assertIn("КОНСТАНТА", text)


class AskingTheAgeChangesTheVerdict(unittest.TestCase):
    """Контроль в ОБРАТНУЮ сторону: названный фоссил — не находка."""

    def setUp(self):
        self.scene = _Scene(SCENE_AGE_NAMED)
        self.addCleanup(self.scene.close)

    def test_a_guard_that_asks_the_prior_age_is_named_not_a_finding(self):
        doc = self.scene.measure()
        self.assertEqual(_verdict_of(doc), C.OUT_CONST_NAMED)
        self.assertEqual(doc["outcomes"][C.OUT_CONST_TRUSTED], 0, doc["outcomes"])

    def test_named_is_not_called_safe(self):
        """Исход зовётся `named`, а не `safe`: верность порога прибор не мерит."""
        self.assertIn("named", C.OUT_CONST_NAMED)
        self.assertNotIn("safe", C.OUT_CONST_NAMED)

    def test_a_named_fossil_leaves_the_exit_code_zero(self):
        self.assertEqual(C.verdict(self.scene.measure()), C.RC_MEASURED)


class KeywordOnlyParametersWereADefectOfTheDraft(unittest.TestCase):
    """Первый черновик не видел `kwonlyargs` — и выдумывал находку на исправленном коде.

    Положительный контроль НАСТОЯЩЕГО дефекта: `evaluate(*, …, prev_report=None)` у
    кустодиана объявлен только-именными параметрами, метка прошлого до параметра не
    доходила, и `constant_in_ci_named` читался как `constant_in_ci_trusted`.
    """

    def test_taint_reaches_a_keyword_only_parameter(self):
        tree = ast.parse(SCENE_AGE_NAMED)
        resolver = C._PathResolver(tree)
        tainted = C._spread(tree, C._read_bindings(tree, "guard_report.json", resolver))
        self.assertIn("prev_report", tainted, sorted(tainted))

    def test_parameters_reports_positional_and_keyword_only_separately(self):
        fdef = [n for n in ast.walk(ast.parse(SCENE_AGE_NAMED))
                if isinstance(n, ast.FunctionDef) and n.name == "evaluate"][0]
        positional, names = C._parameters(fdef)
        self.assertEqual(positional, [])
        self.assertEqual(sorted(names), ["live", "prev_report", "snapshot"])

    def test_the_age_question_is_seen_through_a_keyword_only_parameter(self):
        tree = ast.parse(SCENE_AGE_NAMED)
        self.assertTrue(C._asks_the_age(tree, "guard_report.json", C._PathResolver(tree)))

    def test_and_is_not_seen_where_the_age_is_never_asked(self):
        tree = ast.parse(SCENE_ADR475)
        self.assertFalse(C._asks_the_age(tree, "guard_report.json", C._PathResolver(tree)))


class WriteThroughALocalHelperWasADefectOfTheDraft(unittest.TestCase):
    """Без уровня локального помощника население аварии равно НУЛЮ.

    Кустодиан пишет отчёт не примитивом, а своим `_atomic_write(_REPORT, report)`.
    Первый черновик знал только примитивы и дал на положительном контроле 0 пар.
    """

    def test_the_helper_write_puts_the_pair_into_the_population(self):
        tree = ast.parse(SCENE_ADR475)
        writes, reads = C._sites(tree, C._PathResolver(tree))
        self.assertIn("guard_report.json", writes)
        self.assertIn("guard_report.json", reads)

    def test_the_helper_is_recognised_by_its_parameter_reaching_a_primitive(self):
        slots = C._helper_path_slots(ast.parse(SCENE_ADR475))
        self.assertIn("_atomic_write", slots)
        self.assertEqual(slots["_atomic_write"]["write"], {0})

    def test_a_helper_that_never_writes_is_not_a_write_site(self):
        source = SCENE_ADR475.replace("path.write_text(json.dumps(obj))",
                                      "return json.dumps(obj)")
        writes, reads = C._sites(ast.parse(source), C._PathResolver(ast.parse(source)))
        self.assertNotIn("guard_report.json", writes)
        self.assertIn("guard_report.json", reads)


# ──────────────────────────────────────────────────────────────────────────────
# Ноги, спрошенные по очереди: рвём каждую поимённо
# ──────────────────────────────────────────────────────────────────────────────

class TheReachLegIsAskedFirst(unittest.TestCase):
    def test_a_host_only_reader_is_not_a_finding(self):
        scene = _Scene(SCENE_ADR475, workflow=WORKFLOW_SILENT)
        self.addCleanup(scene.close)
        doc = scene.measure()
        self.assertEqual(_verdict_of(doc), C.OUT_NOT_IN_CI)
        self.assertEqual(doc["outcomes"][C.OUT_CONST_TRUSTED], 0)

    def test_the_reader_is_found_by_module_path_too(self):
        wf = WORKFLOW_CALLS_READER.replace(
            "python3 scripts/guard.py", "python3 -m spa_core.guard")
        scene = _Scene(SCENE_ADR475, workflow=wf,
                       reader_rel="spa_core/guard.py")
        self.addCleanup(scene.close)
        doc = scene.measure()
        self.assertEqual(_verdict_of(doc, reader="spa_core/guard.py"),
                         C.OUT_CONST_TRUSTED)

    def test_a_longer_neighbouring_name_is_not_our_reader(self):
        """`guard_extra.py` в джобе не есть упоминание `guard.py`."""
        wf = WORKFLOW_CALLS_READER.replace("scripts/guard.py", "scripts/guard_extra.py")
        scene = _Scene(SCENE_ADR475, workflow=wf)
        self.addCleanup(scene.close)
        self.assertEqual(_verdict_of(scene.measure()), C.OUT_NOT_IN_CI)


class TheTrackedLegSeparatesAbsentFromWrong(unittest.TestCase):
    def test_an_untracked_artifact_is_absent_in_ci_not_a_finding(self):
        scene = _Scene(SCENE_ADR475, track=("data/snapshot.json",))
        self.addCleanup(scene.close)
        doc = scene.measure()
        self.assertEqual(_verdict_of(doc), C.OUT_ABSENT_IN_CI)
        self.assertEqual(doc["outcomes"][C.OUT_CONST_TRUSTED], 0)

    def test_an_artifact_at_the_repository_root_counts_as_tracked(self):
        """Второй дефект черновика: радиус `git ls-files data` гасил `KANBAN.json`."""
        source = SCENE_ADR475.replace('pathlib.Path("data") / "guard_report.json"',
                                      'pathlib.Path("GUARD_REPORT.json")')
        scene = _Scene(source, track=("GUARD_REPORT.json", "data/snapshot.json"))
        self.addCleanup(scene.close)
        doc = scene.measure()
        self.assertEqual(_verdict_of(doc, artifact="GUARD_REPORT.json"),
                         C.OUT_CONST_TRUSTED)

    def test_two_tracked_paths_with_one_name_are_unmeasured_and_loud(self):
        """Имя не есть адрес: выбор одного из двух был бы догадкой (ADR-465)."""
        scene = _Scene(SCENE_ADR475,
                       track=("data/guard_report.json", "data/snapshot.json",
                              "landing/guard_report.json"))
        self.addCleanup(scene.close)
        doc = scene.measure()
        self.assertEqual(doc["outcomes"][C.OUT_UNMEASURED], 1, doc["outcomes"])
        self.assertEqual(doc["outcomes"][C.OUT_CONST_TRUSTED], 0)
        self.assertTrue(
            any(r.startswith("artifact_name_ambiguous_in_repo:guard_report.json:2")
                for r in doc["unmeasured_reasons"]),
            doc["unmeasured_reasons"])
        self.assertEqual(C.verdict(doc), C.RC_UNMEASURED)


class TheWriterLegAsksWhoCommitsTheArtifactBack(unittest.TestCase):
    def test_a_workflow_that_commits_the_artifact_makes_it_an_observation(self):
        scene = _Scene(SCENE_ADR475, workflow=WORKFLOW_COMMITS_BACK)
        self.addCleanup(scene.close)
        doc = scene.measure()
        self.assertEqual(_verdict_of(doc), C.OUT_COMMITTED_BACK)
        self.assertEqual(doc["committed_sample"][0]["writers"], ["workflow:guard.yml"])

    def test_a_workflow_that_only_mentions_the_artifact_is_not_a_writer(self):
        wf = WORKFLOW_COMMITS_BACK.replace(
            'git commit -am "carry data/guard_report.json forward"',
            'echo data/guard_report.json')
        scene = _Scene(SCENE_ADR475, workflow=wf)
        self.addCleanup(scene.close)
        self.assertEqual(_verdict_of(scene.measure()), C.OUT_CONST_TRUSTED)

    def test_a_delivery_call_receiving_the_path_is_a_writer(self):
        """Третий дефект черновика: свой же публикатор в радиус не входил."""
        source = SCENE_ADR475.replace(
            "    _atomic_write(REPORT, report)",
            "    _atomic_write(REPORT, report)\n    push_to_github(REPORT, 'carry')")
        scene = _Scene(source)
        self.addCleanup(scene.close)
        doc = scene.measure()
        self.assertEqual(_verdict_of(doc), C.OUT_COMMITTED_BACK)
        self.assertTrue(doc["committed_sample"][0]["writers"][0].startswith("call:"),
                        doc["committed_sample"])

    def test_a_delivery_call_for_a_DIFFERENT_artifact_is_not_a_writer(self):
        """Со-присутствие в одном файле писателем не является — иначе авария ADR-475
        оправдалась бы собственным доставщиком снимка."""
        source = SCENE_ADR475.replace(
            "    _atomic_write(REPORT, report)",
            "    _atomic_write(REPORT, report)\n    push_to_github(SNAP, 'carry')")
        scene = _Scene(source)
        self.addCleanup(scene.close)
        self.assertEqual(_verdict_of(scene.measure()), C.OUT_CONST_TRUSTED)

    def test_one_call_naming_the_path_twice_is_still_one_writer(self):
        source = SCENE_ADR475.replace(
            "    _atomic_write(REPORT, report)",
            "    _atomic_write(REPORT, report)\n"
            "    push_to_github(REPORT, 'carry', rel=REPORT)")
        scene = _Scene(source)
        self.addCleanup(scene.close)
        doc = scene.measure()
        self.assertEqual(len(doc["committed_sample"][0]["writers"]), 1,
                         doc["committed_sample"])


class TheIdiomsThatLookLikeTheDefectAndAreNot(unittest.TestCase):
    def test_parity_with_own_regeneration_is_excluded_with_a_named_reason(self):
        scene = _Scene(SCENE_PARITY)
        self.addCleanup(scene.close)
        doc = scene.measure()
        self.assertEqual(_verdict_of(doc), C.OUT_PARITY)
        self.assertEqual(doc["outcomes"][C.OUT_CONST_TRUSTED], 0)

    def test_parity_needs_the_regeneration_to_be_a_LOCAL_producer(self):
        """`json.dumps` за пересборку не сходит: иначе идиома проглотила бы аварию."""
        tree = ast.parse(SCENE_ADR475)
        self.assertFalse(C._parity_with_own_regeneration(
            tree, "guard_report.json", C._PathResolver(tree)))

    def test_a_validator_comparing_only_with_literals_is_excluded(self):
        scene = _Scene(SCENE_VALIDATOR, track=("board.json",),
                       workflow=WORKFLOW_CALLS_READER)
        self.addCleanup(scene.close)
        doc = scene.measure()
        self.assertEqual(_verdict_of(doc, artifact="board.json"), C.OUT_NO_DECISION)

    def test_a_clock_is_a_current_observation_too(self):
        """Наблюдением этого прогона являются не только сеть и файл, но и часы."""
        source = SCENE_ADR475.replace(
            '    live = urllib.request.urlopen("https://example.invalid").read()',
            "    import datetime\n    live = datetime.datetime.now()")
        tree = ast.parse(source)
        self.assertTrue(C._meets_a_current_observation(
            tree, "guard_report.json", C._PathResolver(tree)))

    def test_the_decision_leg_needs_the_two_operands_to_MEET(self):
        """Наблюдение, существующее рядом но не встречающееся с прошлым, не считается."""
        source = SCENE_ADR475.replace(
            "    degrade = stale_now and prev_stale",
            "    degrade = prev_stale")
        tree = ast.parse(source)
        self.assertFalse(C._meets_a_current_observation(
            tree, "guard_report.json", C._PathResolver(tree)))


# ──────────────────────────────────────────────────────────────────────────────
# Форма исходов, третий исход, ADVISORY
# ──────────────────────────────────────────────────────────────────────────────

class TheOutcomeFormIsClosed(unittest.TestCase):
    def test_the_sum_of_outcomes_equals_the_population_on_a_scene(self):
        scene = _Scene(SCENE_ADR475)
        self.addCleanup(scene.close)
        doc = scene.measure()
        self.assertEqual(sum(doc["outcomes"].values()), doc["population"], doc)
        self.assertEqual(doc["notes"], [], doc["notes"])

    def test_every_declared_outcome_is_present_even_at_zero(self):
        """Инв. #17: «нет такого исхода» и «исход не считался» обязаны различаться."""
        scene = _Scene(SCENE_ADR475)
        self.addCleanup(scene.close)
        doc = scene.measure()
        self.assertEqual(sorted(doc["outcomes"]), sorted(C.OUTCOMES))
        self.assertIn(0, doc["outcomes"].values())

    def test_the_report_prints_every_outcome_name_including_the_zeros(self):
        scene = _Scene(SCENE_ADR475)
        self.addCleanup(scene.close)
        text = C.format_report(scene.measure())
        for name in C.OUTCOMES:
            self.assertIn(name, text, name)

    def test_the_cross_tab_number_is_reported_and_is_NOT_part_of_the_sum(self):
        scene = _Scene(SCENE_ADR475, workflow=WORKFLOW_SILENT)
        self.addCleanup(scene.close)
        doc = scene.measure()
        self.assertEqual(doc["host_only_but_git_tracked"], 1, doc)
        self.assertEqual(sum(doc["outcomes"].values()), doc["population"])
        self.assertIn("git checkout", C.format_report(doc))


class AbsentObservationIsItsOwnOutcome(unittest.TestCase):
    """Третий исход обязателен и ГРОМОК: «не измерено» никогда не 0 и не «чисто»."""

    def test_a_missing_workflows_directory_is_unmeasured_not_clean(self):
        scene = _Scene(SCENE_ADR475, workflow=None)
        self.addCleanup(scene.close)
        shutil.rmtree(scene.root / ".github", ignore_errors=True)
        doc = scene.measure()
        self.assertFalse(doc["measured"])
        self.assertEqual(doc["why_unmeasured"], "workflows_dir_missing")
        self.assertEqual(C.verdict(doc), C.RC_UNMEASURED)
        self.assertIn("НЕ ИЗМЕРЕНО", C.format_report(doc))

    def test_an_empty_workflows_directory_is_unmeasured_too(self):
        scene = _Scene(SCENE_ADR475, workflow=None)
        self.addCleanup(scene.close)
        doc = scene.measure()
        self.assertFalse(doc["measured"])
        self.assertEqual(doc["why_unmeasured"], "workflows_dir_empty")
        self.assertEqual(C.verdict(doc), C.RC_UNMEASURED)

    def test_a_tree_without_git_is_unmeasured_with_a_named_reason(self):
        root = pathlib.Path(tempfile.mkdtemp(prefix="spa_prior_run_nogit_"))
        self.addCleanup(shutil.rmtree, root, True)
        (root / "scripts").mkdir()
        (root / "scripts" / "guard.py").write_text(SCENE_ADR475, encoding="utf-8")
        (root / ".github" / "workflows").mkdir(parents=True)
        (root / ".github" / "workflows" / "g.yml").write_text(
            WORKFLOW_CALLS_READER, encoding="utf-8")
        doc = C.measure(root)
        self.assertFalse(doc["measured"])
        self.assertTrue(doc["why_unmeasured"].startswith("git_ls_files_failed"),
                        doc["why_unmeasured"])
        self.assertEqual(C.verdict(doc), C.RC_UNMEASURED)

    def test_an_unparsable_reader_is_counted_unmeasured_with_its_reason(self):
        scene = _Scene(SCENE_ADR475, extra_files=(("scripts/broken.py", "def ("),))
        self.addCleanup(scene.close)
        doc = scene.measure()
        self.assertEqual(doc["outcomes"][C.OUT_UNMEASURED], 1, doc["outcomes"])
        self.assertIn("unparsed:SyntaxError", doc["unmeasured_reasons"])
        self.assertEqual(C.verdict(doc), C.RC_UNMEASURED)

    def test_the_three_exit_codes_are_distinguishable(self):
        self.assertEqual(len({C.RC_MEASURED, C.RC_FINDING, C.RC_UNMEASURED}), 3)

    def test_a_form_refusal_makes_the_verdict_unmeasured_not_clean(self):
        """Сумма исходов, разошедшаяся с населением, есть ОТКАЗ, а не «чисто»."""
        doc = {"measured": True, "notes": ["сумма исходов 1 != населению 2"],
               "outcomes": {name: 0 for name in C.OUTCOMES}}
        self.assertEqual(C.verdict(doc), C.RC_UNMEASURED)


class TheInstrumentOnlyReads(unittest.TestCase):
    def test_applied_is_false(self):
        self.assertFalse(C.APPLIED)
        scene = _Scene(SCENE_ADR475)
        self.addCleanup(scene.close)
        self.assertFalse(scene.measure()["applied"])

    def test_the_scene_tree_is_not_modified_by_the_measurement(self):
        scene = _Scene(SCENE_ADR475)
        self.addCleanup(scene.close)
        before = subprocess.run(["git", "status", "--porcelain"], cwd=scene.root,
                                capture_output=True, text=True).stdout
        scene.measure()
        after = subprocess.run(["git", "status", "--porcelain"], cwd=scene.root,
                               capture_output=True, text=True).stdout
        self.assertEqual(before, after)

    def test_the_report_names_what_it_does_NOT_report(self):
        scene = _Scene(SCENE_ADR475)
        self.addCleanup(scene.close)
        doc = scene.measure()
        self.assertTrue(doc["not_reported"])
        self.assertIn("НЕ ДОКЛАДЫВАЕТ", C.format_report(doc))
        self.assertIn("ADVISORY", C.format_report(doc))


class PathSlotsAreReadInTheRightPosition(unittest.TestCase):
    """`atomic_save(data, path)` — путь ВТОРЫМ; `os.replace(tmp, path)` — целью ВТОРОЙ."""

    def test_atomic_save_takes_the_path_second(self):
        call = ast.parse('atomic_save(payload, "data/x.json")').body[0].value
        writes, reads = C._primitive_path_slots(call)
        self.assertEqual(len(writes), 1)
        self.assertEqual(C._artifact_literals(writes[0]), {"x.json"})
        self.assertEqual(reads, [])

    def test_os_replace_names_the_target_not_the_temporary(self):
        call = ast.parse('os.replace("data/x.json.tmp", "data/x.json")').body[0].value
        writes, _ = C._primitive_path_slots(call)
        self.assertEqual(C._artifact_literals(writes[0]), {"x.json"})

    def test_open_for_writing_and_open_for_reading_are_different_sites(self):
        w = ast.parse('open("data/x.json", "w")').body[0].value
        r = ast.parse('open("data/x.json")').body[0].value
        self.assertTrue(C._primitive_path_slots(w)[0])
        self.assertFalse(C._primitive_path_slots(w)[1])
        self.assertFalse(C._primitive_path_slots(r)[0])
        self.assertTrue(C._primitive_path_slots(r)[1])

    def test_a_mode_given_by_keyword_is_read_too(self):
        call = ast.parse('open("data/x.json", mode="a")').body[0].value
        self.assertTrue(C._primitive_path_slots(call)[0])

    def test_the_path_resolver_follows_a_chain_of_module_constants(self):
        tree = ast.parse('ROOT = "data"\nNAME = "x.json"\nP = ROOT + "/" + NAME\n')
        resolver = C._PathResolver(tree)
        node = ast.parse("P").body[0].value
        self.assertEqual(resolver.resolve(node), {"x.json"})

    def test_a_binding_cycle_does_not_hang_the_resolver(self):
        tree = ast.parse('A = B\nB = A\nC = "data/x.json"\nA = C\n')
        resolver = C._PathResolver(tree)
        self.assertEqual(resolver.resolve(ast.parse("A").body[0].value), {"x.json"})

    def test_a_non_artifact_extension_is_not_a_path(self):
        self.assertIsNone(C.ARTIFACT_NAME_RE.match("report.yaml"))
        self.assertTrue(C.ARTIFACT_NAME_RE.match("report.jsonl"))


class TheTestDirectoriesAreExcludedOnPurpose(unittest.TestCase):
    def test_a_test_file_reading_its_own_fixture_is_not_a_guard(self):
        scene = _Scene(SCENE_ADR475,
                       extra_files=(("spa_core/tests/test_x.py", SCENE_ADR475),))
        self.addCleanup(scene.close)
        doc = scene.measure()
        self.assertNotIn("spa_core/tests/test_x.py",
                         {r["reader"] for r in doc["findings"]})
        self.assertEqual(doc["outcomes"][C.OUT_CONST_TRUSTED], 1, doc["outcomes"])


class TheInstrumentDoesNotJoinTheClassItMeasures(unittest.TestCase):
    """Прибор НЕ производит артефакта — и это не лень, а условие честности.

    Урок цикла #735: прибор, добавляющий себя в измеряемый класс, мерит уже не дерево.
    Артефакт этой переписи, читаемый шагом 0-офис, был бы git-tracked операндом
    «предыдущего прогона» у собственного читателя — то есть 575-й парой населения,
    появившейся от самого замера. Поэтому секция офиса зовёт `measure()` НАПРЯМУЮ, а
    ни одного примитива записи в модуле нет вовсе.
    """

    def setUp(self):
        self.source = pathlib.Path(C.__file__).read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)

    def test_the_module_contains_no_write_site_of_its_own(self):
        resolver = C._PathResolver(self.tree)
        writes, _ = C._sites(self.tree, resolver)
        self.assertEqual(dict(writes), {}, "прибор пишет артефакт — он вошёл в свой класс")

    def test_the_module_calls_no_delivery_primitive(self):
        called = {C._call_name(n) for n in ast.walk(self.tree) if isinstance(n, ast.Call)}
        self.assertEqual(called & set(C.COMMIT_CALL_NAMES), set(), sorted(called))

    def test_the_census_does_not_count_itself_as_a_pair(self):
        scene = _Scene(SCENE_ADR475,
                       extra_files=(("spa_core/monitoring/census.py", self.source),))
        self.addCleanup(scene.close)
        doc = scene.measure()
        readers = {
            row["reader"]
            for key in ("findings", "named_sample", "committed_sample", "excluded_sample")
            for row in doc.get(key, ())
        }
        self.assertNotIn("spa_core/monitoring/census.py", readers, sorted(readers))
        self.assertEqual(doc["outcomes"][C.OUT_CONST_TRUSTED], 1, doc["outcomes"])


# ──────────────────────────────────────────────────────────────────────────────
# Замер ЖИВОГО дерева: храповик класса
# ──────────────────────────────────────────────────────────────────────────────

# ──────────────────────────────────────────────────────────────────────────────
# Перекрёстная ось: читатель ЧУЖОГО прошлого прогона (заказ G104 п. 1, ADR-623)
# ──────────────────────────────────────────────────────────────────────────────

#: ПРОИЗВОДИТЕЛЬ: пишет артефакт и НЕ читает его. В главную ось не попадает (там
#: население — `writes & reads`), в перекрёстную тоже не попадает по этому артефакту —
#: он нужен сцене, чтобы у файла БЫЛ чужой писатель в дереве.
SCENE_PRODUCER = '''
import json, pathlib
OUT = pathlib.Path("data") / "producer_out.json"

def produce(value):
    OUT.write_text(json.dumps({"value": value}))
'''

#: ЧИТАТЕЛЬ ЧУЖОГО вывода, дословная форма находки: читает `producer_out.json`, НЕ
#: пишет его, сравнивает прочитанное с ЖИВЫМ наблюдением этого прогона (сеть), возраст
#: чужого артефакта не спрашивает.
SCENE_CROSS_READER = '''
import json, pathlib, urllib.request
PRIOR = pathlib.Path("data") / "producer_out.json"

def decide(prior, live):
    return prior.get("value") and live.get("value")

def run():
    prior = json.loads(PRIOR.read_text())
    live = json.loads(urllib.request.urlopen("https://example.invalid").read())
    return decide(prior, live)
'''

#: Тот же читатель, но СПРАШИВАЮЩИЙ возраст чужого артефакта — фоссил назван.
SCENE_CROSS_READER_ASKS_AGE = '''
import json, pathlib, datetime, urllib.request
PRIOR = pathlib.Path("data") / "producer_out.json"

def decide(prior, live, age_h):
    return prior.get("value") and live.get("value") and age_h < 24

def run():
    prior = json.loads(PRIOR.read_text())
    stamped = datetime.datetime.fromisoformat(prior.get("generated_at"))
    age_h = (datetime.datetime.now(datetime.timezone.utc) - stamped).total_seconds() / 3600
    live = json.loads(urllib.request.urlopen("https://example.invalid").read())
    return decide(prior, live, age_h)
'''

#: Тот же читатель, сравнивающий чужое только с ЛИТЕРАЛАМИ — валидатор документа.
#: Это ровно та нога, которой на живом дереве 07.10 добыт весь ноль находки (19 из 19).
SCENE_CROSS_READER_LITERALS_ONLY = '''
import json, pathlib
PRIOR = pathlib.Path("data") / "producer_out.json"

def run():
    prior = json.loads(PRIOR.read_text())
    return prior.get("value", 0) > 7
'''

#: Тот же читатель, СВЕРЯЮЩИЙ чужое с пересборкой в этом же прогоне.
#:
#: Первая редакция сцены пересборку изображала, а не несла: `rebuild()` в ней ничего не
#: ПИСАЛА, а нога паритета по построению спрашивает происхождение от собственного
#: ПИСАТЕЛЯ (`_write_data_names` → локальная функция), иначе за пересборку сошёл бы
#: `json.dumps` у любого писателя и идиома проглотила бы настоящую находку. Сцена без
#: записи поэтому честно падала в соседний исход — это была дыра СЦЕНЫ, не прибора
#: (тот же класс, что 9 из 9 выживших мутантов циклов #752–#754). Живое дерево форму
#: подтверждает: `spa_core/backtesting/tier1/evaluator.py` на `mass_tournament_results.json`
#: лежит ровно в этом исходе.
SCENE_CROSS_READER_PARITY = '''
import json, pathlib
PRIOR = pathlib.Path("data") / "producer_out.json"
OWN = pathlib.Path("data") / "guard_report.json"

def rebuild():
    return {"value": 3}

def run():
    prior = json.loads(PRIOR.read_text())
    fresh = rebuild()
    OWN.write_text(json.dumps(fresh))
    return prior == fresh
'''

#: Самокарусельный модуль: пишет И читает один путь. Предмет ГЛАВНОЙ оси; в
#: перекрёстное население он не имеет права попасть ни одной парой.
SCENE_SELF_CAROUSEL_ONLY = '''
import json, pathlib, urllib.request
OWN = pathlib.Path("data") / "producer_out.json"

def run():
    prior = json.loads(OWN.read_text()) if OWN.exists() else {}
    live = json.loads(urllib.request.urlopen("https://example.invalid").read())
    out = {"ok": bool(prior.get("value")) and bool(live.get("value"))}
    OWN.write_text(json.dumps(out))
    return out
'''

WORKFLOW_CALLS_READER_AND_PRODUCER = """
name: guard
on: [push]
jobs:
  run:
    permissions:
      contents: read
    steps:
      - run: python3 spa_core/producer.py
      - run: python3 scripts/guard.py
"""

WORKFLOW_COMMITS_CROSS_ARTIFACT = """
name: guard
on: [push]
jobs:
  run:
    permissions:
      contents: write
    steps:
      - run: python3 scripts/guard.py
      - run: git commit -am "carry data/producer_out.json forward"
"""

#: Пути, которые сцена перекрёстной оси кладёт под git. `producer_out.json` обязан быть
#: ОТСЛЕЖИВАЕМЫМ — иначе пара уходит в `cross_absent_in_ci`, то есть в другой исход.
CROSS_TRACK = ("data/producer_out.json",)


def _cross_scene(reader_source=SCENE_CROSS_READER, *,
                 workflow=WORKFLOW_CALLS_READER,
                 producer_source=SCENE_PRODUCER,
                 track=CROSS_TRACK):
    """Сцена перекрёстной оси: ЧУЖОЙ производитель + читатель, который не пишет.

    Производитель лежит отдельным файлом намеренно: «чужой» здесь есть свойство ДЕРЕВА
    (путь пишет другой модуль), а не имени переменной, и сцена обязана нести это
    свойство, а не изображать его.
    """
    extra = () if producer_source is None else (("spa_core/producer.py", producer_source),)
    return _Scene(reader_source, workflow=workflow, track=track, extra_files=extra)


def _cross_verdict(doc, reader="scripts/guard.py", artifact="producer_out.json"):
    """Исход, в который лёг ИМЕННО этот перекрёстный читатель.

    Читается по ОБРАЗЦАМ, а не по счётчику: счётчики совпадают у разных клеток, и сцена
    обязана нести РАЗЛИЧИМОСТЬ, а не только исход (урок #786). Клетки без образца
    (`not_in_ci`, `absent_in_ci`, `no_producer`, `committed_back`) различимы тем, что у
    них ненулевой счётчик ровно один — это проверяется отдельным утверждением в тестах.
    """
    cross = doc["cross_axis"]
    for row in cross["findings"]:
        if row["reader"] == reader and artifact in row["artifact"]:
            return C.CROSS_CONST_TRUSTED
    for row in cross["named_sample"]:
        if row["reader"] == reader and artifact in row["artifact"]:
            return C.CROSS_CONST_NAMED
    for row in cross["excluded_sample"]:
        if row["reader"] == reader and artifact in row["artifact"]:
            return row["why"]
    nonzero = [k for k, v in cross["outcomes"].items() if v]
    return nonzero[0] if len(nonzero) == 1 else f"ambiguous:{nonzero}"


class TheCrossAxisFindsTheReaderOfSomeoneElsesPriorRun(unittest.TestCase):
    """Положительный контроль находки заказа G104 п. 1.

    Форма — та же, что у аварии ADR-475, но писатель ЧУЖОЙ. Главная ось такую пару не
    видит ВОВСЕ (её население — `writes & reads`), и ровно это ADR-524 назвал вслух
    нижней границей.
    """

    @classmethod
    def setUpClass(cls):
        cls.scene = _cross_scene()
        cls.doc = cls.scene.measure()

    @classmethod
    def tearDownClass(cls):
        cls.scene.close()

    def test_the_cross_reader_of_a_committed_artifact_is_a_finding(self):
        self.assertEqual(_cross_verdict(self.doc), C.CROSS_CONST_TRUSTED)

    def test_the_main_axis_does_not_see_this_pair_at_all(self):
        """Та самая односторонность: главная ось на этой сцене находок не имеет."""
        self.assertEqual(self.doc["outcomes"][C.OUT_CONST_TRUSTED], 0)
        self.assertEqual(self.doc["findings"], [])

    def test_the_finding_names_reader_artifact_and_the_foreign_producers(self):
        row = self.doc["cross_axis"]["findings"][0]
        self.assertEqual(row["reader"], "scripts/guard.py")
        self.assertEqual(row["artifact"], "data/producer_out.json")
        self.assertEqual(row["producers"], ["spa_core/producer.py"])
        self.assertTrue(row["read_lines"])

    def test_a_cross_finding_makes_the_exit_code_one(self):
        self.assertEqual(C.verdict(self.doc), C.RC_FINDING)

    def test_the_report_prints_the_cross_finding_in_full(self):
        text = C.format_report(self.doc)
        self.assertIn("ЧУЖАЯ КОНСТАНТА", text)
        self.assertIn("data/producer_out.json", text)
        self.assertIn("scripts/guard.py", text)

    def test_the_finding_is_counted_under_the_substitution_radius(self):
        """`data/` — радиус дословной команды аварии #361, и он доложен числом."""
        self.assertEqual(self.doc["cross_axis"]["under_substitution_radius"], 1)


class EachCrossLegTornByNameChangesTheVerdict(unittest.TestCase):
    """Контроль в ОБРАТНУЮ сторону: рвать надо каждое звено ПОИМЕННО.

    Проба, зелёная на целом контуре и не краснеющая ни от одного порванного звена,
    измеряет не контур, а своё присутствие (ADR-333, `.claude/rules/acceptance.md` п. 3).
    """

    def _measure(self, **kw):
        scene = _cross_scene(**kw)
        try:
            return scene.measure()
        finally:
            scene.close()

    def test_a_reader_unreachable_from_ci_is_not_a_finding(self):
        doc = self._measure(workflow=WORKFLOW_SILENT)
        self.assertEqual(_cross_verdict(doc), C.CROSS_NOT_IN_CI)
        self.assertEqual(doc["cross_axis"]["outcomes"][C.CROSS_CONST_TRUSTED], 0)

    def test_an_untracked_artifact_is_absent_in_ci_not_a_finding(self):
        doc = self._measure(track=())
        self.assertEqual(_cross_verdict(doc), C.CROSS_ABSENT_IN_CI)
        self.assertEqual(doc["cross_axis"]["outcomes"][C.CROSS_CONST_TRUSTED], 0)

    def test_an_artifact_nobody_in_the_tree_writes_is_a_curated_constant(self):
        """Снять производителя — и это уже не «чужой прогон», а предмет ТРЕТЬЕЙ оси."""
        doc = self._measure(producer_source=None)
        self.assertEqual(_cross_verdict(doc), C.CROSS_NO_PRODUCER)
        self.assertEqual(doc["cross_axis"]["outcomes"][C.CROSS_CONST_TRUSTED], 0)

    def test_an_automation_that_commits_the_artifact_back_is_an_observation(self):
        doc = self._measure(workflow=WORKFLOW_COMMITS_CROSS_ARTIFACT)
        self.assertEqual(_cross_verdict(doc), C.CROSS_COMMITTED_BACK)
        self.assertEqual(doc["cross_axis"]["outcomes"][C.CROSS_CONST_TRUSTED], 0)

    def test_a_producer_called_by_the_same_job_leaves_the_finding(self):
        """Исход назван по ИЗМЕРЕННОМУ («достижим»), а не по следствию («свеж»)."""
        doc = self._measure(workflow=WORKFLOW_CALLS_READER_AND_PRODUCER)
        self.assertEqual(_cross_verdict(doc), C.CROSS_PRODUCER_IN_CI)
        row = [r for r in doc["cross_axis"]["excluded_sample"]
               if r["why"] == C.CROSS_PRODUCER_IN_CI][0]
        self.assertEqual(row["producers_in_ci"], ["spa_core/producer.py"])

    def test_a_reader_that_asks_the_foreign_age_is_named_not_a_finding(self):
        doc = self._measure(reader_source=SCENE_CROSS_READER_ASKS_AGE)
        self.assertEqual(_cross_verdict(doc), C.CROSS_CONST_NAMED)
        self.assertEqual(doc["cross_axis"]["outcomes"][C.CROSS_CONST_TRUSTED], 0)

    def test_named_is_not_called_safe(self):
        """Прибор видит ПРИЗНАК вопроса, а не верность порога — и зовётся `named`."""
        self.assertIn("named", C.CROSS_CONST_NAMED)
        self.assertNotIn("safe", C.CROSS_CONST_NAMED)

    def test_a_reader_comparing_only_with_literals_is_excluded_with_a_reason(self):
        doc = self._measure(reader_source=SCENE_CROSS_READER_LITERALS_ONLY)
        self.assertEqual(_cross_verdict(doc), C.CROSS_NO_DECISION)
        self.assertEqual(doc["cross_axis"]["outcomes"][C.CROSS_CONST_TRUSTED], 0)

    def test_a_reader_checking_parity_with_a_rebuild_is_excluded_with_a_reason(self):
        doc = self._measure(reader_source=SCENE_CROSS_READER_PARITY)
        self.assertEqual(_cross_verdict(doc), C.CROSS_PARITY)
        self.assertEqual(doc["cross_axis"]["outcomes"][C.CROSS_CONST_TRUSTED], 0)


class TheTwoPairAxesDoNotOverlap(unittest.TestCase):
    """`reads - writes` против `writes & reads`: общего элемента нет по построению.

    Утверждение не декоративное: если бы перекрёстная ось брала просто «все чтения»,
    каждая пара главной оси оказалась бы посчитана дважды, и сумма одной из осей
    перестала бы равняться её населению МОЛЧА — отказ формы ловит только расхождение
    внутри оси, а не двойной счёт между осями.
    """

    def test_a_self_carousel_module_never_enters_the_cross_population(self):
        scene = _Scene(SCENE_SELF_CAROUSEL_ONLY, track=CROSS_TRACK)
        try:
            doc = scene.measure()
        finally:
            scene.close()
        cross_readers = {
            row["reader"]
            for key in ("findings", "named_sample", "excluded_sample")
            for row in doc["cross_axis"][key]
        }
        self.assertNotIn("scripts/guard.py", cross_readers)
        self.assertEqual(doc["cross_axis"]["outcomes"][C.CROSS_CONST_TRUSTED], 0)
        # ...и при этом ГЛАВНАЯ ось эту пару видит: иначе сцена доказывала бы лишь
        # собственную пустоту, а не разделение осей.
        self.assertEqual(_verdict_of(doc, artifact="producer_out.json"),
                         C.OUT_CONST_TRUSTED)

    def test_the_cross_population_counts_the_reader_only_once_per_artifact(self):
        scene = _cross_scene()
        try:
            doc = scene.measure()
        finally:
            scene.close()
        cross = doc["cross_axis"]
        self.assertEqual(cross["outcomes"][C.CROSS_CONST_TRUSTED], 1)
        self.assertEqual(sum(cross["outcomes"].values()), cross["population"])


class TheCrossOutcomeFormIsClosed(unittest.TestCase):
    """Сумма равна населению, каждый ноль ОБЪЯВЛЕН (инв. #17)."""

    @classmethod
    def setUpClass(cls):
        cls.scene = _cross_scene()
        cls.doc = cls.scene.measure()

    @classmethod
    def tearDownClass(cls):
        cls.scene.close()

    def test_the_sum_of_cross_outcomes_equals_the_cross_population(self):
        cross = self.doc["cross_axis"]
        self.assertEqual(sum(cross["outcomes"].values()), cross["population"])
        self.assertEqual(cross["notes"], [], cross["notes"])

    def test_every_declared_cross_outcome_is_present_even_at_zero(self):
        cross = self.doc["cross_axis"]
        for name in C.CROSS_OUTCOMES:
            self.assertIn(name, cross["outcomes"], name)

    def test_the_report_prints_every_cross_outcome_name_including_the_zeros(self):
        text = C.format_report(self.doc)
        for name in C.CROSS_OUTCOMES:
            self.assertIn(name, text, name)

    def test_the_report_says_HOW_the_zero_was_obtained(self):
        """Ноль без названной причины читался бы как «класса нет»."""
        self.assertIn("ЧЕМ ДОБЫТ НОЛЬ", C.format_report(self.doc))

    def test_the_order_number_of_the_axis_is_declared(self):
        self.assertEqual(self.doc["cross_axis"]["order"], "G104.1")


class TheCrossAxisAbsentObservationIsItsOwnOutcome(unittest.TestCase):
    """«Не измерено» перекрёстной оси — ГРОМКО, с названной причиной, и никогда не ноль."""

    def test_an_unparsable_module_is_counted_cross_unmeasured_with_its_reason(self):
        scene = _cross_scene()
        try:
            (scene.root / "spa_core" / "broken.py").write_text(
                "def (:\n", encoding="utf-8")
            doc = scene.measure()
        finally:
            scene.close()
        cross = doc["cross_axis"]
        self.assertEqual(cross["outcomes"][C.CROSS_UNMEASURED], 1)
        self.assertTrue(
            any(r.startswith("unparsed:") for r in cross["unmeasured_reasons"]),
            cross["unmeasured_reasons"])
        self.assertEqual(sum(cross["outcomes"].values()), cross["population"])
        self.assertEqual(C.verdict(doc), C.RC_UNMEASURED)

    def test_two_tracked_paths_with_one_name_are_cross_unmeasured_and_loud(self):
        """Имя не есть адрес (ADR-465): выбрать один из двух значило бы догадаться."""
        scene = _cross_scene(
            track=("data/producer_out.json", "landing/src/data/producer_out.json"))
        try:
            doc = scene.measure()
        finally:
            scene.close()
        cross = doc["cross_axis"]
        self.assertEqual(cross["outcomes"][C.CROSS_UNMEASURED], 1)
        self.assertTrue(
            any(r.startswith("artifact_name_ambiguous_in_repo:")
                for r in cross["unmeasured_reasons"]),
            cross["unmeasured_reasons"])
        self.assertEqual(cross["outcomes"][C.CROSS_CONST_TRUSTED], 0)
        self.assertEqual(C.verdict(doc), C.RC_UNMEASURED)

    def test_a_document_without_the_cross_axis_is_unmeasured_not_clean(self):
        """Отсутствие оси в документе — третий исход, а не пустой раздел."""
        scene = _cross_scene(workflow=WORKFLOW_SILENT)
        try:
            doc = scene.measure()
        finally:
            scene.close()
        doc.pop("cross_axis")
        self.assertEqual(C.verdict(doc), C.RC_UNMEASURED)
        self.assertIn("НЕ ИЗМЕРЕНО", C.format_report(doc))
        self.assertIn("G104 п. 1", C.format_report(doc))

    def test_a_cross_form_refusal_makes_the_verdict_unmeasured_not_clean(self):
        scene = _cross_scene(workflow=WORKFLOW_SILENT)
        try:
            doc = scene.measure()
        finally:
            scene.close()
        doc["cross_axis"]["notes"] = ["сумма перекрёстных исходов 1 != 2 — ОТКАЗ формы"]
        self.assertEqual(C.verdict(doc), C.RC_UNMEASURED)
        self.assertIn("[ОТКАЗ]", C.format_report(doc))


def _cross_counts(doc):
    """Ненулевые перекрёстные счётчики. Читается СЧЁТЧИК, а не образец строки.

    Отдельный помощник нужен потому, что ``_cross_verdict`` при наличии образца
    возвращает `row["why"]` и до счётчиков не доходит ВОВСЕ. Прицельная мутация это и
    показала: подмена ИМЕНИ ключа в `counts[...] += 1` переживала батарею у трёх ног
    (`producer_reachable_from_ci`, `parity`, `no_decision`) — сумма исходов не меняется
    (один счётчик вверх, другой вниз), а образец строки к счётчику не привязан. Это
    дословно урок #786: равные счёты двух исходов делают подмену имени невидимой.
    """
    return {k: v for k, v in doc["cross_axis"]["outcomes"].items() if v}


class TheCrossCountersAreReadByNameNotByCoincidence(unittest.TestCase):
    """У КАЖДОЙ ноги проверяется СЧЁТЧИК, а не только образец строки.

    Население каждой сцены — ровно одна значащая пара, поэтому «ненулевой счётчик ровно
    один, и он именно этот» есть полная проверка привязки имени к ноге.
    """

    def _counts(self, **kw):
        scene = _cross_scene(**kw)
        try:
            return _cross_counts(scene.measure())
        finally:
            scene.close()

    def test_the_finding_increments_the_finding_counter_and_no_other(self):
        self.assertEqual(self._counts(), {C.CROSS_CONST_TRUSTED: 1})

    def test_a_reader_unreachable_from_ci_increments_its_own_counter(self):
        self.assertEqual(self._counts(workflow=WORKFLOW_SILENT),
                         {C.CROSS_NOT_IN_CI: 1})

    def test_an_untracked_artifact_increments_its_own_counter(self):
        self.assertEqual(self._counts(track=()), {C.CROSS_ABSENT_IN_CI: 1})

    def test_a_missing_producer_increments_its_own_counter(self):
        self.assertEqual(self._counts(producer_source=None),
                         {C.CROSS_NO_PRODUCER: 1})

    def test_an_artifact_committed_back_increments_its_own_counter(self):
        self.assertEqual(self._counts(workflow=WORKFLOW_COMMITS_CROSS_ARTIFACT),
                         {C.CROSS_COMMITTED_BACK: 1})

    def test_a_producer_in_the_same_job_increments_its_own_counter(self):
        self.assertEqual(self._counts(workflow=WORKFLOW_CALLS_READER_AND_PRODUCER),
                         {C.CROSS_PRODUCER_IN_CI: 1})

    def test_asking_the_age_increments_the_named_counter(self):
        self.assertEqual(self._counts(reader_source=SCENE_CROSS_READER_ASKS_AGE),
                         {C.CROSS_CONST_NAMED: 1})

    def test_comparing_only_with_literals_increments_the_no_decision_counter(self):
        self.assertEqual(self._counts(reader_source=SCENE_CROSS_READER_LITERALS_ONLY),
                         {C.CROSS_NO_DECISION: 1})

    def test_parity_with_a_rebuild_increments_the_parity_counter(self):
        self.assertEqual(self._counts(reader_source=SCENE_CROSS_READER_PARITY),
                         {C.CROSS_PARITY: 1})

    def test_the_reader_count_is_the_difference_not_the_union(self):
        """`reads - writes`, а не `reads | writes`: производитель читателем НЕ является.

        Прицельная мутация переживала батарею, потому что живое дерево проверялось лишь
        порядком величины (`> 50`). На сцене производитель ровно один, поэтому союз дал
        бы ДВА читателя вместо одного — различимо точным числом, и только им.
        """
        scene = _cross_scene()
        try:
            cross = scene.measure()["cross_axis"]
        finally:
            scene.close()
        self.assertEqual(cross["readers"], 1)
        self.assertEqual(cross["population"], 1)


class TheReportLineThatSaysHowTheZeroWasObtainedCarriesItsNUMBERS(unittest.TestCase):
    """Строка «ЧЕМ ДОБЫТ НОЛЬ» обязана нести ЧИСЛА, а не только заголовок.

    Прицельная мутация переживала батарею пять раз: тесты требовали лишь ПРИСУТСТВИЯ
    подстроки «ЧЕМ ДОБЫТ НОЛЬ», поэтому подмена любого имени исхода внутри самой строки
    была невидима. А строка эта — главное утверждение решения: без её чисел ноль находки
    снова читается как «класса нет».

    Проверяется на ЧЕТЫРЁХ сценах намеренно: на сцене находки `parity` и `no_decision`
    оба нули, и подмена одного другим там неразличима ПО ПОСТРОЕНИЮ (урок #786). Каждая
    сцена названа вместе с тем, что именно она и только она различает.
    """

    def _line(self, **kw):
        scene = _cross_scene(**kw)
        try:
            text = C.format_report(scene.measure())
        finally:
            scene.close()
        got = [l for l in text.splitlines() if "ЧЕМ ДОБЫТ НОЛЬ" in l]
        self.assertEqual(len(got), 1, text)
        return got[0]

    def test_on_the_finding_scene_one_pair_reached_and_none_were_excluded(self):
        """Различает `constant_trusted` в сумме: подмена дала бы «дошло 0»."""
        line = self._line()
        self.assertIn("дошло 1 пар(ы)", line)
        self.assertIn("и 0 из них исключены", line)

    def test_on_the_named_scene_one_pair_reached_and_none_were_excluded(self):
        """Различает `constant_named` в сумме — на сцене находки он ноль."""
        line = self._line(reader_source=SCENE_CROSS_READER_ASKS_AGE)
        self.assertIn("дошло 1 пар(ы)", line)
        self.assertIn("и 0 из них исключены", line)

    def test_on_the_literals_scene_the_excluded_number_is_the_one_excluded(self):
        """Различает ОБА вхождения `no_decision`: и в сумме, и в «из них»."""
        line = self._line(reader_source=SCENE_CROSS_READER_LITERALS_ONLY)
        self.assertIn("дошло 1 пар(ы)", line)
        self.assertIn("и 1 из них исключены", line)

    def test_on_the_parity_scene_the_pair_reached_but_was_not_the_excluded_one(self):
        """Различает `parity` в сумме — на сцене литералов он ноль."""
        line = self._line(reader_source=SCENE_CROSS_READER_PARITY)
        self.assertIn("дошло 1 пар(ы)", line)
        self.assertIn("и 0 из них исключены", line)


class TheExcludedSampleIsCappedAndTheRemainderIsNamedByNUMBER(unittest.TestCase):
    """Остаток перечня назван ЧИСЛОМ, а не многоточием — и это ветвь, а не украшение.

    Ветвь `rest > 0` на живом дереве и на всех сценах недостижима (исключённых 19 и 1
    против предела 20), поэтому прицельная мутация переживала её трижды. Форматтер
    принимает ДОКУМЕНТ, значит документ и есть вход этой проверки: население
    синтезируется, а не выдумывается поведение прибора.
    """

    def _doc_with(self, n_excluded):
        scene = _cross_scene(workflow=WORKFLOW_SILENT)
        try:
            doc = scene.measure()
        finally:
            scene.close()
        doc["cross_axis"]["excluded_sample"] = [
            {"reader": f"scripts/r{i}.py", "artifact": f"data/a{i}.json",
             "read_lines": [i], "why": C.CROSS_NO_DECISION}
            for i in range(n_excluded)
        ]
        return doc

    def test_a_remainder_beyond_the_cap_is_reported_as_a_number(self):
        text = C.format_report(self._doc_with(C.CROSS_SAMPLE + 5))
        self.assertIn(f"ещё {5} исключённ", text)

    def test_exactly_the_cap_is_printed_without_a_remainder_line(self):
        """Контроль в ОБРАТНУЮ сторону: без него `rest > 0` → `rest <= 0` выжил бы."""
        text = C.format_report(self._doc_with(C.CROSS_SAMPLE))
        self.assertNotIn("исключённ(ая/ых) пар(а/ы) (полный перечень", text)

    def test_the_printed_sample_never_exceeds_the_cap(self):
        text = C.format_report(self._doc_with(C.CROSS_SAMPLE + 5))
        printed = [l for l in text.splitlines() if "[ИСКЛЮЧЁН с причиной]" in l]
        self.assertEqual(len(printed), C.CROSS_SAMPLE)


class TheNEIGHBOURINGAxesRefusalLegsAlsoRaiseTheCode(unittest.TestCase):
    """Четыре ноги отказа у СОСЕДНИХ осей (ADR-621/622) — контролей у них не было.

    Найдено прицельной мутацией ЭТОГО цикла: `return RC_UNMEASURED` у «хостовой оси
    нет», «хостовая ось отказала», «артефактной оси нет», «артефактная ось отказала»
    переживал батарею — ни одна сцена не приводила соседние оси к отказу. Тесты
    ДОБАВЛЕНЫ (инв. #16 запрещает ослаблять, а не усиливать): форма у этих ног ровно та
    же, что у двух моих новых, и те мутантом убиты — значит молчали именно контроли.
    """

    def _doc(self):
        scene = _cross_scene(workflow=WORKFLOW_SILENT)
        try:
            return scene.measure()
        finally:
            scene.close()

    def test_a_document_without_the_host_axis_is_unmeasured_not_clean(self):
        doc = self._doc()
        doc.pop("host_axis")
        self.assertEqual(C.verdict(doc), C.RC_UNMEASURED)

    def test_a_host_axis_form_refusal_is_unmeasured_not_clean(self):
        doc = self._doc()
        doc["host_axis"]["notes"] = ["сумма хостовых исходов 1 != 2 — ОТКАЗ формы"]
        self.assertEqual(C.verdict(doc), C.RC_UNMEASURED)

    def test_a_document_without_the_artifact_axis_is_unmeasured_not_clean(self):
        doc = self._doc()
        doc.pop("artifact_axis")
        self.assertEqual(C.verdict(doc), C.RC_UNMEASURED)

    def test_an_artifact_axis_form_refusal_is_unmeasured_not_clean(self):
        doc = self._doc()
        doc["artifact_axis"]["notes"] = ["сумма артефактных исходов 1 != 2 — ОТКАЗ формы"]
        self.assertEqual(C.verdict(doc), C.RC_UNMEASURED)

    def test_a_host_axis_unmeasured_count_is_unmeasured_not_clean(self):
        doc = self._doc()
        doc["host_axis"]["outcomes"][C.HOST_UNMEASURED] = 1
        self.assertEqual(C.verdict(doc), C.RC_UNMEASURED)


class TheCrossAxisOnTheLiveTree(unittest.TestCase):
    """Храповик заказа G104 п. 1: новый читатель ЧУЖОЙ константы = КРАСНЫЙ сразу.

    База — НОЛЬ (замер 07.10, дерево `bf7a40ba8`), и списка исключений у проверки нет
    намеренно: население находки пусто, а список исключений на пустом населении был бы
    ровно тем дефектом, против которого проверка написана (инв. #16).
    """

    @classmethod
    def setUpClass(cls):
        cls.root = pathlib.Path(__file__).resolve().parents[2]
        cls.doc = C.measure(cls.root)

    def test_the_cross_axis_was_measured_at_all(self):
        self.assertIn("cross_axis", self.doc)
        self.assertTrue(self.doc["measured"])

    def test_no_guard_silently_trusts_a_FOREIGN_committed_prior_run(self):
        cross = self.doc["cross_axis"]
        self.assertEqual(
            cross["outcomes"][C.CROSS_CONST_TRUSTED], 0,
            "в дереве появился сторож, читающий прошлый вывод ЧУЖОГО производителя из "
            f"git-tracked артефакта и не спрашивающий его возраста: {cross['findings']}")

    def test_the_cross_form_holds_on_the_live_tree_too(self):
        cross = self.doc["cross_axis"]
        self.assertEqual(sum(cross["outcomes"].values()), cross["population"])
        self.assertEqual(cross["notes"], [], cross["notes"])

    def test_the_cross_population_is_not_empty(self):
        """Пустое население ответило бы на свой вопрос ноль, ничего не измерив.

        Утверждается ПОРЯДОК величины, а не точное число: точное пришпиливание краснело
        бы от любой чужой правки дерева, то есть мерило бы календарь, а не класс.
        """
        cross = self.doc["cross_axis"]
        self.assertGreater(cross["population"], 100, cross["population"])
        self.assertGreater(cross["readers"], 50, cross["readers"])

    def test_the_known_excluded_members_are_still_named_in_not_reported(self):
        """Цена ноля названа РУКАМИ, и пропасть она молча не имеет права.

        Сравнение чужого операнда с ПОРОГОМ-литералом в находку не идёт — этим и добыт
        весь ноль. Если строка исчезнет, ноль снова станет выглядеть чистым ответом.
        """
        text = " ".join(self.doc["not_reported"])
        self.assertIn("ПОРОГОМ-ЛИТЕРАЛОМ", text)
        self.assertIn("readiness_audit.py", text)

    def test_the_old_one_sidedness_note_is_gone_because_it_is_now_measured(self):
        """Строка «не измерен вовсе» обязана была уйти: вопрос ЗАКРЫТ этой осью."""
        text = " ".join(self.doc["not_reported"])
        self.assertNotIn("не измерен вовсе, это следующий вопрос", text)


class TheLiveTreeHasNoSilentlyTrustedConstant(unittest.TestCase):
    """Храповик заказа G86 п. 3: новый сторож этого класса = КРАСНЫЙ тест сразу.

    База — НОЛЬ, и ниже нуля она не опускается. Дописывать в базу нечего по
    построению: исключения у этой проверки нет намеренно (порядок `frozen_date_baseline`
    наоборот — там население велико; здесь оно ноль, и список исключений был бы ровно
    тем дефектом, против которого проверка написана).

    «Не измерено» здесь обязано падать ГРОМКО, а не скипать: скип неотличим от
    «прошло», и в дифференциальном замере такой тест не краснеет и не проходит — он
    ИСЧЕЗАЕТ (урок цикла #465).
    """

    @classmethod
    def setUpClass(cls):
        cls.root = pathlib.Path(__file__).resolve().parents[2]
        cls.doc = C.measure(cls.root)

    def test_the_measurement_of_the_live_tree_succeeded(self):
        self.assertTrue(
            self.doc["measured"],
            f"НЕ ИЗМЕРЕНО: {self.doc.get('why_unmeasured')} — это не «чисто»")

    def test_no_guard_silently_trusts_a_committed_prior_run(self):
        self.assertEqual(
            self.doc["outcomes"][C.OUT_CONST_TRUSTED], 0,
            "новый сторож читает «прошлый прогон» из git-tracked артефакта, не "
            f"спрашивая его возраста: {self.doc['findings']}")

    def test_the_form_holds_on_the_live_tree_too(self):
        self.assertEqual(sum(self.doc["outcomes"].values()), self.doc["population"])
        self.assertEqual(self.doc["notes"], [], self.doc["notes"])

    def test_the_adr475_reader_is_still_inside_the_population(self):
        """Положительный контроль ЖИВОГО дерева: авария 25.09 из класса не исчезла.

        Утверждается принадлежность к населению, а не вердикт: вердикт — замер дня,
        и пришпиливать его значило бы краснеть от чужой правки кустодиана.
        """
        seen = {
            row["reader"]
            for key in ("findings", "named_sample", "committed_sample", "excluded_sample")
            for row in self.doc.get(key, ())
        }
        self.assertIn("scripts/site_freshness_monitor.py", seen, sorted(seen))

    def test_the_live_verdict_is_a_measured_one(self):
        self.assertIn(C.verdict(self.doc), (C.RC_MEASURED, C.RC_FINDING))

    def test_the_not_reported_clause_renders_its_number_and_does_not_print_a_literal(self):
        """Собственный отчёт прибора не вправе печатать число КОНСТАНТОЙ.

        Доставка #796 нашла в `not_reported` литерал `1009` — замер дерева
        `bf7a40ba8`, пока на `02bd142f8` та же нога давала уже 1010. Это дословно
        предмет всего ряда ADR-475…623: напечатанное число перестаёт быть правдой
        молча, и сказать об этом некому. Контроль в ОБЕ стороны: оговорка обязана
        нести РОВНО измеренное число оси, и ни одного числа мимо него.
        """
        measured = self.doc["cross_axis"]["outcomes"][C.CROSS_NOT_IN_CI]
        clause = [n for n in self.doc["not_reported"] if "хостового вопроса G104" in n]
        self.assertEqual(
            len(clause), 1,
            f"оговорка про хостовой вопрос перекрёстной оси не найдена: {self.doc['not_reported']}")
        numbers = {int(t) for t in re.findall(r"\d+", clause[0])}
        self.assertIn(
            measured, numbers,
            f"оговорка не несёт измеренного числа {measured}: {clause[0]!r}")
        # Обратная сторона: мимо измеренного в строке не стои́т НИ ОДНОГО числа,
        # кроме номеров заказа/пункта — иначе литерал вернулся бы рядом с замером.
        self.assertEqual(
            numbers - {measured, 104, 2}, set(),
            f"в оговорке есть число, которое ничего не мерит: {clause[0]!r}")


if __name__ == "__main__":
    unittest.main()
