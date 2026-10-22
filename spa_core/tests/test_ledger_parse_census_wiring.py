"""Проводка переписи повторного разбора хеш-лент: у числа есть ВЫЗОВ и ЧИТАТЕЛЬ.

Прибор `spa_core/monitoring/ledger_parse_census.py` (G777 п. 1, ADR-777, цикл #894)
был написан и не звался никем — храповик `test_unwired_guard_modules_ratchet` краснел
на чистой вершине (карточка `inbox-tri-pribora-napisany-i-ne-pozvany-hrap…`, тот же
класс). Подключение — ступень моста `findings_bridge` с ТАКТОМ 7 суток (замер 22.10:
полный замер на копии живого `data/` стоит 66.7 с), объявление артефакта в
конституции, поимённая ветка шага 0-офис.

Звенья и как каждое молчит, если порвано:

| звено | порванное |
|---|---|
| вызов `ledger_parse_census.run(...)` в `findings_bridge.main` | артефакт не обновляется никогда |
| `CENSUS_STAGE` / `CENSUS_PRODUCT` / `PRODUCES` моста | сторож B7 не знает, что агент это производит |
| `artifacts[]` + `produces[]` конституции | шаг 0-офис не открывает файл; SLO не назначен |
| ветка `_summarize_json` | файл открыт, запас роста в контекст не доезжает |
| гейт такта | минута замера каждые шесть часов либо «внутри такта» выдано за вердикт |

Часы инъектируются; живое `data/` не читается — стенды одноразовые. LLM_FORBIDDEN.
"""
from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import findings_bridge as fb
from spa_core.monitoring import ledger_parse_census as census

REPO = Path(__file__).resolve().parents[2]
OFFICE = REPO / "scripts" / "consume_office_reports.py"
ARTIFACT_REL = "data/ledger_parse_census.json"
STAGE_KEY = "ledger_parse_census"

# FROZEN-DATE-OK: injected-clock — NOW уезжает аргументом в `census.run(now=)`, и все
# отметки стендов вычисляются от него же (`NOW - timedelta(...)`).
NOW = dt.datetime(2026, 10, 22, 6, 0, tzinfo=dt.timezone.utc)


def _office():
    spec = importlib.util.spec_from_file_location("_office_lpc_under_test", OFFICE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _manifest() -> dict:
    return json.loads((REPO / "architecture" / "manifest.json").read_text(encoding="utf-8"))


def _called_in_main(src: str) -> set:
    """Имена модулей, у которых `main` моста зовёт `.run(...)` — по AST, не подстрокой."""
    tree = ast.parse(src)
    imported = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "spa_core.monitoring":
            for a in node.names:
                imported[a.asname or a.name] = a.name
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    seen = set()
    for node in ast.walk(main):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "run" and isinstance(node.func.value, ast.Name)):
            seen.add(imported.get(node.func.value.id, node.func.value.id))
    return seen


def _stand(stamp=None) -> Path:
    root = Path(tempfile.mkdtemp(prefix="spa_lpc_"))
    (root / "data").mkdir()
    if stamp is not None:
        (root / "data" / census.ARTIFACT).write_text(
            json.dumps({"generated_at": stamp.isoformat(), "status": "FINDING",
                        "marker": "ПРЕЖНИЙ"}), encoding="utf-8")
    return root


class TheBridgeCallsIt(unittest.TestCase):

    def test_the_bridge_actually_calls_run(self):
        src = Path(fb.__file__).read_text(encoding="utf-8")
        self.assertIn(STAGE_KEY, _called_in_main(src),
                      "ledger_parse_census.run(...) не зовётся в findings_bridge.main — "
                      "артефакт будет писать только рука")

    def test_positive_control_a_mention_is_not_a_call(self):
        mention = ("def main(argv=None):\n"
                   "    # ledger_parse_census тут только назван\n"
                   "    x = 'ledger_parse_census.run(root=1)'\n"
                   "    return x\n")
        self.assertNotIn(STAGE_KEY, _called_in_main(mention))

    def test_stage_composition_declares_it(self):
        self.assertIn(STAGE_KEY, fb.CENSUS_STAGE)
        self.assertEqual(fb.CENSUS_PRODUCT[STAGE_KEY]["artifact"], ARTIFACT_REL)
        self.assertTrue((REPO / fb.CENSUS_PRODUCT[STAGE_KEY]["module"]).exists())
        self.assertIn(ARTIFACT_REL, fb.PRODUCES)


class ArtifactHasTwoHomesInTheConstitution(unittest.TestCase):

    def test_artifacts_entry_names_consumer_and_producer(self):
        art = next((a for a in _manifest()["artifacts"] if a["path"] == ARTIFACT_REL), None)
        self.assertIsNotNone(art, "артефакта нет в artifacts[] — шаг 0-офис его не откроет")
        self.assertEqual(art["status"], "active")
        self.assertIn("orchestrator_protocol", art.get("consumers") or [])
        self.assertEqual(art.get("producer"), "com.spa.decision_loop")

    def test_passport_of_the_producer_declares_it_too(self):
        agent = next(a for a in _manifest()["agents"]
                     if a.get("label") == "com.spa.decision_loop")
        self.assertIn(ARTIFACT_REL, {p.get("artifact") for p in agent.get("produces") or []})

    def test_slo_is_looser_than_the_tact(self):
        art = next(a for a in _manifest()["artifacts"] if a["path"] == ARTIFACT_REL)
        self.assertGreater(art["slo_hours"], census.MEASUREMENT_TACT_DAYS * 24)


class TactIsDecidedByTheFile(unittest.TestCase):

    def setUp(self):
        self._real = census.measure
        self.calls: list = []

        def _spy(data_dir, *, tree_root=None, now=None, workloads=(), **_kw):
            self.calls.append((str(data_dir), str(tree_root)))
            return {"budget_s": 1.0, "min_growth_factor": 4.0, "data_dir": str(data_dir),
                    "rows": [], "population": {"code_files_undeclared": [],
                                               "code_files_missing": []},
                    "measured": [], "unmeasured": [], "workloads": {},
                    "call_sites": {}, "findings": []}

        census.measure = _spy

    def tearDown(self):
        census.measure = self._real

    def test_inside_the_tact_nothing_is_measured_and_nothing_is_written(self):
        root = _stand(NOW - dt.timedelta(days=1))
        before = (root / "data" / census.ARTIFACT).read_bytes()
        out = census.run(str(root), now=NOW)
        self.assertFalse(out["measured"])
        self.assertNotIn("doc", out, "«не мерили» выдано за вердикт")
        self.assertEqual(self.calls, [], "внутри такта перепись всё же позвали")
        self.assertEqual(before, (root / "data" / census.ARTIFACT).read_bytes())

    def test_outside_the_tact_it_measures_under_root_data(self):
        root = _stand(NOW - dt.timedelta(days=census.MEASUREMENT_TACT_DAYS + 1))
        out = census.run(str(root), now=NOW)
        self.assertTrue(out["measured"])
        self.assertEqual(self.calls, [(str(root / "data"), str(root))],
                         "ленты обязаны читаться из root/data, зовущие — из root")
        written = json.loads((root / "data" / census.ARTIFACT).read_text(encoding="utf-8"))
        self.assertEqual(written["status"], "OK")
        self.assertEqual(written["generated_at"], NOW.isoformat())
        self.assertNotIn("marker", written)

    def test_missing_artifact_measures_rather_than_skips(self):
        out = census.run(str(_stand(None)), now=NOW)
        self.assertTrue(out["measured"])
        self.assertEqual(len(self.calls), 1)


def _stand_doc() -> dict:
    """Настоящий замер на пустом стенде: ленты нет ни одной ⇒ каждый член — третий
    исход. Документ проходит JSON туда-обратно, как с диска (≈0.05 с)."""
    root = _stand(None)
    census.run(str(root), now=NOW, workloads=())
    return json.loads((root / "data" / census.ARTIFACT).read_text(encoding="utf-8"))


class OfficeReadsIt(unittest.TestCase):
    """Ветка шага 0-офис печатает ЧИСЛА прибора, а не одно слово статуса."""

    @classmethod
    def setUpClass(cls):
        cls.office = _office()

    def _lines(self):
        doc = _stand_doc()
        return self.office._summarize_json("data/ledger_parse_census.json", doc,
                                           now=NOW, root=str(REPO),
                                           artifact_root=str(REPO))

    def test_the_stand_is_the_third_outcome(self):
        doc = _stand_doc()
        self.assertEqual(doc["status"], "UNMEASURED",
                         "ни одной ленты нет, а статус не «НЕ ИЗМЕРЕНО»")

    def test_named_branch_prints_the_producer_report(self):
        text = "\n".join(self._lines())
        self.assertIn("повторный разбор хеш-лент", text)
        self.assertIn("[НЕ ИЗМЕРЕНО] research_factory", text)

    def test_the_read_is_not_hollow(self):
        self.assertFalse(any(l.startswith(self.office._HOLLOW_MARK) for l in self._lines()))

    def test_positive_control_the_numbers_come_from_the_producer_formatter(self):
        """Отчёт в выжимке — работа ветки, делегирующей ПРОИЗВОДИТЕЛЮ: заглуши
        `format_report` — и отчёт пропадает (мерка выше не про общий путь)."""
        real = census.format_report
        census.format_report = lambda doc: []
        try:
            text = "\n".join(self._lines())
        finally:
            census.format_report = real
        self.assertNotIn("[НЕ ИЗМЕРЕНО] research_factory", text)

    def test_no_schema_drift_against_the_live_producer(self):
        drift = self.office._schema_drift("ledger_parse_census.json", _stand_doc(),
                                          root=str(REPO))
        self.assertEqual(drift, [], f"ветка читает поля, которых производитель не пишет: {drift}")


if __name__ == "__main__":
    unittest.main()
