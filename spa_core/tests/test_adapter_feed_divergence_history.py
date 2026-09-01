"""Память сторожа расхождений: «мигает» и «живёт» — разные ответы (ADR-206).

Карточка `inbox-critical-storozha-fidov-migaet-aave-v3-r`: отчёт
`data/adapter_feed_divergence.json` перезаписывается каждым прогоном, поэтому вопрос
**«сколько раз за последние N суток два ЖИВЫХ наблюдения одного пула разошлись и на
сколько»** был неразрешим ПО ПОСТРОЕНИЮ. Три точки по `aave_v3` собрали РУКАМИ три
разных цикла, и вывод «мигание само гаснет» дожил до опровержения только случайно:

| замер | adapter_status | orchestrator | разница |
|---|---|---|---|
| #392, 27.08 01:14Z | 9.7159 | 11.4059 | 1.69 пп |
| #392, 27.08 05:27Z | 3.1104 | 3.1104 | сошлись |
| #439, 31.08 05:36Z | 11.0231 | 4.9838 | 6.0393 пп (знак перевёрнут) |
| #449, 01.09 17:40Z | 11.2163 | 4.9823 | **6.234 пп** |

Каждый тест ниже — положительный контроль на этом ряду: числа дословные.

Приёмка карточки — «тест в обе стороны»: расхождение пишется, СОГЛАСИЕ не пишется.
Сверх неё проверяется то, без чего журнал врал бы: единица счёта — СНИМОК, а не прогон;
слепота записывается отдельной строкой; окно ответа обрезается возрастом журнала.

Время всюду подаётся как вход `now=`, отметки снимков — от того же якоря.
"""
# FROZEN-DATE-OK: injected-clock — часы подаются входом (`afd.run(now=…)`,
# `afd.history(now=…)`), и ОТМЕТКИ СНИМКОВ закреплены тем же якорем (`NOW`,
# `AAVE_MEASUREMENTS`): обе стороны сравнения свежести зафиксированы, календарь
# на вердикт не влияет. Сами даты здесь — предмет (дословный ряд замеров
# 27.08 → 01.09, которым карточка опровергла гипотезу «мигание само гаснет»).
import datetime as dt
import json
import os
import tempfile
import unittest

from spa_core.monitoring import adapter_feed_divergence as afd

NOW = dt.datetime(2026, 9, 1, 18, 0, tzinfo=dt.timezone.utc)

#: Дословный ряд замеров `aave_v3` из карточки. (отметка снимка, status, orchestrator).
AAVE_MEASUREMENTS = [
    ("2026-08-27T01:14:16+00:00", 9.7159, 11.4059),
    ("2026-08-27T05:27:00+00:00", 3.1104, 3.1104),     # сошлись — строки быть не должно
    ("2026-08-31T05:36:36+00:00", 11.0231, 4.9838),
    ("2026-09-01T17:40:30+00:00", 11.2163, 4.9823),
]


def _docs(stamp: str, s_apy: float, o_apy: float):
    status = {"generated_at": stamp, "adapters": {"aave_v3": {
        "apy": s_apy, "live_apy": s_apy, "tier": 1,
        "tvl_usd": 1.2e10, "tvl_source": "static"}}}
    orch = {"generated_at": stamp, "adapters": [{
        "protocol": "aave_v3", "apy_pct": o_apy, "live_data": True, "tier": "T1",
        "tvl_usd": 1.2e10, "tvl_source": "static"}]}
    return status, orch


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = os.path.join(self.tmp.name, "data")
        os.makedirs(self.data)

    def observe(self, stamp: str, s_apy: float, o_apy: float, *, at: dt.datetime = None):
        status, orch = _docs(stamp, s_apy, o_apy)
        with open(os.path.join(self.data, "adapter_status.json"), "w") as fh:
            json.dump(status, fh)
        with open(os.path.join(self.data, "adapter_orchestrator_status.json"), "w") as fh:
            json.dump(orch, fh)
        observed_at = at or dt.datetime.fromisoformat(stamp) + dt.timedelta(minutes=5)
        return afd.run(root=self.tmp.name, now=observed_at, data_dir=self.data)

    def journal(self):
        records, reason = afd.read_journal(self.data)
        return records, reason


class TestDivergenceIsWrittenAgreementIsNot(_Base):
    """Приёмочный критерий карточки, ровно в обе стороны."""

    def test_a_live_vs_live_divergence_lands_in_the_journal(self):
        self.observe(*AAVE_MEASUREMENTS[3])
        records, _ = self.journal()
        rows = [r for r in records if r["kind"] == "apy_live_vs_live"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["protocol"], "aave_v3")
        self.assertEqual(rows[0]["severity"], afd.CRITICAL)
        self.assertEqual(rows[0]["delta_pp"], 6.234)
        self.assertEqual(rows[0]["adapter_status_apy"], 11.2163)
        self.assertEqual(rows[0]["orchestrator_apy"], 4.9823)

    def test_agreement_writes_nothing(self):
        """27.08 05:27Z: оба фида дали 3.1104 — журналу сказать нечего."""
        report = self.observe(*AAVE_MEASUREMENTS[1])
        self.assertEqual(report["overall"], "OK")
        self.assertEqual(report["history_appended"], 0)
        records, _ = self.journal()
        self.assertEqual([r["kind"] for r in records], ["journal_opened"])
        self.assertEqual(afd.history(self.data, days=30, now=NOW)["by_key"], {})

    def test_an_open_but_empty_journal_is_not_the_same_as_no_journal(self):
        """«Смотрим и не видим» ≠ «смотреть нечем» — иначе здоровье краснеет вечно."""
        no_memory = afd.history(self.data, days=7, now=NOW)
        self.assertEqual(no_memory["status"], afd.UNCHECKED)
        self.observe(*AAVE_MEASUREMENTS[1])                       # согласие, находок нет
        watching = afd.history(self.data, days=1.5,
                               now=dt.datetime(2026, 8, 29, tzinfo=dt.timezone.utc))
        self.assertEqual(watching["status"], "OK")
        self.assertEqual(watching["by_key"], {})
        self.assertGreater(watching["covered_days"], 1.7)         # покрытие ОТ открытия
        self.assertFalse(watching["window_truncated"])

    def test_info_provenance_lines_are_not_recorded_as_recurrence(self):
        """INFO о провенансе TVL — состояние УЖЕ решённое (ADR-053), не рецидив."""
        status, orch = _docs("2026-09-01T17:40:30+00:00", 3.1104, 3.1104)
        status["adapters"]["aave_v3"]["tvl_source"] = "live"
        with open(os.path.join(self.data, "adapter_status.json"), "w") as fh:
            json.dump(status, fh)
        with open(os.path.join(self.data, "adapter_orchestrator_status.json"), "w") as fh:
            json.dump(orch, fh)
        report = afd.run(root=self.tmp.name, now=NOW, data_dir=self.data)
        self.assertEqual(report["counts"]["info"], 1)
        self.assertEqual(report["history_appended"], 0)


class TestTheUnitOfCountIsTheSnapshotNotTheRun(_Base):
    """Оба входа пишет дневной цикл, сторожа зовут часто — иначе счёт считал бы взгляды."""

    def test_re_reading_one_snapshot_adds_no_new_line(self):
        first = self.observe(*AAVE_MEASUREMENTS[3])
        self.assertEqual(first["history_appended"], 1)
        for extra_minutes in (30, 60, 90):
            again = self.observe(*AAVE_MEASUREMENTS[3],
                                 at=NOW + dt.timedelta(minutes=extra_minutes))
            self.assertEqual(again["history_appended"], 0)
        records, _ = self.journal()
        self.assertEqual([r["kind"] for r in records],
                         ["journal_opened", "apy_live_vs_live"])
        self.assertEqual(afd.history(self.data, days=30, now=NOW)
                         ["by_key"]["aave_v3:apy_live_vs_live"]["snapshots_diverged"], 1)

    def test_a_new_snapshot_of_the_same_pair_is_a_new_observation(self):
        for stamp, s_apy, o_apy in AAVE_MEASUREMENTS:
            self.observe(stamp, s_apy, o_apy)
        row = afd.history(self.data, days=30, now=NOW)["by_key"]["aave_v3:apy_live_vs_live"]
        self.assertEqual(row["snapshots_diverged"], 3)   # четвёртый замер — согласие
        self.assertEqual(row["delta_pp_min"], 1.69)
        self.assertEqual(row["delta_pp_max"], 6.234)
        self.assertEqual(row["delta_pp_median"], 6.0393)
        self.assertTrue(row["first_seen"].startswith("2026-08-27"))
        self.assertTrue(row["last_seen"].startswith("2026-09-01"))


class TestTheQuestionOfTheCardIsAnsweredByANumber(_Base):
    """«Сколько раз за N суток и на сколько» — карточка требовала именно числа."""

    def test_the_amplitude_grew_fourfold_and_the_sign_flipped(self):
        for stamp, s_apy, o_apy in AAVE_MEASUREMENTS:
            self.observe(stamp, s_apy, o_apy)
        records, _ = self.journal()
        rows = sorted((r for r in records if r["kind"] == "apy_live_vs_live"),
                      key=lambda r: r["observed_at"])
        self.assertEqual([r["delta_pp"] for r in rows], [1.69, 6.0393, 6.234])
        # знак: 27.08 выше был orchestrator, 31.08 и 01.09 — adapter_status
        self.assertLess(rows[0]["adapter_status_apy"], rows[0]["orchestrator_apy"])
        self.assertGreater(rows[1]["adapter_status_apy"], rows[1]["orchestrator_apy"])

    def test_a_narrow_window_does_not_see_the_older_measurements(self):
        for stamp, s_apy, o_apy in AAVE_MEASUREMENTS:
            self.observe(stamp, s_apy, o_apy)
        recent = afd.history(self.data, days=2, now=NOW)
        self.assertEqual(recent["by_key"]["aave_v3:apy_live_vs_live"]["snapshots_diverged"], 2)


class TestAbsenceOfObservationHasItsOwnValue(_Base):
    """Инвариант #17: «расхождений нет» не смеет означать «мы были слепы»."""

    def test_a_refused_verdict_is_written_as_its_own_line(self):
        status, orch = _docs("2026-08-31T05:36:36+00:00", 11.0231, 4.9838)
        orch["generated_at"] = "2026-08-31T09:00:00+00:00"      # разрыв снимков
        with open(os.path.join(self.data, "adapter_status.json"), "w") as fh:
            json.dump(status, fh)
        with open(os.path.join(self.data, "adapter_orchestrator_status.json"), "w") as fh:
            json.dump(orch, fh)
        report = afd.run(root=self.tmp.name, now=dt.datetime(
            2026, 8, 31, 10, tzinfo=dt.timezone.utc), data_dir=self.data)
        self.assertEqual(report["overall"], afd.UNCHECKED)
        records, _ = self.journal()
        self.assertEqual([r["kind"] for r in records], ["journal_opened", "unchecked"])
        self.assertTrue(records[1]["reasons"])
        h = afd.history(self.data, days=30, now=NOW)
        self.assertEqual(h["by_key"], {})
        self.assertEqual(h["blind_snapshots"], 1)

    def test_a_journal_younger_than_the_window_says_so(self):
        self.observe(*AAVE_MEASUREMENTS[3])
        h = afd.history(self.data, days=30, now=NOW)
        self.assertTrue(h["window_truncated"])
        self.assertLess(h["covered_days"], 30)
        self.assertIn("нечем судить о более раннем", h["note"])

    def test_a_journal_covering_the_window_is_not_flagged(self):
        self.observe(*AAVE_MEASUREMENTS[0])
        h = afd.history(self.data, days=1, now=NOW)
        self.assertFalse(h["window_truncated"])

    def test_a_missing_journal_is_unchecked_not_zero_divergences(self):
        h = afd.history(self.data, days=7, now=NOW)
        self.assertEqual(h["status"], afd.UNCHECKED)
        self.assertIn("журнала нет на диске", h["reason"])


class TestRotationKeepsTheNewest(_Base):
    def test_the_journal_is_capped_and_drops_the_oldest(self):
        path = afd.log_path(self.data)
        with open(path, "w", encoding="utf-8") as fh:
            for i in range(afd.LOG_MAX_LINES + 5):
                fh.write(json.dumps({"observed_at": "2026-01-01T00:00:00+00:00",
                                     "snapshot_key": f"old-{i}", "protocol": "x",
                                     "kind": "apy_live_vs_live", "severity": afd.CRITICAL}) + "\n")
        self.observe(*AAVE_MEASUREMENTS[3])
        records, _ = self.journal()
        self.assertEqual(len(records), afd.LOG_MAX_LINES)
        self.assertEqual(records[-1]["protocol"], "aave_v3")
        self.assertNotIn("old-0", [r["snapshot_key"] for r in records])

    def test_a_corrupt_line_is_skipped_and_named_not_swallowed(self):
        with open(afd.log_path(self.data), "w", encoding="utf-8") as fh:
            fh.write("{not json}\n")
            fh.write(json.dumps({"observed_at": NOW.isoformat(), "snapshot_key": "k",
                                 "protocol": "aave_v3", "kind": "apy_live_vs_live",
                                 "severity": afd.CRITICAL, "delta_pp": 6.234}) + "\n")
        records, reason = self.journal()
        self.assertEqual(len(records), 1)
        self.assertIn("нечитаемых строк: 1", reason)


class TestWiring(unittest.TestCase):
    """Журнал, который никто не пишет и никто не может спросить, — украшение."""

    def test_run_writes_the_journal_next_to_its_report(self):
        with open(afd.__file__, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("append_history(report, base, now)", src)

    def test_the_cli_can_answer_the_cards_question(self):
        import io as _io
        import contextlib
        with tempfile.TemporaryDirectory() as tmp:
            data = os.path.join(tmp, "data")
            os.makedirs(data)
            buf = _io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = afd.main(["--root", tmp, "--data-dir", data, "--history"], now=NOW)
        self.assertEqual(code, 2)                       # памяти нет ⇒ НЕ «расхождений нет»
        self.assertIn("НЕ ИЗМЕРЕНО", buf.getvalue())

    def test_the_answer_rides_in_the_artifact_that_has_a_mandatory_reader(self):
        """У журнала обязательного читателя нет — у отчёта есть (шаг 0-офис)."""
        with tempfile.TemporaryDirectory() as tmp:
            data = os.path.join(tmp, "data")
            os.makedirs(data)
            status, orch = _docs("2026-09-01T17:40:30+00:00", 11.2163, 4.9823)
            for name, doc in (("adapter_status.json", status),
                              ("adapter_orchestrator_status.json", orch)):
                with open(os.path.join(data, name), "w") as fh:
                    json.dump(doc, fh)
            afd.run(root=tmp, now=NOW, data_dir=data)
            with open(os.path.join(data, "adapter_feed_divergence.json")) as fh:
                written = json.load(fh)
        self.assertEqual(written["history"]["status"], "OK")
        self.assertEqual(
            written["history"]["by_key"]["aave_v3:apy_live_vs_live"]["delta_pp_max"], 6.234)

    def test_the_mandatory_office_step_declares_the_memory_as_read(self):
        """Поле, которого нет в `_READ_SCHEMA`, шаг 0-офис объявит НЕ ПРОЧИТАННЫМ."""
        repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(afd.__file__))))
        with open(os.path.join(repo, "scripts", "consume_office_reports.py"),
                  encoding="utf-8") as fh:
            src = fh.read()
        for field in ("history.status", "history.by_key", "history.blind_snapshots"):
            self.assertIn(f'"{field}"', src)

    def test_the_office_step_prints_the_recurrence_not_just_the_moment(self):
        import importlib.util
        repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(afd.__file__))))
        spec = importlib.util.spec_from_file_location(
            "_cor", os.path.join(repo, "scripts", "consume_office_reports.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        report = {
            "overall": afd.CRITICAL, "counts": {"critical": 1, "warn": 0, "info": 0,
                                                "unchecked": 0},
            "compared_protocols": ["aave_v3"], "unchecked": [],
            "findings": [{"protocol": "aave_v3", "kind": "apy_live_vs_live",
                          "severity": afd.CRITICAL, "message": "…"}],
            "history": {"status": "OK", "window_days": 7.0, "covered_days": 5.5,
                        "window_truncated": True, "records": 3, "blind_snapshots": 1,
                        "by_key": {"aave_v3:apy_live_vs_live": {
                            "protocol": "aave_v3", "kind": "apy_live_vs_live",
                            "severity": afd.CRITICAL, "snapshots_diverged": 3,
                            "first_seen": "2026-08-27T01:14:16+00:00",
                            "last_seen": "2026-09-01T17:40:30+00:00",
                            "delta_pp_min": 1.69, "delta_pp_max": 6.234,
                            "delta_pp_median": 6.0393}}},
        }
        text = "\n".join(mod._summarize_json("data/adapter_feed_divergence.json", report))
        self.assertIn("разошлись на 3 снимк", text)
        self.assertIn("1.69…6.234", text)
        self.assertIn("окно обрезано возрастом журнала", text)
        self.assertIn("отказался судить: 1", text)

    def test_a_report_without_memory_goes_through_the_schema_channel_only(self):
        """Отчёт СТАРОГО образца разбирает `_schema_gap` — он один умеет отличить
        «производитель не пишет ключ» от «отчёт написан до доставки ключа» (#248).
        Своя строка в ветке разбора повторила бы ту аварию: находка о здоровом
        контуре теми же словами, что настоящая."""
        import importlib.util
        repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(afd.__file__))))
        spec = importlib.util.spec_from_file_location(
            "_cor2", os.path.join(repo, "scripts", "consume_office_reports.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        text = "\n".join(mod._summarize_json("data/adapter_feed_divergence.json", {
            "overall": "OK", "counts": {"critical": 0, "warn": 0, "info": 0, "unchecked": 0},
            "compared_protocols": ["aave_v3"], "unchecked": [], "findings": []}))
        self.assertIn("расхождение схемы", text)
        self.assertIn("history.by_key", text)
        self.assertNotIn("память за", text)


if __name__ == "__main__":
    unittest.main()
