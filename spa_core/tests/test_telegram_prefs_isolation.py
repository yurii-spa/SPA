"""Страж класса «прогон тестов пишет в ЖИВОЕ состояние» — настройки Телеграм-бота.

Авария (обнаружена 2026-08-08, следы датированы 26.06). В живом
``data/telegram/user_prefs.json`` лежали записи для chat_id ``424242`` и ``999999`` —
это не люди, а константы ``OWNER`` и ``STRANGER`` из ``test_telegram_bot_menus.py`` /
``test_owner_decisions_wiring.py``. У ``424242`` вдобавок проставлен ``mute_until``:
то есть прогон тестов не просто намусорил, а ЗАГЛУШИЛ чат в живых настройках.

Тот же класс уже стоил дорого в другом модуле: ``push_policy`` резолвил ``data/``
статически, и прогон тестов мог заглушить настоящую тревогу kill-switch. Лечение там —
``alert_actions._state_path``: под pytest путь уходит во временный файл САМ, а не по
памяти автора теста. Здесь — тот же приём для ``prefs.PREFS_FILE``.

Каждый тест ниже — **положительный контроль**: на неисправленном модуле
(``path = path or PREFS_FILE``) он краснеет, потому что воспроизводит саму аварию —
запись без указания пути создаёт файл по умолчанию дерева. Проверка, никогда не
видевшая настоящей поломки, — украшение (правило ``.claude/rules/deployment.md``).

Контроль в обратную сторону тоже есть: вне pytest умолчание обязано остаться ЖИВЫМ
файлом (иначе бот в проде перестал бы помнить настройки) — это меряется в отдельном
процессе без ``PYTEST_CURRENT_TEST``.

Только stdlib, без сети, без Keychain, живого дерева НЕ касается.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from spa_core.tests import _child_pytest
from spa_core.telegram import prefs as prefs_store

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Те самые chat_id из тест-файлов, которыми была засеяна живая карта настроек.
OWNER_IN_TESTS = "424242"
STRANGER_IN_TESTS = "999999"


def _fake_tree(root: Path) -> Path:
    """Путь ``data/telegram/user_prefs.json`` внутри поддельного дерева репозитория."""
    return root / "data" / "telegram" / "user_prefs.json"


class TestPytestNeverWritesTheTreeDefault(unittest.TestCase):
    """Под pytest запись без явного пути НЕ создаёт файл по умолчанию дерева."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        # Подделываем дерево целиком: и BASE_DIR, и PREFS_FILE — так пара остаётся
        # «умолчанием этого дерева», а не осознанным перенаправлением.
        self._orig_base = prefs_store.BASE_DIR
        self._orig_file = prefs_store.PREFS_FILE
        prefs_store.BASE_DIR = self.root
        prefs_store.PREFS_FILE = _fake_tree(self.root)
        # Общий временный файл живёт между тестами — начинаем с чистого листа.
        if prefs_store.PYTEST_PREFS_FILE.exists():
            prefs_store.PYTEST_PREFS_FILE.unlink()
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        prefs_store.BASE_DIR = self._orig_base
        prefs_store.PREFS_FILE = self._orig_file
        if prefs_store.PYTEST_PREFS_FILE.exists():
            prefs_store.PYTEST_PREFS_FILE.unlink()

    def test_language_write_does_not_create_the_tree_default(self) -> None:
        """Ровно та авария: `set_pref` без пути осел бы в живых настройках."""
        prefs_store.set_pref(OWNER_IN_TESTS, "lang", "en")

        self.assertFalse(
            _fake_tree(self.root).exists(),
            "прогон под pytest создал файл настроек по умолчанию дерева — "
            "ровно так в живой карте появились chat_id 424242/999999",
        )

    def test_mute_write_does_not_create_the_tree_default(self) -> None:
        """Самое дорогое поле: заглушка чата не должна уезжать в живые настройки."""
        prefs_store.set_pref(OWNER_IN_TESTS, "mute_until", 4_102_444_800)

        self.assertFalse(
            _fake_tree(self.root).exists(),
            "прогон под pytest записал mute_until в файл по умолчанию дерева — "
            "именно так тест заглушил чат в живых настройках",
        )

    def test_stranger_write_does_not_create_the_tree_default(self) -> None:
        prefs_store.set_pref(STRANGER_IN_TESTS, "lang", "en")

        self.assertFalse(_fake_tree(self.root).exists())

    def test_write_is_redirected_not_dropped(self) -> None:
        """Перенаправили, а не проглотили: запись читается обратно и лежит в tempdir."""
        prefs_store.set_pref(OWNER_IN_TESTS, "lang", "en")

        self.assertEqual(prefs_store.get_lang(OWNER_IN_TESTS), "en")
        self.assertTrue(
            prefs_store.PYTEST_PREFS_FILE.exists(),
            "под pytest запись обязана уйти во временный файл, а не исчезнуть",
        )
        doc = json.loads(prefs_store.PYTEST_PREFS_FILE.read_text(encoding="utf-8"))
        self.assertEqual(doc[OWNER_IN_TESTS]["lang"], "en")

    def test_resolved_path_is_outside_the_tree(self) -> None:
        resolved = prefs_store._prefs_path()

        self.assertNotEqual(resolved, _fake_tree(self.root))
        self.assertEqual(resolved, prefs_store.PYTEST_PREFS_FILE)


class TestExplicitRedirectsStillWin(unittest.TestCase):
    """Изоляция не должна отнимать у тестов уже работающие способы задать путь.

    Три существующих файла (`test_telegram_bot_menus`, `test_owner_decisions_wiring`,
    `test_warnings_menu_alert_options`) подменяют `PREFS_FILE` на tmp_path и читают
    результат — если бы новая изоляция перебивала подмену, они бы молча стали
    проверять чужой файл.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_explicit_path_argument_wins(self) -> None:
        target = self.root / "explicit.json"

        prefs_store.set_pref("77", "lang", "en", target)

        self.assertTrue(target.exists())
        self.assertEqual(prefs_store.get_lang("77", target), "en")

    def test_monkeypatched_prefs_file_wins(self) -> None:
        target = self.root / "patched.json"
        orig = prefs_store.PREFS_FILE
        prefs_store.PREFS_FILE = target
        try:
            prefs_store.set_pref("77", "lang", "en")

            self.assertTrue(
                target.exists(),
                "подменённый PREFS_FILE перестал действовать — три существующих "
                "тест-файла молча проверяли бы не тот файл",
            )
            self.assertEqual(prefs_store.get_lang("77"), "en")
        finally:
            prefs_store.PREFS_FILE = orig


class TestOutsidePytestTheLiveDefaultStands(unittest.TestCase):
    """Обратный контроль: в проде умолчание обязано остаться живым файлом.

    Меряется в ОТДЕЛЬНОМ процессе — внутри прогона ``PYTEST_CURRENT_TEST`` выставлен
    всегда, и «как ведёт себя модуль без pytest» из него не увидеть.
    """

    def _run_child(self, env_extra: dict) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code = textwrap.dedent(
                f"""
                import json, pathlib, sys
                sys.path.insert(0, {str(_REPO_ROOT)!r})
                from spa_core.telegram import prefs
                root = pathlib.Path({str(root)!r})
                prefs.BASE_DIR = root
                prefs.PREFS_FILE = root / "data" / "telegram" / "user_prefs.json"
                prefs.set_pref("{OWNER_IN_TESTS}", "lang", "en")
                # `_prefs_path` НАМЕРЕННО читается через getattr: иначе дочерний
                # процесс падал бы на неисправленном модуле по отсутствию символа,
                # и обратный контроль («вне pytest пишем в живой файл») краснел бы
                # не по своей причине — то есть перестал бы быть контролем.
                resolve = getattr(prefs, "_prefs_path", None)
                print(json.dumps({{
                    "tree_default_written": prefs.PREFS_FILE.exists(),
                    "resolved": str(resolve()) if resolve else "",
                }}))
                """
            )
            env = {k: v for k, v in os.environ.items()
                   if k not in ("PYTEST_CURRENT_TEST",)}
            env.update(env_extra)
            out = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True, text=True, env=env, cwd=str(_REPO_ROOT),
            )
            self.assertEqual(out.returncode, 0, out.stderr)
            return json.loads(out.stdout.strip().splitlines()[-1])

    def test_without_pytest_the_write_lands_in_the_tree_default(self) -> None:
        result = self._run_child({})

        self.assertTrue(
            result["tree_default_written"],
            "вне pytest настройки перестали писаться по умолчанию — бот в проде "
            "потерял бы память о языке и заглушках",
        )

    def test_live_env_flag_restores_the_live_default_under_pytest(self) -> None:
        """Аварийный выход для теста, которому нужен ИМЕННО живой путь."""
        result = self._run_child({
            "PYTEST_CURRENT_TEST": "fake::test",
            prefs_store.LIVE_ENV_FLAG: "1",
        })

        self.assertTrue(result["tree_default_written"])

    def test_pytest_env_alone_is_enough_to_divert(self) -> None:
        """Ничего, кроме признака pytest, для изоляции не требуется."""
        result = self._run_child({"PYTEST_CURRENT_TEST": "fake::test"})

        self.assertFalse(
            result["tree_default_written"],
            "признака pytest оказалось недостаточно — изоляция держится на чём-то "
            "ещё, чего в настоящем прогоне может не быть",
        )


class TestUnderRealPytestProcess(unittest.TestCase):
    """Тот же запрет, но проверенный НАСТОЯЩИМ прогоном pytest, а не эмуляцией.

    Внутренние тесты выше опираются на то, что ``PYTEST_CURRENT_TEST`` выставлен.
    Этот — доказывает, что в реальном прогоне он действительно выставлен к моменту
    записи, то есть изоляция сработает у настоящего теста, а не только в теории.
    """

    def test_generated_test_writing_prefs_leaves_the_tree_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            test_file = root / "test_generated_prefs_writer.py"
            test_file.write_text(
                textwrap.dedent(
                    f"""
                    import pathlib, sys
                    sys.path.insert(0, {str(_REPO_ROOT)!r})
                    from spa_core.telegram import prefs

                    ROOT = pathlib.Path({str(root)!r})

                    def test_writes_prefs_without_a_path():
                        prefs.BASE_DIR = ROOT
                        prefs.PREFS_FILE = ROOT / "data" / "telegram" / "user_prefs.json"
                        prefs.set_pref("{OWNER_IN_TESTS}", "lang", "en")
                    """
                ),
                encoding="utf-8",
            )
            # Якорь `--rootdir` даёт `_child_pytest`: без него pytest считает
            # rootdir общим предком cwd и аргумента и обходит `scandir`-ом весь
            # системный временный каталог (замер #382 — 9 780 560 записей,
            # >300 с). Здесь cwd совпадает с каталогом файла и потому спасает
            # сам по себе, но держаться это должно на договорённости набора,
            # а не на совпадении.
            out = _child_pytest.run_child_pytest(
                test_file, "-q", "-p", "no:cacheprovider", cwd=root, timeout=120
            )
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)

            self.assertFalse(
                _fake_tree(root).exists(),
                "настоящий прогон pytest создал файл настроек в дереве — "
                "изоляция в реальных условиях не работает",
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
