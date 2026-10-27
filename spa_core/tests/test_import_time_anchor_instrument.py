#!/usr/bin/env python3
"""Сторож сторожа: умеет ли прибор `import_time_anchor_bombs` отличить бомбу от честного теста.

Предмет — класс, найденный 12.09: якорь времени вида ``NOW = now_utc()`` на уровне модуля
вычисляется на СБОРЕ набора, а субъект спрашивает часы в момент ВЫПОЛНЕНИЯ. В одиночном
прогоне между ними доли секунды, в полном — полтора часа; запись «120 секунд назад»
оказывается старше получасового окна, и тест краснеет от длительности прогона. Храповик
``frozen_date_baseline.json`` этот фитиль не видит по построению: литеральной даты здесь нет.

Проверка идёт на СИНТЕТИЧЕСКИХ сценах в ``tmp_path``, а не на живом наборе: полный замер
класса стоит две минуты и поднимает второй pytest в том же дереве — это отдельный
инструмент, запускаемый шагом цикла (1г), а не шаг набора.

**Обе стороны обязательны, и вторая важнее.** У прибора уже было ДВЕ неверных редакции,
и обе были зелены на своей же первой стороне:

1. состаривание якоря тест-модуля рассинхронизировало его со значениями по умолчанию
   (``def _beacon(..., now=FIXED_NOW)`` связывается на импорте) — прибор объявил бомбами
   **14 тестов из 14**, у которых часы честно инъектированы;
2. сдвиг часов у одного лишь продукта (тест-помощники исключены) объявлял бомбой ВЕРНУЮ
   починку: она берёт якорь в момент утверждения и обязана получить то же «сейчас», что и
   субъект.

Поэтому сцены здесь три: бомба (обязана быть найдена), починенная бомба и честно
инъектированные часы (обе обязаны остаться чистыми).
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location(
    "_iab", ROOT / "scripts" / "import_time_anchor_bombs.py")
iab = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(iab)

#: Задержка сцены — заведомо шире получасового окна дедупа, как и в живом полном прогоне.
LAG_MIN = 95.0

_BOMB = '''
from datetime import timedelta
import json
from spa_core.alerts import telegram_client as tc
from spa_core.tests._freshness import now_utc

NOW = now_utc()                      # ЯКОРЬ НА ИМПОРТЕ — предмет класса


def test_scene(tmp_path, monkeypatch):
    monkeypatch.setenv("SPA_TELEGRAM_DUP_TEST", "1")
    p = tmp_path / "alert_history.json"
    p.write_text(json.dumps({"entries": [
        {"ts": (NOW - timedelta(seconds=120)).isoformat(),
         "preview": "повтор"[:tc._PREVIEW_LEN], "ok": True}]}), encoding="utf-8")
    monkeypatch.setattr(tc, "_HISTORY_STATE", p)
    assert tc._duplicate_recently("повтор") is True
'''

#: Та же сцена с починкой: якорь связывается ПЕРЕД тестом, утверждение не тронуто.
_FIXED = _BOMB.replace(
    "NOW = now_utc()                      # ЯКОРЬ НА ИМПОРТЕ — предмет класса",
    "import pytest\n\nNOW = now_utc()\n\n\n"
    "@pytest.fixture(autouse=True)\ndef _anchor():\n    global NOW\n    NOW = now_utc()")

#: Честно инъектированные часы: субъект получает время АРГУМЕНТОМ и часов не спрашивает.
#: Значение по умолчанию связано на импорте — ровно та форма, на которой прибор ошибся.
_INJECTED = '''
from datetime import timedelta
from spa_core.tests._freshness import now_utc

FIXED_NOW = now_utc()


def _age_hours(stamp, now=FIXED_NOW):
    return (now - stamp).total_seconds() / 3600.0


def test_scene():
    assert _age_hours(FIXED_NOW - timedelta(minutes=1)) < 0.5
'''


def _scene(tmp_path: Path, name: str, body: str) -> str:
    p = tmp_path / f"test_{name}.py"
    p.write_text(body, encoding="utf-8")
    return str(p)


class TheInstrumentTellsABombFromAnHonestTest(unittest.TestCase):
    """Обе стороны: находит настоящую бомбу и молчит на честных часах."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="spa_anchor_scene_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _verdicts(self, body: str, name: str):
        f = [_scene(self.tmp, name, body)]
        return iab.outcomes(f, 0.0, ROOT), iab.outcomes(f, LAG_MIN, ROOT)

    def test_a_real_bomb_is_found(self):
        """Положительный контроль: без него прибор — украшение."""
        base, aged = self._verdicts(_BOMB, "bomb")
        self.assertEqual(base.get("__passed__"), "1",
                         "сцена обязана быть зелёной БЕЗ задержки, иначе она сломана, а не бомба")
        self.assertTrue(any(v == "FAILED" for k, v in aged.items() if k != "__passed__"),
                        "прибор не увидел бомбу — он не отвечает на свой вопрос")

    def test_the_fix_is_not_called_a_bomb(self):
        """Починка обязана пройти: иначе прибор требует ослабить верный тест."""
        base, aged = self._verdicts(_FIXED, "fixed")
        self.assertEqual((base.get("__passed__"), aged.get("__passed__")), ("1", "1"),
                         "верная починка объявлена бомбой — это ошибка ВТОРОЙ редакции прибора")

    def test_an_injected_clock_is_not_called_a_bomb(self):
        """Ошибка ПЕРВОЙ редакции: 14 ложных находок из 14 на этой самой форме."""
        base, aged = self._verdicts(_INJECTED, "injected")
        self.assertEqual((base.get("__passed__"), aged.get("__passed__")), ("1", "1"),
                         "часы инъектированы — длительность прогона не имеет права на них влиять")


#: Та же бомба, но её утверждение живёт ТОЛЬКО под `self.subTest`. Предмет — не часы,
#: а ВИДИМОСТЬ носителя прибору: падение под `subTest` pytest печатает строкой
#: `SUBFAILED(...)`, сам тест при этом идёт точкой и попадает в «N passed». До цикла
#: #951 `_OUTCOME` читал только `FAILED|ERROR|SKIPPED` ⇒ такая бомба была приборУ
#: НЕОТЛИЧИМА от прошедшего теста на ОБЕИХ сторонах сравнения, то есть молчала.
_BOMB_UNDER_SUBTEST = '''
from datetime import timedelta
import unittest
from spa_core.tests._freshness import now_utc

NOW = now_utc()                      # ЯКОРЬ НА ИМПОРТЕ — предмет класса


class Scene(unittest.TestCase):
    def test_scene(self):
        with self.subTest(side="носитель живёт только здесь"):
            self.assertLess((now_utc() - NOW).total_seconds(), 60)
'''


class TheInstrumentSeesACarrierHiddenUnderSubTest(unittest.TestCase):
    """Носитель утверждения под `self.subTest` обязан доходить до вердикта.

    Класс найден циклом #951 замером на НАСТОЯЩЕМ pytest 9.0.3 и общий у двух приборов
    цикла: тот же дефект жил в `delta_mutation_run._FAILED_LINE`, где за четыре цикла
    (#876, #947, #950) съел девять мутационных находок. Ошибка здесь шла в сторону
    САМОУСПОКОЕНИЯ — «бомб нет», — то есть тише красного и потому опаснее.

    Обе стороны обязательны: прибор видит носителя под `subTest` И не меняет вердикт
    там, где `subTest` стои́т вокруг честно инъектированных часов."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="spa_anchor_subtest_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _verdicts(self, body: str, name: str):
        f = [_scene(self.tmp, name, body)]
        return iab.outcomes(f, 0.0, ROOT), iab.outcomes(f, LAG_MIN, ROOT)

    def test_a_bomb_whose_assertion_lives_only_under_subtest_is_found(self):
        """Положительный контроль класса #951. ДО правки обе стороны давали «passed»."""
        base, aged = self._verdicts(_BOMB_UNDER_SUBTEST, "bomb_subtest")
        self.assertEqual(base.get("__passed__"), "1",
                         "сцена обязана быть зелёной БЕЗ задержки, иначе она сломана, "
                         "а не бомба")
        exploded = [(k, v) for k, v in aged.items() if k != "__passed__"]
        self.assertEqual([v for _, v in exploded], ["SUBFAILED"],
                         f"прибор не увидел носителя под subTest: {aged}")
        self.assertEqual(aged.get("__passed__"), "1",
                         "и это главное в находке: pytest СЧИТАЕТ такой тест прошедшим "
                         "— по счётчику прошедших бомба неразличима")

    def test_a_subtest_around_an_injected_clock_is_still_not_a_bomb(self):
        """Обратная сторона: `subTest` сам по себе бомбой не делает. Без неё правка
        читалась бы как «считать подозрительным всё, что под subTest»."""
        body = _INJECTED.replace(
            "def test_scene():\n"
            "    assert _age_hours(FIXED_NOW - timedelta(minutes=1)) < 0.5\n",
            "import unittest\n\n\n"
            "class Scene(unittest.TestCase):\n"
            "    def test_scene(self):\n"
            "        with self.subTest(side='часы инъектированы'):\n"
            "            self.assertLess(_age_hours(FIXED_NOW - timedelta(minutes=1)), 0.5)\n")
        base, aged = self._verdicts(body, "injected_subtest")
        self.assertEqual((base.get("__passed__"), aged.get("__passed__")), ("1", "1"),
                         f"часы инъектированы — задержка влиять не вправе: {base} / {aged}")

    def test_a_name_printed_twice_gets_the_outer_failure(self):
        """НАБЛЮДАЕМЫЙ ДОГОВОР на случай двух строк об одном имени.

        Тест, упавший И под `subTest`, И вне него, печатает ДВЕ строки сводки на одно
        имя. Прибор берёт последнюю, и это ИЗМЕРЕНО достаточным: pytest печатает отчёты
        в порядке фаз, поэтому сильнейший исход и так приходит последним. Таблица
        приоритетов была написана этим же циклом и СНЯТА — прибор по дельте показал её
        мутанта выжившим, и выживший оказался ЭКВИВАЛЕНТНЫМ (урок #949): ни один
        достижимый вывод pytest двух правил не различает.

        Сцена закрепляет не реализацию, а ответ: сменится порядок печати в будущем
        pytest — красным станет ЭТО утверждение, и тогда таблица приоритетов будет
        написана по замеру, а не на всякий случай."""
        body = (
            "import unittest\n\n\n"
            "class Scene(unittest.TestCase):\n"
            "    def test_scene(self):\n"
            "        with self.subTest(n=1):\n"
            "            self.assertEqual(1, 2)\n"
            "        self.assertEqual(3, 4)\n")
        base, _ = self._verdicts(body, "both_sides")
        self.assertEqual([v for k, v in base.items() if k != "__passed__"], ["FAILED"],
                         f"исход ВНЕШНЕГО падения обязан победить подтестовый: {base}")

    def test_the_message_form_of_the_suffix_is_parsed_too(self):
        """ЗВЕНО: форма `SUBFAILED[метка с пробелом]` — вторая из двух, и у прибора
        бомб СВОЯ копия регекса. Без этой сцены квадратная форма была бы проверена
        только у прибора дельты, а второй копии хватило бы круглой."""
        body = (
            "import unittest\n\n\n"
            "class Scene(unittest.TestCase):\n"
            "    def test_scene(self):\n"
            "        with self.subTest('метка с пробелом'):\n"
            "            self.assertEqual(1, 2)\n")
        base, _ = self._verdicts(body, "msg_form")
        self.assertEqual(
            [(k.rsplit("::", 1)[-1], v) for k, v in base.items() if k != "__passed__"],
            [("test_scene", "SUBFAILED")],
            f"имя обязано быть взято ПОСЛЕ квадратного суффикса с пробелом: {base}")


#: Пропуск, который происходит ПОКА прогон короткий: при задержке 0 тест пропущен, при
#: 95 мин — проходит. Якорь на импорте тут не дефект, а МЕХАНИЗМ сцены: он и есть то,
#: чем длительность прогона меняет вердикт.
_SKIP_WHEN_EARLY = '''
import unittest
from spa_core.tests._freshness import now_utc

NOW = now_utc()                      # ЯКОРЬ НА ИМПОРТЕ


class Scene(unittest.TestCase):
    def test_scene(self):
        if (now_utc() - NOW).total_seconds() < 60:
            raise unittest.SkipTest("прогон короткий")
        self.assertTrue(True)
'''

#: Обратный: при задержке 0 проходит, при 95 мин пропускается. Вместе с предыдущим даёт
#: сцену, на которой прибор молчал: пропусков по ОДНОМУ с каждой стороны, а тесты РАЗНЫЕ.
_SKIP_WHEN_LATE = _SKIP_WHEN_EARLY.replace(
    'if (now_utc() - NOW).total_seconds() < 60:\n'
    '            raise unittest.SkipTest("прогон короткий")',
    'if (now_utc() - NOW).total_seconds() >= 60:\n'
    '            raise unittest.SkipTest("прогон длинный")')

#: Пропуск, которому задержка безразлична: обязан остаться чистым на ОБЕИХ сторонах.
_SKIP_ALWAYS = '''
import unittest


class Scene(unittest.TestCase):
    def test_scene(self):
        raise unittest.SkipTest("пропуск не зависит от длительности прогона")
'''

#: Два РАЗНЫХ теста, которых короткая сводка сводит в ОДНО место. Замер #952 на pytest
#: 9.0.3: `raise unittest.SkipTest` из простой функции печатается как
#: `SKIPPED [n] …/_pytest/unittest.py:502: причина` — место лежит ВНУТРИ pytest и у обоих
#: тестов одинаково. Поэтому ключом не годится ни счётчик, ни «файл:строка».
_SKIPS_AT_ONE_PLACE = '''
import unittest


def test_first():
    raise unittest.SkipTest("первая причина")


def test_second():
    raise unittest.SkipTest("вторая причина")
'''


class TheInstrumentNamesWhichTestWasSkipped(unittest.TestCase):
    """Пропуск обязан иметь ЛИЧНОСТЬ, а не номер. Класс найден циклом #952 (заказ G827 п. 1).

    До правки ключом вердикта пропущенного теста становился СЧЁТЧИК из короткой сводки
    (`SKIPPED [1] место: причина`): короткая сводка имён пропущенных тестов не печатает
    ВООБЩЕ и сводит их в группы «место + причина», а `[1]` — размер группы. Сравнение
    «было ↔ стало» по такому ключу работало только пока пропуск был один и тот же: обмен
    двух пропусков местами давал РАВЕНСТВО, и прибор печатал «Бомб нет» при двух
    сменившихся вердиктах. Ошибка шла в сторону САМОУСПОКОЕНИЯ, и слепым был ровно тот
    переход (`passed → skipped`), на котором стои́т урок #465.

    Замер цены до правки (живое население, 30 файлов, задержка 0): исходов кроме
    `__passed__` = 741 НЕ БЫЛО НИ ОДНОГО, то есть сегодня слепота ЛАТЕНТНА и стоила
    НОЛЬ находок. Платили не за сегодняшнюю находку, а за то, что ответ «чисто»
    сейчас держится на отсутствии пропусков в населении, а не на умении прибора их
    различать."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix="spa_anchor_skip_"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _sides(self, files: list[str]):
        return iab.outcomes(files, 0.0, ROOT), iab.outcomes(files, LAG_MIN, ROOT)

    def test_two_skips_swapping_places_are_both_found(self):
        """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ класса: до правки прибор здесь говорил «Бомб нет»."""
        files = [_scene(self.tmp, "skip_when_early", _SKIP_WHEN_EARLY),
                 _scene(self.tmp, "skip_when_late", _SKIP_WHEN_LATE)]
        base, aged = self._sides(files)
        # Сцена обязана быть ИМЕННО такой, иначе она не воспроизводит класс: по одному
        # пропуску с каждой стороны и «1 passed» у обеих — окольной улики нет.
        self.assertEqual(
            ([v for k, v in base.items() if k != "__passed__"],
             [v for k, v in aged.items() if k != "__passed__"],
             base.get("__passed__"), aged.get("__passed__")),
            (["SKIPPED"], ["SKIPPED"], "1", "1"),
            f"сцена сломана, а не класс воспроизведён: {base} / {aged}")
        # СЕРДЦЕ класса, и проверяется ДО обращения к сравнению: на чистом origin/main
        # ключами обеих сторон был счётчик `[1]`, то есть они СОВПАДАЛИ — и сравнение по
        # ним давало равенство при двух сменившихся вердиктах. Утверждение стои́т здесь
        # нарочно: упади оно позже, падение читалось бы как «нет такой функции», а не
        # как предмет класса.
        self.assertNotEqual([k for k in base if k != "__passed__"],
                            [k for k in aged if k != "__passed__"],
                            f"ключи пропусков у двух сторон СОВПАЛИ — значит ключом стал "
                            f"не тест, а номер, и сравнение слепо: {base} / {aged}")
        changed = iab.changed_verdicts(base, aged)
        self.assertEqual(sorted((was, now) for _, was, now in changed),
                         [("SKIPPED", "passed"), ("passed", "SKIPPED")],
                         f"прибор обязан назвать ОБА перехода, а не равенство: {changed}")
        names = [t for t, _, _ in changed]
        self.assertTrue(all(t.endswith("Scene::test_scene") for t in names),
                        f"переход обязан быть назван ИМЕНЕМ теста, не номером: {names}")
        self.assertTrue(all("skip_when_early" in t for t in names[:1])
                        and any("skip_when_late" in t for t in names),
                        f"имена обязаны различать два РАЗНЫХ теста: {names}")

    def test_a_skip_that_ignores_the_lag_is_not_a_bomb(self):
        """ОБРАТНАЯ СТОРОНА: без неё правка читалась бы как «любой пропуск подозрителен».

        И отдельно проверено, что равенство здесь — от СОВПАДЕНИЯ, а не от слепоты:
        пропуск ВИДЕН обеим сторонам поимённо."""
        files = [_scene(self.tmp, "skip_always", _SKIP_ALWAYS)]
        base, aged = self._sides(files)
        self.assertEqual(iab.changed_verdicts(base, aged), [],
                         f"задержке этот пропуск безразличен — находки быть не вправе: "
                         f"{base} / {aged}")
        self.assertEqual(([v for k, v in base.items() if k != "__passed__"],
                          [v for k, v in aged.items() if k != "__passed__"]),
                         (["SKIPPED"], ["SKIPPED"]),
                         f"пропуск обязан быть ВИДЕН обеим сторонам, иначе равенство "
                         f"получено слепотой: {base} / {aged}")

    def test_two_tests_the_summary_puts_at_one_place_get_two_keys(self):
        """ЗВЕНО: личностью не является и «файл:строка».

        Замер #952: оба этих пропуска короткая сводка печатает с местом ВНУТРИ pytest
        (`_pytest/unittest.py:502`), то есть ОДИНАКОВЫМ. Ключ по месту склеил бы их, и
        подмена одного другим снова стала бы равенством — поэтому дверь к пропускам
        читает junit, а не сводку."""
        files = [_scene(self.tmp, "one_place", _SKIPS_AT_ONE_PLACE)]
        base, _ = self._sides(files)
        keys = sorted(k for k in base if k != "__passed__")
        self.assertEqual([k.rsplit("::", 1)[-1] for k in keys], ["test_first", "test_second"],
                         f"два разных пропуска обязаны получить два ключа: {base}")

    def test_the_summary_reader_no_longer_claims_skips(self):
        """ЗВЕНО: дверь к пропускам ОДНА.

        Останься `SKIPPED` в группе `_OUTCOME`, счётчик `[1]` снова встал бы ключом
        РЯДОМ с именем из junit — и сравнение опять зависело бы от порядка."""
        line = "SKIPPED [1] spa_core/tests/test_x.py:12: причина\n"
        self.assertEqual(iab._OUTCOME.findall(line), [],
                         "читатель короткой сводки не вправе объявлять пропуски своими")

    def test_a_missing_junit_report_is_a_refusal_not_an_empty_dict(self):
        """Третий исход (инв. #17): пустой словарь был бы неотличим от «пропусков нет»."""
        with self.assertRaises(iab.NotMeasured) as ctx:
            iab._skips_from_junit(self.tmp / "отчёта-нет.xml", 0.0)
        self.assertIn("junit", str(ctx.exception).lower())

    def test_an_unparsable_junit_report_is_a_refusal(self):
        bad = self.tmp / "bad.xml"
        bad.write_text("<testsuite", encoding="utf-8")
        with self.assertRaises(iab.NotMeasured):
            iab._skips_from_junit(bad, 0.0)


class TheInstrumentRefusesInsteadOfGuessing(unittest.TestCase):
    """Инв. #17: не измерено — отдельный исход с названной причиной, а не «чисто»."""

    def test_an_empty_population_is_a_refusal_not_a_clean_answer(self):
        import tempfile
        empty = Path(tempfile.mkdtemp(prefix="spa_anchor_empty_"))
        with self.assertRaises(iab.NotMeasured) as ctx:
            iab.bombs(LAG_MIN, root=empty)
        self.assertIn("население", str(ctx.exception))

    def test_an_unparsable_test_file_is_a_refusal(self):
        import tempfile
        broken = Path(tempfile.mkdtemp(prefix="spa_anchor_broken_"))
        (broken / "spa_core" / "tests").mkdir(parents=True)
        (broken / "spa_core" / "tests" / "test_broken.py").write_text(
            "def f(:\n", encoding="utf-8")
        with self.assertRaises(iab.NotMeasured) as ctx:
            iab.anchored_at_import(broken)
        self.assertIn("не разобраны", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
