"""Положительные контроли переписи «чем задан порядок списков ответа» (ADR-800).

Каждый тест — ВОПРОС, на который прибор обязан отвечать ПО-РАЗНОМУ в двух сценах;
«зелёный на одной сцене» ничего не доказывает (`.claude/rules/acceptance.md`, п. 3).
Сцена строится из настоящих строк ленты и читается НАСТОЯЩЕЙ читающей моделью
(`research_factory.read`), а не её подобием: предмет прибора — ответ модели, и
заглушка отвечала бы на другой вопрос.

**Чем держится день нулевой.** Объявления природы в `DECLARED` сняты с замера, и
прибор, объявления которого взяты из его же вердикта, сам по себе не доказывает
ничего. Доказывают ДВА контроля ниже, воспроизводящие НАСТОЯЩИЕ носители ADR-799:
порядок первого появления в `registry.all_candidate_ids` (носитель №1) и
`decisions_today`, упорядоченный местом в ленте (носитель №2). На тех же сценах
непатченный код обязан быть ЧИСТ — это и есть противоположные вердикты.

# FROZEN-DATE-OK: injected-clock — якорь сцены ``ANCHOR`` — литерал, и от него же
# вычислены ВСЕ отметки строк сцены; момент замера приходит в прибор аргументом
# (``measure(..., now=…)``, ``measurement_due(..., now=…)``). «Сегодня» читающая
# модель берёт из САМОЙ СВЕЖЕЙ записи ленты, а не из стенных часов (ADR-564),
# поэтому вердикт не движется от календаря ни одной своей стороной.
"""

from __future__ import annotations

import datetime as dt
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import answer_list_order_census as alo
from spa_core.monitoring import ledger_window_dependency_census as lwd
from spa_core.research_factory import contract, read as rf_read, registry

ANCHOR = dt.datetime(2026, 10, 1, 12, 0, tzinfo=dt.timezone.utc)
NOW = ANCHOR + dt.timedelta(hours=2)

#: Личности кандидатов намеренно НЕ отсортированы в порядке появления: сцена обязана
#: различать «порядок первого появления» и «порядок множества», иначе носитель №1
#: под ней выглядел бы исправным.
CANDS = ("zz-cand", "mm-cand", "aa-cand", "qq-cand")
POSITION = "pos-0001"


def _iso(moment: dt.datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _snapshot(cid: str, at: dt.datetime) -> dict:
    return {"kind": "candidate_snapshot", "key": ["candidate_snapshot", cid, f"{cid}-fp"],
            "payload": {"candidate": {"candidate_id": cid, "domain": "D",
                                      "instrument": f"INS-{cid}", "admission_state": None},
                        "fingerprint": f"{cid}-fp"},
            "at": _iso(at)}


def _decision(cid: str, at: dt.datetime) -> dict:
    return {"kind": "admission_decision", "key": ["admission_decision", cid, f"{cid}-dec"],
            "payload": {"candidate_id": cid, "decision": "NEEDS_MORE_EVIDENCE",
                        "generated_at": _iso(at), "failed_gates": [f"GATE_{cid[:2].upper()}"],
                        "unknowns": [], "required_next_evidence": [f"need-{cid}"],
                        "rationale": [f"why-{cid}"], "evidence_ceiling": "L2",
                        "paper_mode": None},
            "at": _iso(at)}


def _paper_open(cid: str, at: dt.datetime) -> dict:
    return {"kind": "paper_open", "key": ["paper_open", cid, "adm-0001", "_single"],
            "payload": {"position_id": POSITION, "candidate_id": cid, "leg_id": "_single",
                        "status": "OPEN", "mark_state": "NEVER_MARKED", "nav_usd": 10000.0,
                        "position_value_usd": 10000.0, "units": 1.0},
            "at": _iso(at)}


def _paper_mark(at: dt.datetime) -> dict:
    """Марка живёт под номером ПОЗИЦИИ — ровно та форма, на которой сорвалась проба."""
    return {"kind": "paper_mark", "key": ["paper_mark", POSITION, _iso(at)],
            "payload": {"position_id": POSITION, "candidate_id": CANDS[0], "leg_id": "_single",
                        "status": "OPEN", "mark_state": "FRESH", "nav_usd": 10012.5,
                        "position_value_usd": 10012.5, "last_mark_at": _iso(at), "units": 1.0},
            "at": _iso(at)}


def _run(at: dt.datetime) -> dict:
    return {"kind": "run", "key": ["run", _iso(at)],
            "payload": {"generated_at": _iso(at), "scanners": ["s"], "scanner_errors": [],
                        "fact_refusals": []},
            "at": _iso(at)}


def scene_entries() -> list:
    """Лента сцены: снимки, решения, бумажная позиция с маркой, прогон.

    Порядок ПОЯВЛЕНИЯ кандидатов отличается от порядка их личностей — на этом и
    держится различение «место в ленте» против «множество».
    """
    entries: list = []
    for n, cid in enumerate(CANDS):
        entries.append(_snapshot(cid, ANCHOR + dt.timedelta(minutes=n)))
    entries.append(_paper_open(CANDS[0], ANCHOR + dt.timedelta(minutes=10)))
    for n, cid in enumerate(CANDS[:3]):
        entries.append(_decision(cid, ANCHOR + dt.timedelta(minutes=20 + n)))
    entries.append(_paper_mark(ANCHOR + dt.timedelta(minutes=40)))
    entries.append(_run(ANCHOR + dt.timedelta(minutes=50)))
    return entries


def build_ledger(root: Path) -> Path:
    data = Path(root) / "data"
    lwd.rechain(scene_entries(), data)
    return data / contract.DATA_SUBDIR / contract.LEDGER


def _first_appearance_ids(ledger) -> list:
    """ТЕЛО `all_candidate_ids` ДО ADR-799 — порядок ПЕРВОГО ПОЯВЛЕНИЯ.

    Это ПРИБОР, а не лекарство: носитель №1 воспроизводится настоящей формой
    дефекта, а не его описанием.
    """
    seen: list = []
    for e in ledger.read_all():
        if e.get("kind") != "candidate_snapshot":
            continue
        cid = ((e.get("payload") or {}).get("candidate") or {}).get("candidate_id")
        if cid and cid not in seen:
            seen.append(cid)
    return seen


class ScenePositiveControl(unittest.TestCase):
    """Сцена обязана быть ТОЙ ЖЕ лентой, иначе все числа прибора — о чужой."""

    def test_rebuilt_scene_reproduces_the_live_head_and_the_census_measures(self):
        with TemporaryDirectory() as root:
            ledger = build_ledger(Path(root))
            report = alo.measure(ledger, now=NOW)
            self.assertEqual(report["status"], alo.STATUS_CLEAN, report)
            self.assertIsNone(report["unmeasured_reason"])
            self.assertEqual(report["entries"], len(scene_entries()))
            self.assertGreaterEqual(report["population"], 5, report["lists"].keys())

    def test_a_ledger_whose_head_disagrees_is_NOT_MEASURED_not_clean(self):
        with TemporaryDirectory() as root:
            ledger = build_ledger(Path(root))
            lines = ledger.read_text(encoding="utf-8").rstrip("\n").split("\n")
            last = json.loads(lines[-1])
            last["entry_hash"] = "0" * 64          # вершина, которой сцена не даёт
            lines[-1] = json.dumps(last, sort_keys=True, separators=(",", ":"))
            ledger.write_text("\n".join(lines) + "\n", encoding="utf-8")

            report = alo.measure(ledger, now=NOW)
            self.assertEqual(report["status"], alo.STATUS_UNMEASURED)
            self.assertIn("не есть та же лента", report["unmeasured_reason"])
            # и НИ ОДНОГО вердикта о списках: числа о чужой ленте не печатаются
            self.assertEqual(report["lists"], {})

    def test_an_unreadable_ledger_is_NOT_MEASURED_with_a_named_reason(self):
        report = alo.measure(Path("/nonexistent/c923/ledger.jsonl"), now=NOW)
        self.assertEqual(report["status"], alo.STATUS_UNMEASURED)
        self.assertIn("лента не прочитана", report["unmeasured_reason"])
        self.assertIsNone(report["entries"])


class TheRealCarriersOfADR799AreNamed(unittest.TestCase):
    """Два НАСТОЯЩИХ носителя ADR-799 — прибор обязан назвать каждого."""

    def setUp(self):
        self._ids = registry.all_candidate_ids
        self._sherlock = rf_read._sherlock_block

    def tearDown(self):
        registry.all_candidate_ids = self._ids
        rf_read._sherlock_block = self._sherlock

    def test_carrier_one_first_appearance_order_IS_named_and_absent_without_it(self):
        with TemporaryDirectory() as root:
            ledger = build_ledger(Path(root))

            clean = alo.measure(ledger, now=NOW)
            self.assertEqual(clean["carriers"], [], clean["carriers"])
            self.assertEqual(clean["status"], alo.STATUS_CLEAN)

            registry.all_candidate_ids = _first_appearance_ids   # тело ДО ADR-799
            broken = alo.measure(ledger, now=NOW)

            self.assertEqual(broken["status"], alo.STATUS_FINDINGS, broken["status"])
            self.assertIn("latest.candidates", broken["carriers"], broken["carriers"])
            moved = [f for f in broken["findings"] if f["finding"] == alo.FINDING_MOVED]
            self.assertTrue(moved, broken["findings"])
            self.assertEqual(alo.VERDICT_MOVED, broken["lists"]["latest.candidates"]["verdict"])
            # вердикт назван ПРИЧИНОЙ, а не только ярлыком
            self.assertIn("ПОРЯДОК", broken["lists"]["latest.candidates"]["reason"])

    def test_carrier_two_decisions_today_ordered_by_place_IS_named(self):
        """`decisions_today`, упорядоченный МЕСТОМ в ленте — носитель №2 ADR-799.

        Воспроизводится наблюдаемой формой дефекта: настоящий блок считается
        настоящим кодом, а его список переупорядочивается в порядок ПЕРВОГО
        ПОЯВЛЕНИЯ — ровно то, что делал `latest_by_candidate.items()` до ADR-799.
        """
        original = rf_read._sherlock_block

        def ledger_ordered(data_dir, ledger, run_now, denom_counts):
            block = original(data_dir, ledger, run_now, denom_counts)
            order = {cid: n for n, cid in enumerate(_first_appearance_ids(ledger))}
            block["decisions_today"] = sorted(
                block["decisions_today"],
                key=lambda row: order.get(row.get("candidate_id"), -1))
            return block

        with TemporaryDirectory() as root:
            ledger = build_ledger(Path(root))

            clean = alo.measure(ledger, now=NOW)
            self.assertNotIn("latest.sherlock.decisions_today", clean["carriers"])

            rf_read._sherlock_block = ledger_ordered
            broken = alo.measure(ledger, now=NOW)

            self.assertIn("latest.sherlock.decisions_today", broken["carriers"],
                          broken["carriers"])
            finding = [f for f in broken["findings"]
                       if f["finding"] == alo.FINDING_MOVED
                       and f["list"] == "latest.sherlock.decisions_today"]
            self.assertTrue(finding, broken["findings"])
            self.assertEqual(alo.SET_DERIVED, finding[0]["nature"])


class ADeclarationIsRequiredAndCannotBeVacuous(unittest.TestCase):

    def setUp(self):
        self._declared = dict(alo.DECLARED)

    def tearDown(self):
        alo.DECLARED.clear()
        alo.DECLARED.update(self._declared)

    def test_a_list_with_no_declared_nature_is_a_finding_not_a_zero(self):
        with TemporaryDirectory() as root:
            ledger = build_ledger(Path(root))
            self.assertEqual(alo.measure(ledger, now=NOW)["status"], alo.STATUS_CLEAN)

            del alo.DECLARED["latest.candidates"]                # объявление снято
            report = alo.measure(ledger, now=NOW)

            self.assertEqual(report["status"], alo.STATUS_FINDINGS)
            undeclared = [f for f in report["findings"]
                          if f["finding"] == alo.FINDING_UNDECLARED]
            self.assertEqual(["latest.candidates"], [f["list"] for f in undeclared])
            self.assertIn("НЕ ИЗМЕРЕНО", undeclared[0]["detail"])

    def test_a_declaration_this_ledger_never_touches_is_a_THIRD_outcome(self):
        """«Нет в ответе» и «не защищает ни от чего» — разные утверждения.

        По одной ленте они неразличимы, поэтому не сливаются в находку: инв. #17.
        """
        with TemporaryDirectory() as root:
            ledger = build_ledger(Path(root))
            alo.DECLARED["latest.no_such_list_at_all"] = alo.SET_DERIVED
            report = alo.measure(ledger, now=NOW)

            self.assertIn("latest.no_such_list_at_all", report["unexercised_declarations"])
            self.assertNotIn("latest.no_such_list_at_all",
                             [f["list"] for f in report["findings"]])
            # и статус от этого НЕ краснеет — иначе третий исход был бы находкой
            self.assertEqual(alo.STATUS_CLEAN, report["status"], report["findings"])

    def test_a_wildcard_pattern_touching_nothing_is_the_same_third_outcome(self):
        with TemporaryDirectory() as root:
            ledger = build_ledger(Path(root))
            alo.DECLARED["latest.nowhere.*"] = alo.SET_DERIVED
            report = alo.measure(ledger, now=NOW)
            self.assertIn("latest.nowhere.*", report["unexercised_declarations"])

    def test_a_declaration_the_ledger_DOES_touch_is_not_called_unexercised(self):
        """Обратная сторона: иначе поле было бы «не измерено» на всём подряд."""
        with TemporaryDirectory() as root:
            ledger = build_ledger(Path(root))
            report = alo.measure(ledger, now=NOW)
            for path in ("latest.candidates", "latest.sherlock.top_blockers",
                         "latest.stale_feeds", "cio_view.observe_only"):
                self.assertIn(path, report["lists"])
                self.assertNotIn(path, report["unexercised_declarations"])

    def test_MULTISET_declared_for_an_identifiable_list_is_a_finding(self):
        """Единственная природа, которой сдвиг прощается, держится ЗАМЕРОМ."""
        with TemporaryDirectory() as root:
            ledger = build_ledger(Path(root))
            alo.DECLARED["latest.candidates"] = alo.MULTISET   # элементы НЕСУТ личность
            report = alo.measure(ledger, now=NOW)

            found = [f for f in report["findings"]
                     if f["finding"] == alo.FINDING_MULTISET_WITH_IDENTITY]
            self.assertEqual(["latest.candidates"], [f["list"] for f in found])

    def test_declaring_MULTISET_over_a_real_carrier_BUYS_NO_SILENCE(self):
        """Единственная природа, прощающая сдвиг, не может погасить находку.

        Один и тот же НАСТОЯЩИЙ носитель (порядок первого появления, ADR-799)
        под двумя объявлениями: `SET_DERIVED` даёт находку о сдвиге, `MULTISET`
        её снимает — и НА ЕЁ МЕСТО встаёт находка о самом объявлении, потому что
        элементы списка несут личность. Тишины не покупает ни то, ни другое.
        """
        original_ids = registry.all_candidate_ids
        try:
            registry.all_candidate_ids = _first_appearance_ids
            with TemporaryDirectory() as root:
                ledger = build_ledger(Path(root))

                as_set = alo.measure(ledger, now=NOW)
                self.assertEqual(
                    ["latest.candidates"],
                    [f["list"] for f in as_set["findings"]
                     if f["finding"] == alo.FINDING_MOVED])

                alo.DECLARED["latest.candidates"] = alo.MULTISET
                as_multiset = alo.measure(ledger, now=NOW)

                self.assertEqual(
                    [], [f["list"] for f in as_multiset["findings"]
                         if f["finding"] == alo.FINDING_MOVED])
                self.assertEqual(
                    ["latest.candidates"],
                    [f["list"] for f in as_multiset["findings"]
                     if f["finding"] == alo.FINDING_MULTISET_WITH_IDENTITY])
                self.assertEqual(alo.STATUS_FINDINGS, as_multiset["status"])
        finally:
            registry.all_candidate_ids = original_ids


class ContentMustBePreservedOrTheVerdictIsNotMeasured(unittest.TestCase):
    """Негодная перестановка обязана давать НЕ ИЗМЕРЕНО, а не «носитель».

    Воспроизводит НАСТОЯЩУЮ ошибку построения пробы (цикл #923): предмет
    `paper_mark` разрешался по `key[1]`, то есть по номеру ПОЗИЦИИ, марка
    отрывалась от своего открытия, и `nav()` — берущий строку с наибольшим
    ``seq`` — отдавал `NEVER_MARKED` вместо `FRESH`. Содержимое ответа при этом
    меняется, и единственный честный вердикт — третий.
    """

    def setUp(self):
        self._subject_map = alo.subject_map

    def tearDown(self):
        alo.subject_map = self._subject_map

    def test_scene_marks_its_position_so_the_control_has_something_to_lose(self):
        with TemporaryDirectory() as root:
            data = Path(root) / "data"
            lwd.rechain(scene_entries(), data)
            answer = rf_read.latest(data)
            marked = [c for c in answer["candidates"]
                      if (c.get("evidence") or {}).get("paper_position")]
            self.assertTrue(marked, "сцена обязана нести бумажную позицию")
            position = marked[0]["evidence"]["paper_position"]
            self.assertEqual("FRESH", position["mark_state"])
            self.assertAlmostEqual(10012.5, position["nav_usd"])

    def test_an_unresolved_subject_yields_NOT_MEASURED_with_a_named_cause(self):
        with TemporaryDirectory() as root:
            ledger = build_ledger(Path(root))
            self.assertEqual(alo.measure(ledger, now=NOW)["status"], alo.STATUS_CLEAN)

            alo.subject_map = lambda entries: {}      # ошибка цикла #923, дословно
            report = alo.measure(ledger, now=NOW)

            self.assertEqual(report["status"], alo.STATUS_UNMEASURED, report["status"])
            self.assertIn("latest.candidates", report["unmeasured_lists"],
                          report["unmeasured_lists"])
            reason = report["lists"]["latest.candidates"]["reason"]
            self.assertIn("не сохранила СОДЕРЖИМОЕ", reason)
            # и НЕ объявлен носителем: «не измерено» никогда не выдаётся за находку
            self.assertEqual(alo.VERDICT_UNMEASURED,
                             report["lists"]["latest.candidates"]["verdict"])
            self.assertNotIn("latest.candidates", report["carriers"])


class TheSubjectIsResolvedThroughThePayloadNotTheKey(unittest.TestCase):
    """Замер той самой ошибки: номер позиции лежит в НАГРУЗКЕ, а не в ключе."""

    def test_position_is_mapped_to_its_candidate_through_the_open_payload(self):
        mapping = alo.subject_map(scene_entries())
        self.assertEqual({POSITION: CANDS[0]}, mapping)

    def test_the_mark_and_its_open_share_one_subject(self):
        entries = scene_entries()
        mapping = alo.subject_map(entries)
        open_row = next(e for e in entries if e["kind"] == "paper_open")
        mark_row = next(e for e in entries if e["kind"] == "paper_mark")
        self.assertEqual(alo.subject_of(open_row, mapping),
                         alo.subject_of(mark_row, mapping))

    def test_grouping_by_the_key_alone_SPLITS_them_which_is_the_measured_defect(self):
        entries = scene_entries()
        open_row = next(e for e in entries if e["kind"] == "paper_open")
        mark_row = next(e for e in entries if e["kind"] == "paper_mark")
        self.assertNotEqual(alo.subject_of(open_row, {}), alo.subject_of(mark_row, {}))

    def test_a_run_row_is_never_a_candidate_subject(self):
        row = _run(ANCHOR)
        self.assertEqual(("kind", "run"), alo.subject_of(row, {}))


class PermutationsPreserveWithinSubjectOrder(unittest.TestCase):

    def test_both_permutations_keep_each_subject_internally_in_order(self):
        entries = scene_entries()
        mapping = alo.subject_map(entries)
        baseline: dict = {}
        for index, entry in enumerate(entries):
            baseline.setdefault(alo.subject_of(entry, mapping), []).append(index)

        permutations = alo.permutations(entries)
        self.assertEqual(2, len(permutations))
        for label, permuted in permutations:
            self.assertEqual(len(entries), len(permuted), label)
            seen: dict = {}
            for entry in permuted:
                seen.setdefault(alo.subject_of(entry, mapping), []).append(
                    entries.index(entry))
            self.assertEqual(baseline, seen, f"перестановка «{label}» порвала предмет")

    def test_the_two_permutations_are_not_the_same_order(self):
        entries = scene_entries()
        (_, first), (_, second) = alo.permutations(entries)
        self.assertNotEqual([id(e) for e in first], [id(e) for e in second])


class DeclarationLookup(unittest.TestCase):

    def test_exact_path_wins(self):
        self.assertEqual(alo.RANKED,
                         alo.declared_nature("latest.sherlock.top_blockers"))

    def test_wildcard_matches_only_the_same_segment_count(self):
        self.assertEqual(alo.SET_DERIVED,
                         alo.declared_nature("cio_view.correlation_groups.ANY_GROUP"))
        # глубже образца — НЕ накрыто: иначе объявление молча расширилось бы
        self.assertIsNone(
            alo.declared_nature("cio_view.correlation_groups.ANY_GROUP.deeper"))

    def test_an_unknown_path_has_no_nature_rather_than_a_default(self):
        self.assertIsNone(alo.declared_nature("latest.something_new"))

    def test_every_declared_nature_is_one_of_the_three(self):
        for path, nature in alo.DECLARED.items():
            self.assertIn(nature, alo.NATURES, path)


class TheTactIsDecidedByTheFile(unittest.TestCase):
    """Три исхода вопроса «пора ли мерить», и третий — отдельное значение."""

    def test_a_missing_artifact_is_due_because_no_measurement_ever_happened(self):
        with TemporaryDirectory() as root:
            self.assertEqual(alo.DUE,
                             alo.measurement_due(Path(root) / "absent.json", now=NOW))

    def test_a_fresh_artifact_is_not_due_and_a_stale_one_is(self):
        with TemporaryDirectory() as root:
            artifact = Path(root) / alo.ARTIFACT
            artifact.write_text(json.dumps({"generated_at": NOW.isoformat()}),
                                encoding="utf-8")
            self.assertEqual(alo.NOT_DUE, alo.measurement_due(artifact, now=NOW))
            self.assertEqual(alo.DUE, alo.measurement_due(
                artifact, now=NOW + dt.timedelta(days=alo.MEASUREMENT_TACT_DAYS, hours=1)))

    def test_an_artifact_without_a_stamp_is_NOT_MEASURED_rather_than_due(self):
        """«Пора» и «неизвестно» ведут к разным действиям — слить их нельзя."""
        with TemporaryDirectory() as root:
            artifact = Path(root) / alo.ARTIFACT
            artifact.write_text(json.dumps({"version": alo.VERSION}), encoding="utf-8")
            verdict = alo.measurement_due(artifact, now=NOW)
            self.assertTrue(verdict.startswith(alo.DUE_UNMEASURED), verdict)
            self.assertIn("generated_at", verdict)
            self.assertNotEqual(alo.DUE, verdict)

    def test_an_unparsable_artifact_is_NOT_MEASURED_with_a_named_reason(self):
        with TemporaryDirectory() as root:
            artifact = Path(root) / alo.ARTIFACT
            artifact.write_text("{не json", encoding="utf-8")
            verdict = alo.measurement_due(artifact, now=NOW)
            self.assertTrue(verdict.startswith(alo.DUE_UNMEASURED), verdict)
            self.assertIn("не разобран", verdict)

    def test_the_three_outcomes_are_distinguishable_values(self):
        self.assertEqual(3, len({alo.DUE, alo.NOT_DUE, alo.DUE_UNMEASURED}))


if __name__ == "__main__":
    unittest.main()


class VerdictPrecedenceDoesNotDependOnPermutationOrder(unittest.TestCase):
    """MOVED > UNMEASURED > STABLE, и порядок перестановок на итог не влияет.

    Иначе прибор отвечал бы на вопрос «в каком порядке я мерил»: сдвиг, показанный
    ГОДНОЙ перестановкой, есть положительное наблюдение, и негодность другой его не
    отменяет. Сцена даёт обе беды разом — настоящий носитель №1 И оторванную марку.
    """

    def setUp(self):
        self._ids = registry.all_candidate_ids
        self._subject_map = alo.subject_map
        self._permutations = alo.permutations

    def tearDown(self):
        registry.all_candidate_ids = self._ids
        alo.subject_map = self._subject_map
        alo.permutations = self._permutations

    @staticmethod
    def _one_good_one_bad(entries, *, bad_first: bool):
        """Пара перестановок, из которых ОДНА годна, а другая НЕТ.

        Годная разрешает предмет по нагрузке открытия; негодная — не разрешает
        вовсе (пустая карта), то есть рвёт марку от её позиции. Это и есть сцена,
        на которой старшинство вердиктов вообще наблюдаемо: прежняя редакция теста
        брала ДВЕ годные перестановки, старшинства не касалась — и мутация №11
        пережила прогон №2 (дыра покрытия МОЯ, названа в ADR-800).
        """
        good = ("годная", alo._subject_order(entries, alo.subject_map(entries),
                                             lambda s: list(reversed(s))))
        bad = ("негодная", alo._subject_order(entries, {},
                                              lambda s: list(reversed(s))))
        return [bad, good] if bad_first else [good, bad]

    def test_the_two_permutations_of_the_control_really_disagree(self):
        """Предпосылка контроля ИЗМЕРЕНА: годная даёт сдвиг, негодная рвёт содержимое.

        Без этой пробы контроль ниже мог бы быть зелёным оттого, что обе
        перестановки годны, — ровно та ошибка, которой мутация №11 и выжила.
        """
        registry.all_candidate_ids = _first_appearance_ids
        with TemporaryDirectory() as root:
            ledger = build_ledger(Path(root))
            for label, only in (("годная", False), ("негодная", True)):
                alo.permutations = lambda entries, _o=only: [
                    self._one_good_one_bad(entries, bad_first=_o)[0]]
                report = alo.measure(ledger, now=NOW)
                verdict = report["lists"]["latest.candidates"]["verdict"]
                if label == "годная":
                    self.assertEqual(alo.VERDICT_MOVED, verdict, report["lists"]["latest.candidates"])
                else:
                    self.assertEqual(alo.VERDICT_UNMEASURED, verdict,
                                     report["lists"]["latest.candidates"])

    def test_a_demonstrated_move_survives_an_unusable_permutation_either_order(self):
        verdicts = {}
        for name, bad_first in (("годная первой", False), ("негодная первой", True)):
            registry.all_candidate_ids = _first_appearance_ids   # носитель №1
            alo.permutations = lambda entries, _b=bad_first: self._one_good_one_bad(
                entries, bad_first=_b)
            with TemporaryDirectory() as root:
                ledger = build_ledger(Path(root))
                verdicts[name] = alo.measure(
                    ledger, now=NOW)["lists"]["latest.candidates"]["verdict"]

        self.assertEqual(alo.VERDICT_MOVED, verdicts["годная первой"], verdicts)
        self.assertEqual(alo.VERDICT_MOVED, verdicts["негодная первой"], verdicts)

    def test_an_unusable_permutation_still_blocks_a_STABLE_verdict(self):
        """Обратная сторона: «сдвига не нашли» не есть «устойчив», если часть
        ответа пробой не покрыта."""
        alo.subject_map = lambda entries: {}
        with TemporaryDirectory() as root:
            ledger = build_ledger(Path(root))
            report = alo.measure(ledger, now=NOW)
            self.assertEqual(alo.VERDICT_UNMEASURED,
                             report["lists"]["latest.candidates"]["verdict"])
            self.assertEqual(alo.STATUS_UNMEASURED, report["status"])
