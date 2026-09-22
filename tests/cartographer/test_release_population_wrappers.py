"""Обёртки launchd — часть НАСЕЛЕНИЯ ВЫПУСКА Director (v1.3.1, 22.09).

Авария, воспроизведённая здесь дословно. Весь код v1.3 был доставлен в прод-дерево,
``deployment_acceptance`` отвечал OK, ``/health`` отвечал ok, содержательный хеш рантайма
совпадал с принятым кандидатом — и владелец всё равно видел путь **v1.2**, потому что
``scripts/agent_director_build.sh`` не передавал ``--v13``. Идентичность выпуска, не
включающая обёртку, не различает «v1.3 исполняется» и «v1.3 лежит рядом».

Поэтому обёртка входит в манифест выпуска, её байты двигают идентичность, а отсутствие
объявленной обёртки НАЗЫВАЕТСЯ отдельным полем, а не подделывается строкой с ``None``
(контракт ``files`` тотален: у каждой строки настоящий sha256).
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'cartographer'))

import release as rel                      # noqa: E402

WRAPPER = 'scripts/agent_director_build.sh'


def _prod(td, *, wrappers=True, v13_flag=True):
    root = Path(td) / 'prod'
    (root / 'scripts/cartographer').mkdir(parents=True, exist_ok=True)
    (root / 'tests/cartographer').mkdir(parents=True, exist_ok=True)
    (root / 'scripts/cartographer/snapshot.py').write_text('# модуль\n')
    (root / 'tests/cartographer/test_snapshot.py').write_text('# тест\n')
    if wrappers:
        flag = ' --v13' if v13_flag else ''
        (root / WRAPPER).write_text(f'#!/bin/bash\nexec python3 pub.py{flag}\n')
        (root / WRAPPER).chmod(0o755)
        (root / 'scripts/agent_director_server.sh').write_text('#!/bin/bash\nexec srv\n')
        (root / 'scripts/agent_director_server.sh').chmod(0o755)
    return root


def _bundle(td):
    b = Path(td) / 'bundle'
    b.mkdir(parents=True, exist_ok=True)
    return b


class TheWrapperIsInTheReleasePopulation(unittest.TestCase):

    def test_the_build_wrapper_is_listed_in_the_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            m = rel.build_release_manifest(_prod(td), _bundle(td), 'a' * 40)
            paths = [f['path'] for f in m['files']]
            self.assertIn(WRAPPER, paths)
            self.assertIn('scripts/agent_director_server.sh', paths)

    def test_the_wrapper_row_records_its_mode(self):
        """Права — часть доставки: 100644 у обёртки launchd = мёртвый агент."""
        with tempfile.TemporaryDirectory() as td:
            m = rel.build_release_manifest(_prod(td), _bundle(td), 'a' * 40)
            row = [f for f in m['files'] if f['path'] == WRAPPER][0]
            self.assertEqual(row['mode'], '0o755')
            self.assertEqual(row['role'], 'launchd_wrapper_selects_runtime_path')

    def test_files_contract_stays_total(self):
        """Каждая перечисленная строка несёт НАСТОЯЩИЙ sha256 — в том числе обёртка."""
        with tempfile.TemporaryDirectory() as td:
            m = rel.build_release_manifest(_prod(td), _bundle(td), 'a' * 40)
            self.assertEqual(m['file_count'], len(m['files']))
            for f in m['files']:
                self.assertEqual(len(f['sha256']), 64, f['path'])


class WrapperBytesMoveTheReleaseIdentity(unittest.TestCase):
    """Смысл всей правки: другая обёртка ⇒ другая идентичность выпуска.

    Сравнение идёт в ОДНОМ дереве, потому что ``semantic_digest`` манифеста включает
    абсолютные пути ``production``/``bundle``: два разных временных каталога различались
    бы и без всякой правки обёртки, и такой «контроль» доказывал бы только то, что
    каталоги разные. Замер 22.09 показал это прямо.
    """

    def test_dropping_the_v13_flag_changes_the_semantic_digest(self):
        with tempfile.TemporaryDirectory() as td:
            root, b = _prod(td, v13_flag=True), _bundle(td)
            with_flag = rel.build_release_manifest(root, b, 'a' * 40)
            (root / WRAPPER).write_text('#!/bin/bash\nexec python3 pub.py\n')
            (root / WRAPPER).chmod(0o755)
            without = rel.build_release_manifest(root, b, 'a' * 40)
            self.assertNotEqual(with_flag['semantic_digest'], without['semantic_digest'])

    def test_a_mode_change_alone_changes_the_digest(self):
        """Права — часть доставки, значит и часть идентичности."""
        with tempfile.TemporaryDirectory() as td:
            root, b = _prod(td), _bundle(td)
            before = rel.build_release_manifest(root, b, 'a' * 40)
            (root / WRAPPER).chmod(0o644)
            after = rel.build_release_manifest(root, b, 'a' * 40)
            self.assertNotEqual(before['semantic_digest'], after['semantic_digest'])

    def test_two_builds_of_an_unchanged_tree_agree(self):
        """Обратная сторона: без неё «другой дайджест» ничего не доказывал бы."""
        with tempfile.TemporaryDirectory() as td:
            root, b = _prod(td), _bundle(td)
            a1 = rel.build_release_manifest(root, b, 'a' * 40)
            a2 = rel.build_release_manifest(root, b, 'a' * 40)
            self.assertEqual(a1['semantic_digest'], a2['semantic_digest'])


class AMissingWrapperIsNamedNotFaked(unittest.TestCase):

    def test_a_missing_wrapper_appears_in_its_own_field(self):
        with tempfile.TemporaryDirectory() as td:
            m = rel.build_release_manifest(_prod(td, wrappers=False), _bundle(td),
                                           'a' * 40)
            self.assertIn(WRAPPER, m['release_population_missing'])
            self.assertIn('scripts/agent_director_server.sh',
                          m['release_population_missing'])

    def test_a_missing_wrapper_does_not_appear_as_a_file_row(self):
        """Отчитаться об отсутствии, сломав контракт ``files``, запрещено."""
        with tempfile.TemporaryDirectory() as td:
            m = rel.build_release_manifest(_prod(td, wrappers=False), _bundle(td),
                                           'a' * 40)
            self.assertNotIn(WRAPPER, [f['path'] for f in m['files']])
            for f in m['files']:
                self.assertEqual(len(f['sha256']), 64, f['path'])

    def test_present_wrappers_leave_the_field_empty_and_that_is_measured_zero(self):
        """Пустой список = ИЗМЕРЕНО и равно нулю, а не «не смотрели»."""
        with tempfile.TemporaryDirectory() as td:
            m = rel.build_release_manifest(_prod(td), _bundle(td), 'a' * 40)
            self.assertEqual(m['release_population_missing'], [])

    def test_the_missing_field_is_not_what_makes_validation_refuse(self):
        """Дифференциально: отсутствие обёрток НЕ добавляет отказа проверке.

        Тонкий стенд валидацию не проходит и с обёртками, и без них (по своей причине —
        пустой список запрещённых действий). Значит сравнивать надо не «прошло/не
        прошло», а ОДИНАКОВА ли причина: иначе мой тест приписал бы своей правке чужой
        отказ.
        """
        def why(wrappers):
            with tempfile.TemporaryDirectory() as td:
                m = rel.build_release_manifest(_prod(td, wrappers=wrappers),
                                               _bundle(td), 'a' * 40)
                try:
                    rel.validate_release_manifest(m, 'built')
                    return None
                except rel.ReleaseInputError as exc:
                    return str(exc)
        self.assertEqual(why(True), why(False))


class TheDeclaredPopulationIsDeclaredNotGuessed(unittest.TestCase):

    def test_wrappers_are_a_declared_tuple(self):
        self.assertIn(WRAPPER, rel.WRAPPERS)
        self.assertIn('scripts/agent_director_server.sh', rel.WRAPPERS)

    def test_no_wrapper_is_discovered_by_glob(self):
        """Население объявлено списком: находка по маске впустила бы чужую обёртку."""
        src = (ROOT / 'scripts' / 'cartographer' / 'release.py').read_text(
            encoding='utf-8')
        self.assertNotIn("glob('agent_*", src)
        self.assertNotIn('glob("agent_*', src)


if __name__ == '__main__':
    unittest.main()
