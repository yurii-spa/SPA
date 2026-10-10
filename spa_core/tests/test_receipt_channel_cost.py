"""Батарея прибора «цена КАНАЛА квитанции» — заказ G110 п. 1 (ADR-684).

Литеральных дат в файле нет и быть не может: у прибора часы — ВХОД
(``build_report(..., now=)``), а записи сцен пишет настоящий писатель, то есть их
свежесть берётся ПО ПОСТРОЕНИЮ. Личность процесса тоже не литерал: оси A и B берут
``os.getpid()`` (жив на любом хосте всегда), ось C — чужую живую личность у
``live_other_anchor``, а в герметичных тестах эта личность ПЕРЕДАЁТСЯ аргументом.

Каждый тест — положительный контроль одного звена: порвать звено ⇒ тест краснеет с
НАЗВАННОЙ причиной. Третий исход проверяется отдельно и ДОСЛОВНО по сообщению: иначе
«не измерено» стало бы неотличимо от «прошло», ровно тот дефект, против которого
прибор и написан.
"""
from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timezone
from pathlib import Path

from spa_core.monitoring import receipt_channel_cost as M

ROOT = Path(__file__).resolve().parents[2]

# FROZEN-DATE-OK: injected-clock — литерал ниже есть ЯКОРЬ, и он уезжает входом:
# `build_report(ROOT, now=NOW, ...)` и `M.run(str(scene), now=NOW)`; обе стороны
# закреплены от ОДНОГО якоря (сравнение идёт с `generated_at`, выведенным из него),
# поэтому сдвиг календаря на вердикт не влияет ни одним тестом файла. Сцены осей A–C
# часов не принимают НАМЕРЕННО: их записи пишет настоящий писатель, свежесть у них ПО
# ПОСТРОЕНИЮ, и записка об инъекции там была бы неправдой (ADR-479).
#: Момент-якорь отчёта. Дата здесь ПРЕДМЕТОМ не является — она нужна только чтобы
#: `generated_at` был закреплён; ни одна ось от неё не зависит.
NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def _anchor():
    """Личность сцены: свой живой номер — не литерал."""
    return {"pid": os.getpid(), "start": "тест: личность, живая по построению"}


class _FakeCensus:
    """Читатель-двойник: та же форма ответа, число — по управляющей таблице."""

    JOURNAL_NAME = "session_changes.jsonl"
    _RECEIPT_PREFIX = "[check_card_claim]"

    def __init__(self, *, measured=True, field=M.READER_FIELD):
        self.measured = measured
        self.field = field
        self.seen = []

    def load_journal(self, path):
        if not self.measured:
            return {"measured": False, "reason": "журнала нет (двойник)", "records": []}
        text = Path(path).read_text(encoding="utf-8") if Path(path).exists() else ""
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
        return {"measured": True, "reason": None, "records": records}

    def measure_receipts(self, records, *, now=None, **_kw):
        self.seen.append(len(records))
        receipts = sum(1 for r in records
                       if str(r.get("summary", "")).startswith(self._RECEIPT_PREFIX))
        return {self.field: 0 if receipts else 1, "window_takings": 1,
                "receipts_in_journal": receipts}


class TestReaderLiterals(unittest.TestCase):
    """Приставка и имя журнала берутся У ЧИТАТЕЛЯ, своей копии прибор не держит."""

    def test_prefix_and_journal_come_from_the_reader(self):
        census = M.load_census()
        self.assertEqual(M.receipt_prefix(census), census._RECEIPT_PREFIX)
        self.assertEqual(M.journal_name(census), census.JOURNAL_NAME)

    def test_missing_literal_is_the_third_outcome_not_a_private_copy(self):
        class Bare:
            JOURNAL_NAME = "session_changes.jsonl"
        self.assertIsNone(M.receipt_prefix(Bare()))

        out = M.measure_visibility(ROOT, census=Bare(), anchor=_anchor())
        self.assertFalse(out["measured"])
        self.assertEqual(out["reason"],
                         "у читателя не объявлена приставка квитанции или имя "
                         "журнала — своей копии литерала прибор не держит")


class TestScene(unittest.TestCase):
    """Сцена пишется НАСТОЯЩИМ писателем, и канал отличается РОВНО адресом."""

    def setUp(self):
        self.guard = M._load_guard(ROOT)
        self.announcer = self.guard.load_announcer()

    def _write(self, tmp, channel, ablate=None):
        return M.write_scene(Path(tmp), announcer=self.announcer,
                             prefix="[check_card_claim]",
                             journal="session_changes.jsonl", anchor=_anchor(),
                             channel=channel, ablate=ablate)

    def test_second_file_receipt_lands_beside_the_journal_not_in_it(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            log = self._write(tmp, M.CHANNEL_SECOND_FILE)
            journal = log.read_text(encoding="utf-8")
            side = (Path(tmp) / M.SECOND_FILE_NAME).read_text(encoding="utf-8")
        self.assertNotIn("[check_card_claim]", journal)
        self.assertIn("[check_card_claim]", side)

    def test_journal_channel_carries_the_third_state_verbatim(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            log = self._write(tmp, M.CHANNEL_JOURNAL_STATE)
            rows = [json.loads(line) for line in
                    log.read_text(encoding="utf-8").splitlines() if line.strip()]
        receipt = [r for r in rows
                   if str(r.get("summary", "")).startswith("[check_card_claim]")]
        self.assertEqual(len(receipt), 1)
        # Валидации состояния у писателя НЕТ — это и есть измеренное свойство.
        self.assertEqual(receipt[0]["card_state"], M.STATE_ASKED)

    def test_each_ablation_removes_exactly_one_requirement(self):
        import tempfile
        for ablate, probe in ((M.ABLATE_PREFIX, lambda r: not str(
                r.get("summary", "")).startswith("[check_card_claim]")),
                              (M.ABLATE_SUBJECT, lambda r: "card" not in r),
                              (M.ABLATE_ANCHOR, lambda r: "session_pid" not in r)):
            with self.subTest(ablate=ablate), tempfile.TemporaryDirectory() as tmp:
                log = self._write(tmp, "journal_claim", ablate=ablate)
                rows = [json.loads(line) for line in
                        log.read_text(encoding="utf-8").splitlines() if line.strip()]
                receipt = rows[-1]
                self.assertTrue(probe(receipt), f"отъём `{ablate}` не состоялся: {receipt}")


class TestVisibility(unittest.TestCase):
    """Ось A: канал виден читателю или нет — и контроль обязан РАЗЛИЧАТЬ."""

    def test_real_run_second_file_is_invisible_journal_state_is_not(self):
        out = M.measure_visibility(ROOT, anchor=_anchor())
        self.assertTrue(out["measured"], out["reason"])
        self.assertEqual(out["by_channel"][M.CHANNEL_SECOND_FILE]["outcome"], M.UNSEEN)
        self.assertEqual(out["by_channel"][M.CHANNEL_JOURNAL_STATE]["outcome"], M.SEEN)
        # Различимость — внутри замера, а не в голове автора.
        self.assertNotEqual(out["baseline"], out["control"])

    def test_blind_control_is_the_third_outcome_not_an_invisible_channel(self):
        class Numb(_FakeCensus):
            def measure_receipts(self, records, *, now=None, **_kw):
                # Читатель нечувствителен к квитанции: число всегда одно.
                return {M.READER_FIELD: 1, "window_takings": 1,
                        "receipts_in_journal": 0}

        out = M.measure_visibility(ROOT, census=Numb(), anchor=_anchor())
        self.assertFalse(out["measured"])
        self.assertIn("контроль НЕ РАЗЛИЧАЕТ", out["reason"])
        self.assertIn("было бы утверждением о приборе", out["reason"])

    def test_unreadable_journal_is_named_not_silently_zero(self):
        out = M.measure_visibility(ROOT, census=_FakeCensus(measured=False),
                                   anchor=_anchor())
        self.assertFalse(out["measured"])
        self.assertIn("журнал сцены не разобран", out["reason"])

    def test_missing_reader_field_is_named(self):
        out = M.measure_visibility(ROOT, census=_FakeCensus(field="другое_поле"),
                                   anchor=_anchor())
        self.assertFalse(out["measured"])
        self.assertIn(f"читатель не вернул поле `{M.READER_FIELD}`", out["reason"])

    def test_guard_that_does_not_load_is_the_third_outcome(self):
        def broken(_root):
            raise FileNotFoundError("сторожа нет (контроль)")
        out = M.measure_visibility(ROOT, guard_loader=broken, anchor=_anchor())
        self.assertFalse(out["measured"])
        self.assertIn("читатель или писатель не загружены", out["reason"])


class TestContract(unittest.TestCase):
    """Ось B: контракт канала меряется ОТЪЁМОМ, вердикт выносит сам читатель."""

    def test_real_run_names_all_three_requirements(self):
        out = M.measure_contract(ROOT, anchor=_anchor())
        self.assertTrue(out["measured"], out["reason"])
        self.assertEqual(out["required_fields"], sorted(M.ABLATIONS))
        self.assertEqual(out["optional_fields"], [])
        for field in M.ABLATIONS:
            self.assertEqual(out["by_field"][field]["value"], out["baseline"],
                             f"без `{field}` квитанция всё ещё читается")

    def test_a_reader_blind_to_the_prefix_moves_the_field_out_of_required(self):
        class PrefixBlind(_FakeCensus):
            def measure_receipts(self, records, *, now=None, **_kw):
                # Квитанцией считается ЛЮБАЯ запись с предметом — приставку не смотрит.
                receipts = sum(1 for r in records
                               if r.get("card") and r.get("verified"))
                return {M.READER_FIELD: 0 if receipts else 1,
                        "window_takings": 1, "receipts_in_journal": receipts}

        out = M.measure_contract(ROOT, census=PrefixBlind(), anchor=_anchor())
        self.assertTrue(out["measured"], out["reason"])
        self.assertIn(M.ABLATE_PREFIX, out["optional_fields"])
        self.assertNotIn(M.ABLATE_PREFIX, out["required_fields"])

    def test_full_receipt_that_does_not_move_the_field_is_the_third_outcome(self):
        class Numb(_FakeCensus):
            def measure_receipts(self, records, *, now=None, **_kw):
                return {M.READER_FIELD: 1, "window_takings": 1,
                        "receipts_in_journal": 0}

        out = M.measure_contract(ROOT, census=Numb(), anchor=_anchor())
        self.assertFalse(out["measured"])
        self.assertIn("отнимать у неё поля бессмысленно", out["reason"])


class TestDoor(unittest.TestCase):
    """Ось C: переворачивает ли канал вердикт двери — по каждому каналу отдельно."""

    def test_real_run_third_state_captures_second_file_is_harmless(self):
        out = M.measure_door(ROOT)
        self.assertTrue(out["measured"], out["reason"])
        self.assertEqual(out["verdict_without"], "free")
        self.assertEqual(out["by_channel"][M.CHANNEL_JOURNAL_STATE]["outcome"],
                         "question_becomes_claim")
        # Сцена УМЕЕТ отвечать «безвредно» — иначе её вердикт был бы односторонним.
        self.assertEqual(out["by_channel"][M.CHANNEL_SECOND_FILE]["outcome"], "harmless")

    def test_unmeasured_foreign_identity_refuses_loudly(self):
        out = M.measure_door(ROOT, anchor={"measured": False, "pid": None,
                                           "reason": "ps не ответил (контроль)"})
        self.assertFalse(out["measured"])
        self.assertIn("личность чужой живой сессии НЕ ИЗМЕРЕНА", out["reason"])
        self.assertIn("по неизмеренному номеру запрещено", out["reason"])

    def test_scene_that_is_not_free_refuses_instead_of_claiming_no_harm(self):
        guard = M._load_guard(ROOT)

        class Busy:
            """Дверь-двойник: любая сцена читается как ЗАНЯТАЯ."""
            load_announcer = staticmethod(guard.load_announcer)

            @staticmethod
            def main(argv):
                print(json.dumps({"verdict": "claimed"}))
                return 1

        out = M.measure_door(ROOT, guard_loader=lambda _r: Busy(),
                             anchor={"measured": True, "pid": os.getpid(),
                                     "start": "контроль"})
        self.assertFalse(out["measured"])
        self.assertIn("а не `free`", out["reason"])
        self.assertIn("переворот вопроса в захват нечем измерить", out["reason"])

    def test_self_anchor_scene_refuses_instead_of_measuring_a_self_claim(self):
        guard = M._load_guard(ROOT)

        class Mine:
            load_announcer = staticmethod(guard.load_announcer)
            calls = []

            @staticmethod
            def main(argv):
                Mine.calls.append(argv)
                payload = {"verdict": "free"}
                if len(Mine.calls) > 1:
                    payload["self_claims"] = [{"session": "я"}]
                print(json.dumps(payload))
                return 0

        out = M.measure_door(ROOT, guard_loader=lambda _r: Mine(),
                             anchor={"measured": True, "pid": os.getpid(),
                                     "start": "контроль"})
        self.assertFalse(out["measured"])
        self.assertIn("опознан сторожем как МОЙ", out["reason"])

    def test_verdict_not_produced_is_named(self):
        guard = M._load_guard(ROOT)

        class Mute:
            load_announcer = staticmethod(guard.load_announcer)

            @staticmethod
            def main(argv):
                print(json.dumps({"card": "нет вердикта"}))
                return 0

        out = M.measure_door(ROOT, guard_loader=lambda _r: Mute(),
                             anchor={"measured": True, "pid": os.getpid(),
                                     "start": "контроль"})
        self.assertFalse(out["measured"])
        self.assertIn("вердикт не произведён на сценах", out["reason"])


class TestReport(unittest.TestCase):
    """Сборка, вердикт, код возврата и форма артефакта."""

    def _axes(self, *, door_outcome="question_becomes_claim"):
        vis = {"measured": True, "reason": None, "field": M.READER_FIELD,
               "journal": "session_changes.jsonl",
               "baseline": 1, "control": 0, "scenes": {},
               "by_channel": {M.CHANNEL_JOURNAL_STATE: {"value": 0, "outcome": M.SEEN},
                              M.CHANNEL_SECOND_FILE: {"value": 1, "outcome": M.UNSEEN}}}
        contract = {"measured": True, "reason": None, "baseline": 1, "full": 0,
                    "by_field": {f: {"value": 1, "required": True} for f in M.ABLATIONS},
                    "required_fields": sorted(M.ABLATIONS), "optional_fields": []}
        door = {"measured": True, "reason": None, "verdict_without": "free",
                "anchor": {"pid": 1, "measured": True},
                "by_channel": {
                    M.CHANNEL_JOURNAL_STATE: {"verdict": "claimed", "exit_code": 1,
                                              "outcome": door_outcome},
                    M.CHANNEL_SECOND_FILE: {"verdict": "free", "exit_code": 0,
                                            "outcome": "harmless"}}}
        return vis, contract, door

    def test_status_and_code_follow_the_door(self):
        vis, contract, door = self._axes()
        report = M.build_report(ROOT, now=NOW, visibility=vis, contract=contract,
                                door=door)
        self.assertEqual(report["status"], M.STATUS_STATE_STILL_CAPTURES)
        self.assertEqual(M.exit_code_for(report), 1)
        self.assertEqual(report["generated_at"], "2026-01-02T03:04:05Z")

        vis, contract, door = self._axes(door_outcome="harmless")
        door["by_channel"][M.CHANNEL_JOURNAL_STATE]["verdict"] = "free"
        report = M.build_report(ROOT, now=NOW, visibility=vis, contract=contract,
                                door=door)
        self.assertEqual(report["status"], M.STATUS_BOTH_HARMLESS)
        self.assertEqual(M.exit_code_for(report), 0)

    def test_any_unmeasured_axis_beats_everything(self):
        vis, contract, door = self._axes()
        for name, axis in (("visibility", vis), ("contract", contract), ("door", door)):
            with self.subTest(axis=name):
                broken = dict(axis, measured=False, reason="контроль: ось не измерена")
                kwargs = {"visibility": vis, "contract": contract, "door": door}
                kwargs[name] = broken
                report = M.build_report(ROOT, now=NOW, **kwargs)
                self.assertFalse(report["measured"])
                self.assertEqual(report["status"], M.STATUS_UNMEASURED)
                self.assertEqual(M.exit_code_for(report), 2)
                self.assertIn("контроль: ось не измерена", report["reason"])
                self.assertIsNone(report["answer"])

    def test_report_shape_is_constant_even_unmeasured(self):
        vis, contract, door = self._axes()
        broken = dict(vis, measured=False, reason="контроль")
        report = M.build_report(ROOT, now=NOW, visibility=broken, contract=contract,
                                door=door)
        for key in ("generated_at", "order", "measured", "status", "reason",
                    "applied", "reader", "reader_field", "visibility", "contract",
                    "door", "answer"):
            self.assertIn(key, report)
        self.assertFalse(report["applied"], "прибор обязан оставаться читающим")

    def test_reader_input_is_taken_from_the_axis_not_resolved_again(self):
        """Имя журнала разрешается ОДИН раз — у оси A; сборка читает его оттуда."""
        vis, contract, door = self._axes()
        vis["journal"] = "другой_журнал.jsonl"
        report = M.build_report(ROOT, now=NOW, visibility=vis, contract=contract,
                                door=door)
        self.assertIn("другой_журнал.jsonl", report["answer"]["reader_input"])

    def test_answer_carries_both_channels_and_the_contract(self):
        vis, contract, door = self._axes()
        report = M.build_report(ROOT, now=NOW, visibility=vis, contract=contract,
                                door=door)
        answer = report["answer"]
        self.assertFalse(answer["second_file_seen_by_reader"])
        self.assertTrue(answer["journal_state_seen_by_reader"])
        self.assertEqual(answer["second_file_door_outcome"], "harmless")
        self.assertEqual(answer["journal_state_door_outcome"], "question_becomes_claim")
        self.assertEqual(answer["receipt_required_fields"], sorted(M.ABLATIONS))

    def test_format_names_the_unmeasured_reason_instead_of_printing_numbers(self):
        vis, contract, door = self._axes()
        broken = dict(door, measured=False, reason="контроль: дверь не измерена")
        report = M.build_report(ROOT, now=NOW, visibility=vis, contract=contract,
                                door=broken)
        lines = M.format_report(report)
        self.assertEqual(len(lines), 1)
        self.assertIn("НЕ ИЗМЕРЕНО", lines[0])
        self.assertIn("контроль: дверь не измерена", lines[0])

    def test_format_of_a_measured_report_names_channels_axes_and_blindness(self):
        vis, contract, door = self._axes()
        text = "\n".join(M.format_report(M.build_report(
            ROOT, now=NOW, visibility=vis, contract=contract, door=door)))
        for needle in ("[ОСЬ A]", "[ОСЬ B]", "[ОСЬ C]", M.CHANNEL_SECOND_FILE,
                       M.CHANNEL_JOURNAL_STATE, "НЕ ДОКЛАДЫВАЕТ", "ADVISORY",
                       "население читателей здесь не измерено"):
            self.assertIn(needle, text)


class TestRun(unittest.TestCase):
    """Ступень моста: артефакт оставляется ВСЕГДА, включая третий исход."""

    def test_run_writes_the_artifact_and_reports_measured(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            scene = Path(tmp)
            (scene / "data").mkdir()
            (scene / "scripts").mkdir()
            (scene / "scripts" / "check_card_claim.py").write_text(
                (ROOT / "scripts" / "check_card_claim.py").read_text(encoding="utf-8"),
                encoding="utf-8")
            (scene / "scripts" / "log_session_change.py").write_text(
                (ROOT / "scripts" / "log_session_change.py").read_text(encoding="utf-8"),
                encoding="utf-8")
            out = M.run(str(scene), now=NOW)
            path = scene / "data" / M.ARTIFACT_NAME
            self.assertTrue(path.is_file(), "артефакт не оставлен")
            doc = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(doc["order"], M.ORDER)
        self.assertEqual(doc["generated_at"], "2026-01-02T03:04:05Z")
        self.assertEqual(bool(out["measured"]), bool(doc["measured"]))

    def test_unwritable_data_dir_is_named_not_swallowed(self):
        """Непишущийся артефакт обязан быть НАЗВАН, а не проглочен.

        «Каталога нет» проверкой НЕ является: атомарная запись каталог создаёт
        сама, и такая сцена молча зеленела бы. Поэтому путь `data` занят ФАЙЛОМ —
        тогда запись невозможна по построению, на любом хосте и без прав root.
        """
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "data").write_text("не каталог", encoding="utf-8")
            out = M.run(str(Path(tmp)), now=NOW)
        self.assertTrue("artifact_not_written" in out["doc"],
                        "запись не состоялась, а прибор об этом не сказал")


class TestWiring(unittest.TestCase):
    """Проводка: ступень моста · манифест · поимённая ветка шага 0-офис."""

    @staticmethod
    def _has(text, needle):
        """Вхождение БЕЗ выгрузки файла в отчёт: `assertIn` печатает весь текст."""
        return needle in text

    def _require(self, text, needle, where):
        self.assertTrue(self._has(text, needle),
                        f"{where}: не найдено {needle!r}")

    def test_bridge_stage_calls_the_instrument(self):
        text = (ROOT / "spa_core" / "monitoring" / "findings_bridge.py").read_text(
            encoding="utf-8")
        for needle in ("from spa_core.monitoring import receipt_channel_cost",
                       "receipt_channel_cost.run(root=args.root)",
                       f"data/{M.ARTIFACT_NAME}"):
            self._require(text, needle, "ступень моста")

    def test_manifest_declares_artifact_with_an_slo(self):
        manifest = json.loads((ROOT / "architecture" / "manifest.json").read_text(
            encoding="utf-8"))
        rows = [row for row in manifest["artifacts"]
                if row.get("path") == f"data/{M.ARTIFACT_NAME}"]
        self.assertEqual(len(rows), 1, "артефакт объявлен не ровно один раз")
        self.assertEqual(rows[0]["producer"], "com.spa.decision_loop")
        self.assertTrue(float(rows[0]["slo_hours"]) > 0)

    def test_office_step_has_a_named_branch_and_both_registry_lines(self):
        text = (ROOT / "scripts" / "consume_office_reports.py").read_text(
            encoding="utf-8")
        # Ветка отрисовки + ОБЕ строки реестра: без них артефакт читается
        # ВХОЛОСТУЮ, и это был измеренный дефект, а не гипотеза (ADR-683).
        for needle in (f'elif name == "{M.ARTIFACT_NAME}":',
                       "from spa_core.monitoring.receipt_channel_cost import "
                       "format_report",
                       f'"{M.ARTIFACT_NAME}": (',
                       f'"{M.ARTIFACT_NAME}":\n'
                       '        "spa_core/monitoring/receipt_channel_cost.py"'):
            self._require(text, needle, "шаг 0-офис")

    def test_declared_read_schema_matches_the_producer(self):
        """Перечень полей объявлен У ПРОИЗВОДИТЕЛЯ, а не придуман (урок ADR-683)."""
        text = (ROOT / "scripts" / "consume_office_reports.py").read_text(
            encoding="utf-8")
        self._require(text, f'"{M.ARTIFACT_NAME}": (', "реестр схемы")
        start = text.index(f'"{M.ARTIFACT_NAME}": (')
        declared = text[start:text.index(")", start)]
        report = M.build_report(
            ROOT, now=NOW,
            visibility={"measured": False, "reason": "контроль"},
            contract={"measured": False, "reason": "контроль"},
            door={"measured": False, "reason": "контроль"})
        for field in ("status", "measured", "order", "applied", "reader",
                      "visibility", "contract", "door"):
            self.assertTrue(f'"{field}"' in declared, f"поле {field} не объявлено")
            self.assertTrue(field in report,
                            f"производитель поля {field} не несёт")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
