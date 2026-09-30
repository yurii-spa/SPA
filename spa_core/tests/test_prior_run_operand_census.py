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


if __name__ == "__main__":
    unittest.main()
