"""Тесты детерминированной сборки и вердикта выкладки (v1.1 Epic 1).

Проверяются три обещания:
  1. вердикт выкладки различает ТРИ исхода, а «не измерено» не выдаётся за «изменилось»;
  2. пушер отсюда недостижим — не по флагу, а по отсутствию кода;
  3. политика свежести объявлена и обоснована источниками, а не пожеланием.
"""
import ast
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from scripts.cartographer import director_publish as dp  # noqa: E402


class TheExitCodeBelongsToLaunchdNotToTheVerdict(unittest.TestCase):
    """Находка канонического гейта: вердикт кодом возврата ломает расписанный агент.

    Гейт ждёт 0, а первый прогон честно отвечает «сравнивать не с чем». Но дефект
    глубже гейта: для launchd и сторожей здоровья любой ненулевой код — поломка, и шаг,
    выходящий 3 каждый час при «менять нечего», выглядел бы вечно сломанным. Настоящая
    поломка утонула бы в этом шуме.
    """

    def _run(self, tmp, extra=()):
        src = Path(tmp) / 'snap'
        src.mkdir(exist_ok=True)
        (src / 'investment_snapshot.json').write_text('{"real_capital_proven": false}')
        import io
        import contextlib
        buf = io.StringIO()
        argv = ['--bundle', str(src), '--output', str(Path(tmp) / f'out{len(extra)}'),
                *extra]
        with contextlib.redirect_stdout(buf):
            code = dp.main(argv)
        return code, buf.getvalue()

    def test_a_not_measured_run_still_exits_zero_by_default(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            code, out = self._run(tmp)
            self.assertEqual(code, 0)
            self.assertIn('NOT_MEASURED', out)   # вердикт виден, но не в коде

    def test_the_verdict_is_readable_in_the_output(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            _code, out = self._run(tmp)
            self.assertIn('ВЕРДИКТ ВЫКЛАДКИ', out)

    def test_the_flag_restores_verdict_codes_for_humans(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            code, _out = self._run(tmp, extra=('--verdict-exit-code',))
            self.assertEqual(code, 2)

    def test_the_wrapper_does_not_ask_for_verdict_codes(self):
        """Обёртка launchd обязана НЕ просить вердикт кодом.

        Предмет — ИСПОЛНЯЕМАЯ часть, а не объяснение. Первая редакция искала флаг во
        всём тексте и краснела на комментарии «этого флага здесь нет намеренно» —
        четвёртый за смену случай одного класса: проверка, чей корпус включает её
        собственное объяснение, отравлена.
        """
        wrapper = ROOT / 'scripts/agent_director_build.sh'
        if not wrapper.exists():
            self.skipTest('обёртка вне этого дерева')
        runnable = [ln for ln in wrapper.read_text().splitlines()
                    if ln.strip() and not ln.lstrip().startswith('#')]
        self.assertTrue(runnable, 'исполняемых строк нет — проверять нечего')
        self.assertNotIn('--verdict-exit-code', '\n'.join(runnable))


class TheVerdictHasThreeOutcomes(unittest.TestCase):

    def test_a_changed_digest_says_publish(self):
        verdict, reason = dp.publish_verdict('aaaa1111', 'bbbb2222')
        self.assertEqual(verdict, 'PUBLISH')
        self.assertIn('изменился', reason)

    def test_an_equal_digest_says_skip(self):
        verdict, _ = dp.publish_verdict('aaaa1111', 'aaaa1111')
        self.assertEqual(verdict, 'SKIP')

    def test_no_published_digest_is_NOT_MEASURED_not_publish(self):
        """Ключевое: отсутствие сравнения — не «наверное, публикуем» (инв. #17)."""
        verdict, reason = dp.publish_verdict('aaaa1111', None)
        self.assertEqual(verdict, 'NOT_MEASURED')
        self.assertIn('НЕ значит', reason)

    def test_an_uncomputed_new_digest_is_NOT_MEASURED_too(self):
        self.assertEqual(dp.publish_verdict(None, 'bbbb2222')[0], 'NOT_MEASURED')
        self.assertEqual(dp.publish_verdict('', 'bbbb2222')[0], 'NOT_MEASURED')

    def test_the_three_verdicts_are_the_declared_vocabulary(self):
        self.assertEqual(set(dp.VERDICTS), {'PUBLISH', 'SKIP', 'NOT_MEASURED'})

    def test_an_unreadable_published_file_reads_as_NOT_MEASURED(self):
        """Битый файл — это «не измерено», а не «изменилось»."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / 'p.json'
            bad.write_text('{не json')
            self.assertIsNone(dp.read_published_digest(bad))
            self.assertEqual(dp.publish_verdict('aaaa', dp.read_published_digest(bad))[0],
                             'NOT_MEASURED')

    def test_a_missing_published_file_is_not_an_exception(self):
        self.assertIsNone(dp.read_published_digest('/nonexistent/p.json'))


class ThePusherIsUnreachableByConstruction(unittest.TestCase):
    """Гарантия «выкладки не будет» держится на отсутствии кода, а не на дисциплине."""

    def _tree(self):
        return ast.parse((ROOT / 'scripts/cartographer/director_publish.py').read_text())

    def test_the_module_imports_no_subprocess_and_no_network(self):
        banned = {'subprocess', 'socket', 'urllib', 'http', 'requests', 'asyncio'}
        found = []
        for node in ast.walk(self._tree()):
            if isinstance(node, ast.Import):
                found += [a.name.split('.')[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.append(node.module.split('.')[0])
        self.assertEqual(sorted(set(found) & banned), [])

    def test_no_call_can_execute_an_external_program(self):
        """Ни одного вызова вида run/Popen/system/exec — искать по ФОРМЕ вызова."""
        forbidden = {'run', 'Popen', 'call', 'check_output', 'system', 'execv',
                     'execvp', 'spawnv', 'fork'}
        hits = []
        for node in ast.walk(self._tree()):
            if isinstance(node, ast.Call):
                fn = node.func
                name = (fn.attr if isinstance(fn, ast.Attribute)
                        else fn.id if isinstance(fn, ast.Name) else None)
                if name in forbidden:
                    hits.append(name)
        self.assertEqual(hits, [])

    def test_the_pusher_is_not_named_at_all_after_the_tunnel_decision(self):
        """При туннеле выкладки не существует: раздаётся активированный каталог.

        До решения ARB команда печатала готовую строку пуша — остаток модели Pages.
        Печатать её для сгенерированных владельческих данных в ПУБЛИЧНЫЙ репозиторий
        опасно само по себе: однажды её кто-нибудь выполнит.
        """
        src = (ROOT / 'scripts/cartographer/director_publish.py').read_text()
        self.assertNotIn('push_to_' + 'github.py', src)
        for node in ast.walk(self._tree()):
            if isinstance(node, ast.Call):
                fn = node.func
                name = (fn.attr if isinstance(fn, ast.Attribute)
                        else fn.id if isinstance(fn, ast.Name) else None)
                self.assertNotIn(name, ('push', 'push_files', 'deliver'))

    def test_there_is_no_approval_flag_that_could_enable_pushing(self):
        """Флага «я разрешаю» нет намеренно: его можно передать по ошибке."""
        src = (ROOT / 'scripts/cartographer/director_publish.py').read_text()
        for flag in ('--allow-push', '--push', '--deploy', '--i-have-arb-approval'):
            self.assertNotIn(flag, src)


class TheFreshnessPolicyIsDeclaredAndGrounded(unittest.TestCase):

    def test_all_three_layers_have_a_tact(self):
        self.assertEqual(set(dp.FRESHNESS), {'CAPITAL', 'STUDIO', 'BUILD'})

    def test_every_tact_names_its_basis_and_its_writers(self):
        """Такт без основания — пожелание. Основание обязано называть писателя."""
        for layer, rec in dp.FRESHNESS.items():
            self.assertTrue(rec['basis'], layer)
            self.assertTrue(rec['sources_written_by'], layer)
            self.assertGreater(len(rec['basis']), 30, layer)

    def test_capital_is_not_faster_than_its_daily_sources(self):
        """Публиковать капитал чаще, чем он меняется, — выдуманная свежесть."""
        self.assertEqual(dp.FRESHNESS['CAPITAL']['tact'], 'DAILY_PLUS_ON_CHANGE')
        self.assertIn('daily_cycle', dp.FRESHNESS['CAPITAL']['sources_written_by'])

    def test_no_layer_claims_real_time(self):
        for rec in dp.FRESHNESS.values():
            self.assertNotIn('REAL_TIME', rec['tact'])
            self.assertNotIn('realtime', rec['tact'].lower())

    def test_the_published_set_is_the_page_manifest_icon_and_headers(self):
        self.assertEqual(set(dp.PUBLISHED_FILES),
                         {'index.html', 'manifest.webmanifest', 'icon.svg', '_headers'})

    def test_the_headers_file_is_in_the_published_set_not_just_written(self):
        """Настоящая находка сборки: файл писался в publish/, но в команду пуша не попадал.

        «Объявили политику кеша, но не доставили» — та же незащищённость, только с
        запиской. Набор публикуемого и команда доставки обязаны быть одним списком.
        """
        self.assertIn('_headers', dp.PUBLISHED_FILES)

    def test_no_raw_dataset_is_in_the_published_set(self):
        """Опубликованная проекция была бы выгрузкой владельческих данных одним GET."""
        for name in ('director_web_projection.json', 'freshness_state.json',
                     'authority_map.json', 'portal_snapshot.json',
                     'reliability_snapshot.json', 'work_snapshot.json'):
            self.assertNotIn(name, dp.PUBLISHED_FILES)

    def test_the_local_only_set_and_the_published_set_do_not_intersect(self):
        self.assertEqual(set(dp.PUBLISHED_FILES) & set(dp.LOCAL_ONLY_FILES), set())


class TheBundleIsDeterministicAndComplete(unittest.TestCase):

    def _bundle(self, tmp):
        """Мини-комплект снимков: сборка не должна требовать живого прода."""
        src = Path(tmp) / 'snapshots'
        src.mkdir()
        (src / 'investment_snapshot.json').write_text(json.dumps({
            'real_capital_proven': False, 'real_capital_note': 'не доказан',
            'capital_by_mode': {'REAL': None, 'PAPER': 100.0},
            'capital_metrics': [], 'kill_switch': {'triggered': False},
            'golive': {'ready': False, 'passed': 27, 'total': 29},
            'rnd_stage_counts': {}, 'counts': {'objects': 1}, 'objects': [],
            'limits': []}, ensure_ascii=False))
        (src / 'action_authority_audit.json').write_text(json.dumps({
            'counts': {'candidates': 0, 'ready_for_ui': 0, 'not_ready': 0, 'red_zone': 13},
            'red_zone': ['move_capital'], 'required_properties': [],
            'ui_exposes_actions': False, 'actions': []}, ensure_ascii=False))
        return src

    def test_the_publish_directory_carries_only_what_the_host_needs(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            src = self._bundle(tmp)
            out = Path(tmp) / 'out'
            dp.build_bundle(bundle=src, output=out)
            pub = out / dp.PUBLISH_DIR
            self.assertEqual(sorted(x.name for x in pub.iterdir()),
                             sorted(dp.PUBLISHED_FILES))

    def test_the_evidence_directory_keeps_the_raw_projection_locally(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            src = self._bundle(tmp)
            out = Path(tmp) / 'out'
            projection, _page, _state = dp.build_bundle(bundle=src, output=out)
            ev = out / dp.EVIDENCE_DIR
            raw = json.loads((ev / 'director_web_projection.json').read_text())
            self.assertEqual(raw['semantic_digest'], projection['semantic_digest'])
            self.assertFalse((out / dp.PUBLISH_DIR / 'director_web_projection.json').exists())

    def test_the_cache_headers_forbid_storing_a_private_response(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            src = self._bundle(tmp)
            out = Path(tmp) / 'out'
            dp.build_bundle(bundle=src, output=out)
            headers = (out / dp.PUBLISH_DIR / '_headers').read_text()
            self.assertIn('no-store', headers)
            self.assertIn('private', headers)
            self.assertIn('noindex', headers)

    def test_the_page_shows_all_four_freshness_times(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            src = self._bundle(tmp)
            _p, page, _s = dp.build_bundle(bundle=src, output=Path(tmp) / 'out')
            for label in ('последняя проверка', 'последняя удачная сборка',
                          'последнее изменение смысла', 'последняя удачная выкладка'):
                self.assertIn(label, page)

    def test_an_unpublished_bundle_says_publish_time_is_not_measured(self):
        """«Не выкладывали» — это «не измерено», а не пустая строка и не ноль."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            src = self._bundle(tmp)
            _p, page, state = dp.build_bundle(bundle=src, output=Path(tmp) / 'out')
            self.assertIsNone(state['last_successful_publish'])
            block = page.split('последняя удачная выкладка', 1)[1].split('</div>', 2)
            self.assertIn('не измерено', ''.join(block[:2]))

    def test_the_page_states_that_an_unchanged_digest_is_not_stale(self):
        """Ловушка, которую блок обязан не допустить: «не перевыкладывали» ≠ «протухло»."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            src = self._bundle(tmp)
            _p, page, _s = dp.build_bundle(bundle=src, output=Path(tmp) / 'out')
            self.assertIn('НЕ\nявляется устаревшим'.replace('\n', ' '), page.replace('\n', ' '))

    def test_the_semantic_change_time_moves_only_when_the_digest_moves(self):
        prev = {'semantic_digest': 'aaaa', 'last_semantic_change': '2026-01-01T00:00:00Z',
                'last_successful_publish': '2026-01-01T00:00:00Z'}
        same = dp.next_freshness_state(prev, digest='aaaa', now='2026-09-20T10:00:00Z')
        self.assertEqual(same['last_semantic_change'], '2026-01-01T00:00:00Z')
        self.assertEqual(same['last_check'], '2026-09-20T10:00:00Z')
        moved = dp.next_freshness_state(prev, digest='bbbb', now='2026-09-20T10:00:00Z')
        self.assertEqual(moved['last_semantic_change'], '2026-09-20T10:00:00Z')

    def test_the_build_never_stamps_a_publish_that_did_not_happen(self):
        """Штамповать выкладку, которой не было, — ложь в артефакте."""
        state = dp.next_freshness_state({}, digest='aaaa', now='2026-09-20T10:00:00Z')
        self.assertIsNone(state['last_successful_publish'])

    def test_a_matching_published_digest_records_the_publish(self):
        state = dp.next_freshness_state({}, digest='aaaa', now='2026-09-20T10:00:00Z',
                                        published_digest='aaaa')
        self.assertEqual(state['last_successful_publish'], '2026-09-20T10:00:00Z')

    def test_a_corrupt_previous_state_is_read_as_empty_not_as_an_error(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / 's.json'
            bad.write_text('{сломано')
            self.assertEqual(dp.read_freshness_state(bad), {})

    def test_two_builds_of_the_same_input_agree_on_the_digest(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            src = self._bundle(tmp)
            a, _pa, _sa = dp.build_bundle(bundle=src, output=Path(tmp) / 'a')
            b, _pb, _sb = dp.build_bundle(bundle=src, output=Path(tmp) / 'b')
            self.assertEqual(a['semantic_digest'], b['semantic_digest'])
            self.assertEqual(dp.publish_verdict(b['semantic_digest'],
                                                a['semantic_digest'])[0], 'SKIP')

    def test_an_existing_output_directory_is_refused(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            src = self._bundle(tmp)
            out = Path(tmp) / 'out'
            out.mkdir()
            with self.assertRaises(dp.PublishError):
                dp.build_bundle(bundle=src, output=out)

    def test_the_output_may_not_land_inside_the_input_set(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            src = self._bundle(tmp)
            with self.assertRaises(Exception):
                dp.build_bundle(bundle=src, output=src / 'inside')


if __name__ == '__main__':
    unittest.main()


class TheServeRootIsNotReadableByOtherUsers(unittest.TestCase):
    """Замер ARB 20.09: корень раздачи оказался 0755.

    Прежний отчёт называл «0600» — но это были ФАЙЛЫ, а каталоги никто не мерил.
    `mkdir` с обычной umask даёт 0755, и приватные данные владельца лежали бы в
    каталоге, читаемом любым пользователем машины. Здесь это проверяется числом.
    """

    def test_a_fresh_serve_root_is_created_0700(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            src = self._publish_dir(tmp)
            root = Path(tmp) / 'studio-os-serve' / 'director'
            dp.activate(root, src, digest='a' * 24)
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)

    def test_an_existing_loose_serve_root_is_tightened(self):
        """Умолчание уже могло создать 0755 — активация обязана это ИСПРАВИТЬ."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            src = self._publish_dir(tmp)
            root = Path(tmp) / 'studio-os-serve' / 'director'
            root.mkdir(parents=True)
            import os as _os
            _os.chmod(root, 0o755)
            _os.chmod(root.parent, 0o755)
            dp.activate(root, src, digest='b' * 24)
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            self.assertEqual(root.parent.stat().st_mode & 0o777, 0o700)

    def test_every_bundle_directory_and_file_is_private(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            src = self._publish_dir(tmp)
            root = Path(tmp) / 'studio-os-serve' / 'director'
            target = dp.activate(root, src, digest='c' * 24)
            self.assertEqual(target.stat().st_mode & 0o777, 0o700)
            for f in target.iterdir():
                self.assertEqual(f.stat().st_mode & 0o777, 0o600, f.name)
            self.assertEqual((root / 'current.json').stat().st_mode & 0o777, 0o600)

    def test_the_home_directory_itself_is_never_touched(self):
        """Ужимаем только свой каталог раздачи: права домашнего — не наше дело."""
        self.assertFalse(dp._is_serve_parent(Path.home()))
        self.assertTrue(dp._is_serve_parent(Path.home() / 'studio-os-serve'))

    def _publish_dir(self, tmp):
        src = Path(tmp) / 'publish'
        src.mkdir()
        for name in dp.PUBLISHED_FILES:
            (src / name).write_text('x')
        return src


class TheFullCycleRebuildsEvidenceFromCanonicalSources(unittest.TestCase):
    """Режим полного цикла: канонические источники → улики → проекция → оболочка.

    Без него расписанный шаг не делал бы того, что объявлено: `director_publish` умел
    собирать комплект лишь из УЖЕ принятых снимков, то есть свежесть держалась бы на
    том, что кто-то руками пересобрал улики. Канонический гейт это и поймал — обёртка
    без аргументов отказала кодом 2 (argparse).
    """

    def test_all_eight_builders_are_wired_in_dependency_order(self):
        names = [n for n, _ in dp.REBUILD_STEPS]
        self.assertEqual(len(names), 8)
        # Зависимость обязана идти ПОСЛЕ того, что она читает.
        self.assertLess(names.index('snapshot'), names.index('authority_map'))
        self.assertLess(names.index('authority_map'), names.index('reliability'))
        self.assertLess(names.index('reliability'), names.index('work'))
        self.assertLess(names.index('governance'), names.index('actions'))
        self.assertLess(names.index('work'), names.index('director'))

    def test_every_step_names_an_existing_builder(self):
        import importlib
        for name, _template in dp.REBUILD_STEPS:
            module = importlib.import_module(f'scripts.cartographer.{name}')
            self.assertTrue(hasattr(module, 'main'), name)

    def test_the_rebuild_imports_no_subprocess(self):
        """Сборщики зовутся ВНУТРИ процесса: `subprocess` — дверь наружу."""
        import ast
        tree = ast.parse((ROOT / 'scripts/cartographer/director_publish.py').read_text())
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found += [a.name.split('.')[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.append(node.module.split('.')[0])
        self.assertNotIn('subprocess', found)

    def test_a_failing_step_names_itself_and_stops_the_cycle(self):
        """Половина улик выглядела бы как целая — поэтому отказ шага рушит весь цикл."""
        import tempfile
        import unittest.mock
        with tempfile.TemporaryDirectory() as tmp:
            broken = unittest.mock.Mock()
            broken.main.side_effect = SystemExit(2)
            with unittest.mock.patch('importlib.import_module', return_value=broken):
                with self.assertRaises(dp.RebuildError) as caught:
                    dp.rebuild_evidence(ROOT, Path(tmp))
            self.assertIn('snapshot', str(caught.exception))
            self.assertIn('кодом 2', str(caught.exception))

    def test_missing_artifacts_after_green_steps_are_refused(self):
        """Шаг может выйти нулём и не положить улику — это тоже отказ, а не успех."""
        import tempfile
        import unittest.mock
        with tempfile.TemporaryDirectory() as tmp:
            silent = unittest.mock.Mock()
            silent.main.return_value = 0
            with unittest.mock.patch('importlib.import_module', return_value=silent):
                with self.assertRaises(dp.RebuildError) as caught:
                    dp.rebuild_evidence(ROOT, Path(tmp))
            self.assertIn('улик нет', str(caught.exception))

    def test_the_work_root_may_not_be_inside_the_repository(self):
        with self.assertRaises(dp.PublishError):
            dp.rebuild_evidence(ROOT, ROOT / 'work')

    def test_the_expected_artifacts_are_the_six_the_bundle_needs(self):
        self.assertEqual(set(dp.REBUILD_ARTIFACTS.values()),
                         {'reliability_snapshot.json', 'work_snapshot.json',
                          'investment_snapshot.json', 'governance_snapshot.json',
                          'action_authority_audit.json', 'director_center.json'})


class TheDigestIgnoresTheClockAtEveryDepth(unittest.TestCase):
    """Замер 20.09: два прогона подряд давали РАЗНЫЕ дайджесты — 458 различий, и все
    до единого `as_of`/`last_seen` внутри находок надёжности.

    На таком дайджесте замысел «публиковать по смене смысла» не держится: он публиковал
    бы каждый час. Момент НАБЛЮДЕНИЯ — не факт.
    """

    def _doc(self, **kw):
        from scripts.cartographer import web_projection as wp
        base = {'schema_version': wp.SCHEMA, 'layers': {'STUDIO': {'reliability': {
            'findings': [{'title': 'x', 'severity': 'WARNING',
                          'as_of': '2026-09-20T22:05:06Z',
                          'last_seen': '2026-09-20T22:05:06Z'}]}}}}
        base.update(kw)
        return base

    def test_a_changed_observation_stamp_does_not_move_the_digest(self):
        from scripts.cartographer import web_projection as wp
        a = self._doc()
        b = json.loads(json.dumps(a))
        f = b['layers']['STUDIO']['reliability']['findings'][0]
        f['as_of'] = '2026-09-20T23:59:59Z'
        f['last_seen'] = '2026-09-20T23:59:59Z'
        self.assertEqual(wp.semantic_digest(a), wp.semantic_digest(b))

    def test_a_changed_FACT_does_move_the_digest(self):
        """Обратный контроль: дайджест, который не двигается, ничего не охраняет."""
        from scripts.cartographer import web_projection as wp
        a = self._doc()
        b = json.loads(json.dumps(a))
        b['layers']['STUDIO']['reliability']['findings'][0]['severity'] = 'CRITICAL'
        self.assertNotEqual(wp.semantic_digest(a), wp.semantic_digest(b))

    def test_a_new_finding_moves_the_digest(self):
        from scripts.cartographer import web_projection as wp
        a = self._doc()
        b = json.loads(json.dumps(a))
        b['layers']['STUDIO']['reliability']['findings'].append({'title': 'новая'})
        self.assertNotEqual(wp.semantic_digest(a), wp.semantic_digest(b))

    def test_volatile_keys_are_declared_not_guessed(self):
        from scripts.cartographer import web_projection as wp
        for key in ('as_of', 'last_seen', 'observed_at', 'generated_at', 'age_hours'):
            self.assertIn(key, wp.VOLATILE_LEAF_KEYS)

    def test_stripping_keeps_the_structure(self):
        """Пропажа самого ПОЛЯ — тоже смысл, и её прятать нельзя."""
        from scripts.cartographer import web_projection as wp
        a = {'x': {'as_of': '1', 'severity': 'WARNING'}}
        b = {'x': {'severity': 'WARNING'}}
        self.assertEqual(wp._strip_volatile(a), wp._strip_volatile(b))
        c = {'x': {'severity': 'WARNING', 'extra': 1}}
        self.assertNotEqual(wp._strip_volatile(a), wp._strip_volatile(c))


class TheFreshnessStateIsWrittenWhereItIsRead(unittest.TestCase):
    """Первая редакция писала состояние только в evidence/, а читала по --state.

    Файла там не было никогда ⇒ каждый прогон считал дайджест новым ⇒ «последнее
    изменение смысла» двигалось бы ежечасно. Ровно тот ложный сдвиг, против которого
    поле и существует.
    """

    def _bundle(self, tmp):
        src = Path(tmp) / 'snap'
        src.mkdir(exist_ok=True)
        (src / 'investment_snapshot.json').write_text('{"real_capital_proven": false}')
        return src

    def test_the_state_file_appears_at_the_declared_path(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            src = self._bundle(tmp)
            state = Path(tmp) / 'state' / 'freshness_state.json'
            dp.build_bundle(bundle=src, output=Path(tmp) / 'o1', state_path=state)
            self.assertTrue(state.exists())
            self.assertEqual(state.stat().st_mode & 0o777, 0o600)

    def test_a_second_unchanged_run_does_not_move_the_semantic_change_time(self):
        """Главная проверка ARB: неизменный смысл не смеет двигать отметку."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            src = self._bundle(tmp)
            state = Path(tmp) / 'state' / 'freshness_state.json'
            _p1, _g1, s1 = dp.build_bundle(bundle=src, output=Path(tmp) / 'o1',
                                           state_path=state, now='2026-09-20T10:00:00Z')
            _p2, _g2, s2 = dp.build_bundle(bundle=src, output=Path(tmp) / 'o2',
                                           state_path=state, now='2026-09-20T11:00:00Z')
            self.assertEqual(s1['semantic_digest'], s2['semantic_digest'])
            self.assertEqual(s2['last_semantic_change'], s1['last_semantic_change'])
            self.assertNotEqual(s2['last_check'], s1['last_check'])
            self.assertNotEqual(s2['last_successful_build'], s1['last_successful_build'])

    def test_a_changed_meaning_DOES_move_the_semantic_change_time(self):
        """Обратный контроль: отметка, которая не двигается, бесполезна."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            src = self._bundle(tmp)
            state = Path(tmp) / 'state' / 'freshness_state.json'
            dp.build_bundle(bundle=src, output=Path(tmp) / 'o1', state_path=state,
                            now='2026-09-20T10:00:00Z')
            (src / 'investment_snapshot.json').write_text(
                '{"real_capital_proven": false, "counts": {"objects": 7}}')
            _p, _g, s2 = dp.build_bundle(bundle=src, output=Path(tmp) / 'o2',
                                         state_path=state, now='2026-09-20T11:00:00Z')
            self.assertEqual(s2['last_semantic_change'], '2026-09-20T11:00:00Z')

    def test_the_state_path_may_not_be_inside_the_repository(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            src = self._bundle(tmp)
            with self.assertRaises(dp.PublishError):
                dp.build_bundle(bundle=src, output=Path(tmp) / 'o',
                                state_path=ROOT / 'freshness_state.json')


class TheVerdictComparesAgainstWhatIsActuallyServed(unittest.TestCase):
    """При туннеле «опубликовано» = «лежит в активном каталоге», а не «в отдельном файле».

    Без этого SKIP не наступал бы никогда: задание переподставляло бы комплект каждый
    час, и обещание «ничего не делать при неизменном смысле» осталось бы словами.
    """

    def test_an_empty_serve_root_reads_as_not_measured(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(dp.read_serving_digest(tmp))
            self.assertIsNone(dp.read_serving_digest(None))

    def test_the_pointer_digest_is_read(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'current.json').write_text(
                json.dumps({'directory': 'b', 'semantic_digest': 'd' * 24}))
            self.assertEqual(dp.read_serving_digest(tmp), 'd' * 24)

    def test_a_corrupt_pointer_reads_as_not_measured(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'current.json').write_text('{сломано')
            self.assertIsNone(dp.read_serving_digest(tmp))

    def test_serving_the_same_digest_yields_SKIP(self):
        self.assertEqual(dp.publish_verdict('e' * 24, 'e' * 24)[0], 'SKIP')

    def test_an_explicit_published_file_still_wins_over_the_serve_root(self):
        """Явно названный файл — сильнее умолчания: так проверяют чужую выкладку."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            pub = Path(tmp) / 'p.json'
            pub.write_text(json.dumps({'semantic_digest': 'f' * 24}))
            self.assertEqual(dp.read_published_digest(pub), 'f' * 24)


class EveryPrivateDirectoryIsCreated0700IncludingParents(unittest.TestCase):
    """Замер 20.09: девять рабочих каталогов оказались 0755.

    `Path.mkdir(parents=True, mode=0o700)` применяет режим только к ПОСЛЕДНЕМУ каталогу;
    промежуточные создаются по умолчанию. Внутри них лежит полная проекция владельца, то
    есть они читались бы любым пользователем машины. Тот же класс, что и с корнем раздачи.
    """

    def test_intermediate_directories_get_0700_too(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            deep = Path(tmp) / 'a' / 'b' / 'c'
            dp._private_mkdir(deep, parents=True)
            for d in (deep, deep.parent, deep.parent.parent):
                self.assertEqual(d.stat().st_mode & 0o777, 0o700, str(d))

    def test_an_existing_loose_directory_is_tightened(self):
        import tempfile
        import os as _os
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / 'loose'
            d.mkdir()
            _os.chmod(d, 0o755)
            dp._private_mkdir(d)
            self.assertEqual(d.stat().st_mode & 0o777, 0o700)

    def test_a_built_bundle_has_no_loose_directory_anywhere(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'snap'
            src.mkdir()
            (src / 'investment_snapshot.json').write_text('{"real_capital_proven": false}')
            out = Path(tmp) / 'deep' / 'work' / 'bundle-x'
            dp.build_bundle(bundle=src, output=out)
            loose = [str(d) for d in out.rglob('*') if d.is_dir()
                     and (d.stat().st_mode & 0o777) != 0o700]
            self.assertEqual(loose, [])
            self.assertEqual(out.stat().st_mode & 0o777, 0o700)
            self.assertEqual(out.parent.stat().st_mode & 0o777, 0o700)

    def test_an_activated_bundle_has_no_loose_directory(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / 'publish'
            src.mkdir()
            for name in dp.PUBLISHED_FILES:
                (src / name).write_text('x')
            root = Path(tmp) / 'studio-os-serve' / 'director'
            target = dp.activate(root, src, digest='a' * 24)
            for d in (root, root.parent, target):
                self.assertEqual(d.stat().st_mode & 0o777, 0o700, str(d))
