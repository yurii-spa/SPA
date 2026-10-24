"""Положительные контроли строки УПЛОТНЕНИЯ истории кандидата (ADR-795, заказ G794 п. 1).

Каждый тест — ВОПРОС, на который система обязана отвечать ПО-РАЗНОМУ в двух сценах:
«зелёный на одной сцене» не доказывает ничего (`.claude/rules/acceptance.md`, п. 3).
Сцены — настоящие строки ленты, прочитанные НАСТОЯЩЕЙ читающей моделью
(`research_factory.read.latest` / `.cio_view`), а не её подобием: предмет правки —
ответ модели, и заглушка отвечала бы на другой вопрос.

Предмет, названный замером ADR-794: `latest.candidates[].reasons` и
`latest.rejections[].reasons` перечисляют причины за ВСЮ жизнь кандидата, поэтому
повтор `transition` их НАКАПЛИВАЕТ (4 554 листа) — лекарство портит ровно то, что
охраняет. Уплотнение несёт историю В СЕБЕ и читается только СВЕЖАЙШЕЕ, поэтому его
повтор не накапливает ничего. Обе половины этого утверждения проверяются ниже
ПРОТИВОПОЛОЖНЫМИ вердиктами на одной и той же ленте.

# FROZEN-DATE-OK: injected-clock — якорь сцены ``ANCHOR`` литерал, и от него же
# вычислены ВСЕ отметки строк; момент замера приходит в код аргументом
# (``rp.measure(..., now=NOW)``, ``history.compact(..., now=…)``,
# ``rf_read.cio_view(..., NOW)``). Ни одна сторона вердикта не читает стенные часы.
"""

from __future__ import annotations

import ast
import datetime as dt
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List, Optional

from spa_core.monitoring import ledger_resnapshot_price_census as rp
from spa_core.monitoring import ledger_window_dependency_census as lwd
from spa_core.research_factory import contract, history
from spa_core.research_factory import read as rf_read
from spa_core.research_factory import run as run_mod
from spa_core.research_factory._common import ledger_for

ANCHOR = dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc)
SPAN_DAYS = 6
HORIZON = ANCHOR + dt.timedelta(days=SPAN_DAYS - 1, hours=1)
NOW = ANCHOR + dt.timedelta(days=SPAN_DAYS - 1, hours=2)
CANDIDATES = ("cand0", "cand1", "cand2")
LADDER = (1, 2, 3)


def _iso(moment: dt.datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _snapshot(cid: str, nonce: int, at: dt.datetime) -> dict:
    return {"kind": "candidate_snapshot", "key": ["candidate_snapshot", cid, f"{cid}-{nonce}"],
            "payload": {"candidate": {"candidate_id": cid, "domain": "D",
                                      "admission_state": None}},
            "at": _iso(at)}


def _run_row(nonce: int, at: dt.datetime) -> dict:
    return {"kind": "run", "key": ["run", f"r{nonce}"],
            "payload": {"generated_at": _iso(at), "denominators": {"scanned": 3}},
            "at": _iso(at)}


def _transition(cid: str, frm: Optional[str], to: str, reason: str, at: dt.datetime) -> dict:
    return {"kind": "transition", "key": ["transition", cid, None, to, _iso(at)],
            "payload": {"candidate_id": cid, "from_state": frm, "gate_ref": None,
                        "reason": reason, "to_state": to},
            "at": _iso(at)}


def scene_entries(*, transition_copies: int = 1) -> List[dict]:
    """Шесть суток ленты: снимки свежие КАЖДЫЙ день, переходы — только в первые двое.

    То есть единственное, чем ответ держится за СТАРЫЕ записи, — история переходов:
    ровно предмет ADR-795. ``transition_copies`` повторяет строки переходов —
    положительный контроль того, что повтор их НАКАПЛИВАЕТ.
    """
    entries: List[dict] = []
    for day in range(SPAN_DAYS):
        at = ANCHOR + dt.timedelta(days=day)
        for index, cid in enumerate(CANDIDATES):
            entries.append(_snapshot(cid, day, at + dt.timedelta(minutes=index)))
        if day in (0, 1):
            for copy in range(transition_copies):
                for index, cid in enumerate(CANDIDATES):
                    frm = None if day == 0 else contract.DISCOVERED
                    to = contract.DISCOVERED if day == 0 else contract.REJECTED
                    entries.append(_transition(
                        cid, frm, to, f"reason-d{day}-{cid}",
                        at + dt.timedelta(minutes=30 + index, seconds=copy)))
        entries.append(_run_row(day, at + dt.timedelta(hours=1)))
    return entries


def compaction_at(entries: List[dict], moment: dt.datetime) -> List[dict]:
    stamps = [lwd._parse_at(entry.get("at")) for entry in entries]
    return rp.compaction_rows_at(entries, stamps, moment, set(CANDIDATES))


def build(root: Path, entries: List[dict], name: str = "scene") -> Path:
    data = Path(root) / name / "data"
    ordered = sorted(entries, key=lambda entry: (lwd._parse_at(entry["at"]), entry["kind"]))
    lwd.rechain(ordered, data)
    return data


def truncate(entries: List[dict], *, days: int) -> List[dict]:
    edge = HORIZON - dt.timedelta(days=days)
    return [entry for entry in entries if (lwd._parse_at(entry["at"]) or edge) >= edge]


def reasons_of(doc: dict) -> dict:
    return {row["candidate_id"]: list(row.get("reasons") or []) for row in doc["candidates"]}


def states_of(doc: dict) -> dict:
    return {row["candidate_id"]: row.get("admission_state") for row in doc["candidates"]}


def candidate_drift(left: dict, right: dict) -> List[str]:
    """Листья ответа, разошедшиеся МЕЖДУ сценами, кроме имени самого лекарства."""
    a = lwd.leaves({"latest": left})
    b = lwd.leaves({"latest": right})
    return sorted(path for path in set(a) | set(b)
                  if path not in lwd.CHAIN_IDENTITY_LEAVES
                  and not path.startswith(rp.MEDICINE_PRESENCE_PREFIX)
                  and a.get(path) != b.get(path))


class CompactionIsNeutralOnTheWholeLedger(unittest.TestCase):
    """Контроль №1: лекарство, сдвинувшее ответ на ПОЛНОЙ ленте, лечит не ту болезнь."""

    def test_a_faithful_compaction_changes_no_candidate_leaf(self):
        entries = scene_entries()
        with TemporaryDirectory() as td:
            plain = rf_read.latest(build(Path(td), entries, "plain"))
            with_comp = rf_read.latest(build(
                Path(td), entries + compaction_at(entries, HORIZON - dt.timedelta(days=1)),
                "comp"))
        self.assertEqual([], candidate_drift(plain, with_comp))
        self.assertEqual(reasons_of(plain), reasons_of(with_comp))
        self.assertEqual(history.STATUS_ABSENT, plain["history_compaction"]["status"])
        self.assertEqual(history.STATUS_OK, with_comp["history_compaction"]["status"])

    def test_repeating_the_transition_rows_instead_multiplies_the_reasons(self):
        """ПРОТИВОПОЛОЖНЫЙ вердикт на той же ленте — то, что измерил ADR-794."""
        with TemporaryDirectory() as td:
            once = rf_read.latest(build(Path(td), scene_entries(transition_copies=1), "one"))
            thrice = rf_read.latest(build(Path(td), scene_entries(transition_copies=3), "three"))
        self.assertEqual({cid: 1 for cid in CANDIDATES},
                         {cid: len(v) for cid, v in reasons_of(once).items()})
        self.assertEqual({cid: 3 for cid in CANDIDATES},
                         {cid: len(v) for cid, v in reasons_of(thrice).items()})
        self.assertNotEqual([], candidate_drift(once, thrice))


class TruncationKeepsTheHistoryOnlyThroughTheCompaction(unittest.TestCase):
    """Предмет заказа: усечение по возрасту обязано стать безопасным — и только с уплотнением."""

    def test_without_the_compaction_truncation_loses_the_reasons_and_the_state(self):
        entries = scene_entries()
        with TemporaryDirectory() as td:
            whole = rf_read.latest(build(Path(td), entries, "whole"))
            cut = rf_read.latest(build(Path(td), truncate(entries, days=1), "cut"))
        self.assertEqual({cid: 1 for cid in CANDIDATES},
                         {cid: len(v) for cid, v in reasons_of(whole).items()})
        self.assertEqual({cid: 0 for cid in CANDIDATES},
                         {cid: len(v) for cid, v in reasons_of(cut).items()})
        self.assertEqual({cid: None for cid in CANDIDATES}, states_of(cut))

    def test_with_the_compaction_the_same_truncation_keeps_both(self):
        entries = scene_entries()
        kept = truncate(entries + compaction_at(entries, HORIZON - dt.timedelta(days=1)), days=1)
        with TemporaryDirectory() as td:
            whole = rf_read.latest(build(Path(td), entries, "whole"))
            cut = rf_read.latest(build(Path(td), kept, "cut"))
        self.assertEqual(reasons_of(whole), reasons_of(cut))
        self.assertEqual(states_of(whole), states_of(cut))
        self.assertEqual([], candidate_drift(whole, cut))

    def test_the_cio_view_state_survives_the_same_truncation(self):
        """Второй публичный вход читающей модели — он тоже судит по переходам."""
        entries = [entry for entry in scene_entries()]
        for index, cid in enumerate(CANDIDATES):
            entries.append(_transition(cid, contract.REJECTED, contract.OBSERVE_ONLY,
                                       "projected elsewhere",
                                       ANCHOR + dt.timedelta(days=1, minutes=40 + index)))
        kept = truncate(entries + compaction_at(entries, HORIZON - dt.timedelta(days=1)), days=1)
        with TemporaryDirectory() as td:
            whole = rf_read.cio_view(build(Path(td), entries, "whole"), NOW)
            bare = rf_read.cio_view(build(Path(td), truncate(entries, days=1), "bare"), NOW)
            cut = rf_read.cio_view(build(Path(td), kept, "cut"), NOW)
        self.assertEqual(sorted(CANDIDATES), sorted(whole["observe_only"]))
        self.assertEqual([], bare["observe_only"])
        self.assertEqual(sorted(whole["observe_only"]), sorted(cut["observe_only"]))


class OnlyTheNewestCompactionIsRead(unittest.TestCase):
    """Почему повтор уплотнения бесплатен для ОТВЕТА, а повтор переходов — нет."""

    def test_five_copies_of_the_compaction_answer_exactly_as_one(self):
        entries = scene_entries()
        one = compaction_at(entries, HORIZON - dt.timedelta(days=1))
        many: List[dict] = []
        for step in range(1, 6):
            many.extend(compaction_at(entries, HORIZON - dt.timedelta(days=step)))
        with TemporaryDirectory() as td:
            single = rf_read.latest(build(Path(td), entries + one, "one"))
            five = rf_read.latest(build(Path(td), entries + many, "five"))
        self.assertEqual(5 * len(CANDIDATES), len(many))
        self.assertEqual(reasons_of(single), reasons_of(five))
        self.assertEqual([], candidate_drift(single, five))

    def test_the_merge_takes_the_repeat_number_and_not_merely_the_content(self):
        """Адресация МУЛЬТИМНОЖЕСТВОМ, а не множеством: урок ADR-794, проверенный здесь.

        Лента с ТРЕМЯ одинаковыми переходами и уплотнением, несущим все три, обязана
        дать три причины — множество дало бы одну.
        """
        entries = scene_entries(transition_copies=3)
        comp = compaction_at(entries, HORIZON - dt.timedelta(days=1))
        self.assertEqual([6] * len(CANDIDATES),
                         [row["payload"]["absorbed"] for row in comp])
        with TemporaryDirectory() as td:
            doc = rf_read.latest(build(Path(td), entries + comp, "scene"))
        self.assertEqual({cid: 3 for cid in CANDIDATES},
                         {cid: len(v) for cid, v in reasons_of(doc).items()})


class ThreeValuesOfTheCompactionStatus(unittest.TestCase):
    """Инв. #17: «в силе» · «ещё нет» · «нельзя поручиться» — три значения, не одно."""

    def _status(self, entries: List[dict]) -> dict:
        with TemporaryDirectory() as td:
            return rf_read.latest(build(Path(td), entries, "scene"))["history_compaction"]

    def test_absent_ok_and_broken_are_three_different_answers(self):
        entries = scene_entries()
        comp = compaction_at(entries, HORIZON - dt.timedelta(days=1))
        bad_schema = [dict(row) for row in comp]
        bad_schema[0]["payload"] = dict(bad_schema[0]["payload"], schema="candidate-history/0")
        self.assertEqual(history.STATUS_ABSENT, self._status(entries)["status"])
        self.assertEqual(history.STATUS_OK, self._status(entries + comp)["status"])
        broken = self._status(entries + bad_schema)
        self.assertEqual(history.STATUS_BROKEN, broken["status"])
        self.assertEqual([CANDIDATES[0]], [item["candidate_id"] for item in broken["broken"]])
        self.assertIn("candidate-history/0", broken["broken"][0]["reason"])

    def test_a_declared_count_that_does_not_match_the_payload_is_refused(self):
        entries = scene_entries()
        comp = [dict(row) for row in compaction_at(entries, HORIZON - dt.timedelta(days=1))]
        comp[1]["payload"] = dict(comp[1]["payload"], absorbed=99)
        broken = self._status(entries + comp)
        self.assertEqual(history.STATUS_BROKEN, broken["status"])
        self.assertIn("absorbed=99", broken["broken"][0]["reason"])

    def test_a_compaction_that_is_not_a_faithful_prefix_is_refused_not_preferred(self):
        entries = scene_entries()
        comp = [dict(row) for row in compaction_at(entries, HORIZON - dt.timedelta(days=1))]
        payload = dict(comp[0]["payload"])
        dropped = list(payload["transitions"])[1:]
        comp[0]["payload"] = dict(payload, transitions=dropped, absorbed=len(dropped))
        with TemporaryDirectory() as td:
            doc = rf_read.latest(build(Path(td), entries + comp, "scene"))
            plain = rf_read.latest(build(Path(td), entries, "plain"))
        block = doc["history_compaction"]
        self.assertEqual(history.STATUS_BROKEN, block["status"])
        self.assertIn("faithful prefix", block["broken"][0]["reason"])
        #: ОТКАЗ не выдумывает историю и не теряет её: ответ ровно тот, что был БЕЗ лекарства.
        self.assertEqual(reasons_of(plain), reasons_of(doc))


class TheWriterAndItsTact(unittest.TestCase):
    """У записи обязан быть ПИСАТЕЛЬ и ТАКТ — иначе это вид, которого никто не пишет."""

    def test_the_writer_records_once_per_candidate_then_sits_still_inside_the_tact(self):
        entries = scene_entries()
        with TemporaryDirectory() as td:
            data = build(Path(td), entries, "scene")
            first = history.compact(data, now=HORIZON + dt.timedelta(minutes=5))
            second = history.compact(data, now=HORIZON + dt.timedelta(minutes=10))
        self.assertEqual(sorted(CANDIDATES), sorted(first["written"]))
        self.assertEqual([], second["written"])
        self.assertEqual(sorted(CANDIDATES), sorted(second["already_current"]))

    def test_a_tact_later_the_writer_refreshes_so_the_row_never_ages_out(self):
        entries = scene_entries()
        with TemporaryDirectory() as td:
            data = build(Path(td), entries, "scene")
            history.compact(data, now=HORIZON + dt.timedelta(minutes=5))
            later = history.compact(data, now=HORIZON + dt.timedelta(days=1, minutes=5))
        self.assertEqual(sorted(CANDIDATES), sorted(later["written"]))

    def test_a_grown_history_is_recorded_inside_the_tact_too(self):
        entries = scene_entries()
        with TemporaryDirectory() as td:
            data = build(Path(td), entries, "scene")
            history.compact(data, now=HORIZON + dt.timedelta(minutes=5))
            ledger = ledger_for(data)
            ledger.append("transition",
                          ["transition", CANDIDATES[0], None, contract.SUPERSEDED, "x"],
                          {"candidate_id": CANDIDATES[0], "from_state": contract.REJECTED,
                           "gate_ref": None, "reason": "later", "to_state": contract.SUPERSEDED},
                          _iso(HORIZON + dt.timedelta(minutes=6)))
            grown = history.compact(data, now=HORIZON + dt.timedelta(minutes=7))
        self.assertEqual([CANDIDATES[0]], grown["written"])
        self.assertEqual(sorted(CANDIDATES[1:]), sorted(grown["already_current"]))

    def test_a_second_write_in_the_SAME_second_is_its_own_outcome_not_a_crash(self):
        """Ключ строки несёт момент: столкновение — четвёртый исход, а не падение прогона.

        И не «уже свеж»: история в этом случае как раз НЕ записана, и назвать её
        записанной значило бы потерять ровно то, ради чего пишется строка.
        """
        entries = scene_entries()
        same = HORIZON + dt.timedelta(minutes=5)
        with TemporaryDirectory() as td:
            data = build(Path(td), entries, "scene")
            first = history.compact(data, now=same)
            ledger = ledger_for(data)
            ledger.append("transition",
                          ["transition", CANDIDATES[0], None, contract.SUPERSEDED, "y"],
                          {"candidate_id": CANDIDATES[0], "from_state": contract.REJECTED,
                           "gate_ref": None, "reason": "same second", "to_state": contract.SUPERSEDED},
                          _iso(same))
            second = history.compact(data, now=same)
        self.assertEqual(sorted(CANDIDATES), sorted(first["written"]))
        self.assertEqual([CANDIDATES[0]], second["key_collision"])
        self.assertEqual([], second["written"])
        self.assertNotIn(CANDIDATES[0], second["already_current"])

    def test_the_writer_refuses_a_candidate_whose_compaction_cannot_be_stood_behind(self):
        entries = scene_entries()
        comp = [dict(row) for row in compaction_at(entries, HORIZON - dt.timedelta(days=1))]
        comp[0]["payload"] = dict(comp[0]["payload"], absorbed=99)
        with TemporaryDirectory() as td:
            data = build(Path(td), entries + comp, "scene")
            report = history.compact(data, now=HORIZON + dt.timedelta(minutes=5))
            code = history.main(["--data-dir", str(data), "--json"])
        self.assertEqual([CANDIDATES[0]], [item["candidate_id"] for item in report["refused"]])
        self.assertNotIn(CANDIDATES[0], report["written"])
        self.assertEqual(1, code)


class TheInstrumentSynthesisIsPerMoment(unittest.TestCase):
    """Fail-OPEN, которого прибор обязан избежать: уплотнение не знает своего будущего."""

    def test_a_row_written_a_tact_ago_carries_no_transition_newer_than_itself(self):
        entries = scene_entries()
        extra = _transition(CANDIDATES[0], contract.REJECTED, contract.SUPERSEDED,
                            "very late", HORIZON - dt.timedelta(hours=1))
        entries = entries + [extra]
        early = compaction_at(entries, HORIZON - dt.timedelta(days=1))
        late = compaction_at(entries, HORIZON)
        early_reasons = [item["payload"]["reason"]
                         for row in early if row["payload"]["candidate_id"] == CANDIDATES[0]
                         for item in row["payload"]["transitions"]]
        late_reasons = [item["payload"]["reason"]
                        for row in late if row["payload"]["candidate_id"] == CANDIDATES[0]
                        for item in row["payload"]["transitions"]]
        self.assertNotIn("very late", early_reasons)
        self.assertIn("very late", late_reasons)

    def test_the_scene_builder_asks_the_recipe_at_every_grid_moment(self):
        entries = scene_entries()
        stamps = [lwd._parse_at(entry["at"]) for entry in entries]
        asked: List[dt.datetime] = []

        def rows_for_moment(moment):
            asked.append(moment)
            return []

        scene, injected = rp.build_scene_entries(entries, stamps, [], 1, HORIZON,
                                                 stamps[0],
                                                 rows_for_moment=rows_for_moment)
        self.assertEqual(len(entries), len(scene))
        self.assertEqual(0, injected)
        self.assertEqual(sorted(asked, reverse=True), asked)
        self.assertGreaterEqual(len(asked), 4)


class TheCensusSeesTheWindowWithItsOwnNumber(unittest.TestCase):
    """Приёмка карточки `inbox-rost-lenty-lechitsya-tolko-strokoi-uplot`, машинная."""

    def _measure(self, recipes):
        entries = scene_entries()
        with TemporaryDirectory() as td:
            data = build(Path(td), entries, "scene")
            return rp.measure(data, now=NOW, recipes=recipes, windows=LADDER)

    def test_the_compaction_recipe_opens_a_window_and_the_finding_disappears(self):
        doc = self._measure(rp.RECIPES)
        rows = {row["recipe"]: row for row in doc["rows"]}
        compaction = rows["snapshot+evidence+compaction"]
        self.assertTrue(compaction["compaction"])
        self.assertTrue(compaction["answer_neutral"])
        self.assertIsNotNone(compaction["safe_window_days"])
        self.assertNotIn(rp.FINDING_NO_RECIPE,
                         [finding["kind"] for finding in doc["findings"]])
        self.assertEqual("snapshot+evidence+compaction", doc["cheapest_opener"])

    def test_a_recipe_bringing_only_the_compaction_is_not_a_ZERO_recipe(self):
        """Дыра покрытия, найденная мутацией 19/21 и закрытая здесь.

        `is_zero` решает, проверять ли рецепт контролем НЕЙТРАЛЬНОСТИ. Рецепт,
        приносящий ТОЛЬКО синтезируемый вид, при забытом `synthesised_kinds` в
        `is_zero` считался бы нулевым — то есть не проверялся бы вовсе и всё равно
        попадал бы в «самый дешёвый, открывающий окно»: рекомендация без проверки.
        """
        only = rp.Recipe("compaction-only", cadence_days=1,
                         synthesised_kinds=(rp.COMPACTION_KIND,),
                         note="только уплотнение, без пересъёмки описания")
        self.assertFalse(only.is_zero)
        doc = self._measure((rp.RECIPES[0], only))
        row = {r["recipe"]: r for r in doc["rows"]}["compaction-only"]
        self.assertIsNotNone(row["answer_neutral"],
                             "контроль нейтральности не прогонялся для рецепта-лекарства")

    def test_without_that_recipe_the_same_scene_still_has_no_window_at_all(self):
        """ПРОТИВОПОЛОЖНЫЙ вердикт: до ADR-795 находка стояла, и стояла верно."""
        before = tuple(recipe for recipe in rp.RECIPES if not recipe.compaction)
        doc = self._measure(before)
        self.assertIn(rp.FINDING_NO_RECIPE, [finding["kind"] for finding in doc["findings"]])
        self.assertIsNone(doc["cheapest_opener"])


class TheMedicineDeductionDoesNotSilenceARealDrift(unittest.TestCase):
    """Сторож вычета: вычтено ИМЯ лекарства, и только оно."""

    def test_a_compaction_that_multiplies_the_reasons_is_still_caught(self):
        entries = scene_entries()
        original = rp.compaction_rows_at

        def doubling(entries_, stamps_, moment, live):
            rows = original(entries_, stamps_, moment, live)
            out = []
            for row in rows:
                payload = dict(row["payload"])
                payload["transitions"] = list(payload["transitions"]) * 2
                payload["absorbed"] = len(payload["transitions"])
                out.append(dict(row, payload=payload))
            return out

        with TemporaryDirectory() as td:
            data = build(Path(td), entries, "scene")
            rp.compaction_rows_at = doubling
            try:
                doc = rp.measure(data, now=NOW, recipes=rp.RECIPES, windows=LADDER)
            finally:
                rp.compaction_rows_at = original
        row = {r["recipe"]: r for r in doc["rows"]}["snapshot+evidence+compaction"]
        self.assertFalse(row["answer_neutral"])
        self.assertGreater(row["answer_drifted_leaves"], 0)
        self.assertIn(rp.FINDING_NOT_NEUTRAL, [f["kind"] for f in doc["findings"]])

    def test_a_reading_model_without_the_block_is_NOT_MEASURED_not_a_clean_pass(self):
        """Вычет ничего — третий исход, а не зелёный вердикт."""
        entries = scene_entries()
        original = lwd.answer_leaves

        def stripped(data_dir, now, undeclared=None):
            answer = original(data_dir, now, undeclared=undeclared)
            return {path: value for path, value in answer.items()
                    if not path.startswith(rp.MEDICINE_PRESENCE_PREFIX)}

        with TemporaryDirectory() as td:
            data = build(Path(td), entries, "scene")
            lwd.answer_leaves = stripped
            try:
                doc = rp.measure(data, now=NOW, recipes=rp.RECIPES, windows=LADDER)
            finally:
                lwd.answer_leaves = original
        self.assertFalse(doc["measured"])
        self.assertIn("вычет имени лекарства", doc["reason"])


def calls_inside(source: str, function: str, receiver: str, attribute: str) -> bool:
    """Зовёт ли тело ``function`` вызов ``receiver.attribute(...)`` — по AST, не подстрокой."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name != function:
            continue
        for inner in ast.walk(node):
            if (isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == attribute
                    and isinstance(inner.func.value, ast.Name)
                    and inner.func.value.id == receiver):
                return True
    return False


class TheWriterIsWiredIntoTheDailyRun(unittest.TestCase):
    """Вид записи БЕЗ писателя — это вид, которого никто не пишет.

    Что здесь меряется и чего НЕ меряется, сказано вслух: это ПРОВОДКА (зовёт ли
    дневной прогон писателя и попадает ли его отчёт в ленту), а не поведение —
    ``run.run_once`` поднимает живые сканеры и в батарее не запускается ни разу.
    Поведение самого ``history.compact`` измерено ВЫШЕ по исходу, на настоящей
    ленте. Проводка мерится AST, а не подстрокой: закомментированный вызов и
    строка в докстринге подстрокой неотличимы от вызова.
    """

    def test_run_once_calls_the_compaction_writer_and_records_its_report(self):
        source = Path(run_mod.__file__).read_text(encoding="utf-8")
        self.assertTrue(calls_inside(source, "run_once", "history", "compact"))
        self.assertIn('"history_compaction": compaction,', source)

    def test_the_same_check_says_NO_for_a_body_without_the_call(self):
        """ПРОТИВОПОЛОЖНЫЙ вердикт — иначе проверка зелена на любом файле."""
        self.assertFalse(calls_inside(
            "def run_once(x):\n    # history.compact(x)\n    return x\n",
            "run_once", "history", "compact"))
        self.assertFalse(calls_inside(
            "def other():\n    history.compact(1)\n", "run_once", "history", "compact"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
