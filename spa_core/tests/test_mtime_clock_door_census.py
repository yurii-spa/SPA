#!/usr/bin/env python3
"""Батарея прибора класса «половина инъекции часов: отметка из ``mtime`` файла».

Предмет — авария 24.11.2026 (ADR-1086, цикл #1232): сцена
``test_mission_control_contract.py`` пиновала КАЖДУЮ свою текстовую отметку от якоря
``NOW``, а отметку архива резерва модель берёт из ``mtime`` файла — её сцена оставляла
стенным часам, и девять проверок покраснели на ``main`` при неизменных байтах.

Контроль у прибора — В ОБЕ СТОРОНЫ и на НАСТОЯЩЕМ приборе, а не рядом с ним:

* сцена в ФОРМЕ аварии (отметка не закреплена) ⇒ прибор обязан назвать её ЧЛЕНОМ;
* та же сцена с закреплённой отметкой (``os.utime`` явными временами — дословно
  лечение ADR-1086) ⇒ прибор обязан промолчать. Порви это звено, и прибор станет
  называть находкой ПОЧИНЕННЫЙ код;
* форма аварии НАЗВАНА по БАЙТАМ: дверь пина обязана ответить «пина нет» на
  до-ADR-1086 написании и «пин есть» на после-;
* предпосылки прибора (одноразовое дерево · канарейка прозрачности) дают ТРЕТИЙ
  исход с названной причиной, а не ноль и не скип.

Освобождения по причине `injected-clock` этому файлу НЕ НУЖНО, и дословная пометка здесь
НЕ НАПИСАНА намеренно: сторож притязания (цикл #477) читает её в ЛЮБОЙ строке файла,
включая прозу, — замер #1233 покрасил этот файл ровно так. Своих литеральных дат файл не
держит: отметки сцен он СТРОИТ от момента прогона, а предмет замера есть РАЗРЫВ между
якорем и файловой системой, а не конкретная дата.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from spa_core.tests import _mtime_clock_door as door

REPO = Path(__file__).resolve().parents[2]

#: Сцена в ФОРМЕ аварии 24.11: якорь уходит ВХОДОМ в читателя, а отметка файла —
#: от стенных часов. Якорь относительный намеренно: предмет замера есть РАЗРЫВ
#: «якорь ↔ файловая система», и литеральная дата сделала бы сцену красной на базе,
#: то есть замер мерил бы не тот вопрос (дословно урок § «Время в тестах», приём №2).
_SCENE = '''
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

NOW = datetime.now(timezone.utc) - timedelta(minutes=5)


def age_minutes(p, *, now):
    """Читатель отметки: ОДНА сторона сравнения приходит из файловой системы."""
    stamped = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
    return abs((now - stamped).total_seconds()) / 60.0


def test_archive_is_fresh(tmp_path):
    arch = tmp_path / "spa_state.tar.gz"
    arch.write_text("x")
{PIN}
    assert age_minutes(arch, now=NOW) < 1800.0
'''

_PIN_LINE = ('    at = (NOW - timedelta(minutes=10)).timestamp()\n'
             '    os.utime(arch, (at, at))')


def _scene_tree(root: Path, *, pinned: bool) -> list[str]:
    """Выложить одноразовое дерево с одной сценой. Возвращает пути для прибора."""
    (root / "spa_core" / "tests").mkdir(parents=True, exist_ok=True)
    rel = "spa_core/tests/test_scene_under_measure.py"
    body = _SCENE.replace("{PIN}", _PIN_LINE if pinned else "")
    (root / rel).write_text(body, encoding="utf-8")
    return [rel]


class TheProberSeesTheRealAccident(unittest.TestCase):
    """Контроль в обе стороны НА ПРИБОРЕ: форма аварии против её лечения."""

    def _differential(self, *, pinned: bool) -> dict:
        with tempfile.TemporaryDirectory(prefix="spa_mtime_ctl_") as tmp:
            tree = Path(tmp) / "tree"
            tree.mkdir()
            files = _scene_tree(tree, pinned=pinned)
            work = Path(tmp) / "work"
            work.mkdir()
            return door.differential(tree, files, shift_days=-400.0,
                                     workdir=work, timeout_s=900)

    def test_an_unpinned_stamp_is_a_member_of_the_class(self):
        doc = self._differential(pinned=False)
        self.assertEqual(doc["unmeasured"], [],
                         f"предпосылки прибора не обеспечены: {doc['unmeasured']}")
        members = [n for n, v in doc["verdict"].items() if v == door.MEMBER]
        self.assertEqual(len(members), 1,
                         f"форма аварии 24.11 не названа членом: {doc['verdict']}")
        base, shifted = doc["candidates"][members[0]]
        self.assertEqual(base, "PASSED")
        self.assertEqual(shifted, "FAILED")

    def test_both_directions_of_the_shift_detect_the_accident_form(self):
        """Направление сдвига — ВХОД, и ОДНОГО направления классу не хватает.

        Замер #1233 на НАСТОЯЩЕЙ сцене ADR-1086 со снятым пином: НАЗАД она даёт
        4 смены вердикта (`FAILED → PASSED` — сдвиг её ЛЕЧИТ, потому что в своей
        аварийной форме она красна уже на базе), а ВПЕРЁД — НОЛЬ. То есть класс
        есть ОБЪЕДИНЕНИЕ двух прогонов, и прогон в одну сторону отвечает на СВОЙ
        вопрос, а не на нужный.

        Здесь это закреплено на сцене, которая зелена на базе: она обязана быть
        названа членом в ОБА направления.
        """
        for shift in (-400.0, 400.0):
            with tempfile.TemporaryDirectory(prefix="spa_mtime_dir_") as tmp:
                tree = Path(tmp) / "tree"
                tree.mkdir()
                files = _scene_tree(tree, pinned=False)
                work = Path(tmp) / "work"
                work.mkdir()
                doc = door.differential(tree, files, shift_days=shift,
                                        workdir=work, timeout_s=900)
            self.assertEqual(doc["unmeasured"], [], f"сдвиг {shift}: {doc['unmeasured']}")
            members = [n for n, v in doc["verdict"].items() if v == door.MEMBER]
            self.assertEqual(len(members), 1,
                             f"сдвиг {shift} не назвал форму аварии членом: "
                             f"{doc['verdict']}")

    def test_the_cure_of_adr_1086_is_not_called_a_finding(self):
        doc = self._differential(pinned=True)
        self.assertEqual(doc["unmeasured"], [],
                         f"предпосылки прибора не обеспечены: {doc['unmeasured']}")
        self.assertEqual(doc["candidates"], {},
                         "закреплённая отметка названа находкой — прибор обвиняет "
                         "ПОЧИНЕННЫЙ код")
        self.assertEqual(doc["verdict"], {})


class ThePinDoorNamesTheAccidentByBytes(unittest.TestCase):
    """Дверь пина отвечает о ДО- и ПОСЛЕ- написании ADR-1086 ПРОТИВОПОЛОЖНО."""

    BEFORE = "arch = tmp_path / 'a.tar.gz'\narch.write_text('x')\n"
    AFTER = ("arch = tmp_path / 'a.tar.gz'\narch.write_text('x')\n"
             "os.utime(arch, (at, at))\n")

    def test_the_two_writings_get_opposite_answers(self):
        self.assertEqual(door.pins_mtime(ast.parse(self.BEFORE)), [])
        self.assertTrue(door.pins_mtime(ast.parse(self.AFTER)))

    def test_a_wall_clock_stamp_is_not_a_pin(self):
        """``os.utime(p, None)`` штампует СТЕННЫМИ часами — это предмет, не выход."""
        self.assertEqual(door.pins_mtime(ast.parse("os.utime(p, None)\n")), [])
        self.assertEqual(door.pins_mtime(ast.parse("os.utime(p)\n")), [])
        self.assertEqual(door.pins_mtime(ast.parse("os.utime(p, times=None)\n")), [])
        self.assertTrue(door.pins_mtime(ast.parse("os.utime(p, ns=(1, 1))\n")))


class NoiseIsAThirdOutcomeNotAFinding(unittest.TestCase):
    """Смена, не вернувшаяся на третьей ступени, — НЕ ИЗМЕРЕНО, а не член класса.

    Дыра ПОКРЫТИЯ, найденная выжившей мутацией M6 замера #1233: ни одна сцена не
    давала исхода `noisy`, поэтому снятие третьей ступени ничего не ломало.
    """

    #: Сцена считает СВОИ прогоны в файле рядом с собой и краснеет с ВТОРОГО.
    #: База (прогон 1) зелена, сдвинутый (2) красен, перемер (3) тоже красен ⇒
    #: вердикт сменился и НЕ ВЕРНУЛСЯ. Календарь здесь не при чём — и это
    #: ровно то, что обязан сказать прибор.
    FLAKY = (
        "from pathlib import Path\n"
        "\n"
        "COUNTER = Path(__file__).with_name('runs.txt')\n"
        "\n"
        "\n"
        "def test_green_only_on_the_first_run():\n"
        "    n = int(COUNTER.read_text()) if COUNTER.exists() else 0\n"
        "    COUNTER.write_text(str(n + 1))\n"
        "    assert n == 0\n"
    )

    def test_a_change_that_does_not_return_is_named_noisy(self):
        with tempfile.TemporaryDirectory(prefix="spa_mtime_noise_") as tmp:
            tree = Path(tmp) / "tree"
            (tree / "spa_core" / "tests").mkdir(parents=True)
            rel = "spa_core/tests/test_flaky_scene.py"
            (tree / rel).write_text(self.FLAKY, encoding="utf-8")
            work = Path(tmp) / "work"
            work.mkdir()
            doc = door.differential(tree, [rel], shift_days=-400.0,
                                    workdir=work, timeout_s=900)
        self.assertEqual(doc["unmeasured"], [], f"предпосылки: {doc['unmeasured']}")
        self.assertTrue(doc["candidates"], "сцена не сменила вердикт вовсе")
        self.assertEqual(set(doc["verdict"].values()), {door.NOISY},
                         f"шум объявлен членом класса: {doc['verdict']}")


class ThePreconditionsAreAThirdOutcome(unittest.TestCase):
    """Сломанная предпосылка — НЕ ИЗМЕРЕНО с названной причиной, а не ноль."""

    def _cli(self, argv: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "spa_core.tests._mtime_clock_door", *argv],
            cwd=str(REPO), capture_output=True, text=True, timeout=900,
            env={**os.environ, "SPA_ENV": "ci"})

    def test_differential_without_a_disposable_tree_refuses(self):
        p = self._cli(["--differential"])
        self.assertEqual(p.returncode, door.UNMEASURED_CODE)
        self.assertIn("--run-root", p.stderr)

    def test_a_named_tree_that_is_not_a_repo_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._cli(["--differential", "--run-root", tmp])
        self.assertEqual(p.returncode, door.UNMEASURED_CODE)
        self.assertIn("НЕ ИЗМЕРЕНО", p.stderr)

    def test_an_empty_surface_is_unmeasured_not_an_empty_class(self):
        with tempfile.TemporaryDirectory(prefix="spa_mtime_empty_") as tmp:
            work = Path(tmp) / "w"
            work.mkdir()
            doc = door.differential(Path(tmp), [], shift_days=-400.0,
                                    workdir=work, timeout_s=60)
        self.assertTrue(doc["unmeasured"])
        self.assertEqual(doc["unmeasured"][0]["what"], "поверхность")

    def test_a_broken_canary_withholds_the_answer_about_the_class(self):
        """Канарейка не сошлась ⇒ кандидаты печатаются КАК КАНДИДАТЫ (урок ADR-898)."""
        with tempfile.TemporaryDirectory(prefix="spa_mtime_canary_") as tmp:
            tree = Path(tmp) / "tree"
            tree.mkdir()
            files = _scene_tree(tree, pinned=False)
            work = Path(tmp) / "work"
            work.mkdir()
            # Порванное звено ровно одно: канарейка плагина объявляется НЕ СОШЕДШЕЙСЯ.
            real = door.plugin_source
            door.plugin_source = lambda: real() + (
                "\nimport json as _j, os as _o\n"
                "_f = _o.environ.get('SPA_MTIME_CANARY_FILE', '')\n"
                "if _f:\n"
                "    open(_f, 'w').write(_j.dumps({'ok': False,"
                " 'error': 'контроль: канарейка объявлена сломанной'}))\n")
            try:
                doc = door.differential(tree, files, shift_days=-400.0,
                                        workdir=work, timeout_s=900)
            finally:
                door.plugin_source = real
        self.assertTrue(doc["unmeasured"],
                        "сломанная канарейка не остановила ответ о классе")
        self.assertEqual(doc["unmeasured"][0]["what"], "канарейка прозрачности")
        self.assertTrue(doc["candidates"], "кандидаты обязаны быть НАЗВАНЫ поимённо")


class TheSurfaceIsMeasuredNotAsserted(unittest.TestCase):
    """Поверхность: нечитаемое поимённо, предмет уже или верхней границы."""

    def test_an_unreadable_file_is_named_unmeasured_not_skipped(self):
        with tempfile.TemporaryDirectory(prefix="spa_mtime_surface_") as tmp:
            root = Path(tmp)
            (root / "spa_core" / "tests").mkdir(parents=True)
            # Пометка собирается ИЗ ЧАСТЕЙ намеренно: сторож притязания читает
            # её в любой строке ЭТОГО файла, включая строковый литерал сцены, и
            # собранная целиком она выписала бы претензию МНЕ (замер #1233).
            marker = "# FROZEN-" + "DATE-OK: injected-clock"
            (root / "spa_core" / "tests" / "test_broken.py").write_text(
                f"{marker}\ndef f(:\n", encoding="utf-8")
            verdicts = door.measure_surface(root, readers=set())
        broken = [v for v in verdicts if v.path.endswith("test_broken.py")]
        self.assertEqual(len(broken), 1)
        self.assertEqual(broken[0].surface, door.UNMEASURED)
        self.assertIn("не разобран", broken[0].reason)

    def test_a_file_that_cannot_be_READ_is_named_unmeasured_too(self):
        """Дыра ПОКРЫТИЯ, найденная выжившей мутацией #11 замера #1233.

        Прежний тест выше рвал ветку РАЗБОРА (`ast.parse` → `SyntaxError`), а
        ветку ЧТЕНИЯ (`read_text` → `UnicodeDecodeError`) не подавал НИКТО:
        мутация «нечитаемый файл глотается молча» ВЫЖИЛА. Выжившую мутацию
        записывают и закрывают сценой, а не замазывают.
        """
        with tempfile.TemporaryDirectory(prefix="spa_mtime_unread_") as tmp:
            root = Path(tmp)
            (root / "spa_core" / "tests").mkdir(parents=True)
            # Байты, которые не декодируются как UTF-8: падает ЧТЕНИЕ, не разбор.
            (root / "spa_core" / "tests" / "test_undecodable.py").write_bytes(
                b"\xff\xfe# FROZEN-" + b"DATE-OK: injected-clock\n")
            verdicts = door.measure_surface(root, readers=set())
        rows = [v for v in verdicts if v.path.endswith("test_undecodable.py")]
        self.assertEqual(len(rows), 1, "нечитаемый файл пропал из вердиктов вовсе")
        self.assertEqual(rows[0].surface, door.UNMEASURED)
        self.assertIn("файл не прочитан", rows[0].reason)

    def test_a_missing_directory_is_unmeasured_with_a_named_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            verdicts = door.measure_surface(Path(tmp), readers=set())
        self.assertEqual([v.surface for v in verdicts], [door.UNMEASURED])
        self.assertIn("каталог не найден", verdicts[0].reason)

    def test_the_subject_is_narrower_than_the_upper_bound(self):
        """Предмет ⊆ «претензия + запись»: ось хопа СУЖАЕТ, а не добавляет."""
        verdicts = door.measure_surface(REPO)
        kinds = {}
        for v in verdicts:
            kinds[v.surface] = kinds.get(v.surface, 0) + 1
        self.assertEqual(kinds.get(door.UNMEASURED, 0), 0,
                         "поверхность прочитана не целиком")
        self.assertGreater(kinds.get(door.IN_SURFACE, 0), 0)
        self.assertGreater(kinds.get(door.NO_READER, 0), 0,
                          "ось одного хопа не отсекла НИ ОДНОГО файла — "
                          "значит она ничего не измеряет")

    def test_the_known_member_of_the_class_is_inside_the_subject(self):
        """Форма, потерявшая ИЗВЕСТНОГО члена, класс не сужает, а ПОДМЕНЯЕТ.

        Дословный урок ADR-1074: мерка «тест САМ перечисляет каталог» находила 1 из 3
        известных членов и была ОПРОВЕРГНУТА. Здесь известный член один — сцена
        ADR-1086, и выпади она из предмета, число предмета было бы ответом о
        поверхности, которой прибор не видел.
        """
        verdicts = {v.path: v for v in door.measure_surface(REPO)}
        known = "spa_core/tests/test_mission_control_contract.py"
        self.assertIn(known, verdicts)
        self.assertEqual(verdicts[known].surface, door.IN_SURFACE,
                         "известный член класса выпал из предмета")
        self.assertTrue(verdicts[known].reader_hits,
                        "у известного члена не назван ни один читатель отметки")

    def test_the_claim_door_is_CALLED_not_merely_imported(self):
        """Мутация M12 замера #1233 ВЫЖИЛА: ввоз остался, а ЗОВ был подменён.

        «Ввезён» ≠ «ЗОВЁТ» — дословный урок ADR-1028. Поэтому меряется AST:
        дверь обязана быть ВЫЗВАНА, и своей копии разбора претензии (поиск
        подстроки `injected-clock` в тексте) у прибора быть не должно.
        """
        src = (REPO / "spa_core/tests/_mtime_clock_door.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        called = {
            (n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", ""))
            for n in ast.walk(tree) if isinstance(n, ast.Call)
        }
        self.assertIn("claims_injected_clock", called,
                      "дверь притязания ввезена, но НЕ ЗВАНА")
        own_copy = [
            n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Compare)
            and any(isinstance(op, (ast.In, ast.NotIn)) for op in n.ops)
            and isinstance(n.left, ast.Constant)
            and isinstance(n.left.value, str)
            and "injected-clock" in n.left.value
        ]
        self.assertEqual(own_copy, [],
                         f"своя копия разбора претензии в строках {own_copy}")


class TheOutcomeParserDistinguishesSkipped(unittest.TestCase):
    """Урок #465: ушедший в ``skipped`` тест не краснеет и не проходит — он ИСЧЕЗАЕТ."""

    def test_skipped_is_its_own_verdict(self):
        out = door._parse_outcomes(
            "spa_core/tests/t.py::a PASSED [ 50%]\n"
            "spa_core/tests/t.py::b SKIPPED [100%]\n"
            "spa_core/tests/t.py::c FAILED [100%]\n")
        self.assertEqual(out["spa_core/tests/t.py::b"], "SKIPPED")
        self.assertEqual(len(out), 3)

    def test_a_vanished_name_is_a_change_of_verdict(self):
        """Имя, пропавшее из прогона, сравнивается с ``ABSENT``, а не отбрасывается."""
        src = (REPO / "spa_core/tests/_mtime_clock_door.py").read_text(encoding="utf-8")
        self.assertIn('base.get(n, "ABSENT") != shifted.get(n, "ABSENT")', src)
        self.assertIn("set(base) | set(shifted)", src)


class ThePerturbationHasTwoSingleDoors(unittest.TestCase):
    """Возмущение идёт ЧЕРЕЗ ``os.utime`` и ``os.stat``, и тип сохраняется."""

    def test_the_canary_of_transparency_passes_on_a_real_run(self):
        with tempfile.TemporaryDirectory(prefix="spa_mtime_type_") as tmp:
            work = Path(tmp) / "work"
            work.mkdir()
            plugin = door.materialise_plugin(work)
            canary = work / "canary.json"
            probe = work / "probe.py"
            probe.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
            env = {**os.environ,
                   "SPA_MTIME_SHIFT_DAYS": "-400",
                   "SPA_MTIME_SHIFT_ROOTS": os.path.realpath(tempfile.gettempdir()),
                   "SPA_MTIME_CANARY_FILE": str(canary),
                   "PYTHONPATH": str(work)}
            subprocess.run([sys.executable, "-c",
                            f"import {plugin.stem}"],
                           cwd=str(work), env=env, capture_output=True, text=True,
                           timeout=120)
            doc = json.loads(canary.read_text(encoding="utf-8"))
        self.assertTrue(doc.get("ok"), f"канарейка прозрачности не сошлась: {doc}")
        for name in ("type_preserved", "free_shifted", "pinned_untouched",
                     "getmtime_follows", "pathlib_follows"):
            self.assertTrue(doc["checks"][name], f"звено канарейки: {name}")

    def test_the_door_does_not_reach_the_OS_through_itself(self):
        """Дефект МОЕГО прибора, найденный замером #1233, а не разбором.

        Первая редакция считала ключ пути `os.path.realpath`, а он идёт через
        `os.lstat` — то есть через УЖЕ ПОДМЕНЁННУЮ дверь. Обёртка уходила в себя,
        и тривиальная сцена (0,4 с после починки) держалась ВОСЕМЬ МИНУТ, выглядя
        зависанием, а не дефектом — дословно урок § окна мутационного прибора, п. 8:
        «работает» и «умер» обязаны выглядеть ПО-РАЗНОМУ.

        Контроль — по ИСХОДУ: корни и ключ считаются дверью, снятой ДО подмены, и у
        обёртки есть сторож повторного входа. Порви любое звено — и контроль в обе
        сторону (`TheProberSeesTheRealAccident`) перестанет завершаться вовсе.
        """
        src = door.plugin_source()
        self.assertIn("_orig_realpath = os.path.realpath", src)
        self.assertIn("_orig_realpath(p)", src)
        self.assertIn("_BUSY", src)
        key = src.split("def _key(path)", 1)[1].split("def ", 1)[0]
        self.assertIn("os.path.abspath", key)
        self.assertNotIn("realpath", key,
                         "ключ пути считается дверью, которую прибор сам подменил")

    def test_a_file_OUTSIDE_the_named_root_is_not_shifted(self):
        """Контроль по ИСХОДУ, а не по исходнику (мутация M3 замера #1233 ВЫЖИЛА).

        Прежняя редакция смотрела в текст плагина и пропускала подмену
        `_under(k) → True`. Теперь корень — ВХОД: сцена, чей файл лежит ВНЕ
        названного корня, обязана остаться СТАБИЛЬНОЙ, а та же сцена с корнем,
        её накрывающим, — стать ЧЛЕНОМ. Два прогона, отличающиеся РОВНО корнем.
        """
        with tempfile.TemporaryDirectory(prefix="spa_mtime_root_") as tmp:
            tree = Path(tmp) / "tree"
            tree.mkdir()
            files = _scene_tree(tree, pinned=False)
            outside = Path(tmp) / "elsewhere"
            outside.mkdir()
            got = {}
            for label, roots in (("вне корня", (str(outside),)),
                                 ("внутри корня", (str(tmp),))):
                work = Path(tmp) / f"w_{len(got)}"
                work.mkdir()
                doc = door.differential(tree, files, shift_days=-400.0,
                                        workdir=work, timeout_s=900,
                                        shift_roots=roots)
                self.assertEqual(doc["unmeasured"], [], f"{label}: {doc['unmeasured']}")
                got[label] = sorted(doc["candidates"])
        self.assertEqual(got["вне корня"], [],
                         "сцена вне НАЗВАННОГО корня всё равно сдвинута — корень "
                         "не ограничивает возмущение")
        self.assertEqual(len(got["внутри корня"]), 1,
                         "сцена ВНУТРИ корня не сдвинута — возмущение не доходит")

    def test_the_direction_of_the_shift_is_backwards_by_default(self):
        """Вперёд — вторая ось (ADR-1085), и этим прогоном она НЕ измеряется."""
        code = door.main.__doc__ or ""
        _ = code
        p = subprocess.run(
            [sys.executable, "-m", "spa_core.tests._mtime_clock_door", "--help"],
            cwd=str(REPO), capture_output=True, text=True, timeout=120)
        self.assertIn("-400", p.stdout)


class TheProberOnlyReads(unittest.TestCase):
    """ADVISORY: ни одного файла набора прибор не правит."""

    def test_the_surface_pass_does_not_touch_the_tree(self):
        target = REPO / "spa_core/tests/test_mission_control_contract.py"
        before = (target.stat().st_mtime_ns, target.stat().st_size)
        door.measure_surface(REPO)
        time.sleep(0.01)
        after = (target.stat().st_mtime_ns, target.stat().st_size)
        self.assertEqual(before, after)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
