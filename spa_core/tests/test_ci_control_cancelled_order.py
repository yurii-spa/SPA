"""ОТМЕНА контрольного прогона — отдельная причина отсутствия вердикта (ADR-1082).

Предмет. Причину отсутствия отчёта читатель вердикта зарабатывает с 18.11 (ADR-1058):
«ещё идёт» он больше не называет смертью. Но внутри «завершён» до 24.11 жило ОДНО слово
на ДВА состояния — «прогон умер раньше сводки», — и второе из них измеримо.

**Замер 2026-11-24 (цикл #1228), живой API.** Цикл #1227, исполняя свой же порядок
«заказывать контрольный прогон КАЖДОЙ доставкой», заказал два прогона с промежутком
2.5 мин: `45292219029` (вершина кода, создан 23:50:24Z) и `45292542397` (вершина
пост-записи, 23:52:50Z). Второй не шёл НИ ОДНОЙ секунды. Группа `ci-control` объявлена
`cancel-in-progress: false` — новый прогон идущий не снимает, а становится ОЖИДАЮЩИМ, и
ожидающего в группе GitHub держит РОВНО ОДНОГО. В 23:58:35Z в ту же группу встал
РАСПИСАННЫЙ прогон `45293308721` (`cron: 23 */6 * * *`), и ожидающий `45292542397` был
отменён в 23:58:36Z, прожив 346 с. Цикл записал его номер в заказ как якорь дельты — то
есть отдал следующему циклу измерение, которого не было.

**Население класса ИЗМЕРЕНО** по ВСЕМ 400 прогонам воркфлоу: отменённых **24** (6.0 %),
и у **16** из них другой прогон создан в пределах 60 с от отмены. Форма наблюдается
КАСКАДОМ (#183 снят созданием #184, #184 — созданием #185, #185 — созданием #186): каждый
новый заказ убивает предыдущий ожидающий. У остальных ВОСЬМИ совпадения в окне нет, и
причина их отмены остаётся НЕ ИЗМЕРЕННОЙ — не «ручной».

**Цена дефекта не косметическая.** «Умер раньше сводки» и «заказ вытеснен» требуют
ПРОТИВОПОЛОЖНЫХ действий: умерший прогон повторять бессмысленно (он дойдёт до того же
предела), а вытесненный не шёл вовсе и обязан быть повторён — ОДИН раз, на ПОСЛЕДНЕЙ
вершине доставки. Второе: строка возраста приписывала завершённому прогону слово «идёт»
(у `45292542397` — «идёт 1.1ч» о прогоне, который жил 346 с и был мёртв час). Число было
верное, слово — нет, а строку читают глазами.

Каждый тест ниже — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ одного порванного звена, и звено названо в его
docstring (`.claude/rules/deployment.md`, § «Проверка сторожа сторожей»).

Ни сети, ни живой машины файл не спрашивает: обе двери (`fetch`, `grab`) и часы — ВХОДЫ.

# FROZEN-DATE-OK: injected-clock — якорь `NOW` уезжает входом `now=NOW` в
# `ccv.run_liveness(...)` / `ccv._absence_cause(...)`, а все отметки сцен считаются от
# него же (`NOW - timedelta`); обе стороны каждого сравнения закреплены одним якорем,
# стенных часов в файле нет ни одного.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone

_REPO = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

PRODUCER_REL = "scripts/ci_control_verdict.py"

#: Момент замера — ВХОД сцены. Ни одна другая дата в файле не литерал.
NOW = datetime(2026, 11, 24, 1, 0, tzinfo=timezone.utc)

#: Номера — из живого замера 24.11, чтобы сцена и находка говорили об одном.
ORDER = "45292542397"        # вытесненный заказ цикла #1227
DISPLACER = "45293308721"    # расписанный прогон, вставший в ту же группу


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, _REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ccv = _load("_t1228_ccv", PRODUCER_REL)


def _row(rid, *, status="completed", conclusion="cancelled", born_h=1.2, lived_s=346.0,
         event="workflow_dispatch"):
    """Строка прогона: рождение и конец — ОБА от якоря, и срок жизни их разность."""
    born = NOW - timedelta(hours=born_h)
    return {"id": rid, "status": status, "conclusion": conclusion, "event": event,
            "head_sha": "86f91d0735840812d8df392bbbe23545cb4e321e", "head_branch": "main",
            "created_at": born.isoformat(),
            "updated_at": (born + timedelta(seconds=lived_s)).isoformat(),
            "html_url": f"https://github.com/yurii-spa/SPA/actions/runs/{rid}"}


class _Net:
    """Сеть ВХОДОМ: обе двери отвечают сценой, а не живым GitHub.

    Иначе каждый тест ниже отвечал бы на вопрос «что сегодня у GitHub», а не «цела ли
    проводка» (`.claude/rules/deployment.md`, § про инъекцию).
    """

    def __init__(self, runs, *, listing_raises=None, listing=None):
        self.runs = runs
        self.listing_raises = listing_raises
        self.listing = listing
        self.asked = []

    def fetch(self, path):
        self.asked.append(path)
        hit = path.rsplit("/actions/runs/", 1)
        if len(hit) == 2 and hit[1].isdigit():
            for row in self.runs:
                if str(row.get("id")) == hit[1]:
                    return dict(row)
            return {}
        if self.listing_raises is not None:
            raise self.listing_raises
        if self.listing is not None:
            return self.listing
        return {"workflow_runs": [dict(r) for r in self.runs]}


def _cause(net, rid=ORDER):
    return ccv._absence_cause(rid, fetch=net.fetch, now=NOW)


# ───── 1. «отменён» и «умер на своём пределе» — РАЗНЫЕ причины ────────────────

class CancelledIsNotTheSameDeathAsAnyOther(unittest.TestCase):
    """Порванное звено: ОДНО слово «умер раньше сводки» стояло на ДВА состояния."""

    def test_the_two_causes_differ_by_the_conclusion_alone(self):
        """ДИФФЕРЕНЦИАЛЬНЫЙ контроль: сцены отличаются РОВНО одним полем.

        Редакция до 24.11 даёт на обе одну строку — и тест краснеет. Случайно такой
        контроль не проходится: совпасть причины могут только при назначении.
        """
        cancelled = _cause(_Net([_row(ORDER, conclusion="cancelled"),
                                 _row(DISPLACER, event="schedule", born_h=1.2,
                                      lived_s=346.0)]))
        failed = _cause(_Net([_row(ORDER, conclusion="failure")]))
        self.assertNotEqual(cancelled, failed,
                            "причина НЕ зависит от того, отменён прогон или умер — "
                            "значит она назначена, а не измерена")
        self.assertIn("ОТМЕНЁН", cancelled)
        self.assertIn("умер раньше сводки", failed)
        self.assertNotIn("умер раньше сводки", cancelled,
                         "отменённый прогон назван умершим: он не шёл вовсе, и "
                         "действие читателя здесь ОБРАТНОЕ")

    def test_a_completed_run_is_never_said_to_be_RUNNING(self):
        """Звено: слово «идёт» приписывалось ЗАВЕРШЁННОМУ прогону.

        У `45292542397` строка несла «идёт 1.1ч» — о прогоне, который прожил 346 с и был
        мёртв час. Слово и число обязаны говорить об одном.
        """
        for conclusion in ("cancelled", "failure"):
            line = _cause(_Net([_row(ORDER, conclusion=conclusion)]))
            self.assertNotIn("идёт", line,
                             f"завершённый прогон (`{conclusion}`) назван идущим")
            self.assertIn("прожил 346 с", line,
                          "срок жизни завершённого прогона не назван либо назван не им")

    def test_the_lifetime_comes_from_the_runs_own_marks_not_from_now(self):
        """Звено: срок жизни считался от ЯКОРЯ наблюдателя, а не от отметок прогона.

        Прогон, родившийся ВДВОЕ раньше, прожил РОВНО столько же — и строка обязана
        сказать то же число. Считай её от `now`, и число поехало бы за календарём.
        """
        near = _cause(_Net([_row(ORDER, born_h=1.2)]))
        far = _cause(_Net([_row(ORDER, born_h=9.0)]))
        self.assertIn("прожил 346 с", near)
        self.assertIn("прожил 346 с", far)


# ───── 2. три исхода вопроса «ЧЕМ отменён» различимы (инв. #17) ───────────────

class WhatCancelledItHasThreeOutcomes(unittest.TestCase):
    """Порванное звено: «не спросили» выдавалось бы за «соседей не было»."""

    def _state(self, net, rid=ORDER):
        row = next(r for r in net.runs if str(r["id"]) == rid)
        return ccv.cancellation_cause(rid, fetch=net.fetch,
                                      cancelled_at=row["updated_at"])

    def test_displaced_names_the_run_that_displaced_it(self):
        """Вытеснение названо ИМЕНЕМ и СОБЫТИЕМ, а не словом «вероятно»."""
        order = _row(ORDER)
        net = _Net([order, _row(DISPLACER, event="schedule",
                                born_h=1.2 - 346.0 / 3600.0, lived_s=3600.0)])
        got = self._state(net)
        self.assertEqual(got["state"], ccv.CXL_DISPLACED)
        self.assertEqual([r["id"] for r in got["by"]], [DISPLACER])
        self.assertEqual(got["by"][0]["event"], "schedule")
        line = _cause(net)
        self.assertIn("ЗАКАЗ ВЫТЕСНЕН", line)
        self.assertIn(DISPLACER, line)
        self.assertIn("schedule", line)

    def test_no_neighbour_is_UNMEASURED_not_a_verdict_about_a_hand(self):
        """Звено: отсутствие соседа читалось бы как «отменили рукой».

        Рука, предел джобы и вытеснение ЗА окном здесь неразличимы, и выдумывать
        любое из трёх запрещено (инв. #17).
        """
        net = _Net([_row(ORDER), _row("1", born_h=20.0)])
        got = self._state(net)
        self.assertEqual(got["state"], ccv.CXL_NO_NEIGHBOUR)
        self.assertEqual(got["by"], [])
        line = _cause(net)
        self.assertIn("НЕ ИЗМЕРЕНО", line)
        self.assertNotIn("ЗАКАЗ ВЫТЕСНЕН", line)
        self.assertNotIn("рукой", line)

    def test_an_unread_listing_is_its_own_third_outcome(self):
        """Звено: немочь двери подставлялась бы как «соседей не было»."""
        net = _Net([_row(ORDER)],
                   listing_raises=urllib.error.URLError("сеть не отвечает"))
        got = self._state(net)
        self.assertEqual(got["state"], ccv.CXL_UNMEASURED)
        self.assertIn("не прочитан", got["why"])
        line = _cause(net)
        self.assertIn("НЕ ИЗМЕРЕНО", line)
        self.assertNotIn("не создавалось", line,
                         "«не спросили» названо «соседей не было»")

    def test_a_listing_without_rows_is_not_an_empty_neighbourhood(self):
        """Звено: документ БЕЗ строк читался бы как измеренный пустой список."""
        net = _Net([_row(ORDER)], listing={"message": "Not Found"})
        got = self._state(net)
        self.assertEqual(got["state"], ccv.CXL_UNMEASURED)
        self.assertIn("строк не несёт", got["why"])

    def test_an_unparsed_cancel_moment_is_measured_as_such(self):
        """Звено: нечитаемый момент отмены дал бы окно вокруг пустоты."""
        got = ccv.cancellation_cause(ORDER, fetch=_Net([_row(ORDER)]).fetch,
                                     cancelled_at=None)
        self.assertEqual(got["state"], ccv.CXL_UNMEASURED)
        self.assertIn("момент отмены", got["why"])

    def test_all_three_states_are_distinct_words(self):
        """Звено: два исхода носили бы одно имя и слились бы у читателя."""
        self.assertEqual(len({ccv.CXL_DISPLACED, ccv.CXL_NO_NEIGHBOUR,
                              ccv.CXL_UNMEASURED}), 3)


# ───── 3. вопрос задаётся о ГРУППЕ, а не о ветке ──────────────────────────────

class TheQuestionIsAskedOfTheGroupNotOfTheBranch(unittest.TestCase):
    """Порванное звено: фильтр по ветке сузил бы вопрос и спрятал вытеснение.

    Группа объявлена строкой `group: ci-control` БЕЗ `github.ref`, поэтому вытеснить
    заказ может прогон любой ветки. Спросить `?branch=main` значило бы ответить на
    другой вопрос и назвать измеримое вытеснение неизмеренным.
    """

    def test_the_listing_is_asked_without_a_branch_filter(self):
        net = _Net([_row(ORDER), _row(DISPLACER, event="schedule",
                                      born_h=1.2 - 346.0 / 3600.0)])
        ccv.cancellation_cause(ORDER, fetch=net.fetch,
                               cancelled_at=net.runs[0]["updated_at"])
        listings = [p for p in net.asked if "/runs?" in p]
        self.assertTrue(listings, "список прогонов не спрошен вовсе")
        for path in listings:
            self.assertNotIn("branch=", path,
                             "вопрос сужен веткой — вытеснение чужой ветки станет "
                             "«не измерено» там, где оно измеримо")

    def test_a_displacer_on_another_branch_still_counts(self):
        other = _row(DISPLACER, event="schedule", born_h=1.2 - 346.0 / 3600.0)
        other["head_branch"] = "autonomy/s1"
        net = _Net([_row(ORDER), other])
        got = ccv.cancellation_cause(ORDER, fetch=net.fetch,
                                     cancelled_at=net.runs[0]["updated_at"])
        self.assertEqual(got["state"], ccv.CXL_DISPLACED)

    def test_the_run_itself_is_never_its_own_displacer(self):
        """Звено: собственная строка прогона попала бы в окно вокруг себя."""
        net = _Net([_row(ORDER, lived_s=0.0)])
        got = ccv.cancellation_cause(ORDER, fetch=net.fetch,
                                     cancelled_at=net.runs[0]["updated_at"])
        self.assertEqual(got["state"], ccv.CXL_NO_NEIGHBOUR)


# ───── 4. окно — ЗАМЕР с причиной, а не круглое число ─────────────────────────

class TheWindowIsAMeasurementNotATaste(unittest.TestCase):
    """Порванное звено: порог без причины подкручивали бы под желаемый ответ."""

    def test_the_window_is_declared_once_and_is_seconds(self):
        self.assertIsInstance(ccv.DISPLACEMENT_WINDOW_S, float)
        self.assertGreater(ccv.DISPLACEMENT_WINDOW_S, 0.0)

    def test_a_neighbour_outside_the_window_is_not_credited(self):
        """Сосед ЗА окном вытеснителем не объявляется — иначе окна не было бы."""
        far = ccv.DISPLACEMENT_WINDOW_S + 30.0
        net = _Net([_row(ORDER),
                    _row(DISPLACER, born_h=1.2 - (346.0 + far) / 3600.0)])
        got = ccv.cancellation_cause(ORDER, fetch=net.fetch,
                                     cancelled_at=net.runs[0]["updated_at"])
        self.assertEqual(got["state"], ccv.CXL_NO_NEIGHBOUR)

    def test_a_neighbour_born_just_BEFORE_the_cancel_counts_too(self):
        """Окно двустороннее: GitHub ставит обе отметки сам, и они дрожат.

        У живого замера вытеснитель создан в 23:58:35Z, а отмена записана 23:58:36Z —
        то есть сосед РОДИЛСЯ РАНЬШЕ отмены. Односторонним окном этот — единственный
        наблюдённый — случай не нашёлся бы вовсе.
        """
        net = _Net([_row(ORDER),
                    _row(DISPLACER, born_h=1.2 - (346.0 - 1.0) / 3600.0)])
        got = ccv.cancellation_cause(ORDER, fetch=net.fetch,
                                     cancelled_at=net.runs[0]["updated_at"])
        self.assertEqual(got["state"], ccv.CXL_DISPLACED)


# ───── 5. причина доезжает до ЧИТАТЕЛЯ, а не живёт в функции ──────────────────

class TheCauseReachesTheReaderOfTheDelta(unittest.TestCase):
    """Порванное звено: дверь написана и не позвана (класс ADR-345).

    Номер отменённого прогона приходит в читатель ИЗВНЕ — заказом предшественника, —
    и именно `--delta` его получает. Отсутствие отчёта обязано нести эту причину.
    """

    def test_the_absence_of_a_report_carries_the_displacement(self):
        order = _row(ORDER)
        net = _Net([order, _row(DISPLACER, event="schedule",
                                born_h=1.2 - 346.0 / 3600.0)])

        class _N(_Net):
            def fetch(self, path):
                if "/artifacts" in path:
                    self.asked.append(path)
                    return {"artifacts": []}
                return super().fetch(path)

        net = _N([order, _row(DISPLACER, event="schedule",
                              born_h=1.2 - 346.0 / 3600.0)])
        with self.assertRaises(ccv.NotMeasured) as box:
            ccv.report_of_run(ORDER, fetch=net.fetch, grab=lambda url: b"", now=NOW)
        said = str(box.exception)
        self.assertIn("ЗАКАЗ ВЫТЕСНЕН", said)
        self.assertIn("вердиктом НЕ является", said,
                      "третий исход потерял оговорку про `conclusion`")


if __name__ == "__main__":
    unittest.main()
