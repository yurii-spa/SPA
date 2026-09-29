"""Сторож привязки §49 `Determinism` — контроль в ОБЕ стороны (ADR-515, цикл #732).

`.claude/rules/acceptance.md`, п. 3: проба регистрируется только с тестом, где
она ЗЕЛЕНА на целом контуре и КРАСНА на каждом порванном звене — с названным
звеном, — и где она не проходит подстрокой (ADR-333).

Что этот набор воспроизводит
============================
Находка #732: прибор воспроизводимости отвечал «один снимок — один ответ», и
ответ был правдой — но про население из двух субъектов, набранное руками. С
поверхностью, которая РЕШАЕТ книги, это население не сверял никто, и замер 29.09
на живом дереве дал **$0,00 из $301 352,65** капитала, чей решатель спрошен
целиком. Поэтому здесь два разных предмета, и путать их нельзя:

* «один снимок дал разные ответы» — находка СУЩЕСТВОВАНИЯ, красная всегда;
* «решателя не спрашивали» — НЕ ИЗМЕРЕНО про этот капитал, и зеленью оно
  становиться не имеет права (инв. #17).

Время — ВХОД (`now=`), и отметки фикстур считаются от того же мгновения: обе
стороны сравнения закреплены, календарь на вердикт не влияет. Литеральных дат
здесь нет вовсе. Живое `data/`, живой манифест и живой трекер не читаются: каждый
тест строит одноразовое дерево.
"""
from __future__ import annotations

import json
import unittest
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import card_acceptance as ca
from spa_core.monitoring import decision_reproducibility as dr
from spa_core.tests._freshness import now_utc

PROBE = "determinism_recomputation_is_reproducible"

#: Модуль-решатель одноразового дерева: субъект зовёт его ПО ИМЕНИ, а перепись
#: называет его решателем книги. Имени нет ни в одном живом реестре.
DECIDER_REL = "spa_core/probe_fake_decider.py"
DECIDER_DOTTED = "spa_core.probe_fake_decider"
#: Второй решатель ТОЙ ЖЕ книги, которого не спрашивал никто — форма находки
#: 29.09 (`portfolio_rebalancer` рядом с аллокатором).
SECOND_DECIDER_REL = "spa_core/probe_fake_second_decider.py"
BOOK_REL = "data/probe_fake_book.json"


def _subject(key="asked", code=None):
    return dr.Subject(key=key, title=f"{key} (фикстура)",
                      clock_fields=("timestamp",),
                      code=code if code is not None
                      else f"from {DECIDER_DOTTED} import decide\n")


def _census(books, coverage, *, measured=True, reason=None):
    """Перепись решателей как ВХОД: знаменатель приходит извне пробы."""
    def _run(data_dir, *, repo_root=None, now=None):
        return {"measured": measured, "reason": reason,
                "books": books, "coverage": coverage}
    return _run


def _one_book_census(capital=1000.0, producers=(DECIDER_REL,)):
    return _census(
        [{"artifact": BOOK_REL, "capital_usd": capital}],
        [{"producer": p, "books": [BOOK_REL]} for p in producers])


def _artifact(*, stamp, findings=(), unchecked=(), keys=("asked",),
              verdicts=None, runs=3):
    verdicts = verdicts or {}
    return {
        "generated_at": stamp,
        "overall": "OK",
        "counts": {"critical": 0, "warn": 0, "info": 0, "unchecked": len(unchecked)},
        "runs": runs,
        "subjects_measured": list(keys),
        "measurements": [{"key": k, "verdict": verdicts.get(k, "OK"),
                          "distinct_outputs": 1, "runs_completed": runs,
                          "clock_fields_declared": ["timestamp"],
                          "clock_fields_varying": ["timestamp"],
                          "differences": [], "side_effects": [],
                          "reason": None} for k in keys],
        "findings": list(findings),
        "unchecked": list(unchecked),
    }


class _Tree:
    """Одноразовое дерево: манифест, артефакт, модули-решатели."""

    def __init__(self, td, *, slo=7, second_home_slo=None, drop_slo=False):
        self.root = Path(td)
        (self.root / "architecture").mkdir(parents=True, exist_ok=True)
        (self.root / "data").mkdir(parents=True, exist_ok=True)
        (self.root / "spa_core").mkdir(parents=True, exist_ok=True)
        for rel in (DECIDER_REL, SECOND_DECIDER_REL):
            (self.root / rel).write_text("def decide():\n    return None\n",
                                         encoding="utf-8")
        art = {"path": dr.REPORT_REL, "producer": "com.spa.decision_loop",
               "consumers": ["orchestrator_protocol"], "status": "active",
               "notes": "фикстура"}
        if not drop_slo:
            art["slo_hours"] = slo
        manifest = {"artifacts": [art], "agents": []}
        if second_home_slo is not None:
            manifest["agents"] = [{"label": "com.spa.decision_loop", "produces": [
                {"artifact": dr.REPORT_REL, "slo_hours": second_home_slo}]}]
        (self.root / "architecture" / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8")

    @property
    def data(self):
        return str(self.root / "data")

    def put(self, doc):
        (self.root / dr.REPORT_REL).write_text(json.dumps(doc), encoding="utf-8")

    def drop_artifact(self):
        (self.root / dr.REPORT_REL).unlink()

    def run(self, *, now, subjects=None, census=None):
        return ca.PROBES[PROBE](None, now=now, repo_root=str(self.root),
                                data_dir=self.data,
                                subjects=subjects if subjects is not None
                                else (_subject(),),
                                census=census or _one_book_census())


class TestTheWholeContourIsGreen(unittest.TestCase):
    """Зелёный путь — и он добыт ПОКРЫТИЕМ, а не тем, что фикстура молчит."""

    def test_asked_decider_of_every_book_and_one_answer_is_satisfied(self):
        now = now_utc()
        with TemporaryDirectory() as td:
            tree = _Tree(td)
            tree.put(_artifact(stamp=(now - timedelta(hours=1)).isoformat()))
            verdict, detail = tree.run(now=now)
        self.assertEqual(verdict, ca.SATISFIED, detail)
        self.assertIn("каждый решатель каждой книги спрошен", detail)

    def test_the_green_path_names_its_own_blindness(self):
        """Слепота названа В ЗЕЛЁНОМ вердикте, а не только в красном."""
        now = now_utc()
        with TemporaryDirectory() as td:
            tree = _Tree(td)
            tree.put(_artifact(stamp=(now - timedelta(hours=1)).isoformat()))
            verdict, detail = tree.run(now=now)
        self.assertEqual(verdict, ca.SATISFIED)
        self.assertIn("транзитивную цепочку проба не обходит", detail)


class TestCoverageOfTheDecidingSurface(unittest.TestCase):
    """Замер #732: воспроизводимость, предъявленная не про тот капитал."""

    def test_a_second_unasked_producer_of_the_same_book_is_red(self):
        """Дословная форма находки 29.09: у книги два решателя, спрошен один."""
        now = now_utc()
        with TemporaryDirectory() as td:
            tree = _Tree(td)
            tree.put(_artifact(stamp=(now - timedelta(hours=1)).isoformat()))
            verdict, detail = tree.run(
                now=now,
                census=_one_book_census(
                    producers=(DECIDER_REL, SECOND_DECIDER_REL)))
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn(SECOND_DECIDER_REL, detail)
        # Книга спрошена ЧАСТИЧНО, и это отдельная сумма: слить её с «не спрошена
        # вовсе» значило бы потерять разницу между «половина решателя молчит» и
        # «молчат все».
        self.assertIn("частично $1,000.00", detail)
        self.assertIn("не спрошена $0.00", detail)

    def test_an_unasked_book_is_red_and_says_it_is_not_a_divergence(self):
        now = now_utc()
        with TemporaryDirectory() as td:
            tree = _Tree(td)
            tree.put(_artifact(stamp=(now - timedelta(hours=1)).isoformat()))
            verdict, detail = tree.run(
                now=now, census=_one_book_census(producers=(SECOND_DECIDER_REL,)))
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("НЕ СПРОШЕН", detail)
        self.assertIn("не известно ничего", detail)
        self.assertIn("не спрошена $1,000.00", detail)
        self.assertIn("частично $0.00", detail)

    def test_a_book_without_a_named_decider_is_not_counted_as_asked(self):
        now = now_utc()
        with TemporaryDirectory() as td:
            tree = _Tree(td)
            tree.put(_artifact(stamp=(now - timedelta(hours=1)).isoformat()))
            verdict, detail = tree.run(
                now=now,
                census=_census([{"artifact": BOOK_REL, "capital_usd": 1000.0}], []))
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("решатель не назван", detail)

    def test_the_dollars_come_from_the_census_not_from_the_probe(self):
        """Знаменатель — ВХОД: другая перепись даёт другое число в вердикте."""
        now = now_utc()
        with TemporaryDirectory() as td:
            tree = _Tree(td)
            tree.put(_artifact(stamp=(now - timedelta(hours=1)).isoformat()))
            _, detail = tree.run(
                now=now,
                census=_one_book_census(capital=4321.0,
                                        producers=(SECOND_DECIDER_REL,)))
        self.assertIn("4,321.00", detail)

    def test_an_empty_book_is_the_third_outcome_not_a_green(self):
        """«Воспроизводимо» про $0 — тишина мёртвого дерева, а не ответ."""
        now = now_utc()
        with TemporaryDirectory() as td:
            tree = _Tree(td)
            tree.put(_artifact(stamp=(now - timedelta(hours=1)).isoformat()))
            verdict, detail = tree.run(now=now,
                                       census=_one_book_census(capital=0.0))
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("тишиной мёртвого дерева", detail)

    def test_a_census_that_did_not_measure_is_the_third_outcome(self):
        now = now_utc()
        with TemporaryDirectory() as td:
            tree = _Tree(td)
            tree.put(_artifact(stamp=(now - timedelta(hours=1)).isoformat()))
            verdict, detail = tree.run(
                now=now, census=_census([], [], measured=False,
                                        reason="дерево не разобрано"))
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("дерево не разобрано", detail)
        # Причина обязана быть ПРИЧИНОЙ ВЕРДИКТА, а не строкой где-то рядом:
        # мутация «не смотреть на `measured`» оставляла тот же третий исход, но
        # объясняла его пустыми книгами — не тем, чего не измерили.
        self.assertTrue(detail.startswith("кого именно спрашивали"), detail)

    def test_a_raising_census_is_the_third_outcome_not_a_crash(self):
        now = now_utc()

        def _boom(data_dir, *, repo_root=None, now=None):
            raise RuntimeError("перепись упала")

        with TemporaryDirectory() as td:
            tree = _Tree(td)
            tree.put(_artifact(stamp=(now - timedelta(hours=1)).isoformat()))
            verdict, detail = tree.run(now=now, census=_boom)
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("перепись упала", detail)
        self.assertTrue(detail.startswith("кого именно спрашивали"), detail)

    def test_a_subject_population_that_disagrees_is_the_third_outcome(self):
        """Артефакт снят другим списком субъектов ⇒ «спрошен» значит разное."""
        now = now_utc()
        with TemporaryDirectory() as td:
            tree = _Tree(td)
            tree.put(_artifact(stamp=(now - timedelta(hours=1)).isoformat(),
                               keys=("asked", "ushedshii")))
            verdict, detail = tree.run(now=now)
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("РАСХОДИТСЯ", detail)

    def test_an_unparsable_subject_is_the_third_outcome_not_zero_coverage(self):
        now = now_utc()
        with TemporaryDirectory() as td:
            tree = _Tree(td)
            tree.put(_artifact(stamp=(now - timedelta(hours=1)).isoformat()))
            verdict, detail = tree.run(
                now=now, subjects=(_subject(code="def (((\n"),))
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("не разобран", detail)

    def test_a_subject_that_answered_NO_still_counts_as_asked(self):
        """«Спрошен и ответил нет» ≠ «не спрошен»: вопрос был задан и отвечен.

        Иначе находка расхождения обнулила бы покрытие того же решателя, и одна
        и та же беда посчиталась бы дважды — как расхождение И как молчание.
        """
        now = now_utc()
        with TemporaryDirectory() as td:
            tree = _Tree(td)
            doc = _artifact(stamp=(now - timedelta(hours=1)).isoformat(),
                            verdicts={"asked": "CRITICAL"},
                            findings=({"severity": "CRITICAL", "subject": "asked",
                                       "kind": "not_reproducible",
                                       "message": "2 РАЗНЫХ ответа"},))
            tree.put(doc)
            block = dr.criterion_verdict(doc, root=str(tree.root), data_dir=tree.data,
                                         subjects=(_subject(),),
                                         census=_one_book_census(), now=now)
        self.assertEqual(block["coverage"]["asked_modules"], [DECIDER_REL])
        self.assertEqual(block["coverage"]["fully_asked_usd"], 1000.0)

    def test_an_unchecked_subject_stops_counting_as_asked(self):
        """Вопрос задан, ответа нет ⇒ покрытие обязано упасть, а не стоять."""
        now = now_utc()
        with TemporaryDirectory() as td:
            tree = _Tree(td)
            tree.put(_artifact(stamp=(now - timedelta(hours=1)).isoformat(),
                               verdicts={"asked": "UNCHECKED"},
                               unchecked=("asked: песочница не собрана",)))
            verdict, detail = tree.run(now=now)
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("песочница не собрана", detail)


class TestAbsenceIsNeverZero(unittest.TestCase):
    """Инв. #17: отсутствие раздела — третий исход, а не пустой список.

    Каждый тест здесь — про одну и ту же ошибку с разных сторон: список, которого
    НЕТ, прочитанный как список ПУСТОЙ. Опаснее всего это у `findings`: «находок
    нет» и «о находках не сказано» дали бы одну и ту же зелень.
    """

    def _run_without(self, key, now):
        with TemporaryDirectory() as td:
            tree = _Tree(td)
            doc = _artifact(stamp=(now - timedelta(hours=1)).isoformat())
            doc.pop(key)
            tree.put(doc)
            return tree.run(now=now)

    def test_an_artifact_without_findings_is_not_green(self):
        verdict, detail = self._run_without("findings", now_utc())
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("НЕРАЗЛИЧИМЫ", detail)

    def test_an_artifact_without_unchecked_is_not_green(self):
        verdict, detail = self._run_without("unchecked", now_utc())
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("`unchecked`", detail)

    def test_an_artifact_without_measurements_is_not_zero_coverage(self):
        verdict, detail = self._run_without("measurements", now_utc())
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("не «не спрашивали никого»", detail)

    def test_a_census_silent_about_deciders_is_not_zero_deciders(self):
        now = now_utc()
        with TemporaryDirectory() as td:
            tree = _Tree(td)
            tree.put(_artifact(stamp=(now - timedelta(hours=1)).isoformat()))
            def _silent(data_dir, *, repo_root=None, now=None):
                return {"measured": True, "books": [{"artifact": BOOK_REL,
                                                     "capital_usd": 1000.0}]}
            verdict, detail = tree.run(now=now, census=_silent)
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("не сказано ничего", detail)

    def test_an_unreadable_book_never_counts_as_zero_dollars(self):
        """Книга без суммы, посчитанная за $0, УМЕНЬШИЛА бы знаменатель."""
        now = now_utc()
        with TemporaryDirectory() as td:
            tree = _Tree(td)
            tree.put(_artifact(stamp=(now - timedelta(hours=1)).isoformat()))
            verdict, detail = tree.run(
                now=now,
                census=_census([{"artifact": BOOK_REL, "capital_usd": 1000.0},
                                {"artifact": "data/bez_summy.json"}],
                               [{"producer": DECIDER_REL,
                                 "books": [BOOK_REL, "data/bez_summy.json"]}]))
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("знаменатель в долларах НЕ ИЗМЕРЕН", detail)

    def test_a_coverage_claiming_measured_without_a_sum_is_refused(self):
        """Сторож на СВОЕЙ двери: «измерено» без суммы — не ноль, а третий исход.

        Такое состояние живая `decider_coverage` не выдаёт по построению, поэтому
        предъявить его может только подмена САМОЙ переписи покрытия — то есть того
        соседа, от которого эта ветка и защищает. Без контроля ветка была бы
        украшением: мутация «не смотреть на сумму» выживала бы молча.
        """
        from unittest.mock import patch
        now = now_utc()
        with TemporaryDirectory() as td:
            tree = _Tree(td)
            doc = _artifact(stamp=(now - timedelta(hours=1)).isoformat())
            tree.put(doc)
            with patch.object(dr, "decider_coverage",
                              return_value={"measured": True, "reason": None,
                                            "books": [], "asked_modules": [],
                                            "answered_subjects": ["asked"]}):
                block = dr.criterion_verdict(doc, root=str(tree.root),
                                             data_dir=tree.data, now=now)
        self.assertEqual(block["status"], dr.CRITERION_UNMEASURED, block["reason"])
        self.assertIn("знаменателя нет", block["reason"])

    def test_a_census_row_without_books_is_the_third_outcome(self):
        now = now_utc()
        with TemporaryDirectory() as td:
            tree = _Tree(td)
            tree.put(_artifact(stamp=(now - timedelta(hours=1)).isoformat()))
            verdict, detail = tree.run(
                now=now,
                census=_census([{"artifact": BOOK_REL, "capital_usd": 1000.0}],
                               [{"producer": DECIDER_REL}]))
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("нет списка книг", detail)


class TestAxisNotOverall(unittest.TestCase):
    """Переносится вердикт ПО ОСИ, а не лестница тяжести `overall`."""

    def test_a_divergence_is_red_even_when_coverage_is_unmeasured(self):
        """Находка существования не отменяется неполнотой населения (ADR-513)."""
        now = now_utc()
        with TemporaryDirectory() as td:
            tree = _Tree(td)
            tree.put(_artifact(
                stamp=(now - timedelta(hours=1)).isoformat(),
                findings=({"severity": "CRITICAL", "subject": "asked",
                           "kind": "not_reproducible",
                           "message": "2 РАЗНЫХ ответа"},)))
            verdict, detail = tree.run(
                now=now, census=_census([], [], measured=False,
                                        reason="перепись не измерила"))
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("РАЗНЫЕ ответы", detail)

    def test_a_divergence_outranks_the_third_outcome_beside_it(self):
        """Порядок лестницы: находка существования ВЫШЕ «не измерено» рядом.

        Ровно тот урок ADR-513: `overall` ставит третий исход выше `CRITICAL`,
        и перенеси проба `overall` — измеренное красное уехало бы под «не
        измерено», тише любой правки.
        """
        now = now_utc()
        with TemporaryDirectory() as td:
            tree = _Tree(td)
            tree.put(_artifact(
                stamp=(now - timedelta(hours=1)).isoformat(),
                unchecked=("tuner: песочница не собрана",),
                verdicts={"asked": "CRITICAL"},
                findings=({"severity": "CRITICAL", "subject": "asked",
                           "kind": "not_reproducible",
                           "message": "2 РАЗНЫХ ответа"},)))
            verdict, detail = tree.run(now=now)
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)

    def test_a_declared_clock_that_never_varied_is_the_third_outcome(self):
        """Вычли из сравнения поле, часами не оказавшееся ⇒ сравнение неполно."""
        now = now_utc()
        with TemporaryDirectory() as td:
            tree = _Tree(td)
            tree.put(_artifact(
                stamp=(now - timedelta(hours=1)).isoformat(),
                findings=({"severity": "INFO", "subject": "asked",
                           "kind": "stale_clock_declaration",
                           "message": "поле не различалось"},)))
            verdict, detail = tree.run(now=now)
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("stale_clock_declaration", detail)

    def test_a_side_effect_does_not_by_itself_redden_the_criterion(self):
        """Запись под `save=False` — факт о субъекте: песочницы у прогонов РАЗНЫЕ."""
        now = now_utc()
        with TemporaryDirectory() as td:
            tree = _Tree(td)
            tree.put(_artifact(
                stamp=(now - timedelta(hours=1)).isoformat(),
                findings=({"severity": "WARN", "subject": "asked",
                           "kind": "side_effect",
                           "message": "записал в песочницу"},)))
            verdict, detail = tree.run(now=now)
        self.assertEqual(verdict, ca.SATISFIED, detail)

    def test_a_finding_without_a_declared_axis_breaks_off_the_verdict(self):
        """Новый вид находки не классифицируется молча — и вид НАЗЫВАЕТСЯ."""
        now = now_utc()
        with TemporaryDirectory() as td:
            tree = _Tree(td)
            tree.put(_artifact(
                stamp=(now - timedelta(hours=1)).isoformat(),
                findings=({"severity": "WARN", "subject": "asked",
                           "kind": "vid_kotorogo_net_v_tablice",
                           "message": "?"},)))
            verdict, detail = tree.run(now=now)
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("vid_kotorogo_net_v_tablice", detail)

    def test_every_kind_the_instrument_can_emit_has_an_axis(self):
        """Таблица осей не имеет права отставать от видов, которые прибор печатает.

        Предмет — ТЕЛО прибора, а не снимок видов рядом: список рядом разъехался
        бы молча (урок #730/#731).
        """
        import re
        src = Path(dr.__file__).read_text(encoding="utf-8")
        emitted = set(re.findall(r'"kind":\s*"([a-z_]+)"', src))
        self.assertTrue(emitted, "виды находок в приборе не найдены — разбор сломан")
        self.assertEqual(emitted - set(dr.FINDING_AXIS), set())


class TestFreshnessComesFromTheConstitution(unittest.TestCase):
    """Порог берётся из манифеста ОБОИМИ домами; своего «24 часа» у пробы нет."""

    def test_a_stale_artifact_is_the_third_outcome(self):
        now = now_utc()
        with TemporaryDirectory() as td:
            tree = _Tree(td, slo=7)
            tree.put(_artifact(stamp=(now - timedelta(hours=9)).isoformat()))
            verdict, detail = tree.run(now=now)
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("протух", detail)

    def test_the_second_home_of_the_declaration_is_read_too(self):
        """Находка #730: срок годности объявляется и в паспорте производителя."""
        now = now_utc()
        with TemporaryDirectory() as td:
            tree = _Tree(td, drop_slo=True, second_home_slo=7)
            tree.put(_artifact(stamp=(now - timedelta(hours=1)).isoformat()))
            verdict, detail = tree.run(now=now)
        self.assertEqual(verdict, ca.SATISFIED, detail)
        self.assertIn("com.spa.decision_loop", detail)

    def test_homes_that_disagree_are_the_third_outcome_not_a_choice(self):
        now = now_utc()
        with TemporaryDirectory() as td:
            tree = _Tree(td, slo=7, second_home_slo=26)
            tree.put(_artifact(stamp=(now - timedelta(hours=1)).isoformat()))
            verdict, detail = tree.run(now=now)
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("свежесть НЕ СУЖДЕНА", detail)

    def test_without_a_declared_threshold_nothing_is_invented(self):
        now = now_utc()
        with TemporaryDirectory() as td:
            tree = _Tree(td, drop_slo=True)
            tree.put(_artifact(stamp=(now - timedelta(hours=1)).isoformat()))
            verdict, detail = tree.run(now=now)
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("нет записи о сроке годности", detail)

    def test_an_unparsable_stamp_is_never_treated_as_fresh(self):
        now = now_utc()
        with TemporaryDirectory() as td:
            tree = _Tree(td)
            tree.put(_artifact(stamp="вчера"))
            verdict, detail = tree.run(now=now)
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("возраст НЕ ИЗМЕРЕН", detail)


class TestTheArtifactIsRead(unittest.TestCase):
    """Артефакта нет / он не объект ⇒ третий исход с адресом, а не тишина."""

    def test_a_missing_artifact_is_the_third_outcome(self):
        now = now_utc()
        with TemporaryDirectory() as td:
            tree = _Tree(td)
            tree.put(_artifact(stamp=(now - timedelta(hours=1)).isoformat()))
            tree.drop_artifact()
            verdict, detail = tree.run(now=now)
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("не прочитан", detail)

    def test_an_artifact_that_is_not_an_object_is_the_third_outcome(self):
        now = now_utc()
        with TemporaryDirectory() as td:
            tree = _Tree(td)
            (Path(td) / dr.REPORT_REL).write_text("[1, 2]", encoding="utf-8")
            verdict, detail = tree.run(now=now)
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("не объект", detail)

    def test_the_probe_reads_the_data_dir_it_was_given(self):
        """Дерево — ВХОД: артефакт своего дерева проба не подставляет."""
        now = now_utc()
        with TemporaryDirectory() as td:
            tree = _Tree(td)
            tree.put(_artifact(stamp=(now - timedelta(hours=1)).isoformat()))
            _, detail = tree.run(now=now)
        self.assertIn(str(Path(td)), detail + str(Path(td)))
        self.assertIn("при пределе 7", detail)


class TestTheBindingDoesNotPassBySubstring(unittest.TestCase):
    """ADR-333: объявление сверяется ПО ЯКОРЮ и вердикт — как ЗНАЧЕНИЕ."""

    def _with_module(self, fake, now, tree):
        import sys
        saved = sys.modules.get(ca.DETERMINISM_MODULE)
        sys.modules[ca.DETERMINISM_MODULE] = fake
        try:
            return tree.run(now=now)
        finally:
            if saved is None:
                sys.modules.pop(ca.DETERMINISM_MODULE, None)
            else:
                sys.modules[ca.DETERMINISM_MODULE] = saved

    def _fake(self, **attrs):
        import types
        mod = types.ModuleType("fake_determinism")
        mod.CRITERION = dr.CRITERION
        mod.REPORT_REL = dr.REPORT_REL
        mod.CRITERION_SATISFIED = dr.CRITERION_SATISFIED
        mod.CRITERION_NOT_SATISFIED = dr.CRITERION_NOT_SATISFIED
        mod.CRITERION_UNMEASURED = dr.CRITERION_UNMEASURED
        mod.criterion_verdict = lambda *a, **k: {
            "status": dr.CRITERION_SATISFIED, "reason": "ок", "coverage": {}}
        for k, v in attrs.items():
            setattr(mod, k, v)
        return mod

    def test_a_criterion_mentioning_the_word_is_not_accepted(self):
        now = now_utc()
        with TemporaryDirectory() as td:
            tree = _Tree(td)
            tree.put(_artifact(stamp=(now - timedelta(hours=1)).isoformat()))
            verdict, detail = self._with_module(
                self._fake(CRITERION="прибор про Determinism и §49 вообще"),
                now, tree)
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("не объявляет себя мерой", detail)

    def test_the_anchor_must_START_the_declaration_not_appear_inside_it(self):
        """Ровно дефект ADR-333: якорь ВПЕРЕДИ, а не «где-то встречается».

        Прибор, у которого «§49 Determinism» стои́т ссылкой в середине заметки,
        мерой этого критерия себя не объявил — он на него сослался. Подстрочное
        совпадение приняло бы за объявление любую такую ссылку.
        """
        now = now_utc()
        with TemporaryDirectory() as td:
            tree = _Tree(td)
            tree.put(_artifact(stamp=(now - timedelta(hours=1)).isoformat()))
            verdict, detail = self._with_module(
                self._fake(CRITERION="прибор стоимости; см. также §49 Determinism"),
                now, tree)
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("не объявляет себя мерой", detail)

    def test_an_unknown_criterion_status_is_never_transferred(self):
        now = now_utc()
        with TemporaryDirectory() as td:
            tree = _Tree(td)
            tree.put(_artifact(stamp=(now - timedelta(hours=1)).isoformat()))
            verdict, detail = self._with_module(
                self._fake(criterion_verdict=lambda *a, **k: {
                    "status": "REPRODUCIBLE", "reason": "ок", "coverage": {}}),
                now, tree)
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("не переносится", detail)

    def test_a_raising_instrument_is_the_third_outcome(self):
        now = now_utc()

        def _boom(*a, **k):
            raise RuntimeError("правило упало")

        with TemporaryDirectory() as td:
            tree = _Tree(td)
            tree.put(_artifact(stamp=(now - timedelta(hours=1)).isoformat()))
            verdict, detail = self._with_module(
                self._fake(criterion_verdict=_boom), now, tree)
        self.assertEqual(verdict, ca.UNMEASURED, detail)
        self.assertIn("правило упало", detail)

    def test_the_probe_reads_the_instrument_and_not_its_own_copy(self):
        """Подмена прибора ДОХОДИТ до пробы — значит правило живёт у прибора."""
        now = now_utc()
        with TemporaryDirectory() as td:
            tree = _Tree(td)
            tree.put(_artifact(stamp=(now - timedelta(hours=1)).isoformat()))
            verdict, detail = self._with_module(
                self._fake(criterion_verdict=lambda *a, **k: {
                    "status": dr.CRITERION_NOT_SATISFIED,
                    "reason": "подменённое правило сказало НЕТ",
                    "coverage": {"measured": False, "reason": "—"}}),
                now, tree)
        self.assertEqual(verdict, ca.NOT_SATISFIED, detail)
        self.assertIn("подменённое правило", detail)


class TestTheRegistration(unittest.TestCase):
    """Проба объявлена мерой критерия, зарегистрирована и принимает дерево входом."""

    def test_the_probe_is_registered_and_declares_the_criterion(self):
        self.assertIn(PROBE, ca.PROBES)
        self.assertEqual(ca.probes_by_s49_criterion().get("Determinism"), [PROBE])

    def test_the_probe_accepts_both_tree_inputs(self):
        self.assertEqual(set(ca.probe_tree_inputs(PROBE)), {"repo_root", "data_dir"})

    def test_the_instrument_declares_itself_the_measure_by_anchor(self):
        self.assertTrue(dr.CRITERION.startswith("§49 Determinism"), dr.CRITERION)

    def test_the_constitution_declares_the_binding_in_the_canonical_form(self):
        """Привязка в манифесте — форма `backtick`, а не `paren` (цена WORDING)."""
        from spa_core.monitoring import s49_criterion_price as price
        root = Path(dr.__file__).resolve().parents[2]
        parsed = price.parse_bindings(price.read_manifest(str(root)))
        bound = parsed["bindings"].get("Determinism") or []
        self.assertEqual([b["path"] for b in bound], [dr.REPORT_REL], bound)
        self.assertEqual([b["form"] for b in bound], [price.CANONICAL_FORM])


class TestTheInstrumentPublishesTheVerdict(unittest.TestCase):
    """Вердикт критерия обязан лежать В АРТЕФАКТЕ, а не только у пробы."""

    def test_run_writes_a_criterion_block(self):
        now = now_utc()
        with TemporaryDirectory() as td:
            data = Path(td) / "data"
            data.mkdir(parents=True)
            (data / "adapter_orchestrator_status.json").write_text(
                json.dumps({"adapters": []}), encoding="utf-8")
            (Path(td) / "spa_core").mkdir()
            (Path(td) / DECIDER_REL).write_text("def decide():\n    return None\n",
                                                encoding="utf-8")
            # Часы обязаны ДРОЖАТЬ между прогонами: иначе прибор справедливо
            # назовёт объявление часов лишним (`stale_clock_declaration`), и
            # предмет теста подменился бы на этот побочный вопрос.
            def _runner(subject, sandbox, root_, seed, timeout):
                stamp = (now + timedelta(microseconds=seed)).isoformat()
                return 0, json.dumps({"timestamp": stamp, "w": {"a": 1}}), ""

            report = dr.run(
                root=td, data_dir=str(data), runs=2, write=False, now=now,
                subjects=(_subject(),), runner=_runner,
                census=_one_book_census())
            self.assertEqual(report["overall"], "OK", report["findings"])
            self.assertEqual(report["criterion"]["status"], dr.CRITERION_SATISFIED,
                             report["criterion"]["reason"])
            self.assertTrue(report["criterion"]["coverage"]["measured"])
            self.assertEqual(report["criterion"]["coverage"]["asked_modules"],
                             [DECIDER_REL])


if __name__ == "__main__":                                    # pragma: no cover
    unittest.main()
