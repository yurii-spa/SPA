"""Положительные контроли переписи «цена усечения ленты по возрасту» (ADR-793).

Каждый тест — ВОПРОС, на который прибор обязан отвечать ПО-РАЗНОМУ в двух сценах;
«зелёный на одной сцене» ничего не доказывает (`.claude/rules/acceptance.md`, п. 3).
Сцены строятся из настоящих строк ленты и читаются НАСТОЯЩЕЙ читающей моделью
(`research_factory.read`), а не её подобием: предмет прибора — ответ модели, и
заглушка отвечала бы на другой вопрос.

# FROZEN-DATE-OK: injected-clock — якорь сцены ``ANCHOR`` — литерал, и от него же
# вычислены ВСЕ отметки строк; момент замера приходит в прибор аргументом
# (``measure(..., now=ANCHOR + …)``, ``measurement_due(..., now=…)``). Окно
# прибор отмеряет от САМОЙ СВЕЖЕЙ ЗАПИСИ ленты (``horizon``), а не от стенных
# часов, поэтому вердикт не движется от календаря ни одной своей стороной.
"""

from __future__ import annotations

import ast
import datetime as dt
import inspect
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import ledger_window_dependency_census as lwd
from spa_core.research_factory import contract

ANCHOR = dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc)
SPAN_DAYS = 6
LADDER = (1, 2, 3)


def _iso(moment: dt.datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _snapshot(cid: str, nonce: int, at: dt.datetime) -> dict:
    return {"kind": "candidate_snapshot", "key": ["candidate_snapshot", cid, f"{cid}-{nonce}"],
            "payload": {"candidate": {"candidate_id": cid, "domain": "D",
                                      "admission_state": None}},
            "at": _iso(at)}


def _run_row(nonce: int, at: dt.datetime) -> dict:
    return {"kind": "run", "key": ["run", f"r{nonce}"], "payload": {"scanned": 3},
            "at": _iso(at)}


def scene_entries(*, refreshed: bool, candidates: int = 3) -> list:
    """Шесть суток ленты. ``refreshed`` — пересниматься ли кандидатам КАЖДЫЙ день.

    Обе сцены имеют ОДИН И ТОТ ЖЕ охват, одни и те же дни прогонов и одно и то же
    множество кандидатов. Различаются РОВНО возрастом свежайшего снимка — то есть
    ровно тем, что прибор и обязан мерить.
    """
    entries: list = []
    for day in range(SPAN_DAYS):
        at = ANCHOR + dt.timedelta(days=day)
        if day == 0 or refreshed:
            for i in range(candidates):
                entries.append(_snapshot(f"cand{i}", day, at + dt.timedelta(minutes=i)))
        entries.append(_run_row(day, at + dt.timedelta(hours=1)))
    return entries


def build_scene(root: Path, entries) -> Path:
    data = Path(root) / "data"
    lwd.rechain(entries, data)
    return data


NOW = ANCHOR + dt.timedelta(days=SPAN_DAYS)


class RechainIsTheSameLedger(unittest.TestCase):
    """Положительный контроль ПОСТРОЕНИЯ сцены: пересборка обязана дать ту же вершину."""

    def test_rechain_reproduces_the_head_written_by_the_ledger_itself(self):
        from spa_core.utils.hash_ledger import HashLedger

        with TemporaryDirectory() as tmp:
            data = Path(tmp) / "written"
            ledger = HashLedger(data, contract.DATA_SUBDIR, contract.ANCHORS_SUBDIR,
                                contract.LEDGER)
            written = [ledger.append(e["kind"], e["key"], e["payload"], e["at"])
                       for e in scene_entries(refreshed=True)]
            rebuilt = lwd.rechain(written, Path(tmp) / "rebuilt")
            self.assertEqual(rebuilt, written[-1]["entry_hash"],
                             "пересборка цепи дала ДРУГУЮ вершину — сцена не та же лента")

    def test_a_tampered_tail_makes_the_whole_measurement_unmeasured(self):
        """Вершина не сошлась ⇒ НЕ ИЗМЕРЕНО, а не «просто другая лента»."""
        with TemporaryDirectory() as tmp:
            entries = scene_entries(refreshed=True)
            data = build_scene(Path(tmp), entries)
            path = data / contract.DATA_SUBDIR / contract.LEDGER
            rows = [json.loads(line) for line in path.read_text().splitlines() if line]
            rows[-1]["entry_hash"] = "0" * 64
            path.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n")
            doc = lwd.measure(data, now=NOW, windows=LADDER)
            self.assertFalse(doc["measured"])
            self.assertEqual(doc["status"], lwd.STATUS_UNMEASURED)
            self.assertIn("вершину живой ленты", doc["reason"])


class TheVerdictFollowsTheAgeOfTheSnapshot(unittest.TestCase):
    """Две сцены, различающиеся РОВНО возрастом снимков — вердикты ПРОТИВОПОЛОЖНЫЕ."""

    def _measure(self, *, refreshed: bool) -> dict:
        with TemporaryDirectory() as tmp:
            data = build_scene(Path(tmp), scene_entries(refreshed=refreshed))
            return lwd.measure(data, now=NOW, windows=LADDER)

    def test_refreshed_candidates_make_the_shortest_window_safe(self):
        doc = self._measure(refreshed=True)
        self.assertTrue(doc["measured"], doc.get("reason"))
        self.assertEqual(doc["status"], lwd.STATUS_CLEAN)
        self.assertEqual(doc["safe_window_days"], min(LADDER))
        self.assertEqual(doc["one_day_dependent_share_pct"], 0.0)
        self.assertEqual(doc["findings"], [])
        # «Ноль» здесь — ИЗМЕРЕННЫЙ ноль: записи усечение всё-таки сняло.
        self.assertTrue(all(r["dropped_entries"] > 0 for r in doc["rows"]),
                        "окно не сняло ни одной записи — сцена не проверяет усечение")

    def test_candidates_snapshotted_once_have_no_safe_window(self):
        doc = self._measure(refreshed=False)
        self.assertTrue(doc["measured"], doc.get("reason"))
        self.assertEqual(doc["status"], lwd.STATUS_FINDINGS)
        self.assertIsNone(doc["safe_window_days"],
                          "«безопасного окна нет» обязано быть None, а не нулём")
        self.assertGreater(doc["one_day_dependent_share_pct"], 0.0)
        self.assertEqual([f["kind"] for f in doc["findings"]],
                         [lwd.FINDING_NO_SAFE_WINDOW])
        for row in doc["rows"]:
            self.assertEqual(row["candidates_lost_differential"], 3)

    def _main_code(self, *, refreshed: bool) -> int:
        with TemporaryDirectory() as tmp:
            data = build_scene(Path(tmp), scene_entries(refreshed=refreshed))
            return lwd.main(["--data-dir", str(data), "--no-write",
                             "--windows", ",".join(str(w) for w in LADDER)])

    def test_main_returns_zero_on_a_clean_scene(self):
        """Исход доходит до КОДА ВОЗВРАТА, а не остаётся в словаре."""
        self.assertEqual(self._main_code(refreshed=True), 0)

    def test_main_returns_one_on_a_finding(self):
        self.assertEqual(self._main_code(refreshed=False), 1)


class BothRoutesOrNothing(unittest.TestCase):
    """Маршрутов два, и расхождение — НЕ ИЗМЕРЕНО, а не среднее."""

    def test_agreement_is_reported_on_every_measured_window(self):
        with TemporaryDirectory() as tmp:
            data = build_scene(Path(tmp), scene_entries(refreshed=False))
            doc = lwd.measure(data, now=NOW, windows=LADDER)
        for row in doc["rows"]:
            self.assertTrue(row["routes_agree"])
            self.assertEqual(row["candidates_lost_differential"],
                             row["candidates_lost_structural"])

    def test_a_disagreeing_structural_route_refuses_the_whole_measurement(self):
        original = lwd.structural_lost
        try:
            lwd.structural_lost = lambda *_a, **_k: {"кандидат-которого-нет"}
            with TemporaryDirectory() as tmp:
                data = build_scene(Path(tmp), scene_entries(refreshed=False))
                doc = lwd.measure(data, now=NOW, windows=LADDER)
        finally:
            lwd.structural_lost = original
        self.assertFalse(doc["measured"])
        self.assertEqual(doc["status"], lwd.STATUS_UNMEASURED)
        self.assertIn("НЕ СОШЛИСЬ", doc["reason"])
        self.assertIsNone(doc.get("one_day_dependent_share_pct"),
                          "доля не имеет права существовать, когда маршруты спорят")


class ListsAreAddressedByIdentity(unittest.TestCase):
    """Та самая ошибка прототипа: адресация по МЕСТУ завышала долю вдвое."""

    def test_removing_an_earlier_item_does_not_move_the_others(self):
        full = lwd.leaves({"xs": [{"candidate_id": "a", "v": 1},
                                  {"candidate_id": "b", "v": 2},
                                  {"candidate_id": "c", "v": 3}]})
        short = lwd.leaves({"xs": [{"candidate_id": "b", "v": 2},
                                   {"candidate_id": "c", "v": 3}]})
        changed = {p for p in set(full) | set(short) if full.get(p) != short.get(p)}
        self.assertEqual(changed, {"xs[candidate_id=a].candidate_id", "xs[candidate_id=a].v"},
                         "сдвиг адресов выдал бы изменившимися и уцелевшие элементы")

    def test_an_item_without_identity_still_gets_an_address(self):
        got = lwd.leaves({"xs": [1, 2]})
        self.assertEqual(sorted(got), ["xs[#0]", "xs[#1]"])

    def test_a_boolean_is_not_mistaken_for_an_identity(self):
        # bool — подкласс int, и `id=True` адресовало бы два разных элемента одинаково.
        got = lwd.leaves({"xs": [{"id": True, "v": 1}, {"id": True, "v": 2}]})
        self.assertEqual(sorted(got), ["xs[#0].id", "xs[#0].v", "xs[#1].id", "xs[#1].v"])


class TheChainExclusionIsChecked(unittest.TestCase):
    """Вычет, вычитающий несуществующий лист, — пустой сторож, и он запрещён."""

    def test_declared_chain_leaves_are_reported_and_left_out_of_the_share(self):
        with TemporaryDirectory() as tmp:
            data = build_scene(Path(tmp), scene_entries(refreshed=True))
            doc = lwd.measure(data, now=NOW, windows=LADDER)
        for row in doc["rows"]:
            self.assertEqual(sorted(row["chain_identity_leaves_changed"]),
                             sorted(lwd.CHAIN_IDENTITY_LEAVES),
                             "вершина цепи обязана меняться у ЛЮБОГО усечения")
            self.assertEqual(row["changed_leaves"], 0)

    def test_a_declared_leaf_that_the_answer_does_not_have_is_unmeasured(self):
        original = lwd.CHAIN_IDENTITY_LEAVES
        try:
            lwd.CHAIN_IDENTITY_LEAVES = original + ("latest.ledger_head_hash.nonesuch",)
            with TemporaryDirectory() as tmp:
                data = build_scene(Path(tmp), scene_entries(refreshed=True))
                doc = lwd.measure(data, now=NOW, windows=LADDER)
        finally:
            lwd.CHAIN_IDENTITY_LEAVES = original
        self.assertFalse(doc["measured"])
        self.assertIn("latest.ledger_head_hash.nonesuch", doc["reason"])


class TheThirdOutcomeIsItsOwnValue(unittest.TestCase):

    def test_an_absent_ledger_names_the_path_and_measures_nothing(self):
        with TemporaryDirectory() as tmp:
            doc = lwd.measure(Path(tmp) / "data", now=NOW, windows=LADDER)
        self.assertFalse(doc["measured"])
        self.assertEqual(doc["status"], lwd.STATUS_UNMEASURED)
        self.assertIn(contract.LEDGER, doc["reason"])
        self.assertEqual(doc["rows"], [])

    def test_a_ledger_younger_than_the_smallest_window_is_unmeasured_not_clean(self):
        entries = [_snapshot("cand0", 0, ANCHOR),
                   _run_row(0, ANCHOR + dt.timedelta(hours=1))]
        with TemporaryDirectory() as tmp:
            data = build_scene(Path(tmp), entries)
            doc = lwd.measure(data, now=NOW, windows=LADDER)
        self.assertFalse(doc["measured"])
        self.assertIn("короче наименьшего окна", doc["reason"])

    def test_an_unparsable_stamp_refuses_instead_of_borrowing_a_neighbour(self):
        """Подстановка соседней датой сделала бы «не наблюдали» равным наблюдению."""
        entries = scene_entries(refreshed=True)
        entries[3] = dict(entries[3], at="позавчера")
        with TemporaryDirectory() as tmp:
            data = build_scene(Path(tmp), entries)
            doc = lwd.measure(data, now=NOW, windows=LADDER)
        self.assertFalse(doc["measured"])
        self.assertIn("отметки не разобраны у 1", doc["reason"])
        self.assertIn("НЕ ИЗВЕСТНО", doc["reason"])

    def test_a_single_entry_ledger_is_unmeasured(self):
        with TemporaryDirectory() as tmp:
            data = build_scene(Path(tmp), [_run_row(0, ANCHOR)])
            doc = lwd.measure(data, now=NOW, windows=LADDER)
        self.assertFalse(doc["measured"])
        self.assertIn("усекать нечего", doc["reason"])

    def test_measurement_due_tells_three_outcomes_apart(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / lwd.ARTIFACT
            due, why = lwd.measurement_due(out, now=NOW)
            self.assertTrue(due)
            self.assertIn("артефакта нет", why)
            out.write_text("{не json")
            due, why = lwd.measurement_due(out, now=NOW)
            self.assertTrue(due, "нечитаемая отметка не имеет права значить «мерили недавно»")
            out.write_text(json.dumps({"generated_at": NOW.isoformat()}))
            due, why = lwd.measurement_due(out, now=NOW + dt.timedelta(days=1))
            self.assertFalse(due)
            due, _ = lwd.measurement_due(
                out, now=NOW + dt.timedelta(days=lwd.MEASUREMENT_TACT_DAYS))
            self.assertTrue(due)


class TheLiveLedgerIsNeverWritten(unittest.TestCase):

    def test_measure_leaves_the_source_bytes_and_stamps_untouched(self):
        with TemporaryDirectory() as tmp:
            data = build_scene(Path(tmp), scene_entries(refreshed=False))
            before = {p: (p.stat().st_size, p.stat().st_mtime_ns)
                      for p in sorted(Path(data).rglob("*")) if p.is_file()}
            lwd.measure(data, now=NOW, windows=LADDER)
            after = {p: (p.stat().st_size, p.stat().st_mtime_ns)
                     for p in sorted(Path(data).rglob("*")) if p.is_file()}
        self.assertEqual(before, after, "прибор тронул исходный каталог")

    def test_scenes_do_not_outlive_the_measurement(self):
        with TemporaryDirectory() as tmp:
            data = build_scene(Path(tmp), scene_entries(refreshed=False))
            work = Path(tmp) / "scenes"
            work.mkdir()
            lwd.measure(data, now=NOW, windows=LADDER, work_dir=work)
            left = [p.name for p in work.iterdir() if p.name != "full"]
        self.assertEqual(left, [], f"сцены окон остались на диске: {left}")


class TheDefaultProducerIsTheRealReadingModel(unittest.TestCase):
    """Сцены подменяемы, УМОЛЧАНИЕ — нет: иначе батарея мерила бы заглушку."""

    def test_answer_leaves_calls_both_public_entries_of_research_factory_read(self):
        tree = ast.parse(inspect.getsource(lwd.answer_leaves))
        called = {f"{n.func.value.id}.{n.func.attr}"
                  for n in ast.walk(tree)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                  and isinstance(n.func.value, ast.Name)}
        self.assertIn("rf_read.latest", called)
        self.assertIn("rf_read.cio_view", called)

    def test_measure_derives_every_answer_through_answer_leaves(self):
        tree = ast.parse(inspect.getsource(lwd.measure))
        names = {n.func.id for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("answer_leaves", names)
        self.assertNotIn("latest", names, "ответ добывается мимо единственной двери")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
