"""Три исхода у читателя артефактов go-live (ADR-881, заказ G879 п. 1 (в)).

Предмет: `GoLiveReadinessReport._read_json` отдавал `{}` **на любую ошибку** и
этим склеивал три состояния мира в одно — «файла нет» (писатель не писал, это
ОТВЕТ), «файл есть и не разобран» (судить нечем, ТРЕТИЙ исход), «файл есть и
говорит нет» (измерено и равно нулю). Перечень `items_unmeasured`, заведённый
ADR-878, писателя не имел: замер 31.10 — ноль записей во всех 36 сценах.

**Каждый тест ниже — положительный контроль, воспроизводящий настоящее
состояние до правки.** Батарея, которая только зеленеет на новом коде, не
доказывает ничего: она обязана КРАСНЕТЬ там, где исходы склеены, — и с ОБЕИХ
сторон, потому что перечень, в который валится всё, различает исходы не лучше
пустого.

Время здесь не предмет: отметки сцены ОТНОСИТЕЛЬНЫЕ (`now` инъектируется в
меру), литеральной даты в файле нет вовсе.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spa_core.analytics import golive_readiness_report as grr
from spa_core.analytics.golive_readiness_report import (
    NO_WRITER,
    OBSERVED,
    UNMEASURED,
    GoLiveReadinessReport,
    _read_artifact,
)
from spa_core.monitoring import golive_artifact_outcomes as gao

# FROZEN-DATE-OK: injected-clock — `NOW` ПЕРЕДАЁТСЯ прибору и сцене аргументом
# (`drive_three_outcomes(now=NOW)`, `gao._scene(root, NOW)`), а все отметки сцены
# вычисляются ОТ него же (`_scene` берёт `now` и отнимает часы). Обе стороны
# закреплены одним якорем, стенных часов на пути теста нет — календарь этот файл
# не красит. Приём №1 `.claude/rules/deployment.md`.
NOW = datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc)


class _ChannelWithoutWriter(GoLiveReadinessReport):
    """Состояние ДО ADR-881: канал есть (ADR-878), писателя у него нет."""

    def _unmeasured_since(self, mark: int):
        return []


class _DefensiveReader(GoLiveReadinessReport):
    """Дословная прежняя дверь: `{}` на любую ошибку, ленты исходов нет."""

    def _read_json(self, path: Path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:                                           # noqa: BLE001
            return {}


class _ConflatesFromTheOtherSide(GoLiveReadinessReport):
    """Склейка с ДРУГОЙ стороны: отсутствие объявлено «не измерено».

    Нужен потому, что мера, спрашивающая только «назван ли битый», зеленела бы
    и у читателя, который валит в тот же перечень ОТВЕТ «писателя нет».
    """

    def _unmeasured_since(self, mark: int):
        return [
            reason or f"{Path(path).name}: писателя нет"
            for path, _outcome, reason in self._read_outcomes[mark:]
        ]


class InstrumentDrivesBothDirections(unittest.TestCase):
    """Мера на НАСТОЯЩЕЙ двери — и на каждой её прежней редакции."""

    def test_fixed_reader_is_measured_and_every_artifact_distinguished(self):
        report = gao.drive_three_outcomes(now=NOW)
        self.assertEqual(report["kind"], gao.THREE_OK, report.get("reason"))
        self.assertEqual(report["distinguished"], report["with_published_reader"])
        self.assertGreater(report["with_published_reader"], 0,
                           "сцена без читаемых артефактов мерила бы себя")
        self.assertEqual(report["blind"], [])

    def test_channel_without_a_writer_is_blind(self):
        """Контроль A: канал ADR-878 на месте, писателя нет ⇒ слеп."""
        report = gao.drive_three_outcomes(
            now=NOW, factory=lambda base: _ChannelWithoutWriter(base_dir=base))
        self.assertEqual(report["kind"], gao.THREE_BLIND)
        self.assertEqual(report["distinguished"], 0)
        self.assertEqual(len(report["blind"]), report["with_published_reader"])
        self.assertIn("НЕ НАЗВАН", report["reason"])

    def test_old_defensive_reader_is_blind(self):
        """Контроль B: дословная прежняя дверь `{}`-на-любую-ошибку."""
        report = gao.drive_three_outcomes(
            now=NOW, factory=lambda base: _DefensiveReader(base_dir=base))
        self.assertEqual(report["kind"], gao.THREE_BLIND)
        self.assertEqual(report["distinguished"], 0)

    def test_conflation_from_the_other_side_is_blind(self):
        """Контроль C: ОТСУТСТВИЕ, выданное за «не измерено», тоже склейка."""
        report = gao.drive_three_outcomes(
            now=NOW,
            factory=lambda base: _ConflatesFromTheOtherSide(base_dir=base))
        self.assertEqual(report["kind"], gao.THREE_BLIND)
        self.assertTrue(
            any("ОТСУТСТВИЕ названо" in line for line in report["blind"]),
            report["blind"])

    def test_unraised_scene_is_unmeasured_and_never_blind(self):
        """Третий исход МЕРЫ: сцену не поднять ⇒ `unmeasured`, не «слеп»."""
        def explode(base_dir: str):
            raise RuntimeError("сцена не поднялась по построению теста")

        report = gao.drive_three_outcomes(now=NOW, factory=explode)
        self.assertEqual(report["kind"], gao.THREE_UNMEASURED)
        self.assertIn("сцена не поднялась", report["reason"])
        self.assertNotIn("distinguished", report)

    def test_artifact_without_a_published_reader_is_a_third_state(self):
        """«Читателя нет» НАЗВАНО и слепой дверь не делает."""
        report = gao.drive_three_outcomes(now=NOW)
        no_reader = report["no_published_reader"]
        self.assertTrue(no_reader, "хоть один прежний (v9) артефакт обязан быть назван")
        self.assertEqual(report["kind"], gao.THREE_OK)
        self.assertEqual(
            report["artifacts"],
            report["with_published_reader"] + len(no_reader),
            "три состояния обязаны СКЛАДЫВАТЬСЯ в население сцены")


class ReaderDoorHasThreeOutcomes(unittest.TestCase):
    """Сама дверь: один вызов — один различимый исход."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="adr880_door_")
        self.root = Path(self._tmp.name)
        gao._scene(self.root, NOW)
        self.addCleanup(self._tmp.cleanup)

    def _read(self, rel: str):
        report = GoLiveReadinessReport(base_dir=str(self.root))
        mark = report._read_mark()
        doc = report._read_json(self.root / rel)
        return doc, report._unmeasured_since(mark), report._read_outcomes[mark:]

    def test_observed_returns_the_document_and_names_nothing(self):
        doc, unmeasured, trail = self._read("data/gate_status.json")
        self.assertEqual(trail[0][1], OBSERVED)
        self.assertEqual(unmeasured, [])
        self.assertEqual(doc["kill_switch_status"], "LOCKED")

    def test_absent_file_is_no_writer_and_is_not_called_unmeasured(self):
        (self.root / "data/gate_status.json").unlink()
        doc, unmeasured, trail = self._read("data/gate_status.json")
        self.assertEqual(trail[0][1], NO_WRITER)
        self.assertEqual(doc, {}, "ставка остаётся fail-CLOSED, как и была")
        self.assertEqual(unmeasured, [],
                         "отсутствие есть ОТВЕТ: его место — items_pending")

    def test_unparsable_file_is_unmeasured_and_is_named(self):
        (self.root / "data/gate_status.json").write_text("{ это не JSON",
                                                         encoding="utf-8")
        doc, unmeasured, trail = self._read("data/gate_status.json")
        self.assertEqual(trail[0][1], UNMEASURED)
        self.assertEqual(doc, {}, "ставка остаётся fail-CLOSED, как и была")
        self.assertEqual(len(unmeasured), 1)
        self.assertIn("gate_status.json", unmeasured[0])

    def test_absent_and_unparsable_give_DIFFERENT_outcomes(self):
        """Прямое отрицание предмета: два состояния — два исхода."""
        path = self.root / "data/gate_status.json"
        original = path.read_bytes()
        path.unlink()
        _d1, _u1, absent = self._read("data/gate_status.json")
        path.write_bytes(b"{ broken")
        _d2, _u2, broken = self._read("data/gate_status.json")
        path.write_bytes(original)
        self.assertNotEqual(absent[0][1], broken[0][1])

    def test_a_list_document_survives_the_door(self):
        """Дверь отдаёт РАЗОБРАННОЕ, а не приведённое к dict.

        `assess_financial` проверяет `isinstance(eq_data, list)`; приведение
        списка к `{}` сломало бы счёт молча.
        """
        (self.root / "data/equity_curve_daily.json").write_text(
            json.dumps([{"date": "2026-10-01", "equity": 1.0}]), encoding="utf-8")
        doc, unmeasured, trail = self._read("data/equity_curve_daily.json")
        self.assertEqual(trail[0][1], OBSERVED)
        self.assertIsInstance(doc, list)
        self.assertEqual(unmeasured, [])


class ScoreDidNotMove(unittest.TestCase):
    """Правка про ПРИЧИНУ, а не про балл — и это проверяется, а не обещается."""

    def test_healthy_scene_scores_the_same_as_the_old_defensive_reader(self):
        with tempfile.TemporaryDirectory(prefix="adr880_score_") as tmp:
            root = Path(tmp)
            gao._scene(root, NOW)
            new = GoLiveReadinessReport(base_dir=str(root)).to_dict()
            old = _DefensiveReader(base_dir=str(root)).to_dict()
        self.assertEqual(new["total_score"], old["total_score"])
        self.assertEqual(new["overall_status"], old["overall_status"])
        self.assertEqual(new["estimated_days_to_ready"],
                         old["estimated_days_to_ready"])

    def test_broken_artifact_scores_the_same_as_the_old_reader(self):
        """И на ПЛОХОМ входе ставка та же: fail-CLOSED не ослаблен."""
        with tempfile.TemporaryDirectory(prefix="adr880_score2_") as tmp:
            root = Path(tmp)
            gao._scene(root, NOW)
            (root / "data/golive_status.json").write_text("{ broken",
                                                          encoding="utf-8")
            new = GoLiveReadinessReport(base_dir=str(root)).to_dict()
            old = _DefensiveReader(base_dir=str(root)).to_dict()
        self.assertEqual(new["total_score"], old["total_score"])
        self.assertGreater(
            sum(len(c["items_unmeasured"]) for c in new["categories"])
            + len(new["estimated_days_unmeasured"]), 0,
            "балл тот же, но ПРИЧИНА обязана быть названа")
        self.assertEqual(
            sum(len(c["items_unmeasured"]) for c in old["categories"]), 0,
            "положительный контроль: прежняя дверь не называла ничего")


class DayEstimateCarriesItsThirdOutcome(unittest.TestCase):
    """Срок — публикуемое ЧИСЛО вне категорий, и у него свой перечень."""

    def _scene(self):
        tmp = tempfile.TemporaryDirectory(prefix="adr880_days_")
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        gao._scene(root, NOW)
        return root

    def test_healthy_scene_names_nothing(self):
        root = self._scene()
        days, unmeasured = GoLiveReadinessReport(
            base_dir=str(root)).estimated_days_to_ready_with_outcome()
        self.assertIsInstance(days, int)
        self.assertEqual(unmeasured, [])

    def test_unparsable_estimate_artifact_is_named_beside_the_number(self):
        root = self._scene()
        (root / "data/backtest/owner_paper_acceptance.json").write_text(
            "{ broken", encoding="utf-8")
        report = GoLiveReadinessReport(base_dir=str(root))
        days, unmeasured = report.estimated_days_to_ready_with_outcome()
        self.assertIsInstance(days, int)
        self.assertTrue(any("owner_paper_acceptance.json" in line
                            for line in unmeasured), unmeasured)
        self.assertEqual(report.estimated_days_to_ready(), days,
                         "подпись прежнего читателя не изменилась")
        self.assertEqual(report.to_dict()["estimated_days_unmeasured"],
                         unmeasured)

    def test_markdown_does_not_print_the_number_as_measured(self):
        root = self._scene()
        (root / "data/backtest/owner_paper_acceptance.json").write_text(
            "{ broken", encoding="utf-8")
        text = GoLiveReadinessReport(base_dir=str(root)).to_markdown()
        self.assertIn("НЕ ИЗМЕРЕНО ПОЛНОСТЬЮ", text)
        self.assertIn("owner_paper_acceptance.json", text)

    def test_markdown_on_a_healthy_scene_says_nothing_of_the_kind(self):
        """Обратная сторона: без неизмеренного строка остаётся прежней."""
        root = self._scene()
        text = GoLiveReadinessReport(base_dir=str(root)).to_markdown()
        self.assertNotIn("НЕ ИЗМЕРЕНО ПОЛНОСТЬЮ", text)


class CategoriesCarryTheirOwnUnmeasured(unittest.TestCase):
    """Перечень принадлежит КАТЕГОРИИ, а не отчёту целиком."""

    def test_only_the_category_that_read_it_names_the_artifact(self):
        with tempfile.TemporaryDirectory(prefix="adr880_cat_") as tmp:
            root = Path(tmp)
            gao._scene(root, NOW)
            (root / "data/capital_config.json").write_text("{ broken",
                                                           encoding="utf-8")
            doc = GoLiveReadinessReport(base_dir=str(root)).to_dict()
        naming = [c["name"] for c in doc["categories"]
                  if any("capital_config.json" in line
                         for line in c["items_unmeasured"])]
        self.assertEqual(naming, ["financial"],
                         "перечень, собранный на весь отчёт, не сказал бы ГДЕ")

    def test_data_sources_adds_both_halves_of_its_unmeasured(self):
        """ADR-878 (три двери писателя) и ADR-881 (общая дверь) СКЛАДЫВАЮТСЯ."""
        with tempfile.TemporaryDirectory(prefix="adr880_ds_") as tmp:
            root = Path(tmp)
            gao._scene(root, NOW)
            # Своя половина: артефакт писателя ЕСТЬ, но не разбирается.
            # Отсутствующий сюда не годится — отсутствие это ОТВЕТ
            # (`no_writer`), и его место в `items_pending` (ADR-879).
            (root / "data/adapter_status.json").write_text(
                "{ broken", encoding="utf-8")
            own = GoLiveReadinessReport(
                base_dir=str(root)).assess_data_sources(now=NOW)
            # вторая половина: общий читатель не разобрал источник
            (root / "data/backtest/source_pipeline.json").write_text(
                "{ broken", encoding="utf-8")
            both = GoLiveReadinessReport(
                base_dir=str(root)).assess_data_sources(now=NOW)
        self.assertTrue(own.items_unmeasured, "своя половина обязана быть непуста")
        self.assertGreater(len(both.items_unmeasured), len(own.items_unmeasured))
        self.assertTrue(any("source_pipeline.json" in line
                            for line in both.items_unmeasured))


class ReaderReachabilityNeedsEverySegment(unittest.TestCase):
    """`_is_read_by` — ВСЕ отрезки пути, а не любой.

    Мутация «достаточно одного отрезка» переживала прогон по дельте: сегодняшнее
    население сцены её не различает (у `data/paper/evidence_v2.json` в
    публикуемом тексте нет НИ ОДНОГО отрезка, а у остальных отрезок один, и
    тогда «любой» совпадает с «все»). Свидетеля у многосоставного случая не
    было — значит претензию `all` не мерил никто; здесь он измеряется прямо.
    """

    SURFACE = 'x = self.data_dir / "paper" / "something_else.json"'

    def test_shared_directory_segment_alone_is_not_a_reader(self):
        self.assertFalse(
            gao._is_read_by(self.SURFACE, "data/paper/evidence_v2.json"),
            "общий каталог «paper» читателем КОНКРЕТНОГО файла не делает")

    def test_every_segment_present_is_a_reader(self):
        self.assertTrue(
            gao._is_read_by(self.SURFACE, "data/paper/something_else.json"))

    def test_data_and_backtest_are_not_asked_about(self):
        """Корневые отрезки отбрасываются: они есть у всех путей разом."""
        surface = 'y = self.backtest_dir / "paper_ready_gate.json"'
        self.assertTrue(
            gao._is_read_by(surface, "data/backtest/paper_ready_gate.json"))


class SceneIsItsOwn(unittest.TestCase):
    """Прибор не смотрит в боевое дерево — иначе в CI он не мерил бы ничего."""

    def test_scene_is_laid_inside_the_given_root_only(self):
        with tempfile.TemporaryDirectory(prefix="adr880_root_") as tmp:
            root = Path(tmp)
            laid = gao._scene(root, NOW)
            self.assertTrue(laid)
            for rel in laid:
                self.assertTrue((root / rel).is_file(), rel)

    def test_stamps_are_relative_to_the_injected_clock(self):
        """Отметки сцены происходят от `now`, а не от стенных часов."""
        far = NOW - timedelta(days=400)
        with tempfile.TemporaryDirectory(prefix="adr880_clock_") as tmp:
            root = Path(tmp)
            gao._scene(root, far)
            doc = json.loads((root / "data/gate_status.json").read_text())
        self.assertTrue(doc["timestamp"].startswith(str(far.year)),
                        doc["timestamp"])


if __name__ == "__main__":                                          # pragma: no cover
    unittest.main()
