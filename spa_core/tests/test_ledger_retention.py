"""Положительные контроли ОТРЕЗАНИЯ ленты как ПЕРЕНОСА (ADR-797, заказ G795 п. 1).

Каждый тест ниже — вопрос, на который прибор обязан отвечать ПО-РАЗНОМУ в двух сценах;
«зелёный на одной сцене» не доказывает ничего (`.claude/rules/acceptance.md`, п. 3).
Сцены — НАСТОЯЩИЕ ленты, собранные кодом самой ленты (`lwd.rechain`), и ответ читается
НАСТОЯЩИМИ объявленными видами (`research_factory.read.latest` / `.cio_view`): предмет
правки — ответ модели, и заглушка отвечала бы на другой вопрос.

Два свойства, которые здесь охраняются в ПРОТИВОПОЛОЖНЫЕ стороны, и оба нужны:

* объявленный перенос префикса делает горячий файл проверяемым (цепь сходится от якоря);
* МОЛЧАЛИВОЕ усечение по-прежнему ломает `verify`, как ломало всегда.

Потеряй одно — и либо перенос невозможен, либо порча ленты становится невидимой.

# FROZEN-DATE-OK: injected-clock — якорь сцены ``ANCHOR`` литерал, и от него вычислены ВСЕ
# отметки строк; момент замера приходит аргументом (``retention.cut(..., now=NOW)``,
# ``history.compact(..., now=…)``, ``rf_read.cio_view(..., NOW)``). Стенных часов не читает
# ни одна сторона вердикта.
"""

from __future__ import annotations

import datetime as dt
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List, Optional

from spa_core.monitoring import ledger_window_dependency_census as lwd
from spa_core.research_factory import contract, history, retention
from spa_core.research_factory import read as rf_read
from spa_core.research_factory._common import ledger_for
from spa_core.utils.hash_ledger import GENESIS, HashLedger, LedgerError

ANCHOR = dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc)
SPAN_DAYS = 6
HORIZON = ANCHOR + dt.timedelta(days=SPAN_DAYS - 1, hours=1)
NOW = ANCHOR + dt.timedelta(days=SPAN_DAYS - 1, hours=2)
CANDIDATES = ("cand0", "cand1", "cand2")
KEEP_DAYS = 3


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


def scene_entries(*, resnapshot_daily: bool = True) -> List[dict]:
    """Шесть суток ленты.

    ``resnapshot_daily=True`` — описание кандидата переснимается КАЖДЫЙ день: та сцена, в
    которой лекарство ADR-795 полное и отрезание обязано стать возможным.
    ``False`` — описание записано ОДИН раз, в первый день: сцена ЖИВОЙ ленты 24.10, где у
    36 из 100 кандидатов свежайший снимок старше окна, и отрезание обязано быть ОТКАЗАНО.
    """
    entries: List[dict] = []
    for day in range(SPAN_DAYS):
        at = ANCHOR + dt.timedelta(days=day)
        if resnapshot_daily or day == 0:
            for index, cid in enumerate(CANDIDATES):
                entries.append(_snapshot(cid, day, at + dt.timedelta(minutes=index)))
        if day in (0, 1):
            for index, cid in enumerate(CANDIDATES):
                frm = None if day == 0 else contract.DISCOVERED
                to = contract.DISCOVERED if day == 0 else contract.REJECTED
                entries.append(_transition(cid, frm, to, f"reason-d{day}-{cid}",
                                           at + dt.timedelta(minutes=30 + index)))
        entries.append(_run_row(day, at + dt.timedelta(hours=1)))
    return entries


def build(root: Path, entries: List[dict], name: str = "scene") -> Path:
    data = Path(root) / name / "data"
    ordered = sorted(entries, key=lambda entry: (lwd._parse_at(entry["at"]), entry["kind"]))
    lwd.rechain(ordered, data)
    ledger_for(data).invalidate_cache()
    return data


def with_compaction(data: Path) -> dict:
    """Позвать НАСТОЯЩЕГО писателя уплотнения — не синтез прибора."""
    report = history.compact(data, now=HORIZON)
    ledger_for(data).invalidate_cache()
    return report


def hot_bytes(data: Path) -> bytes:
    return ledger_for(data).ledger_path().read_bytes()


# ── 1. объявление и его отсутствие — ДВА разных утверждения ──────────────────────────────────


class TheDeclarationIsWhatMakesATruncatedLedgerVerifiable(unittest.TestCase):

    def test_an_untouched_ledger_says_there_is_no_truncation(self):
        with TemporaryDirectory() as td:
            data = build(Path(td), scene_entries())
            verdict = ledger_for(data).verify()
        self.assertTrue(verdict["ok"])
        self.assertEqual(0, verdict["truncated_through"])
        self.assertEqual("absent", verdict["truncation"])

    def test_a_SILENT_head_truncation_still_breaks_the_chain(self):
        """Звено, потеря которого сделала бы порчу ленты невидимой."""
        with TemporaryDirectory() as td:
            data = build(Path(td), scene_entries())
            led = ledger_for(data)
            lines = led.ledger_path().read_text(encoding="utf-8").splitlines(keepends=True)
            led.ledger_path().write_text("".join(lines[5:]), encoding="utf-8")
            led.invalidate_cache()
            verdict = led.verify()
        self.assertFalse(verdict["ok"])
        self.assertEqual("chain", verdict["reason"])

    def test_a_declaration_whose_prefix_is_STILL_PRESENT_is_pending_not_broken(self):
        """Смерть процесса между объявлением и подменой файла: состояние ИСПРАВНО и НАЗВАНО."""
        with TemporaryDirectory() as td:
            data = build(Path(td), scene_entries())
            led = ledger_for(data)
            rows = led.read_all()
            led.truncation_path().write_text(json.dumps(
                {"schema": retention.TRUNCATION_SCHEMA, "through_seq": rows[4]["seq"],
                 "through_entry_hash": rows[4]["entry_hash"], "rows_archived": 5,
                 "archive": "archive/none.jsonl"}), encoding="utf-8")
            led.invalidate_cache()
            verdict = led.verify()
        self.assertTrue(verdict["ok"], verdict)
        self.assertEqual("pending", verdict["truncation"])
        self.assertEqual(0, verdict["truncated_through"])

    def test_a_declaration_that_does_not_line_up_is_a_NAMED_break(self):
        with TemporaryDirectory() as td:
            data = build(Path(td), scene_entries())
            led = ledger_for(data)
            lines = led.ledger_path().read_text(encoding="utf-8").splitlines(keepends=True)
            rows = led.read_all()
            led.ledger_path().write_text("".join(lines[5:]), encoding="utf-8")
            led.truncation_path().write_text(json.dumps(
                {"schema": retention.TRUNCATION_SCHEMA, "through_seq": rows[4]["seq"],
                 "through_entry_hash": GENESIS, "rows_archived": 5,
                 "archive": "archive/none.jsonl"}), encoding="utf-8")
            led.invalidate_cache()
            verdict = led.verify()
        self.assertFalse(verdict["ok"])
        self.assertEqual("truncation_declaration_mismatch", verdict["reason"])
        self.assertEqual("mismatch", verdict["truncation"])

    def test_an_ANCHOR_that_disagrees_with_the_declaration_is_a_break(self):
        """Якорь — единственное, что остаётся доказательством префикса после переноса.

        Этот тест рвёт ТОЛЬКО его: горячий файл и объявление согласны между собой
        (первая горячая запись ссылается на объявленный хеш), а якорь на той же `seq`
        говорит другое — то есть префикс переписан, а объявление подогнано. Без сверки с
        якорем `verify` принял бы такую ленту, и мутационный прибор нашёл эту дыру в
        тестах цикла #920 до доставки.
        """
        with TemporaryDirectory() as td:
            data = build(Path(td), scene_entries())
            with_compaction(data)
            report = retention.cut(data, now=NOW, keep_days=KEEP_DAYS, apply=True)
            self.assertTrue(report["applied"], report)
            led = ledger_for(data)
            anchors = led.anchors_path().read_text(encoding="utf-8").splitlines()
            forged = []
            for line in anchors:
                row = json.loads(line)
                if row["seq"] == report["through_seq"]:
                    row["entry_hash"] = GENESIS
                forged.append(json.dumps(row, sort_keys=True))
            led.anchors_path().write_text("\n".join(forged) + "\n", encoding="utf-8")
            led.invalidate_cache()
            verdict = led.verify()
        self.assertFalse(verdict["ok"], verdict)
        self.assertEqual("truncation_declaration_mismatch", verdict["reason"])

    def test_a_declaration_at_the_WRONG_DEPTH_is_a_declaration_break_not_a_chain_break(self):
        """Глубина объявления и глубина файла — ОДНО утверждение, и расхождение в нём
        обязано называться своим именем: `chain` сказал бы «лента порчена», тогда как
        порчено ОБЪЯВЛЕНИЕ, и чинить надо разное."""
        with TemporaryDirectory() as td:
            data = build(Path(td), scene_entries())
            with_compaction(data)
            led = ledger_for(data)
            rows = led.read_all()
            lines = led.ledger_path().read_text(encoding="utf-8").splitlines(keepends=True)
            #: объявляем через 5-ю запись, а файл срезаем по 8-ю — якорь при этом СОГЛАСЕН
            led.ledger_path().write_text("".join(lines[8:]), encoding="utf-8")
            led.truncation_path().write_text(json.dumps(
                {"schema": retention.TRUNCATION_SCHEMA, "through_seq": rows[4]["seq"],
                 "through_entry_hash": rows[4]["entry_hash"], "rows_archived": 5,
                 "archive": "archive/none.jsonl"}), encoding="utf-8")
            led.invalidate_cache()
            verdict = led.verify()
        self.assertFalse(verdict["ok"], verdict)
        self.assertEqual("truncation_declaration_mismatch", verdict["reason"])

    def test_an_anchor_beyond_the_hot_tail_is_still_caught_after_a_cut(self):
        """Починка хвостовой проверки не имеет права ослепить её: обрезанный КОНЕЦ
        по-прежнему находится, хотя начало теперь законно не первое."""
        with TemporaryDirectory() as td:
            data = build(Path(td), scene_entries())
            with_compaction(data)
            report = retention.cut(data, now=NOW, keep_days=KEEP_DAYS, apply=True)
            self.assertTrue(report["applied"], report)
            led = ledger_for(data)
            lines = led.ledger_path().read_text(encoding="utf-8").splitlines(keepends=True)
            led.ledger_path().write_text("".join(lines[:-1]), encoding="utf-8")
            led.invalidate_cache()
            verdict = led.verify()
        self.assertFalse(verdict["ok"])
        self.assertEqual("ledger_truncated", verdict["reason"])


# ── 2. перенос, а не удаление ────────────────────────────────────────────────────────────────


class TheCutIsAMoveAndTheAnswerDoesNotChange(unittest.TestCase):

    def test_archive_plus_hot_reproduces_the_original_ledger_bit_for_bit(self):
        with TemporaryDirectory() as td:
            data = build(Path(td), scene_entries())
            with_compaction(data)
            before = hot_bytes(data)
            answers_before, unmeasured = retention.view_answers(data, NOW)
            self.assertEqual([], unmeasured)
            report = retention.cut(data, now=NOW, keep_days=KEEP_DAYS, apply=True)
            self.assertTrue(report["applied"], report)
            led = ledger_for(data)
            archive = (led.root() / report["archive"]).read_bytes()
            after_hot = hot_bytes(data)
            self.assertEqual(before, archive + after_hot)
            self.assertLess(len(after_hot), len(before))
            verdict = led.verify()
            answers_after, unmeasured_after = retention.view_answers(data, NOW)
        self.assertTrue(verdict["ok"], verdict)
        self.assertEqual("applied", verdict["truncation"])
        self.assertEqual(report["through_seq"], verdict["truncated_through"])
        self.assertEqual([], unmeasured_after)
        self.assertEqual(answers_before, answers_after)

    def test_the_declaration_is_written_BEFORE_the_hot_file_is_replaced(self):
        """Порядок шагов — утверждение, и у него обязан быть контроль.

        Смерть процесса между подменой горячего файла и записью объявления оставила бы
        усечённый файл БЕЗ объявления, то есть молчаливое усечение, которое `verify`
        обязан называть порчей. Обратный порядок (объявление первым) оставляет ленту,
        которую `verify` называет исправной и `pending`. До этого теста порядок держался
        на прозе: мутационный прибор снял первую запись объявления, и батарея осталась
        ЗЕЛЁНОЙ.
        """
        from unittest import mock
        written: List[Path] = []
        real = retention._atomic_bytes

        def recording(path, data):
            written.append(Path(path).resolve())
            return real(path, data)

        with TemporaryDirectory() as td:
            data = build(Path(td), scene_entries())
            with_compaction(data)
            led = ledger_for(data)
            root = led.root().resolve()
            with mock.patch.object(retention, "_atomic_bytes", recording):
                report = retention.cut(data, now=NOW, keep_days=KEEP_DAYS, apply=True)
        self.assertTrue(report["applied"], report)
        #: Только записи в ЖИВУЮ ленту: сцена замера пишет объявление с тем же ИМЕНЕМ в
        #: своём одноразовом каталоге, и сверка по имени читала бы её запись вместо
        #: нашей — первая версия этого теста ровно так и ослепла (мутация 13 выжила).
        order = [p.name for p in written if p.parent == root]
        declaration = led.truncation_path().name
        hot = led.ledger_name
        self.assertIn(declaration, order)
        self.assertIn(hot, order)
        self.assertLess(order.index(declaration), order.index(hot),
                        f"объявление обязано быть записано ДО подмены горячего файла: {order}")

    def test_a_plan_that_no_longer_matches_the_ledger_is_REFUSED_under_the_lock(self):
        """Между ЗАМЕРОМ и ПЕРЕНОСОМ лента может измениться, и тогда переносится не то,
        что мерили. Сверка стои́т под файловым замком и сравнивает `seq` последней
        отрезаемой строки с тем, который назвал замер; без неё перенос молча увёз бы
        другой префикс. Дыру в этом месте нашёл мутационный прибор, не глаз.
        """
        from unittest import mock
        with TemporaryDirectory() as td:
            data = build(Path(td), scene_entries())
            with_compaction(data)
            real_propose = retention.propose

            def stale_plan(root, now, keep_days=retention.KEEP_DAYS):
                plan = dict(real_propose(root, now, keep_days))
                #: «замер видел ленту на одну строку короче» — ровно то состояние, в
                #: котором план перестал описывать файл
                plan["through_seq"] = plan["through_seq"] + 1
                return plan

            with mock.patch.object(retention, "propose", stale_plan):
                with self.assertRaises(retention.CutRefused) as caught:
                    retention.cut(data, now=NOW, keep_days=KEEP_DAYS, apply=True)
            self.assertIn("лента изменилась", str(caught.exception))
            self.assertFalse((ledger_for(data).root() / "archive").exists())

    def test_the_compaction_status_survives_the_cut(self):
        """Приёмка заказа дословно: `history_compaction.status` остаётся `OK`."""
        with TemporaryDirectory() as td:
            data = build(Path(td), scene_entries())
            with_compaction(data)
            before = rf_read.latest(data)["history_compaction"]
            retention.cut(data, now=NOW, keep_days=KEEP_DAYS, apply=True)
            ledger_for(data).invalidate_cache()
            after = rf_read.latest(data)["history_compaction"]
        self.assertEqual(history.STATUS_OK, before["status"])
        self.assertEqual(before, after)


# ── 3. гейт — ОТВЕТ, а не перечень видов записей ─────────────────────────────────────────────


class TheGateIsTheAnswerItself(unittest.TestCase):

    def test_without_the_daily_resnapshot_the_cut_is_REFUSED_and_the_view_is_named(self):
        """Сцена живой ленты 24.10: уплотнение ЕСТЬ, а описание кандидата не переснимается.

        Строка уплотнения — ОДНА из четырёх составляющих рецепта, измерившего окно; трёх
        других писателей не существует, и прибор обязан это ЗАМЕТИТЬ, а не поверить ADR.
        """
        with TemporaryDirectory() as td:
            data = build(Path(td), scene_entries(resnapshot_daily=False))
            with_compaction(data)
            with self.assertRaises(retention.CutRefused) as caught:
                retention.cut(data, now=NOW, keep_days=KEEP_DAYS, apply=True)
        message = str(caught.exception)
        self.assertIn("research_factory", message)
        diagnosis = caught.exception.report.get("diagnosis") or {}
        by_kind = diagnosis.get("by_kind") or {}
        self.assertEqual(len(CANDIDATES),
                         by_kind["candidate_snapshot"]["newest_older_than_window"])

    def test_a_refusal_leaves_the_ledger_untouched(self):
        with TemporaryDirectory() as td:
            data = build(Path(td), scene_entries(resnapshot_daily=False))
            with_compaction(data)
            before = hot_bytes(data)
            with self.assertRaises(retention.CutRefused):
                retention.cut(data, now=NOW, keep_days=KEEP_DAYS, apply=True)
            self.assertEqual(before, hot_bytes(data))
            self.assertFalse(ledger_for(data).truncation_path().exists())

    def test_a_broken_chain_is_NOT_MEASURED_never_nothing_to_cut(self):
        with TemporaryDirectory() as td:
            data = build(Path(td), scene_entries())
            led = ledger_for(data)
            lines = led.ledger_path().read_text(encoding="utf-8").splitlines(keepends=True)
            led.ledger_path().write_text("".join(lines[5:]), encoding="utf-8")
            led.invalidate_cache()
            with self.assertRaises(retention.CutRefused) as caught:
                retention.cut(data, now=NOW, keep_days=KEEP_DAYS, apply=True)
        self.assertIn("НЕ ИЗМЕРЕНО", str(caught.exception))

    def test_everything_inside_the_window_is_measured_zero_not_a_refusal(self):
        with TemporaryDirectory() as td:
            data = build(Path(td), scene_entries())
            report = retention.cut(data, now=NOW, keep_days=90, apply=True)
        self.assertFalse(report["applied"])
        self.assertEqual(0, report["propose"]["cut_rows"])
        self.assertEqual("nothing_older_than_window", report["measurement"]["reason"])
        self.assertTrue(report["measurement"]["measured"])

    def test_measure_of_zero_rows_is_measured_zero_never_safe(self):
        """«Резать нечего» и «резать можно» — ДВА ответа, и первый не разрешает второго."""
        with TemporaryDirectory() as td:
            data = build(Path(td), scene_entries())
            verdict = retention.measure(data, 0, NOW)
        self.assertFalse(verdict["safe"])
        self.assertTrue(verdict["measured"])
        self.assertIn("measured_zero", verdict["reason"])

    def test_measure_without_a_declared_view_is_NOT_MEASURED_never_safe(self):
        with TemporaryDirectory() as td:
            data = build(Path(td), scene_entries())
            verdict = retention.measure(data, 5, NOW, ledger_id="no_such_ledger")
        self.assertFalse(verdict["safe"])
        self.assertFalse(verdict["measured"])
        self.assertIn("НЕ ИЗМЕРЕНО", verdict["reason"])

    def test_a_view_that_DIES_on_the_truncated_ledger_is_NOT_MEASURED_never_safe(self):
        """Третий исход на ДАЛЬНЕЙ стороне замера, и он отличается от ближней.

        Читатель, который на полной ленте отвечает, а на усечённой падает, — не
        гипотеза: ровно это случилось с сериализатором самого цикла #920 (на усечённой
        ленте ответ несёт отображение с ключами `str` и `None` одновременно). Падение
        читателя ПОСЛЕ отрезания обязано быть НЕ ИЗМЕРЕНО, а не «ответ изменился» и уж
        тем менее не «согласны». Дыру в этом месте нашёл мутационный прибор, не глаз.
        """
        from unittest import mock
        from spa_core.monitoring import ledger_parse_census as census
        real = census.resolve_view

        def brittle(member):
            fn, reason = real(member)
            if fn is None:
                return fn, reason

            def guarded(data_dir, *a, **kw):
                led = ledger_for(Path(data_dir))
                led.invalidate_cache()
                rows = led.read_all()
                if rows and rows[0].get("seq") != 1:
                    raise RuntimeError("этот читатель не переживает усечения")
                return fn(Path(data_dir), *a, **kw)

            return guarded, None

        with TemporaryDirectory() as td:
            data = build(Path(td), scene_entries())
            with_compaction(data)
            with mock.patch.object(census, "resolve_view", brittle):
                verdict = retention.measure(data, 5, NOW)
        self.assertFalse(verdict["safe"])
        self.assertFalse(verdict["measured"])
        self.assertIn("после отрезания", verdict["reason"])
        self.assertTrue(verdict["unmeasured"])

    def test_the_bisect_names_both_ends_of_the_measurement(self):
        with TemporaryDirectory() as td:
            data = build(Path(td), scene_entries(resnapshot_daily=False))
            verdict = retention.largest_safe_cut(data, NOW)
        self.assertEqual(0, verdict["largest_safe_cut_rows"])
        self.assertEqual(1, verdict["first_unsafe_cut_rows"])
        self.assertTrue(verdict["probes"])


# ── 4. идемпотентность записи переживает перенос ─────────────────────────────────────────────


class IdempotencySurvivesTheCut(unittest.TestCase):

    def test_an_archived_key_is_still_FOUND_and_append_is_still_idempotent(self):
        with TemporaryDirectory() as td:
            data = build(Path(td), scene_entries())
            with_compaction(data)
            led = ledger_for(data)
            archived = led.read_all()[0]
            report = retention.cut(data, now=NOW, keep_days=KEEP_DAYS, apply=True)
            self.assertTrue(report["applied"], report)
            led.invalidate_cache()
            self.assertIsNone(next((e for e in led.read_all()
                                    if e["seq"] == archived["seq"]), None))
            found = led.find(archived["kind"], archived["key"])
            self.assertIsNotNone(found, "ключ архива обязан находиться")
            self.assertEqual(archived["entry_hash"], found["entry_hash"])
            entry, created = led.append_idempotent(
                archived["kind"], archived["key"], {"different": True}, _iso(NOW))
        self.assertFalse(created, "второй ряд с ключом архива был бы тихой порчей контракта")
        self.assertEqual(archived["entry_hash"], entry["entry_hash"])

    def test_a_declared_truncation_without_its_key_index_REFUSES_to_answer(self):
        """Третий исход: «дубля нет» обязано быть отличимо от «мы не смотрели»."""
        with TemporaryDirectory() as td:
            data = build(Path(td), scene_entries())
            with_compaction(data)
            led = ledger_for(data)
            archived = led.read_all()[0]
            retention.cut(data, now=NOW, keep_days=KEEP_DAYS, apply=True)
            led.truncation_keys_path().unlink()
            led.invalidate_cache()
            with self.assertRaises(LedgerError) as caught:
                led.find(archived["kind"], archived["key"])
        self.assertIn("key index is missing", str(caught.exception))

    def test_a_key_index_pointing_at_the_wrong_row_is_NAMED_not_trusted(self):
        with TemporaryDirectory() as td:
            data = build(Path(td), scene_entries())
            with_compaction(data)
            led = ledger_for(data)
            rows = led.read_all()
            archived, neighbour = rows[0], rows[1]
            retention.cut(data, now=NOW, keep_days=KEEP_DAYS, apply=True)
            path = led.truncation_keys_path()
            doc = json.loads(path.read_text(encoding="utf-8"))
            mine = HashLedger.key_digest(archived["kind"], archived["key"])
            theirs = HashLedger.key_digest(neighbour["kind"], neighbour["key"])
            doc["keys"][mine] = doc["keys"][theirs]
            path.write_text(json.dumps(doc, sort_keys=True), encoding="utf-8")
            led.invalidate_cache()
            with self.assertRaises(LedgerError) as caught:
                led.find(archived["kind"], archived["key"])
        self.assertIn("unfaithful", str(caught.exception))

    def test_no_truncation_means_find_answers_None_without_touching_any_index(self):
        with TemporaryDirectory() as td:
            data = build(Path(td), scene_entries())
            led = ledger_for(data)
            self.assertIsNone(led.find("candidate_snapshot", ["candidate_snapshot", "nope", "x"]))
            self.assertEqual({}, led._archive_index)


# ── 5. свои две двери: канонизатор ответа и перечень видов ───────────────────────────────────


class TheComparisonHasNoBlindSpotOfItsOwn(unittest.TestCase):

    def test_the_canonicaliser_survives_a_mapping_keyed_by_str_AND_None(self):
        """Замер 24.10: на усечённой ленте ответ `read.latest` несёт ровно такой словарь,
        и `json.dumps(sort_keys=True)` на нём ПАДАЕТ. Падение сериализатора неотличимо от
        «ответ изменился», если не различать их намеренно."""
        with self.assertRaises(TypeError):
            json.dumps({"a": 1, None: 2}, sort_keys=True)
        self.assertEqual(retention.canonical({"a": 1, None: 2}),
                         retention.canonical({None: 2, "a": 1}))

    def test_None_and_the_string_None_are_NOT_the_same_key(self):
        self.assertNotEqual(retention.canonical({None: 1}), retention.canonical({"None": 1}))

    def test_both_declared_views_of_this_ledger_are_compared(self):
        ids = [member.id for member in retention.declared_views()]
        self.assertIn("research_factory", ids)
        self.assertIn("research_factory.cio_view", ids)

    def test_a_ledger_with_no_declared_view_is_NOT_MEASURED_never_safe(self):
        with TemporaryDirectory() as td:
            data = build(Path(td), scene_entries())
            answers, unmeasured = retention.view_answers(data, NOW, ledger_id="no_such_ledger")
        self.assertEqual({}, answers)
        self.assertEqual(1, len(unmeasured))
        self.assertIn("НЕ ИЗМЕРЕНО", unmeasured[0]["reason"])


# ── 6. срок хранения — РЕШЕНИЕ, и оно объявлено ──────────────────────────────────────────────


class TheWindowIsADecisionAndTheGateIsNot(unittest.TestCase):

    def test_the_declared_window_leaves_room_for_missed_tacts_of_the_writer(self):
        """Окно, равное такту писателя, не оставляет ни одного пропущенного такта."""
        self.assertGreater(retention.KEEP_DAYS, history.COMPACTION_TACT_DAYS)
        self.assertGreaterEqual(retention.KEEP_DAYS, retention.MEASURED_FLOOR_DAYS)

    def test_a_wider_window_cuts_fewer_rows(self):
        with TemporaryDirectory() as td:
            data = build(Path(td), scene_entries())
            narrow = retention.propose(data, NOW, keep_days=2)
            wide = retention.propose(data, NOW, keep_days=4)
        self.assertGreater(narrow["cut_rows"], wide["cut_rows"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


# ── 7. положительные контроли ПРОБЫ: каждое звено рвётся поимённо ────────────────────────────


def _shim(module, **overrides):
    """Копия модуля как пространство имён с подменёнными именами.

    Нужна потому, что проба обязана ПАДАТЬ на каждом порванном звене, а порвать звено,
    не имея входа, нечем: проверка, никогда не видевшая поломки, — украшение
    (`.claude/rules/deployment.md`, «Проверка сторожа сторожей»).
    """
    import types
    ns = types.SimpleNamespace(**{name: getattr(module, name)
                                  for name in dir(module) if not name.startswith("__")})
    for name, value in overrides.items():
        setattr(ns, name, value)
    return ns


class TheProbeRedensOnEveryBrokenLink(unittest.TestCase):

    def setUp(self):
        from spa_core.monitoring import card_acceptance
        self.ca = card_acceptance

    def test_the_probe_is_green_on_the_whole_contour(self):
        verdict, why = self.ca.PROBES["ledger_cut_moves_and_is_measured"](None)
        self.assertEqual(self.ca.SATISFIED, verdict, why)

    def test_link_1_a_window_equal_to_the_writers_tact_is_named(self):
        broken = self.ca.ledger_retention_links(
            history=_shim(history, COMPACTION_TACT_DAYS=retention.KEEP_DAYS))
        self.assertTrue(any(line.startswith("звено 1") for line in broken), broken)

    def test_link_2_a_verify_that_forgives_silent_truncation_is_named(self):
        from unittest import mock
        real = HashLedger.verify

        def forgiving(self, *a, **kw):
            verdict = real(self, *a, **kw)
            verdict = dict(verdict)
            verdict["ok"] = True
            verdict["reason"] = None
            return verdict

        with mock.patch.object(HashLedger, "verify", forgiving):
            broken = self.ca.ledger_retention_links()
        self.assertTrue(any(line.startswith("звено 2") for line in broken), broken)

    def test_link_3_a_cut_whose_chain_does_not_meet_its_anchor_is_named(self):
        from unittest import mock
        real = HashLedger.verify

        def amnesiac(self, *a, **kw):
            verdict = dict(real(self, *a, **kw))
            if verdict.get("truncation") == "applied":
                verdict["truncation"] = "absent"
            return verdict

        with mock.patch.object(HashLedger, "verify", amnesiac):
            broken = self.ca.ledger_retention_links()
        self.assertTrue(any(line.startswith("звено 3") for line in broken), broken)

    def test_link_4_a_cut_that_DELETES_instead_of_moving_is_named(self):
        def deleting_cut(data_dir, **kw):
            report = retention.cut(data_dir, **kw)
            if report.get("applied"):
                (ledger_for(Path(data_dir)).root() / report["archive"]).write_bytes(b"")
            return report

        broken = self.ca.ledger_retention_links(
            retention=_shim(retention, cut=deleting_cut))
        self.assertTrue(any(line.startswith("звено 4") for line in broken), broken)

    def test_link_5_a_gate_that_never_refuses_is_named(self):
        """ОБРАТНАЯ сторона: прибор, всегда разрешающий, зелен без этого контроля."""
        def permissive_cut(data_dir, **kw):
            try:
                return retention.cut(data_dir, **kw)
            except retention.CutRefused:
                return {"applied": True, "archive": "archive/none.jsonl",
                        "measurement": {"safe": True}, "rows_archived": 0,
                        "through_seq": 0}

        broken = self.ca.ledger_retention_links(
            retention=_shim(retention, cut=permissive_cut))
        self.assertTrue(any("звено 5" in line and "РАЗРЕШЁН" in line for line in broken),
                        broken)

    def test_link_5_a_gate_that_refuses_the_COMPLETE_recipe_is_named(self):
        def always_refusing(data_dir, **kw):
            raise retention.CutRefused("нет")

        broken = self.ca.ledger_retention_links(
            retention=_shim(retention, cut=always_refusing,
                            CutRefused=retention.CutRefused))
        self.assertTrue(any("звено 5" in line for line in broken), broken)

    def test_the_probe_does_NOT_pass_by_substring(self):
        """ADR-333: проба, которую удовлетворяет текст, меряет текст."""
        import inspect
        source = inspect.getsource(self.ca.ledger_retention_links)
        self.assertIn("retention.cut", source)
        self.assertNotIn("read_text().count", source)
