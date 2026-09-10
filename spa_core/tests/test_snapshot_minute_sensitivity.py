"""Приёмка прибора «решает ли МИНУТА снимка» (заказ CIO #549, ADR-312).

Каждый тест — положительный контроль на КОНКРЕТНЫЙ способ соврать, а не
украшение. Три способа, ради которых прибор и написан:

* выдать ОДИН замер за наблюдение неподвижности («ставка не мигает»);
* назвать дырой транскрипции пару, о которой свидетельствует носитель НОВЕЕ
  записи (изготовить находку из неизмеренного);
* при отсутствии переписи наблюдений доложить «ничего не происходит» вместо
  третьего исхода.

FROZEN-DATE-OK: injected-clock — `measure(..., now=)` принимает часы параметром,
и все отметки в фикстурах ниже заданы литералами. Обе стороны сравнения
закреплены: тест не зависит ни от календаря, ни от часов машины.
"""
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import snapshot_minute_sensitivity as sms

NOW = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)


def _write_jsonl(path: Path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def _record(day, *, unevidenced=(), generated_at=None, as_of=None):
    rec = {
        "cycle_date": day,
        "generated_at": generated_at or f"{day}T08:00:00+00:00",
        "run_ts": None,
        "apy_evidenced_pct": {},
        "apy_unevidenced": list(unevidenced),
    }
    if as_of is not None:
        rec["apy_as_of"] = dict(as_of)
    return rec


def _obs(day, adapter, snapshot, apy, observed_at=None):
    return {
        "observed_at": observed_at or f"{day}T09:00:00+00:00",
        "snapshot": snapshot,
        "kind": "hint_winner",
        "adapter": adapter,
        "apy": apy,
    }


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.data = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write(self, *, history=None, observations=None, snapshot=None,
              stability=None):
        if history is not None:
            _write_jsonl(self.data / sms.HISTORY_FILENAME, history)
        if observations is not None:
            _write_jsonl(self.data / sms.COMPOSITION_FILENAME, observations)
        if snapshot is not None:
            (self.data / sms.SNAPSHOT_FILENAME).write_text(
                json.dumps(snapshot), encoding="utf-8")
        if stability is not None:
            (self.data / sms.STABILITY_FILENAME).write_text(
                json.dumps(stability), encoding="utf-8")

    def measure(self):
        return sms.measure(self.data, now=NOW)


# ───────────────────────── поверхность 1: мигание ─────────────────────────

class TestWithinDayMovement(_Base):
    def test_two_differing_snapshots_are_reported_as_moved(self):
        """Положительный контроль СПОСОБНОСТИ: прибор обязан УМЕТЬ сказать «двинулось»."""
        self.write(
            history=[_record("2026-09-08")],
            observations=[
                _obs("2026-09-08", "aave_v3", "2026-09-08T06:00:00+00:00", 12.7651),
                _obs("2026-09-08", "aave_v3", "2026-09-08T17:27:00+00:00", 3.61),
            ],
        )
        doc = self.measure()
        row, = doc["movement"]
        self.assertEqual(row["verdict"], sms.MOVE_MOVED)
        self.assertAlmostEqual(row["spread_pp"], 9.1551, places=4)

    def test_two_identical_snapshots_are_still_not_moved(self):
        """Контроль на ЛОЖНОЕ «двинулось»: одинаковые значения обязаны дать `still`.

        Без него «двинулось» было бы истинно по построению — прибор, который
        всегда говорит «мигает», не меряет мигание.
        """
        self.write(
            history=[_record("2026-09-08")],
            observations=[
                _obs("2026-09-08", "aave_v3", "2026-09-08T06:00:00+00:00", 3.61),
                _obs("2026-09-08", "aave_v3", "2026-09-08T17:27:00+00:00", 3.61),
            ],
        )
        row, = self.measure()["movement"]
        self.assertEqual(row["verdict"], sms.MOVE_STILL)
        self.assertEqual(row["spread_pp"], 0.0)

    def test_single_snapshot_is_unmeasured_not_still(self):
        """ТРЕТИЙ ИСХОД. Один замер не есть наблюдение неподвижности.

        Это главный способ соврать на этой поверхности: посчитать пары с одним
        снимком «неподвижными» и доложить, что ставка внутри дня не мигает.
        """
        self.write(
            history=[_record("2026-09-08")],
            observations=[
                _obs("2026-09-08", "aave_v3", "2026-09-08T06:00:00+00:00", 3.61),
            ],
        )
        row, = self.measure()["movement"]
        self.assertEqual(row["verdict"], sms.MOVE_UNMEASURED)
        self.assertIsNone(row["spread_pp"])

    def test_two_runs_of_one_snapshot_are_one_observation(self):
        """Два прогона, увидевшие ОДИН снимок, — одно наблюдение, а не мигание."""
        self.write(
            history=[_record("2026-09-08")],
            observations=[
                _obs("2026-09-08", "aave_v3", "2026-09-08T06:00:00+00:00", 3.61,
                     observed_at="2026-09-08T07:03:00+00:00"),
                _obs("2026-09-08", "aave_v3", "2026-09-08T06:00:00+00:00", 3.61,
                     observed_at="2026-09-08T13:06:00+00:00"),
            ],
        )
        row, = self.measure()["movement"]
        self.assertEqual(row["snapshots"], 1)
        self.assertEqual(row["verdict"], sms.MOVE_UNMEASURED)

    def test_non_finite_rate_is_not_an_observation(self):
        """``None``/строка/``True`` ставкой не являются и мигания не создают."""
        self.write(
            history=[_record("2026-09-08")],
            observations=[
                _obs("2026-09-08", "aave_v3", "2026-09-08T06:00:00+00:00", 3.61),
                _obs("2026-09-08", "aave_v3", "2026-09-08T10:00:00+00:00", None),
                _obs("2026-09-08", "aave_v3", "2026-09-08T12:00:00+00:00", True),
            ],
        )
        row, = self.measure()["movement"]
        self.assertEqual(row["snapshots"], 1)
        self.assertEqual(row["verdict"], sms.MOVE_UNMEASURED)


# ──────────────────── поверхность 2: решает ли ВЕРДИКТ ────────────────────

class TestVerdictSensitivity(_Base):
    def _moved(self, spread_from=3.0, spread_to=5.0):
        return [
            _obs("2026-09-08", "aave_v3", "2026-09-08T06:00:00+00:00", spread_from),
            _obs("2026-09-08", "aave_v3", "2026-09-08T17:00:00+00:00", spread_to),
        ]

    def test_spread_above_margin_says_the_minute_decides(self):
        self.write(history=[_record("2026-09-08")], observations=self._moved(),
                   stability={"protocols": [
                       {"protocol": "aave_v3", "margin_pp": 0.3741}]})
        doc = self.measure()
        row, = doc["sensitivity"]
        self.assertEqual(row["verdict"], sms.DECIDES)
        self.assertEqual(doc["status"], sms.STATUS_CRITICAL)

    def test_spread_below_margin_says_the_margin_holds(self):
        """Контроль на ЛОЖНОЕ «минута решает»: при широкой марже вердикт обязан смениться."""
        self.write(history=[_record("2026-09-08")], observations=self._moved(),
                   stability={"protocols": [
                       {"protocol": "aave_v3", "margin_pp": 50.0}]})
        row, = self.measure()["sensitivity"]
        self.assertEqual(row["verdict"], sms.MARGIN_HOLDS)

    def test_spread_exactly_equal_to_the_margin_holds_it_is_not_evidence(self):
        """ГРАНИЦА вердикта закреплена с ОБЕИХ сторон (замер цикла #551).

        Батарея цикла #550 меряла `>` двумя точками, лежащими ДАЛЕКО по разные
        стороны маржи (0.3741 и 50.0 при размахе 2.0), поэтому подмена `>` на
        `>=` вердикта не меняла и мутация ВЫЖИЛА — при том, что именно на этой
        границе прибор решает, называть ли находку. Тай — не свидетельство:
        размах, ровно ДОСТАВШИЙ до маржи, её не превысил, и назвать это «минута
        решает цель» значило бы изготовить находку из равенства. Направление то
        же, что у остальных третьих исходов прибора: не уверен — не обвиняй.
        """
        self.write(history=[_record("2026-09-08")],
                   observations=self._moved(spread_from=3.0, spread_to=5.0),
                   stability={"protocols": [
                       {"protocol": "aave_v3", "margin_pp": 2.0}]})
        row, = self.measure()["sensitivity"]
        self.assertEqual(row["spread_pp"], row["margin_pp"])
        self.assertEqual(row["verdict"], sms.MARGIN_HOLDS)

    def test_spread_a_hair_above_the_margin_does_decide(self):
        """Обратная сторона той же границы: чуть ВЫШЕ маржи — вердикт обязан смениться.

        Без этой половины предыдущий тест проходил бы и на коде, который не
        называет находку НИКОГДА.
        """
        self.write(history=[_record("2026-09-08")],
                   observations=self._moved(spread_from=3.0, spread_to=5.0),
                   stability={"protocols": [
                       {"protocol": "aave_v3", "margin_pp": 1.999}]})
        row, = self.measure()["sensitivity"]
        self.assertEqual(row["verdict"], sms.DECIDES)

    def test_missing_margin_refuses_instead_of_guessing(self):
        """ТРЕТИЙ ИСХОД: нет маржи ⇒ claim про вердикт НЕ выдаётся."""
        self.write(history=[_record("2026-09-08")], observations=self._moved(),
                   stability={"protocols": []})
        row, = self.measure()["sensitivity"]
        self.assertEqual(row["verdict"], sms.NO_MARGIN)
        self.assertIsNone(row["margin_pp"])

    def test_still_pair_is_not_scored_against_the_margin(self):
        """У неподвижной пары сравнивать нечего — она в поверхность 2 не входит."""
        self.write(
            history=[_record("2026-09-08")],
            observations=self._moved(spread_from=3.0, spread_to=3.0),
            stability={"protocols": [{"protocol": "aave_v3", "margin_pp": 0.1}]},
        )
        self.assertEqual(self.measure()["sensitivity"], [])


# ───────────────────── где теряется наблюдённое значение ─────────────────────

class TestLossClassification(_Base):
    def test_observation_older_than_record_is_a_proven_hole(self):
        self.write(
            history=[_record("2026-09-08", unevidenced=["pendle"],
                             generated_at="2026-09-08T17:27:00+00:00")],
            observations=[
                _obs("2026-09-08", "pendle", "2026-09-08T07:03:00+00:00", 13.98)],
        )
        loss, = self.measure()["losses"]
        self.assertEqual(loss["class"], sms.CLASS_HOLE)

    def test_observation_newer_than_record_is_unmeasured_not_a_hole(self):
        """ГЛАВНЫЙ контроль на изготовление находки из неизмеренного.

        Замер 10.09 ровно такой: снимок 07:59:45 живой, запись 07:59:42 — на три
        секунды раньше. Запись не могла видеть будущее.
        """
        self.write(
            history=[_record("2026-09-08", unevidenced=["pendle"],
                             generated_at="2026-09-08T07:00:00+00:00")],
            observations=[
                _obs("2026-09-08", "pendle", "2026-09-08T17:27:00+00:00", 13.98)],
        )
        loss, = self.measure()["losses"]
        self.assertEqual(loss["class"], sms.CLASS_NEWER)

    def test_snapshot_naming_the_leg_but_newer_is_not_no_carrier(self):
        """«Носителя нет» и «носитель есть, но новее» — РАЗНЫЕ третьи исхода."""
        self.write(
            history=[_record("2026-09-08", unevidenced=["pendle"],
                             generated_at="2026-09-08T07:00:00+00:00")],
            observations=[_obs("2026-09-08", "aave_v3",
                               "2026-09-08T06:00:00+00:00", 3.6)],
            snapshot={"generated_at": "2026-09-08T17:59:45+00:00",
                      "adapters": [{"protocol": "pendle", "status": "error",
                                    "apy_pct": None}]},
        )
        loss, = self.measure()["losses"]
        self.assertEqual(loss["class"], sms.CLASS_NEWER)

    def test_comparable_snapshot_with_error_status_blames_the_source(self):
        self.write(
            history=[_record("2026-09-08", unevidenced=["pendle"],
                             generated_at="2026-09-08T18:00:00+00:00")],
            observations=[_obs("2026-09-08", "aave_v3",
                               "2026-09-08T06:00:00+00:00", 3.6)],
            snapshot={"generated_at": "2026-09-08T17:59:45+00:00",
                      "adapters": [{"protocol": "pendle", "status": "error",
                                    "apy_pct": None}]},
        )
        loss, = self.measure()["losses"]
        self.assertEqual(loss["class"], sms.CLASS_FEED_ERROR)

    def test_comparable_snapshot_with_live_rate_is_a_hole(self):
        """Контроль, что предыдущий тест меряет STATUS, а не просто «снимок есть»."""
        self.write(
            history=[_record("2026-09-08", unevidenced=["fluid_usdc"],
                             generated_at="2026-09-08T18:00:00+00:00")],
            observations=[_obs("2026-09-08", "aave_v3",
                               "2026-09-08T06:00:00+00:00", 3.6)],
            snapshot={"generated_at": "2026-09-08T17:59:45+00:00",
                      "adapters": [{"protocol": "fluid_usdc", "status": "ok",
                                    "apy_pct": 4.63}]},
        )
        loss, = self.measure()["losses"]
        self.assertEqual(loss["class"], sms.CLASS_HOLE)

    def test_no_carrier_at_all_is_named_as_such(self):
        self.write(
            history=[_record("2026-09-08", unevidenced=["pendle"])],
            observations=[_obs("2026-09-08", "aave_v3",
                               "2026-09-08T06:00:00+00:00", 3.6)],
        )
        loss, = self.measure()["losses"]
        self.assertEqual(loss["class"], sms.CLASS_NO_CARRIER)

    def test_record_carrying_its_own_stamp_blames_the_funding_gate(self):
        """ADR-312, аддитивное поле: у носителя В ТОЙ ЖЕ записи вопроса о
        сопоставимости нет по построению, и он называет гейт, а не дорогу."""
        self.write(
            history=[_record("2026-09-08", unevidenced=["pendle"],
                             as_of={"pendle": "2026-09-08T06:00:00+00:00"})],
            observations=[_obs("2026-09-08", "aave_v3",
                               "2026-09-08T06:00:00+00:00", 3.6)],
        )
        loss, = self.measure()["losses"]
        self.assertEqual(loss["class"], sms.CLASS_GATE)

    def test_record_stamp_outranks_a_newer_snapshot(self):
        """Порядок носителей: собственная отметка записи сильнее перезаписываемого снимка."""
        self.write(
            history=[_record("2026-09-08", unevidenced=["pendle"],
                             generated_at="2026-09-08T07:00:00+00:00",
                             as_of={"pendle": "2026-09-08T06:00:00+00:00"})],
            observations=[_obs("2026-09-08", "pendle",
                               "2026-09-08T17:27:00+00:00", 13.98)],
        )
        loss, = self.measure()["losses"]
        self.assertEqual(loss["class"], sms.CLASS_GATE)


# ─────────────────────────── третий исход целиком ───────────────────────────

class TestRefusals(_Base):
    def test_missing_journal_refuses_and_produces_no_numbers(self):
        """ГЛАВНЫЙ ОТРИЦАТЕЛЬНЫЙ КОНТРОЛЬ: без журнала — ни одного числа."""
        self.write(observations=[_obs("2026-09-08", "aave_v3",
                                      "2026-09-08T06:00:00+00:00", 3.6)])
        doc = self.measure()
        self.assertEqual(doc["status"], sms.STATUS_UNMEASURED)
        for key in ("movement", "sensitivity", "losses", "class_counts",
                    "population"):
            self.assertNotIn(key, doc, f"{key} выдан при неизмеренном входе")

    def test_missing_observation_log_refuses_instead_of_reporting_no_movement(self):
        """Без переписи наблюдений нельзя отвечать «не мигает» — только «не измерено»."""
        self.write(history=[_record("2026-09-08")])
        doc = self.measure()
        self.assertEqual(doc["status"], sms.STATUS_UNMEASURED)
        self.assertNotIn("movement", doc)
        self.assertTrue(any("НЕ ИЗМЕРЕНО" in f for f in doc["findings"]))

    def test_unmeasured_is_counted_apart_from_zero(self):
        """`counts.unchecked` обязан отличать молчание прибора от чистого прогона.

        Растворив «не измерено» в нулях, мы сделали бы отказ прибора
        неотличимым от чистого прогона — ровно тот fail-OPEN, который тише
        красного и потому опаснее.
        """
        root = self.data / "root"
        (root / "data").mkdir(parents=True)
        self.data = root / "data"
        self.write(history=[_record("2026-09-08")])
        doc = sms.run(root=str(root), write=False, now=NOW)
        self.assertEqual(doc["status"], sms.STATUS_UNMEASURED)
        self.assertEqual(doc["counts"]["critical"], 0)
        # Слагаемых РОВНО два, и проверяются они вместе: сам отказ (статус) и
        # названная причина (находка). `>= 1` здесь мало — при нём батарея
        # мутаций пропускает «растворить статус в нулях»: второе слагаемое
        # маскирует пропажу первого, и счётчик молчит о том, что прибор
        # ОТКАЗАЛ. Ровно тот случай, когда сторож не проверен, потому что
        # соседнее состояние делает его излишним.
        self.assertEqual(doc["counts"]["unchecked"], 2)

    def test_every_refusal_names_its_reason(self):
        """Инвариант, на котором стои́т счёт выше: отказ без причины запрещён."""
        for name, files in (("нет журнала", {"observations": []}),
                            ("нет переписи", {"history": [_record("2026-09-08")]})):
            with self.subTest(name):
                tmp = TemporaryDirectory()
                self.addCleanup(tmp.cleanup)
                self.data = Path(tmp.name)
                self.write(**files)
                doc = self.measure()
                self.assertEqual(doc["status"], sms.STATUS_UNMEASURED)
                self.assertTrue(
                    any(f.startswith("[НЕ ИЗМЕРЕНО]") for f in doc["findings"]),
                    f"{name}: отказ не назвал причину")
                self.assertTrue(doc.get("unmeasured_reason"))


class TestContract(_Base):
    """Форма, которую ждут шаг 0-офис и ступень переписей `findings_bridge`."""

    def _full(self):
        self.write(
            history=[_record("2026-09-08", unevidenced=["pendle"])],
            observations=[
                _obs("2026-09-08", "aave_v3", "2026-09-08T06:00:00+00:00", 3.0),
                _obs("2026-09-08", "aave_v3", "2026-09-08T17:00:00+00:00", 5.0),
            ],
            stability={"protocols": [{"protocol": "aave_v3", "margin_pp": 0.3}]},
        )

    def test_run_writes_the_artifact_and_stamps_overall_and_counts(self):
        # `root` строго ВНУТРИ TemporaryDirectory. `self.data.parent` — общий
        # каталог временных файлов машины: каталог там переживает прогон и
        # сталкивается со следующим, и вердикт теста начинает решать окружение,
        # а не код (ровно это и случилось при первом прогоне батареи).
        root = self.data / "root"
        (root / "data").mkdir(parents=True)
        self.data = root / "data"
        self._full()
        doc = sms.run(root=str(root), now=NOW)
        self.assertEqual(doc["overall"], doc["status"])
        self.assertIn("critical", doc["counts"])
        self.assertTrue((root / "data" / sms.OUTPUT_FILENAME).exists())

    def test_format_report_names_the_status_and_every_finding(self):
        self._full()
        doc = self.measure()
        lines = "\n".join(sms.format_report(doc))
        self.assertIn(doc["status"], lines)
        for f in doc["findings"]:
            self.assertIn(f, lines)

    def test_clock_is_an_input_not_the_wall(self):
        self._full()
        self.assertEqual(sms.measure(self.data, now=NOW)["generated_at"],
                         NOW.isoformat())

    def test_measurement_is_deterministic(self):
        self._full()
        a = self.measure()
        b = self.measure()
        self.assertEqual(json.dumps(a, sort_keys=True, ensure_ascii=False),
                         json.dumps(b, sort_keys=True, ensure_ascii=False))

    def test_broken_line_does_not_destroy_the_file(self):
        self._full()
        with open(self.data / sms.COMPOSITION_FILENAME, "a", encoding="utf-8") as fh:
            fh.write("{не json\n")
        self.assertEqual(self.measure()["status"], sms.STATUS_CRITICAL)


class TestAdditiveRecordField(unittest.TestCase):
    """ADR-312: запись решения несёт МОМЕНТ наблюдения каждой ставки.

    Поле аддитивно и действует ВПЕРЁД: 36 уже написанных строк его не несут, и
    потребитель обязан это пережить — иначе «починка» покрасила бы здоровый
    контур, произведённый до доставки.
    """

    def _doc(self):
        return {"cycle_date": "2026-09-10",
                "generated_at": "2026-09-10T08:00:00+00:00",
                "decision_shadow": {"decision": "HOLD"}, "params": {}}

    def _build(self, **kw):
        from spa_core.paper_trading.allocation_rationale import build_history_record
        return build_history_record(
            self._doc(), apy_pct={"aave_v3": 3.7}, apy_sources={"aave_v3": "live"},
            current_positions={"aave_v3": 100.0}, target_positions={},
            capital_usd=100.0, **kw)

    def test_stamp_is_carried_for_every_leg_of_the_universe(self):
        rec = self._build(apy_as_of={"aave_v3": "2026-09-10T07:59:45+00:00"})
        self.assertEqual(rec["apy_as_of"],
                         {"aave_v3": "2026-09-10T07:59:45+00:00"})

    def test_absent_stamp_map_yields_an_empty_field_not_a_crash(self):
        """Обратная совместимость: писатель без карты моментов не падает."""
        self.assertEqual(self._build()["apy_as_of"], {})

    def test_stamps_outside_the_universe_are_not_smuggled_in(self):
        """Поле следует НАСЕЛЕНИЮ записи, а не карте: иначе оно бы её расширяло."""
        rec = self._build(apy_as_of={"aave_v3": "2026-09-10T07:59:45+00:00",
                                     "не_в_населении": "2026-09-10T07:00:00+00:00"})
        self.assertEqual(set(rec["apy_as_of"]), {"aave_v3"})

    def test_the_field_does_not_move_the_verdict_or_the_populations(self):
        """Аддитивность: со ставкой момента и без неё всё ОСТАЛЬНОЕ бит в бит."""
        bare = self._build()
        stamped = self._build(apy_as_of={"aave_v3": "2026-09-10T07:59:45+00:00"})
        bare.pop("apy_as_of"), stamped.pop("apy_as_of")
        self.assertEqual(json.dumps(bare, sort_keys=True, ensure_ascii=False),
                         json.dumps(stamped, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
