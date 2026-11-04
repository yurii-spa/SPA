# LLM_FORBIDDEN
"""spa_core/tests/test_runner_env_rod_subtraction.py — ШОВ У ВИЛКИ: род
«ОКРУЖЕНИЕ РАННЕРА» вычитается из числа дефектов у ЕДИНСТВЕННОЙ двери (ADR-915).

**Зачем (цикл #1028, заказ G905 п. 1).** Замер #1027 (ADR-913) прогнал дефектную
часть красного набора CI (56 имён) ПОИМЁННО на чистом дереве того же коммита и нашёл,
что **19 из 56 ЗЕЛЕНЫ у себя** — двумя независимыми наблюдениями, 19 из 19. Их
краснота есть свойство МАШИНЫ, не кода. Прибор при этом печатал «дефектов НЕ МЕНЬШЕ
42 и НЕ БОЛЬШЕ 56», а дефектная часть после вычета девятнадцати — **37**:

    42 > 37

то есть опубликованная вилка противоречила САМА СЕБЕ. Нижний край считан по ВСЕМУ
набору, и девятнадцать имён, падающих от свойств раннера, дали прибору девятнадцать
«причин дефекта».

**Лечение — ровно образец ADR-910:** род выводится из вилки у ЕДИНСТВЕННОЙ двери
``fork_of``, а не у каждого читателя. Вилку печатают ТРИ разных места
(``format_census`` · ``as_json`` · ``ci_control.cause_line``), и читатель, вычитающий
род у себя, разошёлся бы с двумя другими МОЛЧА (класс ADR-220).

**Чем этот род отличается от рода часов — ИСТОЧНИКОМ, и отсюда третий исход.** Род
часов опознаётся по сообщению самого провала (литерал производителя срока). «Зелен на
своём дереве» в тексте исключения не написано и не может быть написано: это вердикт
ЗАМЕРА. Поэтому источник — ВНЕШНЕЕ ОБЪЯВЛЕНИЕ
(``spa_core/tests/ci_only_red_class_baseline.json``, доставлено ADR-913), и его
отсутствие обязано быть ТРЕТЬИМ ИСХОДОМ: род НЕ ИЗМЕРЕН ⇒ из вилки не выносится
НИЧЕГО (fail-CLOSED, дословно правило ADR-910, инв. #17).

**Контроли — на НАСТОЯЩЕМ читателе** (`.claude/rules/deployment.md`, § «Проверка
сторожа сторожей»; урок #944/#945: контроль на словаре, собранном руками, мерит свой
словарь, а не проводку). Каждая сцена кладёт файл объявления во временный каталог и
зовёт те же ``env_declaration`` / ``fork_of`` / ``cause_line``, что и боевой путь.
Контроли идут ПАРАМИ и отвечают ПРОТИВОПОЛОЖНО на сценах, отличающихся РОВНО одним
обстоятельством, — иначе проверялся бы текст, а не различение.

Только stdlib, оффлайн. Литеральных дат нет вовсе: свежести этот сторож не судит.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from spa_core.monitoring import failure_cause_census as fcc

import importlib.util as _ilu

_REPO = Path(__file__).resolve().parents[2]


def _load_ci_control():
    """`scripts/ci_control.py` берётся ПО ПУТИ — пакетом он не является."""
    spec = _ilu.spec_from_file_location("_ci_control_for_env_rod",
                                        _REPO / "scripts" / "ci_control.py")
    module = _ilu.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ctl = _load_ci_control()

#: Кадр репозитория для `--tb=short`: без него место провала не опознаётся и
#: верхний край вилки считался бы по другому ключу.
REPO_TB = "spa_core/x.py:10: in test_a\n    assert False\nE   AssertionError: boom"
TIMEOUT_CALL = "Failed: Timeout (>180.0s) from pytest-timeout."


def junit(cases: list[str]) -> str:
    return ("<testsuites><testsuite name='s' tests='%d'>%s</testsuite></testsuites>"
            % (len(cases), "".join(cases)))


def case(classname: str, name: str, *, message: str, text: str = REPO_TB) -> str:
    return (f"<testcase classname='{classname}' name='{name}'>"
            f"<failure message=\"{message}\">{text}</failure></testcase>")


class Scene(unittest.TestCase):
    """Одноразовый каталог + свои объявления. Боевой файл не трогается ничем."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write_declaration(self, members: list[str] | None = None, *,
                          schema: str = fcc.ENV_SCHEMA,
                          raw: str | None = None,
                          member_rows: list[dict] | None = None) -> Path:
        path = self.root / "decl.json"
        if raw is not None:
            path.write_text(raw, encoding="utf-8")
            return path
        rows = member_rows if member_rows is not None else [
            {"nodeid": m, "ci_outcome": "failed", "local_outcome": "passed",
             "ci_cause": "AssertionError: boom", "door": "runner_environment",
             "measured_in": "сцена контроля"}
            for m in (members or [])]
        path.write_text(json.dumps({"schema": schema, "members": rows},
                                   ensure_ascii=False), encoding="utf-8")
        return path

    def census(self, cases: list[str]):
        path = self.root / "j.xml"
        path.write_text(junit(cases), encoding="utf-8")
        return fcc.census_from_path(path)

    def fork(self, cases: list[str], declaration: Path | None):
        return fcc.fork_of(self.census(cases).call,
                           env=fcc.env_declaration(declaration))


# ── 1. предмет ADR-915: объявленное имя уходит из вилки ──────────────────────

class TheDeclaredNameLeavesTheFork(Scene):

    CASES = [
        case("spa_core.tests.test_a", "test_defect", message="KeyError: 'identity'"),
        case("spa_core.tests.test_b", "test_env", message="AssertionError: boom"),
    ]
    #: Объявление пишет форму pytest, запись провала несёт форму junit.
    DECLARED = "spa_core/tests/test_b.py::test_env"

    def test_the_declared_name_is_subtracted_from_the_defect_fork(self):
        """ПРЕДМЕТ: имя, зелёное на своём дереве, стояло среди дефектов кода."""
        fork = self.fork(self.CASES, self.write_declaration([self.DECLARED]))
        self.assertEqual(fork.runner_environment, 1)
        self.assertEqual(fork.population, 1,
                         "род окружения раннера остался в вилке дефектов")
        self.assertEqual(fork.upper, 1, "верхний край всё ещё считает род окружения")

    def test_WITHOUT_the_declaration_the_same_set_keeps_both(self):
        """Порванное звено (обратная сторона той же сцены): нет объявления — нет вычета.

        Сцены отличаются РОВНО наличием файла объявления, и отвечают
        ПРОТИВОПОЛОЖНО. Без этой пары проверялось бы, что число «1» где-то есть.
        """
        fork = self.fork(self.CASES, self.root / "нет-такого-файла.json")
        self.assertEqual(fork.runner_env_read, fcc.ENV_ABSENT)
        self.assertEqual(fork.runner_environment, 0)
        self.assertEqual(fork.population, 2,
                         "вычло падение, не прочитав объявления — fail-OPEN")

    def test_the_rod_is_named_by_nodeid_not_merely_counted(self):
        """Счётчик без имён не даёт ни починить, ни опровергнуть членство."""
        fork = self.fork(self.CASES, self.write_declaration([self.DECLARED]))
        self.assertEqual(list(fork.runner_environment_names),
                         ["spa_core.tests.test_b::test_env"])

    def test_a_set_without_declared_names_is_left_exactly_as_before(self):
        """Обратная сторона: объявление ЕСТЬ и пусто — вилка не двигается."""
        fork = self.fork(self.CASES, self.write_declaration([]))
        self.assertEqual((fork.population, fork.runner_environment), (2, 0))
        self.assertTrue(fork.measured_runner_env)


# ── 2. форма имени: канонизация есть ПРЕДПОСЫЛКА сверки ──────────────────────

class TheNameFormIsCanonisedByTheSingleDoor(Scene):
    """Урок #1026 дословно: артефакт канонизатора ПОДДЕЛЫВАЕТ дельту.

    Объявление пишет `путь/к/файлу.py::Класс::тест`, запись провала несёт
    `путь.к.файлу.Класс::тест`. Сверка двух форм без приведения даёт ПУСТОЕ
    пересечение и читается как «класса в наборе нет» — то есть род молча
    перестаёт вычитаться, и об этом никто не узнаёт.
    """

    def test_the_pytest_form_in_the_declaration_matches_the_junit_form_of_a_failure(self):
        decl = self.write_declaration(
            ["spa_core/tests/test_b.py::TheClass::test_env"])
        fork = self.fork([case("spa_core.tests.test_b.TheClass", "test_env",
                               message="AssertionError: boom")], decl)
        self.assertEqual(fork.runner_environment, 1,
                         "формы имени не приведены — сверка молча опустела")

    def test_the_raw_form_would_NOT_match_and_that_is_the_torn_link(self):
        """Порванное звено названо ЧИСЛОМ: без приведения вычет равен нулю."""
        declared = "spa_core/tests/test_b.py::TheClass::test_env"
        raw = fcc.env_declaration(self.write_declaration([declared])).names
        self.assertNotIn(declared, raw, "имя осталось в форме pytest — дверь не позвана")
        self.assertIn("spa_core.tests.test_b.TheClass::test_env", raw)

    def test_two_members_collapsing_to_one_name_is_NOT_MEASURED(self):
        """Предпосылка объявлена: имён обязано выйти столько, сколько членов.

        Схлопнулись два члена в одно имя ⇒ вычитать по такому набору значило бы
        выносить из вилки неизвестно что.
        """
        decl = self.write_declaration(["spa_core/tests/test_b.py::test_env",
                                       "spa_core/tests/test_b.py::test_env"])
        read = fcc.env_declaration(decl)
        self.assertEqual(read.read, fcc.ENV_NAME_COLLISION)
        self.assertIn("предпосылка сверки НЕ ВЫПОЛНЕНА", read.reason)


# ── 3. третий исход у КАЖДОЙ двери чтения, и каждый fail-CLOSED ──────────────

class EveryUnreadableDeclarationIsNamedAndFailsClosed(Scene):

    CASES = [case("spa_core.tests.test_b", "test_env",
                  message="AssertionError: boom")]
    DECLARED = "spa_core/tests/test_b.py::test_env"

    def _assert_closed(self, declaration: Path, expected: str) -> None:
        read = fcc.env_declaration(declaration)
        self.assertEqual(read.read, expected)
        self.assertFalse(read.measured)
        self.assertTrue(read.reason, "исход назван, а причина — нет")
        fork = fcc.fork_of(self.census(self.CASES).call, env=read)
        self.assertEqual(fork.runner_environment, 0)
        self.assertEqual(fork.population, 1,
                         "НЕ ИЗМЕРЕНО сработало оправданием — провал вынесен из вилки")

    def test_an_absent_file(self):
        self._assert_closed(self.root / "нет.json", fcc.ENV_ABSENT)

    def test_a_file_that_does_not_parse(self):
        self._assert_closed(self.write_declaration(raw="{не json"),
                            fcc.ENV_UNREADABLE)

    def test_a_foreign_schema(self):
        self._assert_closed(self.write_declaration([self.DECLARED],
                                                   schema="чужая/7"),
                            fcc.ENV_BAD_SCHEMA)

    def test_a_document_that_is_not_a_mapping(self):
        self._assert_closed(self.write_declaration(raw="[1, 2, 3]"),
                            fcc.ENV_BAD_SCHEMA)

    def test_members_absent_or_not_a_list(self):
        path = self.root / "decl.json"
        path.write_text(json.dumps({"schema": fcc.ENV_SCHEMA, "members": {}}),
                        encoding="utf-8")
        self._assert_closed(path, fcc.ENV_NO_MEMBERS)

    def test_a_member_without_a_nodeid_string(self):
        """Объявление разобрано НЕ ЦЕЛИКОМ ⇒ вычитать по его части нельзя."""
        self._assert_closed(
            self.write_declaration(member_rows=[{"nodeid": self.DECLARED},
                                                {"ci_outcome": "failed"}]),
            fcc.ENV_BAD_MEMBER)

    def test_the_outcome_set_is_closed(self):
        self.assertEqual(
            fcc.ENV_CLASSES,
            (fcc.ENV_READ_OK, fcc.ENV_ABSENT, fcc.ENV_UNREADABLE,
             fcc.ENV_BAD_SCHEMA, fcc.ENV_NO_MEMBERS, fcc.ENV_BAD_MEMBER,
             fcc.ENV_NAME_COLLISION, fcc.ENV_NOT_ASKED))


# ── 4. порядок вычитания: имя под ДВУМЯ родами считается ОДИН раз ────────────

class TheTwoRodsDoNotDoubleCount(Scene):

    def test_a_name_under_both_rods_is_counted_once_in_the_clock_rod(self):
        """Двойной счёт сломал бы тождество учёта и дал бы ДВА объяснения одному."""
        decl = self.write_declaration(["spa_core/tests/test_b.py::test_slow"])
        fork = self.fork([
            case("spa_core.tests.test_a", "test_defect",
                 message="KeyError: 'identity'"),
            case("spa_core.tests.test_b", "test_slow", message=TIMEOUT_CALL),
        ], decl)
        self.assertEqual(fork.wallclock_timeouts, 1)
        self.assertEqual(fork.runner_environment, 0,
                         "имя сосчитано ОБОИМИ родами — тождество учёта сломано")
        self.assertEqual(fork.population, 1)
        self.assertTrue(fork.accounting_holds)

    def test_the_accounting_identity_covers_BOTH_rods(self):
        decl = self.write_declaration(["spa_core/tests/test_c.py::test_env"])
        fork = self.fork([
            case("spa_core.tests.test_a", "test_defect",
                 message="KeyError: 'identity'"),
            case("spa_core.tests.test_b", "test_slow", message=TIMEOUT_CALL),
            case("spa_core.tests.test_c", "test_env",
                 message="AssertionError: boom"),
        ], decl)
        self.assertEqual((fork.population, fork.wallclock_timeouts,
                          fork.runner_environment, fork.given), (1, 1, 1, 3))
        self.assertTrue(fork.accounting_holds)

    def test_a_broken_accounting_is_REPORTED_and_not_silent(self):
        """Порванное звено: тождество обязано быть опровержимым.

        Собранная руками вилка, у которой слагаемые не сходятся, обязана говорить
        об этом — иначе род, забытый читателем, исчезал бы молча (урок ADR-675).
        """
        bad = fcc.Fork(population=1, cause_groups=1, coarse_groups=1, lower=1,
                       upper=1, merged_by_evidence=0, largest_component=1,
                       groups=(), wallclock_timeouts=0, runner_environment=0,
                       given=2)
        self.assertFalse(bad.accounting_holds)


# ── 5. ТРИ печатающих места говорят об этом, и ни одно не молчит ─────────────

class AllThreeReadersSayIt(Scene):

    CASES = [
        case("spa_core.tests.test_a", "test_defect", message="KeyError: 'identity'"),
        case("spa_core.tests.test_b", "test_env", message="AssertionError: boom"),
    ]
    DECLARED = "spa_core/tests/test_b.py::test_env"

    def test_format_census_names_the_rod_and_says_the_fork_excludes_it(self):
        decl = fcc.env_declaration(self.write_declaration([self.DECLARED]))
        out = fcc.format_census(self.census(self.CASES), env=decl)
        self.assertIn("ОКРУЖЕНИЕ РАННЕРА: 1", out)
        self.assertIn("НЕ входят", out)
        self.assertIn("spa_core.tests.test_b::test_env", out)
        self.assertIn("род окружения раннера ВЫЧТЕН", out)

    def test_format_census_says_NOT_MEASURED_when_the_declaration_is_absent(self):
        """Пара к предыдущему: сцены отличаются РОВНО наличием объявления."""
        decl = fcc.env_declaration(self.root / "нет.json")
        out = fcc.format_census(self.census(self.CASES), env=decl)
        self.assertIn("род ОКРУЖЕНИЯ РАННЕРА НЕ ИЗМЕРЕН", out)
        self.assertIn("БЕЗ вычитания рода окружения раннера", out)
        self.assertNotIn("род окружения раннера ВЫЧТЕН", out)

    def test_format_census_says_measured_ZERO_in_words(self):
        """«Рода нет» сказано словом: молчание совпало бы с «не измерено»."""
        decl = fcc.env_declaration(self.write_declaration([]))
        out = fcc.format_census(self.census(self.CASES), env=decl)
        self.assertIn("измерено и равно нулю", out)

    def test_as_json_carries_the_rod_and_the_read_outcome(self):
        decl = fcc.env_declaration(self.write_declaration([self.DECLARED]))
        payload = fcc.as_json(self.census(self.CASES), env=decl)["call"]
        self.assertEqual(payload["runner_environment"], 1)
        self.assertEqual(payload["runner_environment_names"],
                         ["spa_core.tests.test_b::test_env"])
        self.assertEqual(payload["runner_env_read"], fcc.ENV_READ_OK)
        self.assertEqual(payload["population"], 1)

    def test_cause_line_names_the_rod_BEFORE_the_fork(self):
        """Читатель обязан увидеть род ДО вилки, иначе пойдёт чинить код."""
        line = ctl.cause_line(_axis(runner=2, names=["a::x", "b::y"]))
        self.assertIn("ОКРУЖЕНИЕ РАННЕРА 2", line)
        self.assertIn("в вилку дефектов НЕ входят", line)
        self.assertLess(line.index("ОКРУЖЕНИЕ РАННЕРА"),
                        line.index("дефектов НЕ МЕНЬШЕ"),
                        "род напечатан ПОСЛЕ вилки — читатель уже решил, что это поломки")
        self.assertIn("род окружения раннера ВЫЧТЕН", line)

    def test_cause_line_cuts_names_BY_COUNT_and_names_the_rest_by_number(self):
        names = [f"spa_core/tests/test_{i}.py::K::test_long_enough_to_be_cut_{i}"
                 for i in range(7)]
        line = ctl.cause_line(_axis(runner=7, names=names))
        for whole in names[:ctl._ROD_NAMES_SHOWN]:
            self.assertIn(whole, line, "имя рода обрезано — починить его нечем")
        self.assertIn(f"и ещё {7 - ctl._ROD_NAMES_SHOWN}", line)


# ── 6. ЧЕТВЁРТОЕ состояние у свода: ключа нет ВОВСЕ (урок ADR-911) ──────────

def _axis(*, runner: int = 0, names: list[str] | None = None,
          read: str = fcc.ENV_READ_OK) -> dict:
    """Ось причин, собранная цензом ПОСЛЕ шва ADR-915."""
    return {"status": "measured", "population": 40, "attributed": 40,
            "kinds": {"AssertionError": 40},
            "fork": {"population": 40 - runner, "lower": 29, "upper": 37,
                     "largest_component": 4, "wallclock_timeouts": 0,
                     "wallclock_names": [], "rod_unmeasured": 0, "given": 40,
                     "runner_environment": runner,
                     "runner_environment_names": list(names or []),
                     "runner_env_read": read,
                     "runner_env_reason": "сцена"},
            "top": [["AssertionError", "# != #", 4]],
            "identities_hold": {"phases": True, "cause_classes": True,
                                "site_classes": True, "roster": True,
                                "fork_accounting": True}}


class TheSummaryOlderThanThisShimIsNamed(unittest.TestCase):
    """Отчёт приезжает к читателю ГОТОВЫМ из артефакта прогона, собранного тем
    коммитом, который мерили. Пока шов не на `main`, поля `runner_environment`
    нет ВОВСЕ — и `.get()` отдал бы у него тот же `0`, что у настоящего нуля, то
    есть строка утверждала бы вычитание, которого не было (дословный урок ADR-911:
    такое показание врало в 1 случае из 1).

    Контроли ПАРОЙ, оси отличаются РОВНО наличием ключа.
    """

    @staticmethod
    def _without_key() -> dict:
        axis = _axis()
        fork = dict(axis["fork"])
        for key in ("runner_environment", "runner_environment_names",
                    "runner_env_read", "runner_env_reason"):
            fork.pop(key, None)
        return {**axis, "fork": fork}

    def test_a_summary_without_the_key_says_NOT_MEASURED(self):
        line = ctl.cause_line(self._without_key())
        self.assertIn("род ОКРУЖЕНИЯ РАННЕРА этим сводом НЕ ИЗМЕРЕН", line)
        self.assertIn("старше ADR-915", line)
        self.assertIn("не вычтено НИ ОДНО падение", line)

    def test_a_summary_without_the_key_does_NOT_claim_an_exclusion(self):
        line = ctl.cause_line(self._without_key())
        self.assertIn("БЕЗ вычитания рода окружения раннера", line)
        self.assertNotIn("род окружения раннера ВЫЧТЕН", line)

    def test_a_declared_ZERO_still_claims_the_exclusion(self):
        """Обратная сторона: ноль ОБЪЯВЛЕН — вычитание спрашивали, и это правда."""
        line = ctl.cause_line(_axis(runner=0))
        self.assertIn("род окружения раннера ВЫЧТЕН", line)
        self.assertNotIn("ОКРУЖЕНИЯ РАННЕРА НЕ ИЗМЕРЕН", line)

    def test_an_unread_declaration_in_the_summary_is_named_with_its_reason(self):
        """Пятое состояние: ключ ЕСТЬ, а объявление не прочитано тем прогоном."""
        line = ctl.cause_line(_axis(read=fcc.ENV_ABSENT))
        self.assertIn("род ОКРУЖЕНИЯ РАННЕРА НЕ ИЗМЕРЕН", line)
        self.assertIn(fcc.ENV_ABSENT, line)
        self.assertIn("не вычтено НИ ОДНО падение", line)

    def test_the_two_axes_differ_by_exactly_the_four_keys(self):
        """Предпосылка пары: сцены отличаются РОВНО объявлением рода, не числами."""
        with_key = _axis()["fork"]
        without = self._without_key()["fork"]
        self.assertEqual(set(with_key) - set(without),
                         {"runner_environment", "runner_environment_names",
                          "runner_env_read", "runner_env_reason"})

    def test_a_hand_built_fork_defaults_to_NOT_ASKED(self):
        """Умолчание fail-CLOSED: вилка, собранная руками, вычитания не утверждает."""
        fork = fcc.Fork(population=1, cause_groups=1, coarse_groups=1, lower=1,
                        upper=1, merged_by_evidence=0, largest_component=1,
                        groups=(), given=1)
        self.assertEqual(fork.runner_env_read, fcc.ENV_NOT_ASKED)
        self.assertFalse(fork.measured_runner_env)


# ── 7. ПАРИТЕТ двух читателей одного объявления ──────────────────────────────

class TheTwoReadersOfTheDeclarationAgree(unittest.TestCase):
    """Копий читателя объявления ДВЕ, и это измеренная цена, а не недосмотр.

    Сторож объявления (`test_ci_only_red_class_ratchet.py`) живёт в тест-каталоге и
    из рантайм-модуля не импортируется; `cause_line` судит СЛОВАРЬ из чужого отчёта и
    тоже держит свою копию литерала исхода. Две копии, разошедшиеся молча, и есть
    класс ADR-220 — поэтому согласие ИЗМЕРЯЕТСЯ здесь, у обеих сразу.
    """

    def test_the_schema_string_is_the_same_in_both_readers(self):
        from spa_core.tests import test_ci_only_red_class_ratchet as ratchet
        self.assertEqual(fcc.ENV_SCHEMA, ratchet.SCHEMA)

    def test_both_readers_see_the_same_member_set(self):
        from spa_core.tests import test_ci_only_red_class_ratchet as ratchet
        self.assertEqual(fcc.ENV_DECLARATION, ratchet.BASELINE,
                         "читатели смотрят в РАЗНЫЕ файлы")
        mine = fcc.env_declaration()
        self.assertTrue(mine.measured, f"боевое объявление не прочитано: {mine.reason}")
        theirs = ratchet.load_declaration()
        self.assertEqual(
            mine.declared, len(theirs["members"]),
            "два читателя одного объявления видят РАЗНОЕ число членов")
        self.assertEqual(
            mine.names,
            frozenset(fcc.junit_name(m["nodeid"]) for m in theirs["members"]))

    def test_the_literal_of_cause_line_equals_the_censors_constant(self):
        self.assertEqual(ctl._ENV_READ_OK, fcc.ENV_READ_OK,
                         "копия литерала исхода в своде разошлась с цензом")


if __name__ == "__main__":
    unittest.main()
