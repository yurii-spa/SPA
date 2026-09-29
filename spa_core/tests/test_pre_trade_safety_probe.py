"""ADR-512 — критерий §49 `Pre-trade safety` приказа CIO получает МАШИННУЮ мерку.

Почему этот файл существует
---------------------------
Перепись повторной проверки перед исполнением
(`spa_core/monitoring/pre_trade_recheck_census.py`, цикл #708) меряет критерий
владельца «Каждый trade пересчитывается непосредственно перед execution» с
сентября: её артефакт пишется ступенью моста в такте и свеж (замер 29.09 — 6,2 ч
при объявленном пределе 12 ч). А сводный замер §49
(`scripts/cio_acceptance_rollup.py`) про этот критерий отвечал

    «машинной пробы, объявившей себя мерой этого критерия, в реестре НЕТ —
     вердикт сегодня взять неоткуда»

потому что запись «этот прибор есть мера этого критерия» лежала ПРОЗОЙ, а сводку
читает машина (ADR-504, ADR-506). Это ПЯТАЯ и последняя привязка цены
`TRANSCRIPTION` — по образцу `Economics` (ADR-507), `Persistence` (ADR-508),
`Risk` (ADR-510) и `Anti-churn` (ADR-511), тоже по одному и со своим контролем в
обе стороны.

Что здесь закреплено, и в ОБЕ стороны
-------------------------------------
* проба `trade_is_rechecked_immediately_before_execution` зелена на целом контуре
  и красна на КАЖДОМ порванном звене — с названным звеном;
* `WARNING` прибора («нашлось исполнение без второго наблюдения входов»)
  переносится в `not_satisfied`, `CRITICAL` — тоже, третий исход — в `unmeasured`;
* **вопрос о законности вердикта задаётся ТОЛЬКО на зелёном пути** — и это
  предмет отдельного класса контроля. Доказательство прибора одностороннее:
  `WARNING` есть утверждение СУЩЕСТВОВАНИЯ (нашлось исполнение, стоявшее на том
  же наблюдении, что и предложение), и ни дыра в записи, ни возраст дерева его не
  отменяют; `OK` есть утверждение обо ВСЕХ, и оно рушится от любой неполноты
  материала. Спросить о гигиене раньше значило бы превратить измеренную находку
  владельца (46 из 46 без второго наблюдения) в «НЕ ИЗМЕРЕНО» — зеркальный дефект
  к «не измерено, выданному за чисто»;
* законность зелёного спрашивается ДВУМЯ вопросами, и у каждого свой предмет:
  возраст стоящей книги (живо ли дерево) и ПОКРЫТИЕ — знает ли цепочка аудита все
  ходы журнала. Ход, о котором цепочка не знает, не осматривается вовсе, и «у
  каждого хода была повторная проверка» относилось бы к ВЫБОРКЕ;
* своего порога у пробы НЕТ ни одного: допуск свежести входа — ручка ВЛАДЕЛЬЦА
  (§22 «Не hardcode»), и вердикт следует ЕЙ, а не литералу пробы;
* прибор, не объявивший себя мерой `§49 Pre-trade safety`, ⇒ `unmeasured`; якорь
  читается как НАЧАЛО строки, а не как вхождение подстроки (ADR-333);
* неизвестный статус прибора ⇒ `unmeasured` (fail-CLOSED), а не `satisfied`;
* `data_dir`, `repo_root` и `now` ДОХОДЯТ и до пробы, и до прибора — ВСЕ двери, а
  не одна («половина инъекции», `.claude/rules/deployment.md`), и проверяется это
  по ИСХОДУ пробы, а не по наличию аргумента;
* объявление `s49_criterion` указывает в население §49 живого приказа.

Порядок контроля НЕ произволен: сначала доказывается, что фикстуры дают ИМЕННО те
породы прибора (`TestFixturesReproduceTheMeasuredKinds`), и только потом — что
проба на них отвечает. Без первого шага «красно на порванном звене» тавтологично.

Часы — вход: якорь вычисляется ВНУТРИ теста (не на импорте — ADR-348) и подаётся
и в фикстуры, и в пробу. Литеральных дат в файле нет вовсе. Сеть не трогается,
живое `data/` не читается: материал пишется в одноразовый каталог.
"""
from __future__ import annotations

import json
import unittest
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from spa_core.monitoring import book_oscillation_census as boc
from spa_core.monitoring import card_acceptance as ca
from spa_core.monitoring import pre_trade_recheck_census as ptc
from spa_core.tests._freshness import now_utc

#: Имя пробы в реестре. Проверяется как ИМЯ (равенство), не как подстрока — ADR-333.
PROBE_NAME = "trade_is_rechecked_immediately_before_execution"
#: Критерий §49, мерой которого проба себя объявляет.
CRITERION = "Pre-trade safety"

#: Книга сцены. Состав и суммы здесь безразличны прибору (он судит цепочку
#: аудита), но книга обязана СТОЯТЬ: её возраст и есть вопрос о живости дерева.
BOOK = {"aave_v3": 60_000.0, "compound_v3": 40_000.0}


class _Base(unittest.TestCase):
    """Одноразовый каталог: цепочка аудита, журнал ходов и стоящая книга."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name)
        # Якорь считается здесь, а не на импорте: анкер времени, вычисленный при
        # сборе тестов, краснеет от ДЛИТЕЛЬНОСТИ прогона (ADR-348).
        self.now = now_utc()
        # Дерево сцены — ОДНОРАЗОВОЕ, и это не удобство. Ось читателей гейта
        # прибор меряет, разбирая КАЖДЫЙ `.py` дерева: на живом репозитории это
        # тысячи файлов на каждый зов пробы, то есть контроль, который никто не
        # станет гонять. Одноразовое дерево к тому же ЧЕСТНЕЕ: состав читателей в
        # нём объявлен сценой, а не заимствован у сегодняшнего репозитория —
        # иначе контроль краснел бы от чужой правки. Живое дерево мерится
        # ОТДЕЛЬНЫМ классом (`TestTheLiveTreeIsMeasuredToo`), одним зовом.
        self.repo_root = self._one_off_tree()

    def _one_off_tree(self) -> str:
        """Дерево с модулем повторной проверки и ОДНИМ инертным читателем.

        Ровно та форма, которую прибор различает: инертный читатель объявлен
        списком `GATE_INERT_CALLERS`, читателей на денежном пути нет — как и в
        живом репозитории (инвариант #6 их запрещает).
        """
        root = self.data_dir / "tree"
        gate = root / ptc.GATE_MODULE
        gate.parent.mkdir(parents=True, exist_ok=True)
        gate.write_text("class PreExecutionSafety:\n    pass\n", encoding="utf-8")
        inert = root / ptc.GATE_INERT_CALLERS[0]
        inert.parent.mkdir(parents=True, exist_ok=True)
        inert.write_text(
            f"from {ptc.GATE_MODULE_DOTTED.rsplit('.', 1)[0]} import "
            f"{ptc.GATE_MODULE_DOTTED.rsplit('.', 1)[1]}\n", encoding="utf-8")
        return str(root)

    # ── материал ────────────────────────────────────────────────────────────

    def _events(self, count: int, *, second_observation: bool,
                recheck_event: bool = False, window_s: float = 1.0,
                reach_proposal: bool = True) -> list:
        """Цепочка аудита из `count` исполнений одной породы.

        Порода задаётся ровно теми двумя признаками, которыми её различает прибор:
        изменился ли ярлык наблюдения (`snapshot_id`) между предложением и
        исполнением, и стои́т ли в цепочке событие повторной проверки.
        """
        rows: list = []
        for i in range(count):
            tid = f"T{i + 1:03d}"
            prop_ts = self.now - timedelta(days=count - i, seconds=window_s)
            exec_ts = prop_ts + timedelta(seconds=window_s)
            prop_snap = f"{prop_ts.date().isoformat()}:snap-p{i}"
            exec_snap = (f"{exec_ts.date().isoformat()}:snap-e{i}"
                         if second_observation else prop_snap)
            prev = None
            if reach_proposal:
                rows.append({"event_id": f"p{i}",
                             "event_type": ptc.EVENT_PROPOSAL,
                             "timestamp": prop_ts.isoformat(),
                             "snapshot_id": prop_snap,
                             "prev_event_id": None,
                             "data": {"trade_id": tid}})
                prev = f"p{i}"
            if recheck_event:
                rows.append({"event_id": f"r{i}",
                             "event_type": ptc.RECHECK_EVENT_TYPES[0],
                             "timestamp": exec_ts.isoformat(),
                             "snapshot_id": prop_snap,
                             "prev_event_id": prev,
                             "data": {"trade_id": tid}})
                prev = f"r{i}"
            rows.append({"event_id": f"e{i}",
                         "event_type": ptc.EVENT_EXECUTED,
                         "timestamp": exec_ts.isoformat(),
                         "snapshot_id": exec_snap,
                         "prev_event_id": prev,
                         "data": {"trade_id": tid}})
        return rows

    def _write(self, rows: list, *, move_ids: "list | None" = None,
               write_chain: bool = True, write_journal: bool = True,
               write_book: bool = True, book_age_days: float = 0.0,
               book_stamp: "str | None" = None) -> None:
        """Выложить материал сцены. По умолчанию — ЦЕЛЫЙ контур.

        `move_ids` не задан ⇒ журнал ходов повторяет ярлыки исполнений цепочки,
        то есть покрытие полное по построению. Сцены дыры в записи задают его явно.
        """
        if write_chain:
            (self.data_dir / ptc.CHAIN_FILENAME).write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                encoding="utf-8")
        if write_journal:
            ids = move_ids if move_ids is not None else [
                (r.get("data") or {}).get("trade_id") for r in rows
                if r.get("event_type") == ptc.EVENT_EXECUTED]
            moves = [{"trade_id": tid, "ts": (self.now - timedelta(days=1)).isoformat(),
                      "type": "rebalance", "from_allocation": BOOK,
                      "to_allocation": BOOK, "capital": 100_000.0}
                     for tid in ids]
            (self.data_dir / boc.JOURNAL_NAME).write_text(
                json.dumps(moves, ensure_ascii=False), encoding="utf-8")
        if write_book:
            stamp = book_stamp if book_stamp is not None else (
                self.now - timedelta(days=book_age_days)).isoformat()
            doc: dict = {"positions": BOOK}
            if stamp:
                doc["generated_at"] = stamp
            (self.data_dir / ca.STANDING_BOOK_FILE).write_text(
                json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    # ── сцены ───────────────────────────────────────────────────────────────

    def scene_every_execution_rechecked(self, **kw) -> None:
        """Целый контур: у каждого исполнения входы наблюдались ЗАНОВО."""
        self._write(self._events(3, second_observation=True), **kw)

    def scene_recheck_event_instead_of_new_snapshot(self, **kw) -> None:
        """Второй признак второго взгляда: событие повторной проверки в цепочке."""
        self._write(self._events(3, second_observation=False, recheck_event=True), **kw)

    def scene_no_second_observation(self, **kw) -> None:
        """Находка владельца: исполнение стои́т на ТОМ ЖЕ наблюдении."""
        self._write(self._events(3, second_observation=False), **kw)

    def scene_untraceable_chain(self, **kw) -> None:
        """Цепочка не доходит до предложения — третий исход, а не «проверки не было»."""
        self._write(self._events(2, second_observation=False, reach_proposal=False), **kw)

    # ── прогон ──────────────────────────────────────────────────────────────

    def census(self, *, now=None, tolerance_s=None) -> dict:
        return ptc.run_census(self.data_dir, now=now or self.now,
                              repo_root=Path(self.repo_root),
                              tolerance_s=tolerance_s)

    def probe(self, *, now=None, data_dir=None, repo_root=None) -> tuple:
        fn = ca.PROBES[PROBE_NAME]
        return fn(None, now=now or self.now,
                  data_dir=str(data_dir or self.data_dir),
                  repo_root=str(repo_root or self.repo_root))


# ---------------------------------------------------------------------------
# 1. Фикстуры дают ИМЕННО породы прибора — иначе «красно» тавтологично
# ---------------------------------------------------------------------------

class TestFixturesReproduceTheMeasuredKinds(_Base):

    def test_new_snapshot_per_execution_is_the_OK_species(self) -> None:
        self.scene_every_execution_rechecked()
        report = self.census()
        self.assertEqual(ptc.STATUS_OK, report["status"])
        self.assertEqual(0, report["no_recheck"])
        self.assertEqual(3, report["recheck_present"])

    def test_a_recheck_event_is_the_OK_species_too(self) -> None:
        """OK достижим ДВУМЯ путями, и оба — признак второго взгляда на мир."""
        self.scene_recheck_event_instead_of_new_snapshot()
        report = self.census()
        self.assertEqual(ptc.STATUS_OK, report["status"])
        self.assertEqual(3, report["recheck_present"])

    def test_same_snapshot_and_no_recheck_is_the_WARNING_species(self) -> None:
        self.scene_no_second_observation()
        report = self.census()
        self.assertEqual(ptc.STATUS_WARNING, report["status"])
        self.assertEqual(3, report["no_recheck"])

    def test_owner_tolerance_turns_the_same_scene_CRITICAL(self) -> None:
        """CRITICAL — порода ВЛАДЕЛЬЦА: она появляется от его допуска, не от сцены."""
        self.scene_no_second_observation()
        self.assertEqual(ptc.STATUS_WARNING, self.census()["status"])
        report = self.census(tolerance_s=0.0)
        self.assertEqual(ptc.STATUS_CRITICAL, report["status"])
        self.assertEqual(3, report["stale_beyond_tolerance"])

    def test_untraceable_chain_is_the_third_outcome(self) -> None:
        self.scene_untraceable_chain()
        report = self.census()
        self.assertFalse(report["measured"])
        self.assertEqual(ptc.STATUS_UNMEASURED, report["status"])

    def test_absent_chain_is_the_third_outcome(self) -> None:
        self._write([], write_chain=False)
        self.assertFalse(self.census()["measured"])

    def test_chain_without_executions_is_the_third_outcome(self) -> None:
        """Пустой предмет НЕ есть «повторная проверка на месте» (инв. #17)."""
        self._write([{"event_id": "p0", "event_type": ptc.EVENT_PROPOSAL,
                      "timestamp": self.now.isoformat(), "snapshot_id": "s",
                      "prev_event_id": None, "data": {}}], move_ids=[])
        report = self.census()
        self.assertFalse(report["measured"])
        self.assertIn("trade_executed", report["reason"])

    def test_the_instrument_publishes_the_composition_not_only_the_count(self) -> None:
        """Без состава ярлыков вопрос о покрытии задать НЕЧЕМ (цикл #729)."""
        self.scene_every_execution_rechecked()
        identity = self.census()["identity"]
        self.assertEqual(["T001", "T002", "T003"], identity["labels"])
        self.assertEqual(3, identity["distinct_labels"])

    def test_the_unmeasured_report_says_the_composition_is_absent_not_empty(self) -> None:
        self._write([], write_chain=False)
        self.assertIsNone(self.census()["identity"]["labels"])


# ---------------------------------------------------------------------------
# 2. Проба ПЕРЕНОСИТ вердикт прибора — и ни одного своего правила
# ---------------------------------------------------------------------------

class TestProbeTransfersTheVerdict(_Base):

    def test_whole_contour_is_satisfied(self) -> None:
        self.scene_every_execution_rechecked()
        verdict, detail = self.probe()
        self.assertEqual(ca.SATISFIED, verdict)
        self.assertIn("наблюдались ЗАНОВО", detail)

    def test_recheck_event_contour_is_satisfied_too(self) -> None:
        self.scene_recheck_event_instead_of_new_snapshot()
        self.assertEqual(ca.SATISFIED, self.probe()[0])

    def test_no_second_observation_is_not_satisfied(self) -> None:
        self.scene_no_second_observation()
        verdict, detail = self.probe()
        self.assertEqual(ca.NOT_SATISFIED, verdict)
        self.assertIn("заново не пересчитывается", detail)

    def test_the_verdict_follows_the_owner_dial_not_a_literal_of_the_probe(self) -> None:
        """Допуск свежести — ручка владельца. Проба своего порога НЕ имеет."""
        self.scene_no_second_observation()
        self.assertIn("НЕ ИЗМЕРЕН", self.probe()[1])
        with patch.object(ptc, "load_owner_tolerance",
                          return_value={"measured": True, "reason": None,
                                        "dials": {"mode": "paper"},
                                        "tolerance_dial": "input_max_age_s",
                                        "tolerance_s": 0.0,
                                        "ttl_dial": "input_max_age_s",
                                        "version": "v1.1", "mode": "paper"}):
            verdict, detail = self.probe()
        self.assertEqual(ca.NOT_SATISFIED, verdict)
        self.assertIn("старше объявленного владельцем допуска 3", detail)

    def test_third_outcome_of_the_instrument_is_unmeasured(self) -> None:
        self.scene_untraceable_chain()
        verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("отказалась мерить", detail)

    def test_todays_second_support_of_the_red_is_printed(self) -> None:
        """Красное не только про историю: читателей гейта прибор меряет ПО ДЕРЕВУ."""
        self.scene_no_second_observation()
        self.assertIn("на денежном пути", self.probe()[1])


# ---------------------------------------------------------------------------
# 3. Находка цикла: вопрос о законности задаётся ТОЛЬКО на зелёном пути
# ---------------------------------------------------------------------------

class TestLegitimacyIsAskedOnlyOnTheGreenPath(_Base):

    # ── зелёный путь: гигиена материала обязана его останавливать ───────────

    def test_stale_standing_book_is_unmeasured_although_the_instrument_says_OK(self) -> None:
        self.scene_every_execution_rechecked(
            book_age_days=ca.STANDING_BOOK_MAX_AGE_D + 1)
        self.assertEqual(ptc.STATUS_OK, self.census()["status"])
        verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("стоящая книга протухла", detail)
        self.assertIn("тишиной мёртвого дерева", detail)

    def test_missing_standing_book_is_unmeasured(self) -> None:
        self.scene_every_execution_rechecked(write_book=False)
        verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("не прочитана", detail)

    def test_standing_book_without_a_stamp_is_unmeasured(self) -> None:
        self.scene_every_execution_rechecked(book_stamp="")
        verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("нет отметки `generated_at`", detail)

    def test_standing_book_stamp_that_is_not_a_date_is_unmeasured(self) -> None:
        self.scene_every_execution_rechecked(book_stamp="не-дата")
        verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("не разобрана как дата", detail)

    def test_a_move_the_chain_never_saw_is_unmeasured_never_satisfied(self) -> None:
        """Самый дорогой контроль зелёного пути: иначе `satisfied` о ВЫБОРКЕ."""
        self.scene_every_execution_rechecked()
        self._write(self._events(3, second_observation=True),
                    move_ids=["T001", "T002", "T003", "T099"])
        self.assertEqual(ptc.STATUS_OK, self.census()["status"])
        verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("знает не все ходы книги", detail)
        self.assertIn("T099", detail)

    def test_absent_move_journal_is_unmeasured_on_the_green_path(self) -> None:
        self.scene_every_execution_rechecked(write_journal=False)
        verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("журнал ходов не прочитан", detail)

    def test_empty_move_journal_is_unmeasured_not_full_coverage(self) -> None:
        self.scene_every_execution_rechecked(move_ids=[])
        verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("пуст или не является списком", detail)

    def test_a_move_without_a_label_is_unmeasured_not_covered(self) -> None:
        self.scene_every_execution_rechecked()
        (self.data_dir / boc.JOURNAL_NAME).write_text(
            json.dumps([{"ts": self.now.isoformat()}]), encoding="utf-8")
        verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("нет ярлыка `trade_id`", detail)

    # ── красный путь: та же гигиена НЕ ИМЕЕТ ПРАВА погасить находку ─────────

    def test_a_stale_tree_does_not_hide_the_finding(self) -> None:
        """Иначе измеренная находка владельца стала бы «НЕ ИЗМЕРЕНО» от гигиены."""
        self.scene_no_second_observation(
            book_age_days=ca.STANDING_BOOK_MAX_AGE_D + 10)
        verdict, detail = self.probe()
        self.assertEqual(ca.NOT_SATISFIED, verdict)
        self.assertIn("НЕ задаётся", detail)

    def test_a_hole_in_the_record_does_not_hide_the_finding(self) -> None:
        self.scene_no_second_observation()
        self._write(self._events(3, second_observation=False),
                    move_ids=["T001", "T002", "T003", "T099"])
        self.assertEqual(ca.NOT_SATISFIED, self.probe()[0])

    def test_no_journal_and_no_book_at_all_does_not_hide_the_finding(self) -> None:
        self.scene_no_second_observation(write_journal=False, write_book=False)
        self.assertEqual(ca.NOT_SATISFIED, self.probe()[0])

    def test_the_asymmetry_is_a_property_of_the_direction_not_of_the_scene(self) -> None:
        """ОДИН И ТОТ ЖЕ порванный материал: зелёный путь встаёт, красный идёт."""
        broken = dict(book_age_days=ca.STANDING_BOOK_MAX_AGE_D + 5)
        self.scene_every_execution_rechecked(**broken)
        green = self.probe()
        self.scene_no_second_observation(**broken)
        red = self.probe()
        self.assertEqual(ca.UNMEASURED, green[0])
        self.assertEqual(ca.NOT_SATISFIED, red[0])


# ---------------------------------------------------------------------------
# 4. Объявление прибора: по ЯКОРЮ, а не подстрокой (ADR-333)
# ---------------------------------------------------------------------------

class TestDeclarationIsCheckedByAnchor(_Base):

    def test_an_instrument_that_declares_nothing_is_unmeasured(self) -> None:
        self.scene_every_execution_rechecked()
        with patch.object(ptc, "CRITERION", ""):
            verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("не объявляет себя мерой", detail)

    def test_the_anchor_is_read_as_the_beginning_not_as_a_substring(self) -> None:
        """Заметка, УПОМИНАЮЩАЯ критерий, мерой его не делает."""
        self.scene_every_execution_rechecked()
        with patch.object(ptc, "CRITERION",
                          "заметка про §49 Pre-trade safety и предпусковые проверки"):
            self.assertEqual(ca.UNMEASURED, self.probe()[0])

    def test_a_neighbouring_criterion_is_not_accepted(self) -> None:
        self.scene_every_execution_rechecked()
        with patch.object(ptc, "CRITERION", "§49 Anti-churn — книга не прыгает"):
            self.assertEqual(ca.UNMEASURED, self.probe()[0])

    def test_the_live_instrument_does_declare_the_anchor(self) -> None:
        """Положительный контроль якоря: иначе он был бы красен всегда."""
        self.assertTrue(ptc.CRITERION.startswith(f"§49 {CRITERION}"))


# ---------------------------------------------------------------------------
# 5. Fail-CLOSED: любая неожиданность — `unmeasured`, никогда `satisfied`
# ---------------------------------------------------------------------------

class TestFailClosed(_Base):

    def test_an_instrument_that_cannot_be_imported_is_unmeasured(self) -> None:
        with patch.object(ca, "PRE_TRADE_RECHECK_MODULE",
                          "spa_core.monitoring.no_such_census_module"):
            verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("не загружена", detail)

    def test_an_instrument_that_raises_is_unmeasured(self) -> None:
        self.scene_every_execution_rechecked()
        with patch.object(ptc, "run_census", side_effect=RuntimeError("прибор упал")):
            verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("упала", detail)

    def test_an_unknown_status_is_unmeasured_not_satisfied(self) -> None:
        self.scene_every_execution_rechecked()
        report = dict(self.census(), status="ЧТО-ТО НОВОЕ")
        with patch.object(ptc, "run_census", return_value=report):
            verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("не переносится", detail)

    def test_a_report_without_the_label_composition_is_unmeasured(self) -> None:
        """Проба читает состав У ПРИБОРА и своего чтения цепочки не имеет."""
        self.scene_every_execution_rechecked()
        report = self.census()
        report["identity"] = dict(report["identity"], labels=None)
        with patch.object(ptc, "run_census", return_value=report):
            verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("СОСТАВ ярлыков цепочки", detail)

    def test_an_identity_axis_that_was_not_measured_is_unmeasured(self) -> None:
        self.scene_every_execution_rechecked()
        report = self.census()
        report["identity"] = {"measured": False, "reason": "ось не измерена",
                              "labels": None}
        with patch.object(ptc, "run_census", return_value=report):
            verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("ось ярлыков", detail)

    def test_the_journal_name_is_a_reference_not_a_second_literal(self) -> None:
        """Имя журнала снято у переписи прыжков книги: своего литерала здесь НЕТ."""
        self.scene_every_execution_rechecked()
        with patch.object(boc, "JOURNAL_NAME", ""):
            verdict, detail = self.probe()
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("имя журнала ходов не объявлено", detail)


# ---------------------------------------------------------------------------
# 6. Все двери к окружению закрыты: часы и ОБА дерева доходят ПО ИСХОДУ
# ---------------------------------------------------------------------------

class TestClockAndTreesReachTheProbe(_Base):

    def test_the_clock_changes_the_outcome_of_the_probe_itself(self) -> None:
        """Контроль на ИСХОД, а не на наличие аргумента («половина инъекции»)."""
        self.scene_every_execution_rechecked()
        near = self.probe()
        later = self.probe(now=self.now + timedelta(
            days=ca.STANDING_BOOK_MAX_AGE_D + 1))
        self.assertEqual(ca.SATISFIED, near[0])
        self.assertEqual(ca.UNMEASURED, later[0])
        self.assertIn("протухла", later[1])

    def test_the_clock_reaches_the_instrument_too_measured_by_the_probes_own_answer(
            self) -> None:
        """Вторая дверь — ИСХОДОМ пробы, а не прогоном прибора напрямую.

        Гонять прибор рядом было бы «половиной инъекции» наоборот: контроль был
        бы зелен и тогда, когда проба часы прибору не передаёт вовсе. Поэтому
        отметка замера печатается в пояснении, и спрашивается она у ПРОБЫ.
        """
        self.scene_no_second_observation()
        early = self.probe()
        shifted = self.now + timedelta(hours=1)
        late = self.probe(now=shifted)
        self.assertIn(f"замер снят {self.now.isoformat()}", early[1])
        self.assertIn(f"замер снят {shifted.isoformat()}", late[1])

    def test_the_data_dir_reaches_the_probe(self) -> None:
        with TemporaryDirectory() as empty:
            verdict, detail = self.probe(data_dir=empty)
        self.assertEqual(ca.UNMEASURED, verdict)
        self.assertIn("цепочки аудита нет на диске", detail)

    def test_the_repo_root_reaches_the_gate_axis(self) -> None:
        """Ось читателей гейта мерится ПО ДЕРЕВУ: чужое дерево = третий исход."""
        self.scene_no_second_observation()
        with TemporaryDirectory() as bare:
            verdict, detail = self.probe(repo_root=bare)
        self.assertEqual(ca.NOT_SATISFIED, verdict)
        self.assertIn("НЕ измерены", detail)

    def test_the_declared_inputs_match_what_the_probe_accepts(self) -> None:
        self.assertEqual(("repo_root", "data_dir"), ca.probe_tree_inputs(PROBE_NAME))


# ---------------------------------------------------------------------------
# 7. Реестр и объявление предмета
# ---------------------------------------------------------------------------

class TestRegistryAndDeclaration(_Base):

    def test_the_probe_is_registered_under_its_name(self) -> None:
        self.assertIn(PROBE_NAME, ca.PROBES)
        self.assertIsNone(ca.validate_spec(PROBE_NAME))

    def test_the_probe_declares_the_criterion_of_the_order(self) -> None:
        self.assertEqual({CRITERION: [PROBE_NAME]},
                         {k: v for k, v in ca.probes_by_s49_criterion().items()
                          if k == CRITERION})

    def test_the_dispatcher_runs_it_and_passes_both_trees(self) -> None:
        """Путь читателя целиком: объявление → реестр → вердикт."""
        self.scene_no_second_observation()
        verdict, detail = ca.run_probe(PROBE_NAME, repo_root=self.repo_root,
                                       data_dir=str(self.data_dir))
        self.assertEqual(ca.NOT_SATISFIED, verdict)
        self.assertIn("заново не пересчитывается", detail)


# ---------------------------------------------------------------------------
# 8. Живое дерево мерится ТОЖЕ — но одним зовом, а не в каждой сцене
# ---------------------------------------------------------------------------

class TestTheLiveTreeIsMeasuredToo(_Base):

    def test_the_gate_has_no_money_path_reader_in_this_very_tree(self) -> None:
        """Сегодняшняя опора красного вердикта: замер ЭТОГО репозитория.

        Инвариант #6 запрещает бумажному коду импортировать
        `spa_core/execution/`, поэтому у модуля повторной проверки читателя на
        денежном пути быть не может — и это не довод, а замер: ось называет
        каждого зовущего по имени. Ось НЕ измерена ⇒ падать ГРОМКО: «читателей
        нет» и «не смотрели» обязаны быть различимы (инв. #17).
        """
        self.scene_no_second_observation()
        verdict, detail = self.probe(repo_root=ca.REPO_ROOT)
        axis = ptc.gate_reader_axis(Path(ca.REPO_ROOT))
        if not axis["measured"]:
            self.fail(f"ось читателей гейта НЕ ИЗМЕРЕНА в живом дереве: "
                      f"{axis['reason']} — предпосылка контроля не обеспечена")
        self.assertEqual([], axis["money_path_callers"])
        self.assertEqual(ca.NOT_SATISFIED, verdict)
        self.assertIn("на денежном пути 0", detail)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
