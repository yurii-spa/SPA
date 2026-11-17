# LLM_FORBIDDEN
"""Канал наблюдения прогона — свойство ЭТОЙ сессии, а не её детей (ADR-1039).

**Авария, которую воспроизводит каждый тест ниже, случилась ДВАЖДЫ ПОДРЯД на живом
контрольном прогоне.** `43985062958` (шард 2) и `43996349768` (шард 5) объявлены
**INCOMPLETE** одной и той же парой причин:

    шард не собрал 11031 тестов населения: [...]
    шард собрал 16 тестов вне населения: ['spa_core/tests/test_typed_numbers_target_as_paper.py::…',
                                          'tests/test_doc_drift.py::…']

Число «не собрал» равно ВСЕМУ населению шарда, а 16 «вне населения» — это дословно
``scripts/hook_arg_mutation_census.PROBE_TARGETS``. Механизм: шард объявляет
``SPA_PYTEST_MANIFEST``/``SPA_PYTEST_STREAM`` в окружении джобы и грузит оба плагина
флагом ``-p``; прибор ADR-1037 поднимает ДОЧЕРНИЙ pytest, грузит ТЕ ЖЕ плагины
намеренно (иначе он мерил бы набор, которого в CI не бывает) и наследует окружение
через ``env = {**os.environ}``. Перечень открывается на ``"w"`` ⇒ перечень шарда
ИСЧЕЗАЛ целиком, и вердикта о НАБОРЕ не было ни разу.

**Почему дверь стои́т у РОДИТЕЛЯ, а не у площадки.** Замер поверхности 17.11 (AST по
пяти корням, разрешение имени argv глубиной 1 — это НИЖНЯЯ граница, и это сказано
вслух): площадок, поднимающих дочерний pytest, **45**, и **35** из них канал не
называют вовсе. Починка площадки за площадкой проигрывает по построению — каждая
новая площадка рождается членом класса. Переменная нужна родителю РОВНО ОДИН раз:
дальше запись держит открытый файловый дескриптор, поэтому снятие переменной с
окружения не отнимает у родителя ничего, а у детей отнимает возможность писать в
чужую запись. Тот же приём уже применён в том же самом ``pytest_configure`` к
``SPA_PYTEST_RESUME_ONLY`` — после ТОЙ ЖЕ аварии (контрольный прогон №5, 17.10:
вложенные сцены унаследовали список доигрывания и отбросили все свои тесты).

**Шард РОТИРУЕТСЯ** вместе с раскладкой файлов по шардам, поэтому вопрос «почему
манифест разошёлся именно у шарда 2» имел ложную премису: предметом был не шард, а
тест, которому он достался.

Контроли идут В ОБЕ СТОРОНЫ: сцена, которая не может УВИДЕТЬ аварию, не является
положительным контролем (`.claude/rules/deployment.md`, § «Проверка сторожа
сторожей»), поэтому у двери есть отрицательный контроль — та же сцена с
восстановленным наследованием обязана ЗАТЕРЕТЬ перечень родителя.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_STREAM_PLUGIN = "spa_core.ci.pytest_stream_record"
_MANIFEST_PLUGIN = "spa_core.ci.pytest_collect_manifest"
_MANIFEST_ENV = "SPA_PYTEST_MANIFEST"
_STREAM_ENV = "SPA_PYTEST_STREAM"

#: Сцена РОДИТЕЛЯ. Её второй тест делает ровно то, что делают 35 площадок набора:
#: отдаёт ребёнку ``{**os.environ}`` и грузит ему те же два плагина.
_PARENT_SCENE = '''\
import os, subprocess, sys
from pathlib import Path


def test_the_channel_is_not_in_the_environment_of_this_session():
    """Дверь: к моменту исполнения ТЕСТА переменных в окружении уже нет."""
    assert "SPA_PYTEST_MANIFEST" not in os.environ, os.environ.get("SPA_PYTEST_MANIFEST")
    assert "SPA_PYTEST_STREAM" not in os.environ, os.environ.get("SPA_PYTEST_STREAM")


def test_a_child_pytest_loading_the_same_plugins_runs():
    env = {**os.environ}
    # Отрицательный контроль: наследование ВОССТАНАВЛИВАЕТСЯ руками, чтобы доказать,
    # что сцена способна увидеть аварию. Без этой переменной ветка не исполняется.
    reinject = os.environ.get("SPA_SCENE_REINJECT")
    if reinject:
        env["SPA_PYTEST_MANIFEST"] = reinject
    env["PYTHONPATH"] = os.environ["SPA_SCENE_PYTHONPATH"]
    inner = os.environ["SPA_SCENE_INNER"]
    done = subprocess.run(
        [sys.executable, "-m", "pytest", inner, "-q", "--collect-only",
         "-p", "no:randomly", "-p", "no:cacheprovider",
         "-p", "spa_core.ci.pytest_stream_record",
         "-p", "spa_core.ci.pytest_collect_manifest"],
        env=env, capture_output=True, text=True, timeout=300,
    )
    assert done.returncode == 0, done.stdout + done.stderr
'''

_INNER_SCENE = '''\
def test_inner_one(): assert True
def test_inner_two(): assert True
'''


def _read_manifest(path: Path) -> dict:
    from spa_core.ci.pytest_collect_manifest import read_manifest

    return read_manifest(str(path))


def _events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if raw:
            try:
                out.append(json.loads(raw))
            except ValueError:
                pass
    return out


class TheDoorIsClosedAtTheParent(unittest.TestCase):
    """Двухуровневая сцена: pytest → тест → дочерний pytest с теми же плагинами."""

    def _run_parent(self, tmp: Path, *, reinject: bool) -> tuple[Path, Path, subprocess.CompletedProcess]:
        parent_scene = tmp / "test_parent_scene.py"
        parent_scene.write_text(_PARENT_SCENE, encoding="utf-8")
        inner_scene = tmp / "test_inner_scene.py"
        inner_scene.write_text(_INNER_SCENE, encoding="utf-8")
        manifest = tmp / "collected.jsonl"
        stream = tmp / "stream.jsonl"
        env = {**os.environ}
        env[_MANIFEST_ENV] = str(manifest)
        env[_STREAM_ENV] = str(stream)
        env["PYTHONPATH"] = str(_REPO_ROOT)
        env["SPA_SCENE_PYTHONPATH"] = str(_REPO_ROOT)
        env["SPA_SCENE_INNER"] = str(inner_scene)
        env.pop("SPA_SCENE_REINJECT", None)
        if reinject:
            env["SPA_SCENE_REINJECT"] = str(manifest)
        done = subprocess.run(
            [sys.executable, "-m", "pytest", str(parent_scene), "-q",
             "-p", "no:randomly", "-p", "no:cacheprovider",
             "-p", _STREAM_PLUGIN, "-p", _MANIFEST_PLUGIN],
            cwd=str(tmp), env=env, capture_output=True, text=True, timeout=600,
        )
        return manifest, stream, done

    def test_a_child_pytest_cannot_clobber_the_parents_collect_manifest(self) -> None:
        """Авария 43985062958/43996349768 — в закрытую дверь она не проходит."""
        with _tmp() as tmp:
            manifest, stream, done = self._run_parent(tmp, reinject=False)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            read = _read_manifest(manifest)
            self.assertIsNotNone(
                read["collected"],
                f"перечень родителя не прочитан: {read['why']} — это и есть авария")
            collected = read["collected"] or []
            self.assertTrue(
                any("test_parent_scene.py" in n for n in collected),
                f"перечень родителя ЗАТЁРТ ребёнком: {collected}")
            self.assertFalse(
                any("test_inner_scene.py" in n for n in collected),
                f"в перечне родителя лежит сбор РЕБЁНКА: {collected}")
            # Запись родителя при этом ПОЛНАЯ: дверь не отняла у него ничего.
            kinds = [e.get("e") for e in _events(stream)]
            self.assertIn("session", kinds, kinds)
            self.assertIn("end", kinds, kinds)

    def test_the_scene_sees_the_accident_when_inheritance_is_restored(self) -> None:
        """ОТРИЦАТЕЛЬНЫЙ контроль: сцена без двери обязана ПОКАЗАТЬ аварию.

        Проверка, никогда не видевшая настоящей поломки, — украшение. Здесь
        наследование восстановлено руками у ОДНОЙ площадки, и перечень родителя
        обязан исчезнуть ровно так, как он исчез на шардах 2 и 5.
        """
        with _tmp() as tmp:
            manifest, _stream, done = self._run_parent(tmp, reinject=True)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            read = _read_manifest(manifest)
            collected = read["collected"] or []
            self.assertFalse(
                any("test_parent_scene.py" in n for n in collected),
                "сцена НЕ способна увидеть аварию: при восстановленном наследовании "
                f"перечень родителя всё ещё цел ({collected}) — тогда и зелёный "
                "ответ соседнего теста ничего не доказывает")
            self.assertTrue(
                any("test_inner_scene.py" in n for n in collected),
                f"перечень затёрт, но сбор ребёнка в нём не назван: {collected}")


class TheDoorIsDeclaredInBothPlugins(unittest.TestCase):
    """Паритет с ОБЪЯВЛЕНИЕМ: переменная СНИМАЕТСЯ, а не просто читается.

    Мерить AST, а не подстроку: `os.environ.get(...)` рядом с комментарием про
    снятие — ровно та «записка вместо инъекции», против которой написан сторож
    претензии `injected-clock` (цикл #477).
    """

    CASES = (
        ("spa_core/ci/pytest_stream_record.py", _STREAM_ENV, "STREAM_ENV"),
        ("spa_core/ci/pytest_collect_manifest.py", _MANIFEST_ENV, "MANIFEST_ENV"),
    )

    def test_each_plugin_removes_its_own_channel_from_the_environment(self) -> None:
        for rel, literal, const in self.CASES:
            with self.subTest(plugin=rel):
                tree = ast.parse((_REPO_ROOT / rel).read_text(encoding="utf-8"), filename=rel)
                configure = next(
                    (n for n in ast.walk(tree)
                     if isinstance(n, ast.FunctionDef) and n.name == "pytest_configure"),
                    None)
                self.assertIsNotNone(configure, f"{rel}: нет pytest_configure")
                pops = []
                for call in ast.walk(configure):           # type: ignore[arg-type]
                    if not isinstance(call, ast.Call):
                        continue
                    if not (isinstance(call.func, ast.Attribute) and call.func.attr == "pop"):
                        continue
                    names = [a.id for a in call.args if isinstance(a, ast.Name)]
                    strings = [a.value for a in call.args
                               if isinstance(a, ast.Constant) and isinstance(a.value, str)]
                    pops.extend(names + strings)
                self.assertTrue(
                    const in pops or literal in pops,
                    f"{rel}: канал {literal} НЕ СНИМАЕТСЯ с окружения в pytest_configure "
                    f"(снимаются: {pops}) — значит его унаследует каждый дочерний pytest")


class TheCensusDoesNotTouchItsParentsChannel(unittest.TestCase):
    """Площадка, которая аварию и устроила, судится ПО ИСХОДУ.

    Прибор зовут ДВУМЯ путями: из набора (тогда его прикрывает дверь родителя) и
    рукой из оболочки, где переменная могла быть экспортирована и родителя-pytest
    нет вовсе. Здесь воспроизводится ВТОРОЙ путь: переменная ставится в окружение
    этого процесса, и байты файла обязаны остаться теми же.
    """

    def test_the_child_of_the_census_leaves_a_foreign_manifest_untouched(self) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_hook_arg_mutation_census_under_test",
            _REPO_ROOT / "scripts" / "hook_arg_mutation_census.py")
        assert spec and spec.loader
        census = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(census)

        with _tmp() as tmp:
            foreign = tmp / "collected.jsonl"
            before = json.dumps({"e": "collected", "count": 1,
                                 "nodeids": ["tests/test_foreign.py::test_parent"]},
                                ensure_ascii=False, sort_keys=True) + "\n"
            foreign.write_text(before, encoding="utf-8")
            old = os.environ.get(_MANIFEST_ENV)
            os.environ[_MANIFEST_ENV] = str(foreign)
            try:
                payload, why = census.measure_call_order(_REPO_ROOT)
            finally:
                if old is None:
                    os.environ.pop(_MANIFEST_ENV, None)
                else:
                    os.environ[_MANIFEST_ENV] = old
            # Предпосылка: ребёнок действительно отработал. Не отработал ⇒ падать
            # ГРОМКО, а не судить о нетронутом файле как о доказательстве двери.
            self.assertIsNotNone(
                payload, f"предпосылка НЕ обеспечена: дочерний pytest не отработал ({why})")
            self.assertEqual(
                foreign.read_text(encoding="utf-8"), before,
                "дочерний pytest прибора ЗАТЁР чужой перечень — ровно авария шардов 2 и 5")


def _tmp():
    import tempfile

    class _Ctx:
        def __enter__(self) -> Path:
            self._d = tempfile.TemporaryDirectory(prefix="obs_channel_")
            return Path(self._d.name)

        def __exit__(self, *exc) -> None:
            self._d.cleanup()

    return _Ctx()


if __name__ == "__main__":                                   # pragma: no cover
    unittest.main()
