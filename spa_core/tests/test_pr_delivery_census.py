"""Перепись доставки «открытый PR ≠ доставленная работа» — ADR-477.

Авария 2026-09-25: приказ владельца «Portfolio CIO» состоит из 52 разделов, а на
`main` тело якорной карточки обрывалось на середине §5 — §6–52 и аудит
`docs/research/RS-portfolio-cio-audit-2026-08-29.md` 28 дней жили только в ЧЕРНОВОМ
PR #50. Сторож `pr-ci-liveness` по этому PR был ЗЕЛЁН и был прав: прогонов у head'а
три. Он отвечал на свой вопрос, а нужный — «а работа-то ДОЕХАЛА?» — не задавал никто.

Каждый тест ниже — эта авария либо её обратная сторона. Сеть, база и часы приходят
ВХОДАМИ, поэтому ни один тест не трогает ни сеть, ни календарь машины.

FROZEN-DATE-OK: injected-clock — якорь NOW = datetime(2026, 9, 25, …) и производные
от него (BORN_PR50, NOW_FRESH) передаются АРГУМЕНТОМ в M.census(..., now=…) и
M.verdict_for_pull(..., now=…); обе стороны замера закреплены литералами, стенные
часы в вердикт не входят вовсе.
"""
from __future__ import annotations

import importlib.util
import subprocess
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: Якорь: день, когда авария была измерена. Ниже он уходит ВХОДОМ, а не сравнивается
#: со стенными часами — поэтому тест не краснеет от того, что сдвинулся календарь.
NOW = datetime(2026, 9, 25, 23, 30, tzinfo=timezone.utc)
#: Дата создания PR #50 — дословно из ответа API (`created_at`).
BORN_PR50 = "2026-08-29T03:00:48Z"
LOST_PATH = "docs/research/RS-portfolio-cio-audit-2026-08-29.md"


def _load():
    spec = importlib.util.spec_from_file_location(
        "pr_delivery_census", REPO / "scripts" / "pr_delivery_census.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = _load()


def _pull(number, created_at, title="проба", base="main", draft=True):
    return {"number": number, "created_at": created_at, "title": title,
            "draft": draft, "base": {"ref": base}}


def _fetch(pulls, files_by_pr, boom_on=None):
    """Поддельный API. `boom_on` — подстрока url, на которой он ОТКАЗЫВАЕТ."""
    def fetch(url):
        if boom_on and boom_on in url:
            raise OSError("сеть недоступна")
        if "/pulls?" in url:
            return pulls
        number = int(url.split("/pulls/")[1].split("/")[0])
        return files_by_pr.get(number, [])
    return fetch


def _added(*paths):
    return [{"filename": p, "status": "added"} for p in paths]


def _door(present=(), boom=False):
    """Дверь к базе. `boom=True` — дверь ОТКАЗЫВАЕТ (а не отвечает «нет»)."""
    def exists_on_base(base_ref, path):
        if boom:
            raise M.BaseUnreadable("ветка не найдена локально")
        return path in present
    return exists_on_base


class TheAccidentIsCaught(unittest.TestCase):
    """Положительный контроль: воспроизведённая авария обязана красить прибор."""

    def test_pr50_twenty_eight_days_old_with_a_path_absent_on_main_is_the_defect(self):
        rep = M.census("o/r",
                       _fetch([_pull(50, BORN_PR50, "Аудит Portfolio CIO")],
                              {50: _added(LOST_PATH)}),
                       _door(present=()), NOW)
        self.assertEqual(rep["state"], M.NOT_ARRIVED)
        self.assertEqual(M.exit_code(rep), M.EXIT_DEFECT)

    def test_the_defect_names_the_pr_the_path_and_the_age(self):
        """«Что-то не доехало» бесполезно: прибор НАЗЫВАЕТ номер, путь и срок."""
        rep = M.census("o/r",
                       _fetch([_pull(50, BORN_PR50)], {50: _added(LOST_PATH)}),
                       _door(present=()), NOW)
        text = M.render(rep)
        self.assertIn("#50", text)
        self.assertIn(LOST_PATH, text)
        self.assertIn("ЧЕРНОВИК", text)
        # Возраст обязан стоять в САМОЙ строке PR, а не только в пояснении: мутация
        # «render не называет возраст» выжила ровно потому, что число находилось в
        # тексте причины, и слабостью это было у батареи, а не у прибора.
        head = next(l for l in text.splitlines() if "PR #50" in l)
        self.assertIn("27.9", head)

    def test_green_ci_runs_are_not_this_instruments_question(self):
        """Сердце аварии: у PR #50 прогоны ЕСТЬ, и `pr-ci-liveness` был ЗЕЛЁН.

        Прибор обязан краснеть, не спрашивая о прогонах вовсе: иначе он повторил бы
        чужой ответ на чужой вопрос — та самая ошибка «зелёный сторож ≠ ответ».
        """
        pull = _pull(50, BORN_PR50)
        pull["_runs"] = 3                     # прогоны есть; прибор о них не спрашивает
        rep = M.census("o/r", _fetch([pull], {50: _added(LOST_PATH)}), _door(), NOW)
        self.assertEqual(rep["state"], M.NOT_ARRIVED)


class TheDefectIsAConjunctionNotAnAbsence(unittest.TestCase):
    """Свежий PR по построению несёт пути, которых на базе нет. Это НЕ потеря."""

    def test_a_two_day_old_pr_with_absent_paths_is_in_flight_and_green(self):
        born = (NOW - timedelta(days=2)).isoformat()
        rep = M.census("o/r", _fetch([_pull(51, born)], {51: _added("docs/new.md")}),
                       _door(present=()), NOW)
        self.assertEqual(rep["pulls"][0]["state"], M.IN_FLIGHT)
        self.assertEqual(M.exit_code(rep), M.EXIT_OK)

    def test_paths_already_on_the_base_are_arrived(self):
        rep = M.census("o/r", _fetch([_pull(50, BORN_PR50)], {50: _added(LOST_PATH)}),
                       _door(present=(LOST_PATH,)), NOW)
        self.assertEqual(rep["pulls"][0]["state"], M.ARRIVED)
        self.assertEqual(M.exit_code(rep), M.EXIT_OK)

    def test_the_clock_reaches_the_verdict_and_not_only_the_signature(self):
        """Инъекция обязана доходить до ПРОВОДКИ, а не быть параметром для вида.

        Один и тот же PR при двух разных `now` обязан получать РАЗНЫЕ вердикты;
        совпади они — часы в вердикт не входят, и тест про порог сторожил бы воздух.
        """
        args = (_fetch([_pull(50, BORN_PR50)], {50: _added(LOST_PATH)}), _door(present=()))
        late = M.census("o/r", *args, NOW)
        early = M.census("o/r", *args, datetime.fromisoformat(BORN_PR50.replace("Z", "+00:00"))
                         + timedelta(days=1))
        self.assertEqual(late["pulls"][0]["state"], M.NOT_ARRIVED)
        self.assertEqual(early["pulls"][0]["state"], M.IN_FLIGHT)

    def test_the_threshold_is_an_input_too(self):
        rep = M.census("o/r", _fetch([_pull(50, BORN_PR50)], {50: _added(LOST_PATH)}),
                       _door(present=()), NOW, max_age_days=365)
        self.assertEqual(rep["pulls"][0]["state"], M.IN_FLIGHT)


class NotMeasuredIsItsOwnOutcome(unittest.TestCase):
    """Инв. #17: «посмотреть не смог» обязано отличаться и от «нет», и от «есть»."""

    def test_a_refusing_base_door_is_unmeasured_not_a_missing_path(self):
        rep = M.census("o/r", _fetch([_pull(50, BORN_PR50)], {50: _added(LOST_PATH)}),
                       _door(boom=True), NOW)
        self.assertEqual(rep["pulls"][0]["state"], M.UNMEASURED)
        self.assertEqual(M.exit_code(rep), M.EXIT_UNMEASURED)
        self.assertEqual(rep["pulls"][0]["missing"], [],
                         "отказ двери не имеет права попасть в список НЕ ДОЕХАВШИХ")

    def test_a_refusing_base_door_is_not_read_as_clean_either(self):
        rep = M.census("o/r", _fetch([_pull(50, BORN_PR50)], {50: _added(LOST_PATH)}),
                       _door(boom=True), NOW)
        self.assertNotEqual(rep["state"], M.ARRIVED)
        self.assertNotEqual(M.exit_code(rep), M.EXIT_OK)

    def test_a_refusing_files_endpoint_is_unmeasured(self):
        rep = M.census("o/r", _fetch([_pull(50, BORN_PR50)], {}, boom_on="/files"),
                       _door(), NOW)
        self.assertEqual(rep["pulls"][0]["state"], M.UNMEASURED)
        self.assertEqual(M.exit_code(rep), M.EXIT_UNMEASURED)

    def test_a_refusing_pulls_endpoint_is_unmeasured_at_the_top(self):
        rep = M.census("o/r", _fetch([], {}, boom_on="/pulls?"), _door(), NOW)
        self.assertEqual(rep["state"], M.UNMEASURED)
        self.assertEqual(M.exit_code(rep), M.EXIT_UNMEASURED)
        self.assertIn("список PR не получен", rep["reason"])

    def test_a_pr_that_adds_nothing_is_out_of_reach_not_clean(self):
        """PR из одних правок: у изменяемого пути «доехало?» неразрешимо.

        Объявить такой PR чистым значило бы выдать «не измерено» за «прошло» — ровно
        тот дефект, которым прибор и занимается.
        """
        rep = M.census("o/r",
                       _fetch([_pull(9, BORN_PR50)],
                              {9: [{"filename": "data/x.json", "status": "modified"}]}),
                       _door(), NOW)
        self.assertEqual(rep["pulls"][0]["state"], M.UNMEASURED_SCOPE)
        self.assertEqual(M.exit_code(rep), M.EXIT_UNMEASURED)

    def test_a_pr_without_a_creation_date_is_unmeasured(self):
        rep = M.census("o/r", _fetch([_pull(7, None)], {7: _added(LOST_PATH)}), _door(), NOW)
        self.assertEqual(rep["pulls"][0]["state"], M.UNMEASURED)

    def test_five_states_keep_three_distinct_exit_codes(self):
        codes = {s: M.exit_code({"state": s, "pulls": [], "max_age_days": 7})
                 for s in (M.ARRIVED, M.IN_FLIGHT, M.NOT_ARRIVED, M.UNMEASURED)}
        self.assertEqual(codes[M.ARRIVED], M.EXIT_OK)
        self.assertEqual(codes[M.IN_FLIGHT], M.EXIT_OK)
        self.assertEqual(codes[M.NOT_ARRIVED], M.EXIT_DEFECT)
        self.assertEqual(codes[M.UNMEASURED], M.EXIT_UNMEASURED)
        self.assertEqual(len(set(codes.values())), 3)


class TheVerdictIsNotDecidedByText(unittest.TestCase):
    """ADR-333: проба меряет исход, и подстрокой её пройти нельзя."""

    def test_a_pr_titled_delivered_is_still_not_arrived(self):
        rep = M.census("o/r",
                       _fetch([_pull(50, BORN_PR50, "ДОСТАВЛЕНО: всё доехало, arrived")],
                              {50: _added(LOST_PATH)}),
                       _door(present=()), NOW)
        self.assertEqual(rep["pulls"][0]["state"], M.NOT_ARRIVED)

    def test_a_similar_looking_path_on_the_base_does_not_count(self):
        """На базе лежит ПОХОЖИЙ путь — вердикт обязан остаться красным.

        Сверка идёт по полному пути, а не по вхождению: иначе достаточно было бы
        одноимённого файла в другом каталоге, чтобы прибор замолчал.
        """
        rep = M.census("o/r", _fetch([_pull(50, BORN_PR50)], {50: _added(LOST_PATH)}),
                       _door(present=("docs/RS-portfolio-cio-audit-2026-08-29.md",)), NOW)
        self.assertEqual(rep["pulls"][0]["state"], M.NOT_ARRIVED)

    def test_one_missing_path_out_of_many_is_enough(self):
        rep = M.census("o/r",
                       _fetch([_pull(50, BORN_PR50)], {50: _added("a.md", "b.md", LOST_PATH)}),
                       _door(present=("a.md", "b.md")), NOW)
        self.assertEqual(rep["pulls"][0]["state"], M.NOT_ARRIVED)
        self.assertEqual(rep["pulls"][0]["missing"], [LOST_PATH])


class TheRealBaseDoorAnswersAllThree(unittest.TestCase):
    """Дверь по умолчанию — настоящий git. Сеть не нужна: спрашиваем своё дерево."""

    def setUp(self):
        got = subprocess.run(["git", "rev-parse", "--verify", "HEAD^{commit}"],
                             cwd=REPO, capture_output=True, text=True)
        if got.returncode != 0:
            self.fail("предпосылка не обеспечена: дерево теста не является git-репозиторием "
                      "— вердикт о двери НЕ ИЗМЕРЕН, и молчать об этом нельзя")
        self.door = M.git_base_door(str(REPO))

    def test_a_path_that_exists_is_reported_present(self):
        # Путь выбран давно существующим НАМЕРЕННО: сам этот прибор в момент написания
        # теста ещё не закоммичен, и спрашивать у HEAD о нём значило бы мерить не дверь,
        # а состояние индекса.
        self.assertTrue(self.door("HEAD", "scripts/check_pr_ci_runs.py"))

    def test_a_path_that_does_not_exist_is_reported_absent(self):
        self.assertFalse(self.door("HEAD", "scripts/no-such-file-b7f3a1.py"))

    def test_an_unknown_ref_raises_instead_of_answering_absent(self):
        """Ключевое различение: нет ВЕТКИ ⇒ «спросить не у кого», не «файла нет».

        Ответь дверь `False`, прибор объявил бы КАЖДЫЙ путь не доехавшим и выдал бы
        ложный CRITICAL — отказ, выдающий себя за измерение.
        """
        with self.assertRaises(M.BaseUnreadable):
            self.door("origin/no-such-branch-b7f3a1", "scripts/check_pr_ci_runs.py")


class TheInstrumentHasAReader(unittest.TestCase):
    """Прибор без читателя — украшение (урок тир-куратора, `.claude/rules/acceptance.md`)."""

    def test_the_scheduled_workflow_calls_the_census(self):
        wf = (REPO / ".github" / "workflows" / "pr-ci-liveness.yml").read_text()
        self.assertIn("pr_delivery_census.py", wf)

    def test_the_census_is_not_gated_behind_the_neighbour_step(self):
        """Шаг-сосед («а прогон БЫЛ?») сегодня КРАСНЫЙ — у PR #9 и #10 прогонов ноль.

        Без `if: always()` второй вопрос не задавался бы вовсе, пока не закрыт первый:
        сторож, замолчавший от чужой красноты, молчит ровно тогда, когда нужен.
        """
        wf = (REPO / ".github" / "workflows" / "pr-ci-liveness.yml").read_text()
        step = wf.split("Открытый PR — это НЕ доставленная работа", 1)[1]
        self.assertIn("if: always()", step.split("- name:")[0])

    def test_the_census_step_is_not_allowed_to_be_silenced(self):
        """`continue-on-error` у шага вернул бы ровно ту тишину, против которой ADR-477."""
        wf = (REPO / ".github" / "workflows" / "pr-ci-liveness.yml").read_text()
        self.assertNotIn("continue-on-error", wf)


if __name__ == "__main__":
    unittest.main()
